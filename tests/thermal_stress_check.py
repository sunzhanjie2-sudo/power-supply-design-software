"""Thermal input, clamp ceiling, waveform scope and report regressions."""
import copy
import json
from pathlib import Path
import sys
import unittest

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from runtime_resources import configure_numeric_threads
configure_numeric_threads()
import numpy as np
from design_api import load_spec, run_design
from power_stage import DEFAULT_PARAMS, compute_operating_point
from loss_model import compute_design
from semiconductor import device_stress
from parameter_layout import applicable
from magnetics import transformer_temperature


def spec(name='40W_CCM_FLYBACK.json', **changes):
    return load_spec(dict(json.loads((ROOT/'examples'/name).read_text(encoding='utf-8')), **changes))


class ThermalStressChecks(unittest.TestCase):
    def test_transformer_rise_uses_user_resistance_not_convection(self):
        p=spec(Rth_transformer=23.)
        before=copy.deepcopy(p)
        a=compute_design(p)
        b=compute_design(dict(p,Rth_transformer=46.,h_conv=1000.))
        xa,xb=a['mag']['transformer'],b['mag']['transformer']
        self.assertAlmostEqual(xa['dT'],xa['P_total']*23.)
        self.assertAlmostEqual(xb['dT'],2*xa['dT'])
        self.assertEqual(xa['P_total'],xb['P_total'])
        self.assertEqual(a['eta'],b['eta'])
        self.assertEqual(p,before)
        self.assertNotIn('h_conv',xa)

    def test_multi_and_psr_sum_all_windings_before_temperature(self):
        for name in ('6_OUTPUT_FLYBACK_SSR.json','MP6005_PSR_FLYBACK.json'):
            with self.subTest(name=name):
                r=compute_design(spec(name,Rth_transformer=17.))
                t=r['mag']['transformer']
                self.assertAlmostEqual(t['dT'],17*(t['P_cu']+t['P_core']))
                self.assertGreater(len(t['windings']),1)
                if r.get('psr'):
                    self.assertGreater(t['auxiliary']['P_cu'],0)

    def test_forward_keeps_inductor_thermal_model_separate(self):
        p=spec('40W_ACF_FORWARD.json',Rth_transformer=20.)
        a=compute_design(p);b=compute_design(dict(p,Rth_transformer=40.))
        self.assertEqual(a['mag']['inductor']['dT'],b['mag']['inductor']['dT'])
        self.assertAlmostEqual(b['mag']['transformer']['dT'],2*a['mag']['transformer']['dT'])

    def test_resistance_validation_and_old_config_default(self):
        self.assertEqual(spec()['Rth_transformer'],100.)
        for resistance in (0.,-1.,float('inf'),float('nan')):
            with self.assertRaises(ValueError):transformer_temperature(1.,{'Rth_transformer':resistance})

    def test_flyback_clamp_not_affected_by_old_ring_margin(self):
        for topology in ('FLYBACK','QR-FLYBACK'):
            p=spec(topology=topology,Kc=1.5,K=1.)
            a=compute_design(dict(p,ring_margin=0.))
            b=compute_design(dict(p,ring_margin=4.))
            op=a['op'];c=op['clamp']
            self.assertAlmostEqual(op['V_sw_max'],op['V_in']+p['Kc']*op['V_r'])
            self.assertEqual(op['V_sw_max'],b['op']['V_sw_max'])
            self.assertEqual(c['V_peak'],c['V_plateau'])
            self.assertLess(c['V_peak'],op['V_sw_max'])
            np.testing.assert_array_equal(a['wf']['v_sw'],b['wf']['v_sw'])
            self.assertEqual(a['eta'],b['eta'])

    def test_diode_stress_matches_waveform_and_has_scope_warning(self):
        for topology in ('BUCK','BOOST','BUCK-BOOST','FLYBACK','QR-FLYBACK','ACF-FORWARD'):
            p=spec(topology=topology,V_in=30.,V_out=60. if topology=='BOOST' else 15. if topology=='BUCK' else 30.)
            a=compute_design(dict(p,ring_margin=0.))
            b=compute_design(dict(p,ring_margin=2.))
            da,db=device_stress(a['op']),device_stress(b['op'])
            self.assertEqual(da['diode']['V_max'],db['diode']['V_max'],topology)
            self.assertAlmostEqual(float(np.max(a['wf']['v_d'])),da['diode']['V_max'])
            for key in ('diode','freewheel'):
                if key in da:
                    self.assertIn('未考虑寄生尖峰',da[key]['note'])
                    self.assertFalse(da[key]['includes_parasitic_spikes'])

    def test_hidden_parameters_are_topology_specific(self):
        for topology in ('FLYBACK','QR-FLYBACK'):
            self.assertFalse(applicable('ring_margin',topology,'Voltage Mode'))
            self.assertFalse(applicable('h_conv',topology,'Voltage Mode'))
            self.assertTrue(applicable('Rth_transformer',topology,'Voltage Mode'))
        self.assertFalse(applicable('Rth_transformer','BUCK','Voltage Mode'))
        self.assertTrue(applicable('h_conv','ACF-FORWARD','Voltage Mode'))

    def test_api_exposes_resistance_and_scope(self):
        r=run_design(spec(Rth_transformer=12.))
        self.assertTrue(r['ok'])
        self.assertEqual(r['magnetics']['Rth_transformer'],12.)
        self.assertIn('未考虑寄生尖峰',r['stress']['diode']['note'])

    def test_coupled_solver_clamp_and_all_winding_temperature(self):
        p=spec('3_OUTPUT_COUPLED_FLYBACK.json',Rth_transformer=18.)
        r=compute_design(p);op=r['op'];t=r['mag']['transformer']
        self.assertAlmostEqual(op['clamp']['V_ceiling'],op['V_in']+p['Kc']*op['V_r'])
        self.assertGreaterEqual(op['V_sw_max'],op['clamp']['V_peak'])
        self.assertAlmostEqual(t['dT'],18.*t['P_total'])

    def test_material_coefficients_still_drive_core_loss(self):
        p=spec()
        original=compute_design(p)['mag']['transformer']['P_core']
        doubled=compute_design(dict(p,k_core=2*p['k_core']))['mag']['transformer']['P_core']
        self.assertAlmostEqual(doubled,2*original)
        for name in ('a_core','b_core'):
            changed=compute_design(dict(p,**{name:p[name]+.1}))['mag']['transformer']['P_core']
            self.assertNotAlmostEqual(changed,original)


if __name__=='__main__':unittest.main(verbosity=2)
