"""R15-D: the selectable low-pass edge, and the GUI parity extras.

Matthew's fourth request was a SELECTABLE sigmoid with an adjustable
curvature for the low-pass edge.  Both programs had the edge hard-coded as
tanh at a 2.0 um roll-off, spelled twice in his file (the applied mask at
:6547 and the GUI's preview at :13591) and therefore able to drift.

This file pins:

  * THE EDGE -- one function, `fringe_notch.lowpass_keep`, is the only
    definition of it; the applied mask and the preview curve both call it,
    so what the panel draws is what the spectrum gets.  tanh at 2.0 um
    reproduces the vendored core BIT FOR BIT, which is what makes the new
    control safe to ship on by default;
  * THE PLUMBING -- the shape and the width ride on FringeConfig, through
    the per-point inputs, the session payload and the per-trace defringe
    recipe, per channel;
  * THE Y-AXIS -- the FFT panels' shared range, each bound on its own;
  * THE FUNDAMENTAL -- three states (auto / pinned / none), round-tripping
    through the snapshot and the continuity file in his spelling;
  * THE NAMES -- free text reaching the row labels, the schematic headers
    and the series materials seed.

The pure-mask half needs no Tk and runs anywhere; the panel half runs
against the suite's ONE shared App (tests/conftest.py).
"""
import json

import numpy as np
import pytest

import fringe_config
import fringe_notch
import fringe_panel
from conftest import gui, make_result, shared_app

USES_APP = True


# ---------------------------------------------------------------------------
# 1. the edge itself -- pure numpy, no Tk
# ---------------------------------------------------------------------------
def _freqs(n=601, hi=80000.0):
    return np.linspace(0.0, hi, n)


def test_tanh_is_the_source_expression_bit_for_bit():
    """The shipped shape must be the source's own arithmetic, not a rewrite.

    His mask is `0.5 * (1 - tanh((f - f_cut) / max(roll, 1e-9)))` at :6547.
    Anything that merely agrees to 1e-15 would move every existing number.
    """
    f = _freqs()
    cut, roll = 2000.0 * 15.0, 2000.0 * 2.0
    want = 0.5 * (1.0 - np.tanh((f - cut) / max(roll, 1e-9)))
    got = fringe_notch.lowpass_keep(f, cut, roll, "tanh")
    assert np.array_equal(want, got)


def test_default_shape_and_width_are_the_vendored_ones():
    cfg = fringe_config.DEFAULT_CONFIG
    assert cfg.lp_edge_shape == "tanh"
    assert cfg.lp_rolloff_um == 2.0
    f = _freqs()
    # shape=None and rolloff=None both read the config. The width is in the
    # CALLER's unit (the one-unit contract in the docstring), so the same
    # check on the frequency axis reads cfg.lp_rolloff_um as a frequency;
    # defringe_fft_notch is what converts um -> freq (fringe_notch.py:254).
    assert np.array_equal(fringe_notch.lowpass_keep(f, 30000.0),
                          fringe_notch.lowpass_keep(f, 30000.0,
                                                    cfg.lp_rolloff_um,
                                                    cfg.lp_edge_shape))
    x_um = f / 2000.0
    assert np.array_equal(fringe_notch.lowpass_keep(x_um, 15.0),
                          fringe_notch.lowpass_keep(x_um, 15.0, 2.0, "tanh"))


def test_erf_edge_matches_its_own_definition():
    f = _freqs()
    cut, roll = 30000.0, 4000.0
    got = fringe_notch.lowpass_keep(f, cut, roll, "erf")
    import math
    want = np.array([0.5 * (1.0 - math.erf((v - cut) / roll)) for v in f])
    assert np.allclose(got, want, rtol=0, atol=1e-12)


def test_hard_edge_is_a_step_at_the_cutoff():
    x = np.array([9.0, 10.0, 10.0001, 40.0])
    keep = fringe_notch.lowpass_keep(x, 10.0, 2.0, "hard")
    assert list(keep) == [1.0, 1.0, 0.0, 0.0]


def test_the_three_shapes_all_pass_the_cutoff_at_a_half():
    """Every edge keeps half the signal AT the cutoff except the hard one,
    which is the point of calling it hard."""
    cut = 30000.0
    at = np.array([cut])
    assert fringe_notch.lowpass_keep(at, cut, 4000.0, "tanh")[0] == 0.5
    assert abs(fringe_notch.lowpass_keep(at, cut, 4000.0, "erf")[0]
               - 0.5) < 1e-12
    assert fringe_notch.lowpass_keep(at, cut, 4000.0, "hard")[0] == 1.0


def test_width_controls_the_roll_off():
    """A wider roll-off keeps more just past the cutoff, for both sigmoids."""
    x = np.array([32000.0])
    for shape in ("tanh", "erf"):
        narrow = fringe_notch.lowpass_keep(x, 30000.0, 1000.0, shape)[0]
        wide = fringe_notch.lowpass_keep(x, 30000.0, 8000.0, shape)[0]
        assert wide > narrow


def test_erf_falls_faster_than_tanh_at_one_width_out():
    """The documented pair: one width past the cutoff, tanh keeps ~12% and
    the error function ~8%."""
    x = np.array([34000.0])                 # cutoff 30000 + one width 4000
    t = fringe_notch.lowpass_keep(x, 30000.0, 4000.0, "tanh")[0]
    e = fringe_notch.lowpass_keep(x, 30000.0, 4000.0, "erf")[0]
    assert 0.11 < t < 0.13
    assert 0.07 < e < 0.09
    assert e < t


def test_unknown_shape_is_refused():
    with pytest.raises(ValueError):
        fringe_notch.lowpass_keep(_freqs(), 30000.0, 4000.0, "logistic")
    with pytest.raises(ValueError):
        fringe_config.FringeConfig(lp_edge_shape="logistic")


def test_zero_rolloff_does_not_divide_by_zero():
    keep = fringe_notch.lowpass_keep(_freqs(), 30000.0, 0.0, "tanh")
    assert np.all(np.isfinite(keep))


# ---------------------------------------------------------------------------
# 2. preview == apply: one mask, two readings of it
# ---------------------------------------------------------------------------
def _synthetic(nt_nm=22000.0, n=2048):
    wn = np.linspace(1.0 / 900.0, 1.0 / 500.0, n)
    rng = np.random.default_rng(11)
    sig = (1.0 + 0.2 * np.cos(4.0 * np.pi * nt_nm * wn)
           + 0.02 * rng.standard_normal(n))
    wl = np.linspace(500.0, 900.0, 1500)
    raw = 1.0 + 0.2 * np.cos(4.0 * np.pi * nt_nm / wl)
    return wn, sig, wl, raw


def _applied_mask(centers_nm, widths_um, cut_um, roll_um, shape):
    """The mask `defringe_fft_notch` multiplies into the rfft, rebuilt from
    its own documented pieces and read on the n*t um axis (freqs / 2000).

    The frequency grid is the mirror-padded one the function uses, so the
    comparison is against the mask as APPLIED, not a convenient stand-in.
    """
    wn, sig, _wl, _raw = _synthetic()
    dw = float(np.median(np.abs(np.diff(wn))))
    padded, _pad, _n, n_pad = fringe_notch._mirror_pad(sig)
    freqs = np.fft.rfftfreq(n_pad, d=dw)
    assert padded.size == n_pad
    notch = np.ones_like(freqs)
    for c, hw in zip(centers_nm, widths_um):
        fc = 2.0 * float(c)
        notch = notch * (1.0 - np.exp(-0.5 * ((freqs - fc)
                                              / (2000.0 * hw)) ** 2))
    notch = notch * fringe_notch.lowpass_keep(freqs, 2000.0 * cut_um,
                                              2000.0 * roll_um, shape)
    return freqs / 2000.0, 1.0 - notch


@pytest.mark.parametrize("shape", ["tanh", "erf", "hard"])
def test_preview_curve_equals_the_applied_mask(shape):
    """The whole point of the shared helper: the dotted curve the panel
    draws is the mask the spectrum is cleaned with, sampled on the same
    axis -- for every shape, not just the shipped one."""
    centers_nm = [22000.0, 44000.0]
    widths = [3.0, 2.0]
    x_um, removed_applied = _applied_mask(centers_nm, widths, 15.0, 2.0,
                                          shape)
    removed_preview = fringe_notch.removed_profile_um(
        x_um, [c / 1000.0 for c in centers_nm], widths,
        lowpass=True, lp_cutoff_um=15.0, lp_rolloff_um=2.0,
        lp_edge_shape=shape)
    assert np.allclose(removed_preview, removed_applied, rtol=0, atol=1e-12)


def test_preview_notch_sigma_is_the_half_width_in_micron():
    """In um the notch's sigma IS its +-reach, which is what makes the two
    spaces agree without a conversion factor."""
    x = np.array([15.0, 18.0])              # centre, and one half-width out
    removed = fringe_notch.removed_profile_um(x, [15.0], [3.0])
    assert removed[0] == pytest.approx(1.0)
    assert removed[1] == pytest.approx(1.0 - (1.0 - np.exp(-0.5)))


def test_preview_refuses_a_zero_half_width():
    with pytest.raises(ValueError):
        fringe_notch.removed_profile_um(np.array([1.0]), [15.0], [0.0])


def test_untouched_defaults_leave_the_cleaned_spectrum_alone():
    """Bit parity, end to end: the shipped shape and width through the real
    entry point must equal the expression the vendored core carried."""
    wn, sig, wl, raw = _synthetic()
    kw = dict(nt_fft_nm=22000.0, notch_centers_nm=[22000.0, 44000.0],
              notch_halfwidths_um=[3.0, 2.0], lowpass=True,
              lp_cutoff_um=15.0)
    a = fringe_notch.defringe_fft_notch(wn, sig, wl, raw, **kw)
    b = fringe_notch.defringe_fft_notch(wn, sig, wl, raw,
                                        lp_edge_shape="tanh",
                                        lp_rolloff_um=2.0, **kw)
    assert np.array_equal(a[0], b[0])
    assert np.array_equal(a[2], b[2])
    # ...and a different edge is a different answer, or the control is a lie
    c = fringe_notch.defringe_fft_notch(wn, sig, wl, raw,
                                        lp_edge_shape="erf", **kw)
    assert not np.array_equal(a[0], c[0])


def test_config_carries_the_edge_into_the_mask():
    """A caller that only hands over a cfg still gets its edge: this is the
    route the workbench and Wave B's defringe recipe both use."""
    wn, sig, wl, raw = _synthetic()
    kw = dict(nt_fft_nm=22000.0, notch_centers_nm=[22000.0],
              notch_halfwidths_um=[3.0], lowpass=True, lp_cutoff_um=15.0)
    cfg = fringe_config.DEFAULT_CONFIG.evolve(lp_edge_shape="erf",
                                              lp_rolloff_um=5.0)
    with_cfg = fringe_notch.defringe_fft_notch(wn, sig, wl, raw, cfg=cfg,
                                               **kw)
    explicit = fringe_notch.defringe_fft_notch(wn, sig, wl, raw,
                                               lp_edge_shape="erf",
                                               lp_rolloff_um=5.0, **kw)
    assert np.array_equal(with_cfg[0], explicit[0])


def test_clean_channel_takes_the_edge():
    """The per-trace recipe's route into the main plot's cleaning."""
    import fringe_apply
    wn, sig, wl, raw = _synthetic()
    y = 1.0 + 0.2 * np.cos(4.0 * np.pi * 22000.0 / wl)
    kw = dict(notch_centers_nm=[22000.0], notch_halfwidths_um=[3.0],
              lowpass=True, lp_cutoff_um=15.0)
    soft = fringe_apply.clean_channel(wl, y, **kw)
    hard = fringe_apply.clean_channel(wl, y, lp_edge_shape="hard", **kw)
    assert soft["applied"] and hard["applied"]
    assert not np.array_equal(soft["clean"], hard["clean"])


# ===========================================================================
# the panel half.  Marked test by test rather than module-wide: the mask
# maths above is pure numpy and must run where there is no display.
# ===========================================================================
@pytest.fixture(scope="module")
def a():
    return shared_app()


@pytest.fixture
def fw(a):
    """The workbench with a clean slate, put back afterwards."""
    w = a._fringe
    w.build()
    keep = {
        "chan": dict(w._chan), "trace": dict(w._trace), "disk": dict(w._disk),
        "inputs": dict(w._inputs), "live": dict(w._live_inputs),
        "series": list(w._series), "label": w._label, "local": w._local,
        "results": list(a.results),
        "vars": {k: v.get() for k, v in (
            ("shape_b", w.lp_shape_v["Background"]),
            ("shape_s", w.lp_shape_v["Sample"]),
            ("roll_b", w.lp_roll_v["Background"]),
            ("roll_s", w.lp_roll_v["Sample"]),
            ("name_med", w.name_med_v), ("name_samp", w.name_samp_v),
            ("name_l2", w.name_l2_v), ("ylo", w.ylo_v), ("yhi", w.yhi_v),
            ("dp", w.dp_v), ("cmap", w.cmap_v))},
    }
    for d in (w._chan, w._trace, w._disk, w._inputs, w._live_inputs,
              w._cache, w._fits, w._msv_cache, w._seed_said):
        d.clear()
    w._series = []
    w._dk_cache = {}
    w._dk_sig = None
    w._invalidate_json_cache()
    yield w
    for name, d in (("chan", w._chan), ("trace", w._trace),
                    ("disk", w._disk), ("inputs", w._inputs),
                    ("live", w._live_inputs)):
        d.clear()
        d.update(keep[name])
    w._series = keep["series"]
    w._label = keep["label"]
    w._local = keep["local"]
    a.results = keep["results"]
    w._dk_cache = {}
    w._dk_sig = None
    w._suspend = True
    try:
        v = keep["vars"]
        w.lp_shape_v["Background"].set(v["shape_b"])
        w.lp_shape_v["Sample"].set(v["shape_s"])
        w.lp_roll_v["Background"].set(v["roll_b"])
        w.lp_roll_v["Sample"].set(v["roll_s"])
        w.name_med_v.set(v["name_med"])
        w.name_samp_v.set(v["name_samp"])
        w.name_l2_v.set(v["name_l2"])
        w.ylo_v.set(v["ylo"])
        w.yhi_v.set(v["yhi"])
        w.dp_v.set(v["dp"])
        w.cmap_v.set(v["cmap"])
    finally:
        w._suspend = False
    w._invalidate_json_cache()


def _rec(label, stem, pval, branch="C"):
    r = make_result(label, pval)
    wl = np.linspace(500.0, 900.0, 96)
    r.update({"label": label, "stem": stem, "path": stem + ".csv",
              "wl": wl,
              "bg_c": 10.0 + 0.6 * np.cos(4.0 * np.pi * 22000.0 / wl),
              "samp_c": 5.0 + 0.3 * np.cos(4.0 * np.pi * 18000.0 / wl),
              "pressure_val": pval, "branch": branch,
              "pressure_str": ("%g" % pval).replace(".", "p")})
    return r


def _folder(a, fw, path, recs, label=None):
    a.results = []
    fw._local = {"folder": str(path), "recs": list(recs), "app_sig": ()}
    fw._dk_cache = {}
    fw._dk_sig = None
    fw._label = label if label is not None else recs[0]["label"]
    fw._invalidate_json_cache()


# ---------------------------------------------------------------------------
# 3. the edge, per channel, through the panel
# ---------------------------------------------------------------------------
@gui
def test_lp_edge_reads_the_two_controls(fw):
    fw.lp_shape_v["Sample"].set("erf")
    fw.lp_roll_v["Sample"].set("4.5")
    assert fw._lp_edge("Sample") == ("erf", 4.5)
    # the two channels are independent
    assert fw._lp_edge("Background")[0] == "tanh"


@gui
def test_lp_edge_falls_back_on_nonsense(fw):
    fw.lp_shape_v["Sample"].set("logistic")
    fw.lp_roll_v["Sample"].set("0")
    assert fw._lp_edge("Sample") == ("tanh", 2.0)


@gui
def test_edge_is_in_the_cache_signature(a, fw, tmp_path):
    _folder(a, fw, tmp_path, [_rec("20 GPa", "s_20p0", 20.0)])
    fw.lp_on_v["Sample"].set(True)
    before = fw._sig("Sample")
    fw.lp_shape_v["Sample"].set("hard")
    assert fw._sig("Sample") != before
    back = fw._sig("Sample")
    fw.lp_roll_v["Sample"].set("6")
    assert fw._sig("Sample") != back


@gui
def test_removed_curve_uses_the_chosen_edge(a, fw, tmp_path):
    _folder(a, fw, tmp_path, [_rec("20 GPa", "s_20p0", 20.0)])
    fw.lp_on_v["Sample"].set(True)
    fw.lp_v["Sample"].set("15")
    x = np.array([20.0])                     # past the cutoff
    fw.lp_shape_v["Sample"].set("tanh")
    soft = fw._removed_curve("Sample", x)[0]
    fw.lp_shape_v["Sample"].set("hard")
    assert fw._removed_curve("Sample", x)[0] == 1.0
    assert soft < 1.0


@gui
def test_live_drag_cutoff_overrides_the_stored_one(a, fw, tmp_path):
    _folder(a, fw, tmp_path, [_rec("20 GPa", "s_20p0", 20.0)])
    fw.lp_on_v["Sample"].set(True)
    fw.lp_v["Sample"].set("15")
    x = np.array([20.0])
    at_15 = fw._removed_curve("Sample", x)[0]
    at_40 = fw._removed_curve("Sample", x, lp_cut=40.0)[0]
    assert at_40 < at_15


@gui
def test_edge_rides_in_the_per_point_inputs(a, fw, tmp_path):
    _folder(a, fw, tmp_path, [_rec("20 GPa", "s_20p0", 20.0)])
    fw.lp_shape_v["Background"].set("erf")
    fw.lp_roll_v["Background"].set("3.5")
    snap = fw._input_snapshot()
    assert snap["lp_edge_shape"]["Background"] == "erf"
    assert snap["lp_rolloff_um"]["Background"] == 3.5
    fw.lp_shape_v["Background"].set("tanh")
    fw.lp_roll_v["Background"].set("2")
    assert fw._apply_input_snapshot(snap) is True
    assert fw._lp_edge("Background") == ("erf", 3.5)


@gui
def test_edge_survives_the_continuity_file(a, fw, tmp_path):
    _folder(a, fw, tmp_path, [_rec("20 GPa", "s_20p0", 20.0)])
    fw.lp_shape_v["Sample"].set("hard")
    fw.lp_roll_v["Sample"].set("7")
    fw._commit()
    payload = fw._series_payload()
    text = json.dumps(payload)               # the file must be plain JSON
    back = json.loads(text)
    row = back["inputs"]["stem:s_20p0"]
    assert row["lp_edge_shape"]["Sample"] == "hard"
    assert row["lp_rolloff_um"]["Sample"] == 7.0


@gui
def test_edge_survives_the_session_payload(a, fw, tmp_path):
    _folder(a, fw, tmp_path, [_rec("20 GPa", "s_20p0", 20.0)])
    fw.lp_shape_v["Sample"].set("erf")
    fw.lp_roll_v["Sample"].set("5")
    payload = json.loads(json.dumps(fw.save_state()))
    fw.lp_shape_v["Sample"].set("tanh")
    fw.lp_roll_v["Sample"].set("2")
    fw.load_state(payload)
    assert fw._lp_edge("Sample") == ("erf", 5.0)


@gui
def test_a_payload_without_the_edge_still_loads(a, fw, tmp_path):
    """A session written before this wave has no lp_edge block; it must read
    back as the shipped edge, not raise."""
    _folder(a, fw, tmp_path, [_rec("20 GPa", "s_20p0", 20.0)])
    payload = json.loads(json.dumps(fw.save_state()))
    payload["notch"].pop("lp_edge", None)
    payload.pop("view_opts", None)
    fw.load_state(payload)
    assert fw._lp_edge("Sample")[0] in fringe_config.LP_EDGE_SHAPES


@gui
def test_edge_reaches_the_defringe_recipe(a, fw, tmp_path):
    _folder(a, fw, tmp_path, [_rec("20 GPa", "s_20p0", 20.0)])
    fw._ch("Sample")["user_centers"] = [22.0]
    fw.lp_on_v["Sample"].set(True)
    fw.lp_shape_v["Sample"].set("erf")
    fw.lp_roll_v["Sample"].set("3")
    entry = (fw.defringe_recipe() or {}).get("channels", {}).get("samp_c")
    assert entry is not None
    assert entry["lp_edge_shape"] == "erf"
    assert entry["lp_rolloff_um"] == 3.0
    # plain JSON types, so the Run's provenance sidecar still writes
    json.dumps(entry)


@gui
def test_a_stale_committed_edge_raises_no_leave_prompt(a, fw, tmp_path):
    """A point committed before this wave carries no edge block. Reading its
    absence as an edit would prompt on every point of an old session."""
    _folder(a, fw, tmp_path, [_rec("20 GPa", "s_20p0", 20.0)])
    fw._commit()
    fw._inputs[fw._dkey()].pop("lp_edge_shape", None)
    fw._inputs[fw._dkey()].pop("lp_rolloff_um", None)
    assert "the low-pass edge changed" not in fw._committed_diff()


# ---------------------------------------------------------------------------
# 4. the FFT y-axis range
# ---------------------------------------------------------------------------
@gui
def test_blank_boxes_are_auto(fw):
    fw.ylo_v.set("")
    fw.yhi_v.set("")
    assert fw._forward_y_lim() is None


@gui
def test_one_bound_at_a_time(fw):
    fw.ylo_v.set("")
    fw.yhi_v.set("0.4")
    assert fw._forward_y_lim() == (None, 0.4)
    fw.ylo_v.set("0.05")
    fw.yhi_v.set("")
    assert fw._forward_y_lim() == (0.05, None)


@gui
def test_unreadable_bound_stays_auto(fw):
    fw.ylo_v.set("wide")
    fw.yhi_v.set("0.4")
    assert fw._forward_y_lim() == (None, 0.4)


@gui
def test_y_range_persists_through_the_session(a, fw, tmp_path):
    _folder(a, fw, tmp_path, [_rec("20 GPa", "s_20p0", 20.0)])
    fw.ylo_v.set("0.1")
    fw.yhi_v.set("0.9")
    payload = json.loads(json.dumps(fw.save_state()))
    fw._reset_yaxis()
    assert fw._forward_y_lim() is None
    fw.load_state(payload)
    assert fw._forward_y_lim() == (0.1, 0.9)


# ---------------------------------------------------------------------------
# 5. the fundamental's three states
# ---------------------------------------------------------------------------
@gui
def test_fundamental_auto_is_the_brightest_default(a, fw, tmp_path):
    _folder(a, fw, tmp_path, [_rec("20 GPa", "s_20p0", 20.0)])
    ch = fw._ch("Sample")
    ch["default_centers"] = [18.0, 36.0]
    assert ch["user_fundamental"] is None
    assert fw._fund_key("Sample") == 18.0


@gui
def test_fundamental_pins_and_resets(a, fw, tmp_path):
    _folder(a, fw, tmp_path, [_rec("20 GPa", "s_20p0", 20.0)])
    ch = fw._ch("Sample")
    ch["default_centers"] = [18.0, 36.0]
    fw._pin_fundamental("Sample", 36.0)
    assert fw._fund_key("Sample") == 36.0
    fw._pin_fundamental("Sample", None)
    auto = fw._ch("Sample")["default_centers"]
    assert fw._fund_key("Sample") == (auto[0] if auto else None)
    assert fw._ch("Sample")["user_fundamental"] is None


@gui
def test_fundamental_none_is_not_auto(a, fw, tmp_path):
    """The distinction the sentinel exists for: both read back as no key,
    and only one of them means the reader said so."""
    _folder(a, fw, tmp_path, [_rec("20 GPa", "s_20p0", 20.0)])
    ch = fw._ch("Sample")
    ch["default_centers"] = [18.0, 36.0]
    fw._pin_fundamental("Sample", fringe_panel.FUND_NONE)
    assert fw._fund_key("Sample") is None
    assert ch["user_fundamental"] == fringe_panel.FUND_NONE


@gui
def test_radio_click_again_clears_to_none(a, fw, tmp_path):
    _folder(a, fw, tmp_path, [_rec("20 GPa", "s_20p0", 20.0)])
    ch = fw._ch("Sample")
    ch["default_centers"] = [18.0, 36.0]
    fw._fund_radio("Sample", 36.0)                 # pin the second peak
    assert ch["user_fundamental"] == 36.0
    fw._fund_radio("Sample", 36.0)                 # the same row again
    assert ch["user_fundamental"] == fringe_panel.FUND_NONE
    fw._fund_radio("Sample", 18.0)                 # a different row pins
    assert ch["user_fundamental"] == 18.0


@gui
def test_fundamental_none_round_trips_through_the_snapshot(a, fw, tmp_path):
    _folder(a, fw, tmp_path, [_rec("20 GPa", "s_20p0", 20.0)])
    ch = fw._ch("Sample")
    ch["default_centers"] = [18.0]
    fw._pin_fundamental("Sample", fringe_panel.FUND_NONE)
    snap = json.loads(json.dumps(fw._input_snapshot()))
    assert snap["notch"]["Sample"]["fund"] == fringe_panel.FUND_NONE
    ch["user_fundamental"] = None
    fw._apply_input_snapshot(snap)
    assert fw._ch("Sample")["user_fundamental"] == fringe_panel.FUND_NONE


@gui
def test_his_none_sentinel_reads_back(a, fw, tmp_path):
    """A file HIS program wrote spells the cleared state 'none'; Wave C left
    it reading as auto, which this wave finishes."""
    _folder(a, fw, tmp_path, [_rec("20 GPa", "s_20p0", 20.0)])
    snap = {"notch": {"Sample": {"user": [], "desel": [], "removed": [],
                                 "widths": {}, "fund": "none"}}}
    fw._apply_input_snapshot(snap)
    assert fw._ch("Sample")["user_fundamental"] == fringe_panel.FUND_NONE


@gui
def test_no_fundamental_means_no_added_fundamental(a, fw, tmp_path):
    """A cleared channel must not ask the pipeline to put the detected
    fundamental back: that is the opposite of what the reader said."""
    _folder(a, fw, tmp_path, [_rec("20 GPa", "s_20p0", 20.0)])
    ch = fw._ch("Sample")
    ch["user_centers"] = [22.0]
    ch["default_centers"] = []
    ch["user_fundamental"] = fringe_panel.FUND_NONE
    entry = fw._recipe_channel(ch, None, "Sample")
    assert entry.get("add_fundamental") is not True


# ---------------------------------------------------------------------------
# 6. free-text material names
# ---------------------------------------------------------------------------
@gui
def test_blank_names_fall_back_to_the_models(fw):
    fw.name_med_v.set("")
    fw.name_samp_v.set("")
    fw.name_l2_v.set("")
    fw.medium_v.set("Ar")
    fw.layer2_v.set("KCl")
    med, samp, l2 = fw._material_names()
    assert med == "Argon"                # the label's first word
    assert samp == "sample"
    assert l2 == "KCl"


@gui
def test_names_reach_the_row_labels(fw):
    keep = fw.medium_v.get()
    try:
        fw.name_med_v.set("neon")
        fw.name_samp_v.set("olivine")
        fw._relabel_stack()
        assert fw._stack_lbls["n_medium"].cget("text") == "n neon"
        assert fw._stack_lbls["t"].cget("text") == "t olivine (um)"
        assert "neon" in fw._stack_lbls["d1"].cget("text")

        # a blank box takes the MODEL's own name
        fw.name_med_v.set("")
        fw.medium_v.set("Ar")
        fw._relabel_stack()
        assert fw._stack_lbls["n_medium"].cget("text") == "n Argon"
        assert "Argon" in fw._stack_lbls["d1"].cget("text")

        # and the manual medium ("Other") carries no material name at all,
        # so every row reads the shipped caption again
        fw.name_samp_v.set("")
        fw.medium_v.set("Other")
        fw._relabel_stack()
        assert fw._stack_lbls["n_medium"].cget("text") == "n medium"
        assert fw._stack_lbls["n_sample"].cget("text") == "n sample"
        assert fw._stack_lbls["t"].cget("text") == "t sample (um)"
        assert fw._stack_lbls["d1"].cget("text") == "d1 lower medium (um)"
        assert fw._stack_lbls["d2"].cget("text") == "d2 upper medium (um)"
    finally:
        fw.medium_v.set(keep)
        fw.name_med_v.set("")
        fw.name_samp_v.set("")
        fw._relabel_stack()


@gui
def test_layer2_name_takes_the_thickness_rows_when_it_is_on(fw):
    fw.name_med_v.set("neon")
    fw.name_l2_v.set("rim")
    fw.layer2_on_v.set(True)
    fw._relabel_stack()
    assert "rim" in fw._stack_lbls["d2"].cget("text")
    fw.layer2_on_v.set(False)
    fw._relabel_stack()
    assert "neon" in fw._stack_lbls["d2"].cget("text")


@gui
def test_names_reach_the_schematic_header(a, fw, tmp_path):
    _folder(a, fw, tmp_path, [_rec("20 GPa", "s_20p0", 20.0)])
    fw.name_samp_v.set("olivine")
    fw.name_med_v.set("neon")
    p = fw._stack_params(fw._record())
    assert "olivine" in fw._schematic(p, "sample")
    assert "neon" in fw._schematic(p, "medium")


@gui
def test_names_are_the_series_materials_seed(a, fw, tmp_path):
    _folder(a, fw, tmp_path, [_rec("20 GPa", "s_20p0", 20.0)])
    fw.name_samp_v.set("olivine")
    fw.name_med_v.set("neon")
    names = fw._series_payload()["materials"]["names"]
    assert names["sample"] == "olivine"
    assert names["medium"] == "neon"


# ---------------------------------------------------------------------------
# 7. the calc-n row
# ---------------------------------------------------------------------------
@gui
def test_blank_pressure_box_takes_the_trace_pressure(a, fw, tmp_path):
    _folder(a, fw, tmp_path, [_rec("20 GPa", "s_20p0", 20.0)])
    fw.dp_v.set("")
    assert fw._model_pressure() == 20.0
    fw._dp_blank_restore()
    assert fw.dp_v.get() == "20"


@gui
def test_pressure_box_overrides_the_models(a, fw, tmp_path):
    _folder(a, fw, tmp_path, [_rec("20 GPa", "s_20p0", 20.0)])
    fw.medium_v.set("Ar")
    fw.dp_v.set("")
    at_trace = fw._stack_params(fw._record())["n_medium"]
    fw.dp_v.set("60")
    at_60 = fw._stack_params(fw._record())["n_medium"]
    assert fw._model_pressure() == 60.0
    assert at_60 != at_trace


@gui
def test_ambient_button_puts_the_anvil_on_the_constant(fw):
    fw.diamond_v.set("cauchy")
    fw._ambient_n()
    assert fw.diamond_v.get() == "constant"


# ---------------------------------------------------------------------------
# 8. the stem palette and skip-faint
# ---------------------------------------------------------------------------
@gui
def test_default_palette_is_okabe_ito(fw):
    fw.cmap_v.set("okabeito")
    fw.skipfaint_v.set(False)
    assert list(fw._stem_palette()) == list(fringe_panel.OKABE_ITO)


@gui
def test_skip_faint_drops_the_palest_and_never_empties(fw):
    fw.cmap_v.set("okabeito")
    fw.skipfaint_v.set(False)
    full = fw._stem_palette()
    fw.skipfaint_v.set(True)
    kept = fw._stem_palette()
    assert kept
    assert len(kept) <= len(full)
    for c in kept:
        assert not fringe_panel._is_faint(c)


def test_bright_yellow_is_not_faint_but_pale_yellow_is():
    """Yellow is its own branch, so Okabe-Ito's #F0E442 survives."""
    assert not fringe_panel._is_faint("#F0E442")
    assert fringe_panel._is_faint("#FFFDE0")


# ---------------------------------------------------------------------------
# 9. Reset & drop point
# ---------------------------------------------------------------------------
@gui
def test_reset_and_drop_restores_and_removes(a, fw, tmp_path):
    _folder(a, fw, tmp_path, [_rec("20 GPa", "s_20p0", 20.0)])
    fw.t_v.set("77")
    fw._series = [{"label": "20 GPa", "stem": "s_20p0", "pressure": 20.0,
                   "branch": "C", "A": 30.0, "C": 40.0, "iii": 50.0,
                   "medium": "Ar", "layer2": False, "layer2_name": "Ar",
                   "n_medium": 1.3, "n_layer2": 1.3, "diamond": "constant",
                   "solved": {}}]
    fw._reset_and_drop_point()
    assert fw._series == []
    assert float(fw.t_v.get()) == fringe_panel.SETTINGS_DEFAULTS["fr_t_um"]


@gui
def test_reset_and_drop_on_an_unrecorded_point_only_resets(a, fw, tmp_path):
    _folder(a, fw, tmp_path, [_rec("20 GPa", "s_20p0", 20.0)])
    fw.d2_v.set("12")
    fw._reset_and_drop_point()
    assert float(fw.d2_v.get()) == fringe_panel.SETTINGS_DEFAULTS["fr_d2_um"]


# ---------------------------------------------------------------------------
# 10. neighbour hints
# ---------------------------------------------------------------------------
@gui
def test_neighbour_rows_straddle_this_pressure(a, fw, tmp_path):
    recs = [_rec("10 GPa", "s_10p0", 10.0), _rec("20 GPa", "s_20p0", 20.0),
            _rec("30 GPa", "s_30p0", 30.0)]
    _folder(a, fw, tmp_path, recs, label="20 GPa")
    fw._series = [
        {"label": "10 GPa", "stem": "s_10p0", "pressure": 10.0,
         "branch": "C", "A": 30.0, "C": 40.0, "iii": 50.0, "medium": "Ar",
         "layer2": False, "n_medium": 1.3, "n_layer2": 1.3, "solved": {}},
        {"label": "30 GPa", "stem": "s_30p0", "pressure": 30.0,
         "branch": "C", "A": 31.0, "C": 41.0, "iii": 51.0, "medium": "Ar",
         "layer2": False, "n_medium": 1.3, "n_layer2": 1.3, "solved": {}}]
    below, above = fw._neighbour_rows()
    assert below["label"] == "10 GPa"
    assert above["label"] == "30 GPa"
    hint = fw._hint_for("t_s")
    assert "10 GPa" in hint and "30 GPa" in hint


@gui
def test_no_neighbours_means_no_hint(a, fw, tmp_path):
    _folder(a, fw, tmp_path, [_rec("20 GPa", "s_20p0", 20.0)])
    fw._series = []
    assert fw._hint_for("t_s") == ""
    assert fw._tip_with_hint("what it does.", "t_s") == "what it does."


# ---------------------------------------------------------------------------
# 11. the tab's navigation toolbar
# ---------------------------------------------------------------------------
@gui
def test_the_tab_has_a_toolbar(fw):
    assert fw.toolbar is not None
    assert getattr(fw.canvas, "toolbar", None) is fw.toolbar


@gui
def test_workbench_gestures_stand_down_while_a_toolbar_mode_is_armed(fw):
    assert fw._toolbar_busy() is False
    tb = fw.toolbar
    old = getattr(tb, "mode", "")
    try:
        tb.mode = "pan/zoom"
        assert fw._toolbar_busy() is True
    finally:
        tb.mode = old
