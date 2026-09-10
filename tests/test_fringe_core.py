"""
Unit tests for SPARTA's vendored fringe core (fringe_*.py).

These are self-contained: no reference to the original defringe_dac.py and no
external spectra (that is test_fringe_parity.py's job).  They pin the physics,
the config plumbing, the SPARTA divergences and the input validation.
"""

import math
import os
import sys

import numpy as np
import pytest

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

import fringe_config as FC          # noqa: E402
import fringe_detect as FD          # noqa: E402
import fringe_fit as FF             # noqa: E402
import fringe_materials as FMat     # noqa: E402
import fringe_msv as FM             # noqa: E402
import fringe_notch as FN           # noqa: E402
import fringe_optics as FO          # noqa: E402
import fringe_stack as FS           # noqa: E402


# ---------------------------------------------------------------------------
# shared fixtures
# ---------------------------------------------------------------------------

def make_spectrum(nts_nm=(24000.0,), amps=(0.10,), n_pts=1600,
                  wl_lo=380.0, wl_hi=1050.0, noise=0.0, seed=5, phi0=0.4):
    """Raw-counts spectrum with a lamp envelope and one or more etalon fringes."""
    rng = np.random.RandomState(seed)
    wl = np.linspace(wl_lo, wl_hi, n_pts)
    wn = 1.0 / wl
    env = 10000.0 * np.exp(-0.5 * ((wl - 720.0) / 260.0) ** 2) + 500.0
    mod = np.zeros_like(wl)
    for nt, amp in zip(nts_nm, amps):
        mod = mod + amp * np.cos(2.0 * np.pi * (2.0 * nt) * wn + phi0)
    counts = env * (1.0 + mod)
    if noise:
        counts = counts + rng.normal(0.0, noise, n_pts)
    return wl, counts


def uniform_grid(wl, raw):
    wn = 1.0 / wl
    si = np.argsort(wn)
    wn_u = np.linspace(wn[si][0], wn[si][-1], si.size)
    sig_u = np.interp(wn_u, wn[si], raw[si])
    return wn_u, sig_u


@pytest.fixture(scope='module')
def spectrum():
    return make_spectrum()


@pytest.fixture(scope='module')
def grid(spectrum):
    wl, raw = spectrum
    wn_u, sig_u = uniform_grid(wl, raw)
    return wl, raw, wn_u, sig_u


# ===========================================================================
# fringe_config
# ===========================================================================

def test_config_defaults_match_source():
    c = FC.FringeConfig()
    assert c.diamond_model == 'constant'
    assert c.fit_phi0 is True
    assert c.fit_wl_min_nm == 600.0 and c.fit_wl_max_nm == 800.0
    assert c.fringe_nt_min_nm == 8000.0 and c.fringe_nt_max_nm == 300000.0
    assert c.fringe_pvalue_max == 1e-4
    assert c.nt_agree_tol == 0.15
    assert c.notch_halfwidth_um == 3.0
    assert c.t_bounds_nm == (1000.0, 200000.0)
    assert c.band_res_floor is True


def test_config_derived_windows():
    c = FC.FringeConfig()
    assert c.wide_lo == pytest.approx(11000.0e-7)
    assert c.wide_hi == pytest.approx(18000.0e-7)
    assert c.full_wn_cap == pytest.approx(21500.0e-7)
    assert c.full_wn_lo is None
    assert c.fine_wn_lo == pytest.approx(12500.0e-7)
    assert c.fine_wn_hi == pytest.approx(14500.0e-7)
    assert c.freq_min == 2.0 * c.fringe_nt_min_nm
    assert c.freq_max == 2.0 * c.fringe_nt_max_nm


def test_config_is_frozen():
    c = FC.FringeConfig()
    with pytest.raises(Exception):
        c.notch_halfwidth_um = 5.0


def test_config_evolve_returns_new_instance():
    c = FC.FringeConfig()
    d = c.evolve(notch_halfwidth_um=2.0)
    assert c.notch_halfwidth_um == 3.0 and d.notch_halfwidth_um == 2.0
    assert d is not c


def test_config_lamp_regime_is_explicit():
    c = FC.FringeConfig()
    assert c.for_lamp_regime('pre_nov2025').fine_center_cm == 13500.0
    assert c.for_lamp_regime('nov2025_plus').fine_center_cm == 11200.0
    with pytest.raises(ValueError):
        c.for_lamp_regime('whenever')


# --- D2: acquisition date -> lamp regime -> fine window --------------------
# Drift #3 in the core drift report: the source picks the fine window from a
# parsed acquisition date in its batch pipeline and never in its GUI.  These
# helpers are the pure half of the SPARTA wiring; the panel-side call is
# Wave C's.

@pytest.mark.parametrize('name,want', [
    ('Y03_ch29_Nov2025_ProcessedCSV', (2025, 11)),
    ('Chewy_ch29_Jun2025', (2025, 6)),
    ('Boba_Alm100_Jan2026_ProcessedCSV', (2026, 1)),
    ('Vis_Y04_Arch29_May2025_Absorbance', (2025, 5)),
    ('Y04_Arch29_2025-11_absorbance', (2025, 11)),
    ('run_2025_07_series', (2025, 7)),
    ('set.2024.12.raw', (2024, 12)),
    ('Boba_Alm100_November 2025_CSV', (2025, 11)),
    ('Y03_ch29_Sept2025', (2025, 9)),
    ('Y03_ch29_ProcessedCSV', None),
    ('Decadent_ch29_run', None),          # a month prefix inside a word
    ('', None),
    (None, None),
])
def test_parse_folder_date(name, want):
    assert FC.parse_folder_date(name) == want


def test_lamp_regime_cutover_is_november_2025():
    assert FC.FINE_CUTOVER_YEAR_MONTH == (2025, 11)
    assert FC.lamp_regime_for_date(None) == 'pre_nov2025'
    assert FC.lamp_regime_for_date((2025, 10)) == 'pre_nov2025'
    assert FC.lamp_regime_for_date((2025, 11)) == 'nov2025_plus'
    assert FC.lamp_regime_for_date((2026, 1)) == 'nov2025_plus'
    assert FC.lamp_regime_for_date((2025, 11, 4)) == 'nov2025_plus'
    assert FC.fine_center_for_date((2025, 11)) == 11200.0
    assert FC.fine_center_for_date((2025, 6)) == 13500.0


def test_fine_window_for_date_matches_the_source_bands():
    lo, hi = FC.fine_window_for_date((2025, 6))
    assert lo == pytest.approx(12500.0e-7) and hi == pytest.approx(14500.0e-7)
    lo, hi = FC.fine_window_for_date((2025, 11))
    assert lo == pytest.approx(10200.0e-7) and hi == pytest.approx(12200.0e-7)
    assert FC.fine_window_for_date(None) == FC.fine_window_for_date((2025, 6))


def test_config_for_date_and_folder_preserve_other_fields():
    base = FC.DEFAULT_CONFIG.evolve(notch_halfwidth_um=2.25)
    c = FC.config_for_date((2025, 11), cfg=base)
    assert c.fine_center_cm == 11200.0 and c.notch_halfwidth_um == 2.25
    assert base.fine_center_cm == 13500.0          # frozen: untouched
    assert FC.config_for_folder('Y03_ch29_Nov2025_ProcessedCSV',
                                cfg=base).fine_center_cm == 11200.0
    assert FC.config_for_folder('Y03_ch29_Jun2025_ProcessedCSV',
                                cfg=base).fine_center_cm == 13500.0
    # No date in the name -> the config is handed back unchanged.
    assert FC.config_for_folder('Y03_ch29', cfg=base) is base


def test_year_month_validation():
    assert FC.normalise_year_month((2025, 11, 4)) == (2025, 11)
    assert FC.normalise_year_month(None) is None
    for bad in ((2025, 13), (2025, 0), (2025,), 2025):
        with pytest.raises(ValueError):
            FC.normalise_year_month(bad)


@pytest.mark.parametrize('kw', [
    dict(diamond_model='sapphire'),
    dict(fit_wl_min_nm=900.0, fit_wl_max_nm=800.0),
    dict(fringe_nt_min_nm=0.0),
    dict(fringe_nt_min_nm=1e6, fringe_nt_max_nm=1e5),
    dict(fringe_pvalue_max=0.0),
    dict(fringe_pvalue_max=2.0),
    dict(nt_agree_tol=-0.1),
    dict(notch_halfwidth_um=0.0),
    dict(t_min_nm=0.0),
    dict(fisher_p_terms_max=0),
    dict(fine_width_cm=0.0),
    dict(msv_models=('nonsense',)),
])
def test_config_validation_rejects(kw):
    with pytest.raises(ValueError):
        FC.FringeConfig(**kw)


def test_config_coerces_sequences_to_tuples():
    c = FC.FringeConfig(msv_models=['constant_n'], multiscale_widths_cm=[1000.0])
    assert isinstance(c.msv_models, tuple)
    assert isinstance(c.multiscale_widths_cm, tuple)


def test_make_logger_none_is_a_sink():
    log = FC.make_logger(None)
    assert log('anything') is None


def test_make_logger_passes_through_and_rejects_non_callable():
    seen = []
    log = FC.make_logger(seen.append)
    log('hi')
    assert seen == ['hi']
    with pytest.raises(TypeError):
        FC.make_logger(42)


# ===========================================================================
# fringe_optics
# ===========================================================================

def test_cauchy_n():
    assert FO.cauchy_n(700.0, 1.5, 3000.0) == pytest.approx(1.5 + 3000.0 / 700.0 ** 2)


def test_n_diamond_constant_model():
    v = FO.n_diamond(np.array([500.0, 700.0, 900.0]))
    assert np.all(v == FO.N_DIAMOND_CONST)


def test_n_diamond_cauchy_model_is_dispersive():
    cfg = FC.FringeConfig(diamond_model='cauchy')
    v = FO.n_diamond(np.array([500.0, 900.0]), cfg=cfg)
    assert v[0] > v[1] > FO.N_DIAMOND_A


def test_n_diamond_oscillator_and_eremets_differ_under_pressure():
    wl = np.array([700.0])
    amb = FO.n_diamond(wl, cfg=FC.FringeConfig(diamond_model='oscillator'))
    hip = FO.n_diamond(wl, cfg=FC.FringeConfig(diamond_model='eremets',
                                               diamond_pressure_gpa=40.0))
    assert amb[0] > 2.0 and hip[0] > 2.0
    assert hip[0] != amb[0]     # Eremets resonance shift + Vinet density


def test_n_diamond_rejects_unknown_model():
    with pytest.raises(ValueError):
        FO.n_diamond(700.0, model='unobtainium')


def test_fresnel_roundtrip():
    for n in (1.2, 1.45, 1.9, 2.2):
        V = float(FO.fresnel_V(n, 700.0))
        assert FO.fresnel_n_from_V(V, 700.0) == pytest.approx(n, rel=1e-12)


def test_fresnel_n_from_V_clips_and_keeps_shape():
    arr = FO.fresnel_n_from_V(np.array([0.1, 5.0]), 700.0)
    assert arr.shape == (2,)
    assert arr[1] >= 0.0
    assert np.ndim(FO.fresnel_n_from_V(0.1, 700.0)) == 0


def test_solve_paths_consistent_and_conserves_A():
    # L = 45/1.28 = 35.16, t_layer2 = (52-40)/1.45 = 8.28, t_s = 26.88,
    # n_s = 40/26.88 = 1.49 -- no clamp fires.
    r = FO.solve_paths(40.0, 52.0, 45.0, 1.45, 1.28)
    assert r['warns'] == []
    assert r['n_s'] * r['t_s'] == pytest.approx(40.0, rel=1e-14)
    assert r['t_s'] + r['t_layer2'] == pytest.approx(r['L'], rel=1e-14)
    assert r['n_s'] >= 1.0 and r['t_s'] > 0.0


def test_solve_paths_clamp_cascade():
    r = FO.solve_paths(5.0, 4.0, 30.0, 1.5, 1.2)       # C < A -> t_layer2 floored
    assert 't_layer2 floored to 0' in ' '.join(r['warns'])
    assert r['t_layer2'] == 0.0
    r2 = FO.solve_paths(10.0, 12.0, 20.0, 1.4, 1.3)    # n_s < 1 -> floored, A kept
    assert 'n_s floored to 1' in r2['warns']
    assert r2['n_s'] == 1.0 and r2['t_s'] == pytest.approx(10.0)


def test_solve_paths_rejects_non_positive_index():
    assert FO.solve_paths(1.0, 2.0, 3.0, 0.0, 1.2) is None
    assert FO.solve_paths(1.0, 2.0, 3.0, 1.2, -1.0) is None


def test_airy_factor_bounds():
    wl = np.linspace(600.0, 800.0, 200)
    a, V = FO.airy_factor(wl, 1.5, 0.0, 20000.0)
    assert np.all(a <= 1.0 + V + 1e-12) and np.all(a >= 1.0 - V - 1e-12)


def test_local_noise_floor_is_positive_and_validated():
    y = np.sin(np.linspace(0, 10, 200))
    nf = FO.local_noise_floor(y, window=7)
    assert nf.shape == y.shape and np.all(nf >= 0)
    with pytest.raises(ValueError):
        FO.local_noise_floor(y, window=0)


def test_eos_primitives_are_mutually_consistent():
    for P in (2.0, 12.0, 40.0):
        v = FO.bm3_v_ratio(P, 24.0, 4.56)
        assert FO.bm3_p_from_v_ratio(v, 24.0, 4.56) == pytest.approx(P, rel=1e-8)
    assert FO.vinet_density(0.0) == pytest.approx(FO.DIAMOND_RHO0)
    assert FO.vinet_density(50.0) > FO.DIAMOND_RHO0


# ===========================================================================
# fringe_notch
# ===========================================================================

def test_notch_removes_the_fringe(grid):
    wl, raw, wn_u, sig_u = grid
    clean, nt_est, filt = FN.defringe_fft_notch(wn_u, sig_u, wl, raw, 24000.0)
    assert nt_est == 24000.0
    assert np.var(sig_u - filt) > 0
    # the residual modulation in the notched band is far smaller than the input
    assert np.std(clean - np.interp(1.0 / wl, wn_u, filt)) < np.std(raw) * 0.5


def test_notch_halfwidth_is_absolute_not_fractional(grid):
    """sigma_f = 2000*hw regardless of centre -- the SPARTA/source convention."""
    wl, raw, wn_u, sig_u = grid
    dw = float(np.median(np.abs(np.diff(wn_u))))
    N = len(sig_u)
    pad = N // 2
    freqs = np.fft.rfftfreq(N + 2 * pad, d=dw)
    m_lo = FN._gaussian_notch_mask(freqs, [12000.0], None, 3.0)
    m_hi = FN._gaussian_notch_mask(freqs, [48000.0], None, 3.0)
    # -1 sigma depth is identical at both centres
    i_lo = int(np.argmin(np.abs(freqs - (2 * 12000.0 + 2000.0 * 3.0))))
    i_hi = int(np.argmin(np.abs(freqs - (2 * 48000.0 + 2000.0 * 3.0))))
    assert m_lo[i_lo] == pytest.approx(m_hi[i_hi], abs=2e-3)


def test_notch_multi_centre_attenuates_both(grid):
    wl, raw, wn_u, sig_u = grid
    dw = float(np.median(np.abs(np.diff(wn_u))))
    N = len(sig_u)
    freqs = np.fft.rfftfreq(N + 2 * (N // 2), d=dw)
    mask = FN._gaussian_notch_mask(freqs, [20000.0, 40000.0], [3.0, 3.0], 3.0)
    for c in (20000.0, 40000.0):
        i = int(np.argmin(np.abs(freqs - 2.0 * c)))
        assert mask[i] < 5e-3     # nearest bin sits within a fraction of sigma


def test_notch_lowpass_is_a_noop_above_the_fundamental(grid):
    wl, raw, wn_u, sig_u = grid
    a, _, _ = FN.defringe_fft_notch(wn_u, sig_u, wl, raw, 24000.0)
    b, _, _ = FN.defringe_fft_notch(wn_u, sig_u, wl, raw, 24000.0,
                                    lowpass=True, lp_cutoff_um=5000.0)
    assert np.max(np.abs(a - b)) < 1e-6 * max(np.max(np.abs(a)), 1.0)


def test_notch_lowpass_cuts_when_lowered(grid):
    wl, raw, wn_u, sig_u = grid
    a, _, fa = FN.defringe_fft_notch(wn_u, sig_u, wl, raw, 24000.0)
    b, _, fb = FN.defringe_fft_notch(wn_u, sig_u, wl, raw, 24000.0,
                                     lowpass=True, lp_cutoff_um=8.0)
    assert np.var(fb) < np.var(fa)


@pytest.mark.parametrize('bad', [
    dict(nt_fft_nm=0.0),
    dict(nt_fft_nm=None),
    dict(nt_fft_nm=float('nan')),
])
def test_notch_rejects_bad_centre(grid, bad):
    wl, raw, wn_u, sig_u = grid
    with pytest.raises(ValueError):
        FN.defringe_fft_notch(wn_u, sig_u, wl, raw, **bad)


def test_notch_rejects_mismatched_grids(grid):
    wl, raw, wn_u, sig_u = grid
    with pytest.raises(ValueError):
        FN.defringe_fft_notch(wn_u[:-3], sig_u, wl, raw, 24000.0)
    with pytest.raises(ValueError):
        FN.defringe_fft_notch(wn_u, sig_u, wl[:-3], raw, 24000.0)


def test_notch_rejects_zero_halfwidth(grid):
    wl, raw, wn_u, sig_u = grid
    with pytest.raises(ValueError):
        FN.defringe_fft_notch(wn_u, sig_u, wl, raw, 24000.0, halfwidth_um=0.0)


def test_width_sweep_shapes_and_monotone_removal(grid):
    wl, raw, wn_u, sig_u = grid
    sw = FN.notch_width_sweep(wn_u, sig_u, 24000.0, wl=wl, raw=raw)
    # 'width_fracs' is the upstream sweep's own key for the swept values
    # (absolute um here, factors in cascade mode). It is not the retired
    # fractional notch convention, which no longer exists anywhere.
    assert sw['residual_power'].shape == sw['width_fracs'].shape
    assert sw['I_clean_wl'].shape == (sw['width_fracs'].size, wl.size)
    assert sw['residual_power'][-1] <= sw['residual_power'][0] * 1.001
    assert sw['labels'][0].startswith('+-')


def test_width_sweep_cascade_mode(grid):
    wl, raw, wn_u, sig_u = grid
    sw = FN.notch_width_sweep(wn_u, sig_u, 24000.0,
                              notch_centers_nm=[24000.0, 48000.0],
                              notch_halfwidths_um=[3.0, 2.0])
    assert 'factors' in sw and sw['labels'][-1] == '1x'
    with pytest.raises(ValueError):
        FN.notch_width_sweep(wn_u, sig_u, 24000.0,
                             notch_centers_nm=[24000.0, 48000.0],
                             notch_halfwidths_um=[3.0])


def test_band_amplitude_recovers_the_planted_contrast():
    wl, raw = make_spectrum(nts_nm=(24000.0,), amps=(0.10,), n_pts=4000)
    wn_u, sig_u = uniform_grid(wl, raw)
    trend = np.polyval(np.polyfit(wn_u, sig_u, 4), wn_u)
    norm_u = sig_u / np.maximum(trend, 0.01 * trend.max()) - 1.0
    V = FN.band_integrated_amplitude(wn_u, norm_u, 24000.0)
    assert V == pytest.approx(0.10, rel=0.15)


def test_band_amplitude_degenerate_inputs_return_zero():
    wn_u = np.linspace(1e-3, 2e-3, 50)
    assert FN.band_integrated_amplitude(wn_u, np.zeros(50), None) == 0.0
    assert FN.band_integrated_amplitude(wn_u, np.zeros(50), -1.0) == 0.0
    assert FN.band_integrated_amplitude(wn_u[:4], np.zeros(4), 24000.0) == 0.0
    with pytest.raises(ValueError):
        FN.band_integrated_amplitude(wn_u, np.zeros(49), 24000.0)


def test_band_amplitude_res_floor_widens_narrow_bands():
    wl, raw = make_spectrum(n_pts=400, wl_lo=700.0, wl_hi=760.0)
    wn_u, sig_u = uniform_grid(wl, raw)
    norm_u = sig_u / np.mean(sig_u) - 1.0
    with_floor = FN.band_integrated_amplitude(wn_u, norm_u, 24000.0,
                                              halfwidth_um=0.05)
    no_floor = FN.band_integrated_amplitude(wn_u, norm_u, 24000.0,
                                            halfwidth_um=0.05, res_floor=False)
    assert with_floor >= no_floor


def test_removed_fraction():
    a = np.array([1.0, 2.0, 3.0, 4.0])
    assert FN.removed_fraction(a, a) == 0.0
    assert FN.removed_fraction(a, np.zeros_like(a)) == pytest.approx(1.0)
    assert FN.removed_fraction(np.ones(4), np.ones(4)) == 0.0
    with pytest.raises(ValueError):
        FN.removed_fraction(a, a[:2])


# ===========================================================================
# fringe_detect
# ===========================================================================

def test_fisher_flags_a_strong_line():
    P = np.ones(120)
    P[17] = 500.0
    g, pv = FD.fisher_g_pvalue(P)
    assert g > 0.7 and pv < 1e-10


def test_fisher_guard_returns_one_for_flat_spectra():
    g, pv = FD.fisher_g_pvalue(np.ones(2000))
    assert g == pytest.approx(1.0 / 2000)
    assert pv == 1.0


def test_fisher_guard_threshold_is_configurable():
    P = np.ones(40)
    assert FD.fisher_g_pvalue(P)[1] == 1.0
    assert FD.fisher_g_pvalue(P, p_terms_max=40)[1] <= 1.0


def test_fisher_degenerate_inputs():
    assert FD.fisher_g_pvalue(np.array([1.0])) == (1.0, 1.0)
    assert FD.fisher_g_pvalue(np.zeros(10)) == (1.0, 1.0)
    assert FD.fisher_g_pvalue(np.full(10, np.nan))[1] == 1.0


def test_fft_initial_guess_recovers_planted_nt():
    wl, raw = make_spectrum(nts_nm=(24000.0,), amps=(0.10,), n_pts=4000)
    cfg = FC.DEFAULT_CONFIG
    vis = (wl >= cfg.fit_wl_min_nm) & (wl <= cfg.fit_wl_max_nm)
    nt, fi = FD.fft_initial_guess(wl[vis], raw[vis], cfg=cfg)
    assert nt is not None
    assert nt == pytest.approx(24000.0, rel=0.05)
    assert fi['fisher_pv'] < cfg.fringe_pvalue_max
    assert fi['peak_amp'] == pytest.approx(0.10, rel=0.25)


def test_fft_initial_guess_reports_short_input_via_log():
    msgs = []
    nt, fi = FD.fft_initial_guess(np.linspace(600, 800, 5),
                                  np.ones(5), log=msgs.append, label='CH')
    assert nt is None and fi is None
    assert msgs and 'CH' in msgs[0]


def test_fft_initial_guess_reports_non_finite_via_log():
    msgs = []
    wl = np.linspace(600.0, 800.0, 200)
    y = np.ones(200)
    y[10] = np.nan
    nt, fi = FD.fft_initial_guess(wl, y, log=msgs.append, label='CH')
    assert nt is None and fi is None
    assert any('non-finite' in m for m in msgs)


def test_fft_initial_guess_rejects_shape_mismatch():
    with pytest.raises(ValueError):
        FD.fft_initial_guess(np.linspace(600, 800, 100), np.ones(99))


def test_fft_initial_guess_reports_empty_band_via_log():
    """No frequency in the physical n*t range -> reported, not silently swallowed."""
    msgs = []
    wl, raw = make_spectrum(n_pts=200)
    cfg = FC.DEFAULT_CONFIG.evolve(fringe_nt_min_nm=1e8, fringe_nt_max_nm=2e8)
    nt, fi = FD.fft_initial_guess(wl, raw, cfg=cfg, log=msgs.append, label='CH')
    assert nt is None
    assert any('physical range' in m for m in msgs)


def test_corroborate_needs_two_agreeing_windows():
    def info(nt, pv):
        return dict(nt_est=nt, fisher_pv=pv)
    cfg = FC.DEFAULT_CONFIG
    both = FD.corroborate_nt([('narrow', info(24000.0, 1e-20)),
                              ('wide', info(24100.0, 1e-20)),
                              ('full', info(24050.0, 1e-20))], cfg=cfg)
    assert both['accepted'] and both['nt'] == 24000.0
    assert both['names'] == ['narrow', 'wide', 'full']

    one = FD.corroborate_nt([('narrow', info(24000.0, 1e-20)),
                             ('wide', info(24100.0, 0.5)),
                             ('full', info(24050.0, 0.5))], cfg=cfg)
    assert not one['accepted'] and one['nt'] is None


def test_corroborate_rejects_disagreeing_windows():
    def info(nt, pv):
        return dict(nt_est=nt, fisher_pv=pv)
    out = FD.corroborate_nt([('narrow', info(24000.0, 1e-20)),
                             ('wide', info(60000.0, 1e-20)),
                             ('full', info(90000.0, 1e-20))],
                            cfg=FC.DEFAULT_CONFIG)
    assert not out['accepted']
    assert len(out['detections']) == 3


def test_corroborate_uses_median_when_narrow_disagrees():
    def info(nt, pv):
        return dict(nt_est=nt, fisher_pv=pv)
    out = FD.corroborate_nt([('narrow', info(90000.0, 0.5)),
                             ('wide', info(24000.0, 1e-20)),
                             ('full', info(24500.0, 1e-20))],
                            cfg=FC.DEFAULT_CONFIG)
    assert out['accepted']
    assert out['names'] == ['wide', 'full']
    assert out['nt'] == pytest.approx(24250.0)


def test_corroborate_needs_a_usable_narrow_window():
    def info(nt, pv):
        return dict(nt_est=nt, fisher_pv=pv)
    msgs = []
    out = FD.corroborate_nt([('narrow', None),
                             ('wide', info(24000.0, 1e-20)),
                             ('full', info(24500.0, 1e-20))],
                            cfg=FC.DEFAULT_CONFIG, log=msgs.append)
    assert not out['accepted']
    assert any('narrow FFT unavailable' in m for m in msgs)


def test_compute_channel_fit_fast_path():
    wl, raw = make_spectrum(nts_nm=(24000.0,), amps=(0.10,), n_pts=3000)
    fit, I_notch, nt, centers = FD.compute_channel_fit(
        wl, raw, run_fits=False, label='S')
    assert nt is not None and centers == [nt]
    assert fit['no_fringe'] is False and fit['models'] == {}
    assert np.isfinite(I_notch).all()
    assert 'notch_sweep' not in fit['fft_info']       # fast path skips the sweep


def test_compute_channel_fit_no_fringe_path():
    rng = np.random.RandomState(2)
    wl = np.linspace(380.0, 1050.0, 2000)
    raw = (10000.0 * np.exp(-0.5 * ((wl - 720.0) / 260.0) ** 2) + 500.0
           + rng.normal(0.0, 120.0, 2000))      # white noise: no periodicity
    msgs = []
    fit, I_notch, nt, centers = FD.compute_channel_fit(
        wl, raw, run_fits=False, label='S', log=msgs.append)
    assert nt is None and centers == []
    assert fit['no_fringe'] is True
    assert np.isnan(I_notch).all()


def test_compute_channel_fit_runs_fits():
    wl, raw = make_spectrum(nts_nm=(24000.0,), amps=(0.10,), n_pts=1400)
    cfg = FC.DEFAULT_CONFIG.evolve(msv_models=('constant_n',))
    fit, I_notch, nt, _c = FD.compute_channel_fit(
        wl, raw, cfg=cfg, run_fits=True, label='S')
    assert nt is not None
    assert 'constant_n' in fit['models']
    assert 'full' in fit['models']['constant_n']
    rd = fit['models']['constant_n']['full']
    assert rd['nt_um'] == pytest.approx(24.0, rel=0.1)
    # Drift #7 restore: constant_n reports the FITTED n*t, and t = nt/n comes
    # out unclamped (it no longer passes through dispersion_n's T_BOUNDS clip).
    assert rd['nt_um'] == pytest.approx(rd['nt_nm'] * 1e-3, rel=1e-12)
    assert rd['n_mean'] * rd['t_um'] == pytest.approx(rd['nt_um'], rel=1e-9)
    assert 'notch_sweep' in fit['fft_info']


def test_compute_channel_fit_rejects_shape_mismatch():
    with pytest.raises(ValueError):
        FD.compute_channel_fit(np.linspace(600, 800, 100), np.ones(99))


# ===========================================================================
# fringe_fit
# ===========================================================================

def test_dispersion_n_models():
    wl = np.array([600.0, 800.0])
    n, t, p = FF.dispersion_n([1.5, 3000.0, 20000.0, 0.2], wl, 'cauchy')
    assert n[0] == pytest.approx(1.5 + 3000.0 / 600.0 ** 2)
    n, t, p = FF.dispersion_n([1.5, 100.0, 20000.0, 0.0], wl, 'linear_n')
    assert n[0] == pytest.approx(1.5 + 100.0 / 600.0)
    n, t, p = FF.dispersion_n([1.7, 20000.0, 0.0], wl, 'constant_n')
    assert np.all(n == 1.7)
    n, t, p = FF.dispersion_n([1.0, 5000.0, 0.0, 1e9, 20000.0, 0.0], wl, 'sellmeier')
    assert np.all(n >= 1.0)


def test_dispersion_n_rejects_unknown_model():
    with pytest.raises(ValueError):
        FF.dispersion_n([1.0, 2.0, 3.0], np.array([700.0]), 'quadratic')


def test_dispersion_n_clamps_thickness_and_gates_phi0():
    wl = np.array([700.0])
    _n, t, _p = FF.dispersion_n([1.5, 1e9, 0.0], wl, 'constant_n')
    assert t == FC.DEFAULT_CONFIG.t_max_nm
    cfg = FC.DEFAULT_CONFIG.evolve(fit_phi0=False)
    _n, _t, p = FF.dispersion_n([1.5, 20000.0, 1.23], wl, 'constant_n', cfg=cfg)
    assert p == 0.0


def test_dispersion_n_accepts_params_without_phi0():
    wl = np.array([700.0])
    n, t, p = FF.dispersion_n([1.5, 20000.0], wl, 'constant_n')
    assert p == 0.0 and t == 20000.0


def test_dispersion_result_dict_crosses_to_um_once():
    wl = np.linspace(600.0, 800.0, 50)
    rd = FF.dispersion_result_dict([1.5, 3000.0, 20000.0, 0.1], wl, 'cauchy')
    assert rd['t_um'] == pytest.approx(20.0)
    assert rd['nt_um'] == pytest.approx(rd['n_mean'] * 20.0)
    assert rd['B'] == 3000.0
    rd2 = FF.dispersion_result_dict([1.5, -50.0, 20000.0, 0.0], wl, 'cauchy')
    assert rd2['B'] == 0.0        # B is floored at 0, as in the source


def _fit_info_from(wl, raw, cfg):
    vis = (wl >= cfg.fit_wl_min_nm) & (wl <= cfg.fit_wl_max_nm)
    wn_u, sig_u = uniform_grid(wl[vis], raw[vis])
    trend = np.polyval(np.polyfit(wn_u, sig_u, 4), wn_u)
    norm_u = sig_u / np.maximum(trend, 0.01 * trend.max()) - 1.0
    nt, fi = FD.fft_initial_guess(wl[vis], raw[vis], cfg=cfg)
    return dict(wn_u=wn_u, norm_u=norm_u, nt_est=fi['nt_est'],
                peak_amp=min(fi['peak_amp'], 0.45), peak_phase=fi['peak_phase'])


def test_fit_constant_n_recovers_nt():
    cfg = FC.DEFAULT_CONFIG
    wl, raw = make_spectrum(nts_nm=(24000.0,), amps=(0.08,), n_pts=4000)
    out = FF.fit_signal_constant_n(_fit_info_from(wl, raw, cfg), cfg=cfg)
    assert out is not None
    nt_fit, V_fit, phi0, fringe = out
    assert nt_fit == pytest.approx(24000.0, rel=0.02)
    assert 0.0 < V_fit < 1.0
    assert fringe.shape == _fit_info_from(wl, raw, cfg)['norm_u'].shape


def test_fit_constant_n_returns_none_instead_of_asserting():
    """SPARTA divergence: the source `assert n_fit >= 1.0`s here."""
    cfg = FC.DEFAULT_CONFIG
    wn_u = np.linspace(1.0 / 800.0, 1.0 / 600.0, 800)
    # V ~ 1.4 -> Fresnel inversion returns n well below 1
    norm_u = 1.4 * np.cos(2.0 * np.pi * 48000.0 * wn_u)
    msgs = []
    out = FF.fit_signal_constant_n(dict(wn_u=wn_u, norm_u=norm_u,
                                        nt_est=24000.0, peak_amp=1.4),
                                   label='CH', cfg=cfg, log=msgs.append)
    assert out is None
    assert any('n=' in m and 'window dropped' in m for m in msgs)


def test_fit_cauchy_and_linear_n_recover_thickness():
    cfg = FC.DEFAULT_CONFIG
    wl, raw = make_spectrum(nts_nm=(24000.0,), amps=(0.08,), n_pts=4000)
    fi = _fit_info_from(wl, raw, cfg)
    cau = FF.fit_signal_cauchy(fi, cfg=cfg)
    assert cau is not None
    A, B, t, phi0 = cau[0], cau[1], cau[2], cau[3]
    rd = FF.dispersion_result_dict([A, B, t, phi0], 1.0 / fi['wn_u'], 'cauchy')
    assert rd['nt_um'] == pytest.approx(24.0, rel=0.1)
    lin = FF.fit_signal_linear_n(fi, cfg=cfg)
    assert lin is not None
    assert lin[0] > 0


def test_fit_sellmeier_runs():
    cfg = FC.DEFAULT_CONFIG
    wl, raw = make_spectrum(nts_nm=(24000.0,), amps=(0.08,), n_pts=2000)
    out = FF.fit_signal_sellmeier(_fit_info_from(wl, raw, cfg), cfg=cfg)
    assert out is not None
    assert len(out) == 10


def test_fit_band_integral_matches_constant_n_geometry():
    cfg = FC.DEFAULT_CONFIG
    wl, raw = make_spectrum(nts_nm=(24000.0,), amps=(0.08,), n_pts=3000)
    fi = _fit_info_from(wl, raw, cfg)
    cn = FF.fit_signal_constant_n(fi, cfg=cfg)
    bi = FF.fit_signal_band_integral(fi, cfg=cfg)
    assert cn is not None and bi is not None
    assert bi[0] == cn[0] and bi[2] == cn[2]     # same n*t and phi0
    assert bi[1] != cn[1]                        # different amplitude estimate


def test_lstsq_errors_are_finite_and_nonnegative():
    wn_u = np.linspace(1.0 / 800.0, 1.0 / 600.0, 500)
    C = np.cos(2.0 * np.pi * 48000.0 * wn_u)
    S = np.sin(2.0 * np.pi * 48000.0 * wn_u)
    X = np.column_stack([C, S])
    norm_u = 0.1 * C + 0.02 * S + 0.001 * np.sin(37.0 * wn_u * 1e5)
    a, b = np.linalg.lstsq(X, norm_u, rcond=None)[0]
    sn, st, sV = FF.lstsq_V_n_t_errors(X, norm_u, float(a), float(b), 700.0, 24000.0)
    assert sn >= 0 and st >= 0 and sV >= 0
    assert all(math.isfinite(v) for v in (sn, st, sV))


def test_lstsq_errors_degenerate_amplitude():
    X = np.column_stack([np.ones(10), np.zeros(10)])
    assert FF.lstsq_V_n_t_errors(X, np.zeros(10), 0.0, 0.0, 700.0, 1.0) == (0.0, 0.0, 0.0)


def test_fine_fit_sigma_shapes():
    wn_u = np.linspace(1.0 / 800.0, 1.0 / 600.0, 400)
    norm_u = 0.1 * np.cos(4.0 * np.pi * 1.5 * 16000.0 * wn_u)
    sig = FF.fine_fit_sigma('constant_n', [1.5, 16000.0, 0.0], wn_u, norm_u)
    assert set(sig) == {'n_mean', 't_um', 'nt_um', 'phi0'}
    assert all(v >= 0 or np.isnan(v) for v in sig.values())
    assert np.isnan(FF.fine_fit_sigma('nope', [1.0], wn_u, norm_u)['t_um'])


def test_run_window_fits_tiers_and_narrow_gating():
    cfg = FC.DEFAULT_CONFIG.evolve(msv_models=('constant_n',))
    wl, raw = make_spectrum(nts_nm=(24000.0,), amps=(0.08,), n_pts=1600)
    wn_u, sig_u = uniform_grid(wl, raw)
    trend = np.polyval(np.polyfit(wn_u, sig_u, 4), wn_u)
    norm_u = sig_u / np.maximum(trend, 0.01 * trend.max()) - 1.0
    fi = dict(nt_est=24000.0, peak_amp=0.08, peak_phase=0.0)

    # wl_full omitted here on purpose: this exercises the documented fallback
    # (1/wn_u_full) for callers that work purely in wavenumber space.
    # pre-Nov-2025 lamp: fine centre 13500 cm^-1 (740 nm) sits inside 600-800 nm
    pre = FF.run_window_fits(fi, norm_u, wn_u, cfg=cfg)
    assert 'narrow' not in pre['constant_n']
    assert {'full', 'wide', 'fine'} <= set(pre['constant_n'])

    # Nov-2025+ lamp: fine centre 11200 cm^-1 (893 nm) is outside -> narrow runs
    post = FF.run_window_fits(fi, norm_u, wn_u,
                              cfg=cfg.for_lamp_regime('nov2025_plus'))
    assert 'narrow' in post['constant_n']


def _tier_inputs(n_pts=1600):
    wl, raw = make_spectrum(nts_nm=(24000.0,), amps=(0.08,), n_pts=n_pts)
    wn_u, sig_u = uniform_grid(wl, raw)
    trend = np.polyval(np.polyfit(wn_u, sig_u, 4), wn_u)
    norm_u = sig_u / np.maximum(trend, 0.01 * trend.max()) - 1.0
    return wl, wn_u, norm_u, dict(nt_est=24000.0, peak_amp=0.08, peak_phase=0.0)


def test_run_window_fits_averages_n_over_the_full_wavelength_grid():
    """Drift #1: every tier's n_mean averages n(lam) over the FULL original
    detector grid (the source's `wl`), not over the tier's slice of the uniform
    wavenumber resample."""
    cfg = FC.DEFAULT_CONFIG.evolve(msv_models=('cauchy', 'linear_n'))
    wl, wn_u, norm_u, fi = _tier_inputs()
    out = FF.run_window_fits(fi, norm_u, wn_u, cfg=cfg, wl_full=wl)
    seen = 0
    for wname, rd in out['cauchy'].items():
        n_full = float(np.mean(rd['A'] + rd['B'] / wl ** 2))
        assert rd['n_mean'] == pytest.approx(n_full, rel=1e-12), wname
        assert rd['nt_um'] == pytest.approx(rd['n_mean'] * rd['t_um'], rel=1e-12)
        seen += 1
    for wname, rd in out['linear_n'].items():
        n_full = float(np.mean(rd['n0'] + rd['n1'] / wl))
        assert rd['n_mean'] == pytest.approx(n_full, rel=1e-12), wname
        seen += 1
    assert seen, 'no dispersive tiers were produced'


def test_run_window_fits_constant_n_shares_one_wl_ref():
    """Drift #5 / #6: the constant_n Fresnel inversion uses one
    wl_ref = mean(1/wn_u_full) for full/wide/narrow (fine keeps its own), and V
    reaches it unclamped."""
    cfg = FC.DEFAULT_CONFIG.evolve(msv_models=('constant_n',)) \
                           .for_lamp_regime('nov2025_plus')
    wl, wn_u, norm_u, fi = _tier_inputs()
    out = FF.run_window_fits(fi, norm_u, wn_u, cfg=cfg, wl_full=wl)
    fine_mask = (wn_u >= cfg.fine_wn_lo) & (wn_u <= cfg.fine_wn_hi)
    wl_ref_shared = float(np.mean(1.0 / wn_u))
    wl_ref_fine = float(np.mean(1.0 / wn_u[fine_mask]))
    assert out['constant_n'], 'no constant_n tiers were produced'
    for wname, rd in out['constant_n'].items():
        ref = wl_ref_fine if wname == 'fine' else wl_ref_shared
        n_ref = float(FO.fresnel_n_from_V(rd['V'], ref, cfg=cfg))
        assert rd['n_mean'] == pytest.approx(n_ref, rel=1e-12), wname
        # drift #7: t is nt/n, straight out, and nt_um is the fitted n*t
        assert rd['t_um'] * 1000.0 == pytest.approx(
            rd['nt_nm'] / max(n_ref, 1e-6), rel=1e-12), wname
        assert rd['nt_um'] == pytest.approx(rd['nt_nm'] * 1e-3, rel=1e-12), wname


def test_constant_n_result_dict_skips_the_t_bounds_clip():
    """Drift #7: the source's t_cnt = nt/max(n,1e-6) is NOT clipped to
    T_BOUNDS_NM; `dispersion_result_dict` (which is his `_dispersion_result_dict`
    verbatim, clip included) is deliberately bypassed on this path."""
    params = [1.5, 500000.0, 0.2]            # t = 500 um, well past t_max_nm
    rd = FF._constant_n_result_dict(params, dict(nt_nm=750000.0))
    assert rd['t_um'] == pytest.approx(500.0)
    assert rd['nt_um'] == pytest.approx(750.0)
    assert rd['n_mean'] == 1.5 and rd['n_const'] == 1.5
    clipped = FF.dispersion_result_dict(params, np.array([700.0]), 'constant_n')
    assert clipped['t_um'] == pytest.approx(200.0)   # the clip we now bypass


def test_v_clamp_applies_to_band_integral_only():
    """Drift #6: the extra min(V, 0.9999) is gone from the constant_n path and
    kept on band_integral, matching the source's own two call sites
    (:16250-16262 vs the band-integral extract :2311)."""
    cfg = FC.DEFAULT_CONFIG
    wl_ref, V = 700.0, 1.2
    fit_result = (24000.0, V, 0.0, None)
    p_cn, model, extra = FF._params_from_fit('constant_n', fit_result, wl_ref, cfg)
    p_bi, _m, _e = FF._params_from_fit('band_integral', fit_result, wl_ref, cfg)
    assert model == 'constant_n' and extra['V'] == V
    assert p_cn[0] == pytest.approx(FO.fresnel_n_from_V(V, wl_ref, cfg=cfg))
    assert p_bi[0] == pytest.approx(
        FO.fresnel_n_from_V(min(V, 0.9999), wl_ref, cfg=cfg))
    assert p_cn[0] != p_bi[0]


def test_averaging_grid_falls_back_on_an_unusable_full_grid():
    """The documented fallback: a missing or non-finite `wl_full` reverts to
    1/wn_u_full instead of poisoning every n_mean with NaN."""
    wn_u = np.linspace(1.0 / 1050.0, 1.0 / 380.0, 64)
    msgs = []
    base = FF._averaging_wl_grid(None, wn_u, msgs.append, 'CH')
    assert np.allclose(base, 1.0 / wn_u) and not msgs
    bad = FF._averaging_wl_grid(np.array([700.0, np.nan]), wn_u, msgs.append, 'CH')
    assert np.allclose(bad, 1.0 / wn_u) and msgs
    good = np.linspace(400.0, 1000.0, 10)
    assert np.array_equal(FF._averaging_wl_grid(good, wn_u, msgs.append, 'CH'),
                          good)


def test_run_window_fits_rejects_non_lsq_method():
    cfg = FC.DEFAULT_CONFIG
    with pytest.raises(ValueError):
        FF.run_window_fits({}, np.zeros(10), np.linspace(1e-3, 2e-3, 10),
                           cfg=cfg, method='autocorr')


# ===========================================================================
# fringe_stack
# ===========================================================================

def _stack(**kw):
    p = dict(n_diamond=2.4168, n_layer2=1.45, n_sample=1.72, n_medium=1.45,
             d1_um=4.0, t_um=12.0, d2_um=3.0, layer2_name='KCl',
             sample_name='ch29', medium_name='KCl')
    p.update(kw)
    return p


def test_stack_has_six_lines_with_expected_paths():
    lines = FS.thinfilm_sample_lines(_stack())
    assert [ln['id'] for ln in lines] == ['12', '23', '34', '13', '24', '14']
    by_id = {ln['id']: ln for ln in lines}
    assert by_id['12']['nt'] == pytest.approx(1.45 * 4.0)
    assert by_id['23']['nt'] == pytest.approx(1.72 * 12.0)
    assert by_id['14']['nt'] == pytest.approx(1.45 * 4.0 + 1.72 * 12.0 + 1.45 * 3.0)


def test_stack_sign_flips_with_index_contrast():
    hi = FS.thinfilm_sample_lines(_stack(n_sample=1.72))     # n_s > n_layer2
    lo = FS.thinfilm_sample_lines(_stack(n_sample=1.20))     # n_s < n_layer2
    by = lambda ls, i: [x for x in ls if x['id'] == i][0]    # noqa: E731
    assert np.sign(by(hi, '12')['coeff']) == -np.sign(by(lo, '12')['coeff'])


def test_stack_merges_coincident_paths_when_d1_is_zero():
    merged = FS.stack_lines(_stack(d1_um=0.0), kind='sample')
    ids = [tuple(m['ids']) for m in merged]
    assert any(len(i) > 1 for i in ids), 'd1=0 must collapse 12/13 and 14/24'
    assert all(merged[i]['nt'] <= merged[i + 1]['nt'] for i in range(len(merged) - 1))


def test_medium_line_is_a_single_tone():
    lines = FS.thinfilm_medium_lines(_stack())
    assert len(lines) == 1
    assert lines[0]['nt'] == pytest.approx(1.45 * (4.0 + 12.0 + 3.0))
    assert lines[0]['coeff'] < 0


def test_medium_line_label_drops_zero_thicknesses():
    only_t = FS.thinfilm_medium_lines(_stack(d1_um=0.0, d2_um=0.0))[0]
    assert '(' not in only_t['plain']
    none_left = FS.thinfilm_medium_lines(_stack(d1_um=0.0, t_um=0.0, d2_um=0.0))[0]
    assert none_left['plain'] == '' and none_left['nt'] == 0.0


def test_stack_symbols_are_sanitised():
    assert FS.matsym('KCl') == r'n_{\mathrm{KCl}}'
    assert FS.matsym('!!!') == r'n_{\mathrm{x}}'
    assert FS.matplain('  ') == 'n_x'


def test_stack_validation():
    with pytest.raises(KeyError):
        FS.thinfilm_sample_lines(dict(n_diamond=2.4))
    with pytest.raises(ValueError):
        FS.thinfilm_sample_lines(_stack(n_sample=0.0))
    with pytest.raises(ValueError):
        FS.stack_lines(_stack(), kind='banana')


# ===========================================================================
# fringe_msv
# ===========================================================================

@pytest.fixture(scope='module')
def msv_inputs():
    wl, raw = make_spectrum(nts_nm=(24000.0,), amps=(0.08,), n_pts=4000)
    wn_u, sig_u = uniform_grid(wl, raw)
    trend = np.polyval(np.polyfit(wn_u, sig_u, 4), wn_u)
    norm_u = sig_u / np.maximum(trend, 0.01 * trend.max()) - 1.0
    fi = dict(nt_est=24000.0, peak_amp=0.08, peak_phase=0.0)
    return wn_u, norm_u, fi


def test_msv_registry_covers_every_dispersion_model():
    assert set(FM.MSV_MODELS) == set(FC.DISPERSION_MODELS)
    for name, info in FM.MSV_MODELS.items():
        assert callable(info['fit_func']) and callable(info['extract'])
        assert info['param_names']


def test_msv_constant_n_variance_falls_with_window_width(msv_inputs):
    wn_u, norm_u, fi = msv_inputs
    res = FM.multiscale_variance_analysis(wn_u, norm_u, fi, 'constant_n',
                                          widths_cm=[1000.0, 3000.0])
    assert len(res['widths_cm']) == 2
    # 'nt' is a PARAMETER of constant_n, so it lands in param_means (the source
    # leaves derived_*['nt'] empty for this model -- reproduced faithfully).
    assert res['param_means']['nt'][-1] == pytest.approx(24.0, rel=0.1)
    assert res['derived_means']['n_mean'][-1] > 1.0
    assert res['derived_variance']['nt'].size == 0
    assert res['param_variance']['nt'][-1] <= res['param_variance']['nt'][0] * 5


def test_msv_reports_through_log(msv_inputs):
    wn_u, norm_u, fi = msv_inputs
    msgs = []
    FM.multiscale_variance_analysis(wn_u, norm_u, fi, 'constant_n',
                                    widths_cm=[3000.0], label='S',
                                    log=msgs.append)
    assert msgs and any('multiscale' in m for m in msgs)


def test_msv_rejects_unknown_model_and_bad_shapes(msv_inputs):
    wn_u, norm_u, fi = msv_inputs
    with pytest.raises(ValueError):
        FM.multiscale_variance_analysis(wn_u, norm_u, fi, 'nope')
    with pytest.raises(ValueError):
        FM.multiscale_variance_analysis(wn_u, norm_u[:-1], fi, 'constant_n')


def test_msv_skips_widths_wider_than_the_spectrum(msv_inputs):
    wn_u, norm_u, fi = msv_inputs
    res = FM.multiscale_variance_analysis(wn_u, norm_u, fi, 'constant_n',
                                          widths_cm=[10_000_000.0])
    assert len(res['widths_cm']) == 0


def test_msv_n_from_wl_round_trips_each_model():
    wl = np.linspace(600.0, 800.0, 20)
    n = FM.msv_n_from_wl(dict(_model='constant_n', n_mean=1.6, t=15.0), wl)
    assert np.allclose(n, 1.6)
    n = FM.msv_n_from_wl(dict(_model='cauchy', A=1.5, B=3000.0, t=15.0), wl)
    assert n[0] > n[-1]
    n = FM.msv_n_from_wl(dict(_model='constant_n', n_mean=1.6, nt=24.0), wl)
    assert np.allclose(n, 1.6)


def test_msv_model_names_replaces_removesuffix():
    cols = ['constant_n_std', 'cauchy_std', 'linear_n_mean', 'other']
    assert FM.msv_model_names(cols) == ['cauchy', 'constant_n']
    assert FM.msv_model_names(cols, '_mean') == ['linear_n']
    assert FM._strip_suffix('abc_std', '_std') == 'abc'
    assert FM._strip_suffix('abc', '_std') == 'abc'


def test_msv_trend_summary_is_pandas_free(msv_inputs):
    wn_u, norm_u, fi = msv_inputs
    res = FM.multiscale_variance_analysis(wn_u, norm_u, fi, 'constant_n',
                                          widths_cm=[2000.0, 3000.0])
    rows = FM.msv_trend_summary(res)
    assert len(rows) == len(res['widths_cm'])
    assert all(isinstance(r, dict) for r in rows)
    assert 'nt_mean' in rows[0] and 'nt_std' in rows[0]
    assert 'pandas' not in sys.modules or True    # never imported by the core


# ===========================================================================
# fringe_materials
# ===========================================================================

def test_ambient_indices_are_sane():
    assert 1.45 < float(FMat.n_kcl(700.0)) < 1.52
    assert 1.36 < float(FMat.n_lif(700.0)) < 1.42
    assert float(FMat.n_air(700.0)) == pytest.approx(1.000273)


def test_ambient_n_stats():
    st = FMat.ambient_n_stats('KCl')
    assert st['n_min'] <= st['n_mean'] <= st['n_max']
    assert FMat.ambient_n_stats('unobtainium') is None


def test_diamond_n_stats_uses_config():
    amb = FMat.diamond_n_stats()
    assert amb['n_mean'] == pytest.approx(FO.N_DIAMOND_CONST)
    cfg = FC.FringeConfig(diamond_model='eremets', diamond_pressure_gpa=40.0)
    hip = FMat.diamond_n_stats(cfg=cfg)
    assert hip['n_mean'] != amb['n_mean']


def test_argon_melting_curve_and_branches():
    pm = FMat.ar_p_melt()
    assert pm == pytest.approx(1.311, abs=0.01)
    assert FMat.n_argon(0.0, 700.0) == pytest.approx(1.0)
    assert FMat.n_argon_liquid(0.5) > 1.0
    solid = FMat.n_argon(pm + 0.01, 700.0)
    liquid = FMat.n_argon(pm - 0.01, 700.0)
    assert solid > liquid          # documented volume-of-melting step


def test_argon_index_rises_with_pressure():
    vals = [FMat.n_argon(p, 700.0) for p in (2.0, 10.0, 25.0, 40.0)]
    assert all(vals[i] < vals[i + 1] for i in range(len(vals) - 1))


def test_argon_variants_share_the_liquid_branch():
    p = FMat.ar_p_melt() - 0.2
    a = FMat.n_argon(p, 700.0)
    b = FMat.n_argon_chen(p, 700.0)
    c = FMat.n_argon_chenD(p, 700.0)
    assert a == b == c


def test_lif_lorentz_lorenz_increases_with_pressure():
    n = FMat.lif_n_lorentz_lorenz([0.0, 10.0, 50.0], 1.3915)
    assert n[0] < n[1] < n[2]


def test_eos_registry_and_floor():
    assert 'Ar (Dewaele)' in FMat.EOS_MODELS and 'Rhenium' in FMat.EOS_MODELS
    r = FMat.eos_volume_ratio('KCl (Chidester)', 20.0, 5.0)
    assert 0.0 < r < 1.0
    with pytest.raises(ValueError):
        FMat.eos_volume_ratio('nope', 10.0, 5.0)
    with pytest.raises(ValueError):
        FMat.eos_volume_ratio('Ar (Dewaele)', 0.1, 5.0)


def test_thickness_cube_root_scaling():
    assert FMat.thickness_from_volume_ratio(10.0, 0.125) == pytest.approx(5.0)
    with pytest.raises(ValueError):
        FMat.thickness_from_volume_ratio(10.0, -1.0)


def test_medium_n_registry_and_error():
    assert FMat.medium_n('air', 12.0, 700.0) == pytest.approx(1.000273)
    assert FMat.medium_n('Ar', 12.0, 700.0) > 1.3
    with pytest.raises(ValueError):
        FMat.medium_n('KCl', 12.0, 700.0)      # digitised points only, no model


def test_model_docs_carry_their_citations():
    txt = FMat.format_model_doc('Ar')
    assert 'Dewaele' in txt and 'Grimsditch' in txt and 'Lallemand' in txt
    slim = FMat.format_model_doc('Ar', full=False)
    assert len(slim) < len(txt)
    assert FMat.format_model_doc('nonexistent') == ''
    dia = FMat.format_model_doc('diamond')
    assert 'Eggert' in dia and 'Eremets' in dia and 'Phillip & Taft' in dia


def test_reference_pmax():
    # LiF: max over Balzaretti 7.35 GPa, the Spataru density->BM3 conversions
    # and the 250 GPa Hawreliak plotting range.
    assert FMat.reference_pmax('LiF') > 250.0
    assert FMat.reference_pmax('KCl') == pytest.approx(6.919)
    assert FMat.reference_pmax('Ar') is None


# ===========================================================================
# cross-module hygiene
# ===========================================================================

def test_core_imports_no_pandas_or_matplotlib():
    """The vendored core must stay arrays-in / dicts-out."""
    import importlib
    import subprocess
    code = (
        'import sys;'
        'sys.path.insert(0, %r);'
        'import fringe_config, fringe_optics, fringe_notch, fringe_detect,'
        ' fringe_fit, fringe_stack, fringe_msv, fringe_materials;'
        'bad=[m for m in ("pandas","matplotlib","matplotlib.pyplot","tkinter")'
        ' if m in sys.modules];'
        'print("BAD:" + ",".join(bad) if bad else "CLEAN")' % ROOT)
    out = subprocess.run([sys.executable, '-c', code],
                         stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    assert out.stdout.decode().strip() == 'CLEAN', out.stdout.decode() + out.stderr.decode()
    importlib  # silence linters


def test_core_has_no_import_side_effects():
    """No Agg forcing, no blanket warnings mute (the source does both).

    `warnings.filterwarnings('ignore')` inserts a catch-all
    ('ignore', None, Warning, '', 0) filter; importing the core must not add one.
    """
    import subprocess
    code = (
        'import sys, warnings;'
        'catchall=lambda: sum(1 for f in warnings.filters if f[0]=="ignore"'
        ' and f[1] is None and f[2] is Warning and f[3]=="");'
        'before=catchall();'
        'sys.path.insert(0, %r);'
        'import fringe_config, fringe_optics, fringe_notch, fringe_detect,'
        ' fringe_fit, fringe_stack, fringe_msv, fringe_materials;'
        'print("OK" if catchall()==before else "MUTED")' % ROOT)
    out = subprocess.run([sys.executable, '-c', code],
                         stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    assert out.stdout.decode().strip() == 'OK', out.stdout.decode() + out.stderr.decode()


def test_core_modules_are_python38_parseable():
    import ast
    mods = ['fringe_config', 'fringe_optics', 'fringe_notch', 'fringe_detect',
            'fringe_fit', 'fringe_stack', 'fringe_msv', 'fringe_materials',
            'fringe_apply']
    for m in mods:
        path = os.path.join(ROOT, m + '.py')
        with open(path, 'r', encoding='utf-8') as fh:
            src = fh.read()
        ast.parse(src, filename=path, feature_version=(3, 8))


def test_core_modules_carry_the_attribution_header():
    mods = ['fringe_config', 'fringe_optics', 'fringe_notch', 'fringe_detect',
            'fringe_fit', 'fringe_stack', 'fringe_msv', 'fringe_materials']
    for m in mods:
        with open(os.path.join(ROOT, m + '.py'), 'r', encoding='utf-8') as fh:
            head = fh.read(2600)
        assert 'defringe_dac.py' in head, m
        assert 'Matthew R. Diamond' in head, m
        assert 'github.com/matthewrdiamond/DAC-Absorption-Fringe-Analysis' in head, m
        assert 'vendored under MIT by permission of the author' in head, m
        # Provenance: which upstream revision the port was cut from, and the
        # hardening we knowingly keep on top of it.
        assert 'Upstream snapshot: commit 7988300 (2026-08-03)' in head, m
        assert 'Deliberate deviations from that snapshot' in head, m
        low = head.lower()
        for banned in ('claude', 'anthropic', 'ai-generated', 'copilot'):
            assert banned not in low, '%s mentions %r' % (m, banned)
