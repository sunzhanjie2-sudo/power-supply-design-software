"""QA fixture for literal math subscripts in Word and LibreOffice."""
from pathlib import Path
import sys
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from docx_layout import new_document,equation,paragraph
from word_math import element,run,script

def build():
    doc=new_document('数学下标兼容性检查','仅供排版验证','数学测试')
    for mode in ('style','lit','nor','split'):
        paragraph(doc,mode)
        def label(text):
            r=run(text,True)
            if mode in ('lit','nor'):
                r.find('{http://schemas.openxmlformats.org/officeDocument/2006/math}rPr').append(element(mode))
            return [r] if mode!='split' else [run(c,True) for c in text]
        math=element('oMath',*script([run('P')],label('cap,in')),run('='),
            *script([run('I')],label('in,est')),run('+'),*script([run('P')],label('in,final')))
        doc.add_paragraph()._p.append(math)
    out=Path('_tmp_coupled_word_qa/math_literal_fixture.docx')
    doc.save(out)
    print(out.resolve())

if __name__=='__main__':build()
