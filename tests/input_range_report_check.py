"""Endpoint Word report keeps complete data paired by engineering module."""
import copy
import json
from pathlib import Path
import sys
import unittest
from unittest.mock import patch

import numpy as np

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from runtime_resources import configure_numeric_threads
configure_numeric_threads()
from docx import Document
from design_api import load_spec
from input_voltage_range import calculate_input_endpoints
from input_range_report import export_input_range_docx, _draw_comparison, CASE_COLORS
from matplotlib.figure import Figure
from power_stage import DEFAULT_PARAMS
from report_docx import export_design_docx, value


OUT=ROOT/'_tmp_input_range_report_qa'


def curve(case):
    result=case['result']
    return dict(fracs=[.5,1.],etas=[result['eta'],result['eta']],modes=[result['op']['mode']]*2)


def add_curves(snapshot):
    # Tests avoid computing dozens of unrelated load points. Report validates
    # and plots these supplied values, whose provenance is explicit here.
    for case in snapshot['cases']:
        if case['result']:
            case['efficiency_curve']=curve(case)
    return snapshot


def text(doc):
    return '\n'.join(p.text for p in doc.paragraphs)


class RangeReportChecks(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.snapshot=add_curves(calculate_input_endpoints(dict(DEFAULT_PARAMS,
            V_in_min=24.,V_in_max=40.,input_voltage_case='max'),include_loop=True))
        OUT.mkdir(exist_ok=True)

    def test_both_complete_reports_share_one_document_and_preserve_snapshot(self):
        snap=self.snapshot
        saved=copy.deepcopy(snap['base_spec'])
        path=OUT/'24至40V_双输入端点完整报告.docx'
        state=dict(topo='tl431f',dir='fwd',type2=False,vars={
            'R1':dict(v=40.,u='k'),'CTR':dict(v=1.,u=''),
            'Rpullup':dict(v=20.,u='k'),'Copto':dict(v=.1,u='n')})
        outcome=export_input_range_docx(path,snap,compensation_state=state)
        self.assertFalse(outcome['incomplete'])
        self.assertEqual(outcome['successful_cases'],2)
        self.assertEqual(snap['base_spec'],saved)
        doc=Document(path); body=text(doc)
        self.assertEqual(sum(p.style.name=='Title' for p in doc.paragraphs),1)
        self.assertIn('同一套已确定硬件与补偿',body)
        for title in ('需求与共同硬件','功率级与开关过程','器件选型与损耗',
                      '电容分流与输出纹波','磁件设计与绕制','环路与反馈补偿','输入参数与追溯'):
            self.assertIn(title,body)
        self.assertEqual(outcome['report_architecture'],'module-paired-v1')
        for label in ('Vinmin','Vinmax'):
            self.assertIn(label,'\n'.join(c.text for t in doc.tables for r in t.rows for c in r.cells))
        self.assertNotIn('[Vinmin] 0  拓扑',body)
        self.assertNotIn('[Vinmax] 0  拓扑',body)
        self.assertNotIn('自动选芯 / 匝数会在每个负载点重新设计',body)
        # Shared formulae appear once. Verify their content against the full
        # single-case author, rather than require the old duplicated count.
        from io import BytesIO
        from PIL import Image
        from report_xlsx import _math_text
        tiny=BytesIO();Image.new('RGB',(4,4),'white').save(tiny,format='PNG')
        expected=set()
        with patch('report_docx._chart',return_value=tiny.getvalue()):
            for case in snap['cases']:
                reference=Document();r=case['result']
                export_design_docx('',case['p'],r['op'],r['wf'],r,document=reference,save=False,
                    efficiency_curve=case['efficiency_curve'],compensation_state=state)
                expected.update(_math_text(node) for node in reference.element.xpath('.//m:oMath'))
        actual={_math_text(node) for node in doc.element.xpath('.//m:oMath')}
        self.assertGreaterEqual(len(actual),10)
        self.assertTrue(expected<=actual,expected-actual)
        self.assertEqual(outcome['figure_count'],len(doc.inline_shapes))
        # python-docx assigns relationship/figure identities in the same part;
        # neither endpoint can overwrite the other's images or captions.
        ids=doc.element.xpath('.//wp:docPr/@id')
        self.assertEqual(len(ids),len(set(ids)))
        print('Report QA:',path)

    def test_comparison_lines_are_actual_case_samples_with_stable_colors(self):
        fig=Figure(figsize=(7,5)); _draw_comparison(fig,self.snapshot['cases'])
        for index,case in enumerate(self.snapshot['cases']):
            for axis,key,scale in zip(fig.axes[:3],('i_sw','v_sw','vout_ripple'),(1,1,1000)):
                line=axis.lines[index]
                np.testing.assert_array_equal(line.get_ydata(),case['result']['wf'][key]*scale)
                self.assertEqual(line.get_color(),CASE_COLORS[case['id']])

    def test_failure_is_visible_and_not_replaced_by_other_endpoint(self):
        snap=dict(self.snapshot,cases=[dict(case) for case in self.snapshot['cases']])
        snap['cases'][1].update(result=None,error='测试角点不能收敛',models=None,checks=[])
        path=OUT/'单端点失败报告.docx'
        out=export_input_range_docx(path,snap)
        self.assertTrue(out['incomplete']); self.assertEqual(out['failed_cases'],['Vinmax'])
        body=text(Document(path))
        self.assertIn('计算不完整',body)
        self.assertIn('测试角点不能收敛',body)
        self.assertIn('Vinmax 本工况不可用',body)
        self.assertNotIn('[Vinmax] 2  关键时域',body)

    def test_equal_endpoints_keep_both_labeled_complete_sections(self):
        snap=add_curves(calculate_input_endpoints(dict(DEFAULT_PARAMS,
            V_in_min=30.,V_in_max=30.),include_loop=True))
        self.assertIs(snap['cases'][0]['result'],snap['cases'][1]['result'])
        # Only append orchestration is needed here; full actual authoring is
        # independently tested above, so omit duplicative chart work.
        with patch('input_range_report.export_design_docx',return_value=dict(checks=1,needs_review=0)) as append:
            out=export_input_range_docx(OUT/'相同输入端点报告.docx',snap)
        self.assertEqual(append.call_count,2)
        self.assertIsNot(append.call_args_list[0].kwargs['document'],append.call_args_list[1].kwargs['document'])
        self.assertTrue(all(not c.kwargs['save'] for c in append.call_args_list))
        self.assertFalse(out['incomplete'])

    def test_multi_output_each_cap_group_only_once_per_case(self):
        p=load_spec(json.loads((ROOT/'examples/3_OUTPUT_COUPLED_FLYBACK.json').read_text(encoding='utf-8')))
        p['P_out']=123. # Legacy scalar is not the sum of the configured rails.
        snap=add_curves(calculate_input_endpoints(dict(p,V_in_min=27.,V_in_max=33.),include_loop=True))
        self.assertTrue(all(case['result'] is not None for case in snap['cases']))
        output=OUT/'三路反激_双输入端点完整报告.docx'
        out=export_input_range_docx(output,snap,compensation_state=dict(topo='tl431f',dir='fwd',
            type2=False,vars=dict(R1=dict(v=40.,u='k'),CTR=dict(v=1.,u=''),
                                  Rpullup=dict(v=20.,u='k'),Copto=dict(v=.1,u='n'))))
        doc=Document(output); body=text(doc)
        self.assertEqual(len([t for t in doc.tables if t.cell(0,0).text=='电容']),1)
        for group in ('共享输入','OUT1','OUT2','OUT3'):
            self.assertEqual(sum('图 4-' in p.text and group+' 电容 FFT 分带（仅列一次）' in p.text for p in doc.paragraphs),1)
        self.assertNotIn('图 1-C1',body)
        self.assertEqual(out['successful_cases'],2)
        demand=next(row.cells[1].text for t in doc.tables for row in t.rows
                    if row.cells[0].text=='总功率 / 主反馈路电流')
        self.assertIn('40 W / ',demand)
        self.assertNotIn('123 W',demand)
        print('Multi-output report QA:',output)

    def test_partial_magnetics_and_two_failed_cases_do_not_claim_validation_passed(self):
        snap=dict(self.snapshot,fixed_hardware=False,hardware={},hardware_note='测试磁件选型失败')
        with patch('input_range_report.export_design_docx',return_value=dict(checks=1,needs_review=1)):
            out=export_input_range_docx(OUT/'磁件部分结果报告.docx',snap)
        body=text(Document(out['path']))
        self.assertTrue(out['incomplete']); self.assertFalse(out['hardware_fixed'])
        self.assertIn('硬件未闭合',body)
        self.assertIn('测试磁件选型失败',body)
        both=dict(snap,cases=[dict(case,result=None,error='测试计算失败',checks=[])
                             for case in snap['cases']])
        out=export_input_range_docx(OUT/'两个端点失败报告.docx',both)
        body=text(Document(out['path']))
        self.assertEqual(out['successful_cases'],0)
        self.assertIn('计算不完整',body)
        self.assertNotIn('检查均未出现需复核',body)

    def test_invalid_case_identity_is_rejected(self):
        with self.assertRaisesRegex(ValueError,'Vinmin'):
            export_input_range_docx(OUT/'invalid.docx',dict(self.snapshot,cases=self.snapshot['cases'][:1]))


if __name__=='__main__': unittest.main(verbosity=2)
