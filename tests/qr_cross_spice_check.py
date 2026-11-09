"""QR corner evidence contracts; synthetic RAW fixtures are not simulations."""
import copy
import json
import math
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

import numpy as np

ROOT=Path(__file__).resolve().parents[1]
sys.path[:0]=[str(ROOT),str(ROOT/'tests')]
from runtime_resources import configure_numeric_threads
configure_numeric_threads()
from qr_multi_spice_check import spec
from design_engine.service import calculate_parameters
from spice_export import project_files,normalize_settings
from spice_studies import corner_plan,finalize_cross,matched_parameters,run_cross
from isolated_outputs import output_specs


class QRCornerContracts(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.p=spec()
        cls.p['outputs'][0]['P_out_min']=46.
        cls.p['outputs'][1]['P_out_min']=.05
        run=calculate_parameters(cls.p,analysis='endpoints',include_loop=False,include_cross_regulation=False)
        cls.case=run.runtime_bundle()['cases'][0]
        cls.files=project_files(cls.p,bundle=run.runtime_bundle())
        cls.meta=json.loads(cls.files['manifest.json'])

    def exercise(self,*,stable=True,valid_design=True):
        case=copy.deepcopy(self.case)
        settings=normalize_settings(self.meta['settings'])
        settings.update(cross_enabled=1.,cross_hold_ms=20.)
        rails=output_specs(case['p']);powers,_=corner_plan(rails,settings['cross_mode'])
        stop=max(settings['step_ms']*1e-3,.008)+(len(powers)-1)*settings['cross_hold_ms']*1e-3
        measured={f'cross{k}_{prefix}{n}':value for k in range(len(powers))
            for prefix in ('out','early') for n,value in enumerate((60.,13.),1)}
        class Raw:
            time=np.linspace(0,stop,1000)
            def __init__(self,_path):pass
            def trace(self,_name):return np.zeros_like(self.time)
            def samples(self,_names,_a,_b,_points):return {'time':[0.,stop]}
            def close(self):pass
        # The solver itself is independently tested numerically. Here the
        # fixture proves this branch consumes its verified contract, rather
        # than publishing nominal ratios or treating mocked data as LTspice.
        model=dict(converged=valid_design,normalized_residual=1e-10,
                   timing_policy='test-only-event-contract',valley_index=0,
                   assumptions='unit fixture, not a numerical physics result')
        op=dict(D=.3,f_sw=43000.,coupled_solution={} if valid_design else None,
                qr_coupled_model=model,
                output_ops=[dict(V_out=60.,mode='DCM'),dict(V_out=12.75,mode='DCM')])
        q=matched_parameters(case,self.meta['resolved_controller'])
        q['coupling_config']=dict(enabled=True)
        deck=[]
        def execute(folder,*_):
            deck.append((folder/'analysis.inc').read_text('ascii'))
            return .01
        with tempfile.TemporaryDirectory(dir=ROOT/'artifacts') as td, \
             patch('spice_studies.matched_parameters',return_value=q), \
             patch('isolated_outputs.output_specs',return_value=copy.deepcopy(rails)), \
             patch('power_stage.compute_operating_point',return_value=op) as solve, \
             patch('spice_runtime.TransientRaw',Raw), \
             patch('spice_runtime.read_log',return_value=(measured,[],[],[])), \
             patch('qr_spice_analysis.cycle_quality',return_value=dict(stable=stable,reason='fixture-repeatability')) as quality, \
             patch('spice_studies.cycle_quality',side_effect=AssertionError('fixed-clock quality path')), \
             patch('spice_studies.retry_cross_corners') as retry:
            result=run_cross(self.files,case,self.meta,settings,Path(td),execute)
        self.assertEqual(quality.call_count,len(powers))
        self.assertEqual(solve.call_count,len(powers))
        self.assertIn('V(drain)',deck[0],'actual QR cycle check requires its Vds probe')
        return result

    def test_verified_variable_period_solution_enters_design_column(self):
        result=self.exercise()
        self.assertTrue(result['complete'])
        self.assertTrue(result['simulation_complete'])
        self.assertTrue(result['design_complete'])
        for row in result['records']:
            self.assertEqual(row['design'],[60.,12.75])
            self.assertEqual(row['design_point']['frequency_hz'],43000.)
            self.assertEqual(row['design_point']['timing_policy'],'test-only-event-contract')
        self.assertIsNotNone(result['summary']['design'][1]['cross_only_pct'])

    def test_qr_nonrepeatable_corner_cannot_enter_simulation_envelope(self):
        result=self.exercise(stable=False)
        self.assertTrue(result['design_complete'])
        self.assertFalse(result['simulation_complete'])
        self.assertFalse(result['complete'])
        self.assertTrue(all(row['V_min'] is None for row in result['summary']['simulation']))
        self.assertTrue(all('可重复' in row['error'] for row in result['records']))

    def test_unverified_model_does_not_substitute_nominal_ratio(self):
        result=self.exercise(valid_design=False)
        self.assertTrue(result['simulation_complete'])
        self.assertFalse(result['design_complete'])
        self.assertTrue(all(row['design'] is None for row in result['records']))
        self.assertTrue(all('不' in row['design_error'] for row in result['records']))

    def test_matching_keeps_ceiling_and_binds_exported_qr_timing(self):
        controller=dict(self.meta['resolved_controller'],FSW=40000.,FSW_LIMIT=100000.,
                        TOFFMIN=4e-6,TOFFLIGHT=22e-6,ZDELAY=210e-9,Q_COSS=470e-12)
        q=matched_parameters(self.case,controller)
        self.assertEqual(q['f_sw'],100000.)
        self.assertEqual(q['Coss'],470e-12)
        self.assertAlmostEqual(q['spice_config']['qr_off_min_us'],4.)
        self.assertAlmostEqual(q['spice_config']['qr_off_light_us'],22.)
        self.assertAlmostEqual(q['spice_config']['qr_zcd_delay_ns'],210.)

    def test_actual_exported_rcd_cards_are_frozen_for_load_corners(self):
        import re
        values=self.meta['resolved_controller']
        cards=self.files['design_params.inc'].decode('ascii')
        for key in ('R_SN1','C_SN1','D_SN1_EN'):
            self.assertEqual(values[key],float(re.search(r'(?m)^\.param '+key+r'=([^\s]+)',cards)[1]))
        q=matched_parameters(self.case,values)
        self.assertEqual(q['_qr_rcd_hardware'],dict(R_ohm=values['R_SN1'],C_F=values['C_SN1'],source='spice-export-parameters'))
        with self.assertRaisesRegex(ValueError,'有限正数'):
            matched_parameters(self.case,dict(values,R_SN1=float('nan')))

    def test_finalize_requires_every_planned_corner_and_finite_nonzero_load(self):
        rails=[dict(id=1,name='OUT1',V_out=60.,P_out=92.,P_out_min=46.),
               dict(id=2,name='OUT2',V_out=13.,P_out=.1,P_out_min=.05)]
        def record(i,powers=(92.,.1),design=(60.,13.)):
            return dict(id=str(i),V_in=300.,powers=list(powers),settled=True,
                        simulation=[60.,13.],design=list(design))
        result=dict(total_cases=4,varied_outputs=[1,2],records=[record(1)])
        finalize_cross(result,rails,1)
        self.assertFalse(result['simulation_complete'])
        self.assertFalse(result['design_complete'])
        self.assertTrue(all(not r['complete'] for rows in result['summary'].values() for r in rows))
        result['records']=[record(i) for i in range(4)]
        result['records'][1]['design']=[60.,float('nan')]
        result['records'][2]['powers']=[92.,0.]
        finalize_cross(result,rails,1)
        self.assertFalse(result['complete'])
        self.assertEqual(result['design_valid_cases'],2)
        self.assertEqual(result['settled_cases'],3)


if __name__=='__main__':unittest.main(verbosity=2)
