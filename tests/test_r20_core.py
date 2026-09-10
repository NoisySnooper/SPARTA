"""R20 wave E-core: ONE CSV per trace.

The round merges every ticked product into the trace's own absorbance file
instead of writing a second one beside it.  Two modules carry that:

  * ``engine.write_absorbance_csv(result, out_dir, extra=None, branch=None)``
    -- the six base columns are frozen in name and in order, ``extra``
    appends more after them, ``branch`` forces the name's C/D letter without
    touching the caller's record.  With both defaults the bytes are the
    pre-R20 writer's, which is why the old golden is written BY HAND here
    rather than taken from the function under test;
  * ``fringe_apply.notch_columns(result, bg_kw=None, s_kw=None, **kw)`` --
    the arrays the retired ``write_defringed_csv`` used to write, returned
    instead of filed.  ``Absorbance_notch`` is always filled; a channel with
    no detected fringe still leaves its own column blank.

And the reader has to survive both: ``engine.load_processed_folder`` finds
its columns by name, so the extras are read past, and it parses a forced
letter exactly like a raw-file one.

Pure modules: no App, no Tk (TESTING_POLICY section 1).
"""
import csv
import os

import numpy as np
import pytest

import engine
import fringe_apply
from conftest import make_result

# The synthetic fringe of tests/test_defringe_pipeline.py, the fixture the
# pipeline tests are written against, so the numbers here mean the same thing.
NT_UM = 30.0
NT_NM = NT_UM * 1000.0
GATE = dict(halfwidth_um=3.0, nt_min_nm=8000.0, nt_max_nm=300000.0)

BASE = ["Wavelength_nm", "Wavenumber_cm-1", "Absorbance", "Dark",
        "Background", "Sample"]
NOTCH = ["Absorbance_notch", "Background_notch", "Sample_notch"]


def _fringed(nt_um=NT_UM, amp=0.06, n=1400, lo=500.0, hi=900.0):
    """Counts with ONE clean interference fringe of optical path n*t."""
    wl = np.linspace(lo, hi, n)
    base = 1000.0 * (1.0 + 0.30 * (wl - lo) / (hi - lo))
    return wl, base * (1.0 + amp * np.cos(4.0 * np.pi * nt_um * 1000.0 / wl))


def _flat(n=1400, lo=500.0, hi=900.0, seed=7):
    """Counts with no fringe in them: a lamp envelope and a little noise."""
    wl = np.linspace(lo, hi, n)
    base = 1000.0 * (1.0 + 0.30 * (wl - lo) / (hi - lo))
    rng = np.random.RandomState(seed)
    return wl, base * (1.0 + 0.002 * rng.randn(n))


def _rec(dac="X", sample="oliv", pstr="20p0", tag=None, nan=False):
    """A small engine-style record; `nan` puts holes in two columns."""
    r = make_result("20 GPa", 20.0, n=12, dac=dac, sample=sample, pstr=pstr,
                    tag=tag)
    if nan:
        r["absorbance"][3] = np.nan
        r["bg_c"][5] = np.nan
        r["wn"][0] = np.nan
    return r


def _golden(result, path):
    """The pre-R20 writer, by hand: six columns, blank cell for NaN."""
    with open(path, "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(BASE)
        for row in zip(result["wl"], result["wn"], result["absorbance"],
                       result["dark_c"], result["bg_c"], result["samp_c"]):
            w.writerow(["" if (isinstance(v, float) and np.isnan(v)) else v
                        for v in row])
    return path


def _read(path):
    with open(path, newline="", encoding="utf-8") as fh:
        rows = list(csv.reader(fh))
    return rows[0], rows[1:]


# ===========================================================================
# 1. the writer's frozen half
# ===========================================================================
def test_the_default_call_is_byte_identical_to_the_old_writer(tmp_path):
    """extra=None, branch=None: the same bytes, NaN holes included.

    Every reader of this tool's output -- the viewer, Matthew's scripts, the
    provenance sha -- was written against those bytes."""
    r = _rec(nan=True)
    new = engine.write_absorbance_csv(r, str(tmp_path))
    old = _golden(r, str(tmp_path / "golden.csv"))
    assert os.path.basename(new) == "X_oliv_20p0_absorbance.csv"
    with open(new, "rb") as fh:
        got = fh.read()
    with open(old, "rb") as fh:
        want = fh.read()
    assert got == want


def test_extras_are_appended_after_the_six_and_blanks_stay_blank(tmp_path):
    """Header order is base-then-extras, in the caller's order, and a NaN in
    an extra is a blank cell like everywhere else."""
    r = _rec()
    n = r["wl"].size
    smooth = np.linspace(0.0, 1.0, n)
    holes = np.full(n, np.nan)
    holes[2] = 4.5
    path = engine.write_absorbance_csv(
        r, str(tmp_path), extra=[("Absorbance_notch", smooth),
                                 ("Sample_notch", holes),
                                 ("Fe [wt%]", smooth * 2.0)])
    head, rows = _read(path)
    assert head == BASE + ["Absorbance_notch", "Sample_notch", "Fe [wt%]"]
    i_h = head.index("Sample_notch")
    assert [row[i_h] for row in rows] == ["", "", "4.5"] + [""] * (n - 3)
    got = np.array([float(row[head.index("Absorbance_notch")])
                    for row in rows])
    assert np.allclose(got, smooth)
    # A column that does not line up with the trace is a caller bug, not a
    # file with a short column in it.
    with pytest.raises(ValueError):
        engine.write_absorbance_csv(r, str(tmp_path),
                                    extra=[("Short", smooth[:-1])])


def test_branch_forces_the_letter_without_touching_the_record(tmp_path):
    """The tick puts _C (or _D) on every name; the record still reports what
    the raw file names said."""
    plain, marked = _rec(), _rec(tag="C")
    names = {}
    for key, rec, br in (("c", plain, "C"), ("d", plain, "D"),
                         ("raw", marked, None), ("flip", marked, "D")):
        names[key] = os.path.basename(
            engine.write_absorbance_csv(rec, str(tmp_path), branch=br))
    assert names["c"] == "X_oliv_20p0_C_absorbance.csv"
    assert names["d"] == "X_oliv_20p0_D_absorbance.csv"
    assert names["raw"] == "X_oliv_20p0_C_absorbance.csv"    # today's rule
    assert names["flip"] == "X_oliv_20p0_D_absorbance.csv"   # forced wins
    assert plain["branch_tag"] is None and marked["branch_tag"] == "C"
    # one letter, never two: the stem is dac/sample/pressure plus at most one
    assert names["flip"].count("_D") == 1


# ===========================================================================
# 2. the reader
# ===========================================================================
def test_the_loader_ignores_the_extras_and_reads_a_forced_letter(tmp_path):
    """Columns are found by name, so a merged file loads as its base six."""
    r = _rec()
    n = r["wl"].size
    decoy = r["absorbance"] + 5.0        # if a lookup slipped, this shows
    engine.write_absorbance_csv(
        r, str(tmp_path), extra=[("Absorbance_notch", decoy),
                                 ("Background_notch", np.full(n, np.nan)),
                                 ("Sample_notch", decoy)])
    engine.write_absorbance_csv(_rec(pstr="30p0"), str(tmp_path), branch="D",
                                extra=[("Absorbance_notch", decoy)])
    # a legacy companion from before R20 retired the standalone file
    _golden(r, str(tmp_path / "X_oliv_20p0_absorbance_notch.csv"))

    got = engine.load_processed_folder(str(tmp_path))
    assert len(got) == 2
    by_p = {g["pressure_str"]: g for g in got}
    assert set(by_p) == {"20p0", "30p0"}
    assert by_p["20p0"]["branch_tag"] is None
    assert by_p["30p0"]["branch_tag"] == "D"
    assert by_p["30p0"]["sample"] == "oliv" and by_p["30p0"]["dac"] == "X"
    assert np.allclose(by_p["20p0"]["absorbance"], r["absorbance"])
    assert np.allclose(by_p["20p0"]["bg_c"], r["bg_c"])


# ===========================================================================
# 3. the notch columns
# ===========================================================================
def test_one_clean_channel_still_fills_the_absorbance_column():
    """Background flat, Sample fringed: one channel cleans, and the merged
    Absorbance_notch is a complete trace all the same."""
    wl, samp = _fringed()
    _wl, bg = _flat()
    r = make_result("20 GPa", 20.0, wl=wl, samp=samp, bg=bg,
                    dark=np.ones(wl.size))
    cols = fringe_apply.notch_columns(r, **GATE)

    assert set(cols) == set(NOTCH) | {"applied_bg", "applied_s", "nt_bg_um",
                                      "nt_s_um", "p_bg", "p_s"}
    assert cols["applied_bg"] is False and cols["applied_s"] is True
    assert cols["nt_bg_um"] is None
    assert cols["nt_s_um"] == pytest.approx(NT_UM, rel=0.05)
    assert cols["p_s"] < 1e-4                       # the fringe is confident
    assert cols["p_s"] < cols["p_bg"] <= 1.0        # the flat channel is not

    assert np.isnan(cols["Background_notch"]).all()          # blank column
    assert np.isfinite(cols["Sample_notch"]).all()
    straight = np.log10((bg - 1.0) / (samp - 1.0))
    assert np.isfinite(straight).all()
    assert np.isfinite(cols["Absorbance_notch"]).all()       # always filled
    assert not np.allclose(cols["Absorbance_notch"], straight)
