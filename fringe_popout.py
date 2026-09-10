"""
fringe_popout.py  --  the workbench pop-out: Matthew's window, SPARTA's paint.

The Fringe tab's "Pop out" cell opens THIS window.  It is a replica of the
original GUI: his sidebar on the left in his order, his 2x2 figure on the
right with the navigation toolbar, his menus.  Only the paint is SPARTA's
-- the theme palette, the card vocabulary, the drawn glyphs and the spacing
constants.  No control moves, no control is renamed, and no behaviour
changes.

    Source module : defringe_dac.py  (launch_fft_gui, :8994-:15903)
    Author        : Matthew R. Diamond
    Repository    : github.com/matthewrdiamond/DAC-Absorption-Fringe-Analysis
    License       : vendored under MIT by permission of the author.

ONE MODEL, TWO VIEWS.  This window owns no state.  Every control writes the
SAME tk variable, or calls the SAME method, that the Fringe tab's card uses,
so an edit in one view is an edit in the model and both views follow it.
Three mechanisms carry that:

  * shared tk variables -- a spinbox here and the spinbox in the tab hold
    one `StringVar`, so they cannot disagree
  * the redraw hook -- `FringeWorkbench._redraw` ends by calling
    `_mirror_popout`; this module binds that name to its own painter, which
    re-runs his `_draw_panel` / `_draw_measured` against this window's axes
  * the sync hooks -- the handful of workbench methods that write a LABEL
    (the solved column, the status lines, the button captions) are wrapped
    while the window is open, and the wrapper copies the tab's text onto
    the twin here

The figure is interactive, as his is.  The mouse handlers are his own; they
run inside `_view()`, which lends the workbench this window's axes and
canvas for the length of the call and gives its own back afterwards.

NQT / Lee Lab -- Aug 2026.
"""

import contextlib
import sys
import tkinter as tk
from tkinter import ttk

from matplotlib.backends.backend_tkagg import (FigureCanvasTkAgg,
                                               NavigationToolbar2Tk)
from matplotlib.figure import Figure

import fringe_materials
import fringe_panel

# The window, in ems, capped by the workbench's own screen cap.  His window
# opens at 98% x 88% of the work area; the cap keeps that honest on a small
# screen (DESIGN_RULES rule 16 -- no literal pixels).
WIN_W_EM = 200
WIN_H_EM = 120
# His input column is 430 px at his 12 pt base.  In ems that is 62, so the
# sash lands in the same place at every text size and DPI scale.
SIDE_EM = 62
# His short centred rule between the index rows and the thickness rows.
SEP_RELW = 0.70

# The [?] windows, the guide and the results grid stay the workbench's own
# singletons; this window only adds one, for the guide it does not carry.
GUIDE_ATTR = "_po_guide"


# ---------------------------------------------------------------------------
# Tooltips.  One fact per line, present tense, under 20 words (R12 register).
# The long-form text stays one click away in View > Info and View > Guide.
# ---------------------------------------------------------------------------
TIPS = {
    "anvil": "Choose the n(lambda) model for the diamond anvil.",
    "medium": "Choose the pressure medium. A named medium follows its own "
              "n(P) model.",
    "layer2": "Turn on for a second layer in the cell.",
    "layer2_cb": "Choose the material of the second layer.",
    "medium_name": "What the medium is called on the rows and the "
                   "schematic. Blank takes the dropdown's name.",
    "sample_name": "What the sample is called on the rows and the "
                   "schematic.",
    "layer2_name": "What the second layer is called. Blank takes the "
                   "dropdown's name.",
    "reset_drop": "Put every input back to its shipped value and take this "
                  "point off the results series.",
    "dp": "The pressure the index models are read at. It fills in from the "
          "loaded spectrum.",
    "calc_n": "Read every modelled index at P, at the fringe window's "
              "centre wavelength.",
    "ambient_n": "Put the anvil on the ambient constant 2.4168.",
    "nd": "The anvil index at this spectrum's pressure. The solve holds it "
          "fixed.",
    "nmed": "The medium index. The solve holds it fixed.",
    "nl2": "The second layer's index, read from its material on every "
           "load. Shown only while Layer 2 is ticked.",
    "ns": "The sample index the model stems use. Fit peaks writes the "
          "solved value here.",
    "d2": "Thickness of the medium above the sample.",
    "t": "Thickness of the sample.",
    "d1": "Thickness of the medium below the sample.",
    "total": "d1 + t + d2. Lock In makes this box the driver.",
    "lock": "Hold the total. The three thicknesses then trade against each "
            "other.",
    "fine": "Step every spinbox at a tenth of the usual pace.",
    "fit_distinct": "Fit the sample rectangle and the sample diamond as "
                    "separate peaks, then solve.",
    "fit_shared": "Fit the sample rectangle as a shoulder on the sample "
                  "diamond, then solve.",
    "plot": "Put the solved values of this pressure point on the results "
            "series.",
    "results": "Open the recorded series against pressure.",
    "load_parent": "Pick a folder that holds series subfolders.",
    "load_raw": "Pick one absorbance CSV. Its folder becomes the working "
                "series.",
    "series_cb": "Pick a series subfolder under the parent.",
    "series_prev": "Go to the previous series folder.",
    "series_next": "Go to the next series folder.",
    "save": "Write the recorded points to series_continuity.json.",
    "load": "Read series_continuity.json back in.",
    "load_file": "Open a saved session by name: a point snapshot or a "
                 "series file.",
    "trace_cb": "Pick a pressure point in this series.",
    "trace_prev": "Go to the previous pressure point.",
    "trace_next": "Go to the next pressure point.",
    "lp_on": "Remove every ripple above the cutoff. This is the main "
             "cleaning tool.",
    "lp_um": "The cutoff for this channel, in micron of n*t.",
    "lp_shape": "The shape of the low-pass edge: tanh, error function or "
                "hard.",
    "lp_roll": "The width the edge rolls off over, in micron of n*t.",
    "clear": "Take every notch off this channel.",
    "export_clean": "Write the cleaned spectrum to CSV.",
    "notch_list": "Open the notch list.",
    "write_notches": "Save notch_overrides.csv for the batch pipeline.",
    "delete_notches": "Delete this spectrum's rows from "
                      "notch_overrides.csv.",
    "fits": "Run the amplitude fitters on the current settings.",
    "history": "Reopen an earlier Compute fits run.",
    "tiers": "Switch the right panels between the flat view and the tiered "
             "view.",
    "clean": "Hide or show the red FFT filtered curve.",
    "bandfloor": "Keep the band integral wider than the FFT main lobe.",
    "csv": "Where the workbench writes its CSV files.",
    "panels": "The View menu opens each panel in its own window.",
    "full_on": "Fill the screen with this window. F11 does the same.",
    "full_off": "Leave full screen. Escape and F11 do the same.",
}


def open_popout(wb):
    """Open the replica for `wb`, or raise the one that is already open.

    `FringeWorkbench.popout` holds the singleton guard and the build call;
    by the time this runs there is no window and the workbench is built.
    """
    view = MatthewWindow(wb)
    return view.open()


class MatthewWindow(object):
    """His window, bound to the tab's model."""

    # The workbench methods that write a mirrored label or caption.  Each is
    # wrapped while the window is open so the twin follows the original.
    HOOKS = ("_status", "_set_solve_status", "_refresh_state_indicators",
             "_sync_action_marks", "_sync_view_buttons",
             "_refresh_series_nav_ui", "_refresh_pressure_nav_ui",
             "_sync_medium_row", "_on_layer2", "_on_lock",
             "on_trace_change", "_solve", "_refresh_series_disk",
             "export_notch_overrides", "_delete_notches_file")

    def __init__(self, wb):
        self.wb = wb
        self.app = wb.app
        self.win = None
        self.tw = {}                 # twin widgets, by key
        self.pw = None
        self.fig = None
        self.canvas = None
        self.tkcanvas = None
        self.toolbar = None
        # no native menubar: the menus ride the window's own top bar, so
        # they take the theme (see _build_topbar)
        self._topbar = None
        self._topbar_rule = None
        self._mbtns = []             # the top bar's menu buttons
        self._menus = []
        self._saved = {}             # the wrapped workbench methods
        self._spins = []             # what this window added to wb._spins
        self._fits = []              # what this window added to wb._fit_btns
        self._boxes = []             # plain tk frames this window retints
        self._slotlist = []          # labels that vanish while empty
        self._in_view = False
        self._pending = None
        self._sync_job = None
        self._relayout_job = None
        self._theme_seen = None
        self._sash_set = False
        self.inner = None
        self._fullscreen = False
        self._geom_normal = None     # the size to come back to, and to save
        self._fs_btn = None
        self._fs_icons = {}
        # this window's half of "two views": its own axes and artists
        self.axes = {}
        self.maxes = {}
        self.twins = {}
        self.artists = {"roles": {}, "lp": {}, "hover": {}}
        self.nt_labels = {}
        self.schem_labels = {}
        self.hover_key = None
        self.cursor_now = None

    # =====================================================================
    # open / close
    # =====================================================================
    def open(self):
        wb, a = self.wb, self.app
        win = tk.Toplevel(a.root)
        win.title("Fringe workbench")
        win.transient(a.root)
        a._center_on_root(win, *wb._dlg_size(WIN_W_EM, WIN_H_EM))
        a._apply_titlebar(win)
        # the size and monitor it was last closed at (fr_popout_geom), held
        # to the screen cap; applied at creation only, as _raise_existing
        # promises
        wb._clamp_geometry(win, wb.settings.get("fr_popout_geom"))
        win.bind("<Escape>", self._on_escape)
        win.bind("<F11>", lambda e: (self.toggle_fullscreen(), "break")[1])
        win.protocol("WM_DELETE_WINDOW", wb._close_popout)
        win.bind("<Destroy>", self._on_destroy, add="+")
        self.win = win
        wb._po_view = self
        self._allow_maximize()
        # the bar first: the menus are buttons on it
        self._build_topbar()
        self._build_menubar()
        self._build_body()
        self._install_hooks()
        # the singleton goes live only once the view can answer a redraw
        wb._popout = win
        a._iconize_buttons(win)
        self._retheme()
        # one full pass paints the tab, then this window, then the labels
        wb._request_redraw(now=True)
        wb.sync_view_switch()
        return win

    def _on_destroy(self, event=None):
        if event is not None and event.widget is not self.win:
            return
        self.close()

    # =====================================================================
    # the top bar -- his menus, and full screen: the button, F11, Escape
    # =====================================================================
    def _build_topbar(self):
        """The strip over the window: his menus at the left end, the full
        screen button at the right end where every other program keeps it.

        Windows paints a NATIVE menubar in the system colours and takes no
        theme from Tk, so `win.configure(menu=...)` laid one white band
        over a themed window.  The bar is a widget instead -- a plain tk
        frame in the panel ground with a Menubutton per menu -- and
        `_retheme` paints it with the rest of the chrome.  The window's own
        geometry is untouched by the swap: the bar packs inside the same
        client area the menubar used, so `_clamp_geometry` and the
        full-screen memory keep the numbers they always had.
        """
        win, a = self.win, self.app
        uibg = a._theme_palette()[0]
        bar = tk.Frame(win, background=uibg, bd=0, highlightthickness=0)
        bar.pack(side="top", fill="x")
        self._topbar = bar
        rule = tk.Frame(bar, height=1, bd=0, background=a._hairline()[1])
        rule.pack(side="bottom", fill="x")
        self._topbar_rule = rule
        btn = ttk.Button(bar, width=3, takefocus=1,
                         command=self.toggle_fullscreen)
        btn.pack(side="right", padx=(4, 6), pady=2)
        self._fs_btn = btn
        self._paint_fs_btn()
        return bar

    def _menubutton(self, label):
        """One menu name on the top bar.

        The tk widget, not the ttk one: a menu name is a word on a bar
        rather than a raised button, and this one takes the theme's colours
        straight from `_retheme` (ttk's would carry sv_ttk's button face
        and an indicator arrow).
        """
        a = self.app
        uibg, fg = a._theme_palette()[:2]
        mb = tk.Menubutton(self._topbar, text=label, direction="below",
                           relief="flat", bd=0, padx=8, pady=2,
                           takefocus=1, highlightthickness=0,
                           background=uibg, foreground=fg,
                           activebackground=uibg, activeforeground=fg,
                           font=a._F(0))
        mb.pack(side="left")
        self._mbtns.append(mb)
        return mb

    def _fs_icon(self, filled):
        """The full-screen glyph, drawn (rule 31): four corner brackets
        pointing out, or pointing in once the window fills the screen."""
        col = self.app._theme_palette()[1]
        key = ("fs", bool(filled), col)
        if key in self._fs_icons:
            return self._fs_icons[key]
        try:
            from PIL import Image, ImageDraw, ImageTk
        except Exception:
            return None
        im = Image.new("RGBA", (32, 32), (0, 0, 0, 0))
        d = ImageDraw.Draw(im)
        W, a, b = 3, 4, 28
        arm = 8
        for sx, sy in ((1, 1), (-1, 1), (1, -1), (-1, -1)):
            x = a if sx > 0 else b
            y = a if sy > 0 else b
            if filled:              # corners pointing inward
                x = x + sx * 5
                y = y + sy * 5
            d.line([x, y, x + sx * arm, y], fill=col, width=W)
            d.line([x, y, x, y + sy * arm], fill=col, width=W)
        img = ImageTk.PhotoImage(im.resize((16, 16), Image.LANCZOS))
        self._fs_icons.clear()
        self._fs_icons[key] = img
        return img

    def _paint_fs_btn(self):
        btn = self._fs_btn
        if btn is None:
            return
        try:
            img = self._fs_icon(self._fullscreen)
            if img is None:
                btn.configure(text="⛶")
            else:
                btn.configure(image=img, text="")
                btn.image = img
            self.wb._tip(btn, TIPS["full_off" if self._fullscreen
                                   else "full_on"])
        except tk.TclError:
            pass

    def toggle_fullscreen(self, on=None):
        """Fill the screen, or come back to the size the window had.

        The size to come back to is remembered here rather than read off
        the window, because `_close_popout` writes `fr_popout_geom` from
        whatever the window measures at the time: closing from full screen
        would otherwise save the whole monitor as the window's size.
        """
        win = self.win
        if win is None:
            return
        want = (not self._fullscreen) if on is None else bool(on)
        if want == self._fullscreen:
            return
        try:
            if want:
                self._geom_normal = win.geometry()
                win.attributes("-fullscreen", True)
            else:
                win.attributes("-fullscreen", False)
                geom, self._geom_normal = self._geom_normal, None
                if geom:
                    self.wb._clamp_geometry(win, geom)
        except tk.TclError:
            return
        self._fullscreen = want
        self._paint_fs_btn()
        try:
            win.after_idle(self._init_sash)
        except tk.TclError:
            pass

    def normal_geometry(self):
        """The geometry worth remembering: the windowed one, always."""
        if self._geom_normal:
            return self._geom_normal
        try:
            return self.win.geometry() if self.win is not None else None
        except tk.TclError:
            return None

    def _on_escape(self, _e=None):
        """Escape leaves full screen; otherwise it closes, as it always
        did.  Bindings on the widget under the pointer still run first."""
        if self._fullscreen:
            self.toggle_fullscreen(False)
            return "break"
        self.wb._close_popout()

    def _allow_maximize(self):
        """Put the caption's maximize and minimize boxes back.

        Windows strips both off any window Tk marks `transient`, and this
        one is a second workbench rather than a dialog: it is meant to be
        maximized, and rule 66 says a panel that can outgrow its window
        must be able to reach every control.  The window stays transient,
        so it still travels with the main window.
        """
        win = self.win
        try:
            win.resizable(True, True)
        except tk.TclError:
            pass
        if not sys.platform.startswith("win"):
            return
        try:
            import ctypes
            from ctypes import wintypes
            u = ctypes.windll.user32
            u.GetAncestor.argtypes = [wintypes.HWND, ctypes.c_uint]
            u.GetAncestor.restype = wintypes.HWND
            u.GetWindowLongW.argtypes = [wintypes.HWND, ctypes.c_int]
            u.GetWindowLongW.restype = ctypes.c_long
            u.SetWindowLongW.argtypes = [wintypes.HWND, ctypes.c_int,
                                         ctypes.c_long]
            u.SetWindowLongW.restype = ctypes.c_long
            u.SetWindowPos.argtypes = [wintypes.HWND, wintypes.HWND,
                                       ctypes.c_int, ctypes.c_int,
                                       ctypes.c_int, ctypes.c_int,
                                       ctypes.c_uint]
            win.update_idletasks()
            hwnd = u.GetAncestor(win.winfo_id(), 2)          # GA_ROOT
            if not hwnd:
                return
            style = u.GetWindowLongW(hwnd, -16)              # GWL_STYLE
            want = style | 0x00010000 | 0x00020000           # MAX | MIN box
            if want != style:
                u.SetWindowLongW(hwnd, -16, want)
                u.SetWindowPos(hwnd, None, 0, 0, 0, 0,
                               0x0001 | 0x0002 | 0x0004 | 0x0020)
        except Exception:
            pass

    def close(self):
        """Give the workbench its own methods and widget lists back."""
        if self.win is None:
            return
        self.win = None
        self._remove_hooks()
        wb = self.wb
        for attr in ("_sync_job", "_relayout_job"):
            job = getattr(self, attr, None)
            setattr(self, attr, None)
            if job is not None:
                try:
                    self.app.root.after_cancel(job)
                except (tk.TclError, ValueError):
                    pass
        keep = [s for s in getattr(wb, "_spins", []) if s not in self._spins]
        wb._spins = keep
        wb._fit_btns = [p for p in getattr(wb, "_fit_btns", [])
                        if p[0] not in self._fits]
        if getattr(wb, "_po_view", None) is self:
            wb._po_view = None
        # a window destroyed by anything other than _close_popout still
        # clears the singleton, so the cell never lights for a dead window
        try:
            if wb._popout is not None and not wb._popout.winfo_exists():
                wb._popout = None
        except (AttributeError, tk.TclError):
            wb._popout = None

    # =====================================================================
    # the menus -- his View / Window / Settings, on the top bar
    # =====================================================================
    def _build_menubar(self):
        """His three menus, entry for entry.

        Every entry, command and order is his; only the bar under them is
        SPARTA's.  Each menu is built as a child of the button that posts
        it, which is what Tk asks of a menubutton.
        """
        wb = self.wb
        mbv = self._menubutton("View")
        view = tk.Menu(mbv, tearoff=0)
        mbv.configure(menu=view)
        view.add_command(label="Notch list", command=wb._open_notch_list)
        view.add_command(label="Predicted lines", command=wb._open_pred_lines)
        view.add_command(label="Results vs pressure", command=wb.results_view)
        view.add_separator()
        view.add_command(label="Info", command=wb._open_wb_info)
        # his View > Refractive index models (15104)
        view.add_command(label="Refractive index models...",
                         command=wb._open_models)
        view.add_command(label="Guide", command=self._open_guide)
        # R14: the gates are a card in the main window's Fringe column,
        # so this scrolls that card into view rather than opening a window
        view.add_command(label="Detection card", command=wb._open_detection)
        view.add_separator()
        # his View > Y-axis range... (11806)
        view.add_command(label="Y-axis range...", command=wb._open_yaxis)
        mbw = self._menubutton("Window")
        window = tk.Menu(mbw, tearoff=0)
        mbw.configure(menu=window)
        window.add_command(label="Reset sidebar width",
                           command=self._reset_sash)
        window.add_separator()
        window.add_command(label="Close", command=wb._close_popout)
        mbs = self._menubutton("Settings")
        setting = tk.Menu(mbs, tearoff=0)
        mbs.configure(menu=setting)
        # The df master switch, the same BooleanVar the Fringe column's box
        # and the Quick Access strip's box hold. A pop-out is a whole session
        # away from either of them, and the red FFT filtered curve in here
        # follows it.
        df_var = getattr(self.app, "show_notch", None)
        df_cmd = getattr(self.app, "_toggle_notch", None)
        if df_var is not None and callable(df_cmd):
            setting.add_checkbutton(label="Defringe (df)", variable=df_var,
                                    command=df_cmd)
            setting.add_separator()
        setting.add_checkbutton(label="Error bars (multiscale variance)",
                                variable=wb.msv_v, command=wb._on_msv)
        setting.add_separator()
        # his Settings > Line colormap (11827-11833)
        setting.add_command(label="Line colours...",
                            command=wb._open_cmap_chooser)
        setting.add_checkbutton(label="skip faint", variable=wb.skipfaint_v,
                                command=wb._on_cmap)
        self._menus = [view, window, setting]

    def _open_guide(self):
        """The workbench guide, in a window of its own.

        His GUI keeps its help in View; the tab keeps the same text in the
        pane beside the plot.  One loader feeds both, so this window cannot
        document an older grammar than the tab it was torn off.
        """
        wb, a = self.wb, self.app
        win = wb._raise_existing(GUIDE_ATTR)
        if win is not None:
            return win
        win = tk.Toplevel(a.root)
        win.title("Fringe workbench guide")
        win.transient(a.root)
        a._center_on_root(win, *wb._dlg_size(60, 68))
        a._apply_titlebar(win)
        wb._closes_by_withdraw(win)
        setattr(wb, GUIDE_ATTR, win)
        card = a._card(win, grow="both")
        card.pack(fill="both", expand=True, padx=10, pady=8)
        card.set_title(a._lf_header(card, "Guide", icon="book"))
        wb._guide_body(card.body, fringe_panel.guide_text(), width=44)
        return win

    def _freeze_sash(self):
        self._sash_set = True

    def _reset_sash(self):
        """His Window > Reset sidebar width."""
        try:
            self.pw.sashpos(0, self._want_sash())
        except (AttributeError, tk.TclError):
            pass

    # =====================================================================
    # the body: sidebar left, plots right, one draggable sash (his shape)
    # =====================================================================
    def _build_body(self):
        win, a = self.win, self.app
        pw = ttk.Panedwindow(win, orient="horizontal")
        pw.pack(fill="both", expand=True)
        self.pw = pw
        left = ttk.Frame(pw)
        # his left column scrolls: it is taller than the window (rule 66)
        host = getattr(a, "_scroll_host", None)
        if callable(host):
            hostf, inner = host(left)
            hostf.pack(fill="both", expand=True)
        else:                       # standalone harness
            inner = ttk.Frame(left)
            inner.pack(fill="both", expand=True)
        col = ttk.Frame(inner, padding=(10, 8))
        col.pack(fill="both", expand=True)
        self.inner = inner
        right = ttk.Frame(pw)
        pw.add(left, weight=0)
        pw.add(right, weight=1)
        self._card_materials(col)
        self._card_indices(col)
        self._card_session(col)
        self._card_pressure(col)
        self._card_removal(col)
        self._card_intensity(col)
        self._card_panels(col)
        self._seal_slots()
        # the n layer2 row is hidden until the box is ticked, and it has to
        # come back in its OWN place: the workbench remembers where
        self.wb._seal_l2_rows()
        self._build_plot(right)
        # a Panedwindow gives a weight=0 pane no width of its own until it
        # is mapped, so the sash is set once the window is realised, and
        # re-asserted on the first few <Configure> events (his _init_sash)
        pw.bind("<Configure>", lambda e: self._init_sash(), add="+")
        # a width the reader drags to is theirs; until then the column
        # keeps up with its own content as the cards settle
        pw.bind("<ButtonRelease-1>", lambda e: self._freeze_sash(), add="+")
        inner.bind("<Configure>", lambda e: self._init_sash(), add="+")
        for ms in (60, 220, 500, 900):
            try:
                self.app.root.after(ms, self._init_sash)
            except tk.TclError:
                pass

    def _want_sash(self):
        """How wide his input column has to be, measured.

        A fixed width cannot be right: the row labels are words, the text
        size is the user's, and pack DROPS what it has no room for rather
        than clipping visibly -- which is how the solved column and the
        Results plot button went missing at 62 em.  The floor is his 430 px
        in ems; above that the column asks for exactly what its widest row
        needs, plus the scrollbar and sash gutter.
        """
        em = self.app._em()
        want = int(em * SIDE_EM)
        try:
            want = max(want, self.inner.winfo_reqwidth() + int(em * 4))
        except (AttributeError, tk.TclError):
            pass
        try:                      # never eat more than half the window
            cap = int(self.win.winfo_width() * 0.55)
            if cap > em * 30:
                want = min(want, cap)
        except (AttributeError, tk.TclError):
            pass
        return want

    def _init_sash(self):
        """Widen the sash to what the column asks for, until the user drags.

        Not one-shot: a card's requested width settles over several idle
        passes (the brand cards measure their own bodies), so a sash set at
        60 ms is measured against a column that has not finished growing.
        This only ever widens, and it stops the moment the reader moves the
        sash themselves.
        """
        if self.win is None or self._sash_set:
            return
        try:
            if self.pw.winfo_width() < self.app._em() * 40:
                return            # the pane is not realised yet
            want = self._want_sash()
            if self.pw.sashpos(0) < want:
                self.pw.sashpos(0, want)
        except (AttributeError, tk.TclError):
            return

    # ---- small builders ---------------------------------------------------
    def _card(self, parent, title):
        c = self.app._card(parent, grow="x")
        c.pack(fill="x", pady=(2, 7))
        c.set_title(self.app._lf_header(c, title))
        return c.body

    def _row(self, parent, pady=None):
        f = ttk.Frame(parent)
        f.pack(fill="x",
               pady=(fringe_panel.PAD_ROW if pady is None else pady))
        return f

    def _lbl(self, parent, text, **kw):
        return self.app._lbl(parent, text=text, **kw)

    def _spin(self, parent, var, lo, hi, width=8, step=1.0):
        """A spinbox the fine-steps switch reaches (it walks wb._spins).

        `step` is the box's own coarse increment, the tab's grammar: a
        thickness steps by a micron and an index by a tenth, and fine steps
        divides whichever one the box carries by ten.
        """
        sp = ttk.Spinbox(parent, textvariable=var, from_=lo, to=hi,
                         width=width, increment=self.wb._step(step))
        sp._fr_step = float(step)
        self.wb._spins = getattr(self.wb, "_spins", [])
        self.wb._spins.append(sp)
        self._spins.append(sp)
        return sp

    def _tip(self, widget, key):
        self.wb._tip(widget, TIPS.get(key, ""))

    def _sol_cell(self, row, sym, key):
        """One solved-readout cell: 'sym =' then the value (his column)."""
        a = self.app
        a._lbl(row, text="%s =" % sym,
               foreground=fringe_panel.MUTED).pack(
                   side="left", padx=(fringe_panel.PAD_X, 0))
        lab = a._lbl(row, text="–", font=a._F(0, "bold", mono=True))
        lab.pack(side="left", padx=(fringe_panel.PAD_X_TIGHT, 0))
        self.tw["sol_" + key] = lab
        return lab

    def _slot(self, lab, **pack):
        """A label that holds a row only while it has something to say."""
        lab.pack(**pack)
        self._slotlist.append((lab, dict(pack)))
        return lab

    def _seal_slots(self):
        """Freeze each slot's place in its card, then hide the empty ones.

        Without the remembered sibling a label that fills in later packs at
        the END of its card, under the CSV folder row it should sit above.
        """
        for lab, pack in self._slotlist:
            try:
                sibs = lab.master.pack_slaves()
                i = sibs.index(lab)
                if i + 1 < len(sibs):
                    pack["before"] = sibs[i + 1]
            except (tk.TclError, ValueError):
                pass
            lab._fr_pack = pack
            try:
                self.wb._show_if_text(lab, lab.cget("text"))
            except tk.TclError:
                pass

    # =====================================================================
    # his sidebar, top to bottom
    # =====================================================================
    def _card_materials(self, parent):
        """His Materials block: the stack's identities.

        His header carries Reset & drop point (9514) and each dropdown a
        free-text name beside it; both are here, in his places.
        """
        a, wb = self.app, self.wb
        W = fringe_panel.STACK_LBL_W
        b = self._card(parent, "Materials")
        r = self._row(b)
        rd = ttk.Button(r, text="Reset & drop point",
                        command=wb._reset_and_drop_point)
        rd.pack(side="right")
        self._tip(rd, "reset_drop")
        r = self._row(b, fringe_panel.PAD_TIGHT)
        self._lbl(r, "Anvil", width=W).pack(side="left")
        cb = a._mapped_combo(r, wb.diamond_v, fringe_panel.DIAMOND_LABELS,
                             width=18)
        cb.pack(side="left", fill="x", expand=True)
        self._tip(cb, "anvil")
        r = self._row(b, fringe_panel.PAD_TIGHT)
        self._lbl(r, "Medium", width=W).pack(side="left")
        cb = a._mapped_combo(r, wb.medium_v, fringe_panel.MEDIUM_LABELS,
                             width=18)
        cb.pack(side="left", fill="x", expand=True)
        self._tip(cb, "medium")
        e = ttk.Entry(r, textvariable=wb.name_med_v, width=12)
        e.pack(side="left", padx=(fringe_panel.PAD_X, 0))
        self._tip(e, "medium_name")
        r = self._row(b, fringe_panel.PAD_TIGHT)
        l2 = ttk.Checkbutton(r, text="Layer 2", variable=wb.layer2_on_v,
                             command=wb._on_layer2)
        l2.pack(side="left")
        self._tip(l2, "layer2")
        cb = a._mapped_combo(r, wb.layer2_v,
                             dict((k, k) for k in ("KCl", "LiF", "air")),
                             width=8)
        cb.pack(side="left", padx=(fringe_panel.PAD_X, 0))
        self._tip(cb, "layer2_cb")
        self.tw["l2_cb"] = cb
        e = ttk.Entry(r, textvariable=wb.name_l2_v, width=12)
        e.pack(side="left", padx=(fringe_panel.PAD_X, 0))
        self._tip(e, "layer2_name")
        r = self._row(b, fringe_panel.PAD_TIGHT)
        self._lbl(r, "Sample", width=W).pack(side="left")
        e = ttk.Entry(r, textvariable=wb.name_samp_v, width=12)
        e.pack(side="left", fill="x", expand=True)
        self._tip(e, "sample_name")

    def _card_indices(self, parent):
        """His Refractive Indices & Thicknesses block, solved column too."""
        a, wb = self.app, self.wb
        W = fringe_panel.STACK_LBL_W
        PT = fringe_panel.PAD_TIGHT
        PX = fringe_panel.PAD_X
        b = self._card(parent, "Refractive Indices & Thicknesses")

        hdr = self._row(b)
        self._lbl(hdr, "", width=W).pack(side="left")
        self._lbl(hdr, "input", width=10, font=a._F(-1),
                  foreground=fringe_panel.MUTED).pack(side="left")
        self._lbl(hdr, "solved (this point)", font=a._F(-1),
                  foreground=fringe_panel.MUTED).pack(side="left",
                                                      padx=(PX, 0))

        # his P -> n row, directly over the n diamond row (9591-9619)
        r = self._row(b, PT)
        self._lbl(r, "P:").pack(side="left")
        dp = self._spin(r, wb.dp_v, 0.0, 500.0, width=6)
        dp.configure(command=wb._calc_n)
        dp.bind("<Return>", lambda e: wb._calc_n())
        dp.bind("<FocusOut>", lambda e: wb._dp_blank_restore())
        dp.pack(side="left", padx=(PX, 0))
        self._lbl(r, "GPa").pack(side="left", padx=(3, 0))
        self._tip(dp, "dp")
        cn = ttk.Button(r, text="calc n", width=7, command=wb._calc_n)
        cn.pack(side="left", padx=(12, 12))
        self._tip(cn, "calc_n")
        amb = ttk.Button(r, text="Ambient n (2.4168)", command=wb._ambient_n)
        amb.pack(side="left")
        self._tip(amb, "ambient_n")

        # his n diamond is a BOX (9567): the model writes it on every load
        IDX = fringe_panel.IDX_STEP
        r = self._row(b, PT)
        self._lbl(r, "n diamond", width=W).pack(side="left")
        nd = self._spin(r, wb.nd_v, 0.0, 100000.0, width=10, step=IDX)
        nd.configure(command=wb._commit_stack)
        for _seq in ("<Return>", "<FocusOut>"):
            nd.bind(_seq, wb._commit_stack, add="+")
        nd.pack(side="left")
        self.tw["nd"] = nd
        self._lbl(r, "Fixed", font=a._F(-1, "bold"),
                  foreground=fringe_panel.MUTED).pack(side="left",
                                                      padx=(PX, 0))
        self._tip(nd, "nd")

        r = self._row(b, PT)
        self.tw["lbl_n_medium"] = self._lbl(r, "n medium", width=W)
        self.tw["lbl_n_medium"].pack(side="left")
        cell = ttk.Frame(r)
        cell.pack(side="left")
        nm = self._lbl(cell, "1.2", width=10, font=a._F(0, mono=True))
        ne = self._spin(cell, wb.medium_n_v, 0.0, 100000.0, width=10,
                        step=IDX)
        ne.configure(command=wb._commit_stack)
        for _seq in ("<Return>", "<FocusOut>"):
            ne.bind(_seq, wb._commit_stack, add="+")
        self.tw["nmed_lbl"] = nm
        self.tw["nmed_e"] = ne
        self._lbl(r, "Fixed", font=a._F(-1, "bold"),
                  foreground=fringe_panel.MUTED).pack(side="left",
                                                      padx=(PX, 0))
        self._tip(ne, "nmed")
        self._tip(nm, "nmed")

        # his n layer2 row, hidden until Layer 2 is ticked (9578)
        r = self._row(b, PT)
        self.tw["lbl_n_layer2"] = self._lbl(r, "n layer2", width=W)
        self.tw["lbl_n_layer2"].pack(side="left")
        nl2 = self._spin(r, wb.nl2_v, 0.0, 100000.0, width=10, step=IDX)
        nl2.configure(command=wb._commit_stack)
        for _seq in ("<Return>", "<FocusOut>"):
            nl2.bind(_seq, wb._commit_stack, add="+")
        nl2.pack(side="left")
        self._lbl(r, "Fixed", font=a._F(-1, "bold"),
                  foreground=fringe_panel.MUTED).pack(side="left",
                                                      padx=(PX, 0))
        self._tip(nl2, "nl2")
        wb._l2_row(r, dict(fill="x", pady=PT))

        r = self._row(b, PT)
        self.tw["lbl_n_sample"] = self._lbl(r, "n sample", width=W)
        self.tw["lbl_n_sample"].pack(side="left")
        ns = self._spin(r, wb.ns_v, 0.0, 100000.0, width=10, step=IDX)
        ns.configure(command=wb._commit_stack)
        ns.pack(side="left")
        for _seq in ("<Return>", "<FocusOut>"):
            ns.bind(_seq, wb._commit_stack, add="+")
        wb._tip_live(ns, lambda: wb._tip_with_hint(TIPS["ns"], "n_s"))
        self._sol_cell(r, "n_s", "n_s")

        # his short centred rule between the indices and the thicknesses
        sep = ttk.Frame(b, height=9)
        sep.pack(fill="x", pady=(3, 3))
        sep.pack_propagate(False)
        ttk.Separator(sep, orient="horizontal").place(
            relx=0.5, rely=0.5, relwidth=SEP_RELW, anchor="center")

        for key, var, txt, sym, skey, tipk in (
                ("d2", wb.d2_v, "d2 upper medium (um)", "t_m", "t_layer2",
                 "d2"),
                ("t", wb.t_v, "t sample (um)", "t_s", "t_s", "t"),
                ("d1", wb.d1_v, "d1 lower medium (um)", "L", "L", "d1")):
            r = self._row(b, PT)
            self.tw["lbl_" + key] = self._lbl(r, txt, width=W)
            self.tw["lbl_" + key].pack(side="left")
            sp = self._spin(r, var, 0.0, fringe_panel.THICK_MAX_UM,
                            width=8)
            sp.configure(command=lambda k=key: wb._on_d_edit(k))
            sp.bind("<Return>", lambda e, k=key: wb._on_d_edit(k))
            sp.pack(side="left")
            wb._tip_live(sp, lambda t=tipk, k=skey:
                         wb._tip_with_hint(TIPS[t], k))
            self._sol_cell(r, sym, skey)

        r = self._row(b, fringe_panel.PAD_GROUP)
        self._lbl(r, "Total (um)", width=W).pack(side="left")
        ts = ttk.Spinbox(r, textvariable=wb.total_v, from_=0.0,
                         to=fringe_panel.THICK_MAX_UM,
                         width=8, increment=wb._step(),
                         command=wb._on_total_edit)
        ts.bind("<Return>", lambda e: wb._on_total_edit())
        ts.pack(side="left")
        wb._spins = getattr(wb, "_spins", []) + [ts]
        self._spins.append(ts)
        self.tw["total_sp"] = ts
        self._tip(ts, "total")
        lk = ttk.Checkbutton(r, text="Lock In", variable=wb.lock_v,
                             command=wb._on_lock)
        lk.pack(side="left", padx=(PX, 0))
        self._tip(lk, "lock")
        # his boxed fine-steps switch: it reaches every spinbox in the
        # window, so it keeps the extra emphasis he gave it
        box = tk.Frame(r, relief="solid", borderwidth=1,
                       highlightthickness=0)
        box.pack(side="left", padx=(PX, 0))
        self._boxes.append(box)
        fs = ttk.Checkbutton(box, text="fine steps (÷ 10)",
                             variable=wb.fine_v, command=wb._sync_steps)
        fs.pack(padx=2, pady=1)
        self._tip(fs, "fine")

        r = self._row(b, fringe_panel.PAD_GROUP)
        self._lbl(r, "Fit peaks:").pack(side="left")
        for mode, tipk in (("distinct", "fit_distinct"),
                           ("shared", "fit_shared")):
            img = wb._fit_icon(mode == "shared")
            btn = ttk.Button(r, command=lambda m=mode:
                             wb._fit_peaks_mode(m))
            if img is not None:
                btn.configure(image=img)
                btn.image = img
            else:
                btn.configure(text=mode[0].upper(), width=3)
            btn.pack(side="left", padx=(fringe_panel.PAD_X_TIGHT, 0))
            self._tip(btn, tipk)
            wb._fit_btns.append((btn, mode))
            self._fits.append(btn)
        ttk.Separator(r, orient="vertical").pack(side="left", fill="y",
                                                 padx=PX, pady=1)
        rp = a._brand_button(r, "Plot point", wb._record_point)
        rp.pack(side="left")
        self._tip(rp, "plot")
        rv = ttk.Button(r, text="Results plot", width=13,
                        command=wb.results_view)
        rv.pack(side="left", padx=(PX, 0))
        self.tw["results_btn"] = rv
        self._tip(rv, "results")

    def _card_session(self, parent):
        """His Session block."""
        a, wb = self.app, self.wb
        PX = fringe_panel.PAD_X
        b = self._card(parent, "Session")
        r = self._row(b)
        lp = ttk.Button(r, text="Load parent folder...",
                        command=wb._load_parent_folder)
        lp.pack(side="left", fill="x", expand=True)
        self._tip(lp, "load_parent")
        lr = ttk.Button(r, text="Load raw spectra...",
                        command=wb._load_raw_spectra)
        lr.pack(side="left", fill="x", expand=True, padx=(PX, 0))
        self._tip(lr, "load_raw")

        r = self._row(b, fringe_panel.PAD_TIGHT)
        nx = ttk.Button(r, text="▶", width=2,
                        command=lambda: wb._step_series(1))
        nx.pack(side="right")
        pv = ttk.Button(r, text="◀", width=2,
                        command=lambda: wb._step_series(-1))
        pv.pack(side="left")
        cb = ttk.Combobox(r, textvariable=wb.series_nav_v, state="readonly",
                          width=16)
        cb.pack(side="left", fill="x", expand=True,
                padx=(fringe_panel.PAD_X_TIGHT, fringe_panel.PAD_X_TIGHT))
        cb.bind("<<ComboboxSelected>>", wb._on_series_pick)
        self.tw["series_cb"] = cb
        self.tw["series_prev"] = pv
        self.tw["series_next"] = nx
        self._tip(cb, "series_cb")
        self._tip(pv, "series_prev")
        self._tip(nx, "series_next")

        lab = self._lbl(b, "Series: –", foreground=fringe_panel.MUTED)
        lab.pack(fill="x", pady=fringe_panel.PAD_TIGHT)
        self.tw["series_lbl"] = lab

        r = self._row(b, fringe_panel.PAD_GROUP)
        sv = ttk.Button(r, text="Save session", width=13,
                        command=wb.save_series)
        sv.pack(side="left", fill="x", expand=True)
        self._tip(sv, "save")
        ld = ttk.Button(r, text="Load session", width=13,
                        command=wb.load_series)
        ld.pack(side="left", fill="x", expand=True, padx=(PX, 0))
        self._tip(ld, "load")

        r = self._row(b, fringe_panel.PAD_BTNROW)
        lf = ttk.Button(r, text="Load session file...",
                        command=wb.load_session_file)
        lf.pack(side="left", fill="x", expand=True)
        self._tip(lf, "load_file")

        st = self._lbl(b, "", font=a._F(0, mono=True))
        self.tw["state_lbl"] = self._slot(st, fill="x",
                                          pady=fringe_panel.PAD_TIGHT)
        dk = self._lbl(b, "", font=a._F(0, mono=True))
        self.tw["series_disk_lbl"] = self._slot(
            dk, fill="x", pady=fringe_panel.PAD_TIGHT)

    def _card_pressure(self, parent):
        """His Pressure point row."""
        wb = self.wb
        b = self._card(parent, "Pressure point")
        r = self._row(b)
        nx = ttk.Button(r, text="▶", width=2,
                        command=lambda: wb._step_trace(1))
        nx.pack(side="right")
        pv = ttk.Button(r, text="◀", width=2,
                        command=lambda: wb._step_trace(-1))
        pv.pack(side="left")
        cb = ttk.Combobox(r, textvariable=wb.trace_v, state="readonly",
                          width=18)
        cb.pack(side="left", fill="x", expand=True,
                padx=(fringe_panel.PAD_X_TIGHT, fringe_panel.PAD_X_TIGHT))
        cb.bind("<<ComboboxSelected>>", wb._on_trace_pick)
        self.tw["trace_cb"] = cb
        self.tw["pressure_prev"] = pv
        self.tw["pressure_next"] = nx
        self._tip(cb, "trace_cb")
        self._tip(pv, "trace_prev")
        self._tip(nx, "trace_next")

    def _card_removal(self, parent):
        """His FFT removal block: the per-channel low-pass and the outputs."""
        a, wb = self.app, self.wb
        PX = fringe_panel.PAD_X
        PT = fringe_panel.PAD_TIGHT
        b = self._card(parent, "FFT removal")
        for chan in fringe_panel.CHANNELS:
            a._subhead(b, chan)
            r = self._row(b, PT)
            clr = ttk.Button(r, text="Clear notches", width=13,
                             command=lambda c=chan:
                             wb._clear_notches_for(c))
            clr.pack(side="right", padx=(PX, 0))
            cb = ttk.Checkbutton(r, text="Low-pass cutoff",
                                 variable=wb.lp_on_v[chan],
                                 command=lambda c=chan:
                                 wb._on_lp_toggle(c))
            cb.pack(side="left")
            sp = self._spin(r, wb.lp_v[chan], fringe_panel.LP_MIN_UM,
                            fringe_panel.LP_MAX_UM, width=6)
            sp.configure(command=lambda c=chan: wb._on_lp_edit(c))
            sp.bind("<Return>", lambda e, c=chan: wb._on_lp_edit(c))
            sp.bind("<FocusOut>",
                    lambda e, c=chan: wb._on_lp_edit(c, quiet=True))
            sp.pack(side="left", padx=(fringe_panel.PAD_X_TIGHT, 0))
            self._lbl(r, "um").pack(side="left",
                                    padx=fringe_panel.PAD_X_TIGHT)
            self._tip(cb, "lp_on")
            self._tip(sp, "lp_um")
            self._tip(clr, "clear")
            # the edge that cutoff rolls off over (R15-D): the same two
            # variables the tab's card writes, so the two views agree
            r = self._row(b, PT)
            self._lbl(r, "Edge", width=fringe_panel.LBL_W2).pack(side="left")
            ecb = a._mapped_combo(r, wb.lp_shape_v[chan],
                                  fringe_panel.LP_SHAPE_LABELS,
                                  command=lambda c=chan:
                                  wb._on_lp_edge_edit(c), width=13)
            ecb.pack(side="left")
            rsp = self._spin(r, wb.lp_roll_v[chan], 0.1, 40.0, width=5)
            rsp.configure(command=lambda c=chan: wb._on_lp_edge_edit(c))
            rsp.bind("<Return>", lambda e, c=chan: wb._on_lp_edge_edit(c))
            rsp.bind("<FocusOut>", lambda e, c=chan: wb._on_lp_edge_edit(c))
            rsp.pack(side="left", padx=(fringe_panel.PAD_X, 0))
            self._lbl(r, "um").pack(side="left",
                                    padx=fringe_panel.PAD_X_TIGHT)
            self._tip(ecb, "lp_shape")
            self._tip(rsp, "lp_roll")
        r = self._row(b, fringe_panel.PAD_GROUP)
        ec = ttk.Button(r, text="Export cleaned spectrum",
                        command=wb._export_cleaned)
        ec.pack(side="left", fill="x", expand=True)
        self._tip(ec, "export_clean")
        nl = ttk.Button(r, text="Notch list", width=11,
                        command=wb._open_notch_list)
        nl.pack(side="left", fill="x", expand=True, padx=(PX, 0))
        self._tip(nl, "notch_list")
        r = self._row(b, PT)
        wn = ttk.Button(r, text="Write notches file for batch",
                        command=wb.export_notch_overrides)
        wn.pack(side="left", fill="x", expand=True)
        self._tip(wn, "write_notches")
        dn = ttk.Button(r, text="Delete notches file", width=18,
                        command=wb._delete_notches_file)
        dn.pack(side="left", fill="x", expand=True, padx=(PX, 0))
        self._tip(dn, "delete_notches")
        # 'Write to defringe' retired with R15-B: the df switch and the
        # defringed CSVs read each trace's own notch list live, so there is
        # a button less to press here and in the tab.
        nf = self._lbl(b, "", foreground=fringe_panel.MUTED)
        self.tw["notch_file_lbl"] = self._slot(nf, fill="x", pady=PT)

    def _card_intensity(self, parent):
        """His Refractive Index from Intensity block."""
        a, wb = self.app, self.wb
        PX = fringe_panel.PAD_X
        PT = fringe_panel.PAD_TIGHT
        b = self._card(parent, "Refractive Index from Intensity")
        r = self._row(b)
        cf = a._brand_button(r, "Compute fits", wb._compute_fits)
        cf.pack(side="left")
        self._tip(cf, "fits")
        hb = ttk.Button(r, text="History ▾", width=10,
                        command=wb._open_history)
        hb.pack(side="left", padx=(PX, 0))
        self._tip(hb, "history")
        r = self._row(b, PT)
        tb = ttk.Button(r, text="Show tiered", width=13,
                        command=wb._toggle_tiers)
        tb.pack(side="left", fill="x", expand=True)
        self.tw["tiers_btn"] = tb
        self._tip(tb, "tiers")
        cb = ttk.Button(r, text="Hide clean spectrum", width=18,
                        command=wb._toggle_hideclean)
        cb.pack(side="left", fill="x", expand=True, padx=(PX, 0))
        self.tw["clean_btn"] = cb
        self._tip(cb, "clean")
        r = self._row(b, PT)
        bf = ttk.Checkbutton(r, text="Band Δ resolution floor",
                             variable=wb.bandfloor_v,
                             command=wb._invalidate)
        bf.pack(side="left")
        self._tip(bf, "bandfloor")

    def _card_panels(self, parent):
        """His bottom block: the Panels line, the status rows, the folder."""
        a, wb = self.app, self.wb
        b = self._card(parent, "Panels")
        hint = self._lbl(
            b, "View > Notch list / Predicted lines / Results / Info",
            foreground=fringe_panel.MUTED)
        hint.pack(fill="x", pady=fringe_panel.PAD_ROW)
        self._tip(hint, "panels")
        em32 = a._em() * 32
        st = self._lbl(b, "Load a spectrum to get FFT peaks.",
                       foreground=fringe_panel.MUTED, wraplength=em32,
                       justify="left")
        self.tw["status_lbl"] = self._slot(st, fill="x",
                                           pady=fringe_panel.PAD_ROW)
        sv = self._lbl(b, "", wraplength=em32, justify="left")
        self.tw["solve_lbl"] = self._slot(sv, fill="x",
                                          pady=fringe_panel.PAD_TIGHT)
        r = self._row(b, fringe_panel.PAD_GROUP)
        self._lbl(r, "CSV folder:", width=fringe_panel.LBL_W).pack(
            side="left")
        e = ttk.Entry(r, textvariable=wb.csv_dir_v, state="readonly")
        e.pack(side="left", fill="x", expand=True)
        self._tip(e, "csv")

    # =====================================================================
    # the plots: his 2x2 and his navigation toolbar
    # =====================================================================
    def _build_plot(self, parent):
        wb = self.wb
        face, ink = wb._page()
        self.fig = Figure(figsize=(9.25, 4.05), dpi=100, facecolor=face)
        # his gridspec: forward-model FFT panels down the left column, the
        # measured spectra down the right, Background over Sample in both.
        # The gaps come from `FringeWorkbench._layout_grid`, measured off
        # the drawn furniture, so none are set here (see GRID_PT).
        gs = self.fig.add_gridspec(2, 2, width_ratios=[1.0, 1.25])
        self.ax_bg = self.fig.add_subplot(gs[0, 0])
        self.ax_s = self.fig.add_subplot(gs[1, 0], sharex=self.ax_bg)
        self.ax_mb = self.fig.add_subplot(gs[0, 1])
        self.ax_ms = self.fig.add_subplot(gs[1, 1], sharex=self.ax_mb)
        self.axes = {"Background": self.ax_bg, "Sample": self.ax_s}
        self.maxes = {"Background": self.ax_mb, "Sample": self.ax_ms}
        holder = ttk.Frame(parent)
        holder.pack(fill="both", expand=True)
        self.canvas = FigureCanvasTkAgg(self.fig, master=holder)
        self.tkcanvas = self.canvas.get_tk_widget()
        # the toolbar packs FIRST so the canvas is the sacrificial widget
        # when the sash is dragged (rules 13 and 14)
        bar = ttk.Frame(holder)
        bar.pack(side="bottom", fill="x")
        try:
            self.toolbar = NavigationToolbar2Tk(self.canvas, bar)
            self.toolbar.update()
        except Exception:
            self.toolbar = None
        self.tkcanvas.pack(side="top", fill="both", expand=True)
        try:
            self.tkcanvas.configure(background=wb._pal()[0],
                                    highlightthickness=0)
        except tk.TclError:
            pass
        for name, fn in (("button_press_event", wb._on_press),
                         ("motion_notify_event", wb._on_motion),
                         ("button_release_event", wb._on_release),
                         ("figure_leave_event", wb._on_leave),
                         ("axes_leave_event", wb._on_leave)):
            self.canvas.mpl_connect(name, self._forward(fn))
        # the grid's margins are pixels: a resized canvas gets them again
        self.tkcanvas.bind("<Configure>", self._on_canvas_resize, add="+")

    def _on_canvas_resize(self, _event=None):
        job, self._relayout_job = self._relayout_job, None
        if job is not None:
            try:
                self.app.root.after_cancel(job)
            except (tk.TclError, ValueError):
                pass
        try:
            self._relayout_job = self.app.root.after(120, self._relayout)
        except tk.TclError:
            pass

    def _relayout(self):
        self._relayout_job = None
        if self.win is None or self.fig is None:
            return
        with self._view():
            self.wb._relayout(self.fig, self.canvas)

    def _forward(self, fn):
        """Run one of his mouse handlers against THIS window's axes."""
        def _run(event):
            if self.win is None:
                return
            with self._view():
                fn(event)
        return _run

    # =====================================================================
    # one model, two views
    # =====================================================================
    @contextlib.contextmanager
    def _view(self):
        """Lend the workbench this window's figure for the length of a call.

        Everything swapped here is view state -- the axes, the artists, the
        canvas and the two label registries the draw fills.  The MODEL (the
        records, the notches, the roles, the tk variables) is never touched,
        which is what keeps the two views one model.

        `_request_redraw` is shadowed for the same span.  His handlers ask
        for an immediate redraw after a notch or a drag, and an immediate
        redraw inside the swap would paint the tab's content into this
        window's axes and leave the tab stale.  The request is remembered
        and made once the workbench has its own view back.
        """
        wb = self.wb
        if self._in_view or self.win is None:
            yield
            return
        self._in_view = True
        keep = (wb.fig, wb.canvas, wb._tkcanvas, wb.ax_bg, wb.ax_s,
                wb.ax_mb, wb.ax_ms, wb._axes, wb._maxes, wb._twins,
                wb._artists, wb._nt_labels, wb._schem_labels,
                getattr(wb, "_hover_key", None),
                getattr(wb, "_cursor_now", None))
        wb.fig = self.fig
        wb.canvas = self.canvas
        wb._tkcanvas = self.tkcanvas
        wb.ax_bg, wb.ax_s = self.ax_bg, self.ax_s
        wb.ax_mb, wb.ax_ms = self.ax_mb, self.ax_ms
        wb._axes, wb._maxes = self.axes, self.maxes
        wb._twins, wb._artists = self.twins, self.artists
        wb._nt_labels = self.nt_labels
        wb._schem_labels = self.schem_labels
        wb._hover_key = self.hover_key
        wb._cursor_now = self.cursor_now
        wb._request_redraw = self._defer_redraw
        self._pending = None
        self._pending_keep = False
        try:
            yield
        finally:
            self.twins = wb._twins
            self.artists = wb._artists
            self.nt_labels = wb._nt_labels
            self.schem_labels = wb._schem_labels
            self.hover_key = getattr(wb, "_hover_key", None)
            self.cursor_now = getattr(wb, "_cursor_now", None)
            (wb.fig, wb.canvas, wb._tkcanvas, wb.ax_bg, wb.ax_s, wb.ax_mb,
             wb.ax_ms, wb._axes, wb._maxes, wb._twins, wb._artists,
             wb._nt_labels, wb._schem_labels, wb._hover_key,
             wb._cursor_now) = keep
            try:
                del wb._request_redraw
            except AttributeError:
                pass
            self._in_view = False
            want, self._pending = self._pending, None
            keep, self._pending_keep = bool(self._pending_keep), False
            if want is not None:
                wb._request_redraw(now=want, keep_view=keep)

    def _defer_redraw(self, now=False, keep_view=False):
        """Take the request the workbench made inside the swap, keep_view and
        all.  A low-pass drag in THIS window asks for a redraw that leaves the
        panels' limits alone, and the flag has to survive the deferral or the
        pop-out loses the reader's zoom where the tab keeps it."""
        self._pending = bool(now) or bool(self._pending)
        if keep_view:
            self._pending_keep = True

    def _mirror(self):
        """The workbench's `_mirror_popout` while this window is open.

        `_redraw` calls it once the tab's figure is painted, so the two
        views are drawn from one compute and one model on every frame.
        """
        win = self.win
        if win is None or self.fig is None:
            return
        try:
            if not win.winfo_exists():
                return
        except tk.TclError:
            return
        sig = self.wb._theme_sig()
        if sig != self._theme_seen:
            self._theme_seen = sig
            self._retheme()
        # A view-preserving redraw (a low-pass drag and its release) must not
        # move THIS window's panels either.  `_paint` clears all four axes,
        # so the limits are taken inside the swap, where they are ours, and
        # put back the moment the paint is done.
        keep = bool(getattr(self.wb, "_keep_view", False))
        with self._view():
            saved = self.wb._view_limits() if keep else None
            self._paint()
            if saved is not None:
                self.wb._restore_limits(saved)
        self._sync_soon()

    def _paint(self):
        """His panels, into this window's axes (runs inside `_view`)."""
        wb = self.wb
        face, ink = wb._page()
        wb.fig.set_facecolor(face)
        for ax in (wb.ax_bg, wb.ax_s, wb.ax_mb, wb.ax_ms):
            ax.clear()
            ax.set_facecolor(face)
            for sp in ax.spines.values():
                sp.set_color(ink)
        for tw in wb._twins.values():
            try:
                tw.remove()
            except Exception:
                pass
        wb._twins = {}
        rec = wb._record()
        if rec is None:
            wb.ax_bg.text(0.5, 0.5, "Run a folder, or use Session >\n"
                          "Load raw spectra...",
                          transform=wb.ax_bg.transAxes, ha="center",
                          va="center", color=ink, fontsize=10)
            wb.ax_s.set_axis_off()
            for ax in (wb.ax_mb, wb.ax_ms):
                ax.text(0.5, 0.5, "no measured data", transform=ax.transAxes,
                        ha="center", va="center",
                        color=self.app._muted_fg(), fontsize=9)
        else:
            wb.ax_s.set_axis_on()
            p = wb._stack_params(rec)
            upper = wb._x_upper(p)
            # a cold start writes its solve into the boxes, so the stack
            # model is rebuilt from them before anything is drawn -- the
            # tab's `_redraw` does the same, and the two must agree
            if wb._seed_roles(p, upper):
                p = wb._stack_params(rec)
                upper = wb._x_upper(p)
            # the WHOLE registry, from the workbench's own definition: a
            # window that reset a shorter set left the next gesture reaching
            # for a key that was not there
            wb._artists = wb._blank_artists()
            wb._nt_labels = {}
            wb._schem_labels = {}
            wb._hover_key = None
            for chan in fringe_panel.CHANNELS:
                wb._draw_panel(chan, rec, p, upper)
            for chan in fringe_panel.CHANNELS:
                wb._draw_measured(chan, rec)
        wb._layout_grid(wb.fig)
        wb._fit_labels()
        try:
            self.canvas.draw_idle()
        except Exception:
            pass

    # ---- the label mirror -------------------------------------------------
    def _install_hooks(self):
        wb = self.wb
        self._saved["_mirror_popout"] = wb.__dict__.get("_mirror_popout")
        wb._mirror_popout = self._mirror
        for name in self.HOOKS:
            fn = getattr(wb, name, None)
            if not callable(fn):
                continue
            self._saved[name] = wb.__dict__.get(name)
            wb.__dict__[name] = self._hooked(fn)

    def _hooked(self, fn):
        def _run(*a, **kw):
            try:
                return fn(*a, **kw)
            finally:
                self._sync_soon()
        return _run

    def _remove_hooks(self):
        wb = self.wb
        for name, old in self._saved.items():
            if old is None:
                wb.__dict__.pop(name, None)
            else:
                wb.__dict__[name] = old
        self._saved = {}

    def _sync_soon(self):
        """Coalesce a burst of label writes into one copy pass."""
        if self.win is None or self._sync_job is not None:
            return
        try:
            self._sync_job = self.app.root.after_idle(self._sync_now)
        except (AttributeError, tk.TclError):
            self._sync_now()

    def _sync_now(self):
        self._sync_job = None
        if self.win is None:
            return
        try:
            if not self.win.winfo_exists():
                return
        except tk.TclError:
            return
        wb = self.wb
        # n diamond is a spinbox on both sides now, sharing wb.nd_v, so
        # there is nothing left to copy for it
        for key, src in (("nmed_lbl", getattr(wb, "_nmed_lbl", None)),
                         ("series_lbl", getattr(wb, "_series_lbl", None))):
            self._copy(src, key)
        for skey in ("n_s", "t_s", "t_layer2", "L"):
            self._copy(getattr(wb, "_sol_lbl", {}).get(skey), "sol_" + skey)
        # the material names reach the row labels, so this window's copies
        # of those rows read whatever the tab's do (R15-D)
        for nkey in ("n_medium", "n_sample", "n_layer2", "d2", "t", "d1"):
            self._copy(getattr(wb, "_stack_lbls", {}).get(nkey),
                       "lbl_" + nkey)
        for key, src in (("state_lbl", getattr(wb, "_state_lbl", None)),
                         ("series_disk_lbl",
                          getattr(wb, "_series_disk_lbl", None)),
                         ("notch_file_lbl",
                          getattr(wb, "_notch_file_lbl", None)),
                         ("status_lbl", getattr(wb, "_status_lbl", None)),
                         ("solve_lbl", getattr(wb, "_solve_lbl", None))):
            self._copy(src, key, fg=True, slot=True)
        for key, src in (("results_btn", getattr(wb, "_results_btn", None)),
                         ("tiers_btn", getattr(wb, "_tiers_btn", None)),
                         ("clean_btn", getattr(wb, "_clean_btn", None))):
            self._copy(src, key)
        self._copy_values(getattr(wb, "_trace_cb", None), "trace_cb")
        self._copy_values(getattr(wb, "_series_cb", None), "series_cb")
        for src, keys in ((getattr(wb, "_pressure_btns", None),
                           ("pressure_prev", "pressure_next")),
                          (getattr(wb, "_series_nav_btns", None),
                           ("series_prev", "series_next"))):
            if not src:
                continue
            for i, key in enumerate(keys):
                self._copy_state(src[i], key)
        self._copy_state(getattr(wb, "_l2_cb", None), "l2_cb")
        self._copy_cfg(getattr(wb, "_total_sp", None), "total_sp", "state")
        self._sync_medium_cell()

    def _copy(self, src, key, fg=False, slot=False):
        dst = self.tw.get(key)
        if src is None or dst is None:
            return
        try:
            txt = src.cget("text")
            dst.configure(text=txt)
            if fg:
                dst.configure(foreground=src.cget("foreground"))
            if slot:
                self.wb._show_if_text(dst, txt)
        except tk.TclError:
            pass

    def _copy_values(self, src, key):
        dst = self.tw.get(key)
        if src is None or dst is None:
            return
        try:
            dst["values"] = src["values"]
        except tk.TclError:
            pass

    def _copy_state(self, src, key):
        dst = self.tw.get(key)
        if src is None or dst is None:
            return
        try:
            dst.state(["disabled"] if "disabled" in src.state()
                      else ["!disabled"])
        except tk.TclError:
            pass

    def _copy_cfg(self, src, key, opt):
        dst = self.tw.get(key)
        if src is None or dst is None:
            return
        try:
            dst.configure(**{opt: str(src.cget(opt))})
        except tk.TclError:
            pass

    def _sync_medium_cell(self):
        """His medium row: the typed index while the medium is Other, the
        model's own value otherwise (the tab's `_sync_medium_row`)."""
        lab, ent = self.tw.get("nmed_lbl"), self.tw.get("nmed_e")
        if lab is None or ent is None:
            return
        manual = self.wb.medium_v.get() == fringe_materials.MEDIUM_MANUAL
        try:
            if manual:
                lab.pack_forget()
                ent.pack(side="left")
            else:
                ent.pack_forget()
                lab.pack(side="left")
        except tk.TclError:
            pass

    # ---- theme ------------------------------------------------------------
    def _retheme(self):
        """Repaint what sv_ttk and `_recolor_tk` do not reach: the top bar,
        the menus, the navigation toolbar and the boxed switch."""
        if self.win is None:
            return
        try:
            uibg, fg = self.wb._pal()[:2]
        except (AttributeError, tk.TclError):
            return
        hot = self.app._blendc(uibg, self.app._brand()["ac1"], 0.30)
        for m in self._menus:
            try:
                m.configure(background=uibg, foreground=fg,
                            activebackground=hot, activeforeground=fg,
                            borderwidth=0)
            except tk.TclError:
                pass
        # the bar the menus sit on, and the hairline that ends it
        try:
            self._topbar.configure(background=uibg)
            self._topbar_rule.configure(background=self.app._hairline()[1])
        except (AttributeError, tk.TclError):
            pass
        for mb in self._mbtns:
            try:
                mb.configure(background=uibg, foreground=fg,
                             activebackground=hot, activeforeground=fg,
                             font=self.app._F(0))
            except tk.TclError:
                pass
        for box in self._boxes:
            try:
                box.configure(background=uibg,
                              highlightbackground=self.app._hairline()[1])
            except tk.TclError:
                pass
        try:
            self.tkcanvas.configure(background=uibg)
        except (AttributeError, tk.TclError):
            pass
        # the full-screen glyph is drawn, so a theme switch re-draws it
        # (rule 32: icons are regenerated, never recoloured)
        self._fs_icons.clear()
        self._paint_fs_btn()
        tb = self.toolbar
        if tb is not None:
            self._retint_tree(tb, uibg, fg)
            # matplotlib picks each toolbar glyph's ink from the button's
            # background AT BUILD TIME, so a ground changed afterwards can
            # leave black icons on a black bar.  Its own re-render is the
            # fix; guarded, because it is a private helper.
            setter = getattr(tb, "_set_image_for_button", None)
            if callable(setter):
                for w in tb.winfo_children():
                    if getattr(w, "_image_file", None) is None:
                        continue
                    try:
                        setter(w)
                    except Exception:
                        pass

    def _retint_tree(self, widget, bg, fg):
        """The navigation toolbar is plain tk: give it the panel ground."""
        try:
            widget.configure(background=bg)
        except tk.TclError:
            pass
        try:
            if isinstance(widget, (tk.Label, tk.Button, tk.Checkbutton)):
                widget.configure(foreground=fg, activebackground=bg,
                                 activeforeground=fg,
                                 highlightbackground=bg)
        except tk.TclError:
            pass
        try:
            for child in widget.winfo_children():
                self._retint_tree(child, bg, fg)
        except tk.TclError:
            pass
