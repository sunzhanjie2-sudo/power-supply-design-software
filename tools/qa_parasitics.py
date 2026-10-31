"""Actual LTspice checks of RLC equations and exported ASC/CIR contracts."""
from pathlib import Path
import copy
import json
import re
import subprocess
import sys
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
from runtime_resources import configure_numeric_threads
configure_numeric_threads()


def main():
    from parasitic_ringing import solve_edge
    from spice_runtime import find_ltspice,_run,read_log
    from design_engine.specification import load_spec
    from spice_export import project_files
    root=ROOT/'artifacts/qa/parasitics_20261029';root.mkdir(parents=True,exist_ok=True)
    exe=find_ltspice()
    if not exe:raise RuntimeError('未安装 LTspice，不把缺失仿真当作通过')
    evidence={'rlc':[],'projects':[]}
    for name,changes in [('free',{}),('clamped',{'ceiling':115.}),('rc',{'snub_r':10.,'snub_c':2e-9}),('voltage_step',{'current':0.,'initial_voltage':0.})]:
        args=dict(inductance=100e-9,capacitance=500e-12,resistance=2.,current=3.,plateau=100.)
        args.update(changes)
        predicted=solve_edge(**args)
        folder=root/('RLC_'+name);folder.mkdir(exist_ok=True)
        initial=args.get('initial_voltage',100.)-100.
        lines=['Independent RLC audit, shifted around blocking plateau',
            'LTEST 0 mid 100e-9 IC='+str(args['current']),'RTEST mid port 2',f'CTEST port 0 500e-12 IC={initial}',
            '.options plotwinsize=0 reltol=1e-6 abstol=1e-11', '.tran 0 1.2e-6 0 0.1e-9 uic',
            '.save V(port) I(LTEST)', '.meas tran peak MAX V(port)']
        if 'ceiling' in args:lines+=['VCLAMP top 0 15','DCLAMP port top DCL','.model DCL D(Ron=0.001 Roff=1e12 Vfwd=0)']
        if args.get('snub_c'):lines+=['RSNUB port snub 10',f'CSNUB snub 0 2e-9 IC={initial}']
        lines+=['.end'];(folder/'Flyback.cir').write_text('\n'.join(lines)+'\n',encoding='ascii')
        _run(exe,folder,60,lambda:False);measures,_,errors,_=read_log(folder/'Flyback.log')
        if errors:raise ValueError(errors)
        actual=100+measures['peak'];relative=abs(actual/predicted['peak']-1)
        evidence['rlc'].append(dict(case=name,computed_peak=predicted['peak'],native_peak=actual,relative_difference=relative))
        print('Native RLC',name,'difference',relative,flush=True)
        if relative>.003:raise ValueError('独立局部模型与原生 SPICE 峰值不一致')
    for name in ('40W_CCM_FLYBACK.json','90W_QR_L6565_300V.json','33W_3OUT_ACF_MP6005_COMPACT.json'):
        p=load_spec(json.loads((ROOT/'examples'/name).read_text(encoding='utf-8')))
        p['parasitic_config']=dict(mode='fast',lp_pcb=30e-9,rp_pcb=.005,cw_primary=20e-12,
            snub_r_primary=22.,snub_c_primary=80e-12,r_cj=.15,rails={'OUT1':dict(cj=55e-12,cw=10e-12,l_pcb=15e-9,snub_r=15.,snub_c=100e-12)})
        files=project_files(p);folder=root/name.removesuffix('.json');folder.mkdir(exist_ok=True)
        acf=p['topology']=='ACF-FORWARD'
        for file,data in files.items():
            if file=='design_params.inc':
                data=re.sub(rb'(?m)^\.step[^\r\n]*',b'',data)
                for key,value in (('TEN',1. if acf else 1e-6),('TSS',20e-6),('TSTART',40e-6),('SSMODE',0.)):
                    data=re.sub(rb'(?m)^\.param '+key.encode()+rb'=[^\r\n]*',f'.param {key}={value:.12g}'.encode(),data)
            (folder/file).write_bytes(data)
        # Short compile/execution bench, not a steady-state or full FRA claim.
        analysis=('.options threads=2 plotwinsize=0 method=gear reltol='+('0.003' if acf else '1e-6')+
            '\n.tran 0 '+('0.03m' if acf else '0.3m')+' 0 '+('10n' if acf else '2n')+
            '\n.save V(drain) V(gate) V(sense) I(LP)\n.meas tran compile_peak MAX V(drain)\n.meas tran gate_peak MAX V(gate,sense)\n')
        if acf:
            # Power-stage commutation bench, not a fast-startup controller claim.
            # TEN=1s holds the original controller off; independent ideal gate
            # fixtures exercise both switches with explicit dead time.
            analysis+='VBENCH_GATE gate sense PULSE(0 {VG} 1u 2n 2n {.35/FSW} {1/FSW})\n'
            analysis+='VBENCH_AUX auxgate 0 PULSE(0 {-VG} {1e-6+.35/FSW+TDEAD} 2n 2n {.65/FSW-2*TDEAD} {1/FSW})\n'
        (folder/'analysis.inc').write_text(analysis,encoding='ascii')
        _run(exe,folder,90,lambda:False);measure,_,errors,_=read_log(folder/'Flyback.log')
        if errors or 'compile_peak' not in measure or measure.get('gate_peak',0)<5:raise ValueError('未观察到实际开关动作：'+str(errors))
        cir_peak=measure['compile_peak']
        # Simulate the native ASC as a second independent LTspice entry.
        startup=subprocess.STARTUPINFO();startup.dwFlags=subprocess.STARTF_USESHOWWINDOW;startup.wShowWindow=0
        done=subprocess.run([exe,'-netlist',str(folder/'Flyback.asc')],cwd=folder,timeout=20,stdout=subprocess.DEVNULL,
            stderr=subprocess.STDOUT,startupinfo=startup,creationflags=subprocess.CREATE_NO_WINDOW)
        if done.returncode or not (folder/'Flyback.net').is_file():raise ValueError('ASC 原生网表生成失败')
        def canonical(text):
            cards=[]
            for line in text.splitlines():
                if not line or line[0] in '*;.':continue
                parts=line.replace('§','').lower().split()
                if parts[0][0] in 'rc':parts[1:3]=sorted(parts[1:3])
                cards.append(tuple(parts))
            return sorted(cards)
        net=(folder/'Flyback.net').read_text(encoding='utf-8')
        if canonical(net)!=canonical(files['power_stage.inc'].decode()):
            raise ValueError('原生 ASC 与 CIR 元件卡/节点不同')
        (folder/'cir_entry.cir').write_bytes((folder/'Flyback.cir').read_bytes())
        (folder/'Flyback.cir').write_bytes((folder/'Flyback.net').read_bytes())
        _run(exe,folder,90,lambda:False)
        asc_measure,_,errors,_=read_log(folder/'Flyback.log')
        if errors:raise ValueError(str(errors))
        delta=abs(asc_measure['compile_peak']-cir_peak)
        if delta>max(abs(cir_peak)*.01,1e-4):raise ValueError('同电路不同网表次序的短时峰值差异超过 1%')
        evidence['projects'].append(dict(example=name,cir_peak=cir_peak,asc_peak=asc_measure['compile_peak'],difference=delta,
            gate_peak=measure['gate_peak'],scope=('0.03ms open-loop power-stage commutation fixture; original controller held off' if acf else '0.3ms switching bench with shortened startup')+'; entry consistency only, not steady-state accuracy'))
        print('Native ASC/CIR',name,'difference',delta,flush=True)
    (root/'native_verification.json').write_text(json.dumps(evidence,ensure_ascii=False,indent=2),encoding='utf-8')
    print('Native parasitics checks passed',flush=True)


if __name__=='__main__':main()
