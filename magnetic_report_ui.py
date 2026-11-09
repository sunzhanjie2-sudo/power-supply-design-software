"""Scrollable aligned magnetic report with explicit, coloured conclusions."""
import copy
import tkinter as tk
from tkinter import ttk

from magnetic_report_view import as_text
from scrollable_results import ScrollableResults

COLORS = dict(success='#12724c', danger='#b42318', warning='#956000')
STATES = dict(success='通过', danger='超限', warning='待复核')


class MagneticReport(ttk.Frame):
    def __init__(self, parent):
        super().__init__(parent)
        self._view = None
        self._wrapped = []
        heading = ttk.Frame(self, padding=(9, 6))
        heading.pack(fill='x')
        ttk.Label(heading, text='磁件设计报告', font='TkHeadingFont').pack(side='left')
        ttk.Button(heading, text='复制报告', command=self._copy).pack(side='right')
        self.scroll = ScrollableResults(self, background='#ffffff')
        self.scroll.pack(fill='both', expand=True)
        self.scroll.content.bind('<Configure>', self._rewrap, add='+')

    def _label(self, parent, text, *, color='#243649', bold=False, fraction=1., **grid):
        label = tk.Label(parent, text=text, background=parent.cget('background'),
                         foreground=color, font='TkHeadingFont' if bold else 'TkDefaultFont',
                         justify='left', anchor='nw', borderwidth=0)
        label.grid(sticky='new', **grid)
        self._wrapped.append((label, fraction))
        return label

    def render(self, view):
        if view == self._view:
            return
        self._view = copy.deepcopy(view)
        self._wrapped.clear()
        for child in self.scroll.content.winfo_children():
            child.destroy()
        summary = tk.Frame(self.scroll.content, background='#f3f6fa', padx=10, pady=8)
        summary.pack(fill='x', padx=5, pady=(2, 8))
        summary.columnconfigure(0, weight=1)
        self._label(summary, view['summary'], color='#506277', row=0, column=0)
        for i, c in enumerate(view['conclusions'], 1):
            color = COLORS[c['state']]
            self._label(summary, f"{STATES[c['state']]} · {c['device']} · {c['title']}",
                        color=color, bold=True, row=i*2-1, column=0, pady=(9, 2))
            self._label(summary, c['detail'], color=color, bold=True, row=i*2, column=0)
        for section in view['sections']:
            card = tk.Frame(self.scroll.content, background='#ffffff', padx=10, pady=8)
            card.pack(fill='x', padx=5, pady=(0, 7))
            card.columnconfigure(0, weight=1, uniform='row')
            card.columnconfigure(1, weight=1, uniform='row')
            self._label(card, section['title'], color='#1558b0', bold=True,
                        row=0, column=0, columnspan=2, pady=(0, 8))
            for i, r in enumerate(section['rows'], 1):
                self._label(card, r['label'], color='#5b6878', fraction=.45,
                            row=i, column=0, padx=(0, 8), pady=4)
                value = self._label(card, (r['value'] + ' ' + r['unit']).rstrip(), fraction=.45,
                                    row=i, column=1, pady=4)
                value.configure(anchor='ne', justify='right')
            if section['note']:
                self._label(card, section['note'], color='#66768a', row=len(section['rows'])+1,
                            column=0, columnspan=2, pady=(9, 1))
        self._rewrap()
        self.scroll._schedule_sync()

    def _rewrap(self, _event=None):
        width = max(160, self.scroll.content.winfo_width()-40)
        for label, fraction in self._wrapped:
            target = int(width*fraction)
            if label.cget('wraplength') != target:
                label.configure(wraplength=target)

    def get(self, _start='1.0', _end='end'):
        """Readable plain text for clipboard and existing result consumers."""
        return as_text(self._view) if self._view else ''

    def _copy(self):
        self.clipboard_clear()
        self.clipboard_append(self.get())
