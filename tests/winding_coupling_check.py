"""Physical matrix and owned-window left-panel configuration regressions."""
import copy
import json
from pathlib import Path
import sys
import tkinter as tk
import unittest
from unittest.mock import patch

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from power_stage import DEFAULT_PARAMS
from winding_coupling import default_coupling_config, resolve_winding_model


class MatrixChecks(unittest.TestCase):
    def parameters(self, outputs=1):
        p = copy.deepcopy(DEFAULT_PARAMS)
        p.update(topology='FLYBACK',Np=10,Ns=20,N=.5)
        p['outputs'] = [dict(V_out=30 / (i + 1), P_out=30 / (i + 1), Ns=20 // (i + 1))
                        for i in range(outputs)] if outputs > 1 else []
        p['coupling_config'] = default_coupling_config(outputs)
        return p

    def test_two_winding_short_circuit_leakage_is_one_minus_k_squared(self):
        p = self.parameters()
        model = resolve_winding_model(p)
        self.assertAlmostEqual(model['L_leak'],p['L'] * (1 - .995 ** 2))
        self.assertEqual(model['ratio_sources'], ['primary','actual-turns'])
        np.testing.assert_allclose(np.diag(model['L']), [p['L'],p['L'] * 4])

    def test_full_matrix_uses_all_pairwise_couplings(self):
        p = self.parameters(3)
        p['coupling_config']['k'][1][3] = p['coupling_config']['k'][3][1] = .993
        model = resolve_winding_model(p)
        self.assertEqual(model['L'].shape,(4,4))
        self.assertEqual(model['K'][1,3],.993)
        np.testing.assert_allclose(model['L'],model['L'].T)
        self.assertGreater(model['L_leak'],0)

    def test_impossible_matrix_rejected_even_when_every_k_in_range(self):
        p = self.parameters(2)
        p['coupling_config']['k'] = [[1,.999,.999],[.999,1,.1],[.999,.1,1]]
        with self.assertRaisesRegex(ValueError,'半正定'): resolve_winding_model(p)

    def test_ideal_limit_not_silently_regularized(self):
        p = self.parameters(3)
        p['coupling_config']['k'] = np.ones((4,4)).tolist()
        model = resolve_winding_model(p)
        self.assertTrue(model['ideal'])
        self.assertEqual(model['L_leak'],0)
        self.assertEqual(model['K'][0,1],1)

    def test_other_singular_matrix_has_explicit_limitation(self):
        p = self.parameters(2)
        p['coupling_config']['k'] = [[1,1,.9],[1,1,.9],[.9,.9,1]]
        with self.assertRaisesRegex(ValueError,'奇异'): resolve_winding_model(p)

    def test_legacy_automatic_turns_resolve_once_then_use_actual_ratios(self):
        p = self.parameters(2)
        p['outputs'][1]['Ns'] = 0
        model = resolve_winding_model(p)
        np.testing.assert_allclose(model['ratios'],[1,.5,1])
        self.assertEqual(model['ratio_sources'],['primary','actual-turns','actual-turns'])
        self.assertEqual(model['transformer_hardware']['windings'][1]['Ns'], 10)
        p['outputs'][1]['Ns'] = 5
        self.assertEqual(resolve_winding_model(p)['ratios'][2],2)

    def test_bad_dimensions_symmetry_and_finiteness_rejected(self):
        for kind,value in (('k',[[1]]),('k',[[1,.8],[.9,1]]),
                           ('k',[[1,float('nan')],[float('nan'),1]]),
                           ('k',[[1,-.1],[-.1,1]]),('k',[[1,1.1],[1.1,1]])):
            with self.subTest(kind=kind,value=value):
                p = self.parameters()
                p['coupling_config'][kind] = value
                with self.assertRaises(ValueError): resolve_winding_model(p)

    def test_old_manual_dcr_never_overrides_geometry_or_blocks_loading(self):
        p = self.parameters()
        reference = resolve_winding_model(p)['R']
        for legacy in ([-.1,.1], [.1], [True,.1], [99., 99.]):
            p['coupling_config']['dcr'] = legacy
            np.testing.assert_array_equal(resolve_winding_model(p)['R'], reference)

    def test_zero_coupling_is_a_valid_decoupled_physical_matrix(self):
        p = self.parameters()
        p['coupling_config']['k'] = [[1,0],[0,1]]
        self.assertAlmostEqual(resolve_winding_model(p)['L_leak'],p['L'])

    def test_resolver_does_not_modify_input_or_share_default_rows(self):
        p = self.parameters(6)
        before = copy.deepcopy(p)
        resolve_winding_model(p)
        self.assertEqual(p,before)
        q = default_coupling_config(6)
        q['k'][0][1] = .9
        self.assertEqual(q['k'][1][0],.995)
        self.assertEqual(default_coupling_config(6)['k'][0][1],.995)


class UIConfigChecks(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        import main
        from engineering_ui import Tooltip
        cls.main, cls.Tooltip = main, Tooltip
        cls.root = tk.Tk()
        cls.root.attributes('-alpha',0)
        cls.update_patch = patch.object(main.PowerSupplyAnalyzer,'schedule_update',return_value=None)
        cls.update_patch.start()
        cls.app = main.PowerSupplyAnalyzer(cls.root)
        cls.original = copy.deepcopy(cls.app._config_dict())
        cls.root.unbind('<Configure>')
        for job in cls.root.tk.call('after','info'): cls.root.after_cancel(job)
        cls.root.geometry('1400x880')
        cls.root.update()

    @classmethod
    def tearDownClass(cls):
        cls.app._closing = True
        cls.app._work_cancel.set()
        cls.Tooltip.hide_all(cls.root)
        for job in cls.root.tk.call('after','info'): cls.root.after_cancel(job)
        cls.root.destroy()
        cls.update_patch.stop()

    def setUp(self):
        self.errors = []
        self.root.report_callback_exception = lambda *exc: self.errors.append(exc)
        self.app._apply_config(copy.deepcopy(self.original))
        self.app._folded_sections.clear()
        self.app.param_search.set('')
        self.app._filter_params()
        self.root.update()

    def tearDown(self):
        self.Tooltip.hide_all(self.root)
        self.root.update()
        self.assertEqual(self.errors,[])

    def multiple(self,count):
        self.app.multi_enabled.set(True)
        self.app.output_count.set(str(count))
        self.app._filter_params()
        self.root.update()

    def shown(self,key):
        return bool(self.app._coupling_widgets[key][0].grid_info())

    def test_single_and_six_output_fields_dimension_and_visibility(self):
        self.app.coupling_enabled.set(True)
        self.assertTrue(self.shown((0,1)))
        self.assertFalse(self.shown((0,2)))
        self.multiple(6)
        p = self.app.get_params()
        self.assertEqual(len(p['coupling_config']['k']),7)
        self.assertTrue(self.shown((5,6)))
        self.assertTrue(self.shown(('dcr',6)))
        self.assertEqual(len(self.app._coupling_vars),21)

    def test_symmetry_and_readonly_geometry_dcr_round_trip(self):
        self.multiple(2)
        self.app.coupling_enabled.set(True)
        self.app._coupling_vars[1,2].set('.994')
        self.app._coupling_dcr_vars[2].set('35')
        before = self.app.get_params()['coupling_config']
        self.assertEqual(before['k'][1][2],before['k'][2][1])
        model = resolve_winding_model(self.app.get_params())
        self.assertEqual(model['dcr_source'], 'geometry')
        self.assertNotAlmostEqual(model['R'][2], .035)
        # The compatibility StringVar is now display-only; changing its
        # text cannot create a separate electrical resistance input.
        self.app._coupling_dcr_vars[2].set('not an input')
        np.testing.assert_array_equal(resolve_winding_model(self.app.get_params())['R'], model['R'])
        config = json.loads(json.dumps(self.app._config_dict()))
        self.app._apply_config(config)
        self.assertEqual(self.app.get_params()['coupling_config'],before)

    def test_count_changes_preserve_hidden_pair_drafts(self):
        self.multiple(6)
        self.app.coupling_enabled.set(True)
        self.app._coupling_vars[5,6].set('.994')
        self.app.get_params()
        self.app.output_count.set('2')
        self.assertEqual(len(self.app.get_params()['coupling_config']['k']),3)
        self.app.output_count.set('6')
        self.assertEqual(self.app.get_params()['coupling_config']['k'][5][6],.994)

    def test_active_invalid_blocks_but_disabled_draft_does_not(self):
        self.app.coupling_enabled.set(True)
        self.app._coupling_vars[0,1].set('-')
        with self.assertRaisesRegex(ValueError,'k'): self.app.get_params()
        self.app.coupling_enabled.set(False)
        self.assertFalse(self.app.get_params()['coupling_config']['enabled'])
        self.app._config_dict()
        self.app.coupling_enabled.set(True)
        with self.assertRaisesRegex(ValueError,'k'): self.app.get_params()

    def test_unsupported_context_hides_and_disables_without_discarding_drafts(self):
        self.app.coupling_enabled.set(True)
        self.app._coupling_vars[0,1].set('.99')
        self.app.params['topology'].set(self.main.TOPO_LABEL['QR-FLYBACK'])
        self.assertFalse(self.shown((0,1)))
        self.assertFalse(self.app.get_params()['coupling_config']['enabled'])
        self.app.params['topology'].set(self.main.TOPO_LABEL['FLYBACK'])
        self.assertEqual(self.app.get_params()['coupling_config']['k'][0][1],.99)
        self.app.feedback_mode.set('PSR-MP6005')
        self.assertFalse(self.app.get_params()['coupling_config']['enabled'])
        self.assertFalse(self.shown((0,1)))

    def test_invalid_loaded_matrix_does_not_change_valid_ui(self):
        before = copy.deepcopy(self.app._config_dict())
        bad = copy.deepcopy(before)
        bad['coupling_config'] = dict(enabled=True,k=[[1,.9],[.7,1]],dcr=[.02,.02])
        with self.assertRaisesRegex(ValueError,'对称'): self.app._apply_config(bad)
        self.assertEqual(self.app._config_dict(),before)

    def test_buck_disabled_coupling_does_not_read_inapplicable_turns_or_ratio(self):
        config = copy.deepcopy(self.original)
        config.update(topology='BUCK',N=0,Np=0,Ns=0)
        self.app._apply_config(config)
        self.app.params['N'].set('not used')
        self.assertFalse(self.app.get_params()['coupling_config']['enabled'])
        self.assertFalse(self.app._config_dict()['coupling_config']['enabled'])

    def test_search_and_fold_follow_the_existing_parameter_panel(self):
        self.multiple(3)
        self.app.coupling_enabled.set(True)
        self.app._folded_sections.add(self.app._param_sections['mag'])
        self.app._filter_params()
        self.assertFalse(self.shown((0,3)))
        self.app.param_search.set('kij')
        self.app._filter_params()
        self.assertTrue(self.shown((0,3)))
        self.assertFalse(self.shown((0,4)))

    def test_results_show_solved_voltage_power_and_local_conduction_mode(self):
        rail=dict(id=1,name='主输出',spec=dict(V_out=30,P_out=30),
                  op=dict(V_out=29.9,P_out=29.8,I_d_rms=1.4,mode='CCM',local_mode='DCM'),
                  ripple_pp=.02,P_rectifier=.7,P_cap=.05)
        result=dict(op=dict(coupled_model=dict(enabled=True,ideal_fallback=False)),
                    mag={},outputs=[rail])
        self.app._update_isolated_results(dict(topology='FLYBACK',feedback_output=1),result)
        item=self.app.output_tree.item(self.app.output_tree.get_children()[0],'values')
        self.assertEqual(item[1],'30 / 30')
        self.assertEqual(item[2],'29.9 / 29.8')
        self.assertEqual(item[3],'DCM')
        self.assertIn('周期平均电荷平衡',self.app.output_note.get())
        result['op']['coupled_model']['ideal_fallback']=True
        self.app._update_isolated_results(dict(topology='FLYBACK',feedback_output=1),result)
        item=self.app.output_tree.item(self.app.output_tree.get_children()[0],'values')
        self.assertIn('标称',item[2])
        self.assertIn('不唯一',self.app.output_note.get())

    def test_single_coupled_output_result_tab_is_available(self):
        self.app.coupling_enabled.set(True)
        self.app._sync_isolated_result_tabs()
        self.assertNotEqual(self.app._isolated_result_book.tab(self.app._isolated_result_pages[1],'state'),'hidden')


if __name__ == '__main__': unittest.main(verbosity=2)
