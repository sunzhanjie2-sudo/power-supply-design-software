"""User-facing CLI contract and predictable failure codes."""
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from zipfile import ZipFile

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from design_engine.service import read_snapshot


class CliChecks(unittest.TestCase):
    def call(self, *args):
        return subprocess.run([sys.executable, '-X', 'utf8', str(ROOT/'cli.py'), *map(str, args)],
            cwd=ROOT, capture_output=True, text=True, encoding='utf-8', timeout=120)

    def test_schema_and_validation_outputs_are_json(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory)/'nested/schema.json'
            result = self.call('parameters', '--schema', '--out', path)
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertEqual(json.loads(path.read_text(encoding='utf-8'))['type'], 'object')
            result = self.call('validate', '--spec', ROOT/'examples/40W_CCM_FLYBACK.json', '--out', path)
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertTrue(json.loads(path.read_text(encoding='utf-8'))['ok'])

    def test_invalid_input_returns_structured_issues_without_snapshot(self):
        with tempfile.TemporaryDirectory() as directory:
            folder = Path(directory)
            source, destination = folder/'bad.json', folder/'result.json'
            source.write_text(json.dumps({'V_im': 30}), encoding='utf-8')
            result = self.call('snapshot', '--spec', source, '--out', destination)
            self.assertEqual(result.returncode, 2)
            self.assertEqual(json.loads(result.stdout)['error'], 'invalid_spec')
            self.assertFalse(destination.exists())

    def test_solver_failure_is_not_success_or_a_traceback(self):
        with tempfile.TemporaryDirectory() as directory:
            folder = Path(directory)
            source, destination = folder/'bad_boost.json', folder/'result.json'
            source.write_text(json.dumps(dict(topology='BOOST', V_in=12., V_out=5.)), encoding='utf-8')
            result = self.call('snapshot', '--spec', source, '--out', destination)
            self.assertEqual(result.returncode, 2)
            self.assertEqual(json.loads(result.stdout)['error'], 'calculation_failed')
            self.assertNotIn('Traceback', result.stderr)
            self.assertFalse(destination.exists())

    def test_real_snapshot_and_excel_report(self):
        with tempfile.TemporaryDirectory() as directory:
            folder = Path(directory)
            source = ROOT/'examples/40W_CCM_FLYBACK.json'
            destination = folder/'snapshot.json'
            result = self.call('snapshot', '--spec', source, '--analysis', 'endpoints', '--no-waveforms', '--out', destination)
            self.assertEqual(result.returncode, 0, result.stderr)
            snapshot = read_snapshot(destination)
            self.assertEqual([case['id'] for case in snapshot['cases']], ['Vinmin', 'Vinmax'])
            self.assertNotIn('wf', snapshot['cases'][0]['result'])
            destination = folder/'设计报告.xlsx'
            result = self.call('report', '--spec', source, '--out', destination)
            self.assertEqual(result.returncode, 0, result.stderr)
            with ZipFile(destination) as archive:
                self.assertIsNone(archive.testzip())
                self.assertIn('xl/workbook.xml', archive.namelist())


if __name__ == '__main__':
    unittest.main(verbosity=2)
