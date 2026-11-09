"""QR corner reports retain real frequencies, endpoint pairing and failures."""
from copy import deepcopy
import json
from pathlib import Path
import sys
import unittest
from zipfile import ZipFile

ROOT=Path(__file__).resolve().parents[1];sys.path[:0]=[str(ROOT),str(ROOT/'tests')]
from runtime_resources import configure_numeric_threads
configure_numeric_threads()
from qr_coupled_check import fixture
from input_voltage_range import calculate_input_endpoints
from cross_regulation_report import add_report
from docx_layout import new_document
from report_architecture import capture_document,write_paired_modules
from report_xlsx import export_input_range_xlsx

OUT=ROOT/'artifacts/qr-cross-20261108/report-projection'


class QRCrossReports(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        OUT.mkdir(parents=True,exist_ok=True)
        cls.p=fixture();cls.p['V_in_max']=320.
        cls.p['outputs'][0]['P_out_min']=45.;cls.p['outputs'][1]['P_out_min']=.5
        cls.bundle=calculate_input_endpoints(cls.p,include_loop=True)
        assert cls.bundle['cross_regulation']['complete']

    def test_native_word_section_pairs_by_load_and_keeps_frequency(self):
        snapshots=[]
        for c in self.bundle['cases']:
            doc=new_document('QR角点投影检查','实际矩阵解；只验证本轮新增章节','QA')
            add_report(doc,c['p'],c['result']);snapshots.append(capture_document(doc))
        doc=new_document('QR跨调双端点章节检查','300 V 与 320 V；软件测试输入，不是实物验收','QA')
        write_paired_modules(doc,snapshots,self.bundle['cases'])
        cells='\n'.join(c.text for t in doc.tables for r in t.rows for c in r.cells)
        self.assertIn('实际频率',cells);self.assertIn('X001',cells);self.assertIn('X008',cells)
        self.assertIn('Vinmin',cells);self.assertIn('Vinmax',cells)
        self.assertIn('60 / 1',cells)
        for case in self.bundle['cross_regulation']['cases']:
            self.assertIn(f'{case["f_sw"]:.6g}',cells)
        self.assertGreaterEqual(len(doc.element.xpath('.//m:oMath')),2)
        rcd_note=next(p for p in doc.paragraphs if p.text.startswith('QR固定RCD：'))
        self.assertTrue(rcd_note.paragraph_format.page_break_before)
        doc.save(OUT/'QR交叉调整率_双端章节.docx')

    def test_excel_module_keeps_two_endpoint_frequencies(self):
        # Full workbook uses the same captured native report sections;
        # no independently recomputed or fake efficiencies are supplied.
        result=export_input_range_xlsx(OUT/'QR交叉调整率_模块双端.xlsx',self.bundle)
        self.assertIn('13 交叉调整率',result['sheet_names'])
        with ZipFile(OUT/'QR交叉调整率_模块双端.xlsx') as archive:
            text=''.join(archive.read(name).decode('utf8') for name in archive.namelist()
                         if name.startswith('xl/worksheets/') and name.endswith('.xml'))
        self.assertIn('实际频率',text)
        self.assertIn('X008',text)
        self.assertIn('谷底',text)

    def test_incomplete_and_frequency_limit_are_distinct(self):
        res=deepcopy(self.bundle['cases'][0]['result'])
        data=res['cross_regulation'];data['complete']=False
        data['cases'][0]['qr_timing']['design_frequency_limit_exceeded']=True
        data['cases'][-1].update(status='failed',error='测试：无单周期自洽谷底',voltages=None)
        data['successful_cases']-=1
        doc=new_document('QR状态检查','仅测试状态投影，不是新数值求解','QA')
        add_report(doc,self.p,res)
        text='\n'.join(p.text for p in doc.paragraphs)+'\n'+'\n'.join(c.text for t in doc.tables for r in t.rows for c in r.cells)
        self.assertIn('不能作为完整设计',text)
        self.assertIn('已求解；频率超过设计上限',text)
        self.assertIn('测试：无单周期自洽谷底',text)


if __name__=='__main__':unittest.main(verbosity=2)
