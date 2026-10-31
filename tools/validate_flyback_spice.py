"""Reproducible LTspice integration QA; separate Python environments supported.

Prepare with the project Python; run with the existing ltspice-mcp Python.
Only creates dedicated test artifacts. Never changes simulator settings or user
reference schematics, and never loads the complete switching RAW into memory.
"""
import argparse
import json
from pathlib import Path
import sys

ROOT=Path(__file__).resolve().parents[1]
sys.path[:0]=[str(ROOT),str(ROOT/'tests')]


def prepare(stage):
    from config_io import read_default_config
    from design_engine.specification import load_spec
    from spice_export import project_files
    specifications={'nominal':load_spec(read_default_config()),
        'range':dict(load_spec(read_default_config()),V_in_min=24.,V_in_max=36.),
        'multi':load_spec(json.loads((ROOT/'examples/3_OUTPUT_COUPLED_FLYBACK.json').read_text(encoding='utf-8')))}
    for name,p in specifications.items():
        folder=stage/name;folder.mkdir(parents=True,exist_ok=True)
        for filename,data in project_files(p).items():
            # API variations exercise the two values on separately owned RAWs;
            # user exports retain the original native .step directive.
            if name=='range' and filename=='design_params.inc':
                data=('\n'.join(s for s in data.decode().splitlines() if not s.startswith('.step'))+'\n').encode()
            (folder/filename).write_bytes(data)
    print('Prepared:',stage)


def run(stage,config,out):
    import numpy as np
    from ltspice_mcp.api import Api
    from spice_result_helpers import real_forward_raw,log_measurements
    report=dict(simulator='LTspice',cases=[],limitations=[
        'MCP built-in RAW parser byte cap may be exceeded; actual .meas logs and bounded-memory RAW final time are checked independently.',
        'No complete-chip PSR, nonlinear magnetic, temperature or FRA validation.'])
    with Api(working_dir=stage,config_path=config) as api:
        for name in ('nominal','range','multi'):
            deck=stage/name/('Flyback.asc' if name=='nominal' else 'Flyback.cir')
            check=api.verify_circuit(path=str(deck),checks=['symbols','export'] if name=='nominal' else ['syntax'])
            assert not check['failures'],check
            variations=[dict(kind='assign',assign={'VIN':[24,36]})] if name=='range' else []
            receipt=api.run_experiments(circuits=[dict(path=str(deck),id=name)],variations=variations,
                execution=dict(simulator='ltspice',max_parallel=1,run_timeout_s=180))
            assert receipt['completeness']['produced']==receipt['completeness']['expanded'],receipt
            for row in receipt['runs']['items']:
                records,indices=real_forward_raw(row['raw'])
                measured,log=log_measurements(row['log'])
                assert np.isclose(records['time'][-1],.012,rtol=0,atol=1e-12)
                # Starts from a discharged output, not a prebiased target.
                assert abs(float(records['values'][0,indices['v(out1)']]))<1e-5
                for suffix in ('before','after'):
                    assert abs(measured['out1_'+suffix]/30-1)<.03,measured
                assert measured['out1_load_max']<33 and measured['out1_load_min']>27,measured
                assert np.isfinite(list(measured.values())).all()
                for key,value in measured.items():
                    if 'ripple' in key:assert value>=0
                result=dict(name=name,assignments=row['assignments'],job_id=receipt['job_id'],
                    raw=row['raw'],log=row['log'],raw_bytes=Path(row['raw']).stat().st_size,
                    points=len(records),final_time=float(records['time'][-1]),measurements=measured)
                report['cases'].append(result)
                print(json.dumps(result,ensure_ascii=False),flush=True)
                del records
    out.parent.mkdir(parents=True,exist_ok=True)
    out.write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    print('QA report:',out)


if __name__=='__main__':
    parser=argparse.ArgumentParser()
    parser.add_argument('--stage',type=Path,required=True)
    parser.add_argument('--prepare',action='store_true')
    parser.add_argument('--config',type=Path)
    parser.add_argument('--out',type=Path,default=ROOT/'artifacts/qa/flyback-spice/results.json')
    args=parser.parse_args()
    if args.prepare:prepare(args.stage)
    else:
        if args.config is None:parser.error('--config is required to run the existing simulator')
        run(args.stage,args.config,args.out)
