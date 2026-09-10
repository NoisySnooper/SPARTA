"""The fringe workbench's own contracts (Phases B and C).

A new feature area: `test_fringe_core.py` and `test_fringe_parity.py` cover
the vendored numerics, this file covers what the WORKBENCH does with them.
Detection costs an FFT per channel per trace, so nothing here runs it --
every test seeds the panel's state directly and asserts the rule:

  - the batch-format notch override rows, fundamental first;
  - the seeded role glyphs: parked on the predicted paths, ordered, and
    never over a placement the user or a session already made.  R17 gave
    `_seed_roles` a second path -- a point with no inputs of its own aligns
    to the tallest peak of each panel instead (D3, `allow_align`) -- so the
    calls here pass `allow_align=False` and stay about the model path.  The
    cold start is pinned in `test_r17_w3.py`;
  - the FFT right-click menu offers each panel exactly its own roles;
  - `_resolve_point` is LOSSLESS at the recorded indices, which is the
    whole claim behind the Results view's "exact re-solve";
  - the series survives a save/load round trip byte for byte;
  - `guide_text()` tags the shipped markdown the way the pane renders it.

Runs against the suite's ONE shared App (tests/conftest.py).
"""
import json
import os

import pytest

import fringe_optics
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
    keep = (dict(w._chan), dict(w._trace), list(w._series), w._label,
            list(a.results))
    w._chan.clear()
    w._trace.clear()
    w._series = []
    yield w
    w._chan.clear()
    w._chan.update(keep[0])
    w._trace.clear()
    w._trace.update(keep[1])
    w._series = keep[2]
    w._label = keep[3]
    a.results = keep[4]


# ---------------------------------------------------------------------------
# notch overrides: the file Matthew's batch mode reads
# ---------------------------------------------------------------------------
def test_notch_override_rows_are_batch_shaped_and_ascending(a, fw):
    """His file order, not ours.

    R18-F/G13: his _export_notches writes `for c in
    sorted(_active_centers(ch))` (defringe_dac 15005), so each
    channel's rows go out ASCENDING in n*t and the is_fundamental
    flag rides on whichever row is the fundamental.  SPARTA used to
    hoist the fundamental to the top, which put a file his batch
    reader diffs in a different order for the same notches.
    """
    a.results = [make_result("R1", 1.0, dac="Y04", sample="Arch29",
                             pstr="1p0")]
    fw._label = "R1"
    ch = fw._ch("Sample", "R1")
    ch["default_centers"] = [32.39, 16.20]
    ch["user_centers"] = [48.55, 9.99]
    ch["removed"] = {9.99}                 # clicked off: never exported
    ch["unticked"] = {16.20}               # marker kept, notch off
    ch["user_fundamental"] = 48.55         # right-click pin wins
    ch["widths"] = {48.55: 4.25}

    rows = fw.notch_override_rows()
    assert [r[1] for r in rows] == ["Sample"] * len(rows)
    assert [r[0] for r in rows] == ["y04_arch29_1p0"] * len(rows), \
        "the stem is the batch pipeline's, not the display label"
    assert [(r[2], r[3]) for r in rows] == [(32.39, 0), (48.55, 1)], rows
    assert rows[1][4] == 4.25              # its own half-width
    assert rows[0][4] == pytest.approx(float(fw.hw_v.get()))

    # and the CSV writer is the same rows, in the same order
    import tempfile
    path = os.path.join(tempfile.mkdtemp(prefix="sparta_notch_"),
                        "notch_overrides.csv")
    fw.export_notch_overrides(path)
    lines = open(path, encoding="utf-8").read().strip().splitlines()
    head = [c.strip() for c in lines[0].split(",")]
    assert head == ["stem", "channel", "nt_um", "is_fundamental",
                    "halfwidth_um"]
    assert len(lines) == len(rows) + 1
    assert lines[1].split(",")[:2] == ["y04_arch29_1p0", "Sample"]


# ---------------------------------------------------------------------------
# the opening guess: seeded role glyphs, and the menu that overrides them
# ---------------------------------------------------------------------------
def _fake_peaks(fw, monkeypatch, sample, background):
    """Stand in for detection (an FFT per channel is what this file avoids):
    `sample` / `background` are n*t peaks in STRENGTH order, which is the
    order `peaks_sorted` comes back in.  Shaped like a real computed channel
    so the redraw an assignment triggers still draws."""
    import numpy as np
    grid = {"Sample": sample, "Background": background}

    def compute(chan):
        rec = fw._record()
        if rec is None:
            return None
        xs = np.asarray(grid.get(chan) or [], float)
        return {"cfg": fw._cfg_for(rec), "nt": None, "pv": None, "corr": [],
                "defaults": [], "removed": 0.0,
                "peaks": np.arange(xs.size),
                "nt_um": xs, "V": np.linspace(1.0, 0.5, max(xs.size, 1))[
                    :xs.size]}
    # instance-level, undone by monkeypatch so the shared App is
    # handed back exactly as it was found
    monkeypatch.setattr(fw, "_compute", compute, raising=False)


def test_role_glyphs_seed_onto_the_predicted_paths_and_defer_to_the_user(
        a, fw, monkeypatch):
    """The workbench's way in: a fresh trace arrives with all three glyphs
    parked, snapped to real peaks, ordered, and never on top of a placement
    the user (or a session) already made."""
    a.results = [make_result("R1", 1.0), make_result("R2", 2.0)]
    fw._label = "R1"
    fw._seed_said.clear()
    # R7 ships his defaults d1 = d2 = 0, where A and C coincide by
    # construction (both Sample glyphs start on one peak, his behaviour).
    # This test is about the DISTINCT-pair seed, so give the stack a
    # medium thickness the way any solved cell would have one.
    fw.d1_v.set("5")
    fw.d2_v.set("5")
    rec = fw._record()
    p = fw._stack_params(rec)
    pred = fw._pred_paths(p)
    assert set(pred) == {"sample", "sampledia", "mediumdia"}

    # peaks near the prediction, offered WORST first so a strength-only
    # fallback would pick the wrong pair
    A, C, iii = pred["sample"], pred["sampledia"], pred["mediumdia"]
    _fake_peaks(fw, monkeypatch, [C * 0.9, A * 0.9], [iii * 0.95])
    # allow_align=False: this trace has no committed inputs, so the R17 cold
    # start would put both Sample glyphs on ONE peak before the prediction
    # was ever consulted.  That path is test_r17_w3.py's.
    fw._seed_roles(p, 1e4, allow_align=False)
    roles = fw._tr()["roles"]
    assert roles["sample"]["nt_um"] == pytest.approx(A * 0.9)
    assert roles["sampledia"]["nt_um"] == pytest.approx(C * 0.9)
    assert roles["mediumdia"]["nt_um"] == pytest.approx(iii * 0.95)
    assert roles["sample"]["nt_um"] < roles["sampledia"]["nt_um"]
    assert all(roles[r]["seed"] for r in fringe_panel.ROLES)
    # an untouched seed is the workbench's guess, not unsaved work
    assert fw._dirty_items() == []

    # a second pass leaves them exactly where they are
    fw._seed_roles(p, 1e4, allow_align=False)
    assert fw._tr()["roles"]["sample"]["nt_um"] == pytest.approx(A * 0.9)

    # ...and a glyph the user placed is never overwritten, on this trace
    fw._assign_role_here("sample", 5.0)
    fw._seed_roles(p, 1e4, allow_align=False)
    assert fw._tr()["roles"]["sample"]["nt_um"] == pytest.approx(5.0)
    assert not fw._tr()["roles"]["sample"].get("seed")
    assert fw._dirty_items() == ["this trace is waiting for its first "
                                "save"], \
        "a placement IS work; only the untouched seed is free"

    # a session's roles arrive before the first draw: hands off, and no
    # leave guard on a trace nobody has touched
    fw._label = "R2"
    state = {"chan": {}, "solved": None,
             "roles": {r: {"nt_um": 11.0 + i, "auto": False}
                       for i, r in enumerate(fringe_panel.ROLES)}}
    fw._apply_trace_state(fw._dkey("R2"), state)
    fw._commit("R2")
    fw._seed_roles(fw._stack_params(fw._record()), 1e4, allow_align=False)
    assert [fw._tr()["roles"][r]["nt_um"] for r in fringe_panel.ROLES] == \
        [11.0, 12.0, 13.0]
    assert fw._dirty_items() == []

    # a prediction nowhere near the data (the Stack still holds its
    # defaults): fall back to the strongest peaks, in n*t order, so the
    # pair the solve gets is still invertible
    fw._label = "R1"
    fw._trace[fw._dkey("R1")] = {
        "roles": {r: None for r in fringe_panel.ROLES},
        "gauss": {r: None for r in fringe_panel.ROLES}, "solved": None}
    was_t = fw.t_v.get()
    fw._suspend = True
    fw.t_v.set("900")
    fw._suspend = False
    try:
        _fake_peaks(fw, monkeypatch, [40.0, 12.0], [9.0])
        fw._seed_roles(fw._stack_params(fw._record()), 1e4,
                       allow_align=False)
        placed = fw._tr()["roles"]
        assert placed["sample"]["nt_um"] == pytest.approx(12.0)
        assert placed["sampledia"]["nt_um"] == pytest.approx(40.0)
        assert placed["mediumdia"]["nt_um"] == pytest.approx(9.0)
    finally:
        fw._suspend = True
        fw.t_v.set(was_t)
        fw._suspend = False

    # no peak worth landing on: nothing is parked, and the line says why
    fw._label = "R1"
    fw._trace[fw._dkey("R1")] = {
        "roles": {r: None for r in fringe_panel.ROLES},
        "gauss": {r: None for r in fringe_panel.ROLES}, "solved": None}
    fw._seed_said.clear()
    _fake_peaks(fw, monkeypatch, [], [])
    said = []
    monkeypatch.setattr(fw, "_status",
                        lambda msg, **kw: said.append(msg))
    fw._seed_roles(p, 1e4, allow_align=False)
    assert not any(fw._tr()["roles"].values())
    assert said and "the detector missed this trace" in said[0]


def test_the_fft_right_click_menu_offers_the_panels_own_roles(
        a, fw, monkeypatch):
    """Right-click assign is the always-available way to place a role, so
    each panel offers exactly the roles it carries -- and nothing else."""
    import tkinter as tk
    a.results = [make_result("R1", 1.0)]
    fw._label = "R1"
    _fake_peaks(fw, monkeypatch, [32.39], [27.59])
    seen = []
    real = tk.Menu                     # captured BEFORE the patch: the
    #                                    module attribute is about to move

    class Spy(real):
        def add_command(self, **kw):
            seen.append(kw)
            real.add_command(self, **kw)

        def tk_popup(self, *args, **kw):
            pass                       # never posted: no GUI in the suite

    fringe_panel.tk.Menu = Spy
    try:
        fw._rclick("Sample", 32.4, type("E", (), {"inaxes": None,
                                                  "guiEvent": None})())
        sample_labels = [str(k["label"]) for k in seen]
        seen[:] = []
        fw._rclick("Background", 27.6, type("E", (), {"inaxes": None,
                                                      "guiEvent": None})())
        bg_labels = [str(k["label"]) for k in seen]
    finally:
        fringe_panel.tk.Menu = real

    assert "Assign 32.39 um as Sample" in sample_labels
    assert "Assign 32.39 um as Sample diamonds" in sample_labels
    assert not [s for s in sample_labels if "Medium" in s]
    assert "Assign 27.59 um as Medium diamond" in bg_labels
    assert not [s for s in bg_labels if "Assign" in s and "Sample" in s]

    # and the item does what it says
    [k for k in seen if "Medium diamond" in str(k["label"])][0]["command"]()
    assert fw._tr()["roles"]["mediumdia"]["nt_um"] == pytest.approx(27.59)


# ---------------------------------------------------------------------------
# the exact re-solve
# ---------------------------------------------------------------------------
def _point(label="R1", p=1.0):
    """A recorded point whose solved block really came from solve_paths."""
    A, C, iii, n_l2, n_med = 48.0, 62.0, 71.0, 1.42, 1.42
    sol = fringe_optics.solve_paths(A, C, iii, n_l2, n_med)
    assert sol is not None
    return {"label": label, "stem": label, "pressure": p, "branch": "C",
            "A": A, "C": C, "iii": iii,
            "medium": "argon", "layer2": False, "layer2_name": "argon",
            "n_medium": n_med, "n_layer2": n_l2, "diamond": "peter",
            "solved": {k: float(v) for k, v in sol.items() if k != "warns"}}


def test_resolving_a_point_at_its_own_indices_returns_the_recorded_numbers(
        a, fw):
    """(A, C, iii) are the measurement and solve_paths conserves A, so the
    stored solved tuple is a lossless encoding: re-solving must be identity,
    not an approximation."""
    pt = _point()
    got = fw._resolve_point(pt)
    assert got is not None
    for key in ("n_s", "t_s", "L", "t_layer2"):
        assert got[key] == pytest.approx(pt["solved"][key], rel=0, abs=1e-12), \
            key
    assert got["n_medium"] == pytest.approx(pt["n_medium"])
    assert got["n_layer2"] == pytest.approx(pt["n_layer2"])

    # a point missing a path is refused rather than half-solved
    broken = dict(pt)
    del broken["iii"]
    assert fw._resolve_point(broken) is None


def test_a_recorded_points_branch_follows_the_live_c_d_state(a, fw):
    """A D list or a ticked D box has to move the marker in the Results view
    without the point being recorded again."""
    a.results = [make_result("R1", 1.0)]
    a._build_trace_checks()
    pt = _point("R1")
    fw._series = [pt]
    assert fw._pt_branch(pt) == "C"
    a.dvars["R1"].set(True)
    assert fw._pt_branch(pt) == "D"
    a.dvars["R1"].set(False)
    assert fw._pt_branch(pt) == "C"


# ---------------------------------------------------------------------------
# series continuity file
# ---------------------------------------------------------------------------
def test_the_series_survives_a_save_and_load_round_trip(a, fw, tmp_path):
    was_in = a.in_var.get()
    a.in_var.set(str(tmp_path))
    try:
        fw._series = [_point("R1", 1.0), _point("R2", 2.0)]
        before = json.dumps(fw.save_state(), sort_keys=True, default=str)

        path = fw.save_series()
        assert path and os.path.isfile(path)
        assert os.path.basename(path) == fringe_panel.SERIES_FILE
        payload = json.load(open(path, encoding="utf-8"))
        assert payload["schema"] == fringe_panel.SERIES_SCHEMA
        assert set(payload["points"]) == {"stem:R1", "stem:R2"}
        # the stamped copy is the insurance against a save over a good series
        stamps = [n for n in os.listdir(str(tmp_path))
                  if n != fringe_panel.SERIES_FILE and n.endswith(".json")
                  and not n.endswith(".provenance.json")]
        assert stamps, "save_series must leave a stamped copy behind"

        fw._series = []
        fw._series_disk = None
        assert fw.load_series() == 2
        after = json.dumps(fw.save_state(), sort_keys=True, default=str)
        assert after == before
    finally:
        a.in_var.set(was_in)


def test_load_series_refuses_a_file_it_cannot_read(a, fw, tmp_path):
    was_in = a.in_var.get()
    a.in_var.set(str(tmp_path))
    try:
        fw._series = [_point("R1", 1.0)]
        with open(os.path.join(str(tmp_path), fringe_panel.SERIES_FILE),
                  "w", encoding="utf-8") as f:
            f.write("{not json")
        assert fw.load_series() == 0
        assert len(fw._series) == 1, "a bad file changes nothing"

        with open(os.path.join(str(tmp_path), fringe_panel.SERIES_FILE),
                  "w", encoding="utf-8") as f:
            json.dump({"schema": fringe_panel.SERIES_SCHEMA,
                       "points": []}, f)
        assert fw.load_series() == 0
        assert len(fw._series) == 1
    finally:
        a.in_var.set(was_in)


# ---------------------------------------------------------------------------
# the side guide
# ---------------------------------------------------------------------------
def test_guide_text_tags_the_shipped_markdown_the_way_the_pane_renders_it():
    """Pure: no App.  The pane and the Guide / notes dropdown read the SAME
    file, so this also proves they cannot drift apart."""
    lines = fringe_panel.guide_text()
    assert len(lines) > 20
    tags = {t for t, _s in lines}
    # h = section head, s = sub-head, b/i = paragraph, m = verbatim, gap
    assert tags <= {"h", "s", "b", "i", "m", "gap"}, tags
    assert {"h", "s", "m"} <= tags, tags

    heads = [s for t, s in lines if t == "h"]
    assert heads[0] == "FRINGE WORKBENCH"
    for h in heads:
        assert h == h.upper() and h.strip() == h, h
    # the workbench's own sections (R7: Matthew's grouping), spelled as the
    # _group titles the honesty gate checks -- the guide is an index, so a
    # paraphrase is a bug
    for sec in ("STACK", "SESSION", "PRESSURE POINT", "FFT REMOVAL",
                "REFRACTIVE INDEX FROM INTENSITY", "PANELS"):
        assert "FRINGE > " + sec in heads, sec
    assert all(s.strip() for _t, s in lines if _t != "gap")

    mono = [s for t, s in lines if t == "m"]
    assert mono and all(s.startswith("      ") for s in mono), \
        "a verbatim line keeps the file's own indent"

    para = [s for t, s in lines if t in ("b", "i")]
    assert sum(len(s) for s in para) > 2000, \
        "the pane carries the whole view, not a stub"
    # paragraphs are re-flowed, so the file's 72-column hard breaks are gone
    assert max(len(s) for s in para) > 120
