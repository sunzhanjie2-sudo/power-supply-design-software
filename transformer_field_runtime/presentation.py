"""Shared display conventions for the desktop and the two offline reports."""
from dataclasses import dataclass

# Stable by winding ID in the export order, including when ports are reordered.
COLORS = ('#d44362', '#da8614', '#187fbd', '#9354ba',
          '#168667', '#5e66bf', '#97703c', '#b14488')
CLASSIFICATIONS = {'reference_assumptions': '标称参考（含假设）',
                   'user_defined_linear_model': '用户给定线性模型'}
CORE_MODES = {'assembled': '已装配磁芯', 'half_center_gap': '单半芯配对 · 中柱磨隙',
              'half_spacer': '单半芯配对 · 整体垫片'}


@dataclass(frozen=True)
class PortReading:
    name: str
    self_uH: float
    mutual_uH: float
    k: float
    primary: bool


def port_readings(report):
    ports = report['port_order']
    ref = ports.index(report['primary_port'])
    inductance, coupling = report['L_ports_H'], report['k_ports']
    return [PortReading(name, inductance[i][i] * 1e6, inductance[ref][i] * 1e6,
                        coupling[ref][i], i == ref) for i, name in enumerate(ports)]


def key_readings(report):
    rows = port_readings(report)
    primary = next(row for row in rows if row.primary)
    weakest = min((row for row in rows if not row.primary), key=lambda row: abs(row.k), default=None)
    short = report['ideal_all_secondary_short_Lp_H']
    cards = [('原边自感', f'{primary.self_uH:.4f}', 'µH', f'{primary.name} · 其余端口开路')]
    if weakest is not None:
        cards.append(('与原边耦合最弱', f'{weakest.k:+.5f}', '',
                      f'{primary.name} ↔ {weakest.name} · 按 |k| 比较'))
    if short is not None:
        cards.append(('理想短路原边电感', f'{short * 1e9:.2f}', 'nH', '全部副边零磁链、零电阻'))
    return cards


def winding_colors(geometry):
    return {w['id']: COLORS[i % len(COLORS)] for i, w in enumerate(geometry['windings'])}

