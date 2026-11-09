"""Insert the same verified cross-regulation case into both editable manuals.

Use the bundled document Python. Re-running replaces only the marked addition;
existing chapters, figures and the tutorial's original 33 W case are preserved.
Refresh numerical evidence with docs/examples/collect_cross_regulation_example.py
using the project's numerical environment before changing the worked example.
"""
from pathlib import Path
from copy import deepcopy
import argparse
import hashlib
import json
import math
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from docx import Document
from docx.shared import Inches, Pt, RGBColor
from docx.oxml import OxmlElement
from docx.oxml.ns import qn
from docx.enum.text import WD_ALIGN_PARAGRAPH
from docx_layout import paragraph, table, figure, _font
import word_math as wm

DATA_PATH = ROOT/'docs/examples/cross_regulation_worked_example.json'
QA = ROOT/'artifacts/documentation/cross-regulation-20261102'
TARGETS = {'reference':ROOT/'docs/reference/计算方法与公式说明.docx',
           'tutorial':ROOT/'docs/tutorials/多路反激电源设计入门教程.docx'}
START, END = 'cross_regulation_worked_start', 'cross_regulation_worked_end'


def load_data():
    data = json.loads(DATA_PATH.read_text(encoding='utf-8'))
    assert hashlib.sha256((ROOT/data['source']).read_bytes()).hexdigest() == data['source_sha256']
    for name, expected in data['code_sha256'].items():
        assert hashlib.sha256((ROOT/name).read_bytes()).hexdigest() == expected, f'Recompute documentation evidence after changing {name}'
    assert data['result']['complete'] and len(data['result']['cases']) == 16
    assert data['focus']['solver']['success']
    return data


def make_figures(data):
    import matplotlib
    matplotlib.use('Agg')
    import matplotlib.pyplot as plt
    import numpy as np
    plt.rcParams.update({'font.family':'Microsoft YaHei', 'axes.unicode_minus':False,
        'font.size':10, 'axes.titlesize':11, 'axes.labelsize':10,
        'axes.spines.top':False, 'axes.spines.right':False})
    QA.mkdir(parents=True,exist_ok=True)
    focus=data['focus']; wave=focus['final']['waveform']
    times=np.array(wave['time_s'])*1e6; currents=np.array(wave['currents_A'])
    fig,axs=plt.subplots(2,2,figsize=(9,4.6),layout='constrained')
    for j,(ax,name,color) in enumerate(zip(axs.flat,
            ['原边绕组电流','OUT1 副边电流','OUT2 副边电流','OUT3 副边电流'],
            ['#205b99','#1c8779','#b17624','#78519c'])):
        ax.plot(times,currents[:,j],color=color,lw=1.7)
        ax.axvline(focus['final']['duty']*4,color='#9ba7b3',ls='--',lw=.8)
        ax.set(title=name,xlabel='时间 / μs',ylabel='电流 / A',xlim=(0,4))
        ax.grid(alpha=.18);ax.margins(y=.12)
    fig.savefig(QA/'x004_current.png',dpi=180);plt.close(fig)
    rows=[focus['initial'],*focus['accepted']]
    fig,axs=plt.subplots(1,2,figsize=(9,3.2),layout='constrained')
    axs[0].semilogy(range(len(rows)),[r['max_abs_residual'] for r in rows],color='#205b99',marker='.',ms=4)
    axs[0].axhline(2e-5,color='#a44138',ls='--',lw=.9,label='物理残差验收阈值')
    axs[0].set(xlabel='已接受的更新次数',ylabel='最大归一化残差',title='初猜到收敛');axs[0].legend(fontsize=8)
    for j,color in [(1,'#1c8779'),(2,'#b17624')]:
        axs[1].plot(range(len(rows)),[r['output_port_V'][j] for r in rows],color=color,label=f'OUT{j+1}')
    axs[1].set(xlabel='已接受的更新次数',ylabel='端口电压 / V',title='未知输出电压逐步修正');axs[1].legend()
    for ax in axs:ax.grid(alpha=.18)
    fig.savefig(QA/'x004_convergence.png',dpi=180);plt.close(fig)


def number(x, digits=6):
    return f'{x:.{digits}g}'


class Writer:
    def __init__(self,doc,kind):
        self.doc=doc;self.kind=kind;self.equations=0;self.heading=0
        self.prefix='19' if kind=='reference' else '16'
        self.math_prefix='CR' if kind=='reference' else '练习'
        aliases={
            'Vcap1':'V_c,1','Vcapj':'V_c,j','Voutj':'V_out,j','Vrefj':'V_ref,j',
            'Vref2':'V_ref,2','Vref3':'V_ref,3','Vrect1':'V_F,1','Vrectj':'V_F,j',
            'Vblock1':'V_B,1','Vblockj':'V_B,j','Vdin':'V_D,in','Psetj':'P_set,j',
            'Rloadj':'R_load,j','Pactualj':'P_actual,j','Li':'L_ii','Lj':'L_jj',
            'Mij':'M_ij','kij':'k_ij','Ni':'N_i','Np':'N_p','Ns1':'N_s,1','Nsj':'N_s,j',
            'Lp':'L_p','Lsigma':'L_σ,p','Lpp':'L_pp','Lps':'L_ps','Lss':'L_ss','Lsp':'L_sp',
            'Acu':'A_Cu','Rdcj':'R_dc,j','npar':'n_par','dwire':'d_wire','lMLT':'l_MLT',
            'iA':'i_A','LA':'L_A','RA':'R_A','uA':'u_A','Lmat':'L','Rmat':'R','umat':'u',
            'Rpon':'R_p,on','Rpoff':'R_p,off','Qj':'Q_j','Idavgj':'I_D,j,avg',
            'Iloadj':'I_load,j','I0j':'I_0,j','Iendj':'I_end,j','Ipend':'I_p,end',
            'Iscalej':'I_scale,j','Jscalej':'J_scale,j','Ipkseed':'I_pk,seed',
            'Iminseed':'I_min,seed','Ionavg':'I_p,on,avg','Dseed':'D_seed','Pseed':'P_seed',
            'U':'U','q0':'q_0','qend':'q_end','Cmat':'C','Umat':'U','Hmat':'H',
            'zmodal':'z','amodal':'a','bmodal':'b','hstep':'h','lambda':'λ',
            'rperj':'r_per,j','rqj':'r_Q,j','rend':'r_end','Robj':'r','xvec':'x',
            'Senv':'S_env','Scross':'S_cross','Vmax':'V_max','Vmin':'V_min',
            'Vref':'V_ref','Ebal':'ε_E','Pload':'P_load','PlossRL':'P_loss,RL',
            'Qon':'Q_p,on','Qclamp':'Q_p,clamp','Pclamp':'P_clamp'}
        aliases.update({'i_j':'i_j','w_j':'w_j','Vout2':'V_out,2','Vout3':'V_out,3',
                        'I01':'I_01','I02':'I_02','I03':'I_03',
                        'Iscale1':'I_scale,1','Iscale2':'I_scale,2','Iscale3':'I_scale,3'})
        wm.ALIASES.update(aliases)
        wm.NAMES=sorted(wm.ALIASES,key=len,reverse=True)

    def P(self,text):
        p=paragraph(self.doc,text)
        p.paragraph_format.line_spacing=1.15
        p.paragraph_format.space_after=Pt(6)
        return p

    def H(self,text,*,new_page=False):
        self.heading+=1
        n=self.heading if self.kind=='reference' else self.heading+4
        p=self.doc.add_heading(f'{self.prefix}.{n}  {text}',2)
        p.paragraph_format.page_break_before=new_page
        for r in p.runs:_font(r,14,True,'000000')
        return p

    def E(self,text=None,nodes=None):
        self.equations+=1
        p=self.doc.add_paragraph();p.paragraph_format.line_spacing=1.0
        p.paragraph_format.space_before=Pt(3);p.paragraph_format.space_after=Pt(6)
        math=wm.element('oMath',*(nodes if nodes is not None else wm.math_nodes(text)))
        p._p.append(math)
        _font(p.add_run(f'   ({self.math_prefix}{self.equations:02d})'),9)
        return p

    def T(self,headers,rows,widths=None,small=False):
        rows=list(rows);t=table(self.doc,headers,rows,widths)
        for row in t.rows:
            for cell in row.cells:
                for p in cell.paragraphs:
                    p.paragraph_format.line_spacing=1.1
                    if small:
                        for run in p.runs:run.font.size=Pt(9)
        return t

    def F(self,name,caption):figure(self.doc,(QA/name).read_bytes(),caption,width=6.95)


def add_worked_example(doc,kind,data=None):
    data=data or load_data();w=Writer(doc,kind)
    focus=data['focus'];inputs=focus['inputs'];final=focus['final'];cases=data['result']['cases']
    refs=inputs['target'];geom=data['geometry'];summary=data['result']['summary']
    if kind=='reference':
        title=doc.add_heading('19  三路反激交叉调整率的完整求解算例',1)
        title.paragraph_format.page_break_before=True
        for run in title.runs:_font(run,18,True,'000000')
        w.P('本章把输入参数、绕组方程、二极管换流、周期稳态迭代和交叉调整率统计连成一个可复算的例程。采用 examples/3_OUTPUT_CROSS_REGULATION.json；2026 年 11 月 2 日用当前 Python 内核复算，16 个角点均收敛。所列小数用于核对算法，不代表硬件具有同等精度。')
    else:
        w.P('下面把第 5 章的耦合模型和本章的角点扫描完整串起来。原教程前面的 33 W 算例及结果保留；本练习另用 40 W 交叉调整率算例，三路最大功率改为 30、0.5、9.5 W。请不要把下面的 X004 与前面 33 W 案例的同名角点混用。')
    w.H('先确定算例和测量位置')
    w.P('学习目标是回答一个具体问题：OUT1 稳压时，OUT2 与 OUT3 在其他路轻重载变化后会停在哪个直流电压。先猜各路电压和周期起始电流，计算一个开关周期，再检查一周期后是否回到原状态、各路电容是否不再净充电。只有这些条件同时成立，才得到当前负载的稳态结果。')
    w.T(['项目','本练习输入','作用'],[
        ('拓扑与反馈','固定频率反激  SSR  OUT1 主反馈','仅主反馈路固定直流目标'),
        ('输入与频率','Vin 20–30 V  fs 250 kHz','两端输入共用一套硬件'),
        ('电感与匝数','Lp 8 μH  Np 6  Ns 12 / 5 / 2','Lp 为原边开路自感'),
        ('耦合与钳位','所有非对角 kij=0.995  Kc=1.5','完整矩阵包含漏感影响'),
        ('主开关与采样','Rds(on) 50 mΩ  Rsense 15 mΩ','进入 ON 段原边电阻'),
        ('二极管固定压降','输入防反、各路整流和输出防反均 0.7 V','本练习换流使用固定压降'),
        ('预设效率','93%','只用于求解初猜，不重复计损'),
    ],[1.35,3.15,2.6])
    w.P('电压、负载与交叉调整率都在输出防反管之后的端口统计；SSR 在 OUT1 防反管之前的电容端取样。输入 Vin 指输入连接器；输入防反管之后才是原边功率母线。所有方程内部使用 SI 单位。')
    w.E('Vcap1 = 30+0.7 = 30.7')
    w.E('Vinbus = Vin-Vdin = 20-0.7 = 19.3')
    w.P('以上数值单位为 V。主路电容固定在 30.7 V，扣去 0.7 V 固定防反压降后，端口为 30 V。这是模型的理想直流反馈约束，不包含基准、分压、光耦和真实控制器的误差。')

    w.H('用匝数和压降得到参考电压及负载')
    w.P('匝比先给出非反馈路的参考值，供负载换算和数值归一化使用。它不是最后求出的电压。先把主路电容电压与整流压降相加，按副边匝数比例换算，再扣掉本路整流和输出防反压降。')
    w.E('Vrefj = (Nsj/Ns1)·(Vcap1+Vrect1)-Vrectj-Vblockj')
    w.E('Vref2 = (5/12)·31.4-0.7-0.7 = 11.683333')
    w.E('Vref3 = (2/12)·31.4-0.7-0.7 = 3.833333')
    w.P('OUT2 和 OUT3 的名称仍可叫“12 V”“5 V”，但名称不参与计算。本练习的参考值实际是 11.683333 V 和 3.833333 V。负载功耗设置定义恒定电阻；输出电压变化时，实际功耗随之变化。')
    w.E('Rloadj = Vrefj²/Psetj')
    w.E('Iloadj = Voutj/Rloadj ; Pactualj = Voutj²/Rloadj')
    w.T(['输出','参考 / V','轻载设置 / W','重载设置 / W','轻载 R / Ω','重载 R / Ω'],[
        (f'OUT{j+1}',f'{refs[j]:.6f}',s['P_min'],s['P_max'],
         f'{refs[j]**2/s["P_min"]:.6f}',f'{refs[j]**2/s["P_max"]:.6f}') for j,s in enumerate(summary)
    ],[.7,1.15,1.1,1.1,1.55,1.5])
    w.P('例如 OUT2 选 0.05 W，是接入约 2730.005556 Ω。电压求到 13.562505 V 后，其实际功耗约为 0.067378 W，不再是 0.05 W。若误把每一步都强制成恒功率负载，得到的是另一套模型。')

    w.H('从几何数据建立电感矩阵和绕组电阻')
    w.P('电流参考方向全部指向绕组同名端；副边同名端位于回路返回侧，所以正的副边电流对应整流导通方向。向量次序统一为 P、S1、S2、S3；在这个方向约定下，矩阵非对角项为正。')
    w.E('Li = Lp·(Ni/Np)² ; Mij = kij·√(Li·Lj)')
    rows=[wm.element('mr',*(wm.element('e',*wm.math_nodes(f'{v*1e6:.6f}')) for v in row)) for row in inputs['matrix']]
    mat=wm.element('d',wm.element('dPr',wm.element('begChr',val='['),wm.element('endChr',val=']')),
                   wm.element('e',wm.element('m',*rows)))
    w.E(nodes=[*wm.math_nodes('Lmat = '),mat,*wm.math_nodes('·10⁻⁶')])
    w.P('矩阵单位为 H，括号内按 μH 列出；显示值经过舍入，求解使用原始浮点精度。矩阵必须对称且正定。此例特征值约为 0.005726、0.032227、0.073657、46.332834 μH。k=1 的奇异理想矩阵不用于这套非理想交叉调整率求解。')
    w.E('Lsigma = Lpp-Lps·Lss⁻¹·Lsp = 0.053311·10⁻⁶')
    w.P('上式是其余副边全部短路时折算到原边的漏感，用于解释与检查。完整电感矩阵已包含这部分漏磁影响，不能再串入同一份漏感，否则会重复计算。')
    w.E('Acu = npar·π·dwire²/4 ; Rdcj = ρ·lMLT·Ni/Acu')
    w.T(['绕组','匝数','裸铜直径 / mm','股数','MLT / mm','DCR / mΩ'],[
        (label,int(geom['turns'][j]),f'{geom["diameter_m"][j]*1e3:g}',int(geom['strands'][j]),
         f'{geom["MLT_m"]*1e3:g}',f'{inputs["dcr"][j]*1e3:.6f}')
        for j,label in enumerate(['P','S1','S2','S3'])
    ],[.65,.65,1.45,.65,1.2,2.5])
    w.P('电阻率取 1.72×10⁻⁸ Ω·m。例如原边总铜面积为 40×π×(0.1 mm)²/4=0.314159 mm²，线长为 6×40 mm=240 mm，得到 13.139832 mΩ。这里不读取旧的手填 DCR。')

    w.H('按开关状态写出绕组方程')
    w.E('Lmat·(di/dt)+Rmat·i = umat')
    w.P('i 是四个绕组电流。R 为该状态下的对角电阻矩阵，u 是所施加的绕组端电压。输出电容在一个周期内先当作恒定直流电压，待周期电荷平衡求出后再另外重建纹波。')
    w.E('Rpon = 0.013139832+0.05+0.015 = 0.078139832')
    w.E('Rpoff = 0.013139832')
    w.P('ON 段原边施加 +19.3 V；OFF 段原边经钳位支路施加 −23.55 V。三路副边端电压始终按 −(电容电压+整流压降) 写入；二极管截止时该支路电流为零，是否重新导通由互感感应电压决定。')
    w.E('Vclamp = 1.5·(6/12)·(30.7+0.7) = 23.55')
    w.P('Vclamp 是相对输入母线的钳位电压。Vin=20 V 时对应理想 Vds 钳位上限 19.3+23.55=42.85 V；它不是直接把 Vds 设置成 23.55 V。OFF 原边支路为钳位回流，不能当成 MOS 仍在导通。')
    w.E('LA·(diA/dt)+RA·iA = uA')
    w.P('A 表示当前正在导通的绕组集合。软件只解 L 的 A×A 子矩阵，截止绕组电流固定为零。导通二极管电流下降到零时退出；截止二极管的电压条件允许正向电流时加入。MOS 在 ON 段按控制命令导通，其条件与被动二极管不同。')
    w.E('w = Lmat·(di/dt)+Rmat·i-umat')
    w.E('i_j ≥ 0 ; w_j ≥ 0 ; i_j·w_j = 0')
    w.P('这组三个条件称为二极管互补条件：导通支路电压余量为零；截止支路不能产生负的禁止电压余量。每次遇到事件后重新确定导通集合，因此允许原边开通后的短暂副边换流，也允许不同副边分别进入 CCM 或 DCM。')

    w.H('每一段怎样精确推进电流并积分电荷')
    w.P('一个导通集合不变的区间是系数恒定的 RL 电路。它不需要用屏幕上的折线点做欧拉积分。先做 Cholesky 分解和对称特征分解，转换到相互独立的指数衰减模态，再直接计算段末电流和本段电流面积。')
    w.E('LA = Cmat·Cmat^T ; Hmat = Cmat⁻¹·RA·Cmat^(-T)')
    w.E('Hmat = Umat·Λ·Umat^T ; q0 = Umat^T·Cmat^T·iA(0)')
    w.E('g = Umat^T·Cmat⁻¹·uA ; zmodal = lambda·hstep')
    w.E('amodal = (1-exp(-lambda·hstep))/lambda ; bmodal = (hstep-amodal)/lambda')
    w.E('qend = q0·exp(-lambda·hstep)+g·amodal')
    w.E('iA(hstep) = Cmat^(-T)·Umat·qend')
    w.E('Q = Cmat^(-T)·Umat·(q0·amodal+g·bmodal)')
    w.P('Λ 是特征值对角矩阵；上式的 λ、a、b 和 exp 在每个模态逐元素计算，h 为区间时长。λ 趋近于零时用 a→h、b→h²/2；代码在 |λh|<10⁻⁴ 时用相应级数，其他情况用 expm1 减少消减误差。RMS 所需的电流平方积分使用每段 20 点 Gauss 积分；电荷 Q 使用上面的解析积分。')
    w.P('为找下一个二极管事件，当前实现先在剩余相位区间作 12 段探测，再用 Brent 求根定位边界。电流判零容差为 10⁻⁹ A，电压容差为 10⁻⁸×max(Vinbus,Vclamp,1) V，最小时段为 Ts×10⁻¹²。这些是数值参数，不是硬件测量分辨率。')
    w.P('可以先核对只有原边导通的一段，暂不看矩阵：初始电流为 1.761599 A，持续 1.817142 μs，L=8 μH，R=0.078139832 Ω，电源为 19.3 V。')
    w.E('i(hstep) = (19.3/0.078139832)+(1.761599-19.3/0.078139832)·exp(-0.078139832·hstep/(8·10⁻⁶))')
    w.P('代入 h=1.817142×10⁻⁶ s，得到约 6.075788 A，与完整求解的该段末值一致。这里的指数式既体现电感斜率，也体现 MOS、采样电阻和铜线压降。')

    w.H('先为 X004 准备一个合理初猜')
    w.P('从 16 个角点中选 X004 展开：Vin=20 V，三路功耗设置为 30、0.05、0.95 W。负载已固定为 30、2730.005556、15.467836 Ω；此时实际输出电压仍未知。预设效率 93% 只帮助给出起始占空比和电流量级。')
    w.E('U = 30/0.93 = 32.258065 ; Pseed = (30+0.05+0.95)/0.93 = 33.333333')
    w.E('Dseed = (0.5·U)/(20+0.5·U) = 0.446429')
    w.E('Ionavg = Pseed/(20·Dseed) = 3.733333')
    w.E('ΔIp = (20·Dseed)/(250000·8·10⁻⁶) = 4.464286')
    w.E('Iminseed = Ionavg-ΔIp/2 = 1.501190')
    w.E('Ipkseed = Ionavg+ΔIp/2 = 5.965476')
    w.P('初猜把原边谷值按各路功耗占比和 Np/Nsj 暂时分配到副边，得到周期起始副边电流 0.726382、0.002906、0.138013 A。OUT2/OUT3 电压先取 11.683333/3.833333 V。这个功率比例只用来启动求解；后面的电流由完整 RL 方程决定。初猜阶段使用 Vin=20 V 的旧预设计模型，正式电路使用扣掉输入防反后的 19.3 V，不再叠加效率压降。')

    w.H('六个未知量同时满足七个平衡残差')
    w.P('待调整的物理量有六个：三个副边周期起始电流，两个非反馈端口电压，以及占空比 D。主反馈电容电压固定 30.7 V，开关周期固定 4 μs，周期起始原边电流固定为零。零原边支路电流不等于磁通为零，上一周期末还可能有副边电流。')
    w.E('xvec = [I01/Iscale1,I02/Iscale2,I03/Iscale3,Vout2/Vref2,Vout3/Vref3,D]^T')
    w.P('其中 Iscale 为初猜峰值与额定电流等量级的较大值，三路分别为 2.886520737、0.011546083、0.548438940 A；负载残差量级 Jscale=max(Pset/Vref,0.001 A)。归一化避免大电流路的残差把小电流路淹没，不改变物理方程。')
    w.E('rperj = (Iendj-I0j)/Iscalej')
    w.E('rqj = ((Qj/Ts)-Voutj/Rloadj)/Jscalej')
    w.E('rend = Ipend/(max(Ipkseed,0.01))')
    w.P('前三项要求副边周期首末电流相等，接着三项要求整流平均电流等于负载平均电流，最后一项要求钳位原边电流在下一次开通之前已归零。这是六变量、七残差的有界非线性最小二乘问题，冗余物理约束也用于验收。')
    w.E('min (Robj^T·Robj/2)')
    w.P('当前内核调用 SciPy least_squares，使用默认 trf 方法和二点差分 Jacobian。归一化副边初值范围为 0–30，非反馈电压与参考之比为 0.05–5，占空比为 0.005–0.9；xtol、ftol、gtol 均为 2×10⁻¹⁰，差分相对步长为 2×10⁻⁵，max_nfev=180。达到优化器停止条件之后，还要求七项归一化残差的最大绝对值不超过 2×10⁻⁵，并检查二极管与能量一致性。')
    w.P('边界值是求解域，不代表“最大允许输出电压已被证明”。如果解落到边界、角点不收敛或不支持，必须保留失败原因，不能用匝比参考值填补空缺。')

    w.H('X004 每一次接受更新的实际记录',new_page=True)
    w.P(f'本次 SciPy {data["scipy_version"]} 记录到 {focus["solver"]["accepted_steps"]} 次接受更新，nfev={focus["solver"]["nfev"]}，包括差分试探在内共 {focus["solver"]["residual_calls"]} 次残差评价。下表第 0 行是初猜，后续列出全部接受更新；差分试探不是新的接受步。其他环境的迭代步数可能不同，最终平衡与结果才是主要核对对象。')
    iteration_rows=[dict(focus['initial'],step=0),*focus['accepted']]
    w.T(['步','D','OUT2 / V','OUT3 / V','I01 / A','I02 / A','I03 / A','最大残差'],[
        (r['step'],f'{r["duty"]:.6f}',f'{r["output_port_V"][1]:.6f}',f'{r["output_port_V"][2]:.6f}',
         *[f'{v:.4g}' for v in r['initial_secondary_A']],f'{r["max_abs_residual"]:.3g}') for r in iteration_rows
    ],[.35,.78,.98,.98,.94,.94,.94,1.19],small=True)
    w.P('目标是减小七项残差的平方和，最大单项残差不保证每一步都严格下降。最终 I02 与 I03 只有约 10⁻¹¹ A、10⁻⁹ A，物理上可按零理解；下表和图仍保留求解得到的残差，不把它们人为清零来伪造收敛。')
    w.F('x004_convergence.png','X004 接受更新的收敛记录  第 0 点为初猜')
    w.T(['最终量','求解值'],[
        ('占空比与开通时间',f'{final["duty"]:.9f}  /  {final["duty"]*4:.9f} μs'),
        ('端口 OUT1 / OUT2 / OUT3',' / '.join(f'{v:.9f} V' for v in final['output_port_V'])),
        ('电容端 OUT1 / OUT2 / OUT3',' / '.join(f'{v:.9f} V' for v in final['output_cap_V'])),
        ('起始副边电流',' / '.join(f'{v:.9g} A' for v in final['initial_secondary_A'])),
        ('最大归一化残差',f'{max(abs(v) for v in final["normalized_residual"]):.9g}'),
    ],[2.1,5.0])

    w.H('一个周期内六段导通状态怎样衔接',new_page=True)
    w.P('每次二极管导通集合变化都新建一段。下表给出段末电流；第一段从原边 0 A、S1 约 0.880354 A、S2/S3 约 0 A 开始，后一段的起始电流继承前一段末值。P钳表示原边钳位支路；电流次序始终为 P、S1、S2、S3。')
    segments=final['segments']
    def active_label(seg):
        return '+'.join(('P' if seg['on'] else 'P钳') if j==0 else f'S{j}' for j in seg['active'])
    w.T(['段','开始 / μs','结束 / μs','导通集合','Ip末 / A','I1末 / A','I2末 / A','I3末 / A'],[
        (j+1,f'{s["start_s"]*1e6:.6f}',f'{s["end_s"]*1e6:.6f}',active_label(s),
         *[f'{v:.6f}' for v in s['current_end_A']]) for j,s in enumerate(segments)
    ],[.3,.88,.88,1.28,.94,.94,.94,.94],small=True)
    w.P('最初约 4.03 ns 内 S1 尚在换流，随后只有原边电流上升。关断后约 46.97 ns 内，P 钳位与三路副边同时参与换流。S2 在约 1.884915 μs 退出，S3 在约 2.114251 μs 退出，S1 一直保持到周期末并在下一次开通时换流。因此主路为连续续流，而轻载非反馈路可以只出现很窄的脉冲。')
    w.F('x004_current.png','X004 实际分段 RL 解  虚线为 MOS 关断时刻  原边 OFF 电流属于钳位回路')
    w.P('该图直接取段内指数解，不将小电流支路按功率比例缩放。微秒横轴下很短的换流区间不易看清，应结合上表的事件时刻阅读；图上的抽样点不参与下文的电荷平衡验收。')

    w.H('逐段相加检查电荷 电流及能量')
    w.T(['段','OUT1 电荷 / μC','OUT2 电荷 / μC','OUT3 电荷 / μC'],[
        (j+1,*[f'{v*1e6:.9f}' for v in s['charge_C'][1:]]) for j,s in enumerate(segments)
    ],[.5,2.2,2.2,2.2])
    w.E('Idavgj = Qj/Ts = Iloadj')
    w.T(['输出','总电荷 / μC','整流平均 / A','负载平均 / A','实际功耗 / W'],[
        (f'OUT{j+1}',f'{final["output_charge_C"][j]*1e6:.9f}',
         f'{final["average_rectifier_A"][j]:.9f}',f'{final["average_load_A"][j]:.9f}',
         f'{final["output_power_W"][j]:.9f}') for j in range(3)
    ],[.6,1.55,1.65,1.65,1.65])
    w.P('例如 OUT2 每周期得到约 0.019871762 μC，除以 4 μs 得 0.004967941 A；13.562505 V 除以 2730.005556 Ω 得到同样的负载电流。若整流平均大于负载平均，电容会继续充电，当前猜的输出电压就还不是稳态。')
    w.T(['残差项目','OUT1','OUT2','OUT3'],[
        ('周期首末电流差 / A',*[f'{v:.3g}' for v in final['periodic_residual_A']]),
        ('整流与负载平均差 / A',*[f'{v:.3g}' for v in final['charge_residual_A']]),
        ('归一化周期残差',*[f'{v:.3g}' for v in final['normalized_residual'][:3]]),
        ('归一化电荷残差',*[f'{v:.3g}' for v in final['normalized_residual'][3:6]]),
    ],[2.3,1.6,1.6,1.6])
    w.P(f'第七项原边期末归零残差为 {final["normalized_residual"][6]:.3g}。输入净取电只使用原边 ON 电荷，钳位返回 Vin 的 OFF 回流不再次计入净输入电流。')
    w.E('Pin = Vin·Qon/Ts ; Pclamp = Vclamp·Qclamp/Ts')
    w.E('Ebal = Pin-Σ_(j=1)^3 Pactualj-PlossRL')
    names={'winding_dcr':'绕组 DCR','rectifiers':'三路整流管','output_blocking':'三路输出防反管',
           'input_blocking':'输入防反管','mos_conduction':'MOS 导通','sense':'采样电阻','clamp':'理想钳位吸收'}
    w.T(['RL 模型损耗项目','功率 / W'],[(names[k],f'{v:.9f}') for k,v in final['rl_losses_W'].items()], [4.3,2.8])
    w.P(f'输入功率 {final["input_power_W"]:.9f} W，三路实际输出合计 {sum(final["output_power_W"]):.9f} W，已建模 RL 损耗合计 {sum(final["rl_losses_W"].values()):.9f} W，功率不平衡约 {final["energy_residual_W"]:.3g} W。此检查允许误差为 max(0.001 W,0.2%×Pin)。')
    w.P('这只是周期 RL 电路的能量账，不是软件最终效率的完整损耗账。MOS 开关损耗、磁芯损耗、电容 ESR 损耗和其他后处理项不在这个平衡式内，不能拿这里的功率平衡误差当成最终效率的精度。')

    w.H('保持同一硬件计算全部十六个角点',new_page=True)
    w.P('先以 Vinmin 和各路最大功耗确定硬件，再冻结磁芯、整数匝数、线径、股数、MLT 与几何 DCR。三路各取轻重两档形成 8 组电阻，再与 20/30 V 组合得到 16 点。不重选磁件，也不为每个点重新整定补偿器。')
    w.T(['角点','Vin / V','P1 / W','P2 / W','P3 / W','D','OUT2 / V','OUT3 / V'],[
        (c['id'],f'{c["V_in"]:g}',*[f'{v:g}' for v in c['powers']],f'{c["D"]:.6f}',
         f'{c["voltages"][1]:.6f}',f'{c["voltages"][2]:.6f}') for c in cases
    ],[.68,.68,.64,.64,.64,.96,1.43,1.43])
    w.P('表内 P1/P2/P3 是换算负载电阻的设置值。OUT1 在所有点均为理想反馈端口 30 V；各路实际功率需按求出的电压重新计算。接近相等的数值有时只差浮点末位，不应解释成可测的输入调整差异。')
    w.P('OUT2 最大值来自 X004：主路重载、OUT2 轻载、OUT3 也轻载。它不是“另外两路都重载”。这说明最坏组合必须通过扫描求出，不能按直觉指定。16 点只是端点观察，不能证明连续输入与负载空间内不存在更大极值。')

    w.H('分别计算包络和纯交叉调整率')
    w.P('先把两个不同问题分开。全包络允许 Vin、本路负载和其他路负载一起改变；纯交叉调整率则固定 Vin 和本路电阻，仅比较其他路轻重载组合。两者都用匝比及固定压降得到的参考电压作分母。')
    w.E('Senv = 100·(Vmax-Vmin)/Vref')
    w.P('纯交叉按固定 Vin 和固定本路电阻分组，每组求最大电压减最小电压，除以本路参考，再取各组结果的最大值。注意“固定本路电阻”不等于固定本路实际功率。')
    group_rows=[]
    for rail in (1,2):
        groups={}
        for c in cases:groups.setdefault((c['V_in'],c['powers'][rail]),[]).append(c['voltages'][rail])
        for (vin,power),v in sorted(groups.items()):
            group_rows.append((f'OUT{rail+1}',f'{vin:g}',f'{power:g}',f'{min(v):.6f}',f'{max(v):.6f}',f'{100*(max(v)-min(v))/refs[rail]:.6f}'))
    w.T(['输出','Vin / V','本路设置 / W','组内最小 / V','组内最大 / V','组跨度 / %'],group_rows,[.65,.65,1.25,1.55,1.55,1.45])
    w.E('Scross = 100·(13.562505-12.288159)/11.683333 ≈ 10.9074')
    w.P('上式是 OUT2 在 20 V、本路固定轻载电阻时的最大组跨度。若把所有 16 点的最小值 11.748649 V 也取进来，就得到全包络跨度 15.5252%，而不是纯交叉调整率。百分数计算使用未舍入值，显示代入式可能有末位差异。')
    w.T(['输出','全部角点范围 / V','纯交叉 / %','全包络 / %','相对参考偏差 / %'],[
        (f'OUT{j+1}',f'{s["V_min"]:.6f}–{s["V_max"]:.6f}',f'{s["cross_only_pct"]:.6f}',
         f'{s["span_pct"]:.6f}',f'{s["deviation_min_pct"]:+.4f} 至 {s["deviation_max_pct"]:+.4f}')
        for j,s in enumerate(summary)
    ],[.65,2.05,1.25,1.25,1.9])
    w.P('OUT3 的纯交叉跨度为 5.897786%，全包络为 8.287491%。OUT1 显示零是主反馈理想约束的结果，不代表真实产品零误差。电压范围为直流稳态值，不包含开关纹波、负载突变过冲或短路保护。')

    w.H('在软件中复现并判断结果是否可信')
    w.P('打开 examples/3_OUTPUT_CROSS_REGULATION.json，确认固定频率 FLYBACK、SSR、OUT1 主反馈和启用耦合矩阵。检查 6/12/5/2 匝、各对 k=0.995、20–30 V 输入，以及三路轻重载设置 3–30、0.05–0.5、0.95–9.5 W。在“拓扑”的“交叉调整率与电压范围”中扫描最小/最大负载组合，再查看两端工况报告。此路径不需要启动 LTspice。')
    w.P('源码仓库中的复算证据为 docs/examples/cross_regulation_worked_example.json；生成入口为 docs/examples/collect_cross_regulation_example.py。它调用 cross_regulation.scan_cross_regulation、coupled_flyback._periodic_solution 和 _Circuit，记录优化器实际接受步，不另写一套电流求解公式。图表和本章表格都读取这份数据；记录中含源配置与关键源码 SHA256，便于发现版本变化。')
    w.P('本练习不包含真实控制器动态限流与跳周期、输出电容的大纹波反馈、Coss/Cj 完整换流谐振、反向恢复、布线寄生、温度变化和磁芯非线性。导入二极管 If–Vf 曲线当前主要用于损耗后处理，本练习的耦合换流仍用固定 0.7 V，不声称已经做非线性二极管共同迭代。')
    w.P('0 W 真空载没有泄放与间歇控制模型，当前标记为未计算，不用微小功率替代。任何角点失败都应显示原因，剩余成功点只能称为不完整观察范围。小残差表示这套假设下的数学平衡，是否满足产品指标仍需逐路看电压偏差，并与同节点、同负载的仿真及实测复核。')
    return w


def mark(doc,name):
    p=doc.add_paragraph();p.paragraph_format.space_after=Pt(0)
    p.paragraph_format.space_before=Pt(0);p.paragraph_format.line_spacing=Pt(1)
    b=OxmlElement('w:bookmarkStart');b.set(qn('w:name'),name)
    b.set(qn('w:id'),'9100' if name==START else '9101');p._p.append(b)
    e=OxmlElement('w:bookmarkEnd');e.set(qn('w:id'),b.get(qn('w:id')));p._p.append(e)
    return p


def remove_previous(doc):
    body=doc.element.body;active=False
    for node in list(body):
        names=[x.get(qn('w:name')) for x in node.iter(qn('w:bookmarkStart'))]
        if START in names:active=True
        if active:body.remove(node)
        if END in names:break


def update_document(doc,kind,data=None):
    remove_previous(doc)
    anchor=next(p for p in doc.paragraphs if p.text.startswith('附录 A' if kind=='reference' else '17  '))._p
    before=set(doc.element.body)
    mark(doc,START);writer=add_worked_example(doc,kind,data);mark(doc,END)
    new_nodes=[e for e in doc.element.body if e not in before and e.tag!=qn('w:sectPr')]
    for node in new_nodes:anchor.addprevious(node)
    # Cross links live at the point where the reader first meets the model.
    for p in doc.paragraphs:
        if kind=='reference' and p.text.startswith('小信号不复用旧功率比例 Bode。'):
            p.text='小信号在已收敛周期解附近微扰，保留副边初值与各路电容状态；详见第 18 章。完整轻重载扫描、节点与恒阻负载定义、逐段换流、电荷和周期迭代、16 个角点及两类调整率，见第 19 章完整算例。'
        if kind=='reference' and p.text.startswith('b 为唯一的 SSR 主反馈路'):
            p.text='b 为唯一 SSR 主反馈路，或 PSR 标称采样基准路。实际整数 Np 与各 Ns 决定匝比；本节上式仅为不含压降的理想关系。当前固定频率 SSR 的端口参考电压须先加主路整流与防反压降、按副边匝比换算，再扣本路两项压降；负载位于防反管后，主反馈取样在防反管前。完整代入与非反馈电压求解见第 19 章；参考电压不是另一独立稳压目标。'
        if kind=='reference' and p.text.startswith('本文件对应 2026-10-21'):
            p.text='本文件原有章节保留既有模型说明；2026-11-02 新增第 19 章三路反激交叉调整率完整求解算例，并按当前源码明确节点、恒阻负载和收敛定义。新增算例不改变计算内核和原有默认参数。帮助菜单继续打开本文，完整程序目录须保留 _internal。'
    if kind=='reference':
        for p in doc.paragraphs:
            if p.style.name=='Subtitle':
                p.text='软件计算内核详解  三路反激交叉调整率算例增补  2026-11-02';break
        nav=doc.tables[0]
        if not any(r.cells[0].text=='19' for r in nav.rows):
            row=deepcopy(nav.rows[-1]._tr);nav._tbl.append(row)
        row=next(r for r in nav.rows if r.cells[0].text=='19') if any(r.cells[0].text=='19' for r in nav.rows) else nav.rows[-1]
        for cell,text in zip(row.cells,['19','三路反激交叉调整率完整求解算例','cross_regulation / coupled_flyback']):
            cell.paragraphs[0].clear();_font(cell.paragraphs[0].add_run(text),10)
    else:
        for t in doc.tables:
            for row in t.rows:
                if row.cells[0].text=='16  交叉调整率':
                    row.cells[1].text='先读原 33 W 案例，再用 40 W 完整练习复算方程、迭代与 16 点电压包络'
        for p in doc.paragraphs:
            if p.text.startswith('原公式说明文档 SHA256'):
                p.text=p.text.replace('原公式说明文档 SHA256','2026-10-23 初版保留记录  当时公式说明 SHA256')
    return writer


def main():
    parser=argparse.ArgumentParser();parser.add_argument('--only',choices=list(TARGETS))
    parser.add_argument('--figures-only',action='store_true');args=parser.parse_args()
    data=load_data()
    if args.figures_only:
        make_figures(data);return
    for kind,path in TARGETS.items():
        if args.only and args.only!=kind:continue
        backup=QA/'before'/path.name;backup.parent.mkdir(parents=True,exist_ok=True)
        if not backup.exists():backup.write_bytes(path.read_bytes())
        doc=Document(path);writer=update_document(doc,kind,data);doc.save(path)
        print(json.dumps(dict(file=str(path),added_equations=writer.equations,
            total_math=len(doc.element.xpath('.//m:oMath')),tables=len(doc.tables),figures=len(doc.inline_shapes)),ensure_ascii=False))


if __name__=='__main__':main()
