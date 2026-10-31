"""Own-window checks for on-demand loop loading and numerical cache reuse."""
import copy
from pathlib import Path
import sys
import time
import tkinter as tk
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import main


class ResourceGUIChecks(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.root = tk.Tk()
        cls.root.withdraw()
        cls.errors = []
        cls.root.report_callback_exception = lambda *exc: cls.errors.append(exc)
        with patch.object(main.PowerSupplyAnalyzer, 'schedule_update', return_value=None):
            cls.app = main.PowerSupplyAnalyzer(cls.root)
        for job in cls.root.tk.splitlist(cls.root.tk.call('after', 'info')):
            cls.root.after_cancel(job)
        cls.app._initial_update_job = None
        cls.config = copy.deepcopy(cls.app._config_dict())

    @classmethod
    def tearDownClass(cls):
        cls.app._closing = True
        cls.app._calculation_worker.close()
        for job in cls.root.tk.splitlist(cls.root.tk.call('after', 'info')):
            cls.root.after_cancel(job)
        cls.root.destroy()

    def setUp(self):
        self.app._apply_config(copy.deepcopy(self.config))
        self.app.nb.select(self.app.tab_topology)
        self.assertTrue(self.app.update_all(), self.app.status_var.get())
        self.errors.clear()

    def tearDown(self):
        self.assertEqual(self.errors, [])

    def test_default_page_does_not_start_control_background_work(self):
        app = self.app
        app._control_ready = False
        with patch.object(app, '_start_control_warmup') as warmup:
            app._rendered_tabs.clear()
            app._refresh_visible_tab()
            self.assertFalse(warmup.called)
        self.assertIsNone(app._control_warmup_job)
        self.assertFalse(app._control_loading)

    def test_loop_numeric_result_reused_for_redraw_not_for_new_parameters(self):
        from loop_tuning import analyze_loop
        app = self.app
        app._loop_result = app._loop_signature = None
        with patch('loop_tuning.analyze_loop', wraps=analyze_loop) as analyze:
            app._update_loop(app._last['p'], draw=False)
            first = app._loop_result
            self.assertIsNotNone(first, app.loop_esr_note.get())
            app._update_loop(app._last['p'], draw=True)
            app._update_loop(app._last['p'], draw=False)
            self.assertEqual(analyze.call_count, 1)
            self.assertIs(app._loop_result, first)
            app.set_param('V_in', app._last['p']['V_in'] + 1.)
            self.assertTrue(app.update_all(), app.status_var.get())
            # Revisiting a hidden page must not have done loop work yet.
            self.assertEqual(analyze.call_count, 1)
            app._update_loop(app._last['p'], draw=False)
            self.assertEqual(analyze.call_count, 2)
            self.assertIsNot(app._loop_result, first)

    def test_review_completes_current_loop_checks_after_hidden_design_change(self):
        from loop_tuning import analyze_loop
        app = self.app
        app._update_loop(app._last['p'], draw=False)
        old_signature = app._loop_signature
        app.set_param('V_in', app._last['p']['V_in'] + 2.)
        self.assertTrue(app.update_all(), app.status_var.get())
        self.assertNotEqual(main.parameter_signature(app._last['p']), old_signature)
        app.nb.select(app.tab_review)
        with patch('loop_tuning.analyze_loop', wraps=analyze_loop) as analyze:
            app._refresh_visible_tab()
            self.assertEqual(analyze.call_count, 1)
        self.assertEqual(main.parameter_signature(app._last['p']), app._loop_signature)
        self.assertIn('phase_margin', {c['id'] for c in app._last['checks']})
        self.assertIs(app._last['res']['loop'], app._loop_result)

    def test_failed_control_import_stops_polling_and_reports_error(self):
        import builtins
        real_import = builtins.__import__
        app = self.app
        app._control_ready = False

        def fail_control(name, *args, **kwargs):
            if name == 'control':
                raise ImportError('deliberate dependency failure')
            return real_import(name, *args, **kwargs)

        with patch('builtins.__import__', side_effect=fail_control):
            app._start_control_warmup()
            deadline = time.monotonic() + 3.
            while app._control_poll_job is not None:
                self.root.update()
                self.assertLess(time.monotonic(), deadline)
                time.sleep(.005)
        self.assertFalse(app._control_loading)
        self.assertIn('deliberate dependency failure', app.loop_esr_note.get())
        self.assertIsNone(app._control_poll_job)
        app._control_error = None


if __name__ == '__main__':
    unittest.main(verbosity=2)
