"""Production report helper: native equations, designator mapping and XLSX capture."""
import copy
import json
from pathlib import Path
import sys
import unittest
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
from diode_curves_check import spec,curve
from input_voltage_range import calculate_input_endpoints
from docx_layout import new_document,paragraph
from diode_report import add_diode_report
from report_xlsx import _capture_document


def fixture():
    p=spec();p.update(V_in_min=20.,V_in_max=40.,diode_curves={'D1':curve('整流曲线'),
        'D_IN':curve('输入防反',.2,.04),'D_OUT':curve('输出防反',.3,.05)})
    return p,calculate_input_endpoints(p,include_loop=False,include_cross_regulation=False)


class ReportChecks(unittest.TestCase):
    def test_native_formulas_and_excel_capture_keep_identity(self):
        p,bundle=fixture();before=copy.deepcopy(p)
        for case in bundle['cases']:
            self.assertFalse(case.get('error'),case.get('error'))
            doc=new_document('二极管正向曲线核算','设计报告模块校核','二极管导通损耗')
            add_diode_report(doc,case['p'],case['result'])
            self.assertEqual(len(doc.element.xpath('.//m:oMath')),3)
            text=''.join(doc.element.itertext())
            for item in ('D1','D_IN','D_OUT','整流曲线','输入防反','输出防反','X'):
                self.assertIn(item,text)
            blocks=_capture_document(doc)['devices']
            joined=str(blocks)
            self.assertIn('整流曲线',joined);self.assertIn('导通损耗',joined)
            self.assertNotIn('Rd_diode',joined)
        self.assertEqual(p,before)


def qa():
    p,bundle=fixture();out=ROOT/'_tmp_diode_qa';out.mkdir(exist_ok=True)
    for case in bundle['cases']:
        # Application runtime emits only numeric snapshots/figures here.
        # DOCX authoring uses the bundled artifact runtime in a separate step.
        snapshot=dict(id=case['id'],p={'diode_curves':case['p']['diode_curves']},res={'diode_models':case['result']['diode_models']})
        (out/(case['id']+'_snapshot.json')).write_text(json.dumps(snapshot,ensure_ascii=False),encoding='utf-8')
        from report_docx import _chart
        def draw(fig):
            axes=fig.subplots(1,3)
            for ax,(ref,c) in zip(axes,case['p']['diode_curves'].items()):
                ax.plot([pt[0] for pt in c['points']],[pt[1] for pt in c['points']])
                ax.set(title=ref,xlabel='Vf / V',ylabel='If / A');ax.grid(alpha=.2)
        (out/(case['id']+'_curves.png')).write_bytes(_chart((7.1,2.7),draw))
    print('QA snapshots written:',out)


if __name__=='__main__':
    if '--qa' in sys.argv:qa()
    else:unittest.main(verbosity=2)
