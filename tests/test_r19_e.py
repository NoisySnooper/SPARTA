"""R19 wave E: one bundle of data files, in one place.

Before R19 the same files came from six places behind five folder dialogs,
and what a Run wrote depended on the df DISPLAY switch. R19 put one list on
the Export tab, EXPORT > DATA FILES, and both a Run and 'Export data...'
write exactly what is ticked in it.

R20 kept the list and merged what it names: a ticked row is a COLUMN in the
trace's own CSV now, not a file of its own. The rulings that survive that
change stay here, spelled in R20's vocabulary; the merged model itself, the
Export dialog and the writers are tests/test_r20_e.py.

One test per ruling:

  * the four ticks, their defaults and where they persist (SETTINGS, never a
    preset: applying somebody else's figure must not change what a Run
    writes to disk);
  * where the section lives, what it holds, and what the two sections it
    took controls from no longer hold;
  * its slot between Export and 3D Printing;
  * Ctrl+E.

Runs against the suite's ONE shared App (tests/conftest.py).
"""
import json

import pytest

import app
from conftest import gui, shared_app

USES_APP = True
pytestmark = gui


@pytest.fixture(scope="module")
def a():
    return shared_app()


# --------------------------------------------------------------- helpers ---
def _section(a, title):
    return [r for r in a._collapsibles if r["key"] == title][0]


def _inside(box, w):
    while w is not None:
        if w is box:
            return True
        w = getattr(w, "master", None)
    return False


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


# ------------------------------------------------------- the four ticks ----
def test_the_product_ticks_default_and_persist_in_settings(a):
    """Defringed on, the other three off; every tick reaches the settings
    FILE at once; and none of them is a preset variable."""
    assert app.EXPORT_PRODUCT_DEFAULTS == {"defringed": True,
                                           "smoothed": False,
                                           "cd_tagged": False,
                                           "formula": False}
    assert app.EXPORT_PRODUCT_ORDER == ("absorbance", "defringed", "smoothed",
                                        "formula", "cd_tagged")
    assert a._products() == {"absorbance": True, "defringed": True,
                             "smoothed": False, "cd_tagged": False,
                             "formula": False}
    # Absorbance is a fact, not a choice: the row is ticked and disabled
    assert a._abs_always.get() is True
    assert str(a._product_checks["defringed"].cget("state")) != "disabled"

    reg = a._preset_registry()
    for k in app.EXPORT_PRODUCT_DEFAULTS:
        assert k not in reg
    assert "export_products" not in reg

    a.export_products["smoothed"].set(True)
    with open(app.SETTINGS_PATH) as f:
        data = json.load(f)
    assert data["export_products"] == {"defringed": True, "smoothed": True,
                                       "cd_tagged": False, "formula": False}
    assert a._products()["smoothed"] is True
    a.export_products["smoothed"].set(False)
    with open(app.SETTINGS_PATH) as f:
        assert json.load(f)["export_products"]["smoothed"] is False


# ------------------------------------------------------ where it all is ----
def test_the_data_files_section_holds_the_list_and_the_button(a):
    """EXPORT > DATA FILES exists, sits under the Export tab, carries the
    five rows in order, the button and the status line; and the sections it
    took controls from have let them go."""
    assert a._section_cat["Data files"] == "Export"
    sec = _section(a, "Data files")
    assert sec["cat"] == "Export"
    body = sec["body"]
    assert _labels(body, "TCheckbutton") == [
        "Absorbance data (always)", "Defringed data", "Smoothed data",
        "Formula values", "C/D tag in file name"]
    assert "Include in each trace's CSV:" in _labels(body, "Label")
    for w in (a._export_data_btn, a._data_status):
        assert _inside(body, w)
    assert a._export_data_btn.cget("text") == "Export data" + chr(0x2026)
    assert a._data_status.cget("text") == ""          # empty at birth
    # R20: Crop is export-only, so its widgets live in the dialog and the
    # section carries no entry at all
    assert [w for w in _walk(body) if w.winfo_class() == "TEntry"] == []
    ex = _section(a, "Export")["body"]
    assert "Crop" not in _labels(ex, "TCheckbutton")
    # 'Export CSV...' is gone from EXPORT > EXPORT
    assert not [t for t in _labels(ex, "TButton")
                if t.startswith("Export CSV")]
    # the branch-tagged CSVs left DATA > TRACES
    tr = _section(a, "Traces")["body"]
    assert not [t for t in _labels(tr, "TButton") if "C/D" in t]
    assert "Export D list (CSV) by selection" in _labels(tr, "TButton")
    # 'Find a setting' reads the new widgets without being told about them
    sec["search_text"] = None
    blob = a._section_text(sec)
    for word in ("defringed data", "c/d tag in file name", "export data"):
        assert word in blob, word


def test_data_files_sits_between_export_and_3d_printing(a):
    """The section's SLOT, not just its tab.

    _reorder_sections packs each tab from App.SECTION_ORDER, the factory
    baseline, and appends whatever it does not recognise after it. A key
    missing from that tuple is therefore packed in the tail, BELOW
    3D Printing, which is where R19's first build put 'Data files'. It
    belongs between Export and 3D Printing: in the tuple, and on the live
    Export page. (A settings file whose saved order predates the section
    gets the same slot in _migrate_settings; see test_r20_e.py.)
    """
    order = list(app.App.SECTION_ORDER)
    assert "Data files" in order, "SECTION_ORDER never learned the section"
    assert order.index("Data files") == order.index("Export") + 1
    assert order.index("Data files") < order.index("3D Printing")
    recs = {r["key"]: r for r in a._collapsibles if r["cat"] == "Export"}
    trio = ("Export", "Data files", "3D Printing")
    conts = [recs[k]["cont"] for k in trio]
    page = conts[0].master
    assert all(c.master is page for c in conts), "not one Export page"
    slaves = list(page.pack_slaves())
    pos = [slaves.index(c) for c in conts]
    assert pos == sorted(pos), [str(w) for w in slaves]
    a.root.update_idletasks()
    ys = [c.winfo_y() for c in conts]
    assert ys == sorted(ys), dict(zip(trio, ys))


def test_ctrl_e_is_bound_to_the_data_export(a):
    """The Run/export pair: Ctrl+Return runs, Ctrl+E opens the Export
    dialog (R20; it used to write straight through a folder dialog)."""
    assert a.root.bind("<Control-e>")
    assert a.root.bind("<Control-Return>")
    assert callable(a._open_export_dialog)
    assert not hasattr(a, "_export_data")
