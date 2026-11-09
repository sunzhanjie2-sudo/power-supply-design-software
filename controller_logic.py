"""Shared, presentation-only map of the implemented generic SPICE controller.

This is not a silicon schematic. Read GenericFlybackPWM.lib for actual behavior;
in MP6005 SSR the external TL431/opto drives COMP and the internal EA is disabled.
No solver, Tk or plotting dependency belongs in this module.
"""
import copy
import math

from spice_export import SETTINGS, CHOICES, setting_group

SOURCE_URL = 'https://www.monolithicpower.com/en/mp6005.html'
SHORT_LABELS = dict(frequency_hz='fs',duty_max='Dmax',soft_start_mode='SS模式',soft_start_ms='Tss',
    cs_filter_ns='τcs',blanking_ns='LEB',scp_threshold_v='SCP',short_mode='故障模式',cs_limit='Vcs',
    slope_mode='斜坡',delay_ns='延时',driver_resistance='Rdrv',feedback_scale='H',kp='KP',
    comp_voltage_max='COMP上限',include_cap_esl='ESL',diode_cj_pf='Cj',stop_ms='Tstop',simulation_threads='线程')
SHORT_CHOICES = dict(soft_start_mode={0:'参考缓升',1:'限流缓升',2:'COMP缓升'},
    short_mode={0:'逐周期限流',1:'打嗝',2:'锁存'},slope_mode={0:'跟随设计',1:'自动建议',2:'手动'},include_cap_esl={0:'不含',1:'包含'})

# key -> (diagram block, purpose, interpretation). Every editable setting has
# an explicit explanation; a newly added setting must be mapped deliberately.
HELP = {
    'frequency_hz': ('clock','设置振荡器重复周期，每周期允许开始一次PWM脉冲。','0跟随主界面开关频率；非零会覆盖仿真频率。'),
    'duty_max': ('clock','限制每周期最长导通窗口：约为Dmax/fs。','即使COMP仍要求导通，到窗口末尾也会复位PWM。'),
    'blanking_ns': ('sense','导通最初一段时间屏蔽PWM和逐周期限流判断。','用于避开前沿尖峰；消隐期间的电流超调仍可能发生。SCP另有消隐。'),
    'min_on_ns': ('pwm','在该时间与前沿消隐均结束后，才允许常规PWM比较关断。','Vcs硬限流仅受前沿消隐约束；最小导通并非所有保护的强制保持时间。'),
    'delay_ns': ('drive','设置SR锁存输出的传播延时。','检测达到阈值后，GATE不会理想瞬时响应；实际峰值可超过阈值估算。'),
    'driver_resistance': ('drive','通用驱动器输出到GATE的串联电阻。','影响等效门电容充放电；不等同MOS外部栅阻，也不是开关损耗模型全部驱动阻抗。'),
    'uvlo': ('start','VCC低于此值时禁止开关并复位启动/故障状态。','此通用模型只用一个VCC阈值，不含真实芯片的欠压迟滞或VIN启动过程。'),
    'cs_limit': ('pwm','逐周期电流限制阈值，采用采样端电压量纲。','阈值不乘采样放大倍数；0由导出器自动确定。外部CS滤波、消隐及延时会影响峰值。'),
    'cs_filter_ns': ('sense','设置采样输入的一阶RC滤波时间常数。','0不加滤波；时间越长，尖峰越平滑，但限流与保护看到的电流也越滞后。'),
    'slope_mode': ('pwm','选择叠加到放大后电流采样上的补偿斜坡来源。','可跟随设计、采用自动工程建议或手动；自动值不代表MP6005内部实测斜坡。'),
    'slope': ('pwm','手动斜坡斜率，单位V/s，位于放大后比较器输入域。','只在手动斜坡模式生效；0禁用手动斜坡，-1是兼容自动占位值。'),
    'soft_start_mode': ('start','选择SS渐变作用于输出参考、电流限制或COMP上限。','三种是可选逻辑，不同时叠加；COMP上限缓升参考MP6005 SSR思路。'),
    'soft_start_ms': ('start','控制RUN允许后SS由0上升到1的时间。','SS在关断或保护重启时复位；这是模型内部渐变时间，不保证输出恰好同时到额定值。'),
    'soft_start_current_fraction': ('start','CS限流缓升模式下的初始限流阈值占最终值的比例。','例如0.05表示从最终限流值的5%起步；仅软启动模式1生效。'),
    'comp_offset_v': ('pwm','COMP的零电流偏置；PWM使用COMP减去该偏置作为有效命令。','COMP不高于偏置时不置位PWM；不要把该绝对电压与原始Vcs阈值混用。'),
    'ss_comp_start_v': ('start','COMP软启动上限在SS=0时的绝对电压。','仅软启动模式2生效；需要与COMP零电流偏置、终点配合。'),
    'ss_comp_end_v': ('start','COMP软启动上限在SS接近1时的绝对电压。','仅模式2生效；软启动结束后退出此临时上限，使用正常COMP限幅。'),
    'enable_delay_ms': ('start','使能与VCC满足条件后，延迟允许RUN和软启动。','与软启动时间分开；先使能延时，再进入SS渐变。'),
    'short_mode': ('protect','选择故障之后的处理：仅逐周期限流、打嗝或锁存。','模式0不执行故障关断；模式1等待后重启SS；模式2需撤销使能或欠压复位。'),
    'scp_threshold_v': ('protect','SCP快速故障检测阈值，采用CS采样端电压量纲。','门极导通且SCP消隐结束后才检查；与较低的逐周期Vcs限流阈值是两条判断。'),
    'scp_blanking_ns': ('protect','SCP判据在周期开始后屏蔽的时间。','独立于PWM前沿消隐；这是可配置模型假设，不应误认为芯片已知实测值。'),
    'olp_enabled': ('protect','允许软启动完成后的持续OCP过载计时。','还需要短路保护模式为打嗝或锁存，才能触发故障关断。'),
    'olp_ms': ('protect','持续过载状态累计到此时长后判故障。','并非任何负载过大都立即关断；OCP不连续或窗口断开会复位本模型计时。'),
    'ocp_hold_us': ('protect','将离散逐周期OCP事件保持为持续过载状态的时间窗口。','新OCP脉冲刷新保持窗口；该窗口用于通用模型的过载连续性判定。'),
    'hiccup_off_ms': ('protect','故障打嗝关断后，等待多久再次尝试启动。','仅模式1生效；重试会从SS重新起步。仿真不够长时不能观察到重启。'),
    'feedback_scale': ('feedback','设置理想隔离反馈的比例H。','参考值同时按H缩放，导出器补偿KP/H以保留环路增益；不是真实光耦CTR模型。'),
    'comp_voltage_max': ('feedback','设置正常运行时COMP允许的最高绝对电压。','0采用导出器自动上限；非零还会受模型自动电流/调制上限约束，与临时SS上限不同。'),
    'kp': ('feedback','等效补偿器增益，配合零极点决定环路响应。','0沿用软件补偿KP；实际SSR芯片外的TL431/光耦与阻容在这里用等效传递函数替代。'),
    'fz1': ('feedback','等效补偿器第一零点，用于改变增益斜率与相位。','0沿用软件fz1；二型和三型均使用。原点积分极点保留。'),
    'fp1': ('feedback','等效补偿器第一有限极点，限制高频增益。','0沿用软件fp1；区别于补偿器固有的原点积分极点。'),
    'fz2': ('feedback','三型等效补偿器的第二零点。','0沿用软件fz2；选择二型时该支路不参与传递函数。'),
    'fp2': ('feedback','三型等效补偿器的第二有限极点。','0沿用软件fp2；选择二型时该支路不参与传递函数。'),
    'include_cap_esl': ('power','决定输出/输入电容模型是否包含已配置的ESL。','这是外部电容寄生电感，不是芯片内部量；包含ESL通常使开关仿真更慢。'),
    'diode_cj_pf': ('power','给通用二极管模型添加固定等效结电容。','用于外部功率级振铃近似；不含真实Cj随电压变化及完整反向恢复过程。'),
    'stop_ms': ('test','设置瞬态仿真观察到的结束时间。','需要覆盖启动、稳态和被测事件；打嗝关断较长时应留足观察窗口。'),
    'step_ms': ('test','设置全部输出同时执行负载阶跃的时刻。','应晚于软启动且早于仿真结束；不属于芯片内部定时器。'),
    'load_after': ('test','设置阶跃后的负载电流比例。','1保持额定；0.5为半载；这改变仿真负载，不修改控制器额定参数。'),
    'short_test': ('test','向所选输出并联短路等效电阻，以测试保护。','只是外部故障注入开关，不代表开启或关闭芯片SCP逻辑。'),
    'short_output': ('test','选择短路注入的输出编号。','需要该路实际存在；与主反馈路编号相互独立。'),
    'short_start_ms': ('test','设置外部短路开始时刻。','只在短路注入开启时生效，需早于仿真结束。'),
    'short_duration_ms': ('test','设置外部短路保持的时间。','短路移除后，芯片可能仍在打嗝等待或锁存状态。'),
    'short_resistance': ('test','设置短路注入支路的等效电阻。','越小越接近硬短路；不是器件导通电阻或保护阈值。'),
    'simulation_timeout_s': ('test','限制每个瞬态工况允许占用的实际计算时间。','超时会标记该工况未完成；不会改变电路的仿真时钟或芯片动作时间。'),
    'simulation_threads': ('test','设置LTspice求解线程上限。','属于计算资源设置，更多线程不保证此电路更快，不影响控制器逻辑。'),
    'simulation_reuse': ('test','复用同一设计已通过检查的标称仿真，减少重复运行。','电路、计算结果、后处理版本或检查阈值变化会重新运行。FRA、交叉负载和短路测试仍实际执行；报告保留来源时间。'),
    'comparison_tolerance_pct': ('test','给设计计算与实测仿真差异设置提示阈值。','只改变报告判读，不会调整电路参数或强迫结果一致。'),
    'cycle_tolerance_pct': ('test','判别稳态相邻开关周期是否足够重复。','用于发现大小波或未稳态；超限时报告需复核，而不是把不同周期平均成合格结果。'),
    'fra_enabled': ('test','开启实际开关闭环频率响应测量。','FRA属于仿真试验，不是芯片内部功能；报告可与设计环路对照。'),
    'fra_start_hz': ('test','FRA扫描的最低注入频率。','应低于结束频率；低频点需要更长的收敛与采样时间。'),
    'fra_stop_hz': ('test','FRA扫描的最高注入频率。','接近开关频率时，通用模型和采样效应需谨慎解读。'),
    'fra_oct': ('test','设置每倍频程的FRA频点密度。','点数增加能看得更细，但仿真时间也会增加。'),
    'fra_amplitude_pct': ('test','设置FRA注入峰峰值相对反馈电压的比例。','过大可能进入非线性，过小可能被数值噪声淹没；不是功率输出纹波目标。'),
    'fra_cycles': ('test','设置每个FRA频点至少运行的开关周期数。','低频时还受注入周期数和收敛需求影响，不是只运行这么多周期就必然准确。'),
    'fra_timeout_s': ('test','设置每个输入端点FRA试验的实际计算超时。','超时保留未完成状态，不填造环路结果。'),
    'cross_enabled': ('test','开启多输出min/max负载组合的瞬态角点试验。','用于检查非反馈路交叉调整率；不是芯片内置的多路独立稳压功能。'),
    'cross_mode': ('test','选择全部负载组合还是重点角点。','全组合最多按各路min/max展开；路数增加时运行数量增长。'),
    'cross_hold_ms': ('test','设置每个交叉负载角点保持的时间。','用于让输出稳定；时间不足时会标注未收敛，不纳入已验证包络。'),
    'cross_timeout_s': ('test','设置每个输入端点交叉调整率试验的实际计算超时。','它限制电脑计算时间，与负载保持时间的单位和作用不同。'),
}

from qr_spice_settings import QR_SETTINGS
SHORT_LABELS.update(qr_cds_pf='Cds',qr_aux_ratio='Naux/Np',qr_zcd_r='Rz',qr_zcd_c_pf='Cz',
    qr_zcd_delay_ns='延时',qr_zcd_arm_v='预备',qr_zcd_trigger_v='触发',qr_off_min_us='Toff',
    qr_off_light_us='轻载Toff',qr_starter_us='启动',qr_vcc_v='VCC',qr_uvlo_on_v='UVon',
    qr_uvlo_off_v='UVoff',qr_vff_v='VFF',qr_cs_clamp_v='CS0',qr_ocp_v='OCP',qr_max_on_us='Tonmax')
for _key, (_default,_lo,_hi,_label,_unit) in QR_SETTINGS.items():
    _node=('power' if _key=='qr_cds_pf' else 'sense' if _key.startswith(('qr_zcd','qr_aux')) else 'start' if _key.startswith(('qr_vcc','qr_uvlo')) else 'protect' if _key=='qr_ocp_v' else 'clock')
    HELP[_key]=(_node,_label+'用于准谐振事件触发控制。','QR 专用参数；不作用于固定频率 PWM。阈值参考 L6565；检测与寄生仍须实测。')
HELP.update({
    **{k:('power' if k in ('niso_inductor_dcr','niso_edge_model') else 'pwm',v[3],
            'Buck/Boost 专用配置；三个原型分别定义调制、采样与管脚转换。具体含义见 Buck/Boost 专用框图。')
       for k,v in __import__('nonisolated').SETTINGS.items()},
    'acf_dead_ns':('drive','主 N-MOS 与辅助 P-MOS 交替导通时保留双边沿死区。','0 使用左栏正激死区；MP6005 MODE 可选 100／150／200／300 ns。SYNC 高为 P 管关断，辅助栅极为 AC 移位后的负电压。'),
    'acf_sync_resistance':('drive','辅助 P-MOS 的等效栅极驱动串联电阻。','与 Qg_aux/Vgs 等效门电容共同影响边沿；不是原厂 0.8 A 驱动的完整非线性模型。'),
    'qr_cds_pf':('power','决定退磁后的漏极谐振周期与谷底电压波形。','0 使用设计 Coss；非零为显式仿真假设，不代表实际 Coss(Vds)。'),
    'qr_zcd_delay_ns':('sense','补偿退磁电压过零到漏极谷底之间的时间。','-1 按 π/2√(Lm·Cds) 减去锁存延时估算；RC、Cj、漏感会使谷底偏移，应按波形校核。'),
    'qr_ocp_v':('protect','异常 CS 超过该阈值后关断并锁存。','仅 VCC 欠压复位；理想 VCC 不会自动跌落，不能声称模拟完整供电打嗝。'),
    'qr_vff_v':('pwm','按输入前馈降低逐周期电流上限。','近似 CS上限=CS0×(1−VFF/3)；固定测试电压，尚未连接输入分压网络。'),
    'qr_max_on_us':('drive','未触及电流阈值时也限制最长导通时间。','数值模型安全看门狗，并非宣称 L6565 具有该定时器。'),
})

NODES = [
    dict(id='feedback',x=36,y=20,w=648,h=116,title='外部反馈与等效补偿 → COMP',scope='external',
         body=['主反馈点 → 误差/补偿 → COMP 命令','MP6005 SSR：外部光耦作用于 COMP，内部 EA 关闭'],values=['feedback_scale','kp','comp_voltage_max']),
    dict(id='clock',x=46,y=210,w=292,h=134,title='振荡器 / 占空比窗口',scope='chip',
         body=['周期开始时置位 PWM','Dmax 限制最长导通窗口'],values=['frequency_hz','duty_max']),
    dict(id='start',x=378,y=210,w=292,h=134,title='使能 / 欠压 / 软启动',scope='chip',
         body=['EN、VCC 合格后才允许 RUN','SS 约束参考 / CS / COMP'],values=['soft_start_mode','soft_start_ms']),
    dict(id='sense',x=46,y=402,w=292,h=140,title='CS 滤波 / 前沿消隐',scope='chip',
         body=['采样电压 → RC 滤波 → 消隐','滤波 RC 为外部环节的等效'],values=['cs_filter_ns','blanking_ns']),
    dict(id='protect',x=378,y=402,w=292,h=140,title='SCP / OLP 故障管理',scope='chip',
         body=['SCP：大电流；OLP：持续限流','故障后关断 / 打嗝 / 锁存'],values=['scp_threshold_v','short_mode']),
    dict(id='pwm',x=46,y=600,w=292,h=150,title='PWM 比较 / 逐周期限流',scope='chip',
         body=['采样×增益＋斜坡 vs COMP−偏置','电压模式则比较振荡锯齿','Vcs 硬限流是独立关断条件'],values=['cs_limit','slope_mode']),
    dict(id='drive',x=378,y=600,w=292,h=150,title='SR 锁存 / 延时 / GATE',scope='chip',
         body=['S：时钟；R：PWM / 保护','锁存 → 延时 → 驱动电阻 → MOS'],values=['delay_ns','driver_resistance']),
    dict(id='power',x=36,y=834,w=648,h=104,title='外部功率级与寄生参数',scope='external',
         body=['MOS → 变压器 → 整流 / 滤波 → 输出；采样返回 CS','电容 ESL、二极管 Cj 位于外部功率级'],values=['include_cap_esl','diode_cj_pf']),
    dict(id='test',x=36,y=980,w=648,h=100,title='外部试验与报告设置',scope='test',
         body=['负载阶跃 / 短路注入、FRA、交叉负载角点','结束时间、线程、超时与偏差阈值不属于芯片内部'],values=['stop_ms','simulation_threads']),
]
EDGES = [
    [[190,344],[190,402]],
    [[338,277],[356,277],[356,660],[378,660]],
    [[524,344],[524,402]],
    [[192,542],[192,600]],
    [[524,542],[524,600]],
    [[338,685],[378,685]],
    [[524,750],[524,834]],
    [[36,76],[24,76],[24,670],[46,670]],
    [[36,880],[8,880],[8,460],[46,460]],
    [[684,880],[708,880],[708,76],[684,76]],
]


def definition():
    return dict(width=720,height=1100,source=SOURCE_URL,nodes=copy.deepcopy(NODES),edges=copy.deepcopy(EDGES),short_labels=copy.deepcopy(SHORT_LABELS),short_choices={key:{str(k):v for k,v in choices.items()} for key,choices in SHORT_CHOICES.items()},
        parameters={k:dict(node=v[0],purpose=v[1],meaning=v[2],label=SETTINGS[k][3],unit=SETTINGS[k][4],group=setting_group(k)) for k,v in HELP.items()})


def nonisolated_definition():
    from qr_spice_settings import applicable_keys
    from nonisolated import SETTINGS as extra
    d=definition();keys=applicable_keys('BUCK')
    d['source']='https://www.ti.com/product/LM5022'
    d['parameters']={k:v for k,v in d['parameters'].items() if k in keys}
    for k,v in extra.items():
        d['parameters'][k]=dict(node='clock' if k=='niso_ramp_ratio' else 'power' if k=='niso_inductor_dcr' else 'pwm',purpose=v[3],
            meaning={'niso_profile':'TPS40200：输入前馈电压模式；LTC3864：高侧电阻采样峰值电流；LM5022：低侧采样峰值电流。需与拓扑和模式一致。',
              'niso_ramp_ratio':'TPS40200 典型锯齿幅值为 VIN/10；输入两端各自更新，不使用固定 5V。',
              'niso_ith_gain':'ITH 约 0.8V 对应零电流；默认斜率仅为可配置近似，不用 95mV 限流代替增益。',
              'niso_lm_cs_resistor':'斜坡≈45µA×fs×(2kΩ+外部电阻)，同时进入调制和逐周期限流。',
              'niso_inductor_dcr':'-1 根据匝数、MLT、线径计算；非负值为明确的实测/选型覆盖，两端共用。',
              'niso_edge_model':'快速闭环保留 L、DCR、C、ESR、Ron 和压降，关闭极快的结电容边沿；详细模式保留 Coss/Cj，但求解更慢。'}[k],
            label=v[3],unit=v[4],group=setting_group(k))
    for node in d['nodes']:
        if node['id']=='feedback':node.update(title='反馈分压 → 二／三型补偿 → 比较器指令',body=['FB 基准：0.7 / 0.8 / 1.25V；自动按目标生成 H','comp 是等效指令；comp_pin 是 COMP/ITH 显示量'])
        if node['id']=='pwm':node.update(body=['VM：VIN 比例锯齿 vs 补偿','PCM：实际电流×Rs＋斜坡 vs 补偿','LM5022：COMP 减 1.4V 再除 3'],values=['niso_profile','niso_ith_gain'])
        if node['id']=='power':node.update(body=['Buck：高侧 P-MOS → L → C；D1 续流','Boost：L → N-MOS / 整流 D1 → C'],values=['niso_inductor_dcr','diode_cj_pf'])
        if node['id']=='protect':node.update(body=['默认逐周期限制；可选通用打嗝/锁存','未复刻原厂全部保护；Boost 不能靠关 MOS 隔离短路'])
    return d


def display_value(key, values, design=None, *, compact=False):
    value=values.get(key,SETTINGS[key][0])
    try:
        number=float(str(value).split(' ·')[0])
        if not math.isfinite(number):raise ValueError()
    except (ValueError,TypeError):return '编辑中…'
    if key=='qr_zcd_delay_ns' and number==-1:return '自动估算'
    if key=='acf_dead_ns' and number==0:return f"沿用设计 {(design or {}).get('forward_dead_time',100e-9)*1e9:g} ns"
    if compact and key in SHORT_CHOICES:return SHORT_CHOICES[key].get(int(number),'编辑中…')
    if key in CHOICES:return CHOICES[key].get(int(number),'编辑中…')
    if key=='frequency_hz' and number==0:
        actual=(design or {}).get('f_sw')
        return ('跟随设计 '+f'{actual/1000:g} kHz') if isinstance(actual,(int,float)) else '跟随设计频率'
    if number==0 and key in ('kp','fz1','fz2','fp1','fp2'):return '沿用软件'
    if number==0 and key in ('cs_limit','comp_voltage_max'):return '自动确定'
    unit=SETTINGS[key][4]
    if unit=='Hz' and abs(number)>=1000:return f'{number/1000:g} kHz'
    return f'{number:g}'+(' '+unit if unit else '')


def state_note(key,values):
    try:
        mode=int(float(str(values.get('soft_start_mode',0)).split(' ·')[0]))
        protection=int(float(str(values.get('short_mode',0)).split(' ·')[0]))
        slope=int(float(str(values.get('slope_mode',1)).split(' ·')[0]))
    except (ValueError,TypeError):return '正在编辑，导出时仍会独立校验完整设置。'
    if key in ('ss_comp_start_v','ss_comp_end_v') and mode!=2:return '当前软启动模式未使用此项；切换到COMP上限缓升后生效。'
    if key=='soft_start_current_fraction' and mode!=1:return '当前软启动模式未使用此项；切换到CS限流缓升后生效。'
    if key=='slope' and slope!=2:return '当前使用自动/设计斜坡，手动斜率暂不生效。'
    if key=='hiccup_off_ms' and protection!=1:return '当前不是打嗝模式，重试等待时间暂不生效。'
    if key in ('scp_threshold_v','scp_blanking_ns','olp_enabled','olp_ms','ocp_hold_us') and protection==0:return '当前仅逐周期限流，不执行SCP/OLP故障关断。'
    if key in ('fz2','fp2'):return '第二组零极点只作用于三型；二型保留此值但不使用。'
    return ''


def qr_definition():
    from qr_spice_settings import applicable_keys
    d=definition();d['source']='https://www.st.com/resource/en/datasheet/l6565.pdf'
    d['parameters']={k:v for k,v in d['parameters'].items() if k in applicable_keys('QR-FLYBACK')}
    overrides={
        'feedback':('外部 SSR 等效补偿与电流命令',['防反管前取样；采用计算器 KP 与零极点','外部参考缓升，不是芯片内置软启动'],['kp','soft_start_ms']),
        'clock':('退磁事件与关断消隐',['ZCD 下降沿置位；无固定频率时钟','COMP 降低时延长关断消隐，可跳谷'],['qr_off_min_us','qr_starter_us']),
        'start':('VCC 欠压迟滞与启动许可',['13.5 V 启动 / 9.5 V 关断','外部理想 VCC；不模拟辅助供电'],['qr_vcc_v','qr_uvlo_on_v']),
        'sense':('辅助绕组电压到 ZCD',['RC / 钳位 / 上升预备 / 下降触发','附加延时用于靠近谷底，须核对波形'],['qr_zcd_arm_v','qr_zcd_delay_ns']),
        'protect':('异常 CS 关断锁存',['CS 超限关断；VCC 欠压复位','不使用 MP6005 定时打嗝逻辑'],['qr_ocp_v','cs_filter_ns']),
        'pwm':('CS 比较关断与 VFF 限流',['CS×增益 与 COMP 命令比较','COMP 为软件量纲；芯片电压另行换算'],['qr_cs_clamp_v','qr_vff_v']),
        'drive':('SR 锁存与驱动',['S：ZCD / 无信号启动定时器','R：CS 比较 / 保护 / 看门狗'],['delay_ns','qr_max_on_us']),
        'power':('外部谐振功率级',['Cds、漏感、结电容影响谷底','ZCD 为无负载辅助绕组电压映射'],['qr_cds_pf','diode_cj_pf']),
    }
    for row in d['nodes']:
        if row['id'] in overrides:row['title'],row['body'],row['values']=overrides[row['id']]
    for key,(purpose,meaning) in {
        'blanking_ns':('导通初期屏蔽常规 CS 比较。','与关断后的 ZCD 消隐是两个独立时间。'),
        'soft_start_ms':('外部参考从0缓升到设定值。','为通用闭环验证添加，不代表芯片内置软启动。'),
        'delay_ns':('ZCD 置位与 CS 复位的锁存传播延时。','影响开通谷底位置及峰值电流超调。'),
        'cs_filter_ns':('原始 CS 到比较器的一阶滤波。','滤波会使实际关断峰值超过静态命令。'),
    }.items():d['parameters'][key].update(purpose=purpose,meaning=meaning)
    return d


def acf_definition():
    from qr_spice_settings import applicable_keys
    d=definition()
    d['parameters']={k:v for k,v in d['parameters'].items() if k in applicable_keys('ACF-FORWARD')}
    d['short_labels'].update(acf_dead_ns='死区',acf_sync_resistance='Rsync')
    for row in d['nodes']:
        if row['id']=='drive':
            row.update(title='锁存 / GATE / SYNC / 死区',body=['主 N-MOS：正 Vgs 开通','SYNC 高→P 管关断；低→负 Vgs 开通','两管之间保留双边沿死区'],values=['acf_dead_ns','acf_sync_resistance'])
        if row['id']=='power':
            row.update(title='外部有源钳位正激功率级',body=['P-MOS＋钳位电容复位变压器','每路整流 / 续流 / 输出电感 / 并联电容'],values=['include_cap_esl','diode_cj_pf'])
    return d
