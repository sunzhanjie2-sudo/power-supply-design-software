"""Surgically update magnetic-circuit equations in the two bundled manuals."""
import argparse
from pathlib import Path
import sys

from docx import Document
from docx.enum.text import WD_ALIGN_PARAGRAPH

sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from word_math import element, math_nodes


def before(anchor, text, *, formula=False, heading=False):
    p=anchor.insert_paragraph_before('')
    p.style='Heading 2' if heading else 'Normal'
    if formula:
        p.alignment=WD_ALIGN_PARAGRAPH.CENTER
        p._p.append(element('oMath', *math_nodes(text)))
    else:
        p.add_run(text)
    return p


def update(source, output, tutorial=False):
    if Path(source).resolve()==Path(output).resolve():
        raise ValueError('请先输出到新文件，渲染核对后再替换内置手册')
    doc=Document(source)
    if tutorial:
        anchor=next(p for p in doc.paragraphs if p.text.startswith('12  窗口能否绕下'))
        old=next(p for p in doc.paragraphs if p.text.startswith('Bsat 输入为 0.4 T，Bmax'))
        old.text=('Bsat 输入为 0.4 T，Bmax 设计约束为 0.3 T。两端点参考峰值低于这两个值，'
                  '温升、偏置和实际材料温度特性仍需确认。软件新增有限磁导率气隙初算，见 11.8 节。')
        if any(p.text.startswith('11.8  磁导率') for p in doc.paragraphs):
            raise ValueError('此教程已包含气隙章节')
        before(anchor,'11.8  磁导率怎样确定气隙',heading=True)
        before(anchor,'反激变压器用气隙降低磁路的有效磁导率，使所需原边电感能容纳工作电流。先确定磁芯有效参数和原边匝数，再按目标 AL 估算气隙。材料的相对磁导率 μr 无量纲，与真空磁导率 μ0 及含气隙的有效磁导率 μe 分别使用。')
        before(anchor,'本例选择 DMR44，材料手册在 25 °C 给出初始磁导率 μi=2400，公差 ±25%。输入 μr=0 时使用该值，手动填值可覆盖。小信号 μi 用于初版估算，实际温度、偏磁和频率下应按厂家参数与测量核对。手动设置的 k、α、β 继续独立用于损耗。')
        before(anchor,'le=Ve/Ae=2814.8/62=45.4 mm',formula=True)
        before(anchor,'AL=Lm/Np²=8/6²=0.222222 μH',formula=True)
        before(anchor,'Rcore=le/(μ₀·μr·Ae)；Rgap=lg/(μ₀·Ae)',formula=True)
        before(anchor,'Lm=Np²/(Rcore+Rgap)',formula=True)
        before(anchor,'lg=μ₀·Ae·Np²/Lm−le/μr',formula=True)
        before(anchor,'代入 Np=6、Lm=8 μH、Ae=62 mm²、le=45.4 mm、μr=2400，第一项为 0.350602 mm，磁芯磁阻折算项为 0.018917 mm，得到 lg≈0.331685 mm。无气隙电感约 148.272 μH，目标 AL≈222.222 nH/匝²。20 V 与 30 V 输入使用同一套硬件，气隙相同。')
        before(anchor,'lg 是折算到 Ae 的总等效气隙。中柱单处开隙可用作初值，整副磁芯垫开会使外柱同时形成气隙，垫片厚度需按实际磁路换算。计算忽略边缘磁通，打样按目标 AL 测量调整。若目标 Lm 大于无气隙电感，显示不可实现并复核匝数、磁芯或 μr；不能用负气隙制造。三维建模包分别保存估算结果与用户提供的实际气隙结构。')
    else:
        old=next(p for p in doc.paragraphs if p.text.startswith('按数据库磁芯的 Ae·Wa'))
        old.text=('按数据库磁芯的 Ae·Wa 初选磁芯，或使用用户指定芯型。电感气隙公式忽略磁芯磁阻，'
                  '变压器另用下列有限磁导率关系。le 固定由有效体积与截面积 Ve/Ae 派生，不需输入；'
                  'MLT 为铜线每匝长度。μr=0 使用材料手册初始磁导率，可手动覆盖。')
        anchor=next(p for p in doc.paragraphs if p.text.startswith('7.2  真实峰值磁密'))
        before(anchor,'AL=Lm/Np²；L0=μ₀·μr·Ae·Np²/le',formula=True)
        before(anchor,'lg=μ₀·Ae·Np²/Lm−le/μr',formula=True)
        before(anchor,'反激与准谐振使用原边 L，正激变压器使用 Lm_forward。lg 为折算到 Ae 的总等效气隙，忽略边缘磁通，需按加工后 AL 测量调整。若 lg<0，则目标 Lm 高于无气隙电感 L0，检查项提示不可实现，须复核 μr、le、匝数或磁芯。材料初始 μi 是小信号参数，不包含温度与直流偏磁模型。')
    before(anchor,'气隙公式与边缘磁通说明依据 TI UCC2863x SLUSBW3D 第 61 页式 45。https://www.ti.com/lit/ds/symlink/ucc28630.pdf')
    output=Path(output);output.parent.mkdir(parents=True,exist_ok=True)
    doc.save(output)
    print(output)


if __name__=='__main__':
    p=argparse.ArgumentParser()
    p.add_argument('--source',required=True);p.add_argument('--output',required=True)
    p.add_argument('--tutorial',action='store_true')
    args=p.parse_args();update(args.source,args.output,args.tutorial)
