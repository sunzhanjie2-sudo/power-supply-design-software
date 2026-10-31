"""Per-output charts drawn from the existing nominal multi-output snapshot.

The caller enriches each ``res['outputs']`` entry with the corresponding
``res['wf']['outputs']`` as ``branch['wf']``.  These charts never recompute a
branch or allocate a shared primary MOSFET/input capacitor to each output.
No Tk or pyplot dependency: the same figures can later be used for reports.
"""
import unicodedata

import numpy as np
from matplotlib import rc_context
from matplotlib.ticker import MaxNLocator

from power_charts import POWER_CHART_STYLE
from power_stage import fmt_eng
from stress_notes import DIODE_STRESS_NOTE


OUTPUT_POWER_FIGSIZE = (11.2, 6.0)
OUTPUT_FORWARD_POWER_FIGSIZE = (11.2, 8.4)
OUTPUT_CAPACITORS_FIGSIZE = (11.2, 7.2)
OUTPUT_LOSSES_FIGSIZE = (11.2, 3.6)

_ISOLATED = ('FLYBACK', 'QR-FLYBACK', 'ACF-FORWARD')
_BLUE, _GREEN, _RED, _AMBER = '#1558b0', '#1a7f37', '#b03a2e', '#c18022'
# Bind concrete fallback names to the artists.  A generic ``sans-serif``
# otherwise resolves *after* rc_context ends when a GUI/Agg canvas draws.
_STYLE = dict(POWER_CHART_STYLE, **{'font.family': POWER_CHART_STYLE['font.sans-serif']})
_NARROW_WIDTH = 7.2


def output_chart_figsize(kind, topology='FLYBACK', width_inches=11.2):
    """Recommended card size at a known width, with readable scrollable rows.

    At 540 px / 100 dpi, a four-chart flyback card needs 1085 px in one column,
    a six-chart forward card 1585 px, capacitors 950 px and losses 420 px.
    The Tk owner must apply this height to its plot frame as well as Figure.
    Existing kind ``stress`` is an alias for the device-loss card.
    """
    if kind == 'stress':
        kind = 'loss'
    if kind not in ('power', 'cap', 'loss'):
        raise ValueError(f'未知多路图表类别：{kind}')
    width = max(float(width_inches), 3.6)
    if width < _NARROW_WIDTH:
        height = {'power': (6 if topology == 'ACF-FORWARD' else 4) * 2.5 + .85,
                  'cap': 9.5, 'loss': 4.2}[kind]
    else:
        height = {'power': OUTPUT_FORWARD_POWER_FIGSIZE[1] if topology == 'ACF-FORWARD'
                   else OUTPUT_POWER_FIGSIZE[1], 'cap': OUTPUT_CAPACITORS_FIGSIZE[1],
                  'loss': OUTPUT_LOSSES_FIGSIZE[1]}[kind]
    return width, height


def _wrap_figure_text(fig, text, fontsize):
    """Wrap by approximate glyph width, including CJK full-width characters."""
    columns = max(24, int(fig.get_figwidth() * 72 / (fontsize * .54)) - 8)
    lines = []
    for paragraph in text.split('\n'):
        line, size = '', 0
        for char in paragraph:
            width = 2 if unicodedata.east_asian_width(char) in ('W', 'F') else 1
            if size + width > columns and line:
                lines.append(line.rstrip())
                line, size = '', 0
            line += char
            size += width
        lines.append(line.rstrip())
    return '\n'.join(lines)


def _finish_figure(fig, title, footer, *, h_pad=1.5, w_pad=2., pad=1.08):
    fig._output_layout=(title,footer,h_pad,w_pad,pad)
    fig.suptitle(title, fontsize=12, fontweight='bold', y=.988, va='top')
    fig._output_footer=fig.text(.5,.012,footer,ha='center',va='bottom',fontsize=8,color='#5b6b7a')
    relayout_output_figure(fig)


def relayout_output_figure(fig,font_scale=1.):
    """Reserve header/footer and above-axis legends after GUI font changes."""
    settings=getattr(fig,'_output_layout',None)
    if not settings:return
    title,footer,h_pad,w_pad,pad=settings
    title_size,footer_size=12*font_scale,8*font_scale
    title=_wrap_figure_text(fig,title,title_size)
    footer=_wrap_figure_text(fig,footer,footer_size)
    fig._suptitle.set_text(title);fig._suptitle.set_fontsize(title_size)
    # The rect below already reserves this heading's exact wrapped height.
    fig._suptitle.set_in_layout(False)
    fig._output_footer.set_text(footer);fig._output_footer.set_fontsize(footer_size)
    for ax in fig.axes:
        legend=ax.get_legend()
        if legend:
            anchor=legend.get_bbox_to_anchor().transformed(ax.transAxes.inverted())
            if anchor.y0>=1 and font_scale>1.05:
                rows=(len(legend.get_texts())+legend._ncols-1)//legend._ncols
                # set_title() otherwise resets fontsize from the application's
                # current rcParams, overriding the already-scaled axis title.
                ax.set_title(ax.get_title(),fontsize=ax.title.get_fontsize(),
                             pad=max(ax.title.get_fontsize(),(rows*8*1.4+10)*font_scale))
    height = fig.get_figheight()
    bottom = (.12 + (footer.count('\n') + 1) * footer_size / 72 * 1.35) / height
    top = 1 - (.12 + (title.count('\n') + 1) * title_size / 72 * 1.35) / height
    # Padding is measured in rc font units. The desktop's global UI font
    # must not multiply it a second time after scaling the actual artists.
    with rc_context(dict(_STYLE,**{'font.size':10})):
        fig.tight_layout(rect=(0, bottom, 1, top), h_pad=h_pad, w_pad=w_pad, pad=pad)


def output_title(branch, *, feedback=False):
    """Use schematic output identities, not the currently selected feedback."""
    index = branch['id']
    name = str(branch.get('name', f'OUT{index}'))
    prefix = f'OUT{index}' if name == f'OUT{index}' else f'OUT{index} · {name}'
    return prefix + ('  ★ 反馈/基准路' if feedback else '')


def _check(branch, *, waveform=False):
    topology = branch['op']['topology']
    if topology not in _ISOLATED:
        raise ValueError('各路图表仅适用于隔离多路输出')
    if waveform and 'wf' not in branch:
        raise ValueError('各路图表需要对应的 branch["wf"] 波形快照')
    return topology


def _style_axis(ax, ylabel, *, xlabel='时间 / μs'):
    ax.set_xlabel(xlabel, fontsize=9)
    ax.set_ylabel(ylabel, fontsize=9)
    ax.tick_params(labelsize=9)
    ax.grid(True, alpha=.8)
    ax.set_axisbelow(True)


def _signal(ax, wf, key, title, unit, *, color=_BLUE):
    values = np.asarray(wf[key], dtype=float)
    scale = 1e3 if unit == 'mV' else 1.
    ax.plot(np.asarray(wf['t']) * 1e6, values * scale, lw=1.25, color=color)
    rms = float(np.sqrt(np.mean(values * values)))
    peak = float(np.max(np.abs(values)))
    statistic_unit = 'V' if unit == 'mV' else unit
    ax.set_title(f'{title}\nRMS={fmt_eng(rms, statistic_unit)}  '
                 f'峰值={fmt_eng(peak, statistic_unit)}', fontsize=10)
    _style_axis(ax, unit)


def draw_output_currents(ax, branch):
    """One current comparison axis, retaining distinct physical signals.

    Only exactly equal secondary/rectifier arrays share a line. Forward
    winding and rectifier currents can differ; capacitor current is not
    silently identified with either. Return every signal's actual artist.
    This helper is also used by the Word exporter.
    """
    _check(branch, waveform=True)
    index, wf = branch['id'], branch['wf']
    same = np.array_equal(wf['i_s'], wf['i_d'])
    signals = [('i_s', '副边 / 整流' if same else '副边', _BLUE, '-')]
    if not same:
        signals.append(('i_d', '整流', _AMBER, '--'))
    signals.append(('i_c', '电容组', _GREEN, '--'))
    artists = {}
    with rc_context(_STYLE):
        ax.clear()
        time = np.asarray(wf['t']) * 1e6
        for key, label, color, style in signals:
            values = np.asarray(wf[key], dtype=float)
            rms = float(np.sqrt(np.mean(values * values)))
            peak = float(np.max(np.abs(values)))
            artists[key], = ax.plot(time, values, lw=1.25, color=color, linestyle=style,
                                   label=f'{label}  RMS={fmt_eng(rms, "A")}  峰值={fmt_eng(peak, "A")}')
        if same:
            artists['i_d'] = artists['i_s']
        ax.set_title(f'输出支路电流 OUT{index}\nT1 / D_O{index} / C_O{index}',
                     fontsize=10, pad=len(signals)*10+8)
        _style_axis(ax, 'A')
        ax.legend(fontsize=7, loc='lower left', bbox_to_anchor=(0, 1.02), borderaxespad=0)
    return artists


def draw_shared_power_signals(axes, op, wf):
    """Draw only physically shared signals in the main multi-output panel.

    ``wf['i_p']`` for a flyback is the shared magnetizing-current equivalent,
    not the pulsed primary winding current (the latter equals i_sw).  ACF
    uses its actual bipolar magnetizing-current signal.
    """
    topology = op['topology']
    if topology not in _ISOLATED:
        raise ValueError('共享功率级图表仅适用于隔离拓扑')
    magnetizing = ('i_mag', '共享变压器励磁电流') if topology == 'ACF-FORWARD' else (
        'i_p', '原边磁链等效电流（非独立磁芯磁通）' if op.get('coupled_model') else '共享励磁电流（原边折算）')
    signals = [('i_sw', '共享 MOS 电流 Q1', 'A'),
               ('i_in', '共享输入电流', 'A'),
               ('v_sw', '共享 MOS 漏源电压 Q1', 'V'),
               (magnetizing[0], magnetizing[1], 'A')]
    with rc_context(_STYLE):
        for ax, (key, label, unit) in zip(np.asarray(axes).ravel(), signals):
            ax.clear()
            _signal(ax, wf, key, label, unit)


def draw_output_power(fig, branch, *, feedback=False):
    """Four flyback or six ACF charts; related currents share one axis."""
    topology = _check(branch, waveform=True)
    index, wf = branch['id'], branch['wf']
    signals = [('currents', '', 'A'),
               ('v_d', f'整流二极管反压 D_O{index}（未计寄生尖峰）', 'V'),
               ('vout_ripple', '输出低频纹波（不含 ESL 尖峰）', 'mV'),
               ('vout', '输出电压（低频重构）', 'V')]
    if topology == 'ACF-FORWARD':
        signals = [('iL', f'独立输出电感电流 L_O{index}', 'A'),
                   ('i_free', f'续流二极管电流 D_F{index}', 'A')] + signals
    with rc_context(_STYLE):
        fig.clear()
        columns = 1 if fig.get_figwidth() < _NARROW_WIDTH else 2
        grid = fig.subplots((len(signals) + columns - 1) // columns, columns, squeeze=False)
        result = {}
        for ax, (key, label, unit) in zip(grid.flat, signals):
            if key == 'currents':
                draw_output_currents(ax, branch)
            else:
                _signal(ax, wf, key, label, unit,
                        color=_RED if key == 'vout_ripple' else
                              (_GREEN if key == 'vout' else _BLUE))
            result[key] = ax
        _finish_figure(fig, output_title(branch, feedback=feedback) +
                       f"   {fmt_eng(branch['op']['V_out'], 'V')} / " +
                       fmt_eng(branch['op']['P_out'], 'W'),
                       ('逐对耦合及二极管导通解算；支路模式按能量传递区间内是否提前截止判定。'
                        '定频、恒阻负载、输出电压小纹波近似；非 SPICE 瞬态。'
                        if branch['op'].get('branch_mode') else
                        '各路使用自己的标称波形；共享 Q1 开关过程见本页顶部。'
                        '本模型不验证各路独立稳压或交叉调整率。')+'\n'+DIODE_STRESS_NOTE)
    return result


def draw_output_capacitors(fig, branch, *, feedback=False):
    """LF/ESL voltage, bank/per-cap AC RMS and all frequency-band currents.

    Only ``capacitors['output']`` is valid here.  A child input-capacitor
    spectrum is not the physical shared input bank and must not be shown.
    """
    _check(branch, waveform=True)
    index, wf = branch['id'], branch['wf']
    bank = branch['capacitors']['output']
    caps = bank['caps']
    from capacitor_banks import output_ref
    names = [output_ref(index,i+1,True) for i in range(len(caps))]
    with rc_context(_STYLE):
        fig.clear()
        narrow = fig.get_figwidth() < _NARROW_WIDTH
        if narrow:
            grid = fig.add_gridspec(3, 1, height_ratios=(1., .85, 1.15))
            ax_wave = fig.add_subplot(grid[0, 0])
            ax_rms = fig.add_subplot(grid[1, 0])
            ax_bands = fig.add_subplot(grid[2, 0])
        else:
            grid = fig.add_gridspec(2, 2, height_ratios=(1., 1.08))
            ax_wave = fig.add_subplot(grid[0, 0])
            ax_rms = fig.add_subplot(grid[0, 1])
            ax_bands = fig.add_subplot(grid[1, :])

        low = np.asarray(wf['vout_ripple'], dtype=float)
        total = low + np.asarray(wf['v_esl'], dtype=float)
        time = np.asarray(wf['t']) * 1e6
        ax_wave.plot(time, total * 1e3, lw=1., color=_BLUE, label='含 ESL 总纹波')
        ax_wave.plot(time, low * 1e3, lw=1.25, color=_RED, linestyle='--', label='低频纹波')
        ax_wave.set_title(f"电压纹波：低频 {fmt_eng(wf['ripple_pp'], 'V')}pp\n"
                          f"含 ESL {fmt_eng(wf['ripple_pp_total'], 'V')}pp", fontsize=10)
        _style_axis(ax_wave, 'mV')
        ax_wave.legend(fontsize=8, loc='upper right')

        totals = [bank['total_bank']] + [cap['total'] for cap in caps]
        rms_labels = ['电容组 AC RMS'] + [f'{name} · {fmt_eng(cap["C"], "F")}'
                                             for name, cap in zip(names, caps)]
        y = np.arange(len(totals))
        bars = ax_rms.barh(y, totals, color=['#8999ab', _BLUE, _GREEN][:len(totals)], height=.55)
        ax_rms.set_yticks(y, rms_labels)
        ax_rms.invert_yaxis()
        ax_rms.set_title('电容组 / 每颗电容纹波电流', fontsize=10)
        _style_axis(ax_rms, '', xlabel='AC RMS / A')
        ax_rms.grid(axis='y', visible=False)
        for bar, value in zip(bars, totals):
            ax_rms.text(bar.get_width(), bar.get_y() + bar.get_height()/2,
                        f'  {value:.4g} A', ha='left', va='center', fontsize=8)
        ax_rms.set_xlim(0, max(max(totals) * 1.4, 1e-9))
        ax_rms.xaxis.set_major_locator(MaxNLocator(nbins=4))

        x = np.arange(len(bank['labels']))
        width = .72 / max(len(caps), 1)
        for i, (name, cap) in enumerate(zip(names, caps)):
            ax_bands.bar(x + (i - (len(caps)-1)/2) * width, cap['bands'],
                         width, label=f'{name} · 总 RMS={cap["total"]:.4g} A',
                         color=(_BLUE, _GREEN)[i % 2])
        # All bands remain present; sparse tick labels prevent text collisions.
        if len(x) > 12:
            ticks = sorted(set([1, 5, 10, 15, len(x)-1] if narrow else
                               [0, 1, 2, 3, 5, 10, 15, len(x)-2, len(x)-1]))
            ticks = [i for i in ticks if i < len(x)]
        else:
            ticks = list(x)
        ax_bands.set_xticks(ticks, [bank['labels'][i] for i in ticks])
        ax_bands.set_title('每颗电容各频带纹波电流' +
                           ('\n' if narrow else '') + '（全部频带参与 RMS / ESR 损耗）', fontsize=10)
        _style_axis(ax_bands, '频带 RMS / A', xlabel=f"频带 / f_sw={fmt_eng(branch['op']['f_sw'], 'Hz')}")
        ax_bands.legend(fontsize=8, loc='upper right')
        ax_bands.set_xlim(-.7, max(len(x)-.3, .7))

        _finish_figure(fig, output_title(branch, feedback=feedback) + ' · 输出电容纹波',
                       f"输出电容 ESR 损耗 = {fmt_eng(branch['P_cap'], 'W')}；"
                       '并联分流含相位差，每颗 RMS 不能直接相加。共享输入电容仅在顶部显示。',
                       h_pad=2.)
    return dict(waveform=ax_wave, rms=ax_rms, bands=ax_bands)


def draw_output_losses(fig, branch, *, feedback=False):
    """Power devices physically belonging to this output (not shared Q1/Q2)."""
    topology = _check(branch)
    index = branch['id']
    devices = [(f'D_O{index} · 整流', branch['diode'])]
    if topology == 'ACF-FORWARD' and branch.get('freewheel'):
        devices.append((f'D_F{index} · 续流', branch['freewheel']))
    blocking = bool(branch.get('spec', {}).get('d_out_enable')) or branch['P_dout'] != 0
    names = [name for name, _ in devices]
    conduction = [device['P_cond'] for _, device in devices]
    recovery = [device['P_rr'] for _, device in devices]
    block = [0.] * len(devices)
    if blocking:
        names.append(f'D_B{index} · 输出防反')
        conduction.append(0.)
        recovery.append(0.)
        block.append(branch['P_dout'])
    with rc_context(_STYLE):
        fig.clear()
        ax = fig.add_subplot(111)
        y, left = np.arange(len(names)), np.zeros(len(names))
        for values, label, color in ((conduction, '导通损耗', _BLUE),
                                     (recovery, '反向恢复损耗', _RED),
                                     (block, '输出防反损耗', _AMBER)):
            ax.barh(y, values, left=left, height=.5, label=label, color=color)
            left += np.asarray(values)
        for pos, value in zip(y, left):
            ax.text(value, pos, f'  {value:.4g} W', ha='left', va='center', fontsize=9)
        ax.set_yticks(y, names)
        ax.invert_yaxis()
        ax.set_xlim(0, max(float(left.max()) * 1.22, 1e-9))
        _style_axis(ax, '', xlabel='损耗 / W')
        ax.grid(axis='y', visible=False)
        ax.legend(fontsize=8, loc='lower right', bbox_to_anchor=(1., 1.02), ncol=3)
        _finish_figure(fig, output_title(branch, feedback=feedback) + ' · 本路功率器件损耗',
                       f"整流/续流 {fmt_eng(branch['P_rectifier'], 'W')} + "
                       f"输出防反 {fmt_eng(branch['P_dout'], 'W')}；"
                       '不重复计入共享 Q1、Q2、输入防反或钳位损耗。', pad=1.6)
    return dict(losses=ax)
