"""Load ranges, fixed-BOM corner completeness, failures and report contracts."""
import copy
import json
from pathlib import Path
import sys
import unittest
from unittest.mock import patch

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from runtime_resources import configure_numeric_threads
configure_numeric_threads()
from design_api import load_spec,run_cross_regulation
from isolated_outputs import output_specs,scale_load
from cross_regulation import scan_cross_regulation,summarize,for_input
from calculation_scheduler import CalculationCancelled


def sample():return load_spec(json.loads((ROOT/'examples/3_OUTPUT_CROSS_REGULATION.json').read_text(encoding='utf-8')))


class CrossRegulationCheck(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.p=sample();cls.original=copy.deepcopy(cls.p)
        cls.actual=scan_cross_regulation(cls.p)

    def test_real_scan_is_complete_json_safe_and_not_mutating(self):
        r=self.actual
        self.assertTrue(r['supported']);self.assertTrue(r['complete'])
        self.assertEqual(r['total_cases'],16);self.assertEqual(r['successful_cases'],16)
        self.assertEqual(self.p,self.original)
        json.dumps(r,allow_nan=False)
        self.assertEqual(len({(c['V_in'],tuple(c['powers'])) for c in r['cases']}),16)
        self.assertEqual({c['V_in'] for c in r['cases']},{20.,30.})
        for c in r['cases']:
            self.assertEqual(c['voltages'][0],30.)
            self.assertLess(c['residual'],2e-5)

    def test_extrema_and_pure_cross_definition(self):
        for j,row in enumerate(self.actual['summary']):
            values=[c['voltages'][j] for c in self.actual['cases']]
            self.assertEqual(row['V_min'],min(values));self.assertEqual(row['V_max'],max(values))
            groups={}
            for c in self.actual['cases']:groups.setdefault((c['V_in'],c['powers'][j]),[]).append(c['voltages'][j])
            expected=max(max(v)-min(v) for v in groups.values())/row['V_reference']*100
            self.assertAlmostEqual(row['cross_only_pct'],expected)
        self.assertGreater(self.actual['summary'][1]['span_pct'],0)

    def test_report_input_slices_are_not_duplicated_global_results(self):
        for vin in (20.,30.):
            data=for_input(self.actual,vin)
            self.assertEqual(data['total_cases'],8)
            self.assertTrue(all(c['V_in']==vin for c in data['cases']))
            for j,row in enumerate(data['summary']):
                self.assertEqual(row['V_max'],max(c['voltages'][j] for c in data['cases']))

    def test_declared_min_validation_and_old_file_migration(self):
        p=sample()
        for r in p['outputs']:r.pop('P_out_min')
        self.assertTrue(all(r['P_out_min']==r['P_out'] for r in output_specs(p)))
        for value in (-1,31,float('nan'),float('inf'),True,'1'):
            with self.subTest(value=value):
                bad=sample();bad['outputs'][0]['P_out_min']=value
                with self.assertRaises(ValueError):output_specs(bad)
        scaled=scale_load(self.p,.01)
        self.assertTrue(all(r['P_out_min']<=r['P_out'] for r in output_specs(scaled)))

    def test_no_load_is_unavailable_not_epsilon_and_no_ideal_answer(self):
        p=sample();p['outputs'][1]['P_out_min']=0
        result=scan_cross_regulation(p,voltages=[20.])
        self.assertFalse(result['complete'])
        unavailable=[c for c in result['cases'] if c['powers'][1]==0]
        self.assertEqual(len(unavailable),4)
        self.assertTrue(all(c['voltages'] is None and c['status']=='unavailable' for c in unavailable))
        p['coupling_config']['k']=[[1]*4 for _ in range(4)]
        self.assertFalse(scan_cross_regulation(p)['supported'])
        p['coupling_config']['enabled']=False
        self.assertFalse(scan_cross_regulation(p)['supported'])

    def test_cancellation_propagates(self):
        with self.assertRaises(CalculationCancelled):scan_cross_regulation(self.p,cancelled=lambda:True)

    def test_six_outputs_generate_64_unique_corners_and_keep_hardware(self):
        p=sample();p.update(V_in_min=30.,V_in_max=30.)
        for n in range(4,7):p['outputs'].append(dict(name=f'OUT{n}',Ns=2,V_out=5.,P_out=.5,P_out_min=.05))
        p['coupling_config']['k']=[[1 if i==j else .995 for j in range(7)] for i in range(7)]
        seen=[]
        from power_stage import compute_operating_point as actual_operating_point
        def solve(q):
            if not q.get('outputs'):return actual_operating_point(q)
            seen.append(q)
            if len(seen)==3:raise ValueError('injected failure')
            rails=output_specs(q)
            return dict(coupled_solution={},D=.3,coupled_model=dict(normalized_residual=1e-9),
                output_ops=[dict(V_out=r['V_out'],P_out=r['P_out'],mode='CCM') for r in rails])
        fixed=copy.deepcopy(p);fixed['_fixed_transformer']={'sentinel':'one BOM'}
        with patch('analysis_workflows.pin_hardware',return_value=fixed),patch('power_stage.compute_operating_point',side_effect=solve),patch('winding_coupling.resolve_winding_model',return_value={'ideal':False}):
            result=scan_cross_regulation(p,reference_result={})
        self.assertEqual(result['total_cases'],64);self.assertEqual(len(seen),64)
        self.assertEqual(result['successful_cases'],63);self.assertFalse(result['complete'])
        self.assertTrue(all(q['_fixed_transformer']==fixed['_fixed_transformer'] for q in seen))
        self.assertTrue(all(not r['complete'] for r in result['summary']))


if __name__=='__main__':unittest.main()
