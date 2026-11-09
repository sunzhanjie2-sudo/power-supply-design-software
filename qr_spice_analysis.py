"""Gate-edge based statistics: a variable-frequency QR has no clock bins."""
import numpy as np


def startup_gate_current(raw, step_s, gate_voltage, *, output_count=1, feedback_output=1):
    """Maximum observed winding current 50 ns before a resolved startup turn-on.

    Both interpolation intervals must be at most 100 ns and the measured gate
    must still be low. Stream the adaptive RAW in blocks. This diagnostic is
    independent of the post-startup periodicity and FRA acceptance checks.
    """
    offset = 50e-9
    time = raw.time
    end = min(float(time[-1]), step_s)
    stop = int(np.searchsorted(time, end, side='right'))
    chunk = 65536
    if not 1<=feedback_output<=output_count<=6:
        raise ValueError('QR开通检查的输出路数/反馈编号无效')
    info = dict(available=False, offset_s=offset, end_s=end, total_edges=0, observed_edges=0,
                feedback_output=feedback_output, windings={})
    try:
        drain, sense = raw.trace('v(drain)'), raw.trace('v(sense)')
    except KeyError:
        drain = None
    if drain is not None:
        peak_v = -np.inf
        for first in range(0, len(time), chunk):
            vds = np.subtract(drain[first:first+chunk], sense[first:first+chunk], dtype=float)
            if not np.isfinite(vds).all():
                break
            peak = int(np.argmax(vds))
            if vds[peak] > peak_v:
                peak_v, peak_t = float(vds[peak]), float(time[first+peak])
        else:
            info.update(vds_peak_full_v=peak_v, vds_peak_full_s=peak_t)
    try:
        softstart = raw.trace('v(ss)')
        gate, sense = raw.trace('v(gate)'), raw.trace('v(sense)')
    except KeyError as exc:
        info['reason'] = '启动开通检查缺少探针 '+str(exc)
        return info
    windings={}
    for index in range(1,output_count+1):
        row=info['windings'][f'OUT{index}']=dict(available=False)
        try:windings[index]=raw.trace(f'i(ls{index})')
        except KeyError:row['reason']=f'缺少副边电流探针 i(ls{index})'
    for first in range(0, stop, chunk):
        full = np.flatnonzero(softstart[first:min(first+chunk, stop)] >= .999)
        if full.size:
            stop = first + int(full[0]) + 1
            end = float(time[stop-1])
            break
    info['end_s'] = end
    threshold = gate_voltage / 2
    for first in range(1, stop, chunk):
        last = min(first + chunk, stop)
        vgs = gate[first-1:last] - sense[first-1:last]
        local = np.flatnonzero((vgs[:-1] < threshold) & (vgs[1:] >= threshold))
        info['total_edges'] += int(local.size)
        if not local.size:
            continue
        left = first - 1 + local
        rise_gap = time[left+1] - time[left]
        edges = time[left] + rise_gap * (threshold-vgs[local])/(vgs[local+1]-vgs[local])
        probe = edges - offset
        right = np.clip(np.searchsorted(time, probe, side='right'), 1, len(time)-1)
        gap = time[right] - time[right-1]
        weight = np.divide(probe-time[right-1], gap, out=np.zeros_like(gap), where=gap>0)
        g0 = gate[right-1] - sense[right-1]
        vgs_pre = g0 + weight*(gate[right]-sense[right]-g0)
        resolved = ((rise_gap <= 2*offset) & (gap > 0) & (gap <= 2*offset)
                    & (probe >= time[0]) & (vgs_pre < .1*gate_voltage))
        info['observed_edges'] += int(np.count_nonzero(resolved))
        if not resolved.any():
            continue
        for index,winding in windings.items():
            row=info['windings'][f'OUT{index}']
            i0 = winding[right-1]
            current = (i0 + weight*(winding[right]-i0))[resolved]
            peak = int(np.argmax(current))
            if not row['available'] or current[peak] > row['max_pre_current_a']:
                row.update(available=True,max_pre_current_a=float(current[peak]),
                           max_gate_rise_s=float(edges[resolved][peak]))
                if index==feedback_output:
                    info.update(available=True,max_pre_current_a=row['max_pre_current_a'],
                                max_gate_rise_s=row['max_gate_rise_s'])
    info['all_windings_observed']=all(r['available'] for r in info['windings'].values())
    if not info['available']:
        info['reason'] = '启动窗内未取得可分辨的开通前副边电流'
    return info


def cycle_quality(raw,frequency,start,end,gate_voltage=10,cycles=64,tolerance_pct=5):
    lo,hi=np.searchsorted(raw.time,[start,end]);t=raw.time[lo:hi]
    gate=raw.trace('v(gate)')[lo:hi]-raw.trace('v(sense)')[lo:hi]
    current=raw.trace('i(lp)')[lo:hi]
    vds=raw.trace('v(drain)')[lo:hi]-raw.trace('v(sense)')[lo:hi]
    indices=np.flatnonzero(np.diff((gate>gate_voltage/2).astype(np.int8)))
    edges=t[indices]+(gate_voltage/2-gate[indices])*(t[indices+1]-t[indices])/(gate[indices+1]-gate[indices])
    rising=edges[gate[indices+1]>gate_voltage/2];falling=edges[gate[indices+1]<gate_voltage/2]
    rising=rising[-cycles-1:];rows=[]
    for number,(a,b) in enumerate(zip(rising[:-1],rising[1:])):
        fall=falling[(falling>a)&(falling<b)]
        if len(fall)!=1:continue
        f=float(fall[0]);i,j=np.searchsorted(t,[a,f]);k=np.searchsorted(t,b)
        # Both measurements refer to the next turn-on (b). A clock-based
        # window can include the previous turn-off, when Vds is still low.
        before=b-50e-9
        v_before=float(np.interp(before,t,vds)) if before>f else None
        tail=np.searchsorted(t,(f+b)/2)
        off_vds=vds[tail:k][gate[tail:k]<.1*gate_voltage]
        rows.append(dict(clock=number,start_s=float(a),end_s=float(b),ton_s=f-a,period_s=float(b-a),
            frequency_hz=float(1/(b-a)),duty=float((f-a)/(b-a)),peak=float(max(current[i:j],default=0)),pulses=1,
            turnon_vds_v=v_before,valley_vds_v=float(np.min(off_vds)) if off_vds.size else None))
    empty=dict(stable=False,reason='QR 门极有效周期不足',cycles=rows,duty_min=0.,duty_max=0.,
        duty_span_percent=0.,peak_span_percent=0.,alternation_percent=0.)
    if len(rows)<8:return empty
    duty=np.array([r['duty'] for r in rows]);peak=np.array([r['peak'] for r in rows]);freq=np.array([r['frequency_hz'] for r in rows])
    def spread(x):return float(np.ptp(x)/max(abs(float(np.mean(x))),1e-9)*100)
    alternation=float(abs(np.mean(peak[::2])-np.mean(peak[1::2]))/max(float(np.mean(peak)),1e-9)*100)
    # Regular valley skipping is valid nonlinear operation, but not a single-
    # periodic linearisation point for FRA. Report it without a stability claim.
    repeat=max(spread(duty),spread(peak),spread(freq))<tolerance_pct
    def observed_mean(key):
        values=[r[key] for r in rows if r[key] is not None]
        return float(np.mean(values)) if values else None
    return dict(stable=repeat,reason='QR 实际边沿逐周期重复性通过' if repeat else 'QR 变频／跳谷或周期波动，需复核',
        cycles=rows,duty_min=float(min(duty)),duty_max=float(max(duty)),duty_span_percent=spread(duty),
        peak_span_percent=spread(peak),alternation_percent=alternation,
        frequency_mean_hz=float(len(rows)/sum(r['period_s'] for r in rows)),frequency_min_hz=float(min(freq)),
        frequency_max_hz=float(max(freq)),turnon_vds_mean_v=observed_mean('turnon_vds_v'),
        valley_vds_mean_v=observed_mean('valley_vds_v'),valley_window='off_tail_gate_low',
        note='QR 周期取实际门极上升沿；变频或跳谷并不直接等于环路不稳定。')
