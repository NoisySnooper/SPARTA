"""QoL batch tests (v1.4.8 / v1.4.9).

Locks the settings-backed defaults (journal preset, last export format),
Escape dismissal on every dialog that grew one, the double-click sash reset,
the recent-folder dropdown wiring, the data-drawer combobox identity map,
the drawn primaries, where the round-3 controls now live, and the icon /
theme self-heal passes.

Two grouping rules drive the shape of this file, because both are worth
seconds each:

* a THEME SWITCH costs ~1.9 s (it regenerates every icon and every typeset
  formula), so everything that has to survive one is asserted inside a
  single walk over the themes;
* REALIZING the root (giving it real geometry and mapping it off-screen)
  forces a full relayout, so every pixel-shaped assertion shares one
  ``realized()`` block.

Dialogs are opened for real and forced off-screen at +3200+100: a test run
must never flash a window at the user.  Runs against the suite's ONE shared
App (tests/conftest.py).
"""
import contextlib
import json
import math
import re
import time

import pytest

import app
import tkinter as tk
import tkinter.font as tkfont
from tkinter import ttk
from conftest import (OFF, ROOT, gui, img, kids, make_result, offscreen,
                      open_dialog, realized, shared_app, walk)

USES_APP = True
pytestmark = gui


@pytest.fixture(scope="module")
def a():
    return shared_app()


def _res(label, pval):
    return make_result(label, pval, n=40, pstr=label.split()[0])


def _load(a, results, dest="d"):
    a._finish_run([dict(r) for r in results], [], dest)


def _body(a, title):
    return [r for r in a._collapsibles if r["key"] == title][0]["body"]


def _inside(box, w):
    while w is not None:
        if w is box:
            return True
        w = getattr(w, "master", None)
    return False


# ---- items 7 / 12: the settings-backed defaults -----------------------------
def test_journal_preset_and_export_format_defaults_round_trip(a):
    """Both remember the last pick, both reach the settings FILE, and both
    fall back cleanly when the stored value means nothing."""
    a.fig_preset.set("custom")
    a._set_fig_preset_default()
    assert a.settings["fig_preset_default"] == "custom"
    assert "Current is the default" in a.fig_preset_default_btn.cget("text")

    a.fig_preset.set("Nature single (89 mm)")
    ROOT.update_idletasks()
    # the star clears the moment the live pick and the saved default differ
    assert a.fig_preset_default_btn.cget("text") == "Set as default"
    a._set_fig_preset_default()
    assert "Current is the default" in a.fig_preset_default_btn.cget("text")
    with open(app.SETTINGS_PATH) as f:
        assert json.load(f)["fig_preset_default"] == "Nature single (89 mm)"
    assert a._load_settings()["fig_preset_default"] == "Nature single (89 mm)"
    # the build reads the same key the Set-as-default button writes
    a.settings["fig_preset_default"] = "APS 2-col (7.0 in)"
    assert a.settings.get("fig_preset_default", "custom") == "APS 2-col (7.0 in)"
    a.fig_preset.set("custom")
    a._set_fig_preset_default()

    a.settings.pop("last_export_ext", None)
    dext, types = a._export_types()
    assert dext == ".png" and types[0][0] == "PNG"
    assert a._remember_export_ext(".SVG") is True
    assert a.settings["last_export_ext"] == "svg"
    with open(app.SETTINGS_PATH) as f:
        assert json.load(f)["last_export_ext"] == "svg"
    dext, types = a._export_types()
    assert dext == ".svg"
    assert types[0] == ("SVG", "*.svg")
    assert len(types) == 5 and len(set(types)) == 5   # nothing lost
    assert a._remember_export_ext("docx") is False    # junk is ignored
    assert a.settings["last_export_ext"] == "svg"
    a.settings["last_export_ext"] = "nonsense"
    dext, types = a._export_types()
    assert dext == ".png" and types[0][0] == "PNG"    # unknown -> png
    a.settings.pop("last_export_ext", None)


# ---- items 3 / 9: Escape dismisses every dialog ----------------------------
def test_escape_binding_on_every_dialog_that_grew_one(a):
    _load(a, [_res("1.00 GPa", 1.0), _res("2.00 GPa", 2.0)])
    with offscreen(a):
        for opener, args in ((a._about, ()),
                             (a._open_smooth_panel, ()),
                             (a._show_readout_table, (700.0,))):
            w = open_dialog(opener, *args)
            try:
                assert w.bind("<Escape>"), opener.__name__
            finally:
                w.destroy()


def test_escape_binding_on_name_format_and_fix(a, tmp_path):
    """The editor AND its Fix sub-dialog; Escape on the sub-dialog must
    close only the sub-dialog (the bind lives on that Toplevel)."""
    for nm in ("vis_D42_fo90_0p5_s.001", "vis_D42_fo90_0p5_bg.002"):
        (tmp_path / nm).write_text("")
    a.in_var.set(str(tmp_path))
    with offscreen(a):
        d = open_dialog(a._open_name_format)
        try:
            assert d.bind("<Escape>")
            tvs = kids(d, "Treeview")
            fixb = kids(d, "TButton", "Fix selected")
            rows = tvs[0].get_children() if tvs else []
            assert rows and fixb, "preview rows / Fix button missing"
            tvs[0].selection_set(rows[0])
            before = set(str(x) for x in d.winfo_children())
            fixb[0].invoke()
            ROOT.update_idletasks()
            fd = [x for x in d.winfo_children()
                  if str(x) not in before and x.winfo_class() == "Toplevel"]
            assert fd, "Fix sub-dialog did not open"
            assert fd[-1].bind("<Escape>")
            fd[-1].destroy()
            ROOT.update_idletasks()
            assert d.winfo_exists()     # parent survives the sub-dialog
        finally:
            try:
                d.grab_release()
            except tk.TclError:
                pass
            d.destroy()


# ---- item 15: data-drawer combobox identity map ----------------------------
def test_drawer_labels_are_an_identity_map_that_survives_a_unit_change(a):
    """What the drawer SHOWS follows the Variable; what it RESOLVES to is
    always the same frozen engine record."""
    _load(a, [_res("1.00 GPa", 1.0), _res("2.00 GPa", 2.0),
              _res("3.00 GPa", 3.0)])
    a._toggle_drawer(True)
    try:
        ROOT.update_idletasks()
        raw = [r["label"] for r in a.results]
        assert list(a._drawer_combo.cget("values")) == raw
        assert a._drawer_map == dict(zip(raw, raw))

        a.drawer_trace.set("2.00 GPa")
        assert a._drawer_record()["label"] == "2.00 GPa"
        a.xvar_choice.set("Temperature (K)")
        ROOT.update_idletasks()
        assert list(a._drawer_combo.cget("values")) == ["1.00 K", "2.00 K",
                                                        "3.00 K"]
        assert a.drawer_trace.get() == "2.00 K"      # selection followed
        # ...and still points at the same RECORD, whose label never moved
        assert a._drawer_record()["label"] == "2.00 GPa"
        a.drawer_trace.set("3.00 K")
        assert a._drawer_record()["label"] == "3.00 GPa"
        a._refresh_drawer()                          # must not raise
    finally:
        a._toggle_drawer(False)


# ---- item 1: the recent-folder dropdown is wired up ------------------------
def test_folder_menu_wiring(a):
    a.settings["recent_in"] = [r"C:\data\runA", r"C:\data\runB"]
    m = a._folder_menu_items("in")
    try:
        assert m.entrycget(0, "label") == "Open in Explorer"
        assert m.index("end") == 3                   # cmd, sep, 2 recents
        assert m.entrycget(3, "label") == r"C:\data\runB"
        m.invoke(2)                                  # pick the first recent
        assert a.in_var.get() == r"C:\data\runA"
        assert a.settings["recent_in"][0] == r"C:\data\runA"
    finally:
        m.destroy()
        a.in_var.set("")

    long_path = "C:\\data\\" + ("x" * 90)
    a.settings["recent_in"] = [long_path]
    m = a._folder_menu_items("in")
    try:
        assert m.entrycget(2, "label").startswith("...")
        assert len(m.entrycget(2, "label")) == 60
    finally:
        m.destroy()
        a.settings["recent_in"] = []

    # no recents at all: just the Explorer entry, no dangling separator
    a.settings["recent_out"] = []
    m = a._folder_menu_items("out")
    try:
        assert m.index("end") == 0
    finally:
        m.destroy()

    # the affordances that reach the menu
    assert a._recent_in_btn.cget("text") == "\u25be"
    assert a._recent_out_btn.cget("text") == "\u25be"
    assert a._in_entry.bind("<Button-3>")
    assert a._out_entry.bind("<Button-3>")


# ---- v1.4.8: the Name-format dialog follows the experiment Variable -------
def test_name_format_chips_display_map_round_trip(a, tmp_path):
    """The chip dropdowns SHOW the experiment variable's name wherever they
    show 'pressure' by default, but the stored order stays canonical and a
    profile saved under Temperature is byte-identical to one saved under
    Pressure."""
    for nm in ("vis_D42_fo90_0p5_s_c.001", "vis_D42_fo90_0p5_bg_c.002"):
        (tmp_path / nm).write_text("")
    a.in_var.set(str(tmp_path))
    orig_ask = app.simpledialog.askstring
    app.simpledialog.askstring = lambda *_a, **_k: "chipmap"

    def _shot(choice):
        a.xvar_choice.set(choice)
        with offscreen(a):
            d = open_dialog(a._open_name_format)
            try:
                # "Save as..." turns the built-in into an editable profile,
                # which is what builds the chip strip
                kids(d, "TButton", "Save as")[0].invoke()
                ROOT.update_idletasks()
                tv = kids(d, "Treeview")[0]
                heads = [tv.heading(c, "text") for c in tv.cget("columns")]
                chips = [w for w in kids(d, "TCombobox")
                         if "dac" in (w.cget("values") or ())]
                shown = [w.get() for w in chips]
                values = list(chips[0].cget("values"))
                labs = [w.cget("text") for w in kids(d, "Label")
                        if str(w.cget("text")).endswith(" decimal")]
                prof = [p for p in a._profiles()
                        if p.get("name") == "chipmap"][-1]
                blob = json.dumps(prof, sort_keys=True)
                order = list(prof.get("order", []))
            finally:
                try:
                    d.grab_release()
                except tk.TclError:
                    pass
                d.destroy()
                ROOT.update_idletasks()
                pl = a._profiles()
                pl[:] = [p for p in pl if p.get("name") != "chipmap"]
        return heads, shown, values, labs, blob, order

    try:
        p_heads, p_shown, p_vals, p_labs, p_blob, p_order = \
            _shot("Pressure (GPa)")
        t_heads, t_shown, t_vals, t_labs, t_blob, t_order = \
            _shot("Temperature (K)")
    finally:
        app.simpledialog.askstring = orig_ask
        a.xvar_choice.set("Pressure (GPa)")
        a.in_var.set("")

    canonical = ["dac", "sample", "pressure", "role", "branch", "rep"]
    # what is SHOWN follows the variable ...
    assert p_shown == canonical
    assert t_shown == ["dac", "sample", "temperature", "role", "branch", "rep"]
    assert "temperature" in t_vals and "pressure" not in t_vals
    assert (p_heads[3], t_heads[3]) == ("Pressure", "Temperature")
    assert p_labs == ["Pressure decimal"]
    assert t_labs == ["Temperature decimal"]
    # ... and everything STORED stays canonical
    assert p_order == canonical
    assert t_order == canonical
    assert p_blob == t_blob


# ---- v1.4.8 round 3: where every control now lives -------------------------
def test_moved_controls_live_in_their_new_homes(a):
    pm, tr, ex = _body(a, "Plot mode"), _body(a, "Traces"), _body(a, "Export")
    # the Variable row and the Auto-rescan controls now open the Plot mode box
    rows = pm.winfo_children()
    assert _inside(pm, a._xvar_combo)
    assert _inside(rows[0], a._xvar_combo)              # first row
    assert _inside(pm, a._auto_rescan_sw)
    assert _inside(pm, a._rescan_spin)
    assert _inside(rows[1], a._auto_rescan_sw)          # second row
    assert not _inside(a.left, a._auto_rescan_sw)
    assert [w.cget("text") for w in kids(rows[1], "Label")] == \
        ["Auto rescan", "every", "s"]
    # R19: the branch-tagged CSVs are a tick in EXPORT > DATA FILES,
    # so Traces keeps only its own D-list export, and the one export
    # button on the Export tab lives in Data files, not in Export
    assert not hasattr(a, "_cd_export_btn")
    assert [w.cget("text") for w in tr.winfo_children()
            if w.winfo_class() == "TButton"] == \
        ["Export D list (CSV) by selection"]
    assert not _inside(ex, a._export_data_btn)
    # PANEL_GUIDE points at the new homes. Headings are "TAB > SECTION"
    # now, so the Auto-rescan text has to sit inside the PLOT > PLOT MODE
    # block (the guide's sections are separated by a blank line).
    assert "PLOT > PLOT MODE\n" in app.PANEL_GUIDE
    _pm = app.PANEL_GUIDE.split("PLOT > PLOT MODE\n", 1)[1].split("\n\n", 1)[0]
    assert "Auto rescan" in _pm
    # R19 moved the branch-tagged writer the other way: it is no longer a
    # button in Traces that the guide points AT, it is a row of the new
    # EXPORT > DATA FILES section, and the DATA > TRACES block points at
    # it.  Both ends are pinned so the pair cannot drift.
    # R20 merged the products into ONE CSV per trace, so that row now names
    # the FILE NAME rule and reads 'C/D tag in file name'.  The retired
    # label is pinned absent as well, and the live one is matched over
    # collapsed whitespace because the guide wraps at 72 columns.
    assert "EXPORT > DATA FILES\n" in app.PANEL_GUIDE
    _tr = app.PANEL_GUIDE.split("DATA > TRACES\n", 1)[1].split("\n\n", 1)[0]
    assert "EXPORT >" in " ".join(_tr.split())
    assert "C/D tag in file name" in " ".join(app.PANEL_GUIDE.split())
    assert "C/D-tagged CSV" not in app.PANEL_GUIDE
    # R12 (STE100): the guide spells a definition with a colon, never
    # with the " - " prose dash the register bans.
    assert "Branch tags:" in app.PANEL_GUIDE

    # the spine controls share one box, Text color stays in Colors
    fg, ax, col = (_body(a, "Frame & grid"), _body(a, "Axis"),
                   _body(a, "Colors & colormap"))
    lw = [w for w in walk(ROOT) if w.winfo_class() == "TEntry"
          and str(w.cget("textvariable")) == str(a.spine_lw)][0]
    acol = [w for w in walk(ROOT) if w.winfo_class() == "TCombobox"
            and str(w.cget("textvariable")) == str(a.axis_color)][0]
    tcol = [w for w in walk(ROOT) if w.winfo_class() == "TCombobox"
            and str(w.cget("textvariable")) == str(a.text_color)][0]
    assert _inside(fg, lw) and not _inside(ax, lw)
    assert _inside(fg, acol) and not _inside(col, acol)
    assert _inside(col, tcol)
    assert "Spines" in [str(w.cget("text")) for w in walk(fg)
                        if w.winfo_class() == "Label"]

    # R10: the Defringe section is gone entirely. The df switch survives
    # as a variable (Quick Access owns the box); every parameter it uses
    # now comes from the fringe workbench, with or without its widgets.
    assert hasattr(a, "show_notch")
    for gone in ("notch_width", "notch_nt_min", "notch_nt_max",
                 "notch_pmax", "suppress_fringe_report"):
        assert not hasattr(a, gone), gone
    assert "df_adv_collapsed" not in a._ccards
    assert "Defringe" not in [rec["key"] for rec in a._collapsibles]
    kw = a._notch_params()
    assert set(kw) == {"halfwidth_um", "nt_min_nm", "nt_max_nm",
                       "pvalue_max"}
    assert kw["halfwidth_um"] > 0 and kw["nt_min_nm"] < kw["nt_max_nm"]


def test_the_deleted_controls_are_really_gone_and_the_pickers_are_singular(a):
    """Round 3 removed five buttons, collapsed the Y-data picker to one home
    plus Quick Access, and turned the zoom axis into a readonly combobox."""
    labels = [str(w.cget("text")) for w in walk(a.right_outer)
              if w.winfo_class() == "TButton"]
    for gone in ("Auto fit", "Expand all", "Apply ticks", "Sync H from V",
                 "Reset all to defaults"):
        assert gone not in labels, gone
    assert "Apply limits" in labels and "Reset axes" in labels
    assert labels.count("Auto") == 2         # Ticks and Waterfall keep theirs
    assert not hasattr(app.App, "_reset_defaults")
    assert not hasattr(app.App, "_sync_marker_style")

    cbs = [w for w in walk(ROOT) if w.winfo_class() == "TCombobox"
           and str(w.cget("textvariable")) == str(a.zoom2d_axis)]
    assert len(cbs) == 1
    assert list(cbs[0].cget("values")) == ["both", "X", "Y"]
    assert str(cbs[0].cget("state")) == "readonly"
    assert not [w for w in walk(ROOT) if w.winfo_class() == "TRadiobutton"
                and str(w.cget("variable")) == str(a.zoom2d_axis)]

    ys = [w for w in walk(ROOT) if w.winfo_class() == "TCombobox"
          and str(w.cget("textvariable")) == str(a.ydata)]
    assert len(ys) == 2
    assert "Overlay Y" not in [str(w.cget("text")) for w in walk(ROOT)
                               if w.winfo_class() == "Label"]


def test_plot_mode_radiobuttons_use_neutral_series_wording(a):
    """The mode radiobuttons must read for ANY Series variable -- including
    the v1.4.9 Thickness mode."""
    seen = {}
    for w in walk(ROOT):
        try:
            if (w.winfo_class() == "TRadiobutton"
                    and str(w.cget("variable")) == str(a.mode)):
                seen[str(w.cget("value"))] = str(w.cget("text"))
        except tk.TclError:
            continue
    assert seen == {"overlay": "Overlay all traces",
                    "inspect": "Inspect one trace",
                    "thickness": "Thickness (fringe n*t)"}, seen


# ---- round-3: primaries are drawn buttons that match a real ttk.Button ----
def test_round_buttons_match_ttk_keep_the_option_api_and_take_the_keyboard(a):
    """The accent primaries are RoundButtons whose requested height equals a
    stock ttk.Button's (+-1 px), NUKE excepted - it keeps its fixed 13 pt;
    every call site that later .config()s one keeps working; and Space /
    Return activate them from a private bindtag a Tooltip cannot wipe."""
    ROOT.update_idletasks()
    ref = app.ttk.Button(ROOT, text="Reference")
    ROOT.update_idletasks()
    th = ref.winfo_reqheight()
    ref.destroy()
    assert th > 8
    for name in ("run_btn", "profile_btn", "_data_btn"):
        b = getattr(a, name)
        assert isinstance(b, app.RoundButton), name
        assert abs(b.winfo_reqheight() - th) <= 1, \
            "%s: %d vs ttk %d" % (name, b.winfo_reqheight(), th)
    assert isinstance(a.nuke_btn, app.RoundButton)
    assert a.nuke_btn._o["radius"] == a.run_btn._o["radius"]

    b = a.run_btn
    old = b["text"]
    b.config(text="Cancel", command=a._cancel_run)
    assert b["text"] == "Cancel"
    b.config(text="Run", command=a._run, state="normal")
    assert b["text"] == "Run" and b["state"] == "normal"
    b.config(state="disabled")
    assert b["state"] == "disabled"
    b.config(state="normal")
    a._update_profile_btn()
    assert a.profile_btn["text"].strip().startswith("Name format:")
    a._update_data_btn()
    assert a._data_btn["text"].strip() in ("Data table", "Hide data")
    assert b["bg"] == a._brand()["ac1"]          # per-theme triad, still
    assert b["text"] == old

    assert str(b.cget("takefocus")) == "1"
    assert app.RoundButton.TAG in b.bindtags()
    bound = set(b.bind_class(app.RoundButton.TAG))
    for seq in ("<Key-space>", "<Key-Return>", "<Enter>", "<Leave>",
                "<Button-1>", "<ButtonRelease-1>", "<FocusIn>"):
        assert seq in bound, seq
    hits = []
    oldcmd = b["command"]
    try:
        b.config(command=lambda: hits.append(1))
        assert b._ev_key(None) == "break"
        b.config(state="disabled")
        b._ev_key(None)
        assert hits == [1]                      # disabled swallows the key
    finally:
        b.config(state="normal", command=oldcmd)


# ---- round-3: sash drag, both modes ---------------------------------------
class _Motion(object):
    def __init__(self, x_root):
        self.x_root = x_root


@contextlib.contextmanager
def _sash_probe(a, perf):
    """Count real sash_place calls, and park the paned window off-screen so
    a performance-mode ghost line can never flash at the user."""
    ROOT.update_idletasks()
    calls = []
    real = a.pw.sash_place

    def counting(i, x, y):
        calls.append((i, x))
        return real(i, x, y)

    a.pw.sash_place = counting
    a.pw.winfo_rootx = lambda: 3200
    a.pw.winfo_rooty = lambda: 100
    a.app_perf_mode.set(bool(perf))
    try:
        yield calls
    finally:
        a._sash_ghost(None)
        a._sash_drag = None
        a.app_perf_mode.set(False)
        for attr in ("sash_place", "winfo_rootx", "winfo_rooty"):
            try:
                delattr(a.pw, attr)
            except AttributeError:
                pass


def _drag(a, idx, n=40, per=0.01):
    lim = a._sash_limits(idx)
    if lim is None or lim[1] - lim[0] < n + 4:
        pytest.skip("window too narrow to drag sash %d" % idx)
    lo = lim[0] + 2
    a._start_sash_drag(a._sash_handles[idx])
    t0 = time.monotonic()
    for i in range(n):
        a._drag_sash(idx, _Motion(3200 + lo + i))
        time.sleep(per)
    return time.monotonic() - t0


def test_sash_drag_default_mode_is_throttled_live(a):
    with _sash_probe(a, perf=False) as calls:
        dur = _drag(a, 0)
        during = len(calls)
        assert a._sash_ghost_win is None         # no ghost in this mode
        a._end_sash_drag()
        assert len(calls) - during == 1, "exactly one apply on release"
        cap = math.ceil(dur / (app.SASH_LIVE_MS / 1000.0)) + 1
        assert during <= cap, "%d applies in %.3f s (cap %d)" % (during, dur,
                                                                 cap)
        assert during >= 1, "the default mode must still resize live"


def test_sash_drag_perf_mode_ghosts_applies_once_and_escape_cancels(a):
    with _sash_probe(a, perf=True) as calls:
        _drag(a, 0)
        assert calls == [], "performance mode must not relayout while dragging"
        g = a._sash_ghost_win
        assert g is not None and g.winfo_exists()
        # root-relative placement (read the requested geometry: the strip is
        # deliberately never update()d into view during a test run)
        assert int(g.geometry().split("+")[1]) >= 3200, g.geometry()
        a._end_sash_drag()
        assert len(calls) == 1, "exactly one apply on release"
        assert a._sash_ghost_win is None and not g.winfo_exists()

    with _sash_probe(a, perf=True) as calls:
        before = a.pw.sash_coord(0)[0]
        _drag(a, 0, n=6)
        g = a._sash_ghost_win
        assert g is not None
        assert a._cancel_sash_drag() == "break"
        assert a._sash_ghost_win is None and not g.winfo_exists()
        a._end_sash_drag()                       # release after Escape
        assert calls == [], "a cancelled drag must apply nothing"
        assert a.pw.sash_coord(0)[0] == before
        assert a._cancel_sash_drag() is None     # idle Escape is a no-op


def test_sash_limits_clamp_and_double_click_resets_that_pane(a):
    ROOT.update_idletasks()
    lim = a._sash_limits(0)
    if lim is None:
        pytest.skip("no sash")
    lo, hi = lim
    assert lo >= a._pane_widths()[0]
    assert a._clamp_sash(0, -9999) == lo
    assert a._clamp_sash(0, 99999) == hi
    assert a._sash_limits(9) is None

    lmin, lw, rmin, rw = a._pane_widths()
    total = a.pw.winfo_width()
    if lw + rw + 400 + 12 > total:
        pytest.skip("window narrower than the tuned defaults + center min")
    sw = int(a.pw.cget("sashwidth"))
    a.pw.sash_place(0, lw + 170, 1)
    ROOT.update_idletasks()
    assert a.pw.sash_coord(0)[0] != lw          # really dragged away
    a._reset_sash(0)
    ROOT.update_idletasks()
    assert a.pw.sash_coord(0)[0] == lw          # LEFT pane back to default
    a.pw.sash_place(1, total - 170, 1)
    ROOT.update_idletasks()
    a._reset_sash(1)
    ROOT.update_idletasks()
    # the right pane is measured off the trailing edge, not from x=0
    assert a.pw.sash_coord(1)[0] == total - rw - sw
    assert a._reset_sash(9) is None             # out-of-range is a no-op


def test_app_perf_mode_persists_in_settings_not_presets(a):
    old = bool(a.app_perf_mode.get())
    try:
        a.app_perf_mode.set(True)
        a._toggle_app_perf_mode()
        assert a.settings["app_perf_mode"] is True
        assert json.load(open(app.SETTINGS_PATH))["app_perf_mode"] is True
        a.app_perf_mode.set(False)
        a._toggle_app_perf_mode()
        assert json.load(open(app.SETTINGS_PATH))["app_perf_mode"] is False
        # app state, not a figure preset - and NOT the 3D renderer's own
        # "perf_mode" var, which keeps its registry slot
        assert "app_perf_mode" not in a._preset_registry()
        assert a._preset_registry()["perf_mode"] is a.perf_mode
        assert a.perf_mode is not a.app_perf_mode
    finally:
        a.app_perf_mode.set(old)
        a._toggle_app_perf_mode()


# ---- v1.4.8 simplicity batch ----------------------------------------------
def test_export_actions_guard_on_an_empty_tab(a):
    """Save plot / Copy figure / Batch export had no `if not self.results`,
    so a blank tab exported a 300-dpi picture of the placeholder."""
    old_results = a.results
    seen = []
    a.results = []
    a._warn = lambda t, m: seen.append((t, m))
    try:
        a._save_plot()
        a._copy_clipboard()
        a._batch_export()
    finally:
        del a._warn
        a.results = old_results
    assert [t for t, _m in seen] == ["Save plot", "Copy figure",
                                     "Batch export"]
    # the exact phrasing the six sibling actions already use
    assert {m for _t, m in seen} == {"Load data first (pick folders and Run)."}


def test_sections_toggle_is_one_flip_label_button(a):
    """One button whose label always names the next click -- and it keeps
    working across a theme apply.

    `_apply_brand` regenerates `self._icons`, which frees the PhotoImage the
    Sections button is still showing; every later `configure()` on it then
    raises TclError.  `_sync_collapse_btn` therefore stamps the IMAGE first,
    so the dead reference is cleared before the text is written.  This test
    used to call a `_heal_collapse_btn` workaround; the fix landed in the
    app, so the theme apply below is the proof and the workaround is gone."""
    assert not hasattr(a, "_expand_btn")
    a._apply_brand()                     # frees every icon the buttons hold
    ROOT.update_idletasks()
    a._collapse_all(False)
    ROOT.update_idletasks()
    assert a._collapse_btn.cget("text") == "Collapse all"
    a._toggle_collapse_all()
    ROOT.update_idletasks()
    assert a._collapse_btn.cget("text") == "Expand all"
    assert all(r["collapsed"] for r in a._collapsibles)
    a._toggle_collapse_all()
    ROOT.update_idletasks()
    assert a._collapse_btn.cget("text") == "Collapse all"
    assert not any(r["collapsed"] for r in a._collapsibles)


def test_sections_survive_collapse_cycle_and_tab_switch(a):
    """v1.4.9 R2: Collapse all / Expand all, then a tab switch, must not
    lose sections (Nhan's live shot: Data tab down to Smoothing + Traces,
    Formulas gone).

    The mechanism: five of the six pages change height while HIDDEN, a
    hidden page's canvas performs no redisplay, and without an Expose on
    re-select (the off-screen root here never gets one - same as a window
    parked past a monitor edge) the embedded content frame keeps its stale
    geometry or stays unmapped.  `_heal_tab_scroll` re-asserts the scroll
    geometry on every tab change and after every collapse pass; before it,
    this walk left whole pages empty."""
    nb = a.rnotebook
    names = [str(nb.tab(t, "text")).strip() for t in nb.tabs()]
    with realized():
        def sweep(tag):
            for i, name in enumerate(names):
                nb.select(i)
                ROOT.update()
                inner = a._tab_frames[name]
                assert inner.winfo_ismapped(), \
                    "%s: %s page content unmapped" % (tag, name)
                ih = inner.winfo_height()
                for r in a._collapsibles:
                    if r.get("cat") != name:
                        continue
                    c = r["cont"]
                    assert c.winfo_ismapped(), \
                        "%s: %s section %r unmapped" % (tag, name, r["key"])
                    assert c.winfo_y() + c.winfo_height() <= ih + 1, \
                        "%s: %s section %r clipped" % (tag, name, r["key"])
        sweep("walk1")
        sweep("walk2")
        a._collapse_all(True)
        ROOT.update()
        sweep("collapsed")
        a._collapse_all(False)
        ROOT.update()
        sweep("expanded")
        nb.select(0)


def test_xvar_custom_preset_roundtrip(a):
    """A starred name+unit pair reaches SETTINGS, the dropdown, and back."""
    old = a.settings.get("xvar_custom_presets")
    try:
        a.settings["xvar_custom_presets"] = []
        a.xvar_choice.set(app.XVAR_CUSTOM)
        a.xvar_name.set("Field")
        a.xvar_unit.set("T")
        ROOT.update_idletasks()
        assert a._xvar_star_btn.cget("text") == "\u2606"

        a._toggle_xvar_saved()
        ROOT.update_idletasks()
        assert a.settings["xvar_custom_presets"] == [["Field", "T"]]
        with open(app.SETTINGS_PATH) as f:
            assert json.load(f)["xvar_custom_presets"] == [["Field", "T"]]
        vals = list(a._xvar_combo.cget("values"))
        assert vals.index("Field (T)") > vals.index("Time (min)")
        assert vals[-1] == app.XVAR_CUSTOM      # the escape hatch stays last
        assert a._xvar_star_btn.cget("text") == "\u2605"

        # recall: a preset overwrites the pair, the saved entry restores it
        a.xvar_choice.set("Pressure (GPa)")
        ROOT.update_idletasks()
        assert (a.xvar_name.get(), a.xvar_unit.get()) == ("Pressure", "GPa")
        assert not a._xvar_custom.winfo_manager()
        a.xvar_choice.set("Field (T)")
        ROOT.update_idletasks()
        assert (a.xvar_name.get(), a.xvar_unit.get()) == ("Field", "T")
        assert a._xvar_custom.winfo_manager()   # editable AND un-starrable
        assert a._vlabel() == "Field (T)"

        a._toggle_xvar_saved()                  # the lit star removes it
        ROOT.update_idletasks()
        assert a.settings["xvar_custom_presets"] == []
        assert "Field (T)" not in list(a._xvar_combo.cget("values"))
        assert a.xvar_choice.get() == app.XVAR_CUSTOM
    finally:
        if old is None:
            a.settings.pop("xvar_custom_presets", None)
        else:
            a.settings["xvar_custom_presets"] = old
        a.xvar_choice.set("Pressure (GPa)")
        ROOT.update_idletasks()


def test_reference_lines_rename_and_settings_migration(a):
    keys = [r["key"] for r in a._collapsibles]
    assert "Reference lines" in keys
    assert "Reference guides" not in keys
    old = a.settings
    try:
        a.settings = {"collapsed": {"Reference guides": True, "Axis": False},
                      "fig_preset_default": "wide (10 x 4 in)"}
        a._migrate_settings()
        assert a.settings["collapsed"] == {"Reference lines": True,
                                           "Axis": False}
        assert a.settings["fig_preset_default"] == "Wide (10 x 4 in)"
    finally:
        a.settings = old


def test_theme_dropdown_grouping_and_divider_guard(a):
    vals = list(a._theme_combo.cget("values"))
    # the functional block, then the divider. R9a retired the two
    # Dyslexic themes (the face is an App font now, ui_prefs.APP_FONTS)
    # and added Colorblind Safe Dark.
    assert vals[:6] == ["Standard Light", "Kinda Dark", "Black Hole",
                        "High Contrast", "Colorblind Safe",
                        "Colorblind Safe Dark"]
    assert not [v for v in vals if "Dyslexic" in v]
    assert vals[6] == app.THEME_DIVIDER
    assert app.THEME_DIVIDER not in app.THEME_LABELS.values()
    before = a.theme_mode.get()
    a._theme_combo.set(app.THEME_DIVIDER)
    a._theme_combo._to_code()
    ROOT.update_idletasks()
    assert a.theme_mode.get() == before                 # no theme switch
    assert a._theme_combo.get() == app.THEME_LABELS[before]


def test_auto_rescan_shows_in_the_status_bar(a):
    a.auto_rescan.set(True)
    a.rescan_interval.set(45)
    a._update_status()
    assert "auto-rescan: 45 s" in a.status_lbl.cget("text")
    a.auto_rescan.set(False)
    a._update_status()
    assert "auto-rescan" not in a.status_lbl.cget("text")
    a._cancel_auto_rescan()


def test_app_text_size_moved_into_the_settings_panel(a):
    """R14 A3 moved the size box off the bar and into the gear's panel.

    The VARIABLE is still born with the rest of the chrome, so everything
    that reads it works before the panel is ever opened; the widget is
    built with the panel. test_r14.py covers the panel itself."""
    assert a._ui_size_pick.get() in (["auto"]
                                     + [str(i) for i in range(3, 16)])
    assert not hasattr(a, "_ui_size_cb") or not a._ui_size_cb.winfo_exists()
    assert a._settings_gear_btn.master is a.nuke_btn.master    # the top bar
    assert a._settings_gear_btn.master.master is ROOT
    old_size, old_auto = a._body_size, a._ui_font_auto
    try:
        a._ui_size_pick.set("9")
        a._on_ui_size_pick()
        a._apply_ui_size()
        assert a._body_size == 9 and a._ui_font_auto is False
        assert a.settings["ui_font_size"] == 9
        a._ui_size_pick.set("auto")
        a._on_ui_size_pick()
        a._apply_ui_size()
        assert a._ui_font_auto is True
        assert a.settings["ui_font_size"] == "auto"
        assert a._ui_size_pick.get() == "auto"
    finally:
        a._ui_font_auto = old_auto
        a._ui_size_var.set(old_size)
        a._apply_ui_size()


def test_control_shift_tab_survives_a_tk_without_iso_keysyms(a):
    """Tk 8.6.9 (what Python 3.8.10 ships) rejects <Control-ISO_Left_Tab>,
    which used to abort App.__init__ before the window ever appeared."""
    real = a.root.bind
    seen = []

    def fake(seq=None, *args, **kw):
        if seq == "<Control-ISO_Left_Tab>":
            seen.append(seq)
            raise tk.TclError('bad event type or keysym "ISO_Left_Tab"')
        return real(seq, *args, **kw)

    a.root.bind = fake
    try:
        a._bind_shortcuts()                  # must not raise
    finally:
        del a.root.bind
    assert seen == ["<Control-ISO_Left_Tab>"]


# ---- v1.4.8 polish: everything that must survive a THEME SWITCH ------------
def test_icons_glyphs_and_formula_cues_all_survive_a_theme_switch(a):
    """One walk over the themes, because each switch regenerates every icon
    and every typeset formula and costs ~1.9 s.  Asserted together: the
    notebook tab icons, the card-title hdr:: glyphs, and the three cues on
    the active formula row."""
    labels = [str(a.rnotebook.tab(t, "text")).strip()
              for t in a.rnotebook.tabs()]
    # order per v1.4.9 R1a; the strip itself is covered by
    # test_right_notebook_order_active_tab_by_name_and_the_strip_refits
    assert labels == ["Plot", "Axes", "Style", "Data", "Fringe", "Export"]
    # house rule: one space of air between the glyph and the label
    assert all(str(a.rnotebook.tab(t, "text")).startswith(" ")
               for t in a.rnotebook.tabs())
    named = [m for m in a._lf_markers
             if m.winfo_exists() and getattr(m, "_hdr_icon", None)]
    assert {getattr(m, "_hdr_icon") for m in named} >= {
        "folder", "folder_open", "log", "book"}

    a._qty_sel.set(a.quantities[0]["key"])
    a._refresh_quantity_rows()
    ROOT.update_idletasks()
    body = _body(a, "Formulas")

    def weight(blk, q):
        lab = [w for w in walk(blk) if w.winfo_class() == "Label"
               and str(w.cget("text")).startswith(q["name"])][0]
        return tkfont.nametofont(str(lab.cget("font"))).actual("weight")

    was = a.theme_mode.get()
    try:
        for th in ("dark", "highcontrast", "colorblind", "light"):
            a.theme_mode.set(th)
            ROOT.update_idletasks()
            for t in a.rnotebook.tabs():
                lab = str(a.rnotebook.tab(t, "text")).strip()
                assert "tab::" + lab in a._icons, (th, lab)
                assert str(a.rnotebook.tab(t, "image")), (th, lab)
                assert str(a.rnotebook.tab(t, "compound")) == "left", (th, lab)
            for m in named:
                assert img(m), (th, m._hdr_icon)
            # the three cues on the active formula row
            tags = [w for w in walk(body) if w.winfo_class() == "Label"
                    and str(w.cget("text")) == "on plot"]
            assert len(tags) == 1, th                    # the text carrier
            assert str(tags[0].cget("fg")).lower() \
                == str(a._brand()["ac1"]).lower(), th
            rows = {k: blk for k, blk, _m in a._qty_rows}
            uibg = str(a._theme_palette()[0]).lower()
            act = rows[a.quantities[0]["key"]]
            other = rows[a.quantities[1]["key"]]
            assert str(act.cget("bg")).lower() != uibg, th       # the tint
            assert str(other.cget("bg")).lower() == uibg, th
            assert weight(act, a.quantities[0]) == "bold", th
            assert weight(other, a.quantities[1]) == "normal", th
    finally:
        a.theme_mode.set(was)
        ROOT.update_idletasks()

    # ... and all three cues follow the radio, not the theme
    a._qty_sel.set(a.quantities[1]["key"])
    a._on_qty_row_pick()
    ROOT.update_idletasks()
    rows = {k: blk for k, blk, _m in a._qty_rows}
    uibg = str(a._theme_palette()[0]).lower()
    assert str(rows[a.quantities[1]["key"]].cget("bg")).lower() != uibg
    assert str(rows[a.quantities[0]["key"]].cget("bg")).lower() == uibg
    assert len([w for w in walk(body) if w.winfo_class() == "Label"
                and str(w.cget("text")) == "on plot"]) == 1


def test_icon_map_covers_buttons_without_breaking_any_of_them(a):
    """_iconize_buttons walks EVERY button in the window; the walk must not
    raise on any of them, and every label the map claims must come back
    wearing a glyph from the live set."""
    a._iconize_buttons()
    mine = [w for w in (getattr(a, n, None)
                        for n in ("left", "center", "right_outer"))
            if w is not None] + [a.nuke_btn.master]
    seen = []
    for rt in mine:
        for w in walk(rt):
            if w.winfo_class() == "TButton":
                seen.append((str(w.cget("text")), img(w)))
    assert len(seen) > 40, "the walk found almost no buttons"
    live = set(str(v) for v in a._icons.values())
    got = dict(seen)
    # a sample of the labels the map claims, in BOTH ellipsis spellings
    checked = 0
    for lab in ("Rescan", "New\u2026", "Edit\u2026", "Delete", "Copy log",
                "Export settings", "Reset all", "Save formula CSVs\u2026",
                "Smoothing settings...", "Save project...",
                "Open project...", "Load", "Copy figure", "Apply"):
        if lab in got:
            checked += 1
            assert got[lab], "%r lost its icon" % lab
            assert got[lab] in live, "%r wears a dead image" % lab
    assert checked >= 10, "the sample labels no longer exist"


def test_panel_toggles_are_icon_buttons_with_the_words_in_the_tooltip(a):
    for btn, tip, word in ((a.left_btn, a._left_tip, "left"),
                           (a.right_btn, a._right_tip, "right")):
        assert img(btn), "%s button has no glyph" % word
        assert str(btn.cget("compound")) == "image"
        assert not str(btn.cget("text"))
        # R14's register sweep put the plain verbs back: the tooltip
        # states the function, "Hide ..." / "Show ..."
        assert tip.text.startswith("Hide")
    assert img(a.undo_btn) and img(a.redo_btn)
    try:
        a._toggle_left()
        ROOT.update_idletasks()
        assert a._left_tip.text.startswith("Show")
        assert img(a.left_btn) == str(a._icons["panel_l_off"])
    finally:
        a._toggle_left()
        ROOT.update_idletasks()
    assert a._left_tip.text.startswith("Hide")
    assert img(a.left_btn) == str(a._icons["panel_l"])


def test_folder_cards_fold_away_and_remember_it(a):
    for key in ("in_collapsed", "out_collapsed"):
        assert key in a._ccards, key
        assert not a.settings.get(key), "%s must start expanded" % key
    # the recent-folder caret and the Name-format button live INSIDE the
    # collapsible wrap, so they come back with it
    assert _inside(a._ccards["in_collapsed"]["wrap"], a._recent_in_btn)
    assert _inside(a._ccards["in_collapsed"]["wrap"], a.profile_btn)
    assert _inside(a._ccards["out_collapsed"]["wrap"], a._recent_out_btn)
    for key in ("in_collapsed", "out_collapsed"):
        wrap = a._ccards[key]["wrap"]
        try:
            a._card_toggle(key, True)
            ROOT.update_idletasks()
            assert a.settings[key] is True
            assert not wrap.winfo_manager(), "%s did not fold" % key
        finally:
            a._card_toggle(key, False)
            ROOT.update_idletasks()
        assert a.settings[key] is False
        assert wrap.winfo_manager()
    for key in ("in_collapsed", "out_collapsed", "pg_collapsed",
                "guide_collapsed"):
        rec = a._ccards[key]
        assert list(rec["caret"].master.pack_slaves())[0] is rec["caret"], key


# ---- everything pixel-shaped, in ONE realized root -------------------------
def test_card_borders_and_the_nuke_air_at_1920(a):
    """Pixel-shaped assertions need a root with real geometry, and realizing
    the root forces a full relayout -- so all three share one block.

    (1) a collapsed card is only (top_inset + pad) tall, so its body window
    must not reach over the hairline the canvas draws at y = h - 2 (the
    grow='both' card used to, because the body height was floored at 8 px);
    (2) the same for the two folder cards in the live tree;
    (3) NUKE keeps its clear air on a 1920-wide top bar."""
    with realized("1920x1080"):
        with offscreen(a):
            win = tk.Toplevel(ROOT)
            win.geometry("420x320" + OFF)
            try:
                for grow in ("both", "x"):
                    key = "probe_%s_collapsed" % grow
                    card = a._card(win, grow=grow)
                    card.pack(fill="both", expand=(grow == "both"), pady=4)
                    card.set_title(a._lf_header(card, "Probe"))
                    body = a._collapsible_card(card, key)
                    for _i in range(3):
                        a._lbl(body, text="content line").pack(anchor="w")
                    win.update()
                    win.update_idletasks()
                    try:
                        for collapsed in (True, False):
                            a._card_toggle(key, collapsed)
                            win.update()
                            win.update_idletasks()
                            h = card.winfo_height()
                            assert h >= 8, (grow, collapsed, h)
                            top = card.coords(card._win)[1]
                            bot = top + card.body.winfo_height()
                            drawn = [card.coords(i)
                                     for i in card.find_withtag("card")
                                     if card.type(i) == "line"]
                            assert any(abs(ln[1] - (h - 2)) < 1.5
                                       for ln in drawn), \
                                "grow=%s collapsed=%s: no bottom border" \
                                % (grow, collapsed)
                            assert bot < h - 2, \
                                "grow=%s collapsed=%s: body (%.0f..%.0f) " \
                                "covers the border at %d" % (grow, collapsed,
                                                             top, bot, h - 2)
                    finally:
                        a._ccards.pop(key, None)
                        a.settings.pop(key, None)
            finally:
                win.destroy()
                ROOT.update_idletasks()

        for key in ("in_collapsed", "out_collapsed"):
            card = a._ccards[key]["card"]
            try:
                a._card_toggle(key, True)
                ROOT.update_idletasks()
                ROOT.update()
                h = card.winfo_height()
                assert h >= 8, (key, h)
                drawn = [card.coords(i) for i in card.find_withtag("card")
                         if card.type(i) == "line"]
                assert any(abs(ln[1] - (h - 2)) < 1.5 for ln in drawn), \
                    "%s: no bottom border while collapsed" % key
                top = card.coords(card._win)[1]
                assert top + card.body.winfo_height() < h - 2, \
                    "%s: the body covers the border" % key
            finally:
                a._card_toggle(key, False)
                ROOT.update_idletasks()

        top = a.nuke_btn.master
        a._size_nuke()
        ROOT.update_idletasks()
        assert top.winfo_width() == 1920, top.winfo_width()
        nx, nw = a.nuke_btn.winfo_x(), a.nuke_btn.winfo_width()
        gaps = []
        for c in top.winfo_children():
            if c is a.nuke_btn:
                continue
            x0, x1 = c.winfo_x(), c.winfo_x() + c.winfo_width()
            assert not (x0 < nx + nw and x1 > nx), \
                "%s overlaps NUKE" % c.winfo_class()
            gaps.append(nx - x1 if x1 <= nx else x0 - (nx + nw))
        assert min(gaps) >= a.NUKE_AIR, \
            "NUKE has only %d px of air, want %d" % (min(gaps), a.NUKE_AIR)

        _assert_tabs_fit(a, "1920x1080")


def _assert_tabs_fit(a, tag):
    """No right-panel tab may be narrower than its own glyph + label.

    sv_ttk bakes 32 px of horizontal air into its tab element, which is a
    fixed pixel figure at every DPI and every App text size; six tabs then
    overflowed the panel and every label lost its tail ("Plo", "Expor",
    "Fring").  `_fit_tab_padding` measures the air instead, so this is the
    assertion that keeps it honest.
    """
    nb = a.rnotebook
    st = ttk.Style()
    fnt = tkfont.Font(font=st.lookup("TNotebook.Tab", "font"))
    # Tk 8.6.14 hands lookup() back as a tuple of ints; Tk 8.6.9 (the Win7
    # runtime) as a tuple of Tcl string objects whose str() is
    # "<string object: '8'>".  Take the first element and dig the number out
    # rather than parsing the container's repr.
    raw = st.lookup("TNotebook.Tab", "padding")
    if isinstance(raw, (tuple, list)):
        raw = raw[0] if raw else 0
    m = re.search(r"-?\d+(?:\.\d+)?", str(raw))
    px = int(float(m.group(0))) if m else 0

    # what each tab was actually given: scan the strip
    width = nb.winfo_width()
    spans, cur, start = {}, None, 0
    for x in range(width):
        try:
            idx = nb.index("@%d,%d" % (x, 12))
        except tk.TclError:
            idx = None
        if idx != cur:
            if cur is not None:
                spans[cur] = x - start
            cur, start = idx, x
    if cur is not None:
        spans[cur] = width - start

    bad = []
    for i, t in enumerate(nb.tabs()):
        text = str(nb.tab(t, "text"))
        im = nb.tab(t, "image")
        if isinstance(im, (tuple, list)):
            im = im[0] if im else ""
        iw = (int(a.root.tk.call("image", "width", str(im)))
              if str(im) else 0)
        need = fnt.measure(text) + iw
        got = spans.get(i, 0) - 2 * px
        if got < need:
            bad.append("%s: %r needs %d px, got %d" % (tag, text, need, got))
    assert not bad, bad


# ---- v1.4.8 polish: the formula editor's two house cards -------------------
def _editor_cards(a, win):
    out = {}
    for c in a._brand_cards:
        if not (c.winfo_exists() and str(c).startswith(str(win))):
            continue
        lab = [k for k in c._title.winfo_children() if str(k.cget("text"))]
        out[str(lab[0].cget("text"))] = c
    return out


def test_formula_editor_cards_layout_behaviour_and_minimum_size(a):
    """The work column is an Input card and a Preview card beside the Guide;
    the Input card is sized to its own content (nothing empty under the last
    chip row) while Preview takes the slack the v1.4.9 reflow gives it, the
    chips span the card width, the chip/caret behaviour still works, and the
    window's minimum size fits all of it."""
    seed = {"name": "Pct T", "unit": "%", "expr": "100 * (S - D) / (B - D)",
            "latex": ""}
    with offscreen(a):
        win = a._quantity_editor(None, seed=dict(seed))
        try:
            win.update_idletasks()
            cards = _editor_cards(a, win)
            assert set(cards) == {"Input", "Preview", "Guide"}, sorted(cards)

            inp = cards["Input"]
            assert inp.grow == "x"
            # a grow='x' card requests exactly its content height, so nothing
            # empty can sit under the last line. _fit_height normally runs
            # off <Map>/<Configure>, which an unmapped probe never gets.
            inp._refresh()
            want = inp._top_inset() + inp.body.winfo_reqheight() + inp.pad
            assert abs(inp.winfo_reqheight() - want) <= 2, \
                "Input card asks for %d px for %d px of content" % (
                    inp.winfo_reqheight(), want)
            assert int(inp.pack_info().get("expand", 0)) == 0, \
                "the Input card expands and would leave dead ground"
            assert cards["Preview"].winfo_reqheight() > 0

            import formulas as _F
            n_col = len(_F.column_legend())
            n_fn = len(_F.function_names())
            chips = [w for w in walk(inp) if w.winfo_class() == "Button"]
            assert len(chips) == n_col + n_fn
            rows = {}
            for ch in chips:
                rows.setdefault(str(ch.master), []).append(ch)
            # The rows are a FLOOR that chip_rows raises until every chip
            # fits (R4 item 2: at App text size 15 the last column chip
            # was silently dropped by pack). So: at least the requested
            # 1 + 2, every chip placed, and the rows within one of each
            # other in length.
            assert len(rows) >= 3, "want >= 3 chip rows, got %d" % len(rows)
            assert sum(len(v) for v in rows.values()) == n_col + n_fn
            # every chip on a row narrow enough to hold it: the natural
            # widths of one row must fit the work column's budget
            _cf = a._F(-1, mono=True)
            _budget = a._em() * 46
            for _rk, _rv in rows.items():
                _w = sum(_cf.measure(str(c.cget("text"))) + 4 * a._em()
                         for c in _rv)
                assert _w <= _budget * 1.05, (
                    "chip row wants %d px of a %d px column" % (_w, _budget))
            for ch in chips:
                info = ch.pack_info()
                assert int(info.get("expand", 0)) == 1, \
                    "chip %r does not stretch" % str(ch.cget("text"))
                assert str(info.get("fill")) == "x"

            mw, mh = win.minsize()
            assert mw >= min(win.winfo_screenwidth() - 80, win.winfo_reqwidth())
            assert mh >= min(win.winfo_screenheight() - 140,
                             win.winfo_reqheight())
            assert (mw, mh) >= (660, 480)
        finally:
            win.destroy()
            ROOT.update_idletasks()

    with offscreen(a):
        win = a._quantity_editor(None, seed={"name": "", "unit": "",
                                             "expr": "", "latex": ""})
        try:
            win.update_idletasks()
            ents = [w for w in walk(win) if w.winfo_class() == "TEntry"]
            expr_e = ents[2]
            byname = {str(c.cget("text")): c for c in walk(win)
                      if c.winfo_class() == "Button"}
            expr_e.focus_set()
            byname["S"].invoke()
            byname["log()"].invoke()
            assert expr_e.get() == "Slog()"
            # the caret is left INSIDE the function parentheses
            assert expr_e.index("insert") == len("Slog(")
            save = [w for w in walk(win)
                    if w.__class__.__name__ == "RoundButton"
                    and str(w.cget("text")) == "Save"]
            assert save, "the Save button vanished"
            assert str(save[0].cget("state")) == "disabled"
            labs = [str(w.cget("text")) for w in walk(win)
                    if w.winfo_class() == "Label"]
            assert any(t.startswith("CSV column / file name:") for t in labs)
            assert any(t.startswith("uses:") for t in labs)
        finally:
            win.destroy()
            ROOT.update_idletasks()


# ---- a readonly combobox always reads from its FIRST character -------------
def test_no_combobox_can_be_left_showing_its_value_scrolled(a):
    """"ressure (GPa)" is the bug this locks out.

    ttk leaves the entry view wherever the caret ended up, and a value
    written after build -- a preset, a session load, a relabel -- can land
    while the box is still narrow.  Two things put it back: class bindings
    on the events that move the view, and the `_pin_field_styles` self-heal
    walk, which already has every combobox in hand.
    """
    for ev in ("<<ComboboxSelected>>", "<FocusOut>", "<Map>"):
        assert a.root.bind_class("TCombobox", ev), ev

    combos = [w for w in walk(a.root) if w.winfo_class() == "TCombobox"]
    assert len(combos) > 20, len(combos)
    ro = [c for c in combos if "readonly" in str(c.cget("state"))]
    assert len(ro) > 20, "the panel is combobox-driven (DESIGN_RULES #26)"

    # scroll a handful off char 0 the way ttk's caret would, then heal
    victims = ro[:8]
    for c in victims:
        c.xview(6)
    ROOT.update_idletasks()
    a._pin_field_styles()
    ROOT.update_idletasks()
    for c in victims:
        assert c.xview()[0] == 0.0, (str(c), c.get(), c.xview())

    # and the shared helper does it for one widget, event or not
    c = victims[0]
    c.xview(6)
    ROOT.update_idletasks()
    a._combo_home(c)
    ROOT.update_idletasks()          # deferred to idle on purpose
    assert c.xview()[0] == 0.0, (c.get(), c.xview())

    # nothing in the live tree is left scrolled
    bad = [(str(c), c.get()) for c in combos if c.xview()[0] != 0.0]
    assert not bad, bad


def _tab_extents(nb):
    """{tab index: drawn width in px}, by hit-testing the strip."""
    ext = {}
    for x in range(0, nb.winfo_width()):
        try:
            i = nb.index("@%d,%d" % (x, 12))
        except tk.TclError:
            continue
        lo, hi = ext.get(i, (x, x))
        ext[i] = (min(lo, x), max(hi, x))
    return dict((i, hi - lo + 1) for i, (lo, hi) in ext.items())


def test_right_notebook_order_active_tab_by_name_and_the_strip_refits(a):
    """R1a. Three claims about the six-tab strip.

    ORDER is Plot, Axes, Style, Data, Fringe, Export, with Defringe now the
    first card in Fringe and the Data tab reflowed without it.

    PERSISTENCE is by tab NAME, because the order is free to move; an int
    left by a pre-v1.4.9 settings file is read once through the order THAT
    build shipped and rewritten as a name.

    THE DISAPPEARING TAB. `_fit_tab_padding` hands the tabs every pixel of
    slack there is, so a fit made at one panel width leaves the strip too
    wide at a narrower one -- and ttk::notebook answers an over-wide strip
    by SQUEEZING the tabs until the right-most labels render clipped, which
    is the tab that "disappeared" after a Collapse all / Expand all pass.
    Nothing re-fitted on a resize before R1a. Now a width change schedules
    one, and no label may ever be given less room than it needs.
    """
    nb = a.rnotebook
    names = a._tab_names()
    assert names == ["Plot", "Axes", "Style", "Data", "Fringe",
                     "Export"], names
    # R10 removed the standalone Defringe section: the FFT removal card
    # in the workbench IS the defringe control now.
    assert "Defringe" not in a._section_cat
    assert a._section_cat["FFT removal"] == "Fringe"
    per = {}
    for rec in a._collapsibles:
        per.setdefault(a._section_cat.get(rec["key"]), []).append(rec["key"])
    assert per["Fringe"][0] == "Stack", per["Fringe"]
    assert per["Data"] == ["Smoothing", "Traces", "Formulas"], per["Data"]

    # _restore_tab runs on a root.after(80) the suite may never have flushed
    was_tab = a.settings.get("active_tab")
    was_ready = getattr(a, "_tabs_ready", False)
    try:
        a._tabs_ready = True
        nb.select(names.index("Fringe"))
        # <<NotebookTabChanged>> is a real event, not an idle task
        ROOT.update_idletasks(); ROOT.update()
        assert a.settings["active_tab"] == "Fringe", a.settings.get("active_tab")
        # the one-time migration, through the v1.4.8 order
        for stored, want in ((4, "Export"), (5, "Fringe"), ("3", "Data")):
            a.settings["active_tab"] = stored
            a._tabs_ready = False
            a._restore_tab()
            ROOT.update_idletasks()
            assert a.settings["active_tab"] == want, (stored, want)
            assert a._tab_names()[nb.index("current")] == want, stored
        a.settings["active_tab"] = "No Such Tab"       # must not raise
        a._tabs_ready = False
        a._restore_tab()
    finally:
        a.settings["active_tab"] = was_tab
        a._tabs_ready = was_ready
        nb.select(0)
        ROOT.update_idletasks()

    with realized("1600x950"):
        # a width change arms the debounced re-fit
        a._tabfit_w = None
        a._on_rnb_configure()
        assert getattr(a, "_tabfit_job", None), "a resize must schedule a fit"
        ROOT.after_cancel(a._tabfit_job)
        a._tabfit_job = None

        for pane in (514, 380):
            a.pw.paneconfigure(a.right_outer, width=pane, minsize=80)
            ROOT.update_idletasks(); ROOT.update()
            a._collapse_all(True)
            a._collapse_all(False)
            ROOT.update_idletasks(); ROOT.update()
            a._fit_tab_padding()                  # what <Configure> queues
            ROOT.update_idletasks(); ROOT.update()
            assert len(nb.tabs()) == 6, pane
            drawn = _tab_extents(nb)
            assert len(drawn) == 6, (pane, drawn)
            fnt = tkfont.Font(
                font=ttk.Style().lookup("TNotebook.Tab", "font"))
            for i, t in enumerate(nb.tabs()):
                txt = str(nb.tab(t, "text"))
                im = nb.tab(t, "image")
                if isinstance(im, (tuple, list)):
                    im = im[0] if im else ""
                need = fnt.measure(txt)
                if str(im):
                    need += int(ROOT.tk.call("image", "width", str(im)))
                assert drawn[i] >= need, (pane, txt, drawn[i], need)
        a.pw.paneconfigure(a.right_outer, width=a._pane_widths()[3],
                           minsize=a._pane_widths()[2])
        ROOT.update_idletasks()
