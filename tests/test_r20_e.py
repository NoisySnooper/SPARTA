"""R20 wave E-app: one CSV per trace, and one window that writes it.

R19 put every data file behind one ticked list. R20 merges the files
themselves: a ticked row is a COLUMN in the trace's own absorbance CSV, or
(for C/D) a rule about that file's name, so a folder holds one file per
measurement instead of three spellings of it. The same five ticks drive the
end of a Run and the new Export dialog.

One test per ruling:

  * the five rows, their labels and the muted always-on Absorbance row;
  * the crop widgets left the section and live in the dialog;
  * the dialog opens from the section button, the left-panel Export...
    button and Ctrl+E, and is the modal trio (transient, grab, Escape);
  * with no traces it still opens, says so in the warning role, and cannot
    export;
  * _write_final_csvs' header order for every tick combination, and the
    crop;
  * the C/D name rule, including the untagged twin that has to go;
  * the dialog writes, leaves ONE _export.provenance.json, and reports in
    both status lines;
  * a Run rewrites its CSVs with the ticked columns, logs one line and
    merges "columns" into the reduction sidecar; nothing ticked, no
    rewrite;
  * status labels hold no row while they have nothing to say;
  * the saved section order learns Data files;
  * My notes is the first-launch Guide view.

Runs against the suite's ONE shared App (tests/conftest.py).
"""
import json
import os

import numpy as np
import pytest

import app
from conftest import (gui, make_result, offscreen, open_dialog,
                      realized, shared_app)

USES_APP = True
pytestmark = gui


@pytest.fixture(scope="module")
def a():
    return shared_app()


# --------------------------------------------------------------- helpers ---
def _fringed(nt_um=30.0, amp=0.06, n=600, lo=500.0, hi=900.0):
    """Counts with one clean interference fringe, as fringe_apply expects."""
    wl = np.linspace(lo, hi, n)
    base = 1000.0 * (1.0 + 0.30 * (wl - lo) / (hi - lo))
    return wl, base * (1.0 + amp * np.cos(4.0 * np.pi * nt_um * 1000.0 / wl))


def _rec(pstr, pval, tag=None, dac="Y04", sample="Arch29"):
    wl, samp = _fringed()
    _wl, bg = _fringed(36.0)
    return make_result("%s %s %.2f GPa" % (dac, sample, pval), pval, wl=wl,
                       samp=samp, bg=bg, dark=np.ones(wl.size), dac=dac,
                       sample=sample, pstr=pstr, tag=tag)


def _trio():
    return [_rec("12p5", 12.5), _rec("18p0", 18.0), _rec("9p0", 9.0)]


def _load(a, results):
    a._finish_run([dict(r) for r in results], [], "dest")


def _tick(a, **kw):
    """Set the product ticks by name; everything unnamed goes off."""
    for k in app.EXPORT_PRODUCT_DEFAULTS:
        a.export_products[k].set(bool(kw.get(k, False)))


def _section(a, title):
    return [r for r in a._collapsibles if r["key"] == title][0]


def _walk(parent):
    for c in parent.winfo_children():
        yield c
        for g in _walk(c):
            yield g


def _labels(parent, cls):
    out = []
    for w in _walk(parent):
        if w.winfo_class() == cls:
            try:
                out.append(w.cget("text"))
            except Exception:
                pass
    return out


def _head(path):
    with open(path, encoding="utf-8") as f:
        return f.readline().rstrip("\r\n").split(",")


def _rows(path):
    with open(path, encoding="utf-8") as f:
        return [ln.rstrip("\r\n").split(",") for ln in f if ln.strip()]


BASE = ["Wavelength_nm", "Wavenumber_cm-1", "Absorbance", "Dark",
        "Background", "Sample"]


# ------------------------------------------------------------ the section ---
def test_the_five_rows_say_columns_not_files(a):
    """EXPORT > DATA FILES asks what goes INTO each CSV. Absorbance states a
    fact (ticked, disabled) and takes the MUTED role rather than ttk's stock
    disabled grey, which disappears on the dark accent themes."""
    body = _section(a, "Data files")["body"]
    assert "Include in each trace's CSV:" in _labels(body, "Label")
    assert _labels(body, "TCheckbutton") == [
        app.EXPORT_ROW_LABELS[k] for k in app.EXPORT_ROW_ORDER]
    assert _labels(body, "TCheckbutton") == [
        "Absorbance data (always)", "Defringed data", "Smoothed data",
        "Formula values", "C/D tag in file name"]
    abs_row = a._product_checks["absorbance"]
    assert str(abs_row.cget("state")) == "disabled"
    assert str(abs_row.cget("style")) == "Muted.TCheckbutton"
    assert a._abs_always.get() is True
    assert str(a._product_checks["defringed"].cget("state")) != "disabled"
    # every row carries its tooltip, and none of them names a file any more
    for k in app.EXPORT_ROW_ORDER:
        tip = app.EXPORT_ROW_TIPS[k]
        assert tip and "_absorbance_notch.csv" not in tip
        assert "cd_tagged" not in tip
    assert a._export_data_btn.cget("text") == "Export data" + chr(0x2026)
    assert a._export_data_btn.cget("command")


def test_the_crop_widgets_left_the_section_for_the_dialog(a):
    """Crop is export-only, so the section holds no entry at all; the
    variables stay on the App, where _crop_nm can read them."""
    body = _section(a, "Data files")["body"]
    assert [w for w in _walk(body) if w.winfo_class() == "TEntry"] == []
    assert "Crop" not in _labels(body, "TCheckbutton")
    assert "nm" not in _labels(body, "Label")
    for v in (a.crop_on, a.crop_min, a.crop_max):
        assert v is not None
    assert a._crop_nm() == (False, None, None)


# ------------------------------------------------------------- the dialog ---
def test_the_dialog_opens_from_all_three_places(a):
    """One window behind the section button, the left-panel Export... button
    and Ctrl+E, built to the house modal trio."""
    _load(a, _trio())
    assert a.root.bind("<Control-e>")
    with offscreen(a):
        for opener in (a._export_data_btn.invoke, a._export_btn.invoke,
                       a._open_export_dialog):
            win = open_dialog(opener)
            try:
                assert win.title() == "Export data"
                assert win.bind("<Escape>")
                assert win.wm_transient()
                assert [w.cget("text")
                        for w in _walk(win)
                        if w.winfo_class() == "TCheckbutton"] == [
                    app.EXPORT_ROW_LABELS[k]
                    for k in app.EXPORT_ROW_ORDER] + ["Crop"]
                # the SAME variables, so a tick here is a tick there
                a.export_products["smoothed"].set(True)
                assert "selected" in a._export_checks["smoothed"].state()
                a.export_products["smoothed"].set(False)
                assert str(a._export_checks["absorbance"].cget("state")) \
                    == "disabled"
                assert sorted(w.cget("text") for w in _walk(win)
                              if w.winfo_class() == "TButton") == [
                    "Browse", "Close", "Open folder"]
                assert a._export_go_btn.cget("text") == "Export"
                assert a._export_note.cget("text") == app.EXPORT_SYNC_NOTE
                assert a._export_status.winfo_manager() == ""
            finally:
                win.grab_release()
                win.destroy()
        assert a._export_btn.cget("text") == "Export" + chr(0x2026)
    # the row still reads [Run .....][Export...][Open output], and Run is
    # the one stretchy child, packed LAST so a button is never the widget
    # that gets clipped (rule 13)
    brow = a._export_btn.master
    assert list(brow.pack_slaves()) == [a._openout_btn, a._export_btn,
                                        a.run_btn]
    assert a._openout_btn.pack_info()["side"] == "right"
    assert a._export_btn.pack_info()["side"] == "right"
    assert a.run_btn.pack_info()["side"] == "left"
    assert int(a.run_btn.pack_info()["expand"])


def test_the_dialog_with_no_traces_says_so_and_will_not_write(a):
    """It still opens: the note reads in the warning role and Export is
    disabled, so the window explains itself instead of refusing to appear."""
    a.results = []
    with offscreen(a):
        win = open_dialog(a._open_export_dialog)
        try:
            assert a._export_note.cget("text") == app.EXPORT_NO_DATA_NOTE
            assert a._export_note.cget("fg") == a._semantic_fg(app.SEM_WARN)
            assert str(a._export_go_btn.cget("state")) == "disabled"
            assert a._export_dialog_write() is None
            assert a._export_status.cget("text") == app.EXPORT_NO_DATA_NOTE
        finally:
            win.grab_release()
            win.destroy()


def test_the_dialog_ends_under_its_own_last_row(a):
    """R20 H1 (Nhan): the window was built at _dialog_size(78, 66) and kept
    a further seven em back for a status line that was not packed yet, so
    about 90 px of empty ground sat between the note and the button bar.

    The WIDTH is still the idiom's (the Destination entry is what
    stretches). The HEIGHT is the content's, in the ready state and in the
    no-data one, and it follows the status line up and back down again."""
    def geom_h(win):
        return int(win.geometry().split("+")[0].split("x")[1])

    def band(a):
        """The empty ground between the last packed row of the body and the
        top of the button bar."""
        main = a._export_note.master
        bar = a._export_close_btn.master
        rows = [w for w in main.pack_slaves() if w.winfo_manager()]
        last = rows[-1]
        return bar.winfo_y() - (main.winfo_y() + last.winfo_y()
                                + last.winfo_height())

    def settle(a, n=3):
        for _ in range(n):
            a.root.update_idletasks()
            a.root.update()

    # main's own bottom padding (12, 10) plus one group gap: anything more
    # under the last row is the band this test exists to keep out
    ROOM = sum(app.PAD_GROUP) + 12
    _load(a, _trio())
    with realized(), offscreen(a):
        win = open_dialog(a._open_export_dialog)
        try:
            settle(a)
            assert tuple(win.resizable()) == (1, 0)
            h0 = geom_h(win)
            assert abs(h0 - win.winfo_reqheight()) <= 4, (
                "window %d px for %d px of content"
                % (h0, win.winfo_reqheight()))
            assert a._export_status.winfo_manager() == ""
            assert band(a) <= ROOM, "%d px of nothing over the bar" % band(a)

            # the status line appears: the window grows to hold it
            a._export_say("3 traces -> 3 CSV(s) with Absorbance_notch, "
                          "Background_notch, Sample_notch -> a folder",
                          app.STATE)
            settle(a)
            assert a._export_status.winfo_manager() == "pack"
            h1 = geom_h(win)
            assert h1 > h0, "the status line did not grow the window"
            assert abs(h1 - win.winfo_reqheight()) <= 4
            assert band(a) <= ROOM, "%d px of nothing over the bar" % band(a)
            assert (a._export_status.winfo_y()
                    + a._export_status.winfo_height()
                    <= a._export_note.master.winfo_height())
            # the line wraps rather than running off the edge, and the
            # window is tall enough for every row it wrapped to
            assert (a._export_status.winfo_reqheight()
                    <= a._export_status.winfo_height() + 1)

            # and hands the room back when it goes
            a._export_say("")
            settle(a)
            assert a._export_status.winfo_manager() == ""
            assert abs(geom_h(win) - h0) <= 4
        finally:
            win.grab_release()
            win.destroy()

    # the no-data note is the other height the window has to fit
    a.results = []
    with realized(), offscreen(a):
        win = open_dialog(a._open_export_dialog)
        try:
            settle(a)
            assert a._export_note.cget("text") == app.EXPORT_NO_DATA_NOTE
            assert abs(geom_h(win) - win.winfo_reqheight()) <= 4
            assert band(a) <= ROOM, "%d px of nothing over the bar" % band(a)
        finally:
            win.grab_release()
            win.destroy()


# ------------------------------------------------------------- the writer ---
def test_write_final_csvs_header_order_for_every_tick_combination(
        a, tmp_path):
    """Base six first, always in that order, then the extras in the frozen
    order: the three notch columns, the smoothed ones, the formula."""
    _load(a, _trio())
    a._qty_sel.set("")
    cases = [
        ([], BASE),
        (["defringed"], BASE + list(app.NOTCH_COLUMNS)),
        (["smoothed"], BASE + ["Absorbance_smoothed"]),
        (["defringed", "smoothed"],
         BASE + list(app.NOTCH_COLUMNS) + ["Absorbance_smoothed",
                                           "Absorbance_notch_smoothed"]),
    ]
    for i, (cols, want) in enumerate(cases):
        d = tmp_path / ("case%d" % i)
        res = a._write_final_csvs(a.results, str(d), columns=cols)
        assert len(res["paths"]) == 3, cols
        assert res["columns"] == want[len(BASE):], cols
        for p in res["paths"]:
            assert _head(p) == want, (cols, p)
        assert sorted(os.listdir(str(d))) == [
            "Y04_Arch29_12p5_absorbance.csv",
            "Y04_Arch29_18p0_absorbance.csv",
            "Y04_Arch29_9p0_absorbance.csv"], cols
    # a ticked Formula with nothing picked is not an error: no column, one
    # log line, and the file is still written
    d = tmp_path / "noformula"
    res = a._write_final_csvs(a.results, str(d), columns=["formula"])
    assert res["columns"] == []
    assert "no formula is picked" in a.log.get("1.0", "end")
    assert _head(res["paths"][0]) == BASE
    # the ticks are the default source
    _tick(a, defringed=True)
    assert a._column_ticks() == ["defringed"]
    _tick(a, smoothed=True, formula=True)
    assert a._column_ticks() == ["smoothed", "formula"]


def test_a_formula_header_that_is_already_taken_is_renamed(a, tmp_path):
    """R20 H2 (Nhan): the built-in Absorbance formula's CSV key is exactly
    "Absorbance", which is also one of engine's six frozen base columns, so
    a file written with Formula values ticked carried that name twice and
    engine.load_processed_folder -- which finds its columns BY NAME -- kept
    the later one. The formula column is written as Absorbance_formula
    instead, the rename is logged once, and the sidecar records the name
    that actually went into the file."""
    _load(a, _trio())
    q = next(x for x in a.quantities
             if x.get("builtin") and x["name"] == "Absorbance")
    assert a._formula_header(q) == "Absorbance"        # the clash itself
    assert "Absorbance" in app.engine.ABSORBANCE_BASE_COLUMNS
    a._qty_sel.set(q["key"])
    a.log.delete("1.0", "end")
    d = tmp_path / "clash"
    res = a._write_final_csvs(a.results, str(d), columns=["formula"])
    head = _head(res["paths"][0])
    assert head == BASE + ["Absorbance_formula"]
    assert head.count("Absorbance") == 1
    assert head.count("Absorbance_formula") == 1
    txt = a.log.get("1.0", "end")
    assert ("Formula column 'Absorbance' renamed Absorbance_formula: "
            "the name was taken by a base column.") in txt
    assert txt.count("renamed Absorbance_formula") == 1   # once, not per file
    assert res["columns"] == ["Absorbance_formula"]
    assert res["params"]["columns"] == ["Absorbance_formula"]
    assert res["params"]["column_params"]["formula"]["header"] \
        == "Absorbance_formula"
    # the six base columns survive the round trip, which is the whole point
    back = app.engine.load_processed_folder(str(d))
    assert len(back) == 3
    # a formula whose name is free is written exactly as it is
    q2 = next(x for x in a.quantities if x["name"] == "Transmittance")
    a._qty_sel.set(q2["key"])
    d2 = tmp_path / "free"
    res2 = a._write_final_csvs(a.results, str(d2), columns=["formula"])
    assert _head(res2["paths"][0]) == BASE + ["Transmittance"]
    assert res2["params"]["column_params"]["formula"]["header"] \
        == "Transmittance"
    # the rule looks at the extras too, not only the base six
    assert a._formula_csv_header({"key": "Absorbance_notch", "unit": ""},
                                 ["defringed"]) == \
        "Absorbance_notch_formula"
    assert a._formula_csv_header({"key": "Absorbance_notch", "unit": ""},
                                 []) == "Absorbance_notch"
    a._qty_sel.set("")


def test_the_crop_trims_every_column_and_only_the_export(a, tmp_path):
    """Crop keeps the rows inside the range in EVERY column, and it is not
    remembered anywhere a Run would read it."""
    _load(a, _trio())
    res = a._write_final_csvs(a.results, str(tmp_path),
                              columns=["defringed"], crop_nm=(600.0, 700.0))
    rows = _rows(res["paths"][0])
    assert rows[0] == BASE + list(app.NOTCH_COLUMNS)
    wl = [float(r[0]) for r in rows[1:]]
    assert wl and 600.0 <= min(wl) and max(wl) <= 700.0
    assert len(wl) < 600
    assert all(len(r) == len(rows[0]) for r in rows)
    assert res["params"]["crop"] == [600.0, 700.0]
    # the edges are read the right way round whichever way they are typed
    flip = a._write_final_csvs(a.results, str(tmp_path / "flip"),
                               crop_nm=(700.0, 600.0))
    assert flip["params"]["crop"] == [600.0, 700.0]
    # nothing about a crop is remembered, and a Run never asks for one
    assert "crop" not in app.EXPORT_PRODUCT_DEFAULTS
    assert "crop" not in a.settings
    a._write_run_csvs(a.results, str(tmp_path / "run"))
    assert len(_rows(str(tmp_path / "run" / os.listdir(
        str(tmp_path / "run"))[0]))) == 601


def test_the_cd_rule_names_every_file_and_removes_the_untagged_twin(
        a, tmp_path):
    """The tick forces the letter on every name; a file rewritten under a
    new name takes its untagged twin with it, so the folder holds ONE file
    per point and Load previous run cannot read a measurement twice."""
    _load(a, _trio())
    for r in a.results:                       # deterministic branch state
        a.dvars[r["label"]].set(r["pressure_str"] == "18p0")
    plain = a._write_final_csvs(a.results, str(tmp_path), columns=[],
                                cd_names=False)
    assert sorted(os.path.basename(p) for p in plain["paths"]) == [
        "Y04_Arch29_12p5_absorbance.csv",
        "Y04_Arch29_18p0_absorbance.csv",
        "Y04_Arch29_9p0_absorbance.csv"]
    tagged = a._write_final_csvs(a.results, str(tmp_path), columns=[],
                                 cd_names=True)
    assert sorted(os.path.basename(p) for p in tagged["paths"]) == [
        "Y04_Arch29_12p5_C_absorbance.csv",
        "Y04_Arch29_18p0_D_absorbance.csv",
        "Y04_Arch29_9p0_C_absorbance.csv"]
    assert sorted(os.listdir(str(tmp_path))) == [
        "Y04_Arch29_12p5_C_absorbance.csv",
        "Y04_Arch29_18p0_D_absorbance.csv",
        "Y04_Arch29_9p0_C_absorbance.csv"]
    assert tagged["params"]["cd_names"] is True
    # the name rule itself, and the letter a record already carried.
    # _finish_run sorts the traces by pressure, so the record is picked by
    # its own pressure string rather than by a position in the list.
    rec = dict([r for r in a.results if r["pressure_str"] == "12p5"][0])
    assert app.App._abs_csv_name(rec) == "Y04_Arch29_12p5_absorbance.csv"
    assert app.App._abs_csv_name(rec, "D") == \
        "Y04_Arch29_12p5_D_absorbance.csv"
    assert app.App._abs_csv_name(dict(rec, branch_tag="C")) == \
        "Y04_Arch29_12p5_C_absorbance.csv"
    # two points that would land on ONE name keep both files
    coll = tmp_path / "collide"
    x, y = _rec("12p5", 12.5), _rec("12p5", 12.5)
    y["label"] = x["label"] + " [2]"
    res = a._write_final_csvs([x, y], str(coll), columns=[], cd_names=True)
    assert [os.path.basename(p) for p in res["paths"]] == [
        "Y04_Arch29_12p5_C_absorbance.csv",
        "Y04_Arch29_12p5-2_C_absorbance.csv"]


def test_the_dialog_writes_one_folder_and_one_sidecar(a, tmp_path):
    """End to end through the Export button: the ticked columns, one
    _export.provenance.json whose params name the columns, and the same
    line in the dialog and in the section."""
    _load(a, _trio())
    _tick(a, defringed=True)
    with offscreen(a):
        win = open_dialog(a._open_export_dialog)
        try:
            a._export_dest.set(str(tmp_path))
            res = a._export_dialog_write()
        finally:
            win.grab_release()
            win.destroy()
    assert len(res["paths"]) == 3
    names = sorted(os.listdir(str(tmp_path)))
    assert names == ["Y04_Arch29_12p5_absorbance.csv",
                     "Y04_Arch29_18p0_absorbance.csv",
                     "Y04_Arch29_9p0_absorbance.csv",
                     "_export.provenance.json"]
    assert _head(res["paths"][0]) == BASE + list(app.NOTCH_COLUMNS)
    with open(os.path.join(str(tmp_path), "_export.provenance.json")) as f:
        prov = json.load(f)
    assert prov["kind"] == "data_files"
    assert prov["params"]["columns"] == list(app.NOTCH_COLUMNS)
    assert prov["params"]["n"] == 3
    assert prov["params"]["crop"] is None
    assert prov["params"]["cd_names"] is False
    assert "notch_params" in prov["params"]["column_params"]["defringed"]
    assert len(prov["files"]) == 3
    line = a._data_status.cget("text")
    assert line.startswith("3 traces -> 3 CSV(s) with Absorbance_notch")
    assert line.endswith(os.path.basename(str(tmp_path)))
    assert a._data_status.winfo_manager() == "pack"
    txt = a.log.get("1.0", "end")
    assert "Exported 3 CSV(s) from 3 trace(s) with Absorbance_notch" in txt


# ---------------------------------------------------------------- the Run ---
def test_a_run_rewrites_its_csvs_with_the_ticked_columns(a, tmp_path):
    """The end of a Run adds the ticked columns to the files engine.run
    wrote, logs ONE line and merges "columns" into the reduction sidecar.
    Nothing ticked beyond Absorbance: no rewrite, and the log says the plain
    thing. Viewer mode and a cancelled run write nothing at all."""
    dest = tmp_path / "out"
    dest.mkdir()
    with open(str(dest / "_reduction.provenance.json"), "w",
              encoding="utf-8") as f:
        json.dump({"kind": "reduction", "n_curves": 3}, f)
    a.show_notch.set(False)                    # the df switch is DOWN
    _tick(a, defringed=True)
    assert a._notch_on() is False
    assert a._products()["defringed"] is True  # the gate disagrees with df

    # not told a reduction happened: nothing is written
    a._finish_run([dict(r) for r in _trio()], [], str(dest))
    assert sorted(os.listdir(str(dest))) == ["_reduction.provenance.json"]

    a._finish_run([dict(r) for r in _trio()], [], str(dest),
                  wrote_reduction=True, n_defringed=3)
    names = sorted(os.listdir(str(dest)))
    assert len([n for n in names if n.endswith("_absorbance.csv")]) == 3
    assert not [n for n in names if n.endswith("_absorbance_notch.csv")]
    assert "cd_tagged" not in names
    head = _head(os.path.join(str(dest), names[0]))
    assert head == BASE + list(app.NOTCH_COLUMNS)
    txt = a.log.get("1.0", "end")
    assert ("Run wrote 3 CSV(s) with Absorbance_notch, Background_notch, "
            "Sample_notch -> ") in txt
    assert "Export > Data files picks the columns." in txt
    with open(str(dest / "_reduction.provenance.json")) as f:
        prov = json.load(f)
    assert prov["kind"] == "reduction"         # merged, not replaced
    assert prov["columns"] == list(app.NOTCH_COLUMNS)
    assert "n_own" in prov["column_params"]["defringed"]
    assert "notch_params" in prov["column_params"]["defringed"]

    # nothing ticked: engine's files are left exactly as they are
    plain = tmp_path / "plain"
    plain.mkdir()
    _tick(a)
    a.log.delete("1.0", "end")
    a._finish_run([dict(r) for r in _trio()], [], str(plain),
                  wrote_reduction=True)
    assert os.listdir(str(plain)) == []
    assert "Run wrote 3 CSV(s) -> " in a.log.get("1.0", "end")

    # cancelled, and viewer mode
    _tick(a, defringed=True)
    a._finish_run([dict(r) for r in _trio()], [], str(plain),
                  wrote_reduction=True, cancelled=True)
    assert os.listdir(str(plain)) == []
    assert "Run cancelled: no data files were written." in \
        a.log.get("1.0", "end")
    a._finish_run([dict(r) for r in _trio()], [], str(plain),
                  wrote_reduction=False)
    assert "Viewer mode: nothing written." in a.log.get("1.0", "end")


def test_the_run_reuses_the_columns_its_worker_already_computed(a, tmp_path):
    """The worker cleans off the main thread and hangs the arrays on the
    record; _write_final_csvs takes them rather than cleaning again."""
    dest = str(tmp_path)
    recs = [dict(r) for r in _trio()]
    n = recs[0]["wl"].size
    for r in recs:
        r["notch_cols"] = {"Absorbance_notch": np.full(n, 0.25),
                           "Background_notch": np.full(n, np.nan),
                           "Sample_notch": np.full(n, 7.0)}
        r["notch_recipe"] = {"source": "workbench", "channels": {}}
    _tick(a, defringed=True)
    a._finish_run(recs, [], dest, wrote_reduction=True, n_defringed=3)
    p = [os.path.join(dest, f) for f in sorted(os.listdir(dest))
         if f.endswith("_absorbance.csv")][0]
    rows = _rows(p)
    head = rows[0]
    i_a = head.index("Absorbance_notch")
    i_b = head.index("Background_notch")
    i_s = head.index("Sample_notch")
    assert [r[i_a] for r in rows[1:4]] == ["0.25"] * 3
    assert [r[i_b] for r in rows[1:4]] == ["", "", ""]
    assert [r[i_s] for r in rows[1:4]] == ["7.0"] * 3
    assert "CSV   FAIL" not in a.log.get("1.0", "end")


# ------------------------------------------------------------ the spacing ---
def test_a_status_label_holds_no_row_until_it_has_something_to_say(a):
    """Both status lines are born unpacked and go through _show_status, so
    the gap under Data files and 3D Printing is the section gap and nothing
    else."""
    for lbl in (a._data_status, a._stl_status):
        assert getattr(lbl, "_status_pack", None), lbl
        a._show_status(lbl, "")
        assert lbl.winfo_manager() == ""
        a._show_status(lbl, "something", app.STATE)
        assert lbl.winfo_manager() == "pack"
        assert lbl.cget("text") == "something"
        assert lbl.cget("fg") == a._state_fg()
        a._show_status(lbl, "trouble", app.WARN)
        assert lbl.cget("fg") == a._semantic_fg(app.SEM_WARN)
        a._show_status(lbl, "")
        assert lbl.winfo_manager() == ""
        assert lbl.cget("text") == ""
    a._show_status(None, "no widget, no crash")


# --------------------------------------------------------- settings + guide -
def test_a_saved_section_order_learns_data_files(a):
    """Nhan's own settings hold a dragged order written before the section
    existed, and _reorder_sections packs an unknown key AFTER everything it
    knows -- which is why his build showed Data files last. The migration
    gives it its factory slot."""
    keep = a.settings.get("section_order")
    try:
        a.settings["section_order"] = {
            "Export": ["Figure", "Export", "3D Printing"],
            "Plot": ["Plot mode"]}
        a._migrate_settings()
        seq = a.settings["section_order"]["Export"]
        assert seq == ["Figure", "Export", "Data files", "3D Printing"]
        assert a.settings["section_order"]["Plot"] == ["Plot mode"]
        a._migrate_settings()                      # idempotent
        assert a.settings["section_order"]["Export"].count("Data files") == 1
    finally:
        if keep is None:
            a.settings.pop("section_order", None)
        else:
            a.settings["section_order"] = keep


def test_my_notes_is_the_first_launch_guide_view(a):
    """The box is a scratchpad first and a manual second, so a settings file
    with no ref_view opens on My notes; the last pick is still remembered.

    Asserted on the source, because the default is read once while the App
    is being built and this suite builds exactly one (TESTING_POLICY 1)."""
    src = open(app.__file__, encoding="utf-8").read()
    assert 'self.settings.get("ref_view", "My notes")' in src
    assert 'self.settings.get("ref_view", "Quick start")' not in src
    a.ref_kind.set("My notes")
    assert a.settings["ref_view"] == "My notes"      # the pick is remembered
    a.ref_kind.set("Quick start")
    assert a.settings["ref_view"] == "Quick start"
