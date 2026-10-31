"""Regression tests for saved edits, DPI-independent fonts and retained drawing."""
import ctypes
import json
import os
from pathlib import Path
import sys
import tempfile
import time
import unittest
from unittest.mock import patch
from types import SimpleNamespace
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))


class EditingChecks(unittest.TestCase):
    @classmethod
    def setUpClass(cls):ctypes.windll.shcore.SetProcessDpiAwareness(1)
    def test_clear_save_and_incremental_drag(self):
        import tkinter as tk
        import system_workspace as model
        from system_workspace_ui import SystemWorkspace
        ctypes.windll.shcore.SetProcessDpiAwareness(1)
        with tempfile.TemporaryDirectory() as tmp,patch.dict(os.environ,LOCALAPPDATA=tmp):
            root=tk.Tk();errors=[];root.report_callback_exception=lambda *e:errors.append(str(e[1]))
            ui=SystemWorkspace(root,recovery=True)
            try:
                ui.initialize();ui.load_example();ui.selected=('junction','OR-01');ui.render();root.update()
                ui._inspector_vars[0].set('评审备用母线');ui._inspector_vars[1].set('65')
                self.assertTrue(ui._edit_dirty);self.assertIn('未保存',ui.edit_state.get())
                self.assertTrue(ui.inspector_save.winfo_ismapped())
                ui.inspector_save.invoke();root.update()
                self.assertFalse(ui._edit_dirty)
                saved=model.load_project(model.recovery_path());self.assertEqual(saved['junctions'][0]['capacity'],65.)
                self.assertEqual(saved['junctions'][0]['name'],'评审备用母线')
                p=ui.project['layout']['nodes']['load:LOAD-01'];before=dict(p)
                ui.drag=dict(key='load:LOAD-01',kind='node',original=before,x=before['x'],y=before['y'],moved=False)
                ids=ui.canvas.find_all();electrical=model.checks(ui.project)
                timings=[]
                with patch.object(model,'checks',side_effect=AssertionError('drag must not analyze')),patch.object(model,'save_project',side_effect=AssertionError('drag must not write')):
                    for i in range(50):
                        begin=time.perf_counter();p.update(x=before['x']+i,y=before['y']+i)
                        ui._drag_dirty=True;ui.flush_draw();timings.append(time.perf_counter()-begin)
                    self.assertEqual(ui.canvas.find_all(),ids,'retained objects must survive every frame')
                self.assertEqual(model.checks(ui.project),electrical)
                full=[]
                for i in range(10):
                    begin=time.perf_counter();ui.draw();full.append(time.perf_counter()-begin)
                evidence={'nodes':len(ui.nodes),'incremental_mean_ms':sum(timings)/len(timings)*1000,'full_redraw_mean_ms':sum(full)/len(full)*1000,'retained_objects':len(ids)}
                out=ROOT/'artifacts/qa/canvas_edit_20261031';out.mkdir(parents=True,exist_ok=True)
                (out/'drag-timing.json').write_text(json.dumps(evidence,indent=2),encoding='utf-8')
                ui.drag=None;ui.choose_font(18);self.assertEqual(__import__('ui_preferences').font_size(),18)
                caption=next(w for w in ui.inspector.winfo_children() if isinstance(w,tk.Label))
                self.assertEqual(int(root.tk.splitlist(caption.cget('font'))[1]),-17)
                ui.choose_font(18)
                self.assertEqual(int(root.tk.splitlist(caption.cget('font'))[1]),-17,'applying preferences twice must not rescale them twice')
                for widget in ui.root.winfo_children():
                    if 'font' in widget.keys() and str(widget.cget('font')):
                        self.assertLess(int(root.tk.splitlist(widget.cget('font'))[1]),0)
                ui.choose_font(14);self.assertFalse(errors,errors)
            finally:
                if ui._draw_job is not None:root.after_cancel(ui._draw_job)
                root.destroy()

    def test_calculator_fonts_do_not_grow_with_dpi_or_window(self):
        import tkinter as tk
        from tkinter import ttk,font
        import main
        from ui_preferences import font_size
        with tempfile.TemporaryDirectory() as tmp,patch.dict(os.environ,LOCALAPPDATA=tmp):
            root=tk.Tk();ui=main.PowerSupplyAnalyzer(root,on_return=lambda app:True)
            try:
                original=ui._config_dict()
                root.update()
                for size in (14,18,20,28,40,12):
                    ui._choose_font_size(size);root.update();ui._resize_left();root.update()
                    label,entry,*_=ui._param_widgets['V_in_min']
                    self.assertLess(int(root.tk.splitlist(ttk.Style(root).lookup('Param.TLabel','font'))[1]),0)
                    self.assertLessEqual(label.winfo_x()+label.winfo_width(),entry.winfo_x())
                    self.assertLessEqual(label.winfo_reqwidth(),label.winfo_width()+2)
                    root.geometry('1800x1050');root.update()
                    self.assertAlmostEqual(ui._font_k,size/13)
                    self.assertEqual(font_size(),size)
                self.assertEqual(ui._config_dict(),original)
            finally:ui.on_close()

    def test_folded_inputs_return_to_top_and_power_chart_uses_tall_viewport(self):
        import tkinter as tk
        import main
        from power_stage import DEFAULT_PARAMS
        from loss_model import compute_design
        with tempfile.TemporaryDirectory() as tmp,patch.dict(os.environ,LOCALAPPDATA=tmp):
            root=tk.Tk();root.attributes('-alpha',0);ui=main.PowerSupplyAnalyzer(root,on_return=lambda _:True)
            try:
                root.geometry('1800x1200');root.update()
                ui.left_canvas.yview_moveto(1);root.update()
                ui._folded_sections.update(ui._param_sections.values());ui._filter_params()
                settled=tk.BooleanVar();root.after(70,lambda:settled.set(True));root.wait_variable(settled)
                self.assertLess(ui.left_inner.winfo_reqheight(),ui.left_canvas.winfo_height())
                self.assertEqual(ui.left_canvas.yview(),(0.,1.))
                self.assertAlmostEqual(ui.left_canvas.canvasy(0),0,delta=1)
                self.assertAlmostEqual(ui.left_inner.winfo_rooty(),ui.left_canvas.winfo_rooty(),delta=1)
                p=dict(DEFAULT_PARAMS,topology='BUCK',V_in=32.,V_out=24.,P_out=40.)
                r=compute_design(p);op=r['op'];wf=r['wf']
                ui.nb.select(ui.tab_power);root.update();ui._update_power(op,wf,r,p)
                for _ in range(6):root.update()
                view=ui._result_scrolls['power']
                self.assertGreaterEqual(view.content.winfo_reqheight(),view.canvas.winfo_height()-4)
                self.assertGreater(ui.canvas_power.get_tk_widget().winfo_height(),660)
                root.geometry('3440x1780')
                for size in (20,32,40):
                    ui._choose_font_size(size);root.update();ui._update_power(op,wf,r,p)
                    for _ in range(3):root.update()
                    ui.canvas_power.draw();renderer=ui.canvas_power.get_renderer()
                    for ax in ui.ax_power.ravel():self.assertGreater(ax.get_window_extent(renderer).height,120)
                    for ax in ui.ax_power.ravel()[-2:]:
                        labels=[t.get_window_extent(renderer) for t in ax.get_xticklabels() if t.get_visible()]
                        for left,right in zip(labels,labels[1:]):self.assertLessEqual(left.x1,right.x0+1)
            finally:ui.on_close()

    def test_flux_display_preserves_dc_bias_and_actual_bipolar_swing(self):
        import numpy as np
        from matplotlib.figure import Figure
        from magnetic_plot import show_flux_range
        for values in ([240.,265.,275.],[-42.,-12.,36.],[350.,360.],[0.,0.],[-.5,-.5]):
            ax=Figure().subplots();ax.plot(values);show_flux_range(ax,[np.array(values)],300.)
            low,high=ax.get_ylim()
            self.assertTrue(np.isfinite([low,high]).all());self.assertLess(low,min(values));self.assertGreater(high,max(values))
            self.assertLess(high-low,160)
            self.assertTrue(any('Bsat' in t.get_text() for t in ax.texts))
            self.assertEqual(any('超出饱和' in t.get_text() for t in ax.texts),max(map(abs,values))>300)


if __name__=='__main__':unittest.main(verbosity=2)
