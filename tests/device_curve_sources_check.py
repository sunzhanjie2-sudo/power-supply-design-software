"""Unified source-selection regressions, using only test-owned withdrawn Tk."""
import copy
import json
from pathlib import Path
import sys
import tkinter as tk
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT)); sys.path.insert(0, str(ROOT/'tests'))
from runtime_resources import configure_numeric_threads
configure_numeric_threads()
from device_curve_sources import (TRANSFER, CHARGE, validate_settings, source_for,
    inferred_settings, effective_sources, validate_requests, targets)
from diode_curves_check import curve, spec
from mos_curves_check import demo
from mos_gate_charge_curve_check import profile
from loss_model import compute_design


def complete():
    p = spec()
    p.update(mos_miller_mode='curve', mos_miller_curve=demo(), mos_charge_mode='curve',
             mos_charge_curve=profile(), mos_manual_events={},
             diode_curves={row['target']: curve(row['target']) for row in targets(p) if row['target'].startswith('D')})
    return p


class SourceChecks(unittest.TestCase):
    def test_switch_to_fixed_changes_models_not_saved_data(self):
        p = complete(); saved = copy.deepcopy(p)
        p['device_curve_settings'] = dict(mode='fixed', overrides={})
        result = compute_design(p)
        self.assertEqual(result['semi']['switch']['gate']['mode'], 'fixed')
        self.assertEqual(result['semi']['switch']['gate']['charge_mode'], 'manual')
        self.assertTrue(all(m['model']=='fixed_vf' for m in result['diode_models']))
        self.assertEqual(p['mos_charge_curve'], saved['mos_charge_curve'])
        self.assertEqual(p['diode_curves'], saved['diode_curves'])
        p['device_curve_settings']['mode'] = 'curve'
        result = compute_design(p)
        self.assertEqual(result['semi']['switch']['gate']['mode'], 'curve')
        self.assertEqual(result['semi']['switch']['gate']['charge_mode'], 'curve')
        self.assertTrue(all(m['model']=='vf_if_curve' for m in result['diode_models']))

    def test_per_device_fixed_exception_does_not_affect_others(self):
        p = complete(); p['device_curve_settings'] = dict(mode='curve', overrides={'D1':'fixed'})
        result = compute_design(p)
        models = {m['ref']:m['model'] for m in result['diode_models']}
        self.assertEqual(models['D1'], 'fixed_vf'); self.assertEqual(models['D_IN'], 'vf_if_curve')
        self.assertEqual(result['semi']['switch']['gate']['mode'], 'curve')

    def test_missing_requested_curves_never_fall_back(self):
        p = spec(); p['device_curve_settings'] = dict(mode='curve', overrides={TRANSFER:'fixed', CHARGE:'fixed'})
        with self.assertRaisesRegex(ValueError, 'D1.*待导入|待导入.*D1'): compute_design(p)
        p['device_curve_settings']['overrides'].update({row['target']:'fixed' for row in targets(p)})
        compute_design(p)
        # Dormant targets must not block unrelated topologies.
        p['device_curve_settings']['overrides']['D_F6'] = 'curve'
        validate_requests(p)

    def test_legacy_mapping_and_strict_source_validation(self):
        for p in (spec(), complete(), dict(spec(), gfs=5.)):
            q = dict(p, device_curve_settings=inferred_settings(p))
            for row in targets(p): self.assertEqual(source_for(p,row['target']), source_for(q,row['target']))
        for data in ([], 0, {'mode':'wat'}, {'mode':'fixed','overrides':{'Q2':'curve'}},
                     {'mode':'curve','overrides':{CHARGE:'legacy'}}):
            with self.assertRaises(ValueError): validate_settings(data)

    def test_backend_api_and_direct_losses_use_same_policy(self):
        from design_api import load_spec
        from loss_model import total_losses
        p = complete(); p['device_curve_settings'] = dict(mode='fixed',overrides={'D1':'curve'})
        resolved = load_spec(p)
        self.assertEqual(resolved['diode_curves'], p['diode_curves'])
        self.assertEqual(set(effective_sources(resolved)['diode_curves']), {'D1'})
        result = compute_design(p)
        again = total_losses(result['op'], p, result['wf'])
        self.assertEqual(result['P_total'], again['P_total'])
        self.assertEqual(p['diode_curves'].keys(), complete()['diode_curves'].keys())

    def test_equal_endpoints_respect_explicit_fixed_four_event_override(self):
        from input_voltage_range import calculate_input_endpoints
        from mos_four_manual_check import events
        p=complete(); p.update(V_in_min=30.,V_in_max=30.,mos_manual_events=events(),
                               device_curve_settings=dict(mode='fixed',overrides={}))
        cases=calculate_input_endpoints(p,include_loop=False,include_cross_regulation=False)['cases']
        self.assertTrue(all(not case.get('error') for case in cases))
        self.assertNotEqual(cases[0]['result']['semi']['switch']['t2'],cases[1]['result']['semi']['switch']['t2'])

    def test_word_and_xlsx_capture_provenance_not_dormant_curves(self):
        from device_curve_report import add_device_source_report
        from docx_layout import new_document
        from report_xlsx import _capture_document
        p = complete(); p['device_curve_settings'] = dict(mode='fixed', overrides={'D1':'curve'})
        result = compute_design(p); doc = new_document('来源核对','单元测试','来源核对'); add_device_source_report(doc,p,result)
        text = '\n'.join(cell.text for table in doc.tables for row in table.rows for cell in row.cells)
        self.assertIn('已存曲线但未启用', text); self.assertIn('D1',text)
        self.assertIn('固定值',text); self.assertIn('曲线',text)
        capture = repr(_capture_document(doc))
        self.assertIn('器件计算方式与数据来源',capture); self.assertIn('已存曲线但未启用',capture)


class SourceUI(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        import main
        cls.root = tk.Tk(); cls.root.withdraw()
        cls.schedule = patch.object(main.PowerSupplyAnalyzer,'schedule_update',return_value=None)
        cls.schedule.start(); cls.app = main.PowerSupplyAnalyzer(cls.root)
        cls.base = json.loads((ROOT/'examples/40W_CCM_FLYBACK.json').read_text(encoding='utf-8'))
    @classmethod
    def tearDownClass(cls):
        cls.app._closing=True; cls.app._calculation_worker.close()
        for job in cls.root.tk.call('after','info'): cls.root.after_cancel(job)
        cls.root.destroy(); cls.schedule.stop()
    def setUp(self):
        self.errors=[]; self.root.report_callback_exception=lambda *args:self.errors.append(args)
        self.app._apply_config(copy.deepcopy(self.base))
    def tearDown(self):
        self.root.update(); self.assertEqual(self.errors,[])
    def test_one_location_axes_targets_and_context_only(self):
        a=self.app
        self.assertEqual(list(a._param_sections)[:3],['spec','curves','stage'])
        self.assertFalse(hasattr(a,'_diode_tree')); self.assertFalse(hasattr(a,'_mos_mode_combo'))
        for target,axes in ((TRANSFER,'X=Vgs'),(CHARGE,'X=Qg'),('D1','X=Vf')):
            a._curve_tree.selection_set(target); a._curve_selection_note()
            self.assertIn(axes,a._curve_detail.get())
        a.params['topology'].set('BUCK'); a._filter_params()
        self.assertNotIn('D_F1',a._curve_tree.get_children())
        a._apply_config(json.loads((ROOT/'examples/3_OUTPUT_COUPLED_FLYBACK.json').read_text(encoding='utf-8')))
        children=set(a._curve_tree.get_children())
        self.assertTrue({'D_O1','D_O2','D_O3'}.issubset(children)); self.assertNotIn('D1',children)
        self.assertFalse(any(target.startswith('D_F') for target in children))

    def test_missing_curve_status_persistence_and_explicit_fixed_fallback(self):
        a=self.app; a._curve_global.set('curve'); a._choose_global_curve_mode()
        self.assertIn('待导入',a._curve_summary.get())
        with self.assertRaisesRegex(ValueError,'待导入'): a.get_params()
        saved=a._config_dict(); a._apply_config(saved)
        self.assertEqual(a._device_curve_settings,saved['device_curve_settings'])
        with self.assertRaisesRegex(ValueError,'待导入'): a.get_params()
        a._curve_global.set('fixed'); a._choose_global_curve_mode(); a.get_params()
        self.assertNotIn('待导入',a._curve_summary.get())

    def test_fixed_toggle_keeps_curves_and_manual_drafts(self):
        a=self.app; a._diode_curves={'D1':curve('保留的曲线')}; a._mos_charge_curve=profile()
        draft=copy.deepcopy(a._manual_events_value()); a._set_curve_override('D1','curve')
        a._curve_global.set('fixed'); a._choose_global_curve_mode()
        saved=a._config_dict(); a._apply_config(saved)
        self.assertEqual(a._diode_curves['D1']['name'],'保留的曲线')
        from mos_gate_charge import validate_charge
        self.assertEqual(a._mos_charge_curve,validate_charge(profile())); self.assertEqual(a._manual_events_value(),draft)
        a._curve_tree.selection_set('D1'); a._curve_selection_note()
        self.assertIn('已存但不使用',a._curve_detail.get())
        a._set_curve_override('D1','curve')
        self.assertIn('混合来源',a._curve_summary.get())
        self.assertEqual(source_for(a.get_params(),'D1'),'curve')
        a._apply_config({}); self.assertEqual(a._device_curve_settings,{})

    def test_unbind_is_explicit_local_and_cancel_preserves_binding(self):
        a=self.app; a._diode_curves={'D1':curve('保留的曲线')}; a._set_curve_override('D1','curve')
        a._curve_tree.selection_set('D1')
        with patch('device_curve_ui.messagebox.askyesno',return_value=False): a._unbind_selected_curve()
        self.assertIn('D1',a._diode_curves)
        with patch('device_curve_ui.messagebox.askyesno',return_value=True): a._unbind_selected_curve()
        self.assertNotIn('D1',a._diode_curves); self.assertEqual(source_for(a.get_params(),'D1'),'fixed')

    def test_reuse_requires_explicit_targets_and_owns_independent_data(self):
        from tkinter import ttk
        a=self.app; a._diode_curves={'D1':curve('仅复用所选')}; a._set_curve_override('D1','curve')
        a._curve_tree.selection_set('D1')
        original=tk.Toplevel
        def hidden(*args,**kwargs):
            dialog=original(*args,**kwargs); dialog.withdraw(); return dialog
        with patch('device_curve_ui.tk.Toplevel',side_effect=hidden):
            a._reuse_diode_curve()
        dialog=next(w for w in self.root.winfo_children() if isinstance(w,original))
        checks=[w for w in dialog.winfo_children() if isinstance(w,ttk.Checkbutton)]
        next(w for w in checks if str(w.cget('text')).startswith('D_OUT')).invoke()
        with patch('device_curve_ui.messagebox.askyesno',return_value=True):
            next(w for w in dialog.winfo_children() if isinstance(w,ttk.Button) and w.cget('text')=='复制并启用所选').invoke()
        self.assertEqual(set(a._diode_curves),{'D1','D_OUT'})
        self.assertEqual(a._diode_curves['D1'],a._diode_curves['D_OUT'])
        self.assertIsNot(a._diode_curves['D1']['points'],a._diode_curves['D_OUT']['points'])
        self.assertEqual(source_for(a.get_params(),'D_OUT'),'curve')

    def test_preview_and_curve_hub_folding_release_content(self):
        a=self.app; a._diode_curves={'D1':curve('预览校核')}; a._set_curve_override('D1','curve')
        a._curve_tree.selection_set('D1')
        original=tk.Toplevel
        def hidden(*args,**kwargs):
            dialog=original(*args,**kwargs); dialog.withdraw(); return dialog
        with patch('device_curve_ui.tk.Toplevel',side_effect=hidden): a._preview_selected_curve()
        dialog=a._device_curve_preview; self.assertIsNotNone(dialog)
        dialog.destroy(); self.assertIsNone(a._device_curve_preview)
        frame=a._param_sections['curves']; a._folded_sections.discard(frame); a._filter_params(); self.root.update_idletasks()
        before=frame._section_container.winfo_reqheight()
        a._fold_section(frame); self.root.update_idletasks()
        self.assertLess(frame._section_container.winfo_reqheight(),before/2)


if __name__=='__main__': unittest.main(verbosity=2)
