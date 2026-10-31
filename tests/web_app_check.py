"""Local Web contract/security/process/chart/report checks (no browser required)."""
import copy
import json
from pathlib import Path
import queue
import subprocess
import sys
import tempfile
import time
import unittest
from unittest.mock import patch
from zipfile import ZipFile

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from runtime_resources import configure_numeric_threads
configure_numeric_threads()

from fastapi.testclient import TestClient
from web_app.server import create_app
from web_app.metadata import bootstrap, normalize_config, preview, read_example
from web_app.curves import apply_curve, inspect_curve
from web_app.jobs import JobManager


def wait_state(client, path, timeout=120):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        response = client.get(path)
        response.raise_for_status()
        row = response.json()
        if row['state'] in ('succeeded', 'failed', 'cancelled'):
            return row
        time.sleep(.05)
    raise AssertionError(f'Timed out: {path}')


class MetadataAndCurveChecks(unittest.TestCase):
    def test_bootstrap_reuses_default_and_report_metadata(self):
        data = bootstrap()
        self.assertEqual(data['spec']['topology'], 'FLYBACK')
        self.assertEqual(data['spec']['P_out'], 40)
        self.assertEqual(data['spec']['V_in_min'], 30)
        self.assertIn('__comp', data['spec'])
        self.assertIn('k_core', {r['name'] for r in data['parameters']})
        self.assertEqual(next(r for r in data['parameters'] if r['name']=='target_eta')['display_factor'],100)
        data['spec']['__comp']['vars'] = {}
        self.assertTrue(bootstrap()['spec']['__comp']['vars'])

    def test_normalize_preserves_legacy_curve_selection_and_metadata(self):
        raw = read_example('40W_CCM_FLYBACK.json')
        raw['__web_project_title'] = '测试项目'
        raw['mos_charge_mode'] = 'curve'
        result = normalize_config(raw)
        self.assertEqual(result['__web_project_title'], '测试项目')
        from device_curve_sources import source_for
        self.assertEqual(source_for(result, 'Q1:charge'), 'curve')
        self.assertIn('__comp', result)

    def test_example_paths_are_whitelisted(self):
        for name in ('../main.py', 'main.py', 'C:/Windows/win.ini'):
            with self.assertRaises(ValueError):
                read_example(name)

    def test_preview_is_not_a_converter_solve(self):
        with patch('loss_model.compute_design', side_effect=AssertionError('unexpected solve')):
            data = preview(read_example('6_OUTPUT_FLYBACK_SSR.json'))
        self.assertEqual(len(data['outputs']), 6)
        self.assertIn('D_O6', {r['ref'] for r in data['targets']})

    def test_simple_diode_import_scales_and_selects_only_target(self):
        raw = bootstrap()['spec']
        text = 'x,y\n450,0\n500,1\n650,4\n800,8\n'
        inspection = inspect_curve('ES3D.csv', text, 'D1')
        self.assertTrue(inspection['simple'])
        result = apply_curve(raw, 'ES3D.csv', text, 'D1', x_multiplier=.001)
        self.assertNotIn('D1', raw['diode_curves'])
        self.assertEqual(result['spec']['diode_curves']['D1']['points'][0][0], .45)
        self.assertEqual(result['spec']['device_curve_settings']['overrides']['D1'], 'curve')
        self.assertIn('sha256', result['spec']['diode_curves']['D1']['source'])

    def test_curve_target_must_match_topology_and_no_server_path(self):
        text = 'x,y\n.4,0\n.5,1\n'
        with self.assertRaises(ValueError):
            apply_curve(dict(bootstrap()['spec'],topology='BUCK'), 'a.csv', text, 'D_O6')
        for filename in ('a.exe','a.py','a.png'):
            with self.assertRaises(ValueError):
                inspect_curve(filename, text, 'D1')

    def test_gate_charge_requires_explicit_platform_and_scale(self):
        raw = bootstrap()['spec']
        text = 'x,y\n0,0\n2,2\n4,4\n6,4\n10,10\n'
        with self.assertRaisesRegex(ValueError, '平台'):
            apply_curve(raw,'Qg.csv',text,'Q1:charge',x_multiplier=1e-9)
        result = apply_curve(raw,'Qg.csv',text,'Q1:charge',x_multiplier=1e-9,
                             plateau_start=4.,plateau_end=6.)
        self.assertTrue(result['spec']['mos_charge_curve'])

    def test_structured_gate_charge_not_scaled_twice(self):
        text=(ROOT/'tests/fixtures/actual_gate_profile.json').read_text(encoding='utf-8')
        self.assertFalse(inspect_curve('Qg.json',text,'Q1:charge')['simple'])
        with self.assertRaisesRegex(ValueError, 'SI'):
            apply_curve(bootstrap()['spec'],'Qg.json',text,'Q1:charge',x_multiplier=1e-9)


class LocalSecurityChecks(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.context=TestClient(create_app(testing=True))
        cls.client=cls.context.__enter__()
        cls.token=cls.client.get('/api/bootstrap').json()['token']

    @classmethod
    def tearDownClass(cls):
        cls.context.__exit__(None,None,None)

    def test_health_public_but_protected_routes_need_session(self):
        self.assertEqual(self.client.get('/api/health').json()['local_only'],True)
        self.assertEqual(self.client.post('/api/jobs',json={'spec':{}}).status_code,403)
        self.assertEqual(self.client.get('/api/examples/spec_buck.json',headers={'X-Power-Token':self.token}).status_code,200)

    def test_host_origin_and_cross_site_are_denied(self):
        for headers in ({'host':'evil.example'}, {'origin':'https://evil.example'},
                        {'sec-fetch-site':'cross-site'}):
            self.assertEqual(self.client.get('/api/bootstrap',headers=headers).status_code,403)

    def test_unknown_envelopes_and_wrong_types_rejected(self):
        headers={'X-Power-Token':self.token}
        for body in ({'spec':{},'execute':'anything'}, {'spec':[]}, {'spec':{},'cross_regulation':'yes'}):
            self.assertEqual(self.client.post('/api/jobs',json=body,headers=headers).status_code,422)

    def test_body_budget_and_response_headers(self):
        response=self.client.post('/api/config',content='{}',headers={
            'X-Power-Token':self.token,'content-length':str(17*1024*1024)})
        self.assertEqual(response.status_code,413)
        good=self.client.get('/api/health')
        self.assertEqual(good.headers['x-frame-options'],'DENY')
        self.assertIn("frame-ancestors 'none'", good.headers['content-security-policy'])
        self.assertEqual(good.headers['cache-control'],'no-store')

    def test_no_arbitrary_file_download_and_private_worker_paths(self):
        headers={'X-Power-Token':self.token}
        self.assertEqual(self.client.get('/api/files/main.py',headers=headers).status_code,404)
        self.assertEqual(self.client.get('/api/operations/absent',headers=headers).status_code,404)


class ProcessAndReportChecks(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.context=TestClient(create_app(testing=True))
        cls.client=cls.context.__enter__()
        cls.client.headers['X-Power-Token']=cls.client.get('/api/bootstrap').json()['token']
        cls.spec=bootstrap()['spec']
        cls.spec.update(V_in_min=24.,V_in_max=40.)
        cls.job=cls.client.post('/api/jobs',json={'spec':cls.spec}).json()['id']
        cls.completed=wait_state(cls.client,'/api/jobs/'+cls.job)
        if cls.completed['state']!='succeeded':
            raise AssertionError(cls.completed)
        cls.result=cls.client.get('/api/jobs/'+cls.job+'/result').json()

    @classmethod
    def tearDownClass(cls):
        manager=cls.context.app.state.jobs
        process=manager._process
        owned=manager.root
        cls.context.__exit__(None,None,None)
        if process.is_alive() or owned.exists():
            raise AssertionError('Owned numerical worker or temporary directory leaked')

    def test_a_worker_result_matches_shared_engine_exactly(self):
        from design_engine.service import calculate
        run=calculate(self.spec,analysis='endpoints',include_efficiency=True,include_cross_regulation=False)
        expected=run.to_dict(include_waveforms=False,include_details=False)
        self.assertTrue(self.result['ok'])
        self.assertEqual(self.result['hardware'],expected['hardware'])
        for actual,reference in zip(self.result['cases'],expected['cases']):
            self.assertEqual(actual['summary'],reference['summary'])
        self.assertNotEqual(self.result['cases'][0]['summary']['operating_point']['D'],
                            self.result['cases'][1]['summary']['operating_point']['D'])

    def test_b_lazy_chart_is_png_and_cached_without_solve(self):
        for case in ('Vinmin','Vinmax'):
            response=self.client.get(f'/api/jobs/{self.job}/chart/topology?case={case}')
            self.assertEqual(response.status_code,200,response.text[:100] if response.status_code!=200 else '')
            self.assertTrue(response.content.startswith(b'\x89PNG\r\n'))
        again=self.client.get(f'/api/jobs/{self.job}/chart/topology?case=Vinmin')
        self.assertEqual(again.status_code,200)
        self.assertEqual(self.client.get(f'/api/jobs/{self.job}/chart/invalid').status_code,422)

    def test_c_excel_word_json_generated_from_current_snapshot(self):
        for kind in ('xlsx','docx','json'):
            with self.subTest(kind=kind):
                response=self.client.post(f'/api/jobs/{self.job}/export',json={'format':kind})
                self.assertEqual(response.status_code,202,response.text)
                operation=response.json()['id']
                finished=wait_state(self.client,'/api/operations/'+operation,timeout=180)
                self.assertEqual(finished['state'],'succeeded',finished)
                self.assertNotIn('path',finished['result'])
                downloaded=self.client.get('/api/files/'+operation,params={'filename':'设计/报告:测试'})
                self.assertEqual(downloaded.status_code,200)
                self.assertIn('attachment',downloaded.headers['content-disposition'])
                if kind=='xlsx':
                    manager=self.context.app.state.jobs
                    cached_path,_=manager.file(operation)
                    modified=cached_path.stat().st_mtime_ns
                    repeat=self.client.post(f'/api/jobs/{self.job}/export',json={'format':'xlsx'}).json()['id']
                    self.assertEqual(wait_state(self.client,'/api/operations/'+repeat)['state'],'succeeded')
                    self.assertEqual(cached_path.stat().st_mtime_ns,modified)
                    self.assertEqual(self.client.get('/api/files/'+repeat).content,downloaded.content)
                if kind=='json':
                    # Compact and full JSON have different content hashes, but
                    # share one calculation's timestamp/input/hardware/results.
                    full=downloaded.json()
                    self.assertEqual(full['created_at'],self.result['created_at'])
                    self.assertEqual(full['spec'],self.result['spec'])
                    self.assertEqual(full['hardware'],self.result['hardware'])
                    self.assertEqual(full['cases'][0]['summary'],self.result['cases'][0]['summary'])
                else:
                    import io
                    with ZipFile(io.BytesIO(downloaded.content)) as archive:
                        self.assertTrue(any('/media/' in path for path in archive.namelist()))
                        if kind=='xlsx':
                            self.assertGreaterEqual(len([p for p in archive.namelist() if p.startswith('xl/worksheets/sheet')]),8)
                        else:
                            xml=archive.read('word/document.xml').decode()
                            self.assertIn('Vinmin',xml)
                            self.assertIn('Vinmax',xml)
                            self.assertIn('补偿',xml)
                            self.assertIn('<m:oMath',xml)

    def test_c2_ltspice_zip_uses_current_fixed_hardware_snapshot(self):
        import io
        operation=self.client.post(f'/api/jobs/{self.job}/export',json={'format':'zip'}).json()['id']
        row=wait_state(self.client,'/api/operations/'+operation)
        self.assertEqual(row['state'],'succeeded',row)
        downloaded=self.client.get('/api/files/'+operation)
        self.assertEqual(downloaded.headers['content-type'],'application/zip')
        with ZipFile(io.BytesIO(downloaded.content)) as archive:
            self.assertIsNone(archive.testzip())
            self.assertIn('Flyback.asc',archive.namelist())
            self.assertIn('.step param VIN list 24 40',archive.read('design_params.inc').decode())
            manifest=json.loads(archive.read('manifest.json'))
            self.assertEqual(manifest['hardware']['Np'],self.result['hardware']['transformer']['Np'])
            self.assertEqual(manifest['model_version'],'GenericFlybackPWM-3.1')

    def test_d_queue_and_job_records_are_bounded_even_on_overflow(self):
        manager=JobManager()
        try:
            with patch.object(manager,'start'),patch.object(manager._inbox,'put_nowait',side_effect=queue.Full):
                for _ in range(80):
                    with self.assertRaises(ValueError):
                        manager.submit(self.spec)
            self.assertLessEqual(len(manager._jobs),4)
            self.assertFalse(manager._futures)
        finally:
            manager.close()
        script = ('from web_app.jobs import JobManager\n'
                  'm=JobManager()\n'
                  'm._inbox.put({"payload":"x"*1048576})\n'
                  'm.close()\n'
                  'print("closed")\n')
        completed=subprocess.run([sys.executable,'-c',script],cwd=ROOT,
                                 capture_output=True,text=True,timeout=10)
        self.assertEqual(completed.returncode,0,completed.stderr)
        self.assertIn('closed',completed.stdout)

    def test_e_cancel_supersede_and_keep_http_responsive(self):
        ids=[]
        for _ in range(8):
            response=self.client.post('/api/jobs',json={'spec':self.spec})
            self.assertEqual(response.status_code,202)
            ids.append(response.json()['id'])
        start=time.monotonic()
        self.assertEqual(self.client.get('/api/health').status_code,200)
        self.assertLess(time.monotonic()-start,2.)
        latest=ids[-1]
        self.assertEqual(self.client.post('/api/jobs/'+latest+'/cancel').json()['state'],'cancelled')
        manager=self.context.app.state.jobs
        self.assertLessEqual(len(manager._jobs),4)
        response=self.client.post(f'/api/jobs/{self.job}/export',json={'format':'json'})
        self.assertIn(response.status_code,(404,422))
        next_job=self.client.post('/api/jobs',json={'spec':self.spec}).json()['id']
        self.assertEqual(wait_state(self.client,'/api/jobs/'+next_job)['state'],'succeeded')
        self.assertTrue(manager._process.is_alive())


class HeadlessChartChecks(unittest.TestCase):
    def test_six_output_forward_keeps_every_choke_and_new_chart(self):
        from design_engine.service import calculate
        from web_app.charts import render
        from web_app.presentation import present
        from matplotlib.figure import Figure
        spec = bootstrap()['spec']
        spec.update(topology='ACF-FORWARD', N=.5, Lm_forward=220e-6, C_clamp=47e-9)
        spec['outputs'] = [dict(name=f'OUT{i}', V_out=voltage, P_out=power, P_out_min=power,
            Ns=0, d_wire_s=0., n_strand_s=10, C_out=220e-6, C_out2=100e-6, L=1e-3)
            for i,(voltage,power) in enumerate(zip((30,12,5,3.3,24,15),(20,8,4,2,4,2)),1)]
        run = calculate(spec, analysis='endpoints', include_efficiency=True, include_cross_regulation=False)
        data = present(run)
        self.assertTrue(data['ok'])
        size = len(json.dumps(data, ensure_ascii=False, separators=(',', ':'), allow_nan=False).encode('utf-8'))
        self.assertLess(size, 512*1024)
        print(f'\nDISPLAY_PAYLOAD 6_OUTPUT_ACF_FORWARD: {size} bytes', flush=True)
        self.assertEqual(len(data['display'][0]['magnetics']), 7)
        original_save = Figure.savefig
        inspected = set()
        def inspect(figure, destination, *args, **kwargs):
            stem = Path(destination).stem
            if stem == 'magnetics':
                self.assertEqual(len(figure.axes[1].patches), 7)
                inspected.add(stem)
            if stem == 'magnetic_flux':
                labels = {line.get_label() for line in figure.axes[0].lines}
                for i in range(1,7):
                    self.assertIn(f'L_O{i} 磁通', labels)
                inspected.add(stem)
            if stem == 'outputs':
                self.assertEqual(len(figure.axes), 6)
                self.assertGreaterEqual(figure.get_figheight(), 8.4)
                inspected.add(stem)
            return original_save(figure, destination, *args, **kwargs)
        with tempfile.TemporaryDirectory(prefix='web-acf-chart-check-') as directory:
            folder = Path(directory)
            with patch.object(Figure, 'savefig', inspect):
                for kind in ('topology','power','switching_real','input_caps','device_losses','magnetics',
                             'magnetic_flux','clamp','outputs','output_caps','output_losses'):
                    path = render(run, folder/(kind+'.png'), 'Vinmax', kind, output=6)
                    self.assertGreater(path.stat().st_size, 1000, kind)
            self.assertEqual(inspected, {'magnetics','magnetic_flux','outputs'})

    def test_chart_adapters_cover_topologies_and_each_output(self):
        from design_engine.service import calculate
        from web_app.charts import render, KINDS
        with tempfile.TemporaryDirectory(prefix='web-chart-check-') as directory:
            folder=Path(directory)
            multi=calculate(read_example('6_OUTPUT_FLYBACK_SSR.json'),analysis='endpoints',
                include_efficiency=True,include_cross_regulation=False)
            self.assertTrue(multi.to_dict(include_details=False)['ok'])
            for kind in sorted(KINDS):
                path=render(multi,folder/(kind+'.png'),'Vinmin',kind,output=6)
                self.assertGreater(path.stat().st_size,1000,kind)
            for name in ('40W_ACF_FORWARD.json','MP6005_PSR_FLYBACK.json','spec_buck.json'):
                run=calculate(read_example(name),analysis='endpoints',include_cross_regulation=False)
                self.assertTrue(run.to_dict(include_details=False)['ok'],name)
                kinds = ('topology','power','switching','switching_real','capacitors','input_caps',
                         'losses','device_losses','magnetics','magnetic_flux')
                if name != 'spec_buck.json':
                    kinds += ('clamp',)
                for kind in kinds:
                    with self.subTest(example=name,kind=kind):
                        path=render(run,folder/(name+kind+'.png'),'Vinmax',kind)
                        self.assertGreater(path.stat().st_size,1000)
            for topology in ('BOOST','BUCK-BOOST','QR-FLYBACK'):
                spec=bootstrap()['spec']
                spec['topology']=topology
                if topology!='QR-FLYBACK':
                    spec.update(V_in=12.,V_in_min=12.,V_in_max=18.,V_out=24.)
                run=calculate(spec,analysis='endpoints',include_cross_regulation=False)
                self.assertTrue(run.to_dict(include_details=False)['ok'],topology)
                for kind in ('topology','power','switching','magnetics'):
                    with self.subTest(topology=topology,kind=kind):
                        self.assertGreater(render(run,folder/(topology+kind+'.png'),'Vinmin',kind).stat().st_size,1000)


class PresentationChecks(unittest.TestCase):
    def test_display_payload_budget_and_topology_specific_results(self):
        from design_engine.service import calculate
        from web_app.presentation import present
        for name in ('6_OUTPUT_FLYBACK_SSR.json', '40W_ACF_FORWARD.json', '3_OUTPUT_COUPLED_FLYBACK.json'):
            with self.subTest(example=name):
                run = calculate(read_example(name), analysis='endpoints', include_efficiency=True,
                    include_cross_regulation=False)
                with patch('loss_model.compute_design', side_effect=AssertionError('display must not solve converter')):
                    data = present(run)
                encoded = json.dumps(data, ensure_ascii=False, separators=(',', ':'), allow_nan=False).encode('utf-8')
                # Full waveforms remain worker-owned; display transfer should be
                # comfortably smaller than the multi-megabyte audit snapshot.
                self.assertLess(len(encoded), 512*1024, (name, len(encoded)))
                print(f'\nDISPLAY_PAYLOAD {name}: {len(encoded)} bytes', flush=True)
                self.assertTrue(data['ok'])
                for case in data['display']:
                    self.assertTrue(case['stress'])
                    self.assertTrue(case['operating_point'])
                    self.assertTrue(case['capacitors']['input']['caps'])
                    self.assertGreater(case['waveform_points'], 100)
                    self.assertTrue(case['winding_rows'])
                    if name.startswith('6_OUTPUT'):
                        self.assertEqual(len(case['outputs']), 6)
                        self.assertTrue(case['outputs'][5]['stress'])
                    elif name.startswith('40W_ACF'):
                        self.assertTrue(case['semiconductors']['auxiliary'])
                        self.assertTrue(case['semiconductors']['freewheel'])

    def test_incomplete_mechanical_layer_plan_does_not_discard_electrical_result(self):
        from design_engine.service import calculate
        from web_app.presentation import present
        spec = bootstrap()['spec']
        spec['winding_config'] = dict(window_width=.012, window_height=.008,
            layer_plan=[dict(winding_id='P', turns=1, winding_style='dense_left')])
        run = calculate(spec, analysis='endpoints', include_cross_regulation=False)
        data = present(run)
        self.assertTrue(data['ok'])
        for case in data['display']:
            assessment = case['winding_assessment']
            self.assertEqual(assessment['status'], 'invalid_plan')
            self.assertIsNone(assessment['fits'])
            self.assertTrue(assessment['warnings'])
            self.assertEqual(assessment['config']['layer_plan'][0]['turns'], 1)


if __name__=='__main__':
    import multiprocessing
    multiprocessing.freeze_support()
    unittest.main(verbosity=2)
