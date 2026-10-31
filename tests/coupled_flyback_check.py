"""Conservation and mixed-conduction checks for the optional winding solver."""
import copy
import json
from pathlib import Path
import sys
import unittest

import numpy as np

sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from power_stage import DEFAULT_PARAMS,compute_operating_point
from coupled_flyback import solve_coupled_flyback


def parameters(outputs=None):
    p=copy.deepcopy(DEFAULT_PARAMS)
    p.update(topology='FLYBACK',feedback_mode='SSR',feedback_output=1,Kc=1.5,
             outputs=outputs or [],coupling_config=dict(enabled=True,k=[],dcr=[]))
    return p


def solve(p):
    nominal=compute_operating_point(dict(p,coupling_config=dict(enabled=False)))
    return solve_coupled_flyback(p,nominal)


class CoupledFlybackChecks(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.single_params=parameters()
        cls.single=solve(cls.single_params)
        cls.multi_params=parameters([dict(V_out=30,P_out=30,Ns=0),
                                    dict(V_out=12,P_out=.5,Ns=0),
                                    dict(V_out=5,P_out=1,Ns=0)])
        cls.multi=solve(cls.multi_params)

    def test_exact_energy_and_charge_balance(self):
        for op in (self.single,self.multi):
            meta=op['coupled_model']
            self.assertTrue(meta['converged'])
            self.assertLess(meta['energy_balance_relative'],1e-5)
            self.assertLess(meta['normalized_residual'],2e-5)
            self.assertLess(max(abs(v) for v in meta['charge_balance_A']),1e-6)
            losses=(sum(meta['P_dcr'])+sum(meta['P_rectifier'])+
                    meta['P_mos_conduction']+meta['P_sense']+meta['P_rcd']+
                    meta['P_input_blocking']+sum(meta['P_output_blocking']))
            self.assertAlmostEqual(meta['P_in'],meta['P_out']+losses,delta=1e-4)

    def test_true_branch_pulse_not_power_proportion(self):
        op=self.multi
        self.assertEqual(op['mode'],'CCM')
        self.assertEqual(op['output_ops'][0]['branch_mode'],'CCM')
        self.assertEqual(op['output_ops'][1]['branch_mode'],'DCM')
        self.assertEqual(op['output_ops'][2]['branch_mode'],'DCM')
        currents=op['coupled_solution']['i_winding'][1:]
        self.assertGreater(np.min(currents),-1e-6)
        # Lightly loaded OUT2 has much higher pulse/average ratio; it is not
        # a scaled version of OUT1's transfer interval waveform.
        main,light=op['output_ops'][:2]
        self.assertGreater(light['I_d_pk']/light['I_d_avg'],
                           5*main['I_d_pk']/main['I_d_avg'])
        self.assertNotAlmostEqual(light['V_out'],12.,places=2)

    def test_clamp_is_finite_and_connected_back_to_input(self):
        op=self.multi; wf=op['coupled_solution']; meta=op['coupled_model']
        self.assertGreater(meta['clamp_duty'],0)
        self.assertLess(meta['clamp_duty'],1-op['D'])
        self.assertGreater(meta['P_rcd'],0)
        self.assertAlmostEqual(max(wf['v_sw']),op['V_in_bus']+meta['clamp_voltage'],places=7)
        # Net source current excludes OFF recirculation back to Vin.
        np.testing.assert_allclose(wf['i_in'],wf['i_sw'])
        self.assertTrue(np.any(wf['i_winding'][0,~wf['gate_on']]>0))
        self.assertTrue(np.all(wf['i_sw'][~wf['gate_on']]==0))
        self.assertGreater(op['I_sw_on'],0.)
        self.assertTrue(np.all(np.diff(wf['t'])>0))
        self.assertAlmostEqual(wf['t'][-1],1/op['f_sw'])

    def test_rms_and_current_integrals_match_waveform(self):
        op=self.multi; wf=op['coupled_solution']; t=wf['t']; period=t[-1]
        measured=np.sqrt(np.trapezoid(wf['i_winding']**2,t,axis=1)/period)
        np.testing.assert_allclose(measured,op['coupled_model']['winding_rms'],rtol=7e-4,atol=1e-5)
        for j,child in enumerate(op['output_ops']):
            average=np.trapezoid(wf['i_winding'][j+1],t)/period
            self.assertAlmostEqual(average,child['I_out'],delta=.001)

    def test_pairwise_secondary_coupling_changes_solution(self):
        p=copy.deepcopy(self.multi_params)
        p['coupling_config']['k']=[[1,.995,.995,.995],
                                  [.995,1,.99,.995],
                                  [.995,.99,1,.995],
                                  [.995,.995,.995,1]]
        altered=solve(p)
        self.assertGreater(abs(altered['output_ops'][1]['I_d_pk']-
                               self.multi['output_ops'][1]['I_d_pk']),.01)
        self.assertLess(altered['coupled_model']['energy_balance_relative'],1e-5)

    def test_actual_turns_are_used_and_input_is_unchanged(self):
        p=parameters([dict(V_out=30,P_out=30,Ns=12),dict(V_out=12,P_out=.5,Ns=4)])
        p['Np']=6
        before=copy.deepcopy(p)
        result=solve(p)
        self.assertEqual(p,before)
        self.assertEqual(result['coupled_model']['ratios'],[1.,.5,1.5])
        self.assertLess(result['output_ops'][1]['V_out'],11.)
        json.dumps(result['coupled_model'])  # diagnostics are report/config safe

    def test_ideal_limit_is_explicit_not_regularized(self):
        p=copy.deepcopy(self.multi_params)
        p['coupling_config']['k']=[[1.]*4 for _ in range(4)]
        result=solve(p)
        self.assertTrue(result['coupled_model']['ideal_fallback'])
        self.assertNotIn('coupled_solution',result)
        self.assertNotIn('converged',result['coupled_model'])
        self.assertEqual(result['clamp']['L_leak'],0)
        self.assertEqual(result['clamp']['P_res'],0)
        for child in result['output_ops']+[result['aggregate_op']]:
            self.assertEqual(child['clamp']['L_leak'],0)
            self.assertEqual(child['clamp']['V_peak'],child['clamp']['V_plateau'])
        p['outputs'][1]['Ns']=4
        changed = solve(p)
        # Unregulated voltages now follow actual turns, rather than being
        # independent targets that can contradict an ideal transformer.
        self.assertTrue(changed['coupled_model']['ideal_fallback'])
        self.assertAlmostEqual(changed['output_ops'][1]['V_out'], (30+1.4)/3-1.4)
        self.assertEqual(changed['coupled_model']['ratios'][2], 1.5)
        self.assertEqual(changed['clamp']['L_leak'], 0.)

    def test_infeasible_and_unsupported_models_rejected(self):
        for topo,feedback in (('QR-FLYBACK','SSR'),('FLYBACK','PSR-MP6005')):
            p=parameters(); p.update(topology=topo,feedback_mode=feedback)
            with self.assertRaisesRegex(ValueError,'FLYBACK'):
                solve_coupled_flyback(p,self.single)
        p=parameters([dict(V_out=30,P_out=40),dict(V_out=12,P_out=0)])
        with self.assertRaisesRegex(ValueError,'P_out'):
            solve(p)
        p=parameters(); p['Kc']=1
        with self.assertRaisesRegex(ValueError,'Kc'):
            solve(p)
        p=parameters(); p['coupling_config']['k']=[[1,0],[0,1]]
        with self.assertRaisesRegex(ValueError,'解耦'):
            solve(p)

    def test_six_windings_outputs_and_selected_feedback(self):
        for count in (4,5,6):
            p=parameters([dict(V_out=v,P_out=w,Ns=0) for v,w in
                          zip((30,12,5,3.3,24,15),(20,8,4,2,4,2))][:count])
            result=solve(p)
            self.assertEqual(len(result['output_ops']),count)
            self.assertEqual(result['coupled_solution']['i_winding'].shape[0],count+1)
            self.assertLess(result['coupled_model']['energy_balance_relative'],1e-7)
            self.assertLess(result['coupled_model']['blocked_diode_violation_V'],1e-4)
        p=copy.deepcopy(self.multi_params); p['feedback_output']=2
        result=solve(p)
        self.assertAlmostEqual(result['output_ops'][1]['V_out'],12.)
        self.assertLess(result['coupled_model']['normalized_residual'],2e-5)


if __name__=='__main__':
    unittest.main(verbosity=2)
