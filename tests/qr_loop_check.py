"""QR/BCM peak-current response checked against independent finite differences."""
import copy
import json
import math
from pathlib import Path
import sys
import unittest
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
from design_engine.specification import load_spec
from design_engine.service import calculate_parameters
from qr_loop import linearize,plant
from plants import build_loop_models


class QRLoopCheck(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        spec=json.loads((ROOT/'examples/90W_QR_L6565_300V_TUNED.json').read_text(encoding='utf-8'))
        p=load_spec(spec)
        cls.case=calculate_parameters(p,analysis='endpoints',include_loop=False,include_cross_regulation=False).runtime_bundle()['cases'][0]
        cls.p=cls.case['p'];cls.op=cls.case['result']['op']

    def test_measured_point_derivatives_match_cycle_charge(self):
        m=dict(vin_bus=300.,vout=59.960354,vcap=60.661886,ipk=2.3984846,period=1/41499.295,iout=1.5318816)
        before=copy.deepcopy((self.p,self.op,m));x=linearize(self.p,self.op,measured=m)
        self.assertEqual((self.p,self.op,m),before)
        L,N=self.p['L'],self.p['N'];vin=x['vin_bus'];dead=x['dead_time'];scale=x['current_scale']
        vf=self.p['Vf_diode']
        def current(i,v):
            vr=N*(v+vf);T=L*i*(1/vin+1/vr)+dead
            return scale*N*L*i*i/(2*vr*T)
        di=(current(x['ipk']+1e-5,x['vcap'])-current(x['ipk']-1e-5,x['vcap']))/2e-5
        dv=(current(x['ipk'],x['vcap']+1e-4)-current(x['ipk'],x['vcap']-1e-4))/2e-4
        self.assertAlmostEqual(di,x['d_iout_d_ipk'],places=7)
        self.assertAlmostEqual(dv,x['d_iout_d_vcap'],places=7)
        self.assertAlmostEqual(current(x['ipk'],x['vcap']),x['iout'],places=10)
        self.assertGreater(x['dead_time'],0)
        g,_=plant(self.p,self.op,measured=m)
        self.assertAlmostEqual(20*math.log10(abs(g(2j*math.pi*100))),-3.5,delta=.15)

    def test_design_is_used_by_default_and_peak_gain_is_physical(self):
        models,_=build_loop_models(self.p,self.op);expected,x=plant(self.p,self.op)
        self.assertEqual(x['point_source'],'design')
        self.assertAlmostEqual(abs(models[0](2j*math.pi*100)),abs(expected(2j*math.pi*100)))
        modified=dict(self.p,A_sense=self.p['A_sense']*2)
        doubled,_=plant(modified,self.op)
        self.assertAlmostEqual(abs(doubled(2j*math.pi*100)),abs(expected(2j*math.pi*100))/2)
        self.assertEqual(len(x['capacitors']),2)

    def test_wrong_working_point_is_not_silently_fixed(self):
        with self.assertRaisesRegex(ValueError,'周期小于'):
            linearize(self.p,self.op,measured={'period':1e-6})

    def test_design_prediction_against_recorded_switching_fra(self):
        from spice_export import project_files
        from spice_studies import analytical_loop
        import numpy as np
        fixture=json.loads((ROOT/'tests/fixtures/qr_fra_300v_20261027.json').read_text(encoding='utf-8'))
        actual=fixture['simulation'];frequency=actual['plant']['f']
        metadata=json.loads(project_files(self.p)['manifest.json'])
        predicted=analytical_loop(self.case,metadata['resolved_controller'],frequency)
        self.assertIsNone(predicted['point'])  # no simulator values used for prediction
        for key in ('plant','compensator','loop'):
            self.assertLess(max(abs(a-b) for a,b in zip(predicted[key]['db'],actual[key]['db'])),1.,key)
        self.assertLess(max(abs(a-b) for a,b in zip(predicted['plant']['phase'],actual['plant']['phase'])),15.)
        np.testing.assert_allclose(np.array(actual['plant']['db'])+np.array(actual['compensator']['db']),actual['loop']['db'],atol=.05)


if __name__=='__main__':unittest.main()
