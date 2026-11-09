"""Real owned Tk: two endpoint visibility, drafts, save hook and stale evidence."""
import copy
import json
from pathlib import Path
import sys
import tkinter as tk
import tkinter.font as tkfont
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / 'tests'))
from engineering_acceptance_check import fixture
from engineering_acceptance_ui import AcceptancePanel
from engineering_acceptance import report_snapshot


class AcceptanceUIChecks(unittest.TestCase):
    def setUp(self):
        self.root = tk.Tk()
        self.root.attributes('-alpha', 0)
        # The headless Windows desktop advertises 512x384; explicitly permit
        # the requested 1000px review viewport, as the production app does.
        self.root.maxsize(3000, 2000)
        self.root.geometry('1000x740')
        self.p, self.bundle = fixture()
        self.saved, self.refreshes, self.errors = [], [], []
        self.root.report_callback_exception = lambda *exc: self.errors.append(str(exc))
        self.font = tkfont.nametofont('TkDefaultFont')
        self.original_font = self.font.actual()
        self.font.configure(size=13)
        self.panel = AcceptancePanel(self.root, get_spec=lambda: copy.deepcopy(self.p),
            get_range_result=lambda: self.bundle, on_apply=self.apply,
            on_refresh=lambda: self.refreshes.append(True))
        self.panel.pack(fill='both', expand=True)
        self.panel.refresh()
        self.root.update()

    def apply(self, value):
        self.saved.append(copy.deepcopy(value))
        self.p['engineering_acceptance'] = copy.deepcopy(value)

    def tearDown(self):
        self.font.configure(**self.original_font)
        self.root.destroy()

    def select(self, cid):
        self.panel.tree.selection_set(cid)
        self.panel._selected(force=True)
        self.root.update()

    def test_six_column_matrix_shows_both_endpoints_and_scrolls(self):
        panel = self.panel
        self.assertEqual(len(panel.tree['columns']), 6)
        bounds = panel.tree.bbox('eta', 'Vinmax_state')
        self.assertTrue(bounds)
        self.assertGreater(bounds[0], 0)
        self.assertLessEqual(bounds[0]+bounds[2], panel.tree.winfo_width()+3)
        self.assertGreater(panel.tree.bbox('eta')[3], self.font.metrics('linespace')*3)
        self.assertLess(panel.scroll.canvas.yview()[1], 1.)
        panel.scroll.canvas.yview_moveto(1)
        self.root.update()
        self.assertGreater(panel.scroll.canvas.yview()[0], 0.)
        self.font.configure(size=26)
        self.root.geometry('1000x740')
        panel._reflow()
        self.root.update()
        self.assertGreater(panel.tree.bbox('eta')[3], self.font.metrics('linespace')*3)
        self.assertLess(panel.scroll.canvas.yview()[1]-panel.scroll.canvas.yview()[0], 1.)
        self.assertEqual(self.errors, [])

    def test_targets_measurements_issues_save_reload_without_resolve(self):
        panel = self.panel
        self.select('out1_voltage')
        panel.target['comparison'].set('range')
        panel.target['lower'].set('11.5')
        panel.target['upper'].set('12.5')
        panel.required['simulation'].set(False)
        with patch('loss_model.compute_design', side_effect=AssertionError('editor must not calculate')):
            self.assertTrue(panel.apply_target())
            for case_id in ('Vinmin', 'Vinmax'):
                values = dict(value='12.1', source='DMM-1/人工记录', conditions='20V或30V 2A 25C 已注明探头', evidence_ref='scope1.csv')
                for key, value in values.items():
                    panel.measurement[case_id][key].set(value)
            with patch('engineering_acceptance_ui.messagebox.showerror') as error:
                self.assertFalse(panel.apply_measurements())
                self.assertTrue(error.called)
            panel.confirm_measurement.set(True)
            self.assertTrue(panel.apply_measurements())
            panel.issue['title'].set('启动尖峰待改进')
            panel.issue['action'].set('先核对钳位，再实测')
            self.assertTrue(panel.apply_issue())
        encoded = json.loads(json.dumps(self.p, ensure_ascii=False, allow_nan=False))
        self.assertEqual(len(encoded['engineering_acceptance']['measurements']), 2)
        self.assertEqual(encoded['engineering_acceptance'], self.saved[-1])
        self.assertIn('保存', panel.message.get())
        self.p = encoded
        panel.refresh()
        row = next(r for r in panel.snapshot['rows'] if r['id'] == 'out1_voltage')
        self.assertEqual(row['cases']['Vinmin']['status'], 'pass')
        self.assertEqual(row['cases']['Vinmax']['measurement'], 12.1)
        self.p['L'] *= 1.1
        panel.refresh()
        self.assertEqual(panel.tree.set('out1_voltage', 'Vinmin_state'), '已失效')
        self.assertFalse(panel.confirm_measurement.get())
        panel.request_refresh()
        self.assertEqual(len(self.refreshes), 1)
        imports = []
        panel.on_import_evidence = lambda: imports.append(True)
        panel.import_evidence()
        self.assertEqual(imports, [True])
        self.assertEqual(self.errors, [])

    def test_unapplied_draft_survives_snapshot_refresh_and_new_project_clears_it(self):
        self.select('primary_peak')
        self.panel.target['limit'].set('123.45')
        self.panel.refresh()
        self.root.update()
        self.assertEqual(self.panel.target['limit'].get(), '123.45')
        self.p['L'] *= 1.1
        self.panel.refresh()
        self.root.update()
        self.assertEqual(self.panel.target['limit'].get(), '')
        self.assertEqual(self.errors, [])

    def test_invalid_current_input_clears_previous_status(self):
        self.assertTrue(self.panel.tree.get_children())
        self.p['L'] = float('nan')
        self.panel.refresh()
        self.assertEqual(self.panel.tree.get_children(), ())
        self.assertIsNone(self.panel.snapshot)
        self.assertIn('未就绪', self.panel.summary.get())
        self.assertTrue(all('不沿用' in v.get() for v in self.panel.case_detail.values()))
        self.assertEqual(self.errors, [])


class RealApplicationFingerprintChecks(unittest.TestCase):
    def test_loaded_ui_and_normalized_spec_match_without_solving(self):
        import main
        from design_engine.specification import load_spec
        from engineering_acceptance import input_fingerprint
        root = tk.Tk()
        root.attributes('-alpha', 0)
        root.maxsize(3000, 2000)
        app = None
        try:
            with patch.object(main.PowerSupplyAnalyzer, 'schedule_update', return_value=None), patch(
                    'loss_model.compute_design', side_effect=AssertionError('identity loading must not solve')):
                app = main.PowerSupplyAnalyzer(root)
                for name in ('40W_CCM_3OUT_FLYBACK.json', '33W_3OUT_ACF_MP6005_COMPACT.json', '90W_QR_L6565_300V.json'):
                    with self.subTest(example=name):
                        raw = json.loads((ROOT/'examples'/name).read_text('utf-8-sig'))
                        normalized = load_spec(copy.deepcopy(raw))
                        app._apply_config(copy.deepcopy(raw))
                        self.assertEqual(input_fingerprint(normalized), input_fingerprint(app._current_spec()))
        finally:
            if app is not None:
                app._closing = True
                app._work_cancel.set()
            for job in root.tk.splitlist(root.tk.call('after', 'info')):
                root.after_cancel(job)
            root.destroy()


if __name__ == '__main__':
    unittest.main()
