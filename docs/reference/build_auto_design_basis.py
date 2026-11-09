"""Rebuild the Word guide using the actual example. Optionally pass measured case JSON."""
import argparse
import json
import math
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0,str(ROOT))
from docx.oxml import OxmlElement
from docx.oxml.ns import qn
from docx.opc.constants import RELATIONSHIP_TYPE as RT
from docx_layout import new_document, paragraph, table, section, equation
from design_engine.sizing_basis import DOCUMENT, REVISION, SCOPE, SOURCES
import word_math as wm


def vendor_link(p, key):
    label, _, url = SOURCES[key]
    link = OxmlElement('w:hyperlink')
    link.set(qn('r:id'),p.part.relate_to(url,RT.HYPERLINK,is_external=True))
    run = p.add_run(label)
    from docx.shared import RGBColor
    run.font.color.rgb = RGBColor.from_string('175898')
    run.underline = True
    link.append(run._r)
    p._p.append(link)


def build(vm, pcm, boost, flyback, dcm, multi, output):
    a, b = vm['__auto_design_basis'], pcm['__auto_design_basis']
    spec = a['specification']
    if (a['revision'] != REVISION or b['revision'] != REVISION or
            spec != b['specification'] or (spec['vin_min'],spec['vin_max'],spec['vout'],spec['iout'],
            spec['imin'],spec['fs'],spec['il_ratio'],spec['ripple'],spec['pm']) != (18,30,12,2,1,50000,.3,.01,60)):
        raise ValueError('需使用当前规则版本的 24 W Buck 双模式示例快照')
    bs=boost['__auto_design_basis']
    if (bs['revision']!=REVISION or bs['topology']!='BOOST' or not bs['model_ok'] or
        tuple(bs['specification'][k] for k in ('vin_min','vin_max','vout','iout','imin','fs','eta_guess','il_ratio','ripple','pm'))
            != (9,18,24,1,.5,200000,.9,.3,.01,60)):
        raise ValueError('需使用当前规则版本的 24 W LM5022 Boost 例程与校核结果')
    fb,dc,mx=[p['__auto_design_basis'] for p in (flyback,dcm,multi)]
    if (any(v['revision']!=REVISION or v['topology']!='FLYBACK' for v in (fb,dc,mx))
            or not all(v['model_ok'] for v in (fb,dc)) or not mx['cross_regulation']['complete']
            or len(mx['cross_regulation']['summary'])!=3):
        raise ValueError('需要当版反激 CCM、DCM 及三路交叉负载完整算例')
    wm.ALIASES.update({'Vhigh':'V_in,max','Vlow':'V_in,min','ΔVlim':'ΔV_o,pp',
                       'Ccharge':'C_charge','Cstep':'C_step','Cin':'C_in','ΔIstep':'ΔI_step',
                       'Vcsmin':'V_CS,min','Rcs':'R_CS','Ics':'I_CS','Iload':'I_load',
                       'Dstar':'D_*','ΔVin':'ΔV_in','ΔVc':'ΔV_C','Dmax':'D_max','Ilow':'I_in,ref',
                       'Ipkb':'I_pk,est','Vramp':'V_ramp','Vcsmax':'V_CS,max','Vcsmin':'V_CS,min',
                       'Rext':'R_ext','Vrampmax':'V_ramp,max','fRHP':'f_RHP','Kpin':'K_P,COMP',
                       'Lccm':'L_m,CCM','Ldcm':'L_m,DCM','Prated':'P_rated','Vwind':'V_w,j',
                       'Nsecj':'N_s,j','Nsecfb':'N_s,fb','Vcapfb':'V_cap,fb','Vrectfb':'V_F,fb'})
    wm.NAMES = sorted(wm.ALIASES,key=len,reverse=True)
    r = a['rules']
    doc = new_document('自动计算参数依据','从规格到第一套可复算的器件值  ·  规则版 '+REVISION,
                       '开关电源设计与环路分析  /  参数选择依据')
    doc.core_properties.subject = 'Buck、Boost 与定频反激的器件选值、补偿和多工况核对'
    h = lambda t:doc.add_heading(t,2)
    def para(t): return paragraph(doc,t)
    def note(t,*keys):
        p = paragraph(doc,t,small=True)
        for i,key in enumerate(keys):
            p.add_run('  ·  ' if i else '  ')
            vendor_link(p,key)
    def tab(headers, rows, widths): return table(doc,headers,rows,widths)
    def eq(t, n=None, d=None): return equation(doc,t,n,d)

    h('怎样使用这份依据')
    para('当你只知道输入范围、输出电压和负载时，可以先让软件提出一组可编辑的器件值。这里逐项解释哪条规格决定了下限，为什么选择这个常用值，以及哪些假设还要拿实物验证。')
    h('选择与你的电源相近的例程')
    tab(['设计例程','输入、输出与规格','从哪里读起'],[
        ('Buck 降压','18–30 V → 12 V，1–2 A，50 kHz','第 2–4 页。求高线电感纹波，对照电压模式与峰值电流模式的补偿。'),
        ('Boost 升压','9–18 V → 24 V，0.5–1 A，200 kHz','第 5–7 页。求低线输入电流、脉冲输出电流、逐周期限流与 RHP 零点。'),
        ('隔离反激','20–30 V → 30 V / 40 W，另有三路输出','第 8–10 页。比较 CCM 和 DCM，选择整数匝、限流和钳位，逐路读交叉负载结果。')
    ],[1.18,2.70,3.22])
    h('软件中的三个动作')
    para('① 桌面单元设计选“文件 → 按规格生成初版”。本地网页版在“设计输入”选择同名按钮。选好拓扑与控制器，填写输入端点、负载与纹波要求。')
    para('② 点击“生成并校核”。程序为 L、DCR 和电容组提出候选值。在同拓扑的已有工程中可分别锁定这些器件。若约束不满足，预览会列出对应工况及原因。')
    para('③ 点击“采用此初版”后继续修改或保存工程。JSON 中的 __auto_design_basis 保留生成时的规格、标准值、原厂链接和角点结果。修改设计后，以重新计算的结果为准。')
    note('反馈路端口按输出防反管之后计，SSR 在防反管之前取样。末页列出各拓扑覆盖范围和资料索引。')

    section(doc,'01  从电流纹波选电感，从电荷选电容')
    para('先用理想 CCM 的伏秒平衡估算。固定输出电压时，高线的导通伏秒最多，用最高输入电压检查额定负载纹波。TI 给出 20%–40% 的估算区间，本例取中间值 30%。')
    eq('ΔIL=0.30·Iout')
    eq('Lmin=', 'Vout·(1−Vout/Vhigh)', 'fs·ΔIL')
    para(f"目标峰峰值为 {r['delta_i_target']:.2f} A。代入 12 V、30 V 与 50 kHz，得到 {r['L_min']*1e6:.0f} µH。按 E12 向上取 {vm['L']*1e6:.0f} µH。有损模型若仍超过目标，未锁定的电感再向上取值并复算。")
    h('输出电容的两个下限')
    para('把 120 mVpp 的稳态预算平分给电容量和 ESR。对三角电流积分得出容量下限。另用最小至额定负载的电流差，估算控制器一个周期内暂未增加供电时所需的电荷。')
    eq('Ccharge≥', 'ΔIL','8·fs·ΔVc')
    eq('Cstep≥', 'ΔIstep','fs·ΔVlim')
    tab(['约束','本例结果','选择理由'],[
        ('稳态充放电',f"{r['C_out_charge']*1e6:.1f} µF",'60 mV 分配给电容量，剩余 60 mV 用于 ESR。'),
        ('一个周期补电',f"{r['C_out_step']*1e6:.1f} µF",'1 A 电流差持续 20 µs，允许下跌 120 mV。'),
        ('输出电容',f"{vm['output_capacitors'][0]['C']*1e6:.0f} µF",'取两个下限中较大者，再按 E12 向上取值。库存件需核对工作偏压下的有效容量。'),
        ('输出 ESR',f"上限 {r['ESR_out_ceiling']*1e3:.0f} mΩ",'上限来自 60 mV ÷ 0.6 A。模型先以 35 mΩ 和该上限中较小者按 E24 向下取值。')
    ],[1.38,1.57,4.15])
    note('TI 式 (5)–(6) 用于初估电感，本工具选高线作为纹波校核点。一个周期是项目储能假设。最小负载留空时，只按稳态纹波选容。实物瞬态还受控制带宽和电感电流爬升速度影响。','BUCK')

    section(doc,'02  输入电容、铜损预算与限流电阻')
    h('为什么输入侧要单独选电容')
    para('Buck 的输入电流是脉冲。稳态电源承担平均值，输入电容承担脉冲与平均值之差。矩形电流近似下，D(1−D) 在 D=0.5 时最大，本例的理想占空比范围包含 0.5。')
    eq('Cin≥','Iout·Dstar·(1−Dstar)','fs·ΔVin')
    para(f"输入纹波暂按低线的 2% 分配，充放电部分取 0.18 V，ESR 部分也取 0.18 V。容量下限 {r['C_in_charge']*1e6:.1f} µF，选 {vm['input_capacitors'][0]['C']*1e6:.0f} µF。程序用实际输入脉冲和各支路 C、ESR 再算输入纹波。快沿 ESL 尖峰另行核对。")
    h('为什么 DCR 和限流电阻向下取值')
    eq('Rdc≤','0.005·Pout','Iout^2+ΔIL^2/12')
    eq('Rcs≤','Vcsmin','1.25·Ics')
    para(f"成品电感铜损先分配输出功率的 0.5%。本例 DCR 预算 {r['DCR_budget']*1e3:.1f} mΩ，取 {vm['inductor_dcr']*1e3:.0f} mΩ。按各工况 RMS 电流复算铜损。温升、热态阻值和磁芯交流损耗留给具体料号核实。")
    tab(['芯片参考','CS 阈值范围¹','所用采样电阻','设计判断'],[
        ('TPS40200','55 / 100 / 140 mV',f"{vm['Rs']*1000:.0f} mΩ",'按电感目标峰值 2.30 A 及 25% 余量，取不超过上限的 E24 值。'),
        ('LTC3864','85 / 95 / 103 mV',f"{pcm['Rs']*1000:.0f} mΩ",'在参考模型中再计入斜坡补偿折算电流。按各端点实际占空比回查余量。')
    ],[1.13,1.57,1.07,3.33])
    para(f"以 TPS40200 为例，正常满载峰值约 {a['requirements']['inductor_load_peak']:.2f} A。最高限流阈值 ÷ 采样电阻可到 {r['prospective_fault_current']:.2f} A，还需计入滤波和关断延迟。电感的饱和曲线和 MOS 的脉冲能力应另按故障条件核查。")
    note('¹ 依次为最小、典型、最大值。TPS40200 采用 −40 至 125 °C 的阈值行，LTC3864 按电气特性表所列测试条件。25% 余量与 0.5% 铜损预算均为项目初筛约定。','TPS40200','LTC3864')

    section(doc,'03  用同一套硬件与补偿复算四个角点')
    para('程序先解带 DCR、MOS 导通电阻、采样电阻、续流压降和每颗输出电容 ESR 的周期稳态，再线性化 CCM 工作点。电压模式拟合三型补偿，峰值电流模式拟合二型。K 因子整定得到的一套增益和零极点用于全部角点。')
    tab(['Vin / 负载','占空比','电感峰值','输入纹波','输出纹波','交越频率','PM / GM'],
        [(f"{c['vin']:g} V / {c['current']:g} A",f"{c['duty']:.3f}",f"{c['peak']:.2f} A",
          f"{c['input_ripple']*1000:.0f} mV",f"{c['ripple']*1000:.2f} mV",f"{c['loop']['fc']/1000:.2f} kHz",
          f"{c['loop']['pm']:.1f}° / {c['loop']['gm_db']:.1f} dB") for c in a['corners']],
        [1.05,.70,.84,.91,.93,1.04,1.63])
    note('表为 TPS40200 行为参考模型，电压纹波均为峰峰值。可在程序里切换输入工况核对额定负载结果。')
    h('怎样判断环路能否采用')
    para(f"先试开关频率的 1/12，需要时逐步下调到 1/100，并换用不同工况作整定点。本例目标交越 {vm['fc_target']/1000:.2f} kHz，三型两对重合零、极点分别约 {vm['fz1']:.0f} Hz 和 {vm['fp1']/1000:.2f} kHz。工程约束要求闭环稳定、最低 PM ≥ 60°、GM ≥ 6 dB，所有交越均在开关频率的 1/10 以内。")
    para('改选 LTC3864，同一规格使用 CS 等效指令口径的二型补偿。物理 ITH 网络换算采用典型误差放大器跨导 1.8 mS 及参考模型 ITH 至 CS 的近似系数 0.05。芯片工作点改变时要复核这项近似。轻载进入 DCM 或用户指定空载时，该工况会标为待复核。')
    h('把结果翻译成采购要求')
    req=a['requirements']
    tab(['器件','本例的筛选条件','下一步需核对'],[
        ('Q1 / D1',f"静态耐压下限 {req['vds_steady_min']:.1f} / {req['vrrm_steady_min']:.1f} V",'按工程当前降额规则折算。加上线束浪涌和开关尖峰后再定额。'),
        ('采样电阻',f"额定功率 ≥ {req['sense_rated_w']:.3f} W",'由最坏平均损耗 ÷ 20% 得到，另核对封装温度降额。'),
        ('输入 / 输出电容',f"纹波电流初筛 {req['cap_rms']['input'][0]:.3f} / {req['cap_rms']['output'][0]:.3f} A RMS",'单颗输入电容另计占空比约 0.5 的区间上界。并联时，各支路列端点 RMS，需再查区间分流。')
    ],[1.36,2.47,3.27])
    note('半导体导通与开关参数先沿用对应的通用 Buck 参考算例。候选硬件保留完整参数和生成记录，可替换实物型号继续计算。')

    section(doc,'04  Boost 的电感与两侧电容')
    br=bs['rules']
    para('这台辅源把 9–18 V 升到 24 V，输出电流 0.5–1 A。LM5022 驱动低侧 MOS，开通时输入给电感充电，输出电容独自供电。关断时电感经二极管给输出供电。输入电流连续，输出整流电流呈脉冲，两侧电容分别选值。')
    h('先找最大输入电流，再找电感伏秒最大的位置')
    eq('Ilow=','Pout','η·Vlow')
    eq('D(Vin)=1−η·Vin/Vout')
    eq('Lmin=','Vin·D(Vin)','fs·ΔIL')
    para(f"预设效率取 90%，低线满载的输入电流初估 {br['input_current_design']:.3f} A。电感纹波按此电流的 30% 给定，即 {br['delta_i_target']:.3f} App。输入电压乘占空比在曲线顶点达到最大。把顶点限制在输入范围内，本例取 {br['ripple_witness_vin']:.2f} V，得到 {br['L_min']*1e6:.1f} µH，按 E12 向上取 {boost['L']*1e6:g} µH。")
    h('给输入连续电流和输出脉冲电流分别分配预算')
    eq('Cin≥','ΔIL','8·fs·ΔVin')
    eq('Ccharge≥','Iout·Dmax','fs·ΔVc')
    tab(['初筛项目','本例计算','采用值或约束'],[
        ('输入电容',f"低线 2% 预算，一半给充放电，需 {br['C_in_charge']*1e6:.2f} µF",f"{boost['input_capacitors'][0]['C']*1e6:g} µF，低频纹波再用输入电流及 ESR 复算。"),
        ('输出电容',f"低线占空比初估 {br['duty_estimate']:.3f}，需 {br['C_out_charge']*1e6:.2f} µF",f"0.5 A 阶跃的单周期电荷预算另需 {br['C_out_step']*1e6:.2f} µF。取较大下限，采用 {boost['output_capacitors'][0]['C']*1e6:g} µF。"),
        ('输出 ESR',f"120 mV ÷ {br['peak_design']:.2f} A ≈ {br['ESR_out_ceiling']*1000:.1f} mΩ",f"以 {boost['output_capacitors'][0]['ESR']*1e3:g} mΩ 建模。开通或关断时的电容电流跳变接近电感电流。")
    ],[1.16,2.63,3.31])
    note('应用笔记提供 CCM 初算关系。采用低线满载输入电流作纹波基准、增加区间校核点和分配一半纹波给 ESR，均为本软件采用的选值规则。预设效率用于初算，周期模型用实际压降复算，再由损耗得到最终效率。','BOOST')

    section(doc,'05  LM5022 怎样决定限流与补偿')
    para('CS 比较器同时看到采样电阻压降和时钟产生的补偿斜坡。低线满载时这两项通常都较大。只把 0.5 V 典型阈值除以负载电流，会遗漏升压变换器的输入电流以及已经被斜坡占用的电压。')
    eq('Vramp=45 µA·(2000 Ω+Rext)·D')
    eq('1.25·Ipkb·Rcs+Vrampmax·D≤Vcsmin')
    para(f"LM5022 的 CS 限流阈值为 0.45 / 0.50 / 0.55 V。参考模型用式 (51) 的典型斜坡。选值时用 83–137 mV 的内部整周期斜坡范围，按总串阻比例估算外部电阻的影响。小斜坡检查次谐波，大斜坡检查限流余量。这项外推须用实际 CS 波形复核。")
    tab(['选值','本例','判断依据'],[
        ('采样电阻',f"{boost['Rs']*1000:g} mΩ",f"预估峰值 {br['peak_design']:.2f} A，预留 25% 电流余量，限流按 0.45 V 校核。"),
        ('CS 附加串阻',f"{br['cs_external_ohm']:g} Ω",'使补偿斜率至少达到低线关断侧电流斜率折算电压的一半，再检查周期内环特征根。内部已有 2 kΩ。'),
        ('电感 DCR',f"{boost['inductor_dcr']*1000:g} mΩ",f"按额定功率的 0.5% 预留铜损，DCR 上限约 {br['DCR_budget']*1000:.2f} mΩ。额定温度下的实际阻值待核对。")
    ],[1.42,1.12,4.56])
    h('右半平面零点限制可用带宽')
    eq('fRHP=','Rload·(1−D)^2','2π·L')
    eq('fc≤min(fs/10,fRHP/5)')
    para('提高占空比后，MOS 先延长储能时间，二极管向输出送电的时间反而缩短。这一初始反向响应增加相位滞后。TI 给出的带宽参考为 RHP 零点的 1/3 至 1/10，本工具取 1/5，并同时限制在开关频率的 1/10 以内。每个 CCM 工况均按其实际占空比和负载复算。')
    note('本例 200 kHz 属于数据手册有电气特性数据的频点。软件支持的 50 kHz 初筛下限是项目约定，最高 2.2 MHz 来自芯片资料。芯片原型覆盖 6–60 V 输入。MOS 关断后输入仍可经电感和二极管流向输出，逐周期限流不能切断输出短路。','LM5022')

    section(doc,'06  复核 Boost 的五个工作点')
    low=bs['corners'][0]
    para('把选好的 L、C、DCR、采样电阻和二型补偿同时放进五个模型工况。前四行是电压与负载端点，最后一行是预估电感伏秒最大处的满载检查。表中的交越频率均由同一套补偿复算得到。')
    tab(['输入 / 负载','电感峰值','电感纹波','输出纹波','RHP 零点','实际交越','PM / GM'],[
        (f"{c['vin']:.3g} V / {c['current']:g} A",f"{c['peak']:.2f} A",f"{c['delta_i']:.3f} A",
         f"{c['ripple']*1000:.1f} mV",f"{c['rhp_hz']/1000:.1f} kHz",f"{c['loop']['fc']/1000:.2f} kHz",
         f"{c['loop']['pm']:.1f}° / {c['loop']['gm_db']:.1f} dB") for c in bs['corners']
    ],[1.08,.83,.85,.93,.92,.96,1.53])
    para(f"在 9 V / 1 A，RHP 零点约 {low['rhp_hz']/1000:.2f} kHz，初版允许的交越上限为 {low['fc_limit']/1000:.2f} kHz。实际交越 {low['loop']['fc']/1000:.2f} kHz。恰好达到空载或进入 DCM 的点会显示待复核，该 CCM 相位裕度不用于判定这些点。")
    h('从环路页的增益换算到 COMP 引脚')
    cp=bs['compensation_pin']
    eq('Kpin=3·KP')
    para(f"环路页以 CS 指令作为功率级输入，LM5022 的 COMP 到 CS 小信号增益约为 1/3。因此本例环路 KP 为 {boost['KP']:.2f}，外部运放网络应实现 {cp['kp']:.2f}。1.4 V 偏置决定静态 COMP 电平。电阻电容只按小信号增益和零极点计算。")
    tab(['反馈分压','二型补偿支路','额定条件复核'],[
        (f"上臂 {cp['R1']/1000:g} kΩ，下臂 {cp['R_lower']/1000:.3f} kΩ，基准 1.25 V。",
         f"R2 {cp['R2']/1000:.3f} kΩ，C1 {cp['C1']*1e9:.2f} nF，C2 {cp['C2']*1e9:.2f} nF。标准值替代后需回代。",
         f"输入／输出电容组纹波电流初筛 {bs['requirements']['cap_rms']['input'][0]:.3f} / {bs['requirements']['cap_rms']['output'][0]:.3f} A RMS。")
    ],[2.04,2.52,2.54])
    para(f"按电阻功耗只使用额定值的 20%，采样电阻需要至少 {bs['requirements']['sense_rated_w']:.2f} W。四舍五入前的最小值保存在工程文件中。还需用具体 MOS、二极管与电感料号核实开关尖峰、温升、故障电流和实物负载阶跃。")
    note('表内均为设计模型结果。补偿电路页、Word 与 Excel 工程报告沿用同一组物理阻容和增益口径。','LM5022')

    section(doc,'07  反激怎样确定匝比和励磁电感')
    para('同一组规格可以得到两种磁件。例程输入 20–30 V，反馈端口 30 V，额定 40 W，最小负载 20 W，固定 250 kHz。预设效率为 90%，输入功率预算为 44.44 W。低线目标导通时间占一个周期的 40%。')
    h('在一个周期内留出足够的退磁时间')
    eq('Vr=','Vin·D','1−D−δ')
    para('δ 是退磁后的空闲时间比例。CCM 取零，此例的目标反射电压为 13.33 V。DCM 预留 15% 空闲时间，目标变为 17.78 V。用反射电压除以反馈路电容端电压与整流压降之和，得到目标 Np/Ns。')
    eq('Lccm≥','(Vin·D)²','fs·Pin·r')
    eq('Ldcm=','(Vin·D)²','2·Pin·fs')
    para('CCM 的 r 为峰峰纹波除以原边导通段平均电流。该比例随输入升高而增加，软件用高线伏秒检查 65% 目标，并给整数匝比取整留 6% 空间。DCM 由每周期储能反求电感，低线满载定值，向下选标准值后再验退磁余量。')
    tab(['相同规格','CCM 额定设计','DCM 额定设计'],[
        ('励磁电感与匝数',*[f"{p['L']*1e6:g} µH，{p['Np']:.0f} : {p['Ns']:.0f} 匝" for p in (flyback,dcm)]),
        ('磁芯与 AL',*[f"{p['core_choice']}，{v['rules']['geometry']['AL']*1e9:.0f} nH/匝²" for p,v in ((flyback,fb),(dcm,dc))]),
        ('低线满载原边峰值',*[f"{v['corners'][0]['peak']:.2f} A" for v in (fb,dc)]),
        ('高线满载最大磁密',*[f"{v['corners'][2]['bpeak']*1000:.0f} mT" for v in (fb,dc)])
    ],[2.25,2.42,2.43])
    para('磁芯按 Lm × Ipk / (Np × Ae) 核对峰值磁密，再数各绕组的实际铜面积。初筛取 Bmax 0.22 T、铜窗口利用率 30%、电流密度 4 A/mm²。AL 是对成品或打样气隙磁芯的要求；热阻、窗口绝缘和具体材料需实物核对。')
    note('TI 的 LM5155 应用笔记用于 CCM 功率级选型，DCM 的储能与退磁关系来自 TI 的专文。例程的纹波、磁密和空闲余量是本项目的设计选择。','FLYBACK','FLYBACK-DCM')

    section(doc,'08  MP6005 的限流、钳位和反馈')
    h('用峰值电流选采样电阻，用 RMS 电流选功率等级')
    eq('Rcs≤','Vcsmin','1.25·Ipkb')
    eq('Prated≥','Irms²·Rcs','0.20')
    rr=fb['requirements']; cr=fb['corners'][0]; cp=fb['compensation_pin']
    para(f"MP6005 正常逐周期门限为 140 / 160 / 180 mV，另有典型 300 mV 短路门限。CCM 初算峰值为 {fb['rules']['peak_design']:.2f} A，留 25% 余量，用最低正常门限选 {flyback['Rs']*1000:g} mΩ。放大增益 11 进入环路。采样电阻额定功率向上取整至 {math.ceil(100*rr['sense_rated_w'])/100:.2f} W。")
    tab(['部位','本例初算与复核'],[
        ('电容',f"输入 {flyback['input_capacitors'][0]['C']*1e6:g} µF，输出 {flyback['output_capacitors'][0]['C']*1e6:g} µF。输出的充放电和 ESR 各分配一半纹波预算。两端、两档负载最大输出纹波 {max(r['ripple'] for r in fb['corners'])*1000:.1f} mVpp，目标 300 mVpp。"),
        ('MOS 与整流管',f"关断峰值按 Vin + Kc × Vr 初筛，Kc = {flyback['Kc']:.1f}。计入项目耐压降额并向上取整后，MOS ≥ {math.ceil(rr['vds_min'])} V，整流管 ≥ {math.ceil(rr['vrrm_min'][0])} V，整流反压仍需示波器核对尖峰。"),
        ('RCD 阻容',f"按最大模型耗散工况的钳位电压和漏感能量，建议起算 {rr['rcd_r']:.0f} Ω、{rr['rcd_c']*1e9:.0f} nF。估计耗散 {cr['clamp_loss']:.2f} W，在 20% 功耗使用率下需至少 {rr['clamp_rated_w']:.2f} W。固定阻容在其他工况的实际钳位幅值须验证。"),
        ('TL431 / 光耦',f"反馈取电容端，采用无快车道二型。按 10 kΩ 上拉、CTR = 1、光耦电容 100 pF 反推，R2 ≈ {cp['R2']/1000:.2f} kΩ，C1 ≈ {cp['C1']*1e9:.2f} nF，C2 ≈ {cp['C2']*1e12:.0f} pF。CTR、LED 偏置及光耦高频特性待选料确认。")
    ],[1.5,5.6])
    para('CCM 限制交越频率低于 fs/10 和右半平面零点的 1/5。DCM 由固定频率、每周期完全退磁的储能关系线性化，保留各并联电容的 ESR。两者均用同一套补偿复算本设计所有角点。仿真与计算使用相同工程斜坡；芯片实际内部斜坡另需确认。')
    note('MP6005 频率、SENSE 门限和 SSR 接法来自 MPS 数据表。RCD 的钳位与耗散取舍见 TI 的吸收电路文章。','MP6005','RCD')

    section(doc,'09  三路反激怎样判断每路能否使用')
    x=mx['cross_regulation']; geom=mx['rules']['geometry']
    para('打开内置三路 CCM 反激，再从“按规格生成初版”进入。工程的额定负载为 30 / 1 / 2 W，最小为 2 / 0.3 / 0.5 W。文件名沿用 40 W，实际额定负载合计 33 W。本例选择 OUT1 作为唯一反馈路。')
    eq('Vwind=','Nsecj·(Vcapfb+Vrectfb)','Nsecfb')
    para('上式得到第 j 路绕组侧的电压估值。减去该路整流管及输出防反管压降才得到端口估值。软件保留三个副边的匝数比例，初选原边及各副边为 '+' / '.join(str(v) for v in geom['turns'])+' 匝。同一套匝数、电感和导线用于两端输入。')
    h('读交叉负载结果')
    tab(['输出','匝比端口初估','已求端口范围','其他路负载造成的最大变化¹'],[
        (f"OUT{v['id']}"+(' · 反馈' if v['feedback'] else ''),f"{v['V_reference']:.3f} V",
         f"{v['V_min']:.3f}–{v['V_max']:.3f} V",f"{v['cross_only_pct']:.2f}%") for v in x['summary']
    ],[1.32,1.46,2.0,2.32])
    para(f"每个输入端点有八种轻重载组合，两端共 {x['total_cases']} 种。¹ 固定 Vin 及该路自身负载，只改变其他路负载，以该路匝比端口估值作分母。表中电压范围则纳入该路自身的负载变化。")
    para('此例绕组两两 kij = 0.995，DCR 由匝数、线径、股数和每匝平均长度得到。每个有解的混合负载都参与 MOS 耐压、各整流管反压、采样和钳位电阻功耗的最大值比较。未收敛和真空载工况单独列出。')
    h('电压有解后，再读环路')
    para('满载时，程序用主反馈闭环复算高低线。轻载进入 DCM 后，本例的扫描未遇到 −180° 相位交点，能读到 PM，仍不能给出有限的 GM。预览保留此项待验证。各辅助路的允许电压范围须由下游电路规格判定。')
    note('TI 的多输出反激文章展示了非反馈路电压随其他路负载变化。这里的数值由项目的绕组矩阵求解器计算。','CROSS')

    section(doc,'10  拓扑覆盖与原厂资料索引')
    para('截至规则版 '+REVISION+'，以下三类拓扑可按规格生成初版。反激自动选型采用固定频率 SSR。')
    tab(['拓扑','接入状态与主要校核'],[(k,v) for k,v in SCOPE.items()],[1.52,5.58])
    h('原厂资料')
    for key in SOURCES:
        if key in ('FLYBACK-DCM','MP6005','RCD','CROSS'): continue
        label, detail, _ = SOURCES[key]
        p = doc.add_paragraph()
        vendor_link(p,key)
        p.add_run('  ·  '+detail)
    note('反激补充资料见第 8–10 页。每个拓扑区分原厂规格、项目自定余量、实物料号及其测试条件。')
    doc.save(output)


if __name__=='__main__':
    parser=argparse.ArgumentParser()
    parser.add_argument('--cases',type=Path,help='Folder with current Buck, Boost and flyback example snapshots')
    args=parser.parse_args()
    if args.cases:
        cases=[json.loads((args.cases/(name+'.json')).read_text(encoding='utf-8')) for name in ('buck-vm','buck-pcm','boost-pcm','flyback-ccm','flyback-dcm','flyback-multi')]
    else:
        from design_engine.initial_design import generate,form_options
        cases=[generate(dict(imin=1.,control_mode=mode)) for mode in ('Voltage Mode','Peak Current Mode')]
        cases.append(generate(dict(topology='BOOST',imin=.5)))
        cases.extend(generate(dict(topology='FLYBACK',conduction=m,imin=2/3)) for m in ('CCM','DCM'))
        form=form_options(json.loads((ROOT/'examples/40W_CCM_3OUT_FLYBACK.json').read_text(encoding='utf-8')))
        spec={k:form['values'][k]*scale for k,_,scale,_ in form['fields']}
        cases.append(generate(dict(spec,topology='FLYBACK',windings=form['windings'])))
    build(*cases,Path(__file__).with_name(DOCUMENT))
