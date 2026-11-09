"""Snapshot-based presentation checks, including per-output devices and review states."""
import copy
import json
from pathlib import Path
import sys
import unittest

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from runtime_resources import configure_numeric_threads
configure_numeric_threads()
from design_engine.service import calculate, validate_spec
from magnetic_report_view import build_report, as_text


class MagneticReportChecks(unittest.TestCase):
    def solve(self,name):
        spec=json.loads((ROOT/'examples'/name).read_text(encoding='utf-8-sig'))
        run=calculate(spec,analysis='selected',include_loop=False,include_efficiency=False,include_cross_regulation=False)
        c=run.runtime_bundle()['cases'][0]
        self.assertFalse(c.get('error'),c.get('error'))
        return c

    def test_transformer_reports_each_winding_and_checks_without_changing_result(self):
        c=self.solve('40W_CCM_3OUT_FLYBACK.json')
        d=copy.deepcopy(c['result']['mag'])
        view=build_report(c['p'],c['result'])
        text=as_text(view)
        for key in ('DMR44','2400','Ve/Ae','0.33169','Steinmetz','OUT1','OUT2','OUT3','几何 DCR','Ri-a','kHz'):
            self.assertIn(key,text)
        self.assertEqual(d,c['result']['mag'])
        states={item['title']:item['state'] for item in view['conclusions']}
        self.assertEqual(states['磁饱和检查'],'success')
        self.assertEqual(states['温升检查'],'danger')
        self.assertEqual(states['气隙可实现性'],'warning')
        self.assertEqual(len([s for s in view['sections'] if '· 轻载' in s['title']]),1)
        c['p']['temp_rise_limit']=100.
        self.assertEqual(next(x for x in build_report(c['p'],c['result'])['conclusions'] if x['title']=='温升检查')['state'],'success')

    def test_all_forward_output_inductors_and_psr_auxiliary_are_present(self):
        c=self.solve('33W_3OUT_ACF_MP6005_COMPACT.json')
        text=as_text(build_report(c['p'],c['result']))
        for i in range(1,4):self.assertIn(f'OUT{i} · 输出电感 /',text)
        c=self.solve('MP6005_PSR_FLYBACK.json')
        text=as_text(build_report(c['p'],c['result']))
        self.assertIn('AUX 辅助绕组',text)

    def test_missing_design_and_infeasible_gap_do_not_claim_pass(self):
        p=validate_spec({})['spec']
        v=build_report(p,{'mag':{'transformer':{'ok':False,'reason':'磁芯不足'}}})
        self.assertIn('磁芯不足',as_text(v))
        self.assertNotIn('通过',as_text(v))
        c=self.solve('40W_CCM_3OUT_FLYBACK.json')
        gap=c['result']['mag']['transformer']['gap_design']
        gap.update(status='infeasible',gap_m=None)
        v=build_report(c['p'],c['result'])
        self.assertEqual(next(x for x in v['conclusions'] if x['title']=='气隙可实现性')['state'],'danger')

    def test_every_bundled_switching_example_uses_dmr44_preset(self):
        found=[]
        def visit(value):
            if isinstance(value,dict):
                if 'core_material' in value:
                    material=value['core_material']
                    self.assertEqual(material.get('v') if isinstance(material,dict) else material,'DMR44')
                    self.assertEqual(value['mu_r'],0.)
                    found.append(material)
                for child in value.values():visit(child)
            elif isinstance(value,list):
                for child in value:visit(child)
        for path in (ROOT/'examples').glob('*.json'):
            visit(json.loads(path.read_text(encoding='utf-8-sig')))
        self.assertGreaterEqual(len(found),18)


if __name__=='__main__':unittest.main(verbosity=2)
