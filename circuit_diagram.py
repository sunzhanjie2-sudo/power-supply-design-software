"""Graphical closed-loop circuit diagrams for the five topologies.

Renders a schematic (using matplotlib primitives) and provides hit-testing so
the GUI can let the user *click a component* to edit its parameters or view
its waveforms.  Each topology is described declaratively by:

  COMPONENTS[topo] = [ {id, kind, label, name, x, y, r, params, waves, mag}, ... ]
  WIRES[topo]      = [ (x1,y1, x2,y2), ... ]    (straight segments)
  NODES[topo]      = [ (x,y), ... ]             (junction dots)

`params` lists (key, label_zh, unit, [unit options]) that map straight onto
the GUI parameter store (self.params).  `waves` lists (wf_key, label_zh) of
signals shown when the component is clicked after a run.  `mag=True` adds the
flux-density B(t) waveform for inductors / transformers.
"""

import numpy as np
import matplotlib.pyplot as plt
from matplotlib.patches import Circle, Rectangle, Polygon, Arc

# palette
WIRE = '#4a5560'
COMP = '#1c2733'
ACCENT = '#1558b0'
HILITE = '#d7263d'

# common param lists (referenced by the topology definitions below)
P_SOURCE = [('V_in', '输入电压 Vin', 'V', ['', 'm'])]
P_LOAD = [('V_out', '输出电压 Vout', 'V', ['', 'm']),
          ('P_out', '输出功率 Pout', 'W', ['', 'm'])]
P_MOSFET = [('Rds_on', '导通电阻 Rds(on)', 'Ω', ['m', '']),
            ('tr', '上升时间 tr', 's', ['n']),
            ('tf', '下降时间 tf', 's', ['n']),
            ('Coss', '输出电容 Coss', 'F', ['p', 'n']),
            ('Qg', '栅极电荷 Qg', 'C', ['n'])]
P_DIODE = [('Vf_diode', '正向压降 Vf', 'V', ['', 'm']),
           ('Rd_diode', '动态电阻 Rd', 'Ω', ['m', '']),
           ('Qrr', '反向恢复电荷 Qrr', 'C', ['n'])]
P_CAP = [('C_out', '电容 C', 'F', ['n', 'u', 'm']),
         ('Rc', '等效串联电阻 ESR', 'Ω', ['m', '']),
         ('ESL', '等效串联电感 ESL', 'H', ['n', 'p'])]
P_IND = [('L', '电感量 L', 'H', ['n', 'u', 'm'])]
P_FLYBACK_TX = [('core_choice', '磁芯', 'core', None),
                ('L', '励磁感量 Lm', 'H', ['u', 'm', 'n']),
                ('N', '匝比 Np/Ns', '', None)]
P_LLC_TX = [('core_choice', '磁芯', 'core', None),
            ('n', '匝比 n', '', None),
            ('Ln', '电感比 Ln', '', None)]
P_CTRL = [('KP', '补偿器增益 KP', '', None),
          ('fz1', '零点 fz1', 'Hz', ['', 'k', 'M']),
          ('fp1', '极点 fp1', 'Hz', ['', 'k', 'M'])]


def _mosfet_waves(label='Q1'):
    return [('i_sw', '开关管电流 i_sw'), ('v_sw', '开关管电压 v_sw')]


def _diode_waves():
    return [('i_d', '二极管电流 i_d'), ('v_d', '二极管电压 v_d')]


# ----------------------------------------------------------------------------
# Topology definitions
# ----------------------------------------------------------------------------
COMPONENTS = {
    'BUCK': [
        dict(id='vin', kind='source', label='Vin', name='输入电源',
             x=1.3, y=5.2, r=0.45, params=P_SOURCE,
             waves=[('vout', '输出电压 Vout'), ('i_sw', '输入电流 i_in')]),
        dict(id='q1', kind='mosfet', label='Q1', name='开关管 MOSFET',
             x=3.3, y=4.3, r=0.55, params=P_MOSFET, waves=_mosfet_waves('Q1')),
        dict(id='d1', kind='diode', label='D1', name='续流二极管',
             x=3.3, y=1.7, r=0.5, params=P_DIODE, waves=_diode_waves()),
        dict(id='l1', kind='inductor', label='L1', name='电感',
             x=5.6, y=3.4, r=0.6, params=P_IND,
             waves=[('iL', '电感电流 iL'), ('iL', '纹波电流')], mag=True),
        dict(id='c1', kind='capacitor', label='C1', name='输出电容',
             x=7.2, y=1.7, r=0.5, params=P_CAP,
             waves=[('i_c', '电容纹波电流 i_c'), ('vout_ripple', '输出纹波电压')]),
        dict(id='rload', kind='resistor', label='Rload', name='负载电阻',
             x=8.9, y=3.4, r=0.5, params=P_LOAD,
             waves=[('vout', '输出电压 Vout')]),
        dict(id='ctrl', kind='controller', label='Ctrl', name='控制器 (补偿器+PWM)',
             x=11.4, y=5.4, r=0.9, params=P_CTRL, waves=[]),
    ],
    'BOOST': [
        dict(id='vin', kind='source', label='Vin', name='输入电源',
             x=1.3, y=4.6, r=0.45, params=P_SOURCE,
             waves=[('vout', '输出电压 Vout')]),
        dict(id='l1', kind='inductor', label='L1', name='电感',
             x=3.3, y=3.6, r=0.6, params=P_IND,
             waves=[('iL', '电感电流 iL')], mag=True),
        dict(id='q1', kind='mosfet', label='Q1', name='开关管 MOSFET',
             x=4.9, y=1.8, r=0.55, params=P_MOSFET, waves=_mosfet_waves('Q1')),
        dict(id='d1', kind='diode', label='D1', name='输出二极管',
             x=6.3, y=3.9, r=0.5, params=P_DIODE, waves=_diode_waves()),
        dict(id='c1', kind='capacitor', label='C1', name='输出电容',
             x=7.9, y=1.7, r=0.5, params=P_CAP,
             waves=[('i_c', '电容纹波电流 i_c'), ('vout_ripple', '输出纹波电压')]),
        dict(id='rload', kind='resistor', label='Rload', name='负载电阻',
             x=9.6, y=3.4, r=0.5, params=P_LOAD,
             waves=[('vout', '输出电压 Vout')]),
        dict(id='ctrl', kind='controller', label='Ctrl', name='控制器 (补偿器+PWM)',
             x=11.9, y=5.4, r=0.9, params=P_CTRL, waves=[]),
    ],
    'BUCK-BOOST': [
        dict(id='vin', kind='source', label='Vin', name='输入电源',
             x=1.3, y=5.0, r=0.45, params=P_SOURCE,
             waves=[('vout', '输出电压 Vout')]),
        dict(id='q1', kind='mosfet', label='Q1', name='开关管 MOSFET',
             x=3.2, y=4.2, r=0.55, params=P_MOSFET, waves=_mosfet_waves('Q1')),
        dict(id='l1', kind='inductor', label='L1', name='电感',
             x=5.3, y=3.2, r=0.6, params=P_IND,
             waves=[('iL', '电感电流 iL')], mag=True),
        dict(id='d1', kind='diode', label='D1', name='输出二极管',
             x=6.9, y=4.1, r=0.5, params=P_DIODE, waves=_diode_waves()),
        dict(id='c1', kind='capacitor', label='C1', name='输出电容',
             x=8.4, y=1.7, r=0.5, params=P_CAP,
             waves=[('i_c', '电容纹波电流 i_c'), ('vout_ripple', '输出纹波电压')]),
        dict(id='rload', kind='resistor', label='Rload', name='负载电阻',
             x=10.1, y=3.4, r=0.5, params=P_LOAD,
             waves=[('vout', '输出电压 Vout')]),
        dict(id='ctrl', kind='controller', label='Ctrl', name='控制器 (补偿器+PWM)',
             x=12.3, y=5.4, r=0.9, params=P_CTRL, waves=[]),
    ],
    'FLYBACK': [
        dict(id='vin', kind='source', label='Vin', name='输入电源',
             x=1.3, y=5.2, r=0.45, params=P_SOURCE,
             waves=[('vout', '输出电压 Vout')]),
        dict(id='q1', kind='mosfet', label='Q1', name='开关管 MOSFET',
             x=3.3, y=4.3, r=0.55, params=P_MOSFET, waves=_mosfet_waves('Q1')),
        dict(id='tx', kind='transformer', label='T1', name='变压器',
             x=5.4, y=4.0, r=0.85, params=P_FLYBACK_TX,
             waves=[('i_p', '原边/励磁电流 i_p'), ('i_s', '副边电流 i_s')],
             mag=True),
        dict(id='d1', kind='diode', label='D1', name='输出整流二极管',
             x=7.6, y=4.0, r=0.5, params=P_DIODE, waves=_diode_waves()),
        dict(id='c1', kind='capacitor', label='C1', name='输出电容',
             x=9.0, y=1.7, r=0.5, params=P_CAP,
             waves=[('i_c', '电容纹波电流 i_c'), ('vout_ripple', '输出纹波电压')]),
        dict(id='rload', kind='resistor', label='Rload', name='负载电阻',
             x=10.6, y=3.4, r=0.5, params=P_LOAD,
             waves=[('vout', '输出电压 Vout')]),
        dict(id='ctrl', kind='controller', label='Ctrl', name='控制器 (补偿器+PWM)',
             x=12.4, y=5.4, r=0.9, params=P_CTRL, waves=[]),
    ],
    'LLC': [
        dict(id='vin', kind='source', label='Vin', name='输入电源',
             x=1.2, y=5.2, r=0.45, params=P_SOURCE,
             waves=[('vout', '输出电压 Vout')]),
        dict(id='q1', kind='mosfet', label='Q1', name='全桥开关 Q1',
             x=2.9, y=5.3, r=0.5, params=P_MOSFET, waves=_mosfet_waves('Q1')),
        dict(id='q2', kind='mosfet', label='Q2', name='全桥开关 Q2',
             x=2.9, y=1.6, r=0.5, params=P_MOSFET, waves=_mosfet_waves('Q2')),
        dict(id='q3', kind='mosfet', label='Q3', name='全桥开关 Q3',
             x=4.5, y=5.3, r=0.5, params=P_MOSFET, waves=_mosfet_waves('Q3')),
        dict(id='q4', kind='mosfet', label='Q4', name='全桥开关 Q4',
             x=4.5, y=1.6, r=0.5, params=P_MOSFET, waves=_mosfet_waves('Q4')),
        dict(id='lr', kind='inductor', label='Lr', name='谐振电感',
             x=6.0, y=3.6, r=0.55, params=[('fr', '谐振频率 fr', 'Hz', ['', 'k', 'M']),
                                            ('Q', '品质因数 Q', '', None)],
             waves=[('i_r', '谐振电流 i_r'), ('i_r', '谐振电流纹波')], mag=True),
        dict(id='cr', kind='capacitor', label='Cr', name='谐振电容',
             x=7.0, y=1.7, r=0.5, params=[('fr', '谐振频率 fr', 'Hz', ['', 'k', 'M']),
                                           ('Q', '品质因数 Q', '', None)],
             waves=[('i_r', '谐振电流 i_r')]),
        dict(id='tx', kind='transformer', label='T1', name='谐振变压器',
             x=8.2, y=3.6, r=0.85, params=P_LLC_TX,
             waves=[('i_p', '原边谐振电流 i_r'), ('i_sec', '副边电流 i_sec')],
             mag=True),
        dict(id='d1', kind='diode', label='D1', name='整流二极管 D1',
             x=10.0, y=4.6, r=0.45, params=P_DIODE, waves=[('i_d1', '二极管 D1 电流')]),
        dict(id='d2', kind='diode', label='D2', name='整流二极管 D2',
             x=10.0, y=2.6, r=0.45, params=P_DIODE, waves=[('i_d2', '二极管 D2 电流')]),
        dict(id='c1', kind='capacitor', label='C1', name='输出电容',
             x=11.6, y=1.6, r=0.5, params=P_CAP,
             waves=[('i_c', '电容纹波电流 i_c'), ('vout_ripple', '输出纹波电压')]),
        dict(id='rload', kind='resistor', label='Rload', name='负载电阻',
             x=13.0, y=3.4, r=0.45, params=P_LOAD,
             waves=[('vout', '输出电压 Vout')]),
        dict(id='ctrl', kind='controller', label='Ctrl', name='控制器 (变频 VCO)',
             x=1.2, y=6.4, r=0.9, params=P_CTRL, waves=[]),
    ],
}

# straight wire segments (x1, y1, x2, y2)
WIRES = {
    'BUCK': [
        (1.3, 5.65, 1.3, 4.75), (1.3, 4.75, 3.3, 4.75),   # Vin+ -> Q1 drain
        (3.3, 3.75, 3.3, 2.2), (3.3, 1.2, 3.3, 1.2),       # Q1 source -> diode
        (3.3, 3.75, 5.6, 3.4), (5.6, 3.4, 7.2, 3.4),       # node -> L -> out
        (7.2, 3.4, 8.9, 3.4),                               # out -> load
        (7.2, 2.2, 7.2, 1.2), (7.2, 1.2, 3.3, 1.2),        # cap low -> gnd
        (8.9, 2.9, 8.9, 1.2), (8.9, 1.2, 7.2, 1.2),        # load low -> gnd
        (3.3, 1.2, 3.3, 1.2),
        (7.2, 3.4, 11.4, 3.4), (11.4, 3.4, 11.4, 4.5),     # feedback
        (11.4, 6.3, 3.3, 6.3), (3.3, 6.3, 3.3, 4.85),      # gate drive
    ],
    'BOOST': [
        (1.3, 5.05, 1.3, 4.15), (1.3, 4.15, 3.3, 3.6),
        (3.3, 3.6, 4.9, 3.6), (4.9, 3.6, 6.3, 3.9),
        (6.3, 3.9, 7.9, 3.4), (7.9, 3.4, 9.6, 3.4),
        (4.9, 3.6, 4.9, 2.35), (4.9, 1.2, 4.9, 1.25),
        (7.9, 2.2, 7.9, 1.2), (7.9, 1.2, 4.9, 1.2),
        (9.6, 2.9, 9.6, 1.2), (9.6, 1.2, 7.9, 1.2),
        (7.9, 3.4, 11.9, 3.4), (11.9, 3.4, 11.9, 4.5),
        (11.9, 6.3, 4.9, 6.3), (4.9, 6.3, 4.9, 2.35),
    ],
    'BUCK-BOOST': [
        (1.3, 5.45, 1.3, 4.75), (1.3, 4.75, 3.2, 4.75),
        (3.2, 3.65, 3.2, 2.6), (3.2, 2.6, 5.3, 3.2),
        (5.3, 3.2, 6.9, 3.2), (6.9, 3.2, 6.9, 4.6),
        (6.9, 4.6, 8.4, 3.4), (8.4, 3.4, 10.1, 3.4),
        (3.2, 2.6, 3.2, 1.2), (3.2, 1.2, 8.4, 1.2),
        (8.4, 2.2, 8.4, 1.2), (10.1, 2.9, 10.1, 1.2),
        (10.1, 1.2, 8.4, 1.2),
        (8.4, 3.4, 12.3, 3.4), (12.3, 3.4, 12.3, 4.5),
        (12.3, 6.3, 3.2, 6.3), (3.2, 6.3, 3.2, 4.85),
    ],
    'FLYBACK': [
        (1.3, 5.65, 1.3, 4.85), (1.3, 4.85, 3.3, 4.85),
        (3.3, 3.75, 3.3, 2.6), (3.3, 2.6, 4.55, 4.0),       # Q1 source -> T1 pri
        (5.4, 4.0, 6.25, 4.0), (6.25, 4.0, 7.6, 4.0),       # T1 sec -> D1
        (7.6, 4.0, 9.0, 3.4), (9.0, 3.4, 10.6, 3.4),
        (4.55, 4.0, 3.3, 1.2), (3.3, 1.2, 9.0, 1.2),        # pri return
        (9.0, 2.2, 9.0, 1.2), (10.6, 2.9, 10.6, 1.2),
        (10.6, 1.2, 9.0, 1.2),
        (9.0, 3.4, 12.4, 3.4), (12.4, 3.4, 12.4, 4.5),
        (12.4, 6.3, 3.3, 6.3), (3.3, 6.3, 3.3, 4.85),
    ],
    'LLC': [
        (1.2, 5.65, 1.2, 5.05), (1.2, 5.05, 2.9, 5.3),
        (2.9, 5.3, 4.5, 5.3), (4.5, 5.3, 6.0, 3.6),
        (2.9, 4.8, 2.9, 1.9), (2.9, 1.6, 2.9, 1.2),
        (4.5, 4.8, 4.5, 1.9), (4.5, 1.6, 4.5, 1.2),
        (2.9, 1.2, 4.5, 1.2), (1.2, 4.75, 1.2, 1.2),
        (1.2, 1.2, 2.9, 1.2),
        (6.0, 3.6, 7.0, 3.6), (7.0, 3.6, 8.2, 3.6),        # Lr -> Cr -> T1
        (7.0, 2.2, 7.0, 1.2), (7.0, 1.2, 2.9, 1.2),         # Cr low
        (8.2, 3.6, 10.0, 4.6), (8.2, 3.6, 10.0, 2.6),       # T1 sec CT
        (10.0, 4.6, 11.6, 3.4), (10.0, 2.6, 11.6, 3.4),
        (11.6, 3.4, 13.0, 3.4),
        (8.2, 3.6, 8.2, 1.2), (8.2, 1.2, 11.6, 1.2),        # CT return
        (11.6, 2.1, 11.6, 1.2), (13.0, 2.95, 13.0, 1.2),
        (13.0, 1.2, 11.6, 1.2),
        (11.6, 3.4, 1.2, 3.4), (1.2, 3.4, 1.2, 5.6),        # feedback
        (1.2, 7.3, 4.5, 7.3), (4.5, 7.3, 4.5, 5.8), (2.9, 7.3, 2.9, 5.8),
    ],
}

# ground symbols and junction dots per topology
GROUNDS = {
    'BUCK': [(3.3, 1.2)],
    'BOOST': [(4.9, 1.2)],
    'BUCK-BOOST': [(3.2, 1.2)],
    'FLYBACK': [(3.3, 1.2)],
    'LLC': [(2.9, 1.2), (7.0, 1.2)],
}


# ----------------------------------------------------------------------------
# Symbol drawing helpers
# ----------------------------------------------------------------------------
def _seg(ax, pts, color=WIRE, lw=1.6):
    ax.plot([p[0] for p in pts], [p[1] for p in pts], color=color, lw=lw,
            solid_capstyle='round', zorder=3)


def _dot(ax, x, y, color=WIRE, r=0.06):
    ax.add_patch(Circle((x, y), r, fc=color, ec='none', zorder=5))


def draw_source(ax, x, y, r=0.45):
    ax.add_patch(Circle((x, y), r, fc='white', ec=COMP, lw=1.8, zorder=4))
    ax.plot([x - 0.18, x + 0.18], [y, y], color=COMP, lw=1.4, zorder=5)
    ax.plot([x, x], [y - 0.16, y + 0.16], color=COMP, lw=1.4, zorder=5)
    ax.plot([x, x], [y + 0.34, y + 0.16], color=COMP, lw=1.4, zorder=5)
    _seg(ax, [(x, y + r), (x, y + r + 0.35)], color=WIRE)
    _seg(ax, [(x, y - r), (x, y - r - 0.35)], color=WIRE)


def draw_mosfet(ax, x, y, vertical=True, r=0.5):
    """N-channel MOSFET: gate (left), channel (vertical), body diode."""
    _seg(ax, [(x, y + 0.5), (x, y - 0.5)], color=COMP, lw=2.4)   # channel
    _seg(ax, [(x - 0.35, y + 0.2), (x - 0.35, y - 0.2)], color=COMP, lw=2.0)
    _seg(ax, [(x - 0.35, y), (x, y)], color=COMP, lw=1.6)        # gate lead
    # body diode
    ax.plot([x + 0.18, x + 0.38, x + 0.38, x + 0.18], [y - 0.15, y, y, y],
            color=ACCENT, lw=1.1, zorder=5)
    _seg(ax, [(x + 0.18, y - 0.22), (x + 0.18, y + 0.12)], color=ACCENT, lw=1.1)
    _seg(ax, [(x, y + 0.5), (x, y + 0.75)], color=WIRE)
    _seg(ax, [(x, y - 0.5), (x, y - 0.75)], color=WIRE)


def draw_diode(ax, x, y, r=0.5):
    ax.add_patch(Polygon([(x - 0.24, y + 0.3), (x - 0.24, y - 0.3),
                          (x + 0.24, y)], closed=True, fc='white', ec=COMP,
                         lw=1.8, zorder=4))
    _seg(ax, [(x + 0.24, y + 0.3), (x + 0.24, y - 0.3)], color=COMP, lw=1.8)
    _seg(ax, [(x - 0.24, y), (x - 0.24, y + 0.55)], color=WIRE)
    _seg(ax, [(x + 0.24, y), (x + 0.24, y - 0.55)], color=WIRE)


def draw_inductor(ax, x, y, r=0.6, horizontal=True):
    n = 4
    for i in range(n):
        cx = x - 0.42 + i * 0.28
        ang = np.linspace(np.pi, 2 * np.pi, 30)
        ax.plot(cx + 0.14 * np.cos(ang), y + 0.14 * np.sin(ang),
                color=COMP, lw=1.8, zorder=4)
    _seg(ax, [(x - 0.56, y), (x - 0.42, y)], color=WIRE)
    _seg(ax, [(x + 0.42, y), (x + 0.56, y)], color=WIRE)


def draw_capacitor(ax, x, y, vertical=True, r=0.5):
    _seg(ax, [(x, y + 0.28), (x, y + 0.12)], color=WIRE)
    _seg(ax, [(x, y - 0.28), (x, y - 0.12)], color=WIRE)
    _seg(ax, [(x - 0.22, y + 0.12), (x + 0.22, y + 0.12)], color=COMP, lw=2.2)
    _seg(ax, [(x - 0.22, y - 0.12), (x + 0.22, y - 0.12)], color=COMP, lw=2.2)


def draw_resistor(ax, x, y, r=0.5, horizontal=True):
    ax.add_patch(Rectangle((x - 0.4, y - 0.14), 0.8, 0.28, fc='white',
                           ec=COMP, lw=1.6, zorder=4))
    _seg(ax, [(x - 0.4, y), (x - 0.55, y)], color=WIRE)
    _seg(ax, [(x + 0.4, y), (x + 0.55, y)], color=WIRE)


def draw_transformer(ax, x, y, r=0.85):
    # two winding columns + core lines
    for col_x, n in ((x - 0.32, 3), (x + 0.32, 3)):
        for i in range(n):
            cy = y - 0.28 + i * 0.28
            ang = np.linspace(0, np.pi, 24)
            ax.plot(col_x + 0.1 * np.cos(ang), cy + 0.12 * np.sin(ang),
                    color=COMP, lw=1.7, zorder=4)
    _seg(ax, [(x - 0.44, y + 0.34), (x + 0.44, y + 0.34)], color=COMP, lw=2.0)
    _seg(ax, [(x - 0.44, y - 0.34), (x + 0.44, y - 0.34)], color=COMP, lw=2.0)
    _seg(ax, [(x - 0.32, y + 0.34), (x - 0.32, y + 0.55)], color=WIRE)
    _seg(ax, [(x - 0.32, y - 0.34), (x - 0.32, y - 0.55)], color=WIRE)
    _seg(ax, [(x + 0.32, y + 0.34), (x + 0.32, y + 0.55)], color=WIRE)
    _seg(ax, [(x + 0.32, y - 0.34), (x + 0.32, y - 0.55)], color=WIRE)
    # polarity dots
    _dot(ax, x - 0.32, y + 0.34, color=ACCENT, r=0.05)
    _dot(ax, x + 0.32, y + 0.34, color=ACCENT, r=0.05)


def draw_controller(ax, x, y, label='Ctrl', r=0.9):
    ax.add_patch(Rectangle((x - r, y - 0.5), 2 * r, 1.0, fc='#eaf1fb',
                           ec=ACCENT, lw=1.8, zorder=4))
    ax.text(x, y, label + '\n(补偿器+PWM)', ha='center', va='center',
            fontsize=8.5, color=ACCENT, zorder=5, fontweight='bold')
    _seg(ax, [(x - r, y), (x - r - 0.3, y)], color=WIRE)
    _seg(ax, [(x + r, y), (x + r + 0.3, y)], color=WIRE)


def draw_ground(ax, x, y):
    for i, w in enumerate((0.24, 0.15, 0.07)):
        _seg(ax, [(x - w, y - i * 0.12), (x + w, y - i * 0.12)],
             color=WIRE, lw=1.4)


_DRAWERS = {'source': draw_source, 'mosfet': draw_mosfet, 'diode': draw_diode,
            'inductor': draw_inductor, 'capacitor': draw_capacitor,
            'resistor': draw_resistor, 'transformer': draw_transformer,
            'controller': draw_controller}


def draw_circuit(ax, topo, highlight=None):
    """Draw the closed-loop schematic for `topo` on `ax` (data coords)."""
    ax.set_facecolor('white')
    ax.set_xlim(0, 14)
    ax.set_ylim(0.6, 7.4)
    ax.set_aspect('equal')
    ax.axis('off')

    for x1, y1, x2, y2 in WIRES.get(topo, []):
        _seg(ax, [(x1, y1), (x2, y2)], color=WIRE)

    comps = COMPONENTS.get(topo, [])
    for c in comps:
        drawer = _DRAWERS[c['kind']]
        if c['kind'] == 'controller':
            drawer(ax, c['x'], c['y'], label=c['label'])
        elif c['kind'] == 'mosfet':
            drawer(ax, c['x'], c['y'])
        else:
            drawer(ax, c['x'], c['y'], r=c['r'])
        # label
        dy = 0.95 if c['kind'] in ('source', 'controller') else -0.95
        if c['kind'] == 'mosfet':
            dy = 1.05
        ax.text(c['x'], c['y'] + dy, c['label'], ha='center', va='center',
                fontsize=10, color=ACCENT, fontweight='bold',
                bbox=dict(boxstyle='round,pad=0.18', fc='white', ec='none',
                          alpha=0.0))
        if highlight and c['id'] == highlight:
            ax.add_patch(Circle((c['x'], c['y']), c['r'] + 0.22, fc='none',
                                ec=HILITE, lw=2.5, ls='--', zorder=6))

    for x, y in GROUNDS.get(topo, []):
        draw_ground(ax, x, y)


def hit_test(topo, x, y, tol=0.55):
    """Return the component id under data coords (x, y), or None."""
    best, best_d = None, tol
    for c in COMPONENTS.get(topo, []):
        d = np.hypot(x - c['x'], y - c['y'])
        r = c['r'] + 0.15
        if d < r and d < best_d:
            best, best_d = c['id'], d
    return best


def get_component(topo, comp_id):
    for c in COMPONENTS.get(topo, []):
        if c['id'] == comp_id:
            return c
    return None
