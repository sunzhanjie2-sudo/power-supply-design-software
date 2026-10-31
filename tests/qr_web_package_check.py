"""Frozen QR worker and portable engineering export, with Python off PATH."""
import io
import json
import os
from pathlib import Path
import socket
import subprocess
import sys
import tempfile
import time
from urllib.request import Request,urlopen
import zipfile
import psutil


def check(folder):
    folder=Path(folder).resolve();exe=folder/'PowerDesignWeb.exe'
    with socket.socket() as s:s.bind(('127.0.0.1',0));port=s.getsockname()[1]
    env=dict(os.environ)
    for key in ('PYTHONPATH','PYTHONHOME','VIRTUAL_ENV','CONDA_PREFIX'):env.pop(key,None)
    env.update(PATH=str(Path(os.environ['SystemRoot'])/'System32'),PYTHONNOUSERSITE='1',MPLBACKEND='Agg')
    token='';base=f'http://127.0.0.1:{port}/api'
    def request(path,body=None,raw=False):
        data=None if body is None else json.dumps(body).encode()
        with urlopen(Request(base+path,data=data,headers={'X-Power-Token':token,'Content-Type':'application/json'}),timeout=60) as r:b=r.read()
        return b if raw else json.loads(b)
    def wait(path):
        end=time.monotonic()+90
        while time.monotonic()<end:
            row=request(path)
            if row['state'] in ('failed','cancelled'):raise AssertionError(row)
            if row['state']=='succeeded':return row
            time.sleep(.15)
        raise AssertionError('QR worker timeout')
    with tempfile.TemporaryDirectory(prefix='QR便携验证-') as d:
        with (Path(d)/'service.log').open('w',encoding='utf-8') as log:
            p=subprocess.Popen([str(exe),'--port',str(port)],cwd=d,env=env,stdout=log,stderr=subprocess.STDOUT,creationflags=subprocess.CREATE_NO_WINDOW)
            try:
                for _ in range(200):
                    if p.poll() is not None:raise AssertionError((Path(d)/'service.log').read_text(encoding='utf-8',errors='replace'))
                    try:b=request('/bootstrap');break
                    except OSError:time.sleep(.2)
                else:raise AssertionError('QR frozen service unavailable')
                token=b['token'];assert b['spice_qr_logic']['short_labels']['qr_cds_pf']=='Cds'
                spec=request('/examples/90W_QR_L6565_300V.json')
                assert spec['A_sense']==1. and spec['Coss']==470e-12
                job=request('/jobs',{'spec':spec})['id'];wait('/jobs/'+job)
                result=request('/jobs/'+job+'/result');assert result['ok'],result
                op=request('/jobs/'+job+'/export',{'format':'zip'})['id'];wait('/operations/'+op)
                with zipfile.ZipFile(io.BytesIO(request('/files/'+op,raw=True))) as z:
                    m=json.loads(z.read('manifest.json'));assert m['topology']=='QR-FLYBACK'
                    assert m['resolved_controller']['A_CS']==1. and m['resolved_controller']['TYPE']==2
                    assert m['qr']['event_driven'] and m['voltages']==[300]
                    assert b'SYMBOL GQR_CTRL' in z.read('Flyback.asc')
                    assert b'GQR_CTRL' in z.read('power_stage.inc') and 'Flyback.plt' in z.namelist()
                print('Frozen QR worker + native ASC/ZIP verified:',folder)
            finally:
                if p.poll() is None:
                    for child in reversed(psutil.Process(p.pid).children(recursive=True)):
                        try:child.terminate()
                        except psutil.Error:pass
                    p.terminate();p.wait(timeout=10)


if __name__=='__main__':check(sys.argv[1])
