"""Independent native-ASC export and flattened CIR graph equivalence."""
import argparse
import copy
import json
from pathlib import Path
import re
import sys
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))


def flatten(path, seen=None):
    seen=set() if seen is None else seen;path=Path(path).resolve()
    if path in seen:return []
    seen.add(path);data=path.read_bytes()
    text=data.decode('utf-16') if data.startswith((b'\xff\xfe',b'\xfe\xff')) else data.decode('utf-8-sig')
    lines=[]
    for i,line in enumerate(text.splitlines()):
        s=line.strip().replace('§','')
        if s.startswith(('*',';')) or not s or s.lower() in ('.backanno','.end'):continue
        if i==0 and path.suffix=='.cir':continue
        if s.lower().startswith(('.include ','.lib ')):
            name=s.split(maxsplit=1)[1].strip('"');lines+=flatten(path.parent/name,seen)
        else:lines.append(s)
    return lines


def prepare(stage):
    from design_engine.specification import load_spec
    from spice_export import project_files
    from winding_coupling import default_coupling_config
    base=json.loads((ROOT/'artifacts/qa/acf/example.json').read_text(encoding='utf-8'))
    for n in range(1,7):
        p=copy.deepcopy(base);p['outputs']=(p['outputs']+[copy.deepcopy(p['outputs'][-1]) for _ in range(3)])[:n]
        p['device_curve_settings']=dict(mode='fixed',overrides={})
        p['winding_config']['layer_plan']=[]
        p['coupling_config']=default_coupling_config(n);p['coupling_config']['enabled']=True
        p=load_spec(p);folder=stage/str(n);folder.mkdir(parents=True,exist_ok=True)
        for name,data in project_files(p).items():(folder/name).write_bytes(data)
    print('Prepared',stage)


def verify(stage,config):
    from ltspice_mcp.api import Api
    with Api(working_dir=stage,config_path=config) as api:
        for n in range(1,7):
            folder=stage/str(n)
            result=api.verify_circuit(path=str(folder/'Flyback.asc'),checks=['symbols','export','layout','quality'],
                render=dict(format='svg',delivery='artifact',mode='with_checks'))
            (ROOT/f'artifacts/qa/acf/native_{n}.json').write_text(json.dumps(result,ensure_ascii=False,default=str,indent=2),encoding='utf-8')
            if result.get('failures'):raise RuntimeError(result['failures'])
            print(n,'export',result.get('outcome'),'warnings',len(result.get('warnings',[])),flush=True)
            native=folder/'native_flat.cir';reference=folder/'reference_flat.cir'
            native.write_text('* Native ACF export\n'+'\n'.join(flatten(folder/'Flyback.net'))+'\n.end\n',encoding='utf-8')
            reference.write_text('* Canonical ACF\n'+'\n'.join(flatten(folder/'Flyback.cir'))+'\n.end\n',encoding='utf-8')
            parity=api.verify_circuit(path=str(native),checks=['compare'],compare=dict(reference=str(reference),mode='equivalence'))
            (ROOT/f'artifacts/qa/acf/parity_{n}.json').write_text(json.dumps(parity,ensure_ascii=False,default=str,indent=2),encoding='utf-8')
            if parity.get('failures') or not parity.get('comparison',{}).get('equivalent'):raise RuntimeError(parity)
            print(n,'parity',parity.get('outcome'),flush=True)


if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('mode',choices=['prepare','verify']);p.add_argument('stage',type=Path);p.add_argument('--config');a=p.parse_args()
    prepare(a.stage) if a.mode=='prepare' else verify(a.stage,a.config)
