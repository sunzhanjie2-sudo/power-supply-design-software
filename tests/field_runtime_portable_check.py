"""Portable built-in FEM worker boundaries without launching a heavy field solve."""
from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
import transformer_sim_runner as runner


class PortableRuntimeChecks(unittest.TestCase):
    def setUp(self):
        directory = tempfile.TemporaryDirectory(prefix='field-portable-')
        self.addCleanup(directory.cleanup)
        self.root = Path(directory.name)

    def test_builtin_command_needs_no_external_tool_or_venv(self):
        command = runner._solver_command('builtin', self.root)
        self.assertEqual(command[0], sys.executable)
        self.assertIn('--field-worker', command)
        self.assertIn(str(ROOT / 'desktop_entry.py'), command)
        self.assertEqual(command, runner._solver_command('', self.root))
        with patch.object(sys, 'frozen', True, create=True):
            self.assertEqual(runner._solver_command('builtin', self.root),
                             [sys.executable, '--field-worker'])

    def test_runtime_cache_uses_task_directory(self):
        from transformer_field_runtime.storage import app_home
        with patch.dict(os.environ, {'POWER_DESIGN_FIELD_WORKDIR': str(self.root)}):
            self.assertEqual(app_home(), self.root.resolve())
        with patch.dict(os.environ, {}, clear=True):
            self.assertTrue(app_home().is_relative_to(Path(tempfile.gettempdir())))
            self.assertNotEqual(app_home(), ROOT)

    def test_explicit_elmer_selection_beats_stale_environment(self):
        package = self.root / 'geometry.zip'
        package.write_bytes(b'package')
        core = self.root / 'core.step'
        core.write_bytes(b'CAD check is performed by the worker')
        elmer = self.root / 'selected solver'
        (elmer / 'bin').mkdir(parents=True)
        for name in ('ElmerSolver.exe', 'ElmerGrid.exe'):
            (elmer / 'bin' / name).touch()
        project = dict(schema='transformer-coupling-tool.project.v1',
                       core=dict(calculator_core_model='PQ20-20', path=str(core), mode='assembled'),
                       material=dict(name='DMR44'), frame={}, solver=dict(elmer_home=str(elmer)))
        template = self.root / 'project.json'
        template.write_text(json.dumps(project), encoding='utf-8')
        geometry = dict(core=dict(calculator_core='PQ20-20', calculator_material='DMR44'),
                        design_targets={}, frame={}, source=dict(design_id='portable'))
        with patch.object(runner, 'read_geometry_package', return_value=geometry), \
                patch.object(runner, '_check_windings'), \
                patch.dict(os.environ, {'ELMER_HOME': str(self.root / 'old missing solver')}):
            resolved = runner.bind_solver_project(package, template, self.root)
        self.assertEqual(Path(resolved['solver']['elmer_home']), elmer.resolve())

    def test_source_provenance_matches_all_copied_modules(self):
        folder = ROOT / 'transformer_field_runtime'
        manifest = json.loads((folder / 'SOURCE_MANIFEST.json').read_text('utf-8'))
        self.assertFalse(manifest['physical_model_changed'])
        self.assertGreaterEqual(len(manifest['files']), 17)
        for entry in manifest['files']:
            self.assertEqual(Path(entry['path']).name, entry['path'])
            path = folder / entry['path']
            self.assertEqual(hashlib.sha256(path.read_bytes()).hexdigest(), entry['bundled_sha256'])
            self.assertEqual(len(entry['source_sha256']), 64)

    def test_actual_worker_doctor_from_unrelated_directory(self):
        work = self.root / '任务 缓存'
        work.mkdir()
        events = self.root / 'doctor.jsonl'
        environment = os.environ.copy()
        environment['POWER_DESIGN_FIELD_WORKDIR'] = str(work)
        for key in ('PYTHONHOME', 'PYTHONPATH', 'VIRTUAL_ENV'):
            environment.pop(key, None)
        command = runner._solver_command('builtin', work)
        result = subprocess.run(command + ['doctor', '--events', str(events)], cwd=self.root,
                                env=environment, capture_output=True, timeout=45)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        lines = [json.loads(s[8:]) for s in events.read_text('utf-8').splitlines()
                 if s.startswith('@@EVENT ')]
        self.assertEqual(lines[-1]['stage'], 'doctor')
        self.assertEqual(lines[-1]['gmsh'], '4.15.2')
        self.assertEqual(Path(lines[-1]['work_directory']), work.resolve())
        self.assertFalse(any(self.root.glob('*.exe')))

    def test_worker_failure_keeps_diagnostic_and_no_complete_event(self):
        events = self.root / 'failed.jsonl'
        environment = os.environ.copy()
        environment['POWER_DESIGN_FIELD_WORKDIR'] = str(self.root / 'cache')
        result = subprocess.run(runner._solver_command('', self.root) + [
            'check', '--project', str(self.root / 'missing.json'), '--events', str(events)],
            cwd=self.root, env=environment, capture_output=True, timeout=15)
        self.assertEqual(result.returncode, 1)
        text = events.read_text('utf-8')
        self.assertIn('@@EVENT {"stage": "error"', text)
        self.assertNotIn('"stage": "complete"', text)


if __name__ == '__main__':
    unittest.main(verbosity=2)
