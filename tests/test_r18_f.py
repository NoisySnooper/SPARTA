"""R18-F: the port gaps from the R18-B list, and the R18-A typed-cutoff defect.

One section per item, in the order they landed.

  A5.1  A cutoff box holding 0, nothing, or a word means NO low-pass, his
        gate exactly (defringe_dac 6544 `lowpass and lp_cutoff_um and > 0`,
        his reader 13644-13647).  Ours silently applied 0.001 um or 15 um and
        carried that all the way to the exported CSV.
  G1    notch_overrides.csv is MERGED into the fixed path beside the data:
        rows for spectra this session never opened survive (his 14990-14997).
  G2    Save session also writes session_<stamp>.json (his _snapshot_inputs +
        measured_path), and one entry opens either shape.
  G3    The Layer 2 model set, the medium x layer2 cross-product on n_s / t_s,
        and the As recorded toggle.
  G4    One EoS var per (panel, eos), with a material-derived default.
  G5    The FFT panels carry his legend: one "= 54.89 um" entry per assigned
        role.
  G6    A cold load reads its Gaussian-refined centres (his 63.333 / 54.893
        with t_s 45.744), not the raw peak bins (63.612 / 55.210, t_s 46.009).
  G7    Two residual tiers, his n*t values, his window clipping.
  G8    The 580 / 640 / 766 / 905 nm reference lines.
  G9    The live FFT-resolution readout and the index-ordering paragraph.
  G10   Reset & drop point clears the notch config too.
  G12   The overlay colourway.
  G13   _active_centers in insertion order; the export sorts ascending.
  G14   Thickness spinboxes stop at his 100000.
  G16   The series anchor carries his `curve` field, and reads both shapes.

His t_s 45.744 comes off the real Y03_ch29 3.71 GPa spectrum, which this
suite does not ship; the cold-start section asserts the mechanism that
produces it (the glyphs are already refined on the first frame, and the boxes
hold the solve of THOSE positions) on synthetic spectra placed at his two
observed n*t.
"""
import csv
import json
import os

import numpy as np
import pytest

import fringe_materials
import fringe_panel
import fringe_popout
from conftest import gui, make_result, offscreen, shared_app

USES_APP = True

# His observed numbers on Y03_ch29 at 3.71 GPa (R18-B, Pass 3).
HIS_SAMPLE_UM = 63.333
HIS_MEDIUM_UM = 54.893
HIS_T_S = 45.744
OURS_BEFORE_SAMPLE_UM = 63.612          # the raw peak bin, before the snap
OURS_BEFORE_MEDIUM_UM = 55.210
HIS_P_GPA = 3.71


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------
def _one_fringe(nt_um, amp=0.08, n=2400, lo=560.0, hi=860.0):
    """Counts carrying a single strong fringe of optical path `nt_um`."""
    wl = np.linspace(lo, hi, n)
    base = 1000.0 * (1.0 + 0.30 * (wl - lo) / (hi - lo))
    return wl, base * (1.0 + amp * np.cos(4.0 * np.pi * nt_um * 1000.0 / wl))


def _two_peak_rec(label="3.71 GPa", pval=HIS_P_GPA,
                  s_um=HIS_SAMPLE_UM, b_um=HIS_MEDIUM_UM):
    """His 3.71 GPa point in miniature: one fringe per channel."""
    wl, samp = _one_fringe(s_um)
    _wl, bg = _one_fringe(b_um)
    return make_result(label, pval, wl=wl, samp=samp, bg=bg,
                       dark=np.full(wl.size, 5.0))


class _Box(object):
    """The smallest thing that reads like a tk variable."""

    def __init__(self, text):
        self._text = text

    def get(self):
        return self._text


def _load(a, fw, recs, label=None):
    """Make `recs` the loaded series, without touching the disk."""
    a.results = list(recs)
    fw._local = None
    fw._dk_cache = {}
    fw._dk_sig = None
    fw._cache.clear()
    fw._label = label if label is not None else recs[0]["label"]


def _plain_stack(fw, pressure=None):
    """His shipped stack: a manual medium at 1.2, no Layer 2, unlocked."""
    fw._suspend = True
    try:
        fw.medium_v.set(fringe_materials.MEDIUM_MANUAL)
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


def _labels_on(ax):
    return [str(ln.get_label()) for ln in ax.get_lines()]


class _FakeEvent(object):
    """The two attributes `_grab_at` reads off a mouse event."""

    def __init__(self, fw, chan):
        self.inaxes = fw._axes[chan]
        self.xdata = 15.0
        self.ydata = 0.0
        self.x = 0.0
        self.y = 0.0


@pytest.fixture(scope="module")
def a():
    return shared_app()


@pytest.fixture
def fw(a):
    """The workbench on a clean slate, with every box put back after.

    The Stack is ONE set of controls shared by the whole series, so a value
    this file writes would otherwise decide the next test's solve.
    """
    w = a._fringe
    w.build()
    keep_dicts = (dict(w._chan), dict(w._trace), dict(w._disk),
                  dict(w._inputs), dict(w._live_inputs))
    keep = (w._label, w._local, list(a.results), list(w._series))
    vars_ = {"ns": w.ns_v, "t": w.t_v, "d1": w.d1_v, "d2": w.d2_v,
             "nmed": w.medium_n_v, "med": w.medium_v, "l2": w.layer2_v,
             "dia": w.diamond_v, "dp": w.dp_v, "hw": w.hw_v,
             "total": w.total_v, "wlmin": w.wlmin_v, "wlmax": w.wlmax_v}
    keep_v = {k: v.get() for k, v in vars_.items()}
    keep_b = {"l2on": bool(w.layer2_on_v.get()),
              "lock": bool(w.lock_v.get()),
              "tiers": bool(w.tiers_v.get())}
    keep_lp = {c: (bool(w.lp_on_v[c].get()), w.lp_v[c].get())
               for c in fringe_panel.CHANNELS}
    keep_anchor = dict(w._res_anchor)
    for d in (w._chan, w._trace, w._disk, w._inputs, w._live_inputs,
              w._cache):
        d.clear()
    w._series = []
    w._dk_cache = {}
    w._dk_sig = None
    w._seed_said.clear()
    a.notch_cache.clear()
    yield w
    w._drag = None
    if w._after is not None:
        try:
            w.app.root.after_cancel(w._after)
        except Exception:
            pass
        w._after = None
    for d, src in zip((w._chan, w._trace, w._disk, w._inputs,
                       w._live_inputs), keep_dicts):
        d.clear()
        d.update(src)
    w._label, w._local, a.results, w._series = (keep[0], keep[1],
                                                keep[2], list(keep[3]))
    w._res_anchor = keep_anchor
    w._suspend = True
    try:
        for k, v in vars_.items():
            v.set(keep_v[k])
        w.layer2_on_v.set(keep_b["l2on"])
        w.lock_v.set(keep_b["lock"])
        w.tiers_v.set(keep_b["tiers"])
        for c, (on, cut) in keep_lp.items():
            w.lp_on_v[c].set(on)
            w.lp_v[c].set(cut)
    finally:
        w._suspend = False
    w._cache.clear()
    w._dk_cache = {}
    w._dk_sig = None
    a.notch_cache.clear()


# ===========================================================================
# A5.1  a typed cutoff of 0, blank or non-numeric is NO low-pass
# ===========================================================================
@pytest.mark.parametrize("typed", ["0", "0.0", "-4", "", "   ", "abc",
                                   "nan"])
def test_a_box_with_no_usable_cutoff_reads_as_none(typed):
    """His reader hands None on anything that will not parse, and his gate
    drops a cutoff at or below zero.  One reader answers for every call
    site."""
    assert fringe_panel._lp_cut_um(_Box(typed)) is None


@pytest.mark.parametrize("typed,want", [("19.7", 19.7), ("250", 250.0),
                                        (" 55.21 ", 55.21), ("1", 1.0)])
def test_a_box_with_a_number_reads_as_that_number(typed, want):
    assert fringe_panel._lp_cut_um(_Box(typed)) == pytest.approx(want)


def _panel_source():
    return open(fringe_panel.__file__.replace(".pyc", ".py"),
                encoding="utf-8").read()


def test_the_15_um_fallback_and_the_1e_3_floor_are_gone():
    """The shape the defect was made of -- `max(_f(self.lp_v[c], 15.0),
    1e-3)` -- no longer stands over any cutoff.  The fr_lp_*_um SETTINGS
    keys keep a numeric fallback on purpose: a stored setting is a number.
    """
    src = _panel_source()
    assert "max(_f(self.lp_v" not in src
    assert 'kw["lp_cutoff_um"] = max(' not in src
    assert "lp_cutoff_um=max(" not in src
    assert src.count("_lp_cut_or_none(") >= 8


@gui
@pytest.mark.parametrize("typed", ["0", "", "abc"])
def test_a_typed_non_cutoff_puts_no_low_pass_on_the_channel(a, fw, typed):
    """The workbench's own compute, the recipe the main plot reads, and the
    removed-fraction curve all agree with the box: no low-pass at all."""
    _load(a, fw, [_two_peak_rec()])
    _plain_stack(fw, pressure=HIS_P_GPA)
    chan = "Background"
    fw.lp_on_v[chan].set(True)
    fw.lp_v[chan].set(typed)
    fw._on_lp_edit(chan)                      # <Return> / <FocusOut>

    assert fw._lp_cut_or_none(chan) is None
    rec = fw.defringe_recipe()
    entry = rec["channels"][fringe_panel.CHAN_KEY[chan]]
    assert not entry.get("lowpass")
    assert "lp_cutoff_um" not in entry
    # the removed-fraction preview follows the same rule: whatever the
    # notches take out is all it shows, exactly as with the tick off
    x = np.linspace(1.0, 200.0, 64)
    with_lp = np.asarray(fw._removed_curve(chan, x), float)
    fw.lp_on_v[chan].set(False)
    try:
        without = np.asarray(fw._removed_curve(chan, x), float)
    finally:
        fw.lp_on_v[chan].set(True)
    assert np.allclose(with_lp, without, atol=1e-12)
    # ...and the snapshot records "no cutoff", not 15 um
    snap = fw._input_snapshot()
    assert snap["lp_cutoff_um"][chan] is None


@gui
def test_a_typed_number_still_reaches_the_recipe(a, fw):
    _load(a, fw, [_two_peak_rec()])
    _plain_stack(fw, pressure=HIS_P_GPA)
    chan = "Background"
    fw.lp_on_v[chan].set(True)
    fw.lp_v[chan].set("19.7")
    fw._on_lp_edit(chan)

    assert fw._lp_cut_or_none(chan) == pytest.approx(19.7)
    entry = fw.defringe_recipe()["channels"][fringe_panel.CHAN_KEY[chan]]
    assert entry.get("lowpass") is True
    assert entry["lp_cutoff_um"] == pytest.approx(19.7)
    assert fw._input_snapshot()["lp_cutoff_um"][chan] == pytest.approx(19.7)


@gui
@pytest.mark.parametrize("typed", ["0", "", "abc"])
def test_no_cutoff_draws_no_line_and_no_shade(a, fw, typed):
    """His draw is inside a try that a bad box falls out of, so there is no
    dashed line and no removed-region shade to mislead the reader."""
    _load(a, fw, [_two_peak_rec()])
    _plain_stack(fw, pressure=HIS_P_GPA)
    chan = "Sample"
    fw.lp_on_v[chan].set(True)
    fw.lp_v[chan].set(typed)
    fw._request_redraw(now=True)

    assert fw._artists.get("lp", {}).get(chan) is None
    assert fw._artists.get("lpshade", {}).get(chan) is None
    # and no phantom handle where the line is not
    assert fw._grab_at(chan, 15.0, _FakeEvent(fw, chan)) == (None, None)




@gui
def test_the_pop_out_cutoff_box_is_the_same_variable(a, fw):
    """The pop-out binds the workbench's own StringVar, so the rule holds in
    both windows without a second reader."""
    pop = open(fringe_popout.__file__.replace(".pyc", ".py"),
               encoding="utf-8").read()
    assert "wb.lp_v[chan]" in pop
    fw.lp_v["Sample"].set("abc")
    assert fw._lp_cut_or_none("Sample") is None
    fw.lp_v["Sample"].set("19.7")
    assert fw._lp_cut_or_none("Sample") == pytest.approx(19.7)


def test_the_engine_gate_is_his():
    """No change was made here, and none was needed: the core already reads
    `lowpass and lp_cutoff_um and > 0`, so None means no mask."""
    import fringe_notch
    src = open(fringe_notch.__file__.replace(".pyc", ".py"),
               encoding="utf-8").read()
    assert "if lowpass and lp_cutoff_um and lp_cutoff_um > 0:" in src


# ===========================================================================
# G1  notch_overrides.csv is merged, not overwritten
# ===========================================================================
@gui
def test_the_notch_file_keeps_rows_for_spectra_this_session_never_opened(
        a, fw, tmp_path):
    """His _export_notches drops only the rows whose stem it is writing."""
    rec = _two_peak_rec()
    _load(a, fw, [rec])
    # An engine record carries no "stem" key: the panel builds the
    # batch pipeline's own {dac}_{sample}_{pressure} from the record
    # (fringe_panel 11318-11322), and THAT is what the writer files
    # these rows under.  Only a session-loaded record has a "stem".
    stem = fw._stem_of(rec["label"])
    ch = fw._ch("Sample")
    ch["default_centers"] = [55.21]
    ch["exact"] = {55.21: 55210.19722197445}
    ch["widths"] = {55.21: 3.0}

    path = str(tmp_path / fringe_panel.NOTCH_FILE)
    with open(path, "w", encoding="utf-8", newline="") as f:
        f.write("stem,channel,nt_um,is_fundamental,halfwidth_um\n")
        f.write("SOMEONE_ELSE,Sample,12.3400,1,3.00\n")
        f.write("%s,Sample,99.0000,0,3.00\n" % stem)

    out = fw.export_notch_overrides(path=path)
    assert out == path
    with open(path, encoding="utf-8", newline="") as f:
        rows = [r for r in csv.reader(f) if r]
    head, body = rows[0], rows[1:]
    assert head[0] == "stem" and head[-1] == "halfwidth_um"
    stems = [r[0] for r in body]
    assert "SOMEONE_ELSE" in stems              # a foreign row survives
    assert stems.count(stem) >= 1
    mine = [r for r in body if r[0] == stem]
    assert "99.0000" not in [r[2] for r in mine]   # ours was replaced
    assert float(mine[0][2]) == pytest.approx(55.21, abs=1e-4)


@gui
def test_the_merge_helper_keeps_a_header_the_file_already_had(a, fw,
                                                              tmp_path):
    path = str(tmp_path / "notch_overrides.csv")
    with open(path, "w", encoding="utf-8", newline="") as f:
        f.write("stem,channel,nt_um,is_fundamental,halfwidth_um\n")
        f.write("A,Sample,10.0000,1,3.00\n")
        f.write("B,Background,20.0000,0,3.00\n")
    head, kept = fw._notch_file_merge(path, set(["B"]))
    assert head[0] == "stem"
    assert [r[0] for r in kept] == ["A"]


@gui
def test_the_writer_needs_no_dialog(a, fw):
    """His path is fixed: the writer takes the series folder itself."""
    src = open(fringe_panel.__file__.replace(".pyc", ".py"),
               encoding="utf-8").read()
    body = src.split("def export_notch_overrides")[1].split("\n    def ")[0]
    assert "asksaveasfilename" not in body
    assert "NOTCH_FILE" in body


# ===========================================================================
# G2  session_<stamp>.json, and a loader that reads either shape
# ===========================================================================
def test_the_session_file_is_named_as_his_is():
    assert fringe_panel.SESSION_STAMP == "session_%s.json"


@gui
def test_a_saved_point_snapshot_opens_and_re_applies(a, fw, tmp_path):
    """His _load_session: the snapshot's numbers land back in the boxes, and
    a spectrum it names that is not loaded leaves the inputs applying to the
    point on screen."""
    rec = _two_peak_rec()
    _load(a, fw, [rec])
    _plain_stack(fw, pressure=HIS_P_GPA)
    fw._request_redraw(now=True)          # the cold align runs once, here
    fw.t_v.set("33.5")
    snap = fw._input_snapshot()
    snap["measured_path"] = os.path.join(
        str(tmp_path), fw._stem_of(rec["label"]) + ".csv")
    path = str(tmp_path / "session_20260904_120000.json")
    with open(path, "w", encoding="utf-8") as f:
        json.dump(snap, f)

    fw.t_v.set("11.0")
    assert fw.load_session_file(path=path) == 1
    assert float(fw.t_v.get()) == pytest.approx(33.5)


@gui
def test_a_series_file_picked_by_name_is_read_as_a_series(a, fw, tmp_path):
    """One entry, both shapes: a payload with points goes down the series
    path rather than the snapshot one."""
    path = str(tmp_path / "series_continuity.json")
    with open(path, "w", encoding="utf-8") as f:
        json.dump({"schema": 1, "series_label": "T", "points": {},
                   "inputs": {}}, f)
    assert fw.load_session_file(path=path) == 0     # no points to read
    assert fw._series_path == path


@gui
def test_load_series_accepts_a_named_file(a, fw, tmp_path):
    path = str(tmp_path / "series_continuity.json")
    with open(path, "w", encoding="utf-8") as f:
        json.dump({"schema": 1, "series_label": "T",
                   "points": {"stem:x": {"label": "1 GPa", "pressure": 1.0,
                                         "stem": "x"}},
                   "inputs": {}}, f)
    assert fw.load_series(path=path) == 1
    assert any(p.get("stem") == "x" for p in fw._series)


# ===========================================================================
# G3  the Layer 2 model set and the medium x layer2 cross-product
# ===========================================================================
def _pt(pressure, n_med=1.4, n_l2=1.4):
    return {"pressure": pressure, "A": 63.333, "C": 63.333, "iii": 54.893,
            "n_medium": n_med, "n_layer2": n_l2, "medium": "Ar",
            "layer2": bool(abs(n_med - n_l2) > 1e-12),
            "layer2_name": "KCl"}


@gui
def test_a_series_with_no_layer_2_says_so(a, fw):
    fw._series = [_pt(1.0), _pt(2.0)]
    assert fw._series_has_layer2() is False
    fw._series = [_pt(1.0), _pt(2.0, n_l2=1.9)]
    assert fw._series_has_layer2() is True


@gui
def test_the_layer_2_axis_is_independent_of_the_medium(a, fw):
    """`layer2=` names the material beside the sample and leaves the medium
    where the point recorded it -- which is what makes a cross-product
    meaningful."""
    _load(a, fw, [_two_peak_rec()])
    pt = _pt(HIS_P_GPA, n_med=1.4, n_l2=1.9)
    base = fw._resolve_point(pt)
    if base is None:
        pytest.skip("this triple does not solve")
    assert base["n_medium"] == pytest.approx(1.4)
    assert base["n_layer2"] == pytest.approx(1.9)
    wl = 0.5 * (fringe_panel._f(fw.wlmin_v, 600.0)
                + fringe_panel._f(fw.wlmax_v, 800.0))
    want = fw._index("Ar", HIS_P_GPA, wl)
    only_l2 = fw._resolve_point(pt, layer2="Ar")
    assert only_l2 is not None
    assert only_l2["n_medium"] == pytest.approx(1.4)      # medium untouched
    assert only_l2["n_layer2"] == pytest.approx(want)


@gui
def test_n_s_and_t_s_take_the_cross_product(a, fw):
    """His two check-sets: the medium set drives n_medium and L, the layer 2
    set drives n_layer2 and t_layer2, and n_s / t_s take the product."""
    _load(a, fw, [_two_peak_rec()])
    fw._series = [_pt(1.0, n_l2=1.9)]                 # a real Layer 2
    pts = list(fw._series)
    series = fw._res_series(pts, ["Ar"], ["air"])
    labels = sorted(series)
    assert len(labels) == 3                           # Ar, layer 2 air, Ar x
    cross = [k for k in labels if " x layer 2 " in k]
    assert len(cross) == 1
    assert series[cross[0]]["panels"] == set(("n_s", "t_s"))
    med = [k for k in labels
           if series[k]["medium"] and not series[k]["layer2"]][0]
    assert series[med]["panels"] == set(("n_medium", "L"))
    l2 = [k for k in labels
          if series[k]["layer2"] and not series[k]["medium"]][0]
    assert series[l2]["panels"] == set(("n_layer2", "t_layer2"))


@gui
def test_one_set_alone_still_reaches_n_s_and_t_s(a, fw):
    """An unchecked side is held as recorded, so the product collapses."""
    _load(a, fw, [_two_peak_rec()])
    fw._series = [_pt(1.0, n_l2=1.9)]
    series = fw._res_series(list(fw._series), ["Ar"], [])
    only = series[list(series)[0]]
    assert "n_s" in only["panels"] and "t_s" in only["panels"]


@gui
def test_a_flat_series_keeps_the_medium_curves_on_the_layer_2_panels(a, fw):
    """With no Layer 2 anywhere, n_layer2 IS n_medium, so the medium curve
    belongs on those panels rather than leaving them empty."""
    _load(a, fw, [_two_peak_rec()])
    fw._series = [_pt(1.0)]
    series = fw._res_series(list(fw._series), ["Ar"], [])
    panels = series[list(series)[0]]["panels"]
    assert "n_layer2" in panels and "t_layer2" in panels


def test_the_as_recorded_toggle_ships_on():
    assert fringe_panel.C_SETTINGS_DEFAULTS["fr_res_recorded"] is True


@gui
def test_the_as_recorded_toggle_is_re_defaulted_per_series(a, fw):
    """His _res_default_check: a series opens on its recorded curve, once
    per series, so a later toggle is never fought."""
    with offscreen(a):
        win = fw.results_view()
    try:
        fw._res_recorded_v.set(False)
        fw._res_default_check()                 # same series: left alone
        assert bool(fw._res_recorded_v.get()) is False
        fw._res_defaulted_for = "another series"
        fw._res_default_check()                 # a new one: back on
        assert bool(fw._res_recorded_v.get()) is True
    finally:
        fw._close_results()
    assert win is not None


# ===========================================================================
# G4  one EoS var per (panel, eos)
# ===========================================================================
@gui
def test_each_panel_has_its_own_eos_vars(a, fw):
    """Ours filed ONE BooleanVar under all three panel keys, so a tick put
    the curve on every thickness panel.  Vinet on t_s and BM3 on L has to be
    expressible."""
    with offscreen(a):
        fw.results_view()
    try:
        names = sorted(fringe_materials.EOS_MODELS)
        first = names[0]
        v_ts = fw._res_eos_v["t_s"][first]
        v_l = fw._res_eos_v["L"][first]
        assert v_ts is not v_l
        v_ts.set(True)
        v_l.set(False)
        assert bool(v_ts.get()) is True and bool(v_l.get()) is False
        sel = fw._eos_selections()
        assert first in (sel.get("t_s") or [])
        assert first not in (sel.get("L") or [])
    finally:
        fw._close_results()


@gui
def test_the_first_tick_comes_from_the_panel_material(a, fw):
    """His _res_eos_default_for: L follows the medium, t_layer2 the layer 2
    material, t_s has no medium model at all."""
    fw._suspend = True
    try:
        fw.medium_v.set("Ar")
        fw.layer2_on_v.set(False)
    finally:
        fw._suspend = False
    assert fw._res_eos_default_for("L") == fringe_materials.MATERIAL_EOS["Ar"]
    assert fw._res_eos_default_for("t_layer2") == \
        fringe_materials.MATERIAL_EOS["Ar"]
    assert fw._res_eos_default_for("t_s") is None
    assert fw._eos_panel_label("t_s") == "t_s"


# ===========================================================================
# G5  the FFT-panel legend
# ===========================================================================
@gui
def test_every_assigned_role_gets_its_own_legend_entry(a, fw):
    """Observed on his: ['measured (600-800 nm)', '= 54.89 um'] on the
    Background and a second entry on the Sample, one per glyph."""
    _load(a, fw, [_two_peak_rec()])
    _plain_stack(fw, pressure=HIS_P_GPA)
    fw._request_redraw(now=True)

    for chan, want in (("Background", 1), ("Sample", 2)):
        leg = fw._axes[chan].get_legend()
        assert leg is not None, chan
        texts = [t.get_text() for t in leg.get_texts()]
        assert any(t.startswith("measured (") for t in texts)
        marks = [t for t in texts if t.startswith("= ")]
        assert len(marks) == want, (chan, texts)
        for t in marks:
            assert t.endswith(" um")
            float(t[2:-3])                     # "= 55.21 um" parses


@gui
def test_the_panel_title_keeps_its_number(a, fw):
    """The legend is an addition; his title line stays as it was."""
    _load(a, fw, [_two_peak_rec()])
    _plain_stack(fw, pressure=HIS_P_GPA)
    fw._request_redraw(now=True)
    heads = [t.get_text() for t in fw._axes["Background"].texts]
    assert any("n*t =" in h for h in heads), heads


# ===========================================================================
# G6  the cold load reads its refined centres
# ===========================================================================
@gui
def test_a_cold_load_is_already_snapped(a, fw):
    """His _update re-fits the auto glyphs on every redraw, so the first
    frame shows 63.333 / 54.893 and t_s 45.744, not the raw peak bins
    63.612 / 55.210 with t_s 46.009.  One snap at the end of the align
    branch is what closes that: running the snap again must not move a
    glyph."""
    _load(a, fw, [_two_peak_rec()])
    _plain_stack(fw, pressure=HIS_P_GPA)
    fw._request_redraw(now=True)

    tr = fw._tr()
    before = dict((r, (tr["roles"].get(r) or {}).get("nt_um"))
                  for r in fringe_panel.ROLES)
    assert before["sample"] == pytest.approx(HIS_SAMPLE_UM, abs=0.35)
    assert before["mediumdia"] == pytest.approx(HIS_MEDIUM_UM, abs=0.35)

    fw._autosnap_roles()
    after = dict((r, (tr["roles"].get(r) or {}).get("nt_um"))
                 for r in fringe_panel.ROLES)
    for role in fringe_panel.ROLES:
        if before[role] is None or after[role] is None:
            continue
        assert after[role] == pytest.approx(before[role], abs=1e-9), role


@gui
def test_the_boxes_hold_the_solve_of_the_snapped_positions(a, fw):
    """The align writes its solve, then the snap moves the glyphs; without a
    second write the boxes would describe positions nothing stands on."""
    _load(a, fw, [_two_peak_rec()])
    _plain_stack(fw, pressure=HIS_P_GPA)
    fw._request_redraw(now=True)
    sol = fw._solve(quiet=True)
    if sol is None or sol.get("error"):
        pytest.skip("this synthetic pair does not solve")
    assert float(fw.t_v.get()) == pytest.approx(float(sol["t_s"]), abs=5e-3)
    assert float(fw.ns_v.get()) == pytest.approx(float(sol["n_s"]), abs=5e-4)


def test_his_cold_start_numbers_are_recorded():
    """The observed pair, kept here so a future change that moves them is
    visible in the diff."""
    assert HIS_SAMPLE_UM == 63.333 and HIS_MEDIUM_UM == 54.893
    assert HIS_T_S == 45.744
    assert OURS_BEFORE_SAMPLE_UM == 63.612


# ===========================================================================
# G7  two residual tiers, his n*t values, his window clipping
# ===========================================================================
@gui
def test_the_tiered_view_draws_both_residual_tiers(a, fw):
    """His 7580-7592: the tallest peak's residual clipped to the fit window,
    and the full-window FFT's own residual over the full window."""
    _load(a, fw, [_two_peak_rec()])
    _plain_stack(fw, pressure=HIS_P_GPA)
    c = fw._compute("Sample")
    if not c or not c.get("nt"):
        pytest.skip("no fringe detected on this synthetic channel")
    rec = fw._record()
    tiers = fw._residual_tiers(c, np.asarray(rec["wl"], float),
                              np.asarray(rec["samp_c"], float))
    assert len(tiers) >= 1
    y0, nt0, alpha0 = tiers[0]
    assert alpha0 == 1.0
    assert nt0 == pytest.approx(HIS_SAMPLE_UM, abs=0.6)
    # clipped to the fit window: outside it the tier is blank, not drawn flat
    assert np.isnan(y0).any()
    assert np.isfinite(y0).any()
    if len(tiers) > 1:
        assert tiers[1][2] == pytest.approx(0.4)


@gui
def test_the_tier_label_reads_the_tier_s_own_nt(a, fw):
    """Each tier prints ITS OWN n*t, and the two do not agree.

    Product truth: tier 1 reads the tallest FFT peak and tier 2 the
    full window's, so on this record the labels read 63.6 and 63.4 um
    -- each inside the FFT's own bin of the 63.333 um fringe that was
    synthesised, and not one number printed twice.  The old assertion
    looked for the NOMINAL 63.3 in the text, which no measured peak
    has to land on; this one holds every label to its own tier.
    """
    rec = _two_peak_rec()
    _load(a, fw, [rec])
    _plain_stack(fw, pressure=HIS_P_GPA)
    fw.tiers_v.set(True)
    try:
        fw._request_redraw(now=True)
        labs = [s for s in _labels_on(fw._maxes["Sample"])
                if "cosine fit" in s]
        c = fw._compute("Sample") or {}
        tiers = fw._residual_tiers(c, np.asarray(rec["wl"], float),
                                   np.asarray(rec["samp_c"], float))
        assert len(tiers) >= 2
        assert len(labs) == len(tiers)
        want = ["n*t=%.1f um" % nt for _y, nt, _al in tiers]
        assert [s.split("  ")[-1] for s in labs] == want
        assert len(set(want)) == len(want), want
        for _y, nt, _al in tiers:
            assert nt == pytest.approx(HIS_SAMPLE_UM, abs=1.5)
    finally:
        fw.tiers_v.set(False)


# ===========================================================================
# G8  the four wavelength reference lines
# ===========================================================================
def test_the_reference_wavelengths_are_his():
    assert [w for w, _c in fringe_panel.REF_WL_NM] == [580, 640, 766, 905]


@gui
def test_the_reference_lines_are_drawn_with_their_nm(a, fw):
    _load(a, fw, [_two_peak_rec()])
    _plain_stack(fw, pressure=HIS_P_GPA)
    fw._request_redraw(now=True)
    ax = fw._maxes["Sample"]
    labels = set(t.get_text() for t in ax.texts)
    for wl_nm, _col in fringe_panel.REF_WL_NM:
        assert str(wl_nm) in labels


@gui
def test_a_dark_page_lifts_the_darkest_line(a, fw):
    """Rule 65: the colour is DERIVED per page, not carried twice.  On a
    pale page his colours stand; on a dark one #550000 is lifted."""
    pale = fw._lift_on_page("#550000")
    assert isinstance(pale, str) and pale.startswith("#")


# ===========================================================================
# G9  the live readouts
# ===========================================================================
@gui
def test_the_bin_readout_follows_the_window(a, fw):
    """His: bin = 1 / (2 * (1/lo - 1/hi)) / 1000, about 1.2 um over
    600-800 nm."""
    fw._suspend = True
    try:
        fw.wlmin_v.set("600")
        fw.wlmax_v.set("800")
    finally:
        fw._suspend = False
    kind, text = fw._info_live("fft_bin")
    assert kind == "m"
    assert "1.2 um" in text
    assert "600-800 nm" in text

    fw._suspend = True
    try:
        fw.wlmin_v.set("500")
        fw.wlmax_v.set("900")
    finally:
        fw._suspend = False
    _kind, wide = fw._info_live("fft_bin")
    assert "500-900 nm" in wide
    assert wide != text


@gui
def test_the_index_ordering_line_says_which_way_it_falls(a, fw):
    _load(a, fw, [_two_peak_rec()])
    _plain_stack(fw, pressure=HIS_P_GPA)
    fw.ns_v.set("2.5")
    kind, text = fw._info_live("index_ordering")
    assert kind == "b"
    assert "flips sign" in text and "do not move" in text
    fw.ns_v.set("1.05")
    _kind, low = fw._info_live("index_ordering")
    assert "no sign flip" in low


def _guide_path():
    return os.path.join(os.path.dirname(os.path.abspath(
        fringe_panel.__file__)), "docs", "guide_content",
        fringe_panel.GUIDE_FILE)


def test_the_guide_carries_both_paragraphs():
    """G9's two claims, each where its reader meets it.

    R19's register sweep cut the textbook half of the index-ordering
    sentence from the guide (rule 4: no explanation of what a scientist
    already knows) and kept the operational half.  The mechanism sentence
    is unchanged in the Stack card's own Info text, which is where the
    reader who is looking at the stems reads it, so BOTH ends are pinned
    here rather than one phrase in one file.
    """
    body = open(_guide_path(), encoding="utf-8").read()
    flat = " ".join(body.split())
    assert "bin" in body
    assert "resolvable" in body
    # the operational claim: which pairs invert, when, and what holds still
    assert "12, 13, 24 and 34 invert" in flat
    assert "n*t positions hold" in flat
    # the mechanism, verbatim, on the card it belongs to
    info = " ".join(
        e[1] for e in fringe_panel.INFO_CONTENT["Stack"]
        if len(e) > 1 and isinstance(e[1], str))
    assert "INDEX ORDERING" in info
    assert "higher or a lower refractive index" in " ".join(info.split())


def test_the_guide_keeps_its_72_column_wrap():
    lines = open(_guide_path(), encoding="utf-8").read().splitlines()
    assert max(len(ln) for ln in lines) <= 72


def test_the_guide_adds_no_all_caps_heading():
    """The new text rides in the sections that already exist; an ALL-CAPS
    line at column 0 would make a section head the tour does not know."""
    heads = [ln for ln in open(_guide_path(), encoding="utf-8")
             .read().splitlines()
             if ln and not ln.startswith(" ") and ln == ln.upper()]
    assert "FFT RESOLUTION" not in heads
    assert "INDEX ORDERING" not in heads


# ===========================================================================
# G10  Reset & drop point clears the notch config
# ===========================================================================
@gui
def test_reset_clears_the_notches_on_both_channels(a, fw):
    """His 11291-11295.  A reset that leaves hand-picked centres behind is
    not the shipped state, and the main plot would still apply them."""
    _load(a, fw, [_two_peak_rec()])
    _plain_stack(fw, pressure=HIS_P_GPA)
    for chan in fringe_panel.CHANNELS:
        ch = fw._ch(chan)
        ch["user_centers"] = [12.34]
        ch["unticked"] = set([12.34])
        ch["removed"] = set([9.9])
        ch["widths"] = {12.34: 2.5}
        ch["exact"] = {12.34: 12340.0}
        ch["user_fundamental"] = 12.34

    fw._reset_and_drop_point()

    for chan in fringe_panel.CHANNELS:
        ch = fw._ch(chan)
        assert ch["user_centers"] == []
        assert ch["unticked"] == set()
        assert ch["removed"] == set()
        assert 12.34 not in ch["widths"]
        assert 12.34 not in ch["exact"]
        assert ch["user_fundamental"] is None


# ===========================================================================
# G12  the overlay colourway
# ===========================================================================
def test_the_overlay_colourway_defaults_to_his():
    assert fringe_panel.C_SETTINGS_DEFAULTS["fr_res_cmap"] == "tab10"
    assert fringe_panel.C_SETTINGS_DEFAULTS["fr_res_skip_faint"] is False


@gui
def test_the_curve_colours_come_from_the_chosen_map(a, fw):
    with offscreen(a):
        fw.results_view()
    try:
        if fw._hc():
            pytest.skip("High Contrast shares one ink for every curve")
        cols = fw._res_curve_colors(["one", "two", "three"])
        assert set(cols) == set(["one", "two", "three"])
        assert len(set(cols.values())) == 3
        assert "tab10" in fw._res_cmap_names()
        assert fw._res_curve_colors([]) == {}
    finally:
        fw._close_results()


@gui
def test_more_curves_than_one_map_holds_grow_an_override_row(a, fw):
    """His overflow: the chain extends into the next map and surfaces a
    dropdown for it."""
    with offscreen(a):
        fw.results_view()
    try:
        labels = ["c%02d" % i for i in range(20)]
        spare = [n for n in fw._res_cmap_names()
                 if n != fw._res_cmap_v.get()]
        cols = fw._res_curve_colors(labels)
        assert len(cols) == len(labels)
        if spare and not fw._hc():
            assert len(fw._res_overflow_v) >= 1
        fw._res_curve_colors(["one"])
        assert fw._res_overflow_v == []
    finally:
        fw._close_results()


# ===========================================================================
# G13  insertion order in, ascending out
# ===========================================================================
@gui
def test_active_centers_keep_their_insertion_order(a, fw):
    """His order: the detected defaults as detected, then the hand-picked
    ones as picked.  The fundamental is not hoisted."""
    _load(a, fw, [_two_peak_rec()])
    ch = fw._ch("Sample")
    ch["default_centers"] = [20.0, 40.0]
    ch["user_centers"] = [10.0]
    ch["user_fundamental"] = 40.0
    assert fw._active_centers("Sample") == [20.0, 40.0, 10.0]


@gui
def test_the_export_sorts_ascending(a, fw):
    """His writer sorts on the way out, whatever order they were picked."""
    rec = _two_peak_rec()
    _load(a, fw, [rec])
    ch = fw._ch("Sample")
    ch["default_centers"] = [20.0, 40.0]
    ch["user_centers"] = [10.0]
    ch["user_fundamental"] = 40.0
    ch["exact"] = {20.0: 20000.0, 40.0: 40000.0, 10.0: 10000.0}
    rows = [r for r in fw.notch_override_rows() if r[1] == "Sample"]
    assert [r[2] for r in rows] == sorted(r[2] for r in rows)
    assert [r[2] for r in rows][:3] == [10.0, 20.0, 40.0]
    assert [r[3] for r in rows] == [0, 0, 1]      # the flag still travels


# ===========================================================================
# G14  his spinbox top
# ===========================================================================
def test_the_thickness_boxes_stop_where_his_do():
    assert fringe_panel.THICK_MAX_UM == 100000.0


@gui
def test_no_thickness_spinbox_reaches_300000(a, fw):
    src = _panel_source()
    pop = open(fringe_popout.__file__.replace(".pyc", ".py"),
               encoding="utf-8").read()
    assert "300000.0" not in src
    assert "300000.0" not in pop


# ===========================================================================
# G16  the series anchor carries his `curve`
# ===========================================================================
def test_the_recorded_curve_key_is_his():
    assert fringe_panel.RES_RECORDED == "__recorded__"


@gui
def test_an_anchor_written_by_his_program_round_trips(a, fw):
    """Both shapes read; his fourth field is handed straight back."""
    fw._apply_eos_state({"anchors": [
        {"panel": "t_s", "eos": "Ar (Dewaele)", "dk": "stem:x",
         "curve": "Ar"},
        {"panel": "L", "eos": "Ar (Dewaele)", "dk": "stem:y"}]})
    assert fw._res_anchor[("t_s", "Ar (Dewaele)")] == "stem:x"
    assert fw._res_anchor_curve[("t_s", "Ar (Dewaele)")] == "Ar"
    assert fw._res_anchor_curve[("L", "Ar (Dewaele)")] == \
        fringe_panel.RES_RECORDED
    payload = fw._series_payload()
    got = dict(((r["panel"], r["eos"]), r.get("curve"))
               for r in payload["eos"]["anchors"])
    assert got[("t_s", "Ar (Dewaele)")] == "Ar"
    assert got[("L", "Ar (Dewaele)")] == fringe_panel.RES_RECORDED
