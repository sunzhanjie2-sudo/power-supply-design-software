"""Physical self/mutual inductance data for the experimental flyback solver.

All winding references use the transformer's marked dot convention.  The
secondary rectifier connection supplies the opposite terminal sign in the
circuit solver; users therefore enter positive pairwise coupling coefficients.
This is not the historical RCD ``K`` (which estimated leakage as (1-K)*Lm).
"""
import copy
import math

import numpy as np


DEFAULT_COUPLING = .995
DEFAULT_DCR = .02


def default_coupling_config(count):
    """Return independent, JSON-safe defaults for primary + ``count`` outputs."""
    if not isinstance(count, int) or not 1 <= count <= 6:
        raise ValueError('耦合矩阵需要 1–6 路输出')
    size = count + 1
    return dict(enabled=False,
                k=[[1. if i == j else DEFAULT_COUPLING for j in range(size)] for i in range(size)],
                dcr=[DEFAULT_DCR] * size)


def _positive(value, label, *, allow_zero=False):
    if isinstance(value, bool):
        raise ValueError(f'{label} 必须为有限数值')
    try:
        number = float(value)
    except (ValueError, TypeError):
        raise ValueError(f'{label} 必须为有限数值') from None
    if not math.isfinite(number) or number < 0 or (not allow_zero and number == 0):
        raise ValueError(f'{label} 必须为有限' + ('非负值' if allow_zero else '正值'))
    return number


def validate_coupling_config(config, count):
    """Validate K and optional field-derived self inductances.

    Winding resistance is derived from the resolved conductor geometry.  A
    legacy DCR value must neither override that geometry nor reject an
    otherwise usable saved design.
    """
    defaults = default_coupling_config(count)
    labels = ['P'] + [f'OUT{i + 1}' for i in range(count)]
    size = len(labels)
    if not isinstance(config, dict):
        raise ValueError('coupling_config 必须为配置字典')
    if not isinstance(config.get('enabled', False), bool):
        raise ValueError('耦合矩阵 enabled 必须为布尔值')
    if not isinstance(config.get('field_matrix_enabled', False), bool):
        raise ValueError('场解矩阵 field_matrix_enabled 必须为布尔值')
    order = config.get('port_order', labels)
    if not isinstance(order, (list, tuple)) or len(order) != size or set(order) != set(labels):
        raise ValueError('场解矩阵端口必须恰好对应 P 和当前各路 OUT，不能缺失或重复')
    indices = [order.index(label) for label in labels]
    raw_k = config.get('k', [])
    if not isinstance(raw_k, (list, tuple)):
        raise ValueError('耦合矩阵 k 必须为列表')
    raw_k = raw_k or defaults['k']
    if len(raw_k) != size or any(not isinstance(row, (list, tuple)) or len(row) != size for row in raw_k):
        raise ValueError(f'耦合矩阵必须为 {size}×{size}（P + {size - 1} 路输出）')
    k = np.empty((size, size), dtype=float)
    for i, row in enumerate(raw_k):
        for j, value in enumerate(row):
            k[i, j] = _positive(value, f'k({labels[i]},{labels[j]})', allow_zero=True)
            if k[i, j] > 1:
                raise ValueError(f'k({labels[i]},{labels[j]}) 必须满足 0 ≤ k ≤ 1')
    k = k[np.ix_(indices, indices)]
    self_l = config.get('self_inductances_H')
    if self_l is not None:
        if not isinstance(self_l, (list, tuple)) or len(self_l) != size:
            raise ValueError('场解自感列表必须与端口一一对应，单位为 H')
        self_l = np.array([_positive(self_l[i], f'{labels[j]} 场解自感')
                           for j, i in enumerate(indices)], dtype=float)
    if not np.allclose(np.diag(k), 1., rtol=0., atol=1e-12):
        raise ValueError('耦合矩阵对角线必须为 1')
    if not np.allclose(k, k.T, rtol=0., atol=1e-12):
        raise ValueError('耦合矩阵必须对称，kij = kji')
    eigenvalues = np.linalg.eigvalsh(k)
    if eigenvalues[0] < -1e-10:
        raise ValueError('耦合矩阵不满足物理可实现性：矩阵不是半正定；请检查各绕组两两 kij')
    ideal = bool(np.allclose(k, np.ones_like(k), rtol=0., atol=1e-13))
    if not ideal and eigenvalues[0] <= 1e-11:
        raise ValueError('耦合矩阵为奇异/近奇异：本版仅支持正定矩阵或全部 kij=1 的理想变压器')
    return dict(labels=labels, K=k, ideal=ideal, eigenvalues=eigenvalues,
                self_inductances_H=self_l,
                inductance_source='field-matrix' if self_l is not None else 'turns-ratio')


def resolve_winding_geometry(p, nominal_op, rails=None):
    """Resolve one physical transformer before the coupled-current solve.

    Automatic conductor sizing uses the nominal predesign RMS once.  The
    selected core, integer turns and conductors are then frozen while the
    physical circuit solves its actual RMS currents; final current density
    and copper loss use those currents without silently changing the DCR.
    This avoids an expensive and ambiguous current/auto-wire fixed point.
    """
    import magnetics as mag
    from isolated_outputs import output_specs, selected_params, RAIL_KEYS
    if rails is None:
        rails = output_specs(p)
    if not rails:
        rails = [dict({key: p.get(key) for key in RAIL_KEYS}, id=1, name='OUT1')]
    turns = nominal_op.get('output_turns')
    if not turns:
        from transformer_turns import resolve_output_turns
        turns = resolve_output_turns(p, rails)
    selected = int(p.get('feedback_output', 1)) - 1
    q = selected_params(p, rails)
    q.update(outputs=[], Np=turns['Np'], Ns=turns['Ns'][selected])
    primary_current = float(nominal_op.get('I_p_rms', nominal_op['I_sw_rms']))
    secondary_current = float(nominal_op.get('I_s_rms', nominal_op['I_d_rms']))
    transformer = mag.design_transformer(nominal_op, q, primary_current,
                                         secondary_current, n_ratio=q['N'])
    if not transformer.get('ok'):
        raise ValueError('绕组几何预设计失败：' + transformer.get('reason', '无可用磁芯'))
    hardware = {key: transformer[key] for key in
                ('core', 'core_geometry', 'MLT', 'MLT_source', 'Np', 'Ns', 'd_wire_p', 'd_wire_s',
                 'n_strand_p', 'n_strand_s', 'parallel_wires_p', 'parallel_wires_s', 'R_dc_p', 'R_dc_s')}
    hardware.update(rho=float(p['rho']), windings=[],
                    auto_wire_sizing='nominal-predesign-frozen',
                    primary_wire_source='manual' if p.get('d_wire_p', 0) > 0 else 'nominal-predesign')
    children = nominal_op.get('output_ops') or [nominal_op]
    if len(children) != len(rails):
        raise ValueError('绕组几何预设计与输出路数不一致')
    fixed = p.get('_fixed_transformer') or {}
    fixed_windings = {int(w['id']): w for w in fixed.get('windings', [])}
    for index, (rail, child, count) in enumerate(zip(rails, children, turns['Ns']), 1):
        frozen = fixed_windings.get(index, {})
        if not frozen and fixed and index == selected + 1:
            # Single-output corners have no per-rail configuration to pin.
            # Their selected secondary still belongs to the frozen hardware.
            frozen = fixed
        count = int(frozen.get('Ns', count))
        strands = int(frozen.get('n_strand_s', rail['n_strand_s']))
        from parallel_wires import count as wire_count
        copies=wire_count(frozen if frozen else rail,'s')
        current = float(child.get('I_s_rms', child['I_d_rms']))
        diameter = float(frozen.get('d_wire_s', rail['d_wire_s'])) or max(50e-6, mag.wire_diameter(current / (strands*copies), p['J']))
        area = strands * copies * math.pi * diameter ** 2 / 4.
        resistance = float(p['rho']) * hardware['MLT'] * count / area
        hardware['windings'].append(dict(id=int(rail.get('id', index)), Ns=int(count),
            d_wire_s=float(diameter), n_strand_s=strands, parallel_wires_s=copies, R_dc=resistance,
            wire_source='fixed-hardware' if frozen else 'manual' if rail.get('d_wire_s', 0) > 0 else 'nominal-predesign'))
    feedback = hardware['windings'][selected]
    hardware.update(Ns=feedback['Ns'], d_wire_s=feedback['d_wire_s'],
                    n_strand_s=feedback['n_strand_s'],parallel_wires_s=feedback['parallel_wires_s'],R_dc_s=feedback['R_dc'])
    return hardware


def resolve_winding_model(p, rails=None, *, geometry=None, nominal_op=None):
    """Validate and resolve a winding matrix without changing the input.

    Returns labels, primary-to-winding ratios, full inductance matrix ``L`` in
    henries, normalized ``K``, winding ``R`` in ohms, and the primary
    short-circuit leakage ``L_leak`` (secondary terminals all shorted).  The
    latter is a Schur complement, not the sum of independent leakage values.

    A completely ideal all-ones matrix is an explicit algebraic-transformer
    limit.  Other singular positive-semidefinite matrices are rejected because
    the experimental circuit solver cannot integrate their constrained modes.
    """
    if rails is None:
        from isolated_outputs import output_specs
        rails = output_specs(p)
    if not rails:
        from isolated_outputs import RAIL_KEYS
        rails = [dict({key: p.get(key) for key in RAIL_KEYS}, name='OUT1', id=1)]
    validated = validate_coupling_config(p.get('coupling_config', {}), len(rails))
    labels, k = validated['labels'], validated['K']
    lp = _positive(p.get('Lm_forward') if p.get('topology')=='ACF-FORWARD' else p.get('L'), '原边自感 Lp')
    if geometry is None:
        if nominal_op is None:
            from power_stage import compute_operating_point
            nominal_op = compute_operating_point(dict(p, coupling_config=dict(enabled=False)))
        geometry = resolve_winding_geometry(p, nominal_op, rails)
    np_turns = _positive(geometry['Np'], '已解析 Np')
    ratios, ratio_sources = [1.], ['primary']
    for i, winding in enumerate(geometry['windings']):
        ns = _positive(winding['Ns'], f'OUT{i + 1} 已解析 Ns')
        ratios.append(np_turns / ns)
        ratio_sources.append('actual-turns')
    ratios = np.array(ratios)
    self_l = validated['self_inductances_H']
    if self_l is None:
        self_l = lp / ratios ** 2
    elif not math.isclose(float(self_l[0]), lp, rel_tol=1e-8, abs_tol=1e-15):
        raise ValueError('原边电感与已采用的场解矩阵不一致，请重新仿真或取消场解矩阵')
    inductance = k * np.sqrt(np.outer(self_l, self_l))
    leakage = 0. if validated['ideal'] else lp * (1. - float(k[0, 1:] @ np.linalg.solve(k[1:, 1:], k[1:, 0])))
    resistance = np.array([geometry['R_dc_p']] + [w['R_dc'] for w in geometry['windings']], dtype=float)
    if resistance.shape != (len(labels),) or not np.all(np.isfinite(resistance)) or np.any(resistance < 0):
        raise ValueError('绕组几何计算得到无效 DCR；请检查 MLT、线径、股数和电阻率')
    return dict(validated, ratios=ratios, ratio_sources=ratio_sources,
                L=inductance, L_leak=max(0., leakage), R=resistance,
                dcr_source='geometry', transformer_hardware=copy.deepcopy(geometry))
