"""A widget-owned, vertically scrollable results host for long chart pages.

Place charts and tables in ``view.content``. Their requested heights are kept;
only their widths follow the viewport. No application-wide wheel binding or
periodic polling is used, and dynamically created children are supported.
"""
from __future__ import annotations

import tkinter as tk
from tkinter import ttk


class ScrollableResults(ttk.Frame):
    """Keep result panels readable when a design adds more output rails.

    ``content`` is a normal ttk Frame. Pack/grid its children with a meaningful
    requested height, rather than expanding a single small figure to fit every
    row. ``sync()`` is available after bulk layout changes; normal geometry
    changes schedule the same update automatically.
    """

    _WHEEL_EVENTS = ('<MouseWheel>', '<Button-4>', '<Button-5>')
    _NATIVE_WHEEL_CLASSES = frozenset({
        'TCombobox', 'Combobox', 'Spinbox', 'TSpinbox', 'Text', 'Listbox',
        'Treeview', 'TTreeview', 'Scrollbar', 'TScrollbar',
    })

    def __init__(self, parent, *, background=None, scroll_increment=24, **kwargs):
        super().__init__(parent, **kwargs)
        if background is None:
            background = ttk.Style(self).lookup('TFrame', 'background') or '#eef1f5'
        self.canvas = tk.Canvas(self, borderwidth=0, highlightthickness=0,
                                background=background,
                                yscrollincrement=max(1, int(scroll_increment)))
        self.scrollbar = ttk.Scrollbar(self, orient='vertical',
                                       command=self.canvas.yview)
        self.canvas.configure(yscrollcommand=self.scrollbar.set)
        self.scrollbar.pack(side='right', fill='y')
        self.canvas.pack(side='left', fill='both', expand=True)
        self.content = ttk.Frame(self.canvas)
        self._window_id = self.canvas.create_window((0, 0), window=self.content,
                                                    anchor='nw')
        self._sync_job = None
        self._closed = False
        self._last_viewport_width = None
        self._wheel_tag = 'ScrollableResults_' + str(self)
        self._toplevel = self.winfo_toplevel()
        self._wheel_commands = {}
        # A local bindtag precedes a Matplotlib canvas' own wheel binding, so
        # scrolling a long result page does not also zoom/scroll a plot.
        for sequence in self._WHEEL_EVENTS:
            self._wheel_commands[sequence] = self.bind_class(
                self._wheel_tag, sequence, self._on_mousewheel)
        self._map_binding = self._toplevel.bind('<Map>', self._on_map, add='+')
        self.canvas.bind('<Configure>', self._schedule_sync, add='+')
        self.content.bind('<Configure>', self._schedule_sync, add='+')
        self.bind('<Destroy>', self._on_destroy, add='+')
        self._bind_descendants(self)
        self._schedule_sync()

    def _belongs_to_view(self, widget):
        while isinstance(widget, tk.Misc):
            if widget is self:
                return True
            widget = getattr(widget, 'master', None)
        return False

    def _uses_native_wheel(self, widget):
        """Do not steal selection changes or a nested table/text scroll."""
        while isinstance(widget, tk.Misc) and widget is not self:
            if isinstance(widget, ScrollableResults) and widget is not self:
                return True
            if widget.winfo_class() in self._NATIVE_WHEEL_CLASSES:
                return True
            widget = getattr(widget, 'master', None)
        return False

    def _bind_descendants(self, widget):
        if self._closed:
            return
        try:
            if isinstance(widget, ScrollableResults) and widget is not self:
                return
            if not self._uses_native_wheel(widget):
                tags = widget.bindtags()
                if self._wheel_tag not in tags:
                    widget.bindtags((self._wheel_tag,) + tags)
            for child in widget.winfo_children():
                self._bind_descendants(child)
        except tk.TclError:
            # A figure may be replaced between a geometry notification and
            # the idle update. Its replacement is bound when it is mapped.
            return

    def _on_map(self, event):
        if not self._closed and self._belongs_to_view(event.widget):
            self._bind_descendants(event.widget)
            self._schedule_sync()

    def _schedule_sync(self, _event=None):
        if not self._closed and self._sync_job is None:
            # Match the application's top-level timer ownership. If a test or
            # shutdown helper cancels top-level idle jobs, the Tcl command is
            # then removed from the same widget's bookkeeping as registered.
            self._sync_job = self._toplevel.after_idle(self.sync)

    def _viewport_width(self):
        width = self.canvas.winfo_width()
        if width > 1:
            self._last_viewport_width = width
            return width
        # An unvisited notebook page has a 1 px Canvas. Propagating that
        # sentinel width reaches FigureCanvasTkAgg's resize handler and turns
        # a useful figure into a 0.01-inch figure before its first visit.
        if self._last_viewport_width:
            return self._last_viewport_width
        ancestor = self.master
        while isinstance(ancestor, tk.Misc):
            width = ancestor.winfo_width()
            if width > 1:
                return max(160, width - self.scrollbar.winfo_reqwidth())
            ancestor = getattr(ancestor, 'master', None)
        # Size the Canvas window, not the Canvas request: the latter must
        # remain flexible so a hidden large figure cannot widen the app.
        return 900

    def sync(self):
        """Refresh the scroll extent and wheel routes after a layout change."""
        if self._closed:
            return
        if self._sync_job is not None:
            self._toplevel.after_cancel(self._sync_job)
            self._sync_job = None
        try:
            width = self._viewport_width()
            self.canvas.itemconfigure(self._window_id, width=width)
            if not (self.content.pack_slaves() or self.content.grid_slaves()
                    or self.content.place_slaves()):
                # Tk keeps the previous requested size when the last managed
                # child disappears. Reset that otherwise-empty host explicitly
                # so replacing a six-rail figure does not leave a blank page.
                self.content.configure(height=1)
            # Requested height, unlike the previous canvas bounding box,
            # already reflects panels that were hidden or destroyed.
            requested = self.content.winfo_reqheight()
            height = max(requested, self.canvas.winfo_height())
            self.canvas.configure(scrollregion=(0, 0, width, max(1, height)))
            if requested <= self.canvas.winfo_height():
                self.canvas.yview_moveto(0)
            self._bind_descendants(self)
        except tk.TclError:
            return

    def _on_mousewheel(self, event):
        if self._closed:
            return None
        try:
            widget = event.widget
            if (not self._belongs_to_view(widget)
                    or self._uses_native_wheel(widget)
                    or not self.winfo_viewable() or not widget.winfo_viewable()):
                return None
            start, end = self.canvas.yview()
            if end - start >= .999999:
                return None
            number = getattr(event, 'num', None)
            if number == 4:
                steps = -3
            elif number == 5:
                steps = 3
            else:
                delta = getattr(event, 'delta', 0)
                if not delta:
                    return None
                steps = -int(delta / 120) if abs(delta) >= 120 else (-1 if delta > 0 else 1)
                steps *= 3
            self.canvas.yview_scroll(steps, 'units')
            return 'break'
        except (tk.TclError, AttributeError, TypeError):
            return None

    def _on_destroy(self, event):
        if event.widget is not self or self._closed:
            return
        self._closed = True
        if self._sync_job is not None:
            try:
                self._toplevel.after_cancel(self._sync_job)
            except tk.TclError:
                pass
            self._sync_job = None
        try:
            self._toplevel.unbind('<Map>', self._map_binding)
        except tk.TclError:
            pass
        for sequence, command in self._wheel_commands.items():
            try:
                self.unbind_class(self._wheel_tag, sequence)
                # bind_class registers on the interpreter's root, not self.
                # Remove it there as well so the root does not try to delete
                # the same Tcl command for a second time during shutdown.
                self._root().deletecommand(command)
            except tk.TclError:
                pass
        self._wheel_commands.clear()
