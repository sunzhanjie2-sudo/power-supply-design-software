from pathlib import Path
import sys,json
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
from runtime_resources import configure_numeric_threads
configure_numeric_threads()
from web_app.metadata import normalize_config,read_example
from optimizer import sweep_efficiency,find_target
from analysis_workflows import corners
from loss_model import compute_design
from plants import build_loop_models
from loop_tuning import analyze_loop
from design_engine.contracts import json_value
import numpy as np
p=normalize_config(read_example('24W_BUCK_VM_TPS40200.json'));p['spice_config']['niso_profile']=0
values,etas=sweep_efficiency(p,'f_sw',25000,100000,5,.5)
out=dict(spec=p,sweep=dict(values=values,etas=etas,target_eta=float((min(etas)+max(etas))/2),target_value=find_target(values,etas,float((min(etas)+max(etas))/2))),corners=corners(p,p['V_in_min'],p['V_in_max'],[.5,1],False),responses=[])
for enabled in (False,True):
    q=normalize_config(read_example('40W_CCM_3OUT_FLYBACK.json'));q['coupling_config']['enabled']=enabled;q['V_in']=q['V_in_min']
    r=compute_design(q);models,_=build_loop_models(q,r['op']);data=analyze_loop(q,models,r['op'],n=320);f=10**np.linspace(-2,6,320)
    full=getattr(models[0],'_multi_output_system',None);fb=q['feedback_output']-1
    g=np.asarray(models[0](2j*np.pi*f)).reshape(-1);c=np.asarray(models[1](2j*np.pi*f)).reshape(-1);ref=g*c/(1+g*c)
    if full is None:references=np.tile(ref,(3,1));loads=None
    else:
        a=np.asarray(full(2j*np.pi*f,squeeze=False));v=np.array([x['V_out'] for x in r['op']['output_ops']]);references=a[:,0]*c/(1+g*c)*v[fb]/v[:,None];loads=a[:,1:]-a[:,0,None,:]*c/(1+g*c)*a[fb,1:][None,:,:]
    out['responses'].append(dict(spec=q,indices=[0,50,100,150,200,250,319],reference_db=20*np.log10(np.maximum(abs(references),1e-300)),load_db=20*np.log10(np.maximum(abs(loads[:,0]),1e-300)) if loads is not None else None))
(ROOT/'tests/fixtures/native_actions_reference.json').write_text(json.dumps(json_value(out),separators=(',',':')),encoding='utf8')
print('Wrote independent sweep, fixed hardware corners and normalized multi-output responses.')
