"""
fringe_msv.py -- multi-scale variance analysis of the fringe fit.

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
    msv_extract_constant_n     (:2014)
    msv_extract_cauchy         (:2038)
    msv_extract_linear_n       (:2065)
    msv_extract_sellmeier      (:2092)
    msv_extract_band_integral  (:2307)
    MSV_MODELS registry        (:2322)
    multiscale_variance_analysis (:2351)
    msv_n_from_wl              (:2262)

The idea: tile the spectrum into non-overlapping windows at several widths, fit
each window independently, and read the scatter of the per-window parameters as
an empirical uncertainty.  Narrow windows scatter more; the trend with width is
the diagnostic.

SPARTA adaptations
  * No pandas.  The source's summary/plot-prep helpers
    (`prepare_multiscale_variance` etc.) are DataFrame pipelines and are not
    vendored; `msv_trend_summary` here returns plain dicts.  The `str.removesuffix`
    calls those helpers used (py3.9+) are replaced by explicit slicing so the core
    stays Python 3.8 clean.
  * No printing -- an optional `log=callable` receives the per-width report.
  * Per-window failures are caught narrowly (the source uses a bare
    `except Exception: continue`) and a rejected fit (None, see fringe_fit) is
    treated the same as a failed one: that window is dropped.
"""

import numpy as np

from fringe_config import DEFAULT_CONFIG, NM_TO_UM, make_logger
from fringe_fit import (dispersion_n, fit_signal_band_integral, fit_signal_cauchy,
                        fit_signal_constant_n, fit_signal_linear_n,
                        fit_signal_sellmeier, lstsq_V_n_t_errors)
from fringe_optics import fresnel_V, fresnel_n_from_V

_MSV_ERRORS = (ValueError, IndexError, ZeroDivisionError, FloatingPointError,
               TypeError, OverflowError, np.linalg.LinAlgError, KeyError)


# ---------------------------------------------------------------------------
# Per-model parameter extraction
# ---------------------------------------------------------------------------

def msv_extract_constant_n(fit_result, fft_info, cfg=None):
    """constant_n window result -> the common MSV record."""
    cfg = DEFAULT_CONFIG if cfg is None else cfg
    nt_fit, V_fit, phi0, _fringe_win = fit_result
    wn_u = fft_info['wn_u']
    norm_u = fft_info['norm_u']
    wl_ref = 1.0 / float(np.mean(wn_u))
    n_fit = fresnel_n_from_V(V_fit, wl_ref, cfg=cfg)
    t_fit = nt_fit / max(float(n_fit), 1e-6)
    # Recompute lstsq to get covariance -> sigma_n, sigma_t (sigma_t already in um)
    freq = 2.0 * nt_fit
    C = np.cos(2.0 * np.pi * freq * wn_u)
    S = np.sin(2.0 * np.pi * freq * wn_u)
    X = np.column_stack([C, S])
    ab = np.linalg.lstsq(X, norm_u, rcond=None)[0]
    sigma_n, sigma_t, _ = lstsq_V_n_t_errors(
        X, norm_u, float(ab[0]), float(ab[1]), wl_ref, nt_fit, cfg=cfg)
    nt_um_v = nt_fit * NM_TO_UM
    t_um_v = t_fit * NM_TO_UM
    return dict(nt=nt_um_v, n_mean=float(n_fit), t=t_um_v, phi0=phi0,
                n_mean_err=sigma_n, t_err=sigma_t,
                nt_err=nt_um_v * sigma_n / max(float(n_fit), 1e-6),
                n_mean_lo_edge=float(n_fit), n_mean_hi_edge=float(n_fit),
                nt_lo_edge=nt_um_v, nt_hi_edge=nt_um_v,
                _model='constant_n')


def _dispersive_record(n_u, t, phi0, wn_u, norm_u, cfg, model, extra):
    """Shared tail of the cauchy / linear_n / sellmeier extracts."""
    wl_u = 1.0 / wn_u
    n_mean = float(np.mean(n_u))
    # Recompute lstsq for covariance
    phi = 4.0 * np.pi * n_u * t * wn_u
    C, S = np.cos(phi), np.sin(phi)
    V_u = fresnel_V(n_u, wl_u, cfg=cfg)
    VC, VS = V_u * C, V_u * S
    X = np.column_stack([VC, VS])
    ab = np.linalg.lstsq(X, norm_u, rcond=None)[0]
    wl_ref = float(np.mean(wl_u))
    sigma_n, sigma_t, _ = lstsq_V_n_t_errors(
        X, norm_u, float(ab[0]), float(ab[1]), wl_ref, n_mean * t, cfg=cfg)
    t_um_v = t * NM_TO_UM
    nt_um_v = n_mean * t_um_v
    rec = dict(t=t_um_v, n_mean=n_mean, nt=nt_um_v,
               n_mean_err=sigma_n, t_err=sigma_t,
               nt_err=nt_um_v * sigma_n / max(n_mean, 1e-6),
               n_mean_lo_edge=float(n_u[0]), n_mean_hi_edge=float(n_u[-1]),
               nt_lo_edge=float(n_u[0]) * t_um_v, nt_hi_edge=float(n_u[-1]) * t_um_v,
               phi0=phi0, _model=model)
    rec.update(extra)
    return rec


def msv_extract_cauchy(fit_result, fft_info, cfg=None):
    cfg = DEFAULT_CONFIG if cfg is None else cfg
    A, B, t, phi0, _fw, _wn, _, _ = fit_result
    wn_u = fft_info['wn_u']
    wl_u = 1.0 / wn_u
    B = max(B, 0.0)
    n_u = A + B / wl_u ** 2
    return _dispersive_record(n_u, t, phi0, wn_u, fft_info['norm_u'], cfg,
                              'cauchy', dict(A=A, B=B))


def msv_extract_linear_n(fit_result, fft_info, cfg=None):
    # fit_signal_linear_n returns (t, phi0, n0, n1, fringe_win, wn_u, None, None)
    cfg = DEFAULT_CONFIG if cfg is None else cfg
    t, phi0, n0, n1, _fw, _wn, _, _ = fit_result
    wn_u = fft_info['wn_u']
    n_u = n0 + n1 * wn_u
    return _dispersive_record(n_u, t, phi0, wn_u, fft_info['norm_u'], cfg,
                              'linear_n', dict(n0=n0, n1=n1))


def msv_extract_sellmeier(fit_result, fft_info, cfg=None):
    cfg = DEFAULT_CONFIG if cfg is None else cfg
    B1, C1, B2, C2, t, phi0, _fw, _wn, _, _ = fit_result
    wn_u = fft_info['wn_u']
    wl_u = 1.0 / wn_u
    wl2 = wl_u ** 2
    n_sq = 1.0 + B1 * wl2 / (wl2 - C1) + B2 * wl2 / (wl2 - C2)
    n_u = np.sqrt(np.clip(n_sq, 1.0, None))
    return _dispersive_record(n_u, t, phi0, wn_u, fft_info['norm_u'], cfg,
                              'sellmeier', dict(B1=B1, C1=C1, B2=B2, C2=C2))


def msv_extract_band_integral(fit_result, fft_info, cfg=None):
    cfg = DEFAULT_CONFIG if cfg is None else cfg
    nt_fit, V_band, phi0, _fw = fit_result
    wn_u = fft_info['wn_u']
    wl_ref = 1.0 / float(np.mean(wn_u))
    n_fit = fresnel_n_from_V(min(float(V_band), 0.9999), wl_ref, cfg=cfg)
    t_fit = nt_fit / max(float(n_fit), 1e-6)
    nt_um_v = nt_fit * NM_TO_UM
    t_um_v = t_fit * NM_TO_UM
    return dict(nt=nt_um_v, n_mean=float(n_fit), t=t_um_v, phi0=phi0,
                n_mean_err=0.0, t_err=0.0, nt_err=0.0,
                n_mean_lo_edge=float(n_fit), n_mean_hi_edge=float(n_fit),
                nt_lo_edge=nt_um_v, nt_hi_edge=nt_um_v,
                _model='band_integral')


#: model name -> (fit_function, param_names, param_extractor)
#: param_extractor: callable(fit_result, fft_info, cfg) -> dict with param_names
#: keys + 'n_mean', 'nt'
MSV_MODELS = {
    'constant_n': dict(
        fit_func=fit_signal_constant_n,
        param_names=['nt'],
        extract=msv_extract_constant_n,
    ),
    'band_integral': dict(
        fit_func=fit_signal_band_integral,
        param_names=['nt'],
        extract=msv_extract_band_integral,
    ),
    'cauchy': dict(
        fit_func=fit_signal_cauchy,
        param_names=['A', 'B', 't'],
        extract=msv_extract_cauchy,
    ),
    'linear_n': dict(
        fit_func=fit_signal_linear_n,
        param_names=['n0', 'n1', 't'],
        extract=msv_extract_linear_n,
    ),
    'sellmeier': dict(
        fit_func=fit_signal_sellmeier,
        param_names=['B1', 'C1', 'B2', 'C2', 't'],
        extract=msv_extract_sellmeier,
    ),
}


def msv_n_from_wl(wr, wl, cfg=None):
    """Compute n(wl) array from a per-window result dict and wavelength array (nm).
    Delegates to `dispersion_n` for the actual model evaluation.

    `wr['t']` / `wr['nt']` are stored in um; `dispersion_n` expects t in nm
    (paired with wl in nm), so we scale up at this boundary.
    """
    cfg = DEFAULT_CONFIG if cfg is None else cfg
    m = wr.get('_model', 'constant_n')
    phi0 = wr.get('phi0', 0.0)
    _t_um = wr.get('t')
    _t_nm = float(_t_um) * 1000.0 if _t_um is not None else 0.0
    if m == 'cauchy':
        params = (wr['A'], wr['B'], _t_nm, phi0)
    elif m == 'linear_n':
        params = (wr['n0'], wr['n1'], _t_nm, phi0)
    elif m == 'sellmeier':
        params = (wr['B1'], wr['C1'], wr['B2'], wr['C2'], _t_nm, phi0)
    else:  # constant_n / band_integral
        if _t_um is None:
            _nt_um = wr.get('nt', 0.0)
            _t_nm = (float(_nt_um) * 1000.0 / max(wr.get('n_mean', 1.0), 1e-6))
        params = (wr.get('n_mean', np.nan), _t_nm, phi0)
    n, _, _ = dispersion_n(
        params, wl, m if m in ('cauchy', 'linear_n', 'sellmeier') else 'constant_n',
        cfg=cfg)
    return n


# ---------------------------------------------------------------------------
# The analysis
# ---------------------------------------------------------------------------

def multiscale_variance_analysis(wn_u, norm_u, fft_info_template, model,
                                 widths_cm=None, label="", cfg=None, log=None):
    """Tile spectrum into non-overlapping windows at multiple scales and fit each.

    Parameters
    ----------
    wn_u : 1-D array
        Uniform wavenumber grid (nm^-1).
    norm_u : 1-D array
        Normalized fringe signal on that grid.
    fft_info_template : dict
        Base fft_info dict (must contain 'nt_est', 'peak_amp', etc.).
    model : str
        One of 'constant_n', 'band_integral', 'cauchy', 'linear_n', 'sellmeier'.
    widths_cm : list of float, optional
        Window widths in cm^-1 to sweep.  Defaults to cfg.multiscale_widths_cm.
    label : str
        Label used in the log lines.
    cfg : FringeConfig|None
    log : callable|None
        Receives the per-width report the source printed.

    Returns
    -------
    dict with keys:
        widths_cm, model, param_names, derived_names,
        param_variance, derived_variance, param_means, derived_means,
        per_window, n_windows
    """
    cfg = DEFAULT_CONFIG if cfg is None else cfg
    emit = make_logger(log)
    if widths_cm is None:
        widths_cm = cfg.multiscale_widths_cm
    if model not in MSV_MODELS:
        raise ValueError("multiscale_variance_analysis: unknown model %r "
                         "(known: %s)" % (model, ', '.join(sorted(MSV_MODELS))))
    wn_u = np.asarray(wn_u, float)
    norm_u = np.asarray(norm_u, float)
    if wn_u.size != norm_u.size:
        raise ValueError("multiscale_variance_analysis: wn_u and norm_u length "
                         "mismatch (%d vs %d)" % (wn_u.size, norm_u.size))
    if wn_u.size < 2:
        raise ValueError("multiscale_variance_analysis: need at least 2 grid points")

    minfo = MSV_MODELS[model]
    fit_func = minfo['fit_func']
    param_names = minfo['param_names']
    extract = minfo['extract']
    derived_names = ['n_mean', 't', 'nt']
    if cfg.fit_phi0:
        derived_names.append('phi0')
    all_names = param_names + [d for d in derived_names if d not in param_names]

    wn_min, wn_max = float(wn_u[0]), float(wn_u[-1])

    result = dict(
        widths_cm=[], model=model,
        param_names=list(param_names), derived_names=list(derived_names),
        param_variance={k: [] for k in param_names},
        derived_variance={k: [] for k in derived_names},
        param_means={k: [] for k in param_names},
        derived_means={k: [] for k in derived_names},
        per_window={},
        n_windows=[],
    )

    for width_cm in widths_cm:
        width_wn = width_cm * 1e-7   # cm^-1 -> nm^-1
        if width_wn > (wn_max - wn_min):
            # Window wider than spectrum -- skip
            continue

        # Tile non-overlapping windows
        edges = np.arange(wn_min, wn_max, width_wn)
        window_results = []
        for wn_lo in edges:
            wn_hi = wn_lo + width_wn
            if wn_hi > wn_max + 1e-12:
                break
            mask = (wn_u >= wn_lo) & (wn_u <= wn_hi)
            if mask.sum() < cfg.msv_min_window_points:
                continue
            sub_wn = wn_u[mask]
            sub_norm = norm_u[mask]
            sub_fi = dict(fft_info_template)
            sub_fi['wn_u'] = sub_wn
            sub_fi['norm_u'] = sub_norm
            sub_fi['wn_u_full'] = sub_wn
            sub_fi['norm_u_full'] = sub_norm
            wn_center_cm = float((wn_lo + wn_hi) / 2.0) * 1e7  # nm^-1 -> cm^-1
            try:
                fit_result = fit_func(sub_fi, label='%s msv %gcm' % (label, width_cm),
                                      cfg=cfg, log=None)
                if fit_result is None:
                    continue      # fit rejected (unphysical seed) -- exclude this window
                params = extract(fit_result, sub_fi, cfg=cfg)
            except _MSV_ERRORS:
                continue          # fit failed -- exclude this window
            params['wn_center_cm'] = wn_center_cm
            params['wn_lo_cm'] = float(wn_lo) * 1e7
            params['wn_hi_cm'] = float(wn_hi) * 1e7
            window_results.append(params)

        n_win = len(window_results)
        if n_win < 2:
            # Not enough windows for variance -- skip this width
            continue

        result['widths_cm'].append(width_cm)
        result['n_windows'].append(n_win)
        result['per_window'][width_cm] = window_results

        for name in all_names:
            vals = np.array([wr[name] for wr in window_results])
            var = float(np.var(vals, ddof=1))
            mean = float(np.mean(vals))
            if name in param_names:
                result['param_variance'][name].append(var)
                result['param_means'][name].append(mean)
            else:
                result['derived_variance'][name].append(var)
                result['derived_means'][name].append(mean)

    # Convert lists to arrays
    result['widths_cm'] = np.array(result['widths_cm'])
    result['n_windows'] = np.array(result['n_windows'])
    for name in param_names:
        result['param_variance'][name] = np.array(result['param_variance'][name])
        result['param_means'][name] = np.array(result['param_means'][name])
    for name in derived_names:
        result['derived_variance'][name] = np.array(result['derived_variance'][name])
        result['derived_means'][name] = np.array(result['derived_means'][name])

    if len(result['widths_cm']) > 0:
        emit("%s [%s] multiscale: %d widths, %d-%d windows"
             % (label, model, len(result['widths_cm']),
                result['n_windows'][0], result['n_windows'][-1]))
        for name in all_names:
            d = (result['param_variance'] if name in param_names
                 else result['derived_variance'])
            m = result['param_means'] if name in param_names else result['derived_means']
            if len(d[name]) > 0:
                std_at_largest = float(np.sqrt(d[name][-1])) if d[name][-1] > 0 else 0.0
                emit("  %-10s mean=%.4g  std(largest win)=%.4g"
                     % (name, m[name][-1], std_at_largest))
    else:
        emit("%s [%s] multiscale: no valid widths (spectrum too narrow?)"
             % (label, model))

    return result


# ---------------------------------------------------------------------------
# Summaries (pandas-free replacements for the source's DataFrame prep helpers)
# ---------------------------------------------------------------------------

def _strip_suffix(name, suffix):
    """`name` without a trailing `suffix`.

    The source uses `str.removesuffix` (Python 3.9+) in its DataFrame
    plot-prep helpers; SPARTA ships CPython 3.8.10 on the Win7 build, so this
    does the same job with slicing.
    """
    if suffix and name.endswith(suffix):
        return name[:len(name) - len(suffix)]
    return name


def msv_model_names(columns, suffix='_std'):
    """Model names implied by `<model><suffix>` column labels, sorted.

    Mirrors the source's `sorted({c.removesuffix('_std') for c in ...})` idiom
    without pandas and without the 3.9+ string method.
    """
    return sorted({_strip_suffix(c, suffix) for c in columns if c.endswith(suffix)})


def msv_trend_summary(msv_result):
    """Flatten one `multiscale_variance_analysis` result into plain rows.

    Returns a list of dicts, one per swept width:
        {'width_cm', 'n_windows', '<name>_mean', '<name>_std', ...}
    for every parameter and derived quantity.  This replaces the source's
    pandas `prepare_multiscale_variance` for callers that only need numbers.
    """
    rows = []
    widths = list(msv_result.get('widths_cm', []))
    n_windows = list(msv_result.get('n_windows', []))
    names = (list(msv_result.get('param_names', []))
             + [d for d in msv_result.get('derived_names', [])
                if d not in msv_result.get('param_names', [])])
    for i, w in enumerate(widths):
        row = {'width_cm': float(w),
               'n_windows': int(n_windows[i]) if i < len(n_windows) else 0,
               'model': msv_result.get('model')}
        for name in names:
            if name in msv_result['param_means']:
                mean_arr = msv_result['param_means'][name]
                var_arr = msv_result['param_variance'][name]
            else:
                mean_arr = msv_result['derived_means'][name]
                var_arr = msv_result['derived_variance'][name]
            if i < len(mean_arr):
                row[name + '_mean'] = float(mean_arr[i])
                row[name + '_std'] = float(np.sqrt(max(float(var_arr[i]), 0.0)))
        rows.append(row)
    return rows


__all__ = ['MSV_MODELS', 'msv_extract_constant_n', 'msv_extract_cauchy',
           'msv_extract_linear_n', 'msv_extract_sellmeier',
           'msv_extract_band_integral', 'msv_n_from_wl',
           'multiscale_variance_analysis', 'msv_model_names',
           'msv_trend_summary']
