STYLE TAB

This tab sets how the figure looks: the color, the type, the labels,
the key, and the reference lines drawn over the data.


STYLE > COLORS & COLORMAP

  Filter: type to narrow the colormap list ('blu', 'div', 'gray').
    Clear the box to show all maps.

  Colormap: the color scale spread across the traces, with a live
    swatch under it. The Crameri maps (batlow, roma, hawaii,
    lajolla) are perceptually uniform and color-blind safe, and
    batlow is the default. The two arrow buttons, and the keys [ and
    ], step through the list.

  Set as default: applies this map at every launch. The star marks
    it, and a second click clears it.

  Reverse colormap: flips which end of the scale the highest value
    takes.

  Shades: 'continuous' gives each trace the exact color of its
    value. 'discrete' cuts the map into Levels steps and puts each
    trace on a step. 'auto', the default, uses discrete for eight
    traces or fewer. The colorbar shows the same steps.

  Levels: the number of steps discrete mode cuts the map into, 2 to
    24, default 6. It works with Shades on 'discrete'.

  Trace colors...: click a swatch to set a shown trace's color by
    hand. A set color wins over the colormap everywhere: 2D, 3D, the
    legend, the direct labels and the ridges. 'Clear all' returns
    every trace to the map.

  The 3D Surface look (PLOT > 3D PLOT OPTIONS) reads this map and
    colors the sheet by series value, so the colorbar reads
    correctly. A categorical map bands the sheet by rank.

  Lock colors to all datasets: colors each dataset from the full
    loaded set, so a curve keeps its color when others are toggled
    off. On by default.

  Tint plot with theme: tints the plot background to match the
    theme, which accent themes otherwise keep neutral. The export
    face color is in EXPORT > FIGURE.

  Text color: the tick numbers and axis labels, 2D and 3D. 'auto'
    follows the theme.


STYLE > FONTS

  The typeface for every text element in the figure. The default is
    the interface face. Journal presets override it with Arial, or
    with a serif for APS.

  Bold and Italic, per element: Title, Labels, Ticks, Legend, Bar
    (the colorbar label and its tick numbers). 2D and 3D.

  Italic takes a font that has an italic face. The bundled Jost
    draws upright at every weight, so pick Arial or Segoe UI.
    Journal presets already set Arial.

  Mathtext works in any label box: $\lambda$, Fe$^{2+}$, $\mu$m.
    matplotlib renders it, so the screen matches the export.

  The per-item text sizes sit beside the item each one governs:
    Title size next to Title, tick size in AXES > TICKS, legend size
    in STYLE > LEGEND.


STYLE > TITLE & AXIS LABELS

  Title, X label, Y label and Z label, each with its own size box. X
    and Y labels share one size, since matplotlib applies a single
    label size to both. Right-click a box to restore the automatic
    text.

  Title pos: left / center / right. pad is the gap above the axes in
    points (blank = default).

  Title X / Title Y: the title position in axes fractions, where a y
    above 1 is above the axes. The boxes always show the position
    drawn. Type both values to pin a custom spot; blank one value,
    or change Title pos, for the automatic placement again.

  X pos / Y pos: slide the axis labels along their own axes (left /
    center / right, bottom / center / top). 2D and 3D.

  Footnote: a small note stamped at the bottom-left of the page,
    with its own size box. It exports with the figure. 2D and 3D.


STYLE > LEGEND

  Show legend: a per-trace key.

  Branch tags: the ' - C' / ' - D' suffix on every legend entry.
    Switch it off for the value alone, or rename the two branches in
    the small C and D boxes (heat / cool, inc / dec). Blank falls
    back to C and D. This control is display only: the D list and
    every file name keep the letters C and D.
    What the two branches look like is set in PLOT > 2D PLOT
    OPTIONS, under Decompression traces, and the legend keys follow
    it.

  Location: the usual matplotlib positions, plus outside right,
    left, top and bottom.

  X / Y: the legend box center in axes fractions, pinned and
    released the way Title X / Title Y are.

  Auto-fit oversized legend: reflows an oversized legend to fit the
    page, on export and in the WYSIWYG preview. SPARTA adds columns
    first, then lowers the font size, and writes the values back
    into this panel. Off uses the settings as typed.

  Swatch: 'color box' draws a thick color block per trace, and the
    3D legend uses it. 'line' shows the artist itself.

  Direct labels at curves: writes each trace's value at its curve
    end, in 2D overlay, 2D stacked and 3D ridge. Five rows style the
    labels.

    Size: the label text size in points, default 9.

    Color: 'trace' colors each label like its own curve. Black,
      white, gray or any hex code also work.

    Distance: the gap from the curve end to its label. It runs from
      0 to 40 points, and the default value is 4.

    Bold: thickens the label text.

    Backing: 'none' draws the text alone, 'box' a rounded box in the
      page color, and 'halo' an outline in the page color around the
      glyphs.

  Columns (up to 16), Font size, and an optional Title above the
    entries.

  Frame (shared with colorbar)
    Border box on/off, Background opacity and Border width. Border
    opacity is independent of the background, and Edge color paints
    the border. The same controls style the colorbar frame.


STYLE > COLORBAR

  Show colorbar (continuous maps): a continuous scale across the
    Series variable.

  The legend and the colorbar draw together. SPARTA builds the bar
    first and steps an outside legend past it, so a right-hand bar
    moves a right-hand legend further right. A pinned X / Y stays.

  Auto: colorbar for many traces: off by default. On, a continuous
    colormap with more than about ten traces switches itself to a
    colorbar and drops the legend. A categorical colormap always
    keeps a discrete legend. Off honors the Legend and colorbar
    checkboxes literally.

  Bar label: defaults to the Series variable ('Pressure (GPa)').
    Type here to override it.

  Location: right / left (vertical) or top / bottom (flat). It also
    decides which side the ticks sit on.

  X / Y: the bar center in figure fractions, a different measure
    from axes fractions, pinned and released the way Title X /
    Title Y are.

  Label font, Tick font, Thickness (as a fraction of the axes) and
    # ticks (0 = automatic).

  The frame styling is shared with the legend and set there.


STYLE > REFERENCE LINES

  Vertical lines: wavelength (nm)
    Type a list of wavelengths, separated by commas or spaces, for
    example 450, 620, 700. Each set has its own color, pattern,
    width and opacity. 'Auto every N nm' plus Fill lays down a
    regular comb. Clear empties the box.

  Horizontal lines: absorbance
    The same controls at given Y values, for example 1.0, 2.5, with
    'Auto every N abs' plus Fill, and Clear.

  Reference lines draw on 2D plots. In 3D they draw as faint planes
  through the box.


TOP BAR > THEME

  The six entries above the divider are the working themes: Standard
    Light, Kinda Dark, Black Hole, and the three accessibility
    themes High Contrast, Colorblind Safe and Colorblind Safe Dark.
    Everything below the line changes interface colors only.

  Colorblind Safe and Colorblind Safe Dark use the Okabe-Ito
    palette, one on a white ground and one on a dark ground. Every
    color in both clears the 4.5:1 contrast floor.

  The plot itself stays neutral in every theme. 'Tint plot with
    theme' in STYLE > COLORS & COLORMAP is what changes that.


TOP BAR > SETTINGS

  The gear beside Theme opens the Settings panel. Esc shuts it, and
    so does a click outside.

  Font sets the typeface of every button, label and control. Jost is
    the standard face, and OpenDyslexic the dyslexia-friendly one,
    which works with any theme.

  Text size sets the size of every button, label and control,
    3 to 15. 'auto' takes the size from the screen resolution and
    the display scale. The figure's text sizes are separate, in
    STYLE > FONTS.

  Helper tips is the master switch for the hover tips.

  Performance mode, Tutorial and About share the panel. Every
    setting here applies live, and SPARTA remembers it.
