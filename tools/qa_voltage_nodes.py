"""Actual two-endpoint SSR node verification with a bounded native FRA sweep."""
import json
from pathlib import Path
import sys
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))


def main():
    from runtime_resources import configure_numeric_threads
    configure_numeric_threads()
    from tools.diagnose_spice_discrepancy import source
    from design_engine.service import calculate_parameters
    from spice_export import mp6005_preset
    from spice_runtime import compare_design
    _,files=source();p=json.loads(files['design.json'])
    p['spice_config']=mp6005_preset(dict(fra_start_hz=1000,fra_stop_hz=8000,fra_oct=1,fra_cycles=100,cross_enabled=0))
    run=calculate_parameters(p,analysis='endpoints',include_loop=True,include_cross_regulation=True)
    bundle=run.runtime_bundle();assert bundle['cross_regulation']['complete']
    out=ROOT/'artifacts/qa/voltage-nodes-20261025';out.mkdir(parents=True,exist_ok=True)
    from design_engine.contracts import json_value
    (out/'calculated-corners.json').write_text(json.dumps(json_value(bundle['cross_regulation']),ensure_ascii=False,allow_nan=False,indent=2),encoding='utf-8')
    for case in bundle['cases']:
        op=case['result']['op'];assert abs(op['V_out']-30)<1e-9 and abs(op['V_feedback']-30.7)<1e-9
    result=compare_design(run,out/'输出与反馈节点_仿真核对.docx',progress=lambda *x:print(x,flush=True))
    assert result['successful']==2 and result['fra_successful']==2,result
    print(result,flush=True)


if __name__=='__main__':main()
