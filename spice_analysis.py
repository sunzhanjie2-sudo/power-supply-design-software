"""Time-weighted transient checks and complex FRA data, independent of the UI."""
import math
import re
from pathlib import Path
import numpy as np


def protection_stop(raw, measured, frequency):
    """Capture the first observed FAULT latch and its immediately preceding cycle."""
    if measured.get('fault_max', 0) < .5 or 'v(fault)' not in raw.names:
        return None
    fault = raw.trace('v(fault)')
    for first in range(0, len(fault), 250_000):
        high = np.flatnonzero(fault[first:first+250_000] >= .5)
        if high.size:
            index = first + int(high[0])
            break
    else:
        return None
    when = float(raw.time[index])
    begin = int(np.searchsorted(raw.time, when - 1 / frequency))
    sample = slice(begin, index + 1)
    def maximum(name):
        if name in raw.names:
            return float(np.max(raw.trace(name)[sample]))
    scp = maximum('v(xu_ctrl:xsuper:scp)')
    olp = maximum('v(xu_ctrl:olpt)')
    qr_trip = maximum('v(xu_ctrl:trip)')
    causes = []
    if scp is not None and scp >= .5:
        causes.append('SCP 短路比较器')
    if olp is not None and olp >= 1:
        causes.append('OLP 过载计时器')
    if qr_trip is not None and qr_trip >= .5:
        causes.append('QR 异常 CS 锁存')
    filtered_cs = maximum('v(xu_ctrl:filtered)') if qr_trip is not None else maximum('v(xu_ctrl:cs_filtered)')
    return dict(first_trip_s=when, cause='、'.join(causes) or '保护已动作，具体比较器待核对',
                filtered_cs_peak_v=filtered_cs,
                primary_peak_a=maximum('i(lp)'), fault_max=measured['fault_max'])


def steady_quality(raw,frequency,end,outputs,*,window=.008,bins=16):
    """Reject slow startup/oscillation hidden by two short equal-mean windows.

    Each bin is time-weighted, so adaptive SPICE sampling does not bias the
    trend. This tests pre-step stationarity, not output-voltage compliance.
    """
    finish=float(end)-10/float(frequency);start=finish-window
    if start<raw.time[0]:return dict(passed=False,reason='阶跃前数据不足完整稳态观察窗口',window_s=window)
    edges=np.linspace(start,finish,bins+1);means=[]
    for j in range(1,outputs+1):
        y=raw.trace(f'v(out{j})');values=[]
        for a,b in zip(edges[:-1],edges[1:]):
            first,last=np.searchsorted(raw.time,[a,b]);t=np.r_[a,raw.time[first:last],b]
            v=np.r_[np.interp(a,raw.time[max(0,first-1):first+1],y[max(0,first-1):first+1]),y[first:last],np.interp(b,raw.time[max(0,last-1):last+1],y[max(0,last-1):last+1])]
            values.append(float(np.trapezoid(v,t)/(b-a)))
        means.append(values)
    means=np.asarray(means);scale=np.maximum(abs(np.mean(means[:,-bins//2:],axis=1)),.01)
    drift=100*abs(np.mean(means[:,:bins//2],axis=1)-np.mean(means[:,bins//2:],axis=1))/scale
    span=100*np.ptp(means,axis=1)/scale
    passed=bool(np.max(drift)<=.25 and np.max(span)<=1. and np.all(means>0))
    return dict(passed=passed,reason='阶跃前长窗口均值/摆幅通过' if passed else '阶跃前仍有低频摆动或漂移',
        window_s=window,bin_edges_s=edges.tolist(),mean_v=means.tolist(),drift_percent=drift.tolist(),span_percent=span.tolist(),
        drift_limit_percent=.25,span_limit_percent=1.,scope='阶跃前稳态检查，不是启动过冲或器件安全验收')


def window(time,values,start,end):
    a,b=np.searchsorted(time,[start,end]);axis=np.r_[start,time[a:b],end]
    return axis,np.r_[np.interp(start,time,values),values[a:b],np.interp(end,time,values)]


def statistics(time,values,start,end):
    axis,values=window(time,values,start,end);span=end-start
    mean=float(np.trapezoid(values,axis)/span)
    square=float(np.trapezoid(values*values,axis)/span)
    return dict(mean=mean,rms=math.sqrt(max(0,square)),ac_rms=math.sqrt(max(0,square-mean*mean)),
        minimum=float(np.min(values)),maximum=float(np.max(values)),pp=float(np.ptp(values)))


def cycle_quality(raw,frequency,start,end,gate_voltage=10,cycles=64,tolerance_pct=5):
    """Check each clock period, rather than only slowly varying output DC."""
    ts=1/frequency;last=int(math.floor(end/ts));first=max(int(math.ceil(start/ts)),last-cycles)
    if last-first<8:return dict(stable=False,reason='周期数不足',cycles=[])
    lo,hi=np.searchsorted(raw.time,[first*ts,last*ts]);t=raw.time[lo:hi]
    gate=raw.trace('v(gate)')[lo:hi]-raw.trace('v(sense)')[lo:hi]
    current=raw.trace('i(lp)')[lo:hi]
    indices=np.flatnonzero(np.diff((gate>gate_voltage/2).astype(np.int8)))
    edges=t[indices]+(gate_voltage/2-gate[indices])*(t[indices+1]-t[indices])/(gate[indices+1]-gate[indices])
    levels=gate[indices+1]>gate_voltage/2
    rows=[]
    for number in range(first,last):
        begin,finish=number*ts,(number+1)*ts
        inside=(edges>=begin)&(edges<finish);edge_times=edges[inside]
        boundaries=np.r_[begin,edge_times,finish]
        high=np.interp((boundaries[:-1]+boundaries[1:])/2,t,gate)>gate_voltage/2
        duty=float(np.sum(np.diff(boundaries)[high])/ts)
        a,b=np.searchsorted(t,[begin,finish]);values=current[a:b]
        rises=edge_times[levels[inside]]
        rows.append(dict(clock=number,duty=duty,peak=float(max(values,default=0)),
            pulses=len(rises),gate_rise_s=float(rises[0]) if len(rises)==1 else None))
    duty=np.array([x['duty'] for x in rows]);peak=np.array([x['peak'] for x in rows])
    def spread(x):return float(np.ptp(x)/max(abs(float(np.mean(x))),1e-9))
    alternation=float(abs(np.mean(duty[::2])-np.mean(duty[1::2]))/max(float(np.mean(duty)),1e-9))
    lag1=float(np.sqrt(np.mean(np.diff(duty)**2)));lag2=float(np.sqrt(np.mean((duty[2:]-duty[:-2])**2)))
    doubled=alternation>.05 and lag1>.01 and lag2<lag1*.6
    missing=bool(np.any(duty<.005));multiple=any(x['pulses']>1 for x in rows)
    stable=spread(duty)<tolerance_pct/100 and spread(peak)<tolerance_pct/100 and not missing and not multiple
    return dict(stable=stable,reason='周期二大小波' if doubled else '跳周期或停脉冲' if missing else
        '周期内多次开关' if multiple else '周期波动超限' if not stable else '逐周期重复性通过',
        duty_min=float(min(duty)),duty_max=float(max(duty)),duty_span_percent=100*spread(duty),
        peak_span_percent=100*spread(peak),alternation_percent=100*alternation,cycles=rows)


class FrequencyRaw:
    """Small LTspice complex forward RAW from native FRA, never transient AC."""
    def __init__(self,path):
        data=Path(path).read_bytes();encoding='utf-16-le' if data.startswith(b'T\x00') else 'utf-8'
        marker='Binary:\n'.encode(encoding);at=data.find(marker)
        if at<0:raise ValueError('FRA RAW 缺少二进制数据')
        header=data[:at].decode(encoding);flags=re.search(r'^Flags:\s*(.*)',header,re.M)[1]
        if 'complex' not in flags or 'fastaccess' in flags.lower():raise ValueError('FRA RAW 不是普通复数频域数据')
        count=int(re.search(r'No\. Variables:\s*(\d+)',header)[1]);points=int(re.search(r'No\. Points:\s*(\d+)',header)[1])
        if not 2<=points<=10000 or not 2<=count<=100:raise ValueError('FRA 数据量或频点数无效')
        names=[m[1].lower() for m in re.finditer(r'^\s*\d+\s+(\S+)\s+\S+\s*$',header.rsplit('Variables:',1)[1],re.M)]
        body=data[at+len(marker):]
        if len(body)!=16*count*points or len(names)!=count:raise ValueError('FRA RAW 不完整')
        values=np.frombuffer(body,dtype='<c16').reshape(points,count)
        self.frequency=values[:,0].real;self.traces={name:values[:,i] for i,name in enumerate(names) if i}
        if np.any(np.diff(self.frequency)<=0) or not np.all(np.isfinite(values)):raise ValueError('FRA 频点非递增或含无效数值')


def loop_metrics(frequency,gain):
    f=np.asarray(frequency);gain=np.asarray(gain)
    db=20*np.log10(np.maximum(np.abs(gain),1e-30));phase=np.degrees(np.unwrap(np.angle(gain)))
    if phase[0]>90:phase-=360
    crosses=[];margins=[]
    for i in np.flatnonzero(db[:-1]*db[1:]<=0):
        if db[i]==db[i+1]:continue
        k=-db[i]/(db[i+1]-db[i]);fc=10**(np.log10(f[i])+k*np.log10(f[i+1]/f[i]))
        crosses.append(dict(fc=float(fc),pm=float(180+phase[i]+k*(phase[i+1]-phase[i])),direction='down' if db[i+1]<db[i] else 'up'))
    for turn in range(int(math.floor((min(phase)+180)/360))-1,int(math.ceil((max(phase)+180)/360))+1):
        delta=phase-(-180+turn*360)
        for i in np.flatnonzero(delta[:-1]*delta[1:]<0):
            k=-delta[i]/(delta[i+1]-delta[i]);margins.append(float(-(db[i]+k*(db[i+1]-db[i]))))
    down=[c for c in crosses if c['direction']=='down'];selected=min(down,key=lambda c:c['pm']) if down else None
    return dict(f=f.tolist(),db=db.tolist(),phase=phase.tolist(),crossings=crosses,
        fc=selected['fc'] if selected else None,pm=selected['pm'] if selected else None,
        gm_db=min(margins) if margins else None,gm_scope='仅测得频带；无相位交越不等于无限裕度')
