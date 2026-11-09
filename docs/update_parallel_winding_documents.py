"""Apply the parallel-wire definition locally, preserving the existing manuals."""
import argparse
import ast
from pathlib import Path
import sys
from docx import Document

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
import word_math as wm


def texts(path,call):
    tree=ast.parse(path.read_text(encoding='utf-8-sig'))
    result=[]
    for node in ast.walk(tree):
        if isinstance(node,ast.Call) and ((isinstance(node.func,ast.Name) and node.func.id in call)
            or isinstance(node.func,ast.Name) and node.func.id=='paragraph'):
            for arg in node.args:
                if isinstance(arg,ast.Constant) and isinstance(arg.value,str):result.append(arg.value)
    return result


def update(source,output,tutorial=False):
    if Path(source).resolve()==Path(output).resolve():raise ValueError('先生成副本并渲染核对')
    d=Document(source)
    if any(p.text.startswith('本例线圈并绕数 b=1') for p in d.paragraphs):raise ValueError('已更新，避免重复插入')
    builder=ROOT/('docs/tutorials/build_flyback_tutorial.py' if tutorial else 'docs/build_calculation_reference.py')
    choices=texts(builder,{'P','S'})+texts(ROOT/'winding_report.py',set())
    def chosen(prefix):return next(t for t in choices if t.startswith(prefix))
    def find(prefix):return next(p for p in d.paragraphs if p.text.startswith(prefix))
    def after(prefix,text):
        anchor=find(prefix)
        ps=d.paragraphs
        # Paragraph wrappers are recreated by python-docx; compare underlying XML.
        index=next(i for i,p in enumerate(ps) if p._p is anchor._p)
        p=ps[index+1].insert_paragraph_before(text)
        p.style='Normal'
    def replace(prefix,new):find(prefix).text=chosen(new)
    def formula(prefix,expression):
        p=next(p for p in d.paragraphs if ''.join(p._p.xpath('.//m:t/text()')).startswith(prefix))
        old=p._p.xpath('.//m:oMath')[0]
        old.getparent().replace(old,wm.element('oMath',*wm.math_nodes(expression)))
    if tutorial:
        wm.ALIASES.update({'Atotal':'A_total','Astrand':'A_strand','Nturn':'N_turn'})
        wm.NAMES=sorted(wm.ALIASES,key=len,reverse=True)
        formula('Astrand=', 'Astrand=π·dwire²/4；Atotal=nparallel·nstrand·Astrand')
        after('原边单股直径 0.1 mm',chosen('本例线圈并绕数 b=1'))
        after('普通单根铜线不套用',chosen('均匀排布是生成初始位置'))
    else:
        formula('Rdc=', 'Rdc=ρ·MLT·N/[nparallel·nstrand·πdwire²/4]')
        formula('fill=', 'fill=Σ(N·nparallel·nstrand·Awire)/Wa')
        formula('ACu,j=', 'Acu_j=nparallel_j·nstrand_j·π·d_j²/4')
        replace('fill 只统计','b 为线圈并绕根数')
        replace('线径为单股','线径为单股')
        replace('每匝由 B','线圈并绕数 b 是')
        replace('配置 JSON 的 winding_config','配置 JSON 的 winding_config')
        after('兼容旧配置：',chosen('点选某匝中的线束'))
        replace('耗时电气计算改为','耗时电气计算在后台')
        replace('Tk 控件与绘图发布','Tk 控件与绘图留在')
    out=Path(output);out.parent.mkdir(parents=True,exist_ok=True);d.save(out)
    print(out,len(d.element.xpath('.//m:oMath')))


if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--source',required=True);p.add_argument('--output',required=True)
    p.add_argument('--tutorial',action='store_true');a=p.parse_args();update(a.source,a.output,a.tutorial)
