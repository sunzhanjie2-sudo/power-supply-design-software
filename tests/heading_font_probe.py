"""Small internal rendering probe for inherited East Asian heading themes."""
from pathlib import Path
import sys
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from docx_layout import new_document
from docx.oxml.ns import qn
from docx.oxml import OxmlElement

doc = new_document('字体兼容核对', '仅供内部排版核对', '字体核对')
doc.add_heading('输入范围与评审结论 — 原样式', 1)
doc.add_heading('关键结果并列摘要 — 原样式', 2)
for level, size in ((1, 17), (2, 13)):
    style = doc.styles.add_style('ExplicitHeading'+str(level), 1)
    style.base_style = doc.styles['Heading '+str(level)]
    prop = style.element.get_or_add_rPr()
    fonts = prop.get_or_add_rFonts()
    for key in ('ascii', 'hAnsi', 'eastAsia', 'cs'):
        fonts.set(qn('w:'+key), 'Microsoft YaHei')
    for key in ('asciiTheme', 'hAnsiTheme', 'eastAsiaTheme', 'cstheme'):
        fonts.set(qn('w:'+key), '')
    size_cs = OxmlElement('w:szCs'); size_cs.set(qn('w:val'), str(size*2)); prop.append(size_cs)
    doc.add_paragraph('输入范围与评审结论 — 明确字体', style)
    doc.add_paragraph('关键结果并列摘要 — 明确字体', style)
doc.save('_tmp_input_range_qa/heading_probe.docx')
