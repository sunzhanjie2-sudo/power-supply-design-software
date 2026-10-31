"""Independent migration fixtures; never imported or executed by the web app."""
import copy,json,sys,hashlib
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
from runtime_resources import configure_numeric_threads
configure_numeric_threads()
from design_engine.contracts import json_value
from web_app.metadata import read_example,normalize_config
from loss_model import compute_design
from plants import build_loop_models
from compensation_report import compensation_snapshot
from parasitic_ringing import solve_edge

def main():
    out={'sources':{n:hashlib.sha256((ROOT/(n+'.py')).read_bytes()).hexdigest() for n in ('acf_periodic','acf_loop','acf_cross','mp6005','comp_design','compensation_report','parasitics','parasitic_ringing','transformer_turns')},'designs':[],'compensation':[],'edges':[]}
    base=normalize_config(read_example('40W_CCM_3OUT_FLYBACK.json'))
    psr=copy.deepcopy(base);psr.update(feedback_mode='PSR-MP6005',coupling_config={'enabled':False},Rs=.015)
    auto=copy.deepcopy(base);auto.update(Np=0);auto['outputs'][1]['Ns']=0
    cases=[('psr',psr),('automatic-turns',auto),('acf',normalize_config(read_example('33W_3OUT_ACF_MP6005_COMPACT.json')))]
    for label,p in cases:
        for vin in sorted(set([p['V_in_min'],p['V_in_max']])):
            q=dict(p,V_in=vin,input_voltage_case='max' if vin==p['V_in_max'] and p['V_in_min']!=vin else 'min')
            print('Reference design',label,vin,flush=True)
            res=compute_design(q);op=res['op']
            keys=('D','Dp','f_sw','V_out','I_out','I_sw_pk','I_sw_rms','I_sw_on','I_sw_off','I_d_rms','I_d_pk','V_sw_max','V_d_max','P_out')
            expected={'op':{k:op.get(k) for k in keys},'outputs':[{k:c.get(k) for k in keys} for c in op.get('output_ops',[])],'psr':res.get('psr'),'losses':{k:res[k] for k in ('P_semi','P_mag','P_cap','P_cap_in','P_controller','P_parasitic','P_total','eta')}}
            try:
                models,_=build_loop_models(q,op);expected['gain']=[[complex(models[0](2j*3.141592653589793*f)).real,complex(models[0](2j*3.141592653589793*f)).imag] for f in [1,10,100,1000,10000]]
            except ValueError as e:expected['loop_error']=str(e)
            if op.get('acf_model'):expected['acf']={k:op['acf_model'][k] for k in ('normalized_residual','energy_balance_W','output_voltages','mesh')}
            out['designs'].append(dict(name=label+'/'+str(vin),spec=q,expected=expected))
    p=dict(base,controller_type='type2');op={'V_out':30,'V_feedback':30.7}
    inputs={'opamp3':dict(R1=10000,Vref=2.5),'gm3':dict(R2=10000,R1u=100000,gm=.002),'tl431nf':dict(R1=40000,R_LED=1000,CTR=1,Rpullup=20000,Copto=.1e-9),'tl431f':dict(R1=40000,CTR=1,Rpullup=20000,Copto=.1e-9)}
    for key,values in inputs.items():
        for kind in ('type2','type3'):
            q=dict(p,controller_type=kind,KP=3000,fz1=200,fp1=12000,fz2=300,fp2=30000)
            state=dict(key=key,dir='fwd',type2=False,vars={k:dict(v=v,u='') for k,v in values.items()})
            d=compensation_snapshot(q,op,state);out['compensation'].append(dict(name=key+'/'+kind,p=q,op=op,state=state,expected=d))
            rev=dict(state,dir='rev',vars={k:dict(v=v,u='') for k,v in d['parts'].items() if isinstance(v,(int,float))});out['compensation'].append(dict(name=key+'/'+kind+'/reverse',p=q,op=op,state=rev,expected=compensation_snapshot(q,op,rev)))
    for i,kwargs in enumerate([dict(inductance=150e-9,capacitance=200e-12,resistance=.05,current=5,plateau=60,ceiling=90,duration=3e-6),dict(inductance=150e-9,capacitance=200e-12,resistance=.05,current=5,plateau=60,snub_r=10,snub_c=1e-9,duration=3e-6),dict(inductance=80e-9,capacitance=20e-12,resistance=.15,current=0,plateau=70,initial_voltage=0,duration=1e-6)]):
        print('Reference RLC',i,flush=True);d=solve_edge(**kwargs);out['edges'].append(dict(params=kwargs,expected={k:d.get(k) for k in ('peak','frequency','clamped','energy_initial','energy_final')}))
    path=ROOT/'tests/fixtures/native_full_reference.json';path.write_text(json.dumps(json_value(out),ensure_ascii=False,separators=(',',':')),encoding='utf-8');print('Wrote',path,flush=True)

if __name__=='__main__':main()
