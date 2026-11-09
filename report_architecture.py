"""Shared evidence-first report structure and paired endpoint presentation.

This module only projects completed snapshots. It never runs a field/circuit
solver, tunes a controller, or fills missing evidence with a different case.
"""
from collections import OrderedDict
from contextlib import contextmanager
from contextvars import ContextVar
from copy import deepcopy
from io import BytesIO
import math
import re

from docx.oxml import OxmlElement
from docx.oxml.ns import qn
from docx.shared import Inches, Pt
from docx.enum.text import WD_ALIGN_PARAGRAPH

from docx_layout import paragraph, table, _font

CASE_COLORS = {'Vinmin': '2068A0', 'Vinmax': 'A46118'}
MODULES = OrderedDict([
    ('overview', '需求与共同硬件'), ('topology', '拓扑与输出架构'),
    ('power', '功率级与开关过程'), ('devices', '器件应力与损耗'),
    ('caps', '电容分流与纹波'), ('magnetics', '磁件与绕制'),
    ('loop', '环路与补偿电路'), ('clamp', '钳位与复位'),
    ('efficiency', '损耗与效率'), ('psr', '原边反馈与控制'),
    ('review', '边界与工程复核'), ('inputs', '输入参数追溯'),
    ('cross_regulation', '交叉调整率'), ('bom', '关键器件与降额'),
])
CHAPTERS = (
    ('需求与共同硬件', ('overview', 'topology')),
    ('功率级与开关过程', ('power', 'clamp')),
    ('器件选型与损耗', ('devices', 'efficiency', 'bom')),
    ('电容分流与输出纹波', ('caps',)),
    ('磁件设计与绕制', ('magnetics',)),
    ('环路与反馈补偿', ('loop', 'psr')),
    ('负载边界与交叉调整率', ('cross_regulation',)),
    ('模型边界与待闭合事项', ('review',)),
    ('输入参数与追溯', ('inputs',)),
)
_CAPTURE_WIDTH = ContextVar('report_comparison_chart_width', default=None)


def module_key(title):
    """Stable mapping of the complete legacy author's section headings."""
    if title.startswith('1.4'): return 'bom'
    if title.startswith('1.3'): return 'cross_regulation'
    if title.startswith('附录'): return 'inputs'
    if title.startswith('1.2'):
        return 'psr' if 'PSR' in title or 'MP6005' in title else 'topology'
    if title.startswith('1.1'): return 'topology'
    match = re.match(r'^(\d+)(?:[.\s]|$)', title)
    if match:
        return {'0':'topology', '1':'overview', '2':'power', '3':'devices',
                '4':'caps', '5':'magnetics', '6':'loop', '7':'clamp',
                '8':'efficiency', '9':'review'}.get(match[1])
    return None


def available_width(doc):
    sec = doc.sections[-1]
    return (sec.page_width-sec.left_margin-sec.right_margin)/914400


def module_section(doc, title, *, level=1, new_page=True):
    p = doc.add_heading(title, level)
    p.paragraph_format.page_break_before = bool(new_page)
    for run in p.runs: _font(run, 17 if level == 1 else 13, True)
    return p


@contextmanager
def comparison_charts(width=4.72):
    """Render graphs at their final physical width instead of shrinking text."""
    token = _CAPTURE_WIDTH.set(width)
    try: yield
    finally: _CAPTURE_WIDTH.reset(token)


def chart_size(size,draw=None):
    width = _CAPTURE_WIDTH.get()
    if getattr(draw,'__name__','')=='topology':return size
    return size if width is None else (width, min(max(size[1], 2.1), 5.0))


def prepare_chart(fig,draw=None):
    """Keep final-width plots readable, including long switching titles."""
    if _CAPTURE_WIDTH.get() is None or getattr(draw,'__name__','')=='topology':return
    def wrap(text,budget):
        lines=[]
        for source in text.replace(' · ','\n').splitlines():
            current='';used=0
            for char in source:
                weight=2 if ord(char)>255 else 1
                if current and used+weight>budget:
                    lines.append(current.strip());current='';used=0
                current+=char;used+=weight
            if current:lines.append(current.strip())
        return '\n'.join(lines)
    for ax in fig.axes:
        # The complete wire and physical-layer identities are in the adjacent
        # report tables. At final two-column width an outside legend collides
        # with the per-layer labels; keep those spatial labels on the drawing.
        if '净窗口' in ax.get_title() and ax.get_legend() is not None:
            ax.get_legend().remove()
        if ax.get_xlabel().startswith('阶段展开'):
            # Actual duration remains in the immediately following native
            # table; five stage labels plus nanoseconds cannot fit in 2 inches.
            labels=[label.get_text().splitlines()[0].replace('钳位恢复','钳位\n恢复') for label in ax.get_xticklabels()]
            if labels:
                ax.set_xticks(ax.get_xticks(),labels)
                ax.tick_params(axis='x',labelsize=6)
            ax.set_xlabel('阶段展开（非等时长；时长见分段表）',fontsize=7)
        budget=max(18,int(ax.get_position().width*fig.get_figwidth()*72/4.5))
        if ax.get_title():ax.set_title(wrap(ax.get_title(),budget),fontsize=9)
        for label in ax.get_xticklabels():
            if '\n' not in label.get_text() and len(label.get_text())>12:
                label.set_text(wrap(label.get_text(),12))


def component_check_label(check):
    """Disambiguate a blocking platform from its separately checked envelope."""
    name=check['name']
    if str(check.get('ref','')).startswith('Q'):
        if check.get('metric')=='voltage':
            return check['ref']+' MOS 阻断平台 Vds'
        if check.get('metric')=='peak':
            return check['ref']+(' MOS 钳位/峰值包络 Vds' if '稳态' in name else ' MOS 窄尖峰包络 Vds')
    return name


def _cell_text(value):
    if value is None: return '未计算'
    if isinstance(value, float):
        return f'{value:.6g}' if math.isfinite(value) else '未定义'
    return str(value)


def _records(headers, rows):
    """Unfold the author's two metric/value pairs without dropping a field."""
    result = []
    if len(rows)==1 and len(headers)>2 and headers[0] not in ('核查项','位号 / 检查项','位号','器件','参数','过程'):
        # A one-record summary uses its column headers as metric names; a
        # numerical fc or a mode string is not a stable row identifier.
        return [(str(h),_cell_text(v)) for h,v in zip(headers,rows[0])]
    repeated = len(headers) == 4 and headers[0] == headers[2] and headers[1] == headers[3]
    for row in rows:
        if repeated:
            result.extend((str(row[i]), str(row[i+1])) for i in (0,2))
        else:
            values = [(_cell_text(v)) for v in row[1:]]
            text = values[0] if len(values) == 1 else '\n'.join(
                str(h)+'  '+v for h,v in zip(headers[1:], values))
            result.append((_cell_text(row[0]), text))
    return result


def comparison_rows(headers, left_rows, right_rows):
    def keyed(rows):
        counts, output = {}, OrderedDict()
        for name, value in _records(headers, rows):
            counts[name] = counts.get(name, 0)+1
            output[name, counts[name]] = value
        return output
    left, right = keyed(left_rows), keyed(right_rows)
    return [(key[0], left.get(key, '未提供此项'), right.get(key, '未提供此项'))
            for key in dict.fromkeys([*left, *right])]


def add_comparison_table(doc, headers, left_rows, right_rows, *, title=None,
                         left_label='Vinmin', right_label='Vinmax'):
    if title: module_section(doc, title, level=2, new_page=False)
    if headers[0]=='角点 / Vin' and len(headers)>=4:
        # IDs are global across Vin; the physical comparison key is the same
        # declared load vector. Retain each original ID/Vin as endpoint data.
        headers=[headers[1],headers[0],*headers[2:]]
        left_rows=[(row[1],row[0],*row[2:]) for row in left_rows]
        right_rows=[(row[1],row[0],*row[2:]) for row in right_rows]
    width = available_width(doc)
    rows = comparison_rows(headers, left_rows, right_rows)
    output_headers=[headers[0],left_label,right_label]
    widths=[width*.24,width*.38,width*.38]
    endpoint_columns=(1,2)
    # Long thresholds/ratings are common hardware or model conditions. Give
    # them one readable column instead of repeating them in both endpoint cells.
    if headers[0] in ('核查项','位号 / 检查项') and len(headers) in (4,6):
        def keyed(values):
            counts,result={},OrderedDict()
            for row in values:
                name=row[0];counts[name]=counts.get(name,0)+1
                result[name,counts[name]]=row
            return result
        a,b=keyed(left_rows),keyed(right_rows);rows=[]
        for key in dict.fromkeys([*a,*b]):
            pair=[a.get(key),b.get(key)]
            shared=[];cells=[[],[]]
            for j in range(1,len(headers)):
                values=[_cell_text(row[j]) if row else '未提供此项' for row in pair]
                common=j in ((2,) if len(headers)==4 else (2,4)) and values[0]==values[1]
                if common:shared.append(str(headers[j])+' '+values[0])
                else:
                    for k in (0,1):cells[k].append(str(headers[j])+' '+values[k])
            rows.append((key[0],'\n'.join(shared) or '两端条件分别列示',*['\n'.join(c) for c in cells]))
        output_headers=[headers[0],'共同阈值与额定条件',left_label,right_label]
        widths=[width*.22,width*.32,width*.23,width*.23];endpoint_columns=(2,3)
    result = table(doc, output_headers, rows, widths)
    # Endpoint colours belong to the comparison header, not document headings.
    for index,label in zip(endpoint_columns,('Vinmin','Vinmax')):
        for run in result.rows[0].cells[index].paragraphs[0].runs:
            _font(run, 10, True, 'FFFFFF')
        shade=result.rows[0].cells[index]._tc.get_or_add_tcPr().find(qn('w:shd'))
        if shade is not None: shade.set(qn('w:fill'), CASE_COLORS[label])
    return result


def add_paired_figure(doc, left_blob, right_blob, caption, *,
                      left_label='Vinmin', right_label='Vinmax', landscape=False):
    """Compare figures at readable physical scale and show missing evidence.

    Uses the current section width. On request, temporarily uses landscape
    Letter. Both supplied images are retained; no endpoint borrows the other.
    """
    from docx.enum.section import WD_SECTION_START, WD_ORIENT
    if landscape:
        sec=doc.add_section(WD_SECTION_START.NEW_PAGE)
        sec.orientation=WD_ORIENT.LANDSCAPE
        sec.page_width,sec.page_height=Inches(11),Inches(8.5)
    width=available_width(doc); each=width/2-.16
    grid=table(doc,[left_label,right_label],[['','']],[width/2,width/2])
    # docx_layout.table inserts a five-point spacer. The image row must stay
    # with that spacer AND its caption, otherwise Writer can orphan captions.
    spacer=grid._tbl.getnext()
    if spacer is not None and spacer.tag==qn('w:p'):
        spacer.get_or_add_pPr().append(OxmlElement('w:keepNext'))
    for index,label in enumerate(('Vinmin','Vinmax')):
        shade=grid.rows[0].cells[index]._tc.get_or_add_tcPr().find(qn('w:shd'))
        if shade is not None:shade.set(qn('w:fill'),CASE_COLORS[label])
    for i,(blob,label) in enumerate(((left_blob,left_label),(right_blob,right_label))):
        p=grid.rows[1].cells[i].paragraphs[0]
        p.alignment=WD_ALIGN_PARAGRAPH.CENTER
        p.paragraph_format.line_spacing=1.0
        p.paragraph_format.space_before=p.paragraph_format.space_after=Pt(0)
        p.paragraph_format.keep_with_next=True
        if blob:
            run=p.add_run();run.add_picture(BytesIO(blob),width=Inches(each))
            run._r.xpath('.//wp:docPr')[0].set('descr',label+' '+caption)
        else:
            _font(p.add_run(label+' 图像未提供'),11)
    p=doc.add_paragraph(caption,'Caption');p.alignment=WD_ALIGN_PARAGRAPH.CENTER
    if landscape:
        sec=doc.add_section(WD_SECTION_START.NEW_PAGE)
        sec.orientation=WD_ORIENT.PORTRAIT
        sec.page_width,sec.page_height=Inches(8.5),Inches(11)
    return p


def acceptance_snapshot(p, bundle=None, *, joint_record=None, spice_evidence=None):
    from engineering_acceptance import report_snapshot
    if spice_evidence is None and isinstance(bundle,dict):
        spice_evidence=bundle.get('engineering_acceptance_evidence')
    return report_snapshot(p, range_result=bundle, joint_record=joint_record,
                           spice_evidence=spice_evidence)


def acceptance_rows(snapshot):
    from engineering_acceptance import STATE_LABELS
    rows=[]
    compact={'pass':'满足','review':'需整改','undefined':'待补目标或证据','stale':'证据已失效','na':'不适用'}
    from report_docx import value as engineering_value
    for item in snapshot.get('rows',[]):
        unit=str(item.get('unit') or '')
        scale=100 if item.get('metric')=='eta' else 1
        if scale==100:unit='%'
        def number(value):
            return '—' if value is None else engineering_value(value*scale,unit)
        limit=item.get('limit')
        if item.get('comparison')=='range':
            criterion=number(item.get('lower'))+' 至 '+number(item.get('upper'))
        else:
            criterion=(item.get('comparison') or '')+' '+number(limit) if limit is not None else '待设置阈值'+(' / '+unit if unit else '')
        values=[]
        for case in ('Vinmin','Vinmax'):
            cell=(item.get('cases') or {}).get(case) or {}
            parts=[]
            for source,name in (('calculation','计算'),('simulation','仿真'),('measurement','实测')):
                value=cell.get(source)
                if isinstance(value,dict):
                    value=value.get('value')
                state=(cell.get('states') or {}).get(source,'undefined')
                if source!='calculation' and value is None:continue
                detail=name+' '+number(value)
                if state in ('review','stale'):detail+='  '+compact[state]
                if source=='simulation' and cell.get('delta_simulation') is not None:
                    detail+='  偏差 '+_cell_text(cell['delta_simulation'])+'%'
                elif source=='measurement' and cell.get('delta_measurement') is not None:
                    detail+='  偏差 '+_cell_text(cell['delta_measurement'])+'%'
                parts.append(detail)
            if cell.get('simulation') is None and cell.get('measurement') is None:parts.append('仿真 —   实测 —')
            elif cell.get('simulation') is None:parts.append('仿真 —')
            elif cell.get('measurement') is None:parts.append('实测 —')
            parts.append('结论 '+compact.get(cell.get('status'),'未评估'))
            if cell.get('margin') is not None:parts.append('最小裕量 '+number(cell['margin']))
            if cell.get('reason'):parts.append(str(cell['reason']))
            values.append('\n'.join(parts))
        rows.append((str(item.get('name') or item.get('metric') or item.get('id')),criterion,*values))
    return rows


def add_acceptance_report(doc,p,bundle=None,*,joint_record=None,spice_evidence=None,
                          title='工程验收',short_summary=False):
    snapshot=acceptance_snapshot(p,bundle,joint_record=joint_record,spice_evidence=spice_evidence)
    module_section(doc,title,level=1,new_page=False)
    summary=snapshot.get('summary') or {}
    paragraph(doc,'验收按需求阈值逐项对照设计计算、仿真与实测。缺少阈值或证据的项目保留未评估，'
              '不将仅完成计算写成整机验收通过。')
    if summary:
        from engineering_acceptance import STATE_LABELS
        counts=summary.get('counts') or {}
        lead=paragraph(doc,'当前结论  '+str(summary.get('label') or '待评估')+'；'+
            '，'.join(STATE_LABELS.get(k,k)+' '+str(v)+' 项' for k,v in counts.items())+
            '；未闭合问题 '+str(summary.get('unresolved_issues',0))+' 项。')
        color={'review':'A12D24','undefined':'8C5D16','stale':'8C5D16','pass':'29633B'}.get(summary.get('state'),'000000')
        for run in lead.runs:_font(run,11,True,color)
        if summary.get('scope'):paragraph(doc,str(summary['scope']),True)
    for note in snapshot.get('evidence_notes') or []:paragraph(doc,str(note),True)
    if short_summary:
        reviews=[]
        conditions={row[0]:row[1] for row in acceptance_rows(snapshot)}
        from report_docx import value
        for item in snapshot.get('rows',[]):
            pair=[(item.get('cases') or {}).get(k) or {} for k in ('Vinmin','Vinmax')]
            if not any(cell.get('status')=='review' for cell in pair):continue
            cells=[]
            for cell in pair:
                bad=[source for source in ('calculation','simulation','measurement')
                     if (cell.get('states') or {}).get(source)=='review']
                cells.append('；'.join(source+' '+value(cell.get(source),item.get('unit','')) for source in bad) or '该端未超限')
            name=item.get('name') or item.get('metric') or item.get('id')
            reviews.append((name,*cells,conditions.get(name,'待补目标')))
        if reviews:
            width=available_width(doc)
            table(doc,['已知超限项目','Vinmin','Vinmax','需求阈值'],reviews,[width*.29,width*.25,width*.25,width*.21])
    if not short_summary:
        width=available_width(doc)
        rows=acceptance_rows(snapshot)
        if rows:
            table(doc,['验收指标与证据','需求阈值','Vinmin','Vinmax'],rows,
                  [width*.28,width*.18,width*.27,width*.27])
        else:paragraph(doc,'尚未配置工程验收指标。请先补充允许范围与测量条件；现有设计核查不等同整机验收。')
        issues=snapshot.get('issues') or []
        if issues:
            module_section(doc,'未闭合问题',level=2,new_page=False)
            for issue in issues:
                paragraph(doc,'；'.join(str(issue[k]) for k in ('id','title','description','effective_status','evidence') if issue.get(k)))
    return snapshot


def capture_document(doc):
    """Capture native blocks and image bytes from the complete single-case author."""
    from docx.text.paragraph import Paragraph
    from docx.table import Table
    sections={key:OrderedDict() for key in MODULES}
    module,heading='overview','设计概览'
    for element in doc.element.body:
        block={'xml':deepcopy(element),'part':doc.part}
        if element.tag==qn('w:tbl'):
            t=Table(element,doc)
            widths=[float(c.width or 1) for c in t.columns]
            block.update(kind='table',rows=[[c.text for c in r.cells] for r in t.rows],
                         width_ratios=[w/sum(widths) for w in widths])
        elif element.tag==qn('w:p'):
            p=Paragraph(element,doc);text=p.text.strip()
            if p.style.name.startswith('Heading'):
                if text in ('当前工况完整设计核算','完整设计核算'):continue
                mapped=module_key(text)
                if mapped:module=mapped
                heading=text;sections[module].setdefault(heading,[]);continue
            if text.startswith('本部分所有参数、表格和波形对应'):continue
            images=[]
            for blip in element.xpath('.//a:blip'):
                rid=blip.get(qn('r:embed'))
                if rid:images.append(doc.part.related_parts[rid].blob)
            if images:block.update(kind='image',images=images)
            elif p.style.name=='Caption':block.update(kind='caption',text=text)
            elif element.xpath('.//m:oMath'):block.update(kind='equation',text=text)
            elif text or element.xpath('.//w:hyperlink'):block.update(kind='note',text=text)
            else:continue
        else:continue
        target_module,target_heading=module,heading
        if block['kind']=='table' and block['rows'][0][0]=='核查项':
            target_module,target_heading='review','完整设计核查明细'
        sections[target_module].setdefault(target_heading,[]).append(block)
    return sections


def block_pairs(left,right):
    def keyed(blocks):
        count,out={},OrderedDict()
        for block in blocks:
            kind=block['kind']
            key=(kind,tuple(block['rows'][0])) if kind=='table' else (kind,)
            count[key]=count.get(key,0)+1;out[key+(count[key],)]=block
        return out
    a,b=keyed(left),keyed(right)
    for key in dict.fromkeys([*a,*b]):yield a.get(key),b.get(key)


def _append_native(doc,block):
    node=deepcopy(block['xml'])
    for element in node.iter():
        for attr in (qn('r:id'),qn('r:embed'),qn('r:link')):
            rid=element.get(attr)
            if rid and rid in block['part'].rels:
                rel=block['part'].rels[rid]
                if rel.is_external:
                    new=doc.part.relate_to(rel.target_ref,rel.reltype,is_external=True)
                elif rel.reltype.endswith('/image'):
                    new,_=doc.part.get_or_add_image(BytesIO(rel.target_part.blob))
                else:continue
                element.set(attr,new)
    # Most captured pages become flowing module sections. The QR RCD review
    # is an intentional subsection: keep its explanation and corner table on
    # a fresh page instead of leaving one final row isolated on the next page.
    if not block.get('text','').startswith('QR固定RCD：'):
        for page_break in list(node.xpath('.//w:pageBreakBefore')):
            page_break.getparent().remove(page_break)
    if block['kind']=='equation':
        count=getattr(doc,'_equation_count',0)+1;doc._equation_count=count
        labels=node.xpath('./w:r/w:t')
        if labels and re.fullmatch(r'\(\d+\)',labels[-1].text or ''):
            labels[-1].text=f'({count})'
        ppr=node.get_or_add_pPr()
        for old in list(ppr.findall(qn('w:tabs'))):ppr.remove(old)
        tabs=OxmlElement('w:tabs');stop=OxmlElement('w:tab')
        stop.set(qn('w:val'),'right');stop.set(qn('w:pos'),str(round((available_width(doc)-.1)*1440)))
        tabs.append(stop);ppr.append(tabs)
    doc.element.body.insert(len(doc.element.body)-1,node)


def write_paired_modules(doc,contents,cases,*,chapter_start=2):
    """Same module first, then both endpoints; common prose/equations once."""
    if not any(contents[s][m] for s in (0,1) for m in MODULES):
        return dict(paired_tables=0,paired_figures=0,chapters=0)
    from docx.enum.section import WD_SECTION_START, WD_ORIENT
    sec=doc.add_section(WD_SECTION_START.NEW_PAGE)
    sec.orientation=WD_ORIENT.LANDSCAPE
    sec.page_width,sec.page_height=Inches(11),Inches(8.5)
    pictures=0;tables=0;chapter=chapter_start
    for name,modules in CHAPTERS:
        if not any(contents[s][m] for s in (0,1) for m in modules):continue
        module_section(doc,f'{chapter} {name}',new_page=chapter!=chapter_start);chapter+=1
        for module in modules:
            left,right=contents[0][module],contents[1][module]
            for heading in dict.fromkeys([*left,*right]):
                title=re.sub(r'^(?:\d+(?:\.\d+)*\s*|附录\s*[AB]\s*)','',heading).strip()
                module_section(doc,title,level=2,new_page=False)
                pairs=list(block_pairs(left.get(heading,[]),right.get(heading,[])))
                pending_caption=None
                for index,(a,b) in enumerate(pairs):
                    sample=a or b;kind=sample['kind']
                    if kind=='caption':continue
                    if kind=='image':
                        caption=next(((x or y).get('text','') for x,y in pairs[index+1:index+2]
                                      if (x or y)['kind']=='caption'),'两端点图像对照')
                        n=max(len(a['images']) if a else 0,len(b['images']) if b else 0)
                        for j in range(n):
                            if caption.startswith('图 0-1'):
                                # Dense circuit designators need one full-width
                                # engineering view per endpoint; a small pair
                                # would force unreadable labels. Same module,
                                # adjacent endpoint figures, all data retained.
                                from docx_layout import figure
                                for block,case in ((a,cases[0]),(b,cases[1])):
                                    label=paragraph(doc,case['id']+' '+str(case['voltage'])+' V')
                                    label.paragraph_format.keep_with_next=True
                                    if block and j<len(block['images']):
                                        figure(doc,block['images'][j],case['id']+' '+caption,width=min(8.4,available_width(doc)))
                                        pictures+=1
                                    else:paragraph(doc,'本端拓扑图未提供')
                                continue
                            add_paired_figure(doc,a['images'][j] if a and j<len(a['images']) else None,
                                b['images'][j] if b and j<len(b['images']) else None,
                                caption,left_label=cases[0]['id']+' '+str(cases[0]['voltage'])+' V',
                                right_label=cases[1]['id']+' '+str(cases[1]['voltage'])+' V')
                            pictures+=int(bool(a))+int(bool(b))
                    elif kind=='table':
                        if a and b and a['rows']==b['rows']:
                            width=available_width(doc);cols=len(a['rows'][0])
                            # Common hardware/model tables appear once.
                            ratios=a.get('width_ratios') or [1/cols]*cols
                            table(doc,a['rows'][0],a['rows'][1:],[width*r for r in ratios])
                        else:
                            add_comparison_table(doc,sample['rows'][0],a['rows'][1:] if a else [],
                                                 b['rows'][1:] if b else [])
                        tables+=1
                    elif a and b and a['xml'].xml==b['xml'].xml:
                        _append_native(doc,a)
                    else:
                        # Identical equations carry independent original
                        # counters/relationships. Compare the native math XML,
                        # not a rendered plain-text transcription.
                        same_math=kind=='equation' and a and b and [x.xml for x in a['xml'].xpath('.//m:oMath')]==[x.xml for x in b['xml'].xpath('.//m:oMath')]
                        if same_math:_append_native(doc,a)
                        else:
                            for block,case in ((a,cases[0]),(b,cases[1])):
                                if block:
                                    p=doc.add_paragraph();_font(p.add_run(case['id']),9,True,CASE_COLORS[case['id']])
                                    p.paragraph_format.keep_with_next=True
                                    _append_native(doc,block)
                    if (a is None or b is None) and kind not in ('image','caption'):
                        absent=cases[0] if a is None else cases[1]
                        if absent.get('error') or not absent.get('result'):
                            paragraph(doc,absent['id']+' 本工况不可用  '+str(absent.get('error') or '没有有效计算结果'),True)
    return dict(paired_tables=tables,paired_figures=pictures,chapters=chapter-chapter_start)
