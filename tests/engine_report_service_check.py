"""Real Word/Excel authoring consumes one prepared engineering snapshot."""
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch, Mock
from zipfile import ZipFile
from xml.etree import ElementTree as ET

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from runtime_resources import configure_numeric_threads
configure_numeric_threads()
from design_engine.service import calculate, export_report


class ReportServiceChecks(unittest.TestCase):
    def test_real_exports_do_not_recalculate_or_mutate_the_run(self):
        spec = json.loads((ROOT/'examples/40W_CCM_FLYBACK.json').read_text(encoding='utf-8'))
        spec.update(V_in_min=24., V_in_max=40., input_voltage_case='max')
        run = calculate(spec, analysis='endpoints', include_efficiency=True, include_cross_regulation=False)
        identity = run.to_dict()['snapshot_id']
        # Import authoring libraries before patching their legacy fallbacks.
        import report_docx
        import report_xlsx
        from docx import Document
        with tempfile.TemporaryDirectory() as directory:
            folder = Path(directory)
            with patch('loss_model.compute_design') as compute, \
                 patch('report_docx.compute_design') as fallback, \
                 patch('report_docx.loop_data') as loop, \
                 patch('design_checks.check_catalog') as checks:
                for suffix in ('.docx', '.xlsx'):
                    result = export_report(run, folder/('design' + suffix))
                    self.assertEqual(result['successful_cases'], 2)
                    self.assertFalse(result['incomplete'])
                compute.assert_not_called()
                fallback.assert_not_called()
                loop.assert_not_called()
                checks.assert_not_called()
            document = Document(folder/'design.docx')
            text = '\n'.join(paragraph.text for paragraph in document.paragraphs)
            combined=text+'\n'+'\n'.join(c.text for t in document.tables for r in t.rows for c in r.cells)
            self.assertIn('Vinmin', combined)
            self.assertIn('Vinmax', combined)
            self.assertIn('需求与共同硬件',text)
            self.assertGreater(len(document.inline_shapes), 5)
            with ZipFile(folder/'design.xlsx') as archive:
                self.assertIsNone(archive.testzip())
                sheets = ET.fromstring(archive.read('xl/workbook.xml')).findall('{*}sheets/{*}sheet')
                self.assertGreater(len(sheets), 5)
                self.assertGreater(len([name for name in archive.namelist() if name.startswith('xl/media/')]), 5)
        self.assertEqual(run.to_dict()['snapshot_id'], identity)

    def test_desktop_preparation_uses_the_shared_service(self):
        import main
        marker = object()
        cancel = lambda: False
        with patch('design_engine.service.prepare_endpoint_bundle', return_value=marker) as prepare:
            self.assertIs(main._calculate_input_report(dict(p={'V_in': 30}), cancel), marker)
            prepare.assert_called_once_with({'V_in': 30}, cancelled=cancel)

    def test_review_targets_are_frozen_before_preparation(self):
        import main
        app = main.PowerSupplyAnalyzer.__new__(main.PowerSupplyAnalyzer)
        app._engineering_acceptance = {}
        app.params = {'target_eta': Mock(get=lambda: .95), 'pm_target': Mock(get=lambda: 70.)}
        app.get_param = lambda key: 1200.
        app._winding_config = lambda: dict(winding_config=dict(window_width=0., window_height=0.))
        original = dict(V_in=30., target_eta=.9, pm_target=60., fc_target=1000.)
        prepared = app._report_input_parameters(original)
        self.assertEqual(prepared['target_eta'], .95)
        self.assertEqual(prepared['pm_target'], 70.)
        self.assertEqual(prepared['fc_target'], 1200.)
        self.assertEqual(original['target_eta'], .9)

    def test_changed_review_target_rejects_a_stale_report_without_mutation(self):
        import main
        spec = json.loads((ROOT/'examples/40W_CCM_FLYBACK.json').read_text(encoding='utf-8'))
        run = calculate(spec, analysis='endpoints', include_cross_regulation=False)
        bundle = run.runtime_bundle()
        app = main.PowerSupplyAnalyzer.__new__(main.PowerSupplyAnalyzer)
        app._engineering_acceptance = {}
        app._acceptance_evidence_reference = None
        app._acceptance_evidence_cache = None
        app._snapshot_valid = True
        app._last = {'p': bundle['base_spec']}
        app.root, app.status_var = Mock(), Mock()
        app.params = {'target_eta': Mock(get=lambda: .999),
                      'pm_target': Mock(get=lambda: bundle['base_spec']['pm_target'])}
        app.get_param = lambda key: bundle['base_spec'][key]
        app._winding_config = lambda: dict(winding_config=dict(window_width=0., window_height=0.))
        before = bundle['cases'][0]['p']['target_eta']
        with patch('main.tk.StringVar', return_value=Mock(get=lambda: 'Word 工程报告')), \
             patch('main.filedialog.asksaveasfilename', return_value='not_written.docx'), \
             patch('main.messagebox.showerror') as error, \
             patch('input_range_report.export_input_range_docx') as writer:
            app.export_report(recompute=False, range_result=bundle)
            writer.assert_not_called()
            error.assert_called_once()
            self.assertIn('已变化', error.call_args.args[1])
        self.assertEqual(bundle['cases'][0]['p']['target_eta'], before)

    def test_invalid_report_only_setting_does_not_escape_the_ui_callback(self):
        import main
        app = main.PowerSupplyAnalyzer.__new__(main.PowerSupplyAnalyzer)
        app._snapshot_valid, app._closing = True, False
        app._last = {'p': {}}
        app._export_after_calculation = True
        app._report_input_parameters = Mock(side_effect=ValueError('窗口宽度无效'))
        app._calculation_worker, app.status_var = Mock(), Mock()
        with patch('main.messagebox.showerror') as error:
            app._queue_report_efficiency_curve()
            error.assert_called_once_with('Export report', '窗口宽度无效')
        self.assertFalse(app._export_after_calculation)
        app._calculation_worker.submit.assert_not_called()


if __name__ == '__main__':
    unittest.main(verbosity=2)
