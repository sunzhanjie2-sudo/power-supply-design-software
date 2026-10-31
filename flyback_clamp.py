"""Flyback drain-voltage envelope and RCD clamp bookkeeping.

The nominal path is a first-lobe leakage-L / constant-Coss model, not a
parasitic SPICE simulation.  It distinguishes the reflected-voltage plateau,
the actual clamp ceiling and a separate device-selection allowance.  The
coupled-winding transient solver's voltage/current arrays are authoritative
when present; they are never overlaid with another leakage pulse.

LC first-lobe reference (winding capacitance is not available in this model):
https://www.analog.com/en/resources/technical-articles/snubber-circuits-suppress-voltage-transient-spikes.html
Constant clamp power = Vc * average diode current:
https://www.ti.com/document-viewer/lit/html/SSZTCV6
"""
import math

import numpy as np


FLYBACKS = ('FLYBACK', 'QR-FLYBACK')


def _positive(value, default=0.):
    try:
        value = float(value)
    except (TypeError, ValueError):
        return float(default)
    return value if math.isfinite(value) and value > 0. else float(default)


def attach_clamp(op, p):
    """Attach a clamp dictionary to ``op`` and return the same dictionary.

    Legacy ``K`` retains its original convention Lsigma=(1-K)*L.  Pairwise
    coupling coefficients are exclusively handled by the matrix solver.
    ``V_sw_max`` is the Kc-defined stress ceiling (or a larger solved peak).
    The physical waveform peak remains separately available as V_peak.
    """
    if op.get('topology') not in FLYBACKS:
        return op
    vin = float(op.get('V_in_bus',op['V_in'])) if op.get('coupled_solution') is not None else float(op['V_in'])
    vr = _positive(op.get('V_r'))
    plateau = vin + vr
    kc = _positive(p.get('Kc'))
    ceiling = vin + kc * vr if kc > 1. else plateau
    solution = op.get('coupled_solution')
    if solution is not None:
        voltage = np.asarray(solution['v_sw'], dtype=float)
        current = np.asarray(solution.get('i_clamp', np.zeros_like(voltage)), dtype=float)
        time = np.asarray(solution['t'], dtype=float)
        off = np.mod(time, float(op['Ts'])) >= float(op['D'])*float(op['Ts'])
        quiet = off & (voltage > vin) & (current <= max(float(np.max(current))*1e-6, 1e-12))
        if np.any(quiet):
            plateau = float(np.median(voltage[quiet]))
        peak = float(np.max(voltage)) if voltage.size else plateau
        diagnostics = solution.get('diagnostics', op.get('coupled_model', {}).get('diagnostics', {}))
        matrix_vc = _positive(diagnostics.get('clamp_voltage'))
        if matrix_vc:
            ceiling = vin+matrix_vc
        p_res = diagnostics.get('P_clamp')
        if p_res is None:
            instantaneous = np.maximum(voltage-vin, 0.)*np.maximum(current, 0.)
            if time.size > 1:
                # Solver event grids can be nonuniform and include Ts.  Add
                # the closing endpoint only when it is genuinely absent.
                if time[-1] < time[0]+float(op['Ts']):
                    integration_t = np.r_[time,time[0]+float(op['Ts'])]
                    instantaneous = np.r_[instantaneous,instantaneous[0]]
                else:
                    integration_t = time
                p_res = float(np.trapezoid(instantaneous,integration_t)/float(op['Ts']))
            else:
                p_res = 0.
        matrix_leak = diagnostics.get('L_leak_primary', diagnostics.get('L_sigma_primary',diagnostics.get('L_leak')))
        op['clamp'] = dict(model='coupled_winding_transient', V_plateau=plateau,
            V_peak=peak, V_clamp=matrix_vc or max(peak-vin, 0.), V_ceiling=ceiling,
            P_res=max(float(p_res), 0.), E_clamp=max(float(p_res), 0.) / op['f_sw'],
            L_leak=matrix_leak, t_rise=None, t_decay=None, t_pulse=None,
            notes=['来自耦合绕组时域求解；理想定压钳位，不包含 Coss 边沿与寄生振铃。'])
        op['V_sw_max'] = max(ceiling, peak)
        op['V_sw_recommended'] = op['V_sw_max']
        return op

    ideal_fallback = bool(op.get('coupled_model', {}).get('ideal_fallback'))
    legacy_k = 1. if ideal_fallback else float(p.get('K', .95))
    leak = max((1. - legacy_k) * float(op['L']), 0.)
    i0 = _positive(op.get('I_sw_off', op.get('I_L_pk')))
    coss = _positive(p.get('Coss'))
    delta = max(ceiling - plateau, 0.)
    notes = ['快速包络：K 沿用历史 Lσ=(1−K)L 定义，不是绕组间 kij；不含寄生振铃。',
             'LC 首波瓣只使用常数 Coss，未计入变压器分布电容、器件电容非线性及钳位二极管恢复。']
    data = dict(model='nominal_leakage_envelope', V_plateau=plateau,
                V_peak=plateau, V_clamp=ceiling-vin, V_ceiling=ceiling,
                L_leak=leak, I_initial=i0, Coss=coss, t_rise=0., t_decay=0.,
                t_pulse=0., t_lc=0., I_clamp_start=0., E_clamp=0., P_res=0.,
                clamp_conducts=False, shape='none', notes=notes)
    if kc <= 1.:
        notes.append('未指定有效 Kc>1：仅显示理想阻断平台，未覆盖漏感尖峰；请设置钳位比并实测。')
    elif leak > 0. and i0 > 0. and delta > 0.:
        omega_time = math.sqrt(leak*coss) if coss else 0.
        natural = i0 * math.sqrt(leak/coss) if coss else math.inf
        if delta >= natural:
            # First natural leakage-Coss lobe cannot reach the clamp diode.
            # Later ringing is deliberately not invented without its network.
            data.update(V_peak=plateau+natural, t_rise=.5*math.pi*omega_time,
                        t_pulse=math.pi*omega_time, t_lc=omega_time,
                        shape='unclamped_lobe')
            notes.append('漏感能量不足以达到钳位电压：只显示 LC 首个正向波瓣，钳位功耗为 0。')
        else:
            rise = omega_time * math.asin(delta/natural) if coss else 0.
            iclamp = i0 * math.sqrt(max(1.-(delta/natural)**2, 0.)) if coss else i0
            decay = leak * iclamp / delta
            energy = .5 * (ceiling-vin) * iclamp * decay
            data.update(V_peak=ceiling, t_rise=rise, t_decay=decay,
                        t_pulse=rise+decay, t_lc=omega_time,
                        I_clamp_start=iclamp, E_clamp=energy,
                        P_res=energy*op['f_sw'], clamp_conducts=True,
                        shape='clamped')
            notes.append('Coss 充电至钳位后，漏感电流按 (Vc−Vr)/Lσ 衰减；释放边沿理想化。')
        if data['t_pulse'] >= (1.-float(op['D']))*float(op['Ts']):
            notes.append('警告：漏感复位时间达到关断区间，快速模型的独立周期假设失效。')
    else:
        notes.append('漏感或关断电流为 0：没有漏感尖峰，不能仅因 Kc>1 就画出钳位峰值。')
    op['clamp'] = data
    # Device stress uses the configured upper bound, not a manufactured spike.
    # With no specified clamp we cannot claim an unmodelled transient bound.
    op['V_sw_max'] = max(ceiling, data['V_peak'])
    op['V_sw_recommended'] = op['V_sw_max']
    return op


def leakage_pulse(elapsed, clamp):
    """Voltage above the reflected plateau since leakage commutation starts."""
    x = np.asarray(elapsed, dtype=float)
    pulse = np.zeros_like(x)
    if clamp.get('shape') == 'unclamped_lobe':
        tau = clamp['t_lc']
        active = (x >= 0.) & (x < clamp['t_pulse'])
        pulse[active] = ((clamp['V_peak']-clamp['V_plateau']) * np.sin(x[active]/tau))
    elif clamp.get('shape') == 'clamped':
        rise = clamp['t_rise']
        active = (x >= 0.) & (x < clamp['t_pulse'])
        pulse[active] = clamp['V_peak']-clamp['V_plateau']
        charging = active & (x < rise)
        if rise > 0.:
            # Match the exact LC trajectory up to the ideal clamp ceiling.
            amplitude = clamp['I_initial']*math.sqrt(clamp['L_leak']/clamp['Coss'])
            pulse[charging] = amplitude*np.sin(x[charging]/clamp['t_lc'])
    return pulse


def clamp_voltage(t, op):
    """Nominal periodic Vds including the leakage envelope (SI seconds)."""
    clamp = op.get('clamp')
    phase = np.mod(np.asarray(t, dtype=float), float(op['Ts']))
    on = phase < float(op['D'])*float(op['Ts'])
    plateau = clamp['V_plateau'] if clamp else op['V_in']+op['V_r']
    voltage = np.where(on, 0., plateau)
    if clamp and clamp.get('model') == 'nominal_leakage_envelope':
        voltage += leakage_pulse(phase-float(op['D'])*float(op['Ts']), clamp)
    return voltage


def clamp_current(t, op):
    """RCD diode current, separate from switch current and Coss charging."""
    time = np.asarray(t, dtype=float)
    solution = op.get('coupled_solution')
    if solution is not None:
        st = np.asarray(solution['t'], dtype=float)
        si = np.asarray(solution.get('i_clamp', np.zeros_like(st)), dtype=float)
        if len(st):
            return np.interp(np.mod(time, op['Ts']), np.r_[st, op['Ts']], np.r_[si, si[0]])
        return np.zeros_like(time)
    c = op.get('clamp', {})
    current = np.zeros_like(time)
    if c.get('shape') == 'clamped':
        elapsed = np.mod(time, op['Ts'])-op['D']*op['Ts']-c['t_rise']
        active = (elapsed >= 0.) & (elapsed < c['t_decay'])
        current[active] = c['I_clamp_start']*(1.-elapsed[active]/max(c['t_decay'], 1e-30))
    return current


def rcd_components(op, p):
    """Size the clamp R/C from the same clamp power as the design ledger.

    C≈P/(fs*Vc*deltaVc) is the small-ripple charge-balance approximation,
    not a separate leakage-energy estimate.  Matrix-model P is an integral
    of its actual clamp current; no equivalent-leakage power is added.
    """
    c = op.get('clamp')
    if c is None:
        attach_clamp(op,p)
        c = op.get('clamp')
    if c is None:
        raise ValueError('RCD components require a flyback operating point')
    power = max(float(c['P_res']), 0.)
    vc = max(float(c['V_clamp']), 0.)
    dv = max(float(p.get('dC', .10)), 0.)*vc
    f = float(op['f_sw'])
    resistance = vc*vc/power if power > 0. else math.inf
    capacitance = power/(f*vc*dv) if power > 0. and vc > 0. and dv > 0. else 0.
    leak = c.get('L_leak')
    return dict(K=p.get('K', .95), Kc=p.get('Kc', 0.), Lm=op['L'],
                L_leak=leak, V_reflect=c['V_plateau']-op.get('V_in_bus',op['V_in']),
                V_clamp=vc, dV_clamp=dv,
                E_leak=.5*leak*op['I_L_pk']**2 if leak is not None else None,
                P_user=c['E_clamp'], E_clamp=c['E_clamp'], P_res=power,
                R_snub=resistance, C_snub=capacitance, model=c['model'],
                notes=list(c['notes']))
