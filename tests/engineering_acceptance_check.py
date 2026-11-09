"""Evidence identity, numerical projection and honest acceptance state tests."""
import copy
import json
from pathlib import Path
import sys
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from engineering_acceptance import input_fingerprint, manual_measurement, normalize, report_snapshot


def fixture():
    p = dict(V_in_min=20., V_in_max=30., V_in=20., input_voltage_case='min',
             topology='FLYBACK', V_out=12., P_out=24., L=30e-6,
             target_eta=.9, pm_target=60., temp_rise_limit=40., outputs=[])
    result = dict(op=dict(V_out=12., I_p_rms=1.2, I_L_rms=1.3, I_sw_pk=3.5,
                        V_sw_max=70., I_d_rms=2.1, I_d_pk=7.),
                  wf=dict(ripple_pp=.08), eta=.93,
                  loop=dict(fc=1000., min_pm=62., gm_db=None),
                  mag=dict(transformer=dict(dT=26.)))
    cases = [dict(id=k, voltage=v, result=copy.deepcopy(result),
                  checks=[dict(id='ripple', limit=.12), dict(id='phase_margin', limit=59.)])
             for k, v in (('Vinmin', 20.), ('Vinmax', 30.))]
    return p, dict(base_spec=copy.deepcopy(p), cases=cases)


class AcceptanceChecks(unittest.TestCase):
    def test_normalization_is_owned_strict_and_empty(self):
        self.assertEqual(normalize(None), dict(version=1, criteria=[], measurements=[], issues=[]))
        for value in (False, 0, [], 'x', dict(version=True), dict(version=2)):
            with self.assertRaises(ValueError):
                normalize(value)
        for value in (float('nan'), float('inf'), True):
            with self.assertRaises(ValueError):
                normalize(dict(criteria=[dict(id='a', limit=value)]))
        source = dict(criteria=[dict(id='a', required_sources=['calculation'])])
        result = normalize(source)
        result['criteria'][0]['required_sources'].append('measurement')
        self.assertEqual(source['criteria'][0]['required_sources'], ['calculation'])

    def test_physical_fingerprint_selection_and_legacy_inputs(self):
        p, _ = fixture()
        first = input_fingerprint(p)
        selected = dict(p, input_voltage_case='max', V_in=30., engineering_acceptance=dict(criteria=[]), __old_report='x')
        self.assertEqual(first, input_fingerprint(selected))
        for update in (dict(L=31e-6), dict(P_out=23.), dict(V_in_max=31.),
                       dict(winding_config=dict(layers=[dict(turn_positions=[1e-3])])),
                       dict(mos_miller_curve=dict(points=[[1., 2.], [2., 4.]]))):
            self.assertNotEqual(first, input_fingerprint(dict(p, **update)))
        self.assertNotEqual(input_fingerprint(dict(V_in=12.)), input_fingerprint(dict(V_in=24.)))
        self.assertEqual(input_fingerprint(dict(V_in=12.)), input_fingerprint(dict(V_in_min=12., V_in_max=12.)))
        self.assertEqual(input_fingerprint(dict(V_in=dict(v=12, u=''))), input_fingerprint(dict(V_in=12.)))
        with self.assertRaises(ValueError):
            input_fingerprint(dict(V_in_min=12.))

    def test_completed_values_and_checks_are_projected_without_solving(self):
        p, bundle = fixture()
        original = copy.deepcopy(bundle)
        with patch('loss_model.compute_design', side_effect=AssertionError('projection must not solve')):
            snap = report_snapshot(p, bundle)
        rows = {r['id']: r for r in snap['rows']}
        self.assertEqual(rows['primary_rms']['cases']['Vinmax']['calculation'], 1.2)
        self.assertEqual(rows['temperature_rise']['cases']['Vinmin']['calculation'], 26.)
        self.assertEqual(rows['out1_ripple']['limit'], .12)
        self.assertEqual(rows['phase_margin']['limit'], 59.)
        self.assertIsNone(rows['gain_margin']['cases']['Vinmin']['calculation'])
        self.assertEqual(snap['summary']['state'], 'undefined')
        self.assertEqual(bundle, original)
        json.dumps(snap, allow_nan=False)

    def test_threshold_edit_does_not_rebind_measurement(self):
        p, bundle = fixture()
        m = manual_measurement(p, 'out1_voltage', 'Vinmin', 12.1, source='DMM-1, CSV1', conditions='20V 2A 25C')
        p['engineering_acceptance'] = dict(criteria=[dict(id='out1_voltage', metric='out1_voltage', comparison='range',
            lower=11.5, upper=12.5, required_sources=['calculation', 'measurement'])], measurements=[m])
        snap = report_snapshot(p, bundle)
        row = next(r for r in snap['rows'] if r['id'] == 'out1_voltage')
        self.assertEqual(row['unit'], 'V')
        self.assertIn('端口平均电压', row['name'])
        self.assertEqual(row['cases']['Vinmin']['status'], 'pass')
        self.assertAlmostEqual(row['cases']['Vinmin']['margin'], .4)
        self.assertEqual(row['cases']['Vinmax']['status'], 'undefined')
        p['engineering_acceptance']['criteria'][0]['upper'] = 12.05
        row = next(r for r in report_snapshot(p, bundle)['rows'] if r['id'] == 'out1_voltage')
        self.assertEqual(row['cases']['Vinmin']['status'], 'review')
        self.assertEqual(row['cases']['Vinmin']['measurement_record']['origin'], 'manual-entry')
        changed = dict(p, L=31e-6)
        row = next(r for r in report_snapshot(changed, bundle)['rows'] if r['id'] == 'out1_voltage')
        self.assertEqual(row['cases']['Vinmin']['states']['measurement'], 'stale')
        self.assertIsNone(row['cases']['Vinmin']['delta_measurement'])

    def test_missing_measurement_conditions_is_unknown(self):
        p, bundle = fixture()
        p['engineering_acceptance'] = dict(criteria=[dict(id='primary_peak', limit=5., required_sources=['measurement'])],
            measurements=[manual_measurement(p, 'primary_peak', 'Vinmin', 3., source='', conditions='')])
        row = next(r for r in report_snapshot(p, bundle)['rows'] if r['id'] == 'primary_peak')
        self.assertEqual(row['cases']['Vinmin']['status'], 'undefined')

    def test_strict_boundary_range_and_zero_delta(self):
        p, bundle = fixture()
        p['engineering_acceptance'] = dict(criteria=[dict(id='primary_peak', comparison='<', limit=3.5, required_sources=['calculation'])])
        row = next(r for r in report_snapshot(p, bundle)['rows'] if r['id'] == 'primary_peak')
        self.assertEqual(row['cases']['Vinmin']['status'], 'review')
        self.assertEqual(row['cases']['Vinmin']['margin'], 0.)
        with self.assertRaises(ValueError):
            normalize(dict(criteria=[dict(id='a', comparison='range', lower=2., upper=1.)]))

    @staticmethod
    def spice(p, stable=True):
        case = dict(id='Vinmin_标称负载', voltage=20., complete=True, nominal_comparable=True,
            periodicity=dict(stable=stable), measurements=dict(primary_peak=3.6, vds_peak=71., out1_before=12.05),
            qr_startup=dict(vds_peak_full_v=1335.25),
            loop=dict(available=True, simulation=dict(loop=dict(fc=1048., pm=57.74, gm_db=None))))
        return dict(input_fingerprint=input_fingerprint(p), source='本轮真实运行绑定', evidence=dict(cases=[case]))

    def test_bound_simulation_fra_and_full_startup_extrema(self):
        p, bundle = fixture()
        envelope = self.spice(p)
        rows = {r['id']: r for r in report_snapshot(p, bundle, spice_evidence=envelope)['rows']}
        self.assertEqual(rows['startup_vds_peak']['cases']['Vinmin']['simulation'], 1335.25)
        self.assertEqual(rows['phase_margin']['cases']['Vinmin']['simulation'], 57.74)
        self.assertEqual(rows['phase_margin']['cases']['Vinmin']['states']['simulation'], 'review')
        self.assertIsNone(rows['startup_vds_peak']['cases']['Vinmax']['simulation'])
        unbound = report_snapshot(p, bundle, spice_evidence=envelope['evidence'])
        self.assertFalse(unbound['simulation_matched'])
        self.assertTrue(any('未与当前' in n for n in unbound['evidence_notes']))
        missing_file = report_snapshot(p, bundle, spice_evidence=dict(evidence_error='文件哈希已变化'))
        self.assertTrue(any('文件哈希已变化' in n for n in missing_file['evidence_notes']))
        native = dict(envelope['evidence'], schema='powerdesign-spice-comparison-2', input_fingerprint=input_fingerprint(p))
        self.assertTrue(report_snapshot(p, bundle, spice_evidence=native)['simulation_matched'])
        self.assertFalse(report_snapshot(dict(p, L=31e-6), bundle, spice_evidence=native)['simulation_matched'])
        with_embedded = dict(bundle, engineering_acceptance_evidence=native)
        self.assertTrue(report_snapshot(p, with_embedded)['simulation_matched'])
        row = next(r for r in report_snapshot(p, bundle, spice_evidence=self.spice(p, False))['rows'] if r['id'] == 'phase_margin')
        self.assertEqual(row['cases']['Vinmin']['states']['simulation'], 'undefined')

    def test_equal_voltage_named_manual_events_are_not_duplicated(self):
        p, bundle = fixture()
        p.update(V_in_min=20., V_in_max=20., mos_miller_mode='manual',
            mos_manual_events=dict(min=dict(on=dict(Vgp=4., Qgs=4e-9), off=dict(Vgp=4.2, Qgs=5e-9)),
                                   max=dict(on=dict(Vgp=5., Qgs=6e-9), off=dict(Vgp=5.2, Qgs=7e-9))))
        bundle['base_spec'] = copy.deepcopy(p)
        snap = report_snapshot(p, bundle, spice_evidence=self.spice(p))
        row = next(r for r in snap['rows'] if r['id'] == 'vds_peak')
        self.assertIsNone(row['cases']['Vinmax']['simulation'])
        p['mos_manual_events'] = {}
        bundle['base_spec'] = copy.deepcopy(p)
        snap = report_snapshot(p, bundle, spice_evidence=self.spice(p))
        row = next(r for r in snap['rows'] if r['id'] == 'vds_peak')
        self.assertEqual(row['cases']['Vinmax']['simulation'], 71.)

    def test_joint_adopted_hardware_match_and_issue_closure(self):
        p, bundle = fixture()
        joint = dict(original_config=dict(p, L=10e-6), adopted_config=copy.deepcopy(p),
            circuit=dict(evidence=self.spice(p)['evidence']))
        self.assertTrue(report_snapshot(p, bundle, joint_record=dict(record=joint))['simulation_matched'])
        self.assertFalse(report_snapshot(dict(p, L=10e-6), joint_record=joint)['simulation_matched'])
        p['engineering_acceptance'] = dict(issues=[dict(id='I1', title='启动尖峰', status='closed', evidence='scope1.csv', input_fingerprint=input_fingerprint(p))])
        self.assertEqual(report_snapshot(p, bundle)['summary']['unresolved_issues'], 0)
        self.assertEqual(report_snapshot(dict(p, L=31e-6), bundle)['issues'][0]['effective_status'], 'stale')

    def test_failed_or_selected_only_calculation_does_not_fill_both_ends(self):
        p, bundle = fixture()
        selected = dict(base_spec=p, res=bundle['cases'][0]['result'], checks=bundle['cases'][0]['checks'])
        row = next(r for r in report_snapshot(p, selected)['rows'] if r['id'] == 'primary_peak')
        self.assertEqual(row['cases']['Vinmin']['calculation'], 3.5)
        self.assertIsNone(row['cases']['Vinmax']['calculation'])
        bundle['cases'][1]['error'] = '没有收敛'
        row = next(r for r in report_snapshot(p, bundle)['rows'] if r['id'] == 'primary_peak')
        self.assertIsNone(row['cases']['Vinmax']['calculation'])
        self.assertEqual(row['cases']['Vinmax']['calculation_error'], '没有收敛')

    def test_disabling_every_check_is_not_a_pass(self):
        p, bundle = fixture()
        rows = report_snapshot(p, bundle)['criteria']
        p['engineering_acceptance'] = dict(criteria=[dict(row, enabled=False) for row in rows])
        self.assertEqual(report_snapshot(p, bundle)['summary']['state'], 'undefined')

    def test_active_ownership_keeps_all_branches_and_real_matrix(self):
        from design_engine.specification import load_spec
        root = Path(__file__).resolve().parents[1]
        p = load_spec(json.loads((root/'examples/33W_3OUT_ACF_MP6005_COMPACT.json').read_text('utf-8')))
        fp = input_fingerprint(p)
        mirrors = dict(p, Qrr=99e-9, Vf_diode=.123, L=1e-6, P_out=999., Ns=9, K=.7)
        self.assertEqual(fp, input_fingerprint(mirrors))
        changed = copy.deepcopy(p)
        changed['outputs'][2]['Qrr'] += 1e-9
        self.assertNotEqual(fp, input_fingerprint(changed))
        changed = copy.deepcopy(p)
        changed['outputs'][1]['output_capacitors'][0]['ESR'] += .001
        self.assertNotEqual(fp, input_fingerprint(changed))
        changed = copy.deepcopy(p)
        changed['coupling_config']['k'][0][1] -= .001
        changed['coupling_config']['k'][1][0] -= .001
        self.assertNotEqual(fp, input_fingerprint(changed))
        changed = copy.deepcopy(p)
        changed['winding_config']['layer_insulation'] += 1e-6
        self.assertNotEqual(fp, input_fingerprint(changed))
        buck = load_spec(json.loads((root/'examples/24W_BUCK_VM_TPS40200.json').read_text('utf-8')))
        self.assertEqual(input_fingerprint(buck), input_fingerprint(dict(buck, K=.123, Kc=9.)))


if __name__ == '__main__':
    unittest.main()
