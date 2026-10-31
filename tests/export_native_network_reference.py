"""Generate independent Python reference vectors for the browser network port."""
import copy,json,hashlib
from pathlib import Path
import sys
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
from tests.power_network_check import base,link
import system_workspace as model

rows=[]
def add(name,p):
    p=model.normalize_project(p);rows.append(dict(name=name,project=p,expected=model.checks(p)))
p=base();link(p,'DSP','A');link(p,'DSP','B',vf=.5);add('unequal-OR',p)
p=copy.deepcopy(p);p['sources'][1].update(min=24,max=24);p['connections'][1]['vf']=.3;add('equal-OR-no-sharing',p)
p=copy.deepcopy(p);p['sources'][0]['enabled']=False;add('disabled-primary',p)
p=copy.deepcopy(p);p['sources'][1]['enabled']=False;add('all-sources-off',p)
p=model.load_project(ROOT/'examples/SYSTEM_AUX_ORING.json');add('junction-fanout-converter-loads',p)
p=copy.deepcopy(p);p['sources'][0].update(min=21,max=29);p['sources'][1].update(min=23,max=27);add('input-voltage-reversal',p)
p=copy.deepcopy(p);p['connections'][0]['enabled']=False;add('disabled-diode-branch',p)
p=model.load_project(ROOT/'examples/SYSTEM_AUX_ORING.json');p['sources'][1]['capacity']=5;add('backup-overload',p)
p=base();p['sources'][1].update(min=24,max=24);p['loads']=[]
for i in range(9):
    n='LOAD'+str(i);p['loads'].append(dict(id=n,name=n,power=1,min=0,max=0,enabled=True));link(p,n,'A');link(p,n,'B')
add('tie-enumeration-cap',p)
out=ROOT/'tests/fixtures/native-network-reference.json';out.write_text(json.dumps(dict(python_sha256=hashlib.sha256((ROOT/'power_network.py').read_bytes()).hexdigest(),cases=rows),ensure_ascii=False,indent=2),encoding='utf-8')
print('Generated',len(rows),'independent network cases')
