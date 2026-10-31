"""Custom effective geometry, SI/unit round trips, fixed BOM and owned Tk UI."""
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
from custom_cores import CUSTOM_CORE, validate_geometry
from design_api import load_spec, run_design
from loss_model import compute_design
from magnetics import CORE_DB


def geometry(name='试制磁芯 A',scale=1.):
    return dict(name=name, Ae=62e-6*scale, Ve=2.8148e-6*scale,
                Wa=30e-6*scale, MLT=.044*scale)


def spec(name='40W_CCM_FLYBACK.json',**changes):
    return load_spec(dict(json.loads((ROOT/'examples'/name).read_text(encoding='utf-8')),**changes))


class GeometryChecks(unittest.TestCase):
    def test_mm_cm_and_si_match(self):
        a=validate_geometry(dict(Ae={'v':62,'u':'mm²'},Ve={'v':2.8148,'u':'cm³'},
                                 Wa={'v':.3,'u':'cm²'},MLT={'v':44,'u':'mm'}))
        b=validate_geometry(dict(Ae={'v':.62,'u':'cm²'},Ve={'v':2814.8,'u':'mm³'},
                                 Wa={'v':30,'u':'mm²'},MLT={'v':4.4,'u':'cm'}))
        for key in ('Ae','Ve','Wa','MLT'):
            self.assertAlmostEqual(a[key],b[key],places=14)
            self.assertAlmostEqual(a[key],geometry()[key],places=14)

    def test_invalid_active_dimensions_cannot_fall_back(self):
        for key in ('Ae','Ve','Wa','MLT'):
            for value in (None,0,-1,True,'-',float('nan'),float('inf')):
                with self.subTest(key=key,value=value), self.assertRaises(ValueError):
                    compute_design(spec(core_choice=CUSTOM_CORE,custom_core=dict(geometry(),**{key:value})))
        with self.assertRaises(ValueError):validate_geometry(dict(geometry(),width=20))
        with self.assertRaises(ValueError):validate_geometry(dict(geometry(),Ae={'v':1,'u':'mm'}))

    def test_same_geometry_preserves_standard_design(self):
        p=spec(MLT=0.)
        a=compute_design(p)
        b=compute_design(dict(p,core_choice=CUSTOM_CORE,custom_core=geometry()))
        for key in ('Ae','Ve','Wa','MLT','Np','Ns','B_pk','fill','P_core','P_cu','R_dc_p','dT'):
            self.assertAlmostEqual(a['mag']['transformer'][key],b['mag']['transformer'][key],places=11,msg=key)
        self.assertAlmostEqual(a['eta'],b['eta'],places=12)

    def test_geometry_actually_changes_all_calculations(self):
        p=spec(core_choice=CUSTOM_CORE,custom_core=geometry(),MLT=.9)
        a=compute_design(p)['mag']['transformer']
        self.assertEqual(a['MLT'],.044)  # custom MLT overrides the hidden legacy value
        for key,out,ratio in [('Ae','B_pk',.5),('Ve','P_core',2.),('Wa','fill',.5),('MLT','R_dc_p',2.)]:
            g=geometry();g[key]*=2
            b=compute_design(dict(p,custom_core=g))['mag']['transformer']
            self.assertAlmostEqual(b[out],a[out]*ratio,places=10)

    def test_inactive_draft_does_not_change_standard_result(self):
        p=spec();a=compute_design(p)
        b=compute_design(dict(p,custom_core={'Ae':'-'},custom_core_L={'Ve':None}))
        self.assertEqual(a['eta'],b['eta'])
        self.assertEqual(a['mag']['transformer'],b['mag']['transformer'])

    def test_vin_endpoints_freeze_and_own_custom_geometry(self):
        from input_voltage_range import calculate_input_endpoints
        from analysis_workflows import pin_hardware
        p=spec(core_choice=CUSTOM_CORE,custom_core=geometry(),V_in_min=24.,V_in_max=40.)
        bundle=calculate_input_endpoints(p,include_loop=False)
        for case in bundle['cases']:
            self.assertIsNone(case['error'])
            self.assertEqual(case['result']['mag']['transformer']['Ae'],62e-6)
            self.assertEqual(case['result']['mag']['transformer']['MLT'],.044)
        a=compute_design(p);fixed=pin_hardware(p,a)
        p['custom_core']['Ae']=999
        fixed['custom_core']['Ae']=888
        b=compute_design(fixed)
        self.assertEqual(b['mag']['transformer']['Ae'],62e-6)
        self.assertNotEqual(fixed['_fixed_transformer']['core_geometry']['Ae'],p['custom_core']['Ae'])

    def test_inductor_and_forward_magnetic_owners_are_separate(self):
        p=spec('40W_ACF_FORWARD.json',core_choice=CUSTOM_CORE,custom_core=geometry(),
               core_choice_L=CUSTOM_CORE,custom_core_L=geometry('输出电感',2.))
        r=compute_design(p)
        self.assertEqual(r['mag']['transformer']['Ae'],62e-6)
        self.assertEqual(r['mag']['inductor']['Ae'],124e-6)
        self.assertEqual(r['mag']['inductor']['MLT'],.088)
        p=spec(topology='BUCK',V_out=15.,core_choice=CUSTOM_CORE,custom_core=geometry())
        self.assertEqual(compute_design(p)['mag']['inductor']['Ae'],62e-6)

    def test_forward_multi_output_uses_each_custom_choke(self):
        p=spec('40W_ACF_FORWARD.json',core_choice=CUSTOM_CORE,custom_core=geometry(),
               outputs=[dict(V_out=30.,P_out=30.,L=220e-6,Ns=12,core_choice_L=CUSTOM_CORE,
                             custom_core_L=geometry('电感一',2.)),
                        dict(P_out=10.,Ns=6,L=220e-6,core_choice_L=CUSTOM_CORE,
                             custom_core_L=geometry('电感二',3.))])
        r=compute_design(p)
        self.assertEqual([d['core_label'] for d in r['mag']['inductors']],['电感一','电感二'])
        for dev,want in zip(r['mag']['inductors'],[124e-6,186e-6]):
            self.assertAlmostEqual(dev['Ae'],want,places=14)
        from analysis_workflows import pin_hardware
        q=pin_hardware(p,r)
        for rail in q['outputs']:rail['custom_core_L']={}
        actual=compute_design(q)
        for dev,want in zip(actual['mag']['inductors'],[124e-6,186e-6]):
            self.assertAlmostEqual(dev['Ae'],want,places=14)

    def test_coupled_predesign_and_dcr_match_custom_mlt(self):
        p=spec('3_OUTPUT_COUPLED_FLYBACK.json',core_choice=CUSTOM_CORE,custom_core=geometry(),MLT=.9)
        r=compute_design(p)
        hw=r['op']['coupled_model']['transformer_hardware']
        t=r['mag']['transformer']
        self.assertEqual(hw['core_geometry']['Ae'],t['Ae'])
        self.assertEqual(hw['MLT'],.044)
        for winding,actual in zip(hw['windings'],t['windings']):
            self.assertAlmostEqual(winding['R_dc'],actual['R_dc'])

    def test_api_and_word_excel_shared_report_record_source(self):
        p=spec(core_choice=CUSTOM_CORE,custom_core=geometry())
        data=run_design(p)
        self.assertEqual(data['magnetics']['core_label'],'试制磁芯 A')
        self.assertEqual(data['magnetics']['Ae'],62e-6)
        self.assertIn('非标准',data['magnetics']['MLT_source'])
        json.dumps(data,allow_nan=False)
        from docx import Document
        from report_docx import export_design_docx
        r=compute_design(p);doc=Document()
        with patch('report_docx.figure'),patch('report_docx._chart'),patch('report_docx._bars'):
            export_design_docx(None,p,r['op'],r['wf'],r,document=doc,save=False,
                               efficiency_curve=dict(fracs=[1.],etas=[r['eta']],modes=[r['op']['mode']],failures=[]))
        xml=doc.element.xml
        for value in ('试制磁芯 A','非标准磁芯尺寸输入','有效截面积 Ae','窗口面积 Wa','平均匝长 MLT'):
            self.assertIn(value,xml)


class CustomCoreUIChecks(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        import tkinter as tk
        import main
        cls.main=main;cls.root=tk.Tk();cls.root.attributes('-alpha',0)
        cls.updates=patch.object(main.PowerSupplyAnalyzer,'schedule_update',return_value=None)
        cls.updates.start();cls.app=main.PowerSupplyAnalyzer(cls.root)
        cls.original=copy.deepcopy(cls.app._config_dict())
        cls.root.unbind('<Configure>')
        for job in cls.root.tk.call('after','info'):cls.root.after_cancel(job)
        cls.root.geometry('1400x880');cls.root.update()

    @classmethod
    def tearDownClass(cls):
        cls.app._closing=True;cls.app._work_cancel.set()
        from engineering_ui import Tooltip
        Tooltip.hide_all(cls.root)
        for job in cls.root.tk.call('after','info'):cls.root.after_cancel(job)
        cls.root.destroy();cls.updates.stop()

    def setUp(self):
        self.errors=[];self.root.report_callback_exception=lambda *exc:self.errors.append(exc)
        self.app._apply_config(copy.deepcopy(self.original))
        self.app._folded_sections.clear();self.app.param_search.set('');self.app._filter_params()

    def tearDown(self):
        self.root.update();self.assertEqual(self.errors,[])

    def custom(self):
        self.app._custom_core_vars['custom_core'].set(json.dumps(geometry()))
        self.app.params['core_choice'].set(CUSTOM_CORE)
        self.app._filter_params();self.root.update()
        return self.app._custom_core_editors['custom_core']

    def test_custom_visibility_and_mm_cm_conversion(self):
        editor=self.custom()
        self.assertTrue(editor.frame.grid_info())
        self.assertFalse(self.app._param_widgets['MLT'][0].grid_info())
        self.assertEqual(float(editor.values['Ae'].get()),62.)
        editor.units['Ae'].set('cm²');editor.change_unit('Ae')
        self.assertAlmostEqual(float(editor.values['Ae'].get()),.62)
        self.assertAlmostEqual(self.app.get_params()['custom_core']['Ae'],62e-6)
        editor.values['MLT'].set('50')
        self.assertAlmostEqual(self.app.get_params()['custom_core']['MLT'],.05)
        for key in ('k_core','a_core','b_core'):
            self.assertTrue(self.app._param_widgets[key][0].grid_info())
        for size in ('1100x760','1400x880'):
            self.root.geometry(size);self.root.update()
            for child in editor.frame.winfo_children():
                self.assertLessEqual(child.winfo_x()+child.winfo_width(),editor.frame.winfo_width()+2,
                                     str(child)+' exceeds the geometry editor')

    def test_config_round_trip_keeps_units_and_draft(self):
        editor=self.custom();editor.units['MLT'].set('cm');editor.change_unit('MLT')
        cfg=json.loads(json.dumps(self.app._config_dict(),ensure_ascii=False,allow_nan=False))
        self.app._apply_config(self.original);self.app._apply_config(cfg)
        self.assertEqual(editor.units['MLT'].get(),'cm')
        self.assertAlmostEqual(float(editor.values['MLT'].get()),4.4)
        self.assertEqual(self.app.get_params()['core_choice'],CUSTOM_CORE)
        self.app.params['core_choice'].set('PQ20-20');self.root.update()
        self.assertFalse(editor.frame.grid_info())
        self.assertTrue(self.app._param_widgets['MLT'][0].grid_info())
        self.assertAlmostEqual(self.app.get_params()['custom_core']['MLT'],.044)

    def test_each_forward_output_editor_hidden_in_flyback(self):
        self.custom()
        self.app.params['topology'].set(self.main.TOPO_LABEL['ACF-FORWARD'])
        self.app.multi_enabled.set(True);self.app.output_count.set('2')
        for i in range(2):
            self.app._inline_output_vars[i]['custom_core_L'].set(json.dumps(geometry('L'+str(i),i+2.)))
            self.app._inline_output_vars[i]['core_choice_L'].set(CUSTOM_CORE)
        self.app._filter_params();self.root.update()
        for i in range(2):self.assertTrue(self.app._inline_custom_core_editors[i].frame.grid_info())
        cfg=self.app._config_dict();self.app._apply_config(cfg)
        self.assertEqual([r['custom_core_L']['MLT'] for r in self.app.get_params()['outputs']],[.088,.132])
        self.app.params['topology'].set(self.main.TOPO_LABEL['FLYBACK']);self.root.update()
        for i in range(2):self.assertFalse(self.app._inline_custom_core_editors[i].frame.grid_info())


if __name__=='__main__':unittest.main(verbosity=2)
