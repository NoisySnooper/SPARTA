"""
fringe_notch.py -- Fourier-space notch defringing and band diagnostics.

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
    defringe_fft_notch        (:6479)  multi-centre Gaussian notch + optional low-pass
    notch_width_sweep         (:6568)  residual fringe power vs notch width
    band_integrated_amplitude (:6653)  spread-aware fringe amplitude V
    lowpass_keep              (:6547)  the low-pass edge, ONE definition
    removed_profile_um        (:13570) the same mask read on the n*t um axis

Notch-width convention (source, verbatim intent): half-widths are ABSOLUTE
n*t um (+-reach), NOT a fraction of the centre frequency.  Because the n*t axis
is freqs/2000, a +-hw um band is a +-2000*hw frequency band, so the Gaussian
sigma is sigma_f = 2000*halfwidth_um at EVERY centre -- matching real FFT fringe
peaks, whose width is roughly constant across n*t.

SPARTA adaptations
  * Defaults arrive from a frozen FringeConfig instead of module globals
    (NOTCH_HALFWIDTH_UM, LP_ROLLOFF_UM, BAND_RES_FLOOR).
  * The low-pass edge is `lowpass_keep`, one function used by BOTH the mask
    that is applied to the spectrum and the preview curve the workbench
    draws.  The source spells the same tanh twice (:6547 and :13591), so the
    two could drift; here a shape or a width can only change in one place.
    Shape 'tanh' at roll-off 2.0 um is the source's own edge, verbatim.
  * No printing (optional `log=callable`), no import side effects.
  * Input validation with named errors (see the QoL notes on each function).
  * Python 3.8 compatible; numpy + stdlib only.
"""

import numpy as np

from fringe_config import (DEFAULT_CONFIG, DEFAULT_LP_EDGE_SHAPE,
                           LP_EDGE_SHAPES, make_logger)

# The n*t (um) axis is freqs/2000, so a half-width of hw um maps to a frequency
# half-width of 2000*hw.  Named once instead of the source's repeated literal.
_UM_TO_FREQ = 2000.0

# The roll-off width may not be zero: it divides.  The source's own guard.
_ROLL_FLOOR = 1e-9


def _erf(x):
    """Vectorised error function, without a hard SciPy dependency.

    SciPy is optional in this tree (the vendored core is numpy + stdlib), so
    the fast path is used when it is installed and `math.erf` covers the rest.
    """
    try:
        from scipy.special import erf as _sp_erf
    except Exception:
        import math
        return np.array([math.erf(float(v)) for v in np.ravel(x)],
                        dtype=float).reshape(np.shape(x))
    return _sp_erf(x)


def lowpass_keep(x, cutoff, rolloff=None, shape=None, cfg=None):
    """The low-pass KEEP factor of the notch mask, on any linear axis.

    One definition, used by the mask that is applied to the spectrum
    (`defringe_fft_notch`) and by the preview curve the workbench draws
    (`removed_profile_um`).  `x`, `cutoff` and `rolloff` must share a unit;
    the n*t um axis is frequency/2000, so the same call serves both spaces.

    Shapes (`shape`, None -> ``cfg.lp_edge_shape``):
      'tanh'  0.5 * (1 - tanh((x - cutoff) / r))   the source's edge, verbatim
      'erf'   0.5 * (1 - erf((x - cutoff) / r))    the Gaussian-integral edge
      'hard'  1 below the cutoff, 0 above it       a plain step

    `rolloff` (None -> ``cfg.lp_rolloff_um``) is the same width parameter for
    tanh and erf: at one r past the cutoff, tanh keeps 0.119 and erf 0.079.
    'hard' ignores it.  Returns an array shaped like `x`.
    """
    cfg = DEFAULT_CONFIG if cfg is None else cfg
    shape = cfg.lp_edge_shape if shape is None else str(shape)
    if shape not in LP_EDGE_SHAPES:
        raise ValueError("lowpass_keep: shape must be one of %s (got %r)"
                         % (', '.join(LP_EDGE_SHAPES), shape))
    x = np.asarray(x, float)
    cutoff = float(cutoff)
    if shape == 'hard':
        return np.where(x <= cutoff, 1.0, 0.0)
    roll = cfg.lp_rolloff_um if rolloff is None else rolloff
    r = max(float(roll), _ROLL_FLOOR)
    if shape == 'erf':
        return 0.5 * (1.0 - _erf((x - cutoff) / r))
    return 0.5 * (1.0 - np.tanh((x - cutoff) / r))


def _check_grid(wn_u, sig_u, who):
    """Shared validation for the uniform-wavenumber inputs (SPARTA addition).

    The source module indexes straight into these arrays; a length mismatch or
    a 1-point grid surfaces as an opaque IndexError or a divide-by-zero deep in
    the FFT.  Failing here names the caller and the offending shapes.
    """
    wn_u = np.asarray(wn_u, float)
    sig_u = np.asarray(sig_u, float)
    if wn_u.ndim != 1 or sig_u.ndim != 1:
        raise ValueError("%s: wn_u and sig_u must be 1-D (got %dD, %dD)"
                         % (who, wn_u.ndim, sig_u.ndim))
    if wn_u.size != sig_u.size:
        raise ValueError("%s: wn_u and sig_u length mismatch (%d vs %d)"
                         % (who, wn_u.size, sig_u.size))
    if wn_u.size < 4:
        raise ValueError("%s: need at least 4 points on the uniform grid (got %d)"
                         % (who, wn_u.size))
    dw = float(np.median(np.abs(np.diff(wn_u))))
    if not np.isfinite(dw) or dw <= 0.0:
        raise ValueError("%s: uniform wavenumber grid has non-positive spacing "
                         "(median |dwn| = %r)" % (who, dw))
    return wn_u, sig_u, dw


def _mirror_pad(sig_u):
    """Mirror-pad to make the signal periodic (avoids spectral leakage at edges).

    Returns (sig_padded, pad, N, N_pad) -- verbatim from the source's inline
    padding block, factored out because three functions repeat it.
    """
    N = len(sig_u)
    pad = N // 2
    sig_padded = np.concatenate([sig_u[pad:0:-1], sig_u, sig_u[-2:-pad - 2:-1]])
    return sig_padded, pad, N, len(sig_padded)


def _gaussian_notch_mask(freqs, centers_nm, halfwidths_um, default_halfwidth_um):
    """Product of Gaussian notches at f = 2*n*t for each centre (n*t in nm).

    Half-widths are absolute n*t um, so sigma_f = 2000*hw at every centre.
    An empty centre list is a mask of ones: nothing is notched.
    """
    notch = np.ones_like(freqs)
    for idx, c in enumerate(centers_nm):
        fc = 2.0 * float(c)
        if fc <= 0.0:
            continue
        hw = (halfwidths_um[idx] if (halfwidths_um is not None
                                     and idx < len(halfwidths_um))
              else default_halfwidth_um)
        hw = float(hw)
        if hw <= 0.0:
            raise ValueError("notch half-width must be > 0 um (centre %g nm "
                             "got %r)" % (fc / 2.0, hw))
        sigma_f = _UM_TO_FREQ * hw
        notch *= 1.0 - np.exp(-0.5 * ((freqs - fc) / sigma_f) ** 2)
    return notch


def defringe_fft_notch(wn_u, sig_u, wl, raw, nt_fft_nm, halfwidth_um=None,
                       notch_centers_nm=None, notch_halfwidths_um=None,
                       lowpass=False, lp_cutoff_um=None, lp_rolloff_um=None,
                       cfg=None, lp_edge_shape=None):
    """Defringe by zeroing the fringe peak in Fourier space.

    Works on the uniform-wn signal: FFT, apply Gaussian notch at the fringe
    frequency (and its mirror), inverse FFT.  The correction is then mapped
    back to the wavelength grid.

    Parameters
    ----------
    wn_u : 1-d array   - uniform wavenumber grid
    sig_u : 1-d array  - signal on that grid (raw interpolated)
    wl : 1-d array     - original wavelength grid
    raw : 1-d array    - original signal on wl grid
    nt_fft_nm : float  - n*t from FFT peak (nm); fringe freq = 2*nt
    halfwidth_um : float - notch HALF-width (+-reach) in n*t um (absolute,
                         position-independent).  The Gaussian sigma in freq units is
                         sigma_f = 2000*halfwidth_um (the n*t axis is freqs/2000, so a
                         +-hw um band = a +-2000*hw freq band -> +-1 sigma = +-hw um).
                         None -> cfg.notch_halfwidth_um.
    notch_centers_nm : list|None - the caller's own answer, three states.
                         A LIST of n*t centers (nm) notches exactly those, each at
                         f = 2*n*t, and `nt_fft_nm` is then not consulted at all.
                         An EMPTY list notches nothing, so the mask is the low-pass
                         alone.  None means automatic: notch the detected
                         fundamental at `nt_fft_nm`.
    notch_halfwidths_um : list|None - per-centre half-widths in n*t um, parallel to
                         notch_centers_nm; missing entries fall back to halfwidth_um.
    lowpass, lp_cutoff_um, lp_rolloff_um : optional soft high-cut ON TOP of the notches - a
                         single soft-edge mask multiplied into the same rfft mask,
                         cutoff/rolloff in n*t um.
    lp_edge_shape : str|None - the low-pass edge: 'tanh' (the source's own),
                         'erf' or 'hard'.  None -> cfg.lp_edge_shape.
    cfg : FringeConfig|None - supplies the defaults above.

    Returns (I_clean_wl, nt_est, sig_filtered_wn)
      nt_est is the notch centre this ran at, or None on the explicit-list path.
      sig_filtered_wn is the notch-filtered signal on the wn grid (~ I_laun).
    """
    cfg = DEFAULT_CONFIG if cfg is None else cfg
    halfwidth_um = cfg.notch_halfwidth_um if halfwidth_um is None else halfwidth_um
    wn_u, sig_u, dw = _check_grid(wn_u, sig_u, 'defringe_fft_notch')
    wl = np.asarray(wl, float)
    raw = np.asarray(raw, float)
    if wl.size != raw.size:
        raise ValueError("defringe_fft_notch: wl and raw length mismatch (%d vs %d)"
                         % (wl.size, raw.size))
    explicit = notch_centers_nm is not None
    if not explicit and (nt_fft_nm is None or not np.isfinite(nt_fft_nm)
                         or float(nt_fft_nm) <= 0.0):
        # Only the automatic path reads the fundamental, so only it needs one.
        raise ValueError("defringe_fft_notch: nt_fft_nm must be a positive, finite "
                         "n*t in nm (got %r)" % (nt_fft_nm,))

    # fringe frequency in wn^-1 space (automatic path only)
    f_center = None if explicit else 2.0 * float(nt_fft_nm)

    sig_padded, pad, N, N_pad = _mirror_pad(sig_u)
    S = np.fft.rfft(sig_padded)
    freqs = np.fft.rfftfreq(N_pad, d=dw)

    # Gaussian notch(es): attenuate around the fringe frequency.
    # An explicit center list (n*t in nm) notches exactly those centers (each f = 2*n*t),
    # and an EMPTY one notches nothing; only None falls back to the fundamental at
    # f_center. Half-widths are ABSOLUTE (um +-reach), so sigma_f = 2000*halfwidth_um
    # (-> +-1 sigma = +-hw um) is the same at every centre regardless of position --
    # matching real FFT fringe peaks, whose width is ~constant across n*t.
    centers = notch_centers_nm if explicit else [float(nt_fft_nm)]
    widths = notch_halfwidths_um if explicit else None
    notch = _gaussian_notch_mask(freqs, centers, widths, halfwidth_um)

    # Optional soft low-pass composed into the same mask (applied once). A soft edge, not a hard
    # cut, so the mirror-padded irfft doesn't ring. cutoff/rolloff are n*t um -> freq via *2000.
    # `lowpass_keep` is the one definition of that edge; the workbench's preview curve reads the
    # same function on the um axis, so what is drawn is what is applied.
    if lowpass and lp_cutoff_um and lp_cutoff_um > 0:
        f_cut = _UM_TO_FREQ * float(lp_cutoff_um)
        roll = _UM_TO_FREQ * float(lp_rolloff_um or cfg.lp_rolloff_um)
        notch = notch * lowpass_keep(freqs, f_cut, roll, lp_edge_shape,
                                     cfg=cfg)

    sig_filtered_padded = np.fft.irfft(S * notch, n=N_pad)

    # Trim padding to recover filtered signal on original grid
    sig_filtered = sig_filtered_padded[pad:pad + N]

    # The removed component (fringe) on the wn grid
    fringe_wn = sig_u - sig_filtered

    # Map fringe correction to wavelength grid
    wn_wl = 1.0 / wl
    fringe_on_wl = np.interp(wn_wl, wn_u, fringe_wn)
    I_clean = raw - fringe_on_wl

    # Estimate n*t from the notch centre (the explicit path never had one)
    nt_est = None if f_center is None else f_center / 2.0

    return I_clean, nt_est, sig_filtered


def notch_width_sweep(wn_u, sig_u, nt_fft_nm, wl=None, raw=None, halfwidth_ums=None,
                      notch_centers_nm=None, notch_halfwidths_um=None, factors=None,
                      cfg=None):
    """Sweep notch width and measure residual fringe power.

    Two modes (half-widths are ABSOLUTE n*t um +-reach -> sigma_f = 2000*halfwidth):
      * Cascade (notch_centers_nm AND notch_halfwidths_um given): sweep `factors` and notch
        each centre i at half-width notch_halfwidths_um[i]*factor.  factor=1.0 reproduces the
        chosen per-peak widths, so the 1x curve == the actual notch result.
      * Absolute (default): sweep `halfwidth_ums` (um +-reach), notching the fundamental.

    Returns dict: width_fracs (the swept values -- factors in cascade mode), residual_power,
    labels (per-curve tag, 'x' in cascade else '+-um'), factors (cascade only), and I_clean_wl
    (if wl/raw given).  A sharp drop with width => narrowband (constant n); gradual => dispersive.
    """
    cfg = DEFAULT_CONFIG if cfg is None else cfg
    wn_u, sig_u, dw = _check_grid(wn_u, sig_u, 'notch_width_sweep')
    if nt_fft_nm is None or not np.isfinite(nt_fft_nm) or float(nt_fft_nm) <= 0.0:
        raise ValueError("notch_width_sweep: nt_fft_nm must be a positive, finite "
                         "n*t in nm (got %r)" % (nt_fft_nm,))

    cascade = (notch_centers_nm is not None and notch_halfwidths_um is not None)
    if cascade:
        if len(notch_halfwidths_um) != len(notch_centers_nm):
            # SPARTA addition: the source indexes notch_halfwidths_um[idx] blind,
            # so a short list raises IndexError from inside the FFT loop.
            raise ValueError("notch_width_sweep: notch_halfwidths_um has %d entries "
                             "for %d centres -- they must be parallel"
                             % (len(notch_halfwidths_um), len(notch_centers_nm)))
        sweep_vals = np.asarray([0.2, 0.4, 0.6, 0.8, 1.0]
                                if factors is None else factors, dtype=float)
    else:
        sweep_vals = np.asarray([1.0, 2.0, 3.0, 4.0, 5.0, 6.0, 8.0, 10.0]
                                if halfwidth_ums is None else halfwidth_ums, dtype=float)
    if sweep_vals.size == 0:
        raise ValueError("notch_width_sweep: empty sweep (factors/halfwidth_ums)")

    f_center = 2.0 * float(nt_fft_nm)

    # Mirror-pad once (reused for all curves)
    sig_padded, pad, N, N_pad = _mirror_pad(sig_u)
    S = np.fft.rfft(sig_padded)
    freqs = np.fft.rfftfreq(N_pad, d=dw)

    # Frequency grid for the unpadded signal (used to measure residuals)
    freqs_orig = np.fft.rfftfreq(N, d=dw)
    band_mask = (freqs_orig > f_center * 0.8) & (freqs_orig < f_center * 1.2)

    has_wl = wl is not None and raw is not None
    if has_wl:
        wl = np.asarray(wl, float)
        raw = np.asarray(raw, float)
        if wl.size != raw.size:
            raise ValueError("notch_width_sweep: wl and raw length mismatch (%d vs %d)"
                             % (wl.size, raw.size))
    wn_wl = 1.0 / wl if wl is not None else None
    I_clean_wl = np.empty((len(sweep_vals), len(wl))) if has_wl else None

    residual_power = np.empty(len(sweep_vals))
    for i, v in enumerate(sweep_vals):
        if cascade:
            widths = [float(w) * float(v) for w in notch_halfwidths_um]
            notch = _gaussian_notch_mask(freqs, notch_centers_nm, widths, float(v))
        elif notch_centers_nm is not None:
            notch = _gaussian_notch_mask(freqs, notch_centers_nm, None, float(v))
        else:
            notch = _gaussian_notch_mask(freqs, [float(nt_fft_nm)], None, float(v))
        S_filt = S * notch
        sig_filt_padded = np.fft.irfft(S_filt, n=N_pad)
        sig_filt = sig_filt_padded[pad:pad + N]

        # FFT of filtered signal to measure residual power in fringe band
        S_resid = np.fft.rfft(sig_filt)
        residual_power[i] = np.sum(np.abs(S_resid[band_mask]) ** 2)

        # Map fringe correction to wavelength grid
        if has_wl:
            fringe_wn = sig_u - sig_filt
            fringe_on_wl = np.interp(wn_wl, wn_u, fringe_wn)
            I_clean_wl[i] = raw - fringe_on_wl

    labels = (['%gx' % v for v in sweep_vals] if cascade
              else ['+-%g um' % v for v in sweep_vals])
    result = dict(width_fracs=sweep_vals, residual_power=residual_power, labels=labels)
    if cascade:
        result['factors'] = sweep_vals
    if I_clean_wl is not None:
        result['I_clean_wl'] = I_clean_wl
    return result


def band_integrated_amplitude(wn_u, norm_u, nt, halfwidth_um=None,
                              res_floor=None, cfg=None):
    """Spread-aware fringe amplitude V by integrating the fundamental-band power.

    The single-cosine LSQ fit under-reads V when the fundamental's energy is spread
    over sigma in n*t (chirp/dispersion). This integrates *all* the band energy instead:
        V = sqrt( sum_band |FFT(hann*norm_u)|^2 / K )
    calibrated against a windowed unit cosine K (which cancels the window mean-square
    <w^2> and all FFT/grid constants -- no hand-derived factor). No noise-floor
    subtraction: measured moot (in-band peak/floor SNR ~65; skipping it costs <1% in V).

    The band is centred at f1 = 2*nt with absolute freq half-width 2000*halfwidth_um
    (halfwidth_um is the n*t um +-reach; +-hw um -> freq half-width 2000*hw) -- i.e. the
    *identical* window the notch removes (`defringe_fft_notch`) and the GUI shades.

    res_floor (None -> cfg.band_res_floor): floor the band half-width at the Hann
    main-lobe width (~2 bins = 2/(N*dw)). A short window (e.g. the fine 700-900 nm range)
    has coarse FFT resolution, so a narrow band can be narrower than the main lobe and *clip*
    the peak -> V under-read. Flooring removes that instrumental bias; the climb that
    remains as halfwidth_um grows past the floor is genuine spread.
    """
    cfg = DEFAULT_CONFIG if cfg is None else cfg
    halfwidth_um = cfg.notch_halfwidth_um if halfwidth_um is None else halfwidth_um
    norm_u = np.asarray(norm_u, dtype=float)
    wn_u = np.asarray(wn_u, dtype=float)
    if wn_u.size != norm_u.size:
        raise ValueError("band_integrated_amplitude: wn_u and norm_u length "
                         "mismatch (%d vs %d)" % (wn_u.size, norm_u.size))
    N = len(norm_u)
    if N < 8 or nt is None or float(nt) <= 0.0:
        return 0.0
    dw = float(np.median(np.abs(np.diff(wn_u))))
    if not np.isfinite(dw) or dw <= 0.0:
        return 0.0
    f1 = 2.0 * float(nt)
    half = _UM_TO_FREQ * float(halfwidth_um)
    if (cfg.band_res_floor if res_floor is None else res_floor):
        half = max(half, 2.0 / (N * dw))   # never narrower than the Hann main lobe (~2 bins)
    w = np.hanning(N)
    freqs = np.fft.rfftfreq(N, d=dw)
    X = np.fft.rfft(norm_u * w)
    ref = np.fft.rfft(np.cos(2.0 * np.pi * f1 * wn_u) * w)   # unit-amplitude calibrator
    K = float(np.sum(np.abs(ref) ** 2))
    if K <= 0.0:
        return 0.0
    band = (freqs >= f1 - half) & (freqs <= f1 + half)
    if int(band.sum()) < 1:
        return 0.0
    return float(np.sqrt(np.sum(np.abs(X[band]) ** 2) / K))


def removed_profile_um(x_um, centers_um=None, halfwidths_um=None,
                       lowpass=False, lp_cutoff_um=None, lp_rolloff_um=None,
                       lp_edge_shape=None, cfg=None):
    """The mask's REMOVED fraction over an n*t um grid (source `_removed_fraction`, :13570).

    ``1 - (prod notch_keep) * lowpass_keep``, i.e. exactly the mask
    `defringe_fft_notch` multiplies into the rfft, read on the axis the panel
    plots.  0 means kept, 1 means fully removed.

    The two spaces agree by construction, not by copying: the x axis is
    frequency/2000 and each notch's sigma_f is 2000*hw, so in um the Gaussian's
    sigma IS its +-reach `hw` and its centre IS the centre in um.  The low-pass
    half comes from :func:`lowpass_keep`, the same function the mask calls.

    `centers_um` are n*t centres in um (not nm), parallel to `halfwidths_um`;
    a missing width falls back to ``cfg.notch_halfwidth_um``.
    """
    cfg = DEFAULT_CONFIG if cfg is None else cfg
    x = np.asarray(x_um, float)
    keep = np.ones_like(x)
    centers_um = [] if centers_um is None else list(centers_um)
    for idx, c in enumerate(centers_um):
        hw = (halfwidths_um[idx] if (halfwidths_um is not None
                                     and idx < len(halfwidths_um))
              else cfg.notch_halfwidth_um)
        hw = float(hw)
        if hw <= 0.0:
            raise ValueError("removed_profile_um: notch half-width must be "
                             "> 0 um (centre %g um got %r)" % (float(c), hw))
        keep = keep * (1.0 - np.exp(-0.5 * ((x - float(c)) / hw) ** 2))
    if lowpass and lp_cutoff_um and float(lp_cutoff_um) > 0:
        keep = keep * lowpass_keep(x, float(lp_cutoff_um), lp_rolloff_um,
                                   lp_edge_shape, cfg=cfg)
    return 1.0 - keep


def removed_fraction(sig_u, sig_filtered):
    """Fraction of the signal's variance removed by the notch (SPARTA helper).

    A cheap, unit-free QC number for the workbench readout: 0 means the notch
    was a no-op, 1 means the whole modulation was removed.  Not present in the
    source module (which computes the equivalent inline for its twin axis).
    """
    sig_u = np.asarray(sig_u, float)
    sig_filtered = np.asarray(sig_filtered, float)
    if sig_u.size != sig_filtered.size:
        raise ValueError("removed_fraction: length mismatch (%d vs %d)"
                         % (sig_u.size, sig_filtered.size))
    var_in = float(np.var(sig_u))
    if var_in <= 0.0:
        return 0.0
    return float(np.var(sig_u - sig_filtered) / var_in)


__all__ = ['defringe_fft_notch', 'notch_width_sweep', 'band_integrated_amplitude',
           'lowpass_keep', 'removed_profile_um', 'removed_fraction',
           'LP_EDGE_SHAPES', 'DEFAULT_LP_EDGE_SHAPE', 'make_logger']
