"""Boundary, evidence and native process-tree cancellation checks for the FEM bridge."""
from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import sys
import tempfile
import time
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import transformer_sim_runner as runner


class BridgeChecks(unittest.TestCase):
    def setUp(self):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.root = Path(directory.name)

    def test_mismatched_winding_turns_and_core_rejected_before_launch(self):
        geometry = dict(physical_sections=[dict(section_id='P_A', winding_id='P', turns=48)],
                        windings=[dict(id='P')], core=dict(calculator_core='PQ32-30'))
        settings = dict(primary_port='P', connections=dict(ports={'P': {}},
                        sections={'P_A': dict(winding_id='P', turns=12)}))
        with self.assertRaisesRegex(ValueError, 'P_A.*turns'):
            runner._check_windings(settings, geometry)
        package = self.root / 'test.zip'
        package.touch()
        template = self.root / 'settings.json'
        template.write_text(json.dumps(dict(schema='transformer-coupling-tool.project.v1',
                                 core=dict(calculator_core_model='PQ20-20'))), encoding='utf-8')
        with patch.object(runner, 'read_geometry_package', return_value=geometry):
            with self.assertRaisesRegex(ValueError, '磁芯型号不符'):
                runner.bind_solver_project(package, template, self.root)

    def test_report_rejects_mixed_package_and_changed_file(self):
        def save(name, value):
            (self.root / name).write_text(json.dumps(value), encoding='utf-8')

        package = self.root / 'design.zip'
        package.write_bytes(b'job-A')
        save('status.json', dict(status='complete', report='report.html'))
        member = dict(path='report.html', bytes=6, sha256=hashlib.sha256(b'report').hexdigest())
        manifest = dict(schema='transformer-coupling-tool.artifacts.v1',
                        source_package_sha256=hashlib.sha256(b'job-B').hexdigest(), files=[member])
        save('artifact-manifest.json', manifest)
        with self.assertRaisesRegex(ValueError, '几何 ZIP'):
            runner.verify_field_result(self.root, package)
        manifest['source_package_sha256'] = runner._sha(package)
        save('artifact-manifest.json', manifest)
        (self.root / 'report.html').write_bytes(b'BROKEN')
        with self.assertRaisesRegex(ValueError, '校验失败'):
            runner.verify_field_result(self.root, package)

    @unittest.skipUnless(os.name == 'nt', 'Windows Job Objects')
    def test_cancel_terminates_solver_grandchild(self):
        import _winapi
        child = ('from pathlib import Path; import os,time; '
                 'Path("solver.pid").write_text(str(os.getpid())); time.sleep(120)')
        parent = ('import sys,subprocess,time; '
                  f'subprocess.Popen([sys.executable,"-c",{child!r}]); time.sleep(120)')
        pidfile = self.root / 'solver.pid'
        with (self.root / 'console.log').open('wb') as log:
            with runner._field_process([sys.executable, '-c', parent], self.root, os.environ.copy(), log) as poll:
                limit = time.monotonic() + 10
                while not pidfile.exists() and time.monotonic() < limit and poll() is None:
                    time.sleep(.05)
                self.assertIsNone(poll())
                handle = _winapi.OpenProcess(_winapi.SYNCHRONIZE, False, int(pidfile.read_text()))
                self.addCleanup(_winapi.CloseHandle, handle)
                self.assertEqual(_winapi.WaitForSingleObject(handle, 0), _winapi.WAIT_TIMEOUT)
            self.assertEqual(_winapi.WaitForSingleObject(handle, 5000), _winapi.WAIT_OBJECT_0)


if __name__ == '__main__':
    unittest.main(verbosity=2)
