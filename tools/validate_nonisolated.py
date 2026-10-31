"""Reproducible native LTspice validation for three public reference profiles."""
from pathlib import Path
import copy,json,sys,time
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
from power_stage import DEFAULT_PARAMS
from nonisolated import preset
from design_engine.specification import load_spec
from design_engine.service import calculate_parameters
from plants import build_loop_models
from loop_tuning import kfactor_tune
from spice_export import project_files

NAMES={1:'24W_BUCK_VM_TPS40200.json',2:'24W_BUCK_PCM_LTC3864.json',3:'24W_BOOST_PCM_LM5022.json'}

def examples():
    for n,name in NAMES.items():
        p=copy.deepcopy(DEFAULT_PARAMS)
        p.update(topology='BOOST' if n==3 else 'BUCK',control_mode='Voltage Mode' if n==1 else 'Peak Current Mode',
            V_in=9. if n==3 else 18.,V_in_min=9. if n==3 else 18.,V_in_max=18. if n==3 else 30.,
            V_out=24. if n==3 else 12.,P_out=24.,f_sw=50e3,L=47e-6,
            C_out=220e-6,Rc=.035,C_out2=10e-6,Rc2=.015,cout2_enable=True,
            Cin1=220e-6,Cin2=10e-6,Rcin1=.035,Rcin2=.015,cin2_enable=True,
            Rds_on=.04,Rs=.05 if n==3 else .02,Vf_diode=.55,Vgs=8. if n==2 else 10.,
            Coss=200e-12,Qg=10e-9,d_in_enable=False,d_out_enable=False,outputs=[],coupling_config={},
            feedback_mode='SSR',feedback_output=1,controller_type='type3' if n==1 else 'type2',
            fc_target=1000.,pm_target=60.,spice_config=preset(n),parasitic_config={})
        p['spice_config']['niso_inductor_dcr']=.03
        p['spice_config'].update(soft_start_ms=1.,step_ms=12.,stop_ms=18.,fra_start_hz=200.,fra_stop_hz=5000.,fra_oct=1.,fra_cycles=100.)
        q=load_spec(p);b=calculate_parameters(q,analysis='endpoints',include_loop=False,include_cross_regulation=False).runtime_bundle()
        c=b['cases'][0];g=build_loop_models(c['p'],c['result']['op'])[0][0]
        p['fc_target']=2000. if n==1 else 1000.
        if n==1:p['spice_config'].update(step_ms=30.,stop_ms=40.,simulation_timeout_s=300.,fra_start_hz=1000.,fra_stop_hz=4000.,fra_oct=3.,fra_amplitude_pct=2.)
        tuned=kfactor_tune(g,p['fc_target'],60.,p['controller_type'])
        for k in ('KP','fz1','fz2','fp1','fp2'):
            if tuned.get(k) is not None:p[k]=tuned[k]
        (ROOT/'examples'/name).write_text(json.dumps(p,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
        print(name,{k:p[k] for k in ('KP','fz1','fp1')},flush=True)

def validate(folder):
    from spice_runtime import _run,read_log,TransientRaw
    from spice_analysis import cycle_quality,steady_quality
    folder=Path(folder);folder.mkdir(parents=True,exist_ok=True);summary=[]
    for n,name in NAMES.items():
        p=load_spec(json.loads((ROOT/'examples'/name).read_text(encoding='utf-8')))
        b=calculate_parameters(p,analysis='endpoints',include_loop=True,include_cross_regulation=False).runtime_bundle()
        files=project_files(p,bundle=b)
        for case in b['cases']:
            path=folder/(str(n)+'_'+case['id']);path.mkdir(exist_ok=True)
            from spice_studies import override_parameters
            f=dict(files);f['design_params.inc']=('\n'.join(l for l in f['design_params.inc'].decode().splitlines() if not l.startswith('.step '))+'\n').encode()
            f=override_parameters(f,{'VIN':case['voltage']})
            for k,v in f.items():(path/k).write_bytes(v)
            elapsed=_run(r'D:\LTSPCIE\LTspice.exe',path,180,lambda:False)
            measured,_,errors,warnings=read_log(path/'Flyback.log')
            raw=TransientRaw(path/'Flyback.raw');raw.names['i(lp)']=raw.names['i(l1)']
            edge=p['spice_config']['step_ms']*.001
            cyc=cycle_quality(raw,p['f_sw'],edge-400/p['f_sw'],edge-10/p['f_sw'],p['Vgs']);steady=steady_quality(raw,p['f_sw'],edge,1)
            raw.close();op=case['result']['op']
            row=dict(profile=n,case=case['id'],voltage=case['voltage'],elapsed=elapsed,errors=errors,warnings=warnings,
                measured=measured,design={k:op[k] for k in ('D','I_L_rms','I_L_pk','I_L_avg','I_d_rms','I_d_avg','V_out','V_sw_max')},
                ripple_design=case['result']['wf']['ripple_pp'],periodicity={k:v for k,v in cyc.items() if k!='cycles'},steady=steady)
            summary.append(row);(folder/'native_summary.json').write_text(json.dumps(summary,ensure_ascii=False,indent=2),encoding='utf-8')
            print(n,case['id'],round(elapsed,2),measured.get('out1_before'),cyc['reason'],steady['reason'],flush=True)

if __name__=='__main__':
    if len(sys.argv)==1 or sys.argv[1]=='examples':examples()
    else:validate(sys.argv[1])
