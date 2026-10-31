"""Inspect only a test-owned window with real viewport-lazy result charts."""
from pathlib import Path
import time
import tkinter as tk
from unittest.mock import patch

from multi_output_results_check import main, configuration
from parameter_panel_preview import capture


def run():
    output = Path(__file__).resolve().parents[1] / '_tmp_resource_qa'
    output.mkdir(exist_ok=True)
    root = tk.Tk()
    root.attributes('-alpha', 0)
    errors = []
    root.report_callback_exception = lambda *exc: errors.append(exc)
    with patch.object(main.PowerSupplyAnalyzer, 'schedule_update', return_value=None):
        app = main.PowerSupplyAnalyzer(root)
        for job in root.tk.splitlist(root.tk.call('after', 'info')):
            root.after_cancel(job)
        app._initial_update_job = None

        def wait(predicate, timeout=6.):
            deadline = time.monotonic() + timeout
            while not predicate():
                root.update()
                assert time.monotonic() < deadline, app.status_var.get()
                time.sleep(.01)
            root.update()
            assert not errors, errors

        try:
            root.geometry('1400x900')
            root.update()
            assert app.update_all(), app.status_var.get()
            wait(lambda: hasattr(app.canvas_topology, 'renderer'))
            capture(root, output/'preview_default.png')
            app._apply_config(configuration(count=6, feedback=6))
            assert app.update_all(), app.status_var.get()
            for kind in ('power', 'cap', 'stress'):
                app.nb.select(getattr(app, 'tab_'+kind))
                app._refresh_visible_tab()
                root.update()
                view = app._result_scrolls[kind]
                view.sync()
                view.canvas.yview_moveto(1.)
                wait(lambda: (app._output_result_cards[kind][6]['canvas'] is not None
                              and not app._result_card_jobs.get(kind)))
                capture(root, output/f'preview_{kind}_out6.png')
                card = app._output_result_cards[kind][6]
                card['figure'].savefig(output/f'preview_{kind}_out6_figure.png', dpi=100)
                # Returning to a page releases and rebuilds the same size.
                app.nb.select(app.tab_topology)
                root.update()
                assert all(c['canvas'] is None for c in app._output_result_cards[kind].values())
                app.nb.select(getattr(app, 'tab_'+kind))
                root.update()
                wait(lambda: app._output_result_cards[kind][6]['canvas'] is not None)
                assert len(app._output_result_cards[kind][6]['figure'].axes) > 0
            app.nb.select(app.tab_mag)
            app._refresh_visible_tab()
            app.mag_nb.select(app.tab_mag_winding)
            root.update()
            app._winding_vars['window_width'].set('30')
            app._winding_vars['window_height'].set('20')
            app._refresh_winding()
            wait(lambda: hasattr(app.canvas_winding, 'renderer'))
            capture(root, output/'preview_winding.png')
            print(f'Own-window previews: {output}')
        finally:
            app._closing = True
            app._calculation_worker.close()
            for job in root.tk.splitlist(root.tk.call('after', 'info')):
                root.after_cancel(job)
            root.destroy()


if __name__ == '__main__':
    run()
