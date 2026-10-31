"""Shared multi-output response plots for the desktop and Word report."""
import numpy as np


def draw_multi_output_response(axes, loop, load_output=1):
    """All rails share one feedback denominator; no per-rail PM labels."""
    data = loop['multi_output']
    axes = np.asarray(axes).reshape(2, 2)
    for ax in axes.flat:
        ax.clear(); ax.set_axis_on()
    f = loop['f']
    for index, rail in enumerate(data['outputs']):
        label = f'OUT{rail["id"]}' + (' ★ 反馈' if rail['id'] == data['feedback_output'] else '')
        gain = data['reference'][index]
        axes[0, 0].semilogx(f, 20*np.log10(np.maximum(np.abs(gain), 1e-300)), label=label)
        axes[0, 1].semilogx(f, np.degrees(np.unwrap(np.angle(gain))), label=label)
    axes[0, 0].set(title='主参考到各路电压 · 相对变化率', ylabel='dB（% / %）')
    axes[0, 1].set(title='主参考跟踪相位', ylabel='deg')
    load = data['load']
    if load is not None:
        selected = min(max(int(load_output)-1, 0), len(data['outputs'])-1)
        for index, rail in enumerate(data['outputs']):
            label = f'OUT{rail["id"]}'
            gain = load[index, selected]
            axes[1, 0].loglog(f, np.maximum(np.abs(gain), 1e-14), label=label)
            axes[1, 1].semilogx(f, np.degrees(np.unwrap(np.angle(gain))), label=label)
        axes[1, 0].set(title=f'OUT{selected+1} 负载扰动 → 各路电压', ylabel='|ΔV / ΔI| / Ω')
        axes[1, 1].set(title=f'OUT{selected+1} 负载响应相位', ylabel='deg')
    else:
        for ax in axes[1]:
            ax.text(.5, .5, '理想匝比近似未建立独立负载动态\n不绘制虚假的交叉调整率曲线',
                    ha='center', va='center', transform=ax.transAxes, fontsize=10)
            ax.set_axis_off()
    for ax in axes.flat:
        if ax.axison:
            ax.set_xlabel('频率 / Hz', fontsize=9)
            ax.title.set_fontsize(10)
            ax.yaxis.label.set_fontsize(9)
            ax.tick_params(labelsize=8)
            ax.grid(True, which='both', alpha=.2)
            ax.legend(fontsize=8)
    return axes
