"""Shared-period QR reduction, independent RC referral and arbitrary feedback."""
import copy
import json
import math
from pathlib import Path
import sys
import unittest

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from design_engine.specification import load_spec
from loss_model import compute_design
from plants import build_loop_models
from qr_loop import linearize, plant


def fixture(feedback=1):
    p = load_spec(json.loads((ROOT/'examples/90W_QR_L6565_300V_TUNED.json').read_text('utf-8')))
    p.update(V_in=300., V_in_min=300., V_in_max=300., Np=60, Ns=30,
             L=800e-6, feedback_output=feedback, coupling_config={'enabled':False})
    p['outputs'] = [dict(name='Main', V_out=60., P_out=92., Ns=30,
                        d_out_enable=True, Vf_dout=.7, C_out=440e-6, Rc=.015),
                    dict(name='Aux', V_out=12.92666666666667, P_out=.1, Ns=7,
                        d_out_enable=True, Vf_dout=.7, C_out=330e-6, Rc=.025)]
    return p


class MultiQRModelChecks(unittest.TestCase):
    def test_one_total_power_cycle_and_turns_derived_nonfeedback_voltage(self):
        from isolated_outputs import selected_params
        from power_stage import compute_operating_point
        p=fixture(); original=copy.deepcopy(p)
        result=compute_design(p);op=result['op']
        aggregate=selected_params(p)
        aggregate.update(outputs=[],feedback_output=1)
        expected=compute_operating_point(aggregate)
        self.assertEqual(p,original)
        self.assertAlmostEqual(op['Ts'],expected['Ts'],places=15)
        self.assertAlmostEqual(op['I_sw_pk'],expected['I_sw_pk'],places=12)
        self.assertEqual(op['P_out'],92.1)
        self.assertFalse(op['qr_multi_model']['independent_cross_regulation'])
        self.assertTrue(all(c['Ts']==op['Ts'] for c in op['output_ops']))
        changed=copy.deepcopy(p);changed['outputs'][1]['V_out']=1234.
        stale=compute_design(changed)['op']
        self.assertEqual(op['outputs'][1]['V_out'],stale['outputs'][1]['V_out'])

    def test_factory_keeps_variable_period_and_all_rc_branches(self):
        p=fixture(); op=compute_design(p)['op']; models,description=build_loop_models(p,op)
        x=description.qr_linearization;multi=x['multi_output']
        self.assertEqual(multi['voltage_ratios'],[1.,7/30])
        self.assertEqual(models[0]._loop_metadata['kind'],'qr-ideal-ratio-aggregate')
        self.assertIn('共用',description.model_note)
        self.assertEqual(len(x['capacitors']),4)
        # Independently refer each real series-RC admittance, not a single
        # total-C/average-ESR fit. Diode DC offsets do not change turns ratios.
        for f in (1.,100.,1000.,15000.):
            s=2j*math.pi*f
            admittance=0j
            from output_capacitors import branches
            for rail,ratio in zip(op['outputs'],[1.,7/30]):
                for capacitance,esr in branches(rail):
                    admittance+=ratio**2*s*capacitance/(1+s*esr*capacitance)
            g=sum(r*r*c['I_out']/c['V_out'] for r,c in zip([1.,7/30],op['output_ops']))
            expected=x['d_iout_d_ipk']/x['sense_gain']/(g-x['d_iout_d_vcap']+admittance)
            np.testing.assert_allclose(complex(models[0](s)),expected,rtol=2e-10)

    def test_feedback_second_winding_has_its_own_actual_ratio(self):
        p=fixture(2); op=compute_design(p)['op'];_,description=build_loop_models(p,op)
        x=description.qr_linearization
        self.assertEqual(x['multi_output']['feedback_output'],2)
        self.assertEqual(x['multi_output']['voltage_ratios'],[30/7,1.])
        self.assertAlmostEqual(x['vout'],op['output_ops'][1]['V_out'])
        self.assertAlmostEqual(x['vreflected'],op['V_r'])
        self.assertAlmostEqual(x['multi_output']['equivalent_current'],
            30/7*op['output_ops'][0]['I_out']+op['output_ops'][1]['I_out'])

    def test_measured_multi_cycle_derivatives_match_independent_charge(self):
        p=fixture(2);op=compute_design(p)['op'];children=op['output_ops']
        m=dict(vout=children[1]['V_out'],vcap=children[1]['V_out_cap'],
            iout=children[1]['I_out'],vin_bus=300.,ipk=op['I_sw_pk'],period=op['Ts']*1.2,
            rail_currents=[c['I_out'] for c in children],
            rail_voltages=[c['V_out'] for c in children],
            rail_cap_voltages=[c['V_out_cap'] for c in children])
        x=linearize(p,op,measured=m)
        self.assertTrue(x['multi_output']['measured_rails_complete'])
        L,N=p['L'],60/7;scale=x['current_scale'];dead=x['dead_time']
        vf=op['outputs'][1]['Vf_diode']
        def average(i,v):
            vr=N*(v+vf);period=L*i*(1/x['vin_bus']+1/vr)+dead
            return scale*N*L*i*i/(2*vr*period)
        step=1e-5
        derivative_i=(average(x['ipk']+step,x['vcap'])-average(x['ipk']-step,x['vcap']))/(2*step)
        derivative_v=(average(x['ipk'],x['vcap']+step)-average(x['ipk'],x['vcap']-step))/(2*step)
        self.assertAlmostEqual(derivative_i,x['d_iout_d_ipk'],places=7)
        self.assertAlmostEqual(derivative_v,x['d_iout_d_vcap'],places=7)
        g,detail=plant(p,op,measured=m)
        self.assertTrue(np.isfinite(g(2j*math.pi*100)))

    def test_more_auxiliary_power_changes_primary_cycle(self):
        p=fixture(); first=compute_design(p)['op']
        p['outputs'][1]['P_out']=5.;second=compute_design(p)['op']
        self.assertGreater(second['I_sw_pk'],first['I_sw_pk'])
        self.assertGreater(second['Ts'],first['Ts'])

    def test_explicit_banks_keep_all_capacitors_and_reject_incomplete_measurements(self):
        p=fixture()
        p['outputs'][1]['output_capacitors']=[dict(C=cap,ESR=esr,ESL=0.)
            for cap,esr in ((300e-6,.02),(10e-6,0.),(1e-6,.01))]
        op=compute_design(p)['op'];x=linearize(p,op)
        self.assertEqual(len(x['capacitors']),5)
        for original,transformed in zip(((300e-6,.02),(10e-6,0.),(1e-6,.01)),x['capacitors'][2:]):
            self.assertAlmostEqual(original[0]*original[1],transformed[0]*transformed[1],places=15)
        with self.assertRaisesRegex(ValueError,'逐路对应'):
            linearize(p,op,measured={'rail_currents':[1.]})

    def test_six_outputs_with_third_feedback_keep_independent_esr_time_constants(self):
        from output_capacitors import branches
        p=fixture();p['feedback_output']=3
        p['outputs']=[dict(V_out=v,P_out=w,Ns=ns,C_out=(j+1)*40e-6,
            Rc=(j+1)*.005,C_out2=(j+1)*.8e-6,Rc2=(j+1)*.0005,cout2_enable=True)
            for j,(v,w,ns) in enumerate(zip([60,24,12,5,3.3,15],
                [92,2,1,.2,.1,1],[30,12,6,3,2,8]))]
        op=compute_design(p)['op'];models,description=build_loop_models(p,op)
        x=description.qr_linearization
        self.assertEqual(len(x['capacitors']),12)
        self.assertEqual(x['multi_output']['feedback_output'],3)
        for f in (1,100,1000,15000):
            s=2j*math.pi*f
            admittance=sum(r*r*s*c/(1+s*esr*c)
                for rail,r in zip(op['outputs'],x['multi_output']['voltage_ratios'])
                for c,esr in branches(rail))
            expected=x['d_iout_d_ipk']/x['sense_gain']/(x['output_conductance']+admittance)
            np.testing.assert_allclose(complex(models[0](s)),expected,rtol=1e-9)


if __name__=='__main__':
    unittest.main(verbosity=2)
