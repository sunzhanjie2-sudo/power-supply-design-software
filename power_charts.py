"""Shared power-page/report chart contents, independent of Tk and pyplot.

Layouts can differ for print readability, but labels, samples, units and MOS
stage reconstruction must have a single implementation.
"""
import numpy as np
from matplotlib import rc_context

from power_stage import fmt_eng
from switching_transients import switching_voltage_data, draw_switching_event

POWER_CHART_STYLE = {
    'font.sans-serif': ['Microsoft YaHei', 'SimHei', 'DejaVu Sans'],
    'axes.unicode_minus': False,
    'axes.facecolor': '#ffffff', 'axes.edgecolor': '#c9d2dc',
    'axes.labelcolor': '#22303c', 'axes.titlecolor': '#22303c',
    'axes.titleweight': 'bold', 'axes.spines.top': True, 'axes.spines.right': True,
    'xtick.color': '#5b6b7a', 'ytick.color': '#5b6b7a',
    'axes.grid': True, 'grid.color': '#e6ebf1', 'grid.linewidth': .8,
}


def power_signals(topology):
    label = ('副边二极管电流 D1' if topology in
             ('FLYBACK', 'QR-FLYBACK', 'ACF-FORWARD') else '二极管电流 D1')
    return [('i_sw', 'MOS 电流 Q1', 'A'), ('i_d', label, 'A'),
            ('vout_ripple', '输出纹波 v_rip', 'mV'), ('vout', '输出电压 v_out', 'V')]


def _draw_power_signals(axes, topology, wf):
    """Draw the first four power charts in GUI row-major order."""
    for ax, (key, label, unit) in zip(np.asarray(axes).ravel(), power_signals(topology)):
        ax.clear()
        y = np.asarray(wf[key])
        scale = 1e3 if unit == 'mV' else 1.0
        ax.plot(wf['t'] * 1e6, y * scale, lw=1.2,
                color='#b03a2e' if unit == 'mV' else
                      ('#1a7f37' if key == 'vout' else '#1558b0'))
        pk = float(np.max(np.abs(y))) if len(y) else 0.0
        rms = float(np.sqrt(np.mean(y ** 2)))
        ax.set_title(f'{label}\nrms={fmt_eng(rms*scale, unit)}  '
                     f'pk={fmt_eng(pk*scale, unit)}', fontsize=10)
        ax.set_xlabel('时间 / μs', fontsize=8)
        ax.set_ylabel(unit, fontsize=8)
        ax.tick_params(labelsize=8)
        ax.grid(True)


def _draw_power_switching(axes, op, p, res, *, real_time=False, drain_axes=None):
    """Draw the last two power charts and return their common time data."""
    data = switching_voltage_data(op, p, res['semi']['switch'])
    drains = (None, None) if drain_axes is None else drain_axes
    for ax, drain, event in zip(np.asarray(axes).ravel(), drains, ('on', 'off')):
        draw_switching_event(ax, data, event, real_time=real_time, drain_ax=drain)
    return data


def draw_power_signals(axes, topology, wf):
    """Use the same chart theme even when exporting without visiting the GUI."""
    with rc_context(POWER_CHART_STYLE):
        _draw_power_signals(axes, topology, wf)


def draw_power_switching(axes, op, p, res, *, real_time=False, drain_axes=None):
    with rc_context(POWER_CHART_STYLE):
        return _draw_power_switching(axes, op, p, res,
                                     real_time=real_time, drain_axes=drain_axes)
