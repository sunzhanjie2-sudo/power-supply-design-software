"""Multi-output conservation, MP6005 boundaries and real Tk configuration."""
import copy
import json
import math
from pathlib import Path
import sys
import tkinter as tk
import unittest
import numpy as np
from matplotlib.figure import Figure

sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from power_stage import DEFAULT_PARAMS
from loss_model import compute_design
from isolated_outputs import output_specs,scale_load
from plants import build_loop_models,Compensator2P2Z
from mp6005 import compensation_parts
from analysis_workflows import evaluate,pin_hardware,corners
from design_api import load_spec,run_design,autotune_loop
from topology_diagram import draw_topology
from waveforms import make_waveforms


def multi(topo='FLYBACK',mode='SSR',n=3):
    p=copy.deepcopy(DEFAULT_PARAMS)
    p.update(topology=topo,feedback_mode=mode,feedback_output=1,Rs=.015,Vgs=8.5)
    p['outputs']=[dict(name=f'Rail {i+1}',V_out=v,P_out=w,Ns=0,d_wire_s=0.,n_strand_s=10,
                       C_out=220e-6,C_out2=100e-6,L=1e-3) for i,(v,w) in enumerate(zip((30,12,5,3.3,24,15),(20,8,4,2,4,2)))][:n]
    if topo=='ACF-FORWARD': p.update(N=.5,Lm_forward=220e-6,C_clamp=47e-9)
    return p


class MultiChecks(unittest.TestCase):
    def test_conservation_all_isolated(self):
        for topo in ('FLYBACK','QR-FLYBACK','ACF-FORWARD'):
            p=multi(topo,n=6); r=compute_design(p); op=r['op']; wf=make_waveforms(op,n_pts=100000)
            self.assertEqual(len(r['outputs']),6)
            self.assertEqual(op['P_out'],40)
            self.assertAlmostEqual(np.mean(wf['i_in']),op['P_in_est']/p['V_in'],delta=.001)
            for child,branch in zip(op['output_ops'],wf['outputs']):
                self.assertAlmostEqual(np.mean(branch['i_c']),0.,delta=.001)
                self.assertAlmostEqual(np.mean(branch['i_d']),child['I_d_avg'],delta=.001)
            if topo!='ACF-FORWARD':
                ampere=sum(branch['i_d']/child['N'] for child,branch in zip(op['output_ops'],wf['outputs']))
                np.testing.assert_allclose(ampere,wf['i_s']/op['N'] if op['feedback_output']==1 and len(op['outputs'])==1 else
                                           make_waveforms(op['aggregate_op'],n_pts=100000)['i_s']/op['aggregate_op']['N'],atol=1e-10)
            self.assertAlmostEqual(r['P_semi'],r['semi']['switch']['P_total']+r['semi'].get('auxiliary',{}).get('P_total',0)+sum(x['P_rectifier'] for x in r['outputs']))
            self.assertAlmostEqual(r['P_mag'],r['mag']['transformer']['P_total']+sum(d['P_total'] for d in r['mag'].get('inductors',[])))
            self.assertAlmostEqual(r['P_cap'],sum(x['P_cap'] for x in r['outputs']))

    def test_feedback_does_not_change_primary(self):
        for topo in ('FLYBACK','QR-FLYBACK','ACF-FORWARD'):
            p=multi(topo)
            # Import legacy Ns=0 targets once, then switch feedback on the
            # same physical transformer and the voltage already established
            # by its integer turns.  Retargeting 12.5 V to 12 V would be a
            # deliberate different operating point, not a selector-only edit.
            p['outputs']=[{k:v for k,v in r.items() if k!='id'} for r in output_specs(p)]
            voltage=p['outputs'][1]['V_out']
            a=compute_design(p); b=compute_design(dict(p,feedback_output=2))
            for k in ('P_out','P_in_est','D','I_sw_pk','I_sw_rms','V_sw_max'):
                self.assertAlmostEqual(a['op'][k],b['op'][k],places=9,msg=k+topo)
            np.testing.assert_allclose(a['wf']['i_sw'],b['wf']['i_sw'],atol=1e-10)
            self.assertAlmostEqual(b['op']['I_out'],8/voltage)
            self.assertAlmostEqual(a['P_total'],b['P_total'],places=9)

    def test_schema_nested_units_and_rejections(self):
        p=multi(); p['outputs'][1]['C_out']=dict(v=220,u='u')
        self.assertAlmostEqual(load_spec(p)['outputs'][1]['C_out'],220e-6)
        self.assertEqual(scale_load(p,.25)['outputs'][1]['P_out'],2.)
        for bad in (dict(p,outputs=[{}]*7),dict(p,feedback_output=4),dict(p,topology='BUCK'),
                    dict(p,outputs=[dict(V_out=0)]),dict(p,outputs=[dict(P_out=-1)]),dict(p,outputs=[dict(Ns=1.5)])):
            with self.assertRaises(ValueError): compute_design(bad)
        with self.assertRaisesRegex(ValueError,'DCM'):
            p=multi('ACF-FORWARD'); p['outputs'][1]['L']=1e-6; compute_design(p)

    def test_corners_freeze_every_winding(self):
        p=multi(); r=compute_design(p); fixed=pin_hardware(p,r)
        base=r['mag']['transformer']['windings']
        result=compute_design(dict(scale_load(fixed,.5),V_in=27))
        for a,b in zip(base,result['mag']['transformer']['windings']):
            for k in ('Ns','d_wire_s','n_strand_s'): self.assertEqual(a[k],b[k])
        c=corners(p,load_fracs=(.5,1.))
        self.assertEqual(len(c['corners']),6)
        self.assertFalse(any(x['skipped'] for x in c['corners']))

    def test_automatic_primary_and_legacy_secondaries_freeze_as_one_hardware(self):
        for topology in ('FLYBACK','QR-FLYBACK','ACF-FORWARD'):
            with self.subTest(topology=topology):
                p=multi(topology)
                p['Np']=0
                result=compute_design(p)
                tr=result['mag']['transformer']
                fixed=pin_hardware(p,result)
                secondary=[row['Ns'] for row in tr['windings']]
                self.assertEqual([row['Ns'] for row in fixed['outputs']],secondary)
                self.assertEqual(fixed['_fixed_transformer']['Np'],tr['Np'])
                for vin in (p['V_in']*.9,p['V_in']*1.1):
                    corner=compute_design(dict(scale_load(fixed,.5),V_in=vin))
                    self.assertEqual(corner['op']['output_turns']['Np'],tr['Np'])
                    self.assertEqual(corner['op']['output_turns']['Ns'],secondary)
                    self.assertEqual([row['Ns'] for row in corner['mag']['transformer']['windings']],secondary)
                    for child,ns in zip(corner['op']['output_ops'],secondary):
                        self.assertAlmostEqual(child['N'],tr['Np']/ns)

    def test_schematic_registry(self):
        for n in (1,3,6):
            for topo,mode in (('FLYBACK','SSR'),('QR-FLYBACK','SSR'),('ACF-FORWARD','SSR'),('FLYBACK','PSR-MP6005')):
                p=multi(topo,mode,n); fig=Figure(); rows=draw_topology(fig.subplots(),p)
                refs={r['ref'] for r in rows}
                self.assertIn(f'J_O{n}',refs); self.assertIn(f'D_O{n}',refs)
                self.assertIn('U_PSR' if mode!='SSR' else 'U_FB',refs)

    def test_api_serializable_and_snapshot_unchanged(self):
        p=multi(n=6); original=copy.deepcopy(p); r=run_design(p)
        self.assertTrue(r['ok']); self.assertEqual(len(r['outputs']),6)
        self.assertEqual(p,original); json.dumps(r,ensure_ascii=False)


class PSRChecks(unittest.TestCase):
    def test_datasheet_equations(self):
        p=multi(mode='PSR-MP6005'); r=compute_design(p); d=r['psr']; op=r['op']
        self.assertEqual(op['f_sw'],250e3); self.assertEqual(d['region'],'PWM')
        self.assertAlmostEqual(d['Vfb'],2.)
        self.assertAlmostEqual(d['Vout_set'],op['V_out'])
        reflected=d['Np']/d['Ns']*(op['V_out']+p['Vf_diode'])
        self.assertAlmostEqual(d['Lpri_min'],reflected*.7e-6*p['Rs']/.033)
        self.assertAlmostEqual(d['tcon_min33'],p['L']*.033/p['Rs']/reflected)
        self.assertAlmostEqual(d['Rs_recommended'],.128/op['I_sw_pk'])
        self.assertAlmostEqual(d['Ifb_negative'],p['V_in']*d['Na']/d['Np']/d['RfbH'])
        self.assertAlmostEqual(d['P_controller'],p['V_in']*.0008+d['Vaux']**2/(d['RfbH']+d['RfbL']))
        self.assertIn('auxiliary',r['mag']['transformer'])
        self.assertAlmostEqual(r['P_total'],sum(r[k] for k in ('P_semi','P_mag','P_cap','P_cap_in','P_sense','P_rcd','P_din','P_dout','P_clamp','P_controller')))

    def test_physical_comp_and_autotune(self):
        p=multi(mode='PSR-MP6005'); r=compute_design(p); d=r['psr']; models,_=build_loop_models(p,r['op'])
        s=1j*2*math.pi*1000; r_,c_,cp=d['Rcomp'],d['Ccomp'],d['Cpole']
        expected=d['gm']*(1+s*r_*c_)/(s*(c_+cp)*(1+s*r_*c_*cp/(c_+cp)))
        self.assertAlmostEqual(abs(models[1](s)-expected),0.,places=8)
        from loop_tuning import kfactor_tune
        tuned=kfactor_tune(models[0],1000,60,'type2'); parts=compensation_parts(tuned)
        other=compute_design(dict(p,**parts)); actual=build_loop_models(dict(p,**parts),other['op'])[0][1]
        target=Compensator2P2Z(tuned['KP'],tuned['fz1'],tuned['fp1']).get_transfer_function()
        self.assertAlmostEqual(abs(actual(s)-target(s)),0.,places=8)
        result=autotune_loop(p,1000,60)
        self.assertTrue(result['feasible']); self.assertEqual(set(result['spec_updates']),set(parts))
        self.assertAlmostEqual(result['achieved']['fc'],1000,delta=1)

    def test_light_load_and_unsupported(self):
        p=multi(mode='PSR-MP6005'); q=scale_load(p,.04); r=compute_design(q)
        self.assertEqual(r['psr']['region'],'PFM-estimate')
        with self.assertRaisesRegex(ValueError,'PFM'): build_loop_models(q,r['op'])
        with self.assertRaisesRegex(ValueError,'最小能量'): compute_design(scale_load(p,.001))
        for topo in ('QR-FLYBACK','ACF-FORWARD','BUCK'):
            with self.assertRaises(ValueError): compute_design(dict(p,topology=topo))
        q=dict(p,psr_Rreg=5e3); s=evaluate(q)
        self.assertEqual(next(c for c in s['checks'] if c['id']=='psr_reg')['state'],'review')


class UIChecks(unittest.TestCase):
    def test_config_switching_and_psr_state(self):
        import main
        root=tk.Tk(); root.withdraw(); app=main.PowerSupplyAnalyzer(root)
        try:
            p=multi(n=6); app._apply_config(p); self.assertTrue(app.update_all())
            self.assertEqual(app.get_params()['Vgs'],8.5)
            self.assertEqual(app.get_params()['Rs'],.015)
            self.assertEqual(len(app.output_tree.get_children()),6)
            cfg=app._config_dict(); app._apply_config(cfg); self.assertEqual(app.get_params()['outputs'],load_spec(p)['outputs'])
            voltage=output_specs(app.get_params())[1]['V_out']
            app.feedback_output.set(2); self.assertTrue(app.update_all()); self.assertAlmostEqual(app._last['op']['V_out'],voltage)
            app._apply_config(multi(mode='PSR-MP6005')); self.assertTrue(app.update_all())
            app._update_loop(app._last['p']); self.assertIsNotNone(app._loop_result)
            q=scale_load(multi(mode='PSR-MP6005'),.04); app._apply_config(q); self.assertTrue(app.update_all())
            app._update_loop(app._last['p']); self.assertIsNone(app._loop_result)
            self.assertFalse(any(ax.lines for ax in app.ax_loop.flat))
            self.assertIn('PFM',app.loop_esr_note.get())
            app._apply_config({}); self.assertEqual(app.get_params()['outputs'],[]); self.assertEqual(app.get_params()['feedback_mode'],'SSR')
            app.load_isolated_example('MP6005_PSR_FLYBACK.json')
            self.assertEqual(app.get_params()['Np'],20)
            self.assertTrue(app.update_all(),app.status_var.get())
            self.assertEqual(app._last['res']['psr']['Np'],20)
        finally:
            app._closing=True
            for name in ('update_timer','_font_timer','_initial_update_job','_control_warmup_job','_control_poll_job'):
                job=getattr(app,name,None)
                if job is not None: root.after_cancel(job)
            root.destroy()


if __name__=='__main__': unittest.main(verbosity=2)
