"""MP6005 first drafts, checked against the normal calculator and independent identities."""
import json
import math
from pathlib import Path
import sys
import unittest

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from runtime_resources import configure_numeric_threads
configure_numeric_threads()
from design_engine.initial_design import generate,form_options,describe
from design_engine.service import calculate
from power_stage import compute_operating_point


class FlybackSizing(unittest.TestCase):
    def test_modes_fixed_hardware_and_compensation(self):
        from compensation_report import compensation_snapshot
        from plants import build_loop_models
        import control as ct
        for mode in ('CCM','DCM'):
            with self.subTest(mode=mode):
                p=generate(dict(topology='FLYBACK',conduction=mode,imin=2/3))
                b=p['__auto_design_basis']
                self.assertTrue(b['model_ok'],describe(p))
                spec=json.loads(json.dumps(p,allow_nan=False))
                self.assertEqual(form_options(spec)['conduction'],mode)
                bundle=calculate(spec,analysis='endpoints',include_cross_regulation=False).runtime_bundle()
                self.assertEqual(len(bundle['cases']),2)
                for i,case in enumerate(bundle['cases']):
                    self.assertIsNone(case['error'])
                    q,res=case['p'],case['result']
                    op=res['op'];row=b['corners'][2*i]
                    self.assertEqual(mode,op['mode'])
                    self.assertAlmostEqual(op['V_sw_max'],op['V_in']+q['Kc']*op['V_r'])
                    self.assertAlmostEqual(res['wf']['ripple_pp'],row['ripple'])
                    self.assertAlmostEqual(res['loop']['min_pm'],row['loop']['pm'],places=5)
                    self.assertLessEqual(row['loop']['fc'],row['fc_limit'])
                    self.assertLessEqual(1.25*row['peak']*q['Rs'],.14)
                    self.assertAlmostEqual(p['Np']/p['Ns'],q['N'])
                    self.assertLessEqual(row['bpeak'],q['Bmax'])
                    net=compensation_snapshot(q,op,p['__comp'])
                    self.assertTrue(net['buildable'])
                    self.assertAlmostEqual(net['parts']['R_lower'],b['compensation_pin']['R_lower'])
                    if mode=='DCM':
                        self.assertGreater(row['idle'],.10)
                        self.assertAlmostEqual(.5*q['L']*op['I_sw_pk']**2*q['f_sw']*q['eta_guess'],q['P_out'])
                        (plant,_,_),_=build_loop_models(q,op)
                        gain=op['V_out']/(op['I_sw_pk']*q['Rs']*q['A_sense']*(1+q['ma_slope']*q['L']/q['V_in']))
                        self.assertAlmostEqual(float(ct.dcgain(plant)),gain,places=7)
                self.assertLessEqual(max(r['sense_loss'] for r in b['corners']),.2*b['requirements']['sense_rated_w']+1e-12)

    def test_multi_preserves_ratios_and_verifies_independent_loads(self):
        f=form_options(json.loads((ROOT/'examples/40W_CCM_3OUT_FLYBACK.json').read_text(encoding='utf8')))
        w=f['windings']
        spec={k:f['values'][k]*scale for k,_,scale,_ in f['fields']}
        p=generate(dict(spec,topology='FLYBACK',windings=w))
        b=p['__auto_design_basis']
        self.assertEqual([r['P_out'] for r in p['outputs']],[30,1,2])
        self.assertEqual(p['coupling_config']['k'],w['coupling_config']['k'])
        self.assertEqual(p['N'],p['Np']/p['outputs'][0]['Ns'])
        for r,old in zip(p['outputs'],w['rails']):
            self.assertEqual(r['Ns']/p['outputs'][0]['Ns'],old['Ns']/w['rails'][0]['Ns'])
        self.assertAlmostEqual(b['compensation_pin']['R_lower'],20000*2.5/(30+.7-2.5))
        scan=b['cross_regulation']
        self.assertTrue(scan['complete'],scan.get('error'))
        self.assertEqual(len(scan['cases']),16)
        self.assertTrue(all(c['residual']<2e-5 for c in scan['cases']))
        for c in scan['cases']:
            req=b['requirements'];stress=c['stress']
            self.assertLessEqual(stress['sense_loss'],.2*req['sense_rated_w']+1e-12)
            self.assertLessEqual(stress['clamp_loss'],.2*req['clamp_rated_w']+1e-12)
            self.assertLessEqual(stress['vds'],req['vds_min'])
            self.assertEqual(len(stress['vrrm']),3)
        self.assertGreater(scan['summary'][2]['V_max'],scan['summary'][2]['V_min'])
        self.assertEqual(json.loads(json.dumps(p,allow_nan=False))['feedback_output'],1)
        for r in b['corners']:
            self.assertTrue(r['loop']['stable'])
            if r['loop'].get('gm_scan_limited') and r['loop']['gm_db'] is None:
                self.assertIn('−180°',' '.join(r['issues']))

    def test_selected_feedback_and_locks(self):
        from design_engine.flyback_sizing import _size
        from design_engine.initial_design import _prepare
        f=form_options(json.loads((ROOT/'examples/40W_CCM_3OUT_FLYBACK.json').read_text(encoding='utf8')))
        w=f['windings'];w['feedback_output']=2
        pins={'L':18e-6,'rail_banks':f['locks']['rail_banks']}
        _,s,_,locked=_prepare(dict(topology='FLYBACK',vout=12,iout=.25,imin=.1,locked=pins))
        p,rails,ref,rules=_size(s,locked,w)
        self.assertEqual(ref,1)
        self.assertEqual(p['outputs'][1]['V_out'],12)
        self.assertEqual([r['output_capacitors'] for r in p['outputs']],pins['rail_banks'])
        self.assertEqual(p['L'],pins['L'])
        self.assertEqual(p['N'],p['Np']/p['outputs'][0]['Ns'])
        self.assertGreater(rails[0]['V_out'],rails[1]['V_out'])
        self.assertEqual(form_options(p)['values']['iout'],.25)

    def test_guardrails_no_silent_fallback(self):
        for other in (dict(fs=200000),dict(vin_min=7),dict(vout=3.3),dict(conduction='BCM'),
                      dict(windings=dict(feedback_mode='PSR-MP6005')),dict(locked=dict(inductor_dcr=.01)),
                      dict(windings=dict(feedback_output=2))):
            with self.subTest(other=other),self.assertRaises(ValueError):
                generate(dict(topology='FLYBACK',**other))
        p=generate(dict(topology='FLYBACK',imin=0,vin_max=20.))
        b=p['__auto_design_basis']
        self.assertFalse(b['model_ok'])
        self.assertNotIn('loop',b['corners'][1])
        self.assertIn('真空载',describe(p))


if __name__=='__main__': unittest.main(verbosity=2)
