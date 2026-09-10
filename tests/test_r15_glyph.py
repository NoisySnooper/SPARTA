"""R15-A: the role glyphs -- refine math, drag semantics, draw state.

Matthew's report was that the rectangle and diamond fits "don't find the peaks
I drag them to".  Two defects sat behind it, and this file pins both halves of
the fix (his defringe_dac.py 12269-12507 and 14018-14125):

  * the REFINE: the window is anchored on the nearest DETECTED peak, spans
    +-3 um of absolute n*t, holds its baseline fixed at the whole curve's 5th
    percentile, and falls back to that nearest peak when the fit is rejected;
    the Shared mode deblends an apex plus a shoulder with ONE shared sigma;
    every landed fit is stored for the overlay;
  * the DROP: a released drag is a manual placement that immediately solves
    and writes n sample / t / d2 back, so the model stems move onto the glyph;

plus the glyph state the reader sees: two fills, a dashed guide under a manual
glyph, the stagger that makes a coincident Sample pair separable, and status
lines that tell a refine from a fallback.

The refine tests build tiny synthetic V curves rather than running detection --
an FFT per channel per trace is what tests/test_fringe_ui.py avoids too.
Runs against the suite's ONE shared App (tests/conftest.py).
"""
import numpy as np
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
    """The workbench with a clean slate, put back afterwards -- including the
    Stack boxes and the three settings keys the write-back owns."""
    w = a._fringe
    w.build()                     # the workbench is lazy; these tests draw
    keep = (dict(w._chan), dict(w._trace), list(w._series), w._label,
            list(a.results), w.fitmode_v.get(),
            {k: v.get() for k, v in (("ns", w.ns_v), ("t", w.t_v),
                                     ("d1", w.d1_v), ("d2", w.d2_v))},
            {k: w.settings.get(k) for k in ("fr_n_sample", "fr_t_um",
                                            "fr_d2_um", "fr_fit_mode")})
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
    w.fitmode_v.set(keep[5])
    w._suspend = True
    try:
        for k, var in (("ns", w.ns_v), ("t", w.t_v), ("d1", w.d1_v),
                       ("d2", w.d2_v)):
            var.set(keep[6][k])
    finally:
        w._suspend = False
    for k, v in keep[7].items():
        if v is None:
            w.settings.pop(k, None)
        else:
            w.settings[k] = v


# ---------------------------------------------------------------------------
# synthetic channels: a V curve with known Gaussians and known detected peaks
# ---------------------------------------------------------------------------
def _gauss(x, A, mu, sig):
    return A * np.exp(-0.5 * ((x - mu) / sig) ** 2)


def _curve(peaks, lo=2.0, hi=60.0, dx=0.25, floor=0.01):
    """(x, y, peak_indices) for `peaks` = [(A, mu, sig), ...].

    The detected peaks are the GRID points nearest each centre, so every
    true centre sits off the discrete grid by up to half a bin -- which is
    the whole reason the refine exists.  Indices come back strength-first,
    the order `peaks_sorted` uses.
    """
    x = np.arange(lo, hi + dx, dx)
    y = np.full(x.size, float(floor))
    for A, mu, sig in peaks:
        y = y + _gauss(x, A, mu, sig)
    idx = [int(np.argmin(np.abs(x - mu))) for _A, mu, _s in peaks]
    order = sorted(range(len(peaks)), key=lambda i: -peaks[i][0])
    return x, y, [idx[i] for i in order]


def _fake_channels(fw, monkeypatch, curves):
    """Stand in for detection.  `curves` maps a channel to (x, y, peaks),
    shaped like a real computed channel so a redraw still draws."""
    def compute(chan):
        rec = fw._record()
        if rec is None or chan not in curves:
            return None
        x, y, pk = curves[chan]
        return {"cfg": fw._cfg_for(rec), "nt": None, "pv": None, "corr": [],
                "defaults": [], "removed": 0.0, "fft_info": None,
                "peaks": np.asarray(pk, dtype=int),
                "nt_um": np.asarray(x, float), "V": np.asarray(y, float)}
    monkeypatch.setattr(fw, "_compute", compute, raising=False)


def _load(a, fw, monkeypatch, sample=None, background=None):
    """One trace loaded, with the given synthetic channels."""
    a.results = [make_result("R1", 1.0)]
    fw._label = "R1"
    fw._seed_said.clear()
    curves = {}
    if sample is not None:
        curves["Sample"] = sample
    if background is not None:
        curves["Background"] = background
    _fake_channels(fw, monkeypatch, curves)
    return fw._tr()


class _Ev:
    """A matplotlib-shaped mouse event, only the fields the handlers read."""

    def __init__(self, **kw):
        self.button = 1
        self.inaxes = None
        self.xdata = None
        self.ydata = None
        self.x = 0
        self.y = 0
        self.guiEvent = None
        self.__dict__.update(kw)


# ---------------------------------------------------------------------------
# the single-peak refine
# ---------------------------------------------------------------------------
def test_single_refine_anchors_on_the_nearest_peak_not_the_model_target(
        a, fw, monkeypatch):
    """The window follows the DATA, not the prediction.

    The stack's n*t is routinely a bin or more off the measured peak; a
    window centred on the target clips the peak's far flank (his "right half
    not fitted"), and at the old +-max(2.5*hw, 3) = 7.5 um it could walk to
    the next hump altogether.  Anchored on the nearest detected peak, +-3 um,
    it lands on the peak that is there.
    """
    x, y, pk = _curve([(1.0, 20.4, 0.9), (1.6, 27.5, 0.9)])
    tr = _load(a, fw, monkeypatch, sample=(x, y, pk))

    val, how = fw._refine_peak("Sample", "sample", 23.2)
    assert how == "fit"
    assert val == pytest.approx(20.4, abs=0.05)

    g = tr["gauss"]["sample"]
    assert g["panel"] == "Sample"
    assert g["mu"] == pytest.approx(val)
    # the window is the nearest detected peak (20.5) +- 3 um, in absolute
    # micron -- so the taller 27.5 hump is outside it and cannot pull the fit
    assert g["x0"] == pytest.approx(17.5, abs=0.3)
    assert g["x1"] == pytest.approx(23.5, abs=0.3)
    assert g["x1"] < 27.5


def test_the_refine_baseline_is_the_whole_curves_fifth_percentile(
        a, fw, monkeypatch):
    """c is FIXED, not fitted: between packed fringes the level is the
    neighbours' tails, so a free floor absorbs them and drifts."""
    x, y, pk = _curve([(1.0, 20.4, 0.9)], floor=0.05)
    tr = _load(a, fw, monkeypatch, sample=(x, y, pk))
    fw._refine_peak("Sample", "sample", 20.0)
    assert tr["gauss"]["sample"]["c"] == pytest.approx(
        float(np.percentile(y, 5.0)))


def test_a_rejected_refine_returns_the_nearest_detected_peak(
        a, fw, monkeypatch):
    """The old code kept the glyph where it was and said every glyph kept
    its position.  A rejected fit now hands back something measured, and
    says which outcome it was."""
    # a curve too short to fit: three samples are the minimum, this has two
    tr = _load(a, fw, monkeypatch,
               sample=(np.array([12.0, 13.0]), np.array([0.2, 0.9]), [1]))
    val, how = fw._refine_peak("Sample", "sample", 30.0)
    assert (val, how) == (13.0, "peak")
    assert tr["gauss"]["sample"] is None


def test_a_channel_with_no_peaks_anchors_on_the_model_target(
        a, fw, monkeypatch):
    """No detected peak is not no data: the target is the anchor of last
    resort, and the fit still lands."""
    x, y, _pk = _curve([(1.0, 20.4, 0.9)])
    _load(a, fw, monkeypatch, sample=(x, y, []))
    val, how = fw._refine_peak("Sample", "sample", 20.0)
    assert how == "fit"
    assert val == pytest.approx(20.4, abs=0.05)


# ---------------------------------------------------------------------------
# the Sample pair: Distinct vs Shared
# ---------------------------------------------------------------------------
def test_shared_mode_deblends_a_shoulder_with_one_width(a, fw, monkeypatch):
    """Shared is his apex-plus-shoulder path: the residual of the apex fit
    seeds a second Gaussian, and the joint fit ties both to ONE sigma with
    an ordered offset, so the pair can never come back inverted."""
    x, y, pk = _curve([(1.0, 24.0, 1.1), (0.45, 20.6, 1.1)])
    tr = _load(a, fw, monkeypatch, sample=(x, y, pk))
    fw.fitmode_v.set("shared")

    out = fw._refine_pair(20.0, 24.5)
    assert out["sample"][1] == "fit" and out["sampledia"][1] == "fit"
    assert out["sample"][0] == pytest.approx(20.6, abs=0.25)
    assert out["sampledia"][0] == pytest.approx(24.0, abs=0.25)
    # ordered by construction (m2 = m1 + delta, delta >= 0)
    assert out["sample"][0] <= out["sampledia"][0]

    g_s, g_d = tr["gauss"]["sample"], tr["gauss"]["sampledia"]
    assert g_s["sig"] == pytest.approx(g_d["sig"]), "one shared width"
    pair = tr["gauss"]["_sample_pair"]
    assert pair is not None
    assert pair["mu1"] <= pair["mu2"]
    assert pair["sig"] == pytest.approx(g_s["sig"])
    assert pair["c"] == pytest.approx(float(np.percentile(y, 5.0)))


def test_distinct_mode_fits_each_role_alone_and_stores_no_envelope(
        a, fw, monkeypatch):
    x, y, pk = _curve([(1.0, 20.4, 0.8), (1.0, 34.6, 1.4)])
    tr = _load(a, fw, monkeypatch, sample=(x, y, pk))
    fw.fitmode_v.set("distinct")

    out = fw._refine_pair(20.0, 35.0)
    assert out["sample"][0] == pytest.approx(20.4, abs=0.05)
    assert out["sampledia"][0] == pytest.approx(34.6, abs=0.05)
    assert tr["gauss"]["_sample_pair"] is None, "no joint envelope"
    # independent widths: each role kept its own peak's width
    assert tr["gauss"]["sample"]["sig"] != pytest.approx(
        tr["gauss"]["sampledia"]["sig"], rel=0.05)


# ---------------------------------------------------------------------------
# auto vs manual: what the model may move
# ---------------------------------------------------------------------------
def test_autosnap_moves_auto_roles_only(a, fw, monkeypatch):
    """Auto roles track the model; a glyph you placed is never touched."""
    x, y, pk = _curve([(1.0, 20.4, 0.9), (1.0, 30.6, 0.9)])
    bx, by, bpk = _curve([(1.0, 40.6, 1.0)])
    tr = _load(a, fw, monkeypatch, sample=(x, y, pk),
               background=(bx, by, bpk))
    monkeypatch.setattr(fw, "_pred_paths",
                        lambda _p: {"sample": 20.0, "sampledia": 30.0,
                                    "mediumdia": 40.0}, raising=False)
    fw.fitmode_v.set("distinct")
    tr["roles"]["sample"] = {"nt_um": 5.0, "auto": False}
    tr["roles"]["sampledia"] = {"nt_um": 31.5, "auto": True, "seed": True}

    out = fw._autosnap_roles(p={})
    assert tr["roles"]["sample"] == {"nt_um": 5.0, "auto": False}
    assert "sample" not in out, "a manual role is never re-fit"
    assert tr["roles"]["sampledia"]["nt_um"] == pytest.approx(30.6, abs=0.05)
    assert tr["roles"]["sampledia"]["auto"] is True
    assert tr["roles"]["sampledia"].get("seed"), \
        "a re-refit seed is still the workbench's guess, not your work"
    assert tr["roles"]["mediumdia"]["nt_um"] == pytest.approx(40.6, abs=0.05)

    # ...and a Fit peaks press claims them: keep_seed off drops the mark
    fw._autosnap_roles(p={}, keep_seed=False)
    assert not tr["roles"]["sampledia"].get("seed")


def test_an_auto_sample_right_of_the_diamond_snaps_onto_it(
        a, fw, monkeypatch):
    """A = n_s*t can never exceed C = A + medium.  An AUTO rectangle that
    lands right of the diamond is put ON it (layer 2 at zero); a dragged one
    is left where it was dropped -- the drop handler warns instead."""
    x, y, pk = _curve([(1.0, 40.6, 0.9), (1.0, 20.4, 0.9)])
    tr = _load(a, fw, monkeypatch, sample=(x, y, pk))
    monkeypatch.setattr(fw, "_pred_paths",
                        lambda _p: {"sample": 40.0, "sampledia": 25.0},
                        raising=False)
    fw.fitmode_v.set("distinct")
    tr["roles"]["sampledia"] = {"nt_um": 25.0, "auto": False}

    out = fw._autosnap_roles(p={})
    assert out["sample"] == (25.0, "order")
    assert tr["roles"]["sample"]["nt_um"] == pytest.approx(25.0)
    assert tr["gauss"]["sample"] is None, "the snap is not a fit"

    # the same landing, dragged: it stays put
    tr["roles"]["sample"] = {"nt_um": 40.6, "auto": False}
    fw._autosnap_roles(p={})
    assert tr["roles"]["sample"]["nt_um"] == pytest.approx(40.6)


def test_a_committed_stack_edit_refits_the_auto_glyphs(a, fw, monkeypatch):
    """His GUI re-snaps inside every _update.  Here the same thing hangs off
    the committed edits, so the auto glyphs track the model without a fit
    running on a half-typed number."""
    x, y, pk = _curve([(1.0, 20.4, 0.9), (1.0, 30.6, 0.9)])
    tr = _load(a, fw, monkeypatch, sample=(x, y, pk))
    monkeypatch.setattr(fw, "_pred_paths",
                        lambda _p: {"sample": 20.0, "sampledia": 30.0},
                        raising=False)
    fw.fitmode_v.set("distinct")
    tr["roles"]["sample"] = {"nt_um": 4.0, "auto": False}
    tr["roles"]["sampledia"] = {"nt_um": 12.0, "auto": True}

    fw._commit_stack()

    assert tr["roles"]["sample"]["nt_um"] == pytest.approx(4.0)
    assert tr["roles"]["sampledia"]["nt_um"] == pytest.approx(30.6, abs=0.05)
    fw._request_redraw(now=True)      # flush the debounced one it queued


def test_the_stack_handlers_and_widgets_route_through_the_commit(
        a, fw, monkeypatch):
    """Return, focus out, a spinbox arrow and a combobox pick are the four
    committed edits; a keystroke stays a keystroke."""
    calls = []
    monkeypatch.setattr(fw, "_commit_stack",
                        lambda *_a: calls.append(1), raising=False)
    fw._suspend = True
    try:
        fw.total_v.set("20")
    finally:
        fw._suspend = False
    fw._on_d_edit("t")
    fw._on_total_edit()
    fw._on_layer2()
    assert len(calls) == 3

    # Tk reports a bound <Return> back as its canonical <Key-Return>
    bound = set(fw._nmed_e.bind())
    assert bound & {"<Return>", "<Key-Return>"}
    assert "<FocusOut>" in bound
    assert "<<ComboboxSelected>>" in fw._l2_cb.bind()


# ---------------------------------------------------------------------------
# the drop: place, solve, write back
# ---------------------------------------------------------------------------
def test_a_released_drag_places_the_glyph_and_writes_the_solve_back(
        a, fw, monkeypatch):
    """His _on_release + _apply_solved, end to end.

    The glyph stays at the EXACT drop x, turns manual, and the solve from
    the three glyph positions is written into n sample / t / d2 -- which is
    what walks the model stems onto the glyphs.  d1 is yours and stays.
    """
    x, y, pk = _curve([(1.0, 21.0, 0.9), (1.0, 30.6, 0.9)])
    bx, by, bpk = _curve([(1.0, 40.6, 1.0)])
    tr = _load(a, fw, monkeypatch, sample=(x, y, pk),
               background=(bx, by, bpk))
    monkeypatch.setattr(fw, "_pred_paths",
                        lambda _p: {"sample": 21.0, "sampledia": 30.6,
                                    "mediumdia": 40.6}, raising=False)
    for role, val in (("sample", 18.0), ("sampledia", 30.6),
                      ("mediumdia", 40.6)):
        tr["roles"][role] = {"nt_um": val, "auto": True}
    fw._suspend = True
    try:
        fw.d1_v.set("0")
    finally:
        fw._suspend = False
    said = []
    monkeypatch.setattr(fw, "_status",
                        lambda msg, **kw: said.append(msg), raising=False)

    p = fw._stack_params(fw._record())
    want = fringe_optics.solve_paths(21.0, 30.6, 40.6, p["n_layer2"],
                                     p["n_medium"])

    fw._drag = {"kind": "role", "role": "sample", "chan": "Sample",
                "moved": False}
    fw._on_motion(_Ev(xdata=21.0))
    fw._on_release(_Ev(xdata=21.0))

    assert fw._drag is None
    assert tr["roles"]["sample"]["nt_um"] == pytest.approx(21.0), \
        "the drop point is the placement -- no snap"
    assert tr["roles"]["sample"]["auto"] is False
    assert tr["gauss"]["sample"] is None, "a manual glyph carries no fit"
    assert float(fw.ns_v.get()) == pytest.approx(want["n_s"], abs=5e-4)
    assert float(fw.t_v.get()) == pytest.approx(want["t_s"], abs=5e-4)
    assert float(fw.d2_v.get()) == pytest.approx(want["t_layer2"], abs=5e-4)
    assert float(fw.d1_v.get()) == pytest.approx(0.0), "d1 is yours"
    assert any("applied" in s for s in said), said


def test_a_press_with_no_travel_leaves_the_glyph_alone(a, fw, monkeypatch):
    """Only a real drag is a placement; a press that goes nowhere is not."""
    x, y, pk = _curve([(1.0, 21.0, 0.9)])
    tr = _load(a, fw, monkeypatch, sample=(x, y, pk))
    tr["roles"]["sample"] = {"nt_um": 21.0, "auto": True, "seed": True}
    fw._drag = {"kind": "role", "role": "sample", "chan": "Sample",
                "moved": False}
    fw._on_release(_Ev(xdata=21.0))
    assert tr["roles"]["sample"] == {"nt_um": 21.0, "auto": True,
                                     "seed": True}
    fw._request_redraw(now=True)      # flush the debounced one it queued


def test_an_unphysical_drop_keeps_the_glyph_and_warns_in_the_solve_status(
        a, fw, monkeypatch):
    """Dropped right of the sample diamond: the glyph stays where it was
    put, and the solve-status carries the warning."""
    x, y, pk = _curve([(1.0, 21.0, 0.9), (1.0, 30.6, 0.9)])
    bx, by, bpk = _curve([(1.0, 40.6, 1.0)])
    tr = _load(a, fw, monkeypatch, sample=(x, y, pk),
               background=(bx, by, bpk))
    monkeypatch.setattr(fw, "_pred_paths",
                        lambda _p: {"sample": 21.0, "sampledia": 30.6,
                                    "mediumdia": 40.6}, raising=False)
    tr["roles"]["sample"] = {"nt_um": 21.0, "auto": False}
    tr["roles"]["sampledia"] = {"nt_um": 30.6, "auto": False}
    tr["roles"]["mediumdia"] = {"nt_um": 40.6, "auto": False}
    warned = []
    monkeypatch.setattr(fw, "_set_solve_status",
                        lambda text: warned.append(text), raising=False)

    fw._drag = {"kind": "role", "role": "sample", "chan": "Sample",
                "moved": False}
    fw._on_motion(_Ev(xdata=34.0))
    fw._on_release(_Ev(xdata=34.0))

    assert tr["roles"]["sample"]["nt_um"] == pytest.approx(34.0)
    assert any("right of the sample diamond" in t for t in warned), warned


# ---------------------------------------------------------------------------
# what the reader sees: press hint, stagger, guides
# ---------------------------------------------------------------------------
def test_the_press_hint_states_the_drop_and_what_fit_peaks_does(
        a, fw, monkeypatch):
    """The old hint promised a snap that never existed ("release to drop it,
    then Fit peaks to snap it onto the peak")."""
    x, y, pk = _curve([(1.0, 21.0, 0.9)])
    tr = _load(a, fw, monkeypatch, sample=(x, y, pk))
    tr["roles"]["sample"] = {"nt_um": 21.0, "auto": True}
    fw._request_redraw(now=True)
    ax = fw._axes["Sample"]
    px, py = ax.transAxes.transform((0.5, fw._drawn_row("sample")))
    hints = []
    monkeypatch.setattr(fw, "_hint", lambda msg=None: hints.append(msg),
                        raising=False)

    fw._on_press(_Ev(inaxes=ax, xdata=21.0, x=px, y=py))

    assert fw._drag and fw._drag["role"] == "sample"
    assert fw._drag["moved"] is False
    assert hints and "solves" in hints[-1] and "re-detects" in hints[-1]
    assert "snap it onto the peak" not in hints[-1]
    fw._drag = None


def test_a_coincident_sample_pair_staggers_and_stays_separable(
        a, fw, monkeypatch):
    """Cold-start seeding can put both Sample glyphs on one peak.  The draw
    drops the rectangle a row (his _Y_LOW), and the hit test takes the
    nearest drawn ROW before the nearest x, so each one can be grabbed."""
    x, y, pk = _curve([(1.0, 21.0, 0.9)])
    tr = _load(a, fw, monkeypatch, sample=(x, y, pk))
    for role in ("sample", "sampledia"):
        tr["roles"][role] = {"nt_um": 21.0, "auto": True}
    fw._request_redraw(now=True)
    ax = fw._axes["Sample"]
    if fw._mark_size_um(ax) <= 0:
        pytest.skip("the figure has no measurable width in this run")

    lo_row = fw._drawn_row("sample")
    hi_row = fw._drawn_row("sampledia")
    assert lo_row < hi_row, "the rectangle drops below the diamond"
    assert lo_row >= fringe_panel.ROLE_Y_LOW_MIN

    def _grab(row):
        px, py = ax.transAxes.transform((0.5, row))
        return fw._grab_role("Sample", 21.0, _Ev(inaxes=ax, xdata=21.0,
                                                 x=px, y=py))
    assert _grab(hi_row) == "sampledia"
    assert _grab(lo_row) == "sample"


def test_the_draw_marks_auto_and_manual_apart(a, fw, monkeypatch):
    """Two fills from the theme triad, and a dashed guide under the glyph
    you placed -- so High Contrast never leans on colour alone."""
    x, y, pk = _curve([(1.0, 21.0, 0.9), (1.0, 30.6, 0.9)])
    tr = _load(a, fw, monkeypatch, sample=(x, y, pk))
    tr["roles"]["sample"] = {"nt_um": 21.0, "auto": True}
    tr["roles"]["sampledia"] = {"nt_um": 30.6, "auto": False}
    fw._request_redraw(now=True)

    auto_c, man_c = fw._role_colors()
    assert auto_c != man_c
    arts = fw._artists["roles"]
    assert arts["sample"].get_markerfacecolor() == auto_c
    assert arts["sampledia"].get_markerfacecolor() == man_c
    guides = fw._artists["guides"]
    assert guides["sample"][1].get_linestyle() in ("-", "solid")
    assert guides["sampledia"][1].get_linestyle() in ("--", "dashed")
    assert guides["sampledia"][1].get_color() == man_c


def test_the_fitted_gaussian_is_drawn_for_auto_roles_only(
        a, fw, monkeypatch):
    """The overlay is a detection artifact: it belongs to a glyph the
    workbench fitted, and a drag drops it."""
    x, y, pk = _curve([(1.0, 21.0, 0.9)])
    tr = _load(a, fw, monkeypatch, sample=(x, y, pk))
    fw.fitmode_v.set("distinct")
    val, how = fw._refine_peak("Sample", "sample", 21.0)
    assert how == "fit"
    tr["roles"]["sample"] = {"nt_um": val, "auto": True}

    def _dotted_count():
        # the overlay is a 240-point dotted curve; the length test keeps a
        # short dotted artist from any other layer out of the count
        ax = fw._axes["Sample"]
        return sum(1 for ln in ax.get_lines()
                   if ln.get_linestyle() in (":", "dotted")
                   and len(np.ravel(ln.get_xdata())) > 100)
    fw._request_redraw(now=True)
    with_overlay = _dotted_count()
    assert with_overlay >= 1

    tr["roles"]["sample"] = {"nt_um": val, "auto": False}
    tr["gauss"]["sample"] = None
    fw._request_redraw(now=True)
    assert _dotted_count() < with_overlay


# ---------------------------------------------------------------------------
# the status lines
# ---------------------------------------------------------------------------
def test_the_status_line_tells_the_outcomes_apart():
    """refined-to vs already-on-peak vs kept-after-a-failed-fit vs the
    physical-order snap -- one phrase each, and none of them is the old
    catch-all "every glyph kept its position"."""
    out = {"sample": (20.41, "fit"), "sampledia": (30.60, "fit"),
           "mediumdia": (40.60, "peak")}
    before = {"sample": 18.0, "sampledia": 30.60, "mediumdia": 40.60}
    line = fringe_panel.FringeWorkbench._fit_report(out, before)
    assert "Sample refined to 20.41 um" in line
    assert "Sample diamonds already on the peak at 30.60 um" in line
    assert "Medium diamond kept at the nearest peak 40.60 um (fit failed)" \
        in line

    snap = fringe_panel.FringeWorkbench._fit_report(
        {"sample": (25.0, "order")}, {"sample": 40.6})
    assert "onto the sample diamond at 25.00 um" in snap

    assert fringe_panel.FringeWorkbench._fit_report({}, {}) == \
        "every glyph held its position"
