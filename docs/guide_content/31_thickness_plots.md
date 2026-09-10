THICKNESS PLOTS

The sample changes thickness across a compression run, and the
interference fringes carry that information. SPARTA plots it
directly.


WHERE IT LIVES

  Thickness (fringe n*t) is the third radio in PLOT > PLOT MODE,
  beside Overlay all traces and Inspect one trace. It draws one
  point per shown trace against the Series variable. The Thickness
  row under the radios picks the channels (S / B). 'mark misses'
  flags the traces the detector came back empty from. 'join points'
  unticked leaves a plain scatter. 'Thickness table...' lists the
  numbers behind the points.


WHAT IS PLOTTED

  n*t per channel: the optical path, refractive index times physical
    thickness. The FFT measures it from the raw counts alone, ahead
    of any stack model.

  A point takes a detection or a solve. Every point here is
    measured.

  Point styles:

      filled circle   sample channel
      open square     background channel

    A decompression point is drawn with the decompression line and
    marker controls under 2D plot options.


Compression and decompression are separate lines

  SPARTA draws each channel as two independent polylines, one per
    branch. The last compression point and the first decompression
    point keep the gap between them.

  With both branches present and both channels shown, four lines
    draw: sample C, sample D, background C, background D. The legend
    names each one with its branch letter. The two decompression
    lines take the line style, width, opacity and marker from the
    Decompression traces controls.

  Every trace where the detector missed carries a small open
    down-triangle above the axis, on both branches. 'mark misses' in
    PLOT > PLOT MODE turns those marks off.


Marking the decompression branch

  A branch letter comes from three places, in this order. The _D tag
    in a file name wins, when the naming profile carries one. The
    built-in list for known experiments comes next. The D box beside
    each trace in DATA > TRACES comes last and always wins.

  Decompression list... in DATA > TRACES reads a .csv or .txt of the
    decompression values, in a pressure_GPa column or a plain column
    of numbers, and flags the matching traces D.

  Each listed value takes the nearest loaded trace within 0.05, and
    each trace takes one value: a list containing 18.8 takes the
    18p8 point and leaves the 18p7 point alone. A value outside the
    tolerance is reported, in the log and in a dialog. A trace the
    list leaves out keeps the branch it had.

  SPARTA remembers the list against {DAC}_{Sample}. A re-run, a
    rescan, a session switch or a reopened project applies it again.
    The list travels inside saved projects, and a list loaded for
    one cell leaves another cell's list alone.

  Everything downstream reads that one flag: the overlay's legend
    tags, Only C / Only D, the C/D file names, the two polylines
    here, and the compression and decompression markers in the
    fringe workbench's results view.

  Error bars (multiscale variance) in FRINGE > PANELS estimate the
    spread of the thickness estimate across analysis scales. SPARTA
    draws them on the solved thickness and index panels of the
    results view. They are off by default, at about 35 ms per point.


READING IT

  A compression run drops n*t monotonically as the gasket thins. A
    point that jumps out of that trend means one of three things:
    the detection latched onto a harmonic in place of the
    fundamental, the sample moved out of the beam, or the fringe
    faded and the number is noise. The fringe report in the log, and
    the report in the Detection card, carry the p-value and the
    corroboration count for that trace.

  Sample and background n*t differ. The background passes through
    the medium and the anvils and misses the sample, so the
    difference between the two channels is the sample's own
    contribution. The solve inverts it.

  Use Only C / Only D in DATA > TRACES to read either branch alone.


EXPORT

  The plot exports through the normal EXPORT > EXPORT path, journal
    presets and WYSIWYG preview included. 'Thickness table...' in
    PLOT > PLOT MODE lists the numbers behind the points: n*t and
    its Fisher p-value per trace and per channel, in plot order.


USING THICKNESS IN A FORMULA

  The formula editor reads each trace's thickness as the column t,
  the sample channel's n*t in micron, one value per trace. An
  absorption coefficient is one formula away:

      alpha = ln(10) * A / t

  It ships as the builtin 'Absorption coefficient' in cm^-1, with
  the um to cm conversion inside it. The plain ratio ships as 'A/t'
  in um^-1. See DATA > FORMULAS. t is NaN for any trace the detector
  missed, and a formula that needs t says so on the status line.
