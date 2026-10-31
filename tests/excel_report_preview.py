"""Build a real coupled three-output sample for Excel visual QA."""
import json
from pathlib import Path
import sys

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from runtime_resources import configure_numeric_threads
configure_numeric_threads()
from design_api import load_spec
from input_voltage_range import calculate_input_endpoints
from calculation_scheduler import calculate_report_efficiency_curve
from report_xlsx import export_input_range_xlsx

if __name__=='__main__':
    config=json.loads((ROOT/'examples/3_OUTPUT_COUPLED_FLYBACK.json').read_text(encoding='utf-8'))
    snapshot=calculate_input_endpoints(load_spec(dict(config,V_in_min=27.,V_in_max=33.,input_voltage_case='max',
        winding_config=dict(window_width=.012,window_height=.006))))
    for case in snapshot['cases']:
        if not case.get('result'): raise RuntimeError(case.get('error'))
        case['efficiency_curve']=calculate_report_efficiency_curve(
            dict(p=case['p'],coupled=True),lambda:False)
    state=dict(topo='tl431f',dir='fwd',type2=False,vars=dict(
        R1=dict(v=40.,u='k'),CTR=dict(v=1.,u=''),
        Rpullup=dict(v=20.,u='k'),Copto=dict(v=.1,u='n')))
    out=ROOT/'reports/Excel模块对照/三路反激_Vinmin_Vinmax_模块设计报告.xlsx'
    print(json.dumps(export_input_range_xlsx(out,snapshot,compensation_state=state),ensure_ascii=False))
