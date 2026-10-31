"""Long-startup recheck of existing real corner evidence, no sweep rerun."""
import argparse
import json
from pathlib import Path
import sys
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
from spice_studies import retry_cross_corners,finalize_cross
from spice_runtime import _run,find_ltspice
from isolated_outputs import output_specs

if __name__=='__main__':
    a=argparse.ArgumentParser();a.add_argument('voltage',type=int);args=a.parse_args()
    folder=ROOT/f'artifacts/qa/acf/cross_{args.voltage}_b'
    result=json.loads((folder/'result.json').read_text(encoding='utf-8'))
    if not result.get('time_includes_retries'):
        result['elapsed_s']+=sum(r.get('retry',{}).get('elapsed_s',0) for r in result['records'])
        result['time_includes_retries']=True
    meta=json.loads((folder/'manifest.json').read_text(encoding='utf-8'))
    p=json.loads((folder/'design.json').read_text(encoding='utf-8'));rails=output_specs(p)
    files={f.name:f.read_bytes() for f in folder.iterdir() if f.is_file() and f.name!='result.json' and f.suffix in ('.cir','.lib','.inc','.json')}
    retry_cross_corners(result,files,meta,meta['settings'],folder,
        lambda f,t:_run(find_ltspice(),f,t,lambda:False),rails,progress=lambda m:print(m,flush=True))
    finalize_cross(result,rails,meta['feedback_output'])
    (folder/'result.json').write_text(json.dumps(result,ensure_ascii=False,allow_nan=False,indent=2),encoding='utf-8')
    print('complete',result['complete'],'settled',result['settled_cases'],flush=True)
