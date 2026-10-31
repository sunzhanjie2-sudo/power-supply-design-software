"""Read the user's unchanged example and collect reproducible tutorial data.

Run with the project scientific environment. This never changes the example,
electrical model, tuning, original reference document, or release packages.
"""
from pathlib import Path
import argparse
import hashlib
import json
import sys
import time

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
from runtime_resources import configure_numeric_threads
configure_numeric_threads()
from design_engine.service import calculate
from design_engine.contracts import json_value
from web_app.presentation import present


def trim(value, key=''):
    if isinstance(value, dict):
        return {k: trim(v, k) for k, v in value.items()
                if k not in ('coupled_solution', 'mos_miller_curve', 'mos_charge_curve',
                             'diode_curves', 'wf', 'f', 'gains', 'phases', 'reference', 'load')}
    if isinstance(value, (list, tuple)):
        return [trim(v) for v in value]
    if hasattr(value, 'tolist'):
        return value.tolist()
    return value


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('source', type=Path)
    args = parser.parse_args()
    folder = ROOT/'artifacts/tutorials/multi_flyback_20261023'
    folder.mkdir(parents=True, exist_ok=True)
    raw = args.source.read_bytes()
    spec = json.loads(raw.decode('utf-8-sig'))
    started = time.perf_counter()
    print('Calculating original endpoints and configured load corners', flush=True)
    run = calculate(spec, analysis='endpoints', include_efficiency=False,
                    include_cross_regulation=True,
                    progress=lambda i,n,label: print(f'{i}/{n} {label}', flush=True))
    run.save(folder/'engineering_snapshot.json', include_waveforms=True)
    bundle = run.runtime_bundle()
    display = present(run)
    data = dict(source=dict(name=args.source.name, sha256=hashlib.sha256(raw).hexdigest()),
                original_reference_sha256=hashlib.sha256((ROOT/'docs/reference/计算方法与公式说明.docx').read_bytes()).hexdigest(),
                elapsed=time.perf_counter()-started,
                spec=trim(run.to_dict(include_waveforms=False, include_details=False)['spec']),
                hardware=trim(bundle.get('hardware')), cases=[],
                cross_regulation=trim(bundle.get('cross_regulation')),
                provenance=run.to_dict(include_waveforms=False, include_details=False)['provenance'])
    from compensation_report import compensation_snapshot
    for case, view in zip(bundle['cases'], display['display']):
        item = dict(id=case['id'], voltage=case['voltage'], error=case.get('error'),
                    parameters=trim(case['p']), display=trim(view),
                    result=trim(case.get('result')), checks=case['checks'], loop_error=case.get('loop_error'))
        if case.get('result'):
            try:
                item['compensation'] = compensation_snapshot(case['p'], case['result']['op'], spec.get('__comp'))
            except Exception as exc:
                item['compensation_error'] = str(exc)
        data['cases'].append(item)
    (folder/'tutorial_data.json').write_text(json.dumps(json_value(data), ensure_ascii=False, indent=2, allow_nan=False), encoding='utf-8')
    from web_app.charts import render
    for kind, output in [('topology',1), ('power',1), ('switching_real',1), ('winding',1),
                         ('outputs',1), ('outputs',2), ('outputs',3), ('loop',1)]:
        try:
            render(run, folder/f'{kind}_{output}.png', 'Vinmin', kind, output=output)
        except Exception as exc:
            print(f'Chart {kind}/{output}: {exc}', flush=True)
    for item in data['cases']:
        result = item.get('result') or {}
        print(json.dumps(dict(id=item['id'], error=item['error'],
            op={k:v for k,v in result.get('op',{}).items() if isinstance(v,(str,float,int,bool))},
            totals={k:v for k,v in result.items() if isinstance(v,(float,int,str,bool))},
            checks=item['checks']), ensure_ascii=False), flush=True)
    print(f'Tutorial data and charts: {folder}; elapsed {time.perf_counter()-started:.1f}s', flush=True)


if __name__ == '__main__':
    main()
