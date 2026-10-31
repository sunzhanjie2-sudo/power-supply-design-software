"""Ratings never replace electrical model inputs; missing evidence stays open."""
import copy
import json
import math
from pathlib import Path
import sys
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from runtime_resources import configure_numeric_threads
configure_numeric_threads()
from component_management import normalize_management, evaluate_components, component_registry, rule_for
from design_api import load_spec
from power_stage import DEFAULT_PARAMS
from loss_model import compute_design


def sample(name='40W_CCM_FLYBACK.json'):
    return load_spec(json.loads((ROOT/'examples'/name).read_text(encoding='utf-8')))


class ComponentChecks(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.p=sample(); cls.res=compute_design(cls.p)

    def test_validation_and_copy(self):
        for v in (-1, 0, math.nan, math.inf, True, '100'):
            with self.subTest(v=v), self.assertRaises(ValueError):
                normalize_management({'items':{'Q1':{'voltage_V':v}}})
        for value in ([], 'bad', {'zone':'III'}, {'version':2}, {'overrides':{'mos_voltage':.5}},
                      {'override_reason':'test','overrides':{'mos_voltage':1.1}}):
            with self.assertRaises(ValueError): normalize_management(value)
        raw={'items':{'Q1':{'manufacturer':'Test','voltage_V':200}}}
        copied=normalize_management(raw); copied['items']['Q1']['voltage_V']=1
        self.assertEqual(raw['items']['Q1']['voltage_V'],200)

    def test_workbook_merged_rules_and_zones(self):
        i,ii=normalize_management(),normalize_management({'zone':'II'})
        self.assertEqual(rule_for(i,'mos_voltage')['factor'],.85)
        self.assertEqual(rule_for(ii,'mos_voltage')['factor'],.90)
        self.assertEqual(rule_for(ii,'resistor_power')['factor'],.20)
        self.assertEqual(rule_for(ii,'film_ripple')['factor'],.90)
        self.assertIsNone(rule_for(i,'mlcc_ripple')['factor'])
        self.assertEqual(rule_for(normalize_management({'overrides':{'resistor_power':.1},'override_reason':'project'}),'resistor_power')['factor'],.1)

    def test_exact_limit_boundary_and_missing(self):
        p=dict(self.p,component_management={'items':{'Q1':{'voltage_V':100},'R_S1':{'power_W':1}}})
        def get(v):
            with patch('component_management.stress_map',return_value={('Q1','voltage'):(v,''),('R_S1','power'):(.2,'')}):
                return {c['id']:c for c in evaluate_components(p,self.res)['checks']}
        a=get(85.)
        self.assertEqual(a['bom_Q1_voltage']['state'],'pass')
        self.assertEqual(a['bom_R_S1_power']['state'],'pass')
        self.assertEqual(get(85.01)['bom_Q1_voltage']['state'],'review')
        self.assertEqual(a['bom_Q1_peak']['state'],'undefined')
        self.assertEqual(a['bom_D1_voltage']['state'],'undefined')

    def test_no_fabricated_identity_or_default_ratings(self):
        data=evaluate_components(self.p,self.res)
        self.assertGreater(data['counts']['undefined'],0)
        self.assertEqual(data['counts']['pass'],0)
        q=next(r for r in data['rows'] if r['ref']=='Q1')
        self.assertIsNone(q['model']); self.assertIsNone(q['voltage_V'])
        self.assertNotIn('R_LOAD',{r['ref'] for r in data['rows']})

    def test_capacitor_technology_and_individual_split(self):
        p=dict(self.p,component_management={'items':{'C_IN1':{'voltage_V':100,'ripple_A':.5,'capacitor_type':'electrolytic'},
                    'C_IN2':{'voltage_V':100,'ripple_A':10,'capacitor_type':'mlcc'}}})
        checks={c['id']:c for c in evaluate_components(p,self.res)['checks']}
        self.assertAlmostEqual(checks['bom_C_IN1_ripple']['value'],self.res['capacitors']['input']['caps'][0]['total'])
        self.assertAlmostEqual(checks['bom_C_IN2_ripple']['value'],self.res['capacitors']['input']['caps'][1]['total'])
        self.assertEqual(checks['bom_C_IN1_ripple']['state'],'review')
        self.assertEqual(checks['bom_C_IN2_ripple']['state'],'undefined')
        self.assertEqual(checks['bom_C_IN2_voltage']['factor'],.7)

    def test_wide_mos_peak_does_not_get_relaxed_ratio(self):
        r=copy.deepcopy(self.res);r['op']['clamp']['t_pulse']=r['op']['Ts']
        p=dict(self.p,component_management={'items':{'Q1':{'voltage_V':100}}})
        q=next(c for c in evaluate_components(p,r)['checks'] if c['id']=='bom_Q1_peak')
        self.assertEqual(q['factor'],.85)
        self.assertIn('稳态因数',q['note'])

    def test_multi_output_identity_and_context(self):
        p=sample('6_OUTPUT_FLYBACK_SSR.json');r=compute_design(p)
        data=evaluate_components(p,r);refs={row['ref'] for row in data['rows']}
        self.assertIn('D_O6',refs);self.assertIn('C_O6A',refs)
        self.assertNotIn('L_O6',refs);self.assertNotIn('D1',refs)
        d6=next(c for c in data['checks'] if c['id']=='bom_D_O6_voltage')
        self.assertEqual(d6['value'],r['outputs'][5]['op']['V_d_max'])
        self.assertNotEqual(d6['value'],r['outputs'][0]['op']['V_d_max'])
        p['component_management']={'items':{'D_O6':{'model':'retained'}}}
        p['outputs']=[]
        inactive=evaluate_components(p)
        self.assertIn('D_O6',inactive['inactive_refs'])

    def test_all_topology_registries_match_diagram(self):
        from topology_diagram import topology_components
        from power_stage import TOPOLOGIES
        for t in TOPOLOGIES:
            p=dict(copy.deepcopy(DEFAULT_PARAMS),topology=t,V_in=30,V_out=50 if t=='BOOST' else 12,
                   P_out=15,L=50e-6,N=1.,f_sw=100e3,Kc=1.5,K=.99,dC=.1)
            r=compute_design(p); rows=component_registry(p,r)
            self.assertEqual({x['ref'] for x in rows},{x['ref'] for x in topology_components(p,r['op']) if not x['ref'].startswith('R_LOAD')})
            evaluate_components(p,r)

    def test_metadata_does_not_change_electrical_solution(self):
        p=copy.deepcopy(self.p)
        p['component_management']=normalize_management({'items':{'Q1':{'manufacturer':'A','model':'B','package':'C','voltage_V':1}}})
        r=compute_design(p)
        self.assertEqual(r['eta'],self.res['eta'])
        self.assertEqual(r['op']['V_sw_max'],self.res['op']['V_sw_max'])
        self.assertTrue(any(c['state']=='review' for c in evaluate_components(p,r)['checks']))

    def test_engine_web_and_word_use_same_projection(self):
        from web_app.metadata import preview,normalize_config
        from design_engine.service import validate_spec
        from docx import Document
        from component_report import add_component_report
        p=dict(self.p,component_management={'zone':'II','items':{'Q1':{'manufacturer':'厂家甲','model':'测试型号','package':'SMD','voltage_V':200}}})
        self.assertTrue(validate_spec(p)['ok'])
        self.assertEqual(normalize_config(p)['component_management'],p['component_management'])
        with patch('loss_model.compute_design', side_effect=AssertionError('unexpected solve')):
            self.assertEqual({r['ref'] for r in preview(p)['component_rows']},{r['ref'] for r in component_registry(p)})
            doc=Document();add_component_report(doc,p,self.res)
        text='\n'.join(c.text for t in doc.tables for row in t.rows for c in row.cells)
        self.assertIn('厂家甲',text);self.assertIn('测试型号',text);self.assertIn('90%',text)
        self.assertIn('未考虑寄生尖峰',text)


if __name__=='__main__': unittest.main()
