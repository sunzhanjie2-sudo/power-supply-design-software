"""Readable Buck/Boost switching decks sharing the comparison infrastructure."""
import copy
import hashlib
import json
from pathlib import Path

MODEL_VERSION='GenericBuckBoostPWM-1.0'

def project_files(parameters,*,bundle=None):
    from app_resources import resource_path
    from spice_export import normalize_settings,_json,_number
    from spice_circuit import CONTROL_KEYS,support_cards
    from nonisolated import profile,preset,effective,slope,is_enabled
    from plants import resolve_controller_type
    from capacitor_banks import normalize
    p=normalize(parameters);d=profile(p)
    if not is_enabled(p):
        raise ValueError('请先选择并应用 Buck/Boost 控制器参考配置，再重新计算。仿真与主界面必须使用同一物理模型。')
    settings=normalize_settings(p.get('spice_config'));p['spice_config']=settings
    if bundle is None:
        from design_engine.service import calculate_parameters
        bundle=calculate_parameters(p,analysis='endpoints',include_loop=False,include_cross_regulation=False).runtime_bundle()
    cases=bundle['cases']
    if not cases or any(c.get('error') or not c.get('result') for c in cases):raise ValueError('Buck/Boost 两端工况未计算成功')
    if any(not c['result']['op'].get('niso_model') for c in cases):raise ValueError('请先应用 Buck/Boost 控制器参考配置并重新计算，再导出仿真')
    q=effective(cases[0]['p']);op=cases[0]['result']['op'];m=op['niso_model'];buck=q['topology']=='BUCK'
    if q['Rs']<=0:raise ValueError('Buck/Boost 仿真电流保护与测量需要正的采样电阻 Rs')
    vmin=min(c['voltage'] for c in cases);vmax=max(c['voltage'] for c in cases)
    if vmin<d['vmin'] or vmax>d['vmax']:raise ValueError(f'{d["name"]} 输入电压超出本原型范围 {d["vmin"]:g}–{d["vmax"]:g} V')
    fs=settings['frequency_hz'] or q['f_sw'];s=slope(q)
    if settings['duty_max']/fs<=max(settings['blanking_ns'],settings['min_on_ns'])*1e-9+settings['delay_ns']*1e-9:raise ValueError('消隐和最小导通时间过长')
    block=q['Vf_dout'] if q.get('d_out_enable') else 0.;h=d['ref']/(q['V_out']+block)
    limit=settings['cs_limit'] or (1.4*max(c['result']['op']['I_sw_pk'] for c in cases)*q['Rs'])
    values=dict(FSW=fs,MODE=int(not(d['id']==1)),DMAX=settings['duty_max'],VM=q['Vm'],A_CS=1.,SLOPE=s,
        CS_LIM=limit,TBLANK=settings['blanking_ns']*1e-9,TONMIN=settings['min_on_ns']*1e-9,
        TPROP=settings['delay_ns']*1e-9,VG=q['Vgs'],RDRV=settings['driver_resistance'],UVLO=settings['uvlo'],
        VSET=d['ref'],TSS=settings['soft_start_ms']*1e-3,TYPE=2 if resolve_controller_type(q.get('controller_type','auto'),q['control_mode'])=='type2' else 3,
        TSTOP=settings['stop_ms']*1e-3,TLOAD=settings['step_ms']*1e-3,LOAD_AFTER=settings['load_after'],FB_SCALE=h,FB_SELECT=1,
        CMAX=(q['Vm'] if d['id']==1 else limit+s*settings['duty_max']/fs),TEN=settings['enable_delay_ms']*1e-3,
        SSMODE=settings['soft_start_mode'],SSFRAC=settings['soft_start_current_fraction'],COFF=0.,
        SSCLO=settings['ss_comp_start_v'],SSCHI=settings['ss_comp_end_v'],SCMODE=settings['short_mode'],SCP=settings['scp_threshold_v'],
        SCPBLANK=settings['scp_blanking_ns']*1e-9,OLPEN=settings['olp_enabled'],TOLP=settings['olp_ms']*1e-3,
        THOLD=settings['ocp_hold_us']*1e-6,TOFF=settings['hiccup_off_ms']*1e-3,CS_TAU=settings['cs_filter_ns']*1e-9,
        DIODE_CJ=settings['diode_cj_pf']*1e-12 if settings['niso_edge_model'] else 0.,SHORT_EN=settings['short_test'],SHORT_OUT=1,
        TSHORT=settings['short_start_ms']*1e-3,TSHORT_DUR=settings['short_duration_ms']*1e-3,SHORT_R=settings['short_resistance'],
        PHYS_OFFSET=d['offset'],PHYS_SCALE=d['scale'],LIMIT_RAMP=int(d['id']==3),RAMP_RATIO=settings['niso_ramp_ratio'])
    for key in ('kp','fz1','fp1','fz2','fp2'):values[key.upper()]=settings[key] or q['KP' if key=='kp' else key] or 1000.
    values['KP']/=h
    if settings['comp_voltage_max']:
        if settings['comp_voltage_max']<=d['offset']:raise ValueError('COMP/ITH 上限必须高于原型零电流偏置')
        values['CMAX']=min(values['CMAX'],(settings['comp_voltage_max']-d['offset'])*d['scale'])
    values['SSCLO']=max(0.,settings['ss_comp_start_v']-d['offset'])*d['scale']
    values['SSCHI']=max(0.,settings['ss_comp_end_v']-d['offset'])*d['scale']
    params={}
    def add(k,v):params[k]=float(v);return '{'+k+'}'
    def diode(ref,a,b,v,en=1):return f'X{ref} {a} {b} GPWR_DIODE VF={add(ref+"_VF",v)} ACT={add(ref+"_EN",en)} CJ={{DIODE_CJ}}'
    def cap(ref,a,b,c,r,l,en=1):return f'X{ref} {a} {b} GPWR_CAP C={add(ref+"_C",c)} ESR={add(ref+"_ESR",r)} ESL={add(ref+"_ESL",l if settings["include_cap_esl"] else 0)} ACT={add(ref+"_EN",en)}'
    body=['VIN_SOURCE input 0 {VIN}','VCC_SOURCE vcc 0 {VG}',
        'VEN en 0 PULSE(0 1 1e-6 10e-9 10e-9 {2*TSTOP} {3*TSTOP})','V_SECONDARY_REFERENCE sgnd 0 0',
        diode('D_IN','input','vin_bus',q['Vf_din'],int(q.get('d_in_enable',False))),
        cap('C_IN1','vin_bus','0',q['Cin1'],q['Rcin1'],q['ESLin1']),
        cap('C_IN2','vin_bus','0',q['Cin2'],q['Rcin2'],q['ESLin2'],int(q.get('cin2_enable',False)))]
    add('RSENSE',q['Rs']);add('L1',q['L']);add('RL1',m['dcr']);add('Q_RON',q['Rds_on']);add('Q_COSS',q['Coss'] if settings['niso_edge_model'] else 0.);add('Q_CG',q['Qg']/q['Vgs'] if settings['niso_edge_model'] else 0.)
    if buck:
        body+=['RS1 vin_bus qsource {RSENSE}','L1 sw cap1 {L1} Rser={RL1}',
            'XQ1 sw gate_pin qsource GNISO_PMOS RON={Q_RON} COSS={Q_COSS} CG={Q_CG} VG={VG} CJ={DIODE_CJ}',
            'BGATE gate_drive qsource V=-V(gate_cmd)', 'BCS sense 0 V=V(vin_bus,qsource)',
            'BVDRAIN drain sense V=V(qsource,sw)',diode('D_O1','sgnd','rect1',q['Vf_diode']),'V_D1 rect1 sw 0']
        reverse='V(rect1,sgnd)'
    else:
        body+=['L1 vin_bus sw {L1} Rser={RL1}','RS1 sense 0 {RSENSE}',
            'XQ1 sw gate_pin sense GNISO_NMOS RON={Q_RON} COSS={Q_COSS} CG={Q_CG} VG={VG} CJ={DIODE_CJ}',
            'BGATE gate_drive sense V=V(gate_cmd)','BVDRAIN drain sw V=0','V_D1 sw rect1 0',diode('D_O1','rect1','cap1',q['Vf_diode'])]
        reverse='V(cap1,rect1)'
    body+=['BGMON gate sense V=V(gate_cmd)',
        cap('C_O1','cap1','sgnd',q['C_out'],q['Rc'],q.get('ESL',0)),
        cap('C_O1_2','cap1','sgnd',q['C_out2'],q['Rc2'],q.get('ESL2',0),int(q.get('cout2_enable',False))),
        diode('D_OUT1','cap1','out1',q['Vf_dout'],int(q.get('d_out_enable',False))),
        'BLOAD1 out1 sgnd I=V(out1,sgnd)/'+add('RLOAD1',q['V_out']**2/q['P_out'])+'*(1+({LOAD_AFTER}-1)*limit((time-{TLOAD})/1e-6,0,1))',
        'XFBSEL cap1 sgnd sgnd sgnd sgnd sgnd sgnd fb 0 GPWR_FEEDBACK SEL={FB_SELECT} H={FB_SCALE}',
        'XU_CTRL fb sense en vcc gate_cmd comp ramp ss fault 0 GNISO_CTRL '+ ' '.join(k+'={'+k+'}' for k in CONTROL_KEYS)+' LIMIT_RAMP={LIMIT_RAMP}',
        'BPHYSICAL comp_pin 0 V={PHYS_OFFSET}+V(comp)/{PHYS_SCALE}']
    # Monitor/drive adapters are explicit in the supporting circuit; the sheet
    # shows a labelled driver adapter and the real MOS polarity.
    adapters=[l for l in body if l.startswith(('BGATE ','BCS ','BVDRAIN ','BGMON ','BPHYSICAL '))]
    body=[l for l in body if l not in adapters]
    support=support_cards(1)+adapters+['R_GATE gate_drive gate_pin {RDRV}','SSHORT1 out1 sgnd short1 0 SHORT_SW','BSHORT1 short1 0 V=if({SHORT_EN}>0.5,V(short_stim),0)']
    from spice_circuit import extra_capacitor_cards
    support+=extra_capacitor_cards(q,[q],settings)
    # The steady window is measured independently of plotting decimation.
    analysis=[f'.options threads={int(settings["simulation_threads"])} method=gear reltol=0.003 plotwinsize=300 plotreltol=1e-4',
        '.tran 0 {TSTOP} 0 {1/FSW/60}',
        '.save V(input) V(vin_bus) V(sw) V(rect1) V(qsource) V(gate_pin) V(comp_pin) V(drain) V(sense) V(gate) V(comp) V(ramp) V(ss) V(fault) V(duty_mon) I(L1) I(V_D1) V(out1) V(cap1) V(sgnd)',
        '.meas tran fault_max MAX V(fault) FROM 0 TO {TSTOP}',
        '.meas tran switching_period TRIG V(gate,sense) VAL={VG/2} RISE=2 TD={TLOAD-200/FSW} TARG V(gate,sense) VAL={VG/2} RISE=3 TD={TLOAD-200/FSW}',
        '.meas tran frequency_actual PARAM 1/switching_period']
    quantities={'duty_avg':('AVG','V(duty_mon)'),'input_voltage':('AVG','V(input)'),
        'primary_rms':('RMS','I(L1)'),'primary_avg':('AVG','I(L1)'),'primary_peak':('MAX','I(L1)'),
        'vcs_peak':('MAX','V(sense)'),'vds_peak':('MAX','V(drain,sense)'),
        'out1_before':('AVG','V(out1,sgnd)'),'out1_cap_before':('AVG','V(cap1,sgnd)'),
        'out1_pre_ripple':('PP','V(cap1,sgnd)'), 'out1_winding_rms':('RMS','I(V_D1)'),
        'out1_winding_peak':('MAX','I(V_D1)'),'out1_winding_avg':('AVG','I(V_D1)'),
        'out1_diode_reverse':('MAX',reverse)}
    quantities.update(sense_rms=('RMS','V(sense)'),sense_avg=('AVG','V(sense)'))
    for key,(method,expr) in quantities.items():analysis.append(f'.meas tran {key} {method} {expr} FROM {{TLOAD-200/FSW}} TO {{TLOAD-10/FSW}}')
    analysis+=['.meas tran switch_rms PARAM sense_rms/RSENSE','.meas tran switch_avg PARAM sense_avg/RSENSE','.meas tran switch_peak PARAM vcs_peak/RSENSE']
    analysis+=['.meas tran out1_earlier AVG V(out1,sgnd) FROM {TLOAD-400/FSW} TO {TLOAD-200/FSW}',
        '.meas tran out1_after AVG V(out1,sgnd) FROM {TSTOP-200/FSW} TO {TSTOP-10/FSW}',
        '.meas tran out1_ripple PP V(out1,sgnd) FROM {TSTOP-200/FSW} TO {TSTOP-10/FSW}',
        '.meas tran out1_load_min MIN V(out1,sgnd) FROM {TLOAD} TO {TSTOP}',
        '.meas tran out1_load_max MAX V(out1,sgnd) FROM {TLOAD} TO {TSTOP}']
    if not buck:analysis=[l.replace(' V(qsource)','') for l in analysis]
    inc=['* SI values; normalized comparator domain; physical COMP/ITH monitor is comp_pin.']
    inc += [f'.param {key}={_number(v)}' for key,v in dict(values,**params,VIN=vmin).items() if key!='VM']
    inc.append('.param VM={RAMP_RATIO*(VIN-D_IN_EN*D_IN_VF)}' if d['id']==1 else f'.param VM={_number(q["Vm"])}')
    if vmax!=vmin:inc.append(f'.step param VIN list {vmin:.12g} {vmax:.12g}')
    library=resource_path('resources/spice/GenericFlybackPWM.lib').read_bytes()
    extra=resource_path('resources/spice/GenericBuckBoostPWM.lib').read_bytes()
    extra=extra.replace(b'GNISO_CTRL_FULL' if settings['short_mode'] else b'GNISO_CTRL_FAST',b'GNISO_CTRL')
    notes=[d['name']+'：原创可配置行为模型；未包含或验证独立原厂模型。',
        '反馈在输出防反管前，输出在防反管后；电感 DCR 来自同一冻结几何或显式覆盖。两颗电容分别保留 ESR。',
        '补偿器为二／三型行为网络，CS 等效域与 COMP/ITH 管脚域分开显示；不宣称真实误差放大器输出阻抗、gm、温漂或全部芯片保护。',
        ('电流及环路计算使用无边沿寄生的周期解；SPICE 保留常数 Coss/Cj、门电容、延迟及消隐，因此高频极值可能不同。' if settings['niso_edge_model'] else '快速闭环与周期计算共同忽略结电容快边沿；SPICE 仍包含控制延迟和消隐，极值与环路仍可能存在差异。'),
        '软启动与可选打嗝／锁存均为通用可配置逻辑，非完整芯片保护复刻；LTC3864 未复刻 Burst、短路降频与 OVP。',
        'TPS40200 斜坡随输入电压按配置比例变化；LTC3864 ITH→CS 的默认 0.05 V/V 是可修改近似，95 mV 仅为限流。',
        'LM5022 比较器保留 COMP 1.4 V 偏置及 3:1 转换，斜坡同时进入 PWM 和 0.5 V 逐周期限制。',
        'Boost 关闭 MOS 后输入仍会经电感、二极管给输出供电；短路保护不等于输入断路。',
        '电感为线性模型，不含饱和和磁芯损耗；电容 ESL 可选；二极管未建反向恢复；单路不适用交叉调整率，报告保留负载阶跃与输入两端对比。']
    notes.append('当前为快速闭环模式：Coss、Cj、等效栅电容关闭，不用于开关尖峰或器件动态损耗验证。' if not settings['niso_edge_model'] else '当前为常数结电容边沿模式，求解较慢；仍未包含电压相关电容与二极管恢复。')
    hardware=dict(kind='single-inductor',inductor=m['inductor'],L=q['L'],R_dc_p=m['dcr'],windings=[dict(id=1,Ns=0,R_dc=0,role='output-no-transformer')])
    meta=dict(schema='powerdesign-ltspice-1',model_version=MODEL_VERSION,topology=q['topology'],niso=d,
        controller_mode=q['control_mode'],feedback_output=1,settings=settings,resolved_controller=values,hardware=hardware,
        slope=dict(design=q.get('ma_slope',0)*q['Rs'],recommended=s,resolved=s),voltages=sorted(set(c['voltage'] for c in cases)),
        library_sha256=hashlib.sha256(library+extra).hexdigest(),approximation_notes=notes,
        voltage_nodes=dict(output='after-output-blocking-diode',feedback='capacitor-before-output-blocking-diode',feedback_reference=q['V_out']+block,port_target=q['V_out']))
    deck='Buck/Boost configurable closed loop\n.include design_params.inc\n.include GenericFlybackPWM.lib\n.include GenericBuckBoostPWM.lib\n.include power_stage.inc\n.include coupling.inc\n.include support.inc\n.include analysis.inc\n.end\n'
    readme='# '+d['name']+'\n\n打开 Flyback.asc（兼容文件名，实际为 Buck/Boost 电路）或 Flyback.cir。无需 MCP/Python。\n\n'
    readme+='参数在 design_params.inc；实际电流 I(L1)、I(V_D1)；输出 V(out1)、反馈前 V(cap1)；\n'
    readme+='Buck P-MOS 实际 Vgs=V(gate_pin,qsource)，实际 Vds=V(sw,qsource)，均保留真实极性。\nBoost Vgs=V(gate_pin,sense)，Vds=V(sw,sense)。\n'
    readme+='gate/sense、drain/sense 是统一正幅度监视信号；comp 为比较器域，comp_pin 为 COMP/ITH 显示值。\n\n'+'\n'.join('- '+n for n in notes)+'\n'
    files={'Flyback.cir':deck.encode('ascii'),'GenericFlybackPWM.lib':library,'GenericBuckBoostPWM.lib':extra,
        'design_params.inc':('\n'.join(inc)+'\n').encode('ascii'),'power_stage.inc':('\n'.join(body)+'\n').encode('ascii'),
        'coupling.inc':b'* Non-isolated: no transformer or coupling.\n','support.inc':('\n'.join(support)+'\n').encode('ascii'),
        'analysis.inc':('\n'.join(analysis)+'\n').encode('ascii'),'manifest.json':_json(meta).encode('utf-8'),
        'README.md':readme.encode('utf-8'),'design.json':_json({k:v for k,v in p.items() if not k.startswith('_')}).encode('utf-8')}
    for source in resource_path('resources/spice').glob('*.asy'):files[source.name]=source.read_bytes()
    asc=resource_path('resources/spice/'+('Buck' if buck else 'Boost')+'.asc')
    if asc.is_file():files['Flyback.asc']=asc.read_bytes()
    if asc.with_suffix('.plt').is_file():files['Flyback.plt']=asc.with_suffix('.plt').read_bytes()
    guide=resource_path('docs/BUCK_BOOST_SPICE.md')
    if guide.is_file():files['MODEL_GUIDE.md']=guide.read_bytes()
    return files
