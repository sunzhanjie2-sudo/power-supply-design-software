"""Shared-engine, snapshot, fixed-hardware and real GUI workflow regressions."""
import copy
import json
import math
from pathlib import Path
import sys
import time
import unittest
from unittest.mock import patch
import tkinter as tk
import numpy as np
import control as ct

sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from power_stage import DEFAULT_PARAMS, compute_operating_point
from config_io import decode_config, read_default_config
from design_api import load_spec, run_design
from loss_model import compute_design
from plants import build_loop_models
from loop_tuning import analyze_loop
from capripple import _divide_and_band, analyze_capacitors
from waveforms import make_waveforms
from analysis_workflows import evaluate, corners, pin_hardware, compare
from design_checks import check_catalog


class EngineChecks(unittest.TestCase):
    def test_startup_defaults(self):
        decoded=decode_config(read_default_config())
        for key in ('V_in','V_out','P_out','f_sw','L','Rs','A_sense','KP','fz1','fz2','fp1','fp2','K','Kc'):
            self.assertEqual(DEFAULT_PARAMS[key],decoded[key])
        self.assertEqual(DEFAULT_PARAMS['topology'],'FLYBACK')
        self.assertEqual(DEFAULT_PARAMS['sweep_min'],50e3)
        snap=evaluate(DEFAULT_PARAMS)
        self.assertEqual(snap['op']['mode'],'CCM')
        lcheck=next(c for c in snap['checks'] if c['id']=='L_min')
        self.assertIn('40%',lcheck['note'])
        self.assertIn('不是 CCM 临界值',lcheck['note'])
        # The saved compensator is preserved; the changed plant needs review,
        # not a silent retune to its historical target.
        from design_api import loop_margins_for
        self.assertAlmostEqual(snap['res']['loop']['fc'],loop_margins_for(DEFAULT_PARAMS)['fc'],places=3)

    def test_capacitance_dimensions(self):
        for topo in ('BUCK','BOOST','BUCK-BOOST','FLYBACK','QR-FLYBACK','ACF-FORWARD'):
            p=dict(DEFAULT_PARAMS,topology=topo,V_in=30,V_out=15 if topo=='BUCK' else 30 if topo=='ACF-FORWARD' else 40,
                   P_out=40,L=68e-6)
            a=compute_operating_point(p); b=compute_operating_point(dict(p,Rc=10))
            self.assertEqual(a['C_min'],b['C_min'],topo)

    def test_parseval_and_dc(self):
        f=100e3; N=4096; t=np.arange(N)/(N*f/2)
        x=3+np.sin(2*np.pi*f*t)+.4*np.sin(20*np.pi*f*t)
        cap=[dict(C=100e-6,ESR=.02,ESL=2e-9)]
        r=_divide_and_band(x,t[1]-t[0],f,cap)
        self.assertEqual(r['spectrum_method'],'coherent DFT')
        self.assertAlmostEqual(r['caps'][0]['total'],math.sqrt(.5+.08),places=12)
        self.assertAlmostEqual(sum(x*x for x in r['caps'][0]['bands']),r['total_bank']**2,places=12)
        nyquist=(-1.)**np.arange(N)
        self.assertAlmostEqual(_divide_and_band(nyquist,t[1]-t[0],f,cap)['caps'][0]['total'],1,places=12)

    def test_shared_caps_and_sampling(self):
        p=dict(DEFAULT_PARAMS); res=compute_design(p)
        caps=analyze_capacitors(p,res['op'],res['wf'])
        self.assertEqual(caps,res['capacitors'])
        loss=sum(c['ESR']*c['total']**2 for c in caps['output']['caps'])
        self.assertAlmostEqual(loss,res['P_cap'],places=12)
        doubled=analyze_capacitors(p,res['op'],make_waveforms(res['op'],n_pts=4096))
        for a,b in zip(caps['output']['caps'],doubled['output']['caps']):
            self.assertLess(abs(a['total']-b['total'])/b['total'],.005)

    def test_no_and_multiple_crossovers(self):
        one=ct.tf([1],[1]); tiny=ct.tf([.1],[1])
        r=analyze_loop(DEFAULT_PARAMS,(one,one,tiny))
        self.assertIsNone(r['fc']); self.assertIsNone(r['pm'])
        snap=compute_design(DEFAULT_PARAMS)
        c=next(c for c in check_catalog(DEFAULT_PARAMS,snap,r) if c['id']=='loop')
        self.assertEqual(c['state'],'review')
        band=ct.tf([100,0],[1,11,10])
        r=analyze_loop(DEFAULT_PARAMS,(one,one,band))
        self.assertEqual({c['direction'] for c in r['all_crosses']},{'up','down'})
        self.assertEqual(r['min_pm'],min(c['pm'] for c in r['all_crosses']))

    def test_api_catalog_matches(self):
        for topo in ('BUCK','BOOST','BUCK-BOOST','FLYBACK','QR-FLYBACK','ACF-FORWARD'):
            p=load_spec(dict(topology=topo,V_in=30,V_out=15 if topo=='BUCK' else 30 if topo=='ACF-FORWARD' else 40,P_out=40,L=68e-6))
            snap=evaluate(p); r=run_design(p)
            self.assertTrue(r['ok'],r.get('error'))
            self.assertEqual(r['checks'],snap['checks'],topo)
            self.assertEqual(r['loop']['fc'],snap['res']['loop']['fc'])
            self.assertEqual(r['operating_point']['f_sw'],snap['op']['f_sw'])

    def test_frozen_hardware(self):
        for topo in ('BUCK','FLYBACK','ACF-FORWARD'):
            p=dict(DEFAULT_PARAMS,topology=topo,V_out=15 if topo=='BUCK' else 30,L=68e-6,
                   core_choice='auto',core_shape='auto',Np=0,Ns=0,d_wire_p=0,d_wire_s=0,MLT=0)
            a=evaluate(p); pinned=pin_hardware(p,a['res'])
            b=evaluate(dict(pinned,P_out=p['P_out']*.1,V_in=p['V_in']*1.1))
            for kind in ('inductor','transformer'):
                if '_fixed_'+kind in pinned:
                    for key,val in pinned['_fixed_'+kind].items():
                        self.assertEqual(val,b['res']['mag'][kind][key],f'{topo} {kind} {key}')

    def test_corner_cancellation_and_worst(self):
        p=dict(DEFAULT_PARAMS); events=[]
        result=corners(p,progress=lambda *e:events.append(e))
        self.assertEqual(len(result['corners']),15)
        self.assertEqual(events[-1][:2],(15,15))
        self.assertTrue(result['fixed_hardware'])
        self.assertEqual(result['worst']['min_eta'],min(c['eta'] for c in result['corners'] if not c['skipped']))
        self.assertIn(result['worst_cases']['min_eta']['id'],[c['id'] for c in result['corners']])
        with self.assertRaises(InterruptedError): corners(p,cancelled=lambda:True)
        with self.assertRaises(ValueError): corners(p,35,25)

    def test_comparison_independence(self):
        p=dict(DEFAULT_PARAMS); a=evaluate(p); saved=copy.deepcopy(a['p'])
        b=evaluate(dict(p,C_out=p['C_out']*2))
        r=compare(a,b)
        self.assertEqual(a['p'],saved)
        self.assertEqual(p,DEFAULT_PARAMS)
        self.assertTrue(r['same_requirements'])
        self.assertEqual([d['key'] for d in r['differences']],['C_out'])
        eta=next(m for m in r['metrics'] if m['key']=='eta')
        self.assertAlmostEqual(eta['delta'],(b['res']['eta']-a['res']['eta'])*100)

    def test_gui_config_api_alias(self):
        cfg=read_default_config(); cfg['topology']={'v':'FLYBACK-QR (准谐振反激)','u':''}
        self.assertEqual(load_spec(cfg)['topology'],'QR-FLYBACK')

    def test_dcm_flyback_not_failed_by_ccm_sizing(self):
        import main
        p=dict(DEFAULT_PARAMS,P_out=.4); res=compute_design(p)
        self.assertEqual(res['op']['mode'],'DCM')
        catalog=check_catalog(p,res)
        self.assertEqual(next(c for c in catalog if c['id']=='L_min')['state'],'na')
        strip=main.PowerSupplyAnalyzer._power_checks(res['op'],res['wf'],res,p)
        self.assertIn('不适用',strip)
        markdown=main.build_markdown_report(p,res['op'],res['wf'],res)
        self.assertIn('电感量与设计初选建议',markdown)
        self.assertIn('不适用',markdown)


class GUIChecks(unittest.TestCase):
    def setUp(self):
        import main
        self.main=main; self.root=tk.Tk(); self.root.withdraw()
        self.app=main.PowerSupplyAnalyzer(self.root)
        self.app._control_ready=True; self.assertTrue(self.app.update_all())

    def tearDown(self):
        self.app._closing=True; self.app._work_cancel.set()
        for key in ('update_timer','_font_timer','_initial_update_job','_control_warmup_job','_control_poll_job','_work_poll'):
            job=getattr(self.app,key,None)
            if job:
                try:self.root.after_cancel(job)
                except tk.TclError:pass
        self.root.destroy()

    def wait(self):
        deadline=time.monotonic()+20
        while self.app._work_running and time.monotonic()<deadline:
            self.root.update(); time.sleep(.02)
        self.assertFalse(self.app._work_running,'worker did not complete')

    def test_search_fold_and_catalog(self):
        a=self.app
        self.assertTrue(a._param_widgets['eta_guess'][1].grid_info())
        self.assertEqual(a.get_params()['eta_guess'], .93)
        saved=a._config_dict()
        a.set_param('eta_guess', .85)
        self.assertTrue(a.update_all())
        self.assertEqual(a._last['op']['eta_guess'], .85)
        modified=a._config_dict()
        self.assertEqual(decode_config(modified)['eta_guess'], .85)
        a._apply_config(saved)
        self.assertTrue(a.update_all())
        self.assertEqual(a._last['op']['eta_guess'], .93)
        self.assertEqual(a._current_spec()['KP'],DEFAULT_PARAMS['KP'])
        a.param_search.set('ESL')
        self.assertTrue(a._param_widgets['ESL'][1].grid_info())
        self.assertFalse(a._param_widgets['V_in_min'][1].grid_info())
        a.param_search.set(''); frame=a._param_sections['spec']
        a._fold_section(frame); self.assertFalse(a._param_widgets['V_in_min'][1].grid_info())
        a._fold_section(frame); self.assertTrue(a._param_widgets['V_in_min'][1].grid_info())
        self.assertFalse(a._param_widgets['V_in'][1].grid_info())
        # Loop checks are now completed on demand. Compare the full API
        # catalogue after entering review, not the topology's pending summary.
        a.nb.select(a.tab_review)
        a._refresh_visible_tab()
        self.assertEqual(len(a.review_tree.get_children()),len(a._last['checks']))
        r=run_design(a._current_spec()); self.assertEqual(r['checks'],a._last['checks'])
        a.params['L'].set(-1)
        self.assertFalse(a.update_all())
        self.assertFalse(a._snapshot_valid); self.assertFalse(a.review_tree.get_children())

    def test_real_background_workflows(self):
        a=self.app
        with patch.object(self.main.messagebox,'showerror') as error:
            a._run_corners_ui(); self.wait()
            self.assertFalse(error.called,error.call_args)
            self.assertEqual(len(a.corner_tree.get_children()),5)  # legacy scalar -> equal min/max
            a.schedule_update()  # unchanged UI resize must not discard analysis
            self.assertIsNotNone(a._corner_result)
            a.corner_lo.set(26); self.assertIsNone(a._corner_result)
            a._capture_baseline(); self.wait()
            self.assertIsNotNone(a._baseline)
            a.set_param('C_out',a.get_param('C_out')*2)
            a._compare_ui(False); self.wait()
            self.assertIsNotNone(a._comparison)
            self.assertFalse(error.called,error.call_args)
            self.assertEqual(len(a.fig_compare.axes),2)
            a.set_param('P_out',39)
            self.assertIsNone(a._comparison); self.assertIsNotNone(a._baseline)

    def test_export_valid_and_stale_workflow_data(self):
        a=self.app
        with patch.object(self.main.messagebox,'showerror') as error:
            a._capture_baseline(); self.wait()
            a._compare_ui(False); self.wait()
            a._run_corners_ui(); self.wait()
            self.assertFalse(error.called,error.call_args)
            expected_corners=a._corner_result; expected_compare=a._comparison
            with patch.object(self.main.filedialog,'asksaveasfilename',return_value='_tmp_upgrade_qa/export_contract.docx'), \
                    patch.object(self.main.messagebox,'showinfo'), \
                    patch('input_range_report.export_input_range_docx',return_value={
                        'figure_count':22,'check_count':26,'successful_cases':2,
                        'failed_cases':[],'incomplete':False}) as exporter:
                a.export_report()
                self.assertIs(exporter.call_args.kwargs['corners'],expected_corners)
                self.assertIs(exporter.call_args.kwargs['comparison'],expected_compare)
                a.corner_lo.set(26)
                a.export_report()
                self.assertIsNone(exporter.call_args.kwargs['corners'])
                self.assertIs(exporter.call_args.kwargs['comparison'],expected_compare)
                a.set_param('P_out',39)
                a.export_report()
                self.assertIsNone(exporter.call_args.kwargs['corners'])
                self.assertIsNone(exporter.call_args.kwargs['comparison'])
            self.assertFalse(error.called,error.call_args)

    def test_thermal_label_uses_shared_threshold(self):
        a=self.app; a.params['temp_rise_limit'].set(20)
        self.assertTrue(a.update_all())
        a._update_mag(a._last['op'],a._last['p'],a._last['res'],a._last['wf'])
        self.assertIn('20 K',a.mag_check.get())
        self.assertNotIn('40K',a.mag_check.get())
        a.params['temp_rise_limit'].set(100)
        self.assertTrue(a.update_all())
        a._update_mag(a._last['op'],a._last['p'],a._last['res'],a._last['wf'])
        self.assertIn('100 K',a.mag_check.get())
        self.assertEqual(next(c for c in a._last['checks'] if c['id']=='temp_rise')['state'],'pass')


if __name__=='__main__':unittest.main(verbosity=2)
