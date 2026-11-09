"""Latest-only numerical scheduling, stale isolation, cache and Tk heartbeat."""
import copy
from pathlib import Path
import queue
import sys
import threading
import time
import tkinter as tk
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from calculation_scheduler import (CalculationCancelled, LatestCalculationWorker,
    calculate_efficiency_curve, calculate_report_efficiency_curve, check_calculation_cancelled,
    current_calculation_cancelled, parameter_signature)


def wait_until(predicate, timeout=3.):
    deadline = time.monotonic() + timeout
    while not predicate():
        if time.monotonic() >= deadline:
            raise AssertionError('Background worker did not reach the expected state')
        time.sleep(.005)


class SchedulerChecks(unittest.TestCase):
    def setUp(self):
        self.worker = LatestCalculationWorker(cache_size=2)

    def tearDown(self):
        self.worker.close()

    def test_replaces_pending_jobs_and_never_publishes_stale_success(self):
        started, release = threading.Event(), threading.Event()
        executed = []

        def calculate(parameters, _cancelled):
            executed.append(parameters['id'])
            if parameters['id'] == 1:
                started.set()
                release.wait(2)
            return parameters['id']

        self.worker.submit('design', {'id': 1}, calculate)
        self.assertTrue(started.wait(1))
        for i in range(2, 11):
            last = self.worker.submit('design', {'id': i}, calculate)
        release.set()
        wait_until(lambda: not self.worker.busy)
        result = self.worker.results.get_nowait()
        self.assertEqual(executed, [1, 10])
        self.assertEqual((result.generation, result.value), (last, 10))
        self.assertTrue(self.worker.results.empty())

    def test_stale_error_and_cancelled_work_never_reach_gui(self):
        started, release = threading.Event(), threading.Event()

        def bad(_parameters, _cancelled):
            started.set(); release.wait(2)
            raise ValueError('obsolete invalid design')

        self.worker.submit('design', {}, bad)
        self.assertTrue(started.wait(1))
        self.worker.invalidate()
        release.set()
        wait_until(lambda: not self.worker.busy)
        self.assertTrue(self.worker.results.empty())

    def test_cooperative_cancellation_hook_and_main_thread_isolation(self):
        started = threading.Event()

        def loop(_parameters, _cancelled):
            started.set()
            while True:
                check_calculation_cancelled()
                time.sleep(.005)

        self.worker.submit('design', {}, loop)
        self.assertTrue(started.wait(1))
        self.worker.invalidate()
        wait_until(lambda: not self.worker.busy)
        self.assertFalse(current_calculation_cancelled())
        check_calculation_cancelled()
        self.assertTrue(self.worker.results.empty())

    def test_real_coupled_solver_cooperatively_cancels_obsolete_work(self):
        import coupled_flyback as coupled
        from power_stage import DEFAULT_PARAMS
        from loss_model import compute_design
        p = copy.deepcopy(DEFAULT_PARAMS)
        p.update(topology='FLYBACK', feedback_mode='SSR', feedback_output=1,
                 outputs=[dict(V_out=v, P_out=w, Ns=0.) for v, w in
                          zip((30., 12., 5., 3.3, 24., 15.), (20., 8., 4., 2., 4., 2.))],
                 coupling_config=dict(enabled=True, k=[], dcr=[]))
        started, release, cancelled = threading.Event(), threading.Event(), threading.Event()
        coupled._periodic_solution.cache_clear()
        original_cycle = coupled._Circuit.cycle

        def enter_cycle(circuit, *args, **kwargs):
            # Synchronize at real numerical work, rather than assuming it is
            # still running after an arbitrary delay on every machine.
            started.set()
            if not release.wait(2):
                raise AssertionError('Cancellation test did not release solver')
            return original_cycle(circuit, *args, **kwargs)

        def solve(parameters, _cancelled):
            try:
                return compute_design(parameters)
            except CalculationCancelled:
                cancelled.set()
                raise

        with patch.object(coupled._Circuit, 'cycle', enter_cycle):
            try:
                self.worker.submit('design', p, solve)
                self.assertTrue(started.wait(2))
                self.assertTrue(self.worker.busy)
                before = time.monotonic()
                self.worker.invalidate()
            finally:
                release.set()
            wait_until(lambda: not self.worker.busy, timeout=1.5)
        self.assertLess(time.monotonic() - before, 1.)
        self.assertTrue(cancelled.is_set())
        self.assertTrue(self.worker.results.empty())

    def test_cache_is_bounded_and_owns_independent_copies(self):
        calls = []

        def compute(parameters, _cancelled):
            calls.append(parameters['id'])
            return {'items': [parameters['id']]}

        for i in (1, 2, 2, 3):
            self.worker.submit('design', {'id': i}, compute, cache=True)
            wait_until(lambda: not self.worker.busy)
            result = self.worker.results.get_nowait()
            if i == 2:
                result.value['items'].append('UI changed this')
        self.assertEqual(calls, [1, 2, 3])
        self.assertIsNone(self.worker.cached('design', {'id': 1}))
        self.assertEqual(self.worker.cached('design', {'id': 2}), {'items': [2]})

    def test_input_snapshot_does_not_follow_later_mutation(self):
        original = {'id': [3]}
        started, release = threading.Event(), threading.Event()

        def compute(parameters, _cancelled):
            started.set(); release.wait(2)
            return parameters['id']

        self.worker.submit('design', original, compute)
        self.assertTrue(started.wait(1))
        original['id'][0] = 100
        release.set()
        wait_until(lambda: not self.worker.busy)
        self.assertEqual(self.worker.results.get_nowait().value, [3])

    def test_close_does_not_wait_for_an_uncancellable_library_call(self):
        started, release = threading.Event(), threading.Event()

        def compute(_parameters, _cancelled):
            started.set(); release.wait(2)
            return 1

        generation = self.worker.submit('design', {}, compute)
        self.assertTrue(started.wait(1))
        before = time.monotonic()
        self.worker.close()
        self.assertLess(time.monotonic() - before, .1)
        self.assertFalse(self.worker.is_current(generation))
        release.set()
        wait_until(lambda: not self.worker.busy)
        self.assertTrue(self.worker.results.empty())
        with self.assertRaises(RuntimeError):
            self.worker.submit('design', {}, compute)

    def test_signature_is_stable_but_changes_for_electrical_inputs(self):
        self.assertEqual(parameter_signature({'a': 1, 'b': [2], '__meta': 'view'}),
                         parameter_signature({'b': [2], 'a': 1}))
        self.assertNotEqual(parameter_signature({'Kc': 1.5}), parameter_signature({'Kc': 2.}))

    def test_efficiency_curve_leaves_failed_point_blank_and_cancels(self):
        import numpy as np
        from power_stage import DEFAULT_PARAMS
        calls = []

        def compute(parameters):
            calls.append(parameters['P_out'])
            if len(calls) == 2:
                raise ValueError('deliberately invalid operating point')
            return {'eta': .9}

        with patch('loss_model.compute_design', side_effect=compute):
            result = calculate_efficiency_curve(copy.deepcopy(DEFAULT_PARAMS), lambda: False, n_pts=3)
            self.assertEqual(len(calls), 3)
            self.assertTrue(np.isnan(result['etas'][1]))
            self.assertEqual(len(result['failures']), 1)
            with self.assertRaises(CalculationCancelled):
                calculate_efficiency_curve(copy.deepcopy(DEFAULT_PARAMS), lambda: True)

    def test_report_curve_keeps_original_grid_modes_and_failures(self):
        import numpy as np
        from power_stage import DEFAULT_PARAMS
        for coupled, count in ((True, 5), (False, 19)):
            calls = []

            def compute(parameters):
                calls.append(parameters['P_out'])
                if len(calls) == 2:
                    raise ValueError('invalid branch')
                return {'eta': .91, 'op': {'mode': 'CCM'}}

            with patch('loss_model.compute_design', side_effect=compute):
                result = calculate_report_efficiency_curve(
                    {'p': copy.deepcopy(DEFAULT_PARAMS), 'coupled': coupled}, lambda: False)
            self.assertEqual(len(calls), count)
            self.assertAlmostEqual(result['fracs'][0], .1)
            self.assertAlmostEqual(result['fracs'][-1], 1.)
            self.assertEqual(len(result['modes']), count)
            self.assertEqual(result['modes'][1], '无效')
            self.assertTrue(np.isnan(result['etas'][1]))
            self.assertEqual(result['etas'][0], .91)
            self.assertEqual(len(result['failures']), 1)

    def test_test_owned_tk_window_keeps_processing_heartbeats(self):
        root = tk.Tk()
        root.withdraw()
        heartbeats, threads = [], []
        errors = []
        root.report_callback_exception = lambda *error: errors.append(error)
        finished = threading.Event()
        before = time.monotonic()

        def slow(_parameters, cancelled):
            threads.append(threading.get_ident())
            until = time.monotonic() + .55
            while time.monotonic() < until:
                # A CPU-heavy Python loop also exercises GIL contention.
                sum(i*i for i in range(1200))
                if cancelled():
                    raise CalculationCancelled()
            return 42

        def heartbeat():
            heartbeats.append(time.monotonic())
            if not finished.is_set():
                root.after(15, heartbeat)

        try:
            self.worker.submit('design', {}, slow)
            root.after(1, heartbeat)
            while self.worker.busy or self.worker.results.empty():
                root.update()
                if time.monotonic() - before > 3:
                    self.fail('Tk heartbeat test timed out')
                time.sleep(.002)
            finished.set()
            result = self.worker.results.get_nowait()
            self.assertEqual(result.value, 42)
            self.assertGreater(len(heartbeats), 8)
            self.assertNotEqual(threads[0], threading.get_ident())
            self.assertLess(max(b-a for a, b in zip(heartbeats, heartbeats[1:])), .2)
            self.assertEqual(errors, [])
        finally:
            finished.set()
            for job in root.tk.splitlist(root.tk.call('after', 'info')):
                root.after_cancel(job)
            root.destroy()


class GUIIntegrationChecks(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        import main
        cls.main = main
        cls.root = tk.Tk()
        cls.root.withdraw()
        with patch.object(main.PowerSupplyAnalyzer, 'schedule_update', return_value=None):
            cls.app = main.PowerSupplyAnalyzer(cls.root)
        for job in cls.root.tk.splitlist(cls.root.tk.call('after', 'info')):
            cls.root.after_cancel(job)
        cls.app._initial_update_job = cls.app._control_warmup_job = None
        cls.config = copy.deepcopy(cls.app._config_dict())
        cls.errors = []
        cls.root.report_callback_exception = lambda *error: cls.errors.append(error)

    @classmethod
    def tearDownClass(cls):
        cls.app._closing = True
        cls.app._calculation_worker.close()
        for job in cls.root.tk.splitlist(cls.root.tk.call('after', 'info')):
            cls.root.after_cancel(job)
        cls.root.destroy()

    def setUp(self):
        self.app.cancel_calculation()
        wait_until(lambda: not self.app._calculation_worker.busy)
        self.app._apply_config(copy.deepcopy(self.config))
        self.app.nb.select(self.app.tab_topology)
        self.assertTrue(self.app.update_all(), self.app.status_var.get())
        self.errors.clear()

    def pump_until(self, predicate, timeout=10):
        deadline = time.monotonic() + timeout
        while not predicate():
            self.root.update()
            if time.monotonic() > deadline:
                self.fail('GUI async completion timed out: ' + self.app.status_var.get())
            time.sleep(.004)
        self.root.update()
        self.assertEqual(self.errors, [])

    def test_async_design_only_publishes_latest_parameters_on_tk_thread(self):
        app = self.app
        started, release = threading.Event(), threading.Event()
        published_threads, executed = [], []
        from loss_model import compute_design as real_compute
        real_publish = app._publish_design

        def compute(parameters):
            executed.append(parameters['V_in'])
            if parameters['V_in'] == 31:
                started.set(); release.wait(3)
            return real_compute(parameters)

        def publish(parameters, result, **kwargs):
            published_threads.append(threading.get_ident())
            return real_publish(parameters, result, **kwargs)

        with patch('loss_model.compute_design', side_effect=compute), \
                patch.object(app, '_publish_design', side_effect=publish):
            app.set_param('V_in', 31.)
            before = time.monotonic()
            self.assertTrue(app.request_update())
            self.assertLess(time.monotonic() - before, .2)
            self.assertFalse(app._snapshot_valid)
            self.pump_until(started.is_set)
            for voltage in (32., 33., 34.):
                app.set_param('V_in', voltage)
                app.request_update()
            release.set()
            self.pump_until(lambda: app._snapshot_valid)
        self.assertEqual(executed, [31., 34.])
        self.assertEqual(app._last['p']['V_in'], 34.)
        self.assertEqual(published_threads, [threading.get_ident()])

    def test_actual_six_output_coupled_solve_keeps_tk_heartbeat_alive(self):
        from coupled_flyback import _periodic_solution
        from power_stage import DEFAULT_PARAMS
        _periodic_solution.cache_clear()
        p = copy.deepcopy(DEFAULT_PARAMS)
        p.update(topology='FLYBACK', feedback_mode='SSR', feedback_output=1,
                 outputs=[dict(V_out=v, P_out=w, Ns=0.) for v, w in
                          zip((30., 12., 5., 3.3, 24., 15.), (20., 8., 4., 2., 4., 2.))],
                 coupling_config=dict(enabled=True, k=[], dcr=[]))
        app = self.app
        app._apply_config(p)
        app.nb.select(app.tab_topology)
        beats, completed, publish_times, compute_times = [], threading.Event(), [], []
        original_publish = app._publish_design
        from input_voltage_range import calculate_input_operating_point

        def calculate(*args, **kwargs):
            compute_times.append(time.monotonic())
            return calculate_input_operating_point(*args, **kwargs)

        def publish(parameters, result, **kwargs):
            publish_times.append(time.monotonic())
            return original_publish(parameters, result, **kwargs)

        def heartbeat():
            beats.append(time.monotonic())
            if not completed.is_set():
                self.root.after(20, heartbeat)

        self.root.after(1, heartbeat)
        before = time.monotonic()
        try:
            with patch.object(app, '_publish_design', side_effect=publish), \
                    patch('input_voltage_range.calculate_input_operating_point', side_effect=calculate):
                self.assertTrue(app.request_update())
                self.pump_until(lambda: app._snapshot_valid, timeout=35)
        finally:
            completed.set()
        finished = time.monotonic()
        elapsed = finished - before
        observed = [before, *beats, finished]
        gaps = [b-a for a, b in zip(observed, observed[1:])]
        compute_beats = [beat for beat in beats if compute_times[0] <= beat < publish_times[0]]
        compute_observed = [compute_times[0], *compute_beats, publish_times[0]]
        compute_gaps = [b-a for a, b in zip(compute_observed, compute_observed[1:])]
        print(f'\n6-rail physical solve: {elapsed:.3f}s; '
              f'Tk heartbeats={len(beats)}; max gap={max(gaps)*1000:.1f}ms; '
              f'pre-publish max gap={max(compute_gaps, default=0)*1000:.1f}ms', flush=True)
        # Faster solves need fewer heartbeats. Bound the actual unresponsive
        # interval, including the start-to-first-beat gap previously omitted.
        self.assertGreater(len(compute_beats), 0)
        self.assertLess(max(compute_gaps), .35)
        # This covers both the solve and final main-thread Matplotlib redraw.
        # Allow machine/load variance while rejecting a whole-solve UI freeze.
        self.assertLess(max(gaps), 1.25)
        self.assertEqual(len(app._last['res']['outputs']), 6)
        self.assertTrue(app._last['op']['coupled_model']['converged'])

    def test_current_failure_clears_validity_and_old_failures_do_not_apply(self):
        app = self.app
        app.set_param('V_in', 35.)
        with patch('loss_model.compute_design', side_effect=ValueError('new invalid design')):
            app.request_update()
            self.pump_until(lambda: not app._calculation_worker.busy and
                            app.status_var.get().startswith('Error:'))
        self.assertFalse(app._snapshot_valid)
        self.assertIn('new invalid design', app.status_var.get())
        self.assertTrue(all('未计算' in var.get() for var in app.margin_info.values()))

    def test_efficiency_curve_does_not_block_the_gui_and_stale_curve_is_rejected(self):
        app = self.app
        started, release = threading.Event(), threading.Event()
        def slow_curve(_parameters, cancelled):
            started.set(); release.wait(3)
            return {'fracs': [], 'etas': [], 'failures': [], 'obsolete': True}
        last = app._last
        with patch.object(self.main, 'calculate_efficiency_curve', side_effect=slow_curve):
            before = time.monotonic()
            app._update_eff(last['op'], last['p'], last['res'])
            self.assertLess(time.monotonic() - before, .6)
            self.assertTrue(started.wait(1))
            app.set_param('V_in', 36.)
            app.request_update()
            release.set()
            self.pump_until(lambda: app._snapshot_valid)
        self.assertEqual(app._last['p']['V_in'], 36.)
        self.assertIsNone(app._eff_curve_result)

    def test_synchronous_contract_and_identical_design_cache_avoid_recompute(self):
        with patch.object(self.main, 'compute_design', side_effect=AssertionError('unnecessary solve')):
            self.assertTrue(self.app.update_all())
        self.assertTrue(self.app._snapshot_valid)

    def test_component_refresh_reuses_snapshot_and_invalidates_old_verdicts(self):
        app = self.app
        with patch.object(app, 'get_params', side_effect=AssertionError('view reread every Tk input')):
            app._refresh_components()
            self.assertIn('Q1', app.component_manager.rows)
            app._snapshot_valid = False
            app._refresh_components()
        self.assertEqual(app.component_manager.tree.set('Q1', 'status'), '待重新计算')

    def test_cancel_while_waiting_for_layout_never_starts_numerical_work(self):
        app = self.app
        app.set_param('V_in', 42.)
        app._schedule_parameter_scrollregion()
        with patch('input_voltage_range.calculate_input_operating_point') as calculate:
            self.assertTrue(app.request_update())
            self.assertIsNotNone(app._design_ready_job)
            app.cancel_calculation()
            wait_until(lambda: not app._calculation_worker.busy)
            calculate.assert_not_called()
        self.assertIsNone(app._design_ready_job)
        self.assertTrue(app._calculation_worker.results.empty())

    def test_font_resize_does_not_schedule_a_physical_solve(self):
        with patch.object(self.app, 'schedule_update') as schedule, \
                patch.object(self.app, '_refresh_visible_tab') as refresh:
            self.app._apply_scale(self.app._font_k)
        schedule.assert_not_called()
        refresh.assert_called_once()

    def test_gui_report_precomputes_curve_in_worker_and_does_not_repeat_design(self):
        app = self.app
        started, release = threading.Event(), threading.Event()
        threads = []
        curve = {'fracs': [.1, 1.], 'etas': [.8, .9], 'modes': ['DCM', 'CCM'], 'failures': []}
        bundle = {'cases': [dict(id=case, efficiency_curve=curve) for case in ('Vinmin','Vinmax')]}

        def report_curve(_request, _cancelled):
            threads.append(threading.get_ident())
            started.set(); release.wait(3)
            return bundle

        # Report preparation now batches both voltage endpoints, rather than
        # returning one efficiency curve. Assert the current public boundary.
        with patch.object(self.main, '_calculate_input_report', side_effect=report_curve), \
                patch.object(app, 'export_report') as export, \
                patch.object(self.main, 'compute_design', side_effect=AssertionError('repeated design solve')):
            before = time.monotonic()
            app._export_report_ui()
            self.assertLess(time.monotonic() - before, .2)
            self.assertTrue(started.wait(1))
            generation = app._calculation_worker.generation
            # Visiting efficiency while preparing a report must not replace it.
            app._update_eff(app._last['op'], app._last['p'], app._last['res'])
            self.assertEqual(app._calculation_worker.generation, generation)
            release.set()
            self.pump_until(lambda: export.called)
        self.assertNotEqual(threads[0], threading.get_ident())
        self.assertFalse(export.call_args.kwargs['recompute'])
        self.assertEqual(export.call_args.kwargs['range_result'], bundle)
        self.assertFalse(app._export_after_calculation)

    def test_editing_cancels_old_report_and_never_opens_its_save_dialog(self):
        app = self.app
        started, release = threading.Event(), threading.Event()

        def report_curve(_request, _cancelled):
            started.set(); release.wait(3)
            return {'fracs': [.1], 'etas': [.8], 'modes': ['CCM'], 'failures': []}

        # Use an uncached request to exercise rejection of a running batch.
        app.set_param('V_in', 38.)
        self.assertTrue(app.update_all())
        with patch.object(self.main, '_calculate_input_report', side_effect=report_curve), \
                patch.object(app, 'export_report') as export:
            app._export_report_ui()
            self.assertTrue(started.wait(1))
            app.set_param('V_in', 39.)
            self.assertFalse(app._export_after_calculation)
            app.request_update()
            release.set()
            self.pump_until(lambda: app._snapshot_valid)
            export.assert_not_called()


if __name__ == '__main__':
    unittest.main(verbosity=2)
