"""QR export adapter. Reuses the frozen power stage, never the PWM clock."""
import copy
import hashlib
import json
import math
import re

MODEL_VERSION='GenericQR-L6565-1.0'
CONTROL_KEYS=('A_CS','CS0','VFF','VSET','TSS','TYPE','KP','FZ1','FP1','FZ2','FP2','RDRV','VG',
    'UVON','UVOFF','TLEB','TONMIN','TPROP','CS_TAU','ZARM','ZTRIG','ZDELAY','TOFFMIN','TOFFLIGHT','TSTART','OCP','TONMAX')


def project_files(parameters,*,bundle=None):
    from app_resources import resource_path
    from spice_export import project_files as fixed_project,normalize_settings,_json
    from design_engine.service import calculate_parameters
    p=copy.deepcopy(parameters);settings=normalize_settings(p.get('spice_config'))
    if p.get('feedback_mode','SSR')!='SSR' or p.get('control_mode')!='Peak Current Mode':
        raise ValueError('QR 仿真目前支持峰值电流模式、单路 SSR；PSR 不可套用 SSR 模型')
    if p.get('outputs'):
        raise ValueError('首版 QR 仿真仅支持单路输出；多路 QR 的退磁与跳谷尚未验证')
    if bundle is None:bundle=calculate_parameters(p,analysis='endpoints',include_loop=False,include_cross_regulation=False).runtime_bundle()
    if not bundle.get('cases') or any(c.get('error') for c in bundle['cases']):
        raise ValueError('QR 端点计算失败：'+'; '.join(str(c.get('error')) for c in bundle.get('cases',[]) if c.get('error')))
    if any(c.get('p',{}).get('topology')!='QR-FLYBACK' for c in bundle['cases']):
        raise ValueError('QR 导出必须使用同一 QR 拓扑的计算快照')
    first=bundle['cases'][0];q=first['p'];op=first['result']['op']
    from parasitics import resolved
    cds=resolved(dict(q,spice_config=settings),1)['coss']
    c_res=cds+resolved(dict(q,spice_config=settings),1)['cw_primary']
    if cds<=0:raise ValueError('QR 需要正的有效漏极谐振电容；请填写 qr_cds_pf 或设计 Coss')
    if settings['qr_vcc_v']<=settings['qr_uvlo_on_v']:raise ValueError('QR 理想 VCC 必须高于启动阈值')
    if settings['qr_ocp_v']<=settings['qr_cs_clamp_v']:raise ValueError('QR 异常 CS 阈值必须高于逐周期钳位')
    # The existing exporter supplies only the hardware, fixture and measurements.
    # Every controller card and the fixed-clock library interface is replaced below.
    ref_frequency=float(op['f_sw'])
    base=copy.deepcopy(p);base['topology']='FLYBACK'
    base['spice_config']=dict(settings,frequency_hz=ref_frequency,short_mode=0,soft_start_mode=0,
        cs_limit=settings['qr_cs_clamp_v'],slope_mode=2,slope=0,comp_offset_v=0.,comp_voltage_max=0.)
    files=fixed_project(base,bundle=bundle);meta=json.loads(files['manifest.json']);v=meta['resolved_controller']
    v.update(FSW=ref_frequency,CS0=settings['qr_cs_clamp_v'],VFF=settings['qr_vff_v'],
        UVON=settings['qr_uvlo_on_v'],UVOFF=settings['qr_uvlo_off_v'],
        TLEB=settings['blanking_ns']*1e-9,ZARM=settings['qr_zcd_arm_v'],ZTRIG=settings['qr_zcd_trigger_v'],
        ZDELAY=(max(0.,math.pi/2*math.sqrt(float(q['L'])*c_res)-settings['delay_ns']*1e-9) if settings['qr_zcd_delay_ns']==-1 else settings['qr_zcd_delay_ns']*1e-9),TOFFMIN=settings['qr_off_min_us']*1e-6,
        TOFFLIGHT=settings['qr_off_light_us']*1e-6,TSTART=settings['qr_starter_us']*1e-6,
        OCP=settings['qr_ocp_v'],TONMAX=settings['qr_max_on_us']*1e-6,
        QR_VCC=settings['qr_vcc_v'],Z_RATIO=settings['qr_aux_ratio'],Z_R=settings['qr_zcd_r'],
        Z_C=settings['qr_zcd_c_pf']*1e-12,Q_COSS=cds,CS_LIM=settings['qr_cs_clamp_v']*(1-settings['qr_vff_v']/3),
        SLOPE=0.,COFF=0.,FSW_LIMIT=float(q['f_sw']))
    inc=files['design_params.inc'].decode('ascii')
    for key,value in v.items():
        pattern=r'(?m)^\.param '+key+r'=[^\r\n]*'
        card=f'.param {key}={value:.12g}'
        inc=re.sub(pattern,card,inc) if re.search(pattern,inc) else inc+'\n'+card
    files['design_params.inc']=(inc+'\n').encode('ascii')
    stage=files['power_stage.inc'].decode('ascii')
    stage=stage.replace('VCC_SOURCE vcc 0 {VG}','VCC_SOURCE vcc 0 {QR_VCC}')
    stage=re.sub(r'(?m)^XU_CTRL .*$',
        'XU_CTRL fb sense en vcc gate comp ramp ss fault 0 zcd GQR_CTRL '+' '.join(k+'={'+k+'}' for k in CONTROL_KEYS),stage)
    stage+='\nXZCD drain vin_bus zcd 0 GQR_ZCD RATIO={Z_RATIO} RZ={Z_R} CZ={Z_C}\n'
    files['power_stage.inc']=stage.encode('ascii')
    files['Flyback.cir']=files['Flyback.cir'].replace(b'Generic configurable closed-loop flyback',b'Event-driven QR flyback - L6565 inspired').replace(b'.include power_stage.inc',b'.include GenericQR_L6565.lib\n.include power_stage.inc')
    files['analysis.inc']+=b'\n.save V(zcd) V(vcc)\n'
    library=resource_path('resources/spice/GenericQR_L6565.lib').read_bytes()
    files['GenericQR_L6565.lib']=library
    meta.update(model_version=MODEL_VERSION,library_sha256=hashlib.sha256(library).hexdigest(),
        topology='QR-FLYBACK',settings=settings,qr=dict(cds_f=cds,design_coss_f=q['Coss'],frequency_limit_hz=q['f_sw'],
            design_frequency_hz=ref_frequency,source='https://www.st.com/resource/en/datasheet/l6565.pdf',
            event_driven=True,auxiliary='unloaded-voltage-replica',gate_supply='ideal-configured-Vgs',
            note='FSW 只用于测量窗口与步长；不驱动时钟。VG 采用设计驱动电压，不模拟真实 VCC−压降。'))
    meta['approximation_notes']=[
        'L6565 逻辑参考的原创通用 QR 行为模型，不是 ST 官方晶体管级模型，也未直接套用用户参考库。',
        'ZCD 上升预备、下降触发，经 RC 与附加延时置位；按 COMP 调节关断消隐，轻载可跳谷。400µs 定时器仅在无触发时补发启动脉冲，不是固定频率时钟。',
        'CS 逐周期限流随 VFF 线性折减；异常 CS 超阈值锁存至 VCC 欠压。外部理想 VCC 不会自行跌落，故不能宣称已模拟 VCC 供电打嗝重启。',
        'SSR 采用计算器等效补偿传递函数与外部参考缓升；不模拟芯片 OTA、光耦/TL431 及真实启动供电。COMP 是放大后 CS 命令，芯片等效 COMP=2.5+3×COMP/(A_CS×CS0)。',
        f'有效漏极谐振电容 {cds*1e12:g} pF；设计原 Coss={q["Coss"]*1e12:g} pF。包含此处常数电容与器件结电容，不能当作实测 Coss(Vds)。',
        '驱动采用设计 VG，VCC 仅用于 UVLO 状态；最长导通看门狗属于模型安全约束。',
    ]+[n for n in meta['approximation_notes'] if '固定频率' not in n and '斜坡来源' not in n]
    files['manifest.json']=_json(meta).encode('utf-8')
    files['design.json']=_json(p).encode('utf-8')
    files['README.md']=('# QR 反激 / L6565 逻辑参考\n\n打开 Flyback.asc 或 Flyback.cir 运行。参数在 design_params.inc。\n'
        '主界面的 f_sw 是 QR 设计频率上限，不是本模型的开关时钟。观察 V(zcd)、V(gate,sense)、V(drain,sense)、I(LP)、I(LS1)。\n\n'
        +'\n'.join('- '+n for n in meta['approximation_notes'])+'\n').encode('utf-8')
    files.pop('Flyback.asc',None)
    template=resource_path('resources/spice/QR_Flyback_1.asc')
    if template.is_file():
        files['Flyback.asc']=template.read_bytes()
        if p.get('parasitic_config'):
            from parasitic_spice import schematic
            files['Flyback.asc']=schematic(files['Flyback.asc'],1)
    plot=resource_path('resources/spice/QR_Flyback_1.plt')
    if plot.is_file():files['Flyback.plt']=plot.read_bytes()
    guide=resource_path('docs/QR_L6565_SPICE.md')
    if guide.is_file():files['QR_MODEL_GUIDE.md']=guide.read_bytes()
    return files
