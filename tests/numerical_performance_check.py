"""Accuracy, cancellation and cache ownership for numerical acceleration.

Run directly; timing thresholds intentionally belong in the benchmark, not CI.
"""
from pathlib import Path
import copy
import sys
import unittest
import warnings
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from runtime_resources import configure_numeric_threads
configure_numeric_threads()
import control as ct
import numpy as np
from scipy.linalg import expm
import coupled_flyback as coupled
from coupled_test_fixtures import configuration
from input_voltage_range import _cancellation_scope
from calculation_scheduler import CalculationCancelled, calculate_report_efficiency_curve
from loop_tuning import _frequency_values, plant_phase_unwrapped
from loss_model import compute_design


class PropagationChecks(unittest.TestCase):
    def test_scalar_and_batch_match_independent_matrix_exponential(self):
        rng = np.random.default_rng(713)
        for count in (1, 4, 7):
            turns = np.linspace(.4, 1., count)
            matrix = (np.full((count, count), .995) + np.eye(count)*.005)
            matrix *= 20e-6*turns[:, None]*turns[None, :]
            initial, voltage = rng.random(count), rng.random(count)*30
            for resistance in (np.zeros(count), np.linspace(.01, .07, count)):
                flow = coupled._Flow(matrix, resistance)
                evaluate = flow.prepare_current(initial, voltage)
                times = np.r_[0., 1e-15, np.logspace(-12, -4, 30)]
                # Independent affine system exponential, including R=0.
                system = np.zeros((count+1, count+1))
                system[:count, :count] = -np.linalg.solve(matrix, np.diag(resistance))
                system[:count, count] = np.linalg.solve(matrix, voltage)
                expected = np.column_stack([(expm(system*t) @ np.r_[initial, 1.])[:count]
                                            for t in times])
                actual = evaluate(times)
                np.testing.assert_allclose(actual, expected, rtol=2e-10, atol=2e-9)
                for i, t in enumerate(times):
                    np.testing.assert_allclose(evaluate(t), actual[:, i], rtol=2e-12, atol=2e-11)
                    np.testing.assert_allclose(flow.values(initial, voltage, t)[0], actual[:, i],
                                               rtol=2e-11, atol=2e-10)


class FrequencyChecks(unittest.TestCase):
    def test_batched_state_space_matches_library_siso_mimo_and_discrete(self):
        rng = np.random.default_rng(21)
        a = -np.diag(np.logspace(1, 6, 9)) + rng.normal(size=(9, 9))
        b, c, d = rng.normal(size=(9, 4)), rng.normal(size=(3, 9)), rng.normal(size=(3, 4))
        continuous = ct.ss(a, b, c, d)
        discrete = ct.ss(np.eye(9)*.5, b, c, d, dt=1e-4)
        transfer = ct.tf([1., 200.], [1., 30., 400.])
        static = ct.ss([], [], [], d)
        for model in (continuous, continuous[0, 0], discrete, transfer, static):
            points = (np.exp(2j*np.pi*np.logspace(-2, 3, 777)*1e-4) if model.dt
                      else 2j*np.pi*np.logspace(-2, 7, 777))
            np.testing.assert_allclose(_frequency_values(model, points),
                                       model(points, squeeze=False), rtol=2e-12, atol=2e-12)

    def test_exact_pole_retains_library_diagnostics(self):
        model = ct.ss([[-1.]], [[1.]], [[1.]], [[0.]])
        with warnings.catch_warnings():
            warnings.simplefilter('ignore')
            actual = _frequency_values(model, np.array([-1., 0., 1j]))
            expected = model(np.array([-1., 0., 1j]), squeeze=False)
        np.testing.assert_allclose(actual, expected, equal_nan=True)

    def test_frequency_chunks_remain_cancellable(self):
        calls = 0
        def cancelled():
            nonlocal calls
            calls += 1
            return calls >= 3
        with self.assertRaises(CalculationCancelled), _cancellation_scope(cancelled):
            _frequency_values(ct.ss([[-1.]], [[1.]], [[1.]], [[0.]]), np.arange(2000)*1j)

    def test_phase_unwrap_matches_original_scalar_scan(self):
        for model in (ct.tf([1., -1e3], [1., 200., 1e4]),
                      ct.ss(ct.tf([1.], [1., 5., 200., 50.]))):
            f = np.logspace(np.log10(10.), np.log10(1000.), 400)
            expected = np.degrees(np.unwrap([np.angle(model(2j*np.pi*x)) for x in f]))[-1]
            if expected > 90:
                expected -= 360
            self.assertAlmostEqual(plant_phase_unwrapped(model, 1000.), expected, places=10)


class PeriodicCacheChecks(unittest.TestCase):
    def setUp(self):
        coupled._periodic_solution.cache_clear()
        self.p = configuration()

    def tearDown(self):
        coupled._periodic_solution.cache_clear()

    def test_reuse_does_not_share_mutable_waveforms_or_freeze_other_calculations(self):
        result = compute_design(self.p)
        expected = result['op']['coupled_solution']['i_winding'].copy()
        result['op']['coupled_solution']['i_winding'][:] = 123.
        changed = copy.deepcopy(self.p)
        changed.update(KP=self.p['KP']*1.5, k_core=self.p['k_core']*1.1)
        with patch.object(coupled, 'least_squares', side_effect=AssertionError('unnecessary period solve')):
            fresh = compute_design(changed)
        np.testing.assert_array_equal(fresh['op']['coupled_solution']['i_winding'], expected)
        self.assertNotEqual(fresh['P_mag'], result['P_mag'])

    def test_electrical_changes_recompute_and_cache_stays_bounded(self):
        original = compute_design(self.p)
        variations = [dict(V_in=self.p['V_in']+1), dict(f_sw=self.p['f_sw']*1.01),
                      dict(L=self.p['L']*1.01), dict(Rds_on=self.p['Rds_on']*1.1),
                      dict(Rs=self.p['Rs']*1.1), dict(Kc=self.p['Kc']*1.02),
                      dict(MLT=.06)]
        load = copy.deepcopy(self.p['outputs']); load[1]['P_out'] *= 1.1
        variations.append(dict(outputs=load))
        diode = copy.deepcopy(self.p['outputs']); diode[1]['Vf_diode'] = .9
        variations.append(dict(outputs=diode))
        for changes in variations:
            with self.subTest(changes=changes), patch.object(coupled, 'least_squares', wraps=coupled.least_squares) as solve:
                fresh = compute_design(dict(copy.deepcopy(self.p), **changes))
                self.assertGreater(solve.call_count, 0)
                delta = abs(fresh['op']['D']-original['op']['D']) + np.max(abs(
                    np.array(fresh['op']['coupled_model']['output_voltages']) -
                    np.array(original['op']['coupled_model']['output_voltages'])))
                self.assertGreater(delta, 1e-8)
        self.assertLessEqual(coupled._periodic_solution.cache_info().currsize, 6)

    def test_cancelled_requests_and_failed_solve_do_not_produce_cached_results(self):
        compute_design(self.p)
        with self.assertRaises(CalculationCancelled), _cancellation_scope(lambda: True):
            compute_design(self.p)
        before = coupled._periodic_solution.cache_info().currsize
        with patch.object(coupled, '_sample_solution', side_effect=CalculationCancelled()), \
             self.assertRaises(CalculationCancelled):
            compute_design(dict(self.p, V_in=self.p['V_in']+1))
        self.assertEqual(coupled._periodic_solution.cache_info().currsize, before)


class EfficiencyReuseChecks(unittest.TestCase):
    def calculate(self, changes):
        from design_engine.service import calculate
        spec = dict(V_in_min=30., V_in_max=30.)
        spec.update(changes)
        with patch('calculation_scheduler.calculate_report_efficiency_curve',
                   wraps=calculate_report_efficiency_curve) as sweep:
            result = calculate(spec, analysis='endpoints', include_loop=False,
                               include_cross_regulation=False, include_efficiency=True).runtime_bundle()
        return result, sweep.call_count

    def test_equal_endpoints_reuse_but_own_their_efficiency_arrays(self):
        result, count = self.calculate({})
        self.assertEqual(count, 1)
        a, b = [case['efficiency_curve'] for case in result['cases']]
        np.testing.assert_array_equal(a['etas'], b['etas'])
        a['etas'][0] = -99
        self.assertNotEqual(b['etas'][0], -99)

    def test_manual_gate_differences_still_get_separate_efficiency_scans(self):
        from mos_manual import normalize_events
        from power_stage import DEFAULT_PARAMS
        events = normalize_events(None, DEFAULT_PARAMS)
        events['max']['on']['Vgp'] += .4
        result, count = self.calculate(dict(mos_miller_mode='manual', mos_manual_events=events))
        self.assertEqual(count, 2)
        a, b = [case['efficiency_curve']['etas'] for case in result['cases']]
        self.assertGreater(np.max(abs(a-b)), 1e-8)

    def test_different_input_voltages_still_get_separate_efficiency_scans(self):
        result, count = self.calculate(dict(V_in_max=36.))
        self.assertEqual(count, 2)
        a, b = [case['efficiency_curve']['etas'] for case in result['cases']]
        self.assertGreater(np.max(abs(a-b)), 1e-8)


if __name__ == '__main__':
    unittest.main()
