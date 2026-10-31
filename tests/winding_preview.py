"""Preview only the invisible Tk window created by this test process."""
from pathlib import Path
import sys
import tkinter as tk
from unittest.mock import patch
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from parameter_panel_preview import capture
import main
from config_io import read_default_config


def run():
    out=Path('_tmp_interleaved_winding_qa').resolve();out.mkdir(exist_ok=True)
    root=tk.Tk();root.attributes('-alpha',0)
    with patch.object(main.PowerSupplyAnalyzer,'schedule_update',return_value=None):
        app=main.PowerSupplyAnalyzer(root)
        try:
            root.unbind('<Configure>')
            for job in root.tk.splitlist(root.tk.call('after','info')):root.after_cancel(job)
            app._apply_config(read_default_config())
            root.geometry('1400x900');root.update()
            assert app.update_all()
            app.nb.select(app.tab_mag);app.mag_nb.select(app.tab_mag_winding)
            app._winding_vars['window_width'].set('12')
            app._winding_vars['window_height'].set('6')
            app._refresh_winding();root.update()
            capture(root,out/'winding_inputs.png')
            app._winding_view.canvas.yview_moveto(.30)
            root.update();capture(root,out/'winding_details.png')
            app._winding_view.canvas.yview_moveto(1)
            root.update();capture(root,out/'winding_cross_section.png')
            app.fig_winding.savefig(out/'winding_plot.png',dpi=140)
            root.geometry('1000x700');root.update()
            app._winding_view.canvas.yview_moveto(0)
            root.update();capture(root,out/'winding_small_inputs.png')
            app._winding_view.canvas.yview_moveto(.45)
            root.update();capture(root,out/'winding_small_details.png')
            app._winding_vars['window_height'].set('1')
            app._refresh_winding();root.update()
            app._winding_view.canvas.yview_moveto(1)
            root.update();capture(root,out/'winding_overflow_small.png')
            app._winding_vars['window_height'].set('6')
            app._generate_winding_plan();root.update()
            app._winding_plan_tree.selection_set('0')
            app._split_winding_plan_layer();app._move_winding_plan_layer(1)
            app._refresh_winding();root.update()
            assert app._winding_assessment['windings'][0]['physical_layer_indices']==[1,3]
            def scroll_to(widget):
                body=app._winding_view.content
                y=widget.winfo_rooty()-body.winfo_rooty()
                app._winding_view.canvas.yview_moveto(max(0,y-15)/body.winfo_reqheight())
                root.update()
            root.geometry('1400x900');root.update()
            scroll_to(app._winding_plan_frame)
            capture(root,out/'interleaved_editor.png')
            app._winding_view.canvas.yview_moveto(1);root.update()
            capture(root,out/'interleaved_cross_section.png')
            app.fig_winding.savefig(out/'interleaved_plot.png',dpi=150)
            root.geometry('1000x700');root.update()
            scroll_to(app._winding_plan_frame)
            capture(root,out/'interleaved_small_editor.png')
            app._winding_view.canvas.yview_moveto(1);root.update()
            capture(root,out/'interleaved_small_plot.png')
        finally:
            app._closing=True;app._calculation_worker.close()
            app._cancel_winding_redraw()
            for job in root.tk.splitlist(root.tk.call('after','info')):root.after_cancel(job)
            root.destroy()
    print(out)


if __name__=='__main__':run()
