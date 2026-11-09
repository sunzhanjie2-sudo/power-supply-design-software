"""Reference-inspired Buck/Boost contracts and passive periodic power stage.

No manufacturer macromodel is used. Comparator commands are in the common
post-conversion domain; physical COMP/ITH offsets are explicitly documented.
"""
from __future__ import annotations
import copy
from functools import lru_cache
import json
import math
from types import SimpleNamespace
import numpy as np

def expm(*args,**kwargs):
    from scipy.linalg import expm as implementation
    globals()['expm']=implementation
    return implementation(*args,**kwargs)

def brentq(*args,**kwargs):
    from scipy.optimize import brentq as implementation
    globals()['brentq']=implementation
    return implementation(*args,**kwargs)

def root(*args,**kwargs):
    from scipy.optimize import root as implementation
    globals()['root']=implementation
    return implementation(*args,**kwargs)

PROFILES={1:dict(name='TPS40200 参考 · Buck 电压模式',topology='BUCK',mode='Voltage Mode',ref=.7,offset=0.,scale=1.,vmin=4.5,vmax=52.),
          2:dict(name='LTC3864 参考 · Buck 峰值电流',topology='BUCK',mode='Peak Current Mode',ref=.8,offset=.8,scale=.05,vmin=3.8,vmax=60.),
          3:dict(name='LM5022 参考 · Boost 峰值电流',topology='BOOST',mode='Peak Current Mode',ref=1.25,offset=1.4,scale=1/3,vmin=6.,vmax=60.)}
SETTINGS={
 'niso_profile':(0.,0.,3.,'Buck/Boost 控制器原型，0=未启用',''),
 'niso_ramp_ratio':(.1,.001,1.,'Buck 电压模式：斜坡幅值 / 输入电压',''),
 'niso_ith_gain':(.05,.001,1.,'LTC3864 参考：ITH 至 CS 等效指令增益（可配置近似）','V/V'),
 'niso_lm_cs_resistor':(0.,0.,10000.,'LM5022 外部 CS 滤波串阻（影响斜坡）','Ω'),
 'niso_inductor_dcr':(-1.,-1.,10.,'自制电感 DCR 覆盖，-1=几何；成品取主界面 DCR','Ω'),
 'niso_edge_model':(0.,0.,1.,'开关边沿：0=快速闭环，1=常数 Coss/Cj',''),
}

def is_enabled(p):
    return p.get('topology') in ('BUCK','BOOST') and float(p.get('spice_config',{}).get('niso_profile',0))>0

def profile(p):
    s=p.get('spice_config',{});n=int(s.get('niso_profile',0))
    n=n or (3 if p['topology']=='BOOST' else 1 if p['control_mode']=='Voltage Mode' else 2)
    d=dict(PROFILES[n],id=n)
    if p['topology']!=d['topology'] or p['control_mode']!=d['mode']:
        raise ValueError('控制器原型与拓扑／控制模式不一致，请选择 '+d['name'])
    if n==2:d['scale']=float(s.get('niso_ith_gain',.05))
    d['source']={1:'https://www.ti.com/lit/ds/symlink/tps40200.pdf',2:'https://www.analog.com/media/en/technical-documentation/data-sheets/ltc3864.pdf',3:'https://www.ti.com/lit/ds/symlink/lm5022.pdf'}[n]
    return d

def preset(number,current=None):
    from spice_export import normalize_settings
    s=dict(current or {})
    s.update(niso_profile=float(number),frequency_hz=0.,soft_start_mode=0.,soft_start_ms=1.,
        step_ms=12.,stop_ms=18.,duty_max=.9,blanking_ns=65.,min_on_ns=100.,delay_ns=10.,
        cs_filter_ns=0.,comp_offset_v=0.,comp_voltage_max=0.,short_mode=0.,olp_enabled=0.,
        cs_limit={1:.1,2:.095,3:.5}[number],slope_mode=1.,fra_start_hz=200.,fra_stop_hz=5000.,
        fra_oct=1.,fra_cycles=100.,cross_enabled=0.,feedback_scale=1.,uvlo=3.,simulation_threads=1.,simulation_timeout_s=180.)
    if number==1:s.update(step_ms=30.,stop_ms=40.,simulation_timeout_s=300.,fra_start_hz=1000.,fra_stop_hz=4000.,fra_amplitude_pct=2.,fra_oct=3.)
    return normalize_settings(s)


# Loading controller characteristics must not silently replace hardware, test
# scheduling, soft-start experiments or the user's compensation coefficients.
REFERENCE_KEYS=('niso_profile','niso_ramp_ratio','niso_ith_gain','niso_lm_cs_resistor',
    'frequency_hz','duty_max','blanking_ns','min_on_ns','delay_ns','cs_limit',
    'slope_mode','cs_filter_ns','comp_offset_v','comp_voltage_max','uvlo')


def reference_settings(number,current):
    from spice_export import normalize_settings
    result=normalize_settings(current)
    reference=preset(number)
    result.update({key:reference[key] for key in REFERENCE_KEYS})
    return normalize_settings(result)

def effective(p):
    q=dict(p);s=q.get('spice_config',{});d=profile(q)
    q['f_sw']=s.get('frequency_hz') or q['f_sw']
    q['A_sense']=1.  # the actual current-sense comparator, not ITH/COMP gain
    if d['id']==1:q['Vm']=(q['V_in']-(q['Vf_din'] if q.get('d_in_enable') else 0))*s.get('niso_ramp_ratio',.1)
    return q

def slope(p,op=None):
    s=p.get('spice_config',{});d=profile(p);fs=s.get('frequency_hz') or p['f_sw']
    design=max(0.,p.get('ma_slope',0))*p['Rs']
    auto=(.75*(p['V_out']+p['Vf_diode'])/p['L']*p['Rs'] if d['id']==2 else
          45e-6*fs*(2000+s.get('niso_lm_cs_resistor',0)) if d['id']==3 else 0.)
    mode=s.get('slope_mode',1)
    return s.get('slope',0) if mode==2 else max(design,auto) if mode==1 else design

class Kernel:
    def __init__(self,p,dcr):
        from output_capacitors import build_output_filters
        self.p=p;self.T=1/p['f_sw'];self.R=p['V_out']**2/p['P_out'];self.block=p['Vf_dout'] if p.get('d_out_enable') else 0.
        self.target=p['V_out']+self.block;self.f=build_output_filters([p],[self.R],[self.target]);self.n=1+len(self.f.A)
        self.bus=p['V_in']-(p['Vf_din'] if p.get('d_in_enable') else 0.);self.dcr=dcr
        self.phases=[self.matrix(on) for on in (True,False,None)]

    def matrix(self,on):
        p=self.p;n=self.n;f=self.f;A=np.zeros((n,n));b=np.zeros(n)
        injection=0. if on is None or (p['topology']=='BOOST' and on) else 1.
        c=np.r_[float(f.D[0,0])*injection,f.C[0]];v0=float(f.D[0,0])*self.block/self.R
        A[1:,1:]=f.A;A[1:,0]=f.B[:,0]*injection;b[1:]=f.B[:,0]*self.block/self.R
        if on is not None:
            R=self.dcr+(p['Rs']+p['Rds_on'] if on else .001)
            sees_output=p['topology']=='BUCK' or not on
            A[0,0]=-R/p['L']
            if sees_output:A[0]-=c/p['L']
            b[0]=((self.bus if on or p['topology']=='BOOST' else 0.)-(p['Vf_diode'] if not on else 0.)-(v0 if sees_output else 0.))/p['L']
        # Additional affine integral is the exact average capacitor-terminal voltage.
        M=np.zeros((n+2,n+2));M[:n,:n]=A;M[:n,-1]=b;M[n,:n]=c;M[n,-1]=v0
        return M

    def flow(self,x,phase,t):
        z=expm(self.phases[phase]*t)@np.r_[x,0.,1.]
        return z[:self.n],float(z[self.n])

    def period(self,x,d,clamp=True):
        x1,v1=self.flow(x,0,d*self.T);remain=(1-d)*self.T
        end,v2=self.flow(x1,1,remain);off=remain
        if clamp and end[0]<0:
            off=brentq(lambda t:self.flow(x1,1,t)[0][0],0,remain,xtol=1e-16)
            z,v2=self.flow(x1,1,off);z[0]=0.
            end,vi=self.flow(z,2,remain-off);v2+=vi
        return end,(v1+v2)/self.T,off/self.T

    def solve(self):
        n=self.n;T=self.T
        def fixed(d):
            E=expm(self.phases[1]*(1-d)*T)@expm(self.phases[0]*d*T)
            x=np.linalg.solve(np.eye(n)-E[:n,:n],E[:n,-1])
            return x,self.period(x,d,False)[1]
        maximum=self.p.get('spice_config',{}).get('duty_max',.95)
        d=brentq(lambda d:fixed(d)[1]-self.target,1e-5,maximum-1e-5,xtol=1e-13)
        x,_=fixed(d)
        if x[0]<0:
            def fun(z):
                v=np.r_[0.,z[:-1]];dn=1/(1+np.exp(-np.clip(z[-1],-30,30)))*maximum
                e,mean,_=self.period(v,dn)
                return np.r_[e[1:]-v[1:],(mean-self.target)/self.target]
            r=root(fun,np.r_[x[1:],math.log(d/(maximum-d))],tol=1e-10)
            if not r.success and max(abs(fun(r.x)))>1e-8:raise ValueError('Buck/Boost DCM 周期解未收敛')
            x=np.r_[0.,r.x[:-1]];d=maximum/(1+np.exp(-r.x[-1]))
        end,mean,off=self.period(x,d)
        err=float(max(abs(end-x)))
        if err>1e-6:raise ValueError('Buck/Boost 周期边界残差过大')
        return x,d,off,err

    def traces(self,x,d,off,points=2048):
        t=np.arange(points)*self.T/points;states=np.zeros((points,self.n));phases=np.where(t<d*self.T,0,np.where(t<(d+off)*self.T,1,2))
        for phase,start,duration in [(0,0,d),(1,d,off),(2,d+off,1-d-off)]:
            indices=np.flatnonzero(phases==phase)
            if len(indices):
                current=self.flow(x,phase,t[indices[0]]-start*self.T)[0]
                E=expm(self.phases[phase]/points*self.T)
                z=np.r_[current,0.,1.]
                for k in indices:states[k]=z[:self.n];z=E@z
            x=self.flow(x,phase,duration*self.T)[0]
            if phase==1 and off<1-d-1e-10:x[0]=0.
        il=states[:,0];on=phases==0;diode=il*(phases==1)
        injection=il if self.p['topology']=='BUCK' else diode
        v=states[:,1:]@self.f.C[0]+self.f.D[0,0]*(injection+self.block/self.R)
        return t,il,on,diode,v

def solve(p,nominal):
    q=effective(p);s=q.get('spice_config',{})
    from magnetics import design_inductor
    ind=design_inductor(nominal,q)
    dcr=s.get('niso_inductor_dcr',-1.)
    from inductor_selection import purchased
    if purchased(q):
        # Purchased component data owns DCR in both calculation and SPICE.
        # Do not silently reuse a stale controller/geometry override.
        dcr=ind['R_dc']
    if dcr<0:
        if not ind.get('ok'):raise ValueError('电感几何设计未成功，无法确定仿真 DCR')
        dcr=ind['R_dc']
    args={k:q[k] for k in ('topology','V_in','V_out','P_out','f_sw','L','Rs','Rds_on','Vf_diode','Vf_din','Vf_dout','d_in_enable','d_out_enable','C_out','Rc','C_out2','Rc2','cout2_enable')}
    args['spice_config']={'duty_max':s.get('duty_max',.9)}
    args['output_capacitors']=q.get('output_capacitors')
    data=copy.deepcopy(_cached_solution(json.dumps(args,sort_keys=True),float(dcr)))
    op=dict(nominal);op.update(data['op'])
    data['model'].update(profile=profile(q),slope_v_per_s=slope(q),Vm=q['Vm'],inductor=ind)
    op['niso_model']=data['model']
    return op

@lru_cache(maxsize=32)
def _cached_solution(encoded,dcr):
    p=json.loads(encoded);k=Kernel(p,dcr);x,d,off,err=k.solve();t,il,on,di,v=k.traces(x,d,off)
    sw=il*on;io=(v-k.block)/k.R;ic=(il if p['topology']=='BUCK' else di)-io
    vds=np.where(on,p['Rds_on']*il,k.bus+p['Vf_diode'] if p['topology']=='BUCK' else v+p['Vf_diode'])
    rms=lambda a:float(np.sqrt(np.mean(a*a)))
    mean=lambda a:float(np.mean(a))
    pin=mean((sw if p['topology']=='BUCK' else il))*p['V_in']
    values=dict(D=d,Dp=off,mode='DCM' if off<1-d-1e-8 else 'CCM',f_sw=p['f_sw'],Ts=k.T,
        I_L_avg=mean(il),I_L_rms=rms(il),I_L_pk=float(max(il)),I_L_min=float(min(il)),dI_L=float(np.ptp(il)),
        I_sw_avg=mean(sw),I_sw_rms=rms(sw),I_sw_pk=float(max(sw)),I_d_avg=mean(di),I_d_rms=rms(di),I_d_pk=float(max(di)),
        V_sw_max=float(max(vds)),V_d_max=float(k.bus if p['topology']=='BUCK' else max(v)),
        V_out=p['V_out'],V_out_cap=k.target,V_feedback=k.target,I_out=p['P_out']/p['V_out'],R=k.R,
        V_out_equiv=k.target,R_equiv=k.R,P_in_est=pin,I_in_est=pin/p['V_in'],
        P_loss_budget=pin-p['P_out'],eta_guess=p['P_out']/pin,efficiency_model='nonisolated_periodic_passive')
    if p['topology']=='BOOST':values['rhp_zero']=k.R*(1-d)**2/(2*math.pi*p['L'])
    model=dict(kind='Buck/Boost passive periodic C+ESR',revision=1,converged=True,initial=x.tolist(),D=d,Dp=off,
        residual=err,dcr=dcr,parameters=p,capacitor_banks=k.f.banks,physical_power_w=pin,
        note='冻结 L/DCR、Rds、采样电阻、二极管压降与每颗并联 C+ESR 的周期解；预设效率不重复叠加。'
             '无 ESL、开关延迟、Coss/Cj、反向恢复或磁芯非线性；峰值采样线性化限于稳定 CCM。')
    return dict(op=values,model=model)

def waveform(op,n_cycles=2,n_pts=2048):
    m=op['niso_model'];k=Kernel(m['parameters'],m['dcr']);t,il,on,di,v=k.traces(np.array(m['initial']),m['D'],m['Dp'],n_pts)
    io=(v-k.block)/k.R;sw=il*on
    vs=np.where(on,k.p['Rds_on']*il,k.bus+k.p['Vf_diode'] if k.p['topology']=='BUCK' else v+k.p['Vf_diode'])
    data=dict(iL=il,i_sw=sw,i_s=di,i_d=di,i_c=(il if k.p['topology']=='BUCK' else di)-io,
        i_in=sw if k.p['topology']=='BUCK' else il,v_sw=vs,vout_ripple=v-np.mean(v))
    result={name:np.tile(a,n_cycles) for name,a in data.items()}
    result.update(t=np.concatenate([t+i*k.T for i in range(n_cycles)]),f_sw=op['f_sw'],Ts=k.T,ripple_pp=float(np.ptp(v)))
    result.update(dt=k.T/n_pts,topology=op['topology'])
    # Match the legacy waveform contract for FFT/input capacitor consumers.
    result['i_cin']=result['i_in']-np.mean(result['i_in'])
    result['vin_ripple']=np.zeros_like(result['t'])
    result.update(v_d=np.tile(np.where(on,op['V_d_max'],0.),n_cycles),
        vout=op['V_out']+result['vout_ripple'],vcap=op['V_out_cap']+result['vout_ripple'],
        v_esl=np.zeros_like(result['t']),ripple_pp_total=result['ripple_pp'],esl_spike_pp=0.,
        i_c_rms=float(np.sqrt(np.mean(result['i_c']**2))),i_cin_rms=float(np.sqrt(np.mean(result['i_cin']**2))))
    return result

def build_loop(p,op):
    import control as ct
    from plants import make_compensator
    q=effective(p);m=op['niso_model'];k=Kernel(m['parameters'],m['dcr']);x=np.array(m['initial']);d=m['D'];n=len(x);T=k.T
    if op['mode']!='CCM':raise ValueError('当前 Buck/Boost 原型为 DCM／跳脉冲，不能提供固定频率 CCM 环路；可查看时域仿真')
    def response(x,d):
        e,v,_=k.period(x,d,False);return np.r_[e,v]
    j=np.zeros((n+1,n+1))
    for i in range(n+1):
        h=1e-6*max(1.,abs(x[i])) if i<n else 1e-6
        xp=x.copy();xm=x.copy();dp=dm=d
        if i<n:xp[i]+=h;xm[i]-=h
        else:dp+=h;dm-=h
        j[:,i]=(response(xp,dp)-response(xm,dm))/(2*h)
    a,b,c,f=j[:n,:n],j[:n,n:],j[n:,:n],j[n:,n:]
    if q['control_mode']=='Peak Current Mode':
        E=expm(k.phases[0]*d*T);at=k.flow(x,0,d*T)[0]
        hx=q['Rs']*E[0,:n];hd=(q['Rs']*(k.phases[0]@np.r_[at,0,1])[0]+slope(q))*T
        if hd<=0:raise ValueError('电流比较器上升斜率非正')
        a=a-b@hx[None,:]/hd;c=c-f@hx[None,:]/hd;b=b/hd;f=f/hd
    else:b=b/q['Vm'];f=f/q['Vm']
    radius=float(max(abs(np.linalg.eigvals(a))))
    if radius>=1.000001:raise ValueError(f'峰值采样内环不稳定（周期特征根 {radius:.4g}），请检查斜坡补偿')
    inv=np.linalg.solve(np.eye(n)+a,np.eye(n));ac=2/T*(a-np.eye(n))@inv;bc=2/T*inv@b;cc=2*c@inv;dc=f-c@inv@b
    g=ct.ss(ac,bc,cc,dc);gc=make_compensator(q).get_transfer_function()
    note=m['note']+' 比较器统一在 CS 等效域；COMP/ITH 增益单独转换，不冒充采样增益。'
    details=dict(kind=m['kind'],profile=profile(q),inner_spectral_radius=radius,esr_included=True,capacitor_banks=k.f.banks,
        assumptions=note,frequency_limit=None,bandwidth_limit_enabled=False,feedback_output=1,
        capacitor_states=len(k.f.A),state_count=n,experimental=False,
        outputs=[dict(id=1,name='OUT1',voltage=op['V_out'],current=op['I_out'])])
    g._loop_metadata=details
    return (g,gc,g*gc),SimpleNamespace(model_note=note,loop_metadata=details,mode=op['mode'])
