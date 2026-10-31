"""Reproducible two-endpoint sample with genuinely calculated load curves."""
import argparse
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from runtime_resources import configure_numeric_threads
configure_numeric_threads()
from design_api import load_spec
from input_voltage_range import calculate_input_endpoints
from calculation_scheduler import calculate_report_efficiency_curve
from input_range_report import export_input_range_docx


def build(output):
    config = json.loads((ROOT/'examples/3_OUTPUT_COUPLED_FLYBACK.json').read_text(encoding='utf-8'))
    p = load_spec(dict(config, V_in_min=27., V_in_max=33., input_voltage_case='min'))
    snapshot = calculate_input_endpoints(p)
    for case in snapshot['cases']:
        if case.get('result') is None:
            raise RuntimeError(case.get('error') or 'Missing endpoint result')
        case['efficiency_curve'] = calculate_report_efficiency_curve(
            dict(p=case['p'], coupled=bool(case['result']['op'].get('coupled_model'))), lambda: False)
    state = dict(topo='tl431f', dir='fwd', type2=False, vars=dict(
        R1=dict(v=40.,u='k'), CTR=dict(v=1.,u=''),
        Rpullup=dict(v=20.,u='k'), Copto=dict(v=.1,u='n')))
    result = export_input_range_docx(output, snapshot, compensation_state=state)
    summary = dict(result, operating_points=[dict(
        case=case['id'], voltage=case['voltage'], eta=case['result']['eta'],
        duty=case['result']['op']['D'],
        efficiency_failures=case['efficiency_curve']['failures']) for case in snapshot['cases']])
    print(json.dumps(summary, ensure_ascii=False, default=str))


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--out', default=str(ROOT/'reports/三路反激_Vinmin_Vinmax_完整设计报告.docx'))
    build(parser.parse_args().out)
