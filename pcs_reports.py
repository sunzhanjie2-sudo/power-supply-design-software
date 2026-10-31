"""Company-styled architecture overview and all independent converter reports."""
import json
from pathlib import Path
import re
from zipfile import ZipFile, ZIP_DEFLATED


def architecture_figure(project):
    from matplotlib.figure import Figure
    from matplotlib.backends.backend_agg import FigureCanvasAgg
    from matplotlib.patches import FancyBboxPatch, FancyArrowPatch
    from matplotlib import rc_context
    from io import BytesIO
    units={u['id']:u for u in project['units']}
    def depth(u):return depth(units[u['source']['id']])+1 if u['source']['kind']=='unit' else 1
    columns={0:[dict(b,kind='bus') for b in project['sources']]}
    for u in project['units']: columns.setdefault(depth(u),[]).append(dict(u,kind='unit'))
    all_count=sum(len(v) for v in columns.values())
    if not project.get('layout',{}).get('nodes'):
        columns={col:rows[:4] for col,rows in columns.items() if col<=3}
    shown_count=sum(len(v) for v in columns.values())
    positions={n['id']:(col*3.5,-i*1.8) for col,rows in columns.items() for i,n in enumerate(rows)}
    for key,point in project.get('layout',{}).get('nodes',{}).items():
        if key.split(':',1)[1] in positions:positions[key.split(':',1)[1]]=(point['x']/100,-point['y']/100)
    height=max(1,max((len(v) for v in columns.values()),default=0))*1.8
    with rc_context({'font.sans-serif':['Microsoft YaHei','DejaVu Sans'],'axes.unicode_minus':False}):
        fig=Figure(figsize=(11,max(3,height*.85)),layout='constrained');FigureCanvasAgg(fig);ax=fig.subplots();ax.set_axis_off()
        for rows in columns.values():
            for n in rows:
                x,y=positions[n['id']];dark=n['kind']=='bus'
                ax.add_patch(FancyBboxPatch((x,y),2.85,1.1,boxstyle='round,pad=.08,rounding_size=.12',fc='#0d1726' if dark else '#f3f6fa',ec='#0d1726' if dark else '#dfe6ee'))
                ax.text(x+.12,y+.85,n['id'],fontsize=9,color='#79dbea' if dark else '#2376e5',weight='bold')
                ax.text(x+.12,y+.52,n['name'][:14],fontsize=10,color='white' if dark else '#152238')
                label=(f"{n['min']:g}–{n['max']:g} V / {n['capacity']:g} W" if dark else f"{n['spec']['topology']} / {sum(r['P_out'] for r in n['rails']):g} W")
                ax.text(x+.12,y+.17,label,fontsize=8,color='#bdd0e1' if dark else '#68788f')
                if not dark and n['source']['id'] in positions:
                    px,py=positions[n['source']['id']]
                    ax.add_patch(FancyArrowPatch((px+2.95,py+.55),(x-.1,y+.55),arrowstyle='-|>',mutation_scale=13,color='#2376e5',lw=1.5,connectionstyle='arc3,rad=0.05'))
        if positions:
            ax.set_xlim(min(x for x,y in positions.values())-.25,max(x for x,y in positions.values())+3.25)
            ax.set_ylim(min(y for x,y in positions.values())-.3,max(y for x,y in positions.values())+1.5)
        else:ax.text(.5,.5,'辅源架构为空',transform=ax.transAxes,ha='center',color='#68788f')
        if shown_count<all_count:
            fig.text(.5,.01,f'架构图显示 {shown_count}/{all_count} 个节点；其余单元及完整连接关系见下方配置表。',ha='center',fontsize=8,color='#68788f')
        stream=BytesIO();fig.savefig(stream,format='png',dpi=170);return stream.getvalue()


def export_workspace(project, destination, *, cancelled=lambda:False, progress=lambda *args:None):
    if project.get('schema_version') == 'power.system-network/2':
        from network_report import export_network
        return export_network(project,destination,cancelled=cancelled,progress=progress)
    from pcs_workspace import validate_project,capacity_checks,interface_checks
    from design_engine.service import calculate,export_report
    from calculation_scheduler import CalculationCancelled
    from docx_layout import new_document,paragraph,table,figure,section
    from design_engine.contracts import json_value
    from design_theme import select,report_name
    system = project.get('workspace_kind') == 'power-system'
    select('default' if system else 'pcs');p=validate_project(project)
    area = '电源系统' if system else '辅源'
    destination=Path(destination);work=destination.parent/('pcs-units-'+destination.stem);work.mkdir(exist_ok=True)
    overview=new_document(('电源系统' if system else 'PCS 辅源')+'架构与设计总览',p['title']+'  修订 '+p['revision'],area+'架构与完整计算报告')
    paragraph(overview,'本报告记录已配置的'+area+'供电架构、容量分配与各单元计算状态。每单元的完整 Word、Excel 报告和工程配置随报告包交付，保留 Vinmin 与 Vinmax 两端工况。')
    figure(overview,architecture_figure(p),area+'供电架构  连线为供电关系，非安规或生产原理图')
    table(overview,['单元','名称与拓扑','输入来源','输出配置功率 / W'],[(u['id'],u['name']+'\n'+u['spec']['topology'],u['source']['id']+('/OUT'+str(u['source']['output']) if u['source']['kind']=='unit' else ''),f"{sum(r['P_out'] for r in u['rails']):.5g}") for u in p['units']],[.8,2.8,1.8,1.7])
    overview.add_heading('容量分配初查',1)
    budget=capacity_checks(p)
    table(overview,['输入源或输出端口','配置容量 / W','下级预算 / W','剩余 / W','初查'],[(r['port'],f"{r['capacity']:.5g}",f"{r['allocated']:.5g}",f"{r['remaining']:.5g}",'容量不足' if not r['ok'] else '未超配置') for r in budget],[2.1,1.3,1.3,1.2,1.2])
    paragraph(overview,'预算按各单元输出配置总功率除以预设效率，使用上游端口容量分配给下级输入；不把下级功率重复计为系统外部输出，也不据此宣称整机效率。预算不覆盖启动浪涌、时序、掉电保持、隔离等级或实测交叉调整率。',True)
    interfaces=interface_checks(p)
    for item in interfaces:
        if not item['ok']:
            if item['source_min'] is None:
                paragraph(overview,f"接口待核对 {item['unit']}：输入未连接；该单元仍按自身设计参数独立计算。",True);continue
            paragraph(overview,f"接口待核对 {item['unit']}：设计输入 {item['design_min']:g}–{item['design_max']:g} V 未覆盖上游标称 {item['source_min']:g}–{item['source_max']:g} V。报告未自动改写用户设计。",True)
    outcomes=[];files=[]
    for i,u in enumerate(p['units']):
        if cancelled():raise CalculationCancelled()
        progress(i,len(p['units']),u['id']+' 正在计算 Vinmin / Vinmax')
        try:
            report_name(u['id']+' '+u['name'])
            spec=dict(u['spec'],__web_project_title=u['id']+' '+u['name'])
            run=calculate(spec,analysis='endpoints',include_efficiency=True,
                          include_cross_regulation=p['includeCrossRegulation'],cancelled=cancelled)
            safe=re.sub(r'[^\w\u4e00-\u9fff-]','_',u['id']+'_'+u['name'])[:90]
            for suffix in ('docx','xlsx'):
                path=work/(safe+'.'+suffix);stats=export_report(run,path);files.append(path)
            valid=sum(not c.get('error') and c.get('result') is not None for c in run.runtime_bundle()['cases'])
            outcomes.append(dict(id=u['id'],name=u['name'],successful_cases=valid,total_cases=2,status='完成' if valid==2 else '部分工况未完成'))
            config=work/(safe+'.json')
            config.write_text(json.dumps(json_value(spec),ensure_ascii=False,indent=2),encoding='utf-8')
            files.append(config)
        except CalculationCancelled:raise
        except Exception as exc:
            outcomes.append(dict(id=u['id'],name=u['name'],status='计算或报告失败',error=str(exc)))
        progress(i+1,len(p['units']),u['id']+' '+outcomes[-1]['status'])
    overview.add_heading('逐单元交付状态',1)
    table(overview,['单元','名称','状态','说明'],[(r['id'],r['name'],r['status'],r.get('error','Vinmin / Vinmax；完整结果和模型边界见该单元报告')) for r in outcomes],[.8,1.7,1.4,3.2])
    paragraph(overview,'交叉负载角点：'+('已请求计算，是否成功以单元报告为准。' if p['includeCrossRegulation'] else '本次未执行；可在工作区报告页启用，或在单元设计中单独计算。'),True)
    overview_path=work/('00_'+area+'架构与设计总览.docx');overview.save(overview_path);files.insert(0,overview_path)
    manifest=dict(schema_version='pcs.aux-delivery/1',title=p['title'],revision=p['revision'],presentation='default' if system else 'pcs',budget=budget,interfaces=interfaces,units=outcomes)
    if cancelled():raise CalculationCancelled()
    with ZipFile(destination,'w',compression=ZIP_DEFLATED) as z:
        for f in files:z.write(f,f.name)
        from system_workspace import normalize_project
        saved = normalize_project(project) if system else p
        z.writestr('系统工程.json' if system else '辅源工作区.json',json.dumps(json_value(saved),ensure_ascii=False,indent=2))
        z.writestr('manifest.json',json.dumps(manifest,ensure_ascii=False,indent=2))
    return dict(path=str(destination),media_type='application/zip',units=outcomes,
                successful=sum(r['status']=='完成' for r in outcomes),total=len(outcomes))
