"""R15-C: session continuity -- dataset keys, per-point inputs, markers.

Matthew's third piece of feedback was that session saving and defringing
"need real design integration between the two programs".  Recon found the
gap underneath it: our continuity file wrote ONE copy of the live controls
under every point and never read any of it back, and the per-trace state was
filed under the display label, so two series that both held a 20 GPa point
shared one set of notches, role glyphs and fits.

This file pins the fix, against his design (defringe_dac.py 9156-9281,
11129-11416, 13309-13347, 14622-14828):

  * IDENTITY -- state is keyed by "stem:<file stem>", the label is display
    only, and a folder switch does not leak one series' work into the next;
  * INPUTS -- each point's numbers, notch list, low-pass and role glyphs
    round-trip through series_continuity.json, in his blocks with his key
    names, and a file his program wrote survives a trip through ours with
    the fields we have no control for intact (including rect_fit_mode,
    which his own reader drops);
  * MARKERS -- the pressure dropdown decorates each point with its state
    against the file on disk, and every read of the dropdown normalises the
    decoration away again;
  * SEEDING -- a point with nothing recorded opens on the nearest preceding
    committed point, in his order;
  * P4 -- a redraw request does not empty the compute cache.

Runs against the suite's ONE shared App (tests/conftest.py).
"""
import json
import os

import numpy as np
import pytest

import fringe_panel
from conftest import gui, make_result, shared_app

USES_APP = True
pytestmark = gui


@pytest.fixture(scope="module")
def a():
    return shared_app()


@pytest.fixture
def fw(a):
    """The workbench with a clean slate, put back afterwards."""
    w = a._fringe
    w.build()
    keep = (dict(w._chan), dict(w._trace), dict(w._disk), dict(w._inputs),
            dict(w._inputs_extra), dict(w._live_inputs), list(w._series),
            w._label, w._local, list(a.results), w.fitmode_v.get(),
            {k: v.get() for k, v in (("ns", w.ns_v), ("t", w.t_v),
                                     ("d1", w.d1_v), ("d2", w.d2_v))})
    for d in (w._chan, w._trace, w._disk, w._inputs, w._inputs_extra,
              w._live_inputs, w._cache, w._fits, w._msv_cache, w._seed_said):
        d.clear()
    w._series = []
    w._dk_cache = {}
    w._dk_sig = None
    w._invalidate_json_cache()
    yield w
    for d, src in ((w._chan, keep[0]), (w._trace, keep[1]),
                   (w._disk, keep[2]), (w._inputs, keep[3]),
                   (w._inputs_extra, keep[4]), (w._live_inputs, keep[5])):
        d.clear()
        d.update(src)
    w._series = keep[6]
    w._label = keep[7]
    w._local = keep[8]
    a.results = keep[9]
    w.fitmode_v.set(keep[10])
    w._dk_cache = {}
    w._dk_sig = None
    w._invalidate_json_cache()
    w._suspend = True
    try:
        for k, var in (("ns", w.ns_v), ("t", w.t_v), ("d1", w.d1_v),
                       ("d2", w.d2_v)):
            var.set(keep[11][k])
    finally:
        w._suspend = False


# ---------------------------------------------------------------------------
# a Session-loaded folder, without touching the disk
# ---------------------------------------------------------------------------
def _rec(label, stem, pval, branch="C"):
    """One workbench record, shaped like _read_folder's output."""
    r = make_result(label, pval)
    wl = np.linspace(500.0, 900.0, 64)
    r.update({"label": label, "stem": stem, "path": stem + ".csv",
              "wl": wl, "bg_c": np.full(wl.size, 10.0),
              "samp_c": np.full(wl.size, 5.0),
              "pressure_val": pval, "branch": branch,
              "pressure_str": ("%g" % pval).replace(".", "p")})
    return r


def _folder(a, fw, path, recs, label=None):
    """Make `recs` the working set as though the folder had been loaded."""
    a.results = []
    fw._local = {"folder": str(path), "recs": list(recs), "app_sig": ()}
    fw._dk_cache = {}
    fw._dk_sig = None
    fw._label = label if label is not None else recs[0]["label"]
    fw._invalidate_json_cache()


# ---------------------------------------------------------------------------
# 1. identity: the file stem, not the display label
# ---------------------------------------------------------------------------
def test_dataset_key_is_the_stem(a, fw, tmp_path):
    recs = [_rec("20 GPa", "y03_ch29_20p0", 20.0)]
    _folder(a, fw, tmp_path, recs)
    assert fw._dkey() == "stem:y03_ch29_20p0"
    assert fw._stem_from_key(fw._dkey()) == "y03_ch29_20p0"


def test_two_series_do_not_share_a_pressure_label(a, fw, tmp_path):
    """The bug B found: two folders, both with a 20 GPa point, one state."""
    one = tmp_path / "seriesA"
    two = tmp_path / "seriesB"
    one.mkdir()
    two.mkdir()
    _folder(a, fw, one, [_rec("20 GPa", "a_20p0", 20.0)])
    fw._ch("Sample")["user_centers"] = [12.5]
    key_a = fw._dkey()

    _folder(a, fw, two, [_rec("20 GPa", "b_20p0", 20.0)])
    key_b = fw._dkey()
    assert key_a != key_b
    assert fw._ch("Sample")["user_centers"] == []
    assert fw._chan[(key_a, "Sample")]["user_centers"] == [12.5]


def test_folder_switch_clears_the_working_set(a, fw, tmp_path):
    one = tmp_path / "one"
    two = tmp_path / "two"
    one.mkdir()
    two.mkdir()
    _folder(a, fw, one, [_rec("5 GPa", "a_5p0", 5.0)])
    fw._ch("Sample")["user_centers"] = [9.0]
    fw._commit()
    assert fw._disk and fw._inputs
    fw._clear_series_state()
    assert fw._chan == {} and fw._trace == {}
    assert fw._disk == {} and fw._inputs == {}
    assert fw._fits == {} and fw._fit_history == []


def test_notch_override_rows_use_the_stem(a, fw, tmp_path):
    _folder(a, fw, tmp_path, [_rec("20 GPa", "y03_20p0", 20.0)])
    ch = fw._ch("Sample")
    ch["default_centers"] = [11.0]
    ch["widths"] = {11.0: 2.5}
    rows = [r for r in fw.notch_override_rows() if r[0] == "y03_20p0"]
    assert rows and rows[0][1] == "Sample"
    assert rows[0][2] == pytest.approx(11.0)


def test_a_legacy_session_payload_is_adopted_when_its_record_arrives(a, fw,
                                                                     tmp_path):
    """A pre-stem payload keys traces by label; the stem is only knowable
    once the record exists, so the row waits (his key migration note)."""
    fw._disk_legacy = {"20 GPa": {"chan": {"Sample":
                                           {"user_centers": [13.0],
                                            "removed": [], "unticked": [],
                                            "user_fundamental": None,
                                            "widths": {}}},
                                  "roles": {}, "solved": None}}
    fw._adopt_legacy_disk()
    assert fw._disk_legacy, "no record yet: the row stays put"
    _folder(a, fw, tmp_path, [_rec("20 GPa", "y03_20p0", 20.0)])
    fw._adopt_legacy_disk()
    assert fw._disk_legacy == {}
    assert fw._disk["stem:y03_20p0"]["chan"]["Sample"]["user_centers"] \
        == [13.0]
    fw._disk_legacy = {}


# ---------------------------------------------------------------------------
# 2. per-point inputs round-trip
# ---------------------------------------------------------------------------
def _commit_point(fw, centres=(11.0, 22.0), t="21", ns="1.7"):
    ch = fw._ch("Sample")
    ch["default_centers"] = [centres[0]]
    ch["user_centers"] = [centres[1]]
    ch["unticked"] = {centres[1]}
    ch["widths"] = {centres[0]: 2.5}
    tr = fw._tr()
    # all three paths: _record_point needs A, C and iii, in physical order
    tr["roles"]["sample"] = {"nt_um": 18.0, "auto": False}
    tr["roles"]["sampledia"] = {"nt_um": 25.0, "auto": False}
    tr["roles"]["mediumdia"] = {"nt_um": 30.0, "auto": False}
    fw._suspend = True
    try:
        fw.t_v.set(t)
        fw.ns_v.set(ns)
    finally:
        fw._suspend = False
    fw._commit()


def test_input_snapshot_uses_his_blocks(a, fw, tmp_path):
    _folder(a, fw, tmp_path, [_rec("20 GPa", "y03_20p0", 20.0)])
    _commit_point(fw)
    snap = fw._inputs[fw._dkey()]
    assert set(("nums", "notch", "fitn")) <= set(snap)
    assert set(snap["notch"]["Sample"]) >= {"user", "desel", "removed",
                                            "widths", "fund"}
    assert snap["nums"]["t_um"] == "21"
    assert snap["notch"]["Sample"]["user"] == [22.0]
    assert snap["notch"]["Sample"]["desel"] == [22.0]
    assert snap["roles"]["sample"]["nt_um"] == 18.0


def test_inputs_round_trip_through_the_file(a, fw, tmp_path):
    recs = [_rec("20 GPa", "y03_20p0", 20.0)]
    _folder(a, fw, tmp_path, recs)
    _commit_point(fw)
    tr = fw._tr()
    tr["solved"] = {"n_sample": 1.7, "t_um": 21.0}
    fw._record_point()
    assert fw.save_series() is not None

    # a fresh workbench state, same folder
    for d in (fw._chan, fw._trace, fw._disk, fw._inputs, fw._live_inputs):
        d.clear()
    fw._series = []
    fw._suspend = True
    try:
        fw.t_v.set("5")
        fw.ns_v.set("1.1")
    finally:
        fw._suspend = False
    fw._invalidate_json_cache()
    assert fw.load_series() == 1
    dk = fw._dkey()
    assert dk in fw._inputs
    assert fw.t_v.get() == "21"
    assert fw._ch("Sample")["user_centers"] == [22.0]
    assert fw._ch("Sample")["unticked"] == {22.0}
    assert fw._ch("Sample")["widths"] == {11.0: 2.5}
    assert fw._tr()["roles"]["sample"]["nt_um"] == 18.0


def test_points_are_keyed_by_stem_in_the_file(a, fw, tmp_path):
    _folder(a, fw, tmp_path, [_rec("20 GPa", "y03_20p0", 20.0)])
    _commit_point(fw)
    fw._tr()["solved"] = {"t_um": 21.0}
    fw._record_point()
    payload = fw._series_payload()
    assert list(payload["points"]) == ["stem:y03_20p0"]
    assert payload["points"]["stem:y03_20p0"]["label"] == "20 GPa"
    assert payload["schema"] == fringe_panel.SERIES_SCHEMA


# ---------------------------------------------------------------------------
# his file: read it, keep what we have no control for, write it back
# ---------------------------------------------------------------------------
HIS_FILE = {
    "schema": "fft_gui_series/v2",
    "series_label": "Y03_ch29_Nov2025_ProcessedCSV",
    "materials": {"names": {"anvil": "diamond", "medium": "Ar",
                            "sample": "olivine", "layer2": "KCl"},
                  "layer2_model": "KCl", "layer2": True,
                  "medium_model": "Ar",
                  "rect_fit_mode": "shoulder"},
    "eos": {"selections": {"L": [], "t_layer2": [], "t_s": []},
            "anchors": []},
    "points": {"stem:y03_20p0": {"label": "20 GPa", "stem": "y03_20p0",
                                 "pressure_gpa": 20.0, "pressure": 20.0,
                                 "branch": "C", "sample_um": 18.0}},
    "inputs": {"stem:y03_20p0": {
        "nums": {"n_diamond": "2.4168", "n_medium": "1.28",
                 "n_sample": "1.66", "n_layer2": "1.49",
                 "d2_um": "3", "t_um": "24", "d1_um": "2"},
        "notch": {"Sample": {"user": [21.0], "desel": [], "removed": [],
                             "widths": {"12.0": 3.0}, "fund": 12.0},
                  "Background": {"user": [], "desel": [], "removed": [],
                                 "widths": {}, "fund": None}},
        "fitn": {"Background": 1.31, "Sample": 1.62},
        "his_own_block": {"kept": True}}},
}


def _write_his_file(folder):
    p = os.path.join(str(folder), fringe_panel.SERIES_FILE)
    with open(p, "w", encoding="utf-8") as f:
        json.dump(HIS_FILE, f, indent=2)
    return p


def test_his_file_loads(a, fw, tmp_path):
    _folder(a, fw, tmp_path, [_rec("20 GPa", "y03_20p0", 20.0)])
    _write_his_file(tmp_path)
    assert fw.load_series() == 1
    assert fw.t_v.get() == "24"
    assert fw._ch("Sample")["user_centers"] == [21.0]
    assert fw._ch("Sample")["widths"] == {12.0: 3.0}
    assert fw._ch("Sample")["user_fundamental"] == pytest.approx(12.0)


def test_his_rect_fit_mode_is_read_back(a, fw, tmp_path):
    """His writer stores rect_fit_mode and his own reader drops it."""
    _folder(a, fw, tmp_path, [_rec("20 GPa", "y03_20p0", 20.0)])
    fw.fitmode_v.set("distinct")
    _write_his_file(tmp_path)
    fw.load_series()
    assert fw.fitmode_v.get() == "shared"
    assert fw._series_payload()["materials"]["rect_fit_mode"] == "shoulder"


def test_a_field_we_have_no_control_for_survives_the_round_trip(a, fw,
                                                                tmp_path):
    _folder(a, fw, tmp_path, [_rec("20 GPa", "y03_20p0", 20.0)])
    _write_his_file(tmp_path)
    fw.load_series()
    out = fw._series_payload()["inputs"]["stem:y03_20p0"]
    assert out["his_own_block"] == {"kept": True}
    assert out["nums"]["t_um"] == "24"        # ...and ours are there too
    assert "notch" in out


def test_the_material_seed_never_lands_in_a_point(a, fw, tmp_path):
    _folder(a, fw, tmp_path, [_rec("20 GPa", "y03_20p0", 20.0)])
    _commit_point(fw)
    fw._inputs[fw._dkey()]["layer2_model"] = "KCl"      # as a v1 file had it
    out = fw._inputs_payload()[fw._dkey()]
    assert "layer2_model" not in out


# ---------------------------------------------------------------------------
# 3. the pressure dropdown's markers
# ---------------------------------------------------------------------------
def test_a_marker_never_reaches_the_state(fw):
    assert fw._plain_label("20 GPa ✓") == "20 GPa"
    assert fw._plain_label("20 GPa •") == "20 GPa"
    assert fw._plain_label("20 GPa") == "20 GPa"
    assert fw._plain_label(None) == ""


def test_point_status_tracks_the_file(a, fw, tmp_path):
    _folder(a, fw, tmp_path, [_rec("20 GPa", "y03_20p0", 20.0)])
    dk = fw._dkey()
    assert fw._point_status(dk) == "absent"
    _commit_point(fw)
    fw._tr()["solved"] = {"t_um": 21.0}
    fw._record_point()
    fw.save_series()
    assert fw._point_status(dk) == "saved"
    fw._suspend = True
    try:
        fw.t_v.set("30")
    finally:
        fw._suspend = False
    assert fw._point_status(dk) == "differs"


def test_the_dropdown_carries_the_marker(a, fw, tmp_path):
    _folder(a, fw, tmp_path, [_rec("20 GPa", "y03_20p0", 20.0)])
    fw._trace_cb.configure(values=["20 GPa"])
    fw.trace_v.set("20 GPa")
    fw._pcb_marks = None
    _commit_point(fw)
    fw._tr()["solved"] = {"t_um": 21.0}
    fw._record_point()
    fw.save_series()
    fw._pcb_marks = None
    fw._relabel_pressure_cb()
    assert list(fw._trace_cb.cget("values")) == ["20 GPa ✓"]
    assert fw.trace_v.get() == "20 GPa ✓"
    # ...and the pick handler still finds the point
    assert fw._plain_label(fw.trace_v.get()) == "20 GPa"


# ---------------------------------------------------------------------------
# 4. seed a fresh point from the preceding one
# ---------------------------------------------------------------------------
def _series_of(a, fw, tmp_path):
    recs = [_rec("5 GPa", "s_5p0", 5.0), _rec("10 GPa", "s_10p0", 10.0),
            _rec("20 GPa", "s_20p0", 20.0),
            _rec("10 GPa (D)", "s_10p0d", 10.0, branch="D")]
    _folder(a, fw, tmp_path, recs, label="5 GPa")
    return recs


def test_seed_takes_the_nearest_lower_pressure(a, fw, tmp_path):
    _series_of(a, fw, tmp_path)
    fw._label = "5 GPa"
    _commit_point(fw, t="11")
    fw._label = "10 GPa"
    _commit_point(fw, t="12")
    fw._label = "20 GPa"
    snap, src = fw._seed_from_preceding(fw._dkey())
    assert src == "stem:s_10p0"
    assert snap["nums"]["t_um"] == "12"


def test_seed_stays_inside_the_series(a, fw, tmp_path):
    _series_of(a, fw, tmp_path)
    fw._inputs["stem:from_another_folder"] = {"nums": {"t_um": "99"}}
    fw._label = "5 GPa"
    snap, src = fw._seed_from_preceding(fw._dkey())
    assert src is None and snap is None


def test_a_fresh_point_opens_on_the_seed(a, fw, tmp_path):
    _series_of(a, fw, tmp_path)
    fw._label = "5 GPa"
    _commit_point(fw, t="11")
    fw._label = "10 GPa"
    fw._apply_point_inputs()
    assert fw.t_v.get() == "11"


def test_a_recorded_point_opens_on_its_own_inputs(a, fw, tmp_path):
    _series_of(a, fw, tmp_path)
    fw._label = "5 GPa"
    _commit_point(fw, t="11")
    fw._label = "10 GPa"
    _commit_point(fw, t="12")
    fw._label = "5 GPa"
    fw._live_inputs.clear()
    fw._apply_point_inputs()
    assert fw.t_v.get() == "11"


def test_an_uncommitted_edit_survives_a_step_away(a, fw, tmp_path):
    _series_of(a, fw, tmp_path)
    fw._label = "5 GPa"
    _commit_point(fw, t="11")
    fw._suspend = True
    try:
        fw.t_v.set("17")
    finally:
        fw._suspend = False
    fw._stash_live()
    fw._label = "10 GPa"
    fw._apply_point_inputs()
    fw._stash_live()
    fw._label = "5 GPa"
    fw._apply_point_inputs()
    assert fw.t_v.get() == "17"


def test_the_modelled_indices_are_never_restored(a, fw, tmp_path):
    """n anvils and n layer 2 follow the point's own pressure, so a seed
    from another pressure must not carry them in (his _model_owned_nums)."""
    _series_of(a, fw, tmp_path)
    assert set(fringe_panel.NUM_DERIVED) <= fw._model_owned_nums()


# ---------------------------------------------------------------------------
# 5. what a save would change
# ---------------------------------------------------------------------------
def test_series_diff_names_the_pending_work(a, fw, tmp_path):
    _folder(a, fw, tmp_path, [_rec("20 GPa", "y03_20p0", 20.0)])
    _commit_point(fw)
    fw._tr()["solved"] = {"t_um": 21.0}
    fw._record_point()
    # With no file on disk his diff reports the whole batch in one line
    # and returns (defringe_dac.py 14484-14488); points are named by
    # pressure only once there is a file to compare against.
    why = fw._series_diff()
    assert why and any(fringe_panel.SERIES_FILE in w for w in why), why
    assert "A save would change" in fw._save_tip()
    fw.save_series()
    assert fw._series_diff() == []
    assert "already matches memory" in fw._save_tip()

    fw._tr()["solved"] = {"t_um": 22.0}
    fw._record_point()
    why = fw._series_diff()
    assert why and any("20 GPa" in w for w in why), why


# ---------------------------------------------------------------------------
# 6. P4: a redraw request keeps the compute cache
# ---------------------------------------------------------------------------
def test_invalidate_keeps_the_compute_cache(a, fw, tmp_path, monkeypatch):
    _folder(a, fw, tmp_path, [_rec("20 GPa", "y03_20p0", 20.0)])
    calls = []
    real = fringe_panel.compute_channel_fit

    def counted(*args, **kw):
        calls.append(kw.get("label"))
        return real(*args, **kw)
    monkeypatch.setattr(fringe_panel, "compute_channel_fit", counted)

    fw._compute("Sample")
    n1 = len(calls)
    assert n1 == 1
    fw._compute("Sample")
    assert len(calls) == n1, "the same signature is served from the cache"
    # the stub mirrors the real signature: `_invalidate` forwards keep_view
    # (a low-pass drag and its release ask for a redraw that leaves the
    # panels' limits alone), and a stub that swallowed it would hide the day
    # the caller and the callee stop agreeing
    monkeypatch.setattr(fw, "_request_redraw",
                        lambda now=False, keep_view=False: None)
    fw._invalidate()
    fw._compute("Sample")
    assert len(calls) == n1, "a redraw request does not empty the cache"


def test_a_changed_signature_recomputes(a, fw, tmp_path, monkeypatch):
    _folder(a, fw, tmp_path, [_rec("20 GPa", "y03_20p0", 20.0)])
    calls = []
    real = fringe_panel.compute_channel_fit

    def counted(*args, **kw):
        calls.append(kw.get("label"))
        return real(*args, **kw)
    monkeypatch.setattr(fringe_panel, "compute_channel_fit", counted)
    fw._compute("Sample")
    fw._ch("Sample")["user_centers"] = [15.0]
    fw._compute("Sample")
    assert len(calls) == 2


def test_the_cache_stays_bounded(a, fw, tmp_path):
    for i in range(80):
        fw._cache[("stem:x%d" % i, "Sample", i)] = {"i": i}
    _folder(a, fw, tmp_path, [_rec("20 GPa", "y03_20p0", 20.0)])
    fw._compute("Sample")
    assert len(fw._cache) <= 64 + 1


# ---------------------------------------------------------------------------
# 7. the notch list cannot re-enter itself (R3)
# ---------------------------------------------------------------------------
def test_a_width_commit_is_ignored_mid_rebuild(a, fw, tmp_path):
    """Destroying the focused Entry emits <FocusOut>, which commits a width,
    which asks for the redraw that rebuilds the list."""
    import tkinter as tk
    _folder(a, fw, tmp_path, [_rec("20 GPa", "y03_20p0", 20.0)])
    ch = fw._ch("Sample")
    ch["default_centers"] = [11.0]
    var = tk.StringVar(value="4.0")
    fw._rebuilding = True
    try:
        fw._set_width("Sample", 11.0, var)
        assert 11.0 not in ch["widths"]
    finally:
        fw._rebuilding = False
    fw._set_width("Sample", 11.0, var)
    assert ch["widths"][11.0] == pytest.approx(4.0)


# ---------------------------------------------------------------------------
# 8. D2: the fine window follows the acquisition date
# ---------------------------------------------------------------------------
def test_the_fine_window_follows_the_folder_date(a, fw, tmp_path):
    old = tmp_path / "Y03_ch29_Jun2025_ProcessedCSV"
    new = tmp_path / "Y03_ch29_Nov2025_ProcessedCSV"
    old.mkdir()
    new.mkdir()
    rec = _rec("20 GPa", "y03_20p0", 20.0)
    _folder(a, fw, old, [rec])
    assert fw._dataset_year_month(rec) == (2025, 6)
    lo_old = fw._cfg_for(rec).fine_wn_lo
    _folder(a, fw, new, [rec])
    assert fw._dataset_year_month(rec) == (2025, 11)
    lo_new = fw._cfg_for(rec).fine_wn_lo
    assert lo_new != lo_old, "Nov 2025 on: the 11200 cm^-1 band"


def test_no_date_keeps_the_legacy_window(a, fw, tmp_path):
    plain = tmp_path / "spectra"
    plain.mkdir()
    rec = _rec("20 GPa", "y03_20p0", 20.0)
    _folder(a, fw, plain, [rec])
    assert fw._dataset_year_month(rec) is None
    cfg = fw._cfg_for(rec)
    assert cfg.fine_wn_lo == fringe_panel.FringeConfig().fine_wn_lo
