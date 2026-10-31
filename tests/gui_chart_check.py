"""Render actual GUI charts for review, including config round-trip checks.

python tests/gui_chart_check.py --config path.json --out _tmp_chart_qa
No desktop screenshot or input automation: figures render directly to PNG.
"""
import argparse
import json
import sys
from pathlib import Path
import tkinter as tk

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import main


def render(config, out):
    root = tk.Tk()
    root.withdraw()
    app = main.PowerSupplyAnalyzer(root)
    with open(config, encoding='utf-8') as f:
        cfg = json.load(f)
    app._apply_config(cfg)
    app._expand_params()  # default layout now folds all but demand/power groups
    assert main.CONTROLLER_CHOICES == ('auto','type2','type3')
    for key in ('KP','fz1','fz2','fp1','fp2'):
        assert app._param_widgets[key][1].grid_info(), 'original input field hidden: '+key
    assert app.update_all(), app.status_var.get()
    if 'fc_target' in cfg:
        fc = cfg['fc_target']
        assert abs(app.get_param('fc_target')-fc['v']*app.units[fc['u']])<1e-6
    L = app._last
    app._update_topology(L['op'], L['p'])
    app._update_power(L['op'], L['wf'], L['res'], L['p'])
    app._update_stress(L['op'],L['res'])
    app._update_mag(L['op'],L['p'],L['res'],L['wf'])
    app._update_eff(L['op'],L['p'],L['res'])
    app._update_cap(L['op'],L['p'],L['res'])
    app._update_rcd(L['op'],L['p'])
    app._update_loop(L['p'])
    out = Path(out)
    out.mkdir(parents=True,exist_ok=True)
    for name, fig, size in [
        ('topology',app.fig_topology,(11.5,4.8)),
        ('power',app.fig_power,(11.5,6.6)),
        ('stress',app.fig_stress,(7,2.8)),
        ('magnetics',app.fig_mag,(5,5.5)),
        ('efficiency',app.fig_loss,(7,3.8)),
        ('capacitors',app.fig_cap,(7,6.0)),
        ('clamp',app.fig_rcd,(8,4)),
    ]:
        fig.set_size_inches(*size,forward=False)
        fig.canvas.draw()
        if name == 'capacitors':
            # Verify the rendered harmonic labels themselves, not just the
            # chosen tick indices: no adjacent text bounding boxes overlap.
            renderer = fig.canvas.get_renderer()
            for ax in app.ax_cap_band:
                boxes = [tick.get_window_extent(renderer) for tick in ax.get_xticklabels()]
                assert all(a.x1+2 < b.x0 for a,b in zip(boxes,boxes[1:])), 'harmonic tick collision'
        fig.savefig(out/(name+'.png'),dpi=140)
    topo = app._topo_key()
    print(json.dumps(dict(topology=topo,D=L['op']['D'],eta=L['res']['eta'],
                         fc_target=app.get_param('fc_target'),output=str(out)),ensure_ascii=False))
    saved = app._config_dict()
    app._apply_config(saved)
    assert app._topo_key() == topo
    assert app.update_all()
    for i in range(len(app.nb.tabs())):
        app.nb.select(i)
        app._refresh_visible_tab()
    # Restored independent legacy network flag and original calculation route.
    app.comp_type.set(app.COMP_TOPOS[0][1])
    app.comp_dir.set('fwd')
    app._on_comp_dir_change()
    app.comp_type2.set(True)
    app._run_comp_calc()
    assert 'KP' in app.comp_result.get()
    assert '错误' not in app.comp_result.get(), app.comp_result.get()
    # Single-cap banks should use two rows, not waste a blank third row.
    app.params['cin2_enable'].set(False)
    app.params['cout2_enable'].set(False)
    assert app.update_all()
    app._update_cap(app._last['op'],app._last['p'],app._last['res'])
    assert len(app.fig_cap.axes) == 3
    app._closing = True
    for job in (app.update_timer,app._font_timer,app._initial_update_job,app._control_warmup_job):
        if job is not None:
            root.after_cancel(job)
    root.destroy()


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--config',default='examples/40W_ACF_FORWARD.json')
    parser.add_argument('--out',default='_tmp_chart_qa')
    args = parser.parse_args()
    render(args.config,args.out)
