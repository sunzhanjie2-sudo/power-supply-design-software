"""Structural, provenance and independent arithmetic checks for the tutorial."""
from pathlib import Path
import hashlib
import json
import math
from zipfile import ZipFile
from lxml import etree
from pypdf import PdfReader

ROOT=Path(__file__).resolve().parents[2]
ART=ROOT/'artifacts/tutorials/multi_flyback_20261023'
DOC=Path(__file__).with_name('多路反激电源设计入门教程.docx')
d=json.loads((ART/'tutorial_data.json').read_text(encoding='utf-8'))


def close(a,b):
    assert math.isclose(a,b,rel_tol=1e-9,abs_tol=1e-12),(a,b)


def main():
    for c in d['cases']:
        r=c['result'];g=c['display']['switch_loss']['gate'];sw=c['display']['switch_loss']
        close(r['eta'],r['P_out']/(r['P_out']+r['P_total']))
        close(r['P_total'],sum(r[k] for k in ('P_semi','P_mag','P_cap','P_cap_in',
                    'P_sense','P_rcd','P_din','P_dout','P_clamp','P_controller')))
        close(sw['P_cond'],.05*r['op']['I_sw_rms']**2)
        close(sw['P_sw_on'],.25*r['op']['V_sw_max']*g['I_on']*(sw['t2']+sw['t3'])*250000)
        close(sw['P_sw_off'],.25*r['op']['V_sw_max']*g['I_off']*(sw['t6']+sw['t7'])*250000)
        tr=c['display']['magnetics'][0]
        close(tr['R_dc_p'],1.72e-8*.04*6/(40*math.pi*.0001**2/4))
        close(tr['dT'],tr['P_total']*100)
        close(c['display']['rcd']['R_snub'],23.025**2/r['P_rcd'])
        for out in c['display']['outputs']:
            close(out['P_cap'],sum(x['ESR']*x['total']**2 for x in out['capacitors']['output']['caps']))
        for j,minimum in enumerate(d['cross_regulation']['summary']):
            close(minimum['V_min'],min(x['voltages'][j] for x in d['cross_regulation']['cases']))
            close(minimum['V_max'],max(x['voltages'][j] for x in d['cross_regulation']['cases']))
    ref=ROOT/'docs/reference/计算方法与公式说明.docx'
    assert hashlib.sha256(ref.read_bytes()).hexdigest()==d['original_reference_sha256']
    src=Path(__file__).resolve().parents[2]/'examples/40W_CCM_3OUT_FLYBACK.json'
    assert hashlib.sha256(src.read_bytes()).hexdigest()==d['source']['sha256']
    ns={'m':'http://schemas.openxmlformats.org/officeDocument/2006/math',
        'w':'http://schemas.openxmlformats.org/wordprocessingml/2006/main'}
    with ZipFile(DOC) as z:
        assert z.testzip() is None
        x=etree.fromstring(z.read('word/document.xml'))
        maths=x.findall('.//m:oMath',ns)
        assert len(maths)==110
        assert not any('_' in (t.text or '') for m in maths for t in m.findall('.//m:t',ns))
        assert len(x.findall('.//m:f',ns))>70
        assert len(x.findall('.//m:m',ns))==1
        assert not x.findall('.//w:pBdr',ns)
        assert not x.findall('.//w:ins',ns) and not x.findall('.//w:del',ns)
        # Regression checks for composed denominators and event subscripts.
        cap=next(m for m in maths if ''.join(m.itertext()).startswith('Cmin'))
        assert any('ΔV' in ''.join(v.itertext()) for v in cap.findall('.//m:den',ns))
        assert any('gd,on' in ''.join(v.itertext()) for m in maths for v in m.findall('.//m:sub',ns))
        assert any('gd,off' in ''.join(v.itertext()) for m in maths for v in m.findall('.//m:sub',ns))
        linear=next(m for m in maths if ''.join(m.itertext()).startswith('Ad'))
        assert any('∂x' in ''.join(v.itertext()) for v in linear.findall('.//m:den',ns))
        assert any('∂d' in ''.join(v.itertext()) for v in linear.findall('.//m:den',ns))
        assert any('outer' == ''.join(v.itertext()) for m in maths for v in m.findall('.//m:sub',ns))
    pdf=PdfReader(ART/'render_verified/多路反激电源设计入门教程.pdf')
    chars=[len(p.extract_text()) for p in pdf.pages]
    assert min(chars)>30
    images=list((ART/'render_verified').glob('page-*.png'))
    assert len(images)==len(pdf.pages)
    result=dict(passed=True,pages=len(pdf.pages),native_math_objects=len(maths),
                original_document_unchanged=True,source_json_unchanged=True,
                arithmetic='loss ledger, efficiency, MOS loss, DCR, thermal, clamp RC, capacitor ESR, corner extrema',
                word_sha256=hashlib.sha256(DOC.read_bytes()).hexdigest())
    (ART/'verification.json').write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf-8')
    print(json.dumps(result,ensure_ascii=False))


if __name__=='__main__':
    main()
