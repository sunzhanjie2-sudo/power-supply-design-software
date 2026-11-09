"""Independent magnetic-circuit checks and calculator/export integration."""
import copy
import json
from pathlib import Path
import sys
import tempfile
import unittest

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from runtime_resources import configure_numeric_threads
configure_numeric_threads()
from transformer_gap import estimate, validate_inputs, MU0, MATERIAL_PERMEABILITY
from design_engine.service import calculate, validate_spec


class TransformerGapChecks(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.spec=json.loads((ROOT/'examples/40W_CCM_3OUT_FLYBACK.json').read_text(encoding='utf-8-sig'))
        cls.calculated=calculate(cls.spec,analysis='endpoints',include_loop=False,include_efficiency=False,include_cross_regulation=False)

    def test_example_gap_reconstructs_inductance_and_is_shared_between_endpoints(self):
        cases=self.calculated.runtime_bundle()['cases']
        self.assertTrue(all(not c.get('error') for c in cases))
        g=cases[0]['result']['mag']['transformer']['gap_design']
        self.assertEqual(g,cases[1]['result']['mag']['transformer']['gap_design'])
        self.assertEqual(g['material'],'DMR44')
        self.assertEqual(g['mu_r'],2400.)
        self.assertAlmostEqual(g['gap_m']*1000,.3316850734739543)
        self.assertAlmostEqual(g['AL_target_H']*1e9,222.2222222222)
        reluctance=g['le_m']/(MU0*g['mu_r']*g['Ae_m2'])+g['gap_m']/(MU0*g['Ae_m2'])
        self.assertAlmostEqual(g['primary_turns']**2/reluctance,g['target_inductance_H'],delta=1e-16)

    def test_mu_override_and_forward_inductance_keep_derived_path_length(self):
        c=self.calculated.runtime_bundle()['cases'][0]
        p=dict(c['p'],mu_r=1800.,le_core=.05,topology='ACF-FORWARD',Lm_forward=20e-6,L=80e-6)
        g=estimate(p,c['result']['mag']['transformer']['core_geometry'],6)
        self.assertEqual(g['target_inductance_H'],20e-6)
        self.assertEqual(g['mu_r'],1800.)
        self.assertAlmostEqual(g['le_m'],.0454)
        self.assertIsNone(g['material_source'])
        self.assertAlmostEqual(g['gap_m'],MU0*62e-6*36/20e-6-.0454/1800.)
        self.assertIn('Ve /',g['le_source'])

    def test_normal_calculation_keeps_user_inductance_and_waveforms(self):
        import numpy as np
        changed=calculate(dict(self.spec,mu_r=1800.,le_core=.05),analysis='endpoints',
                          include_loop=False,include_efficiency=False,include_cross_regulation=False)
        for old,new in zip(self.calculated.runtime_bundle()['cases'],changed.runtime_bundle()['cases']):
            self.assertFalse(new.get('error'))
            for key in ('D','I_sw_pk','I_L_rms','f_sw','V_out'):
                self.assertEqual(old['result']['op'][key],new['result']['op'][key])
            for key in ('t','i_p','i_s','v_out'):
                if key in old['result']['wf']:
                    np.testing.assert_array_equal(old['result']['wf'][key],new['result']['wf'][key])
            g=new['result']['mag']['transformer']['gap_design']
            self.assertEqual(g['mu_r'],1800.)
            self.assertAlmostEqual(g['le_m'],.0454)

    def test_word_and_excel_projection_include_gap_math_and_sources(self):
        from io import BytesIO
        from unittest.mock import patch
        from PIL import Image
        from docx import Document
        from report_docx import export_design_docx
        from report_xlsx import _capture_document
        png=BytesIO();Image.new('RGB',(120,80),'white').save(png,format='PNG')
        for c in self.calculated.runtime_bundle()['cases']:
            r=c['result'];doc=Document()
            with patch('report_docx._chart',return_value=png.getvalue()):
                export_design_docx('',c['p'],r['op'],r['wf'],r,document=doc,save=False,
                    efficiency_curve=dict(fracs=[1.],etas=[r['eta']],modes=[r['op']['mode']],failures=[]))
            section=_capture_document(doc)['magnetics']
            self.assertIn('估算等效总气隙',str(section))
            self.assertIn('222.2',str(section))
            self.assertIn('0.33',str(section))
            self.assertIn('无气隙励磁电感',str(section))
            self.assertIn('2400',str(section))
            self.assertTrue(doc.element.xpath('.//m:oMath//m:f'))

    def test_infeasible_and_zero_gap_are_distinct(self):
        core=dict(Ae=62e-6,Ve=2.8148e-6)
        p=dict(topology='FLYBACK',core_material='N87',L=2e-3)
        g=estimate(p,core,6)
        self.assertEqual(g['status'],'infeasible')
        self.assertIsNone(g['gap_m'])
        self.assertLess(g['gap_raw_m'],0)
        p['L']=g['L_ungapped_H']
        zero=estimate(p,core,6)
        self.assertEqual(zero['status'],'estimated')
        self.assertAlmostEqual(zero['gap_m'],0.)

    def test_materials_and_unknown_material(self):
        p=dict(topology='FLYBACK',core_material='Custom',L=8e-6)
        core=dict(Ae=62e-6,Ve=2.8148e-6)
        g=estimate(p,core,6)
        self.assertEqual(g['status'],'unavailable')
        self.assertIsNone(g['mu_r'])
        self.assertIsNone(g['gap_m'])
        for name,mu in [('N87',2200),('DMR44',2400),('PC40',2300),('3C90',2300),('3F3',2000),('N27',2000)]:
            self.assertEqual(estimate(dict(p,core_material=name),core,6)['mu_r'],mu)
            self.assertTrue(MATERIAL_PERMEABILITY[name]['source'].startswith('https://'))
        self.assertEqual(estimate(dict(p,mu_r=1500),core,6)['status'],'estimated')

    def test_invalid_and_unit_inputs(self):
        for key,value in [('mu_r',-1),('mu_r',4e-7),('mu_r',True),('le_core',float('nan')),('le_core',-1)]:
            with self.subTest(key=key,value=value),self.assertRaises(ValueError):
                validate_inputs({key:value})
        spec=copy.deepcopy(self.spec)
        spec.update(mu_r=2300,le_core={'v':4.8,'u':'c'})
        out=validate_spec(spec)
        self.assertTrue(out['ok'],out['issues'])
        self.assertAlmostEqual(out['spec']['le_core'],.048)

    def test_3d_export_keeps_estimate_separate_from_declared_geometry(self):
        from transformer_geometry import export_geometry_package,read_geometry_package
        with tempfile.TemporaryDirectory() as tmp:
            path=Path(tmp)/'T1.zip'
            export_geometry_package(self.calculated,path,self.spec)
            g=read_geometry_package(path)
        self.assertIsNone(g['core']['gap_geometry'])
        self.assertEqual(g['design_targets']['air_gap']['status'],'estimated')
        self.assertFalse(g['ready']['electromagnetic'])
        old=ROOT/'output/变压器三维建模/三路反激-r007接线建模.zip'
        if old.is_file():
            original=read_geometry_package(old)
            self.assertNotIn('air_gap',original['design_targets'])


if __name__=='__main__':unittest.main(verbosity=2)
