"""Native switching FRA and fixed-hardware load corners; no surrogate AC data."""
import copy
import itertools
import json
import math
from pathlib import Path
import re
import numpy as np
from spice_analysis import FrequencyRaw,loop_metrics,statistics,cycle_quality


def override_parameters(files,changes):
    result=dict(files);text=result['design_params.inc'].decode('ascii')
    for key,value in changes.items():
        pattern=r'(?m)^\.param '+re.escape(key)+r'=[^\r\n]*'
        line=f'.param {key}={value:.12g}'
        text=re.sub(pattern,line,text) if re.search(pattern,text) else text+'\n'+line
    result['design_params.inc']=text.encode('ascii');return result


def write_study(folder,files,readme):
    folder.mkdir(parents=True,exist_ok=True)
    for name,data in files.items():
        if name.endswith(('.asc','.asy','.md')):continue
        (folder/name).write_bytes(data)
    (folder/'README.md').write_text(readme,encoding='utf-8')


def collect_study(folder,prefix):
    return {prefix+'/'+p.name:p.read_bytes() for p in folder.iterdir() if p.is_file() and
        (p.suffix in ('.cir','.inc','.lib','.log','.json','.md') or '.fra_' in p.name and p.suffix=='.raw')}


def matched_parameters(case,controller):
    from analysis_workflows import pin_hardware
    p=pin_hardware(case['p'],case['result'])
    p.update(f_sw=controller['FSW'],control_mode='Peak Current Mode' if controller['MODE'] else 'Voltage Mode',
        A_sense=controller['A_CS'],Vm=controller['VM'],
        KP=controller['KP']*controller['FB_SCALE'],fz1=controller['FZ1'],fz2=controller['FZ2'],
        fp1=controller['FP1'],fp2=controller['FP2'],controller_type='type2' if controller['TYPE']==2 else 'type3',
        ma_slope=controller['SLOPE']/(controller['A_CS']*case['p']['Rs']))
    if p.get('topology')=='QR-FLYBACK':
        # FSW is the nominal measurement/window frequency in an event-driven
        # export. It must not overwrite the design's frequency ceiling.
        p['f_sw']=controller.get('FSW_LIMIT',case['p']['f_sw'])
        p['Coss']=controller['Q_COSS']
        settings=dict(p.get('spice_config') or {})
        for source,target,scale in (
                ('Q_COSS','qr_cds_pf',1e12),('TOFFMIN','qr_off_min_us',1e6),
                ('TOFFLIGHT','qr_off_light_us',1e6),('ZDELAY','qr_zcd_delay_ns',1e9),
                ('CS0','qr_cs_clamp_v',1.),('VFF','qr_vff_v',1.),
                ('TONMAX','qr_max_on_us',1e6),('Z_R','qr_zcd_r',1.),
                ('Z_C','qr_zcd_c_pf',1e12),('Z_RATIO','qr_aux_ratio',1.),
                ('ZARM','qr_zcd_arm_v',1.),('ZTRIG','qr_zcd_trigger_v',1.),
                ('TLEB','blanking_ns',1e9),('TONMIN','min_on_ns',1e9),
                ('TPROP','delay_ns',1e9),('CS_TAU','cs_filter_ns',1e9)):
            if source in controller:settings[target]=controller[source]*scale
        p['spice_config']=settings
        if controller.get('D_SN1_EN',1.) and all(key in controller for key in ('R_SN1','C_SN1')):
            resistance,capacitance=(float(controller[key]) for key in ('R_SN1','C_SN1'))
            if not (math.isfinite(resistance) and resistance>0 and math.isfinite(capacitance) and capacitance>0):
                raise ValueError('QR导出的固定RCD阻容必须为有限正数')
            p['_qr_rcd_hardware']=dict(R_ohm=resistance,C_F=capacitance,source='spice-export-parameters')
    return p


def analytical_loop(case,controller,frequencies,*,measured=None):
    from plants import build_loop_models
    from power_stage import compute_operating_point
    p=matched_parameters(case,controller)
    op=case['result']['op'] if p.get('topology')!='QR-FLYBACK' and math.isclose(controller['FSW'],case['p']['f_sw']) else compute_operating_point(p)
    models,_=build_loop_models(p,op);f=np.asarray(frequencies)
    details=None
    if measured is not None:
        if p.get('topology')!='QR-FLYBACK':raise ValueError('实测工作点重建目前只支持 QR')
        from qr_loop import plant
        gvc,details=plant(p,op,measured=measured)
        models=(gvc,models[1],gvc*models[1])
    gains=[np.asarray(model(2j*np.pi*f)).ravel() for model in models]
    return dict(loop=loop_metrics(f,gains[2]),plant=loop_metrics(f,gains[0]),
        compensator=loop_metrics(f,gains[1]/controller['FB_SCALE']),
        point=details,
        assumptions=('以仿真稳态点重建 QR 周期平均模型；平均输出电流比例固定校正，不属于独立预测。' if measured is not None else '按设计工作点及导出补偿参数重建，不依赖仿真数据。'))


def qr_measured_point(case,record):
    """Audit point from complete settled nominal LTspice data, not peak spikes."""
    import statistics
    q=record['periodicity'];m=record['measurements'];cycles=q.get('cycles',[])
    if not record.get('nominal_comparable') or not q.get('stable') or len(cycles)<8:
        raise ValueError('QR 实测工作点未通过稳态与周期检查')
    from voltage_nodes import input_drop
    from isolated_outputs import output_specs
    count=len(output_specs(case['p'])) or 1
    selected=int(case['p'].get('feedback_output',1))
    if not 1<=selected<=count:raise ValueError('QR实测反馈输出编号超出当前路数')
    return dict(vin_bus=float(m['input_voltage'])-input_drop(case['p']),
        vout=float(m[f'out{selected}_before']),vcap=float(m[f'out{selected}_cap_before']),
        ipk=float(statistics.median(c['peak'] for c in cycles)),
        period=float(sum(c['period_s'] for c in cycles)/len(cycles)),
        iout=float(m[f'out{selected}_winding_avg']),
        rail_currents=[float(m[f'out{i}_winding_avg']) for i in range(1,count+1)],
        rail_voltages=[float(m[f'out{i}_before']) for i in range(1,count+1)],
        rail_cap_voltages=[float(m[f'out{i}_cap_before']) for i in range(1,count+1)])


def prepare_fra(files,meta,settings,*,frequencies=None,amplitude_factor=1.):
    values=meta['resolved_controller'];fsw=values['FSW'];start=settings['fra_start_hz'];stop=min(settings['fra_stop_hz'],fsw/10)
    if meta.get('topology')=='QR-FLYBACK':stop=min(stop,meta.get('qr_measured_min_frequency_hz',fsw)/10)
    if frequencies is not None:start,stop=float(min(frequencies)),float(max(frequencies))
    if stop<=start:raise ValueError('FRA 频带受 fsw/10 限制后没有可用范围，请降低起始频率')
    # Native FRA can run beyond the transient stop time. VEN's pulse width
    # uses TSTOP; keeping the old value silently disables the loop mid-sweep.
    result=override_parameters(files,dict(LOAD_AFTER=1,TLOAD=1e6,TSTOP=1e6))
    stage=result['power_stage.inc'].decode('ascii')
    old='sgnd fb 0 GPWR_FEEDBACK';assert stage.count(old)==1
    stage=stage.replace(old,'sgnd fb_return 0 GPWR_FEEDBACK')
    amplitude=max(abs(values['VSET']),.01)*settings['fra_amplitude_pct']/100*amplitude_factor
    delay=max(settings['step_ms']*1e-3,(settings['soft_start_ms']+settings['enable_delay_ms'])*1e-3+.004)
    forward=meta.get('topology')=='ACF-FORWARD'
    settle=max(2/3000,100/fsw,.002 if forward else 0)
    # Native flist ADDS points to the regular sweep on LTspice 24.1.9; combining
    # it with the full range produced invalid probe accumulators. A plain
    # octave sweep over fc/2..2fc gives the intended three half-amplitude points.
    analyzer=f'@1 fb_return fb fstart={start:.12g} fend={stop:.12g} oct={1 if frequencies is not None else settings["fra_oct"]:g} delay={delay:.12g} pp0={amplitude:.12g} tavgmin={settings["fra_cycles"]/fsw:.12g} tsettle={settle:.12g} nmax={1 if frequencies is not None or forward else 2}'
    stage+='\n'+analyzer+f'\n&1C comp 0 fb 0\n&1P cap{int(values["FB_SELECT"])} sgnd comp 0\n'
    result['power_stage.inc']=stage.encode('ascii')
    result['analysis.inc']=(f'.options threads={int(settings["simulation_threads"])} method=gear reltol=0.003 plotwinsize=300\n.fra dTmax={1/fsw/60:.12g}\n'
        '.save V(gate) V(sense) V(comp) V(fb) V(fb_return) V(fault)\n').encode('ascii')
    return result,dict(start_hz=start,stop_hz=stop,delay_s=delay,amplitude_pp_v=amplitude,
        method='LTspice 原生时域 FRA，低阻输出至高阻反馈端串联电压注入；T=-gain_1')


def run_fra(files,case,meta,settings,folder,execute,*,progress=None,operating_point=None):
    result=dict(complete=False,available=False,error=None,simulation=None,design=None,original=None)
    import time
    started=time.monotonic()
    try:
        prepared,definition=prepare_fra(files,meta,settings);result['definition']=definition
        write_study(folder,prepared,'# 开关闭环 FRA\n\n运行 Flyback.cir。此目录使用原生 .fra 和 @1 注入器，不是普通 AC。原生功率级 ASC 见同工况的标称目录。\n')
        result['elapsed_s']=execute(folder,settings['fra_timeout_s'])
        paths=list(folder.glob('Flyback.fra_*.raw'))
        if len(paths)!=1:raise ValueError('LTspice 未输出唯一的 FRA 复数文件；请确认版本支持 .fra')
        raw=FrequencyRaw(paths[0]);gain=-raw.traces['gain_1']
        if np.any(abs(gain)<1e-15):raise ValueError('FRA 返回接近零的环路信号，可能饱和或未进入有效线性区')
        if raw.frequency[0]>definition['start_hz']*1.001 or raw.frequency[-1]<definition['stop_hz']*.999:
            raise ValueError('FRA 未覆盖完整设定频带')
        result['simulation']=dict(loop=loop_metrics(raw.frequency,gain),
            compensator=loop_metrics(raw.frequency,-raw.traces['probe_1c']),
            plant=loop_metrics(raw.frequency,raw.traces['probe_1p']))
        result['design']=analytical_loop(case,meta['resolved_controller'],raw.frequency)
        if operating_point is not None:
            try:
                result['measured_reconstruction']=analytical_loop(case,meta['resolved_controller'],raw.frequency,measured=operating_point)
            except ValueError as exc:
                result['measured_reconstruction_error']=str(exc)
        original=case.get('models')
        if original is None:
            from plants import build_loop_models
            original,_=build_loop_models(case['p'],case['result']['op'])
        if original:
            result['original']=loop_metrics(raw.frequency,np.asarray(original[2](2j*np.pi*raw.frequency)).ravel())
        # A second small-signal amplitude validates sensitivity near crossover.
        crossover=result['simulation']['loop']['fc'] or math.sqrt(raw.frequency[0]*raw.frequency[-1])
        checks=np.unique(np.clip([crossover/2,crossover,crossover*2],raw.frequency[0],raw.frequency[-1]))
        checkfolder=folder/'half_amplitude'
        # ACF has multiple LC branches: compare identical frequencies rather
        # than interpolating across a nearby resonance in a coarse sweep.
        half,_=prepare_fra(files,meta,settings,frequencies=None if meta.get('topology') in ('ACF-FORWARD','BUCK','BOOST') else checks,amplitude_factor=.5)
        write_study(checkfolder,half,'# FRA 半幅复核\n\n只复核关键频点；不替代完整扫描。\n')
        if progress:progress('FRA 半幅复核')
        result['half_amplitude_elapsed_s']=execute(checkfolder,settings['fra_timeout_s'])
        half_raw=FrequencyRaw(next(checkfolder.glob('Flyback.fra_*.raw')))
        half_gain=-half_raw.traces['gain_1']
        if np.any(abs(half_gain)<1e-15):raise ValueError('FRA 半幅复核没有有效环路信号')
        # Compare with interpolation of complex log magnitude and unwrapped phase.
        base_db=np.interp(np.log(half_raw.frequency),np.log(raw.frequency),20*np.log10(abs(gain)))
        base_phase=np.interp(np.log(half_raw.frequency),np.log(raw.frequency),np.unwrap(np.angle(gain)))
        db_error=20*np.log10(abs(half_gain))-base_db
        phase_error=np.degrees(np.angle(half_gain*np.exp(-1j*base_phase)))
        result['amplitude_check']=dict(f=half_raw.frequency.tolist(),db_error=db_error.tolist(),phase_error=phase_error.tolist(),
            passed=bool(np.max(abs(db_error))<1. and np.max(abs(phase_error))<8.))
        result['complete']=True;result['available']=result['amplitude_check']['passed']
        if not result['available']:result['error']='半幅复核差异超限；FRA 曲线仅展示，裕度待复核'
    except Exception as exc:
        from calculation_scheduler import CalculationCancelled
        if isinstance(exc,CalculationCancelled):raise
        result['error']=str(exc)
    result['wall_elapsed_s']=time.monotonic()-started
    return result


def corner_plan(rails,mode):
    n=len(rails);all_combinations=bool(mode or n<=3)
    if all_combinations:
        masks=[i^(i>>1) for i in range(2**n)]
    else:
        masks=list(dict.fromkeys([0,*[1<<i for i in range(n)],*[(2**n-1)^(1<<i) for i in range(n)],2**n-1]))
    combinations=[]
    for mask in masks:
        power=tuple(float(r['P_out_min'] if mask&(1<<i) else r['P_out']) for i,r in enumerate(rails))
        if power not in combinations:combinations.append(power)
    return combinations,'完整 min/max 全组合' if all_combinations else '重点角点，非完整全组合'


def run_cross(files,case,meta,settings,folder,execute,*,cancelled=lambda:False,progress=None):
    from isolated_outputs import output_specs
    from analysis_workflows import pin_hardware
    from power_stage import compute_operating_point
    from calculation_scheduler import CalculationCancelled
    from cross_regulation import summarize
    def solve_corner(parameters):
        # SPICE exports run on their own background thread, outside the normal
        # design-engine cancellation scope. Bind the same token while solving
        # each numerical corner, so cancellation interrupts the QR/RL solver.
        from input_voltage_range import _cancellation_scope
        with _cancellation_scope(cancelled):
            return compute_operating_point(parameters)
    quality=cycle_quality
    if meta.get('topology')=='QR-FLYBACK':
        from qr_spice_analysis import cycle_quality as quality
    p=matched_parameters(case,meta['resolved_controller']);rails=output_specs(p)
    if len(rails)<2:return dict(supported=False,error='单路输出无交叉调整率',records=[],summary=[])
    powers,coverage=corner_plan(rails,settings['cross_mode']);values=meta['resolved_controller'];fsw=values['FSW']
    hold=settings['cross_hold_ms']*1e-3;startup=max(settings['step_ms']*1e-3,.008)
    result=dict(supported=True,complete=False,simulation_complete=False,design_complete=False,
        coverage=coverage,records=[],summary=[],error=None,
        note='同一硬件与控制器；按名义匝比电压/功耗换算恒阻负载。取各角点末段平均电压，不用阶跃尖峰代替交叉调整率。未收敛、保护及真空载角点不进入包络。')
    result['varied_outputs']=[r['id'] for r in rails if r['P_out_min']!=r['P_out']]
    if not result['varied_outputs']:
        result['coverage']='没有配置轻载变化，仅一组负载'
        result['note']+='最小与最大功耗全部相同，0 跨度不能代表全负载交叉调整率为 0。'
    if hold<600/fsw:
        result['error']='每角点保持时间至少 600 个开关周期';return result
    count=len(powers);result['total_cases']=count
    stop=startup+(count-1)*hold;window_s=min(hold/3,max(200/fsw,.001))
    prepared=override_parameters(files,dict(LOAD_AFTER=1,TLOAD=1e6,TSTOP=stop))
    stage=prepared['power_stage.inc'].decode('ascii')
    for j,rail in enumerate(rails):
        terms=[f'{powers[0][j]/max(rail["P_out"],1e-30):.12g}']
        for k in range(1,count):
            ratio=(powers[k][j]-powers[k-1][j])/max(rail['P_out'],1e-30)
            terms.append(f'({ratio:.12g})*limit((time-{startup+(k-1)*hold:.12g})/1e-6,0,1)')
        stage=re.sub(r'(?m)^BLOAD'+str(j+1)+r' .*$',
            f'BLOAD{j+1} out{j+1} sgnd I=V(out{j+1},sgnd)/{{RLOAD{j+1}}}*('+'+'.join(terms)+')',stage)
    prepared['power_stage.inc']=stage.encode('ascii')
    analysis=[f'.options threads={int(settings["simulation_threads"])} method=gear reltol=0.003 plotwinsize=300\n.tran 0 {stop:.12g} 0 {1/fsw/40:.12g}',
        '.save V(gate) V(sense) V(drain) I(LP) V(fault) V(sgnd) '+' '.join(f'V(out{i+1})' for i in range(len(rails)))]
    for k in range(count):
        end=startup if k==0 else startup+k*hold
        for j in range(len(rails)):
            analysis.extend([f'.meas tran cross{k}_out{j+1} AVG V(out{j+1},sgnd) FROM {end-window_s:.12g} TO {end:.12g}',
                f'.meas tran cross{k}_early{j+1} AVG V(out{j+1},sgnd) FROM {end-2*window_s:.12g} TO {end-window_s:.12g}'])
    prepared['analysis.inc']=('\n'.join(analysis)+'\n').encode('ascii')
    write_study(folder,prepared,'# 交叉调整率角点瞬态\n\n以 Flyback.cir 运行。负载采用 Gray-code 顺序减少同时跳变；analysis.inc 定义每个角点的平均窗口。\n')
    try:
        result['elapsed_s']=execute(folder,settings['cross_timeout_s'])
        from spice_runtime import TransientRaw,read_log
        measured,_,errors,_=read_log(folder/'Flyback.log')
        if errors:raise ValueError('; '.join(errors))
        raw=TransientRaw(folder/'Flyback.raw')
        try:
            if not math.isclose(raw.time[-1],stop,abs_tol=1e-10):raise ValueError('交叉调整率瞬态没有到达结束时刻')
            result['simulated_cases']=count
            result['waveform']=raw.samples([f'v(out{i+1})' for i in range(len(rails))],0,stop,4000)
            for k,power in enumerate(powers):
                if cancelled():raise CalculationCancelled()
                end=startup if k==0 else startup+k*hold
                record=dict(id=f'X{k+1:03d}',V_in=case['voltage'],powers=list(power),start_s=0 if k==0 else end-hold,end_s=end,
                    simulation=None,design=None,error=None,settled=False)
                result['records'].append(record)
                voltages=[measured.get(f'cross{k}_out{i+1}') for i in range(len(rails))]
                earlier=[measured.get(f'cross{k}_early{i+1}') for i in range(len(rails))]
                fault=float(max(raw.trace('v(fault)')[np.searchsorted(raw.time,end-2*window_s):np.searchsorted(raw.time,end)],default=0))
                if any(v is None or not math.isfinite(v) for v in voltages+earlier):
                    record['error']='角点测量缺失或非有限值';continue
                drift=[100*abs(a-b)/max(abs(b),.01) for a,b in zip(earlier,voltages)]
                valid=max(drift)<=.25 and fault<.5 and min(power)>0
                record.update(simulation=voltages,drift_percent=drift,fault=fault,settled=valid,
                    error=None if valid else '真空载缺少泄放模型' if min(power)<=0 else '角点末段仍漂移或处于保护，未纳入包络')
                record['periodicity']=quality(raw,fsw,end-2*window_s,end,values['VG'],tolerance_pct=settings['cycle_tolerance_pct'])
                if meta.get('topology')=='QR-FLYBACK' and not record['periodicity'].get('stable'):
                    record.update(settled=False,error='QR角点未取得可重复的实际开关周期：'+
                        record['periodicity'].get('reason','周期检查未通过'))
                if min(power)<=0:continue
                q=copy.deepcopy(p)
                for rail,w in zip(q['outputs'],power):rail.update(P_out=w,P_out_min=min(rail['P_out_min'],w))
                q['P_out']=sum(power)
                try:
                    if q.get('topology')=='ACF-FORWARD':
                        if not q.get('coupling_config',{}).get('enabled'):raise ValueError('正激交叉调整率要求启用两两耦合矩阵周期计算')
                        op=solve_corner(q)
                        if not op.get('acf_model',{}).get('converged'):raise ValueError('没有正激物理周期解')
                        record.update(design=[float(c['V_out']) for c in op['output_ops']],
                            design_point=dict(duty=op['D'],modes=[c['mode'] for c in op['output_ops']],residual=op['acf_model']['normalized_residual']))
                        result['design_note']=op['acf_model']['assumptions']
                    elif q.get('topology')=='QR-FLYBACK':
                        if not q.get('coupling_config',{}).get('enabled'):
                            raise ValueError('QR交叉调整率计算需要启用非理想绕组耦合矩阵；名义匝比不是角点解')
                        op=solve_corner(q)
                        model=op.get('qr_coupled_model') or {}
                        if op.get('coupled_solution') is None or not model.get('converged'):
                            raise ValueError('QR角点没有已验证的变频耦合周期解，不用匝比电压替代')
                        record.update(design=[float(r['V_out']) for r in op['output_ops']],
                            design_point=dict(duty=op['D'],frequency_hz=op['f_sw'],
                                modes=[r.get('branch_mode',r['mode']) for r in op['output_ops']],
                                residual=model['normalized_residual'],
                                timing_policy=model.get('timing_policy'),valley_index=model.get('valley_index')))
                        assumptions=model['assumptions']
                        result['design_note']='；'.join(assumptions) if isinstance(assumptions,(list,tuple)) else str(assumptions)
                    else:
                        if not q.get('coupling_config',{}).get('enabled'):raise ValueError('计算器未启用耦合矩阵，不能给出交叉调整率计算值')
                        op=solve_corner(q)
                        if op.get('coupled_solution') is None:raise ValueError('计算器没有非理想耦合解')
                        record['design']=[float(r['V_out']) for r in op['output_ops']]
                except Exception as exc:
                    if isinstance(exc,CalculationCancelled):raise
                    record['design_error']=str(exc)
        finally:raw.close()
        if meta.get('topology') in ('ACF-FORWARD','QR-FLYBACK'):
            retry_cross_corners(result,files,meta,settings,folder,execute,rails,cancelled=cancelled,progress=progress)
    except Exception as exc:
        if isinstance(exc,CalculationCancelled):raise
        result['error']=str(exc)
    finalize_cross(result,rails,int(values['FB_SELECT']))
    return result


def finalize_cross(result,rails,feedback):
    from cross_regulation import summarize
    def valid_vector(value):
        return isinstance(value,(list,tuple)) and len(value)==len(rails) and all(
            isinstance(v,(int,float)) and not isinstance(v,bool) and math.isfinite(v) and v>0 for v in value)
    def records(kind):
        return [dict(id=r['id'],V_in=r['V_in'],powers=r['powers'],
            status='ok' if valid_vector(r.get(kind)) and min(r['powers'])>0 and
                (kind=='design' or r['settled']) else 'failed',voltages=r.get(kind)) for r in result['records']]
    result['summary']=dict(simulation=summarize(rails,records('simulation'),feedback),design=summarize(rails,records('design'),feedback))
    sim=records('simulation');design=records('design')
    result['settled_cases']=sum(r['status']=='ok' for r in sim)
    result['design_valid_cases']=sum(r['status']=='ok' for r in design)
    expected=int(result.get('total_cases',len(result['records'])))
    observed=expected>0 and len(result['records'])==expected
    varied=bool(result.get('varied_outputs'))
    result['simulation_complete']=bool(varied and observed and result['settled_cases']==expected)
    result['design_complete']=bool(varied and observed and result['design_valid_cases']==expected)
    result['complete']=result['simulation_complete'] and result['design_complete']
    # summarize() sees only received records, so a truncated scan could look
    # complete to it even though planned corners were never produced. Carry
    # the study's coverage check through to each reported envelope as well.
    for kind in ('simulation','design'):
        for row in result['summary'][kind]:
            row['complete']=bool(row['complete'] and result[kind+'_complete'])


def retry_cross_corners(result,files,meta,settings,folder,execute,rails,*,cancelled=lambda:False,progress=None):
    """Bounded independent long-startup checks, retaining failed scan evidence.

    Reuses physical hardware/loads/controller, never a fitted or rescaled trace.
    Each retry is separate so the RAW point/memory budget stays bounded.
    """
    from spice_runtime import TransientRaw,read_log
    from calculation_scheduler import CalculationCancelled
    import time
    fsw=meta['resolved_controller']['FSW'];vg=meta['resolved_controller']['VG']
    stop=min(max(settings['step_ms']*1e-3+3*settings['cross_hold_ms']*1e-3,.15),.2,50000/fsw)
    if stop<=settings['step_ms']*1e-3+1000/fsw:return
    failures=[r for r in result['records'] if not r['settled'] and min(r['powers'])>0][:3]
    for record in failures:
        if cancelled():raise CalculationCancelled()
        remaining=settings['cross_timeout_s']-result.get('elapsed_s',0.)
        if remaining<10:
            record['retry_error']='输入端点交叉调整率总超时预算已耗尽';continue
        if progress:progress(f'角点 {record["id"]} 独立长时间复核 {stop*1000:g} ms')
        if record.get('retry'):
            record.setdefault('retry_history',[]).append({k:record['retry'][k] for k in record['retry'] if k!='waveform'})
        attempt=len(record.get('retry_history',[]))+1
        retry=folder/('retry_'+record['id']+('_'+str(attempt) if attempt>1 else ''))
        prepared=override_parameters(files,dict(TSTOP=stop,TLOAD=1e6,LOAD_AFTER=1,SHORT_EN=0))
        stage=prepared['power_stage.inc'].decode('ascii')
        for i,(rail,power) in enumerate(zip(rails,record['powers']),1):
            stage=re.sub(r'(?m)^BLOAD'+str(i)+r' .*$',f'BLOAD{i} out{i} sgnd I=V(out{i},sgnd)/{{RLOAD{i}}}*{power/rail["P_out"]:.12g}',stage)
        prepared['power_stage.inc']=stage.encode('ascii')
        window=min(.002,stop/10)
        lines=[f'.options threads={int(settings["simulation_threads"])} method=gear reltol=0.003 plotwinsize=300',
            f'.tran 0 {stop:.12g} 0 {1/fsw/40:.12g}',
            '.save V(gate) V(sense) V(drain) I(LP) V(fault) V(sgnd) '+' '.join(f'V(out{i})' for i in range(1,len(rails)+1))]
        for i in range(1,len(rails)+1):
            lines += [f'.meas tran retry_out{i} AVG V(out{i},sgnd) FROM {stop-window:.12g} TO {stop:.12g}',
                f'.meas tran retry_early{i} AVG V(out{i},sgnd) FROM {stop-2*window:.12g} TO {stop-window:.12g}']
        prepared['analysis.inc']=('\n'.join(lines)+'\n').encode('ascii')
        write_study(retry,prepared,'# 独立角点长时间复核\n\n固定该组恒阻负载，从零启动，以末段 2ms 均值和前一窗口核对。原扫描波形未修改；最终角点值来自本目录日志。\n')
        record.setdefault('initial_scan',{k:record.get(k) for k in ('simulation','drift_percent','fault','periodicity','error','settled')})
        raw=None
        started=time.monotonic()
        try:
            elapsed=execute(retry,remaining);m,_,errors,_=read_log(retry/'Flyback.log')
            if errors:raise ValueError('; '.join(errors))
            raw=TransientRaw(retry/'Flyback.raw')
            if not math.isclose(raw.time[-1],stop,abs_tol=1e-10):raise ValueError('角点复核未到结束时刻')
            values=[m[f'retry_out{i}'] for i in range(1,len(rails)+1)]
            earlier=[m[f'retry_early{i}'] for i in range(1,len(rails)+1)]
            drift=[100*abs(a-b)/max(abs(b),.01) for a,b in zip(earlier,values)]
            lo=np.searchsorted(raw.time,stop-2*window);fault=float(np.max(raw.trace('v(fault)')[lo:]))
            quality=cycle_quality
            if meta.get('topology')=='QR-FLYBACK':
                from qr_spice_analysis import cycle_quality as quality
            periodicity=quality(raw,fsw,stop-2*window,stop,vg,tolerance_pct=settings['cycle_tolerance_pct'])
            valid=max(drift)<=.25 and fault<.5 and (meta.get('topology')!='QR-FLYBACK' or periodicity.get('stable',False))
            record['retry']=dict(folder=retry.name,elapsed_s=elapsed,stop_s=stop,window_s=window,
                waveform=raw.samples([f'v(out{i})' for i in range(1,len(rails)+1)],0,stop,3000),passed=valid)
            record.update(simulation=values,drift_percent=drift,fault=fault,settled=valid,
                periodicity=periodicity,
                error=None if valid else '独立长时间角点复核仍未收敛或处于保护')
        except CalculationCancelled:raise
        except Exception as exc:record['retry_error']=str(exc)
        finally:
            if raw is not None:raw.close()
            result['elapsed_s']=result.get('elapsed_s',0.)+time.monotonic()-started
            result['time_includes_retries']=True
