"""Low-frequency peak-current-controlled BCM flyback linearization.

Uses a charge-per-switching-cycle average, not a fixed-frequency PWM model.
The optional measured point is an explicit caller choice and never mutates the
user design. This model excludes switch/valley transitions, sample delay,
magnetics nonlinearity, optical feedback and valley-number changes.
"""
import math


def _multi_context(p, op, measured):
    """Refer passive loads/banks to the feedback winding's capacitor node.

    The held turns ratios are a low-frequency reduction, not a separate
    secondary commutation solution. Fixed diode drops remain DC offsets;
    small-signal voltage ratios follow Ns_j/Ns_feedback, not Vport_j/Vport_fb.
    """
    from isolated_outputs import selected_params
    from output_capacitors import branches
    rails = op.get('outputs') or []
    if not rails:
        return p, op, None
    selected = int(op.get('feedback_output', p.get('feedback_output', 1))) - 1
    children = op.get('output_ops') or []
    if len(children) != len(rails) or not 0 <= selected < len(rails):
        raise ValueError('多路QR缺少对应的各路工作点或有效反馈路')
    q = selected_params(p, rails)
    q['outputs'] = []
    nominal = dict(op, **{key: children[selected][key] for key in
                   ('V_out','V_out_cap','I_out','P_out') if key in children[selected]})
    nominal['N'] = q['N']
    turns = [float(r['Ns']) for r in rails]
    if any(not math.isfinite(n) or n <= 0 for n in turns):
        raise ValueError('多路QR环路需要每路实际正整数匝数')
    ratios = [n / turns[selected] for n in turns]
    m = measured or {}
    arrays = {}
    for key, fallback in (
            ('rail_currents', [c['I_out'] for c in children]),
            ('rail_voltages', [c['V_out'] for c in children]),
            ('rail_cap_voltages', [c.get('V_out_cap', c['V_out']) for c in children])):
        values = m.get(key, fallback)
        if not isinstance(values, (list, tuple)) or len(values) != len(rails):
            raise ValueError(f'多路QR实测数组 {key} 必须与输出逐路对应')
        values = [float(v) for v in values]
        if any(not math.isfinite(v) or v < 0 for v in values):
            raise ValueError(f'多路QR实测数组 {key} 不能含负值或无效值')
        arrays[key] = values
    # Backward-compatible scalar overrides always belong to the selected rail.
    for scalar, array in (('iout','rail_currents'),('vout','rail_voltages'),('vcap','rail_cap_voltages')):
        if scalar in m:
            arrays[array][selected] = float(m[scalar])
    if any(v <= 0 for v in arrays['rail_voltages']):
        raise ValueError('多路QR环路要求各路正的端口电压')
    equivalent_current = sum(r*i for r,i in zip(ratios, arrays['rail_currents']))
    equivalent_conductance = sum(r*r*i/v for r,i,v in zip(
        ratios, arrays['rail_currents'], arrays['rail_voltages']))
    caps, banks = [], []
    for index, (rail, ratio) in enumerate(zip(rails, ratios), 1):
        raw = branches(rail)
        # r² multiplies admittance. Transforming C and ESR inversely preserves
        # every original branch's ESR time constant, even for >2 capacitors.
        caps.extend((cap*ratio**2, esr/ratio**2) for cap, esr in raw)
        banks.append(dict(output=index, turns=turns[index-1], voltage_ratio=ratio,
                          branches=[dict(C=c, ESR=r) for c,r in raw]))
    return q, nominal, dict(feedback_output=selected+1, voltage_ratios=ratios,
        equivalent_current=equivalent_current, load_conductance=equivalent_conductance,
        capacitors=caps, capacitor_banks=banks,
        outputs=[dict(id=r.get('id',j), name=r.get('name',f'OUT{j}'),
                      voltage=arrays['rail_voltages'][j-1]) for j,r in enumerate(rails,1)],
        scope='ideal-ratio-reduced', independent_cross_regulation=False,
        dc_point_source='qr-coupled-valley' if op.get('qr_coupled_model') else 'nominal-ideal-ratio',
        assumptions='多路QR共用峰值电流与变频周期，按实际Ns/Ns反馈路把各负载增量电导和每颗C/ESR折算到防反管前反馈节点。'
                    '固定整流/防反压降仅是直流偏置。低频刚性匝比约化不含各路漏感换流、轻载脉冲、'
                    '独立负载动态或交叉调整率；实际电路FRA及交叉角点用于独立复核。',
        measured_rails_complete=all(key in m for key in ('rail_currents','rail_voltages','rail_cap_voltages')) if measured else False)


def linearize(p, op, *, measured=None):
    from output_capacitors import branches
    from voltage_nodes import output_drop,input_drop
    p,op,multi = _multi_context(p, op, measured)
    m=measured or {}
    L=float(p['L']);N=float(p['N']);gain=float(p['A_sense'])*float(p['Rs'])
    vout=float(m.get('vout',op['V_out']));vcap=float(m.get('vcap',op.get('V_out_cap',vout+output_drop(p))))
    vin=float(m.get('vin_bus',op.get('V_in',float(p['V_in'])) if not measured else op.get('V_in_bus',float(p['V_in'])-input_drop(p))))
    ipk=float(m.get('ipk',op['I_sw_pk']));period=float(m.get('period',op['Ts']))
    iload=float(multi['equivalent_current'] if multi else m.get('iout',float(op['P_out'])/float(op['V_out'])))
    if min(L,N,gain,vout,vcap,vin,ipk,period,iload)<=0:
        raise ValueError('QR 环路工作点、电感及 CS 增益必须为正')
    # The analytical QR operating-point solver uses Vf and port Vout, whereas
    # the SPICE circuit uses Vcap + the rectifier Vf. Preserve each convention.
    vr=float(m.get('vreflected',N*(vcap+float(p.get('Vf_diode',0.7))) if measured else op['V_r']))
    if vr<=0:raise ValueError('QR 反射电压必须为正')
    a=L*(1/vin+1/vr)
    dead=period-a*ipk
    if dead < -period*1e-6:
        raise ValueError('QR 工作点的周期小于导通和退磁时间之和，不能按 BCM 线性化')
    dead=max(0.,dead)
    raw=N*L*ipk**2/(2*vr*period)
    # Constant local scaling reconciles the chosen steady-state current with
    # the ideal triangle. It is held fixed during derivatives, not a dynamic
    # semiconductor loss or capacitor-voltage correction model.
    factor=iload/raw
    di=iload*(2/ipk-a/period)
    dv=iload*(-N/vr+L*ipk*N/(vr**2*period))
    load_g=multi['load_conductance'] if multi else iload/vout
    R=1/load_g
    g=load_g-dv
    if g<=0:raise ValueError('QR 低频输出增量电导非正，不能使用该近似')
    return dict(vin_bus=vin,vout=vout,vcap=vcap,ipk=ipk,period=period,dead_time=dead,
        vreflected=vr,iout=iload,raw_iout=raw,current_scale=factor,
        d_iout_d_ipk=di,d_iout_d_vcap=dv,sense_gain=gain,load_resistance=R,
        output_conductance=g,load_conductance=load_g,
        capacitors=multi['capacitors'] if multi else branches(p),
        point_source='measured' if measured else 'design',multi_output=multi)


def plant(p, op, *, measured=None):
    import control as ct
    x=linearize(p,op,measured=measured);s=ct.tf('s')
    admittance=0
    for C,esr in x['capacitors']:
        admittance += s*C/(1+s*esr*C)
    result=(x['d_iout_d_ipk']/x['sense_gain'])/(x['output_conductance']+admittance)
    result=ct.minreal(result,verbose=False)
    if x['multi_output']:
        detail=x['multi_output']
        result._loop_metadata=dict(kind='qr-ideal-ratio-aggregate',experimental=False,
            feedback_output=detail['feedback_output'],outputs=detail['outputs'],
            scope=detail['scope'],independent_cross_regulation=False,
            voltage_ratios=detail['voltage_ratios'],capacitor_banks=detail['capacitor_banks'],
            assumptions=detail['assumptions'])
    return result,x
