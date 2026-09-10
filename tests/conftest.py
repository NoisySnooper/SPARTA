"""Shared pytest setup for the SPARTA suite.

Five jobs:

* put the tool directory on sys.path so the tests can import
  engine / fringe_apply / app no matter where pytest is launched from;

* point the app at a throwaway settings file so a test run can never write
  into the live ``.quicklook_settings.json`` (it used to clobber the saved
  folders and theme);

* point the crash log at a throwaway file for the same reason.  R17 gave
  the App a ``report_callback_exception`` handler that appends every dead
  Tk callback to ``sparta_errors.log`` beside the program, and a suite that
  deliberately raises inside callbacks would otherwise grow that file in
  the repository.  The session fixture below redirects it and then checks
  that nothing wrote one anyway;

* own the ONE off-screen Tk root and the ONE App the whole GUI suite
  shares.  Every module used to build its own App on the shared root, and
  every relayout, theme switch and ``update()`` then paid for all eight
  trees: a single theme switch costs ~1.9 s with one App and ~17 s with
  eight.  That multiplier was most of the old suite's wall time;

* keep that App quiet between tests: the after-jobs an App queues for
  itself (the coalesced repaint, the undo snapshot, the rescan poll) are
  cancelled and the shipped defaults restored, so no test pays for the
  previous test's repaint or inherits its state.

A module that uses the shared App sets ``USES_APP = True`` at module level;
that is what arms the reset fixture below.  See ``tests/TESTING_POLICY.md``.
"""
import contextlib
import os
import sys
import tempfile

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import app                                              # noqa: E402
import formulas as _F                                   # noqa: E402
import smoothing as _S                                  # noqa: E402

_TMP_DIR = tempfile.mkdtemp(prefix="sparta_test_")
app.SETTINGS_PATH = os.path.join(_TMP_DIR, "settings.json")

# The crash log, redirected at IMPORT and not only in the fixture below: the
# module constant is read by App._report_callback_error through a getattr
# fallback, so a handler that fires before any fixture has run still lands in
# the tempdir rather than in the tool folder.
TEST_ERROR_LOG = os.path.join(_TMP_DIR, "sparta_errors.log")
app.ERROR_LOG_PATH = TEST_ERROR_LOG
app.App._error_log_path = TEST_ERROR_LOG       # every instance, later ones too

#: the file the suite must never create.  ``app.TOOL_DIR`` is the program
#: folder, which for a source checkout is the repository root.
REPO_ERROR_LOG = os.path.join(app.TOOL_DIR, "sparta_errors.log")

OFF = "+3200+100"          # the project's off-screen probe position

try:
    import tkinter as tk
    # This Windows Store Python cannot spin up a SECOND Tk interpreter, so
    # there is exactly one root for the whole session and it stays withdrawn.
    ROOT = tk._default_root or tk.Tk()
    ROOT.withdraw()
    HAVE_GUI = True
except Exception:                                       # no display / no Tk
    tk = None
    ROOT = None
    HAVE_GUI = False

gui = pytest.mark.skipif(not HAVE_GUI, reason="no Tk display")

_APP = None


# --------------------------------------------------------------- the App ---
def quiesce(a):
    """Cancel the after-jobs an App queues for itself.

    ``_redraw`` coalesces onto ``after_idle`` and ``_redraw_now`` arms a
    450 ms undo snapshot; left alone, the next ``update()`` -- in any test --
    pays for a full replot it never asked for."""
    for attr in ("_redraw_after", "_snap_after"):
        job = getattr(a, attr, None)
        if job:
            try:
                a.root.after_cancel(job)
            except Exception:
                pass
            setattr(a, attr, None)
    try:
        a._cancel_auto_rescan()
    except Exception:
        pass


def shared_app():
    """THE App.  Built lazily on first use, never rebuilt.

    Lazy on purpose: the FIRST App constructed on the withdrawn root is what
    gives that root its geometry, so nothing may flush Tk idles before it."""
    global _APP
    if _APP is None:
        _APP = app.App(ROOT)
        quiesce(_APP)
    return _APP


def close_toplevels():
    """Destroy every dialog still standing, whoever opened it."""
    if not HAVE_GUI:
        return
    for w in list(ROOT.winfo_children()):
        if isinstance(w, tk.Toplevel):
            try:
                w.grab_release()
            except Exception:
                pass
            try:
                w.destroy()
            except Exception:
                pass


def reset_app(a):
    """Put the shared App back to its shipped defaults.

    Cheap by construction: it assigns variables and clears dicts, it never
    rebuilds a widget tree, and a variable already at its default is not
    re-set (writing ``theme_mode`` alone costs ~1.9 s)."""
    close_toplevels()
    quiesce(a)
    # T2: the two formula refreshes at the end of this function rebuild the
    # formula rows and re-run the Y pickers, and the NEXT test's update()
    # pays for the relayout they queue.  A test that never touched the
    # formula list leaves the shipped quantities, an empty pick and an
    # untouched cache, so both calls reproduce what is already on screen.
    # Read BEFORE the preset loop below, which puts active_qty back itself.
    _qty_dirty = (a.quantities != _F.default_quantities()
                  or a._qty_sel.get() != ""
                  or a.active_qty.get() != ""
                  or bool(a._qty_cache)
                  or a._qty_cache_sig is not None
                  or "quantities" in a.settings)
    reg = a._preset_registry()
    for k, want in a._defaults.items():
        v = reg.get(k)
        if v is None:
            continue
        try:
            if v.get() != want:
                v.set(want)
        except Exception:
            pass
    a.results = []
    a.trace_vars.clear()
    a.dvars.clear()
    a._sel_trace = None
    a._last_scan = None
    a._skipped_count = 0
    a.in_var.set("")               # not a preset var: it is workflow state
    a.auto_rescan.set(False)
    a.rescan_interval.set(30)
    # R19: the EXPORT > DATA FILES ticks are settings state, not
    # preset state, so the preset loop above cannot restore them and
    # one test that ticks C/D-tagged would otherwise decide what the
    # next test writes to disk
    for _k, _d in getattr(app, "EXPORT_PRODUCT_DEFAULTS", {}).items():
        _v = getattr(a, "export_products", {}).get(_k)
        try:
            if _v is not None and _v.get() != _d:
                _v.set(_d)
        except Exception:
            pass
    # R20: Crop belongs to one export, not to the next one
    for _v in (a.crop_on, a.crop_min, a.crop_max):
        try:
            _v.set(False if _v is a.crop_on else "")
        except Exception:
            pass
    # the two status lines: cleared AND unpacked, the way _show_status
    # leaves them, so a test that asserts an empty section is not looking
    # at a row the previous test packed (R20 2.5)
    for _sl in ("_data_status", "_stl_status", "_export_status"):
        try:
            a._show_status(getattr(a, _sl, None), "")
        except Exception:
            pass
    a.quantities = _F.default_quantities()
    # naming profiles are global settings state: a test that commits one
    # would otherwise decide how the NEXT test's folder parses
    for key in ("quantities", "profiles", "active_profile",
                "name_overrides", "export_products"):
        a.settings.pop(key, None)
    a._qty_sel.set("")
    a._label_edited["ylabel"] = False
    a._label_edited["xlabel"] = False
    a.smooth_params.clear()
    a.smooth_params.update(_S.DEFAULTS)
    for cache in ("smooth_cache", "notch_cache", "_nt_cache"):
        try:
            getattr(a, cache).clear()
        except Exception:
            pass
    while len(a.sessions) > 1:                 # test_sessions opens tabs
        try:
            a._close_session(len(a.sessions) - 1)
        except Exception:
            break
    if _qty_dirty:
        a._refresh_quantity_rows()
        a._refresh_ydata_values()
    quiesce(a)


# ------------------------------------------------------------- crash log ---
@pytest.fixture(scope="session", autouse=True)
def _no_error_log_in_the_repo():
    """Keep the R17 crash log out of the tool folder, and prove it.

    Two halves.  Going in, the module constant and the App's per-instance
    override both point into the session tempdir, so a test that raises
    inside a Tk callback on purpose writes there.  Coming out, the tool
    folder is checked: a ``sparta_errors.log`` that appeared, or grew,
    during the run is a real escape and the session says so with the file's
    own text, because a silent one would ship in the next zip.
    """
    app.ERROR_LOG_PATH = TEST_ERROR_LOG
    app.App._error_log_path = TEST_ERROR_LOG
    try:
        before = os.path.getsize(REPO_ERROR_LOG)
    except OSError:
        before = None                      # the normal case: no such file
    yield
    try:
        after = os.path.getsize(REPO_ERROR_LOG)
    except OSError:
        return                             # still no such file: nothing wrote
    if before is not None and after == before:
        return                             # it predates this run, untouched
    try:
        with open(REPO_ERROR_LOG, encoding="utf-8", errors="replace") as fh:
            body = fh.read()[-4000:]
    except OSError as exc:                 # unreadable, but it is still there
        body = "<could not read: %r>" % (exc,)
    pytest.fail(
        "the suite wrote %s (%d bytes, was %s). A test raised inside a Tk "
        "callback and the handler's redirect was bypassed. Delete the file "
        "once the cause is fixed.\n%s" % (REPO_ERROR_LOG, after, before, body),
        pytrace=False)


@pytest.fixture(autouse=True)
def _shared_app_reset(request):
    """Hand every test a clean App and leave one behind.

    Only arms for modules that declare ``USES_APP = True``; the pure-module
    files (engine, formulas, fringe core / apply / parity) never touch Tk
    and must not pay for it."""
    yield
    if _APP is not None and getattr(request.module, "USES_APP", False):
        reset_app(_APP)


@pytest.fixture
def fresh_app():
    """Build a SECOND App on the shared root, for the rare test that must
    prove what a NEW launch reads back from settings.

    Its widgets are destroyed at teardown: an extra tree left standing would
    tax every later relayout in the session."""
    if not HAVE_GUI:
        pytest.skip("no Tk display")
    born = []

    def build():
        before = set(str(w) for w in ROOT.winfo_children())
        a = app.App(ROOT)
        born.append((a, before))
        return a

    yield build
    for a, before in born:
        quiesce(a)
        for w in list(ROOT.winfo_children()):
            if str(w) not in before:
                try:
                    w.destroy()
                except Exception:
                    pass


# ------------------------------------------------------------- off-screen ---
@contextlib.contextmanager
def offscreen(a):
    """Park every Toplevel born inside the block off the visible desktop.

    Both kinds are covered: the ones ``_center_on_root`` sizes and the ones
    that size themselves.  A test run must never flash a window at the
    user."""
    orig_tl = tk.Toplevel
    orig_center = app.App._center_on_root

    class _Off(orig_tl):
        def __init__(self, *args, **kw):
            orig_tl.__init__(self, *args, **kw)
            try:
                self.geometry(OFF)
            except tk.TclError:
                pass

    def _center(win, w, h):
        win.geometry("%dx%d%s" % (int(w), int(h), OFF))

    tk.Toplevel = _Off
    a._center_on_root = _center
    try:
        yield
    finally:
        tk.Toplevel = orig_tl
        try:
            del a._center_on_root
        except AttributeError:
            pass
        assert app.App._center_on_root is orig_center


@contextlib.contextmanager
def realized(size="1920x1080"):
    """Give the shared root REAL geometry for the length of the block, at the
    off-screen probe position, then put it back.  Nothing is ever visible:
    +3200+100 is outside the desktop."""
    was = ROOT.winfo_geometry()
    ROOT.geometry(size + OFF)
    ROOT.deiconify()
    for _ in range(3):
        ROOT.update_idletasks()
        ROOT.update()
    try:
        yield
    finally:
        ROOT.withdraw()
        ROOT.geometry(was)
        ROOT.update_idletasks()


def open_dialog(fn, *args):
    """Call a dialog opener and return the Toplevel it created."""
    before = set(str(w) for w in ROOT.winfo_children())
    fn(*args)
    ROOT.update_idletasks()
    new = [w for w in ROOT.winfo_children()
           if str(w) not in before and w.winfo_class() == "Toplevel"]
    assert new, "no Toplevel appeared"
    return new[-1]


def toplevels():
    return [w for w in ROOT.winfo_children() if isinstance(w, tk.Toplevel)]


# ---------------------------------------------------------------- walkers ---
def walk(w):
    """Every widget in the tree rooted at w, w first."""
    out = [w]
    for c in w.winfo_children():
        out.extend(walk(c))
    return out


def texts(w):
    got = []
    for x in walk(w):
        try:
            t = x.cget("text")
        except tk.TclError:
            continue
        if isinstance(t, str) and t:
            got.append(t)
    return got


def by_text(top, text):
    for w in walk(top):
        try:
            if w.cget("text") == text:
                return w
        except tk.TclError:
            pass
    return None


def kids(w, cls=None, text=None):
    """Descendants matching a widget class and/or a text prefix."""
    out = []
    for c in walk(w)[1:]:
        try:
            ok = (cls is None or c.winfo_class() == cls)
            if ok and text is not None:
                ok = str(c.cget("text")).startswith(text)
            if ok:
                out.append(c)
        except tk.TclError:
            pass
    return out


def img(w):
    """cget('image') is a 1-tuple on ttk widgets and a string on tk ones."""
    v = w.cget("image")
    if isinstance(v, (tuple, list)):
        v = v[0] if v else ""
    return str(v)


# ----------------------------------------------------------- test records ---
def make_result(label, pval, n=40, dac="D", sample="S", pstr=None, tag=None,
                wl=None, samp=None, bg=None, dark=None, absorb=None):
    """A minimal valid engine-style result dict with real absorbance.

    Every GUI module used to carry its own near-identical copy of this."""
    import numpy as np
    wl = np.linspace(400.0, 1000.0, n) if wl is None else np.asarray(wl, float)
    n = wl.size
    d = np.ones(n) if dark is None else np.asarray(dark, float)
    b = np.full(n, 10.0) if bg is None else np.asarray(bg, float)
    s = np.full(n, 5.0) if samp is None else np.asarray(samp, float)
    if absorb is None:
        absorb = np.linspace(0.1, 1.2, n)
    return {"label": label, "dac": dac, "sample": sample,
            "pressure_str": pstr if pstr is not None else "%gp0" % pval,
            "pressure_val": pval, "rep": 1, "branch_tag": tag,
            "wl": wl, "wn": 1e7 / wl, "absorbance": np.asarray(absorb, float),
            "dark_c": d, "bg_c": b, "samp_c": s}
