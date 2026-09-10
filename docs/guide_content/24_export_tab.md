EXPORT TAB

The Export tab writes figures, data files and printable solids, and
records the settings behind each file.


EXPORT > PRESETS & PROJECTS

  A preset saves the whole control state under a name. Pick it in
    the dropdown and click Load. 'Save as...' names a new one, and
    Delete removes it. A preset stores styling only.

  A project stores the same state plus the input and output folders,
    in a .json file. Use 'Save project...' and 'Open project...' to
    put an analysis back on screen.

  'Reset all' on the control bar at the top of the panel resets
    every plot control. It asks first, and it keeps the loaded data
    and the folders.


EXPORT > FIGURE

  Journal preset: sets a publisher's column width and house style:
    typeface, text sizes, line weight, spines, ticks and DPI.

      Nature single / double        89 mm / 183 mm, Arial
      Science 1 / 2 / 3-col         5.7 / 12.1 / 18.4 cm, Arial
      RSI / AIP 1 / 2-col           3.37 / 6.69 in, Arial
      APS 1 / 2-col                 3.4 / 7.0 in, serif
      Elsevier 1 / 2-col            90 mm / 190 mm, Arial
      Nature 3D single / double     as above, plus the 3D scene
      Science 3D 2-col              as above, plus the 3D scene
      APS 3D 2-col                  as above, plus the 3D scene
      Clean style                   grid off, thin spines
      Square (5 in), Wide (10x4 in) size only

    Clean style keeps your own size and fonts. The 3D presets also
    style the scene: minimal 3-axes frame,
    panes and grid off, a colorbar instead of a legend, and a
    standard camera.

  Set as default: applies the preset at every launch. The star marks
    the saved preset.

  W x H in plus Apply: a custom figure size. Type in either box and
    press Return.

  Transparent background: saves with a transparent page (PNG / SVG /
    PDF). It overrides the face color.

  Tight bounding box: trims the surrounding whitespace on export.

  Pad (in): the margin kept around a tight box.

  Face: the page background on export. Pick auto (the current
    theme), white, black, or 'none' for a transparent page.

  The typeface and the per-item text sizes are in STYLE > FONTS and
    beside each text item.


EXPORT > EXPORT

  DPI: 72 to 600, used by Save plot and Copy figure. Journal presets
    set 300.

  Copy figure: puts the figure on the clipboard as an image, at the
    Figure size and this DPI. Ctrl+Shift+C.

  Preview at export size (WYSIWYG): renders the figure at the exact
    export width and height, so the printed proportions and text
    size show before saving. Off fills the window.

  Also save PNG / PDF / SVG / TIF: one Save writes every ticked
    extra format beside the file you name, with the same base name.

  Editable text: vector exports embed real TrueType text (fonttype
    42), which Illustrator and Inkscape can edit. Off outlines the
    text as paths. It is on by default.

  Grayscale copy: also writes <name>_grayscale.png, to check that
    the curves separate in print.

  Open after: opens the saved file in its default viewer.

  Name: the suggested file name for Save plot. The tokens are {tab}
    {mode} {wf} {preset} {cmap} {date}. The default is
    {tab}_{mode}_{date}.

  Save plot...: PNG, PDF, SVG, EPS or TIFF. SPARTA offers the format
    you saved last. PDF and SVG are vector, and PNG, PDF and SVG
    carry the SPARTA version in their metadata.

  Batch export (one per shown trace)...: solos each shown trace on
    the figure and writes one file per trace, in png, pdf, svg or
    tif. The styling is the current one: mode, labels, fonts and
    journal size.

  Provenance sidecars
    Every reduction and every export writes a JSON sidecar beside
    its output. The reduction sidecar is _reduction.provenance.json.
    It records:
    - the program name and version
    - the timestamp
    - the input folder and the output subfolder
    - the absorbance definition, spelled out
    - the series variable's name and unit
    - how many curves were written
    - whether defringe was on, and with which parameters
    - the columns written and the parameters behind them
    - every curve's identity label and value

    Export sidecars record the same shape for the batch they cover.

  'Export settings' in the left panel's Progress card prints the
    current plot configuration into the log.


EXPORT > DATA FILES

  One list of columns, under the header 'Include in each trace's
  CSV:'. SPARTA writes one CSV per trace,
  {DAC}_{sample}_{value}[_C|_D]_absorbance.csv, and these ticks say
  what it holds. A Run writes them at the end of a reduction. The
  Export dialog writes the same columns again, for every loaded
  trace, into a folder you pick.

  Absorbance data (always): the reduction's base columns,
    Wavelength_nm, Wavenumber_cm-1, Absorbance, Dark, Background and
    Sample. The row is ticked and disabled, because Run always
    writes them.

  Defringed data: adds Absorbance_notch, Background_notch and
    Sample_notch, from FFT-notch cleaning at each trace's own notch
    list in FRINGE > FFT REMOVAL, or at the global controls.
    Absorbance_notch is always filled. A channel with no detected
    fringe leaves its two channel columns blank. The df switch
    changes the plot only. Default on.

  Smoothed data: adds Absorbance_smoothed, and
    Absorbance_notch_smoothed while Defringed data is on, at the
    current DATA > SMOOTHING settings. Default off.

  Formula values: adds one column with the active formula from
    DATA > FORMULAS. The header is the formula key, with its unit in
    brackets when one is set. With no formula active the column is
    skipped and the log says so. Default off.

  C/D tag in file name: puts _C or _D in every file name, after the
    D toggles and the D list. Off, a name carries the letter only
    when the raw file name did. Default off.

  The extra columns follow the base set in that order. Nothing is
    written beside the trace's CSV: the notch columns that used to
    go into {stem}_absorbance_notch.csv now sit in the CSV itself,
    and the cd_tagged subfolder is gone.

  'Export data...' opens the Export dialog. The left panel's
    'Export...' button, between Run and Open output, and Ctrl+E open
    the same dialog. It is modal, and Escape closes it.

  In the dialog:
    - Columns holds the same five rows, bound to the same ticks as
      this section.
    - Crop plus min / max nm keeps only the rows inside a wavelength
      range, in every column, with the low and the high edge in nm.
      It applies to that export alone, never to a Run, and it is not
      remembered.
    - Destination plus Browse says where the CSVs go. It opens on
      the last Run's output folder, then on the Output folder, then
      on the Input folder.
    - The note line reads 'These ticks also set what Run writes.'
      With no traces loaded it reads 'No traces loaded. Run a folder
      first.' and Export is disabled.
    - Export writes the files and reports in the dialog's status
      line, in this section's status line and in the log. Open
      folder opens the destination, and Close leaves the dialog.

  The dialog covers the loaded traces, not the shown ones, so it
    puts the same columns on disk as a Run.

  The status line under the button reports the last write: how many
    traces, which columns and where they went. The per-file lines
    are in the log.

  An export writes one sidecar, <folder>/_export.provenance.json,
    of kind "data_files", holding the columns written, the
    parameters behind them, the crop, the C/D names and the trace
    count. A Run merges the same columns block into
    _reduction.provenance.json.

  The four ticks below Absorbance data are saved in the settings
    file. They are output preferences, so a preset and a project
    leave them alone. 'Save formula CSVs...' in DATA > FORMULAS
    still writes the picked formula on its own.


EXPORT > 3D PRINTING

  This section writes the plotted data as a solid object for a 3D
  printer. SPARTA rebuilds the geometry from the data at export.

  Shape: 'Surface cube' makes the data the top face of a block, with
    four walls dropping to a flat base. It takes three or more shown
    traces. 'Folder divider' makes one shown trace the top edge of a
    thin upright plate on a wider foot.

  The export covers the shown traces, on the plotted Y channel, at
    the X unit on screen, with the plot's smoothing and defringe
    applied. The Y channel is absorbance, a raw channel or a
    formula.

  Size X/Y (mm): the footprint. X runs along the spectral axis, Y
    along the series axis. SPARTA stretches the data to fill it.
    80 x 80 is a desk object.

  Height Z (mm): the total height at exaggeration 1, base plus
    relief.

  Base (mm): the slab under the surface. It keeps the lowest data
    from printing as foil. 6 mm is a safe floor for most printers.

  Z exaggeration: multiplies the relief above the base. 2 doubles
    every feature. The base keeps its thickness.

  Plate (mm): the thickness of the divider plate. 2 mm prints solid
    on a standard nozzle.

  Foot (mm): the depth of the foot under the divider. It runs wider
    than the plate. 14 mm holds an 80 mm plate upright.

  One file per trace: one divider per shown trace into a folder,
    each file named after its trace. Clear the box for a single
    file, from the trace selected on the plot.

  The Plate, Foot and One file per trace rows appear for the folder
    divider. For that shape Size X is the plate width, Height Z its
    total height, and Base the height of the foot. Size Y belongs to
    the cube. The lowest point of the trace keeps 1 mm of plate
    above the foot.

  Export STL...: writes binary STL in millimetres, which every
    slicer reads.

  Mesh check
    SPARTA checks the mesh before it writes. Every edge carries two
    triangles wound in opposite directions, the enclosed volume is
    positive, and

      V - E + F = 2

    A failed check stops the write, and the log names the failure.

  The status line reports the triangle count, the watertight result
    and the file size. The log adds the grid size, the traces, the
    proof numbers, the physical dimensions and the millimetres per
    plotted unit.

  The <name>.stl.provenance.json sidecar holds the version, the
    timestamp, the input folder, the series variable, the grid
    recipe (interpolation, columns, rows, every series value), the
    physical mapping and the watertightness numbers.

  Printing notes
    Fringes and noise print as thin fins that snap off. Turn on
    Smoothing, or tick df, before exporting.
    A large Z exaggeration on a thin base tips over. Raise the base
    when you raise the relief.
    The lowest value sits on the base, so the slab stays solid under
    a negative baseline.

  A file runs about 50 bytes per triangle. The default grid is
  roughly 90 000 triangles, or 4 MB.
