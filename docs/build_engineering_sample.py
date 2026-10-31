"""Build the bundled-default review example, including engineering workflows."""
from pathlib import Path
import sys
import json

sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from design_api import load_spec
from analysis_workflows import evaluate, corners, compare
from report_docx import export_design_docx


def build():
    a=evaluate(load_spec({}))
    grid=corners(a['p'])
    b=evaluate(load_spec(json.loads(Path('examples/40W_ACF_FORWARD.json').read_text(encoding='utf-8'))))
    comparison=compare(a,b,('A：默认 40W CCM 反激','B：内置 40W 有源钳位正激'))
    output=Path('reports/40W_CCM_反激_设计评审报告.docx')
    result=export_design_docx(output,a['p'],a['op'],a['wf'],a['res'],a['models'],
                              corners=grid,comparison=comparison)
    print(json.dumps(result,ensure_ascii=False))


if __name__=='__main__':build()
