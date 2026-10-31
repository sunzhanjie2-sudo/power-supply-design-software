"""Real frozen web worker with no Python/Node on PATH; no external user app."""
import io
import json
import os
from pathlib import Path
import socket
import subprocess
import sys
import time
from urllib.request import Request,urlopen
from zipfile import ZipFile
import psutil


def check(folder):
    root=Path(__file__).resolve().parents[1];folder=Path(folder).resolve()
    output=root/'artifacts/qa/parasitics_20261029/frozen_web';output.mkdir(exist_ok=True)
    with socket.socket() as probe:probe.bind(('127.0.0.1',0));port=probe.getsockname()[1]
    env=dict(os.environ)
    for key in ('PYTHONPATH','PYTHONHOME','VIRTUAL_ENV','CONDA_PREFIX'):env.pop(key,None)
    env.update(PATH=str(Path(os.environ['SystemRoot'])/'System32'),PYTHONNOUSERSITE='1',MPLBACKEND='Agg')
    token='';base=f'http://127.0.0.1:{port}/api'
    def request(path,body=None,raw=False):
        data=None if body is None else json.dumps(body).encode()
        with urlopen(Request(base+path,data=data,headers={'X-Power-Token':token,'Content-Type':'application/json'}),timeout=180) as reply:b=reply.read()
        return b if raw else json.loads(b)
    def wait(path):
        end=time.monotonic()+180
        while time.monotonic()<end:
            value=request(path)
            if value['state'] in ('failed','cancelled'):raise AssertionError(value)
            if value['state']=='succeeded':return value
            time.sleep(.15)
        raise AssertionError('Frozen worker timeout')
    with (output/'service.log').open('w',encoding='utf-8') as log:
        process=subprocess.Popen([str(folder/'PowerDesignWeb.exe'),'--port',str(port)],cwd=output,env=env,
            stdout=log,stderr=subprocess.STDOUT,creationflags=subprocess.CREATE_NO_WINDOW)
        try:
            for _ in range(150):
                if process.poll() is not None:raise AssertionError('Frozen web exit')
                try:bootstrap=request('/bootstrap');break
                except OSError:time.sleep(.2)
            else:raise AssertionError('Frozen web startup timeout')
            token=bootstrap['token'];assert 'cj_default' in bootstrap['parasitics']['fields']
            spec=request('/examples/40W_CCM_FLYBACK.json')
            spec['parasitic_config']=dict(mode='transient',coss=400e-12,lp_pcb=30e-9,
                rails={'OUT1':{'cj':75e-12}})
            job=request('/jobs',{'spec':spec})['id'];wait('/jobs/'+job)
            result=request('/jobs/'+job+'/result');assert result['ok'],result
            for row in result['display']:assert len(row['parasitics']['edges'])==2,row
            png=request(f'/jobs/{job}/chart/parasitics',raw=True)
            assert png.startswith(b'\x89PNG');(output/'parasitics.png').write_bytes(png)
            print('Frozen worker/local RLC/metadata/chart passed',flush=True)
            sizes={}
            for kind in ('zip','docx','xlsx'):
                operation=request('/jobs/'+job+'/export',{'format':kind})['id'];wait('/operations/'+operation)
                content=request('/files/'+operation,raw=True);sizes[kind]=len(content)
                with ZipFile(io.BytesIO(content)) as archive:
                    assert archive.testzip() is None
                    if kind=='zip':
                        assert 'parasitics.inc' in archive.namelist()
                        m=json.loads(archive.read('manifest.json'));assert m['parasitics']['resolved']['mode']=='transient'
                        assert b'PAR_D_O1_CJ' in archive.read('Flyback.asc')
                    elif kind=='docx':assert '寄生参数'.encode() in archive.read('word/document.xml')
                    else:assert any('寄生参数'.encode() in archive.read(name) for name in archive.namelist() if name.endswith('.xml'))
                (output/('verified_report.'+kind)).write_bytes(content)
                print('Frozen export',kind,'passed',flush=True)
            (output/'verification.json').write_text(json.dumps(dict(worker=True,chart=True,exports=sizes),indent=2),encoding='utf-8')
        finally:
            if process.poll() is None:
                for child in reversed(psutil.Process(process.pid).children(recursive=True)):
                    try:child.terminate()
                    except psutil.Error:pass
                process.terminate();process.wait(timeout=10)


if __name__=='__main__':check(sys.argv[1])
