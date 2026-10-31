"""Owned-window Tk regressions for long, dynamically populated result pages."""
from pathlib import Path
from types import SimpleNamespace
import sys
import tkinter as tk
from tkinter import ttk
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from scrollable_results import ScrollableResults


class ScrollableResultsChecks(unittest.TestCase):
    def setUp(self):
        self.root = tk.Tk()
        self.root.attributes('-alpha', 0)
        self.root.geometry('850x550')
        self.errors = []
        self.root.report_callback_exception = lambda *exc: self.errors.append(exc)
        self.left = ttk.Frame(self.root, width=150)
        self.left.pack(side='left', fill='y')
        self.left.pack_propagate(False)
        self.left_entry = ttk.Entry(self.left)
        self.left_entry.pack()
        self.notebook = ttk.Notebook(self.root)
        self.notebook.pack(side='left', fill='both', expand=True)
        self.first = ttk.Frame(self.notebook)
        self.second = ttk.Frame(self.notebook)
        self.notebook.add(self.first, text='results')
        self.notebook.add(self.second, text='other')
        self.view = ScrollableResults(self.first)
        self.view.pack(fill='both', expand=True)
        self.blocks = []
        for i in range(6):
            block = ttk.Frame(self.view.content, height=220)
            block.pack(fill='x', pady=(0, 8))
            block.pack_propagate(False)
            ttk.Label(block, text='OUT' + str(i + 1)).pack()
            self.blocks.append(block)
        self.root.update()
        self.view.sync()
        self.root.update()

    def tearDown(self):
        try:
            self.root.update()
            self.assertEqual(self.errors, [], 'A test-owned Tk callback failed')
        finally:
            self.root.destroy()

    def wheel(self, widget, *, delta=-120, num=None):
        return self.view._on_mousewheel(SimpleNamespace(widget=widget, delta=delta, num=num))

    def region(self):
        return tuple(map(float, self.view.canvas.cget('scrollregion').split()))

    def test_six_rows_keep_their_requested_heights(self):
        self.assertGreater(self.region()[3], 1300)
        self.assertTrue(all(block.winfo_height() == 220 for block in self.blocks))
        self.assertLess(self.view.canvas.yview()[1], 1)

    def test_viewport_width_follows_resize_without_compressing_rows(self):
        for width in (600, 1000, 700):
            self.root.geometry(f'{width}x400')
            self.root.update()
            self.view.sync()
            self.root.update()
            self.assertEqual(self.view.content.winfo_width(), self.view.canvas.winfo_width())
            self.assertTrue(all(block.winfo_height() == 220 for block in self.blocks))

    def test_fold_and_delete_retract_extent_and_scroll_position(self):
        self.view.canvas.yview_moveto(1)
        for block in self.blocks[1:]:
            block.pack_forget()
        self.root.update()
        self.view.sync()
        self.root.update()
        self.assertEqual(self.view.canvas.yview(), (0., 1.))
        self.assertLessEqual(self.region()[3], self.view.canvas.winfo_height())
        for block in self.blocks:
            block.destroy()
        self.root.update()
        self.view.sync()
        self.assertEqual(self.view.canvas.yview(), (0., 1.))

    def test_new_canvas_descendants_get_local_wheel_route(self):
        holder = ttk.Frame(self.view.content)
        holder.pack(fill='x')
        chart = tk.Canvas(holder, height=180)
        chart.pack(fill='x')
        self.root.update()
        self.assertIn(self.view._wheel_tag, chart.bindtags())
        self.assertEqual(self.wheel(chart), 'break')
        self.assertGreater(self.view.canvas.yview()[0], 0)

    def test_deleting_the_last_tall_chart_clears_tk_requested_size(self):
        for block in self.blocks:
            block.destroy()
        large = ttk.Frame(self.view.content, height=2400)
        large.pack(fill='x')
        self.root.update()
        self.assertGreater(self.view.content.winfo_reqheight(), 2000)
        large.destroy()
        self.root.update()
        self.view.sync()
        self.root.update()
        self.assertEqual(self.view.canvas.yview(), (0., 1.))
        self.assertLessEqual(self.region()[3], self.view.canvas.winfo_height())

    def test_mousewheel_does_not_touch_left_column(self):
        before = self.view.canvas.yview()
        self.assertIsNone(self.wheel(self.left_entry))
        self.assertNotIn(self.view._wheel_tag, self.left_entry.bindtags())
        self.assertEqual(before, self.view.canvas.yview())

    def test_combobox_and_native_scrollers_keep_their_wheel_handling(self):
        for cls in (ttk.Combobox, ttk.Spinbox, ttk.Treeview, tk.Text):
            widget = cls(self.blocks[0])
            widget.pack()
            self.root.update()
            before = self.view.canvas.yview()
            self.assertNotIn(self.view._wheel_tag, widget.bindtags())
            self.assertIsNone(self.wheel(widget))
            self.assertEqual(before, self.view.canvas.yview())
            widget.destroy()

    def test_hidden_notebook_page_does_not_scroll(self):
        self.notebook.select(self.second)
        self.root.update()
        before = self.view.canvas.yview()
        self.assertIsNone(self.wheel(self.blocks[0]))
        self.assertEqual(before, self.view.canvas.yview())

    def test_unvisited_notebook_page_never_compresses_figure_host_to_one_pixel(self):
        hidden = ScrollableResults(self.second)
        hidden.pack(fill='both', expand=True)
        figure_host = tk.Canvas(hidden.content, width=1120, height=600)
        figure_host.pack(fill='x')
        configured_widths = []
        figure_host.bind('<Configure>', lambda event: configured_widths.append(event.width))
        self.root.update()
        hidden.sync()
        self.root.update()
        self.assertFalse(hidden.winfo_viewable())
        self.assertGreater(float(hidden.canvas.itemcget(hidden._window_id, 'width')), 160)
        self.assertGreater(hidden.content.winfo_width(), 160)
        self.assertGreater(figure_host.winfo_width(), 160)
        self.assertTrue(all(width > 160 for width in configured_widths))
        self.notebook.select(self.second)
        self.root.update()
        hidden.sync()
        self.root.update()
        self.assertEqual(hidden.content.winfo_width(), hidden.canvas.winfo_width())
        self.assertLessEqual(figure_host.winfo_width(), hidden.canvas.winfo_width())

    def test_wheel_routes_only_one_page_and_never_changes_bind_all(self):
        all_before = {event: self.root.bind_all(event) for event in self.view._WHEEL_EVENTS}
        other = ScrollableResults(self.second)
        other.pack(fill='both', expand=True)
        ttk.Frame(other.content, height=2000).pack(fill='x')
        self.notebook.select(self.second)
        self.root.update()
        other.sync()
        first_before = self.view.canvas.yview()
        event = SimpleNamespace(widget=other.content, delta=-120, num=None)
        self.assertEqual(other._on_mousewheel(event), 'break')
        self.assertGreater(other.canvas.yview()[0], 0)
        self.assertEqual(first_before, self.view.canvas.yview())
        self.assertEqual(all_before, {event: self.root.bind_all(event) for event in self.view._WHEEL_EVENTS})

    def test_linux_wheel_and_actual_tk_event_dispatch(self):
        self.assertEqual(self.wheel(self.blocks[0], num=5), 'break')
        down = self.view.canvas.yview()[0]
        self.assertGreater(down, 0)
        self.assertEqual(self.wheel(self.blocks[0], num=4), 'break')
        self.assertLess(self.view.canvas.yview()[0], down)
        self.blocks[0].event_generate('<MouseWheel>', delta=-120)
        self.root.update()
        self.assertGreater(self.view.canvas.yview()[0], 0)

    def test_destroy_cleans_map_wheel_commands_and_pending_idle_job(self):
        self.view._schedule_sync()
        job = self.view._sync_job
        map_command = self.view._map_binding
        wheel_commands = tuple(self.view._wheel_commands.values())
        wheel_tag = self.view._wheel_tag
        self.assertIn(job, self.root.tk.splitlist(self.root.tk.call('after', 'info')))
        self.view.destroy()
        self.root.update()
        self.assertTrue(self.view._closed)
        self.assertNotIn(job, self.root.tk.splitlist(self.root.tk.call('after', 'info')))
        self.assertNotIn(map_command, self.root.bind('<Map>'))
        for command in (map_command,) + wheel_commands:
            self.assertEqual(self.root.tk.call('info', 'commands', command), '')
        for event in self.view._WHEEL_EVENTS:
            self.assertEqual(self.root.bind_class(wheel_tag, event), '')

    def test_top_level_shutdown_cancellation_does_not_leave_widget_commands(self):
        self.view._schedule_sync()
        job = self.view._sync_job
        self.root.after_cancel(job)
        # Application tests and shutdown helpers may cancel root-owned jobs
        # before recursively destroying children. This must not double-delete
        # a Tcl command retained in the result frame's private bookkeeping.
        self.view.destroy()
        self.root.update()
        self.assertTrue(self.view._closed)
        self.assertIsNone(self.view._sync_job)


if __name__ == '__main__':
    unittest.main(verbosity=2)
