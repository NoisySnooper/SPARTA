"""
fringe_apply.py  --  the one place SPARTA cleans a spectrum.

Every defringed number this program produces comes through here: the main
plot's df switch, the Absorbance_notch / Background_notch / Sample_notch
columns a Run or an Export writes into each trace's own absorbance CSV, the
defringe report and the custom-quantity columns (Af / Sf / Bf).  The fringe
workbench draws with `fringe_detect.compute_channel_fit` directly; this module
makes the same call, with the same keywords, from a recipe.  One pipeline, so
the picture and the plot cannot disagree.

Numeric core vendored from `defringe_dac.py` (DAC Absorption Fringe Analysis).
    Source module : defringe_dac.py
    Author        : Matthew R. Diamond
    Repository    : github.com/matthewrdiamond/DAC-Absorption-Fringe-Analysis
    License       : vendored under MIT by permission of the author.

WHAT A RECIPE SAYS.  `fringe_panel.FringeWorkbench.defringe_recipe` builds one
per trace and `fringe_panel.global_recipe` builds the series-wide one; both
hand this module the same shapes:

    gates     halfwidth_um, nt_min_nm, nt_max_nm, pvalue_max  (series-wide)
    cfg       a FringeConfig -- the detector's wavelength window and models
    channels  per raw channel: notch_centers_nm, notch_halfwidths_um,
              lowpass, lp_cutoff_um, lp_rolloff_um, lp_edge_shape

NO FRINGE, NO CLEANING.  Before any of the grammar below applies, the channel
has to have a fringe in it.  A channel the detector passes over is left exactly
as it came in: no notch, no low-pass, `applied` False and `nt_um` None.  That is
the source's own gate, and it is why `applied` True always travels with a
number.

NOTCH CENTRES, THREE STATES, once a fringe IS detected:

    a LIST   notch exactly these n*t centres (nm), at these half-widths
    []       notch NOTHING
    None     automatic -- the core detects this spectrum's own fundamental

The workbench always names the list, empty included, for a trace it holds
state for, so unticking every notch really does stop notching.  A trace it
holds nothing for gets None, and each spectrum is then cleaned at its own
detected fringe rather than at some other pressure's peaks.

The LOW-PASS is independent of the LIST: on a channel with a fringe it applies
whether or not anything is notched, so an empty list with the low-pass on is a
low-pass alone.  It is not independent of the detection.

WIDTHS are absolute n*t um (+-reach): sigma_f = 2000 * halfwidth_um, the same
reach at every centre.  There is no fractional convention any more.

NaN-safe: invalid points are dropped for the FFT (the uniform-wavenumber
resample bridges the gaps) and restored as NaN in the output, so results align
1:1 with the input.  numpy + scipy (no pandas).

THIS MODULE WRITES NO FILES.  Since R20 there is one CSV per trace, written by
`engine.write_absorbance_csv`; `notch_columns` returns the arrays that go into
it and the caller appends them.

NQT / Lee Lab -- Sep 2026.
"""

import numpy as np

from fringe_config import DEFAULT_CONFIG, LP_EDGE_SHAPES
from fringe_detect import compute_channel_fit, corroborate_nt, fft_initial_guess
from fringe_notch import defringe_fft_notch

_NM_TO_UM = 1.0e-3

#: The raw count channels this module cleans, and the engine keys they live at.
CHANNEL_KEYS = ("bg_c", "samp_c")


# ---------------------------------------------------------------------------
# config assembly
# ---------------------------------------------------------------------------
def config_for(cfg=None, halfwidth_um=None, nt_min_nm=None, nt_max_nm=None,
               pvalue_max=None, lp_rolloff_um=None, lp_edge_shape=None):
    """The FringeConfig one channel is cleaned under.

    `cfg` is the recipe's config (the detector's wavelength window, the
    diamond model, the lamp-regime fine band); the rest are the series-wide
    gates and this channel's low-pass edge, which override it.  The edge rides
    on the config because `compute_channel_fit` hands its cfg straight to
    `defringe_fft_notch` -- the shape and the roll-off reach the mask without
    the detector needing to know they exist.
    """
    base = DEFAULT_CONFIG if cfg is None else cfg
    kw = {}
    if nt_min_nm is not None:
        kw['fringe_nt_min_nm'] = float(nt_min_nm)
    if nt_max_nm is not None:
        kw['fringe_nt_max_nm'] = float(nt_max_nm)
    if pvalue_max is not None:
        kw['fringe_pvalue_max'] = float(pvalue_max)
    if halfwidth_um is not None and float(halfwidth_um) > 0:
        kw['notch_halfwidth_um'] = float(halfwidth_um)
    if lp_rolloff_um is not None and float(lp_rolloff_um) > 0:
        kw['lp_rolloff_um'] = float(lp_rolloff_um)
    if lp_edge_shape is not None and str(lp_edge_shape) in LP_EDGE_SHAPES:
        kw['lp_edge_shape'] = str(lp_edge_shape)
    return base.evolve(**kw) if kw else base


def _finite_view(wl_nm, counts):
    """(mask, wl, counts) over the points an FFT can use, or None."""
    wl_nm = np.asarray(wl_nm, float)
    y = np.asarray(counts, float)
    if wl_nm.shape != y.shape:
        raise ValueError("fringe_apply: wl_nm and counts must have the same "
                         "shape (got %s, %s)" % (wl_nm.shape, y.shape))
    finite = np.isfinite(y) & np.isfinite(wl_nm) & (wl_nm > 0)
    return finite, wl_nm, y


def _covered(nt_nm, centers_nm, halfwidth_um):
    """True when a supplied centre already sits on the detected fundamental.

    Half a half-width either side, the same reach the old automatic path
    used: two Gaussians at one centre cut twice as deep, which is not what
    'add the fundamental as well' means.
    """
    for c in centers_nm or ():
        try:
            c = float(c)
        except (TypeError, ValueError):
            continue
        if np.isfinite(c) and abs(c - float(nt_nm)) <= 500.0 * float(halfwidth_um):
            return True
    return False


# ---------------------------------------------------------------------------
# the one cleaning
# ---------------------------------------------------------------------------
def clean_channel(wl_nm, counts, cfg=None, halfwidth_um=None,
                  nt_min_nm=None, nt_max_nm=None, pvalue_max=None,
                  notch_centers_nm=None, notch_halfwidths_um=None,
                  lowpass=False, lp_cutoff_um=None, lp_rolloff_um=None,
                  lp_edge_shape=None, add_fundamental=False, label='',
                  log=None):
    """Clean ONE raw intensity channel through the vendored fringe core.

    Runs `compute_channel_fit(run_fits=False)` -- the workbench's own fast
    path, no optimisers -- and returns the notch-stage result it stashes at
    ``fft_info['I_notch_1x']``, which is the spectrum WITH the low-pass
    applied.

    Returns a dict:
      clean       defringed counts, same shape as the input, NaNs preserved.
                  A copy of `counts` when no mask ran.
      applied     True iff a mask was actually applied.  Never True without a
                  detected fringe, so a reader of this result can print
                  `nt_um` beside it without guarding.
      nt_um       the detected fundamental in micron, or None.  A measurement
                  of the spectrum, not of the notch list.
      pvalue      Fisher g-test p-value behind that detection (1.0 if none).
      centers_nm  the centres the CALLER named, or None on the automatic path.
                  It tells a panel's picks from the detector's own answer.

    A channel with NO detected fringe is left alone: nothing is notched, the
    low-pass does not run, and `clean` is the input.  That is the source's gate
    and it is why `applied` and `nt_um` agree.

    `notch_centers_nm` is the three-state grammar in the module docstring, and
    it governs a channel that HAS a fringe: a list, [] for none, None for
    automatic.  `add_fundamental` is for a caller holding a reader's picks but
    not the detector's own answer for that spectrum (a session file written
    before this trace was ever computed): the detected fundamental joins the
    list, at the default half-width, unless a pick already sits on it.
    """
    cfg = config_for(cfg, halfwidth_um, nt_min_nm, nt_max_nm, pvalue_max,
                     lp_rolloff_um, lp_edge_shape)
    finite, wl_nm, y = _finite_view(wl_nm, counts)
    out = y.copy()
    result = {"clean": out, "applied": False, "nt_um": None, "pvalue": 1.0,
              "centers_nm": (None if notch_centers_nm is None
                             else [float(c) for c in notch_centers_nm])}
    if int(finite.sum()) < cfg.min_detect_points:
        return result

    wl_f, y_f = wl_nm[finite], y[finite]
    centers = notch_centers_nm
    widths = notch_halfwidths_um
    kw = {}
    if centers is not None:
        kw["notch_centers_nm"] = [float(c) for c in centers]
        if widths is not None:
            kw["notch_halfwidths_um"] = [float(w) for w in widths]
    lp_on = bool(lowpass and lp_cutoff_um and float(lp_cutoff_um) > 0)
    if lp_on:
        kw["lowpass"] = True
        kw["lp_cutoff_um"] = float(lp_cutoff_um)
        kw["lp_rolloff_um"] = float(cfg.lp_rolloff_um)

    fit, _I, nt, _defaults = compute_channel_fit(
        wl_f, y_f, cfg=cfg, label=label, run_fits=False, log=log, **kw)
    fi = fit.get("fft_info") or {}
    result["pvalue"] = float(fi.get("fisher_pv", 1.0))
    if nt is None:
        # No fringe: the core ran no mask at all, so there is nothing to hand
        # back but the spectrum as it came in.  `applied` stays False and
        # `nt_um` stays None -- the pair a caller reports from.
        return result
    result["nt_um"] = float(nt) * _NM_TO_UM

    clean_f = fi.get("I_notch_1x")

    # The detected fundamental, for a caller that holds the picks but not the
    # detector's own answer for this spectrum.  Re-masks off the grids the
    # core already built, so this costs one FFT, not a second detection.
    if (add_fundamental and nt is not None and centers is not None
            and not _covered(nt, kw.get("notch_centers_nm"),
                             cfg.notch_halfwidth_um)
            and fi.get("wn_u_full") is not None):
        merged = [float(nt)] + list(kw.get("notch_centers_nm") or ())
        merged_w = None
        if kw.get("notch_halfwidths_um") is not None:
            merged_w = ([float(cfg.notch_halfwidth_um)]
                        + list(kw["notch_halfwidths_um"]))
        clean_f, _nt_est, _filt = defringe_fft_notch(
            fi["wn_u_full"], fi["sig_u_full"], wl_f, y_f, nt,
            notch_centers_nm=merged, notch_halfwidths_um=merged_w,
            lowpass=lp_on, lp_cutoff_um=kw.get("lp_cutoff_um"),
            lp_rolloff_um=kw.get("lp_rolloff_um"), cfg=cfg)
        kw["notch_centers_nm"] = merged
        result["centers_nm"] = list(merged)

    applied_centers = (kw.get("notch_centers_nm") if centers is not None
                       else ([float(nt)] if nt is not None else []))
    if clean_f is None or not (applied_centers or lp_on):
        return result
    clean_f = np.asarray(clean_f, float)
    if clean_f.shape != y_f.shape or not np.any(np.isfinite(clean_f)):
        return result
    out[finite] = clean_f
    result["applied"] = True
    # centers_nm stays None on the automatic path: it reports what the CALLER
    # named, so a reader of the result can tell a panel's picks from the
    # detector's own answer. The detected fundamental travels as nt_um.
    return result


def detect_nt(wl_nm, counts, cfg=None, halfwidth_um=None, nt_min_nm=None,
              nt_max_nm=None, pvalue_max=None, label='', log=None):
    """(n*t in micron or None, Fisher p) for one raw channel.

    The SAME detection the cleaning runs: the narrow fit window, the wide
    window and the full range, cross-validated 2-of-3 by `corroborate_nt`
    under the same gates and the same config.  Before R17 this read ran one
    FFT over the full range alone, which let a strong short-path ripple win
    where the corroborated answer is the long one -- the thickness reported
    beside a cleaned spectrum was then not the n*t that cleaned it.

    Still DELIBERATELY notch-set independent: n*t here is a MEASUREMENT of the
    dominant fringe, so feeding it the picked centres would make it report the
    picks back and a thickness series would then track the hand that made it
    rather than the sample.  The Fisher p gate holds for the same reason: a
    channel with no confident fringe reports nothing, never a guess.  The p
    returned is the NARROW window's, the one the fit runs in and the one
    `clean_channel` reports.
    """
    cfg = config_for(cfg, halfwidth_um, nt_min_nm, nt_max_nm, pvalue_max)
    finite, wl_nm, y = _finite_view(wl_nm, counts)
    if int(finite.sum()) < cfg.min_detect_points:
        return None, 1.0
    wl_f, y_f = wl_nm[finite], y[finite]
    vis = (wl_f >= cfg.fit_wl_min_nm) & (wl_f <= cfg.fit_wl_max_nm)
    _nt_n, info = fft_initial_guess(wl_f[vis], y_f[vis], cfg=cfg, log=log,
                                    label=label)
    wl_wide_lo, wl_wide_hi = 1.0 / cfg.wide_hi, 1.0 / cfg.wide_lo
    wide = (wl_f >= wl_wide_lo) & (wl_f <= wl_wide_hi)
    _nt_w, info_wide = fft_initial_guess(wl_f[wide], y_f[wide], cfg=cfg,
                                         log=log, label=label)
    _nt_f, info_full = fft_initial_guess(wl_f, y_f, cfg=cfg, log=log,
                                         label=label)
    if info is None:
        return None, 1.0
    corr = corroborate_nt([('narrow', info), ('wide', info_wide),
                           ('full', info_full)], cfg=cfg, log=log, label=label)
    pv = float(info.get("fisher_pv", 1.0))
    nt = corr['nt']
    return (None if nt is None else float(nt) * _NM_TO_UM), pv


# ---------------------------------------------------------------------------
# The notch columns of a trace's CSV
# ---------------------------------------------------------------------------
def notch_columns(result, bg_kw=None, s_kw=None, **kw):
    """The three defringed columns of one engine result, as arrays.

    Cleans the raw Background and Sample counts independently -- Background
    first, the order the ratio is formed in -- then recomputes absorbance from
    the defringed (or, per channel, original) counts.  Nothing is written:
    R20 merged the standalone {stem}_absorbance_notch.csv into the trace's own
    absorbance CSV, so the caller hands these arrays to
    `engine.write_absorbance_csv(..., extra=[...])`.

    Returns a dict:

      Absorbance_notch   ALWAYS filled: recomputed from a channel's clean
                         counts where that channel was cleaned and from its
                         raw counts where it was not.  NaN only where the
                         straight absorbance is NaN, so the column reads as a
                         complete trace whether one channel cleaned, both, or
                         neither (with neither it IS the straight absorbance).
      Background_notch   the channel's clean counts, or an all-NaN array when
      Sample_notch       the detector found no fringe in it: a channel that
                         was not cleaned writes a blank column (Matthew's
                         convention, kept).
      applied_bg         bool, per channel: was a mask actually applied.
      applied_s
      nt_bg_um           the detected fundamental in micron, or None.
      nt_s_um
      p_bg               the Fisher g-test p behind that detection (1.0 when
      p_s                there was none), from clean_channel's "pvalue".

    `kw` is the recipe's shared part (the gates and the config); `bg_kw` and
    `s_kw` are the PER-CHANNEL parts layered on top.  The two channels carry
    different fringes and are cleaned independently, so a recipe that names
    different centres or a different low-pass per channel says so here.  These
    are the same two `clean_channel` calls, with the same kwargs layering, the
    retired writer made: the R17 parity is a parity of this pipeline.
    """
    wl = np.asarray(result["wl"], float)
    dark = np.asarray(result["dark_c"], float)
    bg = np.asarray(result["bg_c"], float)
    s = np.asarray(result["samp_c"], float)
    bg_ds = bg - dark
    s_ds = s - dark

    with np.errstate(divide="ignore", invalid="ignore"):
        abs_straight = np.log10(bg_ds / s_ds)           # = +absorbance
    abs_straight[~np.isfinite(abs_straight)] = np.nan

    bg_ch = clean_channel(wl, bg, **dict(kw, **(bg_kw or {})))
    s_ch = clean_channel(wl, s, **dict(kw, **(s_kw or {})))

    bg_for_abs = (bg_ch["clean"] - dark) if bg_ch["applied"] else bg_ds
    s_for_abs = (s_ch["clean"] - dark) if s_ch["applied"] else s_ds
    with np.errstate(divide="ignore", invalid="ignore"):
        abs_notch = np.log10(bg_for_abs / s_for_abs)
    abs_notch[~np.isfinite(abs_notch)] = np.nan
    # The column is always filled, so a point the cleaning could not form a
    # ratio at falls back to the straight absorbance rather than to a blank.
    gap = np.isnan(abs_notch) & ~np.isnan(abs_straight)
    if gap.any():
        abs_notch[gap] = abs_straight[gap]

    # An un-cleaned channel leaves a blank column (all-NaN -> "").
    return {
        "Absorbance_notch": abs_notch,
        "Background_notch": (np.asarray(bg_ch["clean"], float)
                             if bg_ch["applied"] else np.full_like(wl, np.nan)),
        "Sample_notch": (np.asarray(s_ch["clean"], float)
                         if s_ch["applied"] else np.full_like(wl, np.nan)),
        "applied_bg": bool(bg_ch["applied"]),
        "applied_s": bool(s_ch["applied"]),
        "nt_bg_um": bg_ch["nt_um"],
        "nt_s_um": s_ch["nt_um"],
        "p_bg": bg_ch["pvalue"],
        "p_s": s_ch["pvalue"],
    }


__all__ = ['clean_channel', 'detect_nt', 'notch_columns', 'config_for',
           'CHANNEL_KEYS']
