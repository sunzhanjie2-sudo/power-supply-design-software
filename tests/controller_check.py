"""Regression for restored II/III controllers and legacy RC calculator."""
import math
import sys
import unittest
from pathlib import Path
import control as ct
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import plants
import comp_design as compd
from power_stage import DEFAULT_PARAMS
from loop_tuning import kfactor_tune
from design_api import load_spec

class ControllerTests(unittest.TestCase):
    def test_orders_and_mode_independence(self):
        for mode in ('Voltage Mode','Peak Current Mode'):
            for kind,order,zeros in [('type2',2,1),('type3',3,2)]:
                p=dict(DEFAULT_PARAMS,control_mode=mode,controller_type=kind)
                g=plants.make_compensator(p).get_transfer_function()
                self.assertEqual(len(ct.poles(g)),order)
                self.assertEqual(len(ct.zeros(g)),zeros)
                self.assertTrue(any(abs(v)<1e-12 for v in ct.poles(g)))
        self.assertEqual(plants.resolve_controller_type('auto','Peak Current Mode'),'type2')
        self.assertEqual(plants.resolve_controller_type('auto','Voltage Mode'),'type3')

    def test_withdrawn_pi_config_migration(self):
        self.assertEqual(load_spec({'controller_type':'PI'})['controller_type'],'auto')
        self.assertEqual(load_spec({'controller_type':{'v':'PI','u':''}})['controller_type'],'auto')
        self.assertFalse(hasattr(plants,'CompensatorPI'))

    def test_type2_ignores_unused_corners(self):
        p=dict(DEFAULT_PARAMS,controller_type='type2',fz2=0,fp2=0)
        self.assertEqual(len(ct.poles(plants.make_compensator(p).get_transfer_function())),2)

    def test_legacy_opamp_simplification(self):
        d=compd.opamp_type3_solve(800,1000,2000,10000,20000,10000,type2=True)
        self.assertEqual(d['C2'],0)
        self.assertEqual(d['C3'],0)
        ev=compd.opamp_type3_eval(*(d[k] for k in ('R1','R2','R3','C1','C2','C3')))
        self.assertAlmostEqual(ev['KP'],800)
        self.assertTrue(math.isinf(ev['wp1']))

    def test_legacy_gm_simplification(self):
        d=compd.gm_type3_solve(800,1000,2000,10000,20000,10000,R1=100000,type2=True)
        self.assertEqual(d['C1'],0)
        self.assertEqual(d['C3'],0)
        ev=compd.gm_type3_eval(*(d[k] for k in ('gm','R1','R2','R3','C1','C2','C3')))
        self.assertAlmostEqual(ev['KP'],800)
        self.assertTrue(math.isinf(ev['wp1']))

    def test_original_three_type_roundtrip(self):
        a=compd.opamp_type3_solve(800,1000,2000,10000,20000,10000)
        ev=compd.opamp_type3_eval(*(a[k] for k in ('R1','R2','R3','C1','C2','C3')))
        for key,target in [('KP',800),('wz1',1000),('wz2',2000),('wp1',10000),('wp2',20000)]:
            self.assertAlmostEqual(ev[key],target,places=8)
        a=compd.gm_type3_solve(800,1000,2000,10000,20000,10000)
        ev=compd.gm_type3_eval(*(a[k] for k in ('gm','R1','R2','R3','C1','C2','C3')))
        self.assertAlmostEqual(ev['KP'],800)

    def test_tuning_and_unreachable_target(self):
        s=ct.tf('s'); plant=20/(1+s/(2*math.pi*100))
        for kind in ('type2','type3'):
            r=kfactor_tune(plant,1000,65,kind)
            self.assertTrue(r['feasible'])
            p=dict(DEFAULT_PARAMS,controller_type=kind)
            p.update({k:r[k] for k in ('KP','fz1','fz2','fp1','fp2') if r[k] is not None})
            gc=plants.make_compensator(p).get_transfer_function()
            self.assertAlmostEqual(abs((gc*plant)(2j*math.pi*1000)),1,places=11)
        self.assertFalse(kfactor_tune(ct.tf([1],[1]),1000,200,'type2')['feasible'])
        with self.assertRaises(ValueError):
            kfactor_tune(plant,1000,60,'pi')

if __name__=='__main__':
    unittest.main(verbosity=2)
