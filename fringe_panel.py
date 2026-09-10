"""
fringe_panel.py  --  the fringe workbench: FFT view, sidebar cards, pop-out.

The whole interactive surface lives here.  app.py owns five small touchpoints
(import, the centre Plot|Fringe view switch, the right-notebook Fringe tab, the
settings defaults, the session payload) and nothing else; every widget, every
mouse gesture and all of the workbench state is built and held by
:class:`FringeWorkbench`.

Numeric core vendored from `defringe_dac.py` (DAC Absorption Fringe Analysis).
    Source module : defringe_dac.py  (launch_fft_gui, :8994-:15903)
    Author        : Matthew R. Diamond
    Repository    : github.com/matthewrdiamond/DAC-Absorption-Fringe-Analysis
    License       : vendored under MIT by permission of the author.

This module is the SPARTA-side re-implementation of that GUI's behaviour on
top of the vendored pure functions (fringe_detect / fringe_notch / fringe_fit /
fringe_optics / fringe_stack / fringe_materials / fringe_config).  The physics,
the click grammar and the state discipline are his; the widget grammar,
theming and layout are SPARTA's (DESIGN_RULES).

NQT / Lee Lab -- Aug 2026.
"""

import json
import os
import sys
import time
import tkinter as tk
import warnings
from tkinter import filedialog, messagebox, ttk

import numpy as np
from matplotlib.backends.backend_tkagg import (FigureCanvasTkAgg,
                                               NavigationToolbar2Tk)
from matplotlib.figure import Figure
from matplotlib.path import Path as _MPath
from matplotlib.ticker import AutoMinorLocator, FuncFormatter, MaxNLocator
from matplotlib.ticker import ScalarFormatter

import colormaps
import fringe_materials
import fringe_optics
import fringe_popout
import fringe_stack
from fringe_config import (DIAMOND_MODELS, LP_EDGE_SHAPES, FringeConfig,
                           config_for_date, parse_folder_date)
from fringe_detect import compute_channel_fit
from fringe_notch import removed_profile_um

# ---------------------------------------------------------------------------
# app.py's vocabulary, mirrored here and re-bound from the host module at first
# use so there is still exactly ONE source of truth (DESIGN_RULES rule 9).  The
# literals below are only the fallback the standalone harness runs on.
# ---------------------------------------------------------------------------
LBL_W = 11
LBL_W2 = 6
PAD_ROW = (4, 1)
PAD_GROUP = (8, 2)
PAD_TIGHT = (0, 1)
PAD_X = 6
PAD_X_TIGHT = 2
MUTED = None            # app.py's sentinel; rebound below
Tooltip = None          # app.py's tooltip class; rebound below

_HOST_BOUND = [False]


def _bind_host(app):
    """Adopt the host module's spacing vocabulary, MUTED sentinel and Tooltip.

    fringe_panel must not import app.py (that would be circular), so the two
    names it genuinely shares are looked up on the App's own module the first
    time a workbench is built.  Missing names keep the fallbacks, which is what
    the standalone harness relies on.
    """
    if _HOST_BOUND[0]:
        return
    mod = sys.modules.get(type(app).__module__)
    if mod is not None:
        g = globals()
        for name in ("LBL_W", "LBL_W2", "PAD_ROW", "PAD_GROUP", "PAD_TIGHT",
                     "PAD_X", "PAD_X_TIGHT", "MUTED", "Tooltip"):
            if hasattr(mod, name):
                g[name] = getattr(mod, name)
    _HOST_BOUND[0] = True


# ---------------------------------------------------------------------------
# Settings defaults -- the app patch folds these in under the "# b keys" marker.
# Every key is versioned with the fr_ prefix so nothing collides with the
# frozen v1.4.8 settings names.
# ---------------------------------------------------------------------------
SETTINGS_DEFAULTS = {
    "fr_view": "plot",              # centre view the app opens in
    "fr_anvil": "diamond",
    # The anvil index his program recomputes from each spectrum's own
    # pressure (_load_into_state_body, 13091-13097): the single-oscillator
    # model with the Eremets shift, which is what 'eremets' names here.
    # 2.4030 at 3.71 GPa, his number.  A settings file that already carries
    # fr_diamond_model keeps whatever it holds.
    "fr_diamond_model": "eremets",  # constant|cauchy|oscillator|eremets
    "fr_medium": "Other",          # his default: manual medium
    "fr_medium_n": 1.2,            # his n_medium default
    "fr_layer2_on": False,
    "fr_layer2": "KCl",
    "fr_n_layer2": 1.0,            # his n_layer2 default, on its hidden row
    "fr_sample_name": "",          # "" = the plain word "sample"
    "fr_n_sample": 1.50,           # his defaults, verbatim
    "fr_d1_um": 0.0,
    "fr_t_um": 20.0,
    "fr_d2_um": 0.0,
    "fr_lock_total": False,
    "fr_fine_step": False,
    "fr_wl_min": 600.0,
    "fr_wl_max": 800.0,
    "fr_wl_overrides": {},          # input folder -> [wl_min, wl_max]
    "fr_nt_min_um": 8.0,
    "fr_nt_max_um": 300.0,
    "fr_pvalue_max": 1e-4,
    "fr_agree_tol": 0.15,
    "fr_halfwidth_um": 3.0,
    # Band D resolution floor: the band half-width never falls below the Hann
    # resolution.  His module constant, and a settings key here so a Run and
    # the exported CSVs honour the tick the workbench shows.
    "fr_band_floor": True,
    "fr_lowpass_on": True,         # legacy scalars (pre-R7): kept only
    "fr_lp_cutoff_um": 15.0,       #   as the per-channel migration seed
    "fr_lp_bg_on": None,           # per-channel low-pass; None = seed
    "fr_lp_bg_um": None,           #   from the legacy scalar pair once
    "fr_lp_s_on": None,
    "fr_lp_s_um": None,
    # The low-pass EDGE, per channel (R15-D).  tanh at 2.0 um is the shape
    # and width the vendored core has always used, so a settings file
    # without these keys draws and cleans exactly as it did.
    "fr_lp_bg_shape": "tanh",      # tanh|erf|hard
    "fr_lp_s_shape": "tanh",
    "fr_lp_bg_roll": 2.0,          # roll-off width in n*t um
    "fr_lp_s_roll": 2.0,
    # Free-text material names.  They name the rows, the schematic headers
    # and the series materials seed; the MODEL a name is solved under is
    # still the Medium / Layer 2 dropdown beside it.
    "fr_medium_name": "",          # "" = the medium model's own name
    "fr_layer2_name": "",          # "" = the Layer 2 model's own name
    "fr_y_lo": "",                 # FFT panels' shared y range; "" = auto
    "fr_y_hi": "",
    "fr_stem_cmap": "okabeito",    # qualitative palette for the model stems
    "fr_stem_skip_faint": False,   # drop the palette's palest colours
    "fr_notch_fine": False,        # notch-width spinboxes step at /10
    "fr_fit_mode": "distinct",      # distinct|shared
    "fr_suppress_report": False,    # keep the fringe report out of the log
    "fr_width_migrated": False,
    "fr_popout_geom": "",
}

# ---------------------------------------------------------------------------
# Phase C settings -- the app patch folds these in under the "# c keys" marker,
# the same way the "# b keys" block folds in SETTINGS_DEFAULTS.  Kept apart so
# a settings file written by a v1.4.9 build without the series level still
# reads, and so the two markers stay independently greppable.
# ---------------------------------------------------------------------------
C_SETTINGS_DEFAULTS = {
    # {DAC}_{Sample} -> {"pressures": [...], "path": str, "saved": iso}
    # Written by Data > Traces > Decompression list, read back on every
    # _build_trace_checks so a reload re-applies the same branches.
    "fr_dlists": {},
    "fr_msv_errors": False,         # multiscale-variance error bars (costly)
    "fr_res_models": [],            # alternative medium models drawn as curves
    "fr_res_layer2": [],            # the same set for the LAYER 2 material
    "fr_res_recorded": True,        # draw the points as recorded (his default)
    "fr_res_cmap": "tab10",         # overlay colourway (his default)
    "fr_res_skip_faint": False,     # drop the palette's palest colours
    "fr_res_eos": {},               # panel -> [EoS name, ...]
    "fr_res_anchors": {},           # "panel|eos" -> recorded point label
    "fr_res_geom": "",              # the results window's last geometry
    # The side guide beside the FFT view. Open on a first run: the
    # workbench is the one surface in the program whose mouse grammar
    # cannot be guessed from its controls, so the explanation ships showing
    # and the user turns it off, not the other way round.
    "fr_guide_open": True,
    "fr_guide_w": 0,                # px; 0 = the default share of the pane
}

# The guide beside the FFT view is the shipped workbench view, read from the
# content tree at open time so the panel and the Guide dropdown can never
# drift apart.  GUIDE_FALLBACK is what shows when that tree is not installed.
GUIDE_FILE = "30_fringe_workbench.md"
GUIDE_MIN_W = 34                 # ems: below this the text stops being prose
GUIDE_DEF_W = 44                 # ems: the width it opens at
# The FFT canvas has a floor too, and it outranks the guide's.  One pixel of
# a 160 px canvas is half a micron of n*t: nobody can aim a click at a peak
# on that, the schematic headers break mid-word, and the annotation boxes
# spill past the axes.  When the centre cannot hold this AND the prose floor
# at once, the prose is the one that steps aside.
PLOT_MIN_W = 42                  # ems: the narrowest FFT canvas worth having
SCHEM_PT = 7.0                   # the cell schematic's type size, and the
SCHEM_PT_MIN = 5.0               # smallest it may be shrunk to to fit
SCHEM_WRAP_AT = 6.0 / SCHEM_PT   # below this share of the room the stack
                                 # reads over two lines instead of shrinking
HEAD_PT = 10.0                   # the panel's own name line, and the
HEAD_PT_MIN = 8.0                # smallest it may be shrunk to to fit
DLG_MAX_FRAC = 0.9               # a workbench window may not outgrow this
                                 # share of the screen

# ---------------------------------------------------------------------------
# The 2x2 figure's own margins, in POINTS.
#
# `tight_layout` cannot lay this figure out: every FFT panel carries a
# `twinx` for the removed fraction and every spectra panel a
# `secondary_xaxis` for the wavelength scale, so matplotlib declares the
# figure incompatible, warns once per draw and leaves the DEFAULT
# subplotpars in place -- left 0.125, right 0.9, hspace 0.55.  Measured on
# the real canvas that spent 148 px between the two rows and put the FFT
# panels' "removed fraction" scale on top of the spectra panels' tick
# labels, while the panels themselves held 41% of the figure.
#
# So the grid is placed from measurement instead.  Each number is what the
# furniture on that side actually needs, taken off the rendered figure at
# both window sizes: the panel fonts are fixed sizes, so the need is a
# fixed number of points at any canvas size or DPI.
#   left   y label + tick labels of the FFT column
#   right  the spectra column's last wavelength tick, half outside
#   top    the spectra title, its pad, and the wavelength axis over it
#   bottom the x label + tick labels of the lower row
#   wgap   the FFT panel's removed-fraction scale, then the spectra
#          panel's own tick labels, then air
#   hgap   the upper row's x furniture, then the lower row's title block
GRID_PT = {"left": 46.0, "right": 13.0, "top": 50.0, "bottom": 36.0,
           "wgap": 59.0, "hgap": 84.0}
# ... but the panels always keep this share of the canvas: on a pane
# dragged very narrow the margins shrink together rather than eat the plot.
GRID_MIN_AXES = 0.30

# ---------------------------------------------------------------------------
# Series continuity on disk.  Matthew's writer's schema and file name, so a
# folder written by either program reads in the other.
# ---------------------------------------------------------------------------
SERIES_SCHEMA = "fft_gui_series/v2"
SERIES_FILE = "series_continuity.json"
SERIES_STAMP = "series_continuity_%s.json"     # timestamped session copies
SESSION_STAMP = "session_%s.json"              # his single-point snapshot
NOTCH_FILE = "notch_overrides.csv"

# ---------------------------------------------------------------------------
# Results vs pressure: Matthew's 2x3 grid.  Indices on top, the thickness each
# one divides into underneath it, so a column reads as one physical quantity.
#   (grid position, point key, axis label, EoS panel?)
# ---------------------------------------------------------------------------
RES_PANELS = (
    ("n_s", (0, 0), "$n_s$  (sample)", False),
    ("n_medium", (0, 1), "$n_{medium}$", False),
    ("n_layer2", (0, 2), "$n_{layer2}$", False),
    ("t_s", (1, 0), "$t_s$  ($\\mu$m)", True),
    ("L", (1, 1), "$L = d_1{+}t{+}d_2$  ($\\mu$m)", True),
    ("t_layer2", (1, 2), "$t_{layer2} = d_1{+}d_2$  ($\\mu$m)", True),
)
# His Row-1 wavelength reference lines (defringe_dac 7813-7818): 580, 640,
# 766 and 905 nm with the nm printed at the top.  The colours are DERIVED
# from his four (#FFC200 / #FF2000 / darkred / #550000) rather than copied
# as literals -- the darkest two are invisible on a dark ground, so the
# panel lifts them toward the page ink (rule 65, _lift_for_page).
REF_WL_NM = ((580, "#FFC200"), (640, "#FF2000"), (766, "#8B0000"),
             (905, "#550000"))
RES_EOS_PANELS = ("t_s", "L", "t_layer2")
# His key for "the curve as recorded", the one an EoS anchor is normally
# taken from (defringe_dac _RES_RECORDED).  It travels in the series file's
# anchor entries so a file of his keeps saying which curve it meant.
RES_RECORDED = "__recorded__"
# His thickness spinbox top (defringe_dac: to=100000).  A micron figure
# above this is not a DAC gap, so the box says so at the same place his
# does.
THICK_MAX_UM = 100000.0
RES_MS = 34.0            # recorded-point marker area (pt^2)
RES_MS_D = 46.0          # the open x is drawn a little larger to read as one

# Media that carry a real n(P) model, so "re-solve under this instead" means
# something.  Anything else in MEDIUM_CHOICES has no curve to offer.
RES_MODEL_CHOICES = ("Ar", "ArChen", "ArChenD", "air")

RESULTS_GUIDE = [
    ("h", "WHAT THE SIX PANELS ARE"),
    ("b", "One column per physical quantity. The refractive index is "
          "on top, and the thickness it divides into is underneath. "
          "n_s over t_s is the sample. n_medium over L is the whole "
          "gap. n_layer2 over t_layer2 is the medium alone (d1 + d2)."),
    ("b", "X is pressure in GPa, from each trace's own parsed value."),
    ("h", "THE POINTS"),
    ("m", "  filled circle   compression"),
    ("m", "  open x          decompression"),
    ("b", "The branch is read live from the main window. It reads the "
          "auto-detected D tags, the D boxes in Data > Traces, and any "
          "decompression list you have loaded. Applying a list moves the "
          "markers here too. The recorded points stand."),
    ("b", "Colour is the medium the point was solved under, so a series "
          "that leaked argon to air shows both."),
    ("h", "MODEL OVERLAYS"),
    ("b", "Tick a medium. Every recorded point is solved again under "
          "that model's n(P) at its own pressure. The re-solve is "
          "exact. The three measured optical paths are what was "
          "recorded, and the solve conserves the sample path. "
          "Re-solving under the recorded model reproduces the recorded "
          "numbers to the last bit."),
    ("h", "HOVER"),
    ("b", "The pointer near a marker reads it out: its pressure, its "
          "value, and the medium it was solved under. Every curve under "
          "the pointer answers at once, and the boxes stack apart."),
    ("h", "RIGHT-CLICK"),
    ("b", "Right-click a point to take it off the series. On the point "
          "that is loaded, the same menu also puts the inputs back to "
          "their shipped values. The drop is in memory; the folder's "
          "continuity file keeps the point until a save rewrites it."),
    ("h", "EOS CURVES"),
    ("b", "The thickness panels take dashed equation-of-state curves, "
          "Vinet or Birch-Murnaghan 3rd order. They are scaled as the "
          "cube root of the volume ratio. A curve passes through the "
          "lowest-pressure recorded point by default. The right-click "
          "menu anchors it on the point under the pointer, and releases "
          "it back to automatic."),
    ("h", "ERROR BARS"),
    ("b", "Multiscale-variance bars are off by default because each point "
          "costs about 35 ms to estimate. Turned on in the Series card, "
          "they are computed once per point and cached."),
]

# ---------------------------------------------------------------------------
# Interaction constants -- Matthew's numbers, kept verbatim.
# ---------------------------------------------------------------------------
CLICK_TOL_UM = 0.8       # snap radius (um of n*t) for click-to-toggle
GRAB_TOL_UM = 1.6        # grab radius for a role glyph / the low-pass line
DEBOUNCE_MS = 110        # live redraw debounce while dragging
DIRTY_CAP = 8            # leave-guard itemisation cap
# The low-pass cutoff's range, his (defringe_dac 15724 and 14044): the spinbox
# and the drag clamp share it, so a dragged edge can never leave a value the
# box cannot hold, and neither can reach past the n*t the search band allows.
LP_MIN_UM = 1.0
LP_MAX_UM = 200.0
# Per-notch half-width range, his (0.5 to 20 um of +-reach).
NOTCH_HW_MIN_UM = 0.5
NOTCH_HW_MAX_UM = 20.0

# Matthew's two radii are in DATA units, and his window put 0.8 um at a
# comfortable handful of pixels.  Embedded in SPARTA the same axes are a
# fraction of that width -- measured on the real app with the guide pane
# open, 0.8 um came out at 1.5 px and 1.6 um at 3.0 px, so a click had to
# land inside a pixel or two of the marker or it did nothing.  That is why
# the grammar read as missing.  The radius is therefore a SCREEN distance
# with his micron value as the floor: the feel is his at any window size,
# DPI or zoom level, and it never gets tighter than he specified.
PICK_PX = 9              # click-to-notch reach, in screen pixels
GRAB_PX = 15             # role glyph / low-pass line grab reach, in pixels
TOL_CAP_FRAC = 0.06      # ... but never more than this share of the x span
HOVER_MS = 4500          # how long a status message holds the hint bar

CHANNELS = ("Background", "Sample")
CHAN_KEY = {"Background": "bg_c", "Sample": "samp_c"}

# The _group titles the workbench owns, spelled as the honesty gate and the
# guide's headings spell them, in the order they stand in the column.
FRINGE_SECTIONS = ("Stack", "Session", "Pressure point", "Detection",
                   "FFT removal", "Refractive Index from Intensity",
                   "Panels")

# Which INFO_CONTENT block(s) each card's [?] shows.  The content keys keep
# their pre-R7 names so the math text needs no rewrite; the KEYS here are
# the live section titles, in FRINGE_SECTIONS order, because _build_cards
# looks each one up in the app's collapsible register and _add_info_btn
# quietly does nothing for a title that is not there.
#
# "Detection" is a card again (R14): R10 had folded its gates into a
# Panels > Detection... pop-out and parked the math text on FFT removal.
# The gates stand in the column now, so the detection block goes back to
# the card that carries them and FFT removal keeps the notch block alone.
INFO_FOR = {"Stack": ("Stack", "Roles & solve"),
            "Session": ("Series",),
            "Detection": ("Detection",),
            "FFT removal": ("Notches",),
            "Refractive Index from Intensity": ("Intensity",)}

# Two stacked rows of action buttons at PAD_TIGHT sat 1 px apart, which
# reads as one slab of chrome ("buttons too close together", R14 round 3).
# This is the gutter between them, and between a row of buttons and the
# checkbox or label under it.
PAD_BTNROW = (6, 0)

# The Stack card's own label gutter.  Wider than LBL_W because its thickness
# rows name the role as well as the symbol ("Medium d1 (um)"); one value for
# the whole card so the input and Solved columns line up down it (rule 9's
# "genuinely long labels carry their own width").
STACK_LBL_W = 19

# The Stack card's two spinbox paces, his (9567-9578): a thickness steps by
# a micron, a refractive index by a tenth.  "fine steps" divides whichever
# one the box carries by ten, so it reaches every numeric box in the window.
IDX_STEP = 0.1
THICK_STEP = 1.0

# Role keys, their display names and which panel carries them.  A = sample,
# C = sample-diamond (loaded sample), iii = medium etalon -- the three optical
# paths fringe_optics.solve_paths inverts.
ROLES = ("sample", "sampledia", "mediumdia")
ROLE_DISP = {"sample": "Sample", "sampledia": "Sample diamonds",
             "mediumdia": "Medium diamond"}
ROLE_PANEL = {"sample": "Sample", "sampledia": "Sample",
              "mediumdia": "Background"}
ROLE_Y = {"sample": 0.94, "sampledia": 0.94, "mediumdia": 0.94}
# How far below a glyph a press still counts as reaching for it, in axes
# fraction.  The glyphs live along the top of their panel; a press at the
# right n*t but lower down used to fall straight through to the notch
# toggle and leave a notch nobody asked for.
ROLE_GRAB_DY = 0.34

# Role glyphs: a 2:1 rectangle, a half-filled diamond, a hollow diamond.
RECT_PATH = _MPath([(-1.0, -0.5), (1.0, -0.5), (1.0, 0.5), (-1.0, 0.5),
                    (-1.0, -0.5)],
                   [_MPath.MOVETO, _MPath.LINETO, _MPath.LINETO,
                    _MPath.LINETO, _MPath.CLOSEPOLY])
ROLE_MARK = {"sample": (RECT_PATH, "full"),
             "sampledia": ("D", "left"),
             "mediumdia": ("D", "none")}
ROLE_MS = 13             # glyph size in points, as drawn
# Half-width of each glyph in units of the drawn marker size.  Matplotlib
# normalises a custom marker path to a half-extent of 0.5 on its largest
# coordinate, so RECT_PATH (+-1 in x) draws one marker-size wide -- half-width
# 0.5 -- while a "D" is the unit square turned 45 degrees, half-diagonal
# sqrt(2)/2.  Used by the overlap test and the stagger drop.
ROLE_HALFW = {"sample": 0.5, "sampledia": 0.70711, "mediumdia": 0.70711}
# Where the rectangle goes when the two Sample glyphs collide (his _Y_LOW,
# 12796-12803): far enough down to read as its own row, never so far that
# it leaves the grabbable band.
ROLE_Y_LOW_MIN = 0.42

# Gaussian refine, his numbers verbatim (defringe_dac.py 12310-12507).
# The window is in ABSOLUTE micron, not FFT bins: the transform is coarse
# (about 1 um per bin over 600-800 nm), so a bin-count window balloons over
# the neighbouring fringe peaks.  The baseline is the whole curve's 5th
# percentile held FIXED, because packed fringes have no clean local floor --
# a fitted floor absorbs the neighbours' tails and drifts.
REFINE_WIN_UM = 3.0        # single-peak window half-width
PAIR_REACH_UM = 4.0        # per-anchor reach of the joint Sample window
BASELINE_PCTL = 5.0        # the fixed spectral floor
SHOULDER_AMP_FRAC = 0.15   # a residual bump this tall counts as a shoulder
SHOULDER_SEP_BINS = 0.5    # ...at this separation from the apex, in samples

# Auto-seed: how far the stack's predicted line may sit from a detected peak
# and still claim it.  The Stack boxes are a nominal guess -- the shipped
# defaults are 5 / 20 / 5 um -- so on a real trace the prediction is routinely
# a fifth of its own value out (on the demo series the worst miss is 28% of
# the predicted path).  The fraction carries that drift; the floor keeps a
# short path from having a window too narrow to catch anything.  Only the
# strongest few peaks are considered, which bounds the ordered-pair search.
SEED_TOL_FRAC = 0.35
SEED_TOL_UM = 4.0
SEED_MAX_CAND = 12

# State indicators (the two-level memory-vs-disk model).
IND_SAVED = "✓"     # saved and identical to disk
IND_DIRTY = "•"     # changed in memory
IND_NONE = "⌀"      # nothing recorded

# The pressure dropdown's per-point markers, against the folder's continuity
# file (his _PLABEL_MARKS, 9208).  Display only: state is keyed by the PLAIN
# label, and every read of the dropdown normalises through _plain_label first,
# so a marker can never reach a recorded row or a written file.
PLABEL_MARKS = (" ✓", " •")

# Numeric input fields, spelled as Matthew's writer spells them so a file
# either program writes reads in the other, mapped to the row labels our
# Stack card shows.  n anvils and n layer 2 are written for his reader and
# never restored: both are functions of the point's own pressure, so a value
# inherited from another point would be wrong (his _model_owned_nums).
NUM_KEYS = ("n_sample", "n_medium", "d1_um", "t_um", "d2_um")
NUM_DERIVED = ("n_diamond", "n_layer2")
NUM_DISP = {"n_sample": "n sample", "n_medium": "n medium",
            "d1_um": "d1", "t_um": "t", "d2_um": "d2",
            "n_diamond": "n anvils", "n_layer2": "n layer 2"}
NUM_EPS = 1e-9           # his _NUM_EPS: '0.0' and '0' are the same number

# Every block one point's stored inputs carry.  Anything else in a file this
# program did not write is kept aside and written back out untouched, so a
# round trip through here never costs his GUI a field it uses.
INPUT_KEYS = ("nums", "notch", "fitn", "roles", "solved", "lowpass",
              "lp_cutoff_um", "lp_rolloff_um", "lp_edge_shape",
              "nt_min_um", "nt_max_um", "wl_min_nm",
              "wl_max_nm", "halfwidth_um", "fit_mode")

# The fundamental has three states, his (13536-13547): None is auto, the
# brightest detected peak; a float is a peak the reader pinned; this sentinel
# is "no fundamental on this channel", which auto can never mean.  It travels
# as the string his files carry, through the session payload and the
# continuity file alike.
FUND_NONE = "none"

# The low-pass edge, as the two shape dropdowns spell it.
LP_SHAPE_LABELS = {"tanh": "Tanh", "erf": "Error function", "hard": "Hard"}

# The n*t grid the removed-fraction preview curve is read on.  Fine enough
# that a 0.5 um notch still draws as a notch across the whole panel.
REMOVED_CURVE_PTS = 480

# Series-wide material seed keys.  They live once in the continuity file's
# top-level materials block and are stripped from every per-point entry, so
# two copies of one seed can never disagree (his _MATERIAL_KEYS, 9234).
MATERIAL_KEYS = ("names", "layer2", "layer2_model", "medium_model",
                 "diamond_model", "rect_fit_mode")

# Which Sample fit mode his rect_fit_mode names: 'peak' fits the two Sample
# roles independently, 'shoulder' ties them to one hump.
RECT_FIT_MODES = {"peak": "distinct", "shoulder": "shared"}
FIT_MODE_RECT = {"distinct": "peak", "shared": "shoulder"}

# Okabe-Ito: used for the model stems in EVERY theme, not only Colorblind
# Safe.  The stems are the one place on the figure where colour carries an
# identity (which interface pair), so the palette that survives every kind of
# colour vision is the right default (DESIGN_RULES rule 48).
OKABE_ITO = ("#0072B2", "#D55E00", "#E69F00", "#009E73", "#CC79A7",
             "#56B4E9", "#F0E442")
STEM_DASHES = ("-", "--", "-.", ":")     # High Contrast carries identity here

MEDIUM_CHOICES = ("Ar", "ArChen", "ArChenD", "KCl", "LiF", "air", "Other")
MEDIUM_LABELS = {"Ar": "Argon (Dewaele)", "ArChen": "Argon (Chen)",
                 "ArChenD": "Argon (Chen / Dewaele rho)", "KCl": "KCl",
                 "LiF": "LiF", "air": "Air (leaked cell)",
                 "Other": "Other (type the index)"}
DIAMOND_LABELS = {"constant": "Constant 2.4168", "cauchy": "Cauchy dispersion",
                  "oscillator": "Sellmeier oscillator",
                  "eremets": "Eremets n(P)"}

# View > Refractive index models: his notebook, tab for tab (_show_model_info,
# 15116-15120).  The keys are fringe_materials.MODEL_DOCS keys; the captions
# are the ones the Medium dropdown already uses, so one material is named the
# same in both places.
MODEL_DOC_TABS = (("diamond", "Diamond (anvils)"),
                  ("Ar", "Argon (Dewaele)"),
                  ("ArChen", "Argon (Chen)"),
                  ("ArChenD", "Argon (Chen / Dewaele rho)"))
FIT_MODES = (("distinct", "Distinct"), ("shared", "Shared"))

# ---------------------------------------------------------------------------
# Pop-out helper-guide copy -- the "Reading the FFT view" and "What you do with
# the mouse" blocks of docs/guide_content/30_fringe_workbench.md, trimmed to
# the Guide-card shape (DESIGN_RULES rule 21).  Kept in step with that file by
# hand; the file is the source of the wording.
# ---------------------------------------------------------------------------
GUIDE_FALLBACK = [
    ("h", "READING THE FFT VIEW"),
    ("b", "Two stacked panels, Background on top and Sample below. Both "
          "channels show at once."),
    ("b", "X axis: n*t in micron. It is the optical path of the "
          "interfering layer. Fringe frequency and n*t are related by "
          "f = 2 n*t."),
    ("b", "Y axis: the measured |FFT| amplitude on a physical modulation "
          "scale (V_m), so amplitudes are comparable between channels and "
          "between pressures."),
    ("b", "Model stems mark where the current stack model predicts a "
          "fringe. The m = 2 and m = 3 Airy harmonics are drawn "
          "dashed. A real interference pattern puts power at integer "
          "multiples of its fundamental. Seeing the harmonics is the "
          "fastest confirmation that a peak is a fringe."),
    ("b", "Notch bands are shaded over the region each notch removes. "
          "The right-hand axis reads the fraction of the signal they "
          "take out."),
    ("b", "The dashed low-pass line sets the cutoff above which everything "
          "is treated as noise. Drag it and the view follows. Its edge "
          "shape and roll-off width sit beside the cutoff. The dotted "
          "right-hand curve traces the mask they make."),
    ("b", "A toolbar under the panels pans, zooms and saves. The "
          "workbench's own gestures rest while a toolbar mode is armed."),
    ("h", "PEAK MARKERS"),
    ("m", "  triangle   the fundamental"),
    ("m", "  circle     found automatically"),
    ("m", "  diamond    placed by you"),
    ("m", "  hollow     present but not ticked"),
    ("h", "WHAT YOU DO WITH THE MOUSE"),
    ("b", "Left-click within 0.8 um of a feature toggles a notch there."),
    ("b", "Right-click pins that peak as the fundamental; right-click again "
          "to reset the pin. The same menu hands the peak to a role glyph, "
          "which is the quickest way to place one exactly."),
    ("b", "The three role glyphs start out parked on the workbench's best "
          "guess: the stack's predicted paths, snapped to the nearest "
          "detected peak. They are a starting point."),
    ("b", "Role glyphs drag freely along the axis. The drop point places "
          "the glyph and solves the cell. The solved values go back into "
          "the stack boxes. Fit peaks re-detects all three from the "
          "model: Distinct fits each Sample role independently, Shared "
          "fits them as one hump. The tool keeps the fitted offsets "
          "ordered, so the solve gets a physical ordering."),
    ("b", "A glyph the tool placed carries a solid guide line and a "
          "fitted Gaussian. A glyph you placed carries a dashed guide in "
          "its own fill. A coincident pair steps apart onto two rows."),
]

# ---------------------------------------------------------------------------
# The Info pop-out (Panels > Info) -- his View > Info panel: the marker
# key, the mouse grammar, and where the files go.
# ---------------------------------------------------------------------------
WB_INFO = [
    ("h", "MARKER SHAPES"),
    ("m", "      rectangle       Sample  (A = n_s t)"),
    ("m", "      half diamond    Sample diamonds  (C)"),
    ("m", "      hollow diamond  Medium diamond  (iii)"),
    ("m", "      triangle        the fundamental peak"),
    ("m", "      circle          peak found automatically"),
    ("m", "      diamond         peak you added"),
    ("m", "      hollow          listed but unticked"),
    ("h", "THE MOUSE"),
    ("b", "Left-click a peak to notch it, or to take the notch "
          "away. Right-click a peak for its menu: pin it as the "
          "fundamental, clear the channel's fundamental, or hand the "
          "peak to a role glyph. Drag a glyph, or the dashed low-pass "
          "line, with the left button. The dotted right-hand curve "
          "follows a low-pass drag."),
    ("b", "The toolbar under the panels pans, zooms and saves. The "
          "workbench's own gestures stand down while a toolbar mode is "
          "armed."),
    ("h", "THE FUNDAMENTAL"),
    ("b", "Three states, in the notch list's Fundamental column. An "
          "empty column means the brightest detected peak. A filled "
          "radio is a peak you pinned. Clicking the filled one clears "
          "that channel, which the list says under the rows."),
    ("h", "FILES"),
    ("b", "Save session writes series_continuity.json beside the data, "
          "plus a timestamped copy. Export cleaned spectrum and Write "
          "notches file for batch land in the CSV folder. That folder "
          "is named at the bottom of the panel."),
]

# ---------------------------------------------------------------------------
# The [?] boxes -- the math behind each card, for the curious.
#
# One entry per card.  Content is sourced from the vendored fringe_* module
# docstrings (Matthew R. Diamond's defringe_dac.py port), citations included.
# A ("f", mathtext, plain) row renders as a typeset formula through the
# host's _mathtext_image and falls back to the plain form when mathtext is
# unavailable; the other tags are the guide renderer's own.  Headline
# formula first, prose after -- each box should be scannable.
# ---------------------------------------------------------------------------
INFO_TIP = ("This opens what the card computes: the formulas, the "
            "clamps and the citations, in a small window of its own.")

INFO_CONTENT = {
    "Stack": [
        ("b", "Five layers, four interfaces. Every PAIR of interfaces "
              "is a little etalon of its own. One sample therefore "
              "gives six lines."),
        ("h", "THE SIX LINES"),
        ("m", "      12  lower layer2      n_m d1"),
        ("m", "      23  sample            n_s t"),
        ("m", "      34  upper layer2      n_m d2"),
        ("m", "      13  layer2 + sample   n_m d1 + n_s t"),
        ("m", "      24  sample + layer2   n_s t + n_m d2"),
        ("m", "      14  the whole gap     n_m d1 + n_s t + n_m d2"),
        ("b", "Each line sits at its pair's optical path, which is what the "
              "coloured stems mark on the chart. The Background panel plays "
              "the same game with one line: the medium etalon at n_medium "
              "times L."),
        ("h", "THE AMPLITUDES"),
        ("f", r"$R_{dm}=\left(\frac{n_d-n_m}{n_d+n_m}\right)^{2}"
              r"\qquad R_{ms}=\left(\frac{n_m-n_s}{n_m+n_s}\right)^{2}$",
         "R_dm = ((n_d - n_m)/(n_d + n_m))^2,   "
         "R_ms = ((n_m - n_s)/(n_m + n_s))^2"),
        ("b", "Light loses a slice at every crossing, so the four interface "
              "intensities cascade:"),
        ("m", "      I1 = R_dm"),
        ("m", "      I2 = (1-R_dm)^2 R_ms"),
        ("m", "      I3 = (1-R_dm)^2 (1-R_ms)^2 R_ms"),
        ("m", "      I4 = (1-R_dm)^2 (1-R_ms)^4 R_dm"),
        ("f", r"$c_{ij} = 2\,s\,\sqrt{I_i\,I_j}$",
         "c_ij = 2 s sqrt(I_i I_j)"),
        ("b", "s is the Fresnel sign. Four pairs cross the middle "
              "reflection an odd number of times: 12, 13, 24 and 34. "
              "Those four flip sign when the sample's index climbs "
              "past layer 2's. The model keeps track of the sign for "
              "you."),
        ("b", "The short dashed stems are Airy harmonics. A real "
              "interference pattern also puts power at 2x and 3x its "
              "own path. The tool draws them at h(h/2) and h(h/2)^2 of "
              "the parent height."),
        ("h", "INDEX ORDERING"),
        ("b", "The sign of a reflection depends on whether the light "
              "crosses into a higher or a lower refractive index, and that "
              "sign sets the phase of each interference term. The n*t "
              "positions do not move either way, so the stems stand where "
              "they stood."),
        ("live", "index_ordering"),
        ("h", "SOURCES"),
        ("m", "      M. R. Diamond, defringe_dac.py (thin-film model)"),
        ("m", "      github.com/matthewrdiamond/"),
        ("m", "        DAC-Absorption-Fringe-Analysis (MIT, by permission)"),
        ("m", "      diamond n: Phillip & Taft (1964);"),
        ("m", "        Eggert, Goettel & Silvera, EPL 11, 775 (1990);"),
        ("m", "        Eremets et al., Int. J. High Press. Res. 9, 347"),
        ("m", "        (1992); Dewaele et al., PRB 77, 094106 (2008)"),
    ],
    "Detection": [
        ("f", r"$n{\cdot}t \;=\; f/2$", "n*t = f / 2"),
        ("b", "The chart is an FFT taken in WAVENUMBER. The tool lays "
              "the channel out on a uniform 1/lambda grid. It divides "
              "by a smooth 4th-order trend, because the lamp "
              "multiplies. It then mirror-pads and Hann-tapers the "
              "signal. A layer of optical path n*t modulates that "
              "signal as cos(4 pi n*t nu). The layer appears at "
              "frequency f = 2 n*t. The x axis is that frequency "
              "halved, in micron."),
        ("h", "THE TEST"),
        ("f", r"$g \;=\; \max_k P_k \,/\, \sum_k P_k$",
         "g = max(P_k) / sum(P_k)"),
        ("f", r"$p \;=\; \sum_{j=1}^{\lfloor 1/g\rfloor} (-1)^{j-1}"
              r"\binom{n}{j}\,(1-jg)^{n-1}$",
         "p = sum_{j=1..floor(1/g)} (-1)^(j-1) C(n,j) (1-jg)^(n-1)"),
        ("b", "Fisher's exact test asks how big the biggest periodogram peak "
              "is against everything else, under a white-noise null. Small p "
              "means the peak is unlikely under that null. A near-flat "
              "periodogram scores p = 1, and the tool skips it."),
        ("h", "THE VOTE"),
        ("b", "Three FFT windows run the test on their own stretch: narrow, "
              "wide and full. A window detects when its p clears the Fisher "
              "p gate. The tool accepts the fringe when at least TWO windows "
              "detect it. Those windows also agree on n*t within Agree tol, "
              "a relative fraction. The fit then runs in the narrow band."),
        ("h", "FFT RESOLUTION"),
        ("b", "The FFT is taken over the fit window in wavenumber, 1 over "
              "lambda. Its bin width sets the smallest separation in "
              "optical path n*t at which two peaks can be told apart:"),
        ("f", r"$n\,t\ \mathrm{bin}\;\approx\;"
              r"1\,/\,\left(2\,\Delta(1/\lambda)\right)$",
         "n*t bin ~ 1 / (2 d(1/lambda))"),
        ("b", "Peaks closer together than that bin are not resolvable. The "
              "line below is read from the window set on this card, so it "
              "follows it."),
        ("live", "fft_bin"),
        ("h", "SOURCES"),
        ("m", "      Fisher (1929); Wichert et al. (2004),"),
        ("m", "        Bioinformatics 20(1):5-20, eq. (6)"),
        ("m", "      M. R. Diamond, defringe_dac.py (detection pipeline)"),
    ],
    "Notches": [
        ("f", r"$\sigma_f \;=\; 2000 \cdot hw_{\mu m}$",
         "sigma_f = 2000 * halfwidth_um"),
        ("b", "A notch is a Gaussian bite out of the FFT mask. The "
              "tool attenuates each centre, and its mirror twin, by "
              "the Gaussian factor exp(-(f-f_c)^2 / 2 sigma_f^2). The "
              "n*t axis is f/2000, so a half-width of hw micron is "
              "sigma_f = 2000 hw at EVERY centre. That is one absolute "
              "width wherever the fringe sits. It matches real fringe "
              "peaks, whose width barely changes across n*t."),
        ("b", "Before any of that, the tool mirror-pads the signal. It "
              "reflects half the length onto each end. The FFT then sees a "
              "periodic signal, and the notch stays clean at the edges."),
        ("h", "THE LOW-PASS"),
        ("f", r"$M(f) \;=\; \tfrac{1}{2}\left(1-\tanh\frac{f-f_{cut}}{r}"
              r"\right)$",
         "M(f) = (1/2) (1 - tanh((f - f_cut) / r))"),
        ("b", "The dashed line multiplies a soft shoulder into the same "
              "mask. Everything past the cut counts as noise."),
        ("h", "THE EDGE"),
        ("b", "The shoulder has a shape and a width, per channel. r is the "
              "roll-off width, in the same micron of n*t as the cutoff."),
        ("m", "      tanh    the shipped shape, above"),
        ("m", "      erf     the same width, a touch steeper"),
        ("m", "      hard    a step at the cutoff itself"),
        ("f", r"$M(f) \;=\; \tfrac{1}{2}\left(1-\mathrm{erf}"
              r"\frac{f-f_{cut}}{r}\right)$",
         "M(f) = (1/2) (1 - erf((f - f_cut) / r))"),
        ("b", "One roll-off width past the cutoff, tanh keeps 12% of the "
              "signal and the error function 8%. A hard edge reads 0 there "
              "and rings, because the mirror-padded inverse FFT of a step "
              "is a sinc. tanh at 2 micron is the shipped pair."),
        ("b", "The right-hand axis reads the fraction of the signal "
              "all the bites remove together. The dotted curve is that same "
              "mask along the axis, so it shows WHERE the removal happens. "
              "Removing half the signal to kill one ripple is usually the "
              "wrong trade. These are the numbers that say so."),
        ("h", "WHAT df APPLIES"),
        ("b", "The df switch, a Run and Export data clean each trace at "
              "that trace's own list: its centres, its per-centre "
              "half-widths and its low-pass. The df switch changes the "
              "plot only, and the Defringed data row in Export > Data "
              "files decides whether a Run and an Export add the "
              "cleaned columns. A centre picked here is applied as "
              "picked. "
              "The Fisher p gate stays with the "
              "detector, which supplies the fundamental and the n*t the "
              "log reports."),
        ("b", "A trace this panel has yet to see cleans at the fringe the "
              "detector finds. The gates in the Detection card rule that "
              "pass. A session that leaves this panel closed reads those "
              "gates from the settings file. Every trace then cleans that "
              "way."),
        ("h", "SOURCES"),
        ("m", "      M. R. Diamond, defringe_dac.py"),
        ("m", "        (defringe_fft_notch, band diagnostics)"),
    ],
    "Intensity": [
        ("h", "READING n OFF AN AMPLITUDE"),
        ("f", r"$V \;=\; 2R \qquad R = \left(\frac{n_d-n_s}{n_d+n_s}\\right)^{2}$",
         "V = 2R,   R = ((n_d - n_s)/(n_d + n_s))^2"),
        ("f", r"$n_s \;=\; n_d\,\frac{1-\sqrt{V/2}}{1+\\sqrt{V/2}}$",
         "n_s = n_d (1 - sqrt(V/2)) / (1 + sqrt(V/2))"),
        ("b", "A fringe's amplitude is set by how strongly its two "
              "faces reflect. For a low-finesse etalon between equal "
              "mirrors, that is Fresnel's formula run forward. Compute "
              "fits runs it backward. It fits the fringe's amplitude "
              "V, then inverts for the index that would reflect that "
              "much."),
        ("h", "THE TWO ESTIMATES"),
        ("b", "The cosine fit follows the fringe point by point. It "
              "reads V off the best-fitting cos(4 pi n t / lambda + "
              "phi). The band integral sums the FFT power in a band "
              "around the peak. The band integral is steadier when the "
              "fringe drifts, and it is the blue curves' source. Each "
              "estimator runs over several spectral windows: full, "
              "wide, narrow, fine. fine is the quoted one."),
        ("h", "BAND \u0394 RESOLUTION FLOOR"),
        ("b", "The band integral holds its integration band at the FFT main "
              "lobe or wider, about 2 bins. Only V_band moves when you "
              "toggle it. The notches, the cleaning and the shaded windows "
              "hold."),
        ("h", "SOURCES"),
        ("m", "      M. R. Diamond, defringe_dac.py (fit_signal_*,"),
        ("m", "        band_amp, fresnel_n_from_V)"),
    ],
    "Roles & solve": [
        ("h", "THE THREE PATHS"),
        ("f", r"$A = n_s t \qquad C = n_{l2}(d_1{+}d_2) + n_s t"
              r"\qquad iii = n_m L$",
         "A = n_s t,   C = n_l2 (d1+d2) + n_s t,   iii = n_m L"),
        ("b", "The rectangle is A, light through the sample alone. The "
              "half-filled diamond is C, sample plus the medium above "
              "and below it. The hollow diamond is iii, the whole gap "
              "L = d1 + t + d2 seen through the medium. Three measured "
              "paths and two known indices are enough to solve."),
        ("h", "THE SOLVE"),
        ("f", r"$L = \frac{iii}{n_m} \quad t_{l2} = \frac{C-A}{n_{l2}}"
              r" \quad t_s = L - t_{l2} \quad n_s = \frac{A}{t_s}$",
         "L = iii/n_m,   t_l2 = (C-A)/n_l2,   t_s = L - t_l2,   "
         "n_s = A/t_s"),
        ("b", "Closed form: four lines of algebra, run in that order."),
        ("h", "THE FIT"),
        ("b", "A drag drops the glyph where you release it, marks that "
              "role by hand, and solves. Fit peaks puts every role back "
              "on automatic and seeds from the stack. It then refines "
              "each one with a Gaussian. The window is +/- 3 um around "
              "the nearest detected peak. The baseline is fixed at the "
              "5th percentile of the curve. Shared mode fits the "
              "Sample pair jointly, with one width and an ordered "
              "separation."),
        ("h", "THE CLAMPS"),
        ("b", "The glyphs can land somewhere unphysical. The solve then "
              "clamps as an A-CONSERVING cascade. t_layer2 below zero is "
              "floored, and t_s is recomputed. t_s below zero is floored. A "
              "zero-thickness sample loses its path. n_s below 1 is floored "
              "with t_s = A/n_s, so the measured sample path A = n_s t_s "
              "survives the clamp. That conservation makes the Series card's "
              "re-solve exact later."),
        ("h", "THE VISIBILITY"),
        ("f", r"$R = \left(\frac{n_d-n_s}{n_d+n_s}\right)^{2}"
              r"\qquad V = 2R$",
         "R = ((n_d - n_s)/(n_d + n_s))^2,   V = 2R"),
        ("f", r"$n_s \;=\; n_d\,\frac{1-\sqrt{V/2}}{1+\sqrt{V/2}}$",
         "n_s = n_d (1 - sqrt(V/2)) / (1 + sqrt(V/2))"),
        ("b", "Fresnel, low-finesse, equal mirrors: V sets the stem "
              "heights, and run backwards it reads a refractive index "
              "straight off a peak's amplitude."),
        ("h", "SOURCES"),
        ("m", "      M. R. Diamond, defringe_dac.py"),
        ("m", "        (fresnel_V, solve_paths and the clamp cascade)"),
    ],
    "Series": [
        ("h", "THE RE-SOLVE"),
        ("b", "A recorded point stores the MEASUREMENT: the three "
              "paths A, C and iii. It also stores the two indices the "
              "solve ran at. The solve conserves A, so feeding the "
              "recorded indices back reproduces the recorded numbers "
              "to the last bit. Feeding another medium's n(P) gives "
              "the answer under that model. It is exact, so any "
              "difference you see is the model."),
        ("h", "EOS CURVES"),
        ("f", r"$t(P) \;=\; t_a\left(\frac{V(P)}{V(P_a)}\right)^{1/3}$",
         "t(P) = t_a * (V(P) / V(P_a))^(1/3)"),
        ("b", "A thickness shrinks as the cube root of the volume "
              "ratio. Each equation of state draws a dashed curve "
              "through one anchor point. The two are Vinet and "
              "3rd-order Birch-Murnaghan. The anchor is the "
              "lowest-pressure point until you right-click another. "
              "The curve is a prediction to compare against."),
        ("h", "ERROR BARS"),
        ("b", "Multiscale variance: the tool tiles the spectrum into "
              "non-overlapping windows at several widths, and fits every "
              "window on its own. The scatter of those per-window answers is "
              "an empirical 1-sigma. The quoted sigma is the LARGEST across "
              "the widths. The widest disagreement sets the error."),
        ("h", "THE FILE"),
        ("b", "series_continuity.json holds the recorded points and each "
              "point's own inputs: its numbers, its notch list with the "
              "per-centre widths, its low-pass and its role glyphs. "
              "Opening a point restores them. A point with its inputs "
              "still to come opens seeded from the nearest preceding "
              "point. The schema is the one Matthew Diamond's program "
              "reads and writes, and fields it owns travel through "
              "untouched."),
        ("h", "SOURCES"),
        ("m", "      M. R. Diamond, defringe_dac.py (series continuity,"),
        ("m", "        multiscale variance); every EoS constant keeps"),
        ("m", "        its citation in fringe_materials.py"),
    ],
}


# ---------------------------------------------------------------------------
# small helpers
# ---------------------------------------------------------------------------

def _deep(o):
    """An independent copy of a JSON-shaped value.

    The series snapshot the memory-vs-disk indicator compares against must
    not share a single nested dict with the live points: a shallow copy
    left every point's 'solved' sub-dict aliased, so editing a solved value
    silently edited the snapshot too and the indicator swore the file was
    up to date.  Deliberately not copy.deepcopy - these payloads are plain
    JSON types, and this keeps the import list honest.
    """
    if isinstance(o, dict):
        return dict((k, _deep(v)) for k, v in o.items())
    if isinstance(o, (list, tuple)):
        return [_deep(v) for v in o]
    return o


def guide_text():
    """The shipped fringe-workbench guide, as tagged lines.

    Read from docs/guide_content through guide_tour -- the same loader the
    Guide / notes dropdown uses, so the panel beside the plot and the entry
    in that dropdown are literally the same words and cannot drift.  Falls
    back to the compiled extract when the content tree is not installed
    (a frozen build run from a stripped folder), exactly as guide_views
    falls back to the compiled REF_VIEWS.

    Tags follow the content's own format contract.  A line indented six
    spaces or more is horizontally meaningful and renders monospaced,
    verbatim.  Everything else is grouped into paragraphs by the blank
    lines, so the text re-wraps to whatever width the pane is dragged to
    instead of keeping the file's 72-column hard breaks.  A paragraph that
    is one line long at column 0 is a heading: ALL-CAPS makes it a section
    head, anything else a sub-head.
    """
    text = None
    try:
        import guide_tour
        text = guide_tour._read_text(os.path.join(guide_tour.GUIDE_DIR,
                                                  GUIDE_FILE))
        if text is not None:
            text = guide_tour._strip_markers(text)
    except Exception:
        text = None
    if not text:
        return list(GUIDE_FALLBACK)
    out, buf, indent = [], [], 0

    def flush():
        if not buf:
            return
        if len(buf) == 1 and indent == 0:
            line = buf[0]
            out.append(("h" if line == line.upper() else "s", line))
        else:
            out.append(("b" if indent == 0 else "i", " ".join(buf)))
        del buf[:]

    for raw in text.rstrip().split("\n"):
        line = raw.rstrip()
        if not line.strip():
            flush()
            if out and out[-1][0] != "gap":
                out.append(("gap", ""))
            continue
        if line.startswith("      "):
            flush()
            out.append(("m", line))
            continue
        if not buf:
            indent = len(line) - len(line.lstrip())
        buf.append(line.strip())
    flush()
    return out


def _ckey(center_nm):
    """Canonical notch-centre key: n*t in um, rounded to 0.01 um.

    Matthew's `_ckey`: the notch list, the removed set and the fundamental pin
    all key off the same rounded micron value, so a peak identified from the
    plot and one read back from state are the same entry.
    """
    return round(float(center_nm) / 1000.0, 2)


def _f(var, fallback):
    """Read a float out of a tk variable, falling back on anything unparsable."""
    try:
        v = float(str(var.get()).strip())
    except (ValueError, tk.TclError, AttributeError):
        return fallback
    return v if np.isfinite(v) else fallback


def _lp_cut_um(var):
    """The low-pass cutoff a box holds, or None when it holds no cutoff.

    His gate is `lowpass and lp_cutoff_um and lp_cutoff_um > 0`
    (defringe_dac 6544), and his reader hands it None the moment the text
    will not parse (13644-13647): an empty box, a word, or a zero all mean
    NO low-pass, not a low-pass at some other number.  Ours fell back on
    15 um and floored a typed 0 at 0.001 um, so a half-typed box quietly
    cleaned the trace at a cutoff nobody asked for -- and it reached the
    all-pressures plot and the exported CSVs.
    """
    try:
        v = float(str(var.get()).strip())
    except (ValueError, tk.TclError, AttributeError):
        return None
    if not np.isfinite(v) or v <= 0.0:
        return None
    return float(v)


def _fmt(v, digits=3):
    if v is None or not np.isfinite(v):
        return "–"
    return ("%%.%df" % digits) % v


def _pv(c):
    """The Fisher p behind a computed channel, 1.0 when there is none.

    It is what his no-fringe title reports, and a channel the FFT could not
    even run on has no p at all rather than a small one.
    """
    try:
        v = float((c or {}).get("pv"))
    except (TypeError, ValueError):
        return 1.0
    return v if np.isfinite(v) else 1.0


def _is_faint(c):
    """True when colour `c` washes out on a pale page (his `_is_faint`, 1130).

    Yellow is its own branch, because yellow reads as pale at a luminance
    that leaves other hues perfectly legible: only a PALE yellow is dropped,
    so a clean bright one (Okabe-Ito's #F0E442, luminance 0.836) survives.
    Everything else goes on luminance, with a second, lower cut for washed
    low-saturation colours.  Used by the stem palette's "skip faint" switch.
    """
    import colorsys

    from matplotlib.colors import to_rgb
    try:
        r, g, b = to_rgb(c)
    except (ValueError, TypeError):
        return False
    h, s, _v = colorsys.rgb_to_hsv(r, g, b)
    lum = 0.299 * r + 0.587 * g + 0.114 * b
    if 0.11 <= h <= 0.20:
        return lum > 0.88
    return lum > 0.80 or (lum > 0.70 and s < 0.35)


def defringe_state(settings, panel=None):
    """The FFT-removal parameters EVERYTHING defringe reads.

    v1.4.9 R10 removed the main window's standalone Defringe section, so
    this panel is the only place the numbers live.  The catch is that the
    workbench is built on first use, while the df switch above the plot
    works from a cold start -- so the state has to be readable with no
    widgets in existence:

      * `panel` built  -> the LIVE tk variables, mid-edit values included
      * `panel` absent -> the fr_ settings keys, which carry exactly the
        same defaults (`SETTINGS_DEFAULTS` above) and are rewritten from
        the live variables by `_persist` on every debounced redraw

    The two paths therefore agree by construction, and a user who never
    opens the Fringe tab still gets the auto-detected fundamental at the
    default half-width under the default gates.

    Returns
        nt_min_um / nt_max_um / pvalue_max : the detection gates
        halfwidth_um                       : default notch half-width (+-um)

    These four are series-wide by design.  Which peaks are notched, at what
    width, belongs to a SPECTRUM, so it is read per trace from
    `FringeWorkbench.defringe_recipe`.  A trace the workbench holds nothing
    for is cleaned under the panel's GLOBAL controls -- these gates and the
    per-channel low-pass -- with the core detecting that spectrum's own
    fundamental; `global_recipe` below builds exactly that, from the live
    panel or from the settings keys alone.
    """
    s = settings if isinstance(settings, dict) else {}
    live = panel if (panel is not None
                     and getattr(panel, "_built", False)) else None

    def _key(name, dflt):
        try:
            v = float(s.get(name, dflt))
        except (TypeError, ValueError):
            return dflt
        return v if np.isfinite(v) else dflt

    if live is not None:
        nt_lo, nt_hi = _f(live.ntmin_v, 8.0), _f(live.ntmax_v, 300.0)
        pmax = _f(live.pmax_v, 1e-4)
        hw = _f(live.hw_v, 3.0)
    else:
        nt_lo = _key("fr_nt_min_um", 8.0)
        nt_hi = _key("fr_nt_max_um", 300.0)
        pmax = _key("fr_pvalue_max", 1e-4)
        hw = _key("fr_halfwidth_um", 3.0)
    if not 0 < nt_lo < nt_hi:
        nt_lo, nt_hi = 8.0, 300.0
    if not pmax > 0:
        pmax = 1e-4
    if not hw > 0:
        hw = 3.0
    return {"nt_min_um": nt_lo, "nt_max_um": nt_hi, "pvalue_max": pmax,
            "halfwidth_um": hw}


def global_lowpass(settings, panel=None):
    """{channel key: low-pass kwargs} from the panel's GLOBAL controls.

    Same two paths as `defringe_state`: the live tk variables when the Fringe
    tab has been built, the fr_ settings keys when it never has.  The keys
    carry the same defaults and `_persist` rewrites them from the variables on
    every debounced redraw, so a Run before the tab is ever opened applies the
    saved low-pass and the saved edge.
    """
    s = settings if isinstance(settings, dict) else {}
    live = panel if (panel is not None
                     and getattr(panel, "_built", False)) else None
    out = {}
    for chan, pre in (("Background", "bg"), ("Sample", "s")):
        if live is not None:
            try:
                on = bool(live.lp_on_v[chan].get())
                cut = _lp_cut_um(live.lp_v[chan])
                shape, roll = live._lp_edge(chan)
            except (AttributeError, KeyError, tk.TclError):
                on, cut, shape, roll = False, None, "tanh", 2.0
        else:
            _on = s.get("fr_lp_%s_on" % pre)
            on = bool(s.get("fr_lowpass_on", True) if _on is None else _on)
            _um = s.get("fr_lp_%s_um" % pre)
            try:
                cut = float(s.get("fr_lp_cutoff_um", 15.0) if _um is None
                            else _um)
            except (TypeError, ValueError):
                cut = 15.0
            shape = str(s.get("fr_lp_%s_shape" % pre, "tanh"))
            try:
                roll = float(s.get("fr_lp_%s_roll" % pre, 2.0))
            except (TypeError, ValueError):
                roll = 2.0
        entry = {"notch_centers_nm": None}     # automatic: this spectrum's own
        # No usable cutoff is no low-pass, his gate exactly: the tick alone
        # never puts a filter on the trace.
        if on and cut and float(cut) > 0.0:
            entry["lowpass"] = True
            entry["lp_cutoff_um"] = float(cut)
            entry["lp_rolloff_um"] = roll if roll > 0 else 2.0
            entry["lp_edge_shape"] = (shape if shape in LP_EDGE_SHAPES
                                      else "tanh")
        out[CHAN_KEY[chan]] = entry
    return out


def dataset_year_month(folder=None, rec=None, cache=None):
    """(year, month) a dataset was acquired in, or None.

    The acquisition folder's name is where Matthew's batch reads the date from
    ("Y03_ch29_Nov2025_ProcessedCSV"); a spectrum opened on its own falls back
    to its file stem.  Pure, and free of tk, so both the workbench's own
    config build and the settings-only one read the same date.
    """
    names = []
    if folder:
        names.append(os.path.basename(os.path.normpath(str(folder))))
    if rec is not None and rec.get("stem"):
        names.append(str(rec["stem"]))
    cache = {} if cache is None else cache
    for name in names:
        if name not in cache:
            try:
                cache[name] = parse_folder_date(name)
            except (TypeError, ValueError):
                cache[name] = None
        ym = cache[name]
        if ym is not None:
            return ym
    return None


def global_cfg(settings, rec=None, folder=None, chan=None):
    """A FringeConfig from the fr_ settings keys alone.

    The no-UI twin of `FringeWorkbench._cfg_for`: same fields, same clamps,
    same lamp-regime fine window, read from the keys `_persist` writes rather
    than from the tk variables.  It is what makes a Run before the Fringe tab
    is ever opened clean under the saved Detection card instead of under the
    library defaults.

    `folder` is the input folder, which carries the wavelength-window override
    and the acquisition date; `rec` supplies the trace's own pressure for the
    Eremets diamond model and its stem for the date.  `chan` names the channel
    the config describes, so its `lp_cutoff_um` states that channel's cutoff
    rather than the Sample's; the cutoff that actually cleans still travels as
    a per-channel keyword.
    """
    s = settings if isinstance(settings, dict) else {}

    def _num(name, dflt):
        try:
            v = float(s.get(name, dflt))
        except (TypeError, ValueError):
            return dflt
        return v if np.isfinite(v) else dflt

    model = s.get("fr_diamond_model", "constant")
    if model not in DIAMOND_MODELS:
        model = "constant"
    pres = 0.0
    if model == "eremets" and rec is not None:
        try:
            pres = float(rec.get("pressure_val") or 0.0)
        except (TypeError, ValueError):
            pres = 0.0
    wl_lo, wl_hi = _num("fr_wl_min", 600.0), _num("fr_wl_max", 800.0)
    ov = s.get("fr_wl_overrides") or {}
    if folder and folder in ov:
        try:
            wl_lo, wl_hi = float(ov[folder][0]), float(ov[folder][1])
        except (TypeError, ValueError, IndexError, KeyError):
            wl_lo, wl_hi = _num("fr_wl_min", 600.0), _num("fr_wl_max", 800.0)
    if wl_hi <= wl_lo:
        wl_lo, wl_hi = 600.0, 800.0
    nt_lo, nt_hi = _num("fr_nt_min_um", 8.0), _num("fr_nt_max_um", 300.0)
    if nt_hi <= nt_lo:
        nt_lo, nt_hi = 8.0, 300.0
    pmax = _num("fr_pvalue_max", 1e-4)
    if not (0.0 < pmax <= 1.0):
        pmax = 1e-4
    tol = _num("fr_agree_tol", 0.15)
    hw = _num("fr_halfwidth_um", 3.0)
    pre = "bg" if chan == "Background" else "s"
    _c_um = s.get("fr_lp_%s_um" % pre)
    lp_cut = (_num("fr_lp_cutoff_um", 15.0) if _c_um is None
              else _num("fr_lp_%s_um" % pre, 15.0))
    cfg = FringeConfig(
        diamond_model=model, diamond_pressure_gpa=pres,
        fit_wl_min_nm=wl_lo, fit_wl_max_nm=wl_hi,
        fringe_nt_min_nm=nt_lo * 1000.0, fringe_nt_max_nm=nt_hi * 1000.0,
        fringe_pvalue_max=pmax, nt_agree_tol=(tol if tol > 0 else 0.15),
        notch_halfwidth_um=(hw if hw > 0 else 3.0),
        # the Band D resolution floor is a settings key now, so unticking it
        # reaches a Run and the exported CSVs and not only the picture
        band_res_floor=bool(s.get("fr_band_floor", True)),
        # A5.1: no 1e-3 floor anywhere over a cutoff.  The SETTINGS
        # fallback (15.0, above) stays -- a stored setting is a
        # number -- but a stored 0 means no cutoff, not 0.001 um.
        lp_cutoff_um=(lp_cut if lp_cut > 0.0 else 0.0))
    ym = dataset_year_month(folder, rec)
    return cfg if ym is None else config_for_date(ym, cfg=cfg)


def global_recipe(settings, panel=None, key=None, cfg=None, rec=None,
                  folder=None):
    """The cleaning for a trace the workbench holds no state for.

    Every loaded pressure has a recipe -- that is what makes the panel the
    defringe.  A trace nobody has opened in the workbench is cleaned under the
    GLOBAL controls: these gates, this half-width, this per-channel low-pass
    and edge, with `notch_centers_nm=None` so the core detects THAT spectrum's
    own fundamental rather than borrowing another pressure's peaks.

    Same shape as `FringeWorkbench.defringe_recipe`, source "global".  Built
    from the live panel when it exists and from the fr_ settings keys when it
    does not, and the two agree by construction -- `global_cfg` is the no-UI
    twin of `_cfg_for`, so the detector runs in the saved wavelength window
    and the saved lamp-regime fine band either way.
    """
    st = defringe_state(settings, panel)
    if cfg is None and (rec is not None or folder):
        cfg = global_cfg(settings, rec, folder)
    return {"gates": {"halfwidth_um": st["halfwidth_um"],
                      "nt_min_nm": st["nt_min_um"] * 1000.0,
                      "nt_max_nm": st["nt_max_um"] * 1000.0,
                      "pvalue_max": st["pvalue_max"]},
            "cfg": cfg, "channels": global_lowpass(settings, panel),
            "source": "global", "key": key}


class FringeWorkbench(object):
    """The fringe workbench: an FFT view for the centre canvas plus the right
    panel's five cards, over one shared per-trace state.

    Public API (everything app.py may call):
        build()                 build the cards and the figure (idempotent)
        activate() / deactivate() / toggle()
        is_active()
        on_trace_change(label=None)
        sync_view_switch()      repaint the Plot|Fringe control after a theme
        popout()
        save_state() / load_state(d)
        defringe_recipe(ref)    one trace's cleaning, as defringe kwargs
        defringe_recipes()      the same, {stem: recipe}, for the batch paths
    """

    # -- construction -------------------------------------------------------
    def __init__(self, app, center_parent, sidebar_parent):
        _bind_host(app)
        self.app = app
        self.center_parent = center_parent
        self.sidebar_parent = sidebar_parent
        self.settings = getattr(app, "settings", {})
        for k, v in SETTINGS_DEFAULTS.items():
            self.settings.setdefault(k, v)
        for k, v in C_SETTINGS_DEFAULTS.items():
            self.settings.setdefault(k, (dict(v) if isinstance(v, dict)
                                         else list(v) if isinstance(v, list)
                                         else v))

        self._built = False
        self._active = False
        self._label = None            # current trace's DISPLAY label
        # Per-trace state is keyed by the dataset key "stem:<file stem>", never
        # by the display label: two series can both hold a "20 GPa" point, and
        # a label key silently shared one set of notches, roles and fits
        # between them.  The label stays what the dropdown shows.
        self._chan = {}               # (dk, channel) -> channel state
        self._trace = {}              # dk -> roles / solved / gaussians
        self._disk = {}               # dk -> the last COMMITTED state
        self._disk_legacy = {}        # label -> state from a pre-stem payload
        self._inputs = {}             # dk -> the committed input snapshot
        self._inputs_extra = {}       # dk -> fields of a foreign file we keep
        self._live_inputs = {}        # dk -> the controls as this point left
        self._cache = {}              # (dk, channel, sig) -> computed dict
        self._series = []             # recorded points, in memory
        self._drag = None             # active drag descriptor
        self._after = None            # debounce handle
        self._fit_after = None        # centre-split refit debounce handle
        self._pane_w_seen = 0         # last centre-pane width the fitter saw
        # How the guide beside the plot came to be where it is:
        #   "auto"    the fitter decides, which is the normal state
        #   "hidden"  the fitter stood it down to keep the plot usable
        #   "forced"  the reader asked for it anyway on a narrow pane
        self._guide_fit = "auto"
        self._guide_said = False      # the snug-centre note is said once
        self._fit_quiet = False       # the first fit of an activation is
                                      # a layout decision, not news
        self._wr_cache = {}           # folder -> can we write a file there
        self._popout = None
        self._switch_lbls = {}
        self._notch_rows = None
        # the draggable artists of the MAIN canvas; the pop-out's mirror pass
        # swaps its own in and puts these back (see _mirror_popout)
        self._artists = self._blank_artists()
        self._peak_xy = {}            # chan -> the peak (x, y) last DRAWN
        self._recs_seen = None        # the trace list the workbench has
        self._nt_labels = {}          # chan -> the boxed stagger labels
        self._schem_labels = {}       # chan -> the cell-schematic header
        self._seed_said = {}          # dk -> the last seeding message
        self._cursor_now = None       # the canvas cursor currently set
        self._slots = []              # labels that vanish while empty
        self._guide_boxes = []        # guide Text widgets to repaint on theme
        self._guide_scroll = 0.0      # where the guide was left, this session
        self._suspend = False         # True while load_state rewrites vars
        # ---- series level (Phase C) ------------------------------------
        self._results = None          # the Results-vs-pressure Toplevel
        self._res_ax = {}             # panel key -> axes
        self._res_pick = {}           # panel key -> [(x, y, point), ...]
        self._res_model_v = {}        # medium key -> BooleanVar
        self._res_layer2_v = {}       # layer 2 material key -> BooleanVar
        self._res_recorded_v = None   # "As recorded" (his _RES_RECORDED)
        self._res_cmap_v = None       # overlay colourway
        self._res_skipfaint_v = None
        self._res_overflow_v = []     # the "then" colourway overrides
        self._res_overflow_rows = []  # their frames, packed in order
        self._res_overflow_box = None
        self._res_layer2_row = None   # the Layer 2 section, hidden with none
        self._res_l2_anchor = None    # the row it packs above
        self._res_model_colors = {}   # draw label -> colour, per redraw
        self._res_defaulted_for = None
        self._res_eos_v = {}          # (panel, eos) -> BooleanVar, per panel
        self._res_anchor = {}         # (panel, eos) -> recorded point label
        self._res_anchor_curve = {}   # (panel, eos) -> his `curve` field
        self._res_hover = {}          # panel -> {pts, annot} for the tags
        self._res_model_hover = {}    # panel -> [{line, label, xy, annot}]
        self._res_eos_hover = {}      # panel -> [{line, label, annot}]
        self._msv_cache = {}          # dk -> sigma of n*t (um) or None
        self._series_disk = None      # the series payload last read/written
        self._series_path = None      # the file that payload came from
        # the continuity file as last parsed, keyed on (path, mtime, size):
        # the dropdown markers ask for it on every redraw (his 11311)
        self._json_cache = {"key": None, "data": None}
        self._pcb_marks = None        # marker tuple last written to the combo
        self._load_busy = False       # True while a load rewrites the state
        self._rebuilding = False      # True while the notch list is rebuilt
        self._date_cache = {}         # folder or stem -> (year, month) | None
        self._dk_cache = {}           # label -> dataset key
        self._dk_sig = None           # the working set that cache belongs to
        # ---- R7 workbench-fidelity state ---------------------------
        self._fit_history = []        # Compute fits snapshots, newest first
        self._fits = {}               # (dk, chan) -> run_fits=True fit
        self._local = None            # Session-loaded folder + records
        self._parent_nav = None       # parent-folder browse state
        self._prev_thick = None       # Lock In redistribution baseline
        self._lp_last = {}            # per-channel low-pass edit guard
        self._lp_edge_last = {}       # ...and the same for its edge
        self._rep = {}                # the Detection card's report labels
        self._fit_btns = []           # the two Fit-peaks glyph buttons
        self._notch_win = None
        self._lines_win = None
        self._detect_win = None
        self._hist_win = None
        self._yaxis_win = None        # the FFT y-range dialog
        self._cmap_win = None         # the stem-colour chooser
        self.toolbar = None           # the tab's navigation toolbar
        self._fund_vars = {}          # chan -> the notch list's radio var
        self._lines_txt = None
        # ---- theme responsiveness + the [?] boxes ----------------------
        self._info = None             # the singleton [?] window
        self._info_topic = None       # which card it is showing
        self._info_btns = []          # [(label, title)] for theme re-stamps
        self._icon_cache = {}         # (name, colour) -> PhotoImage
        self._theme_seen = None       # last painted theme signature
        self._hook_tint_var()

    # ---- following the theme while windows are open ----------------------
    def _hook_tint_var(self):
        """Repaint the figures when 'Tint plot with theme' flips.

        The app's checkbox redraws the MAIN plot (`command=self._redraw`)
        and knows nothing about the workbench, so the FFT view kept its old
        page until the next unrelated redraw.  The tint variable is an
        existing host attribute (`plot_theme_bg`); tracing it is the same
        read-only host plumbing `_records` uses.  Attached here AND retried
        from build(): the variable is created by the Style tab's builder,
        which may run after _init_fringe.
        """
        if getattr(self, "_tint_hooked", False):
            return
        var = getattr(self.app, "plot_theme_bg", None)
        if var is None:
            return
        try:
            var.trace_add("write", lambda *_a: self._theme_repaint_maybe())
            self._tint_hooked = True
        except (AttributeError, tk.TclError):
            pass

    def _retint_toolbar(self):
        """Give the tab's navigation toolbar the panel ground.

        It is plain tk, so the ttk theme does not reach it; and matplotlib
        picks each glyph's ink from the button's background AT BUILD TIME,
        so a ground changed afterwards would leave black icons on a dark
        bar.  Its own re-render is the fix (guarded: a private helper).
        Same treatment the pop-out gives its copy.
        """
        tb = getattr(self, "toolbar", None)
        if tb is None:
            return
        try:
            bg, fg = self._pal()[0], self._pal()[1]
        except Exception:
            return

        def _walk(w):
            try:
                w.configure(background=bg)
            except tk.TclError:
                pass
            try:
                if isinstance(w, (tk.Label, tk.Button, tk.Checkbutton)):
                    w.configure(foreground=fg, activebackground=bg,
                                activeforeground=fg, highlightbackground=bg)
            except tk.TclError:
                pass
            try:
                for child in w.winfo_children():
                    _walk(child)
            except tk.TclError:
                pass
        _walk(tb)
        setter = getattr(tb, "_set_image_for_button", None)
        if not callable(setter):
            return
        try:
            children = tb.winfo_children()
        except tk.TclError:
            return
        for w in children:
            if getattr(w, "_image_file", None) is None:
                continue
            try:
                setter(w)
            except Exception:
                pass

    def _theme_sig(self):
        """Everything the figures and drawn glyphs take their colours from.
        One tuple, so 'did the theme move?' is a single comparison."""
        try:
            br = self.app._brand()
            return (tuple(self._pal()[:3]) + tuple(self._page())
                    + (br["ac1"], br["ac2"], br["ac3"], br["ink"],
                       self._hc()))
        except Exception:
            return None

    def _theme_repaint_maybe(self):
        """Repaint everything colour-carrying if the theme has moved.

        Called from sync_view_switch (the app's theme chain reaches it via
        _recolor_tk -> _sync_tabs -> _render_tabs) and from the tint-var
        trace.  Signature-guarded, so the frequent callers - _render_tabs
        runs on every session-tab repaint - cost one tuple compare."""
        sig = self._theme_sig()
        if sig == self._theme_seen:
            return
        self._theme_seen = sig
        if not self._built:
            return
        # the FFT figure: facecolor, spines, ticks, labels, stems, bands --
        # all re-derived inside _redraw; the pop-out mirror rides along
        self._request_redraw(now=True)
        # the tab's navigation toolbar is plain tk, so it needs the ground
        self._retint_toolbar()
        # the results grid re-derives the same way
        self._res_refresh()
        # the [?] window's mathtext images carry the OLD ink; rebuild
        self._refresh_info()
        # drawn [?] glyphs are regenerated per theme, like the app's icons
        self._restamp_info_btns()
        # Windows caption colours on the open Toplevels
        for w in (self._popout, self._results, self._info):
            if w is not None:
                try:
                    if w.winfo_exists():
                        self.app._apply_titlebar(w)
                except tk.TclError:
                    pass

    # ---- theme-derived colours -------------------------------------------
    def _pal(self):
        return self.app._theme_palette()

    def _page(self):
        """(face, ink) for anything drawn ON the figure -- _mpl_colors is the
        page rule (DESIGN_RULES rule 47), never the UI palette."""
        c = self.app._mpl_colors()
        if isinstance(c, dict):
            return c.get("bg", "#ffffff"), c.get("fg", "#1c2530")
        return c[0], c[1]

    def _hc(self):
        try:
            return self.app.theme_mode.get() == "highcontrast"
        except Exception:
            return False

    def _role_colors(self):
        """(auto, manual) for the role glyphs, from the theme triad.

        His yellow/orange pair says who placed a glyph: the workbench or you.
        Here that is the signal accent for auto and the highlight accent for
        manual, so every theme carries it -- and because High Contrast may
        not lean on colour alone (rule 48), the guide line is solid under an
        auto glyph and dashed under one you placed.
        """
        b = self.app._brand()
        return b["ac2"], b["ac3"]

    def _stem_palette(self):
        """The colours the model stems are drawn from, in order.

        Okabe-Ito is the shipped set: the stems are the one place on the
        figure where colour carries an identity, and that palette survives
        every kind of colour vision (rule 48).  The chooser can put another
        qualitative set there, and "skip faint" drops the colours that wash
        out on a pale page.  A filter that empties a palette is ignored, so
        a choice can never leave the stems colourless.
        """
        name = self.cmap_v.get() if hasattr(self, "cmap_v") else "okabeito"
        if name == "okabeito" or not colormaps.is_categorical(name):
            cols = list(OKABE_ITO)
        else:
            cols = [colormaps.color_for(name, 0.0, 0.0, 1.0, i, 12)
                    for i in range(12)]
        if getattr(self, "skipfaint_v", None) is not None \
                and self.skipfaint_v.get():
            kept = [c for c in cols if not _is_faint(c)]
            cols = kept or cols
        return cols

    def _stem_style(self, i):
        """Colour + dash for model line i.  High Contrast may not carry an
        identity with colour alone (rule 48), so there the ink colour is shared
        and the dash pattern is the carrier."""
        if self._hc():
            return self._page()[1], STEM_DASHES[i % len(STEM_DASHES)]
        cols = self._stem_palette()
        return cols[i % len(cols)], "-"

    def _default_material_names(self):
        """(medium, sample, layer 2) as the MODELS name them.

        The one definition, because two callers read it: the row captions
        below, and load_series, which blanks a stored name equal to its
        model's own so the box keeps following the dropdown.
        """
        med_model = self.medium_v.get()
        # "Other" is his manual medium: a typed index with no material
        # behind it, so the rows keep the plain word (his name_dflt,
        # 9503-9504) until a real medium model names them.
        med = ("medium" if med_model == "Other" else
               MEDIUM_LABELS.get(med_model, med_model).split(" ")[0])
        return med, "sample", (self.layer2_v.get() or med)

    def _material_names(self):
        """(medium, sample, layer 2) as the labels and the schematic say them.

        A blank box takes the model's own name, so an untouched workbench
        reads exactly as it did before the boxes existed.
        """
        med_dflt, samp_dflt, l2_dflt = self._default_material_names()
        med = (self.name_med_v.get() or "").strip() or med_dflt
        samp = (self.name_samp_v.get() or "").strip() or samp_dflt
        l2 = (self.name_l2_v.get() or "").strip() or l2_dflt
        return med, samp, l2

    def _layer_name(self):
        """The name the d1 / d2 rows carry: layer 2 when it is on, else the
        medium (his `d1 lower <layer2|medium>`)."""
        med, _samp, l2 = self._material_names()
        return l2 if self.layer2_on_v.get() else med

    def _on_name_var(self, *_a):
        """A material name reaches the row labels, the schematic headers and
        the series seed, so it relabels as well as redraws."""
        if self._suspend:
            return
        self.settings["fr_medium_name"] = (self.name_med_v.get() or "").strip()
        self.settings["fr_sample_name"] = \
            (self.name_samp_v.get() or "").strip()
        self.settings["fr_layer2_name"] = (self.name_l2_v.get() or "").strip()
        self._relabel_stack()
        self._request_redraw()

    def _relabel_stack(self):
        """Write the current material names into the Stack card's labels."""
        med, samp, _l2 = self._material_names()
        layer = self._layer_name()
        # his row captions are the quantity and the material, once each
        # (9881-9886): "n medium", "t sample", "d1 lower medium".
        for key, text in (("n_medium", "n %s" % med),
                          ("n_sample", "n %s" % samp),
                          ("n_layer2", "n %s" % _l2),
                          ("d2", "d2 upper %s (um)" % layer),
                          ("t", "t %s (um)" % samp),
                          ("d1", "d1 lower %s (um)" % layer)):
            lab = getattr(self, "_stack_lbls", {}).get(key)
            if lab is None:
                continue
            try:
                lab.configure(text=text)
            except tk.TclError:
                pass

    def _forward_y_lim(self):
        """(lo, hi) for the two FFT panels, or None for full auto.

        Each box is its own bound: a blank or unreadable entry keeps that
        bound automatic, and two blanks are plain auto (his _forward_y_lim,
        9395-9404).
        """
        def _one(var):
            s = str(var.get()).strip()
            if not s:
                return None
            try:
                return float(s)
            except ValueError:
                return None
        lo, hi = _one(self.ylo_v), _one(self.yhi_v)
        return None if (lo is None and hi is None) else (lo, hi)

    # ---- host plumbing ----------------------------------------------------
    def _tip(self, widget, text):
        if Tooltip is not None:
            Tooltip(widget, text)

    def _tip_live(self, widget, fn):
        """A tooltip whose text is rebuilt each time the pointer arrives.

        The host's Tooltip reads `self.text` when it shows, 450 ms after
        <Enter>, so writing it from a second <Enter> binding is enough.  The
        binding is added, never replaced, so the tip's own scheduling stays
        intact.
        """
        if Tooltip is None:
            return
        try:
            text = fn()
        except Exception:
            text = ""
        tip = Tooltip(widget, text)

        def _refresh(_e=None, _t=tip, _f=fn):
            try:
                _t.text = _f()
            except Exception:
                pass
        try:
            widget.bind("<Enter>", _refresh, add="+")
        except tk.TclError:
            pass
        return tip

    def _log(self, msg):
        fn = getattr(self.app, "_logline", None)
        if callable(fn):
            fn(msg)

    def _status(self, msg, warn=False, log=True):
        """One status line under Roles & solve, echoed to the hint bar under
        the axes.  `log=False` is for messages a redraw can re-emit (the
        ordering warning), which must not spam the log once per frame.

        The echo matters: every answer a plot click gets is written here, and
        the card is at the opposite side of the window from the mouse.
        """
        lab = getattr(self, "_status_lbl", None)
        if lab is not None:
            try:
                lab.configure(text=msg,
                              foreground=(self._warn_fg() if warn
                                          else self.app._muted_fg()))
            except tk.TclError:
                pass
            self._show_if_text(lab, msg)
        self._hint(msg or None)
        if msg and log:
            self._log("Fringe: " + msg)

    @staticmethod
    def _show_if_text(lab, text):
        """Keep a placeholder label out of the layout while it says nothing.

        An empty label still claims a whole text line, and four of them sat
        at the bottoms of the fringe cards -- which is most of the dead
        space at the end of every group.
        """
        pack = getattr(lab, "_fr_pack", None)
        if pack is None:
            return
        try:
            # winfo_manager, not winfo_ismapped: the cards are sealed while
            # the window is still being built, when nothing is mapped yet
            managed = lab.winfo_manager() == "pack"
            if text and text.strip():
                if not managed:
                    lab.pack(**pack)
            elif managed:
                lab.pack_forget()
        except tk.TclError:
            pass

    def _slot(self, lab, **pack):
        """A label that only occupies a row while it has something to say.

        Packed normally at build time so the card's order is the natural
        one; `_seal_slots` then records the sibling it must go back in
        front of and drops the ones that are still empty.
        """
        lab.pack(**pack)
        self._slots = getattr(self, "_slots", [])
        self._slots.append((lab, dict(pack)))
        return lab

    def _seal_slots(self):
        """Freeze each slot's place in its card, then hide the empty ones."""
        for lab, pack in getattr(self, "_slots", []):
            try:
                sibs = lab.master.pack_slaves()
                i = sibs.index(lab)
                if i + 1 < len(sibs):
                    pack["before"] = sibs[i + 1]
            except (tk.TclError, ValueError):
                pass
            lab._fr_pack = pack
            try:
                self._show_if_text(lab, lab.cget("text"))
            except tk.TclError:
                pass

    def _warn_fg(self):
        """The one warning tone: the brand's signal accent shaded toward
        orange, collapsing to plain ink in High Contrast (rule 48)."""
        if self._hc():
            return self._pal()[1]
        return self.app._blendc("#d97a1f", self._pal()[1], 0.15)

    # ---- window singletons ------------------------------------------------
    @staticmethod
    def _dismiss(win):
        """Close a list window his way: WITHDRAW, never destroy (fix 16).

        The notch list, the predicted lines and the fit history are long
        scrolling windows, and rebuilding one on every open threw away where
        the reader had scrolled to and which row had focus.  `_raise_existing`
        deiconifies it again, so the two halves of the grammar meet.
        """
        try:
            win.withdraw()
        except tk.TclError:
            pass

    def _closes_by_withdraw(self, win):
        """Bind Escape and the X of one list window to `_dismiss`."""
        win.bind("<Escape>", lambda e: self._dismiss(win))
        win.protocol("WM_DELETE_WINDOW", lambda: self._dismiss(win))
        return win

    def _raise_existing(self, attr):
        """The one way a workbench Toplevel answers a second open request.

        Mainstream behaviour: clicking the button again NEVER spawns a
        twin - the existing window is un-minimised, raised and focused,
        and the caller returns it.  A dead or destroyed window clears the
        attribute and returns None, which tells the caller to build fresh.
        Geometry memory is applied at CREATION only, so raising a window
        the user has moved never yanks it anywhere.
        """
        win = getattr(self, attr, None)
        if win is None:
            return None
        try:
            if win.winfo_exists():
                win.deiconify()
                win.lift()
                win.focus_force()
                return win
        except tk.TclError:
            pass
        setattr(self, attr, None)
        return None

    # ---- how big a workbench window may be --------------------------------
    def _screen_cap(self, frac=DLG_MAX_FRAC):
        """The largest window this screen should be asked to show."""
        try:
            return (int(self.app.root.winfo_screenwidth() * frac),
                    int(self.app.root.winfo_screenheight() * frac))
        except (AttributeError, tk.TclError):
            return 10 ** 5, 10 ** 5

    def _dlg_size(self, w_em, h_em):
        """A window size in em, capped at a share of the screen.

        The same idiom app.py uses for its own dialogs, written out here
        rather than borrowed, so the workbench never leans on a helper it
        does not own.  Without the cap the results grid asked for 1480x840
        and a 1366x768 laptop lost its button bar off the bottom edge.
        """
        em = self.app._em()
        cw, ch = self._screen_cap()
        return min(int(em * w_em), cw), min(int(em * h_em), ch)

    def _clamp_geometry(self, win, geom):
        """Re-apply a remembered "WxH+X+Y", with the SIZE held to the cap.

        A geometry remembered on a big monitor must not put the buttons off
        the bottom of a small one.
        """
        if not geom:
            return
        try:
            size = geom.split("+")[0].split("-")[0]
            w, h = (int(v) for v in size.split("x"))
        except (ValueError, IndexError):
            return
        cw, ch = self._screen_cap()
        try:
            win.geometry("%dx%d%s" % (min(w, cw), min(h, ch),
                                      geom[len(size):]))
        except tk.TclError:
            pass

    # =======================================================================
    # build
    # =======================================================================
    def build(self):
        if self._built:
            return
        self._built = True
        self._hook_tint_var()          # retry: the Style tab may exist now
        self._theme_seen = self._theme_sig()
        self._build_vars()
        self._build_figure()
        self._build_cards()
        self._bind_keys()
        self.on_trace_change()

    def _bind_keys(self):
        """Page Up / Page Down step the pressure point.

        A series is 20 spectra and the only way through it was 20 trips to
        the dropdown.  Bound on the toplevel with add="+", so every other
        Page key keeps its meaning, and answered only while the Fringe view
        is the one on screen and the focus is outside a text box (the
        promise the main window's shortcut table makes).
        """
        try:
            self.app.root.bind("<Prior>", lambda e: self._hotkey_step(-1),
                               add="+")
            self.app.root.bind("<Next>", lambda e: self._hotkey_step(1),
                               add="+")
        except (AttributeError, tk.TclError):
            pass

    def _hotkey_step(self, d):
        if not self._active:
            return
        fn = getattr(self.app, "_typing_in_box", None)
        if callable(fn) and fn():
            return
        self._step_trace(d)
        return "break"

    # ---- tk variables -----------------------------------------------------
    def _build_vars(self):
        s = self.settings
        self.medium_v = tk.StringVar(value=s.get("fr_medium", "Ar"))
        self.medium_n_v = tk.StringVar(
            value="%g" % s.get("fr_medium_n", 1.2))
        self.layer2_on_v = tk.BooleanVar(value=bool(s.get("fr_layer2_on")))
        self.layer2_v = tk.StringVar(value=s.get("fr_layer2", "KCl"))
        self.diamond_v = tk.StringVar(value=s.get("fr_diamond_model",
                                                  "eremets"))
        # The anvil and Layer 2 indices are BOXES, his way (num_vars
        # 'n_diamond' / 'n_layer2'): the model writes them on every load and
        # on calc n, and what stands in them is what the stack model and the
        # solve are read at.  A typed value therefore holds until the next
        # load or model pick, exactly as it does in his window.
        self.nd_v = tk.StringVar(value="%.4f" % fringe_optics.N_DIAMOND_CONST)
        self.nl2_v = tk.StringVar(value="%g" % s.get("fr_n_layer2", 1.0))
        self.ns_v = tk.StringVar(value="%g" % s.get("fr_n_sample", 1.50))
        self.d1_v = tk.StringVar(value="%g" % s.get("fr_d1_um", 0.0))
        self.t_v = tk.StringVar(value="%g" % s.get("fr_t_um", 20.0))
        self.d2_v = tk.StringVar(value="%g" % s.get("fr_d2_um", 0.0))
        self.total_v = tk.StringVar(value="")
        self.lock_v = tk.BooleanVar(value=bool(s.get("fr_lock_total")))
        self.fine_v = tk.BooleanVar(value=bool(s.get("fr_fine_step")))
        self.wlmin_v = tk.StringVar(value="%g" % s.get("fr_wl_min", 600.0))
        self.wlmax_v = tk.StringVar(value="%g" % s.get("fr_wl_max", 800.0))
        self.wlover_v = tk.BooleanVar(value=False)
        self.ntmin_v = tk.StringVar(value="%g" % s.get("fr_nt_min_um", 8.0))
        self.ntmax_v = tk.StringVar(value="%g" % s.get("fr_nt_max_um", 300.0))
        self.pmax_v = tk.StringVar(value="%g" % s.get("fr_pvalue_max", 1e-4))
        self.tol_v = tk.StringVar(value="%g" % s.get("fr_agree_tol", 0.15))
        self.hw_v = tk.StringVar(value="%g" % s.get("fr_halfwidth_um", 3.0))
        # The fringe report the main log writes when df is switched on.
        # Its switch used to sit in the retired Defringe card's
        # "Detection (advanced)"; it lives in the Detection card now,
        # beside the gates it talks about (R14).
        self.suppress_v = tk.BooleanVar(
            value=bool(s.get("fr_suppress_report", False)))
        self.suppress_v.trace_add("write", self._on_suppress)
        # Per-channel low-pass (R7): Matthew keys the cutoff by channel.
        # A pre-R7 settings file seeds both channels from its scalar
        # pair once, so nothing anyone tuned is lost.
        _lg_on = bool(s.get("fr_lowpass_on", True))
        _lg_um = s.get("fr_lp_cutoff_um", 15.0)
        self.lp_on_v = {}
        self.lp_v = {}
        # R15-D: the edge of that low-pass, per channel too -- its shape and
        # the width it rolls off over. tanh / 2.0 um is the vendored core's
        # own edge, so an untouched pair leaves every number where it was.
        self.lp_shape_v = {}
        self.lp_roll_v = {}
        for _chan, _pre in (("Background", "bg"), ("Sample", "s")):
            _on = s.get("fr_lp_%s_on" % _pre)
            _um = s.get("fr_lp_%s_um" % _pre)
            self.lp_on_v[_chan] = tk.BooleanVar(
                value=_lg_on if _on is None else bool(_on))
            self.lp_v[_chan] = tk.StringVar(
                value="%g" % (_lg_um if _um is None else _um))
            _shape = str(s.get("fr_lp_%s_shape" % _pre, "tanh"))
            self.lp_shape_v[_chan] = tk.StringVar(
                value=(_shape if _shape in LP_EDGE_SHAPES else "tanh"))
            self.lp_roll_v[_chan] = tk.StringVar(
                value="%g" % s.get("fr_lp_%s_roll" % _pre, 2.0))
        # The pressure the n models are read at. Blank means the trace's own
        # (his _dp_blank_restore); a number overrides it for calc n.
        self.dp_v = tk.StringVar(value="")
        # Free-text material names. Blank falls back to the model's own name,
        # so an untouched workbench reads exactly as it did.
        self.name_med_v = tk.StringVar(value=s.get("fr_medium_name", ""))
        self.name_samp_v = tk.StringVar(
            value=s.get("fr_sample_name", ""))
        self.name_l2_v = tk.StringVar(value=s.get("fr_layer2_name", ""))
        # The FFT panels' shared y range. Blank is auto for that bound.
        self.ylo_v = tk.StringVar(value=str(s.get("fr_y_lo", "")))
        self.yhi_v = tk.StringVar(value=str(s.get("fr_y_hi", "")))
        # Model-stem colours, and the notch list's own fine-step switch.
        self.cmap_v = tk.StringVar(value=s.get("fr_stem_cmap", "okabeito"))
        self.skipfaint_v = tk.BooleanVar(
            value=bool(s.get("fr_stem_skip_faint", False)))
        self.notchfine_v = tk.BooleanVar(
            value=bool(s.get("fr_notch_fine", False)))
        # right-column view state (his tiered / clean toggles), which is not
        # persisted, exactly as his GUI treats it.  The band-integral
        # resolution floor IS persisted: it reaches a Run and the exported
        # CSVs through global_cfg, so it cannot be a view toggle.
        self.tiers_v = tk.BooleanVar(value=False)
        self.hideclean_v = tk.BooleanVar(value=False)
        self.bandfloor_v = tk.BooleanVar(
            value=bool(s.get("fr_band_floor", True)))
        self.fitmode_v = tk.StringVar(value=s.get("fr_fit_mode", "distinct"))
        self.trace_v = tk.StringVar(value="")
        self.msv_v = tk.BooleanVar(value=bool(s.get("fr_msv_errors")))
        # every var that changes the picture asks for a debounced redraw
        for v in (self.medium_v, self.medium_n_v, self.layer2_on_v,
                  self.layer2_v, self.nd_v, self.nl2_v, self.ns_v, self.d1_v,
                  self.t_v, self.d2_v, self.hw_v,
                  self.lp_on_v["Background"], self.lp_on_v["Sample"],
                  self.lp_v["Background"], self.lp_v["Sample"],
                  self.lp_roll_v["Background"], self.lp_roll_v["Sample"],
                  self.lp_shape_v["Background"], self.lp_shape_v["Sample"],
                  self.ylo_v, self.yhi_v):
            v.trace_add("write", self._on_model_var)
        # The Anvil model OWNS the n diamond box, so a pick writes the box
        # first and the redraw reads what the box then holds.
        self.diamond_v.trace_add("write", self._on_anvil_var)
        # A name changes the row labels and the schematic headers as well as
        # the picture, so it has its own handler.
        for v in (self.name_med_v, self.name_samp_v, self.name_l2_v):
            v.trace_add("write", self._on_name_var)
        for v in (self.wlmin_v, self.wlmax_v, self.ntmin_v, self.ntmax_v,
                  self.pmax_v, self.tol_v):
            v.trace_add("write", self._on_detect_var)
        # The half-width redraws this panel through _on_model_var above,
        # and since R10 it is also the main plot's notch width, so it
        # gets its own second trace for the host side.
        self.hw_v.trace_add("write", self._on_hw_var)

    # ---- the figure -------------------------------------------------------
    def _build_figure(self):
        """The centre: the FFT figure, and the guide pane beside it.

        The two live in a horizontal Panedwindow so the split is the user's
        to drag; the figure carries the weight, so growing the window grows
        the plot and the guide keeps the width it was left at.  The pane
        itself is what activate() swaps into the plot area, not the bare
        canvas, so the guide comes and goes with the view.
        """
        face, _ink = self._page()
        self.fig = Figure(figsize=(9.2, 5.2), dpi=100, facecolor=face)
        # Matthew's 2x2: the forward-model FFT panels down the LEFT
        # column, the measured spectra (raw + cleaned) down the RIGHT,
        # Background over Sample in both.  His width ratio, kept.  The
        # gaps are _layout_grid's, measured off the drawn furniture, and
        # a gridspec that carried its own would outrank it.
        gs = self.fig.add_gridspec(2, 2, width_ratios=[1.0, 1.25])
        self.ax_bg = self.fig.add_subplot(gs[0, 0])
        self.ax_s = self.fig.add_subplot(gs[1, 0], sharex=self.ax_bg)
        self.ax_mb = self.fig.add_subplot(gs[0, 1])
        self.ax_ms = self.fig.add_subplot(gs[1, 1], sharex=self.ax_mb)
        self._axes = {"Background": self.ax_bg, "Sample": self.ax_s}
        self._maxes = {"Background": self.ax_mb, "Sample": self.ax_ms}
        self._twins = {}
        self._center_pw = ttk.Panedwindow(self.center_parent,
                                          orient="horizontal")
        self._fig_holder = ttk.Frame(self._center_pw)
        self._center_pw.add(self._fig_holder, weight=5)
        # Bottom of the plot area, in the pop-out's order: the navigation
        # toolbar lowest, the mouse-grammar line directly under the axes,
        # then the canvas.  Both pack BEFORE the canvas so the canvas is the
        # sacrificial widget when the pane is dragged narrow (rules 13 and
        # 14): neither the toolbar nor the one line that says what the mouse
        # does may be the thing that goes.
        self._tb_bar = ttk.Frame(self._fig_holder)
        self._tb_bar.pack(side="bottom", fill="x")
        self._build_hint_bar(self._fig_holder)
        self.canvas = FigureCanvasTkAgg(self.fig, master=self._fig_holder)
        self._tkcanvas = self.canvas.get_tk_widget()
        # The pan / zoom / home / save toolbar the pop-out has always had.
        # The workbench's own gestures already stand down while a toolbar
        # mode is armed (_toolbar_busy), so the two grammars do not collide.
        try:
            self.toolbar = NavigationToolbar2Tk(self.canvas, self._tb_bar)
            self.toolbar.update()
        except Exception:
            self.toolbar = None
        self._tkcanvas.pack(side="top", fill="both", expand=True)
        self._tkcanvas.configure(background=self._pal()[0],
                                 highlightthickness=0)
        self.canvas.mpl_connect("button_press_event", self._on_press)
        self.canvas.mpl_connect("motion_notify_event", self._on_motion)
        self.canvas.mpl_connect("button_release_event", self._on_release)
        self.canvas.mpl_connect("figure_leave_event", self._on_leave)
        self.canvas.mpl_connect("axes_leave_event", self._on_leave)
        self._guide_pane = None
        # The split is re-fitted whenever the centre changes width.  It used
        # to be set once, at activation, and never again -- so a window
        # resized after that kept the sash it was born with, which is how a
        # 1400 px window came to show a 160 px plot.
        self._center_pw.bind("<Configure>", self._on_pane_configure, add="+")
        # a sash the reader dragged is a width they chose: remember it when
        # they let go, not only when the guide is closed
        self._center_pw.bind("<ButtonRelease-1>",
                             lambda e: self._remember_guide_sash(), add="+")
        # The grid's margins are PIXEL amounts turned into fractions for
        # the canvas they were measured on, so a canvas that changes size
        # without a redraw would carry the old pixels, scaled.  A resize
        # re-places the grid and re-fits the labels; it costs no compute
        # and no re-draw of the data, only a new layout.
        self._relayout_job = None
        self._tkcanvas.bind("<Configure>", self._on_canvas_resize, add="+")
        self._retint_toolbar()
        if self.settings.get("fr_guide_open", True):
            self._open_guide_pane()

    def _on_canvas_resize(self, _event=None):
        job, self._relayout_job = getattr(self, "_relayout_job", None), None
        if job is not None:
            try:
                self.app.root.after_cancel(job)
            except (tk.TclError, ValueError):
                pass
        try:
            self._relayout_job = self.app.root.after(120, self._relayout)
        except tk.TclError:
            pass

    def _relayout(self, fig=None, canvas=None):
        """Place the grid and fit the labels again, without recomputing."""
        if fig is None and canvas is None:
            self._relayout_job = None      # the pop-out holds its own
        if not self._built:
            return
        self._layout_grid(fig)
        self._fit_labels(canvas)
        try:
            (canvas or self.canvas).draw_idle()
        except Exception:
            pass

    # ---- the hint bar under the axes --------------------------------------
    HINT_DEFAULT = ("click a peak to notch it.  right-click to pin or assign "
                    "a role.  drag a role glyph along the top of its panel")
    HINT_EMPTY = ("run a folder and the fringes turn up here")

    def _hint_text(self):
        """The standing line under the axes: the mouse grammar once there is
        something to aim at, and an invitation before that."""
        return self.HINT_DEFAULT if self._records() else self.HINT_EMPTY

    def _build_hint_bar(self, parent):
        """One line under the FFT axes saying what the mouse does.

        The gestures are real but invisible: nothing on the figure says a
        peak is clickable, and every answer the workbench gave a click
        ("no FFT peak near the click") landed in the Roles & solve card at
        the far side of the window, where a user with the mouse over the
        plot never looks.  This bar is that answer, next to the mouse, and
        it falls back to the grammar once the message has been read.
        """
        f = ttk.Frame(parent)
        f.pack(side="bottom", fill="x")
        self._hint_lbl = self.app._lbl(f, text=self._hint_text(),
                                       font=self.app._F(-1),
                                       foreground=MUTED)
        self._hint_lbl.pack(side="left", padx=(6, 0), pady=(0, 2))
        self._hint_after = None
        self._tip(self._hint_lbl,
                  "Left-click a peak marker to put a notch there, or to take "
                  "one away. Right-click a peak to pin it as the "
                  "fundamental, or to assign one of the role glyphs to it. "
                  "Drag the dashed low-pass line, or any role glyph along "
                  "the top, with the left button. The pointer turns into a "
                  "hand over a peak and into a resize arrow over anything "
                  "you can drag.")
        return f

    def _hint(self, msg=None):
        """Show `msg` in the hint bar for a few seconds, then the grammar."""
        lab = getattr(self, "_hint_lbl", None)
        if lab is None:
            return
        after = getattr(self, "_hint_after", None)
        if after is not None:
            try:
                self.app.root.after_cancel(after)
            except (AttributeError, tk.TclError, ValueError):
                pass
            self._hint_after = None
        try:
            lab.configure(text=(msg or self._hint_text()),
                          foreground=(self.app._muted_fg() if not msg
                                      else self._pal()[1]))
        except tk.TclError:
            return
        if not msg:
            return
        try:
            self._hint_after = self.app.root.after(HOVER_MS, self._hint)
        except (AttributeError, tk.TclError):
            self._hint_after = None

    # ---- the five cards ---------------------------------------------------
    def _build_cards(self):
        # Matthew's sidebar, top to bottom: the defringe switch, the stack
        # inputs with the solved column and the fit actions, the Session
        # group, the pressure-point navigator, the Detection gates, FFT
        # removal (the main tool), Refractive Index from Intensity, and the
        # Panels launcher with the status lines and CSV folder under it.
        # The cards categorise themselves under the Fringe tab.  app.py's
        # _tabspec still lists the pre-R7 section names until integration;
        # the category map is live state, and registering here is what
        # keeps _reorder_sections and the honesty gate honest meanwhile.
        cat = getattr(self.app, "_section_cat", None)
        if isinstance(cat, dict):
            for t in FRINGE_SECTIONS:
                cat[t] = "Fringe"
        self._claim_section_slot()
        self._install_sec_icons()
        self._defringe_row()
        self._card_stack()
        self._card_session()
        self._card_pressure()
        self._card_detection()
        self._card_removal()
        self._card_intensity()
        self._card_panels()
        self._seal_slots()
        self._tighten_sections()
        for title in FRINGE_SECTIONS:
            if title in INFO_FOR:
                self._add_info_btn(title)

    def _claim_section_slot(self):
        """Give the Detection card its slot in the app's section order.

        `_reorder_sections` walks `App.SECTION_ORDER` and parks anything it
        does not know AFTER everything it does, so a card built between
        Pressure point and FFT removal would be dragged to the foot of the
        tab the first time that pass ran.  The order is claimed on the App
        INSTANCE, which shadows the class tuple for this session only and
        needs no app.py edit; a build where the name is already listed
        changes nothing.
        """
        a = self.app
        order = list(getattr(a, "SECTION_ORDER", ()) or ())
        if "Detection" in order or "FFT removal" not in order:
            return
        order.insert(order.index("FFT removal"), "Detection")
        try:
            a.SECTION_ORDER = tuple(order)
        except AttributeError:
            pass

    def _install_sec_icons(self):
        """Give each Fringe card a marker that says what the card is.

        `App._make_icons` draws one `sec::<title>` glyph per section and
        both theme passes stamp it on that section's head; a title the set
        does not carry keeps the plain square, which is what all seven
        Fringe cards wore.  The glyphs are drawn here and posted into the
        app's OWN icon set, so every pass that already stamps a marker --
        `_apply_brand`, `_sync_section_head` -- finds them and nothing here
        has to chase a theme switch.

        That set is rebuilt from scratch on each switch, so the builder is
        wrapped on the app INSTANCE: the same shadowing `_claim_section_slot`
        uses for SECTION_ORDER, and it needs no app.py edit.  The wrapper
        reads the drawing call off the app each time, so a workbench built
        later owns it and the wrap happens once.
        """
        a = self.app
        a._fr_sec_draw = self._draw_sec_icons
        if not getattr(a, "_fr_sec_wrapped", False):
            base = a._make_icons

            def _remake(*args, **kw):
                out = base(*args, **kw)
                fn = getattr(a, "_fr_sec_draw", None)
                if callable(fn):
                    fn()
                return out
            try:
                a._make_icons = _remake
                a._fr_sec_wrapped = True
            except AttributeError:
                pass
        self._draw_sec_icons()

    def _draw_sec_icons(self):
        """Draw the seven markers into the app's icon set.

        The language is app.py's `sec()` helper, stroke for stroke: a 24 px
        canvas at 3 px, downsampled to 12 px, in the theme's second accent.
        A machine without PIL keeps the plain square.
        """
        try:
            from PIL import Image, ImageDraw, ImageTk
        except Exception:
            return
        a = self.app
        ic = getattr(a, "_icons", None)
        if not isinstance(ic, dict):
            return
        try:
            A = a._brand()["ac2"]
        except (AttributeError, KeyError, tk.TclError):
            return
        pil = getattr(a, "_icon_pil", None)
        W = 3

        def sec(name, fn):
            im = Image.new("RGBA", (24, 24), (0, 0, 0, 0))
            fn(ImageDraw.Draw(im))
            small = im.resize((12, 12), Image.LANCZOS)
            img = ImageTk.PhotoImage(small)
            ic["sec::" + name] = img
            if isinstance(pil, dict):
                pil[img] = small

        # the stack itself, edge on: anvil, sample, anvil
        sec("Stack", lambda d: (d.rectangle([2, 3, 22, 7], fill=A),
                                d.rectangle([6, 10, 18, 14], fill=A),
                                d.rectangle([2, 17, 22, 21], fill=A)))
        # a folder: the series on disk (app.py's own folder glyph)
        sec("Session", lambda d: d.polygon(
            [(2, 5), (9, 5), (11, 8), (22, 8), (22, 19), (2, 19)],
            outline=A, width=W))
        # the diamond of the anvil cell
        sec("Pressure point", lambda d: d.polygon(
            [(12, 2), (22, 11), (12, 22), (2, 11)], outline=A, width=W))
        # a magnifier: the gates that find the peaks
        sec("Detection", lambda d: (d.ellipse([3, 3, 15, 15], outline=A,
                                              width=W),
                                    d.line([14, 14, 21, 21], fill=A,
                                           width=W)))
        # the fringe itself, sampled every pixel so the curve survives the
        # downscale (the Fringe tab's own glyph, at marker size)
        sec("FFT removal", lambda d: d.line(
            [(x, 12.0 - 6.0 * float(np.sin((x - 2) * np.pi / 8.0)))
             for x in range(2, 23)], fill=A, width=W))
        # refraction: a ray bending as it crosses the interface
        sec("Refractive Index from Intensity", lambda d: (
            d.line([2, 12, 22, 12], fill=A, width=W),
            d.line([6, 2, 12, 12], fill=A, width=W),
            d.line([12, 12, 16, 22], fill=A, width=W)))
        # a window with a side panel: what the card opens
        sec("Panels", lambda d: (d.rectangle([2, 4, 22, 20], outline=A,
                                             width=W),
                                 d.line([9, 4, 9, 20], fill=A, width=W),
                                 d.line([9, 12, 22, 12], fill=A, width=W)))

    def _defringe_row(self):
        """The df switch, at the head of the Fringe column.

        ONE variable, two boxes: this checkbox and the `df` box on the
        Quick Access strip hold the same `BooleanVar` and call the same
        command, so they cannot disagree and there is no sync code to fall
        out of step.  It stands above the Stack card rather than inside a
        card of its own because it is the one switch the whole column
        serves.
        """
        a = self.app
        var = getattr(a, "show_notch", None)
        cmd = getattr(a, "_toggle_notch", None)
        if var is None or not callable(cmd):
            return
        f = ttk.Frame(self.sidebar_parent, padding=(12, 6))
        f.pack(fill="x", pady=(2, 0))
        self._df_row = f
        cb = ttk.Checkbutton(f, text="Defringe (df)", variable=var,
                             command=cmd)
        cb.pack(side="left")
        self._df_cb = cb
        self._tip(cb, "The master switch for defringing. The plotted counts "
                      "and this panel's red FFT filtered curve both follow "
                      "it. Each trace cleans at its own notch list and "
                      "low-pass from this panel; a trace this panel holds "
                      "nothing for cleans under the global controls, at the "
                      "fringe the detector finds in that spectrum. The df "
                      "box above the plot is the same switch.")
        rule = ttk.Separator(self.sidebar_parent, orient="horizontal")
        rule.pack(fill="x", padx=12, pady=(0, 4))
        self._df_rule = rule

    # ---- the [?] boxes ----------------------------------------------------
    def _add_info_btn(self, title):
        """A small [?] at the right end of a card's title row.

        The affordance for the curious: the card's tooltips say what each
        control does, the [?] window says what the math underneath does.
        Follows the guide pane's own x-close pattern - a bound label on the
        header row - with keyboard access on top.  The glyph is drawn (rule
        31) and re-stamped per theme by _restamp_info_btns.
        """
        rec = next((r for r in getattr(self.app, "_collapsibles", [])
                    if r.get("key") == title), None)
        tl = (rec or {}).get("title_lbl")
        if tl is None:
            return
        try:
            hdr = tl.master
        except AttributeError:
            return
        a = self.app
        lbl = a._lbl(hdr, text="?", font=a._F(0, "bold"),
                     anchor="center", takefocus=1)
        img = self._help_icon()
        if img is not None:
            lbl.configure(image=img, text="")
            lbl.image = img
        # the card bodies are inset 12 px; a [?] 4 px off the panel edge
        # read as though it had been cut in half by the scrollbar
        lbl.pack(side="right", padx=(PAD_X, PAD_X + 4))
        lbl.configure(cursor="hand2")
        for seq in ("<Button-1>", "<Return>", "<Key-space>"):
            lbl.bind(seq, lambda e, t=title: self._open_info(t))
        self._tip(lbl, INFO_TIP)
        self._info_btns.append((lbl, title))

    def _help_icon(self):
        """The [?] glyph: a Bauhaus square holding a drawn question mark,
        in the theme's signal accent (the gear's slot).  Drawn with PIL at
        2x and downsampled, exactly as _make_icons draws the app set; a
        machine without PIL keeps the typed fallback."""
        try:
            from PIL import Image, ImageDraw, ImageTk
        except Exception:
            return None
        col = self.app._brand()["ac2"]
        if self._hc():
            col = self._pal()[1]
        key = ("help", col)
        if key in self._icon_cache:
            return self._icon_cache[key]
        im = Image.new("RGBA", (32, 32), (0, 0, 0, 0))
        d = ImageDraw.Draw(im)
        W = 3
        d.rectangle([3, 3, 29, 29], outline=col, width=W)
        # the question mark: hook, stem, dot
        d.arc([10, 7, 22, 17], start=180, end=90, fill=col, width=W)
        d.line([16, 17, 16, 20], fill=col, width=W)
        d.ellipse([14, 23, 18, 26], fill=col)
        img = ImageTk.PhotoImage(im.resize((16, 16), Image.LANCZOS))
        if len(self._icon_cache) > 8:
            self._icon_cache.clear()
        self._icon_cache[key] = img
        return img

    def _restamp_info_btns(self):
        """Regenerate the [?] glyphs in the new theme's accent (rule 32:
        icons are regenerated per theme, not recoloured)."""
        alive = []
        for lbl, title in self._info_btns:
            try:
                if not lbl.winfo_exists():
                    continue
                img = self._help_icon()
                if img is not None:
                    lbl.configure(image=img, text="")
                    lbl.image = img
                else:
                    lbl.configure(foreground=self.app._brand()["ac2"])
                alive.append((lbl, title))
            except tk.TclError:
                continue
        self._info_btns = alive
        for btn, mode in list(getattr(self, "_fit_btns", [])):
            try:
                if not btn.winfo_exists():
                    continue
                img = self._fit_icon(mode == "shared")
                if img is not None:
                    btn.configure(image=img)
                    btn.image = img
            except tk.TclError:
                continue

    def _open_info(self, topic, _e=None):
        """The singleton math window for one card.

        A second click raises the window it already opened; a click on a
        DIFFERENT card's [?] re-aims the same window rather than opening a
        sibling, so there is never more than one.
        """
        if topic not in INFO_FOR:
            return None
        win = self._raise_existing("_info")
        if win is not None:
            if topic != self._info_topic:
                self._info_topic = topic
                self._fill_info()
            return win
        a = self.app
        win = tk.Toplevel(a.root)
        win.transient(a.root)
        em = a._em()
        a._center_on_root(win, em * 76, em * 60)
        a._apply_titlebar(win)
        win.bind("<Escape>", lambda e: self._close_info())
        win.protocol("WM_DELETE_WINDOW", self._close_info)
        self._info = win
        self._info_topic = topic
        self._fill_info()
        return win

    def _close_info(self):
        win, self._info = self._info, None
        self._info_topic = None
        if win is not None:
            try:
                win.destroy()
            except tk.TclError:
                pass

    def _refresh_info(self):
        """Rebuild the open [?] window's content in the live theme - the
        typeset formulas are IMAGES in the old ink and cannot be retinted."""
        if self._info is None:
            return
        try:
            if not self._info.winfo_exists():
                self._info = None
                return
        except tk.TclError:
            self._info = None
            return
        self._fill_info()

    def _fill_info(self):
        win, topic = self._info, self._info_topic
        if win is None or topic is None:
            return
        try:
            win.title(topic)
            for w in win.winfo_children():
                w.destroy()
        except tk.TclError:
            return
        a = self.app
        card = a._card(win, grow="both")
        card.pack(fill="both", expand=True, padx=10, pady=8)
        card.set_title(a._lf_header(card, topic, icon="book"))
        rows = []
        for _key in INFO_FOR.get(topic, ()):
            if rows:
                rows.append(("gap", ""))
            rows.extend(INFO_CONTENT.get(_key, ()))
        # a ("live", name) row is computed when the window is filled, not
        # shipped: his Info ends on readouts of the state that is actually
        # set, and a paragraph quoting a bin the window no longer has is
        # worse than no paragraph
        rows = [self._info_live(r[1]) if r[0] == "live" else r for r in rows]
        rows = [r for r in rows if r is not None]
        self._info_body(card.body, rows)

    def _info_live(self, name):
        """One computed Info row, or None when it cannot be computed.

        `fft_bin` is his live bin readout (defringe_dac 11665-11666 and
        11712), read from the fit window as it stands; `index_ordering` is
        his flip line (11670-11674), read from the indices in the boxes.
        """
        if name == "fft_bin":
            lo = _f(self.wlmin_v, 600.0)
            hi = _f(self.wlmax_v, 800.0)
            if not (0.0 < lo < hi):
                return None
            dwn = 1.0 / lo - 1.0 / hi
            if dwn <= 0.0:
                return None
            binum = 1.0 / (2.0 * dwn) / 1000.0
            if not np.isfinite(binum):
                return None
            return ("m", "      current bin ~ %.1f um   (window %.0f-%.0f "
                         "nm)" % (binum, lo, hi))
        if name == "index_ordering":
            ns = _f(self.ns_v, 1.5)
            n2 = None
            rec = self._record()
            if rec is not None:
                try:
                    p = self._stack_params(rec)
                    ns = float(p["n_sample"])
                    n2 = float(p["n_layer2"])
                except (KeyError, TypeError, ValueError):
                    n2 = None
            if n2 is None:
                n2 = _f(self.medium_n_v, 1.2)
            if ns >= n2:
                return ("b", "Here n sample %.4f is at or above the layer "
                             "beside it, %.4f. The medium to sample "
                             "reflection flips sign, so the terms for "
                             "interface pairs 12, 13, 24 and 34 invert. "
                             "Their phase flips; their n*t positions do "
                             "not move." % (ns, n2))
            return ("b", "Here n sample %.4f is below the layer beside it, "
                         "%.4f. There is no sign flip, and every interface "
                         "pair keeps its nominal phase." % (ns, n2))
        return None

    def _info_body(self, parent, lines):
        """The [?] renderer: the guide-box shape plus one extra tag.

        A ("f", mathtext, plain) row asks the host to typeset the formula
        (the same _mathtext_image the formula list renders through, so the
        idiom and the caching are the app's own) and embeds the image in
        the text flow; when mathtext is unavailable - no host renderer, or
        a string its parser rejects - the plain form takes the mono tag
        instead, so the math is never silently missing.
        """
        txtf = ttk.Frame(parent)
        txtf.pack(fill="both", expand=True)
        sb = ttk.Scrollbar(txtf)
        sb.pack(side="right", fill="y")
        txt = tk.Text(txtf, width=50, wrap="word", relief="flat", padx=8,
                      pady=6, highlightthickness=0, bd=0,
                      yscrollcommand=sb.set)
        txt.pack(side="left", fill="both", expand=True)
        sb.config(command=txt.yview)
        txt._fr_heads = []
        txt._fr_imgs = []              # tk needs the references held
        mt = getattr(self.app, "_mathtext_image", None)
        try:
            ffg = self.app._code_fg()
        except (AttributeError, tk.TclError):
            ffg = self._pal()[1]
        for row in lines:
            kind = row[0]
            if kind == "f":
                img = mt(row[1], fg=ffg) if callable(mt) else None
                if img is not None:
                    txt.insert("end", "   ")
                    txt.image_create("end", image=img, padx=4, pady=6)
                    txt.insert("end", "\n")
                    txt._fr_imgs.append(img)
                else:
                    txt.insert("end", "      " + row[2] + "\n", ("m",))
                continue
            txt.insert("end", row[1] + "\n",
                       () if kind == "gap" else (kind,))
        txt.configure(state="disabled")
        self._guide_boxes = getattr(self, "_guide_boxes", [])
        self._guide_boxes.append(txt)
        self._retint_guide(txt)
        return txt

    def _tighten_sections(self):
        """End each fringe card where its content ends.

        app.py's `_reorder_sections` re-packs every section it knows about at
        the house `pady=(2, 7)`; the workbench's five are not in its order
        list, so they alone kept `_group`'s build-time `(5, 12)` -- five
        pixels more air above and five more below than every other section in
        the program, on top of the empty placeholder labels `_seal_slots`
        has just taken out.  Together that was Nhan's "bunch of dead space at
        the bottom".  Setting the same pady from here needs no app.py edit,
        and if the sections are ever added to that order list it sets exactly
        the same value.
        """
        for rec in getattr(self.app, "_collapsibles", []):
            if rec.get("key") not in FRINGE_SECTIONS:
                continue
            cont = rec.get("cont")
            if cont is None:
                continue
            try:
                if cont.winfo_manager() == "pack":
                    cont.pack_configure(pady=(2, 7))
            except tk.TclError:
                pass

    def _row(self, parent, pady=None):
        f = ttk.Frame(parent)
        f.pack(fill="x", pady=(PAD_ROW if pady is None else pady))
        return f

    def _wrap_to_card(self, lab, slack=10):
        """Wrap a running-text label at the card's width, not a guess.

        The status lines were born with `wraplength = 32 em`, about half
        the room the Fringe column actually gives them, so a one-line
        message broke over two or three lines with the right half of the
        card empty.  The width is read from the card body instead, and
        re-read whenever the panel is resized.
        """
        def _set(_e=None):
            try:
                w = int(lab.master.winfo_width()) - slack
                # str(): Tk 8.6.9 hands back a Tcl_Obj here
                if w > 60 and int(
                        str(lab.cget("wraplength")) or 0) != w:
                    lab.configure(wraplength=w)
            except (tk.TclError, ValueError):
                pass
        lab.master.bind("<Configure>", _set, add="+")
        _set()
        return lab

    def _spin(self, parent, var, lo, hi, width=8, step=1.0):
        """One numeric box, registered with the fine-steps switch.

        `step` is the box's OWN coarse increment.  His thickness boxes step
        at 1 um and his index boxes at 0.1, and fine steps divides whichever
        one the box carries by ten -- so the switch reaches every box in the
        window without flattening them all to the same pace.
        """
        sp = ttk.Spinbox(parent, textvariable=var, from_=lo, to=hi,
                         width=width, increment=self._step(step))
        sp._fr_step = float(step)
        self._spins = getattr(self, "_spins", [])
        self._spins.append(sp)
        return sp

    def _step(self, base=1.0):
        return (0.1 if self.fine_v.get() else 1.0) * float(base)

    # ---- the rows the Layer 2 tick shows and hides ------------------------
    def _l2_row(self, row, pack):
        """Register one row as Layer 2's own, in whichever window built it.

        His n layer2 row is not there at all until the box is ticked, so the
        row has to be re-packed in its OWN place afterwards -- pack appends,
        and a row that came back at the foot of the card would read as a
        different row.  The sibling under it is remembered by `_seal_l2_rows`
        once the card is fully built.
        """
        self._l2_rows = getattr(self, "_l2_rows", [])
        self._l2_rows.append((row, dict(pack)))
        return row

    def _seal_l2_rows(self):
        """Freeze each Layer 2 row's place, then apply the current tick."""
        out = []
        for row, pack in getattr(self, "_l2_rows", []):
            try:
                if not row.winfo_exists():
                    continue
                sibs = row.master.pack_slaves()
                i = sibs.index(row)
                if i + 1 < len(sibs):
                    pack = dict(pack, before=sibs[i + 1])
            except (tk.TclError, ValueError):
                pass
            out.append((row, pack))
        self._l2_rows = out
        self._sync_l2_rows()

    def _sync_l2_rows(self):
        """Show the Layer 2 rows while the box is ticked, hide them else."""
        try:
            on = bool(self.layer2_on_v.get())
        except tk.TclError:
            return
        for row, pack in list(getattr(self, "_l2_rows", [])):
            try:
                if not row.winfo_exists():
                    self._l2_rows.remove((row, pack))
                    continue
                if on:
                    row.pack(**pack)
                else:
                    row.pack_forget()
            except (tk.TclError, ValueError):
                pass

    def _sync_steps(self, *_a):
        for sp in getattr(self, "_spins", []):
            try:
                sp.configure(increment=self._step(getattr(sp, "_fr_step",
                                                          1.0)))
            except tk.TclError:
                pass

    # ---- STACK ------------------------------------------------------------
    def _card_stack(self):
        """Matthew's input column: the materials, then the indices and
        thicknesses with the solved readout beside them, the Total row
        with Lock In and fine steps, and the Fit peaks / Plot point /
        Results plot action row.  His order, his defaults, his lock-in
        rules; SPARTA's card grammar and theming."""
        b = self.app._group(self.sidebar_parent, "Stack")
        a = self.app
        self._stack_lbls = {}

        # His Materials header carries this button (9514).  Our section
        # headers are the accordion's own click target, so it takes the
        # card's first row instead, right-aligned as his is.
        r = self._row(b)
        rd = ttk.Button(r, text="Reset & drop point",
                        command=self._reset_and_drop_point)
        rd.pack(side="right")
        self._tip(rd, "Put every input back to its shipped value and take "
                      "this pressure point off the results series. The "
                      "continuity file keeps it until the next save.")

        r = self._row(b, PAD_TIGHT)
        a._lbl(r, text="Anvil", width=STACK_LBL_W).pack(side="left")
        dcb = a._mapped_combo(r, self.diamond_v, DIAMOND_LABELS, width=18)
        dcb.pack(side="left", fill="x", expand=True)
        dcb.bind("<<ComboboxSelected>>", self._commit_stack, add="+")
        self._tip(dcb, "Which n(lambda) model stands for the diamond anvil. "
                       "The value it gives sits on the n diamond row below. "
                       "Eremets adds the pressure term, fed from each "
                       "spectrum's own pressure.")

        r = self._row(b, PAD_TIGHT)
        a._lbl(r, text="Medium", width=STACK_LBL_W).pack(side="left")
        mcb = a._mapped_combo(r, self.medium_v, MEDIUM_LABELS, width=18)
        mcb.pack(side="left", fill="x", expand=True)
        mcb.bind("<<ComboboxSelected>>", self._commit_stack, add="+")
        self._tip(mcb, "The pressure medium filling the cell. A named medium "
                       "follows pressure through its n(P) model. Other takes "
                       "the index you type on the n medium row.")

        r = self._row(b, PAD_TIGHT)
        l2 = ttk.Checkbutton(r, text="Layer 2", variable=self.layer2_on_v,
                             command=self._on_layer2)
        l2.pack(side="left")
        self._tip(l2, "Turn on when the cell holds a second distinct layer: "
                      "a coating, a second phase, a reaction rim. Off, the "
                      "medium fills the d1/d2 gap.")
        self._l2_cb = a._mapped_combo(
            r, self.layer2_v, {k: k for k in ("KCl", "LiF", "air")}, width=8)
        self._l2_cb.pack(side="left", padx=(PAD_X, 0))
        self._l2_cb.bind("<<ComboboxSelected>>", self._commit_stack, add="+")

        # ---- what the three layers are CALLED (his free-text Entry beside
        # each Materials dropdown).  The name reaches the row labels below,
        # the schematic over each panel and the series materials seed; the
        # n(P) model stays the dropdown's.
        for var, txt, tip, attr in (
                (self.name_med_v, "Medium name",
                 "What the medium is called on the rows, on the schematic "
                 "and in the saved series. Blank takes the Medium "
                 "dropdown's own name.", None),
                (self.name_samp_v, "Sample name",
                 "What the sample is called on the rows, on the schematic "
                 "and in the saved series.", None),
                (self.name_l2_v, "Layer 2 name",
                 "What the second layer is called. Blank takes the Layer 2 "
                 "dropdown's own name.", "_l2_name_e")):
            r = self._row(b, PAD_TIGHT)
            a._lbl(r, text=txt, width=STACK_LBL_W).pack(side="left")
            e = ttk.Entry(r, textvariable=var, width=14)
            e.pack(side="left", fill="x", expand=True)
            self._tip(e, tip)
            if attr:
                setattr(self, attr, e)

        # ---- indices + thicknesses, with the solved column beside them.
        # His exact row alignment: n_s beside n sample, t_s beside t, the
        # medium total t_m beside d2, and L beside d1.
        self._sol_lbl = {}
        hdr = self._row(b, PAD_GROUP)
        a._lbl(hdr, text="", width=STACK_LBL_W).pack(side="left")
        a._lbl(hdr, text="input", width=10, font=a._F(-1),
               foreground=MUTED).pack(side="left")
        a._lbl(hdr, text="solved (this point)", font=a._F(-1),
               foreground=MUTED).pack(side="left", padx=(PAD_X, 0))

        # His P -> n row, directly over the n diamond row (9591-9619): type a
        # pressure, press calc n, and every modelled index is read at it.
        r = self._row(b, PAD_TIGHT)
        a._lbl(r, text="P", width=STACK_LBL_W).pack(side="left")
        dp = self._spin(r, self.dp_v, 0.0, 500.0, width=6)
        dp.configure(command=self._calc_n)
        dp.bind("<Return>", lambda e: self._calc_n())
        dp.bind("<FocusOut>", lambda e: self._dp_blank_restore())
        dp.bind("<Return>", lambda e: self._dp_blank_restore(), add="+")
        dp.pack(side="left")
        self._dp_spin = dp
        a._lbl(r, text="GPa").pack(side="left", padx=(PAD_X_TIGHT, 0))
        self._tip(dp, "The pressure the index models are read at. It fills "
                      "in from the loaded spectrum; an empty box takes that "
                      "value back.")
        r = self._row(b, PAD_TIGHT)
        a._lbl(r, text="", width=STACK_LBL_W).pack(side="left")
        cn = ttk.Button(r, text="calc n", width=8, command=self._calc_n)
        cn.pack(side="left")
        self._tip(cn, "Read the anvil index at P, and the medium and layer 2 "
                      "indices when a model drives them. The wavelength is "
                      "the fringe window's centre.")
        amb = ttk.Button(r, text="Ambient n (2.4168)",
                         command=self._ambient_n)
        amb.pack(side="left", padx=(PAD_X, 0))
        self._tip(amb, "Put the anvil on the ambient constant 2.4168 "
                       "(Phillip & Taft 1964, at 589 nm).")

        # His n diamond is a BOX, not a readout (9567): the model writes it
        # on every load and on calc n, and the number standing in it is what
        # the stack model is built from.
        r = self._row(b, PAD_TIGHT)
        a._lbl(r, text="n diamond", width=STACK_LBL_W).pack(side="left")
        self._nd_sp = self._spin(r, self.nd_v, 0.0, 100000.0, width=10,
                                 step=IDX_STEP)
        self._nd_sp.configure(command=self._commit_stack)
        for _seq in ("<Return>", "<FocusOut>"):
            self._nd_sp.bind(_seq, self._commit_stack, add="+")
        self._nd_sp.pack(side="left")
        a._lbl(r, text="Fixed", font=a._F(-1, "bold"),
               foreground=MUTED).pack(side="left", padx=(PAD_X, 0))
        self._tip(self._nd_sp, "The anvil index. Every load reads it from "
                               "the Anvil model at that spectrum's own "
                               "pressure; calc n and Ambient n rewrite it. "
                               "Held fixed in the solve.")

        r = self._row(b, PAD_TIGHT)
        self._stack_lbls["n_medium"] = a._lbl(r, text="n medium",
                                              width=STACK_LBL_W)
        self._stack_lbls["n_medium"].pack(side="left")
        cell = ttk.Frame(r)
        cell.pack(side="left")
        self._nmed_lbl = a._lbl(cell, text="1.2", width=10,
                                font=a._F(0, mono=True))
        self._nmed_e = self._spin(cell, self.medium_n_v, 0.0, 100000.0,
                                  width=10, step=IDX_STEP)
        self._nmed_e.configure(command=self._commit_stack)
        for _seq in ("<Return>", "<FocusOut>"):
            self._nmed_e.bind(_seq, self._commit_stack, add="+")
        a._lbl(r, text="Fixed", font=a._F(-1, "bold"),
               foreground=MUTED).pack(side="left", padx=(PAD_X, 0))
        self._tip(self._nmed_e, "Refractive index of the medium: the solve's "
                                "anchor, held fixed. Yours to type while the "
                                "Medium is Other.")
        self._tip(self._nmed_lbl, "The medium index its n(P) model gives "
                                  "at this spectrum's pressure.")

        # His n layer2 row: hidden until Layer 2 is ticked (9578), and the
        # Layer 2 model writes it the way the Anvil model writes n diamond.
        r = self._row(b, PAD_TIGHT)
        self._stack_lbls["n_layer2"] = a._lbl(r, text="n layer2",
                                              width=STACK_LBL_W)
        self._stack_lbls["n_layer2"].pack(side="left")
        self._nl2_sp = self._spin(r, self.nl2_v, 0.0, 100000.0, width=10,
                                  step=IDX_STEP)
        self._nl2_sp.configure(command=self._commit_stack)
        for _seq in ("<Return>", "<FocusOut>"):
            self._nl2_sp.bind(_seq, self._commit_stack, add="+")
        self._nl2_sp.pack(side="left")
        a._lbl(r, text="Fixed", font=a._F(-1, "bold"),
               foreground=MUTED).pack(side="left", padx=(PAD_X, 0))
        self._tip(self._nl2_sp, "Refractive index of the second layer, read "
                                "from its material on every load. Shown "
                                "only while Layer 2 is ticked.")
        self._l2_row(r, dict(fill="x", pady=PAD_TIGHT))

        r = self._row(b, PAD_TIGHT)
        self._stack_lbls["n_sample"] = a._lbl(r, text="n sample",
                                              width=STACK_LBL_W)
        self._stack_lbls["n_sample"].pack(side="left")
        ns = self._spin(r, self.ns_v, 0.0, 100000.0, width=10,
                        step=IDX_STEP)
        ns.configure(command=self._commit_stack)
        ns.pack(side="left")
        for _seq in ("<Return>", "<FocusOut>"):
            ns.bind(_seq, self._commit_stack, add="+")
        self._tip_live(ns, lambda: self._tip_with_hint(
            "Refractive index the model stems are drawn from. Fit peaks "
            "writes the solved value back here.", "n_s"))
        self._sol_lbl["n_s"] = self._sol_cell(r, "n_s")

        for key, var, txt, sym, skey, tip in (
                ("d2", self.d2_v, "d2 upper medium (um)", "t_m",
                 "t_layer2",
                 "Thickness of the medium ABOVE the sample. With Lock In "
                 "on, changing it trades against t at a held total. The "
                 "solved value beside it is the medium TOTAL d1+d2."),
                ("t", self.t_v, "t sample (um)", "t_s", "t_s",
                 "Thickness of the sample itself."),
                ("d1", self.d1_v, "d1 lower medium (um)", "L", "L",
                 "Thickness of the medium BELOW the sample. With Lock In "
                 "on, changing it spreads the difference over d2 and t in "
                 "proportion. The solved value beside it is the whole "
                 "gap L = d1+t+d2.")):
            r = self._row(b, PAD_TIGHT)
            self._stack_lbls[key] = a._lbl(r, text=txt, width=STACK_LBL_W)
            self._stack_lbls[key].pack(side="left")
            sp = self._spin(r, var, 0.0, THICK_MAX_UM, width=8)
            sp.configure(command=lambda k=key: self._on_d_edit(k))
            sp.bind("<Return>", lambda e, k=key: self._on_d_edit(k))
            sp.pack(side="left")
            # one tooltip, rebuilt at hover: what the box does, and his
            # neighbour hint -- what the recorded points either side of this
            # pressure hold for the value beside it (15148-15158)
            self._tip_live(sp, lambda t=tip, k=skey:
                           self._tip_with_hint(t, k))
            self._sol_lbl[skey] = self._sol_cell(r, sym)

        r = self._row(b, PAD_GROUP)
        a._lbl(r, text="Total (um)", width=STACK_LBL_W).pack(side="left")
        self._total_sp = ttk.Spinbox(r, textvariable=self.total_v,
                                     from_=0.0, to=THICK_MAX_UM, width=8,
                                     increment=self._step(),
                                     command=self._on_total_edit)
        self._total_sp.bind("<Return>", lambda e: self._on_total_edit())
        self._total_sp.pack(side="left")
        self._spins = getattr(self, "_spins", []) + [self._total_sp]
        self._tip(self._total_sp, "d1 + t + d2. A mirror while unlocked; "
                                  "the driver while Lock In is ticked.")
        lt = ttk.Checkbutton(r, text="Lock In", variable=self.lock_v,
                             command=self._on_lock)
        lt.pack(side="left", padx=(PAD_X, 0))
        self._tip(lt, "Hold the total. d2 and t then trade against each "
                      "other. A d1 change spreads over d2 and t in "
                      "proportion, spilling when one empties. Editing the "
                      "Total itself grows d2, or drains d1, then d2, then t. "
                      "His redistribution rules, verbatim.")
        # The label gutter, the Total spinbox, Lock In and fine steps came
        # to 103 px more than the Fringe column is wide, and pack clips
        # what it cannot fit: "fine steps" showed as "fi" (R14 round 3).
        # It goes on the next line, indented to the same gutter.
        r = self._row(b, PAD_TIGHT)
        a._lbl(r, text="", width=STACK_LBL_W).pack(side="left")
        fs = ttk.Checkbutton(r, text="fine steps (\u00f7 10)",
                             variable=self.fine_v, command=self._sync_steps)
        fs.pack(side="left")
        self._tip(fs, "Step every spinbox at a tenth of the usual pace. It "
                      "covers thicknesses, Total and both low-pass cutoffs.")

        r = self._row(b, PAD_GROUP)
        a._lbl(r, text="Fit peaks:").pack(side="left")
        for mode, name, tip in (
                ("distinct", "Distinct",
                 "Distinct: fit the sample rectangle and sample-diamond as "
                 "SEPARATE peaks, each at its own stem. It then re-detects "
                 "every role and writes the solved n and t into the boxes "
                 "above, in one click."),
                ("shared", "Shared",
                 "Shared: fit the sample rectangle as a shoulder on the "
                 "sample-diamond's hump. It is one joint fit, one width, "
                 "with the offset kept ordered. It then re-detects and "
                 "writes the solved values back.")):
            img = self._fit_icon(mode == "shared")
            btn = ttk.Button(r, command=lambda m=mode:
                             self._fit_peaks_mode(m))
            if img is not None:
                btn.configure(image=img)
                btn.image = img
            else:
                btn.configure(text=name[0], width=3)
            btn.pack(side="left", padx=(PAD_X_TIGHT, 0))
            self._tip(btn, tip)
            self._fit_btns.append((btn, mode))
        # The two glyph buttons, Plot point and Results plot came to
        # 396 px on a 364 px column at text size 10 and Results plot was
        # cut by 35.  The two actions take their own row; they are not
        # "fit peaks" anyway.
        r = self._row(b, PAD_BTNROW)
        rp = a._brand_button(r, "Plot point", self._record_point)
        rp.pack(side="left", fill="x", expand=True)
        self._plot_btn = rp
        self._tip(rp, "Put this pressure point's solved values onto the "
                      "results series. That series is the in-memory record "
                      "Save session writes to disk.")
        rv = ttk.Button(r, text="Results plot",
                        command=self.results_view)
        rv.pack(side="left", fill="x", expand=True, padx=(PAD_X, 0))
        self._results_btn = rv
        self._tip(rv, "Open the recorded series as six panels against "
                      "pressure. A tick on this caption means the loaded "
                      "point is already on it.")

        self._seal_l2_rows()
        # the anvil box starts on its own model's value, not on the ambient
        # constant it was born holding
        self._sync_anvil_n()
        self._on_layer2()
        self._on_lock()
        self._sync_medium_row()
        self._relabel_stack()
        self._thick_snapshot()

    # ---- the P -> n row ---------------------------------------------------
    def _trace_pressure(self):
        """The loaded spectrum's own parsed pressure, or None."""
        rec = self._record()
        if rec is None:
            return None
        try:
            return float(rec.get("pressure_val"))
        except (TypeError, ValueError):
            return None

    def _model_pressure(self):
        """The pressure the index models are read at: the P box when it holds
        a number, the loaded spectrum's own otherwise."""
        s = str(self.dp_v.get()).strip()
        if s:
            try:
                v = float(s)
            except ValueError:
                v = None
            if v is not None and np.isfinite(v) and v >= 0.0:
                return v
        p = self._trace_pressure()
        return 0.0 if p is None else p

    def _dp_blank_restore(self, _e=None):
        """An empty P box takes the loaded spectrum's pressure back (his
        _dp_blank_restore, 9609-9615), so a stray delete cannot leave calc n
        without a pressure."""
        if str(self.dp_v.get()).strip():
            return
        p = self._trace_pressure()
        if p is not None:
            self._suspend = True
            try:
                self.dp_v.set("%g" % p)
            finally:
                self._suspend = False

    def _ref_wl(self):
        """The wavelength every index model is read at: his fringe-window
        centre, 0.5 * (FIT_WL_MIN + FIT_WL_MAX)."""
        lo, hi = _f(self.wlmin_v, 600.0), _f(self.wlmax_v, 800.0)
        if hi <= lo:
            lo, hi = 600.0, 800.0
        return 0.5 * (lo + hi)

    def _anvil_n(self, wl=None, P=None):
        """The anvil index the Anvil model gives at this point's pressure.

        His `_n_diamond_oscillator(0.5*(FIT_WL_MIN+FIT_WL_MAX), P)` when the
        model is the pressure-shifted oscillator, and whatever the picked
        model says otherwise.  Never raises: an unreadable box or an
        unknown model falls back on the ambient constant.
        """
        model = self.diamond_v.get()
        if model not in DIAMOND_MODELS:
            model = "constant"
        try:
            return float(fringe_optics.n_diamond(
                self._ref_wl() if wl is None else float(wl), model=model,
                pressure_gpa=(self._model_pressure() if P is None
                              else float(P))))
        except (ValueError, TypeError, ZeroDivisionError,
                FloatingPointError):
            return float(fringe_optics.N_DIAMOND_CONST)

    def _sync_anvil_n(self):
        """Write the Anvil model's index into the n diamond box.

        His load path and his calc n both set `num_vars['n_diamond']` from
        the point's own pressure; the box is what the stack model is built
        from, so every load, model pick and Ambient n comes through here.
        The write is guarded: the caller owns the redraw.
        """
        n = self._anvil_n()
        was = self._suspend
        self._suspend = True
        try:
            self.nd_v.set("%.4f" % n)
        except tk.TclError:
            pass
        finally:
            self._suspend = was
        return n

    def _sync_layer2_n(self):
        """Write the Layer 2 material's index into the n layer2 box.

        His `_apply_layer2_auto`: while a material is chosen the model is
        the source of truth, and it is re-read at every load.  With Layer 2
        off the box is left alone -- nothing reads it then.
        """
        try:
            if not self.layer2_on_v.get():
                return None
        except tk.TclError:
            return None
        n = self._index(self.layer2_v.get(), self._model_pressure(),
                        self._ref_wl())
        was = self._suspend
        self._suspend = True
        try:
            self.nl2_v.set("%.4f" % float(n))
        except (tk.TclError, TypeError, ValueError):
            pass
        finally:
            self._suspend = was
        return n

    def _on_anvil_var(self, *_a):
        """The Anvil combo moved: the box takes that model's value."""
        if self._suspend or not self._built:
            return
        self._sync_anvil_n()

    def _calc_n(self):
        """His calc n (_refine_n_diamond, 15195-15231).

        Every index a model owns is read at the P box's pressure and at the
        fringe window's centre wavelength: the anvil always, the medium and
        layer 2 when a model drives them.  The Medium set to Other leaves
        that box alone -- the number there is the reader's.
        """
        rec = self._record()
        if rec is None:
            self._status("load a spectrum first.", warn=True)
            return
        P = self._model_pressure()
        wl = self._ref_wl()
        # the anvil box always, and the Layer 2 box when a material drives
        # it -- his two writes, in his order
        n_dia = self._sync_anvil_n()
        said = ["n anvils %.4f" % n_dia]
        med = self.medium_v.get()
        if med != fringe_materials.MEDIUM_MANUAL:
            said.append("n %s %.4f" % (self._material_names()[0],
                                       self._index(med, P, wl)))
        n_l2 = self._sync_layer2_n()
        if n_l2 is not None:
            said.append("n %s %.4f" % (self._material_names()[2],
                                       float(n_l2)))
        self._status("at %g GPa and %.0f nm: %s." % (P, wl, ", ".join(said)))
        self._request_redraw(now=True)

    def _ambient_n(self):
        """His Ambient n button: the anvil back on the ambient constant.

        Our anvil index comes from the Anvil model rather than a typed
        number, and Constant 2.4168 IS that constant, so this picks the
        model that gives it.
        """
        self.diamond_v.set("constant")
        self._sync_anvil_n()
        self._status("anvil index on the ambient constant 2.4168.")
        self._commit_stack()

    def _reset_and_drop_point(self):
        """His Reset & drop point (11381-11416).

        Every input goes back to its shipped value and this pressure point
        comes off the results series.  The drop is in memory: the folder's
        continuity file still holds the point until a save rewrites it, and
        the status line says so.
        """
        self._restore_input_defaults()
        n0 = len(self._series)
        key = self._dkey()
        self._series = [q for q in self._series if self._pt_key(q) != key]
        dropped = len(self._series) != n0
        self._invalidate_json_cache()
        self._refresh_state_indicators()
        self._res_refresh()
        self._request_redraw(now=True)
        if not dropped:
            self._status("inputs back to their shipped values. the "
                         "results series is as it was.")
            return
        tail = ""
        if key is not None and self._point_status(key) != "absent":
            tail = (" %s still holds it; a save rewrites the file."
                    % SERIES_FILE)
        self._status("inputs back to their shipped values, and the recorded "
                     "point is off the series.%s" % tail)

    def _restore_input_defaults(self):
        """Every Stack input back to the value the program ships with."""
        d = SETTINGS_DEFAULTS
        self._suspend = True
        try:
            self.ns_v.set("%g" % d["fr_n_sample"])
            self.d1_v.set("%g" % d["fr_d1_um"])
            self.t_v.set("%g" % d["fr_t_um"])
            self.d2_v.set("%g" % d["fr_d2_um"])
            self.medium_n_v.set("%g" % d["fr_medium_n"])
            self.medium_v.set(d["fr_medium"])
            self.layer2_v.set(d["fr_layer2"])
            self.layer2_on_v.set(bool(d["fr_layer2_on"]))
            self.diamond_v.set(d["fr_diamond_model"])
            self.lock_v.set(bool(d["fr_lock_total"]))
            self.name_med_v.set(d["fr_medium_name"])
            self.name_samp_v.set(d["fr_sample_name"])
            self.name_l2_v.set(d["fr_layer2_name"])
            self.dp_v.set("")
            for c in CHANNELS:
                self.lp_shape_v[c].set("tanh")
                self.lp_roll_v[c].set("%g" % d["fr_lp_bg_roll"])
        except tk.TclError:
            pass
        finally:
            self._suspend = False
        tr = self._tr()
        if tr is not None:
            for role in ROLES:
                tr["roles"][role] = None
                tr["gauss"][role] = None
            tr["gauss"]["_sample_pair"] = None
            tr["solved"] = None
            tr.pop("seeded", None)
        # ...and the notch config on BOTH channels, his 11291-11295: a reset
        # that leaves hand-picked centres, unticked boxes, removed peaks and
        # custom widths behind is not the shipped state, and the mask the
        # main plot applies would still carry them.
        dk = self._dkey()
        if dk is not None:
            for c in CHANNELS:
                ch = self._chan.get((dk, c))
                if not ch:
                    continue
                ch["user_centers"] = []
                ch["unticked"] = set()
                ch["removed"] = set()
                ch["widths"] = {}
                ch["exact"] = {}
                ch["user_fundamental"] = None
            self._notch_sig = None
        self._on_layer2()
        self._on_lock()
        self._sync_medium_row()
        self._relabel_stack()
        self._dp_blank_restore()
        # the two model-owned index boxes go back to what their shipped
        # models say at this point's pressure, not to a stored number
        self._sync_anvil_n()
        self._sync_layer2_n()

    # ---- neighbour hints (his 12876-12894 + 15148-15158) ------------------
    def _neighbour_rows(self):
        """(below, above) recorded points straddling this trace's pressure.

        The ACTIVE series only, so a hint never mixes another folder's
        numbers in.  A point at the same pressure is neither: it is this
        one's own twin, not a neighbour.
        """
        p_now = self._trace_pressure()
        if p_now is None:
            return None, None
        below = above = None
        for row in self._series:
            pg = row.get("pressure")
            if pg is None or abs(float(pg) - p_now) < 1e-6:
                continue
            pg = float(pg)
            if pg < p_now and (below is None
                               or pg > float(below["pressure"])):
                below = row
            elif pg > p_now and (above is None
                                 or pg < float(above["pressure"])):
                above = row
        return below, above

    def _tip_with_hint(self, text, key):
        """One box's tooltip: what it does, then its neighbour hint when the
        series has recorded points either side of this pressure."""
        hint = self._hint_for(key)
        return (text + "\n\n" + hint) if hint else text

    def _hint_for(self, key):
        """The hover text on one input box: what the recorded points either
        side of this pressure solved for the value beside it."""
        below, above = self._neighbour_rows()
        if below is None and above is None:
            return ""
        disp = {"n_s": "n sample", "t_s": "t sample",
                "t_layer2": "medium total", "L": "whole gap"}.get(key, key)

        def _one(row):
            if row is None:
                return "–"
            sol = self._resolve_point(row)
            v = None if sol is None else sol.get(key)
            if v is None or not np.isfinite(v):
                return "–"
            return "%.4g at %g GPa" % (float(v), float(row["pressure"]))
        return ("Recorded neighbours (%s): %s to %s. The nearest lower "
                "pressure, then the nearest higher one."
                % (disp, _one(below), _one(above)))

    def _sol_cell(self, row, sym):
        """One solved-readout cell: 'sym =' then the bold value."""
        a = self.app
        a._lbl(row, text="%s =" % sym,
               foreground=MUTED).pack(side="left", padx=(PAD_X, 0))
        lab = a._lbl(row, text="\u2013", font=a._F(0, "bold", mono=True))
        lab.pack(side="left", padx=(PAD_X_TIGHT, 0))
        return lab

    def _fit_icon(self, shared):
        """The two Fit-peaks glyphs: his icon pair.  Distinct shows the
        rectangle and diamond apart; Shared shows them abutting, because
        the two roles share one fitted hump.  Drawn with PIL at 2x and
        downsampled, like the app's icon set (rule 31)."""
        try:
            from PIL import Image, ImageDraw, ImageTk
        except Exception:
            return None
        ink = self._pal()[1]
        key = ("fit_shared" if shared else "fit_distinct", ink)
        if key in self._icon_cache:
            return self._icon_cache[key]
        im = Image.new("RGBA", (48, 28), (0, 0, 0, 0))
        d = ImageDraw.Draw(im)
        W = 3
        if shared:
            d.rectangle([6, 8, 22, 20], outline=ink, width=W)
            pts = [(22, 14), (31, 5), (40, 14), (31, 23), (22, 14)]
        else:
            d.rectangle([2, 8, 18, 20], outline=ink, width=W)
            pts = [(28, 14), (37, 5), (46, 14), (37, 23), (28, 14)]
        d.line(pts, fill=ink, width=W, joint="curve")
        img = ImageTk.PhotoImage(im.resize((24, 14), Image.LANCZOS))
        if len(self._icon_cache) > 12:
            self._icon_cache.clear()
        self._icon_cache[key] = img
        return img

    def _on_layer2(self):
        try:
            self._l2_cb.configure(state=("readonly" if self.layer2_on_v.get()
                                         else "disabled"))
        except tk.TclError:
            pass
        self._sync_l2_rows()
        self._sync_layer2_n()
        self._commit_stack()

    def _on_lock(self):
        """His _sync_lock: enable the Total with the box, re-snapshot so
        the first edit either way has a fresh baseline, and seed the
        Total display from the current sum."""
        on = self.lock_v.get()
        try:
            self._total_sp.configure(state=("normal" if on else "disabled"))
        except (AttributeError, tk.TclError):
            pass
        self._thick_snapshot()
        pv = self._prev_thick or {}
        try:
            self.total_v.set("%.4g" % ((pv.get("d1") or 0.0)
                                       + (pv.get("t") or 0.0)
                                       + (pv.get("d2") or 0.0)))
        except tk.TclError:
            pass

    def _sync_medium_row(self, *_a):
        manual = self.medium_v.get() == fringe_materials.MEDIUM_MANUAL
        try:
            if manual:
                self._nmed_lbl.pack_forget()
                self._nmed_e.pack(side="left")
            else:
                self._nmed_e.pack_forget()
                self._nmed_lbl.pack(side="left")
        except (AttributeError, tk.TclError):
            pass

    # ---- Lock In: his redistribution rules, verbatim ----------------------
    def _thick_snapshot(self):
        pv = getattr(self, "_prev_thick", None)
        if pv is None:
            pv = self._prev_thick = {"d1": None, "t": None, "d2": None}
        for k, var in (("d1", self.d1_v), ("t", self.t_v),
                       ("d2", self.d2_v)):
            try:
                pv[k] = float(str(var.get()).strip())
            except (ValueError, tk.TclError):
                pass

    def _set_thick(self, key, val):
        var = {"d1": self.d1_v, "t": self.t_v, "d2": self.d2_v}[key]
        var.set("%.4g" % max(0.0, float(val)))

    def _on_d_edit(self, key):
        """A thickness spinbox was edited.  Unlocked: refresh the Total
        mirror and redraw.  Locked: hold the total by redistributing --
        d2 and t trade off (the partner clamped at 0, after which the
        total may grow); d1 splits its change across d2 and t in
        proportion to their current sizes, spilling the remainder when
        one empties.  Matthew's _on_d_edit, line for line."""
        if getattr(self, "_thick_busy", False):
            return
        var = {"d1": self.d1_v, "t": self.t_v, "d2": self.d2_v}[key]
        try:
            new = float(str(var.get()).strip())
        except (ValueError, tk.TclError):
            self._status("that is not a number.", warn=True)
            return
        pv = getattr(self, "_prev_thick", None) or {}
        if self.lock_v.get() and pv.get(key) is not None:
            delta = new - pv[key]
            self._thick_busy = True
            try:
                self._set_thick(key, new)      # honour the edit verbatim
                if key in ("t", "d2"):
                    other = "d2" if key == "t" else "t"
                    self._set_thick(other, (pv.get(other) or 0.0) - delta)
                else:            # d1: split -delta over d2 and t pro rata
                    pool = (pv.get("d2") or 0.0) + (pv.get("t") or 0.0)
                    if pool > 0:
                        d2n = ((pv.get("d2") or 0.0)
                               - delta * ((pv.get("d2") or 0.0) / pool))
                        tn = ((pv.get("t") or 0.0)
                              - delta * ((pv.get("t") or 0.0) / pool))
                    elif delta < 0:      # both empty, d1 shrinking
                        d2n = tn = -delta / 2.0
                    else:                # both empty, d1 growing
                        d2n = tn = 0.0
                    if d2n < 0:          # d2 cannot absorb -> spill to t
                        tn += d2n
                        d2n = 0.0
                    if tn < 0:           # t cannot absorb -> spill back
                        d2n += tn
                        tn = 0.0
                    if d2n < 0:          # both exhausted -> floor
                        d2n = 0.0
                    self._set_thick("d2", d2n)
                    self._set_thick("t", tn)
            finally:
                self._thick_busy = False
        self._thick_snapshot()
        if not self.lock_v.get():
            try:
                self.total_v.set("%.4g" % (_f(self.d1_v, 0.0)
                                           + _f(self.t_v, 0.0)
                                           + _f(self.d2_v, 0.0)))
            except tk.TclError:
                pass
        self._commit_stack()

    def _commit_stack(self, *_a):
        """A committed stack edit: the auto glyphs follow the model.

        His GUI re-runs the snap-and-refine inside every _update, so the
        glyphs track the inputs live.  Here it hangs off the COMMITTED edits
        -- Return, focus out, a spinbox arrow, a combobox pick -- because a
        keystroke-by-keystroke refit would fit a half-typed number.  A glyph
        you placed is never touched; only the auto ones move.  The readout
        is re-solved when there is one, so it keeps describing the glyphs.
        """
        if self._suspend or not self._built:
            return
        tr = self._tr()
        if tr is None:
            self._request_redraw()
            return
        self._autosnap_roles()
        if tr.get("solved"):
            self._solve(quiet=True)
        self._request_redraw()

    def _on_total_edit(self):
        """The Total spinbox was edited (reachable only while locked).
        Increase: all of it goes to d2.  Decrease: drain d1, then d2,
        then t, each floored at zero.  His _on_total_edit, verbatim."""
        if getattr(self, "_thick_busy", False):
            return
        try:
            new_total = float(str(self.total_v.get()).strip())
        except (ValueError, tk.TclError):
            self._status("that is not a number.", warn=True)
            return
        pv = getattr(self, "_prev_thick", None) or {}
        cur = ((pv.get("d1") or 0.0) + (pv.get("t") or 0.0)
               + (pv.get("d2") or 0.0))
        delta = new_total - cur
        self._thick_busy = True
        try:
            if delta >= 0:
                self._set_thick("d2", (pv.get("d2") or 0.0) + delta)
            else:
                rem = -delta
                for k in ("d1", "d2", "t"):
                    have = pv.get(k) or 0.0
                    take = min(have, rem)
                    self._set_thick(k, have - take)
                    rem -= take
                    if rem <= 0:
                        break
        finally:
            self._thick_busy = False
        self._thick_snapshot()
        self._commit_stack()

    def _fit_peaks_mode(self, mode):
        """His one-click peak workflow (_redetect_and_apply): pick the
        Sample fit strategy, hand every role back to auto, re-seed on the
        model stems, Gaussian-refine in that mode, solve, and write the
        solved geometry into the inputs.

        Every role goes back to auto by design, his included -- a drag is
        honoured by the write-back that follows it (the stems move onto the
        dragged glyph), so a later re-detect anchors there instead of on a
        stale prediction.
        """
        self.fitmode_v.set(mode)
        tr = self._tr()
        rec = self._record()
        if tr is None or rec is None:
            self._status("load a spectrum first.", warn=True)
            return
        was = self._role_positions()      # what the press is measured against
        for role in ROLES:
            tr["roles"][role] = None
            tr["gauss"][role] = None
        tr["gauss"]["_sample_pair"] = None
        tr["seeded"] = False
        self._seed_said.pop(self._dkey(), None)
        p = self._stack_params(rec)
        # the re-detect is the stack model's own workflow: it re-seeds on the
        # model stems, never on the tallest peak
        self._seed_roles(p, self._x_upper(p), allow_align=False)
        msg = self._fit_peaks(before=was)
        applied = self._apply_solved()
        if msg:
            self._status(msg)         # the fit outcome is the headline
        if not applied:               # _apply_solved owns the redraw when it
            self._request_redraw(now=True)      # lands; this covers when it
        self._sync_action_marks()               # cannot

    # ---- SESSION ----------------------------------------------------------
    def _card_session(self):
        b = self.app._group(self.sidebar_parent, "Session")
        a = self.app
        self.series_nav_v = tk.StringVar(value="\u2013 (no parent loaded)")

        r = self._row(b)
        lp = ttk.Button(r, text="Load parent folder...",
                        command=self._load_parent_folder)
        lp.pack(side="left", fill="x", expand=True)
        self._tip(lp, "Pick a folder that CONTAINS series subfolders of "
                      "*_absorbance.csv spectra. The dropdown below then "
                      "jumps between them; each series opens at its "
                      "lowest pressure.")
        lr = ttk.Button(r, text="Load raw spectra...",
                        command=self._load_raw_spectra)
        lr.pack(side="left", fill="x", expand=True, padx=(PAD_X, 0))
        self._tip(lr, "Pick one *_absorbance.csv. Its whole folder loads "
                      "as the working series and the Pressure point "
                      "dropdown fills with its siblings.")

        r = self._row(b, PAD_TIGHT)
        nx = ttk.Button(r, text="\u25b6", width=2,
                        command=lambda: self._step_series(1))
        nx.pack(side="right")
        pv = ttk.Button(r, text="\u25c0", width=2,
                        command=lambda: self._step_series(-1))
        pv.pack(side="left")
        self._series_cb = ttk.Combobox(r, textvariable=self.series_nav_v,
                                       state="readonly", width=16)
        self._series_cb.pack(side="left", fill="x", expand=True,
                             padx=(PAD_X_TIGHT, PAD_X_TIGHT))
        self._series_cb.bind("<<ComboboxSelected>>", self._on_series_pick)
        self._series_nav_btns = (pv, nx)
        self._tip(self._series_cb,
                  "The series subfolders under the loaded parent. Pick one "
                  "to jump straight to it.")
        self._tip(pv, "Previous series folder under the parent.")
        self._tip(nx, "Next series folder under the parent.")

        self._series_lbl = a._lbl(b, text="Series: \u2013",
                                  foreground=MUTED)
        self._series_lbl.pack(fill="x", pady=PAD_BTNROW)
        self._wrap_to_card(self._series_lbl)

        r = self._row(b, PAD_GROUP)
        sv = ttk.Button(r, text="Save session", width=13,
                        command=self.save_series)
        sv.pack(side="left", fill="x", expand=True)
        self._tip_live(sv, self._save_tip)
        ld = ttk.Button(r, text="Load session", width=13,
                        command=self.load_series)
        ld.pack(side="left", fill="x", expand=True, padx=(PAD_X, 0))
        self._tip(ld, "Read series_continuity.json back in. The tool looks "
                      "where the last save put it, then beside the input "
                      "data. A file the original program's batch mode left "
                      "with the spectra is found there.")
        r = self._row(b, PAD_BTNROW)
        lf = ttk.Button(r, text="Load session file...",
                        command=self.load_session_file)
        lf.pack(side="left", fill="x", expand=True)
        self._tip(lf, "Open a saved session by name: a session_*.json "
                      "point snapshot or a series_continuity.json. Files "
                      "the original program wrote open here too.")

        self._state_lbl = a._lbl(b, text="", font=a._F(0, mono=True))
        self._slot(self._state_lbl, fill="x", pady=PAD_TIGHT)
        self._tip(self._state_lbl,
                  "%s saved and identical to disk, %s changed in memory, %s "
                  "waiting for the first point." % (IND_SAVED, IND_DIRTY,
                                                IND_NONE))
        self._series_disk_lbl = a._lbl(b, text="", font=a._F(0, mono=True))
        self._slot(self._series_disk_lbl, fill="x", pady=PAD_TIGHT)
        self._tip(self._series_disk_lbl,
                  "%s the saved file holds exactly these points, %s memory "
                  "and file differ, %s waiting for the first save."
                  % (IND_SAVED, IND_DIRTY, IND_NONE))

    def _save_tip(self):
        """What a save would write, listed at the moment of asking.

        Matthew's _ssave_tip: the pending work is readable on hover, so
        finding out what is unsaved costs no prompt.
        """
        base = ("Writes series_continuity.json beside the input data, plus a "
                "timestamped copy. It carries the recorded points and each "
                "point's own inputs: its numbers, its notch list and its "
                "role glyphs. A data folder inside the program, or a "
                "read-only one, sends them to your output folder.")
        why = self._series_diff()
        if not why:
            return base + "\n\nThe file already matches memory."
        lines = "\n".join("  • " + w for w in why[:DIRTY_CAP])
        if len(why) > DIRTY_CAP:
            lines += "\n  • ...and %d more" % (len(why) - DIRTY_CAP)
        return base + "\n\nA save would change:\n" + lines

    # ---- Session loading: spectra straight into the workbench -------------
    @staticmethod
    def _parse_pressure_name(name):
        import re
        m = re.search(r"_(\d+p\d+)[Dd]?_", name)
        return float(m.group(1).replace("p", ".")) if m else None

    @staticmethod
    def _is_decomp_name(name):
        import re
        return bool(re.search(r"_\d+p\d+[Dd]_", name))

    def _load_raw_spectra(self):
        fp = filedialog.askopenfilename(
            title="Select a *_absorbance.csv",
            initialdir=self._input_folder() or os.getcwd(),
            filetypes=[("Absorbance CSV", "*_absorbance.csv"),
                       ("CSV", "*.csv"), ("All files", "*.*")],
            parent=self.app.root)
        if not fp:
            return
        if not self._leave_guard():
            return
        stem = os.path.splitext(os.path.basename(fp))[0]
        self._load_local_folder(os.path.dirname(fp), want_stem=stem)

    def _load_parent_folder(self):
        d = filedialog.askdirectory(
            title="Select the parent folder of the data series",
            initialdir=self._input_folder() or os.getcwd(),
            parent=self.app.root)
        if not d:
            return
        subs = self._scan_series_folders(d)
        if not subs:
            self._status("the workbench looks for a subfolder of "
                         "*_absorbance.csv files under %s."
                         % os.path.basename(d), warn=True)
            return
        if not self._leave_guard():
            return
        self._parent_nav = {"parent": d, "folders": subs, "idx": 0}
        self._load_local_folder(subs[0])

    @staticmethod
    def _scan_series_folders(parent):
        import glob as _glob
        out = []
        try:
            names = sorted(os.listdir(parent), key=lambda s: s.lower())
        except OSError:
            return out
        for name in names:
            p = os.path.join(parent, name)
            if (os.path.isdir(p)
                    and _glob.glob(os.path.join(p, "*_absorbance.csv"))):
                out.append(p)
        return out

    def _load_local_folder(self, folder, want_stem=None):
        """Read one folder of *_absorbance.csv spectra and make them the
        working set, ordered along the experiment's path -- compression
        ascending, then decompression descending (his _pressure_key)."""
        recs = self._read_folder(folder)
        if not recs:
            self._status("reading *_absorbance.csv in %s failed."
                         % os.path.basename(folder), warn=True)
            return
        # a folder switch is a SERIES switch: the in-memory series belongs
        # to the outgoing folder, so offer to save it, then start clean
        # (his _confirm_leave_series + _switch_active_series discipline)
        old = (getattr(self, "_local", None) or {}).get("folder")
        if self._series and old != folder:
            ans = messagebox.askyesnocancel(
                "Fringe workbench",
                "The current series holds %d plotted point(s) from another "
                "folder.\n"
                "\n"
                "Yes: save the continuity file, then switch\n"
                "No: switch and leave it unsaved\n"
                "Cancel: stay where you are" % len(self._series),
                parent=self.app.root)
            if ans is None:
                return
            if ans:
                self.save_series()
            self._series = []
            self._msv_cache.clear()
        if old is not None and old != folder:
            self._clear_series_state()
        app_sig = tuple(r.get("label") for r in
                        (getattr(self.app, "results", None) or []))
        self._local = {"folder": folder, "recs": recs, "app_sig": app_sig}
        self._wr_cache.clear()
        self._series_disk = None
        self._series_path = None
        self._invalidate_json_cache()
        want = None
        if want_stem:
            for r in recs:
                if r.get("stem") == want_stem:
                    want = r["label"]
                    break
        self._label = None
        self._load_busy = True
        try:
            self.on_trace_change(want)
        finally:
            self._load_busy = False
        self._adopt_legacy_disk()
        if self._apply_point_inputs():
            self._invalidate(every=True)         # the picture is the restored one
        self._sync_series_nav(folder)
        self._refresh_state_indicators()
        self._status("loaded %d spectra from %s."
                     % (len(recs), os.path.basename(folder)))
        # a continuity file beside the data is an offer, like his
        for cand in self._series_read_paths():
            if os.path.isfile(cand):
                if messagebox.askyesno(
                        "Fringe workbench",
                        "This folder has saved continuity. Yes loads its "
                        "recorded points.", parent=self.app.root):
                    self.load_series()
                break

    def _clear_series_state(self):
        """Drop every per-trace working set on a series switch.

        One series is held at a time, which is Matthew's model and the only
        one the continuity file can put back.  Before this, a folder switch
        left _chan, _trace, _disk, _fits and _fit_history behind: keyed by
        the display label, two folders that both held a "20 GPa" point
        silently shared one set of notches, role glyphs and fits.  The keys
        are stems now, so the sharing is gone either way; the clear is what
        keeps the memory, the leave guard and the markers about the series
        actually on screen.
        """
        self._chan.clear()
        self._trace.clear()
        self._disk.clear()
        self._inputs.clear()
        self._inputs_extra.clear()
        self._live_inputs.clear()
        self._fits.clear()
        self._cache.clear()
        self._msv_cache.clear()
        self._seed_said.clear()
        self._dk_cache = {}
        del self._fit_history[:]
        self._fill_history()
        self._notch_sig = None

    def _read_folder(self, folder):
        """Parse every *_absorbance.csv in `folder` (the frozen schema:
        Wavelength_nm ... Background, Sample) into workbench records."""
        import glob as _glob
        paths = _glob.glob(os.path.join(folder, "*_absorbance.csv"))

        def _key(p):
            name = os.path.basename(p)
            pr = self._parse_pressure_name(name)
            tie = (len(name), name.lower())
            if pr is None:
                return (2, 0.0) + tie
            return ((1, -pr) + tie if self._is_decomp_name(name)
                    else (0, pr) + tie)

        recs = []
        for p in sorted(paths, key=_key):
            try:
                arr = np.genfromtxt(p, delimiter=",", names=True)
            except (OSError, ValueError):
                continue
            names = arr.dtype.names or ()

            def _col(want, _names=names, _arr=arr):
                for nm in _names:
                    if want.lower() in nm.lower():
                        return np.asarray(_arr[nm], float)
                return None

            wl = _col("Wavelength")
            bg = _col("Background")
            sm = _col("Sample")
            if wl is None or bg is None or sm is None or wl.size < 8:
                continue
            name = os.path.basename(p)
            stem = os.path.splitext(name)[0]
            pr = self._parse_pressure_name(name)
            dec = self._is_decomp_name(name)
            label = (("%g GPa" % pr) + (" (D)" if dec else "")
                     if pr is not None else stem)
            recs.append({"label": label, "stem": stem, "path": p,
                         "wl": wl, "bg_c": bg, "samp_c": sm,
                         "pressure_val": pr,
                         "pressure_str": (("%g" % pr).replace(".", "p")
                                          if pr is not None else ""),
                         "branch": "D" if dec else "C"})
        # duplicate labels get the stem appended: uniqueness is what the
        # dropdown's routing rides on
        seen = {}
        for r in recs:
            seen.setdefault(r["label"], []).append(r)
        for lab, group in seen.items():
            if len(group) > 1:
                for r in group:
                    r["label"] = "%s (%s)" % (lab, r["stem"])
        return recs

    def _sync_series_nav(self, folder):
        nav = getattr(self, "_parent_nav", None)
        if not nav or folder not in (nav.get("folders") or []):
            parent = os.path.dirname(os.path.normpath(folder))
            subs = self._scan_series_folders(parent)
            if folder not in subs:
                subs = [folder]
            nav = self._parent_nav = {"parent": parent, "folders": subs,
                                      "idx": subs.index(folder)}
        else:
            nav["idx"] = nav["folders"].index(folder)
        self._refresh_series_nav_ui()

    def _refresh_series_nav_ui(self):
        cb = getattr(self, "_series_cb", None)
        nav = getattr(self, "_parent_nav", None)
        if cb is None:
            return
        try:
            if not nav or not nav.get("folders"):
                cb["values"] = []
                self.series_nav_v.set("\u2013 (no parent loaded)")
            else:
                folders = nav["folders"]
                n = len(folders)
                vals = ["%d/%d: %s" % (i + 1, n,
                                       os.path.basename(folders[i]))
                        for i in range(n)]
                cb["values"] = vals
                i = nav.get("idx", -1)
                self.series_nav_v.set(vals[i] if 0 <= i < n else "")
        except tk.TclError:
            return
        btns = getattr(self, "_series_nav_btns", None)
        if btns:
            i = (nav or {}).get("idx", -1)
            n = len((nav or {}).get("folders") or [])
            try:
                btns[0].state(["disabled"] if i <= 0 else ["!disabled"])
                btns[1].state(["disabled"] if (i < 0 or i >= n - 1)
                              else ["!disabled"])
            except tk.TclError:
                pass

    def _step_series(self, d):
        nav = getattr(self, "_parent_nav", None)
        if not nav or not nav.get("folders"):
            self._status("load a parent folder first.", warn=True)
            return
        i = nav.get("idx", -1) + d
        if i < 0 or i >= len(nav["folders"]):
            return
        if not self._leave_guard():
            return
        nav["idx"] = i
        self._load_local_folder(nav["folders"][i])

    def _on_series_pick(self, _e=None):
        nav = getattr(self, "_parent_nav", None)
        cb = getattr(self, "_series_cb", None)
        if not nav or cb is None:
            return
        try:
            i = cb.current()
        except tk.TclError:
            i = -1
        if i is None or i < 0 or i == nav.get("idx"):
            self._refresh_series_nav_ui()
            return
        if not self._leave_guard():
            self._refresh_series_nav_ui()
            return
        nav["idx"] = i
        self._load_local_folder(nav["folders"][i])

    # ---- PRESSURE POINT ---------------------------------------------------
    def _card_pressure(self):
        b = self.app._group(self.sidebar_parent, "Pressure point")
        a = self.app
        r = self._row(b)
        nx = ttk.Button(r, text="\u25b6", width=2,
                        command=lambda: self._step_trace(1))
        nx.pack(side="right")
        pv = ttk.Button(r, text="\u25c0", width=2,
                        command=lambda: self._step_trace(-1))
        pv.pack(side="left")
        self._trace_cb = ttk.Combobox(r, textvariable=self.trace_v,
                                      state="readonly", width=18)
        self._trace_cb.pack(side="left", fill="x", expand=True,
                            padx=(PAD_X_TIGHT, PAD_X_TIGHT))
        self._trace_cb.bind("<<ComboboxSelected>>", self._on_trace_pick)
        self._pressure_btns = (pv, nx)
        self._tip(self._trace_cb,
                  "The pressure points of this series, in the order the "
                  "experiment ran them: up the compression run, then "
                  "back down the decompression leg. This is the only "
                  "picker; the arrows walk the same list.\n"
                  "\n"
                  "%s this point is in series_continuity.json as it stands "
                  "here. %s the file holds it with other values. A plain "
                  "label is a point the file has yet to see."
                  % (IND_SAVED, IND_DIRTY))
        self._tip(pv, "Previous pressure point along the experiment's "
                      "path. Page Up does the same.")
        self._tip(nx, "Next pressure point along the experiment's path. "
                      "Page Down does the same.")

    def _ordered_recs(self):
        """The records along the experiment's path: compression ascending,
        then decompression descending -- his _pressure_key, applied to
        whatever the working set is."""
        def _key(r):
            pr = r.get("pressure_val")
            name = str(r.get("label") or "")
            tie = (len(name), name.lower())
            try:
                pr = None if pr is None else float(pr)
            except (TypeError, ValueError):
                pr = None
            if pr is None:
                return (2, 0.0) + tie
            dec = (r.get("branch") or "C") == "D"
            return ((1, -pr) + tie) if dec else ((0, pr) + tie)
        return sorted(self._records(), key=_key)

    def _refresh_pressure_nav_ui(self):
        btns = getattr(self, "_pressure_btns", None)
        if not btns:
            return
        names = [r["label"] for r in self._ordered_recs()]
        try:
            i = names.index(self._label)
        except ValueError:
            i = -1
        try:
            btns[0].state(["disabled"] if i <= 0 else ["!disabled"])
            btns[1].state(["disabled"] if (i < 0 or i >= len(names) - 1)
                          else ["!disabled"])
        except tk.TclError:
            pass

    # ---- FFT REMOVAL: the main cleaning tool ------------------------------
    def _card_removal(self):
        b = self.app._group(self.sidebar_parent, "FFT removal")
        a = self.app
        for chan in CHANNELS:
            a._subhead(b, chan)
            # The switch, the cutoff and Clear notches came to 411 px on a
            # 364 px column at text size 10: pack DROPPED the unit label
            # and squeezed the spinbox by 25 px.  Clear notches takes the
            # next line, full width, so nothing is cut (rule 14).
            r = self._row(b, PAD_TIGHT)
            cb = ttk.Checkbutton(r, text="Low-pass cutoff",
                                 variable=self.lp_on_v[chan],
                                 command=lambda c=chan:
                                 self._on_lp_toggle(c))
            cb.pack(side="left")
            a._lbl(r, text="um").pack(side="right", padx=(PAD_X_TIGHT, 0))
            sp = self._spin(r, self.lp_v[chan], LP_MIN_UM, LP_MAX_UM, width=6)
            sp.configure(command=lambda c=chan: self._on_lp_edit(c))
            sp.bind("<Return>", lambda e, c=chan: self._on_lp_edit(c))
            sp.bind("<FocusOut>",
                    lambda e, c=chan: self._on_lp_edit(c, quiet=True))
            sp.pack(side="right", padx=(PAD_X, 0))
            # The edge that cutoff rolls off over: its shape and its width.
            # Beside the cutoff, because the three describe one filter.
            r = self._row(b, PAD_TIGHT)
            a._lbl(r, text="Edge", width=LBL_W2).pack(side="left")
            ecb = a._mapped_combo(r, self.lp_shape_v[chan], LP_SHAPE_LABELS,
                                  command=lambda c=chan:
                                  self._on_lp_edge_edit(c), width=13)
            ecb.pack(side="left")
            a._lbl(r, text="um").pack(side="right", padx=(PAD_X_TIGHT, 0))
            rs = self._spin(r, self.lp_roll_v[chan], 0.1, 40.0, width=5)
            rs.configure(command=lambda c=chan: self._on_lp_edge_edit(c))
            rs.bind("<Return>", lambda e, c=chan: self._on_lp_edge_edit(c))
            rs.bind("<FocusOut>", lambda e, c=chan: self._on_lp_edge_edit(c))
            rs.pack(side="right", padx=(PAD_X, 0))
            self._tip(ecb, "The shape of the low-pass edge. Tanh is the "
                           "shipped one. Error function falls a little "
                           "steeper over the same width. Hard cuts at the "
                           "cutoff itself.")
            self._tip(rs, "The width the edge rolls off over, in micron of "
                          "n*t. One width past the cutoff, tanh keeps 12% "
                          "of the signal and the error function 8%. Hard "
                          "reads 0 either way.")
            r = self._row(b, PAD_BTNROW)
            clr = ttk.Button(r, text="Clear notches",
                             command=lambda c=chan:
                             self._clear_notches_for(c))
            clr.pack(side="left", fill="x", expand=True)
            self._tip(cb, "The main cleaning tool: a soft low-pass. It "
                          "removes every ripple above the cutoff in n*t, on "
                          "top of this channel's notches. It is one combined "
                          "mask, applied once. The dashed line on the chart "
                          "is the same control. Drag it.")
            self._tip(sp, "This channel's cutoff, in micron of n*t. "
                          "1 to 200, the range the dragged line clamps to.")
            self._tip(clr, "Take every notch off this channel, keeping the "
                           "fundamental in the list but unticked, ready to "
                           "re-enable. The saved notches file stays as it is.")
        r = self._row(b, PAD_GROUP)
        ec = ttk.Button(r, text="Export cleaned spectrum",
                        command=self._export_cleaned)
        ec.pack(side="left", fill="x", expand=True)
        self._tip(ec, "Write the cleaned spectrum, the red FFT filtered "
                      "curve, per channel to CSV. The columns are "
                      "Wavenumber_cm, Background_notch, Sample_notch and "
                      "Absorbance_notch, his exactly.")
        nl = ttk.Button(r, text="Notch list", width=11,
                        command=self._open_notch_list)
        nl.pack(side="left", fill="x", expand=True, padx=(PAD_X, 0))
        self._tip(nl, "Open the notch list: every centre, its own "
                      "half-width, the fundamental flag. Click peaks on "
                      "the chart to add or remove them.")
        r = self._row(b, PAD_BTNROW)
        wn = ttk.Button(r, text="Write notches file for batch",
                        command=self.export_notch_overrides)
        wn.pack(side="left", fill="x", expand=True)
        self._tip(wn, "Write notch_overrides.csv beside the data. It holds "
                      "every centre and half-width you picked, for every "
                      "spectrum in this session. Rows for other spectra "
                      "stay. The form is the one the batch pipeline reads "
                      "back.")
        dn = ttk.Button(r, text="Delete notches file", width=18,
                        command=self._delete_notches_file)
        dn.pack(side="left", fill="x", expand=True, padx=(PAD_X, 0))
        self._tip(dn, "Remove this spectrum's saved rows from "
                      "notch_overrides.csv; the file goes too once it "
                      "is empty. The live notches on the chart stay.")
        self._notch_file_lbl = a._lbl(b, text="", foreground=MUTED)
        self._slot(self._notch_file_lbl, fill="x", pady=PAD_TIGHT)

    def _lp_edge(self, chan):
        """(shape, roll-off um) of one channel's low-pass edge.

        Read through one method so the mask, the preview curve, the cache
        signature, the per-point snapshot and what defringe applies can never
        disagree about which edge this channel has.
        """
        shape = str(self.lp_shape_v[chan].get())
        if shape not in LP_EDGE_SHAPES:
            shape = "tanh"
        roll = _f(self.lp_roll_v[chan], 2.0)
        return shape, (roll if roll > 0 else 2.0)

    def _lp_cut_or_none(self, chan):
        """This channel's cutoff, or None for "no low-pass at all".

        One reader for the mask, the config, the recipe, the preview curve,
        the drawn line and the per-point snapshot, so none of them can
        disagree with the box about whether a low-pass is running at all.
        """
        try:
            return _lp_cut_um(self.lp_v[chan])
        except (KeyError, AttributeError):
            return None

    def _on_lp_toggle(self, chan):
        self._lp_last[chan] = self.lp_v[chan].get()
        self._invalidate(now=False, every=True)

    def _on_lp_edge_edit(self, chan):
        """A committed edge edit.  Like a cutoff edit, it changes the mask
        the main plot's df switch applies, so the host hears about it too;
        a plain <FocusOut> with nothing changed costs one signature compare
        in the debounced redraw."""
        if self._rebuilding:
            return
        cur = self._lp_edge(chan)
        if cur == self._lp_edge_last.get(chan):
            return
        self._lp_edge_last[chan] = cur
        self._invalidate(now=False, every=True)

    def _on_lp_edit(self, chan, quiet=False):
        """Live cutoff edits redraw; a FocusOut with nothing changed does
        not (his _make_lp_apply guard).  Debounced: the spinbox arrows
        repeat, and one held arrow used to run a full redraw per step."""
        cur = self.lp_v[chan].get()
        if quiet and cur == self._lp_last.get(chan):
            return
        self._lp_last[chan] = cur
        self._invalidate(now=False, every=True)

    def _clear_notches_for(self, chan):
        """His Clear notches: drop every harmonic and manual notch on
        this channel but KEEP the fundamental in the list, unticked,
        ready to re-enable.  The saved notches file is not touched
        (that is Delete notches file)."""
        ch = self._ch(chan)
        if ch is None:
            self._status("no %s data loaded." % chan, warn=True)
            return
        defaults = list(ch.get("default_centers") or [])
        fund = defaults[0] if defaults else None
        keys = set(defaults) | set(ch.get("user_centers") or [])
        keys.discard(fund)
        ch["removed"] |= keys
        ch["user_centers"] = [k for k in ch["user_centers"] if k == fund]
        if fund is not None:
            ch["unticked"].add(fund)
        self._notch_sig = None
        self._status("cleared %s notches. the fundamental stays listed, "
                     "unticked." % chan)
        self._invalidate()

    def _delete_notches_file(self):
        """His Delete notches file: remove THIS spectrum's rows from
        notch_overrides.csv, and the file itself once that empties it.
        The live notches on the chart are untouched."""
        import csv
        folder = self._series_folder()
        if not folder:
            self._status("pick a data folder first.", warn=True)
            return
        path = os.path.join(folder, NOTCH_FILE)
        if not os.path.isfile(path):
            self._status("no %s to clear." % NOTCH_FILE)
            return
        stem = self._stem_of(self._label) if self._label else None
        try:
            with open(path, "r", encoding="utf-8", newline="") as f:
                rows = list(csv.reader(f))
        except (OSError, csv.Error) as exc:
            self._status("could not read %s: %s" % (NOTCH_FILE, exc),
                         warn=True)
            return
        if not rows:
            return
        head, body = rows[0], rows[1:]
        kept = [r for r in body if not (r and r[0] == stem)]
        if len(kept) == len(body):
            self._status("no saved rows for %s." % (stem or "this "
                                                    "spectrum"))
            return
        try:
            if not kept:
                os.remove(path)
                self._status("cleared the last override; removed %s."
                             % NOTCH_FILE)
            else:
                with open(path, "w", encoding="utf-8", newline="") as f:
                    w = csv.writer(f)
                    w.writerow(head)
                    w.writerows(kept)
                self._status("cleared the saved override for %s." % stem)
        except OSError as exc:
            self._status("could not rewrite %s: %s" % (NOTCH_FILE, exc),
                         warn=True)

    def _export_cleaned(self):
        """His Export cleaned spectrum: the red FFT-filtered curve per
        channel as CSV -- Wavenumber_cm, Background_notch, Sample_notch
        and Absorbance_notch = log10(BG/S), his columns and file name."""
        rec = self._record()
        if rec is None:
            self._status("load a spectrum before exporting.", warn=True)
            return
        cols = {}
        for chan in CHANNELS:
            c = self._compute(chan)
            fi = (c or {}).get("fft_info") or {}
            ic = fi.get("I_notch_1x")
            if ic is not None and np.any(np.isfinite(np.asarray(ic))):
                cols["%s_notch" % chan] = np.asarray(ic, float)
        if not cols:
            self._status("the cleaned spectrum needs a detected fringe.",
                         warn=True)
            return
        folder = self._series_folder()
        if not folder:
            self._status("pick an input or output folder first.", warn=True)
            return
        wl = np.asarray(rec["wl"], float)
        wn = 1e7 / np.maximum(wl, 1e-9)
        out = [("Wavenumber_cm", wn)]
        for k in ("Background_notch", "Sample_notch"):
            if k in cols:
                out.append((k, cols[k]))
        if "Background_notch" in cols and "Sample_notch" in cols:
            with np.errstate(divide="ignore", invalid="ignore"):
                absn = np.log10(cols["Background_notch"]
                                / cols["Sample_notch"])
            absn = np.where(np.isfinite(absn), absn, np.nan)
            out.append(("Absorbance_notch", absn))
        stamp = time.strftime("%Y%m%d_%H%M%S")
        stem = self._stem_of(self._label) or "spectrum"
        path = os.path.join(folder, "cleaned_spectrum_%s_%s.csv"
                            % (stem, stamp))
        try:
            with open(path, "w", encoding="utf-8", newline="") as f:
                f.write(",".join(k for k, _v in out) + "\n")
                for i in range(len(wn)):
                    f.write(",".join((("%.10g" % v[i])
                                      if np.isfinite(v[i]) else "")
                                     for _k, v in out) + "\n")
        except OSError as exc:
            self._status("export failed: %s" % exc, warn=True)
            return
        self._log("Fringe: wrote cleaned spectrum -> %s" % path)
        self._status("exported cleaned spectrum -> %s"
                     % os.path.basename(path))

    def _on_wl_over(self):
        key = self._dataset_key()
        ov = self.settings.setdefault("fr_wl_overrides", {})
        if self.wlover_v.get():
            ov[key] = [_f(self.wlmin_v, 600.0), _f(self.wlmax_v, 800.0)]
            self._status("wavelength window pinned to this dataset "
                         "(%g-%g nm)." % tuple(ov[key]))
        else:
            ov.pop(key, None)
            self._status("wavelength window back to the global default.")
        self._invalidate(every=True)

    def _dataset_key(self):
        loc = getattr(self, "_local", None)
        if loc and loc.get("folder"):
            return loc["folder"]
        try:
            return self.app.in_var.get() or "(none)"
        except Exception:
            return "(none)"

    # ---- REFRACTIVE INDEX FROM INTENSITY ----------------------------------
    def _card_intensity(self):
        b = self.app._group(self.sidebar_parent,
                            "Refractive Index from Intensity")
        a = self.app
        r = self._row(b)
        cf = a._brand_button(r, "Compute fits", self._compute_fits)
        cf.pack(side="left", fill="x", expand=True)
        self._tip(cf, "Run the full amplitude fitters on the current notch "
                      "and low-pass settings. They are the constant-n cosine "
                      "fit and the band integral, over every spectral "
                      "window. The right panels switch to the tiered view to "
                      "show the result.")
        hb = ttk.Button(r, text="History \u25be", width=10,
                        command=self._open_history)
        hb.pack(side="left", fill="x", expand=True, padx=(PAD_X, 0))
        self._tip(hb, "Reopen a previous Compute fits run, with its inputs "
                      "and notch settings. The list names each by the fitted "
                      "n.")
        r = self._row(b, PAD_BTNROW)
        self._tiers_btn = ttk.Button(r, text="Show tiered", width=13,
                                     command=self._toggle_tiers)
        self._tiers_btn.pack(side="left", fill="x", expand=True)
        self._tip(self._tiers_btn,
                  "Flat view: the right panels show raw plus the FFT "
                  "filtered spectrum at true intensity. Tiered view: the "
                  "offset diagnostic stack, plus the crimson and blue "
                  "residual FFTs on the left panels. Compute fits "
                  "switches to tiered by itself.")
        self._clean_btn = ttk.Button(r, text="Hide clean spectrum",
                                     width=18,
                                     command=self._toggle_hideclean)
        self._clean_btn.pack(side="left", fill="x", expand=True,
                             padx=(PAD_X, 0))
        self._tip(self._clean_btn,
                  "Hide or show the red FFT filtered curve on the right "
                  "panels. Off leaves raw and the tiers.")
        r = self._row(b, PAD_BTNROW)
        bf = ttk.Checkbutton(r, text="Band \u0394 resolution floor",
                             variable=self.bandfloor_v,
                             command=self._invalidate)
        bf.pack(side="left")
        self._tip(bf, "Applies to the band integral alone: hold its "
                      "integration band at the FFT main lobe or wider. The "
                      "notches, the cleaning and the shaded windows hold. "
                      "Only V_band moves, and mostly on short windows.")

    def _compute_fits(self):
        """His Compute fits: run the full fitters (run_fits=True) on both
        channels under the current notch + low-pass settings, switch the
        right panels to the tiered view, and file a history snapshot."""
        rec = self._record()
        if rec is None:
            self._status("load a spectrum first.", warn=True)
            return
        self._status("computing fits...")
        try:
            self.app.root.update_idletasks()
        except (AttributeError, tk.TclError):
            pass
        cfg = self._cfg_for(rec)
        done = []
        for chan in CHANNELS:
            centers = self._active_centers(chan)
            kw = {}
            if centers:
                kw["notch_centers_nm"] = [k * 1000.0 for k in centers]
                kw["notch_halfwidths_um"] = [self._width_of(chan, k)
                                             for k in centers]
            ccfg = cfg
            _cut = self._lp_cut_or_none(chan)
            if self.lp_on_v[chan].get() and _cut is not None:
                kw["lowpass"] = True
                kw["lp_cutoff_um"] = _cut
                # the edge rides on the config, as it does in _compute
                _shape, _roll = self._lp_edge(chan)
                kw["lp_rolloff_um"] = _roll
                ccfg = cfg.evolve(lp_rolloff_um=_roll, lp_edge_shape=_shape)
            try:
                fit, _I, _nt, _d = compute_channel_fit(
                    rec["wl"], rec[CHAN_KEY[chan]], cfg=ccfg,
                    label="%s %s" % (rec["label"], chan), run_fits=True,
                    **kw)
            except Exception as exc:
                self._status("%s fit failed: %s" % (chan, exc), warn=True)
                continue
            self._fits[(self._dkey(), chan)] = fit
            n = self._fitted_n(chan)
            done.append("%s n=%s" % (chan[0],
                                     _fmt(n, 3) if n is not None
                                     else "\u2013"))
        self.tiers_v.set(True)      # computing fits shows the tiers, his rule
        self._sync_view_buttons()
        self._record_fit_history()
        self._request_redraw(now=True)
        if done:
            self._status("fits computed (%s)." % ", ".join(done))
        else:
            self._status("the fit needs a detected fringe.",
                         warn=True)

    def _fitted_n(self, chan):
        """The fitted constant-n for a channel: fine window first, then
        narrow, wide, full -- his n_mean preference order."""
        return self._fitn_of(self._label, chan)

    def _fine_residual_ffts(self, chan):
        """Post-fit residual FFTs on the measured curve's own grid --
        crimson = direct cosine residual, blue = band-integral residual.
        His _fine_residual_ffts on the vendored core: resid = norm -
        fresnel_V(n) cos(4 pi nt / lambda + phi0), Hann-windowed rfft in
        the measured-FFT V convention."""
        fit = self._fits.get((self._dkey(), chan))
        if not fit:
            return []
        cn = (fit.get("models") or {}).get("constant_n") or {}
        fine = cn.get("fine") or cn.get("narrow")
        if not fine or fine.get("n_mean") is None:
            return []
        fi = fit.get("fft_info") or {}
        wn_u = fi.get("wn_u")
        norm = fi.get("norm_u_detrend")
        if wn_u is None or norm is None or len(np.asarray(norm)) < 16:
            return []
        wn_u = np.asarray(wn_u, float)
        norm = np.asarray(norm, float)
        if wn_u.size != norm.size:
            return []
        wl_u = 1.0 / np.maximum(wn_u, 1e-12)
        w = np.hanning(len(norm))
        wsum = max(float(np.sum(w)), 1e-9)
        dwn = float(np.median(np.diff(wn_u))) or 1e-9
        nt_nm = float(fine["nt_um"]) * 1000.0
        phi0 = float(fine.get("phi0") or 0.0)
        out = []

        def _one(n_val, color, name):
            phi = 4.0 * np.pi * nt_nm / wl_u + phi0
            resid = (norm - fringe_optics.fresnel_V(n_val, wl_u)
                     * np.cos(phi))
            X = np.fft.rfft(resid * w)
            freqs = np.fft.rfftfreq(len(resid), d=abs(dwn))
            out.append((freqs / 2000.0, 2.0 * np.abs(X) / wsum, color,
                        name))

        try:
            _one(float(fine["n_mean"]), "crimson",
                 "direct resid (fine fit)")
            ba = fi.get("band_amp") or {}
            vb = float(ba.get("V_band_fine") or ba.get("V_band") or 0.0)
            if vb > 0:
                cfg = self._cfg_for(self._record() or {})
                wl_c = 0.5 * (cfg.fit_wl_min_nm + cfg.fit_wl_max_nm)
                nb = float(fringe_optics.fresnel_n_from_V(
                    min(vb, 0.9999), wl_c))
                _one(nb, "royalblue", "integral resid (fine fit)")
        except Exception:
            return []
        return out

    def _sync_view_buttons(self):
        try:
            self._tiers_btn.configure(text=("Hide tiered"
                                            if self.tiers_v.get()
                                            else "Show tiered"))
            self._clean_btn.configure(text=("Show clean spectrum"
                                            if self.hideclean_v.get()
                                            else "Hide clean spectrum"))
        except (AttributeError, tk.TclError):
            pass

    def _toggle_tiers(self):
        self.tiers_v.set(not self.tiers_v.get())
        self._sync_view_buttons()
        self._request_redraw(now=True)

    def _toggle_hideclean(self):
        self.hideclean_v.set(not self.hideclean_v.get())
        self._sync_view_buttons()
        self._request_redraw(now=True)

    # ---- fit history ------------------------------------------------------
    def _record_fit_history(self):
        snap = {"stamp": time.strftime("%H:%M:%S"),
                "fitn": {c: self._fitted_n(c) for c in CHANNELS},
                "stack": {"medium": self.medium_v.get(),
                          "medium_n": _f(self.medium_n_v, 1.2),
                          "layer2_on": bool(self.layer2_on_v.get()),
                          "layer2": self.layer2_v.get(),
                          "n_sample": _f(self.ns_v, 1.5),
                          "d1": _f(self.d1_v, 0.0),
                          "t": _f(self.t_v, 20.0),
                          "d2": _f(self.d2_v, 0.0)},
                "lp": {c: [bool(self.lp_on_v[c].get()),
                           self._lp_cut_or_none(c)] for c in CHANNELS},
                "notch": (self._mem_state() or {}).get("chan") or {}}
        same = [s for s in self._fit_history
                if {k: v for k, v in s.items() if k != "stamp"}
                == {k: v for k, v in snap.items() if k != "stamp"}]
        for s in same:
            self._fit_history.remove(s)
        self._fit_history.insert(0, snap)
        del self._fit_history[12:]
        self._fill_history()

    def _open_history(self):
        win = self._raise_existing("_hist_win")
        if win is not None:
            self._fill_history()
            return win
        a = self.app
        win = tk.Toplevel(a.root)
        win.title("Fit history")
        win.transient(a.root)
        a._center_on_root(win, *self._dlg_size(48, 40))
        a._apply_titlebar(win)
        self._closes_by_withdraw(win)
        self._hist_win = win
        card = a._card(win, grow="both")
        card.pack(fill="both", expand=True, padx=10, pady=8)
        card.set_title(a._lf_header(card, "Fit history"))
        a._lbl(card.body,
               text="Previous Compute fits runs, newest first, named by "
                    "the fitted Background / Sample n. Click one to "
                    "restore its inputs and notch settings; the cross "
                    "forgets it.",
               wraplength=a._em() * 40, justify="left",
               foreground=MUTED).pack(anchor="w", pady=PAD_ROW)
        self._hist_rows = ttk.Frame(card.body)
        self._hist_rows.pack(fill="both", expand=True)
        self._fill_history()
        return win

    def _fill_history(self):
        f = getattr(self, "_hist_rows", None)
        if f is None:
            return
        try:
            if not f.winfo_exists():
                self._hist_rows = None
                return
            for w in f.winfo_children():
                w.destroy()
        except tk.TclError:
            return
        a = self.app
        if not self._fit_history:
            a._lbl(f, text="(no fits computed yet)",
                   foreground=MUTED).pack(anchor="w")
            return
        for snap in list(self._fit_history):
            r = ttk.Frame(f)
            r.pack(fill="x", pady=1)
            fn = snap.get("fitn") or {}

            def _n(v):
                return ("%.3f" % v) if isinstance(v, float) else "\u2013"
            ttk.Button(r, text="%s   B n=%s   S n=%s"
                       % (snap.get("stamp", ""),
                          _n(fn.get("Background")), _n(fn.get("Sample"))),
                       command=lambda s=snap:
                       self._hist_recall(s)).pack(side="left", fill="x",
                                                  expand=True)
            ttk.Button(r, text="\u00d7", width=2,
                       command=lambda s=snap:
                       self._hist_forget(s)).pack(side="left",
                                                  padx=(4, 0))

    def _hist_forget(self, snap):
        self._fit_history[:] = [s for s in self._fit_history
                                if s is not snap]
        self._fill_history()

    def _hist_recall(self, snap):
        st = snap.get("stack") or {}
        self._suspend = True
        try:
            if st.get("medium") in MEDIUM_CHOICES:
                self.medium_v.set(st["medium"])
            self.medium_n_v.set("%g" % st.get("medium_n", 1.2))
            self.layer2_on_v.set(bool(st.get("layer2_on", False)))
            if st.get("layer2"):
                self.layer2_v.set(st["layer2"])
            self.ns_v.set("%g" % st.get("n_sample", 1.5))
            self.d1_v.set("%g" % st.get("d1", 0.0))
            self.t_v.set("%g" % st.get("t", 20.0))
            self.d2_v.set("%g" % st.get("d2", 0.0))
            for c in CHANNELS:
                pair = (snap.get("lp") or {}).get(c)
                if isinstance(pair, (list, tuple)) and len(pair) == 2:
                    self.lp_on_v[c].set(bool(pair[0]))
                    self.lp_v[c].set("" if pair[1] is None
                                     else "%g" % float(pair[1]))
        finally:
            self._suspend = False
        if self._label is not None:
            for chan, cd in (snap.get("notch") or {}).items():
                ch = self._ch(chan)
                if ch is None:
                    continue
                ch["user_centers"] = [float(k) for k in
                                      cd.get("user_centers", [])]
                ch["removed"] = set(float(k) for k in
                                    cd.get("removed", []))
                ch["unticked"] = set(float(k) for k in
                                     cd.get("unticked", []))
                ch["user_fundamental"] = cd.get("user_fundamental")
                ch["widths"] = {float(k): float(v) for k, v in
                                (cd.get("widths") or {}).items()}
        self._on_layer2()
        self._sync_medium_row()
        self._thick_snapshot()
        self._notch_sig = None
        self._status("restored a Compute fits run from the history.")
        self._invalidate(every=True)

    # ---- PANELS: the pop-out launcher + the bottom readouts ---------------
    def _card_panels(self):
        b = self.app._group(self.sidebar_parent, "Panels")
        a = self.app
        r = self._row(b)
        for txt, cmd, tip in (
                ("Notch list", self._open_notch_list,
                 "The notch list, in its own window."),
                ("Predicted lines", self._open_pred_lines,
                 "The forward-model lines as selectable text: every "
                 "interface pair and its optical path.")):
            btn = ttk.Button(r, text=txt, command=cmd)
            btn.pack(side="left", fill="x", expand=True,
                     padx=(0 if txt == "Notch list" else PAD_X, 0))
            self._tip(btn, tip)
        r = self._row(b, PAD_BTNROW)
        for txt, cmd, tip in (
                ("Results", self.results_view,
                 "The recorded series against pressure. It is the same "
                 "window the Results plot button opens."),
                ("Info", self._open_wb_info,
                 "The marker key, the mouse grammar, and where the "
                 "files go."),
                ("Detection", self._open_detection,
                 "Scroll the Detection card into view. It holds the "
                 "wavelength window, the n*t band, Fisher p, the "
                 "agreement tolerance and the search report.")):
            btn = ttk.Button(r, text=txt, command=cmd)
            btn.pack(side="left", fill="x", expand=True,
                     padx=(0 if txt == "Results" else PAD_X, 0))
            self._tip(btn, tip)
        r = self._row(b, PAD_BTNROW)
        for txt, cmd, tip in (
                ("Y-axis range", self._open_yaxis,
                 "Set the fringe-amplitude range the two FFT panels share. "
                 "An empty box is automatic for that bound."),
                ("Line colours", self._open_cmap_chooser,
                 "Pick the palette the model stems are drawn from, and "
                 "whether its palest colours are used.")):
            btn = ttk.Button(r, text=txt, command=cmd)
            btn.pack(side="left", fill="x", expand=True,
                     padx=(0 if txt == "Y-axis range" else PAD_X, 0))
            self._tip(btn, tip)
        r = self._row(b, PAD_BTNROW)
        mi = ttk.Button(r, text="Refractive index models",
                        command=self._open_models)
        mi.pack(side="left", fill="x", expand=True)
        self._tip(mi, "What each index model is, the equations it uses, its "
                      "constants and where they were published. One tab per "
                      "material.")
        r = self._row(b, PAD_BTNROW)
        mv = ttk.Checkbutton(r, text="Error bars (multiscale variance)",
                             variable=self.msv_v, command=self._on_msv)
        mv.pack(side="left")
        self._tip(mv, "Estimate each recorded point's uncertainty from the "
                      "spread of the fit across analysis scales. Off by "
                      "default: about 35 ms per point, computed once and "
                      "cached.")

        self._status_lbl = a._lbl(b, text="Load a spectrum to get FFT peaks.",
                                  foreground=MUTED,
                                  wraplength=self.app._em() * 32,
                                  justify="left")
        self._slot(self._status_lbl, fill="x", pady=PAD_ROW)
        self._wrap_to_card(self._status_lbl)
        self._solve_lbl = a._lbl(b, text="",
                                 wraplength=self.app._em() * 32,
                                 justify="left")
        self._slot(self._solve_lbl, fill="x", pady=PAD_TIGHT)
        self._wrap_to_card(self._solve_lbl)
        r = self._row(b, PAD_GROUP)
        a._lbl(r, text="CSV folder:", width=LBL_W).pack(side="left")
        self.csv_dir_v = tk.StringVar(value="\u2013")
        e = ttk.Entry(r, textvariable=self.csv_dir_v, state="readonly")
        e.pack(side="left", fill="x", expand=True)
        self._tip(e, "Where the workbench writes its CSVs: cleaned spectra, "
                     "the notches file, results, the session. Beside your "
                     "data when that folder takes new files, else your "
                     "output folder.")

    def _set_solve_status(self, text):
        """The dedicated solve-status line: solve errors and clamp
        warnings live here so they never overwrite a load or export
        message (his solve_status slot)."""
        lab = getattr(self, "_solve_lbl", None)
        if lab is None:
            return
        try:
            lab.configure(text=text, foreground=self._warn_fg())
        except tk.TclError:
            return
        self._show_if_text(lab, text)

    def _sync_action_marks(self):
        """The green tick on Results plot, his caption grammar: it tracks
        whether THIS pressure point is on the results series."""
        here = self._dkey()
        on = any(self._pt_key(q) == here for q in self._series)
        try:
            self._results_btn.configure(
                text=("Results plot \u2713" if on else "Results plot"))
        except (AttributeError, tk.TclError):
            pass

    # ---- pop-outs ---------------------------------------------------------
    def _open_notch_list(self):
        win = self._raise_existing("_notch_win")
        if win is not None:
            # it was withdrawn, not destroyed, so the rows it holds may be a
            # trace behind: re-read them before it comes back up
            self._notch_sig = None
            self._refresh_notch_rows()
            return win
        a = self.app
        win = tk.Toplevel(a.root)
        win.title("Notch list")
        win.transient(a.root)
        a._center_on_root(win, *self._dlg_size(52, 46))
        a._apply_titlebar(win)
        self._closes_by_withdraw(win)
        self._notch_win = win
        card = a._card(win, grow="both")
        card.pack(fill="both", expand=True, padx=10, pady=8)
        card.set_title(a._lf_header(card, "Notch list"))
        b = card.body
        a._lbl(b, text="Click a peak on the chart to add a notch; click "
                       "it again to take it away. Untick a row to keep "
                       "the marker but stop the notch. Widths are "
                       "absolute half-widths, in +/- micron of n*t. The "
                       "Fundamental column marks the peak the detector "
                       "reports; clicking the marked row clears it.",
               wraplength=a._em() * 44, justify="left",
               foreground=MUTED).pack(anchor="w", pady=PAD_ROW)
        r = ttk.Frame(b)
        r.pack(fill="x", pady=PAD_TIGHT)
        a._lbl(r, text="Half-width", width=LBL_W).pack(side="left")
        # his range, the same one the per-centre rows carry (D4)
        sp = self._spin(r, self.hw_v, NOTCH_HW_MIN_UM, NOTCH_HW_MAX_UM,
                        width=7)
        sp.pack(side="left")
        a._lbl(r, text="+/- um").pack(side="left", padx=PAD_X_TIGHT)
        self._tip(sp, "Default half-width for a NEW notch. Rows keep "
                      "their own widths.")
        rs = ttk.Button(r, text="Reset", width=8,
                        command=self._reset_notches)
        rs.pack(side="right")
        self._tip(rs, "Drop every manual notch on this spectrum and go "
                      "back to the detected fundamental.")
        # his fine-steps switch for the width spinboxes in this window
        # (10118): 0.1 um a step instead of 1.
        r = ttk.Frame(b)
        r.pack(fill="x", pady=PAD_TIGHT)
        nf = ttk.Checkbutton(r, text="fine steps (÷ 10)",
                             variable=self.notchfine_v,
                             command=self._on_notch_fine)
        nf.pack(side="left")
        self._tip(nf, "Step the width boxes in this window at 0.1 micron.")
        self._notch_rows = ttk.Frame(b)
        self._notch_rows.pack(fill="both", expand=True)
        self._notch_sig = None
        self._refresh_notch_rows()
        return win

    def _refresh_notch_rows(self):
        """Rebuild the notch list (in its pop-out).  One row per centre:
        micron, half-width, the fundamental flag and a remove cross.
        Signature-guarded: a low-pass drag redraws at 110 ms and
        rebuilding a dozen widgets per frame would stutter.

        `_rebuilding` holds for the whole teardown and rebuild: destroying
        the row that has the keyboard focus emits <FocusOut>, which is what
        commits a width, and that commit asks for the redraw that lands
        here -- one edit re-entering its own rebuild.
        """
        f = self._notch_rows
        if f is None or self._rebuilding:
            return
        try:
            if not f.winfo_exists():
                self._notch_rows = None
                return
        except tk.TclError:
            return
        sig = []
        for chan in CHANNELS:
            ch = self._ch(chan)
            keys = self._active_centers(chan, include_unticked=True)
            sig.append((chan, tuple(keys), tuple(sorted(ch["unticked"]))
                        if ch else (), self._fund_key(chan),
                        # the stored value, not just the resolved key: auto
                        # with no fringe and an explicitly cleared channel
                        # both read None, and only one of them says so
                        (ch or {}).get("user_fundamental"),
                        tuple(round(self._width_of(chan, k), 4)
                              for k in keys)))
        sig = tuple(sig) + (bool(self.notchfine_v.get()),)
        if sig == getattr(self, "_notch_sig", None):
            return
        self._notch_sig = sig
        self._rebuilding = True
        try:
            self._fill_notch_rows(f)
        finally:
            self._rebuilding = False

    def _on_notch_fine(self):
        """The notch window's own fine-step switch: rebuild the rows so every
        width box takes the new increment."""
        self.settings["fr_notch_fine"] = bool(self.notchfine_v.get())
        self._notch_sig = None
        self._refresh_notch_rows()

    def _fill_notch_rows(self, f):
        """The notch list's rows themselves.  Split out so the re-entrancy
        flag owns exactly the teardown and the rebuild.

        One row per centre: the tick, the micron key, its own half-width, the
        Fundamental radio and the remove cross.  The radio column is his
        (14286-14298): one group per channel, and clicking the row that
        already holds the fundamental clears the channel to none.
        """
        for w in f.winfo_children():
            w.destroy()
        a = self.app
        any_row = False
        self._fund_vars = {}
        step = 0.1 if self.notchfine_v.get() else 1.0
        for chan in CHANNELS:
            ch = self._ch(chan)
            if ch is None:
                continue
            centers = self._active_centers(chan, include_unticked=True)
            if not centers:
                continue
            hdr = ttk.Frame(f)
            hdr.pack(fill="x", pady=PAD_TIGHT)
            a._lbl(hdr, text=chan, font=a._F(-1, "bold"),
                   foreground=MUTED).pack(side="left")
            a._lbl(hdr, text="Fundamental", font=a._F(-1),
                   foreground=MUTED).pack(side="right", padx=(PAD_X, 0))
            # his per-channel Clear beside the header (14200-14206): the
            # per-row crosses in one press
            cl = ttk.Button(hdr, text="Clear", width=7,
                            command=lambda c=chan: self._clear_notches_for(c))
            cl.pack(side="right", padx=(PAD_X, 0))
            self._tip(cl, "Take every notch off %s, keeping the fundamental "
                          "listed and unticked." % chan.lower())
            fund = self._fund_key(chan)
            fv = tk.StringVar(value=("" if fund is None else "%.2f" % fund))
            self._fund_vars[chan] = fv
            for kk in centers:
                any_row = True
                r = ttk.Frame(f)
                r.pack(fill="x", pady=PAD_TIGHT)
                on = tk.BooleanVar(value=kk not in ch["unticked"])
                cb = ttk.Checkbutton(
                    r, variable=on,
                    command=lambda c=chan, k=kk, v=on:
                    self._tick(c, k, v))
                cb.pack(side="left")
                self._tip(cb, "Untick to keep the marker but drop this "
                              "centre from the notch.")
                # his row reads "[x] 55.21 um  +- [3] um  [X]  (o)": the unit
                # after the centre, the width bracketed by +- and um, and the
                # remove cross before the fundamental radio
                a._lbl(r, text=("%.2f" % kk), width=7,
                       font=a._F(0, mono=True)).pack(side="left")
                a._lbl(r, text="um").pack(side="left")
                a._lbl(r, text="+-").pack(side="left", padx=(PAD_X, 0))
                wv = tk.StringVar(value="%g" % self._width_of(chan, kk))
                we = ttk.Spinbox(r, textvariable=wv, from_=NOTCH_HW_MIN_UM,
                                 to=NOTCH_HW_MAX_UM, increment=step, width=5)
                we.configure(command=lambda c=chan, k=kk, v=wv:
                             self._set_width(c, k, v))
                we.pack(side="left", padx=PAD_X_TIGHT)
                we.bind("<Return>",
                        lambda e, c=chan, k=kk, v=wv:
                        self._set_width(c, k, v))
                we.bind("<FocusOut>",
                        lambda e, c=chan, k=kk, v=wv:
                        self._set_width(c, k, v))
                a._lbl(r, text="um").pack(side="left")
                self._tip(we, "Half-width of this notch in +/- micron. "
                              "0.5 to 20, his range.")
                rb = ttk.Radiobutton(r, variable=fv, value=("%.2f" % kk),
                                     command=lambda c=chan, k=kk:
                                     self._fund_radio(c, k))
                rb.pack(side="right", padx=(PAD_X, 0))
                self._tip(rb, "Make this centre the fundamental. Clicking "
                              "the marked one clears the channel.")
                x = ttk.Button(r, text="\u00d7", width=2,
                               command=lambda c=chan, k=kk:
                               self._remove_center(c, k))
                x.pack(side="right")
                self._tip(x, "Remove this centre from the list.")
            if ch["user_fundamental"] == FUND_NONE:
                a._lbl(f, text="  %s has no fundamental." % chan,
                       foreground=MUTED).pack(anchor="w")
        if not any_row:
            a._lbl(f, text="(no fringe)", foreground=MUTED).pack(anchor="w")

    def _open_yaxis(self):
        """His FFT Y-axis range dialog (_show_yaxis_dialog, 11756-11790).

        Two boxes, one per bound, over the fringe-amplitude scale the
        Background and Sample FFT panels share.  An empty box leaves that
        bound automatic; both empty is plain auto.
        """
        win = self._raise_existing("_yaxis_win")
        if win is not None:
            return win
        a = self.app
        win = tk.Toplevel(a.root)
        win.title("FFT Y-axis range")
        win.transient(a.root)
        win.resizable(False, False)
        a._center_on_root(win, *self._dlg_size(44, 20))
        a._apply_titlebar(win)
        self._closes_by_withdraw(win)
        self._yaxis_win = win
        card = a._card(win, grow="both")
        card.pack(fill="both", expand=True, padx=10, pady=8)
        card.set_title(a._lf_header(card, "FFT Y-axis range"))
        b = card.body
        a._lbl(b, text="The fringe-amplitude V range the Background and "
                       "Sample FFT panels share. An empty box is automatic "
                       "for that bound.",
               wraplength=a._em() * 38, justify="left",
               foreground=MUTED).pack(anchor="w", pady=PAD_ROW)
        for var, txt in ((self.yhi_v, "Upper"), (self.ylo_v, "Lower")):
            r = self._row(b, PAD_TIGHT)
            a._lbl(r, text=txt, width=LBL_W).pack(side="left")
            e = ttk.Entry(r, textvariable=var, width=12)
            e.pack(side="left")
            e.bind("<Return>", lambda ev: self._request_redraw(now=True))
            self._tip(e, "A number pins this bound. An empty box leaves it "
                         "automatic.")
        r = self._row(b, PAD_GROUP)
        rs = ttk.Button(r, text="Back to auto", command=self._reset_yaxis)
        rs.pack(side="left")
        self._tip(rs, "Empty both boxes.")
        ap = a._brand_button(r, "Apply",
                             lambda: self._request_redraw(now=True))
        ap.pack(side="right")
        self._tip(ap, "Redraw the two FFT panels at this range.")
        a._iconize_buttons(win)
        return win

    def _reset_yaxis(self):
        self.ylo_v.set("")
        self.yhi_v.set("")
        self._request_redraw(now=True)

    def _open_cmap_chooser(self):
        """His Settings > Line colormap popup (11827-11833, shot 12).

        The model stems are the one place on the figure where colour carries
        an identity, so the chooser offers the QUALITATIVE palettes only: a
        continuous map would give six neighbouring lines six shades of one
        hue.  "Skip faint" drops the colours that wash out on a pale page.
        """
        win = self._raise_existing("_cmap_win")
        if win is not None:
            return win
        a = self.app
        win = tk.Toplevel(a.root)
        win.title("Line colours")
        win.transient(a.root)
        win.resizable(False, False)
        a._center_on_root(win, *self._dlg_size(46, 20))
        a._apply_titlebar(win)
        self._closes_by_withdraw(win)
        self._cmap_win = win
        card = a._card(win, grow="both")
        card.pack(fill="both", expand=True, padx=10, pady=8)
        card.set_title(a._lf_header(card, "Line colours"))
        b = card.body
        a._lbl(b, text="The palette the model stems take their colours from. "
                       "Okabe-Ito is the shipped one, and it holds up under "
                       "every kind of colour vision.",
               wraplength=a._em() * 40, justify="left",
               foreground=MUTED).pack(anchor="w", pady=PAD_ROW)
        r = self._row(b, PAD_TIGHT)
        a._lbl(r, text="Colorway", width=LBL_W).pack(side="left")
        names = ["okabeito"] + [n for n in colormaps.available()
                                if colormaps.is_categorical(n)
                                and n != "okabeito"]
        cb = ttk.Combobox(r, textvariable=self.cmap_v, values=names,
                          state="readonly", width=14)
        cb.pack(side="left")
        cb.bind("<<ComboboxSelected>>", lambda e: self._on_cmap())
        self._tip(cb, "Which qualitative palette the stems use.")
        r = self._row(b, PAD_TIGHT)
        sf = ttk.Checkbutton(r, text="skip faint", variable=self.skipfaint_v,
                             command=self._on_cmap)
        sf.pack(side="left")
        self._tip(sf, "Leave out the palette's palest colours. A filter that "
                      "empties a palette is ignored.")
        a._iconize_buttons(win)
        return win

    def _on_cmap(self):
        self.settings["fr_stem_cmap"] = self.cmap_v.get()
        self.settings["fr_stem_skip_faint"] = bool(self.skipfaint_v.get())
        self._request_redraw(now=True)

    def _open_pred_lines(self):
        win = self._raise_existing("_lines_win")
        if win is not None:
            self._fill_pred_lines()
            return win
        a = self.app
        win = tk.Toplevel(a.root)
        win.title("Predicted lines")
        win.transient(a.root)
        a._center_on_root(win, *self._dlg_size(46, 38))
        a._apply_titlebar(win)
        self._closes_by_withdraw(win)
        self._lines_win = win
        card = a._card(win, grow="both")
        card.pack(fill="both", expand=True, padx=10, pady=8)
        card.set_title(a._lf_header(card, "Predicted lines"))
        a._lbl(card.body, text="Forward-model lines (selectable / "
                               "copyable):",
               foreground=MUTED).pack(anchor="w", pady=PAD_TIGHT)
        pal = self._pal()
        txt = tk.Text(card.body, width=44, height=16, wrap="none",
                      relief="flat", highlightthickness=0, bd=0,
                      background=pal[0], foreground=pal[1],
                      insertbackground=pal[1],
                      font=self.app._F(0, mono=True))
        txt.pack(fill="both", expand=True)
        self._lines_txt = txt
        self._fill_pred_lines()
        return win

    def _fill_pred_lines(self):
        txt = getattr(self, "_lines_txt", None)
        if txt is None:
            return
        try:
            if not txt.winfo_exists():
                self._lines_txt = None
                return
        except tk.TclError:
            return
        rec = self._record()
        rows = []
        if rec is not None:
            try:
                p = self._stack_params(rec)
            except Exception:
                p = None
            if p:
                for name, kind in (("SAMPLE", "sample"),
                                   ("BACKGROUND", "medium")):
                    rows.append(name)
                    try:
                        lines = fringe_stack.stack_lines(p, kind=kind)
                    except Exception:
                        lines = []
                    for ln in lines:
                        ids = "+".join(sorted(ln.get("ids") or []))
                        rows.append("  %s: %s = %.2f um"
                                    % (ids, ln.get("formula") or "",
                                       float(ln["nt"])))
        if not rows:
            rows = ["load a spectrum first"]
        try:
            txt.configure(state="normal")
            txt.delete("1.0", "end")
            txt.insert("1.0", "\n".join(rows))
            txt.configure(state="disabled")
        except tk.TclError:
            pass

    def _open_wb_info(self):
        win = self._raise_existing("_wbinfo_win")
        if win is not None:
            return win
        a = self.app
        win = tk.Toplevel(a.root)
        win.title("Info")
        win.transient(a.root)
        a._center_on_root(win, *self._dlg_size(52, 44))
        a._apply_titlebar(win)
        self._closes_by_withdraw(win)
        self._wbinfo_win = win
        card = a._card(win, grow="both")
        card.pack(fill="both", expand=True, padx=10, pady=8)
        card.set_title(a._lf_header(card, "Info", icon="book"))
        self._guide_body(card.body, list(WB_INFO), width=52)
        return win

    def _open_models(self, select=None):
        """His View > Refractive index models (_show_model_info, 15104).

        One tab per material: what the model is, its equations, the
        constants it runs on and where they were published.  The text comes
        from fringe_materials.MODEL_DOCS, the same source the hover
        tooltips read, so this window can never describe a model the code
        does not use.  `select` names the tab to raise first.
        """
        win = self._raise_existing("_models_win")
        a = self.app
        if win is None:
            win = tk.Toplevel(a.root)
            win.title("Refractive index models")
            win.transient(a.root)
            a._center_on_root(win, *self._dlg_size(84, 62))
            a._apply_titlebar(win)
            self._closes_by_withdraw(win)
            self._models_win = win
            # the button bar first, at the bottom: pack gives the expanding
            # notebook the rest, and a bar packed after it can be squeezed
            # off a short window
            bar = ttk.Frame(win, padding=(10, 8))
            bar.pack(side="bottom", fill="x")
            ttk.Button(bar, text="Close",
                       command=lambda: self._dismiss(win)).pack(side="right")
            nb = ttk.Notebook(win)
            nb.pack(fill="both", expand=True, padx=10, pady=(8, 0))
            self._models_nb = nb
            self._models_tabs = {}
            for key, label in MODEL_DOC_TABS:
                frame = ttk.Frame(nb)
                nb.add(frame, text=label)
                self._models_tabs[key] = frame
                body = ""
                try:
                    body = fringe_materials.format_model_doc(key, full=True)
                except Exception:
                    body = ""
                self._guide_body(frame, [("m", ln) for ln in
                                         (body or "this model carries no "
                                          "reference text.").split("\n")],
                                 width=76)
            a._iconize_buttons(win)
        frame = getattr(self, "_models_tabs", {}).get(select)
        if frame is not None:
            try:
                self._models_nb.select(frame)
            except tk.TclError:
                pass
        return win

    def _open_detection(self):
        """Bring the Detection card out where it can be read.

        R14 promoted the gates from a pop-out to a card in the Fringe
        column, directly above FFT removal.  Everything that used to open
        the window -- the Panels row, the pop-out's View menu, the guide
        tour -- lands here, and the card expands and scrolls into view.
        """
        return self.reveal_card("Detection")

    def reveal_card(self, title):
        """Show one Fringe card: switch to the tab, expand it, scroll to it.

        The right panel is a notebook of scrolling pages, so a card can be
        on a hidden tab, folded shut, or simply below the fold.  All three
        are undone here, in that order, and the card's header is left at
        the top of the page.
        """
        a = self.app
        rec = next((r for r in getattr(a, "_collapsibles", [])
                    if r.get("key") == title), None)
        if rec is None:
            return None
        cont = rec.get("cont")
        # the tab that holds it
        try:
            nb = a.rnotebook
            for i in range(nb.index("end")):
                if str(nb.tab(i, "text")).strip() == rec.get("cat"):
                    nb.select(i)
                    break
        except (AttributeError, tk.TclError):
            pass
        if rec.get("collapsed"):
            try:
                a._set_collapsed(rec, False)
                a._save_collapsed()
            except (AttributeError, tk.TclError):
                pass
        # Selecting the tab and expanding the card both re-lay the page,
        # and the notebook's own tab-changed handler re-asserts the scroll
        # region after that: a single scroll here would be undone.  The
        # move is made again as the page settles, three times over a fifth
        # of a second, which is under the eye's notice.
        for ms in (0, 70, 220):
            try:
                a.root.after(ms, lambda c=cont: self._scroll_card_into_view(c))
            except (AttributeError, tk.TclError):
                self._scroll_card_into_view(cont)
                break
        return cont

    def _scroll_card_into_view(self, cont):
        """Put `cont`'s header at the top of its scrolling page."""
        if cont is None:
            return
        try:
            page = cont.master               # the canvas' window item
            cv = page.master                 # the tk.Canvas itself
        except AttributeError:
            return
        heal = getattr(self.app, "_heal_tab_scroll", None)
        if callable(heal):
            try:
                heal(cv)
            except Exception:
                pass
        try:
            cv.update_idletasks()
            total = float(page.winfo_height())
            room = float(cv.winfo_height())
            if total <= room or total <= 0:
                return
            y = float(cont.winfo_y()) - 6.0
            top = max(0.0, min(y, total - room))
            cv.yview_moveto(top / total)
        except (AttributeError, tk.TclError, ValueError, ZeroDivisionError):
            pass

    def _card_detection(self):
        """The detection gates, and the live report of what they found.

        Matthew's GUI holds these as fixed constants; SPARTA keeps them
        editable.  They are the ONLY detection gates in the program -- the
        main window's "Detection (advanced)" fold is gone, and the df box
        above the plot reads what is set here.  The fringe-report switch
        sits with them, beside the numbers it talks about.
        """
        b = self.app._group(self.sidebar_parent, "Detection")
        a = self.app
        self._detect_body = b

        def gate(label, pady=PAD_TIGHT):
            r = self._row(b, pady)
            a._lbl(r, text=label, width=LBL_W + 3).pack(side="left")
            return r

        r = gate("Window (nm)", PAD_ROW)
        e1 = ttk.Entry(r, textvariable=self.wlmin_v, width=7)
        e1.pack(side="left", fill="x", expand=True)
        a._lbl(r, text="to", width=3, anchor="center").pack(
            side="left", padx=PAD_X_TIGHT)
        e2 = ttk.Entry(r, textvariable=self.wlmax_v, width=7)
        e2.pack(side="left", fill="x", expand=True)
        for e in (e1, e2):
            self._tip(e, "Wavelength range the FFT and the fits run in.")

        r = self._row(b, PAD_TIGHT)
        ov = ttk.Checkbutton(r, text="This dataset only",
                             variable=self.wlover_v,
                             command=self._on_wl_over)
        ov.pack(side="left")
        self._tip(ov, "Store the window above for the current input folder "
                      "alone, so each dataset keeps its own range.")

        r = gate("n*t band (um)", PAD_ROW)
        e3 = ttk.Entry(r, textvariable=self.ntmin_v, width=7)
        e3.pack(side="left", fill="x", expand=True)
        a._lbl(r, text="to", width=3, anchor="center").pack(
            side="left", padx=PAD_X_TIGHT)
        e4 = ttk.Entry(r, textvariable=self.ntmax_v, width=7)
        e4.pack(side="left", fill="x", expand=True)
        for e in (e3, e4):
            self._tip(e, "The n*t search window. The detector considers the "
                         "peaks inside it.")

        # the two single-value gates keep the FIRST box's column, so all
        # four entries in the card line up on one left and one right edge
        r = gate("Fisher p")
        e5 = ttk.Entry(r, textvariable=self.pmax_v, width=7)
        e5.pack(side="left", fill="x", expand=True)
        self._tip(e5, "The g-test significance gate.")
        a._lbl(r, text="", width=3).pack(side="left", padx=PAD_X_TIGHT)
        ttk.Frame(r).pack(side="left", fill="x", expand=True)

        r = gate("Agree tol")
        e6 = ttk.Entry(r, textvariable=self.tol_v, width=7)
        e6.pack(side="left", fill="x", expand=True)
        self._tip(e6, "How closely two of the three detection windows agree "
                      "on n*t for an accepted answer.")
        a._lbl(r, text="", width=3).pack(side="left", padx=PAD_X_TIGHT)
        ttk.Frame(r).pack(side="left", fill="x", expand=True)

        r = self._row(b, PAD_BTNROW)
        sup = ttk.Checkbutton(r, text="Suppress fringe report",
                              variable=self.suppress_v)
        sup.pack(side="left")
        self._tip(sup, "The fringe report goes to the main log whenever "
                       "defringe is switched on there. It lists which traces "
                       "have a detected fringe. It also gives the fitted n*t "
                       "in um and the detection p-value. Tick this to keep "
                       "it quiet.")

        a._subhead(b, "Report")
        self._rep = {}
        for key, txt2 in (("nt", "n*t"), ("p", "p"), ("corr", "from")):
            r = self._row(b, PAD_TIGHT)
            a._lbl(r, text=txt2, width=LBL_W2).pack(side="left")
            lab = a._lbl(r, text="–", font=a._F(0, mono=True))
            lab.pack(side="left", fill="x", expand=True)
            self._rep[key] = lab
        self._tip(self._rep["corr"],
                  "Which of the three detection windows corroborated the "
                  "fringe. A miss reads here too.")
        return b

    # =======================================================================
    # activation / view switch
    # =======================================================================
    def build_view_switch(self, parent):
        """The Plot | Fringe segmented control on the centre tab-strip row.

        Drawn from plain tk widgets recoloured from the palette on every
        repaint, exactly like the session tab strip above it -- sv_ttk's
        notebook tabs would not sit flush on that row.
        """
        self._switch_parent = parent
        self.sync_view_switch()

    def sync_view_switch(self):
        # This is also the workbench's THEME hook: the app's theme chain runs
        # _recolor_tk -> _sync_tabs -> _render_tabs, and _render_tabs ends by
        # calling this.  Anything of ours that holds colours is repainted
        # here, before the early return, so it follows the theme even while
        # the workbench is not showing.  _theme_repaint_maybe carries the
        # heavier half - the FFT figure, the pop-out mirror, the results
        # grid and the [?] window - behind a signature guard, so the
        # session-tab repaints that also land here cost one tuple compare.
        self._retint_guides()
        self._theme_repaint_maybe()
        self._adopt_new_traces()
        parent = getattr(self, "_switch_parent", None)
        if parent is None or not parent.winfo_exists():
            return
        for w in parent.winfo_children():
            w.destroy()
        uibg, fg = self._pal()[:2]
        muted = self.app._muted_fg()
        accent = self.app._brand()["ac2"]
        # No chrome of its own: the switch is a run of cells ON the tab-strip
        # row, and the only state cue is the accent underline. The row that
        # HOLDS it is a plain tk.Frame nobody had ever coloured, so its Tk
        # default (SystemButtonFace) showed through the 6 px gap beside the
        # switch and the 1 px under it -- the white border round the
        # Plot | Fringe control. Painting the row from the same palette is
        # what makes the switch sit flush.
        parent.configure(bg=uibg, bd=0, highlightthickness=0, relief="flat")
        row = parent.master
        if row is not None and row.winfo_class() == "Frame":
            try:
                row.configure(bg=uibg, bd=0, highlightthickness=0,
                              relief="flat")
            except tk.TclError:
                pass
        self._switch_lbls = {}
        for key, text in (("plot", "Plot"), ("fringe", "Fringe")):
            on = (key == "fringe") == self._active
            cell = tk.Frame(parent, bg=uibg, cursor="hand2", bd=0,
                            highlightthickness=0, relief="flat")
            cell.pack(side="left", padx=(0, 2))
            lab = tk.Label(cell, text=text, bg=uibg,
                           fg=(fg if on else muted),
                           font=self.app._F(0, "bold" if on else "normal"),
                           padx=8, pady=3, bd=0, highlightthickness=0,
                           relief="flat")
            lab.pack(side="top")
            tk.Frame(cell, height=2, bd=0, highlightthickness=0,
                     bg=(accent if on else uibg)).pack(side="top", fill="x")
            for w in (cell, lab):
                w.bind("<Button-1>", lambda e, k=key: self._pick_view(k))
            self._switch_lbls[key] = lab
            self._tip(lab, "Show the %s in the centre. The session tab and "
                           "every plot setting stay exactly as they are."
                      % ("plot" if key == "plot" else "fringe workbench"))
        if self._active:
            # The guide toggle only exists while the workbench is showing:
            # in Plot view it would be a control with nothing to act on.
            # Same cell grammar as the two above, so it takes the theme
            # from the same pass, with the state carried three ways - the
            # accent rule, the weight, and the word itself (rule 25).
            on = bool(self.settings.get("fr_guide_open", True))
            cell = tk.Frame(parent, bg=uibg, cursor="hand2", bd=0,
                            highlightthickness=0, relief="flat")
            cell.pack(side="left", padx=(PAD_X, 2))
            img = getattr(self.app, "_icons", {}).get("hdr::book")
            kw = ({"image": img, "compound": "left"} if img is not None
                  else {})
            lab = tk.Label(cell, text=" Guide", bg=uibg,
                           fg=(fg if on else muted),
                           font=self.app._F(0, "bold" if on else "normal"),
                           padx=8, pady=3, bd=0, highlightthickness=0,
                           relief="flat", **kw)
            lab.image = img            # tk needs the reference held
            lab.pack(side="top")
            tk.Frame(cell, height=2, bd=0, highlightthickness=0,
                     bg=(accent if on else uibg)).pack(side="top", fill="x")
            for w in (cell, lab):
                w.bind("<Button-1>", lambda e: self.toggle_guide())
            self._switch_lbls["guide"] = lab
            self._tip(lab, "Show or hide the workbench guide beside the "
                           "plot. It is the same text the Guide / notes box "
                           "carries under 'Fringe analysis'. The split "
                           "between the two is yours to drag.")

            # The tear-off, in the same cell grammar.  The pop-out was
            # finished and had no way in: no button, no menu entry, no
            # shortcut, nothing.  It reads as a state because it is one --
            # the cell lights up while the second window is open, and a
            # click then raises that window instead of making another.
            try:
                on = bool(self._popout is not None
                          and self._popout.winfo_exists())
            except tk.TclError:
                on = False
            cell = tk.Frame(parent, bg=uibg, cursor="hand2", bd=0,
                            highlightthickness=0, relief="flat")
            cell.pack(side="left", padx=(PAD_X, 2))
            img = getattr(self.app, "_icons", {}).get("copy")
            kw = ({"image": img, "compound": "left"} if img is not None
                  else {})
            lab = tk.Label(cell, text=" Pop out", bg=uibg,
                           fg=(fg if on else muted),
                           font=self.app._F(0, "bold" if on else "normal"),
                           padx=8, pady=3, bd=0, highlightthickness=0,
                           relief="flat", **kw)
            lab.image = img            # tk needs the reference held
            lab.pack(side="top")
            tk.Frame(cell, height=2, bd=0, highlightthickness=0,
                     bg=(accent if on else uibg)).pack(side="top", fill="x")
            for w in (cell, lab):
                w.bind("<Button-1>", lambda e: self.popout())
            self._switch_lbls["popout"] = lab
            self._tip(lab, "Float the FFT view into its own window, for a "
                           "second monitor. It carries the same guide. F11 "
                           "fills the screen, and Escape or the X sends it "
                           "home again.")

    def _adopt_new_traces(self):
        """Pick the trace list up again when the app's results change.

        app.py's workbench touchpoints are the view switch, the Fringe tab
        and the session payload -- and none of them calls on_trace_change,
        so a Run started while the Fringe view was ALREADY showing left the
        workbench on its empty state, "Run a folder to load traces", over a
        window full of freshly loaded traces.  The view switch is repainted
        on that same pass, so this is the honest hook; a signature compare
        keeps it to one tuple for the frequent callers.
        """
        if not self._built:
            return
        sig = tuple(r.get("label") for r in self._records())
        if sig == self._recs_seen:
            return
        self.on_trace_change()

    def _pick_view(self, key):
        if key == "fringe":
            self.activate()
        else:
            self.deactivate()

    # ---- the guide beside the plot ---------------------------------------
    def _guide_body(self, parent, lines, width=38):
        """A read-only guide text box, in the Guide / notes panel's shape.

        One builder for all three places the workbench shows guide copy --
        the pane beside the plot, the pop-out's card and the results
        window's card -- so there is one set of tags and one place a
        rendering rule can be wrong.
        """
        txtf = ttk.Frame(parent)
        txtf.pack(fill="both", expand=True)
        sb = ttk.Scrollbar(txtf)
        sb.pack(side="right", fill="y")
        txt = tk.Text(txtf, width=width, wrap="word", relief="flat", padx=6,
                      pady=4, highlightthickness=0, bd=0,
                      yscrollcommand=sb.set)
        txt.pack(side="left", fill="both", expand=True)
        sb.config(command=txt.yview)
        # every heading gets a mark, so a jump target is a real place in the
        # text rather than a line number that moves when the copy changes
        heads = []
        for kind, text in lines:
            if kind == "h":
                mark = "sec%d" % len(heads)
                txt.mark_set(mark, "end-1c")
                txt.mark_gravity(mark, "left")
                heads.append((text, mark))
            # one row at a time so the heading marks keep their places,
            # but through app.py's filler: an indented row hands its
            # leading spaces to a hanging-indent tag there (R20 3b)
            self.app._guide_fill(txt, [(kind, text)])
        txt.configure(state="disabled")
        txt._fr_heads = heads
        self._guide_boxes = getattr(self, "_guide_boxes", [])
        self._guide_boxes.append(txt)
        self._retint_guide(txt)
        return txt

    def _retint_guide(self, txt):
        """Take every colour and font in a guide box from the live palette.

        Called on build AND from `sync_view_switch`, which is the pass the
        theme chain already runs through the tab strip (`_recolor_tk` ->
        `_sync_tabs`).  Without it the box kept the colours it was born in
        and a dark-built pane stayed dark under Standard Light.
        """
        try:
            if not txt.winfo_exists():
                return False
        except tk.TclError:
            return False
        ubg, ufg = self._pal()[:2]
        try:
            txt.configure(background=ubg, foreground=ufg,
                          insertbackground=ufg, font=self.app._F(1),
                          selectbackground=self.app._blendc(
                              ubg, self.app._brand()["ac1"], 0.35),
                          selectforeground=ufg)
            # ONE tag scheme for every guide surface in the program
            # (R20): this pane used to keep a private copy, which is how
            # it missed the hanging indents, the mono spacing and the
            # half-height paragraph gap app.py's cards got. The box body
            # is _F(1), so the shared helper takes delta=1.
            self.app._guide_tags(txt, delta=1)
        except tk.TclError:
            return False
        return True

    def _retint_guides(self):
        """Repaint every live guide box; forget the ones that have gone."""
        boxes = getattr(self, "_guide_boxes", None)
        if not boxes:
            return
        self._guide_boxes = [t for t in boxes if self._retint_guide(t)]
        lab = getattr(self, "_hint_lbl", None)
        if lab is not None:
            try:
                lab.configure(foreground=(
                    self.app._muted_fg()
                    if lab.cget("text") in (self.HINT_DEFAULT,
                                            self.HINT_EMPTY)
                    else self._pal()[1]))
            except tk.TclError:
                pass

    def _open_guide_pane(self):
        """Build and add the guide pane, once.

        The title row carries the same close affordance the session tabs do
        and a jump list of the page's own headings: the pane is a page, and
        a page you cannot navigate or shut from its own header is a pane
        you stop opening.
        """
        if self._guide_pane is not None:
            return self._guide_pane
        a = self.app
        card = a._card(self._center_pw, grow="both",
                       width=a._em() * GUIDE_DEF_W)
        hdr = a._lf_header(card, "Guide", icon="book")
        x = a._lbl(hdr, text="×", font=a._F(1))
        x.pack(side="left", padx=(PAD_X * 2, 0))
        x.configure(cursor="hand2")
        x.bind("<Button-1>", lambda e: self.toggle_guide(False))
        self._tip(x, "Close the guide. The Guide button on the tab strip "
                     "brings it back at the same width.")
        card.set_title(hdr)

        nav = ttk.Frame(card.body)
        nav.pack(fill="x", pady=(0, 2))
        a._lbl(nav, text="Jump to", width=LBL_W2 + 2).pack(side="left")
        self._guide_jump_v = tk.StringVar(value="")
        self._guide_jump = ttk.Combobox(nav, textvariable=self._guide_jump_v,
                                        state="readonly", width=10)
        self._guide_jump.pack(side="left", fill="x", expand=True)
        self._guide_jump.bind("<<ComboboxSelected>>", self._guide_goto)
        self._tip(self._guide_jump,
                  "Scroll the guide to one of its sections.")

        self._guide_txt = self._guide_body(card.body, guide_text(),
                                           width=GUIDE_MIN_W)
        heads = [h for h, _m in getattr(self._guide_txt, "_fr_heads", [])]
        try:
            self._guide_jump.configure(values=heads)
        except tk.TclError:
            pass
        self._center_pw.add(card, weight=0)
        self._guide_pane = card
        self._restore_guide_scroll()
        return card

    def _guide_goto(self, _e=None):
        """Scroll the pane to the picked heading."""
        txt = getattr(self, "_guide_txt", None)
        if txt is None:
            return
        want = self._guide_jump_v.get()
        for head, mark in getattr(txt, "_fr_heads", []):
            if head == want:
                try:
                    txt.see("%s linestart" % mark)
                    txt.yview("%s linestart" % mark)
                except tk.TclError:
                    pass
                return

    def _remember_guide_scroll(self):
        txt = getattr(self, "_guide_txt", None)
        if txt is None:
            return
        try:
            self._guide_scroll = float(txt.yview()[0])
        except (tk.TclError, ValueError, IndexError):
            pass

    def _restore_guide_scroll(self):
        """Put the reader back where they were, for this run of the program.

        Deliberately in memory and not in settings: where you had scrolled
        to an hour ago in another dataset is not where you want to be on a
        fresh start.
        """
        frac = getattr(self, "_guide_scroll", 0.0)
        txt = getattr(self, "_guide_txt", None)
        if not frac or txt is None:
            return

        def _go():
            try:
                txt.yview_moveto(frac)
            except tk.TclError:
                pass
        try:
            self.app.root.after_idle(_go)
        except (AttributeError, tk.TclError):
            _go()

    def toggle_guide(self, show=None):
        """Show or hide the guide beside the plot.

        The default is "whatever it is not doing now", read off the pane
        itself rather than off the setting: the fitter below can have stood
        the guide down, and a Guide press then has to mean "bring it back",
        not "close the thing that is already closed".

        Hiding remembers the width first, so turning it back on puts the
        split back where it was rather than at the default share.
        """
        self.build()
        showing = self._guide_pane is not None
        want = (not showing) if show is None else bool(show)
        if want:
            snug = not self._guide_fits()
            # asking for prose on a narrow pane gets prose: the reader
            # overrules the fitter, and one more press undoes it
            self._guide_fit = "forced" if snug else "auto"
            self._guide_said = False
            self.settings["fr_guide_open"] = True
            self._open_guide_pane()
            self._restore_guide_sash()
            if snug:
                self._status("the centre is snug, so the guide and the plot "
                             "are sharing it. Press Guide again to give the "
                             "plot the whole width back.")
        else:
            self._remember_guide_sash()
            self._remember_guide_scroll()
            self._drop_guide_pane()
            self.settings["fr_guide_open"] = False
            self._guide_fit = "auto"
            self._guide_said = False
        self.sync_view_switch()
        return want

    def _drop_guide_pane(self):
        """Take the guide out of the split and forget its widgets."""
        if self._guide_pane is None:
            return
        try:
            self._center_pw.forget(self._guide_pane)
        except tk.TclError:
            pass
        txt = getattr(self, "_guide_txt", None)
        boxes = getattr(self, "_guide_boxes", None)
        if boxes and txt is not None:
            self._guide_boxes = [t for t in boxes if t is not txt]
        try:
            self._guide_pane.destroy()
        except tk.TclError:
            pass
        self._guide_pane = None
        self._guide_txt = None

    # ---- how the centre is divided ----------------------------------------
    def _pane_total(self):
        try:
            return int(self._center_pw.winfo_width())
        except (AttributeError, tk.TclError):
            return 0

    def _plot_floor(self):
        """The narrowest FFT canvas worth aiming a click into, in pixels."""
        return int(self.app._em() * PLOT_MIN_W)

    def _guide_floor(self):
        """The width below which the guide's prose stops being prose."""
        return int(self.app._em() * GUIDE_MIN_W)

    def _guide_fits(self, total=None):
        """True when the centre can hold both floors at the same time."""
        total = self._pane_total() if total is None else total
        if total < 120:                 # not laid out yet; assume it fits
            return True
        return total >= self._plot_floor() + self._guide_floor()

    def _guide_w_want(self, total):
        """The guide's width for a pane `total` px wide.

        One place decides it, so the setter and the check that the setter
        worked can never disagree about what "right" was.

        The plot is the protagonist.  Whatever the guide would like, it may
        not push the FFT canvas below PLOT_MIN_W ems -- that clamp is the
        whole of the 160 px bug, where a fixed 276 px of prose took the
        centre first and left the plot half a micron of n*t per pixel.
        Above that floor a width the reader dragged is honoured exactly;
        only a split nobody has ever dragged falls back to the default
        share.  The one case where the guide outranks the plot is "forced":
        the reader pressed Guide on a pane too narrow for both, and asking
        for prose has to give prose.
        """
        em = self.app._em()
        w = int(self.settings.get("fr_guide_w") or 0)
        if w < em * GUIDE_MIN_W:
            w = min(em * GUIDE_DEF_W, int(total * 0.55))
        floor = min(self._guide_floor(), total)
        room = max(0, total - self._plot_floor())
        if self._guide_fit == "forced":
            room = max(room, floor)
        return int(min(max(w, min(floor, room)), room))

    def _remember_guide_sash(self):
        """Record a split the reader chose.

        Bound to the pane's own button release as well as to hide and
        deactivate: fr_guide_w was only ever written on the way out, so a
        drag followed by closing the program was forgotten and the setting
        sat at 0 for good.
        """
        if self._guide_pane is None:
            return
        try:
            w = self._center_pw.winfo_width() - self._center_pw.sashpos(0)
        except (tk.TclError, IndexError):
            return
        # a width at or under the floor is the collapsed state, not a
        # choice; remembering it is how the bug used to persist itself
        if w >= self._guide_floor():
            self.settings["fr_guide_w"] = int(w)

    def _on_pane_configure(self, event=None):
        """Debounced: dragging a window edge fires this per pixel."""
        w = int(getattr(event, "width", 0) or 0) if event is not None else 0
        if w and w == self._pane_w_seen:
            return                      # a height-only change costs nothing
        self._pane_w_seen = w
        if self._fit_after is not None:
            try:
                self.app.root.after_cancel(self._fit_after)
            except (AttributeError, tk.TclError, ValueError):
                pass
            self._fit_after = None
        try:
            self._fit_after = self.app.root.after(80, self._fit_split)
        except (AttributeError, tk.TclError):
            self._fit_split()

    def _fit_split(self):
        """Keep the plot above its floor as the centre changes size.

        Three moves, and only one of them can apply on any one pass: stand
        the guide down when both floors stop fitting, bring it back when
        they fit again, and otherwise take back whatever the guide is
        holding above the plot's floor.  Growing the window still grows the
        PLOT -- the figure holder carries the pane weight -- so this never
        widens the guide behind the reader's back.
        """
        self._fit_after = None
        if not self._built or not self._active:
            return
        total = self._pane_total()
        if total < 120:
            return
        quiet, self._fit_quiet = self._fit_quiet, False
        fits = self._guide_fits(total)
        if (self._guide_pane is not None and not fits
                and self._guide_fit != "forced"):
            self._remember_guide_sash()
            self._remember_guide_scroll()
            self._drop_guide_pane()
            self._guide_fit = "hidden"
            self.sync_view_switch()
            if not self._guide_said and not quiet:
                self._guide_said = True
                self._status("the centre got snug, so the guide stepped "
                             "aside to leave the plot room to work in. "
                             "Widen the window, or press Guide, and it "
                             "comes straight back.")
            return
        if self._guide_pane is None and fits and self._guide_fit == "hidden":
            self._guide_fit = "auto"
            self._guide_said = False
            self._open_guide_pane()
            self.sync_view_switch()
            self._restore_guide_sash()
            if not quiet:
                self._status("room again. the guide sits beside the plot.")
            return
        self._clamp_sash(total)

    def _clamp_sash(self, total=None):
        """Give the plot its floor back, without disturbing a split that is
        already fine."""
        if self._guide_pane is None:
            return
        total = self._pane_total() if total is None else total
        try:
            got = total - self._center_pw.sashpos(0)
        except (tk.TclError, IndexError):
            return
        cap = max(0, total - self._plot_floor())
        if self._guide_fit == "forced":
            cap = max(cap, min(self._guide_floor(), total))
        if got > cap:
            try:
                self._center_pw.sashpos(0, total - cap)
            except (tk.TclError, IndexError):
                pass

    def _restore_guide_sash(self, tries=14):
        """Put the sash back where it was left, and KEEP it there.

        Two failures, one fix.  On the first activation the paned window has
        no width yet, so a single after_idle that finds zero gave up and left
        the guide as a hairline.  And on every re-show the sash was right
        when we set it and wrong a moment later: a re-added ttk pane is
        re-sized by the pane manager on a LATER geometry pass, which handed
        the guide 4 px -- Nhan's "if i click it to hide then show again, it
        doesn't show anymore but is collapsed".  Checking once, however
        carefully, cannot catch that; so this is a short watchdog instead.
        It re-asserts the width whenever the pane is below the width at
        which the text stops being prose, and stops after three consecutive
        clean passes.  Above that floor it never interferes, so dragging the
        split remains entirely the user's.
        """
        if self._guide_pane is None:
            return

        # With nothing remembered the split is OURS to set, not ttk's: left
        # alone it hands the pane the card's requested width, and the first
        # hide then remembers that as if the user had chosen it.
        strict = not int(self.settings.get("fr_guide_w") or 0)

        def _place(n=tries, ok=0):
            if self._guide_pane is None:
                return
            try:
                total = self._center_pw.winfo_width()
                if total >= 120:
                    want = self._guide_w_want(total)
                    floor = min(want, self._guide_floor())
                    got = total - self._center_pw.sashpos(0)
                    # both directions now: too WIDE is the 160 px bug, and
                    # the watchdog is the pass that has to catch it
                    if (got < floor - 4 or got > want + 4
                            or (strict and abs(got - want) > 8)):
                        self._center_pw.sashpos(0, max(0, total - want))
                        ok = 0
                    else:
                        ok += 1
            except (tk.TclError, ValueError, IndexError):
                ok = 0
            if ok >= 3 or n <= 0:
                return
            try:
                self.app.root.after(50, _place, n - 1, ok)
            except (AttributeError, tk.TclError):
                pass
        try:
            self.app.root.after_idle(_place)
        except (AttributeError, tk.TclError):
            _place()

    def is_active(self):
        return self._active

    def on_defringe_switch(self):
        """The Defringe master switch moved.

        Harmless since R17 (D2): the right column no longer answers to df --
        it draws the cleaned curve whenever something is being filtered, as
        his window does -- so this repaints and changes nothing.  The hook is
        kept because the app calls it, guarded, on every flip of the switch.
        """
        if self._built and self._active:
            self._request_redraw(now=True)

    def toggle(self):
        self.deactivate() if self._active else self.activate()

    def activate(self):
        if self._active:
            return
        self.build()
        try:
            self.app.canvas.get_tk_widget().pack_forget()
        except (AttributeError, tk.TclError):
            pass
        self._center_pw.pack(side="top", fill="both", expand=True)
        self._active = True
        self._restore_guide_sash()
        # The workbench opening on a narrow window is a layout decision, not
        # something that just happened to the reader -- so the first fit
        # says nothing and lets activate's own greeting stand.  A guide that
        # disappears while they watch still explains itself.
        self._fit_quiet = True
        self._sync_view_buttons()
        self._on_pane_configure()     # and re-fit once the pane has a width
        self.settings["fr_view"] = "fringe"
        self.sync_view_switch()
        self.on_trace_change()
        # the mouse grammar is only worth reciting when there is something
        # to aim it at; over an empty plot it reads as a broken promise
        if self._records():
            self._status("workbench open. left-click a peak to notch it, "
                         "right-click to pin the fundamental.")
        else:
            self._status("Run a folder first. The workbench reads fringes "
                         "out of loaded traces.")

    def deactivate(self):
        if not self._active:
            return
        self._remember_guide_sash()
        self._remember_guide_scroll()
        self._set_cursor("")
        try:
            self._center_pw.pack_forget()
        except tk.TclError:
            pass
        try:
            self.app.canvas.get_tk_widget().pack(side="top", fill="both",
                                                 expand=True)
        except (AttributeError, tk.TclError):
            pass
        self._active = False
        self.settings["fr_view"] = "plot"
        self.sync_view_switch()

    # =======================================================================
    # data plumbing
    # =======================================================================
    def _records(self):
        loc = getattr(self, "_local", None)
        if loc and loc.get("recs"):
            app_now = tuple(r.get("label") for r in
                            (getattr(self.app, "results", None) or []))
            if app_now == loc.get("app_sig"):
                return list(loc["recs"])
            # a fresh Run in the main window takes over
            self._local = None
        return list(getattr(self.app, "results", None) or [])

    def _record(self, label=None):
        label = self._label if label is None else label
        for r in self._records():
            if r.get("label") == label:
                return r
        return None

    def on_trace_change(self, label=None):
        """Refresh the trace list and move to `label` (or keep the current
        one).  The app calls this after a Run, a session switch, or a rescan."""
        if not self._built:
            return
        self._dk_cache = {}
        recs = self._records()
        self._recs_seen = tuple(r.get("label") for r in recs)
        self._adopt_legacy_disk()
        # the dropdown walks the experiment's path: compression
        # ascending, then decompression descending (his ordering)
        names = [r["label"] for r in self._ordered_recs()]
        try:
            self._trace_cb.configure(values=names)
            self._pcb_marks = None     # the markers go back on next refresh
        except (AttributeError, tk.TclError):
            pass
        label = self._plain_label(label) if label else None
        if label is None:
            label = self._label if self._label in names else (names[0]
                                                              if names else None)
        if label != self._label:
            if not self._leave_guard():
                label = self._label
        moved = label != self._label
        if moved:
            self._stash_live()
        self._label = label
        self.trace_v.set(label or "")
        self._load_wl_override()
        if moved:
            self._apply_point_inputs()
        self._invalidate(every=True)
        self._refresh_pressure_nav_ui()

    def _on_trace_pick(self, _e=None):
        # the dropdown carries a status marker; the state is keyed by the
        # plain label, so every read of it normalises first
        want = self._plain_label(self.trace_v.get())
        if want == self._label:
            return
        if not self._leave_guard():
            self.trace_v.set(self._label or "")
            self._pcb_marks = None
            self._relabel_pressure_cb()
            return
        self._stash_live()
        self._label = want
        self.trace_v.set(want)
        self._load_wl_override()
        self._apply_point_inputs()
        self._invalidate(every=True)
        self._refresh_pressure_nav_ui()

    def _step_trace(self, d):
        names = [r["label"] for r in self._ordered_recs()]
        if not names:
            return
        try:
            i = names.index(self._label)
        except ValueError:
            i = 0
        j = i + d
        if j < 0 or j >= len(names):
            return                     # his arrows stop at the ends
        self.trace_v.set(names[j])
        self._on_trace_pick()

    def _load_pressure_box(self):
        """Fill the P box from the loaded spectrum (his _load_into_state,
        13062).  Every load re-seeds it, so an override never follows the
        reader on to the next point."""
        p = self._trace_pressure()
        self._suspend = True
        try:
            self.dp_v.set("" if p is None else "%g" % p)
        except tk.TclError:
            pass
        finally:
            self._suspend = False

    def _load_wl_override(self):
        self._load_pressure_box()
        ov = self.settings.get("fr_wl_overrides") or {}
        key = self._dataset_key()
        self._suspend = True
        try:
            if key in ov:
                lo, hi = ov[key]
                self.wlmin_v.set("%g" % lo)
                self.wlmax_v.set("%g" % hi)
                self.wlover_v.set(True)
            else:
                self.wlover_v.set(False)
        finally:
            self._suspend = False
        # His load rule (13091-13097): the pressure-derived indices are a
        # function of THIS point's pressure, so they are recomputed on every
        # load rather than carried over from the point before.
        self._sync_anvil_n()
        self._sync_layer2_n()

    # ---- per-trace state --------------------------------------------------
    def _dkey(self, label=None):
        """The identity one trace's state is filed under: his "stem:<stem>".

        The display label is not an identity.  "20 GPa" names a different
        spectrum in every series, and two spectra in ONE folder can sit at the
        same pressure (a compression/decompression pair, two samples at
        ambient), so a label key handed both of them the same notches, the
        same role glyphs and the same fits.  A file stem is unique inside its
        folder by construction, which is why Matthew keys on it.

        The trade he documents holds here too: the key follows the FILE NAME,
        so renaming a spectrum starts it fresh.
        """
        label = self._label if label is None else label
        if label is None:
            return None
        # Every read of the per-trace state asks for this, so the record
        # scan behind it is remembered.  The guard is the working set the
        # answer depends on: the loaded folder and how many traces the main
        # window holds.
        sig = ((getattr(self, "_local", None) or {}).get("folder"),
               len(getattr(self.app, "results", None) or []))
        if sig != getattr(self, "_dk_sig", None):
            self._dk_cache = {}
            self._dk_sig = sig
        hit = self._dk_cache.get(label)
        if hit is None:
            hit = self._dk_cache[label] = "stem:" + self._stem_of(label)
        return hit

    def _tr(self, label=None):
        dk = self._dkey(label)
        if dk is None:
            return None
        return self._trace.setdefault(dk, {
            "roles": {r: None for r in ROLES},
            "gauss": {r: None for r in ROLES},
            "solved": None})

    def _ch(self, chan, label=None):
        dk = self._dkey(label)
        if dk is None:
            return None
        return self._chan.setdefault((dk, chan), {
            "default_centers": [], "user_centers": [], "removed": set(),
            "unticked": set(), "user_fundamental": None, "widths": {},
            # key -> the EXACT centre in nm behind it (his `seen` dict,
            # _active_centers 13546).  See _exact_nm.
            "exact": {}})

    def _exact_nm(self, chan, kk, label=None):
        """The EXACT n*t in nm behind a 0.01 um notch key.

        The key is the identity -- it is what a tick, a width, a removal and
        the fundamental pin are filed under, and rounding is what makes two
        readings of the same peak the same peak.  The MASK is a different
        question: his keeps the measured centre as the dict VALUE beside that
        key (`seen[_ckey(c)] = float(c)`) and notches at the measured centre,
        so the mask always sits on the peak.  Ours rebuilt nm as key*1000 and
        lost up to 5 nm, which was the one thing that made a trace opened in
        the workbench disagree with the main plot, with the exported CSVs and
        with his program -- up to 1.4e-4 relative at a point.

        A key with no recorded centre falls back to key*1000, which is what a
        session written before R17 carries.
        """
        ch = self._ch(chan, label)
        if ch is None:
            return float(kk) * 1000.0
        ex = ch.setdefault("exact", {})
        v = ex.get(kk)
        if v is None:
            v = ex.get(round(float(kk), 2))
        try:
            return float(kk) * 1000.0 if v is None else float(v)
        except (TypeError, ValueError):
            return float(kk) * 1000.0

    def _note_exact(self, chan, nt_um, label=None):
        """File a measured peak's exact n*t under its own key, and hand the
        key back.  Every place a centre enters the list goes through here."""
        kk = round(float(nt_um), 2)
        ch = self._ch(chan, label)
        if ch is not None:
            ch.setdefault("exact", {})[kk] = float(nt_um) * 1000.0
        return kk

    def _active_centers_widths(self, chan):
        """(exact centres in nm, their half-widths in um), in parallel --
        his _active_centers_widths (13556-13568).  What the mask is given."""
        keys = self._active_centers(chan)
        return ([self._exact_nm(chan, k) for k in keys],
                [self._width_of(chan, k) for k in keys])

    def _fund_key(self, chan):
        """This channel's fundamental in micron keys, or None.

        Three override states, his (_fund_key, 13536-13547): the stored value
        is None for auto (the brightest detected peak), the FUND_NONE
        sentinel when the reader cleared it, or a float pinned to one peak.
        None comes back for auto-with-no-fringe AND for the cleared state --
        the difference between them lives in the stored value, which is what
        the radio column reads and what the file carries.
        """
        ch = self._ch(chan)
        if ch is None:
            return None
        uf = ch["user_fundamental"]
        if uf == FUND_NONE:
            return None
        if uf is not None:
            return uf
        return ch["default_centers"][0] if ch["default_centers"] else None

    def _active_centers(self, chan, include_unticked=False):
        """Notch centres for `chan`, in micron keys, in INSERTION order.

        His order exactly (defringe_dac _active_centers): the detected
        defaults as they were detected, then the ones picked by hand as they
        were picked.  Ours used to hoist the fundamental to the front, which
        renumbered his notch list and reordered the exported rows for no
        gain -- the mask is a sum, so the order changes nothing it computes.
        The export sorts ascending, as his does.
        """
        ch = self._ch(chan)
        if ch is None:
            return []
        keys = []
        for k in list(ch["default_centers"]) + list(ch["user_centers"]):
            if k in ch["removed"] or k in keys:
                continue
            if not include_unticked and k in ch["unticked"]:
                continue
            keys.append(k)
        return keys

    def _width_of(self, chan, kk):
        ch = self._ch(chan)
        return float(ch["widths"].get(kk, _f(self.hw_v, 3.0)))

    # =======================================================================
    # what defringe applies, per trace  (R15-B)
    # =======================================================================
    def _key_for(self, ref=None):
        """The dataset key a caller means.

        `ref` is a display label, a file stem, a dataset key or a record dict;
        None means the trace on screen.
        """
        if ref is None:
            return self._dkey()
        if isinstance(ref, dict):
            ref = ref.get("label") or ref.get("stem") or ""
        ref = str(ref)
        if not ref:
            return None
        return ref if ref.startswith("stem:") else self._dkey(ref)

    def _record_for_key(self, dk):
        """The loaded record behind a dataset key, or None."""
        if dk is None:
            return None
        for r in self._records():
            if self._dkey(r.get("label")) == dk:
                return r
        return None

    @staticmethod
    def _chan_lists(src):
        """(defaults, user, removed, unticked, fund, widths) out of EITHER a
        live channel state or a committed one.

        The two shapes differ: memory keeps sets and float keys, a committed
        copy keeps sorted lists and '%.2f' width keys.  Everything downstream
        wants one shape.
        """
        defaults, user = [], []
        for name, out in (("default_centers", defaults), ("user_centers", user)):
            for k in (src.get(name) or ()):
                try:
                    out.append(float(k))
                except (TypeError, ValueError):
                    continue

        def _fset(name):
            vals = set()
            for k in (src.get(name) or ()):
                try:
                    vals.add(float(k))
                except (TypeError, ValueError):
                    continue
            return vals

        widths = {}
        for k, v in (src.get("widths") or {}).items():
            try:
                widths[float(k)] = float(v)
            except (TypeError, ValueError):
                continue
        # key -> the exact centre in nm, his `seen` values.  A state written
        # before R17 has none, and every centre then falls back to key*1000.
        exact = {}
        for k, v in (src.get("exact") or {}).items():
            try:
                exact[float(k)] = float(v)
            except (TypeError, ValueError):
                continue
        return (defaults, user, _fset("removed"), _fset("unticked"),
                src.get("user_fundamental"), widths, exact)

    def _recipe_channel(self, src, snap, chan):
        """One channel's defringe kwargs from a channel state.

        `src` is that channel's state (live or committed), `snap` the trace's
        committed input snapshot or None.

        The centre list is ALWAYS named, empty included: a state this panel
        holds is an answer, and an empty answer means notch nothing.  Leaving
        it out would hand the core its `None` default, which notches the
        detected fundamental -- so unticking every box would still defringe.
        """
        (defaults, user, removed, unticked, fund, widths,
         exact) = self._chan_lists(src)
        keys = []
        for k in defaults + user:
            if k in removed or k in unticked or k in keys:
                continue
            keys.append(k)
        # The fundamental's three states decide two things here: which centre
        # leads the list, and whether a trace whose own detection never ran
        # asks defringe to add the detected fundamental.  FUND_NONE is an
        # answer -- this channel has no fundamental -- so it does neither.
        cleared = (fund == FUND_NONE)
        head = None if cleared else (fund if fund is not None
                                     else (defaults[0] if defaults else None))
        if head in keys:
            keys.remove(head)
            keys.insert(0, head)
        hw0 = _f(self.hw_v, 3.0)

        def _w(k):
            # a committed width is filed under its rounded key, so an exact
            # miss is asked again at 2 decimals before the default answers
            v = widths.get(k)
            if v is None:
                v = widths.get(round(k, 2))
            return float(hw0 if v is None else v)

        def _nm(k):
            # the measured centre behind this key, his `seen` value.  A state
            # written before R17 has none and falls back to key*1000.
            v = exact.get(k)
            if v is None:
                v = exact.get(round(k, 2))
            return float(k * 1000.0 if v is None else v)

        # An empty list means a deliberate nothing: every box unticked, every
        # notch cleared, or a cleared fundamental.  It never means "this trace
        # has yet to be looked at" -- a state read back from a saved session
        # whose own detection has not run holds no answer at all, so it stays
        # on the automatic path (None) and the core detects its fundamental.
        virgin = (not defaults and fund is None and not cleared)
        if not keys and virgin:
            entry = {"notch_centers_nm": None}
        else:
            entry = {"notch_centers_nm": [_nm(k) for k in keys],
                     "notch_halfwidths_um": [_w(k) for k in keys]}
            if keys and virgin:
                # the list holds the picks without the fundamental they were
                # picked beside, so the detected one joins them
                entry["add_fundamental"] = True
        lp_on = (snap or {}).get("lowpass") or {}
        lp_um = (snap or {}).get("lp_cutoff_um") or {}
        lp_roll = (snap or {}).get("lp_rolloff_um") or {}
        lp_shape = (snap or {}).get("lp_edge_shape") or {}
        live_shape, live_roll = self._lp_edge(chan)
        try:
            on = bool(lp_on[chan]) if chan in lp_on \
                else bool(self.lp_on_v[chan].get())
            cut = (lp_um[chan] if chan in lp_um
                   else self._lp_cut_or_none(chan))
            cut = None if cut is None else float(cut)
            roll = (float(lp_roll[chan]) if chan in lp_roll else live_roll)
            shape = (str(lp_shape[chan]) if chan in lp_shape else live_shape)
        except (KeyError, TypeError, ValueError, tk.TclError):
            on, cut, roll, shape = False, None, 2.0, "tanh"
        # his gate: a tick with no usable cutoff filters nothing
        if on and cut and cut > 0.0:
            entry["lowpass"] = True
            entry["lp_cutoff_um"] = float(cut)
            # the edge travels as two plain values, so the provenance
            # sidecar the Run writes stays JSON
            entry["lp_rolloff_um"] = (roll if roll > 0 else 2.0)
            entry["lp_edge_shape"] = (shape if shape in LP_EDGE_SHAPES
                                      else "tanh")
        return entry

    def defringe_recipe(self, ref=None):
        """This workbench's cleaning for ONE trace, as defringe kwargs.

        `ref` is a display label, a file stem, a dataset key or a record dict;
        None asks for the trace on screen.  EVERY loaded trace gets a recipe:

          * the trace on screen  -> the LIVE state, so an edit reaches the main
            plot without a commit
          * a trace with a committed copy -> that copy, the state its leave
            guard filed
          * anything else -> the panel's GLOBAL controls (`global_recipe`):
            the gates, the half-width, the per-channel low-pass and edge, with
            notch_centers_nm=None so the core detects THAT spectrum's own
            fundamental.  Source "global".

        None comes back only for a reference that names no dataset at all.

        Shape:
            {"gates":    {halfwidth_um, nt_min_nm, nt_max_nm, pvalue_max},
             "cfg":      FringeConfig for this trace, or None,
             "channels": {"samp_c": {notch_centers_nm, notch_halfwidths_um,
                                     add_fundamental, lowpass, lp_cutoff_um,
                                     lp_rolloff_um, lp_edge_shape},
                          "bg_c": {...}},
             "source":   "live" | "committed" | "global",
             "key":      the dataset key}

        `gates` and `cfg` carry the live Detection card -- the n*t band, the
        Fisher p, the half-width and the wavelength window, including this
        dataset's window override and its lamp-regime fine band.  Those are
        series-wide decisions, and one plot drawn under several windows would
        be a plot of nothing.
        """
        dk = self._key_for(ref)
        if dk is None:
            return None
        rec = self._record_for_key(dk)
        cfg = None
        if rec is not None and self._built:
            try:
                cfg = self._cfg_for(rec)
            except (tk.TclError, ValueError, KeyError):
                cfg = None
        folder = None
        try:
            folder = self._input_folder()
        except (AttributeError, tk.TclError):
            folder = None
        if not self._built:
            return global_recipe(self.settings, self, key=dk, cfg=cfg,
                                 rec=rec, folder=folder)
        committed = self._disk.get(dk)
        live = {chan: self._chan.get((dk, chan)) for chan in CHANNELS}
        if committed is None and not any(live.values()):
            return global_recipe(self.settings, self, key=dk, cfg=cfg,
                                 rec=rec, folder=folder)
        on_screen = (dk == self._dkey())
        snap = None if on_screen else self._inputs.get(dk)
        # a channel this trace has no state for falls to the global controls
        # on its own, so one visited channel never drags the other with it
        chans = dict(global_lowpass(self.settings, self))
        source = "live"
        for chan in CHANNELS:
            src = None
            if not on_screen and committed is not None:
                src = (committed.get("chan") or {}).get(chan)
                if src is not None:
                    source = "committed"
            if src is None:
                src = live.get(chan)
            if not src:
                continue
            chans[CHAN_KEY[chan]] = self._recipe_channel(src, snap, chan)
        st = defringe_state(self.settings, self)
        return {"gates": {"halfwidth_um": st["halfwidth_um"],
                          "nt_min_nm": st["nt_min_um"] * 1000.0,
                          "nt_max_nm": st["nt_max_um"] * 1000.0,
                          "pvalue_max": st["pvalue_max"]},
                "cfg": cfg, "channels": chans, "source": source, "key": dk}

    def defringe_recipes(self):
        """{file stem: recipe} for every LOADED trace, plus every trace this
        workbench holds state for.

        One main-thread read for the batch paths: the notch columns a Run and
        an Export write walk records the worker produces, and a recipe
        is plain numbers plus a frozen config, so it travels to that worker
        while the tk variables stay here.  A pressure nobody has opened here
        is in the map too, carrying the global controls -- there is no second
        path left for it to fall through to.

        A workbench that has never been built answers as well: every trace is
        then global, read off the fr_ settings keys, so a Run or an Export
        before the Fringe tab is ever opened still applies the saved low-pass
        and the saved detection window.
        """
        keys = set(list(self._disk) + [k[0] for k in self._chan])
        for r in self._records():
            dk = self._dkey(r.get("label"))
            if dk is not None:
                keys.add(dk)
        out = {}
        for dk in keys:
            try:                    # one awkward trace leaves the rest theirs
                rp = self.defringe_recipe(dk)
            except Exception:
                rp = None
            if rp:
                out[self._stem_from_key(dk)] = rp
        return out

    # =======================================================================
    # compute
    # =======================================================================
    def _dataset_year_month(self, rec=None):
        """(year, month) the loaded dataset was acquired in, or None.

        The acquisition folder's name is where Matthew's batch reads the
        date from ("Y03_ch29_Nov2025_ProcessedCSV"); a spectrum opened on
        its own falls back to its file stem.  Answers are remembered per
        name -- this is asked once per config build.
        """
        loc = getattr(self, "_local", None)
        folder = (loc or {}).get("folder") or self._input_folder()
        return dataset_year_month(folder, rec, self._date_cache)

    def _cfg_for(self, rec, chan=None):
        """A FringeConfig for one trace, and for `chan` where one is known.

        The config's `lp_cutoff_um` is honesty, not plumbing: the cutoff that
        actually cleans travels as a per-channel keyword.  It used to read the
        SAMPLE box for both channels, so a config describing the Background
        stated a cutoff the Background did not have.  Naming the channel makes
        it say the truth; naming none keeps the old Sample reading.

        diamond_pressure_gpa is fed from the trace's OWN parsed pressure
        whenever the Eremets model is picked -- that model is the only one
        that reads it, and a series-wide constant would quietly wrong every
        point but the anchor.

        The FINE window follows the lamp regime of the acquisition date
        (D2): a dataset taken from November 2025 on fits its fine band at
        11200 cm^-1, which is what his batch does and what his own GUI
        leaves out.  A name with no readable date keeps the legacy band.
        """
        model = self.diamond_v.get()
        if model not in DIAMOND_MODELS:
            model = "constant"
        pres = 0.0
        if model == "eremets":
            try:
                pres = float(rec.get("pressure_val") or 0.0)
            except (TypeError, ValueError):
                pres = 0.0
        wl_lo, wl_hi = _f(self.wlmin_v, 600.0), _f(self.wlmax_v, 800.0)
        if wl_hi <= wl_lo:
            wl_lo, wl_hi = 600.0, 800.0
        nt_lo, nt_hi = _f(self.ntmin_v, 8.0), _f(self.ntmax_v, 300.0)
        if nt_hi <= nt_lo:
            nt_lo, nt_hi = 8.0, 300.0
        pmax = _f(self.pmax_v, 1e-4)
        if not (0.0 < pmax <= 1.0):
            pmax = 1e-4
        tol = _f(self.tol_v, 0.15)
        hw = _f(self.hw_v, 3.0)
        cfg = FringeConfig(
            diamond_model=model, diamond_pressure_gpa=pres,
            fit_wl_min_nm=wl_lo, fit_wl_max_nm=wl_hi,
            fringe_nt_min_nm=nt_lo * 1000.0, fringe_nt_max_nm=nt_hi * 1000.0,
            fringe_pvalue_max=pmax, nt_agree_tol=(tol if tol > 0 else 0.15),
            notch_halfwidth_um=(hw if hw > 0 else 3.0),
            band_res_floor=bool(self.bandfloor_v.get()),
            # 0.0 is his "no cutoff": the mask gate reads
            # `lowpass and lp_cutoff_um and > 0`, so a box holding nothing
            # usable records a config that filters nothing.
            lp_cutoff_um=(self._lp_cut_or_none(chan if chan in CHANNELS
                                               else "Sample") or 0.0))
        ym = self._dataset_year_month(rec)
        return cfg if ym is None else config_for_date(ym, cfg=cfg)

    def _sig(self, chan):
        """Cache signature: everything that changes the computed channel."""
        ch = self._ch(chan) or {}
        keys = tuple(self._active_centers(chan))
        return (self.diamond_v.get(), self.wlmin_v.get(), self.wlmax_v.get(),
                self.ntmin_v.get(), self.ntmax_v.get(), self.pmax_v.get(),
                self.tol_v.get(), self.hw_v.get(),
                bool(self.lp_on_v[chan].get()), self.lp_v[chan].get(),
                self._lp_edge(chan),
                bool(self.bandfloor_v.get()), keys,
                tuple(round(self._width_of(chan, k), 4) for k in keys),
                ch.get("user_fundamental"),
                # the fine window rides on the acquisition date, so it
                # belongs in the key like every other config input
                self._dataset_year_month())

    def _rec_key(self, rec, chan):
        """What a memoised channel result was actually computed FROM.

        `_dkey` is the file stem, his identity for the notches, the widths
        and the role glyphs a reader owns on one trace, and it is the right
        identity for those.  It is NOT an identity for the NUMBERS.  A stem
        is unique inside ONE folder; two sessions can hold two folders that
        both carry it, and a re-run of a folder can hand the same stem a
        re-processed spectrum on a different wavelength grid.  Keyed on the
        stem alone the memo served the first spectrum's fit for the second:
        its cleaned curve, its D(raw, dark) overlay and its detected n*t,
        all belonging to another trace, and a hard ValueError from the
        measured panel the moment the two differed in length.

        So the key carries the three arrays the compute reads, by size and
        by content.  Hashing the bytes of a 2000-point spectrum costs about
        a microsecond, against the ~7 ms the memo is there to save.
        """
        parts = []
        for k in ("wl", CHAN_KEY[chan], "dark_c"):
            v = rec.get(k)
            if v is None:
                parts.append(0)
                parts.append(0)
                continue
            arr = np.ascontiguousarray(np.asarray(v, float))
            parts.append(int(arr.size))
            parts.append(hash(arr.tobytes()))
        return tuple(parts)

    def _compute(self, chan):
        """Fast per-channel compute (run_fits=False, ~7 ms), memoised on the
        cache signature so a live drag only pays for what actually changed."""
        rec = self._record()
        if rec is None:
            return None
        key = (self._dkey(), chan, self._rec_key(rec, chan), self._sig(chan))
        hit = self._cache.get(key)
        if hit is not None:
            return hit
        cfg = self._cfg_for(rec, chan)
        centers, widths = self._active_centers_widths(chan)
        # ALWAYS the explicit list, empty included.  The ticked boxes on this
        # panel are the answer; leaving the list out would hand the core its
        # `None` default, which notches the fundamental it detected -- so
        # unticking every box would still show a filtered curve, and the
        # removed fraction would describe a mask nobody asked for.
        # The centres are the EXACT measured n*t, not the 0.01 um keys they
        # are filed under: this is the call the main plot makes too, and the
        # two must land on the same peak to the last bit.
        kw = {"notch_centers_nm": centers, "notch_halfwidths_um": widths}
        lp_cut = self._lp_cut_or_none(chan)
        if self.lp_on_v[chan].get() and lp_cut is not None:
            kw["lowpass"] = True
            kw["lp_cutoff_um"] = lp_cut
            # The edge rides on the CONFIG, not on a kwarg: compute_channel_fit
            # hands its cfg straight to defringe_fft_notch, so the shape and
            # the width reach the mask without the detector needing to know
            # they exist.  A per-channel copy is what makes the two channels
            # able to hold different edges.
            shape, roll = self._lp_edge(chan)
            kw["lp_rolloff_um"] = roll
            cfg = cfg.evolve(lp_rolloff_um=roll, lp_edge_shape=shape)
        # raw - dark, for the measured panel's overlay only.  His GUI passes it
        # at both call sites and never lets it near the maths: it is stored in
        # the fit dict and plotted, nothing more (defringe_dac 7457-7467).
        raw = np.asarray(rec[CHAN_KEY[chan]], float)
        rmd = None
        dark = rec.get("dark_c")
        if dark is not None:
            try:
                dark = np.asarray(dark, float)
                if dark.shape == raw.shape:
                    rmd = raw - dark
            except (TypeError, ValueError):
                rmd = None
        try:
            fit, _I, nt, defaults = compute_channel_fit(
                rec["wl"], raw, cfg=cfg, raw_minus_dark=rmd,
                label="%s %s" % (rec["label"], chan), run_fits=False, **kw)
        except Exception as exc:                      # a degenerate spectrum
            self._status("%s: %s" % (chan, exc), warn=True)
            return None
        fi = fit.get("fft_info")
        out = {"fit": fit, "nt": nt, "fft_info": fi, "cfg": cfg,
               "defaults": [_ckey(c) for c in defaults]}
        if fi is not None:
            n = len(fi.get("norm_u_detrend", []))
            hann = float(np.sum(np.hanning(n))) if n else 1.0
            out["nt_um"] = np.asarray(fi["freqs"]) / 2000.0
            out["V"] = 2.0 * np.asarray(fi["fft_amp"]) / max(hann, 1e-12)
            ps = fi.get("peaks_sorted")
            out["peaks"] = (np.asarray(ps, dtype=int) if ps is not None
                            else np.array([], dtype=int))
            out["pv"] = fi.get("fisher_pv")
            out["corr"] = fi.get("corroborated_by") or []
        # first sight of this channel seeds the notch list with the detected
        # fundamental, and gives the width migration its centre.  The centre's
        # EXACT nm is filed beside its key at the same moment, so the very
        # first draw already notches where the main plot notches.
        ch = self._ch(chan)
        if ch is not None and out.get("defaults"):
            ex = ch.setdefault("exact", {})
            for c in defaults:
                ex[_ckey(c)] = float(c)
            ch["default_centers"] = list(out["defaults"])
            self._migrate_width(out["defaults"][0])
        self._cache[key] = out
        if len(self._cache) > 64:                     # bounded, cheap to refill
            for k in list(self._cache)[:32]:
                self._cache.pop(k, None)
        return out

    def _invalidate(self, now=True, every=False, keep_view=False):
        """Ask for a redraw after something that changes what is computed.

        The compute cache is NOT emptied here.  Its key already carries
        every parameter that can change a result: the controls (_sig) and
        the spectrum itself (_rec_key), so a stale entry cannot be served,
        it is only ever unreachable.  Emptying it threw
        away the other channel and every trace visited so far, which made
        one notch tick cost two full recomputes and a walk through a
        20-point series reuse nothing.  The 64-entry bound in _compute is
        what keeps it from growing.

        The host hears about it too: the notch list, the per-centre widths and
        the low-pass are what the main plot's df switch cleans with, so a
        change here is a change there.

        `every` says which traces the change reached.  A notch tick or a width
        is one spectrum's, so only THIS trace's cached result is dropped.  The
        low-pass, its edge and the detection window are GLOBAL controls -- they
        clean every trace the panel holds no per-trace answer for -- so those
        drop the whole cache.
        """
        self._notify_defringe(gates=False,
                              label=None if every else self._label)
        self._request_redraw(now=now, keep_view=keep_view)

    # ---- notch width migration -------------------------------------------
    def _migrate_width(self, nt_um):
        """One-time conversion of a legacy FRACTIONAL notch width.

        Before v1.4.9 the width was a fraction of the fringe frequency, so the
        same setting removed a different physical band at every n*t.  A stored
        fractional value is converted ONCE, at the trace's detected centre,
        logged, and the settings marked migrated.
        """
        s = self.settings
        if s.get("fr_width_migrated"):
            return
        frac = None
        for key, scale in (("fr_notch_width_frac", 1.0),
                           ("notch_width", 0.01)):     # the old percent slider
            if key in s:
                try:
                    frac = float(s[key]) * scale
                except (TypeError, ValueError):
                    frac = None
                break
        if frac is None or frac <= 0:
            s["fr_width_migrated"] = True              # nothing legacy stored
            return
        if nt_um is None or not (nt_um > 0):
            return                                     # wait for a centre
        hw = round(frac * float(nt_um), 3)
        s["fr_halfwidth_um"] = hw
        s["fr_width_migrated"] = True
        self._suspend = True
        try:
            self.hw_v.set("%g" % hw)
        finally:
            self._suspend = False
        self._log("Fringe: notch width converted from the old fractional "
                  "convention (%.4g of n*t) to an absolute +/-%.3g um at the "
                  "detected centre %.2f um." % (frac, hw, nt_um))

    # ---- the stack model --------------------------------------------------
    def _index(self, name, P_gpa, wl_nm):
        """Refractive index of a named material at (P, lambda)."""
        if name == fringe_materials.MEDIUM_MANUAL:
            return max(_f(self.medium_n_v, 1.0), 1e-6)
        if name in fringe_materials.MEDIUM_N_OF_P:
            try:
                return fringe_materials.medium_n(name, P_gpa, wl_nm)
            except (ValueError, ZeroDivisionError, FloatingPointError):
                return 1.0
        fn = fringe_materials.AMBIENT_N_FUNC.get(name)
        if fn is not None:
            return float(fn(wl_nm))
        return 1.0

    def _stack_params(self, rec):
        """The dict fringe_stack's line builders take, from the Stack card."""
        cfg = self._cfg_for(rec)
        wl_ref = 0.5 * (cfg.fit_wl_min_nm + cfg.fit_wl_max_nm)
        # The P box is the pressure the index models are read at (his
        # diamond_p_var, 9591). It is filled from each spectrum as it loads,
        # so untouched it IS the trace's own pressure.
        P = self._model_pressure()
        med = self.medium_v.get()
        n_med = self._index(med, P, wl_ref)
        # the two model-owned index BOXES, his way: the model writes them on
        # every load and on calc n, and what stands in them is what the
        # stack model and the solve are built from
        n_dia = max(_f(self.nd_v, fringe_optics.N_DIAMOND_CONST), 1e-6)
        try:
            self._nmed_lbl.configure(text="%.4f" % n_med)
        except (AttributeError, tk.TclError):
            pass
        med_name, samp_name, l2_name_v = self._material_names()
        n_l2 = (max(_f(self.nl2_v, 1.0), 1e-6) if self.layer2_on_v.get()
                else n_med)
        return dict(n_diamond=n_dia,
                    n_layer2=max(n_l2, 1e-6), n_medium=max(n_med, 1e-6),
                    n_sample=max(_f(self.ns_v, 1.6), 1e-6),
                    d1_um=max(_f(self.d1_v, 0.0), 0.0),
                    t_um=max(_f(self.t_v, 0.0), 0.0),
                    d2_um=max(_f(self.d2_v, 0.0), 0.0),
                    layer2_name=(l2_name_v if self.layer2_on_v.get()
                                 else med_name),
                    medium_name=med_name,
                    sample_name=samp_name,
                    anvil_name="diamond")

    def _schematic(self, p, kind):
        """One-line labelled cell stack, interfaces marked with '|'.

        Matthew draws this across each panel header so the model and the
        picture cannot drift apart in the reader's head.
        """
        A = p.get("anvil_name", "diamond")
        if kind == "sample":
            M, S = p.get("layer2_name", "layer2"), p.get("sample_name",
                                                         "sample")
            return ("lower %s  |  lower %s (d1)  |  %s (t)  |  upper %s (d2)"
                    "  |  upper %s" % (A, M, S, M, A))
        return "lower %s  |  %s (d1+t+d2)  |  upper %s" % (
            A, p.get("medium_name", "medium"), A)

    # =======================================================================
    # drawing
    # =======================================================================
    def _on_model_var(self, *_a):
        if not self._suspend:
            self._request_redraw()

    def _on_detect_var(self, *_a):
        if self._suspend:
            return
        # `_sig` carries every gate on this card, so the compute cache
        # invalidates itself; clearing it here only threw work away.
        # detection moved, so a trace that had nothing to seed onto may have
        # peaks now: let the seed speak up again
        self._seed_said.clear()
        self._notify_defringe()
        self._request_redraw()

    def _on_hw_var(self, *_a):
        if not self._suspend:
            self._notify_defringe()

    def _on_suppress(self, *_a):
        self.settings["fr_suppress_report"] = bool(self.suppress_v.get())

    def _show_clean(self, chan):
        """True when the right column draws this channel's cleaned curve.

        Two conditions, his (13678): something is being filtered -- a live
        notch, or this channel's low-pass -- and the reader has left the
        curve visible.  The Defringe master switch is NOT one of them any
        more (D2).  df ships off, so a fresh install used to open this
        workbench with no red curve at all, where his window always draws
        one; and this window is the place cleaning is decided, so hiding its
        own answer behind the main plot's switch read as the low-pass doing
        nothing.  df still governs the main plot.
        """
        try:
            have_mask = (bool(self._active_centers(chan))
                         or bool(self.lp_on_v[chan].get()))
            hidden = bool(self.hideclean_v.get())
        except (AttributeError, KeyError, tk.TclError):
            return False
        return bool(have_mask and not hidden)

    def _df_on(self):
        """The Defringe master switch, read through one method.

        It governs the MAIN PLOT: whether the cleaned absorbance is what the
        curves and the CSVs carry.  Since R17 (D2) it no longer governs this
        window's own cleaned curve -- `_show_clean` draws that whenever
        something is being filtered, as his window does -- so the two are
        deliberately separate and this is the one place the switch is read.
        """
        var = getattr(self.app, "show_notch", None)
        if var is None:
            return False
        try:
            return bool(var.get())
        except tk.TclError:
            return False

    def _notify_defringe(self, gates=True, label=None):
        """Tell the host that a defringe parameter moved.

        These gates and this half-width are not the workbench's private
        business any more (R10): the main plot's df switch and the
        notch columns a Run and an Export write all read them
        through `defringe_state`, so anything the app cached off them
        has to go.  The app's own hook decides whether a redraw is
        worth it.

        `gates` False says the detection gates held still and only one
        trace's cleaning moved, which spares the thickness read a full
        re-detection; `label` names that trace, and None means all of them.
        """
        fn = getattr(self.app, "_notch_params_changed", None)
        if not callable(fn):
            return
        try:
            fn(gates=gates, label=label)
        except TypeError:              # a host from before R15-B
            try:
                fn()
            except Exception:
                pass
        except Exception:
            pass

    def _redraw_keeping_view(self):
        """A repaint that leaves the four panels' limits where they are.

        His live cutoff redraw touches the RIGHT column only
        (_lp_apply_live -> _redraw_row0, 13996-14012): the FFT panel the
        reader is dragging in never moves under the pointer.  Ours rebuilds
        all four axes, so a panel zoomed out to reach past a large peak
        snapped back to 0..upper in the MIDDLE of the gesture -- and once it
        had, the pointer was outside the axes, the panel guard dropped every
        further motion, and the drag simply stopped at the value it had
        reached.  Measured on the real Y03 3.71 GPa Background, panel zoomed
        to 0-600 and dragged from 50 toward 500: the cutoff stopped at 162.5
        in the tab and at 106.25 in the pop-out, where his lands on the
        200 um ceiling.  The release already preserved the view (his
        preserve_view); the live pass did not.
        """
        views = self._view_limits()
        # The pop-out repaints from inside `_redraw` (its `_mirror`), into
        # its OWN axes, so the flag has to travel with the call: this window
        # can save and restore only the axes it is holding at the time.
        self._keep_view = True
        try:
            self._redraw()
        finally:
            self._keep_view = False
        self._restore_limits(views)

    def _request_redraw(self, now=False, keep_view=False):
        if not self._built:
            return
        if self._after is not None:
            try:
                self.app.root.after_cancel(self._after)
            except (tk.TclError, ValueError):
                pass
            self._after = None
        run = self._redraw_keeping_view if keep_view else self._redraw
        if now:
            run()
            return
        try:
            self._after = self.app.root.after(DEBOUNCE_MS, run)
        except tk.TclError:
            run()

    @staticmethod
    def _blank_artists():
        """The empty artist registry a paint starts from.

        One definition, because the pop-out repaints into the same
        workbench: a window that reset a shorter set left the next gesture
        reaching for a key that was not there.
        """
        return {"roles": {}, "lp": {}, "lpshade": {}, "lptext": {},
                "hover": {}, "guides": {}, "removed": {}}

    def _redraw(self):
        self._after = None
        if not self._built:
            return
        face, ink = self._page()
        self.fig.set_facecolor(face)
        for ax in (self.ax_bg, self.ax_s, self.ax_mb, self.ax_ms):
            ax.clear()
            ax.set_facecolor(face)
            for sp in ax.spines.values():
                sp.set_color(ink)
        for tw in self._twins.values():
            try:
                tw.remove()
            except Exception:
                pass
        self._twins = {}
        rec = self._record()
        if rec is None:
            self.ax_bg.text(0.5, 0.5, "Run a folder, or use Session >\n"
                            "Load raw spectra...",
                            transform=self.ax_bg.transAxes, ha="center",
                            va="center", color=ink, fontsize=10)
            self.ax_s.set_axis_off()
            for ax in (self.ax_mb, self.ax_ms):
                ax.text(0.5, 0.5, "no measured data",
                        transform=ax.transAxes, ha="center",
                        va="center", color=self.app._muted_fg(),
                        fontsize=9)
            self._layout_grid()
            self._safe_draw()
            return
        self.ax_s.set_axis_on()
        p = self._stack_params(rec)
        # unlocked, the Total box mirrors d1+t+d2 (his greyed Total)
        if not self.lock_v.get():
            try:
                self.total_v.set("%.4g" % (p["d1_um"] + p["t_um"]
                                           + p["d2_um"]))
            except tk.TclError:
                pass
        upper = self._x_upper(p)
        # the opening guess, before the panels draw: _x_upper has already
        # computed both channels, so the seed reads warm peaks and the glyphs
        # appear in this same pass.  A cold start writes the solve into the
        # boxes, so the stack model is rebuilt from them before anything is
        # drawn -- his single _redraw_all after the align, no flash of t=20
        if self._seed_roles(p, upper):
            p = self._stack_params(rec)
            upper = self._x_upper(p)
        # every artist a gesture can grab is re-registered by this pass, so a
        # handle from the previous one can never be moved off screen
        self._artists = self._blank_artists()
        self._nt_labels = {}          # rebuilt with the axes, like the rings
        self._schem_labels = {}
        self._hover_key = None
        for chan in CHANNELS:
            self._draw_panel(chan, rec, p, upper)
        for chan in CHANNELS:
            self._draw_measured(chan, rec)
        self._refresh_reports()
        self._refresh_notch_rows()
        self._refresh_roles()
        self._refresh_state_indicators()
        self._layout_grid()
        self._fit_labels()
        self._safe_draw()
        self._persist()
        if self._popout is not None:
            self._mirror_popout()

    def _safe_draw(self):
        try:
            self.canvas.draw_idle()
        except Exception:
            pass

    def _fit_labels(self, canvas=None):
        """Turn any stagger label that overruns its axes around.

        Each boxed label is anchored on its own n*t and grows away from it,
        and the side it grows to is picked from which half of the span the
        line sits in.  That is right until the axes get narrow, where a
        line just short of the middle puts its whole box past the right
        spine.  Measuring after the layout costs one text extent per label
        and settles it exactly; a flip that would only move the overrun to
        the other edge is not made.
        """
        canvas = self.canvas if canvas is None else canvas
        try:
            rend = canvas.get_renderer()
        except Exception:
            return False
        moved = False
        for chan, labs in self._nt_labels.items():
            ax = self._axes.get(chan)
            if ax is None:
                continue
            box = ax.get_window_extent()
            for t in labs:
                try:
                    tb = t.get_window_extent(rend)
                except Exception:
                    continue
                pad = 8.0                  # the rounded box drawn round it
                w = (tb.x1 - tb.x0) + 2 * pad
                if t.get_ha() == "left" and tb.x1 + pad > box.x1:
                    if tb.x0 + pad - w >= box.x0:
                        t.set_ha("right")
                        moved = True
                elif t.get_ha() == "right" and tb.x0 - pad < box.x0:
                    if tb.x1 - pad + w <= box.x1:
                        t.set_ha("left")
                        moved = True
        # The cell schematic across each panel header starts at its axes'
        # left edge and reads rightwards, so it used to run off the end of
        # the figure and cut a word in half ("Argon (d1+t+d2").  Its room
        # is its own COLUMN, not the figure: past the spectra panel's tick
        # labels it collides with them (R14).
        try:
            fw = float(canvas.figure.get_window_extent().width)
        except Exception:
            fw = 0.0
        for chan, t in self._schem_labels.items():
            if fw <= 0:
                break
            if self._fit_schem(chan, t, rend, fw):
                moved = True
            if self._fit_head(chan, getattr(t, "_fr_head", None), rend, fw):
                moved = True
        if self._thin_x_ticks(rend):
            moved = True
        return moved

    TICK_GAP_PX = 5.0            # air a tick label keeps from its neighbour

    def _thin_x_ticks(self, rend):
        """Hide x tick labels until the numbers stop touching.

        A panel is a quarter of the canvas wide and the wavenumber scale
        wants five digits per label, so at 1400 px all four panels ran
        their numbers together into one grey band; the wavelength scale
        along the top is 1/x, so its labels bunch at one end whatever the
        spacing.  Both are settled the same way: sweep left to right and
        keep a label only when it clears the last one kept.  Measured, so
        a wide canvas keeps every label it always had.  The ticks stay;
        only the type goes.
        """
        moved = False
        axes = list((self._axes or {}).values())
        axes += list((getattr(self, "_maxes", None) or {}).values())
        axes += [x for k, x in (getattr(self, "_twins", None) or {}).items()
                 if str(k).startswith("sec_")]
        for ax in axes:
            try:
                labs = [t for t in ax.get_xticklabels() if t.get_text()]
            except Exception:
                continue
            if len(labs) < 3:
                continue
            spans = []
            for t in labs:
                try:
                    bb = t.get_window_extent(rend)
                except Exception:
                    continue
                spans.append((float(bb.x0), float(bb.x1), t))
            spans.sort()
            keep = self._tick_keep(spans)
            for i, (_x0, _x1, t) in enumerate(spans):
                on = i in keep
                t.set_visible(on)
                if not on:
                    moved = True
        return moved

    def _tick_keep(self, spans):
        """Which of these tick labels stay: the widest EVEN stride that
        clears, so the scale still reads as a scale.  A 1/x axis can bunch
        at one end past any stride; that falls back to a left-to-right
        sweep, which always clears."""
        n = len(spans)
        gap = self.TICK_GAP_PX

        def clear(idx):
            edge = None
            for i in idx:
                x0, x1, _t = spans[i]
                if edge is not None and x0 < edge + gap:
                    return False
                edge = x1
            return True
        for k in range(1, n + 1):
            idx = list(range(0, n, k))
            if clear(idx):
                return set(idx)
        keep, edge = set(), None
        for i in range(n):
            x0, x1, _t = spans[i]
            if edge is None or x0 >= edge + gap:
                keep.add(i)
                edge = x1
        return keep

    def _fit_head(self, chan, t, rend, fw):
        """Keep the panel's name line inside its own column.

        "Background   n*t = 27.59 um" is 193 px of bold type; on a
        1400 px window the FFT column is 155 px wide, so the line used to
        run over the spectra panel's tick labels beside it.  It shrinks,
        down to HEAD_PT_MIN.
        """
        if t is None:
            return False
        t.set_fontsize(HEAD_PT)
        try:
            bb = t.get_window_extent(rend)
        except Exception:
            return False
        room = self._schem_limit(chan, rend, fw) - float(bb.x0)
        want = float(bb.x1 - bb.x0)
        if room <= 0 or want <= 0 or want <= room:
            return False
        t.set_fontsize(max(HEAD_PT_MIN, HEAD_PT * room / want))
        return True

    def _schem_limit(self, chan, rend, fw):
        """How far right the FFT panel's header may reach, in figure px.

        Up to the spectra panel beside it, minus that panel's own tick
        labels and a finger of air.  With no spectra panel to the right
        the figure edge is the limit, as it always was.
        """
        mx = (getattr(self, "_maxes", None) or {}).get(chan)
        if mx is None:
            return fw - 3.0
        try:
            return float(mx.get_tightbbox(rend).x0) - 6.0
        except Exception:
            try:
                return float(mx.get_position().x0) * fw - 6.0
            except Exception:
                return fw - 3.0

    @staticmethod
    def _schem_two_lines(full):
        """Break the cell stack at the interface nearest its middle."""
        parts = full.split("|")
        if len(parts) < 2:
            return None
        half, run, cut, best = len(full) / 2.0, 0, 1, None
        for i, seg in enumerate(parts[:-1]):
            run += len(seg) + 1
            d = abs(run - half)
            if best is None or d < best:
                best, cut = d, i + 1
        # the interface the break lands on keeps its bar, at the end of
        # the first line, so the stack still reads as a stack
        return ("|".join(parts[:cut]).rstrip() + "  |\n"
                + "|".join(parts[cut:]).lstrip())

    def _fit_schem(self, chan, t, rend, fw):
        """Fit one cell-schematic header into its column.

        A small shrink keeps it on one line.  Past that the stack is
        broken at the interface nearest its middle and read over two
        lines at full size, because 5 pt of grey text is not reading
        matter.  Both forms carry every word Matthew writes.
        """
        full = getattr(t, "_fr_full", None)
        if full is None:
            full = t.get_text()
            t._fr_full = full
        t.set_text(full)
        t.set_fontsize(SCHEM_PT)

        def span():
            try:
                bb = t.get_window_extent(rend)
                return float(bb.x0), float(bb.x1 - bb.x0)
            except Exception:
                return 0.0, 0.0
        x0, want = span()
        room = self._schem_limit(chan, rend, fw) - x0
        if want <= room or want <= 0 or room <= 0:
            return False
        if room / want >= SCHEM_WRAP_AT:
            t.set_fontsize(SCHEM_PT * room / want)
            return True
        two = self._schem_two_lines(full)
        if two is None:
            t.set_fontsize(max(SCHEM_PT_MIN, SCHEM_PT * room / want))
            return True
        t.set_text(two)
        _x, want = span()
        if 0.0 < room < want:
            t.set_fontsize(max(SCHEM_PT_MIN, SCHEM_PT * room / want))
        return True

    def _layout_grid(self, fig=None):
        """Place the 2x2 grid from measured furniture, in place of
        tight_layout (see GRID_PT for why that cannot do this figure).

        The margins are pixel amounts; matplotlib wants `wspace` and
        `hspace` as fractions of the MEAN cell size, so the gap asked for
        in pixels is inverted back into those two numbers here.  For a
        2 x 2 grid  gap = space * (extent - gap) / 2, which gives
        space = 2 * gap / (extent - gap) whatever the width ratios are.
        """
        fig = self.fig if fig is None else fig
        try:
            ext = fig.get_window_extent()
            W, H = float(ext.width), float(ext.height)
            k = float(fig.dpi) / 72.0
        except Exception:
            return
        if W < 40.0 or H < 40.0:
            return
        m = dict((n, v * k) for n, v in GRID_PT.items())
        cap = 1.0 - GRID_MIN_AXES
        hor = m["left"] + m["right"] + m["wgap"]
        if hor > cap * W:
            s = cap * W / hor
            for n in ("left", "right", "wgap"):
                m[n] *= s
        ver = m["top"] + m["bottom"] + m["hgap"]
        if ver > cap * H:
            s = cap * H / ver
            for n in ("top", "bottom", "hgap"):
                m[n] *= s
        left = m["left"] / W
        right = 1.0 - m["right"] / W
        bottom = m["bottom"] / H
        top = 1.0 - m["top"] / H
        gw, gh = m["wgap"] / W, m["hgap"] / H
        # A GridSpec built with its own wspace / hspace OVERRIDES the
        # figure's, so those two are handed back before the figure is
        # asked to place the grid.
        for ax in fig.axes:
            ss = ax.get_subplotspec() if hasattr(ax, "get_subplotspec") \
                else None
            gs = ss.get_gridspec() if ss is not None else None
            if gs is None:
                continue
            for name in ("left", "right", "bottom", "top", "wspace",
                         "hspace"):
                if getattr(gs, name, None) is not None:
                    setattr(gs, name, None)
        try:
            fig.subplots_adjust(
                left=left, right=right, bottom=bottom, top=top,
                wspace=2.0 * gw / max(right - left - gw, 1e-6),
                hspace=2.0 * gh / max(top - bottom - gh, 1e-6))
        except (ValueError, AttributeError):
            pass

    @staticmethod
    def _tight(fig, **kw):
        """fig.tight_layout, with matplotlib's own complaint kept quiet.

        A pane dragged very narrow, or a results grid on a small screen,
        makes tight_layout give up and say so on stdout once per redraw --
        console noise on a program that is working fine.  The filter is
        around this one call and matches only that message, so a genuine
        warning from anywhere else in the draw still gets through.
        """
        try:
            with warnings.catch_warnings():
                warnings.filterwarnings("ignore",
                                        message=".*[Tt]ight.?layout.*",
                                        category=UserWarning)
                fig.tight_layout(**kw)
        except Exception:
            pass

    def _persist(self):
        """Write the card's live values back into the "# b keys" settings.

        Called from the debounced redraw rather than from every trace_add, so
        a spinbox held down costs one write, not thirty.  The app writes the
        settings file itself on close.
        """
        s = self.settings
        s["fr_medium"] = self.medium_v.get()
        s["fr_layer2_on"] = bool(self.layer2_on_v.get())
        s["fr_layer2"] = self.layer2_v.get()
        s["fr_diamond_model"] = self.diamond_v.get()
        s["fr_medium_n"] = _f(self.medium_n_v, 1.2)
        # n diamond is NOT persisted: every load recomputes it from the
        # point's own pressure, so a stored number could only be stale.
        s["fr_n_layer2"] = _f(self.nl2_v, 1.0)
        s["fr_n_sample"] = _f(self.ns_v, 1.5)
        s["fr_d1_um"] = _f(self.d1_v, 0.0)
        s["fr_t_um"] = _f(self.t_v, 20.0)
        s["fr_d2_um"] = _f(self.d2_v, 0.0)
        s["fr_lock_total"] = bool(self.lock_v.get())
        s["fr_fine_step"] = bool(self.fine_v.get())
        s["fr_wl_min"] = _f(self.wlmin_v, 600.0)
        s["fr_wl_max"] = _f(self.wlmax_v, 800.0)
        s["fr_nt_min_um"] = _f(self.ntmin_v, 8.0)
        s["fr_nt_max_um"] = _f(self.ntmax_v, 300.0)
        s["fr_pvalue_max"] = _f(self.pmax_v, 1e-4)
        s["fr_agree_tol"] = _f(self.tol_v, 0.15)
        s["fr_halfwidth_um"] = _f(self.hw_v, 3.0)
        s["fr_band_floor"] = bool(self.bandfloor_v.get())
        s["fr_lp_bg_on"] = bool(self.lp_on_v["Background"].get())
        s["fr_lp_bg_um"] = _f(self.lp_v["Background"], 15.0)
        s["fr_lp_s_on"] = bool(self.lp_on_v["Sample"].get())
        s["fr_lp_s_um"] = _f(self.lp_v["Sample"], 15.0)
        for chan, pre in (("Background", "bg"), ("Sample", "s")):
            shape, roll = self._lp_edge(chan)
            s["fr_lp_%s_shape" % pre] = shape
            s["fr_lp_%s_roll" % pre] = roll
        s["fr_medium_name"] = (self.name_med_v.get() or "").strip()
        s["fr_sample_name"] = (self.name_samp_v.get() or "").strip()
        s["fr_layer2_name"] = (self.name_l2_v.get() or "").strip()
        s["fr_y_lo"] = str(self.ylo_v.get()).strip()
        s["fr_y_hi"] = str(self.yhi_v.get()).strip()
        s["fr_stem_cmap"] = self.cmap_v.get()
        s["fr_stem_skip_faint"] = bool(self.skipfaint_v.get())
        s["fr_notch_fine"] = bool(self.notchfine_v.get())
        s["fr_fit_mode"] = self.fitmode_v.get()

    def _x_upper(self, p):
        """Upper x limit shared by both panels, so a peak at a given n*t sits
        at the same screen x in Background and Sample.

        Reaches the 2nd Airy harmonic of the strong model modes and at least
        2x the PINNED fundamental -- his _forward_row_xupper (8824-8856) reads
        the fundamental the reader pinned, not the one the detector happened
        to name, so re-pinning a peak brings its harmonic into the frame.

        Capped at the Detection card's n*t max (300 um shipped), because that
        is where the search band ends: axis past it is axis no fringe can be
        found in.  And never past where the measured curve actually ends.
        """
        lines = (fringe_stack.stack_lines(p, kind="sample")
                 + fringe_stack.stack_lines(p, kind="medium"))
        mags = [ln["mag"] for ln in lines] or [1.0]
        mmax = max(mags)
        strong = [ln["nt"] for ln in lines if ln["mag"] > 0.1 * mmax] or [1.0]
        reach = 0.0
        nyq = None
        cap = _f(self.ntmax_v, 300.0)
        for chan in CHANNELS:
            c = self._compute(chan)
            if not c or "nt_um" not in c:
                continue
            cfg = c.get("cfg")
            if cfg is not None:
                cap = float(cfg.fringe_nt_max_nm) / 1000.0
            fund = self._fund_key(chan)
            if fund:
                reach = max(reach, 2.0 * float(fund) * 1.08)
            arr = c["nt_um"]
            if len(arr):
                nyq = float(arr[-1]) if nyq is None else min(nyq,
                                                             float(arr[-1]))
        if not (cap > 0):
            cap = 300.0
        upper = min(cap, max(80.0, 2.0 * max(strong) * 1.08, reach))
        step = upper / 8.0
        pw = 10 ** np.floor(np.log10(step)) if step > 0 else 1.0
        nice = next(s for s in (1, 2, 5, 10) if s * pw >= step)
        upper = float(np.ceil(upper / (nice * pw))) * (nice * pw)
        upper = min(upper, cap)          # the rounding may have crossed it
        if nyq and np.isfinite(nyq) and nyq > 0:
            upper = min(upper, nyq)
        return float(max(upper, 1.0))

    def _draw_panel(self, chan, rec, p, upper):
        ax = self._axes[chan]
        face, ink = self._page()
        c = self._compute(chan)
        kind = "sample" if chan == "Sample" else "medium"
        lines = fringe_stack.stack_lines(p, kind=kind)

        # measured curve, on the physical V axis
        ref = None
        if c and "V" in c:
            ax.plot(c["nt_um"], c["V"], color=ink, lw=1.0, alpha=0.9,
                    label="measured (%.0f-%.0f nm)" % (c["cfg"].fit_wl_min_nm,
                                                       c["cfg"].fit_wl_max_nm))
            sel = (np.isfinite(c["V"]) & (c["nt_um"] >= 3.0)
                   & (c["nt_um"] <= upper))
            if sel.any():
                ref = float(np.nanmax(c["V"][sel]))
        # tiered view: his crimson/blue post-fit residual FFTs ride on
        # the forward panels (they pair with the right-column tiers)
        if self.tiers_v.get():
            for _rx, _ry, _rc, _rn in self._fine_residual_ffts(chan):
                ax.plot(_rx, _ry, color=_rc, lw=0.8, alpha=0.85,
                        marker=".", ms=3, zorder=3, label=_rn)
        top = max([ln["mag"] for ln in lines] + ([ref] if ref else []) + [1e-9])

        # model stems + staggered boxed labels + m=2,3 Airy harmonics.
        # Four stagger levels, not three: with d1 == d2 the six sample lines
        # collapse onto neighbouring paths and three levels let two boxes
        # overlap (seen on the first screenshot gate).
        xtr = ax.get_xaxis_transform()
        y_levels = (0.92, 0.71, 0.50, 0.29)
        order = sorted(range(len(lines)), key=lambda i: lines[i]["nt"])
        level = {i: y_levels[k % len(y_levels)] for k, i in enumerate(order)}
        for i, ln in enumerate(lines):
            col, ls = self._stem_style(i)
            nt, h = ln["nt"], ln["mag"]
            ax.vlines(nt, 0.0, h, color=col, lw=2.2, ls=ls, zorder=0.5)
            ax.plot([nt], [h], "o", ms=5, color=col, zorder=0.6)
            for m in (2, 3):
                pos = m * nt
                if pos <= 1e-9 or pos > upper:
                    continue
                ax.vlines(pos, 0.0, h * (0.5 * h) ** (m - 1), color=col,
                          lw=1.3, ls="--", alpha=0.9, zorder=0.4)
            if not ln["formula"]:
                continue
            lx = min(max(nt, 0.02 * upper), 0.98 * upper)
            lab = ax.text(lx, level[i], "%s\n= %.1f um"
                          % (ln["formula"], nt),
                          transform=xtr, fontsize=7.5, color=col,
                          ha=("left" if nt < 0.5 * upper else "right"),
                          va="top", clip_on=False, zorder=7,
                          bbox=dict(boxstyle="round,pad=0.3", fc="none",
                                    ec=col, lw=1.0))
            # kept so _fit_labels can turn the ones that overrun around
            self._nt_labels.setdefault(chan, []).append(lab)

        # notch bands
        band = self.app._blendc(ink, face, 0.72)
        # centre +- half-width, on the MEASURED centre, so every band is
        # exactly the notch it draws (his _mark_fft_peaks, 13775-13779)
        _cents, _hws = self._active_centers_widths(chan)
        for cnm, hw in zip(_cents, _hws):
            cu = cnm / 1000.0
            half = max(float(hw), 0.05)
            ax.axvspan(cu - half, cu + half, color=band, alpha=0.35,
                       zorder=0.2, lw=0)

        # peak markers, provenance in the shape.  Their screen positions are
        # kept so hover can answer "is there a peak under the pointer?"
        # without a compute per mouse move (see _hover_peak).
        drawn_pts = []
        if c and "peaks" in c and len(c["peaks"]):
            ch = self._ch(chan)
            fund = self._fund_key(chan)
            act = set(self._active_centers(chan))
            for idx in c["peaks"]:
                x = float(c["nt_um"][idx])
                if x > upper:
                    continue
                kk = round(x, 2)
                y = float(c["V"][idx])
                drawn_pts.append((x, y))
                mk = ("^" if kk == fund else
                      "D" if kk in ch["user_centers"] else "o")
                filled = kk in act
                ax.plot([x], [y], marker=mk, ms=7, ls="none",
                        color=self.app._brand()["ac1"],
                        markerfacecolor=(self.app._brand()["ac1"] if filled
                                         else "none"),
                        markeredgewidth=1.2, zorder=6)
        self._peak_xy = getattr(self, "_peak_xy", {})
        self._peak_xy[chan] = drawn_pts

        # draggable low-pass line.  "drag" is spelled out on the label: the
        # line looked like a plotted limit, and nothing said it was a handle.
        lp = self._lp_cut_or_none(chan)
        if self.lp_on_v[chan].get() and lp is not None:
            lpc = self.app._brand()["ac3"]
            self._artists["lp"][chan] = ax.axvline(
                lp, color=lpc, lw=1.4, ls="--", alpha=0.95, zorder=5)
            self._artists.setdefault("lptext", {})[chan] = ax.text(
                lp, 0.055, " low-pass (drag)", transform=xtr, fontsize=7,
                color=lpc, ha="left", va="bottom")
            # The removed region, tinted from the cutoff to the right edge in
            # the line's own colour (his teal axvspan, 13788).  It is the one
            # cue that says what the low-pass takes out; without it the dashed
            # line reads as a plotted limit rather than an edge.  Cached beside
            # the line so a drag can slide it without a redraw.
            if lp < upper:
                self._artists.setdefault("lpshade", {})[chan] = ax.axvspan(
                    max(lp, 0.0), upper, color=lpc, alpha=0.06, lw=0,
                    zorder=0.1)

        # the hover ring: one per panel, parked invisible until the pointer
        # is within reach of a peak (see _hover_mark)
        hv, = ax.plot([], [], marker="o", ms=15, ls="none",
                      markerfacecolor="none",
                      markeredgecolor=self.app._brand()["ac3"],
                      markeredgewidth=2.0, zorder=9, visible=False,
                      clip_on=False)
        self._artists.setdefault("hover", {})[chan] = hv

        # role glyphs, their guide lines and their fitted-Gaussian overlays
        self._draw_roles(ax, chan, xtr, ink)
        self._draw_role_legend(ax, chan)

        ax.set_xlim(0, upper)
        # Auto is 0 up to 1.30x the tallest stem or measured peak; the
        # Y-axis dialog pins either bound on its own, and a range that does
        # not increase falls back to auto rather than drawing a flipped
        # panel (his 8930-8945).
        y_lo, y_hi = 0.0, top * 1.30
        lim = self._forward_y_lim()
        if lim is not None:
            if lim[0] is not None:
                y_lo = float(lim[0])
            if lim[1] is not None:
                y_hi = float(lim[1])
        if not (y_hi > y_lo):
            y_lo, y_hi = 0.0, top * 1.30
        ax.set_ylim(y_lo, y_hi)
        ax.xaxis.set_major_locator(MaxNLocator(nbins=8, steps=[1, 2, 5, 10]))
        ax.xaxis.set_minor_locator(AutoMinorLocator(4))
        ax.xaxis.set_major_formatter(FuncFormatter(lambda v, _p: "%g" % v))
        yf = ScalarFormatter(useMathText=True)
        yf.set_powerlimits((-2, 3))
        ax.yaxis.set_major_formatter(yf)
        off = ax.yaxis.get_offset_text()
        off.set_ha("right")
        off.set_va("bottom")
        off.set_position((1.0, 1.0))
        ax.set_xlabel(r"Optical path  $n{\cdot}t$  ($\mu$m)", fontsize=9,
                      color=ink)
        ax.set_ylabel(r"Fringe amplitude $V_m$  ($=2R^{m}$)", fontsize=9,
                      color=ink)
        ax.tick_params(labelsize=9, colors=ink)

        # removed-fraction twin axis
        tw = ax.twinx()
        self._twins[chan] = tw
        tw.set_ylim(0.0, 1.0)
        tw.set_ylabel("removed fraction", fontsize=8, color=ink)
        tw.tick_params(labelsize=8, colors=ink)
        tw.set_facecolor("none")
        for sp in tw.spines.values():
            sp.set_color(ink)
        # The mask itself, read along the axis (his dotted grey twin curve,
        # _draw_mask_profile 13711): what each notch and the low-pass edge
        # take out AT each n*t.  It comes from fringe_notch, the same
        # function the applied mask calls, so the picture and the cleaning
        # cannot drift.  Cached with its grid, because the live low-pass drag
        # re-reads it per frame.
        gx = np.linspace(0.0, max(float(upper), 1e-6), REMOVED_CURVE_PTS)
        curve, = tw.plot(gx, self._removed_curve(chan, gx),
                         color=self.app._muted_fg(), lw=0.9, ls=":",
                         alpha=0.85, zorder=0.3)
        curve._fr_grid = gx
        self._artists.setdefault("removed", {})[chan] = curve
        # No "N% removed" number here.  It was a variance ratio with no
        # counterpart in his window, and it read as a contradiction: past a
        # large peak it printed 0.0% while the cleaned curve was visibly off
        # raw, because the low-pass is still a smoother out to the Nyquist
        # n*t of 929 um in BOTH programs.  The curve above says what the mask
        # does at each n*t, which is the honest statement.

        # two-line header: schematic above, channel name below
        from matplotlib.transforms import offset_copy
        ch_tr = offset_copy(ax.transAxes, fig=self.fig, x=0, y=2,
                            units="points")
        sc_tr = offset_copy(ax.transAxes, fig=self.fig, x=0, y=14,
                            units="points")
        head = chan
        if c and c.get("nt"):
            head = "%s   n*t = %.2f um" % (chan, float(c["nt"]) / 1000.0)
        elif c is not None:
            # his wording, and the number that decided it (7950)
            head = "%s  no fringe detected (p=%.2g)" % (chan, _pv(c))
        head_t = ax.text(0.0, 1.0, head, transform=ch_tr, va="bottom",
                         ha="left", fontsize=HEAD_PT, fontweight="bold",
                         color=ink, clip_on=False)
        schem_t = ax.text(
            0.0, 1.0, self._schematic(p, kind), transform=sc_tr,
            va="bottom", ha="left", fontsize=SCHEM_PT,
            color=self.app._muted_fg(), clip_on=False)
        # the two travel together: _fit_labels fits both to this panel's
        # own column, and one registry is one thing for _view to swap
        schem_t._fr_head = head_t
        self._schem_labels[chan] = schem_t

    def _removed_curve(self, chan, x_um, lp_cut=None):
        """The removed fraction of this channel's mask over an n*t um grid.

        `lp_cut` evaluates the low-pass at a cutoff other than the stored
        one, which is what lets a live drag show the edge under the cursor
        before the value is committed (his lp_cut_override, 13570).
        """
        cents, hws = self._active_centers_widths(chan)
        shape, roll = self._lp_edge(chan)
        on = bool(self.lp_on_v[chan].get())
        cut = (self._lp_cut_or_none(chan) if lp_cut is None
               else float(lp_cut))
        try:
            return removed_profile_um(
                x_um, [c / 1000.0 for c in cents], hws,
                lowpass=bool(on and cut and cut > 0.0), lp_cutoff_um=cut,
                lp_rolloff_um=roll, lp_edge_shape=shape)
        except ValueError:                      # a zero half-width was typed
            return np.zeros_like(np.asarray(x_um, float))

    # ---- role glyphs, guides and fitted-Gaussian overlays -----------------
    def _mark_size_um(self, ax):
        """The drawn glyph size in micron of n*t, from the axes as they are.

        Measured off the transform rather than guessed, so the overlap test
        tracks zoom, window size and DPI the way his does.
        """
        upp = self._um_per_px(ax)
        if upp is None:
            return 0.0
        try:
            return float(ROLE_MS * ax.figure.dpi / 72.0) * upp
        except Exception:
            return 0.0

    def _mark_halfheight_frac(self, ax):
        """Half the tallest glyph's height in axes fraction: what the
        rectangle has to clear when it drops to the lower row."""
        try:
            h = float(ax.get_window_extent().height)
            if h <= 1.0:
                return 0.12
            px = ROLE_MS * ax.figure.dpi / 72.0
            return px * ROLE_HALFW["sampledia"] / h
        except Exception:
            return 0.12

    def _draw_role_legend(self, ax, chan):
        """His FFT-panel legend: the measured window, then one entry per
        ASSIGNED role labelled with the n*t that role feeds the solve.

        Observed on his: ['measured (600-800 nm)', '= 54.89 um'] on
        Background and a second '= 63.33 um' on Sample, one per glyph
        (defringe_dac 12856-12859 and 12970-12981).  Without it a glyph
        sitting off its model stem can only be eyeballed -- the panel title
        carries one number for the whole channel, not the glyph's own.  The
        swatch is a proxy built from the SAME marker the glyph was drawn
        with, so it cannot drift from the plot.
        """
        from matplotlib.lines import Line2D
        h, lab = ax.get_legend_handles_labels()
        tr = self._tr() or {"roles": {}}
        for role in ROLES:
            if ROLE_PANEL[role] != chan:
                continue
            ln = (self._artists.get("roles") or {}).get(role)
            rv = (tr.get("roles") or {}).get(role)
            if ln is None or not rv:
                continue
            mk, fill = ROLE_MARK[role]
            try:
                col = ln.get_color()
                face = ln.get_markerfacecolor()
            except AttributeError:
                continue
            h.append(Line2D([], [], marker=mk, ms=ROLE_MS * 0.8, ls="none",
                            color=col, fillstyle=fill, markerfacecolor=face,
                            markeredgewidth=1.4))
            lab.append("= %.2f um" % float(rv["nt_um"]))
        if not lab:
            return
        face, ink = self._page()
        try:
            leg = ax.legend(h, lab, fontsize=6, loc="upper right",
                            framealpha=0.85, labelspacing=0.7)
        except Exception:
            return
        # the legend has to be the TOP layer: the boxed formula labels, the
        # glyphs and their guides all sit above matplotlib's default 5
        leg.set_zorder(100)
        for t in leg.get_texts():
            t.set_color(ink)
        try:
            leg.get_frame().set_facecolor(face)
            leg.get_frame().set_edgecolor(ink)
        except AttributeError:
            pass

    def _lift_on_page(self, col, floor=0.42):
        """A fixed colour raised until it reads on THIS page (rule 65).

        His four reference-line colours run down to #550000, which is a
        black line on a dark ground.  Rather than carry a second hard-coded
        set, the colour is mixed toward white until its luminance clears
        `floor`, and only on a dark page -- so one table serves the pale
        page, the dark one, and (through the caller) High Contrast.
        """
        from matplotlib.colors import to_hex, to_rgb
        face = self._page()[0]
        try:
            r, g, b = to_rgb(col)
            fr, fg, fb = to_rgb(face)
        except (ValueError, TypeError):
            return col
        if 0.299 * fr + 0.587 * fg + 0.114 * fb >= 0.5:
            return col                       # pale page: his colours as they are
        lum = 0.299 * r + 0.587 * g + 0.114 * b
        if lum >= floor:
            return col
        t = min(max((floor - lum) / max(floor, 1e-6), 0.0), 1.0)
        return to_hex((r + (1.0 - r) * t, g + (1.0 - g) * t,
                       b + (1.0 - b) * t))

    def _draw_ref_lines(self, ax):
        """His four wavelength reference lines, nm printed at the top.

        580 / 640 / 766 / 905 nm (defringe_dac 7813-7818), on the
        wavenumber axis the panel is drawn on.  They are the eye's ruler
        against the fringe spacing, and the top label is what says which
        line is which.
        """
        xtr = ax.get_xaxis_transform()
        ink = self._page()[1]
        for wl_nm, col in REF_WL_NM:
            c = ink if self._hc() else self._lift_on_page(col)
            x = 1e7 / float(wl_nm)
            ax.axvline(x, color=c, lw=1.0, ls="--", zorder=1, alpha=0.9)
            ax.text(x + 40.0, 0.995, str(wl_nm), transform=xtr,
                    fontsize=5.5, color=c, ha="left", va="top",
                    clip_on=True)

    def _residual_tiers(self, c, wl, raw):
        """His two Row-0 residual tiers: [(values, nt_um, alpha), ...].

        Tier one is raw minus the cosine of the TALLEST FFT peak, blanked
        outside the fit window; tier two is the same for the FULL-range
        FFT's own peak over the full window, drawn faint (defringe_dac
        7580-7592).  Ours drew ONE tier from the refined notch centre,
        which is neither of his numbers: on Y03 Sample his two read 63.6 and
        8.2 um where ours read 32.3.
        """
        fi = (c or {}).get("fft_info") or {}
        cfg = (c or {}).get("cfg")
        wl = np.asarray(wl, float)
        raw = np.asarray(raw, float)
        wn = 1.0 / np.maximum(wl, 1e-9)          # nm^-1, his grid
        srt = np.argsort(wn)
        out = []

        def _tier(src, lo, hi, alpha):
            src = src or {}
            nt, amp = src.get("nt_est"), src.get("peak_amp")
            wn_u = src.get("wn_u")
            if not nt or amp is None or wn_u is None:
                return
            wn_u = np.asarray(wn_u, float)
            if wn_u.size < 2:
                return
            # his amplitude: the normalised peak height times the mean raw
            # over the window that peak was measured in
            raw_u = np.interp(wn_u, wn[srt], raw[srt])
            a = float(amp) * float(np.nanmean(raw_u))
            phi = float(src.get("peak_phase") or 0.0)
            sine = a * np.cos(4.0 * np.pi * float(nt) / np.maximum(wl, 1e-9)
                              + phi - 4.0 * np.pi * float(nt) * wn_u[0])
            keep = np.ones(wl.shape, dtype=bool)
            if lo is not None:
                keep &= wn >= lo
            if hi is not None:
                keep &= wn <= hi
            y = raw - sine
            y[~keep] = np.nan
            out.append((y, float(nt) / 1000.0, alpha))

        lo_n = hi_n = None
        if cfg is not None:
            lo_n = 1.0 / max(float(cfg.fit_wl_max_nm), 1e-9)
            hi_n = 1.0 / max(float(cfg.fit_wl_min_nm), 1e-9)
        _tier(fi, lo_n, hi_n, 1.0)
        _tier(fi.get("fft_full"),
              (cfg.full_wn_lo if cfg is not None else None),
              (cfg.full_wn_cap if cfg is not None else None), 0.4)
        return out

    def _draw_roles(self, ax, chan, xtr, ink):
        """Every role this panel carries: the fitted Gaussian under it, its
        vertical guide, the glyph itself, and the joint Sample envelope.

        Two states, two fills (his yellow auto / orange manual): a glyph the
        workbench fitted, and one you dragged.  A fitted curve is a
        detection artifact, so it is drawn only while its role is auto and
        still -- a drag drops it.  When the two Sample glyphs collide the
        rectangle drops a row, which is what makes a coincident pair
        separable by mouse (see _grab_role).
        """
        tr = self._tr()
        self._role_y = getattr(self, "_role_y", {})
        self._artists.setdefault("guides", {})
        if tr is None:
            return
        roles = [r for r in ROLES if ROLE_PANEL[r] == chan]
        auto_c, man_c = self._role_colors()
        drag_role = (self._drag or {}).get("role")

        def _dotted(gx, gy, z):
            # an ink underlay with the accent dotted over it: the dark line
            # fills the gaps, so the curve reads on a pale page and a dark
            # one alike
            ax.plot(gx, gy, color=ink, ls="-", lw=1.6, zorder=z, alpha=0.8,
                    clip_on=True)
            ax.plot(gx, gy, color=auto_c, ls=":", lw=1.3, zorder=z + 0.1,
                    clip_on=True, dash_capstyle="round")

        # the collide-and-stagger test, in drawn glyph widths
        overlap = False
        if chan == "Sample":
            rs, rd = tr["roles"].get("sample"), tr["roles"].get("sampledia")
            if rs and rd:
                span = (ROLE_HALFW["sample"] + ROLE_HALFW["sampledia"]) \
                    * self._mark_size_um(ax)
                overlap = abs(float(rs["nt_um"]) - float(rd["nt_um"])) < span
        h_frac = self._mark_halfheight_frac(ax)
        y_low = max(ROLE_Y_LOW_MIN,
                    ROLE_Y["sample"] - max(1.55 * h_frac, 0.08))
        for role in roles:
            rv = tr["roles"].get(role)
            if not rv:
                self._role_y.pop(role, None)
                continue
            x = float(rv["nt_um"])
            y = y_low if (overlap and role == "sample") else ROLE_Y[role]
            self._role_y[role] = y
            dragging = (drag_role == role)
            is_auto = bool(rv.get("auto")) and not dragging
            face = auto_c if is_auto else man_c
            g = (tr.get("gauss") or {}).get(role)
            if is_auto and g and g.get("panel") == chan and g.get("sig"):
                gx = np.linspace(g["x0"], g["x1"], 240)
                _dotted(gx, g["A"] * np.exp(-0.5 * ((gx - g["mu"])
                                                    / g["sig"]) ** 2)
                        + g["c"], 3.8)
            vl_bg = ax.axvline(x, color=ink, ls="-", lw=1.4, alpha=0.55,
                               zorder=4.0)
            vl_fg = ax.axvline(x, color=face, ls=("-" if is_auto else "--"),
                               lw=1.2, zorder=4.1)
            self._artists["guides"][role] = (vl_bg, vl_fg)
            mk, fill = ROLE_MARK[role]
            ln, = ax.plot([x], [y], marker=mk, ms=ROLE_MS, ls="none",
                          transform=xtr, color=face, fillstyle=fill,
                          markerfacecolor=face, markeredgewidth=1.4,
                          clip_on=False, zorder=8)
            self._artists["roles"][role] = ln
        # the joint envelope: stored once by the shared fit, drawn once, and
        # only while BOTH Sample roles are the workbench's own
        gp = (tr.get("gauss") or {}).get("_sample_pair")
        both_auto = all(bool((tr["roles"].get(r) or {}).get("auto"))
                        for r in ("sample", "sampledia"))
        pair_drag = drag_role in ("sample", "sampledia")
        if (chan == "Sample" and gp and gp.get("sig") and both_auto
                and not pair_drag):
            gx = np.linspace(gp["x0"], gp["x1"], 240)
            env = (gp["A1"] * np.exp(-0.5 * ((gx - gp["mu1"])
                                             / gp["sig"]) ** 2)
                   + gp["A2"] * np.exp(-0.5 * ((gx - gp["mu2"])
                                               / gp["sig"]) ** 2) + gp["c"])
            _dotted(gx, env, 3.6)    # under the components, so both show

    # ---- the measured column (his Row-0 panels) ---------------------------
    def _dark_of(self, rec, raw_like):
        """This trace's dark counts, or None when they will not line up."""
        d = (rec or {}).get("dark_c")
        if d is None:
            return None
        try:
            d = np.asarray(d, float)
        except (TypeError, ValueError):
            return None
        return d if d.shape == np.asarray(raw_like).shape else None

    def _draw_fit_window(self, ax, c):
        """The pale band over the fit window, and his wavelength markers.

        His _row_top_axis shades 600-800 nm on every measured panel and his
        _draw_row0 rules four dashed wavelength lines across it (7812-7818).
        Both say where the numbers on this panel come from: the fit reads the
        window, and nothing outside it moves n or t.  Drawn on the wavenumber
        axis, since that is the axis the panel plots.
        """
        cfg = (c or {}).get("cfg")
        lo = float(getattr(cfg, "fit_wl_min_nm", 600.0) or 600.0)
        hi = float(getattr(cfg, "fit_wl_max_nm", 800.0) or 800.0)
        if hi > lo > 0:
            face, ink = self._page()
            ax.axvspan(1e7 / hi, 1e7 / lo,
                       color=self.app._blendc(self.app._brand()["ac3"], face,
                                              0.86),
                       zorder=0, lw=0)
            xtr = ax.get_xaxis_transform()
            for wl_nm in (lo, hi):
                ax.axvline(1e7 / wl_nm, color=self.app._muted_fg(), lw=0.8,
                           ls="--", zorder=1)
                ax.text(1e7 / wl_nm, 0.995, " %g" % wl_nm, transform=xtr,
                        fontsize=5.5, color=self.app._muted_fg(), ha="left",
                        va="top", clip_on=True)

    def _draw_dark_overlays(self, ax, wn_cm, rec, c, chan):
        """His dark and D(raw, dark) overlays on a measured panel.

        Display only: raw_minus_dark rides in the fit dict and is never let
        near the FFT, the mask or the detection (his 7457-7467).  It is here
        because a reader comparing this window with his looks for it.

        D(raw, dark) is the SAMPLE panel's, his (7560): the dark-subtracted
        curve is what the absorbance divides, and the Background's copy of it
        only crowds a panel that already carries raw and dark.
        """
        dark = self._dark_of(rec, wn_cm)
        if dark is not None:
            ax.plot(wn_cm, dark, color="darkblue", lw=0.4, label="dark",
                    zorder=3)
        rmd = ((c or {}).get("fit") or {}).get("raw_minus_dark")
        if rmd is not None and chan == "Sample":
            ax.plot(wn_cm, np.asarray(rmd, float), color="teal", lw=0.4,
                    alpha=0.7, label=r"$\Delta$(raw, dark)", zorder=3.5)

    def _draw_baseline(self, ax, wn_cm, raw, rec, c, ink, chan):
        """His fringe-free measured panel (_draw_signals, 7444-7470): dark,
        the local noise floor under it, raw, and D(raw, dark).  No cleaned
        curve, because on a channel with no fringe nothing was cleaned.

        The noise floor and D(raw, dark) are the SAMPLE panel's alone, his
        (7554 and 7560); the Background keeps raw and dark.
        """
        dark = self._dark_of(rec, raw)
        if dark is not None:
            ax.plot(wn_cm, dark, color="darkblue", lw=0.4, label="dark",
                    zorder=4)
            if chan == "Sample":
                try:
                    nf = fringe_optics.local_noise_floor(dark)
                    ax.fill_between(wn_cm, 0.0, nf, color="darkblue",
                                    alpha=0.2, label="noise floor", zorder=3)
                except (ValueError, TypeError):
                    pass
        ax.plot(wn_cm, raw, color=ink, lw=0.5, label="raw", zorder=5)
        rmd = ((c or {}).get("fit") or {}).get("raw_minus_dark")
        if rmd is not None and chan == "Sample":
            ax.plot(wn_cm, np.asarray(rmd, float), color="teal", lw=0.4,
                    alpha=0.7, label=r"$\Delta$(raw, dark)", zorder=5)

    def _draw_measured(self, chan, rec):
        """One measured-spectrum panel: the raw transmitted intensity with
        the FFT-filtered clean curve over it, at true intensity -- his
        Row-0 flat view.  Show tiered stacks the diagnostic tiers
        instead: the cosine-fit residual, the clean curve, each fitted
        window's defringed curve, and raw on top, offset apart.

        With NO fringe detected there is no cleaned curve to draw, here or
        anywhere else, so the panel falls back to his baseline view (his
        _draw_signals, 7444-7470): dark, the noise floor under it, raw, and
        D(raw, dark).  The title says so and gives the p that decided it.
        """
        ax = self._maxes[chan]
        face, ink = self._page()
        muted = self.app._muted_fg()
        c = self._compute(chan)
        if not c:
            ax.text(0.5, 0.5, "no measured data", transform=ax.transAxes,
                    ha="center", va="center", color=muted, fontsize=9)
            ax.set_title(chan, fontsize=9, color=ink)
            ax.tick_params(labelleft=False, labelbottom=False, colors=ink)
            return
        wl = np.asarray(rec["wl"], float)
        raw = np.asarray(rec[CHAN_KEY[chan]], float)
        wn_cm = 1e7 / np.maximum(wl, 1e-9)
        fi = c.get("fft_info") or {}
        ic = fi.get("I_notch_1x")
        if ic is not None:
            ic = np.asarray(ic, float)
            if not np.any(np.isfinite(ic)):
                ic = None
        no_fringe = not c.get("nt")
        show_clean = (ic is not None and self._show_clean(chan))
        fin = np.isfinite(raw)
        ptp = float(np.ptp(raw[fin])) if fin.any() else 1.0
        ptp = ptp or 1.0
        inner = 0.10 * ptp
        outer = 0.35 * ptp
        self._draw_fit_window(ax, c)
        self._draw_ref_lines(ax)
        if no_fringe:
            # his fringe-free fallback: no filtered curve exists, so the
            # panel shows what the channel is made of instead
            self._draw_baseline(ax, wn_cm, raw, rec, c, ink, chan)
        elif not self.tiers_v.get():
            # flat view: raw then the clean curve ON TOP, true intensity
            ax.plot(wn_cm, raw, color=ink, lw=0.5, label="raw", zorder=4)
            self._draw_dark_overlays(ax, wn_cm, rec, c, chan)
            if show_clean:
                ax.plot(wn_cm, ic, color="#FF2020", lw=0.6,
                        label="FFT filtered", zorder=5)
        else:
            y = 0.0
            # his two residual tiers, narrow then full (see _residual_tiers)
            for _res, _nt_um, _alpha in self._residual_tiers(c, wl, raw):
                ax.plot(wn_cm, _res + y, color="tab:blue", lw=0.4,
                        alpha=_alpha,
                        label="$\\Delta$(raw, cosine fit)  "
                              "n*t=%.1f um" % _nt_um)
                y += inner
            if show_clean:
                ax.plot(wn_cm, ic + y, color="#FF2020", lw=0.5,
                        label="FFT filtered")
                y += inner
            fit = self._fits.get((self._dkey(), chan)) or {}
            cn = (fit.get("models") or {}).get("constant_n") or {}
            drew_tier = False
            for win, alpha in (("fine", 1.0), ("narrow", 0.55),
                               ("wide", 0.4), ("full", 0.25)):
                d = cn.get(win)
                if not d or d.get("n_mean") is None:
                    continue
                # the window's defringed curve: divide the fitted fringe
                # factor 1 + V cos(4 pi nt / lambda + phi0) out of raw.
                # First-order in his airy_factor -- noted in the guide.
                V = fringe_optics.fresnel_V(float(d["n_mean"]), wl)
                phi = (4.0 * np.pi * float(d["nt_um"]) * 1000.0 / wl
                       + float(d.get("phi0") or 0.0))
                # 0.02, his floor (drift #12): a 0.1 floor clipped the
                # denominator wherever the fitted visibility passed about
                # 0.9, which flattened the deepest troughs of this overlay
                # against his batch pipeline's own output
                den = np.clip(1.0 + V * np.cos(phi), 0.02, None)
                y += outer if not drew_tier else inner
                drew_tier = True
                ax.plot(wn_cm, raw / den + y, color="darkred", lw=0.4,
                        alpha=alpha, label="ConstantN %s  n*t=%.1f um"
                        % (win, float(d["nt_um"])))
            y += outer
            ax.plot(wn_cm, raw + y, color=ink, lw=0.3, label="raw")
        # ---- axis furniture: his Row-0 grammar --------------------------
        if fin.any():
            ax.set_xlim(float(np.nanmin(wn_cm[fin])),
                        float(np.nanmax(wn_cm[fin])))
        ax.tick_params(labelsize=7, colors=ink)
        ax.set_xlabel("Wavenumber (cm$^{-1}$)", fontsize=8, color=ink)
        ax.xaxis.set_major_locator(MaxNLocator(nbins=6))
        ax.xaxis.set_major_formatter(FuncFormatter(lambda v, _p:
                                                   "%g" % v))
        try:
            sec = ax.secondary_xaxis(
                "top", functions=(lambda v: 1e7 / np.maximum(v, 1e-9),
                                  lambda v: 1e7 / np.maximum(v, 1e-9)))
            sec.set_xlabel("Wavelength (nm)", fontsize=7, color=ink)
            sec.tick_params(labelsize=6, colors=ink)
            for sp in sec.spines.values():
                sp.set_color(ink)
            self._twins["sec_" + chan] = sec
        except Exception:
            pass
        # mantissa ticks + a x10^n header, his hand-rolled offset text
        ylo, yhi = ax.get_ylim()
        ymax = max(abs(ylo), abs(yhi))
        exp = int(np.floor(np.log10(ymax))) if ymax > 0 else 0
        sc = 10.0 ** exp
        ax.yaxis.set_major_formatter(
            FuncFormatter(lambda v, _p, _s=sc: "%g" % (v / _s)))
        if exp:
            ax.text(0.005, 0.97, "$\\times 10^{%d}$" % exp,
                    transform=ax.transAxes, ha="left", va="top",
                    fontsize=7, color=ink, clip_on=False)
        title = chan
        if no_fringe:
            title = "%s  no fringe detected (p=%.2g)" % (chan, _pv(c))
        else:
            n_fit = self._fitted_n(chan)
            if n_fit is not None:
                title = "%s   fit n = %.4f" % (chan, n_fit)
        ax.set_title(title, fontsize=9, color=ink, pad=16)
        try:
            lg = ax.legend(fontsize=6, loc="upper right", framealpha=0.7)
            if lg is not None:
                lg.set_zorder(100)
                lg.get_frame().set_facecolor(face)
                lg.get_frame().set_edgecolor(muted)
                for t in lg.get_texts():
                    t.set_color(ink)
        except Exception:
            pass

    # ---- readouts ---------------------------------------------------------
    def _refresh_reports(self):
        rep = getattr(self, "_rep", None) or {}
        if rep:
            c = self._compute("Sample") or self._compute("Background")
            try:
                if not c:
                    for lab in rep.values():
                        lab.configure(text="–")
                else:
                    nt = c.get("nt")
                    rep["nt"].configure(
                        text=("%.3f um" % (float(nt) / 1000.0))
                        if nt else "no fringe")
                    pv = c.get("pv")
                    rep["p"].configure(
                        text=("%.2g" % pv) if pv is not None
                        else "–")
                    corr = c.get("corr") or []
                    rep["corr"].configure(
                        text=(" + ".join(corr) if corr
                              else "not corroborated"))
            except tk.TclError:
                self._rep = {}
        self._fill_pred_lines()

    def _refresh_roles(self):
        # R7: the role paths live on the chart itself (glyphs and the
        # panel legend), as in his GUI -- only the ordering check stays
        self._check_ordering()

    def _check_ordering(self):
        """A dropped glyph lands where it was dropped; if that ordering cannot
        be inverted the workbench says so rather than silently clamping."""
        tr = self._tr()
        if tr is None:
            return
        r = tr["roles"]
        if not (r.get("sample") and r.get("sampledia")):
            return
        A, C = r["sample"]["nt_um"], r["sampledia"]["nt_um"]
        if C < A:
            self._status("sample-diamond sits left of the sample: the "
                         "layer-2 thickness would be negative. Solve will "
                         "floor it.", warn=True, log=False)

    # ---- the opening guess: role glyphs seeded onto the peaks -------------
    def _pred_paths(self, p):
        """Where the stack model expects the three roles, in n*t micron.

        The very three paths solve_paths inverts, read straight off the
        forward lines the panels already draw as stems: A = n_s t (the '23'
        pair), C = n_layer2 (d1+d2) + n_s t (the whole-cell '14' pair) and
        iii = n_medium L (the bare etalon).  An empty dict means the model
        could not be built, and the seed falls back on raw peak strength.
        """
        try:
            sample = fringe_stack.stack_lines(p, kind="sample")
            medium = fringe_stack.stack_lines(p, kind="medium")
        except (KeyError, ValueError, ZeroDivisionError, FloatingPointError):
            return {}
        out = {}
        for ln in sample:
            if "23" in ln["ids"]:
                out["sample"] = float(ln["nt"])
            if "14" in ln["ids"]:
                out["sampledia"] = float(ln["nt"])
        if medium:
            out["mediumdia"] = float(medium[0]["nt"])
        return {k: v for k, v in out.items() if np.isfinite(v) and v > 0.0}

    def _seed_cands(self, chan, upper):
        """Peaks a seed may land on: strongest first, on screen, positive."""
        c = self._compute(chan)
        if not c or "peaks" not in c or not len(c["peaks"]):
            return []
        out = []
        for idx in c["peaks"]:
            x = float(c["nt_um"][idx])
            if not np.isfinite(x) or x <= 0.0 or x > upper:
                continue
            out.append(x)
            if len(out) >= SEED_MAX_CAND:
                break
        return out

    @staticmethod
    def _seed_tol(pred):
        return max(SEED_TOL_UM, SEED_TOL_FRAC * float(pred))

    def _seed_near(self, cands, pred):
        """The peak closest to `pred`, or None if none is close enough."""
        best = None
        tol = self._seed_tol(pred)
        for x in cands:
            d = abs(x - pred)
            if d <= tol and (best is None or d < best[0]):
                best = (d, x)
        return best[1] if best else None

    def _seed_pair(self, cands, pa, pc):
        """The best ORDERED pair of peaks for the two Sample roles.

        Scored jointly, not one role at a time: when the Stack's t is
        over-guessed the peak nearest A is the whole-cell bump, and taking
        each role's nearest peak on its own then puts the rectangle on the
        wrong hump.  Minimising the total miss over the pairs that keep C
        above A does not, and it cannot hand the solve an inverted ordering.
        """
        best = None
        for xa in cands:
            for xc in cands:
                if xc <= xa:
                    continue
                if (abs(xa - pa) > self._seed_tol(pa)
                        or abs(xc - pc) > self._seed_tol(pc)):
                    continue
                score = abs(xa - pa) + abs(xc - pc)
                if best is None or score < best[0]:
                    best = (score, xa, xc)
        return (best[1], best[2]) if best else None

    def _tallest_peak_um(self, chan):
        """The single highest-amplitude FFT peak on one panel, in n*t um.

        His `_tallest_peak_um` (12283): peaks_sorted is amplitude-descending,
        so the first entry is the tallest.  None when the channel has no
        peaks to stand on.
        """
        c = self._compute(chan)
        if not c or "peaks" not in c or not len(c["peaks"]):
            return None
        try:
            x = float(c["nt_um"][int(c["peaks"][0])])
        except (KeyError, IndexError, TypeError, ValueError):
            return None
        return x if np.isfinite(x) and x > 0.0 else None

    def _has_seed(self, label=None):
        """True when this point has inputs to open on.

        His `_seed` (13081): the point's own committed inputs, the state it
        was last left in, or the nearest preceding recorded point's.  With
        none of the three the load is a COLD start, and the glyphs go on the
        tallest peak of each panel instead of on the stack model's guess.
        """
        dk = self._dkey(label)
        if dk is None:
            return False
        if dk in self._live_inputs or dk in self._inputs:
            return True
        return self._seed_from_preceding(dk)[0] is not None

    def _align_to_tallest(self):
        """His cold-start align-and-lock (_align_glyphs_to_tallest_and_lock,
        12620-12660).

        Both Sample roles go on the Sample panel's tallest peak -- they start
        coincident, and dragging one apart separates them -- and the medium
        etalon on the Background panel's tallest.  The solve that follows is
        written straight into n sample / t / d2, so the model stems stand on
        the glyphs from the very first frame instead of on the shipped
        t = 20.  Returns True when the inputs were written, False when the
        glyphs went down but the triple would not solve, and None when there
        was nothing to align to at all -- which hands the trace back to the
        stack model's own guess.

        The write is guarded: a redraw of its own here would draw the panels
        twice and flash the defaults in between.
        """
        tr = self._tr()
        if tr is None:
            return None
        s_top = self._tallest_peak_um("Sample")
        m_top = self._tallest_peak_um("Background")
        if s_top is None and m_top is None:
            return None
        if s_top is not None:
            for role in ("sample", "sampledia"):
                tr["roles"][role] = {"nt_um": float(s_top), "auto": True,
                                     "seed": True}
                tr["gauss"][role] = None
            tr["gauss"]["_sample_pair"] = None
        if m_top is not None:
            tr["roles"]["mediumdia"] = {"nt_um": float(m_top), "auto": True,
                                        "seed": True}
            tr["gauss"]["mediumdia"] = None
        tr["seeded"] = True
        placed = sum(1 for r in ROLES if tr["roles"].get(r))
        sol = self._solve(quiet=True)
        if sol is None or sol.get("error"):
            # No peak on one panel, or an unsolvable triple: the glyphs that
            # were found stay, and the inputs are left alone.  His helper
            # restores its own defaults here; ours are one series-wide set of
            # boxes, so clearing them would take the reader's numbers with
            # them.
            self._seed_status(
                "part", "parked %d of the 3 role glyphs on the tallest peak "
                        "of each panel. Right-click a peak to place the "
                        "rest." % placed)
            return False
        self._write_solve(sol)
        self._seed_status(
            "all", "glyphs placed on the tallest peak of each panel and the "
                   "solve written into the boxes. Drag them, or right-click "
                   "a peak, to move them.")
        return True

    def _write_solve(self, sol):
        """Write one solve into n sample / t / d2 (and the total while
        locked).  Guarded, and quiet: a redraw of its own here would draw
        the panels twice and flash the shipped numbers in between.
        """
        if not sol or sol.get("error"):
            return False
        was = self._suspend
        self._suspend = True
        try:
            self.ns_v.set("%.4f" % sol["n_s"])
            self.t_v.set("%.3f" % sol["t_s"])
            d1 = max(_f(self.d1_v, 0.0), 0.0)
            self.d2_v.set("%.3f" % max(float(sol["t_layer2"]) - d1, 0.0))
            if self.lock_v.get():
                self.total_v.set("%.3f" % sol["L"])
        except tk.TclError:
            pass
        finally:
            self._suspend = was
        self._thick_snapshot()
        return True

    def _seed_roles(self, p, upper, allow_align=True):
        """Park the role glyphs on the workbench's best opening guess.

        Matthew's original kept the three glyphs on screen at all times, and
        a fresh trace with nothing to drag is a workbench with no way in.
        This runs once per trace and only while every role is still empty, so
        a glyph you placed -- or one that arrived with a saved session -- is
        never overwritten.  Seeded glyphs are ordinary glyphs: drag them, fit
        them, clear them.

        A COLD point -- no committed inputs, no live state, nothing to seed
        from -- takes his align-and-lock instead: the tallest peak of each
        panel, solved and written back.  A point that has inputs keeps the
        stack model's prediction, which is what his autosnap does on that
        path.  `allow_align` False is the re-detect action, which is the
        model's own workflow and must not jump to the tallest peak.

        Returns True when the inputs were rewritten, so the caller can
        rebuild the stack model before it draws the panels.
        """
        tr = self._tr()
        if tr is None or tr.get("seeded"):
            return False
        if any(tr["roles"].get(r) for r in ROLES):
            tr["seeded"] = True            # yours, or a session's: hands off
            return False
        if allow_align and not self._has_seed():
            aligned = self._align_to_tallest()
            if aligned is not None:
                # His _update re-fits the AUTO glyphs on every redraw, so a
                # freshly loaded trace already shows its Gaussian-refined
                # centres (63.333 / 54.893, solved t_s 45.744) rather than
                # the raw peak bins the align landed on (63.612 / 55.210,
                # t_s 46.009).  Ours re-fits on a committed edit, which is
                # the documented cadence deviation; ONE snap here puts the
                # first frame on his numbers, and the solve is written back
                # from the refined positions so the boxes agree with them.
                if aligned and self._autosnap_roles():
                    self._write_solve(self._solve(quiet=True))
                return bool(aligned)
        pred = self._pred_paths(p)
        placed = {}
        s_cand = self._seed_cands("Sample", upper)
        if s_cand:
            pair = None
            if len(s_cand) > 1 and "sample" in pred and "sampledia" in pred:
                pair = self._seed_pair(s_cand, pred["sample"],
                                       pred["sampledia"])
            if pair is None:               # no trustworthy prediction: the
                pair = sorted(s_cand[:2])  # strongest peaks, in n*t order
            placed["sample"] = pair[0]
            if len(pair) > 1:
                placed["sampledia"] = pair[1]
        b_cand = self._seed_cands("Background", upper)
        if b_cand:
            x = (self._seed_near(b_cand, pred["mediumdia"])
                 if "mediumdia" in pred else None)
            placed["mediumdia"] = b_cand[0] if x is None else x
        if not placed:
            self._seed_status(
                "none", "the detector missed this trace, so the role glyphs "
                        "stay parked. Loosen Detection, or right-click a "
                        "peak to place a role by hand.")
            return False
        for role, x in placed.items():
            # "seed" marks a glyph nobody has touched yet: it draws and drags
            # exactly like a placed one, but it is not unsaved work (see
            # _dirty_items), so a seeded trace never triggers a leave guard.
            tr["roles"][role] = {"nt_um": float(x), "auto": True, "seed": True}
            tr["gauss"][role] = None
        tr["gauss"]["_sample_pair"] = None
        tr["seeded"] = True
        missing = [ROLE_DISP[r] for r in ROLES if r not in placed]
        if missing:
            self._seed_status(
                "part", "parked %d of the 3 role glyphs on our best guess; "
                "%s still needs a home. Right-click a peak to assign it."
                % (len(placed), " and ".join(missing)))
        else:
            self._seed_status(
                "all", "role glyphs parked on our best guess from your stack. "
                "Drag them, or right-click a peak, to move them.")
        return False

    def _seed_status(self, kind, msg):
        """Say it once per trace: a redraw must not re-announce the seed."""
        dk = self._dkey()
        if self._seed_said.get(dk) == kind:
            return
        self._seed_said[dk] = kind
        self._status(msg, log=False)

    def _refresh_state_indicators(self):
        """Two-level model: what is in memory vs what was committed."""
        items = self._dirty_items()
        if self._label is None:
            self._state_lbl.configure(text="")
            self._show_if_text(self._state_lbl, "")
            return
        if self._dkey() not in self._disk:
            mark, txt = IND_NONE, "this trace is waiting for its first record"
        elif items:
            mark, txt = IND_DIRTY, "%d change(s) in memory" % len(items)
        else:
            mark, txt = IND_SAVED, "saved, identical to disk"
        self._state_lbl.configure(text="%s  %s" % (mark, txt))
        self._show_if_text(self._state_lbl, txt)
        n = len(self._series)
        try:
            self._series_lbl.configure(
                text="Series: %s   %s"
                     % (self._series_label() or "–",
                        ("no points plotted" if not n else
                         "%d point%s plotted"
                         % (n, "" if n == 1 else "s"))))
        except (AttributeError, tk.TclError):
            pass
        try:
            self.csv_dir_v.set(self._series_folder() or "–")
        except (AttributeError, tk.TclError):
            pass
        self._sync_action_marks()
        self._refresh_series_disk()
        self._relabel_pressure_cb()

    # =======================================================================
    # interactions
    # =======================================================================
    def _panel_of(self, ax):
        for chan, a in self._axes.items():
            if a is ax or self._twins.get(chan) is ax:
                return chan
        return None

    def _toolbar_busy(self):
        tb = getattr(self.canvas, "toolbar", None)
        return bool(tb is not None and getattr(tb, "mode", ""))

    # ---- hit radii, in screen pixels --------------------------------------
    def _um_per_px(self, ax):
        """How many micron of n*t one screen pixel is worth on `ax`."""
        try:
            x0, x1 = ax.get_xlim()
            w = float(ax.get_window_extent().width)
        except Exception:
            return None
        if not (w > 1.0) or not np.isfinite(x1 - x0):
            return None
        return abs(float(x1 - x0)) / w

    def _tol(self, ax, px, floor_um):
        """`px` screen pixels in micron: never below `floor_um`, never more
        than `frac` of the visible span.

        The cap earns its place on a narrow canvas.  With the guide pane
        open the axes can be 200 px wide, where 15 px is 7.5 um of n*t --
        wide enough that the low-pass line would claim a peak six micron
        away and every click near it turned into a drag.  Capping on the
        span keeps the reach proportionate at any size.
        """
        upp = self._um_per_px(ax)
        if upp is None:
            return floor_um
        try:
            x0, x1 = ax.get_xlim()
            span = abs(float(x1 - x0))
        except Exception:
            span = 0.0
        tol = max(floor_um, px * upp)
        cap = TOL_CAP_FRAC * span
        if cap > floor_um:
            tol = min(tol, cap)
        return tol

    def _ax_of(self, chan):
        return self._axes.get(chan)

    def _on_press(self, event):
        if event.inaxes is None or event.xdata is None or self._toolbar_busy():
            return
        chan = self._panel_of(event.inaxes)
        if chan is None:
            return
        if event.button == 3:
            self._rclick(chan, float(event.xdata), event)
            return
        if event.button != 1:
            return
        # a draggable handle first, then the notch toggle
        kind, role = self._grab_at(chan, float(event.xdata), event)
        if kind == "role":
            self._drag = {"kind": "role", "role": role, "chan": chan,
                          "moved": False}
            self._hint("dragging %s. the drop point places it and solves; "
                       "Fit peaks re-detects from the model."
                       % ROLE_DISP[role].lower())
            return
        if kind == "lp":
            # x0 and ax are what the release needs if the press never travels:
            # a plain click on the line resolves as a notch click, his
            # fall-through (14090-14097)
            self._drag = {"kind": "lp", "chan": chan, "moved": False,
                          "x0": float(event.xdata), "ax": event.inaxes}
            return
        self._toggle_notch_at(chan, float(event.xdata), ax=event.inaxes)

    def _grab_at(self, chan, x, event):
        """The draggable handle under `x`, if one really is the nearest thing.

        Matthew's order is role glyph, then low-pass line, then the notch
        click.  Order alone is not enough once the reaches are measured in
        pixels: on a narrow canvas the low-pass line's reach overlaps peaks
        several micron away and swallowed every click near it, so the
        low-pass line only wins when it is at least as close as the peak.

        A role glyph is not in that argument.  It sits ON its peak by
        construction, so the nearer-peak test threw the grab away for the
        sake of the very marker the glyph is standing on, and the press
        fell through to the notch toggle -- a notch nobody asked for, three
        times in a row for one reader.  A glyph within reach now wins
        outright, which is also what the pointer has been promising: hover
        and press both read this method, so the resize arrow means the same
        thing every time it appears.
        """
        ax = event.inaxes if event.inaxes is not None else self._ax_of(chan)
        role = self._grab_role(chan, x, event)
        if role is not None:
            rv = (self._tr() or {"roles": {}})["roles"].get(role)
            if rv:
                return "role", role
        peak = self._hover_peak(chan, x, ax)
        d_peak = None if peak is None else abs(float(peak[0]) - x)
        _cut = self._lp_cut_or_none(chan)
        if self.lp_on_v[chan].get() and _cut is not None:
            d = abs(x - _cut)
            if (d <= self._tol(ax, GRAB_PX, GRAB_TOL_UM)
                    and (d_peak is None or d_peak >= d)):
                return "lp", None
        return None, None

    # ---- hover: the affordance the gestures never had ---------------------
    def _on_leave(self, _event=None):
        self._hover_clear()

    def _hover_clear(self):
        self._set_cursor("")
        self._hover_mark(None, None)

    def _set_cursor(self, name):
        if getattr(self, "_cursor_now", None) == name:
            return
        self._cursor_now = name
        try:
            self._tkcanvas.configure(cursor=name)
        except (AttributeError, tk.TclError):
            pass

    def _hover(self, event):
        """Cursor and peak highlight under the pointer.

        Three states, and each one is the answer to "can I click this?":
        a resize arrow over anything draggable (a role glyph, the low-pass
        line), a hand plus a ring around the peak that a click would act
        on, and the plain pointer over bare plot.
        """
        chan = self._panel_of(event.inaxes) if event.inaxes else None
        if chan is None or event.xdata is None or self._toolbar_busy():
            self._hover_clear()
            return
        ax, x = event.inaxes, float(event.xdata)
        if self._grab_at(chan, x, event)[0] is not None:
            self._hover_mark(None, None)
            self._set_cursor("sb_h_double_arrow")
            return
        xy = self._hover_peak(chan, x, ax)
        self._set_cursor("hand2" if xy is not None else "")
        self._hover_mark(chan, xy)

    def _hover_peak(self, chan, x, ax):
        """The drawn peak under the pointer, from what is ON the axes.

        Motion fires per pixel, so this reads the markers the last draw put
        down (`_peak_xy`) instead of asking `_compute` -- a cache miss there
        would cost an FFT per mouse move.  The click path still goes through
        `_nearest_peak`, which is exact.
        """
        pts = getattr(self, "_peak_xy", {}).get(chan) or []
        if not pts:
            return None
        best = min(pts, key=lambda p: abs(p[0] - x))
        if abs(best[0] - x) > self._tol(ax, PICK_PX, CLICK_TOL_UM):
            return None
        return best

    def _hover_mark(self, chan, xy):
        """Ring the peak a click would take, and only that one.

        Guarded on the ring's identity, not on the pointer: motion fires per
        pixel and every repaint is a full figure draw, so moving ACROSS one
        peak must cost one draw, not forty.
        """
        key = None if xy is None else (chan, round(float(xy[0]), 3))
        if key == getattr(self, "_hover_key", None):
            return
        self._hover_key = key
        for ch, ln in self._artists.get("hover", {}).items():
            want = xy is not None and ch == chan
            if want:
                ln.set_data([xy[0]], [xy[1]])
            ln.set_visible(want)
        self._safe_draw()

    def _on_motion(self, event):
        if self._drag is None:
            self._hover(event)
            return
        if event.xdata is None:
            return
        x = max(float(event.xdata), 0.0)
        if self._drag["kind"] == "lp":
            chan = self._drag["chan"]
            # The panel guard, his (14033-14045).  A cutoff is a number read
            # off THIS channel's own FFT axis, so motion that has wandered
            # anywhere else is not a cutoff at all.  Without the guard a
            # pointer that strays into the measured panel mid-drag wrote that
            # panel's wavenumber -- 17867 -- into the box: the tick still read
            # on and the filter silently did nothing.  Dragging the line right,
            # past a large peak, is exactly the gesture that leaves the panel.
            if self._panel_of(event.inaxes) != chan:
                return
            ax = event.inaxes
            try:
                xlo, xhi = (float(v) for v in ax.get_xlim())
            except (AttributeError, TypeError, ValueError):
                xlo, xhi = 1.0, LP_MAX_UM
            # ...and the clamp, his: the spinbox's own range, then whatever of
            # it is on screen.  A drag can never leave a value the box cannot
            # hold, at either end.
            x = min(max(float(event.xdata), 1.0, xlo), LP_MAX_UM, xhi)
            self._drag["moved"] = True
            self._suspend = True
            try:
                self.lp_v[chan].set("%.2f" % x)
            finally:
                self._suspend = False
            ln = self._artists.get("lp", {}).get(chan)
            if ln is not None:
                ln.set_xdata([x, x])
            lt = self._artists.get("lptext", {}).get(chan)
            if lt is not None:
                try:
                    lt.set_x(x)
                except Exception:
                    pass
            self._slide_lp_shade(chan, x, xlo, xhi)
            # the removed-fraction curve follows the cursor, evaluated at
            # the LIVE cutoff: the mask under the pointer, before the value
            # is committed (his _lp_move_left_visuals, 13971)
            cv = self._artists.get("removed", {}).get(chan)
            grid = getattr(cv, "_fr_grid", None) if cv is not None else None
            if grid is not None:
                try:
                    cv.set_ydata(self._removed_curve(chan, grid, lp_cut=x))
                except Exception:
                    pass
            self._safe_draw()
            self._status("low-pass cutoff %.2f um" % x, log=False)
            # debounced at DEBOUNCE_MS, so rapid motion coalesces into one
            # recompute of the measured column per ~110 ms (his _LP_LIVE_MS),
            # and it keeps the view: his live pass repaints the right column
            # alone, so the panel under the pointer cannot move mid-drag
            self._request_redraw(keep_view=True)
        elif self._drag["kind"] == "role":
            role = self._drag["role"]
            tr = self._tr()
            if tr is not None:
                tr["roles"][role] = {"nt_um": x, "auto": False}
                tr["gauss"][role] = None
                if role in ("sample", "sampledia"):
                    tr["gauss"]["_sample_pair"] = None
            first = not self._drag.get("moved")
            self._drag["moved"] = True
            man = self._role_colors()[1]
            ln = self._artists.get("roles", {}).get(role)
            if ln is not None:
                ln.set_xdata([x])
                if first:             # it is yours from the first move on
                    try:
                        ln.set_color(man)
                        ln.set_markerfacecolor(man)
                    except Exception:
                        pass
            for i, gl in enumerate(self._artists.get("guides", {})
                                   .get(role, ())):
                try:
                    gl.set_xdata([x, x])
                    if first and i:   # the coloured line, over the ink one
                        gl.set_color(man)
                        gl.set_linestyle("--")
                except Exception:
                    pass
            if ln is not None:
                self._safe_draw()

    def _slide_lp_shade(self, chan, x, xlo, xhi):
        """Slide the removed-region shade's left edge to a live cutoff.

        The shade is one rectangle in data x over an axes-fraction y, so a
        drag only has to move its left edge and re-length it -- no redraw
        (his _lp_move_left_visuals, 13980-13986).  Older matplotlib hands
        `axvspan` back as a Polygon rather than a Rectangle, so the vertex
        path is kept beside the cheap one.
        """
        sh = self._artists.get("lpshade", {}).get(chan)
        if sh is None:
            return
        xl = min(max(float(x), float(xlo)), float(xhi))
        try:
            sh.set_x(xl)
            sh.set_width(max(float(xhi) - xl, 0.0))
            return
        except AttributeError:
            pass
        try:
            xr = float(np.max(np.asarray(sh.get_xy(), float)[:, 0]))
            sh.set_xy([[xl, 0.0], [xl, 1.0], [xr, 1.0], [xr, 0.0], [xl, 0.0]])
        except Exception:
            pass

    def _view_limits(self):
        """The four panels' x and y limits, for a redraw that must not move
        the view (his preserve_view)."""
        out = []
        for ax in (self.ax_bg, self.ax_s, self.ax_mb, self.ax_ms):
            try:
                out.append((ax, ax.get_xlim(), ax.get_ylim()))
            except Exception:
                continue
        return out

    def _restore_limits(self, saved):
        """Put the limits `_view_limits` took back, after the redraw."""
        for ax, xl, yl in saved or ():
            try:
                ax.set_xlim(*xl)
                ax.set_ylim(*yl)
            except Exception:
                continue
        self._safe_draw()

    def _release_lp(self, drag):
        """Commit a low-pass drag, his _on_release (14066-14097).

        Three things his does and ours did not.  The pending live redraw is
        cancelled, because the full-quality one below supersedes it.  A press
        that never travelled is not a cutoff change at all: it falls through
        to the notch toggle, the same fall-through a role glyph's click has.
        And the commit KEEPS THE VIEW -- zooming in to place the line past a
        large peak is precisely the gesture that would otherwise lose its own
        frame, since a plain redraw re-sets x to 0..upper and re-autoscales y.

        `_lp_last` is written with the committed text so a later <FocusOut>
        on the spinbox sees nothing changed and does not fire again.
        """
        chan = drag.get("chan")
        if self._after is not None:
            try:
                self.app.root.after_cancel(self._after)
            except (tk.TclError, ValueError):
                pass
            self._after = None
        if not drag.get("moved"):
            x0 = drag.get("x0")
            if x0 is not None:
                self._toggle_notch_at(chan, float(x0), ax=drag.get("ax"))
            return
        x = _f(self.lp_v[chan], 15.0)
        ln = self._artists.get("lp", {}).get(chan)
        if ln is not None:
            try:                       # already clamped during the drag
                x = float(np.ravel(ln.get_xdata())[0])
            except (IndexError, TypeError, ValueError):
                pass
        self._suspend = True
        try:
            self.lp_v[chan].set("%g" % x)
        finally:
            self._suspend = False
        self._lp_last[chan] = self.lp_v[chan].get()
        self._status("%s low-pass cutoff %.2f um." % (chan, x))
        # the low-pass is a global control, so the drag lands on every trace
        # the panel holds no per-trace answer for; keep_view is what makes
        # the commit hold the frame the reader placed the line in, in
        # WHICHEVER window the drag happened (his preserve_view).  Saving
        # the limits here instead would restore them before the pop-out's
        # deferred repaint ran, which is why that window used to snap back.
        self._invalidate(now=True, every=True, keep_view=True)

    def _on_release(self, _event):
        if self._drag is None:
            return
        drag = self._drag
        kind = drag.get("kind")
        role = drag.get("role")
        moved = bool(drag.get("moved"))
        self._drag = None
        if kind == "lp":
            self._release_lp(drag)
            return
        if role is None or not moved:
            # a press with no travel leaves the glyph exactly as it was
            self._refresh_roles()
            self._request_redraw()
            return
        self._drop_role(role)

    def _drop_role(self, role):
        """The drop, his _on_release (14098-14125).

        The glyph stays at the EXACT drop position -- no snap -- and becomes
        yours (auto off), then the geometry is solved from the three glyphs
        and written straight back into the inputs, which walks the model
        stems onto the glyphs.  An unphysical drop keeps the glyph and says
        so in the solve-status.
        """
        tr = self._tr()
        if tr is None:
            return
        rv = tr["roles"].get(role) or {}
        x = max(float(rv.get("nt_um") or 0.0), 0.0)
        tr["roles"][role] = {"nt_um": x, "auto": False}
        tr["gauss"][role] = None
        if role in ("sample", "sampledia"):
            tr["gauss"]["_sample_pair"] = None
        tr["seeded"] = True               # you have taken over from the guess
        applied = self._apply_solved()
        rs, rd = tr["roles"].get("sample"), tr["roles"].get("sampledia")
        unphysical = (role in ("sample", "sampledia") and rs and rd
                      and float(rs["nt_um"]) > float(rd["nt_um"]))
        if unphysical:
            self._set_solve_status("sample sits right of the sample diamond: "
                                   "layer 2 floors at 0")
            self._status("%s at %.2f um, right of the sample diamond."
                         % (ROLE_DISP[role], x), warn=True)
        elif not applied:
            self._refresh_roles()
            self._request_redraw(now=True)

    def _drawn_row(self, role):
        """The axes-fraction row a glyph was actually drawn on.

        Read off the artist first, because the pop-out swaps the artist
        registry with the figure it belongs to: the row a press is compared
        against is then the row of the view being pressed, staggered or not.
        """
        ln = self._artists.get("roles", {}).get(role)
        if ln is not None:
            try:
                return float(np.ravel(ln.get_ydata())[0])
            except (IndexError, TypeError, ValueError):
                pass
        return float(getattr(self, "_role_y", {}).get(role, ROLE_Y[role]))

    def _grab_role(self, chan, x, event):
        """Which glyph a press is reaching for: nearest drawn ROW first, then
        nearest x (his _role_at_event, 13836-13871).

        Row before x is what lets a coincident Sample pair be pulled apart:
        the draw staggers the rectangle onto a lower row, so the upper row
        grabs the sample diamond and the lower one the rectangle even while
        their n*t are the same.  Rows within a thousandth count as one row,
        which puts the un-staggered case back on nearest-x.
        """
        best = None
        tr = self._tr()
        if tr is None:
            return None
        try:
            yf = event.inaxes.transAxes.inverted().transform(
                (event.x, event.y))[1]
        except Exception:
            yf = None
        tol = self._tol(event.inaxes if event.inaxes is not None
                        else self._ax_of(chan), GRAB_PX, GRAB_TOL_UM)
        for role in ROLES:
            if ROLE_PANEL[role] != chan:
                continue
            rv = tr["roles"].get(role)
            if not rv:
                continue
            dx = abs(float(rv["nt_um"]) - x)
            if dx > tol:
                continue
            row = self._drawn_row(role)
            dy = abs(row - yf) if yf is not None else 0.0
            if dy > ROLE_GRAB_DY:
                continue
            if best is None or (round(dy, 3), dx) < best[0]:
                best = ((round(dy, 3), dx), role)
        return best[1] if best else None

    def _candidates(self, chan):
        c = self._compute(chan)
        if not c or "peaks" not in c or not len(c["peaks"]):
            return np.array([])
        return c["nt_um"][c["peaks"]]

    def _nearest_peak(self, chan, x, ax=None, exact=False):
        """The 0.01 um key of the peak under `x`, or None if none is in reach.

        `exact` asks for (key, the peak's own n*t in micron) instead: the key
        is the identity the list files a centre under, the second number is
        the centre the mask is given (his click-add stores the measured nm,
        13878).
        """
        cand = self._candidates(chan)
        if not len(cand):
            return (None, None) if exact else None
        j = int(np.argmin(np.abs(cand - x)))
        tol = self._tol(self._ax_of(chan) if ax is None else ax,
                        PICK_PX, CLICK_TOL_UM)
        if abs(float(cand[j]) - x) > tol:
            return (None, None) if exact else None
        um = float(cand[j])
        return (round(um, 2), um) if exact else round(um, 2)

    def _toggle_notch_at(self, chan, x, ax=None):
        """Left-click within reach of a peak: a peak in the list is removed, a
        bare peak is added.  Unticking (keep the marker, drop it from the
        notch) is the list's checkbox, not a plot click -- Matthew's
        grammar."""
        kk, um = self._nearest_peak(chan, x, ax=ax, exact=True)
        if kk is None:
            self._status("aim at a marker to pick its FFT peak.")
            return
        # the mask is given the peak's own n*t, not the key it is filed under
        self._note_exact(chan, um)
        ch = self._ch(chan)
        listed = ((kk in ch["default_centers"] or kk in ch["user_centers"])
                  and kk not in ch["removed"])
        if listed:
            ch["removed"].add(kk)
            ch["user_centers"] = [k for k in ch["user_centers"] if k != kk]
            self._status("removed the notch at %.2f um." % kk)
        else:
            ch["removed"].discard(kk)
            if kk not in ch["default_centers"] and kk not in ch["user_centers"]:
                ch["user_centers"].append(kk)
            self._status("added a notch at %.2f um." % kk)
        self._invalidate()

    def _rclick(self, chan, x, event):
        kk, um = self._nearest_peak(chan, x, ax=event.inaxes, exact=True)
        if kk is None:
            self._status("aim at a marker to pick its FFT peak.")
            return
        self._note_exact(chan, um)     # a pin can add this centre to the list
        ch = self._ch(chan)
        menu = tk.Menu(self.app.root, tearoff=0)
        is_fund = (self._fund_key(chan) == kk)
        menu.add_command(
            label=("%.2f um is the fundamental" % kk if is_fund
                   else "Pin %.2f um as the fundamental" % kk),
            state=("disabled" if is_fund else "normal"),
            command=lambda: self._pin_fundamental(chan, kk))
        if ch["user_fundamental"] != FUND_NONE:
            menu.add_command(
                label="Clear the %s fundamental" % chan.lower(),
                command=lambda: self._pin_fundamental(chan, FUND_NONE))
        if ch["user_fundamental"] is not None:
            menu.add_command(label="Reset the fundamental to auto",
                             command=lambda: self._pin_fundamental(chan, None))
        # ...and the roles this panel carries, so a glyph can always be put
        # somewhere without hunting for it first
        roles = [r for r in ROLES if ROLE_PANEL[r] == chan]
        if roles:
            menu.add_separator()
            for role in roles:
                menu.add_command(
                    label="Assign %.2f um as %s" % (kk, ROLE_DISP[role]),
                    command=lambda r=role, k=kk: self._assign_role_here(r, k))
        ge = getattr(event, "guiEvent", None)
        try:
            if ge is not None:
                menu.tk_popup(ge.x_root, ge.y_root)
            else:
                menu.tk_popup(self.app.root.winfo_pointerx(),
                              self.app.root.winfo_pointery())
        finally:
            menu.grab_release()

    def _pin_fundamental(self, chan, kk):
        """The fundamental's three states, his (_assign_fundamental 13910,
        _clear_fundamental 13928, _set_fundamental_none 13937).

        `kk` is a micron key to pin, None for auto, or FUND_NONE for "this
        channel has no fundamental".  A pinned peak is made a live notch
        member first (un-removed, re-ticked, added when absent), so the
        fundamental always exists on the list it leads.
        """
        ch = self._ch(chan)
        if ch is None:
            return
        ch["user_fundamental"] = kk
        if kk == FUND_NONE:
            self._status("%s has no fundamental." % chan)
        elif kk is not None:
            ch["removed"].discard(kk)
            ch["unticked"].discard(kk)
            if kk not in ch["default_centers"] and kk not in ch["user_centers"]:
                ch["user_centers"].append(kk)
            self._status("%s fundamental pinned at %.2f um." % (chan, kk))
        else:
            self._status("%s fundamental back to the detected peak." % chan)
        self._notch_sig = None
        self._invalidate()

    def _fund_radio(self, chan, kk):
        """The notch list's Fundamental radio (his _on_fund_radio, 14286).

        Clicking the row that already holds it clears the channel to "no
        fundamental"; clicking any other row pins that one.  One control,
        all three states.
        """
        if self._rebuilding:
            return
        cur = self._fund_key(chan)
        if cur is not None and abs(float(cur) - float(kk)) < 0.005:
            self._pin_fundamental(chan, FUND_NONE)
        else:
            self._pin_fundamental(chan, kk)

    # ---- notch list actions ----------------------------------------------
    def _tick(self, chan, kk, var):
        if self._rebuilding:
            return
        ch = self._ch(chan)
        if var.get():
            ch["unticked"].discard(kk)
        else:
            ch["unticked"].add(kk)
        self._invalidate(now=False)

    def _set_width(self, chan, kk, var):
        """Commit one centre's own half-width.

        Returns at once while the list is being rebuilt: destroying the row
        that holds the keyboard focus emits <FocusOut>, which is bound here,
        so a redraw begun by the previous width edit re-entered the rebuild
        it was already inside.
        """
        if self._rebuilding:
            return
        hw = _f(var, self._width_of(chan, kk))
        if hw <= 0:
            var.set("%g" % self._width_of(chan, kk))
            return
        self._ch(chan)["widths"][kk] = hw
        self._invalidate(now=False)

    def _remove_center(self, chan, kk):
        if self._rebuilding:
            return
        ch = self._ch(chan)
        ch["removed"].add(kk)
        ch["user_centers"] = [k for k in ch["user_centers"] if k != kk]
        self._invalidate(now=False)

    def _reset_notches(self):
        for chan in CHANNELS:
            ch = self._ch(chan)
            if ch is None:
                continue
            ch["user_centers"] = []
            ch["removed"] = set()
            ch["unticked"] = set()
            ch["user_fundamental"] = None
            ch["widths"] = {}
        self._status("notches reset to the detected fundamental.")
        self._invalidate()

    # ---- Fit peaks --------------------------------------------------------
    def _fit_peaks(self, before=None):
        """Refine every auto glyph onto its peak, and say what each one did.

        Distinct fits each role independently.  Shared ties the two Sample
        roles to ONE hump: a joint two-Gaussian fit with a shared sigma and an
        offset constrained to delta >= 0, so the pair can never come back in
        an order the solve cannot invert.  `before` is where the glyphs stood
        when the button was pressed, which is what "already on the peak" is
        measured against.  Returns the summary line.
        """
        tr = self._tr()
        if tr is None:
            return ""
        mode = self.fitmode_v.get()
        if before is None:
            before = self._role_positions()
        out = self._autosnap_roles(keep_seed=False)
        self.settings["fr_fit_mode"] = mode
        msg = "fit peaks (%s): %s" % (mode, self._fit_report(out, before))
        self._refresh_roles()
        return msg

    def _role_positions(self):
        """{role: n*t or None} as the glyphs stand right now."""
        tr = self._tr() or {"roles": {}}
        return {r: ((tr["roles"].get(r) or {}).get("nt_um")) for r in ROLES}

    @staticmethod
    def _fit_report(out, before):
        """One phrase per role, telling the three outcomes apart: a landed fit
        that moved it, a landed fit already on the peak, the nearest-peak
        fallback, and the physical-order snap."""
        parts = []
        for role in ROLES:
            if role not in out:
                continue
            val, how = out[role]
            name = ROLE_DISP[role]
            if val is None:
                parts.append("%s unplaced" % name)
                continue
            was = before.get(role)
            still = was is not None and abs(float(was) - float(val)) < 0.005
            if how == "fit" and still:
                parts.append("%s already on the peak at %.2f um" % (name, val))
            elif how == "fit":
                parts.append("%s refined to %.2f um" % (name, val))
            elif how == "order":
                parts.append("%s onto the sample diamond at %.2f um"
                             % (name, val))
            elif how == "peak":
                parts.append("%s kept at the nearest peak %.2f um (fit "
                             "failed)" % (name, val))
            else:
                parts.append("%s held at %.2f um" % (name, val))
        return "; ".join(parts) if parts else "every glyph held its position"

    # ---- the refine, his algorithms ---------------------------------------
    # Ported from defringe_dac.py 12269-12507.  Three things separate these
    # from the pre-R15 versions and each one was a miss on real data:
    # the window is anchored on the NEAREST DETECTED PEAK rather than the raw
    # model target (the model n*t sits a bin or so off the measurement, and a
    # target-centred window clips the peak's far flank); the window is +-3 um
    # absolute rather than a multiple of the notch half-width (which reached
    # 7.5 um and let a fit walk to the neighbouring hump); and a rejected fit
    # returns the nearest detected peak rather than the position it started
    # from, so a glyph always lands on something measured.
    def _fft_xy(self, chan):
        """(x_um, V) of a channel's FFT amplitude, on the plotted V scale."""
        c = self._compute(chan)
        if not c or "V" not in c or "nt_um" not in c:
            return None
        x = np.asarray(c["nt_um"], float)
        y = np.asarray(c["V"], float)
        if x.size == 0 or y.size != x.size:
            return None
        m = np.isfinite(x) & np.isfinite(y)
        if int(m.sum()) < 3:
            return None
        return x[m], y[m]

    def _nearest_peak_um(self, chan, target_um):
        """The detected peak nearest `target_um`, with NO distance gate, so a
        role always finds a peak (his _nearest_peak_um).  `_nearest_peak` is
        the click path and keeps its reach; this one is the fit path."""
        if target_um is None:
            return None
        cand = np.asarray(self._candidates(chan), float)
        cand = cand[np.isfinite(cand)] if cand.size else cand
        if not cand.size:
            return None
        j = int(np.argmin(np.abs(cand - float(target_um))))
        return float(cand[j])

    def _refine_peak(self, chan, role, target_um, win_um=None):
        """One peak, refined by a Gaussian on the FFT amplitude.

        A exp(-((x-mu)/sig)^2/2) + c with c FIXED at the whole curve's 5th
        percentile: in packed fringe data the level between peaks is the
        neighbours' overlapping tails, so a fitted floor absorbs them and
        drifts.  Returns (x_um, how) where how is "fit" for a landed fit,
        "peak" for the nearest-detected-peak fallback and None when the
        channel has neither.  The fitted curve is stored under
        tr["gauss"][role] for the overlay.
        """
        tr = self._tr()
        if tr is not None:
            tr["gauss"][role] = None
        near = self._nearest_peak_um(chan, target_um)
        fallback = (near, "peak" if near is not None else None)
        xy = self._fft_xy(chan)
        if xy is None:
            return fallback
        x, y = xy
        anchor = near if near is not None else (
            None if target_um is None else float(target_um))
        if anchor is None:
            return fallback
        c = float(np.percentile(y, BASELINE_PCTL))
        dx = float(np.median(np.diff(x))) if x.size > 1 else 0.05
        half = float(win_um) if win_um is not None else REFINE_WIN_UM
        m = (x >= anchor - half) & (x <= anchor + half)
        if int(m.sum()) < 3:
            return fallback
        xs, ys = x[m], y[m]
        A0 = max(float(np.max(ys) - c), 1e-9)
        # guard sig_lo < sig_hi for a coarse grid, and keep the seed inside
        # the bounds -- curve_fit raises on either
        sig_lo = min(dx, 0.5 * half)
        sig0 = float(np.clip(max(2.0 * dx, half / 3.0), sig_lo, half))
        try:
            from scipy.optimize import curve_fit
        except ImportError:
            return fallback

        def _g(xx, A, mu, sig):           # c is held fixed in the closure
            return A * np.exp(-0.5 * ((xx - mu) / sig) ** 2) + c
        try:
            with warnings.catch_warnings():
                warnings.simplefilter("ignore")
                popt, _cov = curve_fit(
                    _g, xs, ys, p0=[A0, anchor, sig0],
                    bounds=([0.0, xs[0], sig_lo], [np.inf, xs[-1], half]),
                    maxfev=4000)
        except Exception:
            return fallback
        mu = float(popt[1])
        if not np.isfinite(mu) or not (xs[0] <= mu <= xs[-1]):
            return fallback
        if tr is not None:
            tr["gauss"][role] = {"panel": chan, "A": float(popt[0]), "mu": mu,
                                 "sig": float(popt[2]), "c": c,
                                 "x0": float(xs[0]), "x1": float(xs[-1])}
        return mu, "fit"

    def _refine_pair(self, t_sample, t_sampledia):
        """Both Sample roles at once, in the mode the Fit peaks buttons set.

        Distinct = two independent single-peak refines, no joint envelope.
        Shared = his apex-plus-shoulder path: fit one Gaussian to the apex,
        look for a shoulder in the residual, re-centre the window on the two
        of them, then a joint five-parameter fit A1, m1, A2, delta, sigma with
        ONE shared sigma and m2 = m1 + delta, delta >= 0 -- both fringe peaks
        are set by the same spectral window, so their widths match, and the
        ordered offset keeps the pair in an order the solve can invert.
        Returns {role: (x_um, how)}.
        """
        tr = self._tr()
        if tr is not None:
            tr["gauss"]["sample"] = None
            tr["gauss"]["sampledia"] = None
            tr["gauss"]["_sample_pair"] = None
        fb_s = self._nearest_peak_um("Sample", t_sample)
        fb_d = self._nearest_peak_um("Sample", t_sampledia)

        def _fb():
            return {"sample": (fb_s, "peak" if fb_s is not None else None),
                    "sampledia": (fb_d,
                                  "peak" if fb_d is not None else None)}
        if t_sample is None or t_sampledia is None:
            return _fb()
        if self.fitmode_v.get() != "shared":
            return {"sample": self._refine_peak("Sample", "sample", t_sample),
                    "sampledia": self._refine_peak("Sample", "sampledia",
                                                   t_sampledia)}
        xy = self._fft_xy("Sample")
        if xy is None:
            return _fb()
        x, y = xy
        # which way round the model puts the pair, so the fitted centres map
        # back onto the right roles
        a_lo, a_hi = float(t_sample), float(t_sampledia)
        swapped = a_lo > a_hi
        dx = float(np.median(np.diff(x))) if x.size > 1 else 0.05
        # window anchored on the nearest ACTUAL peaks, each with its own
        # reach, spanning both
        w_lo = fb_s if fb_s is not None else a_lo
        w_hi = fb_d if fb_d is not None else a_hi
        lo, hi = (w_lo, w_hi) if w_lo <= w_hi else (w_hi, w_lo)
        m = (x >= lo - PAIR_REACH_UM) & (x <= hi + PAIR_REACH_UM)
        if int(m.sum()) < 5:              # 5 free parameters
            return _fb()
        xs, ys = x[m], y[m]
        c = float(np.percentile(y, BASELINE_PCTL))
        wwin = float(xs[-1] - xs[0])

        def _amp_at(a):                   # height above the fixed floor
            return max(float(y[int(np.argmin(np.abs(x - a)))] - c), 1e-9)
        # sigma capped at the reach, the same width scale the single fit
        # allows, so a joint Gaussian cannot balloon over the whole window
        sig_hi = PAIR_REACH_UM
        sig_lo = min(dx, 0.5 * sig_hi)
        sig0 = float(np.clip(max(2.0 * dx, (hi - lo) / 3.0), sig_lo, sig_hi))
        try:
            from scipy.optimize import curve_fit
        except ImportError:
            return _fb()

        def _g1(xx, A, mu, sig):
            return A * np.exp(-0.5 * ((xx - mu) / sig) ** 2) + c

        def _g2(xx, A1, m1, A2, dlt, s):
            return (A1 * np.exp(-0.5 * ((xx - m1) / s) ** 2)
                    + A2 * np.exp(-0.5 * ((xx - (m1 + dlt)) / s) ** 2) + c)
        try:
            with warnings.catch_warnings():
                warnings.simplefilter("ignore")
                # step 1: one Gaussian on the apex, so its residual can show
                # a shoulder
                apex0 = float(xs[int(np.argmax(ys))])
                p1, _c1 = curve_fit(
                    _g1, xs, ys,
                    p0=[max(float(np.max(ys)) - c, 1e-9), apex0, sig0],
                    bounds=([0.0, xs[0], sig_lo], [np.inf, xs[-1], sig_hi]),
                    maxfev=4000)
                A_ap, mu_ap, s_ap = (float(v) for v in p1)
                # step 2: the largest positive leftover is a second peak when
                # it is a real fraction of the apex AND more than half a
                # sample away from it; otherwise the second Gaussian seeds on
                # the apex and collapses there (the clean single-peak case)
                resid = ys - _g1(xs, A_ap, mu_ap, s_ap)
                j = int(np.argmax(resid))
                sh_mu, sh_amp = float(xs[j]), float(resid[j])
                sep = SHOULDER_SEP_BINS * dx
                has_shoulder = (sh_amp > SHOULDER_AMP_FRAC * A_ap
                                and abs(sh_mu - mu_ap) > sep)
                seed2 = sh_mu if has_shoulder else mu_ap
                # re-centre the window on apex AND shoulder, each with its own
                # margin, so a shoulder near the old edge keeps its flank
                plo, phi = ((mu_ap, seed2) if mu_ap <= seed2
                            else (seed2, mu_ap))
                m2 = (x >= plo - PAIR_REACH_UM) & (x <= phi + PAIR_REACH_UM)
                if int(m2.sum()) >= 5:
                    xs, ys = x[m2], y[m2]
                    wwin = float(xs[-1] - xs[0])
                # step 3: the joint fit, seeded with the second Gaussian on
                # the shoulder
                lo2, hi2 = ((mu_ap, seed2) if mu_ap <= seed2
                            else (seed2, mu_ap))
                p0 = [_amp_at(lo2), lo2, _amp_at(hi2),
                      float(np.clip(hi2 - lo2, 0.0, wwin)), s_ap]
                lob = [0.0, xs[0], 0.0, 0.0, sig_lo]
                hib = [np.inf, xs[-1], np.inf, wwin, sig_hi]
                popt, _c2 = curve_fit(_g2, xs, ys, p0=p0, bounds=(lob, hib),
                                      maxfev=8000)
        except Exception:
            return _fb()
        A1, mu_lo, A2, dlt, s = (float(v) for v in popt)
        mu_hi = mu_lo + dlt               # delta >= 0, so the order holds
        if not (np.isfinite(mu_lo) and np.isfinite(mu_hi)):
            return _fb()
        if not (xs[0] <= mu_lo <= mu_hi <= xs[-1]):
            return _fb()
        x0, x1 = float(xs[0]), float(xs[-1])
        g_lo = {"panel": "Sample", "A": A1, "mu": mu_lo, "sig": s, "c": c,
                "x0": x0, "x1": x1}
        g_hi = {"panel": "Sample", "A": A2, "mu": mu_hi, "sig": s, "c": c,
                "x0": x0, "x1": x1}
        if tr is not None:
            # each role carries its own component; the combined envelope is
            # stored once, panel-level, and drawn once
            tr["gauss"]["_sample_pair"] = {
                "A1": A1, "mu1": mu_lo, "A2": A2, "mu2": mu_hi, "sig": s,
                "c": c, "x0": x0, "x1": x1}
            tr["gauss"]["sample"], tr["gauss"]["sampledia"] = (
                (g_hi, g_lo) if swapped else (g_lo, g_hi))
        if swapped:
            return {"sample": (mu_hi, "fit"), "sampledia": (mu_lo, "fit")}
        return {"sample": (mu_lo, "fit"), "sampledia": (mu_hi, "fit")}

    def _autosnap_roles(self, p=None, keep_seed=True):
        """Re-fit every AUTO role onto its model path (his _autosnap_roles).

        Both Sample roles auto -> the pair fit in the Fit peaks mode; exactly
        one auto -> a single refine for that one, because a glyph the user
        placed must not enter the joint fit or take a curve of its own; the
        medium etalon is always a single refine.  A manual role is never
        touched.  Returns {role: (x_um, how)} for the status line.
        """
        tr = self._tr()
        if tr is None:
            return {}
        if p is None:
            rec = self._record()
            if rec is None:
                return {}
            p = self._stack_params(rec)
        pred = self._pred_paths(p)
        if not pred:
            # the stack model could not be built at all: the glyphs on screen
            # are better than nothing, so they stay
            return {}
        out = {}

        def is_auto(role):
            cur = tr["roles"].get(role)
            return cur is None or bool(cur.get("auto"))

        def place(role, val, how):
            if val is None:
                tr["roles"][role] = None
                tr["gauss"][role] = None
            else:
                prev = tr["roles"].get(role) or {}
                rv = {"nt_um": float(val), "auto": True}
                if keep_seed and prev.get("seed"):
                    rv["seed"] = True
                tr["roles"][role] = rv
            out[role] = (val, how)

        t_s, t_d = pred.get("sample"), pred.get("sampledia")
        s_auto, d_auto = is_auto("sample"), is_auto("sampledia")
        if s_auto and d_auto:
            pair = self._refine_pair(t_s, t_d)
            place("sample", *(pair.get("sample", (None, None))
                              if t_s is not None else (None, None)))
            place("sampledia", *(pair.get("sampledia", (None, None))
                                 if t_d is not None else (None, None)))
        elif s_auto:
            place("sample", *(self._refine_peak("Sample", "sample", t_s)
                              if t_s is not None else (None, None)))
        elif d_auto:
            place("sampledia",
                  *(self._refine_peak("Sample", "sampledia", t_d)
                    if t_d is not None else (None, None)))
        # Physical order: the sample path A can never exceed the whole-cell
        # path C, since C = A + medium.  An AUTO sample that landed right of
        # the sample-diamond is snapped ONTO it (A = C, layer 2 at zero).  A
        # glyph the user dragged there is left where it is -- the drop handler
        # warns about that one instead.
        rs, rd = tr["roles"].get("sample"), tr["roles"].get("sampledia")
        if (rs and rd and rs.get("auto")
                and float(rs["nt_um"]) > float(rd["nt_um"])):
            place("sample", float(rd["nt_um"]), "order")
            tr["gauss"]["sample"] = None
            tr["gauss"]["_sample_pair"] = None
        if is_auto("mediumdia"):
            t_m = pred.get("mediumdia")
            place("mediumdia",
                  *(self._refine_peak("Background", "mediumdia", t_m)
                    if t_m is not None else (None, None)))
        return out

    def _clear_role(self, role):
        tr = self._tr()
        if tr is None:
            return
        tr["roles"][role] = None
        tr["gauss"][role] = None
        if role in ("sample", "sampledia"):
            tr["gauss"]["_sample_pair"] = None
        tr["seeded"] = True           # deliberate: the seed does not undo it
        self._status("%s unassigned. Right-click a peak to put the glyph "
                     "back." % ROLE_DISP[role])
        self._refresh_roles()
        self._request_redraw(now=True)

    def _assign_role_here(self, role, x):
        """Put one role at `x` outright -- the right-click menu's answer, and
        the same result a drag would leave: yours, unsnapped, refinable."""
        tr = self._tr()
        if tr is None:
            return
        tr["roles"][role] = {"nt_um": float(x), "auto": False}
        tr["gauss"][role] = None
        if role in ("sample", "sampledia"):
            tr["gauss"]["_sample_pair"] = None
        tr["seeded"] = True           # you have taken over from the guess
        self._status("%s assigned at %.2f um; Fit peaks re-detects it."
                     % (ROLE_DISP[role], float(x)))
        self._refresh_roles()
        self._request_redraw(now=True)

    # ---- Solve ------------------------------------------------------------
    def _solve(self, quiet=False):
        """Invert the three picked paths.  Returns the solved dict, or None.

        `quiet` keeps the readout, the solve-status and the stored solve, and
        holds back only the status line -- for the callers that write their
        own (his _apply_solved reports the applied values instead).
        """
        tr = self._tr()
        rec = self._record()
        if tr is None or rec is None:
            return None
        r = tr["roles"]
        missing = [ROLE_DISP[k] for k in ROLES if not r.get(k)]
        if missing:
            if not quiet:
                self._status("assign %s before solving." % ", ".join(missing),
                             warn=True)
            return None
        p = self._stack_params(rec)
        sol = fringe_optics.solve_paths(
            float(r["sample"]["nt_um"]), float(r["sampledia"]["nt_um"]),
            float(r["mediumdia"]["nt_um"]), p["n_layer2"], p["n_medium"])
        if sol is None:
            if not quiet:
                self._status("a refractive index came out at or below zero; "
                             "the solve needs a positive index.", warn=True)
            return None
        tr["solved"] = dict(sol)
        for key in ("n_s", "t_s", "t_layer2", "L"):
            lab = self._sol_lbl.get(key)
            if lab is None:
                continue
            try:
                lab.configure(text=_fmt(sol[key], 3))
            except tk.TclError:
                pass
        warns = sol.get("warns") or []
        self._set_solve_status("; ".join(warns) if warns else "")
        if not quiet:
            if warns:
                self._status("solved with clamps: " + "; ".join(warns),
                             warn=True)
            else:
                self._status("solved: n_s = %s, t_s = %s um, L = %s um."
                             % (_fmt(sol["n_s"]), _fmt(sol["t_s"], 2),
                                _fmt(sol["L"], 2)))
        self._refresh_state_indicators()
        return sol

    def _write_back(self, quiet=False):
        """Write the solved geometry into the input boxes.

        His _apply_solved rule: d1 is yours and stays put, so d2 takes the
        remainder of the solved medium total.  Returns the applied
        (n_s, t_s, d2), or None.
        """
        tr = self._tr()
        sol = (tr or {}).get("solved")
        if not sol:
            if not quiet:
                self._status("solve first, then adopt.", warn=True)
            return None
        self._suspend = True
        try:
            self.ns_v.set("%.4f" % sol["n_s"])
            self.t_v.set("%.3f" % sol["t_s"])
            _d1 = max(_f(self.d1_v, 0.0), 0.0)
            _d2 = max(float(sol["t_layer2"]) - _d1, 0.0)
            self.d2_v.set("%.3f" % _d2)
            if self.lock_v.get():
                self.total_v.set("%.3f" % sol["L"])
        finally:
            self._suspend = False
        self._thick_snapshot()
        for k, v in (("fr_n_sample", sol["n_s"]), ("fr_t_um", sol["t_s"]),
                     ("fr_d2_um", _d2)):
            self.settings[k] = float(v)
        if not quiet:
            self._status("adopted into the stack. the model stems have "
                         "moved.")
            self._request_redraw(now=True)
        return {"n_s": float(sol["n_s"]), "t_s": float(sol["t_s"]),
                "d2": float(_d2)}

    def _apply_solved(self):
        """His _apply_solved: solve from the glyph positions and write the
        answer straight into the inputs, so the model stems stand on the
        glyphs and the next re-detect anchors there.

        The auto glyphs then follow the stems (his _update runs the autosnap
        after every write), and the readout is re-solved so it describes the
        glyphs on screen.  Returns True when the values were applied.
        """
        tr = self._tr()
        if tr is None:
            return False
        sol = self._solve(quiet=True)
        if sol is None:
            self._solve()             # cheap, and it says which half is short
            return False
        applied = self._write_back(quiet=True)
        if applied is None:
            return False
        self._autosnap_roles()
        self._solve(quiet=True)
        self._status("applied: n sample = %.4g, t sample = %s um, "
                     "d2 = %s um." % (applied["n_s"],
                                      _fmt(applied["t_s"], 3),
                                      _fmt(applied["d2"], 3)))
        self._request_redraw(now=True)
        return True

    # ---- Series -----------------------------------------------------------
    def _branch(self, rec):
        fn = getattr(self.app, "_branch_of", None)
        if callable(fn):
            try:
                return fn(rec)
            except Exception:
                pass
        return rec.get("branch") or "C"

    def _record_point(self):
        tr = self._tr()
        rec = self._record()
        if rec is None:
            return
        if not (tr and tr.get("solved")):
            self._status("solve first. a point records the solved values.",
                         warn=True)
            return
        r = tr["roles"] or {}
        # A solve survives its glyphs: unassigning a role (right-click >
        # unassign) leaves `solved` standing, and the three paths below then
        # read a None.  Say which glyph is missing instead of raising.
        unplaced = [ROLE_DISP[k] for k in ROLES
                    if (r.get(k) or {}).get("nt_um") is None]
        if unplaced:
            self._status("%s unplaced. a point records three paths."
                         % ", ".join(unplaced), warn=True)
            return
        p = self._stack_params(rec)
        # The two indices the solve was run AT travel with the point. That is
        # what makes the Results view's re-solve exact rather than
        # approximate: (A, C, iii) are the measurement, and solve_paths
        # conserves A, so feeding the recorded indices back reproduces the
        # recorded numbers bit for bit, and feeding a different medium's n(P)
        # gives the honest answer under that model.
        pt = {"label": rec["label"],
              # the row carries its own stem, so a point read back from a
              # file still resolves to the trace it belongs to
              "stem": self._stem_of(rec["label"]),
              "pressure": float(rec.get("pressure_val") or 0.0),
              "branch": self._branch(rec),
              "A": float(r["sample"]["nt_um"]),
              "C": float(r["sampledia"]["nt_um"]),
              "iii": float(r["mediumdia"]["nt_um"]),
              "medium": self.medium_v.get(),
              "layer2": bool(self.layer2_on_v.get()),
              "layer2_name": (self.layer2_v.get()
                              if self.layer2_on_v.get() else
                              self.medium_v.get()),
              "n_medium": float(p["n_medium"]),
              "n_layer2": float(p["n_layer2"]),
              "diamond": self.diamond_v.get(),
              "solved": {k: float(v) for k, v in tr["solved"].items()
                         if k != "warns"}}
        key = self._pt_key(pt)
        self._series = [q for q in self._series if self._pt_key(q) != key]
        self._series.append(pt)
        self._series.sort(key=lambda q: (q["branch"], q["pressure"]))
        self._commit()
        self._status("recorded %s on the %s branch."
                     % (pt["label"], pt["branch"]))
        self._refresh_state_indicators()

    def _drop_point(self):
        n0 = len(self._series)
        key = self._dkey()
        self._series = [q for q in self._series if self._pt_key(q) != key]
        if len(self._series) == n0:
            self._status("drop point acts on a recorded trace.")
            return
        self._status("dropped the recorded point for this trace.")
        self._refresh_state_indicators()

    # =======================================================================
    # state discipline: memory vs disk
    # =======================================================================
    def _mem_state(self, label=None):
        """The committable state of one trace, as plain JSON types."""
        dk = self._dkey(label)
        if dk is None:
            return {}
        out = {"chan": {}, "roles": {}, "solved": None}
        for chan in CHANNELS:
            ch = self._chan.get((dk, chan))
            if ch is None:
                continue
            out["chan"][chan] = {
                "user_centers": sorted(ch["user_centers"]),
                "removed": sorted(ch["removed"]),
                "unticked": sorted(ch["unticked"]),
                "user_fundamental": ch["user_fundamental"],
                # the detector's own answer travels with the picks (R15-B):
                # defringe applies this list to a trace that is not on
                # screen, and without the fundamental that list is the
                # harmonics on their own
                "default_centers": sorted(ch.get("default_centers") or []),
                "widths": {("%.2f" % k): v for k, v in ch["widths"].items()},
                # the MEASURED centre behind each key (his `seen` values), so
                # a reopened session notches where the detector found the
                # peak and not 5 nm off it.  Additive: a payload without it
                # falls back to key*1000, which is what it always meant.
                "exact": {("%.2f" % k): float(v)
                          for k, v in (ch.get("exact") or {}).items()}}
        tr = self._trace.get(dk)
        if tr:
            out["roles"] = {k: (dict(v) if v else None)
                            for k, v in tr["roles"].items()}
            out["solved"] = (dict(tr["solved"]) if tr.get("solved") else None)
            out["solved"] = ({k: v for k, v in out["solved"].items()
                              if k != "warns"} if out["solved"] else None)
        return out

    @staticmethod
    def _owned_role(rv):
        """A role as the guard sees it: a glyph still sitting where the seed
        parked it is the workbench's opening guess, not work you would be
        sorry to lose, so it must not raise a leave prompt on its own.  One
        drag, fit or assign drops the mark and it counts from then on."""
        rv = rv or {}
        return {} if rv.get("seed") else rv

    def _dirty_items(self, label=None):
        """Itemised differences between memory and disk, in plain words."""
        label = self._label if label is None else label
        dk = self._dkey(label)
        if dk is None:
            return []
        mem = self._mem_state(label)
        disk = self._disk.get(dk)
        if disk is None:
            owned = any(self._owned_role(v) for v in mem["roles"].values())
            # The cold start solves the moment it parks the glyphs, so a
            # solve that stands on seed glyphs alone is part of the opening
            # guess too -- it moves with them, and it must not raise a leave
            # prompt on its own.  One drag, fit or assign drops the seed mark
            # and the solve counts from then on.  A solve with NO glyphs left
            # is the reader's: unassigning does not undo it.
            solved_own = bool(mem["solved"]) and (
                owned or not any(mem["roles"].values()))
            empty = (not any(v.get("user_centers") or v.get("removed")
                             or v.get("unticked") or v.get("user_fundamental")
                             or v.get("widths")
                             for v in mem["chan"].values())
                     and not owned
                     and not solved_own)
            return [] if empty else ["this trace is waiting for its first "
                                     "save"]
        items = []
        for chan in CHANNELS:
            m = mem["chan"].get(chan, {})
            d = (disk.get("chan") or {}).get(chan, {})
            for key, word in (("user_centers", "manual notch centres"),
                              ("removed", "removed centres"),
                              ("unticked", "unticked centres"),
                              ("widths", "notch widths")):
                if m.get(key) != d.get(key):
                    items.append("%s: %s changed" % (chan, word))
            if m.get("user_fundamental") != d.get("user_fundamental"):
                items.append("%s: the pinned fundamental changed" % chan)
        for role in ROLES:
            if (self._owned_role(mem["roles"].get(role))
                    != self._owned_role((disk.get("roles") or {}).get(role))):
                items.append("%s moved" % ROLE_DISP[role])
        if mem.get("solved") != disk.get("solved"):
            items.append("the solved values changed")
        return items

    def _commit(self, label=None):
        """File the current state of one trace as its committed copy.

        Two things are committed together: the trace state the leave guard
        compares against, and the per-point INPUT snapshot the continuity
        file carries and the next point seeds from (his active_series
        ['points'] / ['inputs'] pair, committed by one action).
        """
        label = self._label if label is None else label
        dk = self._dkey(label)
        if dk is None:
            return
        self._disk[dk] = self._mem_state(label)
        self._inputs[dk] = self._input_snapshot(label)
        # An off-screen read of this trace now returns the committed copy
        # rather than the global controls, so what the main plot cleans it
        # with has changed.
        self._notify_defringe(gates=False, label=label)

    def _restore(self, label):
        dk = self._dkey(label)
        d = self._disk.get(dk)
        if d is None:
            return
        self._apply_trace_state(dk, d)
        # ...and the numbers that were committed with it. seed=True is what
        # keeps this to the numbers and the low-pass: the notches and the
        # glyphs have just been put back by the line above.
        snap = self._inputs.get(dk)
        if snap is not None and label == self._label:
            self._apply_input_snapshot(snap, label=label, seed=True)

    def _apply_trace_state(self, dk, d):
        """Write one committed trace state back into memory, under its
        dataset key (never a display label -- the key is the identity)."""
        for chan, cd in (d.get("chan") or {}).items():
            if chan not in CHANNELS:
                continue
            ch = self._chan.setdefault((dk, chan), {
                "default_centers": [], "user_centers": [], "removed": set(),
                "unticked": set(), "user_fundamental": None, "widths": {},
                "exact": {}})
            ch["user_centers"] = [float(k) for k in cd.get("user_centers", [])]
            # A stored fundamental stands in until this channel is computed
            # here, which overwrites it; a session written before R15-B
            # stored none, so memory keeps whatever it already has.
            defs = [float(k) for k in (cd.get("default_centers") or [])]
            if defs or not ch["default_centers"]:
                ch["default_centers"] = defs
            ch["removed"] = set(float(k) for k in cd.get("removed", []))
            ch["unticked"] = set(float(k) for k in cd.get("unticked", []))
            ch["user_fundamental"] = cd.get("user_fundamental")
            ch["widths"] = {float(k): float(v)
                            for k, v in (cd.get("widths") or {}).items()}
            # A payload written before R17 carries no measured centres; the
            # keys it does carry then mean key*1000, exactly as they did.
            # Merged, not replaced, so a centre this session has already
            # measured keeps its own value.
            ex = ch.setdefault("exact", {})
            for k, v in (cd.get("exact") or {}).items():
                try:
                    ex[float(k)] = float(v)
                except (TypeError, ValueError):
                    continue
        tr = self._trace.setdefault(dk, {
            "roles": {r: None for r in ROLES},
            "gauss": {r: None for r in ROLES},
            "solved": None})
        for role in ROLES:
            rv = (d.get("roles") or {}).get(role)
            tr["roles"][role] = (dict(rv) if rv else None)
            # the fitted curves are a live detection artifact, never stored:
            # restored positions arrive without one
            tr["gauss"][role] = None
        tr["gauss"]["_sample_pair"] = None
        tr["solved"] = (dict(d["solved"]) if d.get("solved") else None)

    def _adopt_legacy_disk(self):
        """Move any pre-stem committed state onto its dataset key.

        A session written before the workbench keyed on file stems filed its
        traces under the display label.  The stem behind such a label can
        only be read off the records, and a session load runs before a Run
        has produced any, so those rows wait here until their record turns
        up -- on the next Run, or on the next folder load.
        """
        if not self._disk_legacy:
            return
        for label in list(self._disk_legacy):
            if self._record(label) is None:
                continue
            td = self._disk_legacy.pop(label)
            dk = self._dkey(label)
            if dk is None or dk in self._disk:
                continue
            self._disk[dk] = td
            self._apply_trace_state(dk, td)

    # =======================================================================
    # per-point inputs -- his active_series['inputs']
    # =======================================================================
    def _model_owned_nums(self):
        """The numeric fields a model owns and recomputes from each point's
        own pressure, so a stored value is never written back into them
        (his _model_owned_nums, 14359)."""
        out = set(NUM_DERIVED)
        if self.medium_v.get() != fringe_materials.MEDIUM_MANUAL:
            out.add("n_medium")
        return out

    def _fitn_of(self, label, chan):
        """The fitted constant-n of one trace's channel, or None."""
        fit = self._fits.get((self._dkey(label), chan))
        cn = ((fit or {}).get("models") or {}).get("constant_n") or {}
        for win in ("fine", "narrow", "wide", "full"):
            d = cn.get(win)
            if d and d.get("n_mean") is not None:
                return float(d["n_mean"])
        return None

    def _input_snapshot(self, label=None):
        """One pressure point's inputs, in Matthew's 'inputs' shape.

        nums, notch and fitn are his blocks, spelled his way, so a file this
        program writes reads in his and one his program wrote reads here.
        The rest -- the role glyphs, the solved values, the per-channel
        low-pass, the detection gates and the Sample fit mode -- are SPARTA's
        own, and his reader stores what it does not recognise and hands it
        back untouched.
        """
        label = self._label if label is None else label
        if self._dkey(label) is None:
            return {}
        mem = self._mem_state(label)
        notch = {}
        for chan in CHANNELS:
            cd = (mem.get("chan") or {}).get(chan)
            if cd is None:
                continue
            notch[chan] = {
                "user": [round(float(k), 4)
                         for k in (cd.get("user_centers") or [])],
                "desel": [float(k) for k in (cd.get("unticked") or [])],
                "removed": [float(k) for k in (cd.get("removed") or [])],
                "widths": {str(k): round(float(v), 4)
                           for k, v in (cd.get("widths") or {}).items()},
                "fund": cd.get("user_fundamental")}
        nums = {"n_sample": self.ns_v.get(),
                "n_medium": self.medium_n_v.get(),
                "d1_um": self.d1_v.get(),
                "t_um": self.t_v.get(),
                "d2_um": self.d2_v.get()}
        rec = self._record(label)
        if rec is not None and label == self._label:
            try:                       # the modelled indices, for his reader
                p = self._stack_params(rec)
                nums["n_diamond"] = "%g" % p["n_diamond"]
                nums["n_layer2"] = "%g" % p["n_layer2"]
                nums["n_medium"] = "%g" % p["n_medium"]
            except Exception:
                pass
        return {"nums": nums,
                "notch": notch,
                "fitn": {c: self._fitn_of(label, c) for c in CHANNELS},
                "roles": mem.get("roles") or {},
                "solved": mem.get("solved"),
                "lowpass": dict((c, bool(self.lp_on_v[c].get()))
                                for c in CHANNELS),
                # None when the box holds no usable cutoff, so a snapshot
                # never records a low-pass this point never had
                "lp_cutoff_um": dict((c, self._lp_cut_or_none(c))
                                     for c in CHANNELS),
                "lp_rolloff_um": dict((c, self._lp_edge(c)[1])
                                      for c in CHANNELS),
                "lp_edge_shape": dict((c, self._lp_edge(c)[0])
                                      for c in CHANNELS),
                "nt_min_um": _f(self.ntmin_v, 8.0),
                "nt_max_um": _f(self.ntmax_v, 300.0),
                "wl_min_nm": _f(self.wlmin_v, 600.0),
                "wl_max_nm": _f(self.wlmax_v, 800.0),
                "halfwidth_um": _f(self.hw_v, 3.0),
                "fit_mode": self.fitmode_v.get()}

    def _apply_input_snapshot(self, snap, label=None, seed=False):
        """Write one stored input snapshot back into the controls.

        `seed=True` marks a snapshot borrowed from an earlier point: it
        carries the numbers, the low-pass and the Sample fit mode across, and
        the notch list only into a channel that has none of its own.  The
        role glyphs and the solved values stay with the point that owns them.

        The detection gates travel in the file for the record and stay out of
        the controls: they gate the main plot's defringe as well, so one
        point's window is a series-wide decision.
        """
        if not isinstance(snap, dict):
            return False
        label = self._label if label is None else label
        if self._dkey(label) is None:
            return False
        skip = self._model_owned_nums()
        nums = snap.get("nums") or {}
        self._suspend = True
        try:
            for key, var in (("n_sample", self.ns_v),
                             ("n_medium", self.medium_n_v),
                             ("d1_um", self.d1_v), ("t_um", self.t_v),
                             ("d2_um", self.d2_v)):
                if key in skip or key not in nums:
                    continue
                try:
                    var.set("%g" % float(nums[key]))
                except (TypeError, ValueError):
                    var.set(str(nums[key]))
            lp_on = snap.get("lowpass") or {}
            lp_um = snap.get("lp_cutoff_um") or {}
            lp_roll = snap.get("lp_rolloff_um") or {}
            lp_shape = snap.get("lp_edge_shape") or {}
            for c in CHANNELS:
                if c in lp_on:
                    self.lp_on_v[c].set(bool(lp_on[c]))
                if c in lp_um:
                    if lp_um[c] is None:
                        self.lp_v[c].set("")     # the point had no cutoff
                    else:
                        try:
                            self.lp_v[c].set("%g" % float(lp_um[c]))
                        except (TypeError, ValueError):
                            pass
                if c in lp_roll:
                    try:
                        self.lp_roll_v[c].set("%g" % float(lp_roll[c]))
                    except (TypeError, ValueError):
                        pass
                if str(lp_shape.get(c)) in LP_EDGE_SHAPES:
                    self.lp_shape_v[c].set(str(lp_shape[c]))
                self._lp_last[c] = self.lp_v[c].get()
                self._lp_edge_last[c] = self._lp_edge(c)
            fm = snap.get("fit_mode")
            if fm in ("distinct", "shared"):
                self.fitmode_v.set(fm)
        except tk.TclError:
            return False
        finally:
            self._suspend = False
        for chan, ncfg in (snap.get("notch") or {}).items():
            if chan not in CHANNELS or not isinstance(ncfg, dict):
                continue
            ch = self._ch(chan, label)
            if ch is None:
                continue
            if seed and (ch["user_centers"] or ch["removed"]
                         or ch["unticked"] or ch["widths"]
                         or ch["user_fundamental"] is not None):
                continue               # this channel already has its own
            ch["user_centers"] = [float(k) for k in (ncfg.get("user") or [])]
            ch["unticked"] = set(float(k) for k in (ncfg.get("desel") or []))
            ch["removed"] = set(float(k) for k in (ncfg.get("removed") or []))
            wd = {}
            for ks, wv in (ncfg.get("widths") or {}).items():
                try:
                    wd[float(ks)] = float(wv)
                except (TypeError, ValueError):
                    continue
            ch["widths"] = wd
            uf = ncfg.get("fund")
            # Three states, his: None is auto, the FUND_NONE sentinel is
            # "no fundamental on this channel", a number is a pinned peak.
            # The sentinel is what his files carry and what our radio
            # column writes, so it has to survive the round trip whole.
            if isinstance(uf, str) and uf.strip().lower() == FUND_NONE:
                ch["user_fundamental"] = FUND_NONE
            else:
                try:
                    ch["user_fundamental"] = (float(uf) if uf is not None
                                              else None)
                except (TypeError, ValueError):
                    ch["user_fundamental"] = None
        if not seed:
            tr = self._tr(label)
            roles = snap.get("roles")
            if tr is not None and isinstance(roles, dict):
                for role in ROLES:
                    rv = roles.get(role)
                    tr["roles"][role] = (dict(rv) if isinstance(rv, dict)
                                         else None)
                    tr["gauss"][role] = None
                tr["gauss"]["_sample_pair"] = None
                tr["seeded"] = True
                sol = snap.get("solved")
                tr["solved"] = (dict(sol) if isinstance(sol, dict) else None)
        self._notch_sig = None
        return True

    @staticmethod
    def _inputs_for_json(inputs):
        """The per-point projection actually written to the continuity file:
        the series-wide material seed stripped out.  The writer and every
        'differs from the file' comparison share it, so a shape mismatch can
        never read as a difference (his _inputs_for_json, 9236)."""
        return {dk: {k: v for k, v in (snap or {}).items()
                     if k not in MATERIAL_KEYS}
                for dk, snap in (inputs or {}).items()}

    def _merged_input(self, dk):
        """One point's stored snapshot, over the fields of a foreign file we
        chose to keep.  A continuity file his program wrote carries blocks
        this one has no control for; they travel back out unchanged."""
        row = _deep(self._inputs_extra.get(dk) or {})
        row.update(_deep(self._inputs.get(dk) or {}))
        return row

    def _inputs_payload(self):
        return self._inputs_for_json(
            dict((dk, self._merged_input(dk)) for dk in self._inputs))

    @staticmethod
    def _nums_differ(a, b):
        """(key, was, now) for two nums payloads, compared as NUMBERS where
        both parse.  The spinboxes re-format their own text ('0.0' becomes
        '0' after a Lock In redistribution), and a raw string compare
        reported a change nobody made (his _nums_differ, 14400)."""
        out = []
        for k in sorted(set(a) | set(b)):
            va, vb = a.get(k), b.get(k)
            if va == vb:
                continue
            try:
                if abs(float(va) - float(vb)) <= NUM_EPS:
                    continue
            except (TypeError, ValueError):
                pass
            out.append((k, va, vb))
        return out

    def _committed_diff(self, label=None):
        """What this point holds that a record has not committed, in plain
        words.  One function decides AND explains, so the reasons a prompt
        lists can never disagree with the decision to raise it."""
        label = self._label if label is None else label
        dk = self._dkey(label)
        if dk is None:
            return []
        prev = self._inputs.get(dk)
        if prev is None:
            return ["this point is waiting for its first record"]
        cur = self._input_snapshot(label)
        skip = self._model_owned_nums()
        out = []
        for key, was, now in self._nums_differ(prev.get("nums") or {},
                                               cur.get("nums") or {}):
            if key in skip:
                continue
            out.append("%s: %s to %s" % (NUM_DISP.get(key, key), was, now))
        for keys, word in ((("lowpass", "lp_cutoff_um"), "the low-pass"),
                           (("lp_rolloff_um", "lp_edge_shape"),
                            "the low-pass edge"),
                           (("nt_min_um", "nt_max_um", "wl_min_nm",
                             "wl_max_nm", "halfwidth_um"),
                            "the detection gates"),
                           (("fit_mode",), "the Sample fit mode")):
            # A key the stored snapshot has never heard of is not a change:
            # a point committed by an older build carries no low-pass edge,
            # and reading its absence as an edit would raise a leave prompt
            # on every point of an existing session.
            if any(k in prev and prev.get(k) != cur.get(k) for k in keys):
                out.append("%s changed" % word)
        out.extend(self._dirty_items(label))
        return out

    def _live_inputs_differ(self):
        return bool(self._committed_diff())

    def _pt_key(self, pt):
        """The dataset key of one recorded point."""
        stem = (pt or {}).get("stem")
        if stem:
            return "stem:" + str(stem)
        lab = (pt or {}).get("label")
        return self._dkey(lab) if lab else None

    def _label_of_key(self, dk):
        """The display label behind a dataset key, for the prompts."""
        for r in self._records():
            if self._dkey(r.get("label")) == dk:
                return r.get("label")
        for pt in self._series:
            if self._pt_key(pt) == dk:
                return pt.get("label")
        return self._stem_from_key(dk)

    def _seed_from_preceding(self, dk):
        """(snapshot, source key) to open a not-yet-recorded point with.

        Matthew's order, within the ACTIVE series only (his 9244-9281): the
        nearest committed point EARLIER IN THE DROPDOWN at this same
        pressure, then the nearest LOWER pressure, then the nearest
        neighbour, then the most recent.  (None, None) leaves the cold start
        to the stack model.
        """
        if not self._inputs:
            return None, None
        order = self._ordered_recs()
        keys, press = [], {}
        for r in order:
            k = self._dkey(r.get("label"))
            keys.append(k)
            try:
                press[k] = (None if r.get("pressure_val") is None
                            else float(r["pressure_val"]))
            except (TypeError, ValueError):
                press[k] = None
        pr = press.get(dk)
        # Same-pressure siblings first: pressure alone cannot order two
        # spectra taken at ONE pressure, and the nearest-LOWER rule below is
        # strict, so such a point would cold-start even with a natural seed
        # one row above it.
        here = keys.index(dk) if dk in keys else -1
        if pr is not None and here > 0:
            for j in range(here - 1, -1, -1):
                q = keys[j]
                pj = press.get(q)
                if pj is None or abs(pj - pr) > 1e-6:
                    break
                if q in self._inputs:
                    return self._inputs[q], q
        cand = [(press.get(k), k) for k in self._inputs if k in press]
        if pr is not None:
            lower = [c for c in cand if c[0] is not None and c[0] < pr - 1e-6]
            if lower:
                q = max(lower, key=lambda c: c[0])[1]
                return self._inputs[q], q
            withp = [c for c in cand if c[0] is not None]
            if withp:
                q = min(withp, key=lambda c: abs(c[0] - pr))[1]
                return self._inputs[q], q
        if cand:
            q = cand[-1][1]
            return self._inputs[q], q
        return None, None

    def _stash_live(self):
        """Keep the live controls with the point that is on screen.

        The stack numbers are one set of boxes shared by the whole series,
        so a step to the next point and back would otherwise land on the
        committed values and drop an edit no record carries yet.
        """
        if not self._built or self._label is None:
            return
        dk = self._dkey()
        if dk is not None:
            self._live_inputs[dk] = self._input_snapshot()

    def _apply_point_inputs(self):
        """Open the current point on the state it was left in, on its own
        committed inputs, or on the nearest preceding point's."""
        if self._load_busy or not self._built:
            return False
        dk = self._dkey()
        if dk is None:
            return False
        snap = self._live_inputs.get(dk)
        if snap is None:
            snap = self._inputs.get(dk)
        if snap is not None:
            return self._apply_input_snapshot(snap)
        snap, src = self._seed_from_preceding(dk)
        if snap is None:
            return False               # the stack model opens a cold point
        if not self._apply_input_snapshot(snap, seed=True):
            return False
        self._seed_status("inputs", "inputs seeded from %s."
                          % self._label_of_key(src))
        return True

    # ---- the continuity file as the markers see it ------------------------
    def _invalidate_json_cache(self):
        """Force the next read of the continuity file to touch the disk.

        Called after our own writes: a rewrite that lands in the same
        filesystem tick at the same byte count would otherwise keep serving
        the pre-save parse, and the markers would stay stale until the next
        edit (his 14723-14727).
        """
        self._json_cache = {"key": None, "data": None}
        self._pcb_marks = None

    def _series_json_cached(self):
        """The folder's continuity file as a dict, or None.

        Re-parsed only when its (path, mtime, size) moves.  The dropdown
        markers ask for this on every redraw, so a re-read per frame is the
        one thing it may not cost (his _series_json_cached, 11319).
        """
        path = None
        for cand in self._series_read_paths():
            if os.path.isfile(cand):
                path = cand
                break
        if path is None:
            return None
        try:
            st = os.stat(path)
        except OSError:
            return None
        key = (path, st.st_mtime_ns, st.st_size)
        if self._json_cache.get("key") == key:
            return self._json_cache.get("data")
        data = None
        try:
            with open(path, encoding="utf-8") as f:
                data = json.load(f)
        except (OSError, ValueError):
            data = None                # a bad parse is cached against the
        self._json_cache = {"key": key, "data": data}   # same key
        return data

    def _point_status(self, dk, data=None):
        """One point against the folder's continuity file:

            'saved'    the file holds it, and memory matches
            'differs'  the file holds it, and memory has moved on -- or this
                       is the loaded point and it has edits no record carries
            'absent'   the file has nothing under this key

        `data` lets a caller asking about a whole dropdown read the file
        once instead of once per row.
        """
        if dk is None:
            return "absent"
        if data is None:
            data = self._series_json_cached()
        if not isinstance(data, dict):
            return "absent"
        jpts = data.get("points") or {}
        jins = data.get("inputs") or {}
        if dk not in jpts and dk not in jins:
            return "absent"
        if dk == self._dkey() and self._live_inputs_differ():
            return "differs"
        row = None
        for pt in self._series:
            if self._pt_key(pt) == dk:
                row = _deep(pt)
                break
        if row != jpts.get(dk):
            return "differs"
        mine = (self._inputs_for_json({dk: self._merged_input(dk)}).get(dk)
                if dk in self._inputs else None)
        if mine != jins.get(dk):
            return "differs"
        return "saved"

    @staticmethod
    def _plain_label(s):
        """A dropdown label with any status marker taken off -- the form the
        state is keyed by and a recorded row carries."""
        s = str(s or "")
        for m in PLABEL_MARKS:
            if s.endswith(m):
                return s[:-len(m)]
        return s

    def _relabel_pressure_cb(self):
        """Re-decorate the pressure dropdown with each point's marker.

        The values list is rewritten only when a marker actually moved:
        assigning it resets the widget's index and repaints the entry, which
        flickers while typing and can drop the highlighted row while the list
        is posted (his _relabel_pressure_cb, 13309).
        """
        cb = getattr(self, "_trace_cb", None)
        if cb is None or self._load_busy:
            return
        try:
            plain = [self._plain_label(v) for v in cb.cget("values")]
        except tk.TclError:
            return
        data = self._series_json_cached()
        marks = tuple(self._point_status(self._dkey(p), data=data)
                      for p in plain)
        vals = [p + (PLABEL_MARKS[0] if m == "saved"
                     else PLABEL_MARKS[1] if m == "differs" else "")
                for p, m in zip(plain, marks)]
        cur = self._plain_label(self.trace_v.get())
        want = vals[plain.index(cur)] if cur in plain else None
        if marks == self._pcb_marks:
            # nothing moved: at most re-assert the selection, which a pick
            # or a reordered list leaves holding the plain form
            if want is not None and want != self.trace_v.get():
                self.trace_v.set(want)
            return
        self._pcb_marks = marks
        try:
            cb.configure(values=vals)
        except tk.TclError:
            return
        # Re-assert the selection: the rewrite leaves the variable holding
        # the old decoration, which matches no entry, and the dropdown would
        # open with no row highlighted.  Writing the variable raises no
        # <<ComboboxSelected>>, so this cannot re-enter the pick handler.
        if want is not None:
            self.trace_v.set(want)

    def _series_diff(self):
        """WHY a save would change the continuity file, in plain words.

        The same relationship to the save prompt that _committed_diff has to
        the leave prompt: one function decides and explains (his _series_diff,
        14462).  Points are named by pressure, so an unexpected prompt can be
        traced to the point holding it.
        """
        out = []
        live = self._committed_diff()
        if live:
            out.append("%s: waiting for a record; %s%s"
                       % (self._label or "this point", "; ".join(live[:4]),
                          (" (+%d more)" % (len(live) - 4))
                          if len(live) > 4 else ""))
        if not (self._series or self._inputs):
            return out
        data = self._series_json_cached()
        mine = self._payload_points()
        if not isinstance(data, dict):
            out.append("%s is still to be written (%d recorded point(s))"
                       % (SERIES_FILE, len(mine)))
            return out
        jp = dict(data.get("points") or {})
        ji = dict(data.get("inputs") or {})
        added, changed, dropped = [], [], []
        for dk, row in mine.items():
            if dk not in jp:
                added.append(dk)
            elif row != jp.get(dk):
                changed.append(dk)
        for dk, row in self._inputs_payload().items():
            if dk not in mine and row != ji.get(dk):
                changed.append(dk)
        for dk in jp:
            if dk not in mine:
                dropped.append(dk)

        def _some(keys, words):
            seen, uniq = set(), []
            for k in keys:
                if k in seen:
                    continue
                seen.add(k)
                uniq.append(self._label_of_key(k))
            if not uniq:
                return
            out.append("%s: %s%s" % (words, ", ".join(uniq[:6]),
                                     (" (+%d more)" % (len(uniq) - 6))
                                     if len(uniq) > 6 else ""))
        _some(added, "recorded, and new to the file")
        _some(changed, "recorded again since the last save")
        _some(dropped, "dropped here, and still in the file")
        return out

    def _leave_guard(self):
        """Three-way guard before leaving a trace with unsaved changes.

        Returns True when it is safe to leave (saved or discarded), False when
        the answer was Stay.  The changes are itemised so the answer is never
        a guess; long lists are capped.
        """
        label = self._label
        if label is None:
            return True
        items = self._dirty_items(label)
        if not items:
            return True
        shown = items[:DIRTY_CAP]
        more = len(items) - len(shown)
        body = "\n".join("  • " + s for s in shown)
        if more > 0:
            body += "\n  …and %d more" % more
        ans = messagebox.askyesnocancel(
            "Fringe workbench",
            "%s holds unsaved changes:\n"
            "\n"
            "%s\n"
            "\n"
            "Yes: save, then leave\n"
            "No: leave them unsaved\n"
            "Cancel: stay here" % (label, body),
            parent=self.app.root)
        if ans is None:
            return False
        if ans:
            self._commit(label)
            self._log("Fringe: saved %d change(s) on %s." % (len(items),
                                                             label))
        else:
            self._restore(label)
            self._log("Fringe: discarded %d change(s) on %s." % (len(items),
                                                                 label))
        return True

    # ---- save / load ------------------------------------------------------
    def save_state(self):
        """The workbench's whole session payload.  Additive: app.py stores it
        under one new key and never touches the existing schema."""
        # Reading the payload means reading the control variables, so an
        # unbuilt workbench has to build first (idempotent). app.py skips
        # calling this at all when the panel was never opened, so the
        # common path still never pays for the build.
        self.build()
        self._commit()
        return {
            "version": 2,
            "view": "fringe" if self._active else "plot",
            "label": self._label,
            "stack": {"medium": self.medium_v.get(),
                      "medium_n": self.medium_n_v.get(),
                      "layer2_on": bool(self.layer2_on_v.get()),
                      "layer2": self.layer2_v.get(),
                      "diamond": self.diamond_v.get(),
                      "n_sample": _f(self.ns_v, 1.6),
                      "d1": _f(self.d1_v, 0.0), "t": _f(self.t_v, 0.0),
                      "d2": _f(self.d2_v, 0.0),
                      "lock_total": bool(self.lock_v.get()),
                      "total": _f(self.total_v, 0.0),
                      "fine_step": bool(self.fine_v.get()),
                      # R15-D: the free-text names. A payload without them
                      # loads with the model names, as it always did.
                      "medium_name": (self.name_med_v.get() or "").strip(),
                      "sample_name": (self.name_samp_v.get() or "").strip(),
                      "layer2_name": (self.name_l2_v.get() or "").strip()},
            "detect": {"wl_min": _f(self.wlmin_v, 600.0),
                       "wl_max": _f(self.wlmax_v, 800.0),
                       "nt_min": _f(self.ntmin_v, 8.0),
                       "nt_max": _f(self.ntmax_v, 300.0),
                       "pmax": _f(self.pmax_v, 1e-4),
                       "tol": _f(self.tol_v, 0.15)},
            "notch": {"halfwidth": _f(self.hw_v, 3.0),
                      # R7: per channel.  A pre-R7 payload holds a bool
                      # here instead; load_state migrates it.
                      "lowpass": dict((c, [bool(self.lp_on_v[c].get()),
                                           self._lp_cut_or_none(c)])
                                      for c in CHANNELS),
                      # R15-D: the edge of that low-pass, kept in its own
                      # block so a payload written before it still reads
                      "lp_edge": dict((c, list(self._lp_edge(c)))
                                      for c in CHANNELS),
                      "fine": bool(self.notchfine_v.get())},
            "view_opts": {"y_lo": str(self.ylo_v.get()).strip(),
                          "y_hi": str(self.yhi_v.get()).strip(),
                          "stem_cmap": self.cmap_v.get(),
                          "stem_skip_faint": bool(self.skipfaint_v.get())},
            "fit_mode": self.fitmode_v.get(),
            # version 2: both maps are keyed by "stem:<stem>", not by the
            # display label. load_state still reads a version-1 payload.
            "traces": dict(self._disk),
            "inputs": _deep(self._inputs),
            "series": list(self._series),
            # c keys -- the series level. Additive: a payload written by a
            # build without them still loads, and these are all defaulted.
            "msv_errors": bool(self.msv_v.get()),
            "res_models": [k for k, v in self._res_model_v.items()
                           if v.get()] or list(
                               self.settings.get("fr_res_models") or []),
            "res_layer2": [k for k, v in self._res_layer2_v.items()
                           if v.get()] or list(
                               self.settings.get("fr_res_layer2") or []),
            "eos": {"selections": self._eos_selections(),
                    # his fourth field: WHICH curve the anchor was read
                    # off.  Ours anchors on the recorded point, so it writes
                    # his recorded key -- and a value read out of his file is
                    # handed straight back, so a round trip through this
                    # program never drops what it meant.
                    "anchors": [{"panel": p, "eos": e, "dk": v,
                                 "curve": self._res_anchor_curve.get(
                                     (p, e), RES_RECORDED)}
                                for (p, e), v in sorted(
                                    self._res_anchor.items())]}}

    def load_state(self, d):
        if not isinstance(d, dict):
            return
        self.build()
        self._suspend = True
        try:
            st = d.get("stack") or {}
            for var, key, dflt in (
                    (self.medium_v, "medium", "Other"),
                    (self.medium_n_v, "medium_n", "1.2"),
                    (self.layer2_v, "layer2", "KCl"),
                    (self.diamond_v, "diamond", "constant")):
                var.set(st.get(key, dflt))
            self.layer2_on_v.set(bool(st.get("layer2_on", False)))
            self.lock_v.set(bool(st.get("lock_total", False)))
            self.fine_v.set(bool(st.get("fine_step", False)))
            for var, key, dflt in ((self.ns_v, "n_sample", 1.5),
                                   (self.d1_v, "d1", 0.0),
                                   (self.t_v, "t", 20.0),
                                   (self.d2_v, "d2", 0.0),
                                   (self.total_v, "total", 0.0)):
                var.set("%g" % float(st.get(key, dflt)))
            # the free-text names; a payload without them keeps the models'
            for var, key in ((self.name_med_v, "medium_name"),
                             (self.name_samp_v, "sample_name"),
                             (self.name_l2_v, "layer2_name")):
                if key in st:
                    var.set(str(st.get(key) or ""))
            dt = d.get("detect") or {}
            for var, key, dflt in ((self.wlmin_v, "wl_min", 600.0),
                                   (self.wlmax_v, "wl_max", 800.0),
                                   (self.ntmin_v, "nt_min", 8.0),
                                   (self.ntmax_v, "nt_max", 300.0),
                                   (self.pmax_v, "pmax", 1e-4),
                                   (self.tol_v, "tol", 0.15)):
                var.set("%g" % float(dt.get(key, dflt)))
            nc = d.get("notch") or {}
            self.hw_v.set("%g" % float(nc.get("halfwidth", 3.0)))
            _lpd = nc.get("lowpass")
            if isinstance(_lpd, dict):        # R7 payload: per channel
                for c in CHANNELS:
                    _pair = _lpd.get(c)
                    if (isinstance(_pair, (list, tuple))
                            and len(_pair) == 2):
                        self.lp_on_v[c].set(bool(_pair[0]))
                        self.lp_v[c].set("" if _pair[1] is None
                                         else "%g" % float(_pair[1]))
            else:                             # pre-R7 scalar payload
                for c in CHANNELS:
                    self.lp_on_v[c].set(bool(True if _lpd is None
                                             else _lpd))
                    self.lp_v[c].set(
                        "%g" % float(nc.get("lp_cutoff", 15.0)))
            _edge = nc.get("lp_edge")
            if isinstance(_edge, dict):       # R15-D payload: shape + width
                for c in CHANNELS:
                    _pair = _edge.get(c)
                    if not (isinstance(_pair, (list, tuple))
                            and len(_pair) == 2):
                        continue
                    if str(_pair[0]) in LP_EDGE_SHAPES:
                        self.lp_shape_v[c].set(str(_pair[0]))
                    try:
                        self.lp_roll_v[c].set("%g" % float(_pair[1]))
                    except (TypeError, ValueError):
                        pass
            self.notchfine_v.set(bool(nc.get("fine", False)))
            _vo = d.get("view_opts") or {}
            self.ylo_v.set(str(_vo.get("y_lo", "")))
            self.yhi_v.set(str(_vo.get("y_hi", "")))
            if _vo.get("stem_cmap"):
                self.cmap_v.set(str(_vo["stem_cmap"]))
            self.skipfaint_v.set(bool(_vo.get("stem_skip_faint", False)))
            self.fitmode_v.set(d.get("fit_mode", "distinct"))
            # A version-1 payload keyed its traces by the display label.
            # The stem those labels belong to can only be read off the
            # records, which a session load does not have yet (the app says
            # "click Run to re-process"), so legacy rows wait in
            # _disk_legacy and are adopted by _adopt_legacy_disk() the
            # moment their record turns up.
            self._disk, self._disk_legacy = {}, {}
            for key, td in (d.get("traces") or {}).items():
                if str(key).startswith("stem:"):
                    self._disk[key] = td
                else:
                    self._disk_legacy[key] = td
            for dk, td in self._disk.items():
                self._apply_trace_state(dk, td)
            self._inputs, self._inputs_extra = {}, {}
            self._live_inputs = {}
            for key, snap in (d.get("inputs") or {}).items():
                if isinstance(snap, dict):
                    self._inputs[key] = _deep(snap)
            self._series = list(d.get("series") or [])
            # c keys
            self.msv_v.set(bool(d.get("msv_errors", False)))
            self.settings["fr_msv_errors"] = bool(self.msv_v.get())
            if d.get("res_models") is not None:
                self.settings["fr_res_models"] = list(d["res_models"])
            if d.get("res_layer2") is not None:
                self.settings["fr_res_layer2"] = list(d["res_layer2"])
            self._msv_cache.clear()
        except (TypeError, ValueError) as exc:
            self._log("Fringe: session payload partly unreadable (%s)." % exc)
        finally:
            self._suspend = False
        self._apply_eos_state(d.get("eos") or {})
        self._sync_steps()
        self._on_layer2()
        self._on_lock()
        self._sync_medium_row()
        self._relabel_stack()
        self._sync_anvil_n()
        self._invalidate_json_cache()
        want = self._plain_label(d.get("label"))
        self._load_busy = True
        try:
            self.on_trace_change(want if want else None)
        finally:
            self._load_busy = False
        self._adopt_legacy_disk()
        self._refresh_state_indicators()
        if d.get("view") == "fringe":
            self.activate()

    # =======================================================================
    # series continuity on disk
    # =======================================================================
    def _program_roots(self):
        """Every folder that counts as "inside the program".

        A frozen build unpacks its data under sys._MEIPASS and a onedir
        build keeps a copy beside the executable, so all three are checked
        rather than betting on one packaging layout.
        """
        out = [os.path.dirname(os.path.abspath(__file__))]
        mei = getattr(sys, "_MEIPASS", None)
        if mei:
            out.append(mei)
        if getattr(sys, "frozen", False):
            out.append(os.path.dirname(os.path.abspath(sys.executable)))
        return out

    def _under_program(self, path):
        """True when `path` sits inside the program's own folder.

        The bundled demo data does, and so does everything else a packaged
        install ships.  Writing a reader's results in there pollutes the
        installation, and under Program Files it is simply refused.
        """
        try:
            p = os.path.normcase(os.path.abspath(path))
        except (TypeError, ValueError):
            return False
        for root in self._program_roots():
            r = os.path.normcase(os.path.abspath(root))
            if p == r or p.startswith(r + os.sep):
                return True
        return False

    def _writable(self, folder):
        """Can a file actually be created here?  Remembered per folder.

        os.access is not to be trusted on Windows shares, so the only
        honest test is to write something and take it away again; the
        answer is cached so the disk indicator does not touch the disk on
        every redraw.
        """
        try:
            key = os.path.normcase(os.path.abspath(folder))
        except (TypeError, ValueError):
            return False
        if key in self._wr_cache:
            return self._wr_cache[key]
        probe = os.path.join(folder, ".sparta-write-test-%d" % os.getpid())
        ok = True
        try:
            with open(probe, "w") as f:
                f.write("")
        except OSError:
            ok = False
        else:
            try:
                os.remove(probe)
            except OSError:
                pass
        self._wr_cache[key] = ok
        return ok

    def _input_folder(self):
        loc = getattr(self, "_local", None)
        if loc and os.path.isdir(loc.get("folder") or ""):
            return loc["folder"]
        var = getattr(self.app, "in_var", None)
        try:
            p = (var.get() or "").strip() if var is not None else ""
        except tk.TclError:
            p = ""
        return p if p and os.path.isdir(p) else None

    def _series_dest(self):
        """(folder, why) for series_continuity.json.

        Matthew writes it beside the spectra and so do we -- that shared
        convention is what lets either program pick the other's file up.
        Two folders cannot take it: the bundled demo data, which lives
        inside the program (and on a packaged install that is Program
        Files), and any read-only beamline share.  Both hand the job to the
        run's output folder, which the reader chose and which is writable
        by definition.  `why` is the sentence the status line owes them
        when that happens.
        """
        src = self._input_folder()
        var = getattr(self.app, "out_var", None)
        try:
            out = (var.get() or "").strip() if var is not None else ""
        except tk.TclError:
            out = ""
        out = out if out and os.path.isdir(out) else None
        if src is None:
            return out, None
        why = None
        if self._under_program(src):
            why = ("the data folder lives inside the program, so this went "
                   "to your output folder")
        elif not self._writable(src):
            why = ("the data folder is read-only, so this went to your "
                   "output folder")
        if (why and out and self._writable(out)
                and os.path.normcase(out) != os.path.normcase(src)):
            return out, why
        return src, None

    def _series_folder(self):
        """Where series_continuity.json is written."""
        return self._series_dest()[0]

    def _series_read_paths(self):
        """Every series_continuity.json worth looking in, best first.

        The destination is where we write; the input folder is where
        Matthew's program writes.  A file his batch mode left beside the
        data still loads even when our own saves are going elsewhere.
        """
        out, seen = [], set()
        for folder in (self._series_folder(), self._input_folder()):
            if not folder:
                continue
            key = os.path.normcase(os.path.abspath(folder))
            if key in seen:
                continue
            seen.add(key)
            out.append(os.path.join(folder, SERIES_FILE))
        return out

    def series_path(self):
        folder = self._series_folder()
        return os.path.join(folder, SERIES_FILE) if folder else None

    def _series_label(self):
        # a Session-loaded folder IS the series: name it after the folder,
        # never after wherever the continuity file happens to be written
        loc = getattr(self, "_local", None)
        if loc and loc.get("folder"):
            return os.path.basename(os.path.normpath(loc["folder"]))
        rec = self._record() or (self._records() or [{}])[0]
        dac, samp = rec.get("dac"), rec.get("sample")
        if dac and samp:
            return "%s_%s" % (dac, samp)
        folder = self._series_folder()
        return os.path.basename(os.path.normpath(folder)) if folder else ""

    def _payload_points(self):
        """The recorded points keyed by their identity, his way: one entry
        per "stem:<stem>".  The label used to be the key, which collapsed a
        compression/decompression pair -- and two series' 20 GPa points --
        into one slot."""
        points = {}
        for pt in self._series:
            key = self._pt_key(pt) or str(pt.get("label"))
            points[key] = _deep(pt)
        return points

    def _series_payload(self):
        """The series as Matthew's fft_gui_series/v2 writer shapes it.

        Same top-level fields, same meanings: a schema string, the series
        label, the series-wide materials SEED, the EoS overlay state, the
        recorded points keyed by their identity, and the per-point inputs
        with the material keys stripped (two copies of the seed could
        disagree).  SPARTA's own point rows travel verbatim inside 'points',
        which is what makes a round trip lossless.

        The inputs block carries what each point was recorded WITH -- its
        numbers, its notch list, its role glyphs -- rather than one copy of
        the live controls repeated per point, which is what a reload needs
        to put the series back the way it was left.
        """
        # his fourth field rides on the SERIES file too (his 14712):
        # save_state carried it, this writer dropped it, so a series
        # round trip lost which curve the anchor was read off.
        anchors = [{"panel": p, "eos": e, "dk": v,
                    "curve": self._res_anchor_curve.get(
                        (p, e), RES_RECORDED)}
                   for (p, e), v in sorted(self._res_anchor.items())]
        return {"schema": SERIES_SCHEMA,
                "series_label": self._series_label(),
                "written_by": "SPARTA fringe workbench",
                # The names block is the series-wide seed: what the three
                # layers are CALLED, once for the whole folder, so the rows
                # and the schematic read the same on every point of it.
                "materials": {"names": {"medium": self._material_names()[0],
                                        "sample": self._material_names()[1],
                                        "layer2": self._material_names()[2],
                                        "anvil": "diamond"},
                              "layer2_model": self.layer2_v.get(),
                              "layer2": bool(self.layer2_on_v.get()),
                              "medium_model": self.medium_v.get(),
                              "diamond_model": self.diamond_v.get(),
                              # his rect_fit_mode: written by his GUI and
                              # dropped by his own reader (an upstream gap
                              # reported with this round). Both directions
                              # here.
                              "rect_fit_mode": FIT_MODE_RECT.get(
                                  self.fitmode_v.get(), "peak")},
                "eos": {"selections": self._eos_selections(),
                        "anchors": anchors},
                "points": self._payload_points(),
                "inputs": self._inputs_payload()}

    def save_series(self):
        """Write series_continuity.json where it can actually go, plus a
        stamped copy.

        The stamped copy is the cheap insurance the state discipline asks
        for: the canonical file is overwritten every save, so without it a
        mistaken save over a good series is unrecoverable.  Both names and
        the folder they landed in go in the status line and the log -- a
        file written without saying where is a file the reader has to go
        hunting for, and the timestamped copy used not to be mentioned at
        all.
        """
        folder, why = self._series_dest()
        if folder is None:
            self._status("pick an input or output folder first.", warn=True)
            return None
        # a point's committed INPUTS are worth a file of their own: his
        # writer stores points and inputs side by side, and a series can
        # hold settled inputs for a pressure whose solve is still in hand
        if not (self._series or self._inputs):
            self._status("record a point first.", warn=True)
            return None
        path = os.path.join(folder, SERIES_FILE)
        payload = self._series_payload()
        stamp = time.strftime("%Y%m%d-%H%M%S")
        copy = os.path.join(folder, SERIES_STAMP % stamp)
        try:
            for target in (path, copy):
                with open(target, "w", encoding="utf-8") as f:
                    json.dump(payload, f, indent=2)
        except OSError as exc:
            self._status("writing the series failed: %s" % exc, warn=True)
            return None
        # His save writes a single-point snapshot too: session_<stamp>.json
        # holds THIS point's inputs, its notch config and the spectrum it
        # belongs to (defringe_dac 14830-14853).  His Load session opens one
        # by name, so ours writes one his reader can open -- and Load session
        # file below reads one his writer left.
        snap_path = os.path.join(folder,
                                 SESSION_STAMP % stamp.replace("-", "_"))
        snap = self._input_snapshot()
        if snap:
            snap = dict(snap)
            rec = self._record()
            snap["measured_path"] = str((rec or {}).get("path") or "")
            try:
                with open(snap_path, "w", encoding="utf-8") as f:
                    json.dump(snap, f, indent=2)
            except OSError as exc:
                snap_path = None
                self._log("Fringe: the point snapshot was not written: %s"
                          % exc)
        else:
            snap_path = None
        self._series_disk = payload
        self._series_path = path
        self._invalidate_json_cache()
        self._log("Fringe: wrote %d series point(s) -> %s"
                  % (len(self._series), path))
        self._log("  . timestamped copy: " + copy)
        if snap_path:
            self._log("  . point snapshot: " + snap_path)
        if why:
            self._log("  . " + why + ".")
        fn = getattr(self.app, "_provenance", None)
        if callable(fn):
            try:
                fn(path, "series_continuity",
                   {"schema": SERIES_SCHEMA, "n_points": len(self._series),
                    "series_label": payload["series_label"]},
                   files=[path, copy])
            except Exception:
                pass
        self._status("series saved: %d point(s) in %s, with the timestamped "
                     "copy %s%s beside it%s."
                     % (len(self._series), path, os.path.basename(copy),
                        (" and " + os.path.basename(snap_path)) if snap_path
                        else "",
                        (" (%s)" % why) if why else ""))
        self._refresh_state_indicators()
        return path

    def load_series(self, path=None):
        """Read series_continuity.json back in.

        Best-effort, exactly like Matthew's reader: unknown keys are kept,
        missing ones tolerated, and a bad file logs and changes nothing.  A
        point whose trace is already recorded in memory is REPLACED, so the
        file is the authority for what it carries and memory keeps the rest.
        """
        # The workbench is built on first use (app.py's _init_fringe leaves
        # it unbuilt), and this method ends by writing the stack rows and
        # the medium row, so it has to make sure they exist -- the same
        # thing load_state() does, for the same reason. build() is
        # idempotent.
        self.build()
        if path is None:
            for cand in self._series_read_paths():
                if os.path.isfile(cand):
                    path = cand
                    break
        if path is None:
            self._status("Save series writes the first %s."
                         % SERIES_FILE, warn=True)
            return 0
        try:
            with open(path, encoding="utf-8") as f:
                data = json.load(f)
        except (OSError, ValueError) as exc:
            self._status("could not read %s (%s)." % (SERIES_FILE, exc),
                         warn=True)
            return 0
        pts = data.get("points") or {}
        if not isinstance(pts, dict):
            self._status("reading points from %s failed." % SERIES_FILE,
                         warn=True)
            return 0
        incoming = []
        for key, row in pts.items():
            if not isinstance(row, dict):
                continue
            row = _deep(row)          # never share a nested dict with `data`
            row.setdefault("label", key)
            # A file written before the keys moved to stems put the label in
            # the key slot; the stem is recovered from the record it names,
            # so its point still lines up with the dropdown.
            if not row.get("stem"):
                if str(key).startswith("stem:"):
                    row["stem"] = self._stem_from_key(key)
                elif self._record(row["label"]) is not None:
                    row["stem"] = self._stem_of(row["label"])
            incoming.append(row)
        keep = {self._pt_key(p) for p in incoming}
        self._series = [q for q in self._series
                        if self._pt_key(q) not in keep]
        self._series.extend(incoming)
        self._series.sort(key=lambda q: (q.get("branch") or "C",
                                         q.get("pressure") or 0.0))
        # Per-point inputs, read back. Fields this build has no control for
        # are kept aside and travel back out on the next save, so a file his
        # program wrote survives a round trip through this one.
        self._load_busy = True
        try:
            # the file is the authority for what it carries
            self._live_inputs.clear()
            ins = data.get("inputs")
            if isinstance(ins, dict):
                for key, snap in ins.items():
                    if not isinstance(snap, dict):
                        continue
                    snap = _deep(snap)
                    extra = {k: v for k, v in snap.items()
                             if k not in INPUT_KEYS and k not in MATERIAL_KEYS}
                    if extra:
                        self._inputs_extra[key] = extra
                    self._inputs[key] = {k: v for k, v in snap.items()
                                         if k not in extra}
            mats = data.get("materials") or {}
            self._suspend = True
            try:
                if mats.get("medium_model") in MEDIUM_CHOICES:
                    self.medium_v.set(mats["medium_model"])
                if mats.get("layer2_model"):
                    self.layer2_v.set(mats["layer2_model"])
                if "layer2" in mats:
                    self.layer2_on_v.set(bool(mats["layer2"]))
                if mats.get("diamond_model") in DIAMOND_MODELS:
                    self.diamond_v.set(mats["diamond_model"])
                # rect_fit_mode: his writer stores it and his reader drops
                # it, so a Distinct/Shared choice made in his GUI came back
                # as Distinct. Read here.
                _rfm = RECT_FIT_MODES.get(mats.get("rect_fit_mode"))
                if _rfm:
                    self.fitmode_v.set(_rfm)
                # the free-text names, series-wide. A name equal to the
                # model's own is left blank, so the box keeps following the
                # dropdown instead of freezing on today's answer.
                _nm = mats.get("names") or {}
                # the defaults come off the MODELS just read, never off the
                # boxes, which may still hold the last series' names
                _dm, _ds, _dl = self._default_material_names()
                for _var, _key, _dflt in (
                        (self.name_med_v, "medium", _dm),
                        (self.name_samp_v, "sample", _ds),
                        (self.name_l2_v, "layer2", _dl)):
                    _val = str(_nm.get(_key) or "").strip()
                    if _val:
                        _var.set("" if _val == _dflt else _val)
            finally:
                self._suspend = False
        finally:
            self._load_busy = False
        self._apply_eos_state(data.get("eos") or {})
        self._series_disk = data
        self._series_path = path
        self._msv_cache.clear()
        self._log("Fringe: read %d series point(s) <- %s"
                  % (len(incoming), path))
        self._status("loaded %d point(s) and %d stored input set(s) from %s."
                     % (len(incoming), len(self._inputs), path))
        self._on_layer2()
        self._sync_medium_row()
        self._relabel_stack()
        self._sync_anvil_n()
        self._apply_point_inputs()
        self._notch_sig = None
        self._refresh_state_indicators()
        self._res_refresh()
        self._request_redraw(now=True)
        return len(incoming)

    def load_session_file(self, path=None):
        """Open a saved session file by name -- his shape or ours.

        His `_load_session` (defringe_dac 14883-14921) opens ANY session
        JSON through a dialog, re-loads the spectrum it names and re-applies
        the snapshot.  A series_continuity.json picked here is read as one
        too, so one entry answers for both files this program writes and for
        both files his does.  Inputs still apply when the named spectrum is
        not loaded, as his do.
        """
        self.build()
        if path is None:
            folder = self._series_folder() or self._input_folder()
            path = filedialog.askopenfilename(
                title="Open a saved session file",
                initialdir=folder or None,
                filetypes=[("Session JSON", "*.json"),
                           ("All files", "*.*")],
                parent=self.app.root)
            if not path:
                return 0
        try:
            with open(path, encoding="utf-8") as f:
                data = json.load(f)
        except (OSError, ValueError) as exc:
            self._status("could not read %s (%s)."
                         % (os.path.basename(str(path)), exc), warn=True)
            return 0
        if not isinstance(data, dict):
            self._status("that file holds no saved session.", warn=True)
            return 0
        # a continuity file names its points; a snapshot names one spectrum
        if isinstance(data.get("points"), dict) or "series_label" in data:
            return self.load_series(path=path)
        note = ""
        mp = str(data.get("measured_path") or "")
        if mp:
            stem = os.path.splitext(os.path.basename(mp))[0]
            want = None
            for r in self._records():
                if r.get("stem") == stem:
                    want = r.get("label")
                    break
            if want is None:
                note = ("; its spectrum is not loaded, so the inputs land "
                        "on the point on screen")
            elif want != self._label:
                self.on_trace_change(want)
        if not self._apply_input_snapshot(data, seed=True):
            self._status("that file holds no session inputs.", warn=True)
            return 0
        self._notch_sig = None
        self._refresh_state_indicators()
        self._request_redraw(now=True)
        self._log("Fringe: read a saved point <- %s" % path)
        self._status("loaded the saved point from %s%s."
                     % (os.path.basename(str(path)), note))
        return 1

    def _series_state(self):
        """(indicator, words) for the series against its file on disk."""
        path = self.series_path()
        if path is None or not os.path.isfile(path):
            return (IND_NONE, "not written out yet")
        disk = self._series_disk
        if disk is None or self._series_path != path:
            return (IND_DIRTY, "a file exists here, unread this session")
        mine = self._series_payload()["points"]
        theirs = disk.get("points") or {}
        if mine == theirs:
            return (IND_SAVED, "%s holds these %d point(s)"
                    % (SERIES_FILE, len(mine)))
        n = len(set(mine) ^ set(theirs)) or sum(
            1 for k in mine if mine[k] != theirs.get(k))
        return (IND_DIRTY, "%d point(s) differ from the file" % n)

    def _refresh_series_disk(self):
        lab = getattr(self, "_series_disk_lbl", None)
        if lab is None:
            return
        mark, txt = self._series_state()
        try:
            lab.configure(text="%s  %s" % (mark, txt))
        except tk.TclError:
            pass
        self._show_if_text(lab, txt)

    # ---- notch_overrides.csv ---------------------------------------------
    def _stem_of(self, label):
        """The batch pipeline's file stem for one trace.

        {DAC}_{sample}_{value}, lower case -- the same stem
        engine.write_absorbance_csv builds its file name from (minus the
        branch letter and the _absorbance suffix), so a batch run over
        SPARTA's own output matches these rows.
        """
        rec = self._record(label)
        if rec is None:
            return str(label)
        if rec.get("stem"):          # Session-loaded: the file's own stem
            return rec["stem"]
        return ("%s_%s_%s" % (rec.get("dac", ""), rec.get("sample", ""),
                              rec.get("pressure_str", ""))).lower()

    @staticmethod
    def _stem_from_key(dk):
        """The file stem inside a dataset key."""
        dk = str(dk or "")
        return dk[5:] if dk.startswith("stem:") else dk

    def notch_override_rows(self):
        """[(stem, channel, nt_um, is_fundamental, halfwidth_um)] for every
        trace that has notches, ASCENDING within each group.

        His writer sorts the centres on the way out (`for c in
        sorted(_active_centers(ch))`, defringe_dac 15003), whatever order
        they were picked in.  Pure: the writer below and the tests share
        it."""
        # reads hw_v for the default half-width, so the controls have to
        # exist (the workbench builds on first use); build() is idempotent
        self.build()
        rows = []
        # the state is already filed under "stem:<stem>", so the CSV's stem
        # column is the key with its prefix taken off
        for dk in sorted(set(list(self._trace) + [k[0] for k
                                                  in self._chan])):
            stem = self._stem_from_key(dk)
            for chan in CHANNELS:
                ch = self._chan.get((dk, chan))
                if not ch:
                    continue
                fund = (ch["user_fundamental"] if ch["user_fundamental"]
                        is not None else (ch["default_centers"][0]
                                          if ch["default_centers"] else None))
                keys = []
                for k in list(ch["default_centers"]) + list(ch["user_centers"]):
                    if k in ch["removed"] or k in ch["unticked"] or k in keys:
                        continue
                    keys.append(k)
                for k in sorted(keys):          # his file order
                    rows.append((stem, chan, round(float(k), 4),
                                 int(k == fund),
                                 round(float(ch["widths"].get(
                                     k, _f(self.hw_v, 3.0))), 2)))
        return rows

    NOTCH_HEAD = ["stem", "channel", "nt_um", "is_fundamental",
                  "halfwidth_um"]

    def _notch_file_merge(self, path, mine):
        """The rows already in `path` that this write must not touch.

        His `_export_notches` (defringe_dac 14990-14997) reads the file that
        is there and drops only the rows whose `stem` is the spectrum he is
        about to write; everything else survives.  Returns (header, kept) --
        the header the file already had, so a file written by his GUI or by
        a batch run keeps its own column order.
        """
        import csv
        head = list(self.NOTCH_HEAD)
        if not path or not os.path.isfile(path):
            return head, []
        try:
            with open(path, "r", encoding="utf-8", newline="") as f:
                old = [r for r in csv.reader(f) if r]
        except (OSError, csv.Error, UnicodeDecodeError):
            return head, []
        if not old:
            return head, []
        body = old
        if old[0] and str(old[0][0]).strip().lower() == "stem":
            head, body = old[0], old[1:]
        return head, [r for r in body if str(r[0]) not in mine]

    def export_notch_overrides(self, path=None):
        """Merge this session's notches into notch_overrides.csv.

        His writer goes to the FIXED path beside the data with no dialog, and
        MERGES: the rows for the spectra it is writing are replaced, every
        other row is kept.  Ours wrote every loaded trace over the whole
        file through a Save-As box, so a row his GUI or a batch run had left
        for a spectrum this session never opened was lost.

        Columns, in order: stem, channel, nt_um, is_fundamental,
        halfwidth_um.  load_notch_overrides reads that verbatim, so a batch
        re-run notches every spectrum where this session did.
        """
        import csv
        rows = self.notch_override_rows()
        if not rows:
            self._status("pick a notch first.",
                         warn=True)
            return None
        if path is None:
            folder = self._series_folder()
            if not folder:
                self._status("pick a data folder first.", warn=True)
                return None
            path = os.path.join(folder, NOTCH_FILE)
        mine = set(str(r[0]) for r in rows)
        head, kept = self._notch_file_merge(path, mine)
        try:
            d = os.path.dirname(path)
            if d and not os.path.isdir(d):
                os.makedirs(d)
            tmp = path + ".tmp"
            with open(tmp, "w", encoding="utf-8", newline="") as f:
                w = csv.writer(f)
                w.writerow(head)
                w.writerows(kept)
                for stem, chan, nt, fund, hw in rows:
                    w.writerow([stem, chan, "%.4f" % nt, "%d" % fund,
                                "%.2f" % hw])
            os.replace(tmp, path)
        except OSError as exc:
            self._status("writing the notches file failed: %s" % exc,
                         warn=True)
            return None
        lab = getattr(self, "_notch_file_lbl", None)
        if lab is not None:
            try:
                lab.configure(text="%d row(s) -> %s"
                                   % (len(rows) + len(kept),
                                      os.path.basename(path)))
            except tk.TclError:
                pass
            self._show_if_text(lab, "x")
        self._log("Fringe: wrote %d notch override row(s), kept %d -> %s"
                  % (len(rows), len(kept), path))
        fn = getattr(self.app, "_provenance", None)
        if callable(fn):
            try:
                fn(path, "notch_overrides",
                   {"n_rows": len(rows) + len(kept),
                    "n_written": len(rows), "n_kept": len(kept),
                    "n_traces": len(mine),
                    "halfwidth_convention": "absolute +/- um of n*t"},
                   files=[path])
            except Exception:
                pass
        self._status("wrote %d notch override row(s); kept %d for other "
                     "spectra." % (len(rows), len(kept)))
        return path

    # =======================================================================
    # multiscale-variance error bars
    # =======================================================================
    def _on_msv(self):
        self.settings["fr_msv_errors"] = bool(self.msv_v.get())
        if not self.msv_v.get():
            self._status("error bars off.")
        self._res_refresh()

    def _msv_sigma(self, label):
        """1 sigma on the sample channel's n*t (um) for one recorded point.

        Computed lazily -- it costs about 35 ms a point -- and cached per
        trace.  NOTE for constant_n the n*t variance lives in
        param_variance['nt'], NOT in derived_variance; msv_trend_summary
        already looks in the right place for each name, which is why the
        summary is used here rather than the raw dict.  The reported sigma
        is the LARGEST across the swept window widths: the multiscale point
        is that an estimate you cannot reproduce at some scale is not a
        number you may quote a tighter error on.

        THE SIGNAL (drift #2, his 16487-16505): the full-span notch-baseline
        pair wn_u_full / norm_u_full, masked to the config's full window, is
        what he sweeps.  The narrow detrended pair this used to pass spans
        4167 cm^-1 instead of 11000, so the 4000 and 5000 cm^-1 window widths
        yielded fewer than two windows and were dropped, and the quoted sigma
        came out of the surviving short scales alone -- systematically wider
        than his, on a different normalisation.
        """
        dk = self._dkey(label)
        if dk in self._msv_cache:
            return self._msv_cache[dk]
        self._msv_cache[dk] = None
        keep, self._label = self._label, label
        try:
            c = self._compute("Sample")
        finally:
            self._label = keep
        fi = (c or {}).get("fft_info")
        if not fi or "wn_u_full" not in fi or "norm_u_full" not in fi:
            return None
        try:
            import fringe_msv
            cfg = c["cfg"]
            wn = np.asarray(fi["wn_u_full"], float)
            norm = np.asarray(fi["norm_u_full"], float)
            keepm = np.ones(wn.shape, dtype=bool)
            if cfg.full_wn_lo is not None:
                keepm &= wn >= cfg.full_wn_lo
            if cfg.full_wn_cap is not None:
                keepm &= wn <= cfg.full_wn_cap
            res = fringe_msv.multiscale_variance_analysis(
                wn[keepm], norm[keepm], fi, "constant_n",
                cfg=cfg, label=str(label))
            stds = [row["nt_std"] for row in fringe_msv.msv_trend_summary(res)
                    if row.get("nt_std") is not None
                    and np.isfinite(row["nt_std"])]
        except Exception as exc:
            self._log("Fringe: multiscale variance unavailable for %s (%s)."
                      % (label, exc))
            return None
        if not stds:
            return None
        self._msv_cache[dk] = float(max(stds))
        return self._msv_cache[dk]

    # =======================================================================
    # results vs pressure
    # =======================================================================
    def _pt_branch(self, pt):
        """The point's branch, read LIVE from the main window.

        Recorded points keep the branch they were filed under, but the app's
        C/D state is the authority: ticking a D box, or loading a
        decompression list, must move the marker here without asking for the
        point to be recorded again.
        """
        rec = self._record(pt.get("label"))
        if rec is not None:
            return self._branch(rec)
        return pt.get("branch") or "C"

    def _pt_indices(self, pt):
        """(n_layer2, n_medium) the point was recorded at.

        Stored on the row since v1.4.9; a point written before that is
        reconstructed from its medium name at its own pressure, which is
        what the solve used at the time.
        """
        n_med = pt.get("n_medium")
        n_l2 = pt.get("n_layer2")
        if n_med and n_l2:
            return float(n_l2), float(n_med)
        wl = 0.5 * (_f(self.wlmin_v, 600.0) + _f(self.wlmax_v, 800.0))
        p = float(pt.get("pressure") or 0.0)
        med = pt.get("medium") or self.medium_v.get()
        n_med = float(n_med or self._index(med, p, wl))
        l2 = pt.get("layer2_name") or med
        n_l2 = float(n_l2 or self._index(l2, p, wl))
        return n_l2, n_med

    def _resolve_point(self, pt, medium=None, layer2=None):
        """Re-solve one recorded point, optionally under other materials.

        `medium` None keeps the recorded indices, and then the answer is the
        recorded one EXACTLY: (A, C, iii) are the measurement and
        solve_paths conserves A, so the stored solved tuple is a lossless
        encoding of the three paths at those indices.

        `layer2` names a material for the layer beside the sample and is
        independent of `medium`, which is what lets the n_s / t_s panels
        draw the medium x layer2 cross-product his overlay does.
        """
        try:
            A = float(pt["A"])
            C = float(pt["C"])
            iii = float(pt["iii"])
        except (KeyError, TypeError, ValueError):
            return None
        n_l2, n_med = self._pt_indices(pt)
        if medium is not None or layer2 is not None:
            wl = 0.5 * (_f(self.wlmin_v, 600.0) + _f(self.wlmax_v, 800.0))
            p = float(pt.get("pressure") or 0.0)
            if medium is not None:
                n_med = self._index(medium, p, wl)
                n_l2 = (self._index(pt.get("layer2_name"), p, wl)
                        if pt.get("layer2") else n_med)
            if layer2 is not None:
                n_l2 = self._index(layer2, p, wl)
        sol = fringe_optics.solve_paths(A, C, iii, n_l2, n_med)
        if sol is None:
            return None
        return {"n_s": sol["n_s"], "n_medium": n_med, "n_layer2": n_l2,
                "t_s": sol["t_s"], "L": sol["L"],
                "t_layer2": sol["t_layer2"]}

    def _series_has_layer2(self):
        """True when a recorded point has a Layer 2 distinct from the medium.

        His `_series_has_layer2` (defringe_dac 10298-10306), and the same
        per-point test: with no such point the Layer 2 overlays are inert,
        so the section is not offered at all.
        """
        for p in self._series:
            try:
                n_l2, n_med = self._pt_indices(p)
            except (TypeError, ValueError):
                continue
            if abs(float(n_l2) - float(n_med)) > 1e-12:
                return True
        return False

    def _eos_panel_label(self, panel):
        """Row label for one EoS panel, spelled as its axis is."""
        return {"L": "L", "t_s": "t_s", "t_layer2": "t_layer2"}.get(panel,
                                                                   panel)

    def _res_eos_material(self, panel):
        """The material a panel's thickness belongs to, his mapping.

        L is the whole gap, so it follows the MEDIUM; t_layer2 follows the
        Layer 2 material when the series has one; t_s is the sample and has
        no medium model at all (his _res_eos_material, 10214-10222).
        """
        if panel == "L":
            return self.medium_v.get()
        if panel == "t_layer2":
            return (self.layer2_v.get() if self.layer2_on_v.get()
                    else self.medium_v.get())
        return None

    def _res_eos_default_for(self, panel):
        """The EoS a panel starts on, derived from its own material."""
        return fringe_materials.MATERIAL_EOS.get(
            self._res_eos_material(panel))

    def _res_default_check(self):
        """A series opens on its recorded curve (his _res_default_check,
        10398-10409).  Once per series, so a later toggle is never fought.

        His also clears the model overlays here; ours remembers those
        deliberately (the remembered-dropdown deviation), so only the
        As recorded toggle is re-defaulted.
        """
        sid = self._series_label()
        if self._res_defaulted_for == sid:
            return
        self._res_defaulted_for = sid
        if self._res_recorded_v is not None:
            self._res_recorded_v.set(True)

    def _res_qual_colors(self, name):
        """One qualitative map's colours, skip-faint applied."""
        if name == "okabeito" or not colormaps.is_categorical(name):
            cols = list(OKABE_ITO)
        else:
            cols = [colormaps.color_for(name, 0.0, 0.0, 1.0, i, 12)
                    for i in range(12)]
        if self._res_skipfaint_v is not None and self._res_skipfaint_v.get():
            cols = [c for c in cols if not _is_faint(c)] or cols
        return cols

    def _res_cmap_names(self):
        """The colourways the overlay chooser offers, his order."""
        return ["tab10", "okabeito"] + [
            n for n in colormaps.available()
            if colormaps.is_categorical(n) and n not in ("tab10",)]

    def _res_curve_colors(self, labels):
        """Colour per overlay curve, in draw order.

        His chain (_res_effective_colors, 10370-10396): the primary
        colourway first, then the next maps as the curves outgrow it, each
        extra map surfaced as its own override dropdown so the reader says
        which one continues.  The RECORDED points keep their medium slots --
        the identity a colour carries there is which medium the point was
        solved under, and that must not move with a colourway.
        """
        if not labels:
            self._res_sync_overflow(0)
            return {}
        if self._hc():
            ink = self._page()[1]
            self._res_sync_overflow(0)
            return {lab: ink for lab in labels}
        primary = (self._res_cmap_v.get() if self._res_cmap_v is not None
                   else "tab10")
        chain, cols = [primary], []
        pool = [n for n in self._res_cmap_names() if n != primary]
        overrides = [v.get() for v in self._res_overflow_v]
        while True:
            cols = []
            for nm in chain:
                for c in self._res_qual_colors(nm):
                    if c not in cols:
                        cols.append(c)
            if len(cols) >= len(labels) or not pool:
                break
            nxt = overrides[len(chain) - 1] if len(overrides) >= len(chain) \
                else None
            if nxt not in pool:
                nxt = pool[0]
            pool.remove(nxt)
            chain.append(nxt)
        self._res_sync_overflow(len(chain) - 1, chain)
        if not cols:
            cols = list(OKABE_ITO)
        return {lab: cols[i % len(cols)] for i, lab in enumerate(labels)}

    def _res_sync_overflow(self, n, chain=None):
        """Show one "then" dropdown per extra colourway the chain needed."""
        box = self._res_overflow_box
        try:
            if box is None or not box.winfo_exists():
                return
        except tk.TclError:
            return
        while len(self._res_overflow_rows) > n:
            fr = self._res_overflow_rows.pop()
            self._res_overflow_v.pop()
            try:
                fr.destroy()
            except tk.TclError:
                pass
        while len(self._res_overflow_rows) < n:
            i = len(self._res_overflow_rows)
            v = tk.StringVar(value=(chain[i + 1] if chain
                                    and len(chain) > i + 1 else "okabeito"))
            fr = ttk.Frame(box)
            fr.pack(side="top", fill="x")
            self.app._lbl(fr, text="then", width=14).pack(side="left")
            cb = ttk.Combobox(fr, textvariable=v, width=14, state="readonly",
                              values=self._res_cmap_names())
            cb.pack(side="left")
            cb.bind("<<ComboboxSelected>>",
                    lambda _e: self._res_refresh())
            self._tip(cb, "The colours the overlay curves continue into "
                          "once the map above runs out.")
            self._res_overflow_rows.append(fr)
            self._res_overflow_v.append(v)
        if chain:
            for i, v in enumerate(self._res_overflow_v):
                if len(chain) > i + 1 and v.get() != chain[i + 1]:
                    v.set(chain[i + 1])

    def _res_series(self, pts, models, l2s):
        """The overlay curves to draw: his two check-sets and their cross.

        The MEDIUM set drives n_medium and L, the LAYER 2 set drives
        n_layer2 and t_layer2, and n_s / t_s take the CROSS-PRODUCT of the
        two, an unchecked side held as recorded (his _res_models /
        _res_layer2_models, 10262-10266).  A series with no Layer 2 has
        n_layer2 == n_medium by construction, so there the medium curves
        stay on the Layer 2 panels rather than leaving them empty.
        """
        flat = not self._series_has_layer2()
        out = {}

        def _add(label, med, l2, panels):
            out[label] = {"medium": med, "layer2": l2, "panels": panels,
                          "rows": [(p, self._resolve_point(p, medium=med,
                                                           layer2=l2))
                                   for p in pts]}

        for m in models:
            panels = set(("n_medium", "L"))
            if not l2s:
                panels |= set(("n_s", "t_s"))
            if flat:
                panels |= set(("n_layer2", "t_layer2"))
            _add(MEDIUM_LABELS.get(m, m), m, None, panels)
        for l in l2s:
            panels = set(("n_layer2", "t_layer2"))
            if not models:
                panels |= set(("n_s", "t_s"))
            _add("layer 2 " + MEDIUM_LABELS.get(l, l), None, l, panels)
        if models and l2s:
            for m in models:
                for l in l2s:
                    _add("%s x layer 2 %s" % (MEDIUM_LABELS.get(m, m),
                                              MEDIUM_LABELS.get(l, l)),
                         m, l, set(("n_s", "t_s")))
        return out

    def _eos_selections(self):
        out = {}
        for panel in RES_EOS_PANELS:
            names = [n for n, v in (self._res_eos_v.get(panel) or {}).items()
                     if v.get()]
            if names:
                out[panel] = sorted(names)
        if not self._res_eos_v:          # window never opened: settings win
            stored = self.settings.get("fr_res_eos") or {}
            return {k: list(v) for k, v in stored.items() if v}
        return out

    def _apply_eos_state(self, eos):
        sel = eos.get("selections") or {}
        if isinstance(sel, dict):
            self.settings["fr_res_eos"] = {k: list(v) for k, v in sel.items()}
            for panel, names in sel.items():
                for name, var in (self._res_eos_v.get(panel) or {}).items():
                    var.set(name in names)
        self._res_anchor = {}
        self._res_anchor_curve = {}
        for a in (eos.get("anchors") or []):
            # both shapes: his four-field entry and our old three-field one
            if a.get("panel") and a.get("eos") and a.get("dk"):
                self._res_anchor[(a["panel"], a["eos"])] = a["dk"]
                self._res_anchor_curve[(a["panel"], a["eos"])] = \
                    a.get("curve") or RES_RECORDED
        self.settings["fr_res_anchors"] = {
            "%s|%s" % k: v for k, v in self._res_anchor.items()}

    def _res_color(self, pt):
        """Colour of a recorded point: its medium's slot in Okabe-Ito, so the
        identity a colour carries here is 'which n(P) model produced this'."""
        med = pt.get("medium") or "Other"
        try:
            i = MEDIUM_CHOICES.index(med)
        except ValueError:
            i = len(MEDIUM_CHOICES)
        if self._hc():
            return self._page()[1]
        return OKABE_ITO[i % len(OKABE_ITO)]

    def results_view(self):
        """The recorded series as Matthew's 2x3 grid against pressure.

        Same pop-out shape as the FFT view (rule 21): the work on the left,
        a Guide card on the right, a button bar along the bottom.
        """
        win = self._raise_existing("_results")
        if win is not None:
            self._res_refresh()
            return win
        win = tk.Toplevel(self.app.root)
        win.title("Results vs pressure")
        win.transient(self.app.root)
        self.app._center_on_root(win, *self._dlg_size(148, 84))
        self.app._apply_titlebar(win)
        win.bind("<Escape>", lambda e: self._close_results())
        win.protocol("WM_DELETE_WINDOW", self._close_results)
        self._results = win

        bar = ttk.Frame(win, padding=(10, 8))
        bar.pack(side="bottom", fill="x")
        ttk.Button(bar, text="Close",
                   command=self._close_results).pack(side="right")
        ttk.Button(bar, text="Save figure…",
                   command=self._res_save).pack(side="right",
                                                padx=(0, PAD_X))
        ex = ttk.Button(bar, text="Export results CSV",
                        command=self._res_export)
        ex.pack(side="right", padx=(0, PAD_X))
        self._tip(ex, "Write every recorded point to a CSV: its three "
                      "measured paths, the indices it was solved under and "
                      "the solved geometry. His columns, in his order.")
        self._res_count = self.app._lbl(bar, text="", foreground=MUTED)
        self._res_count.pack(side="left")

        self._build_results_guide(win)
        main = ttk.Frame(win, padding=(12, 10))
        main.pack(side="left", fill="both", expand=True)

        recr = ttk.Frame(main)
        recr.pack(side="top", fill="x", pady=PAD_TIGHT)
        self.app._lbl(recr, text="Recorded", width=14).pack(side="left")
        self._res_recorded_v = tk.BooleanVar(
            value=bool(self.settings.get("fr_res_recorded", True)))
        rc = ttk.Checkbutton(recr, text="As recorded",
                             variable=self._res_recorded_v,
                             command=self._res_refresh)
        rc.pack(side="left", padx=(0, PAD_X))
        self._tip(rc, "Draw every point with the indices it was recorded "
                      "under, each coloured by its own medium. Off leaves "
                      "the model curves alone on the panels.")
        opts = ttk.Frame(main)
        opts.pack(side="top", fill="x", pady=PAD_ROW)
        self.app._lbl(opts, text="Re-solve under", width=14).pack(side="left")
        stored = set(self.settings.get("fr_res_models") or [])
        for key in RES_MODEL_CHOICES:
            v = tk.BooleanVar(value=key in stored)
            self._res_model_v[key] = v
            # The FULL label, never a shortened one: three of the four media
            # are argon, and clipping at the bracket gave three boxes all
            # reading "Argon" -- a display map has to stay injective over
            # the canonical set (rule 53).
            cb = ttk.Checkbutton(opts, text=MEDIUM_LABELS.get(key, key),
                                 variable=v, command=self._res_refresh)
            cb.pack(side="left", padx=(0, PAD_X))
            self._tip(cb, "Solve every recorded point again under %s at its "
                          "own pressure and draw the answer beside the "
                          "recorded one." % MEDIUM_LABELS.get(key, key))
        # The Layer 2 set, his second check-set: shown only when a recorded
        # point actually has a Layer 2 (with none, every curve it could draw
        # is the medium curve already on the panel).
        l2r = ttk.Frame(main)
        self._res_layer2_row = l2r
        self.app._lbl(l2r, text="Layer 2 models",
                      width=14).pack(side="left")
        stored_l2 = set(self.settings.get("fr_res_layer2") or [])
        for key in RES_MODEL_CHOICES:
            v = tk.BooleanVar(value=key in stored_l2)
            self._res_layer2_v[key] = v
            cb = ttk.Checkbutton(l2r, text=MEDIUM_LABELS.get(key, key),
                                 variable=v, command=self._res_refresh)
            cb.pack(side="left", padx=(0, PAD_X))
            self._tip(cb, "Solve every recorded point again with %s beside "
                          "the sample. n_s and t_s then draw one curve per "
                          "medium and layer 2 pair."
                          % MEDIUM_LABELS.get(key, key))
        if self._series_has_layer2():
            l2r.pack(side="top", fill="x", pady=PAD_TIGHT)
        # One EoS row per thickness panel: a panel's tick is its own, so
        # Vinet on t_s and BM3 on L is expressible (his per-panel
        # _res_eos_sel).  The first tick on a fresh panel is the one its
        # material implies.
        stored_eos = self.settings.get("fr_res_eos") or {}
        self._res_l2_anchor = None
        for panel in RES_EOS_PANELS:
            eosr = ttk.Frame(main)
            eosr.pack(side="top", fill="x", pady=PAD_TIGHT)
            if self._res_l2_anchor is None:
                self._res_l2_anchor = eosr   # the Layer 2 row packs above it
            self.app._lbl(eosr, text="EoS on %s"
                                     % self._eos_panel_label(panel),
                          width=14).pack(side="left")
            names = stored_eos.get(panel)
            if names is None:
                dflt = self._res_eos_default_for(panel)
                names = [dflt] if dflt else []
            for name in sorted(fringe_materials.EOS_MODELS):
                v = tk.BooleanVar(value=name in names)
                self._res_eos_v.setdefault(panel, {})[name] = v
                cb = ttk.Checkbutton(eosr, text=name, variable=v,
                                     command=self._res_refresh)
                cb.pack(side="left", padx=(0, PAD_X))
                self._tip(cb, "Draw %s as a dashed thickness curve on the "
                              "%s panel. It scales as the cube root of the "
                              "volume ratio. It anchors on the "
                              "lowest-pressure point, or on the one you "
                              "right-click."
                              % (name, self._eos_panel_label(panel)))
        # the colourway the overlay curves are taken from, his chooser
        cmr = ttk.Frame(main)
        cmr.pack(side="top", fill="x", pady=PAD_TIGHT)
        self.app._lbl(cmr, text="Curve colours", width=14).pack(side="left")
        self._res_cmap_v = tk.StringVar(
            value=str(self.settings.get("fr_res_cmap", "tab10")))
        ccb = ttk.Combobox(cmr, textvariable=self._res_cmap_v, width=14,
                           state="readonly", values=self._res_cmap_names())
        ccb.pack(side="left")
        ccb.bind("<<ComboboxSelected>>", lambda _e: self._res_refresh())
        self._tip(ccb, "The colours the overlay curves are taken from, in "
                       "order. The recorded points keep their own medium "
                       "colours.")
        self._res_skipfaint_v = tk.BooleanVar(
            value=bool(self.settings.get("fr_res_skip_faint", False)))
        sf = ttk.Checkbutton(cmr, text="skip faint",
                             variable=self._res_skipfaint_v,
                             command=self._res_refresh)
        sf.pack(side="left", padx=(PAD_X, 0))
        self._tip(sf, "Leave out the palest colours in the map, which wash "
                      "out on a pale page.")
        # a rebuilt window starts with no override rows: the old ones went
        # down with the Toplevel that held them
        self._res_overflow_v = []
        self._res_overflow_rows = []
        self._res_overflow_box = ttk.Frame(main)
        self._res_overflow_box.pack(side="top", fill="x")

        self._res_fig = Figure(figsize=(9.0, 5.6), dpi=100,
                               facecolor=self._page()[0])
        self._res_canvas = FigureCanvasTkAgg(self._res_fig, master=main)
        self._res_canvas.get_tk_widget().pack(fill="both", expand=True)
        self._res_canvas.mpl_connect("button_press_event", self._on_res_press)
        self._res_canvas.mpl_connect("motion_notify_event", self._on_res_hover)
        self.app._iconize_buttons(win)
        self._clamp_geometry(win, self.settings.get("fr_res_geom"))
        self._res_refresh()
        return win

    def _close_results(self):
        win, self._results = self._results, None
        if win is not None:
            try:
                self.settings["fr_res_geom"] = win.geometry()
                win.destroy()
            except tk.TclError:
                pass
        self.settings["fr_res_models"] = [k for k, v
                                          in self._res_model_v.items()
                                          if v.get()]
        self.settings["fr_res_layer2"] = [k for k, v
                                          in self._res_layer2_v.items()
                                          if v.get()]
        if self._res_recorded_v is not None:
            self.settings["fr_res_recorded"] = bool(
                self._res_recorded_v.get())
        if self._res_cmap_v is not None:
            self.settings["fr_res_cmap"] = self._res_cmap_v.get()
        if self._res_skipfaint_v is not None:
            self.settings["fr_res_skip_faint"] = bool(
                self._res_skipfaint_v.get())
        self.settings["fr_res_eos"] = self._eos_selections()
        self._res_overflow_box = None
        self._res_overflow_v = []
        self._res_overflow_rows = []

    def _res_export(self):
        """His Export results CSV (_export_results, 11110-11127).

        One row per recorded point, in his eighteen columns and his order,
        so a file this program writes opens where his does.  The three
        measured paths and the two indices come off the recorded row itself,
        and the solved geometry is re-solved from them -- which reproduces
        the recorded numbers exactly, because solve_paths conserves the
        sample path.
        """
        import csv
        if not self._series:
            self._status("no recorded points to export.", warn=True)
            return
        folder = self._series_folder()
        if not folder:
            self._status("pick an input or output folder first.", warn=True)
            return
        cols = ["series", "pressure_gpa", "label", "stem", "sample_um",
                "sampledia_um", "mediumdia_um", "n_layer2", "n_medium",
                "n_s", "t_s_um", "t_layer2_um", "L_um", "nl2tl2_um",
                "layer2_model", "medium_model", "layer2", "series_id"]
        series = self._series_label()
        sid = self._input_folder() or folder
        try:
            sid = os.path.abspath(sid)
        except (TypeError, ValueError):
            sid = str(sid)
        rows = []
        for pt in self._series:
            sol = self._resolve_point(pt) or {}
            n_l2, n_med = self._pt_indices(pt)
            t_l2 = sol.get("t_layer2")
            rows.append({
                "series": series,
                "pressure_gpa": pt.get("pressure"),
                "label": pt.get("label"),
                "stem": pt.get("stem") or self._stem_of(pt.get("label")),
                "sample_um": pt.get("A"),
                "sampledia_um": pt.get("C"),
                "mediumdia_um": pt.get("iii"),
                "n_layer2": n_l2,
                "n_medium": n_med,
                "n_s": sol.get("n_s"),
                "t_s_um": sol.get("t_s"),
                "t_layer2_um": t_l2,
                "L_um": sol.get("L"),
                # his nl2tl2: the medium layer's own optical path
                "nl2tl2_um": (None if t_l2 is None
                              else float(n_l2) * float(t_l2)),
                "layer2_model": pt.get("layer2_name"),
                "medium_model": pt.get("medium"),
                "layer2": bool(pt.get("layer2")),
                "series_id": sid})
        stamp = time.strftime("%Y%m%d_%H%M%S")
        path = os.path.join(folder, "fft_results_series_%s.csv" % stamp)
        try:
            with open(path, "w", encoding="utf-8", newline="") as f:
                w = csv.DictWriter(f, fieldnames=cols, extrasaction="ignore")
                w.writeheader()
                for row in rows:
                    w.writerow({k: ("" if row.get(k) is None else row[k])
                                for k in cols})
        except (OSError, csv.Error) as exc:
            self._status("export failed: %s" % exc, warn=True)
            return
        self._log("Fringe: wrote %d result row(s) -> %s" % (len(rows), path))
        self._status("exported %d point(s) -> %s"
                     % (len(rows), os.path.basename(path)))

    def _res_save(self):
        fig = getattr(self, "_res_fig", None)
        if fig is None:
            return
        path = filedialog.asksaveasfilename(
            title="Save the results figure", defaultextension=".png",
            initialfile="results_vs_pressure.png",
            initialdir=self._series_folder() or None,
            filetypes=[("PNG", "*.png"), ("PDF", "*.pdf"), ("SVG", "*.svg")],
            parent=self._results or self.app.root)
        if not path:
            return
        try:
            fig.savefig(path, dpi=200, facecolor=fig.get_facecolor())
        except Exception as exc:
            self._status("saving the figure failed: %s" % exc, warn=True)
            return
        self._log("Fringe: wrote the results figure -> " + path)
        self._status("results figure saved.")

    def _res_build_axes(self):
        fig = self._res_fig
        fig.clear()
        gs = fig.add_gridspec(2, 3, hspace=0.42, wspace=0.38)
        self._res_ax = {}
        for key, (row, col), _lab, _eos in RES_PANELS:
            self._res_ax[key] = fig.add_subplot(gs[row, col])

    def _res_refresh(self):
        """Redraw the six panels.  Cheap enough to run on every toggle."""
        win = self._results
        if win is None or not win.winfo_exists():
            return
        face, ink = self._page()
        self._res_fig.set_facecolor(face)
        self._res_build_axes()
        self._res_pick = {}
        # the hover registries: every artist a tag can attach to, rebuilt
        # with the axes so a stale annotation can never outlive its panel
        self._res_hover = {}
        self._res_model_hover = {}
        self._res_eos_hover = {}
        pts = sorted([p for p in self._series
                      if p.get("pressure") is not None],
                     key=lambda q: q["pressure"])
        self._res_default_check()
        self._res_sync_layer2_row()
        models = [k for k, v in self._res_model_v.items() if v.get()]
        l2s = ([k for k, v in self._res_layer2_v.items() if v.get()]
               if self._series_has_layer2() else [])
        series = self._res_series(pts, models, l2s)
        self._res_model_colors = self._res_curve_colors(sorted(series))
        for key, _pos, ylab, is_eos in RES_PANELS:
            ax = self._res_ax[key]
            ax.set_facecolor(face)
            for sp in ax.spines.values():
                sp.set_color(ink)
            ax.tick_params(colors=ink, labelsize=8)
            ax.tick_params(which="minor", length=3, colors=ink)
            drew = self._res_draw_panel(ax, key, pts, series, ink)
            if is_eos and drew:
                self._res_draw_eos(ax, key, pts)
            if not drew:
                # Two empty states, his (11038-11046): a series with no
                # points at all, and a series whose every curve is turned
                # off.  They ask for different things, so they say
                # different things.
                ax.text(0.5, 0.5,
                        "no series shown" if pts else "no points",
                        transform=ax.transAxes,
                        ha="center", va="center", color=ink, alpha=0.55,
                        fontsize=9)
                ax.set_xlim(0, 1)
                ax.set_ylim(0, 1)
            ax.set_xlabel("Pressure (GPa)", fontsize=9, color=ink)
            ax.set_ylabel(ylab, fontsize=9, color=ink)
            ax.grid(alpha=0.28, which="major")
            ax.grid(alpha=0.12, which="minor")
            ax.xaxis.set_minor_locator(AutoMinorLocator(4))
            ax.yaxis.set_major_locator(MaxNLocator(nbins=5))
            ax.yaxis.set_minor_locator(AutoMinorLocator(2))
            ax.yaxis.set_major_formatter(ScalarFormatter(useOffset=False))
        n_d = sum(1 for p in pts if self._pt_branch(p) == "D")
        lab = getattr(self, "_res_count", None)
        if lab is not None:
            try:
                lab.configure(text="%d point(s):  %d compression, %d "
                                   "decompression" % (len(pts),
                                                      len(pts) - n_d, n_d))
            except tk.TclError:
                pass
        # the key's height is what the panels have to make room for, so the
        # reserved strip is computed from how many rows it actually took
        rows = self._res_legend(pts, series, ink)
        self._tight(self._res_fig, pad=1.3, h_pad=2.0, w_pad=1.8,
                    rect=(0.0, 0.02 + 0.035 * rows, 1.0, 1.0))
        try:
            self._res_canvas.draw_idle()
        except Exception:
            pass

    def _res_sync_layer2_row(self):
        """Show the Layer 2 section only while the series has a Layer 2.

        His `_sync_layer2_section` (defringe_dac 10411-10420) hides it when
        no recorded point has one, and unticks it on the way out so no stale
        combination curve is left on the plot.
        """
        row = self._res_layer2_row
        if row is None:
            return
        try:
            if not row.winfo_exists():
                return
            shown = bool(row.winfo_manager())
            want = self._series_has_layer2()
            if want and not shown:
                anchor = self._res_l2_anchor
                if anchor is not None and anchor.winfo_exists():
                    row.pack(side="top", fill="x", pady=PAD_TIGHT,
                             before=anchor)
                else:
                    row.pack(side="top", fill="x", pady=PAD_TIGHT)
            elif shown and not want:
                row.pack_forget()
                for v in self._res_layer2_v.values():
                    v.set(False)
        except tk.TclError:
            pass

    def _res_legend(self, pts, series, ink):
        """One key for the whole grid, along the bottom.

        Six panels would carry six copies of the same key, and a per-panel
        legend on a plot this small lands on the data. The entries are built
        from proxies rather than scraped off one axis, because the EoS names
        differ between panels and the marker shapes belong to the branch,
        not to any single line.
        """
        from matplotlib.lines import Line2D
        h, lab = [], []
        media = []
        for p in pts:
            m = p.get("medium") or "Other"
            if m not in media:
                media.append(m)
        recorded = (self._res_recorded_v is None
                    or bool(self._res_recorded_v.get()))
        if recorded:
            for m in media:
                col = self._res_color({"medium": m})
                h.append(Line2D([], [], ls="none", marker="o", ms=5.5,
                                color=col))
                lab.append("recorded, %s" % MEDIUM_LABELS.get(m, m))
            h.append(Line2D([], [], ls="none", marker="x", ms=6.0, mew=1.5,
                            color=(self._res_color({"medium": media[0]})
                                   if media else ink)))
            lab.append("decompression")
        for name in sorted(series):
            h.append(Line2D([], [], ls="-", marker="o", ms=3.0, lw=1.1,
                            color=self._res_model_colors.get(name, ink)))
            lab.append("re-solved, %s" % name)
        seen = []
        for panel in RES_EOS_PANELS:
            for i, name in enumerate(sorted(fringe_materials.EOS_MODELS)):
                if name in seen:
                    continue
                if (self._res_eos_v.get(panel) or {}).get(name) is not None \
                        and self._res_eos_v[panel][name].get():
                    seen.append(name)
                    col = (ink if self._hc() else
                           OKABE_ITO[(len(MEDIUM_CHOICES) + i)
                                     % len(OKABE_ITO)])
                    h.append(Line2D([], [], ls="--", lw=1.2, color=col))
                    lab.append("EoS: " + name)
        if self.msv_v.get():
            h.append(Line2D([], [], ls="-", lw=0.9, color=ink,
                            marker="_", ms=6))
            lab.append("multiscale-variance 1 sigma")
        if not h:
            return 0
        ncol = min(4, len(h))
        leg = self._res_fig.legend(h, lab, loc="lower center", ncol=ncol,
                                   fontsize=7.5, frameon=False,
                                   handlelength=2.2, columnspacing=1.6,
                                   borderaxespad=0.2)
        for t in leg.get_texts():
            t.set_color(ink)
        return int(np.ceil(len(h) / float(ncol)))

    def _res_draw_panel(self, ax, key, pts, series, ink):
        """Model curves, then the recorded points on top.  Returns True when
        anything was drawn."""
        drew = False
        for i, (name, spec) in enumerate(sorted(series.items())):
            # each check-set drives its own panels, and n_s / t_s take the
            # cross-product of the two (see _res_series)
            if key not in spec["panels"]:
                continue
            xy = [(p["pressure"], sol[key]) for p, sol in spec["rows"]
                  if sol is not None and np.isfinite(sol[key])]
            if not xy:
                continue
            # The overlay curves take the chosen colourway in draw order,
            # his _res_model_colors.  The RECORDED points keep their medium
            # slots, so the identity a point's colour carries never moves
            # with the colourway.
            col = self._res_model_colors.get(name)
            if col is None:
                col = self._res_color({"medium": spec["medium"] or "Other"})
            dash = STEM_DASHES[(i + 1) % len(STEM_DASHES)] if self._hc() else "-"
            ln, = ax.plot([q[0] for q in xy], [q[1] for q in xy], ls=dash,
                          marker="o", ms=3.0, lw=1.1, color=col, zorder=2,
                          label=name, picker=True, pickradius=6)
            self._res_model_hover.setdefault(key, []).append(
                {"line": ln, "label": name,
                 "colour": col, "annot": None, "xy": list(xy)})
            drew = True
        if self._res_recorded_v is not None \
                and not self._res_recorded_v.get():
            return drew                     # his "As recorded" turned off
        rows = [(p, self._resolve_point(p)) for p in pts]
        rows = [(p, s) for p, s in rows
                if s is not None and np.isfinite(s[key])]
        if not rows:
            return drew
        ax.plot([p["pressure"] for p, _s in rows], [s[key] for _p, s in rows],
                "-", color=self.app._muted_fg(), lw=1.0, zorder=3)
        comp = [(p, s) for p, s in rows if self._pt_branch(p) != "D"]
        deco = [(p, s) for p, s in rows if self._pt_branch(p) == "D"]
        if comp:
            ax.scatter([p["pressure"] for p, _s in comp],
                       [s[key] for _p, s in comp],
                       c=[self._res_color(p) for p, _s in comp],
                       s=RES_MS, zorder=5, edgecolors="none",
                       label="compression")
        if deco:
            ax.scatter([p["pressure"] for p, _s in deco],
                       [s[key] for _p, s in deco],
                       c=[self._res_color(p) for p, _s in deco],
                       s=RES_MS_D, zorder=5, marker="x", linewidths=1.5,
                       label="decompression")
        if self.msv_v.get() and key in ("t_s", "n_s"):
            self._res_error_bars(ax, key, rows, ink)
        self._res_pick[key] = [(p["pressure"], s[key], p) for p, s in rows]
        # what the recorded-point tag reads out: the pressure, the value,
        # the medium the point was solved under, and its branch
        self._res_hover[key] = {
            "pts": [(p["pressure"], s[key],
                     MEDIUM_LABELS.get(p.get("medium") or "Other",
                                       p.get("medium") or "Other")
                     + (" · decompression" if self._pt_branch(p) == "D"
                        else ""))
                    for p, s in rows],
            "annot": None}
        return True

    def _res_error_bars(self, ax, key, rows, ink):
        """Multiscale-variance bars on the sample panels.

        The measurement the variance is on is the sample optical path
        A = n_s * t_s, so it propagates onto t_s at fixed n_s and onto n_s at
        fixed t_s.  Both are one division; neither pretends to know a
        covariance the measurement never gave.
        """
        xs, ys, es = [], [], []
        for p, s in rows:
            sig = self._msv_sigma(p.get("label"))
            if sig is None or not np.isfinite(sig):
                continue
            n_s, t_s = float(s["n_s"]), float(s["t_s"])
            if key == "t_s":
                err = sig / n_s if n_s > 0 else None
            else:
                err = sig / t_s if t_s > 0 else None
            if err is None or not np.isfinite(err):
                continue
            xs.append(p["pressure"])
            ys.append(s[key])
            es.append(err)
        if xs:
            ax.errorbar(xs, ys, yerr=es, fmt="none", ecolor=ink, elinewidth=0.9,
                        capsize=2.5, alpha=0.75, zorder=4)

    def _res_draw_eos(self, ax, key, pts):
        """One dashed EoS curve per checked model, anchored on the lowest-
        pressure recorded point unless a right-click set another."""
        names = [n for n, v in (self._res_eos_v.get(key) or {}).items()
                 if v.get()]
        if not names:
            return
        cand = []
        for p in pts:
            sol = self._resolve_point(p)
            if sol is not None and np.isfinite(sol[key]):
                cand.append((float(p["pressure"]), float(sol[key]),
                             p.get("label")))
        if len(cand) < 2:
            return
        p_lo = min(c[0] for c in cand)
        p_hi = max(c[0] for c in cand)
        for i, name in enumerate(sorted(fringe_materials.EOS_MODELS)):
            if name not in names:
                continue
            meta = fringe_materials.EOS_MODELS.get(name)
            if meta is None:
                continue
            floor = meta["p_floor"]
            on = [c for c in cand if c[0] >= floor]
            if not on:
                continue
            over = self._res_anchor.get((key, name))
            hit = next((c for c in on if c[2] == over), None)
            if over is not None and hit is None:
                self._res_anchor.pop((key, name), None)     # stale -> auto
            pa, ya, _dk = hit if hit is not None else min(on,
                                                          key=lambda c: c[0])
            px = np.linspace(max(p_lo, floor), p_hi, 200)
            try:
                py = fringe_materials.thickness_from_volume_ratio(
                    ya, [fringe_materials.eos_volume_ratio(name, float(v), pa)
                         for v in px])
            except (ValueError, ZeroDivisionError, FloatingPointError):
                continue
            # EoS colours start past the media slots so a dashed curve never
            # takes the colour of a point it is drawn beside.
            col = (self._page()[1] if self._hc()
                   else OKABE_ITO[(len(MEDIUM_CHOICES) + i) % len(OKABE_ITO)])
            lab = "%s (anchor %g GPa%s)" % (name, pa,
                                            ", set" if hit is not None else "")
            ln, = ax.plot(px, py, "--", color=col, lw=1.2, zorder=1,
                          label=lab, picker=True, pickradius=6)
            self._res_eos_hover.setdefault(key, []).append(
                {"line": ln, "label": lab, "colour": col, "annot": None})

    def _res_nearest(self, panel, event):
        """The recorded point nearest the click on `panel`, or None.

        Distance is measured in each axis' own span, so a panel whose y runs
        over thousandths is as easy to aim at as one that runs over microns.
        """
        pick = self._res_pick.get(panel) or []
        if not pick or event.xdata is None or event.ydata is None:
            return None
        x0, x1 = event.inaxes.get_xlim()
        y0, y1 = event.inaxes.get_ylim()
        sx = abs(x1 - x0) or 1.0
        sy = abs(y1 - y0) or 1.0

        def _d2(t):
            return (((t[0] - event.xdata) / sx) ** 2
                    + ((t[1] - event.ydata) / sy) ** 2)
        best = min(pick, key=_d2)
        return best if _d2(best) <= 0.01 else None

    def _on_res_press(self, event):
        """Right-click on a results panel: what can be done to the point
        under the pointer (his _on_results_rclick, 11441).

        Every panel offers the point itself -- taken off the series, and on
        the LOADED point also put back to the shipped inputs first.  A
        thickness panel adds the EoS anchor, which is its own undo: the
        anchored point right-clicked again releases the curve to automatic.
        """
        if event.button != 3 or event.inaxes is None:
            return
        panel = next((k for k, a in self._res_ax.items()
                      if a is event.inaxes), None)
        if panel is None:
            return
        best = self._res_nearest(panel, event)
        if best is None:
            return
        pt = best[2]
        label = pt.get("label")
        here = (self._pt_key(pt) == self._dkey())
        menu = tk.Menu(self.app.root, tearoff=0)
        if here:
            menu.add_command(label="Restore defaults and remove %s" % label,
                             command=self._reset_and_drop_point)
        else:
            menu.add_command(label="Remove %s" % label,
                             command=lambda p=pt: self._res_drop(p))
        names = [n for n, v in (self._res_eos_v.get(panel) or {}).items()
                 if v.get()] if panel in RES_EOS_PANELS else []
        if names:
            menu.add_separator()
            for name in names:
                if self._res_anchor.get((panel, name)) == label:
                    menu.add_command(
                        label="Release the %s anchor (back to automatic)"
                              % name,
                        command=lambda n=name, p=panel:
                        self._res_anchor_set(p, n, None))
                else:
                    menu.add_command(
                        label="Anchor %s at %g GPa" % (name, best[0]),
                        command=lambda n=name, p=panel, l=label:
                        self._res_anchor_set(p, n, l))
        ge = getattr(event, "guiEvent", None)
        try:
            if ge is not None:
                menu.tk_popup(int(ge.x_root), int(ge.y_root))
            else:
                menu.tk_popup(self.app.root.winfo_pointerx(),
                              self.app.root.winfo_pointery())
        finally:
            menu.grab_release()

    def _res_anchor_set(self, panel, name, label):
        """Pin one EoS curve on one point, or release it to automatic."""
        if label is None:
            self._res_anchor.pop((panel, name), None)
            self._res_anchor_curve.pop((panel, name), None)
            self._status("%s on %s is back to the lowest-pressure point."
                         % (name, panel))
        else:
            self._res_anchor[(panel, name)] = label
            self._res_anchor_curve[(panel, name)] = RES_RECORDED
            self._status("%s on %s is anchored at %s." % (name, panel, label))
        self.settings["fr_res_anchors"] = {"%s|%s" % k: v for k, v
                                           in self._res_anchor.items()}
        self._res_refresh()

    def _res_drop(self, pt):
        """Take one recorded point off the series from the results window.

        The drop is in memory: the folder's continuity file still holds the
        point until a save rewrites it, and the status line says so.
        """
        key = self._pt_key(pt)
        n0 = len(self._series)
        self._series = [q for q in self._series if self._pt_key(q) != key]
        if len(self._series) == n0:
            return
        tail = ""
        if key is not None and self._point_status(key) != "absent":
            tail = (" %s still holds it; a save rewrites the file."
                    % SERIES_FILE)
        self._status("%s is off the series.%s"
                     % (pt.get("label") or "the point", tail))
        self._invalidate_json_cache()
        self._refresh_state_indicators()
        self._res_refresh()

    # ---- the results window's hover readouts (his 11535-11659) -----------
    RES_HOVER_PX = 18.0      # how near a marker a tag turns up
    RES_TAG_DX = 9.0         # the tag's resting offset, in points

    def _res_tag(self, ax, face, edge, size=7.5, z=6):
        """One hover tag: a small boxed annotation parked invisible."""
        return ax.annotate(
            "", xy=(0, 0), xytext=(self.RES_TAG_DX, self.RES_TAG_DX),
            textcoords="offset points", fontsize=size, zorder=z,
            color=edge, visible=False,
            bbox=dict(boxstyle="round,pad=0.3", fc=face, ec=edge,
                      alpha=0.95))

    def _on_res_hover(self, event):
        """Read out whatever the pointer is over, on every curve at once.

        Three kinds of tag: the recorded point (its pressure, its value, the
        medium it was solved under), each re-solved model curve, and each
        EoS line.  All of them show together, and a de-overlap pass stacks
        the boxes so none hides another -- his design, because comparing a
        recorded point against the model at that point is the whole reason
        the panels exist.
        """
        if self._results is None:
            return
        ax = event.inaxes
        panel = next((k for k, a in self._res_ax.items() if a is ax), None)
        drew = False
        shown = []
        face, ink = self._page()
        # a tag on a panel the pointer has left goes away
        for key, reg in self._res_hover.items():
            an = reg.get("annot")
            if key != panel and an is not None and an.get_visible():
                an.set_visible(False)
                drew = True
        for reg in (list(self._res_model_hover.items())
                    + list(self._res_eos_hover.items())):
            if reg[0] == panel:
                continue
            for ed in reg[1]:
                an = ed.get("annot")
                if an is not None and an.get_visible():
                    an.set_visible(False)
                    drew = True
        if panel is not None and event.x is not None:
            reach = self.RES_HOVER_PX ** 2

            def _nearest(xy):
                best, best_d2 = None, None
                for item in xy:
                    try:
                        dx, dy = ax.transData.transform((item[0], item[1]))
                    except Exception:
                        continue
                    d2 = (dx - event.x) ** 2 + (dy - event.y) ** 2
                    if best_d2 is None or d2 < best_d2:
                        best, best_d2 = item, d2
                return (best, best_d2)

            reg = self._res_hover.get(panel) or {}
            hit, d2 = _nearest(reg.get("pts") or [])
            an = reg.get("annot")
            if hit is not None and d2 is not None and d2 <= reach:
                if an is None:
                    an = self._res_tag(ax, face, ink)
                    reg["annot"] = an
                an.xy = (hit[0], hit[1])
                an.set_text("%g GPa\n%.4g\n%s" % (hit[0], hit[1], hit[2]))
                an.set_visible(True)
                drew = True
                shown.append(an)
            elif an is not None and an.get_visible():
                an.set_visible(False)
                drew = True
            for ed in self._res_model_hover.get(panel, []):
                hit, d2 = _nearest(ed.get("xy") or [])
                on_pt = hit is not None and d2 is not None and d2 <= reach
                on_line = False
                if not on_pt:
                    try:
                        on_line = bool(ed["line"].contains(event)[0])
                    except Exception:
                        on_line = False
                an = ed.get("annot")
                if on_pt or on_line:
                    if an is None:
                        an = ed["annot"] = self._res_tag(ax, face,
                                                         ed["colour"], z=7)
                    if on_pt:
                        an.xy = (hit[0], hit[1])
                        an.set_text("%g GPa\n%.4g\n%s"
                                    % (hit[0], hit[1], ed["label"]))
                    else:
                        an.xy = (event.xdata, event.ydata)
                        an.set_text(ed["label"])
                    an.set_visible(True)
                    drew = True
                    shown.append(an)
                elif an is not None and an.get_visible():
                    an.set_visible(False)
                    drew = True
            for ed in self._res_eos_hover.get(panel, []):
                try:
                    on_line = bool(ed["line"].contains(event)[0])
                except Exception:
                    on_line = False
                an = ed.get("annot")
                if on_line:
                    if an is None:
                        an = ed["annot"] = self._res_tag(ax, face,
                                                         ed["colour"], size=7)
                    an.xy = (event.xdata, event.ydata)
                    an.set_text(ed["label"])
                    an.set_visible(True)
                    drew = True
                    shown.append(an)
                elif an is not None and an.get_visible():
                    an.set_visible(False)
                    drew = True
            if shown:
                self._res_destack(ax, shown)
        if drew:
            try:
                self._res_canvas.draw_idle()
            except Exception:
                pass

    def _res_destack(self, ax, shown):
        """Stagger simultaneous tags so none is hidden (his 11636-11657).

        The work is in DISPLAY PIXELS, because a box's extent is pixels;
        the chosen offset is converted back to points, which is the unit the
        annotation's offset is in.  Anchors never move -- only the labels.
        """
        try:
            rend = self._res_canvas.get_renderer()
        except Exception:
            return
        px_per_pt = self._res_fig.dpi / 72.0
        placed = []
        for an in shown:
            try:
                ax_disp, ay_disp = ax.transData.transform(an.xy)
                h = an.get_window_extent(renderer=rend).height
            except Exception:
                continue
            dy = self.RES_TAG_DX * px_per_pt
            for (pax, ptop) in placed:
                if abs(pax - ax_disp) < 90.0 and (ay_disp + dy) < ptop + 4.0:
                    dy = (ptop + 4.0) - ay_disp + h
            an.set_position((self.RES_TAG_DX, dy / px_per_pt))
            placed.append((ax_disp, ay_disp + dy + h))

    def _build_results_guide(self, win):
        """The results window's helper card, same shape as the pop-out's."""
        card = self.app._card(win, grow="both", width=self.app._em() * 38)
        card.pack(side="right", fill="both", expand=True, padx=(0, 10), pady=8)
        card.set_title(self.app._lf_header(card, "Guide", icon="book"))
        self._guide_body(card.body, RESULTS_GUIDE, width=38)
        return card

    # =======================================================================
    # pop-out
    # =======================================================================
    def popout(self):
        """Open Matthew's window: his layout and controls, SPARTA's paint.

        R11: the tear-off is no longer a second copy of the FFT figure, it
        is the original GUI -- his sidebar on the left in his order, his
        2x2 figure and navigation toolbar on the right, his View / Window /
        Settings menubar.  fringe_popout builds and owns every widget of
        it.

        ONE MODEL, TWO VIEWS.  The replica binds to THIS workbench: the
        same tk variables, the same methods, the same compute.  An edit in
        either view is an edit in the model, and both follow it.

        The contract this method has always had is unchanged -- the
        singleton guard above, the window remembered in `_popout` (so
        `_close_popout`, `sync_view_switch` and the theme chain reach it),
        the geometry memory in `fr_popout_geom`, and Escape or the X
        sending it home.
        """
        if self._raise_existing("_popout") is not None:
            return
        self.build()
        return fringe_popout.open_popout(self)

    def _close_popout(self):
        win, self._popout = self._popout, None
        # A window closed while it fills the screen must not save the
        # screen as its size: the view keeps the windowed geometry.
        view = getattr(self, "_po_view", None)
        geom = None
        if view is not None:
            try:
                geom = view.normal_geometry()
            except (AttributeError, tk.TclError):
                geom = None
        if win is not None:
            try:
                self.settings["fr_popout_geom"] = geom or win.geometry()
                win.destroy()
            except tk.TclError:
                pass
        self.sync_view_switch()

    def _mirror_popout(self):
        """Re-render the same panels into the pop-out's own figure.

        Mirroring by redraw rather than by sharing the Figure keeps each
        canvas at its own size; the compute is cached, so the second render
        costs only the drawing.
        """
        if self._popout is None or not self._popout.winfo_exists():
            return
        main_fig, main_axes = self.fig, self._axes
        main_twins, main_art = self._twins, self._artists
        main_labs = (self._nt_labels, self._schem_labels)
        try:
            self._po_fig.clear()
            # the main canvas keeps its own artists (restored in `finally`)
            self._artists = self._blank_artists()
            self._nt_labels = {}
            self._schem_labels = {}
            self.fig = self._po_fig
            self.ax_bg = self._po_fig.add_subplot(211)
            self.ax_s = self._po_fig.add_subplot(212)
            self._axes = {"Background": self.ax_bg, "Sample": self.ax_s}
            self._twins = {}
            # fresh subplots are born on matplotlib's white; the mirror has
            # to give them the page, exactly as _redraw's clear loop does,
            # or a tinted theme shows dark chrome around white panels
            face, ink = self._page()
            for ax in (self.ax_bg, self.ax_s):
                ax.set_facecolor(face)
                for sp in ax.spines.values():
                    sp.set_color(ink)
            rec = self._record()
            if rec is not None:
                p = self._stack_params(rec)
                upper = self._x_upper(p)
                for chan in CHANNELS:
                    self._draw_panel(chan, rec, p, upper)
            self._po_fig.set_facecolor(self._page()[0])
            self._tight(self._po_fig, pad=1.4, h_pad=2.4)
            self._fit_labels(self._po_canvas)
            self._po_canvas.draw_idle()
        finally:
            self.fig, self._axes = main_fig, main_axes
            self._twins, self._artists = main_twins, main_art
            self._nt_labels, self._schem_labels = main_labs
            self.ax_bg = main_axes["Background"]
            self.ax_s = main_axes["Sample"]

    def _build_popout_guide(self, win):
        """The pop-out's helper card.

        Same card shape as the formula editor's Guide, and the SAME content
        as the pane beside the plot -- one loader, one renderer, so the
        pop-out cannot end up documenting an older grammar than the window
        it was torn off.
        """
        card = self.app._card(win, grow="both", width=self.app._em() * 38)
        card.pack(side="right", fill="both", expand=True, padx=(0, 10), pady=8)
        card.set_title(self.app._lf_header(card, "Guide", icon="book"))
        self._guide_body(card.body, guide_text(), width=38)
        return card
