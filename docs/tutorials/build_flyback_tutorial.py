"""Build a separate beginner tutorial with editable Word equations.

Consumes the unchanged engine snapshot collected beside the QA figures.
Run using the Codex bundled document Python. No source design or reference
document is edited, and no engineering result is retuned for publication.
"""
from pathlib import Path
import hashlib
import json
import math
import sys

from docx.shared import Inches, Pt
from docx.oxml import OxmlElement
from docx.oxml.ns import qn
from docx.enum.text import WD_ALIGN_PARAGRAPH

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
from docx_layout import new_document, paragraph, table, figure, equation, _font
import word_math as wm

ART = ROOT/'artifacts/tutorials/multi_flyback_20261023'
OUT = Path(__file__).with_name('多路反激电源设计入门教程.docx')
REF = ROOT/'docs/reference/计算方法与公式说明.docx'
DATA = json.loads((ART/'tutorial_data.json').read_text(encoding='utf-8'))
CASES = DATA['cases']
LO, HI = CASES
SPEC = DATA['spec']

# Tutorial-only notation. Shared equation renderer and electrical code remain
# unchanged. Explicit aliases produce actual native subscripts, not underscores.
wm.ALIASES.update({
    'Rload':'R_load','Vest':'V_est','Vset':'V_set','Lij':'L_ij','Lii':'L_ii',
    'Ljj':'L_jj','kij':'k_ij','λp':'λ_p','λj':'λ_j','Lpp':'L_pp',
    'Lps':'L_ps','Lsp':'L_sp','Lss':'L_ss','Ron':'R_on','Roff':'R_off',
    'Qpost,on':'Q_post,on','Qpost,off':'Q_post,off','Vplateau':'V_plateau',
    'Vceiling':'V_ceiling','Vc':'V_c','Prcd':'P_RCD','Eclamp':'E_clamp',
    'Nturn':'N_turn','Atotal':'A_total','Astrand':'A_strand','Irms,p':'I_rms,p',
    'Cbank':'C_bank','Pactual':'P_actual','Prated':'P_rated','Iload':'I_load',
    'Vtarget':'V_target','Vnom':'V_nom','Icap':'I_cap','kN':'k_N',
    'Tms':'T_ms','Qcycle':'Q_cycle','Vopto':'V_opto','ωz':'ω_z','ωp':'ω_p',
    'Ad':'A_d','Bc':'B_c','Bload':'B_load','Aclosed':'A_closed',
    'xnext':'x_n+1','xstate':'x_n','vc':'v_c','v_j':'v_j','i_j':'i_j',
    'vstate':'v','istate':'i','C_j':'C_j','R_j':'R_j','kth':'k_th',
    'i_d':'i_d','Δv_C':'Δv_C','v_Cbank':'v_Cbank',
    'V_d,理想':'V_d,ideal','I_k':'I_k','P_d,固定':'P_d,fixed',
    'P_rr':'P_rr','Vreverse':'V_reverse','L_pj':'L_pj','B_ref':'B_ref',
    'Fr_j':'F_r,j','Lp':'L_p','PvNSE':'P_v,NSE',
    'v_j,next':'v_j,next','P_j,actual':'P_j,actual','PMtarget':'PM_target',
    'Iclamp':'I_clamp','Vgp':'V_gp','Ids':'I_ds','Pv':'P_v',
    'Qgd,on':'Q_gd,on','Qgd,off':'Q_gd,off','Qpre':'Q_pre','Qpost':'Q_post',
    'GMdB':'GM_dB','Kc':'K_c','dC':'d_C','ma':'m_a',
    'ESR':'ESR','ESL':'ESL','MLT':'MLT','log':'log','d_outer':'d_outer',
})
wm.NAMES = sorted(wm.ALIASES, key=len, reverse=True)


def f(value, digits=4):
    if value is None:
        return '未定义'
    if not math.isfinite(float(value)):
        return '未定义'
    return f'{value:.{digits}g}'


def vals(path, scale=1, digits=4, unit=''):
    def read(c):
        v=c
        for k in path.split('.'):
            v=v[int(k)] if isinstance(v,list) else v[k]
        return f(v*scale,digits)+unit
    return [read(c) for c in CASES]


def build():
    baseline=hashlib.sha256(REF.read_bytes()).hexdigest()
    # This builder must leave the current reference unchanged; its historical
    # 2026-10-23 hash is provenance, not a ban on later authorized revisions.
    doc=new_document('多路反激电源设计入门教程',
        '用一份真实配置走完从需求到报告的计算过程',
        '多路反激电源设计入门教程')
    doc.core_properties.subject='初学者教程  原理 推导 数值算例 软件模型边界'
    normal=doc.styles['Normal']
    normal.font.size=Pt(11)
    normal.paragraph_format.line_spacing=1.2
    normal.paragraph_format.space_after=Pt(7)
    foot=doc.sections[0].footer.paragraphs[0]
    foot.clear();foot.alignment=WD_ALIGN_PARAGRAPH.RIGHT
    _font(foot.add_run('案例教程  ·  '),8)
    page=OxmlElement('w:fldSimple');page.set(qn('w:instr'),'PAGE');foot._p.append(page)
    eq_manifest=[]
    headings=[]

    def P(text):
        return paragraph(doc,text)
    def S(text):
        return paragraph(doc,text,True)
    def E(text):
        eq_manifest.append(text)
        p=equation(doc,text)
        p.paragraph_format.space_before=Pt(3)
        p.paragraph_format.space_after=Pt(7)
        return p
    def T(headers,rows,widths=None):
        rows=list(rows)
        t=table(doc,headers,rows,widths)
        for row in t.rows:
            for cell in row.cells:
                for p in cell.paragraphs:
                    p.paragraph_format.line_spacing=1.1
        # Keep short comparisons whole; longer parameter/corner tables repeat
        # their headers naturally on a following page.
        if len(rows)<=8 or headers[0]=='历史或备用字段':
            for row in t.rows[:-1]:
                for cell in row.cells:
                    for p in cell.paragraphs:
                        p.paragraph_format.keep_with_next=True
        return t
    def H(text):
        doc.add_heading(text,2)
    def C(text):
        p=doc.add_heading(text,1)
        # Continuous lesson layout prevents one-line chapter-tail pages.
        # Front matter and appendices remain clean, separate entry points.
        p.paragraph_format.page_break_before=(text=='阅读路线' or text.startswith(('1  ', '附录 B', '附录 C')))
        p.paragraph_format.space_before=Pt(20)
        headings.append(text)
    def F(name,caption,width=6.95):
        figure(doc,(ART/(name+'.png')).read_bytes(),caption,width=width)
    def pair_rows(items):
        return [(name,*vals(path,scale,digits,unit)) for name,path,scale,digits,unit in items]
    def source(text):
        # The beginner-facing code index is consolidated in Appendix C.
        # Repeating module lists at every lesson tail caused orphan pages.
        return None
    def practice(q,a):
        P('想一想  '+q)
        P('参考答案  '+a)

    P('这份教程写给刚接触反激电源设计的读者。你不需要先会控制理论，也不必一开始就理解矩阵。先沿着“电压、电流从哪里来，器件为什么发热，报告应该怎么看”这条线读下去，再回头学习后面的多绕组和环路模型。')
    P('案例文件是 40W CCM 多路反激.json。我们先做理想手算，再沿着原配置的实际模型计算，从结果中学习如何发现问题、复核假设。本例保留了未达到评审目标的部分，适合练习完整的设计判断，而不是只看一份全部通过的报告。')
    H('先知道这个例子的结论')
    P('输入范围为 20～30 V，开关频率为 250 kHz。OUT1 是 30 V 主反馈路，OUT2 和 OUT3 由绕组匝数决定参考电压。文件名保留“40W”，但三路配置功率相加是 33 W；进一步按实际恒阻负载求解后，总输出约为 32.65～32.66 W。教程会把这三个口径分开。')
    T(['读完后应能回答','本例的实际结果'],[
        ('为什么三路电流形状不同','主反馈 OUT1 为 CCM；OUT2 和 OUT3 为 DCM'),
        ('为什么 5V 不一定等于 5V','有漏感和压降，标称负载下约 4.54～4.55 V'),
        ('预设效率是不是最终效率','预设 93%；损耗汇总约 85.43% 和 87.03%'),
        ('为什么模型显示通过仍要复核','温升、5V 纹波、交叉调整率和物理补偿网络仍有待核查项'),
    ],[2.55,4.55])
    P('所有公式都是 Word 原生数学对象，可以在 Word 中点击后编辑。图中曲线是软件模型计算结果或导入曲线的重绘，不是示波器实测。数值通常保留 3～5 位有效数字；末位差异可能来自显示舍入。')
    S('编写依据  当前项目计算内核与该 JSON 的只读计算快照，2026 年 10 月 23 日。这里没有为新手省略模型限制；有些章节先给直观解释，再给进阶推导。')

    C('阅读路线')
    P('第一次阅读，建议先看第 1～4 章，再结合第 6～11 章观察电流、纹波、损耗和变压器。第 5 章的矩阵求解、第 14～15 章的环路与补偿器可以放到第二遍。')
    T(['章节','要解决的问题'],[
        ('1  需求和单位','原文件哪些值真正生效，为什么不能只看文件名'),
        ('2  反激工作原理','MOS 开通与关断时，能量分别流向哪里'),
        ('3  手算一个理想工作点','占空比、电流斜坡、峰值和 RMS 怎样得到'),
        ('4  软件计算顺序','预设效率和最终效率为什么不一样'),
        ('5  多绕组耦合','怎样从 kij 得到各路电流和输出电压'),
        ('6  波形和电流统计','平均值、峰值、RMS 和 CCM DCM 如何判断'),
        ('7  电容','容量、ESR、ESL 和并联分流怎样计算'),
        ('8  应力和 RCD','钳位尖峰、MOS 耐压与整流二极管反压'),
        ('9  MOS 损耗','两条导入曲线、四个事件和 t1 到 t8'),
        ('10  二极管损耗','逐点 If Vf 积分和防反二极管的区别'),
        ('11  变压器电气与温升','匝数、DCR、电流密度、磁芯损耗和热阻'),
        ('12  绕制窗口','利兹线压扁与交错绕制怎样做几何预评估'),
        ('13  总损耗与效率','损耗账本怎样相加，不重复计数'),
        ('14  多路输出环路','只有一个主反馈环，其余输出怎样跟随'),
        ('15  补偿电路','理想传递函数和 TL431 光耦电路为何不能画等号'),
        ('16  交叉调整率','16 个负载角点怎样形成电压包络'),
        ('17  报告与复核','如何读 Vinmin Vinmax 对比并安排验证'),
        ('附录','生效参数、公式对应代码、复习题与资料'),
    ],[2.15,4.95])
    P('阅读约定  “理想手算”用于建立量级概念；“本例软件结果”来自实际开启的耦合矩阵模型。两者假设不同，不能把理想公式算出的数值当作软件应该精确复现的答案。')

    C('1  把原始配置整理成设计需求')
    H('1.1  先分清需求和器件参数')
    P('需求描述我们希望电源完成什么，例如输入 20～30 V、输出 30 V。器件参数描述我们打算用什么实现，例如 6 匝原边、8 µH 自感、50 mΩ MOS 导通电阻。计算结果则是把这些需求和器件放在一起后得到的电流、温升和效率。结果不能反过来冒充需求。')
    T(['项目','本例输入','含义'],[
        ('拓扑和控制','反激  SSR  峰值电流模式','固定频率，只有 OUT1 被主反馈约束'),
        ('输入范围','Vinmin 20 V  Vinmax 30 V','同一套匝数、线材和补偿参数计算两个端点'),
        ('开关频率','250 kHz','每秒 25 万个开关周期'),
        ('原边自感和匝数','8 µH  6 匝','已启用耦合矩阵，此 L 是原边开路自感'),
        ('副边匝数','OUT1 12 匝  OUT2 5 匝  OUT3 2 匝','不是每路都能独立设定稳压值'),
        ('耦合系数','任意不同绕组之间 kij 0.995','并非只有原副边之间的一个 K'),
        ('效率输入和目标','预设 93%  评审目标 92%','两者都不是最终损耗计算值'),
    ],[1.5,2.7,2.9])
    T(['输出','参考电压','最大配置功率','最小配置功率','负载电阻'],[
        ('OUT1 主反馈','30 V','30 W','2 W','30 Ω'),
        ('OUT2 非反馈','12.5 V','1 W','0.3 W','156.25 Ω'),
        ('OUT3 非反馈','5 V','2 W','0.5 W','12.5 Ω'),
    ],[1.55,1.2,1.4,1.4,1.55])
    E('Rload=Vtarget²/Prated')
    P('例如 OUT2 的负载是 12.5²÷1＝156.25 Ω。若实际电压变成 12.5577 V，电流和功率就分别变成约 0.08037 A 和 1.00925 W。这里不是把每一路都强制保持为恒功率负载。')
    E('Iload=V_j/Rload；Pactual=V_j²/Rload')
    H('1.2  为什么文件里还看得到 40W 和旧 ESR')
    P('JSON 顶层 P_out 是 40 W，顶层输出 ESR 是 82 mΩ，但多路输出表中 OUT1 的功率是 30 W，ESR 是 40 mΩ。当前多路计算采用各路表的参数，总配置功率是 30＋1＋2＝33 W，不再把顶层 40 W 重复计入。报告的最终功率还会受非反馈路实际电压影响。')
    P('这不是要求你修改原文件，而是提醒：打开历史配置时，要同时检查“原始字段”和“当前生效字段”。教程用实际生效的 OUT1 ESR 40 mΩ，不沿用失效的顶层 82 mΩ。')
    H('1.3  单位先换对，再谈公式')
    T(['前缀','倍率','本例中的换算'],[
        ('k','10³','250 kHz＝250000 Hz'),('m','10⁻³','15 mΩ＝0.015 Ω'),
        ('µ 或 u','10⁻⁶','8 µH＝0.000008 H'),('n','10⁻⁹','5.2 nC＝0.0000000052 C'),
        ('p','10⁻¹²','100 pF＝0.1 nF'),
    ],[1.2,1.5,4.4])
    P('线径界面以 mm 输入，MLT 以长度单位显示；内核统一换成 m。0.1 mm 不是 0.1 m。磁芯面积 62 mm² 要换成 62×10⁻⁶ m²。电流密度 4 A/mm² 等于 4×10⁶ A/m²。导入曲线的轴倍率同样必须正确，否则数值看起来能导入，却可能相差十亿倍。')
    source('config_io.py  isolated_outputs.output_specs  transformer_turns.resolve_output_turns')

    C('2  先理解反激为什么能够升降压和隔离')
    F('topology_1','图 1  本例三路反激示意图  仅表示模型连接和位号  不包含完整驱动和安规设计')
    P('先找出 Q1、T1 和三只整流二极管 D_O1～D_O3。Q1 控制原边是否接通输入。T1 的励磁与耦合电感储存并转移能量。整流二极管只允许副边电流朝输出电容方向流动。输出电容在副边不供电时继续给负载供电。')
    H('2.1  Q1 开通时')
    P('在理想的储能区间，输入给原边加正电压，励磁电流逐渐上升，副边整流二极管反向截止。负载此时主要由输出电容维持。电感电流不能瞬间跳变，因此提高输入电压会提高上升斜率，但控制器可通过缩短开通时间限制峰值。非理想耦合时，开关边沿还存在短暂换流，不能要求每个绕组在边沿立即服从理想比例。')
    E('v=L·di/dt；di/dt=v/L')
    H('2.2  Q1 关断时')
    P('原边开关支路被切断，磁场仍有储能，绕组电压翻转，使副边整流二极管导通，电流流入负载与电容。漏感中的能量不能立即全部进入副边，因而在原边形成额外电压，钳位支路为它提供释放路径。')
    E('E=(1/2)·L·I²')
    P('对于本例这种多绕组模型，更一般的磁场储能是电流向量与全电感矩阵的二次型，而不只是 8 µH 乘原边电流平方的一半。后面的矩阵章会解释这一点。')
    H('2.3  CCM 和 DCM 在这里指什么')
    P('理想单路 CCM 表示励磁储能在下一周期开始前仍未降到零；DCM 则有完全退磁后的空闲区间。反激原边端子电流在 Q1 关断后本来就不流过 MOS，因此不能看到 MOS 电流中间有零电流就认定“原边 DCM”。')
    P('多路带漏感时，还要分别观察各路副边的退磁区间：某路可能只在很短的换流时段导通，随后提前降为零。这样即使主反馈路标为 CCM，轻载路也可能为 DCM。软件标记只是该模型下的工作模式，仍应结合波形和定义判断。')
    practice('反激的 OUT2 是否还需要像正激那样额外填一个输出滤波电感','本例不需要。JSON 中各路残留的 L 和 core_choice_L 是历史兼容字段，不作为反激独立输出电感参与计算。')

    C('3  用理想手算建立数量级概念')
    P('这一章故意先拿掉漏感、铜阻、二极管压降和其他损耗，使用 33 W 总负载、原副边匝比 N＝Np/Ns1＝0.5。这样你能用纸笔检查数量级。此章不是当前软件耦合模型的精确答案。')
    H('3.1  从频率得到周期')
    E('Ts=1/fs=1/250000=4·10⁻⁶')
    P('周期为 4 µs。占空比 D 是 Q1 开通时间占整个周期的比例，因此开通时间为 D×4 µs，关断时间为其余部分。频率和占空比不是同一个量。')
    H('3.2  从伏秒平衡得到占空比')
    P('稳定工作时，励磁电感在一个周期内的净电流变化为零。若开通时电压是 Vin，关断时原边反射电压幅值为 Vr，那么上升和下降的伏秒面积相等。')
    E('Vin·D·Ts=Vr·(1-D)·Ts')
    E('Vr=N·Vo；D=Vr/(Vin+Vr)')
    P('理想反射电压是 0.5×30＝15 V。在 20 V 输入时，D＝15÷35＝0.42857；在 30 V 输入时，D＝15÷45＝0.33333。输入越高，在这个理想例子中需要的开通时间越短。')
    T(['理想量','20 V 输入','30 V 输入'],[
        ('D','0.42857','0.33333'),('开通时间','1.7143 µs','1.3333 µs'),
        ('关断时间','2.2857 µs','2.6667 µs'),
    ],[2.7,2.2,2.2])
    H('3.3  原边电流纹波怎样算')
    E('ΔIp=Vin·D·Ts/L')
    P('20 V 时，ΔIp＝20×0.42857×4 µs÷8 µH＝4.2857 A。30 V 时是 5.0000 A。注意：输入更高虽然占空比更小，但电流斜率更大，所以峰峰纹波不一定减小。')
    H('3.4  从功率得到开通区间的平均电流')
    P('理想情况下输入功率等于输出功率，输入全周期平均电流为 Pout/Vin。原边只在占空比 D 的区间从输入吸取电流，所以开通区间平均值还要除以 D。')
    E('Iin,est=Po/Vin；Ip,on,avg=Iin,est/D')
    E('Ipk=Ip,on,avg+ΔIp/2；Imin=Ip,on,avg-ΔIp/2')
    T(['理想手算结果','20 V 输入','30 V 输入'],[
        ('全周期输入平均电流','1.6500 A','1.1000 A'),
        ('开通区间平均电流','3.8500 A','3.3000 A'),
        ('开通前电流 Imin','1.7071 A','0.8000 A'),
        ('关断前电流 Ipk','5.9929 A','5.8000 A'),
    ],[3.1,2.0,2.0])
    P('两端点手算 Imin 都大于零，所以理想励磁工作点为 CCM。如果算出了负 Imin，不能继续把负数当作二极管允许的反向电流使用，而应换用 DCM 的分段条件。')
    H('3.5  为什么损耗要用 RMS')
    P('电阻瞬时发热是 i²R。先平均 i²，再开方得到的才是 RMS。对只在 D 区间导通的线性斜坡，可以直接积分得到下面的公式。')
    E('Irms²=D·(Ipk²+Ipk·Imin+Imin²)/3')
    P('如果错误地使用全周期平均电流平方，脉冲越尖，低估发热越严重。后续对实际矩阵波形，软件直接统计波形或积分，不强行套用整段理想三角波。')
    H('3.6  8 µH 是否意味着设计正确')
    P('本例内核的“L 初选下限”不是 CCM 临界电感。它是按约 40% 电流纹波再加 1.5 倍裕量给出的保守预设计提示，20 V 和 30 V 结果约为 33.70 µH 和 46.51 µH。因此 8 µH 会触发复核，但这不等于当前波形不能工作，也不等于主反馈已经变成 DCM。')
    E('Ip,on,avg=Pin,est/(Vin·DCCM)')
    E('Lmin≈1.5·Vin·DCCM·Ts/(0.4·Ip,on,avg)')
    P('这两式沿用等效预设计的 DCCM 与预估输入功率，不拿矩阵解的全周期输入平均电流直接作分母。特别要区分全周期平均电流与开通区间平均电流；两者差了占空比。')
    source('power_stage.py  design_checks.py  实际耦合计算另见第 5 章')

    C('4  软件是按什么顺序算出结果的')
    H('4.1  从配置到固定硬件')
    P('第一步把界面单位转换成 SI，确认拓扑、路数与反馈路。第二步解析实际整数匝数，以 OUT1 30 V 为基准形成 OUT2 12.5 V、OUT3 5 V 的匝比参考。第三步在 Vinmin 解析磁芯与线材，固定同一套硬件，再算 Vinmax。这样比较的是同一个变压器，而不是偷偷换了两套设计。')
    E('V_j,est=V_b·Ns_j/Ns_b')
    P('本例 30×5÷12＝12.5 V，30×2÷12＝5 V。这一步只是无负载压降的匝比参考，不是另设两个稳压环。软件接着用参考电压与配置功率换算各路电阻，再求实际非反馈电压。')
    H('4.2  预设效率在哪一步起作用')
    P('预设效率 93% 用来做设计初值与未启用耦合矩阵时的一阶工作点估算。例如从 33 W 得到约 35.484 W 的初估输入功率。它不是让所有电流统一乘上 1/0.93。')
    E('Pin,est=Po/η₀；Ploss,budget=Po·(1/η₀-1)')
    P('在未启用矩阵的旧模型中，内核使用等效电压负担 U＝Vo/η₀ 求工作点，保持分段波形的伏秒与电荷关系。本例已经启用矩阵，93% 主要帮助初值；最终占空比、电流与非反馈电压由显式 RL 电路和电荷平衡求解，不再被 93% 强制约束。')
    H('4.3  两本功率账不要混淆')
    P('矩阵电路先包含绕组 DCR、MOS 导通电阻、采样电阻、固定整流压降和定压钳位。该电路有自己的输入输出能量守恒检查。随后损耗模块用导入曲线重新评估整流损耗，并加入磁芯损耗、交流铜损修正、输入输出防反二极管、开关交叠、Coss、栅驱动和电容 ESR 损耗。')
    P('因此快照里的 P_in_est 在矩阵模型下表示显式电路阶段的输入功率，不应再机械地把它解释成 Pout/93%。最终 P_in 则是实际输出功率加损耗账本。二者差值揭示了后处理损耗尚未全部反馈到周期解，不能宣称已经做过完全自洽的电热联合迭代。')
    T(['功率口径','20 V 输入','30 V 输入'],pair_rows([
        ('显式电路阶段输入','result.P_in_est',1,6,' W'),
        ('实际总输出','result.P_out',1,6,' W'),
        ('最终损耗账本输入','result.P_in',1,6,' W'),
        ('两者差值','result.P_in_delta',1,5,' W'),
    ]),[3.0,2.05,2.05])
    H('4.4  完整计算链')
    P('读取参数 → 解析绕组和硬件 → 求周期稳态 → 重建时域波形 → 计算电容分流、器件与磁件损耗 → 汇总最终效率 → 在线性化工作点求环路 → 做工程检查 → 在固定硬件下扫描轻重载角点 → 组织 Word 或 Excel 报告。显示某个页面和导出报告都应消费同一组已算结果。')
    source('design_engine.service  input_voltage_range  loss_model.compute_design')

    C('5  用耦合矩阵求多路输出')
    P('这一章可以分两遍读。第一遍只记住：每路副边电流不是按功率比例分出来的，而是由耦合、电阻、输出电压和二极管的导通条件共同决定。第二遍再看矩阵公式。资料 [1] 同样说明，漏感会影响多输出之间的调整关系；本教程的具体数值仍以软件当前实现为准。')
    H('5.1  自感和互感从哪里来')
    P('绕组次序固定为 P、OUT1、OUT2、OUT3。原边自感是 8 µH。软件假定各绕组的自感按匝数平方缩放，再用每一对 kij 生成互感。用户给出 0.995，并不是给出“0.5% 的全部损耗”。')
    E('L_j=Lp·(N_j/Np)²；Lij=kij·√(Lii·Ljj)')
    T(['绕组','匝数','开路自感','匝比 Np/Ns'],[
        ('P','6','8 µH','1'),('OUT1','12','32 µH','0.5'),
        ('OUT2','5','5.55556 µH','1.2'),('OUT3','2','0.888889 µH','3'),
    ],[1.3,1.0,2.1,2.7])
    P('例如 P 与 OUT1 的互感是 0.995×√(8×32)＝15.92 µH。完整矩阵如下，所有元素统一使用 µH。对角线是自感，对称位置是同一对绕组的互感。')
    matrix=LO['result']['op']['coupled_model']['L']
    pr=doc.add_paragraph();pr.paragraph_format.space_after=Pt(9)
    rows=[]
    for row in matrix:
        rows.append(wm.element('mr',*[wm.element('e',wm.run(f(v*1e6,6),True)) for v in row]))
    mat=wm.element('m',*rows)
    pr._p.append(wm.element('oMath',wm.run('L'),wm.run('='),
        wm.element('d',wm.element('dPr',wm.element('begChr',val='['),wm.element('endChr',val=']')),wm.element('e',mat))))
    eq_manifest.append('L matrix in microhenries')
    P('两两 kij 都在 0～1 内并不足以保证整个矩阵合理。软件还检查对称性、对角线以及半正定性。本例 K 的特征值为 3.985、0.005、0.005、0.005，因此正定。全部 kij＝1 是理想变压器的奇异极限，软件用专门的理想回退处理，而不是把奇异矩阵硬求逆。')
    E('E=(1/2)·istate^T·L·istate')
    P('这是线性耦合电感的一般磁场储能，i 为全部绕组电流组成的列向量，右上角 T 表示转置。矩阵正定保证非零电流组合的储能为正；只给任意几对看似合理的 kij 仍可能破坏这个条件。该线性储能关系不包含磁芯饱和。')
    H('5.2  为什么不能把各对漏感相加')
    P('把所有副边端子同时短路时，原边测到的等效短路漏感要考虑副边之间也有互感。它由整个矩阵的舒尔补计算，而不是每对漏感的简单相加。')
    E('Lleak=Lpp-Lps·Lss⁻¹·Lsp')
    P('本例计算为 0.053311 µH，约 53.31 nH。它与旧 RCD 输入 K＝0.99 推出的 (1−K)×8 µH＝80 nH 不同；矩阵开启时采用前者。这里的旧 K、两两 kij、钳位系数 Kc 是三个不同的概念。')
    H('5.3  每个导通区间怎样计算电流')
    E('vstate=L·distate/dt+R·istate')
    E('distate/dt=L⁻¹·(vstate-R·istate)')
    P('L 是上面的全矩阵，R 是各绕组 DCR 组成的对角矩阵。MOS 开通时，原边还串入 Rds(on) 和采样电阻。副边绕组的同名端约定和二极管方向已经由求解器处理；不要为了“反激”再把界面的正 kij 任意改成负数。')
    P('在某一组二极管状态不变的区间，电路是线性的 RL 系统。软件用矩阵指数对应的解析传播计算电流和电荷，再寻找二极管电流降到零、其他支路开始正向导通的事件，切换到下一个区间。它不是每个采样点简单地按输出功率占比分流。')
    H('5.4  稳态解必须同时满足什么')
    E('istate(Ts)=istate(0)')
    E('∫_0^Ts (i_j(t)-V_j/R_j)dt=0')
    E('V_b=30')
    P('第一条要求每周期结束能回到起点；第二条要求每路电容一周期不净充电也不净放电；第三条只固定反馈路的直流电压。未知量包括副边周期初始电流、占空比以及非反馈路电压。二极管还必须满足只正向导通、截止时没有违反正向偏置条件。')
    P('20 V 工况的归一化稳态残差约 7.91×10⁻¹⁰，显式电路能量相对误差约 1.76×10⁻¹¹。这说明数值求解在该模型内闭合，不意味着实物误差也有这么小。')
    H('5.5  这个模型没有替你模拟什么')
    P('周期内暂把输出电容电压视为常数，再用电流重建纹波；钳位是理想定压耗能支路。不含 Coss 和二极管结电容的完整谐振、真实控制器跳周期、反向恢复换流、布线寄生、温度迭代与磁芯非线性。它能解释部分漏感换流和交叉调整现象，不能替代 SPICE 或示波器。')
    source('winding_coupling.resolve_winding_model  coupled_flyback.py')

    C('6  从波形读出电流和工作模式')
    P('20 V 时占空比约 0.440865，30 V 时约 0.342360。它们与第 3 章的理想答案不同，因为这里已经加入 DCR、导通电阻、二极管压降及漏感换流。注意关断后的钳位电流属于原边绕组的另一条路径，不是 Q1 的导通电流。')
    T(['实际计算量','20 V 输入','30 V 输入'],pair_rows([
        ('占空比','result.op.D',1,6,''),
        ('Q1 开通电流','display.switch_loss.gate.I_on',1,5,' A'),
        ('Q1 关断电流','display.switch_loss.gate.I_off',1,5,' A'),
        ('Q1 全周期 RMS','result.op.I_sw_rms',1,5,' A'),
        ('原边绕组全周期 RMS','result.op.coupled_model.winding_rms.0',1,5,' A'),
    ]),[3.0,2.05,2.05])
    H('6.1  平均值和 RMS 的积分定义')
    E('Iavg=(1/Ts)·∫_0^Ts i(t)dt')
    E('Irms=√((1/Ts)·∫_0^Ts i(t)²dt)')
    P('平均整流电流决定每周期给负载送出多少电荷；RMS 决定铜阻和 ESR 发热；峰值约束器件脉冲电流与磁通峰值。一个“电流”字段不能同时代替这三项。')
    F('tutorial_primary','图 2  同一硬件在两个输入端点的 Q1 电流 电压与钳位电流',5.65)
    P('读图时先用 4 µs 的周期定位边沿：20 V 工况的关断点在约 1.7635 µs，30 V 在约 1.3694 µs。输入较高的一条曲线更早关断，但开通斜率更陡。实际斜率还受电阻压降与换流影响，不要求整段完全是理想直线。')
    P('第二幅图先到钳位峰值，再回到反射平台。第三幅图说明多出来的原边电流流向了钳位支路。模型中该区间约 44.47 ns 和 42.73 ns，相比 4 µs 周期很短；只看整周期大图时容易把它当作一根竖线。')
    P('图上的陡直边缘来自理想开关、事件切换与采样重建，不代表真实器件能够瞬间完成换流。若要看 Vgs 与 Vds 的有限转换时间，请结合第 9 章的 t1 到 t8；它仍是分段估算，而不是完整寄生仿真。')
    H('6.2  三路副边分别看')
    F('tutorial_secondaries','图 3  各副边电流  两个输入端点对比  零电流空闲区间不可按功率比例填平',5.55)
    rows=[]
    for j in range(3):
        a,b=[c['display']['outputs'][j] for c in CASES]
        rows.append((f'OUT{j+1}',a['mode'],f(a['I_out'],5)+' / '+f(b['I_out'],5),
                     f(a['stress']['diode']['I_rms'],5)+' / '+f(b['stress']['diode']['I_rms'],5),
                     f(a['stress']['diode']['I_pk'],5)+' / '+f(b['stress']['diode']['I_pk'],5)))
    T(['输出','模式','平均电流 A','RMS 电流 A','峰值电流 A'],rows,[.7,.65,1.85,1.95,1.95])
    S('上表每格依次为 20 V / 30 V。主反馈路在规定的退磁区间保持连续，其他两路会提前截止；不是按完整周期是否有零电流判断反激 CCM。')
    P('OUT2 平均电流仅约 80 mA，峰值却超过 2 A；OUT3 平均约 0.364 A，峰值约 5.70 A。这正是不能只按直流输出电流选择绕组线径、二极管和电容纹波额定值的原因。')
    practice('若 OUT3 输出电流是 0.364 A，能否把绕组 RMS 也填写成 0.364 A','不能。本例绕组 RMS 约 1.196 A，铜损若按直流值计算会显著偏低。')
    source('coupled_flyback.py  isolated_outputs.coupled_waveforms  waveforms.py')

    C('7  从电容电流计算纹波和发热')
    H('7.1  电容承担的是电流差')
    P('副边电流不是连续稳定的直流，而负载一直在消耗电流。两者之差进入电容：副边供给多时充电，供给不足时放电。稳态时电容组平均电流接近零。')
    E('ic(t)=i_d(t)-Io')
    E('Δv_C(t)=(1/C)·∫ ic(t)dt')
    P('如果只做初选，可假设 MOS 开通时完全由电容给负载供电，得到 C≥Io×D×Ts/ΔV。20 V 时 OUT1 约为 1×0.440865×4 µs÷0.3＝5.878 µF。实际有 330＋10＝340 µF，但容量大于初选下限并不保证 ESR 尖峰、ESL 尖峰和寿命都满足。')
    E('Cmin≈Io·D·Ts/(ΔV)')
    H('7.2  ESR 和 ESL 分别增加什么')
    E('v_Cbank(t)=Δv_C(t)+ESR·ic(t)+ESL·dic/dt')
    P('ESR 造成与电流同形的电压分量并发热；ESL 在电流快速变化时形成电压尖峰。内核把电容与 ESR 形成的低频纹波单列，把 ESL 边沿尖峰另列，不拿采样依赖很强的理想尖峰冒充精确实测值。')
    F('tutorial_ripple','图 4  20 V 工况电容组电流和低频纹波  零均值纹波不等于没有峰峰值',6.5)
    H('7.3  并联电容不是按容量比例固定分流')
    P('本例每路都并联一只 10 µF 低 ESR 电容。它在开关频率附近可能比大电容承担更多交流电流。软件把总电流分解到各频率，按每只电容的复阻抗分流，再重建电压与损耗。')
    E('Zj(f)=ESRj+j·(2πf·ESLj-1/(2πf·Cj))')
    E('Yj=1/Zj；Ij=Ibank·Yj/(Y₁+Y₂)')
    P('式中的 j 是虚数单位，与电容编号的下标要区分。各支路电流有相位，因此两个电容各自的 RMS 不能直接相加，也不要求其平方和等于电容组 RMS 的平方。并联谐振附近还可能出现循环电流。')
    E('PESR,j=ESRj·Ij,total²')
    rows=[]
    for j in range(3):
        ca=LO['display']['outputs'][j]['capacitors']['output']
        for k,cap in enumerate(ca['caps'],1):
            rows.append((f'OUT{j+1} 电容{k}',f(cap['C']*1e6)+' µF',f(cap['ESR']*1e3)+' mΩ',
                         f(cap['total'],5)+' A',f(cap['ESR']*cap['total']**2,5)+' W'))
    T(['20 V 工况','容量','ESR','分流 RMS','ESR 损耗'],rows,[1.4,1.15,1.2,1.65,1.7])
    P('例如 OUT2 电容组总交流 RMS 约 0.3223 A，其中 10 µF 支路的 RMS 约 0.3340 A，比电容组还大，并不自动表示程序算错；需要结合复阻抗和相位理解。')
    H('7.4  输入电容也需要同样检查')
    E('icin(t)=mean(iin)-iin(t)')
    P('正负号取决于电流方向约定，但不影响 RMS。输入电容为 330 µF／15 mΩ／5 nH 与 100 µF／0.1 mΩ／5 nH 并联。20 V 时电容组交流 RMS 约 2.1474 A，两支路分别约 0.5342 A、1.8780 A；总 ESR 损耗约 4.633 mW。低 ESR 数值非常乐观，应核对实物与频率条件。')
    H('7.5  柱状图的频带怎样相加')
    E('Ij,total=√(Σ_k Ij,band²)')
    P('软件对整周期稳态波形使用相干 DFT；非整周期才使用平顶窗并按时域交流 RMS 校准。频带包括低于 0.5fs、各次开关谐波和高频剩余部分。不同频带能量按平方相加，不把柱子高度直接相加。')
    T(['低频纹波峰峰值','20 V 输入','30 V 输入','配置限制'],[
        (f'OUT{j+1}',f(LO['display']['outputs'][j]['ripple_pp']*1e3,5)+' mV',
         f(HI['display']['outputs'][j]['ripple_pp']*1e3,5)+' mV',
         ['300 mV','125 mV','50 mV'][j]) for j in range(3)
    ],[2.2,1.65,1.65,1.6])
    P('OUT3 在两个端点都超过 50 mV 的配置阈值。即使它的总容量达到 480 µF，也不能据此忽略 ESR 与脉冲电流。软件另外按实际 4.55 V 计算纹波百分比时，数值会比按名义 5 V 计算略大；阅读报告要先看比较基准。')
    source('waveforms  capripple._divide_and_band  loss_model.total_losses')

    C('8  计算 MOS 应力与 RCD 钳位')
    H('8.1  反射平台和钳位尖峰不是一回事')
    P('Q1 关断后的漏源电压包括输入电压和原边反射电压。漏感换流还会在这个平台上抬高电压，直到钳位支路吸收电流。Kc 定义为相对输入母线的钳位电压与参考反射电压之比，不是 MOS 额定耐压的降额系数。')
    E('Vc=Kc·Vr；Vceiling=Vin+Vc')
    P('本例钳位参考采用反馈路含 0.7 V 整流压降的反射值：0.5×(30＋0.7)＝15.35 V。Kc＝1.5，因此 Vc＝23.025 V，20 V 和 30 V 的 MOS 钳位应力分别为 43.025 V、53.025 V。矩阵换流后的实际平台略低于这个参考值，不必恰好等于 15.35 V。')
    T(['MOS 电压量','20 V 输入','30 V 输入'],pair_rows([
        ('换流后反射平台加 Vin','display.clamp.V_plateau',1,6,' V'),
        ('钳位应力上限','display.clamp.V_ceiling',1,6,' V'),
        ('模型波形峰值','display.clamp.V_peak',1,6,' V'),
    ]),[3.0,2.05,2.05])
    P('本例没有在上述值之外再乘一次旧 ring_margin＝30%。但实际器件耐压仍要结合布线、探头测量、容差、温度和异常工况留余量；模型峰值不等于可直接选用同数值额定耐压的 MOS。')
    H('8.2  钳位功率怎样得到')
    E('Eclamp=∫_0^Ts Vc·Iclamp(t)dt')
    E('Prcd=Eclamp·fs')
    P('矩阵模型直接积分定压钳位电流。20 V 时每周期约 3.13698 µJ，乘 250 kHz 得 0.78425 W；30 V 时约 0.72671 W。不要再叠加一次 ½L漏I²fs，否则会把同一钳位支路重复计算。')
    P('常见的一阶 RCD 手算式是 ½L漏Ipk²fs×Vc/(Vc−Vr)，用于解释钳位不只消耗一个简单的漏感储能量。这个式子在本例不作为实际波形积分的替代，尤其不能把多绕组等效漏感当作独立串联支路强行套用。')
    E('Eleak=(1/2)·Lleak·Ipk²')
    E('Prcd,估算=Eleak·fs·Vc/(Vc-Vr)')
    H('8.3  由功率初选 R 和 C')
    E('Rsnub=Vc²/Prcd')
    E('ΔVc=dC·Vc；Csnub≈Prcd/(fs·Vc·ΔVc)')
    T(['按该端点初算','20 V 输入','30 V 输入'],pair_rows([
        ('电阻 Rsnub','display.rcd.R_snub',1,6,' Ω'),
        ('电容 Csnub','display.rcd.C_snub',1e9,5,' nF'),
        ('钳位电容纹波目标','display.rcd.dV_clamp',1,5,' V'),
        ('电阻耗散','display.rcd.P_res',1,5,' W'),
    ]),[3.0,2.05,2.05])
    P('两列是按同一钳位目标分别得到的初选需求，不是让你在两个输入电压之间切换电阻。实物只能选择一套 R、C 和功率额定值，覆盖较重的功耗和纹波需求，再做开关仿真和实测。当前周期模型把钳位保持为定压，未求解固定 R、C 的完整动态，因此不能宣称选完 676 Ω 和约 59.2 nF 就会在所有工况精确保持 23.025 V。')
    H('8.4  整流二极管反压怎样看')
    E('V_d,理想≈V_j+Vin·Ns_j/Np')
    P('这是没有寄生尖峰时的理想参考。实际矩阵结果从绕组端电压求得；低于简单参考并不表示寄生尖峰已经被模型覆盖。')
    T(['整流二极管反压','20 V 输入','30 V 输入'],[
        (f'D_O{j+1}',f(LO['display']['outputs'][j]['stress']['diode']['V_max'],5)+' V',
         f(HI['display']['outputs'][j]['stress']['diode']['V_max'],5)+' V') for j in range(3)
    ],[3.0,2.05,2.05])
    P('所有整流二极管反压都未包含寄生尖峰。选型要留耐压余量并在样机实测，不可把 MOS 的 Kc 钳位应力上限直接套在各副边二极管上。')
    source('flyback_clamp  semiconductor.device_stress  coupled_flyback')

    C('9  用两条器件曲线计算 MOS 损耗')
    H('9.1  为什么需要两条不同的曲线')
    P('Id Vgs 转移曲线回答“这个电流大致对应多高的栅压”，Vgs Qg 栅电荷曲线回答“栅压升到这里需要送入多少电荷”。两条曲线的横纵轴不同，不能互相替代。资料 [2] 解释门极充放电与米勒阶段，资料 [3] 给出电荷名称的定义；以下时间公式沿用本软件已经采用的表格口径，不声称是所有器件的唯一精确模型。')
    T(['导入入口','X 轴','Y 轴','本例数据'],[
        ('Q1 转移曲线','Vgs  V','Id  A','143 个点  标注 25 ℃'),
        ('Q1 栅电荷曲线','Qg  C 或选择 n 倍率','Vgs  V','160 个点  12 A  100 V  25 ℃'),
    ],[1.5,1.65,1.5,2.45])
    P('本例曲线名称包含 BSC500，但名称本身不能替代器件完整订货号和测试条件。转移曲线未完整声明测试 Vds，栅电荷曲线的校核标记为未确认；这些都需要回到原规格书核查。允许外推只表示程序会给出趋势估算，不表示数据范围之外具有同样精度。')
    F('tutorial_mos_curves','图 5  由实际事件电流反查栅压  再从平台前支路读取对应电荷',6.95)
    H('9.2  四个事件逐一计算')
    P('输入电压改变，占空比与电流随之改变。我们分别使用 Vinmin 开通、Vinmin 关断、Vinmax 开通、Vinmax 关断四个事件，而不是用一个固定米勒电压套完全部工况。')
    E('Vgp=F⁻¹(Ids)')
    P('F 是所选 Id Vgs 曲线。内核按声明的线性或对数坐标插值，反查对应栅压。这里把静态或脉冲转移特性近似用于动态米勒平台，是一项模型假设，不是等同示波器上测得的平台。')
    P('还有一个边沿近似：矩阵模型中的理想开关在漏感换流起点可出现瞬时零电流，软件不会据此把有限开通损耗直接设为零。开通损耗使用周期初始原边磁链除以原边自感形成的等效交叠电流，关断使用关断前的实际开关电流。因此下表的开通电流是损耗估算幅值，不是已经包含 Coss 和反向恢复的真实瞬态测量。')
    rows=[]
    for c in CASES:
        g=c['display']['switch_loss']['gate']
        for event,label in [('on','开通'),('off','关断')]:
            rows.append((f"{c['voltage']:g} V {label}",f(g['I_'+event],6),f(g['Vgp_'+event],6),
                         f(g['Qgs_'+event]*1e9,6),f(g['Qgd_'+event]*1e9,5)))
    T(['事件','电流 A','平台电压 V','零伏至平台 nC','米勒平段 nC'],rows,[1.25,1.35,1.45,1.65,1.4])
    H('9.3  Qgs Qgd 和总 Qg 怎样读')
    E('Qg_th=Qpre(Vth)；Qgs,on=Qpre(Vgp,on)')
    E('Qgs,off=Qpre(Vgp,off)')
    E('Qgd=Qplateau,end-Qplateau,start')
    E('Qg=Qpost(Vgs)')
    P('Qpre 是平台前上升段的反查函数，Qpost 是平台后上升段。软件只在平台前读取 Qg(th) 和两个 Qgs，绝不因为某个查询电压偏高就误读平台后支路。平台起止点已设为 5.2 nC 和 7.2 nC，所以 Qgd＝2.0 nC。Vth＝3 V 对应 Qg(th)≈3.54690 nC。')
    P('驱动电压是 10 V，本例总 Qg≈14.1381 nC，使用了平台后端点外推，必须在教程与报告中注明。四个事件复用同一条 12 A／100 V 参考栅电荷曲线，因而 Qgd 与总 Qg 相同；只有反查栅压及对应平台前 Qgs 随电流变化。没有实际多电流、多 Vds 栅电荷数据时，不应为了凑四个不同数字而人为修改 Qgd。')
    H('9.4  先把开通和关断总栅阻相加')
    E('Ron=Rg_drive+Rs_on+Rg=2+6.8+1.9=10.7')
    E('Roff=Rg_drive+Rs_off+Rg=10.7')
    P('单位均为 Ω。Rg 是 MOS 内部栅阻，不能在关断总栅阻里漏掉。真实驱动器的拉高和拉低内阻未必相同，本例按输入的同一驱动内阻估算。')
    H('9.5  t1 到 t8 各自在描述什么')
    T(['阶段','物理含义','是否计入交叠损耗时间'],[
        ('t1','栅压从零升到阈值','不计入主交叠项'),('t2','电流从零附近上升到开通事件电流','开通项'),
        ('t3','开通米勒阶段  Vds 下降','开通项'),('t4','平台后栅极继续充电','仅绘图补充估算'),
        ('t5','关断前栅压从驱动值下降到平台','仅绘图补充估算'),('t6','关断米勒阶段  Vds 上升','关断项'),
        ('t7','电流下降  栅压向阈值下降','关断项'),('t8','阈值以下栅极继续放电','不计入主交叠项'),
    ],[.7,3.9,2.5])
    P('LN 是自然对数。下面的对数项来自 RC 充放电过程，不能把字母 l 误读成电流 I。它们是本项目沿用的分段栅电荷估算，并未解出所有非线性电容与驱动电感。')
    E('t₁=-Ron·Qg_th/Vth·ln(1-Vth/Vgs)')
    E('t₂=-Ron·Qgs,on/Vgp,on·ln(1-Vgp,on/Vgs)-t₁')
    E('t₃=Qgd,on·Ron/(Vgs-Vgp,on)')
    E('t₆=Qgd,off·Roff/Vgp,off')
    E('t₇=-Roff·(Qgs,off-Qg_th)/(Vgp,off-Vth)·ln(Vth/Vgp,off)')
    E('t₈=3·Roff·Qg_th/Vth')
    P('以 20 V 开通为例：t1＝−10.7×3.54690 nC÷3×ln(0.7)≈4.512 ns；将 Vgp,on＝3.88512 V、Qgs,on＝4.59705 nC 代入 t2 得 1.715 ns。t3＝2 nC×10.7÷(10−3.88512)≈3.500 ns。先将 nC 看作 10⁻⁹ C，就自然得到 ns。')
    T(['时间','20 V 输入','30 V 输入'],[
        (key,*vals('display.switch_loss.'+key,1e9,5,' ns')) for key in ('t1','t2','t3','t6','t7','t8')
    ],[2.7,2.2,2.2])
    P('t8 取 3RC，表示栅压下降到原来的约 5%，不是数学意义上精确到 0 V。t4 与 t5 用平台后剩余电荷作辅助估算，不进入上述交叠时间，也不会为了容纳漏感钳位尾巴而拉长 t7 或 t8。')
    E('Qpost,on=Qg-Qgs,on-Qgd,on')
    E('t₄≈3·Ron·Qpost,on/(Vgs-Vgp,on)')
    E('Qpost,off=Qg-Qgs,off-Qgd,off')
    E('t₅≈Roff·Qpost,off/(Vgs-Vgp,off)·ln(Vgs/Vgp,off)')
    F('tutorial_switching','图 6  20 V 工况的 Vgs 与 Vds  横轴按阶段展开而非等时长  t4 t5 为补充估算',6.95)
    H('9.6  五项损耗怎样组成 MOS 结果')
    E('Pcond=Rds,on·Isw,rms²')
    E('Pon=k_sw·Vds·Ids,on·(t₂+t₃)·fs')
    E('Poff=k_sw·Vds·Ids,off·(t₆+t₇)·fs')
    E('Pcoss=(1/2)·Coss·Vds²·fs')
    E('Pgate=Qg·Vgs·fs')
    P('本例 k_sw＝0.25，Vds 在损耗账本中采用应力上限，是偏保守的简化；开通波形图则从实际关断平台下降，不会假装开通前一直处于钳位尖峰。Coss 固定为 200 pF、Rds(on) 固定为 50 mΩ，未随 Vds 与结温变化。k_sw 是工程经验系数，不能当作精确开关能量测量。')
    T(['Q1 损耗','20 V 输入','30 V 输入'],[
        (label,*vals('display.switch_loss.'+key,1,6,' W')) for key,label in [
            ('P_cond','导通'),('P_sw_on','开通交叠'),('P_sw_off','关断交叠'),
            ('P_coss','Coss 硬开关'),('P_gate','门极驱动'),('P_total','合计')]
    ],[2.7,2.2,2.2])
    P('例如 20 V 时，导通损耗＝0.05×2.77540²≈0.38514 W。30 V 时关断电流略小，但 Vds 更高，所以关断交叠损耗反而从约 0.15454 W 增到 0.18309 W。这说明“电流更小”不能单独决定开关损耗。')
    P('门极驱动损耗计入系统账本，不表示全部热量都耗散在 MOS 芯片内。若以后改用实测 Eon Eoff，应检查其是否已含 Coss 或反向恢复能量，避免与现有分项重复。')
    source('mos_curves  mos_gate_charge  mos_gate  semiconductor.mosfet_loss  switching_transients')

    C('10  二极管怎样用导入曲线算损耗')
    H('10.1  先看清是哪个二极管')
    P('D_IN 是输入防反二极管，当前模型按输入脉冲电流计算。D_O1～D_O3 是三路整流二极管，电流是对应副边脉冲。D_B1～D_B3 是输出电容后面的防反二极管，当前按直流负载电流计算。它们在图中位置不同，不能把同一个平均值直接套给所有二极管。')
    T(['曲线导入对象','X 轴','Y 轴','损耗使用的电流'],[
        ('D_IN','Vf  V','If  A','输入端脉冲电流'),
        ('D_O1 D_O2 D_O3','Vf  V','If  A','各路整流电流'),
        ('D_B1 D_B2 D_B3','Vf  V','If  A','各路平均负载电流'),
    ],[2.05,1.1,1.1,2.85])
    H('10.2  逐点反查 Vf 再平均功率')
    E('Pdiode=(1/Ts)·∫_0^Ts Vf(i(t))·i(t)dt')
    E('Pdiode≈(1/M)·Σ_(k=1)^M Vf(I_k)·I_k')
    P('第二式用于均匀采样。每个电流点先从 If Vf 曲线反查压降，再计算瞬时 I×Vf，最后求平均。一般不能用 Vf(平均电流)×平均电流替代，因为 Vf 随电流非线性变化，整流电流又有脉冲。')
    E('P_d,固定=Vf·Iavg')
    P('只有选择固定值粗略计算时，才使用固定压降乘平均电流。本版动态电阻不参与计算。曲线启用时不会再叠加固定 Vf×I 或旧 Rd×Irms²。固定 0.7 V 仍用于本例周期稳态求解的整流压降，因此“曲线损耗”不等于已用非线性二极管重算所有电流。')
    H('10.3  本例计算结果')
    rows=[]
    for i,c in enumerate(CASES):
        pass
    rows.append(('D_IN',*vals('result.P_din',1,6,' W')))
    for j in range(3):
        rows.append((f'D_O{j+1}',f(LO['display']['outputs'][j]['P_rectifier'],6)+' W',f(HI['display']['outputs'][j]['P_rectifier'],6)+' W'))
        rows.append((f'D_B{j+1}',f(LO['display']['outputs'][j]['P_dout'],6)+' W',f(HI['display']['outputs'][j]['P_dout'],6)+' W'))
    T(['器件','20 V 输入','30 V 输入'],rows,[2.7,2.2,2.2])
    P('以 D_B1 为例，直流负载电流是 1 A，曲线反查压降约 0.67917 V，所以功耗约 0.67917 W。D_O1 的平均电流同样约 1 A，但电流是脉冲，20 V 下曲线积分损耗约 0.74335 W，不能沿用 D_B1 的答案。')
    H('10.4  低电流外推和反向恢复')
    P('原始 If Vf 数据的电流范围约 0.209～15.345 A，本例脉冲尾部和某些防反支路低于这个范围，软件沿端点趋势外推并提示。导入时还对 4 个轻微回退点做单调整理，最大 Vf 调整约 2.14 mV，原 CSV 没有被修改。整理后能计算不等于测试温度、曲线族或低电流外推已获确认。')
    E('P_rr≈Qrr·Vreverse·fs')
    P('本例 Qrr＝0，因此账本中的反向恢复项为零。这只是未提供或忽略该项，不表示实际二极管一定没有恢复损耗。当前二极管结电容、恢复换流尖峰和温度变化也未完整计入。')
    source('diode_curves.conduction  semiconductor.diode_loss  loss_model.total_losses')

    C('11  变压器从电气尺寸算到温升')
    H('11.1  磁芯参数先看单位')
    T(['PQ20 20 模型几何','数值','换成 SI'],[
        ('有效截面积 Ae','62 mm²','6.2×10⁻⁵ m²'),
        ('有效体积 Ve','2.8148 cm³','2.8148×10⁻⁶ m³'),
        ('数据库窗口面积 Wa','30 mm²','3.0×10⁻⁵ m²'),
        ('用户每匝平均线长 MLT','40 mm','0.04 m'),
        ('材料标签','DMR44','损耗仍由可编辑 k α β 决定'),
    ],[2.6,2.0,2.5])
    P('Ae 是磁路截面积，不是窗口面积。MLT 是每一匝导线的平均长度，不是磁路长度。本例采用用户输入 40 mm，不能在 DCR 公式中误用磁芯有效磁路长度。数据库几何是模型输入，不替代实际采购骨架和磁芯的尺寸公差。')
    H('11.2  匝数与磁通的第一步关系')
    E('ΔB≈Vin·D·Ts/(Np·Ae)')
    E('Np,auto=ceil(Vin·D·Ts/(Bmax·Ae))')
    P('自动匝数公式用于预设计；本例 Np＝6 已手动固定，不会为了满足 Bmax 自动改掉。对于简单单路励磁模型，还常用 Bpk≈Lm×Ipk/(Np×Ae) 检查饱和。不过多绕组全矩阵只有总磁链，不能唯一分离磁芯主磁通与每条漏磁通。')
    H('11.3  本例为什么采用原边磁链参考')
    E('λp=Σ_j L_pj·i_j；B_ref=λp/(Np·Ae)')
    P('软件根据求解的原边磁链得到一个标明“原边磁链参考”的 B 波形，使用其峰值与摆幅估算饱和和磁芯损耗。不要把它称为已准确求出的磁芯局部 B，尤其不要把所有泄漏磁链都误当作共同铁芯磁通。')
    T(['磁通参考量','20 V 输入','30 V 输入'],pair_rows([
        ('峰值参考 Bpk','display.magnetics.0.B_pk',1e3,6,' mT'),
        ('峰峰摆幅 ΔB','display.magnetics.0.dB',1e3,6,' mT'),
    ]),[3,2.05,2.05])
    P('Bsat 输入为 0.4 T，Bmax 设计约束为 0.3 T。两端点参考峰值低于这两个值，温升、偏置和实际材料温度特性仍需确认。气隙按原边目标 L 与线性磁路作初算，需核对加工后的 AL。')
    H('11.4  线径 股数 MLT 怎样得到 DCR')
    E('Astrand=π·dwire²/4；Atotal=nparallel·nstrand·Astrand')
    E('Rdc=ρ·MLT·Nturn/Atotal')
    P('原边单股直径 0.1 mm，40 股并绕，总裸铜面积 40×π×0.1²÷4＝0.314159 mm²。6 匝总长度约 6×40＝240 mm，使用 ρ＝1.72×10⁻⁸ Ω·m，DCR≈13.1398 mΩ。它不是由用户再输入一个独立电阻决定。JSON 中旧 dcr 数组不覆盖几何计算。')
    P('本例线圈并绕数 b=1，nstrand=40 表示每根利兹线内有 40 股。如果改为两根相同利兹线并绕 6 匝，b=2，截面为 12 根整线，电气仍是 6 匝；每匝铜面积为 0.628319 mm²，DCR≈6.56992 mΩ。若保持同一 RMS 电流，J 减半；实际工作点随后仍要重算。每根线内分束仅重新组合这 40 股，不能再次增加铜面积。')
    E('J_j=Irms_j/Acu_j')
    rows=[]
    tr0,tr1=[c['display']['magnetics'][0] for c in CASES]
    rows.append(('P','6','40','13.1398',f(tr0['J_actual_p']/1e6,5)+' / '+f(tr1['J_actual_p']/1e6,5)))
    for w0,w1 in zip(tr0['windings'],tr1['windings']):
        rows.append((f"OUT{w0['id']}",str(w0['Ns']),str(w0['n_strand_s']),f(w0['R_dc']*1e3,6),
                     f(w0['J_actual']/1e6,5)+' / '+f(w1['J_actual']/1e6,5)))
    T(['绕组','匝数','股数','DCR mΩ','电流密度 A/mm²'],rows,[.9,.65,.65,1.45,3.45])
    S('所有绕组单股直径均为 0.1 mm。电流密度栏依次是 20 V / 30 V；单位为 A/mm²。输入目标 J＝4 A/mm² 在自动选线时参与预设计，手动线径并不会被自动放大来满足它。')
    H('11.5  交流铜损怎样修正')
    E('δ=√(ρ/(π·fs·μ₀))')
    E('x=dwire/δ；Fr=1+x⁴/(48+0.8·x⁴)')
    E('Pcu=Σ_j Fr_j·Rdc_j·Irms_j²')
    P('本例该简化圆线修正 Fr≈1.00682。它主要反映单股尺寸相对集肤深度的影响，没有准确求解多层邻近效应、利兹绞距和端部损耗。把 40 股全部压成一根粗实心线再算集肤修正也不对，电气模型仍按单股直径计算。')
    P('原边铜损必须使用包括钳位换流路径的绕组 RMS，而不是只用 Q1 RMS。20 V 原边铜损约 0.10375 W，各副边约 0.06828 W、0.00487 W、0.01262 W，合计约 0.18952 W。')
    H('11.6  k α β 不是可以省略的三个数')
    P('本例 k＝27.49、α＝1.456、β＝2.246。它们来自材料在一定温度、频率和磁通范围内的经验拟合。软件采用的基准单位是频率 kHz、磁通 T，得到损耗密度 mW/cm³；换一套单位就必须相应更换 k，不能只保留数字。')
    E('Pv=k·(fs/1000)^α·Bpk^β')
    P('这条经典 Steinmetz 关系适用于相应的正弦数据基准。本例反激磁通非正弦，所以变压器实际使用 NSE 波形积分，并不是简单把反激 Bpk 填进正弦式。')
    E('kN=k/((2π)^(α-1)·∫_0^(2π) |cosθ|^α dθ)')
    E('PvNSE=(ΔB/2)^(β-α)·(kN/Tms)·∫_0^Tms |dB/dtms|^α dtms')
    P('这里的积分先得到损耗密度，时间使用 ms，使频率与原 kHz 拟合一致；最后乘 1000 换成 W/m³，再乘 Ve 得到 W。软件先把事件时间上的磁链参考插值到均匀网格，再做波形积分，避免把相邻极近的事件点误当作均匀采样。')
    E('Pcore=PvNSE·1000·Ve')
    P('式中 PvNSE 是上一式的损耗密度，不是已经乘过体积的功率。NSE 改善了非正弦激励的估算，但不补足材料温度曲线、直流偏置和局部磁场信息。')
    T(['变压器损耗','20 V 输入','30 V 输入'],pair_rows([
        ('全部绕组铜损','display.magnetics.0.P_cu',1,6,' W'),
        ('NSE 磁芯损耗','display.magnetics.0.P_core',1,6,' W'),
        ('变压器总损耗','display.magnetics.0.P_total',1,6,' W'),
    ]),[3,2.05,2.05])
    H('11.7  温升直接用用户热阻')
    E('ΔT=Pmag·Rth')
    P('用户输入的变压器至环境热阻 Ri-a＝100 K/W。20 V 时 ΔT＝0.417204×100≈41.72 K；30 V 时约 47.82 K，均超过配置的 40 K 评审上限。温升 K 的数值与摄氏度差值相同，但不是绝对温度。若环境 25 ℃，简单估算整体温度约为 66.7 ℃、72.8 ℃；环境 25 ℃只是这里的演示假设，不是 JSON 输入。')
    P('这种总损耗乘热阻的集中参数模型不等于绕组热点温度。热阻要按实际骨架、灌封、气流、安装与附近热源校准。旧 h_conv＝10 不再用来替代变压器热阻，不能把两个温升模型重复叠加。')
    source('magnetics  isolated_outputs.multi_magnetics  winding_coupling.resolve_winding_geometry')
    H('11.8  磁导率怎样确定气隙')
    P('材料相对磁导率 μr 无量纲。μr=0 跟随材料手册，le 固定由 Ve/Ae 派生，不需输入。DMR44 初始 μi=2400±25%（25 °C），小信号数据用于初版磁路估算。')
    E('le=Ve/Ae；AL=Lm/Np²；L0=μ₀·μr·Ae·Np²/le')
    E('lg=μ₀·Ae·Np²/Lm−le/μr')
    P('本例 Np=6、Lm=8 μH、Ae=62 mm²、Ve=2814.8 mm³，le=45.4 mm，得 AL=222.222 nH/匝²、无气隙电感 148.272 μH、总等效气隙约 0.331685 mm。两输入端点使用同一气隙。')
    P('lg<0 表示当前磁芯、匝数和磁导率不能实现目标 Lm。计算忽略边缘磁通，实际加工按 AL 测量调整；整副垫片需考虑外柱气隙。来源 TI UCC2863x SLUSBW3D 式 45，https://www.ti.com/lit/ds/symlink/ucc28630.pdf。')

    C('12  窗口能否绕下要单独评估')
    H('12.1  铜面积够不代表实际能够绕制')
    E('fill=Σ_j N_j·Acu_j/Wa')
    P('数据库 Wa＝30 mm² 下，裸铜窗口占比约 18.06%。这是电气面积估算，没有完整扣除漆包绝缘、层间胶带、爬电距离、引线和工艺公差。软件另有真实宽高的分层几何预评估，两者分母和含义不同。')
    H('12.2  本例的机械窗口')
    T(['配置','数值'],[
        ('骨架输入窗口','宽 12 mm  高 3.3 mm'),('左右边距','各 0.25 mm'),
        ('上下边距','各 0.1 mm'),('可用净宽与净高','11.5 mm  3.1 mm'),
        ('单股外径加量','0.03 mm  外径由 0.1 mm 变成 0.13 mm'),
        ('异绕组间绝缘厚度','0.15 mm'),('同绕组普通层间绝缘','0.05 mm  当前相邻层均为异绕组'),
        ('线束填充系数与压扁','0.75  宽乘 1.5  高除以 1.5'),
    ],[3.2,3.9])
    H('12.3  多股等效线束与等面积压扁')
    E('D_b=d_outer·√(nstrand/k_pack)')
    E('b_w=1.5·D_b；b_h=D_b/1.5')
    P('以原边 40 股为例，外径 0.13 mm、填充系数 0.75，等效线束直径约 0.94939 mm，压扁后宽约 1.42408 mm、高约 0.63292 mm。画的是一个等效椭圆，不是把每根细铜丝逐个摆出。填充系数和压扁率为几何假设，真实利兹线含外包层且形状不规则，应以样线测量为准。')
    P('普通单根铜线不套用利兹线的压扁假设。疏绕把本层匝数分散在可用宽度；密绕按紧凑节距排列并可选择靠左、靠右或居中。这些是摆放方式，不会自动重新计算 kij 或 DCR。')
    P('均匀排布是生成初始位置的一键操作。用户可点选某一匝线并左右拖动，或在画布中按左右方向键微调；步长可设，Shift×10、Alt÷10，Ctrl+Z 撤销。首次移动固定物理层序，保存的是稳定段 ID 与本层匝号、束号对应的轴向中心，单位 m；径向位置由层序决定。重叠或净隙不足会标红。保存工程可保留位置，报告与建模导出使用同一坐标；拖动不启动电气求解。')
    F('tutorial_winding','图 7  本例五层交错绕制  OUT1 的 12 匝分成第 1 层和第 5 层各 6 匝',6.95)
    H('12.4  按层相加检查高度')
    rows=[]
    assess=LO['display']['winding_assessment']
    for layer in assess['physical_layers']:
        rows.append((str(layer['layer_index']),layer['winding_id'],str(layer['turns']),
                     f(layer['height']*1e3,6),f(layer['insulation_before']*1e3,4)))
    T(['物理层','绕组','匝数','线束层高 mm','本层前绝缘 mm'],rows,[.65,1.2,.65,2.2,2.4])
    E('H_req=2·m_y+Σ_ℓ h_layer+Σ_ℓ t_layer')
    P('5 层线束总高约 2.493187 mm，加 4 道 0.15 mm 绕组间绝缘，再加上下 0.2 mm 边距，共需要 3.293187 mm。相对 3.3 mm 输入窗口，只剩约 0.006813 mm，也就是 6.81 µm。')
    P('因此界面虽然显示 fits，也只能理解为“名义几何勉强容纳”，不能理解为工程可绕制已经通过。这个余量小于很多常见制造波动的量级，未给引线、交叉跨线和外包胶带留出可靠空间；应增加机械余量并实际试绕。几何预览不是安规认证。')
    source('winding_layout.assess_winding_window  本例 layer_plan 原样保留')

    C('13  汇总总损耗和最终效率')
    H('13.1  先列账再相加')
    P('把同一种热源只记一次。三路整流损耗合计已经包含在半导体损耗里，不能再把每路 D_O 的损耗另加到总损耗。钳位积分只有一项，不再叠加旧漏感估算。输入输出防反二极管单列，电容和磁件损耗也分别计入。')
    rows=[]
    losses=[('P_semi','MOS 与三路整流'),('P_mag','变压器'),('P_cap','全部输出电容 ESR'),
            ('P_cap_in','输入电容 ESR'),('P_sense','采样电阻'),('P_rcd','RCD 钳位'),
            ('P_din','输入防反'),('P_dout','三路输出防反'),('P_controller','控制器附加项'),('P_total','总损耗')]
    for key,label in losses:
        rows.append((label,*vals('result.'+key,1,6,' W')))
    T(['损耗账本','20 V 输入','30 V 输入'],rows,[3,2.05,2.05])
    E('Ploss=Psemi+Pmag+Pcap+Pcap,in+Psense+Prcd+Pdin+Pdout')
    P('控制器项本例为零，表示当前 SSR 算例没有提供完整辅助供电、控制器静态耗电等数据，不表示实物控制器不耗电。门极驱动已经在 MOS 分项中计入，后续新增辅助电源模型时也要避免重复计算同一能量。')
    H('13.2  最终效率由损耗算出')
    E('Pin,final=Po+Ploss；ηfinal=Po/Pin,final')
    P('20 V 时，η＝32.66447÷(32.66447＋5.57098)≈85.4298%；30 V 时，η＝32.65142÷(32.65142＋4.86429)≈87.0340%。不能用 33 W 或文件名 40 W 换掉分子，却仍保留由实际波形得到的损耗。')
    T(['效率口径','20 V 输入','30 V 输入'],[
        ('预设效率','93%','93%'),('评审目标','92%','92%'),
        ('最终计算效率',*vals('result.eta',100,6,'%')),
        ('相对预设差值',*vals('result.eta_delta',100,5,' 个百分点')),
    ],[3,2.05,2.05])
    H('13.3  该先改善哪里')
    P('在这个模型账本中，输入防反、输出防反、RCD 及半导体损耗比较显著。后续若要优化，应先核对这些曲线与保护器件是否符合实际产品方案，再比较替代方案。这里只解释原配置，不自动删除防反二极管或改为同步整流。')
    P('效率与 93% 预设相差约 6～8 个百分点，说明最初预算与后处理结果差距较大。应复核曲线、补足温度与辅助损耗，再决定是否更新预设并重新计算。不可把最终效率回填后不加说明地覆盖原配置，制造“预设和结果完全一致”的假象。')
    source('loss_model.total_losses  第 4 章的两阶段功率口径仍适用')

    C('14  多路输出只有一个主反馈环路')
    H('14.1  环路究竟在控制哪一路')
    P('本例 OUT1 电压经过误差放大和补偿形成控制信号，再调节 Q1 的 PWM。OUT2 与 OUT3 共用这一个开关动作，它们没有各自独立的 PWM，也没有各自独立设定的反馈环。主反馈电压稳定不代表非反馈电压完全稳定。')
    E('T=Gc·Gb；S=1/(1+T)')
    P('Gb 是控制信号到主反馈电压的对象，Gc 是补偿器，T 是开环增益，S 是灵敏度。对每个非反馈输出，还需要控制信号到该输出的传递函数 Gj，而不是复制主反馈 Bode 图。')
    E('Hj=Gj·Gc/(1+Gb·Gc)')
    P('这表示在小扰动条件下，其他输出如何跟随同一个闭环动作。软件在显示各路归一化参考响应时还按各路电压作比例换算，便于比较。负载扰动则需要单独的输出阻抗矩阵。')
    H('14.2  峰值电流内环是什么意思')
    P('采样电阻 Rs＝15 mΩ，电流检测放大倍数 A_sense＝11，总检测系数为 0.165 V/A。每周期电流上升到比较器阈值后关断 Q1。外环决定阈值，内环决定当前周期何时关断。此处的 A_sense 是电流检测通道，不是光耦 CTR。')
    E('vcompare=Rs·A_sense·(ip_off+ma·D·Ts)')
    P('本例斜坡补偿 ma＝0。不能只因标称 D 小于 0.5 就断言所有角点内环都稳定；软件还检查周期映射的极点与首次比较器交点假设。本教程不额外添加实际芯片未指定的驱动、消隐和限流逻辑。')
    H('14.3  软件如何从周期解建立小信号模型')
    E('xnext=F(xstate,d)')
    E('Ad=(∂F)/(∂x)；Bd=(∂F)/(∂d)')
    E('v_j,next=v_j+(Q_j-Ts·v_j/R_j)/C_j')
    P('状态包含三路副边周期初始电流与三路输出电压。软件给各状态和占空比很小的扰动，比较一个周期后状态的变化，得到线性矩阵。电容在每周期末按净电荷更新，不是把输出电压完全冻结到永远。')
    P('峰值电流模式还会把比较器对状态和占空比的变化纳入内环，再把离散周期映射作低频连续等效。软件用两档扰动幅度检查导数一致性；位于明显模式边界、纹波太大或比较器条件不成立时，会拒绝给出具有误导性的唯一 Bode。')
    H('14.4  二型补偿器的极点到底有几个')
    P('controller_type＝auto 且控制为峰值电流模式，当前解析为二型补偿器。二型包含一个原点积分极点、一个有限频率极点和一个有限频率零点。“只看到一个有限频率极点”不等于总共只有一个极点。')
    E('Gc(s)=KP·(1+s/ωz)/(s·(1+s/ωp))')
    E('ωz=2πfz₁；ωp=2πfp₁')
    P('当前 KP＝4178.4914，fz1≈144.987 Hz，fp1≈70.6268 kHz。保存的 fz2≈2.01456 MHz、fp2≈159.155 kHz 不参与当前二型理想 Gc，但第 15 章的物理快车道参考网络会读取完整字段。因此必须分别核验“理想控制器”和“电路参考网络”。KP 在这里是 KP/s 的积分系数，不是普通的无量纲直流放大倍数。')
    H('14.5  穿越频率 相位裕度 增益裕度')
    E('|T(j2πfc)|=1；PM=180+arg(T(j2πfc))')
    E('GMdB=-20·log₁₀|T(jω₁₈₀)|')
    P('穿越频率是开环幅值过 0 dB 的频率。相位裕度是在这个频率距 −180° 还有多少余量。增益裕度在相位到 −180° 时计算，不能从另一张幅频图凭目测随便相减。若扫描范围内没有交点，应报告未观察到，不能把有限范围结果说成无限稳定。')
    F('tutorial_loop','图 8  固定补偿参数下两个输入端点的主反馈开环  高频部分仍是近似外推',6.5)
    T(['环路结果','20 V 输入','30 V 输入'],pair_rows([
        ('穿越频率','result.loop.fc',1,6,' Hz'),('相位裕度','result.loop.pm',1,6,' °'),
        ('扫描内增益裕度','result.loop.gm_db',1,6,' dB'),
        ('闭环极点最大实部','result.loop.closed_loop_max_pole_real',1,6,' rad/s'),
        ('内环周期映射谱半径','result.loop.model.inner_spectral_radius',1,8,''),
    ]),[3,2.05,2.05])
    P('同一套补偿器在两个端点的穿越频率分别约 3.170 kHz、3.802 kHz。没有为 Vinmax 自动另调一套参数，因此穿越频率不必相同。谱半径小于 1 只是该离散内环模型的检查结果，不能替代整个硬件环路的测量。')
    H('14.6  自动整定背后的 K 因子')
    E('boost=PMtarget-90-arg(Gb(j2πfc))')
    E('K=tan(45+boost/2)')
    E('fz=fc/K；fp=fc·K；KP=2πfc/(K·|Gb(j2πfc)|)')
    P('上述角度单位为度，K 因子把零点和极点放在目标 fc 两侧以获得所需相位提升。本教程只解释算法，没有执行整定，也没有覆盖原始 KP。遇到所需相位提升超出二型可实现范围时，不能只提高 KP 来解决相位问题。')
    H('14.7  去掉带宽限制不代表模型变精确')
    P('反激还可能出现右半平面零点：控制动作要求增加送能，但输出在很短时间内可能先朝相反方向变化，限制可用带宽。本例周期映射对象的零点估计约 79.58 kHz；它属于模型的高频估计，不能直接当作实物精确频率，也不能拿旧单路标称对象的零点替代多路矩阵对象。')
    P('当前临时低频 fc 限制已按你的要求停用，但模型仍是小纹波、低频实验近似，不含 ESR/ESL、真实光耦与 TL431 动态、驱动延迟、钳位电容动态和 Coss/Cj 高频谐振。扫描内的 PM、GM 只能作为设计参考，最终需用开关仿真、实物 FRA 和负载变化验证。')
    source('multi_output_loop.build_coupled_loop  plants.make_compensator  loop_tuning.analyze_loop')

    C('15  把理想补偿器变成实际阻容')
    H('15.1  本例选择的参考网络')
    P('JSON 的补偿电路页保留了“TL431 与光耦快车道三型网络”，正向由 KP 和零极点反算阻容。它与第 14 章 auto 解析得到的二型理想补偿器不是同一个选择。保存电路页状态并不会自动使两种模型一致。')
    image=ROOT/'resources/comp_images/tl431f_clean.png'
    figure(doc,image.read_bytes(),'图 9  本例 TL431 光耦快车道参考网络  不是完整可生产原理图',width=6.4)
    P('用户给定 R1＝51 kΩ、CTR＝1、Rpullup＝10 kΩ、Copto＝100 pF。R1 是输出分压上电阻；CTR 是光耦电流传输比；Rpullup 与总光耦侧电容形成极点。CTR 的频率与温度变化、TL431 偏置和实际型号尚未完整建模。')
    H('15.2  可以直接复算的阻容关系')
    E('C₁=1/(2πfz₁·R₁)')
    E('R_LED=CTR·Rpullup/(KP·R₁·C₁)')
    E('Rlower=R₁·2.5/(Vo-2.5)')
    E('C₂=1/(2πfp₂·Rpullup)-Copto')
    cp=LO['compensation']['parts']
    T(['参数','计算值','读法'],[
        ('C1',f(cp['C1']*1e9,6)+' nF','约 21.524 nF'),
        ('R_LED',f(cp['R_LED'],6)+' Ω','约 2.180 kΩ'),
        ('R_lower',f(cp['R_lower'],6)+' Ω','约 4.636 kΩ'),
        ('R_pz',f(cp['R_pz'],6)+' Ω','由现有近似分支给出'),
        ('C_pz',f(cp['C_pz']*1e12,6)+' pF','约 27.178 pF'),
        ('C2',f(cp['C2'],4)+' F','接近零  可理解为不额外并联'),
    ],[1.3,2.3,3.5])
    H('15.3  为什么这组电路不能称为精确实现')
    P('快车道支路满足 fz2＝1/[2π(R_LED＋R_pz)C_pz]，fp1＝1/(2πR_pzC_pz)，因此当电阻电容为正时，必须 fp1＞fz2。当前保存目标却是 fp1≈70.627 kHz，小于 fz2≈2.01456 MHz，无法按这个支路精确实现。')
    E('fz₂=1/(2π·(R_LED+R_pz)·C_pz)')
    E('fp₁=1/(2π·R_pz·C_pz)')
    P('现有程序给出近似高频零极点对，回代后实际 fp1≈8.05824 MHz，而不是目标 70.627 kHz。它可以输出正值器件，但“器件为正、可装配”不等于“网络传递函数匹配目标”。这正是需要在报告里同时列目标、回代和限制说明的原因。')
    T(['回代频率','目标','参考网络回代'],[
        ('fz1','144.987 Hz','144.987 Hz'),('fz2','2.01456 MHz','2.01456 MHz'),
        ('fp1','70.6268 kHz','8.05824 MHz  不匹配'),
        ('fp2','159.155 kHz','159.155 kHz'),
    ],[1.25,2.5,3.35])
    P('另外，理想二型 Gc 根本没有使用 fz2 与 fp2，而这张电路图有完整的快车道和光耦极点。不能把图 8 的相位裕度直接当作图 9 实物电路的相位裕度。后续应选择与二型目标相容的网络，或用实际网络传递函数重新评估。这里不替你修改原配置。')
    H('15.4  还必须补上什么实物检查')
    P('参考图里的 R_bias、TL431 阴极偏置电流、光耦 LED 电流范围、光耦带宽与 CTR 温漂、输出电压范围下的偏置、阻容标准值和容差都要复核。C2≈2×10⁻¹⁸ F 是浮点近零结果，不是需要采购的 2 aF 电容。')
    source('compensation_report.compensation_snapshot  comp_design.tl431_f_solve  tl431_f_eval')

    C('16  用轻重载组合估算交叉调整率')
    H('16.1  最小功耗输入究竟做什么')
    P('每路配置的最小功耗是用来定义轻载端点。本例 OUT1 是 2～30 W，OUT2 是 0.3～1 W，OUT3 是 0.5～2 W。对于每个轻重载组合，软件先按匝比参考电压与配置功率换算固定电阻，再重新求稳态电压。它不是把负载强制成恒功率，也不是在每路电压上直接加一个百分比。')
    E('R_j=V_j,est²/P_j；P_j,actual=V_j²/R_j')
    H('16.2  为什么要扫描而不是预定最坏组合')
    P('常见直觉是“其他路重载、自己轻载时电压最高”，但换流、压降和控制动作可能改变最坏组合。本例完整计算 2³＝8 个负载组合，再乘 2 个输入端点，共 16 点。不能只算你预计最坏的一个组合就宣称得到范围。')
    T(['角点','Vin V','OUT1 W','OUT2 W','OUT3 W','OUT2 V','OUT3 V'],[
        (c['id'],f(c['V_in']),f(c['powers'][0]),f(c['powers'][1]),f(c['powers'][2]),
         f(c['voltages'][1],6),f(c['voltages'][2],6))
        for c in DATA['cross_regulation']['cases']
    ],[.65,.65,.85,.85,.85,1.6,1.65])
    P('16 点全部在当前模型中收敛。两个非反馈输出的最大值都出现在 X004，即 Vin＝20 V、OUT1 配置 30 W、OUT2 0.3 W、OUT3 0.5 W。它并不是“另两路都重载”。这说明最坏组合必须通过所选模型扫描确认。')
    H('16.3  包络和纯交叉变化分开报告')
    E('ΔV_env,%=100·(V_max,j-V_min,j)/V_ref,j')
    P('包络把输入变化、本路轻重载和其他路轻重载全部包含。纯交叉变化则在输入电压和本路负载保持相同的子组内，只改变其他路负载，取最大电压跨度。两者不是同一个指标。')
    cross=DATA['cross_regulation']['summary']
    T(['输出','观察到的电压范围','对参考偏差','包络跨度','纯交叉跨度'],[
        (f"OUT{r['id']}",f(r['V_min'],6)+'～'+f(r['V_max'],6)+' V',
         f(r['deviation_min_pct'],4)+'%～'+f(r['deviation_max_pct'],4)+'%',
         f(r['span_pct'],5)+'%',f(r['cross_only_pct'],5)+'%') for r in cross
    ],[.7,2.15,1.9,1.15,1.2])
    P('OUT1 的 30.000 V 是理想直流主反馈约束，零跨度不等于真实基准、电阻、光耦和控制器的稳压误差为零。OUT3 相对 5 V 的整个包络都偏低，应该优先复核它的压降、匝数与实际负载需求。')
    H('16.4  这些范围不能承诺什么')
    P('这是 16 个采样角点的观察包络，不是对连续输入和负载空间的严格全局极值，更不是负载突变的瞬态过冲。未加入真实跳周期、无负载泄放、Coss/Cj 完整振铃和温度。若最小功耗设为 0 W，但没有预负载或泄放模型，程序不应给出有保证的有限空载电压。')
    source('cross_regulation.scan_cross_regulation  summarize')

    C('17  把结果整理成可以复核的报告')
    H('17.1  Vinmin 和 Vinmax 应该横向比较什么')
    P('复算操作可以按这个顺序进行：导入案例 JSON，确认反激与 SSR，检查 OUT1 为反馈路及三组匝数，选择 Vinmin 查看波形，再切到 Vinmax。保留同一套硬件和补偿参数完成双端点报告，随后检查交叉调整率角点。曲线有未校核或外推提示时，先阅读提示，不要为消除提示随意更换单位或改动数据。')
    P('Excel 每个 Sheet 对应一个模块，两种输入工况放左右两侧，适合查最坏应力；Word 可先给总览，再依模块解释。看报告时先确认相同硬件、相同反馈路、相同补偿参数，再比较输出，不能只挑一列“通过”作为设计结论。')
    T(['关键结果','20 V 输入','30 V 输入','本例怎样判断'],[
        ('Q1 峰值电流','6.1522 A','5.9314 A','20 V 较大'),
        ('Q1 钳位电压','43.025 V','53.025 V','30 V 较大'),
        ('最终计算效率','85.4298%','87.0340%','均低于 92% 目标'),
        ('变压器温升','41.720 K','47.823 K','30 V 更严苛  均超 40 K'),
        ('OUT3 低频纹波','60.413 mV','59.174 mV','均超 50 mV 配置阈值'),
        ('OUT3 直流输出','4.54866 V','4.53800 V','均低于 5 V 匝比参考'),
        ('物理补偿网络','快车道近似支路','同一套参考阻容','不能直接沿用理想二型 PM'),
    ],[1.7,1.35,1.35,2.7])
    H('17.2  本例的检查项应该怎样解释')
    P('L 初选提示并不等于 CCM 失败；裸铜填充率通过不等于机械可绕制；相位裕度通过不等于物理光耦电路已验证；16 个角点全部收敛不等于输出电压满足产品规范。报告应分别保留模型有效性、数值收敛和产品要求三个层次。')
    H('17.3  建议按这个顺序复核')
    P('先确认真正的功率需求是 33 W 还是 40 W，以及 5V 路是否要求负载端精确 5 V。然后核对 MOS 和二极管的完整型号、测试条件与曲线倍率，补足曲线未校核和外推项。接着确认实际骨架窗口、绝缘和绕制余量，并校准 DCR、互感或漏感、热阻。')
    P('在电气模型输入可信后，再重新分配纹波和温升目标、选择能够实现理想控制器的物理补偿网络，使用实际阻容回代环路。最后通过开关仿真与样机逐步核对电流、Vds 尖峰、二极管反压、纹波、效率、热稳态和 FRA。这里列的是后续复核路径，本教程没有执行硬件修改。')
    H('17.4  对初学者尤其重要的测试边界')
    P('带电测量要注意隔离与地线连接，示波器接地方式可能直接改变或短接电路。测高 dv/dt 节点应使用适当量程、带宽和接法的探头。不要仅凭本例低压输入就忽略储能、短路和器件击穿风险。首次样机应采用限流和逐级上电，由具备相关经验的人复核。')

    C('附录 A  生效参数速查')
    P('以下用于对照软件界面与 JSON。它不是重新设计参数。多路支路的配置优先于历史顶层输出字段；未启用拓扑和控制模式的字段仍可能保存在旧 JSON 中，但不应被当作本例的有效计算项。')
    H('A1  输入 主开关和采样')
    T(['参数','本例数值','用途'],[
        ('Vinmin Vinmax','20 V  30 V','双端点'),('fs L','250 kHz  8 µH','周期与原边开路自感'),
        ('Rs A_sense ma','15 mΩ  11  0 A/s','峰值电流检测和内环'),
        ('Rds(on) Coss','50 mΩ  200 pF','导通及硬开关输出电容损耗'),
        ('Vgs Vth','10 V  3 V','栅极驱动与阈值'),
        ('Rg_drive Rs_on Rs_off Rg','2 Ω  6.8 Ω  6.8 Ω  1.9 Ω','驱动内阻 外部栅阻 MOS 内部栅阻'),
        ('k_sw','0.25','开关交叠经验系数'),
        ('Kc dC','1.5  0.1','钳位比与纹波比例'),
        ('输入电容组','330 µF 与 100 µF 并联','ESR 15 mΩ 与 0.1 mΩ  ESL 均 5 nH'),
        ('输入防反','启用 D_IN 曲线','按输入脉冲积分损耗'),
    ],[2.15,2.1,2.85])
    H('A2  各路独立器件')
    T(['项目','OUT1','OUT2','OUT3'],[
        ('参考电压','30 V 主反馈','12.5 V 匝比参考','5 V 匝比参考'),
        ('最大配置功率','30 W','1 W','2 W'),('最小配置功率','2 W','0.3 W','0.5 W'),
        ('副边匝数','12','5','2'),('单股直径','0.1 mm','0.1 mm','0.1 mm'),
        ('并绕股数','30','10','20'),('主电容','330 µF','220 µF','470 µF'),
        ('主电容 ESR','40 mΩ','40 mΩ','20 mΩ'),('主电容 ESL','5 nH','5 nH','5 nH'),
        ('并联电容','10 µF','10 µF','10 µF'),('并联 ESR ESL','0.1 mΩ  0.1 nH','0.1 mΩ  0.1 nH','0.1 mΩ  0.1 nH'),
        ('整流损耗','D_O1 曲线','D_O2 曲线','D_O3 曲线'),
        ('输出防反','D_B1 曲线','D_B2 曲线','D_B3 曲线'),
        ('周期求解固定压降','0.7 V','0.7 V','0.7 V'),('Qrr','0','0','0'),('纹波目标','1%','1%','1%'),
    ],[1.75,1.8,1.8,1.75])
    H('A3  变压器和补偿')
    T(['参数','生效值'],[
        ('磁芯 材料','PQ20 20  DMR44 标签'),('Bmax Bsat','0.3 T  0.4 T'),
        ('目标电流密度 J 和 Ku','4 A/mm²  0.3  手动绕组以实际结果复核'),
        ('原边 Np 线径 股数','6 匝  0.1 mm  40 股'),('MLT ρ','40 mm  1.72×10⁻⁸ Ω·m'),
        ('k α β','27.49  1.456  2.246'),('热阻 温升上限','100 K/W  40 K'),
        ('两两耦合','所有不同绕组 kij＝0.995'),
        ('理想补偿器','auto 解析为二型'),('KP fz1 fp1','4178.4914  144.987 Hz  70.6268 kHz'),
        ('目标 fc PM','3200 Hz  82°'),('电路参考网络','TL431 光耦快车道  正向计算'),
        ('电路用户输入','R1 51 kΩ  CTR 1  Rpullup 10 kΩ  Copto 100 pF'),
    ],[2.4,4.7])
    H('A4  保存了但本例不按该值直接计算的字段')
    T(['历史或备用字段','本例处理'],[
        ('顶层 P_out 40 W 顶层 Rc 82 mΩ','由各路表优先  不是把 40 W 当实际总输出'),
        ('固定 Vgp Qgs Qg 等备用值','当前两条 MOS 曲线启用  采用曲线读取结果'),
        ('mos_manual_events 四组手动平台','当前曲线模式不使用这四组旧手动值'),
        ('旧动态电阻 Rd','当前二极管不使用动态电阻项'),
        ('旧 coupling_config.dcr 数组','不覆盖 MLT 线径 匝数 股数推导 DCR'),
        ('旧 RCD K 0.99','矩阵已给出等效漏感  不再据此另加漏感损耗'),
        ('ring_margin 30%','反激 MOS 钳位应力按 Kc  不额外叠加'),
        ('h_conv 10','变压器温升改用用户 Ri-a'),
        ('各路 L 正激电感磁芯','本例反激不设独立输出电感'),
        ('MP6005 PSR 参数','本例是 SSR  不启用辅助绕组 PSR 计算'),
        ('有源钳位正激相关字段','拓扑不是正激  不参与本例'),
        ('fz2 fp2','不进入当前理想二型 Gc  但物理网络参考页会读取'),
        ('sweep_var sweep_min max n','扫描设置  不是当前端点的额外电气约束'),
    ],[2.75,4.35])

    C('附录 B  复习题与答案')
    practice('为什么导入文件名叫 40W，而最终输出是约 32.66 W','各路配置合计是 33 W；非反馈路在恒阻负载下电压变化，使实际输出功率再发生变化。文件名和旧顶层字段不能覆盖当前三路结果。')
    practice('为什么 30 V 输入的 MOS 导通损耗较小，但关断损耗较大','前者主要跟 RMS 电流平方有关，后者还乘关断电压、关断电流和转换时间。输入升高后 Vds 上升，可能抵消或超过电流下降的影响。')
    practice('OUT2 电容组 RMS 比其中一只电容 RMS 小，是不是一定计算错误','不是。并联电容按复阻抗分流，存在相位差和循环电流；需要检查复数分流，不能按 RMS 标量直接相加。')
    practice('四个开关事件是否一定要有四个不同 Qgd','不一定。本例复用同一条参考栅电荷曲线，Qgd 相同；平台电压与平台前 Qgs 随事件电流变化。只有实际数据支持时才能引入电流和 Vds 维度的 Qgd 变化。')
    practice('骨架几何显示可容纳，为什么仍不建议直接投产','本例高度只剩约 6.81 µm 名义余量，未计引线、公差和完整绝缘，几何通过不等于制造与安规通过。')
    practice('为什么图中 PM 接近 82°，补偿电路仍要重新检查','Bode 使用理想二型补偿器；保存的快车道物理参考网络存在零极点不匹配，且真实光耦 TL431 动态未完整纳入。')
    practice('交叉调整率为 16 个角点全部收敛，是否等于设计合格','不是。收敛只是当前数学模型有解；实际电压可能偏离规范，而且未穷尽连续范围、温度、容差和瞬态。')

    C('附录 C  复算入口与来源')
    H('C1  对应到项目代码')
    T(['计算内容','主要实现文件或函数'],[
        ('配置解析和反馈路','config_io  isolated_outputs  transformer_turns'),
        ('稳态耦合电流','winding_coupling  coupled_flyback'),
        ('波形和电容分流','waveforms  isolated_outputs.coupled_waveforms  capripple'),
        ('MOS 平台和电荷','mos_curves  mos_gate_charge  mos_gate'),
        ('MOS 二极管损耗','semiconductor  diode_curves  loss_model'),
        ('钳位与应力','flyback_clamp  semiconductor.device_stress'),
        ('磁芯和绕组','magnetics  isolated_outputs.multi_magnetics'),
        ('绕制几何','winding_layout.assess_winding_window'),
        ('环路和整定','multi_output_loop  plants  loop_tuning'),
        ('补偿参考网络','comp_design  compensation_report'),
        ('交叉调整率','cross_regulation.scan_cross_regulation'),
        ('固定硬件双端点','input_voltage_range  design_engine.service'),
    ],[2.2,4.9])
    P('复算时应在项目科学计算环境中读取原 JSON，调用 design_engine.service.calculate，选择 analysis 为 endpoints，并开启 include_cross_regulation。若要导出软件标准 Word 或 Excel 工程报告，还需在准备阶段开启 include_efficiency，先完成效率扫描。教程本身不依赖打开过哪些软件页签。')
    H('C2  本教程的可复现信息')
    P('源配置文件名为 '+DATA['source']['name']+'。教程按读取时的原内容计算，不修改源文件。完整参数与波形快照、图表生成脚本及本教程生成脚本分别保存在 artifacts/tutorials 和 docs/tutorials 中，便于后续维护。')
    S('源 JSON SHA256  '+DATA['source']['sha256'])
    S('计算模型版本  '+str(DATA['provenance']['model_version']))
    S('计算源码指纹  '+str(DATA['provenance']['code_fingerprint']))
    S('2026-10-23 初版保留记录  当时公式说明 SHA256  '+DATA['original_reference_sha256'])
    H('C3  进一步阅读')
    P('[1] Texas Instruments  Power Tips 关于多输出反激交叉调整率的技术说明。用于理解漏感和绕组连接如何影响多路输出，不作为本例电压的替代计算。')
    S('https://www.ti.com/document-viewer/lit/html/SSZTCW3/GUID-9BE5B4A2-3166-4329-A3F0-4F836580FCC7')
    P('[2] Texas Instruments  Fundamentals of MOSFET and IGBT Gate Driver Circuits  SLUA618A，重点看开通 关断和栅电荷章节。用于理解门极阶段，本文具体 LN 时间公式仍以项目实现为准。')
    S('https://www.ti.com/lit/ml/slua618a/slua618a.pdf')
    P('[3] Toshiba  Electrical characteristics of MOSFETs  Charge Characteristic。用于区分阈值前后电荷 米勒平段和总栅电荷，不表示不同厂商的所有 Qgs 命名完全相同。')
    S('https://toshiba.semicon-storage.com/us/semiconductor/knowledge/faq/mosfet/electrical-characteristics-of-mosfetscharge-characteristic-qg-qg.html')
    P('本教程没有复刻整本参考书或规格书。电路图和计算曲线由项目绘图代码生成，公式按当前软件实现解释。实际产品应继续核对所选器件的完整规格书和适用的安全要求。')

    # Avoid inherited decorative title borders, do not edit the reference.
    for border in list(doc.element.xpath('.//w:pBdr')):
        border.getparent().remove(border)
    for p in doc.paragraphs:
        p.paragraph_format.widow_control=True
    from docs.update_cross_regulation_documents import update_document
    update_document(doc, 'tutorial')
    OUT.parent.mkdir(parents=True,exist_ok=True)
    doc.save(OUT)
    assert hashlib.sha256(REF.read_bytes()).hexdigest()==baseline
    (ART/'equations.json').write_text(json.dumps(eq_manifest,ensure_ascii=False,indent=2),encoding='utf-8')
    print(json.dumps(dict(output=str(OUT),equations=len(eq_manifest),figures=len(doc.inline_shapes),
        tables=len(doc.tables),paragraphs=len(doc.paragraphs),original_unchanged=True),ensure_ascii=False))


if __name__=='__main__':
    build()
