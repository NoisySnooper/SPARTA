# SPARTA

*SPectroscopic Absorption, Real Time Analysis* — reduction and
publication-quality visualization of visible / near-IR optical-absorption
spectra from diamond-anvil-cell experiments (developed for NSLS-II beamline
22-IR-1; formerly SQUISHE, originally the Beamline DAC Data Tool).

![SPARTA — the 3D shape surface of the bundled demo series, with the measured traces marked on the sheet](docs/screenshot.png)

## Download (no Python needed)

Most people want **SPARTA_v1.5.0_signed-runtime.zip** from the
[Releases page](https://github.com/NoisySnooper/SPARTA/releases/latest):
unzip it anywhere and double-click `SPARTA.exe`. There is no installer, no
administrator rights are needed, and nothing is written to the registry.
Windows 10 / 11, 64-bit.

**SPARTA_v1.5.0_win7.zip** is the same program on CPython 3.8.10, for offline
Windows 7 SP1 x64 beamline machines that cannot be upgraded.

The source route below (`python app.py`, or `run.bat`) stays for developers.

## What it does

- Reads raw spectrometer segments, concatenates the grating segments of each
  measurement, and computes `A = -log10[(Sample - Dark) / (Background - Dark)]`,
  writing one absorbance CSV per pressure point.
- **Flexible filename ingestion**: the classic
  `vis_{DAC}_{Sample}[_{P}][_bg|_s][_C|_D][_n][.{seq}]` convention works with
  zero setup, and any other naming scheme can be taught from a single example
  file ("Name format" editor: label the pieces of a real filename, watch the
  whole folder validate live, fix or exclude stubborn files by hand, save the
  grammar as a reusable profile). Segment numbering is fully configurable —
  any separator text (with comma-separated alternatives), digits or
  letters, and a strict or assume-an-index policy for suffix-less names — and single-cell folders can default the
  DAC / sample instead of naming them in every file.
- **Removes diamond-anvil interference fringes** (FFT-notch defringe with a
  Fisher g-test acceptance gate) and applies the lab's 5-step
  Savitzky-Golay smoothing pipeline.
- Interactive plotting: overlay, inspect-one-pressure, 2D stacked,
  a filled 3D ridge view, and a continuous 3D shape surface — with camera
  presets, keyboard orbit, box-frame options, and per-axis stretch.

## Highlights

- **Multi-tab sessions**: browser-style tabs, each with independent data,
  folders, settings, and undo history — compare loads side by side.
- **Raw data table**: a resizable spreadsheet under the plot (wavelength,
  wavenumber, absorbance, raw channels, defringed and smoothed columns) with
  copy-as-TSV and open-in-Excel.
- **Journal figure presets**: one pick applies a publisher's current column
  width and house style with a WYSIWYG preview at the exact export size. 
- **Publication controls**: color-block legend keys or an automatic pressure
  colorbar for dense series, title and axis-label positioning, per-axis label
  gaps and spine widths, Crameri perceptually-uniform colormaps.
- **Traceability**: every reduction and export writes a JSON provenance
  sidecar (tool version, parameters, timestamps, file hashes).
- **A designed interface**: the SPARTA visual system — bundled Jost
  typeface (OFL), per-theme accent triads across every control, geometric
  icon set, themed title bar and top banner, a named theme set (from clean
  Standard Light and true-black to Rainbow, Coast Guard, and more), and an
  adjustable interface text size.

## New in v1.5.0

- **One defringe pipeline**: the main plot, a Run's defringed columns, every
  export and the thickness read all clean through the fringe workbench's own
  routine, vendored from Matthew R. Diamond's `defringe_dac.py`. The old
  automatic defringe module is removed, so no trace can fall through to a
  second code path that disagrees with the workbench.
- **Parity with the reference program**: the workbench notches at the measured
  peak rather than a rounded value, so a trace opened in the workbench cleans
  exactly as the main plot, the CSV columns and Matthew's own program do. His
  session files open in SPARTA and SPARTA writes ones his program can open, the
  batch notches file is merged instead of overwritten, and the pop-out window
  is a full replica of his, bound to the same model.
- **No fringe, no cleaning**: a channel with no detected fringe passes straight
  through, with no notch, no low-pass and no red curve. The panel reads "no
  fringe detected (p=...)" and shows raw and dark, with the noise floor and the
  raw-minus-dark difference on the Sample channel, which is what the reference
  program does. The main plot and the CSV columns leave that channel raw.
- **The thickness read is corroborated**: the Thickness plot reads n·t with the
  same detector the cleaning uses, where two of three detection windows must
  agree.
- **The low-pass cutoff line** drags inside its own FFT chart only, from 1 to
  200 microns, and keeps the zoom on release; a pointer that left the chart
  used to write the neighbouring chart's wavenumber into the cutoff. The region
  the low-pass removes is tinted to the right of the line, and a cutoff box
  left empty, set to 0 or given text means no low-pass, as in the reference
  program.
- **The workbench opens solved**: on the first open of a point the glyphs land
  on the tallest peak of each chart, the solve runs, and n sample, t and d2 are
  filled in. **n diamond** follows the point's pressure (Eremets model) with an
  "Ambient n (2.4168)" reset; **View > Refractive index models** opens the model
  reference; the results plot gains the Layer 2 overlays, an "As recorded"
  toggle and per-panel EoS rows; the FFT panels carry a legend of the assigned
  peaks and the 580, 640, 766 and 905 nm reference lines.
- **Nothing fails silently**: a failure inside any control is written to the log
  pane and to `sparta_errors.log` beside the program. The Defringe box repaints
  the plot on every switch, so the fringe report can no longer run first and
  strand the all-pressures plot on a channel with no detected fringe.
- **One CSV per trace**: every ticked product is a column in that trace's own
  absorbance CSV instead of a file of its own. Defringed data adds
  Absorbance_notch, Background_notch and Sample_notch; Smoothed data adds
  Absorbance_smoothed, and Absorbance_notch_smoothed as well while Defringed is
  ticked; Formula values adds one column for the active formula. The reduction
  sidecar records the columns written and the parameters behind them.
- **The Export dialog**: EXPORT > DATA FILES, the new **Export...** button
  between Run and Open output on the left panel, and **Ctrl+E** all open one
  window with the same ticks, a Crop row, a destination box with Browse, and
  Export / Open folder / Close. An export writes one `_export.provenance.json`
  beside the CSVs, and the dialog and the section report the same result.
- **C/D tag in file name** is a name rule now: ticked, every file carries `_C`
  or `_D` and the untagged twin is removed, so a folder holds one file per
  point; unticked, a name carries the letter only when the raw file name did.
- **Crop is export-only**: it lives in the dialog, trims every column, and a Run
  never applies it.
- **Retired**: the standalone `*_absorbance_notch.csv`, the `cd_tagged`
  subfolder, the "Save C/D-tagged CSVs..." button in Data > Traces, and
  "Export CSV..." on the Export tab. Load previous run still ignores the old
  notch file, so existing output folders reopen unchanged.
- **The guide is one technical register**: the guide views, the in-app Guide
  panel, the guided tour and QUICKSTART.pdf are rewritten to one plain style,
  one idea per sentence, present tense, imperative instructions. Every control
  name, default, range, unit, file name and formula is unchanged.
- **Guide typography**: a line that reads as a sentence is set as prose and
  hangs under its first line, while tables, file names and formulas stay
  monospaced and aligned. Paragraph and line spacing are even, and whole
  paragraphs that used to be frozen in the formula face are body text again.
- **My notes** is what the Guide box opens on at a first launch, the last pick
  still remembered, and **Data files** sits between Export and 3D Printing even
  on a panel whose section order was saved before that section existed.
- **Two ready-to-run downloads**: the signed-runtime package for Windows 10 and
  11, and a Windows 7 SP1 x64 package on CPython 3.8.10 for offline beamline
  machines. Both carry the same app, QUICKSTART.pdf and release notes, and
  neither needs Python, an installer or administrator rights.
- The test suite is now 780 tests.

## New in v1.4.10

- **Fringe peak fitting follows the reference routine**: dragging a band on
  the FFT places it and solves in one action, the Gaussian refinement lands
  on the measured peak instead of drifting off it, and the fit is drawn over
  the data so you can see what was matched.
- **Defringe uses each trace's own notches everywhere**: the bands you set in
  the workbench are the ones applied to the on-screen trace, to Run, and to
  every export, and a band you place by hand survives the significance gate
  instead of being dropped by it. The old **Write to defringe** step is
  retired — there is nothing left to copy across.
- **Sessions remember the workbench**: per-point notch and glyph state is
  saved with the session, points that carry saved work are marked in the
  pressure list, and a new point starts from its neighbors instead of blank.
- **New controls**: a low-pass **Edge shape** (Tanh, Erf or Hard) with a
  roll-off width; a Fringe-tab toolbar; a calculated-n row; free-text
  material names; a Y-axis dialog; a stem colormap chooser; a
  **Fundamental** radio in the notch list; neighbor hints; live dragging of
  the low-pass edge; **Reset** and drop point; and right-click, hover and
  branch markers in the results window.
- **More accurate results**: dispersion is averaged over the full detector
  grid (the fine-tier n was off by up to 5%), error bars are computed from
  the full-span signal, and data taken after November 2025 uses the correct
  fine window.
- **Faster**: the app opens about twice as fast, redraws and stepping through
  pressure points no longer recompute work that has not changed, and a
  rescan keeps the traces you had selected.
- **Ctrl+Return** runs, **Escape** cancels, and **PageUp / PageDown** step
  through pressure points. The tutorial is 71 steps.
- The test suite is now 586 tests.

## New in v1.4.9

- **Diamond fringe workbench**: a Fringe tab and a switchable centre view
  (Plot | Fringe) that reads the interference fringes in the raw spectra —
  measured |FFT| against n·t per channel, notch bands you set by clicking a
  peak, model stems with Airy harmonics, and a Solve step that returns the
  sample's refractive index and thickness with the medium and any second
  layer accounted for. Vendored from Matthew R. Diamond's `defringe_dac.py`
  with permission (MIT), refactored pandas-free and validated against the
  original to 1e-10 on real spectra. The workbench follows Matthew's own
  routine: the low-pass filter is the main tool, the notch list sits in the
  Panels menu, and there is no separate Defringe section any more — the FFT
  removal card in the Fringe tab *is* the defringe control, and the main
  plot's defringed display and the Run's defringed CSVs read from it. A
  **Detection** card holds the gates that decide when a fringe is real —
  the wavelength window (overridable per dataset), the n·t search band,
  the Fisher p gate, and how closely two of the three detection windows
  must agree. **Pop out** opens a full replica of his window — his
  sidebar, his 2x2 figure, his menus — bound to the same model, so the tab
  and the pop-out stay in step, and it fills the screen on F11 (Escape
  leaves again). Every card in the Fringe tab carries a **[?] box** with
  the maths behind it and the papers it comes from, so the model a number
  came out of is one click away.
- **3D shape**: a fourth mode in the **Stacked & 3D** box (the section
  formerly called Waterfall). Adjacent pressure traces are joined
  into one continuous gradient surface (wavelength × pressure, absorbance as
  height) you can orbit — with a filled underside, relief shading, and a
  choice of interpolation along the pressure axis. The same surface exports
  from the Export tab's **3D Printing** section as a **watertight binary
  STL** — a printable solid with closed sides and a flat base slab, with
  physical size, base thickness and Z exaggeration controls plus the usual
  provenance sidecar.
- **Thickness vs pressure** plot mode, and `α = ln(10)·A/t` and `A/t`
  as formula builtins, with sample thickness `t` available as a per-trace
  quantity in the formula editor.
- **Decompression trace controls**: line style, width, opacity and markers
  for the D branch, mirroring the compression controls across overlay,
  stacked and 3D — plus decompression-list CSV ingestion for datasets
  whose filenames carry no `_D` tag.
- **Guided tour and first-run welcome**: a game-style walkthrough that dims
  the window around whichever control is being explained and lets you click
  the real thing, driven by a small bundled synthetic demo dataset
  (`demo_data/`) so you can try the whole path before your own data is
  anywhere near it. Chapters can be skipped or jumped to, and any step that
  asks you to do something will do it for you if you would rather watch.
- **Make it yours**: a **Settings** dropdown under the top bar's gear
  gathers the chrome you set once — an **App font** picker (Jost, the
  shipped dyslexia-friendly OpenDyslexic (OFL), Comic Sans MS, Arial,
  Segoe UI and a few more, applied to the whole interface), interface
  text size, helper tips, performance mode, the tutorial and About;
  a new **Colorblind Safe Dark** theme beside the light one; a **Quick Access
  customizer** — tick which settings and one-click actions appear on
  the strip above the tabs and it follows live; and **drag-and-drop
  section reordering** — press Collapse all and every section header
  becomes a handle, so each tab ends up in the order you work in. All of
  it sticks between sessions.
- **Depth on the plot**: the legend and the colorbar now sit together
  without colliding; 2D stacked picks a separation that actually keeps
  nineteen curves apart; the colormap gains **Shades** (continuous or a
  set number of discrete **Levels**) and a **Trace colors** editor for
  setting one curve by hand; the direct labels at the curve ends take a
  size, a distance, bold and a box or halo **Backing**; and **3D shape**
  can **mark the measured traces** on the surface so real data is told
  apart from the interpolated fill. One **Graphics** dial — potato, low,
  medium, high, best — sets how many quads the sheet is drawn from, with
  relief shading and its strength, a quad **mesh**, polygon antialiasing
  and **draft quality while rotating** as separate switches beside it;
  orbiting a nineteen-trace surface draws the decimated draft while the
  mouse moves and the full surface on release. The 3D Printing section
  adds a **folder divider** shape — an upright plate whose top edge is
  one trace's silhouette — beside the surface cube.
- **Plain language everywhere**: every instructional surface — the Guide
  views, the 22-page QUICKSTART, the [?] boxes, tooltips, hints, empty
  states and the tour itself — is written to ASD-STE100 Simplified
  Technical English. One fact per sentence, one name per thing, formulas
  kept verbatim.
- **Faster**: the interface-text-size control and theme switching no longer
  pay several full re-layouts of the window. Text size and theme changes are
  roughly 2× quicker than v1.4.8 on the same machine, a registry leak that
  made every theme switch slower than the last is fixed, and the fringe
  workbench is built on first use rather than at startup.
- The test suite is now 426 tests.

## New in v1.4.8

- **SPARTA**: the program is now SPARTA — *SPectroscopic Absorption, Real
  Time Analysis* (formerly SQUISHE). Same tool, settings, and file formats;
  the About page records the lineage.
- **Generic experiment variable**: the independent variable is no longer
  hard-wired to pressure. A Series variable row in the Plot mode box offers
  Pressure (GPa), Temperature (K), Dose (Gy), Time (min), or a fully custom
  name and unit — every legend entry, colorbar, table header, inspect
  title, and 3D axis follows the choice, while CSV columns, folder names,
  and provenance keys stay exactly as before (old outputs and scripts keep
  working; exports additionally record the variable name and unit).
- **C/D-tagged CSV export**: one button writes the per-point absorbance
  CSVs with the branch in the filename (`..._C_absorbance.csv` /
  `..._D_absorbance.csv`), taken from the same compression/decompression
  state the plot shows, with a provenance sidecar.
- **Auto rescan**: a pill toggle with an adjustable interval (default 30 s)
  polls the input folder between measurements and re-reduces when new
  files appear — the live-acquisition watch mode; the manual Rescan button
  stays, and F5 or Enter in the folder box rescans on demand.
- **Quality of life**: recent-folders dropdown (and right-click) on both
  folder boxes; drag-and-drop a folder onto the window; Escape closes
  every dialog and dialogs open centered; mouse-wheel zoom in the 3D view;
  double-click a pane divider to reset it; the journal preset and the
  export file format can be remembered as defaults; interface text size
  now goes down to 3; assorted tooltips, theming fixes on two popups, and
  a repaired Ctrl+Shift+C copy-figure shortcut.
- **Formulas**: define your own quantity as ordinary arithmetic over the
  loaded columns — raw sample / background / dark counts, wavelength,
  absorbance, and the defringed and smoothed variants. The editor shows
  the real typeset formula (derived from what you type, so the picture
  cannot disagree with the arithmetic), lists problems live, and previews
  min / max / NaN as you go. Expressions are checked against a whitelist
  *before* anything runs — no names beyond the columns, no attributes,
  indexing, imports, or eval — so a rejected formula is never executed.
  A formula plots on the Y axis beside absorbance and exports as its own
  separate two-column CSVs; the absorbance CSVs a Run writes are never
  touched or extended.
- **Saved variable presets**: a custom Series name and unit can be starred
  into the dropdown, so a field, pH, or dose run is one pick next time.
- **A quieter interface**: a spacing and consistency overhaul across every
  panel (one gutter, one row rhythm, sub-headings drawn one way instead of
  three), geometric icons on the panel tabs and the main buttons, and
  rounded accent buttons for the primary actions.
- **Faster**: startup is about 40% quicker, a theme switch about 44%, and
  typing in the Name-format editor is now instant rather than
  re-parsing the folder per keystroke.
- **Eleven bug fixes**: a junk or infinite auto-rescan interval no longer
  throws (or arms a dead timer); a Variable named like a parser field no
  longer bricks the Name-format dialog; short traces and oversize
  smoothing windows no longer crash the filter, the settings dialog, or
  the smoothed export; units containing backslashes are substituted
  literally; C/D-tagged export counts traces, not colliding labels; an
  auto-rescan tick skips while a modal is open and can no longer orphan
  its own timer; a malformed file drop is rejected; and a long branch
  label, a long Variable name, and the 500-file preview cap are capped or
  disclosed instead of overflowing the layout.
- **Runs on older Tk**: a keysym missing from Tk 8.6.9 (what Python 3.8.10
  ships, and what Windows 7 machines tend to have) used to abort startup
  before the window appeared.
- The test suite is now 335+ tests.

## New in v1.4.7

- **Full control of segment numbering**: a custom name format now decides
  how grating segments are numbered. The separator can be any text
  (`.`, `-`, multi-character like `_seg`, or several comma-separated
  alternatives such as `_,-`); numbering is digits (`.001` and `.1` read
  alike, padding-agnostic) or letters (`.a` = 1, `.b` = 2,
  case-insensitive); and a name *without* a segment suffix takes a chosen
  index (default 1) or is rejected with a logged reason. A blank
  separator means the convention has no segment numbers at all. "Guess
  format" detects the folder's segment convention on its own, and the
  per-file Fix dialog can override the segment index by hand.
- **Teach by example, decomposed**: the Name-format editor now shows the
  prefix, every separator, and the segment suffix in place, each labeled,
  so an unfamiliar filename scheme is legible at a glance.
- **Default DAC / sample**: single-cell folders whose names never carry a
  DAC (or sample) piece can drop that token from the order and supply the
  value as a profile default instead.
- **Readable fields in every theme**: fixed a theme-switch bug that could
  leave input-box text invisible on light or dark backgrounds.

## New in v1.4.6

- **Deep export control**: "Also save" writes PNG/PDF/SVG/TIF in one
  Save; "Editable text" embeds journal-safe TrueType (fonttype 42) in
  vector exports; a grayscale print-check copy; a file-name template;
  tool-version metadata inside PNG/PDF/SVG; and batch export now solos
  each trace on the fully styled figure in a chosen format.
- **Placement freedom**: legend, title, and colorbar all have live X/Y
  readout boxes (type both values to pin a custom position); the
  colorbar docks right/left/top/bottom; more legend locations including
  outside left/top/bottom; the legend auto-fits oversized entries on
  export (with an off switch) and writes the values it used back into
  the panel.
- **Text styling**: Bold/Italic per element (title, axis labels, ticks,
  legend, colorbar), tick number formats (fixed decimals or scientific),
  X tick rotation (including the top axis), a page footnote, and a 2D
  inset-zoom panel for absorption-edge close-ups.
- **Accessibility**: High Contrast and Colorblind Safe (Okabe-Ito)
  themes; legend and 3D pane colors now follow the actual plot page
  rather than the interface theme.
- **3D parity and presets**: X pos / Y pos / Flip Y now work in 3D, and
  Nature/Science/APS 3D journal presets style the whole 3D scene the way
  those journals print it.
- **Interface**: Quick Access, Progress, and Guide cards collapse;
  panel-divider drags and pane toggles are much faster (debounced
  redraws); theme switching is twice as fast.
- **SQUISHE everywhere**: the repository is now
  `github.com/NoisySnooper/SPARTA` (the old SQUISHE URL redirects), the macOS
  bundle builds as `SQUISHE.app`, and the Windows package launcher is
  `SQUISHE.exe`.

## New in v1.4.5

- **Themes, expanded**: a named theme set in the top-bar Theme menu —
  Standard Light, Flashbang White, Kinda Dark, Black Hole, and the accent
  themes Semper Paratus, Touch Grass, Pink Pony Club, Davy Jones, New
  Mexico, Ocean, Rainbow, Synthwave, Christmas, and Tet — each with a
  themed top banner and per-section accent colors down the settings panels.
- **Sturdier reduction**: a data-integrity pass — grating channels aligned
  by wavelength (not array index), tolerant file decoding, non-finite
  pressures rejected, and a re-entrancy guard so a mid-run rescan can't
  corrupt output — with the test suite grown to 53.
- **3D axis frame** now genuinely draws on top at every camera angle
  (occlusion-proof), and an all-hidden 3D view shows a themed empty state
  instead of a blank white box.
- **Interface polish**: readable dropdown lists in every theme, uniform
  button spacing, a grab handle on each panel divider, and field text that
  stays legible on light fields in dark themes.

## New in v1.4.4

- **Direct labels at curves**: label every curve at its end with its
  pressure, in the trace color, instead of a legend box (2D overlay,
  2D stacked, and 3D ridge).
- **Legend frame control**: border opacity independent of background
  opacity, edge color, and up to 16 columns.
- **"3 axes" box frame** is the new 3D default: the classic matplotlib
  look with just the x / y / z tick axes facing you, always drawn on top
  so ridge walls can't hide them; custom mode can force them into any
  edge mix.
- In-app guide, About page, and tooltips brought up to date with all of
  the above (and stale claims removed).

## New in v1.4.3

- **Work the plot directly**: click a curve to select it, double-click to
  solo it, click a legend entry to hide it, right-click a curve for quick
  actions (inspect that pressure, hide, mark decompression, defringe
  compare, open the data table) that drive the matching panel controls.
- **Guess format**: the Name format dialog can read the input folder and
  propose the whole filename grammar automatically; correct anything wrong
  in the live preview, then adopt it.
- **Quality flags**: every reduced point gets quick checks (saturation,
  missing channels, negative absorbance); flagged traces show a colored
  dot with the reason on hover.
- **Rescan** re-reduces only when new files appeared in the input folder
  (the between-measurements top-up), and **defringe compare** overlays the
  selected trace's pre-defringe curve in gray.
- **Adaptive interface**: text size follows screen resolution and Windows
  display scale (manual 9-15 override), DPI-proof panel widths, a flat
  hairline-card look, and a themed-plot-background toggle.
- **3D box & panes**: frame modes (open front, floor only, custom
  per-edge), frame shade and width, pane color and opacity; "none" now
  removes every edge.
- Smoothing defaults retuned on real 22-IR-1 spectra (Savitzky-Golay
  windows 201/101 -> 101/51: keeps ~97% of the noise suppression at a
  third of the absorption-edge distortion; the other steps stay verbatim
  Igor).

## Run from source

```
pip install -r requirements.txt
python app.py
```

Or double-click `run.bat`. Windows 10/11; the bundled Jost typeface loads
privately at startup (no font installation).

## Build a standalone .exe (no Python needed on the target PC)

```
python -m venv build-env
build-env\Scripts\activate
pip install -r requirements.txt
pyinstaller beamline_tool.spec
```

The result is a self-contained folder at `dist\SPARTA\`. Ship the whole
folder. A onedir build (rather than a single packed .exe) is used
deliberately: it starts faster and is far less likely to be flagged by
antivirus / SmartScreen. If SmartScreen warns on first launch (expected for
any unsigned exe): More info -> Run anyway.

## Files

| File | Purpose |
|------|---------|
| `app.py` | GUI, plotting, all controls |
| `engine.py` | parse / concatenate / absorbance / naming profiles / CSV + provenance |
| `formulas.py` | the formula registry and its whitelist evaluator |
| `fringe_apply.py` | the one defringe entry point: clean a channel from a recipe, build the notch columns |
| `fringe_*.py` | the vendored fringe core: optics, detection, notches, fits, stack, multiscale variance, materials + EOS |
| `fringe_panel.py` | the Fringe workbench: FFT view, cards, solve, series |
| `fringe_popout.py` | the pop-out replica of the original window |
| `export3d.py` | surface grid, relief shading, watertight binary STL |
| `guide_tour.py` | the guided tour, the welcome card, the guide loader |
| `ui_prefs.py` | App font, section order, Quick Access pins |
| `smoothing.py` | 5-step smoothing pipeline |
| `colormaps.py` | Crameri + matplotlib colormaps |
| `decomp.py` | known decompression-pressure sets |
| `demo_data/` | the bundled synthetic dataset the tour runs on |
| `docs/guide_content/` | the Guide panel's views, plus QUICKSTART.pdf |
| `fonts/` | Jost and OpenDyslexic typefaces (OFL licenses included) |
| `tests/` | pytest suite (parser, engine, sessions, plotting, fringe, UI) |
| `beamline_tool.spec`, `version_info.txt` | PyInstaller build config |

## Version history

- **v1.5.0**: one defringe pipeline, vendored from Matthew R. Diamond's
  program, for the main plot, a Run, every export and the thickness read,
  with the old automatic defringe module removed; the workbench notches at
  the measured peak so it agrees with the plot and the CSVs, a channel with
  no detected fringe is left raw everywhere, and the Thickness plot reads
  n·t with the corroborated detector; the low-pass cutoff line drags inside
  its own chart only and the region it removes is tinted; a failure inside
  any control is logged instead of silent; every ticked product is now a
  column in that trace's own absorbance CSV, written by a Run or by the new
  Export dialog (EXPORT > DATA FILES, the Export... button, Ctrl+E), with
  C/D as a file-name rule and Crop as export-only; the standalone notch CSV,
  the cd_tagged subfolder and "Export CSV..." are retired; the guide, Guide
  panel, tour and QUICKSTART.pdf are rewritten to one technical register with
  prose and verbatim text set apart; suite grown to 780 tests.
- **v1.4.10** — fringe peak fitting reworked to the reference behavior (a
  drag places the band and solves, the Gaussian refinement lands on the
  measured peak, fit overlays drawn); defringe now applies each trace's own
  workbench notches to the display, to Run and to every export, and
  hand-placed bands survive the significance gate, so **Write to defringe**
  is retired; sessions store per-point notch and glyph state, mark saved
  points in the pressure list and seed a new point from its neighbors; new
  controls — low-pass Edge shape (Tanh / Erf / Hard) with roll-off width, a
  Fringe-tab toolbar, a calculated-n row, free-text material names, a Y-axis
  dialog, a stem colormap chooser, a Fundamental radio in the notch list,
  neighbor hints, live low-pass dragging, Reset and drop point, and
  results-window right-click / hover / branch markers; accuracy fixes
  (dispersion averaged over the full detector grid, where the fine-tier n
  was off by up to 5%; error bars from the full-span signal; the correct
  fine window for post-November-2025 data); about 2× faster startup, with
  unchanged redraws and pressure-point steps no longer recomputed and trace
  selections kept across a rescan; Ctrl+Return to run, Escape to cancel,
  PageUp / PageDown to step points; tutorial grown to 71 steps; suite grown
  to 586 tests.
- **v1.4.9** — diamond fringe workbench (Fringe tab, Plot | Fringe centre
  switch, Detection gates, notch bands, Airy model stems, Solve for n and
  t, per-card [?] maths, and a pop-out replica of the original window with
  F11 full screen), vendored from Matthew R. Diamond's `defringe_dac.py`
  with permission and validated against it to 1e-10; 3D shape surface with
  measured-trace marking, relief shading and strength, a potato-to-best
  Graphics dial, mesh / antialias / draft-while-rotating switches, and
  watertight binary STL export including a folder-divider shape;
  thickness-vs-pressure mode with `α = ln(10)·A/t` and `A/t` builtins;
  decompression trace controls and decompression-list CSV ingestion;
  guided tour, first-run welcome and a bundled synthetic `demo_data/`;
  a top-bar Settings dropdown with an App font system (Jost, OpenDyslexic,
  and more), Colorblind Safe Dark, a Quick Access customizer and
  drag-and-drop section reordering; legend / colorbar coexistence, colormap Shades and Levels, a Trace
  colors editor and backed direct labels; every instructional surface
  rewritten to ASD-STE100 Simplified Technical English with a 22-page
  QUICKSTART; ~2× faster text-size and theme changes; suite grown to
  426 tests.
- **v1.4.8** — SPARTA rebrand (formerly SQUISHE); generic experiment
  variable (pressure/temperature/dose/time/custom name+unit driving every
  label, file schema unchanged) with starrable saved presets; user-defined
  formulas (typeset preview, whitelist-checked expressions, separate
  two-column CSV export); C/D-tagged CSV export; auto-rescan watch
  mode with adjustable interval plus F5/Enter manual rescan; QoL batch
  (recent-folders dropdowns, folder drag-and-drop, Escape + centering on
  all dialogs, 3D wheel zoom, divider double-click reset, journal-preset
  and export-format memory, text size to 3, shortcut and theming fixes);
  spacing and consistency overhaul with tab/button icons and rounded
  accent buttons; ~40% faster startup, ~44% faster theme switch, instant
  Name-format typing; eleven bug fixes; Tk 8.6.9 / Windows 7 startup fix;
  suite grown to 335+ tests.
- **v1.4.7** — full user control of grating-segment numbering in custom
  name formats (any separator incl. multi-character and comma-separated
  alternatives, digit or letter schemes, missing-suffix policy incl.
  reject, guesser detection, per-file segment override); Teach-by-example
  decomposition (prefix, separators, and segment suffix shown in place);
  default DAC/sample for tokens the names never show; theme-visibility fix
  keeping field text readable in every light and dark theme.
- **v1.4.6** — deep export control (multi-format save, TrueType vector
  text, grayscale check, metadata, styled batch); live X/Y placement
  with pinning for legend/title/colorbar; colorbar docking; per-element
  Bold/Italic, tick formats and rotation; footnote and 2D inset zoom;
  High Contrast + Colorblind Safe themes; 3D setting parity and 3D
  journal presets; collapsible left-panel cards; major responsiveness
  work; SQUISHE naming everywhere (repo, SQUISHE.app, SQUISHE.exe).
- **v1.4.5** — expanded, named theme set with themed banners and
  per-section accent colors; data-integrity hardening (channel
  wavelength-alignment, tolerant decoding, re-entrancy guard) and a
  53-test suite; occlusion-proof 3D axis frame; readable dropdowns in
  every theme and interface polish.
- **v1.4.4** — direct trace labels (2D + 3D); independent legend border
  opacity and up to 16 columns; "3 axes" box frame (new 3D default,
  occlusion-proof); refreshed in-app guides.
- **v1.4.3** — clickable plot (select / solo / hide / right-click quick
  actions); filename-grammar auto-guess; per-point quality flags; Rescan;
  defringe compare; adaptive text size and DPI-proof layout; hairline-card
  design; 3D box-frame and pane controls; smoothing defaults retuned for
  22-IR-1.
- **v1.4** — SQUISHE rebrand and visual system; multi-tab sessions; flexible
  filename ingestion; raw data table; journal presets with WYSIWYG preview;
  provenance sidecars; 2D/3D view controls; 43-test suite.
- **v1.3** — reference-guide planes, log-Z ridge, locked trace colors,
  legend/colorbar styling split, adjustable defringe gates.
- **v1.2** — FFT-notch defringe (contributed by
  [Matthew Diamond](https://github.com/matthewrdiamond)); 3D ridge stretch,
  camera presets, projections.
- **v1.1** — per-item text sizes, colorbar customization, performance mode.

## Credits

- Written by Nhan Ta, Dr. Lee's Lab, NSLS-II 22-IR-1.
- The fringe-analysis core is Matthew R. Diamond's `defringe_dac.py`,
  vendored with his permission (MIT) and refactored pandas-free; the
  workbench follows his own routine:
  [github.com/matthewrdiamond/DAC-Absorption-Fringe-Analysis](https://github.com/matthewrdiamond/DAC-Absorption-Fringe-Analysis)
- The FFT-notch defringe method contributed by
  [Matthew Diamond](https://github.com/matthewrdiamond).
- Developed in Dr. Kanani K. M. Lee's lab for NSLS-II beamline 22-IR-1.

## License

[MIT](LICENSE). The bundled Jost and OpenDyslexic typefaces are licensed
separately under the SIL Open Font License 1.1 (`fonts/OFL.txt`,
`fonts/OFL-OpenDyslexic.txt`).
