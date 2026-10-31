import copy
import csv
import io
import json
from pathlib import Path
import sys
import tempfile
import tkinter as tk
import unittest
from unittest.mock import patch
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
from runtime_resources import configure_numeric_threads
configure_numeric_threads()
from design_api import load_spec
from input_voltage_range import calculate_input_endpoints,calculate_input_operating_point
from mos_manual import normalize_events
from simple_curves import read_simple,to_transfer,to_charge
from mos_curves import gate_voltage
from mos_gate_charge import read_charges


def events():
    return dict(min=dict(on=dict(Vgp=3.6,Qgs=4.8e-9),off=dict(Vgp=4.2,Qgs=5.6e-9)),
                max=dict(on=dict(Vgp=4.,Qgs=6e-9),off=dict(Vgp=4.8,Qgs=7e-9)))


def spec():
    p=load_spec(json.loads((ROOT/'examples/40W_CCM_FLYBACK.json').read_text(encoding='utf-8')))
    p.update(V_in_min=20.,V_in_max=40.,mos_miller_mode='manual',mos_manual_events=events())
    return p


class FourManualChecks(unittest.TestCase):
    def test_four_voltage_charge_pairs_feed_losses_and_waveforms(self):
        from switching_transients import switching_voltage_data
        p=spec();saved=copy.deepcopy(p)
        bundle=calculate_input_endpoints(p,include_loop=False,include_cross_regulation=False)
        for case in bundle['cases']:
            self.assertFalse(case.get('error'),case.get('error'))
            result=case['result'];gate=result['semi']['switch']['gate'];key=case['p']['input_voltage_case']
            for edge in ('on','off'):
                self.assertEqual(gate['Vgp_'+edge],p['mos_manual_events'][key][edge]['Vgp'])
                self.assertEqual(gate['Qgs_'+edge],p['mos_manual_events'][key][edge]['Qgs'])
            self.assertEqual(switching_voltage_data(result['op'],case['p'],result['semi']['switch'])['gate'],gate)
        self.assertEqual(p,saved)

    def test_equal_voltages_do_not_reuse_different_manual_pairs(self):
        p=dict(spec(),V_in_min=30.,V_in_max=30.)
        bundle=calculate_input_endpoints(p,include_loop=False,include_cross_regulation=False)
        a,b=[c['result']['semi']['switch'] for c in bundle['cases']]
        self.assertEqual(a['gate']['manual_case'],'min');self.assertEqual(b['gate']['manual_case'],'max')
        self.assertNotEqual(a['t2'],b['t2']);self.assertNotEqual(a['t7'],b['t7'])
        selected=calculate_input_operating_point(dict(p,input_voltage_case='max'))
        self.assertEqual(selected['res']['semi']['switch']['gate']['manual_case'],'max')

    def test_equal_electrical_results_keep_correct_endpoint_provenance(self):
        p=dict(spec(),V_in_min=30.,V_in_max=30.)
        p['mos_manual_events']['max']=copy.deepcopy(p['mos_manual_events']['min'])
        bundle=calculate_input_endpoints(p,include_loop=False,include_cross_regulation=False)
        a,b=[c['result'] for c in bundle['cases']]
        self.assertEqual(a['semi']['switch']['gate']['manual_case'],'min')
        self.assertEqual(b['semi']['switch']['gate']['manual_case'],'max')
        self.assertIs(a['wf'],b['wf'])

    def test_plain_csv_json_and_collections_require_only_scale_selection(self):
        gate=[[0,0],[1,1],[2,2],[3,3],[5,4],[8,6],[11,6],[14,8],[18,12]]
        with tempfile.TemporaryDirectory(dir=ROOT) as d:
            f=Path(d)/'my.csv';f.write_text('x,y\n3,0.1\n4,5\n5,10',encoding='utf-8')
            c=to_transfer(read_simple(f)['curves'][0],y_multiplier=1e-3)
            self.assertAlmostEqual(gate_voltage(c,.005),4)
            self.assertGreater(gate_voltage(c,.02),5)
            for data in (gate,dict(points=gate),dict(curves=[dict(name='one',points=gate),dict(name='two',points=gate)])):
                f=Path(d)/'Qg.json';f.write_text(json.dumps(data),encoding='utf-8')
                parsed=read_simple(f);c=to_charge(parsed['curves'][0],source=parsed['source'])
                self.assertIsNone(c['Id_test_A']);self.assertIsNone(c['Vds_test_V'])
                g=read_charges(c,3.,13.,6.1,5.)
                self.assertAlmostEqual(g['Qgs_on'],8.15e-9);self.assertTrue(g['charge_extrapolations'])

    def test_legacy_migration_and_invalid_data(self):
        legacy=normalize_events({},dict(Vgp_on=3.8,Vgp_off=4.3,Qgs=5.2e-9))
        self.assertEqual(legacy['min'],legacy['max'])
        bad=events();bad['max']['off']['Qgs']=float('nan')
        with self.assertRaises(ValueError):normalize_events(bad)


class ManualUI(unittest.TestCase):
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

    def test_table_visibility_config_and_endpoint_selection(self):
        a=self.app;a.params['mos_miller_mode'].set('manual');a._folded_sections.clear();a._filter_params()
        for key in ('Vgp_on','Vgp_off','Qgs'):self.assertFalse(a._param_widgets[key][0].grid_info())
        for (case,edge,key),var in a._manual_event_vars.items():var.set(str(events()[case][edge][key]*(1e9 if key=='Qgs' else 1)))
        cfg=a._config_dict();a._apply_config(cfg)
        for case in ('min','max'):
            a.params['input_voltage_case'].set(case);self.assertTrue(a.update_all())
            g=a._last_design['semi']['switch']['gate']
            self.assertEqual(g['Vgp_on'],events()[case]['on']['Vgp'])
            self.assertAlmostEqual(g['Qgs_off'],events()[case]['off']['Qgs'])
        old=copy.deepcopy(self.base);old.pop('mos_manual_events',None);a._apply_config(old)
        self.assertEqual(a._manual_events_value()['min'],a._manual_events_value()['max'])

    def test_plain_import_uses_scale_dialog_and_cancel_keeps_existing(self):
        a=self.app
        with tempfile.TemporaryDirectory(dir=ROOT) as d:
            f=Path(d)/'Qg.json';f.write_text(json.dumps([[0,0],[5,4.4],[7,4.4],[15,10]]),encoding='utf-8')
            data=read_simple(f);candidate=to_charge(data['curves'][0])
            with patch('mos_curve_ui.filedialog.askopenfilename',return_value=str(f)),patch('simple_curve_ui.import_simple',return_value=candidate) as dialog:
                a._import_gate_charge();self.assertTrue(dialog.called)
            self.assertEqual(a.params['mos_charge_mode'].get(),'curve')
            self.assertEqual(a._mos_charge_curve,candidate)
            with patch('mos_curve_ui.filedialog.askopenfilename',return_value=str(f)),patch('simple_curve_ui.import_simple',return_value=None):a._import_gate_charge()
            self.assertEqual(a._mos_charge_curve,candidate)
            a._manual_event_vars['min','on','Qgs'].set('unused')
            self.assertEqual(str(a._manual_event_entries['min','on','Qgs'].cget('state')),'disabled')
            self.assertTrue(a.update_all())


if __name__=='__main__':unittest.main(verbosity=2)
