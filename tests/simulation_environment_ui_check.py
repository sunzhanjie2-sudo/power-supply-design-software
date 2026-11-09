"""Tk boundary checks for portable solver settings, no external solve."""
from contextlib import ExitStack
import copy
from pathlib import Path
import sys
import threading
import time
import tkinter as tk
from tkinter import ttk
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from simulation_environment_ui import EnvironmentPanel, CORE_MODES


class PortableEnvironmentUI(unittest.TestCase):
    def setUp(self):
        self.stack = ExitStack()
        self.root = tk.Tk()
        self.root.withdraw()
        self.errors = []
        self.root.report_callback_exception = lambda *args:self.errors.append(str(args[1]))
        self.values = dict(elmer_home='D:/ElmerFEM', ltspice='D:/LTspice/LTspice.exe',
            core_path='C:/model/core.step', core_model='PQ32-30', core_mode='half_center_gap',
            brep_unit='mm', translation_mm=[1.,2.,3.], rotation_deg=[0.,0.,0.],
            center_leg_radius_m=.006725, gap_center_z_m=0., r0_m=.008, z0_m=-.0094,
            mesh_profile='standard', air_radius_m=.05, timeout_s=1200, core_source='厂家CAD与装配记录')
        self.config = {'core_choice':'PQ32-30'}
        self.panel = EnvironmentPanel(self.root, self.config, initial=self.values)
        self.panel.pack(fill='both', expand=True)
        self.root.update()

    def tearDown(self):
        self.root.destroy()
        self.stack.close()
        self.assertEqual(self.errors, [])

    def drain(self, predicate, timeout=3):
        until = time.monotonic() + timeout
        while not predicate() and time.monotonic() < until:
            self.root.update()
            time.sleep(.01)
        self.assertTrue(predicate())

    def test_units_and_current_model_snapshot_keep_independent_values(self):
        self.assertEqual(self.panel._values['r0_m'].get(), '8')
        self.panel._values['r0_m'].set('8.5')
        snapshot = self.panel.snapshot()
        self.assertEqual(snapshot['r0_m'], .0085)
        self.assertEqual(snapshot['center_leg_radius_m'], .006725)
        self.assertEqual(snapshot['core_mode'], 'half_center_gap')
        self.assertEqual(snapshot['translation_mm'], [1.,2.,3.])
        snapshot['translation_mm'][0] = 999
        self.assertEqual(self.panel.snapshot()['translation_mm'][0], 1.)

    def test_same_model_refresh_does_not_erase_unsaved_user_edits(self):
        self.panel._values['core_path'].set('C:/new/core.step')
        self.panel._values['r0_m'].set('9.1')
        self.panel.set_config(dict(self.config, P_out=92))
        self.assertEqual(self.panel.snapshot()['core_path'], 'C:/new/core.step')
        self.assertEqual(self.panel.snapshot()['r0_m'], .0091)
        new = dict(self.values, core_model='PQ20-20', r0_m=.004)
        with patch('simulation_environment.load_environment', return_value=new) as load:
            self.panel.set_config({'core_choice':'PQ20-20'})
        load.assert_called_once()
        self.assertEqual(self.panel.snapshot()['r0_m'], .004)

    def test_check_probes_off_thread_and_publishes_only_on_tk_thread(self):
        entered = threading.Event()
        release = threading.Event()
        self.addCleanup(release.set)
        def check(values, require_spice, probe):
            self.assertIsNot(threading.current_thread(), threading.main_thread())
            self.assertEqual(values['r0_m'], .008)
            self.assertTrue(require_spice)
            self.assertTrue(probe)
            entered.set()
            release.wait(2)
            return {'ok':False, 'checks':[{'name':'Elmer', 'ok':False, 'message':'缺少运行库'}]}
        with patch('simulation_environment.check_environment', side_effect=check) as checker:
            self.panel.check_button.invoke()
            self.assertTrue(entered.wait(1))
            self.assertTrue(self.panel._checking)
            self.assertIn('正在检查', self.panel.status.get())
            self.panel.check()
            self.assertEqual(checker.call_count, 1)
            marker = []
            self.root.after(0, lambda:marker.append(True))
            self.root.update()
            self.assertEqual(marker, [True], '环境检测不得阻塞Tk')
            release.set()
            self.drain(lambda:not self.panel._checking)
        self.assertIn('缺少运行库', self.panel.status.get())
        self.assertIn('未通过', self.panel.status.get())

    def test_destroy_while_probe_is_running_does_not_touch_destroyed_widgets(self):
        release = threading.Event()
        self.addCleanup(release.set)
        def check(*args, **kwargs):
            release.wait(2)
            return {'ok':True, 'checks':[]}
        with patch('simulation_environment.check_environment', side_effect=check):
            self.panel.check()
            self.panel.destroy()
            release.set()
            self.root.update()
        self.assertTrue(self.panel._closed)
        self.assertIsNone(self.panel._poll_id)

    def test_save_uses_plain_snapshot_and_updates_registered_cad_location(self):
        def save(config, values):
            self.assertIs(threading.current_thread(), threading.main_thread())
            self.assertEqual(config, self.config)
            self.assertEqual(values['core_mode'], 'half_center_gap')
            return dict(values, core_path='C:/portable/simulation-models/hash/core.step')
        with patch('simulation_environment.save_environment', side_effect=save):
            self.panel.save()
        self.assertEqual(self.panel.snapshot()['core_path'], 'C:/portable/simulation-models/hash/core.step')
        self.assertIn('已保存', self.panel.status.get())

    def test_changed_cad_does_not_keep_old_geometric_certification(self):
        self.panel._source.update(core_sha256='old', cad_verified=True)
        self.panel._values['core_path'].set('C:/another.step')
        snapshot = self.panel.snapshot()
        self.assertNotIn('core_sha256', snapshot)
        self.assertNotIn('cad_verified', snapshot)

    def test_model_import_keeps_machine_executables(self):
        imported = {key:copy.deepcopy(value) for key,value in self.values.items()
                    if key not in ('elmer_home','ltspice')}
        imported['core_path'] = 'C:/imported/core.step'
        with patch('simulation_environment_ui.filedialog.askopenfilename', return_value='model.zip'), \
             patch('simulation_environment.import_model_package', return_value=imported) as load:
            self.panel.import_model()
        load.assert_called_once_with('model.zip', 'PQ32-30')
        snapshot = self.panel.snapshot()
        self.assertEqual(snapshot['elmer_home'], self.values['elmer_home'])
        self.assertEqual(snapshot['ltspice'], self.values['ltspice'])
        self.assertEqual(snapshot['core_path'], 'C:/imported/core.step')

    def test_narrow_large_font_actions_reflow_and_no_automatic_solver(self):
        self.root.deiconify()
        style = ttk.Style(self.root)
        old = style.configure('TButton').get('font')
        style.configure('TButton', font=('Microsoft YaHei UI', 20))
        try:
            self.root.geometry('680x700')
            self.root.update()
            self.panel._layout()
            self.root.update()
            buttons = self.panel._action_widgets
            self.assertGreater(max(int(b.grid_info()['row']) for b in buttons), 0)
            for button in buttons:
                self.assertLessEqual(button.winfo_x() + button.winfo_width(), self.panel._actions.winfo_width() + 1)
            self.assertFalse(self.panel._checking)
        finally:
            style.configure('TButton', font=old or 'TkDefaultFont')
            self.root.update()


if __name__ == '__main__':
    unittest.main(verbosity=2)
