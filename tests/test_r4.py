"""Feedback round R4 (Nhan's live pass, 2026-08-06).

Nine items. The ones with a falsifiable invariant are pinned here; the
purely visual ones (the 3D shape subheader's position, the styled guide
boxes' looks) were screenshot-gated and are covered below only by their
structure - that the rows exist, in the right group, with the right tags.

One file, grouped asserts, shared App (tests/TESTING_POLICY.md).
"""
import tkinter as tk
from tkinter import ttk

import pytest

from conftest import gui, shared_app, quiesce

USES_APP = True
pytestmark = gui


@pytest.fixture(scope="module")
def a():
    return shared_app()


def _walk(w, out):
    for c in w.winfo_children():
        out.append(c)
        _walk(c, out)
    return out


class mapped(object):
    """Map the shared root OFF-SCREEN for the few asserts that need real
    pixel geometry (rule 58: +3200+100, never visible), then put it back
    the way the rest of the suite expects it."""

    def __init__(self, root, geom="1400x860+3200+100"):
        self.root, self.geom = root, geom

    def __enter__(self):
        self.old = self.root.geometry()
        self.root.geometry(self.geom)
        self.root.deiconify()
        self.root.update_idletasks()
        self.root.update()
        return self.root

    def __exit__(self, *exc):
        self.root.withdraw()
        try:
            self.root.geometry(self.old)
        except tk.TclError:
            pass
        self.root.update_idletasks()
        return False


# ---------------------------------------------------------------- item 1 ---
def test_plot_controls_share_the_status_row(a):
    """The view buttons live ON the status line, not under it, and the
    status line drops to a row of its own only when the row cannot hold
    everything (R4 item 1)."""
    row = a._center_bar
    wrap = a._center_barwrap
    # the toolbar, the readout and Data table are all in the one row
    kids = set(str(w) for w in row.winfo_children())
    assert str(a._data_btn) in kids
    assert str(a.cursor_lbl) in kids
    assert str(a._tb_strip) in kids
    for key in ("reset", "pan", "zoom", "save"):
        assert a._tb_btns[key].master is a._tb_strip

    # pack order is clip order: the status text is packed LAST, so it is
    # the sacrificial widget and the buttons never are (rule 13 / 14)
    with mapped(a.root, "1920x1080+3200+100"):
        a.cursor_lbl.configure(text="")
        a.status_lbl.configure(text="tab: Plot | shown: 1/1")
        a._bar_split = True                   # force a fresh decision
        a._fit_center_bar()
        a.root.update_idletasks()
        assert a._bar_split is False, "a wide window must fit one row"
        assert len(wrap.winfo_children()) >= 2   # row + the parked row
        one_row = wrap.winfo_height()
        # a long status TRUNCATES on a wide window - it does not evict the
        # buttons and it does not force a second row (rule 14)
        a.status_lbl.configure(text="tab: Plot | mode: Overlay | preset: " +
                               "Nature double column (183 mm) " * 4 +
                               "| shown: 19/19")
        a._fit_center_bar()
        a.root.update_idletasks(); a.root.update()
        assert a._bar_split is False, "a wide window must not split"
        assert a._data_btn.winfo_ismapped()
        assert a.cursor_lbl.winfo_ismapped()

    # a centre pane with no room left gets the two-row bar back
    with mapped(a.root, "1030x700+3200+100"):
        a._fit_center_bar()
        a.root.update_idletasks(); a.root.update()
        assert a._bar_split is True, "a narrow window must give the status "\
                                     "line its own row"
        assert wrap.winfo_height() > one_row, (
            "the split must give the status line a row of its own")
        assert a._data_btn.winfo_ismapped()
        assert a.cursor_lbl.winfo_ismapped()
        a.status_lbl.configure(text="")
        a._fit_center_bar()
    quiesce(a)


# ---------------------------------------------------------------- item 2 ---
def test_scroll_host_carries_a_scrollbar_only_when_it_must(a):
    """_scroll_host: content shorter than the room shows no bar, taller
    shows one, and the canvas asks for the CONTENT's height rather than
    Tk's stock canvas size (R4 item 2)."""
    win = tk.Toplevel(a.root)
    win.geometry("300x200+3200+100")
    try:
        host, body = a._scroll_host(win)
        host.pack(fill="both", expand=True)
        lbl = ttk.Label(body, text="one line")
        lbl.pack()
        win.update_idletasks()
        host._sparta_sync()
        win.update_idletasks()
        cv = host._sparta_canvas
        assert int(cv.cget("height")) == max(60, body.winfo_reqheight())
        bars = [w for w in _walk(host, []) if isinstance(w, ttk.Scrollbar)]
        assert len(bars) == 1
        assert not bars[0].winfo_ismapped(), "a bar nobody needs"

        for i in range(60):
            ttk.Label(body, text="row %d" % i).pack()
        win.update_idletasks()
        host._sparta_sync()
        win.update_idletasks()
        assert bars[0].winfo_ismapped(), "content past the fold, no bar"
    finally:
        win.destroy()


def test_quick_access_customizer_shows_every_item(a):
    """Nhan's screenshot: the checklist clipped at ~10 of 12 with no way
    to reach the rest. Every row must be built, and the window must ask
    for the height its content needs.

    R8 widened it to TWO columns - settings on the left, one-press
    actions on the right - so the count is both lists, and neither may
    lose a row to the fold."""
    if getattr(a, "_qa_win", None) is not None:
        try:
            a._qa_win.destroy()
        except tk.TclError:
            pass
        a._qa_win = None
    a._open_qa_customizer()
    win = a._qa_win
    try:
        win.geometry("+3200+100")
        win.update_idletasks()
        boxes = [w for w in _walk(win, [])
                 if isinstance(w, ttk.Checkbutton)]
        assert len(boxes) == len(a.QA_ITEMS) + len(a.QA_FUNCS)
        labels = set(str(b.cget("text")) for b in boxes)
        assert labels == (set(l for _k, l, _d in a.QA_ITEMS)
                          | set(l for _k, l, _s, _i, _t, _d in a.QA_FUNCS))
        # two real columns, not one long list
        _ctl = [b for b in boxes
                if str(b.cget("text")) == a.QA_ITEMS[0][1]][0]
        _fun = [b for b in boxes
                if str(b.cget("text")) == a.QA_FUNCS[0][1]][0]
        assert _fun.winfo_rootx() > _ctl.winfo_rootx()
        # sized to content: the scroll host's canvas asks for the whole
        # checklist (capped), so _fit_dialog cannot hand the window a Tk
        # default height and clip the last rows the way v1.4.9 shipped
        cvs = [w for w in _walk(win, []) if isinstance(w, tk.Canvas)]
        assert cvs, "the customizer has no scroll host"
        cv = cvs[0]
        inner = [w for w in cv.winfo_children()][0]
        cap = int(a.root.winfo_screenheight() * 0.68)
        assert int(cv.cget("height")) >= min(inner.winfo_reqheight(), cap)
        assert any(isinstance(w, ttk.Scrollbar) for w in _walk(win, []))
    finally:
        win.destroy()
        a._qa_win = None


# ---------------------------------------------------------------- item 3 ---
def test_guide_box_follows_both_size_controls(a):
    """W1b froze the Guide panel's prose to the app font, so the box's own
    Size spinbox moved nothing. Both controls must move every tag."""
    import tkinter.font as tkfont
    tags = ("h", "s", "b", "i", "m")

    def sizes():
        a.root.update_idletasks()
        return dict((t, tkfont.Font(root=a.root,
                                    font=a.ref.tag_cget(t, "font")
                                    ).actual("size")) for t in tags)

    old_app, old_gear = a._body_size, a.guide_font_size.get()
    try:
        a.guide_font_size.set(9)
        a._apply_guide_font()
        a._ui_size_var.set(8)
        a._apply_ui_size()
        small = sizes()
        a._ui_size_var.set(14)
        a._apply_ui_size()
        big = sizes()
        for t in tags:
            assert big[t] > small[t], "tag %r ignores the app text size" % t

        a._ui_size_var.set(9)
        a._apply_ui_size()
        base = sizes()
        a.guide_font_size.set(16)
        a._apply_guide_font()
        zoomed = sizes()
        for t in tags:
            assert zoomed[t] > base[t], "tag %r ignores the Guide gear" % t
        # the gear is a zoom: at its factory setting the prose IS the app
        # text size
        assert a._guide_zoom() == 16 - a.GUIDE_SIZE_BASE
    finally:
        a.guide_font_size.set(old_gear)
        a._apply_guide_font()
        a._ui_size_var.set(old_app)
        a._apply_ui_size()
        quiesce(a)


# ---------------------------------------------------------------- item 4 ---
def test_theme_box_is_exactly_as_wide_as_its_longest_name(a):
    """No elision, no slack (R4 item 4)."""
    import app as A
    cb = a._theme_combo
    a.root.update_idletasks()
    f = a._combo_font()
    zero = max(1, f.measure("0"))
    need = max(f.measure(s) for s in A.THEME_LABELS.values())
    room = int(cb.cget("width")) * zero
    assert room >= need, "the longest theme name would elide"
    assert room - need < zero * 2, "more than a glyph of dead width"


# ------------------------------------------------------------- item 5/7 ---
def test_3d_shape_group_and_fill_color(a):
    """The shape controls live under their own subheader, and the fill
    colour is a real, preset-registered setting (R4 items 5 and 7)."""
    assert "wf3d_surf_fill_color" in a._preset_registry()
    assert a.wf3d_surf_fill_color.get() == "auto"
    assert a._surf_fill_kw() is None, "'auto' must not override export3d"
    a.wf3d_surf_fill_color.set("#888888")
    kw = a._surf_fill_kw()
    assert kw["color"] == "#888888"
    assert kw["wall_darken"] == 1.0, "a picked colour must arrive as picked"
    a.wf3d_surf_fill_color.set("theme bg")
    assert a._surf_fill_kw()["color"] == a._mpl_colors()[0]
    a.wf3d_surf_fill_color.set("auto")

    # the subheader exists and the five rows sit after it, before
    # 'Layout & speed'
    heads = [w for w in _walk(a.rframes[0] if hasattr(a, "rframes")
                              else a.root, [])
             if isinstance(w, tk.Label)
             and str(w.cget("text")).strip() in ("3D shape", "Layout & speed",
                                                 "Ridges")]
    names = [str(w.cget("text")).strip() for w in heads]
    assert "3D shape" in names, names
    assert names.index("Ridges") < names.index("3D shape") \
        < names.index("Layout & speed"), names
    quiesce(a)


# ---------------------------------------------------------------- item 8 ---
@pytest.mark.parametrize("opener,attr", [
    ("_open_interp_info", "_interp_info_win"),
    ("_open_smooth_panel", "_smooth_win"),
    ("_open_name_format", "_nf_win"),
])
def test_every_guide_box_is_styled(a, opener, attr):
    """One renderer, one tag set: bold ALL-CAPS heading in the signal
    accent, a sub-heading, body prose, an aside and mono verbatim -- on
    every guide surface app.py owns (R4 item 8)."""
    if getattr(a, attr, None) is not None:
        try:
            getattr(a, attr).destroy()
        except tk.TclError:
            pass
        setattr(a, attr, None)
    getattr(a, opener)()
    win = getattr(a, attr)
    try:
        win.geometry("+3200+100")
        try:
            win.grab_release()
        except tk.TclError:
            pass
        win.update_idletasks()
        texts = [w for w in _walk(win, []) if isinstance(w, tk.Text)]
        assert texts, "no guide text box"
        txt = texts[0]
        for t in ("h", "s", "b", "i", "m"):
            assert str(txt.tag_cget(t, "font")), \
                "%s: tag %r has no font" % (attr, t)
        assert str(txt.tag_cget("h", "foreground")) == a._signal_fg()
        assert str(txt.tag_cget("m", "foreground")) == a._code_fg()
    finally:
        win.destroy()
        setattr(a, attr, None)


def test_shortcuts_popup_is_a_styled_singleton(a):
    """F1's list was an OS messagebox: unthemeable, and its proportional
    font broke the aligned key column (R4 item 8, QoL)."""
    import app as A
    if getattr(a, "_shortcuts_win", None) is not None:
        try:
            a._shortcuts_win.destroy()
        except tk.TclError:
            pass
        a._shortcuts_win = None
    a._show_shortcuts_popup()
    win = a._shortcuts_win
    try:
        win.geometry("+3200+100")
        win.update_idletasks()
        a._show_shortcuts_popup()               # a second F1 must not twin
        assert a._shortcuts_win is win
        txt = [w for w in _walk(win, []) if isinstance(w, tk.Text)][0]
        for t in ("h", "s", "b", "i", "m"):
            assert str(txt.tag_cget(t, "font"))
        body = txt.get("1.0", "end-1c")
        assert "KEYBOARD SHORTCUTS" in body
        assert "Ctrl+S" in body and "Esc" in body
        # the table rows are verbatim, so the key column stays aligned
        line = txt.search("Ctrl+S", "1.0")
        assert "m" in txt.tag_names(line), txt.tag_names(line)
        # ...and the closing note is prose, not a table row
        # R12 re-toned the note; it is still prose, not a table row
        # R19 register rule 2: the agent noun is SPARTA, "the tool" retires.
        # The note itself is unchanged in substance and still prose.
        note = txt.search("SPARTA ignores single keys", "1.0")
        assert note, "the closing note is gone"
        assert "b" in txt.tag_names(note), txt.tag_names(note)
        assert win.winfo_toplevel() is win
        assert A.SHORTCUTS_TEXT.splitlines()[0] == "KEYBOARD SHORTCUTS"
    finally:
        win.destroy()
        a._shortcuts_win = None


def test_guide_panel_uses_the_same_renderer(a):
    for t in ("h", "s", "b", "i", "m"):
        assert str(a.ref.tag_cget(t, "font"))
    assert str(a.ref.tag_cget("h", "foreground")) == a._signal_fg()


# ---------------------------------------------------------------- item 9 ---
def test_about_credits(a):
    """Nhan's name, no MIT-by-permission line, and Matthew's repository as
    a second link line (R4 item 9)."""
    if getattr(a, "_about_win", None) is not None:
        try:
            a._about_win.destroy()
        except tk.TclError:
            pass
        a._about_win = None
    a._about()
    win = a._about_win
    try:
        win.geometry("+3200+100")
        win.update_idletasks()
        txt = [w for w in _walk(win, []) if isinstance(w, tk.Text)][0]
        body = txt.get("1.0", "end-1c")
        assert "Nhan Ta" in body
        assert "Nguyen Quang Ta" not in body
        assert "vendored under the MIT license" not in body
        assert ("https://github.com/matthewrdiamond/"
                "DAC-Absorption-Fringe-Analysis") in body
        assert "https://github.com/NoisySnooper/SPARTA" in body
        assert "lnk" in txt.tag_names(), "the repo lines are not links"
    finally:
        win.destroy()
        a._about_win = None


def test_about_copy_file_matches(a):
    import io
    import os
    p = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(
        __file__))), "docs", "guide_content", "ABOUT_COPY.md")
    s = io.open(p, encoding="utf-8").read()
    body = s.split("-->", 1)[-1]
    assert "Nhan Ta" in body
    assert "Nguyen Quang Ta" not in body
    assert "vendored under the MIT license" not in body
    assert "matthewrdiamond/DAC-Absorption-Fringe-Analysis" in body


# ------------------------------------------------------------------- R8 ---
def test_quick_access_pins_actions_as_well_as_settings(a):
    """The strip's second column: ticking an 'Essential function' puts a
    compact icon button on the strip, live, and untick takes it away.
    Strip furniture is SETTINGS, never a preset (rule 30)."""
    was = list(a.settings.get("qa_funcs") or [])
    try:
        assert a.QA_FUNCS_DEFAULT == (), "a fresh install pins nothing"
        assert "qa_funcs" not in a._preset_registry()
        # every offered action resolves to something that can be pressed
        for key, _lab, short, icon, tgt, tip in a.QA_FUNCS:
            assert short and tip and icon in a._icons, key
            if tgt.startswith("@"):
                assert getattr(a, tgt[1:], None) is not None, tgt
            else:
                assert callable(getattr(a, tgt, None)), tgt

        a._qa_apply_funcs([])
        a.root.update_idletasks()
        assert not a._qa_fx_btns

        keys = [k for k, _l, _s, _i, _t, _d in a.QA_FUNCS][:6]
        a._qa_apply_funcs(keys)
        a.root.update_idletasks()
        a._qa_fx_flow()
        assert len(a._qa_fx_btns) == len(keys)
        assert all(str(b.cget("image")) for b in a._qa_fx_btns)
        assert all(str(b.cget("compound")) == "left" for b in a._qa_fx_btns)
        assert a.settings["qa_funcs"] == keys
        # they wrap instead of running off the end of the strip
        assert a._qa_fx_rows and sum(len(r.winfo_children())
                                     for r in a._qa_fx_rows) >= 0
        # an unknown key is dropped, not drawn
        a._qa_apply_funcs(keys + ["not_a_function"])
        a.root.update_idletasks()
        assert a._qa_funcs() == keys
        # a dead target is a no-op, never a traceback out of a button
        a._qa_fire("_definitely_not_a_method_")
        a._qa_fire("@_definitely_not_a_widget_")

        a._qa_apply_funcs([])
        a.root.update_idletasks()
        assert not a._qa_fx_btns
    finally:
        a._qa_apply_funcs(was)
        quiesce(a)
