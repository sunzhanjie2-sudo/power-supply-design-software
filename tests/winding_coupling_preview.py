"""Render only an owned Tk window for narrow six-output coupling-panel QA."""
from pathlib import Path
import tkinter as tk
from tkinter import ttk
from unittest.mock import patch

from parameter_panel_preview import capture, main


def run():
    output = Path(__file__).resolve().parents[1] / '_tmp_winding_coupling_qa'
    output.mkdir(exist_ok=True)
    root = tk.Tk()
    root.attributes('-alpha',0)
    with patch.object(main.PowerSupplyAnalyzer,'schedule_update',return_value=None):
        app = main.PowerSupplyAnalyzer(root)
        root.unbind('<Configure>')
        for job in root.tk.splitlist(root.tk.call('after','info')): root.after_cancel(job)
        root.geometry('1000x700')
        root.update()
        main._apply_fonts(ttk.Style(root),.7)
        app.multi_enabled.set(True)
        app.output_count.set('6')
        app.coupling_enabled.set(True)
        app.param_search.set('kij')
        app._filter_params()
        root.update()
        app._sync_parameter_scrollregion()
        app.left_canvas.yview_moveto(0.)
        root.update()
        capture(root,output/'01_pairwise_upper.png')
        app.left_canvas.yview_moveto(1.)
        root.update()
        capture(root,output/'02_pairwise_lower.png')
        final_label=app._coupling_widgets[5,6][0]
        assert final_label.winfo_viewable()
        assert final_label.winfo_rooty()+final_label.winfo_height() <= app.left_canvas.winfo_rooty()+app.left_canvas.winfo_height()
        app.param_search.set('')
        app._folded_sections=set(app._param_sections.values())
        app._filter_params()
        root.update()
        capture(root,output/'03_all_folded.png')
        assert not final_label.winfo_viewable()
        for job in root.tk.splitlist(root.tk.call('after','info')): root.after_cancel(job)
        app._closing=True
        app._work_cancel.set()
        root.destroy()
    print(f'Own-window coupling previews: {output}')


if __name__=='__main__': run()
