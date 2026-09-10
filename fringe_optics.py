"""
fringe_optics.py -- Fresnel / dispersion optics for DAC fringe analysis.

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
    cauchy_n                     (:987)   Cauchy dispersion n(lam) = A + B/lam^2
    vinet_density                (:215)   Vinet EOS density, default = diamond
    bm3_v_ratio / bm3_p_from_v_ratio (:231/:243)  3rd-order Birch-Murnaghan
    n_diamond_oscillator         (:992)   single-oscillator diamond n(P, lam)
    n_diamond / cauchy_n_diamond (:1007/:1022)  the four diamond models
    fresnel_V / fresnel_n_from_V (:1027/:1036)  visibility <-> sample index
    solve_paths                  (:1049)  A-conserving clamp cascade
    airy_factor                  (:1236)  1 + V*cos(phi + phi0)
    local_noise_floor            (:1253)  Hampel median + MAD noise floor

SPARTA adaptations
  * The source dispatches `n_diamond` on the mutable module globals
    DIAMOND_MODEL / DIAMOND_PRESSURE_GPA; here the model and pressure arrive
    via a frozen FringeConfig (or explicit keyword), so there is no global
    state and no import-order hazard.
  * No import side effects, no printing, numpy + scipy + stdlib only,
    Python 3.8 compatible.
  * Every physical-constant citation from the source is preserved verbatim.

Unit zones (source module convention): values that multiply wn[1/nm] or divide
wl[nm] are in nm; values stored, exported or displayed are in um.
"""

import numpy as np
# scipy.optimize and scipy.ndimage are imported inside the two functions
# that use them: importing this module costs a second of scipy otherwise,
# and most sessions never reach an equation of state or a Hampel pass.
from scipy.special import erfinv

from fringe_config import DEFAULT_CONFIG


# ---------------------------------------------------------------------------
# Diamond constants -- citations verbatim from defringe_dac.py:126-150
# ---------------------------------------------------------------------------

# Cauchy (current default)
N_DIAMOND_A     = 2.380         # Cauchy A for diamond (n at infinite lam)
N_DIAMOND_B     = 13000.0       # Cauchy B for diamond (nm^2); gives n~2.40 at 800 nm

# Constant - Phillip & Taft (1964) at 589 nm
N_DIAMOND_CONST = 2.4168

# Single-oscillator model for diamond: n^2 - 1 = F1 / (w1^2 - w^2)
# w1(P) = w0 + K*P;  F1(P) = C * w1(P) * rho(P)
#
# w0 and F1(P=0) from Eggert, Goettel & Silvera, EPL 11, 775 (1990),
#   who fit Edwards & Ochoa (1981) ambient data to single-oscillator form.
# K from Eremets et al., Int. J. High Press. Res. 9, 347 (1992),
#   who measured n(P,lambda) up to 40 GPa via interference fringes.
# EOS: Vinet EOS from Dewaele et al., Phys. Rev. B 77, 094106 (2008), Table III.
#   X-ray diffraction in neon medium, 0-80 GPa at 298 K.
#   K0 = isothermal conversion of Brillouin data (Vogelgesang et al. 1996).
DIAMOND_W0    = 84900.0        # cm^-1, resonance frequency at P=0 (Eggert 1990)
DIAMOND_F1_0  = 3.35e10        # (cm^-1)^2, oscillator strength at P=0 (Eggert 1990)
DIAMOND_K     = 218.0          # cm^-1 GPa^-1, dw1/dP (Eremets 1992)
DIAMOND_V0    = 5.6693         # A^3/atom, ambient atomic volume (Dewaele 2008)
DIAMOND_K0    = 444.5          # GPa, isothermal bulk modulus (Dewaele 2008)
DIAMOND_K0P   = 4.18           # K0' (Dewaele 2008)
DIAMOND_RHO0  = 12.011 / (6.02214076e23 * DIAMOND_V0 * 1e-24)  # g/cm^3; M_C = 12.011 g/mol (IUPAC)
DIAMOND_C     = DIAMOND_F1_0 / (DIAMOND_W0 * DIAMOND_RHO0)     # F1 = C*w1*rho

# Backwards-compatible private aliases matching the source module's names, so
# a reader diffing against defringe_dac.py finds the same identifiers.
_DIAMOND_W0, _DIAMOND_F1_0, _DIAMOND_K = DIAMOND_W0, DIAMOND_F1_0, DIAMOND_K
_DIAMOND_V0, _DIAMOND_K0, _DIAMOND_K0P = DIAMOND_V0, DIAMOND_K0, DIAMOND_K0P
_DIAMOND_RHO0, _DIAMOND_C = DIAMOND_RHO0, DIAMOND_C


# ---------------------------------------------------------------------------
# Equations of state (shared primitives; fringe_materials builds on these)
# ---------------------------------------------------------------------------

def vinet_density(P_gpa, K0=DIAMOND_K0, K0p=DIAMOND_K0P, rho0=DIAMOND_RHO0):
    """Density at pressure P via the Vinet EOS (diamond defaults, Dewaele 2008).

    Vinet: P = 3 K0 x^-2 (1-x) exp[eta(1-x)],  eta = 1.5(K0'-1),  x = (V/V0)^(1/3).
    Returns rho(P) = rho0 / x^3.
    """
    if P_gpa <= 0:
        return rho0
    eta = 1.5 * (K0p - 1.0)

    from scipy.optimize import brentq

    def _vinet_residual(x):
        return 3.0 * K0 * x ** (-2) * (1.0 - x) * np.exp(eta * (1.0 - x)) - P_gpa

    x_sol = brentq(_vinet_residual, 0.3, 1.0)   # x = (V/V0)^(1/3), between 0.3 and 1
    return rho0 / x_sol ** 3


def bm3_v_ratio(P_gpa, K0, K0p):
    """V/V0 at pressure P via the 3rd-order Birch-Murnaghan EOS."""
    if P_gpa <= 0:
        return 1.0

    from scipy.optimize import brentq

    def _bm3(x):   # x = V0/V
        f = 0.5 * (x ** (2.0 / 3.0) - 1.0)
        return 3.0 * K0 * f * (1.0 + 2.0 * f) ** 2.5 * (1.0 + 1.5 * (K0p - 4.0) * f) - P_gpa

    x_sol = brentq(_bm3, 1.0, 5.0)
    return 1.0 / x_sol   # V/V0


def bm3_p_from_v_ratio(v_ratio, K0, K0p):
    """Pressure (GPa) from V/V0 via the 3rd-order Birch-Murnaghan EOS."""
    x = 1.0 / v_ratio    # V0/V
    f = 0.5 * (x ** (2.0 / 3.0) - 1.0)
    return 3.0 * K0 * f * (1.0 + 2.0 * f) ** 2.5 * (1.0 + 1.5 * (K0p - 4.0) * f)


# ---------------------------------------------------------------------------
# Dispersion models
# ---------------------------------------------------------------------------

def cauchy_n(wl_nm, A, B):
    """Cauchy dispersion: n(lam) = A + B/lam^2,  lam in nm."""
    return A + B / (wl_nm ** 2)


def n_diamond_oscillator(wl_nm, P_gpa):
    """Single-oscillator diamond n at pressure P.

    Eggert (1990) ambient parameters + Eremets (1992) pressure shift.
    n^2 - 1 = F1(P) / (w1(P)^2 - w^2)
    """
    wl = np.asarray(wl_nm, float)
    wn = 1.0e7 / wl                                   # photon wavenumber, cm^-1
    w1 = DIAMOND_W0 + DIAMOND_K * P_gpa               # resonance at pressure
    rho = vinet_density(P_gpa)
    F1 = DIAMOND_C * w1 * rho
    n_sq = 1.0 + F1 / (w1 ** 2 - wn ** 2)
    return np.sqrt(np.clip(n_sq, 1.0, None))


def n_diamond(wl_nm, cfg=None, model=None, pressure_gpa=None):
    """Diamond refractive index -- dispatches to the configured model.

    `model` / `pressure_gpa` override the corresponding FringeConfig fields;
    `cfg=None` uses `fringe_config.DEFAULT_CONFIG` (model 'constant', P=0),
    which is the source module's default state.
    """
    cfg = DEFAULT_CONFIG if cfg is None else cfg
    model = cfg.diamond_model if model is None else model
    P_gpa = cfg.diamond_pressure_gpa if pressure_gpa is None else pressure_gpa
    wl = np.asarray(wl_nm, float)
    if model == 'constant':
        return np.full_like(wl, N_DIAMOND_CONST)
    elif model == 'cauchy':
        return N_DIAMOND_A + N_DIAMOND_B / wl ** 2
    elif model == 'oscillator':
        return n_diamond_oscillator(wl, 0.0)
    elif model == 'eremets':
        return n_diamond_oscillator(wl, P_gpa)
    else:
        raise ValueError("Unknown diamond model: %r (expected one of "
                         "'constant', 'cauchy', 'oscillator', 'eremets')" % (model,))


def cauchy_n_diamond(wl_nm, cfg=None):
    """Diamond refractive index -- delegates to n_diamond() dispatcher."""
    return n_diamond(wl_nm, cfg=cfg)


# ---------------------------------------------------------------------------
# Fresnel
# ---------------------------------------------------------------------------

def fresnel_V(n_sample, wl_nm, cfg=None):
    """Fringe visibility from Fresnel (low-finesse, equal mirrors):
       R = ((nd - ns)/(nd + ns))^2,  V = 2R.  nd from the diamond model.
    """
    nd = cauchy_n_diamond(wl_nm, cfg=cfg)
    R = ((nd - n_sample) / (nd + n_sample)) ** 2
    return 2.0 * R


def fresnel_n_from_V(V, wl_nm, cfg=None):
    """Infer n_sample from fringe visibility V via inverse Fresnel.
    Accepts scalar or array V; wl_nm is a scalar reference wavelength.
    """
    nd = float(cauchy_n_diamond(wl_nm, cfg=cfg))
    scalar = np.ndim(V) == 0
    V = np.atleast_1d(np.asarray(V, dtype=float))
    R = np.clip(V / 2.0, 0.0, 0.9999)
    r = np.sqrt(R)
    n = nd * (1.0 - r) / (1.0 + r)
    return float(n[0]) if scalar else n


# ---------------------------------------------------------------------------
# Peak solve
# ---------------------------------------------------------------------------

def solve_paths(A, C, iii, n_layer2, n_medium):
    """Closed-form peak solve -- the pure core shared by the live GUI solve and the Results-plot
    re-derivation under alternative material indices. Given the three measured optical paths (um)
        A   = n_s*t                             (sample)
        C   = n_layer2*(d1+d2) + n_s*t          (loaded sample-diamond)
        iii = n_medium*L,  L = d1+t+d2          (medium etalon)
    and the fixed indices n_layer2, n_medium, returns dict(n_s, t_s, t_layer2, L, warns) with the
    physical-bound clamps applied as an A-CONSERVING CASCADE: each clamp recomputes downstream so
    the returned tuple stays mutually consistent AND conserves the sample optical path A = n_s*t_s
    wherever possible. Clamp order / semantics:
        t_layer2 >= 0  (A <= C): floor t_layer2, recompute t_s = L - t_layer2.
        t_s >= 0       : floor t_s. This is the ONE unavoidable loss -- t_s=0 makes A=n_s*t_s=0,
                         so A cannot be recovered (a zero-thickness sample has no peak).
        n_s >= 1       : floor n_s, then recompute t_s = A/n_s so n_s*t_s = A still holds (absorb
                         the floor into the geometric thickness, keep the measured path A).
    Because A is conserved (except the t_s=0 case), the stored solved tuple is a lossless encoding
    of (A, C, iii) at the recorded n_layer2/n_medium, so it can be re-solved exactly under a new
    medium index.
    `warns` is a list of the clamp messages that fired. Returns None on a non-positive index."""
    if n_layer2 <= 0 or n_medium <= 0:
        return None
    L = iii / n_medium                  # d1+t+d2, the whole gap (iii, n_medium > 0 -> L >= 0)
    t_layer2 = (C - A) / n_layer2       # d1+d2, the medium alone
    t_s = L - t_layer2                  # t, the sample
    warns = []
    if t_layer2 < 0.0:
        t_layer2 = 0.0
        t_s = L - t_layer2              # recompute t_s against the clamped medium thickness
        warns.append('rectangle right of sample-diamond -> t_layer2 floored to 0')
    if t_s < 0.0:
        t_s = 0.0                       # unrecoverable: A = n_s*t_s is now 0 (see docstring)
        warns.append('t_s floored to 0')
    # n_s from the (possibly clamped) t_s. Floor to 1 conserving A: t_s = A/n_s = A.
    n_s = (A / t_s) if t_s > 0 else 1.0
    if n_s < 1.0:
        n_s = 1.0
        t_s = A / n_s                   # = A; keeps n_s*t_s = A (t_s stays < L since A < t_s <= L)
        warns.append('n_s floored to 1')
    return dict(n_s=n_s, t_s=t_s, t_layer2=t_layer2, L=L, warns=warns)


# ---------------------------------------------------------------------------
# Forward fringe model
# ---------------------------------------------------------------------------

def airy_factor(wl_nm, A, B, t_nm, phi0=0.0, cfg=None):
    """1 + V(lam)*cos(phi + phi0), with V(lam) from Fresnel and phi = 4*pi*n(lam)*t/lam.

    Both wl and t in nm -- fitter-zone helper. Callers in the um zone convert
    via the boundary helpers documented at the top of the file.
    """
    n = cauchy_n(wl_nm, A, B)
    V = fresnel_V(n, wl_nm, cfg=cfg)
    phi = 4.0 * np.pi * n * t_nm / wl_nm + phi0
    return 1.0 + V * np.cos(phi), V


# ---------------------------------------------------------------------------
# Noise estimation
# ---------------------------------------------------------------------------

MAD_TO_SIGMA = 1.0 / (np.sqrt(2) * erfinv(0.5))   # ~ 1.4826


def local_noise_floor(data, window=7, n_sigma=3.0):
    """Per-pixel noise floor via Hampel filter: median baseline + robust MAD spread.

    SPARTA addition: `window` must be a positive integer -- scipy's median_filter
    silently accepts 0/negative sizes on some versions and returns nonsense.
    """
    window = int(window)
    if window < 1:
        raise ValueError("local_noise_floor: window must be >= 1 (got %r)" % (window,))
    data = np.asarray(data, float)
    from scipy.ndimage import median_filter

    med = median_filter(data, size=window)
    mad = median_filter(np.abs(data - med), size=window)
    return n_sigma * MAD_TO_SIGMA * mad
