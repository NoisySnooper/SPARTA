DATA TAB

Three sections act on the numbers: the smoothing pipeline, which
traces are shown and which branch they belong to, and your own
formulas. Fringe removal is on the Fringe tab.

Three things carry the name data: this Data tab, the data table in
the drawer under the plot, and a session tab above the plot.


DATA > SMOOTHING

  Show smoothed: draws the smoothed curve over the raw one in 2D,
    and smooths each ridge in 3D. The raw trace stays visible at the
    opacity below.

  Raw opacity: how much of the raw trace shows through, 0 to 1.
    Right-click resets it.

  No raw background: hides the raw trace, at Raw opacity 0.
    Unticking restores the previous opacity.

  Smoothing settings...: the whole filter. SPARTA runs five steps
    top to bottom on the raw absorbance. Removed points become gaps
    (NaN).

    1. Saturation cutoff: drops points above the ceiling.

         drop where A > Max absorbance

       Max absorbance   default 4.0. Higher keeps more.

    2. Density filter: blanks stretches where too few real points
       survive.

         in each Window: if (#finite) < Min valid -> blank the Window

       Window (pts)     default 50, the span checked at once
       Min valid pts    default 10

       SPARTA clamps the window to the length of the trace.

    3. Hampel despike: removes isolated spikes and keeps real peak
       shape.

         replace where |A - med| > Sigma * 1.4826 * MAD

       Window (pts)      default 5, half-width of the local median
       Sigma threshold   default 3.0. Lower is more aggressive

    4. Savitzky-Golay (split): the main smoother. It fits a
       low-order polynomial to a sliding window and keeps the
       fitted center point. The spectrum splits at a wavelength,
       and each side takes its own window and order.

       Split at (nm)               default 600
       Left window / Left poly     default 101 / 2, below the split
       Right window / Right poly   default 51 / 2, above it

       Split at (nm) is the boundary between the two grating and
       detector regimes. The split always uses wavelength, whatever
       the display axis shows. Steps 1, 2, 3 and 5 are the Igor
       values verbatim. This step always runs. Steps 1, 2, 3 and 5
       have Enable boxes.

    5. Jump filter: cleans up step discontinuities, where segments
       meet and where a filter blanked a run.

         drop where |dA| > Max jump within Step dist (+/- Buffer)

       Max jump (abs)    default 0.2
       Step dist (pts)   default 1
       Buffer (pts)      default 2, trimmed each side

    SPARTA clamps the point-count fields as it parses them. The
    preview redraws as you type. Cancel and Escape revert to the
    values you opened with.

  Reset beside 'Smoothing settings...' restores the defaults and
    clears the smoothing cache.

  Smoothing is a display filter. The base columns a Run writes stay
    as they are. Tick Smoothed data in EXPORT > DATA FILES to add
    Absorbance_smoothed to each trace's CSV.


DATA > TRACES

  One row per loaded point. The check shows the trace. The D box
    marks the trace decompression. A D trace takes the Decompression
    traces style, and sits after the compression branch in the
    legend.

  A colored dot before a row means a quality check fired. Hover it
    for the reason:
    - no absorbance at all, naming which raw channels did arrive
    - points at or above A = 4: likely saturated or a blocked beam
    - negative absorbance over more than 5% of the trace: check the
      channel pairing or lamp drift

  Double-click a row to solo that trace. Double-click again to
    restore the others.

  All / None show or hide everything. Only C hides every D trace,
    and Only D hides every C trace.

  Decompression list... reads a .csv or .txt of decompression
    values, in a pressure_GPa column or as numbers separated by
    commas, spaces, tabs or newlines. 'p' may stand for the decimal
    (1p39 = 1.39). Header lines and stray words are ignored. Each
    value takes the nearest loaded trace within 0.05, and each trace
    takes one value. A value outside the tolerance is reported. The
    list is remembered per {DAC}_{Sample}, so a re-run or a reopened
    project applies it again. The ? button spells the format out.

  Export D list (CSV) by selection writes the values currently
    flagged D back out, in the format Decompression list reads.

  A branch letter comes from three places, in this order. An
    explicit _C / _D tag in the file name wins. SPARTA then
    recognises ten historical experiments from a built-in list. Last
    comes the D box, ticked by hand.

  C/D tag in file name, a row in EXPORT > DATA FILES, puts the
    letter into every output file name.


DATA > FORMULAS

  Your own quantities, written as arithmetic over the loaded columns
  and shown as typeset formulas.

  The columns
    S    Sample counts, raw, dark not subtracted
    B    Background / reference counts, raw
    D    Dark counts, the detector baseline
    wl   Wavelength in nm - the grid every column shares
    A    Absorbance as the pipeline computes it,
         -log10[(S - D)/(B - D)]
    Sf   Sample counts, FFT-defringed        (needs Defringe on)
    Bf   Background counts, FFT-defringed    (needs Defringe on)
    Af   Absorbance from the defringed channels (needs Defringe on)
    As   Absorbance after the smoothing filter (needs Show smoothed)
    t    Optical thickness n*t of the SAMPLE channel, in um

    Long spellings resolve too: sample, background, dark, wavelength,
    absorbance, and thickness or nt_um for t. Any case works.

    t is one value per trace, read from the fringe detection. It
    enters a formula as a constant over that trace's wavelength
    grid, and scales a spectrum uniformly. t is the sample channel's
    n*t, and it is NaN wherever the detector missed. NaN propagates
    and draws as a gap.

    A variant whose processing is off is absent. The status line
    under the list names the formula that needs it, and those traces
    draw as a gap.

  Writing one
    Use numbers, parentheses, and these operators:

      + - * / **

    The functions are log10, log, exp, sqrt, abs, minimum and
    maximum. Click any symbol under the Expression box to insert it
    at the cursor. Exponents are capped at 8.

    Examples:
      100 * (S - D) / (B - D)     transmittance in %, from raw counts
      log((B - D) / (S - D))      optical density in base e
      A - As                      what the smoother removed
      A - Af                      what the notch removed
      A / t                       absorbance per unit thickness

  The builtins
    Absorbance and Transmittance ship read-only, spelled out in
    formula form. Open one and press Duplicate to start a new
    formula from it.

    - Absorption coefficient: alpha, in cm^-1.

        alpha = ln(10) * A / t, written log(10) * A / (t * 1e-4)

      The um to cm conversion sits inside the builtin. Hand it t in
      um and read cm^-1.
    - A/t: absorbance per unit thickness, in um^-1.

    Both need t, and both are NaN for any trace the detector missed.

  The row dot plots that formula: the Y axis list gains
    'formula: <name>', labelled with its name and unit. View / Edit,
    Delete and 'Save formula CSVs...' act on the same row. Pick
    'absorbance' in the Y axis list to go back. The plotted row is
    tinted and bold, with an 'on plot' tag.

  New / Edit opens the two-panel editor: the name, unit, expression
    and an optional LaTeX override on the left, a Guide and the live
    column table on the right. On 'auto', SPARTA derives the picture
    from the expression itself. The problems list and a min / max /
    NaN preview of the first shown trace update as you type. Save
    stays off until the formula is clean.

  Name and unit: the name labels the Y axis and names the CSV
    column. The unit is free text printed after the name. Leave it
    empty for a bare ratio.

  SPARTA checks the expression against a whitelist before anything
    runs: the columns, the listed functions and the arithmetic
    operators. Everything else is rejected there. Division by zero,
    log of a negative and overflow return NaN.

  'Save formula CSVs...' writes the picked formula for every loaded
    trace as two-column files, {label}_{key}.csv, holding
    Wavelength_nm and the formula with the expression in the header
    comments. One provenance sidecar covers the batch. This button
    is separate from the Data files ticks.

  Formula values in EXPORT > DATA FILES adds the active formula as
    one column of each trace's CSV, on every Run and every export.
    The column takes the formula key, with its unit in brackets when
    one is set. With no formula active the column is skipped and the
    log says so.
