"""Cheap, explicit LTspice work plans. Never change the circuit or solver mesh."""
from __future__ import annotations

import math


def recommend_settings(parameters, settings, scope=None):
    """Raise observation windows conservatively; do not pretend this proves settling.

    The lowest compensator zero is only a scheduling proxy, not a closed-loop
    pole. Actual transient/periodicity checks remain the acceptance authority.
    Existing longer windows, device parameters and FRA resolution are retained.
    """
    from spice_export import normalize_settings
    from isolated_outputs import output_specs
    from plants import resolve_controller_type
    s = normalize_settings(settings)
    fs = s['frequency_hz'] or float(parameters['f_sw'])
    zeros = [s['fz1'] or float(parameters.get('fz1', 0))]
    if resolve_controller_type(parameters.get('controller_type','auto'),parameters.get('control_mode')) == 'type3':
        zeros.append(s['fz2'] or float(parameters.get('fz2', 0)))
    zeros = [f for f in zeros if f > 0]
    settling = max(.002, 420 / fs, 7 / (2 * math.pi * min(zeros)) if zeros else .004)
    step = s['enable_delay_ms'] + s['soft_start_ms'] + settling * 1000 + 420000 / fs
    # Even-millisecond rounding makes the recommendation easy to edit.
    s['step_ms'] = max(s['step_ms'], math.ceil(step / 2) * 2)
    after = max(s['stop_ms'] - settings.get('step_ms', s['step_ms']), 4., 420000 / fs)
    s['stop_ms'] = max(s['stop_ms'], s['step_ms'] + after)
    if s['short_test']:
        s['stop_ms'] = max(s['stop_ms'], s['short_start_ms'] + s['short_duration_ms'] + after)
    if scope == 'quick':
        s.update(fra_enabled=0., cross_enabled=0., short_test=0.)
    elif scope == 'full':
        s.update(fra_enabled=1., cross_enabled=float(len(output_specs(parameters)) > 1))
        if parameters.get('topology') == 'QR-FLYBACK':
            rails = output_specs(parameters)
            # An unchanged min/max load cannot measure cross regulation. Keep
            # the user's load range; never invent a light-load corner.
            if rails and not any(float(r.get('P_out_min', r['P_out'])) < float(r['P_out']) for r in rails):
                s['cross_enabled'] = 0.
    elif scope is not None:
        raise ValueError('未知仿真任务范围')
    return normalize_settings(s)


def execution_plan(parameters, settings):
    """Describe selected work, not a promise about simulator wall-clock time."""
    from isolated_outputs import output_specs
    from spice_studies import corner_plan
    from spice_export import normalize_settings
    s = normalize_settings(settings)
    lo = float(parameters.get('V_in_min', parameters['V_in']))
    hi = float(parameters.get('V_in_max', lo))
    voltages = list(dict.fromkeys((lo, hi)))
    rails = output_specs(parameters)
    cross_requested = bool(s['cross_enabled'] and len(rails) > 1)
    unchanged = bool(rails) and not any(float(r['P_out_min']) < float(r['P_out']) for r in rails)
    cross = cross_requested and not (parameters.get('topology') == 'QR-FLYBACK' and unchanged)
    cross_skip_reason = ('QR各路最小功耗与额定功耗相同，未定义轻重载变化；请先填写各路实际最小功耗。'
                         if parameters.get('topology') == 'QR-FLYBACK' and len(rails)>1 and unchanged else '')
    corners, coverage = corner_plan(rails, s['cross_mode']) if cross else ([], '未选择' if len(rails) > 1 else '单路不适用')
    fs = s['frequency_hz'] or float(parameters['f_sw'])
    stop = min(s['fra_stop_hz'], fs / 10)
    points = max(0, math.ceil(math.log2(stop / s['fra_start_hz']) * s['fra_oct']) + 1) if stop > s['fra_start_hz'] else 0
    stages = []
    for vin in voltages:
        for name in (['启动与负载阶跃', '短路注入'] if s['short_test'] else ['启动与负载阶跃']):
            stages.append(dict(vin=vin, kind='transient', name=name, duration_s=s['stop_ms'] / 1000,
                               timeout_s=s['simulation_timeout_s']))
        if s['fra_enabled']:
            stages.append(dict(vin=vin, kind='fra', name='环路 FRA 与半幅复核', points=points,
                               timeout_s=2 * s['fra_timeout_s']))
        if cross:
            stages.append(dict(vin=vin, kind='cross', name=f'{len(corners)} 组轻重载组合',
                               duration_s=max(s['step_ms'], 8.) / 1000 + (len(corners)-1) * s['cross_hold_ms'] / 1000,
                               timeout_s=s['cross_timeout_s']))
    skipped = []
    if not s['fra_enabled']:skipped.append('环路 FRA')
    if len(rails) > 1 and not cross:skipped.append('交叉调整率')
    if not s['short_test']:skipped.append('短路注入')
    return dict(voltages=voltages, output_count=max(1,len(rails)), stages=stages, cross_enabled=cross,
                cross_requested=cross_requested,cross_skip_reason=cross_skip_reason,
                cross_count=len(corners), cross_coverage=coverage, fra_enabled=bool(s['fra_enabled']),
                fra_points_approx=points, skipped=skipped,
                timeout_budget_s=sum(x['timeout_s'] for x in stages),
                transient_duration_s=sum(x.get('duration_s', 0) for x in stages),
                step_ms=s['step_ms'], stop_ms=s['stop_ms'], reuse=bool(s['simulation_reuse']))


def plan_text(plan):
    text = f"{len(plan['voltages'])} 个输入端点 · {plan['output_count']} 路输出 · 阶跃 {plan['step_ms']:g} ms / 结束 {plan['stop_ms']:g} ms"
    if plan['fra_enabled']:text += f"；FRA 约 {plan['fra_points_approx']} 点/端点 + 半幅复核"
    if plan['cross_enabled']:text += f"；负载角点 {plan['cross_count']} 组/端点"
    if plan['skipped']:text += '。本次不含：' + '、'.join(plan['skipped'])
    if plan.get('cross_skip_reason'):text += '。' + plan['cross_skip_reason']
    text += '。建议先快速预检；未稳定时暂停后续扫描。'
    return text
