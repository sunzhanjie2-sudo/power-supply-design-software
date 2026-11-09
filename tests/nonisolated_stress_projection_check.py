"""Independent physical-envelope and legacy-allowance stress regressions."""
import copy
import json
from pathlib import Path
import sys
import unittest
import numpy as np

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from runtime_resources import configure_numeric_threads
configure_numeric_threads()
from component_management import evaluate_components
from design_engine.specification import load_spec
from loss_model import compute_design
from power_stage import DEFAULT_PARAMS
from semiconductor import device_stress


def profile(name, vin):
    p=load_spec(json.loads((ROOT/'examples'/name).read_text('utf8')))
    p.update(V_in=vin,d_in_enable=False,d_out_enable=False)
    return p


class NonisolatedStressChecks(unittest.TestCase):
    def test_buck_periodic_plateau_is_bus_plus_freewheel_drop(self):
        for name in ('24W_BUCK_VM_TPS40200.json','24W_BUCK_PCM_LTC3864.json'):
            with self.subTest(name=name):
                p=profile(name,30.);res=compute_design(p);op=res['op']
                s=device_stress(op)['switch']
                self.assertIn('niso_model',op)
                self.assertAlmostEqual(s['V_block'],30.+p['Vf_diode'])
                self.assertEqual(s['V_block'],op['V_sw_max'])
                self.assertEqual(s['V_max'],op['V_sw_max'])
                check=next(x for x in evaluate_components(p,res)['checks'] if x['id']=='bom_Q1_voltage')
                self.assertEqual(check['value'],s['V_block'])
                self.assertIn('不再除',check['note'])

    def test_boost_periodic_envelope_keeps_output_ripple_and_diode_drop(self):
        for voltage in (9.,18.):
            p=profile('24W_BOOST_PCM_LM5022.json',voltage);res=compute_design(p);op=res['op']
            s=device_stress(op)['switch']
            self.assertEqual(s['V_block'],op['V_sw_max'])
            self.assertGreaterEqual(s['V_block'],p['V_out']+p['Vf_diode']-.001)
            self.assertAlmostEqual(s['V_block'],float(np.max(res['wf']['vcap']))+p['Vf_diode'],delta=.002)
            self.assertIn('实际 Vds',s['blocking_voltage_note'])

    def test_unused_legacy_allowance_cannot_scale_periodic_stress_or_loss(self):
        for name,vin in (('24W_BUCK_VM_TPS40200.json',30.),('24W_BOOST_PCM_LM5022.json',9.)):
            p=profile(name,vin)
            a=compute_design(dict(p,ring_margin=0.))
            b=compute_design(dict(p,ring_margin=4.))
            self.assertEqual(a['op']['V_sw_max'],b['op']['V_sw_max'])
            self.assertEqual(device_stress(a['op'])['switch']['V_block'],device_stress(b['op'])['switch']['V_block'])
            self.assertEqual(a['eta'],b['eta'])
            self.assertEqual(a['P_sense'],b['P_sense'])

    def test_legacy_topology_plateau_and_selection_envelope_remain_distinct(self):
        for topology,out in (('BUCK',12.),('BOOST',50.),('BUCK-BOOST',12.)):
            p=dict(copy.deepcopy(DEFAULT_PARAMS),topology=topology,V_in=30.,V_out=out,
                   P_out=12.,f_sw=100e3,L=50e-6,ring_margin=.7,spice_config={})
            op=compute_design(p)['op'];s=device_stress(op)['switch']
            expected=30. if topology=='BUCK' else op['V_out_equiv'] if topology=='BOOST' else 30.+op['V_out_equiv']
            self.assertAlmostEqual(s['V_block'],expected)
            self.assertEqual(s['V_max'],op['V_sw_max'])
            self.assertEqual(s['V_recommended'],op['V_sw_max'])
            self.assertGreater(s['V_recommended'],s['V_block'])

    def test_unknown_voltage_semantics_preserve_available_maximum(self):
        op=compute_design(profile('24W_BUCK_VM_TPS40200.json',30.))['op']
        op.pop('niso_model',None);op.pop('efficiency_model',None)
        op.update(V_sw_max=60.,ring_margin=1.)
        s=device_stress(op)['switch']
        self.assertEqual(s['V_block'],60.)
        self.assertEqual(s['V_max'],60.)
        self.assertIn('未区分',s['blocking_voltage_note'])

    def test_flyback_and_active_clamp_voltage_definitions_unchanged(self):
        for name in ('40W_CCM_FLYBACK.json','90W_QR_L6565_300V.json','40W_ACF_FORWARD.json'):
            p=load_spec(json.loads((ROOT/'examples'/name).read_text('utf8')))
            op=compute_design(p)['op'];s=device_stress(op)
            if p['topology']=='ACF-FORWARD':
                self.assertEqual(s['switch']['V_block'],op['V_clamp'])
                self.assertEqual(s['auxiliary']['V_block'],op['V_clamp'])
                self.assertEqual(s['diode']['V_block'],op['V_d_block'])
            else:
                self.assertEqual(s['switch']['V_block'],op['clamp']['V_plateau'])
                self.assertEqual(s['switch']['V_peak_physical'],op['clamp']['V_peak'])
            self.assertEqual(s['switch']['V_max'],op['V_sw_max'])


if __name__=='__main__':unittest.main(verbosity=2)
