"""Actual native canvas gestures, at different zoom levels, and saved layout."""
import copy
from pathlib import Path
import sys
import tempfile
import unittest
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
import system_workspace as model
from network_layout import diode_point


class CanvasChecks(unittest.TestCase):
    def test_load_or_bus_and_diode_drag_with_zoom_keep_electrical_results(self):
        import ctypes
        ctypes.windll.shcore.SetProcessDpiAwareness(1)
        import tkinter as tk
        from system_workspace_ui import SystemWorkspace
        root=tk.Tk();errors=[];root.report_callback_exception=lambda *e:errors.append(str(e[1]))
        app=None
        try:
            app=SystemWorkspace(root,recovery=False);app.initialize();app.load_example();root.update()
            original=model.checks(app.project)
            connections=copy.deepcopy(app.project['connections'])
            def drag(world,dx,dy):
                # Bring the chosen world point into view without altering it.
                app.canvas.xview_moveto(0);app.canvas.yview_moveto(0);root.update()
                region=app.canvas.cget('scrollregion').split()
                app.canvas.xview_moveto(max(0,(world['x']*app.zoom-160)/float(region[2])))
                app.canvas.yview_moveto(max(0,(world['y']*app.zoom-180)/float(region[3])))
                app.draw();root.update()
                x=round(world['x']*app.zoom-app.canvas.canvasx(0));y=round(world['y']*app.zoom-app.canvas.canvasy(0))
                app.canvas.event_generate('<ButtonPress-1>',x=x,y=y)
                app.canvas.event_generate('<B1-Motion>',x=round(x+dx*app.zoom),y=round(y+dy*app.zoom))
                root.update()
                app.canvas.event_generate('<ButtonRelease-1>',x=round(x+dx*app.zoom),y=round(y+dy*app.zoom));root.update()
            for zoom in (.75,1.35):
                app.set_zoom(zoom);root.update()
                for key in ('load:LOAD-01','junction:OR-01'):
                    before=dict(app.project['layout']['nodes'][key])
                    drag(dict(x=before['x']+120,y=before['y']+54),45,28)
                    after=app.project['layout']['nodes'][key]
                    self.assertAlmostEqual(after['x']-before['x'],45,delta=2)
                    self.assertAlmostEqual(after['y']-before['y'],28,delta=2)
                edge=next(e for e in app.project['connections'] if e['mode']=='diode')
                before=diode_point(app.project,edge)
                drag(before,40,36)
                after=app.project['layout']['diodes'][edge['id']]
                self.assertAlmostEqual(after['x']-before['x'],40,delta=2)
                self.assertAlmostEqual(after['y']-before['y'],36,delta=2)
            self.assertEqual(app.project['connections'],connections)
            self.assertEqual(model.checks(app.project),original)
            with tempfile.TemporaryDirectory() as d:
                path=Path(d)/'自由画布.json';model.save_project(app.project,path)
                self.assertEqual(model.load_project(path)['layout'],app.project['layout'])
            self.assertFalse(errors,errors)
            app.fit_canvas();root.update()
            from PIL import ImageGrab
            out=ROOT/'artifacts/qa/canvas_studio_20261031';out.mkdir(parents=True,exist_ok=True)
            ImageGrab.grab(bbox=(root.winfo_rootx(),root.winfo_rooty(),root.winfo_rootx()+root.winfo_width(),root.winfo_rooty()+root.winfo_height())).save(out/'desktop.png')
        finally:
            if app and app._draw_job is not None:root.after_cancel(app._draw_job)
            root.destroy()

    def test_layout_prunes_stale_diodes_and_rejects_invalid_coordinates(self):
        p=model.load_project(ROOT/'examples/SYSTEM_AUX_ORING.json')
        e=p['connections'][0];p['layout']['diodes']={e['id']:dict(x=385,y=210),'removed':dict(x=30,y=40)}
        result=model.normalize_project(p)
        self.assertEqual(result['layout']['diodes'],{e['id']:dict(x=385.,y=210.)})
        result['layout']['diodes'][e['id']]['x']=float('nan')
        with self.assertRaises(ValueError):model.normalize_project(result)


if __name__=='__main__':unittest.main(verbosity=2)
