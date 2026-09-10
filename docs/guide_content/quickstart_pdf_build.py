"""
quickstart_pdf_build.py  --  build docs/QUICKSTART.pdf from the guide content.

Reads the plain-text markdown in docs/guide_content/ and typesets it with
matplotlib's PdfPages: no new dependencies, and the same font stack the
figures already use.

Layout rules (they mirror the on-screen guide's own contract):
  - a line at column 0 that is ALL CAPS and starts with a letter is a heading
  - a line indented six spaces or more is set in a monospaced face only when
    it is a table row or a verbatim shape (see mono_line_flags); a wrapped
    continuation at that indent is prose and sets in Arial like its item
  - HTML comments are editorial and never reach the page
  - source lines are already wrapped at or under 72 characters, so one
    source line is one printed line

Usage:
    python docs/guide_content/quickstart_pdf_build.py
    python docs/guide_content/quickstart_pdf_build.py --version v1.4.10
    python docs/guide_content/quickstart_pdf_build.py --out somewhere.pdf

NQT / Lee Lab -- Aug 2026
"""

import argparse
import datetime
import os
import re
import sys

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.backends.backend_pdf import PdfPages


HERE = os.path.dirname(os.path.abspath(__file__))
DOCS = os.path.abspath(os.path.join(HERE, ".."))
ROOT = os.path.abspath(os.path.join(DOCS, ".."))

# --- brand -----------------------------------------------------------------
# The name lives in app.py's BRAND dict; these are the display copies the
# cover needs. Keep them in step with BRAND if that ever changes.
WORDMARK = "sparta"
DOT = "."
EXPANSION = "SPectroscopic Absorption, Real Time Analysis"
SUBTITLE = "Concatenator · Absorbance Calculator · Plotter"
ORG = "NSLS-II 22-IR-1  —  Dr. Lee's Lab"
ACCENT = "#1D3EC0"          # a neutral, print-safe brand blue
INK = "#1c2530"
MUTED = "#6b7480"

_SANS_PREFS = ["Arial", "Helvetica", "Liberation Sans", "DejaVu Sans"]
_MONO_PREFS = ["Consolas", "Courier New", "Liberation Mono", "DejaVu Sans Mono"]


def _resolve(prefs):
    """The first preferred family this machine actually has.

    Handing matplotlib the whole list works, but it logs a findfont warning
    for every family it has to walk past; resolving once keeps the build
    output clean and makes the substitution visible in one place.
    """
    try:
        from matplotlib import font_manager
        have = {f.name for f in font_manager.fontManager.ttflist}
    except Exception:
        return prefs[-1]
    for fam in prefs:
        if fam in have:
            return fam
    return prefs[-1]


SANS = _resolve(_SANS_PREFS)
MONO = _resolve(_MONO_PREFS)

# --- page geometry, in inches ---------------------------------------------
PAGE_W, PAGE_H = 8.5, 11.0
M_L, M_R, M_T, M_B = 1.05, 0.95, 1.00, 0.95

BODY_PT = 10.0
MONO_PT = 9.0
HEAD_PT = 11.5

LEAD = 0.192                 # inches between body baselines
LEAD_BLANK = 0.105           # a blank source line
LEAD_HEAD_ABOVE = 0.22
LEAD_HEAD_BELOW = 0.085

TEXT_H = PAGE_H - M_T - M_B
# The source is wrapped at 72 characters, which at 10 pt Arial is about
# 5.4 in. Rules are drawn to the real measure rather than to the page
# width, so the block reads as a deliberate narrow column instead of as a
# short line inside a wide one.
MEASURE = 5.55

# Which content files go in the PDF, and what each is called on the
# contents page.
SECTIONS = [
    ("00_quick_start.md", "Quick start"),
    ("11_naming_system.md", "The naming system"),
    ("40_workflows.md", "Workflows"),
    ("50_shortcuts.md", "Keyboard shortcuts"),
]

# Files whose every line is column-aligned and must be set monospaced.
MONO_FILES = {"50_shortcuts.md"}

COMMENT_RE = re.compile(r"<!--.*?-->", re.S)


def app_version(default="v1.4.10"):
    """APP_VERSION out of app.py, so the cover cannot drift from the build."""
    path = os.path.join(ROOT, "app.py")
    try:
        with open(path, "r", encoding="utf-8", errors="replace") as f:
            for line in f:
                m = re.match(r'\s*APP_VERSION\s*=\s*["\']([^"\']+)["\']', line)
                if m:
                    return m.group(1)
    except OSError:
        pass
    return default


VERBATIM_CHARS = set("=/\\<>{}[]")
LOWER_WORD_RE = re.compile(r"[a-z]{3,}\Z")
DIGIT_RE = re.compile(r"\d")


def _three_lower_words(stripped):
    """True when three plain lowercase words run together: that is prose."""
    run = 0
    for word in stripped.split():
        if LOWER_WORD_RE.match(word):
            run += 1
            if run >= 3:
                return True
        else:
            run = 0
    return False


def _is_verbatim(stripped):
    """True for a formula, a path, a file name or another literal shape."""
    for token in stripped.split():
        if (any(c in VERBATIM_CHARS for c in token)
                or len(DIGIT_RE.findall(token)) >= 2):
            return not _three_lower_words(stripped)
    return False


def mono_line_flags(lines):
    """{index: True} for the deeply indented lines that set monospaced.

    The panel's own rule, mirrored so the PDF and the Guide box break the
    same way. A line indented six spaces or more is aligned material only
    when it is a table row - three or more internal spaces, or two or more
    with a mono sibling at the same indent - or a verbatim shape: a token
    carrying one of = -> / \\ < > { } [ ] or two digits, in a line that is
    not three consecutive lowercase words of prose. Everything else at that
    indent is the wrapped continuation of the item above it, and it sets in
    the body face like the rest of that item.
    """
    flags = {}
    for i, raw in enumerate(lines):
        line = raw.rstrip()
        stripped = line.strip()
        if not stripped or len(line) - len(line.lstrip(" ")) < 6:
            continue
        flags[i] = (re.search(r"\S {3,}\S", line) is not None
                    or _is_verbatim(stripped))
    for i in sorted(flags):
        if flags[i]:
            continue
        line = lines[i].rstrip()
        if re.search(r"\S {2,}\S", line) is None:
            continue
        indent = len(line) - len(line.lstrip(" "))
        for j in (i - 1, i + 1):
            sib = lines[j].rstrip() if 0 <= j < len(lines) else ""
            if flags.get(j) and len(sib) - len(sib.lstrip(" ")) == indent:
                flags[i] = True
                break
    return flags


def load_blocks(path, mono_all=False):
    """One source file as a list of (kind, text) blocks.

    kind is 'h' (heading), 'b' (body), 'm' (monospaced body) or 's' (blank).
    The file's first line is dropped: the contents page supplies the title.
    """
    with open(path, "r", encoding="utf-8") as f:
        text = f.read()
    text = COMMENT_RE.sub("", text)
    lines = text.splitlines()
    if lines:
        lines = lines[1:]                     # the title line
    blocks = []
    mono = mono_line_flags(lines)
    for idx, raw in enumerate(lines):
        line = raw.rstrip()
        if not line.strip():
            blocks.append(("s", ""))
            continue
        indent = len(line) - len(line.lstrip(" "))
        stripped = line.strip()
        # A heading is unindented and all upper case. The honesty gate is
        # stricter (it also demands an alphabetic first character), so a
        # numbered step like '1. RUN' sets as a heading here while staying
        # outside the gate's reach - which is exactly what both want.
        if (indent == 0 and any(c.isalpha() for c in stripped)
                and stripped == stripped.upper()):
            blocks.append(("h", stripped))
        elif mono_all or mono.get(idx):
            blocks.append(("m", line))
        else:
            blocks.append(("b", line))
    # a heading may not be the last thing on a page with nothing under it,
    # and trailing blanks only waste paper
    while blocks and blocks[-1][0] == "s":
        blocks.pop()
    return blocks


def block_height(kind, first_on_page):
    if kind == "s":
        return LEAD_BLANK
    if kind == "h":
        return (0.0 if first_on_page else LEAD_HEAD_ABOVE) + LEAD + LEAD_HEAD_BELOW
    return LEAD


def paginate(sections):
    """Lay every section out into pages.

    Returns (pages, starts) where a page is a list of (kind, text, y_inches
    measured DOWN from the top margin) and starts maps a section title to the
    1-based content page it opens on.
    """
    pages, starts = [], {}
    page, y = [], 0.0

    def flush():
        nonlocal page, y
        if page:
            pages.append(page)
        page, y = [], 0.0

    for path, title in sections:
        flush()                               # every section opens a page
        starts[title] = len(pages) + 1
        page.append(("t", title, y))
        y += 0.42
        blocks = load_blocks(path,
                             mono_all=os.path.basename(path) in MONO_FILES)
        for i, (kind, text) in enumerate(blocks):
            h = block_height(kind, not page)
            if kind == "s" and not page:
                continue                      # never open a page with a blank
            if y + h > TEXT_H:
                flush()
                h = block_height(kind, True)
                if kind == "s":
                    continue
            if kind == "h":
                # a heading with fewer than three lines under it belongs on
                # the next page, not orphaned at the foot of this one
                if y + h + 3 * LEAD > TEXT_H:
                    flush()
                    h = block_height(kind, True)
                y += 0.0 if len(page) == 0 else LEAD_HEAD_ABOVE
                page.append((kind, text, y))
                y += LEAD + LEAD_HEAD_BELOW
            else:
                page.append((kind, text, y))
                y += h
    flush()
    return pages, starts


# --- drawing ---------------------------------------------------------------
def new_page():
    fig = plt.figure(figsize=(PAGE_W, PAGE_H))
    fig.patch.set_facecolor("white")
    return fig


def put(fig, x_in, y_in_from_top, text, size, family, weight="normal",
        color=INK, ha="left", va="top"):
    fig.text(x_in / PAGE_W, 1.0 - (y_in_from_top / PAGE_H), text,
             fontsize=size, family=family, weight=weight, color=color,
             ha=ha, va=va)


def rule(fig, x_in, y_in_from_top, w_in, h_pt=2.0, color=ACCENT):
    """A Bauhaus rule: a filled bar, not a line artist."""
    h_in = h_pt / 72.0
    fig.add_artist(
        plt.Rectangle((x_in / PAGE_W, 1.0 - (y_in_from_top + h_in) / PAGE_H),
                      w_in / PAGE_W, h_in / PAGE_H,
                      transform=fig.transFigure, facecolor=color,
                      edgecolor="none", zorder=3))


def text_width_in(fig, artist):
    """The drawn width of a text artist, in inches. Needs a renderer, so
    the figure is drawn once first; Agg makes that cheap and exact, which
    beats a hardcoded offset that breaks the moment Arial is substituted."""
    fig.canvas.draw()
    bb = artist.get_window_extent(renderer=fig.canvas.get_renderer())
    return bb.width / fig.dpi


def draw_cover(pdf, version):
    fig = new_page()
    y = 3.05
    # wordmark: lowercase name, then the accent dot hard against it
    wm = fig.text(M_L / PAGE_W, 1.0 - y / PAGE_H, WORDMARK, fontsize=62,
                  family=SANS, weight="medium", color=INK, ha="left",
                  va="top")
    put(fig, M_L + text_width_in(fig, wm), y, DOT, 62, SANS, weight="bold",
        color=ACCENT)
    y += 1.02
    put(fig, M_L, y, EXPANSION, 12, SANS, color=MUTED)
    y += 0.26
    put(fig, M_L, y, SUBTITLE, 10, SANS, color=MUTED)
    y += 0.55
    rule(fig, M_L, y, 1.6, 3.0)
    y += 0.42
    put(fig, M_L, y, "Quick start guide", 22, SANS, weight="semibold")
    y += 0.44
    # The cover is printed guide prose, so PLAN_R19 section 3 governs it:
    # the agent noun is SPARTA ("the tool" retires, rule 2) and the filler
    # goes (rule 4).
    put(fig, M_L, y,
        "Getting data in, teaching SPARTA your file names,", 11, SANS)
    y += 0.20
    put(fig, M_L, y,
        "and the recipes for the outputs you need.", 11, SANS)

    put(fig, M_L, PAGE_H - 1.55, version, 13, SANS, weight="bold",
        color=ACCENT)
    put(fig, M_L, PAGE_H - 1.30, ORG, 10, SANS, color=MUTED)
    put(fig, M_L, PAGE_H - 1.10,
        "Generated " + datetime.date.today().isoformat(), 9, SANS,
        color=MUTED)
    pdf.savefig(fig)
    plt.close(fig)


def draw_contents(pdf, starts, n_pages):
    fig = new_page()
    put(fig, M_L, M_T, "CONTENTS", HEAD_PT + 3, SANS, weight="bold")
    rule(fig, M_L, M_T + 0.32, MEASURE, 2.0, INK)
    y = M_T + 0.66
    for _path, title in SECTIONS:
        put(fig, M_L, y, title, 12, SANS)
        put(fig, M_L + MEASURE, y, str(starts[title]), 12, SANS, ha="right")
        y += 0.34
    y += 0.30
    put(fig, M_L, y,
        "The same text is in the program: left panel, Guide / notes,", 9.5,
        SANS, color=MUTED)
    y += 0.20
    put(fig, M_L, y,
        "View dropdown. Hover any control for a tip; F1 lists the", 9.5,
        SANS, color=MUTED)
    y += 0.20
    put(fig, M_L, y, "keyboard shortcuts.", 9.5, SANS, color=MUTED)
    y += 0.40
    put(fig, M_L, y, "%d pages" % n_pages, 9.5, SANS, color=MUTED)
    pdf.savefig(fig)
    plt.close(fig)


def draw_page(pdf, page, number, total):
    fig = new_page()
    for kind, text, y in page:
        yy = M_T + y
        if kind == "t":
            put(fig, M_L, yy, text.upper(), HEAD_PT + 4, SANS, weight="bold")
            rule(fig, M_L, yy + 0.30, MEASURE, 2.0, INK)
        elif kind == "h":
            put(fig, M_L, yy, text, HEAD_PT, SANS, weight="bold",
                color=ACCENT)
        elif kind == "m":
            put(fig, M_L, yy, text, MONO_PT, MONO)
        else:
            put(fig, M_L, yy, text, BODY_PT, SANS)
    # footer
    put(fig, M_L, PAGE_H - M_B + 0.42, WORDMARK + DOT + "  quick start",
        8, SANS, color=MUTED)
    put(fig, M_L + MEASURE, PAGE_H - M_B + 0.42, "%d / %d" % (number, total),
        8, SANS, color=MUTED, ha="right")
    pdf.savefig(fig)
    plt.close(fig)


def build(out_path, version):
    for path, _title in SECTIONS:
        full = os.path.join(HERE, path)
        if not os.path.exists(full):
            raise SystemExit("missing content file: %s" % full)
    sections = [(os.path.join(HERE, p), t) for p, t in SECTIONS]
    pages, starts = paginate(sections)
    total = len(pages)
    os.makedirs(os.path.dirname(out_path) or ".", exist_ok=True)
    with PdfPages(out_path) as pdf:
        draw_cover(pdf, version)
        draw_contents(pdf, starts, total)
        for i, page in enumerate(pages, 1):
            draw_page(pdf, page, i, total)
        info = pdf.infodict()
        info["Title"] = "SPARTA quick start guide"
        info["Author"] = "Lee Lab, NSLS-II 22-IR-1"
        info["Subject"] = EXPANSION
        info["Keywords"] = ("diamond anvil cell, absorption spectroscopy, "
                            "SPARTA, " + version)
        info["CreationDate"] = datetime.datetime.now()
    return total + 2


def main():
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[1])
    ap.add_argument("--out", default=os.path.join(DOCS, "QUICKSTART.pdf"))
    ap.add_argument("--version", default=None,
                    help="version string for the cover (default: APP_VERSION "
                         "read from app.py)")
    a = ap.parse_args()
    ver = a.version or app_version()
    n = build(a.out, ver)
    print("wrote %s  (%d pages, %s; text %s, mono %s)"
          % (a.out, n, ver, SANS, MONO))
    return 0


if __name__ == "__main__":
    sys.exit(main())
