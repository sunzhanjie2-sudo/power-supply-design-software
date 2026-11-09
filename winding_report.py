"""Shared winding-window reference and Word report, using native equations."""
from docx_layout import paragraph,table,equation,section,figure
from winding_layout import (validate_winding_config,transformer_windings,
                            assess_winding_window,draw_winding_cross_section)


def _physical_positions(indices):
    """Compact a logical winding's layer indices; the physical table is exact."""
    values=list(indices)
    if not values:
        return '—'
    runs=[]
    first=last=values[0]
    for value in values[1:]:
        if value==last+1:
            last=value
        else:
            runs.append(str(first) if first==last else f'{first}–{last}')
            first=last=value
    runs.append(str(first) if first==last else f'{first}–{last}')
    return '、'.join(runs[:12])+('…（共 '+str(len(values))+' 层）' if len(runs)>12 else '')


def add_winding_snapshot(doc,parameters,result):
    """Do not silently invent bobbin dimensions for legacy specifications."""
    rows=transformer_windings(result)
    if not rows:
        return None
    assessment=assess_winding_window(rows,parameters.get('winding_config'))
    if not assessment['configured']:
        return None
    from report_docx import _chart
    section(doc,'5.2  变压器可绕制几何评估')
    cfg=assessment['config']
    manual=bool(cfg.get('layer_plan'))
    mm=lambda x:f'{x*1e3:.4g} mm'
    paragraph(doc,'骨架单侧净窗口的轴向 × 径向等比例截面。采用当前实际匝数、裸铜线径和电气总股数，按指定绕组顺序分层；每束多股线只画一个等效截面，支持疏绕、密绕靠左与密绕靠右。图中骨架挡墙仅为窗口外的示意，不占输入净窗口，也不代表实测壁厚。')
    table(doc,['窗口 / 工艺输入','数值','窗口 / 工艺输入','数值'],[
        ('净窗口宽',mm(cfg['window_width']),'净窗口高',mm(cfg['window_height'])),
        ('左右留边（每侧）',mm(cfg['margin_x']),'上下留边（每侧）',mm(cfg['margin_y'])),
        ('单股含漆外径增量',mm(cfg['diameter_allowance']),'束 / 匝间隙',mm(cfg['wire_gap'])),
        ('层间绝缘',mm(cfg['layer_insulation']),'绕组间绝缘',mm(cfg['interwinding_insulation'])),
        ('当前方案','几何可放下' if assessment['fits'] else '超出窗口','总叠高 / 余量',
         mm(assessment['required_height'])+' / '+mm(assessment['height_margin']))],[2.,1.55,2.,1.55])
    wire_rows=[]
    layout_rows=[]
    styles={'sparse':'疏绕','dense_left':'密绕靠左','dense_right':'密绕靠右'}
    for r in assessment['windings']:
        legacy=r['layout_model']=='legacy_rectangular'
        kind='旧矩形束' if legacy else ('利兹线' if r['wire_type']=='litz' else '圆铜线')
        actual=bool(cfg['overrides'].get(r['id'],{}).get('bundle_diameter',0))
        diameter='—（旧方案）' if legacy else f"{r['bundle_diameter']*1e3:.4g}\n"+('指定外径' if actual else f"估算 k={r['packing_factor']:.4g}" if r['strands_per_bundle']>1 else '单股含漆外径')
        wire_rows.append((r['id'],f"{int(r['turns'])} × {int(r['strands'])} × {int(r.get('parallel_wires',1))}",
            f"{kind}\n{r['parallel_bundles']} × {r['strands_per_bundle']}",
            f"{r['bare_diameter']*1e3:.4g} / {r['outer_diameter']*1e3:.4g}",
            diameter,f"{r['flatten_ratio']:.4g}",
            f"{r['bundle_width']*1e3:.4g} × {r['bundle_height']*1e3:.4g}"))
        if manual:
            layout_rows.append((r['id'],str(r['layers']),
                _physical_positions(r['physical_layer_indices']),
                f"{r['turns_per_layer']} / {r['capacity']}",
                f"{r['buildup']*1e3:.4g}",f"{r['stack_span']*1e3:.4g}"))
        else:
            layout_rows.append((r['id'],styles[r['winding_style']],
                f"{r['turns_per_layer']} / {r['capacity']}",str(r['layers']),
                f"{r['turn_width']*1e3:.4g}",f"{r['buildup']*1e3:.4g}"))
    table(doc,['绕组','匝数 × 股/根\n× 并绕根数','线材\n总束数 × 股/束','单股裸径 /\n含漆外径 mm',
               '整束原外径 mm\n来源 / 填充系数','压扁\n倍数','单束宽 × 高\nmm'],
          wire_rows,[.55,.8,1.15,1.35,1.25,.6,1.4])
    if manual:
        table(doc,['绕组','层数','所在物理层','每层上限 /\n窗口容量',
                   '本绕组占厚*\nmm','首末层跨高\nmm'],
              layout_rows,[.55,.55,1.65,1.45,1.45,1.45])
        paragraph(doc,f"采用手动物理层序，共 {assessment['total_layer_count']} 层。每层上限是配置允许值，非各层实际匝数，实际值见逐物理层表。*本绕组占厚仅包含其线束层高及物理相邻同绕组层间绝缘，不含中间其它绕组；首末层跨高才包含其中穿插的线层与绝缘，不能把各绕组跨高相加求总叠高。物理层号按骨架向外连续编号，详表保留全部层序。",True)
        physical_rows=[]
        previous=None
        for layer in assessment['physical_layers']:
            insulation_kind='无（首层）' if previous is None else ('同绕组层间' if previous==layer['winding_id'] else '异绕组间')
            physical_rows.append((str(layer['layer_index']),layer['winding_id'],str(layer['turns']),
                styles[layer['winding_style']],f"{layer['insulation_before']*1e3:.4g}\n{insulation_kind}",
                f"{layer['height']*1e3:.4g}"))
            previous=layer['winding_id']
        table(doc,['物理层号','绕组','本层匝数','本层绕法','前置绝缘\nmm / 类型','本层线束高\nmm'],
              physical_rows,[.7,.7,.8,1.3,1.8,1.8])
        paragraph(doc,'同一电气绕组可出现在第 1、3 等不同物理层，其总匝数只按分配到各层的匝数求和。相邻物理层换绕组时每次计入绕组间绝缘，例如 P–OUT1–P 有两处界面；不自动评估跨线、分段引线、实际连接或漏感改善。',True)
    else:
        table(doc,['绕组','绕法','每层匝数 /\n窗口容量','层数','每匝总宽\nmm','径向叠厚\nmm'],
              layout_rows,[.55,1.25,1.5,.6,1.6,1.6])
    paragraph(doc,'单根线股数 × 线圈并绕根数 = 每匝总铜股数；并绕 2 根相同线绕 6 匝仍是 6 匝，截面为 12 根线。每根线内分束仅重新组合其原有股数，不增加铜面积，例如并绕根数为 1 时，3 束 × 20 股要求电气总股数为 60。单股铜线保持圆形；利兹线默认按宽 ×1.5、高 ÷1.5 的等截面积假设压扁，填充系数默认 0.75 为可编辑假设，优先采用实测整束原外径。压扁后束高若小于单股含漆线径则拒绝配置；外径面积下界只属必要条件，不保证真实堆积可行。疏绕可一键均匀生成，逐匝位置可再手调；每层匝数不超过窗口容量。',True)
    positions=cfg.get('turn_positions',{})
    if any(positions.values()):
        by_id={s['id']:s for s in assessment.get('cross_sections',[])}
        moved=[]
        for sid,entries in positions.items():
            for key,center in entries.items():
                point=by_id.get(sid+':'+key)
                moved.append((sid,key,f'{center*1e3:.6g}',
                    f"{(point['y']+point['height']/2)*1e3:.6g}" if point else '已失效',
                    '待修正' if not point or point.get('conflict') else '已应用'))
        table(doc,['物理段','本层匝号 : 束号','中心 X / mm','中心 Y / mm','位置状态'],moved,[1.,1.6,1.4,1.4,1.7])
        paragraph(doc,'逐匝位置只覆盖轴向中心 X，径向 Y 由所属物理层决定。报告截面与建模导出采用同一坐标；红色位置及已失效记录须修正。',True)
    figure(doc,_chart((7.1,3.9),lambda fig:draw_winding_cross_section(fig.subplots(),assessment)),
           '图 5-3  指定层绕方案的等比例截面；圆 / 椭圆为整束等效外轮廓，不逐根绘制束内铜丝')
    paragraph(doc,f"裸铜面积 / 净窗口面积为 {assessment['copper_fill']*100:.1f}%。当前方案的宽度或叠高超限即不能按此排布放下；低面积占比也可能绕不下，不代表其他绕法均不可行。",True)
    for note in assessment['warnings']:
        paragraph(doc,note,True)
    paragraph(doc,'该截面不自动修改几何铜损、绕组 DCR、漏感或 kij；仍需复核端部引线、跨线、绞线鼓包、骨架圆角、材料公差及绝缘工艺。几何可放下不等于满足绝缘安规或可量产。',True)
    return assessment


def add_winding_reference(doc):
    section(doc,'17  变压器可绕制评估与界面响应')
    paragraph(doc,'④磁件页新增“可绕制评估”子页，仅隔离拓扑显示。输入骨架单侧净绕线窗口的轴向宽 W 和径向高 H（界面 mm、内部 m），再填写每侧留边、含漆外径增量、层间与绕组间绝缘、线束间隙。窗口尺寸不从磁芯 Wa 推断：不同骨架结构可能具有相同 Wa，轴向排匝与径向叠厚仍不同。')
    doc.add_heading('17.1  匝数、分束与等效线径',2)
    paragraph(doc,'原边 P、OUT1–OUT6 与 MP6005 的 AUX 从磁件计算结果读取已解析的匝数、裸铜直径及电气总股数 n，不使用输入中 0=自动 的占位值。单股含漆外径为 0 时采用裸径加全局增量，也可逐绕组指定实测值。默认余量只是可编辑初值，不是材料或绝缘等级推荐。')
    equation(doc,'d_o = d_c + Δd')
    equation(doc,'W_u = W−2m_x；H_u = H−2m_y')
    paragraph(doc,'线圈并绕数 b 是相同完整导线的根数，缺省 1；nstrand 是每根线股数，每匝总铜股数 n=b·nstrand。6 匝、b=2 时截面为 12 根整线，电气仍为 6 匝。每根线内分束数只重新分组，须整除 nstrand；总束数 B=b×分束数。b=1 时 3 束×20 股对应总股数 60，不重复增加铜。每束画一个等效截面，同匝完整束组不跨层拆分。')
    equation(doc,'n_b = n/B')
    paragraph(doc,'每束多股线的未压扁等效外径 D_b 按下式估算；k_pack 为束内含漆单线面积占比，默认 0.75 只是可编辑的几何假设，不是厂商通用值。指定实测整束原外径时直接采用该值，不再用填充系数推算。每束只有一股时直接取 D_b=d_o，不额外放大。')
    equation(doc,'D_b = d_o·√(n_b/k_pack)')
    paragraph(doc,'默认线材自动识别：每束多于一股时按利兹线，每束一股时为普通圆铜线；用户可把多股束改为不压扁的普通圆线束。实际非利兹并绕线不应保留自动识别。利兹线压扁倍数 a_f 默认 1.5，宽度增加而高度按等面积下降；普通圆铜线强制 a_f=1。实测整束外径是压扁前外径，并非压扁后的宽。')
    equation(doc,'b_w = a_f·D_b；b_h = D_b/a_f')
    equation(doc,'π·b_w·b_h/4 = π·D_b²/4')
    equation(doc,'D_b≥d_o·√n_b；b_h≥d_o')
    paragraph(doc,'整束外径必须不小于全部含漆单线面积对应的等效圆直径，压扁后束高不能小于单股含漆线径，否则拒绝此配置。这两个检查只是必要条件，并不充分保证真实圆线堆积、绞合或压制工艺可行。')
    paragraph(doc,'压扁式仅为保持整束包络截面积的工程预估，不包含压制力、绞合节距、护套、槽内接触或真实形变。它不改变电气铜截面积和损耗。不同线材应以实测外形校核；单股铜线即使选择利兹线也不压扁。')
    doc.add_heading('17.2  完整匝束、自动排层与窗口判据',2)
    paragraph(doc,'g 为同层相邻束与相邻完整匝组之间的最小间隙；它不再用于等效束内逐根排丝。每匝总宽 w_t 先包含 B 束，再计算窗口最大容量 q_max。手动每层匝数为 0 时采用最大容量；非 0 时须为不超过容量的正整数。')
    equation(doc,'w_t = B·b_w+(B−1)·g')
    equation(doc,'q_max = floor((W_u+g)/(w_t+g))')
    equation(doc,'1≤q≤q_max')
    paragraph(doc,'自动模式按绕组顺序连续分组，不穿插其它绕组；以下层数及分组叠厚式仅用于这种连续排层。手动物理层序使用第 17.4 节逐层算法。')
    equation(doc,'l = ceil(N/q)')
    equation(doc,'h_j = l·b_h+(l−1)·t_l')
    paragraph(doc,'q 为实际采用的每层完整匝数，N 为该绕组总匝数；floor 向下取整，ceil 向上取整。q_max=0 表示完整匝组超宽，直接判不可放下；此时不以 N/0 求层数，只画一匝一层的超宽示意，不能解释为有效绕法。t_l 为层间绝缘，每一绕组内部仅在相邻层间计入。')
    equation(doc,'H_req = 2m_y+Σ h_j+(n_w−1)·t_w')
    equation(doc,'ΔH = H−H_req')
    equation(doc,'k_Cu = (Σ(N_j·n_j·π·d_c,j²/4))/(W·H)')
    paragraph(doc,'n_w 为绕组数量，t_w 为相邻绕组之间的绝缘厚度。顺序可用上移 / 下移按钮调整。所有绕组 q_max≥1 且 ΔH≥0 才表示指定层绕方案几何可放下；裸铜面积占比按 N×n 统计，分束与压扁不重复增加或减少铜面积。低面积占比不保证排层可放下。')
    doc.add_heading('17.3  疏绕、密绕与截面显示',2)
    paragraph(doc,'每一层实际排 s 匝（末层可以较少），完整匝组的占宽为 w_occ。疏绕将各匝组均匀分布到有效窗口两端；同一匝内的 B 束仍相邻，不把它们拆散到全窗。密绕按最小间距靠左或靠右排列，末层同样使用所选对齐方式。')
    equation(doc,'w_occ = s·w_t+(s−1)·g')
    equation(doc,'p_x = (W_u−w_t)/(s−1)')
    paragraph(doc,'上一式仅适用于疏绕且 s>1，p_x 是相邻匝组起点间距；只有一匝时置于有效窗口中央。密绕时 p_x=w_t+g，首匝起点为下面的左靠或右靠位置。')
    equation(doc,'x_0 = m_x；x_0 = m_x+W_u−w_occ')
    paragraph(doc,'图的横纵轴使用同一毫米比例，圆 / 椭圆表示整束等效外轮廓，不将包络内部涂成实心裸铜。骨架挡墙仅画在输入净窗口以外，尺寸为示意而非实际壁厚；超限部分保留并标红。等效束截面超过 12000 个或总物理层数超过 256 时简化绘图：手动保留逐层带状顺序，自动显示绕组整体包络，不画单束椭圆。数值判断仍覆盖全部匝数、层数与电气总股数。')
    paragraph(doc,'兼容旧配置：若某绕组仅保存显式非零 strand_columns、没有新的线束字段，则沿用旧矩形束宽高；界面与报告明确标为旧方案，不偷偷改变旧评估。切换新模型需清除旧列数；新字段不能与非零旧列数混用。旧方案不再逐根绘制束内铜丝，仅显示每匝矩形轮廓。')
    paragraph(doc,'点选某匝中的线束可左右拖动，或用方向键按设定步长移动（Shift×10、Alt÷10、Ctrl+Z 撤销）。一键均匀排布保留交错层序，之后可微调。首次移动固定物理段 ID；turn_positions 按本层匝号:束号保存米制轴向中心 X，Y 由层序决定。重叠、净隙不足、越界或旧位置失效均提示。位置编辑不触发电气求解，报告与建模导出复用坐标。')
    paragraph(doc,'适用边界：不含引线与跨线的走线、绕组分段的端部连接、绞线膨胀、骨架圆角、槽内实际形变、工艺公差与安规认证。绝缘按用户输入的厚度占位，不自动执行爬电、电气间隙或耐压合规校核。更改几何排布不会回写铜损、DCR、漏感或耦合矩阵；需要用户按工艺或实测另行更新电气参数。')
    doc.add_heading('17.4  手动物理层序与交错绕制',2)
    paragraph(doc,'勾选手动物理层序后，每一行对应一层，按骨架向外编号；同一电气绕组可以分配到第 1、3 等不连续层。例如 P 的 6 匝可拆成第 1 层 3 匝、第 3 层 3 匝，中间穿插 OUT1。这里仍是一个 6 匝电气绕组，不能把每层当成新增绕组或重复计算铜面积。可新增、删除、拆层及上下移动，并从自动排层重新生成草案。')
    paragraph(doc,'全部当前有效绕组（包括存在时的 AUX）必须在层序中出现，每绕组各层匝数之和必须等于磁件结果；每层为正整数匝，不得超过窗口容量，也不能超过该绕组非零的每层匝数设置。手动最多 1000 层，未分配完或分配过量均报错，不静默补匝或截断。各层可覆盖默认疏密绕方式，省略则继承所属绕组设置。')
    equation(doc,'N_j = Σ N_layer')
    paragraph(doc,'上一求和仅遍历分配给绕组 j 的物理层。第 ℓ 层线束高为 h_ℓ，其前置绝缘为 t_ℓ：首层 t_1=0；相邻两层属于同一绕组时取层间绝缘 t_l，属于不同绕组时取绕组间绝缘 t_w。P–OUT1–P 会产生两处异绕组界面，不因 P 再次出现而漏计第二处。')
    equation(doc,'y_first = m_y')
    equation(doc,'y_layer = y_prev+h_prev+t_layer')
    equation(doc,'H_req = 2m_y+Σ h_layer+Σ t_layer')
    paragraph(doc,'y_ℓ 为物理层下沿位置，递推式用于第 2 层起。总叠高按每个物理层及其前置绝缘各计一次，不再用“不同绕组数量减一”替代实际界面数。高度余量仍为 ΔH=H−H_req。绕组汇总分别给出其实际物理层号、本绕组占厚及首末层跨高；后者包括穿插的其它线层，不可相加作为总高。')
    paragraph(doc,'交错层序只控制几何排布，不生成跨线、端部引线或电气连接图；仍须确认同一绕组各段串联方向、绝缘工艺与实际可绕制性。它不会自动降低漏感、修改两两 kij / DCR、重算铜损或保证耦合改善；这些电气量仍需实测或独立场仿真确认。')
    doc.add_heading('17.5  保存、报告与后台计算',2)
    paragraph(doc,'配置 JSON 的 winding_config 保存 SI 窗口尺寸、绕组顺序、线材外形、分束、压扁与绕法；layer_plan 保存物理层序，空列表表示自动，turn_positions 保存逐匝轴向中心。电气并绕数使用 parallel_wires_p/s，各路输出独立保存 parallel_wires_s，旧工程缺省 1。关闭手动模式时有效层序为空，草案仅留在界面；要保存需重新启用。Word 报告包含线材与排布表、手调位置和同一截面图；未配置窗口时不输出绕制结论。')
    paragraph(doc,'耗时电气计算在后台运行，合并连续输入，只保留最新任务；过期及取消结果不发布，缓存有界。窗口尺寸和逐匝位置仅刷新局部几何，不启动耦合求解。效率曲线与扫描共用后台队列，避免抢占 CPU。')
    paragraph(doc,'Tk 控件与绘图留在主线程，后台只返回数值快照；缩放不重算，取消不阻塞。后台化改善响应，不保证求解更快，图形发布仍有开销。')
    paragraph(doc,'结构参考：Texas Instruments SLUP125，Magnetics Design 3 – Windings，讨论骨架、圆线空隙、绝缘及端接对窗口使用的影响；这里采用上述明确的等效束几何算法，并非复现某一厂商完整绕制工具。1.5 与 0.75 均为可配置几何假设，不是该文献给出的通用材料常数。')
    paragraph(doc,'https://www.ti.com/lit/ml/slup125/slup125.pdf',True)
