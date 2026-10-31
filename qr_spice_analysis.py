"""Gate-edge based statistics: a variable-frequency QR has no clock bins."""
import numpy as np


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
        # Measure immediately before switching, excluding the switch-driven drop.
        before=max(start,a-50e-9);v_before=float(np.interp(before,t,vds))
        tail=np.searchsorted(t,max(f,b-.8/frequency));local=vds[tail:k]
        rows.append(dict(clock=number,start_s=float(a),end_s=float(b),ton_s=f-a,period_s=float(b-a),
            frequency_hz=float(1/(b-a)),duty=float((f-a)/(b-a)),peak=float(max(current[i:j],default=0)),pulses=1,
            turnon_vds_v=v_before,valley_vds_v=float(min(local,default=v_before))))
    empty=dict(stable=False,reason='QR 门极有效周期不足',cycles=rows,duty_min=0.,duty_max=0.,
        duty_span_percent=0.,peak_span_percent=0.,alternation_percent=0.)
    if len(rows)<8:return empty
    duty=np.array([r['duty'] for r in rows]);peak=np.array([r['peak'] for r in rows]);freq=np.array([r['frequency_hz'] for r in rows])
    def spread(x):return float(np.ptp(x)/max(abs(float(np.mean(x))),1e-9)*100)
    alternation=float(abs(np.mean(peak[::2])-np.mean(peak[1::2]))/max(float(np.mean(peak)),1e-9)*100)
    # Regular valley skipping is valid nonlinear operation, but not a single-
    # periodic linearisation point for FRA. Report it without a stability claim.
    repeat=max(spread(duty),spread(peak),spread(freq))<tolerance_pct
    return dict(stable=repeat,reason='QR 实际边沿逐周期重复性通过' if repeat else 'QR 变频／跳谷或周期波动，需复核',
        cycles=rows,duty_min=float(min(duty)),duty_max=float(max(duty)),duty_span_percent=spread(duty),
        peak_span_percent=spread(peak),alternation_percent=alternation,
        frequency_mean_hz=float(len(rows)/sum(r['period_s'] for r in rows)),frequency_min_hz=float(min(freq)),
        frequency_max_hz=float(max(freq)),turnon_vds_mean_v=float(np.mean([r['turnon_vds_v'] for r in rows])),
        valley_vds_mean_v=float(np.mean([r['valley_vds_v'] for r in rows])),
        note='QR 周期取实际门极上升沿；变频或跳谷并不直接等于环路不稳定。')
