"""Portable, closed-loop LTspice flyback projects; no GUI/simulator dependency.

The switching deck is deliberately independent of the calculator's analytical
efficiency correction. It uses real winding resistance and a physical RCD.
"""
from __future__ import annotations

import copy
import hashlib
import json
import math
from pathlib import Path
import tempfile
import os
import zipfile

MODEL_VERSION = 'GenericFlybackPWM-3.1'
SETTINGS = {
    'duty_max': (.7, .05, .95, '最大占空比', ''),
    'blanking_ns': (100., 0., 2000., '前沿消隐', 'ns'),
    'min_on_ns': (100., 0., 2000., '最小导通时间', 'ns'),
    'delay_ns': (20., 1., 500., '比较器／锁存延时', 'ns'),
    'driver_resistance': (2., .01, 1000., '驱动输出串联电阻', 'Ω'),
    'uvlo': (4.5, .1, 100., '驱动供电欠压阈值', 'V'),
    'soft_start_ms': (1., .01, 100., '软启动时间', 'ms'),
    'stop_ms': (12., .1, 5000., '仿真结束时间', 'ms'),
    'step_ms': (8., .05, 4999., '负载阶跃时刻', 'ms'),
    'load_after': (.5, .01, 2., '阶跃后／额定负载', ''),
    'feedback_scale': (1., .001, 1., '理想隔离反馈比例', ''),
    'cs_limit': (0., 0., 10., 'Vcs 逐周期钳位，0=自动', 'V'),
    'slope': (-1., -1., 1e9, '手动补偿斜坡（手动模式生效）', 'V/s'),
    'slope_mode': (1.,0.,2.,'斜坡补偿来源',''),
    'cs_filter_ns': (0.,0.,1000.,'外部 CS 滤波时间常数','ns'),
    'comp_voltage_max': (0.,0.,20.,'COMP 最高电压，0=自动','V'),
    'kp': (0., 0., 1e9, '补偿 KP，0=沿用软件', ''),
    'fz1': (0., 0., 1e9, 'fz1，0=沿用软件', 'Hz'),
    'fp1': (0., 0., 1e9, 'fp1，0=沿用软件', 'Hz'),
    'fz2': (0., 0., 1e9, 'fz2，0=沿用软件', 'Hz'),
    'fp2': (0., 0., 1e9, 'fp2，0=沿用软件', 'Hz'),
    'include_cap_esl': (0., 0., 1., '电容 ESL：0=不含，1=包含', ''),
    'diode_cj_pf': (20., .1, 10000., '通用二极管等效结电容（假设）', 'pF'),
    'frequency_hz': (0., 0., 2e6, '芯片频率，0=跟随设计', 'Hz'),
    'soft_start_mode': (0., 0., 2., '软启动逻辑', ''),
    'soft_start_current_fraction': (.05, 0., 1., '软启动初始电流阈值比例', ''),
    'comp_offset_v': (0., 0., 10., 'COMP 零电流偏置', 'V'),
    'ss_comp_start_v': (1.5, 0., 20., 'COMP 软启动钳位起点', 'V'),
    'ss_comp_end_v': (3.5, 0., 20., 'COMP 软启动钳位终点', 'V'),
    'enable_delay_ms': (0., 0., 100., '使能到允许开关延时', 'ms'),
    'short_mode': (0., 0., 2., '短路保护逻辑', ''),
    'scp_threshold_v': (.30, .001, 10., 'SCP 原始 CS 阈值', 'V'),
    'scp_blanking_ns': (250., 0., 5000., 'SCP 消隐（模型假设）', 'ns'),
    'olp_enabled': (0., 0., 1., '启用持续 OCP 过载保护', ''),
    'olp_ms': (4.8, .001, 1000., '持续 OCP 判故障时间', 'ms'),
    'ocp_hold_us': (50., .1, 10000., 'OCP 脉冲保持窗口', 'µs'),
    'hiccup_off_ms': (340., .01, 5000., '打嗝关断后重试时间', 'ms'),
    'short_test': (0., 0., 1., '启用输出短路注入测试', ''),
    'short_output': (1., 1., 6., '短路测试输出编号', ''),
    'short_start_ms': (6., .001, 4999., '短路注入开始时间', 'ms'),
    'short_duration_ms': (2., .001, 5000., '短路持续时间', 'ms'),
    'short_resistance': (.01, .001, 10., '短路等效电阻', 'Ω'),
    'simulation_timeout_s': (180., 10., 1800., '每工况仿真超时', 's'),
    'simulation_threads': (2.,1.,8.,'LTspice 最大线程数',''),
    'comparison_tolerance_pct': (5., .1, 100., '对比偏差提示阈值', '%'),
    'cycle_tolerance_pct': (5.,1.,30.,'逐周期重复性阈值','%'),
    'fra_enabled': (1.,0.,1.,'实际开关闭环 FRA 对比',''),
    'fra_start_hz': (500.,20.,1e5,'FRA 起始频率','Hz'),
    'fra_stop_hz': (25000.,100.,2e5,'FRA 结束频率','Hz'),
    'fra_oct': (2.,1.,4.,'FRA 每倍频程点数',''),
    'fra_amplitude_pct': (.2,.01,2.,'FRA 注入峰峰值／反馈电压','%'),
    'fra_cycles': (500.,100.,3000.,'FRA 每频点最少开关周期',''),
    'fra_timeout_s': (600.,30.,3600.,'每端点 FRA 超时','s'),
    'cross_enabled': (1.,0.,1.,'交叉调整率瞬态角点对比',''),
    'cross_mode': (0.,0.,1.,'交叉调整率角点覆盖',''),
    'cross_hold_ms': (8.,2.,500.,'每个负载角点保持时间','ms'),
    'cross_timeout_s': (1200.,30.,3600.,'每端点交叉调整率超时','s'),
}

from qr_spice_settings import QR_SETTINGS
SETTINGS.update(QR_SETTINGS)
from acf_spice import SETTINGS as ACF_SETTINGS
SETTINGS.update(ACF_SETTINGS)
from nonisolated import SETTINGS as NISO_SETTINGS
SETTINGS.update(NISO_SETTINGS)

CHOICES = {
    'niso_profile': {0:'未启用（沿用原计算）',1:'TPS40200 · Buck 电压模式',2:'LTC3864 · Buck 峰值电流',3:'LM5022 · Boost 峰值电流'},
    'niso_edge_model': {0:'快速闭环：不含结电容尖峰',1:'常数 Coss / Cj 开关边沿'},
    'soft_start_mode': {0:'输出参考缓升',1:'CS 限流阈值缓升',2:'COMP 上限缓升（MP6005 SSR 思路）'},
    'short_mode': {0:'仅逐周期限流',1:'故障关断后打嗝重启',2:'故障锁存至关闭使能'},
    'olp_enabled': {0:'关闭',1:'开启'}, 'short_test': {0:'关闭',1:'开启'},
    'include_cap_esl': {0:'快速验证 不含 ESL',1:'详细模型 包含 ESL'},
    'slope_mode': {0:'跟随设计计算值',1:'自动工程建议值（非芯片实测）',2:'手动设置，0 表示禁用'},
    'fra_enabled': {0:'关闭',1:'开启'},'cross_enabled': {0:'关闭',1:'开启'},
    'cross_mode': {0:'三路以内全组合，更多路采用重点角点',1:'所有 min/max 负载组合（耗时较长）'},
}


def mp6005_preset(current=None):
    """Datasheet Rev1.1 pp5/6/18; configurable reference, not a silicon model."""
    value=dict(current or {})
    value.update(frequency_hz=250e3,soft_start_mode=2,soft_start_ms=4.7,
        comp_offset_v=1.5,ss_comp_start_v=1.5,ss_comp_end_v=3.5,enable_delay_ms=.5,
        cs_limit=.16,blanking_ns=250,min_on_ns=250,duty_max=.7,
        short_mode=1,scp_threshold_v=.30,scp_blanking_ns=250,
        olp_enabled=1,olp_ms=4.8,ocp_hold_us=50,hiccup_off_ms=340,
        slope_mode=1,cs_filter_ns=15,comp_voltage_max=5.)
    value['step_ms']=max(value.get('step_ms',8),12.)
    value['stop_ms']=max(value.get('stop_ms',12),18.)
    return normalize_settings(value)


def setting_group(key):
    if key.startswith('niso_'):return 'Buck / Boost 原型'
    if key.startswith('acf_'):return '有源钳位与 SYNC'
    if key.startswith('qr_'):return '准谐振与 ZCD'
    if key in ('frequency_hz','duty_max','blanking_ns','min_on_ns','delay_ns','driver_resistance','uvlo','cs_limit','slope_mode','slope','cs_filter_ns'):return '频率与 PWM'
    if key in ('soft_start_mode','soft_start_ms','soft_start_current_fraction','comp_offset_v','ss_comp_start_v','ss_comp_end_v','enable_delay_ms'):return '软启动逻辑'
    if key in ('short_mode','scp_threshold_v','scp_blanking_ns','olp_enabled','olp_ms','ocp_hold_us','hiccup_off_ms'):return '短路与过载保护'
    if key in ('stop_ms','step_ms','load_after','short_test','short_output','short_start_ms','short_duration_ms','short_resistance','simulation_timeout_s','simulation_threads','comparison_tolerance_pct'):return '测试与对比报告'
    if key.startswith(('fra_','cross_')) or key=='cycle_tolerance_pct':return '环路与交叉调整率'
    return '补偿与寄生'


def ordered_setting_keys():
    groups=('Buck / Boost 原型','准谐振与 ZCD','有源钳位与 SYNC','频率与 PWM','软启动逻辑','短路与过载保护','测试与对比报告','环路与交叉调整率','补偿与寄生')
    return sorted(SETTINGS,key=lambda k:(groups.index(setting_group(k)),0 if k=='frequency_hz' else 1,list(SETTINGS).index(k)))


def normalize_settings(value=None):
    if value is None:
        value = {}
    if not isinstance(value, dict) or set(value) - set(SETTINGS):
        raise ValueError('SPICE 设置含未知字段，或不是对象')
    result = {}
    for key, (default, lo, hi, label, _) in SETTINGS.items():
        number = value.get(key, default)
        if isinstance(number, bool) or not isinstance(number, (int, float)) or not math.isfinite(number) or not lo <= number <= hi:
            raise ValueError(f'{label} 必须为 {lo:g} 至 {hi:g} 的有限数值')
        result[key] = float(number)
    if 'slope' in value and value['slope']>=0 and 'slope_mode' not in value:result['slope_mode']=2.
    if -1<result['niso_inductor_dcr']<0:raise ValueError('电感 DCR 只接受 -1（几何计算）或非负值')
    if result['slope'] < 0 and result['slope'] != -1:
        raise ValueError('斜坡只接受 -1（自动）或非负数')
    if result['slope_mode']==2 and result['slope']<0:raise ValueError('手动斜坡模式需填写非负斜率')
    if result['fra_start_hz']>=result['fra_stop_hz']:raise ValueError('FRA 结束频率必须大于起始频率')
    if result['include_cap_esl'] not in (0.,1.):
        raise ValueError('电容 ESL 开关只能为 0 或 1')
    for key in (*CHOICES,'short_output','fra_oct','fra_cycles','simulation_threads'):
        if int(result[key])!=result[key] or (key in CHOICES and int(result[key]) not in CHOICES[key]):
            raise ValueError(SETTINGS[key][3]+' 必须使用给定选项')
    if result['ss_comp_end_v']<=result['ss_comp_start_v']:
        raise ValueError('COMP 软启动终点必须大于起点')
    if result['short_mode'] and result['cs_limit'] and result['scp_threshold_v']<=result['cs_limit']:
        raise ValueError('SCP 阈值应大于逐周期限流阈值')
    if result['short_test'] and result['short_start_ms']>=result['stop_ms']:
        raise ValueError('短路注入开始时间必须早于仿真结束')
    if not result['soft_start_ms'] < result['step_ms'] < result['stop_ms']:
        raise ValueError('时间必须满足：软启动 < 负载阶跃 < 仿真结束')
    if result['qr_zcd_arm_v']<=result['qr_zcd_trigger_v']:raise ValueError('ZCD 预备阈值必须高于触发阈值')
    if result['qr_zcd_delay_ns']<0 and result['qr_zcd_delay_ns']!=-1:raise ValueError('QR 延时只接受 -1 自动估算或非负值')
    if result['qr_uvlo_on_v']<=result['qr_uvlo_off_v']:raise ValueError('VCC 启动阈值必须高于关断阈值')
    return result


def _number(value):
    number = float(value)
    if not math.isfinite(number):
        raise ValueError('不能将非有限数值写入 SPICE')
    return f'{number:.12g}'


def _json(value):
    from design_engine.contracts import json_value
    return json.dumps(json_value(value), ensure_ascii=False, allow_nan=False, indent=2) + '\n'


def project_files(parameters, *, bundle=None):
    from capacitor_banks import normalize
    parameters=normalize(parameters)
    """Return an owned filename->bytes map. Never executes untrusted SPICE text."""
    from app_resources import resource_path
    from isolated_outputs import output_specs, RAIL_KEYS
    from winding_coupling import resolve_winding_geometry, resolve_winding_model
    from plants import resolve_controller_type
    p = copy.deepcopy(parameters)
    if p.get('topology') in ('BUCK','BOOST'):
        from nonisolated_spice import project_files as nonisolated_project
        return nonisolated_project(p,bundle=bundle)
    if p.get('topology') == 'QR-FLYBACK':
        from qr_spice_export import project_files as qr_project
        return qr_project(p,bundle=bundle)
    forward = p.get('topology') == 'ACF-FORWARD'
    if p.get('topology') not in ('FLYBACK','ACF-FORWARD') or p.get('feedback_mode', 'SSR') != 'SSR':
        raise ValueError('LTspice 支持反激／有源钳位正激 SSR 闭环；PSR 尚未实现')
    if p.get('control_mode') not in ('Peak Current Mode','Voltage Mode'):
        raise ValueError('控制模式必须为 Peak Current Mode 或 Voltage Mode')
    settings = normalize_settings(p.get('spice_config'))
    if bundle is None:
        from design_engine.service import calculate_parameters
        bundle = calculate_parameters(p, analysis='endpoints', include_loop=False,
            include_cross_regulation=False).runtime_bundle()
    if not bundle.get('cases') or any(c.get('error') or not c.get('result') for c in bundle['cases']):
        raise ValueError('当前端点计算失败，无法导出完整仿真工程')
    if forward and any(c.get('p',{}).get('topology')!='ACF-FORWARD' for c in bundle['cases']):
        raise ValueError('正激导出必须使用同一正激拓扑的计算快照')
    first = bundle['cases'][0]
    q = copy.deepcopy(first['p'])  # same frozen Vinmin hardware at both voltages
    rails = output_specs(q) or [dict({key: q.get(key) for key in RAIL_KEYS}, name='OUT1', id=1)]
    op = first['result']['op']
    geometry = (op.get('acf_model') or {}).get('transformer_hardware') or resolve_winding_geometry(q, op, rails)
    notes = [
        '通用固定频率 SSR 行为模型，不代表 MP6005 或其他芯片的内部精确实现。',
        '主开关为 Ron + 常数 Coss + 等效门电容的开关模型；未复用 Id–Vgs / Vgs–Qg 作为完整晶体管模型。',
        '二极管采用固定正向压降和通用等效结电容；该电容是假设值，不是已选器件实测参数，不含反向恢复或温度模型。',
        '隔离反馈为理想受控源，不含光耦/TL431 延时和寄生；需自行替换再评估环路。',
        '磁芯采用线性电感，不含饱和、磁滞与磁芯损耗；DCR 来自已冻结的 MLT、匝数、线径和股数。',
        '预设效率用于计算器设计估算，未重复乘入物理 SPICE 电压或电流；两者数值不保证一致。',
        '负载为电阻；阶跃时所有输出同时按同一比例变化。此文件不构成完整交叉调整率角点扫描。',
        '普通 .ac 不适用于此开关闭环模型；本工程提供瞬态验证，未生成或宣称 FRA 结果。',
    ]
    if op.get('acf_model'):
        notes=[s for s in notes if not s.startswith('预设效率用于')]
        notes.append('计算器已启用正激物理周期模型：同一 kij、几何 DCR、钳位与输出电感，不重复叠加预设效率。理想门极边沿、恒定寄生和刚性电容端等差异仍保留。')
    notes.append('电容 ESR 保留；'+('包含用户电容 ESL，采用串联寄生电容模型。' if settings['include_cap_esl'] else
        '当前为闭环快速验证设置，未包含电容 ESL；高频应力/纹波尖峰不宜据此签核。'))
    if q.get('coupling_config', {}).get('enabled'):
        matrix = resolve_winding_model(q, rails, geometry=geometry, nominal_op=op)
        kvals = matrix['K'].tolist()
        coupling_source = 'user-pairwise-kij'
    else:
        legacy_k = float(q.get('K', .99))
        if not 0 < legacy_k <= 1:
            raise ValueError('历史漏感系数 K 必须满足 0 < K ≤ 1')
        kij = math.sqrt(legacy_k)
        kvals = [[1. if i == j else kij for j in range(len(rails)+1)] for i in range(len(rails)+1)]
        coupling_source = 'uniform-sqrt-legacy-K'
        notes.append('未启用 kij 矩阵：统一取 kij=√K。单副边时匹配 Lσ=(1−K)Lp；多副边仅为默认近似，应输入实测矩阵。')
    frequency = settings['frequency_hz'] or float(q['f_sw'])
    if frequency <= 0 or settings['duty_max']/frequency <= max(settings['blanking_ns'], settings['min_on_ns'])*1e-9 + settings['delay_ns']*1e-9:
        raise ValueError('消隐／最小导通／延时相对于开关周期过大')
    selected = int(q.get('feedback_output', 1))
    gain = float(q['A_sense'])
    rs = float(q['Rs'])
    if gain <= 0 or rs <= 0:
        raise ValueError('SPICE 电流保护需要正的 Rs 和采样放大倍数')
    peak = max(float(c['result']['op']['I_sw_pk']) for c in bundle['cases'])
    current_limit = settings['cs_limit'] or 1.4*peak*rs
    if settings['short_mode'] and settings['scp_threshold_v']<=current_limit:
        raise ValueError('SCP 阈值必须高于解析后的逐周期 Vcs 阈值，请手动设置 cs_limit')
    if settings['short_test'] and settings['short_output']>len(rails):
        raise ValueError('短路测试所选输出不存在')
    design_slope=max(0.,float(q.get('ma_slope',0.)))*gain*rs
    # 0.75 of the largest secondary-reflected downslope, in the amplified CS domain.
    # This engineering starting point is exposed as such, never an MP6005 specification.
    reflected=max((float(r['V_out'])+float(r['Vf_diode'])+
        (float(r['Vf_dout']) if r.get('d_out_enable') else 0))*geometry['Np']/w['Ns']
        for r,w in zip(rails,geometry['windings']))
    recommended=.75*reflected/float(q['L'])*gain*rs
    if forward:
        recommended=.75*sum((r['V_out']+r['Vf_diode']+(r['Vf_dout'] if r.get('d_out_enable') else 0))
            /r['L']*w['Ns']/geometry['Np'] for r,w in zip(rails,geometry['windings']))*gain*rs
    slope=settings['slope'] if settings['slope_mode']==2 else max(design_slope,recommended) if settings['slope_mode']==1 and q['control_mode']=='Peak Current Mode' else design_slope
    if forward:
        from acf_spice import current_slope
        slope=current_slope(q,rails,geometry,settings)
    notes.append(f'斜坡来源模式 {int(settings["slope_mode"])}：设计 {design_slope:.6g} V/s；仿真 {slope:.6g} V/s；自动建议为反射下降斜率的 0.75 倍，不是 MP6005 数据表数值。')
    values = dict(FSW=frequency, MODE=1 if q['control_mode'] == 'Peak Current Mode' else 0,
        DMAX=settings['duty_max'], VM=float(q['Vm']), A_CS=gain, SLOPE=slope,
        CS_LIM=current_limit, TBLANK=settings['blanking_ns']*1e-9,
        TONMIN=settings['min_on_ns']*1e-9, TPROP=settings['delay_ns']*1e-9,
        VG=float(q['Vgs']), RDRV=settings['driver_resistance'], UVLO=settings['uvlo'],
        TSS=settings['soft_start_ms']*1e-3, TSTOP=settings['stop_ms']*1e-3,
        TLOAD=settings['step_ms']*1e-3, LOAD_AFTER=settings['load_after'],
        FB_SCALE=settings['feedback_scale'], VSET=(rails[selected-1]['V_out']+
            (rails[selected-1]['Vf_dout'] if rails[selected-1].get('d_out_enable') else 0))*settings['feedback_scale'],
        TYPE=2 if resolve_controller_type(q.get('controller_type','auto'), q['control_mode']) == 'type2' else 3)
    for key in ('kp','fz1','fp1','fz2','fp2'):
        values[key.upper()] = settings[key] or float(q['KP' if key == 'kp' else key])
        if values['TYPE']==2 and key in ('fz2','fp2') and values[key.upper()]<=0:
            values[key.upper()] = 1000. if key=='fz2' else 80000.  # inactive state, never in type-II transfer
        if values[key.upper()] <= 0:
            raise ValueError(f'{key} 必须为正值，才能导出有限零极点的补偿器')
    # Calculator error signal is full output voltage. Scaling feedback must
    # preserve total loop gain rather than silently reducing it by FB_SCALE.
    values['KP'] /= settings['feedback_scale']
    values['CMAX'] = gain*current_limit + slope*settings['duty_max']/frequency if values['MODE'] else float(q['Vm'])
    if settings['comp_voltage_max']:
        if settings['comp_voltage_max']<=settings['comp_offset_v']:raise ValueError('COMP 最高电压必须高于零电流偏置')
        values['CMAX']=min(values['CMAX'],settings['comp_voltage_max']-settings['comp_offset_v'])
    values.update(TEN=settings['enable_delay_ms']*1e-3,SSMODE=settings['soft_start_mode'],
        SSFRAC=settings['soft_start_current_fraction'],COFF=settings['comp_offset_v'],
        SSCLO=settings['ss_comp_start_v'],SSCHI=settings['ss_comp_end_v'],
        SCMODE=settings['short_mode'],SCP=settings['scp_threshold_v'],
        SCPBLANK=settings['scp_blanking_ns']*1e-9,OLPEN=settings['olp_enabled'],
        TOLP=settings['olp_ms']*1e-3,THOLD=settings['ocp_hold_us']*1e-6,
        TOFF=settings['hiccup_off_ms']*1e-3,DIODE_CJ=settings['diode_cj_pf']*1e-12,
        SHORT_EN=settings['short_test'],SHORT_OUT=settings['short_output'],
        TSHORT=settings['short_start_ms']*1e-3,TSHORT_DUR=settings['short_duration_ms']*1e-3,
        SHORT_R=settings['short_resistance'],FB_SELECT=selected,CS_TAU=settings['cs_filter_ns']*1e-9)
    if forward:
        values.update(TDEAD=settings['acf_dead_ns']*1e-9 or float(q['forward_dead_time']),RSYNC=settings['acf_sync_resistance'])
        if 2*values['TDEAD']*frequency >= min(values['DMAX'],1-values['DMAX']):
            raise ValueError('正激死区过长，无法保留最大占空比下的钳位导通区间')
    if values['VG'] <= values['UVLO']:
        raise ValueError('驱动供电 VG 必须高于 UVLO')
    vin = sorted(set(float(c['voltage']) for c in bundle['cases']))
    inc = ['* User editable SI parameters. No units/Unicode suffix in numeric values.']
    inc += [f'.param {key}={_number(value)}' for key, value in values.items()]
    inc.append(f'.param VIN={_number(vin[0])}')
    if len(vin) > 1:
        inc.append('.step param VIN list ' + ' '.join(map(_number, vin)))
    from spice_circuit import render_stage,support_cards
    if forward:
        from acf_spice import render_stage
        body,power_parameters=render_stage(q,rails,geometry,kvals,settings)
    else:
        from flyback_clamp import rcd_components
        body,power_parameters=render_stage(q,rails,geometry,kvals,rcd_components(op,q),settings)
    inc += [f'.param {key}={_number(value)}' for key,value in power_parameters.items()]
    coupling=[line for line in body if line.startswith('K_')]
    from spice_circuit import extra_capacitor_cards
    support=support_cards(len(rails))+[line for line in body if line.startswith(('SSHORT','BSHORT'))]+extra_capacitor_cards(p,rails,settings)
    body=[line for line in body if not line.startswith(('K_','SSHORT','BSHORT'))]
    # Store a small, useful signal set, not all behavioral internal nodes.
    analysis = ['* Bounded waveform compression: review precision before sign-off.',
        f'.options threads={int(settings["simulation_threads"])} ' + ('' if settings['include_cap_esl'] else 'method=gear reltol=0.003 ') +
            'plotwinsize=300 plotreltol=1e-4 plotvntol=1e-5 plotabstol=1e-7',
        '.tran 0 {TSTOP} 0 {1/FSW/40}',
        '.save V(input) V(duty_mon) V(drain) V(sense) V(gate) V(comp) V(ramp) V(ss) V(fault) I(LP)',
        '.meas tran fault_max MAX V(fault) FROM 0 TO {TSTOP}',
        '.meas tran gate_mean AVG V(gate,sense) FROM {TLOAD-200/FSW} TO {TLOAD-10/FSW}',
        '.meas tran duty_avg AVG V(duty_mon) FROM {TLOAD-200/FSW} TO {TLOAD-10/FSW}',
        '.meas tran input_voltage AVG V(input) FROM {TLOAD-200/FSW} TO {TLOAD-10/FSW}',
        '.meas tran switching_period TRIG V(gate,sense) VAL={VG/2} RISE=2 TD={TLOAD-200/FSW} TARG V(gate,sense) VAL={VG/2} RISE=3 TD={TLOAD-200/FSW}',
        '.meas tran frequency_actual PARAM 1/switching_period',
        '.meas tran primary_rms RMS I(LP) FROM {TLOAD-200/FSW} TO {TLOAD-10/FSW}',
        '.meas tran primary_avg AVG I(LP) FROM {TLOAD-200/FSW} TO {TLOAD-10/FSW}',
        '.meas tran vcs_peak MAX V(sense) FROM {TLOAD-200/FSW} TO {TLOAD-10/FSW}']
    for i in range(1,len(rails)+1):
        analysis += [f'.save V(out{i}) V(cap{i}) V(rect{i}) V(sgnd) I(LS{i})',
            f'.meas tran out{i}_before AVG V(out{i},sgnd) FROM {{TLOAD-200/FSW}} TO {{TLOAD-10/FSW}}',
            f'.meas tran out{i}_cap_before AVG V(cap{i},sgnd) FROM {{TLOAD-200/FSW}} TO {{TLOAD-10/FSW}}',
            f'.meas tran out{i}_earlier AVG V(out{i},sgnd) FROM {{TLOAD-400/FSW}} TO {{TLOAD-200/FSW}}',
            f'.meas tran out{i}_pre_ripple PP V(cap{i},sgnd) FROM {{TLOAD-200/FSW}} TO {{TLOAD-10/FSW}}',
            f'.meas tran out{i}_winding_rms RMS I(LS{i}) FROM {{TLOAD-200/FSW}} TO {{TLOAD-10/FSW}}',
            f'.meas tran out{i}_winding_avg AVG I(LS{i}) FROM {{TLOAD-200/FSW}} TO {{TLOAD-10/FSW}}',
            f'.meas tran out{i}_winding_peak MAX I(LS{i}) FROM {{TLOAD-200/FSW}} TO {{TLOAD-10/FSW}}',
            f'.meas tran out{i}_diode_reverse MAX V(cap{i},rect{i}) FROM {{TLOAD-200/FSW}} TO {{TLOAD-10/FSW}}',
            f'.meas tran out{i}_after AVG V(out{i},sgnd) FROM {{TSTOP-200/FSW}} TO {{TSTOP-10/FSW}}',
            f'.meas tran out{i}_ripple PP V(out{i},sgnd) FROM {{TSTOP-200/FSW}} TO {{TSTOP-10/FSW}}',
            f'.meas tran out{i}_load_min MIN V(out{i},sgnd) FROM {{TLOAD}} TO {{TSTOP}}',
            f'.meas tran out{i}_load_max MAX V(out{i},sgnd) FROM {{TLOAD}} TO {{TSTOP}}']
    analysis += ['.meas tran primary_peak MAX I(LP) FROM {TLOAD-200/FSW} TO {TLOAD-10/FSW}',
        '.meas tran vds_peak MAX V(drain,sense) FROM {TLOAD-200/FSW} TO {TLOAD-10/FSW}']
    if forward:
        from acf_spice import extra_analysis
        for i in range(1,len(rails)+1):
            analysis=[s.replace(f'V(cap{i},rect{i})',f'V(choke{i},rect{i})').replace(f' I(LS{i}) FROM',f' (-I(LS{i})) FROM') for s in analysis]
        analysis += extra_analysis(len(rails))
    if values['TLOAD']<=420/frequency or values['TSTOP']-values['TLOAD']<=220/frequency:
        raise ValueError('阶跃前至少 420 周期，阶跃后至少 220 周期，用于稳态核对与测量')
    deck = '\n'.join(['Generic configurable closed-loop flyback',
        '.include design_params.inc', '.include GenericFlybackPWM.lib',
        '.include power_stage.inc', '.include coupling.inc', '.include support.inc', '.include analysis.inc', '.end',''])
    library = resource_path('resources/spice/GenericFlybackPWM.lib').read_bytes()
    metadata = dict(schema='powerdesign-ltspice-1',model_version=MODEL_VERSION,
        library_sha256=hashlib.sha256(library).hexdigest(), topology='FLYBACK',feedback='SSR',
        controller_mode=q['control_mode'], feedback_output=selected, voltages=vin,
        settings=settings, resolved_controller=values, hardware=geometry,
        voltage_nodes=dict(output='after-output-blocking-diode',feedback='capacitor-before-output-blocking-diode',
            feedback_reference=values['VSET']/values['FB_SCALE'],port_target=rails[selected-1]['V_out']),
        coupling=dict(source=coupling_source,k=kvals), slope=dict(design=design_slope,recommended=recommended,resolved=slope),approximation_notes=notes)
    readme = ('# 反激闭环 LTspice 工程\n\n'
        '解压到普通文件夹，在 LTspice 打开 `Flyback.asc` 或 `Flyback.cir`，点击 Run。无需安装 MCP 或 Python。\n'
        'ASC 原生展示输入、RCD、主 MOS、变压器各绕组、整流、电容、负载及闭环控制器，支持直接查看连线和器件。\n'
        '有 Vinmin/Vinmax 时一次运行两个 .step，使用 Select Steps 切换。\n\n'
        '参数入口：`design_params.inc`；CIR 功率连接：`power_stage.inc`；ASC 已直接放置这些元件，不能重复包含 power_stage.inc。\n'
        '互感在 coupling.inc，短路注入与监测在 support.inc，瞬态与测量在 analysis.inc。\n'
        '模型库可独立复制。GFLY_CTRL2 集成可配置软启动与保护；GPWM_CORE2 可接任意外部补偿器及电流钳位信号；GCOMP 为二/三型补偿。\n'
        '所有模型参数均为局部子电路参数。详细引脚、方程、修改示例见 `MODEL_GUIDE.md`。\n\n'
        '端口电压 V(outN,sgnd) 在防反管后；反馈固定取防反管前 V(capN,sgnd)。VSET=(主反馈端口目标+该路固定防反压降)×FB_SCALE；未启用防反管时两节点重合。\n'
        '查看 V(out1,sgnd)、V(cap1,sgnd)、V(gate,sense)、V(drain,sense)、I(LP)、I(LS1)、V(comp)、V(ramp)、V(ss)、V(fault)。SS=0..1，FAULT=1 表示保护关断。\n'
        'Ctrl+L 查看启动后、阶跃后平均电压／纹波／电流峰值等 .meas。测量失败或未达到仿真终点时不可采用。\n\n'
        '导出 ASC 工程不运行 LTspice；在软件里选“仿真与设计计算对比报告”才会实际运行，输出 Word 和包含日志的工程 ZIP。\n'
        'MP6005 SSR 参考配置仍可修改：OCP 160mV、SCP 300mV、软启动 4.7ms、OLP 4.8ms、重试关断 340ms。SCP 消隐是可配置假设。\n'
        '若仿真结束早于 340ms 关断期，只能观察关断，不能据此宣称已观察到打嗝重启。\n\n'
        '## 模型边界\n\n' + '\n'.join('- '+n for n in notes) + '\n')
    files = {'Flyback.cir':deck.encode('ascii'), 'design_params.inc': ('\n'.join(inc)+'\n').encode('ascii'),
        'power_stage.inc': ('\n'.join(body)+'\n').encode('ascii'),
        'support.inc': ('\n'.join(support)+'\n').encode('ascii'),
        'coupling.inc': ('\n'.join(coupling)+'\n').encode('ascii'),
        'analysis.inc': ('\n'.join(analysis)+'\n').encode('ascii'),
        'GenericFlybackPWM.lib':library, 'manifest.json':_json(metadata).encode('utf-8'),
        'design.json':_json({k:v for k,v in p.items() if not k.startswith('_')}).encode('utf-8'),
        'README.md':readme.encode('utf-8')}
    guide = resource_path('docs/FLYBACK_SPICE.md')
    if guide.is_file():
        files['MODEL_GUIDE.md'] = guide.read_bytes()
    for name in ('OUTPUT_FEEDBACK_NODES.md','SPICE_COMPREHENSIVE_COMPARISON.md','PARALLEL_ESR_LOOP.md'):
        guide=resource_path('docs/'+name)
        if guide.is_file():files[name]=guide.read_bytes()
    for source in resource_path('resources/spice').glob('*.asy'):
        files[source.name]=source.read_bytes()
    schematic=resource_path(f'resources/spice/Flyback_{len(rails)}.asc')
    if forward:
        from acf_spice import MODEL_VERSION as acf_version
        extra=resource_path('resources/spice/GenericACF_MP6005.lib').read_bytes()
        files['GenericACF_MP6005.lib']=extra
        files['Flyback.cir']=files['Flyback.cir'].replace(b'Generic configurable closed-loop flyback',b'Active-clamp forward - MP6005 inspired').replace(b'.include power_stage.inc',b'.include GenericACF_MP6005.lib\n.include power_stage.inc')
        metadata.update(model_version=acf_version,topology='ACF-FORWARD',acf=dict(dead_time_s=values['TDEAD'],
            clamp_capacitance_f=q['C_clamp'],magnetizing_inductance_h=q['Lm_forward'],
            output_inductors_h=[r['L'] for r in rails],library_sha256=hashlib.sha256(extra).hexdigest()))
        notes[:]=[n for n in notes if '普通 .ac' not in n]
        notes += ['MP6005 SSR/SYNC 逻辑参考；主 N-MOS 与低侧 P-MOS＋钳位电容，逐边沿死区。辅助栅极用理想 AC 电平移位，保护时主动放电；不模拟外部耦合电容的下垂与放电延时。',
            '每路含独立正激整流管、续流管、输出电感和两颗并联电容；LO 为线性理想电感，未输入独立输出电感 DCR/磁芯饱和。',
            '输出、反馈取样点分别在防反管后／前。磁耦合和钳位换流由物理网络求解；计算器小纹波及 CCM 近似须与实际波形对比。',
            '未实现真实 MP6005 的 PSM、频率抖动、OVP、内部 LDO 与温度保护；不得当作原厂芯片模型。']
        metadata['approximation_notes']=notes
        files['manifest.json']=_json(metadata).encode('utf-8')
        files['README.md']=('# MP6005 逻辑参考：多路有源钳位正激\n\n打开 Flyback.asc 或 Flyback.cir；Vinmin/Vinmax 使用 .step，所有硬件保持不变。\n'
            '查看 V(gate,sense)、V(sync)、V(auxgate)、V(drain,sense)、V(drain,aclamp)、I(LP)、I(LS1)、I(LO1)、V(out1,sgnd)。\n'
            '参数：design_params.inc；ASC 与 CIR 为相同物理网络。运行对比报告才会执行 FRA 与交叉负载角点扫描。\n\n'
            +'\n'.join('- '+n for n in notes)+'\n').encode('utf-8')
        guide=resource_path('docs/ACF_MP6005_SPICE.md')
        if guide.is_file():files['ACF_MODEL_GUIDE.md']=guide.read_bytes()
        schematic=resource_path(f'resources/spice/ACF_Forward_{len(rails)}.asc')
    if schematic.is_file():files['Flyback.asc']=schematic.read_bytes()
    if forward and schematic.with_suffix('.plt').is_file():files['Flyback.plt']=schematic.with_suffix('.plt').read_bytes()
    from parasitic_spice import apply_project
    return apply_project(files,q)


def export_project(path, parameters, *, bundle=None):
    """Atomically write a portable ZIP; no extracted file paths come from users."""
    files = project_files(parameters, bundle=bundle)
    destination = Path(path)
    destination.parent.mkdir(parents=True, exist_ok=True)
    temporary = None
    try:
        with tempfile.NamedTemporaryFile(dir=destination.parent, suffix='.tmp', delete=False) as stream:
            temporary = Path(stream.name)
        with zipfile.ZipFile(temporary, 'w', zipfile.ZIP_DEFLATED) as archive:
            for name, data in files.items():
                archive.writestr(name, data)
        os.replace(temporary, destination)
    finally:
        if temporary:
            temporary.unlink(missing_ok=True)
    return dict(path=str(destination), model_version=json.loads(files['manifest.json'])['model_version'], file_count=len(files))
