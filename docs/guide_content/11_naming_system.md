NAMING SYSTEM

A Run reads five things from every file: the DAC, the sample, the
value of the experiment variable, the channel (sample / background /
dark) and the grating segment.


TOKENS

  A token is whatever sits between two separators.

      vis_Y04_Arch29_26p0_s.003
      \_/ \_/ \____/ \__/ \/ \_/
       1   2    3      4   5  segment suffix

    Tokens 1 to 5 here are the prefix, the DAC id, the sample id,
    the value and the channel keyword. The segment suffix splits off
    before tokenizing, and empty tokens drop out.

  A profile assigns a meaning to each token position, in order:

      dac       the cell id. Required, unless a default gives it.
      sample    the sample id. Required, unless a default gives it.
      pressure  the value of the Series variable. Optional.
      role      the channel keyword (sample / background / dark).
      branch    the compression / decompression tag.
      rep       the retake number.
      ignore    a piece the pipeline does not need.

    'pressure' is the internal field name; the dialog shows the
    Series variable's name.


THE TWO KINDS OF PROFILE

  22-IR-1 default (built-in): a fixed grammar, read-only, stable
    across releases.

      vis_{DAC}_{Sample}[_{Pressure}][_bg|_s][_C|_D][_rep][.{seq}]

    - the name starts with 'vis' and carries at least three
      underscore-separated tokens
    - a bare name = dark, _bg = background, _s = sample
    - _C / _D is the branch tag, _2 / _3 a retake, in either order
    - the value uses 'p' for the decimal: 1p39 = 1.39. A missing
      value token reads as 0, with a note in the log
    - the segment suffix is a dot plus digits (.001 .. .00N). A file
      with no suffix is segment 1
    - a trailing '.csv' twin is tolerated and deduplicated

      vis_Y04_Arch29_26p0_s.003
        DAC       Y04
        sample    Arch29
        value     26.0
        channel   sample
        branch    none
        retake    1
        segment   3

    Rejections:

      vis_Y04_Arch29_26p0_s_r.003   unrecognized trailing token
      vis_Y04_Arch29_26p0_sA.003    unrecognized trailing token
      vis_Y04_Arch29_bg.001.002     malformed (extra extension)
      vis_Y04_Arch29_26p0_s.abc     segment is not numeric
      Y04_Arch29_26p0_s.003         does not match
                                    vis_DAC_SAMPLE[_PRESSURE]

    The built-in accepts bg / s / C / D / a digit retake. The fix is
    a custom profile or a per-file fix.

  Custom profiles: everything above becomes editable, saved under
    a name and surviving restarts.


THE PROFILE FIELDS

  Prefix
    A fixed first token, matched case-insensitively and consumed
    ('vis' in the classic names). Another first token is skipped
    with "missing prefix '<x>'".

  Separator
    The text between tokens, usually _ or -. Comma-separate
    alternatives ('_,-'), tried longest-first.

  Value decimal (labelled with the Series variable's name)
    'p' reads 12p5 as 12.5, '.' reads 12.5, ',' reads 12,5. '.' and
    ',' are accepted whatever you pick.

  Strip units
    Unit text removed from the END of the value token, comma-
    separated and case-insensitive: with 'gpa,kbar', '15.3GPa' reads
    as 15.3.

  Segment sep
    The text before the segment number at the end of the name, one
    or more characters ('_seg' reads name_seg003). The RIGHTMOST
    occurrence splits base from segment.

  Numbering
    - digits: any all-digit run, read with int(), so .001, .01 and
      .1 all mean segment 1.
    - letters: a = 1, b = 2 ... z = 26, then aa = 27 (spreadsheet
      style), case-insensitive. Capped at two letters, so .txt,
      .dat and .asc stay extensions.

  No number =
    What a bare name means: a segment index, normally 1, or
    'reject', which skips the file with the reason "no segment
    suffix ('<sep><segment>' required)".

  Background / Sample / Dark keyword(s)
    The token that marks each channel, comma-separated alternatives
    (bg,ref), case-insensitive. Dark is the default role.

  Compression / Decompression keyword(s)
    The branch tag, shown as C and D on the plot, with D dashed.
    Left blank, both fall back to c/d.

  Default DAC Name / Default Sample Name
    For single-cell folders whose names omit that piece. Put the
    value here AND drop that label from the token order.

  Token order
    The meanings in the order the pieces appear, set by the chips
    under 'Teach by example'.


HOW A NAME IS PARSED, STEP BY STEP

  1. A single trailing '.csv' is removed.

  2. The segment suffix splits off: the text after the rightmost
     segment separator decodes under the numbering scheme. It counts
     as a segment only when it decodes AND something is left in
     front; otherwise the 'No number =' policy applies.

  3. The rest tokenizes on the separator, and the prefix, if any,
     matches the first token and is consumed.

  4. The token order walks left to right against the remaining
     tokens:

     - dac, sample: consume the token unconditionally. A missing
       token is an error ("missing dac token").
     - ignore: consume a token if one is there.
     - pressure: consume the token ONLY if it reads as a number,
       after unit-stripping and decimal substitution; otherwise it
       passes to the NEXT field.
     - role: consume the token ONLY if it is a known channel
       keyword.
     - branch: consume the token ONLY if it is a known branch
       keyword.
     - rep: consume the token ONLY if it is all digits.

     One token order therefore reads both vis_Y04_Arch29_bg.001 and
     vis_Y04_Arch29_26p0_bg_C_2.001.

  5. Any token left over is an error: "unrecognized trailing token".

  6. Defaults fill what the name omits: value 0, channel dark,
     retake 1, plus the DAC and sample defaults you set.


TEACH BY EXAMPLE

  Open 'Name format' from the left panel.

  1. Pick a profile, or press 'Save as...' and name a new one. The
     built-in opens read-only.

  2. Set the grammar boxes: separator first, then prefix, decimal,
     unit stripping, keywords, segment convention.

  3. Under 'Teach by example', pick a filename that shows EVERY
     piece the scheme can produce. Each token gets a chip with a
     dropdown; set each dropdown to what that piece means. The gray
     pieces between chips are the literal separators, and the
     segment suffix sits at the end, captioned with how it was read.
     Click either to jump to the box that governs it.

  4. Watch the Preview, which parses every file in the folder with
     the grammar as it stands. Green rows parsed, red rows skipped
     with the reason, blue rows fixed by hand. The counter reads
     "matched N / M files". The preview reads at most 500 files.

  5. Press 'Use this profile'. A grammar with a problem makes the
     button refuse and lists it:

     - an empty separator
     - an unknown field
     - a role keyword that maps to no channel
     - dac or sample supplied by neither a token nor a default
     - an unusable segment scheme
     - a bad missing-segment value


GUESS FORMAT

  'Guess format' reads the folder and proposes the whole grammar.
  The preview is the real check.

  It settles the segment convention first, scoring the candidate
  separators (. - _ _seg -seg) against both numbering schemes. The
  strong signal is one base recurring with SEVERAL segment values.
  All files numbered sets 'No number =' to 'reject', some files
  numbered sets 1.

  It then takes the token separator with the most consistent token
  count, makes a shared literal first token the prefix, and
  classifies the rest as value, channel-keyword, branch and retake
  columns; the first two unclaimed columns become dac and sample.
  The keywords it knows are bg / ref / back / background, s / sam /
  samp / sample / sig, dark / dk / drk, c / comp / up, d / dec /
  decomp / down.

  It reports "matched N / M files" as a toast and in the log. A
  folder with fewer than two id columns, or a profile the validator
  rejects, gets a plain default.


WORKED EXAMPLES

  Every piece present, dash-separated:

      vis-D42-fo90-15.3GPa-s-c-2.003

      Prefix          vis
      Separator       -
      Value decimal   .
      Strip units     gpa
      Sample keyword  s
      Compression     c
      Segment sep     .
      Numbering       digits
      Order           dac, sample, pressure, role, branch, rep

    DAC D42, sample fo90, 15.3, sample channel, compression, retake
    2, segment 3.

  Letter segments (a/b/c):

      ol_run7_4p2_bg_b

      Segment sep  _
      Numbering    letters
      No number =  1

    The rightmost '_' splits 'b' off, which decodes as segment 2.
    The segment separator and the token separator are the same
    character here; give segments their own separator where you
    can, such as '-b' or '_segb'.

  Dash-numbered segments with underscore tokens:

      quartz_C3_8p1_s-2

      Separator    _
      Segment sep  -
      Numbering    digits

    The conventions stay apart, because '-' serves the segment
    alone.

  Single-cell folder, with DAC and sample outside the names:

      12p5_bg.001

      Prefix               (blank)
      Separator            _
      Default DAC Name     Y04
      Default Sample Name  Arch29
      Order                pressure, role

    The output CSVs are still named
    Y04_Arch29_12p5_absorbance.csv.

  A spare piece: in vis_20260731_Y04_Arch29_26p0_s.003, label the
    date chip 'ignore'.


EDGE CASES AND TRAPS

  Decimal character equal to the segment separator.
    With decimal '.' and segment sep '.', a name ending in a dotted
    value ('..._2.5') has its '5' read as a segment, because the
    segment split runs first. Give segments a different separator,
    or use 'p'.

  Token separator equal to the segment separator.
    Legal. Any trailing token that decodes under the numbering
    scheme becomes the segment: under 'digits' a trailing
    retake number, under 'letters' a trailing one-letter or
    two-letter keyword.

  A value of 0.
    Allowed and meaningful. A MISSING value token also reads as 0,
    and the log then records "no pressure in filename, assumed
    0 GPa".

  Negative or non-finite values.
    SPARTA takes a finite value at or above 0.

  Case.
    Prefix, channel keywords, branch keywords, unit suffixes and
    letter segments match case-insensitively. DAC and sample ids
    keep the case as written, because they become file names.

  Two profiles, one folder.
    One profile is active at a time. Run the majority convention,
    and fix the minority by hand.


FIXING STUBBORN FILES

  Double-click a preview row, or press 'Fix selected...', to type
  its fields by hand: Channel role (dark / background / sample),
  DAC, Sample, <Series variable>, Replicate and Segment.

  A blank field keeps what the parser produced. A fix beats any
  pattern, and a fix that supplies a channel role resurrects a
  rejected file.

  'Exclude selected' leaves the file out of the run, and the note
  reads "excluded by user". 'Remove fix' undoes one file, 'Clear all
  fixes' the whole folder. Fixes are stored per folder and applied
  after parsing on every Run, Rescan and preview.


WHERE THE PARSED VALUES GO

  dac, sample and the value become the output file name stem:
    {DAC}_{SAMPLE}_{VALUE}[_C|_D]_absorbance.csv.

  The trace's identity label is "{DAC} {SAMPLE} {VALUE} GPa", plus a
    branch tag and a retake note. The display relabels it to the
    active Series variable's unit; the label itself holds, as the
    key that presets, sessions and exports resolve through.
