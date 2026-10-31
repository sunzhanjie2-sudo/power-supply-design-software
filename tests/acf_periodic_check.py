"""Physical invariants and independent archived LTspice reference checks."""
import copy
import json
from pathlib import Path
import sys
import time
import unittest
import numpy as np
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
from runtime_resources import configure_numeric_threads
configure_numeric_threads()
from design_engine.specification import load_spec
from power_stage import compute_operating_point
from acf_periodic import solve_point
from winding_coupling import resolve_winding_model
from acf_loop import build_loop
from spice_analysis import loop_metrics,steady_quality


class PeriodicChecks(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.p=load_spec(json.loads((ROOT/'examples/33W_3OUT_ACF_MP6005.json').read_text(encoding='utf-8')))
        cls.reference=json.loads((ROOT/'tests/fixtures/acf_reference.json').read_text())
        cls.ops={v:compute_operating_point(dict(cls.p,V_in=v)) for v in (20,30)}

    def test_period_charge_and_energy_are_checked(self):
        for op in self.ops.values():
            meta=op['acf_model'];self.assertLess(meta['normalized_residual'],1e-6)
            self.assertLess(meta['energy_balance_relative'],.01)
            z=op['acf_solution'];t=z['t']
            self.assertAlmostEqual(t[-1],op['Ts'],places=14)
            for il,c in zip(z['iL'],op['output_ops']):
                self.assertAlmostEqual(float(np.trapezoid(il,t)/op['Ts']),c['I_out'],delta=2e-6)
            self.assertAlmostEqual(float(np.trapezoid(z['i_clamp'],t)/op['Ts']),0.,delta=.005)

    def test_against_real_spice_dc_and_currents(self):
        for record in self.reference['cases']:
            op=self.ops[record['voltage']];m=record['measurements']
            self.assertLess(abs(op['D']/m['duty_avg']-1),.02)
            self.assertLess(abs(op['I_p_rms']/m['primary_rms']-1),.03)
            for i,child in enumerate(op['output_ops'],1):
                self.assertLess(abs(child['V_out']/m[f'out{i}_before']-1),.01)
                self.assertLess(abs(child['I_s_rms']/m[f'out{i}_winding_rms']-1),.03)
                self.assertLess(abs(child['I_d_avg']/m[f'out{i}_winding_avg']-1),.03)

    def test_loop_uses_same_physical_point_and_ramp(self):
        f=np.geomspace(100,4000,300)
        for record in self.reference['cases']:
            op=self.ops[record['voltage']];p=dict(self.p,V_in=record['voltage'])
            models,detail=build_loop(p,op);actual=loop_metrics(f,np.asarray(models[2](2j*np.pi*f)).ravel())
            self.assertLess(abs(actual['fc']/record['loop']['fc']-1),.1)
            self.assertLess(abs(actual['pm']-record['loop']['pm']),7.)
            self.assertAlmostEqual(detail.loop_metadata['slope_v_per_s'],19045.08125,places=5)
            self.assertTrue(detail.loop_metadata['esr_included'])
            self.assertEqual(detail.loop_metadata['capacitor_states'],6)

    def test_no_efficiency_double_count_or_input_mutation(self):
        p=copy.deepcopy(self.p);before=copy.deepcopy(p)
        a=compute_operating_point(p);b=compute_operating_point(dict(p,eta_guess=.8))
        self.assertEqual(p,before)
        self.assertAlmostEqual(a['D'],b['D'],places=10)
        self.assertEqual(a['acf_model']['output_voltages'],b['acf_model']['output_voltages'])

    def test_period_sensitivities_match_direct_perturbation(self):
        p=dict(self.p,V_in=20);op=self.ops[20];g=op['acf_model']['transformer_hardware']
        model=resolve_winding_model(p,op['outputs'],geometry=g)
        circuit,z=solve_point(p,op['outputs'],g,model)
        h=1e-6;hi=circuit.cycle(z['initial'],z['voltages'],z['duty']+h)
        lo=circuit.cycle(z['initial'],z['voltages'],z['duty']-h)
        finite=(hi['mean']-lo['mean'])/(2*h)
        self.assertLess(float(np.linalg.norm(finite-z['charge_jac'][:,-1])/max(np.linalg.norm(finite),1e-8)),.01)

    def test_long_window_rejects_low_frequency_startup(self):
        class Raw:
            time=np.linspace(0,.03,30001)
            def trace(self,key):return 30+self.amplitude*np.sin(2*np.pi*200*self.time)
        raw=Raw();raw.amplitude=1
        self.assertFalse(steady_quality(raw,250e3,.025,1)['passed'])
        raw.amplitude=.001
        self.assertTrue(steady_quality(raw,250e3,.025,1)['passed'])


if __name__=='__main__':unittest.main()
