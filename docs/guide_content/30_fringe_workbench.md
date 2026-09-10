FRINGE WORKBENCH

A regular ripple on a spectrum is light that bounced inside the
cell. It carries the thickness of the layer it bounced in. The
workbench takes that ripple out of the absorbance, or reads it as a
measurement.


Two ways in

  The df box beside the plot is the quick one. Ticked, SPARTA finds
  the strongest ripple in every trace, removes it, and computes
  absorbance again for the plot.

  The workbench is the same physics with every step exposed: four
  charts, a low-pass filter you drag, and notches you place by
  clicking. Its solve turns ripples into thickness and refractive
  index. Each trace cleans at its own workbench settings, and a
  trace the workbench has yet to open cleans at the ripple the
  detector finds in it.


Opening it

  Click Fringe at the right-hand end of the session-tab row above
    the plot, and Plot to go back. The rest of the session holds.

  Guide opens and closes this page beside the chart. Pop out floats
    the chart into its own window. F11 fills the screen, and Escape
    sends it home.

  The controls sit in the Fringe tab: Stack, Session, Pressure
    point, Detection, FFT removal, Refractive Index from Intensity,
    and Panels.


The four charts

  Left column: the ripple spectrum, Background on top and Sample
    below. Left to right is n*t in micron, thickness times index; up
    and down is the ripple's amplitude. A bump means a layer of
    about that thickness is in the light path. The tall coloured
    lines are the model's predictions, and thin dashed lines at two
    and three times a line's position are its harmonics.

  Shaded bands mark where a notch removes signal, and the scale on
    the right edge reads the fraction removed. The dashed vertical
    line is the low-pass cut; drag it from 1 to 200 micron. The
    tinted band to its right is what the low-pass takes out.

  Right column: the measured spectrum, Background on top and Sample
    below. Raw draws in ink, the cleaned result in red. Before a
    spectrum loads it reads "no measured data".

  A channel with no detected fringe carries no cleaned curve. Its
    title reads "no fringe detected (p=..)" and the panel draws raw
    and dark instead. The Sample panel adds the noise floor under
    the dark and D(raw, dark).

  Peak markers on the bumps:

      filled triangle   the main ripple
      filled circle     found automatically
      filled diamond    you put it there
      hollow            still listed, switched off

  Along the top of each left chart the cell is written out in order:
    anvil, medium, sample, medium, anvil.

  The toolbar under the charts holds home, back and forward for the
    view history, a pan hand and a zoom rectangle that act on
    whichever chart you drag in, and Save for the four as an image.
    The workbench gestures rest while a toolbar mode is armed.


Using the mouse

  Point at a bump. The arrow becomes a hand, and a ring marks what a
    click will act on. Left-click adds a notch there, and a second
    click takes it away. Right-click a bump to pin it as the main
    ripple, or to hand it to one of the three role shapes.

  Point at the dashed low-pass line, or at a shape along the top.
    The arrow becomes a left-right arrow. Drag it.

      rectangle    through the sample
      half-filled  through the sample AND the diamonds
      diamond      through the medium only

  The three shapes arrive parked on the workbench's best guess.
    Dragging one places it and solves the cell on the drop. Fit
    peaks re-detects all three from the model.

  A point with inputs of its own opens on the stack model's guess. A
    point with none opens on the tallest bump of each chart, and the
    solve that follows fills n sample, t sample and d2.

  A shape SPARTA placed carries a solid guide line, and one you
    placed a dashed line in its own fill. A pair that lands on one
    bump steps apart onto two rows. A fitted Gaussian draws under
    each automatic shape, with a joint envelope over the two Sample
    shapes while both are automatic.


FRINGE > STACK

  Describe what the light goes through, and read the answers back.

  Anvil: the formula for the diamond's index. Eremets n(P) is the
    shipped model. Every load reads it at that spectrum's own
    pressure and writes the answer on the n diamond row, which is a
    box, so an index of your own goes in it. The row is marked
    Fixed, and the solve holds it.

  Medium: what fills the cell. A named medium follows pressure
    through its n(P) model. Other takes an index typed on the n
    medium row. The default is Other with n = 1.2, Fixed too.

  When n sample reaches the index of the layer beside it, the terms
  for interface pairs 12, 13, 24 and 34 invert. The n*t positions
  hold, so only the phase turns over. The [?] says which way the
  ordering falls at the numbers in the boxes.

  Layer 2: switch it on for a second distinct layer, then pick what
    it is. The n layer2 row appears with it, and the picked model
    writes the index there.

  Medium name, Sample name, Layer 2 name: what the rows, the legends
    and the cell picture call each material. A blank box takes the
    model's own name.

  P and calc n: the pressure the index models are read at, and the
    button that reads them. P fills in from the loaded spectrum, and
    an empty box takes that value back. calc n reads the anvil
    index at P, and the medium and layer 2 while a model drives
    them. The wavelength is the fringe window's centre.

  Ambient n (2.4168): puts the anvil back on the ambient constant.
    The next load reads the Anvil model again.

  Reset & drop point: puts the inputs back to their defaults and
    takes this point off the results series. The continuity file
    keeps its copy until the next save.

  n sample: the index the prediction lines are drawn from, 1.5 to
    start. Fit peaks and the drop of a dragged shape write the
    solved value back here.

  d2 upper medium (um), t sample (um), d1 lower medium (um): the
    stack top to bottom, defaults 0 / 20 / 0. Beside each box is
    that row's solved value: n_s beside n sample, t_s beside t, the
    medium total t_m beside d2, and the whole gap L beside d1.

  Total (um) plus Lock In: unlocked, Total mirrors d1+t+d2. Locked,
    Total holds and d2 and t trade against each other. A d1 change
    spreads over both in proportion. Editing the Total grows d2, or
    drains d1, then d2, then t.

  fine steps (/ 10): every spinbox moves at a tenth of its own step.
    An index box steps by 0.1 and a thickness box by 1 micron, so
    fine steps gives them 0.01 and 0.1.

  Fit peaks: the two glyph buttons. Both re-detect all three peaks,
    solve, and write the answers into the boxes above. Distinct fits
    the rectangle and the sample-diamond as separate peaks. Shared
    fits the rectangle as a shoulder on the sample-diamond's hump.

  Plot point: puts this point's solved values onto the results
    series. Results plot opens the series. A tick on its caption
    means the point is on the series already.

  The [?] on the card title opens the six interface pairs, the
    Fresnel amplitudes, the solve and its clamps.


FRINGE > SESSION

  Load parent folder...: pick a folder that contains series
    subfolders of *_absorbance.csv spectra. The dropdown between the
    arrows jumps between them, and each series opens at its lowest
    pressure.

  Load raw spectra...: pick one *_absorbance.csv. Its whole folder
    loads, and the Pressure point dropdown fills with its siblings.
    Both loaders read the files a Run writes.

  Series:: names the working series.

  Save session: writes the recorded points as
    series_continuity.json, plus a timestamped copy, beside the
    input data. A read-only folder sends them to the output folder,
    and the status line names the path. The file carries each
    point's own numbers, notch list and role shapes, and the tooltip
    itemises what a save would change.

  Load session: reads the file back from wherever the last save put
    it. It is the format Matthew Diamond's program reads and writes,
    so a folder saved by either program opens in the other.

  The marks under the buttons: a tick when file and memory match, a
    dot when they differ, a circle before the first write.


FRINGE > PRESSURE POINT

  The dropdown picks which spectrum the workbench shows. The arrows
  walk the list in the order the experiment ran, up the compression
  run and back down the decompression leg, and they stop at the
  ends. Page Up and Page Down walk it from the keyboard.

  Each label carries a mark against series_continuity.json. A tick
  means the file holds that point as it stands here. A dot means the
  file holds it with other values. A plain label is a point the file
  has yet to see.

  A point with its own inputs still to come opens seeded from the
  nearest preceding point. Leaving a point with unsaved changes asks
  first, and SPARTA lists what differs.


FRINGE > FFT REMOVAL

  The cleaning pipeline, and the only one. This card is what the df
  box cleans the plot with, and what the Defringed data row in
  EXPORT > DATA FILES writes into each trace's CSV, on a Run and on
  an export. It holds one sub-block per channel, Background and
  Sample, so the two clean independently.

  A channel with no detected fringe keeps its own counts, since
  detection is what turns the cleaning on. The panel titles that
  channel "no fringe detected (p=..)", draws raw and dark in place
  of a cleaned curve, and leaves that channel's notch column in the
  CSVs blank.

  Once a fringe is there, the notch list has three states. Boxes
  ticked: those centres come out. Every box unticked, or the
  fundamental set to none: nothing comes out. A spectrum this panel
  has yet to open: the detector picks that spectrum's own
  fundamental. A low-pass is on or off apart from all three.

  Low-pass cutoff: everything above the cutoff is removed. The
    cutoff is in micron of n*t, default 15, over a range of 1
    to 200. The dashed line on the chart is the same control, and
    a drag on either one moves the other. The tinted band right of
    the line is what comes out.

  Edge: the shape the cutoff rolls off with, and the width it rolls
    off over. Tanh is the shipped shape, at 2 micron. Error function
    falls a little steeper over the same width. Hard cuts at the
    cutoff itself. One width past the cutoff, tanh keeps 12% of the
    signal and error function keeps 8%. A dotted curve over the left
    chart traces the mask.

  Clear notches: takes every notch off that channel. The fundamental
    stays in the list, unticked. With the list empty the channel
    keeps its own counts, and a low-pass that is on still applies.

  Export cleaned spectrum: writes the red FFT filtered curve per
    channel to CSV. The columns are Wavenumber_cm, Background_notch,
    Sample_notch, Absorbance_notch.

  Notch list: the notch table in its own window, with every centre
    at its own half-width, a remove cross, and the default width for
    new notches. The Fundamental column marks the peak the detector
    reports, and clicking the marked row clears that channel. Clear
    takes every notch off one channel. fine steps moves the width
    boxes 0.1 micron a press.

  Write notches file for batch: saves notch_overrides.csv, with
    every centre and width you picked. The batch pipeline reads that
    form back.

  Delete notches file: removes this spectrum's saved rows from that
    file. The live notches on the chart stay.

  Hide clean spectrum: takes the red curve off. It is drawn whenever
    something is being filtered, whatever the df box says.

  The df box changes the main plot only. While Defringed data is
    ticked in EXPORT > DATA FILES, a Run adds Absorbance_notch,
    Background_notch and Sample_notch to each trace's own CSV, and
    the Export dialog writes the same columns again into the folder
    you pick. There is no separate notch file any more. Each trace
    cleans at its own list here: its centres, each at its own
    half-width, plus that channel's low-pass cutoff and edge. A
    trace this panel has yet to open cleans under the global
    controls, at the fringe the detector finds in it.

  The Detection card holds the search gates and the switch that
    keeps the fringe report out of the log.

  The [?] on the card title shows the mask as a formula: the
    Gaussian notch, the mirror padding, and the three low-pass
    edges.


FRINGE > REFRACTIVE INDEX FROM INTENSITY

  A fringe's amplitude carries an index too.

  Compute fits: runs the amplitude fitters, the cosine fit and the
    band integral, over every spectral window, on the current notch
    and low-pass settings. The right panels switch to the tiered
    view, and the fitted n appears in each panel title.

  History: reopens a previous Compute fits run, with its inputs and
    notch settings, named by the fitted n.

  Show tiered / Hide tiered: the flat view shows raw plus the
    cleaned curve at true intensity. Tiered stacks the diagnostics
    apart: the cosine-fit residual, the cleaned curve, each fitted
    window's defringed curve, and raw on top. The left panels gain
    the crimson and blue residual FFTs.

  Hide clean spectrum / Show clean spectrum: the red curve, on and
    off.

  Band D resolution floor: holds the band integral's integration
    band at the FFT main lobe or wider. Only the band values move.

  The [?] on the card title holds the two estimators and the Fresnel
    inversion, written out.


FRINGE > DETECTION

  The search gates: wavelength window, n*t band, Fisher p, and
  agreement tolerance. The card also holds the live report of what
  the search found. The df box reads the same gates, and the window
  travels with the df pass, so a trace cleans over the range set
  here. A dataset keeps a window for one input folder alone.

  The window also sets how fine the FFT is. The transform is taken
  in wavenumber, 1 over lambda, and its bin width is about

      1 / (2 d(1/lambda))

  The 600 to 800 nm window gives a bin near 1.2 um of n*t. Two peaks
  closer together than the bin are not resolvable, so a pair that
  will not separate means the window is too narrow. The [?] prints
  the bin for the window that is set.

  Suppress fringe report keeps the per-trace summary out of the main
    log.


FRINGE > PANELS

  The pop-out windows, one click each: Notch list, Predicted lines,
  Results and Info. Predicted lines holds the forward-model lines as
  copyable text, and Info the marker key and the mouse grammar.
  Detection scrolls the Detection card into view. Closing a pop-out
  hides it, and the next click brings it back with its rows re-read.

  Y-axis range: the fringe-amplitude range the two left charts
    share. An empty box leaves that bound automatic.

  Line colours: the palette the model stems are drawn from, and
    whether its palest colours are used.

  Refractive index models: one tab per material, with each model's
    equation, its constants and the paper they come from.

  Error bars (multiscale variance): uncertainty for the results
    plot, from the spread of the fit across analysis scales. SPARTA
    computes it once per point and caches it.

  Below the buttons sit the status line, the solve line, and the CSV
  folder every export writes to. Clamp warnings appear on the solve
  line.


Results vs pressure

  Six charts against pressure: the three indices n_s, n_medium and
  n_layer2 over the three thicknesses t_s, L and t_layer2.
  Compression points are filled circles, decompression points open
  crosses, and point colour is the medium the point was solved
  under. One key along the bottom names every mark.

  Re-solve under runs every recorded point through another medium's
  pressure curve, from the measured paths each point stores. EoS
  curves adds dashed equation-of-state lines to the thickness
  charts. Save figure... writes the grid at print quality.

  Export results CSV writes every recorded point to one file in the
  series folder, fft_results_series_<stamp>.csv: its three measured
  paths, the indices it was solved under, and the solved geometry.

  Hovering a point reads its values back, and hovering a model curve
  or an EoS line reads that line at the cursor. Readouts that would
  overlap stack apart.

  Right-click a point to anchor an EoS curve there or to remove the
  point. On the loaded point the menu also restores the inputs.


State, and keeping work

  The workbench tracks what you changed and what it has written:

      check   written down, same as the file
      dot     changed here, still to write
      circle  waiting for the first record

  Moving away from unsaved changes offers save, discard, or stay,
  with the differences listed. Long lists stop at eight lines and
  count the rest.


Credit

  The fringe analysis is a port of Matthew R. Diamond's
  defringe_dac.py, used with permission under the MIT license. The
  numbers are checked against the original on real spectra, and his
  citations are kept in the source.
