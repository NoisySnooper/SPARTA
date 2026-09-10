"""guide_tour.py  --  the welcome card, the guided tour, and the Guide
panel's content.

Three things live here so app.py carries almost none of it:

  1. GUIDE CONTENT.  `guide_views()` builds the Guide / notes dropdown from
     docs/guide_content/*.md in the order manifest.json gives, falling back
     to the texts compiled into app.py when the folder is missing (a
     stripped-down install, or a package built without the docs tree).
     `bad_headings()` is the --selftest honesty gate: every ALL-CAPS
     heading in a LIVE gated view has to name a section that really exists
     in the right panel.

  2. THE WELCOME CARD.  First launch (and About > 'Welcome & tour...')
     opens a short, friendly orientation card with three ways out: start
     the tour, open the guide, or just explore.  'Don't show this again'
     writes one settings key.

  3. THE TOUR.  A game-style walkthrough, in named CHAPTERS: the window
     darkens except for a spotlight on the control being explained, and a
     callout card with an arrow points at it.  The spotlight is four
     semi-transparent black strips tiling the window AROUND the target
     rectangle, so the target itself is never covered - it stays live, and
     a step can ask you to click it.

     The tour is HANDS-ON.  Wherever an action is safe and observable the
     step waits for you to do it on the real control (Run, a plot mode, a
     colormap, opening a dialog) rather than narrating it at you, and the
     dialogs - Name format, Smoothing settings, the formula editor - are
     walked from the INSIDE: the spotlight and the card follow the target
     into whichever Toplevel owns it, and a modal grab is released while
     the tour is driving so both the dialog and the card stay clickable.

     Steps are data (see TOUR_STEPS): a chapter, a resolver that finds the
     widget, the words, an optional pre-action that makes the widget
     reachable, an optional one-click action for people who would rather
     not, and an optional predicate for 'now you try it'.

Nothing in here touches app.py's state except through the public methods
it already has, so the tour cannot corrupt a session.

NQT / Lee Lab -- Aug 2026
"""

import json
import os
import re
import sys
import tempfile
import tkinter as tk
from tkinter import ttk

TOOL_DIR = os.path.dirname(os.path.abspath(__file__))


def _roots():
    """Places the shipped content can be, most specific first.

    Running from source it is simply the folder this file sits in. A
    frozen build unpacks its data under sys._MEIPASS, and a onedir build
    keeps a copy beside the executable, so try all three rather than bet
    on one packaging layout.
    """
    out = [TOOL_DIR]
    mei = getattr(sys, "_MEIPASS", None)
    if mei:
        out.append(mei)
    if getattr(sys, "frozen", False):
        out.append(os.path.dirname(os.path.abspath(sys.executable)))
    seen, uniq = set(), []
    for r in out:
        if r and r not in seen:
            seen.add(r)
            uniq.append(r)
    return uniq


def _find_dir(*parts):
    """First existing <root>/<parts...>; the source-tree path if none is."""
    for r in _roots():
        p = os.path.join(r, *parts)
        if os.path.isdir(p):
            return p
    return os.path.join(TOOL_DIR, *parts)


GUIDE_DIR = _find_dir("docs", "guide_content")
DEMO_DIR = _find_dir("demo_data")

# Settings keys this module owns.  Written into app.settings once at
# startup by app.py's "# d2 keys" block; never renamed, never reused.
D2_SETTINGS_DEFAULTS = {
    "welcome_seen": False,     # the welcome card's "Don't show this again"
    "tour_done": False,        # set when the tour reaches its last step
}

# The scrim is a fixed constant, not a derived color: it has to read as
# "the light is off here" in every theme, and a themed scrim would tint
# the application instead of dimming it (same standing as the NUKE red).
SCRIM = "#000000"
SCRIM_ALPHA = 0.55
ARROW = 14                     # px thickness of the callout's arrow gutter
PAD_BTN = 6                    # the one gap between two buttons on a row
WATCH_MS = 250                 # the follow-the-target watchdog interval

# The tour's boxes are sized in CHARACTERS of the ACTIVE prose face, not
# in digit-ems.  app._em() measures a '0', which is the right unit for
# the panel grid but the wrong one for prose: OpenDyslexic - the App font
# value that puts a dyslexia-friendly face on the whole UI, and the two
# retired Dyslexic themes before it - draws a '0' barely wider than
# Jost's while its letters run about 40% wider.  A card of em * 54 held
# 73 characters per line in Jost and only 57 in OpenDyslexic, which is
# the cramped, oddly wrapped tour Nhan ran into.  Measuring the alphabet
# keeps the LINE LENGTH constant instead, so a wide face is given a wider
# card - which is what a reader actually feels.
_ALPHA = "abcdefghijklmnopqrstuvwxyz"
CARD_CHARS = 73                # characters per line the callout aims for
WELCOME_CHARS = 89             # the welcome dialog, same measure


def _adv(app):
    """Average advance of one lowercase letter in the ACTIVE body face,
    measured NOW: the theme (and so the face) can change under a running
    tour, and every caller re-asks rather than caching a build-time
    number."""
    try:
        f = app._F(0)
        return max(4.0, f.measure(_ALPHA) / float(len(_ALPHA)))
    except Exception:
        return 7.4


def _box_px(app, chars):
    """Width in pixels of a box `chars` characters wide in the active
    face, clamped so a wide face can grow the card but never past a bit
    over half the window (the callout has to leave its target visible,
    and _card_spot needs somewhere to put it)."""
    w = int(round(chars * _adv(app)))
    try:
        rw = app.root.winfo_width()
    except Exception:
        rw = 0
    if rw > 200:
        w = min(w, int(rw * 0.55))
    return max(240, w)


# ---------------------------------------------------------------------------
# 1. Guide content
# ---------------------------------------------------------------------------
_FALLBACK_QUICK_START = (
    "QUICK START\n\n"
    "1. Select the Input folder of raw segment files. Another filename\n"
    "   scheme is taught in 'Name format', under the folder box.\n"
    "2. Select an Output folder and press Run. SPARTA joins the grating\n"
    "   segments of each measurement, computes absorbance, and writes one\n"
    "   CSV per measurement to <output>/<inputname>_absorbance/. The ticks\n"
    "   in Export > Data files pick the columns that CSV carries.\n"
    "3. Every trace plots at once. The right panel holds six tabs, Plot,\n"
    "   Axes, Style, Data, Fringe and Export, and 'Find a setting' at the\n"
    "   top opens the section that holds a control.\n"
    "4. Export tab > Figure: a Journal preset sets the column width and\n"
    "   the house style in one pick. Export tab > Export writes the\n"
    "   figure. The Export dialog writes the CSVs into any folder:\n"
    "   'Export\u2026' in the left panel, 'Export data\u2026' in Export\n"
    "   tab > Data files, or Ctrl+E.\n\n"
    "With no data at hand, About > 'Welcome & tour...' loads a small\n"
    "bundled demo series and walks the whole path."
)


def _strip_markers(text):
    """Drop the editorial <!-- ... --> comments the content carries."""
    out, i = [], 0
    while True:
        a = text.find("<!--", i)
        if a < 0:
            out.append(text[i:])
            break
        b = text.find("-->", a)
        if b < 0:
            out.append(text[i:a])
            break
        head = text[i:a]
        # a marker on its own line takes the whole line with it
        if head.endswith("\n") and text[b + 3:b + 4] == "\n":
            out.append(head)
            i = b + 4
        else:
            out.append(head)
            i = b + 3
    return "".join(out)


def _read_text(path):
    try:
        with open(path, "r", encoding="utf-8") as f:
            return f.read()
    except Exception:
        return None


# ---- reflow: authoring width is not reading width -------------------------
# The guide files are hard-wrapped at ~72 columns for the repository's
# sake.  Shown raw, those newlines fight the panel's real width and every
# paragraph comes out ragged - long line, short line, hanging indent -
# which is exactly the mess Nhan photographed.  So the loader reflows:
# the lines of a paragraph are joined back into one and the Text widget
# (wrap="word") breaks them wherever the panel actually ends, while
# anything whose SHAPE carries meaning keeps its line breaks untouched.
#
# What stays verbatim, from the manifest's own format contract:
#   - ALL-CAPS headings (the honesty-gated section names among them);
#   - lines indented six spaces or more THAT ALSO READ AS VERBATIM
#     (R20): the contract marks six spaces "horizontal alignment is
#     meaningful", but a wrapped continuation line under a deep list
#     item reaches that indent too, and freezing it put whole
#     sentences in the mono face.  So depth alone no longer decides:
#     a deep line is verbatim when it is a column-aligned row, or when
#     it carries a verbatim shape (one of = -> / \ < > { } [ ] or a
#     token with two or more digits) and does NOT read as a sentence.
#     A deep line that reads as prose joins the paragraph above it -
#     the hanging continuation it always was;
#   - column-aligned rows at any indent (three or more spaces inside the
#     line, the shortcut tables' shape);
#   - list rows ("- " or "1." / "1)") start their own paragraph, so a
#     list never collapses into a wall, but their wrapped continuation
#     lines still join up.
#
# guide_segments() is the one classifier; it returns (tag, text) pairs
# so a renderer can also STYLE the parts differently - prose in the
# body face, verbatim blocks in mono.  Tags:
#   'h'    ALL-CAPS heading line, verbatim
#   's'    sub-heading: a one-line paragraph at column 0
#   'b'    prose paragraph at column 0, joined onto one line
#   'i'    indented prose paragraph, joined (its indent survives)
#   'm'    monospace line, verbatim
#   'gap'  one blank line
#   'raw'  a whole un-reflowed text (the compiled built-in views)
# A renderer that ignores the tags loses nothing but the styling:
# reflow_guide() below is exactly "join the texts with newlines".
_MONO_INDENT = 6
_LIST_ROW = re.compile(r"^(- |\d+[.)]\s)")
# a control-name lead: the name of a control, then ": " and what it does.
# It is what starts an item when the item sits deeper than the block's
# base indent, under a sub-heading of its own ("3D shape" over "Draft
# quality while rotating: draws a coarser sheet ...").  A name is SHORT
# (48 characters at most), carries no sentence period, and opens with a
# capital, a digit or a quote, so a wrapped continuation that happens to
# run past a colon is not mistaken for one: "ticked: those centres come
# out" opens mid-sentence, and "written beside the trace's CSV: the notch
# columns that used to" runs too long.
_ITEM_LEAD = re.compile(r"^[\"'(\[]?[A-Z0-9][^.:]{1,47}: \S")
# the characters that mark a line as machine text rather than a sentence:
# assignments and arrows, paths, angle brackets, braces and brackets
_VERBATIM_CHARS = "=/\\<>{}[]"
_WORD = re.compile(r"[A-Za-z]{3,}")


def _indent_of(line):
    return len(line) - len(line.lstrip(" "))


def _is_heading(line):
    s = line.strip()
    return bool(s) and s == s.upper() and any(c.isalpha() for c in s)


def is_table_row(line):
    """A column-aligned row: three or more spaces inside the line.

    A TWO-space gap is only a table row when its siblings prove it
    (_block_segments promotes those), because prose is allowed to carry
    an incidental double space ("Name format:  22-IR-1").
    """
    return "   " in line.strip()


def reads_as_prose(line):
    """True when the line reads as a sentence: three consecutive
    all-lowercase words of three or more letters.

    This is the ONE prose test.  app.py's fallback classifier imports it
    so the panel, the [?] boxes and the compiled built-ins all draw the
    line between a sentence and a verbatim block in the same place.
    "and notches noise now and then." passes; "A = -log10(S / B)",
    "docs/guide_content/20_plot_tab.md" and the column list
    "Wavelength_nm, Wavenumber_cm-1, Absorbance, Dark, Background" do
    not - a run of Capitalised names is not a sentence.
    """
    run = 0
    for tok in (line or "").split():
        w = tok.strip(".,;:!?()'\"")
        if len(w) >= 3 and w.isalpha() and w.islower():
            run += 1
            if run >= 3:
                return True
        else:
            run = 0
    return False


def is_verbatim_shape(line):
    """True when the line carries machine text and does not read as a
    sentence: a verbatim character, or a token with two or more digits.

    "and/or the notch columns" carries a slash and still reads as prose,
    so it is not verbatim; "Sample - Dark / Background - Dark" is.
    """
    s = (line or "").strip()
    if not s:
        return False
    if not (any(ch in s for ch in _VERBATIM_CHARS)
            or any(sum(c.isdigit() for c in t) >= 2 for t in s.split())):
        return False
    return not reads_as_prose(s)


def _is_mono_line(line):
    if _indent_of(line) >= _MONO_INDENT:
        # depth alone is not verbatim any more (R20): a wrapped
        # continuation under a deep item lands here too
        return is_table_row(line) or is_verbatim_shape(line)
    return is_table_row(line)


def guide_segments(text):
    """The text of one guide view, classified into (tag, text) pairs."""
    segs, block = [], []
    for raw in text.split("\n"):
        line = raw.rstrip()
        if not line.strip():
            if block:
                segs.extend(_block_segments(block))
                block = []
            if segs and segs[-1][0] != "gap":
                segs.append(("gap", ""))
        else:
            block.append(line)
    if block:
        segs.extend(_block_segments(block))
    while segs and segs[-1][0] == "gap":
        segs.pop()
    return segs


def _block_segments(lines):
    """One blank-line-delimited block, classified.

    The subtlety is telling two paragraph shapes apart.  Flat blocks
    repeat one indent ("  a\\n  b\\n  c" is ONE paragraph); hanging
    blocks return to a base indent to start each item ("  item\\n
    cont\\n  item" is TWO).  Whether any line sits deeper than the
    block's shallowest prose line is what says which shape this is.

    A hanging item returns to ITS OWN first-line indent, not to the
    block's base, so a block that nests ("3D shape" at two, its items
    at four, their continuations at six) breaks into one paragraph per
    item rather than one paragraph for the lot.  Only an indent that
    has something deeper under it carries items that way; an indent
    that is the deepest in its block is wrapped text and stays whole.
    The first item of a nest has nothing shallower to return to, so a
    list marker or a control-name lead (_ITEM_LEAD) starts it.
    """
    out = []
    kinds = []
    for l in lines:
        if _is_heading(l):
            kinds.append("h")
        elif _is_mono_line(l):
            kinds.append("m")
        else:
            kinds.append("p")
    # column rows whose gap is only TWO spaces ride with their table: a
    # line that shares its indent with a mono sibling in this block and
    # carries an internal 2+ space run is a row of the same table
    # ("Drop a folder  Make it..." between two three-space rows), while
    # the identical shape with no such sibling is prose with a quoted
    # double space in it and reflows like any other sentence.
    for _pass in (1, 2):
        mono_indents = set(_indent_of(l) for l, k in zip(lines, kinds)
                           if k == "m")
        for j, (l, k) in enumerate(zip(lines, kinds)):
            if k != "p":
                continue
            ind = _indent_of(l)
            if ind in mono_indents and re.search(r"\S {2,}\S", l):
                kinds[j] = "m"
                continue
            # a definition row wrapped into a deep hanging column
            # ("digits  - any all-digit run," continued 10 spaces in):
            # the continuation is already mono by depth, so the row it
            # belongs to must stay a row or half the sentence freezes
            # and half reflows
            if (j + 1 < len(lines) and kinds[j + 1] == "m"
                    and _indent_of(lines[j + 1]) >= ind + 6
                    and (re.search(r"\S {2,}\S", l)
                         or re.match(r"\S+ - \S", l.strip()))):
                kinds[j] = "m"
    prose = [l for l, k in zip(lines, kinds) if k == "p"]
    indents = set(_indent_of(l) for l in prose)
    # the indents that carry ITEMS rather than wrapped text: an indent
    # with something deeper under it.  Returning to an item indent
    # starts the next item ("Fill opacity:" under "Color traces by
    # colormap:"), while a paragraph that wraps at its own indent with
    # nothing deeper stays one paragraph ("The um to cm conversion sits
    # inside the builtin. Hand it t in" / "um and read cm^-1.").  One
    # indent in the block leaves no item level at all, which is what
    # makes a flat block one paragraph.
    items = set(i for i in indents if any(j > i for j in indents))
    para, pind = [], 0

    def flush():
        if not para:
            return
        if pind == 0 and len(para) == 1:
            out.append(("s", para[0]))
        else:
            out.append(("i" if pind else "b", " " * pind + " ".join(para)))
        del para[:]

    for l, k in zip(lines, kinds):
        if k == "h":
            flush()
            out.append(("h", l.strip()))
            continue
        if k == "m":
            flush()
            out.append(("m", l))
            continue
        ind, s = _indent_of(l), l.strip()
        if para and (_LIST_ROW.match(s) or ind < pind
                     or (ind in items
                         and (ind <= pind or _ITEM_LEAD.match(s)))):
            flush()
        if not para:
            pind = ind
        para.append(s)
    flush()
    return out


def reflow_guide(text_or_segments):
    """Reflowed plain text: what the Guide panel shows.

    Takes either a raw view text or the segments guide_segments made of
    one, so a caller that wants both never classifies twice.
    """
    segs = text_or_segments
    if isinstance(segs, str):
        segs = guide_segments(segs)
    return "\n".join(t for _tag, t in segs).rstrip() + "\n"


def load_manifest(base_dir=None):
    """The guide manifest, or None when the content tree is missing."""
    d = base_dir or GUIDE_DIR
    raw = _read_text(os.path.join(d, "manifest.json"))
    if not raw:
        return None
    try:
        man = json.loads(raw)
    except ValueError:
        return None
    return man if isinstance(man, dict) and man.get("views") else None


def _view_is_live(entry):
    """A view is live unless the manifest says it is not yet built.

    The fringe workbench view ships with "live": false and is flipped by
    the patch that actually builds the Fringe tab, so the honesty gate
    never checks headings for a panel that does not exist yet.
    """
    return bool(entry.get("live", True))


def guide_views(builtin=None, base_dir=None, segments=None):
    """Ordered {view name: text} for the Guide / notes dropdown.

    `builtin` is app.py's REF_VIEWS: the texts compiled into the program.
    Views the manifest maps to a file are read from disk - reflowed to
    reading width (see guide_segments above) - while views with no file
    (Absorbance reference, Panel guide) keep their compiled text as is.
    Missing content tree, unreadable manifest, unreadable file: that view
    falls back to the compiled text, so the dropdown is never empty and
    the program never fails to start over a missing doc.

    `segments`, when a dict is passed, is filled with {view name:
    [(tag, text), ...]} for every view returned - the same texts, plus
    the classification a renderer needs to give prose the body font and
    verbatim blocks a mono one.  Built-in texts come back as one
    ('raw', text) pair.  A caller that ignores it gets exactly the old
    contract.
    """
    builtin = dict(builtin or {})
    segmap = segments if isinstance(segments, dict) else None

    def keep(name, text, segs=None):
        out[name] = text
        if segmap is not None:
            segmap[name] = segs if segs else [("raw", text)]

    man = load_manifest(base_dir)
    if man is None:
        if "Quick start" not in builtin:
            builtin["Quick start"] = _FALLBACK_QUICK_START
        if segmap is not None:
            for name, text in builtin.items():
                segmap[name] = [("raw", text)]
        return builtin
    d = base_dir or GUIDE_DIR
    by_name = {}
    for e in man.get("views", []):
        if e.get("view"):
            by_name[e["view"]] = e
    order = [n for n in man.get("dropdown_order", []) if n != "My notes"]
    for n in by_name:
        if n not in order and n != "My notes":
            order.append(n)
    out = {}
    for name in order:
        e = by_name.get(name, {})
        text = segs = None
        if e.get("file"):
            raw = _read_text(os.path.join(d, e["file"]))
            if raw is not None:
                try:
                    segs = guide_segments(_strip_markers(raw))
                    text = reflow_guide(segs)
                except Exception:
                    # a view that defeats the classifier still shows,
                    # just at authoring width
                    segs = None
                    text = _strip_markers(raw).rstrip() + "\n"
        if text is None:
            text = builtin.get(name)
        if text:
            keep(name, text, segs)
    for name, text in builtin.items():           # never lose a built-in view
        if name not in out:
            keep(name, text)
    return out


def live_section_titles(app):
    """{'PLOT > PLOT MODE', ...} from the sections the app really built.

    The fringe workbench is built on FIRST USE (app.py's _init_fringe
    leaves it unbuilt so an unopened panel costs no re-layout on every
    theme or text-size change), and its cards register themselves in
    _collapsibles only when they exist. Anything asking what sections
    the app has -- the honesty gate above all -- has to bring it up
    first, or the gate would silently stop checking the whole FRINGE
    section set and report a pass it never earned.
    """
    build_fringe(app)
    cat = getattr(app, "_section_cat", {})
    return set("%s > %s" % (cat.get(rec["key"], "?").upper(),
                            rec["key"].upper())
               for rec in getattr(app, "_collapsibles", []))


def bad_headings(app, panel_guide="", base_dir=None):
    """Gated headings that name no section the app actually built.

    The honesty gate.  Checked for app.py's own PANEL_GUIDE plus every
    manifest view that is BOTH gate="section_headings" AND live.  Line 1
    of a view is its title and is exempt, matching PANEL_GUIDE's own
    convention.  Returns a list of "<view>: <line>" strings; empty is a
    pass.
    """
    secs = live_section_titles(app)
    outside = ("LEFT PANEL", "TOP BAR", "PLOT AREA")

    def scan(label, text):
        bad = []
        for ln in text.splitlines()[1:]:
            ln = ln.rstrip()
            if (ln[:1].isalpha() and ln == ln.upper()
                    and ln not in secs and not ln.startswith(outside)):
                bad.append("%s: %s" % (label, ln))
        return bad

    out = scan("PANEL_GUIDE", panel_guide) if panel_guide else []
    man = load_manifest(base_dir)
    if man is None:
        return out
    d = base_dir or GUIDE_DIR
    for e in man.get("views", []):
        if e.get("gate") != "section_headings" or not e.get("file"):
            continue
        if not _view_is_live(e):
            continue
        text = _read_text(os.path.join(d, e["file"]))
        if text:
            out += scan(e["file"], _strip_markers(text))
    return out


# ---------------------------------------------------------------------------
# 2. Demo data
# ---------------------------------------------------------------------------
def demo_available():
    return os.path.isdir(DEMO_DIR) and any(
        n.startswith("vis_") for n in os.listdir(DEMO_DIR))


def demo_output_dir():
    """A writable scratch folder for the demo run (never the demo folder
    itself - a Run must not litter something we ship)."""
    d = os.path.join(tempfile.gettempdir(), "sparta_demo_output")
    try:
        if not os.path.isdir(d):
            os.makedirs(d)
    except OSError:
        return tempfile.gettempdir()
    return d


def load_demo(app):
    """Point the folders at the bundled demo series. Returns True on ok."""
    if not demo_available():
        app._warn("Demo data",
                  "The bundled demo folder is missing from this install "
                  "(expected demo_data beside the program). Pick your own "
                  "input folder instead.")
        return False
    app.in_var.set(DEMO_DIR)
    app.out_var.set(demo_output_dir())
    try:
        app._logline("Demo data loaded: 5 series points, 3 channels, "
                     "2 grating segments (synthetic).")
    except Exception:
        pass
    return True


def run_demo(app):
    """Load the demo folders and start the run."""
    if load_demo(app):
        app._run()
        return True
    return False


# ---------------------------------------------------------------------------
# 3. Small widget-finding helpers used by the step resolvers
# ---------------------------------------------------------------------------
def _alive(w):
    try:
        return bool(w is not None and w.winfo_exists())
    except Exception:
        return False


def app_module(app):
    """The module app.py was loaded as - '__main__' when the GUI is run
    directly, 'app' when it is imported. Never import app.py by name from
    here: that would build a SECOND copy of the module."""
    import sys
    return sys.modules.get(type(app).__module__)


def brand(app, key, default):
    """One string out of app.py's BRAND dict; the name lives only there."""
    mod = app_module(app)
    b = getattr(mod, "BRAND", None) if mod is not None else None
    if isinstance(b, dict) and b.get(key):
        return b[key]
    return default


def build_fringe(app):
    """Make sure the fringe workbench's cards exist, without showing it.

    app.py builds the workbench on FIRST USE, so its six cards (Stack,
    Session, Pressure point, FFT removal, Refractive Index from
    Intensity, Panels) are absent from _collapsibles until then. Every
    lookup here that could name one of them goes through this first.
    build() is idempotent and does NOT switch the centre view --
    _ensure_fringe is what does that.
    """
    fr = getattr(app, "_fringe", None)
    if fr is None or getattr(fr, "_built", False):
        return fr
    if getattr(fr, "_gt_build_failed", False):
        return fr                      # it said no once; do not keep asking
    try:
        fr.build()
        app.root.update_idletasks()
    except Exception:
        # remembered, because gate predicates land here on a 400 ms
        # clock: a build that raises once would otherwise be re-attempted
        # forever, and a half-built panel re-registering its cards is
        # exactly the kind of wreck a tour must never cause.  The steps
        # that needed the workbench simply skip themselves instead.
        try:
            fr._gt_build_failed = True
        except Exception:
            pass
    return fr


def section_rec(app, key):
    for rec in getattr(app, "_collapsibles", []):
        if rec.get("key") == key:
            return rec
    # not there yet: it may be one of the workbench's, which only
    # register once the panel has been built
    if build_fringe(app) is not None:
        for rec in getattr(app, "_collapsibles", []):
            if rec.get("key") == key:
                return rec
    return None


def open_section(app, tab, key):
    """Show a right-panel section: select its tab, unfold it, scroll to it."""
    select_tab(app, tab)
    rec = section_rec(app, key)
    if rec is None:
        return None
    try:
        if rec.get("collapsed"):
            app._set_collapsed(rec, False)
    except Exception:
        pass
    return rec


def select_tab(app, label):
    nb = getattr(app, "rnotebook", None)
    if nb is None:
        return
    try:
        for i, tab in enumerate(nb.tabs()):
            if str(nb.tab(tab, "text")).strip() == label:
                nb.select(i)
                return
    except Exception:
        pass


def section_body(app, key):
    rec = section_rec(app, key)
    return rec["cont"] if rec else None


def sections_span(app, keys):
    """The union of several sections - one spotlight over two neighbors."""
    out = [section_body(app, k) for k in keys]
    out = [w for w in out if _alive(w)]
    return out or None


def _walk(parent):
    """Every descendant of `parent`, breadth first."""
    if not _alive(parent):
        return
    stack = list(parent.winfo_children())
    while stack:
        w = stack.pop(0)
        yield w
        try:
            stack.extend(w.winfo_children())
        except Exception:
            pass


def _k(t):
    """Normalise a label for matching: three dots and the ellipsis
    character are the same button (app.py's `_k`, same reason)."""
    return str(t).strip().replace("...", "…")


def find_by_text(parent, text):
    """First descendant whose -text option equals `text` (depth first)."""
    want = _k(text)
    for w in _walk(parent):
        try:
            if _k(w.cget("text")) == want:
                return w
        except Exception:
            pass
    return None


def next_sibling(widget):
    """The widget packed immediately after this one - a label's own box."""
    if not _alive(widget):
        return None
    try:
        sibs = widget.master.winfo_children()
        i = sibs.index(widget)
    except Exception:
        return None
    return sibs[i + 1] if i + 1 < len(sibs) else None


def find_all_text(parent, texts):
    """The widgets carrying each of `texts`, in that order, skipping any
    that is missing.  None when nothing at all was found."""
    out = [find_by_text(parent, t) for t in texts]
    out = [w for w in out if _alive(w)]
    return out or None


def card_of(widget):
    """The BrandCard a widget sits in, or None.

    A card is recognized by its shape (a .body frame and .set_title), not
    by its class name, so this keeps working if the class is ever moved.
    """
    node = widget
    for _ in range(12):
        if not _alive(node):
            return None
        if hasattr(node, "body") and hasattr(node, "set_title"):
            return node
        node = getattr(node, "master", None)
    return None


def common_block(parent, texts):
    """The nearest frame that contains ALL of `texts` - the rectangle of a
    group of rows that has no attribute of its own to point at."""
    found = [find_by_text(parent, t) for t in texts]
    found = [w for w in found if _alive(w)]
    if not found:
        return None
    if len(found) == 1:
        return found[0]
    chains = []
    for w in found:
        chain, node = [], w
        while _alive(node):
            chain.append(str(node))
            node = getattr(node, "master", None)
        chains.append(chain)
    first = chains[0]
    for name in first:
        if all(name in c for c in chains[1:]):
            try:
                return found[0].nametowidget(name)
            except Exception:
                return None
    return None


def span_from(label):
    """The label plus every sibling packed after it - the rectangle of a
    sub-heading and the rows that belong to it."""
    if not _alive(label):
        return None
    try:
        sibs = label.master.winfo_children()
        i = sibs.index(label)
    except Exception:
        return label
    return [w for w in sibs[i:] if _alive(w)]


def _rect(widget):
    try:
        return (widget.winfo_rootx(), widget.winfo_rooty(),
                max(1, widget.winfo_width()), max(1, widget.winfo_height()))
    except Exception:
        return None


def union_rect(target):
    """Screen rectangle of a widget, or of a list of widgets."""
    if target is None:
        return None
    if not isinstance(target, (list, tuple)):
        target = [target]
    boxes = [_rect(w) for w in target if _alive(w)]
    boxes = [b for b in boxes if b and b[2] > 1 and b[3] > 1]
    if not boxes:
        return None
    x0 = min(b[0] for b in boxes)
    y0 = min(b[1] for b in boxes)
    x1 = max(b[0] + b[2] for b in boxes)
    y1 = max(b[1] + b[3] for b in boxes)
    return (x0, y0, x1 - x0, y1 - y0)


def owner_window(target):
    """The Toplevel (or root) a target lives in - the window the scrim has
    to tile.  A step whose target moved into a dialog dims the dialog."""
    w = target[0] if isinstance(target, (list, tuple)) and target else target
    if not _alive(w):
        return None
    try:
        return w.winfo_toplevel()
    except Exception:
        return None


def scroll_into_view(app, target):
    """Scroll the right-panel page that owns `target` until it shows."""
    w = target[0] if isinstance(target, (list, tuple)) and target else target
    if not _alive(w):
        return
    canvases = list(getattr(app, "_tab_canvases", []))
    node, canvas = w, None
    while _alive(node):
        if node in canvases:
            canvas = node
            break
        node = getattr(node, "master", None)
    if canvas is None:
        return
    inner = None
    try:
        for item in canvas.find_all():
            if canvas.type(item) == "window":
                inner = canvas.nametowidget(canvas.itemcget(item, "window"))
                break
    except Exception:
        return
    if not _alive(inner):
        return
    try:
        app.root.update_idletasks()
        total = max(1, inner.winfo_height())
        y = w.winfo_rooty() - inner.winfo_rooty()
        view = canvas.winfo_height()
        if view >= total:
            return
        top = canvas.canvasy(0)
        h = max(w.winfo_height(), 1)
        if y >= top + 10 and y + h <= top + view - 10:
            return                      # already comfortably on screen
        canvas.yview_moveto(max(0.0, min(1.0, (y - 30.0) / total)))
        app.root.update_idletasks()
    except Exception:
        pass


# ---- dialogs the tour walks from the inside -------------------------------
NAME_FORMAT = ("Name format",)
SMOOTH_PANEL = ("Smoothing settings (Igor 5-step)",)
FORMULA_EDITOR = ("New formula", "Edit formula", "View formula")
NOTCH_LIST = ("Notch list",)


def find_dialog(app, titles):
    """The app's own Toplevel carrying one of `titles`, or None.

    Matched on winfo_class rather than isinstance: a probe harness may
    have replaced tk.Toplevel with a subclass of its own.
    """
    root = getattr(app, "root", None)
    if root is None:
        return None
    try:
        kids = list(root.winfo_children())
    except Exception:
        return None
    for w in reversed(kids):
        try:
            if w.winfo_class() != "Toplevel" or not w.winfo_exists():
                continue
            if str(w.title()) in titles:
                return w
        except Exception:
            continue
    return None


def in_dialog(titles, pick, fallback):
    """A target that lives inside a dialog.

    While the dialog is open the spotlight is on `pick(app, dialog)` (the
    whole dialog when the pick misses).  While it is shut the step falls
    back to whatever OPENS it, so a resolver never comes back empty - the
    tour's own skip logic and the test that walks every target both read
    a target that resolves.
    """
    def _resolve(app):
        d = find_dialog(app, titles)
        if d is not None:
            try:
                w = pick(app, d)
            except Exception:
                w = None
            if w is not None:
                return w
            return d
        try:
            return fallback(app)
        except Exception:
            return None
    return _resolve


def dialog_open(titles):
    return lambda a: find_dialog(a, titles) is not None


def dialog_shut(titles):
    return lambda a: find_dialog(a, titles) is None


# ---- the top bar's Settings panel -----------------------------------------
# R14 moved the app font, the text size, the helper switch, Performance
# mode, About and the tutorial off the bar and into one anchored panel
# behind a gear.  The panel is a Toplevel like the dialogs above, with two
# differences the tour has to know about: it carries the ROOT's title, so
# find_dialog cannot see it, and it shuts itself the moment the keyboard
# focus lands outside it.
def settings_open(app):
    """True while the Settings panel is on screen."""
    try:
        return bool(app._settings_menu_open())
    except Exception:
        return False


def settings_win(app):
    """The Settings panel's own Toplevel, or None.  The app publishes the
    window itself, which is what the tour reads."""
    win = getattr(app, "_settings_win", None)
    return win if _alive(win) else None


def open_settings(app):
    """Show the Settings panel and keep it up for the step.

    The panel shuts on FocusOut, and the tour's callout is a window of its
    own that takes the focus the moment it paints.  So the tour drops that
    ONE binding on the panel it opened; Escape, the gear and a click in the
    main window all still shut it, which is how the reader closes it too.
    """
    if not settings_open(app):
        fn = getattr(app, "_show_settings_menu", None)
        if not callable(fn):
            return None
        try:
            fn()
        except Exception:
            return None
    win = settings_win(app)
    if win is not None:
        try:
            win.unbind("<FocusOut>")
        except Exception:
            pass
        try:
            app.root.update_idletasks()
        except Exception:
            pass
    return win


def close_settings(app):
    """Put the bar back the way the reader found it."""
    fn = getattr(app, "_hide_settings_menu", None)
    if callable(fn):
        try:
            fn()
        except Exception:
            pass


def in_settings(pick, fallback):
    """A target that lives inside the Settings panel.

    Same contract as in_dialog: while the panel is open the spotlight is on
    pick(app, win), and while it is shut the step falls back to the gear
    that opens it, so a resolver never comes back empty.
    """
    def _resolve(app):
        win = settings_win(app)
        if win is not None:
            try:
                w = pick(app, win)
            except Exception:
                w = None
            return w if w is not None else win
        try:
            return fallback(app)
        except Exception:
            return None
    return _resolve


# The formula editor's boxes start empty but the LaTeX box carries ghost
# hint text, so "has the user typed something" is answered by comparing
# against a snapshot taken when the step opens, not by testing for empty.
_ARMED = {}


def _entry_values(app, titles):
    d = find_dialog(app, titles)
    if d is None:
        return None
    out = []
    for w in _walk(d):
        try:
            if w.winfo_class() in ("TEntry", "Entry"):
                out.append(str(w.get()))
        except Exception:
            pass
    return tuple(out)


def arm_formula(app):
    _ARMED["formula"] = _entry_values(app, FORMULA_EDITOR)


def formula_touched(app):
    now = _entry_values(app, FORMULA_EDITOR)
    if now is None:
        return True                    # the editor is gone; do not block
    return now != _ARMED.get("formula")


# ---- what a 'do it for me' button does, and how it answers back -----------
def _press(widget):
    """Press a real control. True when something was actually pressed."""
    if not _alive(widget):
        return False
    try:
        widget.invoke()
    except Exception:
        return False
    return True


def _say(app, text):
    """A 'do it for me' button's own answer, put where the reader is
    already looking: the hint line under the card's prose."""
    fn = getattr(getattr(app, "_tour", None), "say", None)
    if callable(fn):
        try:
            fn(text)
            return
        except Exception:
            pass
    try:
        app._logline(text)
    except Exception:
        pass


def close_dialog(titles, texts=("Close", "Cancel")):
    """Shut a dialog the way its own buttons shut it.

    Three steps only want a window closed, and until now they asked and
    then waited: no action button, so a reader who had already closed it
    sat out the full PATIENCE wondering what they had done wrong (the
    usability probe, F2).  The fix presses the dialog's OWN button rather
    than destroying the window, so whatever that button promised still
    happens - Cancel putting the smoothing values back, a leave guard
    having its say.  Escape is the second try, because all three of these
    windows bind it to the same path, and only a window that answers to
    neither is closed outright.
    """
    def _go(app):
        d = find_dialog(app, titles)
        if d is None:
            _say(app, "That window is already closed. Press Next to carry on.")
            return
        for t in texts:
            if _press(find_by_text(d, t)):
                return
        try:
            d.event_generate("<Escape>")
        except Exception:
            pass
        if find_dialog(app, titles) is None:
            return
        try:
            d.destroy()
        except Exception:
            pass
    return _go


def _formula_chips(app, d):
    """The strip of clickable symbols under the Expression box."""
    del app
    lab = find_by_text(d, "click a symbol to insert it")
    box = getattr(lab, "master", None) if _alive(lab) else None
    return box if _alive(box) else d


def formula_example(app):
    """Drop a symbol into the Expression box by pressing the very chip the
    step is pointing at, so the caret, the typeset picture and the preview
    all update exactly as they would under the reader's own finger."""
    d = find_dialog(app, FORMULA_EDITOR)
    if d is None:
        _say(app, "The formula editor is closed. Press Next to carry on.")
        return
    chips = _formula_chips(app, d)
    for name in ("S", "B", "A", "wl"):
        if _press(find_by_text(chips, name)):
            return
    _say(app, "The symbol chips are out of reach on this build. Type "
              "anything in the Expression box.")


# The same trick, one panel section wide: snapshot everything a section
# SAYS (labels, entries, spinboxes) when the step opens, and 'did the user
# do the thing' becomes 'has any of it changed'.  That works for a readout
# the tour cannot predict - a solved index, a detection report, a notch
# list - without the tour knowing any of the workbench's internals.
def _state_of(widget):
    """Everything a section SAYS, plus everything it is set to.

    Entries, spinboxes and labels alone were not enough: a section whose
    controls are checkboxes and dropdowns - the Axis section is exactly
    that - never changed under this reader, so its 'now you try it' gate
    could not be opened by the very actions its hint suggested (Flip X
    is a checkbox, the X unit is a dropdown) and every reader sat out
    the full PATIENCE (Nhan, round 4, step 18).  So combobox values,
    check/radio variables and slider positions are part of the answer.
    """
    out = []
    for w in _walk(widget):
        try:
            cls = w.winfo_class()
        except Exception:
            continue
        if cls in ("TEntry", "Entry", "TSpinbox", "Spinbox",
                   "TCombobox", "Combobox"):
            try:
                out.append(str(w.get()))
            except Exception:
                pass
            continue
        if cls in ("Scale", "TScale"):
            try:
                out.append("%.4f" % float(w.get()))
            except Exception:
                pass
            continue
        if cls in ("Checkbutton", "TCheckbutton",
                   "Radiobutton", "TRadiobutton"):
            try:
                v = str(w.cget("variable"))
                if v:
                    out.append("%s=%s" % (v, w.getvar(v)))
            except Exception:
                pass
            # and fall through: a re-lettered check is state too
        try:
            t = w.cget("text")
        except Exception:
            continue
        if t:
            out.append(str(t))
    return tuple(out)


def arm_section(key):
    def _arm(app):
        _ARMED[key] = _state_of(section_body(app, key))
    return _arm


def section_changed(key):
    def _changed(app):
        body = section_body(app, key)
        if body is None:
            return True
        return _state_of(body) != _ARMED.get(key)
    return _changed


# ---------------------------------------------------------------------------
# 4. The steps
# ---------------------------------------------------------------------------
class Step(object):
    """One stop on the tour.

    chapter  the named part of the tour this step belongs to.  Steps of one
             chapter are contiguous; 'Skip this part' jumps past them.
    target   callable(app) -> widget, list of widgets, or None.  None means
             "no spotlight": the whole window dims and the card centers.
    pre      callable(app) run before the step is shown (select a tab,
             unfold a section, arm a snapshot) so the target is reachable.
    action   (label, callable(app)) for a button that does the step for you.
    wait     callable(app) -> bool.  While it is False, Next waits and the
             card says what it is waiting for.
    avail    callable(app) -> bool, checked ONCE when the tour starts: a
             step whose control this build does not have is dropped, so the
             step count the card shows is honest.
    dialog   the titles of the dialog this step lives inside.  When that
             dialog closes the tour walks on to the next step outside it.
    """

    def __init__(self, key, chapter, title, body, target=None, pre=None,
                 action=None, wait=None, wait_hint="", avail=None,
                 dialog=None):
        self.key = key
        self.chapter = chapter
        self.title = title
        self.body = body
        self.target = target
        self.pre = pre
        self.action = action
        self.wait = wait
        self.wait_hint = wait_hint
        self.avail = avail
        self.dialog = dialog


def _plot_canvas(app):
    c = getattr(app, "canvas", None)
    try:
        return c.get_tk_widget()
    except Exception:
        return None


def _decompression_span(app):
    rec = open_section(app, "Plot", "2D plot options")
    if rec is None:
        return None
    lab = find_by_text(rec["body"], "Decompression traces")
    return span_from(lab) if lab is not None else rec["cont"]


def _folder_cards(app):
    cards = [card_of(getattr(app, "_in_entry", None)),
             card_of(getattr(app, "_out_entry", None))]
    cards = [c for c in cards if _alive(c)]
    return cards or None


def _log_block(app):
    out = []
    rb = getattr(app, "_rescan_btn", None)
    if _alive(rb):
        out.append(rb.master)
    pc = getattr(app, "_progress_card", None)
    if _alive(pc):
        out.append(pc)
    return out or None


def _guide_card(app):
    return card_of(getattr(app, "ref", None))


def _find_block(app):
    """The 'Find a setting' row plus the Collapse all / Reset all bar."""
    out = []
    cb = getattr(app, "_collapse_btn", None)
    if _alive(cb):
        out.append(cb.master)
        # the Find row is the sibling packed just above the collapse bar
        try:
            sibs = cb.master.master.winfo_children()
            i = sibs.index(cb.master)
            if i > 0 and _alive(sibs[i - 1]):
                out.insert(0, sibs[i - 1])
        except Exception:
            pass
    return out or None


def _top_bar(app):
    """What stayed on the bar: Theme, the Settings gear and NUKE.

    R14 moved the app font, the text size and the helper switch into the
    gear's panel, so the bar step points at the controls still on the bar.
    """
    out = []
    w = getattr(app, "_theme_combo", None)
    if _alive(w) and _alive(getattr(w, "master", None)):
        out.append(w.master)
    for name in ("_settings_gear_btn", "nuke_btn"):
        w = getattr(app, name, None)
        if _alive(w):
            out.append(w)
    return out or None


def _settings_gear(app):
    """The gear on the top bar: the door to the Settings panel."""
    return getattr(app, "_settings_gear_btn", None)


def _settings_rows(app, win):
    """The panel's four rows, then its two buttons, top to bottom."""
    rows = _rows_named(win, ["Font", "Text size", "Helper tips",
                            "Performance mode"])
    btns = find_all_text(win, ["Tutorial", "About"]) or []
    return (rows + [b for b in btns if b not in rows]) or None


def _session_strip(app):
    out = [getattr(app, "_tabbar", None), getattr(app, "_view_switch", None)]
    out = [w for w in out if _alive(w)]
    return out or None


def _builtin_rows(app):
    body = section_body(app, "Formulas")
    if not _alive(body):
        return None
    rows = find_all_text(body, ["Absorption coefficient (cm^-1)",
                                "A/t (um^-1)"])
    if not rows:
        return body
    return [card_of(r) or r for r in rows]


def _has(name):
    return lambda a: _alive(getattr(a, name, None))


def _has_plot():
    """app.canvas is a FigureCanvasTkAgg, not a widget - ask it for the
    Tk one before deciding the plot exists."""
    return lambda a: _alive(_plot_canvas(a))


def _has_section(key):
    return lambda a: section_rec(a, key) is not None


def _stl_key(a):
    """The Export tab's printable-solid section, under either of its
    names: '3D Printing' since the R2 rename, '3D shape' before it."""
    if section_rec(a, "3D Printing") is not None:
        return "3D Printing"
    return "3D shape"


def _fringe_active(app):
    return bool(getattr(getattr(app, "_fringe", None), "_active", False))


def _fringe_canvas(app):
    return getattr(build_fringe(app), "_tkcanvas", None)


def _ensure_fringe(app):
    """Put the center on the workbench for the steps that are about it.

    The chapter opens by ASKING you to click the switch; every step after
    that one needs the view to actually be there, including for a reader
    who pressed Next instead. Idempotent, and guarded: a build without the
    workbench simply skips those steps.
    """
    fr = getattr(app, "_fringe", None)
    if fr is None:
        return
    try:
        if not getattr(fr, "_active", False):
            fr.activate()
            # a widget mapped this instant has no geometry until Tk has
            # run its layout: without this the first workbench step finds
            # a 1x1 canvas and skips itself
            app.root.update_idletasks()
    except Exception:
        pass
    select_tab(app, "Fringe")


def _fringe_guide_toggle(app):
    fr = getattr(app, "_fringe", None)
    lab = (getattr(fr, "_switch_lbls", {}) or {}).get("guide")
    if _alive(lab):
        return lab
    return getattr(app, "_view_switch", None)


def _fringe_toolbar(app):
    """The matplotlib toolbar under the four panels.

    R15-D gave the Fringe tab the strip the pop-out always had.  Built
    with the workbench, so this answers COLD like every other workbench
    resolver: build_fringe first, then the strip, then the toolbar
    itself for a build that packed it somewhere else.
    """
    fr = build_fringe(app)
    for name in ("_tb_bar", "toolbar"):
        w = getattr(fr, name, None)
        if _alive(w):
            return w
    return None


def _has_df():
    """The Defringe row exists once the workbench has been built, so the
    availability check builds it exactly the way _has_section does."""
    def _ok(app):
        build_fringe(app)
        return _alive(getattr(getattr(app, "_fringe", None), "_df_cb", None))
    return _ok


def _defringe_row(app):
    """The 'Defringe (df)' switch at the head of the Fringe column.

    The workbench is built here, the way section_rec builds it for every
    other workbench target: a resolver has to answer COLD, without the
    step's own `pre` having run first. The tour's skip logic calls it
    cold (_goto asks for a rectangle before it shows a step) and so does
    the test that walks every target.
    """
    build_fringe(app)
    fr = getattr(app, "_fringe", None)
    for name in ("_df_row", "_df_cb"):
        w = getattr(fr, name, None)
        if _alive(w):
            return w
    return None


def _toggle_defringe(app):
    """Press the Defringe box: the same click the step asks for."""
    fr = getattr(app, "_fringe", None)
    if not _press(getattr(fr, "_df_cb", None)):
        _say(app, "The Defringe box is out of reach on this build. Press "
                  "Next to carry on.")


def _df_state(app):
    """Is defringe on?  None when the variable cannot be read."""
    try:
        return bool(app.show_notch.get())
    except Exception:
        return None


def arm_defringe(app):
    _ARMED["df"] = _df_state(app)


def defringe_changed(app):
    """Fail-open: a build that cannot be read takes the reader's word."""
    now = _df_state(app)
    if now is None:
        return True
    return now != _ARMED.get("df")


def _fringe_call(name, *args):
    """Press one of the workbench's own buttons for a reader who would
    rather watch than aim. Guarded: a build without the method just
    logs, it never breaks the step."""
    def _go(app):
        fr = getattr(app, "_fringe", None)
        fn = getattr(fr, name, None)
        if callable(fn):
            fn(*args)
    return _go


# The R7 workbench rebuild renamed and regrouped every sidebar card, so
# each lookup below names the card and the caption the reader can now
# actually see.  Where the panel publishes the widget itself (_fit_btns,
# _plot_btn, _results_btn, _sol_lbl) we take it from there: a caption
# that grows a tick mark - "Results plot" -> "Results plot ok" - would
# make a by-text lookup lie about a button that is still right there.
STACK_ROWS = ("n sample", "d1 lower medium (um)", "t sample (um)",
              "d2 upper medium (um)")


def _rows_named(body, texts):
    """The row frames holding each of `texts`, in order, dropping any
    caption this build does not carry."""
    rows = []
    for t in texts:
        lab = find_by_text(body, t)
        if _alive(lab) and _alive(getattr(lab, "master", None)):
            rows.append(lab.master)
    return rows


def _all_rows_named(body, texts):
    """Every row whose caption is one of `texts` - the per-channel rows
    of FFT removal, where each caption appears once per channel."""
    want = set(_k(t) for t in texts)
    rows, seen = [], set()
    for w in _walk(body):
        try:
            if _k(w.cget("text")) not in want:
                continue
        except Exception:
            continue
        m = getattr(w, "master", None)
        if _alive(m) and str(m) not in seen:
            seen.add(str(m))
            rows.append(m)
    return rows


def _row_or_widget(body, texts):
    """The row frame holding each caption, or the control itself when the
    caption IS the control.

    A checkbutton wears its own label and is packed straight into the
    card, so its master is the whole card: spotlighting that would name
    every control in the section at once.
    """
    out = []
    for t in texts:
        w = find_by_text(body, t)
        if not _alive(w):
            continue
        try:
            cls = w.winfo_class()
        except Exception:
            cls = ""
        if cls in ("TCheckbutton", "Checkbutton", "TRadiobutton",
                   "Radiobutton", "TButton", "Button"):
            out.append(w)
            continue
        m = getattr(w, "master", None)
        out.append(m if _alive(m) else w)
    return out


def _stack_rows(app):
    """The index and thickness rows of the Stack card, solved column and
    all - what a fit writes into and what the stems are drawn from."""
    body = section_body(app, "Stack")
    if not _alive(body):
        return None
    return _rows_named(body, STACK_ROWS) or body


def _calc_n_row(app):
    """The pressure override on the Stack card: the P box, 'calc n' and
    the ambient constant (R15-D, his 9589-9619)."""
    body = section_body(app, "Stack")
    if not _alive(body):
        return None
    rows = _rows_named(body, ["P"])
    btn = find_by_text(body, "calc n")
    if _alive(btn) and _alive(getattr(btn, "master", None)):
        rows.append(btn.master)
    return rows or body


def _nudge_spin(box, step=1.0):
    """Bump a spinbox one step, the way its own arrow does.

    The R7 cards are built from ttk.Spinbox, which has no `invoke` - the
    classic tk.Spinbox method the old nudge relied on - so the value is
    typed and committed with Return instead, which is exactly the other
    way a reader changes one of these boxes.
    """
    if not _alive(box):
        return False
    try:
        box.invoke("buttonup")
        return True
    except Exception:
        pass
    try:
        step = float(box.cget("increment")) or step
    except Exception:
        pass
    try:
        v = float(str(box.get()).strip() or 0.0)
    except Exception:
        return False
    try:
        box.delete(0, "end")
        box.insert(0, "%g" % (v + step))
        box.event_generate("<Return>")
        return True
    except Exception:
        return False


def _spin_in(row):
    """The first spinbox or entry inside a row, whatever else it packs.

    The workbench rows pack a unit label between the caption and the box
    (R14 spacing pass), so 'the widget packed after the caption' is that
    label and nudging it does nothing.  The row is asked for its box.
    """
    if not _alive(row):
        return None
    for w in _walk(row):
        try:
            if w.winfo_class() in ("TSpinbox", "Spinbox", "TEntry", "Entry"):
                return w
        except Exception:
            pass
    return None


def _nudge_row_of(lab):
    """Bump the box that belongs to `lab`, by position then by row."""
    if _nudge_spin(next_sibling(lab)):
        return True
    return _nudge_spin(_spin_in(getattr(lab, "master", None)))


def _nudge_sample_t(app):
    """Bump the sample thickness one step, so the prediction stems move."""
    body = section_body(app, "Stack")
    lab = find_by_text(body, "t sample (um)") if _alive(body) else None
    if not _nudge_row_of(lab):
        _say(app, "The thickness box is out of reach on this build. Press "
                  "Next to carry on.")


def _fit_row(app):
    """The 'Fit peaks:' caption and its two glyph buttons."""
    body = section_body(app, "Stack")
    if not _alive(body):
        return None
    lab = find_by_text(body, "Fit peaks:")
    fr = getattr(app, "_fringe", None)
    out = [lab] if _alive(lab) else []
    for btn, _mode in (getattr(fr, "_fit_btns", None) or []):
        if _alive(btn):
            out.append(btn)
    return out or body


def _lowpass_rows(app):
    """Both channels' low-pass rows on the FFT removal card - the main
    cleaning tool, one cutoff per channel."""
    body = section_body(app, "FFT removal")
    if not _alive(body):
        return None
    rows = _all_rows_named(body, ["Low-pass cutoff", "Clear notches"])
    heads = _rows_named(body, ["Background", "Sample"])
    return (rows + [h for h in heads if h not in rows]) or body


def _nudge_lowpass(app):
    """Move the Sample channel's cutoff one step, so the dashed line and
    the cleaned curve both answer."""
    body = section_body(app, "FFT removal")
    labs = []
    if _alive(body):
        for w in _walk(body):
            try:
                if _k(w.cget("text")) == "Low-pass cutoff":
                    labs.append(w)
            except Exception:
                pass
    # the card is built Background first, Sample second: the last row is
    # the Sample one, which is the curve the chapter is about
    for lab in reversed(labs):
        if _nudge_row_of(lab):
            return
    _say(app, "The cutoff box is out of reach on this build. Press Next to "
              "carry on.")


def _lp_edge_rows(app):
    """Both channels' 'Edge' rows on the FFT removal card: the shape the
    cutoff rolls off with, and the width it rolls off over (R15-D)."""
    body = section_body(app, "FFT removal")
    if not _alive(body):
        return None
    return _all_rows_named(body, ["Edge"]) or body


def _notch_list_btn(app):
    """The 'Notch list' button on the FFT removal card - the pop-out the
    centres now live in."""
    body = section_body(app, "FFT removal")
    if not _alive(body):
        return None
    return find_by_text(body, "Notch list") or body


def _fund_rows(app, win):
    """The notch list's rows: the tick, the micron key, the half-width,
    the Fundamental radio and the remove cross.

    Taken from the panel, because the rows are rebuilt whenever a centre
    moves and a by-text lookup would hold a destroyed widget.
    """
    rows = getattr(getattr(app, "_fringe", None), "_notch_rows", None)
    if _alive(rows):
        return rows
    return find_by_text(win, "Fundamental")


def _notchable_peak(app):
    """(channel, n*t) for the notch action to aim at, or None.

    The panel hands its peaks back amplitude-first, so we take the tallest
    one that is NOT already notched and the button does what it says on
    it.  Sample panel before Background: that is the curve the chapter is
    about.  When every peak is already spoken for we aim at the tallest
    anyway and the click takes it back off, which is the other half of the
    very gesture this step teaches.
    """
    fr = getattr(app, "_fringe", None)
    cand = getattr(fr, "_candidates", None)
    if not callable(cand):
        return None
    active = getattr(fr, "_active_centers", None)
    tallest = None
    for chan in ("Sample", "Background"):
        try:
            xs = [float(x) for x in cand(chan)]
        except Exception:
            continue
        if not xs:
            continue
        if tallest is None:
            tallest = (chan, xs[0])
        try:
            listed = set(active(chan, include_unticked=True)) \
                if callable(active) else set()
        except Exception:
            listed = set()
        for x in xs:
            if round(x, 2) not in listed:
                return (chan, x)
    return tallest


def _notch_one(app):
    """Notch a peak - the same call a left-click on the plot makes, so the
    notch list fills in exactly as it would have.

    Nothing to notch is an answer too, and the reader gets told it rather
    than being left to wait the step out.
    """
    fn = getattr(getattr(app, "_fringe", None), "_toggle_notch_at", None)
    hit = _notchable_peak(app)
    if hit is None or not callable(fn):
        _say(app, "This trace waits for a run with fringes in it. Press "
                  "Next to carry on.")
        return
    try:
        fn(hit[0], hit[1])
    except Exception as e:
        _say(app, "The plot would not take a notch (%r). Press Next to carry "
                  "on." % (e,))


def _notch_state(app):
    """Which centres are notched, per channel, or None when the panel
    cannot be read.  The Notches CARD is gone in R7 - the centres live
    in a pop-out - so the gate reads the state itself rather than
    snapshotting a section that no longer exists."""
    fn = getattr(getattr(app, "_fringe", None), "_active_centers", None)
    if not callable(fn):
        return None
    out = []
    for chan in ("Background", "Sample"):
        try:
            out.append((chan, tuple(sorted(fn(chan,
                                              include_unticked=True)))))
        except Exception:
            return None
    return tuple(out)


def arm_notches(app):
    _ARMED["fr_notches"] = _notch_state(app)


def notch_changed(app):
    """A centre went on or came off.  Fail-open exactly like record_done:
    a build that cannot be read takes the reader's word for it."""
    now = _notch_state(app)
    if now is None:
        return True
    was = _ARMED.get("fr_notches", _MISSING)
    if was is _MISSING:
        return True
    return now != was


def _detection_card(app):
    """The Detection card: the four search gates and the live report.

    R7 had put them in a pop-out behind Panels.  R14 brought them back
    into a card of their own, in the Fringe column directly above FFT
    removal, and the Panels row's 'Detection' button scrolls to it.
    """
    return section_body(app, "Detection")


def _detection_shown(app):
    """Is the Detection card open?  Fail-open on a build without it."""
    rec = section_rec(app, "Detection")
    if rec is None:
        return True
    return not bool(rec.get("collapsed"))


def _solved_block(app):
    """The solved column: the four cells a fit writes, in their rows."""
    fr = getattr(app, "_fringe", None)
    out = []
    for lab in (getattr(fr, "_sol_lbl", None) or {}).values():
        m = getattr(lab, "master", None)
        if _alive(m) and m not in out:
            out.append(m)
    if out:
        return out
    body = section_body(app, "Stack")
    if not _alive(body):
        return None
    return _rows_named(body, STACK_ROWS) or body


def _intensity_row(app):
    """The 'Compute fits' row of the Refractive Index from Intensity
    card - the amplitude fitters, and the one card the chapter had never
    taught."""
    body = section_body(app, "Refractive Index from Intensity")
    if not _alive(body):
        return None
    btn = find_by_text(body, "Compute fits")
    if _alive(btn) and _alive(getattr(btn, "master", None)):
        return btn.master
    return body


def _intensity_done(app):
    """'Compute fits' ends by switching the right panels to the tiered
    view, whether or not a fit landed, so the tiered flag is what the
    gate reads.  Fail-open when the panel cannot be read."""
    fr = getattr(app, "_fringe", None)
    v = getattr(fr, "tiers_v", None)
    if v is None:
        return True
    try:
        return bool(v.get())
    except Exception:
        return True


def _notch_writers(app):
    body = section_body(app, "FFT removal")
    if not _alive(body):
        return None
    return find_all_text(body, ["Write notches file for batch",
                                "Delete notches file"]) or body


def _point_block(app):
    """'Plot point' on the Stack card plus the Pressure point card - the
    two halves of 'file this one, then walk to the next'."""
    fr = getattr(app, "_fringe", None)
    out = []
    btn = getattr(fr, "_plot_btn", None)
    if not _alive(btn):
        body = section_body(app, "Stack")
        btn = find_by_text(body, "Plot point") if _alive(body) else None
    if _alive(btn):
        out.append(btn)
    press = section_body(app, "Pressure point")
    if _alive(press):
        out.append(press)
    return out or None


def _pressure_picker(app):
    """The pressure dropdown and its two arrows.

    R15-C decorates each label with a saved / differs marker, so this is
    the control the session step is about.  Cold-safe through
    section_body, which builds the workbench.
    """
    cb = getattr(getattr(app, "_fringe", None), "_trace_cb", None)
    if not _alive(cb):
        build_fringe(app)
        cb = getattr(getattr(app, "_fringe", None), "_trace_cb", None)
    if _alive(cb) and _alive(getattr(cb, "master", None)):
        return cb.master
    return section_body(app, "Pressure point")


_MISSING = object()


def _series_state(app):
    """A fingerprint of the recorded points, or None when there are none
    to read.  Every value in there is a plain string, number or bool, so
    this stays cheap however long the series gets."""
    s = getattr(getattr(app, "_fringe", None), "_series", None)
    if s is None:
        return None
    out = []
    for q in s:
        try:
            out.append(tuple(sorted((str(k), repr(v))
                                    for k, v in q.items())))
        except Exception:
            out.append(repr(q))
    return (len(out), tuple(out))


def arm_record(app):
    _ARMED["fr_series"] = _series_state(app)


def record_done(app):
    """A point actually went into the series.

    This used to accept ANY change to the workbench's status line, and a
    REFUSAL is a change: press Record with nothing solved, the bench says
    'solve first', and the step went green on a point that was never
    recorded (the usability probe).  So the gate now reads the series
    itself.  Fail-open is unchanged: a build with no series to read, or a
    read that goes wrong, takes the reader's word for it.
    """
    now = _series_state(app)
    if now is None:
        return True                    # nothing to read; do not block
    was = _ARMED.get("fr_series", _MISSING)
    if was is _MISSING:
        return True                    # never armed; do not block
    return now != was


def _results_btn(app):
    """'Results plot' on the Stack card.  Taken from the panel, because
    its caption grows a tick once this point is on the series and a
    by-text lookup would then miss a button that never moved."""
    btn = getattr(getattr(app, "_fringe", None), "_results_btn", None)
    if _alive(btn):
        return btn
    body = section_body(app, "Stack")
    if not _alive(body):
        return None
    return find_by_text(body, "Results plot") or body


def _click_by_text(key, text):
    """Press a control by the words on it, inside one panel section.

    The 'do it for me' fallbacks: they aim at the label a reader can see
    rather than at an attribute name, so a renamed variable cannot make
    the button lie about what it will press.
    """
    def _go(app):
        w = find_by_text(section_body(app, key), text)
        if w is None:
            return
        try:
            w.invoke()
        except Exception:
            pass
    return _go


# ---- the plot toolbar, and the 2D view ------------------------------------
def _tb_btn(app, key):
    b = (getattr(app, "_tb_btns", {}) or {}).get(key)
    return b if _alive(b) else None


def _toolbar_strip(app):
    b = _tb_btn(app, "reset")
    return b.master if b is not None and _alive(b.master) else None


def _view_state(app):
    try:
        ax = app.ax
        return (tuple(round(float(v), 5) for v in ax.get_xlim())
                + tuple(round(float(v), 5) for v in ax.get_ylim()))
    except Exception:
        return None


def arm_view(app):
    _ARMED["view"] = _view_state(app)


def view_moved(app):
    now = _view_state(app)
    if now is None:
        return True                    # no axes to read; do not block
    return now != _ARMED.get("view")


def _pan_nudge(app):
    """Slide the view a step sideways - what the pan hand does."""
    try:
        ax = app.ax
        x0, x1 = ax.get_xlim()
        d = (x1 - x0) * 0.15
        ax.set_xlim(x0 + d, x1 + d)
        app.canvas.draw_idle()
    except Exception:
        pass


def _zoom_nudge(app):
    """Dive into the middle third - what a magnifier box does."""
    try:
        ax = app.ax
        x0, x1 = ax.get_xlim()
        c, h = (x0 + x1) / 2.0, (x1 - x0) * 0.3
        ax.set_xlim(c - h, c + h)
        app.canvas.draw_idle()
    except Exception:
        pass


def _press_reset(app):
    b = _tb_btn(app, "reset")
    if b is not None:
        try:
            b.invoke()
        except Exception:
            pass


# ---- the 3D scene ---------------------------------------------------------
_WF_3D = ("3D ridge", "3D shape")


def _cam_state(app):
    out = []
    for name in ("wf3d_elev", "wf3d_azim", "wf3d_zoom"):
        try:
            out.append(round(float(getattr(app, name).get()), 3))
        except Exception:
            out.append(None)
    # a mouse drag rotates the axes directly, so read the camera itself
    # as well as the sliders that mirror it
    try:
        ax = app.ax
        out.append(round(float(getattr(ax, "azim", 0.0)), 2))
        out.append(round(float(getattr(ax, "elev", 0.0)), 2))
    except Exception:
        pass
    return tuple(out)


def arm_camera(app):
    _ARMED["camera"] = _cam_state(app)


def camera_moved(app):
    return _cam_state(app) != _ARMED.get("camera")


def _in_3d(app):
    try:
        return app.wf_mode.get() in _WF_3D
    except Exception:
        return False


def _ensure_3d(app):
    """The 3D steps need a 3D scene under them, whoever pressed Next."""
    try:
        if not _in_3d(app):
            app.wf_mode.set("3D ridge")
            app._redraw()
    except Exception:
        pass


def _go_ridge(app):
    try:
        app.wf_mode.set("3D ridge")
        app._redraw()
    except Exception:
        pass


def _go_surface(app):
    try:
        app.wf_mode.set("3D shape")
        app._redraw()
    except Exception:
        pass


def _orbit_for_me(app):
    _ensure_3d(app)
    try:
        app._orbit3d(4, 1)
    except Exception:
        pass


def _stretch_state(app):
    out = []
    for name in ("wf3d_sx", "wf3d_sy", "wf3d_sz"):
        try:
            out.append(round(float(getattr(app, name).get()), 3))
        except Exception:
            out.append(None)
    return tuple(out)


def arm_stretch(app):
    _ARMED["stretch"] = _stretch_state(app)


def stretch_moved(app):
    return _stretch_state(app) != _ARMED.get("stretch")


def _stretch_nudge(app):
    _ensure_3d(app)
    try:
        app.wf3d_sx.set(round(float(app.wf3d_sx.get()) + 0.3, 2))
        app._redraw()
    except Exception:
        pass


def _stretch_rows(app):
    body = section_body(app, "3D plot options")
    if not _alive(body):
        return None
    rows = []
    for t in ("Stretch X", "Stretch Y", "Stretch Z"):
        lab = find_by_text(body, t)
        if _alive(lab) and _alive(getattr(lab, "master", None)):
            rows.append(lab.master)
    return rows or body


def _surface_rows(app):
    body = section_body(app, "3D plot options")
    if not _alive(body):
        return None
    # v1.4.9 R13 folded 'Surface detail' into the Graphics dial, and R9b
    # added 'Mark measured traces' beside it.  Row frames, not the bare
    # labels: a column of labels spotlights a narrow strip down the left
    # of the controls it is naming.
    return _row_or_widget(body, ["Interpolation", "Mark measured traces",
                                 "Fill underside"]) or body


# The six controls R14 gave the sheet's look: the Graphics dial, the two
# new speed switches, the mesh, and relief with its strength.
WF3D_LOOK = ("Graphics", "Smooth polygon edges (antialias)",
             "Draft quality while rotating", "Relief shading",
             "Relief strength", "Show mesh")


def _surface_look_rows(app):
    body = section_body(app, "3D plot options")
    if not _alive(body):
        return None
    return _row_or_widget(body, WF3D_LOOK) or body


def _toggle_mesh(app):
    """Tick 'Show mesh': the look switch whose effect reads at once."""
    body = section_body(app, "3D plot options")
    cb = find_by_text(body, "Show mesh") if _alive(body) else None
    if not _press(cb):
        _say(app, "The 'Show mesh' box is out of reach on this build. Press "
                  "Next to carry on.")


def _settle_2d(app):
    """Bring the plot back down for the chapters after the 3D ones: the
    axes and style steps read clearest on a 2D view, and '2D stacked'
    keeps the Stacked & 3D lesson on screen."""
    try:
        if _in_3d(app):
            app.wf_mode.set("2D stacked")
            app._redraw()
    except Exception:
        pass


def _cycle_colormap(app):
    try:
        app._cycle_cmap(1)
    except Exception:
        pass


def _flip_x(app):
    try:
        app.flipx.set(not bool(app.flipx.get()))
        app._redraw()
    except Exception:
        pass


def _seed_find(app):
    try:
        app.section_search.set("legend")
    except Exception:
        pass


def _find_used(app):
    try:
        return bool(str(app.section_search.get()).strip())
    except Exception:
        return True


def _clear_find(app):
    """Put the panel back the way it was: the previous step asked the
    reader to type in the Find box, which folds most of the panel away."""
    try:
        if str(app.section_search.get()).strip():
            app.section_search.set("")
    except Exception:
        pass


def _try_dark(app):
    try:
        app.theme_mode.set("dark" if app.theme_mode.get() != "dark"
                           else "light")
    except Exception:
        pass


def _arm_theme(app):
    _ARMED["theme"] = getattr(app, "theme_mode", None) and app.theme_mode.get()


def _theme_changed(app):
    try:
        return app.theme_mode.get() != _ARMED.get("theme")
    except Exception:
        return True


def _leave_fringe(app):
    fr = getattr(app, "_fringe", None)
    if fr is not None and getattr(fr, "_active", False):
        try:
            fr.deactivate()
        except Exception:
            pass


def _back_to_overlay(app):
    try:
        if app.mode.get() != "overlay":
            app.mode.set("overlay")
            app._redraw()
    except Exception:
        pass


C_START = "Getting started"
C_INPUT = "Data input"
C_PLOT = "Reading the plot"
C_ARRANGE = "Arranging traces"
C_AXES = "The axes"
C_STYLE = "Style"
C_NUMBERS = "The numbers"
C_FRINGE = "Fringe workbench"
C_EXPORT = "Export"
C_SETTLE = "Settling in"

# The two steps that teach the top bar's Settings panel.  Every other step
# shuts it on arrival, so the bar a later step points at is the plain one.
SETTINGS_STEPS = frozenset(("settings", "settings_rows"))


TOUR_STEPS = [
    # -- Getting started ---------------------------------------------------
    # v1.4.9 R12: every string below follows the STE register. One fact per
    # sentence, sentences under 20 words, active voice, present tense, one
    # agent ("the tool"). Control names and formulas are verbatim.
    Step(
        "welcome", C_START,
        "Welcome",
        "The data sits on the left, the plot in the middle, the "
        "controls in the tabs on the right.\n"
        "\n"
        "The tour changes no file on disk, so click freely. Esc leaves. "
        "The arrow keys step back and forward, and 'Jump to' moves "
        "between chapters."),

    Step(
        "workspace", C_START,
        "Session tabs",
        "The tabs above the plot are separate sessions. Each session "
        "holds its own data, folders and undo history. '+' adds one, "
        "and Ctrl+Tab cycles them.\n"
        "\n"
        "The Plot / Fringe switch sits at the far right and changes the "
        "middle of the window.",
        target=_session_strip,
        avail=_has("_tabbar")),

    # -- Data input --------------------------------------------------------
    Step(
        "folders", C_INPUT,
        "Input and output folders",
        "Input folder points at the raw segment files. Browse, paste a "
        "path, or drag a folder in. Each Run makes its own subfolder "
        "under Output, and earlier runs stay as they are.\n"
        "\n"
        "The demo series loads with one click.",
        target=_folder_cards,
        action=("Load the demo", load_demo),
        wait=lambda a: bool(a.in_var.get().strip()
                            and a.out_var.get().strip()),
        wait_hint="Fill in an input folder and an output folder.",
        avail=_has("_in_entry")),

    Step(
        "names", C_INPUT,
        "Name format",
        "This button names the profile that reads the filenames. The "
        "built-in profile reads classic 22-IR-1 names.\n"
        "\n"
        "vis_Y04_Arch29_26p0_s.003 is DAC Y04, sample Arch29, 26.0 GPa, "
        "sample channel, grating segment 3.\n"
        "\n"
        "Click the button.",
        target=lambda a: getattr(a, "profile_btn", None),
        action=("Open it for me", lambda a: a._open_name_format()),
        wait=dialog_open(NAME_FORMAT),
        wait_hint="Click the Name format button.",
        avail=_has("profile_btn")),

    Step(
        "names_grammar", C_INPUT,
        "The filename grammar",
        "Prefix is what every file starts with. Separator sits between "
        "the fields. Segment sep and Numbering describe the "
        "grating-segment suffix.\n"
        "\n"
        "'No number =' indexes or rejects a file that omits the suffix. "
        "The keyword boxes name the background, sample, dark and C / D "
        "tags.",
        target=in_dialog(
            NAME_FORMAT,
            lambda a, d: common_block(d, ["Prefix", "Numbering"]),
            lambda a: getattr(a, "profile_btn", None)),
        dialog=NAME_FORMAT,
        avail=_has("profile_btn")),

    Step(
        "names_teach", C_INPUT,
        "Teaching by example",
        "One filename breaks into chips, and each chip takes a role: "
        "DAC, sample, value, channel or ignore.\n"
        "\n"
        "Change a chip and read the Preview. Green is parsed; red is "
        "skipped, with the reason beside it.",
        target=in_dialog(
            NAME_FORMAT,
            lambda a, d: card_of(find_by_text(d, "Teach by example")),
            lambda a: getattr(a, "profile_btn", None)),
        dialog=NAME_FORMAT,
        avail=_has("profile_btn")),

    Step(
        "names_done", C_INPUT,
        "Guess, commit, close",
        "'Guess format' reads the folder and proposes a profile, which "
        "is usually the fastest start. 'Use this profile' commits it, "
        "and 'Save as...' keeps it for next time.\n"
        "\n"
        "No change takes effect until it is committed. Close the window "
        "and the tour carries on.",
        target=in_dialog(
            NAME_FORMAT,
            lambda a, d: find_all_text(d, ["Guess format", "Use this profile",
                                           "Close"]),
            lambda a: getattr(a, "profile_btn", None)),
        dialog=NAME_FORMAT,
        action=("Close it for me", close_dialog(NAME_FORMAT, ("Close",))),
        wait=dialog_shut(NAME_FORMAT),
        wait_hint="Close the Name format window.",
        avail=_has("profile_btn")),

    Step(
        "run", C_INPUT,
        "Run",
        "Run joins each measurement's grating segments and computes "
        "absorbance:\n"
        "\n"
        "A = -log10[(Sample - Dark) / (Background - Dark)]\n"
        "\n"
        "It writes one CSV per measurement and a provenance sidecar. "
        "The ticks in Export > Data files pick the columns that CSV "
        "carries.\n"
        "\n"
        "Press Run. The tour waits here.",
        target=lambda a: getattr(a, "run_btn", None),
        action=("Run it for me", run_demo),
        wait=lambda a: bool(getattr(a, "results", None)),
        wait_hint="Waiting for the run to finish.",
        avail=_has("run_btn")),

    Step(
        "export_btn", C_INPUT,
        "Export…",
        "The button beside Run opens the Export dialog: the same "
        "columns as a Run, written into any folder you pick. Ctrl+E "
        "opens it too, and so does 'Export data…' in Export tab > "
        "Data files.\n"
        "\n"
        "The dialog also carries a wavelength crop. The crop applies "
        "to that export alone, never to a Run.",
        target=lambda a: getattr(a, "_export_btn", None),
        avail=_has("_export_btn")),

    Step(
        "log", C_INPUT,
        "The progress log",
        "Progress records every run, every rescan and every skipped "
        "file. 'Copy log' copies all of it, and 'Export settings' "
        "prints the plot configuration for a methods section.\n"
        "\n"
        "Rescan, or F5, re-runs the folder when new files appear. 'Load "
        "previous run' reopens a finished output folder.",
        target=_log_block,
        avail=_has("_progress_card")),

    # -- Reading the plot --------------------------------------------------
    Step(
        "canvas", C_PLOT,
        "The plot",
        "Every trace draws at once. Click a curve to select it, "
        "double-click to solo it, and click a legend entry to hide that "
        "trace.\n"
        "\n"
        "Right-click a curve for the quick actions: inspect, solo, "
        "hide, toggle D, defringe compare and show in the data table.",
        target=_plot_canvas,
        avail=_has_plot()),

    Step(
        "nav_pan", C_PLOT,
        "Panning",
        "The strip under the plot is the navigation kit: Reset, the pan "
        "hand, the zoom box and save.\n"
        "\n"
        "Click the hand, then drag to move the view. Click the hand "
        "again to release it. The Limits boxes in the Axes tab follow "
        "along.",
        pre=arm_view,
        target=lambda a: _tb_btn(a, "pan") or _toolbar_strip(a),
        action=("Pan it for me", _pan_nudge),
        wait=view_moved,
        wait_hint="Click the hand, then drag the plot a little.",
        avail=lambda a: _tb_btn(a, "pan") is not None),

    Step(
        "nav_zoom", C_PLOT,
        "Zooming",
        "The magnifier works by box: drag a box and the view fills with "
        "it. With both tools released, the wheel zooms about the "
        "cursor.\n"
        "\n"
        "Zoom in on any feature. The way back is the next step.",
        pre=arm_view,
        target=lambda a: _tb_btn(a, "zoom") or _toolbar_strip(a),
        action=("Zoom in for me", _zoom_nudge),
        wait=view_moved,
        wait_hint="Drag a box with the magnifier, or spin the wheel.",
        avail=lambda a: _tb_btn(a, "zoom") is not None),

    Step(
        "nav_reset", C_PLOT,
        "Reset",
        "Reset refits the 2D view and refits the 3D camera; the 0 key "
        "does the same. Only the view changes.\n"
        "\n"
        "The camera button beside it saves the figure (Ctrl+S). The "
        "Export chapter covers that.",
        target=lambda a: _tb_btn(a, "reset") or _toolbar_strip(a),
        action=("Reset it for me", _press_reset),
        avail=lambda a: _tb_btn(a, "reset") is not None),

    Step(
        "plotmode", C_PLOT,
        "Overlay, Inspect, Thickness",
        "Three views of the same data. Overlay draws everything on one "
        "pair of axes. Inspect shows one measurement's Sample, "
        "Background and Dark counts. Thickness plots the fringe n*t of "
        "every trace.\n"
        "\n"
        "Select 'Inspect one trace'.",
        pre=lambda a: open_section(a, "Plot", "Plot mode"),
        target=lambda a: section_body(a, "Plot mode"),
        action=("Show me Inspect", lambda a: (a.mode.set("inspect"),
                                              a._redraw())),
        wait=lambda a: a.mode.get() == "inspect",
        wait_hint="Pick 'Inspect one trace'.",
        avail=_has_section("Plot mode")),

    Step(
        "table", C_PLOT,
        "The data table",
        "The plot is back on Overlay. Ctrl+D, or this button, slides a "
        "spreadsheet out under the plot. It holds the numbers for the "
        "selected trace, smoothed and defringed columns included.\n"
        "\n"
        "'Copy all (TSV)' pastes into Excel; 'Open in Excel' writes a "
        "CSV and opens it.",
        pre=_back_to_overlay,
        target=lambda a: getattr(a, "_data_btn", None),
        action=("Open the table", lambda a: a._toggle_drawer(True)),
        wait=lambda a: bool(getattr(a, "_drawer_shown", False)),
        wait_hint="Press the Data table button, or Ctrl+D.",
        avail=_has("_data_btn")),

    Step(
        "quick", C_PLOT,
        "Quick Access",
        "The strip above the tabs pins frequently used controls: the "
        "colormap, the line width, the Stacked & 3D mode, both axes and "
        "the theme tint. Each one is the setting itself, in a second "
        "place.\n"
        "\n"
        "The gear in the corner picks what lives here, in two columns "
        "of controls and functions. Click the title to fold the strip "
        "away.",
        target=lambda a: getattr(a, "_qa_card", None),
        avail=_has("_qa_card")),

    # -- Arranging traces --------------------------------------------------
    Step(
        "waterfall", C_ARRANGE,
        "Stacked and 3D modes",
        "Overlay puts every trace on one baseline. '2D stacked' shifts "
        "each trace up by the Offset/step. '3D ridge' draws one ridge "
        "per trace, with the series value running into the page. Keys "
        "1, 2 and 3 do the same.\n"
        "\n"
        "'Auto separation (2D stacked)' sets the gap from the shown "
        "traces, and 'Auto' beside the step spreads the ridges evenly.",
        pre=lambda a: open_section(a, "Plot", "Stacked & 3D"),
        target=lambda a: section_body(a, "Stacked & 3D"),
        action=("Stack them for me", lambda a: a.wf_mode.set("2D stacked")),
        wait=lambda a: a.wf_mode.get() != "off",
        wait_hint="Pick '2D stacked' or '3D ridge'.",
        avail=_has_section("Stacked & 3D")),

    Step(
        "opt2d", C_ARRANGE,
        "The 2D controls",
        "Line style and Curve line width style the curves. Inset zoom "
        "magnifies an X range in a corner panel.\n"
        "\n"
        "'Defringe compare' draws the pre-defringe curve behind the "
        "selected one, so the cleaning is visible.",
        pre=lambda a: open_section(a, "Plot", "2D plot options"),
        target=lambda a: section_body(a, "2D plot options"),
        avail=_has_section("2D plot options")),

    Step(
        "decomp", C_ARRANGE,
        "Compression and decompression",
        "C is compression and D is decompression. The D branch takes "
        "its own line style, dash pattern, width, opacity and marker.\n"
        "\n"
        "Those settings carry into the overlay, the 2D stacked view, "
        "the 3D ridge and the legend. One demo point carries the _D "
        "tag.",
        pre=lambda a: open_section(a, "Plot", "2D plot options"),
        target=_decompression_span,
        avail=_has_section("2D plot options")),

    Step(
        "opt3d", C_ARRANGE,
        "The 3D scene",
        "Camera, box and panes sit here, with what the ridges are made "
        "of. '3D look' picks filled walls, outlines only, or surface; "
        "surface joins adjacent traces into one sheet, colored by "
        "series value.\n"
        "\n"
        "'Even rank spacing' keeps a crowded series readable, and '3D "
        "detail (points/ridge)' buys a smoother spin.",
        pre=lambda a: open_section(a, "Plot", "3D plot options"),
        target=lambda a: section_body(a, "3D plot options"),
        avail=_has_section("3D plot options")),

    Step(
        "go3d", C_ARRANGE,
        "3D ridge and 3D shape",
        "'3D ridge' (key 3) draws every trace as a ridge, with the "
        "series value running into the page. '3D shape' (key 4) joins "
        "those ridges into one surface.\n"
        "\n"
        "Everything already styled carries over.",
        pre=lambda a: open_section(a, "Plot", "Stacked & 3D"),
        target=lambda a: section_body(a, "Stacked & 3D"),
        action=("3D ridge for me", _go_ridge),
        wait=_in_3d,
        wait_hint="Pick '3D ridge' (key 3) or '3D shape' (key 4).",
        avail=_has_section("Stacked & 3D")),

    Step(
        "orbit3d", C_ARRANGE,
        "The 3D camera",
        "Drag the plot and the camera orbits: left and right move the "
        "azimuth, up and down move the elevation. The arrow keys do the "
        "same in three-degree steps.\n"
        "\n"
        "The +/- keys zoom. The sliders in 3D plot options read out the "
        "camera. Ctrl+R, or Reset, puts it back.",
        pre=lambda a: (_ensure_3d(a), arm_camera(a)),
        target=_plot_canvas,
        action=("Orbit for me", _orbit_for_me),
        wait=camera_moved,
        wait_hint="Drag the plot, or tap an arrow key.",
        avail=lambda a: (_alive(_plot_canvas(a))
                         and hasattr(a, "wf3d_azim"))),

    Step(
        "stretch3d", C_ARRANGE,
        "Stretch and spacing",
        "Stretch X, Y and Z fan the 3D box out along wavelength, series "
        "and absorbance. The data keeps its values; only the "
        "presentation changes.\n"
        "\n"
        "'Reset stretch' restores the proportions, and 'Even rank "
        "spacing' sorts an uneven series into ranks.",
        pre=lambda a: (_ensure_3d(a),
                       open_section(a, "Plot", "3D plot options"),
                       arm_stretch(a)),
        target=_stretch_rows,
        action=("Stretch X for me", _stretch_nudge),
        wait=stretch_moved,
        wait_hint="Slide one of the Stretch rows.",
        avail=lambda a: (section_rec(a, "3D plot options") is not None
                         and hasattr(a, "wf3d_sx"))),

    Step(
        "surface3d", C_ARRANGE,
        "The surface controls",
        "'3D shape' carries its own controls. Interpolation fills the "
        "gaps between measured traces, and Fill underside closes the "
        "bottom.\n"
        "\n"
        "'Mark measured traces' draws every measured trace on the "
        "surface, so real data stands apart from the fill. An exported "
        "solid always uses the full grid.",
        pre=lambda a: open_section(a, "Plot", "3D plot options"),
        target=_surface_rows,
        action=("Show me the surface", _go_surface),
        avail=_has_section("3D plot options")),

    Step(
        "surface3d_look", C_ARRANGE,
        "Sheet quality",
        "Graphics runs from potato to best, trading polygons for speed.\n"
        "\n"
        "'Smooth polygon edges (antialias)' softens each polygon "
        "outline. 'Draft quality while rotating' draws a coarser sheet "
        "during a drag. 'Show mesh' draws the edge of every polygon.\n"
        "\n"
        "'Relief shading' lights the surface from the north-west, and "
        "'Relief strength' scales it from 0 to 1. Tick a box and read "
        "the sheet.",
        pre=lambda a: (open_section(a, "Plot", "3D plot options"),
                       arm_section("3D plot options")(a)),
        target=_surface_look_rows,
        action=("Show me the mesh", _toggle_mesh),
        wait=section_changed("3D plot options"),
        wait_hint="Tick 'Show mesh', or move 'Relief strength'.",
        avail=_has_section("3D plot options")),

    # -- The axes ----------------------------------------------------------
    Step(
        "axis", C_AXES,
        "The axes",
        "X converts between wavelength, wavenumber and photon energy. Y "
        "picks what Overlay plots: absorbance, a raw channel, or a "
        "formula. 'Top axis' mirrors a second unit across the top.\n"
        "\n"
        "The limit boxes and the plot hold one state: a zoom fills the "
        "boxes, and a typed limit moves the plot. 'Reset axes' is the "
        "way back.",
        pre=lambda a: (_settle_2d(a),
                       open_section(a, "Axes", "Limits & scale"),
                       open_section(a, "Axes", "Axis"),
                       arm_section("Axis")(a)),
        target=lambda a: sections_span(a, ["Axis", "Limits & scale"]),
        action=("Flip X for me", _flip_x),
        wait=section_changed("Axis"),
        wait_hint="Try 'Flip X', or switch X to wavenumber.",
        avail=_has_section("Axis")),

    Step(
        "ticks", C_AXES,
        "Ticks, frame and grid",
        "Major and minor spacing sit per axis, and a blank box means "
        "automatic. 'Auto' fills the boxes with the values matplotlib "
        "uses now, ready to nudge. 'Marks: in' is the common journal "
        "setting.\n"
        "\n"
        "Frame & grid styles both the grids and the spines, and 'Hide "
        "top/right spines' takes one click.",
        pre=lambda a: (open_section(a, "Axes", "Frame & grid"),
                       open_section(a, "Axes", "Ticks")),
        target=lambda a: sections_span(a, ["Ticks", "Frame & grid"]),
        avail=_has_section("Ticks")),

    # -- Style -------------------------------------------------------------
    Step(
        "colors", C_STYLE,
        "Color",
        "The colormap spreads across the traces by series value. The "
        "Crameri maps (batlow, roma, hawaii, lajolla) are perceptually "
        "uniform and color-blind safe. [ and ] cycle the list.\n"
        "\n"
        "Shades picks continuous or discrete color, and Levels sets the "
        "number of steps. 'Trace colors...' sets one trace by hand. "
        "'Lock colors to all datasets' holds each curve's color when "
        "its neighbors are hidden.",
        pre=lambda a: (open_section(a, "Style", "Colors & colormap"),
                       arm_section("Colors & colormap")(a)),
        target=lambda a: section_body(a, "Colors & colormap"),
        action=("Try the next one", _cycle_colormap),
        wait=section_changed("Colors & colormap"),
        wait_hint="Press ], or pick a map, and the traces recolor.",
        avail=_has_section("Colors & colormap")),

    Step(
        "type", C_STYLE,
        "Type and labels",
        "Fonts sets the typeface for every text element in the figure, "
        "with Bold and Italic per element. Italic takes a face that has "
        "one, such as Arial or Segoe UI.\n"
        "\n"
        "The title and the axis labels each carry their own size box. "
        "Mathtext works in all of them: $\\lambda$ and Fe$^{2+}$ come "
        "out typeset.",
        pre=lambda a: (open_section(a, "Style", "Title & axis labels"),
                       open_section(a, "Style", "Fonts")),
        target=lambda a: sections_span(a, ["Fonts", "Title & axis labels"]),
        avail=_has_section("Fonts")),

    Step(
        "key", C_STYLE,
        "Legends and reference lines",
        "Past about ten traces a legend covers the data. 'Direct labels "
        "at curves' writes each value at its own curve end, styled by "
        "Size, Distance, Bold and Backing.\n"
        "\n"
        "A colorbar gives one continuous scale, and the legend and the "
        "colorbar draw together. Reference lines draws vertical "
        "wavelengths or horizontal absorbance levels, each with its own "
        "color, pattern and opacity.",
        pre=lambda a: (open_section(a, "Style", "Reference lines"),
                       open_section(a, "Style", "Colorbar"),
                       open_section(a, "Style", "Legend")),
        target=lambda a: sections_span(a, ["Legend", "Colorbar",
                                           "Reference lines"]),
        avail=_has_section("Legend")),

    # -- The numbers -------------------------------------------------------
    Step(
        "smoothing", C_NUMBERS,
        "Smoothing",
        "'Show smoothed' draws the smoothed curve over the raw one, and "
        "Raw opacity sets how much raw shows through. The CSVs a Run "
        "wrote stay as they are.\n"
        "\n"
        "The filter pipeline sits behind 'Smoothing settings...'.",
        pre=lambda a: open_section(a, "Data", "Smoothing"),
        target=lambda a: section_body(a, "Smoothing"),
        action=("Open it for me", lambda a: a._open_smooth_panel()),
        wait=dialog_open(SMOOTH_PANEL),
        wait_hint="Press 'Smoothing settings...'.",
        avail=_has_section("Smoothing")),

    Step(
        "smooth_steps", C_NUMBERS,
        "The five filters",
        "Saturation cutoff drops points above a ceiling. The density "
        "filter blanks mostly-empty stretches. Hampel removes isolated "
        "spikes and keeps real peaks. Savitzky-Golay is the smoother. "
        "The jump filter cleans the steps where segments meet.\n"
        "\n"
        "Live preview is on: toggle an Enable box, or change 'Split at "
        "(nm)', and the plot redraws.",
        target=in_dialog(
            SMOOTH_PANEL,
            lambda a, d: common_block(d, ["1. Saturation cutoff",
                                          "5. Jump filter"]),
            lambda a: section_body(a, "Smoothing")),
        dialog=SMOOTH_PANEL,
        avail=_has_section("Smoothing")),

    Step(
        "smooth_done", C_NUMBERS,
        "Apply or cancel",
        "Apply keeps the changes. Cancel and Escape both restore the "
        "values the window opened with.\n"
        "\n"
        "Removed points become gaps. Close the window and the tour "
        "moves on.",
        target=in_dialog(
            SMOOTH_PANEL,
            lambda a, d: find_all_text(d, ["Apply", "Cancel"]),
            lambda a: section_body(a, "Smoothing")),
        dialog=SMOOTH_PANEL,
        action=("Close it for me", close_dialog(SMOOTH_PANEL, ("Cancel",))),
        wait=dialog_shut(SMOOTH_PANEL),
        wait_hint="Close the smoothing window.",
        avail=_has_section("Smoothing")),

    Step(
        "traces", C_NUMBERS,
        "Traces and branches",
        "One row per loaded point. The check shows the trace, and the D "
        "box marks it decompression. A colored dot means a quality "
        "check fired, and a hover gives the reason.\n"
        "\n"
        "'Only C' and 'Only D' read one branch at a time. "
        "'Decompression list...' tags matching traces from a plain list "
        "of values, which suits filenames that omit the _D tag.",
        pre=lambda a: open_section(a, "Data", "Traces"),
        target=lambda a: section_body(a, "Traces"),
        avail=_has_section("Traces")),

    Step(
        "formulas", C_NUMBERS,
        "Formulas",
        "Any arithmetic over the loaded columns becomes a plottable, "
        "exportable quantity. The row dot plots that formula, and Edit, "
        "Delete and 'Save formula CSVs' act on it.\n"
        "\n"
        "Press 'New...' and the tour writes one alongside you.",
        pre=lambda a: open_section(a, "Data", "Formulas"),
        target=lambda a: section_body(a, "Formulas"),
        action=("Open the editor", lambda a: a._quantity_editor()),
        wait=dialog_open(FORMULA_EDITOR),
        wait_hint="Press 'New...' in the Formulas box.",
        avail=_has_section("Formulas")),

    Step(
        "formula_expr", C_NUMBERS,
        "The expression editor",
        "The editor takes numbers, parentheses and the operators +, -, "
        "*, / and **. It also takes log10, log, exp, sqrt, abs, minimum "
        "and maximum. Click a symbol under the Expression box to drop "
        "it in at the cursor.\n"
        "\n"
        "Try this one:\n"
        "\n"
        "100 * (S - D) / (B - D)\n"
        "\n"
        "Nothing is stored until the formula is saved.",
        pre=arm_formula,
        target=in_dialog(
            FORMULA_EDITOR,
            lambda a, d: common_block(d, ["Expression",
                                          "click a symbol to insert it"]),
            lambda a: section_body(a, "Formulas")),
        dialog=FORMULA_EDITOR,
        action=("Type one for me", formula_example),
        wait=formula_touched,
        wait_hint="Click a symbol, or type in a box.",
        avail=_has_section("Formulas")),

    Step(
        "formula_done", C_NUMBERS,
        "The formula preview",
        "The Preview card shows the formula typeset. It lists the "
        "columns the formula uses, anything wrong with it, and the min, "
        "max and NaN count of the first trace.\n"
        "\n"
        "Save stays off until the formula is clean. Name it and save, "
        "or press Cancel.",
        target=in_dialog(
            FORMULA_EDITOR,
            lambda a, d: (find_all_text(d, ["Save", "Cancel"]) or [])
            + [card_of(find_by_text(d, "Preview"))],
            lambda a: section_body(a, "Formulas")),
        dialog=FORMULA_EDITOR,
        action=("Close it for me",
                close_dialog(FORMULA_EDITOR, ("Cancel", "Close"))),
        wait=dialog_shut(FORMULA_EDITOR),
        wait_hint="Save it, or cancel it.",
        avail=_has_section("Formulas")),

    Step(
        "builtins", C_NUMBERS,
        "The built-in formulas",
        "Absorbance and Transmittance ship read-only, written out as "
        "formulas. 'Absorption coefficient' is ln(10) * A / t in cm^-1, "
        "and 'A/t' is the plain ratio in um^-1.\n"
        "\n"
        "Both use t, the optical thickness from fringe detection. A "
        "confident fringe gives a trace its t; the formula draws a gap "
        "for the others.",
        pre=lambda a: open_section(a, "Data", "Formulas"),
        target=_builtin_rows,
        avail=_has_section("Formulas")),

    # -- Fringe workbench --------------------------------------------------
    # The longest chapter on purpose: it is the one surface in the program
    # whose mouse grammar cannot be guessed from its controls, and it
    # assumes no prior knowledge of the analysis it is a port of.
    #
    # R7 order: the LOW-PASS is the main cleaning tool, so it is taught
    # first and the hand-picked notches come after it as the refinement.
    # R10 retired the standalone Defringe card: the FFT removal card IS
    # the defringe control now, and R16 made it the ONLY one -- every
    # view cleans through it.  R14 brought the search gates back out of
    # that pop-out into a Detection card above FFT removal, and put the
    # Defringe switch at the head of the column.  The seven cards are
    # Stack, Session, Pressure point, Detection, FFT removal, Refractive
    # Index from Intensity and Panels.
    Step(
        "fringe_why", C_FRINGE,
        "Where the fringes come from",
        "A fine wiggle sits on top of every curve. The cell has flat, "
        "parallel surfaces, so light bounces between them before it "
        "leaves.\n"
        "\n"
        "Paths that agree give a bright fringe and paths that disagree "
        "give a dark one. The spacing is thickness times refractive "
        "index, so the ripple measures the cell.",
        target=_plot_canvas,
        avail=_has_plot()),

    Step(
        "fringe_switch", C_FRINGE,
        "The Fringe workbench",
        "The workbench cleans the fringes and measures them. The df box "
        "above the plot follows whatever is set here.\n"
        "\n"
        "Click 'Fringe' on the switch. Only the middle of the window "
        "changes.",
        target=lambda a: getattr(a, "_view_switch", None),
        action=("Switch for me", _fringe_call("activate")),
        wait=_fringe_active,
        wait_hint="Click 'Fringe' at the right-hand end of the tab strip.",
        avail=_has("_view_switch")),

    Step(
        "fringe_df", C_FRINGE,
        "The Defringe switch",
        "'Defringe (df)' sits at the head of the Fringe column, and the "
        "df box above the plot is the same switch.\n"
        "\n"
        "It is a display switch: it changes the plotted counts only. "
        "The Defringed data row in Export > Data files decides whether a "
        "Run and an Export add the cleaned columns. The red FFT "
        "filtered curve in this window draws whenever something is "
        "being filtered, whatever this box says.\n"
        "\n"
        "Click it and read the plotted curves.",
        pre=lambda a: (_ensure_fringe(a), arm_defringe(a)),
        target=_defringe_row,
        action=("Toggle it for me", _toggle_defringe),
        wait=defringe_changed,
        wait_hint="Click the 'Defringe (df)' box.",
        avail=_has_df()),

    Step(
        "fringe_fft", C_FRINGE,
        "The four panels",
        "The left column shows what the described cell predicts, as an "
        "FFT. The right column shows the measured spectra, raw and "
        "cleaned. Background sits on top in both columns, Sample below.\n"
        "\n"
        "The left axis is optical path, n*t in microns. A bump there "
        "means something in the cell is that many microns thick.",
        pre=_ensure_fringe,
        target=_fringe_canvas,
        avail=_has("_view_switch")),

    Step(
        "fringe_toolbar", C_FRINGE,
        "The panel toolbar",
        "A matplotlib toolbar sits under the four panels. Home returns "
        "the view, and Back and Forward walk the history.\n"
        "\n"
        "The pan hand and the zoom rectangle act on whichever panel the "
        "drag starts in. Save writes the four panels as an image. The "
        "workbench gestures rest while a toolbar mode is armed.",
        pre=_ensure_fringe,
        target=_fringe_toolbar,
        avail=lambda a: _alive(_fringe_toolbar(a))),

    Step(
        "fringe_stack", C_FRINGE,
        "The Stack card",
        "Stack is what sits in the light path: Anvil, Medium, an "
        "optional Layer 2, and three thicknesses. The three are d1 "
        "lower medium, t sample and d2 upper medium.\n"
        "\n"
        "Colored stems mark the predicted peak positions. Nudge 't "
        "sample (um)'. The stems sit on the measured bumps when the "
        "description is right.",
        pre=lambda a: (_ensure_fringe(a),
                       open_section(a, "Fringe", "Stack"),
                       arm_section("Stack")(a)),
        target=_stack_rows,
        action=("Nudge it for me", _nudge_sample_t),
        wait=section_changed("Stack"),
        wait_hint="Nudge 't sample (um)' and watch the stems move.",
        avail=_has_section("Stack")),

    Step(
        "fringe_calcn", C_FRINGE,
        "Indices at a pressure",
        "The P box holds the pressure the index models are read at. It "
        "fills in from the loaded spectrum, and an empty box takes that "
        "value back.\n"
        "\n"
        "'calc n' reads the anvil index at P. The medium and layer 2 "
        "follow while a model drives them. The wavelength is the fringe "
        "window's centre.\n"
        "\n"
        "'Ambient n (2.4168)' puts the anvil back on the ambient "
        "constant.",
        pre=lambda a: (_ensure_fringe(a),
                       open_section(a, "Fringe", "Stack")),
        target=_calc_n_row,
        action=("Read them for me", _fringe_call("_calc_n")),
        avail=_has_section("Stack")),

    Step(
        "fringe_lowpass", C_FRINGE,
        "The low-pass cutoff",
        "The FFT removal card is the first tool to reach for. On a "
        "channel with a fringe it treats everything rippling faster "
        "than the cutoff as noise and removes it. Background and Sample "
        "each take their own cutoff, from 1 to 200 micron.\n"
        "\n"
        "Nudge a cutoff and read the cleaned curve. The dashed line on "
        "the chart is the same control and can be dragged; the drag "
        "holds inside its own chart, and the tinted band right of the "
        "line is what comes out. 'Clear notches' puts a channel back to "
        "low-pass only.",
        pre=lambda a: (_ensure_fringe(a),
                       open_section(a, "Fringe", "FFT removal"),
                       arm_section("FFT removal")(a)),
        target=_lowpass_rows,
        action=("Move the cutoff", _nudge_lowpass),
        wait=section_changed("FFT removal"),
        wait_hint="Change a 'Low-pass cutoff' box, or drag the dashed line.",
        avail=_has_section("FFT removal")),

    Step(
        "fringe_edge", C_FRINGE,
        "The edge shape",
        "'Edge' picks how the cutoff rolls off. Tanh is the shipped "
        "shape, error function falls a little steeper over the same "
        "width, and Hard cuts at the cutoff itself.\n"
        "\n"
        "The box beside it is the roll-off width, in micron of n*t. One "
        "width past the cutoff, tanh keeps 12% of the signal and error "
        "function keeps 8%.\n"
        "\n"
        "A dotted curve over the FFT panel traces the mask the two "
        "make.",
        pre=lambda a: (_ensure_fringe(a),
                       open_section(a, "Fringe", "FFT removal")),
        target=_lp_edge_rows,
        avail=_has_section("FFT removal")),

    Step(
        "fringe_notch", C_FRINGE,
        "Notching a peak",
        "One ripple sometimes survives the low-pass. A notch is a bite "
        "out of the transform, and removing that band removes its "
        "ripple from the spectrum.\n"
        "\n"
        "Left-click within about 0.8 microns of a peak to notch it, and "
        "click it again to take it off. 'Notch list' opens the centres "
        "and their widths in their own window.",
        pre=lambda a: (_ensure_fringe(a),
                       open_section(a, "Fringe", "FFT removal"),
                       arm_notches(a)),
        target=_fringe_canvas,
        action=("Notch one for me", _notch_one),
        wait=notch_changed,
        wait_hint="Click a peak on the plot to notch it.",
        avail=_has_section("FFT removal")),

    Step(
        "fringe_pin", C_FRINGE,
        "The fundamental peak",
        "One peak is the fundamental, the real interference spacing. "
        "The peaks at two and three times its n*t are harmonics.\n"
        "\n"
        "Right-click a peak to pin it as the fundamental. The same menu "
        "hands the choice back.",
        pre=_ensure_fringe,
        target=_fringe_canvas,
        avail=_has_section("FFT removal")),

    Step(
        "fringe_notchlist", C_FRINGE,
        "The notch list",
        "'Notch list' opens every centre in a window of its own, one "
        "row per notch. A ticked row is notched; an unticked row keeps "
        "its marker on the chart.\n"
        "\n"
        "The box beside the tick holds that row's own half-width, in "
        "micron. 'fine steps' moves those boxes 0.1 micron a press.",
        pre=lambda a: (_ensure_fringe(a),
                       open_section(a, "Fringe", "FFT removal")),
        target=_notch_list_btn,
        action=("Open the list", _fringe_call("_open_notch_list")),
        wait=dialog_open(NOTCH_LIST),
        wait_hint="Press 'Notch list' on the FFT removal card.",
        avail=_has_section("FFT removal")),

    Step(
        "fringe_fundamental", C_FRINGE,
        "The Fundamental column",
        "The radio column marks the peak the detector reports as the "
        "fundamental. The rest are its harmonics.\n"
        "\n"
        "Click another row and the fundamental moves there. Click the "
        "marked row and that channel's fundamental clears, which the "
        "list states under the rows.\n"
        "\n"
        "'Clear' takes every notch off one channel. The chart's "
        "right-click menu offers the same three states.",
        target=in_dialog(NOTCH_LIST, _fund_rows, _notch_list_btn),
        dialog=NOTCH_LIST,
        action=("Close it for me", close_dialog(NOTCH_LIST)),
        wait=dialog_shut(NOTCH_LIST),
        wait_hint="Close the notch list.",
        avail=_has_section("FFT removal")),

    Step(
        "fringe_detect", C_FRINGE,
        "The Detection card",
        "The Detection card sits above FFT removal and holds the search "
        "gates and the live report.\n"
        "\n"
        "'Window (nm)' is the wavelength range, 'n*t band (um)' the "
        "optical path range, 'Fisher p' the significance gate and "
        "'Agree tol' the agreement tolerance. The df pass reads the "
        "same window, so a trace cleans over the range set here.\n"
        "\n"
        "SPARTA examines three stretches, and two of them agree for an "
        "accepted answer. The Report gives the path it settled on, the "
        "p-value and the windows that agreed.",
        pre=lambda a: (_ensure_fringe(a),
                       open_section(a, "Fringe", "Detection")),
        target=_detection_card,
        action=("Show me the card", _fringe_call("_open_detection")),
        wait=_detection_shown,
        wait_hint="Open the Detection card on the Fringe panel.",
        avail=_has_section("Detection")),

    Step(
        "fringe_roles", C_FRINGE,
        "The three peak roles",
        "Three peaks, three journeys through the cell. 'Sample' is "
        "light between the sample's two faces, 'Sample diamonds' adds "
        "the medium against it, and 'Medium diamond' is the whole gap "
        "between the anvils.\n"
        "\n"
        "The glyphs sit along the top of the panels. Drag one onto a "
        "different peak and the drop point places it and solves the "
        "cell in one gesture. A right-click assigns the role at the "
        "peak under the cursor.\n"
        "\n"
        "A solid guide line marks a glyph SPARTA placed, a dashed guide "
        "marks a placed one. A coincident pair steps apart onto two "
        "rows, so either one can be pulled off.",
        pre=_ensure_fringe,
        target=_fringe_canvas,
        avail=_has_section("Stack")),

    Step(
        "fringe_solve", C_FRINGE,
        "Fit peaks",
        "'Fit peaks:' resets every role to automatic and seeds them "
        "from the stack. A Gaussian then refines each one onto its real "
        "centre and SPARTA solves. Distinct fits the sample and "
        "sample-diamond peaks apart; Shared fits them as one hump.\n"
        "\n"
        "A fitted Gaussian draws under each automatic role, and a joint "
        "envelope covers the Sample pair while both roles are "
        "automatic.\n"
        "\n"
        "Three peak positions and the stack give n sample, t sample, "
        "the layer total and the whole gap L.",
        pre=lambda a: (_ensure_fringe(a),
                       open_section(a, "Fringe", "Stack"),
                       arm_section("Stack")(a)),
        target=_fit_row,
        action=("Fit them for me", _fringe_call("_fit_peaks_mode",
                                                "distinct")),
        wait=section_changed("Stack"),
        wait_hint="Press one of the two 'Fit peaks:' buttons.",
        avail=_has_section("Stack")),

    Step(
        "fringe_adopt", C_FRINGE,
        "The solved column",
        "The answers land beside the boxes they came from: n_s beside n "
        "sample, t_s beside t sample, the medium total beside d2 and L "
        "beside d1.\n"
        "\n"
        "A fit writes them back into the inputs, so the stems relock "
        "onto the solved geometry. A dragged glyph does the same on the "
        "drop. Fit again until they stop moving.",
        pre=lambda a: (_ensure_fringe(a),
                       open_section(a, "Fringe", "Stack")),
        target=_solved_block,
        avail=_has_section("Stack")),

    Step(
        "fringe_intensity", C_FRINGE,
        "Fits from the intensity",
        "'Compute fits' runs the full amplitude fitters at the current "
        "notch and low-pass settings. The right panels switch to the "
        "tiered view and show the result.\n"
        "\n"
        "History reopens a previous run, named by the fitted n.",
        pre=lambda a: (_ensure_fringe(a),
                       open_section(a, "Fringe",
                                    "Refractive Index from Intensity")),
        target=_intensity_row,
        action=("Compute them for me", _fringe_call("_compute_fits")),
        wait=_intensity_done,
        wait_hint="Press 'Compute fits'.",
        avail=_has_section("Refractive Index from Intensity")),

    Step(
        "fringe_record", C_FRINGE,
        "Recording a series",
        "One solved point is a data point, and a run is the whole "
        "series. 'Plot point' files this point's solved values.\n"
        "\n"
        "Pressure point walks the rest, up the compression run and back "
        "down the decompression leg. The demo turns at 8.40 GPa. "
        "Session > 'Save session' writes the lot to disk.",
        pre=lambda a: (_ensure_fringe(a),
                       open_section(a, "Fringe", "Pressure point"),
                       open_section(a, "Fringe", "Stack"),
                       arm_record(a)),
        target=_point_block,
        action=("File this one", _fringe_call("_record_point")),
        wait=record_done,
        wait_hint="Press 'Plot point' to file this pressure point.",
        avail=_has_section("Stack")),

    Step(
        "fringe_session", C_FRINGE,
        "The session file",
        "The pressure dropdown marks each point against "
        "series_continuity.json. A tick means the file holds this point "
        "as it stands here, a dot means the file holds it with other "
        "values, and a plain label is a point the file has yet to see.\n"
        "\n"
        "Page Up and Page Down walk the same list. A fresh point opens "
        "seeded from the nearest preceding point in the series.\n"
        "\n"
        "'Save session' carries the recorded points and each point's "
        "own inputs, and its tooltip itemises what a save would change.",
        pre=lambda a: (_ensure_fringe(a),
                       open_section(a, "Fringe", "Pressure point")),
        target=_pressure_picker,
        avail=_has_section("Pressure point")),

    Step(
        "fringe_results", C_FRINGE,
        "The results plot",
        "'Results plot' opens the filed points as six panels. The three "
        "refractive indices run along the top, and under each one sits "
        "the thickness it belongs to.\n"
        "\n"
        "Compression points are filled circles and decompression points "
        "are open crosses. A tick on the button means this point is "
        "already on the plot.",
        pre=lambda a: (_ensure_fringe(a),
                       open_section(a, "Fringe", "Stack")),
        target=_results_btn,
        action=("Show me the results", _fringe_call("results_view")),
        avail=_has_section("Stack")),

    Step(
        "fringe_defringe", C_FRINGE,
        "Cleaning the written CSVs",
        "The df box above the plot cleans each trace at its own notch "
        "list, cutoffs and edge. A Run and an Export follow the same "
        "lists whenever the Defringed data row is ticked in Export > "
        "Data files.\n"
        "\n"
        "The ticked boxes are the answer. With every box unticked the "
        "trace keeps its own counts, and on a channel with a fringe a "
        "low-pass that is on still applies. A channel with no detected "
        "fringe passes through as it came in, and its notch column "
        "stays blank. A trace this panel has yet to open cleans under "
        "the global controls, at the fringe the detector finds in it.\n"
        "\n"
        "'Write notches file for batch' exports the same decisions as a "
        "CSV the batch pipeline reads. 'Delete notches file' drops this "
        "spectrum's saved rows.",
        pre=lambda a: (_ensure_fringe(a),
                       open_section(a, "Fringe", "FFT removal")),
        target=_notch_writers,
        avail=_has_section("FFT removal")),

    Step(
        "fringe_guide", C_FRINGE,
        "The full reference",
        "'Guide' beside the Plot / Fringe switch opens the workbench "
        "reference next to the plot. It covers every marker shape, "
        "every mouse gesture and every control on the six cards. The "
        "same text sits under 'Fringe analysis' in the Guide box.\n"
        "\n"
        "'Pop out' opens the original analysis window, with its own "
        "layout and its whole control set. The two views share one "
        "model, so an edit in either shows in both.\n"
        "\n"
        "The button at the pop-out's top right fills the screen, and "
        "F11 does the same. Escape leaves full screen.",
        pre=_ensure_fringe,
        target=_fringe_guide_toggle,
        avail=_has("_view_switch")),

    # -- Export ------------------------------------------------------------
    Step(
        "presets", C_EXPORT,
        "Presets and projects",
        "A preset saves the whole control state under a name, so one "
        "house style serves any dataset. A project saves that plus the "
        "folders, as a .json that reopens months later.\n"
        "\n"
        "'Reset all' resets every plot control and asks first. The data "
        "and the folders stay.",
        pre=lambda a: (_leave_fringe(a),
                       open_section(a, "Export", "Presets & projects")),
        target=lambda a: section_body(a, "Presets & projects"),
        avail=_has_section("Presets & projects")),

    Step(
        "figure", C_EXPORT,
        "Journal presets",
        "One pick sets a publisher's column width and house style: "
        "typeface, text sizes, line weight, spines, ticks and DPI. "
        "Nature, Science, RSI/AIP, APS and Elsevier are all there.\n"
        "\n"
        "'Set as default' remembers one.",
        pre=lambda a: open_section(a, "Export", "Figure"),
        target=lambda a: section_body(a, "Figure"),
        avail=_has_section("Figure")),

    Step(
        "export", C_EXPORT,
        "Saving the figure",
        "'Save plot...' writes PNG, PDF, SVG, EPS or TIFF, and the "
        "'Also save' boxes write the extra formats beside it. 'Editable "
        "text' keeps vector labels editable in Illustrator or Inkscape.\n"
        "\n"
        "'Batch export (one per shown trace)...' saves one file per "
        "shown trace on the current styled figure. Every export leaves "
        "a provenance sidecar.",
        pre=lambda a: (open_section(a, "Export", "Export"),
                       arm_section("Export")(a)),
        target=lambda a: section_body(a, "Export"),
        action=("Show me true size",
                _click_by_text("Export", "Preview at export size (WYSIWYG)")),
        wait=section_changed("Export"),
        wait_hint="Tick 'Preview at export size (WYSIWYG)'.",
        avail=_has_section("Export")),

    Step(
        "data_files", C_EXPORT,
        "Data files",
        "One list of the columns each trace's CSV carries. A Run "
        "writes them, and an Export writes them again. Absorbance "
        "data (always) is ticked and disabled, because a Run always "
        "writes the base columns.\n"
        "\n"
        "Defringed data is on by default and appends the three notch "
        "columns. Smoothed data, Formula values and C/D tag in file "
        "name are off. The C/D row names the files, it does not copy "
        "them.\n"
        "\n"
        "'Export data…' opens the Export dialog, and so do the left "
        "panel's 'Export…' button and Ctrl+E. It writes one CSV per "
        "loaded trace into a folder you pick, with an optional "
        "wavelength crop for that export alone, under one provenance "
        "sidecar.",
        pre=lambda a: open_section(a, "Export", "Data files"),
        target=lambda a: section_body(a, "Data files"),
        avail=_has_section("Data files")),

    Step(
        "stl", C_EXPORT,
        "3D printing",
        "The 3D surface leaves as a printable solid: the data becomes "
        "the top face, four walls drop to a flat base, and SPARTA "
        "checks the mesh watertight before it writes.\n"
        "\n"
        "Shape picks 'Surface cube' or 'Folder divider'. Size X/Y, "
        "Height Z, Base and Z exaggeration set the print in mm. Smooth "
        "or defringe first, because every fringe prints as a fin.",
        # the section is "3D Printing" after the R2 rename and "3D shape"
        # before it; the tour points at whichever this build carries
        pre=lambda a: open_section(a, "Export", _stl_key(a)),
        target=lambda a: section_body(a, _stl_key(a)),
        avail=lambda a: section_rec(a, _stl_key(a)) is not None),

    # -- Settling in -------------------------------------------------------
    Step(
        "find", C_SETTLE,
        "Finding a control",
        "Type what is wanted in 'Find' (grid, legend, ridge). The "
        "sections holding it open, and the rest fold away.\n"
        "\n"
        "'Collapse all' folds everything to titles. Click it again to "
        "open them.",
        target=_find_block,
        action=("Search for 'legend'", _seed_find),
        wait=_find_used,
        wait_hint="Type something in the Find box.",
        avail=_has("_collapse_btn")),

    Step(
        "guide", C_SETTLE,
        "The guide box",
        "This box is the manual. Its View dropdown holds a quick start "
        "and the naming system. It also holds one page per panel tab, "
        "the workflows, the fringe workbench, the shortcut list and "
        "troubleshooting.\n"
        "\n"
        "'My notes' at the bottom is a scratchpad saved between "
        "launches.",
        pre=_clear_find,
        target=_guide_card,
        avail=_has("ref")),

    Step(
        "chrome", C_SETTLE,
        "Theme and top bar",
        "Theme sits up here. Six themes sit above the divider, High "
        "Contrast and the two Colorblind Safe themes among them. Below "
        "the line, only the colors change.\n"
        "\n"
        "The gear beside it opens Settings. NUKE is the hard reset and "
        "it asks first. The two arrows at the far right hide the "
        "panels.",
        pre=_arm_theme,
        target=_top_bar,
        action=("Try another theme", _try_dark),
        wait=_theme_changed,
        wait_hint="Pick a theme from the dropdown.",
        avail=_has("_theme_combo")),

    Step(
        "settings", C_SETTLE,
        "The Settings panel",
        "The gear on the top bar opens the Settings panel.\n"
        "\n"
        "It holds Font, Text size, Helper tips and Performance mode. "
        "Tutorial and About sit at the bottom.\n"
        "\n"
        "Click the gear.",
        pre=close_settings,
        target=_settings_gear,
        action=("Open it for me", open_settings),
        wait=settings_open,
        wait_hint="Click the gear on the top bar.",
        avail=_has("_settings_gear_btn")),

    Step(
        "settings_rows", C_SETTLE,
        "The Settings rows",
        "Font sets the typeface of the program, and OpenDyslexic is in "
        "the list. Text size scales every control, and 'auto' reads it "
        "from the screen.\n"
        "\n"
        "Helper tips switches the hover tips. Performance mode suits a "
        "slower machine.\n"
        "\n"
        "Tutorial starts this tour again. About names the build.",
        pre=open_settings,
        target=in_settings(_settings_rows, _settings_gear),
        avail=_has("_settings_gear_btn")),

    Step(
        "finish", C_SETTLE,
        "End of the tour",
        "Folder in, Run, read the plot, style it, export it. Everything "
        "else is detail to look up when it is needed.\n"
        "\n"
        "F1 lists the shortcuts, and hovering any control gives its "
        "tip. Settings > About > 'Welcome & tour...' brings this back "
        "at any time."),
]


# ---------------------------------------------------------------------------
# 5. The spotlight
# ---------------------------------------------------------------------------
class _Spotlight(object):
    """Four semi-transparent strips tiling the window around one rectangle.

    A hole cut in a single overlay would need per-pixel alpha, which Tk
    does not have; four opaque-ish strips around the target give the same
    picture and leave the target itself completely untouched - not
    covered, not greyed, still clickable.

    The strips are created ONCE per tour and only ever moved.  Each one
    remembers its geometry string and whether it is mapped, so a step that
    does not move a strip costs it no map, no unmap and no reconfigure -
    which is what stops the four of them tearing past each other on every
    Next (the flicker).
    """

    def __init__(self, app):
        self.app = app
        self.strips = []
        self._geo = [None] * 4
        self._mapped = [False] * 4
        # diagnostics: a map / unmap is the expensive, visible operation.
        # The harness asserts these stay near four for a whole walk.
        self.maps = 0
        self.unmaps = 0
        self.moves = 0
        for _ in range(4):
            w = tk.Toplevel(app.root)
            w.withdraw()
            w.overrideredirect(True)
            try:
                # park it off the desktop before it can ever be mapped: a
                # brand-new Toplevel is 1x1+0+0, and anything that maps one
                # before show() has given it a rectangle would paint a
                # one-pixel sliver in the corner of the screen
                w.geometry("1x1-4000-4000")
            except tk.TclError:
                pass
            try:
                w.attributes("-alpha", SCRIM_ALPHA)
                w.attributes("-topmost", True)
            except tk.TclError:
                pass
            try:
                w.configure(background=SCRIM)
            except tk.TclError:
                pass
            self.strips.append(w)

    def _boxes(self, rect, win):
        wx, wy, ww, wh = win
        if rect is None:
            return [(wx, wy, ww, wh), None, None, None]
        tx, ty, tw, th = rect
        # clamp the target to the window: a control scrolled half out of
        # its pane must not punch a hole through the chrome beside it
        tx0 = max(wx, min(tx, wx + ww))
        ty0 = max(wy, min(ty, wy + wh))
        tx1 = max(tx0, min(tx + tw, wx + ww))
        ty1 = max(ty0, min(ty + th, wy + wh))
        return [
            (wx, wy, ww, ty0 - wy),                     # above
            (wx, ty1, ww, (wy + wh) - ty1),             # below
            (wx, ty0, tx0 - wx, ty1 - ty0),             # left
            (tx1, ty0, (wx + ww) - tx1, ty1 - ty0),     # right
        ]

    def boxes(self, rect, win):
        """The four strip rectangles, for tests that check coverage."""
        return self._boxes(rect, win)

    def show(self, rect, win):
        """Move the strips. Returns how many CHANGED mapped state.

        The count matters to the caller: mapping a Toplevel raises it, so
        any step that brings a new strip up has put it above the callout
        and the callout has to be raised back exactly once.
        """
        changed = 0
        for i, (w, b) in enumerate(zip(self.strips, self._boxes(rect, win))):
            if b is None or b[2] < 1 or b[3] < 1:
                if self._mapped[i]:
                    try:
                        w.withdraw()
                    except tk.TclError:
                        pass
                    self._mapped[i] = False
                    self.unmaps += 1
                    changed += 1
                continue
            g = "%dx%d+%d+%d" % (b[2], b[3], b[0], b[1])
            try:
                if self._geo[i] != g:
                    w.geometry(g)
                    self._geo[i] = g
                    self.moves += 1
                if not self._mapped[i]:
                    w.deiconify()
                    self._mapped[i] = True
                    self.maps += 1
                    changed += 1
            except tk.TclError:
                pass
        return changed

    def hide(self):
        for i, w in enumerate(self.strips):
            try:
                w.withdraw()
            except tk.TclError:
                pass
            self._mapped[i] = False

    def destroy(self):
        for w in self.strips:
            try:
                w.destroy()
            except tk.TclError:
                pass
        self.strips = []


# ---------------------------------------------------------------------------
# 6. The tour
# ---------------------------------------------------------------------------
class Tour(object):
    TAG = "SpartaTourKeys"
    PAD = 5                # px of air the spotlight leaves around a target
    GAP = 10               # px between the arrow tip and the target

    def __init__(self, app, steps=None):
        self.app = app
        allsteps = list(steps or TOUR_STEPS)
        self.steps = [s for s in allsteps if self._available(s)]
        self.dropped = [s.key for s in allsteps if s not in self.steps]
        self.chapters = []
        for s in self.steps:
            if s.chapter and s.chapter not in self.chapters:
                self.chapters.append(s.chapter)
        self.i = 0
        self.spot = None
        self.card = None
        self._wait_job = None
        self._move_job = None
        self._watch_job = None
        self._tagged = []
        self._grabbed = None
        self._last_rect = None
        self._last_geo = None
        self._side = "none"
        self._arrow_mid = None
        self._card_wh = (420, 260)
        self._act_label = None
        self._act_note = ""            # what the last action button said
        self._auto_ok = True
        self._grew = False
        self._stack_state = "ok"
        self._unlock_job = None        # the unconditional PATIENCE timer
        self._unlocked = False         # it fired for the current step
        self._logged = set()           # step keys that already explained
        #                                themselves in the log, once each

    def _available(self, step):
        if step.avail is None:
            return True
        try:
            return bool(step.avail(self.app))
        except Exception:
            return False

    # -- lifecycle ------------------------------------------------------
    def start(self):
        if getattr(self.app, "_tour", None) is not None:
            try:
                self.app._tour.stop()
            except Exception:
                pass
        self.app._tour = self
        self.spot = _Spotlight(self.app)
        self._build_shell()
        # a click on the dimmed area is dead by design - but if a strip
        # has somehow climbed over the callout (a stacking fight the hit
        # test cannot always see from here), that dead click is also the
        # cheapest possible moment to put the card back on top
        for w in self.spot.strips:
            try:
                w.bind("<Button-1>", lambda _e: self._lift_card())
            except tk.TclError:
                pass
        self._bind_keys()
        self.i = 0
        self._goto(0, +1)
        self._watch()
        return self

    def stop(self, _e=None):
        for job in (self._wait_job, self._move_job, self._watch_job,
                    self._unlock_job):
            if job is not None:
                try:
                    self.app.root.after_cancel(job)
                except Exception:
                    pass
        self._wait_job = self._move_job = self._watch_job = None
        self._unlock_job = None
        self._unbind_keys()
        if self.spot is not None:
            self.spot.destroy()
            self.spot = None
        self._kill_card()
        close_settings(self.app)
        self._regrab()
        if getattr(self.app, "_tour", None) is self:
            self.app._tour = None
        return "break"

    def _kill_card(self):
        if self.card is not None:
            try:
                self.card.destroy()
            except tk.TclError:
                pass
            self.card = None
        self._next_btn = None
        self._prune_app_registries()

    def _prune_app_registries(self):
        """Take the tour's dead widgets back out of app.py's re-theming
        lists.

        `_card`, `_lbl`, `_brand_button` and `_lf_header` file every
        widget they make in a list on the app - `_brand_cards`,
        `_content_labels`, `_brand_btns`, `_lf_markers` - and
        `_apply_brand` walks all of them on every theme switch.  The
        callout is built from exactly those helpers, so a finished tour
        leaves dead entries behind: switching theme afterwards then
        re-tints a destroyed card and re-stamps a marker whose label is
        gone (`invalid command name ...!brandcard.!frame.!label`), which
        raised out of the theme switch and took the interpreter with it.
        Tk also RECYCLES widget path names, so a stale entry can end up
        re-drawing whatever inherited its name.

        Swept generically rather than by a list of names: any list on the
        app holding widgets is filtered, and ONLY entries whose widget is
        genuinely destroyed are dropped, so this can never touch the
        application's own chrome.
        """
        app = self.app
        try:
            items = list(vars(app).items())
        except Exception:
            return
        for name, lst in items:
            if not isinstance(lst, list) or not lst:
                continue
            try:
                if not any(hasattr(w, "winfo_exists") for w in lst):
                    continue                     # not a widget registry
                if all(_alive(w) for w in lst
                       if hasattr(w, "winfo_exists")):
                    continue                     # nothing dead in it
                lst[:] = [w for w in lst
                          if not hasattr(w, "winfo_exists") or _alive(w)]
            except Exception:
                pass
        del name

    # -- modal grabs ----------------------------------------------------
    def _ungrab(self, step=None):
        """Let go of any modal grab that locks the callout out.

        A RUNTIME check, not a per-step classification.  Name format and
        the formula editor are grab_set, and the hands-on design means they
        normally open in the MIDDLE of a step - the step that points at the
        button that opens them.  Classifying only the steps that live
        inside a dialog therefore missed the common case: the grab arrived
        while the tour was still on the opener step, the card sat outside
        the grab tree, and every click on it died (Nhan, step 4).

        A grab is left alone when the card is inside its tree, and when it
        belongs to the card itself - Tk grabs for a Combobox popdown, and
        stealing that would shut the card's own chapter dropdown a quarter
        of a second after it opened.
        """
        del step                       # kept for callers; no longer used
        if not _alive(self.card):
            return
        try:
            cur = self.app.root.grab_current()
        except tk.TclError:
            return
        if cur is None:
            return
        card, gw = str(self.card), str(cur)
        if gw == card:
            return                     # ours
        if card.startswith(gw + "."):
            return                     # the card is inside the grab tree
        if gw.startswith(card + "."):
            return                     # the grab is inside the card
        try:
            self._grabbed = cur
            cur.grab_release()
        except tk.TclError:
            pass

    def _regrab(self):
        w, self._grabbed = self._grabbed, None
        if _alive(w):
            try:
                w.grab_set()
            except tk.TclError:
                pass

    # -- keyboard -------------------------------------------------------
    def _bind_keys(self):
        r = self.app.root
        r.bind_class(self.TAG, "<Escape>", self.stop)
        r.bind_class(self.TAG, "<Right>", lambda e: self._key(+1))
        r.bind_class(self.TAG, "<Left>", lambda e: self._key(-1))
        r.bind_class(self.TAG, "<Configure>", self._on_move)
        # first in the list, so a tour arrow key wins over the plot pan
        tags = tuple(t for t in r.bindtags() if t != self.TAG)
        r.bindtags((self.TAG,) + tags)

    def _unbind_keys(self):
        r = self.app.root
        try:
            r.bindtags(tuple(t for t in r.bindtags() if t != self.TAG))
        except tk.TclError:
            pass
        for w in self._tagged:
            try:
                w.bindtags(tuple(t for t in w.bindtags() if t != self.TAG))
            except tk.TclError:
                pass
        self._tagged = []

    def _tagify(self, widget):
        """Give a callout widget the tour's key bindings, so the arrows
        still navigate after a click has moved focus onto a button.  The
        chapter dropdown is left alone: a readonly Combobox needs its own
        arrow keys to pick a line."""
        try:
            if widget.winfo_class() == "TCombobox":
                return
        except tk.TclError:
            return
        try:
            widget.bindtags((self.TAG,) + tuple(widget.bindtags()))
            self._tagged.append(widget)
        except tk.TclError:
            return
        for c in widget.winfo_children():
            self._tagify(c)

    def _key(self, step):
        try:
            if self.app._typing_in_box():
                return None            # let the box have its arrow key
        except Exception:
            pass
        self._nav(step)
        return "break"

    def _on_move(self, _e=None):
        if self._move_job is not None:
            return
        self._move_job = self.app.root.after(80, self._reposition)

    def _reposition(self):
        self._move_job = None
        if self.spot is None or not self.steps:
            return
        step = self.steps[self.i]
        self._place(*self._target_rect(step))

    # -- the watchdog ---------------------------------------------------
    def _watch(self):
        """Follow the target without repainting anything that has not moved.

        One timer covers three cases a <Configure> on the root cannot: a
        dialog being dragged, a modal grab arriving late, and the dialog a
        step lives inside being closed by the user (Escape, the X, Cancel).
        Nothing is redrawn unless the rectangle actually changed, so the
        cost of it is one geometry read.

        The body is fenced as a whole: this chain is the tour's pulse
        (the follow, the cover heal, the walked-on-from-a-closed-dialog
        advance all live on it), and one exception from a widget that
        vanished mid-tick must not stop the heart.
        """
        self._watch_job = None
        if self.spot is None or not self.steps:
            return
        try:
            self._ungrab()
            step = self.steps[self.i]
            if step.dialog and find_dialog(self.app, step.dialog) is None:
                nxt = self._after_dialog(self.i, step.dialog)
                if nxt is not None:
                    self._goto(nxt, +1)
                    step = None        # _goto repainted; skip this tick
            if step is not None:
                rect, owner = self._target_rect(step)
                if rect != self._last_rect:
                    self._place(rect, owner)
                # cheap enough to run every tick, and it self-heals if
                # anything else raises a window over the callout
                self._ensure_clickable()
        except Exception:
            pass
        if self.spot is not None:      # _goto above may have stopped us
            self._watch_job = self.app.root.after(WATCH_MS, self._watch)

    def _after_dialog(self, idx, titles):
        """The first step at or after idx that does not live in `titles`."""
        for j in range(idx + 1, len(self.steps)):
            if self.steps[j].dialog != titles:
                return j
        return None

    # -- navigation -----------------------------------------------------
    def _nav(self, step):
        if step > 0 and self.i >= len(self.steps) - 1:
            self.app.settings["tour_done"] = True
            try:
                self.app._save_settings()
            except Exception:
                pass
            return self.stop()
        self._goto(self.i + step, step)

    def _skip_chapter(self):
        here = self.steps[self.i].chapter
        for j in range(self.i + 1, len(self.steps)):
            if self.steps[j].chapter != here:
                return self._goto(j, +1)
        return self.stop()

    def _jump_to(self, chapter):
        for j, s in enumerate(self.steps):
            if s.chapter == chapter:
                return self._goto(j, +1)

    def _goto(self, idx, direction=+1):
        """Show step idx, skipping any step whose target cannot be found."""
        n = len(self.steps)
        for _ in range(n):
            if idx < 0:
                idx = 0
            if idx >= n:
                return self.stop()
            step = self.steps[idx]
            # the Settings panel is a window over the bar: any step that
            # is not about it starts with it shut, so the spotlight lands
            # on the control the step names
            if step.key not in SETTINGS_STEPS:
                close_settings(self.app)
            if step.pre is not None:
                try:
                    step.pre(self.app)
                except Exception as e:
                    # the step still shows and its PATIENCE unlock still
                    # arms; the stage just was not set for it
                    self._log_once(step, "Tour: could not set the stage "
                                   "for '%s' (%r); carrying on."
                                   % (step.key, e))
            rect, owner = self._target_rect(step)
            if (rect is None and step.target is not None
                    and self._resolve(step) is None):
                idx += (1 if direction > 0 else -1)   # gone: skip it
                continue
            # a target that exists but has no geometry yet (the workbench
            # sets its own sash on a 60 ms timer the first time it opens)
            # is NOT a missing control: show the step, and the watchdog
            # drops the spotlight on it as soon as Tk has laid it out
            self.i = idx
            # Going back must STAY back: without this, stepping Previous
            # out of a dialog lands on the opener step, whose gate is still
            # satisfied (the dialog is still open), and the tour walks
            # straight back in - a loop the reader cannot escape.
            self._auto_ok = direction > 0
            try:
                self._show(step, rect, owner)
            except Exception as e:
                # a step that failed to paint must still be escapable:
                # card up, Next live, and the tour says what happened
                self._recover(step, e)
            return
        self.stop()

    def _resolve(self, step):
        """The step's target widget(s), or None when there is nothing live.

        Kept separate from _target_rect because 'the control is gone' and
        'the control exists but Tk has not laid it out yet' need different
        answers: the first is a step to skip, the second is a step to show
        while the watchdog waits for the geometry.
        """
        if step.target is None:
            return None
        try:
            target = step.target(self.app)
        except Exception:
            return None
        if target is None:
            return None
        if isinstance(target, (list, tuple)):
            target = [w for w in target if _alive(w)]
            return target or None
        return target if _alive(target) else None

    def _target_rect(self, step):
        """(padded screen rect, owning Toplevel) for a step's target."""
        target = self._resolve(step)
        if target is None:
            return (None, None)
        try:
            scroll_into_view(self.app, target)
        except Exception:
            pass
        rect = union_rect(target)
        if rect is None:
            # A widget mapped a moment ago has no geometry until Tk has run
            # its layout, and a step whose `pre` had to open a whole view
            # (the fringe workbench) hits exactly that. One idle pass, one
            # retry - cheaper than skipping a real step.
            try:
                self.app.root.update_idletasks()
            except tk.TclError:
                return (None, None)
            rect = union_rect(target)
        if rect is None:
            return (None, None)
        return ((rect[0] - self.PAD, rect[1] - self.PAD,
                 rect[2] + 2 * self.PAD, rect[3] + 2 * self.PAD),
                owner_window(target))

    # -- painting -------------------------------------------------------
    def _rect_of(self, win):
        try:
            return (win.winfo_rootx(), win.winfo_rooty(),
                    win.winfo_width(), win.winfo_height())
        except tk.TclError:
            return None

    def _region(self, owner):
        """The rectangle the scrim tiles and the card is kept inside.

        Root alone for a normal step; root UNION the dialog when the target
        has moved into one, so the dialog and everything behind it dim
        together and the card can sit outside a small dialog.
        """
        r = self._rect_of(self.app.root) or (0, 0, 800, 600)
        if owner is None or owner is self.app.root:
            return r
        o = self._rect_of(owner)
        if o is None:
            return r
        x0 = min(r[0], o[0])
        y0 = min(r[1], o[1])
        x1 = max(r[0] + r[2], o[0] + o[2])
        y1 = max(r[1] + r[3], o[1] + o[3])
        return (x0, y0, x1 - x0, y1 - y0)

    def _place(self, rect, owner=None):
        """One batched pass: strips, then the card, then the arrow.

        Everything that can move is moved with geometry() only - nothing is
        destroyed, nothing is re-mapped that was already mapped - and there
        is exactly one update_idletasks in the whole path, so a step change
        repaints once instead of four times.
        """
        if self.spot is None:
            return
        win = self._region(owner)
        self._last_rect = rect
        raised = self.spot.show(rect, win)
        if self.card is None:
            return
        # Mapping a Toplevel RAISES it. Step 1 has no target, so only the
        # one full-window strip is up and the card (mapped after it) sits
        # on top; step 2 is the first targeted step, so three more strips
        # map - above the card - and swallow every click on Next. So: any
        # step that changed a strip's mapped state gets the card raised
        # back, exactly once. Once per step change, never per frame, so
        # this is not the per-repaint lift() the flicker fix removed.
        if raised:
            try:
                self.card.lift()
            except tk.TclError:
                pass
        side, cw, ch, x, y, mid = self._card_spot(rect, win)
        self._side, self._arrow_mid = side, mid
        self._pack_arrow(side)
        geo = "%dx%d+%d+%d" % (cw, ch, x, y)
        try:
            if geo != self._last_geo:
                self.card.geometry(geo)
                self._last_geo = geo
            self.card.update_idletasks()
            # size the card's interior even before its first map: a
            # withdrawn Toplevel gets no <Configure>, and grow="both"
            # takes the body's height from that event
            self._card_w._layout()
        except tk.TclError:
            return
        # last line of defence. If anything about this theme or text size
        # still leaves the buttons below the bottom edge, grow the card by
        # the shortfall and place it again - once.
        ok, fb, cb = self._footer_ok()
        if not ok and not self._grew:
            self._grew = True
            self._card_wh = (self._card_wh[0],
                             self._card_wh[1] + (fb - cb) + 4)
            return self._place(rect, owner)
        self._draw_arrow(side, cw, ch, mid)

    def _card_spot(self, rect, win):
        """Where the callout goes, and where its arrow tip has to land.

        Returns (side, w, h, x, y, mid).  `side` names the CARD edge the
        arrow gutter sits on, w/h include that gutter, and `mid` is the tip
        position in screen coordinates along the shared axis - y for a
        left/right gutter, x for top/bottom.

        The side is chosen by ROOM, not by a fixed order, and the card is
        then clamped twice: to the window, and again so that the target's
        center still falls inside the gutter's usable span.  That second
        clamp is what makes the arrow point at the thing rather than at the
        corner nearest it.
        """
        cw0, ch0 = self._card_wh
        wx, wy, ww, wh = win
        if rect is None:
            return ("none", cw0, ch0,
                    wx + (ww - cw0) // 2, wy + (wh - ch0) // 2, None)
        tx, ty, tw, th = rect
        # aim at the part of the target that is actually on the window
        ax0, ay0 = max(wx, tx), max(wy, ty)
        ax1 = min(wx + ww, tx + tw)
        ay1 = min(wy + wh, ty + th)
        cx_t = (ax0 + max(ax0, ax1)) // 2
        cy_t = (ay0 + max(ay0, ay1)) // 2

        room = {"beside_right": (wx + ww) - (tx + tw),
                "beside_left": tx - wx,
                "below": (wy + wh) - (ty + th),
                "above": ty - wy}
        need = {"beside_right": cw0 + ARROW + self.GAP,
                "beside_left": cw0 + ARROW + self.GAP,
                "below": ch0 + ARROW + self.GAP,
                "above": ch0 + ARROW + self.GAP}
        order = sorted(room, key=lambda k: -room[k])
        pick = None
        for k in order:
            if room[k] >= need[k]:
                pick = k
                break
        if pick is None:
            pick = order[0]

        if pick in ("beside_right", "beside_left"):
            side = "left" if pick == "beside_right" else "right"
            cw, ch = cw0 + ARROW, ch0
            if side == "left":                     # card sits to the RIGHT
                x = tx + tw + self.GAP
            else:
                x = tx - cw - self.GAP
            x = max(wx, min(x, wx + ww - cw))
            y = cy_t - ch // 2
            y = max(wy, min(y, wy + wh - ch))
            lo, hi = y + ARROW + 2, y + ch - ARROW - 2
            if cy_t < lo:
                y -= (lo - cy_t)
            elif cy_t > hi:
                y += (cy_t - hi)
            # staying on the window wins over a perfectly centerd tip: a
            # card half off the screen is worse than an arrow two pixels
            # short of the middle of a very tall target
            y = max(wy, min(y, wy + wh - ch))
            mid = max(y + ARROW + 2, min(cy_t, y + ch - ARROW - 2))
            return (side, cw, ch, x, y, mid)

        side = "top" if pick == "below" else "bottom"
        cw, ch = cw0, ch0 + ARROW
        if side == "top":                          # card sits BELOW
            y = ty + th + self.GAP
        else:
            y = ty - ch - self.GAP
        y = max(wy, min(y, wy + wh - ch))
        x = cx_t - cw // 2
        x = max(wx, min(x, wx + ww - cw))
        lo, hi = x + ARROW + 2, x + cw - ARROW - 2
        if cx_t < lo:
            x -= (lo - cx_t)
        elif cx_t > hi:
            x += (cx_t - hi)
        x = max(wx, min(x, wx + ww - cw))
        mid = max(x + ARROW + 2, min(cx_t, x + cw - ARROW - 2))
        return (side, cw, ch, x, y, mid)

    def _pack_arrow(self, side):
        """Repack gutter then body, in that order: pack order is allocation
        order, and a body packed first with expand=True would leave the
        gutter nothing to sit in."""
        cv = self._arrow_cv
        holder = self._holder
        if not _alive(cv) or not _alive(holder):
            return
        try:
            cv.pack_forget()
            holder.pack_forget()
            if side in ("left", "right"):
                cv.configure(width=ARROW, height=1)
                cv.pack(side=side, fill="y")
            elif side in ("top", "bottom"):
                cv.configure(width=1, height=ARROW)
                cv.pack(side=side, fill="x")
            holder.pack(side="left", fill="both", expand=True)
        except tk.TclError:
            pass

    def _draw_arrow(self, side, cw, ch, mid):
        """The triangle on the card edge, its tip ON the target's center."""
        cv = self._arrow_cv
        if not _alive(cv):
            return
        try:
            cv.delete("all")
        except tk.TclError:
            return
        if side == "none" or mid is None:
            return
        try:
            ac = self.app._brand()["ac2"]
        except Exception:
            ac = "#c07020"
        a, half = ARROW, ARROW // 2
        cx, cy = self._card_xy()
        if side in ("left", "right"):
            m = mid - cy                      # canvas y == card y
            if side == "left":
                pts = [a, m - half, a, m + half, 0, m]
            else:
                pts = [0, m - half, 0, m + half, a, m]
        else:
            m = mid - cx
            if side == "top":
                pts = [m - half, a, m + half, a, m, 0]
            else:
                pts = [m - half, 0, m + half, 0, m, a]
        try:
            cv.create_polygon(*pts, fill=ac, outline=ac)
        except tk.TclError:
            pass

    def _card_xy(self):
        try:
            return (self.card.winfo_rootx(), self.card.winfo_rooty())
        except (tk.TclError, AttributeError):
            return (0, 0)

    def arrow_tip(self):
        """(axis, screen coordinate) of the arrow's tip, or None.

        The verification hook: a step's tip has to sit on its target's
        center along the shared axis.  Exposed rather than inferred from
        pixels so the check is exact.
        """
        if self._side == "none" or self._arrow_mid is None:
            return None
        axis = "y" if self._side in ("left", "right") else "x"
        return (axis, self._arrow_mid)

    # -- the callout card -----------------------------------------------
    def _build_shell(self):
        """The callout, built ONCE.

        The old tour destroyed and rebuilt this Toplevel on every step,
        which is a window unmap and remap per Next - the single biggest
        source of the flicker.  Now only the words inside it change.
        """
        app = self.app
        uibg = app._theme_palette()[0]
        win = tk.Toplevel(app.root)
        self.card = win
        win.withdraw()
        win.overrideredirect(True)
        try:
            win.attributes("-topmost", True)
        except tk.TclError:
            pass
        win.configure(background=uibg)

        self._wrap = ttk.Frame(win)
        self._wrap.pack(fill="both", expand=True)
        self._arrow_cv = tk.Canvas(self._wrap, width=ARROW, height=ARROW,
                                   highlightthickness=0, bd=0,
                                   background=uibg)
        self._holder = ttk.Frame(self._wrap)
        self._holder.pack(side="left", fill="both", expand=True)

        # grow="both", NOT "x": the body window then follows the card's
        # ACTUAL height, so the two button rows - packed side="bottom"
        # first - always get their space and the prose is what gives way.
        # With grow="x" the card sized itself from a body reqheight that
        # the packer had not recomputed yet, the Toplevel came out short,
        # and the whole footer fell outside the window with no way to
        # advance the tour (Nhan, step 1, New Mexico at text size 10).
        card = app._card(self._holder, grow="both")
        card.pack(fill="both", expand=True)
        self._card_w = card
        hdr = app._lf_header(card, "", icon="book")
        card.set_title(hdr)
        kids = [k for k in hdr.winfo_children() if _alive(k)]
        self._title_lbl = kids[-1] if kids else None
        body = card.body
        muted = app._muted_fg()

        # The card is a FIXED width, so the wrap measure is exact: the
        # BrandCard insets its body by `pad` on each side and the label
        # fills it.  The old tour wrapped six ems short of that and hard
        # wrapped the prose on top, which is where the dead column on the
        # right of every step came from.
        self._card_pad = int(getattr(card, "pad", 8))
        self._wrapln = _box_px(app, CARD_CHARS) - 2 * self._card_pad - 2

        # sacrificial-last-packed (rule 14): the two button rows claim
        # their space before the prose can push them off the card
        # Buttons pack FIRST and to the right; the one stretchy thing on
        # each row (the progress line, the chapter box) packs last and is
        # the one allowed to truncate (rule 13 / 14).
        bar2 = self._bar2 = ttk.Frame(body)
        bar2.pack(side="bottom", fill="x", pady=(10, 0))
        self._next_btn = app._brand_button(bar2, "Next",
                                           lambda: self._nav(+1))
        self._next_btn.pack(side="right")
        self._prev_btn = app._brand_button(bar2, "Previous",
                                           lambda: self._nav(-1),
                                           tier="secondary")
        self._prev_btn.pack(side="right", padx=(0, PAD_BTN))
        app._brand_button(bar2, "Exit", self.stop,
                          tier="tertiary").pack(side="right",
                                                padx=(0, PAD_BTN))
        self._prog_lbl = app._lbl(bar2, text="", foreground=muted,
                                  anchor="w")
        self._prog_lbl.pack(side="left", fill="x", expand=True)

        bar1 = self._bar1 = ttk.Frame(body)
        bar1.pack(side="bottom", fill="x", pady=(8, 0))
        self._skip_btn = app._brand_button(bar1, "Skip this part",
                                           self._skip_chapter,
                                           tier="tertiary")
        self._skip_btn.pack(side="right")
        app._lbl(bar1, text="Jump to").pack(side="left", padx=(0, PAD_BTN))
        self._chap_var = tk.StringVar(value="")
        self._chap_cb = ttk.Combobox(bar1, textvariable=self._chap_var,
                                     state="readonly",
                                     values=list(self.chapters))
        self._chap_cb.pack(side="left", fill="x", expand=True)
        self._chap_cb.bind("<<ComboboxSelected>>", self._on_chapter_pick)

        self._prose = app._lbl(body, text="", justify="left",
                               wraplength=self._wrapln)
        self._prose.pack(anchor="w", fill="x")
        self._hint = app._lbl(body, text="", foreground=muted,
                              justify="left", wraplength=self._wrapln)
        self._hint.pack(anchor="w", fill="x", pady=(8, 0))
        # ONE action button for the whole tour, re-lettered per step: the
        # old code destroyed and rebuilt it, which leaked dead widgets into
        # app._brand_btns (they are re-tinted on every theme switch) and
        # churned widgets on a window that must not flicker.
        self._arow = ttk.Frame(body)
        self._act_btn = app._brand_button(self._arow, "", lambda: None,
                                          tier="secondary")
        self._act_btn.pack(side="left")
        self._act_fn = None

        try:
            app._iconize_buttons(win)
        except Exception:
            pass
        self._tagify(win)

    # -- how tall the card has to be -------------------------------------
    @staticmethod
    def _pady(widget):
        """The vertical padding pack was given, as a total."""
        try:
            v = widget.pack_info().get("pady", 0)
        except Exception:
            return 0
        if isinstance(v, (tuple, list)):
            return sum(int(x) for x in v)
        s = str(v).split()
        try:
            if len(s) >= 2:
                return int(s[0]) + int(s[1])
            return 2 * int(s[0])
        except ValueError:
            return 0

    def _stack_height(self, widgets):
        return sum(w.winfo_reqheight() + self._pady(w)
                   for w in widgets if _alive(w))

    def _chrome_height(self):
        """Title + the two button rows + the card's own insets.

        The floor the card may never go below, because these are the only
        parts a reader cannot do without.
        """
        card = self._card_w
        pad = self._card_pad
        try:
            top = card._top_inset()
        except Exception:
            top = pad
        return top + pad + 2 + self._stack_height([self._bar1, self._bar2])

    def _measure_height(self):
        """The card's height, from REAL requested sizes, measured now.

        Summed child by child rather than read off the body frame: a frame
        caches its requested height until the packer runs again, so asking
        it right after the text changed answers for the PREVIOUS step -
        which is exactly how a card came out too short to show its own
        buttons.  update_idletasks() first, so every child has re-measured
        itself against the new wraplength.
        """
        app = self.app
        card = self._card_w
        pad = self._card_pad
        try:
            self.card.update_idletasks()
        except tk.TclError:
            pass
        try:
            top = card._top_inset()
        except Exception:
            top = pad
        try:
            kids = list(card.body.pack_slaves())
        except tk.TclError:
            kids = []
        need = top + self._stack_height(kids) + pad + 2
        # never taller than most of the window, and never shorter than the
        # chrome: a clamp takes its pixels out of the prose, never out of
        # the buttons (the body is packed bottom-first for that reason)
        win = self._rect_of(app.root) or (0, 0, 800, 600)
        hard = max(self._chrome_height() + app._em() * 2, 120)
        cap = max(hard, int(win[3] * 0.85))
        return max(hard, min(need, cap))

    # -- is it actually clickable? ---------------------------------------
    @staticmethod
    def _centre(widget):
        try:
            return (widget.winfo_rootx() + widget.winfo_width() // 2,
                    widget.winfo_rooty() + widget.winfo_height() // 2)
        except tk.TclError:
            return None

    def hit_test(self, widget):
        """The widget Tk says is under `widget`'s own centre point.

        `winfo_containing` answers across the whole application, other
        Toplevels included, so a scrim strip lying over the callout shows
        up here as the strip.  This is the only honest test of 'can the
        user click this' short of moving the mouse.
        """
        pt = self._centre(widget)
        if pt is None or not _alive(self.card):
            return None
        try:
            return self.card.winfo_containing(pt[0], pt[1])
        except tk.TclError:
            return None

    def clickable(self, widget):
        """True when `widget` (or a child of it) is what a click would hit."""
        got = self.hit_test(widget)
        if got is None:
            return False
        try:
            return str(got) == str(widget) or str(got).startswith(
                str(widget) + ".")
        except Exception:
            return False

    def controls(self):
        """The card controls a reader has to be able to press right now."""
        out = [self._next_btn, self._chap_cb, self._skip_btn, self._prev_btn]
        if self._act_label and _alive(self._act_btn):
            out.append(self._act_btn)
        return [w for w in out if _alive(w) and w.winfo_ismapped()]

    def _ensure_clickable(self):
        """Runtime guard: if some other window is on top of the callout's
        Next button, raise the callout and look again.

        `winfo_containing` returning None is INCONCLUSIVE, not "covered":
        Windows skips a fully transparent layered window when it resolves a
        point, and a window without -topmost can answer None too.  Treating
        None as a failure made the guard lift on every 250 ms tick and
        write a log line each time ("covered by 'None'").  So None only
        re-asserts -topmost, once, and says nothing.

        Anything it does say is said ONCE PER STEP and only when the state
        actually changes.
        """
        if not _alive(self.card):
            return True
        try:
            if not self.card.winfo_ismapped():
                return True
        except tk.TclError:
            return True
        btn = self._next_btn
        if not _alive(btn):
            return True
        got = self.hit_test(btn)
        if got is None:
            # inconclusive. Make sure the callout is topmost so the test can
            # answer next time, and do it at most once per step.
            if self._stack_state != "unknown":
                self._stack_state = "unknown"
                for w in ([self.card] + list(self.spot.strips if self.spot
                                             else [])):
                    try:
                        w.attributes("-topmost", True)
                    except tk.TclError:
                        pass
                # and put the card above the strips once, blind: when the
                # test cannot answer, the cheap guess is the one that
                # would fix the only cover we could have caused ourselves
                self._lift_card()
            return True
        if self.clickable(btn):
            self._stack_state = "ok"
            return True
        try:
            self.card.lift()
            self.card.update_idletasks()
        except tk.TclError:
            return False
        if self.clickable(btn):
            self._stack_state = "ok"
            return True
        if self._stack_state != "covered":
            self._stack_state = "covered"
            try:
                self.app._logline(
                    "Tour: another window (%s) is sitting over the callout "
                    "and it will not come forward. Esc leaves the tour; "
                    "About > 'Welcome & tour...' reopens it."
                    % (str(self.hit_test(btn)),))
            except Exception:
                pass
        return False

    def _footer_ok(self):
        """(fits, footer bottom, card bottom) in screen coordinates.

        The verification hook for the one failure a reader cannot recover
        from: buttons outside the window.
        """
        try:
            cb = self.card.winfo_rooty() + self.card.winfo_height()
            fb = self._bar2.winfo_rooty() + self._bar2.winfo_height()
        except tk.TclError:
            return (True, 0, 0)
        return (fb <= cb + 1, fb, cb)

    def _on_chapter_pick(self, _e=None):
        name = self._chap_var.get()
        if name and name != self.steps[self.i].chapter:
            self._jump_to(name)

    def _show(self, step, rect, owner=None):
        """Re-word the card for one step. No window is created or destroyed
        here, which is what keeps a step change from flashing."""
        app = self.app
        if self._title_lbl is not None and _alive(self._title_lbl):
            self._title_lbl.configure(text=step.title)
        # re-derive rather than reuse: the app text size AND the UI face
        # can both change under a running tour (the theme box is one of
        # the controls the tour points at), so the card's width, its
        # inset and its wrap are all measured fresh here - nothing about
        # the geometry survives from build time.
        self._card_pad = int(getattr(self._card_w, "pad", self._card_pad))
        _cw = _box_px(app, CARD_CHARS)
        self._wrapln = _cw - 2 * self._card_pad - 2
        self._prose.configure(text=step.body, wraplength=self._wrapln)
        self._hint.configure(wraplength=self._wrapln)

        n = len(self.steps)
        self._prog_lbl.configure(
            text="%s  -  %d / %d" % (step.chapter or "Tour", self.i + 1, n))
        if self._chap_var.get() != (step.chapter or ""):
            self._chap_var.set(step.chapter or "")
        self._next_btn.configure(text=("Done" if self.i == n - 1 else "Next"))
        # Fail-open by construction: EVERY step begins with Next live.
        # A gated step may take it back, but only through _arm_gate
        # below, which cannot leave it dark for more than PATIENCE.
        # Without this reset a disabled Next survived the step change:
        # close the smoothing dialog and the watchdog walked the tour on
        # to the next step, which has no gate, so nothing ever asked for
        # the button back, and the tour was wedged for good (Nhan,
        # round 4, steps 26 and 31; that step was 'defringe' then and is
        # 'traces' since R10 retired the Defringe card).
        try:
            self._next_btn.configure(state="normal")
        except tk.TclError:
            pass
        try:
            self._prev_btn.configure(
                state=("disabled" if self.i == 0 else "normal"))
        except tk.TclError:
            pass
        last_chapter = all(s.chapter == step.chapter
                           for s in self.steps[self.i:])
        try:
            self._skip_btn.configure(
                state=("disabled" if last_chapter else "normal"))
        except tk.TclError:
            pass

        # The hint line is always on screen: a waiting step says what it is
        # waiting for, and a step that needs nothing says so, which is what
        # makes the accent Next button read as the way forward rather than
        # as one of four buttons.
        self._act_note = ""            # a new step, a clean hint line
        if step.wait is not None and step.wait_hint:
            self._hint.configure(text=step.wait_hint)
        else:
            self._hint.configure(text="Press Next to carry on.")

        # the action row: re-lettered, never rebuilt
        self._arow.pack_forget()
        label = step.action[0] if step.action else None
        self._act_label = label
        if label:
            fn = self._act_fn = step.action[1]
            try:
                self._act_btn.configure(
                    text=label, command=lambda f=fn: self._do_action(f))
            except tk.TclError:
                pass
            self._arow.pack(fill="x", pady=(10, 0))

        # measure with the gutter OFF. Left packed, a top/bottom gutter is
        # counted in the requested height and _card_spot then adds another
        # one, so a card that lands below two targets in a row grows by
        # ARROW every time. _place repacks it a moment later.
        self._pack_arrow("none")
        self._grew = False
        self._stack_state = "ok"
        self._card_wh = (_cw, self._measure_height())
        self._ungrab(step)
        self._place(rect, owner)
        try:
            if self.card.state() != "normal":
                self.card.deiconify()
                self.card.lift()
        except tk.TclError:
            pass
        # winfo_containing only answers for mapped windows, so the hit test
        # belongs here - after the card is really on screen - not in _place
        self._ensure_clickable()
        self._arm_gate(step)

    def _do_action(self, fn):
        try:
            fn(self.app)
        except Exception as e:
            try:
                self.app._logline("Tour action failed: %r" % e)
            except Exception:
                pass
        self.app.root.after(120, self._reposition)

    def say(self, text):
        """An action button's own answer to the reader.

        A 'do it for me' that CANNOT do it - no peak on this trace, a
        window already closed - must say so, and say it where the reader
        is looking rather than in the Progress log.  The note is kept so
        the gate poll below does not paint the old hint back over it a
        fifth of a second later, and it is dropped when the step changes.
        """
        self._act_note = str(text or "")
        if _alive(self._hint):
            try:
                self._hint.configure(text=self._act_note)
            except Exception:
                pass

    def _lift_card(self):
        try:
            if _alive(self.card):
                self.card.lift()
        except tk.TclError:
            pass

    def _recover(self, step, exc):
        """A step whose _show raised is still a step you can leave.

        Whatever half-painted, three things must hold afterwards: the
        card is on screen, Next is live, and the gate timers of the
        step before are not still running against this one.
        """
        self._log_once(step, "Tour: the '%s' step hit a snag (%r); "
                       "Next stays live, carry on."
                       % (step.key, exc))
        self._cancel_gate()
        try:
            if self.card is not None and self.card.state() != "normal":
                self.card.deiconify()
        except tk.TclError:
            pass
        self._lift_card()
        try:
            self._next_btn.configure(state="normal")
        except Exception:
            pass

    # A gate is an invitation, never a trap: after PATIENCE the step
    # unlocks anyway and the hint says so.  A reader who cannot find the
    # peak we asked them to click must not be stuck with Skip-the-chapter
    # as their only way forward.
    PATIENCE = 30                       # x 400 ms = 12 seconds

    def _log_once(self, step, msg):
        """One line in the Progress log per step, never a stream."""
        if step.key in self._logged:
            return
        self._logged.add(step.key)
        try:
            self.app._logline(msg)
        except Exception:
            pass

    def _gate_ok(self, step):
        """Is the 'now you try it' done?  An erroring check counts as
        done: a predicate is a courtesy, never a lock."""
        if step.wait is None:
            return True
        try:
            return bool(step.wait(self.app))
        except Exception as e:
            self._log_once(step, "Tour: the '%s' step could not check "
                           "your progress (%r), so it is taking your "
                           "word for it." % (step.key, e))
            return True

    def _arm_gate(self, step):
        """Start a step's gate: the poll, plus the PATIENCE unlock.

        The two timers are independent on purpose.  The poll chain can
        die of a thousand cuts - and every cut is caught below - but
        the unlock must not depend on that chain surviving at all.  It
        is armed HERE, unconditionally, for every gated step: whatever
        the pre-action did, whatever the predicate does, a gate can
        hold Next for at most PATIENCE x 400 ms.
        """
        self._cancel_gate()
        self._unlocked = False
        if step.wait is None:
            return                     # nothing gated; Next is already live
        try:
            self._unlock_job = self.app.root.after(
                self.PATIENCE * 400, lambda: self._force_unlock(step))
        except Exception:
            return                     # cannot run timers: Next stays live
        self._poll_wait(step)

    def _cancel_gate(self):
        for name in ("_wait_job", "_unlock_job"):
            job = getattr(self, name, None)
            if job is not None:
                try:
                    self.app.root.after_cancel(job)
                except Exception:
                    pass
                setattr(self, name, None)

    def _force_unlock(self, step):
        """PATIENCE ran out: the gate opens no matter what."""
        self._unlock_job = None
        if not self.steps or self.steps[self.i] is not step:
            return                     # a different step owns the card now
        self._unlocked = True
        try:
            self._next_btn.configure(state="normal")
        except Exception:
            pass
        base = self._act_note or step.wait_hint
        if _alive(self._hint) and base:
            try:
                self._hint.configure(
                    text=base + "  (or just press Next and we will move on)")
            except Exception:
                pass

    def _poll_wait(self, step, tries=0):
        """Hold Next until a 'now you try it' step is actually done.

        Fail-open at every joint: a predicate that raises counts as done
        (_gate_ok), a button that cannot be reached ends the gating
        rather than the tour, a reschedule that fails hands over to
        _force_unlock, and the PATIENCE unlock itself lives on its own
        timer in _arm_gate, where nothing here can starve it.
        """
        if self._wait_job is not None:
            try:
                self.app.root.after_cancel(self._wait_job)
            except Exception:
                pass
            self._wait_job = None
        if step.wait is None or self._next_btn is None:
            return
        if not self.steps or self.steps[self.i] is not step:
            return                     # we have moved on since this was armed
        ok = self._gate_ok(step)
        patient = self._unlocked or tries >= self.PATIENCE
        try:
            self._next_btn.configure(
                state=("normal" if (ok or patient) else "disabled"))
        except Exception:
            ok = True                  # cannot hold what we cannot reach
        if _alive(self._hint):
            if ok:
                hint = "Nicely done. Press Next to carry on."
            else:
                hint = self._act_note or step.wait_hint
                if patient:
                    hint += "  (or just press Next and we will move on)"
            try:
                self._hint.configure(text=hint)
            except Exception:
                pass
        if ok and self._follows_into_dialog(step):
            return                     # advancing; stop polling
        if not ok:
            try:
                self._wait_job = self.app.root.after(
                    400, lambda: self._poll_wait(step, tries + 1))
            except Exception:
                self._force_unlock(step)

    def _follows_into_dialog(self, step):
        """Walk on by ourselves when the reader opens the dialog we were
        about to show them.

        The hands-on steps ask you to press a button that opens a dialog,
        and the next step lives INSIDE it.  Making you then find and press
        Next as well - on a card that has just been covered by a modal
        window - is the opposite of 'everything flows'.  So when the next
        step's dialog is up and we are not already in it, the tour follows
        you in.
        """
        if not self._auto_ok:
            return False               # the reader just walked BACKWARD
        j = self.i + 1
        if j >= len(self.steps):
            return False
        nxt = self.steps[j]
        if not nxt.dialog or nxt.dialog == step.dialog:
            return False
        if find_dialog(self.app, nxt.dialog) is None:
            return False
        self._wait_job = self.app.root.after(350, lambda: self._nav(+1))
        return True


def start_tour(app):
    """Public entry point: run the guided tour from the beginning."""
    return Tour(app).start()


# ---------------------------------------------------------------------------
# 7. The welcome card
# ---------------------------------------------------------------------------
WELCOME_LEAD = "A short guided tour of SPARTA."

WELCOME_BODY = (
    "SPARTA turns a folder of raw grating segments into absorbance spectra "
    "and a figure for a paper. Point it at the folder and press Run: SPARTA "
    "joins, computes and plots every measurement.\n\n"
    "The tour walks that path in the window itself. The program dims around "
    "whatever is being explained, and the real controls stay clickable.\n\n"
    "The chapters are short and any of them can be skipped. Esc leaves at "
    "any point. A small demo dataset is bundled in."
)


def _contrast(app, color, on):
    """WCAG contrast ratio between two Tk colors, or None if unreadable."""
    try:
        c1 = app.root.winfo_rgb(color)
        c2 = app.root.winfo_rgb(on)
    except Exception:
        return None

    def lum(rgb):
        out = []
        for v in rgb:
            v = (v / 65535.0)
            out.append(v / 12.92 if v <= 0.03928
                       else ((v + 0.055) / 1.055) ** 2.4)
        return 0.2126 * out[0] + 0.7152 * out[1] + 0.0722 * out[2]

    a, b = lum(c1), lum(c2)
    hi, lo = max(a, b), min(a, b)
    return (hi + 0.05) / (lo + 0.05)


def wordmark_dot_color(app):
    """The accent for the wordmark's period, guaranteed legible.

    The dot is ac2, derived per theme like every other accent (rule 4).
    High Contrast, though, is not allowed dimmed chrome (rule 48), and a
    novelty theme can put ac2 close to its own ground; either way the
    logo would wash out.  So the derived color is CHECKED against the
    ground it lands on and falls back to the theme's own foreground when
    it cannot carry itself.
    """
    try:
        uibg, fg = app._theme_palette()[:2]
        ac2 = app._brand()["ac2"]
    except Exception:
        return None
    r = _contrast(app, ac2, uibg)
    if r is None or r < 3.0:
        return fg
    return ac2


def maybe_show_welcome(app):
    """First-run hook. No-op once the user has ticked 'Don't show again'."""
    try:
        if app.settings.get("welcome_seen"):
            return None
    except Exception:
        return None
    return show_welcome(app)


def show_welcome(app):
    """The welcome card. Also About > 'Welcome & tour...'."""
    win = tk.Toplevel(app.root)
    win.title("Welcome")
    try:
        win.transient(app.root)
    except tk.TclError:
        pass
    # width in characters of the ACTIVE face, height off the ACTIVE line
    # height: both move when a Dyslexic theme swaps the typeface, and the
    # old digit-em numbers moved with neither (R5 item 1)
    W = _box_px(app, WELCOME_CHARS)
    try:
        _lh = app._F(0).metrics("linespace")
    except Exception:
        _lh = 20
    app._center_on_root(win, W, _lh * 20)
    app._apply_titlebar(win)
    win.bind("<Escape>", lambda e: win.destroy())

    ic = getattr(app, "_icons", {})
    hdr = ttk.Frame(win, padding=(14, 12, 14, 4))
    hdr.pack(fill="x")
    _markw = 0
    if ic.get("mark_lg") is not None:
        tk.Label(hdr, image=ic["mark_lg"], bd=0,
                 background=app._theme_palette()[0]).pack(side="left",
                                                          padx=(0, 12))
        try:
            _markw = ic["mark_lg"].width() + 12
        except Exception:
            _markw = 0
    hcol = ttk.Frame(hdr)
    hcol.pack(side="left", fill="x", expand=True)
    wrow = ttk.Frame(hcol)
    wrow.pack(anchor="w")
    app._lbl(wrow, text=brand(app, "wordmark", "sparta"),
             font=app._F(12, semi=True)).pack(side="left")
    app._lbl(wrow, text=brand(app, "dot", "."),
             font=app._F(12, "bold", semi=True),
             foreground=wordmark_dot_color(app)).pack(side="left")
    # the lead sits beside the mark, so its wrap is the dialog minus the
    # mark's REAL width - measured, not an em allowance that only ever
    # matched one typeface
    lead = app._lbl(hcol, text=WELCOME_LEAD, font=app._F(1),
                    justify="left",
                    wraplength=max(140, W - 2 * 14 - _markw - 8))
    lead.pack(anchor="w")

    outer = ttk.Frame(win, padding=(14, 6, 14, 10))
    outer.pack(fill="both", expand=True)
    card = app._card(outer, grow="x")
    card.pack(fill="x")
    card.set_title(app._lf_header(card, "What the tour does", icon="book"))
    pad = int(getattr(card, "pad", 8))
    app._lbl(card.body, text=WELCOME_BODY, justify="left",
             wraplength=max(140, W - 2 * 14 - 2 * pad - 4)).pack(
                 anchor="w", fill="x")

    again = tk.BooleanVar(value=bool(app.settings.get("welcome_seen")))
    cb = ttk.Checkbutton(outer, text="Don't show this again",
                         variable=again)
    cb.pack(anchor="w", pady=(10, 0))

    bar = ttk.Frame(win, padding=(14, 4, 14, 12))
    bar.pack(side="bottom", fill="x")

    def remember():
        app.settings["welcome_seen"] = bool(again.get())
        try:
            app._save_settings()
        except Exception:
            pass

    def close():
        remember()
        win.destroy()

    def do_tour():
        close()
        app.root.after(120, lambda: start_tour(app))

    def do_guide():
        close()
        try:
            app._card_toggle("guide_collapsed", False)
        except Exception:
            pass
        try:
            app.ref_kind.set("Quick start")
        except Exception:
            pass

    b1 = app._brand_button(bar, "Yes, show me around", do_tour)
    b1.pack(side="right")
    b2 = app._brand_button(bar, "Open the guide", do_guide, tier="secondary")
    b2.pack(side="right", padx=(0, PAD_BTN))
    b3 = app._brand_button(bar, "Just explore", close, tier="tertiary")
    b3.pack(side="right", padx=(0, PAD_BTN))
    try:
        app._iconize_buttons(win)
    except Exception:
        pass
    # size to the content: the copy is longer than the old card's and a
    # fixed height clipped the button bar at app text size 15
    try:
        win.update_idletasks()
        need = win.winfo_reqheight()
        app._center_on_root(win, W, max(_lh * 13, need))
    except tk.TclError:
        pass
    return win
