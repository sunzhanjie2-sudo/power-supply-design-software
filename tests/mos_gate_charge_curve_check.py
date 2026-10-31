"""Direct pre-Miller lookup, interchange and four-event integration checks."""
import copy
import csv
import json
import math
from pathlib import Path
import sys
import tempfile
import time
import unittest
import tkinter as tk
from unittest.mock import patch
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
from runtime_resources import configure_numeric_threads
configure_numeric_threads()
from mos_gate_charge import SCHEMA,COLLECTION,validate_charge,read_charges,read_charge_candidates
from design_api import load_spec
from input_voltage_range import calculate_input_endpoints
from mos_four_cases import event_rows


def profile():
    return dict(schema=SCHEMA,name='非真实器件 栅电荷接口测试',Tj_C=None,Id_test_A=12.,Vds_test_V=100.,
        Qgs_ref_C=8e-9,Qplateau_end_C=11e-9,points=[[0.,0.],[1e-9,1.],[2e-9,2.],[3e-9,3.],
        [5e-9,4.],[8e-9,6.],[11e-9,6.],[14e-9,8.],[18e-9,12.]],reviewed=True)


def spec():
    p=load_spec(json.loads((ROOT/'examples/40W_CCM_FLYBACK.json').read_text(encoding='utf-8')))
    p.update(V_in_min=20.,V_in_max=40.,gfs=5.,mos_charge_mode='curve',mos_charge_curve=profile())
    return p


class ChargeCurveChecks(unittest.TestCase):
    def test_nonlinear_pre_inverse_not_cgs(self):
        g=read_charges(profile(),3.,10.,3.5,5.)
        self.assertAlmostEqual(g['Qg_th'],3e-9)
        self.assertAlmostEqual(g['Qgs_on'],4e-9)
        self.assertAlmostEqual(g['Qgs_off'],6.5e-9)
        self.assertAlmostEqual(g['Qgd_on'],3e-9)
        self.assertAlmostEqual(g['Qg_on'],16e-9)
        self.assertNotIn('Cgs_incremental',g)

    def test_platform_start_never_platform_end(self):
        g=read_charges(profile(),3.,10.,6.,6.)
        self.assertAlmostEqual(g['Qgs_on'],8e-9)
        self.assertNotEqual(g['Qgs_on'],11e-9)

    def test_extrapolate_only_the_correct_branch(self):
        g=read_charges(profile(),3.,13.,6.1,5.)
        self.assertAlmostEqual(g['Qgs_on'],8.15e-9)
        self.assertAlmostEqual(g['Qg_on'],19e-9)
        self.assertEqual(len(g['charge_extrapolations']),2)
        for args in ((3.,10.,6.1,5.),(3.,13.,4.,5.)):
            with self.assertRaises(ValueError):read_charges(dict(profile(),allow_extrapolation=False),*args)
        with self.assertRaises(ValueError):read_charges(profile(),3.,6.,4.,5.)

    def test_metadata_and_flat_interval_validation(self):
        self.assertIsNone(validate_charge(profile())['Tj_C'])
        for change in (dict(Id_test_A=0),dict(Qgs_ref_C=11e-9),dict(Qplateau_end_C=18e-9),dict(Tj_C='unknown')):
            with self.assertRaises(ValueError):validate_charge(dict(profile(),**change))

    def test_json_csv_collection_roundtrip(self):
        p=profile()
        with tempfile.TemporaryDirectory(dir=ROOT) as folder:
            folder=Path(folder)
            f=folder/'gate.json';f.write_text(json.dumps(dict(schema=COLLECTION,curves=[p,dict(p,Vds_test_V=160.)])),encoding='utf-8')
            self.assertEqual(len(read_charge_candidates(f)),2)
            f=folder/'gate.csv';headers=['Qg_C','Vgs_V','Tj_C','Id_test_A','Vds_test_V','Qgs_ref_C','Qplateau_end_C']
            with f.open('w',newline='',encoding='utf-8-sig') as handle:
                writer=csv.writer(handle);writer.writerow(headers)
                writer.writerows([q,v]+[p[k] for k in headers[2:]] for q,v in p['points'])
            actual=read_charge_candidates(f)[0]
            self.assertEqual(actual['points'],p['points']);self.assertIsNone(actual['Tj_C'])
            self.assertEqual(len(actual['import_file']['sha256']),64)

    def test_four_event_times_loss_and_waveforms(self):
        from switching_transients import switching_voltage_data
        p=spec();before=copy.deepcopy(p)
        bundle=calculate_input_endpoints(p,include_loop=False,include_cross_regulation=False)
        for case in bundle['cases']:
            self.assertFalse(case.get('error'),case.get('error'))
            sw=case['result']['semi']['switch'];g=sw['gate'];params=case['p']
            expected=read_charges(p['mos_charge_curve'],params['Vth'],params['Vgs'],g['Vgp_on'],g['Vgp_off'])
            self.assertEqual(g['Qgs_on'],expected['Qgs_on']);self.assertEqual(g['Qgs_off'],expected['Qgs_off'])
            self.assertNotIn('Cgs_incremental',g)
            ron=params['Rg_drive']+params['Rs_on']+params['Rg'];roff=params['Rg_drive']+params['Rs_off']+params['Rg']
            self.assertAlmostEqual(sw['t3'],g['Qgd_on']*ron/(params['Vgs']-g['Vgp_on']))
            self.assertAlmostEqual(sw['t6'],g['Qgd_off']*roff/g['Vgp_off'])
            self.assertAlmostEqual(sw['P_gate'],params['Vgs']*g['Qg_on']*case['result']['op']['f_sw'])
            waves=switching_voltage_data(case['result']['op'],params,sw)
            self.assertEqual(waves['gate'],g)
        rows=event_rows(bundle)
        self.assertEqual(len(rows),4)
        self.assertEqual(len(set(r[3] for r in rows)),4)
        self.assertEqual(len(set(r[4] for r in rows)),4)
        self.assertEqual(len(set(r[5] for r in rows)),1)
        self.assertEqual(p,before)


class ChargeUIChecks(unittest.TestCase):
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

    def test_embedded_charge_curve_config_and_old_reset(self):
        a=self.app;a._mos_charge_curve=profile();a.params['mos_charge_mode'].set('curve')
        a.set_param('Vgs',10.);a.set_param('Vgp_on',3.8);a.set_param('Vgp_off',4.3)
        saved=a._config_dict();a._mos_charge_curve={};a._apply_config(saved)
        self.assertEqual(a._mos_charge_curve['points'],profile()['points'])
        self.assertEqual(a.params['mos_charge_mode'].get(),'curve')
        self.assertTrue(a.update_all())
        a._apply_config(copy.deepcopy(self.base))
        self.assertFalse(a._mos_charge_curve);self.assertEqual(a.params['mos_charge_mode'].get(),'manual')

    def test_inactive_scalar_charge_drafts_are_ignored(self):
        a=self.app;a._mos_charge_curve=profile();a.params['mos_charge_mode'].set('curve');a._folded_sections.clear();a._filter_params()
        for key in ('Qg','Qg_th','Qgs','Qgd'):
            self.assertFalse(a._param_widgets[key][0].grid_info())
            a.params[key].set('unused')
        self.assertTrue(a.update_all())
        self.assertEqual(a._last_design['semi']['switch']['gate']['charge_mode'],'curve')

    def test_failed_or_cancelled_import_does_not_replace_data(self):
        a=self.app;before=copy.deepcopy(a._mos_charge_curve)
        with patch('mos_curve_ui.filedialog.askopenfilename',return_value=''):a._import_gate_charge()
        self.assertEqual(a._mos_charge_curve,before)
        with patch('mos_curve_ui.filedialog.askopenfilename',return_value=str(ROOT/'examples/40W_CCM_FLYBACK.json')),patch('mos_curve_ui.messagebox.showerror') as error:
            a._import_gate_charge();self.assertTrue(error.called)
        self.assertEqual(a._mos_charge_curve,before)

    def test_four_event_dialog_completes_and_clears_stale_rows(self):
        from tkinter import ttk
        a=self.app;a._show_mos_four();dialog=a._mos_four_dialog;dialog.withdraw()
        def descendants(widget):
            for child in widget.winfo_children():yield child;yield from descendants(child)
        tree=next(w for w in descendants(dialog) if isinstance(w,ttk.Treeview))
        deadline=time.monotonic()+6
        while len(tree.get_children())!=4 and time.monotonic()<deadline:
            self.root.update();time.sleep(.01)
        self.assertEqual(len(tree.get_children()),4)
        a.set_param('V_in_max',35.)
        deadline=time.monotonic()+1.5
        while tree.get_children() and time.monotonic()<deadline:
            self.root.update();time.sleep(.01)
        self.assertFalse(tree.get_children())
        dialog.tk.call(dialog.protocol('WM_DELETE_WINDOW'))
        self.assertIsNone(a._mos_four_dialog)


if __name__=='__main__':unittest.main(verbosity=2)
