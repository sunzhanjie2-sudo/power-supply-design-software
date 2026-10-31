"""Master-calculation, report and owned-Tk regression for winding coupling.

Only this test's transparent Tk window is controlled. No user window or
desktop pixels are read. Run this file directly from the project checkout.
"""
import copy
import json
from pathlib import Path
import sys
import tkinter as tk
import unittest
from unittest.mock import patch

import numpy as np

sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from power_stage import DEFAULT_PARAMS
from loss_model import compute_design
from waveforms import make_waveforms
from winding_coupling import default_coupling_config


from coupled_test_fixtures import configuration


class MasterCouplingChecks(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.p=configuration()
        cls.result=compute_design(cls.p)
        cls.p6=configuration(6)
        cls.six=compute_design(cls.p6)

    def test_real_six_output_master_path_is_finite_and_converged(self):
        result=self.six
        self.assertEqual(len(result['outputs']),6)
        self.assertEqual(len(result['wf']['outputs']),6)
        self.assertEqual(np.asarray(result['op']['coupled_model']['K']).shape,(7,7))
        self.assertTrue(result['op']['coupled_model']['converged'])
        self.assertLess(result['op']['coupled_model']['energy_balance_relative'],1e-5)
        for key in ('P_total','P_semi','P_mag','P_cap','P_cap_in','P_rcd','eta'):
            self.assertTrue(np.isfinite(result[key]),key)
        for wf in result['wf']['outputs']:
            for key in ('i_d','i_c','vout','v_sw'):
                self.assertTrue(np.all(np.isfinite(wf[key])),key)

    def test_fixed_hardware_preserves_resolved_integer_turns_and_dcr(self):
        from analysis_workflows import pin_hardware
        fixed=pin_hardware(self.p,self.result)
        self.assertEqual([r['Ns'] for r in fixed['outputs']],
                         [w['Ns'] for w in self.result['mag']['transformer']['windings']])
        solved=compute_design(fixed)
        self.assertEqual(solved['op']['coupled_model']['ratios'],self.result['op']['coupled_model']['ratios'])
        np.testing.assert_allclose(solved['op']['coupled_model']['R'], self.result['op']['coupled_model']['R'])

    def test_branch_capacitors_and_rectifier_losses_use_real_pulse_current(self):
        result=self.result
        cap_sum=0.
        for rail,wf in zip(result['outputs'],result['wf']['outputs']):
            child=rail['op']
            self.assertLess(wf['charge_sampling_relative'],.002)
            self.assertAlmostEqual(float(np.sqrt(np.mean(wf['i_d']**2))),child['I_d_rms'],
                                   delta=max(child['I_d_rms']*.003,1e-5))
            bank=rail['capacitors']['output']
            ac=wf['i_c']-np.mean(wf['i_c'])
            self.assertAlmostEqual(bank['total_bank'],float(np.sqrt(np.mean(ac**2))),places=10)
            cap_loss=sum(c['ESR']*c['total']**2 for c in bank['caps'])
            self.assertAlmostEqual(rail['P_cap'],cap_loss,places=10)
            expected=rail['spec']['Vf_diode']*child['I_d_avg']+rail['spec']['Rd_diode']*child['I_d_rms']**2
            self.assertAlmostEqual(rail['diode']['P_cond'],expected,places=10)
            cap_sum+=cap_loss
        self.assertAlmostEqual(result['P_cap'],cap_sum,places=10)
        self.assertNotAlmostEqual(result['outputs'][1]['op']['I_d_pk']/result['outputs'][0]['op']['I_d_pk'],
                                  self.p['outputs'][1]['P_out']/self.p['outputs'][0]['P_out'],places=3)

    def test_dcr_is_used_once_in_copper_and_not_added_again_to_total_input(self):
        result=self.result
        tr=result['mag']['transformer']
        meta=result['op']['coupled_model']
        self.assertEqual(tr['dcr_source'],'geometry')
        self.assertAlmostEqual(tr['R_dc_p'],meta['R'][0])
        expected=tr['Fr_p']*meta['R'][0]*meta['winding_rms'][0]**2
        for i,winding in enumerate(tr['windings'],1):
            self.assertAlmostEqual(winding['R_dc'],meta['R'][i])
            loss=winding['Fr']*meta['R'][i]*meta['winding_rms'][i]**2
            self.assertAlmostEqual(winding['P_cu'],loss,places=9)
            expected+=loss
        self.assertAlmostEqual(tr['P_cu'],expected,places=9)
        self.assertAlmostEqual(result['P_mag'],tr['P_cu']+tr['P_core'],places=9)
        ledger=sum(result[k] for k in ('P_semi','P_mag','P_cap','P_cap_in','P_sense',
                                       'P_rcd','P_din','P_dout','P_clamp','P_controller'))
        self.assertAlmostEqual(result['P_total'],ledger,places=9)
        self.assertAlmostEqual(result['P_in'],result['P_out']+ledger,places=9)
        self.assertAlmostEqual(result['P_rcd'],meta['P_rcd'],places=9)

    def test_disabling_matrix_restores_the_original_nominal_distribution(self):
        p=copy.deepcopy(self.p)
        p['coupling_config']['enabled']=False
        old=compute_design(p)
        self.assertNotIn('coupled_model',old['op'])
        ratio=old['outputs'][1]['op']['I_d_pk']/old['outputs'][0]['op']['I_d_pk']
        expected=(p['outputs'][1]['P_out']/p['outputs'][0]['P_out']*
                  old['outputs'][1]['op']['N']/old['outputs'][0]['op']['N'])
        self.assertAlmostEqual(ratio,expected,places=10)
        self.assertEqual([r['op']['V_out'] for r in old['outputs']],[30,12.5,5])
        for child, winding in zip(old['outputs'], old['mag']['transformer']['windings']):
            self.assertAlmostEqual(child['op']['V_out'], 30 * winding['Ns'] / 12)

    def test_local_ccm_dcm_and_actual_unregulated_output_are_exposed(self):
        op=self.result['op']
        self.assertEqual(op['mode'],'CCM')
        self.assertEqual([q['branch_mode'] for q in op['output_ops']],['CCM','DCM','DCM'])
        self.assertAlmostEqual(op['output_ops'][0]['V_out'],30,places=6)
        self.assertGreater(abs(op['output_ops'][1]['V_out']-12.5),.05)
        self.assertEqual(op['output_ops'][1]['V_out_target'],12.5)

    def test_json_report_and_master_calculation_do_not_mutate_input(self):
        from design_api import run_design
        p=copy.deepcopy(self.p)
        before=copy.deepcopy(p)
        report=run_design(p)
        self.assertTrue(report['ok'],report.get('error'))
        json.dumps(report,ensure_ascii=False)
        self.assertEqual(p,before)
        self.assertEqual([r['mode'] for r in report['outputs']],['CCM','DCM','DCM'])
        self.assertEqual(report['loop']['model']['kind'],'coupled-period-map')
        self.assertEqual(len(report['loop']['dc_load_V_per_A']),3)
        self.assertTrue(report['coupling']['converged'])
        self.assertAlmostEqual(report['flyback_clamp']['P_res'],report['losses']['P_rcd'])

    def test_all_k_one_has_no_artificial_leakage_clamp_spike(self):
        p=copy.deepcopy(self.p)
        p['coupling_config']['k']=np.ones((4,4)).tolist()
        result=compute_design(p)
        op=result['op']
        self.assertTrue(op['coupled_model']['ideal_fallback'])
        self.assertEqual(op['coupled_model']['L_leak'],0.)
        self.assertEqual(result['P_rcd'],0.)
        self.assertEqual(op['clamp']['P_res'],0.)
        self.assertAlmostEqual(op['clamp']['V_peak'],op['clamp']['V_plateau'])
        self.assertLessEqual(float(np.max(result['wf']['v_sw'])),op['clamp']['V_plateau']+1e-9)


class OwnedTkCouplingChecks(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        import main
        from engineering_ui import Tooltip
        cls.main,cls.Tooltip=main,Tooltip
        cls.root=tk.Tk()
        cls.root.attributes('-alpha',0)
        cls.update_patch=patch.object(main.PowerSupplyAnalyzer,'schedule_update',return_value=None)
        cls.update_patch.start()
        cls.app=main.PowerSupplyAnalyzer(cls.root)
        cls.original=copy.deepcopy(cls.app._config_dict())
        cls.root.unbind('<Configure>')
        for job in cls.root.tk.splitlist(cls.root.tk.call('after','info')): cls.root.after_cancel(job)
        cls.root.geometry('1100x760')
        cls.root.update()

    @classmethod
    def tearDownClass(cls):
        cls.app._closing=True
        cls.app._work_cancel.set()
        cls.Tooltip.hide_all(cls.root)
        for job in cls.root.tk.splitlist(cls.root.tk.call('after','info')): cls.root.after_cancel(job)
        cls.root.destroy()
        cls.update_patch.stop()

    def setUp(self):
        self.errors=[]
        self.root.report_callback_exception=lambda *exc: self.errors.append(exc)
        self.app._apply_config(configuration())
        self.app._control_ready=False
        self.app.nb.select(self.app.tab_topology)

    def tearDown(self):
        self.Tooltip.hide_all(self.root)
        self.root.update()
        self.assertEqual(self.errors,[])

    def calculate(self):
        self.assertTrue(self.app.update_all(),self.app.status_var.get())
        self.root.update()
        self.assertFalse(self.app.status_var.get().startswith(('Refresh:','Power:','Error:')),
                         self.app.status_var.get())
        return self.app._last

    def test_left_couplings_save_load_and_actual_results_table(self):
        self.app._coupling_vars[1,2].set('.994')
        self.app._coupling_dcr_vars[2].set('35')
        snapshot=self.calculate()
        self.assertEqual(snapshot['op']['coupled_model']['K'][1][2],.994)
        winding = snapshot['res']['mag']['transformer']['windings'][1]
        expected = snapshot['p']['rho'] * snapshot['res']['mag']['transformer']['MLT'] * winding['Ns'] / (
            winding['n_strand_s'] * np.pi * winding['d_wire_s'] ** 2 / 4)
        self.assertAlmostEqual(snapshot['op']['coupled_model']['R'][2], expected)
        self.assertNotAlmostEqual(expected, .035)
        saved=json.loads(json.dumps(self.app._config_dict()))
        self.app._apply_config(copy.deepcopy(self.original))
        self.assertFalse(self.app.coupling_enabled.get())
        self.app._apply_config(saved)
        after=self.calculate()
        self.assertEqual(after['p']['coupling_config'],saved['coupling_config'])
        values=[self.app.output_tree.item(row,'values') for row in self.app.output_tree.get_children()]
        self.assertEqual([row[3] for row in values],
                         [q['branch_mode'] for q in after['op']['output_ops']])
        self.assertEqual(values[1][2],f"{after['op']['output_ops'][1]['V_out']:.5g} / {after['op']['output_ops'][1]['P_out']:.5g}")

    def test_bode_and_compensation_tabs_keep_the_new_model_accessible(self):
        self.calculate()
        for page in (self.app.tab_loop,self.app.tab_comp):
            self.assertNotEqual(self.app.nb.tab(page,'state'),'hidden')
        self.app.coupling_enabled.set(False)
        self.calculate()
        for page in (self.app.tab_loop,self.app.tab_comp):
            self.assertNotEqual(self.app.nb.tab(page,'state'),'hidden')
        self.assertNotIn('coupled_model',self.app._last['op'])

    def test_invalid_psd_matrix_invalidates_snapshot_instead_of_reusing_it(self):
        self.calculate()
        self.assertTrue(self.app._snapshot_valid)
        self.app._coupling_vars[0,1].set('.999')
        self.app._coupling_vars[0,2].set('.999')
        self.app._coupling_vars[1,2].set('.1')
        with patch('traceback.print_exc'):
            self.assertFalse(self.app.update_all())
        self.assertFalse(self.app._snapshot_valid)
        self.assertIsNone(self.app._loop_result)
        self.assertIn('半正定',self.app.status_var.get())
        with self.assertRaisesRegex(ValueError,'半正定'):
            self.app._config_dict()

    def test_rcd_plot_uses_the_same_matrix_waveform_not_an_added_second_spike(self):
        snapshot=self.calculate()
        self.app.nb.select(self.app.tab_rcd)
        self.app._refresh_visible_tab()
        self.root.update()
        line=self.app.ax_rcd[1].lines[0]
        expected=make_waveforms(snapshot['op'],n_cycles=3,n_pts=4096)
        np.testing.assert_allclose(line.get_xdata(),expected['t']*1e6)
        np.testing.assert_allclose(line.get_ydata(),expected['v_sw'])
        self.assertAlmostEqual(float(np.max(line.get_ydata())),snapshot['op']['clamp']['V_peak'],
                               delta=.02)
        self.assertAlmostEqual(snapshot['res']['P_rcd'],snapshot['op']['coupled_model']['P_rcd'])

    def test_coupled_topology_diagram_and_rcd_component_values_remain_available(self):
        from flyback_clamp import rcd_components
        snapshot=self.calculate()
        # Call the updater directly: the lazy-page wrapper intentionally
        # catches render errors, so update_all=True alone cannot prove this.
        self.app._update_topology(snapshot['op'],snapshot['p'])
        refs=set(self.app.topology_tree.get_children())
        self.assertTrue({'T1','D_O1','D_O2','D_O3','R_SN1','C_SN1'} <= refs)
        rcd=rcd_components(snapshot['op'],snapshot['p'])
        resistor=self.app.topology_tree.item('R_SN1','values')[2]
        capacitor=self.app.topology_tree.item('C_SN1','values')[2]
        self.assertIn(self.main.fmt_eng(rcd['R_snub'],'Ω'),resistor)
        self.assertIn(self.main.fmt_eng(rcd['C_snub'],'F'),capacitor)


def preview():
    """Optional real-data preview using only this process's owned HWND."""
    from tkinter import ttk
    from parameter_panel_preview import capture, main
    output=Path(__file__).resolve().parents[1]/'_tmp_coupled_integration_qa'
    output.mkdir(exist_ok=True)
    root=tk.Tk()
    root.attributes('-alpha',0)
    with patch.object(main.PowerSupplyAnalyzer,'schedule_update',return_value=None):
        app=main.PowerSupplyAnalyzer(root)
        root.unbind('<Configure>')
        for job in root.tk.splitlist(root.tk.call('after','info')): root.after_cancel(job)
        root.geometry('1000x700')
        root.update()
        main._apply_fonts(ttk.Style(root),.7)
        app._apply_config(configuration())
        app._control_ready=False
        assert app.update_all(),app.status_var.get()
        assert not app.status_var.get().startswith(('Refresh:','Power:','Error:')),app.status_var.get()
        app._folded_sections.clear()
        app.param_search.set('kij')
        app._filter_params()
        root.update()
        app.nb.select(app.tab_rcd)
        app._refresh_visible_tab()
        root.update()
        capture(root,output/'01_rcd_coupled_window.png')
        app.fig_rcd.savefig(output/'02_rcd_coupled_plot.png',dpi=120)
        app.nb.select(app.tab_topology)
        app._isolated_result_book.select(app._isolated_result_pages[1])
        app._refresh_visible_tab()
        root.update()
        capture(root,output/'03_actual_outputs_table.png')
        app.nb.select(app.tab_power)
        app._refresh_visible_tab()
        root.update()
        app._output_result_cards['power'][2]['figure'].savefig(output/'04_out2_dcm_power.png',dpi=110)
        for job in root.tk.splitlist(root.tk.call('after','info')): root.after_cancel(job)
        app._closing=True
        app._work_cancel.set()
        root.destroy()
    print(f'Own-window real-data previews: {output}')


if __name__=='__main__':
    if '--preview' in sys.argv: preview()
    else: unittest.main(verbosity=2)
