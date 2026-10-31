"""Linear-regulator report projection; no switching traces or invented Bode."""
import json
from pathlib import Path

STATE={'pass':'模型内满足','review':'需核对','undefined':'资料待补充','na':'不适用'}
def fmt(v):return '未定义 / 不适用' if v is None else '是' if v is True else '否' if v is False else f'{v:.6g}' if isinstance(v,(int,float)) else str(v)

def modules(result):
    from ldo import FIELDS
    p=result['spec'];rows=[]
    for section,fields in FIELDS:
        if section=='可调输出分压' and p['output_mode']=='fixed':continue
        rows.extend((section+' / '+label,p[k]/scale if p[k] is not None else None,unit)for k,label,unit,scale in fields)
    identity=[('厂家',p['manufacturer'] or '待填',''),('型号',p['model'] or '待填',''),('封装',p['package'] or '待填',''),
              ('输出类型','固定输出' if p['output_mode']=='fixed' else '可调输出',''),
              ('反向电流保护',{'unknown':'待核对','yes':'已声明具备','no':'不具备'}[p['reverse_blocking']],''),
              ('具有 EN 引脚',p['enable_pin'],''),('具有 PG 引脚',p['power_good'],''),('跟随上游输入',p['follow_input'],''),
              ('资料来源与条件',p['notes'] or '待补充','')]
    names={'R_top':'上分压电阻 R1','R_bottom':'下分压电阻 R2','I_divider':'分压支路电流','P_top':'R1 耗散','P_bottom':'R2 耗散'}
    return [('需求与器件',identity+rows),
            ('分压与损耗',[(names[k],v,'A' if k=='I_divider' else 'W' if k.startswith('P_') else 'Ω')for k,v in result['divider'].items()] if p['output_mode']=='adjustable' else [('分压网络','固定输出，不使用外部分压','')]),
            ('检查与降额',[(r['name'],fmt(r['value'])+' '+r['unit'],r['comparison']+' '+fmt(r['limit'])+' '+r['unit']+'；'+STATE[r['state']]+'；'+r['note'])for r in result['checks']]),
            ('关键器件BOM',[(r['ref']+' '+r['role'],' / '.join(r.get(k) or '待填' for k in ('manufacturer','model','package')),f"数量 {r['quantity']}；{'平均耗散 / W' if r['kind']=='resistor' else '工作电压 / V'} {fmt(r.get('value'))}；额定 {fmt(r.get('rating'))}；{'推荐输入上限检查' if r['kind']=='ic' else '降额因数 '+fmt(r.get('factor'))}；{STATE[r['state']]}")for r in result['bom']])]

def circuit_png(p):
    from io import BytesIO
    from matplotlib.figure import Figure
    from matplotlib.backends.backend_agg import FigureCanvasAgg
    from matplotlib.patches import Rectangle
    from matplotlib import rc_context
    with rc_context({'font.sans-serif':['Microsoft YaHei','DejaVu Sans'],'axes.unicode_minus':False}):
        fig=Figure(figsize=(9,2.7),layout='constrained');FigureCanvasAgg(fig);a=fig.subplots();a.axis('off');a.set_xlim(0,10);a.set_ylim(0,3)
        a.add_patch(Rectangle((4,1.45),2,1.05,fc='#edf4ff',ec='#2376e5',lw=1.6));a.text(5,2.1,'U1 · LDO',ha='center',color='#173b64',weight='bold')
        a.plot([.5,4],[2,2],color='#173b64');a.plot([6,9.5],[2,2],color='#173b64');a.plot([.5,9.5],[.35,.35],color='#173b64');a.plot([5,5],[1.45,.35],color='#173b64')
        for x,label in [(2,'C_IN1'),(8,'C_OUT1')]:
            a.plot([x,x],[2,1.3],color='#173b64');a.plot([x-.25,x+.25],[1.3,1.3],color='#173b64');a.plot([x-.25,x+.25],[1.15,1.15],color='#173b64');a.plot([x,x],[1.15,.35],color='#173b64');a.text(x+.35,1,label,fontsize=10)
        a.text(.5,2.25,'VIN');a.text(8.5,2.25,'OUT '+fmt(p['V_out'])+'V');a.text(5,.07,'GND',ha='center')
        if p['output_mode']=='adjustable':a.text(6.5,.65,'FB: R1 + R2；详见分压表',fontsize=10,color='#2376e5')
        stream=BytesIO();fig.savefig(stream,format='png',dpi=160);return stream.getvalue()

def export_report(result,destination):
    path=Path(destination);suffix=path.suffix.lower();p=result['spec'];path.parent.mkdir(parents=True,exist_ok=True)
    if suffix=='.json':path.write_text(json.dumps(result,ensure_ascii=False,indent=2,allow_nan=False),encoding='utf-8')
    elif suffix=='.docx':
        from docx_layout import new_document,paragraph,table,figure,equation
        doc=new_document('LDO 线性稳压器设计报告',p.get('__web_project_title','') or '输入端点 × 轻载/满载','LDO 静态设计与器件检查')
        paragraph(doc,'本报告不使用开关电源功率级或补偿模型。压差不足时，不给出承诺稳压的输出、效率和温升。')
        figure(doc,circuit_png(p),'LDO 参考连接与器件位号；实际引脚、EN/PG与接线按所选芯片规格书')
        for formula in ['Iin = Iout + Idiv + Iq','Pchip = (Vin - Vout)·(Iout + Idiv) + Vin·Iq','Tj = Ta + Pchip·θja','η = Pout/Pin']:
            equation(doc,formula)
        paragraph(doc,'Iq 为接地电流；Idiv 为外部分压电流，固定输出时取零。θja 为实际板级条件下的有效结至环境热阻。上述损耗、效率及结温采用标称输出电压。',True)
        for title,rows in modules(result):doc.add_heading(title,1);table(doc,['参数 / 位号','值 / 资料','单位 / 判定'],[(a,fmt(b),fmt(c))for a,b,c in rows],[2.7,1.9,2.5])
        doc.add_heading('四角点结果',1)
        table(doc,['工况','Vin / V','Iout / A','芯片损耗 / W','η / %','结温 / °C','压差裕量 / V'],[(c['id'],fmt(c['V_in']),fmt(c['I_out']),fmt(c['P_chip']),fmt(c['eta']*100 if c['eta'] is not None else None),fmt(c['T_j']),fmt(c['dropout_margin']))for c in result['corners']],[1.2,.65,.7,.9,.8,.9,1.1])
        doc.add_heading('输入预算与输出精度包络',1)
        table(doc,['工况','输入电流 / mA','输入功率 / W','输出功率 / W','输出电压范围 / V'],[(c['id'],fmt(c['I_in']*1000),fmt(c['P_in']),fmt(c['P_out']),fmt(c['V_out_min'])+' – '+fmt(c['V_out_max']))for c in result['corners']],[1.2,1.2,1.2,1.2,2.1])
        doc.add_heading('计算边界',1)
        for note in result['notes']:paragraph(doc,note)
        doc.save(path)
    elif suffix=='.xlsx':
        from openpyxl import Workbook
        from openpyxl.styles import Font,PatternFill,Alignment
        book=Workbook();book.remove(book.active)
        for title,rows in modules(result):
            sheet=book.create_sheet(title);sheet.append(['参数 / 位号','值 / 资料','单位 / 判定'])
            for row in rows:sheet.append(list(row))
        sheet=book.create_sheet('双端点角点对比')
        headers=['工况','Vin/V','Iout/A','Pchip/W','η','Tj/°C','压差裕量/V']
        for col,label in [(1,'Vinmin'),(9,'Vinmax')]:
            sheet.cell(1,col,label)
            for j,h in enumerate(headers):sheet.cell(2,col+j,h)
            for i,c in enumerate([r for r in result['corners'] if r['id'].startswith(label)],3):
                for j,v in enumerate([c['id'],c['V_in'],c['I_out'],c['P_chip'],c['eta'],c['T_j'],c['dropout_margin']]):sheet.cell(i,col+j,v)
        sheet=book.create_sheet('模型边界')
        for note in result['notes']:sheet.append([note])
        sheet=book.create_sheet('功率与输出范围');sheet.append(['工况','Iin / A','Pin / W','Pout / W','Vout,min / V','Vout,max / V'])
        for c in result['corners']:sheet.append([c['id'],c['I_in'],c['P_in'],c['P_out'],c['V_out_min'],c['V_out_max']])
        for sheet in book:
            sheet.freeze_panes='A3';sheet.auto_filter.ref=sheet.dimensions
            for c in sheet[1]:c.font=Font(color='FFFFFF',bold=True);c.fill=PatternFill('solid',fgColor='173B64')
            for col in sheet.columns:
                sheet.column_dimensions[col[0].column_letter].width=18 if sheet.title in ('双端点角点对比','功率与输出范围') else 48
            for row in sheet:
                for cell in row:
                    cell.alignment=Alignment(wrap_text=True,vertical='top')
                    if isinstance(cell.value,str):cell.data_type='s'
            if sheet.title=='双端点角点对比':
                sheet.column_dimensions['H'].width=3
                for c in sheet[2]:c.font=Font(color='FFFFFF',bold=True);c.fill=PatternFill('solid',fgColor='173B64')
                for row in (3,4):
                    for col in (5,13):sheet.cell(row,col).number_format='0.0%'
            if sheet.title=='模型边界':sheet.column_dimensions['A'].width=110
        book.save(path)
    else:raise ValueError('LDO 报告只支持 Word、Excel 或 JSON')
    return dict(path=str(path),media_type={'.json':'application/json','.xlsx':'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet','.docx':'application/vnd.openxmlformats-officedocument.wordprocessingml.document'}[suffix])
