"""v1.4.9 R5: the six live-feedback fixes.

Per TESTING_POLICY these ride the ONE shared App and assert the contract
each fix has to keep, not the pixels (the R5 probe scripts carried the
screenshot evidence).
"""
import os
import types

import pytest

import app
import guide_tour
from conftest import ROOT, gui, shared_app

USES_APP = True
pytestmark = gui

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
GUIDE = os.path.join(HERE, "docs", "guide_content")


@pytest.fixture(scope="module")
def a():
    return shared_app()


# ---------------------------------------------------------------------------
# item 1 - the tour's boxes are measured in characters of the ACTIVE face
# ---------------------------------------------------------------------------
class _StubFont(object):
    def __init__(self, adv):
        self.adv = adv

    def measure(self, s):
        return int(round(len(s) * self.adv))

    def metrics(self, _k):
        return 20


class _StubApp(object):
    def __init__(self, adv, root_w=1600):
        self._adv = adv
        self._w = root_w
        self.root = types.SimpleNamespace(winfo_width=lambda: self._w)

    def _F(self, _d=0, **kw):
        return _StubFont(self._adv)


def test_tour_box_width_follows_the_prose_face_not_the_digit():
    """A face whose letters run wider gets a wider box, so the LINE
    LENGTH in characters stays put. This is the whole of R5 item 1."""
    narrow = _StubApp(7.38)          # Jost
    wide = _StubApp(10.35)           # OpenDyslexic
    wn = guide_tour._box_px(narrow, guide_tour.CARD_CHARS)
    ww = guide_tour._box_px(wide, guide_tour.CARD_CHARS)
    assert ww > wn
    # same characters per line either way (within a character)
    assert abs(wn / 7.38 - ww / 10.35) < 1.0
    assert abs(wn / 7.38 - guide_tour.CARD_CHARS) < 1.0


def test_tour_box_width_is_clamped_to_the_window():
    """A wide face may grow the card, never past a bit over half the
    window - the callout still has to leave its target in view."""
    wide = _StubApp(10.35, root_w=1400)
    assert guide_tour._box_px(wide, guide_tour.WELCOME_CHARS) <= 1400 * 0.55 + 1
    # ... and never below a readable floor, however small the window
    tiny = _StubApp(10.35, root_w=300)
    assert guide_tour._box_px(tiny, guide_tour.CARD_CHARS) == 240


def test_tour_adv_survives_a_faceless_app():
    assert guide_tour._adv(object()) > 0


def test_tour_card_remeasures_on_every_show(a):
    """_show must re-derive the width, the card inset and the wrap; a
    build-time cache is what left the Dyslexic card wrapping short."""
    import inspect
    src = inspect.getsource(guide_tour.Tour._show)
    assert "_box_px(app, CARD_CHARS)" in src
    assert "self._card_pad = int(getattr(self._card_w" in src
    assert "self._card_wh = (_cw," in src


def test_tour_no_digit_em_geometry_left():
    """The old constants are gone; nothing may size a tour box by '0'."""
    src = open(guide_tour.__file__, encoding="utf-8").read()
    assert "CARD_EM" not in src
    assert "WELCOME_EM" not in src


# ---------------------------------------------------------------------------
# item 2 - the Quick Access gear rides the LAST row
# ---------------------------------------------------------------------------
def test_qa_gear_sits_on_the_last_row_never_its_own(a):
    keep = list(a._qa_visible())
    try:
        for vis in (list(app.App.QA_DEFAULT),
                    ["wf", "lw"],
                    ["yaxis", "xaxis", "seriesvar"],
                    ["legend", "cbar", "grid"]):
            a._qa_apply_visible(vis)
            ROOT.update_idletasks()
            rows = a._qa_wrap.pack_slaves()
            gear = a._qa_gear_btn
            assert gear.winfo_exists()
            # it lives ON the last row, and that row has other tenants
            assert gear.master is rows[-1], vis
            assert len(rows[-1].pack_slaves()) > 1, vis
            # ... at its right end
            ROOT.update_idletasks()
            right = gear.winfo_x() + gear.winfo_width()
            assert right >= rows[-1].winfo_width() - 4, vis
    finally:
        a._qa_apply_visible(keep)


def test_qa_empty_strip_still_offers_the_gear(a):
    keep = list(a._qa_visible())
    try:
        a._qa_apply_visible([])
        ROOT.update_idletasks()
        rows = a._qa_wrap.pack_slaves()
        assert len(rows) == 1
        assert a._qa_gear_btn.winfo_exists()
        assert a._qa_gear_btn.master is rows[0]
    finally:
        a._qa_apply_visible(keep)


# ---------------------------------------------------------------------------
# item 3 - no reserved blank line under the join-points row
# ---------------------------------------------------------------------------
def test_thickness_status_line_takes_its_space_back(a):
    lab = a._thick_status
    a._set_thick_status("")
    ROOT.update_idletasks()
    assert not lab.winfo_ismapped(), "an empty status line must not be packed"
    a._set_thick_status("detecting fringes in 3 trace(s)")
    ROOT.update_idletasks()
    assert lab.winfo_ismapped()
    # and it lands ABOVE the separator, not after the readout row. R9a
    # had folded that separator away behind 'Advanced'; R14 reversed the
    # fold, so the separator is always packed and the anchor is simply
    # itself again.
    sibs = lab.master.pack_slaves()
    assert sibs.index(lab) < sibs.index(a._thick_sep)
    a._set_thick_status("")
    ROOT.update_idletasks()
    assert not lab.winfo_ismapped()


# ---------------------------------------------------------------------------
# item 4 - guides say what and how, never why-we-rejected
# ---------------------------------------------------------------------------
def test_interp_info_keeps_the_maths_and_drops_the_justification():
    src = open(app.__file__, encoding="utf-8").read()
    assert "STAYED HOME" not in src
    assert "talked themselves" not in src
    # the two formulas the box exists to teach are still there
    assert "STRAIGHT (LINEAR)" in src
    assert "SMOOTH (MONOTONE CUBIC)" in src


@pytest.mark.parametrize("name,gone", [
    ("20_plot_tab.md", "Only these two are offered on purpose"),
    ("23_data_tab_formulas.md", "were retuned on the June 2026"),
])
def test_guide_md_justification_removed(name, gone):
    body = open(os.path.join(GUIDE, name), encoding="utf-8").read()
    assert gone not in body


def test_guide_md_kept_the_how_to_text():
    body = open(os.path.join(GUIDE, "20_plot_tab.md"), encoding="utf-8").read()
    # R9b dropped 'the math' from every [?] title and R12 re-toned the
    # sentence; the pointer to the box is what must survive.
    # R19 re-wrapped the paragraph, so the sentence is matched over
    # collapsed whitespace: the pointer is the fact, the line break is not.
    assert "The [?] beside it opens the formulas." in " ".join(body.split())
    body = open(os.path.join(GUIDE, "23_data_tab_formulas.md"),
                encoding="utf-8").read()
    # R20 re-wrapped the smoothing steps, so both sentences now span a
    # line break.  They are matched over collapsed whitespace: the words
    # and their order are the fact, the line break is not.
    _flat = " ".join(body.split())
    assert "Steps 1, 2, 3 and 5 are the Igor values verbatim." in _flat
    assert "Steps 1, 2, 3 and 5 have Enable boxes." in _flat


# ---------------------------------------------------------------------------
# item 5 - the Fringe TAB builds the workbench too
# ---------------------------------------------------------------------------
# R7: the workbench cards mirror Matthew's sidebar.  The category map in
# app.py still lists the pre-R7 names until integration, so membership is
# asserted against the LIVE _collapsibles registry, which is what the
# honesty gate reads too.
# R10 removed the standalone Defringe section: its one switch folded into
# the workbench, where the FFT removal card IS the defringe control.
FRINGE_SECTIONS = ["Stack", "Session", "Pressure point",
                   "FFT removal", "Refractive Index from Intensity",
                   "Panels"]


def test_fringe_tab_selection_builds_the_workbench(a):
    keep = a.rnotebook.index(a.rnotebook.select())
    try:
        names = a._tab_names()
        a.rnotebook.select(names.index("Fringe"))
        a._on_tab_changed()
        ROOT.update_idletasks()
        assert a._fringe._built, "selecting the Fringe tab must build it"
        got = {r["key"] for r in a._collapsibles}
        assert set(FRINGE_SECTIONS) <= got
    finally:
        a.rnotebook.select(keep)
        a._on_tab_changed()


def test_late_built_fringe_cards_keep_section_order(a):
    names = a._tab_names()
    keep = a.rnotebook.index(a.rnotebook.select())
    try:
        a.rnotebook.select(names.index("Fringe"))
        a._on_tab_changed()
        ROOT.update_idletasks()
        recs = {r["key"]: r for r in a._collapsibles}
        ys = [(recs[k]["cont"].winfo_y(), k) for k in FRINGE_SECTIONS
              if k in recs]
        assert [k for _y, k in sorted(ys)] == FRINGE_SECTIONS
    finally:
        a.rnotebook.select(keep)
        a._on_tab_changed()


def test_late_built_fringe_cards_match_the_header_of_a_born_early_one(a):
    names = a._tab_names()
    keep = a.rnotebook.index(a.rnotebook.select())
    try:
        a.rnotebook.select(names.index("Fringe"))
        a._on_tab_changed()
        ROOT.update_idletasks()
        recs = {r["key"]: r for r in a._collapsibles}

        def sig(key):
            r = recs[key]
            return (str(r["title_lbl"].cget("foreground")),
                    str(r["title_lbl"].cget("font")),
                    str(r["marker"].cget("foreground")),
                    str(r["caret"].cget("foreground")))
        # every workbench card is built on demand now (R10), so the
        # baseline is a section born with the window
        base = sig("Plot mode")
        for k in FRINGE_SECTIONS:       # built on demand
            assert sig(k) == base, k
    finally:
        a.rnotebook.select(keep)
        a._on_tab_changed()


def test_workbench_is_still_lazy_until_something_asks():
    """The startup win: _init_fringe builds the view switch and nothing
    else, and only _wake_fringe_tab / activate() / load_state() pay."""
    import inspect
    src = inspect.getsource(app.App._init_fringe)
    assert "build_view_switch" in src
    assert "self._fringe.build()" not in src
    wake = inspect.getsource(app.App._wake_fringe_tab)
    assert '!= "Fringe"' in wake
    assert "_heal_tab_scroll" in wake
    assert "_on_tab_changed" in inspect.getsource(app.App).replace("\n", "")
    assert "_wake_fringe_tab" in inspect.getsource(app.App._on_tab_changed)
