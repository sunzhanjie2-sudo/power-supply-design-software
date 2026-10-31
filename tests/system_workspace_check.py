"""System-tree persistence, electrical interfaces and actual Tk return lifecycle."""
import copy
import json
from pathlib import Path
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
import system_workspace as w


class SystemChecks(unittest.TestCase):
    def test_legacy_config_metadata_and_roundtrip(self):
        raw = json.loads((ROOT/'examples/40W_CCM_3OUT_FLYBACK.json').read_text(encoding='utf-8'))
        p = w.normalize_project(w.fresh_project(raw))
        self.assertEqual(p['units'][0]['spec']['__comp'], raw['__comp'])
        self.assertEqual(len(p['units'][0]['rails']), 3)
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory)/'系统工程.json'
            w.save_project(p, path)
            self.assertEqual(w.load_project(path), p)
            path.write_text(json.dumps(raw), encoding='utf-8')
            imported = w.load_project(path)
            self.assertEqual(imported['units'][0]['spec']['__comp'], raw['__comp'])

    def test_cascade_budget_sync_and_cycle_rejection(self):
        p = w.normalize_project(w.fresh_project())
        buck = json.loads((ROOT/'examples/24W_BUCK_VM_TPS40200.json').read_text(encoding='utf-8'))
        p['units'].append(dict(id='PSU-02', name='下级 Buck', source=w.disconnected(), spec=buck))
        p = w.normalize_project(p)
        w.connect(p, 'PSU-02', dict(kind='unit', id='PSU-01', output=1))
        w.sync_input(p, 'PSU-02')
        self.assertEqual(p['units'][1]['spec']['V_in_min'], 30)
        self.assertEqual(p['units'][1]['spec']['V_in_max'], 30)
        rows = w.checks(p)
        self.assertTrue(rows['interfaces'][1]['ok'])
        demand = p['units'][1]['spec']['P_out']/p['units'][1]['spec']['eta_guess']
        self.assertAlmostEqual(next(r['allocated'] for r in rows['capacity'] if r['port']=='PSU-01/OUT1'), demand)
        before = copy.deepcopy(p)
        with self.assertRaises(ValueError):
            w.connect(p, 'PSU-01', dict(kind='unit', id='PSU-02', output=1))
        self.assertEqual(p, before)

    def test_port_reduction_delete_and_restore_preserve_child(self):
        raw = json.loads((ROOT/'examples/40W_CCM_3OUT_FLYBACK.json').read_text(encoding='utf-8'))
        p = w.normalize_project(w.fresh_project(raw))
        p['units'].append(dict(id='PSU-02', name='下级', source=dict(kind='unit', id='PSU-01', output=3), spec=w.fresh_project()['units'][0]['spec']))
        p = w.normalize_project(p)
        w.connect(p, 'PSU-02', dict(kind='unit', id='PSU-01', output=3))
        child = copy.deepcopy(p['units'][1]['spec'])
        detached = w.set_unit_config(p, 'PSU-01', w.fresh_project()['units'][0]['spec'])
        self.assertEqual(detached, ['PSU-02'])
        self.assertEqual(w.incoming(p, 'PSU-02'), [])
        self.assertEqual(p['units'][1]['spec'], child)
        w.connect(p, 'PSU-02', dict(kind='unit', id='PSU-01', output=1))
        record = w.remove_node(p, 'unit', 'PSU-01')
        self.assertEqual(p['units'][0]['spec'], child)
        w.restore_node(p, record)
        self.assertEqual(w.incoming(p, 'PSU-02')[0]['source']['id'], 'PSU-01')


class DesktopLifecycle(unittest.TestCase):
    def test_first_screen_and_two_independent_calculators_return(self):
        import ctypes
        try:
            ctypes.windll.shcore.SetProcessDpiAwareness(1)
        except (AttributeError, OSError):
            pass
        import tkinter as tk
        from system_workspace_ui import SystemWorkspace
        root = tk.Tk()
        errors = []
        root.report_callback_exception = lambda *error: errors.append(str(error[1]))
        try:
            shell = SystemWorkspace(root, recovery=False)
            shell.initialize()
            self.assertIsNone(shell.calculator)
            self.assertEqual(len(shell.project['units']), 1)
            shell.add_unit()
            shell.project['units'][1]['name'] = '独立 Buck'
            buck = json.loads((ROOT/'examples/24W_BUCK_VM_TPS40200.json').read_text(encoding='utf-8'))
            w.set_unit_config(shell.project, 'PSU-02', buck)
            for identity in ('PSU-01','PSU-02','PSU-01'):
                shell.open_unit(identity)
                app = shell.calculator
                self.assertIsNotNone(app)
                self.assertEqual(app._topo_key(), 'BUCK' if identity=='PSU-02' else 'FLYBACK')
                if identity=='PSU-01':
                    app.set_param('P_out', 42)
                app.on_close()
                self.assertTrue(root.winfo_exists())
                self.assertIsNone(shell.calculator)
                self.assertEqual(w.unit_by_id(shell.project, identity)['spec']['P_out'], 24 if identity=='PSU-02' else 42)
            root.update()
            # No dangling bind_all handlers referring to destroyed Toplevels.
            root.event_generate('<MouseWheel>', delta=-120)
            root.update()
            self.assertEqual(errors, [])
            from PIL import ImageGrab
            root.geometry('1440x900+0+0')
            shell.render();root.update()
            dest = ROOT/'artifacts/qa/system_workspace_20261031/desktop.png'
            dest.parent.mkdir(parents=True, exist_ok=True)
            ImageGrab.grab(bbox=(root.winfo_rootx(),root.winfo_rooty(),root.winfo_rootx()+root.winfo_width(),root.winfo_rooty()+root.winfo_height())).save(dest)
        finally:
            if shell.calculator:
                shell.calculator._workspace_return = lambda app: True
                shell.calculator.on_close()
            root.destroy()


if __name__ == '__main__':
    unittest.main(verbosity=2)
