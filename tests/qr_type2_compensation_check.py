"""QR unity-sense tuning and independently derived physical Type II networks."""
import copy
import json
import math
from pathlib import Path
import sys
import unittest
from unittest.mock import patch
import numpy as np
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
from runtime_resources import configure_numeric_threads
configure_numeric_threads()
from design_engine.specification import load_spec
from power_stage import compute_operating_point
from plants import build_loop_models,make_compensator
from loop_tuning import kfactor_tune,analyze_loop
from compensation_report import compensation_snapshot
import comp_design as compd


def state(key,**changes):
    inputs=dict(R1=40e3,Vref=2.5,R2=10e3,R1u=0.,gm=.002,CTR=1.,Rpullup=20e3,Copto=.1e-9,R_LED=1000.)
    inputs.update(changes)
    return dict(key=key,dir='fwd',type2=False,vars={k:dict(v=v,u='') for k,v in inputs.items()})


class QRType2Checks(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.p=load_spec(json.loads((ROOT/'examples/90W_QR_L6565_300V.json').read_text(encoding='utf-8')))
        cls.op=compute_operating_point(cls.p)

    def test_unity_sampling_and_k_factor_result(self):
        p=self.p;self.assertEqual(p['A_sense'],1.)
        models,_=build_loop_models(p,self.op);r=kfactor_tune(models[0],1000,60,'type2')
        self.assertAlmostEqual(r['fz1'],p['fz1'],places=7)
        self.assertEqual(p['Coss'],p['spice_config']['qr_cds_pf']*1e-12)
        self.assertGreater(r['fp1'],r['fz1'])
        q=dict(p,KP=r['KP'],fz1=r['fz1'],fp1=r['fp1'],controller_type='type2')
        gc=make_compensator(q).get_transfer_function()
        gain=models[0](2j*math.pi*1000)*gc(2j*math.pi*1000)
        self.assertAlmostEqual(abs(gain),1.,places=10)
        self.assertAlmostEqual(180+np.angle(gain,deg=True),60.,places=8)
        scanned=analyze_loop(q,(models[0],gc,models[0]*gc),self.op)
        self.assertAlmostEqual(scanned['fc'],1000,delta=.1)

    def test_actual_impedances_match_two_pole_one_zero_for_all_four_figures(self):
        p=self.p
        for key in ('opamp3','gm3','tl431nf','tl431f'):
            with self.subTest(key=key):
                data=compensation_snapshot(p,self.op,state(key));d=data['parts']
                self.assertTrue(data['buildable']);self.assertTrue(data['exact_type2'])
                self.assertFalse(math.isfinite(data['realized']['wz2']))
                self.assertFalse(math.isfinite(data['realized']['wp2']))
                for f in (1,30,300,1000,10000,100000):
                    s=2j*math.pi*f
                    expected=p['KP']*(1+s/(2*math.pi*p['fz1']))/(s*(1+s/(2*math.pi*p['fp1'])))
                    if key=='opamp3':
                        z=1/(s*d['C2']+1/(d['R2']+1/(s*d['C1'])))
                        actual=z/d['R1']
                    elif key=='gm3':
                        z=1/(s*d['C3']+1/(d['R3']+1/(s*d['C2'])))
                        actual=d['gm']*d['R2']/(d['R1']+d['R2'])*z
                    else:
                        collector=d['CTR']*d['Rpullup']/d['R_LED']/(1+s*d['Rpullup']*(d['C2']+d['Copto']))
                        actual=collector*((d['R2']+1/(s*d['C1']))/d['R1'] if key=='tl431nf' else 1+1/(s*d['R1']*d['C1']))
                    self.assertLess(abs(actual/expected-1),1e-9)

    def test_inactive_corners_cannot_change_parts_or_block_realization(self):
        for key in ('opamp3','gm3','tl431nf','tl431f'):
            baseline=compensation_snapshot(self.p,self.op,state(key))['parts']
            for fz2,fp2 in ((10000,500000),(1e12,.001),(.001,1e12)):
                changed=compensation_snapshot(dict(self.p,fz2=fz2,fp2=fp2),self.op,state(key))
                self.assertEqual(changed['parts'],baseline)

    def test_actual_opto_limit_is_still_enforced(self):
        d=compensation_snapshot(self.p,self.op,state('tl431nf',Copto=10e-9))
        self.assertFalse(d['buildable']);self.assertLess(d['parts']['C2'],0)

    def test_reverse_preserves_exact_type_two_without_remote_pair(self):
        for key in ('opamp3','gm3','tl431nf','tl431f'):
            d=compensation_snapshot(self.p,self.op,state(key))
            updates=compd.controller_updates(d['realized'])
            self.assertEqual(updates['controller_type'],'type2')
            self.assertNotIn('fz2',updates);self.assertNotIn('fp2',updates)
            self.assertAlmostEqual(updates['fp1'],self.p['fp1'])

    def test_web_forward_and_reverse_share_only_active_three_constants(self):
        from web_app.actions import _compensate,_INPUTS
        import tempfile
        with tempfile.TemporaryDirectory() as folder:
            image=Path(folder)/'reference.png'
            for key in ('opamp3','gm3','tl431nf','tl431f'):
                inputs={k:v['v'] for k,v in state(key)['vars'].items() if k in _INPUTS[key]}
                result=_compensate(self.p,dict(op=self.op),dict(key=key,inputs=inputs),image)
                self.assertTrue(result['buildable']);self.assertEqual(len(result['checks']),3)
                reverse={k:v for k,v in result['parts'].items() if k in _INPUTS[key]}
                back=_compensate(self.p,dict(op=self.op),dict(key=key,inputs=reverse,direction='rev'),image)
                self.assertTrue(back['buildable'])
                self.assertEqual(back['spec_updates']['controller_type'],'type2')
                self.assertNotIn('fz2',back['spec_updates'])

    def test_desktop_auto_tune_then_each_network(self):
        import tkinter as tk
        import main
        root=tk.Tk();root.withdraw()
        try:
            with patch.object(main.PowerSupplyAnalyzer,'schedule_update',return_value=None):
                app=main.PowerSupplyAnalyzer(root)
                app.load_isolated_example('90W_QR_L6565_300V.json')
                app.comp_type2.set(True)
                app.run_auto_tune()
                self.assertFalse(app.comp_type2.get())
                self.assertNotIn('error',app.tune_result.get().lower())
                for key,label in app.COMP_TOPOS:
                    app.comp_type.set(label)
                    app._run_comp_calc()
                    text=app.comp_result.get()
                    self.assertNotIn('error',text.lower(),key+': '+text)
                    self.assertIn('标准二型',text)
                    self.assertNotIn('当前阻容不可直接实现',text)
        finally:
            for job in root.tk.splitlist(root.tk.call('after','info')):
                try:root.after_cancel(job)
                except tk.TclError:pass
            root.destroy()


if __name__=='__main__':unittest.main()
