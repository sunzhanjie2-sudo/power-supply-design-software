"""Render this test's owned Tk window for topology/inline-editor visual QA."""
import json
from pathlib import Path
import sys
import tkinter as tk
from tkinter import ttk
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import main
from parameter_panel_preview import capture
from parameter_ui_check import pending_jobs, pump


def run():
    project = Path(__file__).resolve().parents[1]
    output = project / '_tmp_topology_context_qa'
    output.mkdir(exist_ok=True)
    root = tk.Tk()
    root.attributes('-alpha', 0)
    with patch.object(main.PowerSupplyAnalyzer, 'schedule_update', return_value=None):
        app = main.PowerSupplyAnalyzer(root)
        root.unbind('<Configure>')
        for job in pending_jobs(root):
            root.after_cancel(job)
        root.geometry('1400x880')
        main._apply_fonts(ttk.Style(root), .9)
        for file, query, name in (
            ('40W_CCM_FLYBACK.json', '', '01_single_flyback'),
            ('6_OUTPUT_FLYBACK_SSR.json', 'C_out', '02_six_output_capacitors'),
            ('6_OUTPUT_FLYBACK_SSR.json', 'Ns', '03_six_secondary_windings'),
            ('40W_ACF_FORWARD.json', '', '04_forward'),
            ('MP6005_PSR_FLYBACK.json', 'MP6005', '05_psr'),
        ):
            app._apply_config(json.loads((project / 'examples' / file).read_text(encoding='utf-8')))
            app.param_search.set(query)
            app._filter_params()
            app.left_canvas.yview_moveto(0)
            assert app.update_all(), app.status_var.get()
            pump(root)
            capture(root, output / (name + '.png'))
        app._closing = True
        app._work_cancel.set()
        for job in pending_jobs(root):
            root.after_cancel(job)
        root.destroy()
    print(f'Owned-window previews: {output}')


if __name__ == '__main__':
    run()
