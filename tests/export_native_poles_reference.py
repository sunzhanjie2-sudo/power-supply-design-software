import json,sys
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
from runtime_resources import configure_numeric_threads
configure_numeric_threads()
import control as ct
from loss_model import compute_design
from plants import build_loop_models
from design_engine.contracts import json_value
data=json.loads((ROOT/'tests/fixtures/native_engine_reference.json').read_text(encoding='utf8'))
data+=json.loads((ROOT/'tests/fixtures/native_full_reference.json').read_text(encoding='utf8'))['designs']
out=[]
for row in data:
    p=row['spec'];r=compute_design(p)
    try:
        models,_=build_loop_models(p,r['op']);poles=ct.poles(ct.feedback(models[2],1));stable=bool(all(v.real<0 for v in poles));out.append(dict(name=row['name'],stable=stable,poles=[[v.real,v.imag] for v in poles]))
    except ValueError as e:out.append(dict(name=row['name'],error=str(e)))
    print('Poles',row['name'],flush=True)
(ROOT/'tests/fixtures/native_poles_reference.json').write_text(json.dumps(json_value(out),separators=(',',':')),encoding='utf8')
