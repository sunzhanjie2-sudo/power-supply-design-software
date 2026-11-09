"""Real QR endpoint/corner, waveform, loss, loop and field-adoption contracts.

The fixture is a synthetic 60 W + 1 W engineering check, not a claimed
measurement or validation of a shipped example. No numerical solver is mocked.
"""
import copy
import json
from pathlib import Path
import sys
import unittest
from unittest.mock import patch

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT), str(ROOT / 'tests')]
from runtime_resources import configure_numeric_threads
configure_numeric_threads()
from qr_coupled_check import fixture
from input_voltage_range import calculate_input_endpoints
from cross_regulation import scan_cross_regulation, for_input
from calculation_scheduler import CalculationCancelled

OUT = ROOT / 'artifacts/qr-cross-regulation-20261108/core'


def sample():
    p = fixture()
    p['V_in_max'] = 320.
    for rail, minimum in zip(p['outputs'], (45., .5)):
        rail['P_out_min'] = minimum
    return p


class QRCrossIntegrationChecks(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.p = sample()
        cls.original = copy.deepcopy(cls.p)
        cls.bundle = calculate_input_endpoints(cls.p, include_loop=True)
        cls.scan = cls.bundle['cross_regulation']

    def test_complete_endpoints_and_all_eight_actual_corners(self):
        b, r = self.bundle, self.scan
        self.assertEqual(self.p, self.original)
        self.assertTrue(b['fixed_hardware'])
        self.assertTrue(r['supported']); self.assertTrue(r['complete'])
        self.assertEqual((r['total_cases'], r['successful_cases']), (8, 8))
        self.assertEqual(len({(c['V_in'], tuple(c['powers'])) for c in r['cases']}), 8)
        self.assertEqual({c['V_in'] for c in r['cases']}, {300., 320.})
        for c in b['cases']:
            self.assertIsNone(c['error']); self.assertIsNone(c['loop_error'])
            self.assertIsNotNone(c['models'])
            op = c['result']['op']; m = op['qr_coupled_model']
            self.assertTrue(m['converged'])
            self.assertTrue(m['independent_cross_regulation'])
            self.assertLess(m['normalized_residual'], 2e-5)
            self.assertLess(abs(m['energy_balance_relative']), 1e-5)
        for c in r['cases']:
            self.assertEqual(c['status'], 'ok')
            self.assertAlmostEqual(c['voltages'][0], 60., places=10)
            timing = c['qr_timing']
            self.assertAlmostEqual(c['f_sw'], 1 / sum(timing[k] for k in ('T_on', 'T_demag', 'T_ring')), places=6)
            self.assertLess(c['residual'], 2e-5)
        self.assertGreater(max(c['f_sw'] for c in r['cases']) - min(c['f_sw'] for c in r['cases']), 1000.)
        json.dumps(r, ensure_ascii=False, allow_nan=False)

    def test_corner_scanner_reuses_the_same_physical_hardware(self):
        from power_stage import compute_operating_point
        seen, solved = [], []
        def observe(q):
            # compute_operating_point also recursively obtains the disabled
            # nominal starting point and scalar child contexts. Count only
            # the actual multi-winding matrix requests made by this scan.
            physical=q.get('coupling_config', {}).get('enabled') and len(q.get('outputs') or []) == 2
            if physical:
                seen.append(copy.deepcopy(q))
            op=compute_operating_point(q)
            if physical:solved.append((q,op))
            return op
        with patch('power_stage.compute_operating_point', side_effect=observe):
            r = scan_cross_regulation(self.p, reference_result=self.bundle['cases'][0]['result'])
        self.assertTrue(r['complete']); self.assertEqual(len(seen), 8)
        expected = self.bundle['fixed_spec']
        def physical_transformer(value):
            result=copy.deepcopy(value)
            # A reference re-evaluation truthfully changes this provenance
            # label from manual to fixed-hardware; conductor data must match.
            for winding in result.get('windings',[]):winding.pop('wire_source',None)
            return result
        for q in seen:
            self.assertEqual(physical_transformer(q['_fixed_transformer']),physical_transformer(expected['_fixed_transformer']))
            self.assertEqual(q['_qr_rcd_hardware'],expected['_qr_rcd_hardware'])
            for key in ('L', 'Np', 'Ns', 'MLT', 'coupling_config', 'spice_config',
                        'controller_KP', 'controller_fz1', 'controller_fp1'):
                if key in expected:
                    self.assertEqual(q[key], expected[key])
            for rail, original in zip(q['outputs'], expected['outputs']):
                for key in ('Ns', 'd_wire_s', 'n_strand_s', 'parallel_wires_s',
                            'output_capacitors', 'Vf_diode', 'Vf_dout'):
                    if key in original:
                        self.assertEqual(rail[key], original[key])
        clamp_by_input={}
        for q,op in solved:
            from flyback_clamp import rcd_components
            model=op['qr_coupled_model'];vc=model['clamp_voltage']
            self.assertEqual(model['rcd_hardware']['R_ohm'],expected['_qr_rcd_hardware']['R_ohm'])
            self.assertEqual(model['rcd_hardware']['C_F'],expected['_qr_rcd_hardware']['C_F'])
            self.assertAlmostEqual(model['P_clamp'],vc**2/expected['_qr_rcd_hardware']['R_ohm'],places=7)
            components=rcd_components(op,q)
            self.assertEqual(components['R_snub'],expected['_qr_rcd_hardware']['R_ohm'])
            self.assertEqual(components['C_snub'],expected['_qr_rcd_hardware']['C_F'])
            self.assertAlmostEqual(components['dV_clamp'],model['rcd_ripple_upper_V'],places=8)
            if q['outputs'][1]['P_out']==1.:
                clamp_by_input.setdefault(q['V_in'],{})[q['outputs'][0]['P_out']]=vc
        for values in clamp_by_input.values():self.assertLess(values[45.],values[60.])

    def test_actual_waveform_currents_drive_each_branch_loss(self):
        for c in self.bundle['cases']:
            r = c['result']; op = r['op']; wf = r['wf']
            self.assertAlmostEqual(wf['f_sw'], op['f_sw'], places=8)
            self.assertEqual(len(wf['outputs']), 2)
            for row, child_wf, copper in zip(r['outputs'], wf['outputs'], r['mag']['transformer']['windings']):
                child = row['op']; current = np.asarray(child_wf['i_d'])
                avg = float(np.mean(current)); rms = float(np.sqrt(np.mean(current**2)))
                self.assertAlmostEqual(avg, child['I_out'], delta=child['I_out']*.001)
                self.assertAlmostEqual(rms, child['I_d_rms'], delta=child['I_d_rms']*.001)
                # Loss uses exact integrated charge; plot samples have a
                # separately checked interpolation error, not bit identity.
                self.assertAlmostEqual(row['diode']['P_cond'], row['spec']['Vf_diode']*child['I_out'], places=9)
                self.assertAlmostEqual(row['P_dout'], row['spec']['Vf_dout']*child['I_out'], places=9)
                self.assertAlmostEqual(copper['I_rms'], child['I_s_rms'], places=12)
                self.assertAlmostEqual(copper['P_cu'], copper['R_dc']*copper['Fr']*child['I_s_rms']**2, places=10)
                self.assertGreater(row['ripple_pp'], 0.)
            # Two independent diode commutations are not proportional copies.
            pulse1 = np.asarray(wf['outputs'][0]['i_d'])
            pulse2 = np.asarray(wf['outputs'][1]['i_d'])
            self.assertGreater(float(np.max(np.abs(pulse1/max(pulse1)-pulse2/max(pulse2)))), .05)

    def test_loop_remains_explicitly_a_low_frequency_reduction(self):
        from plants import build_loop_models
        for c in self.bundle['cases']:
            models, plant = build_loop_models(c['p'], c['result']['op'])
            detail = models[0]._loop_metadata
            self.assertEqual(detail['kind'], 'qr-ideal-ratio-aggregate')
            self.assertEqual(detail['scope'], 'ideal-ratio-reduced')
            self.assertFalse(detail['independent_cross_regulation'])
            self.assertIn('低频约化', plant.model_note)
            self.assertIn('未对多路换流或离散跳谷', plant.model_note)
            self.assertEqual(plant.qr_linearization['multi_output']['dc_point_source'], 'qr-coupled-valley')

    def test_zero_load_is_partial_and_cancellation_is_not_a_failed_corner(self):
        p = sample(); p['outputs'][1]['P_out_min'] = 0.
        r = scan_cross_regulation(p, reference_result=self.bundle['cases'][0]['result'])
        self.assertTrue(r['supported']); self.assertFalse(r['complete'])
        self.assertEqual((r['successful_cases'], r['total_cases']), (4, 8))
        unavailable = [c for c in r['cases'] if c['powers'][1] == 0.]
        self.assertEqual(len(unavailable), 4)
        self.assertTrue(all(c['status']=='unavailable' and c['voltages'] is None for c in unavailable))
        self.assertTrue(all(not row['complete'] for row in r['summary']))
        with self.assertRaises(CalculationCancelled):
            calculate_input_endpoints(self.p, include_loop=True, cancelled=lambda: True)
        checks = [0]
        def cancel_during_scan():
            checks[0] += 1
            return checks[0] >= 5
        with self.assertRaises(CalculationCancelled):
            scan_cross_regulation(self.p, reference_result=self.bundle['cases'][0]['result'], cancelled=cancel_during_scan)

    def test_equal_load_endpoints_do_not_claim_zero_full_load_cross_regulation(self):
        p = sample()
        for rail in p['outputs']:
            rail['P_out_min'] = rail['P_out']
        r = scan_cross_regulation(p, reference_result=self.bundle['cases'][0]['result'])
        self.assertTrue(r['complete']); self.assertEqual(r['total_cases'], 2)
        self.assertEqual(r['varied_outputs'], [])
        self.assertIn('未覆盖轻载变化', r['note'])
        self.assertIn('不代表全负载交叉调整率为 0', r['note'])
        for vin in (300., 320.):
            point = for_input(r, vin)
            self.assertEqual(point['total_cases'], 1)
            self.assertTrue(all(row['span_pct']==0. for row in point['summary']))

    def test_joint_field_adoption_enables_the_qr_multi_matrix(self):
        from joint_simulation import apply_leakage_margin, _adopt
        from design_engine.specification import load_spec
        from power_stage import compute_operating_point
        matrix = self.bundle['cases'][0]['result']['op']['qr_coupled_model']['L']
        margin = apply_leakage_margin(dict(port_order=['P', 'OUT1', 'OUT2'], L_ports_H=matrix), 1.2)
        record = dict(model_conditions=dict(core=dict(mode='half_center_gap', total_gap_m=.001,
            source='integration-test', path='test.step', sha256='a'*64)))
        config, notes = _adopt(self.p, record, margin)
        self.assertEqual(self.p, self.original)
        coupling = config['coupling_config']
        self.assertTrue(coupling['enabled']); self.assertTrue(coupling['field_matrix_enabled'])
        np.testing.assert_allclose(coupling['self_inductances_H'], np.diag(matrix), rtol=1e-13)
        np.testing.assert_allclose(coupling['k'], margin['adopted_k_ports'], rtol=1e-13)
        self.assertEqual(config['__transformer_simulation']['adoption_scope'], 'joint-export-copy')
        self.assertTrue(any('QR多路' in note for note in notes))
        adopted = compute_operating_point(load_spec(config))
        self.assertTrue(adopted['qr_coupled_model']['converged'])
        self.assertTrue(adopted['qr_coupled_model']['independent_cross_regulation'])

    @classmethod
    def tearDownClass(cls):
        OUT.mkdir(parents=True, exist_ok=True)
        b = cls.bundle
        receipt = dict(kind='numerical-integration-receipt-not-measurement',
            description='Synthetic QR 60 W + 1 W, Pmin 45 W / 0.5 W, Vin 300..320 V; full independent matrix, no SPICE run.',
            endpoint_errors=[dict(id=c['id'], error=c['error'], loop_error=c['loop_error']) for c in b['cases']],
            frozen_rcd_hardware=b['fixed_spec']['_qr_rcd_hardware'],
            corners=cls.scan, endpoints=[])
        for c in b['cases']:
            r = c['result']; op = r['op']; m = op['qr_coupled_model']
            receipt['endpoints'].append(dict(id=c['id'], V_in=c['voltage'], frequency_hz=op['f_sw'],
                D=op['D'], output_voltage_V=[x['V_out'] for x in op['output_ops']],
                output_rms_A=[x['I_s_rms'] for x in op['output_ops']],
                residual=m['normalized_residual'], energy_balance_W=m['energy_balance_W'],
                valley_index=m['valley_index'], off_blanking_s=m['off_blanking_s'],
                clamp_voltage_V=m['clamp_voltage'],rcd_policy=m['rcd_policy'],
                rcd_hardware=m.get('rcd_hardware'),rcd_power_balance_W=m.get('rcd_power_balance_W'),
                rcd_ripple_upper_relative=m.get('rcd_ripple_upper_relative'),
                T_on=m['T_on'], T_demag=m['T_demag'], T_ring=m['T_ring'],
                assumptions=m['assumptions'], loop_metadata=c['models'][0]._loop_metadata))
        (OUT/'integration-receipt.json').write_text(json.dumps(receipt, ensure_ascii=False, indent=2, allow_nan=False), 'utf-8')


if __name__ == '__main__':
    unittest.main(verbosity=2)
