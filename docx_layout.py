"""Shared, lazy-loaded Word layout for engineering reports and the reference."""
from io import BytesIO

from docx import Document
from docx.shared import Inches, Pt, RGBColor
from docx.enum.text import WD_ALIGN_PARAGRAPH
from docx.enum.table import WD_TABLE_ALIGNMENT, WD_CELL_VERTICAL_ALIGNMENT
from docx.oxml import OxmlElement
from docx.oxml.ns import qn

FONT = 'Microsoft YaHei'
INK = '17365D'


def _font(run, size=11, bold=False, color='000000'):
    run.font.name = FONT
    run.font.size = Pt(size)
    run.font.bold = bold
    run.font.color.rgb = RGBColor.from_string(color)
    prop = run._element.get_or_add_rPr()
    fonts = prop.get_or_add_rFonts()
    fonts.set(qn('w:eastAsia'), FONT)
    fonts.set(qn('w:cs'), FONT)
    # Small notes/table text must not inherit the Normal style's larger
    # complex-script size after the explicit-font compatibility correction.
    size_cs = prop.find(qn('w:szCs'))
    if size_cs is None:
        size_cs = OxmlElement('w:szCs'); prop.append(size_cs)
    size_cs.set(qn('w:val'), str(size*2))


def new_document(title, subtitle, running_title):
    from design_theme import is_pcs,report_name
    pcs = is_pcs()
    if pcs and report_name(): title='PCS 辅源设计报告 '+report_name()
    doc = Document()
    sec = doc.sections[0]
    sec.page_width, sec.page_height = Inches(8.5), Inches(11)
    sec.top_margin, sec.bottom_margin = Inches(.7), Inches(.65)
    sec.left_margin = sec.right_margin = Inches(.7)
    sec.header_distance = sec.footer_distance = Inches(.3)
    for name, size in [('Normal',11), ('Title',26), ('Subtitle',11),
                       ('Heading 1',17), ('Heading 2',13), ('Heading 3',11),
                       ('Caption',9)]:
        s = doc.styles[name]
        s.font.name, s.font.size = FONT, Pt(size)
        s.font.color.rgb = RGBColor(0,0,0)
        rpr = s.element.get_or_add_rPr()
        fonts = rpr.get_or_add_rFonts()
        # The stock template retains major/minor theme fonts. Some DOCX
        # renderers then mix CJK fallback glyphs with YaHei at the wrong
        # advances (overprinted headings). Use explicit fonts for all scripts.
        for attr in ('asciiTheme', 'hAnsiTheme', 'eastAsiaTheme', 'cstheme'):
            fonts.attrib.pop(qn('w:'+attr), None)
        for attr in ('ascii', 'hAnsi', 'eastAsia', 'cs'):
            fonts.set(qn('w:'+attr), FONT)
        size_cs = rpr.find(qn('w:szCs'))
        if size_cs is None:
            size_cs = OxmlElement('w:szCs'); rpr.append(size_cs)
        size_cs.set(qn('w:val'), str(size*2))
        s.paragraph_format.space_after = Pt(6)
        s.paragraph_format.line_spacing = 1.12
        s.paragraph_format.widow_control = True
        if name.startswith('Heading'):
            s.font.bold = True
            s.paragraph_format.space_before = Pt(12)
            s.paragraph_format.keep_with_next = True
    # The bundled default template can carry decorative paragraph borders.
    # Strip them explicitly rather than inheriting a rule below the title.
    for border in list(doc.styles.element.xpath('.//w:pBdr')):
        border.getparent().remove(border)
    doc.styles['Title'].paragraph_format.space_after = Pt(12)
    h = sec.header.paragraphs[0]
    _font(h.add_run(('PCS 技术货架  /  辅源工作区  /  ' if pcs else '')+running_title),8)
    f = sec.footer.paragraphs[0]
    f.alignment = WD_ALIGN_PARAGRAPH.RIGHT
    _font(f.add_run('研发设计评审  ·  '),8)
    field = OxmlElement('w:fldSimple')
    field.set(qn('w:instr'),'PAGE')
    f._p.append(field)
    doc.core_properties.title = title
    doc.core_properties.author = 'PCS 技术货架' if pcs else '开关电源设计与环路分析工具'
    doc.core_properties.subject = '计算结果、设计核查与模型边界'
    tp=doc.add_paragraph(title,'Title')
    for run in tp.runs: _font(run,26)
    sp=doc.add_paragraph(subtitle,'Subtitle')
    for run in sp.runs:
        _font(run,11); run.font.italic=False
    return doc


def paragraph(doc, text, small=False):
    p = doc.add_paragraph()
    _font(p.add_run(text),9 if small else 11)
    return p


def table(doc, headers, rows, widths=None, math_columns=()):
    """Real data tables only: fixed widths, repeated header, no split rows."""
    t = doc.add_table(rows=1, cols=len(headers))
    t.alignment = WD_TABLE_ALIGNMENT.CENTER
    t.autofit = False
    widths = widths or [7.1/len(headers)]*len(headers)
    for col,w in zip(t.columns,widths):
        col.width = Inches(w)
    pr = t._tbl.tblPr
    borders = OxmlElement('w:tblBorders')
    for edge in ('top','left','bottom','right','insideH','insideV'):
        e = OxmlElement('w:'+edge)
        for k,v in [('val','single'),('sz','4'),('color','D9D9D9')]:
            e.set(qn('w:'+k),v)
        borders.append(e)
    pr.append(borders)
    layout = OxmlElement('w:tblLayout')
    layout.set(qn('w:type'),'fixed')
    pr.append(layout)
    all_rows = [headers]+list(rows)
    for i,vals in enumerate(all_rows):
        row = t.rows[0] if i==0 else t.add_row()
        rpr = row._tr.get_or_add_trPr()
        rpr.append(OxmlElement('w:cantSplit'))
        if i==0:
            rpr.append(OxmlElement('w:tblHeader'))
        for j,(cell,val,w) in enumerate(zip(row.cells,vals,widths)):
            cell.width = Inches(w)
            cell.vertical_alignment = WD_CELL_VERTICAL_ALIGNMENT.CENTER
            cp = cell._tc.get_or_add_tcPr()
            sh = OxmlElement('w:shd')
            from design_theme import is_pcs
            sh.set(qn('w:fill'),('0D1726' if is_pcs() else INK) if i==0 else ('F3F6FA' if is_pcs() and i%2 else 'F1F4F8' if i%2 else 'FFFFFF'))
            cp.append(sh)
            margins = OxmlElement('w:tcMar')
            for edge,amount in [('top',65),('bottom',65),('left',90),('right',90)]:
                e=OxmlElement('w:'+edge); e.set(qn('w:w'),str(amount)); e.set(qn('w:type'),'dxa'); margins.append(e)
            cp.append(margins)
            p = cell.paragraphs[0]
            p.paragraph_format.space_after = Pt(0)
            p.paragraph_format.line_spacing = Pt(13.5)
            if i==0:
                p.paragraph_format.keep_with_next = True
            if i==0 or (j>0 and len(str(val))<22):
                p.alignment = WD_ALIGN_PARAGRAPH.CENTER
            if i > 0 and j in math_columns:
                from word_math import math_nodes, element
                # Exact line height clips stacked numerators/denominators.
                p.paragraph_format.line_spacing = 1.0
                p.paragraph_format.space_before = Pt(0)
                p.paragraph_format.space_after = Pt(0)
                math = element('oMath', *math_nodes(str(val)))
                for run in math.iter(qn('m:r')):
                    props = run.find(qn('w:rPr'))
                    if props is None:
                        props = OxmlElement('w:rPr'); run.insert(1, props)
                    size = OxmlElement('w:sz'); size.set(qn('w:val'), '20')
                    props.append(size)
                p._p.append(math)
            else:
                _font(p.add_run(str(val)),10,i==0,'FFFFFF' if i==0 else '000000')
    gap=doc.add_paragraph()
    gap.paragraph_format.space_before=gap.paragraph_format.space_after=Pt(0)
    gap.paragraph_format.line_spacing=Pt(5)
    _font(gap.add_run(''),1)
    return t


def figure(doc, blob, caption, width=7.1):
    p = doc.add_paragraph()
    p.alignment = WD_ALIGN_PARAGRAPH.CENTER
    p.paragraph_format.keep_with_next = True
    p.paragraph_format.space_after = Pt(3)
    run=p.add_run()
    run.add_picture(BytesIO(blob),width=Inches(width))
    alt = run._r.xpath('.//wp:docPr')
    if alt:
        alt[0].set('descr',caption)
    p = doc.add_paragraph(caption,'Caption')
    p.alignment = WD_ALIGN_PARAGRAPH.CENTER


def figure_pair(doc,left,right,caption):
    p=doc.add_paragraph()
    p.alignment=WD_ALIGN_PARAGRAPH.CENTER
    p.paragraph_format.keep_with_next=True
    for i,blob in enumerate((left,right)):
        if i: p.add_run('  ')
        run=p.add_run(); run.add_picture(BytesIO(blob),width=Inches(3.3))
        run._r.xpath('.//wp:docPr')[0].set('descr',caption+('（左）' if i==0 else '（右）'))
    p=doc.add_paragraph(caption,'Caption')
    p.alignment=WD_ALIGN_PARAGRAPH.CENTER


def equation(doc, text, numerator=None, denominator=None):
    """Numbered structured OMML: scripts, fractions, radicals and operators."""
    from word_math import math_nodes, element
    from docx.enum.text import WD_TAB_ALIGNMENT
    p = doc.add_paragraph()
    p.paragraph_format.space_after=Pt(4)
    p.paragraph_format.line_spacing=1.0
    import re
    label = re.match(r'^(.*?[：:])\s*(.*)$', text)
    if label:
        _font(p.add_run(label[1]+' '),11)
        text=label[2]
    m=element('oMath', *math_nodes(text))
    if numerator is not None:
        m.append(element('f', element('num', *math_nodes(numerator)),
                         element('den', *math_nodes(denominator))))
    p._p.append(m)
    count=getattr(doc, '_equation_count', 0)+1
    doc._equation_count=count
    p.paragraph_format.tab_stops.add_tab_stop(Inches(7.0), WD_TAB_ALIGNMENT.RIGHT)
    _font(p.add_run(f'\t({count})'),9)
    return p


def section(doc,title):
    p=doc.add_heading(title,1)
    from design_theme import is_pcs
    p.paragraph_format.page_break_before=not is_pcs()
    return p
