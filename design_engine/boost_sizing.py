"""Asynchronous LM5022 Boost draft. SI values, fixed hardware for all input voltages."""
import json

from app_resources import resource_path
from .preferred_values import E12, E24, standard
from .specification import load_spec


def _sense(peak, duty, off_swing):
    # Select both resistors together. 0.45 V is the minimum trip threshold.
    # Project screening scales the datasheet's 83–137 mV ramp envelope with
    # total CS resistance; nominal waveforms use nonisolated.slope().
    cs_min, cs_max = .45, .55
    ramp_min, ramp_max = .083, .137
    rs = standard((cs_min-ramp_max*duty)/(1.25*peak), E24, False)
    for _ in range(len(E24)*4):
        needed = max(0., 2000.*(.5*off_swing*rs/ramp_min - 1.))
        external = standard(needed,E24,True) if needed > 1e-4 else 0.
        ramp = ramp_max*(1.+external/2000.)
        if external <= 10000. and 1.25*peak*rs+ramp*duty <= cs_min:
            return rs, external, dict(cs_min=cs_min, cs_max=cs_max, ramp_upper=ramp,
                                      prospective_fault_current=cs_max/rs)
        rs = standard(rs*.999, E24, False)
    raise ValueError('未找到可同时满足限流余量和斜坡补偿的采样电阻组合')


def power_stage(s, locked):
    name = '24W_BOOST_PCM_LM5022'
    p = json.loads(resource_path('examples/'+name+'.json').read_text(encoding='utf-8'))
    lo, hi, vo, io, fs, eta = (s[k] for k in ('vin_min','vin_max','vout','iout','fs','eta_guess'))
    rated_power = io*vo
    iin = rated_power/(eta*lo)
    di, dv = s['il_ratio']*iin, s['ripple']*vo
    max_duty = 1.-eta*lo/vo
    if max_duty >= p['spice_config']['duty_max']:
        raise ValueError(f"低线预估占空比 {max_duty:.1%} 已达到参考模型上限 {p['spice_config']['duty_max']:.0%}，请调整输入范围或升压比")
    # With the design-efficiency duty estimate, V·D(V) is concave and has
    # an interior maximum at Vo/(2η). The input-current maximum is at Vinmin.
    witness = max(lo,min(hi,vo/(2*eta)))
    v_seconds = witness*(1.-eta*witness/vo)/fs
    l_min = v_seconds/di
    inductance = locked.get('L',standard(l_min,E12,True))
    peak = iin+di/2
    dcr_budget = .005*rated_power/(iin**2+di**2/12)
    dcr = locked.get('inductor_dcr',standard(dcr_budget,E24,False))
    rs, external, cs_rules = _sense(peak,max_duty,(vo+p['Vf_diode']-lo)/(inductance*fs))

    # Input sees triangular ripple; while the MOS is on, Cout alone supplies Io.
    cin_min = di/(8*fs*.01*lo)
    c_charge = io*max_duty/(fs*.5*dv)
    load_step = 0. if s['imin'] is None else io-s['imin']
    c_step = load_step/(fs*dv)
    esr_out = .5*dv/peak
    for side, capacitance, esr in (('input',cin_min,.01*lo/di),('output',max(c_charge,c_step),esr_out)):
        p[side+'_capacitors'] = locked.get(side+'_capacitors',[
            dict(C=standard(capacitance,E12,True), ESR=standard(min(.035,esr),E24,False), ESL=1e-9)])
    p.update(V_in_min=lo,V_in_max=hi,V_in=lo,input_voltage_case='min',V_out=vo,
             P_out=rated_power,P_out_min=vo*(s['imin'] or 0.),f_sw=fs,eta_guess=eta,L=inductance,
             inductor_design_enabled=False,inductor_dcr=dcr,Rs=rs,A_sense=1.,controller_type='type2',
             ripple_target=s['ripple'],pm_target=s['pm'])
    p['spice_config'].update(niso_lm_cs_resistor=external,niso_inductor_dcr=-1.)
    rules = dict(template=name,L_min=l_min,delta_i_target=di,delta_v_limit=dv,
                 input_current_design=iin,peak_design=peak,duty_estimate=max_duty,
                 ripple_witness_vin=witness,DCR_budget=dcr_budget,
                 C_out_charge=c_charge,C_out_step=c_step,C_in_charge=cin_min,
                 ESR_out_ceiling=esr_out,cs_external_ohm=external,rhp_divisor=5.,
                 locked=list(locked),**cs_rules)
    return load_spec(p),rules
