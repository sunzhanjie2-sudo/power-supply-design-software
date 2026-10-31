"""Exercise the application's DOCX exporter for the physical coupling path."""
import copy
import json
from pathlib import Path
import sys
from unittest.mock import patch

import numpy as np

sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from docx import Document
from design_api import load_spec
from loss_model import compute_design
from report_docx import export_design_docx
from multi_output_charts import draw_output_currents
from plants import build_loop_models


def run():
    p=load_spec(json.loads(Path('examples/3_OUTPUT_COUPLED_FLYBACK.json').read_text(encoding='utf-8')))
    saved=copy.deepcopy(p)
    result=compute_design(p)
    models,_=build_loop_models(p,result['op'])
    path=Path('_tmp_coupled_report_qa/3路耦合反激设计报告.docx')
    path.parent.mkdir(exist_ok=True)
    captured=[]
    def currents(ax,branch):
        artists=draw_output_currents(ax,branch)
        for key,line in artists.items():
            np.testing.assert_array_equal(line.get_ydata(),branch['wf'][key])
        captured.append(branch['id'])
        return artists
    with patch('multi_output_charts.draw_output_currents',side_effect=currents):
        outcome=export_design_docx(path,p,result['op'],result['wf'],result,models=models)
    assert captured==[r['id'] for r in result['outputs']]
    assert p==saved
    doc=Document(path)
    body='\n'.join(para.text for para in doc.paragraphs)
    cells='\n'.join(cell.text for t in doc.tables for row in t.rows for cell in row.cells)
    assert '绕组耦合计算快照' in body
    assert '解算电压 / 功率' in cells
    assert 'DCM' in cells and '能量平衡残差' in cells
    assert '刚性' in body and '周期映射' in body
    assert outcome['loop_available']
    assert 'V·A⁻¹' in cells and '唯一主反馈路' in body
    assert '临时频带限制' in cells and '已停用' in cells
    assert '有效频带上限' not in cells
    assert '高频结果属于近似外推' in body
    assert len(doc.inline_shapes)>=15
    assert len(doc.element.xpath('.//m:oMath'))>=2
    print(json.dumps(outcome,ensure_ascii=True))
    print('Coupled exporter checks passed; document tables/images/native math preserved.')


if __name__=='__main__':
    run()
