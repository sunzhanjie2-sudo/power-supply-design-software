"""Specification sizing, verification and interchange through the normal engine."""
import copy
import json
import math
from pathlib import Path
import sys
import unittest
from zipfile import ZipFile
from xml.etree import ElementTree as ET

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from runtime_resources import configure_numeric_threads
configure_numeric_threads()
from design_engine.initial_design import form_options, generate
from design_engine.service import calculate
from design_engine.sizing_basis import DOCUMENT, MODES, SCOPE, SOURCES
from app_resources import resource_path


class InitialDesign(unittest.TestCase):
    def test_frozen_draft_matches_normal_engine(self):
        from compensation_report import compensation_snapshot
        for mode in MODES:
            with self.subTest(mode=mode):
                p=generate(dict(control_mode=mode,imin=1))
                b=p['__auto_design_basis']
                self.assertTrue(b['model_ok'])
                self.assertEqual(len(b['corners']),4)
                self.assertAlmostEqual(b['rules']['L_min'],240e-6)
                self.assertAlmostEqual(p['L'],270e-6)
                self.assertGreaterEqual(p['output_capacitors'][0]['C'],b['rules']['C_out_step'])
                self.assertGreater(b['requirements']['input_bank_ccm_rms_bound'],
                                   max(r['rms_in'] for r in b['corners']))
                self.assertEqual(b['requirements']['cap_rms']['input'],[b['requirements']['input_bank_ccm_rms_bound']])
                self.assertEqual(p['inductor_rated_current'],0)
                raw=json.loads(json.dumps(p,allow_nan=False))
                bundle=calculate(raw,analysis='endpoints',include_cross_regulation=False).runtime_bundle()
                for case in bundle['cases']:
                    q=case['p']
                    r=next(row for row in b['corners'] if row['vin']==case['voltage'] and row['current']==2)
                    for k in ('L','inductor_dcr','Rs','input_capacitors','output_capacitors','KP','fz1','fp1'):
                        self.assertEqual(p[k],q[k])
                    self.assertIsNone(case['error'])
                    self.assertAlmostEqual(case['result']['wf']['ripple_pp'],r['ripple'],places=9)
                    self.assertAlmostEqual(case['result']['loop']['min_pm'],r['loop']['pm'],places=5)
                    self.assertTrue(compensation_snapshot(q,case['result']['op'],p['__comp'])['buildable'])

    def test_locked_banks_do_not_silently_change(self):
        pins=dict(L=330e-6,inductor_dcr=.035,input_capacitors=[dict(C=1e-6,ESR=.2,ESL=0.)],
                  output_capacitors=[dict(C=100e-6,ESR=.022,ESL=1e-9),dict(C=100e-6,ESR=.025,ESL=2e-9)])
        inp=dict(locked=pins,imin=1.)
        before=copy.deepcopy(inp)
        p=generate(inp)
        self.assertEqual(inp,before)
        for key in pins:
            self.assertEqual(p[key],pins[key])
        self.assertFalse(p['__auto_design_basis']['model_ok'])
        issues=str(p['__auto_design_basis']['corners'])
        self.assertIn('输入电容组纹波',issues)
        self.assertIn('DCR 超出',issues)
        self.assertEqual(len(p['__auto_design_basis']['requirements']['cap_rms']['output']),2)

    def test_no_load_light_load_and_equal_inputs(self):
        for current in (0.,.04):
            p=generate(dict(imin=current,vin_max=18.))
            b=p['__auto_design_basis']
            self.assertEqual(len(b['corners']),2)
            self.assertFalse(b['model_ok'])
            self.assertNotIn('loop',b['corners'][1])
            self.assertTrue(b['corners'][1]['issues'])
        p=generate(dict(vin_max=18.,iout=2.5,imin=None))
        self.assertEqual(len(p['__auto_design_basis']['corners']),1)
        self.assertEqual(p['P_out'],30.)

    def test_invalid_and_cancelled(self):
        from calculation_scheduler import CalculationCancelled
        for s in [dict(vin_min=34.),dict(vout=16.5),dict(pm=float('nan')),dict(imin=3.),
                  dict(locked={'L':0}),dict(fs=5000.)] + [dict(topology=t) for t in SCOPE if t not in ('BUCK','BOOST','FLYBACK')]:
            with self.subTest(s=s), self.assertRaises(ValueError): generate(s)
        with self.assertRaises(CalculationCancelled):generate({},cancelled=lambda:True)

    def test_boost_power_stage_five_points_and_roundtrip(self):
        cfg=generate(dict(topology='BOOST',imin=.5))
        b=cfg['__auto_design_basis']
        self.assertEqual(cfg['control_mode'],'Peak Current Mode')
        self.assertEqual(cfg['spice_config']['niso_profile'],3)
        self.assertTrue(b['model_ok'])
        self.assertEqual(len(b['corners']),5)
        self.assertAlmostEqual(cfg['L'],39e-6)
        self.assertAlmostEqual(b['rules']['L_min'],37.5e-6)
        self.assertAlmostEqual(b['rules']['input_current_design'],24/(.9*9))
        self.assertAlmostEqual(b['rules']['C_out_charge'],(.6625*1)/(.12*200000))
        witness,=[r for r in b['corners'] if r.get('interior_ripple')]
        self.assertAlmostEqual(witness['vin'],24/(2*.9))
        self.assertEqual(witness['current'],1.)
        self.assertAlmostEqual(b['rules']['cs_min'],.45)
        self.assertAlmostEqual(cfg['Rs'],.082)
        decoded=json.loads(json.dumps(cfg,allow_nan=False))
        run=calculate(decoded,analysis='endpoints',include_cross_regulation=False)
        for case in run.runtime_bundle()['cases']:
            self.assertIsNone(case['error'])
            p, result = case['p'],case['result']
            row=next(r for r in b['corners'] if r['vin']==case['voltage'] and r['current']==1.)
            self.assertAlmostEqual(row['ripple'],result['wf']['ripple_pp'])
            self.assertAlmostEqual(row['loop']['pm'],result['loop']['min_pm'])
            self.assertAlmostEqual(row['rhp_hz'],24*(1-row['duty'])**2/(2*math.pi*cfg['L']))
            for key in ('L','Rs','inductor_dcr','KP','fz1','fp1','input_capacitors','output_capacitors'):
                self.assertEqual(p[key],cfg[key])
        for r in b['corners']:
            self.assertLess(r['inner_radius'],1)
            self.assertLessEqual(r['cs_with_margin'],.45)
            self.assertLessEqual(r['loop']['fc'],min(cfg['f_sw']/10,r['rhp_hz']/5))
        self.assertNotAlmostEqual(b['rules']['input_current_design'],cfg['P_out']/cfg['V_out'])
        self.assertGreater(b['requirements']['cap_rms']['output'][0],1.3)
        self.assertLess(b['requirements']['cap_rms']['input'][0],.3)
        cfg['input_capacitors'][0]['C']=1.
        self.assertNotEqual(cfg['input_capacitors'],b['selected']['input_capacitors'])

    def test_boost_comp_pin_network_and_reverse(self):
        from compensation_report import compensation_snapshot
        import comp_design as comp
        p=generate(dict(topology='BOOST',imin=.5))
        st=p['__comp']
        net=compensation_snapshot(p,dict(V_out=p['V_out']),st)
        parts=net['parts']
        keys=('R1','R2','R3','C1','C2','C3')
        actual=comp.opamp_type3_eval(*(parts[k] for k in keys))
        self.assertTrue(net['buildable'])
        self.assertAlmostEqual(actual['KP'],3*p['KP'])
        self.assertAlmostEqual(parts['R_lower']*24/(parts['R1']+parts['R_lower']),1.25)
        reverse=dict(st,dir='rev',vars={k:dict(v=parts[k],u='') for k in keys})
        read=compensation_snapshot(p,dict(V_out=24),reverse)
        for k in ('KP','wz1','wp1'):
            self.assertAlmostEqual(read['realized'][k],net['targets'][k])
        self.assertEqual(p['__auto_design_basis']['compensation_pin']['command_gain'],1/3)

    def test_boost_limits_locks_and_light_load(self):
        for args in (dict(vout=12),dict(control_mode='Voltage Mode'),dict(eta_guess=1.2),
                     dict(fs=3e6), dict(vin_min=6,vout=80)):
            with self.subTest(args=args), self.assertRaises(ValueError):
                generate(dict(topology='BOOST',**args))
        for imin in (0.,.03):
            p=generate(dict(topology='BOOST',imin=imin,vin_max=9.))
            rows=p['__auto_design_basis']['corners']
            self.assertEqual(len(rows),2)
            self.assertTrue(rows[1]['issues'])
            self.assertNotIn('loop',rows[1])
        pins=dict(L=47e-6,inductor_dcr=.027,output_capacitors=[dict(C=4.7e-6,ESR=.09,ESL=2e-9)])
        p=generate(dict(topology='BOOST',imin=.5,locked=pins))
        for key in pins:self.assertEqual(p[key],pins[key])
        self.assertFalse(p['__auto_design_basis']['model_ok'])
        self.assertIn('输出纹波超限',str(p['__auto_design_basis']['corners']))
        options=form_options(p)
        self.assertEqual(options['topology'],'BOOST')
        self.assertEqual(tuple(options['modes']),('Peak Current Mode',))
        self.assertEqual(options['locks']['output_capacitors'],pins['output_capacitors'])
        self.assertEqual(options['variants']['BUCK']['locks'],{})
        self.assertEqual(options['values']['eta_guess'],90.)
        # A higher step-up ratio at low line requires extra ramp.
        p=generate(dict(topology='BOOST',vin_min=6.,vin_max=12.,vout=36.))
        self.assertGreater(p['spice_config']['niso_lm_cs_resistor'],0.)
        self.assertTrue(p['__auto_design_basis']['model_ok'])

    def test_manual_math_links_and_topology_coverage(self):
        from power_stage import TOPOLOGIES
        self.assertEqual(set(SCOPE),set(TOPOLOGIES))
        with ZipFile(resource_path(DOCUMENT)) as doc:
            xml=ET.fromstring(doc.read('word/document.xml'))
            links=ET.fromstring(doc.read('word/_rels/document.xml.rels'))
        self.assertTrue({url for _,_,url in SOURCES.values()}<={link.get('Target') for link in links})
        math={'m':'http://schemas.openxmlformats.org/officeDocument/2006/math'}
        self.assertGreaterEqual(len(xml.findall('.//m:oMath',math)),7)
        self.assertGreaterEqual(len(xml.findall('.//m:f',math)),6)

    def test_web_draft_download_and_config_roundtrip(self):
        from fastapi.testclient import TestClient
        from web_app.server import create_app
        with TestClient(create_app(testing=True)) as client:
            self.assertEqual(client.get('/api/auto-design-basis').status_code,403)
            client.headers['X-Power-Token']=client.get('/api/bootstrap').json()['token']
            opts=client.post('/api/initial-design/options',json={'spec':{}}).json()
            response=client.post('/api/initial-design',json={'spec':{'imin':opts['values']['imin']}})
            self.assertEqual(response.status_code,200,response.text[:250])
            p=response.json()['config']
            saved=client.post('/api/config',json={'spec':p}).json()
            self.assertEqual(saved['__auto_design_basis'],p['__auto_design_basis'])
            self.assertEqual(client.get('/api/auto-design-basis').content,resource_path(DOCUMENT).read_bytes())
            req={'topology':'BOOST','imin':opts['variants']['BOOST']['values']['imin']}
            response=client.post('/api/initial-design',json={'spec':req})
            self.assertEqual(response.status_code,200,response.text[:200])
            boost=response.json()['config']
            self.assertEqual(boost['topology'],'BOOST')
            self.assertTrue(boost['__auto_design_basis']['model_ok'])
            self.assertEqual(client.post('/api/config',json={'spec':boost}).json()['__comp'],boost['__comp'])
            self.assertEqual(client.post('/api/initial-design',json={'spec':{'topology':'BUCK-BOOST'}}).status_code,422)


if __name__=='__main__':
    unittest.main(verbosity=2)
