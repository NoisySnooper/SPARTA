AXES TAB

This tab sets the coordinate system: the unit on each axis, the
range, the ticks, and the box around the plot. The data itself is
unchanged.


AXES > AXIS

  X axis: the spectral unit of the bottom axis. SPARTA converts the
    same data at every redraw.

      wavenumber [cm-1] = 1e7 / wavelength [nm]
      photon energy [eV] = 1239.84 / wavelength [nm]

  Y axis: what overlay mode plots on the left axis. Pick absorbance,
    one of the raw counts channels (sample / background / dark), or
    'formula: <name>', which appears once a formula is picked in
    DATA > FORMULAS. Absorbance is the default. The Quick Access
    strip can carry a second copy of this control, on the same
    variable, and the strip's gear picks what it carries.

  Top axis: mirrors a second unit across the top of the plot.
    Wavenumber and energy are reciprocal in wavelength, so keep X
    min above 0.

  Right axis: none, mirror the left Y, or % transmittance
    (T = 100 x 10^-A, absorbance mode only). 2D plots.

  Flip X / Flip Y: reverse either axis.

  Label gap: distance in points from the X and Y axes to their
    labels. The 3D label gaps are in PLOT > 3D PLOT OPTIONS.


AXES > LIMITS & SCALE

  X / Y / Z min and max. Leave a pair blank to fit the data. The Z
    row applies to 3D only.

  These boxes and the plot are two views of one state: a zoom with
    the drag box, the wheel, the toolbar or the View pad fills the
    boxes, so the zoom holds across redraws. Typing a limit and
    pressing Return does what 'Apply limits' does. Right-click a box
    to clear it.

  Reset axes clears all six boxes and turns auto-fit back on.

  Scale: linear or log, independently for X and Y. Log on absorbance
    drops non-positive points. Log on the spectral axis takes X min
    above 0.


AXES > TICKS

  Major / minor spacing per axis, in axis units. Blank means
    automatic. Z is 3D only. Return, or leaving a box, redraws.
    Right-click a box to clear it.

  Auto fills the spacing boxes with the values matplotlib uses right
    now.

  Marks: out, in (the journal convention), or inout.

  Minor ticks: draw them at all. Positions are automatic while the
    minor spacing box is blank.

  Ticks on all sides (2D): mirrors ticks onto the top and right
    spines.

  Tick length major / minor and Tick width, in points. The label
    font is the tick-number size.

  X format / Y format: fixed decimals (0 = integers, 0.00 = two
    places) or scientific notation. 'auto' leaves matplotlib's
    choice alone. 2D linear axes.

  Rotate X: rotates the X tick labels 0 to 90 degrees, in 15-degree
    steps.


AXES > FRAME & GRID

  Major grid and Minor grid style independently, each with its own
  color, pattern, width and opacity. 'auto' color follows the theme.
  The minor grid takes minor ticks on to have something to draw
  against.

  Spines: the three controls that style the box around the plot.
    - Axis line: thickness in points.
    - Axis color: outer spine color in 2D, box edge color in 3D.
      'auto' follows the theme.
    - Hide top/right spines: the two-spine journal look.

  Journal presets set grid off, spines hidden, ticks in and minor
  ticks on. 'Clean style (no grid, thin spines)' in EXPORT > FIGURE
  does the same, and leaves the fonts and sizes alone.
