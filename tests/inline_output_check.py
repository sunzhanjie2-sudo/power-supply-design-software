"""Inline-output SI/configuration regressions; only an owned Tk window."""
import copy
import json
from pathlib import Path
import sys
import tkinter as tk
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import main
from isolated_outputs import RAIL_KEYS
from loss_model import compute_design
from engineering_ui import Tooltip


class InlineTestCase(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.root = tk.Tk()
        cls.root.attributes('-alpha', 0)
        cls.update_patch = patch.object(main.PowerSupplyAnalyzer, 'schedule_update', return_value=None)
        cls.update_patch.start()
        cls.app = main.PowerSupplyAnalyzer(cls.root)
        cls.original_config = copy.deepcopy(cls.app._config_dict())
        cls.root.unbind('<Configure>')
        for job in cls.root.tk.call('after', 'info'):
            cls.root.after_cancel(job)
        cls.root.geometry('1400x880')
        cls.root.update()

    @classmethod
    def tearDownClass(cls):
        cls.app._closing = True
        cls.app._work_cancel.set()
        Tooltip.hide_all(cls.root)
        for job in cls.root.tk.call('after', 'info'):
            cls.root.after_cancel(job)
        cls.root.destroy()
        cls.update_patch.stop()

    def setUp(self):
        self.errors = []
        self.root.report_callback_exception = lambda *exc: self.errors.append(exc)
        self.app._apply_config(copy.deepcopy(self.original_config))
        self.app.advanced_params.set(True)
        self.app._folded_sections.clear()
        self.app.param_search.set('')
        self.app._filter_params()
        self.root.update()

    def tearDown(self):
        Tooltip.hide_all(self.root)
        self.root.update()
        self.assertEqual(self.errors, [], 'An inline output Tk callback failed')

    def load_example(self, name):
        path = Path(__file__).resolve().parents[1] / 'examples' / name
        self.app._apply_config(json.loads(path.read_text(encoding='utf-8')))
        self.app._folded_sections.clear()
        self.app._filter_params()
        self.root.update()

    def outputs(self, count=2):
        self.app.multi_enabled.set(True)
        self.app.output_count.set(str(count))
        self.app._filter_params()
        self.root.update()

    def set_output(self, index, key, value):
        self.app._inline_output_vars[index - 1][key].set(value)

    def shown(self, index, key):
        return bool(self.app._inline_output_widgets[index - 1, key][0].grid_info())


class InlineOutputChecks(InlineTestCase):
    def test_all_rail_fields_exist_for_six_outputs(self):
        for i in range(6):
            self.assertEqual(set(self.app._inline_output_vars[i]), {'name', *RAIL_KEYS})
            for key in ('name',) + RAIL_KEYS:
                if key in ('C_out','Rc','ESL','C_out2','Rc2','ESL2','cout2_enable'):
                    self.assertIn(i,self.app._inline_cap_editors)
                    continue
                self.assertIn((i, key), self.app._inline_output_widgets)

    def test_first_enable_seeds_current_single_output(self):
        self.app.set_param('V_out', 24.)
        self.app.set_param('P_out', 36.)
        self.outputs(1)
        p = self.app.get_params()
        self.assertEqual(p['outputs'][0]['V_out'], 24.)
        self.assertEqual(p['outputs'][0]['P_out'], 36.)

    def test_si_values_are_used_by_actual_design(self):
        self.outputs(2)
        for rail, key, value in ((1,'P_out','30'), (1,'Ns','30'), (2,'Ns','12'), (2,'P_out','10'),
                                 (2,'C_out','220'), (2,'Rc','25'), (2,'Qrr','12'), (2,'d_wire_s','0.3')):
            self.set_output(rail,key,value)
        p = self.app.get_params()
        rail = p['outputs'][1]
        for key, value in (('C_out',220e-6),('Rc',.025),('Qrr',12e-9),('d_wire_s',.0003)):
            self.assertAlmostEqual(rail[key],value)
        result = compute_design(p)
        self.assertEqual(len(result['outputs']), 2)
        self.assertAlmostEqual(result['outputs'][1]['spec']['V_out'], 11.16)
        self.assertAlmostEqual(result['op']['P_out'], 40.)

    def test_visible_invalid_value_blocks_calculation_and_save(self):
        self.outputs(2)
        self.set_output(2, 'Ns', '-')
        for getter in (self.app.get_params, self.app._config_dict):
            with self.assertRaisesRegex(ValueError, 'OUT2'):
                getter()
        self.assertEqual(self.app.output_config, [])

    def test_nonfinite_negative_and_fractional_values_rejected(self):
        self.outputs(1)
        for key, text in (('V_out','nan'),('C_out','-1'),('Ns','2.5'),('n_strand_s','0')):
            previous = self.app._inline_output_vars[0][key].get()
            self.set_output(1, key, text)
            with self.subTest(key=key):
                with self.assertRaises(ValueError): self.app.get_params()
            self.set_output(1, key, previous)

    def test_six_outputs_and_feedback_clamp_preserve_same_design_rail_edits(self):
        self.outputs(6)
        self.set_output(3, 'P_out', '1')
        self.set_output(6, 'P_out', '1')
        self.set_output(6, 'V_out', '5')
        self.app.feedback_output.set(6)
        self.assertEqual(len(self.app.get_params()['outputs']), 6)
        self.app.output_count.set('3')
        self.assertEqual(self.app.feedback_output.get(), 3)
        self.assertEqual(len(self.app.get_params()['outputs']), 3)
        self.app.output_count.set('6')
        p = self.app.get_params()
        # A removed/re-added, non-feedback rail starts with reference turns;
        # its old voltage is no longer an independent target.
        self.assertEqual(p['outputs'][5]['V_out'], p['outputs'][2]['V_out'])

    def test_invalid_output_count_not_silently_clamped(self):
        self.outputs(1)
        for value in ('','-','0','7','2.5','nan'):
            self.app.output_count.set(value)
            with self.subTest(value=value):
                with self.assertRaisesRegex(ValueError,'路数'): self.app.get_params()

    def test_save_load_round_trip_preserves_per_rail_units_and_feedback(self):
        self.outputs(2)
        for key,value in (('V_out',15),('P_out',5),('ripple_target',2),('Ns',9),('name','辅助15V')):
            self.set_output(2,key,value)
        self.app.feedback_output.set(2)
        before = copy.deepcopy(self.app.get_params()['outputs'])
        config = json.loads(json.dumps(self.app._config_dict()))
        self.app._apply_config(config)
        self.assertEqual(self.app.get_params()['outputs'], before)
        self.assertEqual(self.app.feedback_output.get(), 2)
        self.assertEqual(self.app.output_count.get(), '2')

    def test_new_single_output_load_clears_previous_six_rail_cache(self):
        self.outputs(6)
        self.set_output(6,'V_out',99)
        self.set_output(6,'P_out',1)
        self.app.get_params()
        self.app._apply_config(copy.deepcopy(self.original_config))
        self.outputs(6)
        self.assertNotEqual(self.app.get_params()['outputs'][5]['V_out'],99.)
        self.assertEqual(self.app.get_params()['outputs'][5]['P_out'],0.)

    def test_legacy_examples_and_direct_configuration_updates_work(self):
        self.load_example('6_OUTPUT_FLYBACK_SSR.json')
        self.assertEqual(len(self.app.get_params()['outputs']),6)
        self.app.output_config[0]['V_out']=27.
        self.assertEqual(self.app.get_params()['outputs'][0]['V_out'],27.)
        self.assertEqual(float(self.app._inline_output_vars[0]['V_out'].get()),27.)

    def test_forward_choke_survives_fast_topology_change_and_json(self):
        self.outputs(1)
        self.app.params['topology'].set(main.TOPO_LABEL['ACF-FORWARD'])
        self.set_output(1,'L',220)
        self.set_output(1,'core_choice_L','PQ32-25')
        self.app.params['topology'].set(main.TOPO_LABEL['FLYBACK'])
        self.assertFalse(self.shown(1,'L'))
        config=self.app._config_dict()
        self.assertAlmostEqual(config['outputs'][0]['L'],220e-6)
        self.app._apply_config(config)
        self.app.params['topology'].set(main.TOPO_LABEL['ACF-FORWARD'])
        self.assertAlmostEqual(self.app.get_params()['outputs'][0]['L'],220e-6)
        self.assertEqual(self.app.get_params()['outputs'][0]['core_choice_L'],'PQ32-25')

    def test_hidden_choke_and_optional_invalid_values_do_not_block_flyback(self):
        self.outputs(1)
        for key,value in (('L','-'),('cout2_enable',False),('C_out2','-'),('d_out_enable',False),('Vf_dout','-')):
            self.set_output(1,key,value)
        p=self.app.get_params()
        self.assertEqual(p['topology'],'FLYBACK')
        self.assertGreater(p['outputs'][0]['L'],0)
        self.app.params['topology'].set(main.TOPO_LABEL['ACF-FORWARD'])
        with self.assertRaisesRegex(ValueError,'正激输出电感'): self.app.get_params()

    def test_optional_valid_edit_survives_quick_disable_and_save(self):
        self.outputs(1)
        self.set_output(1,'C_out2','470')
        self.set_output(1,'cout2_enable',False)
        config=self.app._config_dict()
        self.assertAlmostEqual(config['outputs'][0]['C_out2'],470e-6)
        self.assertFalse(config['outputs'][0]['cout2_enable'])

    def test_psr_effective_only_fixed_flyback_and_restores_on_return(self):
        self.load_example('MP6005_PSR_FLYBACK.json')
        self.app._inline_psr_vars['psr_Rcomp'].set('18')
        self.assertEqual(self.app.get_params()['psr_Rcomp'],18e3)
        for topology in ('QR-FLYBACK','ACF-FORWARD'):
            self.app.params['topology'].set(main.TOPO_LABEL[topology])
            self.assertEqual(self.app.get_params()['feedback_mode'],'SSR')
            self.assertEqual(self.app.feedback_mode.get(),'PSR-MP6005')
        self.app.params['topology'].set(main.TOPO_LABEL['FLYBACK'])
        self.assertEqual(self.app.get_params()['feedback_mode'],'PSR-MP6005')
        self.assertEqual(self.app.get_params()['psr_Rcomp'],18e3)

    def test_psr_direct_tuning_writeback_updates_inline_form(self):
        self.load_example('MP6005_PSR_FLYBACK.json')
        self.app.psr_config.update(psr_Rcomp=22e3,psr_Ccomp=47e-9)
        p=self.app.get_params()
        self.assertAlmostEqual(p['psr_Rcomp'],22e3)
        self.assertAlmostEqual(p['psr_Ccomp'],47e-9)
        self.assertEqual(float(self.app._inline_psr_vars['psr_Rcomp'].get()),22.)

    def test_psr_auto_tune_writes_back_to_real_inline_inputs(self):
        from mp6005 import compensation_parts
        self.load_example('MP6005_PSR_FLYBACK.json')
        tuned=dict(feasible=True,comp_type='type2',KP=50.,fz1=100.,fp1=10000.)
        expected=compensation_parts(tuned)
        with patch('loss_model.compute_design',return_value={'op':{'f_sw':250e3}}), \
             patch('plants.build_loop_models',return_value=([object()],None)), \
             patch('loop_tuning.kfactor_tune',return_value=tuned):
            self.app._psr_auto_tune(self.app.get_params())
        for key,value in expected.items():
            self.assertAlmostEqual(self.app.get_params()[key],value)

    def test_visible_psr_invalid_blocks_but_hidden_psr_does_not_block_ssr(self):
        self.load_example('MP6005_PSR_FLYBACK.json')
        self.app._inline_psr_vars['psr_Rcomp'].set('-')
        with self.assertRaisesRegex(ValueError,'MP6005'): self.app.get_params()
        self.app.params['topology'].set(main.TOPO_LABEL['QR-FLYBACK'])
        self.assertEqual(self.app.get_params()['feedback_mode'],'SSR')
        self.app.params['topology'].set(main.TOPO_LABEL['FLYBACK'])
        with self.assertRaisesRegex(ValueError,'MP6005'): self.app.get_params()


if __name__=='__main__': unittest.main(verbosity=2)
