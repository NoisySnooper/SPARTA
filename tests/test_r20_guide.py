"""R20 wave L-r: the guide classifier and the guide rendering.

Two symptoms, one file.

The classifier froze every line at six spaces or deeper in the monospace
face.  Six spaces is the format contract's "horizontal alignment is
meaningful" mark, but a wrapped continuation line under a deep list item
lands there too, so whole sentences came out in Consolas.  R20 splits the
two apart: a deep line is verbatim when it is a column-aligned row, or
when it carries a verbatim shape (one of ``= -> / \\ < > { } [ ]``, or a
token with two or more digits) AND does not read as a sentence.  The
sentence test is three consecutive all-lowercase words of three or more
letters, and it lives in ONE place -- ``guide_tour.reads_as_prose`` --
which app.py's fallback classifier borrows rather than copies.

The renderer then gave every indented paragraph the same 10 px margin, so
a wrapped list item lost its hanging indent, and paragraph gaps came out
as a blank body-height line plus the tag's own spacing.  R20 hangs the
indent off the paragraph's own depth and renders a gap at half the body
size.

The module is pure: no App, no Tk root (see tests/TESTING_POLICY.md).
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import guide_tour                                            # noqa: E402


def _tags(text):
    return [t for t, _s in guide_tour.guide_segments(text)]


def _mono(text):
    return [s for t, s in guide_tour.guide_segments(text) if t == "m"]


# ---------------------------------------------------------------------------
# the prose test itself
# ---------------------------------------------------------------------------
def test_reads_as_prose_wants_three_lowercase_words():
    assert guide_tour.reads_as_prose("and notches noise now and then.")
    assert guide_tour.reads_as_prose("it writes one file per trace")
    # a run of Capitalised column names is a list, not a sentence
    assert not guide_tour.reads_as_prose(
        "Wavelength_nm, Wavenumber_cm-1, Absorbance, Dark, Background")
    assert not guide_tour.reads_as_prose("A = -log10(S / B)")
    assert not guide_tour.reads_as_prose("Ctrl+E   Export data")


def test_verbatim_shape_reads_the_line_not_its_depth():
    assert guide_tour.is_verbatim_shape("docs/guide_content/00_quick_start.md")
    assert guide_tour.is_verbatim_shape("A = -log10((S - D) / (B - D))")
    assert guide_tour.is_verbatim_shape("{DAC}_{SAMPLE}_absorbance.csv")
    assert guide_tour.is_verbatim_shape("v1.5.0")           # digit-heavy token
    # a slash inside a sentence does not make the sentence verbatim
    assert not guide_tour.is_verbatim_shape(
        "the ticks and/or the crop apply to this export alone")
    assert not guide_tour.is_verbatim_shape("adds the notch columns")


# ---------------------------------------------------------------------------
# R20 3a: what a six-space line means now
# ---------------------------------------------------------------------------
def test_a_nested_continuation_line_at_six_spaces_is_prose():
    segs = guide_tour.guide_segments(
        "  Defringed data adds the notch columns\n"
        "      to every CSV the Run writes.")
    assert segs == [("i", "  Defringed data adds the notch columns"
                          " to every CSV the Run writes.")], segs


def test_a_path_line_at_six_spaces_is_mono():
    text = "  The content tree:\n\n      docs/guide_content/24_export_tab.md\n"
    assert _mono(text) == ["      docs/guide_content/24_export_tab.md"]


def test_a_formula_line_at_six_spaces_is_mono():
    text = ("  Absorbance:\n\n"
            "      A = -log10((Sample - Dark) / (Background - Dark))\n")
    assert _mono(text) == [
        "      A = -log10((Sample - Dark) / (Background - Dark))"]


def test_a_two_column_table_with_three_space_gaps_is_mono():
    text = ("  A ticked row appends its columns:\n\n"
            "      Defringed data   Absorbance_notch, Background_notch\n"
            "      Smoothed data    Absorbance_smoothed\n")
    assert len(_mono(text)) == 2, guide_tour.guide_segments(text)


def test_an_incidental_double_space_at_six_spaces_stays_prose():
    # two spaces is not a column gap, and the line reads as a sentence
    segs = guide_tour.guide_segments(
        "  Export data writes one CSV per trace\n"
        "      and the log line  names the columns it wrote.")
    assert [t for t, _s in segs] == ["i"], segs


# ---------------------------------------------------------------------------
# R20 wave G: where one paragraph ends and the next begins
#
# A block that nests -- a sub-heading at two, its items at four, their
# wrapped continuations at six -- used to come out as ONE paragraph,
# because every line under the block's shallowest prose line counted as a
# continuation.  An item now returns to ITS OWN indent, and only an indent
# with something deeper under it carries items at all, so a paragraph that
# wraps at its own indent is still one paragraph.
# ---------------------------------------------------------------------------
def test_a_nested_item_list_breaks_into_one_paragraph_per_item():
    """20_plot_tab.md's '3D shape' shape."""
    segs = guide_tour.guide_segments(
        "  3D shape\n"
        "    The continuous sheet's own controls.\n"
        "    Draft quality while rotating: draws a coarser sheet for\n"
        "      the length of a drag. On by default.\n"
        "    Interpolation: how the sheet crosses the gap between two\n"
        "      measured traces. Straight takes the shortest line.\n"
        "    Mark measured traces: draws every measured trace on the\n"
        "      sheet, each at its own series value.\n")
    assert segs == [
        ("i", "  3D shape The continuous sheet's own controls."),
        ("i", "    Draft quality while rotating: draws a coarser sheet"
              " for the length of a drag. On by default."),
        ("i", "    Interpolation: how the sheet crosses the gap between"
              " two measured traces. Straight takes the shortest line."),
        ("i", "    Mark measured traces: draws every measured trace on"
              " the sheet, each at its own series value."),
    ], segs


def test_numbered_steps_under_a_sub_heading_split():
    segs = guide_tour.guide_segments(
        "  Two steps\n"
        "    1. Pick a folder and press Run.\n"
        "    2. Open the output folder to check the CSVs the run\n"
        "      wrote.\n")
    assert segs == [
        ("i", "  Two steps"),
        ("i", "    1. Pick a folder and press Run."),
        ("i", "    2. Open the output folder to check the CSVs the run"
              " wrote."),
    ], segs


def test_a_long_colon_phrase_is_a_sentence_not_an_item_lead():
    """A control name is short; a sentence that runs past a colon is not.

    'Surface joins adjacent traces into a single gradient sheet:' is 58
    characters before the colon, so it reads on as prose.
    """
    segs = guide_tour.guide_segments(
        "  Ridges\n"
        "    Surface joins adjacent traces into a single gradient"
        " sheet: the\n"
        "      series value goes into the page.\n"
        "    3D look: walls + traces.\n")
    assert segs == [
        ("i", "  Ridges Surface joins adjacent traces into a single"
              " gradient sheet: the series value goes into the page."),
        ("i", "    3D look: walls + traces."),
    ], segs


def test_a_wrapped_line_that_opens_with_a_colon_phrase_stays_a_wrap():
    """Only an indent with something deeper under it carries items, and a
    wrap is the deepest line in its block."""
    segs = guide_tour.guide_segments(
        "  W x H in / Apply: custom size. Transparent / Tight bbox /\n"
        "    Face: export page options.\n")
    assert segs == [
        ("i", "  W x H in / Apply: custom size. Transparent / Tight bbox"
              " / Face: export page options."),
    ], segs


def test_a_deep_paragraph_that_wraps_at_its_own_indent_stays_whole():
    segs = guide_tour.guide_segments(
        "      The um to cm conversion sits inside the builtin. Hand\n"
        "      it t in um and read cm^-1.\n"
        "    - A/t: absorbance per unit thickness, in um^-1.\n")
    assert segs == [
        ("i", "      The um to cm conversion sits inside the builtin."
              " Hand it t in um and read cm^-1."),
        ("i", "    - A/t: absorbance per unit thickness, in um^-1."),
    ], segs


def test_a_flat_block_is_one_paragraph_however_many_colons_it_carries():
    segs = guide_tour.guide_segments(
        "  Once a fringe is there, the notch list has three states."
        " Boxes\n"
        "  ticked: those centres come out. Every box unticked, or the\n"
        "  fundamental set to none: nothing comes out.\n")
    assert [t for t, _s in segs] == ["i"], segs


def test_a_control_name_lead_is_a_name_not_a_wrapped_sentence():
    m = guide_tour._ITEM_LEAD.match
    assert m("Draft quality while rotating: draws a coarser sheet")
    assert m("3D detail (points/ridge): points kept per ridge")
    assert m("'Direct labels at curves': one label per trace")
    # a wrapped line that runs on past a colon is not an item lead
    assert not m("ticked: those centres come out. Every box unticked")
    assert not m("written beside the trace's CSV: the notch columns")
    assert not m("'Thickness table...' lists n*t and the p-value")
    assert not m("Surface joins adjacent traces into a single gradient"
                 " sheet: wavelength across")


def test_headings_and_shortcut_tables_are_untouched():
    text = ("EXPORT > DATA FILES\n\n"
            "  Include in each trace's CSV.\n\n"
            "  Ctrl+E          Export data\n"
            "  Ctrl+D          Data table\n")
    tags = _tags(text)
    assert tags[0] == "h"
    assert tags.count("m") == 2, guide_tour.guide_segments(text)


# ---------------------------------------------------------------------------
# R20 3b: what the renderer does with those segments
#
# _guide_fill needs a Text only to insert into, so a recorder stands in for
# one and the module stays pure. The tags themselves (the margins, the mono
# spacing, the half-height gap font) need a live widget and belong to the
# GUI pass.
# ---------------------------------------------------------------------------
import app                                                    # noqa: E402


class _Recorder(object):
    def __init__(self):
        self.rows = []

    def insert(self, _where, text, tags):
        self.rows.append((tags[0] if tags else None, text))


def _fill(rows):
    r = _Recorder()
    app.App._guide_fill(None, r, rows)
    return r.rows


def test_an_indented_paragraph_hangs_off_its_own_depth():
    rows = _fill([("i", "  a two-space item"),
                  ("i", "      a six-space item"),
                  ("b", "flat prose")])
    assert rows[0] == ("i2", "a two-space item\n")
    assert rows[1] == ("i6", "a six-space item\n")
    assert rows[2] == ("b", "flat prose\n")


def test_a_plain_aside_keeps_the_indent_the_flat_margin_stood_for():
    # the dialog Guide cards insert ('i', 'text') with no leading spaces
    assert _fill([("i", "an aside")]) == [("i2", "an aside\n")]


def test_a_very_deep_paragraph_clamps_to_the_top_rung():
    rows = _fill([("i", " " * 28 + "a deep aside")])
    assert rows == [("i12", "a deep aside\n")], rows


def test_a_gap_carries_its_own_tag_and_mono_keeps_its_spaces():
    rows = _fill([("gap", ""), ("m", "      A = 1")])
    assert rows[0] == ("gap", "\n")
    assert rows[1] == ("m", "      A = 1\n")


def test_the_guide_tag_set_lives_in_one_place():
    # every guide surface goes through _guide_tags: the fringe workbench's
    # pop-out guide pane used to configure a private copy of h/s/b/i/m
    import inspect
    import fringe_panel
    src = inspect.getsource(fringe_panel)
    for tag in ('"m"', '"i"', '"b"'):
        assert "tag_configure(%s" % tag not in src, tag
    assert "_guide_tags(" in src
