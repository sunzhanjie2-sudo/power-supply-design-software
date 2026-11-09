"""Acceptance metadata is saved without changing the electrical snapshot."""
import copy
from pathlib import Path
import sys
import tempfile
import json
import tkinter as tk
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from runtime_resources import configure_numeric_threads
configure_numeric_threads()
from config_io import read_default_config
from design_engine.specification import load_spec
from engineering_acceptance import normalize, input_fingerprint, report_snapshot


def settings():
    return normalize(dict(criteria=[dict(id='eta', metric='eta', name='效率核查', unit='',
        comparison='>=', limit=.80, required_sources=['calculation'], enabled=True)]))


class Transport(unittest.TestCase):
    def test_schema_and_web_normalization_keep_owned_records(self):
        from web_app.metadata import normalize_config
        raw = read_default_config()
        raw['engineering_acceptance'] = settings()
        for decoder in (load_spec, normalize_config):
            p = decoder(raw)
            self.assertEqual(p['engineering_acceptance'], settings())
            p['engineering_acceptance']['criteria'][0]['name'] = '独立副本'
            self.assertEqual(raw['engineering_acceptance'], settings())
        self.assertNotIn('engineering_acceptance', read_default_config())


class Desktop(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        import main
        cls.main = main
        cls.root = tk.Tk()
        cls.root.withdraw()
        cls.scheduling = patch.object(main.PowerSupplyAnalyzer, 'schedule_update', return_value=None)
        cls.scheduling.start()
        cls.app = main.PowerSupplyAnalyzer(cls.root)
        cls.errors = []
        cls.root.report_callback_exception = lambda *args: cls.errors.append(args)

    @classmethod
    def tearDownClass(cls):
        cls.app._closing = True
        cls.app._calculation_worker.close()
        for job in cls.root.tk.call('after', 'info'):
            cls.root.after_cancel(job)
        cls.root.destroy()
        cls.scheduling.stop()

    def setUp(self):
        self.app._apply_config(read_default_config())
        self.assertTrue(self.app.update_all(), self.app.status_var.get())

    def test_metadata_apply_save_and_reopen_without_resolve(self):
        app = self.app
        before = app._last
        old_p = copy.deepcopy(before['p'])
        identity = id(before['res'])
        with patch('loss_model.compute_design', side_effect=AssertionError('metadata must not solve')):
            app._acceptance_apply(settings())
            saved = app._config_dict()
        self.assertEqual(id(app._last['res']), identity)
        self.assertEqual(before['p'], old_p, 'cached input wrapper must not be mutated')
        self.assertEqual(input_fingerprint(old_p), input_fingerprint(app._last['p']))
        self.assertEqual(saved['engineering_acceptance'], settings())
        app._apply_config(saved)
        self.assertEqual(app.get_params()['engineering_acceptance'], settings())
        app._apply_config(read_default_config())
        self.assertEqual(app.get_params()['engineering_acceptance'], normalize())

    def test_current_selected_case_does_not_fake_the_other_endpoint(self):
        app = self.app
        app._acceptance_apply(settings())
        bundle = app._acceptance_get_range_result()
        self.assertEqual(len(bundle['cases']), 1)
        snap = report_snapshot(app._current_spec(), range_result=bundle)
        row = next(r for r in snap['rows'] if r['id'] == 'eta')
        self.assertIsNotNone(row['cases']['Vinmin']['calculation'])
        self.assertIsNone(row['cases']['Vinmax']['calculation'])
        self.assertNotEqual(row['cases']['Vinmax']['status'], 'pass')

    def test_refresh_is_explicit_background_work(self):
        app = self.app
        with patch.object(app._calculation_worker, 'submit') as submit, \
             patch.object(app, '_ensure_calculation_poll'):
            app.acceptance_panel.refresh()
            submit.assert_not_called()
            app._acceptance_refresh_endpoints()
            self.assertEqual(submit.call_args.args[0], 'acceptance_endpoints')
            self.assertIs(submit.call_args.args[2], self.main._calculate_acceptance_endpoints)
        self.root.update()
        self.assertEqual(self.errors, [])

    def test_imported_evidence_reference_survives_project_reload_and_detects_changes(self):
        app = self.app
        with tempfile.TemporaryDirectory() as folder:
            path=Path(folder)/'comparison.json'
            payload=dict(schema='powerdesign-spice-comparison-2',
                input_fingerprint=input_fingerprint(app._current_spec()),cases=[])
            path.write_text(json.dumps(payload),encoding='utf-8')
            with patch.object(self.main.filedialog,'askopenfilename',return_value=str(path)):
                app._acceptance_import_evidence()
            saved=app._config_dict()
            self.assertIn('__acceptance_evidence',saved)
            app._apply_config(saved)
            self.assertEqual(app._acceptance_get_spice_evidence()['evidence'],payload)
            payload['cases']=[dict(id='Vinmin',complete=False)]
            path.write_text(json.dumps(payload),encoding='utf-8')
            self.assertIn('已变化',app._acceptance_get_spice_evidence()['evidence_error'])
            app.acceptance_panel.refresh()
            self.assertTrue(any('已变化' in n for n in app.acceptance_panel.snapshot['evidence_notes']))


if __name__ == '__main__':
    unittest.main(verbosity=2)
