"""Only the feedback output is a setpoint; other rails follow actual turns."""
import copy
import sys
from pathlib import Path
import unittest

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from power_stage import DEFAULT_PARAMS, compute_operating_point
from isolated_outputs import output_specs, selected_params
from transformer_turns import resolve_output_turns
from waveforms import make_waveforms


def parameters(topology='FLYBACK', feedback=1, automatic=False):
    p = copy.deepcopy(DEFAULT_PARAMS)
    p.update(topology=topology, feedback_output=feedback, Np=0 if automatic else 6,
             N=.5, outputs=[dict(V_out=30, P_out=20, Ns=12, L=1e-3),
                            dict(V_out=12, P_out=8, Ns=5, L=1e-3),
                            dict(V_out=5, P_out=4, Ns=2, L=1e-3)])
    # Pure turns-ratio fixture. Fixed drops are exercised separately below.
    for rail in p['outputs']:rail.update(Vf_diode=0.,d_out_enable=False)
    return p


def canonical(p):
    q = copy.deepcopy(p)
    q['outputs'] = [{key: value for key, value in rail.items() if key != 'id'}
                    for rail in output_specs(q)]
    return q


class OutputVoltageTurnChecks(unittest.TestCase):
    def test_unregulated_voltages_follow_integer_turns(self):
        for topology in ('FLYBACK', 'QR-FLYBACK', 'ACF-FORWARD'):
            with self.subTest(topology=topology):
                p = parameters(topology)
                p['outputs'][1]['V_out'] = 999.
                p['outputs'][2].pop('V_out')
                rails = output_specs(p)
                self.assertEqual([r['V_out'] for r in rails], [30., 12.5, 5.])
                op = compute_operating_point(p)
                self.assertEqual([r['V_out'] for r in op['output_ops']], [30., 12.5, 5.])
                self.assertEqual([r['N'] for r in op['output_ops']], [.5, 1.2, 3.])

    def test_selected_feedback_setpoint_and_actual_ratio(self):
        p = parameters(feedback=2)
        selected = selected_params(p)
        self.assertEqual(selected['V_out'], 12.)
        self.assertEqual(selected['N'], 6 / 5)
        self.assertEqual(selected['Np'], 6)
        self.assertEqual(selected['Ns'], 5)
        np.testing.assert_allclose([r['V_out'] for r in output_specs(p)], [28.8, 12., 4.8],atol=1e-12)

    def test_feedback_edit_scales_estimates_not_turns(self):
        p = canonical(parameters())
        p['outputs'][0]['V_out'] = 36
        rails = output_specs(p)
        self.assertEqual([r['Ns'] for r in rails], [12, 5, 2])
        self.assertEqual([r['V_out'] for r in rails], [36., 15., 6.])

    def test_old_unregulated_values_cannot_drive_resolved_hardware(self):
        p = parameters()
        before = output_specs(p)
        for rail in p['outputs'][1:]:
            rail['V_out'] = float('nan')
        after = output_specs(p)
        self.assertEqual(before, after)

    def test_canonicalization_is_pure_and_idempotent(self):
        p = parameters(automatic=True)
        for rail in p['outputs']:
            rail['Ns'] = 0
        original = copy.deepcopy(p)
        first = canonical(p)
        self.assertEqual(p, original)
        self.assertTrue(all(r['Ns'] > 0 for r in first['outputs']))
        for _ in range(3):
            self.assertEqual(canonical(first), first)
        first['outputs'][1]['V_out'] = 999
        first['outputs'][2]['V_out'] = .001
        self.assertEqual([r['Ns'] for r in output_specs(first)],
                         [r['Ns'] for r in output_specs(p)])

    def test_legacy_zero_turns_seed_rounding_then_follow_hardware(self):
        p = parameters()
        for rail in p['outputs']:
            rail['Ns'] = 0
        rails = output_specs(p)
        self.assertEqual([r['Ns'] for r in rails], [12, 5, 2])
        self.assertEqual([r['V_out'] for r in rails], [30., 12.5, 5.])

    def test_auto_primary_is_stable_for_every_feedback_and_topology(self):
        for topology in ('FLYBACK', 'QR-FLYBACK', 'ACF-FORWARD'):
            for feedback in (1, 2, 3):
                p = parameters(topology, feedback, automatic=True)
                if topology == 'ACF-FORWARD':
                    p['N'] = .3
                for rail in p['outputs']:
                    rail['Ns'] = 0
                first = canonical(p)
                turns = resolve_output_turns(first, output_specs(first))
                second = resolve_output_turns(canonical(first), output_specs(first))
                self.assertEqual(turns, second)
                self.assertEqual(canonical(first), first)

    def test_fixed_corner_primary_and_secondary_are_not_redesigned(self):
        p = parameters(automatic=True)
        p['_fixed_transformer'] = dict(Np=14, Ns=12, core='PQ20-20', MLT=.052)
        turns = resolve_output_turns(p, output_specs(p))
        self.assertEqual(turns['Np'], 14)
        self.assertEqual(turns['Ns'], [12, 5, 2])
        self.assertEqual(turns['transformer']['MLT'], .052)
        self.assertEqual(selected_params(p)['N'], 14 / 12)

    def test_branch_charge_and_ampere_turns_conservation(self):
        for topology in ('FLYBACK', 'QR-FLYBACK', 'ACF-FORWARD'):
            p = parameters(topology)
            op = compute_operating_point(p)
            wf = make_waveforms(op, n_pts=100000)
            for child, branch in zip(op['output_ops'], wf['outputs']):
                self.assertAlmostEqual(float(np.mean(branch['i_c'])), 0., delta=.001)
                self.assertAlmostEqual(child['R'], child['V_out'] ** 2 / child['P_out'])
            if topology != 'ACF-FORWARD':
                ampere = sum(branch['i_d'] / child['N']
                             for child, branch in zip(op['output_ops'], wf['outputs']))
                aggregate = make_waveforms(op['aggregate_op'], n_pts=100000)
                np.testing.assert_allclose(ampere, aggregate['i_s'] / op['aggregate_op']['N'], atol=1e-10)

    def test_psr_keeps_reference_setpoint_and_fixed_frequency(self):
        p = parameters(feedback=2)
        p['feedback_mode'] = 'PSR-MP6005'
        op = compute_operating_point(p)
        self.assertEqual(op['V_out'], 12)
        self.assertEqual(op['f_sw'], 250e3)
        self.assertEqual(op['N'], 6 / 5)
        np.testing.assert_allclose([r['V_out'] for r in op['outputs']], [28.8, 12., 4.8],atol=1e-12)

    def test_invalid_feedback_voltage_is_still_rejected(self):
        p = parameters()
        p['outputs'][0]['V_out'] = 0
        with self.assertRaisesRegex(ValueError, 'V_out'):
            output_specs(p)

    def test_single_output_default_stays_on_original_path(self):
        p = copy.deepcopy(DEFAULT_PARAMS)
        before = copy.deepcopy(p)
        op = compute_operating_point(p)
        self.assertEqual(p, before)
        self.assertEqual(op['N'], p['N'])
        self.assertNotIn('output_turns', op)
        self.assertEqual(output_specs(p), [])


if __name__ == '__main__':
    unittest.main(verbosity=2)
