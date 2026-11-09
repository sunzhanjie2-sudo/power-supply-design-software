"""Readable magnetic-result projection shared by Tk and the Python web UI.

No design is solved here: rows and checks describe the supplied snapshot.
"""
from math import isfinite


def _number(value, scale=1.):
    if value is None or not isfinite(float(value)):
        return '未计算'
    return f'{float(value)*scale:.5g}'


def build_report(p, result):
    md = result.get('mag') or {}
    devices = []
    transformer = md.get('transformer')
    if transformer:
        devices.append(('T1 · 变压器', transformer, True))
    inductors = md.get('inductors')
    if inductors:
        devices.extend((f'OUT{i} · 输出电感', d, False) for i, d in enumerate(inductors, 1))
    elif md.get('inductor'):
        devices.append(('L1 · 电感', md['inductor'], False))
    sections, conclusions = [], []

    def section(title, rows, note=''):
        sections.append(dict(title=title, rows=rows, note=note))

    def row(label, value, unit='', scale=1.):
        return dict(label=label, value=_number(value, scale), unit=unit)

    def text(label, value):
        return dict(label=label, value=str(value), unit='')

    def conclusion(device, title, state, detail):
        conclusions.append(dict(device=device, title=title, state=state, detail=detail))

    for title, d, is_transformer in devices:
        if not d.get('ok'):
            conclusion(title, '未完成设计', 'warning', d.get('reason', '缺少磁件结果'))
            continue
        if d.get('design_enabled') is False:
            section(title + ' / 外购成品', [
                row('电感量 L', d.get('L'), 'µH', 1e6), row('厂家 DCR', d.get('R_dc'), 'mΩ', 1e3),
                row('实际 RMS 电流', d.get('I_rms'), 'A'), row('实际峰值电流', d.get('I_pk'), 'A'),
                row('直流铜损', d.get('P_cu'), 'W'), row('用户附加损耗', d.get('P_extra'), 'W'),
            ], d.get('note', ''))
            for label, key, actual in [('额定 RMS 电流', 'inductor_rated_current', 'I_rms'),
                                        ('饱和电流 Isat', 'inductor_saturation_current', 'I_pk')]:
                rating = d.get(key) or 0.
                state = 'warning' if rating <= 0 else 'success' if d[actual] <= rating else 'danger'
                detail = '厂家额定值未提供' if rating <= 0 else f"实际 {_number(d[actual])} A / 额定 {_number(rating)} A"
                conclusion(title, label, state, detail)
            conclusion(title, '磁芯与温升未评估', 'warning', '未进行磁密、绕制和温升计算；应核对厂家规格。')
            continue

        section(title + ' / 磁芯与材料', [
            text('磁芯型号', d.get('core_label') or d.get('core', '未提供')),
            text('磁芯材料', p.get('core_material', '未提供')),
            row('有效截面积 Ae', d.get('Ae'), 'mm²', 1e6),
            row('有效体积 Ve', d.get('Ve'), 'mm³', 1e9),
            row('窗口面积 Wa', d.get('Wa'), 'mm²', 1e6),
            row('所需面积乘积 Ap', d.get('ap'), 'mm⁴', 1e12),
            row('Steinmetz 系数 k', p.get('k_core')),
            row('频率指数 α', p.get('a_core')), row('磁密指数 β', p.get('b_core')),
        ], '磁损系数单位：Pv[mW/cm³] = k·(f/kHz)^α·B[T]^β。沿用实际磁通的 NSE 积分。')

        if is_transformer:
            windings = [('P · 原边', d['Np'], d['d_wire_p'], d['n_strand_p'],
                         d['I_rms_p'], d['J_actual_p'], d['R_dc_p'], d['Fr_p'],d.get('parallel_wires_p',1))]
            if d.get('windings'):
                windings.extend((f"OUT{w['id']} · {w['name']}", w['Ns'], w['d_wire_s'],
                                 w['n_strand_s'], w['I_rms'], w['J_actual'], w['R_dc'], w['Fr'],w.get('parallel_wires_s',1))
                                for w in d['windings'])
            else:
                windings.append(('S · 副边', d['Ns'], d['d_wire_s'], d['n_strand_s'],
                                 d['I_rms_s'], d['J_actual_s'], d['R_dc_s'], d['Fr_s'],d.get('parallel_wires_s',1)))
            if d.get('auxiliary'):
                w = d['auxiliary']
                section(title + ' / AUX 辅助绕组', [
                    row('匝数', w['Na'], '匝'), row('单股线径', w['d_wire'], 'mm', 1e3),
                    row('实际 RMS 电流', w['I_rms'], 'A'), row('几何 DCR', w['R_dc'], 'mΩ', 1e3),
                    row('绕组铜损', w['P_cu'], 'W'),
                ])
        else:
            windings = [('电感绕组', d['N'], d['d_wire'], 1, d['I_rms'], d['J_actual'], d['R_dc'], d['Fr'],1)]
        for name, turns, diameter, strands, rms, density, resistance, ac, copies in windings:
            section(title + ' / ' + name, [
                row('匝数', turns, '匝'), row('单股线径', diameter, 'mm', 1e3), row('单根线股数', strands, '股'),
                *([row('线圈并绕数',copies,'根'),row('截面线数（匝数 × 根数）',turns*copies,'根')] if is_transformer else []),
                row('实际 RMS 电流', rms, 'A'), row('电流密度 J', density, 'A/mm²', 1e-6),
                row('几何 DCR', resistance, 'mΩ', 1e3), row('Rac / Rdc', ac),
            ])

        section(title + ' / 损耗与温升', [
            row('峰值磁密 Bpk', d.get('B_pk'), 'mT', 1e3), row('磁通摆幅 ΔB', d.get('dB'), 'mT', 1e3),
            row('裸铜窗口占比', d.get('fill'), '%', 100),
            row('每匝平均长度 MLT', d.get('MLT'), 'mm', 1e3),
            row('磁芯损耗', d.get('P_core'), 'W'), row('绕组铜损', d.get('P_cu'), 'W'),
            row('磁件总损耗', d.get('P_total'), 'W'),
            row('至环境热阻 Ri-a', d.get('Rth_transformer'), 'K/W') if is_transformer else
                row('对流换热系数 h', d.get('h_conv', p['h_conv']), 'W/(m²·K)'),
            row('估算温升 ΔT', d.get('dT'), 'K'), row('温升评审上限', p['temp_rise_limit'], 'K'),
        ], f"MLT 来源：{d.get('MLT_source', '未提供')}。"
           + ('温升 = 总损耗 × 用户 Ri-a。' if is_transformer else '温升使用表面积与对流估算。')
           + '裸铜占比未含绝缘和骨架公差，可绕制性另见绕制评估页。')
        b, bsat, dt, limit = d['B_pk'], p['Bsat'], d['dT'], p['temp_rise_limit']
        conclusion(title, '磁饱和检查', 'success' if b < bsat else 'danger',
                   f"Bpk {_number(b, 1e3)} mT / Bsat {_number(bsat, 1e3)} mT")
        conclusion(title, '温升检查', 'success' if dt <= limit else 'danger',
                   f"ΔT {_number(dt)} K / 上限 {_number(limit)} K")
        if d.get('fill', 0.) > 1.:
            conclusion(title, '铜窗口超限', 'danger', f"裸铜占比 {_number(d['fill'], 100)}%，大于可用窗口。")
        gap = d.get('gap_design')
        if is_transformer and gap:
            section(title + ' / 磁导率与气隙', [
                row('磁材相对磁导率 μr', gap.get('mu_r')),
                row('有效磁路长度 le = Ve/Ae', gap.get('le_m'), 'mm', 1e3),
                row('目标励磁电感 Lm', gap.get('target_inductance_H'), 'µH', 1e6),
                row('目标 AL', gap.get('AL_target_H'), 'nH/匝²', 1e9),
                row('无气隙电感 L0', gap.get('L_ungapped_H'), 'µH', 1e6),
                row('含气隙有效磁导率 μe', gap.get('mu_effective')),
                row('估算等效总气隙 lg', gap.get('gap_m'), 'mm', 1e3),
            ], gap['mu_r_source'] + '。' + (gap.get('mu_r_conditions') or '') + '。' + gap['note'])
            conclusion(title, '气隙可实现性', 'danger' if gap['status'] == 'infeasible' else 'warning',
                       f"lg ≈ {_number(gap['gap_m'], 1e3)} mm；线性估算可实现，加工按 AL 实测调整。"
                       if gap['status'] == 'estimated' else gap['note'])
        elif not is_transformer:
            section(title + ' / 气隙', [row('忽略磁芯磁阻的气隙初值', d.get('gap'), 'mm', 1e3)],
                    '电感沿用既有高磁导率近似；实体气隙和边缘磁通需按实物复核。')

    if not devices:
        conclusion('磁件设计', '未计算', 'warning', md.get('reason') or '检查磁芯、Bmax、电流密度与窗口约束。')
    errors = sum(c['state'] == 'danger' for c in conclusions)
    pending = sum(c['state'] == 'warning' for c in conclusions)
    summary = f"{errors} 项超限 · {pending} 项待复核；温升上限 {p['temp_rise_limit']:g} K。"
    return dict(title='磁件设计报告', summary=summary, sections=sections, conclusions=conclusions)


def as_text(view):
    lines = [view['title'], view['summary'], '', '设计结论']
    states = dict(success='通过', danger='超限', warning='待复核')
    for c in view['conclusions']:
        lines.append(f"[{states[c['state']]}] {c['device']} · {c['title']}：{c['detail']}")
    for s in view['sections']:
        lines.extend(['', s['title']])
        lines.extend(f"{r['label']}：{r['value']} {r['unit']}".rstrip() for r in s['rows'])
        if s['note']:
            lines.append(s['note'])
    return '\n'.join(lines)
