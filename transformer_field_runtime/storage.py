from __future__ import annotations
from datetime import datetime
import hashlib
import json
import os
from pathlib import Path
import sys
import tempfile


def app_home():
    # The integrated worker never writes beside the EXE or inside the package.
    # Its parent supplies one private directory for each task, including Elmer's
    # optional stack-reserve launch copy and Matplotlib caches.
    value = os.environ.get('POWER_DESIGN_FIELD_WORKDIR')
    if value:
        return Path(value).resolve()
    return Path(tempfile.gettempdir()) / 'PowerDesign' / 'field-runtime'


def strict_json(raw):
    def pairs(items):
        result={}
        for k,v in items:
            if k in result:raise ValueError('JSON键重复：'+k)
            result[k]=v
        return result
    def reject(value):raise ValueError('JSON含非有限数值：'+value)
    return json.loads(raw.decode('utf-8-sig'),object_pairs_hook=pairs,parse_constant=reject)


def read(path):return strict_json(Path(path).read_bytes())
def canonical_json(value):return json.dumps(value,ensure_ascii=False,allow_nan=False,sort_keys=True,separators=(',',':'))
def content_hash(value):return hashlib.sha256(canonical_json(value).encode('utf-8')).hexdigest()


def sha(path):
    h=hashlib.sha256()
    with Path(path).open('rb') as f:
        for block in iter(lambda:f.read(4*1024**2),b''):h.update(block)
    return h.hexdigest()


def write(path,value):
    path=Path(path);path.parent.mkdir(parents=True,exist_ok=True)
    temporary=path.with_name(path.name+'.tmp')
    temporary.write_text(json.dumps(value,ensure_ascii=False,allow_nan=False,indent=2)+'\n',encoding='utf-8')
    os.replace(temporary,path)


def event(stage,message,progress=None,**extra):
    payload=dict(stage=stage,message=message,**extra)
    if progress is not None:payload['progress']=progress
    print('@@EVENT '+json.dumps(payload,ensure_ascii=False,allow_nan=False),flush=True)


def now():return datetime.now().astimezone().isoformat(timespec='seconds')
