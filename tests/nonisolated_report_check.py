"""Single-output physical models traverse the public API and both reports."""
import json
from pathlib import Path
import sys
import tempfile
import unittest
from zipfile import ZipFile

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from runtime_resources import configure_numeric_threads
configure_numeric_threads()
from design_engine.specification import load_spec
from design_engine.service import calculate_parameters, export_report


class SingleOutputReportChecks(unittest.TestCase):
    def test_all_profiles_serialize_and_export_both_input_endpoints(self):
        with tempfile.TemporaryDirectory() as folder:
            for name in ('24W_BUCK_VM_TPS40200', '24W_BUCK_PCM_LTC3864', '24W_BOOST_PCM_LM5022'):
                with self.subTest(example=name):
                    spec = load_spec(json.loads((ROOT/'examples'/(name+'.json')).read_text(encoding='utf-8')))
                    run = calculate_parameters(spec, analysis='endpoints', include_loop=True,
                                               include_cross_regulation=False, include_efficiency=True)
                    data = run.to_dict()
                    json.dumps(data, allow_nan=False)
                    self.assertEqual(len(data['cases']), 2)
                    for case in data['cases']:
                        self.assertIsNone(case['loop_error'])
                        self.assertTrue(case['summary']['ok'])
                        self.assertIsNone(case['summary']['loop']['dc_load_V_per_A'])
                    for suffix, required in (('.docx', 'word/document.xml'), ('.xlsx', 'xl/workbook.xml')):
                        target = Path(folder)/(name+suffix)
                        result = export_report(run, target)
                        self.assertEqual(result['successful_cases'], 2)
                        self.assertFalse(result['incomplete'])
                        with ZipFile(target) as archive:
                            self.assertIsNone(archive.testzip())
                            self.assertIn(required, archive.namelist())


if __name__ == '__main__':
    unittest.main()
