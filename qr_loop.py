"""Low-frequency peak-current-controlled BCM flyback linearization.

Uses a charge-per-switching-cycle average, not a fixed-frequency PWM model.
The optional measured point is an explicit caller choice and never mutates the
user design. This model excludes switch/valley transitions, sample delay,
magnetics nonlinearity, optical feedback and valley-number changes.
"""
import math


def linearize(p, op, *, measured=None):
    from output_capacitors import branches
    from voltage_nodes import output_drop,input_drop
    m=measured or {}
    L=float(p['L']);N=float(p['N']);gain=float(p['A_sense'])*float(p['Rs'])
    vout=float(m.get('vout',op['V_out']));vcap=float(m.get('vcap',op.get('V_out_cap',vout+output_drop(p))))
    vin=float(m.get('vin_bus',op.get('V_in',float(p['V_in'])) if not measured else op.get('V_in_bus',float(p['V_in'])-input_drop(p))))
    ipk=float(m.get('ipk',op['I_sw_pk']));period=float(m.get('period',op['Ts']))
    iload=float(m.get('iout',float(op['P_out'])/float(op['V_out'])))
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
    R=vout/iload
    g=1/R-dv
    if g<=0:raise ValueError('QR 低频输出增量电导非正，不能使用该近似')
    return dict(vin_bus=vin,vout=vout,vcap=vcap,ipk=ipk,period=period,dead_time=dead,
        vreflected=vr,iout=iload,raw_iout=raw,current_scale=factor,
        d_iout_d_ipk=di,d_iout_d_vcap=dv,sense_gain=gain,load_resistance=R,
        output_conductance=g,capacitors=branches(p),point_source='measured' if measured else 'design')


def plant(p, op, *, measured=None):
    import control as ct
    x=linearize(p,op,measured=measured);s=ct.tf('s')
    admittance=0
    for C,esr in x['capacitors']:
        admittance += s*C/(1+s*esr*C)
    result=(x['d_iout_d_ipk']/x['sense_gain'])/(x['output_conductance']+admittance)
    return ct.minreal(result,verbose=False),x
