TROUBLESHOOTING

Symptom first, then the cause and the fix. For a Run, read the
Progress log.


NO TRACES AFTER A RUN

  The log says "Found 0 measurement group(s)".

  A HINT that lists subfolders means you pointed at a parent
    folder; pick the folder holding the segment files.

  Every file on a SKIP line means another naming profile fits: press
    'Guess format', check the preview, then 'Use this profile'.

  A folder of SPARTA's own *_absorbance.csv output sends Run into
    viewer mode.


FILES WERE SKIPPED - WHAT THE REASONS MEAN

  Each skipped file gets a SKIP line with its reason, shown live in
  red in the 'Name format' preview.

  does not match vis_DAC_SAMPLE[_PRESSURE]
    The built-in grammar takes a 'vis' token and three pieces. Teach
    a custom profile.

  missing prefix '<x>'
    The first token differs from the Prefix box.

  unrecognized trailing token '<x>'
    A piece is left over. Label a date or operator chip 'ignore';
    the built-in takes only bg / s, C / D and a digit retake, so it
    rejects _r and _sA.

  missing dac token / missing sample token
    The name ran out of pieces. Drop a chip, or set Default DAC Name
    / Default Sample Name.

  segment is not numeric
    The text after the final dot is not digits.

  no segment suffix ('<sep><segment>' required)
    'No number =' is set to reject; set it back to 1.

  malformed (extra extension)
    The base still holds a dot after the segment split, as in
    ..._bg.001.002.

  pressure '<x>' not numeric / pressure not finite / < 0
    The value token takes a finite number at or above 0. Check Value
    decimal and Strip units.

  role '<x>' is not a valid channel
    A role map entry points at something other than dark, background
    or sample.

  excluded by user
    You excluded it in the preview; 'Clear all fixes' undoes every
    fix.

  Double-click a row to type its fields by hand, or press 'Exclude
  selected'.


A PROFILE WILL NOT COMMIT

  'Use this profile' refuses and lists the problems:

    separator is empty
      The Separator box has to hold something.

    '<dac|sample>' missing from token order
      Add a chip, or a default name.

    role is in the order but the role map is empty
      A chip is labelled 'role' and no keywords are set.

    'reject' needs a segment separator
      With no segment separator, 'reject' would skip everything.

    missing-segment value must be a whole number >= 1 or 'reject'
      That box takes a whole number at or above 1, or 'reject'.


THE VALUE AND SEGMENT COLUMNS LOOK SWAPPED

  A name ending in a dotted value, with '.' as both the value
  decimal and the segment separator, has its last digit read as a
  segment: '..._2.5' gives segment 5. Use 'p' for the decimal.

  The milder form is a token separator equal to the segment
  separator: a trailing token that decodes becomes the segment.


A TRACE HAS NO ABSORBANCE

  Absorbance takes sample, background and dark together. A group
  that misses one loads as raw counts, and its name carries a
  channel tag ([S only], [S+B]).

  With raw channels alone, the overlay Y axis switches to the best
    available raw channel.

  A load that mixes complete and incomplete groups raises a
    banner.

  Inspect one trace shows which channels arrived.

  "no shared segments -- skipped" means the channels of that group
    share no segment number.

  "channel grids differ ... aligned by wavelength" means the
    channels were interpolated onto the anchor's grid, with NaN
    outside each channel's own range.


A TRACE IS FLAGGED IN DATA > TRACES

  The colored dot means a quality check fired. Hover it.

  "N point(s) at A >= 4: likely saturated or blocked beam"
    The sample channel is at or near the detector floor over part of
    the range, where the ratio is meaningless. The fix is at the
    beamline; the saturation cutoff in the smoother hides the
    range.

  "negative absorbance over N point(s): check channel pairing / lamp
   drift"
    The sample channel is brighter than the background, usually from
    a background at a different lamp state or a mismatched pair. The
    group uses the latest retake of the anchor channel.

  "no absorbance (raw channels: ...)" names the channels that did
    arrive.


DEFRINGE FINDS NO FRINGE

  SPARTA notches a channel on a confident detection alone. A channel
  with no fringe keeps its counts, its notch column stays blank, and
  the workbench titles it "no fringe detected (p=..)".

  The fringe report in the log lists the traces with a detection,
    their fitted n*t in micron, and the p-value.

  The Detection card in the Fringe tab holds the controls.
    'n*t band (um)' defaults to 8 to 300 um; a very thin or thick
      sample falls outside it.
    'Fisher p' defaults to 1e-4; raising it catches weaker fringes
      and notches noise now and then.
    Detection runs at 16 finite points or more, on the raw Sample
      and Background channels, before the ratio.

  Detection can succeed on a harmonic, 2 n*t or 3 n*t. Right-click
    the bump you believe in to pin the fundamental.

  'Suppress fringe report' keeps the log quiet.


THE NOTCH REMOVED SOMETHING I WANTED

  Turn on 'Defringe compare (selected trace)' in PLOT > 2D PLOT
  OPTIONS and click the curve. The pre-defringe absorbance draws
  behind it in gray dashed.

  Then narrow the notch in FRINGE > FFT REMOVAL > Notch list. Every
  centre carries its own half-width, and unticking one leaves that
  part alone. Untick df to switch it all off.


TEXT IS UNREADABLE, OR A CONTROL LOOKS WRONG AFTER A THEME SWITCH

  SPARTA re-pins field text on every theme change. A stale state
  heals on the next redraw and logs "field styles were stale".

  On some Tk builds, checkboxes and switches keep a fixed blue
  accent. It is cosmetic.

  For interface text too small or too large, use Text size in the
  Settings panel: 3 to 15, or 'auto'.

  High Contrast is the most legible theme, Colorblind Safe
  (Okabe-Ito) the color-vision-safe one.

  'Tint plot with theme' in STYLE > COLORS & COLORMAP carries it
  into the figure.


ITALIC DOES NOTHING

  The bundled Jost typeface draws upright at every weight. Pick
  Arial or Segoe UI in STYLE > FONTS for an italic face; journal
  presets already set Arial, or a serif for APS.


THE LEGEND CHANGED SIZE ON EXPORT

  'Auto-fit oversized legend' reflowed it to fit the page: columns
  first, then a lower font size. The values it used are written back
  into STYLE > LEGEND. Turn it off and an oversized legend overflows.


A RUN WROTE TO A FOLDER I DID NOT EXPECT

  A Run creates <output>/<input folder name>_absorbance/, with a
  timestamp appended when that folder exists and holds files. 'Open
  output' opens the folder used.


A DEFRINGED OR SMOOTHED CSV IS MISSING

  There is one CSV per trace,
  {DAC}_{sample}_{value}[_C|_D]_absorbance.csv, and the ticks in
  EXPORT > DATA FILES add columns to it. SPARTA writes no
  {stem}_absorbance_notch.csv, no {label}_smoothed.csv and no
  cd_tagged subfolder.

  Open the CSV and look for Absorbance_notch, Absorbance_smoothed or
  the formula key. An empty Background_notch or Sample_notch means
  that channel had no detected fringe.

  'Load previous run...' ignores any {stem}_absorbance_notch.csv an
  earlier version left behind.


AUTO RESCAN IS NOT FIRING

  It waits for the first Run for a baseline file list, and fires
  while SPARTA sits idle. The status line under the plot reads
  'auto-rescan: N s' whenever the timer is armed; any other reading
  means it is off.


WINDOWS 7 AND OTHER OLDER MACHINES

  SPARTA has a separate Windows 7 package, built for Python 3.8.10:
    - Some shortcuts depend on newer key symbols and stay unbound;
      Ctrl+Shift+Tab still cycles tabs backwards.
    - Turn on 'Reduce motion' in PLOT > 3D PLOT OPTIONS.
    - Lower '3D detail (points/ridge)' and turn on 'Performance
      mode (faster 3D)'; both act on the 3D view alone.
    - For heavy pane dragging, turn on the app-wide Performance
      mode.

  A program that stays shut may be unpacked wrong: it is a directory
  build, and the launcher runs from inside its folder.


NOTHING ELSE WORKS

  NUKE, on the top bar, clears the session: data, plot, folders, log
  and every control. Files on disk, saved presets and the default
  colormap survive. It asks first.

  'Reset all' on the right panel's control bar is gentler: plot
  controls back to default, data and folders kept.
