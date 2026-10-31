"""Headless advanced Web parity checks, including the real owned worker."""
import copy
import json
from pathlib import Path
import sys
import tempfile
import time
import unittest
from concurrent.futures import Future
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from runtime_resources import configure_numeric_threads
configure_numeric_threads()
from web_app.actions import execute, validate_options
from web_app.metadata import bootstrap, read_example
from web_app.jobs import JobManager
from design_engine.service import calculate


def wait(manager, identity, operation=False, timeout=120):
    deadline = time.monotonic()+timeout
    while time.monotonic() < deadline:
        row = manager.operation(identity) if operation else manager.status(identity)
        if row['state'] in ('succeeded', 'failed', 'cancelled'):
            return row
        time.sleep(.03)
    raise AssertionError('Task timed out: '+identity)


class ActionChecks(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.directory = tempfile.TemporaryDirectory(prefix='web-actions-check-')
        cls.spec = bootstrap()['spec']
        cls.spec.update(V_in_min=24., V_in_max=40.)
        # A realizable four-corner reference is required to verify all four
        # networks; the shipped type-II example intentionally ignores fz2/fp2.
        cls.spec.update(controller_type='type3', KP=10000., fz1=100., fz2=1000., fp1=10000., fp2=100000.)
        cls.design_run = calculate(cls.spec, analysis='endpoints', include_cross_regulation=False)
        cls.original = cls.design_run.to_dict(include_details=False)

    @classmethod
    def tearDownClass(cls):
        cls.directory.cleanup()

    def action(self, action, options):
        path = Path(self.directory.name)/(self._testMethodName+action+'.png')
        result = execute(self.design_run, action, options, path)
        json.dumps(result, allow_nan=False)
        self.assertTrue(result['snapshot_unchanged'])
        self.assertEqual(self.design_run.to_dict(include_details=False), self.original)
        return result

    def test_options_are_bounded_and_reject_expression_paths(self):
        invalid = [
            ('tune', {'fc': float('nan')}), ('tune', {'run': 'anything'}),
            ('optimize', {'variables': [{}], 'bounds': [[1, 2]]}),
            ('optimize', {'variables': ['L'], 'bounds': [[1, 2]], 'maxiter': 100}),
            ('sweep', {'variable': '__import__', 'minimum': 1, 'maximum': 2}),
            ('sweep', {'variable': {}, 'minimum': 1, 'maximum': 2}),
            ('sweep', {'variable': 'L', 'minimum': 2, 'maximum': 1}),
            ('sweep', {'variable': 'L', 'minimum': 1, 'maximum': 2, 'points': 42}),
            ('corners', {'load_fracs': [0]}), ('loop_response', {'load_output': 7}),
            ('compensate', {'key': {}, 'inputs': {}}),
            ('compensate', {'inputs': {'file': 'C:/Windows/win.ini'}}),
            ('winding_preview', {'config': {'filename': 'x'}}),
        ]
        for action, opts in invalid:
            with self.subTest(action=action, opts=opts), self.assertRaises(ValueError):
                validate_options(action, opts)

    def test_tune_uses_actual_candidate_and_rejects_infeasible_target(self):
        result = self.action('tune', {'fc': 1000., 'pm': 60., 'controller_type': 'type2'})
        self.assertTrue(result['feasible'], result)
        self.assertGreaterEqual(result['achieved']['min_pm'], 59.)
        self.assertTrue(result['achieved']['closed_loop_stable'])
        self.assertEqual(result['spec_updates']['controller_type'], 'type2')
        rejected = self.action('tune', {'fc': 30000., 'pm': 170., 'controller_type': 'type2'})
        self.assertFalse(rejected['feasible'])
        self.assertFalse(rejected['spec_updates'])

    def test_four_compensation_networks_forward_reverse_and_reference(self):
        inputs = {
            'opamp3': dict(R1=10000., Vref=2.5),
            'gm3': dict(R2=10000., R1u=100000., gm=.002),
            'tl431nf': dict(R1=40000., R_LED=1000., CTR=1., Rpullup=20000., Copto=.1e-9),
            'tl431f': dict(R1=40000., CTR=1., Rpullup=20000., Copto=.1e-9),
        }
        from web_app.actions import _INPUTS
        for key, values in inputs.items():
            with self.subTest(network=key):
                result = self.action('compensate', dict(key=key, direction='fwd', inputs=values))
                self.assertTrue(result['has_chart'])
                self.assertTrue(Path(result['path']).read_bytes().startswith(b'\x89PNG'))
                reverse = {k: v for k, v in result['parts'].items() if k in _INPUTS[key]}
                # Forward warning paths may deliberately report a negative C2.
                # That is not an installable reverse input; use a real component.
                if reverse.get('C2', 0) < 0:
                    reverse['C2'] = 0.
                back = self.action('compensate', dict(key=key, direction='rev', inputs=reverse))
                self.assertAlmostEqual(back['realized']['KP'], result['realized']['KP'], places=6)
                self.assertIn('__comp', back['spec_updates'])
                self.assertEqual(len(back['checks']), 5)

    def test_sweep_and_target_match_desktop_values(self):
        from calculation_scheduler import calculate_optimization
        from optimizer import find_target
        options = dict(variable='f_sw', minimum=100000., maximum=400000., points=5, target_eta=.87)
        actual = self.action('find_target', options)
        p = self.design_run.runtime_bundle()['cases'][0]['p']
        p = {k: v for k, v in p.items() if not k.startswith('_fixed_')}
        expected = calculate_optimization(dict(kind='sweep', p=p, frac=1., var='f_sw', lo=100000., hi=400000., n=5), lambda: False)
        self.assertEqual([r['eta'] for r in actual['rows']], list(expected['etas']))
        self.assertEqual(actual['target_value'], find_target(expected['values'], expected['etas'], .87))

    def test_small_optimization_is_bounded_and_does_not_apply(self):
        result = self.action('optimize', dict(variables=['L'], bounds=[[6e-6, 12e-6]], maxiter=1, popsize=5))
        self.assertTrue(result['limited_budget'])
        self.assertGreater(result['evaluations'], 1)
        self.assertGreaterEqual(result['best']['L'], 6e-6)
        self.assertLessEqual(result['best']['L'], 12e-6)
        self.assertIsInstance(result['ok'], bool)

    def test_fixed_hardware_corners_and_geometric_preview(self):
        result = self.action('corners', dict(v_in_min=24., v_in_max=40., load_fracs=[.5, 1.], include_nominal=False))
        self.assertTrue(result['fixed_hardware'])
        self.assertEqual(len(result['corners']), 4)
        preview = self.action('winding_preview', {'config': dict(window_width=.012, window_height=.008)})
        self.assertTrue(preview['has_chart'])
        self.assertTrue(preview['automatic_plan'])
        overflow = self.action('winding_preview', {'config': dict(window_width=.0006, window_height=.0003)})
        self.assertTrue(overflow['has_chart'])
        self.assertFalse(overflow['assessment']['fits'])

    def test_psr_tuning_writes_real_comp_not_ssr(self):
        run = calculate(read_example('MP6005_PSR_FLYBACK.json'), analysis='endpoints', include_cross_regulation=False)
        path = Path(self.directory.name)/'psr-tune.png'
        result = execute(run, 'tune', dict(fc=500., pm=55., controller_type='type3'), path)
        self.assertTrue(result['feasible'], result)
        for key in ('psr_Rcomp', 'psr_Ccomp', 'psr_Cpole'):
            self.assertGreater(result['spec_updates'][key], 0)
        self.assertNotIn('KP', result['spec_updates'])
        with self.assertRaises(ValueError):
            execute(run, 'compensate', dict(key='opamp3', inputs=dict(R1=10000., Vref=2.5)), path)

    def test_multi_output_response_reuses_existing_loop_matrix(self):
        run = calculate(read_example('6_OUTPUT_FLYBACK_SSR.json'), analysis='endpoints', include_cross_regulation=False)
        path = Path(self.directory.name)/'response.png'
        result = execute(run, 'loop_response', {'load_output': 6}, path)
        self.assertEqual(len(result['outputs']), 6)
        self.assertTrue(result['has_chart'])
        self.assertLessEqual(len(result['frequency']), 800)
        self.assertIsNone(result['outputs'][0]['load_db'])

    def test_coupled_response_has_actual_load_matrix(self):
        run = calculate(read_example('3_OUTPUT_COUPLED_FLYBACK.json'), analysis='endpoints', include_cross_regulation=False)
        path = Path(self.directory.name)/'coupled-response.png'
        result = execute(run, 'loop_response', {'load_output': 2}, path)
        self.assertEqual(len(result['outputs']), 3)
        self.assertEqual(len(result['dc_load']), 3)
        self.assertIsNotNone(result['outputs'][0]['load_db'])
        self.assertNotEqual(result['outputs'][0]['load_db'], result['outputs'][1]['load_db'])

    def test_invalid_manual_plan_can_still_generate_repair_plan(self):
        result = self.action('winding_preview', {'config': dict(window_width=.012, window_height=.008,
            layer_plan=[dict(winding_id='P', turns=1, winding_style='dense_left')])})
        self.assertIsNone(result['assessment']['fits'])
        self.assertTrue(result['preview_error'])
        self.assertTrue(result['automatic_plan'])
        self.assertEqual(result['assessment']['config']['layer_plan'][0]['turns'], 1)

    def test_infeasible_network_keeps_its_reference_without_invented_parts(self):
        run = calculate(bootstrap()['spec'], analysis='endpoints', include_cross_regulation=False)
        path = Path(self.directory.name)/'infeasible-network.png'
        data = execute(run, 'compensate', dict(key='gm3', inputs=dict(R2=10000., R1u=100000., gm=.002)), path)
        self.assertFalse(data['buildable'])
        self.assertEqual(data['parts'], {})
        self.assertTrue(data['has_chart'])
        self.assertEqual(set(data['spec_updates']), {'__comp'})
        self.assertEqual(data['spec_updates']['__comp']['encoding'], 'si')

    def test_pre_cancelled_action_raises_without_file(self):
        from calculation_scheduler import CalculationCancelled
        path = Path(self.directory.name)/'cancelled.png'
        with self.assertRaises(CalculationCancelled):
            execute(self.design_run, 'tune', dict(fc=1000., pm=60.), path, cancelled=lambda: True)
        self.assertFalse(path.exists())


class ProcessChecks(unittest.TestCase):
    def test_owned_process_actions_cancel_independently_and_preserve_snapshot(self):
        manager = JobManager()
        process = None
        root = manager.root
        try:
            job = manager.submit(bootstrap()['spec'])['id']
            self.assertEqual(wait(manager, job)['state'], 'succeeded')
            original = manager.result(job)
            process = manager._process
            operation, future = manager.operate(job, 'action', action='optimize', options=dict(
                variables=['L', 'f_sw'], bounds=[[4e-6, 20e-6], [100000., 400000.]], maxiter=20, popsize=10))
            # Exercise the real worker, not only an unstarted queue cancellation.
            deadline = time.monotonic()+10
            while manager.operation(operation)['state'] == 'queued' and time.monotonic() < deadline:
                time.sleep(.01)
            self.assertEqual(manager.cancel_operation(operation)['state'], 'cancelled')
            operation2, future2 = manager.operate(job, 'action', action='tune', options=dict(fc=1000., pm=60., controller_type='type2'))
            done = wait(manager, operation2, operation=True)
            self.assertEqual(done['state'], 'succeeded', done)
            self.assertTrue(done['result']['feasible'])
            self.assertEqual(manager._process.pid, process.pid)
            self.assertEqual(manager.result(job), original)
            self.assertEqual(manager.status(job)['state'], 'succeeded')
            self.assertTrue(manager.file(operation2)[0].is_file())
            self.assertTrue(future.done())
        finally:
            manager.close()
        self.assertFalse(root.exists())
        self.assertFalse(process.is_alive())

    def test_operation_pruning_removes_only_owned_action_png(self):
        manager = JobManager()
        job = 'owned-check'
        manager.current_id = job
        manager._jobs[job] = dict(state='succeeded', generation=0)
        folder = manager.root/job
        folder.mkdir()
        shared = folder/'topology-Vinmin-1.png'
        shared.write_bytes(b'keep')
        first = None
        try:
            with patch.object(manager, '_enqueue', return_value=Future()):
                for index in range(70):
                    identity, _ = manager.operate(job, 'action', action='tune', options={})
                    path = folder/('action-'+identity+'.png')
                    path.write_bytes(b'owned')
                    manager._operations[identity].update(state='succeeded', result=dict(path=str(path)))
                    first = first or path
            self.assertLessEqual(len(manager._operations), 64)
            self.assertFalse(first.exists())
            self.assertTrue(shared.is_file())
        finally:
            manager.close()

    def test_transport_manual_validation_and_no_paths(self):
        from fastapi.testclient import TestClient
        from web_app.server import create_app
        with TestClient(create_app(testing=True)) as client:
            client.headers['X-Power-Token'] = client.get('/api/bootstrap').json()['token']
            response = client.get('/api/manual')
            self.assertEqual(response.status_code, 200)
            self.assertTrue(response.content.startswith(b'PK'))
            from app_resources import resource_path
            tutorial = client.get('/api/tutorial')
            self.assertEqual(tutorial.status_code, 200)
            self.assertEqual(tutorial.content, resource_path('多路反激电源设计入门教程.docx').read_bytes())
            self.assertIn('attachment', tutorial.headers['content-disposition'])
            self.assertIn('wordprocessingml.document', tutorial.headers['content-type'])
            self.assertEqual(client.get('/api/tutorial/unknown.docx').status_code, 404)
            with patch('app_resources.resource_path', return_value=ROOT/'missing-tutorial.docx'):
                self.assertEqual(client.get('/api/tutorial').status_code, 404)
            token = client.headers.pop('X-Power-Token')
            self.assertEqual(client.get('/api/tutorial').status_code, 403)
            client.headers['X-Power-Token'] = token
            for body in (dict(action='execute', options={}), dict(action='tune', options={'filename': 'x'}),
                         dict(action='sweep', options={'variable': {}, 'minimum': 1, 'maximum': 2})):
                self.assertEqual(client.post('/api/jobs/not-a-job/action', json=body).status_code, 422)
            self.assertEqual(client.post('/api/jobs/not-a-job/export', json={'format': 'xlsx', 'mos_real_time': 'yes'}).status_code, 422)
            self.assertEqual(client.post('/api/operations/absent/cancel').status_code, 404)

    def test_transport_action_and_export_time_axis_cache_variants(self):
        from fastapi.testclient import TestClient
        from web_app.server import create_app
        with TestClient(create_app(testing=True)) as client:
            client.headers['X-Power-Token'] = client.get('/api/bootstrap').json()['token']
            job = client.post('/api/jobs', json={'spec': bootstrap()['spec']}).json()['id']
            manager = client.app.state.jobs
            self.assertEqual(wait(manager, job)['state'], 'succeeded')
            submitted = client.post(f'/api/jobs/{job}/action', json=dict(action='tune', options=dict(fc=1000., pm=60.)))
            self.assertEqual(submitted.status_code, 202, submitted.text)
            operation = submitted.json()['id']
            self.assertEqual(wait(manager, operation, operation=True)['state'], 'succeeded')
            public = client.get('/api/operations/'+operation).json()
            self.assertNotIn('path', public['result'])
            self.assertNotIn('_cancellation_slot', public)
            self.assertTrue(client.get('/api/files/'+operation).content.startswith(b'\x89PNG'))
            paths = []
            for real in (False, True):
                response = client.post(f'/api/jobs/{job}/export', json={'format': 'xlsx', 'mos_real_time': real})
                self.assertEqual(response.status_code, 202)
                operation = response.json()['id']
                self.assertEqual(wait(manager, operation, operation=True)['state'], 'succeeded')
                paths.append(manager.file(operation)[0])
            self.assertNotEqual(paths[0], paths[1])
            self.assertIn('staged', paths[0].name)
            self.assertIn('real', paths[1].name)


if __name__ == '__main__':
    import multiprocessing
    multiprocessing.freeze_support()
    unittest.main(verbosity=2)
