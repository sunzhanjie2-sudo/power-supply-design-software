"""Switching Power Supply Design & Loop Analyzer (Tkinter GUI) — V0.0.0

A clean, step-by-step design flow for Buck / Boost / Buck-Boost / Flyback /
QR-Flyback (quasi-resonant, BCM) / Active-Clamp Forward converters. The flow
follows the design procedure of the reference book in 参考资料/:

    R. W. Erickson, D. Maksimović, "Fundamentals of Power Electronics",
    3rd ed.

  ① Topology schematic        component designators and parameter mapping
  ② Power stage & waveforms   (book ch. 2/3)  currents, ripple, MOS switching
  ③ Device stress             (book ch. 4)    MOSFET/diode V·I stress + losses
  ④ Magnetics                 (book ch. 10-12) core, turns, gap, saturation,
                                                thermal (ΔT)
  ⑤ Loop design               (book ch. 8/9)  Bode, PM/GM, K-factor auto-tune
  ⑥ Efficiency & optimisation (book ch. 3)    loss breakdown, η-load, sweep

Every design must be checked against (all are surfaced in the GUI):

  - capacitor ripple current: separate capacitor page; RMS + ESR loss and a
    capacitor ripple-current rating recommendation are reported;
  - semiconductor stress:      i_sw(t) / i_d(t) are always plotted; stress
    tables + loss breakdown + derating advice;
  - magnetics saturation:      B(t) vs. the saturation flux Bsat, margin in %;
  - magnetics thermal:         transformer ΔT = P_loss * Ri-a (user input);
                              standalone inductors retain convection;
  - control loop:              phase/gain margin, crossover, RHP-zero and DCM
    model caveats.
  - QR flyback (BCM):          variable f_sw = 1/(T_on+T_demag+T_ring) vs the
    f_max limit; valley delay T_ring = pi*sqrt(Lm*Coss).

All computation lives in the sibling modules; this file only glues them to
the GUI (no business logic).
"""

if __name__ == '__main__':
    from desktop_entry import main as launch_workspace
    launch_workspace()
    raise SystemExit

import sys
import os
from runtime_resources import configure_numeric_threads

# Configure this process before Matplotlib/NumPy load native numeric pools.
# Explicit user overrides are retained; no machine-wide settings are changed.
configure_numeric_threads()

# keep compatibility with the packaged exe's environment
_user_site = os.path.join(os.environ.get('APPDATA', ''), 'Python', 'Python311',
                          'site-packages')
if not getattr(sys, 'frozen', False) and os.path.isdir(_user_site):
    sys.path.insert(0, _user_site)

import matplotlib
matplotlib.use('TkAgg')
# CJK font support for chart titles (falls back gracefully on non-Windows)
matplotlib.rcParams['font.sans-serif'] = ['Microsoft YaHei', 'SimHei',
                                          'DejaVu Sans']
matplotlib.rcParams['axes.unicode_minus'] = False

import copy
import json
import queue
import tkinter as tk
from tkinter import ttk, filedialog, messagebox
import tkinter.font as tkfont
import numpy as np
class _LazyControl:
    """Import the (heavy) control package on first attribute access instead
    of at module import time — start-up does not need it until the loop tab
    is used."""
    def __getattr__(self, name):
        import control
        globals()['ct'] = control          # replace the proxy outright
        return getattr(control, name)


ct = _LazyControl()

from resource_canvas import EfficientFigureCanvasTkAgg as FigureCanvasTkAgg
from matplotlib.figure import Figure
from matplotlib.image import imread

from manual import show_manual, MANUAL_VERSION
from engineering_ui import EngineeringUI, Tooltip
from parameter_panel import ParameterPanelUI
from multi_output_results import MultiOutputResultsUI
from calculation_scheduler import (LatestCalculationWorker, calculate_efficiency_curve,
                                   calculate_report_efficiency_curve, calculate_optimization,
                                   parameter_signature, CalculationCancelled)
from winding_ui import WindingUI

# ----------------------------------------------------------------------------
# Visual theme: modern flat palette + Segoe UI / Microsoft YaHei typography
# ----------------------------------------------------------------------------
BG = '#eef1f5'          # window background
PANEL = '#f5f7fa'       # section panels
CARD = '#ffffff'        # cards / trees / entries
FG = '#22303c'          # primary text
MUTED = '#5b6b7a'       # secondary text
ACCENT = '#1558b0'      # brand blue
ACCENT_DK = '#0d47a1'
ACCENT_LT = '#2d7dd2'
BORDER = '#c9d2dc'
BTN = '#e4e9f0'
BTN_ACTIVE = '#d3dce6'
SEL = '#dbe7f6'         # selection
FAM = 'Microsoft YaHei UI'
OK = '#1a7f37'
WARN = '#b54708'
BAD = '#b03a2e'

# Shown wherever η is reported: the loss model counts only the major
# power-stage losses, so the computed efficiency is optimistic and is NOT the
# efficiency of the built hardware.
ETA_NOTE = ('⚠ 计算效率说明: η 仅计入 MOSFET(导通/开关/Coss/栅极)、二极管/SR(导通/反向恢复)、'
            '磁件(磁芯+铜损)、输入/输出/钳位电容 ESR、采样电阻、RCD 钳位电阻、输入/输出防反二极管(如启用)损耗; '
            '未计温度效应(热态 Rds_on 增大)、'
            '辅助/控制电路功耗(驱动供电/反馈/风扇)、输入整流桥、PCB/连接器铜损、EMI 滤波、'
            'RCD 以外的吸收电路、绕组邻近效应等附加损耗 —— 模型估算, 并非最终实物效率, '
            '差值需实测确定，不保证固定百分点或实测上限。运行点按预设η的等效损耗预算，不逐项叠加压降；最终η不覆盖预设。')


# reference window size the fixed UI layout was designed for; fonts scale
# with min(w/W0, h/H0) so text stays readable (no overlap) on small laptops
REF_WIN = (1600, 950)


def _draw_canvas(canvas):
    """GUI draws coalesce and wait for visibility; batch draw() stays eager."""
    request=getattr(canvas,'request_draw',None)
    if request is not None:
        request()
    else:
        canvas.draw()


def _font_scale_for(w, h):
    """Font scale factor for a window of w x h pixels (clamped 0.70~1.60)."""
    return max(0.70, min(1.60, min(w / REF_WIN[0], h / REF_WIN[1])))


def _setup_style(root, k=1.0):
    """Configure ttk 'clam' theme, fonts and colours (k = font scale)."""
    style = ttk.Style(root)
    style.theme_use('clam')
    _apply_fonts(style, k)


def _apply_fonts(style, k):
    """(Re)apply every font at scale factor k (1.0 = the 1600x950 reference
    layout).  Re-run on window resize; also scales the matplotlib chart text
    so plot titles/legends/ticks never overlap at small window sizes."""
    def F(n):
        # Negative Tk sizes mean pixels. Positive points were multiplied by
        # Windows DPI again, overflowing the fixed-width parameter columns.
        return -max(9, int(round(n * k)))

    for name in ('TkDefaultFont', 'TkTextFont', 'TkMenuFont'):
        f = tkfont.nametofont(name)
        f.configure(family=FAM, size=F(13))
    tkfont.nametofont('TkHeadingFont').configure(family=FAM, size=F(11),
                                                 weight='bold')
    tkfont.nametofont('TkFixedFont').configure(family='Consolas', size=F(13))

    style.configure('.', font=(FAM, F(13)), background=BG, foreground=FG)
    style.configure('TFrame', background=BG)
    style.configure('TLabel', background=BG, foreground=FG)
    style.configure('Param.TLabel', background=BG, foreground=FG,
                    font=(FAM, F(12)))
    style.configure('Margin.TLabel', background=BG, foreground=FG,
                    font=(FAM, F(11), 'bold'))
    style.configure('CurveMode.TRadiobutton', font=(FAM, F(12), 'bold'),
                    background=BG, foreground=ACCENT)
    style.configure('Muted.TLabel', background=BG, foreground=MUTED,
                    font=(FAM, F(12)))
    style.configure('Result.TLabel', background=BG, foreground=ACCENT,
                    font=(FAM, F(12)))
    style.configure('Ok.TLabel', background=BG, foreground=OK,
                    font=(FAM, F(10), 'bold'))
    style.configure('Warn.TLabel', background=BG, foreground=WARN,
                    font=(FAM, F(10), 'bold'))
    style.configure('Error.TLabel', background=BG, foreground=BAD,
                    font=(FAM, F(12)))

    # banner
    style.configure('Banner.TFrame', background=ACCENT)
    style.configure('Banner.TLabel', background=ACCENT, foreground='white',
                    font=(FAM, F(16), 'bold'))
    style.configure('BannerSub.TLabel', background=ACCENT,
                    foreground='#cfe0f5', font=(FAM, F(12)))
    style.configure('Banner.TButton', background='#ffffff', foreground=ACCENT_DK,
                    bordercolor='#ffffff', padding=(10, 4),
                    font=(FAM, F(10), 'bold'))
    style.map('Banner.TButton',
              background=[('active', '#dbe7f6'), ('pressed', '#c9dcf3')],
              foreground=[('active', ACCENT_DK)])

    # step guide strip
    style.configure('Guide.TFrame', background='#e3ecf7')
    style.configure('Guide.TLabel', background='#e3ecf7',
                    foreground=ACCENT_DK, font=(FAM, F(12)))

    # section frames
    style.configure('TLabelframe', background=BG, bordercolor=BORDER,
                    relief='solid', borderwidth=1)
    style.configure('TLabelframe.Label', background=BG, foreground=ACCENT,
                    font=(FAM, F(10), 'bold'))

    # buttons
    style.configure('TButton', background=BTN, foreground=FG,
                    bordercolor=BORDER, focusthickness=0,
                    padding=(12, 6), font=(FAM, F(12)))
    style.map('TButton',
              background=[('active', BTN_ACTIVE), ('pressed', '#c3cdd9')])
    style.configure('Accent.TButton', background=ACCENT, foreground='white',
                    bordercolor=ACCENT, font=(FAM, F(10), 'bold'),
                    padding=(14, 6))
    style.map('Accent.TButton',
              background=[('active', ACCENT_DK), ('pressed', ACCENT_DK)],
              foreground=[('disabled', '#9db6d6')])

    # notebook
    style.configure('TNotebook', background=BG, borderwidth=0)
    style.configure('TNotebook.Tab', background='#dde4ec', foreground=FG,
                    padding=(max(2, int(6*k)), max(4, int(8*k))), font=(FAM, F(11)))
    style.map('TNotebook.Tab',
              background=[('selected', CARD)],
              foreground=[('selected', ACCENT)],
              borderwidth=[('selected', 0)])

    # treeviews
    style.configure('Treeview', background=CARD, fieldbackground=CARD,
                    foreground=FG, rowheight=max(24,round(29*k)), font=(FAM, F(12)),
                    bordercolor=BORDER, relief='flat')
    style.configure('Treeview.Heading', background='#e6ebf2',
                    foreground=FG, font=(FAM, F(10), 'bold'), relief='flat',
                    padding=5)
    style.map('Treeview', background=[('selected', SEL)],
              foreground=[('selected', FG)])

    # scrollbars, entries, combos, checkbuttons
    style.configure('TScrollbar', troughcolor='#dde3eb',
                    background='#b6c1cf', arrowcolor=FG,
                    bordercolor='#dde3eb')
    style.configure('TEntry', fieldbackground=CARD, foreground=FG,
                    bordercolor=BORDER, insertcolor=FG, padding=4)
    style.configure('TCombobox', fieldbackground=CARD, background=CARD,
                    foreground=FG, arrowcolor=ACCENT, bordercolor=BORDER,
                    padding=3)
    style.map('TCombobox', fieldbackground=[('readonly', CARD)])
    style.configure('TCheckbutton', background=BG, foreground=FG,
                    font=(FAM, F(12)))
    style.map('TCheckbutton', background=[('active', BG)])

    # chart text follows the same scale (applies to newly drawn text)
    matplotlib.rcParams.update({
        'font.size': max(8,12*k),
        'axes.labelsize': max(8,12*k),
        'axes.titlesize': max(9,14.5*k),
        'legend.fontsize': max(8,12*k),
        'xtick.labelsize': max(8,11*k),
        'ytick.labelsize': max(8,11*k),
    })


def _polish_matplotlib():
    matplotlib.rcParams.update({
        'figure.facecolor': '#ffffff',
        'axes.facecolor': '#ffffff',
        'axes.edgecolor': BORDER,
        'axes.labelcolor': FG,
        'axes.titlecolor': FG,
        'xtick.color': MUTED,
        'ytick.color': MUTED,
        'axes.grid': True,
        'grid.color': '#e6ebf1',
        'grid.linewidth': 0.8,
        'font.size': 13,
        'axes.labelsize': 13,
        'axes.titlesize': 14.5,
        'legend.fontsize': 12,
        'xtick.labelsize': 11,
        'ytick.labelsize': 11,
        'axes.titleweight': 'bold',
    })


from power_stage import (DEFAULT_PARAMS, TOPOLOGIES, TOPO_FLYBACK,
                         fmt_eng, compute_operating_point)
from waveforms import make_waveforms
from semiconductor import device_stress
from loss_model import compute_design
from loop_tuning import kfactor_tune
import comp_design as compd
import optimizer as opt
import capripple as capr
import magnetics as mag
from plants import (BuckConverter, BoostConverter, BuckBoostConverter,
                    FlybackConverter, ActiveClampForwardConverter,
                    make_compensator, uses_dcm_peak_energy,
                    normalize_controller_type, resolve_controller_type)

APP_VERSION = 'V0.0.0 · 20261108 QR多路交叉调整率'


def _subplots(nrows=1, ncols=1, figsize=(6.4, 4.8)):
    """Create an embeddable figure without a pyplot window manager.

    ``pyplot.subplots`` creates an extra hidden Tk toplevel for every chart.
    The application embeds all figures itself, so those managers only slow
    startup and waste native window resources.
    """
    fig = Figure(figsize=figsize)
    return fig, fig.subplots(nrows, ncols)


def _loss_bars(ax, labels, values, title, colors=ACCENT):
    """Readable long categories and values even on a laptop-sized chart."""
    ax.clear()
    bars = ax.barh(np.arange(len(values)), values, color=colors, height=.62)
    ax.set_yticks(np.arange(len(values)), labels, fontsize=9)
    ax.invert_yaxis()
    ax.set_title(title, fontsize=10, pad=9)
    ax.set_xlabel('损耗 / W', fontsize=9)
    ax.tick_params(axis='x', labelsize=8)
    ax.set_xlim(0, max(max(values, default=0)*1.32, .01))
    ax.bar_label(bars, labels=[f'{v:.3f}' for v in values], padding=4, fontsize=8)
    ax.grid(False)
    ax.grid(True, axis='x', alpha=.55)
    ax.set_axisbelow(True)


def build_markdown_report(p, op, wf, res):
    """Build a portable, human-readable snapshot of the current design."""
    stress = device_stress(op)
    c_total = __import__('capacitor_banks').total(op)
    from design_checks import check_catalog, STATE_LABELS
    checks = [(c['name'],fmt_eng(c['value'],c['unit']) if c['value'] is not None else '未定义',
               STATE_LABELS[c['state']]) for c in check_catalog(p,res,res.get('loop'))]
    lines = [
        '# 开关电源设计报告', '',
        f"> 由 Switching Power Supply Design & Loop Analyzer {APP_VERSION} 导出。", '',
        '## 设计规格', '',
        '| 项目 | 数值 |', '|---|---:|',
        f"| 拓扑 | {op['topology']} |",
        f"| 控制模式 | {p['control_mode']} |",
        f"| 控制器 | {CONTROLLER_NAMES[resolve_controller_type(p.get('controller_type','auto'),p['control_mode'])]} |",
        f"| 输入电压 | {fmt_eng(op['V_in'], 'V')} |",
        f"| 输出电压 | {fmt_eng(op['V_out'], 'V')} |",
        f"| 输出功率 | {fmt_eng(p['P_out'], 'W')} |",
        f"| 开关频率 | {fmt_eng(op['f_sw'], 'Hz')} |", '',
        '## 关键结果', '',
        '| 项目 | 数值 |', '|---|---:|',
        f"| 占空比 D | {op['D']:.4f} |",
        f"| 电感纹波 ΔI | {fmt_eng(op['dI_L'], 'A')} |",
        f"| 峰值电流 | {fmt_eng(op['I_L_pk'], 'A')} |",
        f"| 输出纹波 | {fmt_eng(wf['ripple_pp'], 'V')} |",
        f"| 电容纹波电流 RMS | {fmt_eng(wf['i_c_rms'], 'A')} |",
        f"| 预设效率 | {op['eta_guess'] * 100:.2f}% |",
        f"| 最终计算效率 | {res['eta'] * 100:.2f}% |",
        f"| 预估 / 损耗反算输入功率 | {op['P_in_est']:.3f} / {res['P_in']:.3f} W |",
        f"| 总损耗 | {res['P_total']:.3f} W |", '',
        '## 设计检查', '',
        '| 检查项 | 当前值 | 结论 |', '|---|---:|---|',
    ]
    lines.extend(f'| {name} | {value} | {state} |'
                 for name, value, state in checks)
    lines += [
        '', '## 器件应力', '',
        '| 器件 | 电压最大值 | 电流 RMS | 电流峰值 |',
        '|---|---:|---:|---:|',
        (f"| MOSFET | {fmt_eng(stress['switch']['V_max'], 'V')} | "
         f"{fmt_eng(stress['switch']['I_rms'], 'A')} | "
         f"{fmt_eng(stress['switch']['I_pk'], 'A')} |"),
        (f"| 整流器件 | {fmt_eng(stress['diode']['V_max'], 'V')} | "
         f"{fmt_eng(stress['diode']['I_rms'], 'A')} | "
         f"{fmt_eng(stress['diode']['I_pk'], 'A')} |"),
        '', '## 损耗分解', '',
        '| 类别 | 损耗 |', '|---|---:|',
        f"| 半导体 | {res['P_semi']:.3f} W |",
        f"| 磁件 | {res['P_mag']:.3f} W |",
        f"| 电容 ESR | {res['P_cap']:.3f} W |",
        f"| 输入电容 ESR | {res['P_cap_in']:.3f} W |",
        f"| 采样电阻 | {res['P_sense']:.3f} W |",
        f"| RCD 钳位 | {res.get('P_rcd', 0.0):.3f} W |",
        f"| 有源钳位电容 ESR | {res.get('P_clamp', 0.0):.3f} W |",
        '', '## 使用提示', '',
        ('- 计算效率是模型估算值，不是实测上限保证；热态参数、辅助供电、PCB/连接器、EMI '
         '滤波等附加损耗仍需通过样机验证。'),
        '- 器件耐压、额定电流和电容纹波电流应保留足够降额裕量。',
        '- 环路结果应结合实测 Bode 图与负载瞬态再次确认。', '',
    ]
    if op['topology'] == 'ACF-FORWARD':
        lines += ['## 有源钳位正激', '', '| 项目 | 数值 |', '|---|---:|',
                  f"| 输出滤波电感 L | {fmt_eng(op['L'],'H')} |",
                  f"| 变压器励磁电感 Lm | {fmt_eng(op['Lm_forward'],'H')} |",
                  f"| 低侧钳位电容 | {fmt_eng(op['C_clamp'],'F')} |",
                  f"| 钳位电容稳态电压 | {op['V_clamp']:.3f} V |",
                  f"| 复位电压 | {op['V_reset']:.3f} V |",
                  f"| 励磁电流峰值 | ±{op['I_mag_pk']:.3f} A |",
                  f"| 建议最大环路 fc | {fmt_eng(op['fc_recommended_max'],'Hz')} |", '',
                  '| 辅助器件 | 最大电压 | RMS 电流 |', '|---|---:|---:|']
        for key, name in [('auxiliary','钳位 MOSFET'),('freewheel','续流二极管')]:
            s = stress[key]
            lines.append(f"| {name} | {fmt_eng(s['V_max'],'V')} | {fmt_eng(s['I_rms'],'A')} |")
        lines += ['', *['- '+w for w in op['warnings']], '',
                  '公式来源：[TI SLUA535A](https://www.ti.com/lit/an/slua535a/slua535a.pdf)、'
                  '[TI SLUP262](https://e2e.ti.com/cfs-file/__key/communityserver-discussions-components-files/234/slup262.pdf)。', '']
    return '\n'.join(lines)


def resource_path(rel):
    """Compatibility entry point; assets have one shared source/bundle map."""
    from app_resources import resource_path as locate
    return str(locate(rel))


def _calculate_input_report(request, cancelled):
    """Prepare both endpoints on the existing numerical worker, not Tk."""
    from design_engine.service import prepare_endpoint_bundle
    return prepare_endpoint_bundle(request['p'], cancelled=cancelled)


def _calculate_acceptance_endpoints(request, cancelled):
    """Reuse fixed-hardware endpoints without report-only efficiency scans."""
    from design_engine.service import prepare_endpoint_bundle
    return prepare_endpoint_bundle(request['p'], cancelled=cancelled,
                                   include_cross_regulation=False, include_efficiency=False)


# ----------------------------------------------------------------------------
# Parameter table: (key, label, unit options, section)  — bilingual labels
# ----------------------------------------------------------------------------
PARAM_SPECS = [
    # specification
    ('V_in',  'Input voltage V_in (输入电压)',          ['', 'm'], 'spec'),
    ('V_in_min', 'Minimum input voltage (输入电压下限)', ['', 'm'], 'spec'),
    ('V_in_max', 'Maximum input voltage (输入电压上限)', ['', 'm'], 'spec'),
    ('V_out', 'Output voltage V_out (端口电压，防反后)', ['', 'm'], 'spec'),
    ('P_out', 'Output power P_out, W (输出功率)',       ['', 'm'], 'spec'),
    ('eta_guess', 'Preset efficiency η (预设效率, 0~1)', [], 'spec'),
    ('f_sw',  'Switching freq f_sw, Hz (开关频率)',     ['', 'k', 'M'], 'spec'),
    # power stage
    ('L',     'L, H (反激励磁 / 正激输出滤波电感)',     ['p', 'n', 'u', 'm'], 'stage'),
    ('Rs',    'Sense resistor Rs, Ohm (采样电阻)',      ['m', ''], 'stage'),
    ('A_sense', 'Current-sense amp gain A_sense (采样放大倍数, 芯片内部)', [], 'stage'),
    ('Vm',    'Modulation ramp Vm, V (调制斜坡幅值)',   ['', 'm'], 'stage'),
    ('N',     'Transformer Np/Ns (变压器匝比)',         [], 'stage'),
    ('Lm_forward', '正激变压器励磁电感 Lm, H', ['u', 'm'], 'forward'),
    ('C_clamp', '低侧钳位电容 C_clamp, F', ['n', 'u'], 'forward'),
    ('forward_d_max', '正激最大占空比 (0~1)', [], 'forward'),
    ('forward_dead_time', '正激驱动死区时间, s', ['n', 'u'], 'forward'),
    ('Rds_aux', '钳位 MOSFET Rds(on), Ω', ['m', ''], 'forward'),
    ('Qg_aux', '钳位 MOSFET Qg, C', ['n'], 'forward'),
    ('Coss_aux', '钳位 MOSFET Coss, F', ['p', 'n'], 'forward'),
    ('ESR_clamp', '钳位电容 ESR, Ω', ['m', ''], 'forward'),
    ('Vf',    'Vf, V (旧版兼容;效率模型不叠加)', ['', 'm'], 'stage'),
    ('ripple_target', 'Output ripple target, rel. (纹波目标)', [], 'stage'),
    ('ring_margin',   'Vds ringing margin, rel. (振铃裕量)',   [], 'stage'),
    # --- output / input capacitor bank (up to 2 parallel caps per rail) ---
    ('C_out',  'Output cap 1 C, F (输出电容1)',       ['n', 'u', 'm'], 'stage'),
    ('Rc',     'Output cap 1 ESR, Ohm (输出电容1 ESR)', ['m', ''], 'stage'),
    ('ESL',    'Output cap 1 ESL, H (输出电容1 ESL)',  ['n', 'p'], 'stage'),
    ('C_out2', 'Output cap 2 C, F (输出电容2, 可选)',  ['u', 'm', 'n'], 'stage'),
    ('Rc2',    'Output cap 2 ESR, Ohm (输出电容2 ESR)', ['m', ''], 'stage'),
    ('ESL2',   'Output cap 2 ESL, H (输出电容2 ESL)',  ['n', 'p'], 'stage'),
    ('Cin1',   'Input cap 1 C, F (输入电容1)',         ['u', 'm', 'n'], 'stage'),
    ('Rcin1',  'Input cap 1 ESR, Ohm (输入电容1 ESR)', ['m', ''], 'stage'),
    ('ESLin1', 'Input cap 1 ESL, H (输入电容1 ESL)',   ['n', 'p'], 'stage'),
    ('Cin2',   'Input cap 2 C, F (输入电容2, 可选)',   ['u', 'm', 'n'], 'stage'),
    ('Rcin2',  'Input cap 2 ESR, Ohm (输入电容2 ESR)', ['m', ''], 'stage'),
    ('ESLin2', 'Input cap 2 ESL, H (输入电容2 ESL)',   ['n', 'p'], 'stage'),
    # anti-reverse (blocking) diodes, input & output rails
    ('Vf_din',  'Anti-reverse diode Vf, in (输入防反二极管压降)',   ['', 'm'], 'stage'),
    ('Rd_din',  'Anti-reverse diode Rd, in (输入防反二极管 Rd)',   ['m', ''], 'stage'),
    ('Vf_dout', 'Anti-reverse diode Vf, out (输出防反二极管压降)', ['', 'm'], 'stage'),
    ('Rd_dout', 'Anti-reverse diode Rd, out (输出防反二极管 Rd)',  ['m', ''], 'stage'),
    # devices
    ('Rds_on',   'MOSFET Rds(on), Ohm (导通电阻)',      ['m', ''], 'device'),
    ('Vf_diode', 'Diode Vf, V (二极管压降)',            ['', 'm'], 'device'),
    ('Rd_diode', 'Diode Rd, Ohm (二极管动态电阻)',      ['m', ''], 'device'),
    ('Coss',     'MOSFET Coss, F (输出电容)',           ['p', 'n'], 'device'),
    ('Qg',       'MOSFET gate charge, C (栅极电荷)',    ['n'], 'device'),
    ('Vth',      'Threshold Vgs(th), V (开启阈值电压)',    ['', 'm'], 'device'),
    ('gfs',      'Effective gfs, A/V (有效跨导；0=固定平台，>0按Vth+Id/gfs计算)', ['', 'm'], 'device'),
    ('mos_curve_vds', 'Output curve slice Vds, V (输出曲线族读取电压，不是Vin)', ['', 'm'], 'device'),
    ('Vgp_on',   'Miller plateau Vgp(on), V (开通米勒平台)', ['', 'm'], 'device'),
    ('Vgp_off',  'Miller plateau Vgp(off), V (关断米勒平台)', ['', 'm'], 'device'),
    ('Qg_th',    'Gate threshold charge Qg(th), C (栅极门限电荷)', ['n'], 'device'),
    ('Qgs',      'Gate-source charge Qgs, C (栅源电荷)',    ['n'], 'device'),
    ('Qgd',      'Miller charge Qgd, C (米勒平台电荷)',     ['n'], 'device'),
    ('Rg_drive', 'Driver resistance Rg_drive, Ohm (驱动器内阻)', [''], 'device'),
    ('Rs_on',    'Gate series Ron, Ohm (开通栅极串联电阻)', [''], 'device'),
    ('Rs_off',   'Gate series Roff, Ohm (关断栅极串联电阻)', [''], 'device'),
    ('Rg',       'Internal gate resistance Rg, Ohm (MOS内栅阻)', [''], 'device'),
    ('k_sw',     'Switching-loss factor k (电感0.25/电阻0.167)', [], 'device'),
    ('Qrr',      'Diode reverse-recovery Qrr, C (反向恢复电荷)', ['n'], 'device'),
    ('Vgs',      'Gate drive voltage, V (栅极驱动电压)', ['', 'm'], 'device'),
    ('ma_slope', 'Slope compensation ma, A/s (斜坡补偿, 原边电感电流斜率)', ['k'], 'device'),
    # magnetics
    ('inductor_dcr', '成品电感 DCR', ['m', ''], 'mag'),
    ('inductor_rated_current', '成品电感额定 RMS 电流', ['', 'm'], 'mag'),
    ('inductor_saturation_current', '成品电感饱和电流', ['', 'm'], 'mag'),
    ('inductor_extra_loss', '成品电感附加损耗', ['', 'm'], 'mag'),
    ('Bmax', 'Max flux density Bmax, T (设计最大磁通密度)', [], 'mag'),
    ('Bsat', 'Saturation flux Bsat, T (饱和磁密)',        [], 'mag'),
    ('Ku',    'Window fill factor Ku (窗口填充系数)',     [], 'mag'),
    ('mu_r', '磁材相对磁导率（0=材料预设）', [], 'mag'),
    ('rho',   'Wire resistivity rho, Ohm*m (导线电阻率)', [], 'mag'),
    ('Rth_transformer', 'Transformer to ambient Ri-a, K/W (变压器至环境热阻)', [], 'mag'),
    ('h_conv', 'Inductor convection coeff h, W/m^2K (电感对流系数)', [], 'mag'),
    ('temp_rise_limit', '磁件温升评审上限, K', [], 'mag'),
    ('k_core', 'Steinmetz k (磁损系数 k)',               [], 'mag'),
    ('a_core', 'Steinmetz alpha (磁损系数 α)',           [], 'mag'),
    ('b_core', 'Steinmetz beta (磁损系数 β)',            [], 'mag'),
    ('MLT', 'Mean length per turn MLT, cm (每圈平均长度, 0=auto)', ['c', 'm'], 'mag'),
    ('Np', 'Transformer primary turns Np (原边匝数, 0=auto)', [], 'mag'),
    ('Ns', 'Transformer secondary turns Ns (副边匝数, 0=auto)', [], 'mag'),
    ('d_wire_p', 'Primary wire dia, mm (原边线径, 0=auto)', ['m'], 'mag'),
    ('d_wire_s', 'Secondary wire dia, mm (副边线径, 0=auto)', ['m'], 'mag'),
    ('n_strand_p', 'Primary parallel strands (原边并绕数)', [], 'mag'),
    ('n_strand_s', 'Secondary parallel strands (副边并绕数)', [], 'mag'),
    ('parallel_wires_p', '原边线圈并绕数（相同整根线）', [], 'mag'),
    ('parallel_wires_s', '副边线圈并绕数（相同整根线）', [], 'mag'),
    # controller
    ('KP',   'Controller KP (控制器增益)',               [], 'ctrl'),
    ('fz1',  'Zero fz1, Hz (零点)',                      ['', 'k', 'M'], 'ctrl'),
    ('fz2',  'Zero fz2, Hz (零点)',                      ['', 'k', 'M'], 'ctrl'),
    ('fp1',  'Pole fp1, Hz (极点)',                      ['', 'k', 'M'], 'ctrl'),
    ('fp2',  'Pole fp2, Hz (极点)',                      ['', 'k', 'M'], 'ctrl'),
]

# bilingual display labels for the topology / control-mode combo boxes;
# the *values* used by the compute engine stay the English keys
TOPO_LABEL = {'BUCK': 'BUCK (降压)', 'BOOST': 'BOOST (升压)',
              'BUCK-BOOST': 'BUCK-BOOST (升降压)',
              'FLYBACK': 'FLYBACK (反激)',
              'QR-FLYBACK': 'FLYBACK-QR (准谐振反激)',
              'ACF-FORWARD': 'ACF-FORWARD (有源钳位正激)'}
TOPO_KEY = {v: k for k, v in TOPO_LABEL.items()}
CTRL_LABEL = {'Voltage Mode': 'Voltage Mode (电压模式)',
              'Peak Current Mode': 'Peak Current Mode (峰值电流模式)'}
CTRL_KEY = {v: k for k, v in CTRL_LABEL.items()}
CONTROLLER_CHOICES = ('auto', 'type2', 'type3')
CONTROLLER_NAMES = {'type2': '二型', 'type3': '三型'}

SECTION_TITLES = {'spec': 'Specifications (规格参数)', 'stage': 'Power Stage (功率级)',
                  'forward': '有源钳位正激 (独立励磁 / 钳位参数)',
                  'device': 'Power Devices (功率器件)',
                  'mag': 'Magnetics (磁件)', 'ctrl': 'Controller (控制器/补偿器)'}

SWEEP_OPTIONS = {
    'BUCK': [('f_sw', 'Switching frequency (开关频率)'),
             ('L', 'Inductance (电感)'),
             ('C_out', 'Output capacitance (输出电容)'),
             ('Rds_on', 'MOSFET Rds(on) (导通电阻)'),
             ('Bmax', 'Flux density Bmax (磁通密度)'),
             ],
    'BOOST': [('f_sw', 'Switching frequency (开关频率)'),
              ('L', 'Inductance (电感)'),
              ('C_out', 'Output capacitance (输出电容)'),
              ('Rds_on', 'MOSFET Rds(on) (导通电阻)'),
              ('Bmax', 'Flux density Bmax (磁通密度)'),
              ],
    'BUCK-BOOST': [('f_sw', 'Switching frequency (开关频率)'),
                   ('L', 'Inductance (电感)'),
                   ('C_out', 'Output capacitance (输出电容)'),
                   ('Rds_on', 'MOSFET Rds(on) (导通电阻)'),
                   ('Bmax', 'Flux density Bmax (磁通密度)'),
                   ],
    'FLYBACK': [('f_sw', 'Switching frequency (开关频率)'),
                ('L', 'Magnetising Lm (励磁电感)'),
                ('N', 'Turns ratio N (匝比)'),
                ('C_out', 'Output capacitance (输出电容)'),
                ('Rds_on', 'MOSFET Rds(on) (导通电阻)')],
    'QR-FLYBACK': [('L', 'Magnetising Lm (励磁电感)'),
                   ('N', 'Turns ratio N (匝比)'),
                   ('C_out', 'Output capacitance (输出电容)'),
                   ('Rds_on', 'MOSFET Rds(on) (导通电阻)')],
    'ACF-FORWARD': [('f_sw', 'Switching frequency (开关频率)'),
                    ('L', 'Output choke (输出滤波电感)'),
                    ('Lm_forward', 'Transformer Lm (励磁电感)'),
                    ('C_clamp', 'Clamp capacitor (钳位电容)'),
                    ('N', 'Turns ratio Np/Ns (匝比)')],
}

# one-line guidance shown at the top of every step (design flow)
STEP_GUIDE = [
    '功率级 (书 ch.2/3): 核对 CCM/DCM、器件电流与输出纹波；末两图为 Q1 开通 / 关断的 Vgs、Vds 分段示意。电容电流见⑦页。',
    '器件应力 (书 ch.4): 核对 MOSFET / 二极管的电压、电流应力与损耗分解, 按 ≥1.2~1.5 倍裕量选型。',
    '磁件设计 (书 ch.10~12): 选芯、匝数、气隙; 校核饱和裕度 Bpk < Bsat 与温升 ΔT。',
    '环路设计 (书 ch.8/9): 校核穿越频率、相位裕度、增益裕度; 注意 RHP 零点与 DCM 模型限制。',
    '效率与优化 (书 ch.3): 损耗分解、效率-负载曲线、参数扫描与优化。',
]

# First four power-page charts; the last two are Q1 turn-on / turn-off.
def _power_signals(topo):
    from power_charts import power_signals
    return power_signals(topo)

from isolated_ui import IsolatedUI


class PowerSupplyAnalyzer(WindingUI, IsolatedUI, ParameterPanelUI, MultiOutputResultsUI, EngineeringUI):
    def __init__(self, root, *, initial_config=None, on_return=None):
        self.root = root
        self._workspace_return = on_return
        self.root.title("Switching Power Supply Design & Loop Analyzer  " + APP_VERSION)
        # adaptive window size: fit small laptop screens, keep 1600x950 max
        _sw = self.root.winfo_screenwidth()
        _sh = self.root.winfo_screenheight()
        _w0 = min(1600, max(1000, _sw - 40))
        _h0 = min(950, max(600, _sh - 90))
        self.root.geometry(f'{_w0}x{_h0}')
        self.root.minsize(1000, 600)

        from ui_preferences import font_size
        self._font_k = font_size()/13
        _polish_matplotlib()            # colours only; sizes come from _apply_fonts
        _setup_style(root, self._font_k)
        self._font_timer = None
        self._wrap_widgets = []

        # application icon (source mode: icon.png; the exe embeds icon.ico)
        try:
            icon = resource_path('icon.png')
            if os.path.isfile(icon):
                self.root.iconphoto(True, tk.PhotoImage(file=icon))
        except Exception:
            pass

        self.units = {'p': 1e-12, 'n': 1e-9, 'u': 1e-6, 'm': 1e-3, 'c': 1e-2,
                      'k': 1e3, 'M': 1e6, '': 1}
        self.update_pending = False
        self.update_timer = None
        # Let editing settle before an expensive multi-winding periodic solve.
        self.update_delay = 450
        self._calculation_worker = LatestCalculationWorker(cache_size=3)
        self._calculation_poll_job = None
        self._design_ready_job = None
        self._eff_curve_signature = None
        self._eff_curve_result = None
        self._export_after_calculation = False
        self._control_ready = False
        self._control_warmup_job = None
        self._control_poll_job = None
        self._control_loading = False
        self._control_error = None
        self._loop_signature = None
        self._loop_models = None
        self._loop_error = None
        self._loop_pending_signature = None
        self._loop_tune_pending = None
        self._lazy_output_cards = True
        self._initial_update_job = None
        self._closing = False
        self._building = True
        self._last = None            # latest design dict shared by the tabs
        self._component_management = {}
        self._spice_config = {}
        self._parasitic_config = {}
        self._engineering_acceptance = {}
        self._acceptance_range_result = None
        self._acceptance_evidence_reference = None
        self._acceptance_evidence_cache = None
        self._rendered_tabs = set()  # notebook indexes matching _last

        self.params = {}
        self.unit_opts = {}
        self.param_labels = []
        self._param_widgets = {}
        self._param_sections = {}
        self._folded_sections = set()
        self._param_layout_job = None
        self._snapshot_valid = False
        self.input_case_note = tk.StringVar(value='输入工况待计算')
        self._init_engineering_state()
        self._init_isolated_state()
        self._init_winding_state()
        self._build_params()

        # margin / status displays
        self.margin_info = {k: tk.StringVar(value=v) for k, v in
                            [('pm', 'PM: --'), ('gm', 'GM: --'),
                             ('fc', 'fc: --')]}
        # caveat shown in the loop tab: the output-cap ESR zero is only modelled
        # buck/boost/buck-boost/flyback/
        # QR plants use an ideal output cap and do NOT include it.
        self.loop_esr_note = tk.StringVar(value='')
        self.controller_note = tk.StringVar(value='')
        self.status_var = tk.StringVar(value='正在准备首屏… (Preparing workspace)')

        self.create_widgets()
        from config_io import read_default_config
        self._apply_config(initial_config if initial_config is not None else read_default_config())
        self._building = False

        # Apply topology-dependent defaults before traces are attached; this
        # avoids scheduling a redundant second first-screen calculation.
        self.on_topology_change(reset_target=False)
        self._on_controller_change()
        for var in self.params.values():
            var.trace('w', lambda *a: self.schedule_update())
        self.params['topology'].trace('w', lambda *a: self.on_topology_change())
        self.params['controller_type'].trace('w', lambda *a: self._on_controller_change())
        self.params['control_mode'].trace('w', lambda *a: self._on_controller_change())
        self._collect_wrap_widgets()
        self.root.bind('<Configure>', self._on_root_resize, add='+')
        self.root.protocol('WM_DELETE_WINDOW', self.on_close)
        self.root.bind('<Destroy>', self._calculation_window_destroyed, add='+')

        # Let Tk show the shell before calculating/redrawing the first tab.
        # Loop analysis is loaded on demand, not as idle background work.
        self._initial_update_job = self.root.after_idle(self._run_initial_update)

    def _run_initial_update(self):
        self._initial_update_job = None
        if not self._closing:
            self.request_update()

    def _start_control_warmup(self):
        """Load loop-only libraries when a loop/review page first needs them."""
        self._control_warmup_job = None
        if self._closing or self._control_ready or self._control_loading:
            return
        import threading
        self._control_loading=True
        self._control_error=None

        def worker():
            try:
                import control  # noqa: F401
            except Exception as error:
                self._control_error=str(error)
            else:
                self._control_ready = True
            finally:
                self._control_loading=False
        threading.Thread(target=worker, name='control-warmup', daemon=True).start()
        def poll():
            self._control_poll_job = None
            if self._closing:
                return
            if self._control_ready:
                self._refresh_loop_margins()
                self._rendered_tabs.discard(4)
                self._refresh_visible_tab()
            elif self._control_error is not None:
                self.loop_esr_note.set('环路依赖加载失败：'+self._control_error)
            else:
                self._control_poll_job = self.root.after(100, poll)
        self._control_poll_job = self.root.after(100, poll)

    def _refresh_loop_margins(self):
        """Fill toolbar margin values without recomputing/redrawing the page."""
        if self._closing or not self._control_ready or self._last is None or not self._snapshot_valid:
            return
        try:
            if self.nb.index(self.nb.select()) in (4,9):
                self._update_loop(self._last['p'], draw=False)
        except Exception:
            pass

    # --------------------------------------------------- responsive fonts
    def _collect_wrap_widgets(self):
        """Record every wrapping label so its wraplength follows the window
        scale; one-line guide labels get a wraplength here in the first place
        so they wrap instead of clipping on narrow windows."""
        self._wrap_widgets = []

        def walk(w):
            if isinstance(w, ttk.Label):
                wl = w.cget('wraplength')
                if wl and wl > 0:
                    self._wrap_widgets.append((w, wl))
                elif 'Guide' in str(w.cget('style')):
                    w.configure(wraplength=1500)
                    self._wrap_widgets.append((w, 1500))
            for c in w.winfo_children():
                walk(c)

        walk(self.root)

    def _on_root_resize(self, event):
        if event.widget is not self.root or self._building:
            return
        # Resizing changes layout, never the user's chosen font size.
        self._resize_left()

    def _choose_font_size(self,value):
        from ui_preferences import save_font_size
        value=save_font_size(value)
        self._font_choice.set(str(value))
        self._apply_scale(value/13)

    def _apply_scale(self, k):
        """Re-apply fonts / wraplengths / chart text sizes at scale k."""
        self._font_timer = None
        self._font_k = k
        _apply_fonts(ttk.Style(self.root), k)
        for w, base in self._wrap_widgets:
            try:
                w.configure(wraplength=int(base * k))
            except Exception:
                pass
        self._resize_left()
        self._schedule_parameter_scrollregion()
        # Font/viewport changes are presentation-only: keep the numerical solve.
        self._rendered_tabs.clear()
        self._refresh_visible_tab()

    def on_close(self):
        """Cancel pending update timers, destroy the window, and make sure the
        process (incl. the packaged one-file bootloader child) is really gone."""
        if self._workspace_return and not self._workspace_return(self):
            return
        self._closing = True
        if getattr(self, '_mousewheel_binding', None):
            self.root._root()._unbind(('bind', 'all', '<MouseWheel>'), self._mousewheel_binding)
        self._calculation_worker.close()
        Tooltip.hide_all(self.root)
        self._work_cancel.set()
        for job in (self.update_timer, self._font_timer,
                    self._initial_update_job, self._control_warmup_job, self._control_poll_job, self._work_poll,
                    self._param_layout_job, self._calculation_poll_job,
                    getattr(self, '_design_ready_job', None)):
            if job is not None:
                try:
                    self.root.after_cancel(job)
                except Exception:
                    pass
        try:
            self.root.destroy()
        finally:
            if self._workspace_return is None:
                os._exit(0)

    # ------------------------------------------------------------------ params
    def _build_params(self):
        for key, _label, units, _sec in PARAM_SPECS:
            default = DEFAULT_PARAMS.get(key, DEFAULT_PARAMS['V_in'] if key in ('V_in_min', 'V_in_max') else 0.0)
            unit = self._natural_unit(default, units)
            # entry values are stored *in the selected unit* (e.g. L = 4.7 with
            # unit 'u'); get_param() converts back to SI.
            self.params[key] = tk.DoubleVar(value=default / self.units[unit])
            self.params[key + '_unit'] = tk.StringVar(value=unit)
            self.unit_opts[key] = units
        self.params['topology'] = tk.StringVar(
            value=TOPO_LABEL[DEFAULT_PARAMS['topology']])
        self.params['control_mode'] = tk.StringVar(value=CTRL_LABEL[DEFAULT_PARAMS['control_mode']])
        self.params['controller_type'] = tk.StringVar(value='auto')
        self.params['input_voltage_case'] = tk.StringVar(value='min')
        self.params['core_choice'] = tk.StringVar(value='auto')
        self.params['inductor_design_enabled'] = tk.BooleanVar(value=True)
        # Shared clamp variables are created before the left-side editor;
        # the right-side clamp page now contains results only.
        self.rcd_K = tk.DoubleVar(value=0.95)
        self.rcd_Kc = tk.DoubleVar(value=1.5)
        self.rcd_dC = tk.DoubleVar(value=0.10)
        self.params.update(rcd_K=self.rcd_K, rcd_Kc=self.rcd_Kc, rcd_dC=self.rcd_dC)

        # optimisation tab vars
        self.params['target_eta'] = tk.DoubleVar(value=DEFAULT_PARAMS['target_eta'])
        self.params['load_frac'] = tk.DoubleVar(value=DEFAULT_PARAMS['load_frac'])
        self.params['sweep_var'] = tk.StringVar(value='f_sw')
        self.params['sweep_min'] = tk.DoubleVar(value=50)
        self.params['sweep_min_unit'] = tk.StringVar(value='k')
        self.params['sweep_max'] = tk.DoubleVar(value=500)
        self.params['sweep_max_unit'] = tk.StringVar(value='k')
        self.params['sweep_n'] = tk.DoubleVar(value=41)

    @staticmethod
    def _natural_unit(value, units):
        """Choose the unit from 'units' that shows 'value' between 0.1..1000."""
        if not units or value == 0:
            return units[-1] if units else ''
        exp = int(np.floor(np.log10(abs(value)) / 3))
        pref = ['p', 'n', 'u', 'm', '', 'k', 'M']
        if 'c' in units and exp == -2:
            return 'c'
        unit = pref[max(-4, min(2, exp)) + 4]
        if unit in units:
            return unit
        order = [units.index(u) if u in ('p', 'n', 'u', 'm', '', 'k', 'M') else -1
                 for u in units]
        return units[int(np.argmin([abs(o - (max(-4, min(2, exp)) + 4))
                                    for o in order]))]

    def get_param(self, name):
        """SI value of a parameter (value * unit)."""
        if name == 'V_in' and 'input_voltage_case' in self.params:
            key = 'V_in_max' if self.params['input_voltage_case'].get() == 'max' else 'V_in_min'
            return self.get_param(key)
        v = self.params[name].get()
        u = self.params.get(name + '_unit')
        return v * self.units[u.get()] if u is not None else v

    def set_param(self, name, value):
        """Set a parameter from an SI value, picking a nice display unit."""
        if name == 'V_in' and 'V_in_min' in self.params:
            # Compatibility with old tools: a scalar input means a single
            # operating point, never an invented +/- tolerance range.
            self.set_param('V_in_min', value)
            self.set_param('V_in_max', value)
        units = self.unit_opts.get(name, [''])
        if not units:
            self.params[name].set(value)
            return
        exp = int(np.floor(np.log10(abs(value) + 1e-30) / 3)) if value != 0 else 0
        exp = max(-4, min(2, exp))
        pref = ['p', 'n', 'u', 'm', '', 'k', 'M']
        unit = 'c' if ('c' in units and exp == -2) else pref[exp + 4]
        if unit not in units:
            unit = units[-1]
        self.params[name].set(value / self.units[unit] if unit else value)
        self.params[name + '_unit'].set(unit)

    def _topo_key(self):
        return TOPO_KEY.get(self.params['topology'].get(),
                            self.params['topology'].get())

    def _ctrl_key(self):
        return CTRL_KEY.get(self.params['control_mode'].get(),
                            self.params['control_mode'].get())

    def _controller_key(self):
        return resolve_controller_type(self.params['controller_type'].get(), self._ctrl_key())

    def _on_controller_change(self):
        """Restore the original five controller entries and II/III loop orders."""
        if self._building:
            return
        kind = self._controller_key()
        for key in ('KP','fz1','fz2','fp1','fp2'):
            for widget in self._param_widgets.get(key, ()):
                widget.grid()
        self.controller_note.set(
            '二型: 原点极点 + fz1 零点 + fp1 高频极点；fz2/fp2 未启用，阻容计算忽略。' if kind == 'type2' else
            '三型: 原点极点 + fz1/fz2 零点 + fp1/fp2 高频极点。')
        if hasattr(self,'tune_result'):
            self.tune_result.set('')
        self._filter_params()
        self.schedule_update()

    def get_params(self, *, check_curve_sources=True):
        """All parameters as SI dict."""
        if check_curve_sources:
            self._validate_curve_requests()
        p = {}
        for key, _l, _u, _s in PARAM_SPECS:
            # Inactive topology/rail-owned values stay in the saved design,
            # but never enter this topology's calculation (even if partially
            # typed before switching). Folding/search do not affect ownership.
            p[key] = self.get_param(key) if self._scalar_parameter_active(key) else DEFAULT_PARAMS.get(key, DEFAULT_PARAMS['V_in'])
        p['input_voltage_case'] = self.params['input_voltage_case'].get()
        p['mos_miller_mode']=self.params['mos_miller_mode'].get()
        p['mos_miller_curve']=__import__('copy').deepcopy(self._mos_miller_curve)
        p['mos_charge_mode']=self.params['mos_charge_mode'].get()
        p['mos_charge_curve']=__import__('copy').deepcopy(self._mos_charge_curve)
        p['diode_curves']=__import__('copy').deepcopy(self._diode_curves)
        p['device_curve_settings']=__import__('copy').deepcopy(self._device_curve_settings)
        p['component_management']=__import__('copy').deepcopy(self._component_management)
        p['spice_config']=__import__('copy').deepcopy(self._spice_config)
        p['parasitic_config']=__import__('copy').deepcopy(self._parasitic_config)
        p['engineering_acceptance']=copy.deepcopy(self._engineering_acceptance)
        p.update(self._capacitor_parameters())
        for key in ('Rd_diode','Rd_din','Rd_dout'):p[key]=0.
        p['mos_manual_events']=self._manual_events_value() if self._mos_resolved_mode()=='manual' else {}
        if self._psr_active():
            p.update(f_sw=250e3, A_sense=11.)
        p['topology'] = self._topo_key()
        p['control_mode'] = self._ctrl_key()
        p['controller_type'] = normalize_controller_type(self.params['controller_type'].get())
        p['inductor_design_enabled'] = self.params['inductor_design_enabled'].get()
        p['cin2_enable'] = self.params.get('cin2_enable', tk.BooleanVar(value=False)).get()
        p['cout2_enable'] = self.params.get('cout2_enable', tk.BooleanVar(value=False)).get()
        p['d_in_enable'] = self.params.get('d_in_enable', tk.BooleanVar(value=False)).get()
        p['d_out_enable'] = self.params.get('d_out_enable', tk.BooleanVar(value=False)).get()
        # winding current density is a DERIVED result (I_rms / strand area);
        # this fixed value is only used to auto-size the wire when the user
        # has not entered a wire diameter / turns.
        p['J'] = DEFAULT_PARAMS['J']
        # tr/tf are internal edge-time defaults (ESL slew)
        p['tr'] = DEFAULT_PARAMS['tr']
        p['tf'] = DEFAULT_PARAMS['tf']
        p['core_choice'] = self.params.get('core_choice',
                                           tk.StringVar(value='auto')).get()
        p['core_choice_L'] = self.params.get('core_choice_L',
                                             tk.StringVar(value='auto')).get()
        if self._topo_key() != 'ACF-FORWARD' or self._multiple_active():
            p['core_choice_L'] = 'auto'
        p['core_shape'] = self.params.get('core_shape',
                                          tk.StringVar(value='auto')).get()
        p['core_material'] = self.params['core_material'].get()
        p.update(self._custom_core_parameters())
        p.update(target_eta=self.params['target_eta'].get(),
                 fc_target=self.get_param('fc_target'),
                 pm_target=self.params['pm_target'].get())
        from input_voltage_range import normalize_input_voltage_spec
        return normalize_input_voltage_spec(self._isolated_parameters(p))

    # ------------------------------------------------------------------ gui
    def create_widgets(self):
        main = ttk.Frame(self.root, padding='10 8 10 8')
        main.grid(row=0, column=0, sticky='nsew')
        self.root.columnconfigure(0, weight=1)
        self.root.rowconfigure(0, weight=1)

        # top banner
        banner = ttk.Frame(main, style='Banner.TFrame', padding='14 8')
        banner.grid(row=0, column=0, columnspan=2, sticky='ew', pady=(0, 8))
        self._calculator_banner=banner
        titlebar=ttk.Frame(banner,style='Banner.TFrame')
        titlebar.grid(row=0,column=0,sticky='w')
        self._calculator_banner_title=titlebar
        ttk.Label(titlebar, text='开关电源设计与环路分析',
                  style='Banner.TLabel').pack(side='left')
        if self._workspace_return:
            ttk.Button(titlebar, text='← 返回系统架构', style='Banner.TButton',
                       command=self.on_close).pack(side='left', padx=14)
        actions=ttk.Frame(banner,style='Banner.TFrame');actions.grid(row=0,column=1,sticky='e')
        self._calculator_banner_actions=actions;self._calculator_banner_rows=None
        banner.columnconfigure(0,weight=1)
        export_button=ttk.Menubutton(actions,text='导出报告 ▾',style='Banner.TButton')
        export_menu=tk.Menu(export_button,tearoff=False)
        export_menu.add_command(label='电磁仿真，电路仿真，设计计算联合报告…',command=self._export_joint_ui)
        export_menu.add_separator()
        export_menu.add_command(label='设计报告 · Word / Excel / Markdown',command=self._export_report_ui)
        export_menu.add_command(label='仿真与设计计算对比报告 · Word + 工程 ZIP',command=lambda:self._export_spice_ui(comparison=True))
        export_menu.add_separator()
        export_menu.add_command(label='仿真与报告中心 · 设置 / 单项导出',command=self._export_joint_ui)
        export_button.configure(menu=export_menu);export_button.pack(side='right',padx=(8,0))
        ttk.Button(actions, text='重新计算', style='Banner.TButton',
                   command=self.request_update).pack(side='right', padx=(8, 0))
        from ui_preferences import font_control
        self._font_choice=font_control(actions,self._choose_font_size)
        banner.bind('<Configure>',self._layout_calculator_banner)

        # ---- left parameter panel (width adapts to the window) -------------
        left = ttk.Frame(main, style='TFrame')
        left.grid(row=1, column=0, sticky='ns')
        left.grid_propagate(False)
        self.left = left
        canvas = tk.Canvas(left, width=330, highlightthickness=0,
                           background=PANEL, borderwidth=0)
        vsb = ttk.Scrollbar(left, orient='vertical', command=self._scroll_params)
        canvas.configure(yscrollcommand=vsb.set)
        vsb.pack(side='right', fill='y')
        canvas.pack(side='left', fill='both', expand=True)
        self.left_canvas = canvas
        self.left_inner = ttk.Frame(canvas, style='TFrame')
        self._param_canvas_window = canvas.create_window((0, 0), window=self.left_inner, anchor='nw')
        def resize_params(event):
            canvas.itemconfigure(self._param_canvas_window,width=max(1,event.width))
            self._schedule_parameter_scrollregion()
        canvas.bind('<Configure>',resize_params)
        self.left_inner.bind('<Configure>',self._schedule_parameter_scrollregion)
        self.left_inner.columnconfigure(0, weight=1)

        self._build_param_panel(self.left_inner)
        self._mousewheel_binding = self.root.bind_all('<MouseWheel>', self._on_mousewheel, add='+')

        # ---- notebook --------------------------------------------------------
        results = ttk.Frame(main)
        results.grid(row=1, column=1, sticky='nsew', padx=(8, 0))
        ttk.Label(results, textvariable=self.input_case_note, style='Margin.TLabel',
                  padding=(8, 4), wraplength=1000).pack(fill='x')
        nb = ttk.Notebook(results)
        nb.pack(fill='both', expand=True)
        main.columnconfigure(1, weight=1)
        main.rowconfigure(1, weight=1)

        self.tab_topology = ttk.Frame(nb)
        self.tab_power = ttk.Frame(nb)
        self.tab_stress = ttk.Frame(nb)
        self.tab_mag = ttk.Frame(nb)
        self.tab_loop = ttk.Frame(nb)
        self.tab_eff = ttk.Frame(nb)
        self.tab_cap = ttk.Frame(nb)
        self.tab_rcd = ttk.Frame(nb)
        self.tab_comp = ttk.Frame(nb)
        self.tab_review = ttk.Frame(nb)
        nb.add(self.tab_topology, text=' ① 拓扑 ')
        nb.add(self.tab_power, text=' ② 功率级 ')
        nb.add(self.tab_stress, text=' ③ 器件 ')
        nb.add(self.tab_mag, text=' ④ 磁件 ')
        nb.add(self.tab_loop, text=' ⑤ 环路 ')
        nb.add(self.tab_eff, text=' ⑥ 效率 ')
        nb.add(self.tab_cap, text=' ⑦ 电容纹波 ')
        nb.add(self.tab_rcd, text=' ⑧ RCD钳位 ')
        nb.add(self.tab_comp, text=' ⑨ 补偿参数 ')
        nb.add(self.tab_review, text=' ⑩ 工程评审 ')
        self.nb = nb
        nb.bind('<<NotebookTabChanged>>', lambda _e: self._refresh_visible_tab())

        self._build_topology_tab()
        self._build_power_tab()
        self._build_stress_tab()
        self._build_mag_tab()
        self._build_loop_tab()
        self._build_eff_tab()
        self._build_cap_tab()
        self._build_rcd_tab()
        self._build_comp_tab()
        self._build_review_tab()

        # menu bar: manual + about
        menubar = tk.Menu(self.root)
        filemenu = tk.Menu(menubar, tearoff=0)
        filemenu.add_command(label='保存配置 (Save Config)', command=self.save_config)
        filemenu.add_command(label='打开配置 (Open Config)', command=self.load_config)
        filemenu.add_command(label='导出设计报告 (Word / Excel)',
                             command=self._export_report_ui)
        filemenu.add_command(label='电磁仿真，电路仿真，设计计算联合报告…', command=self._export_joint_ui)
        filemenu.add_command(label='LTspice 电源闭环 · 配置与导出', command=self._export_spice_ui)
        filemenu.add_command(label='仿真与设计计算对比报告 (Word)',command=lambda:self._export_spice_ui(comparison=True))
        filemenu.add_separator()
        filemenu.add_command(label='Exit (退出)', command=self.on_close)
        menubar.add_cascade(label='File (文件)', menu=filemenu)
        examples = tk.Menu(menubar, tearoff=0)
        from example_catalog import EXAMPLES
        for filename, label in EXAMPLES.items():
            examples.add_command(label=label, command=lambda name=filename:self.load_isolated_example(name))
        menubar.add_cascade(label='示例', menu=examples)
        automatic = tk.Menu(menubar, tearoff=0)
        automatic.add_command(label='按规格生成初版（Buck / Boost / 反激）…', command=self.open_initial_design)
        automatic.add_command(label='自动计算参数依据', command=self.open_auto_design_basis)
        menubar.add_cascade(label='自动设计', menu=automatic)
        helpmenu = tk.Menu(menubar, tearoff=0)
        helpmenu.add_command(label='计算方法与公式说明',
                             command=self.open_calculation_reference)
        helpmenu.add_command(label='多路反激电源设计入门教程',
                             command=self.open_design_tutorial)
        helpmenu.add_command(label='自动计算参数依据', command=self.open_auto_design_basis)
        menubar.add_cascade(label='Help (帮助)', menu=helpmenu)
        self.root.config(menu=menubar)
        self.root.bind('<Control-s>', lambda _e: self.save_config())
        self.root.bind('<Control-o>', lambda _e: self.load_config())
        self.root.bind('<Control-e>', lambda _e: self.export_report())

        # status bar
        bar = ttk.Label(self.root, textvariable=self.status_var,
                        style='Muted.TLabel', relief='flat',
                        background='#ffffff', padding=(10, 5))
        bar.grid(row=1, column=0, sticky='ew')
        bar.configure(borderwidth=1, relief='solid')
        self.root.option_add('*TCombobox*Listbox.font', (FAM, 10))

        self._resize_left()
        main.bind('<Configure>', lambda _e: self._resize_left())

    def _resize_left(self, _evt=None):
        """Left panel width follows the main window (≈23.5%, clamped)."""
        w = self.left.master.winfo_width()
        if w < 200:
            return
        limit=.64 if self._font_k*13>24 else .48
        target = min(int(w*limit),max(round(390*self._font_k), min(740,int(w*.30))))
        self.left.configure(width=target)
        self.left_canvas.configure(width=target - 18)
        widths={}
        for lab in self.param_labels:
            try:
                parent=lab.master
                if parent not in widths:
                    occupied={}
                    for child in parent.grid_slaves():
                        col=int(child.grid_info().get('column',0))
                        if col:occupied[col]=max(occupied.get(col,0),child.winfo_reqwidth()+10)
                    pw=parent.winfo_width()
                    widths[parent]=max(65,min(target-36,pw if pw>100 else target-36)-sum(occupied.values())-18)
                if abs(float(lab.cget('wraplength'))-widths[parent])>1:lab.configure(wraplength=widths[parent])
            except Exception:
                pass
        for frame in self._param_sections.values():
            if hasattr(frame, '_section_summary'):
                frame._section_summary.configure(wraplength=max(260, target-36))
        self._layout_calculator_banner()

    def _layout_calculator_banner(self,_event=None):
        if not hasattr(self,'_calculator_banner_actions'):return
        width=self._calculator_banner.winfo_width()
        if width<100:return
        split=self._calculator_banner_title.winfo_reqwidth()+self._calculator_banner_actions.winfo_reqwidth()+50>width
        if split!=self._calculator_banner_rows:
            self._calculator_banner_rows=split
            self._calculator_banner_actions.grid(row=1 if split else 0,column=0 if split else 1,columnspan=2 if split else 1,sticky='e',pady=(6,0) if split else 0)

    def _on_mousewheel(self, event):
        """Scroll the parameter pane when the pointer is anywhere over it."""
        try:
            widget = self.root.winfo_containing(event.x_root, event.y_root)
            while widget is not None and widget is not self.left:
                widget = widget.master
            if widget is self.left and event.delta:
                Tooltip.hide_all(self.root)
                self.left_canvas.yview_scroll(-int(event.delta / 120), 'units')
                return 'break'
        except Exception:
            pass

    def _scroll_params(self, *args):
        Tooltip.hide_all(self.root)
        self.left_canvas.yview(*args)

    # ---------------------------------------------------------- config I/O
    def _acceptance_apply(self, data):
        """Save review metadata without running an electrical calculation."""
        from engineering_acceptance import normalize
        self._engineering_acceptance = normalize(data)
        if self._last is not None:
            wrapper = dict(self._last)
            for key in ('p', 'calculation_params'):
                if key in wrapper:
                    wrapper[key] = dict(wrapper[key],
                        engineering_acceptance=copy.deepcopy(self._engineering_acceptance))
            self._last = wrapper
        self._export_after_calculation = False
        self.status_var.set('验收设置与记录已应用；保存工程可保留，电气结果无需重算。')

    def _acceptance_get_range_result(self):
        from engineering_acceptance import input_fingerprint
        current = self._current_spec()
        cached = self._acceptance_range_result
        if cached and input_fingerprint(cached['base_spec']) == input_fingerprint(current):
            return cached
        if self._snapshot_valid and self._last:
            saved = self._last['p']
            if input_fingerprint(saved) == input_fingerprint(current):
                key = 'Vinmax' if saved.get('input_voltage_case') == 'max' else 'Vinmin'
                return dict(base_spec=saved, fixed_hardware=False, cases=[
                    dict(id=key, voltage=saved['V_in'], p=saved,
                         result=self._last['res'], checks=self._last.get('checks', []))])
        return cached

    def _acceptance_get_joint_record(self):
        """Resolve an explicitly retained local run record, not arbitrary logs."""
        dialog = getattr(self, '_joint_simulation_dialog', None)
        if dialog is not None and isinstance(getattr(dialog, 'result', None), dict):
            live = dialog.result
            if live.get('adopted_config'):
                return live
        history = getattr(self, '_joint_simulation', None) or {}
        if history.get('adopted_config'):
            return history
        path = history.get('manifest_path')
        if not path:
            return history
        from pathlib import Path
        try:
            source = Path(path)
            if source.suffix.lower() != '.json' or not source.is_file() or source.stat().st_size > 32*1024*1024:
                return history
            marker = (str(source.resolve()), source.stat().st_mtime_ns, source.stat().st_size)
            cached = getattr(self, '_acceptance_joint_record_cache', None)
            if cached is None or cached[0] != marker:
                from transformer_geometry import strict_json
                record = strict_json(source.read_bytes())
                if not isinstance(record, dict):
                    return history
                self._acceptance_joint_record_cache = (marker, record)
            return self._acceptance_joint_record_cache[1]
        except (OSError, ValueError, TypeError):
            return history

    def _acceptance_refresh_endpoints(self):
        try:
            request = dict(p=copy.deepcopy(self._current_spec()))
            self._calculation_worker.submit('acceptance_endpoints', request,
                _calculate_acceptance_endpoints, cache=True)
            self.status_var.set('正在后台刷新验收 Vinmin / Vinmax；未启动电磁或电路仿真。')
            self._ensure_calculation_poll()
        except Exception as exc:
            messagebox.showerror('工程验证与验收', str(exc), parent=self.root)

    def _acceptance_get_spice_evidence(self):
        reference = self._acceptance_evidence_reference
        if not reference:
            return None
        from pathlib import Path
        try:
            source = Path(reference['path'])
            stat = source.stat()
            marker = (reference['path'], reference['payload_sha256'], stat.st_mtime_ns, stat.st_size)
            cached = self._acceptance_evidence_cache
            if cached is None or cached[0] != marker:
                from acceptance_evidence_io import load_evidence
                _, envelope = load_evidence(source, reference=reference)
                self._acceptance_evidence_cache = (marker, envelope)
            return self._acceptance_evidence_cache[1]
        except (OSError, ValueError, KeyError) as exc:
            return dict(source='证据引用不可用：'+str(exc), evidence_error=str(exc))

    def _acceptance_import_evidence(self):
        path = filedialog.askopenfilename(parent=self.root, title='导入电路比较或联合仿真证据',
            filetypes=[('仿真证据 JSON / ZIP', '*.json *.zip')])
        if not path:
            return
        try:
            from acceptance_evidence_io import load_evidence
            reference, _ = load_evidence(path)
            self._acceptance_evidence_reference = reference
            self._acceptance_evidence_cache = None
            self.acceptance_panel.refresh()
            self.status_var.set('仿真证据引用已导入；按当前硬件匹配判定，保存工程可保留引用。')
        except (OSError, ValueError) as exc:
            messagebox.showerror('导入验收证据', str(exc), parent=self.root)

    def _config_dict(self):
        """Serialisable dict of every UI parameter (value + unit)."""
        cfg = {}
        for key, var in self.params.items():
            if key.endswith('_unit'):
                continue
            if isinstance(var, tk.DoubleVar):
                uvar = self.params.get(key + '_unit')
                prefix = uvar.get() if uvar is not None else ''
                try:
                    value = float(var.get())
                    if not np.isfinite(value):
                        raise ValueError(f'{key} 必须为有限数值')
                except (ValueError, tk.TclError):
                    inactive_scalar = key in self._param_widgets and not self._scalar_parameter_active(key)
                    inactive_rcd = key in ('rcd_K', 'rcd_Kc', 'rcd_dC') and self._topo_key() not in ('FLYBACK', 'QR-FLYBACK')
                    inactive_rcd = inactive_rcd or (key=='rcd_K' and hasattr(self,'coupling_enabled')
                                                   and self.coupling_enabled.get() and self._coupling_supported())
                    if not (inactive_scalar or inactive_rcd):
                        raise
                    fallback = {'rcd_K': .95, 'rcd_Kc': 1.5, 'rcd_dC': .10}.get(key, DEFAULT_PARAMS.get(key))
                    value = fallback / self.units[prefix]
                cfg[key] = dict(v=value, u=prefix)
            else:
                try:
                    cfg[key] = dict(v=var.get(), u='')
                except Exception:
                    pass
        cfg['__version__'] = MANUAL_VERSION
        if getattr(self,'_auto_design_basis',None):
            cfg['__auto_design_basis'] = copy.deepcopy(self._auto_design_basis)
        if getattr(self, '_transformer_simulation', None):
            cfg['__transformer_simulation'] = copy.deepcopy(self._transformer_simulation)
        if getattr(self, '_joint_simulation', None):
            cfg['__joint_simulation'] = copy.deepcopy(self._joint_simulation)
        if self._acceptance_evidence_reference:
            cfg['__acceptance_evidence'] = copy.deepcopy(self._acceptance_evidence_reference)
        cfg['mos_miller_curve']=__import__('copy').deepcopy(self._mos_miller_curve)
        cfg['mos_charge_curve']=__import__('copy').deepcopy(self._mos_charge_curve)
        cfg['diode_curves']=__import__('copy').deepcopy(self._diode_curves)
        cfg['device_curve_settings']=__import__('copy').deepcopy(self._device_curve_settings)
        cfg['component_management']=__import__('copy').deepcopy(self._component_management)
        cfg['spice_config']=__import__('copy').deepcopy(self._spice_config)
        cfg['parasitic_config']=__import__('copy').deepcopy(self._parasitic_config)
        cfg['engineering_acceptance']=copy.deepcopy(self._engineering_acceptance)
        cfg.update(self._capacitor_parameters())
        for key in ('Rd_diode','Rd_din','Rd_dout'):cfg[key]=dict(v=0.,u='')
        cfg['mos_manual_events']=self._manual_events_value(strict=False)
        cfg['__comp'] = self._comp_state()
        cfg.update(self._isolated_config())
        cfg.update(self._winding_config())
        cfg.update(self._custom_core_parameters())
        cfg['V_in'] = dict(v=self.get_param('V_in'), u='')
        return cfg

    def _comp_state(self):
        """Tab-8 compensator designer state for the config file: direction,
        topology, type-II flag and every entered RC value (value + unit)."""
        d = {'topo': self.comp_type.get(),
             'type2': bool(self.comp_type2.get()),
             'dir': self.comp_dir.get(),
             'vars': {}}
        for key, var in self.comp_vars.items():
            if key.endswith('_unit'):
                continue
            try:
                u = self.comp_vars.get(key + '_unit')
                d['vars'][key] = {'v': float(var.get()),
                                  'u': (u.get() if u else '')}
            except Exception:
                pass
        return d

    def _apply_comp_state(self, st):
        """Restore the tab-8 designer state from a config dict (old configs
        without the __comp key are simply skipped)."""
        from compensation_report import network_key
        try:
            key=network_key(st.get('key') or st.get('topo'))
            self.comp_type.set(dict(self.COMP_TOPOS)[key])
        except ValueError:
            pass
        self.comp_type2.set(bool(st.get('type2', False)))
        self.comp_dir.set('rev' if st.get('dir') == 'rev' else 'fwd')
        self._on_comp_dir_change()          # rebuild inputs for dir + topo
        for key, d in (st.get('vars') or {}).items():
            if key not in self.comp_vars:
                continue                    # parts of another mode/topology
            try:
                self.comp_vars[key].set(float(d.get('v', 0.0)))
                uk = key + '_unit'
                if uk in self.comp_vars and d.get('u') is not None:
                    self.comp_vars[uk].set(str(d.get('u', '')))
            except Exception:
                pass

    def save_config(self):
        path = filedialog.asksaveasfilename(
            defaultextension='.json', filetypes=[('JSON config', '*.json')],
            title='保存电源参数配置 (Save parameter config)')
        if not path:
            return
        try:
            with open(path, 'w', encoding='utf-8') as f:
                json.dump(self._config_dict(), f, ensure_ascii=False, indent=2)
            from pathlib import Path
            if self._geometry_source is None:
                self._geometry_source=(Path(path).name,Path(path).read_bytes())
            self.status_var.set(f'配置已保存: {os.path.basename(path)}')
        except Exception as e:
            messagebox.showerror('Save config', str(e))

    def _export_report_ui(self):
        """Re-use a valid snapshot, or export after its asynchronous replacement."""
        self._export_after_calculation = True
        if self._snapshot_valid:
            self._queue_report_efficiency_curve()
        else:
            self.request_update(preserve_export=True)

    def _queue_report_efficiency_curve(self):
        if not self._snapshot_valid or self._last is None or self._closing:
            self._export_after_calculation = False
            return
        try:
            request = dict(p=self._report_input_parameters(self._last['p']))
        except Exception as exc:
            self._export_after_calculation = False
            self.status_var.set('报告参数无效，请先检查评审目标和绕制设置。')
            messagebox.showerror('Export report', str(exc))
            return
        if str(self.cross_button.cget('state'))=='disabled':
            self._mark_cross_regulation_stale()
        self._calculation_worker.submit('report_input_range', request,
                                       _calculate_input_report, cache=True)
        if self._eff_curve_result is None:
            self._eff_curve_signature = None
            self._rendered_tabs.discard(self.nb.index(self.tab_eff))
        self.status_var.set('正在后台准备 Vin min / Vin max 两端完整报告数据… 可继续编辑；编辑将取消本次导出。')
        self._ensure_calculation_poll()

    def _report_input_parameters(self, parameters):
        """Freeze review targets/layout before preparing numerical report data."""
        report_params = dict(parameters)
        winding_config = self._winding_config()['winding_config']
        if winding_config['window_width'] > 0 and winding_config['window_height'] > 0:
            report_params['winding_config'] = winding_config
        report_params.update(target_eta=self.params['target_eta'].get(),
                             fc_target=self.get_param('fc_target'),
                             pm_target=self.params['pm_target'].get())
        report_params['engineering_acceptance'] = copy.deepcopy(self._engineering_acceptance)
        return report_params

    def export_report(self, recompute=True, efficiency_curve=None, range_result=None):
        """Export both endpoints as Word, modular Excel or Markdown."""
        if (recompute and not self.update_all()) or not self._snapshot_valid:
            messagebox.showerror('Export report', '当前设计尚未成功计算，请先检查输入参数。')
            return
        report_filetype = tk.StringVar(value='Word 工程报告')
        path = filedialog.asksaveasfilename(
            defaultextension='.docx',
            filetypes=[('Word 工程报告', '*.docx'), ('Excel 模块对照报告', '*.xlsx'),
                       ('Markdown 摘要', '*.md')],
            typevariable=report_filetype,
            initialfile='开关电源设计评审报告_Vinmin_Vinmax.docx',
            title='导出设计报告 (Export design report)')
        if not path:
            return
        # Some native save dialogs keep the initial .docx suffix after the
        # user selects Excel. Respect the chosen format in that case.
        selected_suffix = {'Excel 模块对照报告':'.xlsx','Markdown 摘要':'.md'}.get(report_filetype.get())
        if selected_suffix and os.path.splitext(path)[1].lower() in ('','.docx'):
            corrected = os.path.splitext(path)[0]+selected_suffix
            if os.path.exists(corrected) and not messagebox.askyesno(
                    '确认覆盖',f'文件已存在，是否覆盖？\n\n{corrected}',parent=self.root):
                return
            path = corrected
        try:
            L = self._last
            # Review targets share the design snapshot; keep the export copy
            # independent of the cached numerical results.
            report_params = self._report_input_parameters(L['p'])
            self.root.configure(cursor='watch')
            self.status_var.set('两端计算已准备；正在生成报告图表与排版，此阶段请稍候…')
            self.root.update_idletasks()
            if range_result is None:
                # Explicit synchronous API/batch callers retain their behavior;
                # all GUI buttons prepare this data through the worker first.
                range_result = _calculate_input_report(dict(p=report_params), lambda: False)
            range_result = dict(range_result,
                engineering_acceptance_evidence=self._acceptance_get_spice_evidence())
            for case in range_result['cases']:
                if case.get('p') is not None:
                    changed = [key for key in ('target_eta', 'fc_target', 'pm_target', 'winding_config')
                               if key in report_params and case['p'].get(key) != report_params[key]]
                    if changed:
                        raise ValueError('报告准备后评审目标或绕制设置已变化，请重新导出：'+', '.join(changed))
            if os.path.splitext(path)[1].lower() == '.md':
                sections = ['# 输入范围设计报告\n\n同一套器件，分别检查 Vin min 与 Vin max；补偿参数不自动重新整定。']
                for case in range_result['cases']:
                    sections.append(f"\n## {case['id']} — {case['voltage']:.6g} V\n")
                    if case.get('error'):
                        sections.append('计算未成功：'+str(case['error']))
                    else:
                        design = case['result']
                        sections.append(build_markdown_report(case['p'], design['op'], design['wf'], design))
                report = '\n'.join(sections)
                with open(path, 'w', encoding='utf-8-sig', newline='\n') as f:
                    f.write(report)
            else:
                excel = os.path.splitext(path)[1].lower() == '.xlsx'
                if not excel and os.path.splitext(path)[1].lower() != '.docx':
                    path += '.docx'
                if excel:
                    from report_xlsx import export_input_range_xlsx as export_design_report
                else:
                    from input_range_report import export_input_range_docx as export_design_report
                corners = self._corner_result
                if corners and (corners['base_spec'] != L['p'] or
                                tuple(corners['v_in']) != (self.corner_lo.get(),self.corner_hi.get())):
                    corners = None
                comparison = self._comparison
                if comparison and comparison['context_spec'] != L['p']:
                    comparison = None
                result = export_design_report(path, range_result, corners=corners, comparison=comparison,
                    compensation_state=self._comp_state(), mos_real_time=self.mos_real_time.get())
                failures = result['failed_cases']
                failure_count = len(failures) if isinstance(failures, (list, tuple)) else failures
                extra = (f"{result['sheet_count']} 个模块 Sheet，左侧 Vinmin，右侧 Vinmax。\n" if excel else '')
                cross = range_result.get('cross_regulation')
                if cross:
                    extra += (f"交叉调整率：{cross.get('successful_cases',0)} / {cross.get('total_cases',0)} 个负载角点有效。\n"
                              if cross.get('supported') else '交叉调整率：当前模型不支持，报告已列出原因。\n')
                messagebox.showinfo('Excel 设计报告' if excel else 'Word 设计报告',
                    f"已导出 Vin min / Vin max 两端报告：{result['successful_cases']} 个工况成功，"
                    f"{failure_count} 个工况失败。\n"
                    + extra +
                    f"共 {result['figure_count']} 张图表、{result['check_count']} 项核查；"
                    f"{'报告不完整，请查看失败工况。' if result['incomplete'] else '请查看总览对比与各工况详情。'}\n\n{path}")
            self.status_var.set(f'设计报告已导出: {os.path.basename(path)}')
        except Exception as e:
            messagebox.showerror('Export report', str(e))
        finally:
            self.root.configure(cursor='')

    def _apply_config(self, cfg):
        """Apply a loaded config dict (value + unit) to the UI parameters."""
        self._geometry_source=None
        cfg = dict(cfg)
        from inductor_selection import DEFAULTS as INDUCTOR_DEFAULTS
        for key, default in INDUCTOR_DEFAULTS.items():
            cfg.setdefault(key, default)
        from component_management import normalize_management
        component_data = normalize_management(cfg.get('component_management'))
        from engineering_acceptance import normalize as normalize_acceptance
        acceptance_data = normalize_acceptance(cfg.get('engineering_acceptance'))
        from acceptance_evidence_io import normalize_reference
        acceptance_reference = normalize_reference(cfg.get('__acceptance_evidence'))
        from spice_export import normalize_settings
        spice_data = normalize_settings(cfg.get('spice_config'))
        from parasitics import normalize as normalize_parasitics
        parasitic_data = normalize_parasitics(cfg['parasitic_config']) if cfg.get('parasitic_config') else {}
        # A missing transfer parameter means legacy fixed plateaus, never
        # the gfs left over from the previously opened device/configuration.
        cfg.setdefault('gfs', dict(v=0., u=''))
        from config_io import decode_config
        from device_curve_sources import validate_settings
        source_settings=validate_settings(cfg.get('device_curve_settings',{}))
        cfg.setdefault('mos_miller_mode',dict(v='auto',u=''))
        curve_mode=decode_config({'mos_miller_mode':cfg['mos_miller_mode']})['mos_miller_mode']
        if curve_mode not in ('auto','manual','curve','gfs'):raise ValueError('未知 MOS 平台来源')
        from mos_curves import validate_curve
        curve_data=validate_curve(cfg['mos_miller_curve']) if cfg.get('mos_miller_curve') else {}
        if not source_settings and curve_mode=='curve' and not curve_data:raise ValueError('曲线模式缺少 MOS 曲线数据')
        cfg.setdefault('mos_charge_mode',dict(v='manual',u=''))
        charge_mode=decode_config({'mos_charge_mode':cfg['mos_charge_mode']})['mos_charge_mode']
        if charge_mode not in ('manual','curve'):raise ValueError('未知栅电荷来源')
        from mos_gate_charge import validate_charge
        charge_data=validate_charge(cfg['mos_charge_curve']) if cfg.get('mos_charge_curve') else {}
        from diode_curves import validate_bank
        diode_data=validate_bank(cfg.get('diode_curves',{}))
        if not source_settings and charge_mode=='curve' and not charge_data:raise ValueError('栅电荷模式缺少 Vgs–Qg 曲线')
        gate_gfs = decode_config({'gfs': cfg['gfs']})['gfs']
        if curve_mode in ('auto','gfs') and (isinstance(gate_gfs, bool) or not isinstance(gate_gfs, (int, float)) or not np.isfinite(gate_gfs) or gate_gfs < 0):
            raise ValueError('MOS 有效跨导 gfs 必须为有限非负数，0 为固定平台模式')
        self._mos_miller_curve=curve_data
        self._mos_charge_curve=charge_data
        self._diode_curves=diode_data
        self._device_curve_settings=source_settings
        self._component_management=component_data
        self._engineering_acceptance=acceptance_data
        self._acceptance_range_result=None
        self._acceptance_evidence_reference=acceptance_reference
        self._acceptance_evidence_cache=None
        self._spice_config=spice_data
        self._parasitic_config=parasitic_data
        self._auto_design_basis=copy.deepcopy(cfg.get('__auto_design_basis'))
        self._transformer_simulation = copy.deepcopy(cfg.get('__transformer_simulation'))
        self._joint_simulation = copy.deepcopy(cfg.get('__joint_simulation'))
        if hasattr(self,'component_manager'):
            self.component_manager.current=None  # a new design must not inherit unapplied edits
        self._load_manual_events(cfg)
        cfg.setdefault('mos_curve_vds',dict(v=0.,u=''))
        # Legacy files carry a scalar, in their original value/unit format.
        # Preserve it exactly as a degenerate range rather than assuming +/-10%.
        if 'V_in_min' not in cfg and 'V_in_max' not in cfg:
            old = cfg.get('V_in', dict(v=DEFAULT_PARAMS['V_in'], u=''))
            cfg.update(V_in_min=old, V_in_max=old, input_voltage_case='min')
        elif 'V_in_min' not in cfg:
            cfg['V_in_min'] = cfg['V_in_max']
        elif 'V_in_max' not in cfg:
            cfg['V_in_max'] = cfg['V_in_min']
        cfg.setdefault('input_voltage_case', 'min')
        self._load_custom_core_config(cfg)
        self._load_winding_config(cfg)
        self._load_isolated_config(cfg)
        self._building = True
        self._param_auto_saved.clear()
        self.params['controller_type'].set('auto')
        for k, d in cfg.items():
            if k in ('K','Kc','dC'): k='rcd_'+k
            if k == 'V_in':
                continue  # derived from the canonical range and selected case
            if k == '__version__' or k not in self.params:
                continue
            var = self.params[k]
            try:
                if not isinstance(d,dict):
                    if isinstance(var,tk.DoubleVar) and k+'_unit' in self.params:
                        self.set_param(k,float(d))
                    else: var.set(d)
                    continue
                u = str(d.get('u', ''))
                if isinstance(var, tk.DoubleVar):
                    var.set(float(d['v'] if 'v' in d else var.get()))
                    uk = k + '_unit'
                    if uk in self.params:
                        self.params[uk].set(u)
                else:
                    var.set(d['v'] if 'v' in d else var.get())
            except Exception:
                pass
        if isinstance(cfg.get('__comp'), dict):
            self._apply_comp_state(cfg['__comp'])
        self.params['controller_type'].set(normalize_controller_type(self.params['controller_type'].get()))
        self._sync_curve_source_params()
        self._load_capacitor_parameters(cfg)
        # legacy configs saved with the removed LLC topology fall back to Buck
        if self._topo_key() not in TOPOLOGIES:
            self.params['topology'].set(TOPO_LABEL['BUCK'])
        # Loading may trigger view traces before all new values are assigned.
        # Rebuild hand-input caches solely from this configuration's final data.
        self._param_auto_saved.clear()
        self._refresh_param_rows()
        self._building = False
        self.on_topology_change(reset_target=False)
        self._on_controller_change()
        self.schedule_update()

    def load_config(self):
        path = filedialog.askopenfilename(
            filetypes=[('JSON config', '*.json')],
            title='打开电源参数配置 (Load parameter config)')
        if not path:
            return
        try:
            from pathlib import Path
            raw=Path(path).read_bytes()
            cfg=json.loads(raw.decode('utf-8-sig'))
            self._apply_config(cfg)
            self._geometry_source=(Path(path).name,raw)
            self.status_var.set(f'配置已加载: {os.path.basename(path)}')
        except Exception as e:
            messagebox.showerror('Load config', str(e))

    def load_forward_example(self):
        path = resource_path(os.path.join('examples', '40W_ACF_FORWARD.json'))
        try:
            with open(path, encoding='utf-8') as f:
                self._apply_config(json.load(f))
            self.request_update()
            self.status_var.set('已加载 40W 有源钳位正激: 30V → 30V, 250kHz；L 为独立输出电感')
        except Exception as e:
            messagebox.showerror('正激示例', str(e))

    # ------------------------------------------------------------ help dialogs
    def show_flow(self):
        flow = (
            '设计流程 (Design flow, 参照参考书 Erickson ch.2~12)\n'
            '────────────────────────────────────────\n'
            '① 拓扑示意\n'
            '   选择拓扑 → 核对连接、器件位号与当前参数\n'
            '② 功率级 & 波形  (ch.2/3)\n'
            '   填规格与 L/C/匝比 → 核对 CCM/DCM、占空比、\n'
            '   器件电流、输出纹波以及 Q1 的 t1–t8 开通 / 关断图\n'
            '③ 器件应力  (ch.4)\n'
            '   核对 MOSFET/二极管 Vds/Vr、Id/If 应力与损耗,\n'
            '   按 ≥1.2~1.5 倍裕量选型\n'
            '④ 磁件设计  (ch.10~12)\n'
            '   选磁芯/匝数/气隙/线径; 校核 Bpk < Bsat (饱和裕量)\n'
            '   变压器 ΔT = P×Ri-a，独立电感 ΔT = P/(h·A)\n'
            '⑤ 环路设计  (ch.8/9)\n'
            '   设定 fc≈fsw/10、PM≈60° → K因子自动整定;\n'
            '   核对 PM/GM/穿越频率, 注意 Boost/反激 RHP 零点\n'
            '⑥ 效率 & 优化  (ch.3)\n'
            '   损耗分解、效率-负载曲线、参数扫描/优化\n'
            '⑦ 电容纹波  ⑧ RCD / 有源钳位  ⑨ 补偿参数  ⑩ 工程评审\n'
            '\n完整说明书: Help → 中文说明书')
        tk.messagebox.showinfo('设计流程 (Design Flow)', flow)

    def open_calculation_reference(self):
        """Open the shipped calculation reference with the user's DOCX app."""
        self._open_help_document('计算方法与公式说明.docx', '计算说明')

    def open_design_tutorial(self):
        """Open the separate worked-example tutorial without regenerating it."""
        self._open_help_document('多路反激电源设计入门教程.docx', '入门教程')

    def open_initial_design(self):
        from initial_design_ui import show
        return show(self)

    def open_auto_design_basis(self):
        from design_engine.sizing_basis import DOCUMENT
        self._open_help_document(DOCUMENT, '自动计算参数依据')

    def _open_help_document(self, name, title):
        candidates = [os.path.join(os.path.dirname(sys.executable), name),
                      resource_path(name),
                      os.path.join(os.path.dirname(os.path.abspath(__file__)), name)]
        path = next((p for p in candidates if os.path.isfile(p)), None)
        if path is None:
            messagebox.showerror(title, f'未找到{name}，请保留完整程序目录。')
            return
        try:
            os.startfile(path)
        except Exception as exc:
            messagebox.showerror(title, f'无法打开文档，请确认已安装 Word 或 WPS。\n{exc}')

    def open_book(self):
        # search the exe folder, the PyInstaller bundle, then the source tree
        cand = [os.path.join(os.path.dirname(sys.executable), '参考资料',
                             'fundamentals of power electronics.pdf'),
                resource_path(os.path.join('参考资料',
                                           'fundamentals of power electronics.pdf')),
                os.path.join(os.path.dirname(os.path.abspath(__file__)),
                             '参考资料', 'fundamentals of power electronics.pdf')]
        path = next((p for p in cand if os.path.isfile(p)), None)
        if path is None:
            tk.messagebox.showinfo('参考书',
                                   '未找到参考书 PDF (fundamentals of power '
                                   'electronics.pdf)。把 参考资料/ 文件夹放到 exe 同目录即可。')
            return
        try:
            os.startfile(path)
        except Exception as e:
            tk.messagebox.showinfo('参考书', f'无法打开: {e}')

    def show_manual(self):
        return show_manual(self.root)

    def show_about(self):
        tk.messagebox.showinfo(
            'About (关于)',
            'Switching Power Supply Design & Loop Analyzer\n'
            '开关电源设计与环路分析工具\n\n'
            f'Version: {APP_VERSION} (参考书: Fundamentals of Power Electronics, '
            f'Erickson & Maksimović)\n'
            'Topologies: Buck / Boost / Buck-Boost / Flyback / QR-Flyback / ACF-Forward\n'
            '拓扑: 降压 / 升压 / 升降压 / 反激 / 准谐振反激 / 有源钳位正激\n\n'
            '设计检查: 电容纹波电流 / 器件应力 / 磁件饱和与温升 / 环路稳定\n'
            'Help (帮助) → 设计流程说明 (Design Flow)')

    # ------------------------------------------------------------ param panel
    def _add_section(self, parent, title):
        import re
        match = re.search(r'\(([^()]+)\)', title)
        title = match[1] if match else title
        container = ttk.Frame(parent)
        container.pack(fill='x', pady=3)
        header = ttk.Label(container, text='▼ '+title, style='TLabelframe.Label',
                           padding=(6, 4), takefocus=True, cursor='hand2')
        header.pack(fill='x')
        f = ttk.Frame(container, padding=6, relief='solid', borderwidth=1)
        f.pack(fill='x')
        f._section_container, f._section_header, f._section_title = container, header, title
        header.bind('<Button-1>', lambda _e: self._fold_section(f))
        header.bind('<Return>', lambda _e: self._fold_section(f))
        header.bind('<space>', lambda _e: self._fold_section(f))
        Tooltip(header, '点击标题折叠 / 展开；搜索会临时展开匹配内容。')
        return f

    def _param_row(self, parent, row, key, label, units):
        return ParameterPanelUI._param_row(self, parent, row, key, label, units)

    def _build_param_panel(self, parent):
        return ParameterPanelUI._build_param_panel(self, parent, PARAM_SPECS, TOPO_LABEL, CTRL_LABEL)

    def on_material_change(self):
        m = self.mat_combo.get()
        if m in mag.STEINMETZ_MATERIALS:
            d = mag.STEINMETZ_MATERIALS[m]
            self.params['k_core'].set(d['k'])
            self.params['a_core'].set(d['a'])
            self.params['b_core'].set(d['b'])

    def on_core_shape_change(self):
        """First level of the core picker: shape -> refresh the model list."""
        shape = self.params['core_shape'].get()
        models = (['auto'] + mag.core_model_list(shape)
                  if shape != 'auto' else ['auto'] + list(mag.CORE_DB.keys()))
        models.insert(1,mag.CUSTOM_CORE)
        self.core_combo.configure(values=models)
        if self.params['core_choice'].get() not in models:
            self.params['core_choice'].set('auto')

    def on_core_model_change(self):
        """Second level: keep the shape consistent with a chosen model."""
        model = self.params['core_choice'].get()
        if model == 'auto':
            return
        for sh, models in mag.CORE_SHAPES.items():
            if model in models:
                self.params['core_shape'].set(sh)
                break

    def on_topology_change(self, reset_target=True):
        if self._building:
            return
        topo = self._topo_key()
        # default tuning target: fsw/10
        try:
            fs = self.get_param('f_sw')
        except (ValueError, tk.TclError):
            fs = 0  # keep the previous target while an edit is incomplete
        if fs > 0 and reset_target:
            fc = fs/10
            if topo == 'ACF-FORWARD':
                try:
                    fc = compute_operating_point(self.get_params())['fc_recommended_max']
                except (ValueError, tk.TclError):
                    pass
            self.set_param('fc_target', fc)
        # Parameter filtering owns section visibility/order, including the
        # forward-only group while a search hides neighbouring sections.
        self._sync_topology_pages()
        self.rcd_input_frame.configure(text=(
            '有源钳位参数请在左栏编辑 (Lm / C_clamp / 死区 / 辅助 MOSFET)'
            if topo == 'ACF-FORWARD' else
            'RCD 参数在左栏“功率级与钳位”编辑；本页只显示结果'))
        self.guide_rcd.configure(text=(
            '有源钳位正激: 低侧钳位复位电压 / 辅助 MOSFET / 励磁电流 / 谐振与带宽限制'
            if topo == 'ACF-FORWARD' else
            'RCD 吸收钳位 (反激原边漏感): K / Kc / ΔC'))
        # update sweep options
        self.sweep_combo.configure(values=[l for _k, l in SWEEP_OPTIONS.get(topo, SWEEP_OPTIONS['BUCK'])])
        self.sweep_combo.set(SWEEP_OPTIONS.get(topo, SWEEP_OPTIONS['BUCK'])[0][1])
        # step guides
        self.guide_power.configure(text=STEP_GUIDE[0])
        self.guide_stress.configure(text=STEP_GUIDE[1])
        self.guide_mag.configure(text=STEP_GUIDE[2])
        self.guide_loop.configure(text=STEP_GUIDE[3])
        self.guide_eff.configure(text=STEP_GUIDE[4])
        self._filter_params()

    def _sync_topology_pages(self):
        """Hide incompatible pages without changing their lazy-render indexes."""
        if not hasattr(self, 'tab_comp'):
            return
        topo = self._topo_key()
        if hasattr(self, 'mag_nb'):
            winding_supported = topo in ('FLYBACK', 'QR-FLYBACK', 'ACF-FORWARD')
            if not winding_supported and self.mag_nb.select() == str(self.tab_mag_winding):
                self.mag_nb.select(self.tab_mag_design)
            self.mag_nb.tab(self.tab_mag_winding,
                            state='normal' if winding_supported else 'hidden')
            if winding_supported:
                self.mag_simulation_button.pack(side='right', padx=5)
            else:
                self.mag_simulation_button.pack_forget()
        pfm = bool(self._psr_active() and self._snapshot_valid and self._last
                   and self._last['p'].get('feedback_mode') == 'PSR-MP6005'
                   and self._last['op'].get('regulation_region') == 'PFM-estimate')
        states = {
            self.tab_rcd: topo in ('FLYBACK', 'QR-FLYBACK', 'ACF-FORWARD'),
            self.tab_comp: not self._psr_active(),
            self.tab_loop: not pfm,
        }
        selected = self.nb.select()
        if selected and any(str(tab) == selected and not shown for tab, shown in states.items()):
            self.nb.select(self.tab_topology)
        for tab, shown in states.items():
            state = 'normal' if shown else 'hidden'
            if self.nb.tab(tab, 'state') != state:
                self.nb.tab(tab, state=state)
        self.nb.tab(self.tab_rcd, text=' ⑧ 有源钳位 ' if topo == 'ACF-FORWARD' else ' ⑧ RCD钳位 ')
        self._sync_inline_output_context()

    def _rcd_parameters(self):
        if self._topo_key() in ('FLYBACK', 'QR-FLYBACK'):
            matrix = bool(hasattr(self,'coupling_enabled') and self.coupling_enabled.get()
                          and self._topo_key()=='FLYBACK' and self._effective_feedback_mode()=='SSR')
            return dict(K=.95 if matrix else float(self.rcd_K.get()), Kc=float(self.rcd_Kc.get()),
                        dC=min(max(float(self.rcd_dC.get()), 0.0), 1.0))
        return dict(K=0.95, Kc=1.5, dC=0.10)

    def _sweep_key(self):
        topo = self._topo_key()
        opts = SWEEP_OPTIONS.get(topo, SWEEP_OPTIONS['BUCK'])
        label = self.sweep_combo.get()
        for k, l in opts:
            if l == label:
                return k
        return opts[0][0]

    # ------------------------------------------------------------ actions
    def schedule_update(self):
        if self._building or self._closing:
            return
        self._calculation_worker.invalidate()
        self._export_after_calculation = False
        self._snapshot_valid = False
        if hasattr(self,'component_manager'):
            self.component_manager.mark_stale()
        self._refresh_param_summaries()
        self._sync_device_curve_controls()
        if hasattr(self, '_sync_corner_input_range'):
            self._sync_corner_input_range()
        self._mark_winding_stale()
        self._mark_transformer_readouts_stale()
        self._mark_cross_regulation_stale()
        self._mark_mos_gate_stale()
        self._eff_curve_signature = None
        self._eff_curve_result = None
        self._loop_result = None
        self._loop_signature = None
        self._loop_error = None
        self._loop_models = None
        self._loop_tune_pending = None
        for var in getattr(self, 'margin_info', {}).values():
            var.set('环路: 待计算')
        if hasattr(self, 'review_summary'):
            self.review_summary.set('参数已变化，检查结果待重新计算。')
        self._invalidate_workflows()
        if self.update_timer is not None:
            self.root.after_cancel(self.update_timer)
        # The coupled solver is substantially more costly than the nominal
        # analytical model; a longer debounce coalesces an entire edit gesture.
        heavy = bool(hasattr(self, 'coupling_enabled') and self.coupling_enabled.get()
                     and self._coupling_supported())
        self.update_timer = self.root.after(700 if heavy else self.update_delay,
                                            self.request_update)

    def _calculation_window_destroyed(self, event):
        if event.widget is self.root:
            self._calculation_worker.close()

    def _ensure_calculation_poll(self):
        if self._calculation_poll_job is None and not self._closing:
            self._calculation_poll_job = self.root.after(50, self._poll_calculations)

    def request_update(self, *, preserve_export=False):
        """UI entry: Tk reads inputs; the numerical worker never sees widgets."""
        if self._closing:
            return False
        ready_job = getattr(self, '_design_ready_job', None)
        if ready_job is not None:
            self.root.after_cancel(ready_job)
            self._design_ready_job = None
        self._mark_cross_regulation_stale()
        self._mark_mos_gate_stale()
        if not preserve_export:
            self._export_after_calculation = False
        if self.update_timer is not None:
            self.root.after_cancel(self.update_timer)
            self.update_timer = None
        try:
            p = self.get_params()
            p.update(self._rcd_parameters())
            self._snapshot_valid = False
            self._mark_winding_stale()
            from input_voltage_range import calculate_input_operating_point
            import threading
            ready = threading.Event()
            if self._param_layout_job is not None:
                # Finish the current input-panel reflow before a CPU-heavy
                # worker competes with thousands of Tcl geometry callbacks.
                # Never run update()/update_idletasks() recursively here.
                def allow_calculation():
                    self._design_ready_job = None
                    ready.set()
                def after_layout():
                    self._design_ready_job = self.root.after(40, allow_calculation)
                self._design_ready_job = self.root.after_idle(after_layout)
            else:
                ready.set()

            def calculate(snapshot, cancelled):
                while not ready.wait(.02):
                    if cancelled():
                        raise CalculationCancelled()
                return calculate_input_operating_point(snapshot, cancelled=cancelled)

            self._calculation_worker.submit('design', p,
                calculate, cache=True)
            self.status_var.set('正在后台计算设计… 可继续编辑；仅应用最新参数的结果。')
            self._ensure_calculation_poll()
            return True
        except Exception as error:
            self._calculation_worker.invalidate()
            self._show_calculation_error(error)
            self._export_after_calculation = False
            return False

    def _poll_calculations(self):
        self._calculation_poll_job = None
        if self._closing:
            return
        try:
            self._drain_cross_progress()
            while True:
                result = self._calculation_worker.results.get_nowait()
                if not self._calculation_worker.is_current(result.generation):
                    continue
                if result.kind == 'design':
                    if result.error is not None:
                        self._show_calculation_error(result.error)
                        self._export_after_calculation = False
                        continue
                    self._publish_design(result.parameters, result.value['res'],
                                         calculation_params=result.value['p'])
                    if self._export_after_calculation:
                        self._queue_report_efficiency_curve()
                elif result.kind == 'acceptance_endpoints':
                    from engineering_acceptance import input_fingerprint
                    if result.error is not None:
                        self.status_var.set('验收两端计算失败：'+str(result.error))
                    elif input_fingerprint(result.parameters['p']) == input_fingerprint(self._current_spec()):
                        self._acceptance_range_result = result.value
                        self.status_var.set('验收两端计算已更新；仿真和实测仍按各自证据判定。')
                    if hasattr(self, 'acceptance_panel'):
                        self.acceptance_panel.refresh()
                elif result.kind == 'report_input_range':
                    if not self._export_after_calculation:
                        continue
                    self._export_after_calculation = False
                    self._rendered_tabs.discard(self.nb.index(self.tab_eff))
                    if not self._snapshot_valid or self._last is None or result.parameters['p'] != self._last['p']:
                        continue
                    if result.error is not None:
                        self.status_var.set(f'两端报告数据计算失败: {result.error}')
                        continue
                    def export_when_current(job=result):
                        if (not self._closing and self._snapshot_valid
                                and self._calculation_worker.is_current(job.generation)
                                and self._last is not None and job.parameters['p'] == self._last['p']):
                            self.export_report(recompute=False, range_result=job.value)
                    self.root.after_idle(export_when_current)
                elif result.kind == 'efficiency':
                    if not self._snapshot_valid or self._last is None:
                        continue
                    if parameter_signature(result.parameters) != parameter_signature(self._last.get('calculation_params', self._last['p'])):
                        continue
                    if result.error is not None:
                        self._eff_curve_result = dict(error=str(result.error))
                    else:
                        self._eff_curve_result = result.value
                    self._render_efficiency_curve()
                    _draw_canvas(self.canvas_loss)
                elif result.kind == 'coupled_loop':
                    self._finish_coupled_loop(result)
                elif result.kind == 'cross_regulation':
                    self._finish_cross_regulation(result)
                elif result.kind in ('sweep', 'target', 'optimize'):
                    self._finish_optimization_job(result)
        except queue.Empty:
            pass
        except Exception as error:
            # A plotting/presentation failure must not kill the job poller.
            self.status_var.set(f'显示计算结果: {error}')
        if self._calculation_worker.busy or not self._calculation_worker.results.empty():
            self._ensure_calculation_poll()

    def _tab_updaters(self):
        """Zero-arg refreshers in notebook order, reading the latest design."""
        L = self._last
        engine_p = L.get('calculation_params', L['p'])
        return (
            lambda: self._update_topology(L['op'], engine_p),
            lambda: self._update_power(L['op'], L['wf'], L['res'], engine_p),
            lambda: self._update_stress(L['op'], L['res']),
            lambda: self._update_mag(L['op'], engine_p, L['res'], L['wf']),
            lambda: self._update_loop(L['p']),
            lambda: self._update_eff(L['op'], engine_p, L['res']),
            lambda: self._update_cap(L['op'], engine_p, L['res']),
            lambda: self._update_rcd(L['op'], engine_p),
            lambda: self._update_comp(L['op'], engine_p),
            self._update_review,
        )

    def _refresh_visible_tab(self):
        """Redraw only the visible notebook tab.  update_all() clears
        _rendered_tabs on every design change, so the visible tab always
        redraws there and the others render on their first visit."""
        if self._last is None or not self._snapshot_valid:
            return
        try:
            idx = self.nb.index(self.nb.select())
        except Exception:
            return
        if idx in (4,9) and not self._control_ready:
            if 'control' in sys.modules:
                self._control_ready=True
            else:
                self._start_control_warmup()
                if idx==4:
                    self.loop_esr_note.set('正在按需加载环路分析库… 可切换页面继续操作。')
                    return
        if idx in self._rendered_tabs:
            return
        self._rendered_tabs.add(idx)
        try:
            # Review must complete current loop checks even when the library
            # was loaded on an earlier design but hidden during this solve.
            if (idx==9 and self._control_ready and
                    parameter_signature(self._last['p'])!=self._loop_signature):
                self._update_loop(self._last['p'],draw=False)
            self._tab_updaters()[idx]()
        except Exception as e:
            self.status_var.set(f'Refresh: {e}')

    # ------------------------------------------------------------ compute
    def calculate_transfer_functions(self, p, op=None):
        from plants import build_loop_models
        if self._snapshot_valid and self._last and p == self._last['p']:
            p = self._last.get('calculation_params', p)
            op = self._last['op'] if op is None else op
        elif op is None:
            from input_voltage_range import calculate_input_operating_point
            snapshot = calculate_input_operating_point(p)
            p, op = snapshot['p'], snapshot['op']
        models, self._last_plant = build_loop_models(p, op)
        return models

    # ------------------------------------------------------------ update
    def update_all(self):
        """Synchronous API retained for batch callers and existing test tools.

        UI controls use request_update(); an identical successful design is
        re-used here, so explicit report exports do not repeat a physical solve.
        """
        if self.update_timer is not None:
            self.root.after_cancel(self.update_timer)
            self.update_timer = None
        self._calculation_worker.invalidate()
        self._export_after_calculation = False
        try:
            p = self.get_params()
            # feed the RCD (RC) clamp choice into the design so the device
            # stress (clamped drain peak) and the loss breakdown (snubber
            # resistor power) reflect the selected K / Kc / dC on the RCD tab.
            p.update(self._rcd_parameters())
            if self._last is not None and self._last['p'] == p:
                res = self._last['res']
                calculation_params = self._last.get('calculation_params', p)
            else:
                snapshot = self._calculation_worker.cached('design', p)
                if snapshot is None:
                    from input_voltage_range import calculate_input_operating_point
                    snapshot = calculate_input_operating_point(p)
                    self._calculation_worker.remember('design', p, snapshot)
                res, calculation_params = snapshot['res'], snapshot['p']
            return self._publish_design(p, res, calculation_params=calculation_params)
        except Exception as error:
            self._show_calculation_error(error)
            return False

    def _publish_design(self, p, res, calculation_params=None):
        """Only Tk's main thread may apply a numerical result to the interface."""
        try:
            op, wf = res['op'], res['wf']
            if self._eff_curve_result is None:
                # A manual recalculation may have superseded a pending curve.
                self._eff_curve_signature = None

            # status bar
            topo_label = TOPO_LABEL.get(op['topology'], op['topology'])
            if p['topology'] == 'QR-FLYBACK':
                f_ok = op['f_sw'] <= op['f_max']
                self.status_var.set(
                    f"{topo_label}: fsw(计算)={fmt_eng(op['f_sw'], 'Hz')}  "
                    f"mode=BCM(准谐振)  D={op['D']:.3f}  I_pk={fmt_eng(op['I_L_pk'], 'A')}  "
                    f"V_r={fmt_eng(op['V_r'], 'V')}  "
                    f"{'✓ f_sw ≤ f_max' if f_ok else '⚠ f_sw 超 f_max 限制!'}  "
                    f"η={res['eta'] * 100:.1f}% (模型估算, 未计附加损耗)")
            else:
                dcm_note = '  [DCM · 环路工作条件见环路页]' if op['mode'] == 'DCM' else ''
                self.status_var.set(
                    f"{topo_label}: D={op['D']:.3f}  mode={op['mode']}  "
                    f"dI_L={fmt_eng(op['dI_L'], 'A')}  I_L_pk={fmt_eng(op['I_L_pk'], 'A')}  "
                    f"ripple={fmt_eng(wf['ripple_pp'], 'V')}  eta={res['eta'] * 100:.1f}%"
                    f" (模型估算, 未计附加损耗)"
                    + dcm_note + (' · 逐对耦合 / 恒阻负载近似' if op.get('coupled_model') else ''))

            # toolbar loop margins: cheap numbers only, kept fresh on every
            # design change; the ④ Bode plots redraw only when that tab shows.
            # Skipped while the lazy `control` import has not finished (the
            # background warm-up or the first ④ visit fills them in).
            calculation_params = calculation_params or p
            # Review records do not change the electrical solve. Keep the
            # published wrapper current without mutating cached input dicts.
            p = dict(p, engineering_acceptance=copy.deepcopy(self._engineering_acceptance))
            calculation_params = dict(calculation_params,
                engineering_acceptance=copy.deepcopy(self._engineering_acceptance))
            self._last = dict(op=op, wf=wf, res=res, p=p, calculation_params=calculation_params)
            self._prune_output_result_cards(res)
            self._update_isolated_results(calculation_params,res)
            self._update_transformer_electrical_readouts(calculation_params,res)
            self._update_mos_gate_readout(res)
            self._snapshot_valid = True
            self._update_diode_result_readout(res)
            self._refresh_param_summaries()
            self._sync_topology_pages()
            from design_checks import check_catalog
            self._last['checks'] = check_catalog(calculation_params, res)
            if self._control_ready and self.nb.index(self.nb.select()) in (4,9):
                self._update_loop(p, draw=False)
            self._last_design = res
            self._update_review()
            # redraw ONLY the visible tab; the others refresh on first visit
            self._rendered_tabs.clear()
            self._refresh_visible_tab()
            return True
        except Exception as error:
            self._show_calculation_error(error)
            return False

    def _show_calculation_error(self, error):
        self.status_var.set(f'Error: {error}')
        self._snapshot_valid = False
        self._mark_winding_stale()
        self._mark_transformer_readouts_stale()
        self._mark_mos_gate_stale()
        self._loop_result = None
        self._loop_signature = None
        for var in self.margin_info.values():
            var.set('环路: 未计算')
        self.loop_esr_note.set(str(error))
        for axis in self.ax_loop.flat:
            axis.clear()
            axis.text(.5, .5, '参数无效，环路结果已清空', ha='center', va='center',
                      transform=axis.transAxes)
        _draw_canvas(self.canvas_loop)
        self._invalidate_workflows()
        self._clear_review(str(error))

    # ============================================================ ① topology
    def _build_topology_tab(self):
        f = self._build_isolated_controls(self.tab_topology)
        ttk.Button(f, text='仿真与报告中心 · 变压器 / 控制器 / 联合导出…', command=self._export_joint_ui).pack(anchor='e',padx=8,pady=4)
        from component_ui import ComponentManager
        component_page = ttk.Frame(self._isolated_result_book)
        self._component_page = component_page
        self._isolated_result_book.insert(1, component_page, text='关键器件 BOM 与降额')
        from scrollable_results import ScrollableResults
        self._component_scroll = ScrollableResults(component_page)
        self._component_scroll.pack(fill='both',expand=True)
        self.component_manager = ComponentManager(self._component_scroll.content, self._component_context, self._component_changed)
        self._isolated_result_book.bind('<<NotebookTabChanged>>', lambda _e: self._refresh_components(), add='+')
        guide = ttk.Frame(f, style='Guide.TFrame', padding='8 5')
        guide.pack(fill='x', pady=2)
        ttk.Label(guide, text='拓扑参考图：随当前拓扑与可选器件更新。Q1 对应②页的 Vgs / Vds；下表将位号映射到软件参数。',
                  style='Guide.TLabel', wraplength=1000).pack(anchor='w')
        self.topology_stats = tk.StringVar()
        ttk.Label(f, textvariable=self.topology_stats, style='Margin.TLabel').pack(anchor='w', padx=8, pady=3)
        self.fig_topology, self.ax_topology = _subplots(figsize=(11.5, 4.4))
        self.fig_topology.subplots_adjust(left=.02, right=.98, bottom=.02, top=.98)
        self.canvas_topology = FigureCanvasTkAgg(self.fig_topology, master=f)
        self.canvas_topology.get_tk_widget().pack(fill='both', expand=True)
        box = ttk.LabelFrame(f, text='器件位号 ↔ 当前计算参数（表内可滚动）', padding=4)
        box.pack(fill='x', padx=4, pady=4)
        self.topology_tree = ttk.Treeview(box, columns=('ref', 'role', 'values'), show='headings', height=5)
        for key, label, width in (('ref', '位号', 95), ('role', '器件 / 用途', 310), ('values', '参数与当前值', 600)):
            self.topology_tree.heading(key, text=label)
            self.topology_tree.column(key, width=width, minwidth=70, anchor='w', stretch=key != 'ref')
        scroll = ttk.Scrollbar(box, orient='vertical', command=self.topology_tree.yview)
        self.topology_tree.configure(yscrollcommand=scroll.set)
        self.topology_tree.bind('<Double-1>', self._open_component_manager)
        scroll.pack(side='right', fill='y'); self.topology_tree.pack(fill='x', expand=True)
        ttk.Label(f, text='工程示意，非可生产原理图；未展开驱动 / 控制器、ESR / ESL 与寄生参数。防反压降与采样电阻仍按原模型仅计损耗。',
                  style='Muted.TLabel', wraplength=1100).pack(anchor='w', padx=8, pady=(0, 4))

    def _update_topology(self, op, p):
        from topology_diagram import draw_topology
        rows = draw_topology(self.ax_topology, p,op)
        self.topology_stats.set(f"{TOPO_LABEL.get(op['topology'], op['topology'])}  ·  "
                                f"Vin={fmt_eng(op['V_in'], 'V')} → |Vout|={fmt_eng(op['V_out'], 'V')}  ·  "
                                f"{fmt_eng(op['P_out'], 'W')}  /  {fmt_eng(op['f_sw'], 'Hz')}")
        self.topology_tree.delete(*self.topology_tree.get_children())
        for row in rows:
            self.topology_tree.insert('', 'end', iid=row['ref'], values=(row['ref'], row['role'], row['values']))
        _draw_canvas(self.canvas_topology)
        self._refresh_components()

    def _component_context(self):
        if self._snapshot_valid and self._last:
            # The table is a view of the published electrical snapshot. Reading
            # hundreds of live Tk fields here competes with the numerical
            # worker for the GIL and can stall a notebook change for seconds.
            p = dict(self._last.get('calculation_params', self._last['p']),
                     component_management=copy.deepcopy(self._component_management))
            return p, self._last['res']
        p = self.get_params(check_curve_sources=False)
        p.update(self._rcd_parameters())
        res = self._last['res'] if self._snapshot_valid and self._last else None
        return p, res

    def _export_joint_ui(self):
        """One entry for transformer extraction, circuit setup and joint export."""
        try:
            if self._topo_key() not in ('FLYBACK', 'QR-FLYBACK', 'ACF-FORWARD'):
                return self._export_spice_ui()
            from joint_simulation_ui import show
            return show(self)
        except Exception as exc:
            messagebox.showerror('仿真与报告中心',str(exc),parent=self.root)

    def _export_spice_ui(self,comparison=False):
        try:
            p=self.get_params(check_curve_sources=False)
            p.update(self._rcd_parameters())
            from spice_ui import open_export_dialog
            def apply(data):
                self._spice_config=__import__('copy').deepcopy(data)
                self.schedule_update()
                self.status_var.set('SPICE 设置已应用；保存设计 JSON 可保留设置。')
            def latest():
                current=self.get_params(check_curve_sources=False);current.update(self._rcd_parameters());return current
            open_export_dialog(self.root,p,apply,get_parameters=latest,initial_tab='测试与对比报告' if comparison else None)
        except Exception as exc:
            messagebox.showerror('LTspice 导出',str(exc),parent=self.root)

    def _refresh_components(self):
        if hasattr(self, 'component_manager'):
            if not self._snapshot_valid:
                # A tab-change event may arrive while loading/solving a design.
                # Do not reread partially edited inputs or show stale verdicts.
                self.component_manager.mark_stale()
                return
            try: self.component_manager.refresh()
            except (ValueError, tk.TclError): pass  # unfinished electrical inputs; no fake passing result

    def _component_changed(self, data):
        import copy
        self._component_management = copy.deepcopy(data)
        # Metadata-only changes reuse solved currents/voltages, avoiding a costly
        # coupled multi-winding solve. All projections and exports see new ratings.
        if self._last and self._snapshot_valid:
            for key in ('p','calculation_params'):
                if key in self._last:
                    self._last[key] = dict(self._last[key], component_management=copy.deepcopy(data))
            from design_checks import check_catalog
            self._last['res']['checks'] = check_catalog(self._last['p'], self._last['res'], self._last['res'].get('loop'))
            self._rendered_tabs.discard(9)
        self.status_var.set('关键器件资料/降额规则已应用；请保存设计 JSON。未重复求解功率级。')

    def _open_component_manager(self, _event=None):
        self._isolated_result_book.select(self._component_page)
        self._refresh_components()
        selected = self.topology_tree.selection()
        if selected and selected[0] in self.component_manager.rows:
            self.component_manager.tree.selection_set(selected[0])

    # ============================================================ ② power tab
    def _build_power_tab(self):
        f = self._build_results_scroll(self.tab_power, 'power')
        top = ttk.Frame(f, style='Guide.TFrame', padding='8 4')
        top.pack(fill='x', pady=(2, 4))
        self.guide_power = self._result_label(top, text=STEP_GUIDE[0],
                                     style='Guide.TLabel')
        self.guide_power.pack(fill='x')

        options = ttk.Frame(f)
        options.pack(fill='x', padx=8)
        self.mos_real_time = tk.BooleanVar(value=False)
        ttk.Checkbutton(options, text='MOS 图使用真实时间轴（默认按阶段展开，便于查看短分段）',
                        variable=self.mos_real_time, command=self._redraw_power).pack(side='left')

        stats = ttk.Frame(f)
        stats.pack(fill='x', pady=2)
        self.power_stats = tk.StringVar(value='')
        self._result_label(stats, textvariable=self.power_stats,
                           style='Margin.TLabel').pack(fill='x')

        self.fig_power, self.ax_power = _subplots(2, 3, figsize=(11.5, 6.6))
        self.ax_power_drain = tuple(ax.twinx() for ax in self.ax_power.ravel()[-2:])
        self.canvas_power = FigureCanvasTkAgg(self.fig_power, master=f)
        self.canvas_power.get_tk_widget().pack(fill='both', expand=True)
        self._bind_result_overview('power', self.canvas_power)

        chk = ttk.Frame(f, style='Guide.TFrame', padding='8 4')
        chk.pack(fill='x', pady=(4, 0))
        ttk.Label(chk, text='设计检查 (Design checks):',
                  style='Guide.TLabel').pack(anchor='w')
        self.power_checks = tk.StringVar(value='')
        self._result_label(chk, textvariable=self.power_checks, style='Guide.TLabel').pack(fill='x', padx=8)

        self.mos_notes = tk.StringVar()
        self._result_label(f, textvariable=self.mos_notes, style='Muted.TLabel').pack(fill='x', padx=8, pady=3)
        self.parasitic_host=ttk.LabelFrame(f,text='寄生换流 · 独立局部估算',padding=8)
        self.parasitic_note=tk.StringVar()
        self._result_label(self.parasitic_host,textvariable=self.parasitic_note,style='Muted.TLabel').pack(fill='x')
        self.fig_parasitic=None
        self.canvas_parasitic=None
        self._build_output_result_host(f, 'power')

    def _redraw_power(self):
        if self._last is not None and self._snapshot_valid:
            L = self._last
            self._update_power(L['op'], L['wf'], L['res'], L['p'])

    def _update_power(self, op, wf, res, p):
        try:
            topo = op['topology']
            self._prepare_result_overview('power')

            if topo == 'QR-FLYBACK':
                stats = (f"fsw(计算)={fmt_eng(op['f_sw'], 'Hz')}  变频·BCM  "
                         f"D={op['D']:.3f}  I_pk={fmt_eng(op['I_L_pk'], 'A')}  "
                         f"V_r={fmt_eng(op['V_r'], 'V')}  "
                         f"T_ring={op['T_ring'] * 1e6:.2f} us  "
                         f"η={res['eta'] * 100:.1f}% (模型估算, 未计附加损耗)")
            else:
                stats = (f"D={op['D']:.3f}  mode={op['mode']}  "
                         f"ΔiL={fmt_eng(op['dI_L'], 'A')}  I_L_pk={fmt_eng(op['I_L_pk'], 'A')}  "
                         f"V_out ripple={fmt_eng(wf['ripple_pp'], 'V')}  "
                         f"η={res['eta'] * 100:.1f}% (模型估算, 未计附加损耗)")
                if op['mode'] == 'DCM':
                    stats += '  ⚠ DCM (轻载或 L 偏小)'
            self.power_stats.set(f"预设η={op['eta_guess']*100:.1f}%  " + stats)
            if res.get('outputs'):
                self.power_stats.set(self.power_stats.get()+f" · 总输出 {op['P_out']:g} W / {len(res['outputs'])} 路；上述纹波为 OUT{op['feedback_output']}，下方为全部各路详情。")

            from power_charts import draw_power_signals, draw_power_switching
            if res.get('outputs'):
                from multi_output_charts import draw_shared_power_signals
                draw_shared_power_signals(self.ax_power.ravel()[:4], op, wf)
            else:
                draw_power_signals(self.ax_power.ravel()[:4], topo, wf)
            self._mos_voltage_data = draw_power_switching(
                self.ax_power.ravel()[-2:], op, p, res,
                real_time=self.mos_real_time.get(), drain_axes=self.ax_power_drain)
            self.mos_notes.set('  '.join(self._mos_voltage_data['notes']))
            data=op.get('parasitics') or {}
            if data.get('edges'):
                if self.fig_parasitic is None:
                    self.fig_parasitic=Figure(figsize=(10,5),dpi=100)
                    self.canvas_parasitic=FigureCanvasTkAgg(self.fig_parasitic,master=self.parasitic_host)
                    self.canvas_parasitic.get_tk_widget().pack(fill='both',expand=True)
                self.parasitic_host.pack(fill='both',expand=True,padx=8,pady=8)
                self.parasitic_note.set(data['scope'])
                self.fig_parasitic.clear();self.fig_parasitic.set_size_inches(10,2.8*len(data['edges']))
                self.canvas_parasitic.get_tk_widget().configure(height=280*len(data['edges']))
                from parasitic_ringing import draw
                draw(self.fig_parasitic,data);_draw_canvas(self.canvas_parasitic)
            else:self.parasitic_host.pack_forget()
            self._scale_result_text('power')
            self.fig_power.set_layout_engine('tight',pad=1.0,h_pad=1.6,w_pad=1.6)
            _draw_canvas(self.canvas_power)
            self.power_checks.set(self._power_checks(op, wf, res, p))
            self._update_output_result_cards('power', op, res)
        except Exception as e:
            import traceback
            traceback.print_exc()
            self.status_var.set(f'Power: {e}')

    @staticmethod
    def _power_checks(op, wf, res, p):
        """Steady-state design checklist (Erickson ch.2/3 + ripple-current)."""
        from design_checks import check_catalog
        catalog = {c['id']:c for c in check_catalog(p,res,res.get('loop'))}
        from isolated_outputs import selected_params
        p=selected_params(p)
        out = []
        topo = op['topology']
        if op['mode'] == 'BCM':                    # QR flyback (variable f)
            f_ok = op['f_sw'] <= op['f_max']
            C_ok = __import__('capacitor_banks').total(op) >= op['C_min']
            out.append(
                f"准谐振 BCM: 工作频率 f_sw(计算) = {fmt_eng(op['f_sw'], 'Hz')}  "
                f"(f_max 限制 = {fmt_eng(op['f_max'], 'Hz')}) "
                f"{'✓' if f_ok else '⚠ 超频: 减小 Lm/增大 N/限制负载范围'}  |  "
                f"C={fmt_eng(op['C_out'], 'F')} {'≥' if C_ok else '<'} "
                f"C_min={fmt_eng(op['C_min'], 'F')} {'✓' if C_ok else '⚠'}")
            out.append(
                f"频率组成: T_on={op['T_on'] * 1e6:.2f}us + "
                f"T_demag={op['T_demag'] * 1e6:.2f}us + "
                f"T_ring=π√(Lm·Coss)={op['T_ring'] * 1e6:.2f}us  |  "
                f"反射电压 V_r={fmt_eng(op['V_r'], 'V')}  "
                f"谷底延迟用 Coss={p['Coss'] * 1e12:.0f} pF (器件参数)")
            if np.isfinite(op['rhp_zero']):
                out.append(f"RHP 零点 = {fmt_eng(op['rhp_zero'], 'Hz')} → 环路 fc 应 ≪ "
                           f"{fmt_eng(op['rhp_zero'] / 5, 'Hz')}  (变频 COt 控制建议用峰值电流模式)")
            else:
                out.append("RHP 零点 = 无 (准谐振 BCM 无右半平面零点) → fc 不受 RHP 限制")
        else:
            ok_mode = op['mode'] == 'CCM'
            L_check = catalog['L_min']
            L_ok = L_check['state'] in ('pass','na')
            L_result = '不适用' if L_check['state']=='na' else ('✓' if L_ok else '⚠ 初选建议')
            L_meaning = '纹波初选' if topo=='FLYBACK' else 'CCM 初选'
            C_ok = __import__('capacitor_banks').total(op) >= op['C_min']
            r_ok = wf['ripple_pp'] <= p['ripple_target'] * op['V_out']
            out.append(
                f"模式 mode={op['mode']} "
                f"{'✓' if ok_mode else '⚠ DCM'}  |  "
                f"L={fmt_eng(op['L'], 'H')}; L_min({L_meaning})={fmt_eng(op['L_min'], 'H')} "
                f"{L_result}  |  "
                f"C(总)={fmt_eng(__import__('capacitor_banks').total(op), 'F')} {'≥' if C_ok else '<'} C_min={fmt_eng(op['C_min'], 'F')} "
                f"{'✓' if C_ok else '⚠'}  |  "
                f"纹波={fmt_eng(wf['ripple_pp'], 'V')} vs 目标 {p['ripple_target'] * op['V_out']:.3g} V "
                f"{'✓' if r_ok else '⚠'}")
            if topo=='FLYBACK':
                out.append(L_check['note'])
            if topo in ('BOOST', 'BUCK-BOOST', 'FLYBACK'):
                if np.isfinite(op['rhp_zero']):
                    out.append(f"RHP 零点 = {fmt_eng(op['rhp_zero'], 'Hz')} → 环路 fc 应 ≪ "
                               f"{fmt_eng(op['rhp_zero'] / 5, 'Hz')}")
                else:
                    out.append("RHP 零点 = 无 (DCM 无右半平面零点) → fc 不受 RHP 限制")
        # capacitor ripple current (always the key check)
        if topo == 'ACF-FORWARD':
            out.append(f"正激: L 为输出滤波电感, Lm={fmt_eng(op['Lm_forward'],'H')} | "
                       f"Vclamp={op['V_clamp']:.1f} V, Vreset={op['V_reset']:.1f} V | "
                       f"fc 建议≤{fmt_eng(op['fc_recommended_max'],'Hz')}; 未默认计入 ZVS 收益")
        i_c_rms = wf['i_c_rms']
        p_cap = res['P_cap']
        scope = ''
        if res.get('outputs'):
            selected = next(row for row in res['outputs'] if row['id'] == op['feedback_output'])
            p_cap = selected['P_cap']
            scope = f"主反馈 OUT{op['feedback_output']} · "
        rec = 2.0 * i_c_rms                    # ~50% derating of the rating
        out.append(
            scope+f"电容纹波电流 I_c(rms) = {fmt_eng(i_c_rms, 'A')} → 本路 ESR 损耗 "
            f"{p_cap:.3f} W; 选电容额定纹波电流 ≥ {fmt_eng(rec, 'A')} "
            f"(按 ~50% 降额, 参考: Knowles 电容纹波电流热设计)")
        if wf.get('esl_spike_pp') and wf['esl_spike_pp'] > 0.1:
            out.append(f"ESL 开关尖峰 ≈ {fmt_eng(wf['esl_spike_pp'], 'V')} (高频, "
                       f"由 ESL×di/dt 估算, 建议并联小陶瓷电容吸收; 不计入纹波目标)")
        out.append(f"预设 η = {op['eta_guess'] * 100:.2f}% → 最终计算 η = {res['eta'] * 100:.2f}%   "
                   f"总损耗 = {res['P_total']:.3f} W  "
                   f"(半导体 {res['P_semi']:.3f} + 磁件 {res['P_mag']:.3f} + "
                   f"电容(入/出) {res['P_cap_in']:.3f}/{res['P_cap']:.3f} + 采样 {res['P_sense']:.3f} + "
                   f"RCD {res.get('P_rcd', 0.0):.3f} + 钳位电容 {res.get('P_clamp', 0.0):.3f} + "
                   f"防反二极管(入/出) {res.get('P_din', 0.0):.3f}/{res.get('P_dout', 0.0):.3f})")
        out.append('η为模型估算: 未计附加损耗(温度/辅助电路/输入整流/EMI 等), '
                   '非最终实物效率, 见⑥页注')
        return '   |   '.join(out)

    # ============================================================ ② stress tab
    def _build_stress_tab(self):
        f = self._build_results_scroll(self.tab_stress, 'stress')
        top = ttk.Frame(f, style='Guide.TFrame', padding='8 4')
        top.pack(fill='x', pady=(2, 4))
        self.guide_stress = self._result_label(top, text=STEP_GUIDE[1],
                                      style='Guide.TLabel')
        self.guide_stress.pack(fill='x')

        body = ttk.Frame(f)
        body.pack(fill='both', expand=True)
        for col in range(2):
            body.columnconfigure(col, weight=1)
        self.sw_tree = self._make_stress_tree(body, 0, 'MOSFET switch (开关管)')
        self.di_tree = self._make_stress_tree(body, 1, 'Rectifier diode (整流二极管)')
        self.swl_tree = self._make_stress_tree(body, 2, 'Switch loss (开关管损耗)')
        self.dil_tree = self._make_stress_tree(body, 3, 'Diode/SR loss (整流损耗)')

        self.fig_stress, self.ax_stress = _subplots(1, 2, figsize=(11.5, 2.4))
        self.fig_stress.set_layout_engine('constrained')
        self.canvas_stress = FigureCanvasTkAgg(self.fig_stress, master=f)
        self.canvas_stress.get_tk_widget().pack(fill='x', pady=(4, 0))
        self._bind_result_overview('stress', self.canvas_stress)

        self.stress_note = tk.StringVar(value='')
        self._result_label(f, textvariable=self.stress_note, foreground=BAD).pack(fill='x', pady=3)
        self._build_output_result_host(f, 'stress')

    def _make_stress_tree(self, parent, col, title):
        frame = ttk.LabelFrame(parent, text=title, padding=4)
        frame.grid(row=col//2, column=col%2, sticky='nsew', padx=3, pady=3)
        tree = ttk.Treeview(frame, columns=('v',), show='tree', height=9)
        tree.heading('#0', text='quantity (参数)')
        tree.column('#0', width=190)
        tree.column('v', width=120, anchor='e')
        tree.pack(fill='both', expand=True)
        return tree

    def _update_stress(self, op, res):
        try:
            self._prepare_result_overview('stress')
            stress = device_stress(op)
            note_sw = stress['switch'].get('note', '')
            if op['topology'] in ('FLYBACK', 'QR-FLYBACK'):
                Kc_t = float(self.rcd_Kc.get())
                if Kc_t and Kc_t > 1.0:
                    note_sw += (f"  |  Vds 平台 {op.get('clamp',{}).get('V_plateau',op['V_in']+op['V_r']):.3g} V；"
                                f"包络峰值 {op.get('clamp',{}).get('V_peak',op['V_sw_max']):.3g} V；"
                                f"Kc 钳位上限 {op['clamp']['V_ceiling']:.3g} V（未叠加振铃裕度，另核实降额）")
            self._fill_tree(self.sw_tree, [
                ('Vds max (最大漏源电压)', fmt_eng(stress['switch']['V_max'], 'V')),
                ('Vds blocking (稳态阻断)', fmt_eng(stress['switch']['V_block'], 'V')),
                ('Id rms (有效值)', fmt_eng(stress['switch']['I_rms'], 'A')),
                ('Id peak (峰值)', fmt_eng(stress['switch']['I_pk'], 'A')),
                ('Id avg (平均值)', fmt_eng(stress['switch']['I_avg'], 'A')),
                ('note (说明)', note_sw),
            ])
            self._fill_tree(self.di_tree, [
                ('Vr max (反压，未计寄生尖峰)', fmt_eng(stress['diode']['V_max'], 'V')),
                ('Vr blocking (稳态阻断)', fmt_eng(stress['diode']['V_block'], 'V')),
                ('If rms (有效值)', fmt_eng(stress['diode']['I_rms'], 'A')),
                ('If peak (峰值)', fmt_eng(stress['diode']['I_pk'], 'A')),
                ('If avg (平均值)', fmt_eng(stress['diode']['I_avg'], 'A')),
                ('note (说明)', stress['diode'].get('note', '')),
            ])
            sw = res['semi']['switch']
            self._fill_tree(self.swl_tree, [
                ('Miller model (平台模型)', sw['gate']['label']),
                ('Id,on / Id,off (换流电流)', f"{sw['gate']['I_on']:.4g} / {sw['gate']['I_off']:.4g} A"),
                ('Vgp,on / Vgp,off (当前平台)', f"{sw['gate']['Vgp_on']:.4g} / {sw['gate']['Vgp_off']:.4g} V"),
                ('P cond (导通损耗)', f'{sw["P_cond"]:.3f} W'),
                ('P sw(on) = Ptr (开通损耗)', f'{sw["P_sw_on"]:.3f} W'),
                ('  t2+t3 (开通时间)', f'{((sw.get("t2", 0) + sw.get("t3", 0)) * 1e9):.1f} ns'),
                ('P sw(off) = Ptf (关断损耗)', f'{sw["P_sw_off"]:.3f} W'),
                ('  t6+t7 (关断时间)', f'{((sw.get("t6", 0) + sw.get("t7", 0)) * 1e9):.1f} ns'),
                ('P coss (输出电容损耗)', f'{sw["P_coss"]:.3f} W'),
                ('P gate (栅极驱动损耗)', f'{sw["P_gate"]:.3f} W'),
                ('P total (总损耗)', f'{sw["P_total"]:.3f} W'),
            ])
            di = res['semi']['diode']
            if di.get('sr'):
                self._fill_tree(self.dil_tree, [
                    ('SR conduction (同步整流导通)', f'{di["P_sr_cond"]:.3f} W'),
                    ('Body diode, dead-time (体二极管/死区)', f'{di["P_body"]:.3f} W'),
                    ('SR gate drive (栅极驱动)', f'{di["P_gate"]:.3f} W'),
                    ('P total, 2×SR (总损耗)', f'{di["P_total"]:.3f} W'),
                ])
            else:
                self._fill_tree(self.dil_tree, [
                    ('P cond (导通损耗)', f'{di["P_cond"]:.3f} W'),
                    ('P rr (反向恢复损耗)', f'{di["P_rr"]:.3f} W'),
                    ('P total (总损耗)', f'{di["P_total"]:.3f} W'),
                ])
            # loss components bar chart
            ax1, ax2 = self.ax_stress
            swc = ['导通', '开通', '关断', 'Coss', '栅极驱动']
            swv = [sw['P_cond'], sw['P_sw_on'], sw['P_sw_off'],
                   sw['P_coss'], sw['P_gate']]
            _loss_bars(ax1, swc, swv, f'主 MOSFET 损耗 · {sw["P_total"]:.3f} W', '#c0392b')
            if di.get('sr'):
                dk = ['SR cond', 'body', 'gate']
                dv = [di['P_sr_cond'], di['P_body'], di['P_gate']]
                diode_title = f'SR 损耗 · {di["P_total"]:.3f} W'
            else:
                dk = ['导通', '反向恢复']
                dv = [di['P_cond'], di['P_rr']]
                diode_title = f'整流器件损耗 · {di["P_total"]:.3f} W'
            if op['topology'] == 'ACF-FORWARD':
                aux, free = res['semi']['auxiliary'], res['semi']['freewheel']
                dk += ['续流管导通', '续流反向恢复', '钳位 MOSFET']
                dv += [free['P_cond'], free['P_rr'], aux['P_total']]
                extra_sw = [(f'钳位 MOSFET {k}', fmt_eng(stress['auxiliary'][k], u))
                            for k,u in [('V_max','V'),('I_rms','A'),('I_pk','A')]]
                self._fill_tree(self.sw_tree, [
                    ('主 MOSFET Vds max', fmt_eng(stress['switch']['V_max'],'V')),
                    ('主 MOSFET Id rms', fmt_eng(stress['switch']['I_rms'],'A')),
                    ('主 MOSFET Id peak', fmt_eng(stress['switch']['I_pk'],'A'))]+extra_sw)
                self._fill_tree(self.di_tree, [
                    ('正向管 Vr max', fmt_eng(stress['diode']['V_max'],'V')),
                    ('正向管 If rms', fmt_eng(stress['diode']['I_rms'],'A')),
                    ('续流管 Vr max', fmt_eng(stress['freewheel']['V_max'],'V')),
                    ('续流管 If rms', fmt_eng(stress['freewheel']['I_rms'],'A'))])
                diode_title = '副边整流 / 续流与辅助开关损耗'
            _loss_bars(ax2, dk, dv, diode_title, '#2980b9')
            if res.get('outputs'):
                self._draw_multi_stress_overview(op, res, _loss_bars)
            self._scale_result_text('stress')
            _draw_canvas(self.canvas_stress)

            ns = res['semi']['n_switches']
            nd = res['semi']['n_diodes']
            self.stress_note.set(
                f'半导体总损耗: {res["semi"]["P_total"]:.3f} W '
                f'({ns} 开关管 + {nd} 整流管). '
                f'选型建议 (1.2~1.5× 裕量): MOSFET ≥ '
                f'{fmt_eng(stress["switch"]["V_max"] * 1.2, "V")} / '
                f'{fmt_eng(stress["switch"]["I_rms"] * 2, "A")} rms; '
                f'整流管 ≥ {fmt_eng(stress["diode"]["V_max"] * 1.2, "V")} / '
                f'{fmt_eng(stress["diode"]["I_avg"] * 2, "A")} avg.\n'
                + __import__('stress_notes').DIODE_STRESS_NOTE)
            if res.get('outputs'):
                self.stress_note.set(self._multi_stress_note(res)+'\n'+__import__('stress_notes').DIODE_STRESS_NOTE)
            self._update_output_result_cards('stress', op, res)
        except Exception as e:
            import traceback
            traceback.print_exc()
            self.status_var.set(f'Stress: {e}')

    @staticmethod
    def _fill_tree(tree, items):
        tree.delete(*tree.get_children())
        for i, (k, v) in enumerate(items):
            tag = 'odd' if i % 2 else 'even'
            tree.insert('', 'end', text=k, values=(v,), tags=(tag,))
        tree.tag_configure('even', background='#ffffff')
        tree.tag_configure('odd', background='#f2f5f9')

    # ============================================================ ③ magnetics
    def _build_mag_tab(self):
        self.mag_nb = ttk.Notebook(self.tab_mag)
        self.mag_nb.pack(fill='both', expand=True)
        self.tab_mag_design = ttk.Frame(self.mag_nb)
        self.tab_mag_winding = ttk.Frame(self.mag_nb)
        self.mag_nb.add(self.tab_mag_design, text='磁件设计与温升')
        self.mag_nb.add(self.tab_mag_winding, text='变压器可绕制评估')
        self._build_winding_tab(self.tab_mag_winding)
        f = self.tab_mag_design
        top = ttk.Frame(f, style='Guide.TFrame', padding='8 4')
        top.pack(fill='x', pady=(2, 4))
        self.mag_simulation_button = ttk.Button(top, text='仿真与报告中心…',
                                              command=self._export_joint_ui)
        self.mag_simulation_button.pack(side='right', padx=5)
        self.guide_mag = ttk.Label(top, text=STEP_GUIDE[2],
                                   style='Guide.TLabel')
        self.guide_mag.pack(side='left')

        body = ttk.Panedwindow(f, orient='horizontal')
        body.pack(fill='both', expand=True)
        plot = ttk.Frame(body, width=620)
        right = ttk.Frame(body, width=460)
        plot.pack_propagate(False)
        right.pack_propagate(False)
        body.add(plot, weight=3)
        body.add(right, weight=2)
        def initial_split(event):
            if event.width > 400 and body.winfo_ismapped():
                body.sashpos(0, int(event.width * .52))
                body.unbind('<Configure>', split_binding)
        split_binding = body.bind('<Configure>', initial_split, add='+')
        self.fig_mag, (self.ax_mag_b, self.ax_mag_loss) = _subplots(
            2, 1, figsize=(6.0, 6.0))
        self.fig_mag.set_layout_engine('constrained')
        self.canvas_mag = FigureCanvasTkAgg(self.fig_mag, master=plot)
        self.canvas_mag.get_tk_widget().pack(fill='both', expand=True)
        from magnetic_report_ui import MagneticReport
        self.mag_report = MagneticReport(right)
        self.mag_report.pack(fill='both', expand=True)
        self.mag_text = self.mag_report
        self.mag_check = tk.StringVar(value='')

    def _set_magnetic_report(self, p, res):
        from magnetic_report_view import build_report
        view = build_report(p, res)
        self.mag_report.render(view)
        self.mag_check.set(view['summary'])
        xf = (res.get('mag') or {}).get('transformer') or {}
        if hasattr(self, 'transformer_gap_readout') and xf.get('gap_design'):
            from transformer_gap import summary
            self.transformer_gap_readout.set(summary(xf['gap_design']))

    def _b_waveforms(self, op, wf, res):
        """B(t) waveforms of the designed magnetic device(s)."""
        md = res.get('mag') or {}
        out = []
        ind = md.get('inductor')
        if ind and ind.get('ok') and ind.get('design_enabled') is not False:
            N, Ae = ind['N'], ind['Ae']
            L, i = op['L'], wf['iL']
            out.append(dict(name='电感 (L)', t=wf['t'], B=L * i / (N * Ae),
                            B_pk=ind['B_pk'], dT=ind.get('dT', 0.0)))
        xf = md.get('transformer')
        if xf and xf.get('ok'):
            if op['topology'] == 'ACF-FORWARD':
                B = op['Lm_forward']*wf['i_mag']/(xf['Np']*xf['Ae'])
                out.append(dict(name='正激变压器 T', t=wf['t'], B=B,
                                B_pk=xf['B_pk'], dT=xf.get('dT',0)))
            if op['topology'] in ('FLYBACK', 'QR-FLYBACK'):
                Np, Ae = xf['Np'], xf['Ae']
                B = op['L'] * wf['i_p'] / (Np * Ae)
                out.append(dict(name='变压器 (T, 原边磁通)', t=wf['t'], B=B,
                                B_pk=xf['B_pk'], dT=xf.get('dT', 0.0)))
        return out

    def _update_mag(self, op, p, res, wf):
        try:
            md = res.get('mag') or {}
            ind = md.get('inductor') or {}
            if ind.get('design_enabled') is False:
                self.ax_mag_b.clear(); self.ax_mag_loss.clear()
                self.ax_mag_b.set_axis_off()
                self.ax_mag_b.text(.5, .56, '外购成品电感 · 不进行磁芯与绕组设计',
                    transform=self.ax_mag_b.transAxes, ha='center', va='center', fontsize=12)
                self.ax_mag_b.text(.5, .36, 'L 仍用于工作点、波形与环路；磁密和温升未评估',
                    transform=self.ax_mag_b.transAxes, ha='center', va='center', fontsize=10)
                _loss_bars(self.ax_mag_loss, ['直流铜损', '用户附加损耗'], [ind['P_cu'], ind['P_extra']],
                           '成品电感已计入的损耗', ['#1558b0','#8e44ad'])
                _draw_canvas(self.canvas_mag)
                self._set_magnetic_report(p, res)
                self._update_winding(op, p, res)
                return
            Bsat = p['Bsat']
            ax_b, ax_loss = self.ax_mag_b, self.ax_mag_loss
            ax_b.clear()
            ax_loss.clear()
            ax_b.set_axis_on()

            devices = self._b_waveforms(op, wf, res)
            colors = ['#1558b0', '#8e44ad', '#c0392b']
            for dev, col in zip(devices, colors):
                t, B = dev['t'], dev['B']
                ax_b.plot(t * 1e6, B * 1e3, lw=1.1, color=col,
                          label=dev['name'])
            if devices:
                from magnetic_plot import show_flux_range
                show_flux_range(ax_b,[dev['B']*1e3 for dev in devices],Bsat*1e3)
            ax_b.set_title('磁通密度与饱和界限', fontsize=10, pad=9)
            ax_b.set_xlabel('时间 / µs', fontsize=9); ax_b.set_ylabel('B / mT', fontsize=9)
            ax_b.tick_params(labelsize=8)
            ax_b.legend(fontsize=8, loc='lower right')
            ax_b.grid(True)

            parts = []
            if md.get('inductor') and md['inductor'].get('ok'):
                ind = md['inductor']
                parts.append(('L core', ind['P_core'], ind['P_cu']))
            if md.get('transformer') and md['transformer'].get('ok'):
                xf = md['transformer']
                parts.append(('T core', xf['P_core'], xf['P_cu']))
            if parts:
                labels, values = [], []
                for name, core, copper in parts:
                    prefix = '输出电感' if name.startswith('L') else '变压器'
                    labels.extend([prefix+' 磁芯', prefix+' 铜损'])
                    values.extend([core, copper])
                _loss_bars(ax_loss, labels, values, '磁件损耗',
                           ['#1558b0','#8e44ad']*len(parts))
            _draw_canvas(self.canvas_mag)

            self._set_magnetic_report(p, res)
            self._update_winding(op, p, res)
        except Exception as e:
            import traceback
            traceback.print_exc()
            self.status_var.set(f'Mag: {e}')

    # ============================================================ ④ loop tab
    def _build_loop_tab(self):
        f = self.tab_loop
        top = ttk.Frame(f, style='Guide.TFrame', padding='8 4')
        top.pack(fill='x', pady=(2, 4))
        self.guide_loop = ttk.Label(top, text=STEP_GUIDE[3],
                                    style='Guide.TLabel')
        self.guide_loop.pack(side='left')

        margin_row = ttk.Frame(f)
        margin_row.pack(fill='x', pady=3)
        ttk.Label(margin_row, text='稳定裕度',
                  style='Muted.TLabel').pack(side='left')
        for k in ('pm', 'gm', 'fc'):
            ttk.Label(margin_row, textvariable=self.margin_info[k],
                      style='Margin.TLabel').pack(side='left', padx=8)

        # Reminder about the output-cap ESR zero (not modelled).
        self.esr_note_label = ttk.Label(f, textvariable=self.loop_esr_note,
                                        wraplength=900, anchor='w',
                                        style='Muted.TLabel')
        self.esr_note_label.pack(fill='x', pady=(0, 3))

        tune = ttk.LabelFrame(f, text='Venable K 因子自动整定',
                              padding=4)
        tune.pack(fill='x', pady=2)
        ttk.Label(tune, text='目标 fc / Hz').pack(side='left')
        self.params['fc_target'] = tk.DoubleVar(value=10e3)
        self.params['fc_target_unit'] = tk.StringVar(value='k')
        self.unit_opts['fc_target'] = ['', 'k', 'M']
        ttk.Entry(tune, textvariable=self.params['fc_target'], width=7).pack(side='left')
        ttk.Combobox(tune, textvariable=self.params['fc_target_unit'],
                     values=['', 'k', 'M'], width=3, state='readonly').pack(side='left')
        ttk.Label(tune, text='PM / °').pack(side='left', padx=(12, 2))
        self.params['pm_target'] = tk.DoubleVar(value=60.0)
        ttk.Entry(tune, textvariable=self.params['pm_target'], width=5).pack(side='left')
        ttk.Label(tune, text='类型').pack(side='left', padx=(12, 2))
        self.tune_type = self.params['controller_type']
        ttk.Combobox(tune, textvariable=self.tune_type,
                     values=CONTROLLER_CHOICES, width=7,
                     state='readonly').pack(side='left')
        ttk.Button(tune, text='自动整定', style='Accent.TButton',
                   command=self.run_auto_tune).pack(side='left', padx=10)
        self.tune_result = tk.StringVar(value='')
        ttk.Label(f, textvariable=self.tune_result, wraplength=1000,
                  justify='left', style='Result.TLabel').pack(fill='x',pady=(0,2))
        ttk.Label(f,textvariable=self.controller_note,style='Muted.TLabel',
                  wraplength=1000).pack(fill='x',pady=(0,3))

        self.loop_view_row = ttk.Frame(f)
        self.loop_view_row.pack(fill='x', pady=(0, 3))
        self.loop_view = tk.StringVar(value='主反馈 Bode')
        view = ttk.Combobox(self.loop_view_row, textvariable=self.loop_view,
            values=['主反馈 Bode', '各路响应'], state='readonly', width=16)
        view.pack(side='left', padx=4)
        view.bind('<<ComboboxSelected>>', lambda _e: self._redraw_loop_view())
        ttk.Label(self.loop_view_row, text='负载扰动注入').pack(side='left', padx=(8, 2))
        self.loop_load_output = tk.StringVar(value='OUT1')
        self.loop_load_combo = ttk.Combobox(self.loop_view_row, textvariable=self.loop_load_output,
            values=['OUT1'], state='readonly', width=7)
        self.loop_load_combo.pack(side='left')
        self.loop_load_combo.bind('<<ComboboxSelected>>', lambda _e: self._redraw_loop_view())
        self.loop_response_note = tk.StringVar()
        response_note = ttk.Label(self.loop_view_row, textvariable=self.loop_response_note,
                  style='Muted.TLabel', wraplength=220, justify='left')
        response_note.pack(side='left', padx=8, fill='x', expand=True)
        response_note.bind('<Configure>', lambda e: response_note.configure(wraplength=max(100,e.width-10)))
        self.loop_view_row.pack_forget()

        self.fig_loop, self.ax_loop = _subplots(2, 2, figsize=(11.5, 6.6))
        self.canvas_loop = FigureCanvasTkAgg(self.fig_loop, master=f)
        self.canvas_loop.get_tk_widget().pack(fill='both', expand=True)

    def run_auto_tune(self):
        """Venable K-factor design from target crossover / phase margin.

        Explicit II/III selections are independent of VM/PCM. Auto keeps
        the legacy default (VM -> III, PCM -> II)."""
        try:
            p = self.get_params()
            p.update(self._rcd_parameters())
            if p.get('feedback_mode')=='PSR-MP6005':
                self._psr_auto_tune(p)
                return
            current = self._last if self._snapshot_valid else None
            if p.get('coupling_config',{}).get('enabled') and (current is None or current['p'] != p):
                self.tune_result.set('请先等待当前参数的后台工作点计算完成，再整定。')
                return
            coupled = bool(current and current['op'].get('coupled_solution') is not None)
            if coupled:
                if p != current['p']:
                    self.tune_result.set('请先等待当前参数的工作点计算完成，再整定。')
                    return
                signature = parameter_signature(p)
                if signature != self._loop_signature:
                    self._loop_tune_pending = signature
                    self._queue_coupled_loop(p, current['op'])
                    self.tune_result.set('正在后台建立当前耦合环路，完成后整定；编辑参数会取消。')
                    return
                if self._loop_error:
                    raise ValueError(self._loop_error)
                Gvc, _Gc, _Go = self._loop_models
            else:
                Gvc, _Gc, _Go = self.calculate_transfer_functions(p,
                    current['op'] if current and current['p'] == p else None)
            fc = self.params['fc_target'].get() * self.units[self.params['fc_target_unit'].get()]
            pm = self.params['pm_target'].get()
            clamp_note = ''
            metadata = getattr(Gvc, '_loop_metadata', {})
            if metadata.get('experimental'):
                if metadata['inner_spectral_radius'] >= 1:
                    raise ValueError('周期内环谱半径 ≥1，请先修正斜坡补偿或工况，未写入外环参数')
            if p['topology'] == 'ACF-FORWARD':
                limit = compute_operating_point(p)['fc_recommended_max']
                if fc > limit:
                    fc = limit
                    self.set_param('fc_target', fc)
                    clamp_note = f'  | 有源钳位谐振限制: fc 已降至 {fc:.0f} Hz'
            f_lim = (compute_operating_point(p)['f_sw']
                     if p['topology'] == 'QR-FLYBACK' else p['f_sw'])
            if fc > f_lim / 6.0:
                fc = f_lim / 6.0
            kind = resolve_controller_type(p['controller_type'],p['control_mode'])
            r = kfactor_tune(Gvc, fc, pm, kind)
            if not r['feasible']:
                self.tune_result.set(f"{CONTROLLER_NAMES[kind]}无法达到此目标：所需相位提升 "
                                     f"{r['boost_required']:.2f}°；请调整 fc/PM 或选择其它类型。参数未写回。")
                return
            if metadata.get('experimental'):
                from loop_tuning import analyze_loop
                tuned = dict(p, controller_type=kind)
                tuned.update({key:r[key] for key in ('KP','fz1','fz2','fp1','fp2') if r.get(key) is not None})
                candidate = make_compensator(tuned).get_transfer_function()
                verified = analyze_loop(tuned, (Gvc, candidate, Gvc*candidate))
                if (not verified['closed_loop_stable'] or verified['fc'] is None or
                        verified['min_pm'] is None or verified['min_pm'] < pm-1):
                    raise ValueError('候选补偿未通过闭环极点/全部穿越校验，参数未写入；请降低 fc 或调整类型')
                self.set_param('fc_target', fc)
            for key in ('KP','fz1','fz2','fp1','fp2'):
                if r.get(key) is not None:
                    self.set_param(key,r[key])
            if kind=='type2' and self.comp_dir.get()=='fwd':
                self.comp_type2.set(False)
            warn = ''
            try:
                tuned = dict(p,controller_type=kind)
                tuned.update({key:r[key] for key in ('KP','fz1','fz2','fp1','fp2') if r.get(key) is not None})
                Gc_b = make_compensator(tuned)
                wv = np.logspace(np.log10(2 * np.pi * min(10., fc/100)),
                                 np.log10(2 * np.pi * (metadata.get('frequency_limit') or max(f_lim*10, 1e6))), 6000)
                mv, _pv, wv = ct.bode(Gvc * Gc_b.get_transfer_function(),
                                      omega=wv, dB=False, Hz=False, plot=False)
                mv = np.asarray(mv).ravel()
                wv = np.asarray(wv).ravel()
                mdb = 20 * np.log10(mv)
                crosses = []
                for i in range(len(mdb) - 1):
                    if mdb[i] >= 0 >= mdb[i + 1]:
                        crosses.append(float(np.interp(
                            0, mdb[i:i + 2][::-1], wv[i:i + 2][::-1]))
                            / (2 * np.pi))
                if crosses:
                    fc_near = min(crosses, key=lambda f: abs(np.log10(f / fc)))
                    if abs(np.log10(fc_near / fc)) > 0.15:
                        g1 = abs(Gvc(1j * 2 * np.pi * fc * 1.2))
                        g2 = abs(Gvc(1j * 2 * np.pi * fc / 1.2))
                        slope = (20 * np.log10(g1 / g2)
                                 / np.log10(1.2 ** 2))
                        warn = (f'  [0-dB 穿越点在 {fc_near:.0f} Hz, 非目标 '
                                f'{fc:.0f} Hz; fc 处对象斜率 {slope:+.0f} '
                                f'dB/dec — 请把 fc 移到对象下降斜面上]')
            except Exception:
                pass
            self.tune_result.set(
                f"type {r['comp_type']}: boost={r['boost']:.1f}°, K={r['K']:.2f}, "
                + f"KP={r['KP']:.4g}, fz={r['fz1']:.3g} Hz, fp={r['fp1']:.3g} Hz"
                + warn + clamp_note)
            self.schedule_update()
        except Exception as e:
            self.tune_result.set(f'auto-tune error: {e}')

    def _redraw_loop_view(self):
        if self._snapshot_valid and self._last:
            self._update_loop(self._last['p'])

    def _queue_coupled_loop(self, p, op):
        signature = parameter_signature(p)
        generation = getattr(self, '_loop_request_generation', None)
        if self._loop_pending_signature == signature and generation is not None and self._calculation_worker.is_current(generation):
            return
        engine_p = self._last.get('calculation_params', p) if self._last and self._last['p'] == p else p
        def calculate(snapshot, _cancelled):
            from plants import build_loop_models
            from loop_tuning import analyze_loop
            models, plant = build_loop_models(engine_p, op)
            return dict(models=models, plant=plant, loop=analyze_loop(engine_p, models, op))
        self._loop_pending_signature = signature
        if str(self.cross_button.cget('state')) == 'disabled':
            self._mark_cross_regulation_stale()
        self._loop_request_generation = self._calculation_worker.submit('coupled_loop', p, calculate, cache=True)
        for var in self.margin_info.values():
            var.set('环路: 后台计算中')
        self.loop_esr_note.set('正在按当前耦合周期解建立低频环路；编辑参数会取消旧结果。')
        self._ensure_calculation_poll()

    def _finish_coupled_loop(self, job):
        if not self._snapshot_valid or not self._last or job.parameters != self._last['p']:
            return
        signature = parameter_signature(job.parameters)
        self._loop_pending_signature = None
        self._loop_signature = signature
        self._loop_error = str(job.error) if job.error is not None else None
        self._loop_result = job.value['loop'] if job.error is None else None
        self._loop_models = job.value['models'] if job.error is None else None
        if job.error is None:
            self._last_plant = job.value['plant']
        if self._loop_tune_pending == signature:
            self._loop_tune_pending = None
            if job.error is None:
                self.run_auto_tune()
                return
            self.tune_result.set('auto-tune error: '+str(job.error))
        self._update_loop(job.parameters, draw=False)
        self._rendered_tabs.discard(4)
        self._rendered_tabs.discard(9)
        self._refresh_visible_tab()

    def _update_loop(self, p, draw=True):
        from loop_tuning import analyze_loop
        from design_checks import check_catalog
        try:
            current = self._last
            op = current['op'] if current and current['p'] == p else compute_design(p)['op']
            signature=parameter_signature(p)
            if current and current['p'] == p and op.get('coupled_solution') is not None:
                if signature != self._loop_signature:
                    self._queue_coupled_loop(p, op)
                    if draw:
                        for axis in self.ax_loop.flat:
                            axis.clear(); axis.text(.5, .5, '正在后台建立多路低频环路…',
                                ha='center', va='center', transform=axis.transAxes, fontsize=10)
                        _draw_canvas(self.canvas_loop)
                    return
                if self._loop_error:
                    raise ValueError(self._loop_error)
            loop=getattr(self,'_loop_result',None)
            if signature!=self._loop_signature or loop is None:
                models = self.calculate_transfer_functions(p, op)
                self._loop_models = models
                loop = analyze_loop(current.get('calculation_params', p) if current and current['p'] == p else p, models, op)
                self._loop_result = loop
                self._loop_signature=signature
            self._control_ready=True
            if current and current['p'] == p:
                current['loop'] = loop
                current['res']['loop'] = loop
                current['checks'] = check_catalog(current.get('calculation_params', p), current['res'], loop)
                if hasattr(self, 'review_tree'):
                    self._update_review()
            fc, pm, gm = loop['fc'], loop['pm'], loop['gm_db']
            self.margin_info['pm'].set(f'相位裕度: {pm:.1f}°' if pm is not None else '相位裕度: 未定义')
            self.margin_info['gm'].set(f'增益裕度: {gm:.1f} dB' if gm is not None else
                '增益裕度: 扫描范围内未检出' if loop.get('gm_scan_limited') or loop.get('gm_band_limited') else '增益裕度: 无有限值')
            self.margin_info['fc'].set(f'穿越频率: {fc:.1f} Hz' if fc is not None else '穿越频率: 未检出')
            note = '理想电容模型未包含 ESR 零点；低频平均模型结果须经仿真和 FRA 复核。'
            if op.get('outputs'):
                note += f" 当前为 OUT{op['feedback_output']}，采用刚性匝比能量等效，不验证各路独立负载动态。"
            if loop.get('model'):
                model = loop['model']
                feedback_output = model.get('feedback_output', op.get('feedback_output', 1))
                note = f"反馈路：OUT{feedback_output}。"+model['assumptions']
                if model.get('frequency_limit'):
                    note += f" 有效频带 ≤{model['frequency_limit']:.0f} Hz，建议 fc ≤{model['recommended_fc_max']:.0f} Hz。"
                if not loop['closed_loop_stable']:
                    note += ' ⚠ 近似闭环含非稳定极点，不能仅凭 PM 判稳。'
            if p.get('feedback_mode')=='PSR-MP6005' or uses_dcm_peak_energy(p,op):
                note = self._last_plant.model_note
            if p['topology'] == 'ACF-FORWARD':
                note = f"正激采用低频 Buck 派生模型，不含钳位完整动态。建议 fc ≤ {fmt_eng(op['fc_recommended_max'], 'Hz')}。"
            if op['mode'] != 'CCM' and not op.get('coupled_solution') and not uses_dcm_peak_energy(p,op):
                note += ' 当前采用低频单极点 DCM 近似。'
            if fc is None:
                note += ' 扫描范围内无下降穿越，不能用扫描末端作为 fc。'
            if len(loop['all_crosses']) > 1:
                note += f" 检出 {len(loop['all_crosses'])} 个穿越；显示靠近目标的一项，检查取全部穿越的最小 PM。"
            self.loop_esr_note.set(note)
            multi = loop.get('multi_output')
            if multi:
                if not self.loop_view_row.winfo_manager():
                    self.loop_view_row.pack(fill='x', pady=(0, 3), before=self.canvas_loop.get_tk_widget())
                values = [f'OUT{r["id"]}' for r in multi['outputs']]
                self.loop_load_combo.configure(values=values, state='readonly' if multi['load'] is not None else 'disabled')
                if self.loop_load_output.get() not in values:
                    self.loop_load_output.set(values[0])
                self.loop_response_note.set('负载增大为正；只作局部小信号' if multi['load'] is not None else '理想匝比参考响应；无负载矩阵')
            else:
                self.loop_view_row.pack_forget()
            if not draw:
                return
            if multi and self.loop_view.get() == '各路响应':
                from loop_charts import draw_multi_output_response
                draw_multi_output_response(self.ax_loop, loop, int(self.loop_load_output.get()[3:]))
                self.fig_loop.tight_layout()
                _draw_canvas(self.canvas_loop)
                return
            f = loop['f']
            gains, phases = loop['gains'], loop['phases']
            ax = self.ax_loop
            for a in ax.flat:
                a.clear(); a.set_axis_on()
            for i, label in enumerate(('Gvc 对象', 'Gc 补偿器')):
                ax[0, 0].semilogx(f, 20*np.log10(np.maximum(np.abs(gains[i]), 1e-300)), label=label)
                ax[0, 1].semilogx(f, phases[i], label=label)
            ax[0, 0].set(title='对象与补偿器幅频', ylabel='dB')
            ax[0, 1].set(title='对象与补偿器相频', ylabel='deg')
            ax[1, 0].semilogx(f, 20*np.log10(np.maximum(np.abs(gains[2]), 1e-300)), label='开环 T')
            ax[1, 1].semilogx(f, phases[2], label='开环相位')
            ax[1, 0].axhline(0, color='#b54a4a', ls='--', lw=.8)
            ax[1, 1].axhline(-180, color='#b54a4a', ls='--', lw=.8)
            ax[1, 0].set(title='开环幅频', ylabel='dB', xlabel='Hz')
            ax[1, 1].set(title='开环相频', ylabel='deg', xlabel='Hz')
            for c in loop['all_crosses']:
                for a in ax[1]:
                    a.axvline(c['fc'], color='#4C8A79', ls='--', lw=.8)
            target = p.get('fc_target', 0)
            if target > 0:
                ax[1, 0].axvline(target, color='#8677B2', ls=':', label='目标 fc')
            for a in ax.flat:
                a.legend(fontsize=8); a.grid(True, alpha=.3)
            self.fig_loop.tight_layout()
            _draw_canvas(self.canvas_loop)
        except Exception as e:
            self.status_var.set(f'环路计算失败: {e}')
            self._loop_result = None
            # A failed current numerical model is a completed error, not a
            # reason to resubmit the same job on every tab refresh.
            self._loop_signature = parameter_signature(p) if self._loop_error else None
            for var in self.margin_info.values(): var.set('环路: 未计算')
            self.loop_esr_note.set(str(e))
            if draw:
                for axis in self.ax_loop.flat:
                    axis.clear(); axis.text(.5,.5,str(e),ha='center',va='center',wrap=True,transform=axis.transAxes,fontsize=9)
                _draw_canvas(self.canvas_loop)
            if self._last:
                self._last['loop'] = None
                self._last['res']['loop'] = None
                self._last['checks'] = check_catalog(self._last.get('calculation_params', p), self._last['res'], loop_error=str(e))
                if hasattr(self, 'review_tree'): self._update_review()

    @staticmethod
    def _find_crossover(mag, omega, fc_target=None):
        """All 0-dB crossings; prefer the one closest to fc_target (the
        designed crossover), otherwise the highest one (dominant pole)."""
        mag_db = 20 * np.log10(mag)
        cross = []
        for i in range(len(mag_db) - 1):
            if mag_db[i] >= 0 >= mag_db[i + 1]:
                w = float(np.interp(0, mag_db[i:i + 2][::-1], omega[i:i + 2][::-1]))
                cross.append(w)
        if not cross:
            return None
        if fc_target and fc_target > 0:
            return min(cross, key=lambda w: abs(w - 2 * np.pi * fc_target))
        return cross[-1]

    # ============================================================ cap-ripple 6
    def _build_cap_tab(self):
        f = self._build_results_scroll(self.tab_cap, 'cap')
        guide = ttk.Frame(f, style='Guide.TFrame', padding='8 4')
        guide.pack(fill='x', pady=(2, 4))
        self._result_label(guide,
                  text='电容纹波：整周期 DFT，全频点复阻抗分流；RMS 与损耗、评审及报告共用一份结果。',
                  style='Guide.TLabel').pack(fill='x')
        self.fig_cap, (self.ax_cap_tot, self.ax_cap_band) = _subplots(
            2, 1, figsize=(11.5, 7.0))
        self.canvas_cap = FigureCanvasTkAgg(self.fig_cap, master=f)
        self.canvas_cap.get_tk_widget().pack(fill='both', expand=True)
        self._bind_result_overview('cap', self.canvas_cap)
        self.cap_summary = tk.StringVar(value='')
        self._result_label(f, textvariable=self.cap_summary, foreground='#1a5fb4').pack(fill='x', pady=3)
        self._build_output_result_host(f, 'cap')

    def _update_cap(self, op, p, res):
        try:
            ra = res['capacitors']
            multiple = bool(res.get('outputs'))
            self._draw_cap(ra, shared_only=multiple)
            parts = [f"共享输入电容银行 {ra['total_in']:.3f} A rms，ESR损耗 {res['P_cap_in']:.4g} W"] if multiple else [
                f"input cap bank {ra['total_in']:.3f} A | output cap bank {ra['total_out']:.3f} A"]
            banks = [('IN', ra['input'])]
            if multiple:
                parts.extend(f"OUT{row['id']}{' ★' if row['id']==op['feedback_output'] else ''}：{row['capacitors']['total_out']:.4g} A rms / {row['P_cap']:.4g} W"
                             for row in res['outputs'])
            else:
                banks.append(('OUT', ra['output']))
            for tag, rail in banks:
                for i, c in enumerate(rail['caps']):
                    dom = [(l, round(c['bands'][k], 3)) for k, l in
                           enumerate(rail['labels']) if c['bands'][k] > 0.02 * c['total']]
                    dom_s = ', '.join(f'{l}={v:.3f}A' for l, v in dom[:4])
                    parts.append(f"{tag} C{i + 1}: C={c['C'] * 1e6:.0f}uF ESR={c['ESR'] * 1e3:.0f}mR "
                                 f"ESL={c['ESL'] * 1e9:.0f}nH -> {c['total']:.3f} A rms ({dom_s})")
            self.cap_summary.set('   |   '.join(parts))
            self._update_output_result_cards('cap', op, res)
        except Exception as e:
            import traceback
            traceback.print_exc()
            self.status_var.set(f'Cap: {e}')

    def _draw_cap(self, ra, shared_only=False):
        # Separate panels retain every harmonic value without squeezing four
        # number annotations/legend entries into each narrow frequency band.
        self.fig_cap.clear()
        self.fig_cap.set_layout_engine('constrained')
        compact = self._prepare_result_overview('cap')
        labels, vals, caps = [], [], []
        banks = (('输入', ra['input']),) if shared_only else (('输入', ra['input']), ('输出', ra['output']))
        for prefix, rail in banks:
            for i, c in enumerate(rail['caps']):
                name = f'{prefix} C{i+1}'
                labels.append(f"{name} · {fmt_eng(c['C'],'F')} / {fmt_eng(c['ESR'],'Ω')}")
                vals.append(c['total'])
                caps.append((name, c, rail['labels']))
        columns = 1 if compact else 2
        band_rows = (len(caps)+columns-1)//columns
        height = round(max(700, max(280,28*len(caps))+240*band_rows)*max(1,self._font_k*13/20))
        self._result_overview_heights['cap']=height
        self.fig_cap.set_size_inches(self.fig_cap.get_figwidth(), height/self.fig_cap.dpi, forward=False)
        self.canvas_cap.get_tk_widget().configure(height=height)
        gs = self.fig_cap.add_gridspec(1+band_rows, columns,
                                      height_ratios=[max(1.1,len(caps)/9)]+[1]*band_rows)
        ax_t = self.fig_cap.add_subplot(gs[0, :])
        palette = ['#d62728', '#1f77b4', '#2ca02c', '#9467bd','#e08214','#008b8b']
        colors=[palette[i%len(palette)] for i in range(len(caps))]
        bars = ax_t.barh(np.arange(len(vals)), vals, color=colors[:len(vals)], height=.6)
        ax_t.set_yticks(np.arange(len(vals)), labels, fontsize=9)
        ax_t.invert_yaxis()
        ax_t.set_xlim(0, max(max(vals, default=0)*1.25, .01))
        ax_t.bar_label(bars, fmt='%.3f', fontsize=9, padding=4)
        title = f"共享输入电容纹波电流 · 银行 {ra['total_in']:.3f} A rms（只计一次）" if shared_only else f"电容总纹波电流 · 输入 {ra['total_in']:.3f} A / 输出 {ra['total_out']:.3f} A"
        ax_t.set(title=title,
                 xlabel='RMS / A')
        ax_t.title.set_fontsize(10)
        ax_t.xaxis.label.set_size(9)
        ax_t.tick_params(axis='x', labelsize=8)
        ax_t.grid(False)
        ax_t.grid(True, axis='x', alpha=.55)
        self.ax_cap_tot = ax_t
        self.ax_cap_band = []
        for k, (name, c, bands) in enumerate(caps):
            ax = self.fig_cap.add_subplot(gs[1+k//columns, k%columns])
            x = np.arange(len(bands))
            ax.bar(x, c['bands'], color=colors[k], width=.75)
            # Sparse horizontal ticks rather than 22 rotated band labels.
            # Leave at least four bars between labels, including both edges.
            # The first subharmonic label otherwise collides with "1f".
            ticks = np.unique(np.r_[np.arange(0, max(len(bands)-4, 1), 4), len(bands)-1])
            ax.set_xticks(ticks, [bands[i] for i in ticks], fontsize=8)
            ax.set_title(f'{name} · 各频带 RMS', fontsize=10, pad=8)
            ax.set_ylabel('A', fontsize=9)
            ax.tick_params(axis='y', labelsize=8)
            ax.margins(y=.18)
            ax.grid(False)
            ax.grid(True, axis='y', alpha=.55)
            self.ax_cap_band.append(ax)
        self._scale_result_text('cap')
        _draw_canvas(self.canvas_cap)

    # ============================================================ RCD (RC) clamp
    def _build_rcd_tab(self):
        f = self.tab_rcd
        top = ttk.Frame(f, style='Guide.TFrame', padding='8 4')
        top.pack(fill='x', pady=(2, 4))
        self.guide_rcd = ttk.Label(top,
            text='RCD (RC) 吸收钳位 (反激/准谐振反激原边漏感) — 输入 Kc, K, ΔC, 其余取当前设计',
                                   style='Guide.TLabel')
        self.guide_rcd.pack(side='left')

        inp = ttk.LabelFrame(f,
                             text='输入 Inputs (其余量取当前运行点: V_reflect / Lm / I_pk / f_sw)',
                             padding=4)
        inp.pack(fill='x', pady=2)
        self.rcd_input_frame = inp
        ttk.Label(inp, text='所有拓扑配置请在左侧列编辑；本页展示钳位计算与波形。',
                  style='Muted.TLabel', wraplength=900).pack(fill='x')

        self.rcd_result = tk.StringVar(value='')
        res = ttk.LabelFrame(f, text='输出 Outputs', padding=4)
        res.pack(fill='x', pady=2)
        ttk.Label(res, textvariable=self.rcd_result, style='Result.TLabel',
                  wraplength=980).pack(side='left', fill='x', expand=True)

        self.fig_rcd, self.ax_rcd = _subplots(1, 2, figsize=(11.2, 3.8))
        self.canvas_rcd = FigureCanvasTkAgg(self.fig_rcd, master=f)
        self.canvas_rcd.get_tk_widget().pack(fill='both', expand=True)

    def _update_rcd(self, op, p):
        """Standalone RCD (RC) clamp tab.  Inputs from the tab (K/Kc/dC); the
        rest comes from the current design operating point."""
        try:
            ax = self.ax_rcd
            for a in ax:
                a.clear()
            topo = op['topology']
            if topo == 'ACF-FORWARD':
                self._update_active_clamp(op, p)
                return
            if topo not in ('FLYBACK', 'QR-FLYBACK'):
                self.rcd_result.set(
                    f'RCD 仅适用于反激 / 准谐振反激 (当前拓扑: {topo})')
                self.fig_rcd.tight_layout()
                _draw_canvas(self.canvas_rcd)
                return
            from flyback_clamp import rcd_components
            rcd = rcd_components(op,p)
            self.guide_rcd.configure(text='矩阵换流 / Kc / ΔC；kij 在左栏⑦编辑，旧 K 不参与本模型。' if op.get('coupled_model') else
                                     '快速漏感包络 / Kc / 旧 K / ΔC；与周期波形及功耗使用同一模型。')
            dC = p.get('dC',.1)
            leakage = '由矩阵求解' if rcd['L_leak'] is None else f"{rcd['L_leak']*1e6:.4g} µH"
            self.rcd_result.set(
                f"V_reflect = {rcd['V_reflect']:.1f} V   |   "
                f"V_clamp = {rcd['V_clamp']:.1f} V   |   "
                f"L_leak = {leakage}   |   "
                f"P_res = {rcd['P_res']:.3f} W   |   "
                f"R_snub = {rcd['R_snub'] / 1e3:.2f} kΩ   |   "
                f"C_snub = {rcd['C_snub'] * 1e9:.1f} nF   |   "
                f"ΔV_c = {rcd['dV_clamp']:.3g} V ({dC * 100:.0f}% of V_clamp)\n"
                + ' '.join(rcd['notes']))
            self._plot_rcd_waveform(ax, op, rcd, dC)
            self.fig_rcd.tight_layout()
            _draw_canvas(self.canvas_rcd)
        except Exception as e:
            import traceback; traceback.print_exc()
            try:
                self.rcd_result.set(f'RCD error: {e}')
            except Exception:
                pass

    def _update_active_clamp(self, op, p):
        from active_clamp import forward_waveforms
        t = np.linspace(0, 3*op['Ts'], 3000, endpoint=False)
        wf = forward_waveforms(op, t)
        ax_v, ax_i = self.ax_rcd
        ax_v.plot(t*1e6, wf['v_sw'], label='主开关 Vds', color=ACCENT)
        ax_v.plot(t*1e6, wf['v_clamp'], label='钳位电容电压', color=WARN, ls='--')
        ax_v.axhline(op['V_clamp'], lw=.8, color=MUTED, ls=':')
        ax_v.set(title='低侧有源钳位电压 (小纹波近似)', xlabel='时间 / µs', ylabel='V')
        ax_v.legend(fontsize=9)
        ax_i.plot(t*1e6, wf['i_mag'], label='励磁电流', color='#8e44ad')
        ax_i.plot(t*1e6, wf['i_aux'], label='辅助 MOSFET 电流', color=OK, ls='--')
        ax_i.axhline(0, color=MUTED, lw=.8)
        ax_i.set(title='双极性励磁电流与钳位复位', xlabel='时间 / µs', ylabel='A')
        ax_i.legend(fontsize=9)
        self.rcd_result.set(
            f"D={op['D']:.3f} / 上限 {op['forward_d_max']:.2f}  | "
            f"V_reset={op['V_reset']:.2f} V  |  低侧 C_clamp 电压={op['V_clamp']:.2f} V  | "
            f"隆起≈{op['V_clamp_hump']:.2f} V  |  主/辅助 MOSFET 峰值估算={op['V_sw_max']:.2f} V\n"
            f"I_mag(pk)=±{op['I_mag_pk']:.3f} A  |  I_clamp(rms)={op['I_clamp_rms']:.3f} A  | "
            f"C_clamp ≥ {fmt_eng(op['C_clamp_min'],'F')} (隆起≤5%)  | "
            f"f_res={fmt_eng(op['f_clamp'],'Hz')}  |  建议 fc≤{fmt_eng(op['fc_recommended_max'],'Hz')}\n"
            + ' '.join(op['warnings']))
        self.fig_rcd.tight_layout()
        _draw_canvas(self.canvas_rcd)

    def _plot_rcd_waveform(self, ax, op, rcd, dC):
        from flyback_clamp import clamp_current
        wf = make_waveforms(op,n_cycles=3,n_pts=4096)
        t,Vd = wf['t'],wf['v_sw']
        V_plateau = op['clamp']['V_plateau']
        V_spike = op['clamp']['V_peak']
        Vc = np.full_like(t,rcd['V_clamp'])
        if rcd['C_snub'] > 0 and np.isfinite(rcd['R_snub']):
            current = clamp_current(t,op)
            frequencies = np.fft.rfftfreq(len(t),float(t[1]-t[0]))
            impedance = rcd['R_snub']/(1+2j*np.pi*frequencies*rcd['R_snub']*rcd['C_snub'])
            impedance[0] = 0.
            Vc += np.fft.irfft(np.fft.rfft(current)*impedance,len(t))
        ax[0].plot(t * 1e6, Vc, lw=1.2, color='#1558b0')
        ax[0].axhline(rcd['V_clamp'], color='r', ls='--', lw=0.8,
                      label=f"V_clamp={rcd['V_clamp']:.1f} V")
        ax[0].fill_between(t * 1e6, rcd['V_clamp'] - rcd['dV_clamp'] / 2,
                           rcd['V_clamp'] + rcd['dV_clamp'] / 2,
                           alpha=0.15, color='#1558b0',
                           label=f"ΔV_c={rcd['dV_clamp']:.2f} V")
        ax[0].set_title('钳位电容电压（按钳位电流的小纹波 RC 重建）')
        ax[0].set_xlabel('time, us'); ax[0].set_ylabel('V')
        ax[0].legend(fontsize=9); ax[0].grid(True)
        ax[1].plot(t * 1e6, Vd, lw=1.2, color='#c0392b')
        ax[1].axhline(V_spike, color='g', ls='--', lw=0.8,
                      label=f'实际包络峰值={V_spike:.1f} V')
        ax[1].axhline(V_plateau, color='b', ls=':', lw=0.8,
                      label=f'平台 V_in+V_reflect={V_plateau:.1f} V')
        ax[1].set_title('Q1 漏源电压（与功率级及应力同一模型）')
        ax[1].set_xlabel('time, us'); ax[1].set_ylabel('V')
        ax[1].legend(fontsize=9); ax[1].grid(True)

    # ==================================================== ⑧ compensation RC
    COMP_TOPOS = [
        ('opamp3', '普通运放补偿网络（跟随⑤页类型）'),
        ('gm3', '跨导运放补偿网络（跟随⑤页类型）'),
        ('tl431nf', 'TL431+光耦 — 无快车道 (LED 接独立偏置)'),
        ('tl431f', 'TL431+光耦 — 快车道 (LED 接 Vout)'),
    ]
    # reference figure per topology, shown on the tab (file in comp_images/)
    COMP_IMAGES = {
        'opamp3': 'opamp3_clean.png', 'gm3': 'gm3.png',
        'tl431nf': 'tl431nf.png', 'tl431f': 'tl431f_clean.png',
    }
    # per-topology user inputs: key -> (label, default, unit options)
    COMP_INPUTS = {
        'opamp3': [('R1', '上分压电阻 R1 (Vo→FB, Ω)', 10e3, ['', 'k']),
                   ('Vref', '基准电压 V_REF, V (运放+端)', 2.5, ['', 'm'])],
        'gm3': [('R2', '下分压电阻 R2 (Ω)', 10e3, ['', 'k']),
                ('R1u', '上分压电阻 R1 (仅二型需填, Ω)', 0.0, ['', 'k']),
                ('gm', '跨导 gm (S, 典型 2m)', 2e-3, ['m', ''])],
        'tl431nf': [('R1', '上分压电阻 R1 (Ω)', 40e3, ['', 'k']),
                    ('R_LED', 'LED 电阻 R_LED (Ω)', 1e3, ['', 'k']),
                    ('CTR', '光耦 CTR (电流传输比)', 1.0, []),
                    ('Rpullup', '光耦上拉 R_pullup (Ω)', 20e3, ['', 'k']),
                    ('Copto', '光耦结电容 C_opto (F)', 2e-9, ['n', 'p'])],
        'tl431f': [('R1', '上分压电阻 R1 (Ω)', 40e3, ['', 'k']),
                   ('CTR', '光耦 CTR', 1.0, []),
                   ('Rpullup', '光耦上拉 R_pullup (Ω)', 20e3, ['', 'k']),
                   ('Copto', '光耦结电容 C_opto (F)', 2e-9, ['n', 'p'])],
    }
    # reverse mode: the FULL part set of each topology (figure naming);
    # Legacy simplified branches use zero capacitors and GHz placeholders.
    COMP_REV_INPUTS = {
        'opamp3': [('R1', 'R1 上分压 (Ω)', 10e3, ['', 'k']),
                   ('R2', 'R2 反馈串联 (Ω)', 10e3, ['', 'k']),
                   ('R3', 'R3 输入支路 (Ω)', 10e3, ['', 'k']),
                   ('C1', 'C1 反馈串联 (F)', 10e-9, ['n', 'p', 'u']),
                   ('C2', 'C2 反馈并联 (F, 0=简化支路)', 10e-9, ['n', 'p', 'u']),
                   ('C3', 'C3 输入支路 (F, 0=二型)', 10e-9, ['n', 'p', 'u'])],
        'gm3': [('gm', 'gm 跨导 (S)', 2e-3, ['m', '']),
                ('R1', 'R1 上分压 (Ω)', 100e3, ['', 'k']),
                ('R2', 'R2 下分压 (Ω)', 10e3, ['', 'k']),
                ('R3', 'R3 Zt串联 (Ω)', 10e3, ['', 'k']),
                ('C1', 'C1 并联R1 (F, 0=二型)', 2.2e-9, ['n', 'p', 'u']),
                ('C2', 'C2 Zt串联 (F)', 10e-9, ['n', 'p', 'u']),
                ('C3', 'C3 Zt并联 (F, 0=简化支路)', 10e-9, ['n', 'p', 'u'])],
        'tl431nf': [('CTR', 'CTR 光耦传输比', 1.0, []),
                    ('R_LED', 'R_LED (Ω)', 1e3, ['', 'k']),
                    ('Rpullup', 'R_pullup (Ω)', 20e3, ['', 'k']),
                    ('Copto', 'C_opto (F)', 2e-9, ['n', 'p']),
                    ('R1', 'R1 上分压 (Ω)', 40e3, ['', 'k']),
                    ('R2', 'R2 (FB→阴极串联) (Ω)', 40e3, ['', 'k']),
                    ('R3', 'R3 (Vout→FB串联) (Ω)', 4e3, ['', 'k']),
                    ('C1', 'C1 (FB→阴极串联) (F)', 3.8e-9, ['n', 'p', 'u']),
                    ('C2', 'C2 并联光耦 (F)', 3.3e-9, ['n', 'p', 'u']),
                    ('C3', 'C3 (Vout→FB串联) (F)', 0.4e-9, ['n', 'p', 'u'])],
        'tl431f': [('CTR', 'CTR 光耦传输比', 1.0, []),
                   ('R_LED', 'R_LED (Vout→LED) (Ω)', 200.0, ['', 'k']),
                   ('Rpullup', 'R_pullup (Ω)', 20e3, ['', 'k']),
                   ('Copto', 'C_opto (F)', 2e-9, ['n', 'p']),
                   ('R1', 'R1 上分压 (Ω)', 40e3, ['', 'k']),
                   ('C1', 'C1 (FB→阴极) (F)', 4e-9, ['n', 'p', 'u']),
                   ('R_pz', 'R_pz (FB→阴极第二支路) (Ω)', 15.0, ['', 'k']),
                   ('C_pz', 'C_pz (第二支路串联) (F)', 790e-9, ['n', 'p', 'u']),
                   ('C2', 'C2 并联光耦 (F)', 1e-9, ['n', 'p', 'u'])],
    }

    def _build_comp_tab(self):
        f = self.tab_comp
        top = ttk.Frame(f, style='Guide.TFrame', padding='8 4')
        top.pack(fill='x', pady=(2, 4))
        self.guide_comp = ttk.Label(top, wraplength=1400, justify='left',
            text='⑨ 环路补偿电路参数: 由⑤页算出的 KP / 零点 fz / 极点 fp 反推阻容值。'
                 '只需填少量初始阻容 (分压/LED 等), 其余全部解出; '
                 '正向自动跟随⑤页二型/三型；二型保留有限高频极点，忽略未启用的第二零极点。'
                 '参考: TND381-D (TL431), Venable K-factor。',
            style='Guide.TLabel')
        self.guide_comp.pack(side='left', fill='x', expand=True)

        sel = ttk.LabelFrame(f, text='参考网络与计算方向', padding=4)
        sel.pack(fill='x', pady=2)
        choices = ttk.Frame(sel); choices.pack(fill='x')
        actions = ttk.Frame(sel); actions.pack(fill='x',pady=3)
        self.comp_type = tk.StringVar(value='opamp3')
        ttk.Combobox(choices, textvariable=self.comp_type, width=42,
                     values=[label for _k, label in self.COMP_TOPOS],
                     state='readonly').pack(side='left', padx=4)
        self.comp_type2 = tk.BooleanVar(value=False)
        self.chk_comp_t2 = ttk.Checkbutton(choices,text='旧版简化（不含高频极点）',variable=self.comp_type2)
        self.chk_comp_t2.pack(side='left', padx=10)
        # design direction: forward = constants -> parts, reverse = parts ->
        # constants (written back to tab 4, Bode plot follows)
        self.comp_dir = tk.StringVar(value='fwd')
        ttk.Radiobutton(actions, text='正向：参数→阻容',
                        variable=self.comp_dir, value='fwd',
                        command=self._on_comp_dir_change).pack(
            side='left', padx=(10, 2))
        ttk.Radiobutton(actions, text='反向：阻容→参数',
                        variable=self.comp_dir, value='rev',
                        command=self._on_comp_dir_change).pack(
            side='left', padx=2)
        self.btn_comp_fwd = ttk.Button(actions, text='计算阻容',
                                       style='Accent.TButton',
                                       command=self._run_comp_calc)
        self.btn_comp_fwd.pack(side='left', padx=8)
        self.btn_comp_rev = ttk.Button(actions, text='反推并写入⑤页',
                                       style='Accent.TButton',
                                       command=self._run_comp_reverse)
        self.comp_type.trace('w', lambda *a: self._rebuild_comp_inputs())

        self.comp_inframe = ttk.LabelFrame(f, text='用户初始阻容 (其余阻容由 KP/fz/fp 反推)', padding=4)
        self.comp_inframe.pack(fill='x', pady=2)
        self.comp_vars = {}
        self._on_comp_dir_change()

        self.comp_result = tk.StringVar(value='')
        res = ttk.LabelFrame(f, text='计算结果 (Results — 与⑤页一致性与设计提示)', padding=4)
        res.pack(fill='x', pady=2)
        ttk.Label(res, textvariable=self.comp_result, style='Result.TLabel',
                  wraplength=1000, justify='left').pack(side='left', fill='x', expand=True)

        # schematic view of the selected topology
        self.fig_comp, self.ax_comp = _subplots(figsize=(11.0, 3.2))
        self.canvas_comp = FigureCanvasTkAgg(self.fig_comp, master=f)
        self.canvas_comp.get_tk_widget().pack(fill='both', expand=True, pady=(2, 4))
        self.comp_type.trace('w', lambda *a: self._draw_comp_schematic())
        self.comp_type2.trace('w', lambda *a: self._draw_comp_schematic())
        self._draw_comp_schematic()

    def _on_comp_dir_change(self):
        """Direction switch: rebuild inputs and swap the action button."""
        rev = self.comp_dir.get() == 'rev'
        self.comp_inframe.configure(
            text=('输入补偿电路阻容值 (图上命名, 省略支路电容填 0)'
                  if rev else '用户初始阻容 (其余阻容由 KP/fz/fp 反推)'))
        if rev:
            self.btn_comp_fwd.pack_forget()
            self.btn_comp_rev.pack(side='left', padx=8)
            self.chk_comp_t2.state(['disabled'])
        else:
            self.btn_comp_rev.pack_forget()
            self.btn_comp_fwd.pack(side='left', padx=8)
            self.chk_comp_t2.state(['!disabled'])
        self._rebuild_comp_inputs()

    def _rebuild_comp_inputs(self):
        for w in self.comp_inframe.winfo_children():
            w.destroy()
        self.comp_vars = {}
        key = self._comp_key()
        specs = (self.COMP_REV_INPUTS[key] if self.comp_dir.get() == 'rev'
                 else self.COMP_INPUTS[key])
        r, c = 0, 0
        for pkey, label, default, units in specs:
            ttk.Label(self.comp_inframe, text=label).grid(
                row=r, column=c, sticky='w', padx=(10, 2), pady=2)
            v = tk.DoubleVar(value=default)
            ent = ttk.Entry(self.comp_inframe, textvariable=v, width=8)
            ent.grid(row=r, column=c + 1, padx=2)
            self.comp_vars[pkey] = v
            if units:
                u = tk.StringVar(value=('k' if default >= 1e3 and 'k' in units
                                        else ('n' if default >= 1e-9 and 'n' in units
                                              else ('m' if default < 1e-3 and 'm' in units else units[0]))))
                ttk.Combobox(self.comp_inframe, textvariable=u, width=3,
                             values=units, state='readonly').grid(row=r, column=c + 2, padx=(0, 8))
                self.comp_vars[pkey + '_unit'] = u
                v.set(default/self.units[u.get()])
            else:
                self.comp_vars[pkey + '_unit'] = tk.StringVar(value='')
            c += 3
            if c >= 9:
                c = 0
                r += 1

    def _comp_key(self):
        from compensation_report import network_key
        try:return network_key(self.comp_type.get())
        except ValueError:return 'opamp3'

    def _comp_in(self, pkey):
        """User comp input as SI."""
        v = float(self.comp_vars[pkey].get())
        u = self.comp_vars.get(pkey + '_unit')
        mult = self.units.get(u.get() if u else '', 1.0)
        return v * mult

    def _run_comp_calc(self):
        """Use the same active-order RC calculation as Web and reports."""
        p = self.get_params()
        if p.get('feedback_mode') == 'PSR-MP6005':
            self.comp_result.set('MP6005 使用①页物理 COMP 网络；不使用 SSR 参考电路。')
            return
        try:
            from compensation_report import compensation_snapshot, snapshot_lines
            state = self._comp_state()
            state['dir'] = 'fwd'
            if self._snapshot_valid and self._last and self._last['p'] == p:
                op = self._last['op']
            else:
                from voltage_nodes import output_drop
                op = dict(V_out=p['V_out'], V_feedback=p['V_out']+output_drop(p))
            data = compensation_snapshot(p, op, state)
            self.comp_result.set('   |   '.join(snapshot_lines(data)))
        except Exception as exc:
            self.comp_result.set('补偿计算 error: '+str(exc))

    def _run_comp_reverse(self):
        """Reverse mode: enter the compensator RC values (figure naming) ->
        derive KP / fz / fp -> write them back into the tab-4 controller
        entries so the loop Bode plot, margins and auto-tune fields follow."""
        if self.get_params().get('feedback_mode')=='PSR-MP6005':
            self.comp_result.set('MP6005 请在①页输入 Rcomp/Ccomp/Cpole；不把 SSR 电路参数写入 PSR。')
            return
        try:
            key = self._comp_key()
            vin = self._comp_in
            if key == 'opamp3':
                ev = compd.opamp_type3_eval(
                    vin('R1'), vin('R2'), vin('R3'),
                    vin('C1'), vin('C2'), vin('C3'))
            elif key == 'gm3':
                ev = compd.gm_type3_eval(
                    vin('gm'), vin('R1'), vin('R2'), vin('R3'),
                    vin('C1'), vin('C2'), vin('C3'))
            elif key == 'tl431nf':
                ev = compd.tl431_nf_eval(
                    vin('CTR'), vin('Rpullup'), vin('Copto'), vin('R_LED'),
                    vin('R1'), vin('R2'), vin('R3'),
                    vin('C1'), vin('C2'), vin('C3'))
            else:  # tl431f
                ev = compd.tl431_f_eval(
                    vin('CTR'), vin('Rpullup'), vin('Copto'), vin('R_LED'),
                    vin('R1'), vin('C1'), vin('R_pz'), vin('C_pz'), vin('C2'))
            from compensation_report import opamp_command_scale
            ev['KP'] *= opamp_command_scale(self.get_params(),key)
            if not ev['KP'] or not (ev['wz1'] > 0):
                raise ValueError('阻容值无效: KP/fz1 无法计算')
            updates = compd.controller_updates(ev)
            if updates['controller_type'] == 'type2':
                self.params['controller_type'].set('type2')
                for name in ('KP','fz1','fp1'):
                    self.set_param(name, updates[name])
                self.schedule_update()
                self.comp_result.set(f"标准二型已写入⑤页：KP={updates['KP']:.6g}，"
                    f"fz1={fmt_eng(updates['fz1'],'Hz')}，fp1={fmt_eng(updates['fp1'],'Hz')}；"
                    '第二零极点未启用，无需远端抵消。')
                return
            # write back to the tab-4 controller entries.  A missing corner
            # (type-II network) maps to a very high frequency; the matching
            # zero/pole pair then cancels inside the 3P3Z form.
            FAR = 1e9
            corners = {'KP': ev['KP'],
                       'fz1': ev['wz1'] / (2 * np.pi),
                       'fz2': (ev['wz2'] / (2 * np.pi)
                               if np.isfinite(ev['wz2']) else FAR),
                       'fp1': (ev['wp1'] / (2 * np.pi)
                               if np.isfinite(ev['wp1']) else FAR),
                       'fp2': (ev['wp2'] / (2 * np.pi)
                               if np.isfinite(ev['wp2']) else FAR)}
            for k, v in corners.items():
                self.set_param(k, v)
            self.schedule_update()          # redraw ④ margins / Bode
            # controller type hint: a cancelled pair behaves as type 2
            cancelled = (not np.isfinite(ev['wz2'])
                         and not np.isfinite(ev['wp2']))
            hint = ('二型网络: fz2/fp2 已同置 1e9 Hz 相互抵消 (等效 type 2)'
                    if cancelled else '三型网络: 四个零极点已全部写入')
            self.comp_result.set(
                f"反推结果 → 已写入⑤页:  KP = {ev['KP']:.4g}   "
                f"fz1 = {fmt_eng(corners['fz1'], 'Hz')}   "
                f"fz2 = {fmt_eng(corners['fz2'], 'Hz')}   "
                f"fp1 = {fmt_eng(corners['fp1'], 'Hz')}   "
                f"fp2 = {fmt_eng(corners['fp2'], 'Hz')}   |   {hint}   |   "
                "环路 Bode 图/裕度已更新 (切到⑤页查看)")
        except Exception as e:
            self.comp_result.set(f'反推 error: {e}')

    def _update_comp(self, op, p):
        """Tab ⑧ auto-refresh: forward mode recomputes from the tab-4
        constants; reverse mode only redraws the reference figure (the
        entered RC values and the last reverse result are kept)."""
        try:
            if self.comp_vars:
                if self.comp_dir.get() != 'rev':
                    self._run_comp_calc()
                self._draw_comp_schematic()
        except Exception:
            pass

    # ------------------------------------------ reference figure view (⑧)
    def _draw_comp_schematic(self):
        """Show the reference figure of the selected topology (naming on the
        figure matches the solved part names)."""
        ax = self.ax_comp
        ax.clear()
        ax.axis('off')
        key = self._comp_key()
        fn = resource_path(os.path.join('comp_images',
                                        self.COMP_IMAGES[key]))
        try:
            img = imread(fn)
            ax.imshow(img)
        except Exception as e:
            ax.text(0.5, 0.5, f'参考图加载失败: {fn}\n{e}', ha='center',
                    va='center', transform=ax.transAxes, color=BAD)
        self.fig_comp.tight_layout(pad=0.4)
        _draw_canvas(self.canvas_comp)

    # ============================================================ efficiency
    def _build_eff_tab(self):
        f = self.tab_eff
        top = ttk.Frame(f, style='Guide.TFrame', padding='8 4')
        top.pack(fill='x', pady=(2, 4))
        self.guide_eff = ttk.Label(top, text=STEP_GUIDE[4],
                                   style='Guide.TLabel')
        self.guide_eff.pack(side='left')

        self.fig_loss, (self.ax_lbreak, self.ax_eta) = _subplots(
            1, 2, figsize=(11.5, 3.4))
        self.fig_loss.set_layout_engine('constrained')
        self.canvas_loss = FigureCanvasTkAgg(self.fig_loss, master=f)
        self.canvas_loss.get_tk_widget().pack(fill='x', pady=(2, 4))
        self.loss_summary = tk.StringVar(value='')
        ttk.Label(f, textvariable=self.loss_summary, foreground='#1a5fb4',
                  wraplength=1500, justify='left').pack(fill='x')
        ttk.Label(f, text=ETA_NOTE, style='Warn.TLabel', wraplength=1500,
                  justify='left').pack(fill='x')

        sweep = ttk.LabelFrame(f, text='Parameter sweep (参数扫描)', padding=4)
        sweep.pack(fill='x', pady=4)
        ttk.Label(sweep, text='Variable (变量):').pack(side='left')
        self.sweep_combo = ttk.Combobox(sweep, width=26, state='readonly')
        self.sweep_combo.pack(side='left', padx=4)
        self.sweep_combo.bind('<<ComboboxSelected>>', lambda e: self.on_sweep_var_change())
        ttk.Label(sweep, text='from (从):').pack(side='left')
        ttk.Entry(sweep, textvariable=self.params['sweep_min'], width=7).pack(side='left')
        ttk.Combobox(sweep, textvariable=self.params['sweep_min_unit'],
                     values=['n', 'u', 'm', '', 'k', 'M'], width=3,
                     state='readonly').pack(side='left')
        ttk.Label(sweep, text='to (到):').pack(side='left', padx=(8, 2))
        ttk.Entry(sweep, textvariable=self.params['sweep_max'], width=7).pack(side='left')
        ttk.Combobox(sweep, textvariable=self.params['sweep_max_unit'],
                     values=['n', 'u', 'm', '', 'k', 'M'], width=3,
                     state='readonly').pack(side='left')
        ttk.Label(sweep, text='pts (点数):').pack(side='left', padx=(8, 2))
        ttk.Entry(sweep, textvariable=self.params['sweep_n'], width=4).pack(side='left')
        ttk.Button(sweep, text='Run sweep (运行扫描)', style='Accent.TButton',
                   command=self.run_sweep).pack(side='left', padx=8)
        ttk.Button(sweep, text='Find target (查找目标)', command=self.find_target).pack(side='left', padx=2)
        ttk.Button(sweep, text='Optimize, max η (效率优化)', style='Accent.TButton',
                   command=self.run_optimize).pack(side='left', padx=8)
        ttk.Button(sweep, text='取消计算', command=self.cancel_calculation).pack(side='left', padx=2)
        ttk.Label(sweep, text='load (负载):').pack(side='left', padx=(8, 2))
        ttk.Entry(sweep, textvariable=self.params['load_frac'], width=4).pack(side='left')
        ttk.Label(sweep, text='target η:').pack(side='left', padx=(8, 2))
        ttk.Entry(sweep, textvariable=self.params['target_eta'], width=5).pack(side='left')

        self.fig_opt, self.ax_opt = _subplots(figsize=(11.5, 3.0))
        self.canvas_opt = FigureCanvasTkAgg(self.fig_opt, master=f)
        self.canvas_opt.get_tk_widget().pack(fill='both', expand=True)
        self.opt_result = tk.StringVar(value='')
        ttk.Label(f, textvariable=self.opt_result, foreground='#1a5fb4',
                  wraplength=1500, justify='left').pack(fill='x', pady=2)

    def _update_eff(self, op, p, res):
        try:
            ax1, ax2 = self.ax_lbreak, self.ax_eta
            ax1.clear()
            names = ['半导体', '磁件', '输入电容 ESR', '输出电容 ESR', '采样电阻', 'RCD 钳位',
                     '输入防反', '输出防反']
            vals = [res['P_semi'],
                    res['P_mag'] if np.isfinite(res['P_mag']) else 0,
                    res['P_cap_in'], res['P_cap'], res['P_sense'], res.get('P_rcd', 0.0),
                    res.get('P_din', 0.0), res.get('P_dout', 0.0)]
            if op['topology'] == 'ACF-FORWARD':
                names[5], vals[5] = '钳位电容 ESR', res.get('P_clamp', 0)
            if res.get('psr'):
                names.append('MP6005 静态/分压'); vals.append(res['P_controller'])
            if res.get('P_parasitic',0):
                names.append('布线 / RC 吸收电阻'); vals.append(res['P_parasitic'])
            _loss_bars(ax1, names, vals, f'损耗分解 · 合计 {res["P_total"]:.3f} W',
                       ['#c0392b','#8e44ad','#3498db','#2980b9','#27ae60','#e67e22','#16a085','#d35400'])

            signature = parameter_signature(p)
            if signature != self._eff_curve_signature and not self._export_after_calculation:
                self._eff_curve_signature = signature
                self._eff_curve_result = None
                if str(self.cross_button.cget('state')) == 'disabled':
                    self._mark_cross_regulation_stale()
                self._calculation_worker.submit('efficiency', p,
                                               calculate_efficiency_curve, cache=True)
                self._ensure_calculation_poll()
            self._render_efficiency_curve()

            topo = op['topology']
            if True:
                rhp_s = (fmt_eng(op['rhp_zero'], 'Hz')
                         if np.isfinite(op['rhp_zero']) else '无')
                extra = (f"D={op['D']:.3f}, mode={op['mode']}, "
                         f"RHP zero (右半平面零点) = {rhp_s}")
            self.loss_summary.set(
                f"预设 η={op['eta_guess']*100:.2f}% → 最终计算 η={res['eta']*100:.2f}% "
                f"(差值 {res['eta_delta']*100:+.2f} 个百分点) | "
                f"预估/损耗反算 Pin={op['P_in_est']:.3f}/{res['P_in']:.3f} W | 总损耗 {res['P_total']:.3f} W | "
                f"半导体 {res['P_semi']:.3f} + 磁件 {res['P_mag']:.3f} + 电容(入/出) {res['P_cap_in']:.3f}/{res['P_cap']:.3f} "
                f"+ 采样 {res['P_sense']:.3f} + RCD {res.get('P_rcd', 0.0):.3f}"
                f" + 防反二极管(入/出) {res.get('P_din', 0.0):.3f}/{res.get('P_dout', 0.0):.3f} W"
                f" + 有源钳位电容 ESR {res.get('P_clamp',0):.3f} W"
                f"   |   {extra}")
            _draw_canvas(self.canvas_loss)
        except Exception as e:
            import traceback
            traceback.print_exc()
            self.status_var.set(f'Loss: {e}')

    def _render_efficiency_curve(self):
        ax = self.ax_eta
        ax.clear()
        curve = self._eff_curve_result
        if curve and 'error' not in curve:
            fracs, etas = curve['fracs'], curve['etas']
            ax.plot(fracs * 100, etas * 100, 'o-', lw=1.2)
            finite = etas[np.isfinite(etas)]
            lo_ylim = (finite.min() - .05) if finite.size else .5
            ax.set_ylim(max(.05, lo_ylim) * 100, 100)
            if curve['failures']:
                ax.text(.02, .03, f"{len(curve['failures'])} 个负载点无有效解，已留空",
                        transform=ax.transAxes, fontsize=8, color=BAD,
                        bbox=dict(facecolor='white', alpha=.85, edgecolor='none'))
        else:
            text = ('负载曲线计算失败：' + curve['error']) if curve else '负载曲线正在后台逐点计算…\n可切换页面或继续编辑'
            if not curve and self._export_after_calculation:
                text = '正在准备报告负载曲线…\n本页曲线可在报告完成后重新进入计算'
            ax.text(.5, .5, text, ha='center', va='center', wrap=True,
                    transform=ax.transAxes, fontsize=9)
            if self._last and self._snapshot_valid:
                ax.plot([100], [self._last['res']['eta'] * 100], 'o', color=ACCENT)
        ax.set_title('效率与负载', fontsize=10, pad=9)
        ax.set_xlabel('负载 / %', fontsize=9)
        ax.set_ylabel('效率 / %', fontsize=9)
        ax.tick_params(labelsize=8)
        ax.grid(True)

    def on_sweep_var_change(self):
        """Reset sweep bounds around the current value of the chosen variable."""
        var = self._sweep_key()
        try:
            base = self.get_param(var)
        except KeyError:
            return
        if base <= 0:
            return
        units = ['p', 'n', 'u', 'm', '', 'k', 'M']
        for key, scale in (('sweep_min', 0.5), ('sweep_max', 2.0)):
            v = base * scale
            exp = int(np.floor(np.log10(abs(v)) / 3))
            exp = max(-4, min(2, exp))
            u = units[exp + 4]
            self.params[key].set(v / self.units[u])
            self.params[key + '_unit'].set(u)

    def _sweep_bounds(self):
        lo = self.params['sweep_min'].get() * self.units[self.params['sweep_min_unit'].get()]
        hi = self.params['sweep_max'].get() * self.units[self.params['sweep_max_unit'].get()]
        n = max(3, int(self.params['sweep_n'].get()))
        return lo, hi, n

    def run_sweep(self):
        self._start_optimization_job('sweep')

    def find_target(self):
        self._start_optimization_job('target')

    def run_optimize(self):
        self._start_optimization_job('optimize')

    def cancel_calculation(self):
        self._calculation_worker.invalidate()
        if self._design_ready_job is not None:
            self.root.after_cancel(self._design_ready_job)
            self._design_ready_job = None
        if self.update_timer is not None:
            self.root.after_cancel(self.update_timer)
            self.update_timer = None
        self._eff_curve_signature = None
        self._eff_curve_result = None
        self._export_after_calculation = False
        self.opt_result.set('后台计算已取消；已完成的当前设计保持不变。')
        self.status_var.set('计算已取消；尚未完成的新参数没有可用结果。' if not self._snapshot_valid
                            else '后台扫描 / 负载曲线已取消。')
        if self._snapshot_valid:
            self._rendered_tabs.discard(self.nb.index(self.tab_eff))
            self.ax_eta.clear()
            self.ax_eta.text(.5, .5, '负载曲线已取消；重新进入本页可重新计算',
                             ha='center', va='center', transform=self.ax_eta.transAxes,
                             fontsize=9)
            _draw_canvas(self.canvas_loss)

    def _start_optimization_job(self, kind):
        try:
            if not self._snapshot_valid:
                self.opt_result.set('当前参数仍待计算，请先等待设计计算完成。')
                self.request_update()
                return
            p = self.get_params()
            p.update(self._rcd_parameters())
            lo, hi, n = self._sweep_bounds()
            request = dict(kind=kind, p=p, var=self._sweep_key(), lo=lo, hi=hi,
                           n=n, frac=self.params['load_frac'].get(),
                           target=self.params['target_eta'].get())
            self._export_after_calculation = False
            if str(self.cross_button.cget('state')) == 'disabled':
                self._mark_cross_regulation_stale()
            self._calculation_worker.submit(kind, request, calculate_optimization)
            if self._eff_curve_result is None:
                self._eff_curve_signature = None
                self._rendered_tabs.discard(self.nb.index(self.tab_eff))
                self.ax_eta.clear()
                self.ax_eta.text(.5, .5, '负载曲线已暂停，让位于参数分析；\n完成后重新进入本页可更新',
                                 ha='center', va='center', transform=self.ax_eta.transAxes,
                                 fontsize=9)
                _draw_canvas(self.canvas_loss)
            self.opt_result.set('正在后台优化… 可继续编辑或取消。' if kind == 'optimize'
                                else f'正在后台逐点扫描 {n} 个参数点… 可继续编辑或取消。')
            self._ensure_calculation_poll()
        except Exception as error:
            self.opt_result.set(f'分析参数: {error}')

    def _finish_optimization_job(self, job):
        request = job.parameters
        if not self._snapshot_valid or self._last is None or request['p'] != self._last['p']:
            return
        if job.error is not None:
            self.opt_result.set(f'后台分析失败: {job.error}')
            return
        if job.kind == 'optimize':
            result = job.value
            msg = [f"最大效率 max η = {result['eta'] * 100:.2f}% (负载 {request['frac'] * 100:.0f}%)"]
            msg.extend(f"{key} = {fmt_eng(value, '')}" for key, value in result['best'].items())
            self.opt_result.set('   |   '.join(msg))
            self.ax_opt.clear()
            self.ax_opt.text(.05, .5, '\n'.join(msg), transform=self.ax_opt.transAxes,
                             fontsize=13, va='center')
            self.ax_opt.axis('off')
            _draw_canvas(self.canvas_opt)
            return
        self._show_sweep_result(request, job.value, find=job.kind == 'target')

    def _show_sweep_result(self, request, result, *, find=False):
        try:
            var, frac = request['var'], request['frac']
            values, etas = result['values'], result['etas']
            ax = self.ax_opt
            ax.clear()
            if var in opt._LOG_VARS:
                ax.semilogx(values, etas * 100, 'o-', lw=1.2)
            else:
                ax.plot(values, etas * 100, 'o-', lw=1.2)
            target = request['target']
            ax.axhline(target * 100, color='r', ls='--', lw=1,
                       label=f'target {target * 100:.0f}% (目标)')
            ax.set_title(f'Efficiency vs {var} (效率-参数曲线, 负载 {frac * 100:.0f}%)')
            ax.set_xlabel(var); ax.set_ylabel('η, % (效率)')
            ax.legend(); ax.grid(True)
            _draw_canvas(self.canvas_opt)
            ok = np.isfinite(etas)
            if find:
                found = opt.find_target(values, etas, target)
                if found is not None:
                    ax.axvline(found, color='g', ls='--', lw=1)
                    _draw_canvas(self.canvas_opt)
                    self.opt_result.set(f'{var} = {fmt_eng(found, "")} 达到 η = {target * 100:.1f}% '
                                        f'(负载 {frac * 100:.0f}%)')
                    self.set_param(var, found)
                else:
                    self.opt_result.set(f'目标 {target * 100:.0f}% 未达到' +
                        (f' — 范围内最大 η={etas[ok].max()*100:.1f}%' if ok.any() else '：所有点无效'))
                return
            if ok.any():
                self.opt_result.set(
                    f'扫描 {var}: η {etas[ok].min() * 100:.1f}..{etas[ok].max() * 100:.1f}% '
                    f'(在 {var} = {fmt_eng(values[ok][np.argmax(etas[ok])], "")} 处最大)')
            else:
                self.opt_result.set('扫描失败: 所有点无效')
        except Exception as error:
            self.opt_result.set(f'显示扫描: {error}')
