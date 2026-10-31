"""End-to-end v2 comparison smoke; actual LTspice and the shared design engine."""
import argparse
import json
from pathlib import Path
import sys
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))


def main():
    parser=argparse.ArgumentParser();parser.add_argument('--multi',type=Path)
    parser.add_argument('--output',type=Path,default=ROOT/'artifacts/qa/spice-controller-v2')
    args=parser.parse_args()
    from runtime_resources import configure_numeric_threads
    configure_numeric_threads()
    from config_io import read_default_config
    from design_engine.specification import load_spec
    from design_engine.service import calculate_parameters
    from spice_export import mp6005_preset
    from spice_runtime import compare_design
    configurations=[('单路MP6005参考',load_spec(read_default_config()))]
    if args.multi:configurations.append(('多路MP6005参考',load_spec(json.loads(args.multi.read_text(encoding='utf-8-sig')))))
    for name,p in configurations:
        p['spice_config']=mp6005_preset()
        run=calculate_parameters(p,analysis='endpoints',include_loop=False,include_cross_regulation=False)
        print(name,[(c['voltage'],len(c['result']['outputs'] or [])) for c in run.runtime_bundle()['cases']],flush=True)
        result=compare_design(run,args.output/(name+'_对比报告.docx'),progress=lambda *x:print(x,flush=True))
        print(result,flush=True)
        assert result['successful']==result['total'],result


if __name__=='__main__':main()
