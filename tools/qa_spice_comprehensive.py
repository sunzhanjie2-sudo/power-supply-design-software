"""Actual application-path FRA/current/ripple/cross-regulation validation."""
import argparse
import json
from pathlib import Path
import sys
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))


def main():
    parser=argparse.ArgumentParser();parser.add_argument('spec',type=Path)
    parser.add_argument('--out',type=Path,default=ROOT/'artifacts/qa/spice-controller-v3/多路反激_全面仿真对比.docx')
    args=parser.parse_args()
    from runtime_resources import configure_numeric_threads
    configure_numeric_threads()
    from design_engine.service import calculate_parameters
    from design_engine.specification import load_spec
    from spice_export import mp6005_preset
    from spice_runtime import compare_design
    p=load_spec(json.loads(args.spec.read_text(encoding='utf-8-sig')));p['spice_config']=mp6005_preset()
    run=calculate_parameters(p,analysis='endpoints',include_loop=True,include_cross_regulation=False)
    result=compare_design(run,args.out,progress=lambda *x:print(x,flush=True))
    print(json.dumps(result,ensure_ascii=False),flush=True)
    assert result['successful']==result['total'],result


if __name__=='__main__':main()
