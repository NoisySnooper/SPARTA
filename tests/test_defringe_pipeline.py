"""R16: one defringe pipeline, read per trace.

Matthew tested v1.4.10 and reported two defects.  Unticking every notch (or
setting the fundamental to none) still defringed, and a low-pass edge dragged
above the peak looked ignored: the panel dropped an EMPTY centre list before
the call, so the core fell back to its `None` default and notched the
fundamental it had detected.  And the main plot, a Run's CSVs and the
thickness read went through a SECOND module for any pressure the workbench
held no state for, under its own legacy band, with no low-pass and no edge.

The old module is gone.  Everything cleans through `fringe_apply`, which makes
the same `fringe_detect.compute_channel_fit` call the workbench draws from.
This file pins the result:

  * NO FRINGE, NO CLEANING (R17 D1) -- a channel the detector passes over is
    left exactly as it came in: no notch, no low-pass, applied False, nt_um
    None.  His gate, and it is what makes `applied` and `nt_um` agree;
  * THREE STATES, once a fringe IS detected -- a list notches those centres,
    [] notches nothing, None lets the core detect this spectrum's own
    fundamental.  The low-pass is independent of the LIST: on is on;
  * EVERY PRESSURE -- the workbench answers for every loaded trace.  Live for
    the one on screen, its committed copy for a trace it has filed, its GLOBAL
    controls for the rest, and the same global recipe off the fr_ settings
    keys when the Fringe tab has never been built.  No fallback path is left;
  * ONE MASTER SWITCH -- df governs the MAIN PLOT.  Since R17 (D2) it does not
    govern the workbench's own cleaned curve, which draws whenever something
    is being filtered, as his window does.  Export > Defringed CSV is an
    explicit action and ignores the switch too;
  * INVALIDATION -- a global control reaches every trace, a notch tick reaches
    one.

The pure-module half needs no Tk.  The App half runs against the suite's ONE
shared App (tests/conftest.py).
"""
import os
import time

import numpy as np
import pytest

import fringe_apply
import fringe_panel
from conftest import gui, make_result, shared_app

USES_APP = True

NT_UM = 30.0                      # the synthetic fringe, in micron of n*t
NT_NM = NT_UM * 1000.0
GATE = dict(halfwidth_um=3.0, nt_min_nm=8000.0, nt_max_nm=300000.0)


# ---------------------------------------------------------------------------
# synthetic spectra
# ---------------------------------------------------------------------------
def _fringed(nt_um=NT_UM, amp=0.06, n=1400, lo=500.0, hi=900.0):
    """Counts with ONE clean interference fringe of optical path n*t.

    The vendored core's convention: a layer of optical path n*t modulates a
    channel as cos(4 pi n*t / lambda), with n*t in nm.
    """
    wl = np.linspace(lo, hi, n)
    base = 1000.0 * (1.0 + 0.30 * (wl - lo) / (hi - lo))   # lamp envelope
    y = base * (1.0 + amp * np.cos(4.0 * np.pi * nt_um * 1000.0 / wl))
    return wl, y


def _flat(n=1400, lo=500.0, hi=900.0, seed=7):
    """Counts with no fringe in them: a lamp envelope and a little noise."""
    wl = np.linspace(lo, hi, n)
    base = 1000.0 * (1.0 + 0.30 * (wl - lo) / (hi - lo))
    rng = np.random.RandomState(seed)
    return wl, base * (1.0 + 0.002 * rng.randn(n))


def _rec(label, pval, nt_um=NT_UM, stem=None):
    """An engine-style record whose two raw channels carry a fringe."""
    wl, samp = _fringed(nt_um)
    _wl, bg = _fringed(nt_um + 6.0)
    r = make_result(label, pval, wl=wl, samp=samp, bg=bg,
                    dark=np.ones(wl.size))
    if stem:
        r["stem"] = stem
    return r


# ===========================================================================
# 1. the three states of a notch list
# ===========================================================================
def test_none_lets_the_detector_choose():
    """The automatic path: detect, gate, notch the fundamental."""
    wl, y = _fringed()
    out = fringe_apply.clean_channel(wl, y, **GATE)
    assert out["applied"] is True
    assert out["nt_um"] == pytest.approx(NT_UM, rel=0.05)
    assert out["pvalue"] < 1e-4
    assert not np.allclose(out["clean"], y)
    # centers_nm reports what the CALLER named, and it named nothing
    assert out["centers_nm"] is None


def test_none_leaves_a_flat_channel_alone():
    """No confident fringe, no automatic notch."""
    wl, y = _flat()
    out = fringe_apply.clean_channel(wl, y, **GATE)
    assert out["applied"] is False
    assert np.array_equal(out["clean"], y)


def test_an_empty_list_notches_nothing_and_the_clean_is_the_raw():
    """(a) THE fix.  [] is a decision: every box unticked, nothing removed.

    With no low-pass either there is no mask at all, so the returned
    spectrum is the input, value for value.
    """
    wl, y = _fringed()
    out = fringe_apply.clean_channel(wl, y, notch_centers_nm=[],
                                     notch_halfwidths_um=[], **GATE)
    assert out["applied"] is False
    assert np.array_equal(out["clean"], y)
    assert out["centers_nm"] == []
    # the detector still ran, so the report can still say what it found
    assert out["nt_um"] == pytest.approx(NT_UM, rel=0.05)


def test_an_empty_list_still_takes_the_low_pass():
    """(b) The low-pass is independent of the notch list.

    A cutoff far above every fringe in the spectrum passes it whole, so the
    result tracks the raw counts; the same cutoff dropped under the fringe
    removes it.  Either way something was applied.
    """
    wl, y = _fringed()
    wide = fringe_apply.clean_channel(wl, y, notch_centers_nm=[], lowpass=True,
                                      lp_cutoff_um=2000.0, **GATE)
    assert wide["applied"] is True
    assert np.allclose(wide["clean"], y, rtol=0, atol=1e-6 * np.ptp(y))

    tight = fringe_apply.clean_channel(wl, y, notch_centers_nm=[],
                                       lowpass=True, lp_cutoff_um=8.0, **GATE)
    assert tight["applied"] is True
    assert np.ptp(tight["clean"]) < np.ptp(y)


def test_the_low_pass_does_not_land_on_a_channel_with_no_fringe():
    """R17 D1, the reversal.  A spectrum the detector passes over is left
    alone: the mask stage never runs, so the low-pass does not either.

    Before R17 the low-pass ran anyway.  On the real series that is 47% of
    channels (81 of 174), each drawn 4-9% of full scale off raw at every
    cutoff -- which is what "the low-pass does something unexpected" was.
    His program applies nothing to these.
    """
    wl, y = _flat()
    out = fringe_apply.clean_channel(wl, y, notch_centers_nm=[], lowpass=True,
                                     lp_cutoff_um=8.0, **GATE)
    assert out["applied"] is False
    assert out["nt_um"] is None
    assert np.array_equal(out["clean"], y)


def test_applied_never_comes_without_a_thickness():
    """The pair a caller reports from.  `applied` True always travels with a
    number, so a report can print n*t beside it without guarding -- which is
    the crash the defringe switch used to hit."""
    wl, fringed = _fringed()
    _wl, flat = _flat()
    for y in (fringed, flat):
        for kw in ({}, dict(notch_centers_nm=[]),
                   dict(lowpass=True, lp_cutoff_um=8.0),
                   dict(notch_centers_nm=[NT_NM], notch_halfwidths_um=[3.0])):
            out = fringe_apply.clean_channel(wl, y, **dict(GATE, **kw))
            assert (out["nt_um"] is not None) or (out["applied"] is False)


def test_a_named_list_waits_for_the_p_gate():
    """R17 D1.  A p gate no spectrum can clear stops the named centre too.

    The gate is the detection, and the detection is what the whole mask
    stage hangs on -- so it governs the picks as well as the automatic path.
    """
    gate = dict(GATE, pvalue_max=1e-300)
    wl, y = _fringed()
    auto = fringe_apply.clean_channel(wl, y, **gate)
    assert auto["applied"] is False
    assert np.array_equal(auto["clean"], y)

    picked = fringe_apply.clean_channel(wl, y, notch_centers_nm=[NT_NM],
                                        notch_halfwidths_um=[3.0], **gate)
    assert picked["applied"] is False
    assert picked["nt_um"] is None
    assert np.array_equal(picked["clean"], y)
    # it still reports what the CALLER named, so a panel can say what it asked
    assert picked["centers_nm"] == [NT_NM]


def test_a_named_list_waits_for_a_detection():
    """R17 D1.  A search band that holds no peak: nothing is cut."""
    wl, y = _fringed()
    out = fringe_apply.clean_channel(wl, y, notch_centers_nm=[NT_NM],
                                     notch_halfwidths_um=[3.0],
                                     halfwidth_um=3.0,
                                     nt_min_nm=180000.0, nt_max_nm=300000.0)
    assert out["applied"] is False
    assert np.array_equal(out["clean"], y)


def test_the_core_honours_an_empty_list_directly():
    """The same grammar one level down, where the mask is built.

    The fringe IS there and the detector finds it; the empty list says to
    leave it alone, so the mask is all-pass and the notched spectrum is the
    raw one.  Before R16 the empty list was dropped and the fundamental came
    out anyway.
    """
    import fringe_detect
    wl, y = _fringed()
    fit, _I, nt, _d = fringe_detect.compute_channel_fit(
        wl, y, run_fits=False, notch_centers_nm=[])
    fi = fit["fft_info"]
    assert nt is not None                       # the fringe IS there
    assert np.allclose(fi["I_notch_1x"], y, rtol=0, atol=1e-6 * np.ptp(y))

    auto, _I2, _nt2, _d2 = fringe_detect.compute_channel_fit(
        wl, y, run_fits=False)                  # None: the detector decides
    assert not np.allclose(auto["fft_info"]["I_notch_1x"], y,
                           rtol=0, atol=1e-6 * np.ptp(y))


def test_nan_points_come_back_as_nan():
    wl, y = _fringed()
    y = y.copy()
    y[10:14] = np.nan
    out = fringe_apply.clean_channel(wl, y, **GATE)
    assert out["applied"] is True
    assert np.all(np.isnan(out["clean"][10:14]))
    assert np.all(np.isfinite(out["clean"][20:-20]))


# ===========================================================================
# 2. add_fundamental: the picks without the centre they were picked beside
# ===========================================================================
def test_add_fundamental_brings_the_detected_centre_in():
    wl, y = _fringed()
    out = fringe_apply.clean_channel(wl, y, notch_centers_nm=[NT_NM * 2.0],
                                     add_fundamental=True, **GATE)
    assert out["applied"] is True
    assert len(out["centers_nm"]) == 2
    assert out["centers_nm"][0] == pytest.approx(NT_NM, rel=0.05)
    assert out["centers_nm"][1] == NT_NM * 2.0


def test_add_fundamental_never_doubles_a_centre():
    """Two Gaussians at one centre cut twice as deep, so a pick already on
    the fundamental stands alone."""
    wl, y = _fringed()
    out = fringe_apply.clean_channel(wl, y, notch_centers_nm=[NT_NM],
                                     add_fundamental=True, **GATE)
    assert out["centers_nm"] == [NT_NM]


def test_widths_stay_parallel_to_their_centres():
    wl, y = _fringed()
    wide = fringe_apply.clean_channel(wl, y, notch_centers_nm=[NT_NM * 2.0],
                                      notch_halfwidths_um=[9.0],
                                      add_fundamental=True, **GATE)
    narrow = fringe_apply.clean_channel(wl, y, notch_centers_nm=[NT_NM * 2.0],
                                        notch_halfwidths_um=[0.5],
                                        add_fundamental=True, **GATE)
    assert not np.allclose(wide["clean"], narrow["clean"])


# ===========================================================================
# 3. the detector the thickness plot reads
# ===========================================================================
def test_detect_nt_is_notch_set_independent():
    """n*t is a MEASUREMENT of the dominant fringe, so it takes no centres."""
    wl, y = _fringed()
    nt, pv = fringe_apply.detect_nt(wl, y, **GATE)
    assert nt == pytest.approx(NT_UM, rel=0.05)
    assert pv < 1e-4
    assert fringe_apply.detect_nt(*_flat(), **GATE)[0] is None


# ===========================================================================
# 4. the notch columns of a trace's CSV  (R20: no standalone notch file)
# ===========================================================================
def test_the_columns_take_per_channel_kwargs(monkeypatch):
    """The two channels carry different fringes and are cleaned apart.

    Background is cleaned first, then Sample, which is the order the ratio is
    formed in.
    """
    seen = []
    real = fringe_apply.clean_channel

    def spy(wl, counts, *a, **kw):
        seen.append(dict(kw))
        return real(wl, counts, *a, **kw)

    monkeypatch.setattr(fringe_apply, "clean_channel", spy)
    r = _rec("20 GPa", 20.0)
    cols = fringe_apply.notch_columns(
        r, halfwidth_um=3.0,
        bg_kw={"notch_centers_nm": [NT_NM]},
        s_kw={"notch_centers_nm": [NT_NM * 2.0]})
    assert cols["applied_bg"] is True and cols["applied_s"] is True
    assert [kw["notch_centers_nm"] for kw in seen] == [[NT_NM],
                                                       [NT_NM * 2.0]]
    assert all(kw["halfwidth_um"] == 3.0 for kw in seen)


def test_the_columns_match_the_pipeline_and_reach_the_csv(tmp_path):
    """Sample_notch IS what clean_channel returns, and it lands in the file.

    R20 merged the three columns into the trace's own absorbance CSV, so the
    round trip through engine's writer is part of the contract.
    """
    import csv
    import engine
    r = _rec("20 GPa", 20.0, stem="s_20p0")
    kw = dict(GATE)
    cols = fringe_apply.notch_columns(r, **kw)
    want = fringe_apply.clean_channel(r["wl"], r["samp_c"], **kw)["clean"]
    assert np.allclose(cols["Sample_notch"], want)
    assert cols["nt_s_um"] == pytest.approx(NT_UM, rel=0.05)
    assert cols["p_s"] < 1e-4

    path = engine.write_absorbance_csv(
        r, str(tmp_path),
        extra=[(h, cols[h]) for h in ("Absorbance_notch", "Background_notch",
                                      "Sample_notch")])
    with open(path, newline="", encoding="utf-8") as fh:
        rows = list(csv.reader(fh))
    head = rows[0]
    assert head == ["Wavelength_nm", "Wavenumber_cm-1", "Absorbance", "Dark",
                    "Background", "Sample", "Absorbance_notch",
                    "Background_notch", "Sample_notch"]
    col = np.array([float(row[head.index("Sample_notch")]) for row in rows[1:]])
    assert np.allclose(col, want)


def test_an_uncleaned_channel_leaves_a_blank_column(tmp_path):
    """Nothing notched, nothing low-passed: two blank channel columns.

    Absorbance_notch is filled all the same -- with nothing removed it is the
    straight absorbance -- so the merged CSV never carries a hole there.
    """
    import csv
    import engine
    r = _rec("20 GPa", 20.0, stem="s_20p0")
    cols = fringe_apply.notch_columns(r, notch_centers_nm=[], **GATE)
    assert cols["applied_bg"] is False and cols["applied_s"] is False
    assert np.isnan(cols["Background_notch"]).all()
    assert np.isnan(cols["Sample_notch"]).all()
    straight = np.log10((r["bg_c"] - r["dark_c"])
                        / (r["samp_c"] - r["dark_c"]))
    assert np.allclose(cols["Absorbance_notch"], straight, equal_nan=True)

    path = engine.write_absorbance_csv(
        r, str(tmp_path),
        extra=[(h, cols[h]) for h in ("Absorbance_notch", "Background_notch",
                                      "Sample_notch")])
    with open(path, newline="", encoding="utf-8") as fh:
        rows = list(csv.reader(fh))
    head = rows[0]
    i_bg, i_s = head.index("Background_notch"), head.index("Sample_notch")
    assert all(row[i_bg] == "" and row[i_s] == "" for row in rows[1:])
    assert all(row[head.index("Absorbance_notch")] != "" for row in rows[1:])


# ===========================================================================
# 5. the retirement of the old module
# ===========================================================================
def test_the_old_module_is_gone():
    with pytest.raises(ImportError):
        __import__("defringe")


def test_no_fractional_width_convention_survives():
    """Half-widths are absolute n*t um everywhere. 'width_fracs' survives
    only as the upstream sweep's own result key, which is a list of swept
    values rather than a convention."""
    import inspect

    import fringe_notch
    src = inspect.getsource(fringe_notch)
    assert "width_frac=" not in src            # the retired keyword
    assert "LEGACY_CONFIG" not in src


def test_write_to_defringe_is_retired():
    assert not hasattr(fringe_panel.FringeWorkbench, "_write_to_defringe")
    assert "fr_apply_centers" not in fringe_panel.SETTINGS_DEFAULTS
    assert "fr_apply_centers" not in fringe_panel.C_SETTINGS_DEFAULTS


def test_defringe_state_is_gates_only():
    """It carries the series-wide numbers, and no centres at all."""
    st = fringe_panel.defringe_state({"fr_apply_centers": {"bg_c": {}}}, None)
    assert sorted(st) == ["halfwidth_um", "nt_max_um", "nt_min_um",
                          "pvalue_max"]


# ===========================================================================
# 6. the global recipe, with no UI at all
# ===========================================================================
def test_the_settings_only_recipe_is_a_whole_recipe():
    """A Run before the Fringe tab is ever opened still has an answer."""
    rp = fringe_panel.global_recipe({}, None, rec={"pressure_val": 20.0},
                                    folder=None)
    assert rp["source"] == "global"
    assert sorted(rp["gates"]) == ["halfwidth_um", "nt_max_nm", "nt_min_nm",
                                   "pvalue_max"]
    for key in ("bg_c", "samp_c"):
        # automatic: each spectrum is cleaned at its OWN detected fundamental
        assert rp["channels"][key]["notch_centers_nm"] is None
    assert rp["cfg"] is not None


def test_the_settings_only_recipe_carries_the_saved_low_pass():
    s = {"fr_lp_s_on": True, "fr_lp_s_um": 22.0, "fr_lp_s_shape": "erf",
         "fr_lp_s_roll": 4.0, "fr_lp_bg_on": False}
    rp = fringe_panel.global_recipe(s, None)
    samp = rp["channels"]["samp_c"]
    assert samp["lowpass"] is True
    assert samp["lp_cutoff_um"] == pytest.approx(22.0)
    assert samp["lp_edge_shape"] == "erf"
    assert samp["lp_rolloff_um"] == pytest.approx(4.0)
    assert "lowpass" not in rp["channels"]["bg_c"]


def test_the_settings_only_config_is_the_saved_detection_card():
    """global_cfg is the no-UI twin of _cfg_for: same window, same band."""
    s = {"fr_wl_min": 640.0, "fr_wl_max": 760.0, "fr_nt_min_um": 9.0,
         "fr_nt_max_um": 120.0, "fr_pvalue_max": 1e-3, "fr_halfwidth_um": 4.5}
    cfg = fringe_panel.global_cfg(s, None, None)
    assert cfg.fit_wl_min_nm == pytest.approx(640.0)
    assert cfg.fit_wl_max_nm == pytest.approx(760.0)
    assert cfg.fringe_nt_min_nm == pytest.approx(9000.0)
    assert cfg.fringe_nt_max_nm == pytest.approx(120000.0)
    assert cfg.fringe_pvalue_max == pytest.approx(1e-3)
    assert cfg.notch_halfwidth_um == pytest.approx(4.5)


def test_the_settings_only_config_follows_the_lamp_date():
    """The acquisition folder's month moves the fine band, as the batch does."""
    base = fringe_panel.global_cfg({}, None, None)
    dated = fringe_panel.global_cfg({}, None, "X/Y03_ch29_Nov2025_ProcessedCSV")
    assert dated.fine_wn_lo != base.fine_wn_lo


def test_a_wavelength_override_reaches_the_settings_only_config():
    s = {"fr_wl_overrides": {"/data/run7": [610.0, 690.0]}}
    cfg = fringe_panel.global_cfg(s, None, "/data/run7")
    assert cfg.fit_wl_min_nm == pytest.approx(610.0)
    assert cfg.fit_wl_max_nm == pytest.approx(690.0)


# ===========================================================================
# 7. the App: per-trace consumption  (every test here carries @gui)
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
            w._label, w._local, list(a.results))
    for d in (w._chan, w._trace, w._disk, w._inputs, w._cache):
        d.clear()
    w._dk_cache = {}
    w._dk_sig = None
    a.notch_cache.clear()
    yield w
    for d, src in ((w._chan, keep[0]), (w._trace, keep[1]),
                   (w._disk, keep[2]), (w._inputs, keep[3])):
        d.clear()
        d.update(src)
    w._label = keep[4]
    w._local = keep[5]
    a.results = keep[6]
    w._dk_cache = {}
    w._dk_sig = None
    a.notch_cache.clear()


def _load(a, fw, recs, label=None):
    """Make `recs` the loaded series, without touching the disk."""
    a.results = list(recs)
    fw._local = None
    fw._dk_cache = {}
    fw._dk_sig = None
    fw._label = label if label is not None else recs[0]["label"]


def _ticked(a, recs, shown):
    """Put `recs` on the plot with `shown` (labels) ticked."""
    import tkinter as tk
    a.results = list(recs)
    a.trace_vars = {r["label"]: tk.BooleanVar(value=(r["label"] in shown))
                    for r in recs}


@gui
def test_stem_agrees_with_the_workbench(a, fw):
    """The app matches a record to a recipe by the workbench's own key."""
    r = _rec("20 GPa", 20.0)
    _load(a, fw, [r])
    assert a._trace_stem(r) == fw._stem_of(r["label"])
    assert fw._dkey(r["label"]) == "stem:" + a._trace_stem(r)


@gui
def test_an_unvisited_pressure_gets_the_global_recipe(a, fw):
    """(c) No pressure falls through to a second path any more."""
    r20 = _rec("20 GPa", 20.0, stem="s_20p0")
    r30 = _rec("30 GPa", 30.0, stem="s_30p0")
    _load(a, fw, [r20, r30], label="20 GPa")
    fw.lp_on_v["Sample"].set(True)
    fw.lp_v["Sample"].set("18")
    try:
        rp = a._defringe_recipe(r30)           # never opened in the workbench
        assert rp is not None
        assert rp["source"] == "global"
        kw = a._notch_kw("samp_c", recipe=rp)
        # its OWN fundamental, not another pressure's peaks
        assert kw["notch_centers_nm"] is None
        # under the panel's global low-pass and edge
        assert kw["lowpass"] is True
        assert kw["lp_cutoff_um"] == pytest.approx(18.0)
        assert kw["lp_edge_shape"] in fringe_panel.LP_EDGE_SHAPES
        assert kw["cfg"] is not None
    finally:
        fw.lp_on_v["Sample"].set(False)


@gui
def test_the_loaded_trace_reads_live(a, fw):
    """An edit on the chart reaches the main plot without a commit."""
    r = _rec("20 GPa", 20.0)
    _load(a, fw, [r])
    ch = fw._ch("Sample")
    ch["default_centers"] = [NT_UM]
    ch["user_centers"] = [NT_UM * 2.0]
    rp = a._defringe_recipe(r)
    assert rp["source"] == "live"
    kw = a._notch_kw("samp_c", recipe=rp)
    assert kw["notch_centers_nm"] == [NT_NM, NT_NM * 2.0]
    assert kw["notch_halfwidths_um"] == [fw._width_of("Sample", NT_UM)] * 2
    assert "add_fundamental" not in kw       # the fundamental is in the list
    # the channel nobody touched falls to the global controls on its own
    assert rp["channels"]["bg_c"]["notch_centers_nm"] is None


@gui
def test_unticking_every_notch_sends_an_empty_list(a, fw):
    """Matthew's first defect, at the recipe boundary."""
    r = _rec("20 GPa", 20.0)
    _load(a, fw, [r])
    ch = fw._ch("Sample")
    ch["default_centers"] = [NT_UM]
    ch["unticked"] = {NT_UM}
    kw = a._notch_kw("samp_c", r)
    assert kw["notch_centers_nm"] == []
    assert "add_fundamental" not in kw


@gui
def test_a_cleared_fundamental_sends_an_empty_list(a, fw):
    r = _rec("20 GPa", 20.0)
    _load(a, fw, [r])
    ch = fw._ch("Sample")
    ch["default_centers"] = [NT_UM]
    ch["unticked"] = {NT_UM}
    ch["user_fundamental"] = fringe_panel.FUND_NONE
    kw = a._notch_kw("samp_c", r)
    assert kw["notch_centers_nm"] == []
    assert kw.get("add_fundamental") is not True


@gui
def test_a_trace_whose_detection_never_ran_stays_automatic(a, fw):
    """(f) [] means a deliberate nothing, never 'no information yet'.

    A channel restored from a saved session with no defaults, no pin and no
    picks holds no answer, so it stays on the automatic path.
    """
    r = _rec("20 GPa", 20.0)
    _load(a, fw, [r])
    ch = fw._ch("Sample")
    ch["default_centers"] = []
    ch["user_centers"] = []
    ch["user_fundamental"] = None
    entry = fw._recipe_channel(ch, None, "Sample")
    assert entry["notch_centers_nm"] is None
    assert "add_fundamental" not in entry


@gui
def test_each_trace_is_cleaned_at_its_own_list(a, fw):
    """The one-snapshot-for-all-pressures behaviour is what died."""
    r20 = _rec("20 GPa", 20.0, stem="s_20p0")
    r30 = _rec("30 GPa", 30.0, stem="s_30p0")
    _load(a, fw, [r20, r30], label="20 GPa")
    fw._ch("Sample", "20 GPa")["user_centers"] = [NT_UM]
    fw._ch("Sample", "30 GPa")["user_centers"] = [NT_UM * 2.0]
    fw._commit("30 GPa")             # off screen: its committed copy answers
    kw20 = a._notch_kw("samp_c", r20)
    kw30 = a._notch_kw("samp_c", r30)
    assert kw20["notch_centers_nm"] == [NT_NM]
    assert kw30["notch_centers_nm"] == [NT_NM * 2.0]


@gui
def test_a_trace_off_screen_reads_its_committed_copy(a, fw):
    r20 = _rec("20 GPa", 20.0, stem="s_20p0")
    r30 = _rec("30 GPa", 30.0, stem="s_30p0")
    _load(a, fw, [r20, r30], label="20 GPa")
    fw._ch("Sample", "30 GPa")["user_centers"] = [NT_UM]
    fw._commit("30 GPa")
    fw._ch("Sample", "30 GPa")["user_centers"] = [NT_UM * 3.0]   # uncommitted
    rp = a._defringe_recipe(r30)
    assert rp["source"] == "committed"
    assert rp["channels"]["samp_c"]["notch_centers_nm"] == [NT_NM]


@gui
def test_a_restored_trace_asks_for_the_fundamental(a, fw):
    """State read back from a saved session holds the picks; the detector
    holds the fundamental they were picked beside."""
    r = _rec("20 GPa", 20.0, stem="s_20p0")
    r2 = _rec("30 GPa", 30.0, stem="s_30p0")
    _load(a, fw, [r, r2], label="30 GPa")
    dk = fw._dkey("20 GPa")
    fw._apply_trace_state(dk, {"chan": {"Sample": {
        "user_centers": [NT_UM * 2.0], "removed": [], "unticked": [],
        "user_fundamental": None, "widths": {}}}})
    fw._disk[dk] = fw._mem_state("20 GPa")
    kw = a._notch_kw("samp_c", r)
    assert kw["notch_centers_nm"] == [NT_NM * 2.0]
    assert kw["add_fundamental"] is True


@gui
def test_committed_default_centres_travel(a, fw):
    """Once the fundamental IS known for that trace, it travels with the
    picks and nothing has to be asked of the detector."""
    r = _rec("20 GPa", 20.0, stem="s_20p0")
    r2 = _rec("30 GPa", 30.0, stem="s_30p0")
    _load(a, fw, [r, r2], label="20 GPa")
    ch = fw._ch("Sample")
    ch["default_centers"] = [NT_UM]
    ch["user_centers"] = [NT_UM * 2.0]
    fw._commit("20 GPa")
    assert fw._disk[fw._dkey()]["chan"]["Sample"]["default_centers"] == [NT_UM]
    fw._label = "30 GPa"                      # step away
    fw._dk_cache = {}
    kw = a._notch_kw("samp_c", r)
    assert kw["notch_centers_nm"] == [NT_NM, NT_NM * 2.0]
    assert "add_fundamental" not in kw


@gui
def test_the_low_pass_travels_per_trace(a, fw):
    r = _rec("20 GPa", 20.0)
    _load(a, fw, [r])
    fw._ch("Sample")["default_centers"] = [NT_UM]
    fw.lp_on_v["Sample"].set(True)
    fw.lp_v["Sample"].set("15")
    try:
        kw = a._notch_kw("samp_c", r)
        assert kw["lowpass"] is True
        assert kw["lp_cutoff_um"] == pytest.approx(15.0)
    finally:
        fw.lp_on_v["Sample"].set(False)


@gui
def test_the_recipe_carries_the_detection_window(a, fw):
    """The wavelength window was never carried before: the cleaning ran
    under the old module's legacy band whatever the Detection card said."""
    r = _rec("20 GPa", 20.0)
    _load(a, fw, [r])
    fw._ch("Sample")["default_centers"] = [NT_UM]
    rp = a._defringe_recipe(r)
    assert rp["cfg"] is not None
    assert rp["cfg"].fit_wl_min_nm == pytest.approx(float(fw.wlmin_v.get()))
    assert a._notch_kw("samp_c", recipe=rp)["cfg"] is rp["cfg"]


@gui
def test_recipes_by_stem_cover_every_loaded_trace(a, fw):
    """(d) Every pressure is in the map, visited or not."""
    r20 = _rec("20 GPa", 20.0, stem="s_20p0")
    r30 = _rec("30 GPa", 30.0, stem="s_30p0")
    _load(a, fw, [r20, r30], label="20 GPa")
    fw._ch("Sample", "20 GPa")["user_centers"] = [NT_UM]
    recipes = a._defringe_recipes()
    assert set(recipes) >= {"s_20p0", "s_30p0"}
    assert recipes["s_30p0"]["source"] == "global"
    kw, bgk, sk = a._recipe_kwargs(recipes["s_20p0"])
    assert sk["notch_centers_nm"] == [NT_NM]
    assert set(kw) >= {"halfwidth_um", "nt_min_nm", "nt_max_nm", "pvalue_max"}


@gui
def test_the_worker_recipe_covers_a_stem_the_map_never_saw(a, fw):
    """A Run reduces spectra the main thread has never held."""
    r = _rec("20 GPa", 20.0, stem="s_20p0")
    _load(a, fw, [r])
    fresh = _rec("45 GPa", 45.0, stem="s_45p0")
    glob = fringe_panel.global_recipe(a.settings, fw)
    rp = a._worker_recipe({}, glob, dict(a.settings), None, fresh)
    assert rp["source"] == "global"
    assert rp["cfg"] is not None
    assert rp["channels"]["samp_c"]["notch_centers_nm"] is None


@gui
def test_recipe_provenance_is_json_types(a, fw):
    r = _rec("20 GPa", 20.0, stem="s_20p0")
    _load(a, fw, [r])
    fw._ch("Sample")["user_centers"] = [NT_UM]
    import json
    prov = a._recipe_provenance(a._defringe_recipes())
    json.dumps(prov)                          # a FringeConfig would raise
    assert prov["s_20p0"]["channels"]["samp_c"]["notch_centers_nm"] == [NT_NM]
    assert len(prov["s_20p0"]["wl_window_nm"]) == 2


@gui
def test_the_legacy_snapshot_key_is_dropped(a):
    """'Write to defringe' is retired and nothing reads its snapshot."""
    a.settings["fr_apply_centers"] = {"samp_c": {"notch_centers_nm": [NT_NM]}}
    try:
        a._migrate_apply_centers()
        assert "fr_apply_centers" not in a.settings
        assert getattr(a, "_df_legacy_centers", None) in (None, {})
    finally:
        a.settings.pop("fr_apply_centers", None)


# ===========================================================================
# 8. the master switch
# ===========================================================================
@gui
def test_df_off_leaves_the_main_plot_raw(a, fw):
    """(e) The main plot draws the record's own absorbance."""
    r = _rec("20 GPa", 20.0, stem="s_20p0")
    _ticked(a, [r], {"20 GPa"})
    keep = a.show_notch.get()
    try:
        a.show_notch.set(False)
        assert a._abs(r) is r["absorbance"]
        assert a._channel(r, "sample") is r["samp_c"]
        a.show_notch.set(True)
        assert a._abs(r) is not r["absorbance"]
    finally:
        a.show_notch.set(keep)
        a.notch_cache.clear()


@gui
def test_df_does_not_reach_the_workbench_filtered_curve(a, fw):
    """(e) R17 D2, the reversal.  The right column draws the cleaned curve
    whenever something is being filtered, as his window always does.

    df ships OFF, so gating on it meant a fresh install opened this
    workbench with no red curve at all -- next to his program, that reads as
    the low-pass doing nothing.  The switch still governs the main plot,
    which is what `_df_on` is for.
    """
    r = _rec("20 GPa", 20.0)
    _load(a, fw, [r])
    fw._ch("Sample")["default_centers"] = [NT_UM]
    keep = a.show_notch.get()
    try:
        a.show_notch.set(True)
        assert fw._df_on() is True
        assert fw._show_clean("Sample") is True
        a.show_notch.set(False)
        assert fw._df_on() is False           # still the main plot's switch
        assert fw._show_clean("Sample") is True
    finally:
        a.show_notch.set(keep)


@gui
def test_nothing_masked_means_no_filtered_curve(a, fw):
    """With every notch off and no low-pass there is nothing to draw."""
    r = _rec("20 GPa", 20.0)
    _load(a, fw, [r])
    ch = fw._ch("Sample")
    ch["default_centers"] = [NT_UM]
    ch["unticked"] = {NT_UM}
    keep = bool(fw.lp_on_v["Sample"].get())
    try:
        fw.lp_on_v["Sample"].set(False)
        assert fw._show_clean("Sample") is False
    finally:
        fw.lp_on_v["Sample"].set(keep)


@gui
def test_the_switch_repaints_the_workbench(a, fw):
    assert callable(getattr(fw, "on_defringe_switch", None))
    seen = []
    keep = a.show_notch.get()
    try:
        fw.on_defringe_switch = lambda: seen.append(True)
        a.show_notch.set(False)
        a._toggle_notch()
        assert seen == [True]
    finally:
        del fw.on_defringe_switch        # the class method answers again
        a.show_notch.set(keep)


@gui
def test_the_export_is_explicit_and_ignores_the_switch(a, fw, tmp_path):
    """The export cleans whatever df says, into the trace's OWN CSV.

    R20: no standalone {stem}_absorbance_notch.csv any more -- the columns
    join the absorbance file the reduction already writes.
    """
    import engine
    r = _rec("20 GPa", 20.0, stem="s_20p0")
    _load(a, fw, [r])
    keep = a.show_notch.get()
    try:
        a.show_notch.set(False)
        rp = a._defringe_recipe(r)
        kw, bgk, sk = a._recipe_kwargs(rp)
        cols = fringe_apply.notch_columns(r, bg_kw=bgk, s_kw=sk, **kw)
        assert cols["applied_s"] is True
        path = engine.write_absorbance_csv(
            r, str(tmp_path),
            extra=[(h, cols[h]) for h in ("Absorbance_notch",
                                          "Background_notch", "Sample_notch")])
        assert os.path.isfile(path)
        assert path.endswith("_absorbance.csv")
        assert not path.endswith("_absorbance_notch.csv")
    finally:
        a.show_notch.set(keep)


# ===========================================================================
# 9. the pass walks what is on screen, on the Run worker
# ===========================================================================
@gui
def test_the_report_walks_the_shown_traces_only(a, fw, monkeypatch):
    recs = [_rec("20 GPa", 20.0, stem="s_20p0"),
            _rec("30 GPa", 30.0, stem="s_30p0"),
            _rec("40 GPa", 40.0, stem="s_40p0")]
    _ticked(a, recs, {"30 GPa"})
    seen = []
    real = a._notch_result
    monkeypatch.setattr(a, "_notch_result",
                        lambda r: (seen.append(r["label"]), real(r))[1])
    a._defringe_report(quiet=True)
    assert seen == ["30 GPa"]


@gui
def test_the_pass_fills_only_what_is_shown(a, fw, monkeypatch):
    recs = [_rec("20 GPa", 20.0, stem="s_20p0"),
            _rec("30 GPa", 30.0, stem="s_30p0")]
    _ticked(a, recs, {"20 GPa"})
    monkeypatch.setattr(a, "_run_busy", lambda: True)   # inline branch
    done = []
    a._defringe_pass(then=lambda: done.append(True))
    assert done == [True]
    assert set(a.notch_cache) == {"20 GPa"}


@gui
def test_the_pass_runs_on_the_worker_and_hands_back(a, fw):
    """Off the drawing thread, with the Run's own progress machinery."""
    recs = [_rec("20 GPa", 20.0, stem="s_20p0")]
    _ticked(a, recs, {"20 GPa"})
    done = []
    a._defringe_pass(then=lambda: done.append(True))
    deadline = time.time() + 20.0
    while a._df_queue is not None and time.time() < deadline:
        a.root.update()
        time.sleep(0.01)
    assert a._df_queue is None
    assert done == [True]
    assert "20 GPa" in a.notch_cache
    assert a.run_btn.cget("text") == "Run"
    assert not a._run_busy()


@gui
def test_a_cancelled_pass_says_so_and_puts_the_switch_back(a, fw, monkeypatch):
    recs = [_rec("%d GPa" % p, float(p), stem="s_%d" % p)
            for p in (20, 30, 40, 50)]
    _ticked(a, recs, {r["label"] for r in recs})
    real = fringe_apply.clean_channel

    def slow(*args, **kw):                    # so Cancel lands mid-pass
        time.sleep(0.05)
        return real(*args, **kw)

    monkeypatch.setattr(fringe_apply, "clean_channel", slow)
    a.show_notch.set(True)
    try:
        a._toggle_notch()
        a._cancel_run()                       # the Escape / button path
        deadline = time.time() + 20.0
        while a._df_queue is not None and time.time() < deadline:
            a.root.update()
            time.sleep(0.01)
        assert a._df_queue is None
        assert a.show_notch.get() is False
    finally:
        a.show_notch.set(False)
        a.notch_cache.clear()


# ===========================================================================
# 10. invalidation
# ===========================================================================
@gui
def test_one_trace_s_edit_drops_one_cached_result(a, fw):
    recs = [_rec("20 GPa", 20.0, stem="s_20p0"),
            _rec("30 GPa", 30.0, stem="s_30p0")]
    _ticked(a, recs, {"20 GPa", "30 GPa"})
    for r in recs:
        a._notch_result(r)
    a._nt_cache["20 GPa"] = {"s": 1.0, "b": 1.0, "sp": 0.0, "bp": 0.0,
                             "err": None}
    a._notch_params_changed(gates=False, label="20 GPa")
    assert "20 GPa" not in a.notch_cache
    assert "30 GPa" in a.notch_cache
    assert "20 GPa" in a._nt_cache            # the gates held still
    a._notch_params_changed()
    assert a.notch_cache == {}
    assert a._nt_cache == {}


@gui
def test_a_notch_edit_reaches_the_host_for_that_trace(a, fw):
    """_invalidate is the workbench's own 'this changed' call."""
    seen = []
    r = _rec("20 GPa", 20.0)
    _load(a, fw, [r])
    try:
        a._notch_params_changed = (lambda gates=True, label=None:
                                   seen.append((gates, label)))
        fw._invalidate(now=False)
        assert seen == [(False, "20 GPa")]
    finally:
        del a._notch_params_changed          # the class method answers again
        if fw._after is not None:            # the debounced redraw it queued
            try:
                a.root.after_cancel(fw._after)
            except Exception:
                pass
            fw._after = None


@gui
def test_a_global_low_pass_change_drops_every_cached_result(a, fw):
    """A global control reaches every trace the panel holds nothing for, so
    the whole cache goes and the main plot is redrawn."""
    seen = []
    recs = [_rec("20 GPa", 20.0, stem="s_20p0"),
            _rec("30 GPa", 30.0, stem="s_30p0")]
    _ticked(a, recs, {"20 GPa", "30 GPa"})
    _load(a, fw, recs, label="20 GPa")
    for r in recs:
        a._notch_result(r)
    assert set(a.notch_cache) == {"20 GPa", "30 GPa"}
    try:
        a._notch_params_changed = (lambda gates=True, label=None:
                                   seen.append((gates, label)))
        fw._on_lp_toggle("Sample")
        assert seen == [(False, None)]
    finally:
        del a._notch_params_changed
        if fw._after is not None:
            try:
                a.root.after_cancel(fw._after)
            except Exception:
                pass
            fw._after = None
    a._notch_params_changed(gates=False, label=None)
    assert a.notch_cache == {}


@gui
def test_the_gates_reach_every_trace_and_the_thickness_read(a, fw):
    seen = []
    r = _rec("20 GPa", 20.0)
    _load(a, fw, [r])
    try:
        a._notch_params_changed = (lambda gates=True, label=None:
                                   seen.append((gates, label)))
        fw._on_detect_var()
        fw._on_hw_var()
        assert seen == [(True, None), (True, None)]
    finally:
        del a._notch_params_changed
        if fw._after is not None:
            try:
                a.root.after_cancel(fw._after)
            except Exception:
                pass
            fw._after = None
