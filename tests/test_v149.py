"""v1.4.9 batch: decompression line styling, the Thickness plot mode, and
the thickness-aware formula builtins.

What is locked here is the contract, not the pixels:
  - the D-branch style vars exist, live in the preset registry, persist to
    their own settings keys, and REALLY reach the drawn Line2D (pattern,
    width, opacity, marker, and the marker thinning on a long curve);
  - the defaults still reproduce the historical look (dashed, same width);
  - Thickness mode draws one point per trace from the fringe detector,
    breaks its line at a non-detection and marks it, and never lets the 3D
    ridge hijack it;
  - alpha = ln(10)*A/t_cm is numerically right, in cm^-1, and t propagates
    NaN through any formula on a trace with no confident fringe.

Detection costs an FFT per channel per trace, so a test that needs the
series loaded says everything it has to say about that load.  Runs against
the suite's ONE shared App (tests/conftest.py); no Toplevel here is ever
mapped on the visible desktop.
"""
import numpy as np
import pytest

import app
import fringe_apply
import formulas as F
from conftest import ROOT, gui, offscreen, quiesce, shared_app

USES_APP = True
pytestmark = gui


@pytest.fixture(scope="module")
def a():
    return shared_app()


# ---------------------------------------------------------------------------
# synthetic traces
# ---------------------------------------------------------------------------
WL = np.linspace(400.0, 1000.0, 1200)
NT_NM = 25_000.0                     # 25 um of optical thickness


def _fringed(amp=0.12):
    """A raw counts channel carrying one clean diamond fringe at NT_NM."""
    base = 1000.0 + 200.0 * np.exp(-((WL - 700.0) / 120.0) ** 2)
    return base * (1.0 + amp * np.cos(2 * np.pi * 2 * NT_NM / WL))


def _unfringed(seed=1):
    """A raw counts channel the Fisher gate refuses (checked below)."""
    rs = np.random.RandomState(seed)
    return 1000.0 + 0.5 * WL + rs.normal(0.0, 20.0, WL.size)


def _res(label, pval, fringe=True):
    s = _fringed() if fringe else _unfringed()
    b = _fringed(0.10) if fringe else _unfringed(2)
    d = np.ones_like(WL)
    with np.errstate(divide="ignore", invalid="ignore"):
        a = -np.log10((s - d) / (b - d))
    a[~np.isfinite(a)] = np.nan
    return {"label": label, "dac": "D1", "sample": "S1",
            "pressure_str": label.split()[0], "pressure_val": pval, "rep": 1,
            "branch_tag": None, "wl": WL.copy(), "wn": 1e7 / WL,
            "absorbance": a, "dark_c": d, "bg_c": b, "samp_c": s}


def _series():
    """Two compression traces with a fringe, one decompression trace, and
    one trace the detector will refuse."""
    return [_res("1.00 GPa", 1.0), _res("2.00 GPa", 2.0),
            _res("3.00 GPa", 3.0, fringe=False), _res("4.00 GPa", 4.0)]


def _load(a):
    a._finish_run([dict(r) for r in _series()], [], "v149")


def _reset_decomp(a):
    a.dash_decomp.set(True)
    a.decomp_style.set("dashed")
    a.decomp_dashes.set("6, 3")
    a.decomp_lw.set("")
    a.decomp_alpha.set("1")
    a.decomp_marker.set("none")
    a.decomp_msize.set("4")
    a.line_style.set("solid")
    a._sync_decomp_row()


def _mark_d(a, labels):
    for lbl, v in a.dvars.items():
        v.set(lbl in labels)


def _lines_by_label(a):
    return {lbl: ln for ln, lbl in a._pick_map.items()}


# ---------------------------------------------------------------------------
# the synthetic data really is what the tests assume
# ---------------------------------------------------------------------------
def test_the_fixtures_are_detected_and_refused_as_intended():
    r = fringe_apply.clean_channel(WL, _fringed())
    assert r["applied"] and abs(r["nt_um"] - NT_NM * 1e-3) < 0.5
    r = fringe_apply.clean_channel(WL, _unfringed())
    assert not r["applied"] and r["nt_um"] is None
    nt, _pv = fringe_apply.detect_nt(WL, _fringed())
    assert nt is not None and abs(nt - NT_NM * 1e-3) < 0.5
    assert fringe_apply.detect_nt(WL, _unfringed())[0] is None


# ---------------------------------------------------------------------------
# formulas.py: the new column and the two builtins (pure, no GUI)
# ---------------------------------------------------------------------------
def test_t_is_a_registered_column_and_both_builtins_are_well_formed():
    assert "t" in F.column_names()
    assert F.canonical("thickness") == "t"
    assert any(c["name"] == "t" for c in F.column_legend())
    for name in ("Absorption coefficient", "A/t"):
        q = next(x for x in F.BUILTINS if x["name"] == name)
        assert F.validate_quantity(q, taken=[]) == []
        assert F.mathtext_problems(q["latex"]) == []
        assert F.is_builtin(q)


def test_alpha_and_a_over_t_are_numerically_right():
    """alpha = ln(10) * A / t_cm, with t handed in as um; A/t stays per-um;
    and a NaN thickness propagates rather than guessing."""
    alpha = next(x for x in F.BUILTINS
                 if x["name"] == "Absorption coefficient")
    assert alpha["unit"] == "cm^-1"
    A = np.array([0.5, 1.0, 2.0])
    got = F.evaluate_quantity(alpha, {"A": A, "t": np.full(3, 25.0)})
    assert np.allclose(got, np.log(10.0) * A / (25.0 * 1e-4),
                       rtol=0, atol=1e-9)
    # the factor really is the um -> cm one: 10 um of the same A must give
    # 2.5x the coefficient of 25 um
    got10 = F.evaluate_quantity(alpha, {"A": A, "t": np.full(3, 10.0)})
    assert np.allclose(got10 / got, 2.5, rtol=1e-12)
    assert np.isnan(F.evaluate_quantity(
        alpha, {"A": np.array([0.5, 1.0]), "t": np.full(2, np.nan)})).all()

    aot = next(x for x in F.BUILTINS if x["name"] == "A/t")
    assert aot["unit"] == "um^-1"
    out = F.evaluate_quantity(aot, {"A": np.array([0.5]),
                                    "t": np.array([25.0])})
    assert abs(float(out[0]) - 0.02) < 1e-12


# ---------------------------------------------------------------------------
# decompression styling
# ---------------------------------------------------------------------------
def test_decomp_vars_are_in_the_registry_and_persist_to_their_own_keys(a):
    reg = a._preset_registry()
    for k in ("line_style", "dash_decomp", "decomp_style", "decomp_dashes",
              "decomp_lw", "decomp_alpha", "decomp_marker", "decomp_msize",
              "thick_S", "thick_B", "thick_miss", "thick_line"):
        assert k in reg, k

    _reset_decomp(a)
    a.decomp_style.set("custom")
    a.decomp_dashes.set("8, 2, 2, 2")
    a.decomp_lw.set("2.5")
    a.decomp_alpha.set("0.4")
    a.decomp_marker.set("square")
    a.decomp_msize.set("6")
    a._persist_decomp()
    st = a.settings
    assert st["decomp_style"] == "custom"
    assert st["decomp_dashes"] == "8, 2, 2, 2"
    assert st["decomp_lw"] == "2.5"
    assert st["decomp_alpha"] == "0.4"
    assert st["decomp_marker"] == "square"
    assert st["decomp_msize"] == "6"
    assert st["decomp_apart"] is True

    snap = {k: v.get() for k, v in reg.items()}
    _reset_decomp(a)
    assert a.decomp_style.get() == "dashed"
    a._apply_preset_data(snap)
    assert a.decomp_style.get() == "custom"
    assert a.decomp_marker.get() == "square"
    assert a.decomp_msize.get() == "6"
    _reset_decomp(a)


def test_custom_pattern_parses_falls_back_and_gates_its_boxes(a):
    _reset_decomp(a)
    assert str(a._decomp_dash_e.cget("state")) == "disabled"
    assert str(a._decomp_msize_e.cget("state")) == "disabled"
    a.decomp_style.set("custom")
    a.decomp_marker.set("circle")
    a._sync_decomp_row()
    assert str(a._decomp_dash_e.cget("state")) == "normal"
    assert str(a._decomp_msize_e.cget("state")) == "normal"

    a.decomp_dashes.set("6, 3")
    assert a._decomp_ls() == (0, (6.0, 3.0))
    a.decomp_dashes.set("8 2 2 2")
    assert a._decomp_ls() == (0, (8.0, 2.0, 2.0, 2.0))
    # an odd count is trimmed to on/off pairs, junk falls back to dashed
    a.decomp_dashes.set("6 3 2")
    assert a._decomp_ls() == (0, (6.0, 3.0))
    for junk in ("", "abc", "4"):
        a.decomp_dashes.set(junk)
        assert a._decomp_ls() == "--", junk
    _reset_decomp(a)


def test_decomp_defaults_and_overrides_reach_the_drawn_line(a):
    """The shipped look is what every build before v1.4.9 drew: solid C,
    dashed D at the compression width, no markers.  Every override then
    lands on the D line and NONE of it touches C."""
    _reset_decomp(a)
    _load(a)
    _mark_d(a, ["4.00 GPa"])
    a.mode.set("overlay")
    a.show_smooth.set(False)
    a.lw.set(1.0)
    a._redraw_now()
    lines = _lines_by_label(a)
    assert lines["1.00 GPa"].get_linestyle() == "-"
    assert lines["4.00 GPa"].get_linestyle() == "--"
    assert lines["4.00 GPa"].get_linewidth() \
        == lines["1.00 GPa"].get_linewidth()
    assert lines["4.00 GPa"].get_marker() in ("None", "", None)

    a.decomp_style.set("dotted")
    a.decomp_lw.set("2.5")
    a.decomp_alpha.set("0.4")
    a.decomp_marker.set("square")
    a.decomp_msize.set("6")
    a._redraw_now()
    lines = _lines_by_label(a)
    d, c = lines["4.00 GPa"], lines["1.00 GPa"]
    assert d.get_linestyle() == ":"
    assert abs(d.get_linewidth() - 2.5) < 1e-9
    assert abs(d.get_alpha() - 0.4) < 1e-9
    assert d.get_marker() == "s"
    assert abs(d.get_markersize() - 6.0) < 1e-9
    assert d.get_markevery() == max(1, WL.size // 24)   # not 1200 markers
    assert c.get_linestyle() == "-"
    assert abs(c.get_linewidth() - 1.0) < 1e-9
    assert c.get_marker() in ("None", "", None)

    # ... and the whole 'style D apart' idea can be switched off
    _reset_decomp(a)
    a.line_style.set("dashdot")
    a.dash_decomp.set(False)
    a._redraw_now()
    lines = _lines_by_label(a)
    assert lines["4.00 GPa"].get_linestyle() == "-."
    assert lines["1.00 GPa"].get_linestyle() == "-."
    _reset_decomp(a)


# ---------------------------------------------------------------------------
# Thickness plot mode
# ---------------------------------------------------------------------------
def test_thickness_rows_plot_table_and_cache(a):
    """One load, one detection pass, everything Thickness mode promises:
    the rows match the fringe detector, the gates own the cache, the
    plot breaks its line at a miss and marks it, the axis labels follow the
    Series variable, the 3D ridge cannot hijack the mode, the D branch takes
    the decompression style, and the table lists every trace."""
    from tkinter import ttk
    import tkinter as tk

    _reset_decomp(a)
    _load(a)
    _mark_d(a, [])
    rows = a._thickness_rows()
    assert [r["pressure_val"] for r, _ in rows] == [1.0, 2.0, 3.0, 4.0]
    got = {r["pressure_val"]: d["s"] for r, d in rows}
    assert got[3.0] is None                       # the refused trace
    for p in (1.0, 2.0, 4.0):
        assert got[p] is not None
        assert abs(got[p] - NT_NM * 1e-3) < 0.5

    a.mode.set("thickness")
    a.thick_S.set(True)
    a.thick_B.set(False)
    a.thick_miss.set(True)
    a.legend_on.set(True)
    a._redraw_now()
    lines = a.ax.get_lines()
    assert lines, "thickness mode drew nothing"
    ys = np.asarray(lines[0].get_ydata(), float)
    assert ys.size == 4
    assert np.isnan(ys[2])                        # the miss BREAKS the line
    assert np.isfinite(ys[[0, 1, 3]]).all()
    assert lines[0].get_marker() == "o"
    # the miss marker: a down triangle, hollow, just above the axis
    tri = [ln for ln in lines if ln.get_marker() == "v"]
    assert len(tri) == 1
    assert list(tri[0].get_xdata()) == [3.0]
    ylo, yhi = a.ax.get_ylim()
    assert ylo < float(tri[0].get_ydata()[0]) < ylo + 0.4 * (yhi - ylo)
    assert "n*t for" in a._thick_status.cget("text")
    assert "missed by the detector" in a._thick_status.cget("text")

    assert a.xlabel_v.get() == a._vlabel()
    assert "Optical thickness" in a.ylabel_v.get()

    # the 3D ridge must never hijack this mode
    a.wf_mode.set("3D ridge")
    a._redraw_now()
    assert a.ax.name != "3d"
    assert not a._wf3d_active()
    a.wf_mode.set("off")

    # the decompression branch takes the D style here too
    _mark_d(a, ["4.00 GPa"])
    a.decomp_style.set("dotted")
    a._redraw_now()
    styles = [ln.get_linestyle() for ln in a.ax.get_lines()
              if ln.get_marker() == "o"]
    assert "-" in styles and ":" in styles

    with offscreen(a):
        a._thickness_table()
        win = [w for w in ROOT.winfo_children()
               if isinstance(w, tk.Toplevel)][-1]
        win.update_idletasks()
        tv = [w for w in win.winfo_children()
              if isinstance(w, ttk.Treeview)][0]
        trows = tv.get_children()
        assert len(trows) == 4
        assert [tv.item(r, "values") for r in trows][2][2] == "-"  # the miss
        win.destroy()

    a.mode.set("overlay")
    assert a._nt_cache                    # the gates own the cache
    a._notch_params_changed()
    assert not a._nt_cache


# ---------------------------------------------------------------------------
# t as a plottable quantity
# ---------------------------------------------------------------------------
def test_t_is_supplied_per_trace_and_alpha_plots_without_guessing(a):
    """The t column is a CONSTANT column over the trace's own grid (so it
    divides a spectrum with no shape rules of its own), it is NaN on a
    trace with no confident fringe, and the alpha builtin then draws a gap
    there instead of inventing a number."""
    _reset_decomp(a)
    _load(a)
    good = next(r for r in a.results if r["pressure_val"] == 1.0)
    miss = next(r for r in a.results if r["pressure_val"] == 3.0)
    cg = a._formula_columns(good, {"t"})
    cm = a._formula_columns(miss, {"t"})
    assert cg["t"].shape == good["wl"].shape
    assert abs(float(cg["t"][0]) - NT_NM * 1e-3) < 0.5
    assert np.isnan(cm["t"]).all()
    # a formula that never mentions t must not pay for the detection
    assert "t" not in a._formula_columns(good, {"A"})

    q = next(x for x in a.quantities
             if x["name"] == "Absorption coefficient")
    a._qty_sel.set(q["key"])
    a._on_qty_row_pick()
    ROOT.update_idletasks()
    a._redraw_now()
    qmap = a._qty_map(a._shown())
    assert qmap is not None and len(qmap) == 4
    finite = {lbl: bool(np.isfinite(v).any()) for lbl, v in qmap.items()}
    assert finite["1.00 GPa"] is True
    assert finite["3.00 GPa"] is False            # NaN t -> a gap, not a guess


# ---------------------------------------------------------------------------
# decompression lists (Phase C): the user-supplied CSV that flags D traces
# on a dataset whose file names carry no _D tag
# ---------------------------------------------------------------------------
def test_the_dlist_parser_reads_every_shape_these_files_come_in():
    """Pure classmethod, no App: one loop over the spellings, because the
    rule is 'be tolerant', not 'be tolerant about commas'."""
    p = app.App._parse_dlist
    nine = [0, 0.3, 7.1, 11.2, 18.8, 26, 35, 43.1, 46.5]

    # the real fixture: June2026/Arch29 D List.csv
    assert p("pressure_GPa\n0\n0.3\n7.1\n11.2\n18.8\n26\n35\n43.1\n46.5\n") \
        == nine
    for text in (
            "\n".join(str(v) for v in nine),                  # bare column
            "PRESSURE_GPA\r\n" + "\r\n".join(str(v) for v in nine),
            '"pressure_gpa"\n' + "\n".join('"%s"' % v for v in nine),
            "p_gpa;" + ";".join("x" for _ in range(2)) + "\n"
            + "\n".join("%s;9;9" % v for v in nine),
            "gpa\t junk\n" + "\n".join("%s\t 42" % v for v in nine)):
        assert p(text) == nine, text[:40]

    # a named column is the ONLY column read: a second numeric column (a
    # temperature, a run number) must not be taken for pressures
    assert p("run,pressure_GPa,T_K\n1,7.1,300\n2,18.8,300\n") == [7.1, 18.8]
    # with no header every number counts, and 'p' stands in for the point
    assert p("18p8\n26\n") == [18.8, 26.0]
    # rubbish is dropped, never guessed at
    assert p("") == []
    assert p("pressure_GPa\nabc\n-\n7.1\n") == [7.1]


def test_the_dlist_match_is_nearest_unique_and_reports_what_it_missed(a):
    """Every (value, trace) pair inside the tolerance, best first, both
    sides dropping out once used -- that is what stops two listed values
    from claiming one trace between them."""
    _reset_decomp(a)
    _load(a)                       # traces at 1.0, 2.0, 3.0, 4.0
    hits, misses = a._match_dlist([2.0, 4.0])
    assert sorted(lbl for _v, lbl, _d in hits) == ["2.00 GPa", "4.00 GPa"]
    assert misses == []

    # inside the tolerance, and off by less than a hair
    hits, misses = a._match_dlist([2.02])
    assert [lbl for _v, lbl, _d in hits] == ["2.00 GPa"]
    assert hits[0][2] == pytest.approx(0.02)

    # two values that straddle ONE trace: the nearer takes it, the other
    # is reported as a miss rather than doubling up
    hits, misses = a._match_dlist([1.98, 2.03])
    assert len(hits) == 1 and hits[0][0] == 1.98
    assert misses == [2.03]

    # outside the tolerance nothing is guessed
    assert a._match_dlist([9.9]) == ([], [9.9])
    assert a._match_dlist([2.0], tol=0.0)[0] == [(2.0, "2.00 GPa", 0.0)]


def test_applying_a_dlist_moves_the_branch_and_survives_a_rebuild(a):
    """The D checkbox IS the manual branch, so one apply has to reach the
    legend tag, the Thickness plot's split and every other consumer -- and
    the stored list has to come back on the next rebuild."""
    _reset_decomp(a)
    _load(a)
    _mark_d(a, [])
    assert {r["label"]: a._branch_of(r) for r in a.results} == {
        "1.00 GPa": "C", "2.00 GPa": "C", "3.00 GPa": "C", "4.00 GPa": "C"}

    hits, misses = a._apply_dlist([2.0, 4.0], source="Arch29 D List.csv")
    assert len(hits) == 2 and misses == []
    assert a._branch_of(a.results[1]) == "D"
    assert a._branch_of(a.results[3]) == "D"
    assert a._branch_of(a.results[0]) == "C"

    # a list is silent about what it does not mention: an auto-detected _D
    # name is evidence of its own and must not be cleared
    a.dvars["1.00 GPa"].set(True)
    a._apply_dlist([2.0], announce=False)
    assert a._branch_of(a.results[0]) == "D"

    # stored per {DAC}_{Sample}, re-applied where the D vars are born
    was = a.settings.get("fr_dlists")
    try:
        _mark_d(a, [])
        a.settings["fr_dlists"] = {a._dlist_key(): {"pressures": [2.0, 4.0]}}
        a._build_trace_checks()
        ROOT.update_idletasks()
        assert a._branch_of(a.results[1]) == "D"
        assert a._branch_of(a.results[3]) == "D"
    finally:
        if was is None:
            a.settings.pop("fr_dlists", None)
        else:
            a.settings["fr_dlists"] = was
        _mark_d(a, [])


def test_all_four_builtins_reach_the_panel_the_selector_and_the_plot(a):
    """The shipped formula set, pinned end to end.

    Reported as "the two new builtins do not appear in the formula
    selector", which is exactly what a STALE build looks like: the v1.4.8
    package carries a two-entry BUILTINS and no t column.  Nothing between
    the registry and the Y picker may drop one, so the whole chain is
    asserted here rather than trusted.
    """
    want = ["Absorbance", "Transmittance", "Absorption coefficient", "A/t"]
    assert [q["name"] for q in F.BUILTINS] == want
    assert all(F.is_builtin(q) for q in F.default_quantities())

    # ... they survive _load_quantities, whatever settings hold
    was = a.settings.get("quantities")
    try:
        a.settings["quantities"] = [
            {"name": "Mine", "expr": "A * 2", "unit": "", "latex": "",
             "key": "Mine"}]
        loaded = a._load_quantities()
        assert [q["name"] for q in loaded][:4] == want
        assert loaded[-1]["name"] == "Mine"
    finally:
        if was is None:
            a.settings.pop("quantities", None)
        else:
            a.settings["quantities"] = was

    # ... they are all rows in the panel, all four typeset, all locked
    a._refresh_quantity_rows()
    ROOT.update_idletasks()
    rows = {k for k, _blk, _m in a._qty_rows}
    keys = {q["key"] for q in a.quantities if F.is_builtin(q)}
    assert keys <= rows, keys - rows
    for q in a.quantities:
        if not F.is_builtin(q):
            continue
        assert q["latex"], q["name"]
        assert F.mathtext_problems(q["latex"]) == [], q["name"]

    # ... and picking either NEW one arms the Y pickers with its token
    for q in [x for x in a.quantities
              if x["name"] in ("Absorption coefficient", "A/t")]:
        a._qty_sel.set(q["key"])
        a._on_qty_row_pick()
        quiesce(a)                       # the pick queues a repaint we skip
        assert a.active_qty.get() == q["key"], q["name"]
        assert a.ydata.get() == "formula: " + q["name"], q["name"]
        for cb in a._ydata_combos:
            assert a.ydata.get() in list(cb.cget("values")), q["name"]
    a._qty_sel.set("")
    a.active_qty.set("")
    a.ydata.set("absorbance")
    quiesce(a)


def test_3d_shape_mode_surface_detail_the_stl_gate_and_the_colormap_arrows(a):
    """R1a. The fourth waterfall mode and the two controls beside it.

    "3D shape" is the Surface look promoted to a mode: it draws the
    continuous sheet without touching the 3D look, every 3D branch reaches
    it through `_wf_is3d`, and Surface detail scales the live quad budget
    without ever lifting a Performance-mode session over the normal
    default. The STL export reads the DATA, not the mode, so it is live
    whenever three traces are shown. The colormap arrows walk the list the
    dropdown is SHOWING, so a filter narrows them with it.
    """
    import colormaps
    import export3d

    assert app.WF_MODES == ["off", "2D stacked", "3D ridge", "3D shape"]
    assert app.WF_3D == ("3D ridge", "3D shape")
    for mode, is3 in (("off", False), ("2D stacked", False),
                      ("3D ridge", True), ("3D shape", True)):
        a.wf_mode.set(mode)
        assert a._wf_is3d() is is3, mode
    a.wf_mode.set("off")
    assert a.root.bind("<Key-4>"), "key 4 must pick the new mode"
    assert "wf3d_surf_detail" in a._preset_registry()

    budgets = {}
    for perf in (False, True):
        a.perf_mode.set(perf)
        for step in ("draft", "auto", "fine"):
            a.wf3d_surf_detail.set(step)
            budgets[(perf, step)] = a._surface_max_cells()
    a.perf_mode.set(False)
    a.wf3d_surf_detail.set("auto")
    assert (budgets[(False, "draft")] < budgets[(False, "auto")]
            < budgets[(False, "fine")]), budgets
    assert budgets[(False, "auto")] == export3d.DEFAULT_MAX_CELLS, budgets
    for step in ("draft", "auto", "fine"):
        assert budgets[(True, step)] <= export3d.DEFAULT_MAX_CELLS, budgets

    _load(a)
    try:
        look = a.wf3d_look.get()
        a.wf_mode.set("3D shape")
        a._redraw_now()
        quiesce(a)
        kinds = [type(c).__name__ for c in a.ax.collections]
        assert any("Poly3D" in k for k in kinds), kinds
        assert a.wf3d_look.get() == look, "the mode must not rewrite the look"
        assert str(a._stl_btn.cget("state")) == "normal"

        for v in a.trace_vars.values():
            v.set(False)
        a._update_status()
        assert str(a._stl_btn.cget("state")) == "disabled"
        for v in a.trace_vars.values():
            v.set(True)
        a._update_status()
    finally:
        a.wf_mode.set("off")
        quiesce(a)

    vals = list(colormaps.available())
    a.cmap.set(vals[0])
    a._step_cmap(1)
    assert a.cmap.get() == vals[1], a.cmap.get()
    a._step_cmap(-1)
    a._step_cmap(-1)
    assert a.cmap.get() == vals[-1], "the list wraps"
    a.cmap.set(vals[0])
    a.cmap_filter.set("bat")
    ROOT.update_idletasks()
    shown = [str(v) for v in a.cmap_cb.cget("values")]
    a.cmap.set(shown[0])
    a._step_cmap(1)
    assert a.cmap.get() in shown, (a.cmap.get(), shown)
    a.cmap_filter.set("")
    ROOT.update_idletasks()
    a.cmap.set(vals[0])
    for nm in ("_cmap_prev_btn", "_cmap_next_btn",
               "_qa_cmap_prev", "_qa_cmap_next"):
        b = getattr(a, nm, None)
        assert b is not None, nm
        im = b.cget("image")
        if isinstance(im, (tuple, list)):
            im = im[0] if im else ""
        assert str(im), nm + " must carry a drawn glyph"
    row = a._cmap_prev_btn.master
    classes = [w.winfo_class() for w in row.winfo_children()]
    assert classes.count("TButton") == 2 and "TCombobox" in classes, classes


# ---------------------------------------------------------------------------
# R8: bicolor ("honeybee") D traces
# ---------------------------------------------------------------------------
def test_bicolor_is_two_artists_a_second_ink_and_a_dashed_legend_key(a):
    """'bicolor' draws the D branch as a solid base in the trace's own
    color with an evenly dashed overlay in a second ink. Everything that
    cannot stack two artists still sees the historical dashed."""
    _reset_decomp(a)
    _load(a)
    _mark_d(a, ["4.00 GPa"])
    a.mode.set("overlay")
    a.show_smooth.set(False)
    a.lw.set(1.0)

    assert "bicolor" in list(a._decomp_style_cb.cget("values"))
    assert "decomp_color2" in a._preset_registry()
    assert not a._bicolor_on()
    assert a._decomp_c2_row.winfo_manager() != "pack"

    # R14 reversed the R9a 'Advanced' fold: every row of the section is
    # visible, and Second color packs itself after Pattern.
    a.decomp_style.set("bicolor")
    a.decomp_color2.set("auto")
    a._sync_decomp_row()
    a.root.update_idletasks()
    assert a._bicolor_on()
    assert a._decomp_c2_row.winfo_manager() == "pack", \
        "Second color must appear"
    assert a._decomp_ls() == "--", "the no-second-artist fallback"

    a._redraw_now()
    lines = _lines_by_label(a)
    d, c = lines["4.00 GPa"], lines["1.00 GPa"]
    tw = getattr(d, "_sparta_bi", None)
    assert tw is not None, "the D trace must carry its overlay"
    assert getattr(c, "_sparta_bi", None) is None, "C is never striped"
    assert d.get_linestyle() in ("-", "solid")
    on, off = tw._dash_pattern[1][:2]
    assert abs(on - off) < 1e-9, "the two inks share the curve 50/50"
    assert on >= 2.9, "never collapses to a dotted line"
    assert abs(tw.get_linewidth() - d.get_linewidth()) < 1e-9
    assert tw.get_marker() in ("None", "", None), "no doubled markers"
    assert tw.get_color() != d.get_color()

    # dash length follows the line width, and matplotlib's own lw scaling
    # is divided back out so it does not grow as the square of it
    seen = {}
    for w in (0.8, 2.5):
        a.lw.set(w)
        a._redraw_now()
        _t = _lines_by_label(a)["4.00 GPa"]._sparta_bi
        seen[w] = _t._dash_pattern[1][0]
    assert seen[0.8] < seen[2.5] <= 11.0, seen
    a.lw.set(1.0)

    # a named second ink is honored; nonsense falls back rather than blanks
    a.decomp_color2.set("#ff00ff")
    a._redraw_now()
    assert _lines_by_label(a)["4.00 GPa"]._sparta_bi.get_color() == "#ff00ff"
    a.decomp_color2.set("not-a-color")
    a._redraw_now()
    assert _lines_by_label(a)["4.00 GPa"]._sparta_bi.get_color()
    a.decomp_color2.set("auto")

    # the legend key must not lie: hatched box, or the real artist pair
    a.legend_on.set(True)
    a.colorbar_on.set(False)
    a.auto_key.set(False)
    a.legend_swatch.set("color box")
    a._redraw_now()
    hs = list(getattr(a.ax.get_legend(), "_sparta_handles", []) or [])
    assert any(getattr(h, "get_hatch", lambda: None)() for h in hs)
    a.legend_swatch.set("line")
    a._redraw_now()
    hs = list(getattr(a.ax.get_legend(), "_sparta_handles", []) or [])
    assert any(isinstance(h, tuple) for h in hs)
    a.legend_swatch.set("color box")

    # switching away withdraws the row and puts the plain dash back
    a.decomp_style.set("dashed")
    a._sync_decomp_row()
    a.root.update_idletasks()
    assert a._decomp_c2_row.winfo_manager() != "pack"
    a._redraw_now()
    assert getattr(_lines_by_label(a)["4.00 GPa"], "_sparta_bi", None) is None
    _reset_decomp(a)
    quiesce(a)
