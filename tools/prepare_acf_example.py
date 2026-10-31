"""Reproducible, explicit migration of the user's 3-output flyback example."""
import copy
import hashlib
import json
from pathlib import Path
import sys
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from config_io import decode_config
from acf_spice import preset


def parameters(source):
    p=decode_config(json.loads(source.read_text(encoding='utf-8-sig')))
    p.update(topology='ACF-FORWARD',Np=8,Ns=30,N=8/30,L=1e-3,
             Lm_forward=220e-6,C_clamp=100e-9,forward_dead_time=100e-9,
             forward_d_max=.7,P_out=33.,controller_type='type2',
             KP=100.,fz1=100.,fp1=15000.,ma_slope=0.,fc_target=125.,pm_target=58.)
    for r,ns,ind in zip(p['outputs'],(30,13,6),(1e-3,1.5e-3,220e-6)):
        r.update(Ns=ns,L=ind)
    # Preserve all output cap banks, load powers and paired coupling data.
    p['winding_config']=copy.deepcopy(p['winding_config'])
    # Each 15-turn section occupies two physical layers in the retained window.
    # Keep any radial overflow visible instead of giving the UI an invalid
    # 15-turn physical layer that raises while rendering the winding page.
    p['winding_config']['layer_plan']=[dict(winding_id='OUT1',turns=9),dict(winding_id='OUT1',turns=6),
        dict(winding_id='P',turns=8),dict(winding_id='OUT2',turns=13),dict(winding_id='OUT3',turns=6),
        dict(winding_id='OUT1',turns=9),dict(winding_id='OUT1',turns=6)]
    from device_curve_sources import inferred_settings
    p['device_curve_settings']=inferred_settings(p)
    p['device_curve_settings']['overrides'].update({f'D_F{i}':'fixed' for i in range(1,4)})
    p['spice_config']=preset(dict(fra_start_hz=100.,fra_stop_hz=4000.,fra_oct=2.,fra_cycles=500.,fra_amplitude_pct=.5,
        simulation_timeout_s=600.,fra_timeout_s=1200.,cross_timeout_s=1800.,
        cross_hold_ms=40.,step_ms=25.,stop_ms=35.))
    from design_engine.specification import load_spec
    return load_spec(p)


if __name__=='__main__':
    source=Path(sys.argv[1]);p=parameters(source)
    from design_engine.service import calculate_parameters
    run=calculate_parameters(p,analysis='endpoints',include_loop=False,include_cross_regulation=False)
    bundle=run.runtime_bundle()
    for c in bundle['cases']:
        if c.get('error'):raise ValueError(c['error'])
        o=c['result']['op']
        print(c['id'],c['voltage'],o['D'],[(x['op']['V_out'],x['op']['mode']) for x in c['result']['outputs']])
    from spice_export import project_files
    d=ROOT/'artifacts/qa/acf/bench';d.mkdir(parents=True,exist_ok=True)
    for name,data in project_files(p,bundle=bundle).items():
        if name=='design_params.inc':
            data=('\n'.join(s for s in data.decode().splitlines() if not s.startswith('.step '))+'\n').encode()
        (d/name).write_bytes(data)
    (ROOT/'artifacts/qa/acf/example.json').write_text(json.dumps(p,ensure_ascii=False,indent=2),encoding='utf-8')
