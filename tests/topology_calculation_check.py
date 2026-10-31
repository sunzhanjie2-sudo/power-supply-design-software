"""Exercise real GUI calculation/config/export routing for every topology.

Only a transparent Tk window created by this test is used. Word generation is
mocked at its export boundary: the exact current snapshot is inspected without
creating a document or interacting with any user application.
"""
import copy
import json
import math
from pathlib import Path
import sys
import tkinter as tk
import unittest
from unittest.mock import patch

import numpy as np

PROJECT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from config_io import decode_config
from engineering_ui import Tooltip
from parameter_ui_check import pending_jobs, pump
from power_stage import DEFAULT_PARAMS, TOPOLOGIES


def example(filename):
    return decode_config(json.loads((PROJECT / 'examples' / filename).read_text(encoding='utf-8')))


def valid_spec(topology):
    p = copy.deepcopy(DEFAULT_PARAMS)
    p.update(topology=topology, feedback_mode='SSR', feedback_output=1, outputs=[],
             core_choice='auto', core_shape='auto', core_choice_L='auto',
             target_eta=.92, fc_target=3000., pm_target=60.)
    if topology == 'BUCK':
        p.update(example('spec_buck.json'))
    elif topology == 'BOOST':
        p.update(V_in=12., V_out=30., P_out=40., L=100e-6, f_sw=100e3)
    elif topology == 'BUCK-BOOST':
        p.update(V_in=12., V_out=24., P_out=40., L=100e-6, f_sw=100e3)
    elif topology == 'ACF-FORWARD':
        p.update(example('40W_ACF_FORWARD.json'))
    elif topology == 'QR-FLYBACK':
        p.update(topology=topology, Np=50, Ns=0, core_choice='PQ32-25')
    return p


def multiple_spec(topology='FLYBACK', psr=False):
    p = valid_spec(topology)
    p.update(example('6_OUTPUT_FLYBACK_SSR.json'))
    p.update(topology=topology, outputs=p['outputs'][:2])
    if topology == 'ACF-FORWARD':
        p.update(N=.5, L=68e-6, Lm_forward=220e-6, C_clamp=47e-9)
        p['outputs'][0]['L'] = 1e-3
        p['outputs'][1]['L'] = 2e-3
    if psr:
        p.update(feedback_mode='PSR-MP6005', Vgs=8.5, Rs=.015)
    return p


class TopologyCalculationChecks(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        import main
        cls.main = main
        cls.root = tk.Tk()
        cls.root.attributes('-alpha', 0)
        # Calculations are invoked explicitly; no queued test action can race
        # the next fixture, and no background control import is started.
        cls.scheduling = patch.object(main.PowerSupplyAnalyzer, 'schedule_update', return_value=None)
        cls.scheduling.start()
        cls.app = main.PowerSupplyAnalyzer(cls.root)
        cls.root.unbind('<Configure>')
        for job in pending_jobs(cls.root):
            cls.root.after_cancel(job)
        cls.root.geometry('1400x880')
        cls.app._control_ready = False
        pump(cls.root)

    @classmethod
    def tearDownClass(cls):
        cls.app._closing = True
        cls.app._work_cancel.set()
        Tooltip.hide_all(cls.root)
        for job in pending_jobs(cls.root):
            cls.root.after_cancel(job)
        cls.root.destroy()
        cls.scheduling.stop()

    def setUp(self):
        self.errors = []
        self.root.report_callback_exception = lambda *exc: self.errors.append(exc)
        self.app._last = None
        self.app._snapshot_valid = False
        self.app._control_ready = False
        self.app.nb.select(self.app.tab_topology)

    def tearDown(self):
        pump(self.root)
        self.assertEqual(self.errors, [], 'A test-owned Tk callback failed')

    def load_and_compute(self, p):
        self.app._apply_config(copy.deepcopy(p))
        self.app.get_params()
        self.assertTrue(self.app.update_all(), self.app.status_var.get())
        self.assertTrue(self.app._snapshot_valid)
        self.assertTrue(math.isfinite(self.app._last['res']['eta']))
        return self.app._last

    def assert_same_result(self, expected, actual):
        self.assertEqual(actual['p']['topology'], expected['p']['topology'])
        self.assertEqual(actual['p'].get('feedback_mode', 'SSR'), expected['p'].get('feedback_mode', 'SSR'))
        self.assertEqual(actual['p'].get('feedback_output', 1), expected['p'].get('feedback_output', 1))
        for key in ('D', 'f_sw', 'P_out', 'P_in_est', 'I_sw_pk', 'I_sw_rms', 'V_sw_max', 'I_out'):
            np.testing.assert_allclose(actual['op'][key], expected['op'][key], rtol=1e-10, atol=1e-12, err_msg=key)
        for key in ('P_total', 'P_semi', 'P_mag', 'P_cap', 'eta'):
            np.testing.assert_allclose(actual['res'][key], expected['res'][key], rtol=1e-10, atol=1e-12, err_msg=key)
        np.testing.assert_allclose(actual['wf']['i_sw'], expected['wf']['i_sw'], rtol=1e-10, atol=1e-12)

    def test_all_six_topologies_calculate_save_and_reload_consistently(self):
        for topology in TOPOLOGIES:
            with self.subTest(topology=topology):
                first = self.load_and_compute(valid_spec(topology))
                encoded = json.loads(json.dumps(self.app._config_dict(), ensure_ascii=False, allow_nan=False))
                # Switch to a different topology before loading, not merely
                # reapplying a configuration over an identical context.
                self.load_and_compute(valid_spec('BOOST' if topology != 'BOOST' else 'BUCK'))
                second = self.load_and_compute(encoded)
                self.assert_same_result(first, second)

    def test_two_outputs_calculate_and_roundtrip_in_all_isolated_topologies(self):
        for topology in ('FLYBACK', 'QR-FLYBACK', 'ACF-FORWARD'):
            with self.subTest(topology=topology):
                first = self.load_and_compute(multiple_spec(topology))
                self.assertEqual(len(first['p']['outputs']), 2)
                self.assertEqual(len(first['res']['outputs']), 2)
                self.assertEqual(len(first['res']['mag']['transformer']['windings']), 2)
                self.assertAlmostEqual(first['op']['P_out'], 28.)
                self.app.feedback_output.set(2)
                self.assertTrue(self.app.update_all(), self.app.status_var.get())
                second = self.app._last
                self.assertAlmostEqual(second['op']['V_out'], 12.)
                self.assertAlmostEqual(second['op']['P_out'], 28.)
                saved = self.app._config_dict()
                reloaded = self.load_and_compute(saved)
                self.assert_same_result(second, reloaded)

    def test_flyback_hidden_chokes_do_not_change_shared_lm(self):
        for topology in ('FLYBACK', 'QR-FLYBACK'):
            with self.subTest(topology=topology):
                expected = self.load_and_compute(multiple_spec(topology))
                for index, text in enumerate(('0', '-1')):
                    self.app._inline_output_vars[index]['L'].set(text)
                    self.app._inline_output_vars[index]['core_choice_L'].set('unused legacy choke')
                effective = self.app.get_params()
                self.assertTrue(self.app.update_all(), self.app.status_var.get())
                actual = self.app._last
                self.assertAlmostEqual(actual['op']['L'], effective['L'])
                self.assertAlmostEqual(actual['op']['aggregate_params']['L'], effective['L'])
                self.assertTrue(all(branch['L'] == effective['L'] for branch in actual['op']['output_ops']))
                self.assertIsNone(actual['res']['mag']['inductor'])
                self.assert_same_result(expected, actual)

    def test_forward_chokes_are_independent_and_shared_single_value_is_inactive(self):
        first = self.load_and_compute(multiple_spec('ACF-FORWARD'))
        self.app._param_display_vars['L'].set('-')
        effective = self.app.get_params()
        self.assertEqual([rail['L'] for rail in effective['outputs']], [1e-3, 2e-3])
        self.assertTrue(self.app.update_all(), self.app.status_var.get())
        actual = self.app._last
        self.assertEqual([branch['L'] for branch in actual['op']['output_ops']], [1e-3, 2e-3])
        self.assertEqual(len(actual['res']['mag']['inductors']), 2)
        self.assert_same_result(first, actual)

    def test_nonisolated_save_does_not_leak_cached_multioutput_or_psr(self):
        for topology in ('BUCK', 'BOOST', 'BUCK-BOOST'):
            with self.subTest(topology=topology):
                self.load_and_compute(multiple_spec(psr=True))
                self.app.params['topology'].set(self.main.TOPO_LABEL[topology])
                vin, vo = ((48., 12.) if topology == 'BUCK' else (12., 30.))
                self.app.set_param('V_in', vin)
                self.app.set_param('V_out', vo)
                self.app.set_param('P_out', 40.)
                self.app.set_param('L', 100e-6)
                self.assertTrue(self.app.multi_enabled.get(), 'The session should retain its isolated editor cache')
                self.assertEqual(self.app.feedback_mode.get(), 'PSR-MP6005')
                self.assertTrue(self.app.update_all(), self.app.status_var.get())
                first = self.app._last
                saved = self.app._config_dict()
                self.assertEqual(saved['outputs'], [])
                self.assertEqual(saved['feedback_mode'], 'SSR')
                self.assertEqual(saved['feedback_output'], 1)
                reloaded = self.load_and_compute(saved)
                self.assert_same_result(first, reloaded)
                self.assertFalse(self.app.multi_enabled.get())

    def test_word_export_receives_current_calculated_multirail_snapshot(self):
        self.load_and_compute(multiple_spec())
        self.app._inline_output_vars[1]['P_out'].set('9')
        self.app.feedback_output.set(2)
        path = str(PROJECT / '_test_not_written_topology_snapshot.docx')
        with patch('main.filedialog.asksaveasfilename', return_value=path), \
                patch('main.messagebox.showinfo'), patch('main.messagebox.showerror') as error, \
                patch('input_range_report.export_input_range_docx', return_value={
                    'figure_count':0, 'check_count':0, 'successful_cases':2,
                    'failed_cases':[], 'incomplete':False}) as export:
            self.app.export_report()
        error.assert_not_called()
        export.assert_called_once()
        exported_path, bundle = export.call_args.args
        self.assertEqual(exported_path, path)
        # Reports have used two named endpoints since the input-range feature.
        # Check that current edits reach both; there is no scalar-only export.
        self.assertEqual([case['id'] for case in bundle['cases']], ['Vinmin', 'Vinmax'])
        self.assertTrue(bundle['fixed_hardware'])
        for case in bundle['cases']:
            p, res = case['p'], case['result']
            self.assertEqual(p['feedback_output'], 2)
            self.assertAlmostEqual(p['outputs'][1]['P_out'], 9.)
            self.assertAlmostEqual(res['op']['P_out'], 29.)
            self.assertAlmostEqual(res['op']['V_out'], 12.)
            np.testing.assert_allclose(res['wf']['i_sw'], self.app._last['wf']['i_sw'])
        self.assertFalse(Path(path).exists(), 'The Word writer must remain mocked')


if __name__ == '__main__':
    unittest.main(verbosity=2)
