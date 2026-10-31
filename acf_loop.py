"""Single-feedback ACF loop from its independent physical periodic solution."""
from types import SimpleNamespace
import numpy as np


def build_loop(p,op):
    import control as ct
    from plants import make_compensator
    from output_capacitors import build_output_filters
    from acf_spice import current_slope
    meta=op['acf_model'];n=len(op['outputs']);s=len(meta['state_initial']);T=op['Ts']
    if not meta.get('current_mesh_verified',True):raise ValueError('此角点高频电流网格尚未收敛，不输出有效环路裕度；请用实际 FRA 核对')
    j=np.asarray(meta['period_jac']);current=np.asarray(meta['charge_jac']);h=np.asarray(meta['threshold_jac']).copy()
    sense=float(p['Rs'])*float(p.get('A_sense',1))
    old_slope=float(meta.get('linearization_slope',0.))
    actual_slope=current_slope(p,op['outputs'],meta['transformer_hardware'])
    h[-1]+=(actual_slope-old_slope)*T
    scales=np.asarray(meta['state_scales'])
    a=j[:,:s]*scales[None,:]/scales[:,None]
    b=j[:,s:]/scales[:,None]
    ji=current[:,:s]*scales[None,:];jfeed=current[:,s:]
    hi=h[:s]*scales;hfeed=h[s:]
    identity=np.eye(s)
    if np.linalg.cond(identity+a)>1e10:raise ValueError('正激周期核接近 −1 采样极点，不输出低频等效环路')
    inv=np.linalg.solve(identity+a,identity)
    ax=2/T*(a-identity)@inv;bx=2/T*inv@b
    jx=2*ji@inv;jf=jfeed-ji@inv@b
    hx=2*hi@inv;hf=hfeed-hi@inv@b
    rails=op['outputs'];loads=np.asarray(meta['load_resistances'])
    voltages=np.array([c['V_out_cap'] for c in op['output_ops']])
    filters=build_output_filters(rails,loads,voltages);m=len(filters.A)
    av,ad=bx[:,:n],bx[:,n];jv,jd=jf[:,:n],jf[:,n]
    peak=p['control_mode']=='Peak Current Mode'
    algebraic=np.zeros((n+1,n+1));algebraic[:n,:n]=np.eye(n)-filters.D@jv
    algebraic[:n,n]=-filters.D@jd
    algebraic[n,:n]=hf[:n] if peak else 0.
    algebraic[n,n]=hf[n] if peak else float(p['Vm'])
    if algebraic[n,n]<=1e-8:raise ValueError('正激峰值比较器的占空比增益非正，需检查斜坡补偿及工作点')
    row=np.maximum(np.max(abs(algebraic),axis=1),1e-20)
    normalized=algebraic/row[:,None]
    if np.linalg.cond(normalized)>1e10:raise ValueError('正激电容网络与峰值采样的代数方程接近奇异')
    states=np.zeros((n+1,s+m));states[:n,:s]=filters.D@jx;states[:n,s:]=filters.C
    if peak:states[n,:s]=-hx
    inputs=np.zeros((n+1,n+1));inputs[n,0]=1;inputs[:n,1:]=-filters.D
    solved=np.linalg.solve(normalized,np.column_stack((states,inputs))/row[:,None])
    vs,ds=solved[:n,:s+m],solved[n,:s+m]
    vi,di=solved[:n,s+m:],solved[n,s+m:]
    top=np.column_stack((ax,np.zeros((s,m))))+av@vs+np.outer(ad,ds)
    bottom=np.column_stack((filters.B@jx,filters.A))+filters.B@jv@vs+np.outer(filters.B@jd,ds)
    btop=av@vi+np.outer(ad,di);bbottom=filters.B@jv@vi+np.outer(filters.B@jd,di)
    bbottom[:,1:]-=filters.B
    full=ct.ss(np.vstack((top,bottom)),np.vstack((btop,bbottom)),vs,vi)
    gvc=full[int(op['feedback_output'])-1,0];gc=make_compensator(p).get_transfer_function()
    sampling=a-np.outer(b[:,-1],h[:s]*scales)/(h[-1]) if peak else a
    details=dict(kind='acf-periodic-MNA',revision=1,experimental=True,feedback_output=op['feedback_output'],
        outputs=[dict(id=r['id'],name=r.get('name',f'OUT{r["id"]}'),voltage=float(c['V_out']),current=float(c['I_out'])) for r,c in zip(rails,op['output_ops'])],
        slope_v_per_s=actual_slope,
        inner_spectral_radius=float(max(abs(np.linalg.eigvals(sampling)))),
        derivative_method='analytic fixed-active-set implicit-step sensitivities; mode-boundary derivatives require switching verification',
        esr_included=True,capacitor_banks=filters.banks,capacitor_states=m,state_count=s+m,
        frequency_limit=None,recommended_fc_max=None,bandwidth_limit_enabled=False,
        assumptions='正激两两互感、物理钳位和输出电感周期解线性化；保留每颗并联 C+ESR 独立状态。'
        '峰值采样含励磁/换流电流及用户斜坡。仅所选一路反馈，其余路参与共享功率级。'
        '低频周期平均等效，采样核取励磁与反射电感电流包络并保留 CS 滤波；不含光耦/TL431、消隐/传播延迟和大信号限幅。高频需实际 FRA。')
    gvc._multi_output_system=full;gvc._loop_metadata=details
    return (gvc,gc,gvc*gc),SimpleNamespace(model_note=details['assumptions'],loop_metadata=details,
        full_system=full,output_filters=filters)
