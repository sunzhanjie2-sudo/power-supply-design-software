"""Only forward outputs own a choke; flyback always keeps shared Lm.

The checks are headless and verify calculation results, not just the form
catalogue. Legacy output fields are preserved instead of mutating saved data.
"""
import copy
from pathlib import Path
import sys
import unittest

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from isolated_outputs import output_specs, selected_params
from loss_model import compute_design
from power_stage import DEFAULT_PARAMS


def design(topology='FLYBACK'):
    p = copy.deepcopy(DEFAULT_PARAMS)
    p.update(topology=topology, feedback_mode='SSR', feedback_output=1,
             outputs=[dict(name='OUT1', V_out=30., P_out=28., C_out=220e-6,
                           L=1e-3, Ns=0, d_wire_s=0., n_strand_s=10),
                      dict(name='OUT2', V_out=12., P_out=12., C_out=220e-6,
                           L=2e-3, Ns=0, d_wire_s=0., n_strand_s=10)])
    if topology == 'ACF-FORWARD':
        p.update(N=.5, Lm_forward=220e-6, C_clamp=47e-9)
    return p


class RailTopologyValidationChecks(unittest.TestCase):
    def test_flyback_legacy_choke_values_are_inactive_and_preserved(self):
        for topology in ('FLYBACK', 'QR-FLYBACK'):
            for value in (0., -1.):
                with self.subTest(topology=topology, legacy_L=value):
                    p = design(topology)
                    p['outputs'][0].update(L=value, core_choice_L='unused legacy core')
                    original = copy.deepcopy(p)
                    rails = output_specs(p)
                    self.assertEqual(rails[0]['L'], value)
                    self.assertEqual(rails[0]['core_choice_L'], 'unused legacy core')
                    self.assertEqual(p, original)

    def test_flyback_computation_keeps_shared_lm(self):
        for topology in ('FLYBACK', 'QR-FLYBACK'):
            p = design(topology)
            expected = compute_design(p)
            for value in (0., -1.):
                with self.subTest(topology=topology, legacy_L=value):
                    candidate = copy.deepcopy(p)
                    for rail in candidate['outputs']:
                        rail.update(L=value, core_choice_L='not an actual choke')
                    original = copy.deepcopy(candidate)
                    self.assertEqual(selected_params(candidate)['L'], p['L'])
                    actual = compute_design(candidate)
                    self.assertEqual(candidate, original)
                    self.assertEqual(actual['op']['L'], p['L'])
                    self.assertEqual(actual['op']['aggregate_params']['L'], p['L'])
                    for branch in actual['op']['output_ops']:
                        self.assertEqual(branch['L'], p['L'])
                    for key in ('D', 'f_sw', 'I_sw_pk', 'I_sw_rms', 'V_sw_max'):
                        self.assertAlmostEqual(actual['op'][key], expected['op'][key], places=12)
                    for key in ('P_total', 'P_semi', 'P_mag', 'P_cap', 'eta'):
                        self.assertAlmostEqual(actual[key], expected[key], places=12)
                    np.testing.assert_array_equal(actual['wf']['i_sw'], expected['wf']['i_sw'])
                    self.assertIsNone(actual['mag']['inductor'])
                    self.assertNotIn('inductors', actual['mag'])

    def test_forward_requires_positive_finite_choke_per_output(self):
        for value in (0., -1., float('nan'), float('inf')):
            with self.subTest(branch_L=value):
                p = design('ACF-FORWARD')
                p['outputs'][1]['L'] = value
                with self.assertRaisesRegex(ValueError, 'OUT2.L'):
                    output_specs(p)
                with self.assertRaisesRegex(ValueError, 'OUT2.L'):
                    compute_design(p)

    def test_forward_uses_independent_chokes(self):
        p = design('ACF-FORWARD')
        result = compute_design(p)
        self.assertEqual([branch['L'] for branch in result['op']['output_ops']], [1e-3, 2e-3])
        self.assertEqual(len(result['mag']['inductors']), 2)
        self.assertEqual(selected_params(p)['L'], 1e-3)
        self.assertEqual(selected_params(dict(p, feedback_output=2))['L'], 2e-3)

    def test_real_output_requirements_still_rejected(self):
        for topology in ('FLYBACK', 'QR-FLYBACK', 'ACF-FORWARD'):
            for key in ('V_out', 'C_out'):
                with self.subTest(topology=topology, field=key):
                    p = design(topology)
                    p['outputs'][0][key] = 0.
                    with self.assertRaisesRegex(ValueError, 'OUT1.'+key):
                        output_specs(p)


if __name__ == '__main__':
    unittest.main(verbosity=2)
