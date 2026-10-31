"""Minimal native-OMML corrections plus QA modules; run with artifact Python."""
import copy
import json
from pathlib import Path
import shutil
import sys
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
from docx import Document
from docx.shared import Pt
from word_math import element,math_nodes
from app_resources import resource_path


def update_master(folder):
    path=resource_path('计算方法与公式说明.docx')
    backup=folder/'计算说明_修改前备份.docx'
    if not backup.exists():shutil.copy2(path,backup)
    doc=Document(path)
    def contents(p):return ''.join(p._p.itertext())
    def replace_math(prefix,text):
        paragraph=next(p for p in doc.paragraphs if ''.join(p._p.xpath('.//m:t/text()')).startswith(prefix))
        old=paragraph._p.xpath('.//m:oMath')[0]
        old.getparent().replace(old,element('oMath',*math_nodes(text)))
    replace_math('Pdiode=','Pdiode=Pcond+Qrr·Vr·fs')
    replace_math('Pdin=','Pdin=mean(iin·Vf,din(iin))')
    replace_math('Pdout=','Pdout=Io·Vf,dout(Io)')
    for p in doc.paragraphs:
        text=p.text
        if '真实 Vf_diode、Rd_diode' in text:
            p.text=text.replace('真实 Vf_diode、Rd_diode 和防反二极管参数仍进入最终损耗',
                '真实二极管压降或导入的 Vf–If 曲线仍进入最终损耗；旧 Rd 动态电阻项已停用')
        elif '每路分别设置输出功率、整流器 Vf/Rd/Qrr' in text:
            p.text=text.replace('整流器 Vf/Rd/Qrr','整流器固定 Vf/Qrr 与按位号绑定的独立 Vf–If 曲线')
        elif '电路还显式包含 MOS 导通电阻、采样电阻、整流 Vf/Rd' in text:
            p.text=text.replace('整流 Vf/Rd','整流固定 Vf')+' Vf–If 导入曲线仅用于周期求解后的导通损耗，尚未参与非线性换流或小信号线性化；不使用隐含的 Rd。'
    if not any('导入正向特性 X=Vf' in p.text for p in doc.paragraphs):
        anchor=next(p for p in doc.paragraphs if p.text.startswith('6.4'))
        for text in ('导入正向特性 X=Vf（V）、Y=If（A），按拓扑图位号逐个绑定。D1/D2 为单路整流/续流，D_Oj/D_Fj 为 OUTj 整流/续流，D_IN、D_OUT 或 D_Bj 为防反。不同温度曲线由名称区分，不自动修正结温。',
                     '导通损耗先反查当前电流下的 Vf，再平均瞬时功率；不能用平均电流查一次代替脉冲积分。无曲线时使用固定 Vf×Iavg；动态电阻不再输入或叠加。'):
            anchor.insert_paragraph_before(text)
        for formula in ('Pcond=1/Ts·∫_0^Ts Vf(If(t))·If(t) dt',
                        'Pcond=Σ_(k=1)^Nsamples (If,k·Vf(If,k))/Nsamples'):
            p=anchor.insert_paragraph_before();p.paragraph_format.space_after=Pt(4)
            p._p.append(element('oMath',*math_nodes(formula)))
        anchor.insert_paragraph_before('CSV 仅需 x,y 两列，JSON 仅需点数组；V1.3 提取文件已乘数量级，导入倍率 X/Y 均选 1。端点外按相邻点趋势外推并提示，负 Vf 截为零，零电流损耗为零。曲线随设计 JSON 内嵌保存，Vinmin/Vinmax 各自使用对应周期电流；曲线仅用于损耗后处理。公式依据 ST AN604 第 2 节式 10。')
    doc.save(path)
    print('Updated native-formula manual:',path)


def qa_modules(folder):
    from docx_layout import new_document,paragraph,figure
    from diode_report import add_diode_report
    for name in ('Vinmin','Vinmax'):
        snapshot=json.loads((folder/(name+'_snapshot.json')).read_text(encoding='utf-8'))
        doc=new_document('二极管正向曲线导通损耗核算',name+' 模块排版校核','二极管正向特性')
        paragraph(doc,'本核对文件采用格式测试曲线，验证器件绑定、周期功率计算和报告排版，不用于真实器件选型。')
        add_diode_report(doc,snapshot['p'],snapshot['res'],charts=False)
        figure(doc,(folder/(name+'_curves.png')).read_bytes(),'二极管位号与正向特性坐标')
        doc.save(folder/(name+'_diodes.docx'))


if __name__=='__main__':
    folder=ROOT/'_tmp_diode_qa';folder.mkdir(exist_ok=True)
    update_master(folder);qa_modules(folder)
