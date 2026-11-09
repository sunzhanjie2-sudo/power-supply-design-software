"""Rebuild the editable calculation reference; retain original circuit figures.

Run with the bundled artifact Python. --source must be the preserved original,
not the already rebuilt reference. Equations are native OMML, not screenshots.
"""
import argparse
import re
from pathlib import Path
import sys
from docx import Document

sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from docx_layout import new_document, paragraph, table, figure, figure_pair, equation, section
from app_resources import resource_path


def build(source,output):
    old=Document(source)
    images=[]
    for shape in old.inline_shapes:
        rid=shape._inline.xpath('.//a:blip')[0].get('{http://schemas.openxmlformats.org/officeDocument/2006/relationships}embed')
        images.append(old.part.related_parts[rid].blob)
    # Original attachment: four compensation diagrams, then three gate
    # figures. Our rebuilt reference places the gate figures first. Support
    # either source without silently swapping circuits and waveform images.
    captions=[p.text for p in old.paragraphs if p.text.startswith(('图 6-', '图 10-'))]
    if len(images)>=7 and captions and captions[0].startswith('图 6-'):
        images=images[3:7]+images[:3]+images[7:]
    # Code-native redraws preserve the original circuit connectivity while
    # removing screenshot-only hints and incomplete lecture annotations.
    for index,filename in ((0,'opamp3_clean.png'),(3,'tl431f_clean.png')):
        resource=resource_path('comp_images')/filename
        if len(images)>index and resource.is_file():
            images[index]=resource.read_bytes()
    d=new_document('计算方法与公式说明',
        '软件计算内核详解  热阻与钳位应力更新版  2026-10-21',
        '开关电源设计与环路分析  ·  计算方法与公式说明')
    P=lambda t:paragraph(d,t)
    S=lambda t:paragraph(d,t,True)
    E=lambda t,n=None,de=None:equation(d,t,n,de)
    def T(h,r,w=None):
        cols=()
        if h[1] in ('Lmin 的软件表达式',): cols=(1,)
        if h[1] in ('Gd0','代码中的 M₁','Gc0'): cols=(1,2)
        if h[1]=='主开关电压应力': cols=(1,)
        return table(d,h,r,w,math_columns=cols)
    def chapter(title):
        if re.match(r'^\d+\.\d+',title):
            d.add_heading(title,2)
        else:
            section(d,title)
    def H(title): d.add_heading(title,2)
    P('本文面向研发、设计评审与软件使用者，说明软件实际采用的计算路径、数学模型、参数单位与适用边界。覆盖 Buck、Boost、Buck-Boost、Flyback、QR-Flyback 和低侧有源钳位正激六种拓扑。公式与当前源码对应，不将理想化结果表述为样机测量或器件额定值。')
    P('保留原文四类补偿电路与三幅栅电荷参考图，公式采用可编辑 Word 原生数学对象。本版统一六种拓扑的预设效率与最终效率口径；沿用原版零极点输入及⑨页简化支路，并明确其与标准二型补偿器的区别。')
    H('阅读导航')
    T(['章节','内容','主要代码 / 页签'],[
        ('1','计算路径、单位与符号','power_stage / loss_model'),
        ('2–4','稳态 PWM、QR 与有源钳位正激','② 功率级 / active_clamp'),
        ('5','时域波形、并联电容与 FFT 分带','② / ⑦ waveforms / capripple'),
        ('6–7','器件应力、半导体与磁件损耗','③ / ④ semiconductor / magnetics'),
        ('8–9','小信号模型、补偿器与 K 因子','⑤ plants / loop_tuning'),
        ('10','补偿元件正反算与兼容限制','⑨ comp_design'),
        ('11–12','RCD、总损耗、效率与扩展分析','⑧ / ⑥ design_api'),
        ('13 / 附录','报告口径、复核清单与资料','report_docx / tests'),
        ('14–15','多绕组输出与 MP6005 PSR','① isolated_outputs / mp6005'),
        ('16–17','逐对耦合、钳位与绕制几何评估','winding_coupling / winding_layout'),
        ('18','多路主反馈环路与各路响应','multi_output_loop / loop_charts'),
    ],[.75,3.55,2.8])
    S('重要：计算值 ≠ 额定值；模型内通过 ≠ 已验证硬件稳定；效率曲线 ≠ 实测曲线。软件未提供输入范围 / 温度 / 器件容差的完整认证模型。')

    chapter('1  计算路径与符号约定')
    H('1.1  一次设计计算的顺序')
    P('GUI 将输入（包括预设效率）换算为 SI → 求解工作点 → 构造周期波形 → 计算器件、磁件、电容与其他已建模损耗 → 汇总最终计算效率并复核差值。未启用耦合矩阵时使用固定预设效率的等效负担模型；启用逐对耦合后按第 16 章的显式电路求解，预设效率仅作初值。⑤页仅为已有小信号模型显示结果，新耦合模型不沿用旧 Bode。Word 导出刷新当前设计，与程序共享绘图函数，不依赖页签是否已打开。最终效率不自动覆盖预设效率，也不自动重整定补偿器。')
    T(['变量','含义 / 内部单位','容易混淆的约定'],[
        ('Vin / Vo / Po','输入 / 输出电压 V；输出功率 W','Buck-Boost 的 Vo 输入为幅值，VM 对象保留反相符号'),
        ('fs / Ts','Hz / s；Ts=1/fs','QR 的界面 fs 是频率上限，工作频率另求'),
        ('N / Np / Ns','N=Np/Ns；原 / 副边整数匝数','多路采用已解析的实际匝数；N 用于自动匝数预设计'),
        ('L / Lm_forward','H','反激标称 L=励磁电感；矩阵 L=开路自感 Lp；正激 L=输出电感'),
        ('C / Rc / ESL','F / Ω / H','ESR 是电阻；ESL 是电感；两者不属于容量'),
        ('Rs / A_sense / ma','Ω / 倍数 / A·s⁻¹','ma 为输入电流等效斜坡，不是 V/s'),
        ('B / Ae / Ve / Wa','T / m² / m³ / m²','界面 mm²、cm³ 仅为显示转换'),
        ('J / ρ / h','A/m² / Ω·m / W·m⁻²·K⁻¹','J=4×10⁶ A/m² 等于 4 A/mm²'),
        ('fz / fp / ω','Hz / Hz / rad/s','所有频率输入先按 ω=2πf 转换'),
        ('KP','积分器系数','不是普通无量纲 Kp；Gc 含 KP/s'),
    ],[1.35,2.7,3.05])
    E('R = ','Vo²','Po'); E('Io = ','Po','Vo')
    H('1.2  通用电流均方根')
    E('Irms² = Dx · (Ipk² + Ipk·Imin + Imin²) / 3')
    P('该式描述一段线性斜坡在全开关周期内的均方贡献。Dx 是该段持续时间 / 周期；多个不重叠段的均方值相加后开方。不要将不同段的 RMS 直接相加。')

    chapter('1.3  预设效率：设计输入与最终结果分离')
    P('eta_guess 为左侧规格区的可编辑设计输入，采用比例值（0.93 即 93%）；合法范围为 0<η₀≤1。默认 40 W CCM 反激预设为 93%。target_eta 则是效率页的优化 / 评审目标，两者不是同一参数。旧配置缺少 eta_guess 时使用默认值。')
    E('Pin,est = ','Po','η₀')
    E('Ploss,budget=Po(1/η₀−1)；Iin,est=Pin,est/Vin')
    E('U=Vo/η₀；Req=U/Io=R/η₀；Io=Po/Vo')
    P('统一一阶等效输出电压负担：先让理想功率级驱动电压 U、功率 Pin,est，因此内部与实际输出的平均电流均为 Io。该转换保持分段线性波形的伏秒、电荷和输入功率平衡；它不是把所有电流乘以 1/η₀，更不会把实际输出电压改为 U。Buck / 正激的电感平均电流仍是 Io，反激 / Boost 等的输入电流、占空比与峰值则随工作点变化。')
    P('η₀预算包括整体整流与其他损耗，因此稳态不再另加旧工作点参数 Vf（仅为历史配置兼容保留）。真实 Vf_diode、Rd_diode 和防反二极管参数仍进入最终损耗。η₀=1 表示理想工作点，不表示有损耗的器件最终效率必为 100%。')
    E('mean(iin)≈Pin,est/Vin；mean(ic)=0')
    E('ηfinal=Po/(Po+ΣPloss)；Δη=ηfinal−η₀')
    E('ΔPin=Po+ΣPloss−Pin,est')
    P('损耗预算只是工作点假设，不再次加入 ΣPloss，避免重复计损。QR 也保持此输入，取消历史效率固定点迭代。|Δη|>2 个百分点提示复核（经验设计阈值，并非精度或收敛保证）；用户可调整预设后重新计算与整定。最终计算效率可能高于或低于预设，仍不是样机实测效率。')
    S('适用边界：单个效率数值无法唯一确定每个器件的真实压降、损耗分布和谐振波形。本软件选择等效输出负担这一统一工程近似；真实电流斜率、器件阻断电压和动态极点应以逐器件非理想仿真与实测复核。波形输入功率取 Pin,est，最终损耗反算输入功率另列，二者有差值时不宣称已经闭环自洽。')

    chapter('2  固定频率 PWM 稳态模型')
    H('2.1  Buck：降压')
    P('本章 U=Vo/η₀、Req=R/η₀；Vo、Po、Io 仍表示实际输出需求。所有模式判定、RMS、L / C 初选、磁件与波形都使用同一效率工作点。')
    E('DCCM = U/Vin；ΔIL = (Vin−U)D/(fsL)')
    E('Imin = Io−ΔIL/2；Ipk = Io+ΔIL/2')
    P('先按 CCM 求 ΔIL；Io≥ΔIL/2 时采用 CCM。否则进入 DCM，电感从零开始上升、下降至零后驻留。')
    E('DDCM = √[2IoLU fs / (Vin(Vin−U))]')
    E('Dp = (Vin−U)D/U；Ipk=(Vin−U)D/(fsL)')
    E('Lmin = 1.5(Vin−U)DCCM/(2fsIo)')
    H('2.2  Boost：升压')
    E('DCCM=1−Vin/U；IL,avg=Io/(1−D)')
    E('ΔIL=VinD/(fsL)；Ipk=IL,avg+ΔIL/2；Imin=IL,avg−ΔIL/2')
    E('DDCM=√{L[(2M−1)²−1]/(2ReqTs)}；M=U/Vin')
    E('Ipk=VinDTs/L；Dp=2Io/Ipk')
    E('fRHP = ','(1−D)²Req','2πL')
    P('仅 CCM 保留此低频右半平面零点；DCM 的低频近似忽略开关频率附近的高频极点 / 零点。电感的平均电流和输出负载电流不是同一个量。')
    H('2.3  Buck-Boost：反相升降压')
    E('DCCM=U/(Vin+U)；IL,avg=Io/(1−D)')
    E('DDCM=M√[2L/(ReqTs)]；M=U/Vin；Ipk=VinDTs/L')
    E('Dp=2Io/Ipk；fRHP=(1−D)²Req/(2πDL)')
    P('负载电流由 OFF 段三角电流的面积决定。CCM 与 DCM 的开关、二极管 RMS 分别按 D 与 Dp 计算；电感 RMS 按 D+Dp 计算。')

    chapter('2.4  Flyback：反激 CCM / DCM')
    P('N=Np/Ns；整体损耗预算通过 U 进入反射电压，不另叠加 Vf。固定频率反激以原边励磁电感 L 为能量存储电感。')
    E('Vr=NU；DCCM=Vr/(Vin+Vr)')
    E('Ip,on,avg=Pin,est/(VinD)；ΔIp=VinD/(fsL)')
    E('Imin=Ip,on,avg−ΔIp/2；Ipk=Ip,on,avg+ΔIp/2')
    P('Imin<0 时切换 DCM。CCM 与 DCM 均使用 Pin,est=UIo，消除历史原边平均电流与次级电荷平衡口径不一致的问题。')
    E('DDCM = √[2Pin,est Lfs]/Vin')
    E('Ipk=VinDTs/L；Is,pk=N·Ipk；Dp=2Io/Is,pk')
    E('fRHP = ','VinN(1−D)','2πLIo')
    P('此 fRHP 为同一效率工作点下的低频带宽提示；⑤页小信号对象使用 U、Req 与实际 D，有限 RHP 零点与该提示一致。没有由此建立真实损耗动态，仍需完整反馈链和实测复核。')
    H('2.5  最小 L / C 建议的真实含义')
    T(['拓扑','Lmin 的软件表达式','解释'],[
        ('Buck','1.5(Vin−U)D/(2fsIo)','在 CCM 边界基础上加 1.5 倍系数'),
        ('Boost','1.5VinD(1−D)/(2fsIo)','使用 CCM 的 D，而非 DCM 重解 D'),
        ('Buck-Boost','1.5VinD(1−D)/(2fsIo)','同为 CCM 初选，不是绝对下限'),
        ('Flyback','1.5VinD/(fs·0.4Ip,on,avg)','按 40% 原边纹波初选，不排除有意 DCM'),
    ],[1.3,3.1,2.7])
    E('Δv目标=ripple_target·Vo')
    P('Cmin 统一只表示电荷纹波所需容量，单位为 F。ESR 纹波是独立电压检查，不能把 ΔI·Rc/Δv 这一无量纲条件当作电容量。GUI、API 与 Word 使用 design_checks.py 的同一核查表；合成阻抗波形的低频 ripple_pp 是最终纹波检查值。')
    E('Buck 电荷容量：C≥ΔIL/(8fsΔv)')
    E('Boost / 反激电荷容量：C≥IoD/(fsΔv)')

    chapter('3  QR-Flyback：变频 BCM 与谷底近似')
    P('软件将 QR 视为单谷底 BCM：每周期退磁到零，再等待半个 L-Coss 谐振周期。工作频率随输入、负载、励磁电感及效率变化，界面 f_sw 仅作 f_max 限制。')
    E('Pin=Pin,est=Po/η₀；Vr=NU；Tring=π√(LCoss)')
    E('a=L(1/Vin+1/Vr)；b=Pin·a')
    E('Ipk = ','b+√(b²+2LPinTring)','L')
    E('Ton=LIpk/Vin；Tdemag=LIpk/Vr')
    E('fs = ','1','Ton+Tdemag+Tring')
    E('D=Ton/Ts；Dp=Tdemag/Ts')
    P('由 ½LIpk²=Pin(aIpk+Tring) 解正根，再以该工作点计算损耗与最终 η。预设 η₀在本轮始终固定，不迭代或写回输入；兼容入口 recompute_qr_eta 也改为单次计算。次级三角电流平均值保持为 Io。')
    H('局限与误差来源')
    P('Coss 被当作常数；没有多个谷底选择、跳周期、控制 IC 延迟、非线性电容或谷底剩余电压。损耗分支将开通损耗和 Coss 损耗置零，是理想谷底假设，不表示实际零损耗。二极管 Qrr 仍按用户输入计算，不能因 BCM 就默认忽略。')
    P('环路在此模式下复用低频 DCM 单极点对象，没有包含变频控制器的采样与谷底逻辑。其无有限低频 RHP 零点，只是本模型的简化结论。')

    chapter('4  有源钳位正激：独立双磁件模型')
    P('新增拓扑为低侧有源钳位、主 / 辅助 MOSFET、正向 / 续流两只二极管的单输出正激。输出电感 L 与变压器励磁电感 Lm_forward 分开输入；不沿用反激的储能逻辑，也未实现同步整流。')
    H('4.1  输出电感与 CCM / DCM')
    E('Vs=Vin/N；DCCM=U/Vs')
    E('ΔIL=(Vs−U)D/(fsL)')
    E('DDCM=√[2IoLUfs/(Vs(Vs−U))]')
    E('Ipk=(Vs−U)DTs/L')
    E('Dp=(Vs−U)D/U')
    P('CCM 以 Io≥ΔIL/2 判定；DCM 电流归零后输出电感驻留，但变压器仍在整个 OFF 段复位。有效 D 未扣除死区，只校核 2tdead<min(D,1−D)Ts 和 D<forward_d_max。')
    H('4.2  伏秒复位与双极性励磁')
    E('Vcl=Vin/(1−D)；Vreset=Vcl−Vin')
    E('VinD−Vreset(1−D)=0')
    E('ΔIm=VinDTs/Lm；Im,pk=ΔIm/2')
    E('i主,ON=iL/N+im；i辅助,OFF=im')
    E('I辅助,rms=Im,pk√[(1−D)/3]')
    P('理想励磁电流在 ±Im,pk 间往返。主开关 RMS 按包含励磁分量的有符号线性电流端点求均方；应力峰值取绝对值。实际漏感换流和体二极管导通过程未求解。')
    H('4.3  钳位电容初选与带宽建议')
    E('Vhump = ','VinD(1−D)','8Lmfs²Ccl')
    E('fr=1/[2π√(LmCcl)]；feff=(1−D)fr')
    E('fc,max=min(fs/10,feff/5)')
    E('Ccl,min=VinD(1−D)/(8Lmfs²·0.05Vcl)')
    P('Ccl,min 采用隆起为钳位基准电压 5% 的预算；超过 10% 发出小纹波近似不足提示。增大 Ccl 降低隆起，但也降低谐振频率和建议带宽。软件该模型不保留低频 RHP 零点，不包含完整钳位谐振传函。')

    chapter('4.4  有源钳位正激：波形、应力与使用示例')
    P('输出电感电流在导通段上升、续流段下降，DCM 余段为零。励磁电流始终按 ON / OFF 两段线性摆动。辅助管在 OFF 段承担励磁电流；钳位电压用基准值加 4Vhump·x(1−x) 抛物线表示，x 为归一化 OFF 时间。该图是教学 / 初选波形，不是完整谐振仿真。')
    E('V器件,pk=(Vcl+Vhump)(1+ring_margin)')
    E('ΔB=VinDTs/(NpAe)；Bpk=ΔB/2')
    T(['40 W 内置示例','输入 / 计算值','含义'],[
        ('Vin → Vo / Po / fs','30 V → 30 V / 40 W / 250 kHz','与此前反激案例保持需求一致'),
        ('N / Lout / Lm / Ccl','0.5 / 68 μH / 220 μH / 47 nF','输出电感与励磁电感分离'),
        ('η₀ / D / Vcl / ΔIL','93% / 0.538 / 64.9 V / 0.877 A','预设效率下的初步估算'),
        ('fc 建议上限','约 4.58 kHz','取 min(fs/10,feff/5)'),
        ('绕组初值','Np=6；Ns=12','实物 AL、磁导率、气隙尚需选型核实'),
    ],[1.65,2.85,2.6])
    P('损耗口径不自动给予 ZVS 优惠：主开关保留硬开通和 Coss 项；辅助管仅算导通、栅驱动、保守 Coss，遗漏其完整交叠损耗。正向和续流二极管分别计算，钳位电容 ESR 计入效率，RCD 电阻不适用于此拓扑。')
    S('动态边界：未模拟非线性 Coss、漏感谐振、栅极时序的真实死区、磁通不平衡、体二极管、突发 / 跳周期、全负载 ZVS 范围与控制 IC 保护。死区可行性通过不能证明 ZVS；变压器对称 Bpk 假设也不能排除实物偏磁饱和。')

    chapter('5  时域波形与电容纹波分析')
    H('5.1  波形构造')
    P('make_waveforms 默认生成两开关周期、每周期 2048 点的均匀时间序列。分段电流由预设效率工作点的 D、Dp、峰 / 谷电流决定；开关电压用等效模型的状态切换。输出电容电流：Buck / 正激为 iL−Io，其余为整流电流−Io，周期均值理论为零（离散采样有小误差）。输出电压保持 Vo 加纹波。源侧电流仅 Boost 连续取 iL，Buck、反相 Buck-Boost、反激和 QR 取 ON 段开关电流，正激包含 ON 段反射负载及励磁电流；输入电容电流为源侧电流减去其平均值。')
    E('Ic,rms=√(mean(ic²))；icin=iin−mean(iin)')
    H('5.2  并联电容复阻抗')
    E('Zj(f)=ESRj+j[2πf·ESLj−1/(2πfCj)]')
    E('Ij(f)=Ibank(f)·Yj(f)/ΣYk(f)；Yj=1/Zj')
    P('两只电容在每个频率独立复数分流，不使用固定比例分流。单只电容的电流可因相位与谐振环流大于组总电流；不能把两只 RMS 相加。频率模型假定 C、ESR、ESL 为常数且参数有效。')
    H('5.3  输出纹波电压合成')
    E('V(f)=Ic(f)·Zeq(f)；Zeq=1/ΣYj')
    P('waveforms.py 去直流后用 rFFT → 每频点乘合成阻抗 → irFFT 还原周期电压。分别计算 ESL=0 的低频纹波和含 ESL 的完整纹波。ripple_pp 是低频最大值减最小值；ripple_pp_total 为完整波形峰峰值；esl_spike_pp 实际字段为 ESL 差分波形的最大绝对幅值，不应按名称误读为峰峰值。')
    S('理想电流阶跃配合 ESL 会产生强尖峰，数值随采样和带宽变化。真正尖峰需使用器件寄生、布局、开关速度和测量带宽验证。')

    chapter('5.4  整周期 DFT 分带与功率守恒')
    P('稳态波形覆盖整数开关周期时，capripple.py 使用无窗 rFFT，逐一保留所有正频率 bin。以单边 Parseval 权重计算均方值，Nyquist bin 单独使用一倍权重，其余正频率使用两倍权重。每个 bin 按复阻抗分流后归入对应频带，不再只选谐波附近的一个峰值。非整周期输入才采用五项平顶窗并按时域 RMS 校准总能量，该分支只是估算。平顶窗为：')
    E('w[n]=a₀−a₁cosθ+a₂cos2θ−a₃cos3θ+a₄cos4θ')
    E('θ=2πn/(Nsamples−1)')
    T(['系数','值'],[('a₀','0.21557895'),('a₁','0.41663158'),('a₂','0.277263158'),('a₃','0.083578947'),('a₄','0.006947368')],[2,5.1])
    E('p[k]=2·|X[k]/Nsamples|²')
    P('上式适用于非 DC 且非 Nyquist 的正频点；Nyquist 权重为 1。分带边界为 (h−0.5)fs 至 (h+0.5)fs；最低带为 <0.5fs，最高带为 >20.5fs。全部 bin 均计入，保证频带能量没有漏项。')
    E('Ij,band²=Σ(p[k]·|Yj(f[k])/(ΣYk(f[k]))|²)')
    E('Ij,total=√(ΣIj,band²)；PESR,j=ESRj·Ij,total²')
    P('GUI、损耗和报告直接复用 compute_design 返回的 capacitors 快照，均使用两周期、每周期 2048 点；不存在页签独立重采样。单电容满足 Parseval；并联电容可能出现谐振环流。非理想尖峰和窄共振仍需采样收敛检查及仿真复核。')

    chapter('6  功率器件应力与损耗')
    H('6.1  电压 / 电流应力')
    T(['拓扑','主开关电压应力','二极管反向电压'],[
        ('Buck','Vin(1+ring)','Vin'),('Boost','U(1+ring)','U'),
        ('Buck-Boost','(Vin+U)(1+ring)','Vin+U'),
        ('Flyback / QR','Vin+KcVr；未设钳位时仅知 Vin+Vr','U+Vin/N'),
        ('ACF-FORWARD','(Vcl+Vhump)(1+ring)','整流 Vreset/N；续流 Vin/N'),
    ],[1.4,3.4,2.3])
    P('RMS 由分段三角波求取。峰值和平均电流来自工作点，正激分别给出主 / 辅助 MOSFET 和正向 / 续流二极管。没有器件实际额定值输入，故应力表不是合格判定表。')
    P('整流二极管反压未考虑寄生尖峰应力，具体应力需实测；选型建议留有耐压余量。反激 MOS 以 Kc=Vclamp/Vreflect 确定钳位上限 Vin+Kc·Vreflect，不再叠加振铃裕度；波形仍按漏感能量求解，可低于上限。Kc 不是器件额定耐压降额系数。未设有效 Kc 时仅显示理想平台，不能作为已覆盖尖峰的应力上限。')
    H('6.2  主 MOSFET 栅电荷时间法')
    E('Ron=Rg_drive+Rs_on+Rg')
    E('Roff=Rg_drive+Rs_off+Rg')
    E('t₁=−(Qg_th·Ron/Vth)·ln(1−Vth/Vgs)')
    E('t₂=−(Qgs·Ron/Vgp,on)·ln(1−Vgp,on/Vgs)−t₁')
    E('t₃=Qgd·Ron/(Vgs−Vgp,on)')
    E('t₆=Qgd·Roff/Vgp,off')
    E('t₇=−[(Qgs−Qg_th)·Roff/(Vgp,off−Vth)]·ln(Vth/Vgp,off)')
    E('t₈=3Qg_th·Roff/Vth')
    P('时间公式依据 mosfet损耗计算.xlsx；ln 为自然对数，代码使用等价的 log1p 以降低浮点消减误差。电荷使用 C，电阻使用 Ω，时间结果为 s。开通电流变化阶段为 t₂，米勒段为 t₃；关断对应 t₆+t₇。t₁ / t₈ 不直接纳入交叠损耗；t₈ 是表中 3RC 近似（残余电压约为阈值的 5%），不是下降到严格 0 V 的精确时间。参数须满足 0<Vth<Vgp,on<Vgs、Vgp,off>Vth、Qgs≥Qg_th，电荷和电阻非负；非法参数或负 t₂ 会报错，不再以分母钳位掩盖。平台电压分别依据开通和关断电流工作点选取。')
    S('参考表 F26 引用了空白 H15；此处按 F15 的内部栅阻修正，关断总栅阻为 Roff。参考表中的 nC / ns 与代码的 C / s 相差 10⁹ 倍，数值对照须先统一单位。')

    chapter('6.3  栅电荷参考图与损耗合成')
    if len(images)>4: figure(d,images[4],'图 6-1  原文保留：MOSFET 开关过程参考',6.4)
    E('Pcond=Rds,on·Isw,rms²')
    E('Pon=k_sw·Vds·Ids,on·(t₂+t₃)fs')
    E('Poff=k_sw·Vds·Ids,off·(t₆+t₇)fs')
    E('Pcoss=½CossVds²fs；Pgate=QgVgsfs')
    P('软件使用开通谷值 / 关断峰值电流；k_sw 为用户选择的交叠系数（默认 0.25），不是由器件波形自动识别。常数 Rds,on 与 Coss 无温度或电压依赖。QR 模式 Pon=Pcoss=0；正激主开关未默认作此减免。')
    H('二极管与辅助开关')
    E('Pdiode=Vf·Iavg+Rd·Irms²+Qrr·Vr·fs')
    P('Qrr>0 时按上式计反向恢复；包括 QR 分支，不自动判断真实恢复机制。辅助 MOSFET 的损耗为 Rds_aux·Iaux,rms²+Qg_aux·Vgs·fs+½Coss_aux·Vblock²fs，未包含完整交叠与换流能量。同步整流 / LLC 的公式不属于当前可用拓扑，原文相关条目已移除。')
    if len(images)>5:
        chapter('6.4  平台电压与电荷输入的选取')
        figure_pair(d,images[5],images[6],'图 6-2（上）电流 / 栅压曲线；图 6-3（下）栅电荷参考（保留原图）')
        P('图示仅帮助理解参数。以选定器件的数据手册、实际 Vds / Id、驱动电压及温度为依据；不能从未给定测试条件的示意图读出通用参数。')

    chapter('7  磁件初选、磁通与损耗')
    H('7.1  面积乘积、匝数与气隙')
    E('Ap,L = ','L·Ipk·Irms','Bmax·J·Ku')
    E('Ap,T = ','2Po','Bmax·J·Ku·fs')
    E('NL=ceil[LIpk/(BmaxAe)]')
    E('lg=μ₀NL²Ae/L；μ₀=4π×10⁻⁷ H/m')
    E('Np,auto=ceil[VinDTs/(BmaxAe)]')
    E('Ns,auto=max(1,round(Np/N))')
    P('按数据库磁芯的 Ae·Wa 选择面积乘积满足要求的磁芯，或使用用户指定芯型。上面的电感气隙公式忽略磁芯磁阻。变压器另按有限磁导率磁路计算，μr=0 使用材料手册初始磁导率，le 固定由 Ve/Ae 派生，只读显示，le 与平均匝长 MLT 分别处理。')
    E('AL=Lm/Np²；L0=μ₀·μr·Ae·Np²/le')
    E('lg=μ₀·Ae·Np²/Lm−le/μr')
    P('反激与准谐振使用原边 L，正激变压器使用 Lm_forward。lg 为折算到 Ae 的总等效气隙，忽略边缘磁通，需以加工后 AL 测量调整。若 lg<0，目标 Lm 高于无气隙电感 L0，显示不可实现并复核匝数、磁导率与磁芯。该估算不改变电气输入 Lm，也不会自动填充三维模型的真实加工气隙。依据 TI UCC2863x SLUSBW3D 式(45)，https://www.ti.com/lit/ds/symlink/ucc28630.pdf。')
    H('7.2  真实峰值磁密与摆幅不同')
    E('电感 / 反激：Bpk=L·Ipk/(NAe)')
    E('正激变压器：ΔB=VinDTs/(NpAe)，Bpk=ΔB/2')
    P('饱和校核使用峰值 |B|，磁芯损耗使用实际波形的峰峰摆幅 ΔB。反激 CCM 的直流偏置不能省略；正激 Bpk=ΔB/2 依赖对称复位假设。Bmax 是初选匝数目标，Bsat 是饱和核查输入，二者不是同一参数。')
    H('7.3  绕组电阻与趋肤修正')
    E('δ=√[ρ/(πfsμ₀)]；x=dwire/δ')
    E('Fr=1+x⁴/(48+0.8x⁴)')
    E('Rdc=ρ·MLT·N/[nparallel·nstrand·πdwire²/4]')
    E('Pcu=Fr·Rdc·Irms²')
    E('fill=Σ(N·nparallel·nstrand·Awire)/Wa')
    S('b 为线圈并绕根数，nstrand 为单根线股数，旧工程及示例 b=1。6 匝、并绕 2 根仍为 6 匝，截面为 12 根线。固定线径与股数时 b 加倍使铜面积加倍、DCR 与 J 减半；电气工作点需重新求解。fill 只统计裸铜，不含绝缘与爬电；Fr 是简化修正，假定均匀分流，未求解并绕环流及邻近效应。')

    chapter('7.4  磁芯损耗：实际采用 NSE 波形积分')
    P('材料常数采用 Pv[mW/cm³]=k·f[kHz]^α·B[T]^β。1 mW/cm³=10³ W/m³，因此体积 Ve 使用 m³ 时最终乘 10³Ve。软件保留经典 Steinmetz、iGSE 与 NSE 闭式函数，但正常磁件设计路径统一采用实际 B(t) 的 NSE 积分，不是三种模型按拓扑自动切换。')
    E('Psin=k(f/1000)^α·Bpk^β·10³Ve')
    E('Cα=∫_0^(2π)|cosθ|^αdθ')
    E('kN=k/[(2π)^(α−1)Cα]')
    E('PNSE = (ΔB/2)^(β−α) · kN · 10³Ve · A')
    E('A = ','∫_0^(Tms)|dB/dtms|^α dtms','Tms')
    P('程序使用 np.gradient 在 ms 时间轴上求斜率，累加 |dB/dt|^αΔt，再除以记录时长。驻留段斜率为零；直流偏置不额外修正材料损耗常数。闭式三角解仅用于交叉验证：')
    E('Ptri=kN(2fs/1000)^α(ΔB/2)^β·F·10³Ve')
    E('F=D^(1−α)+Dp^(1−α)')
    H('iGSE 保留函数')
    E('Cfit=0.2761+1.7061/(α+1.354)')
    E('ki=k/[2^(β+1)π^(α−1)Cfit]')
    E('PiGSE=ki(2fs/1000)^αΔB^βF·10³Ve/2^α')
    P('这些损耗公式需要材料参数在对应温度、频率与磁密范围内有效；未拟合直流偏磁、磁滞回线、局部温度或材料频率分区。超过数据手册范围不应外推为可靠损耗。')
    H('7.5  温升近似')
    E('ΔT=(Pcu+Pcore)·Rth')
    P('变压器采用用户输入的整体至环境热阻 Ri-a，字段 Rth_transformer，单位 K/W。全部副边及 PSR 辅助绕组的铜损均先汇总再计算温升。默认 100 K/W 仅为初始假设，不来自磁芯目录；须按实测或热设计填写。此模型给出稳态整体温升，不预测局部热点，也不自动迭代热态铜阻。')
    P('以下表面积与对流公式仅用于独立电感，不再用于变压器：')
    E('Asurf=2(1.5Ve^(1/3))²')
    E('ΔT = ','Pcu+Pcore','h·Asurf')
    P('h 为电感可编辑对流系数；表面积由有效体积经验估计。GUI、API、Word 与 Excel 统一使用 temp_rise_limit，默认 40 K，可在评审参数中调整。没有环境温度与局部热网络，不能直接给出热点温度或热设计合格结论。')

    chapter('8  小信号功率级模型')
    H('8.1  CCM 电压模式对象')
    P('s 为拉普拉斯变量，D′=1−D，C 为主输出电容。本章 Gvc 核心公式中的 Vo、Po、R 统一取内部等效量 U、Pin,est、Req（不是实际输出需求），Vf 取零，D 来自同一预设工作点；核心对象算出后按下式折回实际输出增益。η₀在小信号分析中冻结，不建模损耗随频率和温度的变化。标准四种 PWM 对象不含 ESR 零点。单路兼容模型中第二并联电容未进入环路传函；多输出模型使用各路两只电容的折算总容量，见第 14 章。')
    E('Gvc,out(s)=η₀·Gvc,core(s)')
    E('Buck：Gvc = ','Vin/Vm','1+sL/R+s²LC')
    E('Boost：δ=1+sL/(D′²R)+s²LC/D′²')
    E('Gvc = ','[Vo/(D′Vm)]·[1−sL/(D′²R)]','δ')
    E('Buck-Boost：Gvc = ','−[Vo/(DD′Vm)]·[1−sDL/(D′²R)]','δ')
    E('Flyback：δF=1+sL/[(ND′)²R]+s²LC/(ND′)²')
    E('Gvc = ','[Vo/(DD′Vm)]·[1−sDL/((ND′)²R)]','δF')
    P('Buck-Boost 的 CCM VM 传函带负号，GUI 相位连续化会反映反相直流增益；反馈极性必须单独核对。GUI、API 自动整定、报告和角点均调用 build_loop_models，使用上述固定效率等效对象，避免各入口使用不同的理想 D。改变预设效率后应重新核查裕度，必要时重新整定，不自动改写旧补偿器。')
    chapter('8.2  DCM / BCM 低频单极点')
    E('Gvc=(Gd0/Vm)/(1+s/ωp)')
    T(['拓扑','Gd0','ωp'],[
        ('Buck','(2Vo/D)(1−M)/(2−M)','(2−M)/[(1−M)RC]'),
        ('Boost','(2Vo/D)(M−1)/(2M−1)','(2M−1)/[(M−1)RC]'),
        ('Buck-Boost / Flyback / QR','Vo/D','2/(RC)'),
    ],[2.05,2.6,2.45])
    P('M=Vo/Vin，D 取实际工作点。单路定频反激 SSR 的 DCM 峰值电流环路按每周期储能线性化，含采样增益、补偿斜坡和各输出电容 ESR。上表为传统占空比近似。QR 的变频模型另见专题说明。')

    chapter('8.3  峰值电流模式：调制器与内环')
    E('Fm = ','fs','Rs·A_sense·[ma+(M₁−M₂)/2]')
    E('Fi=Rs·A_sense')
    T(['对象','代码中的 M₁','代码中的 M₂'],[
        ('Buck','Vin/L','Vo/L'),('Boost','Vin/L','(Vo−Vin)/L'),
        ('Buck-Boost','Vin/L','Vo/L'),('Flyback','Vin/L','N(Vo+Vf)/L')
    ],[1.8,2.65,2.65])
    P('以上是当前内核采用的等效斜坡定义，不要将 Buck 的 M₁=Vin/L 直接当作真实 ON 段电感斜率 (Vin−Vo)/L。分母中的 ma+(M₁−M₂)/2≤0 时，改用 (M₁+M₂)/2；之后还将斜坡分母绝对值至少限制为 1。回退保持有限增益，不等于完成离散采样次谐波稳定性验证。')
    H('Buck / Boost / Buck-Boost 的二阶表示')
    E('Gvc=Gc0·NRHP(s)/[1+s/(Qcωc)+(s/ωc)²]')
    P('令 S=1+t₁+t₂。Buck 取 ωc=√S/√LC；Boost / Buck-Boost 取 ωc=D′√S/√LC。其 Gc0、t₁、t₂ 与阻尼分母的代码对应如下：')
    T(['对象','Gc0','t₁ / t₂'],[
        ('Buck','VoFm/(DS)','FmVoFi/(DR)；FmFvVo/D'),
        ('Boost','VoFm/(D′S)','2FmVoFi/(D′²R)；FmFvVo/D′'),
        ('Buck-Boost','−VoFm/(DD′S)','FmVo(1+D)Fi/(D′²RD)；−FmFvVo/(DD′)'),
    ],[1.35,1.9,3.85])
    E('Buck：Fv=−D²TsRsA_sense/(2L)')
    E('Boost：Fv=D′²TsRsA_sense/(2L)')
    E('Buck-Boost：Fv=−D′²TsRsA_sense/(2L)')
    P('Qc 的分子分别为 R√(C/L)√S 或 D′R√(C/L)√S；分母记为 H，下一页列出。NRHP 为各对象 VM 分子的零点因子（Buck=1）。')

    chapter('8.4  电流模式阻尼、反激与正激折算')
    E('Buck：H=1+RCFmVoFi/(DL)')
    E('Boost：H=1+RCFmVoFi/(D′L)−FmFvVo/D′')
    E('Buck-Boost：H=1+RCFmVoFi/(DL)+FmFvVo/D′')
    H('反激直接构造闭合电流内环')
    E('Fv=−D′²TsRsA_sense/(2L)')
    E('Gvd=[Vo/(DD′)]·[1−sDL/((ND′)²R)]/δF')
    E('Gid = ','NVo(1+D)[1+sRC/(1+D)]','D(ND′)²R·δF')
    E('Gvc = ','FmGvd','1+Fm(FiGid+FvGvd)')
    P('Fi 把电流对象折算回 PWM 比较器端。不能泛化为“所有频率的环路增益永远与 Rs 精确成反比”；分母内还有电流反馈和拓扑相关系数。反激 GUI 的历史 fm_fallback 提示标志使用相反的斜坡差方向，与实际 _pwm_fm 触发条件不一致；请按上面的真实分母检查，不仅依赖提示文字。')
    H('有源钳位正激对象')
    P('以次级折算 Buck 为基础：Vin,eq=Vin/N，采样电阻 Rs,eq=Rs/N；等效斜坡 ma,eq=N(ma+Vin/Lm)。PCM 使用继承的 Buck 二阶模型；该 PCM 分支不含 ESR 零点。')
    E('VM：Gvc = ','(Vin/N)(1+sRcC)/Vm','1+s(L/R+RcC)+s²LC(1+Rc/R)')
    P('仅正激 CCM VM 保留主输出电容 ESR 零点；DCM 仍采用 Buck 单极点近似。没有 Ccl / Lm 的钳位谐振完整动态，带宽应低于 min(fs/10,(1−D)fr/5)。普通对象的缺省理想 ESR 与正激 VM 的 ESR 口径不同，需要明确区分。')

    chapter('9  补偿器、Bode 指标与 K 因子整定')
    H('9.1  软件当前的补偿器阶数')
    E('二型 Gc = ','KP(1+s/ωz₁)','s(1+s/ωp₁)')
    E('三型 Gc = ','KP(1+s/ωz₁)(1+s/ωz₂)','s(1+s/ωp₁)(1+s/ωp₂)')
    T(['选择','有限零点','极点总数','输入参与'],[
        ('type2','1','2（含原点）','KP / fz1 / fp1'),
        ('type3','2','3（含原点）','KP / fz1 / fz2 / fp1 / fp2'),
        ('auto','按模式决定','PCM→二型；VM→三型','显式类型不受控制模式覆盖'),
    ],[1.1,1,2.15,2.85])
    P('PI 选项已撤回。加载此前 controller_type=PI 的配置会迁移为 auto，数值保留但传函已不是 PI，应重新整定确认。五个原版零极点输入保留；二型忽略 fz2 / fp2，而原点极点由公式的 1/s 隐含，不显示为可填频率。')
    H('9.2  开环与裕度')
    E('T(s)=Gc(s)Gvc(s)')
    E('PM=180°+∠T(j2πfc)；|T(j2πfc)|=1')
    E('GMdB=−20log₁₀|T(jω₁₈₀)|')
    P('相位按对数频率扫频后 unwrap 连续化；不能只用 np.angle 的 ±180° 主值读取非最小相位对象。在没有穿越时显示未定义；没有有限 −180° 穿越，不等于无限硬件稳定裕量。多个穿越必须查看全部，必要时采用 Nyquist 与闭环极点判据。')
    H('9.3  K 因子')
    E('boost=PM目标−90°−∠Gvc(fc)')
    E('二型：K=tan(45°+boost/2)')
    E('三型：K=tan(45°+boost/4)')
    E('fz=fc/K；fp=Kfc')
    E('KP₂=ωc/[K|Gvc(jωc)|]')
    E('KP₃=ωc/[K²|Gvc(jωc)|]')
    S('三型使用两个相同零点 / 两个相同有限极点。GUI 与 API 的 auto 均按 PCM→二型、VM→三型解析；底层 kfactor_tune 直接传 auto 才按 boost≤75° 选型。二型可行范围约 ±90°，三型保守范围 ±170°；不可行时不写回参数。')

    chapter('9.4  整定后的频率限制与复核')
    P('GUI 一般将目标 fc 限制到实际 fs/6；QR 使用当前计算得到的变频频率，而不是界面频率上限。正激先受 fc,max=min(fs/10,feff/5) 约束。当前整定并不自动保证 RHP 零点带宽条件通过，仍需检查 fRHP 及最小裕度。')
    P('整定在指定 fc 处匹配增益与相位，不保证该点是唯一穿越。GUI、API 与 Word 均调用 analyze_loop，扫描上升和下降穿越，以最接近目标的下降穿越显示 fc，并按全部穿越的最小 PM 核查。未检出下降穿越时 fc / PM 显示未定义，不用扫描末端代替。QR 环路使用预设效率下求得的实际工作频率。')
    P('Word 的扫频范围为 0.01 Hz 到 max(10fs,1 MHz)，6000 对数点；该范围内未检出有限穿越时标记未定义，不用末端频率替代。GM 由控制库的 margin 计算；数据和图使用同一传递函数。')
    H('从软件到硬件的核查顺序')
    T(['复核步骤','为什么需要'],[
        ('核对反馈极性与采样增益','避免反相对象相位和归一化尺度理解错误'),
        ('检查实际有效零 / 极点','④的抽象补偿器与⑧简化支路并非必然一致'),
        ('检查所有 0 dB 穿越','单点匹配不保证最小裕度'),
        ('检查 RHP / fs / 钳位谐振约束','低频近似在这些频率附近可能失效'),
        ('加入 ESR、延迟、器件带宽和光耦','软件简化对象不含完整实物反馈链'),
        ('仿真和 FRA 测量','用实际工作点、容差与温度验证'),
    ],[2.5,4.6])

    chapter('10  补偿网络阻容正反算：原版路径')
    P('⑨页保留四类参考网络的原版算法：普通运放三型、跨导运放三型、TL431+光耦无快车道和快车道三型。此页的“二型简化支路”独立勾选，未与⑤页的抽象 type2 一一绑定。请按本章限制使用，不能从复选框名称推断标准二型硬件已经完整实现。')
    H('10.1  普通运放三型')
    if images: figure(d,images[0],'图 10-1  普通运放补偿网络（按原连接关系重绘）',4.8)
    E('KP=1/[R₁(C₁+C₂)]')
    E('ωz₁=1/(R₂C₁)；ωz₂=1/[(R₁+R₃)C₃]')
    E('Cs=C₁C₂/(C₁+C₂)')
    E('ωp₁=1/(R₂Cs)；ωp₂=1/(R₃C₃)')
    P('这里 p₁ / p₂ 指两个有限极点，另有原点积分极点。原图用 fp1=0、fp2 / fp3 编号，与④输入编号不同，本文统一使用有限极点编号。')
    E('S=1/(KPR₁)；r=ωz₁/ωp₁')
    E('C₂=Sr；C₁=S−C₂；R₂=1/(ωz₁C₁)')
    E('R₃=ωz₂R₁/(ωp₂−ωz₂)；C₃=1/(ωp₂R₃)')
    S('正向要求 R₁ / KP>0，两个目标零点分别低于相应极点。原版简化支路把 C₂=C₃=0：只剩原点极点和一个零点，不保留标准 type2 的高频极点。')

    chapter('10.2  跨导运放三型')
    if len(images)>1: figure(d,images[1],'图 10-2  原文保留：跨导运放网络',5.0)
    S('原附件参考图的输出 C₂ / C₃ 标号与代码定义相反：本章公式及界面参数按代码取 C₂ 与 R₃ 串联、C₃ 并联。使用原图时须先交换该两项标号，不应直接抄图。')
    E('KP=gm·R₂/[(C₂+C₃)(R₁+R₂)]')
    E('ωz₁=1/(R₃C₂)；ωz₂=1/(R₁C₁)')
    E('Cs=C₂C₃/(C₂+C₃)')
    E('ωp₁=1/(R₃Cs)；ωp₂=(R₁+R₂)/(R₁C₁R₂)')
    E('R₁=R₂(ωp₂−ωz₂)/ωz₂；C₁=1/(ωz₂R₁)')
    E('S=gmR₂/[KP(R₁+R₂)]；r=ωz₁/ωp₁')
    E('C₃=Sr；C₂=S−C₃；R₃=1/(ωz₁C₂)')
    P('R₂ / gm 必须为正，ωp₂>ωz₂；分压反馈电压 VoR₂/(R₁+R₂) 应与 Vref 相容。原版简化支路令 C₁=C₃=0，需要用户提供 R₁；同样只保留一个零点和积分极点，不实现④标准二型的有限高频极点。')

    chapter('10.3  TL431 + 光耦：无快车道')
    if len(images)>2: figure(d,images[2],'图 10-3  原文保留：无快车道 TL431 网络',4.3)
    P('LED 电阻接独立偏置 Vdd，视为交流地；反馈点用理想虚地模型。元件命名沿用 TND381-D p.45 参考图。')
    E('KP=CTR·Rpullup/(R_LED·R₁·C₁)')
    E('ωz₁=1/(R₂C₁)；ωz₂=1/(R₁C₃)')
    E('ωp₁=1/(R₃C₃)；ωp₂=1/(Rpullup·Cp)')
    E('Cp=C₂+Copto')
    P('Cp 是代码中的光耦输出总并联电容。原文用“∥”记号描述这一项容易被误读为串联等效值，现明确写为 C₂+Copto。应按参考图的实际连接核对，不能脱离输出节点和负载模型套用。')
    E('C₁=CTR·Rpullup/(KP·R_LED·R₁)')
    E('R₂=1/(ωz₁C₁)；C₃=1/(ωz₂R₁)')
    E('R₃=1/(ωp₁C₃)')
    P('由目标 ωp₂ 求 Cp 再解 C₂=Cp−Copto。若 Cp<Copto，得到负电容，表示目标极点高于寄生电容所允许范围；旧正向路径未对所有这种情况显式拒绝，需自行复核。额外提示光耦极点≥10fc、TL431 阴极偏置、LED 电阻上限。这些是设计提示，不是包括 CTR 温漂 / 光耦带宽的完整偏置与动态仿真。')

    chapter('10.4  TL431 + 光耦：快车道与反向限制')
    if len(images)>3: figure(d,images[3],'图 10-4  快车道 TL431 网络（按原连接关系重绘）',4.7)
    E('KP=CTR·Rpullup/(R_LED·R₁·C₁)')
    E('ωz₁=1/(R₁C₁)')
    E('ωz₂=1/[(R_LED+R_pz)C_pz]')
    E('ωp₁=1/(R_pzC_pz)')
    E('ωp₂=1/(Rpullup·Cp)')
    P('LED 电阻接输出电压，存在直接快车道。在原版抽象三型拟合之外，实物高频还可能出现平坦增益地板 CTR·Rpullup/R_LED，不能仅凭抽象 Gc 判读全部高频动态。')
    H('10.5  反向、占位与回代的真实范围')
    P('反向按各网络 eval 函数提取 KP 与有限零极点。缺失角点返回 inf，GUI 将缺失频率写为 1 GHz 占位；这不是真实器件极点，也不是完整的传函约简。仅三型中成对相同的零 / 极点可抵消；其他组合或二型选择不能自动保证消失支路的等价实现。')
    P('恢复后的正向回代只比较 KP 相对误差，不逐一验证全部目标零极点。此前文档称“有效零极点全部匹配”的描述已纠正。补偿 RC 本次按用户要求回退，不继续引入 PI 网络或新的二型实现；需完整电路可实现性验证时，应单独推导实际网络并仿真。')

    chapter('11  RCD 吸收钳位')
    P('仅固定频率 / QR 反激且 Kc>1 时启用。K、Kc 和波动比例 dC 来自⑦页；原边励磁电感、峰值电流、反射电压和频率来自当前工作点。')
    E('Lleak=(1−K)Lm；Vcl=KcVr')
    E('Eleak=½LleakIpk²')
    E('Pres=Eleak·fs·Vcl/(Vcl−Vr)')
    E('Rsnub=Vcl²/Pres')
    E('ΔVcl=dC·Vcl；Csnub=Vcl/(ΔVclRsnubfs)')
    P('K 是软件经验漏感比例公式的输入。若使用互感耦合定义，常见漏感折算可能包含 1−k²，不能将任意仪表读出的耦合系数不加判断地填入。建议先测得漏感再按 K=1−Lleak/Lm 映射到本模型。')
    P('本节漏感能量式是历史快速初估，未扣除漏感对 Coss 的充电能量。当前最终功耗及 R/C 由第16章同一波形模型计算：快速模式采用剩余钳位电流，矩阵模式积分钳位支路。不能在这些结果上再次叠加本节 Pres。钳位电压是上限，零漏感或能量不足时不会自动达到该上限。钳位电容电压采用同一电流驱动的小纹波 RC 重建，不表示完整寄生瞬态。')
    P('有源钳位正激使用另一套复位 / Ccl 模型，不将上述 Pres 计入效率；不能把反激 RCD 表作为正激辅助管和钳位电容选型结果。')

    chapter('12  总损耗、效率与辅助分析')
    E('Ptotal=Psemi+Pmag+Pcap+Pcap,in+Psense+Prcd+Pdin+Pdout+Pclamp+P_ctrl')
    E('Pin,final=Po+Ptotal；ηfinal=Po/(Po+Ptotal)')
    E('Pcap=ΣESRout,j·Ioutcap,j,rms²')
    E('Pcap,in=ΣESRin,j·Iincap,j,rms²')
    E('Psense=Rs·Isw,rms²')
    E('Pdin=Vf,din·mean(iin)+Rd,din·mean(iin²)')
    E('Pdout=Vf,dout·Io+Rd,dout·Io²')
    E('Pclamp=ESRclamp·Iclamp,rms²（仅正激）')
    P('防反二极管损耗由勾选开关控制；输入 / 输出电容 ESR 均按逐频点复阻抗分流后的 RMS 求和并计入 Ptotal。所有损耗由同一预设效率下的工作点和波形求得，损耗反算 Pin,final 不代替本轮波形依据 Pin,est。效率预算 Ploss,budget 不再次计入 Ptotal；半导体项已经包含实际整流管 Vf_diode。分析异常显式报错，不静默回退。')
    H('12.1  效率-负载曲线与参数扫描')
    P('界面和双端点报告固定 Vin min 的磁芯、匝数、平均匝长和线径，以同一预设 η₀重算各负载的工作点与损耗；QR 也不迭代效率。无效点留空，曲线不是实测。旧标量 API 可按各点重新设计磁件，不能混同固定硬件结果。参数优化目标仅为模型内效率，不含采购、EMI 或制造约束。')
    H('12.2  API 角点与负载阶跃估算')
    P('工程评审扫描需求页两端输入 ×10/25/50/75/100%负载，共10点；两端相同则5点。固定 Vin min 全部磁件和绕组，电容、采样与补偿不变，重算各点工作点、损耗与环路；失败显式列出。旧 run_corners 标量 API 保留 ±10%默认范围。扫描不穷举输入区间、容差和温度；A/B 对比不修改设计或自动评判优劣。')
    E('ΔVESR=ΔI·ESReq')
    E('ΔVC≈ΔI/(2πfcCtotal)')
    E('ΔV估算≈ΔVESR+ΔVC')
    P('load_transient 是一阶负载阶跃估算。忽略 ESL、闭环阻尼、限流、负载边沿和大信号行为；默认 fc 为 fs/10 或正激带宽上限。电容取并联总 C、ESR 取并联等效，不能代替真实瞬态仿真。')

    chapter('13  Word 报告口径与评审清单')
    P('通过顶部“导出报告”、文件菜单或 Ctrl+E 默认导出 .docx；也可选择旧 Markdown 摘要。Word 按导出快照重新生成图，不改变参数或执行自动整定，包含需求、工作点、关键波形、器件、电容纹波、磁件、环路、钳位、损耗、效率与附录输入。帮助菜单可直接打开本文档，需要系统安装 Word / WPS 或其他 DOCX 阅读器。')
    H('输入范围与双端点完整报告')
    P('输入需求必须满足 0 < Vin min ≤ Vin max。界面显式选择当前端点，所有图表和结果对应所选实际输入电压。旧配置迁移为上下限均等于原 V_in，不自行扩展范围。两个端点共用 Vin min 确定的自动磁件与全部绕组；PSR 辅助绕组也保持固定，不为各端点分别整定。')
    P('Word 报告始终整理两个端点，与界面当前选中项无关：先放并列摘要、较不利端点、共同硬件、检查差异及共轴曲线，再依次展开完整 Vinmin 与 Vinmax 报告。章节与图题带端点标记。没有有限穿越、环路不适用或计算失败时明确说明，不用零或另一端结果替代。两端比较不构成整个输入区间、全负载或全温认证；不能预先假定 Vin min 对所有指标都是最坏工况。')
    H('13.1  需要特别解释的检查')
    T(['检查','本模型中“满足”的含义','仍需完成'],[
        ('纹波','ESL=0 的低频峰峰值不超目标','带宽受控的真实尖峰和负载动态'),
        ('磁密','Bpk<用户输入 Bsat','最坏温度、容差、偏磁和启动瞬态'),
        ('窗口填充','裸铜面积 / Wa≤1','骨架、绝缘、爬电、绕法与工艺'),
        ('温升','变压器按用户热阻；独立电感按对流模型','环境温度、热点、风道和实测'),
        ('环路','当前模型所检出穿越的裕度条件','反馈全链路、容差、Nyquist 和 FRA'),
        ('效率','计入的损耗口径满足目标','完整系统功耗、热态器件与实测'),
    ],[1.1,2.75,3.25])
    P('软件损耗未包含完整控制 / 辅助供电、整流桥、PCB / 连接器、EMI 滤波、热态参数、绕组邻近效应和全部吸收网络。MP6005 PSR 额外计入典型静态电流与分压损耗，不能代表完整控制器供电和热损耗。输入与输出电容 ESR 已计入。效率可能偏乐观，但不能保证一定是实测上限，也没有固定百分点的误差保证；预设 / 最终效率差值是设计假设复核，不是实测误差。')
    H('13.2  本次更新校正的原文表述')
    P('统一电荷容量、温升、环路穿越与电容纹波快照；公式使用原生分式、上下标、根式与积分结构，并连续编号；保留补偿网络和栅电荷参考图，明确原版简化支路、未实现的模型和必须实测的边界。')

    chapter('14  隔离拓扑的多绕组输出')
    P('支持固定频率反激、QR 反激和有源钳位正激，最多 6 路功率输出；PSR 辅助采样绕组另计。只输入主反馈或 PSR 基准路的电压，其余路电压按整数副边匝数比估算并只读显示。每路分别设置输出功率、整流器 Vf/Rd/Qrr、两组并联电容、防反、纹波目标、匝数、裸铜线径和并绕股数；正激还可指定各路输出电感与磁芯。①页拓扑、位号及输出核算表采用同一数据。')
    H('14.1  总功率、主反馈与折算基准')
    E('Pout = Σ P_j'); E('I_j = P_j/V_j')
    E('N_j = Np/Ns_j')
    E('V_j,est = V_b·Ns_j/Ns_b')
    P('b 为唯一的 SSR 主反馈路，或 PSR 辅助采样的标称基准路。多路计算采用已解析的实际整数 Np 和各 Ns；N 仍指 OUT1 的预设计 Np/Ns，用于尚未指定匝数的初始选匝。非反馈路电压由上式更新，不再作为另一个独立目标。匝比估算未包含整流压降、绕组压降和交叉调整率。切换基准且保持等效电压时只是变换参考；修改新反馈路电压则会改变设计工作点。PSR 没有独立次级闭环。')
    P('旧 JSON 的 Ns=0 且保存了多路目标电压时，仅用旧电压比例生成初始整数匝数；界面保存已解析匝数。之后改变反馈电压不会暗中改变这些绕组匝数，非反馈路的旧电压值不能覆盖匝比推算结果。')
    H('14.2  未启用耦合矩阵的反激与 QR 标称模型')
    E('w_j = P_j/Pout'); E('I_s,j(t) = N_j·w_j·I_p,off(t)')
    E('Σ (I_s,j(t)/N_j) = I_p,off(t)')
    P('原边励磁电流对应全部输出功率。次级在退磁段按功率权重分配电流，保持总安匝和各路平均电荷平衡；每路电容电流为整流电流减该路直流负载电流。这是标称设计近似，不会预测真实二极管抢流、绕组耦合或交叉调整率。反激 L 是共享励磁电感，各路正激 L 字段不参与反激工作点。')
    chapter('14.3  多路正激：各路必须均为 CCM')
    E('L_eq = 1/(Σ ((V_j/V_b)²/L_j))')
    E('C_eq = Σ (C_j·(V_j/V_b)²)')
    P('每路按独立 L、C 和负载求解，变压器原边电流为次级负载折返加励磁电流；共享 PWM 占空比。原边综合电流采用折算等效电感，环路采用全部输出电容能量折算到主反馈路的 C_eq。任一路进入 DCM 时，其所需占空比可能不同，本版本明确拒绝该标称工况，角点记录为无效，不将各路当作可独立稳压的变换器。')
    H('14.4  损耗、磁件与模型边界')
    P('共享磁芯和原边铜损只计一次；副边逐绕组累加交流修正铜损与窗口面积；正激逐路累计输出电感损耗。原边开关、输入电容、采样、RCD 或钳位电容只计一次，各路整流、电容和输出防反独立累计。PSR 辅助采样绕组加入窗口与分压负载的铜损，未假定它供应完整 VCC 功率。')
    E('Acu_j=nparallel_j·nstrand_j·π·d_j²/4')
    E('J_j=Irms_j/Acu_j')
    E('Rdc_j=ρ·MLT·Ns_j/Acu_j')
    P('线径为单股裸铜直径，nstrand 为单根完整线的股数，b 为完整线圈并绕根数。每路输出可独立配置 b，缺省 1；电流密度采用整个绕组周期 RMS 电流除以总裸铜面积，A/m² 除以一百万后显示 A/mm²。DCR 由铜电阻率、MLT、整数匝数与铜面积生成。MLT=0 时沿用磁芯目录估计，未含端接、额外引线或未输入的温升电阻变化。利兹线压扁和几何分束不改变铜面积。')
    P('SSR 仅关闭所选反馈路的环路。由匝比定义得到的电压不能再当作独立目标进行取整误差合格判定；未反馈路仍应做独立负载、空载、热态压降和耦合复核。当前角点按相同比例改变全部输出功率并固定绕组几何，不等比例负载需另行仿真。')

    chapter('15  MP6005 原边反馈 PSR')
    P('依据 MPS MP6005 Rev.1.1（2024-10-11）。仅用于固定频率反激，MODE 悬空。器件支持 PSR CCM；重载 PWM 标称 250kHz，轻载先钳住最小峰值电流再降低开关频率。SSR 正激支持不表示 PSR 也支持正激。软件不把通用 SSR 对象的 Bode 结果直接改名为 PSR。')
    H('15.1  辅助绕组与反馈分压')
    E('V_aux = (N_a/N_s)·(Vo + V_f)')
    E('β = R_FB,L/(R_FB,H + R_FB,L)')
    E('V_FB = β·(V_aux - I_reg·R_FB,H)')
    E('I_reg = g_reg·R_s·Iin,est')
    E('Vo,设定 = (2V/β + I_reg·R_FB,H)·N_s/N_a - V_f')
    P('Na=0 时按辅助目标电压选整数匝数。RfbL=0 时按标称采样与压降补偿直流偏置反算下电阻。Rreg+Rs 根据手册阻值档位选择补偿跨导；不在规定区间内标记需复核，不猜测档位。平均 SENSE 电压按 Rs×预估输入平均电流估算，未模拟滤波动态、实际二极管压降变化或内部采样保持。分压设定误差检查不包括 Vref 容差，不能当作输出精度。')
    T(['Rreg+Rs 范围','补偿跨导 / μA·mV⁻¹','典型设置'],[
        ('0–1.3kΩ','0','无补偿'),('3–3.6kΩ','0.05','3.3kΩ'),('6.2–7.5kΩ','0.1','6.8kΩ'),
        ('12.7–13kΩ','0.2','12.7kΩ'),('24.9–28kΩ','0','另一抖频设置档')])
    E('I_FB,负向 ≈ Vin·N_a/(N_p·R_FB,H)')
    P('负向 FB 电流必须小于 1mA，上分压电阻小于 100kΩ；输入推荐范围 8–80V。VCC/GATE 推荐最大 16V，界面的 MOS Vgs 应与 VCC 相符，内置 VCC 典型值为 8.5V。辅助采样绕组未默认承担 VCC 供电。')
    chapter('15.2  采样窗口、最低电感与限流')
    E('L_min = (N_p/N_s)·(Vo + V_f)·0.7μs·R_s/(0.033V)')
    E('t_33 = L·(0.033V/R_s)/((N_p/N_s)·(Vo + V_f))')
    E('t_con = Dp·Ts')
    E('R_s,建议 ≤ 0.8·0.160V/Ipk')
    P('以 33mV 的最小峰值电流低端检查次级导通时间，建议不少于 0.7μs。当前工作点次级导通时间要求至少覆盖 0.6μs，去除 300ns 消隐后显示有效窗口；占空比上限 70%。CS 峰值按 0.8×160mV 初选裕量检查，并另外核对 140mV 限值低端。实际电感、限流和时序仍受容差、内部 LEB 与驱动延迟影响。')
    H('15.3  轻载降频与最小能量负载')
    E('Ipk,最小 ≈ 0.036V/R_s')
    E('fs,估算 ≈ 2·Pin,est/(L·Ipk,最小²)')
    E('Pout,最低 ≈ ηguess·L·Ipk,最小²·30kHz/2')
    P('固定 250kHz 求解的峰值 SENSE 电压低于典型 36mV 时，软件仅在 DCM 内使用固定最小峰值电流的能量平衡估算降频。若低于典型 30kHz 的最低能量负载，直接拒绝稳压假设并提示预负载。PFM 不提供 PWM Bode / PM / GM，也不提供一阶负载阶跃估算；这不是完整 MP6005 状态机或轻载模式验证。')
    chapter('15.4  COMP 物理二型网络与 PWM 环路近似')
    if len(images) >= 8:
        # Preserve the existing reviewed vector-derived diagram. This also
        # lets the artifact runtime edit native Word math without needing
        # the engineering application's plotting/scipy dependencies.
        figure(d,images[7], '图 15-1  MP6005 PSR 采样与 COMP 网络简化参考；不展开 VCC、EN 及保护外围')
    else:
        from topology_diagram import draw_psr_network
        from report_docx import _chart
        figure(d,_chart((7.1,2.2),lambda fig:draw_psr_network(fig.subplots(),standalone=True)),
               '图 15-1  MP6005 PSR 采样与 COMP 网络简化参考；不展开 VCC、EN 及保护外围')
    E('G_c(s) = g_m·(1 + s·R_z·C_z)/(s·(C_z + C_p)·(1 + s·R_z·C_z·C_p/(C_z + C_p)))')
    E('fz = 1/(2πR_zC_z)'); E('fp = (C_z + C_p)/(2πR_zC_zC_p)'); E('KP = g_m/(C_z + C_p)')
    E('H_FB = β·N_a/N_s')
    P('COMP 为 Rcomp 与 Ccomp 串联，再与 Cpole 并联到地；gm 取典型 0.59mA/V。含积分极点、一个有限零点和一个有限极点。整定仅写回 PSR 专用 Rcomp/Ccomp/Cpole，不覆盖 SSR 网络。')
    P('PWM 小信号按通用 PCM 对象、CS 增益 11、辅助分压 H_FB 及半周期延迟的一阶 Padé 近似构造。多路电容按刚性匝比折算；内部斜坡、动态补偿及采样保持未精确建模，裕度仅供候选补偿初选，须用厂商模型或样机 FRA 验证。PFM 清空旧曲线与裕度。')
    E('P_ctrl ≈ Vin·0.8mA + V_aux²/(R_FB,H + R_FB,L)')
    P('典型静态与分压损耗计入最终效率；栅驱动已计入 MOS，不重复统计。未建立外部 VCC、驱动输出电阻热损耗与完整辅助供电模型。')

    from coupling_report import add_coupling_reference
    add_coupling_reference(d)
    from winding_report import add_winding_reference
    add_winding_reference(d)
    from loop_report import add_multi_output_loop_reference
    add_multi_output_loop_reference(d)

    chapter('附录 A  代码索引与验证入口')
    T(['文件','主要入口','用途'],[
        ('power_stage.py','compute_operating_point / compute_qrflyback_op','PWM / QR 稳态'),
        ('active_clamp.py','compute_forward_op / forward_waveforms','正激工作点、钳位和波形'),
        ('waveforms.py','make_waveforms / cap_bank_ripple','波形与并联纹波电压'),
        ('capripple.py','capacitor_ripple_analysis / cap_bank_esr_loss','纹波频带与复阻抗分流'),
        ('semiconductor.py','device_stress / semiconductor_losses','应力与主要器件损耗'),
        ('magnetics.py','design_inductor / design_transformer / core_loss_nse_waveform','磁件、磁损、铜损与温升'),
        ('plants.py','各 Converter 类 / make_compensator','VM / PCM 与二 / 三型传函'),
        ('loop_tuning.py','analyze_loop / kfactor_tune','统一穿越与 K 因子整定'),
        ('multi_output_loop.py / loop_charts.py','build_coupled_loop / draw_multi_output_response','周期映射小信号、全路响应与稳定性检查'),
        ('comp_design.py','各 solve / eval 函数','原版阻容正反算'),
        ('loss_model.py','compute_design / total_losses','固定预设工作点后的最终损耗效率'),
        ('design_api.py','run_design / run_corners / load_transient','自动化分析'),
        ('input_voltage_range.py / input_range_report.py','calculate_input_endpoints / export_input_range_docx','Vin min 固定硬件、双端点计算与完整对照报告'),
        ('report_docx.py','export_design_docx','独立图表、完整 Word 报告'),
        ('isolated_outputs.py','compute_isolated_op / multi_magnetics','多路功率与磁件汇总'),
        ('mp6005.py','design_psr / compensation_parts','MP6005 PSR 核算与物理 COMP'),
        ('winding_layout.py / winding_ui.py','assess_winding_window / WindingUI','净窗口、逐层线束与等比例截面'),
        ('calculation_\nscheduler.py','LatestCalculationWorker','最新请求、取消与有限数值缓存'),
    ],[1.7,2.8,2.6])
    S('回归入口：tests/gate_charge_check.py、quick_check.py、api_check.py、forward_check.py、controller_check.py、report_check.py；GUI 图表检查为 gui_chart_check.py。测试仅覆盖已列场景，不代表安规认证、误差全覆盖或实物验证。')
    S('符号索引：η₀ / ηfinal 为预设 / 最终效率；U / Req 为内部等效输出电压 / 负载；D / Dp 为导通 / 退磁占空比；Bpk / ΔB 为峰值磁密 / 磁密摆幅；Gc / Gvc / T 为补偿器 / 对象 / 开环。其余定义见各章首次说明。')

    chapter('附录 B  理论资料与版本说明')
    P('本文的首要对象是软件实际实现。理论资料可用于推导和校核，但不能据此推定软件已经实现书中全部寄生、控制采样和热模型。')
    P('Texas Instruments，The duty cycle paradox（SSZTCO3，2015）：真实占空比受器件压降和损耗影响。本文等效输出负担是为保证软件预设效率、伏秒与电荷一致性而采用的一阶工程近似，并非该资料给出的完整逐器件非理想模型。')
    S('https://www.ti.com/document-viewer/lit/html/SSZTCO3/GUID-292D8B9D-5297-46CB-98DA-C7099A8F41F7')
    P('R. W. Erickson、D. Maksimović，《Fundamentals of Power Electronics》，第 3 版：稳态、DCM、平均小信号、磁件与磁芯损耗的理论基础。项目参考资料目录含原书。')
    P('Ridley / Basso 峰值电流模式模型：作为 PCM 平均建模的背景，实际代码采用本文所列等效系数与简化二阶形式，并非完整离散采样模型。')
    P('D. Venable，The K Factor，Powercon 10，1983：二 / 三型零极点对称放置的背景资料。')
    P('onsemi TND381-D，C. Basso，The TL431 in the Control of Switching Power Supplies：TL431 / 光耦快车道与无快车道参考电路。保留附件电路连接关系；运放及快车道参考图重绘以清理截图提示与残缺讲义标注。')
    P('Texas Instruments SLUA535A（2020 修订），Understanding and Designing an Active Clamp Current Mode Controlled Converter Using the UCC2897A：低侧钳位运行、钳位电容与电流模式环路的参考。')
    S('https://www.ti.com/lit/an/slua535a/slua535a.pdf')
    P('Texas Instruments SLUP262，Incorporating Active-Clamp Technology to Maximize Efficiency：开关电压、钳位电容隆起与谐振讨论的参考。')
    S('https://e2e.ti.com/cfs-file/__key/communityserver-discussions-components-files/234/slup262.pdf')
    chapter('版本与使用边界')
    P('MPS MP6005 Rev.1.1（2024-10-11），采样与补偿机制见第 16–18 页，元件初选见第 19–21 页，典型反激应用见第 27 页。')
    S('https://www.monolithicpower.com/en/documentview/productdocument/index/version/2/document_type/Datasheet/lang/en/sku/MP6005GK/')
    P('本文件对应 2026-10-18 输入范围与双工况报告版；新版程序目录为 Input_voltage_range_update。启动仍为 40W CCM 单路反激，上下限均 30V，预设效率 93%，耦合矩阵默认关闭；用户自行填写实际输入范围。SSR 保留 auto / type2 / type3；PSR 使用物理二型 COMP 网络。保留 _internal 子目录，计算说明从帮助菜单打开。多路只有基准电压输入，其余按实际副边匝比估算；线径和股数旁显示 RMS 电流密度，耦合电路和铜损共用自动几何 DCR。t1–t8 MOS 图与 Word 报告共享快照；非理想耦合反激按第 18 章建立低频实验环路，不沿用旧 Bode；临时低频门槛仍停用，高频精度尚未验证。窗口几何评估继续支持等效圆束、利兹线等面积压扁、疏绕及密绕左右靠齐，以及同一绕组分配到不连续物理层；几何排布不反向修改铜面积、DCR 或 kij。数值线程限制、按需绘图和后台最新请求队列继续保留。')
    P('内容用于初选与设计复核，不是电源安全标准、器件规格书、量产工艺文件或样机测量报告。发现本文与源代码冲突时，以实际运行版本及计算入口为准并进行独立核验。')
    from docs.update_cross_regulation_documents import update_document
    update_document(d, 'reference')
    from docs.update_qr_cross_regulation_reference import update_document as update_qr_cross
    update_qr_cross(d)
    Path(output).parent.mkdir(parents=True,exist_ok=True)
    d.save(output)
    print(f'Saved {output}; tables={len(d.tables)}; images={len(d.inline_shapes)}; native equations={len(d.element.xpath(".//m:oMath"))}')


if __name__=='__main__':
    a=argparse.ArgumentParser(); a.add_argument('--source',required=True); a.add_argument('--output',required=True)
    args=a.parse_args(); build(args.source,args.output)
