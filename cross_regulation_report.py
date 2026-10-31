"""One report section reused by the Word and module-per-sheet Excel paths."""


def draw_envelope(fig, result):
    ax=fig.subplots()
    rows=[r for r in result.get('summary',[]) if not r['feedback'] and r['V_min'] is not None]
    for j,row in enumerate(rows):
        lo,hi=row['deviation_min_pct'],row['deviation_max_pct']
        ax.plot((lo,hi),(j,j),lw=5,color='#24669B',solid_capstyle='round')
        ax.scatter((lo,hi),(j,j),color='#24669B',s=24)
        ax.annotate(f'{lo:+.2f}%',(lo,j),xytext=(-4,10),textcoords='offset points',ha='right',fontsize=9)
        ax.annotate(f'{hi:+.2f}%',(hi,j),xytext=(4,-18),textcoords='offset points',ha='left',fontsize=9)
    ax.set_yticks(range(len(rows)),[f'OUT{r["id"]} · {r["V_reference"]:g} V' for r in rows])
    ax.axvline(0,color='#8F9BAB',linestyle='--',lw=1)
    ax.set(xlabel='相对匝比参考电压的偏差 / %',title='非反馈路负载角点直流电压包络'+('（不完整）' if not result.get('complete') else ''))
    if not rows:ax.text(.5,.5,'无有效的非反馈路角点结果',transform=ax.transAxes,ha='center')
    ax.margins(x=.3,y=.65);ax.grid(axis='x',alpha=.2)


def add_report(doc,p,res):
    if len(p.get('outputs',[]))<2:return
    from docx_layout import section,paragraph,table,figure,equation
    from report_docx import value,_chart
    from cross_regulation import NOTE,SOURCE,load_label
    section(doc,'1.3 多路负载范围与交叉调整率')
    data=res.get('cross_regulation')
    paragraph(doc,data.get('note',NOTE) if data else NOTE)
    if not data:
        paragraph(doc,'本报告快照尚未执行负载角点扫描。请使用双输入端点报告或先运行交叉调整率计算；不以标称电压代替扫描范围。',True)
        return
    table(doc,['输出','反馈设定或匝比参考','最小功率','最大功率'],[
        (f'OUT{r["id"]}'+(' 主反馈' if r['id']==data['feedback_output'] else ''),value(r['V_out'],'V'),
         value(r['P_out_min'],'W'),value(r['P_out'],'W')) for r in data['rails']],[1.2,2.3,1.3,1.3])
    if not data.get('supported'):
        paragraph(doc,'未执行：'+str(data.get('error')),True);return
    paragraph(doc,f"有效角点 {data['successful_cases']} / {data['total_cases']}。"+
              ('全部声明的离散角点已求解；不保证连续负载区间内无更坏值。' if data['complete'] else
               '存在未计算或不收敛角点，下表仅为成功角点观察范围，不能作为完整设计电压上下限。'),True)
    equation(doc,'R_j = ','V_ref,j²','P_load,j')
    equation(doc,'ΔV_env,% = 100·','V_max,j − V_min,j','V_ref,j')
    paragraph(doc,'包络跨度同时包含本路负载变化与其他路负载影响；“纯交叉跨度”则固定输入电压和被观察路自身负载，仅改变其他路负载，再取其中最大的跨度，均以该路匝比参考电压归一化。电压为直流平均值，不含开关纹波及动态过冲。')
    table(doc,['输出','直流范围 / V','相对参考偏差 / %','包络跨度 / %','纯交叉跨度 / %'],[
        (f'OUT{r["id"]}'+(' 主反馈' if r['feedback'] else ''),
         '未求解' if r['V_min'] is None else f"{r['V_min']:.5g} — {r['V_max']:.5g}",
         '未求解' if r['V_min'] is None else f"{r['deviation_min_pct']:+.3g} — {r['deviation_max_pct']:+.3g}",
         value(r['span_pct']),value(r['cross_only_pct'])) for r in data['summary']],
        [1.,1.65,1.75,1.3,1.4])
    figure(doc,_chart((7.1,2.6),lambda fig:draw_envelope(fig,data)),'图 1-交叉调整率 非反馈路直流电压角点包络')
    lookup={c['id']:c for c in data['cases']}
    extremes=[]
    for row in data['summary']:
        if row['feedback']:continue
        for kind,key in (('最低','min_case'),('最高','max_case')):
            case=lookup.get(row[key])
            if case:extremes.append((f'OUT{row["id"]} {kind}',case['id'],value(case['V_in'],'V'),
                                    ' / '.join(f'{v:g}' for v in case['powers'])))
    paragraph(doc,'下表负载向量与电压向量均按 OUT1 至 OUT'+str(len(data['rails']))+' 的顺序排列。')
    if extremes:table(doc,['极值','角点','输入电压','负载向量 / W'],extremes,[1.,.7,.9,4.5])
    doc.add_heading('1.3.1 负载组合扫描明细',2)
    table(doc,['角点 / Vin','负载向量 / W','直流电压向量 / V','状态'],[
        (c['id']+' / '+value(c['V_in'],'V'),' / '.join(f'{v:g}' for v in c['powers']),
         ' / '.join(f'{v:.5g}' for v in c['voltages']) if c['voltages'] is not None else '未求解',
         '已求解' if c['status']=='ok' else c['error']) for c in data['cases']],
        [.85,2.,2.,2.25])
    paragraph(doc,'参考：TI 多输出反激漏感与交叉调整率技术说明 '+SOURCE,True)
