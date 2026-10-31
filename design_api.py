"""Headless design API — the machine-readable entry point for AI tool chains.

Everything here is import-safe (no GUI).  Typical use:

    import design_api
    report = design_api.run_design({
        'topology': 'BUCK', 'V_in': 12, 'V_out': 5, 'P_out': 5,
        'f_sw': 100e3, 'L': 47e-6, 'C_out': 100e-6,
    })
    for chk in report['checks']:
        if not chk['pass']:
            print('FAIL', chk['id'], chk['name'], chk['value'], chk['limit'])

or from the shell:  python cli.py design --spec spec.json --out report.json
"""

import copy
import math

from power_stage import (DEFAULT_PARAMS, TOPOLOGIES, compute_operating_point,
                         compute_qrflyback_op)
from loss_model import compute_design
from loop_tuning import kfactor_tune
import plants

# ----------------------------------------------------------------- spec load

from design_engine.specification import load_spec


# ----------------------------------------------------------------- helpers

def _chk(cid, name, value, limit, ok, comparison, unit=''):
    return dict(id=cid, name=name, value=value, limit=limit,
                margin=(value - limit) if comparison in ('<=', '>=') else None,
                comparison=comparison, unit=unit, pass_=bool(ok))


def _safe(fn, default):
    try:
        return fn()
    except Exception:
        return default


# ----------------------------------------------------------------- checks

from design_engine.reporting import _design_checks, report_for_result as _report_for_result


# ----------------------------------------------------------------- report

def run_design(spec):
    """Full design report for one spec.  Returns dict with operating_point,
    losses, magnetics, checks, warnings and the normalised spec."""
    p = load_spec(spec)
    try:
        from design_engine.service import calculate_parameters
        run = calculate_parameters(p)
    except Exception as e:
        from calculation_scheduler import CalculationCancelled
        if isinstance(e, CalculationCancelled):
            raise
        return dict(ok=False, error=f'{type(e).__name__}: {e}', spec=p)
    return run.legacy_report()


# ----------------------------------------------------------------- Vin endpoints

def run_input_endpoints(spec, *, progress=None, cancelled=None):
    """JSON-ready full min/max reports, sharing one Vinmin-sized physical BOM."""
    from design_engine.service import calculate_parameters
    return calculate_parameters(load_spec(spec), analysis='endpoints',
        progress=progress, cancelled=cancelled).legacy_endpoints()


# ----------------------------------------------------------------- corners

def run_cross_regulation(spec, *, progress=None, cancelled=None):
    """JSON-safe min/max load combinations, with fixed BOM and failed corners."""
    from cross_regulation import scan_cross_regulation
    return scan_cross_regulation(load_spec(spec), progress=progress, cancelled=cancelled)


def run_corners(spec, v_in_min=None, v_in_max=None,
                load_fracs=(0.1, 0.25, 0.5, 0.75, 1.0),
                include_nominal=False, progress=None, cancelled=None):
    """Vin-min/max × load grid.  Returns per-corner results + worst cases.

    v_in_min/max default to ±10 % around the spec's V_in.  Corners that are
    physically invalid (e.g. Boost with V_out ≤ V_in) are reported as
    skipped, not errors.
    """
    from analysis_workflows import corners
    return corners(load_spec(spec), v_in_min, v_in_max, load_fracs,
                   include_nominal, progress, cancelled)


# ----------------------------------------------------------------- transient

def load_transient(spec, di, fc=None):
    """First-order load-step ΔV estimate (both terms, worst-case total).

    di : load step magnitude in amps (positive = load increase → dip).
    fc : loop crossover in Hz; defaults to f_sw/10 (standard design choice).
    """
    p = load_spec(spec)
    from isolated_outputs import selected_params
    if p.get('feedback_mode')=='PSR-MP6005':
        raise ValueError('MP6005 PSR 暂不提供简化负载阶跃估算；请做采样控制时域仿真')
    if p.get('coupling_config',{}).get('enabled'):
        raise ValueError('逐对耦合模型暂不提供单路一阶负载阶跃估算；请做独立负载时域验证')
    op = compute_operating_point(p)
    p = selected_params(p)
    from capacitor_banks import bank,total
    C_tot=total(p)
    rs=[c['ESR'] for c in bank(p)]
    r_par=0. if 0 in rs else 1/sum(1/r for r in rs)
    if not fc:
        fc = op.get('fc_recommended_max', p['f_sw'] / 10.0)

    dv_esr = di * r_par                       # instantaneous ESR step
    dv_cap = di / (2.0 * math.pi * fc * C_tot)  # capacitive droop until loop acts
    return dict(
        di=float(di), fc=float(fc), C_total=float(C_tot),
        R_esr_par=float(r_par),
        dv_esr=float(dv_esr), dv_cap=float(dv_cap),
        dv_total=float(dv_esr + dv_cap),
        target=float(p.get('ripple_target', 0.01) * p['V_out']),
        advice=((f"有源钳位正激: 建议 fc≤{op['fc_recommended_max']:.0f} Hz；"
                 if p['topology'] == 'ACF-FORWARD' else '')
                + "(1) 增大 C_out 或并联低 ESR 电容降低两项; "
                "(2) 提高 fc (≤f_sw/10~f_sw/6, 注意 RHP 零点/右半平面限制) 缩短容性跌落; "
                "(3) ΔV_ESR = ΔI·ESR 与环路无关, 只能靠低 ESR 电容解决."),
    )


# ----------------------------------------------------------------- autotune

def loop_margins_for(p, op=None):
    from plants import build_loop_models
    from loop_tuning import analyze_loop
    if op is None:
        from input_voltage_range import has_input_voltage_range, calculate_input_operating_point
        if has_input_voltage_range(p):
            snapshot = calculate_input_operating_point(p)
            p, op = snapshot['p'], snapshot['op']
        else:
            op = compute_design(p)['op']
    models, _ = build_loop_models(p, op)
    loop = analyze_loop(p, models, op)
    result = {k: loop[k] for k in ('fc', 'pm', 'min_pm', 'gm_db', 'gm_infinite', 'all_crosses')}
    result['descending_crossovers'] = [dict(fc=f, pm=m) for f, m in loop['crosses']]
    if loop.get('model'):
        result.update(model=loop['model'],closed_loop_stable=loop['closed_loop_stable'],
                      gm_band_limited=loop['gm_band_limited'], gm_scan_limited=loop['gm_scan_limited'])
    return result


def autotune_loop(spec, fc, pm):
    """K-factor tune against the plant, verify by re-computing margins."""
    p = load_spec(spec)
    psr=p.get('feedback_mode')=='PSR-MP6005'
    multi_flyback = p['topology']=='FLYBACK' and bool(p.get('outputs') or p.get('coupling_config',{}).get('enabled'))
    if p['topology'] not in ('BUCK','ACF-FORWARD') and not psr and not multi_flyback:
        raise ValueError('autotune_loop: 目前支持 BUCK / ACF-FORWARD (VM/PCM); '
                         '其它拓扑请用 GUI ④页')
    from input_voltage_range import has_input_voltage_range, calculate_input_operating_point
    if has_input_voltage_range(p):
        snapshot = calculate_input_operating_point(p)
        p, op = snapshot['p'], snapshot['op']
    else:
        op = compute_design(p)['op']
    p['control_mode'] = p.get('control_mode', 'Voltage Mode')
    if p['topology'] == 'ACF-FORWARD':
        fc = min(fc, op['fc_recommended_max'])
    (Gvc, _, _), _ = plants.build_loop_models(p, op)
    metadata = getattr(Gvc, '_loop_metadata', {})
    if metadata.get('experimental'):
        if metadata['inner_spectral_radius'] >= 1:
            raise ValueError('周期内环非稳定，不能自动写回外环补偿')
    kind = 'type2' if psr else plants.resolve_controller_type(p['controller_type'],p['control_mode'])
    if psr: fc=min(fc,op['f_sw']/10)
    r = kfactor_tune(Gvc, fc, pm, kind)
    p2 = dict(p)
    p2['fc_target'] = fc
    p2['controller_type'] = r['comp_type']
    for key in ('KP','fz1','fz2','fp1','fp2'):
        if r.get(key) is not None:
            p2[key] = r[key]
    psr_updates={}
    if psr and r['feasible']:
        from mp6005 import compensation_parts
        psr_updates=compensation_parts(r); p2.update(psr_updates)
    m = loop_margins_for(p2,op if metadata.get('experimental') else None)
    if metadata.get('experimental') and (not m['closed_loop_stable'] or m['fc'] is None or
                                       m['min_pm'] is None or m['min_pm'] < pm-1):
        r['feasible'] = False
    return dict(comp_type=r['comp_type'], KP=r['KP'], fz1=r['fz1'],
                fz2=r.get('fz2'), fp1=r['fp1'], fp2=r.get('fp2'),
                K=r['K'], boost=r['boost'], boost_required=r['boost_required'],
                feasible=r['feasible'],
                achieved=dict(fc=m.get('fc'), pm=m.get('pm'),
                              descending_crossovers=m['descending_crossovers'],
                              min_pm=m['min_pm']),
                fc_target=fc,
                fc_recommended_max=metadata.get('recommended_fc_max',op.get('fc_recommended_max')),
                Kp=r.get('Kp'), Ki=r.get('Ki'),
                spec_updates=(psr_updates if psr else {k: p2[k] for k in ('controller_type','KP','fz1','fz2','fp1','fp2')
                              if k == 'controller_type' or r.get(k) is not None}
                             ) if r['feasible'] else {})


# ----------------------------------------------------------------- listing

def list_parameters(topology=None):
    """Parameter name / default / category list (helps AI construct specs)."""
    from design_engine.catalog import parameter_catalog
    keys = set(DEFAULT_PARAMS) if topology is None or topology in TOPOLOGIES else set()
    keys.update(('V_in_min', 'V_in_max', 'input_voltage_case'))
    return [dict(name=row['name'], default=row['default'])
            for row in parameter_catalog() if row['name'] in keys]
