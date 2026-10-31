"""Rebuild the editable dual-source OR-ing auxiliary-network example."""
import json
from pathlib import Path
import sys
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
import system_workspace as w

p=w.fresh_project(json.loads((ROOT/'examples/24W_BUCK_VM_TPS40200.json').read_text(encoding='utf-8')))
p.update(title='双源竞争供电与负载分配示例',sources=[
    dict(id='BUS-01',name='主辅源 24V',min=24,max=28,capacity=100,enabled=True),
    dict(id='BUS-02',name='电池备用辅源',min=22,max=26,capacity=80,enabled=True)],
    junctions=[dict(id='OR-01',name='24V 二极管竞争母线',capacity=50,enabled=True)],
    loads=[dict(id='LOAD-01',name='24V 风扇',power=2,min=20,max=30,enabled=True),
           dict(id='LOAD-02',name='控制板 DSP 与采样',power=3,min=10,max=14,enabled=True),
           dict(id='LOAD-03',name='继电器与通信',power=2,min=10,max=14,enabled=True)],connections=[])
p['units'][0]['name']='12V 控制电源'
p=w.normalize_project(p)
def link(source,target,kind='bus',vf=.3):
    edge=w.connect(p,target,dict(kind=kind,id=source,output=1))
    next(e for e in p['connections'] if e['id']==edge)['vf']=vf
link('BUS-01','OR-01');link('BUS-02','OR-01',vf=.5)
link('OR-01','PSU-01','junction');link('OR-01','LOAD-01','junction')
link('PSU-01','LOAD-02','unit');link('PSU-01','LOAD-03','unit')
w.sync_input(p,'PSU-01');w.auto_layout(p)
w.save_project(p,ROOT/'examples/SYSTEM_AUX_ORING.json')
print('Built examples/SYSTEM_AUX_ORING.json')
