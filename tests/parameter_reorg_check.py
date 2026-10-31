"""Owned-window regressions for the eight-group parameter design workflow.

No mouse movements, focus changes, dialogs, or other applications are used.
DoubleVar values and saved configuration prefixes remain backward compatible;
the new StringVar display values and units are a presentation layer only.
"""
import copy
import json
from pathlib import Path
import sys
import tkinter as tk
from tkinter import ttk
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parent))
from engineering_ui import Tooltip
from parameter_ui_check import pending_jobs, pump


SECTIONS = ['spec', 'curves', 'stage', 'device', 'capacitors', 'drive', 'sense', 'mag', 'ctrl']
GATE_REQUIRED = ('Vth', 'Vgp_on', 'Vgp_off', 'Qg_th', 'Qgs', 'Qgd', 'Rg',
                 'Vgs', 'Rg_drive', 'Rs_on', 'Rs_off')
OPTIONALS = {
    'cin2_enable': ('Cin2', 'Rcin2', 'ESLin2'),
    'cout2_enable': ('C_out2', 'Rc2', 'ESL2'),
    'd_in_enable': ('Vf_din',),
    'd_out_enable': ('Vf_dout',),
}


class ParameterReorganisationChecks(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        import main
        cls.main = main
        cls.root = tk.Tk()
        cls.root.attributes('-alpha', 0)
        cls.update_patch = patch.object(main.PowerSupplyAnalyzer, 'schedule_update', return_value=None)
        cls.update_patch.start()
        cls.app = main.PowerSupplyAnalyzer(cls.root)
        cls.initial_folds = set(cls.app._folded_sections)
        cls.original_config = copy.deepcopy(cls.app._config_dict())
        cls.original_params = copy.deepcopy(cls.app.get_params())
        # Cancel computation and resize jobs before making the owned shell visible.
        cls.root.unbind('<Configure>')
        for job in pending_jobs(cls.root):
            cls.root.after_cancel(job)
        cls.root.geometry('1400x880')
        cls.root.update()

    @classmethod
    def tearDownClass(cls):
        cls.app._closing = True
        cls.app._work_cancel.set()
        Tooltip.hide_all(cls.root)
        for job in pending_jobs(cls.root):
            cls.root.after_cancel(job)
        cls.root.destroy()
        cls.update_patch.stop()

    def setUp(self):
        self.errors = []
        self.root.report_callback_exception = lambda *exc: self.errors.append(exc)
        self.app._apply_config(copy.deepcopy(self.original_config))
        self.app.param_search.set('')
        self.app.advanced_params.set(True)
        self.app._folded_sections.clear()
        self.app._filter_params()
        self.app.left_canvas.yview_moveto(0)
        self.root.geometry('1400x880')
        pump(self.root)
        self.assertIsNone(self.app._last, 'This suite must not start a GUI calculation')

    def tearDown(self):
        Tooltip.hide_all(self.root)
        pump(self.root)
        self.assertEqual(self.errors, [], 'A parameter-panel Tk callback failed')

    def mapped(self, key):
        return bool(self.app._param_widgets[key][1].winfo_ismapped())

    def display_number(self, key):
        return float(self.app._param_display_vars[key].get())

    def basic(self):
        self.app.advanced_params.set(False)
        self.app._filter_params()
        pump(self.root)

    def test_sections_with_unified_curve_hub_and_startup_folds(self):
        self.assertEqual(list(self.app._param_sections), SECTIONS)
        self.assertEqual(self.initial_folds, set())
        for key in SECTIONS:
            frame = self.app._param_sections[key]
            self.assertTrue(frame._section_header.winfo_ismapped())
            self.assertIn(key, self.app._param_summary_vars)
            self.assertTrue(self.app._param_summary_vars[key].get().strip())

    def test_complete_units_preserve_legacy_prefixes(self):
        expected = {'L': 'µH', 'Rds_on': 'mΩ', 'Qg_th': 'nC', 'f_sw': 'kHz',
                    'V_in': 'V', 'P_out': 'W', 'eta_guess': '%'}
        for key, display_unit in expected.items():
            with self.subTest(key=key):
                self.assertIn(display_unit, self.app._param_unit_choices(key))
                self.assertEqual(self.app._param_unit_vars[key].get(), display_unit)
        self.assertEqual(self.app.params['L_unit'].get(), 'u')
        self.assertEqual(self.app.params['Qg_th_unit'].get(), 'n')
        self.assertEqual(self.app._config_dict()['L']['u'], 'u')

    def test_each_parameter_has_one_editor_in_its_device_or_design_group(self):
        expected = {'V_in': 'spec', 'ripple_target': 'spec', 'L': 'stage',
                    'N': 'stage', 'Rds_on': 'device', 'Vth': 'device',
                    'Rg': 'device', 'Cin1': 'capacitors', 'C_out': 'capacitors',
                    'Vgs': 'drive', 'Rg_drive': 'drive', 'Rs_on': 'drive',
                    'Rs': 'sense', 'A_sense': 'sense', 'Vm': 'sense',
                    'ma_slope': 'sense', 'Np': 'mag', 'KP': 'ctrl'}
        editors = [widgets[1] for widgets in self.app._param_widgets.values()]
        self.assertEqual(len(editors), len(set(editors)))
        for key, section in expected.items():
            with self.subTest(key=key, group=section):
                editor = self.app._param_widgets[key][1]
                parent = editor.master
                ancestors = []
                while parent is not None:
                    ancestors.append(parent)
                    parent = parent.master
                self.assertIn(self.app._param_sections[section], ancestors)

    def test_percent_display_edit_and_old_config_round_trip(self):
        self.assertAlmostEqual(self.display_number('eta_guess'), 93)
        self.app._param_display_vars['eta_guess'].set('91.5')
        self.app._param_display_vars['ripple_target'].set('2.5')
        pump(self.root)
        self.assertAlmostEqual(self.app.get_param('eta_guess'), .915)
        self.assertAlmostEqual(self.app.get_param('ripple_target'), .025)
        cfg = self.app._config_dict()
        self.assertAlmostEqual(cfg['eta_guess']['v'], .915)
        self.assertEqual(cfg['eta_guess']['u'], '')
        self.app._apply_config(copy.deepcopy(cfg))
        pump(self.root)
        self.assertAlmostEqual(self.display_number('eta_guess'), 91.5)
        self.assertAlmostEqual(self.display_number('ripple_target'), 2.5)
        self.assertAlmostEqual(self.app.get_param('eta_guess'), .915)

    def test_switch_display_unit_does_not_change_physical_value(self):
        for key in ('L', 'Rds_on', 'f_sw', 'C_out', 'MLT'):
            with self.subTest(key=key):
                physical = self.app.get_param(key)
                choices = self.app._param_unit_choices(key)
                current = self.app._param_unit_vars[key].get()
                alternate = next(label for label in choices if label != current)
                self.app._param_unit_vars[key].set(alternate)
                self.app._change_param_unit(key)
                pump(self.root)
                self.assertAlmostEqual(self.app.get_param(key), physical, places=12)
                self.assertEqual(self.app.params[key + '_unit'].get(), choices[alternate])
                self.app._param_unit_vars[key].set(current)
                self.app._change_param_unit(key)
                pump(self.root)
                self.assertAlmostEqual(self.app.get_param(key), physical, places=12)

    def test_auto_switch_round_trip_preserves_manual_values_and_other_inputs(self):
        manual = {'Np': 13., 'Ns': 26., 'd_wire_p': .00045, 'd_wire_s': .0006, 'MLT': .07}
        for key, value in manual.items():
            with self.subTest(key=key):
                self.app.set_param(key, value)
                pump(self.root)
                before = self.app.get_params()
                self.app._param_auto_vars[key].set(True)
                self.app._toggle_param_auto(key)
                pump(self.root)
                self.assertEqual(self.app.get_param(key), 0)
                self.assertTrue(self.app._param_widgets[key][1].instate(['readonly']))
                self.app._param_auto_vars[key].set(False)
                self.app._toggle_param_auto(key)
                pump(self.root)
                self.assertAlmostEqual(self.app.get_param(key), value)
                self.assertFalse(self.app._param_widgets[key][1].instate(['readonly']))
                self.assertEqual(self.app.get_params(), before)

    def test_new_auto_configuration_does_not_reuse_another_design_manual_cache(self):
        self.app.set_param('Np', 37)
        cfg = copy.deepcopy(self.original_config)
        cfg['Np'] = {'v': 0, 'u': ''}
        self.app._apply_config(cfg)
        pump(self.root)
        self.assertTrue(self.app._param_auto_vars['Np'].get())
        self.assertEqual(self.app.get_param('Np'), 0)
        self.app._param_auto_vars['Np'].set(False)
        self.app._toggle_param_auto('Np')
        pump(self.root)
        self.assertEqual(self.app._param_display_vars['Np'].get(), '')
        self.assertFalse(self.app._param_widgets['Np'][1].instate(['readonly']))
        with self.assertRaises((tk.TclError, ValueError)):
            self.app.get_param('Np')

    def test_typing_zero_in_manual_turns_switches_to_auto_without_zero_cache(self):
        self.app.set_param('Np', 13)
        remembered = self.app._param_auto_saved['Np']
        self.assertFalse(self.app._param_auto_vars['Np'].get())
        self.app._param_display_vars['Np'].set('0')
        pump(self.root)
        self.assertEqual(self.app.get_param('Np'), 0)
        self.assertTrue(self.app._param_auto_vars['Np'].get())
        self.assertTrue(self.app._param_widgets['Np'][1].instate(['readonly']))
        self.assertEqual(self.app._param_display_vars['Np'].get(), '自动')
        self.assertEqual(self.app._param_auto_saved['Np'], remembered)
        self.assertNotEqual(self.app._param_auto_saved['Np'][0], 0)
        self.app._param_auto_vars['Np'].set(False)
        self.app._toggle_param_auto('Np')
        pump(self.root)
        self.assertEqual(self.app.get_param('Np'), 13)

    def test_optional_disabled_inputs_hidden_under_advanced_and_search(self):
        for flag, keys in OPTIONALS.items():
            with self.subTest(flag=flag):
                remembered = {k: self.app.get_param(k) for k in keys}
                self.app.params[flag].set(False)
                self.app._filter_params()
                pump(self.root)
                self.assertTrue(all(not self.mapped(k) for k in keys))
                self.app.param_search.set(keys[0])
                pump(self.root)
                self.assertFalse(self.mapped(keys[0]), 'Search must not reactivate a disabled circuit part')
                self.app.param_search.set('')
                self.app.params[flag].set(True)
                self.app._filter_params()
                pump(self.root)
                self.assertTrue(all(self.mapped(k) for k in keys))
                self.assertEqual({k: self.app.get_param(k) for k in keys}, remembered)

    def test_checkbox_callback_immediately_filters_optional_fields(self):
        def children(widget):
            for child in widget.winfo_children():
                yield child
                yield from children(child)
        checkbox = next(w for w in children(self.app._param_sections['capacitors'])
                        if isinstance(w, ttk.Checkbutton) and
                        str(w.cget('variable')) == str(self.app.params['cout2_enable']))
        self.assertTrue(self.app.params['cout2_enable'].get())
        checkbox.invoke()
        pump(self.root)
        self.assertFalse(self.mapped('C_out2'))
        checkbox.invoke()
        pump(self.root)
        self.assertTrue(self.mapped('C_out2'))

    def test_gate_model_inputs_are_visible_in_basic_mode(self):
        self.basic()
        for key in GATE_REQUIRED:
            with self.subTest(key=key):
                if key in ('Vgp_on','Vgp_off','Qgs'):
                    self.assertFalse(self.mapped(key))
                    for case in ('min','max'):
                        for edge in ('on','off'):
                            self.assertTrue(self.app._manual_event_entries[case,edge,'Qgs' if key=='Qgs' else 'Vgp'].winfo_ismapped())
                else:self.assertTrue(self.mapped(key))
        for key in ('rho', 'k_core', 'a_core', 'b_core'):
            with self.subTest(advanced_key=key):
                self.assertTrue(self.mapped(key))

    def test_advanced_checkbox_removed_and_magnetic_coefficients_stay_editable(self):
        def texts(parent):
            result=[]
            for child in parent.winfo_children():
                if isinstance(child,ttk.Checkbutton):result.append(child.cget('text'))
                result.extend(texts(child))
            return result
        self.assertNotIn('显示高级参数',texts(self.root))
        self.basic()  # legacy flag cannot hide parameters anymore
        for key,value in (('k_core',31.2),('a_core',1.4),('b_core',2.3)):
            self.assertTrue(self.mapped(key))
            self.app._param_display_vars[key].set(str(value))
            pump(self.root)
            self.assertAlmostEqual(self.app.get_param(key),value)
        saved=self.app._config_dict()
        self.app._apply_config(saved)
        for key,value in (('k_core',31.2),('a_core',1.4),('b_core',2.3)):
            self.assertAlmostEqual(self.app.get_param(key),value)

    def test_topology_caption_and_inapplicable_inputs(self):
        for topo, word in (('FLYBACK', '励磁'), ('ACF-FORWARD', '输出'), ('BUCK', '功率')):
            with self.subTest(topo=topo):
                self.app.params['topology'].set(self.main.TOPO_LABEL[topo])
                pump(self.root)
                label = self.app._param_widgets['L'][0].cget('text')
                self.assertIn(word, label)
                self.assertEqual(self.mapped('N'), topo != 'BUCK')
                self.assertEqual(self.mapped('Lm_forward'), topo == 'ACF-FORWARD')
                self.assertEqual(self.mapped('C_clamp'), topo == 'ACF-FORWARD')
                self.assertEqual(list(self.app._param_sections), SECTIONS)

    def test_voltage_mode_sense_resistor_stays_visible_for_its_loss(self):
        self.app.params['control_mode'].set(self.main.CTRL_LABEL['Voltage Mode'])
        self.basic()
        self.assertTrue(self.mapped('Rs'))

    def test_psr_effective_sampling_gain_is_readonly_without_overwriting_ssr_input(self):
        self.app.set_param('A_sense', 20)
        self.app.params['controller_type'].set('type3')
        self.app.feedback_mode.set('PSR-MP6005')
        pump(self.root)
        self.assertEqual(self.display_number('A_sense'), 11)
        self.assertTrue(self.app._param_widgets['A_sense'][1].instate(['readonly']))
        self.assertEqual(self.app.get_params()['A_sense'], 11)
        self.assertEqual(self.app.get_params()['controller_type'], 'type2')
        self.assertEqual(self.app.get_param('A_sense'), 20)
        self.app.feedback_mode.set('SSR')
        pump(self.root)
        self.assertEqual(self.display_number('A_sense'), 20)
        self.assertFalse(self.app._param_widgets['A_sense'][1].instate(['readonly']))

    def test_psr_fixed_frequency_mode_and_controller_preserve_legacy_raw_values(self):
        self.app.set_param('f_sw', 100e3)
        self.app.params['control_mode'].set(self.main.CTRL_LABEL['Voltage Mode'])
        self.app.params['controller_type'].set('type3')
        raw = {key: self.app.params[key].get() for key in
               ('f_sw', 'f_sw_unit', 'control_mode', 'controller_type')}
        self.app.feedback_mode.set('PSR-MP6005')
        pump(self.root)
        frequency = self.display_number('f_sw') * self.app.units[self.app.params['f_sw_unit'].get()]
        self.assertEqual(frequency, 250e3)
        self.assertTrue(self.app._param_widgets['f_sw'][1].instate(['readonly']))
        self.assertTrue(self.app._param_widgets['f_sw'][2].instate(['disabled']))
        self.assertTrue(self.app.ctrl_combo.instate(['disabled']))
        self.assertEqual(self.app.ctrl_combo.get(), self.main.CTRL_LABEL['Peak Current Mode'])
        self.assertTrue(self.app._param_controller_combo.instate(['disabled']))
        self.assertIn('type2', self.app._param_controller_combo.get())
        for key in ('KP', 'fz1', 'fz2', 'fp1', 'fp2'):
            with self.subTest(psr_compatibility_key=key):
                self.assertFalse(self.mapped(key))
                self.app.param_search.set(key)
                pump(self.root)
                self.assertFalse(self.mapped(key), 'Search must not expose unused SSR compatibility parameters')
        self.assertEqual({key: self.app.params[key].get() for key in raw}, raw)
        self.app.param_search.set('')
        self.app.feedback_mode.set('SSR')
        pump(self.root)
        self.assertEqual(self.display_number('f_sw'), raw['f_sw'])
        self.assertFalse(self.app._param_widgets['f_sw'][1].instate(['readonly']))
        self.assertTrue(self.app._param_widgets['f_sw'][2].instate(['readonly']))
        self.assertTrue(self.app.ctrl_combo.instate(['readonly']))
        self.assertEqual(self.app.ctrl_combo.get(), raw['control_mode'])
        self.assertTrue(self.app._param_controller_combo.instate(['readonly']))
        self.assertEqual(self.app._param_controller_combo.get(), raw['controller_type'])
        self.assertTrue(all(self.mapped(key) for key in ('KP', 'fz1', 'fz2', 'fp1', 'fp2')))

    def test_multi_output_summary_and_inline_fields_replace_old_scalar_editors(self):
        fixture = Path(__file__).resolve().parents[1] / 'examples' / '6_OUTPUT_FLYBACK_SSR.json'
        cfg = copy.deepcopy(self.original_config)
        cfg.update(json.loads(fixture.read_text(encoding='utf-8')))
        cfg.pop('coupling_config', None)  # New rail count needs its own matrix.
        self.app._apply_config(cfg)
        pump(self.root)
        self.assertEqual(len(self.app.get_params()['outputs']), 6)
        self.assertIn('6', self.app._param_summary_vars['spec'].get())
        for key in ('V_out', 'P_out'):
            self.assertFalse(self.mapped(key))
            entries = [self.app._inline_output_widgets[index, key][1] for index in range(6)]
            self.assertEqual(len(set(entries)), 6)
            self.assertTrue(all(entry.winfo_ismapped() for entry in entries))
            self.assertTrue(all(entry.master is self.app._param_sections['spec'] for entry in entries))

    def test_multi_output_owned_fields_hidden_but_input_and_flyback_primary_editable(self):
        fixture = Path(__file__).resolve().parents[1] / 'examples' / '6_OUTPUT_FLYBACK_SSR.json'
        cfg = copy.deepcopy(self.original_config)
        cfg.update(json.loads(fixture.read_text(encoding='utf-8')))
        cfg.pop('coupling_config', None)
        self.app._apply_config(cfg)
        pump(self.root)
        owned = ('C_out', 'Rc', 'ESL', 'C_out2', 'Rc2', 'ESL2', 'Vf_diode',
                 'Rd_diode', 'Qrr', 'Vf_dout', 'Rd_dout', 'ripple_target',
                 'Ns', 'd_wire_s', 'n_strand_s')
        remembered = {key: self.app.get_param(key) for key in owned}
        for key in owned:
            with self.subTest(output_owned=key):
                self.assertFalse(self.mapped(key))
                self.app.param_search.set(key)
                pump(self.root)
                self.assertFalse(self.mapped(key))
                self.app.param_search.set('')
                pump(self.root)
        for flag in ('cout2_enable', 'd_out_enable'):
            self.assertFalse(self.app._param_switches[flag].winfo_ismapped())
            self.app.param_search.set(flag)
            pump(self.root)
            self.assertFalse(self.app._param_switches[flag].winfo_ismapped())
            self.app.param_search.set('')
            pump(self.root)
        for key in ('V_in_min', 'V_in_max', 'Cin1', 'Rcin1', 'ESLin1', 'Cin2', 'Vf_din',
                    'L', 'N', 'Np', 'd_wire_p', 'n_strand_p'):
            with self.subTest(shared_parameter=key):
                self.assertTrue(self.mapped(key))
                self.assertFalse(self.app._param_widgets[key][1].instate(['readonly']))
        self.assertEqual({key: self.app.get_param(key) for key in owned}, remembered)

    def test_multi_forward_hides_per_output_inductance_and_disables_shared_choke_selector(self):
        fixture = Path(__file__).resolve().parents[1] / 'examples' / '6_OUTPUT_FLYBACK_SSR.json'
        cfg = copy.deepcopy(self.original_config)
        cfg.update(json.loads(fixture.read_text(encoding='utf-8')))
        cfg.pop('coupling_config', None)
        cfg['topology'] = self.main.TOPO_LABEL['ACF-FORWARD']
        self.app._apply_config(cfg)
        pump(self.root)
        remembered = self.app.get_param('L')
        self.assertFalse(self.mapped('L'))
        self.assertTrue(self.app.inductor_core_combo.instate(['disabled']))
        self.app.param_search.set('输出滤波电感')
        pump(self.root)
        self.assertFalse(self.mapped('L'))
        self.app.param_search.set('')
        pump(self.root)
        for key in ('Lm_forward', 'Np', 'N', 'd_wire_p', 'n_strand_p'):
            with self.subTest(shared_primary=key):
                self.assertTrue(self.mapped(key))
                self.assertFalse(self.app._param_widgets[key][1].instate(['readonly']))
        self.assertEqual(self.app.get_param('L'), remembered)

    def test_search_raw_key_reveals_advanced_field_and_restores_folding(self):
        self.basic()
        frame = self.app._param_sections['mag']
        self.app._fold_section(frame)
        pump(self.root)
        self.assertIn(frame, self.app._folded_sections)
        self.app.param_search.set('k_core')
        pump(self.root)
        self.assertTrue(frame.winfo_ismapped())
        self.assertTrue(self.mapped('k_core'))
        self.assertIn(frame, self.app._folded_sections)
        self.app.param_search.set('')
        pump(self.root)
        self.assertFalse(frame.winfo_ismapped())
        self.assertFalse(self.mapped('k_core'))

    def test_section_title_search_selects_the_group(self):
        self.app.param_search.set('栅极驱动')
        pump(self.root)
        frame = self.app._param_sections['drive']
        self.assertTrue(frame.winfo_ismapped())
        for key in ('Vgs', 'Rg_drive', 'Rs_on', 'Rs_off'):
            self.assertTrue(self.mapped(key))
        self.assertFalse(self.mapped('V_in'))

    def test_subgroup_title_search_selects_its_component_without_other_devices(self):
        self.app.param_search.set('Q1')
        pump(self.root)
        self.assertTrue(self.mapped('Rds_on'))
        self.assertTrue(self.mapped('Qgd'))
        self.assertFalse(self.mapped('Vf_diode'))
        self.assertFalse(self.mapped('V_in'))

    def test_incomplete_edit_is_not_replaced_with_a_hidden_previous_number(self):
        try:
            self.app._param_display_vars['Rds_on'].set('-')
            self.app._filter_params()
            pump(self.root)
            self.assertEqual(self.app._param_display_vars['Rds_on'].get(), '-')
            with self.assertRaises((tk.TclError, ValueError)):
                self.app.get_param('Rds_on')
            self.assertIn('待填写', self.app._param_summary_vars['device'].get())
        finally:
            self.app.set_param('Rds_on', self.original_params['Rds_on'])

    def test_loading_valid_configuration_replaces_incomplete_entry(self):
        try:
            self.app._param_display_vars['Rds_on'].set('-')
            self.app._apply_config(copy.deepcopy(self.original_config))
            pump(self.root)
            self.assertAlmostEqual(self.app.get_param('Rds_on'), self.original_params['Rds_on'])
        finally:
            self.app.set_param('Rds_on', self.original_params['Rds_on'])

    def test_invalid_output_configuration_does_not_suspend_later_updates(self):
        before = self.app.get_params()
        invalid = {'topology': 'FLYBACK', 'outputs': [{'V_out': 30, 'P_out': -1}]}
        with self.assertRaises(ValueError):
            self.app._apply_config(invalid)
        self.assertFalse(self.app._building)
        self.assertEqual(self.app.get_params(), before)

    def test_topology_switch_with_incomplete_input_still_refreshes_labels(self):
        for key, topology, caption in (('Rds_on', 'ACF-FORWARD', '输出'),
                                       ('f_sw', 'BUCK', '功率')):
            with self.subTest(incomplete_key=key):
                try:
                    self.app._param_display_vars[key].set('-')
                    self.app.params['topology'].set(self.main.TOPO_LABEL[topology])
                    pump(self.root)
                    self.assertIn(caption, self.app._param_widgets['L'][0].cget('text'))
                    self.assertEqual(self.errors, [])
                    self.assertEqual(self.app._param_display_vars[key].get(), '-')
                finally:
                    self.app.set_param(key, self.original_params[key])

    def test_parameter_editors_fit_small_and_normal_windows(self):
        for width, height in ((1400, 880), (1000, 700)):
            with self.subTest(size=(width, height)):
                self.root.geometry(f'{width}x{height}')
                self.app._filter_params()
                pump(self.root)
                left = self.app.left_canvas.winfo_rootx()
                right = left + self.app.left_canvas.winfo_width()
                for key, widgets in self.app._param_widgets.items():
                    for widget in widgets[1:]:
                        if not widget.winfo_ismapped():
                            continue
                        self.assertGreaterEqual(widget.winfo_rootx(), left - 2, key)
                        self.assertLessEqual(widget.winfo_rootx() + widget.winfo_width(), right + 2, key)

    def test_thermal_and_clamp_inputs_follow_topology_and_save(self):
        a=self.app
        self.assertFalse(a._scalar_parameter_active('h_conv'))
        self.assertFalse(a._scalar_parameter_active('ring_margin'))
        self.assertTrue(a._scalar_parameter_active('Rth_transformer'))
        a.params['Rth_transformer'].set(27.)
        saved=a._config_dict()
        self.assertEqual(saved['Rth_transformer']['v'],27.)
        a._apply_config(saved)
        self.assertEqual(a.get_params()['Rth_transformer'],27.)
        a.params['topology'].set('BUCK')
        a._parameter_context_changed()
        self.assertFalse(a._scalar_parameter_active('Rth_transformer'))
        self.assertTrue(a._scalar_parameter_active('h_conv'))
        self.assertTrue(a._scalar_parameter_active('ring_margin'))

    def test_layout_operations_do_not_change_default_design(self):
        from loss_model import compute_design
        before = self.app.get_params()
        self.assertEqual(before['topology'], 'FLYBACK')
        self.assertEqual(before['P_out'], 40)
        self.assertAlmostEqual(before['eta_guess'], .93)
        result_before = compute_design(copy.deepcopy(before))
        self.app.advanced_params.set(False)
        self.app._filter_params()
        for frame in self.app._param_sections.values():
            self.app._fold_section(frame)
        self.app.param_search.set('Qgd')
        pump(self.root)
        self.app.param_search.set('')
        self.app._folded_sections.clear()
        self.app._filter_params()
        pump(self.root)
        after = self.app.get_params()
        self.assertEqual(after, before)
        result_after = compute_design(copy.deepcopy(after))
        for key in ('eta', 'P_total', 'P_semi', 'P_mag', 'P_sense', 'P_cap', 'P_cap_in'):
            self.assertEqual(result_after[key], result_before[key], key)
        for key in ('D', 'dI_L', 'I_sw_rms', 'V_sw_max'):
            self.assertEqual(result_after['op'][key], result_before['op'][key], key)


if __name__ == '__main__':
    unittest.main(verbosity=2)
