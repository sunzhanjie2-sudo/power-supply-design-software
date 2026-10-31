"""Module-per-sheet Excel reports for the same two solved input endpoints.

Reuses the existing engineering-report authoring path in memory, so the Excel
and Word versions cannot drift to different loss, ripple or compensation
formulas. No intermediate Word file is written. Only the final XLSX is saved.
"""
from collections import OrderedDict
import math
import re

from xlsx_report_writer import (Sheet, WIDTHS, SIDE_PX, fitted_height,
                                numeric_text, number_format, save_workbook)


MODULES = OrderedDict([
    ('overview', '01 需求与工况总览'), ('topology', '02 拓扑与多路输出'),
    ('power', '03 功率级与开关波形'), ('devices', '04 功率器件与损耗'),
    ('caps', '05 电容纹波'), ('magnetics', '06 磁件与绕制'),
    ('loop', '07 环路与补偿电路'), ('clamp', '08 钳位与复位'),
    ('efficiency', '09 损耗与效率'), ('psr', '10 MP6005 PSR'),
    ('review', '11 模型与评审'), ('inputs', '12 输入参数快照'),
    ('cross_regulation', '13 交叉调整率'),
    ('bom', '14 关键器件BOM与降额'),
])


def _module(title):
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


def _math_text(element):
    """Readable equation descriptions, not misleading executable cell formulas."""
    local = element.tag.rsplit('}',1)[-1]
    children = {child.tag.rsplit('}',1)[-1]:child for child in element}
    def part(name):
        child = children.get(name)
        return '' if child is None else _math_text(child)
    def property_value(group, name, default):
        properties = children.get(group)
        if properties is not None:
            for child in properties:
                if child.tag.rsplit('}',1)[-1] == name:
                    return next((v for k,v in child.attrib.items() if k.endswith('}val')),default)
        return default
    if local in ('t',): return element.text or ''
    if local == 'f': return '('+part('num')+')/('+part('den')+')'
    if local == 'sSub': return part('e')+'_{'+part('sub')+'}'
    if local == 'sSup': return part('e')+'^('+part('sup')+')'
    if local == 'sSubSup': return part('e')+'_{'+part('sub')+'}^('+part('sup')+')'
    if local == 'd':
        expressions = [_math_text(child) for child in element if child.tag.rsplit('}',1)[-1] == 'e']
        return property_value('dPr','begChr','(')+property_value('dPr','sepChr',',').join(expressions)+property_value('dPr','endChr',')')
    if local == 'nary':
        return (property_value('naryPr','chr','∑')+('_{'+part('sub')+'}' if part('sub') else '')
                +('^('+part('sup')+')' if part('sup') else '')+' '+part('e'))
    if local == 'rad':
        return ('root['+part('deg')+']' if part('deg') else 'sqrt')+'('+part('e')+')'
    return ''.join(_math_text(child) for child in element if not child.tag.endswith('Pr'))


def _capture_document(doc):
    """Extract ordered content blocks without rasterizing tables or equations."""
    from docx.oxml.ns import qn
    from docx.text.paragraph import Paragraph
    from docx.table import Table
    sections = {key:OrderedDict() for key in MODULES}
    module, section = 'overview', '设计概览'
    def add(block):
        sections[module].setdefault(section, []).append(block)
    for element in doc.element.body:
        if element.tag == qn('w:tbl'):
            t = Table(element, doc)
            add(dict(kind='table', rows=[[c.text for c in row.cells] for row in t.rows]))
            continue
        if element.tag != qn('w:p'): continue
        p = Paragraph(element, doc)
        text = p.text.strip()
        if p.style.name.startswith('Heading'):
            if text == '当前工况完整设计核算': continue
            new_module = _module(text)
            if new_module is not None: module = new_module
            section = text
            sections[module].setdefault(section, [])
        elif p.style.name == 'Caption':
            add(dict(kind='caption', text=text))
        elif element.xpath('.//m:oMath'):
            equations = '； '.join(_math_text(e) for e in element.xpath('.//m:oMath'))
            lead = re.sub(r'\s*\(\d+\)\s*$', '', text).strip()
            add(dict(kind='equation', text=(lead+' ' if lead else '')+equations))
        elif element.xpath('.//a:blip'):
            pictures = []
            for blip in element.xpath('.//a:blip'):
                rid = blip.get(qn('r:embed'))
                if rid: pictures.append(doc.part.related_parts[rid].blob)
            if pictures: add(dict(kind='image', images=pictures))
        elif text:
            if text.startswith('本部分所有参数、表格和波形对应'): continue
            text = text.replace('上述为原生 Word 数学对象。', '上述为公式文本；Word 报告使用原生数学对象。')
            add(dict(kind='note', text=text))
        else:
            # Hyperlink-only paragraphs (for example the PSR source link).
            link_text = ''.join(element.xpath('.//w:hyperlink//w:t/text()'))
            if link_text: add(dict(kind='note', text=link_text))
    return sections


def _spans(count):
    # Every report table currently has at most eight columns. Never silently
    # omit data if a future module exceeds the reserved comparison-panel width.
    if not 1 <= count <= 8:
        raise ValueError(f'Excel 报告表格有 {count} 列，需调整模块布局后导出')
    if count == 2: return [3,5]
    if count == 3: return [3,2,3]
    if count == 4: return [2,2,2,2]
    result = [1]*count
    result[0] += 8-count
    return result


def _write_block(sheet, row, offset, block, label):
    kind = block['kind']
    if kind == 'table':
        spans = _spans(len(block['rows'][0]))
        if len(block['rows'][0])==5 and block['rows'][0][1]=='直流范围 / V':
            spans=[1,2,2,1,2]
        for i, values in enumerate(block['rows']):
            col = offset
            for j, (text, span) in enumerate(zip(values, spans)):
                value, fmt = (str(text), None) if i == 0 else numeric_text(text)
                style = (2 if label == 'Vinmin' else 3) if i == 0 else (6 if i%2 else 0)
                sheet.span(row+i, col, span, value, style, fmt)
                width = sum(WIDTHS[col:col+span])
                height = fitted_height(text, width)
                sheet.heights[row+i] = max(sheet.heights.get(row+i,24),height)
                col += span
        return len(block['rows'])+1
    if kind == 'image':
        blobs = block['images']; width = (SIDE_PX-12*(len(blobs)-1))/len(blobs)
        height = max(sheet.image(row,offset,blob,label+' 工程图',width,index*(width+12))
                     for index, blob in enumerate(blobs))
        rows = math.ceil((height+12)/32)
        for r in range(row,row+rows): sheet.heights[r] = max(sheet.heights.get(r,24),24)
        return rows
    text = block.get('text','')
    style = 4 if kind == 'caption' else 9 if kind == 'equation' else 7
    sheet.span(row, offset, 8, text, style)
    height = fitted_height(text, sum(WIDTHS[offset:offset+8]))
    sheet.heights[row] = max(sheet.heights.get(row,24),height)
    return 2


def _block_pairs(left, right):
    """Pair like content even when one endpoint lacks a table/plot/model."""
    def keyed(blocks):
        counters, out = {}, OrderedDict()
        for block in blocks:
            kind = block['kind']
            key = (kind, tuple(block['rows'][0])) if kind == 'table' else (kind,)
            counters[key] = counters.get(key,0)+1
            out[key+(counters[key],)] = block
        return out
    a,b = keyed(left),keyed(right)
    for key in dict.fromkeys([*a,*b]): yield a.get(key),b.get(key)


def _headers(sheet, cases, note):
    sheet.heights.update({1:12, 2:34, 3:36, 4:30})
    sheet.span(2,0,17,sheet.name,1)
    sheet.span(3,0,17,note,7)
    for offset, case in zip((0,9),cases):
        text = case['id']+f"  输入 {case['voltage']:.8g} V"
        if case.get('error') or not case.get('result'): text += '  计算不可用'
        sheet.span(4,offset,8,text,2 if offset == 0 else 3)


def export_input_range_xlsx(path, range_result, *, compensation_state=None,
                            mos_real_time=False, comparison=None, corners=None):
    """Write an offline XLSX report; never change parameters or auto-tune.

    Every worksheet compares independently calculated Vinmin and Vinmax data.
    The workbook is a report snapshot, not a second implementation of the
    switching solver. Graphs and mathematical descriptions use the Word
    report's exact source. Numeric single quantities remain numeric in Excel.
    """
    by_id = {case['id']:case for case in range_result.get('cases',[])}
    if len(range_result.get('cases',[])) != 2 or set(by_id) != {'Vinmin','Vinmax'}:
        raise ValueError('输入范围报告必须包含 Vinmin 与 Vinmax 两个具名工况')
    cases = [by_id[key] for key in ('Vinmin','Vinmax')]
    from docx import Document
    from report_docx import export_design_docx, _chart
    from input_range_report import _metrics, METRICS, _worse, _draw_comparison
    content, details = [], []
    for case in cases:
        if case.get('error') or not case.get('result'):
            content.append({key:OrderedDict() for key in MODULES}); continue
        res = case['result']; doc = Document()
        details.append(export_design_docx('',case['p'],res['op'],res['wf'],res,
            models=case.get('models'),loop_error=case.get('loop_error'),
            corners=case.get('corners') or (corners if case['id']=='Vinmin' else None),
            comparison=comparison if case['id']=='Vinmin' else None,
            mos_real_time=mos_real_time,efficiency_curve=case.get('efficiency_curve'),
            compensation_state=compensation_state,document=doc,save=False))
        content.append(_capture_document(doc))
        del doc
    fixed = bool(range_result.get('fixed_hardware',range_result.get('hardware')))
    common = '导出时的计算快照，修改单元格不会重算模型。左侧 Vinmin，右侧 Vinmax。'
    common += '磁件与绕组按 Vinmin 固定，补偿不单独整定。' if fixed else '未固定有效磁件，报告不完整。'
    if cases[0]['voltage'] == cases[1]['voltage']:
        from mos_manual import distinct_endpoints
        common += '上下限相同，但手动 MOS 事件参数不同，分别核算。' if distinct_endpoints(range_result['base_spec']) else '上下限相同，两端结果一致。'
    if len(details) != 2: common += '存在失败工况，不以另一端点替代。'
    sheets = []
    for module, name in MODULES.items():
        left,right = content[0][module],content[1][module]
        if module != 'overview' and not left and not right: continue
        sheet = Sheet(name); _headers(sheet,cases,common)
        row, page_start = 6, 6
        if module == 'overview':
            metrics = [_metrics(case) for case in cases]
            for index, (key,label,unit,scale,direction) in enumerate(METRICS):
                vals = [m.get(key) for m in metrics]
                worse = _worse(vals[0], vals[1], direction)
                sheet.heights[row] = 30
                for side, value in enumerate(vals):
                    offset = side*9
                    sheet.span(row,offset,4,label,6 if index%2 else 0)
                    valid = value is not None and math.isfinite(float(value))
                    numeric = value if valid else '未定义'
                    fmt = number_format(value,unit) if valid else None
                    sheet.span(row,offset+4,2,numeric,6 if index%2 else 0,fmt if valid else None)
                    sheet.span(row,offset+6,2,'较不利端' if worse == cases[side]['id'] else worse if worse in ('两端相同','未完整计算') else '',7)
                row += 1
            sheet.span(row+1,0,17,'较不利端仅比较这两个输入端点，不代表全输入区间、所有负载或温度容差已经通过。',7)
            sheet.heights[row+1]=30; row+=3
            from mos_four_cases import event_rows
            if any((c.get('result') or {}).get('semi',{}).get('switch',{}).get('gate') for c in cases):
                sheet.span(row,0,17,'MOS 四开关事件的电压与电荷',4);row+=2
                used=0
                for side,case in enumerate(cases):
                    rows=event_rows(dict(cases=[case]))
                    header=['事件','Id / A','Vgp / V','Qgs / nC','Qgd / nC','Qg(th) / nC','总Qg / nC']
                    values=[[r[1]]+[f'{v*(1e9 if i>=4 else 1):.6g}' if isinstance(v,(int,float)) else v for i,v in enumerate(r[2:],2)] for r in rows]
                    used=max(used,_write_block(sheet,row,side*9,dict(kind='table',rows=[header,*values]),case['id']))
                row+=used
                sheet.span(row,0,17,'Qgs 为到平台电荷，Qgd 为平台段电荷差。复用同一 Vgs–Qg 参考曲线时，Qgd / Qg(th) / 总 Qg 可能相同；不强制改出四个不同数值。',7)
                sheet.heights[row]=38;row+=3
            if details:
                blob = _chart((14.2,5.2),lambda fig:_draw_comparison(fig,cases))
                height=sheet.image(row,0,blob,'双端点同轴对比',SIDE_PX*2+26)
                used=math.ceil((height+12)/32)
                for r in range(row,row+used): sheet.heights[r]=24
                row+=used+2
        for title in dict.fromkeys([*left,*right]):
            # Keep corresponding subsection starts at identical vertical rows.
            if sum(sheet.heights.get(r,24) for r in range(page_start,row)) > 520:
                sheet.breaks.append(row); page_start=row
            for side in (0,1): sheet.span(row,side*9,8,title,4)
            sheet.heights[row]=30; row+=2
            for a,b in _block_pairs(left.get(title,[]),right.get(title,[])):
                used=0
                for side, block in enumerate((a,b)):
                    if block:
                        used=max(used,_write_block(sheet,row,side*9,block,cases[side]['id']))
                    elif cases[side].get('error') or not cases[side].get('result'):
                        # One unmistakable failure note per section, not fake 0s.
                        pass
                row+=used
        for side,case in enumerate(cases):
            if case.get('error') or not case.get('result'):
                sheet.span(5,side*9,8,'本工况计算不可用：'+str(case.get('error') or '没有有效结果'),8)
                sheet.heights[5]=max(sheet.heights.get(5,24),fitted_height(str(case.get('error','')),100))
        sheets.append(sheet)
    save_workbook(path,sheets)
    failed=[case['id'] for case in cases if case.get('error') or not case.get('result')]
    cross = range_result.get('cross_regulation')
    cross_incomplete = bool(cross and cross.get('supported') and not cross.get('complete'))
    return dict(path=str(path),case_count=2,successful_cases=2-len(failed),failed_cases=failed,
                incomplete=bool(failed) or not fixed or cross_incomplete,hardware_fixed=fixed,
                cross_regulation_complete=cross.get('complete') if cross else None,
                sheet_count=len(sheets),sheet_names=[sheet.name for sheet in sheets],
                figure_count=sum(len(sheet.images) for sheet in sheets),
                check_count=sum(detail['checks'] for detail in details))
