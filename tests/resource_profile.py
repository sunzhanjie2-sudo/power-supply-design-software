"""Profile only this script's own invisible app process; no user windows.

Run in fresh processes before/after changes, with the same Python and geometry.
The numbers are diagnostic, not an assertion on all PCs or a system benchmark.
"""
from pathlib import Path
import argparse
import gc
import json
import sys
import time

START = time.perf_counter()
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import psutil


def run(output, scenario='default', stress_cycles=0):
    import tkinter as tk
    import main
    imported = time.perf_counter()
    process = psutil.Process()
    root = tk.Tk()
    root.attributes('-alpha', 0)
    app = None
    report = {'scenario': scenario, 'pid': process.pid,
              'python': sys.version, 'geometry': '1400x900',
              'import_seconds': imported - START}

    def pump(seconds=0.1):
        deadline = time.perf_counter() + seconds
        while time.perf_counter() < deadline:
            root.update()
            time.sleep(.005)

    def settled(timeout=45.):
        deadline = time.perf_counter() + timeout
        def control_settled():
            if getattr(app, '_control_loading', False):
                return False
            is_loop = app.nb.select() == str(app.tab_loop)
            if (is_loop and not app._last['op'].get('coupled_model')
                    and not getattr(app, '_control_error', None)):
                return getattr(app, '_loop_result', None) is not None
            return True
        while time.perf_counter() < deadline:
            root.update()
            worker = app._calculation_worker
            if (app._snapshot_valid and not worker.busy
                    and worker.results.empty() and app.update_timer is None
                    and control_settled()):
                pump(.2)
                if not worker.busy and worker.results.empty() and control_settled():
                    return
            time.sleep(.005)
        raise TimeoutError(app.status_var.get())

    def measure():
        from matplotlib.backends.backend_tkagg import FigureCanvasTkAgg
        from matplotlib.figure import Figure
        children = []
        def walk(widget):
            children.append(widget)
            for child in widget.winfo_children():
                walk(child)
        walk(root)
        info = process.memory_info()
        objects = gc.get_objects()
        images = root.tk.splitlist(root.tk.call('image', 'names'))
        tk_pixel_bytes = sum(int(root.tk.call('image', 'width', name))
                             * int(root.tk.call('image', 'height', name)) * 4
                             for name in images)
        return dict(rss_mb=round(info.rss / 2**20, 3),
                    private_mb=round(getattr(info, 'private', info.rss) / 2**20, 3),
                    cpu_seconds=sum(process.cpu_times()[:2]),
                    thread_count=process.num_threads(),
                    figures=sum(isinstance(item, Figure) for item in objects),
                    figure_canvases=sum(isinstance(item, FigureCanvasTkAgg) for item in objects),
                    widgets=len(children),
                    tk_images=len(images),
                    tk_pixel_mb=round(tk_pixel_bytes / 2**20, 3),
                    pending_after=len(root.tk.splitlist(root.tk.call('after', 'info'))))

    try:
        constructed = time.perf_counter()
        app = main.PowerSupplyAnalyzer(root)
        report['constructor_seconds'] = time.perf_counter() - constructed
        root.geometry('1400x900')
        settled()
        report['first_design_seconds'] = time.perf_counter() - START
        # Include existing normal control warm-up / lazy page setup in idle.
        pump(2.0)
        settled()
        report['initial_settled'] = measure()
        cpu_before = sum(process.cpu_times()[:2])
        idle_before = time.perf_counter()
        pump(2.5)
        duration = time.perf_counter() - idle_before
        cpu_delta = sum(process.cpu_times()[:2]) - cpu_before
        report['idle'] = dict(seconds=duration, cpu_seconds=cpu_delta,
                              one_core_percent=100 * cpu_delta / duration)
        original_config = app._config_dict()

        def apply_six():
            config = dict(original_config)
            config.update(outputs=[dict(V_out=v, P_out=w, Ns=0.)
                for v, w in zip((30., 12., 5., 3.3, 24., 15.), (20., 8., 4., 2., 4., 2.))],
                feedback_mode='SSR', feedback_output=1,
                coupling_config=dict(enabled=False, k=[], dcr=[]))
            app._apply_config(config)
            app.request_update()
            settled()

        if scenario == 'six':
            apply_six()
            report['scenario_settled'] = measure()
        visits = []
        tabs = [('power', app.tab_power), ('stress', app.tab_stress),
                ('magnetics', app.tab_mag), ('capacitors', app.tab_cap),
                ('loop', app.tab_loop), ('efficiency', app.tab_eff),
                ('topology', app.tab_topology)]
        for pass_number in (1, 2):
            for name, tab in tabs:
                before = time.perf_counter()
                app.nb.select(tab)
                root.update()
                settled()
                visits.append(dict(page=name, visit=pass_number,
                                   seconds=time.perf_counter() - before))
        report['tab_visits'] = visits
        report['after_visits'] = measure()
        before = time.perf_counter()
        for _ in range(3):
            app.update_all()
            root.update()
        report['three_republishes_seconds'] = time.perf_counter() - before
        gc.collect()
        pump(.1)
        report['after_republishes'] = measure()
        report['lifecycle_cycles'] = []
        for cycle in range(stress_cycles):
            for mode in ('six', 'default'):
                if mode == 'six':
                    apply_six()
                else:
                    app._apply_config(original_config)
                    app.request_update()
                    settled()
                for _name, tab in tabs:
                    app.nb.select(tab)
                    root.update()
                    settled()
                gc.collect()
                pump(.1)
                report['lifecycle_cycles'].append(dict(cycle=cycle+1, mode=mode,
                                                       **measure()))
        try:
            from threadpoolctl import threadpool_info
        except ImportError:
            report['native_pools'] = 'threadpoolctl not installed'
        else:
            report['native_pools'] = threadpool_info()
    finally:
        if app is not None:
            app._closing = True
            app._calculation_worker.close()
            if hasattr(app, '_cancel_winding_redraw'):
                app._cancel_winding_redraw()
        for job in root.tk.splitlist(root.tk.call('after', 'info')):
            root.after_cancel(job)
        root.destroy()
        report['total_seconds'] = time.perf_counter() - START
        output = Path(output)
        output.parent.mkdir(exist_ok=True, parents=True)
        output.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding='utf-8')
        print(json.dumps(report, ensure_ascii=False, indent=2))


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--output', required=True)
    parser.add_argument('--scenario', choices=('default', 'six'), default='default')
    parser.add_argument('--stress-cycles', type=int, default=0)
    args = parser.parse_args()
    run(args.output, args.scenario, args.stress_cycles)
