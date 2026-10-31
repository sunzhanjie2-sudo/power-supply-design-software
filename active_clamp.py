"""Low-side active-clamp forward: first-order steady-state engineering model.

N = Np/Ns; L is the OUTPUT choke, Lm_forward is transformer magnetizing L.
Two diode secondary (forward + freewheel), symmetric triangular magnetizing
current and small clamp ripple. No blanket ZVS credit is applied to losses.
References: TI SLUA535A sections 2/4.3/6 and SLUP262 equations 3/11/12.
https://www.ti.com/lit/an/slua535a/slua535a.pdf
https://e2e.ti.com/cfs-file/__key/communityserver-discussions-components-files/234/slup262.pdf
"""

import numpy as np


def compute_forward_op(p):
    from power_stage import _with_efficiency
    return _with_efficiency(p, _compute_forward_op)


def _compute_forward_op(p):
    from power_stage import _tri_rms

    vin, vo, power, fs, L, N = (float(p[k]) for k in
                               ('V_in', 'V_out', 'P_out', 'f_sw', 'L', 'N'))
    lm = float(p.get('Lm_forward', 220e-6))
    cc = float(p.get('C_clamp', 47e-9))
    duty_max = float(p.get('forward_d_max', 0.7))
    dead = float(p.get('forward_dead_time', 80e-9))
    if not all(np.isfinite(v) and v > 0 for v in
               (vin, vo, power, fs, L, N, lm, cc, p['C_out'])):
        raise ValueError('有源钳位正激: 电压/功率/频率/L/Lm/N/C 必须为有限正数')
    if not 0 < duty_max < 1 or not np.isfinite(dead) or dead < 0:
        raise ValueError('有源钳位正激: 0 < 最大占空比 < 1, 死区时间 ≥ 0')
    vf = float(p.get('Vf', 0.7))
    for name, default in (('Vf', .7), ('ring_margin', .3), ('Rds_aux', .1),
                          ('Qg_aux', 10e-9), ('Coss_aux', 200e-12), ('ESR_clamp', .03)):
        value = float(p.get(name, default))
        if not np.isfinite(value) or value < 0:
            raise ValueError(f'有源钳位正激: {name} 必须为有限非负数')
    vs = vin / N
    if vs <= vo + vf:
        raise ValueError('正激次级电压 Vin/N 必须高于 Vout+Vf；请减小 Np/Ns')
    T = 1 / fs
    io = power / vo
    # Both secondary diodes have the same forward drop. During freewheel
    # the choke sees -(Vo+Vf); volt-second balance: D= (Vo+Vf)/Vs.
    d_ccm = (vo + vf) / vs
    di = (vs - vo - vf) * d_ccm * T / L
    if io >= di / 2:
        mode, D = 'CCM', d_ccm
        valley, peak, Dp = io - di / 2, io + di / 2, 1 - D
    else:
        mode = 'DCM'
        D = np.sqrt(2 * io * L * (vo + vf) * fs /
                    (vs * (vs - vo - vf)))
        peak = (vs - vo - vf) * D * T / L
        valley, di = 0.0, peak
        Dp = (vs - vo - vf) * D / (vo + vf)
    if D >= duty_max:
        raise ValueError(f'正激占空比 {D:.3f} 达到/超过上限 {duty_max:.3f}；减小匝比 N 或提高输入电压')
    if 2 * dead >= min(D, 1 - D) * T:
        raise ValueError('死区时间过长，主开关或复位导通区间不足')
    # Primary reset is active throughout OFF, even after the choke enters
    # DCM. Small-ripple approximation, bipolar magnetizing current.
    dim = vin * D * T / lm
    im = dim / 2
    sw_start, sw_end = valley / N - im, peak / N + im
    sw_rms = _tri_rms(sw_end, sw_start, D)
    aux_rms = im * np.sqrt((1 - D) / 3)
    v_block = vin / (1 - D)   # LOW-side clamp capacitor and both primary FETs
    v_reset = v_block - vin
    hump = vin * D * (1 - D) / (8 * lm * fs**2 * cc)
    f_res = 1 / (2 * np.pi * np.sqrt(lm * cc))
    # Effective clamp natural frequency for the averaged current loop.
    f_effective = (1 - D) * f_res
    ring = float(p.get('ring_margin', .3))
    v_peak = (v_block + hump) * (1 + ring)
    rect_rms = _tri_rms(peak, valley, D)
    free_rms = _tri_rms(peak, valley, Dp)
    dv = max(float(p.get('ripple_target', .01)) * vo, 1e-12)
    # Positive capacitor charge: CCM triangle, or DCM portion above Io.
    q_ripple = (di*T/8 if mode == 'CCM'
                else io*T*(1-io/peak)**2)
    cap_rms = im * np.sqrt((1 - D) / 3)
    warnings = [
        '低侧有源钳位、双二极管整流；励磁电流与钳位波形为小纹波近似，未建模漏感换流细节。',
        'ZVS 需结合负励磁电流、输出电感电流及寄生电容验证；当前损耗保留主 MOSFET 硬开通估算。',
    ]
    if hump / v_block > .1:
        warnings.append('钳位电压隆起超过 10%，小纹波近似偏弱；增大 C_clamp 后复核。')
    if 2 * dead / T > .05:
        warnings.append('死区占周期比例超过 5%；有效占空比/波形需用开关级仿真复核。')
    return dict(
        topology='ACF-FORWARD', V_in=vin, V_out=vo, P_out=power,
        f_sw=fs, Ts=T, R=vo**2/power, I_out=io, L=L, C_out=p['C_out'],
        Rc=p['Rc'], Rs=p['Rs'], N=N, Vf=vf, ring_margin=ring,
        D=D, Dp=Dp, mode=mode, I_L_avg=io, I_L_min=valley, I_L_pk=peak,
        dI_L=di, I_L_rms=_tri_rms(peak, valley, D+Dp),
        I_sw_rms=sw_rms, I_sw_pk=max(abs(sw_start), abs(sw_end)),
        I_sw_avg=(sw_start+sw_end)*D/2,
        I_sw_on=sw_start, I_sw_off=sw_end, V_sw_max=v_peak,
        I_d_rms=rect_rms, I_d_avg=(peak+valley)*D/2, I_d_pk=peak,
        V_d_max=v_reset/N, V_d_block=v_reset/N,
        I_free_rms=free_rms, I_free_avg=(peak+valley)*Dp/2,
        I_free_pk=peak, V_free_max=vs, V_free_block=vs,
        I_aux_rms=aux_rms, I_aux_pk=im, I_aux_avg_abs=im*(1-D)/2,
        I_p_rms=np.sqrt(sw_rms**2+aux_rms**2), I_s_rms=rect_rms,
        Lm_forward=lm, C_clamp=cc, forward_dead_time=dead,
        forward_d_max=duty_max, I_mag_pk=im, dI_mag=dim,
        V_reset=v_reset, V_clamp=v_block, V_clamp_hump=hump,
        I_clamp_rms=cap_rms, f_clamp=f_res, f_clamp_effective=f_effective,
        fc_recommended_max=min(fs/10, f_effective/5),
        C_clamp_min=vin*D*(1-D)/(8*lm*fs**2*.05*v_block),
        rhp_zero=np.inf, L_min=(vs-vo-vf)*d_ccm/(2*fs*io)*1.5,
        C_min=q_ripple/dv, pwr_factor=1.0,
        ESL=p.get('ESL',0), C_out2=p.get('C_out2',p['C_out']),
        Rc2=p.get('Rc2',p['Rc']), ESL2=p.get('ESL2',0),
        cout2_enable=bool(p.get('cout2_enable',False)),
        tr=p.get('tr',20e-9), tf=p.get('tf',20e-9), warnings=warnings)


def forward_waveforms(op, t):
    from waveforms import _tri_phase
    T, D = op['Ts'], op['D']
    ph = (t % T) / T
    on = ph < D
    il = _tri_phase(t, T, D, op['Dp'], op['I_L_pk'], op['I_L_min'])
    im = np.where(on, -op['I_mag_pk']+op['dI_mag']*ph/D,
                  op['I_mag_pk']-op['dI_mag']*(ph-D)/(1-D))
    ip = np.where(on, il/op['N']+im, im)
    # Integral of reset current: capacitor returns to the same voltage each
    # cycle. SLUP262 eq.12 gives the peak of the parabolic clamp-voltage hump.
    x = np.clip((ph-D)/(1-D), 0, 1)
    vc = op['V_clamp'] + np.where(on, 0, 4*op['V_clamp_hump']*x*(1-x))
    return dict(iL=il, i_mag=im, i_p=ip, i_s=np.where(on,il,0),
                i_sw=np.where(on,ip,0), i_aux=np.where(on,0,im),
                i_d=np.where(on,il,0), i_free=np.where(on,0,il),
                i_c=il-op['I_out'], i_in=np.where(on,ip,0),
                v_sw=np.where(on,0,vc), v_clamp=vc,
                v_primary=np.where(on,op['V_in'],-op['V_reset']),
                v_d=np.where(on,0,op['V_d_block']),
                v_free=np.where(on,op['V_free_block'],0))
