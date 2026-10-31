"""Shared Word/Excel section; Excel consumes the same module blocks."""

def add_report(doc,p,result):
    data=result['op'].get('parasitics')
    if not data or (data['mode']=='fast' and not p.get('parasitic_config')):return
    from report_docx import section,paragraph,table,figure,_chart
    from parasitics import parameter_rows,NOTE
    section(doc,'2.2  寄生参数与局部换流核查')
    paragraph(doc,NOTE,True)
    table(doc,['参数 / 器件位号','采用值'],parameter_rows(p,len(result['op'].get('output_ops') or [None])),[4.6,2.5])
    if data.get('scope'):paragraph(doc,data['scope'],True)
    if data.get('edges'):
        table(doc,['端口','局部估算峰值 / V','无阻尼 LC 频率 / MHz'],[
            (z['ref'],f'{z["peak"]:.4g}',f'{z["frequency"]/1e6:.4g}' if z['frequency'] else '不适用') for z in data['edges']],[1.5,2.7,2.9])
        from parasitic_ringing import draw
        # At most two curves per figure keeps six-output reports readable.
        for start in range(0,len(data['edges']),2):
            subset=dict(data,edges=data['edges'][start:start+2])
            figure(doc,_chart((7.1,2.8*len(subset['edges'])),lambda fig:draw(fig,subset)),
                '局部 RLC 估算；并非完整多绕组同时换流或实测波形')
    paragraph(doc,'反激局部振铃不反向改写平均电流、直流输出与低频环路；器件耐压核查取原应力与局部峰值中较大者。'
        '正激周期电路已有的振铃不再叠加本地 LC 曲线。新增 RC 吸收的完整损耗请使用导出的 SPICE 工程核对，不能仅凭波形衰减判断效率。',True)
    if result.get('P_parasitic',0):paragraph(doc,f"正激物理周期已计入新增布线/RC 电阻损耗：{result['P_parasitic']:.5g} W；没有与原有铜损重复计算。")
