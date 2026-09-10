"""
fringe_detect.py -- fringe detection: FFT initial guess, Fisher g-test,
2-of-3 window corroboration, and the per-channel detect+notch pipeline.

Vendored from `defringe_dac.py` (DAC Absorption Fringe Analysis).
    Source module : defringe_dac.py
    Author        : Matthew R. Diamond
    Repository    : github.com/matthewrdiamond/DAC-Absorption-Fringe-Analysis
    License       : vendored under MIT by permission of the author.
    Upstream snapshot: commit 7988300 (2026-08-03)

Deliberate deviations from that snapshot, kept on purpose (hardening; every
other difference is a bug): drift #4 per-window rejection instead of hot-path
asserts, #8 point-count / finiteness gate on detection, #9 Fisher p-value
overflow guard, #10 the 20-point floor extended to the full and wide tiers,
#13 ValueError on a zero or negative notch half-width.

Contents (source line refs are into defringe_dac.py):
    fisher_g_pvalue      (:1262)  Fisher's exact periodicity test
    fft_initial_guess    (:1458)  divisive poly detrend + Hann + banded peak search
    corroborate_nt       (:17707) the 2-of-3 window agreement block, lifted out of
                                  compute_channel_fit into a testable function
    compute_channel_fit  (:17663) per-channel FFT -> corroboration -> notch -> fits

SPARTA divergences from the source (each deliberate, see the docstrings):
  1. `fisher_g_pvalue` carries SPARTA's overflow guard (`p_terms_max`).  The
     unpatched source evaluates the exact alternating sum for floor(1/g) terms,
     which for a near-flat periodogram is ~n terms; above roughly 1030 bins
     `scipy.special.comb(n, j, exact=True)` returns a Python int too large to
     convert to float and the sum raises OverflowError.  Weak periodicity is by
     definition not significant, so the guard returns p = 1.0 instead.
  2. `fft_initial_guess`'s bare `except Exception: pass` is replaced by narrow
     exception handling that reports the failure through `log`.
  3. No printing: diagnostics go to an optional `log=callable`.
  4. `compute_channel_fit` drops the source's out_dir / fig_dir / plotdata_dir
     side-effect parameters -- it computes and returns, it never writes.

Python 3.8 compatible; numpy + scipy + stdlib only (no pandas, no matplotlib).
"""

import numpy as np

# scipy.signal / scipy.special are imported inside the two functions that need
# them: the live workbench imports this module on every session open, and the
# fast path (run_fits=False, no Fisher sum) must not pay for them.
from fringe_config import DEFAULT_CONFIG, NM_TO_UM, make_logger
from fringe_notch import (band_integrated_amplitude, defringe_fft_notch,
                          notch_width_sweep)

# Exceptions that a numerically degenerate spectrum can legitimately raise out
# of the detection pipeline.  Anything else is a bug and propagates.
_DETECT_ERRORS = (ValueError, IndexError, ZeroDivisionError, FloatingPointError,
                  TypeError, OverflowError, np.linalg.LinAlgError)


def fisher_g_pvalue(periodogram, p_terms_max=None, cfg=None):
    """Fisher's exact test for periodicity in a periodogram.

    Parameters
    ----------
    periodogram : 1-D array
        Power spectral values P_k (must be > 0; typically |FFT|^2 or |FFT|).
    p_terms_max : int|None
        SPARTA overflow guard.  None -> cfg.fisher_p_terms_max (default 30).

    Returns
    -------
    g : float
        Fisher's g-statistic = max(P_k) / sum(P_k).
    pvalue : float
        Exact survival probability P(g > observed_g) under the null of white noise.
        Small p-value => significant periodicity.

    Reference: Fisher (1929); Wichert et al. (2004) Bioinformatics 20(1):5-20, eq. (6).

    SPARTA guard (divergence from the source): the exact alternating-sum form is
    only numerically stable for a small number of terms (a strong fringe: g large,
    p_terms 1-3).  A near-flat periodogram gives g ~ 1/n, so p_terms ~ n; that path
    both overflows comb(n, j) (above ~1030 bins the exact integer no longer converts
    to float) and loses all precision to cancellation.  Weak periodicity is by
    definition not significant, so this returns p = 1 (do not notch) rather than
    raising.  A degenerate periodogram (empty, all-zero, all-NaN) likewise scores
    p = 1 instead of raising.
    """
    cfg = DEFAULT_CONFIG if cfg is None else cfg
    p_terms_max = cfg.fisher_p_terms_max if p_terms_max is None else int(p_terms_max)
    P = np.asarray(periodogram, dtype=float)
    n = P.size
    if n < 2:
        return 1.0, 1.0
    total = float(P.sum())
    if not np.isfinite(total) or total <= 0:
        # an all-zero / all-NaN periodogram has no periodicity to test
        return 1.0, 1.0
    g = float(P.max() / total)
    if not np.isfinite(g) or g <= 0:
        return g, 1.0
    # Survival function: P(g > x) = sum_{j=1}^{floor(1/x)} (-1)^{j-1} C(n,j) (1-jx)^{n-1}
    p_terms = int(1.0 / g)            # floor(1/g)
    if p_terms > p_terms_max:
        return g, 1.0
    from scipy.special import comb
    pvalue = 0.0
    for j in range(1, p_terms + 1):
        term = (-1.0) ** (j - 1) * comb(n, j, exact=True) * (1.0 - j * g) ** (n - 1)
        pvalue += term
    pvalue = max(0.0, min(1.0, pvalue))   # clamp to [0, 1] for numerical safety
    return g, pvalue


def fft_initial_guess(wl_nm, intensity, cfg=None, log=None, label=''):
    """Estimate n*t (nm) via FFT of the raw signal in wavenumber space.

    Returns (nt_est, fft_info).
    nt_est is None when no confident fringe peak is found (SNR too low),
    signalling that fringe removal should be skipped for this signal.
    fft_info is always populated for diagnostic plots.

    The detrend is DIVISIVE (`sig_u / trend - 1`), which is the right form for
    raw counts carrying a multiplicative lamp envelope.  It is used ONLY for FFT
    peak-finding; the fits use a separate notch-baseline norm_u built later.

    SPARTA divergence: the source wraps the whole body in
    ``try: ... except Exception: pass``, which silently swallows real bugs.  Here
    only the numeric failure modes of a degenerate spectrum are caught, and each
    is reported through `log`.
    """
    cfg = DEFAULT_CONFIG if cfg is None else cfg
    emit = make_logger(log)
    fft_info = None

    wl_nm = np.asarray(wl_nm, dtype=float)
    intensity = np.asarray(intensity, dtype=float)
    if wl_nm.ndim != 1 or intensity.ndim != 1 or wl_nm.size != intensity.size:
        raise ValueError("fft_initial_guess: wl_nm and intensity must be 1-D and "
                         "the same length (got %s, %s)"
                         % (wl_nm.shape, intensity.shape))
    if wl_nm.size < cfg.min_detect_points:
        emit("%s fringe detect: only %d points (< %d) -- skipped"
             % (label, wl_nm.size, cfg.min_detect_points))
        return None, None
    if not (np.all(np.isfinite(wl_nm)) and np.all(wl_nm > 0)):
        emit("%s fringe detect: wavelength grid has non-finite or non-positive "
             "values -- skipped" % (label,))
        return None, None
    if not np.all(np.isfinite(intensity)):
        emit("%s fringe detect: intensity has non-finite values -- skipped"
             % (label,))
        return None, None

    # Resample to uniform wavenumber grid (1/lam, nm^-1)
    wn = 1.0 / wl_nm
    sort_idx = np.argsort(wn)
    wn_s = wn[sort_idx]
    sig_s = intensity[sort_idx]
    wn_u = np.linspace(wn_s[0], wn_s[-1], len(wn_s))
    sig_u = np.interp(wn_u, wn_s, sig_s)
    return fft_peak_on_uniform_grid(wn_u, sig_u, cfg=cfg, log=log, label=label)


def fft_peak_on_uniform_grid(wn_u, sig_u, cfg=None, log=None, label=''):
    """The FFT peak search of `fft_initial_guess`, on an ALREADY-uniform grid.

    Same return contract, (nt_est, fft_info).  Split out so a caller that has
    built the uniform wavenumber grid itself does not round-trip through 1/wn
    and pick up last-ulp differences.
    """
    from scipy.signal import find_peaks

    cfg = DEFAULT_CONFIG if cfg is None else cfg
    emit = make_logger(log)
    fft_info = None
    wn_u = np.asarray(wn_u, dtype=float)
    sig_u = np.asarray(sig_u, dtype=float)
    try:
        # Polynomial detrend to remove lamp envelope, then Hann window. This is the
        # DETREND-normalised fringe (signal / smooth 4th-order poly - 1), used ONLY for
        # FFT peak-finding; the fits use a separate notch-baseline norm_u built later.
        trend = np.polyval(np.polyfit(wn_u, sig_u, deg=cfg.detrend_poly_deg), wn_u)
        trend = np.maximum(trend, 0.01 * float(trend.max()))
        norm_u_detrend = sig_u / trend - 1              # (I-trend)/trend
        window = np.hanning(len(norm_u_detrend))
        sig_win = norm_u_detrend * window

        # FFT: fringe peak is at freq = 2*n*t  (nm)
        dw = wn_u[1] - wn_u[0]
        fft_complex = np.fft.rfft(sig_win)
        fft_amp = np.abs(fft_complex)
        freqs = np.fft.rfftfreq(len(sig_win), d=dw)

        # Search window: the configured physical n*t range
        freq_min = cfg.freq_min
        freq_max = cfg.freq_max
        valid = (freqs >= freq_min) & (freqs <= freq_max)
        if not valid.any():
            raise ValueError("no valid frequencies in physical range "
                             "(n*t %g-%g nm)" % (cfg.fringe_nt_min_nm,
                                                 cfg.fringe_nt_max_nm))

        # Find all prominent local maxima in the valid range, sorted by amplitude
        peaks, _ = find_peaks(fft_amp,
                              prominence=fft_amp[valid].max() * cfg.peak_prominence_frac)
        peaks_in_range = peaks[(freqs[peaks] >= freq_min) & (freqs[peaks] <= freq_max)]
        if len(peaks_in_range) > 0:
            order = np.argsort(fft_amp[peaks_in_range])[::-1]
            peaks_sorted = peaks_in_range[order]
            peak_idx = int(peaks_sorted[0])
        else:
            peaks_sorted = np.array([], dtype=int)
            peak_idx = int(np.argmax(np.where(valid, fft_amp, 0.0)))
        nt_est = freqs[peak_idx] / 2.0
        peak_phase = float(np.angle(fft_complex[peak_idx]))
        hann_sum = np.sum(window)
        peak_amp = 2.0 * fft_amp[peak_idx] / hann_sum

        fisher_g, fisher_pv = fisher_g_pvalue(fft_amp[valid] ** 2, cfg=cfg)
        fft_info = dict(wn_u=wn_u, norm_u_detrend=norm_u_detrend,
                        freqs=freqs, fft_amp=fft_amp,
                        fft_complex=fft_complex,
                        peak_idx=peak_idx, peaks_sorted=peaks_sorted,
                        nt_est=nt_est, peak_phase=peak_phase,
                        peak_amp=peak_amp,
                        fisher_g=fisher_g, fisher_pv=fisher_pv)

        if fisher_pv > cfg.fringe_pvalue_max:
            return None, fft_info

        return nt_est, fft_info
    except _DETECT_ERRORS as exc:
        emit("%s fringe detect failed (%s): %s"
             % (label, type(exc).__name__, exc))
        return None, fft_info


def corroborate_nt(windows, cfg=None, log=None, label=''):
    """2-of-3 cross-validation of the detected n*t across FFT windows.

    `windows` is an ordered sequence of (name, fft_info) pairs; the source uses
    ('narrow', 'wide', 'full').  A window "detects" the fringe when its Fisher
    p-value clears cfg.fringe_pvalue_max on its own range; the fringe is accepted
    when at least two windows detect it AND agree on n*t within cfg.nt_agree_tol
    (a RELATIVE fraction).  The fit runs in the narrow band, so a usable narrow
    fft_info is required to accept.

    Returns dict(nt, names, detections, accepted) where
      nt         - accepted fundamental n*t (nm) or None,
      names      - the corroborating window names (possibly empty),
      detections - [(name, nt_nm)] for every individually significant window,
      accepted   - bool.

    Lifted verbatim (logic-for-logic) out of the source's compute_channel_fit
    so it can be unit-tested without a spectrum.
    """
    cfg = DEFAULT_CONFIG if cfg is None else cfg
    emit = make_logger(log)
    windows = list(windows)
    by_name = dict(windows)
    narrow_info = by_name.get('narrow')

    detections = []   # (name, nt_nm) for windows individually clearing significance
    for wname, winfo in windows:
        if (winfo and winfo.get('nt_est') is not None
                and winfo.get('fisher_pv', 1.0) <= cfg.fringe_pvalue_max):
            detections.append((wname, float(winfo['nt_est'])))

    # Largest subset of detections that mutually agree on n*t.
    best_group = []
    for _, nti in detections:
        if nti == 0:
            continue
        grp = [d for d in detections if abs(d[1] - nti) / nti <= cfg.nt_agree_tol]
        if len(grp) > len(best_group):
            best_group = grp

    if len(best_group) >= 2 and narrow_info is not None:
        names = [g[0] for g in best_group]
        nt = (float(narrow_info['nt_est']) if 'narrow' in names
              else float(np.median([g[1] for g in best_group])))
        if 'narrow' not in names:
            npv = narrow_info.get('fisher_pv')
            nptxt = ("p=%.2g" % npv) if npv is not None else "n/a"
            emit("%s narrow FFT not in agreement (%s); fringe accepted via %s "
                 "(n*t~%.1f um)" % (label, nptxt, '+'.join(names), nt / 1000.0))
        elif len(names) < 3:
            emit("%s fringe corroborated by %s (n*t~%.1f um)"
                 % (label, '+'.join(names), nt / 1000.0))
        return dict(nt=nt, names=names, detections=detections, accepted=True)

    if len(best_group) >= 2 and narrow_info is None:
        emit("%s wide/full agree but narrow FFT unavailable -- cannot fit, "
             "rejecting fringe" % (label,))
    elif detections:
        detail = ", ".join("%s=%.1fum" % (n, t / 1000.0) for n, t in detections)
        emit("%s no 2-of-3 FFT agreement (%s) -- rejecting fringe" % (label, detail))
    return dict(nt=None, names=[], detections=detections, accepted=False)


def compute_channel_fit(wl, raw, cfg=None, label='', notch_centers_nm=None,
                        run_fits=True, raw_minus_dark=None, halfwidth_um=None,
                        notch_halfwidths_um=None, lowpass=False,
                        lp_cutoff_um=None, lp_rolloff_um=None,
                        method='lsq', log=None):
    """Per-channel FFT -> 2-of-3 cross-validation -> notch stage -> (optional) fits.

    Returns (fit, I_notch, nt, default_centers):
      fit             - the per-channel dict.  With `run_fits` it also carries the
                        tiered dispersion fits under fit['models']; without, it is
                        the fast partial dict carrying raw + the notch-stage
                        fft_info (enough to render raw + FFT/notch overlays).
      I_notch         - the FFT-notch defringed spectrum, consumed by the
                        corrected-absorbance step.  All-NaN when no mask ran:
                        no fringe was detected, so nothing was applied.
      nt              - accepted fundamental n*t (nm) or None.
      default_centers - [nt] (the fundamental) or [] -- the default notch list.

    NO FRINGE, NO MASK.  The whole notch stage is gated on the detection, the
    source's own gate: with no accepted n*t there is no notch AND no low-pass,
    I_notch stays all-NaN, fft_info carries no 'I_notch_1x' and default_centers
    is empty.  A channel the detector passed over is handed back exactly as it
    came in, which is what the source's batch and GUI both do with it.

    notch_centers_nm : once a fringe IS detected, the caller's own answer, three
                       states.  A LIST of n*t centers (nm) notches exactly those.
                       An EMPTY list notches nothing.  None means automatic: the
                       fundamental this call detected.  The low-pass is
                       independent of the LIST -- on is on, with or without
                       centres -- but not of the detection.  run_fits=False stops
                       after the notch stage (fast live path; no optimisers run,
                       a few ms).

    SPARTA divergence: the source signature carries out_dir / base_stem / fig_dir /
    plotdata_dir and writes figures and CSVs as a side effect.  This one is pure --
    it computes and returns.  Diagnostics go to `log`.
    """
    cfg = DEFAULT_CONFIG if cfg is None else cfg
    emit = make_logger(log)
    halfwidth_um = cfg.notch_halfwidth_um if halfwidth_um is None else halfwidth_um

    wl = np.asarray(wl, dtype=float)
    raw = np.asarray(raw, dtype=float)
    if wl.ndim != 1 or raw.ndim != 1 or wl.size != raw.size:
        raise ValueError("compute_channel_fit: wl and raw must be 1-D and the same "
                         "length (got %s, %s)" % (wl.shape, raw.shape))

    vis = (wl >= cfg.fit_wl_min_nm) & (wl <= cfg.fit_wl_max_nm)
    wl_local = wl[vis]
    wn_full = 1.0 / wl
    sidx = np.argsort(wn_full)

    norm_u_full = wn_u_full = sig_u_full = None
    I_notch = np.full_like(raw, np.nan)
    default_centers = []

    nt, fft_info = fft_initial_guess(wl_local, raw[vis], cfg=cfg, log=log,
                                     label=label)

    # Additional FFTs on wide and full ranges (diagnostic + cross-validation)
    wl_wide_lo, wl_wide_hi = 1.0 / cfg.wide_hi, 1.0 / cfg.wide_lo
    wide_vis = (wl >= wl_wide_lo) & (wl <= wl_wide_hi)
    nt_wide, fft_info_wide = fft_initial_guess(wl[wide_vis], raw[wide_vis],
                                               cfg=cfg, log=log, label=label)
    nt_full, fft_info_full = fft_initial_guess(wl, raw, cfg=cfg, log=log, label=label)
    if fft_info is not None:
        fft_info['fft_wide'] = fft_info_wide
        fft_info['fft_full'] = fft_info_full

    corr = corroborate_nt([('narrow', fft_info), ('wide', fft_info_wide),
                           ('full', fft_info_full)], cfg=cfg, log=log, label=label)
    nt = corr['nt']
    if nt is not None and fft_info is not None:
        fft_info['nt_est'] = nt
        fft_info['corroborated_by'] = list(corr['names'])
    if nt is not None:
        default_centers = [float(nt)]   # fundamental only

    if fft_info is not None:
        wn_u_full = np.linspace(wn_full[sidx[0]], wn_full[sidx[-1]], len(wl))
        sig_u_full = np.interp(wn_u_full, wn_full[sidx], raw[sidx])
        trend_u_full = np.polyval(
            np.polyfit(wn_u_full, sig_u_full, cfg.detrend_poly_deg), wn_u_full)
        trend_u_full = np.maximum(trend_u_full, 0.01 * float(trend_u_full.max()))

        # Notch-filter normalization (all methods use this).
        # THE WHOLE STAGE IS GATED ON THE DETECTION, the source's own gate
        # (defringe_dac.py:17752).  No accepted n*t means no notch and no
        # low-pass: the channel is handed back untouched, I_notch stays all-NaN
        # and no cleaned curve exists to draw or to report a thickness for.
        # Once a fringe IS detected the notch list keeps its three states --
        # named centres, [] for none, None for the detected fundamental -- and
        # the low-pass is independent of the LIST, so an empty list with the
        # low-pass on is a low-pass alone.
        if nt is not None:
            I_notch, _, sig_filtered_wn = defringe_fft_notch(
                wn_u_full, sig_u_full, wl, raw, nt,
                halfwidth_um=halfwidth_um, notch_centers_nm=notch_centers_nm,
                notch_halfwidths_um=notch_halfwidths_um,
                lowpass=lowpass, lp_cutoff_um=lp_cutoff_um,
                lp_rolloff_um=lp_rolloff_um, cfg=cfg)
            # Stash the notch-cleaned spectrum (on the wl grid, WITH the low-pass applied)
            # so the workbench Row-0 can draw it directly -- no need to run/select from the
            # width sweep. (Key keeps the historical '_1x' suffix; it's the single actual
            # result, no sweep factor.)
            fft_info['I_notch_1x'] = I_notch
            # Baseline for the fit's norm_u is the notch-filtered signal (raw with the
            # notched peaks removed) -- the original pre-GUI design. Folding the notched
            # peaks back into norm_u IS intended: the current notch list (fundamental +
            # manual notches) thus feeds the fits, restoring the interactive-notch -> fit
            # link. trend_u_full remains the polynomial detrend used ONLY by
            # fft_initial_guess for FFT peak-finding.
            notch_baseline = np.clip(sig_filtered_wn, 1e-6, None)
            norm_u_full = (sig_u_full - notch_baseline) / notch_baseline
            fft_info['wn_u_full'] = wn_u_full
            fft_info['sig_u_full'] = sig_u_full
            fft_info['norm_u_full'] = norm_u_full
            fft_info['trend_u_full'] = trend_u_full
            fft_info['notch_baseline'] = notch_baseline

        # Everything below reads the fundamental: the band amplitude, the width
        # sweep and the notch-refined peak are all measurements OF it.
        if nt is not None:
            # Band-integrated (spread-aware) amplitude -- DIAGNOSTIC only; reported n is
            # unchanged. Integrates the fundamental-band FFT power over the fundamental's
            # absolute um +-reach. Operates on the SAME notch-baseline norm_u_full the fits
            # use, so V_band vs the fitted V is a fair same-signal spread comparison. The
            # notch's Gaussian shaping gives band-int a small (~2%) negative bias here --
            # acceptable for a diagnostic.
            _fund_hw = halfwidth_um
            if notch_centers_nm is not None and notch_halfwidths_um is not None:
                for _bc, _bw in zip(notch_centers_nm, notch_halfwidths_um):
                    if round(float(_bc), 1) == round(float(nt), 1):
                        _fund_hw = float(_bw)
                        break
            _V_band = band_integrated_amplitude(wn_u_full, norm_u_full, nt,
                                                halfwidth_um=_fund_hw, cfg=cfg)
            # NARROW window (fit_wl_min..max) -- matches the workbench measured FFT.
            _narrow_m = ((wn_u_full >= 1.0 / cfg.fit_wl_max_nm)
                         & (wn_u_full <= 1.0 / cfg.fit_wl_min_nm))
            _V_band_narrow = (band_integrated_amplitude(
                wn_u_full[_narrow_m], norm_u_full[_narrow_m], nt,
                halfwidth_um=_fund_hw, cfg=cfg)
                if int(_narrow_m.sum()) >= cfg.min_detect_points else _V_band)
            # TRUE FINE window (cfg.fine_wn_lo..hi) -- matches the Row-0 fine I_clean tier.
            _finew_m = (wn_u_full >= cfg.fine_wn_lo) & (wn_u_full <= cfg.fine_wn_hi)
            _V_band_fine = (band_integrated_amplitude(
                wn_u_full[_finew_m], norm_u_full[_finew_m], nt,
                halfwidth_um=_fund_hw, cfg=cfg)
                if int(_finew_m.sum()) >= cfg.min_detect_points else _V_band_narrow)
            fft_info['band_amp'] = dict(V_band=_V_band, V_band_narrow=_V_band_narrow,
                                        V_band_fine=_V_band_fine, nt=nt)
            fft_info['band_halfwidth_um'] = _fund_hw   # band_integral MSV model reads this

            # Notch width sweep (dispersion diagnostic) -- cascade of FACTORS around the
            # effective per-peak half-widths. Gated on run_fits, the cheapest gate that
            # covers every drawing path yet skips this ~5x defringe on every live update.
            # An empty centre list is a decision -- notch nothing -- so there is
            # no width to sweep and the 5x defringe is skipped outright.
            if run_fits and (notch_centers_nm is None or len(notch_centers_nm)):
                _eff_centers = (notch_centers_nm if notch_centers_nm is not None
                                else [nt])
                _eff_widths = (notch_halfwidths_um if notch_halfwidths_um is not None
                               else [halfwidth_um] * len(_eff_centers))
                fft_info['notch_sweep'] = notch_width_sweep(
                    wn_u_full, sig_u_full, nt, wl=wl, raw=raw,
                    notch_centers_nm=_eff_centers,
                    notch_halfwidths_um=_eff_widths, cfg=cfg)

            # Notch-refined FFT: FFT on notch-normalized signal for refined n*t
            _nr_S = np.fft.rfft(norm_u_full)
            _nr_freqs = np.fft.rfftfreq(len(norm_u_full),
                                        d=np.median(np.abs(np.diff(wn_u_full))))
            _nr_amp = np.abs(_nr_S) * 2.0 / len(norm_u_full)
            _nr_f_expect = 2.0 * nt
            _nr_mask = ((_nr_freqs > _nr_f_expect * 0.5)
                        & (_nr_freqs < _nr_f_expect * 1.5))
            if np.any(_nr_mask):
                _nr_idx_masked = np.argmax(_nr_amp[_nr_mask])
                _nr_idx = np.where(_nr_mask)[0][_nr_idx_masked]
                _nr_nt = _nr_freqs[_nr_idx] / 2.0
                _nr_amp_val = float(_nr_amp[_nr_idx]) * float(np.mean(notch_baseline))
                _nr_phase = float(np.angle(_nr_S[_nr_idx]))
            else:
                _nr_nt = nt
                _nr_amp_val = float(fft_info.get('peak_amp', 0))
                _nr_phase = fft_info.get('peak_phase', 0.0)

            fft_info['notch_refined_nt'] = _nr_nt
            fft_info['notch_refined_amp'] = _nr_amp_val
            fft_info['notch_refined_phase'] = _nr_phase

        # Note: fft_info['norm_u_detrend'] is kept as-is from fft_initial_guess
        # (polynomial detrend, peak-finding only). The fits' notch-baseline norm_u
        # is built separately.

        if nt is not None:
            # Trim fft_info to the narrow fit window
            wn_fit_lo = 1.0 / cfg.fit_wl_max_nm
            wn_fit_hi = 1.0 / cfg.fit_wl_min_nm
            fft_info['wn_fit_lo'] = wn_fit_lo
            fft_info['wn_fit_hi'] = wn_fit_hi
            cw_mask = ((fft_info['wn_u'] >= wn_fit_lo)
                       & (fft_info['wn_u'] <= wn_fit_hi))
            fft_info['wn_u'] = fft_info['wn_u'][cw_mask]
            fft_info['norm_u_detrend'] = fft_info['norm_u_detrend'][cw_mask]
            emit("%s FFT window: %.0f-%.0f cm^-1 (%d pts)"
                 % (label, wn_fit_lo * 1e7, wn_fit_hi * 1e7, int(cw_mask.sum())))

    if nt is None:
        pv = fft_info['fisher_pv'] if fft_info and 'fisher_pv' in fft_info else 1.0
        emit("%s no fringe detected (p=%.2g > %g)"
             % (label, pv, cfg.fringe_pvalue_max))
        fit = dict(raw=raw, fft_info=fft_info, no_fringe=True,
                   raw_minus_dark=raw_minus_dark, models={})
        # No fundamental, so no fits and no mask: nothing the caller named --
        # centres, a low-pass, or both -- was applied, I_notch is all-NaN and
        # fft_info carries no 'I_notch_1x'.  The channel is untouched.
        return fit, I_notch, None, default_centers

    if not run_fits:
        fit = dict(raw=raw, fft_info=fft_info, no_fringe=False,
                   raw_minus_dark=raw_minus_dark, models={})
        return fit, I_notch, nt, default_centers

    # Imported lazily: the fast path (run_fits=False) never needs the optimisers.
    from fringe_fit import run_window_fits
    try:
        # `wl` is the source's `wl`: the full ORIGINAL detector wavelength grid.
        # Every tier's n_mean / nt_um averages n(lam) over it (source :16097).
        models = run_window_fits(fft_info, norm_u_full, wn_u_full, cfg=cfg,
                                 label=label, log=log, method=method,
                                 wl_full=wl)
    except _DETECT_ERRORS as exc:
        emit("%s %s fit failed (%s): %s"
             % (label, method, type(exc).__name__, exc))
        fit = dict(raw=raw, fft_info=fft_info, no_fringe=True,
                   raw_minus_dark=raw_minus_dark, models={})
        return fit, np.full_like(raw, np.nan), nt, default_centers

    fit = dict(raw=raw, fft_info=fft_info, no_fringe=False,
               raw_minus_dark=raw_minus_dark, models=models, nt=nt,
               nt_um=float(nt) * NM_TO_UM)
    return fit, I_notch, nt, default_centers


__all__ = ['fisher_g_pvalue', 'fft_initial_guess', 'corroborate_nt',
           'compute_channel_fit']
