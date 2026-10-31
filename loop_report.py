"""Editable native-math reference for the experimental multi-output loop."""
from docx_layout import section, paragraph, equation, table


def add_capacitor_bank_snapshot(doc,model):
    if not model.get('esr_included'):return
    rows=[]
    for bank in model['capacitor_banks']:
        branch=[f"{c['C']*1e6:.5g} μF / {c['ESR']*1e3:.5g} mΩ" for c in bank['branches']]
        rows.append((f'OUT{bank["output"]}',branch[0],branch[1] if len(branch)>1 else '未启用',
                     str(bank['states'])))
    paragraph(doc,f"环路已包含各电容独立 ESR 支路，共 {model['capacitor_states']} 个电容状态、{model['state_count']} 个功率级状态。")
    table(doc,['输出','电容 1 容量 / ESR','电容 2 容量 / ESR','电容状态数'],rows,[.65,2.55,2.55,1.35])
    paragraph(doc,'每颗启用电容分别建模。只有 ESR 严格为零且直接并联的理想电容才合并其共享电压状态；第二颗停用时完全退出网络。低频等效 ESR 只作为参考，不替代实际双支路网络。',True)


def add_multi_output_loop_reference(doc):
    section(doc,'18  多路输出的主反馈环路与各路响应')
    paragraph(doc,'多输出电源仍只有一个主开关调制量和一个所选主反馈量。软件没有为各副边虚构独立补偿器：⑤页的 PM、GM 与穿越频率属于主反馈回路，其他输出显示同一闭环下的参考跟踪与负载扰动响应。主反馈选择沿用左栏 OUT 设置，不额外建立第二套反馈配置。')
    doc.add_heading('理想模型与耦合模型分开处理',2)
    paragraph(doc,'未启用矩阵、或全部 kij=1 理想回退时，保留原刚性匝比、总负载及电容能量折算模型。各路参考响应按相对电压变化率推导，不能用它预测独立负载动态。尤其多路正激有独立 LC 支路，现有能量折算只是初选，不声称完整多支路动态。')
    paragraph(doc,'固定频率 SSR 反激且存在已收敛的非理想耦合周期解时，使用绕组周期核与独立并联 RC 支路联立的小信号模型。绕组周期核在固定电容端电压下精确积分 RL 换流电荷，求出平均整流电流及峰值采样的微扰导数；随后以实际 C、ESR、恒阻负载和端口电流平衡建立连续状态空间，不把两颗电容的 ESR 简单并联。没有重复运行完整直流非线性求解，也没有重新乘预设效率。')
    equation(doc,'δxnext = Ad·δxstate + Bd·δu')
    paragraph(doc,'Ad、Bd 来自同一周期事件求解器的数值微扰；归一化微扰步长分别取 2×10⁻⁵ 和 1×10⁻⁵，最大相对差异超过 3% 时拒绝输出。零电流状态使用非负方向差分；非常接近 CCM/DCM 边界时拒绝假设唯一线性模型。移除旧总电容更新项、提取平均注入电流导数后，才连接实际并联电容网络，避免容量和负载重复计入。')
    doc.add_heading('两颗并联电容分别保留容量和 ESR',2)
    equation(doc,'Z_k(s) = R_k + ', '1','s·C_k')
    equation(doc,'Z_p(s) = ','Z_1(s)·Z_2(s)','Z_1(s)+Z_2(s)')
    equation(doc,'Z_o(s) = ','Z_p(s)·R_L','Z_p(s)+R_L')
    paragraph(doc,'Zp 为两电容并联阻抗，Zo 为其与负载电阻 RL 并联后的端口阻抗。')
    paragraph(doc,'每颗有限 ESR 电容的内部储能电压独立作为状态，外部电容端电压由各支路电流、恒阻负载与额外下拉负载共同确定。两支路一般产生两个 ESR 零点和支路间附加极点，不能全频段只用总容量与一个等效 ESR。')
    equation(doc,'i_k = ','vnode − u_k','R_k')
    equation(doc,'du_k/dt = ','i_k','C_k')
    paragraph(doc,'反馈仍取所选一路防反管前的电容端，而不是任意一颗电容的内部储能电压。固定防反压降下，端口和取样节点的小信号电压增量相同。ESR 为零的直接并联电容共享一个电压状态，容量相加；并联的有限 ESR 支路仍独立保留。')
    paragraph(doc,'电压模式按斜坡幅值把控制电压扰动变为占空比扰动。峰值电流模式将导通末端采样量与控制电压相等的约束一并微分，使斜坡和电流内环进入周期矩阵。')
    equation(doc,'δD = ','δvcontrol','Vm')
    equation(doc,'vcompare = Rs·A_sense·(ip_off+slope_a·D·Ts)')
    paragraph(doc,'这里假设比较器的首次有效交点位于当前关断边沿，未建模前沿消隐、传播延迟、芯片限流或模式管理。')
    paragraph(doc,'仅绕组周期核通过双线性变换作低频连续等效，平均电流和比较器输出同步转换其直通项，再与各路实际连续 RC 网络及峰值内环约束联立。ESR 对反馈及负载瞬时电压的直通作用同时保留。它不是完整开关瞬态模型；直流与周期电流仍使用刚性电容边界，尚未将 ESR 纹波反算到原周期换流，也未加入 Coss/Cj 或 ESL。')
    doc.add_heading('统一的闭环分母',2)
    equation(doc,'T(s) = Gc(s)·Gb(s)')
    equation(doc,'Hj(s) = ','Gj(s)·Gc(s)','1 + T(s)')
    equation(doc,'Zjk(s) = Gjk(s) - ','Gj(s)·Gc(s)·Gbk(s)','1 + T(s)')
    paragraph(doc,'Gb 为主反馈路的控制到输出传递，Gj 为第 j 路的控制到输出传递，Gjk 为第 k 路负载电流到第 j 路电压的开环功率级传递。负载扰动的正方向为额外下拉电流，单位 A；额定负载仍为原固定电阻。Hj 表示主参考到该路电压；GUI 按 Vb/Vj 归一化为相对变化率，0 dB 表示相同百分比跟踪。Zjk 的单位为 Ω，即 V/A。')
    paragraph(doc,'报告的直流负载灵敏度矩阵是在正的积分补偿下保持主反馈直流电压不变的局部导数。主反馈行约为零不代表瞬态没有压降，更不代表未反馈输出独立稳压；导数也不能直接用于 1 A 等可能很大的有限负载阶跃。未启用矩阵时不编造此表。')
    doc.add_heading('扫描范围与自动整定检查',2)
    paragraph(doc,'临时低频带宽限制已停用。Bode 保留原扫描范围，不再按 fs/20、各路 ESR 零点的 1/5 截断，也不再按上述频带的一半或数值 RHP 零点的 1/5 强制降低整定目标。并联电容的低频等效串联电阻只作参考，实际传递函数采用各独立支路；解除限制不代表高频精度已验证。')
    equation(doc,'Reff = ','Σ_j(Rc,j·C_j²)','(Σ_j(C_j))²')
    paragraph(doc,'Bode 的默认扫描范围为 0.01 Hz 至开关频率十倍和 1 MHz 中的较大者，仅为数值观察范围，不是模型精度承诺。高频结果属于近似外推。增益裕度仅在扫描范围内检测，未出现 −180° 穿越时显示“扫描范围内未检出”，不称无限增益裕度。原有开关频率整定保护、RHP 带宽建议、闭环极点、内环周期矩阵谱半径与两档差分一致性检查保留；候选补偿仍须通过全部 0 dB 穿越的最小 PM 和闭环极点检查。')
    paragraph(doc,'实际电容充放电纹波超过直流电压 10%、差分不一致、绕组周期核接近 −1 极点、代数耦合近奇异或无有效周期解时，不提供该近似 Bode。快速 RC 连续极点经双线性变换靠近 −1 不作为真实 PWM 周期倍化结论；原周期谱检查仅描述恒电容端绕组核。QR、MP6005 PSR、正激及未启用矩阵的单路兼容模型不使用本次独立 RC 网络，继续采用其原有能力与限制。没有加入加权反馈、多路独立调制或后级稳压器。')
    paragraph(doc,'GUI 在同一后台数值工作线程按需计算环路，只发布当前参数对应的结果；切换主反馈、参数或输出数量会使旧结果失效。报告独立重建同源图表和灵敏度表，不依赖是否浏览过结果页。验证覆盖三路和六路、主反馈切换、周期微扰、双线性响应、独立直流重算、后台错误与取消；不构成所有控制器、所有负载角点或样机硬件验证。')
    doc.add_heading('资料与工程判断',2)
    paragraph(doc,'Texas Instruments，Multiple Output Flybacks How to Improve Cross Regulation；Analog Devices，Flyback Controller Improves Cross Regulation for Multiple Output Applications。原厂资料支持主反馈与未反馈路的区别，以及漏感、电阻、整流压降对交叉调整率的影响；本软件的电容周期更新与数值步长是工程实现假设，不是照搬原厂完整仿真模型。',True)
    # Friendly clickable labels keep two long URLs from creating an orphan
    # reference-only page while retaining exact original source targets.
    from docx.oxml import OxmlElement
    from docx.oxml.ns import qn
    from docx.opc.constants import RELATIONSHIP_TYPE
    links=paragraph(doc,'原厂网页：',True)
    for label,url in (
        ('TI 多输出反激交叉调整率  ', 'https://www.ti.com/video/5577137426001'),
        ('ADI Design Note 344', 'https://www.analog.com/en/resources/design-notes/flyback-controller-improves-cross-regulation.html')):
        link=OxmlElement('w:hyperlink')
        link.set(qn('r:id'),doc.part.relate_to(url,RELATIONSHIP_TYPE.HYPERLINK,is_external=True))
        run=OxmlElement('w:r'); props=OxmlElement('w:rPr')
        color=OxmlElement('w:color'); color.set(qn('w:val'),'1558B0'); props.append(color)
        size=OxmlElement('w:sz'); size.set(qn('w:val'),'18'); props.append(size)
        text=OxmlElement('w:t'); text.text=label
        run.extend((props,text)); link.append(run); links._p.append(link)
