"""Visual QA of only a test-owned narrow window and its computed figures."""
from pathlib import Path
import tkinter as tk
from unittest.mock import patch

from multi_output_results_check import main, configuration
from parameter_panel_preview import capture


def run():
    output = Path(__file__).resolve().parents[1] / '_tmp_multi_results_qa'
    output.mkdir(exist_ok=True)
    root = tk.Tk()
    root.attributes('-alpha', 0)
    with patch.object(main.PowerSupplyAnalyzer, 'schedule_update', return_value=None):
        app = main.PowerSupplyAnalyzer(root)
        root.unbind('<Configure>')
        for job in root.tk.splitlist(root.tk.call('after', 'info')):
            root.after_cancel(job)
        root.geometry('1000x700')
        root.update()
        app._apply_config(configuration('ACF-FORWARD', count=2, feedback=2))
        assert app.update_all(), app.status_var.get()
        for kind in ('power', 'stress', 'cap'):
            app.nb.select(getattr(app, 'tab_'+kind))
            root.update()
            app._refresh_visible_tab()
            root.update()
            view = app._result_scrolls[kind]
            view.sync()
            view.canvas.yview_moveto(1.)
            root.update()
            capture(root, output/(kind+'_window.png'))
            app._output_result_cards[kind][2]['figure'].savefig(output/(kind+'_out2.png'), dpi=100)
        app._closing = True
        app._work_cancel.set()
        for job in root.tk.splitlist(root.tk.call('after', 'info')):
            root.after_cancel(job)
        root.destroy()
    print(f'Owned-window/figure previews: {output}')


if __name__ == '__main__':
    run()
