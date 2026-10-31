"""Surgically update the current reference without rebuilding unrelated parts.

Use the bundled document Python. Input and output must differ so that the
original stays available until render QA of the candidate has completed.
"""
import argparse
from copy import deepcopy
from pathlib import Path
import sys

from docx import Document
from docx.oxml.ns import qn
from docx.oxml import OxmlElement
from docx.enum.text import WD_ALIGN_PARAGRAPH

sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from word_math import element, math_nodes


def replace_text(p,text):
    # Preserve paragraph and first run typography; replace only its content.
    props=deepcopy(p.runs[0]._r.rPr) if p.runs and p.runs[0]._r.rPr is not None else None
    p.clear()
    run=p.add_run(text)
    if props is not None:run._r.insert(0,props)


def insert_before(anchor,text=None,formula=None):
    paragraph=anchor.insert_paragraph_before(text or '')
    paragraph.style='Normal'
    if formula:paragraph._p.append(element('oMath',*math_nodes(formula)))
    return paragraph


def update(source,output):
    assert Path(source).resolve()!=Path(output).resolve(),'Keep the source intact until QA'
    d=Document(source)
    changed=[]
    for p in list(d.paragraphs):
        if p.text=='软件计算内核详解  输入范围与双工况报告版  2026-10-18':
            replace_text(p,'软件计算内核详解  热阻与钳位应力更新版  2026-10-21')
        if p.text.startswith('本文件对应 2026-10-18 输入范围与双工况报告版'):
            replace_text(p,p.text.replace('本文件对应 2026-10-18 输入范围与双工况报告版','本文件对应 2026-10-21 热阻与钳位应力更新版').replace('Input_voltage_range_update','Thermal_clamp_stress_20261021'))
        if p.text.startswith('h 为可编辑对流系数；'):
            replace_text(p,'变压器采用用户输入的整体至环境热阻 Ri-a（Rth_transformer，K/W），温升等于全部绕组铜损与磁芯损耗之和乘以热阻。默认100 K/W仅是初始假设，不是磁芯目录数据，须按实测或热设计填写。包含已建模 PSR 辅助绕组铜损，不迭代热态铜阻，不预测局部热点。')
            insert_before(p,'变压器稳态温升按下式计算；前述表面积及对流公式仅用于独立电感，不用于变压器。')
            insert_before(p,formula='ΔT=(Pcu+Pcore)·Rth')
            changed.append('thermal')
        if '物理包络峰值与另加振铃裕量的器件选型参考分开列出' in p.text:
            replace_text(p,p.text.replace('物理包络峰值与另加振铃裕量的器件选型参考分开列出','物理包络峰值与 Kc 定义的钳位应力上限分开列出；反激不再叠加振铃裕度'))
            changed.append('clamp')
        if p.text.startswith('RMS 由分段三角波求取。'):
            insert_before(p,'整流二极管反压未考虑寄生尖峰应力，具体应力需实测，建议选型时留有耐压余量；单路、多路均适用。反激 MOS 的 Kc 为 Vclamp/Vreflect，钳位电压相对输入母线；应力上限按下式计算，不再叠加旧振铃裕度。实际包络峰值可能低于上限，无漏感不虚构尖峰。未配置有效 Kc>1 时仅知理想阻断平台，不能据此认为已覆盖尖峰。Kc 不是器件额定耐压的降额系数。')
            insert_before(p,formula='Vds,clamp=Vin+Kc·Vr')
            changed.append('diode')
    tables=[t for t in d.tables if t.cell(0,1).text=='主开关电压应力']
    assert len(tables)==1
    t=tables[0]
    sw=('Vin(1+ring)','U(1+ring)','(Vin+U)(1+ring)','Vin+Kc·Vr','(Vcl+Vhump)(1+ring)')
    diode=('Vin','U','Vin+U','U+Vin/N','Vreset/N')
    for i,(s,v) in enumerate(zip(sw,diode),1):
        for j,formula in ((1,s),(2,v)):
            cell=t.cell(i,j)
            p=cell.paragraphs[0]
            p.clear();p.paragraph_format.line_spacing=1.0
            p.alignment=WD_ALIGN_PARAGRAPH.CENTER
            math=element('oMath',*math_nodes(formula))
            for run in math.iter(qn('m:r')):
                prop=OxmlElement('w:rPr');size=OxmlElement('w:sz');size.set(qn('w:val'),'20')
                prop.append(size);run.insert(1,prop)
            p._p.append(math)
    for t in d.tables:
        for row in t.rows:
            for cell in row.cells:
                for p in cell.paragraphs:
                    if '经验对流模型不超提醒阈值' in p.text:
                        replace_text(p,p.text.replace('经验对流模型不超提醒阈值','变压器按用户热阻，独立电感按对流模型'))
    assert sorted(changed)==['clamp','diode','thermal'],changed
    # Added formulas carry no duplicate numbering; retain all existing labels.
    assert len(d.inline_shapes)==len(Document(source).inline_shapes)
    Path(output).parent.mkdir(parents=True,exist_ok=True)
    d.save(output)
    print('Updated reference; existing figures and all unrelated content retained')


if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--source',required=True);p.add_argument('--output',required=True)
    args=p.parse_args();update(args.source,args.output)
