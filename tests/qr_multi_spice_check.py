"""Multi-output QR retains every winding and measures the chosen feedback rail."""
import copy
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

import numpy as np

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from design_engine.specification import load_spec
from design_engine.service import calculate_parameters
from spice_export import project_files
from qr_spice_export import _multi_schematic
from qr_spice_analysis import startup_gate_current
from spice_studies import qr_measured_point


def spec(feedback=1):
    p=load_spec(json.loads((ROOT/'examples/90W_QR_L6565_300V_TUNED.json').read_text('utf-8')))
    p.update(V_in=300.,V_in_min=300.,V_in_max=300.,feedback_output=feedback,
             outputs=[dict(V_out=60.,P_out=92.,P_out_min=92.,Ns=30,name='主路'),
                      dict(V_out=13.,P_out=.1,P_out_min=.1,Ns=7,name='辅助')])
    if feedback==2:p.update(N=60/7,Ns=7,V_out=13.)
    return p


class MultiQRSpiceChecks(unittest.TestCase):
    def files(self,feedback=1):
        p=spec(feedback)
        run=calculate_parameters(p,analysis='endpoints',include_loop=False,include_cross_regulation=False)
        return p,project_files(p,bundle=run.runtime_bundle())

    def test_independent_auxiliary_power_branch_and_event_controller_are_exported(self):
        p,files=self.files()
        meta=json.loads(files['manifest.json'])
        self.assertEqual(meta['qr']['output_count'],2)
        self.assertEqual(meta['resolved_controller']['FB_SELECT'],1)
        stage=files['power_stage.inc'].decode('ascii')
        for name in ('LS1 ','LS2 ','XD_O1 ','XD_O2 ','BLOAD1 ','BLOAD2 '):
            self.assertIn('\n'+name, '\n'+stage)
        self.assertIn('GQR_CTRL',stage)
        self.assertNotIn('GFLY_CTRL2',stage)
        self.assertEqual(len(meta['hardware']['windings']),2)
        self.assertEqual(len(meta['coupling']['k']),3)
        self.assertIn('K_1_2 LS1 LS2',files['coupling.inc'].decode())
        native=files['Flyback.asc'].decode('utf-8')
        for symbol in ('InstName LS1','InstName LS2','InstName D_O2','InstName LOAD2',
                       'SYMBOL GQR_CTRL','SYMATTR InstName ZCD','FLAG 208 800 zcd'):
            self.assertIn(symbol,native)
        self.assertNotIn('SYMBOL GFLY_CTRL2',native)
        self.assertIn('I(LS2)',files['Flyback.plt'].decode('utf-16le'))
        self.assertIn('V(out2,sgnd)',files['Flyback.plt'].decode('utf-16le'))

    def test_feedback_two_is_retained_in_netlist_and_metadata(self):
        _,files=self.files(feedback=2)
        meta=json.loads(files['manifest.json'])
        self.assertEqual(meta['feedback_output'],2)
        self.assertEqual(meta['resolved_controller']['FB_SELECT'],2)
        self.assertEqual(meta['qr']['feedback_output'],2)
        self.assertIn('SEL={FB_SELECT}',files['power_stage.inc'].decode('ascii'))

    def test_six_output_native_sheet_keeps_all_power_parts(self):
        native=_multi_schematic((ROOT/'resources/spice/Flyback_6.asc').read_bytes(),6).decode()
        self.assertEqual(native.count('SYMBOL GQR_CTRL'),1)
        for n in range(1,7):
            self.assertIn(f'SYMATTR InstName LS{n}\n',native)
            self.assertIn(f'SYMATTR InstName LOAD{n}\n',native)
        self.assertIn('SYMATTR Value {QR_VCC}',native)

    def test_measured_point_uses_selected_rail_and_retains_all_rail_measurements(self):
        p=spec(2)
        measurements={'input_voltage':300.}
        for n in (1,2):
            measurements.update({f'out{n}_before':60./n,
                f'out{n}_cap_before':60./n+.7,f'out{n}_winding_avg':.2/n})
        cycles=[dict(peak=2.,period_s=20e-6) for _ in range(8)]
        record=dict(nominal_comparable=True,periodicity=dict(stable=True,cycles=cycles),measurements=measurements)
        point=qr_measured_point(dict(p=p),record)
        self.assertEqual(point['vout'],30.)
        self.assertEqual(point['vcap'],30.7)
        self.assertEqual(point['iout'],.1)
        self.assertEqual(point['rail_currents'],[.2,.1])
        self.assertEqual(point['rail_voltages'],[60.,30.])

    def test_startup_check_does_not_assume_feedback_is_ls1(self):
        class Raw:
            time=np.arange(0,30e-6,10e-9)
            def trace(self,name):
                t=self.time
                return {'v(ss)':np.minimum(t/15e-6,1.),'v(sense)':np.zeros_like(t),
                    'v(gate)':np.where(((t%10e-6)>=2e-6)&((t%10e-6)<4e-6),10.,0.),
                    'i(ls1)':np.ones_like(t)*2.,'i(ls2)':np.ones_like(t)*.07}[name]
        result=startup_gate_current(Raw(),28e-6,10.,output_count=2,feedback_output=2)
        self.assertTrue(result['all_windings_observed'])
        self.assertEqual(result['max_pre_current_a'],.07)
        self.assertEqual(result['windings']['OUT1']['max_pre_current_a'],2.)
        self.assertEqual(result['windings']['OUT2']['max_pre_current_a'],.07)

    def test_cross_uses_actual_qr_edges_and_requires_independent_matrix_prediction(self):
        from spice_studies import corner_plan,run_cross
        from spice_export import normalize_settings
        p=spec();p['outputs'][0]['P_out_min']=46.;p['outputs'][1]['P_out_min']=.05
        run=calculate_parameters(p,analysis='endpoints',include_loop=False,include_cross_regulation=False)
        case=run.runtime_bundle()['cases'][0]
        files=project_files(p,bundle=run.runtime_bundle());meta=json.loads(files['manifest.json'])
        from isolated_outputs import output_specs
        rails=output_specs(case['p']);settings=normalize_settings(meta['settings'])
        settings.update(cross_enabled=1.,cross_hold_ms=20.)
        powers,_=corner_plan(rails,settings['cross_mode'])
        stop=max(settings['step_ms']*1e-3,.008)+(len(powers)-1)*settings['cross_hold_ms']*1e-3
        measured={}
        for k in range(len(powers)):
            for n,value in enumerate((60.,13.),1):
                measured[f'cross{k}_out{n}']=measured[f'cross{k}_early{n}']=value
        class Raw:
            time=np.linspace(0,stop,1000)
            def __init__(self,_path):pass
            def trace(self,_name):return np.zeros_like(self.time)
            def samples(self,_names,_a,_b,_points):return {'time':[0.,stop]}
            def close(self):pass
        tmp=ROOT/'artifacts/qr-joint-multi-20261107/tmp';tmp.mkdir(parents=True,exist_ok=True)
        with tempfile.TemporaryDirectory(dir=tmp) as directory, \
             patch('spice_runtime.TransientRaw',Raw), \
             patch('spice_runtime.read_log',return_value=(measured,[],[],[])), \
             patch('qr_spice_analysis.cycle_quality',return_value={'stable':True,'cycles':[]}) as quality, \
             patch('spice_studies.cycle_quality',side_effect=AssertionError('fixed-clock path used')):
            result=run_cross(files,case,meta,settings,Path(directory),lambda *_: .01)
        self.assertIsNone(result['error'])
        self.assertEqual(quality.call_count,len(powers))
        self.assertEqual(len(result['records']),len(powers))
        for record in result['records']:
            self.assertIsNone(record['design'])
            self.assertIn('名义匝比',record['design_error'])
            self.assertTrue(record['settled'])
        self.assertTrue(result['simulation_complete'])
        self.assertFalse(result['design_complete'])
        self.assertFalse(result['complete'])


if __name__=='__main__':unittest.main(verbosity=2)
