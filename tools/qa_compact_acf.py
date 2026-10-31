"""Native LTspice smoke comparison for the small-choke catalog example.

Keeps all new evidence separate from the original large-choke reference run.
Only parameter/include decks are written; ASC is copied from verified templates.
"""
import json
from pathlib import Path
import sys

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))


def main():
    from runtime_resources import configure_numeric_threads
    configure_numeric_threads()
    from design_engine.specification import load_spec
    from design_engine.service import calculate_parameters
    from spice_export import project_files
    from spice_runtime import _run,read_log,find_ltspice,TransientRaw
    from spice_analysis import steady_quality
    p=load_spec(json.loads((ROOT/'examples/33W_3OUT_ACF_MP6005_COMPACT.json').read_text(encoding='utf-8')))
    # No load step in this smoke run. Keep controller and device models exactly
    # as the shipped example; FRA/corner scans are separate user operations.
    p['spice_config'].update(fra_enabled=0.,cross_enabled=0.,step_ms=35.,stop_ms=36.,load_after=1.)
    run=calculate_parameters(p,analysis='endpoints',include_loop=True,include_cross_regulation=False)
    bundle=run.runtime_bundle()
    files=project_files(p,bundle=bundle)
    base=ROOT/'artifacts/qa/example_catalog_20261028'
    evidence=[]
    for case in bundle['cases']:
        if case.get('error') or case.get('loop_error'):raise RuntimeError(str(case))
        vin=case['voltage'];folder=base/('vin'+str(int(vin)));folder.mkdir(parents=True,exist_ok=True)
        for name,data in files.items():
            if name=='design_params.inc':
                lines=[s for s in data.decode().splitlines() if not s.startswith('.step ')]
                lines=[f'.param VIN={vin:.12g}' if s.startswith('.param VIN=') else s for s in lines]
                data=('\n'.join(lines)+'\n').encode()
            (folder/name).write_bytes(data)
        print('Native LTspice start',vin,flush=True)
        elapsed=_run(find_ltspice(),folder,600,lambda:False)
        measurements,_,errors,_=read_log(folder/'Flyback.log')
        if errors:raise RuntimeError(str(errors))
        raw=TransientRaw(folder/'Flyback.raw')
        try:
            steady=steady_quality(raw,case['p']['f_sw'],.035,3)
            default_step_steady=steady_quality(raw,case['p']['f_sw'],.025,3)
        finally:raw.close()
        op=case['result']['op']
        row=dict(vin=vin,elapsed_s=elapsed,measurements=measurements,steady=steady,
            default_step_steady=default_step_steady,
            calculation=[{k:c[k] for k in ('V_out','I_L_pk','I_L_min','I_s_rms','mode')} for c in op['output_ops']])
        evidence.append(row)
        (base/'native_verification.json').write_text(json.dumps(evidence,ensure_ascii=False,indent=2),encoding='utf-8')
        print(json.dumps(dict(vin=vin,steady=steady.get('passed'),vout=[measurements.get(f'out{i}_before') for i in (1,2,3)],fault=measurements.get('fault_max')),ensure_ascii=False),flush=True)


if __name__=='__main__':main()
