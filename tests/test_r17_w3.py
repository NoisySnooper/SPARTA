"""R17-W3: the workbench's cold start, its index boxes, and the surfaces
his window has that ours did not.

The parity audit found five things wrong with the first frame a reader sees:

  * COLD START.  His `_align_glyphs_to_tallest_and_lock` (defringe_dac
    12620-12660, called from `_load_into_state_body` when a load has no seed)
    puts both Sample role glyphs on the Sample panel's tallest FFT peak and
    the medium etalon on the Background's, solves from those three paths, and
    writes n sample / t / d2 back before anything is drawn.  Ours parked the
    glyphs on the shipped stack's guess and left the solved column empty, so
    on Y03_ch29 at 3.71 GPa his window opened on 63.33 / 54.89 um and n_s
    1.385, t_s 45.744 where ours opened on 26.40 / 33.61 and dashes;
  * n DIAMOND.  His is a Spinbox that every load rewrites from that
    spectrum's own pressure (2.4030 at 3.71 GPa); ours was a static label
    stuck on the ambient 2.4168, which moves every solved n_s and t_s;
  * THE INDEX ROWS.  His n medium, n sample and n layer2 are spinboxes, so
    "fine steps" reaches them; ours were entries, and the n layer2 row was
    missing outright;
  * TWO MISSING SURFACES.  View > Refractive index models (his
    `_show_model_info`, 15104) and Export results CSV in the Results window
    (his `_export_results`, 11110, eighteen columns);
  * THE POP-OUT.  Its cutoff spinbox reached 400 where his stops at 200, its
    repaint reset a SHORTER artist registry than the workbench now fills, and
    its list windows were destroyed on close rather than withdrawn.

The dict- and function-level checks need no Tk.  The panel half runs against
the suite's ONE shared App (tests/conftest.py).
"""
import csv
import os

import numpy as np
import pytest

import fringe_optics
import fringe_panel
import fringe_popout
from conftest import gui, make_result, realized, shared_app, walk

USES_APP = True

# His numbers on Y03_ch29 at 3.71 GPa, read off his own window by the R17-C
# parity pass: the two peaks the glyphs land on and the solve they give.
HIS_SAMPLE_UM = 63.33
HIS_MEDIUM_UM = 54.89
HIS_N_S = 1.385
HIS_T_S = 45.744
HIS_N_DIAMOND = 2.4030
HIS_P_GPA = 3.71


# ---------------------------------------------------------------------------
# synthetic spectra: one dominant fringe per channel, at a known n*t
# ---------------------------------------------------------------------------
def _one_fringe(nt_um, amp=0.08, n=2400, lo=560.0, hi=860.0):
    """Counts carrying a single strong fringe of optical path `nt_um`."""
    wl = np.linspace(lo, hi, n)
    base = 1000.0 * (1.0 + 0.30 * (wl - lo) / (hi - lo))
    return wl, base * (1.0 + amp * np.cos(4.0 * np.pi * nt_um * 1000.0 / wl))


def _no_fringe(n=2400, lo=560.0, hi=860.0, seed=7):
    """Counts with no fringe in them: a lamp envelope and a little noise."""
    wl = np.linspace(lo, hi, n)
    base = 1000.0 * (1.0 + 0.30 * (wl - lo) / (hi - lo))
    rng = np.random.RandomState(seed)
    return wl, base * (1.0 + 0.002 * rng.randn(n))


def _flat_rec(label="0 GPa", pval=0.0):
    """A record neither channel has a fringe in."""
    wl, samp = _no_fringe()
    _wl, bg = _no_fringe(seed=3)
    rng = np.random.RandomState(11)
    return make_result(label, pval, wl=wl, samp=samp, bg=bg,
                       dark=5.0 + 0.01 * rng.randn(wl.size))


def _two_peak_rec(label="3.71 GPa", pval=HIS_P_GPA,
                  s_um=HIS_SAMPLE_UM, b_um=HIS_MEDIUM_UM):
    """A record whose Sample panel's tallest peak is `s_um` and whose
    Background's is `b_um` -- his 3.71 GPa point, in miniature."""
    wl, samp = _one_fringe(s_um)
    _wl, bg = _one_fringe(b_um)
    return make_result(label, pval, wl=wl, samp=samp, bg=bg,
                       dark=np.full(wl.size, 5.0))


# ---------------------------------------------------------------------------
# fixtures
# ---------------------------------------------------------------------------
@pytest.fixture(scope="module")
def a():
    return shared_app()


@pytest.fixture
def fw(a):
    """The workbench on a clean slate, with the Stack card put back after.

    Every box this file writes is snapshotted, because the Stack is ONE set
    of controls shared by the whole series and a leaked value would decide
    the next test's solve.
    """
    w = a._fringe
    w.build()
    keep_dicts = (dict(w._chan), dict(w._trace), dict(w._disk),
                  dict(w._inputs), dict(w._live_inputs))
    keep = (w._label, w._local, list(a.results), list(w._series))
    vars_ = {"ns": w.ns_v, "t": w.t_v, "d1": w.d1_v, "d2": w.d2_v,
             "nd": w.nd_v, "nl2": w.nl2_v, "nmed": w.medium_n_v,
             "med": w.medium_v, "l2": w.layer2_v, "dia": w.diamond_v,
             "dp": w.dp_v, "hw": w.hw_v, "total": w.total_v}
    keep_v = {k: v.get() for k, v in vars_.items()}
    keep_b = {"l2on": bool(w.layer2_on_v.get()),
              "lock": bool(w.lock_v.get()),
              "fine": bool(w.fine_v.get())}
    keep_lp = {c: (bool(w.lp_on_v[c].get()), w.lp_v[c].get())
               for c in fringe_panel.CHANNELS}
    for d in (w._chan, w._trace, w._disk, w._inputs, w._live_inputs,
              w._cache):
        d.clear()
    w._series = []
    w._dk_cache = {}
    w._dk_sig = None
    w._seed_said.clear()
    a.notch_cache.clear()
    yield w
    _quiet(w)
    for d, src in zip((w._chan, w._trace, w._disk, w._inputs,
                       w._live_inputs), keep_dicts):
        d.clear()
        d.update(src)
    w._label, w._local, a.results, w._series = (keep[0], keep[1],
                                                keep[2], list(keep[3]))
    w._suspend = True
    try:
        for k, v in vars_.items():
            v.set(keep_v[k])
        w.layer2_on_v.set(keep_b["l2on"])
        w.lock_v.set(keep_b["lock"])
        w.fine_v.set(keep_b["fine"])
        for c, (on, cut) in keep_lp.items():
            w.lp_on_v[c].set(on)
            w.lp_v[c].set(cut)
    finally:
        w._suspend = False
    w._sync_l2_rows()
    w._cache.clear()
    w._dk_cache = {}
    w._dk_sig = None
    a.notch_cache.clear()


def _quiet(fw):
    """Drop any armed drag and the debounced redraw a test left behind."""
    fw._drag = None
    if fw._after is not None:
        try:
            fw.app.root.after_cancel(fw._after)
        except Exception:
            pass
        fw._after = None


def _load(a, fw, recs, label=None):
    """Make `recs` the loaded series, without touching the disk."""
    a.results = list(recs)
    fw._local = None
    fw._dk_cache = {}
    fw._dk_sig = None
    fw._cache.clear()
    fw._label = label if label is not None else recs[0]["label"]


def _plain_stack(fw, pressure=None):
    """His shipped stack: a manual medium at 1.2, no Layer 2, unlocked.

    Set under the suspend guard, because these writes are the test's setup
    and not an edit the workbench should redraw for.
    """
    fw._suspend = True
    try:
        fw.medium_v.set(fringe_panel.fringe_materials.MEDIUM_MANUAL)
        fw.medium_n_v.set("1.2")
        fw.layer2_on_v.set(False)
        fw.lock_v.set(False)
        fw.ns_v.set("1.5")
        fw.t_v.set("20")
        fw.d1_v.set("0")
        fw.d2_v.set("0")
        fw.dp_v.set("" if pressure is None else "%g" % pressure)
    finally:
        fw._suspend = False
    fw._sync_medium_row()


def _spins_named(root, var):
    """Every ttk.Spinbox in `root` bound to `var`."""
    name = str(var)
    out = []
    for w in walk(root):
        try:
            if w.winfo_class() != "TSpinbox":
                continue
            if str(w.cget("textvariable")) == name:
                out.append(w)
        except Exception:
            continue
    return out


# ===========================================================================
# 1. the shipped anvil model  (D3)
# ===========================================================================
def test_the_shipped_anvil_model_reproduces_his_n_diamond():
    """His load recomputes n (anvils) from the single-oscillator model with
    the Eremets pressure shift.  In SPARTA that model is keyed 'eremets';
    'oscillator' is the same oscillator held at ambient, and it cannot
    reproduce his number at pressure."""
    assert fringe_panel.SETTINGS_DEFAULTS["fr_diamond_model"] == "eremets"
    at_p = float(fringe_optics.n_diamond(700.0, model="eremets",
                                         pressure_gpa=HIS_P_GPA))
    assert at_p == pytest.approx(HIS_N_DIAMOND, abs=5e-5)
    ambient = float(fringe_optics.n_diamond(700.0, model="oscillator",
                                            pressure_gpa=HIS_P_GPA))
    assert ambient != pytest.approx(HIS_N_DIAMOND, abs=5e-4)


def test_a_settings_file_that_carries_the_model_keeps_it():
    """The defaults are DEFAULTS: app.py folds them in with setdefault, so a
    reader who picked Constant keeps Constant across the upgrade."""
    settings = {"fr_diamond_model": "constant"}
    for k, v in fringe_panel.SETTINGS_DEFAULTS.items():
        settings.setdefault(k, v)
    assert settings["fr_diamond_model"] == "constant"
    assert settings["fr_n_layer2"] == 1.0


def test_the_layer2_index_has_a_shipped_default():
    assert fringe_panel.SETTINGS_DEFAULTS["fr_n_layer2"] == 1.0
    assert fringe_panel.IDX_STEP == 0.1


# ===========================================================================
# 2. cold start: his align-and-lock
# ===========================================================================
@gui
def test_a_cold_load_puts_the_glyphs_on_the_tallest_peak_of_each_panel(
        a, fw):
    """His 12632-12645: both Sample roles on the Sample panel's tallest, the
    medium etalon on the Background's, and the two Sample roles coincident
    until one is dragged off the other.

    R18-F/G6 moved where "the tallest peak" is READ: the align branch
    of _seed_roles now runs _autosnap_roles, so a cold load leaves the
    glyphs on the GAUSSIAN-REFINED centre of that peak (his cadence,
    his 63.333 / 54.893) rather than on the FFT bin the peak fell in.
    That is a tighter place, not a looser one: the refined centre sits
    within a bin of the tallest bin and within 0.05 um of the fringe
    that was synthesised, so this asserts both.
    """
    _load(a, fw, [_two_peak_rec()])
    _plain_stack(fw, pressure=HIS_P_GPA)
    fw._request_redraw(now=True)

    s_top = fw._tallest_peak_um("Sample")
    b_top = fw._tallest_peak_um("Background")
    assert s_top is not None and b_top is not None
    roles = fw._tr()["roles"]
    # both Sample roles still coincident, and on the Sample panel
    assert roles["sample"]["nt_um"] == \
        pytest.approx(roles["sampledia"]["nt_um"])
    # each glyph is the refined centre of its panel's tallest peak
    assert roles["sample"]["nt_um"] == pytest.approx(s_top, abs=0.5)
    assert roles["mediumdia"]["nt_um"] == pytest.approx(b_top, abs=0.5)
    # and the refinement lands on the fringe that was synthesised --
    # his 63.333 / 54.893, not the bin the peak fell in
    assert roles["sample"]["nt_um"] == \
        pytest.approx(HIS_SAMPLE_UM, abs=0.05)
    assert roles["mediumdia"]["nt_um"] == \
        pytest.approx(HIS_MEDIUM_UM, abs=0.05)
    # the peaks his window landed on, to the FFT's own grid
    assert s_top == pytest.approx(HIS_SAMPLE_UM, abs=1.5)
    assert b_top == pytest.approx(HIS_MEDIUM_UM, abs=1.5)
    _quiet(fw)


@gui
def test_a_cold_load_writes_the_solve_into_the_boxes(a, fw):
    """His helper writes n_sample / t_um / d2_um inside the loading guard, so
    the first frame draws the stems on the glyphs instead of on t = 20."""
    _load(a, fw, [_two_peak_rec()])
    _plain_stack(fw, pressure=HIS_P_GPA)
    fw._request_redraw(now=True)

    sol = fw._tr()["solved"]
    assert sol is not None
    assert float(fw.ns_v.get()) == pytest.approx(sol["n_s"], abs=1e-3)
    assert float(fw.t_v.get()) == pytest.approx(sol["t_s"], abs=1e-2)
    assert float(fw.d2_v.get()) == pytest.approx(sol["t_layer2"], abs=1e-2)
    # the solve is his: A = C puts the whole gap in the sample, and the
    # medium etalon divided by n_medium is that gap
    a_path = fw._tr()["roles"]["sample"]["nt_um"]
    iii = fw._tr()["roles"]["mediumdia"]["nt_um"]
    assert sol["t_s"] == pytest.approx(iii / 1.2, rel=1e-6)
    assert sol["n_s"] == pytest.approx(a_path / sol["t_s"], rel=1e-6)
    assert sol["n_s"] == pytest.approx(HIS_N_S, abs=0.08)
    assert sol["t_s"] == pytest.approx(HIS_T_S, abs=2.0)
    _quiet(fw)


@gui
def test_the_cold_start_leaves_the_solved_column_filled(a, fw):
    """The readout his window opens on: n_s, t_s and L, not dashes."""
    _load(a, fw, [_two_peak_rec()])
    _plain_stack(fw, pressure=HIS_P_GPA)
    fw._request_redraw(now=True)
    for key in ("n_s", "t_s", "L"):
        txt = fw._sol_lbl[key].cget("text")
        assert txt and txt != "–"
    _quiet(fw)


@gui
def test_a_point_with_its_own_inputs_keeps_them(a, fw):
    """Seed precedence, his 13081: a point that HAS inputs is not a cold
    start, so the glyphs come from the stack model, not from the tallest
    peak, and the boxes are not rewritten."""
    rec = _two_peak_rec()
    _load(a, fw, [rec])
    _plain_stack(fw, pressure=HIS_P_GPA)
    dk = fw._dkey()
    assert dk is not None
    fw._inputs[dk] = {"nums": {"n_sample": "1.5", "t_um": "20",
                               "d1_um": "0", "d2_um": "0"}}
    assert fw._has_seed() is True

    fw._request_redraw(now=True)
    roles = fw._tr()["roles"]
    # the model path may not find all three, but it must not have written
    # the tallest-peak solve into the boxes
    assert float(fw.t_v.get()) == pytest.approx(20.0)
    assert float(fw.ns_v.get()) == pytest.approx(1.5)
    if roles["sample"] and roles["sampledia"]:
        assert not (roles["sample"]["nt_um"]
                    == pytest.approx(roles["sampledia"]["nt_um"])
                    == pytest.approx(fw._tallest_peak_um("Sample")))
    _quiet(fw)


@gui
def test_the_cold_start_is_not_unsaved_work(a, fw):
    """The align solves as soon as it parks the glyphs.  That solve is part
    of the opening guess, so stepping to the next trace must not raise the
    leave guard on a spectrum nobody has touched."""
    _load(a, fw, [_two_peak_rec()])
    _plain_stack(fw, pressure=HIS_P_GPA)
    fw._request_redraw(now=True)
    assert fw._tr()["solved"] is not None
    assert fw._dirty_items() == []
    # one drag makes it the reader's, and then it counts
    fw._tr()["roles"]["sample"] = {"nt_um": 40.0, "auto": False}
    assert fw._dirty_items() != []
    _quiet(fw)


@gui
def test_the_re_detect_action_never_jumps_to_the_tallest_peak(a, fw):
    """`_fit_peaks_mode` is the stack model's own workflow: it re-seeds on
    the model stems (his _redetect_and_apply), so the align is not offered
    to it."""
    _load(a, fw, [_two_peak_rec()])
    _plain_stack(fw, pressure=HIS_P_GPA)
    fw._request_redraw(now=True)
    tr = fw._tr()
    for role in fringe_panel.ROLES:
        tr["roles"][role] = None
    tr["seeded"] = False
    p = fw._stack_params(fw._record())
    wrote = fw._seed_roles(p, fw._x_upper(p), allow_align=False)
    assert wrote is False
    _quiet(fw)


@gui
def test_a_channel_with_no_peaks_leaves_the_boxes_alone(a, fw):
    """Deviation from his, deliberate: his helper restores its own defaults
    when nothing can be solved.  Ours leaves the boxes, because in SPARTA
    they are one series-wide set and clearing them would take the reader's
    numbers with them.

    A fringe-free channel still HAS noise peaks -- his `_tallest_peak_um`
    reads `peaks_sorted`, not the detection -- so this drives the branch by
    taking the peaks away."""
    _load(a, fw, [_two_peak_rec()])
    _plain_stack(fw)
    fw._suspend = True
    try:
        fw.t_v.set("33")
        fw.ns_v.set("1.77")
    finally:
        fw._suspend = False
    fw._tallest_peak_um = lambda chan: None
    try:
        # None, not False: nothing to align to hands the trace back to the
        # stack model's own guess rather than freezing it on no glyphs
        assert fw._align_to_tallest() is None
    finally:
        del fw._tallest_peak_um
    assert float(fw.t_v.get()) == pytest.approx(33.0)
    assert float(fw.ns_v.get()) == pytest.approx(1.77)
    _quiet(fw)


# ===========================================================================
# 3. the index boxes
# ===========================================================================
@gui
def test_every_index_row_is_a_spinbox_over_his_range(a, fw):
    """His four index rows are Spinboxes 0 to 100000, stepping 0.1."""
    for var in (fw.nd_v, fw.medium_n_v, fw.ns_v, fw.nl2_v):
        boxes = _spins_named(fw.app.root, var)
        assert boxes, "no spinbox bound to %s" % var
        sp = boxes[0]
        assert float(sp.cget("from")) == pytest.approx(0.0)
        assert float(sp.cget("to")) == pytest.approx(100000.0)
        assert getattr(sp, "_fr_step", None) == pytest.approx(
            fringe_panel.IDX_STEP)


@gui
def test_fine_steps_reaches_the_index_boxes_and_the_thicknesses(a, fw):
    """His fine-steps switch divides EVERY box's own pace by ten: 0.01 on an
    index, 0.1 on a thickness."""
    was = bool(fw.fine_v.get())
    try:
        fw.fine_v.set(False)
        fw._sync_steps()
        assert fw._step(fringe_panel.IDX_STEP) == pytest.approx(0.1)
        assert fw._step() == pytest.approx(1.0)
        nd = _spins_named(fw.app.root, fw.nd_v)[0]
        t = _spins_named(fw.app.root, fw.t_v)[0]
        assert float(nd.cget("increment")) == pytest.approx(0.1)
        assert float(t.cget("increment")) == pytest.approx(1.0)
        fw.fine_v.set(True)
        fw._sync_steps()
        assert float(nd.cget("increment")) == pytest.approx(0.01)
        assert float(t.cget("increment")) == pytest.approx(0.1)
    finally:
        fw.fine_v.set(was)
        fw._sync_steps()


@gui
def test_the_layer2_index_row_is_hidden_until_the_box_is_ticked(a, fw):
    """His n layer2 row is not there at all until Layer 2 is on, and it
    comes back in its OWN place rather than at the foot of the card."""
    rows = [r for r, _pack in fw._l2_rows]
    assert rows, "no Layer 2 row was registered"
    fw.layer2_on_v.set(False)
    fw._sync_l2_rows()
    assert all(not r.winfo_manager() for r in rows)
    fw.layer2_on_v.set(True)
    fw._sync_l2_rows()
    row = rows[0]
    assert all(r.winfo_manager() == "pack" for r in rows)
    sibs = list(row.master.pack_slaves())
    assert row in sibs
    # it sits above the n sample row it was built before, not at the end
    assert sibs.index(row) < len(sibs) - 1
    fw.layer2_on_v.set(False)
    fw._sync_l2_rows()


@gui
def test_the_layer2_index_reaches_the_stack_model(a, fw):
    """With Layer 2 on, the box is what n_layer2 is read from."""
    _load(a, fw, [_two_peak_rec()])
    _plain_stack(fw, pressure=HIS_P_GPA)
    fw._suspend = True
    try:
        fw.layer2_on_v.set(True)
        fw.nl2_v.set("1.7")
    finally:
        fw._suspend = False
    p = fw._stack_params(fw._record())
    assert p["n_layer2"] == pytest.approx(1.7)
    fw._suspend = True
    try:
        fw.layer2_on_v.set(False)
    finally:
        fw._suspend = False
    p = fw._stack_params(fw._record())
    assert p["n_layer2"] == pytest.approx(p["n_medium"])
    _quiet(fw)


# ===========================================================================
# 4. n diamond from the trace's own pressure
# ===========================================================================
@gui
def test_every_load_reads_n_diamond_from_that_points_pressure(a, fw):
    """His `_load_into_state_body` (13091-13097): n (anvils) is a function of
    THIS point's pressure, so it is recomputed on every load."""
    _load(a, fw, [_two_peak_rec()])
    _plain_stack(fw)
    fw._load_wl_override()
    assert float(fw.nd_v.get()) == pytest.approx(HIS_N_DIAMOND, abs=5e-5)
    p = fw._stack_params(fw._record())
    assert p["n_diamond"] == pytest.approx(HIS_N_DIAMOND, abs=5e-5)
    _quiet(fw)


@gui
def test_a_second_pressure_moves_the_anvil_index(a, fw):
    """Two points, two indices: the box follows the spectrum, not the
    series."""
    lo = _two_peak_rec("3.71 GPa", HIS_P_GPA)
    hi = _two_peak_rec("26.2 GPa", 26.2)
    _load(a, fw, [lo, hi], label="3.71 GPa")
    _plain_stack(fw)
    fw._load_wl_override()
    at_lo = float(fw.nd_v.get())
    fw._label = "26.2 GPa"
    fw._load_wl_override()
    at_hi = float(fw.nd_v.get())
    assert at_hi != pytest.approx(at_lo, abs=1e-4)
    assert at_hi == pytest.approx(
        float(fringe_optics.n_diamond(700.0, model="eremets",
                                      pressure_gpa=26.2)), abs=5e-5)
    _quiet(fw)


@gui
def test_ambient_n_puts_the_anvil_back_on_the_constant(a, fw):
    """His Ambient n button.  Our anvil index comes from the Anvil model, and
    Constant 2.4168 IS that constant, so the button picks that model and the
    box takes its value."""
    _load(a, fw, [_two_peak_rec()])
    _plain_stack(fw)
    fw._load_wl_override()
    assert float(fw.nd_v.get()) != pytest.approx(2.4168, abs=1e-4)
    fw._ambient_n()
    assert fw.diamond_v.get() == "constant"
    assert float(fw.nd_v.get()) == pytest.approx(
        fringe_optics.N_DIAMOND_CONST, abs=1e-4)
    assert fw._stack_params(fw._record())["n_diamond"] == pytest.approx(
        fringe_optics.N_DIAMOND_CONST, abs=1e-4)
    _quiet(fw)


@gui
def test_a_typed_anvil_index_is_what_the_stack_model_uses(a, fw):
    """The cell is a BOX now, his way: what stands in it is what the stems
    are built from, until the next load or model pick rewrites it."""
    _load(a, fw, [_two_peak_rec()])
    _plain_stack(fw)
    fw._suspend = True
    try:
        fw.nd_v.set("2.6000")
    finally:
        fw._suspend = False
    assert fw._stack_params(fw._record())["n_diamond"] == pytest.approx(2.6)
    _quiet(fw)


@gui
def test_the_anvil_combo_rewrites_the_box(a, fw):
    _load(a, fw, [_two_peak_rec()])
    _plain_stack(fw, pressure=HIS_P_GPA)
    fw.diamond_v.set("cauchy")
    assert float(fw.nd_v.get()) == pytest.approx(
        float(fringe_optics.n_diamond(700.0, model="cauchy")), abs=1e-4)
    fw.diamond_v.set("eremets")
    assert float(fw.nd_v.get()) == pytest.approx(HIS_N_DIAMOND, abs=5e-5)
    _quiet(fw)


@gui
def test_calc_n_writes_both_model_owned_boxes(a, fw):
    """His calc n reads every modelled index at the P box's pressure."""
    _load(a, fw, [_two_peak_rec()])
    _plain_stack(fw)
    fw._suspend = True
    try:
        fw.dp_v.set("20")
    finally:
        fw._suspend = False
    fw._calc_n()
    assert float(fw.nd_v.get()) == pytest.approx(
        float(fringe_optics.n_diamond(700.0, model="eremets",
                                      pressure_gpa=20.0)), abs=5e-5)
    _quiet(fw)


# ===========================================================================
# 5. the no-fringe overlays are the Sample panel's  (his _draw_row0)
# ===========================================================================
def _labels_on(ax):
    return set(str(ln.get_label()) for ln in ax.get_lines()) | set(
        str(c.get_label()) for c in ax.collections)


@gui
def test_the_noise_floor_and_the_dark_difference_are_the_samples(a, fw):
    """His 7554 and 7560 gate both on label == 'Sample'.  The Background
    keeps raw and dark."""
    _load(a, fw, [_flat_rec()])
    _plain_stack(fw)
    fw._request_redraw(now=True)

    s_lab = _labels_on(fw._maxes["Sample"])
    b_lab = _labels_on(fw._maxes["Background"])
    assert "raw" in s_lab and "raw" in b_lab
    assert "dark" in s_lab and "dark" in b_lab
    assert "noise floor" in s_lab
    assert "noise floor" not in b_lab
    assert any("dark)" in s for s in s_lab)
    assert not any("dark)" in s for s in b_lab)
    _quiet(fw)


# ===========================================================================
# 6. the notch list's default half-width  (D4)
# ===========================================================================
@gui
def test_the_default_half_width_box_carries_his_range(a, fw):
    """0.5 to 20 um, the same range the per-centre rows use."""
    _load(a, fw, [_two_peak_rec()])
    win = fw._open_notch_list()
    try:
        boxes = _spins_named(win, fw.hw_v)
        assert boxes
        sp = boxes[0]
        assert float(sp.cget("from")) == pytest.approx(
            fringe_panel.NOTCH_HW_MIN_UM)
        assert float(sp.cget("to")) == pytest.approx(
            fringe_panel.NOTCH_HW_MAX_UM)
    finally:
        win.destroy()
        fw._notch_win = None
        fw._notch_rows = None
    _quiet(fw)


# ===========================================================================
# 7. the list windows withdraw  (fix 16)
# ===========================================================================
@gui
def test_a_list_window_is_withdrawn_not_destroyed(a, fw):
    """Scroll position and expansion survive a close, and the second open is
    the SAME window raised.

    Inside `realized()`, because `wm state` is only readable with a MAPPED
    root.  The list window is a transient of the root (fringe_panel:4623),
    and Tk keeps a transient of a withdrawn master withdrawn whatever it is
    asked: measured, `deiconify()` on a transient of a withdrawn root
    reports "withdrawn" before and after, while the same call on a transient
    of a mapped root reports "normal".  The suite's root stays withdrawn for
    the whole session (conftest:66-68), so without the block BOTH state
    assertions here read the master's state, not this window's.
    """
    _load(a, fw, [_two_peak_rec()])
    win = fw._open_notch_list()
    try:
        with realized():
            fw._dismiss(win)
            assert win.winfo_exists()
            assert win.state() == "withdrawn"
            again = fw._open_notch_list()
            assert again is win
            assert win.state() != "withdrawn"
    finally:
        win.destroy()
        fw._notch_win = None
        fw._notch_rows = None
    _quiet(fw)


@gui
def test_escape_and_the_x_button_do_the_same_thing(a, fw):
    """DESIGN_RULES rule 2: where the X does more than destroy, Escape must
    call the SAME function."""
    _load(a, fw, [_two_peak_rec()])
    win = fw._open_yaxis()
    try:
        assert win.protocol("WM_DELETE_WINDOW")
        assert win.bind("<Escape>")
        fw._dismiss(win)
        assert win.winfo_exists() and win.state() == "withdrawn"
    finally:
        win.destroy()
        fw._yaxis_win = None


# ===========================================================================
# 8. View > Refractive index models  (his _show_model_info)
# ===========================================================================
def test_the_model_tabs_name_materials_the_docs_carry():
    """The window is built from fringe_materials.MODEL_DOCS, so a tab can
    never describe a model the code does not have."""
    import fringe_materials
    keys = [k for k, _label in fringe_panel.MODEL_DOC_TABS]
    assert keys == ["diamond", "Ar", "ArChen", "ArChenD"]
    for key in keys:
        assert key in fringe_materials.MODEL_DOCS
        body = fringe_materials.format_model_doc(key, full=True)
        assert body and "References" in body


@gui
def test_the_models_window_builds_one_tab_per_material(a, fw):
    win = fw._open_models()
    try:
        assert win.title() == "Refractive index models"
        assert len(fw._models_tabs) == len(fringe_panel.MODEL_DOC_TABS)
        assert list(fw._models_nb.tabs())
        # it closes his way, like every other list window
        fw._dismiss(win)
        assert win.winfo_exists() and win.state() == "withdrawn"
        # ...and a named tab is raised on the way back up
        again = fw._open_models("ArChen")
        assert again is win
        assert str(fw._models_nb.select()) == str(fw._models_tabs["ArChen"])
    finally:
        win.destroy()
        fw._models_win = None
        fw._models_tabs = {}


# ===========================================================================
# 9. Export results CSV  (his _export_results, 11110)
# ===========================================================================
HIS_RESULT_COLS = ["series", "pressure_gpa", "label", "stem", "sample_um",
                   "sampledia_um", "mediumdia_um", "n_layer2", "n_medium",
                   "n_s", "t_s_um", "t_layer2_um", "L_um", "nl2tl2_um",
                   "layer2_model", "medium_model", "layer2", "series_id"]


@gui
def test_the_results_csv_carries_his_columns_in_his_order(a, fw, tmp_path):
    _load(a, fw, [_two_peak_rec()])
    _plain_stack(fw, pressure=HIS_P_GPA)
    fw._series = [{"label": "3.71 GPa", "stem": "y03_3p71",
                   "pressure": HIS_P_GPA, "branch": "C",
                   "A": HIS_SAMPLE_UM, "C": HIS_SAMPLE_UM,
                   "iii": HIS_MEDIUM_UM, "medium": "Other",
                   "layer2": False, "layer2_name": "Other",
                   "n_medium": 1.2, "n_layer2": 1.2, "diamond": "eremets",
                   "solved": {}}]
    fw._series_folder = lambda: str(tmp_path)
    fw._input_folder = lambda: str(tmp_path)
    try:
        fw._res_export()
    finally:
        del fw._series_folder
        del fw._input_folder

    made = [f for f in os.listdir(str(tmp_path))
            if f.startswith("fft_results_series_") and f.endswith(".csv")]
    assert len(made) == 1
    with open(os.path.join(str(tmp_path), made[0]), encoding="utf-8") as f:
        rows = list(csv.DictReader(f))
        f.seek(0)
        head = f.readline().strip().split(",")
    assert head == HIS_RESULT_COLS
    assert len(rows) == 1
    row = rows[0]
    assert row["label"] == "3.71 GPa"
    assert row["stem"] == "y03_3p71"
    assert float(row["sample_um"]) == pytest.approx(HIS_SAMPLE_UM)
    assert float(row["mediumdia_um"]) == pytest.approx(HIS_MEDIUM_UM)
    assert float(row["n_medium"]) == pytest.approx(1.2)
    # the solve is re-run from the recorded paths, and it conserves A
    assert float(row["t_s_um"]) == pytest.approx(HIS_MEDIUM_UM / 1.2,
                                                 rel=1e-9)
    assert float(row["n_s"]) == pytest.approx(
        HIS_SAMPLE_UM / (HIS_MEDIUM_UM / 1.2), rel=1e-9)
    assert float(row["nl2tl2_um"]) == pytest.approx(
        1.2 * float(row["t_layer2_um"]), rel=1e-9)
    assert row["medium_model"] == "Other"
    assert row["layer2"] == "False"
    _quiet(fw)


@gui
def test_an_empty_series_says_so_instead_of_writing_a_file(a, fw, tmp_path):
    _load(a, fw, [_two_peak_rec()])
    fw._series = []
    fw._series_folder = lambda: str(tmp_path)
    try:
        fw._res_export()
    finally:
        del fw._series_folder
    assert os.listdir(str(tmp_path)) == []
    _quiet(fw)


# ===========================================================================
# 10. the pop-out
# ===========================================================================
def test_the_artist_registry_has_one_definition():
    """Every repaint resets the SAME set of keys.  The pop-out used to reset
    three of them, so a gesture on that path reached for a key that was not
    there (`guides`, in `_draw_roles`)."""
    blank = fringe_panel.FringeWorkbench._blank_artists()
    assert set(blank) == {"roles", "lp", "lpshade", "lptext", "hover",
                          "guides", "removed"}
    assert all(v == {} for v in blank.values())
    names = fringe_popout.MatthewWindow._paint.__code__.co_names
    assert "_blank_artists" in names
    assert "_seed_roles" in names and "_stack_params" in names


def test_the_popout_cutoff_box_takes_his_range_from_one_place():
    """Fix 13: the spinbox and the drag clamp share LP_MIN_UM / LP_MAX_UM,
    so a dragged edge can never leave a value the box cannot hold."""
    assert (fringe_panel.LP_MIN_UM, fringe_panel.LP_MAX_UM) == (1.0, 200.0)
    names = fringe_popout.MatthewWindow._card_removal.__code__.co_names
    assert "LP_MIN_UM" in names and "LP_MAX_UM" in names
    consts = fringe_popout.MatthewWindow._card_removal.__code__.co_consts
    assert 400.0 not in [c for c in consts if isinstance(c, float)]


def test_the_popout_index_rows_are_the_same_boxes_as_the_tab():
    """One set of variables, two windows: the pop-out builds spinboxes over
    wb.nd_v / wb.nl2_v / wb.ns_v and registers its Layer 2 row with the
    workbench's own gate."""
    names = fringe_popout.MatthewWindow._card_indices.__code__.co_names
    for want in ("nd_v", "nl2_v", "ns_v", "medium_n_v", "IDX_STEP",
                 "_l2_row"):
        assert want in names, want
    assert "nl2" in fringe_popout.TIPS


def test_the_popout_seals_its_layer2_row():
    names = fringe_popout.MatthewWindow._build_body.__code__.co_names
    assert "_seal_l2_rows" in names


def test_the_popout_view_menu_offers_the_model_window():
    names = fringe_popout.MatthewWindow._build_menubar.__code__.co_names
    assert "_open_models" in names
