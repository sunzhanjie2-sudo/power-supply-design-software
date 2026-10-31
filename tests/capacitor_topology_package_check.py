"""Render bank diagrams and export Word through the actual portable web worker."""
import io
import json
import os
from pathlib import Path
import socket
import subprocess
import sys
import time
from urllib.request import Request, urlopen
from zipfile import ZipFile

import psutil
from PIL import Image


def check(folder):
    root = Path(__file__).resolve().parents[1]
    folder = Path(folder).resolve()
    output = root/'artifacts/qa/capacitor_topology_20261030/frozen'
    output.mkdir(parents=True, exist_ok=True)
    with socket.socket() as sock:
        sock.bind(('127.0.0.1', 0)); port = sock.getsockname()[1]
    env = dict(os.environ)
    for key in ('PYTHONPATH', 'PYTHONHOME', 'VIRTUAL_ENV', 'CONDA_PREFIX'):
        env.pop(key, None)
    env.update(PATH=str(Path(os.environ['SystemRoot'])/'System32'), PYTHONNOUSERSITE='1', MPLBACKEND='Agg')
    token = ''

    def request(path, body=None, raw=False):
        data = None if body is None else json.dumps(body).encode()
        req = Request(f'http://127.0.0.1:{port}/api'+path, data=data,
                      headers={'X-Power-Token': token, 'Content-Type': 'application/json'})
        with urlopen(req, timeout=180) as response: data = response.read()
        return data if raw else json.loads(data)

    def wait(path):
        deadline = time.monotonic()+180
        while time.monotonic() < deadline:
            value = request(path)
            if value['state'] in ('failed', 'cancelled'): raise AssertionError(value)
            if value['state'] == 'succeeded': return
            time.sleep(.1)
        raise AssertionError('Frozen operation timeout: '+path)

    def caps(n): return [dict(C=(100+i)*1e-6, ESR=.02, ESL=1e-9) for i in range(n)]

    summary = []
    with (output/'service.log').open('w', encoding='utf-8') as log:
        process = subprocess.Popen([str(folder/'PowerDesignWeb.exe'), '--port', str(port)],
            cwd=output, env=env, stdout=log, stderr=subprocess.STDOUT, creationflags=subprocess.CREATE_NO_WINDOW)
        try:
            for _ in range(150):
                if process.poll() is not None: raise AssertionError('Frozen worker exited')
                try: bootstrap = request('/bootstrap'); break
                except OSError: time.sleep(.2)
            else: raise AssertionError('Frozen startup timeout')
            token = bootstrap['token']
            for name, inputs, counts in (('three', 3, (3, 3, 3)), ('large', 12, (1, 4, 27))):
                spec = request('/examples/40W_CCM_3OUT_FLYBACK.json')
                spec['coupling_config']['enabled'] = False
                spec['input_capacitors'] = caps(inputs)
                for row, count in zip(spec['outputs'], counts): row['output_capacitors'] = caps(count)
                job = request('/jobs', {'spec': spec})['id']; wait('/jobs/'+job)
                assert request('/jobs/'+job+'/result')['ok']
                chart = request('/jobs/'+job+'/chart/topology', raw=True)
                with Image.open(io.BytesIO(chart)) as picture:
                    picture.verify()
                (output/(name+'.png')).write_bytes(chart)
                entry = dict(name=name, inputs=inputs, outputs=counts, chart_bytes=len(chart))
                if name == 'three':
                    operation = request('/jobs/'+job+'/export', {'format': 'docx'})['id']
                    wait('/operations/'+operation)
                    document = request('/files/'+operation, raw=True)
                    with ZipFile(io.BytesIO(document)) as archive:
                        assert archive.testzip() is None
                        xml = archive.read('word/document.xml').decode()
                        assert all(ref in xml for ref in ('C_IN3', 'C_O1C', 'C_O2C', 'C_O3C'))
                        assert any(n.startswith('word/media/') for n in archive.namelist())
                    (output/'three.docx').write_bytes(document)
                    entry['word_bytes'] = len(document)
                summary.append(entry)
                print('Frozen topology and report passed:', entry, flush=True)
            (output/'verification.json').write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding='utf-8')
        finally:
            if process.poll() is None:
                for child in reversed(psutil.Process(process.pid).children(recursive=True)):
                    try: child.terminate()
                    except psutil.Error: pass
                process.terminate(); process.wait(timeout=10)


if __name__ == '__main__': check(sys.argv[1])
