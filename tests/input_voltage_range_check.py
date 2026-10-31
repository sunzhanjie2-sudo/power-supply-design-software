"""Range boundaries, legacy compatibility and one-BOM endpoint regressions."""
import copy
import json
from pathlib import Path
import subprocess
import sys
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import numpy as np

from power_stage import DEFAULT_PARAMS
from loss_model import compute_design
from design_api import load_spec, run_design, run_input_endpoints
from input_voltage_range import (normalize_input_voltage_spec,
                                 calculate_input_operating_point,
                                 calculate_input_endpoints)
from calculation_scheduler import CalculationCancelled


def automatic_spec(topology='FLYBACK'):
    return dict(copy.deepcopy(DEFAULT_PARAMS), topology=topology,
                V_out=15 if topology == 'BUCK' else 60 if topology == 'BOOST' else 30,
                V_in_min=24., V_in_max=40., input_voltage_case='max',
                core_choice='auto', core_shape='auto', Np=0, Ns=0,
                d_wire_p=0., d_wire_s=0., MLT=0.)


class NormalizationChecks(unittest.TestCase):
    def test_module_import_does_not_load_numerical_or_control_stack(self):
        subprocess.run([sys.executable, '-c',
            "import sys,input_voltage_range; assert not {'numpy','control','scipy'} & set(sys.modules)"],
            cwd=Path(__file__).resolve().parents[1], check=True, capture_output=True)

    def test_legacy_migrates_to_equal_endpoints_and_does_not_mutate(self):
        original = dict(V_in=48., outputs=[dict(Ns=2)])
        saved = copy.deepcopy(original)
        resolved = normalize_input_voltage_spec(original)
        self.assertEqual(original, saved)
        self.assertEqual((resolved['V_in_min'], resolved['V_in_max'], resolved['V_in']), (48., 48., 48.))
        resolved['outputs'][0]['Ns'] = 9
        self.assertEqual(original, saved)

    def test_units_selection_and_legacy_scalar_api(self):
        p = load_spec(dict(V_in_min=dict(v=.024, u='k'), V_in_max=40,
                           V_in=999, input_voltage_case='max'))
        self.assertEqual((p['V_in_min'], p['V_in_max'], p['V_in']), (24., 40., 40.))
        old = load_spec(dict(V_in=45))
        self.assertEqual(old['V_in'], 45)
        self.assertNotIn('V_in_min', old)
        self.assertEqual(compute_design(dict(DEFAULT_PARAMS, V_in=45))['op']['V_in'], 45)

    def test_range_invalid_values_are_rejected(self):
        for changes in (dict(V_in_min=50), dict(V_in_min=0, V_in_max=40),
                        dict(V_in_min=50, V_in_max=40), dict(V_in_min=float('nan'), V_in_max=40),
                        dict(V_in_min=24, V_in_max=float('inf')), dict(V_in_min=True, V_in_max=40),
                        dict(input_voltage_case='typ')):
            with self.subTest(changes=changes), self.assertRaises(ValueError):
                normalize_input_voltage_spec(dict(V_in=30, **changes))


class FixedHardwareChecks(unittest.TestCase):
    def test_automatic_magnetic_geometry_and_dcr_do_not_change(self):
        for topology in ('BUCK', 'BOOST', 'BUCK-BOOST', 'FLYBACK', 'QR-FLYBACK', 'ACF-FORWARD'):
            with self.subTest(topology=topology):
                p = automatic_spec(topology)
                bundle = calculate_input_endpoints(p, include_loop=False)
                self.assertTrue(bundle['fixed_hardware'])
                self.assertEqual(bundle['hardware_reference'], 'Vinmin')
                lo, hi = bundle['cases']
                self.assertIsNone(lo['error'])
                self.assertIsNone(hi['error'])
                for kind, geometry in bundle['hardware'].items():
                    if kind not in ('inductor', 'transformer'):
                        continue
                    for key in ('core', 'MLT', 'Np', 'Ns', 'N', 'd_wire',
                                'd_wire_p', 'd_wire_s', 'n_strand_p', 'n_strand_s'):
                        if key in geometry:
                            self.assertEqual(lo['result']['mag'][kind][key], hi['result']['mag'][kind][key])
                    for key in ('R_dc', 'R_dc_p', 'R_dc_s'):
                        if key in lo['result']['mag'][kind]:
                            self.assertEqual(lo['result']['mag'][kind][key], hi['result']['mag'][kind][key])
                self.assertNotEqual(lo['result']['op']['D'], hi['result']['op']['D'])
                for key in ('KP', 'fz1', 'fz2', 'fp1', 'fp2', 'C_out', 'L'):
                    self.assertEqual(lo['p'][key], hi['p'][key])

    def test_coupled_all_windings_preserve_L_R_and_integer_turns(self):
        from coupled_test_fixtures import configuration
        p = configuration()
        p.update(V_in_min=24., V_in_max=40., input_voltage_case='max', Np=0,
                 d_wire_p=0., d_wire_s=0.)
        for rail in p['outputs']:
            rail['d_wire_s'] = 0.
        bundle = calculate_input_endpoints(p)
        lo, hi = bundle['cases']
        for case in (lo, hi):
            self.assertIsNone(case['error'])
            self.assertIsNone(case['loop_error'])
            self.assertIsNotNone(case['result']['loop'])
        for key in ('L', 'R', 'ratios'):
            np.testing.assert_array_equal(lo['result']['op']['coupled_model'][key],
                                          hi['result']['op']['coupled_model'][key])
        self.assertEqual(len(bundle['hardware']['transformer']['windings']), 3)
        for a, b in zip(lo['result']['mag']['transformer']['windings'], hi['result']['mag']['transformer']['windings']):
            for key in ('Ns', 'd_wire_s', 'n_strand_s', 'R_dc'):
                self.assertEqual(a[key], b[key])

    def test_selection_does_not_change_hardware_reference(self):
        p = automatic_spec()
        a = calculate_input_operating_point(dict(p, input_voltage_case='min'))
        b = calculate_input_operating_point(dict(p, input_voltage_case='max'))
        self.assertEqual(a['hardware'], b['hardware'])
        self.assertEqual(a['op']['V_in'], 24.)
        self.assertEqual(b['op']['V_in'], 40.)
        self.assertEqual(a['base_spec']['input_voltage_case'], 'min')
        self.assertEqual(b['base_spec']['input_voltage_case'], 'max')

    def test_equal_endpoints_only_solve_once_but_keep_both_labels(self):
        p = dict(automatic_spec(), V_in_max=24.)
        with patch('loss_model.compute_design', wraps=compute_design) as count:
            bundle = calculate_input_endpoints(p, include_loop=False)
        self.assertEqual(count.call_count, 1)
        self.assertEqual([case['id'] for case in bundle['cases']], ['Vinmin', 'Vinmax'])
        self.assertIs(bundle['cases'][0]['result'], bundle['cases'][1]['result'])

    def test_invalid_maximum_does_not_discard_valid_minimum(self):
        p = dict(automatic_spec('BOOST'), V_in_min=12., V_in_max=40., V_out=30.)
        bundle = calculate_input_endpoints(p, include_loop=False)
        lo, hi = bundle['cases']
        self.assertIsNone(lo['error'])
        self.assertIsNotNone(lo['result'])
        self.assertIsNotNone(hi['error'])
        self.assertIsNone(hi['result'])

    def test_cancellation_is_not_converted_into_an_endpoint_error(self):
        with self.assertRaises(CalculationCancelled):
            calculate_input_endpoints(automatic_spec(), cancelled=lambda: True)
        def cancel_during_solve(_p):
            raise CalculationCancelled()
        with patch('loss_model.compute_design', side_effect=cancel_during_solve), self.assertRaises(CalculationCancelled):
            calculate_input_endpoints(automatic_spec())
        from analysis_workflows import evaluate
        # All snapshot callers now use the single plant factory directly.
        with patch('plants.build_loop_models', side_effect=CalculationCancelled()), self.assertRaises(CalculationCancelled):
            evaluate(DEFAULT_PARAMS)

    def test_single_voltage_preserves_partial_design_when_core_selection_fails(self):
        original_compute = compute_design
        def magnetic_failure(p):
            result = original_compute(p)
            result['mag'] = dict(ok=False, reason='test: no core large enough')
            return result
        p = dict(automatic_spec(), V_in_min=30., V_in_max=30.)
        with patch('loss_model.compute_design', side_effect=magnetic_failure):
            snap = calculate_input_operating_point(p)
            bundle = calculate_input_endpoints(p, include_loop=False)
        self.assertEqual(snap['op']['V_in'], 30.)
        self.assertFalse(snap['fixed_hardware'])
        self.assertIn('磁件选型失败', snap['hardware_note'])
        self.assertFalse(snap['res']['mag']['ok'])
        self.assertTrue(all(case['result'] is not None for case in bundle['cases']))
        self.assertFalse(bundle['fixed_hardware'])

    def test_reports_and_legacy_corners_remain_json_serializable(self):
        p = automatic_spec()
        report = run_design(p)
        self.assertTrue(report['ok'])
        self.assertEqual(report['input_voltage_range']['selected'], 'max')
        self.assertEqual(report['input_voltage_range']['hardware_reference'], 'Vinmin')
        endpoint_report = run_input_endpoints(p)
        self.assertTrue(endpoint_report['ok'])
        self.assertEqual([c['V_in'] for c in endpoint_report['cases']], [24., 40.])
        json.dumps(endpoint_report)
        from design_api import run_corners
        legacy = run_corners(dict(V_in=30), load_fracs=(1.,))
        self.assertEqual(legacy['v_in'], (27., 33.))
        ranged = run_corners(p, load_fracs=(1.,))
        self.assertEqual(ranged['v_in'], (24., 40.))
        self.assertEqual(ranged['hardware'], calculate_input_endpoints(p, include_loop=False)['hardware'])


if __name__ == '__main__':
    unittest.main(verbosity=2)
