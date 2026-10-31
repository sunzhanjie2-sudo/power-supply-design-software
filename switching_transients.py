"""Q1 gate-charge voltage sketches, sharing the loss engine's six times.

These are reconstructed piecewise waveforms, not a parasitic transient solver.
t4/t5 are display-only estimates; the switching-loss ledger is never changed.
Reference for the four turn-on/off stages: TI SLUA618A, sections 2.5 / 2.6.
https://www.ti.com/lit/ug/slua618a/slua618a.pdf
"""
import math

import numpy as np


STAGE_NAMES = {
    't1': '开通延迟', 't2': '电流上升', 't3': '开通米勒', 't4': '栅极续充',
    't5': '关断延迟', 't6': '关断米勒', 't7': '电流下降', 't8': '栅极放电',
}
COLORS = ('#dbeafe', '#dcfce7', '#ffedd5', '#ede9fe')


def switching_voltage_data(op, p, switch_loss):
    """Return t1..t8 in SI and normalized voltage samples per time segment.

    The six spreadsheet durations are copied verbatim from mosfet_loss.
    Qpost = Qg-Qgs-Qgd gives a constant-capacitance approximation above the
    plateau: t4=3*Ron*Qpost/(Vdrv-Vgp_on),
    t5=Roff*Qpost/(Vdrv-Vgp_off)*ln(Vdrv/Vgp_off).
    Missing/inconsistent post-plateau charge leaves these estimates unknown.
    """
    vdrv, vth = p['Vgs'], p['Vth']
    from mos_gate import operating_gate
    gate = switch_loss.get('gate') or operating_gate(op, p)
    von, voff = gate['Vgp_on'], gate['Vgp_off']
    ron = p['Rg_drive'] + p['Rs_on'] + p['Rg']
    roff = p['Rg_drive'] + p['Rs_off'] + p['Rg']
    times = {k: float(switch_loss[k]) for k in ('t1', 't2', 't3', 't6', 't7', 't8')}
    qpost_on = gate.get('Qg_on',p['Qg']) - gate['Qgs_on'] - gate.get('Qgd_on',p['Qgd'])
    qpost_off = gate.get('Qg_off',p['Qg']) - gate['Qgs_off'] - gate.get('Qgd_off',p['Qgd'])
    times['t4'] = times['t5'] = None
    notes = ['t1/t2/t3/t6/t7/t8 与损耗计算一致；t4/t5* 为补充估算，不计入交叠损耗。',
             '分段重建，不含寄生振铃；t4/t8 取 3RC，终点并非严格达到驱动电压 / 0 V。']
    notes.extend(gate['notes'])
    if qpost_on > 0 and 0 < von < vdrv:
        times['t4'] = 3 * ron * qpost_on / (vdrv - von)
    if qpost_off > 0 and 0 < voff < vdrv:
        times['t5'] = roff * qpost_off / (vdrv - voff) * math.log(vdrv / voff)
    if times['t4'] is None or times['t5'] is None:
        notes.append('Qg≤Qgs+Qgd 或关断平台不低于驱动电压：t4/t5 时长未知，仅显示阶段形状。')
    if op['topology'] in ('QR-FLYBACK', 'ACF-FORWARD'):
        notes.append('QR / 有源钳位图为栅电荷参考过程，不代表实际谷底或 ZVS 换流。')
    # The loss ledger may conservatively use the stress limit.  A gate event
    # must instead distinguish the off-state plateau from the brief leakage
    # clamp peak; the spike is not a fictitious high voltage at turn-on.
    vhigh = float(op['V_sw_max'])
    clamp = op.get('clamp')
    vplateau = float(clamp['V_plateau']) if clamp else vhigh
    if clamp:
        vhigh = max(float(clamp['V_peak']), vplateau)
        notes.extend(clamp['notes'])
    ion, ioff = gate['I_on'], gate['I_off']
    vlow_on = min(vhigh, p['Rds_on'] * ion)
    vlow_off = min(vhigh, p['Rds_on'] * ioff)
    u = np.linspace(0., 1., 65)

    def charge(a, b):
        # Reconstructed RC-shaped curve constrained to the stage endpoints.
        if a == b:
            return np.full_like(u, a)
        r = math.log((vdrv - a) / (vdrv - b))
        return a + (b - a) * (-np.expm1(-r*u)) / (-math.expm1(-r))

    def discharge(a, b):
        return a * np.exp(-math.log(a/b)*u)

    on_vg = [charge(0., vth), charge(vth, von), np.full_like(u, von),
             vdrv - (vdrv-von)*np.exp(-3*u)]
    off_vg = [discharge(vdrv, voff), np.full_like(u, voff),
              discharge(voff, vth), vth*np.exp(-3*u)]
    on_vd = [np.full_like(u, vplateau), np.full_like(u, vplateau),
             vplateau+(vlow_on-vplateau)*u, np.full_like(u, vlow_on)]
    off_vd = [np.full_like(u, vlow_off), vlow_off+(vplateau-vlow_off)*u,
              np.full_like(u, vplateau), np.full_like(u, vplateau)]

    def event(keys, vg, vd):
        return [dict(key=k, name=STAGE_NAMES[k], duration=times[k], u=u,
                     vgs=g, vds=d, estimated=k in ('t4', 't5'))
                for k, g, d in zip(keys, vg, vd)]

    on_stages = event(('t1', 't2', 't3', 't4'), on_vg, on_vd)
    off_stages = event(('t5', 't6', 't7', 't8'), off_vg, off_vd) if voff < vdrv else None
    tail = None
    if clamp and off_stages is not None:
        from flyback_clamp import leakage_pulse
        coupled = op.get('coupled_solution')
        if coupled is None:
            pulse_end = float(clamp.get('t_pulse') or 0.)
            landmarks = [float(clamp.get('t_rise') or 0.), pulse_end]

            def voltage_after_miller(elapsed):
                return vplateau + leakage_pulse(elapsed, clamp)
        else:
            # The coupled solver has an ideal instantaneous clamp edge.  Its
            # measured dwell and peak take precedence over the LC sketch.
            tt = np.asarray(coupled['t'], dtype=float)
            vv = np.asarray(coupled['v_sw'], dtype=float)
            ic = np.asarray(coupled.get('i_clamp', np.zeros_like(tt)), dtype=float)
            origin = float(op['D'])*float(op['Ts'])
            active = (tt >= origin) & (ic > max(float(np.max(ic))*1e-6, 1e-12))
            if np.any(active):
                last_index = int(np.flatnonzero(active)[-1])
                pulse_end = float(tt[min(last_index+1,len(tt)-1)]-origin)
            else:
                pulse_end = 0.
            landmarks = [pulse_end]

            def voltage_after_miller(elapsed):
                return np.interp(origin+np.asarray(elapsed), tt, vv)

            off_stages[1]['vds'] = vlow_off+(float(voltage_after_miller(0.))-vlow_off)*u
            notes.append('矩阵模型钳位沿为理想跳变：关断平台后的电压取实际周期样本，不额外叠加漏感尖峰。')

        elapsed = 0.
        for index, key in ((2, 't7'), (3, 't8')):
            duration = times[key]
            # Include exact physical landmarks, even when a sub-ns rise is
            # shorter than 1/64 of a gate stage; otherwise the peak vanishes.
            extra = [(point-elapsed)/duration for point in landmarks
                     if duration > 0. and elapsed < point < elapsed+duration]
            stage_u = np.unique(np.r_[u, extra,
                [np.nextafter(x, 0.) for x in extra]])
            off_stages[index]['u'] = stage_u
            off_stages[index]['vds'] = voltage_after_miller(elapsed+stage_u*duration)
            off_stages[index]['vgs'] = (voff*np.exp(-math.log(voff/vth)*stage_u)
                                       if key == 't7' else vth*np.exp(-3*stage_u))
            elapsed += duration
        if pulse_end > elapsed:
            # Do not stretch t7/t8 to fit the clamp.  The reset tail is a
            # separate physical interval, not another gate-charge stage.
            tail_duration = pulse_end-elapsed
            tail_u = np.unique(np.r_[u, np.nextafter(1., 0.)])
            tail = dict(duration=tail_duration, u=tail_u,
                        vds=voltage_after_miller(elapsed+tail_u*tail_duration),
                        vgs=np.full_like(tail_u, vth*math.exp(-3.)))
            if coupled is None:
                tail['vds'][-1] = vplateau
            notes.append(f'漏感钳位恢复延续至 t8 后约 {tail_duration*1e9:.3g} ns；不改变 t1–t8。')

    return dict(times=times, notes=notes, vdrv=vdrv, vth=vth, vhigh=vhigh,
                vplateau=vplateau, clamp=clamp, off_tail=tail, gate=gate,
                on=on_stages, off=off_stages)


def draw_switching_event(ax, data, event, *, real_time=False, drain_ax=None):
    """Draw a dual-voltage chart; by default unfold stages for readability."""
    from matplotlib.ticker import MaxNLocator
    ax.clear()
    drain = drain_ax if drain_ax is not None else ax.twinx()
    drain.clear()
    drain.patch.set_visible(False)
    # clear() resets YAxis label placement even for a pre-existing twinx axis.
    drain.yaxis.set_label_position('right')
    drain.yaxis.tick_right()
    stages = data[event]
    if stages is None:
        ax.set_title('Q1 MOS 关断 · 无法重建', fontsize=10)
        ax.text(.5, .5, '关断平台电压必须低于驱动电压\n请核对 Vgp_off / Vgs',
                transform=ax.transAxes, ha='center', fontsize=9)
        ax.set_xticks([]); ax.set_yticks([]); drain.set_yticks([])
        return drain
    physical = real_time and all(s['duration'] is not None for s in stages)
    x0 = 0.
    centers, labels, boundaries = [], [], [0.]
    for i, s in enumerate(stages):
        width = s['duration']*1e9 if physical else 1.
        x = x0 + s['u']*width
        ax.axvspan(x0, x0+width, color=COLORS[i], alpha=.65, zorder=0)
        ax.plot(x, s['vgs'], color='#1558b0', lw=1.8)
        drain.plot(x, s['vds'], color='#c65d12', lw=1.8)
        centers.append(x0+width/2)
        duration = '未知' if s['duration'] is None else f"{s['duration']*1e9:.3g} ns"
        labels.append(s['key']+('*' if s['estimated'] else '')+'\n'+duration)
        x0 += width
        boundaries.append(x0)
    for x in boundaries[1:-1]:
        ax.axvline(x, color='#8695a5', ls=':', lw=.7)
    tail = data.get('off_tail') if event == 'off' else None
    if tail:
        width = tail['duration']*1e9 if physical else 1.
        x = x0+tail['u']*width
        ax.axvspan(x0, x0+width, color='#f1f5f9', alpha=.8, zorder=0)
        ax.plot(x, tail['vgs'], color='#1558b0', lw=1.8)
        drain.plot(x, tail['vds'], color='#c65d12', lw=1.8)
        ax.axvline(x0, color='#8695a5', ls=':', lw=.7)
        centers.append(x0+width/2)
        labels.append('钳位恢复\n'+f"{tail['duration']*1e9:.3g} ns")
        x0 += width
    ax.set_xlim(-max(x0, 1.)*.015, max(x0, 1.)*1.015)
    ax.set_ylim(0., data['vdrv']*1.12)
    drain.set_ylim(0., max(data['vhigh'], 1.)*1.12)
    ax.set_ylabel('Vgs / V', color='#1558b0', fontsize=8)
    drain.set_ylabel('Vds / V', color='#c65d12', fontsize=8)
    ax.tick_params(axis='y', colors='#1558b0', labelsize=7)
    drain.tick_params(axis='y', colors='#c65d12', labelsize=7)
    ax.yaxis.set_major_locator(MaxNLocator(4))
    drain.yaxis.set_major_locator(MaxNLocator(4))
    drain.grid(False)
    gate = data.get('gate')
    suffix = (f" · Id={gate['I_'+event]:.3g}A  Vgp={gate['Vgp_'+event]:.3g}V" if gate else '')
    ax.set_title('Q1 MOS '+('开通' if event == 'on' else '关断')+suffix, fontsize=10, pad=8)
    if physical:
        ax.set_title(ax.get_title(), fontsize=10, pad=33)
        ax.xaxis.set_major_locator(MaxNLocator(4))
        ax.tick_params(axis='x', labelsize=7)
        ax.set_xlabel('时间 / ns（* 补充估算）', fontsize=8)
        # Place phase labels in a fixed-width header: very short phases must
        # not collide merely because a neighbouring RC tail is much longer.
        for i, label in enumerate(labels):
            ax.text((i+.5)/len(labels), 1.035, label, transform=ax.transAxes,
                    ha='center', va='bottom', fontsize=7, clip_on=False,
                    bbox=dict(facecolor=COLORS[i] if i < 4 else '#f1f5f9',
                              edgecolor='none', pad=1.5))
    else:
        ax.set_xticks(centers, labels, fontsize=7)
        ax.set_xlabel('阶段展开（非等时长；* 补充估算）', fontsize=8)
    ax.grid(axis='y', alpha=.45)
    return drain
