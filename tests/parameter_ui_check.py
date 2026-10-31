"""Real Tk regressions for parameter folding and tooltip ownership.

Every test window belongs to this process and is transparent. The suite never
reads another app, moves the pointer, or changes another window's focus.
"""
from pathlib import Path
import sys
import time
import tkinter as tk
from tkinter import ttk
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from engineering_ui import Tooltip

TOPLEVEL_CLASS = tk.Toplevel


def pending_jobs(root):
    return set(root.tk.splitlist(root.tk.call('after', 'info')))


def pump(root, seconds=0):
    until = time.monotonic() + seconds
    while True:
        root.update()
        if time.monotonic() >= until:
            return
        time.sleep(.01)


def popups(root):
    found = []
    def visit(widget):
        for child in widget.winfo_children():
            if isinstance(child, TOPLEVEL_CLASS):
                found.append(child)
            visit(child)
    visit(root)
    return found


class TooltipChecks(unittest.TestCase):
    def setUp(self):
        self.root = tk.Tk()
        self.root.attributes('-alpha', 0)
        self.root.geometry('300x120')
        self.errors = []
        self.root.report_callback_exception = lambda *exc: self.errors.append(exc)
        self.frame = ttk.Frame(self.root)
        self.frame.pack(fill='both', expand=True)
        self.widget = ttk.Label(self.frame, text='test-owned target')
        self.widget.pack()
        self.tip = Tooltip(self.widget, 'test-owned tooltip')
        self.original_toplevel = tk.Toplevel
        self.popup_patch = patch('engineering_ui.tk.Toplevel', side_effect=self.hidden_popup)
        self.popup_patch.start()
        self.show_patch = patch.object(Tooltip, '_can_show', return_value=True)
        self.real_can_show = Tooltip._can_show
        self.show_patch.start()
        pump(self.root)

    def hidden_popup(self, *args, **kwargs):
        popup = self.original_toplevel(*args, **kwargs)
        popup.attributes('-alpha', 0)
        return popup

    def assert_clean(self):
        for tip in list(self.root._tooltip_instances):
            self.assertIsNone(tip.job)
            self.assertIsNone(tip.popup)
        self.assertEqual(popups(self.root), [])

    def tearDown(self):
        try:
            Tooltip.hide_all(self.root)
            pump(self.root)
            self.assertEqual(self.errors, [], 'A test-owned Tk callback failed')
        finally:
            self.popup_patch.stop()
            self.show_patch.stop()
            self.root.destroy()

    def test_repeated_enter_cancels_the_previous_delayed_callback(self):
        self.tip.enter(None)
        first = self.tip.job
        self.assertIn(first, pending_jobs(self.root))
        self.tip.enter(None)
        second = self.tip.job
        self.assertNotEqual(first, second)
        self.assertNotIn(first, pending_jobs(self.root))
        self.assertIn(second, pending_jobs(self.root))
        self.tip.leave()
        self.assertNotIn(second, pending_jobs(self.root))
        pump(self.root, .7)
        self.assert_clean()

    def test_show_twice_never_leaves_an_orphan_popup(self):
        self.tip.show()
        first = self.tip.popup
        self.tip.show()
        pump(self.root)
        self.assertEqual(len(popups(self.root)), 1)
        self.assertIsNotNone(self.tip.popup)
        if first is not self.tip.popup:
            self.assertFalse(first.winfo_exists())
        self.assertIs(self.tip.popup.master, self.root)
        self.assertNotIn(self.tip.popup, self.frame.winfo_children())
        self.tip.leave()
        self.assert_clean()

    def test_new_tip_replaces_other_active_tip_and_hide_all_cancels_pending(self):
        other = Tooltip(ttk.Label(self.frame, text='second target'), 'other')
        other.widget.pack()
        pump(self.root)
        self.tip.show()
        first = self.tip.popup
        other.show()
        pump(self.root)
        self.assertFalse(first.winfo_exists())
        self.assertIsNone(self.tip.popup)
        self.assertEqual(len(popups(self.root)), 1)
        self.tip.enter(None)
        self.assertIsNotNone(self.tip.job)
        Tooltip.hide_all(self.root)
        self.assert_clean()

    def test_widget_destroy_cleans_active_and_pending_tips(self):
        self.tip.show()
        popup = self.tip.popup
        self.widget.destroy()
        pump(self.root)
        self.assertFalse(popup.winfo_exists())
        self.assertIsNone(self.tip.popup)
        other = Tooltip(ttk.Label(self.frame, text='pending target'), 'pending')
        other.widget.pack()
        pump(self.root)
        other.enter(None)
        job = other.job
        other.widget.destroy()
        pump(self.root)
        self.assertIsNone(other.job)
        self.assertNotIn(job, pending_jobs(self.root))
        self.assertEqual(popups(self.root), [])

    def test_unmap_cleans_delayed_job_and_active_popup(self):
        self.tip.enter(None)
        job = self.tip.job
        self.widget.pack_forget()
        pump(self.root)
        self.assertIsNone(self.tip.job)
        self.assertNotIn(job, pending_jobs(self.root))
        self.widget.pack()
        pump(self.root)
        self.tip.show()
        self.widget.pack_forget()
        pump(self.root)
        self.assert_clean()

    def test_root_focus_out_cancels_tooltips_without_changing_real_focus(self):
        self.tip.show()
        self.root.event_generate('<FocusOut>', when='tail')
        pump(self.root)
        self.assert_clean()

    def test_hidden_or_unfocused_controls_cannot_display_a_stale_callback(self):
        with patch.object(Tooltip, '_can_show', self.real_can_show), \
                patch.object(self.root, 'focus_displayof', return_value=None):
            self.tip.show()
            self.assert_clean()
        with patch.object(Tooltip, '_can_show', self.real_can_show), \
                patch.object(self.widget, 'winfo_viewable', return_value=False):
            self.tip.show()
            self.assert_clean()

    def test_geometry_change_clears_a_pending_hint(self):
        self.tip.enter(None)
        self.root.event_generate('<Configure>', when='tail')
        pump(self.root)
        self.assert_clean()
        self.tip.enter(None)
        self.root.event_generate('<FocusOut>', when='tail')
        pump(self.root)
        self.assert_clean()


class ParameterLayoutChecks(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        import main
        cls.main = main
        cls.root = tk.Tk()
        cls.root.attributes('-alpha', 0)
        cls.update_patch = patch.object(main.PowerSupplyAnalyzer, 'schedule_update', return_value=None)
        cls.update_patch.start()
        cls.app = main.PowerSupplyAnalyzer(cls.root)
        # Resize styling must append rather than replace tooltip cleanup.
        cls.configure_bindings = cls.root.bind('<Configure>')
        cls.root.unbind('<Configure>')
        for job in pending_jobs(cls.root):
            cls.root.after_cancel(job)
        cls.root.geometry('1360x850')
        cls.root.update()
        cls.original_toplevel = tk.Toplevel

    @classmethod
    def tearDownClass(cls):
        cls.app._closing = True
        cls.app._work_cancel.set()
        Tooltip.hide_all(cls.root)
        for job in pending_jobs(cls.root):
            cls.root.after_cancel(job)
        cls.root.destroy()
        cls.update_patch.stop()

    def setUp(self):
        self.errors = []
        self.root.report_callback_exception = lambda *exc: self.errors.append(exc)
        Tooltip.hide_all(self.root)
        self.app._folded_sections.clear()
        self.app.param_search.set('')
        self.app.advanced_params.set(True)
        self.app.params['topology'].set(self.main.TOPO_LABEL['FLYBACK'])
        self.app._filter_params()
        self.app.left_canvas.yview_moveto(0)
        pump(self.root)
        self.assertTrue(self.root.winfo_ismapped())
        self.assertIsNone(self.app._last, 'This suite must not compute a design')

    def tearDown(self):
        Tooltip.hide_all(self.root)
        pump(self.root)
        self.assertEqual(self.errors, [], 'A parameter-panel Tk callback failed')

    def shell(self, section):
        return self.app._param_sections[section]._section_container

    def visible_order(self):
        names = {self.shell(key): key for key in self.app._param_sections}
        return [names[widget] for widget in self.app.left_inner.pack_slaves() if widget in names]

    def hidden_popup(self, *args, **kwargs):
        popup = self.original_toplevel(*args, **kwargs)
        popup.attributes('-alpha', 0)
        return popup

    def test_fold_reclaims_real_height_and_moves_the_next_section(self):
        self.assertIn('lambda', self.configure_bindings)
        self.assertIn('_on_root_resize', self.configure_bindings)
        frame = self.app._param_sections['spec']
        before = self.shell('spec').winfo_reqheight()
        next_before = self.shell('stage').winfo_y()
        self.app._fold_section(frame)
        pump(self.root)
        after = self.shell('spec').winfo_reqheight()
        self.assertLess(after, before / 2)
        self.assertGreater(after, 5)
        self.assertTrue(frame._section_header.winfo_ismapped())
        self.assertFalse(frame.winfo_ismapped())
        self.assertLess(self.shell('stage').winfo_y(), next_before - before / 2)
        self.app._fold_section(frame)
        pump(self.root)
        self.assertEqual(self.shell('spec').winfo_reqheight(), before)
        self.assertTrue(frame.winfo_ismapped())

    def test_folding_all_sections_reduces_the_scrollable_form_height(self):
        before = self.app.left_inner.winfo_reqheight()
        for frame in self.app._param_sections.values():
            self.app._fold_section(frame)
        pump(self.root)
        after = self.app.left_inner.winfo_reqheight()
        self.assertLess(after, before / 2)
        for key in self.visible_order():
            self.assertLess(self.shell(key).winfo_reqheight(), 100)
        bbox = self.app.left_canvas.bbox('all')
        self.assertLessEqual(bbox[3] - bbox[1], after + 2)

    def test_search_temporarily_expands_a_folded_section_then_restores_it(self):
        frame = self.app._param_sections['spec']
        self.app._fold_section(frame)
        pump(self.root)
        collapsed_height = self.shell('spec').winfo_reqheight()
        self.app.param_search.set('V_in')
        pump(self.root)
        self.assertIn(frame, self.app._folded_sections)
        self.assertTrue(frame.winfo_ismapped())
        self.assertTrue(self.app._param_widgets['V_in'][1].winfo_ismapped())
        self.assertGreater(self.shell('spec').winfo_reqheight(), collapsed_height)
        self.app.param_search.set('')
        pump(self.root)
        self.assertFalse(frame.winfo_ismapped())
        self.assertEqual(self.shell('spec').winfo_reqheight(), collapsed_height)

    def test_unmatched_search_hides_whole_sections_and_advanced_toggle_restores(self):
        self.app.param_search.set('unlikely_no_parameter_matches_847631')
        pump(self.root)
        self.assertEqual(self.visible_order(), [])
        self.app.param_search.set('')
        self.app.advanced_params.set(False)
        self.app._filter_params()
        pump(self.root)
        self.assertTrue(self.app._param_widgets['V_in'][1].winfo_ismapped())
        # The charge-model inputs are required, not advanced-only defaults.
        self.assertTrue(self.app._param_widgets['Qg_th'][1].winfo_ismapped())
        self.app.advanced_params.set(True)
        self.app._filter_params()
        pump(self.root)
        self.assertTrue(self.app._param_widgets['Qg_th'][1].winfo_ismapped())
        self.assertEqual(self.visible_order(),
                         ['spec', 'stage', 'device', 'capacitors', 'drive',
                          'sense', 'mag', 'ctrl'])

    def test_forward_topology_round_trip_keeps_container_order(self):
        expected = ['spec', 'stage', 'device', 'capacitors', 'drive',
                    'sense', 'mag', 'ctrl']
        for topology in ('ACF-FORWARD', 'FLYBACK', 'ACF-FORWARD'):
            self.app.params['topology'].set(self.main.TOPO_LABEL[topology])
            pump(self.root)
            self.assertEqual(self.visible_order(), expected)
            self.assertEqual(self.app._param_widgets['Lm_forward'][1].winfo_ismapped(),
                             topology == 'ACF-FORWARD')

    def test_hidden_parameter_and_scrollbar_actions_remove_tooltips(self):
        widget = self.app._param_widgets['V_in'][1]
        tip = next(t for t in self.root._tooltip_instances if t.widget is widget)
        with patch.object(Tooltip, '_can_show', return_value=True), \
                patch('engineering_ui.tk.Toplevel', side_effect=self.hidden_popup):
            tip.show()
            self.app._fold_section(self.app._param_sections['spec'])
            pump(self.root)
            self.assertIsNone(tip.popup)
            tip.enter(None)
            self.app._scroll_params('scroll', 1, 'units')
            self.assertIsNone(tip.job)
            self.app._fold_section(self.app._param_sections['spec'])
            pump(self.root)
            tip.show()
            self.app._scroll_params('moveto', .3)
            self.assertIsNone(tip.popup)
            self.assertEqual(popups(self.root), [])


if __name__ == '__main__':
    unittest.main(verbosity=2)
