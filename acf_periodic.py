"""Independent periodic MNA model of a diode active-clamp forward stage.

Linear winding matrix, DCR, two rectifiers and one choke per output, physical
clamp capacitor/ESR, constant Coss/Cj and two nonoverlapping switches. Output
capacitor DC voltages are shooting unknowns, fixed by charge balance and one
feedback constraint. No LTspice data or fitted correction factors are used.
"""
from __future__ import annotations

import copy
import json
from functools import lru_cache
import numpy as np
from scipy.optimize import root


class PeriodicForward:
    def __init__(self,p,rails,geometry,model,*,points=512):
        from voltage_nodes import input_drop,output_drop
        self.p=p;self.rails=rails;self.geometry=geometry;self.n=len(rails)
        n=self.n;self.w=slice(0,n+1);self.o=slice(n+1,2*n+1)
        self.v=slice(2*n+1,4*n+3);self.c=4*n+3;self.cs=self.c+1
        self.cj=slice(self.cs+1,self.cs+1+2*n+2);self.size=self.cj.stop
        from parasitics import resolved
        self.parasitics=resolved(p,n)
        self.extra_rc=[]
        if self.parasitics['snub_c_primary']:
            self.extra_rc.append((2*n+1,None,self.parasitics['snub_r_primary'],self.parasitics['snub_c_primary']))
        for j,r in enumerate(self.parasitics['rails']):
            if r['snub_c']:self.extra_rc.append((2*n+3+2*j,2*n+4+2*j,r['snub_r'],r['snub_c']))
        self.extra_start=self.size;self.size+=len(self.extra_rc)
        self.nodes=2*n+2;self.base=2*n+1
        self.T=1/float(p['f_sw']);self.dead=float(p.get('forward_dead_time',0))
        self.points=points;self.vin=float(p['V_in'])-input_drop(p)
        self.block=np.array([output_drop(r) for r in rails])
        self.load=np.array([r['V_out']**2/max(r['P_out'],1e-12) for r in rails])
        self.target=float(rails[int(p.get('feedback_output',1))-1]['V_out'])
        self.fb=int(p.get('feedback_output',1))-1
        self.vf=np.array([r['Vf_diode'] for r in rails])
        self.L=np.array(model['L']);self.R=np.array(model['R']);self.K=np.asarray(model['K']).tolist()
        self.E=np.zeros((self.size,self.size));self.A=np.zeros_like(self.E)
        self.b=np.zeros(self.size);self.B=np.zeros((self.size,n))
        self.E[self.w,self.w]=self.L
        self.E[self.o,self.o]=np.diag([r['L'] for r in rails])
        self.A[self.w,self.w]=-np.diag(self.R)
        self.A[0,self.base]=-1;self.b[0]=self.vin
        self.A[self.base,0]=1
        for j in range(n):
            rect,choke=self.base+2+2*j,self.base+3+2*j
            self.A[j+1,rect]=1;self.A[rect,j+1]=-1
            self.A[n+1+j,choke]=1;self.A[choke,n+1+j]=-1
            self.B[n+1+j,j]=-1;self.b[n+1+j]=-self.block[j]
        # The same constant capacitance assumptions as the export library.
        cj=float(p.get('_acf_cj',20e-12))
        caps=np.zeros((self.nodes,self.nodes))
        caps[0,0]=max(float(self.parasitics['coss']),1e-12)+self.parasitics['cw_primary']
        caps[1,1]=max(float(self.parasitics['coss_aux']),1e-12)
        for j,r in enumerate(self.parasitics['rails']):caps[2+2*j,2+2*j]+=r['cw']
        self.E[self.v,self.v]=caps
        self.cj_pairs=[(self.base,None),(self.base+1,None)]
        for j in range(n):self.cj_pairs.extend([(self.base+2+2*j,self.base+3+2*j),(self.base+3+2*j,None)])
        # Coss already includes the MOS drain/body junction capacitance.
        # Preserve old projects, but do not count it twice in the unified model.
        self.cj_values=([0.,0.] if p.get('parasitic_config') else [self.parasitics['cj_default']]*2)
        for r in self.parasitics['rails']:self.cj_values.extend([r['cj'],r['cj_free']])
        for index,((a,b),cj) in enumerate(zip(self.cj_pairs,self.cj_values),self.cj.start):
            stamp=np.zeros(self.size);stamp[a]=1;stamp[index]=-1
            if b is not None:stamp[b]=-1
            self.E[index,index]=cj
            resistance=self.parasitics['r_cj']
            self.A[a]-=stamp/resistance
            if b is not None:self.A[b]+=stamp/resistance
            self.A[index]+=stamp/resistance
        for index,(a,b,r,c) in enumerate(self.extra_rc,self.extra_start):
            stamp=np.zeros(self.size);stamp[a]=1;stamp[index]=-1
            if b is not None:stamp[b]=-1
            self.E[index,index]=c
            self.A[a]-=stamp/r
            if b is not None:self.A[b]+=stamp/r
            self.A[index]+=stamp/r
        cc=float(p['C_clamp']);esr=max(float(p['ESR_clamp']),1e-5)
        self.E[self.c,self.c]=cc
        self.E[self.cs,self.cs]=max(float((p.get('spice_config') or {}).get('cs_filter_ns',15))*1e-9,1e-12)
        self.A[self.cs,self.cs]=-1.
        # iC=(Vd-Vaux-Vc)/ESR, positive from drain towards auxiliary.
        stamp=np.zeros(self.size);stamp[self.base]=1;stamp[self.base+1]=-1;stamp[self.c]=-1
        self.A[self.base]-=stamp/esr;self.A[self.base+1]+=stamp/esr;self.A[self.c]+=stamp/esr
        self.cache={}
        # Fixed diode incidence map: avoid rebuilding Python lists at every
        # implicit time step and every active-set retry.
        self._diode_map=np.zeros((2+2*n,self.nodes))
        self._diode_map[0,0]=-1.;self._diode_map[1,1]=1.
        for j in range(n):
            self._diode_map[2+2*j,2+2*j]=1.
            self._diode_map[2+2*j,3+2*j]=-1.
            self._diode_map[3+2*j,3+2*j]=-1.
        self._diode_threshold=np.r_[.8,.8,np.repeat(self.vf,2)]

    def _matrices(self,main,aux,bits):
        key=(main,aux,bits.tobytes())
        if key in self.cache:return self.cache[key]
        a=self.A.copy();b=self.b.copy();offset=self.base
        if main:
            # Low-frequency current-control envelope: primary linkage plus
            # reflected choke currents. Exclude rectifier-Cj displacement
            # ringing from the sampling kernel; the power waveform keeps it.
            a[self.cs,self.w]=float(self.p['Rs'])*self.L[0]/self.L[0,0]
            a[self.cs,self.o]=float(self.p['Rs'])*self.L[0,1:]/self.L[0,0]
        a[offset,offset]-=int(main)/max(self.p['Rds_on']+self.p['Rs'],1e-5)
        a[offset+1,offset+1]-=int(aux)/max(self.p['Rds_aux'],1e-5)
        g=1000.  # Export diode Ron=1 mOhm.
        if bits[0]:a[offset,offset]-=g;b[offset]-=.8*g
        if bits[1]:a[offset+1,offset+1]-=g;b[offset+1]+=.8*g
        for j in range(self.n):
            r,k=offset+2+2*j,offset+3+2*j
            if bits[2+2*j]:
                a[r,r]-=g;a[r,k]+=g;a[k,r]+=g;a[k,k]-=g
                b[r]+=g*self.vf[j];b[k]-=g*self.vf[j]
            if bits[3+2*j]:a[k,k]-=g;b[k]-=g*self.vf[j]
        self.cache[key]=(a,b)
        return a,b

    def _diodes(self,x):
        return self._diode_map@x[self.v]-self._diode_threshold

    def cycle(self,initial,vo,duty,*,derivatives=False,trace=False):
        from calculation_scheduler import check_calculation_cancelled
        if not self.dead/self.T<duty<1-2*self.dead/self.T:raise ValueError('正激周期占空比/死区无有效区间')
        phases=[(True,False,duty*self.T,self.T,max(16,self.points//2)),
                (False,False,self.dead,0.,max(4,self.points//32)),
                (False,True,(1-duty)*self.T-2*self.dead,-self.T,max(16,self.points//2)),
                (False,False,self.dead,0.,max(4,self.points//32))]
        x=np.array(initial,float);n=self.n;size=self.size
        jac=np.column_stack((np.eye(size),np.zeros((size,n+1)))) if derivatives else None
        integral=np.zeros(n);charge_jac=np.zeros((n,size+n+1)) if derivatives else None
        bits=self._diodes(x)>0;cache={};history=[x.copy()];times=[0.];gates=[False];auxgates=[False];elapsed=0.
        input_drive=self.B@vo
        for main,aux,duration,dduration,count in phases:
            h=duration/count;hd=dduration/count
            for tick in range(count):
                if tick%128==0:check_calculation_cancelled()
                before=x;previous_jac=jac
                seen=set()
                for attempt in range(24):
                    signature=bits.tobytes();key=(main,aux,signature,h)
                    if key not in cache:
                        a,b=self._matrices(main,aux,bits);m=self.E-h*a
                        inv=np.linalg.solve(m,np.eye(size))
                        q=inv@(h*self.B)
                        cache[key]=(inv@self.E,q,q@vo,inv@(h*b),inv,a,b)
                    flow,q,vo_drive,c,inv,a,b=cache[key]
                    new=flow@before+vo_drive+c
                    drop=self._diodes(new)
                    updated=np.where(abs(drop)<1e-9,bits,drop>0)
                    updated_signature=updated.tobytes()
                    if updated_signature==signature:break
                    if updated_signature in seen:
                        # Numerical equality at the diode boundary is allowed,
                        # a finite conflicting forward voltage is not.
                        if max(abs(drop[updated!=bits]),default=0.)<1e-7:break
                    seen.add(signature);bits=updated
                else:raise ValueError('正激周期二极管状态迭代未收敛')
                x=new
                integral+=h*(before[self.o]+x[self.o])/2
                if derivatives:
                    jac=flow@previous_jac
                    jac[:,size:size+n]+=q
                    jac[:,-1]+=hd*(inv@(a@x+b+input_drive))
                    charge_jac+=h*(previous_jac[self.o]+jac[self.o])/2
                    charge_jac[:,-1]+=hd*(before[self.o]+x[self.o])/2
                elapsed+=h
                if trace:history.append(x.copy());times.append(elapsed);gates.append(main);auxgates.append(aux)
            if main:
                sense=float(self.p['Rs'])*float(self.p.get('A_sense',1.))
                slope=sense*float(self.p.get('ma_slope',0.))
                threshold=float(self.p.get('A_sense',1.))*x[self.cs]+slope*duty*self.T
                if derivatives:
                    threshold_jac=float(self.p.get('A_sense',1.))*jac[self.cs].copy();threshold_jac[-1]+=slope*self.T
        answer=dict(end=x,mean=integral/self.T)
        answer['threshold']=float(threshold)
        if derivatives:answer.update(jac=jac,charge_jac=charge_jac/self.T,threshold_jac=threshold_jac)
        if trace:answer.update(t=np.array(times),states=np.asarray(history).T,gate=np.asarray(gates),aux_gate=np.asarray(auxgates))
        return answer

    def solve(self,*,seed=None):
        from acf_cross import estimate
        n=self.n;s=self.size
        estimate0=estimate(self.p,self.rails,self.geometry,self.K)
        vo=np.array(estimate0['voltages']);d=estimate0['duty']
        io=vo/self.load
        x=np.zeros(s);x[self.o]=io
        x[0]=-self.vin*d*self.T/(2*self.p['Lm_forward'])
        x[self.c]=self.vin/(1-d);x[self.base]=0;x[self.base+1]=-x[self.c]
        x[self.base+2:self.base+self.nodes]=np.repeat(vo+self.block,2)
        for index,(a,b) in enumerate(self.cj_pairs,self.cj.start):x[index]=x[a]-(x[b] if b is not None else 0.)
        for index,(a,b,r,c) in enumerate(self.extra_rc,self.extra_start):x[index]=x[a]-(x[b] if b is not None else 0.)
        scales=np.r_[max(float(sum(io)),1.),np.maximum(io,.03),np.maximum(io,.03),
                     max(self.vin/(1-d),1.)*np.ones(self.nodes),max(self.vin/(1-d),1.),.1,
                     max(self.vin/(1-d),1.)*np.ones(2*n+2+len(self.extra_rc))]
        scale=np.r_[scales,np.maximum(vo,1.),1.]
        initial=np.r_[x,vo,d]/scale if seed is None else np.asarray(seed)/scale
        memo={}
        def evaluate(z):
            if memo.get('z') is not None and np.array_equal(memo['z'],z):return memo['f'],memo['jac']
            physical=z*scale;start=physical[:s];voltage=physical[s:s+n];duty=physical[-1]
            if not 0.01<duty<min(self.p['forward_d_max'],1-2*self.dead/self.T):
                raise ValueError('正激周期求解超出占空比界限')
            point=self.cycle(start,voltage,duty,derivatives=True)
            residual=np.r_[(point['end']-start)/scales,(point['mean']-voltage/self.load)/np.maximum(io,.03),(voltage[self.fb]-self.target)/self.target]
            j1=point['jac'].copy();j1[:,:s]-=np.eye(s)
            j2=point['charge_jac'].copy();j2[:,s:s+n]-=np.diag(1/self.load)
            j3=np.zeros((1,s+n+1));j3[0,s+self.fb]=1/self.target
            derivative=np.vstack((j1/scales[:,None],j2/np.maximum(io,.03)[:,None],j3))*scale
            memo.update(z=z.copy(),f=residual,jac=derivative)
            return residual,derivative
        solved=root(lambda z:evaluate(z)[0],initial,jac=lambda z:evaluate(z)[1],method='hybr',options={'xtol':1e-8,'maxfev':100})
        residual=float(np.max(abs(evaluate(solved.x)[0])))
        if residual>1e-6:raise ValueError(f'正激周期/电荷平衡未收敛：{residual:.3g}；{solved.message}')
        physical=solved.x*scale;point=self.cycle(physical[:s],physical[s:s+n],physical[-1],derivatives=True,trace=True)
        point.update(initial=physical[:s],voltages=physical[s:s+n],duty=float(physical[-1]),residual=residual,
                     evaluations=solved.nfev,seed=physical)
        return point


def _solve_point(p,rails,geometry,model,*,points=2048,seed=None):
    """Bounded mesh refinement. A failed physical solve never becomes nominal."""
    settings=p.get('spice_config') or {}
    q=dict(p,_acf_cj=float(settings.get('diode_cj_pf',20.))*1e-12,
           forward_dead_time=float(settings.get('acf_dead_ns',0))*1e-9 or p['forward_dead_time'])
    from parasitics import resolved,augment_matrix
    model=augment_matrix(model,resolved(p,len(rails)))
    circuit=PeriodicForward(q,rails,geometry,model,points=min(512,points))
    previous=circuit.solve(seed=seed)
    comparisons=[]
    for count in (1024,2048,4096,8192):
        circuit=PeriodicForward(q,rails,geometry,model,points=count)
        point=circuit.solve(seed=previous['seed'])
        def measures(z):
            t=z['t'];x=z['states']
            return np.r_[z['voltages'],z['duty'],np.sqrt(np.trapezoid(x[:2*len(rails)+1]**2,t,axis=1)/circuit.T)]
        a,b=measures(previous),measures(point)
        error=float(max(abs(a-b)/np.maximum(abs(b),.02)))
        comparisons.append(dict(points=count,relative_change=error,voltage_change=float(max(abs(a[:len(rails)]-b[:len(rails)])/np.maximum(abs(b[:len(rails)]),.01)))))
        previous=point
        if count>=max(points,2048) and error<.01:break
    if comparisons[-1]['voltage_change']>.005:
        raise ValueError('正激周期电压网格细化差异超过 0.5%，不输出未经收敛的直流解')
    point['mesh']=comparisons
    return circuit,point


@lru_cache(maxsize=16)
def _cached_point(serialized,points):
    p,rails,geometry,model=json.loads(serialized)
    return _solve_point(p,rails,geometry,model,points=points)


def solve_point(p,rails,geometry,model,*,points=2048,seed=None):
    if seed is not None:return _solve_point(p,rails,geometry,model,points=points,seed=seed)
    # Thermal/BOM/plot/compensator changes do not rerun an electrical period.
    keys=('topology','V_in','f_sw','Lm_forward','Coss','Coss_aux','C_clamp','ESR_clamp','Rds_on','Rds_aux',
          'Rs','A_sense','ma_slope','forward_dead_time','forward_d_max','feedback_output','d_in_enable','Vf_din','parasitic_config')
    params={k:p[k] for k in keys if k in p}
    settings=p.get('spice_config') or {}
    params['spice_config']={k:settings[k] for k in ('diode_cj_pf','cs_filter_ns','acf_dead_ns') if k in settings}
    reduced_rails=[{k:r[k] for k in ('id','name','V_out','P_out','Vf_diode','Vf_dout','d_out_enable','L')} for r in rails]
    reduced_model={k:np.asarray(model[k]).tolist() for k in ('L','R','K')}
    key=json.dumps([params,reduced_rails,geometry,reduced_model],sort_keys=True,separators=(',',':'))
    circuit,point=_cached_point(key,points)
    return circuit,copy.deepcopy(point)


def solve_forward(p,nominal):
    from isolated_outputs import output_specs,RAIL_KEYS
    from winding_coupling import resolve_winding_geometry,resolve_winding_model
    from voltage_nodes import CONVENTION
    rails=output_specs(p) or [dict({k:p.get(k) for k in RAIL_KEYS},id=1,name='OUT1')]
    geometry=resolve_winding_geometry(p,nominal,rails)
    model=resolve_winding_model(p,rails,geometry=geometry)
    if model['ideal']:
        op=copy.deepcopy(nominal)
        op.setdefault('warnings',[]).append('全部 kij=1 为奇异理想变压器极限：保留显式标称近似，不伪造非理想周期解。')
        return op
    circuit,z=solve_point(p,rails,geometry,model)
    model=dict(model,L=circuit.L,R=circuit.R)
    op=copy.deepcopy(nominal);t=z['t'];x=z['states'];D=z['duty'];T=circuit.T;n=len(rails)
    avg=lambda y:float(np.trapezoid(y,t)/T)
    rms=lambda y:float(np.sqrt(max(np.trapezoid(y*y,t)/T,0.)))
    main=t<D*T;aux=(t>D*T+circuit.dead)&(t<T-circuit.dead)
    ip=x[0];isec=-x[1:n+1];ilo=x[circuit.o];vn=x[circuit.v]
    iw=np.where(main,ip,0.);ia=np.where(aux,(vn[0]-vn[1]-x[circuit.c])/max(p['ESR_clamp'],1e-5),0.)
    # Primary linkage is a reference, not a uniquely identified core flux.
    linkage=model['L'][0]@x[circuit.w];im=linkage/model['L'][0,0]
    actual_power=z['voltages']**2/circuit.load
    ic=(vn[0]-vn[1]-x[circuit.c])/max(p['ESR_clamp'],1e-5)
    # Backward-Euler power audit uses each step's final state and the switch
    # state that actually propagated that step. A pre-turn-on voltage must
    # never be assigned to the newly closed Ron by trapezoidal sampling.
    weighted=lambda y:float(np.dot(np.diff(t),y[1:])/T)
    dissipation=sum(model['R'][j]*weighted(x[j]**2) for j in range(n+1))
    dissipation+=weighted(np.where(z['gate'],vn[0]**2/max(p['Rds_on']+p['Rs'],1e-5),0.))
    dissipation+=weighted(np.where(z['aux_gate'],vn[1]**2/max(p['Rds_aux'],1e-5),0.))+p['ESR_clamp']*weighted(ic**2)
    dissipation+=weighted(np.maximum(-vn[0]-.8,0.)*1000*(-vn[0]))+weighted(np.maximum(vn[1]-.8,0.)*1000*vn[1])
    for index,(a,b) in enumerate(circuit.cj_pairs,circuit.cj.start):
        v=x[a]-(x[b] if b is not None else 0.)-x[index]
        dissipation+=weighted(v*v/circuit.parasitics['r_cj'])
    for index,(a,b,r,c) in enumerate(circuit.extra_rc,circuit.extra_start):
        v=x[a]-(x[b] if b is not None else 0.)-x[index]
        dissipation+=weighted(v*v/r)
    extra_power=circuit.parasitics['rp_pcb']*weighted(ip**2)
    extra_power+=sum(r['r_pcb']*weighted(x[j+1]**2) for j,r in enumerate(circuit.parasitics['rails']))
    for index,(a,b,r,c) in enumerate(circuit.extra_rc,circuit.extra_start):
        v=x[a]-(x[b] if b is not None else 0.)-x[index]
        extra_power+=weighted(v*v/r)
    for j in range(n):
        vr,vk=vn[2+2*j],vn[3+2*j]
        dissipation+=weighted(np.maximum(vr-vk-circuit.vf[j],0.)*1000*(vr-vk))
        dissipation+=weighted(np.maximum(-vk-circuit.vf[j],0.)*1000*(-vk))
    energy=circuit.vin*weighted(ip)-sum((z['voltages']+circuit.block)*np.array([weighted(v) for v in ilo]))-dissipation
    children=[];forward=[];free=[]
    old=nominal.get('output_ops') or [nominal]
    for j,(rail,vo,child0) in enumerate(zip(rails,z['voltages'],old)):
        child=copy.deepcopy(child0);il=ilo[j];secondary=isec[j]
        ir=np.maximum((vn[2+2*j]-vn[3+2*j]-circuit.vf[j])*1000,0.)
        iff=np.maximum((-vn[3+2*j]-circuit.vf[j])*1000,0.)
        forward.append(ir);free.append(iff)
        mode='CCM' if min(il)>max(max(il)*1e-4,1e-7) else 'DCM'
        child.update(D=D,Dp=1-D,mode=mode,V_out=float(vo),V_out_cap=float(vo+circuit.block[j]),
            V_feedback=float(vo+circuit.block[j]),V_out_equiv=float(vo+circuit.block[j]+circuit.vf[j]),
            P_out=float(actual_power[j]),P_rated=float(rail['P_out']),R=float(circuit.load[j]),R_equiv=float(circuit.load[j]),
            I_out=float(vo/circuit.load[j]),I_L_avg=avg(il),I_L_pk=float(max(il)),I_L_min=float(min(il)),
            I_L_rms=rms(il),dI_L=float(np.ptp(il)),I_s_rms=rms(secondary),I_s_pk=float(max(secondary)),
            I_d_avg=avg(secondary),I_d_rms=rms(secondary),I_d_pk=float(max(secondary)),
            I_free_avg=avg(iff),I_free_rms=rms(iff),I_free_pk=float(max(iff)),
            V_d_max=float(max(vn[3+2*j]-vn[2+2*j])),V_d_block=float(max(vn[3+2*j]-vn[2+2*j])),
            V_free_max=float(max(vn[3+2*j])),V_free_block=float(max(vn[3+2*j])),
            output_id=j+1,name=rail['name'],efficiency_model='periodic-MNA-explicit-circuit')
        charge=np.r_[0.,np.cumsum((il[:-1]+il[1:]-2*child['I_out'])*np.diff(t)/2)]
        child['C_min']=float(np.ptp(charge))/max(rail['ripple_target']*vo,1e-12)
        child['L_min']=child['L']*child['dI_L']/max(2*child['I_out'],1e-12)*1.5
        children.append(child)
    fb=circuit.fb;chief=children[fb]
    op.update({k:chief[k] for k in ('V_out','V_out_cap','V_feedback','V_out_equiv','I_out','R','R_equiv','L','C_out','Rc','ESL','C_out2','Rc2','ESL2','cout2_enable',
        'I_L_avg','I_L_min','I_L_pk','I_L_rms','dI_L','I_s_rms','I_d_avg','I_d_rms','I_d_pk',
        'I_free_avg','I_free_rms','I_free_pk','V_d_max','V_d_block','V_free_max','V_free_block','C_min')})
    op.update(D=D,Dp=1-D,mode=chief['mode'],outputs=rails,output_ops=children,feedback_output=fb+1,
        P_out=float(sum(actual_power)),P_rated=float(sum(r['P_out'] for r in rails)),
        P_in_est=float(p['V_in'])*avg(ip),I_in_est=avg(ip),
        I_p_rms=rms(ip),I_p_avg=avg(ip),I_sw_rms=rms(iw),I_sw_avg=avg(iw),I_sw_pk=float(max(ip[main])),
        I_sw_on=max(float(im[0]+sum(model['L'][0,j+1]/model['L'][0,0]*ilo[j,0] for j in range(n))),0.),
        I_sw_on_waveform=float(ip[0]),I_sw_off=float(ip[np.flatnonzero(main)[-1]]),
        I_aux_rms=rms(ia),I_aux_pk=float(max(abs(ia))),I_aux_avg_abs=avg(abs(ia)),
        I_mag_pk=float(max(abs(im))),dI_mag=float(np.ptp(im)),
        V_sw_max=float(max(vn[0])),V_clamp=avg(x[circuit.c]),V_clamp_hump=float(max(x[circuit.c])-avg(x[circuit.c])),V_clamp_pp=float(np.ptp(x[circuit.c])),
        V_reset=avg(x[circuit.c])-circuit.vin,V_in_bus=circuit.vin,
        I_clamp_rms=rms((vn[0]-vn[1]-x[circuit.c])/max(p['ESR_clamp'],1e-5)),
        efficiency_model='periodic-MNA-explicit-circuit',voltage_convention=CONVENTION,P_parasitic=float(extra_power))
    op['P_loss_budget']=op['P_in_est']-op['P_out']
    op['f_clamp_effective']=(1-D)*op['f_clamp']
    op['fc_recommended_max']=min(op['f_sw']/10,op['f_clamp_effective']/5)
    op['acf_model']=dict(kind='periodic-MNA',revision=1,converged=True,independent_prediction=True,
        transformer_hardware=geometry,L=model['L'].tolist(),R=model['R'].tolist(),K=model['K'].tolist(),
        winding_rms=[rms(v) for v in x[circuit.w]],
        load_resistances=circuit.load.tolist(),output_voltages=z['voltages'].tolist(),
        normalized_residual=z['residual'],mesh=z['mesh'],diode_cj=circuit.p['_acf_cj'],
        energy_balance_W=float(energy),energy_balance_relative=float(abs(energy)/max(circuit.vin*avg(ip),1.)),
        current_mesh_verified=bool(z['mesh'][-1]['relative_change']<=.02),
        state_initial=z['initial'].tolist(),period_jac=z['jac'].tolist(),charge_jac=z['charge_jac'].tolist(),
        threshold_jac=z['threshold_jac'].tolist(),threshold=z['threshold'],
        linearization_slope=float(p['Rs'])*float(p.get('A_sense',1))*float(p.get('ma_slope',0.)),
        state_scales=np.maximum(np.max(abs(x),axis=1),.01).tolist(),
        assumptions='完整两两互感、几何 DCR、输出电感、钳位 C/ESR、恒定 Coss/Cj、有限导通电阻和双边沿死区。'
        '周期电流/钳位与各路电荷平衡独立求解；电容端直流近似，纹波再由每颗 C+ESR/ESL 重建。'
        '预设效率保留为设计参考，不再重复叠加到显式损耗电路。输出电感与当前导出一致为理想 L，尚未含其 DCR。'
        'MOS 开关边沿理想，开通重叠损耗仍用反射负载电流的保守电荷法，不从理想瞬时电流为零推定 ZVS。未含非线性电容、反向恢复、温度及磁饱和。')
    op['acf_solution']=dict(t=t,i_primary=ip,i_mag=im,i_sw=iw,i_aux=ia,i_s=isec,iL=ilo,
        i_forward=np.asarray(forward),i_free=np.asarray(free),i_clamp=ic,v_sw=vn[0],v_clamp=x[circuit.c],
        v_primary=circuit.vin-vn[0]-model['R'][0]*ip,lambda_p=linkage,
        v_d=np.array([vn[3+2*j]-vn[2+2*j] for j in range(n)]),
        v_free=np.array([vn[3+2*j] for j in range(n)]))
    op['warnings']=[op['acf_model']['assumptions'],'二极管反压含本模型的恒定结电容振铃；真实尖峰仍需实测并留选型裕量。']
    if not op['acf_model']['current_mesh_verified']:
        op['warnings'].append('该角点电压网格已收敛，但高频绕组电流 RMS 对网格仍敏感；电流/峰值仅供参考，不给出该点的有效小信号裕度。')
    if op['acf_model']['energy_balance_relative']>.02:
        raise ValueError('正激周期能量账本残差超过 2%，不输出未经核对的工作点')
    return op


def waveforms(op,n_cycles,n_pts):
    from waveforms import cap_bank_ripple
    z=op['acf_solution'];T=op['Ts'];t=np.linspace(0,n_cycles*T,n_cycles*max(n_pts,2048),endpoint=False)
    phase=t%T;sample=lambda y:np.interp(phase,z['t'],y)
    common=dict(t=t,dt=t[1]-t[0],f_sw=op['f_sw'],topology=op['topology'],
        i_primary=sample(z['i_primary']),i_p=sample(z['i_primary']),i_mag=sample(z['i_mag']),
        i_sw=sample(z['i_sw']),i_aux=sample(z['i_aux']),i_in=sample(z['i_primary']),
        v_sw=sample(z['v_sw']),v_primary=sample(z['v_primary']),v_clamp=sample(z['v_clamp']),i_clamp=sample(z['i_clamp']))
    common['i_cin']=common['i_in']-np.mean(common['i_in'])
    common['i_cin_rms']=float(np.sqrt(np.mean(common['i_cin']**2)))
    outputs=[]
    for j,child in enumerate(op['output_ops']):
        from capacitor_banks import tuples
        il=sample(z['iL'][j]);ic=il-child['I_out'];caps=tuples(child)
        low=cap_bank_ripple(t,ic,[(c,r,0.) for c,r,_ in caps]);full=cap_bank_ripple(t,ic,caps)
        wf=dict(common,iL=il,i_s=sample(z['i_s'][j]),i_d=sample(z['i_forward'][j]),
            i_free=sample(z['i_free'][j]),i_c=ic,v_d=sample(z['v_d'][j]),v_free=sample(z['v_free'][j]),
            vout=child['V_out']+low,vcap=child['V_out_cap']+low,vout_ripple=low,v_esl=full-low,
            ripple_pp=float(np.ptp(low)),ripple_pp_total=float(np.ptp(full)),
            esl_spike_pp=float(max(abs(full-low))),i_c_rms=float(np.sqrt(np.mean(ic**2))))
        outputs.append(wf)
    result=dict(outputs[op['feedback_output']-1]);result['outputs']=outputs
    return result
