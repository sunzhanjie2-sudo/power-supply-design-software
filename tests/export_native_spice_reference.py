from pathlib import Path
import sys,json,re,hashlib
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
from runtime_resources import configure_numeric_threads
configure_numeric_threads()
from web_app.metadata import read_example,normalize_config
from spice_export import project_files
out=[]
for name in ['40W_CCM_3OUT_FLYBACK.json','33W_3OUT_ACF_MP6005_COMPACT.json','90W_QR_L6565_300V.json','24W_BUCK_VM_TPS40200.json','24W_BUCK_PCM_LTC3864.json','24W_BOOST_PCM_LM5022.json']:
    p=normalize_config(read_example(name));print('SPICE files only',name,flush=True);files=project_files(p);params=dict(re.findall(r'(?m)^\.param (\w+)=(.*)$',files['design_params.inc'].decode('ascii')))
    out.append(dict(name=name,spec=p,params=params,stage=files['power_stage.inc'].decode('ascii'),symbols={k:hashlib.sha256(v).hexdigest() for k,v in files.items() if k.endswith('.asy')}))
(ROOT/'tests/fixtures/native_spice_reference.json').write_text(json.dumps(out,separators=(',',':')),encoding='utf8')
