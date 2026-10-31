"""Run ONLY an explicitly supplied frozen web bundle with Python/Node off PATH.

Tests HTTP, an actual worker solve, plots, advanced images and both Office
exports. No installed runtime packages can be imported by the frozen process.
"""
import argparse
import hashlib
import json
import os
from pathlib import Path
import socket
import subprocess
import sys
import tempfile
import time
from urllib.request import Request, urlopen
from zipfile import ZipFile
import psutil

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))


def check(folder):
    folder=Path(folder).resolve()
    exe=folder/'PowerDesignWeb.exe'
    assert exe.is_file() and (folder/'_internal/web_app/static/index.html').is_file()
    # Bind a free loopback port; release immediately before launching our EXE.
    with socket.socket() as probe:
        probe.bind(('127.0.0.1',0));port=probe.getsockname()[1]
    env=dict(os.environ)
    for key in ('PYTHONPATH','PYTHONHOME','VIRTUAL_ENV','CONDA_PREFIX'):
        env.pop(key,None)
    env.update(PATH=str(Path(os.environ['SystemRoot'])/'System32'),PYTHONNOUSERSITE='1',
               MPLBACKEND='Agg',POWER_DESIGN_NUM_THREADS='1')
    token='';base=f'http://127.0.0.1:{port}/api'
    def request(path,body=None,raw=False):
        data=None if body is None else json.dumps(body).encode()
        headers={'X-Power-Token':token,'Content-Type':'application/json'}
        with urlopen(Request(base+path,data=data,headers=headers),timeout=120) as response:
            content=response.read()
        return content if raw else json.loads(content)
    def wait(path):
        deadline=time.monotonic()+300
        while time.monotonic()<deadline:
            row=request(path)
            if row['state'] in ('failed','cancelled'):raise AssertionError(row)
            if row['state']=='succeeded':return row
            time.sleep(.1)
        raise AssertionError('Timed out: '+path)
    with tempfile.TemporaryDirectory(prefix='power-web-portable-中文-') as working:
        working=Path(working)
        with (working/'service.log').open('w',encoding='utf-8') as log:
            process=subprocess.Popen([str(exe),'--port',str(port)],cwd=working,env=env,
                stdout=log,stderr=subprocess.STDOUT,creationflags=subprocess.CREATE_NO_WINDOW)
            descendants=[]
            try:
                deadline=time.monotonic()+40
                while time.monotonic()<deadline:
                    if process.poll() is not None:
                        raise AssertionError((working/'service.log').read_text(encoding='utf-8',errors='replace'))
                    try:
                        if request('/health')['local_only']:break
                    except OSError:time.sleep(.15)
                else:raise AssertionError('EXE service did not start')
                bootstrap=request('/bootstrap');token=bootstrap['token']
                assert bootstrap['spec']['P_out']==40
                manual=request('/manual',raw=True)
                with ZipFile(__import__('io').BytesIO(manual)) as document:
                    assert b'<m:oMath' in document.read('word/document.xml')
                tutorial=request('/tutorial',raw=True)
                from app_resources import resource_path
                assert tutorial==resource_path('多路反激电源设计入门教程.docx').read_bytes()
                with ZipFile(__import__('io').BytesIO(tutorial)) as document:
                    assert b'<m:oMath' in document.read('word/document.xml')
                # This is the frozen runtime smoke. Full FRA/corner QA has its own real-evidence run.
                bootstrap['spec']['spice_config']=dict(fra_enabled=1,cross_enabled=0,
                    fra_start_hz=1000,fra_stop_hz=8000,fra_oct=1,fra_cycles=100)
                job=request('/jobs',{'spec':bootstrap['spec']})['id']
                wait('/jobs/'+job)
                result=request('/jobs/'+job+'/result')
                assert result['ok'] and len(result['cases'])==2,result
                for kind in ('topology','switching_real','capacitors','magnetic_flux','clamp','loop'):
                    image=request(f'/jobs/{job}/chart/{kind}',raw=True)
                    assert image.startswith(b'\x89PNG'),kind
                action=request('/jobs/'+job+'/action',{'action':'compensate',
                    'options':{'key':'opamp3','direction':'fwd','type2':True,
                               'inputs':{'R1':10000,'Vref':2.5}}})['id']
                wait('/operations/'+action)
                assert request('/files/'+action,raw=True).startswith(b'\x89PNG')
                reports={}
                for kind in ('xlsx','docx'):
                    operation=request('/jobs/'+job+'/export',{'format':kind,'mos_real_time':True})['id']
                    wait('/operations/'+operation)
                    content=request('/files/'+operation,raw=True)
                    with ZipFile(__import__('io').BytesIO(content)) as archive:
                        assert len(archive.namelist())>20
                    reports[kind]=len(content)
                operation=request('/jobs/'+job+'/export',{'format':'zip'})['id']
                wait('/operations/'+operation)
                with ZipFile(__import__('io').BytesIO(request('/files/'+operation,raw=True))) as archive:
                    assert 'Flyback.asc' in archive.namelist()
                    assert 'GPWM_CORE.asy' in archive.namelist()
                    manifest=json.loads(archive.read('manifest.json'))
                    assert manifest['settings']['diode_cj_pf']==20
                    assert manifest['settings']['include_cap_esl']==0
                    assert b'V_SECONDARY_REFERENCE sgnd 0 0' in archive.read('power_stage.inc')
                operation=request('/jobs/'+job+'/export',{'format':'comparison'})['id']
                wait('/operations/'+operation)
                with ZipFile(__import__('io').BytesIO(request('/files/'+operation,raw=True))) as archive:
                    evidence=json.loads(archive.read('comparison.json'))
                    assert len(evidence['cases'])==1 and evidence['cases'][0]['complete'],evidence
                    assert evidence['cases'][0]['actual_end_s']==.012
                    assert abs(evidence['cases'][0]['measurements']['out1_before']-30)<.3
                    assert evidence['cases'][0]['loop']['available'],evidence['cases'][0]['loop']
                    assert any(n.endswith('.docx') for n in archive.namelist())
                print(json.dumps(dict(bundle=str(folder),portable_exe_sha256=hashlib.sha256(exe.read_bytes()).hexdigest(),
                    path_isolated=True,unicode_cwd=True,actual_worker=True,charts=6,compensation_png=True,
                    reports=reports,spice_zip=True,actual_spice_comparison=True,manual_bytes=len(manual),tutorial_bytes=len(tutorial)),ensure_ascii=False))
            finally:
                if process.poll() is None:
                    descendants=psutil.Process(process.pid).children(recursive=True)
                    for child in reversed(descendants):
                        try:child.terminate()
                        except psutil.NoSuchProcess:pass
                    process.terminate()
                process.wait(timeout=10)
                psutil.wait_procs(descendants,timeout=5)
                assert all(not child.is_running() for child in descendants),'Owned worker left alive'


if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('folder')
    check(parser.parse_args().folder)
