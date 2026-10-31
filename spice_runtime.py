"""Owned LTspice batch runs, bounded RAW reading and auditable comparisons."""
from __future__ import annotations
import copy
import hashlib
import json
import math
import os
from pathlib import Path
import re
import subprocess
import tempfile
import time
import zipfile
import numpy as np


def find_ltspice():
    candidates=[os.environ.get('LTSPICE_EXE',''),r'D:\LTSPCIE\LTspice.exe',
        r'C:\Program Files\ADI\LTspice\LTspice.exe',r'C:\Program Files\LTC\LTspiceXVII\XVIIx64.exe',
        os.path.expandvars(r'%LOCALAPPDATA%\Programs\ADI\LTspice\LTspice.exe')]
    preferences=Path(os.environ.get('LOCALAPPDATA',str(Path.home()))) / 'PowerDesign'/'ltspice.json'
    try:candidates.insert(0,json.loads(preferences.read_text(encoding='utf-8'))['executable'])
    except (OSError,ValueError,KeyError,TypeError):pass
    return next((str(Path(p).resolve()) for p in candidates if p and Path(p).is_file()),None)


def set_ltspice(executable):
    path=Path(executable).resolve()
    if path.name.casefold() not in ('ltspice.exe','xviix64.exe','xviix86.exe') or not path.is_file():
        raise ValueError('请选择实际的 LTspice.exe 或 XVIIx64.exe')
    preferences=Path(os.environ.get('LOCALAPPDATA',str(Path.home()))) / 'PowerDesign'/'ltspice.json'
    preferences.parent.mkdir(parents=True,exist_ok=True)
    preferences.write_text(json.dumps(dict(executable=str(path)),ensure_ascii=False),encoding='utf-8')


def read_log(path):
    data=Path(path).read_bytes()
    text=data.decode('utf-16') if data.startswith((b'\xff\xfe',b'\xfe\xff')) else data.decode('utf-8',errors='replace')
    measurements={m[1]:float(m[2]) for m in re.finditer(r'(?m)^([a-z]\w*)(?::\s+.*?|\s*)=([-+\d.eE]+)(?:\s|$)',text)}
    errors=[line.strip() for line in text.splitlines() if any(x in line.lower() for x in ('fatal error','timestep too small','singular matrix','measurement failed','voltage not found','current not found'))]
    warnings=[line.strip() for line in text.splitlines() if line.lower().startswith('warning:')]
    return measurements,text,errors,warnings


class TransientRaw:
    """LTspice real forward binary only, with validated lengths and time axis."""
    def __init__(self,path):
        path=Path(path)
        with path.open('rb') as stream:header_bytes=stream.read(65536)
        encoding='utf-16-le' if header_bytes.startswith(b'T\x00') else 'utf-8'
        marker='Binary:\n'.encode(encoding)
        where=header_bytes.find(marker)
        if where<0:raise ValueError('RAW 格式不是受支持的二进制瞬态数据')
        header=header_bytes[:where].decode(encoding)
        flags=re.search(r'^Flags:\s*(.*)$',header,re.M)[1].strip().split()
        if 'real' not in flags or 'FastAccess' in flags or 'complex' in flags:
            raise ValueError('当前读取器只支持普通 real 瞬态 RAW，请关闭 FastAccess 后重跑')
        count=int(re.search(r'No\. Variables:\s*(\d+)',header)[1]);points=int(re.search(r'No\. Points:\s*(\d+)',header)[1])
        if not 2<=points<=30000000:raise ValueError('RAW 点数无效或超过可用预算，请缩短仿真时长')
        names=[m[1].casefold() for m in re.finditer(r'^\s*\d+\s+(\S+)\s+\S+\s*$',header.rsplit('Variables:',1)[1],re.M)]
        dtype=np.dtype([('time','<f8'),('values','<f8' if 'double' in flags else '<f4',(count-1,))])
        offset=where+len(marker)
        if len(names)!=count or path.stat().st_size!=offset+points*dtype.itemsize:raise ValueError('RAW 不完整或头信息与数据长度不一致')
        self.data=np.memmap(path,mode='r',dtype=dtype,offset=offset,shape=(points,))
        self.names={name:i-1 for i,name in enumerate(names) if i}
        self.time=np.abs(self.data['time'])  # LTspice marks breakpoints with negative time
        for first in range(0,points,500000):
            chunk=self.time[max(0,first-1):first+500000]
            if not np.all(np.isfinite(chunk)) or np.any(np.diff(chunk)<0):raise ValueError('RAW 时间倒退，可能包含多个 .step，请逐工况运行')
    def trace(self,name):return self.data['values'][:,self.names[name.casefold()]]
    def samples(self,names,start,end,points=2400):
        axis=np.linspace(start,end,points)
        neighbours=np.searchsorted(self.time,axis,side='right')
        right=np.clip(neighbours,0,len(self.time)-1)
        left=np.clip(neighbours-1,0,len(self.time)-1)
        width=self.time[right]-self.time[left]
        fraction=np.divide(axis-self.time[left],width,out=np.zeros_like(axis),where=width>0)
        fraction=np.clip(fraction,0,1)
        # Gather only the neighbouring points needed by each displayed sample.
        # np.interp on a strided float32 memmap makes whole-file float64 copies.
        result=dict(time=axis.tolist())
        for key in names:
            values=self.trace(key);a=values[left].astype(float);b=values[right].astype(float)
            result[key]=(a+(b-a)*fraction).tolist()
        return result
    def close(self):
        self.time=None
        self.data._mmap.close()


def partial_transient_time(path):
    """Read an unfinished RAW tail for diagnostics only, never measurements."""
    import struct
    try:
        with Path(path).open('rb') as stream:
            header_bytes=stream.read(65536)
            encoding='utf-16-le' if header_bytes.startswith(b'T\x00') else 'utf-8'
            marker='Binary:\n'.encode(encoding);where=header_bytes.find(marker)
            if where<0:return None
            header=header_bytes[:where].decode(encoding)
            flags=re.search(r'^Flags:\s*(.*)$',header,re.M)[1].split()
            if 'real' not in flags or 'FastAccess' in flags:return None
            count=int(re.search(r'No\. Variables:\s*(\d+)',header)[1])
            if not 2<=count<=100000:return None
            stride=8+(count-1)*(8 if 'double' in flags else 4)
            offset=where+len(marker);size=stream.seek(0,2)
            points=(size-offset)//stride
            if points<=0:return None
            stream.seek(offset+(points-1)*stride)
            value=abs(struct.unpack('<d',stream.read(8))[0])
            return value if math.isfinite(value) else None
    except (OSError,ValueError,TypeError,IndexError,AttributeError,struct.error):
        return None


def _run(executable,folder,timeout,cancelled):
    from calculation_scheduler import CalculationCancelled
    folder=Path(folder).resolve()
    kwargs=dict(cwd=str(folder),stdout=subprocess.DEVNULL,stderr=subprocess.STDOUT)
    if os.name=='nt':
        startup=subprocess.STARTUPINFO();startup.dwFlags=subprocess.STARTF_USESHOWWINDOW;startup.wShowWindow=0
        kwargs.update(startupinfo=startup,creationflags=subprocess.CREATE_NO_WINDOW|subprocess.BELOW_NORMAL_PRIORITY_CLASS)
    process=subprocess.Popen([executable,'-b',str(folder/'Flyback.cir')],**kwargs)
    start=time.monotonic()
    try:
        while process.poll() is None:
            if cancelled():raise CalculationCancelled()
            if time.monotonic()-start>timeout:
                reached=partial_transient_time(folder/'Flyback.raw')
                detail=f'；瞬态约推进至 {reached*1000:.4g} ms' if reached is not None else ''
                raise TimeoutError(f'LTspice 超过 {timeout:g} s{detail}；本工况未完成')
            time.sleep(.1)
        if process.returncode:raise RuntimeError(f'LTspice 返回退出码 {process.returncode}')
    finally:
        if process.poll() is None:
            process.terminate()
            try:process.wait(timeout=5)
            except subprocess.TimeoutExpired:process.kill();process.wait(timeout=5)
    return time.monotonic()-start


def _comparison_rows(case,measured,meta,periodicity=None,steady=None):
    result=case['result'];op=result['op'];rows=[]
    noniso=meta.get('topology') in ('BUCK','BOOST')
    tolerance=meta['settings']['comparison_tolerance_pct']
    stable=True
    for i in range(1,len(meta['hardware']['windings'])+1):
        a=measured.get(f'out{i}_earlier');b=measured.get(f'out{i}_before')
        if a is None or b is None or abs(a-b)>max(abs(b)*.01,.01):stable=False
    ready=stable and measured.get('fault_max',1)<.5 and (periodicity is None or periodicity['stable']) and (steady is None or steady['passed'])
    def add(name,unit,design,sim,scope='同名工况与量纲',comparable=True):
        delta=(sim-design)/abs(design)*100 if ready and comparable and design not in (None,0) and sim is not None else None
        status=('测量缺失' if sim is None else periodicity['reason']+' 仅统计' if periodicity and not periodicity['stable'] else '未稳态或处于保护' if not ready else '口径不同 仅并列' if not comparable
            else '不计算零基准百分比' if delta is None else '偏差待复核' if abs(delta)>tolerance else '偏差在提示阈值内')
        rows.append(dict(metric=name,unit=unit,design=design,simulation=sim,delta_percent=delta,status=status,scope=scope))
    add('输入电压','V',case['voltage'],measured.get('input_voltage'))
    add('实际开关频率','Hz',op['f_sw'] if meta.get('topology')=='QR-FLYBACK' else case['p']['f_sw'],measured.get('frequency_actual'),'稳态门极边沿周期测量')
    add('门极导通占空比','',op['D'],measured.get('duty_avg'))
    add('原边电流 RMS','A',op.get('I_p_rms',op['I_sw_rms']),measured.get('primary_rms'))
    add('原边电流峰值','A',op['I_sw_pk'],measured.get('primary_peak'))
    add('原边电流平均值','A',op.get('I_p_avg',op['I_sw_avg']),measured.get('primary_avg'),
        '同一原边绕组全周期有符号均值' if 'I_p_avg' in op else '计算开关平均电流与物理原边绕组电流，含钳位换流差异')
    add('Vcs 峰值','V',op['I_sw_pk']*case['p']['Rs'],measured.get('vcs_peak'),'采样端含开通过渡尖峰',False)
    if noniso:
        for key,field,title in [('switch_rms','I_sw_rms','RMS'),('switch_avg','I_sw_avg','平均值'),('switch_peak','I_sw_pk','峰值')]:
            add('MOS Q1 电流 '+title,'A',op[field],measured.get(key),'实际串联 Rs 支路全周期电流',not meta['settings']['niso_edge_model'])
    add('MOS Vds 峰值','V',op['V_sw_max'],measured.get('vds_peak'),'计算器钳位包络与瞬态寄生模型不同',False)
    outputs=result.get('outputs') or []
    for i,winding in enumerate(meta['hardware']['windings'],1):
        child=outputs[i-1]['op'] if outputs else op
        add(f'OUT{i} 输出平均电压','V',child['V_out'],measured.get(f'out{i}_before'),'设计模型稳态电压与含器件压降的 SPICE 输出')
        add(f'OUT{i} 电容端／反馈前电压','V',child.get('V_out_cap',child['V_out']),measured.get(f'out{i}_cap_before'),
            '防反管前电容端；只有所选一路进入反馈')
        add(f'OUT{i} 副边电流 RMS','A',child.get('I_s_rms',child['I_d_rms']),measured.get(f'out{i}_winding_rms'))
        add(f'OUT{i} 副边电流峰值','A',child.get('I_s_pk',child['I_d_pk']),measured.get(f'out{i}_winding_peak'))
        add(f'OUT{i} 副边电流平均值','A',child['I_d_avg'],measured.get(f'out{i}_winding_avg'))
        ripple=outputs[i-1]['ripple_pp'] if outputs else result['wf']['ripple_pp']
        add(f'OUT{i} 输出电容纹波峰峰值','V',ripple,measured.get(f'out{i}_pre_ripple'),'ESL/器件开关边沿及整流模型不同',False)
        add(f'OUT{i} 整流管反压','V',child['V_d_max'],measured.get(f'out{i}_diode_reverse'),'理想稳态反压与瞬态极值不同',False)
    if noniso:
        for row in rows:
            name=row['metric']
            if name.startswith('原边电流'):
                field={'原边电流 RMS':'I_L_rms','原边电流峰值':'I_L_pk','原边电流平均值':'I_L_avg'}[name]
                row['design']=op[field]
                row['delta_percent']=(row['simulation']-op[field])/abs(op[field])*100 if ready and op[field] and row['simulation'] is not None else None
                row['metric']=name.replace('原边电流','电感 L1 电流');row['scope']='同一电感 L1 的全周期电流'
                if row['delta_percent'] is not None:row['status']='偏差待复核' if abs(row['delta_percent'])>tolerance else '偏差在提示阈值内'
            row['metric']=row['metric'].replace('副边电流','二极管 D1 电流').replace('整流管反压','续流管反压' if meta['topology']=='BUCK' else '整流管反压')
    return rows,ready


def compare_design(run,destination,*,cancelled=lambda:False,progress=None,executable=None):
    """Create a Word report plus an auditable ZIP. Never invent simulator data."""
    from spice_export import project_files,normalize_settings
    from calculation_scheduler import CalculationCancelled
    executable=executable or find_ltspice()
    if not executable:raise ValueError('未检测到 LTspice。请在桌面仿真设置中选择 LTspice.exe 后重试')
    bundle=run.runtime_bundle();p=bundle['base_spec'];settings=normalize_settings(p.get('spice_config'))
    destination=Path(destination).resolve();destination.parent.mkdir(parents=True,exist_ok=True)
    report_path=destination if destination.suffix.lower()=='.docx' else destination.with_suffix('.docx')
    zip_path=destination if destination.suffix.lower()=='.zip' else destination.with_suffix('.zip')
    from spice_export import MODEL_VERSION
    qr=p.get('topology')=='QR-FLYBACK'
    if qr:
        from qr_spice_export import MODEL_VERSION
    forward=p.get('topology')=='ACF-FORWARD'
    noniso=p.get('topology') in ('BUCK','BOOST')
    if noniso:
        from nonisolated_spice import MODEL_VERSION
    if forward:
        from acf_spice import MODEL_VERSION
    from spice_studies import run_fra,run_cross,collect_study
    from spice_analysis import cycle_quality,statistics
    if qr:
        from qr_spice_analysis import cycle_quality
    evidence=dict(schema='powerdesign-spice-comparison-2',model=MODEL_VERSION,cases=[],settings=settings,topology=p.get('topology'))
    cases=[];seen=set()
    for case in bundle['cases']:
        if case['voltage'] not in seen:cases.append(case);seen.add(case['voltage'])
    total=len(cases)*((2 if settings['short_test'] else 1)+int(settings['fra_enabled'])+int(settings['cross_enabled']))
    with tempfile.TemporaryDirectory(prefix='spice-compare-',dir=destination.parent) as temporary:
        work=Path(temporary);archive_files={};done=0
        for case in cases:
            for fault_case in ([False,True] if settings['short_test'] else [False]):
                if cancelled():raise CalculationCancelled()
                done+=1;label=case['id']+('_短路测试' if fault_case else '_标称负载')
                if progress:progress(done,total,'LTspice '+label)
                q=copy.deepcopy(p);q['spice_config']=dict(settings,short_test=int(fault_case))
                files=project_files(q,bundle=bundle)
                meta=json.loads(files['manifest.json'])
                folder=work/label;folder.mkdir()
                for name,data in files.items():
                    if name=='design_params.inc':
                        data=('\n'.join(line for line in data.decode('ascii').splitlines() if not line.startswith(('.step ','.param VIN=')))+f'\n.param VIN={case["voltage"]:.12g}\n').encode('ascii')
                        files[name]=data
                    (folder/name).write_bytes(data)
                    archive_files[label+'/'+name]=data
                record=dict(id=label,voltage=case['voltage'],fault_test=fault_case,complete=False,measurements={},rows=[],plots=[],
                    controller=meta['resolved_controller'],slope=meta['slope'],feedback_output=meta['feedback_output'],
                    qr=meta.get('qr'),acf=meta.get('acf'),approximation_notes=meta.get('approximation_notes',[]),
                    niso=meta.get('niso'),
                    hardware=meta['hardware'],source_hashes={k:hashlib.sha256(v).hexdigest() for k,v in files.items() if k.endswith(('.cir','.inc','.lib'))},
                    loop=dict(available=False,error='未启用 FRA'),cross=dict(supported=False,error='未启用交叉调整率扫描'))
                evidence['cases'].append(record)
                if case['result']['op'].get('acf_model'):
                    cm=case['result']['op']['acf_model']
                    record['calculation_model']={key:cm[key] for key in ('kind','revision','assumptions','mesh','current_mesh_verified','normalized_residual','energy_balance_relative')}
                raw=None
                try:
                    record['elapsed_s']=_run(executable,folder,settings['simulation_timeout_s'],cancelled)
                    measured,log,errors,warnings=read_log(folder/'Flyback.log')
                    raw=TransientRaw(folder/'Flyback.raw')
                    if noniso:
                        raw.names['i(lp)']=raw.names['i(l1)']
                        raw.names['i(ls1)']=raw.names['i(v_d1)']
                    if errors or not math.isclose(raw.time[-1],settings['stop_ms']*1e-3,abs_tol=1e-10):
                        raise ValueError('仿真未到结束时刻或日志存在求解失败：'+'; '.join(errors))
                    required=['primary_rms','primary_peak','vds_peak','fault_max','input_voltage','frequency_actual','duty_avg']+[f'out{i}_before' for i in range(1,len(meta['hardware']['windings'])+1)]
                    if any(k not in measured for k in required):raise ValueError('必要的 .meas 数据缺失，不能生成有效对比')
                    record.update(complete=True,measurements=measured,warnings=warnings,
                        actual_end_s=float(raw.time[-1]),points=len(raw.time))
                    frequency=meta['resolved_controller']['FSW']
                    record['periodicity']=cycle_quality(raw,frequency,settings['step_ms']*1e-3-400/frequency,
                        settings['step_ms']*1e-3-10/frequency,meta['resolved_controller']['VG'],tolerance_pct=settings['cycle_tolerance_pct'])
                    if forward:
                        from acf_spice import timing_quality
                        record['acf_timing']=timing_quality(raw,frequency,settings['step_ms']*1e-3-10/frequency,
                            meta['resolved_controller']['VG'],meta['hardware']['R_dc_p'])
                        if not record['acf_timing']['passed']:
                            record['periodicity'].update(stable=False,reason='有源钳位死区／磁复位检查未通过')
                    if qr and record['periodicity'].get('frequency_mean_hz'):
                        measured['frequency_actual']=record['periodicity']['frequency_mean_hz']
                        meta['qr_measured_min_frequency_hz']=record['periodicity']['frequency_min_hz']
                    if forward or noniso:
                        from spice_analysis import steady_quality
                        record['steady_before_step']=steady_quality(raw,frequency,settings['step_ms']*1e-3,len(meta['hardware']['windings']))
                    record['rows'],record['nominal_comparable']=_comparison_rows(case,measured,meta,record['periodicity'],record.get('steady_before_step'))
                    if fault_case:
                        for row in record['rows']:row.update(delta_percent=None,status='短路测试 不与标称判差')
                    names=['v(out'+str(i)+')' for i in range(1,len(meta['hardware']['windings'])+1)]
                    record['startup']=raw.samples(names+['v(ss)','v(fault)'],0,float(raw.time[-1]),3000)
                    end=settings['step_ms']*1e-3-10/meta['resolved_controller']['FSW'];begin=end-5/meta['resolved_controller']['FSW']
                    record['switching']=raw.samples(['v(drain)','v(sense)','v(gate)','v(comp)','v(ramp)','i(lp)']+(['v(zcd)'] if qr else [])+
                        (['v(sync)','v(auxgate)','v(aclamp)','v(vin_bus)','i(c_active)']+[f'i(lo{i})' for i in range(1,len(meta['hardware']['windings'])+1)] if forward else [])+
                        ['i(ls'+str(i)+')' for i in range(1,len(meta['hardware']['windings'])+1)]+
                        [f'v({node}{i})' for i in range(1,len(meta['hardware']['windings'])+1) for node in ('out','cap')],begin,end,2400)
                    if forward:
                        for i in range(1,len(meta['hardware']['windings'])+1):
                            key=f'i(ls{i})'
                            record['switching'][key]=(-np.asarray(record['switching'][key])).tolist()
                    wf=case['result']['wf'];sample_time=np.asarray(record['switching']['time'])
                    if qr or math.isclose(case['p']['f_sw'],meta['resolved_controller']['FSW']):
                        design_frequency=case['result']['op']['f_sw'] if qr else case['p']['f_sw']
                        origin=record['periodicity']['cycles'][0]['start_s'] if qr and record['periodicity']['cycles'] else 0.
                        phase=np.mod(sample_time-origin,1/design_frequency)
                        # LP is a physical winding current, not magnetising current.
                        record['design_switching']={key:np.interp(phase,wf['t'],wf[source]).tolist()
                            for key,source in [('i_p','iL' if noniso else 'i_primary' if 'i_primary' in wf else 'i_p' if forward else 'i_sw'),('v_sw','v_sw')]}
                    record['branches']=[]
                    for i in range(1,len(meta['hardware']['windings'])+1):
                        child=wf['outputs'][i-1] if wf.get('outputs') else wf
                        branch=dict(id=i,name=(case['result']['outputs'][i-1]['name'] if case['result'].get('outputs') else 'OUT1'),
                            simulation_ripple=statistics(raw.time,raw.trace(f'v(out{i})'),settings['step_ms']*1e-3-200/frequency,settings['step_ms']*1e-3-10/frequency))
                        if qr or math.isclose(case['p']['f_sw'],frequency):
                            branch['design_current']=np.interp(phase,child['t'],child['i_s']).tolist()
                            branch['design_ripple']=np.interp(phase,child['t'],child['vout_ripple']).tolist()
                            branch['design_ripple_pp']=float(child['ripple_pp'])
                            if forward:
                                branch['design_choke']=np.interp(phase,child['t'],child['iL']).tolist()
                                child_op=case['result']['outputs'][i-1]['op'] if case['result'].get('outputs') else case['result']['op']
                                branch.update(choke_design_rms=child_op['I_L_rms'],choke_design_peak=child_op['I_L_pk'],choke_design_valley=child_op['I_L_min'])
                        record['branches'].append(branch)
                    fault=raw.trace('v(fault)');indices=np.flatnonzero(np.diff((fault>.5).astype(np.int8))>0)
                    record['fault_events_s']=raw.time[indices+1].tolist()[:100]
                    record['source_model_hash']=meta['library_sha256']
                except CalculationCancelled:raise
                except Exception as exc:record.update(complete=False,error=str(exc))
                finally:
                    if raw is not None:raw.close()
                    if (folder/'Flyback.log').is_file():archive_files[label+'/Flyback.log']=(folder/'Flyback.log').read_bytes()
                if fault_case:continue
                def execute(study_folder,timeout):return _run(executable,study_folder,timeout,cancelled)
                if settings['fra_enabled']:
                    done+=1
                    if progress:progress(done,total,'LTspice '+case['id']+' 原生 FRA')
                    if record['complete'] and record['periodicity']['stable'] and record['nominal_comparable']:
                        study=work/(case['id']+'_FRA')
                        operating_point=None
                        if qr:
                            from spice_studies import qr_measured_point
                            operating_point=qr_measured_point(case,record)
                        record['loop']=run_fra(files,case,meta,settings,study,execute,
                            progress=lambda message:progress(done,total,case['id']+' '+message) if progress else None,
                            operating_point=operating_point)
                        if study.is_dir():archive_files.update(collect_study(study,study.name))
                        if (study/'half_amplitude').is_dir():archive_files.update(collect_study(study/'half_amplitude',study.name+'/half_amplitude'))
                    else:record['loop']['error']='标称工况未通过逐周期与直流稳态检查，不提供有效线性化 FRA'
                if settings['cross_enabled']:
                    done+=1
                    if progress:progress(done,total,'LTspice '+case['id']+' 交叉调整率角点')
                    study=work/(case['id']+'_交叉调整率')
                    record['cross']=run_cross(files,case,meta,settings,study,execute,cancelled=cancelled,
                        progress=lambda message:progress(done,total,case['id']+' '+message) if progress else None)
                    if study.is_dir():archive_files.update(collect_study(study,study.name))
                    for retry in study.glob('retry_*'):
                        if retry.is_dir():archive_files.update(collect_study(retry,study.name+'/'+retry.name))
        if cancelled():raise CalculationCancelled()
        from spice_comparison_report import write_report
        pending_report=work/'comparison.docx'
        archive_files['comparison.json']=json.dumps(evidence,ensure_ascii=False,allow_nan=False,indent=2).encode('utf-8')
        try:write_report(pending_report,evidence)
        except Exception as exc:
            recovery=destination.with_name(destination.stem+f'-evidence-{time.time_ns()}.zip')
            with zipfile.ZipFile(recovery,'w',zipfile.ZIP_DEFLATED) as archive:
                for name,data in archive_files.items():archive.writestr(name,data)
            raise RuntimeError('报告排版未完成，实际仿真证据已保留：'+str(recovery)) from exc
        archive_files[report_path.name]=pending_report.read_bytes()
        pending_zip=work/'comparison.zip'
        with zipfile.ZipFile(pending_zip,'w',zipfile.ZIP_DEFLATED) as archive:
            for name,data in archive_files.items():archive.writestr(name,data)
        if cancelled():raise CalculationCancelled()
        os.replace(pending_report,report_path)
        os.replace(pending_zip,zip_path)
    nominal=[c for c in evidence['cases'] if not c['fault_test']]
    fra_success=sum(c['loop'].get('available',False) for c in nominal)
    cross_cases=[c for c in nominal if c['cross'].get('supported')]
    cross_success=sum(c['cross'].get('complete',False) for c in cross_cases)
    return dict(path=str(zip_path),report_path=str(report_path),successful=sum(c['complete'] for c in evidence['cases']),
        total=len(evidence['cases']),fra_successful=fra_success,fra_total=len(nominal) if settings['fra_enabled'] else 0,
        cross_successful=cross_success,cross_total=len(cross_cases),
        incomplete=any(not c['complete'] for c in evidence['cases']) or
            bool(settings['fra_enabled'] and fra_success<len(nominal)) or
            bool(settings['cross_enabled'] and cross_success<len(cross_cases)))
