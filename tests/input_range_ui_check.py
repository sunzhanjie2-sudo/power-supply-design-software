"""Owned transparent Tk windows: selected voltage, hardware and export jobs."""
import copy
from pathlib import Path
import sys
import time
import tkinter as tk
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import main
from config_io import read_default_config
from engineering_ui import Tooltip


class InputRangeUIChecks(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.root = tk.Tk(); cls.root.attributes('-alpha', 0)
        cls.real_schedule = main.PowerSupplyAnalyzer.schedule_update
        cls.schedule_patch = patch.object(main.PowerSupplyAnalyzer, 'schedule_update', return_value=None)
        cls.schedule_patch.start()
        cls.app = main.PowerSupplyAnalyzer(cls.root)
        cls.root.unbind('<Configure>')
        for job in cls.root.tk.splitlist(cls.root.tk.call('after', 'info')):
            cls.root.after_cancel(job)
        cls.root.geometry('1400x900'); cls.root.update()

    @classmethod
    def tearDownClass(cls):
        cls.app._closing = True; cls.app._calculation_worker.close()
        Tooltip.hide_all(cls.root)
        for job in cls.root.tk.splitlist(cls.root.tk.call('after', 'info')):
            cls.root.after_cancel(job)
        cls.root.destroy(); cls.schedule_patch.stop()

    def setUp(self):
        self.errors = []
        self.root.report_callback_exception = lambda *exc: self.errors.append(exc)
        self.app.nb.select(self.app.tab_topology)
        self.app._apply_config(copy.deepcopy(read_default_config()))
        self.app.set_param('V_in_min', 24)
        self.app.set_param('V_in_max', 40)
        self.app.params['input_voltage_case'].set('min')
        self.app._folded_sections.discard(self.app._param_sections['spec'])
        self.app._filter_params()

    def tearDown(self):
        self.root.update()
        self.assertEqual(self.errors, [])

    def wait_design(self):
        deadline = time.monotonic()+20
        while not self.app._snapshot_valid:
            self.root.update()
            self.assertLess(time.monotonic(), deadline, self.app.status_var.get())
            time.sleep(.005)
        self.root.update()

    def test_only_range_editors_and_clear_current_case(self):
        self.root.update()
        self.assertFalse(self.app._param_widgets['V_in'][1].winfo_ismapped())
        for key in ('V_in_min', 'V_in_max'):
            self.assertTrue(self.app._param_widgets[key][1].winfo_ismapped())
        self.assertEqual(self.app.get_param('V_in'), 24)
        self.app.params['input_voltage_case'].set('max')
        self.assertEqual(self.app.get_param('V_in'), 40)
        self.assertIn('Vin max = 40V', self.app.input_case_note.get())
        self.assertIn('待计算', self.app.input_case_note.get())

    def test_legacy_configuration_migrates_without_invented_range(self):
        self.app._apply_config({'V_in': {'v': 25000, 'u': 'm'}})
        p = self.app.get_params()
        self.assertEqual((p['V_in_min'], p['V_in_max'], p['V_in']), (25,25,25))
        saved = self.app._config_dict()
        self.assertEqual(saved['V_in'], {'v':25, 'u':''})
        self.app.set_param('V_in', 32)
        self.assertEqual((self.app.get_param('V_in_min'), self.app.get_param('V_in_max')), (32,32))

    def test_new_range_roundtrip_ignores_conflicting_legacy_scalar(self):
        cfg = self.app._config_dict()
        cfg['input_voltage_case'] = {'v': 'max', 'u': ''}
        cfg['V_in'] = {'v': 999, 'u':''}
        self.app._apply_config(cfg)
        p = self.app.get_params()
        self.assertEqual((p['V_in_min'],p['V_in_max'],p['V_in']), (24,40,40))
        self.assertEqual(self.app._config_dict()['V_in']['v'], 40)

    def test_async_switch_uses_same_hardware_and_invalidates_all_tabs(self):
        self.app.request_update(); self.wait_design()
        low = self.app._last
        self.assertEqual(low['op']['V_in'], 24)
        self.app._rendered_tabs.update(range(10))
        self.app.params['input_voltage_case'].set('max')
        type(self).real_schedule(self.app)
        self.assertFalse(self.app._snapshot_valid)
        self.assertIn('待计算', self.app.input_case_note.get())
        self.app.request_update(); self.wait_design()
        high = self.app._last
        self.assertEqual(high['op']['V_in'], 40)
        self.assertIn('Vin max = 40V', self.app.input_case_note.get())
        self.assertIn('当前', self.app.input_case_note.get())
        for key in ('Np','Ns','d_wire_p','d_wire_s','n_strand_p','n_strand_s','core_choice'):
            self.assertEqual(low['calculation_params'][key], high['calculation_params'][key], key)
        self.assertNotEqual(low['op']['D'], high['op']['D'])
        self.assertEqual(self.app._rendered_tabs, {0})

    def test_invalid_range_clears_valid_snapshot(self):
        self.assertTrue(self.app.update_all())
        self.app.set_param('V_in_min', 41)
        self.assertFalse(self.app.request_update())
        self.assertFalse(self.app._snapshot_valid)
        self.assertIn('V_in_min', self.app.status_var.get())

    def test_background_export_prepares_both_cases_without_retuning(self):
        self.assertTrue(self.app.update_all())
        before = {key:self.app.get_param(key) for key in ('KP','fz1','fz2','fp1','fp2')}
        with patch.object(self.app, 'export_report') as export:
            self.app._export_report_ui()
            deadline = time.monotonic()+30
            while not export.called:
                self.root.update()
                self.assertLess(time.monotonic(),deadline,self.app.status_var.get())
                time.sleep(.005)
        bundle = export.call_args.kwargs['range_result']
        self.assertEqual([c['voltage'] for c in bundle['cases']], [24,40])
        self.assertTrue(all(c['result'] and c['efficiency_curve'] for c in bundle['cases']))
        self.assertEqual(before, {key:self.app.get_param(key) for key in before})


if __name__ == '__main__':
    unittest.main(verbosity=2)
