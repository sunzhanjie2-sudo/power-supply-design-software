"""MP6005 Rev 1.1, 2024-10-11: PSR checks and physical COMP network.

PWM loop modelling is approximate; proprietary sampling, internal slope
compensation and PFM dynamics are not a verified IC simulation.
"""
import math

DATASHEET = 'https://www.monolithicpower.com/en/documentview/productdocument/index/version/2/document_type/Datasheet/lang/en/sku/MP6005GK/'
DEFAULTS = dict(psr_Na=0.,psr_aux_target=9.,psr_RfbH=47e3,psr_RfbL=0.,
                psr_Rreg=6.8e3,psr_Rcomp=10e3,psr_Ccomp=10e-9,
                psr_Cpole=220e-12,psr_Vcc=8.5)


def design_psr(p,op,transformer=None):
    if p.get('feedback_mode','SSR')!='PSR-MP6005': return None
    if op['topology']!='FLYBACK': raise ValueError('MP6005 PSR 仅用于固定频率反激')
    from isolated_outputs import selected_params
    q = selected_params(p)
    v = {k:float(p.get(k,x)) for k,x in DEFAULTS.items()}
    for k,x in v.items():
        if not math.isfinite(x) or x<0: raise ValueError(f'{k} 必须为有限非负值')
    for k in ('psr_aux_target','psr_RfbH','psr_Rcomp','psr_Ccomp','psr_Cpole','psr_Vcc'):
        if v[k]<=0: raise ValueError(f'{k} 必须大于 0')
    if int(v['psr_Na'])!=v['psr_Na']: raise ValueError('psr_Na 必须为整数匝数，0 表示自动')
    tr = transformer or {}
    np_ = int(tr.get('Np',q.get('Np',0)) or 1)
    ns = int(tr.get('Ns',q.get('Ns',0)) or max(1,round(np_/op['N'])))
    from voltage_nodes import capacitor_voltage,output_drop
    vf = q['Vf_diode'];v_cap=capacitor_voltage(q)
    na = int(v['psr_Na']) or max(1,round(ns*v['psr_aux_target']/(v_cap+vf)))
    va = na/ns*(v_cap+vf)
    rh,rg = v['psr_RfbH'],v['psr_Rreg']
    gain = next((g for lo,hi,g in ((0,1300,0),(3000,3600,5e-5),
                 (6200,7500,1e-4),(12700,13000,2e-4),(24900,28000,0))
                 if lo<=rg+q['Rs']<=hi),None)
    vs_avg = q['Rs']*op['I_in_est']
    ireg = (gain or 0)*vs_avg
    denominator = va-ireg*rh-2.
    rl = v['psr_RfbL']
    if not rl:
        if denominator<=0: raise ValueError('辅助绕组电压不足或补偿过大，无法构造正的反馈分压电阻')
        rl = rh*2/denominator
    beta = rl/(rh+rl)
    predicted = (2/beta+ireg*rh)*ns/na-vf-output_drop(q)
    reflected = np_/ns*(v_cap+vf)
    rs = q['Rs']
    if rs<=0: raise ValueError('MP6005 Rs 必须大于 0')
    r,cc,cp = v['psr_Rcomp'],v['psr_Ccomp'],v['psr_Cpole']
    feedback_loss = va**2/(rh+rl)
    return dict(controller='MP6005',source=DATASHEET,revision='1.1 (2024-10-11)',
                region=op.get('regulation_region','PWM'),Np=np_,Ns=ns,Na=na,
                Vaux=va,RfbH=rh,RfbL=rl,beta=beta,Hfb=beta*na/ns,
                Vfb=beta*(va-ireg*rh),Vout_set=predicted,Vout_error=predicted-q['V_out'],
                Ifb_negative=q['V_in']*na/np_/rh,RfbH_min=q['V_in']*na/np_/.001,
                Rreg=rg,compensation_gain=gain,Ireg=ireg,compensation_offset=ireg*rh*ns/na,
                Rs_recommended=.128/op['I_sw_pk'],Ipk_limit_typ=.160/rs,Ipk_limit_min=.140/rs,
                Vcs_peak=rs*op['I_sw_pk'],Vcs_average=vs_avg,
                Lpri_min=reflected*.7e-6*rs/.033,tcon_min33=op['L']*(.033/rs)/reflected,
                tcon=op['Dp']*op['Ts'],sample_blank=.3e-6,
                sample_window=max(0,op['Dp']*op['Ts']-.3e-6),
                minimum_load=.5*op['L']*(.036/rs)**2*30e3*op['eta_guess'],
                Rcomp=r,Ccomp=cc,Cpole=cp,fz=1/(2*math.pi*r*cc),
                fp=(cc+cp)/(2*math.pi*r*cc*cp),KP=.00059/(cc+cp),gm=.00059,Vcc=v['psr_Vcc'],
                P_controller=q['V_in']*.0008+feedback_loss,P_feedback=feedback_loss,
                note='MODE 悬空；PSR PWM 为平均模型，含 gEA、辅助分压与半周期延迟近似；内部斜坡、采样细节与动态补偿未建精确模型。PFM 不给出 SSR Bode 裕度。')


def compensation_parts(tuning):
    if tuning['comp_type']!='type2': raise ValueError('MP6005 PSR COMP 网络仅支持二型补偿')
    wz,wp = 2*math.pi*tuning['fz1'],2*math.pi*tuning['fp1']
    if not 0<wz<wp or tuning['KP']<=0: raise ValueError('MP6005 COMP 参数不可实现')
    total = .00059/tuning['KP']
    cp = total*wz/wp
    cc = total-cp
    return dict(psr_Rcomp=1/(wz*cc),psr_Ccomp=cc,psr_Cpole=cp)
