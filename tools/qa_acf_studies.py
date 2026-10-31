"""Real simulator checkpoints; no recorded or synthetic FRA substitute."""
import argparse
import json
from pathlib import Path
import sys
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
from design_engine.specification import load_spec
from design_engine.service import calculate_parameters
from spice_export import project_files
from spice_studies import run_fra,run_cross
from spice_runtime import _run,find_ltspice

if __name__=='__main__':
    a=argparse.ArgumentParser();a.add_argument('study',choices=['fra','cross']);a.add_argument('--voltage',type=int,default=20);a.add_argument('--revision',default='a');args=a.parse_args()
    p=load_spec(json.loads((ROOT/'artifacts/qa/acf/example.json').read_text(encoding='utf-8')))
    run=calculate_parameters(p,analysis='endpoints',include_loop=True,include_cross_regulation=False)
    bundle=run.runtime_bundle();case=next(c for c in bundle['cases'] if c['voltage']==args.voltage)
    files=project_files(p,bundle=bundle);meta=json.loads(files['manifest.json']);s=meta['settings']
    files['design_params.inc']=('\n'.join(x for x in files['design_params.inc'].decode().splitlines() if not x.startswith(('.step ','.param VIN=')))+f'\n.param VIN={args.voltage}\n').encode()
    folder=ROOT/f'artifacts/qa/acf/{args.study}_{args.voltage}_{args.revision}'
    execute=lambda f,t:_run(find_ltspice(),f,t,lambda:False)
    result=(run_fra(files,case,meta,s,folder,execute,progress=lambda m:print(m,flush=True)) if args.study=='fra'
        else run_cross(files,case,meta,s,folder,execute))
    (folder/'result.json').write_text(json.dumps(result,ensure_ascii=False,allow_nan=False,indent=2),encoding='utf-8')
    print(json.dumps({k:v for k,v in result.items() if k not in ('waveform','design','simulation','original','records')},ensure_ascii=False),flush=True)
