"""Plot already-validated artifacts; no simulator run or uniform-sample stats."""
from pathlib import Path
import json
import sys
ROOT=Path(__file__).resolve().parents[1]
sys.path[:0]=[str(ROOT),str(ROOT/'tests')]
from runtime_resources import configure_numeric_threads
configure_numeric_threads()
import numpy as np
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
from spice_result_helpers import real_forward_raw


def cycle_mean(records,names,node,period=4e-6):
    # LTspice may mark compression breakpoints by a negative stored time.
    time=np.abs(records['time'])
    voltage=records['values'][:,names[node]]
    integral=np.empty(len(time));integral[0]=0.
    np.cumsum((voltage[:-1]+voltage[1:])*.5*np.diff(time),out=integral[1:])
    bounds=np.arange(0,time[-1]+period*.1,period)
    area=np.interp(bounds,time,integral)
    return (bounds[:-1]+bounds[1:])/2, np.diff(area)/period


def plot():
    folder=ROOT/'artifacts/qa/flyback-spice'
    data=json.loads((folder/'results.json').read_text(encoding='utf-8'))
    plt.rcParams.update({'font.sans-serif':['Microsoft YaHei','DejaVu Sans'],'axes.unicode_minus':False})
    fig,axes=plt.subplots(2,2,figsize=(13,7.5),layout='constrained')
    for case in data['cases']:
        if case['name']=='multi':continue
        records,names=real_forward_raw(case['raw'])
        time,voltage=cycle_mean(records,names,'v(out1)')
        time=time*1000
        label=('默认 Vin=30 V' if case['name']=='nominal' else f"Vin={case['assignments']['VIN']} V")
        axes[0,0].plot(time,voltage,label=label,lw=1.2)
        mask=time>7.8
        axes[0,1].plot(time[mask],voltage[mask],label=label,lw=1)
        del records
    case=next(x for x in data['cases'] if x['name']=='multi')
    records,names=real_forward_raw(case['raw'])
    for i in range(1,4):
        time,voltage=cycle_mean(records,names,f'v(out{i})')
        axes[1,0].plot(time*1000,voltage,label=f'OUT{i}')
    absolute_time=np.abs(records['time'])
    lo,hi=np.searchsorted(absolute_time,[.00794,.00796])
    stride=max(1,(hi-lo)//2000)
    times=(absolute_time[lo:hi:stride]-.00794)*1e6
    for name,label in [('i(lp)','原边电流'),('i(ls1)','OUT1 绕组'),('i(ls2)','OUT2 绕组'),('i(ls3)','OUT3 绕组')]:
        axes[1,1].plot(times,records['values'][lo:hi:stride,names[name]],label=label,lw=1)
    titles=['单路：启动与双输入工况（周期平均）','单路：8 ms 减载后的恢复（周期平均）','三路：仅 OUT1 主反馈（周期平均）','三路：阶跃前绕组电流（5 个周期）']
    for ax,title in zip(axes.flat,titles):
        ax.set_title(title,loc='left',fontweight='bold');ax.grid(alpha=.2);ax.legend(fontsize=8)
        ax.set_xlabel('时间 / ms' if ax is not axes[1,1] else '时间 / μs')
        ax.set_ylabel('电压 / V' if ax is not axes[1,1] else '电流 / A')
    axes[0,1].set_ylim(29.8,30.25)
    fig.suptitle('GenericFlybackPWM 1.0 · LTspice 实际瞬态验证\n快速设置：不含电容 ESL，等效结电容假设 20 pF；不用于高频应力签核',fontsize=13)
    fig.savefig(folder/'closed-loop-validation.png',dpi=150)
    plt.close(fig)


if __name__=='__main__':plot()
