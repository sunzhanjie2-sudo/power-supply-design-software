"""Numerical map, shared-feedback and independent DC sensitivity checks."""
import copy
import json
from pathlib import Path
import sys
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from runtime_resources import configure_numeric_threads
configure_numeric_threads()

import control as ct
import numpy as np
from scipy.optimize import brentq
from matplotlib.figure import Figure
from matplotlib.backends.backend_agg import FigureCanvasAgg
from matplotlib import rc_context

from design_api import load_spec
from loss_model import compute_design
from plants import build_loop_models, make_compensator
from loop_tuning import analyze_loop, kfactor_tune
from loop_charts import draw_multi_output_response
from analysis_workflows import pin_hardware
from coupled_integration_check import configuration
from calculation_scheduler import CalculationCancelled
from unittest.mock import patch


class MultiLoopChecks(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.p = load_spec(json.loads((ROOT/'examples/3_OUTPUT_COUPLED_FLYBACK.json').read_text(encoding='utf-8')))
        cls.result = compute_design(cls.p)
        cls.models, cls.plant = build_loop_models(cls.p, cls.result['op'])
        cls.loop = analyze_loop(cls.p, cls.models, cls.result['op'], n=1200)

    def test_each_output_and_both_capacitors_have_their_own_states(self):
        self.assertEqual(self.plant.full_system.noutputs, 3)
        self.assertEqual(self.plant.full_system.ninputs, 4)
        self.assertEqual(self.plant.discrete_A.shape, (9, 9))
        self.assertEqual(self.plant.loop_metadata['capacitor_states'],6)
        self.assertTrue(self.plant.loop_metadata['esr_included'])
        self.assertEqual(self.loop['multi_output']['load'].shape, (3, 3, 1200))
        caps = [r['C_out']+(r['C_out2'] if r['cout2_enable'] else 0) for r in self.result['op']['outputs']]
        np.testing.assert_array_equal(caps, self.plant.loop_metadata['capacitance'])
        self.assertLess(self.plant.loop_metadata['derivative_error'], .03)

    def test_current_mode_linearization_predicts_a_constrained_nonlinear_cycle(self):
        period = self.plant.period_map
        a, bd, hx, hd = period.linearize(1e-5)
        delta = np.array([1., 0., 0., .2, -.3, .1])*1e-6
        # Keep zero-current states in the physically allowed cone.
        delta[:3] = np.maximum(delta[:3], 0.)
        state = period.state+delta
        baseline, threshold, _ = period.evaluate(period.state, period.duty)
        drive = 1e-7
        duty = brentq(lambda d: period.evaluate(state, d)[1]-threshold-drive,
                      period.duty-.001, period.duty+.001, xtol=1e-13)
        actual, _, _ = period.evaluate(state, duty)
        predicted = baseline+(a-np.outer(bd, hx)/hd)@delta+bd/hd*drive
        np.testing.assert_allclose(actual, predicted, rtol=0, atol=2e-9)

    def test_voltage_mode_has_no_accidental_peak_current_feedback(self):
        p = dict(self.p, control_mode='Voltage Mode')
        models, plant = build_loop_models(p, self.result['op'])
        # Physical winding/capacitor dynamics remain; current comparator
        # gain and artificial ramp must have no effect when driving Vm*d.
        other,_=build_loop_models(dict(p,A_sense=37.,ma_slope=1e7),self.result['op'])
        for f in (1.,500.,3000.):
            np.testing.assert_allclose(models[0](2j*np.pi*f),other[0](2j*np.pi*f),rtol=1e-8)
        self.assertFalse(plant.loop_metadata['current_mode'])

    def test_frequency_domain_current_balance_matches_joint_state_space(self):
        # Independent complex KCL solve: exact parallel-RC impedance,
        # original discrete winding map, and the current threshold equation.
        period = self.plant.period_map
        a, bd, hx, hd = period.linearize(1e-5)
        n=period.count;sv=period.scale[n:]
        charge=period.capacitance*sv/period.period
        ji=charge[:,None]*a[n:,:n]
        jv=charge[:,None]*(a[n:,n:]-np.eye(n))/sv[None,:]+np.diag(1/period.load)
        jd=charge*bd[n:]
        for f in (1,30,500,3000):
            s = 2j*np.pi*f
            z = (1+s*period.period/2)/(1-s*period.period/2)
            current_v=np.linalg.solve(z*np.eye(n)-a[:n,:n],a[:n,n:]/sv[None,:])
            current_d=np.linalg.solve(z*np.eye(n)-a[:n,:n],bd[:n])
            impedance=[]
            for rail,load in zip(period.rails,period.load):
                admittance=1/load+s*rail['C_out']/(1+s*rail['Rc']*rail['C_out'])
                if rail['cout2_enable']:
                    admittance+=s*rail['C_out2']/(1+s*rail['Rc2']*rail['C_out2'])
                impedance.append(1/admittance)
            zi=np.diag(impedance)
            matrix=np.zeros((n+1,n+1),complex)
            matrix[:n,:n]=np.eye(n)-zi@(ji@current_v+jv)
            matrix[:n,n]=-zi@(ji@current_d+jd)
            matrix[n,:n]=hx[:n]@current_v+hx[n:]/sv
            matrix[n,n]=hx[:n]@current_d+hd
            rhs=np.zeros((n+1,n+1),complex);rhs[n,0]=1.;rhs[:n,1:]=-zi
            expected=np.linalg.solve(matrix,rhs)[:n]
            np.testing.assert_allclose(self.plant.full_system(s),expected,rtol=2e-8,atol=1e-8)

    def test_dc_cross_load_matches_independent_full_steady_state_solves(self):
        fixed = pin_hardware(self.p, self.result)
        # A resistor perturbation matching +dI at the original actual voltage
        # is first-order equivalent to our additive load-current disturbance.
        rail, delta_i = 1, 1e-4
        target = self.result['outputs'][rail]['spec']['V_out']
        actual = self.result['outputs'][rail]['op']['V_out']
        voltages = []
        for direction in (-1, 1):
            p = copy.deepcopy(fixed)
            p['outputs'][rail]['P_out'] += direction*delta_i*target**2/actual
            p['outputs'][rail]['P_out_min']=min(p['outputs'][rail]['P_out_min'],p['outputs'][rail]['P_out'])
            r = compute_design(p)
            voltages.append(np.array([v['op']['V_out'] for v in r['outputs']]))
        measured = (voltages[1]-voltages[0])/(2*delta_i)
        np.testing.assert_allclose(self.loop['multi_output']['dc_load'][:, rail], measured,
                                   rtol=.015, atol=.002)

    def test_provisional_bandwidth_gate_is_disabled_without_infinite_gm_claim(self):
        self.assertIsNone(self.plant.loop_metadata['frequency_limit'])
        self.assertIsNone(self.plant.loop_metadata['recommended_fc_max'])
        self.assertFalse(self.plant.loop_metadata['bandwidth_limit_enabled'])
        self.assertAlmostEqual(self.loop['f'][-1], max(self.result['op']['f_sw']*10, 1e6))
        self.assertFalse(self.loop['gm_band_limited'])
        self.assertTrue(self.loop['gm_scan_limited'])
        self.assertFalse(self.loop['gm_infinite'])
        self.assertTrue(self.loop['closed_loop_stable'])
        np.testing.assert_allclose(self.loop['multi_output']['dc_load'][0], 0., atol=1e-10)

    def test_tuned_single_loop_has_one_common_feedback_denominator(self):
        gvc = self.models[0]
        fc = 1000.
        tuned = kfactor_tune(gvc, fc, 65, 'type2')
        self.assertTrue(tuned['feasible'])
        p = dict(self.p, controller_type='type2', **{k:tuned[k] for k in ('KP','fz1','fp1')})
        gc = make_compensator(p).get_transfer_function()
        loop = analyze_loop(p, (gvc, gc, gvc*gc), self.result['op'], n=1800)
        self.assertAlmostEqual(loop['fc'], fc, delta=fc*.002)
        self.assertAlmostEqual(loop['pm'], 65., delta=.05)
        self.assertTrue(loop['closed_loop_stable'])
        np.testing.assert_allclose(loop['multi_output']['reference'][0], loop['gains'][2]/(1+loop['gains'][2]))

    def test_all_six_outputs_and_feedback_switch_are_supported(self):
        for feedback in (1, 2):
            p = configuration(count=6)
            # With deprecated diode Rd removed, avoid the genuine/numerical
            # CCM/DCM boundary of the old fixture. Keep the safety guard intact.
            p['L']*=1.25
            p['feedback_output'] = feedback
            result = compute_design(p)
            models, _ = build_loop_models(p, result['op'])
            loop = analyze_loop(p, models, result['op'], n=300)
            self.assertEqual(loop['multi_output']['reference'].shape, (6, 300))
            self.assertEqual(loop['model']['feedback_output'], feedback)
            self.assertTrue(np.all(np.isfinite(loop['multi_output']['load'])))

    def test_ideal_model_does_not_invent_cross_regulation(self):
        p = copy.deepcopy(self.p)
        p['coupling_config']['enabled'] = False
        result = compute_design(p)
        models, _ = build_loop_models(p, result['op'])
        loop = analyze_loop(p, models, result['op'], n=200)
        self.assertEqual(loop['model']['kind'], 'ideal-ratio-aggregate')
        self.assertIsNone(loop['multi_output']['load'])
        self.assertIsNone(loop['multi_output']['dc_load'])

    def test_cancellation_is_not_swallowed_by_the_numerical_model(self):
        with patch('multi_output_loop.check_calculation_cancelled', side_effect=CalculationCancelled):
            with self.assertRaises(CalculationCancelled):
                build_loop_models(self.p, self.result['op'])

    def test_api_autotune_preserves_requested_crossover_above_old_gate(self):
        from design_api import autotune_loop
        tuned=autotune_loop(self.p,fc=3200,pm=65)
        self.assertTrue(tuned['feasible'])
        self.assertTrue(tuned['spec_updates'])
        self.assertEqual(tuned['fc_target'],3200)
        self.assertIsNone(tuned['fc_recommended_max'])
        self.assertAlmostEqual(tuned['achieved']['fc'],3200,delta=10)

    def test_esr_does_not_reintroduce_the_old_bandwidth_rejection(self):
        op=copy.deepcopy(self.result['op'])
        for rail in op['outputs']:
            rail.update(Rc=1e6,Rc2=1e6)
        _,plant=build_loop_models(self.p,op)
        self.assertIsNone(plant.loop_metadata['frequency_limit'])

    def test_zero_esr_and_disabled_second_branch_have_physical_state_counts(self):
        ideal=copy.deepcopy(self.result['op'])
        for rail in ideal['outputs']:rail.update(Rc=0.,Rc2=0.)
        zero,plant=build_loop_models(self.p,ideal)
        self.assertEqual(plant.full_system.nstates,6)
        self.assertEqual(plant.loop_metadata['capacitor_states'],3)
        # DC capacitor currents are zero, so ESR changes no DC sensitivity.
        np.testing.assert_allclose(zero[0](0),self.models[0](0),rtol=2e-8)
        phase_change=np.degrees(np.angle(self.models[0](2j*np.pi*3000)/zero[0](2j*np.pi*3000)))
        self.assertGreater(phase_change,5.)
        single=copy.deepcopy(self.result['op'])
        for rail in single['outputs']:rail['cout2_enable']=False
        _,plant=build_loop_models(self.p,single)
        self.assertEqual(plant.full_system.nstates,6)

    def test_swapping_parallel_branches_preserves_the_coupled_response(self):
        op=copy.deepcopy(self.result['op'])
        for rail in op['outputs']:
            rail['C_out'],rail['C_out2']=rail['C_out2'],rail['C_out']
            rail['Rc'],rail['Rc2']=rail['Rc2'],rail['Rc']
        swapped,_=build_loop_models(self.p,op)
        for f in (0,30,500,3000):
            np.testing.assert_allclose(swapped[0](2j*np.pi*f),self.models[0](2j*np.pi*f),rtol=1e-7)

    def test_infeasible_high_frequency_tune_does_not_write_parameters(self):
        from design_api import autotune_loop
        tuned=autotune_loop(self.p,fc=10000,pm=170)
        self.assertEqual(tuned['fc_target'],10000)
        self.assertFalse(tuned['feasible'])
        self.assertEqual(tuned['spec_updates'],{})

    def test_large_capacitor_voltage_ripple_is_rejected(self):
        op=copy.deepcopy(self.result['op'])
        op['outputs'][0]['C_out']*=1e-5
        op['outputs'][0]['C_out2']*=1e-5
        with self.assertRaisesRegex(ValueError,'10%'):
            build_loop_models(self.p,op)

    def test_gui_print_response_charts_share_actual_arrays(self):
        with rc_context({'font.family':['Microsoft YaHei', 'DejaVu Sans']}):
            fig = Figure(figsize=(10.8, 6.3)); FigureCanvasAgg(fig)
            axes = fig.subplots(2, 2)
            for load in (1, 2, 3):
                draw_multi_output_response(axes, self.loop, load)
                fig.tight_layout(); fig.canvas.draw()
                self.assertEqual(len(fig.axes), 4)
                self.assertTrue(all(len(a.lines) == 3 for a in axes.flat))
                for i, line in enumerate(axes[1, 0].lines):
                    np.testing.assert_allclose(line.get_ydata(), np.maximum(abs(self.loop['multi_output']['load'][i, load-1]), 1e-14))


if __name__ == '__main__':
    unittest.main(verbosity=2)
