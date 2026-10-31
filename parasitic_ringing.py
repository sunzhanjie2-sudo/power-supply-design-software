"""Local commutation RLC estimate with an ideal voltage clamp.

The shifted port voltage starts at its blocking plateau with a specified
commutation current. Kirchhoff equations are integrated, including an optional
series RC shunt. It does not synthesize a cosmetic decaying sine or pretend to
solve the full switching converter. All results carry that scope explicitly.
"""
import copy
import json
import math
from functools import lru_cache
import numpy as np


def solve_edge(inductance, capacitance, resistance, current, plateau, *, ceiling=None,
               snub_r=10., snub_c=0., duration=None, initial_voltage=None):
    from scipy.integrate import solve_ivp
    from calculation_scheduler import check_calculation_cancelled
    vals=(inductance,capacitance,resistance,current,plateau,snub_r,snub_c)
    if any(not math.isfinite(float(v)) or v<0 for v in vals): raise ValueError('局部 RLC 参数必须为有限非负数')
    if snub_c and snub_r<=0: raise ValueError('RC 吸收电阻必须大于零')
    if ceiling is not None and (not math.isfinite(ceiling) or ceiling<plateau): raise ValueError('钳位上限必须不小于阻断平台')
    initial_voltage=plateau if initial_voltage is None else float(initial_voltage)
    if not math.isfinite(initial_voltage) or initial_voltage<0:raise ValueError('初始端口电压必须为有限非负值')
    if not inductance or not capacitance or (not current and initial_voltage==plateau):
        return dict(t=np.array([0.,1e-9]),voltage=np.array([plateau,plateau]),peak=plateau,
                    frequency=None,energy_initial=.5*inductance*current**2,status='无有效 LC 激励',clamped=False)
    L,C,R=inductance,capacitance,resistance
    period=2*math.pi*math.sqrt(L*C)
    end=min(8*period,duration) if duration is not None else 8*period
    if end<=0: raise ValueError('局部振铃观察时间必须为正')
    has_snub=snub_c>0
    def rhs(t,x):
        check_calculation_cancelled()
        i,v,u=x
        js=(v-u)/snub_r if has_snub else 0.
        return [(-v-R*i)/L,(i-js)/C,js/snub_c if has_snub else 0.]
    top=ceiling-plateau if ceiling is not None else math.inf
    bottom=-plateau  # ideal body/rectifier diode clips a negative absolute port voltage
    start=0.;x=np.array([current,initial_voltage-plateau,initial_voltage-plateau]);times=[0.];history=[x.copy()];clamped=False
    for _ in range(64):
        if start>=end*(1-1e-12): break
        def upper(t,z):return z[1]-top
        def lower(t,z):return z[1]-bottom
        upper.terminal=True;upper.direction=1
        lower.terminal=True;lower.direction=-1
        events=[lower] if not math.isfinite(top) else [upper,lower]
        sol=solve_ivp(rhs,(start,end),x,method='Radau',rtol=2e-8,
            atol=[max(current,1.)*1e-10,max(plateau,1.)*1e-10,max(plateau,1.)*1e-10],
            max_step=period/48,events=events)
        if not sol.success: raise ValueError('局部 RLC 积分失败：'+sol.message)
        times.extend(sol.t[1:]);history.extend(sol.y[:,1:].T)
        start=float(sol.t[-1]);x=sol.y[:,-1].copy()
        if start>=end*(1-1e-12): break
        high=bool(math.isfinite(top) and len(sol.t_events[0]))
        bound=top if high else bottom;clamped=clamped or high
        sign=1. if high else -1.
        def clamp_rhs(t,z):
            check_calculation_cancelled()
            i,v,u=z
            return [(-bound-R*i)/L,0.,(bound-u)/(snub_r*snub_c) if has_snub else 0.]
        def release(t,z):return sign*(z[0]-((bound-z[2])/snub_r if has_snub else 0.))
        release.terminal=True;release.direction=-1
        x[1]=bound
        sol=solve_ivp(clamp_rhs,(start,end),x,method='Radau',rtol=2e-8,atol=1e-10,
                      max_step=period/48,events=release)
        if not sol.success: raise ValueError('局部钳位积分失败')
        times.extend(sol.t[1:]);history.extend(sol.y[:,1:].T)
        start=float(sol.t[-1]);x=sol.y[:,-1].copy()
        # Move infinitesimally inside the permitted interval after release.
        x[1]=bound-sign*max(plateau,1.)*1e-10
    else: raise ValueError('局部钳位事件数超出上限，请检查参数')
    z=np.asarray(history).T;t=np.asarray(times);v=z[1]+plateau
    return dict(t=t,voltage=v,peak=float(max(v)),frequency=1/period,
        energy_initial=.5*L*current**2+.5*(C+snub_c)*(initial_voltage-plateau)**2,status='集中参数局部换流估算',clamped=clamped,
        current=z[0],energy_final=float(.5*L*z[0,-1]**2+.5*C*z[1,-1]**2+(.5*snub_c*z[2,-1]**2 if has_snub else 0.)))


@lru_cache(maxsize=16)
def _cached_edge(key):return solve_edge(**json.loads(key))


def edge(**params):return copy.deepcopy(_cached_edge(json.dumps(params,sort_keys=True)))


def attach(p,op,wf):
    from parasitics import ISOLATED,resolved,NOTE
    if p['topology'] not in ISOLATED:return
    children=op.get('output_ops') or [op]
    cfg=resolved(p,len(children))
    data=dict(mode=cfg['mode'],parameters=cfg,note=NOTE,edges=[])
    op['parasitics']=data
    if cfg['mode']=='fast':return
    if p['topology']=='ACF-FORWARD':
        data['scope']='正激沿用完整 MNA 周期；新增端间电容与 RC 吸收进入同一电路。'
        if not op.get('acf_solution'):raise ValueError('正激寄生细算需要启用两两 kij 物理周期计算')
        data['scope']+=' 新增布线电阻与 RC 吸收电阻的周期损耗已计入效率；电容仍为常数，未包含完整芯片与器件非线性。'
        return
    if p.get('feedback_mode','SSR')!='SSR':raise ValueError('反激局部寄生估算目前支持 SSR；PSR 需独立控制器仿真')
    if p['topology']=='QR-FLYBACK' and len(children)>1:raise ValueError('QR 寄生瞬态目前仅支持单路；多路退磁/谷底尚未验证')
    # Freeze winding geometry used by the current operating point.
    from winding_coupling import resolve_winding_geometry,resolve_winding_model
    from isolated_outputs import output_specs,RAIL_KEYS
    rails=output_specs(p) or [dict({k:p.get(k) for k in RAIL_KEYS},id=1,name='OUT1')]
    q=copy.deepcopy(p)
    if not p.get('coupling_config',{}).get('enabled'):
        k=float(p.get('K',.95))
        if not 0<k<=1:raise ValueError('旧 K 必须满足 0<K≤1')
        size=len(rails)+1
        q['coupling_config']=dict(enabled=True,k=[[1. if i==j else math.sqrt(k) for j in range(size)] for i in range(size)])
    geometry=resolve_winding_geometry(q,op,rails)
    matrix=resolve_winding_model(q,rails,geometry=geometry,nominal_op=op)
    lm=np.asarray(matrix['L'])
    def leakage(j):
        if matrix.get('ideal'):return 0.
        rest=[k for k in range(len(lm)) if k!=j]
        # Short-circuit driving-point leakage, a local reduction, not a modal fit.
        return max(float(lm[j,j]-lm[j,rest]@np.linalg.pinv(lm[np.ix_(rest,rest)])@lm[rest,j]),0.)
    clamp=op.get('clamp') or {};plateau=float(clamp.get('V_plateau',op['V_in']+op['V_r']))
    params=dict(inductance=leakage(0)+cfg['lp_pcb'],capacitance=cfg['coss']+cfg['cw_primary'],
        resistance=float(matrix['R'][0])+cfg['rp_pcb'],current=float(op.get('I_sw_off',op['I_sw_pk'])),
        plateau=plateau,ceiling=float(clamp['V_ceiling']) if p.get('Kc',0)>1 else None,
        snub_r=cfg['snub_r_primary'],snub_c=cfg['snub_c_primary'],duration=(1-op['D'])*op['Ts'])
    trace=edge(**params);trace.update(ref='Q1',parameters=params)
    data['edges'].append(trace)
    op['V_sw_max']=max(op['V_sw_max'],trace['peak'])
    for j,(child,r) in enumerate(zip(children,cfg['rails']),1):
        child_wf=(wf.get('outputs') or [wf])[j-1]
        # Current just before the next MOS turn-on, not the unrelated earlier peak.
        commutation_current=max(float(np.asarray(child_wf['i_d'])[-1]),0.)
        params=dict(inductance=leakage(j)+r['l_pcb'],capacitance=r['cj']+r['cw'],
            resistance=float(matrix['R'][j])+r['r_pcb']+cfg['r_cj'],
            current=commutation_current,plateau=float(child['V_d_max']),initial_voltage=0.,
            snub_r=r['snub_r'],snub_c=r['snub_c'],duration=op['D']*op['Ts'])
        trace=edge(**params);trace.update(ref=(f'D_O{j}' if p.get('outputs') else 'D1（SPICE D_O1）'),parameters=params)
        data['edges'].append(trace)
        child['V_d_max']=max(child['V_d_max'],trace['peak'])
        if j==int(p.get('feedback_output',1)):op['V_d_max']=child['V_d_max']
    if p['topology']=='QR-FLYBACK':
        params=dict(inductance=float(p['L']),capacitance=cfg['coss']+cfg['cw_primary'],
            resistance=float(matrix['R'][0])+cfg['rp_pcb'],current=0.,plateau=float(op['V_in']),
            initial_voltage=float(op['V_in']+op['V_r']),duration=float(op['T_ring']))
        trace=edge(**params);trace.update(ref='Q1 · 退磁后首谷底',parameters=params)
        data['edges'].append(trace)
    data['scope']=('开关沿后的独立端口 RLC 估算：短路驱动点漏感 + 本地 C/串联 R/RC 吸收；'
        '从原工作点的电流激励起算。各端口独立，不代表两两耦合的完整高频同时解。'
        '整流支路采用换流前电流和阻断电压阶跃激励，未模拟真实反向恢复；结果不构成严格应力上界，不据此更新平均电流、直流输出或低频环路。'
        'Q1 使用理想定压钳位；吸收损耗未迭代至效率，最终峰值仍需 SPICE 与实测核对。')
    wf['parasitics']=data
    op.setdefault('warnings',[]).extend([NOTE,data['scope']])


def draw(fig,data):
    edges=data.get('edges',[])
    if not edges:
        ax=fig.subplots();ax.axis('off');ax.text(.04,.7,data.get('scope','快速模式：不额外计算局部振铃。'),wrap=True)
        return
    axes=np.atleast_1d(fig.subplots(len(edges),1))
    for ax,z in zip(axes,edges):
        ax.plot(z['t']*1e9,z['voltage'],color='#1874bd',label='局部 RLC 估算')
        ax.axhline(z['parameters']['plateau'],color='#8998a5',ls='--',label='阻断平台')
        f=f" · LC {z['frequency']/1e6:.2f} MHz" if z['frequency'] else ''
        ax.set(title=f"{z['ref']} · 峰值 {z['peak']:.2f} V"+f,xlabel='换流后时间 / ns',ylabel='电压 / V')
        ax.grid(alpha=.2);ax.legend(loc='upper right',fontsize=8)
    fig.tight_layout(pad=1.5)
