QUICK START

Quick start covers the path from raw segment files to a figure.
SPARTA writes to disk on Run, Export data and Save only.

Point the Input folder at demo_data, which ships beside the
program: 5 series points, 3 channels, 2 grating segments,
22-IR-1 naming, one point tagged _D. About > 'Welcome & tour...'
loads that folder and walks this path in the window. Esc leaves the
tour.


1. POINT AT THE DATA

  Input folder, in the left panel: press Browse, drag a folder from
    Explorer onto the window, or paste a path and press Enter. Enter
    also rescans and remembers the folder.
  The scan reads one folder: the folder holding the segment files
    themselves.
  Output folder: press Browse and pick a writable folder. A Run
    creates <output>/<inputname>_absorbance/. If that subfolder
    exists and holds files, SPARTA appends a timestamp
    (<inputname>_absorbance_YYYYMMDD_HHMM).


2. CHECK HOW THE NAMES ARE READ

  The button under the Input box shows the active profile. The
    default is '22-IR-1 default', which reads

      vis_{DAC}_{Sample}[_{Pressure}][_bg|_s][_C|_D][_rep][.{seq}]

    so vis_Y04_Arch29_26p0_s.003 is DAC Y04, sample Arch29, 26.0
    GPa, the sample channel, grating segment 3.

  For another scheme, open the button and press 'Guess format'. In
    the Preview, green means parsed and red means skipped with the
    reason. Correct the fields, then press 'Use this profile'. The
    Naming system view holds the walkthrough.


3. RUN

  Press Run. SPARTA joins the grating segments of each measurement
    and computes

      A = -log10[(Sample - Dark) / (Background - Dark)]

  A Run writes one CSV per measurement into the output subfolder,
    named {DAC}_{sample}_{value}[_C|_D]_absorbance.csv. Export tab >
    Data files ticks the columns that CSV carries; Defringed data is
    ticked by default. A _reduction.provenance.json sidecar carries
    the version, the parameters and every curve. The left panel's
    'Export...' button, the Export tab's 'Export data...' and Ctrl+E
    all open the Export dialog, which writes the same columns into a
    folder you pick.

  Each Progress log line is one measurement: OK lines carry the
    point count and the file written, SKIP lines the filename and
    the reason. Run reads Cancel during a run.

  Absorbance takes all three channels. A measurement with fewer
    loads as raw counts, tagged in the trace name ([S only], [S+B]).


4. CHECK THE DATA

  Every trace plots at once.

  Inspect one trace in Plot tab > Plot mode. The left axis shows
    Sample, Background and Dark counts, the right axis the
    absorbance.

  Traces, in the Data tab, holds one row per loaded point. A colored
    dot marks a quality check that fired; hover it for the reason
    (saturation, negative absorbance, missing channels).

  Click a curve to select it, double-click to solo it, click a
    legend entry to hide it. Right-click one for inspect, solo,
    hide, toggle D, defringe compare and show in data table. Ctrl+D
    opens the data table, with 'Copy all (TSV)' and 'Open in Excel'.


5. MAKE THE FIGURE

  Export tab > Figure: pick a Journal preset. One pick sets the
    publisher's column width and house style: typeface, text sizes,
    line weight, spines, ticks and DPI. 'Preview at export size
    (WYSIWYG)', in Export tab > Export, shows the printed
    proportions on screen.

  Style tab > Legend: above about ten traces, turn on 'Direct labels
    at curves' or use Style tab > Colorbar.

  Export tab > Export: 'Save plot...' writes PNG, PDF, SVG, EPS and
    TIFF. PDF and SVG are vector. 'Editable text' keeps the labels
    editable in Illustrator or Inkscape.


THE REST OF THE WINDOW

  Session tabs above the plot hold independent sessions, each with
    its own data, folders, settings and undo history.
  'Load previous run' reopens a finished output folder from its
    CSVs. Rescan (or F5) re-runs the folder after new files arrive.
  The top bar carries Theme; the gear that opens the Settings panel
    (Font, Text size, Helper tips, Performance mode, Tutorial,
    About); and NUKE, which clears the session and asks first.
  The Quick Access strip above the tabs starts empty; its gear picks
    what it carries.
  F1 lists the keyboard shortcuts.
