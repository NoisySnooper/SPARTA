"""make_demo_data.py  --  build the bundled demo dataset.

Writes a small SYNTHETIC absorption series into demo_data/ next to this
file, named in the classic 22-IR-1 convention so the built-in naming
profile reads it with no configuration:

    vis_DEMO_glass_<P>[_bg|_s][_D].<seg>

5 series points x 3 channels (bare = dark, _bg = background, _s = sample)
x 2 grating segments (.001 / .002) = 30 files, ~1200 points per
measurement.  Four points are the compression branch (0.0 / 5.2 / 12.8 /
20.1 GPa); the fifth carries the _D tag (8.4 GPa on release), so the
decompression styling, the Only C / Only D filters and the D branch of a
thickness plot all have something real to act on.

The spectra are MODELLED, not measured: a smooth lamp envelope, a
pressure-dependent absorption edge that red-shifts under compression, and
the THREE etalon tones of a real loaded cell, so the whole fringe
workbench loop - detect, assign the three roles, Fit peaks, Solve,
Record - completes on it for real:

    sample channel      A   = n_s * t            the sample etalon
                        C   = A + n_Ar * (d1+d2) the whole-cell line
                              (sample + the argon gap around it)
    background channel  iii = n_Ar * L           the empty-gap etalon,
                              L = d1 + t + d2

The ground truth behind the tones is one consistent cell: an n_s = 1.75
glass plate thinning under load inside an argon-filled gap that closes
with pressure, between diamond anvils.  The argon index per pressure is
the SAME Ar model the workbench solves with (fringe_materials.medium_n,
values frozen below), so solving the demo with the default stack (medium
Argon (Dewaele), no layer 2) hands back the ground truth: n_s = 1.75,
t and L per the tables below, no clamps.  The decompression point does
not retrace the compression branch: its sample path sits 2.45 um below
the compression trend at the same pressure, the permanent-compaction
hysteresis a real release run shows.

Nothing here is measurement data and nothing is anybody's unpublished
result: the generator is deterministic, so the same files come out of
every run and the folder can be shipped verbatim.

Run:  python make_demo_data.py [--out DIR] [--check]
      --check re-reads the folder through engine.scan_folder, through
      the fringe detector (both channels), and - when the fringe core is
      importable - runs the actual three-role solve on every point and
      asserts it lands on the ground truth.
"""

import argparse
import os
import sys

import numpy as np

TOOL_DIR = os.path.dirname(os.path.abspath(__file__))
DEMO_DIR = os.path.join(TOOL_DIR, "demo_data")

DAC = "DEMO"
SAMPLE = "glass"

# (pressure token, pressure in GPa, branch).  'p' is the decimal point;
# the branch is an engine token of its own (..._s_D.001), never glued to
# the pressure - '8p4D' would fail the numeric pressure parse.
POINTS = [("0p0", 0.0, None),
          ("5p2", 5.2, None),
          ("12p8", 12.8, None),
          ("20p1", 20.1, None),
          ("8p4", 8.4, "D")]      # on release, after the 20.1 GPa point

# Two grating segments, adjoining rather than overlapping (the engine
# concatenates them in seq order).
SEGMENTS = [(1, 400.0, 700.0, 600), (2, 700.5, 1000.0, 600)]

DARK_LEVEL = 340.0          # counts, detector pedestal
LAMP_PEAK = 26000.0         # counts at the envelope maximum
LAMP_CENTER = 745.0         # nm
LAMP_WIDTH = 255.0          # nm (gaussian sigma of the envelope)

EDGE_A_MAX = 1.65           # absorbance well below the edge
EDGE_BASE = 0.045           # flat absorbance above the edge
EDGE_NM_0 = 521.0           # edge position at 0 GPa (nm)
EDGE_SHIFT = 6.4            # nm per GPa (red shift under compression)
EDGE_WIDTH = 27.0           # nm (sigmoid softness)

# ---------------------------------------------------------------------------
# The cell (ground truth the three tones are computed from)
# ---------------------------------------------------------------------------
N_SAMPLE = 1.75             # the glass plate's index (constant with P here)
NT_SAMPLE_0 = 32.0          # sample optical path n_s*t at 0 GPa (um)
NT_SAMPLE_SLOPE = -0.28     # um per GPa (the sample thins under load)
NT_D_HYSTERESIS = 2.45      # um the D branch stays BELOW the C trend
GAP_0 = 9.4                 # d1+d2, the argon gap around the sample (um)
GAP_SLOPE = -0.14           # um per GPa (the gasket closes)

# Argon refractive index per demo pressure, at 700 nm - the values of
# fringe_materials.medium_n('Ar', P, 700.0), frozen here so the folder
# is byte-reproducible standalone.  --check re-derives them against the
# live model and complains on drift.
N_AR = {0.0: 1.0, 5.2: 1.4238422806, 8.4: 1.4624180093,
        12.8: 1.4986500801, 20.1: 1.5393248280}

# Modulation depths (fraction of the channel's counts).  The sample
# etalon dominates its channel so detection still reports the sample
# path as the fundamental; the whole-cell line is the weaker second
# tone a real cell shows (wedge and parallelism damp the longer path).
FRINGE_M_SAMPLE = 0.055     # A tone, sample channel
FRINGE_M_CELL = 0.026       # C tone, sample channel
FRINGE_M_BG = 0.038         # iii tone, background channel
FRINGE_PHASE = 0.7          # radians (A + iii)
FRINGE_PHASE_2 = 2.1        # radians (C - decorrelated from A)

NOISE_FRAC = 0.0035         # gaussian read noise as a fraction of the counts
DARK_NOISE = 2.5            # counts


def _seed(pressure_token, channel, seq, branch=None):
    """A stable per-file seed, so a re-run reproduces the folder byte for
    byte and one changed point does not reshuffle the others."""
    h = 0
    for ch in "%s|%s|%d|%s" % (pressure_token, channel, seq, branch or "C"):
        h = (h * 131 + ord(ch)) & 0x7FFFFFFF
    return h


def lamp(wl):
    """Smooth source envelope (counts), never negative."""
    return LAMP_PEAK * np.exp(-0.5 * ((wl - LAMP_CENTER) / LAMP_WIDTH) ** 2)


def absorbance(wl, pressure):
    """Modelled sample absorbance: one edge, red-shifting with pressure."""
    edge = EDGE_NM_0 + EDGE_SHIFT * pressure
    return EDGE_BASE + EDGE_A_MAX / (1.0 + np.exp((wl - edge) / EDGE_WIDTH))


# ---------------------------------------------------------------------------
# Ground-truth optical paths (um) per point
# ---------------------------------------------------------------------------
def nt_sample_um(pressure, branch=None):
    """A = n_s*t.  The release branch does not retrace the compression
    one: some of the thinning is permanent, so a D point sits below the
    C trend at the same pressure."""
    nt = NT_SAMPLE_0 + NT_SAMPLE_SLOPE * pressure
    return nt - NT_D_HYSTERESIS if branch == "D" else nt


def gap_um(pressure):
    """d1+d2, the argon-filled gap around the sample."""
    return GAP_0 + GAP_SLOPE * pressure


def cell_paths(pressure, branch=None):
    """The three optical paths (um) the workbench's solve inverts:
    A (sample), C (whole cell), iii (medium etalon)."""
    n_ar = N_AR[pressure]
    A = nt_sample_um(pressure, branch)
    t = A / N_SAMPLE
    gap = gap_um(pressure)
    L = t + gap
    return {"A": A, "C": A + n_ar * gap, "iii": n_ar * L,
            "t": t, "gap": gap, "L": L, "n_ar": n_ar}


def fringe(wl, nt_um, depth, phase=FRINGE_PHASE):
    """Etalon modulation.  The fringe is periodic in wavenumber 1/lambda
    with frequency 2*n*t, which is exactly what the detector looks for."""
    nt_nm = nt_um * 1000.0
    return depth * np.cos(2.0 * np.pi * (2.0 * nt_nm) * (1.0 / wl) + phase)


def channel_counts(wl, pressure, channel, rng, branch=None):
    """Counts for one channel on one wavelength grid."""
    dark = DARK_LEVEL + DARK_NOISE * rng.standard_normal(wl.size)
    if channel == "dark":
        return dark
    src = lamp(wl)
    p = cell_paths(pressure, branch)
    if channel == "background":
        # the empty spot beside the sample: anvil | argon (L) | anvil
        sig = src * (1.0 + fringe(wl, p["iii"], FRINGE_M_BG))
    else:
        # through the sample: the sample etalon plus the whole-cell line
        t = np.power(10.0, -absorbance(wl, pressure))
        sig = src * t * (1.0 + fringe(wl, p["A"], FRINGE_M_SAMPLE)
                         + fringe(wl, p["C"], FRINGE_M_CELL,
                                  phase=FRINGE_PHASE_2))
    sig = np.clip(sig, 0.0, None)
    noise = NOISE_FRAC * np.sqrt(np.maximum(sig, 1.0)) * np.sqrt(sig + 1.0)
    return dark + sig + noise * rng.standard_normal(wl.size) * 0.05


def filename(pressure_token, channel, seq, branch=None):
    suffix = {"dark": "", "background": "_bg", "sample": "_s"}[channel]
    if branch:
        suffix += "_" + branch
    return "vis_%s_%s_%s%s.%03d" % (DAC, SAMPLE, pressure_token, suffix, seq)


def write_file(path, wl, counts, label):
    """Two-column instrument CSV with the usual quoted metadata line."""
    with open(path, "w", encoding="utf-8", newline="") as f:
        f.write('"# SPARTA demo dataset (synthetic)","%s"\n' % label)
        for w, c in zip(wl, counts):
            f.write("%.3f,%.1f\n" % (w, c))


def build(out_dir=DEMO_DIR, quiet=False):
    """Write the whole folder.  Returns the list of files written."""
    if not os.path.isdir(out_dir):
        os.makedirs(out_dir)
    written = []
    for ptok, pval, branch in POINTS:
        for channel in ("dark", "background", "sample"):
            for seq, lo, hi, n in SEGMENTS:
                wl = np.linspace(lo, hi, n)
                rng = np.random.RandomState(_seed(ptok, channel, seq, branch))
                counts = channel_counts(wl, pval, channel, rng, branch)
                name = filename(ptok, channel, seq, branch)
                write_file(os.path.join(out_dir, name), wl, counts, name)
                written.append(name)
    _write_readme(out_dir)
    if not quiet:
        print("Wrote %d files to %s" % (len(written), out_dir))
    return written


def _write_readme(out_dir):
    comp = [p for p in POINTS if p[2] is None]
    dec = [p for p in POINTS if p[2] == "D"]
    rows = []
    for ptok, pval, branch in sorted(POINTS, key=lambda p: p[1]):
        c = cell_paths(pval, branch)
        rows.append("    %5.1f %s   %5.2f  %5.2f  %5.2f      %5.2f  %5.2f"
                    % (pval, branch or "C", c["A"], c["C"], c["iii"],
                       c["t"], c["L"]))
    txt = (
        "SPARTA demo dataset\n"
        "===================\n\n"
        "Synthetic, generated by make_demo_data.py.  Not measurement data.\n\n"
        "%d series points x 3 channels x 2 grating segments, named in the\n"
        "22-IR-1 convention the built-in profile reads:\n\n"
        "    vis_%s_%s_<P>[_bg|_s][_D].<seg>\n\n"
        "    no suffix = dark,  _bg = background,  _s = sample\n"
        "    P uses 'p' for the decimal point: 12p8 = 12.8 GPa\n"
        "    _D marks the decompression branch (no tag = compression)\n\n"
        "    compression    %s GPa\n"
        "    decompression  %s GPa, on release from the highest point\n\n"
        "Model: a gaussian lamp envelope, an absorption edge that red-shifts\n"
        "%.1f nm per GPa, and the three etalon tones of one consistent cell:\n"
        "an n = %.2f glass plate thinning under load inside an argon-filled\n"
        "gap that closes with pressure, between diamond anvils.  The sample\n"
        "channel carries the sample etalon (the strong tone) and the weaker\n"
        "whole-cell line; the background channel carries the empty-gap\n"
        "etalon.  The argon index per pressure is the same Ar model the\n"
        "fringe workbench solves with, so the full loop - detect, assign\n"
        "roles, Fit peaks, Solve, Record - lands on the ground truth below\n"
        "(default stack: medium Argon (Dewaele), no layer 2, no clamps).\n\n"
        "    P GPa      A      C    iii        t      L    (um)\n"
        "%s\n\n"
        "    A = n_s*t (sample), C = A + n_Ar*(d1+d2) (whole cell),\n"
        "    iii = n_Ar*L with L = d1+t+d2.  Solve returns n_s = %.2f.\n\n"
        "The decompression point does not retrace the compression branch:\n"
        "its sample path sits %.2f um below the compression trend at the\n"
        "same pressure, so 'Only C' / 'Only D' and the Thickness (fringe\n"
        "n*t) mode both show something real.\n\n"
        "Point the Input folder here and press Run.  The interactive tour\n"
        "(About > Welcome & tour) loads it for you.\n"
        % (len(POINTS), DAC, SAMPLE,
           " / ".join("%.1f" % p[1] for p in comp),
           " / ".join("%.1f" % p[1] for p in dec),
           EDGE_SHIFT, N_SAMPLE, "\n".join(rows), N_SAMPLE,
           NT_D_HYSTERESIS))
    with open(os.path.join(out_dir, "README.txt"), "w",
              encoding="utf-8") as f:
        f.write(txt)


# ---------------------------------------------------------------------------
# Verification (not a test suite: a build-time sanity pass)
# ---------------------------------------------------------------------------
def check(out_dir=DEMO_DIR):
    """Re-read the folder the way the app does.  Returns True on success."""
    sys.path.insert(0, TOOL_DIR)
    import engine
    groups, skipped = engine.scan_folder(out_dir)
    ok = True
    print("scan_folder: %d group(s), %d skipped" % (len(groups), len(skipped)))
    for raw in skipped:
        # README.txt is not a segment file and is expected to be skipped
        if raw["raw"] == "README.txt":
            continue
        ok = False
        print("  UNEXPECTED SKIP %s: %s" % (raw["raw"], raw["reason"]))
    want_branches = sorted((p[2] or "C") for p in POINTS)
    got_branches = []
    for gkey in sorted(groups, key=lambda k: groups[k]["pressure_val"]):
        g = groups[gkey]
        chans = sorted(g["meas"])
        segs = sorted(g["meas"]["sample"][1])
        got_branches.append(gkey[3] or "C")
        print("  %-30s %5.1f  branch=%s channels=%s segments=%s"
              % (str(gkey), g["pressure_val"], gkey[3] or "C",
                 ",".join(chans), segs))
        if chans != ["background", "dark", "sample"]:
            ok = False
            print("    MISSING CHANNELS")
        if segs != [1, 2]:
            ok = False
            print("    MISSING SEGMENTS")
    if len(groups) != len(POINTS):
        ok = False
        print("  expected %d groups, got %d" % (len(POINTS), len(groups)))
    if sorted(got_branches) != want_branches:
        ok = False
        print("  branch tags %s, expected %s"
              % (sorted(got_branches), want_branches))

    # the frozen argon indices must match the live model (drift alarm)
    try:
        import fringe_materials
        for pv, nfroz in sorted(N_AR.items()):
            nlive = fringe_materials.medium_n("Ar", pv, 700.0)
            if abs(nlive - nfroz) > 1e-6:
                ok = False
                print("  N_AR DRIFT at %.1f GPa: frozen %.10f, model %.10f"
                      % (pv, nfroz, nlive))
    except Exception as e:                              # pragma: no cover
        print("fringe_materials unavailable (%r); N_AR drift not checked" % e)

    # reduce into a scratch dir, never into the folder we ship
    import shutil
    import tempfile
    scratch = tempfile.mkdtemp(prefix="sparta_democheck_")
    try:
        results, _sk = engine.run(out_dir, scratch, log=lambda m: None)
    finally:
        shutil.rmtree(scratch, ignore_errors=True)
    print("engine.run: %d result(s)" % len(results))
    if len(results) != len(POINTS):
        ok = False
        print("  engine.run did not reduce every point")

    try:
        import fringe_apply
    except Exception as e:                              # pragma: no cover
        print("fringe_apply unavailable (%r); skipping the fringe check" % e)
        return ok
    for r in sorted(results, key=lambda x: x["pressure_val"]):
        row = ["%5.1f GPa %s" % (r["pressure_val"],
                                 r.get("branch_tag") or "C")]
        truth = cell_paths(r["pressure_val"], r.get("branch_tag"))
        for ch, key, want in (("sample", "samp_c", truth["A"]),
                              ("background", "bg_c", truth["iii"])):
            counts = r.get(key)
            if counts is None:
                row.append("%s: n/a" % ch)
                continue
            out = fringe_apply.clean_channel(r["wl"], counts)
            nt = out.get("nt_um")
            row.append("%s n*t = %s um (want %.2f, p = %.1e)"
                       % (ch, "none" if nt is None else "%.2f" % nt,
                          want, out.get("pvalue", 1.0)))
            if not out.get("applied"):
                ok = False
            elif nt is not None and abs(nt - want) > 0.6:
                ok = False
                row.append("OFF TRUTH")
        print("  " + "   ".join(row))

    # the three-role solve, exactly as the workbench runs it: the three
    # ground-truth paths at the recorded argon index must invert to the
    # cell (n_s, t, L) with no clamp warnings.
    try:
        import fringe_optics
    except Exception as e:                              # pragma: no cover
        print("fringe_optics unavailable (%r); skipping the solve check" % e)
        return ok
    print("solve_paths (three-role inversion, medium = Ar):")
    for ptok, pval, branch in sorted(POINTS, key=lambda p: p[1]):
        c = cell_paths(pval, branch)
        sol = fringe_optics.solve_paths(c["A"], c["C"], c["iii"],
                                        c["n_ar"], c["n_ar"])
        good = (sol is not None and not sol["warns"]
                and abs(sol["n_s"] - N_SAMPLE) < 1e-9
                and abs(sol["t_s"] - c["t"]) < 1e-9
                and abs(sol["L"] - c["L"]) < 1e-9)
        if not good:
            ok = False
        print("  %5.1f %s  n_s=%.4f t=%.3f L=%.3f  %s"
              % (pval, branch or "C",
                 sol["n_s"] if sol else float("nan"),
                 sol["t_s"] if sol else float("nan"),
                 sol["L"] if sol else float("nan"),
                 "ok" if good else "MISMATCH"))
    return ok


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--out", default=DEMO_DIR)
    ap.add_argument("--check", action="store_true",
                    help="verify the folder parses and the fringes detect")
    ap.add_argument("--quiet", action="store_true")
    a = ap.parse_args(argv)
    build(a.out, quiet=a.quiet)
    if a.check:
        return 0 if check(a.out) else 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
