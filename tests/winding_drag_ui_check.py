"""Real Tk canvas callbacks: drag, keyboard, undo, save/load without electrical work."""
import copy,sys,time,unittest
from pathlib import Path
from unittest.mock import patch
import tkinter as tk
ROOT=Path(__file__).resolve().parents[1];sys.path[:0]=[str(ROOT),str(ROOT/'tests')]
from winding_ui_check import Host
from matplotlib.backend_bases import MouseEvent,KeyEvent


class WindingDragUI(unittest.TestCase):
    def test_pointer_keyboard_undo_and_roundtrip_are_geometry_only(self):
        root=tk.Tk();root.withdraw();root.maxsize(2400,1800);root.geometry('1000x850')
        errors=[];root.report_callback_exception=lambda *args:errors.append(args)
        app=Host(root)
        try:
            source=dict(mag=dict(transformer=dict(ok=True,Np=6,Ns=2,n_strand_p=1,n_strand_s=1,
                parallel_wires_p=2,parallel_wires_s=1,d_wire_p=.4e-3,d_wire_s=.4e-3)))
            app._update_winding({}, {}, source)
            app._winding_vars['window_width'].set('10');app._winding_vars['window_height'].set('4')
            app._refresh_winding();root.deiconify();root.update()
            app._winding_view.canvas.yview_moveto(1.);root.update();app.canvas_winding.draw()
            scene=app._winding_assessment
            point=next(s for s in scene['cross_sections'] if s['winding_id']=='P' and s['turn']==1 and s['bundle']==2)
            x,y=(point['x']+point['width']/2)*1e3,(point['y']+point['height']/2)*1e3
            def mouse(name,x,y,button=1):
                px,py=app.ax_winding.transData.transform((x,y))
                app.canvas_winding.callbacks.process(name,MouseEvent(name,app.canvas_winding,px,py,button=button))
            def settle():
                deadline=time.monotonic()+.25
                while time.monotonic()<deadline:root.update();time.sleep(.01)
            with patch('loss_model.compute_design',side_effect=AssertionError('electrical solve during drag')):
                mouse('button_press_event',x,y);mouse('motion_notify_event',x+.05,y)
                self.assertEqual(app._winding_positions,{})
                mouse('button_release_event',x+.05,y);settle()
                center=app._winding_config()['winding_config']['turn_positions'][point['section_id']][point['position_key']]
                self.assertAlmostEqual(center*1e3,x+.05,places=3)
                app.canvas_winding.callbacks.process('key_press_event',KeyEvent('key_press_event',app.canvas_winding,key='right'))
                settle();new=app._winding_config()['winding_config']['turn_positions'][point['section_id']][point['position_key']]
                self.assertAlmostEqual((new-center)*1e3,.01,places=6)
                cfg=copy.deepcopy(app._winding_config())
                app._uniform_winding_positions();self.assertEqual(app._winding_positions,{})
                app._undo_winding_position();self.assertEqual(app._winding_positions,cfg['winding_config']['turn_positions'])
                app._load_winding_config(cfg);app._refresh_winding()
                self.assertEqual(app._winding_config(),cfg)
                self.assertTrue(app._winding_assessment['fits'])
            self.assertEqual(errors,[])
        finally:
            app._closing=True;app._cancel_winding_redraw()
            for job in root.tk.splitlist(root.tk.call('after','info')):root.after_cancel(job)
            root.destroy()


if __name__=='__main__':unittest.main(verbosity=2)
