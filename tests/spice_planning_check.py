"""Scheduling, honest coverage, cancellation-safe reuse and failure gating."""
import copy
import json
import os
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from runtime_resources import configure_numeric_threads
configure_numeric_threads()
from design_engine.service import calculate_parameters
from design_engine.specification import load_spec
from spice_export import normalize_settings,project_files
from spice_planning import execution_plan,recommend_settings
from spice_result_cache import NominalCache,cache_key
from spice_runtime import compare_design,_simulate_nominal


class PlanningChecks(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.p=load_spec(json.loads((ROOT/'examples/40W_CCM_3OUT_FLYBACK.json').read_text(encoding='utf-8')))
        cls.design_run=calculate_parameters(cls.p,analysis='endpoints',include_loop=False,include_cross_regulation=False)

    def test_profiles_preserve_electrical_model_and_resolution(self):
        s=normalize_settings();quick=recommend_settings(self.p,s,'quick')
        self.assertEqual((quick['step_ms'],quick['stop_ms']),(12.,16.))
        changed={k for k in s if s[k]!=quick[k]}
        self.assertEqual(changed,{'step_ms','stop_ms','fra_enabled','cross_enabled'})
        plan=execution_plan(self.p,quick)
        self.assertEqual(plan['voltages'],[20.,30.]);self.assertEqual(len(plan['stages']),2)
        self.assertIn('环路 FRA',plan['skipped'])
        full=recommend_settings(self.p,quick,'full');plan=execution_plan(self.p,full)
        self.assertEqual(len(plan['stages']),6);self.assertEqual(plan['cross_count'],8)
        self.assertEqual(full['fra_cycles'],s['fra_cycles'])
        # The suggestion cannot shrink a deliberate long observation window.
        long=normalize_settings(dict(step_ms=200,stop_ms=400))
        self.assertEqual(recommend_settings(self.p,long)['stop_ms'],400)

    def test_single_input_and_output_are_not_duplicate_jobs(self):
        p=copy.deepcopy(self.p);p.update(V_in_min=30,V_in_max=30,outputs=[])
        plan=execution_plan(p,normalize_settings())
        self.assertEqual(len(plan['stages']),2)
        self.assertEqual(plan['output_count'],1)
        self.assertFalse(plan['cross_enabled'])

    def test_qr_equal_load_bounds_do_not_invent_cross_regulation_corners(self):
        p=copy.deepcopy(self.p);p['topology']='QR-FLYBACK'
        for rail in p['outputs']:rail['P_out_min']=rail['P_out']
        saved=copy.deepcopy(p)
        full=recommend_settings(p,normalize_settings(),'full')
        self.assertEqual(p,saved)
        plan=execution_plan(p,full)
        self.assertFalse(plan['cross_enabled'])
        self.assertFalse(any(s['kind']=='cross' for s in plan['stages']))
        manual=execution_plan(p,dict(full,cross_enabled=1.))
        self.assertTrue(manual['cross_requested'])
        self.assertFalse(manual['cross_enabled'])
        self.assertIn('最小功耗',manual['cross_skip_reason'])
        p['outputs'][1]['P_out_min']=p['outputs'][1]['P_out']/10
        varied=recommend_settings(p,full,'full')
        self.assertTrue(execution_plan(p,varied)['cross_enabled'])

    def test_key_tracks_circuit_simulator_calculation_and_tolerances(self):
        bundle=self.design_run.runtime_bundle();case=bundle['cases'][0]
        files=project_files(bundle['base_spec'],bundle=bundle);s=normalize_settings()
        with tempfile.TemporaryDirectory(dir=ROOT/'artifacts') as td:
            exe=Path(td)/'simulator.exe';exe.write_bytes(b'example-version')
            key=lambda f=files,c=case,settings=s:cache_key(f,c,settings,exe,[_simulate_nominal])
            original=key()
            self.assertEqual(key(settings=dict(s,fra_enabled=0,cross_enabled=0)),original)
            self.assertNotEqual(key(settings=dict(s,cycle_tolerance_pct=6)),original)
            self.assertNotEqual(key(f=dict(files,**{'power_stage.inc':b'changed device'})),original)
            changed=copy.deepcopy(case);changed['result']['op']['D']*=1.01
            self.assertNotEqual(key(c=changed),original)
            exe.write_bytes(b'new-version-2');self.assertNotEqual(key(),original)

    def test_helper_module_changes_invalidate_evidence(self):
        from types import SimpleNamespace
        bundle=self.design_run.runtime_bundle();case=bundle['cases'][0]
        files=project_files(bundle['base_spec'],bundle=bundle);s=normalize_settings()
        with tempfile.TemporaryDirectory(dir=ROOT/'artifacts') as td:
            exe=Path(td)/'simulator.exe';exe.write_bytes(b'version')
            def key():return cache_key(files,case,s,exe,[_simulate_nominal])
            with patch('spice_result_cache.importlib.util.find_spec') as finder:
                finder.return_value=SimpleNamespace(loader=SimpleNamespace(get_code=lambda _:compile('x=1','helper.py','exec')))
                original=key()
                finder.return_value=SimpleNamespace(loader=SimpleNamespace(get_code=lambda _:compile('x=2','helper.py','exec')))
                self.assertNotEqual(key(),original)

    def test_cache_rejects_failures_corruption_and_bounds_storage(self):
        valid=dict(complete=True,nominal_comparable=True,fault_test=False,measurements={},periodicity={},
                   startup={},switching={},branches=[],source_hashes={})
        with tempfile.TemporaryDirectory(dir=ROOT/'artifacts') as td,patch('spice_result_cache.MAX_ENTRIES',2):
            cache=NominalCache(td)
            cache.store('failed',dict(valid,complete=False),b'bad');self.assertIsNone(cache.load('failed'))
            cache.store('unsettled',dict(valid,nominal_comparable=False),b'bad');self.assertIsNone(cache.load('unsettled'))
            for i in range(3):cache.store(str(i),valid,b'actual log')
            self.assertEqual(len(list(Path(td).glob('*.zip'))),2)
            result=cache.load('2');self.assertEqual(result[1],b'actual log')
            result[0]['measurements']['changed']=True
            self.assertEqual(cache.load('2')[0]['measurements'],{})
            (Path(td)/'2.zip').write_bytes(b'broken');self.assertIsNone(cache.load('2'))

    def test_quick_to_full_reuses_same_nominal_design(self):
        with tempfile.TemporaryDirectory(dir=ROOT/'artifacts') as td:
            exe=Path(td)/'simulator.exe';exe.write_bytes(b'version')
            keys=[]
            for scope in ('quick','full'):
                p=copy.deepcopy(self.p);p['spice_config']=recommend_settings(p,p['spice_config'],scope)
                bundle=calculate_parameters(p,analysis='endpoints',include_loop=False,include_cross_regulation=False).runtime_bundle()
                files=project_files(bundle['base_spec'],bundle=bundle)
                keys.append(cache_key(files,bundle['cases'][0],p['spice_config'],exe,[_simulate_nominal]))
            self.assertEqual(keys[0],keys[1])

    def test_cache_write_permission_error_is_nonblocking(self):
        valid=dict(complete=True,nominal_comparable=True,fault_test=False)
        with tempfile.TemporaryDirectory(dir=ROOT/'artifacts') as td,patch.object(Path,'open',side_effect=PermissionError('read only')):
            NominalCache(td).store('cannot-write',valid,b'log')

    def test_reused_qr_record_keeps_measured_fra_frequency_boundary(self):
        p=load_spec(json.loads((ROOT/'examples/90W_QR_L6565_300V.json').read_text(encoding='utf-8')))
        p['spice_config'].update(fra_enabled=1,cross_enabled=0,simulation_reuse=1,short_test=0)
        run=calculate_parameters(p,analysis='endpoints',include_loop=False,include_cross_regulation=False)
        cached=dict(complete=True,nominal_comparable=True,fault_test=False,
                    periodicity=dict(stable=True,frequency_min_hz=41000))
        observed=[]
        def fra(files,case,meta,*args,**kwargs):
            observed.append(meta.get('qr_measured_min_frequency_hz'))
            return dict(available=True)
        with tempfile.TemporaryDirectory(dir=ROOT/'artifacts') as td,\
             patch('spice_result_cache.NominalCache.load',return_value=(cached,b'unit test log','test')) ,\
             patch('spice_runtime._run') as simulate,\
             patch('spice_studies.run_fra',new=fra),patch('spice_studies.qr_measured_point',return_value={}),\
             patch('spice_comparison_report.write_report',side_effect=lambda p,e:Path(p).write_bytes(b'unit test report')):
            result=compare_design(run,Path(td)/'test.docx',executable=sys.executable)
            simulate.assert_not_called()
            self.assertEqual(observed,[41000])
            self.assertEqual(result['fra_successful'],1)

    def test_unsettled_nominal_does_not_start_expensive_studies(self):
        def unsuccessful(exe,folder,case,meta,s,record,cancelled,progress=None):
            record.update(complete=True,nominal_comparable=False,periodicity=dict(stable=False))
        with tempfile.TemporaryDirectory(dir=ROOT/'artifacts') as td,patch.dict(os.environ,POWER_DESIGN_SPICE_CACHE=td),\
             patch('spice_runtime._simulate_nominal',new=unsuccessful),\
             patch('spice_studies.run_fra') as fra,patch('spice_studies.run_cross') as cross,\
             patch('spice_comparison_report.write_report',side_effect=lambda p,e:Path(p).write_bytes(b'report')):
            result=compare_design(self.design_run,Path(td)/'test.docx',executable=sys.executable)
            fra.assert_not_called();cross.assert_not_called()
            self.assertTrue(result['incomplete']);self.assertEqual(result['cross_total'],2)
            self.assertEqual(result['cross_successful'],0)


if __name__=='__main__':unittest.main()
