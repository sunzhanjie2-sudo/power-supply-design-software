"""Frozen worker can calculate all three profiles and export without Python."""
import io,json,os,socket,subprocess,sys,time
from pathlib import Path
from urllib.request import Request,urlopen
from zipfile import ZipFile
import psutil

def check(folder,with_banks=False):
    root=Path(__file__).resolve().parents[1];folder=Path(folder).resolve();output=root/'artifacts/qa'/('nonisolated_frozen_'+folder.parent.name+('_banks' if with_banks else ''));output.mkdir(exist_ok=True)
    with socket.socket() as s:s.bind(('127.0.0.1',0));port=s.getsockname()[1]
    env=dict(os.environ)
    for k in ('PYTHONPATH','PYTHONHOME','VIRTUAL_ENV','CONDA_PREFIX'):env.pop(k,None)
    env.update(PATH=str(Path(os.environ['SystemRoot'])/'System32'),PYTHONNOUSERSITE='1',MPLBACKEND='Agg')
    base=f'http://127.0.0.1:{port}/api';token=''
    def request(path,body=None,raw=False):
        data=None if body is None else json.dumps(body).encode()
        with urlopen(Request(base+path,data=data,headers={'X-Power-Token':token,'Content-Type':'application/json'}),timeout=180) as r:b=r.read()
        return b if raw else json.loads(b)
    def wait(path):
        end=time.monotonic()+180
        while time.monotonic()<end:
            v=request(path)
            if v['state'] in ('failed','cancelled'):raise AssertionError(v)
            if v['state']=='succeeded':return v
            time.sleep(.15)
        raise AssertionError('Frozen operation timeout')
    summary=[]
    with (output/'service.log').open('w',encoding='utf-8') as log:
        p=subprocess.Popen([str(folder/'PowerDesignWeb.exe'),'--port',str(port)],cwd=output,env=env,stdout=log,stderr=subprocess.STDOUT,creationflags=subprocess.CREATE_NO_WINDOW)
        try:
            for _ in range(150):
                if p.poll() is not None:raise AssertionError('Frozen worker exited')
                try:b=request('/bootstrap');break
                except OSError:time.sleep(.2)
            else:raise AssertionError('Frozen startup timeout')
            token=b['token'];assert all(n in b['spice_presets'] for n in ('tps40200','ltc3864','lm5022'));assert b['spice_niso_logic']
            names=['24W_BUCK_VM_TPS40200.json','24W_BUCK_PCM_LTC3864.json','24W_BOOST_PCM_LM5022.json']
            for n,name in enumerate(names,1):
                spec=request('/examples/'+name)
                if with_banks:
                    spec.update(input_capacitors=[dict(C=100e-6,ESR=.05,ESL=1e-9)]*3,
                        output_capacitors=[dict(C=57.5e-6,ESR=.08,ESL=1e-9)]*4)
                job=request('/jobs',{'spec':spec})['id'];wait('/jobs/'+job)
                r=request('/jobs/'+job+'/result');assert r['ok'],r
                sizes={}
                for kind in ('zip','docx','xlsx'):
                    op=request('/jobs/'+job+'/export',{'format':kind})['id'];wait('/operations/'+op);data=request('/files/'+op,raw=True);sizes[kind]=len(data)
                    with ZipFile(io.BytesIO(data)) as z:
                        assert z.testzip() is None
                        if kind=='zip':
                            m=json.loads(z.read('manifest.json'));assert m['niso']['id']==n;assert m['hardware']['kind']=='single-inductor'
                            assert 'Flyback.asc' in z.namelist();assert 'MODEL_GUIDE.md' in z.namelist()
                            assert b'GNISO_CTRL' in z.read('GenericBuckBoostPWM.lib')
                            if with_banks:
                                assert b'XC_IN3' in z.read('support.inc')
                                assert b'XC_O1_4' in z.read('support.inc')
                        elif kind=='docx':assert 'word/document.xml' in z.namelist()
                        else:assert 'xl/workbook.xml' in z.namelist()
                    (output/(name[:-5]+'.'+kind)).write_bytes(data)
                summary.append(dict(name=name,exports=sizes));print('Frozen calculation/ASC/Word/Excel passed',name,flush=True)
            (output/'verification.json').write_text(json.dumps(summary,ensure_ascii=False,indent=2),encoding='utf-8')
        finally:
            if p.poll() is None:
                for child in reversed(psutil.Process(p.pid).children(recursive=True)):
                    try:child.terminate()
                    except psutil.Error:pass
                p.terminate();p.wait(timeout=10)
if __name__=='__main__':check(sys.argv[1],with_banks='--banks' in sys.argv)
