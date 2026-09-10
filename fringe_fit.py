"""
fringe_fit.py -- dispersion models and the least-squares fringe fitters.

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
    dispersion_n            (:1297)  params -> n(lam), t, phi0 for the 4 models
    dispersion_result_dict  (:1429)  named params + n_mean/nt_um at the um boundary
    lstsq_V_n_t_errors      (:1179)  lstsq covariance -> sigma_V, sigma_n, sigma_t
    fit_signal_constant_n   (:1614)  bounded Brent over n*t, analytic amplitude/phase
    fit_signal_cauchy       (:1667)  Nelder-Mead over (A, B, t)
    fit_signal_linear_n     (:1738)  Nelder-Mead over (n0, n1, t)
    fit_signal_sellmeier    (:1937)  Nelder-Mead over (B1, C1, B2, C2, t)
    fit_signal_band_integral(:2293)  constant_n nt/phi0 with band-integrated V
    fine_fit_sigma          (:1807)  finite-difference Jacobian -> parameter sigmas
    find_fit_window         (:1572)  sliding-R^2 window search (kept, unused by default)
    run_window_fits         (:15934) the LSQ half of _run_all_fitters' window tiering

SPARTA divergences from the source (each deliberate):
  1. NO hot-path asserts.  The source guards `n_fit >= 1.0`, `n0_0 >= 1.0` and
     `amp_free > 1e-6` with bare `assert`, which (a) vanishes under `python -O`
     and (b) aborts the whole channel on a physically-possible seed.  Here the
     seed/result checks return None and report through `log`; the per-iteration
     amplitude check returns a large residual so the optimiser steers away
     instead of crashing.
  2. No printing: results go to an optional `log=callable`.
  3. Tunables (FIT_PHI0, T_BOUNDS_NM, FRINGE_NT_MIN/MAX_NM, the fit windows)
     come from a frozen FringeConfig instead of module globals.
  4. `run_window_fits` gates the narrow-window fits on whether the fine window's
     centre falls inside the narrow band (i.e. the two are redundant) instead of
     the source's parsed-folder-date lamp-era test.
  5. `run_window_fits` applies the source's 20-point window floor to the full and
     wide tiers as well, where the source gates only narrow and fine.  A tier too
     short to fit is dropped instead of aborting the channel.

Grid zones inside `run_window_fits` (source `_run_all_fitters`, verbatim):
  * the FIT runs on the window slice of the uniform wavenumber grid;
  * the REPORTED n_mean / nt_um average n(lam) over `wl_full`, the full original
    detector wavelength grid, in every tier (source :16097-16098, :16654-16694);
  * the constant_n Fresnel inversion uses one wl_ref = mean(1/wn_u_full) for the
    full/wide/narrow tiers, and the fine tier's own mean (source :16245-16262).

Unit zones (source convention): the fit math runs in nm; t/nt cross to um once,
at `dispersion_result_dict` / the `*_err` helpers, via NM_TO_UM.
Python 3.8 compatible; numpy + scipy + stdlib only.
"""

import numpy as np

# scipy.optimize is imported inside the fitters, not here: importing this module
# must stay cheap for callers that only want the dispersion helpers.
from fringe_config import DEFAULT_CONFIG, NM_TO_UM, make_logger
from fringe_notch import band_integrated_amplitude
from fringe_optics import cauchy_n_diamond, fresnel_V, fresnel_n_from_V

# Residual returned in place of the source's `assert amp_free > 1e-6`: large
# enough that any real minimum wins, finite so the simplex keeps moving.
_DEGENERATE_PENALTY = 1e12

_EXPECTED_PARAM_LEN = {'cauchy': 4, 'linear_n': 4, 'constant_n': 3, 'sellmeier': 6}


# ---------------------------------------------------------------------------
# Dispersion model helpers
# ---------------------------------------------------------------------------

def dispersion_n(params, wl, model, cfg=None):
    """Map optimizer params to n(lam) array, t, phi0.

    model='cauchy':     params = (A, B, t, phi0)      -> n = A + B/lam^2
    model='linear_n':   params = (n0, n1, t, phi0)    -> n = n0 + n1/lam  (linear in wn)
    model='constant_n': params = (n, t, phi0)         -> n = const
    model='sellmeier':  params = (B1, C1, B2, C2, t, phi0)
                                    -> n = sqrt(1 + B1 lam^2/(lam^2-C1) + B2 lam^2/(lam^2-C2))
    Returns (n_array, t, phi0).
    """
    cfg = DEFAULT_CONFIG if cfg is None else cfg
    # Accept param vectors with or without trailing phi0
    if len(params) < _EXPECTED_PARAM_LEN.get(model, 99):
        params = list(params) + [0.0]
    if model == 'cauchy':
        A, B, t, phi0 = params
        B = float(max(B, 0.0))
        n = A + B / wl ** 2
    elif model == 'linear_n':
        n0, n1, t, phi0 = params
        n = n0 + n1 / wl
    elif model == 'constant_n':
        n_val, t, phi0 = params
        n = np.full_like(wl, float(n_val))
    elif model == 'sellmeier':
        B1, C1, B2, C2, t, phi0 = params
        wl2 = wl ** 2
        n_sq = 1.0 + B1 * wl2 / (wl2 - C1) + B2 * wl2 / (wl2 - C2)
        n = np.sqrt(np.clip(n_sq, 1.0, None))
    else:
        raise ValueError("Unknown dispersion model: %r (expected one of %s)"
                         % (model, ', '.join(sorted(_EXPECTED_PARAM_LEN))))
    t = float(np.clip(t, cfg.t_min_nm, cfg.t_max_nm))
    if not cfg.fit_phi0:
        phi0 = 0.0
    return n, t, phi0


def dispersion_result_dict(params, wl, model, cfg=None):
    """Extract named parameters and compute n_mean, nt_um from fitted params.

    Fit math runs in nm (wl is nm); thickness values are converted to um here
    once at the boundary, so all downstream consumers see t_um / nt_um in um.
    """
    n, t, phi0 = dispersion_n(params, wl, model, cfg=cfg)
    n_mean = float(np.mean(n))
    t_um_v = t * NM_TO_UM
    nt_um = n_mean * t_um_v
    d = dict(t_um=t_um_v, phi0=phi0, n_mean=n_mean, nt_um=nt_um)
    if model == 'cauchy':
        d['A'] = params[0]
        d['B'] = float(max(params[1], 0.0))
    elif model == 'linear_n':
        d['n0'] = params[0]
        d['n1'] = params[1]
    elif model == 'constant_n':
        d['n_const'] = params[0]
    elif model == 'sellmeier':
        d['B1'] = params[0]
        d['C1'] = params[1]
        d['B2'] = params[2]
        d['C2'] = params[3]
    return d


# ---------------------------------------------------------------------------
# Error propagation
# ---------------------------------------------------------------------------

def lstsq_V_n_t_errors(X, norm_u, a, b, wl_ref, nt, cfg=None):
    """Propagate lstsq covariance on (a,b) through V -> n -> t.

    Parameters
    ----------
    X : (N, 2) design matrix used in lstsq
    norm_u : (N,) data vector
    a, b : float, lstsq coefficients
    wl_ref : float, reference wavelength (nm) for Fresnel inversion
    nt : float, n*t product (nm) -- internal fit unit

    Returns
    -------
    sigma_n, sigma_t, sigma_V : float
        sigma_t is returned in um (converted from the nm-internal computation)
        so callers see t-uncertainty in the same unit as the t_um values.
    """
    N = len(norm_u)
    resid = norm_u - X @ np.array([a, b])
    s2 = float(np.sum(resid ** 2)) / max(N - 2, 1)      # residual variance
    XtX = X.T @ X
    try:
        cov_ab = s2 * np.linalg.inv(XtX)                 # 2x2 covariance of (a,b)
    except np.linalg.LinAlgError:
        return 0.0, 0.0, 0.0
    var_a, var_b, cov_ab_01 = cov_ab[0, 0], cov_ab[1, 1], cov_ab[0, 1]

    # V = hypot(a, b)
    V = float(np.hypot(a, b))
    if V < 1e-12:
        return 0.0, 0.0, 0.0
    # sigma_V via error propagation:
    # sigma_V^2 = (dV/da)^2*var_a + (dV/db)^2*var_b + 2*(dV/da)(dV/db)*cov_ab
    dVda, dVdb = a / V, b / V
    var_V = dVda ** 2 * var_a + dVdb ** 2 * var_b + 2 * dVda * dVdb * cov_ab_01
    sigma_V = float(np.sqrt(max(var_V, 0.0)))

    # n = nd*(1-r)/(1+r) where r = sqrt(V/2)
    nd = float(cauchy_n_diamond(wl_ref, cfg=cfg))
    R = min(V / 2.0, 0.9999)
    r = np.sqrt(R)
    if r < 1e-12:
        return 0.0, 0.0, sigma_V
    dr_dV = 1.0 / (4.0 * r)                              # d(sqrt(V/2))/dV
    dn_dr = -2.0 * nd / (1.0 + r) ** 2
    sigma_n = abs(dn_dr * dr_dV) * sigma_V

    # t = nt / n
    n = nd * (1.0 - r) / (1.0 + r)
    if abs(n) < 1e-12:
        return sigma_n, 0.0, sigma_V
    t = nt / n
    sigma_t = t * sigma_n / abs(n)

    return float(sigma_n), float(sigma_t) * NM_TO_UM, float(sigma_V)


# ---------------------------------------------------------------------------
# Window search (preserved from the source; the fitters use fixed ranges)
# ---------------------------------------------------------------------------

def find_fit_window(wn_u, norm_u, phase_u, V_u=None, win_cm=2500.0,
                    frac_thresh=0.20):
    """Find the wavenumber window where a fitted model explains the most variance (R^2)."""
    win_nm1 = win_cm * 1e-7
    half = win_nm1 / 2.0
    n_cen = 80
    centers = np.linspace(wn_u[0] + half, wn_u[-1] - half, n_cen)
    scores = np.zeros(n_cen)
    for i, wc in enumerate(centers):
        mask = (wn_u >= wc - half) & (wn_u <= wc + half)
        if mask.sum() < 10:
            continue
        nm, ph = norm_u[mask], phase_u[mask]
        hann = np.hanning(len(nm))
        y_c = (nm - nm.mean()) * hann
        ss_tot = float(np.dot(y_c, y_c))
        if ss_tot < 1e-30:
            continue
        Cw = np.cos(ph) * hann
        Sw = np.sin(ph) * hann
        if V_u is not None:
            V_win = V_u[mask]
            Cw = V_win * Cw
            Sw = V_win * Sw
        a, b = np.linalg.lstsq(np.column_stack([Cw, Sw]), y_c, rcond=None)[0]
        ss_res = float(np.sum((y_c - a * Cw - b * Sw) ** 2))
        scores[i] = max(1.0 - ss_res / ss_tot, 0.0)
    thresh = frac_thresh * max(scores.max(), 1e-30)
    peak_idx = int(np.argmax(scores))
    lo_idx = peak_idx
    while lo_idx > 0 and scores[lo_idx - 1] >= thresh:
        lo_idx -= 1
    hi_idx = peak_idx
    while hi_idx < len(scores) - 1 and scores[hi_idx + 1] >= thresh:
        hi_idx += 1
    wn_lo = max(float(centers[lo_idx]) - half, float(wn_u[0]))
    wn_hi = min(float(centers[hi_idx]) + half, float(wn_u[-1]))
    return wn_lo, wn_hi


# ---------------------------------------------------------------------------
# Fitting: ConstantN
# ---------------------------------------------------------------------------

def fit_signal_constant_n(fft_info, label="", cfg=None, log=None):
    """1-D bounded Brent over n*t; amplitude and phase solved analytically.

    Single-fundamental fit: V=2R from the fundamental amplitude, n from Fresnel(V).

    Returns (nt_fit, V_fit, phi0, fringe_win), or None when the Fresnel inversion
    lands below n = 1 (physically impossible for a sample between diamonds).  The
    source asserts here; SPARTA reports through `log` and returns None so the
    caller can drop this window instead of losing the channel.
    """
    from scipy.optimize import minimize_scalar

    cfg = DEFAULT_CONFIG if cfg is None else cfg
    emit = make_logger(log)
    wn_u = fft_info['wn_u']
    norm_u = fft_info['norm_u']
    nt0 = fft_info['nt_est']

    def residual(nt):
        nt = float(nt)
        freq = 2.0 * nt
        C = np.cos(2.0 * np.pi * freq * wn_u)
        S = np.sin(2.0 * np.pi * freq * wn_u)
        X = np.column_stack([C, S])
        coeffs = np.linalg.lstsq(X, norm_u, rcond=None)[0]
        return float(np.mean((norm_u - X @ coeffs) ** 2))

    # Bracket around FFT estimate to stay inside the alias watershed
    half_alias = 1.0 / (4.0 * (wn_u.max() - wn_u.min()))
    half_width = min(0.20 * nt0, 0.9 * half_alias)
    _nt_lo = max(cfg.fringe_nt_min_nm, nt0 - half_width)
    _nt_hi = min(cfg.fringe_nt_max_nm, nt0 + half_width)
    if _nt_hi - _nt_lo < 1.0:
        _nt_lo, _nt_hi = cfg.fringe_nt_min_nm, cfg.fringe_nt_max_nm
    res = minimize_scalar(residual,
                          bounds=(_nt_lo, _nt_hi),
                          method='bounded',
                          options=dict(maxiter=2000, xatol=1.0))
    nt_fit = float(np.clip(res.x, cfg.fringe_nt_min_nm, cfg.fringe_nt_max_nm))

    freq = 2.0 * nt_fit
    C = np.cos(2.0 * np.pi * freq * wn_u)
    S = np.sin(2.0 * np.pi * freq * wn_u)
    X = np.column_stack([C, S])
    a, b = np.linalg.lstsq(X, norm_u, rcond=None)[0]
    V_fit = float(np.hypot(a, b))
    phi0 = float(np.arctan2(-b, a)) if cfg.fit_phi0 else 0.0
    fringe_win = a * C + b * S
    wl_ref = 1.0 / float(np.mean(wn_u))

    n_fit = fresnel_n_from_V(V_fit, wl_ref, cfg=cfg)
    if not (n_fit >= 1.0):
        emit("%s [ConstantN] rejected: Fresnel inversion gives n=%.4f < 1 "
             "(V=%.4f) -- window dropped" % (label, n_fit, V_fit))
        return None
    t_um = (nt_fit / n_fit) * NM_TO_UM
    emit("%s [ConstantN] nt=%.2f um  n_mean=%.4f  t=%.2f um  V=%.4f  phi0=%.3f  obj=%.2e"
         % (label, nt_fit / 1000.0, n_fit, t_um, V_fit, phi0, res.fun))
    return nt_fit, V_fit, phi0, fringe_win


# ---------------------------------------------------------------------------
# Shared Nelder-Mead machinery for the dispersive models
# ---------------------------------------------------------------------------

def _seed_n0_t0(fft_info, label, model_tag, cfg, emit):
    """FFT-seeded (n0, t0, wl_u, wl_ctr) or None when the seed is unphysical."""
    wn_u = fft_info['wn_u']
    nt0 = fft_info['nt_est']
    V0 = fft_info['peak_amp']
    wl_u = 1.0 / wn_u
    wl_ctr = float(np.mean(wl_u))
    n0_0 = float(fresnel_n_from_V(V0, wl_ctr, cfg=cfg))
    if not (n0_0 >= 1.0):
        emit("%s [%s] rejected: FFT-seed n0=%.4f < 1 (V0=%.4f) -- window dropped"
             % (label, model_tag, n0_0, V0))
        return None
    return n0_0, nt0 / n0_0, wl_u, wl_ctr


def _dispersive_residual(n_u, t, wn_u, wl_u, norm_u, cfg):
    """Shared residual body: normalised V*cos/V*sin projection, mean square error."""
    phi = 4.0 * np.pi * n_u * t * wn_u
    C, S = np.cos(phi), np.sin(phi)
    V_u = fresnel_V(n_u, wl_u, cfg=cfg)
    VC, VS = V_u * C, V_u * S
    a, b = np.linalg.lstsq(np.column_stack([VC, VS]), norm_u, rcond=None)[0]
    amp_free = float(np.hypot(a, b))
    if amp_free <= 1e-6:
        # Source asserts here; a penalty keeps the simplex alive instead.
        return _DEGENERATE_PENALTY
    model = (a * VC + b * VS) / amp_free
    return float(np.mean((norm_u - model) ** 2))


def _finalise_dispersive(n_u, t_fit, wn_u, wl_u, norm_u, cfg, emit, label, tag):
    """Post-fit lstsq projection -> (phi0, fringe_win, V_u) or None if degenerate."""
    phi = 4.0 * np.pi * n_u * t_fit * wn_u
    C, S = np.cos(phi), np.sin(phi)
    V_u = fresnel_V(n_u, wl_u, cfg=cfg)
    VC, VS = V_u * C, V_u * S
    a, b = np.linalg.lstsq(np.column_stack([VC, VS]), norm_u, rcond=None)[0]
    phi0 = float(np.arctan2(-b, a)) if cfg.fit_phi0 else 0.0
    amp = float(np.hypot(a, b))
    if amp <= 1e-6:
        emit("%s [%s] rejected: degenerate fringe amplitude (%.3g) -- window dropped"
             % (label, tag, amp))
        return None
    return phi0, (a * VC + b * VS) / amp, V_u


# ---------------------------------------------------------------------------
# Fitting: Cauchy dispersion (A, B, t)
# ---------------------------------------------------------------------------

def fit_signal_cauchy(fft_info, label="", cfg=None, log=None):
    """3-D Nelder-Mead over (A, B, t) with Cauchy dispersion n(lam) = A + B/lam^2.

    Returns (A, B, t_nm, phi0, fringe_win, wn_u, None, None) -- the source's tuple
    shape -- or None when the FFT seed or the final amplitude is degenerate.
    """
    from scipy.optimize import minimize

    cfg = DEFAULT_CONFIG if cfg is None else cfg
    emit = make_logger(log)
    wn_u = fft_info['wn_u']
    norm_u = fft_info['norm_u']

    seed = _seed_n0_t0(fft_info, label, 'Cauchy', cfg, emit)
    if seed is None:
        return None
    n0_0, t0, wl_u, wl_ctr = seed

    def residual(params):
        A, B, t = params
        B = float(max(B, 0.0))
        t = float(np.clip(t, cfg.t_min_nm, cfg.t_max_nm))
        n_u = A + B / wl_u ** 2
        return _dispersive_residual(n_u, t, wn_u, wl_u, norm_u, cfg)

    t_step = max(t0 * 0.02, 200.0)
    init_simplex = np.array([
        [n0_0,        0.0,    t0],
        [n0_0 + 0.05, 0.0,    t0],
        [n0_0,        2000.0, t0],
        [n0_0,        0.0,    t0 + t_step],
    ])
    res = minimize(residual, [n0_0, 0.0, t0], method='Nelder-Mead',
                   options=dict(initial_simplex=init_simplex,
                                maxiter=5000, xatol=0.01, fatol=1e-14))
    A_fit, B_fit, t_fit = res.x
    B_fit = float(max(B_fit, 0.0))
    t_fit = float(np.clip(t_fit, cfg.t_min_nm, cfg.t_max_nm))

    n_u = A_fit + B_fit / wl_u ** 2
    fin = _finalise_dispersive(n_u, t_fit, wn_u, wl_u, norm_u, cfg, emit,
                               label, 'Cauchy')
    if fin is None:
        return None
    phi0, fringe_win, V_u = fin

    rd = dispersion_result_dict([A_fit, B_fit, t_fit, phi0], wl_u, 'cauchy', cfg=cfg)
    emit("%s [Cauchy] A=%.4f B=%.0f nm^2  t=%.2f um  n_mean=%.4f  nt=%.2f um  "
         "V=%.4f  phi0=%.3f  obj=%.2e"
         % (label, A_fit, B_fit, rd['t_um'], rd['n_mean'], rd['nt_um'],
            float(np.mean(V_u)), phi0, res.fun))
    return A_fit, B_fit, t_fit, phi0, fringe_win, wn_u, None, None


# ---------------------------------------------------------------------------
# Fitting: linear n(wn)
# ---------------------------------------------------------------------------

def fit_signal_linear_n(fft_info, label="", cfg=None, log=None):
    """3-D Nelder-Mead over (n0, n1, t) with linear dispersion n(wn) = n0 + n1*wn.

    Returns (t_nm, phi0, n0, n1, fringe_win, wn_u, None, None) or None.
    """
    from scipy.optimize import minimize

    cfg = DEFAULT_CONFIG if cfg is None else cfg
    emit = make_logger(log)
    wn_u = fft_info['wn_u']
    norm_u = fft_info['norm_u']

    seed = _seed_n0_t0(fft_info, label, 'LinearN', cfg, emit)
    if seed is None:
        return None
    n0_0, t0, wl_u, wl_ctr = seed

    def residual(params):
        n0, n1, t = params
        n1 = float(max(n1, 0.0))
        t = float(np.clip(t, cfg.t_min_nm, cfg.t_max_nm))
        n_u = n0 + n1 * wn_u
        return _dispersive_residual(n_u, t, wn_u, wl_u, norm_u, cfg)

    t_step = max(t0 * 0.02, 200.0)
    init_simplex = np.array([
        [n0_0,        0.0,  t0],
        [n0_0 + 0.05, 0.0,  t0],
        [n0_0,        5e-4, t0],
        [n0_0,        0.0,  t0 + t_step],
    ])
    res = minimize(residual, [n0_0, 0.0, t0], method='Nelder-Mead',
                   options=dict(initial_simplex=init_simplex,
                                maxiter=5000, xatol=0.001, fatol=1e-14))
    n0_fit, n1_fit, t_fit = res.x
    n1_fit = float(max(n1_fit, 0.0))
    t_fit = float(np.clip(t_fit, cfg.t_min_nm, cfg.t_max_nm))

    n_u = n0_fit + n1_fit * wn_u
    fin = _finalise_dispersive(n_u, t_fit, wn_u, wl_u, norm_u, cfg, emit,
                               label, 'LinearN')
    if fin is None:
        return None
    phi0, fringe_win, V_u = fin

    rd = dispersion_result_dict([n0_fit, n1_fit, t_fit, phi0], wl_u, 'linear_n', cfg=cfg)
    emit("%s [LinearN] n0=%.4f n1=%+.2e/nm-1  t=%.2f um  n_mean=%.4f  nt=%.2f um  "
         "V=%.4f  phi0=%.3f  obj=%.2e"
         % (label, n0_fit, n1_fit, rd['t_um'], rd['n_mean'], rd['nt_um'],
            float(np.mean(V_u)), phi0, res.fun))
    return t_fit, phi0, n0_fit, n1_fit, fringe_win, wn_u, None, None


# ---------------------------------------------------------------------------
# Fitting: Sellmeier dispersion (B1, C1, B2, C2, t)
# ---------------------------------------------------------------------------

def fit_signal_sellmeier(fft_info, label="", cfg=None, log=None):
    """5-D Nelder-Mead over (B1, C1, B2, C2, t) with two-term Sellmeier dispersion.

    Returns (B1, C1, B2, C2, t_nm, phi0, fringe_win, wn_u, None, None) or None.
    """
    from scipy.optimize import minimize

    cfg = DEFAULT_CONFIG if cfg is None else cfg
    emit = make_logger(log)
    wn_u = fft_info['wn_u']
    norm_u = fft_info['norm_u']

    seed = _seed_n0_t0(fft_info, label, 'Sellmeier', cfg, emit)
    if seed is None:
        return None
    n0_0, t0, wl_u, wl_ctr = seed

    C1_0 = 73.76 ** 2       # ~5441 nm^2 (UV pole)
    C2_0 = 32790.0 ** 2     # ~1.075e9 nm^2 (IR pole)
    B2_0 = 0.0
    B1_0 = (n0_0 ** 2 - 1.0) * (wl_ctr ** 2 - C1_0) / wl_ctr ** 2

    def residual(params):
        B1, C1, B2, C2, t = params
        t = float(np.clip(t, cfg.t_min_nm, cfg.t_max_nm))
        wl2 = wl_u ** 2
        n_sq = 1.0 + B1 * wl2 / (wl2 - C1) + B2 * wl2 / (wl2 - C2)
        n_u = np.sqrt(np.clip(n_sq, 1.0, None))
        n_mean = float(np.mean(n_u))
        if n_mean < 0.5 or n_mean > 10.0:
            return 1e12
        return _dispersive_residual(n_u, t, wn_u, wl_u, norm_u, cfg)

    t_step = max(t0 * 0.02, 200.0)
    init_simplex = np.array([
        [B1_0,       C1_0,       B2_0,       C2_0,       t0],
        [B1_0 + 0.3, C1_0,       B2_0,       C2_0,       t0],
        [B1_0,       C1_0 * 1.5, B2_0,       C2_0,       t0],
        [B1_0,       C1_0,       B2_0 + 0.5, C2_0,       t0],
        [B1_0,       C1_0,       B2_0,       C2_0 * 2.0, t0],
        [B1_0,       C1_0,       B2_0,       C2_0,       t0 + t_step],
    ])
    res = minimize(residual, [B1_0, C1_0, B2_0, C2_0, t0], method='Nelder-Mead',
                   options=dict(initial_simplex=init_simplex,
                                maxiter=15000, xatol=0.01, fatol=1e-14))
    B1_fit, C1_fit, B2_fit, C2_fit, t_fit = res.x
    t_fit = float(np.clip(t_fit, cfg.t_min_nm, cfg.t_max_nm))

    wl2 = wl_u ** 2
    n_sq = 1.0 + B1_fit * wl2 / (wl2 - C1_fit) + B2_fit * wl2 / (wl2 - C2_fit)
    n_u = np.sqrt(np.clip(n_sq, 1.0, None))
    fin = _finalise_dispersive(n_u, t_fit, wn_u, wl_u, norm_u, cfg, emit,
                               label, 'Sellmeier')
    if fin is None:
        return None
    phi0, fringe_win, V_u = fin

    rd = dispersion_result_dict([B1_fit, C1_fit, B2_fit, C2_fit, t_fit, phi0],
                                wl_u, 'sellmeier', cfg=cfg)
    emit("%s [Sellmeier] B1=%.4f C1=%.0f  B2=%.4f C2=%.0f  t=%.2f um  n_mean=%.4f  "
         "nt=%.2f um  V=%.4f  phi0=%.3f  obj=%.2e"
         % (label, B1_fit, C1_fit, B2_fit, C2_fit, rd['t_um'], rd['n_mean'],
            rd['nt_um'], float(np.mean(V_u)), phi0, res.fun))
    return B1_fit, C1_fit, B2_fit, C2_fit, t_fit, phi0, fringe_win, wn_u, None, None


# ---------------------------------------------------------------------------
# Fitting: band-integrated amplitude (constant_n geometry, spread-aware V)
# ---------------------------------------------------------------------------

def fit_signal_band_integral(fft_info, label="", cfg=None, log=None):
    """MSV 'fit' = nt+phi0 from the LSQ (the band integral has no phase), amplitude V
    swapped for the band-integrated value. Returns the constant_n tuple shape
    (nt, V, phi0, fringe_win) so the defringe reconstruction is correctly phased.
    Downstream the extract turns V into n_band = fresnel_n_from_V(V), so the rendered
    curve uses n_band's OWN Fresnel envelope -- it differs from the constant_n curve by
    amplitude AND that envelope, not by height alone. Band width comes from the template."""
    cfg = DEFAULT_CONFIG if cfg is None else cfg
    base = fit_signal_constant_n(fft_info, label=label, cfg=cfg, log=None)
    if base is None:
        make_logger(log)("%s [BandIntegral] skipped: constant_n seed rejected" % (label,))
        return None
    nt_fit, _V_lsq, phi0, fringe_win = base
    V_band = band_integrated_amplitude(
        fft_info['wn_u'], fft_info['norm_u'], nt_fit,
        halfwidth_um=float(fft_info.get('band_halfwidth_um', cfg.notch_halfwidth_um)),
        cfg=cfg)
    return nt_fit, V_band, phi0, fringe_win


# ---------------------------------------------------------------------------
# Per-parameter uncertainties
# ---------------------------------------------------------------------------

def fine_fit_sigma(model_name, params, wn_u, norm_u, cfg=None):
    """Per-parameter 1-sigma uncertainties from the LSQ covariance at the fit optimum.

    Builds the physical-model residual vector r(p) = norm_u - V*cos(4 pi n(p) t wn + phi0),
    computes a two-sided finite-difference Jacobian J (N x k), and derives
    pcov = sigma^2_res * pinv(J^T J) with sigma^2_res = SSE / (N - k).  Returns sigmas for
    the derived quantities (n_mean, t_um, nt_um, phi0) with chain-rule propagation.
    Units: sigma_t_um and sigma_nt_um in um; internal fit math runs with t in nm
    against wn in 1/nm.

    params ordering mirrors the fitters:
      - constant_n : [n, t, phi0]
      - cauchy     : [A, B, t, phi0]
      - linear_n   : [n0, n1, t, phi0]
    """
    cfg = DEFAULT_CONFIG if cfg is None else cfg
    wn_u = np.asarray(wn_u, float)
    norm_u = np.asarray(norm_u, float)
    wl_u = 1.0 / wn_u
    N = wn_u.size
    nan_out = {'n_mean': np.nan, 't_um': np.nan, 'nt_um': np.nan, 'phi0': np.nan}

    if model_name == 'constant_n':
        n_fit, t_fit, phi0_fit = params
        p0 = np.array([n_fit, t_fit, phi0_fit], float)

        def model_fn(p):
            n, t, phi0 = p
            n_arr = np.full_like(wl_u, float(n))
            V_u = fresnel_V(n_arr, wl_u, cfg=cfg)
            phi = 4.0 * np.pi * float(n) * float(t) * wn_u + float(phi0)
            return V_u * np.cos(phi)
    elif model_name == 'cauchy':
        A_fit, B_fit, t_fit, phi0_fit = params
        p0 = np.array([A_fit, B_fit, t_fit, phi0_fit], float)

        def model_fn(p):
            A, B, t, phi0 = p
            n_u = A + B / wl_u ** 2
            V_u = fresnel_V(n_u, wl_u, cfg=cfg)
            phi = 4.0 * np.pi * n_u * float(t) * wn_u + float(phi0)
            return V_u * np.cos(phi)
    elif model_name == 'linear_n':
        n0_fit, n1_fit, t_fit, phi0_fit = params
        p0 = np.array([n0_fit, n1_fit, t_fit, phi0_fit], float)

        def model_fn(p):
            n0, n1, t, phi0 = p
            n_u = n0 + n1 * wn_u
            V_u = fresnel_V(n_u, wl_u, cfg=cfg)
            phi = 4.0 * np.pi * n_u * float(t) * wn_u + float(phi0)
            return V_u * np.cos(phi)
    else:
        return nan_out

    k = p0.size
    if N <= k:
        return {'n_mean': np.inf, 't_um': np.inf, 'nt_um': np.inf, 'phi0': np.inf}

    r0 = norm_u - model_fn(p0)
    sse = float(np.sum(r0 ** 2))
    sigma2_res = sse / max(N - k, 1)

    J = np.zeros((N, k), dtype=float)
    for i in range(k):
        h = 1e-6 * max(abs(p0[i]), 1.0)
        p_plus = p0.copy()
        p_plus[i] += h
        p_minus = p0.copy()
        p_minus[i] -= h
        # residual = norm_u - model; d_residual/dp_i = -d_model/dp_i
        J[:, i] = -(model_fn(p_plus) - model_fn(p_minus)) / (2.0 * h)

    try:
        inv_JTJ = np.linalg.pinv(J.T @ J, rcond=1e-12)
    except np.linalg.LinAlgError:
        return nan_out
    pcov = sigma2_res * inv_JTJ

    diag = np.diag(pcov)
    if not np.all(np.isfinite(diag)) or np.any(diag < 0):
        sigma_res = float(np.sqrt(max(sigma2_res, 0.0)))
        t_abs = abs(p0[1] if model_name == 'constant_n' else p0[2])
        n_floor = abs(p0[0]) if model_name == 'constant_n' else 1.4
        return {
            'n_mean': sigma_res * n_floor,
            't_um':   sigma_res * t_abs * NM_TO_UM,
            'nt_um':  sigma_res * t_abs * n_floor * NM_TO_UM,
            'phi0':   sigma_res,
        }
    sig_raw = np.sqrt(diag)

    wl_bar = float(np.mean(wl_u))
    wn_bar = float(np.mean(wn_u))

    if model_name == 'constant_n':
        n_val, t_val, _ = params
        sig_n = float(sig_raw[0])
        sig_t = float(sig_raw[1])
        sig_p0 = float(sig_raw[2])
        cov_nt = float(pcov[0, 1])
        var_nt = (t_val * sig_n) ** 2 + (n_val * sig_t) ** 2 + 2.0 * n_val * t_val * cov_nt
    elif model_name == 'cauchy':
        A, B, t_val, _ = params
        sig_t = float(sig_raw[2])
        sig_p0 = float(sig_raw[3])
        var_nmean = (sig_raw[0] ** 2
                     + (sig_raw[1] / wl_bar ** 2) ** 2
                     + 2.0 * pcov[0, 1] / wl_bar ** 2)
        sig_n = float(np.sqrt(max(var_nmean, 0.0)))
        n_val = A + B / wl_bar ** 2
        cov_nmean_t = pcov[0, 2] + pcov[1, 2] / wl_bar ** 2
        var_nt = ((t_val * sig_n) ** 2 + (n_val * sig_t) ** 2
                  + 2.0 * n_val * t_val * cov_nmean_t)
    else:  # linear_n
        n0, n1, t_val, _ = params
        sig_t = float(sig_raw[2])
        sig_p0 = float(sig_raw[3])
        var_nmean = (sig_raw[0] ** 2
                     + (wn_bar * sig_raw[1]) ** 2
                     + 2.0 * wn_bar * pcov[0, 1])
        sig_n = float(np.sqrt(max(var_nmean, 0.0)))
        n_val = n0 + n1 * wn_bar
        cov_nmean_t = pcov[0, 2] + wn_bar * pcov[1, 2]
        var_nt = ((t_val * sig_n) ** 2 + (n_val * sig_t) ** 2
                  + 2.0 * n_val * t_val * cov_nmean_t)

    sig_nt = float(np.sqrt(max(var_nt, 0.0)))
    return {'n_mean': sig_n,
            't_um':   sig_t * NM_TO_UM,
            'nt_um':  sig_nt * NM_TO_UM,
            'phi0':   sig_p0}


# ---------------------------------------------------------------------------
# Window tiering (the LSQ half of the source's _run_all_fitters)
# ---------------------------------------------------------------------------

#: model name -> (fitter, params-builder from the fitter's tuple)
_LSQ_FITTERS = {
    'constant_n': fit_signal_constant_n,
    'cauchy': fit_signal_cauchy,
    'linear_n': fit_signal_linear_n,
    'sellmeier': fit_signal_sellmeier,
    'band_integral': fit_signal_band_integral,
}


def _params_from_fit(model, fit_result, wl_ref, cfg):
    """Normalise a fitter's tuple into the `dispersion_n` parameter order.

    `wl_ref` is the reference wavelength (nm) for the constant_n family's
    Fresnel inversion; the dispersive models carry their own n(lam) and ignore
    it.  The source computes it ONCE per channel (mean of 1/wn_u_full) and
    shares it across the full/wide/narrow tiers -- see `run_window_fits`.

    constant_n:  V is passed to the Fresnel inversion RAW.  The source clamps V
    only inside `band_integrated_amplitude`; the inversion has its own internal
    clip on R = V/2 (source :16250-16262 vs :2311).  band_integral keeps the
    min(V, 0.9999) of the source's own band-integral extract (:2311, :2311 ->
    _msv_extract_band_integral :2311/:2307).
    """
    if model in ('constant_n', 'band_integral'):
        nt_fit, V_fit, phi0, _fw = fit_result
        V_for_n = min(float(V_fit), 0.9999) if model == 'band_integral' else float(V_fit)
        n_fit = float(fresnel_n_from_V(V_for_n, wl_ref, cfg=cfg))
        # Source :16291-16311: t_cnt = nt / max(n, 1e-6), UNCLAMPED -- it is not
        # routed through dispersion_n's T_BOUNDS clip.
        t_nm = nt_fit / max(n_fit, 1e-6)
        return [n_fit, t_nm, phi0], 'constant_n', dict(V=float(V_fit), nt_nm=float(nt_fit))
    if model == 'cauchy':
        A, B, t, phi0 = fit_result[:4]
        return [A, B, t, phi0], 'cauchy', {}
    if model == 'linear_n':
        t, phi0, n0, n1 = fit_result[:4]
        return [n0, n1, t, phi0], 'linear_n', {}
    if model == 'sellmeier':
        B1, C1, B2, C2, t, phi0 = fit_result[:6]
        return [B1, C1, B2, C2, t, phi0], 'sellmeier', {}
    raise ValueError("unknown model %r" % (model,))


def _constant_n_result_dict(params, extra):
    """The source's constant_n result values (:16291-16311), not routed through
    `dispersion_result_dict`.

    n is the Fresnel-inverted constant, t is nt/n straight from the fit and
    nt_um is the FITTED n*t -- none of the three passes the T_BOUNDS clip that
    `dispersion_n` applies (the source clips t only inside the optimisers).
    """
    n_val, t_nm, phi0 = params
    return dict(t_um=float(t_nm) * NM_TO_UM,
                phi0=phi0,
                n_mean=float(n_val),
                nt_um=float(extra['nt_nm']) * NM_TO_UM,
                n_const=n_val)


def _averaging_wl_grid(wl_full, wn_u_full, emit, label):
    """The wavelength grid n_mean is averaged over: the source's `wl`.

    `wl_full` is the FULL original detector wavelength grid (nm) handed to
    `_run_all_fitters`; every tier's n_mean/nt_um is averaged over it, not over
    the window slice of the uniform wavenumber resample (source :16097-16098,
    :16654-16694).  Callers that have no original grid (a caller working purely
    in wavenumber space) fall back to 1/wn_u_full, the closest full-span stand-in.
    """
    if wl_full is None:
        return 1.0 / wn_u_full
    wl = np.asarray(wl_full, float).ravel()
    if wl.size and np.all(np.isfinite(wl)) and np.all(wl > 0):
        return wl
    emit("%s averaging grid unusable (%d points); using 1/wn_u_full"
         % (label, wl.size))
    return 1.0 / wn_u_full


def run_window_fits(fft_info, norm_u_full, wn_u_full, cfg=None, label='',
                    log=None, method='lsq', models=None, wl_full=None):
    """Run the configured dispersion models over the standard window tiers.

    Window tiers (source `_run_all_fitters`):
      full   - the whole spectrum
      wide   - cfg.wide_lo_cm .. cfg.wide_hi_cm
      narrow - cfg.fit_wl_min_nm .. cfg.fit_wl_max_nm
      fine   - cfg.fine_width_cm centred on cfg.fine_center_cm

    `wl_full` is the full original detector wavelength grid in nm (the source's
    `wl`).  Every tier's reported n_mean / nt_um is the average of n(lam) over
    THAT grid, not over the tier's slice of the uniform wavenumber resample.

    Returns {model: {window: result_dict}}.  Each result_dict is
    `dispersion_result_dict` plus 'sigma' (from `fine_fit_sigma`) and, for the
    constant_n family, the fitted V and n*t in nm.

    Narrow-window gating (SPARTA divergence): the source skips narrow fits for
    pre-Nov-2025 data, whose narrow band overlaps the fine band, deciding that
    from a parsed folder date.  Here the same call is made from the config
    itself -- narrow is skipped when the fine window's centre wavelength falls
    inside the narrow band, which is exactly the redundancy the source was
    guarding against, with no date magic.
    """
    cfg = DEFAULT_CONFIG if cfg is None else cfg
    emit = make_logger(log)
    if method != 'lsq':
        raise ValueError("run_window_fits: only the 'lsq' method is vendored "
                         "(got %r); the source's logcurv/autocorr/phasematch "
                         "fitters are not part of the SPARTA core" % (method,))
    models = tuple(cfg.msv_models) if models is None else tuple(models)

    wn_u_full = np.asarray(wn_u_full, float)
    norm_u_full = np.asarray(norm_u_full, float)
    wl_avg = _averaging_wl_grid(wl_full, wn_u_full, emit, label)

    wide_mask = (wn_u_full >= cfg.wide_lo) & (wn_u_full <= cfg.wide_hi)
    wn_lo_narrow = 1.0 / cfg.fit_wl_max_nm
    wn_hi_narrow = 1.0 / cfg.fit_wl_min_nm
    narrow_mask = (wn_u_full >= wn_lo_narrow) & (wn_u_full <= wn_hi_narrow)
    fine_mask = (wn_u_full >= cfg.fine_wn_lo) & (wn_u_full <= cfg.fine_wn_hi)

    fine_center_wn = cfg.fine_center_cm * 1e-7
    fine_inside_narrow = wn_lo_narrow <= fine_center_wn <= wn_hi_narrow
    narrow_ok = (not fine_inside_narrow) and int(narrow_mask.sum()) >= cfg.fit_min_points
    fine_ok = int(fine_mask.sum()) >= cfg.fit_min_points

    windows = [('full', np.ones_like(wn_u_full, dtype=bool)),
               ('wide', wide_mask)]
    if narrow_ok:
        windows.append(('narrow', narrow_mask))
    if fine_ok:
        windows.append(('fine', fine_mask))
    emit("%s windows: full=%d wide=%d narrow=%d%s fine=%d%s"
         % (label, wn_u_full.size, int(wide_mask.sum()), int(narrow_mask.sum()),
            '' if narrow_ok else ' [skipped]', int(fine_mask.sum()),
            '' if fine_ok else ' [skipped]'))

    # constant_n Fresnel reference wavelength (source :16245, :16260): ONE value
    # for full/wide/narrow, taken over the whole uniform grid; the fine tier gets
    # its own.  A per-window wl_ref would move n for every dispersive diamond
    # model (cauchy / oscillator / eremets).
    wl_ref_shared = float(np.mean(1.0 / wn_u_full)) if wn_u_full.size else 0.0
    wl_ref_fine = (float(np.mean(1.0 / wn_u_full[fine_mask]))
                   if fine_ok else wl_ref_shared)

    out = {}
    for model in models:
        fitter = _LSQ_FITTERS.get(model)
        if fitter is None:
            raise ValueError("run_window_fits: unknown model %r" % (model,))
        out[model] = {}
        for wname, mask in windows:
            if int(mask.sum()) < cfg.fit_min_points:
                continue
            sub = dict(fft_info)
            sub['wn_u'] = wn_u_full[mask]
            sub['norm_u'] = norm_u_full[mask]
            sub['wn_u_full'] = sub['wn_u']
            sub['norm_u_full'] = sub['norm_u']
            fit_result = fitter(sub, label="%s %s" % (label, wname), cfg=cfg, log=log)
            if fit_result is None:
                continue
            wl_ref = wl_ref_fine if wname == 'fine' else wl_ref_shared
            params, disp_model, extra = _params_from_fit(model, fit_result,
                                                         wl_ref, cfg)
            if disp_model == 'constant_n':
                rd = _constant_n_result_dict(params, extra)
            else:
                rd = dispersion_result_dict(params, wl_avg, disp_model, cfg=cfg)
            rd.update(extra)
            rd['model'] = model
            rd['window'] = wname
            rd['n_points'] = int(mask.sum())
            rd['sigma'] = fine_fit_sigma(disp_model, params, sub['wn_u'],
                                         sub['norm_u'], cfg=cfg)
            out[model][wname] = rd
    return out


__all__ = ['dispersion_n', 'dispersion_result_dict', 'lstsq_V_n_t_errors',
           'find_fit_window', 'fit_signal_constant_n', 'fit_signal_cauchy',
           'fit_signal_linear_n', 'fit_signal_sellmeier',
           'fit_signal_band_integral', 'fine_fit_sigma', 'run_window_fits']
