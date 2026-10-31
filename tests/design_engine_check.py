"""Service contracts, ownership, cancellation, baseline and legacy parity."""
import copy
import json
import math
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from runtime_resources import configure_numeric_threads
configure_numeric_threads()
import numpy as np
from engine_baseline_cases import CASES, case_spec, metrics
from design_engine.catalog import parameter_catalog, specification_schema
from design_engine.contracts import json_value
from design_engine.service import (calculate, calculate_parameters, read_snapshot,
                                  validate_spec, SpecValidationError, export_report)
from design_api import load_spec, run_design, run_input_endpoints
from calculation_scheduler import CalculationCancelled
from power_stage import DEFAULT_PARAMS


class ContractChecks(unittest.TestCase):
    def test_import_is_lightweight_and_gui_free(self):
        code = "import sys, design_engine.service, design_engine.catalog; assert not {'tkinter','main','numpy','scipy','control','matplotlib','docx','openpyxl'} & set(sys.modules)"
        subprocess.run([sys.executable, '-c', code], cwd=ROOT, check=True, capture_output=True)

    def test_real_calculation_does_not_import_the_desktop_or_tk(self):
        code = "import sys; from design_engine.service import calculate; r=calculate({}); assert r.to_dict(include_details=False)['ok']; assert not {'tkinter','main'} & set(sys.modules)"
        subprocess.run([sys.executable, '-c', code], cwd=ROOT, check=True, capture_output=True)

    def test_catalogue_covers_existing_defaults_without_aliasing(self):
        rows = parameter_catalog()
        self.assertEqual(len(rows), len({row['name'] for row in rows}))
        self.assertTrue(set(DEFAULT_PARAMS) <= {row['name'] for row in rows})
        next(row for row in rows if row['name'] == 'coupling_config')['default']['enabled'] = True
        self.assertFalse(DEFAULT_PARAMS['coupling_config']['enabled'])
        with self.assertRaises(ValueError):
            parameter_catalog('NONEXISTENT')

    def test_catalogue_units_keep_percent_as_stored_ratio(self):
        row = next(row for row in parameter_catalog() if row['name'] == 'eta_guess')
        self.assertEqual((row['unit'], row['display_unit'], row['display_factor']), ('', '%', 100))

    def test_schema_is_valid_and_accepts_existing_examples(self):
        from jsonschema import Draft202012Validator, ValidationError
        schema = specification_schema()
        Draft202012Validator.check_schema(schema)
        validator = Draft202012Validator(schema)
        for name in CASES:
            with self.subTest(name=name):
                validator.validate(case_spec(name))
        with self.assertRaises(ValidationError):
            validator.validate({'V_im': 30})

    def test_input_validation_never_solves_converter(self):
        with patch('loss_model.compute_design', side_effect=AssertionError('unexpected solve')):
            self.assertTrue(validate_spec(case_spec(CASES[0]))['ok'])

    def test_invalid_input_issues_are_structured(self):
        for changes in (dict(V_in=True), dict(V_in='bad'), dict(eta_guess=0), dict(V_in=float('nan')),
                        dict(C_out=[]), dict(unknown_parameter=1),
                        dict(custom_core={'Ae': float('nan')}, core_choice='auto')):
            with self.subTest(changes=changes):
                outcome = validate_spec(dict(case_spec(CASES[0]), **changes))
                self.assertFalse(outcome['ok'])
                self.assertTrue(outcome['issues'])
                self.assertTrue({'field', 'code', 'message'} <= outcome['issues'][0].keys())
        with self.assertRaises(SpecValidationError):
            calculate([])

    def test_json_is_strict_and_preserves_explicit_nonfinite_diagnostics(self):
        diagnostics = []
        value = json_value(dict(x=np.array([1., np.inf, np.nan]), c=2+3j), diagnostics)
        json.dumps(value, allow_nan=False)
        self.assertEqual(value['x'], [1., None, None])
        self.assertEqual(value['c'], dict(real=2., imag=3.))
        self.assertEqual([row['path'] for row in diagnostics], ['$.x[1]', '$.x[2]'])
        with self.assertRaises(TypeError):
            json_value(object())

    def test_old_defaults_and_input_curves_are_owned(self):
        a = load_spec({})
        a['custom_core']['name'] = 'changed'
        self.assertNotIn('name', load_spec({})['custom_core'])


class CalculationChecks(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.runs = {name: calculate(case_spec(name)) for name in CASES}
        cls.expected = json.loads((ROOT/'tests/fixtures/engine_baseline_20261022.json').read_text(encoding='utf-8'))
        cls.ranged_spec = dict(case_spec(CASES[0]), V_in_min=24., V_in_max=40., input_voltage_case='max')
        cls.range_run = calculate(cls.ranged_spec, analysis='endpoints', include_cross_regulation=False)

    def test_pre_refactor_numerical_baselines(self):
        for name, run in self.runs.items():
            case = run.runtime_bundle()['cases'][0]
            actual = metrics(dict(res=case['result'], op=case['result']['op'], wf=case['result']['wf']))
            for key, expected in self.expected[name].items():
                with self.subTest(name=name, metric=key):
                    if isinstance(expected, (int, float)):
                        self.assertTrue(math.isclose(actual[key], expected, rel_tol=2e-9, abs_tol=1e-11),
                                        (actual[key], expected))
                    else:
                        self.assertEqual(actual[key], expected)

    def test_legacy_api_and_service_match(self):
        for name, run in self.runs.items():
            with self.subTest(name=name):
                legacy = run_design(case_spec(name))
                shared = run.legacy_report()
                self.assertEqual(legacy['operating_point'], shared['operating_point'])
                self.assertEqual(legacy['losses'], shared['losses'])
                self.assertEqual(legacy['checks'], shared['checks'])

    def test_selected_endpoint_and_full_range_share_hardware_and_values(self):
        selected = calculate(self.ranged_spec)
        full = self.range_run.runtime_bundle()
        self.assertEqual(selected.runtime_bundle()['hardware'], full['hardware'])
        self.assertEqual(selected.legacy_report()['losses'], self.range_run.reports()[1]['report']['losses'])
        self.assertNotEqual(full['cases'][0]['result']['op']['D'], full['cases'][1]['result']['op']['D'])

    def test_legacy_endpoint_report_shape_and_values(self):
        old = run_input_endpoints(self.ranged_spec)
        new = self.range_run.legacy_endpoints()
        self.assertEqual(old['hardware'], new['hardware'])
        self.assertEqual([c['report']['losses'] for c in old['cases']],
                         [c['report']['losses'] for c in new['cases']])

    def test_reading_summaries_and_snapshots_never_recalculates(self):
        run = self.runs[CASES[0]]
        with patch('loss_model.compute_design', side_effect=AssertionError('unexpected solve')), \
             patch('loop_tuning.analyze_loop', side_effect=AssertionError('unexpected loop analysis')):
            self.assertTrue(run.reports()[0]['report']['ok'])
            self.assertTrue(run.to_dict()['ok'])

    def test_caller_and_snapshot_mutations_are_isolated(self):
        spec = copy.deepcopy(self.ranged_spec)
        saved = copy.deepcopy(spec)
        run = calculate(spec)
        self.assertEqual(spec, saved)
        snapshot = run.to_dict()
        original = snapshot['spec']['V_in']
        spec['V_in'] = 999
        snapshot['spec']['V_in'] = 888
        bundle = run.runtime_bundle()
        bundle['cases'][0]['p']['V_in'] = 777
        self.assertEqual(run.to_dict()['spec']['V_in'], original)

    def test_strict_serialization_for_all_cases_and_deterministic_identity(self):
        for name, run in self.runs.items():
            with self.subTest(name=name):
                a, b = run.to_dict(), run.to_dict()
                json.dumps(a, allow_nan=False)
                self.assertEqual(a['snapshot_id'], b['snapshot_id'])
                self.assertEqual(a['provenance']['model_version'], 'legacy-model-2026-10-21')
                self.assertEqual(len(a['provenance']['code_fingerprint']), 64)
                self.assertNotIn('models', a['cases'][0])

    def test_saved_audit_snapshot_verifies_content_and_detects_tampering(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory)/'设计快照.json'
            identity = self.range_run.save(path)
            payload = read_snapshot(path)
            self.assertEqual(payload['snapshot_id'], identity)
            payload['spec']['V_in'] += 1
            path.write_text(json.dumps(payload, ensure_ascii=False), encoding='utf-8')
            with self.assertRaisesRegex(ValueError, '哈希'):
                read_snapshot(path)

    def test_cancel_is_never_reported_as_valid_design(self):
        for mode in ('selected', 'endpoints'):
            with self.subTest(mode=mode), self.assertRaises(CalculationCancelled):
                calculate(self.ranged_spec, analysis=mode, cancelled=lambda: True)
        with patch('design_engine.service.calculate_parameters', side_effect=CalculationCancelled()):
            with self.assertRaises(CalculationCancelled):
                run_design(self.ranged_spec)

    def test_invalid_analysis_is_rejected(self):
        with self.assertRaises(ValueError):
            calculate(self.ranged_spec, analysis='all')

    def test_export_requires_prepared_endpoint_efficiency_data(self):
        with self.assertRaisesRegex(ValueError, 'endpoints'):
            export_report(self.runs[CASES[0]], 'unused.xlsx')
        with self.assertRaisesRegex(ValueError, '效率扫描'):
            export_report(self.range_run, 'unused.xlsx')

    def test_mcp_new_contract_tools_smoke(self):
        from importlib.util import find_spec
        if find_spec('mcp') is None:
            self.skipTest('optional MCP transport not installed')
        import mcp_server
        outcome = json.loads(mcp_server.validate_spec(json.dumps(self.ranged_spec)))
        self.assertTrue(outcome['ok'])
        self.assertEqual(json.loads(mcp_server.parameter_schema())['type'], 'object')
        snapshot = json.loads(mcp_server.design_snapshot(json.dumps(case_spec(CASES[0]))))
        self.assertTrue(snapshot['ok'])
        self.assertIsNone(snapshot['cases'][0]['result'])
        self.assertIn('operating_point', snapshot['cases'][0]['summary'])

    def test_internal_solver_traces_are_not_duplicated_in_wire_results(self):
        run = self.runs['3_OUTPUT_COUPLED_FLYBACK.json']
        full = run.to_dict()
        self.assertNotIn('coupled_solution', json.dumps(full))
        self.assertIn('wf', full['cases'][0]['result'])
        compact = run.to_dict(include_waveforms=False, include_details=False)
        self.assertIsNone(compact['cases'][0]['result'])
        self.assertLess(len(json.dumps(compact)), len(json.dumps(full)))


if __name__ == '__main__':
    unittest.main(verbosity=2)
