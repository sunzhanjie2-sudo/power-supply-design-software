"""Application-generated Word and Excel share thermal/stress scope and math."""
import json
from pathlib import Path
import sys
import unittest
from unittest.mock import patch

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT));sys.path.insert(0,str(ROOT/'tests'))
from runtime_resources import configure_numeric_threads
configure_numeric_threads()
from docx import Document
from design_api import load_spec
from input_voltage_range import calculate_input_endpoints
from report_docx import export_design_docx
from report_xlsx import _capture_document
from thermal_stress_check import spec


class ThermalReportChecks(unittest.TestCase):
    def test_single_and_multi_endpoint_reports(self):
        from io import BytesIO
        from PIL import Image
        png=BytesIO();Image.new('RGB',(120,80),'white').save(png,format='PNG')
        for name in ('40W_CCM_FLYBACK.json','6_OUTPUT_FLYBACK_SSR.json'):
            bundle=calculate_input_endpoints(spec(name,Rth_transformer=21.,V_in_min=27.,V_in_max=33.),
                include_loop=False,include_cross_regulation=False)
            for case in bundle['cases']:
                self.assertFalse(case.get('error'),case.get('error'))
                r=case['result'];doc=Document()
                # Tests layout-independent content only; real charts get separate visual QA.
                with patch('report_docx._chart',return_value=png.getvalue()):
                    export_design_docx('',case['p'],r['op'],r['wf'],r,document=doc,save=False,
                        efficiency_curve=dict(fracs=[1.],etas=[r['eta']],modes=[r['op']['mode']],failures=[]))
                content=_capture_document(doc)
                self.assertIn('未考虑寄生尖峰',str(content['devices']))
                self.assertIn('Kc 钳位上限',str(content['devices']))
                self.assertIn('R_{i-a}',str(content['magnetics']))
                self.assertIn('21',str(content['magnetics']))
                self.assertNotIn('温升为经验表面积加对流',str(content['magnetics']))
                self.assertTrue(doc.element.xpath('.//m:oMath'))


if __name__=='__main__':unittest.main(verbosity=2)
