"""Real owned-window tests of topology filtering and calculation ownership."""
import copy
from pathlib import Path
import sys
import tkinter as tk
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parent))
from engineering_ui import Tooltip
from parameter_ui_check import pending_jobs, pump
from parameter_layout import META, applicable
from power_stage import DEFAULT_PARAMS, TOPOLOGIES


class TopologyContextChecks(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        import main
        cls.main = main
        cls.root = tk.Tk()
        cls.root.attributes('-alpha', 0)
        cls.scheduling = patch.object(main.PowerSupplyAnalyzer, 'schedule_update', return_value=None)
        cls.scheduling.start()
        cls.app = main.PowerSupplyAnalyzer(cls.root)
        cls.config = copy.deepcopy(cls.app._config_dict())
        cls.root.unbind('<Configure>')
        for job in pending_jobs(cls.root):
            cls.root.after_cancel(job)
        cls.root.geometry('1400x880')
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
        self.app._apply_config(copy.deepcopy(self.config))
        self.app._expand_params()
        pump(self.root)

    def tearDown(self):
        pump(self.root)
        self.assertEqual(self.errors, [])

    def topology(self, topo):
        self.app.params['topology'].set(self.main.TOPO_LABEL[topo])
        pump(self.root)

    def shown(self, key):
        return bool(self.app._param_widgets[key][1].grid_info())

    def test_every_topology_hides_inapplicable_scalar_parameters_even_under_search(self):
        for topo in TOPOLOGIES:
            self.topology(topo)
            mode = self.app._presentation_context()[1]
            for key in META:
                if not applicable(key, topo, mode):
                    with self.subTest(topology=topo, field=key):
                        self.assertFalse(self.shown(key))
                        self.app.param_search.set(key)
                        pump(self.root)
                        self.assertFalse(self.shown(key))
                        self.app.param_search.set('')

    def test_only_isolated_topologies_have_a_clamp_page(self):
        original = self.app.nb.tabs()
        for topo in TOPOLOGIES:
            self.topology(topo)
            expected = 'normal' if topo in ('FLYBACK', 'QR-FLYBACK', 'ACF-FORWARD') else 'hidden'
            self.assertEqual(self.app.nb.tab(self.app.tab_rcd, 'state'), expected)
            self.assertEqual(self.app.nb.tabs(), original, 'hidden pages must retain lazy-render indexes')
            title = self.app.nb.tab(self.app.tab_rcd, 'text')
            self.assertIn('有源钳位' if topo == 'ACF-FORWARD' else 'RCD', title)

    def test_switching_away_from_selected_incompatible_page_selects_topology(self):
        self.app.nb.select(self.app.tab_rcd)
        self.topology('BOOST')
        self.assertEqual(self.app.nb.select(), str(self.app.tab_topology))
        self.assertEqual(self.app.nb.tab(self.app.tab_rcd, 'state'), 'hidden')

    def test_psr_page_and_parameters_only_belong_to_fixed_frequency_flyback(self):
        self.app.feedback_mode.set('PSR-MP6005')
        for topo in ('FLYBACK', 'QR-FLYBACK', 'ACF-FORWARD', 'BUCK', 'FLYBACK'):
            self.topology(topo)
            psr = topo == 'FLYBACK'
            self.assertEqual(self.app._psr_active(), psr)
            self.assertEqual(self.app.nb.tab(self.app.tab_comp, 'state'), 'hidden' if psr else 'normal')
            p = self.app.get_params()
            self.assertEqual(p.get('feedback_mode', 'SSR'), 'PSR-MP6005' if psr else 'SSR')
            self.assertEqual(self.app.feedback_mode.get(), 'PSR-MP6005', 'SSR context must not erase the cached choice')

    def test_ignored_incomplete_forward_input_does_not_break_flyback(self):
        self.app._param_display_vars['Lm_forward'].set('-')
        self.app._param_display_vars['Rds_aux'].set('-')
        p = self.app.get_params()
        self.assertEqual(p['Lm_forward'], DEFAULT_PARAMS['Lm_forward'])
        self.assertEqual(p['Rds_aux'], DEFAULT_PARAMS['Rds_aux'])
        self.assertEqual(self.app._param_display_vars['Lm_forward'].get(), '-')
        self.topology('ACF-FORWARD')
        with self.assertRaises((ValueError, tk.TclError)):
            self.app.get_params()
        self.app.set_param('Lm_forward', DEFAULT_PARAMS['Lm_forward'])
        self.app.set_param('Rds_aux', DEFAULT_PARAMS['Rds_aux'])

    def test_ignored_winding_input_does_not_break_nonisolated_context(self):
        self.app._param_display_vars['Ns'].set('-')
        self.topology('BUCK')
        self.assertEqual(self.app.get_params()['Ns'], DEFAULT_PARAMS['Ns'])
        self.topology('FLYBACK')
        with self.assertRaises((ValueError, tk.TclError)):
            self.app.get_params()
        self.app.set_param('Ns', DEFAULT_PARAMS['Ns'])

    def test_folding_and_search_never_exclude_active_invalid_values(self):
        self.app._param_display_vars['Rds_on'].set('-')
        self.app._folded_sections.add(self.app._param_sections['device'])
        self.app.param_search.set('输入电压')
        pump(self.root)
        with self.assertRaises((ValueError, tk.TclError)):
            self.app.get_params()
        self.app.set_param('Rds_on', DEFAULT_PARAMS['Rds_on'])

    def test_rcd_is_configured_once_on_left_and_only_used_by_flyback(self):
        for key, widgets in self.app._rcd_param_widgets.items():
            self.assertIs(widgets[1].master, self.app._param_sections['stage'])
            self.assertTrue(widgets[1].grid_info())
        self.app.rcd_K.set('unfinished')
        self.topology('ACF-FORWARD')
        self.assertEqual(self.app._rcd_parameters()['K'], .95)
        self.assertFalse(any(w[1].grid_info() for w in self.app._rcd_param_widgets.values()))
        self.topology('FLYBACK')
        with self.assertRaises((ValueError, tk.TclError)):
            self.app._rcd_parameters()
        self.app.rcd_K.set(.95)

    def test_qr_frequency_label_is_a_limit_not_an_independent_operating_frequency(self):
        self.topology('QR-FLYBACK')
        self.assertIn('fmax', self.app._param_widgets['f_sw'][0].cget('text'))
        self.topology('FLYBACK')
        self.assertIn('fsw', self.app._param_widgets['f_sw'][0].cget('text'))

    def test_feedback_changes_invalidate_and_request_a_new_calculation(self):
        with patch.object(self.app, 'schedule_update') as schedule:
            self.app.feedback_mode.set('PSR-MP6005')
            schedule.assert_called()

    def test_background_control_loading_cannot_restore_stale_margins(self):
        previous = self.app._control_ready
        self.app._control_ready = True
        self.app._last = dict(p={})
        self.app._snapshot_valid = False
        try:
            with patch.object(self.app, '_update_loop') as update:
                self.app._refresh_loop_margins()
                update.assert_not_called()
        finally:
            self.app._control_ready = previous
            self.app._last = None

    def test_psr_displays_fixed_values_even_when_stored_ssr_draft_is_incomplete(self):
        self.app._param_display_vars['f_sw'].set('-')
        self.app._param_display_vars['A_sense'].set('-')
        self.app.feedback_mode.set('PSR-MP6005')
        pump(self.root)
        self.assertAlmostEqual(float(self.app._param_display_vars['f_sw'].get()) * self.app.units[self.app.params['f_sw_unit'].get()], 250e3)
        self.assertEqual(self.app._param_display_vars['A_sense'].get(), '11')
        self.assertEqual(self.app.get_params()['f_sw'], 250e3)
        self.app.feedback_mode.set('SSR')
        self.app.set_param('f_sw', DEFAULT_PARAMS['f_sw'])
        self.app.set_param('A_sense', DEFAULT_PARAMS['A_sense'])

    def test_saving_ignores_only_inactive_incomplete_compatibility_fields(self):
        self.app._param_display_vars['Lm_forward'].set('-')
        saved = self.app._config_dict()
        self.assertAlmostEqual(saved['Lm_forward']['v'] * self.app.units[saved['Lm_forward']['u']], DEFAULT_PARAMS['Lm_forward'])
        self.assertEqual(self.app._param_display_vars['Lm_forward'].get(), '-')
        self.app._param_display_vars['Rds_on'].set('-')
        with self.assertRaises((ValueError, tk.TclError)):
            self.app._config_dict()
        self.app.set_param('Lm_forward', DEFAULT_PARAMS['Lm_forward'])
        self.app.set_param('Rds_on', DEFAULT_PARAMS['Rds_on'])

    def test_pfm_has_no_pwm_bode_page_and_pwm_restores_it(self):
        self.app.feedback_mode.set('PSR-MP6005')
        self.app._last = dict(p=dict(feedback_mode='PSR-MP6005'), op=dict(regulation_region='PFM-estimate'))
        self.app._snapshot_valid = True
        self.app._sync_topology_pages()
        self.assertEqual(self.app.nb.tab(self.app.tab_loop, 'state'), 'hidden')
        self.app._open_parameter_tab('tab_loop')
        self.assertEqual(self.app.nb.tab(self.app.tab_loop, 'state'), 'hidden', 'sidebar links must not revive an incompatible page')
        self.app._last['op']['regulation_region'] = 'PWM'
        self.app._sync_topology_pages()
        self.assertEqual(self.app.nb.tab(self.app.tab_loop, 'state'), 'normal')
        self.app._snapshot_valid = False
        self.app._last = None


if __name__ == '__main__':
    unittest.main(verbosity=2)
