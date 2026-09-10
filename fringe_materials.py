# -*- coding: utf-8 -*-
"""
fringe_materials.py -- refractive-index and equation-of-state library for
DAC pressure media, samples, anvils and gasket.

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

Every physical constant below is copied with its source citation VERBATIM from
defringe_dac.py:126-935.  Nothing here is refitted, and no constant has been
changed.  Do not edit a value without editing its citation.

Contents (source line refs are into defringe_dac.py):
    n_kcl / n_lif / n_air        (:165/:175/:181)  ambient Sellmeier indices
    ambient_n_stats              (:188)
    diamond_n_stats              (:203)
    lif_n_lorentz_lorenz         (:269)  Lorentz-Lorenz strain polarizability
    argon block                  (:308-:641)  Dewaele/Grimsditch and constant-LL
    bm3_volume_ratio / vinet_volume_ratio (:652/:658)
    EOS_MODELS registry          (:682)
    MEDIUM_N_OF_P registry       (:709)
    model docs                   (:719-:910)
    reference_pmax               (:913)

SPARTA adaptations
  * Sample-specific bookkeeping is NOT vendored: the source's folder->xlsx
    aliases, pressure-medium aliases, fringe-exclude lists, xlsx sidecar
    readers and per-dataset colour/marker overrides all live in SPARTA's own
    session config instead.
  * Vinet / Birch-Murnaghan primitives live in `fringe_optics` (shared with the
    diamond model) and are imported here rather than duplicated.
  * numpy + scipy + stdlib only; no pandas, no matplotlib; Python 3.8 clean.
"""

import numpy as np
# scipy.integrate and scipy.optimize are imported inside the four
# functions that use them (P6): the EOS inversions are a rare path, and
# every fringe import walks through this module.

from fringe_optics import (DIAMOND_K0, DIAMOND_K0P, N_DIAMOND_CONST,
                           bm3_p_from_v_ratio, bm3_v_ratio, n_diamond,
                           vinet_density)
from fringe_optics import (DIAMOND_F1_0, DIAMOND_K, DIAMOND_RHO0, DIAMOND_V0,
                           DIAMOND_W0)


# ---------------------------------------------------------------------------
# Gasket / sample / medium bulk moduli
# ---------------------------------------------------------------------------

# Rhenium gasket EOS (3rd-order Birch-Murnaghan)
_RE_K0 = 352.6    # GPa, bulk modulus
_RE_K0P = 4.56    # K0', pressure derivative of bulk modulus

# LiF sample EOS (3rd-order Birch-Murnaghan, Lee et al. 2026 JPCS)
_LIF_K0 = 73.3    # GPa, bulk modulus
_LIF_K0P = 3.97   # K0', pressure derivative of bulk modulus

# KCl pressure medium EOS (3rd-order Birch-Murnaghan, Chidester et al. 2021 PRB 104 094107)
_KCL_K0 = 24.0    # GPa, bulk modulus
_KCL_K0P = 4.56   # K0', pressure derivative of bulk modulus


# ---------------------------------------------------------------------------
# Ambient refractive index of pressure media (Li 1976, refractiveindex.info)
# ---------------------------------------------------------------------------

def n_kcl(wl_nm):
    """KCl refractive index at ambient P (Li 1976 Sellmeier). wl_nm in nm."""
    lam2 = (np.asarray(wl_nm, float) / 1000.0) ** 2  # µm²
    n2 = (1 + 0.26486
          + 0.30523 * lam2 / (lam2 - 0.100 ** 2)
          + 0.41620 * lam2 / (lam2 - 0.131 ** 2)
          + 0.18870 * lam2 / (lam2 - 0.162 ** 2)
          + 2.6200 * lam2 / (lam2 - 70.42 ** 2))
    return np.sqrt(np.clip(n2, 1.0, None))


def n_lif(wl_nm):
    """LiF refractive index at ambient P (Li 1976 Sellmeier). wl_nm in nm."""
    lam2 = (np.asarray(wl_nm, float) / 1000.0) ** 2
    n2 = 1 + 0.92549 * lam2 / (lam2 - 0.07376 ** 2) + 6.96747 * lam2 / (lam2 - 32.790 ** 2)
    return np.sqrt(np.clip(n2, 1.0, None))


def n_air(wl_nm):
    """Air refractive index (~1.0003, effectively non-dispersive over vis/NIR).
    Used for an air-medium reference line; there is no high-pressure EOS for air."""
    return np.full_like(np.asarray(wl_nm, float), 1.000273)


AMBIENT_N_FUNC = {'KCl': n_kcl, 'LiF': n_lif, 'air': n_air}


def ambient_n_stats(material, wn_lo_nm1=9000e-7, wn_hi_nm1=21500e-7, npts=200):
    """Compute ambient n statistics over a wavenumber range.

    Returns dict with n_mean, n_min, n_max, wl_nm (array), n_arr (array),
    or None if material is not recognized.
    """
    func = AMBIENT_N_FUNC.get(material)
    if func is None:
        return None
    wl_nm = np.linspace(1.0 / wn_hi_nm1, 1.0 / wn_lo_nm1, npts)
    n_arr = func(wl_nm)
    return dict(n_mean=float(np.mean(n_arr)), n_min=float(np.min(n_arr)),
                n_max=float(np.max(n_arr)), wl_nm=wl_nm, n_arr=n_arr)


def diamond_n_stats(wn_lo_nm1=9000e-7, wn_hi_nm1=21500e-7, npts=200, cfg=None):
    """Compute diamond n statistics over a wavenumber range.

    SPARTA divergence: the source reads the DIAMOND_PRESSURE_GPA global; the
    model and pressure arrive via `cfg` here.
    Returns dict with n_mean, n_min, n_max.
    """
    wl_nm = np.linspace(1.0 / wn_hi_nm1, 1.0 / wn_lo_nm1, npts)
    n_arr = n_diamond(wl_nm, cfg=cfg)
    return dict(n_mean=float(np.mean(n_arr)), n_min=float(np.min(n_arr)),
                n_max=float(np.max(n_arr)))


# ---------------------------------------------------------------------------
# LiF at pressure
# ---------------------------------------------------------------------------

# LiF: density & refractive index from Spataru, Shulenburger, Benedict 2015
# (PRB 92 245117).  Density (g/cc), n.  Convert density → pressure via BM3
# using LiF ρ₀ = 2.640 g/cc.
_LIF_RHO0 = 2.640
_LIF_SPATARU_RHO_N = [
    (2.643, 1.423),
    (4.118, 1.477),
    (4.888, 1.502),
    (5.470, 1.519),
    (5.954, 1.530),
    (6.383, 1.542),
]

# Hawreliak, Winey, Gupta 2024 Lorentz-Lorenz strain polarizability parameter
# α/α₀ = (V/V₀)^Λ, Λ = 0.73 ± 0.02
_LIF_HAWRELIAK_LAMBDA = 0.73
_LIF_HAWRELIAK_LAMBDA_ERR = 0.02


def lif_n_lorentz_lorenz(P_gpa, n0, Lambda=_LIF_HAWRELIAK_LAMBDA):
    """LiF refractive index at pressure P via the Lorentz-Lorenz model with
    strain polarizability α/α₀ = (V/V₀)^Λ (Hawreliak et al. 2024).

    Parameters
    ----------
    P_gpa : array_like
        Pressure in GPa.
    n0 : float
        Ambient refractive index.
    Lambda : float
        Strain polarizability parameter.
    """
    P_arr = np.atleast_1d(np.asarray(P_gpa, dtype=float))
    v_ratios = np.array([bm3_v_ratio(p, _LIF_K0, _LIF_K0P) for p in P_arr])
    f0 = (n0 ** 2 - 1) / (n0 ** 2 + 2)
    # f(n)/f(n0) = (α/V) / (α₀/V₀) = (V/V₀)^(Λ-1)
    f_n = f0 * v_ratios ** (Lambda - 1.0)
    f_n = np.clip(f_n, 0, 0.9999)
    n_sq = (2 * f_n + 1) / (1 - f_n)
    return np.sqrt(np.clip(n_sq, 1.0, None))


# KCl: refractive index vs pressure from Proctor et al. 2024 (Phys. Fluids).
# Pressure (GPa), n.  Fig. 4(c) raw data and Lorentz-Lorenz fit values.
_KCL_PROCTOR_RAW = [
    (0.527, 1.607), (0.617, 1.545), (0.845, 1.558), (1.377, 1.507),
    (1.776, 1.666), (3.685, 1.598), (4.217, 1.599), (4.407, 1.706),
    (4.929, 1.721), (5.129, 1.641), (5.442, 1.592), (5.794, 1.600),
    (6.278, 1.658), (6.919, 1.911),
]
_KCL_PROCTOR_LL = [
    (0.527, 1.484), (0.617, 1.475), (0.845, 1.486), (1.377, 1.501),
    (1.776, 1.538), (1.919, 1.521), (3.685, 1.648), (4.217, 1.663),
    (4.407, 1.699), (4.920, 1.707), (5.129, 1.709), (5.442, 1.702),
    (5.803, 1.702), (6.278, 1.720), (6.910, 1.792),
]


# ---------------------------------------------------------------------------
# Argon pressure medium: n(P, λ) from an EOS + a one-electron dielectric model.
#
# Two papers chained together:
#   (1) Dewaele et al., Sci. Rep. 11, 15192 (2021), Eqs. (2)-(5) + Table 2.
#       Quasi-harmonic Mie-Grüneisen-Debye EOS for fcc Ar gives P(V, T); we
#       invert it numerically for V at the sample pressure, then ρ = M/(N_A·V).
#   (2) Grimsditch, Loubeyre & Polian, PRB 33, 7192 (1986), Eqs. (3)-(4).
#       A Clausius-Mossotti / one-electron form giving n from ρ and photon
#       energy E, via a density-dependent band gap E_b(ρ).
#
# NOTE on Eq. (3).  As printed it reads
#     3(n²-1)/(n²+2) = 5.4/(E_b²-E²) + 3.125e-4
# which taken literally gives n ≈ 1.007 instead of the ~1.2-1.6 of the paper's own
# Table I, and is nearly flat in ρ.  The omission is a leading factor A·ρ on the
# right-hand side, made explicit in the primary source that Grimsditch's Eq. (3)
# condenses — Itié & Le Toullec, J. Phys. Colloques 45, C8-53 (1984), their Eq. (3):
#     ε₁(E,ρ) − 1 = A·ρ·[f_b/(E_b²−E²) + f_c/(E_c²−E²)],   A = 4πℏ²N_a e²/m_e
# with ε₁ − 1 = 3(n²−1)/(n²+2) (their Eq. 4, Clausius-Mossotti).  So the printed
# "5.4" is NOT an error: it is f_b, the outer-shell oscillator strength.
#
# A is not a constant of nature in its own right — it is shorthand for a product of
# ordinary physical constants (as R = N_a·k_B is), so it is spelled out from CODATA
# values in the code rather than hardcoded:
#     A = 4πℏ²N_a e²/m_e = 830.358 eV²·cm³/mol
# Itié's ρ is MOLAR (mol/cm³) while Grimsditch's Table I tabulates MASS density
# (g/cm³), so for argon the working coefficient is A/M_Ar with M_Ar = 39.948 g/mol:
#     A/M_Ar = 20.7860 eV²·cm³/g
#
# PROVENANCE of every constant used below — "computed" means from physical constants,
# "fitted" means the cited authors fitted it to their own measurements:
#   A                          computed (CODATA)
#   f_b = 5.4                  fitted — Itié & Le Toullec, to low-T xenon n(ρ,E)
#   3.125e-4                   fitted — Grimsditch, argon core term (NOT Itié's xenon
#                              f_c/(E_c²−E²) ≈ 1.4e-3, which fits argon ~30× worse)
#   E_b(ρ) coefficients        fitted — Grimsditch, an explicitly "empiric law"
#   V₀ K₀ K₀′ θ_D0 γ₀ (EOS)    fitted — Dewaele et al., to X-ray P–V data
#   P_melt(T) coefficients     Datchi 2000 melting curve (via Jia 2008 Eq. 3)
#   liquid n(P) cubic          measured — Lallemand & Vidal 1977, via Grimsditch Table I
#                              (see n_argon_liquid / the liquid-branch block below)
# So the model is not parameter-free — it is built from OTHER papers' published fits,
# with nothing refitted to the data it is checked against below.  (An earlier version
# of this code used a coefficient fitted here to Table I itself; that was circular and
# has been removed.)
#
# VERIFICATION — nothing below is tuned to the table it is compared with:
#   * A reproduces Itié's own xenon table to ≤0.0026 in n, using their published
#     f_b = 5.4, E_b0 = 12.33 eV, E₁ = 0.381 eV, β = 1.8.
#   * For argon, A/M_Ar with the printed f_b = 5.4 and 3.125e-4 reproduces Table I
#     to ≤0.0024 (rms 0.0007), below its 3-decimal precision.  Fitting f_b freely
#     against argon returns 5.3990 — recovering the published 5.4 to three figures,
#     which is the strongest single check that Eq. (3) is right as printed.
#   * Chained to the Dewaele EOS (which independently matches Grimsditch's tabulated
#     ρ to ~1%), the full P → n path reproduces Table I to ≤0.0053 (rms 0.0027) on
#     the solid branch over 2.0-33.6 GPa.
# Checked against a 14-row sample of Table I spanning ρ = 1.03-3.94 g/cm³; the
# remaining ~84 rows have not been checked.
# ---------------------------------------------------------------------------
_AR_V0 = 38.0          # Å³/atom, ambient-P 0 K atomic volume (Dewaele Table 2)
_AR_K0 = 2.65          # GPa, bulk modulus at ambient P, 0 K
_AR_K0P = 7.423        # K0'
_AR_THETA0 = 93.3      # K, Debye temperature at low T / ambient P
_AR_GAMMA_A = 2.20     # γ(V) = 2.20·(V/V0) + 0.5   (Dewaele Eq. 4)
_AR_GAMMA_B = 0.5
_AR_M = 39.948         # g/mol, molar mass (IUPAC)
_AR_T_REF = 296.0      # K, room temperature of the Dewaele 296 K isotherm

# --- Eq. (3) constants -----------------------------------------------------
# "A" is not a measured constant of its own: it is shorthand for a product of ordinary
# physical constants, A = 4πℏ²N_a e²/m_e, the way R = N_a·k_B is shorthand.  So it is
# spelled out from CODATA 2018 values here rather than hardcoded as a literal, which
# keeps it checkable and visibly distinct from the FITTED constants below.
# Unit note: the paper works in Gaussian units, where 4πe²(Gaussian) → e²/ε₀ in SI.
_CODATA_HBAR = 1.054571817e-34    # J·s
_CODATA_E = 1.602176634e-19       # C (also the J→eV conversion factor)
_CODATA_ME = 9.1093837015e-31     # kg
_CODATA_NA = 6.02214076e23        # 1/mol
_CODATA_EPS0 = 8.8541878128e-12   # F/m
# A in J²·m³/mol, then → eV²·cm³/mol:  /e² converts J²→eV², ×1e6 converts m³→cm³.
_AR_A_EV2_CM3 = (_CODATA_HBAR ** 2 * _CODATA_NA * _CODATA_E ** 2
                 / (_CODATA_ME * _CODATA_EPS0)) / _CODATA_E ** 2 * 1e6   # = 830.358
# Fitted (not computed) constants — see the provenance table above.
_AR_FB = 5.4              # outer-shell oscillator strength (the "5.4" of Eq. 3)
_AR_GRIM_C2 = 3.125e-4    # additive core-electron term of Eq. (3), as printed
# Working coefficient for MASS density in g/cm³ (Grimsditch's Table I convention).
_AR_A_MASS = _AR_A_EV2_CM3 / _AR_M    # eV² cm³/g = 20.7860

# --- Melting curve (liquid/solid phase boundary) ---------------------------
# fcc Ar crystallisation pressure vs temperature, the Datchi melting curve:
#     P_melt(T) = 2.172e-4·T^1.556 − 0.21   (GPa, T in K)  →  1.311 GPa at 296 K.
# Primary: Datchi, Loubeyre & LeToullec, PRB 61, 6535 (2000); the coefficients here are
# quoted from Jia et al., J. Chem. Phys. 129, 154503 (2008), Eq. (3) — a second-hand
# transcription (Datchi 2000 not consulted directly; the same ref is already cited for
# the diamond EOS). This replaces the former hardcoded _AR_P_MIN = 1.4 and the Chen
# _AR_CHEN_PMIN = 1.3, which were arbitrary round thresholds rather than a phase boundary.
_AR_MELT_A = 2.172e-4     # GPa·K^-EXP
_AR_MELT_EXP = 1.556
_AR_MELT_B = 0.21         # GPa


def ar_p_melt(T=None):
    """fcc Ar melting pressure (GPa) at temperature T (K) via the Datchi curve."""
    if T is None:
        T = _AR_T_REF
    return _AR_MELT_A * float(T) ** _AR_MELT_EXP - _AR_MELT_B


# The solid-branch floor for every Ar model is now the melting pressure at room T, not an
# arbitrary threshold. Same symbol names retained so downstream references (p_floor of the
# volume-ratio helpers, _MEDIUM_SUBSOLID_P, model docs, GUI status) pick up the new value.
# Both Ar variants melt at the same P; the former split (1.4 vs 1.3) was not physical.
_AR_P_MIN = ar_p_melt()        # ≈ 1.311 GPa at 296 K
_AR_CHEN_PMIN = _AR_P_MIN


# --- Liquid branch: n(P) below the melting curve ---------------------------
# Below melting, argon is liquid and no solid EOS applies. The liquid index is taken
# directly from a cubic fit to the LIQUID n column of Grimsditch Table I (its sub-melting
# rows, 21 points, P = 0.11–1.36 GPa) — no density, no dielectric model, no EOS.
#
# PROVENANCE. Grimsditch Table I's caption: n is "measured in the liquid (Ref. 16) and
# calculated in the solid using Eqs. (4) and (5)." So for the LIQUID rows n is measured,
# and Grimsditch Ref. 16 is Lallemand & Vidal, J. Chem. Phys. 66, 4776 (1977) — the
# origin of the liquid optical index. Lallemand's own argon data reach only ~0.89 GPa;
# Grimsditch's liquid rows extend to 1.36 GPa, so the 0.89–1.36 GPa part is Grimsditch's
# extension of Lallemand, not raw Lallemand data. These are used as the in-hand tabulated
# optical liquid n, credited to Lallemand via Grimsditch Table I — NOT computed from the
# Itié/Grimsditch dielectric model (that applies only to the solid rows).
#
# The coefficients are numpy.polyfit(P, n, 3) over those 21 rows (rms 0.0027, max 0.0047),
# computed once and frozen here so there is no runtime fit.
# Cross-checks (not used by the model): Jia et al. 2008 Eq. (6) at Grimsditch's tabulated
# ρ reproduces this liquid n to ≤0.008; Lallemand's √ε_static sits ~0.005 below it
# (static- vs optical-frequency index).
_AR_LIQUID_N_COEFFS = (0.095703, -0.298537, 0.362537, 1.136303)  # high→low, for np.polyval
_AR_LIQUID_P_LO = 0.11    # GPa, lowest Grimsditch liquid row (below → gas tail)
_AR_GAS_N = 1.0           # n of argon gas as P → 0 (tail endpoint)


def n_argon_liquid(P_gpa):
    """Optical n of LIQUID argon at pressure P (GPa), shared by every Ar medium model.

    0.11 ≤ P < P_melt: the frozen cubic fit to Grimsditch Table I's liquid n rows
    (measured index, Lallemand & Vidal 1977 via Grimsditch — see the block above).
    0 ≤ P < 0.11: a short linear tail from n(0.11) down to gas n ≈ 1.0 at P = 0 (argon is
    gas there; the cubic must not be extrapolated). Scalar in/out."""
    P = float(P_gpa)
    if P <= 0.0:
        return _AR_GAS_N
    if P >= _AR_LIQUID_P_LO:
        return float(np.polyval(_AR_LIQUID_N_COEFFS, P))
    n_lo = float(np.polyval(_AR_LIQUID_N_COEFFS, _AR_LIQUID_P_LO))
    return _AR_GAS_N + (n_lo - _AR_GAS_N) * (P / _AR_LIQUID_P_LO)


def ar_debye_D(y):
    """Debye function D(y) = (3/y³)∫₀^y t³/(eᵗ-1) dt, used by the MGD thermal term."""
    if y < 1e-6:
        return 1.0
    if y > 30.0:                      # high-y limit; integral → π⁴/15
        return 3.0 * (np.pi ** 4 / 15.0) / y ** 3
    from scipy.integrate import quad
    return 3.0 / y ** 3 * quad(lambda t: t ** 3 / np.expm1(t), 0.0, y)[0]


def ar_pressure(x, T=_AR_T_REF):
    """Total pressure (GPa) of fcc Ar at x = V/V₀ and temperature T.

    P(V,T) = P₀(V) + P_th(V,T): Rydberg-Vinet static term (Dewaele Eq. 2) plus
    the quasi-harmonic Mie-Grüneisen-Debye thermal term (Eq. 3), with γ(V) and
    θ_D(V) from Eqs. (4) and (5).  Zero-point pressure is neglected, as there.
    """
    R_GAS = 8.314462618            # J/(mol·K)
    N_AV = 6.02214076e23
    p0 = (3.0 * _AR_K0 * (1.0 - x ** (1.0 / 3.0)) * x ** (-2.0 / 3.0)
          * np.exp(1.5 * (_AR_K0P - 1.0) * (1.0 - x ** (1.0 / 3.0))))
    if T <= 0:
        return p0
    theta = _AR_THETA0 * np.sqrt(1.0 / x) * np.exp(_AR_GAMMA_A * (1.0 - x))
    gamma = _AR_GAMMA_A * x + _AR_GAMMA_B
    v_m3mol = x * _AR_V0 * 1e-30 * N_AV        # Å³/atom → m³/mol
    p_th = 3.0 * gamma * R_GAS * T / v_m3mol * ar_debye_D(theta / T) / 1e9
    return p0 + p_th


def ar_density(P_gpa, T=_AR_T_REF):
    """fcc Ar density (g/cm³) at pressure P via the Dewaele MGD EOS.

    Inverts P(V,T) for V.  At 296 K the thermal term makes P(x) non-monotonic
    below ~0.78 GPa (argon is fluid there), so this is only called for
    P ≥ _AR_P_MIN; callers handle the sub-solid range separately.
    """
    from scipy.optimize import brentq
    N_AV = 6.02214076e23
    x = brentq(lambda xx: ar_pressure(xx, T) - float(P_gpa), 0.15, 3.0)
    return _AR_M / (x * _AR_V0 * 1e-24 * N_AV)


def n_argon(P_gpa, wl_nm, T=_AR_T_REF):
    """Refractive index of argon at pressure P (GPa) and wavelength wl_nm.

    Solid branch (P ≥ P_melt): Dewaele MGD EOS → ρ(P), then Grimsditch Eqs. (3)-(4)
    → n(ρ, E). Liquid branch (P < P_melt): the shared measured liquid n(P) from
    n_argon_liquid (Lallemand via Grimsditch — see that helper). The liquid/solid
    boundary is the Datchi melting curve ar_p_melt(T); n steps by the physical
    volume-of-melting difference there (not smoothed). Scalar in, scalar out.
    """
    P = float(P_gpa)
    wl = np.asarray(wl_nm, dtype=float)

    def _n_solid(p):
        rho = ar_density(p, T)                    # g/cm³
        E = 1239.84193 / wl                       # eV, photon energy (hc in eV·nm)
        E_b = 19.23 + 0.381 * np.abs(0.9107 * rho - 1.0) ** 1.8   # Grimsditch Eq. (4)
        # ε₁ − 1 = A·ρ·[f_b/(E_b²−E²) + core], and ε₁ − 1 = 3(n²−1)/(n²+2).
        eps_m1 = _AR_A_MASS * rho * (_AR_FB / (E_b ** 2 - E ** 2) + _AR_GRIM_C2)
        lhs = np.clip(eps_m1 / 3.0, 0.0, 0.9999)
        return np.sqrt((1.0 + 2.0 * lhs) / (1.0 - lhs))

    if P >= ar_p_melt(T):
        return float(np.mean(_n_solid(P)))
    return n_argon_liquid(P)


# ---------------------------------------------------------------------------
# Constant Lorentz-Lorenz (LL) reconstructions of argon n(P).
#
# An alternative to the Grimsditch dielectric model of n_argon above. Rather
# than a density-dependent band gap, these hold the molar Lorentz-Lorenz
# refractivity fixed:
#     LL = (1/ρ_molar)·(n²−1)/(n²+2)   [cm³/mol]
# fitted (averaged) over 19 digitized (P, n) points, then inverted:
#     CM = LL·ρ_molar,   n = √((1 + 2·CM)/(1 − CM)).
# Being a single averaged constant, the reconstruction is wavelength-INDEPENDENT
# (the wl_nm argument is accepted only for a common medium-model signature).
#
# The two variants differ ONLY in which EOS turns P into the density used both
# to fit LL and to reconstruct n — hence the ~6 % gap in the fitted constant:
#   ArChen  — Chen et al., PRB 81, 144110 (2010): 3rd-order Birch-Murnaghan in
#             Eulerian finite strain, referenced at a FINITE P_ref = 2 GPa
#             (K_ref = 15.1 GPa, K_ref' = 5.4, ρ_ref = 2.18 g/cm³).
#   ArChenD — same LL machinery, but density from the Dewaele 2021 MGD EOS
#             (ar_density, the same P→ρ used by n_argon).
# Fitted LL constants and solid-branch thresholds are per the digitization run
# (constant_LL_parameters.csv); below threshold n is a liquid-branch placeholder
# linearly ramped from n = 1.2 at 0 GPa, matching n_argon's continuity trick.
# ---------------------------------------------------------------------------
_AR_LL_DEWAELE = 4.4068     # cm³/mol, constant LL fitted on Dewaele-2021 densities
_AR_LL_CHEN = 4.6616        # cm³/mol, constant LL fitted on Chen-2010 densities
# Chen 2010 BM3 (Eulerian) reference state at 2 GPa.
_AR_CHEN_PREF = 2.0         # GPa
_AR_CHEN_KREF = 15.1        # GPa, K at P_ref
_AR_CHEN_KREFP = 5.4        # K' at P_ref
_AR_CHEN_RHOREF = 2.18      # g/cm³, ρ at P_ref
# (_AR_CHEN_PMIN is defined above near the melting curve = ar_p_melt(); the Chen model
#  melts at the same room-T pressure as the others — the former 1.3 GPa was arbitrary.)


def ar_density_chen(P_gpa):
    """fcc Ar mass density (g/cm³) at pressure P via the Chen 2010 BM3 EOS.

    3rd-order Birch-Murnaghan referenced at P_ref = 2 GPa. The BM3 P(V) polynomial is
    the SAME one as the P=0-referenced bm3_p_from_v_ratio; we reuse it (single source of
    the formula, no re-stated coefficients) with the compression ratio taken relative to
    the 2 GPa reference and P_ref added on:
        η = V_ref/V = ρ/ρ_ref  (the ratio bm3_p_from_v_ratio calls V₀/V internally),
        P(η) = P_ref + bm3_p_from_v_ratio(1/η, K_ref, K_ref').
    Inverted numerically for η, then ρ = ρ_ref·η. Reproduces the source anchors
    ρ(1.3 GPa) ≈ 2.066 g/cm³ and ρ(25 GPa) ≈ 3.42 g/cm³. Meaningful on the solid branch
    (P ≥ _AR_CHEN_PMIN); callers gate on that."""

    def _P_of_eta(eta):
        # bm3_p_from_v_ratio takes v_ratio = V/V_ref = 1/η and forms V_ref/V = η itself.
        return _AR_CHEN_PREF + bm3_p_from_v_ratio(1.0 / eta, _AR_CHEN_KREF, _AR_CHEN_KREFP)

    # P(η) is monotonic in η over the physical range; bracket from mild expansion
    # (η=0.5, P well below the solid branch) to strong compression (η=3).
    from scipy.optimize import brentq
    eta = brentq(lambda e: _P_of_eta(e) - float(P_gpa), 0.5, 3.0)
    return _AR_CHEN_RHOREF * eta


def n_argon_LL(P_gpa, rho_g_cm3, LL_cm3_mol, p_min):
    """Argon n at pressure P from a constant molar Lorentz-Lorenz refractivity.

    Solid branch (P ≥ p_min): ρ_molar = ρ_mass/M_Ar, CM = LL·ρ_molar,
    n = √((1+2CM)/(1−CM)). Below p_min (the melting pressure): the SHARED measured
    liquid n(P) from n_argon_liquid — identical for every Ar model, since the liquid
    does not depend on which solid EOS is chosen. n steps by whatever this model's solid
    branch gives at p_min (not smoothed); the Chen solid models sit well above the
    measured liquid there. `rho_g_cm3` is a callable P→ρ (Chen or Dewaele). Scalar in/out."""
    def _n_solid(p):
        rho_molar = rho_g_cm3(p) / _AR_M          # mol/cm³
        cm = LL_cm3_mol * rho_molar
        cm = float(np.clip(cm, 0.0, 0.9999))
        return np.sqrt((1.0 + 2.0 * cm) / (1.0 - cm))

    P = float(P_gpa)
    if P >= p_min:
        return _n_solid(P)
    return n_argon_liquid(P)


def n_argon_chen(P_gpa, wl_nm=None, T=_AR_T_REF):
    """Argon n(P): constant-LL model with density from the Chen 2010 BM3 EOS.
    Wavelength-independent (LL is a single constant); wl_nm/T unused, kept for a
    uniform medium-model signature."""
    return n_argon_LL(P_gpa, ar_density_chen, _AR_LL_CHEN, _AR_CHEN_PMIN)


def n_argon_chenD(P_gpa, wl_nm=None, T=_AR_T_REF):
    """Argon n(P): constant-LL model with density from the Dewaele 2021 MGD EOS.
    Same LL machinery as n_argon_chen but a different P→ρ, and a different
    fitted LL constant. Wavelength-independent; wl_nm passed through unused."""
    return n_argon_LL(P_gpa, lambda p: ar_density(p, T),
                      _AR_LL_DEWAELE, _AR_P_MIN)


def ar_volume(P_gpa, T=_AR_T_REF):
    """fcc Ar atomic volume V (Å³/atom) at pressure P via the Dewaele 2021 MGD EOS.

    Same inversion of P(V,T) as ar_density, but returns V = x·V₀ directly rather
    than converting to mass density — the L-vs-pressure overlay needs V, not ρ."""
    from scipy.optimize import brentq
    x = brentq(lambda xx: ar_pressure(xx, T) - float(P_gpa), 0.15, 3.0)
    return x * _AR_V0


def ar_volume_ratio(P_gpa, P_anchor, T=_AR_T_REF):
    """fcc-Ar volume ratio V(P)/V(P_anchor) via the Dewaele 2021 MGD EOS. Valid on the
    solid branch (P ≥ _AR_P_MIN), which the caller enforces."""
    return ar_volume(P_gpa, T) / ar_volume(P_anchor, T)


def ar_volume_ratio_chen(P_gpa, P_anchor):
    """fcc-Ar volume ratio V(P)/V(P_anchor) via the Chen 2010 BM3 EOS, from the density
    (V ∝ 1/ρ): ρ_chen(P_anchor)/ρ_chen(P). Valid on the solid branch (P ≥ _AR_CHEN_PMIN)."""
    return ar_density_chen(P_anchor) / ar_density_chen(P_gpa)


# (Mg,Fe)SiO₃ perovskite sample EOS — Dorfman et al., EPSL 361 (2013) 249, Table 2,
# "This work" Fe#74 row (3rd-order Birch-Murnaghan). Only K₀ and K₀′ are needed: the volume
# RATIO V(P)/V(P_anchor) cancels V₀ (= 166.7 Å³, unused here). The published fit was
# constrained to 69-107 GPa; anchoring below that extrapolates outside that window.
_PV_FE74_K0 = 271.0    # GPa
_PV_FE74_K0P = 4.0     # K0' (fixed in the published fit)


def bm3_volume_ratio(P_gpa, P_anchor, K0, K0p):
    """Volume ratio V(P)/V(P_anchor) for a 3rd-order Birch-Murnaghan material (V₀ cancels,
    so only K₀, K₀′ matter)."""
    return bm3_v_ratio(P_gpa, K0, K0p) / bm3_v_ratio(P_anchor, K0, K0p)


def vinet_volume_ratio(P_gpa, P_anchor, K0, K0p):
    """Volume ratio V(P)/V(P_anchor) for a Vinet material, from the density (V ∝ 1/ρ)."""
    return vinet_density(P_anchor, K0, K0p, 1.0) / vinet_density(P_gpa, K0, K0p, 1.0)


# EoS registry for the results-plot overlays. Each 'fn' is a pure EoS returning the VOLUME
# RATIO V(P)/V(P_anchor); the caller turns that into a thickness via
# y = y_anchor·ratio^(1/3) (isotropic compression), so the thickness step is not baked into
# the EoS. 'p_floor' is the pressure below which the EoS has no valid solution. Materials
# filling the gap (Ar/KCl medium, perovskite/LiF sample) are the physical fits; diamond
# (anvil) / rhenium (gasket) are offered too but aren't gap materials. BM3/Vinet models bind
# K₀/K₀′ via a small named closure (no functools).
def _mk_bm3(K0, K0p):
    def _fn(P, Pa):
        return bm3_volume_ratio(P, Pa, K0, K0p)
    return _fn


def _mk_vinet(K0, K0p):
    def _fn(P, Pa):
        return vinet_volume_ratio(P, Pa, K0, K0p)
    return _fn


EOS_NONE = 'None'
EOS_MODELS = {
    'Ar (Dewaele)':    {'fn': ar_volume_ratio,      'p_floor': _AR_P_MIN},
    'Ar (Chen)':       {'fn': ar_volume_ratio_chen, 'p_floor': _AR_CHEN_PMIN},
    'KCl (Chidester)': {'fn': _mk_bm3(_KCL_K0, _KCL_K0P), 'p_floor': 1e-9},
    'Fe#74 (Dorfman)': {'fn': _mk_bm3(_PV_FE74_K0, _PV_FE74_K0P), 'p_floor': 1e-9},
    'LiF (Lee)':       {'fn': _mk_bm3(_LIF_K0, _LIF_K0P), 'p_floor': 1e-9},
    'Diamond':         {'fn': _mk_vinet(DIAMOND_K0, DIAMOND_K0P), 'p_floor': 1e-9},
    'Rhenium':         {'fn': _mk_bm3(_RE_K0, _RE_K0P), 'p_floor': 1e-9},
}
# Material model (from the medium/layer2 dropdown) → the EoS that panel's dropdown defaults
# to. Ar-family media default to their matching Ar EoS; materials with no volume EoS (air,
# manual/Other) → None.
MATERIAL_EOS = {'Ar': 'Ar (Dewaele)', 'ArChen': 'Ar (Chen)', 'ArChenD': 'Ar (Dewaele)'}


def thickness_from_volume_ratio(y_anchor, volume_ratio):
    """Isotropic cube-root thickness scaling: y = y_anchor · (V/V_anchor)^(1/3).

    The single place the EoS volume ratio becomes a thickness, so the ratio
    functions in EOS_MODELS stay pure volume EoS (source note at the registry).
    """
    r = np.asarray(volume_ratio, float)
    if np.any(r < 0):
        raise ValueError("thickness_from_volume_ratio: volume ratio must be >= 0")
    return y_anchor * r ** (1.0 / 3.0)


def eos_volume_ratio(name, P_gpa, P_anchor):
    """Volume ratio from the EOS_MODELS registry, with a named error and a floor check."""
    entry = EOS_MODELS.get(name)
    if entry is None:
        raise ValueError("unknown EOS %r (known: %s)"
                         % (name, ', '.join(sorted(EOS_MODELS))))
    floor = entry['p_floor']
    if P_gpa < floor or P_anchor < floor:
        raise ValueError("%s has no solution below %.4g GPa (got P=%.4g, anchor=%.4g)"
                         % (name, floor, P_gpa, P_anchor))
    return entry['fn'](P_gpa, P_anchor)


def n_air_of_P(P_gpa, wl_nm):
    """Air refractive index as a medium model. Pressure-independent (a leaked cell is at
    ~ambient, and air is effectively non-dispersive over the fringe window), so P is
    ignored — the wrapper just gives n_air a (P, wl) signature so it registers like the
    other media models. Used e.g. for decompression points where the pressure medium has
    leaked out and air fills the gap."""
    return float(np.mean(n_air(wl_nm)))


# Media with a functional n(P) model available to the medium dropdown.  Values are
# callables (P_gpa, wl_nm) -> n.  '(manual)' is handled separately as the
# no-model case; media whose only data is digitized points (e.g. KCl above) are
# deliberately excluded so the dropdown never implies a model that isn't there.
MEDIUM_N_OF_P = {'Ar': n_argon,
                 'ArChen': n_argon_chen,      # constant-LL, Chen-2010 density
                 'ArChenD': n_argon_chenD,    # constant-LL, Dewaele-2021 density
                 'air': n_air_of_P}           # ~1.0003, pressure-independent (leaked cell)
# Solid-branch threshold per Ar model — below it n(P) is a liquid-branch ramp, so
# the status readout can flag "(sub-solid ramp)". Each model uses its source's range.
MEDIUM_SUBSOLID_P = {'Ar': _AR_P_MIN, 'ArChen': _AR_CHEN_PMIN, 'ArChenD': _AR_P_MIN}
MEDIUM_MANUAL = 'Other'        # dropdown sentinel: no model, user types the name and n


def medium_n(medium, P_gpa, wl_nm):
    """n of a pressure medium at P, via MEDIUM_N_OF_P, with a named error.

    SPARTA helper: the source indexes the registry directly at each call site.
    """
    fn = MEDIUM_N_OF_P.get(medium)
    if fn is None:
        raise ValueError("no n(P) model for medium %r (known: %s; use %r for a "
                         "hand-entered index)"
                         % (medium, ', '.join(sorted(MEDIUM_N_OF_P)), MEDIUM_MANUAL))
    return float(fn(P_gpa, wl_nm))


# ---------------------------------------------------------------------------
# Model documentation, one entry per material.
#
# Single source for both the hover tooltips and the refractive-index models window, so the
# equations/constants/references shown to the user cannot drift from the code:
# every numeric value below is interpolated from the same module constants the
# models actually use.
#
#   'summary'  one line — what the model gives you (used in the slim tooltip)
#   'equations'/'constants'/'refs'/'notes'  full detail (used in the info window)

# Shared liquid-branch documentation, common to all three Ar models (the liquid n(P) is
# identical across them). Spliced into each model's 'notes' and 'refs'.
_MODEL_DOC_LIQUID_NOTE = [
    'Liquid branch (P < P_melt), shared by every Ar model:',
    '  n(P) is a cubic fit to the LIQUID n column of Grimsditch Table I (21 rows,',
    '  0.11–1.36 GPa; rms 0.0027). Grimsditch\'s caption marks that column "measured',
    '  in the liquid (Ref. 16)"; Ref. 16 is Lallemand & Vidal 1977 — the measured',
    '  optical index. (Lallemand\'s own data reach ~0.89 GPa; the 0.89–1.36 GPa part is',
    '  Grimsditch\'s extension.) No density, no dielectric model, no EOS on this branch.',
    '  Below 0.11 GPa (gas): a short linear tail to n → 1.0 at P = 0.',
    '  The liquid/solid boundary is the Datchi melting curve (Jia 2008 Eq. 3).',
]
_MODEL_DOC_LIQUID_REFS = [
    'Liquid n (P < P_melt) — Lallemand & Vidal, J. Chem. Phys. 66, 4776 (1977),',
    '    via the liquid n column of Grimsditch Table I (Grimsditch Ref. 16).',
    'Melting curve — Datchi, Loubeyre & LeToullec, PRB 61, 6535 (2000),',
    '    coefficients quoted from Jia et al., J. Chem. Phys. 129, 154503 (2008), Eq. (3).',
]


def _model_doc_diamond():
    return {
        'title': 'Diamond (anvils) — n(P, λ)',
        'summary': 'Single-oscillator model with a pressure-shifted resonance.',
        'equations': [
            'n² − 1 = F₁ / (ω₁² − ω²)',
            'resonance:  ω₁(P) = ω₀ + K·P',
            'strength:   F₁(P) = C·ω₁(P)·ρ(P),   C = F₁(0) / (ω₀·ρ₀)',
        ],
        'constants': [
            'ω₀     = %.0f cm⁻¹' % DIAMOND_W0,
            'F₁(0)  = %.3g (cm⁻¹)²' % DIAMOND_F1_0,
            'K      = dω₁/dP = %.0f cm⁻¹/GPa' % DIAMOND_K,
            'ρ(P)   : Vinet EOS, V₀ = %.4f Å³/atom, K₀ = %.1f GPa, K₀′ = %.2f'
            % (DIAMOND_V0, DIAMOND_K0, DIAMOND_K0P),
            'ρ₀     = %.4f g/cm³ (from M_C = 12.011 g/mol, IUPAC)' % DIAMOND_RHO0,
            'ambient constant model: n = %g' % N_DIAMOND_CONST,
        ],
        'refs': [
            'ω₀, F₁(0) — Eggert, Goettel & Silvera, EPL 11, 775 (1990); single-oscillator',
            '    fit to the ambient n(λ) of Edwards & Ochoa (1981).',
            'K — Eremets et al., High Press. Res. 9, 347 (1992); n(P,λ) fringes to 40 GPa.',
            'Vinet EOS — Dewaele et al., PRB 77, 094106 (2008), Table III (XRD in Ne,',
            '    0–80 GPa, 298 K; K₀ via Brillouin isothermal conversion, Vogelgesang 1996).',
            'n = 2.4168 constant — Phillip & Taft (1964) at 589 nm.',
        ],
        'notes': [
            'Used directly by "calc n", independent of the batch diamond-model setting.',
        ],
    }


def _model_doc_argon():
    return {
        'title': 'Argon (medium) — n(P, λ)',
        'summary': 'EOS gives ρ(P); a one-electron dielectric model gives n(ρ, E).',
        'equations': [
            'ρ(P):  P(V,T) = P₀(V) + P_th(V,T), inverted numerically for V',
            '       P₀: Rydberg-Vinet;  P_th: quasi-harmonic Mie-Grüneisen-Debye',
            '       γ(V) = 2.20·(V/V₀) + 0.5,   θ_D(V) = 93.3·√(V₀/V)·exp[2.20(1−V/V₀)]',
            '',
            'n(ρ,E):  3(n²−1)/(n²+2) = ε₁ − 1 = A·ρ·[f_b/(E_b²−E²) + 3.125×10⁻⁴]',
            '         E_b = 19.23 + 0.381·|0.9107·ρ − 1|^1.8',
            '',
            'Liquid (P < P_melt = %.3f GPa at 296 K): measured n(P), see below.'
            % ar_p_melt(),
        ],
        'constants': [
            'EOS: V₀ = %g Å³/at, K₀ = %g GPa, K₀′ = %g,' % (_AR_V0, _AR_K0, _AR_K0P),
            '     θ_D0 = %g K, γ₀ = 2.7,  M = %g g/mol' % (_AR_THETA0, _AR_M),
            'A    = 4πℏ²N_a e²/m_e = %.3f eV² cm³/mol  (from CODATA values)'
            % _AR_A_EV2_CM3,
            'A/M  = %.4f eV² cm³/g   (for ρ in g/cm³)' % _AR_A_MASS,
            'f_b  = %g   (outer-shell oscillator strength, Itié & Le Toullec)' % _AR_FB,
            'core = %g   (core-electron term, Grimsditch Eq. 3)' % _AR_GRIM_C2,
        ],
        'refs': [
            'EOS — Dewaele, Rosa, Guignot et al., Sci. Rep. 11, 15192 (2021),',
            '    Eqs. (2)–(5) and Table 2.',
            'n(ρ,E) — Grimsditch, Loubeyre & Polian, PRB 33, 7192 (1986), Eqs. (3)–(4).',
            'A·ρ prefactor — Itié & Le Toullec, J. Phys. Colloques 45, C8-53 (1984),',
            '    Eqs. (3)–(4). Cited by Grimsditch as the source of this model.',
        ] + _MODEL_DOC_LIQUID_REFS,
        'notes': [
            'The A·ρ prefactor follows Itié & Le Toullec Eq. (3); Grimsditch Eq. (3) is',
            'written without it. A = 4πℏ²N_a e²/m_e is evaluated from CODATA values in',
            'the code. Itié\'s ρ is molar and Grimsditch\'s is mass density, so the code',
            'uses A/M_Ar.',
            '',
            'Agreement with published tables (solid branch):',
            '  n(ρ) vs Grimsditch Table I (98 rows): max 0.0047, rms 0.0009.',
            '  Full P→n chain, P ≥ P_melt (74 rows): max 0.0053.',
            '  n(ρ) vs Itié Table (xenon, 5 rows): max 0.0026.',
            '  Dewaele ρ(P) vs Grimsditch tabulated ρ: within 1.4%.',
            '',
            'Liquid branch (P < P_melt): the shared measured liquid n(P) — see the',
            'liquid-branch note common to all Ar models below.',
            '',
        ] + _MODEL_DOC_LIQUID_NOTE + [
            '',
            'Melting step (Ar): n_liq → n_sol at P_melt = %.3f GPa is +0.010,'
            % ar_p_melt(),
            '  the physical volume of melting for this model.',
        ],
    }


def _model_doc_argon_LL(chen):
    """Doc dict for the constant-Lorentz-Lorenz Ar variants. `chen=True` is the
    Chen-2010-density variant (ArChen); `chen=False` the Dewaele-2021 one (ArChenD).
    Both share the LL machinery and differ only in the P→ρ EOS and fitted LL."""
    if chen:
        title, ll, pmin = 'Argon (medium) — ArChen n(P)', _AR_LL_CHEN, _AR_CHEN_PMIN
        eos = ['ρ(P): Chen 2010 3rd-order Birch-Murnaghan (Eulerian strain),',
               '      referenced at P_ref = %g GPa,' % _AR_CHEN_PREF,
               '      K_ref = %g GPa, K_ref′ = %g, ρ_ref = %g g/cm³'
               % (_AR_CHEN_KREF, _AR_CHEN_KREFP, _AR_CHEN_RHOREF)]
        eos_ref = 'EOS — Chen et al., Phys. Rev. B 81, 144110 (2010).'
    else:
        title, ll, pmin = 'Argon (medium) — ArChenD n(P)', _AR_LL_DEWAELE, _AR_P_MIN
        eos = ['ρ(P): Dewaele 2021 Mie-Grüneisen-Debye EOS (same as the "Ar" model),',
               '      V₀ = %g Å³/at, K₀ = %g GPa, K₀′ = %g' % (_AR_V0, _AR_K0, _AR_K0P)]
        eos_ref = 'EOS — Dewaele et al., Sci. Rep. 11, 15192 (2021), Eqs. (2)–(5), Table 2.'
    return {
        'title': title,
        'summary': 'EOS gives ρ(P); a constant molar Lorentz-Lorenz refractivity gives '
                   'n(ρ). Wavelength-independent.',
        'equations': eos + [
            '',
            'n(ρ):  LL = (1/ρ_molar)·(n²−1)/(n²+2)  held constant',
            '       CM = LL·ρ_molar,   n = √((1 + 2·CM)/(1 − CM))',
            '',
            'Liquid (P < P_melt = %.3f GPa at 296 K): measured n(P), see below.'
            % ar_p_melt(),
        ],
        'constants': [
            'LL   = %g cm³/mol   (averaged over 19 digitized (P, n) points)' % ll,
            'M    = %g g/mol' % _AR_M,
        ],
        'refs': [
            eos_ref,
            'Lorentz-Lorenz reconstruction fitted to digitized argon n(P) points.',
        ] + _MODEL_DOC_LIQUID_REFS,
        'notes': [
            'The molar Lorentz-Lorenz refractivity is fitted (averaged) over the digitized',
            'points using this variant\'s EOS density, then inverted to reconstruct n(P). As',
            'a single averaged constant it carries no wavelength dependence.',
            '',
        ] + _MODEL_DOC_LIQUID_NOTE + [
            '',
            'Melting step (%s): this solid model sits above the'
            % ('ArChen' if chen else 'ArChenD'),
            '  measured liquid at P_melt, so n jumps by ~%s there —'
            % ('+0.084' if chen else '+0.044'),
            '  a real disagreement between the constant-LL solid model and the measured',
            '  liquid, shown as-is, not smoothed.',
        ],
    }


# key → callable returning the doc dict (called lazily so the text always reflects
# the current module constants).
MODEL_DOCS = {'diamond': _model_doc_diamond, 'Ar': _model_doc_argon,
              'ArChen': lambda: _model_doc_argon_LL(True),
              'ArChenD': lambda: _model_doc_argon_LL(False)}


def format_model_doc(key, full=True):
    """Render one material's model doc as plain text.

    full=False gives the slim hover form (title + summary + equations + a pointer);
    full=True adds constants, references and notes for the info window.
    """
    mk = MODEL_DOCS.get(key)
    if mk is None:
        return ''
    d = mk()
    out = [d['title'], '=' * len(d['title']), '', d['summary'], '']
    out += d['equations']
    if not full:
        out += ['', 'Constants and references: the refractive index models window.']
        return '\n'.join(out)
    for head, items in (('Constants', d['constants']), ('References', d['refs']),
                        ('Notes', d['notes'])):
        if items:
            out += ['', head + ':'] + ['  ' + s if s else '' for s in items]
    return '\n'.join(out)


def reference_pmax(pressure_medium):
    """Max pressure (GPa) across all reference datasets for a pressure medium.
    Used to size the n_mean "reference range" column.  Add new reference sources
    here when extending the reference library for additional materials.
    """
    _p_values = []
    if pressure_medium == 'LiF':
        # Balzaretti 1996: linear fit, measured to 7.35 GPa
        _p_values.append(7.35)
        # Spataru 2015: convert density points to pressure via BM3
        for _rho, _ in _LIF_SPATARU_RHO_N:
            _p_values.append(bm3_p_from_v_ratio(_LIF_RHO0 / _rho, _LIF_K0, _LIF_K0P))
        # Hawreliak 2024 L-L model: range we plot it over
        _p_values.append(250.0)
    elif pressure_medium == 'KCl':
        _p_values.extend(p for p, _ in _KCL_PROCTOR_RAW)
        _p_values.extend(p for p, _ in _KCL_PROCTOR_LL)
    if not _p_values:
        return None
    return max(_p_values)


__all__ = ['n_kcl', 'n_lif', 'n_air', 'AMBIENT_N_FUNC', 'ambient_n_stats',
           'diamond_n_stats', 'lif_n_lorentz_lorenz', 'ar_p_melt',
           'n_argon_liquid', 'ar_debye_D', 'ar_pressure', 'ar_density',
           'n_argon', 'ar_density_chen', 'n_argon_LL', 'n_argon_chen',
           'n_argon_chenD', 'ar_volume', 'ar_volume_ratio',
           'ar_volume_ratio_chen', 'bm3_volume_ratio', 'vinet_volume_ratio',
           'EOS_MODELS', 'EOS_NONE', 'MATERIAL_EOS', 'eos_volume_ratio',
           'thickness_from_volume_ratio', 'n_air_of_P', 'MEDIUM_N_OF_P',
           'MEDIUM_SUBSOLID_P', 'MEDIUM_MANUAL', 'medium_n', 'MODEL_DOCS',
           'format_model_doc', 'reference_pmax']
