"""Current-dependent plateau, endpoint consistency and owned Tk regressions."""
import copy
import json
import math
from pathlib import Path
import sys
import tkinter as tk
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from runtime_resources import configure_numeric_threads
configure_numeric_threads()
from mos_gate import operating_gate
from semiconductor import mosfet_loss
from design_api import load_spec, run_design
from loss_model import compute_design
from input_voltage_range import calculate_input_endpoints, calculate_input_operating_point
from switching_transients import switching_voltage_data, draw_switching_event
from matplotlib.figure import Figure
import numpy as np


def spec():
    p = load_spec(json.loads((ROOT/'examples/40W_CCM_FLYBACK.json').read_text(encoding='utf-8')))
    return dict(p, V_in_min=20., V_in_max=40., gfs=5.)


class MillerChecks(unittest.TestCase):
    def test_currents_and_charge_map_are_used_in_times(self):
        p = spec(); r = compute_design(p); op = r['op']; sw = r['semi']['switch']; gate = sw['gate']
        self.assertEqual(gate['mode'], 'current')
        self.assertAlmostEqual(gate['Vgp_on'], p['Vth']+gate['I_on']/5)
        self.assertAlmostEqual(gate['Vgp_off'], p['Vth']+gate['I_off']/5)
        self.assertNotEqual(gate['Vgp_on'], gate['Vgp_off'])
        c = (p['Qgs']-p['Qg_th'])/(p['Vgp_on']-p['Vth'])
        self.assertAlmostEqual(gate['Qgs_on'], p['Qg_th']+c*(gate['Vgp_on']-p['Vth']), delta=1e-20)
        self.assertAlmostEqual(gate['Qgs_off'], p['Qg_th']+c*(gate['Vgp_off']-p['Vth']), delta=1e-20)
        ron = p['Rg_drive']+p['Rs_on']+p['Rg']; roff = p['Rg_drive']+p['Rs_off']+p['Rg']
        self.assertAlmostEqual(sw['t2'], -ron*gate['Qgs_on']/gate['Vgp_on']*math.log1p(-gate['Vgp_on']/p['Vgs'])-sw['t1'], delta=1e-20)
        self.assertAlmostEqual(sw['t3'], p['Qgd']*ron/(p['Vgs']-gate['Vgp_on']), delta=1e-20)
        self.assertAlmostEqual(sw['t6'], p['Qgd']*roff/gate['Vgp_off'], delta=1e-20)
        dv = gate['Vgp_off']-p['Vth']
        self.assertAlmostEqual(sw['t7'], roff*(gate['Qgs_off']-p['Qg_th'])/dv*math.log1p(dv/p['Vth']), delta=1e-20)
        for key in ('t1','t8','P_cond','P_gate','P_coss'):
            self.assertEqual(sw[key], compute_design(dict(p,gfs=0.))['semi']['switch'][key])

    def test_endpoints_recompute_not_duplicate_or_mutate(self):
        p = spec(); saved = copy.deepcopy(p)
        bundle = calculate_input_endpoints(p, include_loop=False, include_cross_regulation=False)
        self.assertEqual(p, saved)
        gates = [c['result']['semi']['switch']['gate'] for c in bundle['cases']]
        self.assertNotEqual(gates[0]['I_on'], gates[1]['I_on'])
        self.assertNotEqual(gates[0]['Vgp_on'], gates[1]['Vgp_on'])
        self.assertNotEqual(gates[0]['Vgp_off'], gates[1]['Vgp_off'])
        for case, gate in zip(bundle['cases'], gates):
            data = switching_voltage_data(case['result']['op'],case['p'],case['result']['semi']['switch'])
            self.assertEqual(data['gate'],gate)
            self.assertEqual(data['on'][2]['vgs'][0],gate['Vgp_on'])
            self.assertEqual(data['off'][1]['vgs'][0],gate['Vgp_off'])
            self.assertAlmostEqual(data['times']['t4'],3*(p['Rg_drive']+p['Rs_on']+p['Rg'])*(p['Qg']-gate['Qgs_on']-p['Qgd'])/(p['Vgs']-gate['Vgp_on']))

    def test_old_fixed_model_and_gfs_units(self):
        p = spec(); p.pop('gfs')
        self.assertEqual(compute_design(p)['semi']['switch']['gate']['mode'],'fixed')
        self.assertEqual(load_spec(dict(gfs={'v':5000,'u':'m'}))['gfs'],5.)

    def test_explicit_switch_edge_currents_take_priority(self):
        p = spec(); op = dict(compute_design(p)['op'], I_sw_on=-2., I_sw_off=-7.)
        g = operating_gate(op,p)
        self.assertEqual((g['I_on'],g['I_off']),(0.,7.))
        self.assertEqual((g['Vgp_on'],g['Vgp_off']),(p['Vth'],p['Vth']+7/5))

    def test_exact_and_near_zero_current_are_finite(self):
        p = spec(); base = compute_design(p)['op']
        for current in (0., 1e-14, 1e-10, 1e-6):
            op = dict(base,I_sw_on=current,I_sw_off=current)
            sw = mosfet_loss(op,p)
            d = switching_voltage_data(op,p,sw)
            self.assertGreaterEqual(sw['t2'],0.)
            self.assertGreaterEqual(sw['t7'],0.)
            for event in ('on','off'):
                self.assertTrue(all(np.isfinite(s['vgs']).all() for s in d[event]))
                fig = Figure(); ax = fig.subplots(); draw_switching_event(ax,d,event)
                self.assertIn('Vgp=',ax.get_title())
            if current == 0:
                self.assertEqual((sw['t2'],sw['t7']),(0.,0.))

    def test_qr_zero_current_reference_and_existing_loss_scope(self):
        p = dict(spec(),topology='QR-FLYBACK',P_out=2.)
        r = compute_design(p); sw = r['semi']['switch']
        self.assertEqual(sw['P_sw_on'],0.)
        self.assertEqual(sw['P_coss'],0.)
        self.assertEqual(sw['gate']['I_on'],0.)
        self.assertEqual(sw['gate']['I_off'],r['op']['I_L_pk'])

    def test_invalid_gfs_and_insufficient_drive_do_not_clamp(self):
        p = spec(); op = compute_design(p)['op']
        for gm in (-1.,True,'bad',math.inf,math.nan,.001):
            with self.subTest(gfs=gm), self.assertRaises(ValueError):
                operating_gate(op,dict(p,gfs=gm))
        self.assertEqual(operating_gate(op,dict(p,Vgp_off='unused'))['mode'],'current')
        with self.assertRaises(ValueError):
            operating_gate(op,dict(p,gfs=0.,Vgp_off='bad'))

    def test_api_contains_same_effective_values_and_losses(self):
        p = spec(); r = calculate_input_operating_point(p)['res']; out = run_design(p)
        self.assertEqual(out['mosfet']['gate'],r['semi']['switch']['gate'])
        self.assertEqual(out['mosfet']['P_sw_on'],r['semi']['switch']['P_sw_on'])

    def test_coupled_and_forward_use_primary_switch_not_output_currents(self):
        coupled = load_spec(json.loads((ROOT/'examples/3_OUTPUT_COUPLED_FLYBACK.json').read_text(encoding='utf-8')))
        forward = dict(spec(),topology='ACF-FORWARD')
        for p in (dict(coupled,gfs=5.),forward):
            r = compute_design(p); gate = r['semi']['switch']['gate']; op = r['op']
            self.assertAlmostEqual(gate['Vgp_on'],p['Vth']+max(op.get('I_sw_on',op['I_L_min']),0.)/5)
            self.assertAlmostEqual(gate['Vgp_off'],p['Vth']+abs(op.get('I_sw_off',op['I_L_pk']))/5)


class MillerUIChecks(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        import main
        cls.root = tk.Tk(); cls.root.withdraw()
        cls.app = main.PowerSupplyAnalyzer(cls.root)
        cls.base = copy.deepcopy(cls.app._config_dict())

    @classmethod
    def tearDownClass(cls):
        cls.app._closing=True
        cls.app._calculation_worker.close()
        for job in cls.root.tk.call('after','info'):
            cls.root.after_cancel(job)
        cls.root.destroy()

    def setUp(self):
        self.app._apply_config(copy.deepcopy(self.base))

    def test_gfs_input_changes_readout_and_hides_unused_fixed_off(self):
        a = self.app; a.set_param('gfs',5.); self.assertTrue(a.update_all())
        self.assertIn('电流相关',a.mos_gate_readout.get())
        self.assertIn('Vgp,on=',a.mos_gate_readout.get())
        a._folded_sections.clear(); a._filter_params()
        self.assertFalse(a._param_widgets['Vgp_off'][0].grid_info())
        a.params['Vgp_off'].set('unused draft')
        self.assertTrue(a.update_all())
        config = a._config_dict()
        self.assertEqual(config['gfs']['v'],5.)
        a.schedule_update()
        self.assertIn('待计算',a.mos_gate_readout.get())

    def test_switch_input_endpoint_and_legacy_load(self):
        a = self.app; a.set_param('gfs',5.)
        a.set_param('V_in_min',20.); a.set_param('V_in_max',40.)
        a.params['input_voltage_case'].set('min'); self.assertTrue(a.update_all())
        lo = a._last['res']['semi']['switch']['gate']
        a.params['input_voltage_case'].set('max'); self.assertTrue(a.update_all())
        hi = a._last['res']['semi']['switch']['gate']
        self.assertNotEqual(lo['Vgp_on'],hi['Vgp_on'])
        old = copy.deepcopy(self.base); old.pop('gfs',None)
        a._apply_config(old); self.assertEqual(a.get_params()['gfs'],0.)
        self.assertTrue(a.update_all()); self.assertIn('手动四事件',a.mos_gate_readout.get())

    def test_invalid_loaded_gfs_does_not_keep_previous_valid_value(self):
        for value in (True,-1.,float('nan'),{'v':'bad','u':''}):
            with self.subTest(value=value), self.assertRaises(ValueError):
                self.app._apply_config(dict(self.base,gfs=value))


if __name__=='__main__':unittest.main(verbosity=2)
