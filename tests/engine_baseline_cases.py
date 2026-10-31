"""Stable pre-refactor calculation cases; not a statement of physical accuracy.

Run this file to print candidate metrics. Committed reference values must only
be updated after a reviewed model change, never automatically during tests.
"""
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from runtime_resources import configure_numeric_threads
configure_numeric_threads()

CASES = ('40W_CCM_FLYBACK.json', 'spec_buck.json', 'spec_flyback.json',
         '40W_ACF_FORWARD.json', '6_OUTPUT_FLYBACK_SSR.json',
         '3_OUTPUT_COUPLED_FLYBACK.json', 'MP6005_PSR_FLYBACK.json')


def case_spec(name):
    return json.loads((ROOT / 'examples' / name).read_text(encoding='utf-8'))


def metrics(snapshot):
    result, op = snapshot['res'], snapshot['op']
    mag = result.get('mag', {})
    dev = mag.get('transformer') or mag.get('inductor') or {}
    return dict(D=op['D'], I_L_pk=op['I_L_pk'], I_sw_rms=op['I_sw_rms'],
                V_sw_max=op['V_sw_max'], eta=result['eta'],
                P_total=result['P_total'], ripple_pp=snapshot['wf']['ripple_pp'],
                mode=op['mode'], P_core=dev.get('P_core'))


if __name__ == '__main__':
    from design_api import load_spec
    from analysis_workflows import evaluate
    values, type_paths = {}, {}

    def visit(value, path):
        name = type(value).__module__ + '.' + type(value).__name__
        type_paths.setdefault(name, path)
        if isinstance(value, dict):
            for key, child in value.items():
                visit(child, path + '.' + str(key))
        elif isinstance(value, (list, tuple)):
            for child in value:
                visit(child, path + '[]')

    for name in CASES:
        snapshot = evaluate(load_spec(case_spec(name)))
        values[name] = metrics(snapshot)
        visit(snapshot['res'], 'res')
        print(name + ': captured', file=sys.stderr, flush=True)
    print(json.dumps(values, ensure_ascii=False, indent=2))
    print(json.dumps(type_paths, ensure_ascii=False), file=sys.stderr)
