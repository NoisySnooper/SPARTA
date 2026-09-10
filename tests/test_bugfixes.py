"""Regression tests for the v1.4.8 bug hunt (F1-F8, C1-C3).

One test per verified finding, derived from the hunt's own reproduction
scripts. Each docstring records the symptom the fix removed, so a future edit
that reintroduces it names itself.  Where a finding had a battery of inputs
(five spellings of infinity, ten backslash units, six bogus HDROP handles)
the battery is a loop inside ONE test: relaunching pytest's machinery per
input bought nothing but wall time.

Runs against the suite's ONE shared App (tests/conftest.py).  Dialogs are
opened for real and forced off-screen at +3200+100: a test run must never
flash a window at the user.
"""
import contextlib
import os
import struct
import sys

import numpy as np
import pytest

import app
import engine
import smoothing
from conftest import (ROOT, by_text, gui, make_result, offscreen, shared_app,
                      toplevels, walk)

USES_APP = True

_win = pytest.mark.skipif(sys.platform != "win32", reason="Windows only")


@pytest.fixture(scope="module")
def a():
    return shared_app()


# --------------------------------------------------------------- helpers ---
def _res(dac, sample, pstr, pval):
    return make_result("%s %s %.2f GPa" % (dac, sample, pval), pval, n=12,
                       dac=dac, sample=sample, pstr=pstr)


def _make_files(folder, names):
    for nm in names:
        open(os.path.join(str(folder), nm), "w").close()
    return str(folder)


_BEAMLINE_NAMES = ["vis_Y04_Arch29_12p5_bg_C.001",
                   "vis_Y04_Arch29_12p5_s_C.001",
                   "vis_Y04_Arch29_12p5_d_C.001"]


@contextlib.contextmanager
def _namefmt(a, folder, save_as=True):
    """Open the Name-format dialog off-screen on folder; save_as leaves the
    builtin profile, which is what makes the chip row appear."""
    a.in_var.set(folder)
    with offscreen(a):
        before = set(str(w) for w in ROOT.winfo_children())
        a._open_name_format()
        ROOT.update()
        d = [w for w in ROOT.winfo_children()
             if str(w) not in before and w.winfo_class() == "Toplevel"][-1]
        if save_as:
            by_text(d, "Save as…").invoke()
            ROOT.update()
        try:
            yield d
        finally:
            for step in (d.grab_release,
                         lambda: d.winfo_exists() and d.destroy()):
                try:
                    step()
                except Exception:
                    pass
            ROOT.update()
    a.in_var.set("")


def _matched_text(d):
    """The dialog's 'matched N / M files' status line."""
    out = ""
    for w in walk(d):
        try:
            t = w.cget("text")
        except Exception:
            continue
        if isinstance(t, str) and t.startswith("matched "):
            out = t
    return out


def _chip_values(d):
    for w in walk(d):
        if w.winfo_class() == "TCombobox" and "dac" in (w.cget("values") or ()):
            return list(w.cget("values")), int(w.cget("width"))
    return [], -1


# ------------------------------------------------------------------- F1 ----
@gui
def test_bugfix_f1_infinite_interval_never_raises(a):
    """Tcl's double parser accepts 'inf' / '1e400', so IntVar.get() handed
    back a float infinity and int(float(...)) raised OverflowError - which
    was not in the except tuple, so it escaped once per keystroke."""
    for typed in ("inf", "Inf", "INFINITY", "1e400", "-inf"):
        a._rescan_spin.delete(0, "end")
        a._rescan_spin.insert(0, typed)
        ROOT.update()
        assert a._auto_rescan_secs() == 30, typed   # the documented fallback
    a._rescan_spin.delete(0, "end")
    a._rescan_spin.insert(0, "30")
    ROOT.update()


@gui
def test_bugfix_f1_pill_still_arms_the_timer_with_a_junk_interval(a):
    """_toggle_auto_rescan raised inside _persist_rescan before it ever
    reached _schedule_auto_rescan, so the pill showed ON with no timer."""
    a._rescan_spin.delete(0, "end")
    a._rescan_spin.insert(0, "inf")
    ROOT.update()
    a.auto_rescan.set(True)
    a._toggle_auto_rescan()
    try:
        assert a._auto_rescan_job is not None
        assert a.settings["rescan_interval"] == 30
    finally:
        a.auto_rescan.set(False)
        a._cancel_auto_rescan()
        a._rescan_spin.delete(0, "end")
        a._rescan_spin.insert(0, "30")
        ROOT.update()


# ------------------------------------------------------------------- F2 ----
@gui
def test_bugfix_f2_variable_named_like_a_field_does_not_brick_the_dialog(
        a, tmp_path, monkeypatch):
    """A Variable called Sample / DAC / Branch / Rep / Role / Ignore aliased
    the pressure chip onto a REAL field name: the dropdown grew a duplicate
    option, _fcanon stored the user's 'sample' chip as 'pressure', the real
    field vanished from the order and validate_profile then refused 'Use
    this profile' with "'sample' missing from token order". The alias is
    dropped when it would shadow a field, so nothing aliases and nothing
    is blocked."""
    errs = []
    monkeypatch.setattr(app.simpledialog, "askstring", lambda *x, **k: "V")
    monkeypatch.setattr(app.messagebox, "showerror",
                        lambda *x, **k: errs.append(x))
    monkeypatch.setattr(app.messagebox, "showinfo", lambda *x, **k: None)
    folder = _make_files(tmp_path, _BEAMLINE_NAMES)
    a.xvar_choice.set(app.XVAR_CUSTOM)
    a.xvar_unit.set("u")
    for vname in ("Sample", "dac", "Branch", "REP", "Role", "ignore"):
        a.xvar_name.set(vname)
        with _namefmt(a, folder) as d:
            vals, _w = _chip_values(d)
            assert vals == list(engine.FIELD_CHOICES), vname  # no alias
            assert len(vals) == len(set(vals)), vname
            by_text(d, "Use this profile").invoke()
            ROOT.update()
            assert errs == [], vname            # committed, not refused
            assert not d.winfo_exists(), vname  # ... and the dialog closed
        assert "pressure" in a._active_profile().get("order", [])


@gui
def test_bugfix_f2_a_harmless_variable_name_still_aliases(a, tmp_path,
                                                          monkeypatch):
    """The display alias is the point of the feature: only COLLIDING names
    fall back to the canonical label."""
    monkeypatch.setattr(app.simpledialog, "askstring", lambda *x, **k: "V")
    monkeypatch.setattr(app.messagebox, "showinfo", lambda *x, **k: None)
    a.xvar_choice.set("Temperature (K)")
    with _namefmt(a, _make_files(tmp_path, _BEAMLINE_NAMES)) as d:
        vals, _w = _chip_values(d)
        assert vals == ["dac", "sample", "temperature", "role", "branch",
                        "rep", "ignore"]


# ------------------------------------------------------------------- F3 ----
def _legacy_density(y, win, min_pts):
    """smoothing._density exactly as it shipped before the fix."""
    finite = np.isfinite(y).astype(float)
    half = int(win // 2)
    kernel = np.ones(2 * half + 1)
    counts = np.convolve(finite, kernel, mode="same")
    y[counts < min_pts] = np.nan


def _noisy(n, seed=1):
    rng = np.random.default_rng(seed)
    x = np.linspace(400.0, 1000.0, n)
    y = 0.8 + 0.3 * np.sin(x / 37.0) + 0.02 * rng.standard_normal(n)
    y[n // 7] = 9.9                  # saturation hit
    y[n // 5:n // 5 + 3] = np.nan    # a NaN island
    y[n // 3] += 1.5                 # a spike for Hampel
    y[2 * n // 3] += 0.9             # a jump for step 5
    return x, y


def test_bugfix_f3_normal_traces_are_byte_identical(monkeypatch):
    """The window clamp must be invisible on every trace long enough for
    the requested window: the output is compared BYTE FOR BYTE against the
    pre-fix _density, not merely 'close'.  Four (length, window) pairs cover
    the shape of the space: a real spectrum, the shortest trace the clamp
    still leaves alone, and both odd/even window parities."""
    for n, win in ((5360, 50), (2000, 49), (101, 50), (51, 1)):
        x, y = _noisy(n)
        params = dict(smoothing.DEFAULTS, density_win=win)
        monkeypatch.setattr(smoothing, "_density", _legacy_density)
        before = smoothing.smooth_curve(x, y, params)
        monkeypatch.undo()
        after = smoothing.smooth_curve(x, y, params)
        assert (np.ascontiguousarray(before, dtype="<f8").tobytes()
                == np.ascontiguousarray(after, dtype="<f8").tobytes()), (n, win)


def test_bugfix_f3_degenerate_length_or_window_does_not_crash():
    """np.convolve(mode='same') returns max(len(y), len(kernel)), so a
    kernel longer than the trace produced a mask longer than y:
    'IndexError: boolean index did not match indexed array' for any trace
    of <= density_win points (and ValueError at length 0).  The clamp turns
    an absurd window into 'the whole trace', which is what was asked for."""
    for n in (0, 1, 2, 12, 50, 51):
        x, y = (np.linspace(400.0, 1000.0, n), np.linspace(0.1, 1.0, n))
        assert len(smoothing.smooth_curve(x, y)) == n, n
    x, y = _noisy(5360)
    for win in (6000, 100000, 0, -5):
        out = smoothing.smooth_curve(x, y, dict(smoothing.DEFAULTS,
                                                density_win=win))
        assert len(out) == 5360, win


@gui
def test_bugfix_f3_smoothing_dialog_clamps_the_point_counts(a):
    """'Window (pts)' is free text with a per-keystroke live preview; an
    absurd value must be clamped on parse rather than reaching the
    filters."""
    a._finish_run([_res("Y04", "Arch29", "12p5", 12.5)], [], "dest")
    with offscreen(a):
        before = set(str(w) for w in ROOT.winfo_children())
        a._open_smooth_panel()
        ROOT.update()
        win = [w for w in ROOT.winfo_children()
               if str(w) not in before and w.winfo_class() == "Toplevel"][-1]
        try:
            by_text(win, "Live preview").invoke()  # live trace on
            ent = None
            for w in walk(win):
                if w.winfo_class() == "TEntry":
                    v = w.cget("textvariable")
                    if v and str(win.getvar(v)) == str(
                            smoothing.DEFAULTS["density_win"]):
                        ent = w
                        break
            assert ent is not None
            ent.delete(0, "end")
            for ch in "999999999":                  # one live redraw per key
                ent.insert("end", ch)
                ROOT.update()
            assert a.smooth_params["density_win"] == app.SMOOTH_INT_BOUNDS[
                "density_win"][1]
        finally:
            by_text(win, "Cancel").invoke()
            ROOT.update()


@gui
def test_bugfix_f3_export_smoothed_survives_a_short_trace(a, tmp_path):
    """The smoothed loop had no try/except, so the crash escaped into the
    Tk button callback and the export silently did nothing. R19 gave every
    caller one loop; R20 made it the Smoothed COLUMN of _write_final_csvs,
    and the guard has to still be there."""
    a._finish_run([_res("Y04", "Arch29", "12p5", 12.5)], [], "dest")
    for r in a.results:
        a.trace_vars[r["label"]].set(True)
    a.smooth_params["density_win"] = 6000           # > the 12-point trace
    a.smooth_cache.clear()
    a.show_smooth.set(True)
    res = a._write_final_csvs(a.results, str(tmp_path), columns=["smoothed"])
    assert len(res["paths"]) == 1
    assert res["columns"] == ["Absorbance_smoothed"]
    assert [f for f in os.listdir(str(tmp_path))
            if f.endswith("_absorbance.csv")]


# ------------------------------------------------------------------- F4 ----
@gui
def test_bugfix_f4_unit_is_a_literal_replacement(a):
    """The unit was passed as re.sub's REPLACEMENT TEMPLATE, so backslash
    escapes were expanded: '$\\mu$m' and '\\AA' raised re.error once per
    keystroke and 'a\\b' silently became 'a<backspace>'."""
    a.xvar_choice.set(app.XVAR_CUSTOM)
    for unit in ("$\\mu$m", "\\AA", "a\\b", "\\1", "x\\", "\\n", "\\g<0>",
                 "\\\\", "&", "\\g<name>"):
        a.xvar_unit.set(unit)
        assert a._relabel("Y04 Arch29 12.50 GPa") == \
            "Y04 Arch29 12.50 " + unit
        assert a._relabel("Y04 Arch29 12.50 GPa [C]") == \
            "Y04 Arch29 12.50 " + unit + " [C]"
    a.xvar_unit.set("")                          # unitless: suffix dropped
    assert a._relabel("Y04 Arch29 12.50 GPa") == "Y04 Arch29 12.50"
    a.xvar_choice.set("Pressure (GPa)")
    assert a._relabel("Y04 Arch29 12.50 GPa") == "Y04 Arch29 12.50 GPa"


# ------------------------------------------------------------------- F5 ----
def _collide():
    """Four records, two distinct engine labels: 12.500 / 12.501 / 12.504
    all print '12.50 GPa'."""
    return [_res("Y04", "A", "12p5", 12.500),
            _res("Y04", "A", "12p50", 12.501),
            _res("Y04", "A", "12p500", 12.504),
            _res("Y04", "B", "20p0", 20.0)]


@gui
def test_bugfix_f5_counts_match_the_files_on_disk(a, tmp_path):
    """The branch dict was keyed by engine label, and labels are not
    unique: 4 files were written but the log line and the provenance
    sidecar counted the 2 distinct LABELS, claiming 2 compression CSVs
    that do not exist. R20: the C/D row is a rule about the ONE CSV each
    trace gets, so the count is simply how many files came back, and it is
    still per record and not per label."""
    a._finish_run([dict(r) for r in _collide()], [], "dest")
    for r in a.results:
        a.dvars[r["label"]].set(True)               # everything decompression
    a.export_products["defringed"].set(False)       # base columns only
    a.export_products["cd_tagged"].set(True)
    res = a._write_final_csvs(a.results, str(tmp_path))
    csvs = sorted(f for f in os.listdir(str(tmp_path))
                  if f.endswith(".csv"))
    assert len(csvs) == 4                           # was 2 labels
    assert all("_d_" in f.lower() for f in csvs)
    assert len(res["paths"]) == 4
    assert res["params"]["n"] == 4
    assert res["params"]["cd_names"] is True


@gui
def test_bugfix_f5_every_record_gets_its_own_file(a, tmp_path):
    """Three records print ONE engine label, so a label-keyed answer
    describes fewer points than there are files. The writer walks records,
    not labels: four points, four distinct names, each carrying the letter
    its own D box asks for."""
    a._finish_run([dict(r) for r in _collide()], [], "dest")
    assert len(a.dvars) == 2 < len(a.results) == 4    # the F5 trap itself
    for r in a.results:
        a.dvars[r["label"]].set(r["sample"] == "A")
    names = [os.path.basename(p) for p in
             a._write_final_csvs(a.results, str(tmp_path),
                                 columns=[], cd_names=True)["paths"]]
    assert sorted(names) == [
        "Y04_A_12p500_D_absorbance.csv",
        "Y04_A_12p50_D_absorbance.csv",
        "Y04_A_12p5_D_absorbance.csv",
        "Y04_B_20p0_C_absorbance.csv"]
    assert len(set(names)) == 4


# ---------------------------------------------------------------- F6 / F7 --
@gui
def test_bugfix_f6_tick_skips_while_a_modal_is_open(a, tmp_path, monkeypatch):
    """Tk after-jobs fire normally during a grab_set(), so a poll that
    landed while a dialog was open re-ran the pipeline and replaced
    self.results / trace_vars / dvars underneath it."""
    import tkinter as tk
    calls = []
    monkeypatch.setattr(a, "_rescan", lambda auto=False: calls.append(auto))
    a.auto_rescan.set(True)
    a.in_var.set(str(tmp_path))
    a._last_scan = (str(tmp_path), set())
    modal = tk.Toplevel(ROOT)
    modal.geometry("100x100+3200+100")
    ROOT.update()
    modal.grab_set()
    try:
        assert ROOT.grab_current() is not None
        a._auto_rescan_tick()
        a._cancel_auto_rescan()
        assert calls == []                      # not under the modal
    finally:
        modal.grab_release()
        modal.destroy()
        ROOT.update()
    a._auto_rescan_tick()                       # ... and it resumes after
    a._cancel_auto_rescan()
    assert calls == [True]


@gui
def test_bugfix_f7_tick_does_not_orphan_its_own_timer(a, tmp_path, monkeypatch):
    """The tick DROPPED its handle instead of cancelling it, so any entry
    that was not the timer firing left a queued job behind and the
    finally: armed a second one - 20 stray ticks took the after-queue from
    1 job to 21, of which 20 survived _cancel_auto_rescan()."""
    def jobs():
        return set(ROOT.tk.call("after", "info"))

    monkeypatch.setattr(a, "_rescan", lambda auto=False: None)
    a.in_var.set(str(tmp_path))
    a._last_scan = (str(tmp_path), set())
    a.auto_rescan.set(True)
    a._schedule_auto_rescan()
    base = jobs()
    assert a._auto_rescan_job in base
    for _ in range(20):
        a._auto_rescan_tick()
    assert len(jobs()) == len(base)             # exactly one job, still
    job = a._auto_rescan_job
    a._cancel_auto_rescan()
    a.auto_rescan.set(False)
    left = jobs()
    assert job not in left
    assert len(left) == len(base) - 1           # nothing survived the cancel


# ------------------------------------------------------------------- F8 ----
def _fake_hdrop(paths):
    """A genuine DROPFILES block, byte-for-byte what Explorer hands over."""
    import ctypes
    k32 = ctypes.windll.kernel32
    k32.GlobalAlloc.restype = ctypes.c_void_p
    k32.GlobalLock.restype = ctypes.c_void_p
    k32.GlobalLock.argtypes = [ctypes.c_void_p]
    k32.GlobalUnlock.argtypes = [ctypes.c_void_p]
    blob = ("\0".join(paths) + "\0\0").encode("utf-16-le")
    data = struct.pack("<IiiII", 20, 0, 0, 0, 1) + blob   # fWide = 1
    h = k32.GlobalAlloc(0x0002, len(data))
    p = k32.GlobalLock(ctypes.c_void_p(h))
    ctypes.memmove(p, data, len(data))
    k32.GlobalUnlock(ctypes.c_void_p(h))
    return h


def _real_shell32():
    import ctypes
    from ctypes import wintypes
    sh = ctypes.windll.shell32
    sh.DragQueryFileW.argtypes = [wintypes.HANDLE, wintypes.UINT,
                                  wintypes.LPWSTR, wintypes.UINT]
    sh.DragQueryFileW.restype = wintypes.UINT
    sh.DragFinish.argtypes = [wintypes.HANDLE]
    return sh


@gui
@_win
def test_bugfix_f8_bogus_hdrop_is_rejected_and_a_real_drop_still_works(
        a, tmp_path, monkeypatch):
    """The window has DragAcceptFiles on, so any process can PostMessage
    WM_DROPFILES with a garbage wparam. DragQueryFileW on an invalid
    handle fail-fasted the whole process with 0xC0000409 - uncatchable by
    the try/except in _drop_wndproc. Measured before the fix: hdrop=1 and
    hdrop=2 both killed the interpreter (returncode 0xC0000409).  The last
    assertion is the positive control: validation must not break drops."""
    monkeypatch.setattr(a, "_shell32", _real_shell32(), raising=False)
    for hdrop in (0, 1, 2, 0xDEADBEEF, -1, 0x7FFFFFFFFFFF):
        assert a._drop_paths(hdrop) == [], hex(hdrop) if hdrop > 0 else hdrop
    want = [str(tmp_path), os.path.join(str(tmp_path), "a.txt")]
    assert a._drop_paths(_fake_hdrop(want)) == want


# ---------------------------------------------------------------- C1 / C2 --
@gui
def test_bugfix_c1_branch_label_is_one_capped_line(a):
    """legend_branch_c / _d are free-text entries whose value went into the
    legend verbatim: 'a\\nb' gave a two-line key and 'X'*500 a
    500-character one."""
    a.legend_branch_tags.set(True)
    a.legend_branch_c.set("a\nb")
    assert a._branch_label("C") == "a b"
    a.legend_branch_c.set("first\r\n\tsecond")
    assert a._branch_label("C") == "first second"
    a.legend_branch_c.set("X" * 500)
    assert len(a._branch_label("C")) == app.BRANCH_LABEL_MAX
    a.legend_branch_c.set("  \n  ")
    assert a._branch_label("C") == "C"          # blank -> the letter
    a.legend_branch_c.set(" comp ")
    assert a._branch_label("C") == "comp"       # ordinary case unchanged
    a.legend_branch_c.set("two  spaces")
    assert a._branch_label("C") == "two  spaces"


@gui
def test_bugfix_c2_chip_width_is_capped(a, tmp_path, monkeypatch):
    """_FIELD_W followed the Variable name, so a 120-character name gave
    EVERY chip combobox width=120 and blew the dialog layout."""
    monkeypatch.setattr(app.simpledialog, "askstring", lambda *x, **k: "V")
    monkeypatch.setattr(app.messagebox, "showinfo", lambda *x, **k: None)
    a.xvar_choice.set(app.XVAR_CUSTOM)
    a.xvar_name.set("V" * 120)
    with _namefmt(a, _make_files(tmp_path, _BEAMLINE_NAMES)) as d:
        vals, width = _chip_values(d)
        assert vals and width == 24


# ------------------------------------------------------------------- C3 ----
@gui
def test_bugfix_c3_preview_cap_is_disclosed(a, tmp_path, monkeypatch):
    """The preview parses at most 500 files, and 'matched N / 500' looked
    like the whole folder.  A small folder must say nothing extra."""
    monkeypatch.setattr(app.messagebox, "showinfo", lambda *x, **k: None)
    big = tmp_path / "big"
    big.mkdir()
    n = app.NAMEFMT_PREVIEW_CAP + 20
    _make_files(big, ["vis_Y04_Arch29_%dp5_s_C.001" % i for i in range(n)])
    with _namefmt(a, str(big), save_as=False) as d:
        lbl = _matched_text(d)
    assert lbl.startswith("matched ")
    assert "/ %d files" % app.NAMEFMT_PREVIEW_CAP in lbl
    assert "first %d of %d" % (app.NAMEFMT_PREVIEW_CAP, n) in lbl

    small = tmp_path / "small"
    small.mkdir()
    with _namefmt(a, _make_files(small, _BEAMLINE_NAMES), save_as=False) as d:
        assert _matched_text(d) == "matched 3 / 3 files"


def test_no_dialog_outlived_this_module():
    """Cheap tripwire: the module opens real Toplevels, and a leaked one
    would tax every later relayout in the session."""
    assert toplevels() == []
