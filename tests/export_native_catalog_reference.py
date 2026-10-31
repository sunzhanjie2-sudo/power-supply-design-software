"""Independent Python catalog projection; generated explicitly, never during builds."""
import sys,json,hashlib
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
from runtime_resources import configure_numeric_threads
configure_numeric_threads()
from design_engine.contracts import json_value
from loss_model import compute_design
from component_management import evaluate_components
from design_checks import check_catalog
source=json.loads((ROOT/'tests/fixtures/native_full_reference.json').read_text())
base=json.loads((ROOT/'tests/fixtures/native_engine_reference.json').read_text())
rows=[]
for item in [source['designs'][0],source['designs'][-2],base[0]]:
    p=item['spec'];p['component_management']={'zone':'II','items':{'Q1':{'manufacturer':'Test','model':'Q','package':'SMD','voltage_V':200},'R_S1':{'power_W':1}}}
    print(item['name'],flush=True);r=compute_design(p);e=evaluate_components(p,r)
    rows.append({'name':item['name'],'spec':p,'rows':[{k:v for k,v in row.items() if k in ('ref','kind','quantity')} for row in e['rows']],'checks':[{k:v for k,v in c.items() if k in ('ref','metric','value','rating','factor','limit','state')} for c in e['checks']]})
(ROOT/'tests/fixtures/native_catalog_reference.json').write_text(json.dumps(json_value({'cases':rows}),ensure_ascii=False,indent=2),encoding='utf-8')
