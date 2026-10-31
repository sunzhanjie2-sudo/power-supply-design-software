"""Explicit curve types, inverse interpolation and config/import workflows."""
import copy
import json
import math
from pathlib import Path
import sys
import tempfile
import tkinter as tk
import unittest
from unittest.mock import patch

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from runtime_resources import configure_numeric_threads
configure_numeric_threads()
from mos_curves import SCHEMA,validate_curve,read_curve_candidates,gate_voltage
from mos_gate import operating_gate
from design_api import load_spec,run_design
from loss_model import compute_design
from input_voltage_range import calculate_input_endpoints
from switching_transients import switching_voltage_data


def demo(kind='transfer'):
    return read_curve_candidates(ROOT/'examples'/('MOS_CURVE_DEMO_TRANSFER.csv' if kind=='transfer' else 'MOS_CURVE_DEMO_OUTPUT_FAMILY.csv'))[0]


def spec(kind='transfer'):
    p=load_spec(json.loads((ROOT/'examples/40W_CCM_FLYBACK.json').read_text(encoding='utf-8')))
    p.update(mos_miller_mode='curve',mos_miller_curve=demo(kind),mos_curve_vds=2.,V_in_min=20.,V_in_max=40.)
    return p


class CurveChecks(unittest.TestCase):
    def test_transfer_linear_inverse_and_endpoints(self):
        c=demo()
        self.assertAlmostEqual(gate_voltage(c,3.5),3.75)
        self.assertEqual(gate_voltage(c,.1),3.1)
        self.assertEqual(gate_voltage(c,20.),6.)
        self.assertGreater(gate_voltage(c,21.),6.)
        for current in (.01,21.):
            with self.assertRaises(ValueError):gate_voltage(dict(c,allow_extrapolation=False),current)

    def test_declared_log_axes_are_respected_on_inversion(self):
        c=validate_curve(dict(schema=SCHEMA,kind='transfer',x_scale='linear',y_scale='log',points=[[3.,1.],[5.,100.]]))
        self.assertAlmostEqual(gate_voltage(c,10.),4.)
        c=validate_curve(dict(c,x_scale='log'))
        self.assertAlmostEqual(gate_voltage(c,10.),math.sqrt(15.))

    def test_output_family_needs_multiple_vgs_and_fixed_vds(self):
        c=demo('output_family')
        self.assertEqual(gate_voltage(c,5.,2.),4.)
        self.assertAlmostEqual(gate_voltage(c,8.5,2.),4.5)
        for current,voltage in ((1.,0.),(1.,5.),(.1,2.),(21.,2.)):
            with self.assertRaises(ValueError):gate_voltage(dict(c,allow_extrapolation=False),current,voltage)

    def test_bad_curves_are_rejected_not_sorted_into_a_false_inverse(self):
        c=demo()
        for points in ([[3.,1.],[3.,2.]],[[3.,1.],[4.,1.]],[[3.,2.],[4.,1.]],[[3.,True],[4.,2.]],[[3.,1.],[4.,math.inf]],[[3.,1.],[4.,10**1000]]):
            with self.subTest(points=points),self.assertRaises(ValueError):validate_curve(dict(c,points=points))
        out=demo('output_family');out['traces'][1]['Vgs_V']=out['traces'][0]['Vgs_V']
        with self.assertRaises(ValueError):validate_curve(out)

    def test_family_crossed_at_reading_slice_is_not_ambiguous(self):
        c=demo('output_family')
        c['traces'][1]['points']=[[x,y*100] for x,y in c['traces'][1]['points']]
        with self.assertRaises(ValueError):gate_voltage(validate_curve(c),3.,2.)

    def test_csv_does_not_guess_axes_units_temperature_or_single_family_trace(self):
        samples=['x,y\n1,2\n2,3','Vds_V,Ids_A\n1,2\n2,3','Vgs_V,Ids_A,Tj_C\n3,1,25\n4,2,125',
            'Vgs_V,Vds_V,Ids_A\n4,1,2\n4,2,3','Vgs_V,Ids_A\n','Vgs_V,Ids_A,Ids_A\n3,1,2\n4,2,3']
        with tempfile.TemporaryDirectory(prefix='_tmp_mos_curve_test_',dir=ROOT) as d:
            path=Path(d)/'curve.csv'
            for text in samples:
                path.write_text(text,encoding='utf-8')
                with self.subTest(text=text),self.assertRaises(ValueError):read_curve_candidates(path)

    def test_studio_units_multiple_candidates_and_source_retention(self):
        c=dict(kind='mosfet_transfer',name='25 C',x_quantity='Vgs',y_quantity='Ids',x_unit='mV',y_unit='mA',
            points=[[3100,100],[4000,5000]],conditions='Vds=20 V; Tj=25 C',reviewed=False,
            source=dict(filename='mos.pdf',page=3,stored_path='not-a-portable-reference'))
        payload=dict(family='mosfet',mpn='DEMO',curves=[c,dict(c,name='125 C')])
        with tempfile.TemporaryDirectory(prefix='_tmp_mos_curve_test_',dir=ROOT) as d:
            path=Path(d)/'part.json';path.write_text(json.dumps(payload),encoding='utf-8')
            result=read_curve_candidates(path)
        self.assertEqual(len(result),2)
        self.assertEqual(result[0]['points'],[[3.1,.1],[4.,5.]])
        self.assertEqual(result[0]['source'],dict(filename='mos.pdf',page=3))
        self.assertEqual(result[0]['import_file']['filename'],'part.json')

    def test_manual_is_independent_of_gfs_and_curves(self):
        p=spec();r=compute_design(p)
        gate=operating_gate(r['op'],dict(p,mos_miller_mode='manual',gfs='not used',mos_miller_curve={}))
        self.assertEqual((gate['Vgp_on'],gate['Vgp_off']),(p['Vgp_on'],p['Vgp_off']))
        self.assertEqual(gate['mode'],'fixed')

    def test_current_zero_limit_and_drive_limit_do_not_extrapolate(self):
        p=spec();op=compute_design(p)['op']
        zero=operating_gate(dict(op,I_sw_on=0.),p)
        self.assertEqual(zero['Vgp_on'],p['Vth'])
        extended=operating_gate(dict(op,I_sw_on=.001,I_sw_off=30.),p)
        self.assertTrue(extended['extrapolations'])
        with self.assertRaises(ValueError):operating_gate(dict(op,I_sw_off=20.),dict(p,Vgs=5.5))

    def test_both_curve_types_endpoints_charges_and_waveforms(self):
        for kind in ('transfer','output_family'):
            p=spec(kind);saved=copy.deepcopy(p)
            bundle=calculate_input_endpoints(p,include_loop=False,include_cross_regulation=False)
            self.assertEqual(p,saved)
            gates=[]
            for case in bundle['cases']:
                r=case['result'];sw=r['semi']['switch'];gate=sw['gate'];gates.append(gate)
                self.assertEqual(gate['mode'],'curve')
                self.assertAlmostEqual(gate['Vgp_on'],gate_voltage(p['mos_miller_curve'],gate['I_on'],2.))
                self.assertAlmostEqual(gate['Vgp_off'],gate_voltage(p['mos_miller_curve'],gate['I_off'],2.))
                self.assertNotEqual(gate['Qgs_on'],gate['Qgs_off'])
                data=switching_voltage_data(r['op'],case['p'],sw)
                self.assertEqual(data['on'][2]['vgs'][0],gate['Vgp_on'])
                self.assertEqual(data['off'][1]['vgs'][0],gate['Vgp_off'])
            self.assertNotEqual(gates[0]['Vgp_on'],gates[1]['Vgp_on'])

    def test_curve_api_and_empty_curve_errors(self):
        p=spec();result=run_design(p)
        self.assertEqual(result['mosfet']['gate']['mode'],'curve')
        self.assertNotIn('points',result['mosfet']['gate']['curve_info'])
        with self.assertRaises(ValueError):load_spec(dict(mos_miller_mode='curve'))


class CurveUIChecks(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        import main
        cls.root=tk.Tk();cls.root.withdraw();cls.app=main.PowerSupplyAnalyzer(cls.root)
        cls.base=copy.deepcopy(cls.app._config_dict())

    @classmethod
    def tearDownClass(cls):
        cls.app._closing=True;cls.app._calculation_worker.close()
        for job in cls.root.tk.call('after','info'):cls.root.after_cancel(job)
        cls.root.destroy()

    def setUp(self):self.app._apply_config(copy.deepcopy(self.base))

    def test_import_embed_round_trip_and_old_file_reset(self):
        a=self.app
        with patch('mos_curve_ui.filedialog.askopenfilename',return_value=str(ROOT/'examples/MOS_CURVE_DEMO_TRANSFER.csv')):
            a._import_mos_curve()
        self.assertEqual(a.params['mos_miller_mode'].get(),'curve')
        self.assertTrue(a.update_all())
        self.assertIn('曲线查值',a.mos_gate_readout.get())
        cfg=a._config_dict();a._mos_miller_curve={};a._apply_config(copy.deepcopy(cfg))
        self.assertEqual(a._mos_miller_curve,cfg['mos_miller_curve'])
        self.assertTrue(a.update_all())
        a._apply_config(copy.deepcopy(self.base))
        self.assertFalse(a._mos_miller_curve)
        self.assertEqual(a._mos_resolved_mode(),'manual')

    def test_mode_visibility_and_unused_values(self):
        a=self.app;a._mos_miller_curve=demo('output_family');a.params['mos_miller_mode'].set('curve');a.set_param('mos_curve_vds',2.)
        a._folded_sections.clear();a._filter_params()
        self.assertTrue(a._param_widgets['mos_curve_vds'][0].grid_info())
        self.assertFalse(a._param_widgets['gfs'][0].grid_info())
        self.assertFalse(a._param_widgets['Vgp_off'][0].grid_info())
        a.params['gfs'].set('unused');a.params['Vgp_off'].set('unused')
        self.assertTrue(a.update_all())
        a.params['mos_miller_mode'].set('manual');a.set_param('Vgp_off',4.3)
        a.params['mos_curve_vds'].set('unused');self.assertTrue(a.update_all())
        self.assertFalse(a._param_widgets['mos_curve_vds'][0].grid_info())
        self.assertFalse(a._param_widgets['Vgp_off'][0].grid_info())
        self.assertTrue(a._manual_event_entries['min','off','Vgp'].grid_info())

    def test_import_cancel_invalid_and_explicit_curve_choice_keep_state(self):
        a=self.app;before=copy.deepcopy(a._mos_miller_curve)
        with patch('mos_curve_ui.filedialog.askopenfilename',return_value=''):
            a._import_mos_curve()
        self.assertEqual(a._mos_miller_curve,before)
        with patch('mos_curve_ui.filedialog.askopenfilename',return_value=str(ROOT/'examples/40W_CCM_FLYBACK.json')),patch('mos_curve_ui.messagebox.showerror') as error:
            a._import_mos_curve();self.assertTrue(error.called)
        self.assertEqual(a._mos_miller_curve,before)
        bad=dict(self.base,mos_miller_mode='curve',mos_miller_curve={})
        with self.assertRaises(ValueError):a._apply_config(bad)

    def test_multiple_candidates_use_explicit_selection_and_cancellation(self):
        a=self.app;first=demo();second=dict(first,name='another condition')
        before=copy.deepcopy(a._mos_miller_curve)
        with patch('mos_curve_ui.filedialog.askopenfilename',return_value='device.json'),patch('mos_curves.read_curve_candidates',return_value=[first,second]):
            with patch.object(a,'_select_mos_curve',return_value=None) as select:
                a._import_mos_curve();select.assert_called_once_with([first,second])
                self.assertEqual(a._mos_miller_curve,before)
            with patch.object(a,'_select_mos_curve',return_value=second):
                a._import_mos_curve()
        self.assertEqual(a._mos_miller_curve['name'],'another condition')
        self.assertEqual(a.params['mos_miller_mode'].get(),'curve')


if __name__=='__main__':unittest.main(verbosity=2)
