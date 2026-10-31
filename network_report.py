"""System-network reports: topology, loads, diode OR-ing and endpoint units."""
import copy
import json
from pathlib import Path
import re
from zipfile import ZipFile, ZIP_DEFLATED


def architecture(project):
    from io import BytesIO
    from matplotlib.figure import Figure
    from matplotlib.backends.backend_agg import FigureCanvasAgg
    from matplotlib.patches import FancyBboxPatch, FancyArrowPatch, Polygon
    from matplotlib import rc_context
    from system_workspace import auto_layout, all_nodes
    from network_layout import diode_point
    p = copy.deepcopy(project)
    saved=copy.deepcopy(p.get('layout',{}));auto_layout(p)
    p['layout']['nodes'].update(saved.get('nodes',{}));p['layout']['diodes']=saved.get('diodes',{})
    positions=p['layout']['nodes']
    entries=list(all_nodes(p))
    xy={n['id']:(positions.get(k+':'+n['id'],dict(x=40,y=50+i*220))['x']/100,
                  -positions.get(k+':'+n['id'],dict(x=40,y=50+i*220))['y']/100) for i,(k,n) in enumerate(entries)}
    dpoints={e['id']:diode_point(p,e) for e in p['connections'] if e['mode']=='diode'}
    maxx=max([v[0]+3.2 for v in xy.values()]+[v['x']/100+.7 for v in dpoints.values()]+[4]);miny=min([v[1]-3.2 for v in xy.values()]+[-v['y']/100-.6 for v in dpoints.values()]+[-3])
    ratio=(abs(miny)+1)/maxx
    with rc_context({'font.sans-serif':['Microsoft YaHei','DejaVu Sans'],'axes.unicode_minus':False,'svg.fonttype':'none','svg.hashsalt':'power-network-layout'}):
        fig=Figure(figsize=(11,max(3,min(9,11*ratio))),layout='constrained');FigureCanvasAgg(fig)
        ax=fig.subplots();ax.set_axis_off()
        for e in p['connections']:
            s=e['source'];a=xy[s['id']];b=xy[e['target']]
            sy=a[1]-(1.02 if s['kind']=='bus' else 1.19+.26*(s['output']-1))
            color='#2376e5' if e['enabled'] else '#a3acba'
            start,end=(a[0]+2.88,sy),(b[0],b[1]-.94)
            mx,my=(start[0]+end[0])/2,(start[1]+end[1])/2
            if e['mode']=='diode':
                dp=dpoints[e['id']];mx,my=dp['x']/100,-dp['y']/100
                segments=[(start,(mx-.44,my)),((mx+.44,my),end)]
            else:segments=[(start,end)]
            for aa,bb in segments:
                ax.add_patch(FancyArrowPatch(aa,bb,arrowstyle='-|>',mutation_scale=10,color=color,lw=1.3,
                                            linestyle='-' if e['enabled'] else '--',connectionstyle='arc3,rad=0.03'))
            if e['mode']=='diode':
                ax.add_patch(FancyBboxPatch((mx-.44,my-.25),.88,.5,boxstyle='round,pad=.01,rounding_size=.07',fc='white',ec='#9bb2cd',lw=1,zorder=5))
                ax.text(mx,my+.13,e['id'],fontsize=5.5,ha='center',color='#677e9b',zorder=6)
                ax.add_patch(Polygon([(mx-.23,my+.05),(mx-.1,my-.02),(mx-.23,my-.09)],fc='#edf3ff',ec=color,lw=1,zorder=6))
                ax.plot([mx-.08,mx-.08],[my-.11,my+.07],color=color,lw=1,zorder=6)
                ax.text(mx+.17,my-.05,f"{e['vf']:g}V",fontsize=6.5,ha='center',color='#294560',zorder=6)
            else:ax.text(mx,my+.1,'OUT'+str(s['output']) if s['kind']=='unit' else 'DC',fontsize=6.5,ha='center',color='#7c91aa')
        for kind,n in entries:
            x,y=xy[n['id']];height=1.58+.26*max(0,len(n.get('rails',[]))-1)
            dark=kind=='bus';fc={'bus':'#10243b','unit':'#f4f7ff','junction':'#f4efff','load':'#eaf7f1'}[kind]
            ax.add_patch(FancyBboxPatch((x,y-height),2.88,height,boxstyle='round,pad=.02,rounding_size=.08',fc=fc,ec='#94adc9',lw=1))
            ax.text(x+.14,y-.27,n['id']+' · '+{'bus':'输入源','unit':'电源模块','junction':'二极管 OR','load':'负载'}[kind],fontsize=8,color='#78daeb' if dark else '#2376e5',weight='bold')
            ax.text(x+.14,y-.58,n['name'][:17],fontsize=10,color='white' if dark else '#172c46',weight='bold')
            text=(f"{n['min']:g}–{n['max']:g}V / {n['capacity']:g}W" if dark else
                  f"{n['power']:g}W 负载" if kind=='load' else f"OR 母线容量 {n['capacity']:g}W" if kind=='junction' else n['spec']['topology'])
            ax.text(x+.14,y-.82,text,fontsize=8,color='#b8cbdc' if dark else '#6b7e94')
            if kind=='unit':
                for i,r in enumerate(n['rails'],1):
                    ax.text(x+2.7,y-1.19-.26*(i-1),f"OUT{i} {r['V_out']:.4g}V",fontsize=7,ha='right',color='#15846d')
            if not n['enabled']:ax.text(x+2.25,y-.58,'停用',fontsize=8,color='#b67726')
        ax.set_xlim(0,maxx);ax.set_ylim(miny,.1)
        if not entries:ax.text(.5,.5,'供电网络为空',transform=ax.transAxes,ha='center')
        png,svg=BytesIO(),BytesIO();fig.savefig(png,format='png',dpi=150);fig.savefig(svg,format='svg')
        return png.getvalue(),svg.getvalue()


def export_network(project,destination,*,cancelled=lambda:False,progress=lambda *args:None):
    from ldo_report import fmt
    from system_workspace import normalize_project, checks, all_nodes
    from design_engine.service import calculate,export_report
    from calculation_scheduler import CalculationCancelled
    from docx_layout import new_document,paragraph,table,figure
    from design_theme import select,report_name
    from openpyxl import Workbook
    from openpyxl.styles import Font,PatternFill,Alignment
    p=normalize_project(project);review=checks(p)
    select('default')
    target=Path(destination);work=target.parent/('network-units-'+target.stem);work.mkdir(exist_ok=True)
    doc=new_document('辅源供电网络与设计总览',p['title']+' 修订 '+p['revision'],'系统架构与各模块计算报告')
    paragraph(doc,'本报告记录输入源、变换器、二极管竞争供电与终端负载的连接关系。开关电源沿用独立设计参数；启用“跟随上游”的 LDO 按连接关系同步输入范围。系统层检查容量、电压及备用供电。')
    png,svg=architecture(p);figure(doc,png,'辅源供电网络  二极管符号表示隔离竞争支路，箭头为供电方向')
    doc.add_heading('节点与负载',1)
    nrows=[]
    for kind,n in all_nodes(p):
        detail=(f"{n['min']:g}–{n['max']:g} V / {n['capacity']:g} W" if kind=='bus' else
                f"{n['power']:g} W；允许 {n['min']:g}–{n['max']:g} V，0为不限" if kind=='load' else
                f"{n['capacity']:g} W OR 母线" if kind=='junction' else n['spec']['topology'])
        nrows.append((n['id'],n['name'],kind,detail,'启用' if n['enabled'] else '停用'))
    table(doc,['节点','名称','类型','配置','状态'],nrows,[.8,1.5,.9,3.1,.6])
    doc.add_heading('供电连接与二极管参数',1)
    erows=[(e['id'],e['source']['id']+('/OUT'+str(e['source']['output']) if e['source']['kind']=='unit' else ''),e['target'],
            '二极管 OR' if e['mode']=='diode' else '直连',f"{e['vf']:g}" if e['mode']=='diode' else '—','启用' if e['enabled'] else '停用') for e in p['connections']]
    table(doc,['连接','上游','下游','方式','Vf / V','状态'],erows,[.8,1.5,1.4,1.1,.7,.7])
    doc.add_heading('正常与备用供电功率预算',1)
    brows=[(r['port'],f"{r['normal']:.5g}",f"{r['allocated']:.5g}",f"{r['capacity']:.5g}",'未超容量' if r['ok'] else '待检查',r['worst_case']) for r in review['capacity']]
    table(doc,['端口','正常 / W','最坏 / W','容量 / W','检查','最坏工况'],brows,[1.2,.85,.85,.85,.85,2])
    paragraph(doc,'开关电源按配置额定输出功率/预设效率预算；LDO 按该工况实际输入电压及最大负载、分压、Iq 预算。终端负载和后级模块输入占用上游端口额定容量，不再次叠加到上游模块输入。竞争支路逐工况选择，备用源不重复计为同时承担同一负载。',True)
    paragraph(doc,review['method'],True)
    if not review['coverage_complete']:paragraph(doc,'分支组合超过枚举限额，预算覆盖不完整，不判为通过。',True)
    doc.add_heading('输入电压与失电检查',1)
    irows=[(r['unit'],r['name'],'无供电' if r['source_min'] is None else f"{r['source_min']:.5g}–{r['source_max']:.5g}",
            f"{r['design_min']:.5g}–{r['design_max']:.5g}",r['note'],'电压覆盖' if r['ok'] else '待检查') for r in review['interfaces']]
    table(doc,['节点','名称','可用 / V','设计 / V','供电状态','电压检查'],irows,[.8,1.3,1.1,1.1,1.6,.7])
    doc.add_heading('竞争二极管导通损耗估算',1)
    drows=[(r['connection'],r['source'],r['target'],f"{r['vf']:.5g}",f"{r['loss']:.5g}") for r in review['diode_losses'] if r['vf']]
    table(doc,['连接','上游','下游','Vf / V','最大损耗 / W'],drows,[1,1.7,1.7,1,1.4])
    paragraph(doc,'二极管采用用户填写的固定 Vf，损耗按支路电流×Vf。未包含动态切换、尖峰、反向漏电、温度变化或真实均流；同压支路按各支路独占供电枚举。',True)
    linear_rows=[(r['unit'],fmt(r['max_loss']),fmt(r['max_Tj']),'满足' if r['dropout_ok'] else '压差不足','满足' if r['thermal_ok'] else '热设计需核对') for r in review.get('ldo',[])]
    if linear_rows:
        doc.add_heading('LDO 静态损耗与热设计',1)
        table(doc,['单元','最大芯片损耗 / W','最高估算结温 / °C','压差','温升检查'],linear_rows,[1.3,1.4,1.5,1.1,1.8])
    files=[];outcomes=[]
    for i,u in enumerate(p['units']):
        if cancelled():raise CalculationCancelled()
        progress(i,len(p['units']),u['id']+' 正在计算 Vinmin / Vinmax')
        try:
            report_name(u['id']+' '+u['name']);spec=dict(u['spec'],__web_project_title=u['id']+' '+u['name'])
            from ldo import is_ldo
            if is_ldo(spec):
                from system_workspace import prepare_unit
                from power_units import export_ldo
                spec=dict(prepare_unit(p,u['id'])['spec'],__web_project_title=u['id']+' '+u['name'])
                safe=re.sub(r'[^\w\u4e00-\u9fff-]','_',u['id']+'_'+u['name'])[:90]
                for suffix in ('docx','xlsx','json'):
                    path=work/(safe+'.'+suffix);export_ldo(spec,path);files.append(path)
                outcomes.append(dict(id=u['id'],name=u['name'],status='完成',design_type='ldo',successful_cases=4,total_cases=4))
                progress(i+1,len(p['units']),u['id']+' 完成');continue
            run=calculate(spec,analysis='endpoints',include_efficiency=True,include_cross_regulation=p['includeCrossRegulation'],cancelled=cancelled)
            safe=re.sub(r'[^\w\u4e00-\u9fff-]','_',u['id']+'_'+u['name'])[:90]
            for suffix in ('docx','xlsx'):
                path=work/(safe+'.'+suffix);export_report(run,path);files.append(path)
            valid=sum(not c.get('error') and c.get('result') is not None for c in run.runtime_bundle()['cases'])
            outcomes.append(dict(id=u['id'],name=u['name'],successful_cases=valid,total_cases=2,status='完成' if valid==2 else '部分工况未完成'))
            config=work/(safe+'.json');config.write_text(json.dumps(spec,ensure_ascii=False,indent=2),encoding='utf-8');files.append(config)
        except CalculationCancelled:raise
        except Exception as exc:outcomes.append(dict(id=u['id'],name=u['name'],status='计算或报告失败',error=str(exc)))
        progress(i+1,len(p['units']),u['id']+' '+outcomes[-1]['status'])
    doc.add_heading('独立单元交付状态',1)
    table(doc,['模块','名称','状态','说明'],[(r['id'],r['name'],r['status'],r.get('error','按单元设计参数计算两端输入；架构停用不删除独立设计')) for r in outcomes],[.8,1.8,1.1,3.3])
    overview=work/'00_辅源供电网络与设计总览.docx';doc.save(overview);files.insert(0,overview)
    workbook=Workbook();workbook.remove(workbook.active)
    sheets=[('节点与负载',['节点','名称','类型','配置','状态'],nrows),('供电连接',['连接','上游','下游','方式','Vf/V','状态'],erows),
            ('功率预算',['端口','正常W','最坏W','容量W','检查','最坏工况'],brows),('输入与失电',['节点','名称','可用V','设计V','供电状态','检查'],irows),
            ('二极管估算',['连接','上游','下游','Vf/V','最大损耗W'],drows),
            ('竞争供电工况',['工况','正常','各端口分配W','选中支路','失电节点'],[(c['name'],c['normal'],json.dumps(c['allocated'],ensure_ascii=False),json.dumps(c['routes'],ensure_ascii=False),'、'.join(c['unavailable'])) for c in review['cases']])]
    if linear_rows:sheets.append(('LDO损耗与温升',['单元','最大芯片W','估算结温°C','压差','温升'],linear_rows))
    for name,header,rows in sheets:
        sheet=workbook.create_sheet(name);sheet.append(header)
        for row in rows:sheet.append(row)
        sheet.freeze_panes='A2';sheet.auto_filter.ref=sheet.dimensions
        for cell in sheet[1]:cell.fill=PatternFill('solid',fgColor='173B64');cell.font=Font(color='FFFFFF',bold=True)
        for col in sheet.columns:
            letter=col[0].column_letter;sheet.column_dimensions[letter].width=min(75,max(18,max(len(str(c.value or '')) for c in col[:50])+3))
        for row in sheet.iter_rows(min_row=2):
            for cell in row:
                cell.alignment=Alignment(vertical='top',wrap_text=True)
                if isinstance(cell.value,str):cell.data_type='s'
    excel=work/'00_供电网络预算.xlsx';workbook.save(excel);files.append(excel)
    manifest=dict(schema_version='power.system-delivery/2',title=p['title'],revision=p['revision'],units=outcomes,
                  budget=review['capacity'],interfaces=review['interfaces'],method=review['method'],coverage_complete=review['coverage_complete'])
    if cancelled():raise CalculationCancelled()
    with ZipFile(target,'w',compression=ZIP_DEFLATED) as z:
        for f in files:z.write(f,f.name)
        z.writestr('系统工程.json',json.dumps(p,ensure_ascii=False,indent=2))
        z.writestr('供电网络.svg',svg);z.writestr('manifest.json',json.dumps(manifest,ensure_ascii=False,indent=2))
    return dict(path=str(target),media_type='application/zip',units=outcomes,successful=sum(r['status']=='完成' for r in outcomes),total=len(outcomes))
