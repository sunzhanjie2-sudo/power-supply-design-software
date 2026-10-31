"""Prepare controlled LTspice startup experiments; preserve prior evidence."""
import argparse
import json
from pathlib import Path
import re
import sys

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))


def prepare(destination):
    source=ROOT/'artifacts/qa/acf/cross_20_b/retry_X002'
    destination.mkdir(parents=True,exist_ok=False)
    for path in source.iterdir():
        if path.suffix in ('.cir','.lib','.inc'):
            (destination/path.name).write_bytes(path.read_bytes())
    params=(destination/'design_params.inc').read_text(encoding='ascii')
    params=re.sub(r'(?m)^\.param TSTOP=.*$', '.param TSTOP=0.04',params)
    (destination/'design_params.inc').write_text(params,encoding='ascii')
    analysis='''.options threads=2 method=gear reltol=0.003 plotwinsize=300
.tran 0 40m 0 100n
.save V(out1) V(out2) V(out3) V(sgnd) V(comp) V(ss) V(fault) V(xu_ctrl:xmain:command) V(xu_ctrl:xmain:xcomp:integ)
.meas tran startup_main_peak MAX V(out1,sgnd) FROM 0 TO 0.04
.meas tran startup_out2_min MIN V(out2,sgnd) FROM 0.012 TO 0.04
.meas tran startup_out3_min MIN V(out3,sgnd) FROM 0.012 TO 0.04
.meas tran startup_fault MAX V(fault) FROM 0 TO 0.04
'''
    (destination/'analysis.inc').write_text(analysis,encoding='ascii')
    (destination/'experiment.json').write_text(json.dumps(dict(
        purpose='Fixed-load startup diagnosis, no dynamic load injection',
        source=str(source),voltage=20,powers=[2,1,2],
        variants=[dict(KP=100,TSS=.0047),dict(KP=300,TSS=.0047),dict(KP=100,TSS=.02)],
        note='Only KP or TSS changes. These variants are diagnostic, not new validated release presets.'
    ),indent=2),encoding='utf-8')
    print(destination)


def analyze(job_folder,destination):
    import hashlib
    from zipfile import ZipFile,ZIP_DEFLATED
    import numpy as np
    from matplotlib import pyplot as plt
    from spice_runtime import TransientRaw,read_log

    destination.mkdir(parents=True,exist_ok=True)
    job_folder=Path(job_folder)
    prefix=job_folder.name
    results=[]
    labels=['原参数：KP=100，SS=4.7 ms','仅增益：KP=300，SS=4.7 ms','仅软启动：KP=100，SS=20 ms']
    runs=[]
    for i,(kp,tss) in enumerate([(100,.0047),(300,.0047),(100,.02)]):
        stem=job_folder/f'{prefix}_case_{i}'
        values,log,errors,_=read_log(stem.with_suffix('.log'))
        expected=['startup_main_peak','startup_out2_min','startup_out3_min','startup_fault']
        if errors or any(k not in values for k in expected):
            raise RuntimeError(f'Incomplete native measurements for case {i}: {errors}')
        raw=TransientRaw(stem.with_suffix('.raw'))
        try:
            if abs(raw.time[-1]-.04)>1e-8:raise RuntimeError('Incomplete transient')
            signals=[f'v(out{j})' for j in range(1,4)]+['v(comp)','v(ss)','v(fault)','v(xu_ctrl:xmain:command)','v(xu_ctrl:xmain:xcomp:integ)']
            runs.append(raw.samples(signals,0,.04,4001))
        finally:raw.close()
        results.append(dict(label=labels[i],KP=kp,TSS=tss,measurements={k:values[k] for k in expected},
                            log_sha256=hashlib.sha256(stem.with_suffix('.log').read_bytes()).hexdigest()))

    # The archived 100 ms run is the user's screenshot, not a new load step.
    cold=ROOT/'artifacts/qa/acf/cross_20_b/retry_X002/Flyback.raw'
    raw=TransientRaw(cold)
    try:
        original=raw.samples([f'v(out{j})' for j in range(1,4)],0,.1,4001)
        means=[];duties=[]
        for ms in range(1,101):
            a,b=np.searchsorted(raw.time,[(ms-1)*.001,ms*.001]);t=raw.time[a:b]
            means.append([float(np.trapezoid(raw.trace(f'v(out{j})')[a:b],t)/(t[-1]-t[0])) for j in range(1,4)])
            gate=raw.trace('v(gate)')[a:b]-raw.trace('v(sense)')[a:b]
            duties.append(float(np.trapezoid((gate>5).astype(float),t)/(t[-1]-t[0])))
    finally:raw.close()
    means=np.asarray(means);reference=np.mean(means[-5:],axis=0)
    bad=np.any(abs(means-reference)/reference>.01,axis=1)
    settle=int(np.flatnonzero(bad)[-1]+1) if np.any(bad) else 0
    evidence=dict(voltage=20,powers=[2,1,2],load_step=False,short_test=False,
        native_measurements=results,original_100ms=dict(source=str(cold),reference_v=reference.tolist(),
        one_percent_settling_ms=settle,method='1 ms time-weighted means, all rails within 1% of 95–100 ms mean for rest of recorded run',
        bin_end_ms=list(range(1,101)),mean_v=means.tolist(),gate_on_fraction=duties),
        experimental_scope='Single 20 V light-feedback corner. KP=300 is a diagnosis, not a validated replacement for all corners or a hardware recommendation.')
    comparison=ROOT/'output/MP6005_三路有源钳位正激_20261028/仿真与设计计算对比报告.zip'
    with ZipFile(comparison) as z:nominal=json.loads(z.read('comparison.json'))
    evidence['nominal_step_checks']=[]
    for case in nominal['cases']:
        m=case['measurements']
        evidence['nominal_step_checks'].append(dict(voltage=case['voltage'],planned_step_ms=25,
            before_v=[m[f'out{i}_before'] for i in range(1,4)],
            adjacent_window_drift_pct=[100*abs(m[f'out{i}_before']-m[f'out{i}_earlier'])/abs(m[f'out{i}_before']) for i in range(1,4)],
            periodicity_passed=case['periodicity']['stable'],fault_max=m['fault_max']))
    (destination/'diagnosis.json').write_text(json.dumps(evidence,ensure_ascii=False,indent=2),encoding='utf-8')
    plt.rcParams.update({'font.sans-serif':['Microsoft YaHei','DejaVu Sans'],'axes.unicode_minus':False,'font.size':11})
    fig,ax=plt.subplots(2,1,figsize=(13,7),layout='constrained',sharex=True)
    for j in range(1,4):ax[0].plot(np.array(original['time'])*1000,original[f'v(out{j})'],label=f'OUT{j}')
    ax[0].set(title='原固定负载启动：20 V，2 / 1 / 2 W，全程无负载阶跃',ylabel='输出电压 / V')
    ax[0].axvline(settle,color='gray',ls='--',label=f'全路进入并保持 ±1%：约 {settle} ms')
    ax[1].plot(np.arange(1,101)-.5,100*np.array(duties),label='每 1 ms 的实际门极导通时间占比')
    ax[1].set(ylabel='导通时间占比 / %',xlabel='时间 / ms')
    for a in ax:a.grid(alpha=.25);a.legend(loc='best')
    fig.savefig(destination/'原启动与供能变化.png',dpi=150);plt.close(fig)

    fig,ax=plt.subplots(2,2,figsize=(13,8),layout='constrained')
    for j in range(1,4):
        a=ax.flat[j-1]
        for d,label in zip(runs,labels):a.plot(np.array(d['time'])*1000,d[f'v(out{j})'],label=label)
        a.set(title=f'OUT{j}：只改一个控制参数的对照',xlabel='时间 / ms',ylabel='V')
    d=runs[0];t=np.array(d['time'])*1000
    ax[1,1].plot(t,np.array(d['v(comp)'])-1.5,label='实际 COMP − 1.5 V')
    ax[1,1].plot(t,d['v(xu_ctrl:xmain:xcomp:integ)'],label='补偿器积分状态')
    ax[1,1].plot(t,np.minimum(1.8133262275,2*np.array(d['v(ss)'])),'--',label='软启动允许的指令上限')
    ax[1,1].set(title='原参数控制器内部状态（通用行为模型）',xlabel='时间 / ms',ylabel='V')
    for a in ax.flat:a.grid(alpha=.25);a.legend(fontsize=8,loc='best')
    fig.savefig(destination/'控制参数单变量对照.png',dpi=150);plt.close(fig)

    source=job_folder/'staged/Flyback/root-0/acf_startup_20261028'
    with ZipFile(destination/'诊断工程与原始数据.zip','w',ZIP_DEFLATED) as archive:
        for i in range(3):
            for path in source.iterdir():
                if path.name.startswith('case-') or path.name=='design_params.inc' or not path.is_file():continue
                data=path.read_bytes()
                if path.suffix=='.cir':
                    # MCP snapshots use absolute include paths. Relocate only
                    # these references; keep models and numerical cards intact.
                    text=data.decode('ascii')
                    text=re.sub(r'(?m)^(\.(?:include|lib))\s+([^\r\n]+)',
                        lambda m:m[1]+' '+Path(m[2].strip().strip('"')).name,text)
                    data=text.encode('ascii')
                archive.writestr(f'case_{i}/{path.name}',data)
            params=source/f'case-{i:04d}__design_params.inc'
            archive.writestr(f'case_{i}/design_params.inc',params.read_bytes())
            stem=job_folder/f'{prefix}_case_{i}'
            for suffix in ('.raw','.log'):
                archive.writestr(f'case_{i}/Flyback{suffix}',stem.with_suffix(suffix).read_bytes())
        archive.writestr('diagnosis.json',(destination/'diagnosis.json').read_bytes())
    print(json.dumps(dict(results=results,original_settling_ms=settle),ensure_ascii=False,indent=2))


if __name__=='__main__':
    a=argparse.ArgumentParser();a.add_argument('destination',type=Path);a.add_argument('--analyze-job',type=Path)
    args=a.parse_args()
    analyze(args.analyze_job,args.destination) if args.analyze_job else prepare(args.destination)
