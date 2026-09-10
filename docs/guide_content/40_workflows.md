WORKFLOWS

Recipes by goal, each assuming a folder is loaded.


A PUBLICATION OVERLAY FIGURE

  1. Run the folder and check the trace count in the log.
  2. DATA > TRACES: tick the traces for the figure. 'Lock colors to
     all datasets' in STYLE > COLORS & COLORMAP holds the colors.
  3. EXPORT > FIGURE: pick the journal preset for your column width.
  4. EXPORT > EXPORT: 'Preview at export size (WYSIWYG)' shows the
     figure at its printed size.
  5. Up to about ten traces use STYLE > LEGEND, Location 'outside
     right'; above that, STYLE > COLORBAR or 'Direct labels at
     curves'.
  6. STYLE > TITLE & AXIS LABELS: override the default labels for a
     house form. Mathtext works: $\lambda$ (nm), Fe$^{2+}$.
  7. Save the plot as PDF with 'Editable text' on; 'Also save' adds
     PNG, and 'Grayscale copy' a mono version.
  8. 'Export settings', under Progress, prints the configuration
     into the log for the methods section.


DEFRINGED COLUMNS FOR IGOR OR ANOTHER TOOL

  1. Tick df beside the plot to see the cleaned curves; the df
     switch changes the plot only.
  2. Read the fringe report in the log: the traces with a detected
     fringe, the fitted n*t in micron, and the p-value.
  3. Check one trace with 'Defringe compare (selected trace)' in
     PLOT > 2D PLOT OPTIONS, then click a curve; the gray dashed
     line behind it is the pre-defringe absorbance. Narrow the
     half-width in FRINGE > FFT REMOVAL > Notch list when the notch
     took out real structure, widen it when fringes survive.
  4. EXPORT > DATA FILES: Defringed data is ticked by default, so a
     Run writes the columns. For a folder already loaded, press
     'Export...' in the left panel, or Ctrl+E, and Export in the
     dialog.
  5. Each trace's CSV then carries Absorbance_notch,
     Background_notch and Sample_notch after the base columns. Each
     trace follows its own notch list, the rest the global controls.


SMOOTHED COLUMNS

  Tick Smoothed data in EXPORT > DATA FILES, then Run or open the
  Export dialog. Each trace's CSV then carries Absorbance_smoothed,
  and Absorbance_notch_smoothed while Defringed data is on. Tune the
  filter first in DATA > SMOOTHING > 'Smoothing settings...'. Crop,
  in the Export dialog, limits one export to a wavelength range.


THICKNESS VERSUS PRESSURE

  1. Tick df beside the plot. The detection supplies n*t.
  2. Check the fringe report; the 'mark misses' triangles show the
     traces without a detection.
  3. PLOT > PLOT MODE: switch to Thickness (fringe n*t). Sample
     points are filled circles, background points open squares;
     the S / B boxes pick the channels.
  4. For solved physical thickness, take the traces through the
     fringe workbench: describe the stack, assign roles, Solve,
     Record point. 'Results vs pressure...' in FRINGE > SESSION
     plots the solved values.


COMPARING COMPRESSION AND DECOMPRESSION

  1. Set the branches. An explicit _C / _D tag in the filename
     wins, and ten historical experiments are recognised. Otherwise
     tick the D box per trace in DATA > TRACES.
  2. 'Decompression list...' in DATA > TRACES reads a CSV or text
     file of decompression values: a pressure_GPa column or plain
     numbers, 'p' allowed as the decimal. Each value takes the
     nearest loaded trace within 0.05.
  3. Read the branches apart with 'Only C' and 'Only D'.
  4. Overlay both. The Decompression traces controls in PLOT > 2D
     PLOT OPTIONS draw the D branch dashed under 'Style D traces
     apart', with its own width, opacity and markers.
  5. STYLE > LEGEND: rename 'C' and 'D' in the two small boxes. The
     rename is display only; the file names and the D list keep C
     and D.
  6. 'Export D list (CSV) by selection' writes the branch assignment
     back out.
  7. Tick C/D tag in file name in EXPORT > DATA FILES to put the
     branch letter into every output file name. There is no second
     copy and no subfolder.


A CUSTOM QUANTITY, PLOTTED AND EXPORTED

  1. DATA > FORMULAS: press New..., name it and give it a unit. The
     name labels the Y axis and the CSV column.
  2. Write the expression over the loaded columns. A problems list
     and a live min / max / NaN preview update as you type; Save
     stays disabled until the formula is clean.
  3. Tick df when the formula uses Sf, Bf or Af, and 'Show
     smoothed' when it uses As. A missing column is reported and
     leaves a gap.
  4. Save, then click the dot beside the row. The formula becomes
     the Y axis ('formula: <name>').
  5. 'Save formula CSVs...' writes one two-column file per trace:
     wavelength plus the formula, with the expression in the header
     comments. Ticking Formula values in EXPORT > DATA FILES adds
     the formula as one column of each trace's CSV instead, on every
     Run and every export.


LIVE ACQUISITION AT THE BEAMLINE

  1. Run once as soon as there are a few measurements.
  2. PLOT > PLOT MODE: turn on Auto rescan, at roughly your
     measurement cadence.
  3. The status line under the plot reads 'auto-rescan: N s' while
     the timer is armed; a tick that finds new files re-reduces the
     folder.


COMPARING TWO DATASETS SIDE BY SIDE

  1. Press Ctrl+T for a new session tab, with its own data, folders,
     settings and undo history.
  2. Load or Run the second dataset there. The tab names itself
     after the folder, and a double-click renames it.
  3. Ctrl+Tab cycles. Style one tab, save it as a preset in
     EXPORT > PRESETS & PROJECTS, and load it in the other.


COMING BACK TO A SESSION LATER

  The curves alone: 'Load previous run...' on the left panel,
    pointed at the output subfolder a Run wrote.

  The styling: EXPORT > PRESETS & PROJECTS, pick the preset and
    Load. A preset carries the plot controls only.

  Everything: 'Open project...', which is every setting plus the
    input and output folders, in one .json.
