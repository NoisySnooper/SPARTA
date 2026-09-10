"""The C/D name rule and the auto-rescan poll (v1.4.8, merged in R20).

Two features that must not drift:

* The C/D tag row of EXPORT > DATA FILES puts the branch letter into the
  name of the SAME per-point absorbance CSV a Run writes. The naming rule
  and the byte-for-byte identity with engine's own writer are the contract,
  and the export sidecar is a frozen provenance schema. Before R20 these
  were second copies in a cd_tagged subfolder; the rule they carry is the
  same one.
* Auto rescan owns exactly ONE root.after timer, cancels cleanly, and its
  two controls persist in SETTINGS (workflow state, not figure state).

Runs against the suite's ONE shared App (tests/conftest.py).
"""
import json
import os

import pytest

import app
import engine
from conftest import ROOT, gui, make_result, offscreen, open_dialog, \
    shared_app

USES_APP = True
pytestmark = gui


@pytest.fixture(scope="module")
def a():
    return shared_app()


def _res(dac, sample, pstr, pval, tag=None):
    return make_result("%s %s %.2f GPa" % (dac, sample, pval), pval, n=12,
                       dac=dac, sample=sample, pstr=pstr, tag=tag)


def _trio():
    """Three points, one of them tagged D in its file name."""
    return [_res("Y04", "Arch29", "12p5", 12.5),
            _res("Y04", "Arch29", "18p0", 18.0),
            _res("Y04", "Arch29", "9p0", 9.0, "D")]


def _load(a, results):
    a._finish_run([dict(r) for r in results], [], "dest")


# ------------------------------------------------------- the C/D name rule --
def test_tagged_csv_naming_rule(a, tmp_path):
    """{DAC}_{sample}_{value}_{C|D}_absorbance.csv -- the branch letter goes
    exactly where Run already puts a file-name branch tag; anything not
    explicitly marked D is compression (including a point whose FILE NAME
    said D but whose D box the user cleared); and two points that would land
    on one name keep both files."""
    res = _trio()
    _load(a, res)
    for r in a.results:
        a.dvars[r["label"]].set(r["pressure_str"] == "9p0")
    written = a._write_final_csvs(a.results, str(tmp_path), columns=[],
                                  cd_names=True)["paths"]
    assert sorted(os.path.basename(p) for p in written) == [
        "Y04_Arch29_12p5_C_absorbance.csv",
        "Y04_Arch29_18p0_C_absorbance.csv",
        "Y04_Arch29_9p0_D_absorbance.csv"]
    assert all(os.path.isfile(p) for p in written)

    # the D box cleared on a point whose raw name said D: compression
    plain = tmp_path / "plain"
    for r in a.results:
        a.dvars[r["label"]].set(False)
    written = a._write_final_csvs(a.results, str(plain), columns=[],
                                  cd_names=True)["paths"]
    assert sorted(os.path.basename(p) for p in written) == [
        "Y04_Arch29_12p5_C_absorbance.csv",
        "Y04_Arch29_18p0_C_absorbance.csv",
        "Y04_Arch29_9p0_C_absorbance.csv"]

    coll = tmp_path / "collide"
    x = _res("Y04", "Arch29", "12p5", 12.5)
    y = _res("Y04", "Arch29", "12p5", 12.5, "D")
    y["label"] = x["label"] + " [D]"          # distinct identity, same stem
    written = a._write_final_csvs([x, y], str(coll), columns=[],
                                  cd_names=True)["paths"]
    assert [os.path.basename(p) for p in written] == [
        "Y04_Arch29_12p5_C_absorbance.csv",
        "Y04_Arch29_12p5-2_C_absorbance.csv"]
    assert len([f for f in os.listdir(str(coll))
                if f.endswith(".csv")]) == 2


def test_tagged_csv_content_matches_untagged_writer(a, tmp_path):
    """Only the name changes: with no columns ticked the bytes are the ones
    engine's own writer produces."""
    res = _trio()
    _load(a, res)
    for r in a.results:
        a.dvars[r["label"]].set(r["pressure_str"] == "9p0")
    tagged = tmp_path / "tagged"
    plain = tmp_path / "plain"
    plain.mkdir()
    written = a._write_final_csvs(a.results, str(tagged), columns=[],
                                  cd_names=True)["paths"]
    for r, p in zip(a.results, written):
        ref = engine.write_absorbance_csv(dict(r, branch_tag=None),
                                          str(plain))
        assert open(ref, "rb").read() == open(p, "rb").read()


def test_the_export_dialog_writes_one_folder_and_one_sidecar(a, tmp_path):
    """End to end through EXPORT > DATA FILES: the branch is what the plot
    uses (auto-detected D plus the manual toggles), every point has exactly
    ONE file, and ONE sidecar covers the whole write."""
    _load(a, _trio())
    for r in a.results:                       # deterministic branch state
        a.dvars[r["label"]].set(r["pressure_str"] == "18p0")
    a.export_products["defringed"].set(False)
    a.export_products["cd_tagged"].set(True)
    with offscreen(a):
        win = open_dialog(a._open_export_dialog)
        try:
            a._export_dest.set(str(tmp_path))
            a._export_dialog_write()
        finally:
            win.grab_release()
            win.destroy()
    assert sorted(os.listdir(str(tmp_path))) == [
        "Y04_Arch29_12p5_C_absorbance.csv",
        "Y04_Arch29_18p0_D_absorbance.csv",
        "Y04_Arch29_9p0_C_absorbance.csv",
        "_export.provenance.json"]
    with open(os.path.join(str(tmp_path), "_export.provenance.json")) as f:
        prov = json.load(f)
    assert prov["kind"] == "data_files"
    assert prov["variable_name"] == "Pressure"
    assert prov["variable_unit"] == "GPa"
    assert prov["params"]["n"] == 3
    assert prov["params"]["columns"] == []
    assert prov["params"]["cd_names"] is True
    assert len(prov["files"]) == 3


def test_no_data_opens_the_dialog_but_writes_nothing(a):
    """Matches the other data-dependent exports: a note, not a dialog. The
    window still opens so it can say why it will not write."""
    a.results = []
    with offscreen(a):
        win = open_dialog(a._open_export_dialog)
        try:
            assert str(a._export_go_btn.cget("state")) == "disabled"
            assert a._export_note.cget("text") == app.EXPORT_NO_DATA_NOTE
            assert a._export_dialog_write() is None
        finally:
            win.grab_release()
            win.destroy()


# ------------------------------------------------------- auto rescan -------
def test_rescan_settings_roundtrip(a, fresh_app):
    """auto_rescan / rescan_interval live in SETTINGS (like the folders),
    not in the figure-preset registry, and survive a fresh launch."""
    reg = a._preset_registry()
    assert "auto_rescan" not in reg and "rescan_interval" not in reg
    a.auto_rescan.set(True)
    a.rescan_interval.set(45)
    a._persist_rescan()
    with open(app.SETTINGS_PATH) as f:
        data = json.load(f)
    assert data["auto_rescan"] is True
    assert data["rescan_interval"] == 45

    new = fresh_app()                      # a new launch reads it back
    try:
        assert new.auto_rescan.get() is True
        assert new.rescan_interval.get() == 45
        assert new._auto_rescan_job is not None   # armed on startup
    finally:
        new._cancel_auto_rescan()
    a._cancel_auto_rescan()


def test_one_timer_only_clamped_and_reachable(a):
    """The interval is clamped to 5 s .. 1 h, exactly one after-job exists at
    any moment, and both the keyboard routes into a rescan are wired."""
    a.rescan_interval.set(1)
    assert a._auto_rescan_secs() == 5
    a.rescan_interval.set(99999)
    assert a._auto_rescan_secs() == 3600
    a.rescan_interval.set(30)
    assert a._auto_rescan_secs() == 30

    def jobs():
        return set(ROOT.tk.call("after", "info"))

    assert a._auto_rescan_job is None
    a.auto_rescan.set(True)
    a._toggle_auto_rescan()
    first = a._auto_rescan_job
    assert first is not None and first in jobs()
    a.rescan_interval.set(11)               # reschedules cleanly
    second = a._auto_rescan_job
    assert second is not None and second != first
    assert first not in jobs() and second in jobs()
    a._schedule_auto_rescan()               # never stacks a second job
    third = a._auto_rescan_job
    assert second not in jobs() and third in jobs()
    a.auto_rescan.set(False)
    a._toggle_auto_rescan()
    assert a._auto_rescan_job is None
    assert third not in jobs()

    assert ROOT.bind("<F5>")
    assert a._in_entry.bind("<Return>")
    assert "F5" in app.SHORTCUTS_TEXT
    assert "Enter (input)" in app.SHORTCUTS_TEXT


def test_tick_waits_for_the_first_run_and_never_fires_mid_run(a, tmp_path,
                                                              monkeypatch):
    calls = []
    monkeypatch.setattr(a, "_rescan", lambda auto=False: calls.append(auto))
    a.auto_rescan.set(True)
    a.in_var.set(str(tmp_path))

    a._last_scan = None                     # no Run has completed yet
    a._auto_rescan_tick()
    a._cancel_auto_rescan()
    assert calls == []

    a._last_scan = (str(tmp_path), set())   # ... now one has
    a._auto_rescan_tick()
    a._cancel_auto_rescan()
    assert calls == [True]                  # and it takes the silent path

    monkeypatch.setattr(a, "_run_busy", lambda: True)
    a._auto_rescan_tick()                   # a Run is in flight: skip
    a._cancel_auto_rescan()
    assert calls == [True]


# ------------------------------------------- Inspect combobox identity -----
def test_inspect_selection_survives_a_variable_change(a):
    """The combobox DISPLAYS the active Variable's unit; the selection still
    resolves to the same engine record."""
    _load(a, _trio())
    vals = list(a.inspect_combo.cget("values"))
    assert vals == [r["label"] for r in a.results]      # GPa: byte-identical
    a.inspect_p.set(vals[1])
    assert a._inspect_record() is a.results[1]
    a.xvar_choice.set("Temperature (K)")
    assert all(v.endswith(" K") for v in a.inspect_combo.cget("values"))
    assert a._inspect_record() is a.results[1]
    a._menu_inspect(a.results[2]["label"])             # right-click Inspect
    assert a._inspect_record() is a.results[2]
    a.xvar_choice.set("Pressure (GPa)")
    assert a._inspect_record() is a.results[2]
