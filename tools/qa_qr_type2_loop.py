"""New native QR unity-CS evidence; does not reuse the old gain-11 run."""
import json
from pathlib import Path
import sys
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))


def main():
    from runtime_resources import configure_numeric_threads
    configure_numeric_threads()
    from design_engine.specification import load_spec
    from design_engine.service import calculate_parameters
    from spice_export import project_files
    from spice_runtime import _run,read_log,TransientRaw,find_ltspice
    from spice_analysis import steady_quality
    from qr_spice_analysis import cycle_quality
    from spice_studies import run_fra
    p=load_spec(json.loads((ROOT/'examples/90W_QR_L6565_300V.json').read_text(encoding='utf-8')))
    p['spice_config'].update(simulation_timeout_s=600.,fra_timeout_s=1200.)
    run=calculate_parameters(p,analysis='endpoints',include_loop=True,include_cross_regulation=False)
    case=run.runtime_bundle()['cases'][0]
    files=project_files(p,bundle=run.runtime_bundle());meta=json.loads(files['manifest.json'])
    base=ROOT/'artifacts/qa/qr_type2_20261029';folder=base/'nominal';folder.mkdir(parents=True,exist_ok=True)
    for name,data in files.items():
        if name=='design_params.inc':data=('\n'.join(s for s in data.decode().splitlines() if not s.startswith('.step '))+'\n').encode()
        (folder/name).write_bytes(data)
    print('New QR gain-1 transient start',flush=True)
    _run(find_ltspice(),folder,600,lambda:False)
    m,_,errors,warnings=read_log(folder/'Flyback.log')
    if errors:raise ValueError(str(errors))
    raw=TransientRaw(folder/'Flyback.raw')
    try:
        cycles=cycle_quality(raw,case['result']['op']['f_sw'],.07,.079)
        fs=cycles.get('frequency_mean_hz',case['result']['op']['f_sw'])
        steady=steady_quality(raw,fs,.08,1)
    finally:raw.close()
    evidence=dict(parameters=p,measurements=m,periodicity=cycles,steady=steady,warnings=warnings)
    path=base/'verification.json';path.write_text(json.dumps(evidence,ensure_ascii=False,indent=2),encoding='utf-8')
    print('QR nominal',dict(stable=cycles['stable'],steady=steady['passed'],vout=m.get('out1_before'),frequency=fs),flush=True)
    if not cycles['stable'] or not steady['passed'] or m.get('fault_max',0)>.5:
        raise ValueError('新QR工作点未通过稳态/周期检查，未发布有效FRA')
    meta['qr_measured_min_frequency_hz']=cycles.get('frequency_min_hz',fs)
    evidence['fra']=run_fra(files,case,meta,meta['settings'],base/'FRA',
        lambda folder,timeout:_run(find_ltspice(),folder,timeout,lambda:False),
        progress=lambda message:print(message,flush=True))
    path.write_text(json.dumps(evidence,ensure_ascii=False,indent=2),encoding='utf-8')
    print('QR actual FRA',evidence['fra'].get('available'),evidence['fra'].get('error'),flush=True)


if __name__=='__main__':main()
