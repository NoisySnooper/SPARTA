DATA INPUT

The left panel is where data enters SPARTA.


LEFT PANEL > FOLDERS

  Input folder: the folder of raw spectrometer segment files. Press
    Browse, paste a path and press Enter, or drag a folder or a file
    from Explorer onto the window (Windows). Enter also rescans. The
    arrow beside Browse, and a right-click in the box, list the last
    5 input folders and 'Open in Explorer'.

  Output folder: any folder you can write to. A Run creates

      <output>/<input folder name>_absorbance/

    or, when that subfolder exists and holds files,

      <output>/<input folder name>_absorbance_YYYYMMDD_HHMM/

  Run: for each measurement group SPARTA joins the grating segments
    in ascending segment order, sorts by wavelength, and computes

      A = -log10[(Sample - Dark) / (Background - Dark)]

  Export..., between Run and Open output, opens the Export dialog:
    it writes the CSV of every loaded trace into a folder you pick,
    with the same columns a Run writes. Ctrl+E opens the same dialog.

  Open output opens the destination subfolder.


WHAT A RUN WRITES

  A Run writes one CSV per measurement group. The ticks in Export
    tab > Data files pick the columns that CSV carries. Defringed
    data is ticked by default; the other three ticks start off. One
    summary line closes the run.

  {DAC}_{SAMPLE}_{VALUE}[_C|_D]_absorbance.csv holds the base
    columns Wavelength_nm, Wavenumber_cm-1, Absorbance, Dark,
    Background and Sample. Blank cells are NaN, and the value token
    uses 'p' for the decimal (26p0).

  A ticked row appends its columns after the base set, in order:

      Defringed data   Absorbance_notch, Background_notch, Sample_notch
      Smoothed data    Absorbance_smoothed
      Formula values   one column named by the formula key

    Smoothed data also appends Absorbance_notch_smoothed while
    Defringed data is ticked. The formula column takes the key of the
    active formula in Data tab > Formulas, with its unit in brackets
    when one is set.

  Absorbance_notch is always filled: absorbance recomputed from the
    cleaned channels, and equal to Absorbance where nothing was
    removed. Background_notch and Sample_notch stay blank for a
    channel with no detected fringe. Each trace cleans at its own
    notch list from Fringe tab > FFT removal, or at the panel's
    global controls. The df switch changes the plot only.

  C/D tag in file name puts _C or _D in every file name, after the D
    toggles and the D list. Off, a name carries the letter only when
    the raw file name did. There is no separate copy and no
    subfolder, so Load previous run sees one file per point.

  _reduction.provenance.json records the version, the two folders,
    the absorbance definition, the Series variable, the defringe
    state, the columns written and every curve.


HOW MEASUREMENTS ARE GROUPED

  SPARTA groups files by (DAC, sample, value, branch). Inside a
    group each channel (dark / background / sample) can have several
    replicates, and each replicate several grating segments.

  The group anchors on the sample channel, else background, else
    dark, at the highest replicate index. Other channels pair by
    replicate, else by their own latest.

  Only the segments the channels share are joined; a group whose
    channels share none is skipped.

  Channels on different wavelength grids are interpolated onto the
    anchor's grid, and points outside a channel's own range become
    NaN.

  raw/.csv twins are counted once.

  Absorbance takes all three channels. Otherwise the channels
    present load as raw counts, the absorbance column is all-NaN,
    and the trace label carries a tag ([S only], [S+B]).


LEFT PANEL > NAME FORMAT

  The button under the Input box names the profile in force, and
    opens teach-by-example, Guess format, the whole-folder preview
    and the per-file fixes. The Naming system view holds the deep
    dive.


LEFT PANEL > RESCAN

  Rescan, beside 'Load previous run', compares the input folder
    against the file list captured at the last Run; new files
    re-reduce the whole folder. F5 does the same from anywhere.

  The Auto rescan pill in Plot tab > Plot mode repeats that
    unattended, from 5 to 3600 s, default 30, after the first Run.


LOAD PREVIOUS RUN (VIEWER MODE)

  'Load previous run...' asks for a folder of *_absorbance.csv
    files, the output subfolder a Run wrote, and re-imports them as
    traces straight off disk. A blank session tab lists recent
    runs.

  The importer ignores files ending in _absorbance_notch.csv, which
    earlier versions wrote beside the absorbance CSV, and passes over
    every other file silently. Extra columns in an imported CSV are
    ignored by name. Smoothing and defringe still apply live on
    imported data.

  Run falls back to viewer mode when the folder holds SPARTA's own
    *_absorbance.csv output and the raw segments sit elsewhere. It
    logs "Viewer mode: nothing written."


LEFT PANEL > PROGRESS AND GUIDE / NOTES

  Progress logs every run, rescan and action, with the reason for
    every skipped file. 'Copy log' copies the whole log, and 'Export
    settings' prints the current plot configuration into the log.

  Guide / notes is this box: the View dropdown switches between the
    guide views and 'My notes', a scratchpad saved between launches.
    The gear beside it holds this box's font and size.


TOP BAR > SETTINGS

  Performance mode, in the Settings panel behind the gear, resizes
    the panes once on a divider drag, for a slower machine.
    'Performance mode (faster 3D)' in Plot tab > 3D plot options is
    a different control.
