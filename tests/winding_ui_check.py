"""Owned Tk window: local geometry, complete windings and persistent SI config."""
from pathlib import Path
import gc
import sys
import time
import tkinter as tk
from tkinter import ttk
import unittest
import weakref
import matplotlib
matplotlib.rcParams['font.sans-serif']=['Microsoft YaHei','SimHei','DejaVu Sans']
matplotlib.rcParams['axes.unicode_minus']=False
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from winding_ui import WindingUI
from winding_layout import validate_winding_config


def source():
    tr=dict(ok=True,Np=6,Ns=12,n_strand_p=40,n_strand_s=30,d_wire_p=.1e-3,d_wire_s=.1e-3,
        windings=[dict(id=i,name=f'输出{i}',Ns=i+2,n_strand_s=2,d_wire_s=.2e-3) for i in range(1,7)],
        auxiliary=dict(Na=4,d_wire=.15e-3))
    return dict(mag=dict(transformer=tr))


class Host(WindingUI):
    def __init__(self,root):
        self.root=root;self._closing=False;self._snapshot_valid=True
        self._init_winding_state()
        self.frame=ttk.Frame(root);self.frame.pack(fill='both',expand=True)
        self._build_winding_tab(self.frame)


class WindingUIChecks(unittest.TestCase):
    def setUp(self):
        self.root=tk.Tk();self.root.attributes('-alpha',0);self.root.geometry('970x700')
        self.errors=[]
        self.root.report_callback_exception=lambda *exc:self.errors.append(exc)
        self.app=Host(self.root)
        self.app._update_winding({}, {}, source())
        self.root.update()

    def tearDown(self):
        self.app._closing=True;self.app._cancel_winding_redraw()
        self.root.update();self.root.destroy()
        self.assertEqual(self.errors,[])

    def configured(self):
        self.app._winding_vars['window_width'].set('12')
        self.app._winding_vars['window_height'].set('8')
        self.app._refresh_winding();self.root.update()

    def test_primary_six_outputs_and_auxiliary_are_all_visible(self):
        rows=self.app._ordered_winding_rows()
        self.assertEqual([r['id'] for r in rows],['P']+[f'OUT{i}' for i in range(1,7)]+['AUX'])
        self.assertEqual(len(self.app._winding_rows_frame.grid_slaves()),4*9)

    def test_geometry_source_does_not_retain_full_electrical_snapshot(self):
        import numpy as np
        electrical=source()
        electrical['wf']={'t':np.arange(10000.)}
        reference=weakref.ref(electrical['wf']['t'])
        self.app._update_winding({}, {}, electrical)
        rows=self.app._ordered_winding_rows()
        del electrical
        gc.collect()
        self.assertIsNone(reference())
        self.assertEqual(rows[0]['id'],'P')
        self.assertEqual(rows[0]['turns'],6)
        self.configured()
        self.assertIsNotNone(self.app._winding_assessment)

    def test_defaults_use_equivalent_litz_and_single_copper_without_flattening(self):
        self.configured()
        rows={row['id']:row for row in self.app._winding_assessment['windings']}
        self.assertEqual(rows['P']['wire_type'],'litz')
        self.assertAlmostEqual(rows['P']['flatten_ratio'],1.5)
        self.assertEqual(rows['AUX']['wire_type'],'solid')
        self.assertEqual(rows['AUX']['bundle_width'],rows['AUX']['bundle_height'])

    def test_selected_details_bind_correct_winding_and_choices(self):
        self.configured()
        self.app._winding_selected.set('OUT1')
        variables=self.app._winding_override_vars('OUT1')
        entry=self.app._winding_detail_widgets['parallel_bundles']
        self.assertEqual(str(entry.cget('textvariable')),str(variables['parallel_bundles']))
        self.app._winding_detail_choices['winding_style'].set('密绕：靠右')
        self.app._winding_detail_choices['wire_type'].set('普通铜线（不压扁）')
        self.app._refresh_winding()
        row=next(row for row in self.app._winding_assessment['windings'] if row['id']=='OUT1')
        self.assertEqual(row['winding_style'],'dense_right')
        self.assertEqual(row['wire_type'],'solid')
        self.assertEqual(row['bundle_width'],row['bundle_height'])
        self.assertEqual(self.app._winding_override_vars('P')['wire_type'].get(),'auto')

    def test_equivalent_bundle_settings_si_roundtrip_and_do_not_multiply_copper(self):
        self.configured()
        variables=self.app._winding_override_vars('P')
        for name,value in dict(parallel_bundles='2',packing_factor='.8',bundle_diameter='.8',
                outer_diameter='.14',flatten_ratio='1.7',turns_per_layer='2',winding_style='dense_left').items():
            variables[name].set(value)
        self.app._refresh_winding()
        cfg=self.app._winding_config()
        entry=cfg['winding_config']['overrides']['P']
        self.assertAlmostEqual(entry['bundle_diameter'],.0008)
        self.assertAlmostEqual(entry['outer_diameter'],.00014)
        row=self.app._winding_assessment['windings'][0]
        self.assertEqual(row['strands_per_bundle'],20)
        self.assertEqual(row['parallel_bundles'],2)
        self.assertEqual(row['conductor_count'],6*40)
        self.app._load_winding_config({});self.app._load_winding_config(cfg)
        self.assertEqual(self.app._winding_config(),cfg)

    def test_legacy_rectangular_bundle_requires_explicit_conversion(self):
        cfg=dict(winding_config=dict(window_width=.012,window_height=.008,
            overrides={'P':dict(outer_diameter=.15e-3,strand_columns=8)}))
        self.app._load_winding_config(cfg);self.app._refresh_winding();self.root.update()
        entry=self.app._winding_config()['winding_config']['overrides']['P']
        self.assertEqual(set(entry),{'outer_diameter','strand_columns'})
        self.assertEqual(str(self.app._winding_detail_widgets['wire_type'].cget('state')),'disabled')
        self.assertIn('保留旧版矩形束',self.app._winding_detail_note.get())
        self.app._convert_winding_bundle();self.root.update()
        entry=self.app._winding_config()['winding_config']['overrides']['P']
        self.assertEqual(entry['strand_columns'],0)
        self.assertEqual(entry['wire_type'],'auto')
        self.assertEqual(self.app._winding_assessment['windings'][0]['wire_type'],'litz')

    def test_invalid_bundle_divisor_is_explained_not_silently_rounded(self):
        self.configured()
        self.app._winding_override_vars('P')['parallel_bundles'].set('3')
        self.app._refresh_winding()
        self.assertIsNone(self.app._winding_assessment)
        self.assertIn('整除',self.app.winding_summary.get())

    def test_nonfinite_and_blank_bundle_count_do_not_crash_tk_callback(self):
        self.configured()
        for value in ('inf','nan',''):
            with self.subTest(value=value):
                self.app._winding_override_vars('P')['parallel_bundles'].set(value)
                self.app._refresh_winding();self.root.update()
                self.assertIsNone(self.app._winding_assessment)
                self.assertIn('未生成有效评估',self.app.winding_summary.get())
                self.assertEqual(self.errors,[])

    def test_narrow_view_reflows_details_and_remains_scrollable(self):
        # Headless Windows sessions can cap a top-level window below the two-column breakpoint.
        self.root.maxsize(1200,900)
        self.configured()
        self.root.geometry('520x700');self.root.update()
        self.assertEqual(self.root.winfo_width(),520)
        self.assertEqual(self.app._winding_input_columns,1)
        frame=self.app._winding_details_frame
        for widget in self.app._winding_detail_widgets.values():
            self.assertLessEqual(widget.winfo_x()+widget.winfo_width(),frame.winfo_width())
        self.assertLess(self.app._winding_view.canvas.yview()[1],1)
        self.root.geometry('970x700');self.root.update()
        self.assertEqual(self.root.winfo_width(),970)
        self.assertEqual(self.app._winding_input_columns,2)

    def test_mm_to_si_roundtrip_keeps_per_winding_overrides_and_order(self):
        self.configured()
        values=self.app._winding_override_vars('P')
        values['outer_diameter'].set('.15');values['strand_columns'].set('8')
        self.app._winding_selected.set('OUT1');self.app._move_winding(-1)
        cfg=self.app._winding_config()
        self.assertAlmostEqual(cfg['winding_config']['window_width'],.012)
        self.app._load_winding_config({});self.app._load_winding_config(cfg)
        self.assertEqual(self.app._winding_config(),cfg)
        self.assertEqual(self.app._ordered_winding_rows()[0]['id'],'OUT1')

    def test_local_edit_redraws_without_any_electrical_entrypoint(self):
        self.configured()
        self.app._winding_vars['window_height'].set('1')
        deadline=time.monotonic()+.42
        while time.monotonic()<deadline:
            self.root.update();time.sleep(.005)
        self.assertIsNone(self.app._winding_job)
        self.assertFalse(self.app._winding_assessment['fits'])
        self.assertIn('超出窗口',self.app.winding_summary.get())
        self.assertEqual(self.app.ax_winding.get_aspect(),1.)

    def test_invalid_override_clears_previous_result(self):
        self.configured()
        self.app._winding_override_vars('P')['outer_diameter'].set('.05')
        self.app._refresh_winding()
        self.assertIsNone(self.app._winding_assessment)
        self.assertIn('不能小于裸铜直径',self.app.winding_summary.get())

    def test_invalid_electrical_snapshot_is_explicit(self):
        self.configured();self.app._snapshot_valid=False;self.app._refresh_winding()
        self.assertIn('上一有效计算',self.app.winding_summary.get())
        self.app._mark_winding_stale();self.app._mark_winding_stale()
        self.assertEqual(self.app.winding_summary.get().count('上一有效计算'),1)

    def test_old_configuration_does_not_invent_window(self):
        self.configured();self.app._load_winding_config({});self.app._refresh_winding()
        self.assertFalse(self.app._winding_assessment['configured'])
        self.assertEqual(self.app._winding_vars['window_width'].get(),'')

    def test_manual_generation_split_and_reorder_assign_same_winding_to_layers_one_and_three(self):
        self.configured()
        self.app._generate_winding_plan();self.root.update()
        self.assertTrue(self.app._winding_plan_enabled.get())
        self.assertIsNotNone(self.app._winding_assessment)
        self.assertEqual(self.app._winding_layer_plan[0]['winding_id'],'P')
        self.app._winding_plan_tree.selection_set('0')
        self.app._split_winding_plan_layer()
        self.app._move_winding_plan_layer(1)
        self.app._refresh_winding();self.root.update()
        rows={row['id']:row for row in self.app._winding_assessment['windings']}
        self.assertEqual(rows['P']['physical_layer_indices'],[1,3])
        self.assertEqual(rows['P']['layer_turns'],[3,3])
        self.assertEqual(sum(int(row['turns']) for row in self.app._winding_layer_plan if row['winding_id']=='P'),6)
        self.assertIn('实体层 1、3',self.app.winding_summary.get())
        self.assertIn('P：已分配 6 / 6 匝，实体层 1、3',self.app._winding_plan_note.get())

    def test_manual_selected_editor_updates_turns_winding_and_layer_style(self):
        self.configured();self.app._generate_winding_plan();self.root.update()
        self.app._winding_plan_tree.selection_set('0');self.app._select_winding_plan_layer()
        self.app._winding_plan_editor_vars['winding_style'].set('密绕：靠右')
        self.app._refresh_winding()
        self.assertEqual(self.app._winding_config()['winding_config']['layer_plan'][0]['winding_style'],'dense_right')
        self.app._winding_plan_editor_vars['winding_style'].set('跟随该绕组')
        self.assertNotIn('winding_style',self.app._winding_config()['winding_config']['layer_plan'][0])
        self.app._winding_plan_editor_vars['winding_id'].set('OUT1')
        self.app._winding_plan_editor_vars['turns'].set('2')
        self.assertEqual(self.app._winding_layer_plan[0]['winding_id'],'OUT1')
        self.assertEqual(self.app._winding_layer_plan[0]['turns'],'2')
        self.app._refresh_winding()
        self.assertIsNone(self.app._winding_assessment)
        self.assertIn('未生成有效评估',self.app.winding_summary.get())

    def test_manual_config_roundtrip_and_toggle_preserves_draft_only_in_memory(self):
        self.configured();self.app._generate_winding_plan()
        cfg=self.app._winding_config()
        self.app._winding_plan_enabled.set(False)
        self.assertEqual(self.app._winding_config()['winding_config']['layer_plan'],[])
        self.assertEqual(len(self.app._winding_layer_plan),len(cfg['winding_config']['layer_plan']))
        self.app._winding_plan_enabled.set(True)
        self.assertEqual(self.app._winding_config(),cfg)
        self.app._load_winding_config({});self.app._load_winding_config(cfg);self.app._refresh_winding()
        self.assertEqual(self.app._winding_config(),cfg)
        self.assertTrue(self.app._winding_assessment['interleaved'])

    def test_enabled_empty_manual_plan_is_not_silently_automatic(self):
        self.configured();self.app._winding_plan_enabled.set(True)
        self.app._refresh_winding()
        self.assertIsNone(self.app._winding_assessment)
        self.assertIn('尚无层',self.app.winding_summary.get())
        self.assertEqual(self.app._winding_config(include_layer_plan=False)['winding_config']['layer_plan'],[])

    def test_manual_add_delete_and_invalid_edit_do_not_crash_callbacks(self):
        self.configured();self.app._generate_winding_plan();self.root.update()
        original=len(self.app._winding_layer_plan)
        self.app._add_winding_plan_layer()
        self.assertEqual(len(self.app._winding_layer_plan),original+1)
        self.app._delete_winding_plan_layer()
        self.assertEqual(len(self.app._winding_layer_plan),original)
        for value in ('inf','nan','','-1','2.5'):
            with self.subTest(value=value):
                self.app._winding_plan_editor_vars['turns'].set(value)
                self.app._refresh_winding();self.root.update()
                self.assertIsNone(self.app._winding_assessment)
                self.app._split_winding_plan_layer()
                self.assertEqual(self.errors,[])
        self.app._generate_winding_plan()
        self.assertIsNotNone(self.app._winding_assessment)

    def test_manual_plan_narrow_window_keeps_controls_within_view(self):
        self.configured();self.app._generate_winding_plan()
        self.root.geometry('520x700');self.root.update()
        frame=self.app._winding_plan_body
        for widget in self.app._winding_plan_editor_widgets.values():
            self.assertLessEqual(widget.winfo_x()+widget.winfo_width(),widget.master.winfo_width())
        self.assertLess(self.app._winding_view.canvas.yview()[1],1)
        self.assertGreater(frame.winfo_reqheight(),100)
        tree=self.app._winding_plan_tree
        self.assertLess(tree.xview()[1],1)
        tree.xview_moveto(1)
        self.assertAlmostEqual(tree.xview()[1],1)

    def test_interleaved_insulation_readout_distinguishes_each_actual_boundary(self):
        self.app._winding_source=[
            dict(id=key,turns=turns,strands=1,bare_diameter=.2e-3)
            for key,turns in [('P',60),('OUT1',30),('OUT2',7)]]
        plan=[dict(winding_id=key,turns=turns,section_id=sid)
              for key,turns,sid in [('P',27,'P_A'),('OUT1',15,'P_B'),('OUT2',7,'P_C'),
                                    ('OUT1',15,'P_D'),('P',27,'OUT1_A'),('P',6,'P_tail')]]
        self.app._load_winding_config(dict(winding_config=dict(window_width=.0188,window_height=.0052,
            layer_insulation=.0003,interwinding_insulation=.00002,layer_plan=plan)))
        self.app._refresh_winding()
        saved=self.app._winding_config()
        before=self.app._winding_assessment
        self.assertIsNotNone(before)
        tree=self.app._winding_plan_tree
        self.assertEqual([tree.set(str(i),'insulation_kind') for i in range(6)],
            ['首层']+['不同绕组相邻层']*4+['同绕组相邻层'])
        self.assertEqual([float(tree.set(str(i),'insulation_mm')) for i in range(6)],
            [0,.02,.02,.02,.02,.3])
        self.assertIn('同绕组界面 1 处',self.app._winding_insulation_note.get())
        self.assertIn('不同绕组界面 4 处',self.app._winding_insulation_note.get())
        self.app._winding_vars['layer_insulation'].set('.4')
        self.app._refresh_winding()
        after=self.app._winding_assessment
        for i,(old,new) in enumerate(zip(before['physical_layers'],after['physical_layers'])):
            self.assertAlmostEqual(new['y']-old['y'],.0001 if i==5 else 0)
        self.assertAlmostEqual(after['required_height']-before['required_height'],.0001)
        self.assertEqual(tree.set('5','insulation_mm'),'0.4')
        self.app._winding_vars['interwinding_insulation'].set('.04')
        self.app._refresh_winding()
        for i,(old,new) in enumerate(zip(after['physical_layers'],self.app._winding_assessment['physical_layers'])):
            self.assertAlmostEqual(new['y']-old['y'],min(i,4)*.00002)
        self.assertEqual(tree.set('4','insulation_mm'),'0.04')
        self.app._load_winding_config(saved)
        self.app._refresh_winding()
        self.assertEqual(self.app._winding_config(),saved)
        self.app._winding_plan_editor_vars['turns'].set('invalid')
        self.app._refresh_winding()
        self.assertEqual(tree.set('5','insulation_kind'),'待评估')


class ApiCompatibilityChecks(unittest.TestCase):
    def test_winding_config_accepts_si_and_rejects_unknown_geometry(self):
        from design_api import load_spec
        cfg=dict(window_width=.012,window_height=.008)
        self.assertEqual(load_spec(dict(winding_config=cfg))['winding_config'],validate_winding_config(cfg))
        with self.assertRaises(ValueError):load_spec(dict(winding_config=dict(width=.012)))


if __name__=='__main__':unittest.main(verbosity=2)
