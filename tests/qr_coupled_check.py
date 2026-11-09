"""Independent QR matrix charge, energy and timing constraints (no SPICE)."""
import copy
import json
import math
from pathlib import Path
import sys
import unittest

import numpy as np

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from runtime_resources import configure_numeric_threads
configure_numeric_threads()
from design_engine.specification import load_spec
from power_stage import compute_operating_point
from winding_coupling import default_coupling_config


def fixture(count=2,feedback=1):
    p=load_spec(json.loads((ROOT/'examples/90W_QR_L6565_300V.json').read_text('utf-8-sig')))
    p.update(V_in=300.,V_in_min=300.,V_in_max=300.,L=800e-6,Np=60,Ns=30,
        MLT=.068,Rds_on=.1,Rs=.33,Coss=99e-12,f_sw=100000.,
        feedback_output=feedback,d_in_enable=False)
    turns=(30,8,3,5,12,15);volts=(60,15,5,9,24,30);powers=(60,1,.1,.3,2,2)
    p['outputs']=[dict(name=f'OUT{j+1}',Ns=turns[j],V_out=volts[j],P_out=powers[j],
        P_out_min=.01,Vf_diode=.7,d_out_enable=True,Vf_dout=.7,
        d_wire_s=.1e-3,n_strand_s=50,C_out=330e-6,Rc=.025) for j in range(count)]
    p['coupling_config']=default_coupling_config(count)
    p['coupling_config']['enabled']=True
    return p


class QRCoupledChecks(unittest.TestCase):
    def test_charge_energy_and_samples_independently(self):
        p=fixture();original=copy.deepcopy(p);op=compute_operating_point(p)
        m=op['qr_coupled_model'];s=op['coupled_solution'];T=op['Ts']
        self.assertEqual(p,original)
        self.assertTrue(m['converged']);self.assertLess(m['normalized_residual'],2e-5)
        self.assertLess(abs(m['energy_balance_W']),1e-5)
        # Independent sampled integration, not a second read of solver residual.
        current=s['i_winding'];time=s['t']
        for i,row in enumerate(op['output_ops'],1):
            self.assertAlmostEqual(np.trapezoid(current[i],time)/T,row['I_out'],delta=row['I_out']*.001)
            self.assertAlmostEqual(np.trapezoid(current[i]**2,time)/T,row['I_d_rms']**2,delta=max(row['I_d_rms']**2*.002,1e-9))
        self.assertLess(float(np.max(np.abs(current[:,0]))),1e-8)
        self.assertLess(float(np.max(np.abs(current[:,-1]))),1e-8)
        self.assertLess(m['blocked_diode_violation_V'],1e-5)
        self.assertAlmostEqual(m['P_in'],m['P_out']+sum(m['P_dcr'])+sum(m['P_rectifier'])+
            sum(m['P_output_blocking'])+m['P_input_blocking']+m['P_mos_conduction']+m['P_sense']+m['P_clamp'],places=5)

    def test_variable_period_and_frequency_limit_is_only_a_check(self):
        p=fixture();full=compute_operating_point(p)
        q=copy.deepcopy(p);q['outputs'][0]['P_out']=3;q['outputs'][1]['P_out']=.1
        light=compute_operating_point(q)
        self.assertNotAlmostEqual(full['f_sw'],light['f_sw'],delta=1.)
        low=compute_operating_point(dict(p,f_sw=10000.))
        self.assertTrue(low['qr_coupled_model']['design_frequency_limit_exceeded'])
        self.assertAlmostEqual(low['f_sw'],full['f_sw'],delta=1e-3)
        self.assertAlmostEqual(low['Ts'],low['T_on']+low['T_demag']+low['T_ring'],places=14)

    def test_pairwise_coupling_and_load_change_the_aux_voltage(self):
        p=fixture();a=compute_operating_point(p)
        q=copy.deepcopy(p);q['outputs'][1]['P_out']=.2;b=compute_operating_point(q)
        self.assertGreater(abs(a['output_ops'][1]['V_out']-b['output_ops'][1]['V_out']),.05)
        q=copy.deepcopy(p);q['coupling_config']['k'][1][2]=q['coupling_config']['k'][2][1]=.993
        c=compute_operating_point(q)
        self.assertGreater(abs(a['output_ops'][1]['V_out']-c['output_ops'][1]['V_out']),.005)
        self.assertAlmostEqual(a['V_feedback'],a['V_feedback_target'],places=11)

    def test_valley_blanking_selects_the_first_allowed_valley(self):
        p=fixture();p['outputs'][0]['P_out']=3.;p['outputs'][1]['P_out']=.1
        op=compute_operating_point(p);m=op['qr_coupled_model']
        n=m['valley_index'];ring=m['first_valley_delay_s'];off=m['T_demag']+m['T_ring']
        self.assertGreater(n,1)
        self.assertGreaterEqual(off+1e-12,m['off_blanking_s'])
        self.assertLess(off-2*ring,m['off_blanking_s']+1e-12)

    def test_non_self_consistent_valley_branch_does_not_publish_a_fake_period(self):
        p=fixture();p['outputs'][0]['P_out']=30
        with self.assertRaisesRegex(ValueError,'单周期|谷底'):
            compute_operating_point(p)

    def test_six_outputs_arbitrary_feedback_and_unequal_local_pulses(self):
        p=fixture(6,3);op=compute_operating_point(p)
        self.assertEqual(op['feedback_output'],3)
        self.assertEqual(len(op['output_ops']),6)
        self.assertEqual(len(op['coupled_solution']['i_winding']),7)
        self.assertAlmostEqual(op['output_ops'][2]['V_out'],5.,places=10)
        self.assertTrue(all(row['V_out']>0 for row in op['output_ops']))
        self.assertLess(op['qr_coupled_model']['normalized_residual'],2e-5)

    def test_effective_capacitance_and_cancellation_and_cache_isolation(self):
        import calculation_scheduler as cs
        from unittest.mock import patch
        p=fixture();a=compute_operating_point(p)
        a['coupled_solution']['i_winding'][0,0]=999.
        b=compute_operating_point(p)
        self.assertEqual(b['coupled_solution']['i_winding'][0,0],0.)
        q=copy.deepcopy(p);q['spice_config']['qr_cds_pf']=198.
        c=compute_operating_point(q)
        self.assertAlmostEqual(c['qr_coupled_model']['first_valley_delay_s']/
            b['qr_coupled_model']['first_valley_delay_s'],math.sqrt(2),places=10)
        with patch.object(cs,'check_calculation_cancelled',side_effect=cs.CalculationCancelled):
            with self.assertRaises(cs.CalculationCancelled):compute_operating_point(p)

    def test_zero_load_current_clamp_and_ideal_limit_are_explicit(self):
        p=fixture();p['outputs'][1]['P_out']=0
        with self.assertRaisesRegex(ValueError,'P_out|空载'):compute_operating_point(p)
        p=fixture();p['spice_config']['qr_cs_clamp_v']=.05
        with self.assertRaisesRegex(ValueError,'CS'):compute_operating_point(p)
        p=fixture();p['coupling_config']['k']=[[1.]*3 for _ in range(3)]
        op=compute_operating_point(p)
        self.assertTrue(op['qr_coupled_model']['ideal_fallback'])
        self.assertNotIn('coupled_solution',op)

    def test_fixed_rcd_power_balance_light_load_and_resistance_cache(self):
        from analysis_workflows import pin_hardware
        from loss_model import compute_design
        p=fixture();res=compute_design(p);fixed=pin_hardware(p,res)
        hardware=copy.deepcopy(fixed['_qr_rcd_hardware'])
        full=compute_operating_point(fixed)
        light=copy.deepcopy(fixed);light['outputs'][0]['P_out']=45.
        lower=compute_operating_point(light)
        for op in (full,lower):
            model=op['qr_coupled_model'];vc=model['clamp_voltage']
            self.assertEqual(model['rcd_hardware']['R_ohm'],hardware['R_ohm'])
            self.assertEqual(model['rcd_hardware']['C_F'],hardware['C_F'])
            self.assertAlmostEqual(model['P_clamp'],vc**2/hardware['R_ohm'],places=8)
            self.assertLess(abs(model['rcd_power_balance_W']),1e-7)
            self.assertGreater(model['rcd_ripple_upper_V'],0.)
            self.assertAlmostEqual(model['rcd_ripple_upper_V'],model['P_clamp']*op['Ts']/vc/hardware['C_F'],places=8)
            self.assertIn('RC瞬态',op['warnings'][-1])
        self.assertLess(lower['qr_coupled_model']['clamp_voltage'],full['qr_coupled_model']['clamp_voltage']-10.)
        changed=copy.deepcopy(fixed);changed['_qr_rcd_hardware']['R_ohm']*=.8
        different=compute_operating_point(changed)
        self.assertLess(different['qr_coupled_model']['clamp_voltage'],full['qr_coupled_model']['clamp_voltage']-10.)
        np.testing.assert_allclose(compute_operating_point(fixed)['coupled_solution']['i_winding'],full['coupled_solution']['i_winding'])

    def test_invalid_or_zero_power_rcd_cannot_be_frozen(self):
        from analysis_workflows import pin_hardware
        from loss_model import compute_design
        p=fixture();r=compute_design(p)
        no_power=copy.deepcopy(r);no_power['op']['clamp']['P_res']=0.
        with self.assertRaisesRegex(ValueError,'R/C|功率'):pin_hardware(p,no_power)
        for key,value in (('R_ohm',0.),('R_ohm',float('inf')),('R_ohm',True),('C_F',0.)):
            q=copy.deepcopy(p);q['_qr_rcd_hardware']=dict(R_ohm=100000.,C_F=1e-9)
            q['_qr_rcd_hardware'][key]=value
            with self.subTest(key=key,value=value),self.assertRaisesRegex(ValueError,'RCD'):
                compute_operating_point(q)


if __name__=='__main__':unittest.main(verbosity=2)
