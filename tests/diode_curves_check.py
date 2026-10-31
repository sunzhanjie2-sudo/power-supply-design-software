import copy
import json
from pathlib import Path
import sys
import tempfile
import tkinter as tk
import unittest
from unittest.mock import Mock,patch

ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
from runtime_resources import configure_numeric_threads
configure_numeric_threads()
import numpy as np
from diode_curves import validate_curve,validate_bank,conduction,from_xy,active_diodes
from design_api import load_spec
from loss_model import compute_design


def curve(name='示例正向曲线',a=.45,b=.08):
    # Artificial linear Vf(I) fixture, not a real device datasheet.
    return validate_curve(dict(name=name,points=[[a,0.],[a+b,1.],[a+10*b,10.]]))


def spec():
    p=load_spec(json.loads((ROOT/'examples/40W_CCM_FLYBACK.json').read_text(encoding='utf-8')))
    p.update(d_in_enable=True,d_out_enable=True)
    return p


class CurveChecks(unittest.TestCase):
    def test_pixel_backsteps_are_fitted_and_cleanup_survives_validation(self):
        raw=dict(name='描点回退回归',points=[[.557,.2],[1.0915462814,10.9274191939],
            [1.0958266453,10.9262018078],[1.1035313002,11.2363579377],
            [1.1069555912,11.1949707944],[1.202,15.34]])
        original=copy.deepcopy(raw);clean=validate_curve(raw)
        self.assertEqual(raw,original)
        self.assertTrue(all(b[0]>=a[0] for a,b in zip(clean['points'],clean['points'][1:])))
        self.assertEqual(clean['cleanup']['adjusted_points'],4)
        self.assertLess(clean['cleanup']['max_adjustment_V'],.003)
        self.assertEqual(validate_curve(clean),clean)
        self.assertEqual(validate_bank({'D1':clean})['D1'],clean)
        model=conduction([0.,1.,11.,16.],clean)
        self.assertGreater(model['P_cond'],0.)
        self.assertEqual(model['cleanup'],clean['cleanup'])
        self.assertTrue(any('回退点' in note for note in model['notes']))

    def test_cumulative_backtrack_not_disguised_by_small_steps(self):
        points=[[.5,0.],[1.,1.]]+[[1.-i*.001,i+1.] for i in range(1,81)]+[[1.2,100.]]
        with self.assertRaisesRegex(ValueError,'明显倒退'):validate_curve(dict(points=points))
        boundary=validate_curve(dict(points=[[0.,0.],[1.,1.],[.98,2.],[2.,3.]]))
        self.assertTrue(boundary.get('cleanup'))
        with self.assertRaises(ValueError):validate_curve(dict(points=[[0.,0.],[1.,1.],[.9,2.],[2.,3.]]))

    def test_import_dialog_stays_on_screen_with_offscreen_owner(self):
        from simple_curve_ui import _place_dialog
        dialog=Mock()
        for method,value in [('winfo_reqwidth',590),('winfo_reqheight',450),('winfo_screenwidth',1920),('winfo_screenheight',1080)]:
            getattr(dialog,method).return_value=value
        owner=Mock()
        for method,value in [('winfo_rootx',-3000),('winfo_rooty',-500),('winfo_width',1200),('winfo_height',800)]:
            getattr(owner,method).return_value=value
        _place_dialog(dialog,owner)
        dialog.geometry.assert_called_once_with('620x470+16+32')

    def test_pulsed_power_is_mean_iv_not_average_current_lookup(self):
        i=np.array([0.,0.,2.,4.]);c=curve()
        d=conduction(i,c)
        self.assertAlmostEqual(d['P_cond'],.45*np.mean(i)+.08*np.mean(i*i))
        self.assertNotAlmostEqual(d['P_cond'],float(np.mean(i))*(.45+.08*np.mean(i)))

    def test_zero_current_negative_current_and_endpoint_extension(self):
        c=validate_curve(dict(points=[[.5,1.],[.7,3.]]))
        d=conduction([-2.,0.,.5,5.],c)
        self.assertAlmostEqual(d['P_cond'],(.45*.5+.9*5)/4)
        self.assertEqual(len(d['extrapolations']),2)
        self.assertEqual(conduction([0,0],c)['P_cond'],0.)

    def test_validation_and_quantity_scale(self):
        c=from_xy(dict(name='mA 曲线',points=[[500,100],[600,1000]]),1e-3,1e-3)
        self.assertEqual(c['points'],[[.5,.1],[.6,1.]])
        for data in [dict(points=[[1,2],[.5,3]]),dict(points=[[1,2],[2,2]]),dict(points=[[1,float('nan')],[2,3]])]:
            with self.assertRaises(ValueError):validate_curve(data)
        with self.assertRaises(ValueError):validate_bank({'D_SN1':curve()})

    def test_fixed_drop_ignores_deprecated_dynamic_resistance(self):
        p=spec();base=compute_design(p)
        p.update(Rd_diode=999.,Rd_din=999.,Rd_dout=999.)
        changed=compute_design(p)
        self.assertEqual(base['P_total'],changed['P_total'])
        self.assertAlmostEqual(base['semi']['diode']['P_cond'],p['Vf_diode']*base['op']['I_d_avg'])

    def test_independent_rectifier_input_output_bindings(self):
        p=spec();p['diode_curves']={'D1':curve('整流'), 'D_IN':curve('输入',.2,.03),'D_OUT':curve('输出',.3,.05)}
        saved=copy.deepcopy(p);r=compute_design(p)
        self.assertEqual(p,saved)
        self.assertAlmostEqual(r['semi']['diode']['P_cond'],conduction(r['wf']['i_d'],p['diode_curves']['D1'])['P_cond'])
        self.assertAlmostEqual(r['P_din'],conduction(r['wf']['i_in'],p['diode_curves']['D_IN'])['P_cond'])
        self.assertAlmostEqual(r['P_dout'],conduction([r['op']['I_out']],p['diode_curves']['D_OUT'])['P_cond'])
        self.assertEqual({d['ref'] for d in r['diode_models']},{'D1','D_IN','D_OUT'})

    def test_multi_outputs_independent_even_when_out2_is_feedback(self):
        p=load_spec(json.loads((ROOT/'examples/6_OUTPUT_FLYBACK_SSR.json').read_text(encoding='utf-8')))
        p['outputs']=p['outputs'][:3];p['feedback_output']=2
        p['diode_curves']={f'D_O{i}':curve(f'器件{i}',.2+i*.1,.01*i) for i in range(1,4)}
        r=compute_design(p)
        for row,wf in zip(r['outputs'],r['wf']['outputs']):
            c=p['diode_curves'][f"D_O{row['id']}"]
            self.assertAlmostEqual(row['diode']['P_cond'],conduction(wf['i_d'],c)['P_cond'])
            self.assertEqual(row['diode']['curve_name'],c['name'])
        self.assertEqual(len([m for m in r['diode_models'] if m['kind']=='rectifier']),3)

    def test_forward_rectifier_and_freewheel_are_independent(self):
        p=load_spec(json.loads((ROOT/'examples/40W_ACF_FORWARD.json').read_text(encoding='utf-8')))
        p['diode_curves']={'D1':curve('正向整流'), 'D2':curve('续流',.2,.02)}
        r=compute_design(p)
        self.assertAlmostEqual(r['semi']['freewheel']['P_cond'],conduction(r['wf']['i_free'],p['diode_curves']['D2'])['P_cond'])
        self.assertEqual(r['semi']['diode']['curve_name'],'正向整流')
        self.assertEqual(r['semi']['freewheel']['curve_name'],'续流')

    def test_two_input_endpoints_reuse_same_curve_not_same_loss(self):
        from input_voltage_range import calculate_input_endpoints
        p=spec();p.update(V_in_min=20.,V_in_max=40.,diode_curves={'D1':curve()})
        out=calculate_input_endpoints(p,include_loop=False,include_cross_regulation=False)
        self.assertEqual(len(out['cases']),2)
        losses=[]
        for case in out['cases']:
            self.assertFalse(case.get('error'),case.get('error'))
            r=case['result'];self.assertAlmostEqual(r['semi']['diode']['P_cond'],conduction(r['wf']['i_d'],p['diode_curves']['D1'])['P_cond'])
            losses.append(r['semi']['diode']['P_cond'])
        self.assertNotAlmostEqual(*losses,places=4)


class DiodeUIChecks(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        import main
        cls.root=tk.Tk();cls.root.withdraw()
        cls.app=main.PowerSupplyAnalyzer(cls.root)
        cls.app._building=True

    @classmethod
    def tearDownClass(cls):
        cls.root.destroy()

    def setUp(self):
        self.app._apply_config(json.loads((ROOT/'examples/40W_CCM_FLYBACK.json').read_text(encoding='utf-8')))
        self.app._building=True

    def test_curve_bank_roundtrip_and_new_config_clears_old_bank(self):
        a=self.app;a._diode_curves={'D1':curve('我选的二极管')}
        cfg=a._config_dict();self.assertEqual(cfg['diode_curves'],a._diode_curves)
        a._apply_config(cfg);self.assertEqual(a.get_params()['diode_curves']['D1']['name'],'我选的二极管')
        a._apply_config({});self.assertEqual(a._diode_curves,{})

    def test_import_target_and_axis_are_explicit_and_no_rd_fields_mapped(self):
        a=self.app
        a._folded_sections.clear();a._filter_params();self.root.update()
        self.assertEqual(set(a._curve_tree.get_children()),{'Q1:transfer','Q1:charge','D1','D_IN','D_OUT'})
        a._curve_tree.selection_set('D_OUT');a._curve_selection_note()
        self.assertIn('D_OUT',a._curve_detail.get());self.assertIn('X=Vf',a._curve_detail.get())
        for k in ('Rd_diode','Rd_din','Rd_dout'):
            self.assertFalse(a._param_widgets[k][0].grid_info())
            self.assertFalse(a._scalar_parameter_active(k))

    def test_import_binds_only_selected_designator_cancel_preserves(self):
        a=self.app;a._curve_tree.selection_set('D_OUT')
        with tempfile.TemporaryDirectory(dir=ROOT) as directory:
            path=Path(directory)/'我的二极管.json';path.write_text('[[0.5,0.1],[0.8,2.0]]',encoding='utf-8')
            with patch('diode_curve_ui.filedialog.askopenfilename',return_value=str(path)),patch('simple_curve_ui.import_simple',return_value=curve('已确认曲线')) as dialog:
                a._import_diode_curve()
            self.assertEqual(set(a._diode_curves),{'D_OUT'})
            self.assertIn('D_OUT',dialog.call_args.kwargs['target'])
            with patch('diode_curve_ui.filedialog.askopenfilename',return_value=str(path)),patch('simple_curve_ui.import_simple',return_value=None):a._import_diode_curve()
            self.assertEqual(a._diode_curves['D_OUT']['name'],'已确认曲线')


if __name__=='__main__':unittest.main(verbosity=2)
