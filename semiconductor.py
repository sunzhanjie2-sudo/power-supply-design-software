"""Power-semiconductor stress and loss estimation.

MOSFET (switch) and rectifier diode for each topology:

- voltage / current stress (used for device selection)
- conduction loss, switching loss (linearised Eon/Eoff), gate-drive loss,
  Coss discharge loss
- diode conduction loss + optional reverse-recovery loss

Loss formulas are first-order engineering estimates (see README references);
for accurate numbers use the device datasheet curves (Eon/Eoff vs V/I).
"""

import math
from stress_notes import DIODE_STRESS_NOTE, FLYBACK_STRESS_NOTE

from power_stage import (TOPO_BUCK, TOPO_BOOST, TOPO_BUCKBOOST, TOPO_FLYBACK,
                         TOPO_QRFLYBACK)


# ----------------------------------------------------------------------------
# Stress
# ----------------------------------------------------------------------------
def device_stress(op):
    """Stress summary for the switch and the rectifier diode."""
    topo = op['topology']
    sw = {'I_rms': op['I_sw_rms'], 'I_pk': op['I_sw_pk'],
          'I_avg': op['I_sw_avg'], 'V_max': op['V_sw_max']}
    d = {'I_rms': op['I_d_rms'], 'I_pk': op['I_d_pk'],
         'I_avg': op['I_d_avg'], 'V_max': op['V_d_max']}
    if topo in (TOPO_FLYBACK, TOPO_QRFLYBACK):
        # Keep the physical plateau distinct from the configured Kc ceiling.
        V_ref = op['V_r']
        sw['V_block'] = op['V_in'] + V_ref
        if op.get('clamp'):
            sw['V_block'] = op['clamp']['V_plateau']
            sw['V_peak_physical'] = op['clamp']['V_peak']
            sw['V_recommended'] = op.get('V_sw_recommended', sw['V_max'])
            sw['clamp_model'] = op['clamp']['model']
        d['V_block'] = op['V_out_equiv'] + op['V_in'] / op['N']
        if op.get('branch_mode'):
            d['V_block'] = op['V_d_max']
    else:
        sw['V_block'] = op['V_sw_max'] / (1.0 + op['ring_margin'])
        d['V_block'] = op['V_d_max']

    if topo == TOPO_BUCK:
        sw['note'] = 'low-side free-wheel; hard switching'
        d['note'] = 'free-wheeling diode'
    elif topo == TOPO_BOOST:
        sw['note'] = 'boost switch, hard switching'
        d['note'] = 'output diode (reverse recovery!)'
    elif topo == TOPO_BUCKBOOST:
        sw['note'] = 'inverting switch, hard switching'
        d['note'] = 'output diode (reverse recovery!)'
    elif topo == TOPO_FLYBACK:
        sw['note'] = 'primary MOSFET + leakage spike'
        d['note'] = 'output rectifier'
    elif topo == TOPO_QRFLYBACK:
        sw['note'] = 'QR: valley switching, Eon ~ 0'
        d['note'] = 'output rectifier (BCM, no reverse recovery)'
    if topo in (TOPO_FLYBACK,TOPO_QRFLYBACK) and op.get('clamp'):
        c=op['clamp']
        sw['note'] += ('；'+FLYBACK_STRESS_NOTE if c['V_ceiling'] > op['V_in']+op['V_r']
                       else '；未配置有效 Kc>1，仅理想阻断平台，未覆盖漏感尖峰应力，须实测。')
    result = {'switch': sw, 'diode': d}
    if topo == 'ACF-FORWARD':
        sw['V_block'] = op['V_clamp']
        d['V_block'] = op['V_d_block']
        sw['note'] = '正激主 MOSFET: 反射负载+双极性励磁电流；保守硬开通估算'
        d['note'] = '正向整流二极管，仅 ON 导通；续流器件另列'
        result['auxiliary'] = dict(I_rms=op['I_aux_rms'], I_pk=op['I_aux_pk'],
                                  I_avg=op['I_aux_avg_abs'], V_max=op['V_sw_max'],
                                  V_block=op['V_clamp'], note='有源钳位辅助 MOSFET')
        result['freewheel'] = dict(I_rms=op['I_free_rms'], I_pk=op['I_free_pk'],
                                  I_avg=op['I_free_avg'], V_max=op['V_free_max'],
                                  V_block=op['V_free_block'], note='输出续流二极管')
    for key in ('diode', 'freewheel'):
        if key in result:
            result[key]['note'] = result[key].get('note', '')+'；'+DIODE_STRESS_NOTE
            result[key]['includes_parasitic_spikes'] = False
    return result


# ----------------------------------------------------------------------------
# Losses
# ----------------------------------------------------------------------------
def mosfet_loss(op, dev, sw_stress=None):
    """MOSFET loss using the gate-charge switching-loss model (data-sheet
    parameters) plus Coss discharge loss.

    Switching times follow mosfet损耗计算.xlsx (charges in C, times in s):

        Rg_on  = Rg_drive + Rs_on  + Rg
        Rg_off = Rg_drive + Rs_off + Rg
        t1 = -Rg_on*Qg(th)/Vth * ln(1 - Vth/Vgs)
        t2 = -Rg_on*Qgs/Vgp_on * ln(1 - Vgp_on/Vgs) - t1
        t3 = Qgd*Rg_on/(Vgs - Vgp_on)
        t6 = Qgd*Rg_off/Vgp_off
        t7 = -Rg_off*(Qgs-Qg(th))/(Vgp_off-Vth) * ln(Vth/Vgp_off)
        t8 = 3*Rg_off*Qg(th)/Vth

    t8 uses the spreadsheet's three-time-constant discharge approximation,
    not the mathematically infinite time to reach exactly zero volts.

        Ptr = k * Vds * Ids_on  * (t2 + t3) * f
        Ptf = k * Vds * Ids_off * (t6 + t7) * f     (k=1/4 inductive, 1/6 resistive)

    Coss loss (hard switching) is added separately: P_coss = 0.5*Coss*Vds^2*f.

    dev: dict with Rds_on, Vgs, Qg, Coss and the gate-charge params
         Vth, Vgp_on, Vgp_off, Qg_th, Qgs, Qgd, Rg_drive, Rs_on, Rs_off,
         Rg, k_sw. Optional gfs>0 derives Vgp=Vth+Id/gfs separately for
         each event, and maps Qgs using the reference Vgp_on charge point.
         gfs=0 preserves the worksheet's original fixed-plateau model.
    """
    topo = op['topology']
    f = op['f_sw']
    sw = sw_stress or device_stress(op)['switch']
    I_rms = sw['I_rms']
    V_ds = sw['V_max']
    Rds, Coss, Qg, Vgs = (dev['Rds_on'], dev['Coss'], dev['Qg'], dev['Vgs'])
    Vth = float(dev.get('Vth', 2.5))
    from mos_gate import operating_gate
    gate = operating_gate(op, dev)
    Vgp_on, Vgp_off = gate['Vgp_on'], gate['Vgp_off']
    Qgs_on, Qgs_off = gate['Qgs_on'], gate['Qgs_off']
    Qg_th = gate['Qg_th']
    Qgs = gate['Qgs_on']
    Qgd = gate['Qgd_on']
    Qgd_off=gate['Qgd_off']
    Qg=gate['Qg_on']
    Rg_drive = float(dev.get('Rg_drive', 2.0))
    Rs_on = float(dev.get('Rs_on', 4.7))
    Rs_off = float(dev.get('Rs_off', 4.7))
    Rg = float(dev.get('Rg', 1.5))
    k = float(dev.get('k_sw', 0.25))

    gate_params = dict(Vgs=Vgs, Vth=Vth, Vgp_on=Vgp_on, Vgp_off=Vgp_off,
                       Qg_th=Qg_th, Qgs=Qgs, Qgd=Qgd, Rg_drive=Rg_drive,
                       Rs_on=Rs_on, Rs_off=Rs_off, Rg=Rg)
    for key, value in gate_params.items():
        if not math.isfinite(value):
            raise ValueError(f'MOS 栅电荷法参数 {key} 必须为有限数值')
    if not 0 < Vth <= Vgp_on < Vgs:
        raise ValueError('MOS 栅电荷法要求 0 < Vth < Vgp_on < Vgs；请核对阈值、平台和驱动电压')
    if Vgp_off<Vth:
        raise ValueError('MOS 栅电荷法要求 Vgp_off ≥ Vth；请核对关断平台电压')
    for key in ('Qg_th', 'Qgs', 'Qgd', 'Rg_drive', 'Rs_on', 'Rs_off', 'Rg'):
        if gate_params[key] < 0:
            raise ValueError(f'MOS 栅电荷法参数 {key} 不能为负')
    if min(Qgs_on,Qgs_off) < Qg_th or not math.isfinite(Qgs_off):
        raise ValueError('MOS 栅电荷法要求 Qgs >= Qg_th；请核对栅电荷曲线')

    Rg_on = Rg_drive + Rs_on + Rg
    Rg_off = Rg_drive + Rs_off + Rg

    def gate_times():
        # log1p is algebraically identical to the worksheet's LN expressions
        # and retains precision for small voltage ratios / nearby voltages.
        t1 = -Rg_on * Qg_th / Vth * math.log1p(-Vth / Vgs)
        t2 = -Rg_on * Qgs_on / Vgp_on * math.log1p(-Vgp_on / Vgs) - t1
        if gate['mode'] != 'fixed' and Vgp_on == Vth:
            t2 = 0.  # exact zero-current limit, not a synthetic epsilon load
        if t2 < 0:
            raise ValueError('MOS 栅电荷法得到负 t2；请核对 Qgs、Qg_th 与开通平台电压')
        t3 = Qgd * Rg_on / (Vgs - Vgp_on)
        t6 = Qgd_off * Rg_off / Vgp_off
        dv = Vgp_off - Vth
        t7 = (Rg_off * (Qgs_off - Qg_th) / dv * math.log1p(dv / Vth)
              if dv > 0 else 0.)
        t8 = 3.0 * Rg_off * Qg_th / Vth
        return dict(t1=t1, t2=t2, t3=t3, t6=t6, t7=t7, t8=t8)

    P_cond = Rds * I_rms ** 2
    if topo == TOPO_QRFLYBACK:
        # valley switching: Eon ~ 0, Coss recovered; turn-off is hard at I_pk
        Ids_off = gate['I_off']
        times = gate_times()
        P_sw_on = 0.0
        P_sw_off = k * V_ds * Ids_off * (times['t6'] + times['t7']) * f
        P_coss = 0.0
    else:
        Ids_on, Ids_off = gate['I_on'], gate['I_off']
        times = gate_times()
        P_sw_on = k * V_ds * Ids_on * (times['t2'] + times['t3']) * f
        P_sw_off = k * V_ds * Ids_off * (times['t6'] + times['t7']) * f
        P_coss = 0.5 * Coss * V_ds ** 2 * f        # hard-switching Coss loss

    P_gate = Qg * Vgs * f
    P_total = P_cond + P_sw_on + P_sw_off + P_coss + P_gate
    return dict(P_cond=P_cond, P_sw_on=P_sw_on, P_sw_off=P_sw_off,
                P_coss=P_coss, P_gate=P_gate, P_total=P_total,
                Ptr=P_sw_on, Ptf=P_sw_off, gate=gate,
                t1=times['t1'], t2=times['t2'], t3=times['t3'],
                t6=times['t6'], t7=times['t7'], t8=times['t8'])


def diode_loss(op, dev, di_stress=None, current=None, curve_key='diode_curve'):
    """Diode rectifier loss (conduction + reverse recovery)."""
    f = op['f_sw']
    d = di_stress or device_stress(op)['diode']
    V_r = d['V_max']
    Vf = dev['Vf_diode']
    Qrr = dev.get('Qrr', 0.0)

    I_avg, I_rms = d['I_avg'], d['I_rms']
    from diode_curves import conduction
    if current is None and dev.get(curve_key):
        from waveforms import make_waveforms
        current=make_waveforms(op)['i_free' if curve_key=='freewheel_curve' else 'i_d']
    details=conduction([I_avg] if current is None else current,dev.get(curve_key),Vf,average=I_avg)
    P_cond=details['P_cond']
    P_rr = Qrr * V_r * f if Qrr and Qrr > 0 else 0.0
    return dict(details,sr=False,P_rr=P_rr,P_total=P_cond+P_rr)


def semiconductor_losses(op, dev, n_switches=1, n_diodes=1, wf=None):
    """Total semiconductor loss (switch + rectifier, per topology)."""
    stress = device_stress(op)
    sw = mosfet_loss(op, dev, stress['switch'])
    if wf is None and (dev.get('diode_curve') or dev.get('freewheel_curve')):
        from waveforms import make_waveforms
        wf=make_waveforms(op)
    di = diode_loss(op, dev, stress['diode'],None if wf is None else wf['i_d'])
    total = n_switches * sw['P_total'] + n_diodes * di['P_total']
    if op['topology'] == 'ACF-FORWARD':
        free = diode_loss(op, dev, stress['freewheel'],None if wf is None else wf['i_free'],'freewheel_curve')
        # Auxiliary switch uses separate Rds/Qg/Coss. Conduction, drive and
        # conservative unrecovered Coss included; no automatic ZVS credit.
        aux = dict(P_cond=dev.get('Rds_aux', .1)*op['I_aux_rms']**2,
                   P_gate=dev.get('Qg_aux', 10e-9)*dev['Vgs']*op['f_sw'],
                   P_coss=.5*dev.get('Coss_aux',200e-12)*op['V_sw_max']**2*op['f_sw'])
        aux['P_total'] = sum(aux.values())
        total += aux['P_total'] + free['P_total']
        return dict(switch=sw, diode=di, auxiliary=aux, freewheel=free,
                    n_switches=2, n_diodes=2, P_total=total)
    return dict(switch=sw, diode=di, n_switches=n_switches,
                n_diodes=n_diodes, P_total=total)
