"""R17 W2: the Defringe switch repaints the all-pressures plot, and a Tk
callback that dies says so.

Matthew's first report of round 2 was "the defringe button doesn't update the
all-pressures plot".  R17-B reproduced it on the first try on real data and it
is one broken line.  ``fringe_apply.clean_channel`` returns ``applied=True``
with ``nt_um=None`` whenever the low-pass alone ran and no confident fringe was
detected -- 14 of 18 real Y03 traces, 81 of 174 real channels.
``_defringe_report`` formatted that None with ``%.1f``, the TypeError landed in
a Tk callback with no handler, and ``self._redraw()`` on the NEXT line never
ran.  The cache filled, the progress bar ran, the plot did not move, and in the
windowed exe the traceback went nowhere.

This file pins the four contracts that came out of it:

  * ORDER -- the repaint the user asked for runs FIRST and never waits on a
    log line.  A report that raises costs one line in the log and nothing else;
  * NO NUMBER IS ASSUMED -- every reader of a detected n*t or a Fisher p goes
    through ``_num_or_dash`` / ``_nt_tag``, so a channel cleaned with nothing
    detected behind it reads "low-pass only" instead of raising;
  * NOTHING IS SILENT -- ``root.report_callback_exception`` puts the traceback
    in the log pane AND in sparta_errors.log beside the program;
  * the three extras R17-B found on the way: an all-NaN trace takes no stacked
    label (F4), a workbench edit invalidates every session tab's cache and not
    only the front one (F5), and the program says out loud that A / S / B / D
    are raw and only Af / Sf / Bf follow the switch (F3).

Authored under the suite policy: the ONE shared App, no second root, every
Toplevel off-screen, the live settings file never touched.
"""
import inspect
import warnings

import numpy as np
import pytest

import app
import fringe_apply
from conftest import gui, make_result, shared_app

USES_APP = True
pytestmark = gui

WL = np.linspace(500.0, 900.0, 400)


@pytest.fixture(scope="module")
def a():
    return shared_app()


# ---------------------------------------------------------------------------
# records
# ---------------------------------------------------------------------------
def _res(label, pval, absorb=None):
    """An engine-style record with real counts, or with an absorbance that is
    NaN end to end (a raw-only [S+B] trace, which is what F4 trips over)."""
    d = np.ones_like(WL)
    b = 1200.0 + 40.0 * np.sin(WL / 11.0)
    s = 600.0 + 20.0 * np.sin(WL / 9.0)
    if absorb is None:
        with np.errstate(divide="ignore", invalid="ignore"):
            absorb = -np.log10((s - d) / (b - d))
        absorb = np.where(np.isfinite(absorb), absorb, np.nan)
    return make_result(label, pval, wl=WL.copy(), samp=s, bg=b, dark=d,
                       absorb=absorb)


def _lp_only(wl_nm, counts, **kw):
    """What the low-pass-only path returns: a mask ran, nothing was detected.

    `applied` True with `nt_um` None is the exact pair that killed the redraw.
    Deterministic and cheap, so the test asserts on an equality rather than on
    a detector's judgement."""
    y = np.asarray(counts, float)
    return {"clean": y - 3.0, "applied": True, "pvalue": 1.0,
            "nt_um": None, "centers_nm": None}


def _lines(a):
    return {lbl: ln for ln, lbl in a._pick_map.items()}


def _plain_overlay(a):
    a.mode.set("overlay")
    a.wf_mode.set("off")
    a.ydata.set("absorbance")
    a.show_smooth.set(False)
    a.df_compare.set(False)


# ===========================================================================
# 1. the formatting helpers -- nothing assumes a number
# ===========================================================================
def test_a_missing_number_never_reaches_a_percent_f():
    """The one broken line, as a unit.  `"%.1f" % None` is a TypeError; every
    reader now goes through these two instead."""
    assert app.App._num_or_dash(None) == "-"
    assert app.App._num_or_dash(None, "%.3f") == "-"
    assert app.App._num_or_dash(12.34) == "12.3"
    assert app.App._num_or_dash(12.34, "%.3f") == "12.340"
    assert app.App._num_or_dash(1e-7, "%.1e") == "1.0e-07"
    assert app.App._num_or_dash("not a number") == "-"
    # a cleaned channel with a fringe behind it, and one without
    assert app.App._nt_tag(12.34) == "n*t=12.3um"
    assert app.App._nt_tag(None) == "low-pass only"


# ===========================================================================
# 2. F1 -- df ON repaints even when a channel was cleaned without a fringe
# ===========================================================================
@gui
def test_df_on_repaints_when_a_channel_has_no_detected_fringe(a, monkeypatch):
    """THE regression.  Every shown trace ends up drawn with the CLEANED
    absorbance, and the report says 'low-pass only' instead of raising."""
    recs = [_res("10.00 GPa", 10.0), _res("20.00 GPa", 20.0)]
    a._finish_run([dict(r) for r in recs], [], "r17w2")
    _plain_overlay(a)
    monkeypatch.setitem(a.settings, "fr_suppress_report", False)
    monkeypatch.setattr(fringe_apply, "clean_channel", _lp_only)
    monkeypatch.setattr(a, "_run_busy", lambda: True)   # the in-line branch
    a.notch_cache.clear()
    a.log.delete("1.0", "end")

    a.show_notch.set(True)
    a._toggle_notch()                     # must not raise, must not stall
    a._redraw_now()

    lines = _lines(a)
    assert set(lines) == {"10.00 GPa", "20.00 GPa"}
    for r in a.results:
        nr = a._notch_result(r)
        assert nr["s_applied"] is True and nr["s_nt"] is None
        assert nr["b_applied"] is True and nr["b_nt"] is None
        drawn = np.asarray(lines[r["label"]].get_ydata(), float)
        assert np.allclose(drawn, nr["absorbance"], equal_nan=True), \
            "%s is not drawn with the cleaned absorbance" % r["label"]
        assert not np.allclose(drawn, np.asarray(r["absorbance"], float),
                               equal_nan=True), \
            "%s is still drawn RAW with df on" % r["label"]

    txt = a.log.get("1.0", "end")
    assert "low-pass only" in txt or "n*t=-" in txt
    assert "Defringe report failed" not in txt
    assert "Fringe detected in" in txt          # the report ran to its end

    a.show_notch.set(False)
    a._toggle_notch()


@gui
def test_a_report_that_raises_costs_one_log_line_and_nothing_else(a,
                                                                  monkeypatch):
    """The order is the fix: the plot first, the log line after.  A report is
    not a plot and must never be able to hold one back."""
    a._finish_run([dict(_res("10.00 GPa", 10.0))], [], "r17w2")
    _plain_overlay(a)
    monkeypatch.setitem(a.settings, "fr_suppress_report", False)
    monkeypatch.setattr(a, "_run_busy", lambda: True)

    def boom(quiet=False):
        raise TypeError("must be real number, not NoneType")

    monkeypatch.setattr(a, "_defringe_report", boom)
    drew = []
    real_redraw = a._redraw
    monkeypatch.setattr(a, "_redraw",
                        lambda *x: (drew.append(1), real_redraw(*x))[1])
    a.notch_cache.clear()
    a.log.delete("1.0", "end")

    a.show_notch.set(True)
    a._toggle_notch()

    assert drew, "the repaint never ran"
    txt = a.log.get("1.0", "end")
    assert txt.count("Defringe report failed") == 1
    assert "NoneType" in txt                   # the reason is in the line
    assert a.notch_cache, "the pass itself still filled the cache"

    a.show_notch.set(False)
    a._toggle_notch()


# ===========================================================================
# 3. a Tk callback failure is never silent
# ===========================================================================
@gui
def test_a_dead_tk_callback_lands_in_the_log_and_in_the_error_file(
        a, monkeypatch, tmp_path):
    """The packaged build is a windowed exe with no stderr.  Without this the
    next F1 is just as invisible as the first one was."""
    assert "report_callback_exception" in vars(a.root), \
        "App installs no handler on the root"
    a._install_error_handler()             # idempotent; make it THIS App's
    path = tmp_path / "sparta_errors.log"
    monkeypatch.setattr(app, "ERROR_LOG_PATH", str(path))
    monkeypatch.setattr(a, "_error_log_path", str(path), raising=False)
    a.log.delete("1.0", "end")

    def boom():
        raise ValueError("r17 w2 probe")

    a.root.after_idle(boom)
    a.root.update()

    txt = a.log.get("1.0", "end")
    assert "Callback error" in txt
    assert "ValueError" in txt and "r17 w2 probe" in txt
    assert path.is_file(), "nothing was written to the error file"
    disk = path.read_text(encoding="utf-8")
    assert "Traceback" in disk and "r17 w2 probe" in disk

    # the shipped destination is beside the program, not in a temp folder
    assert app.ERROR_LOG_PATH == str(path)     # only while monkeypatched
    src = inspect.getsource(app)
    assert 'ERROR_LOG_PATH = os.path.join(TOOL_DIR, "sparta_errors.log")' in src


@gui
def test_the_error_handler_cannot_recurse(a, monkeypatch, tmp_path):
    """A failure INSIDE the handler must not raise its way back out: _logline
    pumps idles, and an idle callback can raise."""
    a._install_error_handler()
    path = tmp_path / "sparta_errors.log"
    monkeypatch.setattr(a, "_error_log_path", str(path), raising=False)
    monkeypatch.setattr(app, "ERROR_LOG_PATH", str(path))
    calls = []

    def bad_logline(msg):
        calls.append(msg)
        raise RuntimeError("the log pane is gone")

    monkeypatch.setattr(a, "_logline", bad_logline)
    a.root.report_callback_exception(ValueError, ValueError("probe"), None)
    assert calls, "the handler never reached the log"
    assert path.is_file(), "a dead log pane cost the error file"
    assert not getattr(a, "_in_error_handler", False)


# ===========================================================================
# 4. F4 -- an all-NaN trace takes no stacked label
# ===========================================================================
@gui
def test_an_all_nan_trace_takes_no_stacked_label(a):
    """np.nanmedian over an all-NaN trace warns and answers NaN, so the label
    went nowhere and every redraw printed a RuntimeWarning.  Skip the label.

    The warning count is measured against the SAME draw with the dead trace
    unticked, so an unrelated warning somewhere else in the draw cannot make
    this pass or fail by itself.
    """
    good = _res("10.00 GPa", 10.0)
    dead = _res("20.00 GPa", 20.0, absorb=np.full(WL.size, np.nan))
    a._finish_run([dict(good), dict(dead)], [], "r17w2")
    a.mode.set("overlay")
    a.ydata.set("absorbance")
    a.show_smooth.set(False)
    a.show_notch.set(False)
    a.wf_mode.set("2D stacked")
    a.wf_auto_sep.set(False)          # keep _stack_step out of the measurement
    a.wf_step.set("0.5")
    a.wf_label.set(True)

    def _draw_and_count():
        with warnings.catch_warnings(record=True) as rec:
            warnings.simplefilter("always")
            a._redraw_now()
        return sum(1 for w in rec if "All-NaN" in str(w.message))

    a.trace_vars[dead["label"]].set(False)
    base = _draw_and_count()
    a.trace_vars[dead["label"]].set(True)
    withdead = _draw_and_count()
    assert withdead <= base, \
        "the all-NaN trace still raises an All-NaN warning (%d vs %d)" \
        % (withdead, base)

    labels = [t.get_text() for t in a.ax.texts]
    assert "10.0" in labels, "the finite trace lost its stacked label"
    assert "20.0" not in labels, "the all-NaN trace was still labelled"

    a.wf_mode.set("off")
    a.wf_auto_sep.set(True)


# ===========================================================================
# 5. F5 -- a workbench edit invalidates every session, not only the front one
# ===========================================================================
@gui
def test_a_workbench_edit_reaches_the_inactive_session_caches(a):
    """Every other tab holds its OWN dicts (_capture_session / _tab_load
    rebind the live names onto them), so clearing the live one reaches the
    front tab and nothing else."""
    lbl, other = "10.00 GPa", "20.00 GPa"
    a.notch_cache[lbl] = {"absorbance": None}
    a.notch_cache[other] = {"absorbance": None}
    fake = {"name": "Session 2",
            "notch_cache": {lbl: 1, other: 2},
            "smooth_cache": {lbl: 1, other: 2},
            "nt_cache": {lbl: 1, other: 2}}
    a.sessions.append(fake)
    try:
        # one trace's notch list moved, the detection gates held still
        a._notch_params_changed(gates=False, label=lbl)
        assert lbl not in a.notch_cache
        assert lbl not in fake["notch_cache"], \
            "the inactive session still holds the old cleaning"
        assert lbl not in fake["smooth_cache"]
        assert other in fake["notch_cache"], \
            "a label-scoped edit must not be a global clear"
        assert fake["nt_cache"] == {lbl: 1, other: 2}, \
            "gates=False must leave the detection cache alone"

        # a gate moved: everything goes, in every session
        a._notch_params_changed(gates=True)
        assert fake["notch_cache"] == {}
        assert fake["smooth_cache"] == {}
        assert fake["nt_cache"] == {}
    finally:
        a.sessions.remove(fake)


# ===========================================================================
# 6. F3 -- the program says which symbols follow the switch
# ===========================================================================
def test_the_symbol_hint_names_the_defringed_variants():
    """A formula written over A is raw BY DESIGN, and until R17 nothing said
    so where the reader is.  It reads as 'df does nothing' every time."""
    note = app.DF_SYMBOL_NOTE
    for sym in ("A, S, B and D", "raw", "Af", "Sf", "Bf", "Defringe switch"):
        assert sym in note, "the hint does not mention %r" % sym
    assert "defringed" in note
    assert "—" not in note                 # STE: no em dashes
    src = inspect.getsource(app)
    # said in BOTH Y-axis pickers and in the formula editor's Guide
    assert src.count("DF_SYMBOL_NOTE") >= 4, \
        "the note is defined but not printed in all three places"
    # ...and in the in-app guide's own DATA > FORMULAS block, which is where
    # the reader meets the symbols.  That block lives in PANEL_GUIDE (the
    # Guide window's text).  app.INFO_TEXT is the short reference card next
    # to it -- absorbance, x-axis units, CSV naming, 1737 characters, no
    # formulas section at all -- so the clause could never have gone there.
    # The clause is wrapped at 72 columns and R19's register sweep re-wrapped
    # the block, so it is matched over collapsed whitespace: the words are
    # what the reader needs, the line break is the formatter's business.
    assert "stay raw whatever the df" in " ".join(app.PANEL_GUIDE.split())
    assert "DATA > FORMULAS" in app.PANEL_GUIDE


# ===========================================================================
# 7. the thickness table tolerates a channel with nothing detected
# ===========================================================================
@gui
def test_the_thickness_table_prints_a_dash_for_a_missing_read(a, monkeypatch):
    """The plot already broke its line at a miss; the table has to print
    something for the p-value column too."""
    r = _res("10.00 GPa", 10.0)
    a._finish_run([dict(r)], [], "r17w2")
    monkeypatch.setattr(a, "_nt_result",
                        lambda rr: {"s": None, "b": 12.5, "sp": None,
                                    "bp": 3e-5, "err": None})
    rows = a._thickness_rows()
    assert rows and len(rows) == 1
    _rec, d = rows[0]
    cells = (a._num_or_dash(d["s"], "%.3f"), a._num_or_dash(d["sp"], "%.1e"),
             a._num_or_dash(d["b"], "%.3f"), a._num_or_dash(d["bp"], "%.1e"))
    assert cells == ("-", "-", "12.500", "3.0e-05")
