"""
Parity harness: SPARTA's vendored fringe core vs the original defringe_dac.py.

The original module forces `matplotlib.use('Agg')` and
`warnings.filterwarnings('ignore')` at import time, so it is NEVER imported
into the test process.  Instead a small driver script (embedded below) is
written to a temp directory and run as a subprocess; it loads the same input
arrays this test loads, evaluates the original functions on them, and writes
its answers back as .npz + .json.  The test then runs the vendored modules on
the identical inputs and compares.

Cases: two synthetic etalon spectra (single and double), seven real Y04_Arch29
spectra spanning 0-45 GPa (Background and Sample channels), and one older
Ta_AllFiles_Jan2026 visible-range set.

Compared:
    fisher_g_pvalue        exact, or the documented SPARTA-guard divergence
    fft_initial_guess      nt_est / fisher g / fisher p / peak amp+phase, exact
    2-of-3 corroboration   accepted n*t, exact
    defringe_fft_notch     output arrays, <= 1e-10 relative
    band_integrated_amp    <= 1e-10 relative
    fit_signal_constant_n  n*t, V, phi0, <= 1e-8 relative
    fit_signal_cauchy      A, B, t, phi0, n_mean, <= 1e-8 relative
    solve_paths            exact
    run_window_fits        vs the real `_run_all_fitters`, per model x window
                           tier: n_mean / t_um / nt_um / phi0 / model params,
                           <= 1e-10 relative (drift #1, #5, #6, #7); the tier
                           SET is asserted against SPARTA's documented gates
                           (drift #4, #10) rather than against his.

The whole module skips (rather than fails) when the original source tree or the
spectra are not present, so the suite still runs on a machine without them.
"""

import csv
import glob
import json
import os
import subprocess
import sys
import tempfile

import numpy as np
import pytest

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

# --- external locations -----------------------------------------------------
_PROGRAMS = os.path.dirname(ROOT)
_RESEARCH = os.path.dirname(_PROGRAMS)
SOURCE_DIR = os.path.join(_PROGRAMS, 'DAC-Absorption-Fringe-Analysis-main')
SOURCE_PY = os.path.join(SOURCE_DIR, 'defringe_dac.py')
Y04_CSV_DIR = os.path.join(_RESEARCH, 'June2026',
                           'Analysis_OpticalAbsorption_2026-06-25', 'csv',
                           'Y04_Arch29')
TA_DIR = os.path.join(_RESEARCH, 'Ta_AllFiles_Jan2026', 'USCGA',
                      'Chewy_ch29_Jun2025')

HAVE_SOURCE = os.path.isfile(SOURCE_PY)
HAVE_Y04 = os.path.isdir(Y04_CSV_DIR)

pytestmark = pytest.mark.skipif(
    not HAVE_SOURCE,
    reason='original defringe_dac.py not available at %s' % SOURCE_PY)


# ---------------------------------------------------------------------------
# The subprocess driver.  Runs against the ORIGINAL module only.
# ---------------------------------------------------------------------------

_DRIVER = r'''
import json, sys
import numpy as np

source_dir, job_npz, job_json, out_npz, out_json = sys.argv[1:6]
sys.path.insert(0, source_dir)
import defringe_dac as D

job = np.load(job_npz)
meta = json.load(open(job_json))

res = {}
arrays = {}

# --- solve_paths (pure math, config-free) ---------------------------------
sp = []
for a, c, iii, n2, nm in meta['solve_cases']:
    r = D.solve_paths(a, c, iii, n2, nm)
    if r is None:
        sp.append(None)
    else:
        sp.append(dict(n_s=r['n_s'], t_s=r['t_s'], t_layer2=r['t_layer2'],
                       L=r['L'], warns=list(r['warns'])))
res['solve_paths'] = sp

# --- optics scalars --------------------------------------------------------
wl_probe = np.asarray(meta['wl_probe'], float)
res['n_diamond'] = {}
for model in ('constant', 'cauchy', 'oscillator', 'eremets'):
    D.DIAMOND_MODEL = model
    D.DIAMOND_PRESSURE_GPA = meta['diamond_pressure_gpa']
    res['n_diamond'][model] = [float(v) for v in np.atleast_1d(D.n_diamond(wl_probe))]
D.DIAMOND_MODEL = 'constant'
D.DIAMOND_PRESSURE_GPA = 0.0
res['fresnel_V'] = [float(v) for v in np.atleast_1d(D.fresnel_V(np.asarray(meta['n_probe']), wl_probe))]
res['fresnel_n_from_V'] = [float(D.fresnel_n_from_V(v, 700.0)) for v in meta['V_probe']]
_af, _V = D.airy_factor(wl_probe, 1.5, 3000.0, 25000.0, 0.3)
arrays['airy_factor'] = np.asarray(_af, float)
arrays['airy_V'] = np.asarray(_V, float)
arrays['local_noise_floor'] = np.asarray(
    D.local_noise_floor(job['noise_probe'], window=7, n_sigma=3.0), float)

# --- Fisher overflow probe: a long near-flat periodogram, the case SPARTA's
# guard exists for (floor(1/g) ~ n terms; comb(n, j, exact=True) stops
# converting to float above ~1030 bins).
res['fisher_overflow'] = {}
for key in ('overflow_periodogram', 'overflow_periodogram_small'):
    try:
        g, pv = D.fisher_g_pvalue(job[key])
        res['fisher_overflow'][key] = [float(g), float(pv)]
    except Exception as exc:
        res['fisher_overflow'][key] = 'ERROR:' + type(exc).__name__

# --- materials -------------------------------------------------------------
mat = {}
mat['n_kcl'] = [float(v) for v in np.atleast_1d(D._n_kcl(wl_probe))]
mat['n_lif'] = [float(v) for v in np.atleast_1d(D._n_lif(wl_probe))]
mat['n_air'] = [float(v) for v in np.atleast_1d(D._n_air(wl_probe))]
mat['ar_p_melt'] = float(D._ar_p_melt())
mat['n_argon'] = [float(D._n_argon(p, 700.0)) for p in meta['pressures']]
mat['n_argon_chen'] = [float(D._n_argon_chen(p, 700.0)) for p in meta['pressures']]
mat['n_argon_chenD'] = [float(D._n_argon_chenD(p, 700.0)) for p in meta['pressures']]
mat['ar_density'] = [float(D._ar_density(p)) for p in meta['pressures'] if p >= D._AR_P_MIN]
mat['bm3_v_ratio'] = [float(D._bm3_v_ratio(p, 24.0, 4.56)) for p in meta['pressures']]
mat['vinet_density'] = [float(D._vinet_density(p)) for p in meta['pressures']]
mat['lif_ll'] = [float(v) for v in np.atleast_1d(
    D._lif_n_lorentz_lorenz(np.asarray(meta['pressures'], float), 1.3915))]
mat['eos'] = {}
for name in sorted(D._EOS_MODELS):
    fn = D._EOS_MODELS[name]['fn']
    floor = D._EOS_MODELS[name]['p_floor']
    mat['eos'][name] = [float(fn(max(p, floor * 1.001), max(5.0, floor * 1.001)))
                        for p in meta['pressures'] if p >= floor]
res['materials'] = mat

# --- thin-film stack -------------------------------------------------------
stack = []
for p in meta['stacks']:
    lines = D._thinfilm_sample_lines(p) + D._thinfilm_medium_lines(p)
    merged = D._merge_lines(lines)
    stack.append([dict(ids=list(m['ids']), desc=m['desc'], plain=m['plain'],
                       formula=m['formula'], nt=float(m['nt']),
                       coeff=float(m['coeff']), mag=float(m['mag']))
                  for m in merged])
res['stack'] = stack

# --- per-spectrum cases ----------------------------------------------------
cases = {}
for name in meta['case_names']:
    c = meta['cases'][name]
    D.FIT_WL_MIN_NM = c['wl_min']
    D.FIT_WL_MAX_NM = c['wl_max']
    wl = job[name + '__wl']
    raw = job[name + '__raw']
    rec = {}

    # (1) Fisher on the exact periodogram SPARTA computed.
    P = job[name + '__periodogram']
    try:
        g, pv = D.fisher_g_pvalue(P)
        rec['fisher_direct'] = [float(g), float(pv)]
    except Exception as exc:
        rec['fisher_direct'] = 'ERROR:' + type(exc).__name__

    # (2) fft_initial_guess on the narrow window.
    vis = (wl >= D.FIT_WL_MIN_NM) & (wl <= D.FIT_WL_MAX_NM)
    nt_n, fi_n = D.fft_initial_guess(wl[vis], raw[vis])
    rec['nt_narrow'] = None if nt_n is None else float(nt_n)
    if fi_n is None:
        rec['fi_narrow'] = None
    else:
        rec['fi_narrow'] = dict(nt_est=float(fi_n['nt_est']),
                                fisher_g=float(fi_n['fisher_g']),
                                fisher_pv=float(fi_n['fisher_pv']),
                                peak_amp=float(fi_n['peak_amp']),
                                peak_phase=float(fi_n['peak_phase']),
                                peak_idx=int(fi_n['peak_idx']),
                                n_peaks=int(len(fi_n['peaks_sorted'])))

    # (3) the 2-of-3 corroboration block, verbatim from compute_channel_fit.
    wl_wide_lo, wl_wide_hi = 1.0 / D.WIDE_HI, 1.0 / D.WIDE_LO
    wide_vis = (wl >= wl_wide_lo) & (wl <= wl_wide_hi)
    nt_w, fi_w = D.fft_initial_guess(wl[wide_vis], raw[wide_vis])
    nt_f, fi_f = D.fft_initial_guess(wl, raw)
    detections = []
    for wname, winfo in [('narrow', fi_n), ('wide', fi_w), ('full', fi_f)]:
        if (winfo and winfo.get('nt_est') is not None
                and winfo.get('fisher_pv', 1.0) <= D.FRINGE_PVALUE_MAX):
            detections.append((wname, float(winfo['nt_est'])))
    best_group = []
    for _, nti in detections:
        grp = [d for d in detections if abs(d[1] - nti) / nti <= D.NT_AGREE_TOL]
        if len(grp) > len(best_group):
            best_group = grp
    if len(best_group) >= 2 and fi_n is not None:
        names = [g[0] for g in best_group]
        nt_acc = (float(fi_n['nt_est']) if 'narrow' in names
                  else float(np.median([g[1] for g in best_group])))
    else:
        names = []
        nt_acc = None
    rec['nt_accepted'] = nt_acc
    rec['corroborated_by'] = names
    rec['detections'] = [[n, float(t)] for n, t in detections]

    # (4) notch on the full uniform grid at a FIXED probe centre.
    wn_full = 1.0 / wl
    sidx = np.argsort(wn_full)
    wn_u_full = np.linspace(wn_full[sidx[0]], wn_full[sidx[-1]], len(wl))
    sig_u_full = np.interp(wn_u_full, wn_full[sidx], raw[sidx])
    nt_probe = float(c['nt_probe'])
    I_clean, nt_est, sig_filt = D.defringe_fft_notch(
        wn_u_full, sig_u_full, wl, raw, nt_probe)
    arrays[name + '__notch_Iclean'] = np.asarray(I_clean, float)
    arrays[name + '__notch_filt'] = np.asarray(sig_filt, float)
    rec['notch_nt_est'] = float(nt_est)

    # (4b) multi-centre notch + low-pass.
    centers = [float(x) for x in c['notch_centers']]
    widths = [float(x) for x in c['notch_widths']]
    I_clean2, _, sig_filt2 = D.defringe_fft_notch(
        wn_u_full, sig_u_full, wl, raw, nt_probe,
        halfwidth_um=2.5, notch_centers_nm=centers, notch_halfwidths_um=widths,
        lowpass=True, lp_cutoff_um=30.0, lp_rolloff_um=2.0)
    arrays[name + '__notch2_Iclean'] = np.asarray(I_clean2, float)
    arrays[name + '__notch2_filt'] = np.asarray(sig_filt2, float)

    # (4c) width sweep.
    sweep = D.notch_width_sweep(wn_u_full, sig_u_full, nt_probe,
                                wl=wl, raw=raw)
    arrays[name + '__sweep_power'] = np.asarray(sweep['residual_power'], float)
    arrays[name + '__sweep_clean'] = np.asarray(sweep['I_clean_wl'], float)

    # (5) band-integrated amplitude on SPARTA's exact norm_u.
    wn_u = job[name + '__wn_u']
    norm_u = job[name + '__norm_u']
    rec['band_amp'] = float(D.band_integrated_amplitude(wn_u, norm_u, nt_probe))
    rec['band_amp_wide'] = float(
        D.band_integrated_amplitude(wn_u, norm_u, nt_probe, halfwidth_um=6.0))
    rec['band_amp_nofloor'] = float(
        D.band_integrated_amplitude(wn_u, norm_u, nt_probe, res_floor=False))

    # (6) the fitters on the identical (wn_u, norm_u, nt_est, peak_amp).
    fi = dict(wn_u=wn_u, norm_u=norm_u, nt_est=float(c['fit_nt_est']),
              peak_amp=float(c['fit_peak_amp']), peak_phase=0.0)
    try:
        nt_fit, V_fit, phi0, fringe_win = D.fit_signal_constant_n(
            fi, label=name, quiet=True)
        rec['constant_n'] = [float(nt_fit), float(V_fit), float(phi0)]
        arrays[name + '__cn_fringe'] = np.asarray(fringe_win, float)
    except Exception as exc:
        rec['constant_n'] = 'ERROR:' + type(exc).__name__
    try:
        A, B, t, phi0c, fw, _wn, _a, _b = D.fit_signal_cauchy(fi, label=name)
        rd = D._dispersion_result_dict([A, B, t, phi0c], 1.0 / wn_u, 'cauchy')
        rec['cauchy'] = [float(A), float(B), float(t), float(phi0c),
                         float(rd['n_mean']), float(rd['t_um']), float(rd['nt_um'])]
        arrays[name + '__cau_fringe'] = np.asarray(fw, float)
    except Exception as exc:
        rec['cauchy'] = 'ERROR:' + type(exc).__name__
    try:
        t_l, phi0_l, n0_l, n1_l, fw_l, _wn, _a, _b = D.fit_signal_linear_n(fi, label=name)
        rec['linear_n'] = [float(t_l), float(phi0_l), float(n0_l), float(n1_l)]
    except Exception as exc:
        rec['linear_n'] = 'ERROR:' + type(exc).__name__

    # (7) fine_fit_sigma at the constant_n optimum.
    if isinstance(rec['constant_n'], list):
        nt_fit, V_fit, phi0 = rec['constant_n']
        wl_ref = 1.0 / float(np.mean(wn_u))
        n_fit = float(D.fresnel_n_from_V(V_fit, wl_ref))
        sig = D._fine_fit_sigma('constant_n',
                                [n_fit, nt_fit / max(n_fit, 1e-6), phi0],
                                wn_u, norm_u)
        rec['sigma_constant_n'] = {k: float(v) for k, v in sig.items()}

    cases[name] = rec

res['cases'] = cases

# --- window tiering: the whole of _run_all_fitters' LSQ half ---------------
# Called for real (not re-implemented here) on the SAME uniform grids SPARTA
# built, so every number below is his own.  MSV / figures / landscapes are
# switched off: they are compared elsewhere and cost minutes.
D.multiscale = False
D.landscape = False
D.SAVE_FIGS = False
D.PLOT_MULTISCALE = False
_FINE_LO_0, _FINE_HI_0 = D.FINE_WN_LO, D.FINE_WN_HI
rwf = {}
for rkey in sorted(meta['rwf_jobs']):
    j = meta['rwf_jobs'][rkey]
    name = j['case']
    D.FIT_WL_MIN_NM = j['wl_min']
    D.FIT_WL_MAX_NM = j['wl_max']
    if j['fine_center_cm'] is None:
        D.FINE_WN_LO, D.FINE_WN_HI = _FINE_LO_0, _FINE_HI_0
    else:
        D.FINE_WN_LO = (j['fine_center_cm'] - D.FINE_WIDTH_CM / 2.0) * 1e-7
        D.FINE_WN_HI = (j['fine_center_cm'] + D.FINE_WIDTH_CM / 2.0) * 1e-7
    ym = tuple(j['year_month']) if j['year_month'] else None
    fi = dict(nt_est=float(j['nt_est']), peak_amp=float(j['peak_amp']),
              peak_phase=float(j['peak_phase']))
    try:
        result, _pc, _lc, _sc = D._run_all_fitters(
            'lsq', fi,
            job[name + '__rwf_norm_u_full'], job[name + '__rwf_wn_u_full'],
            job[name + '__rwf_sig_u_full'],
            job[name + '__wl'], job[name + '__raw'],
            float(j['nt']), name, False, year_month=ym)
    except Exception as exc:
        rwf[rkey] = 'ERROR:%s:%s' % (type(exc).__name__, str(exc)[:160])
        continue
    got = {}
    for mkey, dkey in (('cauchy', 'cauchy'), ('linear_n', 'linear_n'),
                       ('constant_n', 'constant_n_cw')):
        sub = result.get(dkey)
        if not sub:
            continue
        per_win = {}
        for w in ('full', 'wide', 'narrow', 'fine'):
            if sub.get('n_mean_' + w) is None:
                continue
            e = dict(n_mean=float(sub['n_mean_' + w]),
                     t_um=float(sub['t_um_' + w]),
                     nt_um=float(sub['nt_um_' + w]),
                     phi0=float(sub.get('phi0_' + w) or 0.0))
            if mkey == 'cauchy':
                e['A'] = float(sub['A_' + w])
                e['B'] = float(sub['B_' + w])
            elif mkey == 'linear_n':
                e['n0'] = float(sub['n0_' + w])
                e['n1'] = float(sub['n1_' + w])
            else:
                e['V'] = float(sub['V_' + w])
            per_win[w] = e
        got[mkey] = per_win
    rwf[rkey] = got
D.FINE_WN_LO, D.FINE_WN_HI = _FINE_LO_0, _FINE_HI_0
res['run_window_fits'] = rwf

np.savez(out_npz, **arrays)
with open(out_json, 'w') as fh:
    json.dump(res, fh)
print('driver ok')
'''


# ---------------------------------------------------------------------------
# Input construction
# ---------------------------------------------------------------------------

def _synth_etalon(n_pts=2400, wl_lo=380.0, wl_hi=1050.0, nts_nm=(24000.0,),
                  amps=(0.09,), seed=7, lamp=True):
    """Synthetic raw-counts spectrum with one or more etalon fringes."""
    rng = np.random.RandomState(seed)
    wl = np.linspace(wl_lo, wl_hi, n_pts)
    wn = 1.0 / wl
    env = (12000.0 * np.exp(-0.5 * ((wl - 720.0) / 260.0) ** 2) + 600.0
           if lamp else np.full_like(wl, 8000.0))
    modulation = np.zeros_like(wl)
    for nt, amp in zip(nts_nm, amps):
        modulation += amp * np.cos(2.0 * np.pi * (2.0 * nt) * wn + 0.37)
    counts = env * (1.0 + modulation) + rng.normal(0.0, 6.0, n_pts)
    return wl, counts


def _load_y04(path):
    with open(path, 'r', encoding='utf-8') as fh:
        rows = list(csv.reader(fh))
    arr = np.array([[float(x) if x else np.nan for x in r] for r in rows[1:]])
    return arr[:, 0], arr[:, 4], arr[:, 5]     # wl, Background, Sample


def _load_ta(path):
    d = np.loadtxt(path, delimiter=',', skiprows=1)
    return d[:, 0], d[:, 1]


def _build_cases():
    """(cases, meta) where cases[name] = dict(wl, raw, wl_min, wl_max)."""
    cases = {}

    wl, y = _synth_etalon(nts_nm=(24000.0,), amps=(0.09,), seed=7)
    cases['synth_single'] = dict(wl=wl, raw=y, wl_min=600.0, wl_max=800.0)

    wl, y = _synth_etalon(nts_nm=(21000.0, 46000.0), amps=(0.07, 0.035), seed=11)
    cases['synth_double'] = dict(wl=wl, raw=y, wl_min=600.0, wl_max=800.0)

    wl, y = _synth_etalon(nts_nm=(24000.0,), amps=(0.0,), seed=13)
    cases['synth_flat'] = dict(wl=wl, raw=y, wl_min=600.0, wl_max=800.0)

    if HAVE_Y04:
        picks = [('0p0', 'bg'), ('0p3', 's'), ('11p2', 'bg'), ('18p7', 'bg'),
                 ('26p0', 's'), ('35p0', 'bg'), ('45p5', 'bg')]
        for tag, chan in picks:
            path = os.path.join(Y04_CSV_DIR, 'Y04_Arch29_%s_absorbance.csv' % tag)
            if not os.path.isfile(path):
                continue
            w, bg, s = _load_y04(path)
            cases['y04_%s_%s' % (tag, chan)] = dict(
                wl=w, raw=(bg if chan == 'bg' else s),
                wl_min=600.0, wl_max=800.0)

    if os.path.isdir(TA_DIR):
        hits = sorted(glob.glob(os.path.join(TA_DIR, '*_s.001')))
        if hits:
            w, y = _load_ta(hits[len(hits) // 2])
            # Visible-only spectrometer (378-554 nm): the default 600-800 nm
            # window is empty there, so this case also exercises config-driven
            # window relocation (the source reads its globals, which the driver
            # sets to the same values).
            cases['ta_chewy_ch29'] = dict(wl=w, raw=y, wl_min=400.0, wl_max=545.0)

    return cases


_SOLVE_CASES = [
    (10.0, 12.0, 20.0, 1.4, 1.3),      # n_s floor path
    (30.0, 42.0, 55.0, 1.45, 1.28),    # ordinary
    (5.0, 4.0, 30.0, 1.5, 1.2),        # t_layer2 floor path
    (60.0, 61.0, 12.0, 1.5, 1.2),      # t_s floor path
    (25.0, 30.0, 40.0, 1.0, 1.0),      # unit indices
    (25.0, 30.0, 40.0, 0.0, 1.2),      # non-positive index -> None
    (25.0, 30.0, 40.0, 1.2, -1.0),     # non-positive index -> None
]

_STACKS = [
    dict(n_diamond=2.4168, n_layer2=1.45, n_sample=1.72, n_medium=1.45,
         d1_um=4.0, t_um=12.0, d2_um=3.0, layer2_name='KCl',
         sample_name='ch29', medium_name='KCl'),
    dict(n_diamond=2.4168, n_layer2=1.30, n_sample=1.20, n_medium=1.30,
         d1_um=0.0, t_um=18.0, d2_um=0.0, layer2_name='Ar',
         sample_name='LiF', medium_name='Ar'),
    dict(n_diamond=2.4168, n_layer2=1.40, n_sample=1.40, n_medium=1.40,
         d1_um=5.0, t_um=0.0, d2_um=5.0, layer2_name='KCl',
         sample_name='none', medium_name='KCl'),
]

_PRESSURES = [0.0, 0.05, 0.5, 1.2, 1.4, 2.0, 5.0, 12.5, 25.0, 40.0]
_WL_PROBE = [450.0, 600.0, 700.0, 800.0, 1000.0]

# --- window-tiering (run_window_fits <-> _run_all_fitters) job selection ----
# Every tiering job runs 3 models x 3-4 windows of Nelder-Mead on BOTH sides,
# so the case list is deliberately short.  'pre' = the pre-Nov-2025 lamp
# (fine centre 13500 cm^-1, source year_month=None); 'post' = the Nov-2025+
# lamp (fine centre 11200 cm^-1, source year_month=(2025, 11)), which is the
# only regime in which either side runs the NARROW tier on a 600-800 nm case.
_RWF_CASE_ORDER = ['synth_single', 'y04_0p0_bg', 'y04_11p2_bg', 'y04_35p0_bg',
                   'ta_chewy_ch29']
_RWF_POST_CASES = ['synth_single', 'y04_0p0_bg']
_RWF_REGIMES = {
    'pre':  dict(fine_center_cm=None, year_month=None, lamp_regime=None),
    'post': dict(fine_center_cm=11200.0, year_month=[2025, 11],
                 lamp_regime='nov2025_plus'),
}
#: Aligned paths must agree to this.  Not a fudge factor: the two sides run the
#: same optimiser on the same arrays, so the only spread is float association.
_RWF_TOL = 1e-10


@pytest.fixture(scope='module')
def parity():
    """Build inputs, run the original in a subprocess, return (inputs, ref)."""
    import fringe_config as FC
    import fringe_detect as FD

    cases = _build_cases()
    if not cases:
        pytest.skip('no parity input spectra available')

    tmpdir = tempfile.mkdtemp(prefix='fringe_parity_')
    job_npz = os.path.join(tmpdir, 'job.npz')
    job_json = os.path.join(tmpdir, 'job.json')
    out_npz = os.path.join(tmpdir, 'ref.npz')
    out_json = os.path.join(tmpdir, 'ref.json')

    arrays = {}
    meta_cases = {}
    rng = np.random.RandomState(3)
    arrays['noise_probe'] = (np.sin(np.linspace(0, 20, 400))
                             + rng.normal(0, 0.05, 400))
    # Flat periodograms: floor(1/g) == n, so the exact alternating sum needs n
    # terms.  1400 bins overflows comb(n, j, exact=True) -> float in the source;
    # 40 bins merely trips SPARTA's p_terms cap.
    arrays['overflow_periodogram'] = np.ones(1400)
    arrays['overflow_periodogram_small'] = np.ones(40)

    for name, c in cases.items():
        wl = np.asarray(c['wl'], float)
        raw = np.asarray(c['raw'], float)
        cfg = FC.DEFAULT_CONFIG.evolve(fit_wl_min_nm=c['wl_min'],
                                       fit_wl_max_nm=c['wl_max'])
        c['cfg'] = cfg

        # Periodogram for the Fisher comparison: SPARTA's own narrow-window FFT.
        vis = (wl >= cfg.fit_wl_min_nm) & (wl <= cfg.fit_wl_max_nm)
        wn = 1.0 / wl[vis]
        si = np.argsort(wn)
        wn_u = np.linspace(wn[si][0], wn[si][-1], si.size)
        sig_u = np.interp(wn_u, wn[si], raw[vis][si])
        trend = np.polyval(np.polyfit(wn_u, sig_u, 4), wn_u)
        trend = np.maximum(trend, 0.01 * float(trend.max()))
        norm_u = sig_u / trend - 1.0
        win = np.hanning(norm_u.size)
        amp = np.abs(np.fft.rfft(norm_u * win))
        freqs = np.fft.rfftfreq(norm_u.size, d=wn_u[1] - wn_u[0])
        band = (freqs >= cfg.freq_min) & (freqs <= cfg.freq_max)
        periodogram = amp[band] ** 2

        # Fit inputs: identical arrays for both sides.
        nt_seed = float(freqs[np.argmax(np.where(band, amp, 0.0))] / 2.0)
        if not (nt_seed > 0):
            nt_seed = 24000.0
        peak_amp = float(2.0 * amp[np.argmax(np.where(band, amp, 0.0))]
                         / np.sum(win))
        peak_amp = float(min(max(peak_amp, 1e-4), 0.45))

        _fit, _I, nt_det, _dc = FD.compute_channel_fit(
            wl, raw, cfg=cfg, label=name, run_fits=False)
        nt_probe = float(nt_det) if nt_det else 24000.0

        # Uniform full grids for the window-tiering comparison.  Both sides get
        # SPARTA's arrays verbatim, so the tiering is the only thing under test.
        _fi = _fit.get('fft_info') or {}
        if nt_det is not None and _fi.get('norm_u_full') is not None:
            c['rwf'] = dict(wn_u_full=np.asarray(_fi['wn_u_full'], float),
                            norm_u_full=np.asarray(_fi['norm_u_full'], float),
                            sig_u_full=np.asarray(_fi['sig_u_full'], float),
                            nt=float(nt_det),
                            nt_est=float(_fi['nt_est']),
                            peak_amp=float(_fi['peak_amp']),
                            peak_phase=float(_fi['peak_phase']))
            arrays[name + '__rwf_wn_u_full'] = c['rwf']['wn_u_full']
            arrays[name + '__rwf_norm_u_full'] = c['rwf']['norm_u_full']
            arrays[name + '__rwf_sig_u_full'] = c['rwf']['sig_u_full']

        arrays[name + '__wl'] = wl
        arrays[name + '__raw'] = raw
        arrays[name + '__periodogram'] = periodogram
        arrays[name + '__wn_u'] = wn_u
        arrays[name + '__norm_u'] = norm_u
        meta_cases[name] = dict(
            wl_min=c['wl_min'], wl_max=c['wl_max'], nt_probe=nt_probe,
            fit_nt_est=nt_seed, fit_peak_amp=peak_amp,
            notch_centers=[nt_probe, 2.0 * nt_probe],
            notch_widths=[2.5, 4.0])
        c['meta'] = meta_cases[name]
        c['wn_u'] = wn_u
        c['norm_u'] = norm_u
        c['periodogram'] = periodogram

    rwf_jobs = {}
    for name in _RWF_CASE_ORDER:
        c = cases.get(name)
        if not c or 'rwf' not in c:
            continue
        regimes = ['pre'] + (['post'] if name in _RWF_POST_CASES else [])
        for regime in regimes:
            r = _RWF_REGIMES[regime]
            rwf_jobs['%s@%s' % (name, regime)] = dict(
                case=name, regime=regime,
                wl_min=c['wl_min'], wl_max=c['wl_max'],
                fine_center_cm=r['fine_center_cm'],
                year_month=r['year_month'],
                nt=c['rwf']['nt'], nt_est=c['rwf']['nt_est'],
                peak_amp=c['rwf']['peak_amp'],
                peak_phase=c['rwf']['peak_phase'])

    # A 6 nm window at the red end of the synthetic spectrum, added in
    # R15-G to look for the source-side abort the hardening test wants.
    # It did NOT produce one: both sides tier the sliver and agree on it
    # exactly (worst rel 0 over its own 51 values), so the two paths are
    # pinned on a short window as well. The abort branch stays unproved
    # and the hardening test still skips loudly -- see its docstring.
    _sc = cases.get('synth_single')
    if _sc and 'rwf' in _sc:
        rwf_jobs['synth_single@short'] = dict(
            case='synth_single', regime='pre',
            wl_min=794.0, wl_max=800.0,
            fine_center_cm=None, year_month=None,
            nt=_sc['rwf']['nt'], nt_est=_sc['rwf']['nt_est'],
            peak_amp=_sc['rwf']['peak_amp'],
            peak_phase=_sc['rwf']['peak_phase'])

    np.savez(job_npz, **arrays)
    meta = dict(case_names=sorted(cases), cases=meta_cases,
                solve_cases=_SOLVE_CASES, stacks=_STACKS,
                pressures=_PRESSURES, wl_probe=_WL_PROBE,
                n_probe=[1.2, 1.4, 1.6, 1.8, 2.0],
                V_probe=[0.001, 0.05, 0.2, 0.5, 1.5],
                rwf_jobs=rwf_jobs,
                diamond_pressure_gpa=18.5)
    with open(job_json, 'w') as fh:
        json.dump(meta, fh)

    driver_path = os.path.join(tmpdir, 'run_original.py')
    with open(driver_path, 'w', encoding='utf-8') as fh:
        fh.write(_DRIVER)

    env = dict(os.environ)
    env['PYTHONIOENCODING'] = 'utf-8'
    env['MPLBACKEND'] = 'Agg'
    proc = subprocess.run(
        [sys.executable, driver_path, SOURCE_DIR, job_npz, job_json,
         out_npz, out_json],
        stdout=subprocess.PIPE, stderr=subprocess.PIPE, env=env, cwd=tmpdir)
    if proc.returncode != 0:
        pytest.skip('reference driver failed (rc=%d):\n%s'
                    % (proc.returncode, proc.stderr.decode('utf-8', 'replace')[-4000:]))

    with open(out_json, 'r') as fh:
        ref = json.load(fh)
    ref_arrays = np.load(out_npz)
    meta['_job_arrays'] = {k: arrays[k] for k in
                           ('noise_probe', 'overflow_periodogram',
                            'overflow_periodogram_small')}
    return cases, ref, ref_arrays, meta


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------

def _rel(a, b):
    """Max relative deviation, falling back to absolute where b ~ 0."""
    a = np.asarray(a, float)
    b = np.asarray(b, float)
    if a.shape != b.shape:
        return np.inf
    denom = np.maximum(np.abs(b), np.abs(a))
    scale = np.max(denom) if denom.size else 1.0
    if not np.isfinite(scale) or scale == 0.0:
        return float(np.max(np.abs(a - b))) if a.size else 0.0
    return float(np.max(np.abs(a - b)) / scale)


def _case_names(cases):
    return sorted(cases)


# ---------------------------------------------------------------------------
# Tests: config-free pure math
# ---------------------------------------------------------------------------

def test_parity_solve_paths(parity):
    import fringe_optics as FO
    _cases, ref, _arr, _meta = parity
    for args, want in zip(_SOLVE_CASES, ref['solve_paths']):
        got = FO.solve_paths(*args)
        if want is None:
            assert got is None, 'solve_paths%s should be None' % (args,)
            continue
        assert got is not None
        for k in ('n_s', 't_s', 't_layer2', 'L'):
            assert got[k] == want[k], 'solve_paths%s key %s' % (args, k)
        # Documented divergence: SPARTA's clamp messages are ASCII (they are
        # written into CSV provenance columns and to a cp1252 console on the
        # Win7 build); the source spells the same message with a U+2192 arrow.
        assert ([w.replace(u'→', '->') for w in want['warns']]
                == list(got['warns'])), 'solve_paths%s warns' % (args,)


def test_parity_diamond_models(parity):
    import fringe_config as FC
    import fringe_optics as FO
    _cases, ref, _arr, meta = parity
    wl = np.asarray(meta['wl_probe'], float)
    for model, want in ref['n_diamond'].items():
        cfg = FC.DEFAULT_CONFIG.evolve(
            diamond_model=model,
            diamond_pressure_gpa=meta['diamond_pressure_gpa'])
        got = np.atleast_1d(FO.n_diamond(wl, cfg=cfg))
        assert _rel(got, want) == 0.0, 'n_diamond[%s]' % model


def test_parity_fresnel(parity):
    import fringe_optics as FO
    _cases, ref, arr, meta = parity
    wl = np.asarray(meta['wl_probe'], float)
    got = np.atleast_1d(FO.fresnel_V(np.asarray(meta['n_probe']), wl))
    assert _rel(got, ref['fresnel_V']) == 0.0
    got_n = [FO.fresnel_n_from_V(v, 700.0) for v in meta['V_probe']]
    assert _rel(got_n, ref['fresnel_n_from_V']) == 0.0
    af, V = FO.airy_factor(wl, 1.5, 3000.0, 25000.0, 0.3)
    assert _rel(af, arr['airy_factor']) == 0.0
    assert _rel(V, arr['airy_V']) == 0.0


def test_parity_local_noise_floor(parity):
    import fringe_optics as FO
    _cases, _ref, arr, meta = parity
    probe = meta['_job_arrays']['noise_probe']
    got = FO.local_noise_floor(probe, window=7, n_sigma=3.0)
    assert _rel(got, arr['local_noise_floor']) == 0.0


def test_parity_fisher_overflow_divergence(parity):
    """The guard's raison d'etre: the source overflows, SPARTA returns p = 1.

    A perfectly flat periodogram of n bins gives g = 1/n, so floor(1/g) = n and
    the exact alternating sum needs n terms.  At n = 1400 the source's
    `comb(n, j, exact=True)` returns a Python int too large to convert to float
    and the sum raises; at n = 40 it merely wastes precision.  Both are
    "no significant periodicity", which is what the guard reports.
    """
    import fringe_detect as FD
    _cases, ref, _arr, meta = parity
    big = meta['_job_arrays']['overflow_periodogram']
    small = meta['_job_arrays']['overflow_periodogram_small']

    want_big = ref['fisher_overflow']['overflow_periodogram']
    g, pv = FD.fisher_g_pvalue(big)
    assert g == 1.0 / big.size
    assert pv == 1.0
    assert isinstance(want_big, str) and want_big.startswith('ERROR:'), (
        'expected the unpatched source to raise on a %d-bin flat periodogram, '
        'got %r' % (big.size, want_big))

    want_small = ref['fisher_overflow']['overflow_periodogram_small']
    g2, pv2 = FD.fisher_g_pvalue(small)
    assert pv2 == 1.0                      # guard: p_terms = 40 > 30
    assert isinstance(want_small, list)    # source did not raise here
    assert g2 == want_small[0]             # ... and the g-statistic still agrees

    # With the cap lifted to n, SPARTA reproduces the source's exact sum.
    g3, pv3 = FD.fisher_g_pvalue(small, p_terms_max=small.size)
    assert g3 == want_small[0]
    assert _rel([pv3], [want_small[1]]) <= 1e-12


def test_parity_materials(parity):
    import fringe_materials as FMat
    import fringe_optics as FO
    _cases, ref, _arr, meta = parity
    m = ref['materials']
    wl = np.asarray(meta['wl_probe'], float)
    P = meta['pressures']
    assert _rel(np.atleast_1d(FMat.n_kcl(wl)), m['n_kcl']) == 0.0
    assert _rel(np.atleast_1d(FMat.n_lif(wl)), m['n_lif']) == 0.0
    assert _rel(np.atleast_1d(FMat.n_air(wl)), m['n_air']) == 0.0
    assert FMat.ar_p_melt() == m['ar_p_melt']
    assert _rel([FMat.n_argon(p, 700.0) for p in P], m['n_argon']) <= 1e-12
    assert _rel([FMat.n_argon_chen(p, 700.0) for p in P], m['n_argon_chen']) <= 1e-12
    assert _rel([FMat.n_argon_chenD(p, 700.0) for p in P], m['n_argon_chenD']) <= 1e-12
    assert _rel([FMat.bm3_v_ratio(p, 24.0, 4.56) for p in P], m['bm3_v_ratio']) <= 1e-12
    assert _rel([FO.vinet_density(p) for p in P], m['vinet_density']) <= 1e-12
    assert _rel(np.atleast_1d(FMat.lif_n_lorentz_lorenz(np.asarray(P, float), 1.3915)),
                m['lif_ll']) <= 1e-12
    for name, want in m['eos'].items():
        floor = FMat.EOS_MODELS[name]['p_floor']
        got = [FMat.EOS_MODELS[name]['fn'](max(p, floor * 1.001),
                                           max(5.0, floor * 1.001))
               for p in P if p >= floor]
        assert _rel(got, want) <= 1e-12, 'EOS %s' % name


def test_parity_stack_lines(parity):
    import fringe_stack as FS
    _cases, ref, _arr, _meta = parity
    for p, want in zip(_STACKS, ref['stack']):
        lines = FS.thinfilm_sample_lines(p) + FS.thinfilm_medium_lines(p)
        got = FS.merge_lines(lines)
        assert len(got) == len(want)
        for g, w in zip(got, want):
            assert list(g['ids']) == list(w['ids'])
            assert g['desc'] == w['desc']
            assert g['plain'] == w['plain']
            assert g['formula'] == w['formula']
            assert g['nt'] == w['nt']
            assert g['coeff'] == w['coeff']
            assert g['mag'] == w['mag']


# ---------------------------------------------------------------------------
# Tests: per-spectrum
# ---------------------------------------------------------------------------

def test_parity_fisher_guard(parity):
    """Fisher parity, and the documented SPARTA-guard divergence."""
    import fringe_detect as FD
    cases, ref, _arr, _meta = parity
    diverged = []
    for name in _case_names(cases):
        want = ref['cases'][name]['fisher_direct']
        P = cases[name]['periodogram']
        g, pv = FD.fisher_g_pvalue(P)
        if isinstance(want, str):
            # The unpatched source raised.  SPARTA's guard must return p == 1.0.
            assert pv == 1.0, ('%s: source raised %s but SPARTA returned p=%r'
                               % (name, want, pv))
            diverged.append((name, want))
            continue
        g_ref, pv_ref = want
        assert g == g_ref, '%s: Fisher g' % name
        p_terms_ref = int(1.0 / g_ref) if g_ref > 0 else 0
        if p_terms_ref > FD.DEFAULT_CONFIG.fisher_p_terms_max:
            # Guard fires: SPARTA reports "not significant" instead of the
            # cancellation-dominated exact sum.
            assert pv == 1.0
            diverged.append((name, 'guard p_terms=%d' % p_terms_ref))
        else:
            assert pv == pv_ref, '%s: Fisher p' % name
    print('fisher divergences (expected):', diverged)


def test_parity_fft_initial_guess(parity):
    import fringe_detect as FD
    cases, ref, _arr, _meta = parity
    for name in _case_names(cases):
        c = cases[name]
        want = ref['cases'][name]
        cfg = c['cfg']
        wl, raw = c['wl'], c['raw']
        vis = (wl >= cfg.fit_wl_min_nm) & (wl <= cfg.fit_wl_max_nm)
        nt, fi = FD.fft_initial_guess(wl[vis], raw[vis], cfg=cfg)
        if want['fi_narrow'] is None:
            assert fi is None or fi.get('fisher_pv', 1.0) > cfg.fringe_pvalue_max, name
            continue
        assert fi is not None, name
        w = want['fi_narrow']
        assert fi['nt_est'] == w['nt_est'], '%s nt_est' % name
        assert fi['peak_idx'] == w['peak_idx'], '%s peak_idx' % name
        assert fi['peak_amp'] == w['peak_amp'], '%s peak_amp' % name
        assert fi['peak_phase'] == w['peak_phase'], '%s peak_phase' % name
        assert fi['fisher_g'] == w['fisher_g'], '%s fisher_g' % name
        assert len(fi['peaks_sorted']) == w['n_peaks'], '%s n_peaks' % name
        # Fisher p either matches exactly or is the documented guard divergence.
        if fi['fisher_pv'] != w['fisher_pv']:
            assert fi['fisher_pv'] == 1.0, '%s fisher_pv' % name
        # nt_est acceptance decision must agree whenever p matches.
        if fi['fisher_pv'] == w['fisher_pv']:
            assert (nt is None) == (want['nt_narrow'] is None), '%s accept' % name
            if nt is not None:
                assert nt == want['nt_narrow'], '%s nt' % name


def test_parity_corroboration(parity):
    import fringe_detect as FD
    cases, ref, _arr, _meta = parity
    for name in _case_names(cases):
        c = cases[name]
        want = ref['cases'][name]
        cfg = c['cfg']
        wl, raw = c['wl'], c['raw']
        vis = (wl >= cfg.fit_wl_min_nm) & (wl <= cfg.fit_wl_max_nm)
        _nt, fi_n = FD.fft_initial_guess(wl[vis], raw[vis], cfg=cfg)
        wide = (wl >= 1.0 / cfg.wide_hi) & (wl <= 1.0 / cfg.wide_lo)
        _ntw, fi_w = FD.fft_initial_guess(wl[wide], raw[wide], cfg=cfg)
        _ntf, fi_f = FD.fft_initial_guess(wl, raw, cfg=cfg)
        corr = FD.corroborate_nt([('narrow', fi_n), ('wide', fi_w),
                                  ('full', fi_f)], cfg=cfg)
        assert corr['nt'] == want['nt_accepted'], '%s accepted n*t' % name
        assert list(corr['names']) == list(want['corroborated_by']), name
        assert [[n, t] for n, t in corr['detections']] == want['detections'], name


def test_parity_notch_arrays(parity):
    import fringe_notch as FN
    cases, ref, arr, _meta = parity
    worst = 0.0
    for name in _case_names(cases):
        c = cases[name]
        cfg = c['cfg']
        wl, raw = c['wl'], c['raw']
        wn_full = 1.0 / wl
        sidx = np.argsort(wn_full)
        wn_u_full = np.linspace(wn_full[sidx[0]], wn_full[sidx[-1]], len(wl))
        sig_u_full = np.interp(wn_u_full, wn_full[sidx], raw[sidx])
        nt_probe = c['meta']['nt_probe']

        I_clean, nt_est, sig_filt = FN.defringe_fft_notch(
            wn_u_full, sig_u_full, wl, raw, nt_probe, cfg=cfg)
        assert nt_est == ref['cases'][name]['notch_nt_est'], name
        d1 = _rel(I_clean, arr[name + '__notch_Iclean'])
        d2 = _rel(sig_filt, arr[name + '__notch_filt'])
        assert d1 <= 1e-10, '%s notch I_clean rel=%.3g' % (name, d1)
        assert d2 <= 1e-10, '%s notch filtered rel=%.3g' % (name, d2)

        I2, _, f2 = FN.defringe_fft_notch(
            wn_u_full, sig_u_full, wl, raw, nt_probe, halfwidth_um=2.5,
            notch_centers_nm=c['meta']['notch_centers'],
            notch_halfwidths_um=c['meta']['notch_widths'],
            lowpass=True, lp_cutoff_um=30.0, lp_rolloff_um=2.0, cfg=cfg)
        d3 = _rel(I2, arr[name + '__notch2_Iclean'])
        d4 = _rel(f2, arr[name + '__notch2_filt'])
        assert d3 <= 1e-10, '%s multi-notch rel=%.3g' % (name, d3)
        assert d4 <= 1e-10, '%s multi-notch filtered rel=%.3g' % (name, d4)

        sweep = FN.notch_width_sweep(wn_u_full, sig_u_full, nt_probe,
                                     wl=wl, raw=raw, cfg=cfg)
        d5 = _rel(sweep['residual_power'], arr[name + '__sweep_power'])
        d6 = _rel(sweep['I_clean_wl'], arr[name + '__sweep_clean'])
        assert d5 <= 1e-10, '%s sweep power rel=%.3g' % (name, d5)
        assert d6 <= 1e-10, '%s sweep clean rel=%.3g' % (name, d6)
        worst = max(worst, d1, d2, d3, d4, d5, d6)
    print('worst notch relative deviation: %.3g' % worst)


def test_parity_band_amplitude(parity):
    import fringe_notch as FN
    cases, ref, _arr, _meta = parity
    for name in _case_names(cases):
        c = cases[name]
        cfg = c['cfg']
        want = ref['cases'][name]
        nt_probe = c['meta']['nt_probe']
        got = FN.band_integrated_amplitude(c['wn_u'], c['norm_u'], nt_probe, cfg=cfg)
        assert _rel([got], [want['band_amp']]) <= 1e-10, name
        got6 = FN.band_integrated_amplitude(c['wn_u'], c['norm_u'], nt_probe,
                                            halfwidth_um=6.0, cfg=cfg)
        assert _rel([got6], [want['band_amp_wide']]) <= 1e-10, name
        gnf = FN.band_integrated_amplitude(c['wn_u'], c['norm_u'], nt_probe,
                                           res_floor=False, cfg=cfg)
        assert _rel([gnf], [want['band_amp_nofloor']]) <= 1e-10, name


def _fit_info(c):
    return dict(wn_u=c['wn_u'], norm_u=c['norm_u'],
                nt_est=c['meta']['fit_nt_est'],
                peak_amp=c['meta']['fit_peak_amp'], peak_phase=0.0)


def test_parity_fit_constant_n(parity):
    import fringe_fit as FF
    cases, ref, arr, _meta = parity
    worst = 0.0
    for name in _case_names(cases):
        c = cases[name]
        want = ref['cases'][name]['constant_n']
        got = FF.fit_signal_constant_n(_fit_info(c), label=name, cfg=c['cfg'])
        if isinstance(want, str):
            # source raised (its `assert n_fit >= 1.0`); SPARTA returns None
            assert got is None, '%s: source %s, SPARTA returned a fit' % (name, want)
            continue
        assert got is not None, name
        nt_fit, V_fit, phi0, fringe_win = got
        d = max(_rel([nt_fit], [want[0]]), _rel([V_fit], [want[1]]),
                _rel([phi0], [want[2]]))
        assert d <= 1e-8, '%s constant_n rel=%.3g' % (name, d)
        df = _rel(fringe_win, arr[name + '__cn_fringe'])
        assert df <= 1e-8, '%s constant_n fringe rel=%.3g' % (name, df)
        worst = max(worst, d, df)
    print('worst constant_n relative deviation: %.3g' % worst)


def test_parity_fit_cauchy(parity):
    import fringe_fit as FF
    cases, ref, arr, _meta = parity
    worst = 0.0
    for name in _case_names(cases):
        c = cases[name]
        want = ref['cases'][name]['cauchy']
        got = FF.fit_signal_cauchy(_fit_info(c), label=name, cfg=c['cfg'])
        if isinstance(want, str):
            assert got is None, '%s: source %s, SPARTA returned a fit' % (name, want)
            continue
        assert got is not None, name
        A, B, t, phi0, fw = got[0], got[1], got[2], got[3], got[4]
        rd = FF.dispersion_result_dict([A, B, t, phi0], 1.0 / c['wn_u'],
                                       'cauchy', cfg=c['cfg'])
        d = max(_rel([A], [want[0]]), _rel([t], [want[2]]),
                _rel([phi0], [want[3]]), _rel([rd['n_mean']], [want[4]]),
                _rel([rd['t_um']], [want[5]]), _rel([rd['nt_um']], [want[6]]))
        if want[1] != 0.0 or B != 0.0:
            d = max(d, _rel([B], [want[1]]))
        assert d <= 1e-8, '%s cauchy rel=%.3g' % (name, d)
        df = _rel(fw, arr[name + '__cau_fringe'])
        assert df <= 1e-8, '%s cauchy fringe rel=%.3g' % (name, df)
        worst = max(worst, d, df)
    print('worst cauchy relative deviation: %.3g' % worst)


def test_parity_fit_linear_n(parity):
    import fringe_fit as FF
    cases, ref, _arr, _meta = parity
    worst = 0.0
    for name in _case_names(cases):
        c = cases[name]
        want = ref['cases'][name]['linear_n']
        got = FF.fit_signal_linear_n(_fit_info(c), label=name, cfg=c['cfg'])
        if isinstance(want, str):
            assert got is None, name
            continue
        assert got is not None, name
        t_l, phi0_l, n0_l, n1_l = got[0], got[1], got[2], got[3]
        d = max(_rel([t_l], [want[0]]), _rel([phi0_l], [want[1]]),
                _rel([n0_l], [want[2]]))
        if want[3] != 0.0 or n1_l != 0.0:
            d = max(d, _rel([n1_l], [want[3]]))
        assert d <= 1e-8, '%s linear_n rel=%.3g' % (name, d)
        worst = max(worst, d)
    print('worst linear_n relative deviation: %.3g' % worst)


def test_parity_fine_fit_sigma(parity):
    import fringe_fit as FF
    import fringe_optics as FO
    cases, ref, _arr, _meta = parity
    for name in _case_names(cases):
        c = cases[name]
        want = ref['cases'][name].get('sigma_constant_n')
        if want is None:
            continue
        cn = ref['cases'][name]['constant_n']
        nt_fit, V_fit, phi0 = cn
        wl_ref = 1.0 / float(np.mean(c['wn_u']))
        n_fit = float(FO.fresnel_n_from_V(V_fit, wl_ref, cfg=c['cfg']))
        got = FF.fine_fit_sigma('constant_n',
                                [n_fit, nt_fit / max(n_fit, 1e-6), phi0],
                                c['wn_u'], c['norm_u'], cfg=c['cfg'])
        for k, v in want.items():
            if np.isnan(v):
                assert np.isnan(got[k]), '%s sigma %s' % (name, k)
            else:
                assert _rel([got[k]], [v]) <= 1e-10, '%s sigma %s' % (name, k)


# ---------------------------------------------------------------------------
# Window tiering: run_window_fits <-> _run_all_fitters
# ---------------------------------------------------------------------------

def _rwf_cfg(c, j):
    """The FringeConfig matching one driver job.

    A job may narrow the fit window (the short-window hardening case); the
    driver already writes its own FIT_WL_MIN_NM / FIT_WL_MAX_NM from the
    same two numbers, so both sides read one window.
    """
    cfg = c['cfg']
    if (j.get('wl_min'), j.get('wl_max')) != (c['wl_min'], c['wl_max']):
        cfg = cfg.evolve(fit_wl_min_nm=float(j['wl_min']),
                         fit_wl_max_nm=float(j['wl_max']))
    lamp = _RWF_REGIMES[j['regime']]['lamp_regime']
    return cfg if lamp is None else cfg.for_lamp_regime(lamp)


def _rwf_masks(cfg, wn_u_full):
    """Per-tier boolean masks, exactly as `run_window_fits` builds them."""
    wn_lo_narrow = 1.0 / cfg.fit_wl_max_nm
    wn_hi_narrow = 1.0 / cfg.fit_wl_min_nm
    return dict(
        full=np.ones_like(wn_u_full, dtype=bool),
        wide=(wn_u_full >= cfg.wide_lo) & (wn_u_full <= cfg.wide_hi),
        narrow=(wn_u_full >= wn_lo_narrow) & (wn_u_full <= wn_hi_narrow),
        fine=(wn_u_full >= cfg.fine_wn_lo) & (wn_u_full <= cfg.fine_wn_hi))


def _rwf_fine_centre_inside_narrow(cfg):
    """SPARTA's narrow-tier gate (fringe_fit header divergence 4)."""
    return (1.0 / cfg.fit_wl_max_nm
            <= cfg.fine_center_cm * 1e-7
            <= 1.0 / cfg.fit_wl_min_nm)


def _rwf_run(c, j):
    """SPARTA's answer for one driver job, on the driver's own input arrays."""
    import fringe_fit as FF
    cfg = _rwf_cfg(c, j)
    fi = dict(nt_est=j['nt_est'], peak_amp=j['peak_amp'],
              peak_phase=j['peak_phase'])
    got = FF.run_window_fits(fi, c['rwf']['norm_u_full'], c['rwf']['wn_u_full'],
                             cfg=cfg, label=j['case'],
                             wl_full=np.asarray(c['wl'], float))
    return cfg, got


def _same(a, b):
    """Relative agreement, counting NaN == NaN (his `wl` IS our `wl`)."""
    if np.isnan(a) and np.isnan(b):
        return 0.0
    return _rel([a], [b])


def test_parity_run_window_fits(parity):
    """The tiered fits, value for value, against his real `_run_all_fitters`.

    Pins the four restored drift items at once (a change to any one of them
    moves at least one number here by far more than _RWF_TOL):
      drift #1  n_mean / nt_um average n(lam) over the FULL original wavelength
                grid, in every tier, for cauchy and linear_n.
      drift #5  constant_n Fresnel inversion uses wl_ref = mean(1/wn_u_full),
                one value shared by full/wide/narrow; fine keeps its own.
      drift #6  no extra min(V, 0.9999) clamp on the constant_n path.
      drift #7  constant_n t = nt/max(n, 1e-6), never sent through T_BOUNDS.
    """
    cases, ref, _arr, meta = parity
    jobs = meta['rwf_jobs']
    assert jobs, 'no window-tiering jobs were built'
    compared = 0
    worst = 0.0
    ran = []
    for rkey in sorted(jobs):
        j = jobs[rkey]
        c = cases[j['case']]
        want = ref['run_window_fits'][rkey]
        if isinstance(want, str):
            continue            # see test_parity_run_window_fits_hardening
        cfg, got = _rwf_run(c, j)
        masks = _rwf_masks(cfg, c['rwf']['wn_u_full'])
        fine_in_narrow = _rwf_fine_centre_inside_narrow(cfg)
        ran.append(rkey)

        for model, wins in want.items():
            assert model in got, '%s: SPARTA ran no %s' % (rkey, model)
            for wname, w in wins.items():
                if wname not in got[model]:
                    # Deliberate hardening, never a silent miss:
                    #   drift #10 -- the >=20-point floor now covers full/wide
                    #   header divergence 4 -- narrow is gated on band overlap
                    if wname == 'narrow':
                        assert fine_in_narrow, (
                            '%s %s: narrow missing without the overlap gate'
                            % (rkey, model))
                    else:
                        assert int(masks[wname].sum()) < cfg.fit_min_points, (
                            '%s %s: %s tier missing with %d points'
                            % (rkey, model, wname, int(masks[wname].sum())))
                    continue
                g = got[model][wname]
                for k, v in sorted(w.items()):
                    d = _same(float(g[k]), float(v))
                    assert d <= _RWF_TOL, (
                        '%s %s/%s %s: SPARTA %.17g vs source %.17g (rel=%.3g)'
                        % (rkey, model, wname, k, g[k], v, d))
                    worst = max(worst, d)
                    compared += 1

        # ... and nothing extra: a tier SPARTA ran but he did not can only be
        # narrow, and only because his lamp-date gate closed it (drift #3, the
        # D2 item; SPARTA decides from the band overlap instead).
        for model, wins in got.items():
            for wname in wins:
                if wname in want.get(model, {}):
                    continue
                assert wname == 'narrow' and not fine_in_narrow, (
                    '%s %s: SPARTA produced an unexpected %s tier'
                    % (rkey, model, wname))

    assert ran, 'every tiering job aborted on the source side'
    assert compared >= 60, 'only %d values compared' % compared
    print('run_window_fits parity: %d values over %d jobs (%s), worst rel=%.3g'
          % (compared, len(ran), ', '.join(ran), worst))


def test_parity_run_window_fits_hardening(parity):
    """Where the source aborts the whole channel, SPARTA drops one window.

    Pins drift #4 (the source's `assert n_fit >= 1.0` etc. reach
    compute_channel_fit's bare except and kill the channel) together with
    drift #10 (SPARTA's >=20-point floor now also covers full and wide, so the
    starved tier never reaches a fitter).  Asserted as SPARTA's documented
    behaviour, not as a loosened tolerance.
    """
    cases, ref, _arr, meta = parity
    jobs = meta['rwf_jobs']
    aborted = [k for k in sorted(jobs)
               if isinstance(ref['run_window_fits'][k], str)]
    if not aborted:
        # R15-G added synth_single@short (a 6 nm window) hunting for one and
        # the source completed it too. Skipping loudly beats passing
        # vacuously: a real abort case is v1.5.0 work.
        pytest.skip('no source-side abort among the tiering jobs '
                    '(a 6 nm window did not raise one either)')
    explained = []
    for rkey in aborted:
        j = jobs[rkey]
        c = cases[j['case']]
        cfg, got = _rwf_run(c, j)          # must not raise: that is the point
        assert isinstance(got, dict), rkey
        masks = _rwf_masks(cfg, c['rwf']['wn_u_full'])
        starved = set(w for w, m in masks.items()
                      if int(m.sum()) < cfg.fit_min_points)
        # No tier below the floor may ever reach a fitter (drift #10).
        for model, wins in got.items():
            assert not (starved & set(wins)), (
                '%s %s: fitted a starved tier %s'
                % (rkey, model, sorted(starved & set(wins))))
        if starved:
            explained.append((rkey, sorted(starved),
                              ref['run_window_fits'][rkey].split(':')[1]))
    print('source-side aborts, SPARTA kept going:', aborted)
    print('  ... explained by the per-tier point floor:', explained)


def test_parity_n_mean_uses_the_full_wavelength_grid(parity):
    """Drift #1, isolated -- and its magnitude, printed.

    The reported n_mean must be mean(n(lam)) over the FULL original detector
    grid.  The pre-restore value (the window-restricted uniform resample) is
    recomputed here from the same fitted parameters so the size of the change
    is on the record.
    """
    cases, ref, _arr, meta = parity
    jobs = meta['rwf_jobs']
    rows = []
    for rkey in sorted(jobs):
        j = jobs[rkey]
        c = cases[j['case']]
        if isinstance(ref['run_window_fits'][rkey], str):
            continue
        cfg, got = _rwf_run(c, j)
        masks = _rwf_masks(cfg, c['rwf']['wn_u_full'])
        wl_full = np.asarray(c['wl'], float)
        for model in ('cauchy', 'linear_n'):
            for wname, g in sorted(got.get(model, {}).items()):
                wl_win = 1.0 / c['rwf']['wn_u_full'][masks[wname]]
                if model == 'cauchy':
                    n_full = float(np.mean(g['A'] + g['B'] / wl_full ** 2))
                    n_win = float(np.mean(g['A'] + g['B'] / wl_win ** 2))
                else:
                    n_full = float(np.mean(g['n0'] + g['n1'] / wl_full))
                    n_win = float(np.mean(g['n0'] + g['n1'] / wl_win))
                assert _same(float(g['n_mean']), n_full) <= 1e-12, (
                    '%s %s/%s: n_mean is not the full-grid average'
                    % (rkey, model, wname))
                assert _same(float(g['nt_um']),
                             float(g['n_mean']) * float(g['t_um'])) <= 1e-12,                     '%s %s/%s nt_um' % (rkey, model, wname)
                if np.isfinite(n_full) and n_full != 0.0:
                    rows.append((rkey, model, wname, n_win, n_full,
                                 (n_win - n_full) / n_full))
    assert rows, 'no dispersive fits to compare'
    rows.sort(key=lambda r: -abs(r[5]))
    print('drift #1 magnitude (n_mean window-average -> full-grid average):')
    for r in rows[:8]:
        print('   %-26s %-9s %-6s  %.6f -> %.6f  (%+.3g rel)'
              % (r[0], r[1], r[2], r[3], r[4], r[5]))


def test_parity_constant_n_thickness_is_unclamped(parity):
    """Drift #7 / #5 / #6 on the constant_n path, read off the result dicts.

    t_um is nt/n straight from the fit (no T_BOUNDS clip), nt_um is the fitted
    n*t, and n comes from the shared full-grid wl_ref for full/wide/narrow
    while fine uses its own.
    """
    import fringe_optics as FO
    cases, ref, _arr, meta = parity
    jobs = meta['rwf_jobs']
    seen = 0
    for rkey in sorted(jobs):
        j = jobs[rkey]
        c = cases[j['case']]
        if isinstance(ref['run_window_fits'][rkey], str):
            continue
        cfg, got = _rwf_run(c, j)
        wn = c['rwf']['wn_u_full']
        masks = _rwf_masks(cfg, wn)
        wl_ref_shared = float(np.mean(1.0 / wn))
        for wname, g in sorted(got.get('constant_n', {}).items()):
            wl_ref = (float(np.mean(1.0 / wn[masks['fine']]))
                      if wname == 'fine' else wl_ref_shared)
            # drift #6: raw V, no min(V, 0.9999) on this path
            n_ref = float(FO.fresnel_n_from_V(float(g['V']), wl_ref, cfg=cfg))
            assert _same(float(g['n_mean']), n_ref) <= 1e-12, \
                '%s constant_n/%s n_mean' % (rkey, wname)
            # drift #7: t is nt/n, never clipped into [t_min_nm, t_max_nm]
            t_nm = float(g['nt_um']) * 1000.0 / max(n_ref, 1e-6)
            assert _same(float(g['t_um']) * 1000.0, t_nm) <= 1e-12, \
                '%s constant_n/%s t_um' % (rkey, wname)
            seen += 1
    assert seen >= 3, 'only %d constant_n tiers checked' % seen


def test_parity_run_window_fits_covers_every_tier(parity):
    """The harness must actually exercise full, wide, fine AND narrow."""
    cases, ref, _arr, meta = parity
    tiers = set()
    for rkey, j in sorted(meta['rwf_jobs'].items()):
        if isinstance(ref['run_window_fits'][rkey], str):
            continue
        _cfg, got = _rwf_run(cases[j['case']], j)
        for wins in got.values():
            tiers |= set(wins)
    assert {'full', 'wide', 'fine'} <= tiers, sorted(tiers)
    if any(k.endswith('@post') for k in meta['rwf_jobs']):
        assert 'narrow' in tiers, (
            'the post-Nov-2025 lamp job must exercise the narrow tier; got %s'
            % sorted(tiers))


def test_parity_case_coverage(parity):
    """The harness must actually cover real spectra, not just synthetics."""
    cases, _ref, _arr, _meta = parity
    real = [n for n in cases if n.startswith('y04_')]
    assert len(real) >= 6, 'expected >= 6 real Y04_Arch29 spectra, got %d' % len(real)
    assert any(n.startswith('synth_') for n in cases)
    if os.path.isdir(TA_DIR):
        assert 'ta_chewy_ch29' in cases
