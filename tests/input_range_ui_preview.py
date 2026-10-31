"""Capture only this process's transparent Tk window for range-layout QA."""
from pathlib import Path
import sys
import tkinter as tk
from tkinter import ttk
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import main
from parameter_panel_preview import capture
from engineering_ui import Tooltip


def run():
    folder = Path('_tmp_input_range_qa/ui').resolve(); folder.mkdir(parents=True, exist_ok=True)
    root = tk.Tk(); root.attributes('-alpha', 0)
    with patch.object(main.PowerSupplyAnalyzer, 'schedule_update', return_value=None):
        app = main.PowerSupplyAnalyzer(root)
        try:
            root.unbind('<Configure>')
            for job in root.tk.splitlist(root.tk.call('after', 'info')):
                root.after_cancel(job)
            app.set_param('V_in_min', 24); app.set_param('V_in_max', 40)
            root.geometry('1400x900'); main._apply_fonts(ttk.Style(root), .9)
            app._filter_params(); assert app.update_all(), app.status_var.get(); root.update()
            capture(root, folder/'vinmin_wide.png')
            app.params['input_voltage_case'].set('max')
            root.geometry('1000x700'); main._apply_fonts(ttk.Style(root), .7)
            assert app.update_all(), app.status_var.get(); root.update()
            capture(root, folder/'vinmax_narrow.png')
            app.nb.select(app.tab_power); app._refresh_visible_tab(); root.update()
            capture(root, folder/'vinmax_power.png')
        finally:
            app._closing = True; app._calculation_worker.close(); Tooltip.hide_all(root)
            for job in root.tk.splitlist(root.tk.call('after', 'info')):
                root.after_cancel(job)
            root.destroy()
    print(folder)


if __name__ == '__main__':
    run()
