PLOT TAB

This tab sets what is drawn and how the traces are arranged. Each of
its four sections folds shut by its title. Type a control's name into
'Find a setting' at the top of the panel to open the right section.


PLOT > PLOT MODE

  Series variable: what the number in each file name means. Pick a
    preset (Pressure GPa, Temperature K, Dose Gy, Time min) or
    Custom... for your own name and unit. The colorbar label, the
    legend entries, the 3D depth axis, the inspect title and the
    data table header follow the choice. Only the labels change: the
    parsed values, the CSV columns, the output file names and the
    provenance keys stay as they are.
    The star beside the custom boxes saves that name and unit pair
    into the dropdown. Click the lit star to remove it. A blank unit
    prints values as bare numbers.

  Auto rescan plus every N s: one timer for the whole program, 5 to
    3600 s, default 30, remembered between launches. It waits for
    the first Run, fires while SPARTA is idle, and re-runs the
    folder when new files appeared.
    While it is armed the status line under the plot reads
    'auto-rescan: N s'. A tick that finds new files says so in a
    toast. Changing the interval restarts the timer. Rescan and F5
    still work by hand.

  Overlay all traces: every shown trace on one set of axes. The Y
    axis row in AXES > AXIS picks what it plots.

  Inspect one trace: Sample, Background and Dark counts on the left
    axis, and that trace's Absorbance on the right. Inspect picks
    the trace, and Channels S / B / D / Abs picks which curves draw.
    The right-hand axis takes the same theme styling as the main
    axis.

  Thickness (fringe n*t): one point per shown trace, the optical
    thickness n*t against the Series variable. The value is the
    fringe frequency the detector finds in the raw counts, so the
    notch list has no say in it. Two of the three search windows
    agree on n*t before a number is reported. Sample points are
    filled, background points open, and D traces keep their own
    style.
    The Thickness row picks the channels drawn (S / B). 'mark
    misses' puts a small open triangle above the axis wherever the
    detector searched and missed. 'join points' unticked leaves a
    plain scatter. 'Thickness table...' lists n*t and the p-value
    per trace.

  Absorbance readout at...: type a wavelength in nm for a table of
    the absorbance there, for every shown trace. 'on click' does the
    same from a left-click on a 2D plot.


PLOT > STACKED & 3D

  Mode
    - off: every trace on a shared baseline.
    - 2D stacked: each trace shifted up by Offset/step.
    - 3D ridge: x = wavelength, depth = series value, height =
      absorbance. A filled joyplot.
    - 3D shape: the same scene with the ridges joined into one
      continuous surface, orbited live. Every 3D plot option still
      applies: camera, stretch, label gaps, axis ranges.

    Keys 1 / 2 / 3 / 4 switch between them, except while you type in
    a box.

  Offset/step: in 2D stacked, the vertical gap between successive
    curves. In 3D ridge with 'Even rank spacing' on, how far apart
    the ridges sit along the series axis. Default 0.2.

  Auto: picks a step that spreads the shown ridges evenly, and turns
    'Even rank spacing' on to hold it. In 2D stacked it measures the
    gap the shown curves need and writes that into Offset/step.

  Auto separation (2D stacked): sets the stacked gap from the shown
    traces. SPARTA compares each curve with the next, clears the
    largest overlap by 6 percent, and prints the gap beside the box.
    Clear this box to use your own Offset/step. It is on by default.

  Label each ridge with its value: writes the series value beside
    each ridge.


PLOT > 2D PLOT OPTIONS

  Line style: solid / dashed / dotted / dash-dot for the 2D curves.

  Decompression traces, a sub-heading in this section, holds the
    same style controls for D traces alone. The default is dashed at
    the compression width.

    - Style D traces apart: the master switch. Untick it and a D
      trace looks like a C one.
    - Line style: solid / dashed / dotted / dashdot / custom /
      bicolor.
    - Pattern: the dash sequence in points, on/off alternating
      ('6, 3'), used while Line style is 'custom'.
    - Second color: the stripe's second ink, shown only while Line
      style is 'bicolor'. 'auto' takes the high-contrast ink for the
      page: white on a dark page, near-black on a white one. A color
      name or a hex code also works.
    - Width: points; blank follows Curve line below.
    - opacity: 0 to 1, on the same row as Width.
    - Marker: a point marker on every D trace, with its size box
      beside it, in points.

    Bicolor keeps the trace's own color and dashes a second color
    over it, half and half along the curve, at a stripe length that
    follows the line width. It draws in overlay, 2D stacked, the 3D
    trace lines and the Thickness plot. On a filled 3D ridge it
    draws dashed. The legend keys reflect these controls, and a
    bicolor trace gets a hatched two-color swatch. SPARTA remembers
    them between launches.

  Inset zoom: magnifies an X range in a corner panel. Type the two
    wavelengths, then pick the corner and the size fraction (0.15 to
    0.5). SPARTA outlines the zoomed region on the main plot. 2D
    overlay and stacked.

  Defringe compare (selected trace): with df ticked, click a curve
    to select it, and its pre-defringe absorbance draws behind it as
    a gray dashed line.

  Curve line: line width for the 2D curves, in points. Type a value
    or drag. Right-click resets it.

  Aspect ratio: the shape of the plot box. Pick Auto (fill the
    area), 1:1, 4:3, 3:2, 16:9, or custom W:H.

  View: a pan pad with Fit in the middle. Hold a button to repeat.
    Fit X / Fit Y refit one axis. Zoom +/- acts about the view
    center, on X, Y or both. Arrows pan, +/- zoom and 0 fits, except
    while you type in a box. Drag a box on the plot to zoom into it.
    The wheel zooms at the cursor.


PLOT > 3D PLOT OPTIONS

  Camera
    Elevation (0-90 degrees above the horizon), Azimuth (-180 to
    180), Zoom (0.5 to 2.0, camera distance).
    View presets Iso / Front / Side / Top snap the camera, and Reset
    returns to the default.
    Arrow keys orbit three degrees a step. The +/- keys zoom, 0
    resets, and the wheel drives the camera.

  Box & panes
    Box frame picks which of the twelve box edges draw:

      open front  the corner facing you stays open
      3 axes      the x, y and z tick axes facing you, the default
      closed      all twelve edges
      floor only  the four bottom edges
      no top      everything but the top rim
      none        no edges at all
      custom      unlocks the Edges checkboxes

    '3 axes' draws on top at every camera angle, so ridge walls
      cannot hide it.
    Edges (active only in 'custom'): 3 axes / floor / posts / top /
      open front. '3 axes' can be forced on top of any mix.
    Frame shade: edge color. 'auto' follows the theme's axis color.
    Frame width: edge thickness.
    Panes: the three back walls. Pick grid / white / theme / light
      gray / off, with their own opacity. Dark themes keep dark
      panes. The gridline styling sits in AXES > FRAME & GRID.

  Ridges
    3D look: walls + traces (filled ridges with outlines), walls
      only (filled, no outline), traces only (outlines, no fill),
      surface (one continuous sheet).
    Surface joins adjacent traces into a single gradient sheet:
      wavelength across, the series value into the page, the plotted
      channel as height. The height between two measured values is a
      straight line. SPARTA trims wavelengths that any shown trace
      is missing off both ends, and bridges a dropout inside a trace
      from that trace's own neighbours.
      The sheet takes its colour from the colormap by series value,
      so the colorbar still reads correctly. Z limits, Log Z, Clip Z
      spikes, Even rank spacing, Project and 3D detail all apply.
      The outline controls and Fill opacity do not.
      Three shown traces are the minimum. Below three SPARTA draws
      the ridge outlines and the log says why.
      The sheet draws at a coarser cell size than the grid behind
      it. The STL export in EXPORT > 3D PRINTING always uses the
      full grid.
    Color traces by colormap: outlines each ridge in its trace color
      in place of flat black or white.
    Fill opacity: transparency of each filled wall.
    3D line width / 3D line color / 3D line opacity: the outlines.
      'auto' color is white on dark themes and black on light.
    Project: drops a faint shadow of every trace onto the back wall,
      the floor, or both.
    Log Z (absorbance) scale: log10-transforms the values and
      relabels the ticks as powers of ten. Values at or below zero
      are dropped.
    Clip Z spikes (99th pct): caps the automatic Z range at the 99th
      percentile. Typed Z limits always win.
    Even rank spacing: places ridges at 1, 2, 3 and so on, whatever
      the real gaps between series values are. Unticked, each ridge
      sits at its true value.

  3D shape
    The continuous sheet's own controls. Reach it by picking
    'surface' as the 3D look above, or '3D shape' in the Mode box.
    Graphics: quality against speed, in five notches: potato, low,
      medium, high and best. potato draws the fewest polygons, best
      draws every polygon in the grid, and medium is the default. It
      sets how finely SPARTA draws the sheet and the stand-in you
      orbit. Performance mode holds the dial at low, and the panel
      says so under the box. The exported solid always uses the full
      grid.
    Smooth polygon edges (antialias): antialiases each polygon on
      its own, which opens hairline seams between neighbours. Off by
      default.
    Draft quality while rotating: draws a coarser sheet for the
      length of a drag, at the same relief, mesh, underside and
      antialias settings. The full sheet returns on release. On by
      default.
    Interpolation: how the sheet crosses the gap between two
      measured traces. Straight takes the shortest line. Smooth
      rounds every crease with a monotone cubic, which stays between
      the two measurements it sits between. The [?] beside it opens
      the formulas. The same choice feeds the exported STL grid, and
      the provenance sidecar records which one ran.
    Mark measured traces: draws every measured trace on the sheet,
      each at its own series value. 3D line color, 3D line width and
      3D line opacity in Ridges style these lines, and 'auto' picks
      black or white per trace by contrast. On by default.
    Relief shading: lights the sheet from the north-west, so ridges
      and valleys read as shape. It changes brightness only, and it
      tracks the box aspect. On by default.
    Relief strength: how far that shading lifts and drops the
      brightness. The range runs from 0 to 1, where 0 leaves the
      colors flat and 1 is the full modulation. The default is 0.6.
    Show mesh: draws the edge of every polygon in the theme's text
      color. The line count follows the Graphics notch. Off by
      default.
    Fill underside: closes the sheet into a solid, with walls down
      all four sides and a flat base, which is what the STL export
      prints. Every wall draws at every angle. On by default.
    Fill color: what those walls and that base are painted. 'auto'
      takes the sheet's own edge colors and dims them. 'theme bg'
      sinks them into the page and leaves the silhouette. Any other
      entry paints all five faces that flat color.

  Layout & speed
    Stretch X / Y / Z: fan the box out along the spectral, series or
      height axis. The data keeps its spacing. Each has its own
      reset.
    Label gap X / Y / Z: distance from each axis's numbers to its
      title. Raise it when an axis name overlaps the tick numbers.
    3D detail (points/ridge): points kept per ridge while rendering
      3D, from 200 to 3000. A lower count rotates faster on big
      spectra. 2D plots and every export use the full data.
    Performance mode (faster 3D): decimates harder and skips the raw
      ghost. Off by default. 2D and exports keep the full data. The
      app-wide Performance mode, in the top bar's Settings panel, is
      a different control.
    Reduce motion (no UI animation): turns off the small one-shot
      interface animations.


PLOT AREA > SESSION TABS

  The browser-style tabs above the plot. Each is an independent
    session with its own data, folders, settings and undo history.
    '+' opens a blank tab. Running or loading data names the tab
    after the folder. Double-click renames, and the x or a
    middle-click closes. Ctrl+T opens a new tab, Ctrl+W closes, and
    Ctrl+Tab / Ctrl+Shift+Tab cycle.
    A blank tab lists recent runs for one-click reopening. NUKE
    clears every tab back to one.


PLOT AREA > DATA TABLE

  The Data table button at the bottom right opens a spreadsheet
    drawer under the plot, for the selected trace. Ctrl+D does the
    same. The columns are Wavelength_nm, Wavenumber_cm-1,
    Absorbance, Dark, Background and Sample. Absorbance_defringed
    and Absorbance_smoothed join them when those toggles are on.
    Drag the top edge to resize.
    'Copy all (TSV)' pastes into Excel. 'Open in Excel' writes a CSV
    and opens it. Ctrl+C copies the selected rows.

  The status line on the same bar reads the active tab, the plot
  mode, the preset and the shown trace count. While the poll timer
  is armed it reads 'auto-rescan: N s' too.
