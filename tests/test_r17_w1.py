"""R17-W1: the low-pass gesture, the removed-region shade, exact notch
centres, and the no-fringe channel.

Matthew tested v1.4.10 twice.  His second report was that "the low-pass does
something unexpected past the large diamond-diamond FFT peak".  Three defects
sat behind that sentence and this file pins all three, plus the two numeric
drifts the parity audit found beside them:

  * THE DRAG.  His handler rejects motion that has left the dragged channel's
    own FFT panel and clamps x to [1, 200] intersected with the visible range
    (defringe_dac 14033-14045).  Ours had neither, so a pointer that strayed
    into the measured panel mid-drag wrote THAT panel's wavenumber -- 17867 --
    into the cutoff: the tick still read on and the filter silently stopped
    filtering.  Dragging right, past a large peak, is the gesture that leaves
    the panel.  His release also keeps the zoom; ours snapped back to 0-140;
  * THE SHADE.  His tints the removed region above the cutoff (13788).  It is
    the only cue that says what the low-pass takes out.  Ours drew a dashed
    line and a "N% removed" number that printed 0.0% while the cleaned curve
    was visibly off raw -- a contradiction his window never offers;
  * NO FRINGE, NO MASK.  His gates the whole notch stage on the detection
    (17752).  47% of real channels have no fringe; ours low-passed them all
    the same and drew a red curve 4-9% of full scale off raw at every cutoff;
  * EXACT CENTRES.  His `_active_centers` keys by the rounded 0.01 um value
    but keeps the MEASURED nm as the dict value.  Ours rebuilt nm as
    key * 1000, so the moment a trace was opened in the workbench its cleaning
    stopped matching the main plot, the CSVs and his program;
  * THE THICKNESS READ.  `detect_nt` ran one full-range FFT where the cleaning
    corroborates 2-of-3, so the number reported beside a cleaned spectrum was
    not the n*t that cleaned it.

The pure-module half needs no Tk.  The panel half runs against the suite's ONE
shared App (tests/conftest.py).
"""
import numpy as np
import pytest

import fringe_apply
import fringe_detect
import fringe_panel
from conftest import gui, make_result, shared_app, walk

USES_APP = True

NT_UM = 30.0
NT_NM = NT_UM * 1000.0
GATE = dict(halfwidth_um=3.0, nt_min_nm=8000.0, nt_max_nm=300000.0)


# ---------------------------------------------------------------------------
# synthetic spectra
# ---------------------------------------------------------------------------
def _fringed(nt_um=NT_UM, amp=0.06, n=1400, lo=500.0, hi=900.0):
    """Counts with ONE clean fringe of optical path n*t."""
    wl = np.linspace(lo, hi, n)
    base = 1000.0 * (1.0 + 0.30 * (wl - lo) / (hi - lo))
    return wl, base * (1.0 + amp * np.cos(4.0 * np.pi * nt_um * 1000.0 / wl))


def _flat(n=1400, lo=500.0, hi=900.0, seed=7):
    """Counts with no fringe in them: a lamp envelope and a little noise."""
    wl = np.linspace(lo, hi, n)
    base = 1000.0 * (1.0 + 0.30 * (wl - lo) / (hi - lo))
    rng = np.random.RandomState(seed)
    return wl, base * (1.0 + 0.002 * rng.randn(n))


def _two_peak(n=3000, lo=380.0, hi=1050.0):
    """A long fringe on the red side and a strong SHORT one on the blue.

    The full range alone latches on the short peak; the narrow fit window and
    the wide window both see the long one and agree.  This is r16-B's finding
    F1 reproduced: the demo channel read 8.99 um from the full window while
    the cleaning notched 26.39 um.
    """
    wl = np.linspace(lo, hi, n)
    base = 1000.0 * (1.0 + 0.3 * (wl - lo) / (hi - lo))
    w_short = np.clip((650.0 - wl) / 250.0, 0.0, 1.0)
    w_long = np.clip((wl - 620.0) / 120.0, 0.0, 1.0)
    return wl, base * (1.0
                       + 0.05 * w_long * np.cos(4.0 * np.pi * 26000.0 / wl)
                       + 0.25 * w_short * np.cos(4.0 * np.pi * 9000.0 / wl))


def _rec(label, pval, stem=None, flat=False):
    """An engine-style record whose raw channels carry a fringe, or none."""
    wl, samp = (_flat() if flat else _fringed())
    _wl, bg = (_flat(seed=3) if flat else _fringed(NT_UM + 6.0))
    r = make_result(label, pval, wl=wl, samp=samp, bg=bg,
                    dark=np.full(wl.size, 5.0))
    if stem:
        r["stem"] = stem
    return r


# ===========================================================================
# 1. NO FRINGE, NO MASK  (D1, at the source)
# ===========================================================================
def test_the_core_runs_no_mask_without_a_detection():
    """His gate (17752).  No accepted n*t, no notch and no low-pass."""
    wl, y = _flat()
    fit, I_notch, nt, defaults = fringe_detect.compute_channel_fit(
        wl, y, run_fits=False, notch_centers_nm=[], lowpass=True,
        lp_cutoff_um=8.0)
    assert nt is None and defaults == []
    assert fit["no_fringe"] is True
    assert np.isnan(I_notch).all()
    assert "I_notch_1x" not in (fit["fft_info"] or {})


def test_a_named_centre_needs_a_detection_too():
    """The gate is on the DETECTION, so it governs the picks as well."""
    wl, y = _flat()
    fit, I_notch, nt, _d = fringe_detect.compute_channel_fit(
        wl, y, run_fits=False, notch_centers_nm=[12000.0],
        notch_halfwidths_um=[3.0])
    assert nt is None
    assert np.isnan(I_notch).all()
    assert "I_notch_1x" not in (fit["fft_info"] or {})


def test_the_three_states_still_hold_once_a_fringe_is_there():
    """[] is a decision, and the low-pass is independent of the LIST."""
    wl, y = _fringed()
    empty, _I, nt, _d = fringe_detect.compute_channel_fit(
        wl, y, run_fits=False, notch_centers_nm=[])
    assert nt is not None
    assert np.allclose(empty["fft_info"]["I_notch_1x"], y,
                       rtol=0, atol=1e-6 * np.ptp(y))

    lp_only, _I2, _nt2, _d2 = fringe_detect.compute_channel_fit(
        wl, y, run_fits=False, notch_centers_nm=[], lowpass=True,
        lp_cutoff_um=8.0)
    got = lp_only["fft_info"]["I_notch_1x"]
    assert not np.allclose(got, y, rtol=0, atol=1e-6 * np.ptp(y))
    assert np.ptp(got) < np.ptp(y)


def test_clean_channel_hands_back_the_input_on_a_fringe_free_channel():
    wl, y = _flat()
    out = fringe_apply.clean_channel(wl, y, notch_centers_nm=[], lowpass=True,
                                     lp_cutoff_um=8.0, **GATE)
    assert out["applied"] is False
    assert out["nt_um"] is None
    assert np.array_equal(out["clean"], y)
    assert out["clean"] is not y                  # a copy, not the caller's


# ===========================================================================
# 2. THE THICKNESS READ  (D7)
# ===========================================================================
def test_detect_nt_is_the_cleanings_own_n_t():
    """The read and the cleaning corroborate the same 2 of 3 windows.

    Before R17 this ran ONE full-range FFT, which on this spectrum latches on
    the short blue-side fringe -- 8.9 um against the 26.4 um the mask uses.
    """
    wl, y = _two_peak()
    _fit, _I, nt, _d = fringe_detect.compute_channel_fit(wl, y,
                                                         run_fits=False)
    read, pv = fringe_apply.detect_nt(wl, y)
    assert nt is not None
    assert read == float(nt) * 1e-3               # the same number, bit for bit
    assert pv < 1e-4

    full_only, _info = fringe_detect.fft_initial_guess(wl, y)
    assert full_only is not None
    # the old read, and it is a different peak altogether
    assert abs(float(full_only) * 1e-3 - read) > 1.0


def test_detect_nt_stays_notch_set_independent_and_gated():
    """It takes no centres, and a channel with no confident fringe reports
    nothing rather than a guess."""
    import inspect
    args = inspect.signature(fringe_apply.detect_nt).parameters
    assert "notch_centers_nm" not in args
    assert fringe_apply.detect_nt(*_flat(), **GATE)[0] is None


# ===========================================================================
# 3. EXACT NOTCH CENTRES, the pure half  (his `seen` dict)
# ===========================================================================
@gui
def test_the_recipe_emits_the_measured_centre_not_the_key(_fw_module):
    """`_recipe_channel` reads the exact value his `seen` map keeps."""
    fw = _fw_module
    src = {"default_centers": [], "user_centers": [12.0], "removed": [],
           "unticked": [], "user_fundamental": None, "widths": {}}
    entry = fw._recipe_channel(dict(src), None, "Sample")
    assert entry["notch_centers_nm"] == [12000.0]       # old schema: key*1000

    src["exact"] = {"12.00": 12002.21678738575}
    entry = fw._recipe_channel(src, None, "Sample")
    assert entry["notch_centers_nm"] == [12002.21678738575]


def test_the_exact_centre_is_what_reproduces_his_mask():
    """Given his measured centre, our core is bit-identical to the automatic
    path; given the rounded key it is not."""
    wl, y = _fringed()
    _fit, _I, nt, _d = fringe_detect.compute_channel_fit(wl, y,
                                                         run_fits=False)
    key = round(float(nt) / 1000.0, 2)
    assert key * 1000.0 != float(nt)              # the drift the fix removes

    auto = fringe_apply.clean_channel(wl, y, **GATE)
    exact = fringe_apply.clean_channel(wl, y, notch_centers_nm=[float(nt)],
                                       notch_halfwidths_um=[3.0], **GATE)
    quant = fringe_apply.clean_channel(wl, y,
                                       notch_centers_nm=[key * 1000.0],
                                       notch_halfwidths_um=[3.0], **GATE)
    assert np.array_equal(exact["clean"], auto["clean"])
    assert not np.array_equal(quant["clean"], auto["clean"])


# ===========================================================================
# 4. the settings key the resolution floor travels on
# ===========================================================================
def test_the_band_floor_is_a_settings_key_the_no_ui_config_reads():
    assert fringe_panel.SETTINGS_DEFAULTS["fr_band_floor"] is True
    assert fringe_panel.global_cfg({}, None, None).band_res_floor is True
    off = fringe_panel.global_cfg({"fr_band_floor": False}, None, None)
    assert off.band_res_floor is False


def test_the_no_ui_config_states_the_channels_own_cutoff():
    """Honesty: the cutoff that cleans travels as a keyword, but a config
    describing the Background used to quote the Sample's number."""
    s = {"fr_lp_bg_um": 40.0, "fr_lp_s_um": 12.0}
    bg = fringe_panel.global_cfg(s, None, None, chan="Background")
    sa = fringe_panel.global_cfg(s, None, None, chan="Sample")
    assert bg.lp_cutoff_um == pytest.approx(40.0)
    assert sa.lp_cutoff_um == pytest.approx(12.0)
    assert fringe_panel.global_cfg(s, None, None).lp_cutoff_um == \
        pytest.approx(12.0)                        # unnamed keeps the Sample


# ===========================================================================
# 5. the panel  (every test below carries @gui)
# ===========================================================================
@pytest.fixture(scope="module")
def a():
    return shared_app()


@pytest.fixture
def fw(a):
    """The workbench with a clean slate, put back afterwards."""
    w = a._fringe
    w.build()
    keep = (dict(w._chan), dict(w._trace), dict(w._disk), dict(w._inputs),
            w._label, w._local, list(a.results),
            {c: (bool(w.lp_on_v[c].get()), w.lp_v[c].get())
             for c in fringe_panel.CHANNELS},
            bool(w.bandfloor_v.get()),
            {k: v.get() for k, v in (("ns", w.ns_v), ("t", w.t_v),
                                     ("d1", w.d1_v), ("d2", w.d2_v))})
    for d in (w._chan, w._trace, w._disk, w._inputs, w._cache):
        d.clear()
    w._dk_cache = {}
    w._dk_sig = None
    w._seed_said.clear()
    a.notch_cache.clear()
    yield w
    _quiet(w)
    for d, src in ((w._chan, keep[0]), (w._trace, keep[1]),
                   (w._disk, keep[2]), (w._inputs, keep[3])):
        d.clear()
        d.update(src)
    w._label = keep[4]
    w._local = keep[5]
    a.results = keep[6]
    w._suspend = True
    try:
        for c, (on, cut) in keep[7].items():
            w.lp_on_v[c].set(on)
            w.lp_v[c].set(cut)
        w.bandfloor_v.set(keep[8])
        for k, var in (("ns", w.ns_v), ("t", w.t_v), ("d1", w.d1_v),
                       ("d2", w.d2_v)):
            var.set(keep[9][k])
    finally:
        w._suspend = False
    w._cache.clear()
    w._dk_cache = {}
    w._dk_sig = None
    a.notch_cache.clear()


@pytest.fixture(scope="module")
def _fw_module(a):
    """The workbench, built, for the pure-ish reads above.  No state is
    touched, so it needs no per-test slate."""
    a._fringe.build()
    return a._fringe


def _quiet(fw):
    """Drop any armed drag and the debounced redraw a test left behind."""
    fw._drag = None
    if fw._after is not None:
        try:
            fw.app.root.after_cancel(fw._after)
        except Exception:
            pass
        fw._after = None


def _load(a, fw, recs, label=None):
    """Make `recs` the loaded series, without touching the disk."""
    a.results = list(recs)
    fw._local = None
    fw._dk_cache = {}
    fw._dk_sig = None
    fw._cache.clear()
    fw._label = label if label is not None else recs[0]["label"]


def _lp_off(fw):
    fw._suspend = True
    try:
        for c in fringe_panel.CHANNELS:
            fw.lp_on_v[c].set(False)
    finally:
        fw._suspend = False


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


def _arm_lp(fw, chan, x0=None):
    """Arm a low-pass drag the way `_on_press` does."""
    ax = fw._axes[chan]
    fw._drag = {"kind": "lp", "chan": chan, "moved": False,
                "x0": (fringe_panel._f(fw.lp_v[chan], 15.0) if x0 is None
                       else float(x0)),
                "ax": ax}
    return ax


# ---- the drag: the panel guard and the clamp ------------------------------
@gui
def test_motion_outside_the_dragged_panel_is_not_a_cutoff(a, fw):
    """Matthew's complaint (2), reproduced and fixed.

    Measured before the guard: a pointer crossing into the measured panel
    mid-drag wrote 17867 -- that panel's wavenumber -- into the cutoff, the
    box still read on, and the removed fraction fell to 5e-05.
    """
    _load(a, fw, [_rec("20 GPa", 20.0)])
    fw.lp_on_v["Sample"].set(True)
    fw.lp_v["Sample"].set("60")
    fw._request_redraw(now=True)
    _arm_lp(fw, "Sample")

    fw._on_motion(_Ev(inaxes=fw._maxes["Sample"], xdata=17867.05))
    assert fringe_panel._f(fw.lp_v["Sample"], 0.0) == pytest.approx(60.0)
    fw._on_motion(_Ev(inaxes=fw._axes["Background"], xdata=120.0))
    assert fringe_panel._f(fw.lp_v["Sample"], 0.0) == pytest.approx(60.0)
    assert fw._drag["moved"] is False              # nothing was dragged
    _quiet(fw)


@gui
def test_the_drag_clamps_to_his_range_and_to_the_visible_span(a, fw):
    """`x = min(max(xdata, 1.0, xlo), 200.0, xhi)`, his 14044."""
    _load(a, fw, [_rec("20 GPa", 20.0)])
    fw.lp_on_v["Sample"].set(True)
    fw.lp_v["Sample"].set("15")
    fw._request_redraw(now=True)
    ax = _arm_lp(fw, "Sample")
    ax.set_xlim(0.0, 600.0)                        # a zoomed-out panel

    fw._on_motion(_Ev(inaxes=ax, xdata=0.3))
    assert fringe_panel._f(fw.lp_v["Sample"], 0.0) == pytest.approx(1.0)
    fw._on_motion(_Ev(inaxes=ax, xdata=500.0))
    assert fringe_panel._f(fw.lp_v["Sample"], 0.0) == pytest.approx(200.0)

    ax.set_xlim(20.0, 90.0)                        # zoomed IN: the view wins
    fw._on_motion(_Ev(inaxes=ax, xdata=140.0))
    assert fringe_panel._f(fw.lp_v["Sample"], 0.0) == pytest.approx(90.0)
    fw._on_motion(_Ev(inaxes=ax, xdata=5.0))
    assert fringe_panel._f(fw.lp_v["Sample"], 0.0) == pytest.approx(20.0)
    _quiet(fw)


@gui
def test_the_release_keeps_the_view(a, fw):
    """His `_redraw_all(preserve_view=True)`.  Zooming in to place the line
    past a large peak is the very gesture that used to lose its own frame:
    5-90 um snapped back to 0-140 and y re-autoscaled."""
    _load(a, fw, [_rec("20 GPa", 20.0)])
    fw.lp_on_v["Sample"].set(True)
    fw.lp_v["Sample"].set("15")
    fw._request_redraw(now=True)
    axes = (fw.ax_bg, fw.ax_s, fw.ax_mb, fw.ax_ms)
    for i, ax in enumerate(axes):
        ax.set_xlim(5.0 + i, 90.0 + i)
        ax.set_ylim(-1.0 - i, 2.0 + i)
    want = [(ax.get_xlim(), ax.get_ylim()) for ax in axes]

    ax = _arm_lp(fw, "Sample")
    fw._on_motion(_Ev(inaxes=ax, xdata=60.0))
    fw._on_release(_Ev())

    assert fringe_panel._f(fw.lp_v["Sample"], 0.0) == pytest.approx(60.0)
    assert [(a_.get_xlim(), a_.get_ylim()) for a_ in axes] == want
    # a later FocusOut must not fire again on the committed value
    assert fw._lp_last["Sample"] == fw.lp_v["Sample"].get()
    _quiet(fw)


@gui
def test_a_press_with_no_travel_falls_through_to_the_notch(a, fw):
    """His fall-through (14090-14097): a plain click on the line is a notch
    click, not a cutoff change -- and it does not invalidate every trace."""
    r = _rec("20 GPa", 20.0)
    _load(a, fw, [r])
    fw.lp_on_v["Sample"].set(True)
    fw._request_redraw(now=True)
    c = fw._compute("Sample")
    assert len(c["peaks"])
    peak = float(c["nt_um"][c["peaks"][0]])
    key = round(peak, 2)
    ch = fw._ch("Sample")
    listed = key in ch["default_centers"] or key in ch["user_centers"]

    _arm_lp(fw, "Sample", x0=peak)
    fw._on_release(_Ev())

    if listed:                                     # the click takes it away
        assert key in ch["removed"]
    else:                                          # ...or adds it
        assert key in ch["user_centers"]
    assert fw._exact_nm("Sample", key) == pytest.approx(peak * 1000.0)
    _quiet(fw)


# ---- the control ranges ---------------------------------------------------
@gui
def test_the_cutoff_spinbox_carries_his_range(a, fw):
    """1 to 200, the range the drag clamps to (his 15724)."""
    assert (fringe_panel.LP_MIN_UM, fringe_panel.LP_MAX_UM) == (1.0, 200.0)
    for chan in fringe_panel.CHANNELS:
        got = _spinboxes_for(fw.sidebar_parent, fw.lp_v[chan])
        assert got, "no cutoff spinbox for %s" % chan
        for sp in got:
            assert float(sp.cget("from")) == pytest.approx(1.0)
            assert float(sp.cget("to")) == pytest.approx(200.0)


@gui
def test_a_notch_rows_width_spinbox_carries_his_range(a, fw):
    """0.5 to 20 um of +-reach, his per-centre range."""
    from conftest import offscreen
    assert (fringe_panel.NOTCH_HW_MIN_UM,
            fringe_panel.NOTCH_HW_MAX_UM) == (0.5, 20.0)
    r = _rec("20 GPa", 20.0)
    _load(a, fw, [r])
    fw._compute("Sample")
    fw._ch("Sample")["default_centers"] = [NT_UM]
    with offscreen(a):
        win = fw._open_notch_list()
    try:
        fw._notch_sig = None
        fw._refresh_notch_rows()
        rows = _spinbox_ranges(fw._notch_rows)
        assert (0.5, 20.0) in rows
        assert not any(hi > 20.0 for _lo, hi in rows)
        assert "(no fringe)" not in _texts_of(fw._notch_rows)
    finally:
        win.destroy()
        fw._notch_win = None
        fw._notch_rows = None


def _spinboxes_for(root, var):
    name = str(var)
    out = []
    for w in walk(root):
        try:
            if w.winfo_class() != "TSpinbox":
                continue
            if str(w.cget("textvariable")) == name:
                out.append(w)
        except Exception:
            continue
    return out


def _spinbox_ranges(root):
    out = []
    for w in walk(root):
        try:
            if w.winfo_class() == "TSpinbox":
                out.append((float(w.cget("from")), float(w.cget("to"))))
        except Exception:
            continue
    return out


def _texts_of(root):
    out = []
    for w in walk(root):
        try:
            t = w.cget("text")
        except Exception:
            continue
        if isinstance(t, str) and t:
            out.append(t)
    return out


# ---- the visuals ----------------------------------------------------------
@gui
def test_the_removed_region_is_shaded_from_the_cutoff_to_the_edge(a, fw):
    """His teal axvspan (13788), the one cue that says what is taken out."""
    _load(a, fw, [_rec("20 GPa", 20.0)])
    fw.lp_on_v["Sample"].set(True)
    fw.lp_v["Sample"].set("45")
    fw._request_redraw(now=True)

    sh = fw._artists["lpshade"]["Sample"]
    assert sh is not None
    xhi = float(fw._axes["Sample"].get_xlim()[1])
    assert float(sh.get_x()) == pytest.approx(45.0)
    assert float(sh.get_x()) + float(sh.get_width()) == pytest.approx(xhi)
    assert float(sh.get_alpha()) == pytest.approx(0.06)
    # ...and it is the low-pass line's own colour, taken from the theme
    from matplotlib.colors import to_rgb
    line_rgb = to_rgb(fw._artists["lp"]["Sample"].get_color())
    assert tuple(round(v, 6) for v in sh.get_facecolor()[:3]) == \
        tuple(round(v, 6) for v in line_rgb)
    _quiet(fw)


@gui
def test_the_shade_follows_a_live_drag(a, fw):
    _load(a, fw, [_rec("20 GPa", 20.0)])
    fw.lp_on_v["Sample"].set(True)
    fw.lp_v["Sample"].set("20")
    fw._request_redraw(now=True)
    ax = _arm_lp(fw, "Sample")
    ax.set_xlim(0.0, 140.0)

    fw._on_motion(_Ev(inaxes=ax, xdata=80.0))

    sh = fw._artists["lpshade"]["Sample"]
    assert float(sh.get_x()) == pytest.approx(80.0)
    assert float(sh.get_x()) + float(sh.get_width()) == pytest.approx(140.0)
    _quiet(fw)


@gui
def test_the_percent_removed_number_is_gone(a, fw):
    """D5.  It was a variance ratio with no counterpart in his window, and it
    printed 0.0% while the cleaned curve was 2.3% of range off raw."""
    _load(a, fw, [_rec("20 GPa", 20.0)])
    fw.lp_on_v["Sample"].set(True)
    fw._request_redraw(now=True)
    said = [t.get_text() for ax in fw.fig.get_axes() for t in ax.texts]
    assert not any("removed" in s and "%" in s for s in said)
    # the twin curve his window has is still there
    assert fw._artists["removed"]["Sample"] is not None


@gui
def test_the_fft_y_label_names_the_physical_scale(a, fw):
    _load(a, fw, [_rec("20 GPa", 20.0)])
    fw._request_redraw(now=True)
    lab = fw._axes["Sample"].get_ylabel()
    assert "V_m" in lab and "2R^{m}" in lab


@gui
def test_the_x_upper_reads_the_pinned_fundamental_and_caps_at_the_band(
        a, fw):
    """His _forward_row_xupper (8836/8848): the PINNED fundamental sets the
    reach, and the Detection card's n*t max is the ceiling."""
    r = _rec("20 GPa", 20.0)
    _load(a, fw, [r])
    # a small, known stack, so the model stems cannot decide the answer on
    # their own (the fixture puts the boxes back)
    fw._suspend = True
    try:
        fw.ns_v.set("1.5")
        fw.t_v.set("5")
        fw.d1_v.set("0")
        fw.d2_v.set("0")
    finally:
        fw._suspend = False
    fw._compute("Sample")
    p = fw._stack_params(fw._record())

    fw._ch("Sample")["user_fundamental"] = 120.0
    wide = fw._x_upper(p)
    fw._ch("Sample")["user_fundamental"] = 12.0
    narrow = fw._x_upper(p)
    assert wide > narrow

    keep = fw.ntmax_v.get()
    try:
        fw._ch("Sample")["user_fundamental"] = 5000.0
        fw.ntmax_v.set("300")
        fw._cache.clear()
        assert fw._x_upper(p) <= 300.0
    finally:
        fw.ntmax_v.set(keep)
        fw._ch("Sample")["user_fundamental"] = None
        fw._cache.clear()
    _quiet(fw)


# ---- exact centres, through the panel ------------------------------------
@gui
def test_the_workbench_notches_where_the_main_plot_notches(a, fw):
    """The whole point of the `seen` map.  A trace opened here must clean
    bit-identically to the automatic path the main plot takes."""
    r = _rec("20 GPa", 20.0, stem="s_20p0")
    _load(a, fw, [r])
    _lp_off(fw)
    fw._compute("Sample")                 # seeds default_centers + exact
    c = fw._compute("Sample")
    nt = float(c["nt"])
    key = round(nt / 1000.0, 2)

    assert fw._ch("Sample")["exact"][key] == nt
    assert fw._exact_nm("Sample", key) == nt
    cents, hws = fw._active_centers_widths("Sample")
    assert cents == [nt]

    rp = fw.defringe_recipe(r)
    entry = dict(rp["channels"]["samp_c"])
    assert entry["notch_centers_nm"] == [nt]

    base = dict(rp["gates"])
    base["cfg"] = rp["cfg"]
    live = fringe_apply.clean_channel(r["wl"], r["samp_c"],
                                      **dict(base, **entry))
    auto_entry = dict(entry)
    auto_entry["notch_centers_nm"] = None
    auto_entry.pop("notch_halfwidths_um", None)
    auto = fringe_apply.clean_channel(r["wl"], r["samp_c"],
                                      **dict(base, **auto_entry))
    assert live["applied"] and auto["applied"]
    assert np.array_equal(live["clean"], auto["clean"])

    # and the rounded key really would have been a different mask
    quant = dict(entry)
    quant["notch_centers_nm"] = [key * 1000.0]
    assert key * 1000.0 != nt
    other = fringe_apply.clean_channel(r["wl"], r["samp_c"],
                                       **dict(base, **quant))
    assert not np.array_equal(other["clean"], auto["clean"])
    _quiet(fw)


@gui
def test_a_clicked_peak_is_filed_at_its_measured_n_t(a, fw):
    r = _rec("20 GPa", 20.0)
    _load(a, fw, [r])
    fw._request_redraw(now=True)
    c = fw._compute("Sample")
    peak = float(c["nt_um"][c["peaks"][0]])
    key = round(peak, 2)
    fw._ch("Sample")["removed"].add(key)          # make the click an ADD

    fw._toggle_notch_at("Sample", peak, ax=fw._axes["Sample"])

    assert key in fw._ch("Sample")["user_centers"] or \
        key in fw._ch("Sample")["default_centers"]
    # the measured n*t, to the bit -- not the key it is filed under
    assert fw._exact_nm("Sample", key) == peak * 1000.0
    _quiet(fw)


@gui
def test_the_measured_centre_survives_a_session_round_trip(a, fw):
    r = _rec("20 GPa", 20.0, stem="s_20p0")
    _load(a, fw, [r])
    fw._compute("Sample")
    c = fw._compute("Sample")
    nt = float(c["nt"])
    key = round(nt / 1000.0, 2)

    fw._commit()
    dk = fw._dkey()
    stored = fw._disk[dk]["chan"]["Sample"]
    assert stored["exact"]["%.2f" % key] == nt

    fw._chan.clear()
    fw._apply_trace_state(dk, fw._disk[dk])
    assert fw._exact_nm("Sample", key) == nt
    _quiet(fw)


@gui
def test_a_session_written_before_r17_falls_back_to_the_key(a, fw):
    """Backward compatible: no `exact` block means key * 1000, which is
    exactly what such a payload always meant."""
    r = _rec("20 GPa", 20.0, stem="s_20p0")
    _load(a, fw, [r])
    dk = fw._dkey()
    fw._apply_trace_state(dk, {"chan": {"Sample": {
        "user_centers": [12.0], "removed": [], "unticked": [],
        "user_fundamental": None, "default_centers": [], "widths": {}}}})
    assert fw._exact_nm("Sample", 12.0) == 12000.0
    _quiet(fw)


# ---- the no-fringe channel, on screen -------------------------------------
@gui
def test_a_channel_with_no_fringe_draws_his_baseline_and_no_red_curve(a, fw):
    """His Row-0 fallback (7444-7470).  Nothing was cleaned, so nothing
    cleaned is drawn; the panel shows what the channel is made of."""
    r = _rec("20 GPa", 20.0, flat=True)
    _load(a, fw, [r])
    fw.lp_on_v["Sample"].set(True)                 # on, and still no mask
    fw._request_redraw(now=True)

    c = fw._compute("Sample")
    assert c["nt"] is None
    assert "I_notch_1x" not in (c["fft_info"] or {})

    ms = fw._maxes["Sample"]
    labels = [ln.get_label() for ln in ms.lines]
    assert "raw" in labels
    assert "dark" in labels
    assert any("(raw, dark)" in str(t) for t in labels)
    assert "FFT filtered" not in labels
    assert any("noise floor" == str(col.get_label())
               for col in ms.collections)
    assert "no fringe detected (p=" in ms.get_title()
    head = fw._schem_labels["Sample"]._fr_head.get_text()
    assert head.startswith("Sample  no fringe detected (p=")
    _quiet(fw)


@gui
def test_a_fringed_channel_keeps_the_dark_overlays_and_the_red_curve(a, fw):
    _load(a, fw, [_rec("20 GPa", 20.0)])
    fw.lp_on_v["Sample"].set(True)
    fw._request_redraw(now=True)
    ms = fw._maxes["Sample"]
    labels = [str(ln.get_label()) for ln in ms.lines]
    assert "raw" in labels and "dark" in labels
    assert any("(raw, dark)" in s for s in labels)
    assert "FFT filtered" in labels
    assert "no fringe detected" not in ms.get_title()
    _quiet(fw)


@gui
def test_the_fit_window_is_drawn_on_the_measured_panels(a, fw):
    """His pale band plus the dashed window markers, on the wavenumber axis
    the panel actually plots."""
    _load(a, fw, [_rec("20 GPa", 20.0)])
    fw._request_redraw(now=True)
    ms = fw._maxes["Sample"]
    c = fw._compute("Sample")
    lo = float(c["cfg"].fit_wl_min_nm)
    hi = float(c["cfg"].fit_wl_max_nm)
    want = sorted((1e7 / hi, 1e7 / lo))

    verticals = []
    for ln in ms.lines:
        xd = np.ravel(np.asarray(ln.get_xdata(), float))
        if xd.size == 2 and xd[0] == xd[1]:
            verticals.append(float(xd[0]))
    for x in want:
        assert any(abs(v - x) < 1e-6 for v in verticals), x
    assert ms.patches, "no fit-window band"
    _quiet(fw)


# ---- the df gate is gone --------------------------------------------------
@gui
def test_the_workbench_curve_no_longer_waits_for_the_df_switch(a, fw):
    """D2.  df ships off, and his window always draws the filtered curve."""
    _load(a, fw, [_rec("20 GPa", 20.0)])
    fw.lp_on_v["Sample"].set(True)
    keep = a.show_notch.get()
    try:
        a.show_notch.set(False)
        assert fw._show_clean("Sample") is True
        fw._request_redraw(now=True)
        labels = [str(ln.get_label()) for ln in fw._maxes["Sample"].lines]
        assert "FFT filtered" in labels
        said = [t.get_text() for t in fw._maxes["Sample"].texts]
        assert not any("Defringe off" in s for s in said)
    finally:
        a.show_notch.set(keep)
    _quiet(fw)


@gui
def test_the_band_floor_tick_reaches_the_settings_file(a, fw):
    keep = a.settings.get("fr_band_floor")
    try:
        fw.bandfloor_v.set(False)
        fw._persist()
        assert a.settings["fr_band_floor"] is False
        assert fringe_panel.global_cfg(a.settings, None,
                                       None).band_res_floor is False
        fw.bandfloor_v.set(True)
        fw._persist()
        assert fringe_panel.global_cfg(a.settings, None,
                                       None).band_res_floor is True
    finally:
        if keep is None:
            a.settings.pop("fr_band_floor", None)
        else:
            a.settings["fr_band_floor"] = keep
