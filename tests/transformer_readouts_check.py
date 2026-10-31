"""Owned-window regressions for turns-derived rails and electrical readouts."""
import copy
from pathlib import Path
import sys
import tkinter as tk
from tkinter import ttk
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parent))
from inline_output_check import InlineTestCase
from loss_model import compute_design


class TransformerReadoutChecks(InlineTestCase):
    def two_outputs(self):
        self.outputs(2)
        self.set_output(1, 'Ns', 12)
        self.set_output(1, 'P_out', 30)
        self.set_output(2, 'Ns', 6)
        self.set_output(2, 'P_out', 10)
        return self.app.get_params()

    def test_only_selected_feedback_voltage_is_editable(self):
        self.outputs(6)
        for selected in (1, 4, 6, 2):
            self.app.feedback_output.set(selected)
            self.root.update()
            for index in range(6):
                state = str(self.app._inline_output_widgets[index, 'V_out'][1].cget('state'))
                self.assertEqual(state, 'normal' if index + 1 == selected else 'readonly')

    def test_unregulated_voltage_is_derived_and_invalid_old_text_is_ignored(self):
        self.two_outputs()
        self.set_output(2, 'V_out', '-')
        p = self.app.get_params()
        self.assertEqual(p['outputs'][1]['V_out'], 15.)
        self.assertEqual(self.app._inline_output_vars[1]['V_out'].get(), '15')
        self.set_output(2, 'Ns', 9)
        self.assertEqual(self.app.get_params()['outputs'][1]['V_out'], 22.5)

    def test_feedback_target_change_updates_all_derived_voltages(self):
        self.two_outputs()
        self.set_output(1, 'V_out', 24)
        self.assertEqual(self.app.get_params()['outputs'][1]['V_out'], 12.)
        self.app.feedback_output.set(2)
        self.set_output(2, 'V_out', 18)
        self.assertEqual(self.app.get_params()['outputs'][0]['V_out'], 36.)

    def test_quick_target_edit_then_feedback_switch_uses_fresh_ratio_voltage(self):
        self.two_outputs()
        with patch('loss_model.compute_design', side_effect=AssertionError('preview must not solve')):
            self.set_output(1, 'V_out', 24)
            self.assertEqual(self.app._inline_output_vars[1]['V_out'].get(), '12')
            self.app.feedback_output.set(2)
            self.assertEqual(self.app._inline_output_vars[1]['V_out'].get(), '12')
        p = self.app.get_params()
        self.assertEqual([row['V_out'] for row in p['outputs']], [24., 12.])

    def test_quick_turn_edit_then_feedback_switch_keeps_new_turns_voltage(self):
        self.two_outputs()
        self.set_output(2, 'Ns', 9)
        self.assertEqual(self.app._inline_output_vars[1]['V_out'].get(), '22.5')
        self.app.feedback_output.set(2)
        self.assertEqual([row['V_out'] for row in self.app.get_params()['outputs']], [30., 22.5])

    def test_preview_preserves_incomplete_and_automatic_turns(self):
        self.two_outputs()
        self.set_output(2, 'Ns', '-')
        self.set_output(1, 'V_out', '24.')
        self.assertEqual(self.app._inline_output_vars[0]['V_out'].get(), '24.')
        self.assertEqual(self.app._inline_output_vars[1]['Ns'].get(), '-')
        with self.assertRaises(ValueError):
            self.app.get_params()
        self.set_output(2, 'Ns', '0')
        self.set_output(1, 'V_out', '-')
        self.assertEqual(self.app._inline_output_vars[1]['Ns'].get(), '0')
        self.assertEqual(self.app._inline_output_vars[0]['V_out'].get(), '-')

    def test_incomplete_feedback_voltage_still_blocks_get_and_save(self):
        self.two_outputs()
        self.set_output(1, 'V_out', '-')
        for getter in (self.app.get_params, self.app._config_dict):
            with self.assertRaises(ValueError):
                getter()

    def test_new_rail_turns_follow_current_feedback_not_startup_hidden_voltage(self):
        self.outputs(1)
        self.set_output(1, 'Ns', 24)
        self.app.output_count.set('3')
        self.assertEqual(self.app._inline_output_vars[1]['Ns'].get(), '24')
        self.assertEqual(self.app._inline_output_vars[2]['Ns'].get(), '24')
        self.set_output(2, 'V_out', '999')
        self.assertEqual(self.app.get_params()['outputs'][1]['V_out'], 30.)

    def test_density_labels_exist_next_to_all_wire_and_parallel_inputs(self):
        for key in ('d_wire_p', 'n_strand_p', 'd_wire_s', 'n_strand_s'):
            parent = self.app._param_widgets[key][1].master
            row = self.app._param_widgets[key][1].grid_info()['row']
            side = next(w for w in self.app._param_widgets[key]
                        if isinstance(w, ttk.Frame))
            self.assertIs(side.master, parent)
            self.assertEqual(side.grid_info()['row'], row)
        self.outputs(6)
        for index in range(6):
            for key in ('d_wire_s', 'n_strand_s'):
                widgets = self.app._inline_output_widgets[index, key]
                self.assertEqual(widgets[-1].grid_info()['column'], 3)
                self.assertEqual(widgets[-1].cget('textvariable'),
                                 str(self.app._transformer_density_vars[f'OUT{index + 1}']))

    def test_geometry_dcr_is_label_not_an_editable_entry(self):
        self.outputs(6)
        for index in range(7):
            widgets = self.app._coupling_widgets['dcr', index]
            self.assertIsInstance(widgets[1], ttk.Label)
            self.assertFalse(isinstance(widgets[1], ttk.Entry))
        # Simulating an old editable draft must not affect the model or throw.
        for variable in self.app._coupling_dcr_vars.values():
            variable.set('not an input')
        self.app.get_params()

    def test_actual_rms_density_and_dcr_readouts_use_result_without_trace_updates(self):
        p = self.two_outputs()
        result = compute_design(p)
        before = copy.deepcopy(self.app.output_config)
        with patch.object(self.app, 'schedule_update') as update:
            self.app._update_transformer_electrical_readouts(p, result)
            update.assert_not_called()
        transformer = result['mag']['transformer']
        self.assertEqual(self.app._transformer_density_vars['P'].get(),
                         f"J {transformer['J_actual_p'] / 1e6:.3g} A/mm²")
        self.assertEqual(self.app._transformer_dcr_vars['P'].get(),
                         f"{transformer['R_dc_p'] * 1e3:.4g}")
        for winding in transformer['windings']:
            name = f"OUT{winding['id']}"
            self.assertEqual(self.app._transformer_density_vars[name].get(),
                             f"J {winding['J_actual'] / 1e6:.3g} A/mm²")
            self.assertEqual(self.app._transformer_dcr_vars[name].get(),
                             f"{winding['R_dc'] * 1e3:.4g}")
        self.assertEqual(self.app.output_config, before)

    def test_single_secondary_uses_same_readout_and_stale_mark_is_explicit(self):
        p = self.app.get_params()
        result = compute_design(p)
        self.app._update_transformer_electrical_readouts(p, result)
        self.assertIn('A/mm²', self.app._transformer_density_vars['OUT1'].get())
        self.app._mark_transformer_readouts_stale()
        self.assertEqual(self.app._transformer_density_vars['OUT1'].get(), 'J 待更新')
        self.assertEqual(self.app._transformer_dcr_vars['OUT1'].get(), '待更新')

    def test_populated_density_readouts_fit_parameter_sidebar(self):
        for multiple in (False, True):
            p = self.two_outputs() if multiple else self.app.get_params()
            self.app._update_transformer_electrical_readouts(p, compute_design(p))
            for width, height in ((1400, 880), (1000, 700)):
                self.root.geometry(f'{width}x{height}')
                self.app._filter_params()
                self.root.update()
                edge = self.app.left_canvas.winfo_rootx() + self.app.left_canvas.winfo_width()
                lists = (list(self.app._param_widgets.values()) +
                         list(self.app._inline_output_widgets.values()))
                for widgets in lists:
                    for widget in widgets:
                        if widget.winfo_ismapped():
                            self.assertLessEqual(widget.winfo_rootx() + widget.winfo_width(), edge + 2)

    def test_search_and_topology_do_not_expose_other_winding_readouts(self):
        self.outputs(2)
        self.app.param_search.set('DCR')
        self.app._filter_params()
        self.assertTrue(self.app._coupling_widgets['dcr', 0][0].grid_info())
        self.assertTrue(self.app._coupling_widgets['dcr', 2][0].grid_info())
        self.assertFalse(self.app._coupling_widgets['dcr', 3][0].grid_info())
        # Use the application mapping, rather than depending on translated labels.
        import main
        self.app.params['topology'].set(main.TOPO_LABEL['BUCK'])
        self.app._filter_params()
        self.assertFalse(any(self.app._coupling_widgets['dcr', i][0].grid_info()
                             for i in range(7)))


if __name__ == '__main__':
    unittest.main(verbosity=2)
