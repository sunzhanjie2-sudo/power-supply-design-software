"""Resolve one physical transformer before deriving unregulated outputs.

Only the feedback output is a voltage setpoint.  The remaining voltages are
ideal turns-ratio estimates, not extra regulation constraints.  Old JSON with
Ns=0 can use its former voltage targets once to seed integer secondary turns;
callers persist those returned turns when accepting a configuration.
"""
import math


def _seed_operating_point(p, rails, secondary_turns=None):
    from power_stage import compute_operating_point
    main = int(p.get('feedback_output', 1)) - 1
    selected = rails[main]
    q = dict(p, outputs=[], feedback_output=1,
             coupling_config=dict(enabled=False),
             **{key: value for key, value in selected.items()
                if key not in ('name', 'id', 'L', 'core_choice_L', 'custom_core_L')})
    q['P_out'] = sum(row['P_out'] for row in rails)
    if secondary_turns is not None:
        q['N'] = p['N'] * secondary_turns[0] / secondary_turns[main]
    else:
        q['N'] = p['N'] * rails[0]['V_out'] / selected['V_out']
    fixed = p.get('_fixed_transformer') or {}
    np_turns = fixed.get('Np') or p.get('Np', 0)
    selected_ns = (secondary_turns[main] if secondary_turns is not None
                   else selected.get('Ns', 0))
    if np_turns and selected_ns:
        q['N'] = np_turns / selected_ns
    if p['topology'] == 'ACF-FORWARD':
        q['L'] = 1 / sum((row['V_out'] / selected['V_out']) ** 2 / row['L']
                        for row in rails)
    return compute_operating_point(q), q


def _primary_geometry(p, op):
    """Use the magnetic engine's core/volt-second rule without loss FFT work."""
    import magnetics as mag
    fixed = p.get('_fixed_transformer') or {}
    ap = max(2 * op['P_out'] / (p['Bmax'] * p['J'] * p['Ku'] * op['f_sw']), 1e-30)
    name, core = mag.resolve_core(p, ap, fixed)
    if core is None:
        raise ValueError('没有足够大的变压器磁芯，无法推导非反馈输出的实际匝比')
    turns = int(fixed.get('Np') or p.get('Np', 0) or
                math.ceil(op['V_in'] * op['D'] * op['Ts'] / (p['Bmax'] * core['Ae'])))
    return dict(core=name, Np=max(1, turns), Ae=core['Ae'],
                MLT=mag.resolve_mlt(p, name, core, fixed))


def resolve_output_turns(p, rails):
    """Return Np, Ns, actual Np/Ns ratios and nominal output voltages.

    ``rails`` are decoded and validated output dictionaries.  Explicit turns
    never depend on an unregulated output's stale ``V_out``.  For old automatic
    turns only, its old voltage supplies the initial winding-ratio seed.  A
    second primary predesign then uses those frozen integer secondary turns,
    so subsequent canonicalization does not change the resolved hardware.
    """
    if not rails:
        return None
    main = int(p.get('feedback_output', 1)) - 1
    target = float(rails[main]['V_out'])
    secondary = [int(row.get('Ns', 0)) for row in rails]
    fixed = p.get('_fixed_transformer') or {}
    for winding in fixed.get('windings', []):
        index = int(winding['id']) - 1
        if 0 <= index < len(secondary) and winding.get('Ns'):
            secondary[index] = int(winding['Ns'])
    if fixed.get('Ns'):
        secondary[main] = int(fixed['Ns'])
    if not all(secondary):
        if any(not isinstance(row.get('V_out'), (int, float)) or
               not math.isfinite(row['V_out']) or row['V_out'] <= 0 for row in rails):
            raise ValueError('旧配置 Ns=0 迁移需要原各路正电压作为初始匝数参考；请填写实际副边匝数')
        initial_op, _ = _seed_operating_point(p, rails)
        geometry = _primary_geometry(p, initial_op)
        # N remains the predesign Np/Ns(OUT1) anchor for legacy Ns=0 files.
        # Respect explicit OUT1 turns when available, rather than replacing
        # them with the independent predesign ratio.
        anchor = secondary[0] or max(1, round(geometry['Np'] / p['N']))
        v_first = float(rails[0]['V_out'])
        secondary = [ns or max(1, round(anchor * float(row['V_out']) / v_first))
                     for ns, row in zip(secondary, rails)]
    from voltage_nodes import ratio_voltage
    voltages = [target if i==main else ratio_voltage(rails[main],row,ns/secondary[main])
                for i,(row,ns) in enumerate(zip(rails,secondary))]
    if any(v<=0 for v in voltages):
        raise ValueError('副边匝比电压不足以覆盖整流及输出防反压降；请增加该路匝数或降低压降')
    canonical = [dict(row, V_out=vo, Ns=ns)
                 for row, vo, ns in zip(rails, voltages, secondary)]
    final_op, _ = _seed_operating_point(p, canonical, secondary)
    geometry = _primary_geometry(p, final_op)
    return dict(Np=geometry['Np'], Ns=secondary, voltages=voltages,
                ratios=[geometry['Np'] / ns for ns in secondary],
                transformer=geometry, feedback_output=main + 1,
                voltage_model='turns-ratio-with-rectifier-and-blocking-drops; unregulated estimate')
