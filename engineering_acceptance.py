"""Traceable engineering acceptance data, never a second physical solver.

Version 1 stores user targets, manually entered measurements and issue history.
All numerical design values are projections of already completed snapshots.
An input hash is an identity guard, not an instrument authenticity certificate.
"""
from __future__ import annotations

import copy
from datetime import datetime, timezone
import hashlib
import json
import math

SCHEMA = 'power-design.engineering-acceptance.v1'
VERSION = 1
SOURCES = ('calculation', 'simulation', 'measurement')
CASE_IDS = ('Vinmin', 'Vinmax')
STATE_LABELS = {'pass': '录入/模型值满足', 'review': '不满足 / 需整改',
                'undefined': '待补证据/目标', 'stale': '输入已变 / 证据失效',
                'na': '不适用'}
_DISPLAY_KEYS = {'input_voltage_case', 'ui_font_size', 'font_size', 'display_voltage_case',
                 'sweep_var', 'sweep_min', 'sweep_max', 'sweep_n'}


def _text(value, field, *, limit=8000):
    if value is None:
        return ''
    if not isinstance(value, str) or len(value) > limit:
        raise ValueError(f'{field} 应为不超过 {limit} 字的文字')
    return value.strip()


def _finite(value, field):
    if value is None or value == '':
        return None
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
        raise ValueError(f'{field} 必须为有限数值或空值')
    return float(value)


def _number(value):
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    return float(value) if math.isfinite(value) else None


def normalize(value=None):
    """Validate a config or a complete spec; return an owned JSON-safe config."""
    value = {} if value is None else value
    if not isinstance(value, dict):
        raise ValueError('engineering_acceptance 应为对象')
    if 'engineering_acceptance' in value:
        value = value.get('engineering_acceptance')
        value = {} if value is None else value
    if (not isinstance(value, dict) or type(value.get('version', 1)) is not int or
            value.get('version', 1) != 1):
        raise ValueError('不支持的工程验收配置版本')
    result = dict(version=1, criteria=[], measurements=[], issues=[])
    for group in ('criteria', 'measurements', 'issues'):
        rows = value.get(group, [])
        if not isinstance(rows, list) or len(rows) > 5000:
            raise ValueError(group + ' 应为不超过5000项的列表')
        used = set()
        for index, source in enumerate(rows):
            if not isinstance(source, dict):
                raise ValueError(group + ' 每项必须为对象')
            row = dict(id=_text(source.get('id'), group + '.id', limit=160))
            if not row['id'] or row['id'] in used:
                raise ValueError(group + ' 的 id 不能为空或重复')
            used.add(row['id'])
            if group == 'criteria':
                row.update(metric=_text(source.get('metric', row['id']), 'metric', limit=160),
                    name=_text(source.get('name'), 'name', limit=240),
                    unit=_text(source.get('unit'), 'unit', limit=40),
                    comparison=source.get('comparison', '<='),
                    limit=_finite(source.get('limit'), 'limit'),
                    lower=_finite(source.get('lower'), 'lower'),
                    upper=_finite(source.get('upper'), 'upper'),
                    note=_text(source.get('note'), 'note'),
                    enabled=source.get('enabled', True),
                    required_sources=copy.deepcopy(source.get('required_sources', list(SOURCES))))
                if row['comparison'] not in ('<=', '>=', '<', '>', 'range'):
                    raise ValueError('阈值关系应为 <=、>=、<、> 或 range')
                if not isinstance(row['enabled'], bool):
                    raise ValueError('enabled 必须为布尔值')
                if (not isinstance(row['required_sources'], list) or not row['required_sources'] or
                        any(s not in SOURCES for s in row['required_sources']) or
                        len(set(row['required_sources'])) != len(row['required_sources'])):
                    raise ValueError('required_sources 应为不重复的计算/仿真/实测来源列表')
                if row['comparison'] == 'range' and row['lower'] is not None and row['upper'] is not None and row['lower'] > row['upper']:
                    raise ValueError('阈值下限不能大于上限')
            elif group == 'measurements':
                row.update(criterion_id=_text(source.get('criterion_id'), 'criterion_id', limit=160),
                    case_id=source.get('case_id'), value=_finite(source.get('value'), 'measurement.value'),
                    source=_text(source.get('source'), 'measurement.source', limit=1000),
                    conditions=_text(source.get('conditions'), 'measurement.conditions'),
                    evidence_ref=_text(source.get('evidence_ref'), 'measurement.evidence_ref', limit=2000),
                    note=_text(source.get('note'), 'measurement.note'),
                    input_fingerprint=_text(source.get('input_fingerprint'), 'measurement.input_fingerprint', limit=100),
                    recorded_at=_text(source.get('recorded_at'), 'recorded_at', limit=100),
                    origin='manual-entry')
                if row['case_id'] not in CASE_IDS or not row['criterion_id']:
                    raise ValueError('实测必须指定指标及 Vinmin/Vinmax')
            else:
                row.update(title=_text(source.get('title'), 'issue.title', limit=240),
                    description=_text(source.get('description'), 'issue.description'),
                    action=_text(source.get('action'), 'issue.action'),
                    owner=_text(source.get('owner'), 'issue.owner', limit=160),
                    status=source.get('status', 'open'),
                    evidence=_text(source.get('evidence'), 'issue.evidence'),
                    input_fingerprint=_text(source.get('input_fingerprint'), 'issue.input_fingerprint', limit=100),
                    updated_at=_text(source.get('updated_at'), 'issue.updated_at', limit=100))
                if row['status'] not in ('open', 'in_progress', 'closed'):
                    raise ValueError('整改状态应为 open、in_progress 或 closed')
            result[group].append(row)
    return result


def _canonical_inputs(parameters):
    """Resolve active SI ownership without calculating physical operating points.

    Defaults are expanded without calculating or validating feasibility. Fields
    beginning with '_' are engine internals / saved provenance, never user
    electrical inputs. Nested physical winding positions and curve points stay.
    """
    if not isinstance(parameters, dict):
        raise ValueError('设计输入应为对象')
    from config_io import decode_config
    from power_stage import DEFAULT_PARAMS
    p = copy.deepcopy(DEFAULT_PARAMS)
    decoded = decode_config(parameters)
    p.update(decoded)
    present = ('V_in_min' in decoded, 'V_in_max' in decoded)
    if any(present) and not all(present):
        raise ValueError('输入电压范围必须同时有上下限才能匹配证据')
    if not any(present) and 'V_in' in decoded:
        p['V_in_min'] = p['V_in_max'] = decoded['V_in']
    # Reuse ownership rules, never compare UI compatibility mirrors as extra
    # independent hardware. Every actual branch remains in the canonical data.
    from capacitor_banks import normalize as normalize_capacitors
    p = normalize_capacitors(p)
    if p.get('outputs'):
        from isolated_outputs import output_specs, selected_params
        rails = output_specs(p)
        p = selected_params(p, rails)
        p['outputs'] = [{key: value for key, value in r.items() if key != 'id'} for r in rails]
    from mos_manual import manual_platform, normalize_events
    if manual_platform(p):
        p['mos_manual_events'] = normalize_events(p.get('mos_manual_events'), p)
        for key in ('Vgp_on', 'Vgp_off', 'Qgs'):
            p.pop(key, None)  # overridden by explicit/legacy-expanded events
    coupling = p.get('coupling_config') or {}
    if not coupling.get('enabled') and not coupling.get('field_matrix_enabled'):
        p['coupling_config'] = dict(enabled=False, field_matrix_enabled=False)
    else:
        # DCR has been geometric, not an editable winding-model input, since
        # TRANSFORMER_ELECTRICAL. Preserve the actual k/self-L/port order.
        p['coupling_config'] = {key: value for key, value in coupling.items() if key != 'dcr'}
    if coupling.get('enabled') or p.get('topology') == 'ACF-FORWARD':
        p.pop('K', None)  # matrix leakage / active clamp owns this quantity
    if p.get('topology') in ('BUCK', 'BOOST', 'BUCK-BOOST'):
        p.pop('K', None)
        p.pop('Kc', None)  # flyback RCD controls have no nonisolated owner
    if p.get('winding_config'):
        winding = copy.deepcopy(p['winding_config'])
        actual_windings = {'P'} | {f'OUT{i}' for i in range(1, len(p.get('outputs') or [1])+1)}
        if p.get('feedback_mode') == 'PSR-MP6005':
            actual_windings.add('AUX')
        winding['overrides'] = {key: value for key, value in (winding.get('overrides') or {}).items()
                               if key in actual_windings}
        p['winding_config'] = winding
    for key in ('tr', 'tf', 'le_core'):
        p.pop(key, None)  # legacy edge times / le have no active formula owner
    p.pop('engineering_acceptance', None)
    for key in tuple(p):
        if key.startswith('_') or key in _DISPLAY_KEYS:
            p.pop(key, None)
    if 'V_in_min' in p and 'V_in_max' in p:
        p.pop('V_in', None)
    # JSON numbers 1 and 1.0 have identical engineering meaning.
    def canonical(value):
        if isinstance(value, dict):
            return {str(k): canonical(v) for k, v in sorted(value.items())}
        if isinstance(value, (list, tuple)):
            return [canonical(v) for v in value]
        if isinstance(value, bool) or value is None or isinstance(value, str):
            return value
        if isinstance(value, (int, float)):
            if not math.isfinite(value):
                raise ValueError('输入包含非有限数，不能匹配证据')
            return float(format(float(value), '.15g'))
        if hasattr(value, 'tolist'):
            return canonical(value.tolist())
        raise ValueError('输入包含非JSON数据，不能匹配证据')
    return canonical(p)


def input_fingerprint(parameters):
    """Hash active inputs; UI drafts, legacy mirrors and evidence are excluded."""
    blob = json.dumps(_canonical_inputs(parameters), ensure_ascii=False, sort_keys=True, separators=(',', ':'), allow_nan=False)
    return hashlib.sha256(blob.encode('utf-8')).hexdigest()


def _base_spec(bundle):
    return bundle.get('base_spec', bundle.get('spec')) if isinstance(bundle, dict) else None


def _matches(spec, fingerprint):
    try:
        return isinstance(spec, dict) and input_fingerprint(spec) == fingerprint
    except (ValueError, TypeError):
        return False


def _cases(bundle):
    rows = bundle.get('cases', []) if isinstance(bundle, dict) else []
    if isinstance(bundle, dict) and not rows and (bundle.get('res') or bundle.get('result')):
        base = bundle.get('base_spec') or bundle.get('p') or {}
        case_id = 'Vinmax' if base.get('input_voltage_case') == 'max' else 'Vinmin'
        rows = [dict(id=case_id, result=bundle.get('res') or bundle.get('result'),
                     checks=bundle.get('checks', []), loop_error=bundle.get('loop_error'))]
    return {row.get('id'): row for row in rows if isinstance(row, dict) and row.get('id') in CASE_IDS}


def _default_rows(parameters, calculation_cases):
    """Metric registration and thresholds project existing checks, not formulas."""
    result = []
    def add(key, name, unit='', comparison='<=', limit=None, note=''):
        result.append(dict(id=key, metric=key, name=name, unit=unit, comparison=comparison,
            limit=limit, lower=None, upper=None, note=note, enabled=True, required_sources=list(SOURCES)))
    add('eta', '模型效率', '', '>=', parameters.get('target_eta'), '比例值，例如0.93表示93%；未计热态/未建模附加损耗。')
    add('primary_rms', '电感/原边电流 RMS', 'A')
    add('primary_peak', '电感/原边电流峰值', 'A')
    add('vds_peak', 'MOS 稳态最大 Vds', 'V', note='计算包络与实际瞬态模型可能不同；另查全启动极值。')
    add('startup_vds_peak', 'MOS 全启动 Vds 峰值', 'V', note='缺少全程极值时不以稳态峰值代替。')
    add('fc', '环路穿越频率', 'Hz')
    add('phase_margin', '全部穿越最小相位裕度', 'deg', '>=', parameters.get('pm_target'))
    add('gain_margin', '测得频带内有限增益裕度', 'dB', '>=' , 0., '无相位交越不等于无限裕度。')
    add('temperature_rise', '磁件最高估算温升', 'K', '<=', parameters.get('temp_rise_limit'), '给定热阻/对流的模型值，不是热点实测。')
    rails = parameters.get('outputs') or [dict(V_out=parameters.get('V_out'), ripple_target=parameters.get('ripple_target'))]
    for index, rail in enumerate(rails, 1):
        add(f'out{index}_voltage', f'OUT{index} 端口平均电压', 'V', note='防反管后端口；用户填写允许范围。')
        add(f'out{index}_ripple', f'OUT{index} 低频输出纹波', 'V', note='已有低频纹波检查阈值；不含未建模尖峰。')
        add(f'out{index}_rms', f'OUT{index} 整流/副边电流 RMS', 'A')
        add(f'out{index}_peak', f'OUT{index} 整流/副边电流峰值', 'A')
    # Reuse unified engineering check thresholds, including the actual ripple
    # target evaluated by that model. Unknown/NA check limits remain unknown.
    for case in calculation_cases.values():
        for check in case.get('checks') or (case.get('result') or {}).get('checks') or []:
            cid = check.get('id')
            if cid == 'ripple' and len(rails) == 1:
                row = next(r for r in result if r['id'] == 'out1_ripple')
                row['limit'] = _number(check.get('limit'))
            for index in range(1, len(rails)+1):
                if cid == f'OUT{index}_ripple':
                    next(r for r in result if r['id'] == f'out{index}_ripple')['limit'] = _number(check.get('limit'))
            if cid == 'bom_Q1_voltage':
                for key in ('vds_peak', 'startup_vds_peak'):
                    next(r for r in result if r['id'] == key)['limit'] = _number(check.get('limit'))
            if cid == 'phase_margin':
                next(r for r in result if r['id'] == 'phase_margin')['limit'] = _number(check.get('limit'))
        break
    return result


def _calculation_values(case):
    res = case.get('result') or case.get('res') or {}
    op = res.get('op') or case.get('op') or {}
    wf = res.get('wf') or case.get('wf') or {}
    loop = res.get('loop') or {}
    magnetic = res.get('mag') or {}
    temperatures = [_number(d.get('dT')) for key in ('transformer', 'inductor')
                    if isinstance((d := magnetic.get(key)), dict)]
    values = dict(eta=res.get('eta'), primary_rms=op.get('I_p_rms', op.get('I_L_rms', op.get('I_sw_rms'))),
        primary_peak=op.get('I_sw_pk', op.get('I_L_pk')), vds_peak=op.get('V_sw_max'),
        startup_vds_peak=None, fc=loop.get('fc'), phase_margin=loop.get('min_pm'),
        gain_margin=loop.get('gm_db'), temperature_rise=max((v for v in temperatures if v is not None), default=None))
    outputs = res.get('outputs') or [dict(op=op, ripple_pp=wf.get('ripple_pp'))]
    for index, rail in enumerate(outputs, 1):
        child = rail.get('op') or {}
        values.update({f'out{index}_voltage': child.get('V_out'),
            f'out{index}_ripple': rail.get('ripple_pp'),
            f'out{index}_rms': child.get('I_s_rms', child.get('I_d_rms')),
            f'out{index}_peak': child.get('I_s_pk', child.get('I_d_pk'))})
    return {k: _number(v) for k, v in values.items()}


def _simulation_values(case):
    measured = case.get('measurements') or {}
    loop = case.get('loop') or {}
    metrics = loop.get('simulation') or loop.get('metrics') or {}
    metrics = metrics.get('loop', metrics)
    values = dict(primary_rms=measured.get('primary_rms'), primary_peak=measured.get('primary_peak'),
                  vds_peak=measured.get('vds_peak'))
    startup = case.get('full_transient') or case.get('startup_extrema') or {}
    # QR's existing full-transient scan is stored separately from plotted data.
    values['startup_vds_peak'] = startup.get('vds_peak_full_v')
    for container in (case.get('startup') or {}, case.get('runtime') or {}, case.get('full_run') or {}, case.get('qr_startup') or {}):
        if isinstance(container, dict) and container.get('vds_peak_full_v') is not None:
            values['startup_vds_peak'] = container['vds_peak_full_v']
    if loop.get('available'):
        values.update(fc=metrics.get('fc'), phase_margin=metrics.get('pm'), gain_margin=metrics.get('gm_db'))
    for key, value in measured.items():
        if not key.startswith('out'):
            continue
        for suffix, target in (('_before', '_voltage'), ('_pre_ripple', '_ripple'),
                               ('_winding_rms', '_rms'), ('_winding_peak', '_peak')):
            if key.endswith(suffix):
                values[key[:-len(suffix)] + target] = value
    return {k: _number(v) for k, v in values.items()}


def _judge(value, criterion):
    if value is None:
        return 'undefined', None
    operator = criterion['comparison']
    if operator == 'range':
        lo, hi = criterion.get('lower'), criterion.get('upper')
        if lo is None or hi is None:
            return 'undefined', None
        margin = min(value - lo, hi - value)
        return ('pass' if margin >= 0 else 'review'), margin
    limit = criterion.get('limit')
    if limit is None:
        return 'undefined', None
    margin = limit - value if operator in ('<=', '<') else value - limit
    passed = margin > 0 if operator in ('<', '>') else margin >= 0
    return ('pass' if passed else 'review'), margin


def _spice_binding(p, fingerprint, joint_record, spice_evidence, notes):
    envelope = spice_evidence or {}
    if isinstance(envelope, dict) and envelope.get('evidence_error'):
        notes.append('仿真证据引用不可用：' + str(envelope['evidence_error']))
    if isinstance(envelope, dict) and envelope.get('input_fingerprint') == fingerprint and isinstance(envelope.get('evidence'), dict):
        return envelope['evidence'], True, _text(envelope.get('source') or '当前输入绑定的电路仿真记录', 'source')
    if (isinstance(envelope, dict) and envelope.get('schema') == 'powerdesign-spice-comparison-2' and
            envelope.get('input_fingerprint') == fingerprint and isinstance(envelope.get('cases'), list)):
        return envelope, True, '原生电路仿真证据 / 当前输入指纹匹配'
    joint = joint_record or {}
    if isinstance(joint, dict) and isinstance(joint.get('record'), dict):
        joint = joint['record']
    if isinstance(joint, dict) and _matches(joint.get('adopted_config'), fingerprint):
        evidence = (joint.get('circuit') or {}).get('evidence')
        if isinstance(evidence, dict):
            return evidence, True, '联合任务当前采用硬件 / ' + str(joint.get('directory') or '内存记录')
    if envelope or joint:
        notes.append('既有电路/联合证据未与当前采用输入匹配；未借用旧数据通过。联合原输入与回填后硬件不同，请先采用硬件或打开其工程。')
    return {}, False, '未取得匹配配置的仿真证据'


def report_snapshot(p, range_result=None, joint_record=None, spice_evidence=None):
    """Pure completed-data projection. Never reads arbitrary paths or runs tools."""
    from config_io import decode_config
    p = decode_config(p)
    if spice_evidence is None and isinstance(range_result, dict):
        spice_evidence = range_result.get('engineering_acceptance_evidence')
    fingerprint = input_fingerprint(p)
    config = normalize(p.get('engineering_acceptance'))
    notes = ['计算/通用行为仿真/手工录入分别列示；满足仅针对所选目标，不是硬件认证。',
             '手工实测为用户录入，软件不证明仪器校准、接法、带宽或数据真实性。']
    matched = _matches(_base_spec(range_result), fingerprint)
    calculation_cases = _cases(range_result) if matched else {}
    if range_result is not None and not matched:
        notes.append('两端计算快照与当前真实输入不同，计算数据已失效；请显式刷新两端。')
    criteria = _default_rows(p, calculation_cases)
    by_id = {row['id']: row for row in criteria}
    for override in config['criteria']:
        if override['id'] in by_id:
            current = by_id[override['id']]
            current.update({key: value for key, value in override.items()
                            if key not in ('name', 'unit') or value})
        else:
            criteria.append(copy.deepcopy(override))
    spice, bound, origin = _spice_binding(p, fingerprint, joint_record, spice_evidence, notes)
    simulated = [c for c in spice.get('cases', []) if isinstance(c, dict) and not c.get('fault_test')]
    measurements = {(m['criterion_id'], m['case_id']): m for m in config['measurements']}
    rows = []
    for criterion in criteria:
        row = copy.deepcopy(criterion)
        row['cases'] = {}
        for case_id in CASE_IDS:
            case = calculation_cases.get(case_id) or {}
            vin = p.get('V_in_min' if case_id == 'Vinmin' else 'V_in_max', p.get('V_in'))
            # Endpoints can share a voltage but have separate manual gate-charge
            # events. A named Vinmin record must never fill a missing Vinmax.
            sim = next((c for c in simulated if str(c.get('id', '')).split('_', 1)[0] == case_id
                        and _number(c.get('voltage')) == _number(vin)), {})
            shared_note = ''
            if not sim:
                from mos_manual import distinct_endpoints
                legacy_shared = (p.get('V_in_min') == p.get('V_in_max') and not distinct_endpoints(p))
                if legacy_shared:
                    sim = next((c for c in simulated if _number(c.get('voltage')) == _number(vin)), {})
                    if sim:
                        shared_note = '同电压且MOS事件相同，复用 ' + str(sim.get('id') or '原单工况') + '；未重新仿真'
            measurement = measurements.get((criterion['id'], case_id))
            values = _calculation_values(case) if case and not case.get('error') else {}
            simvalues = _simulation_values(sim)
            available = dict(calculation=values.get(criterion['metric']), simulation=simvalues.get(criterion['metric']),
                measurement=measurement.get('value') if measurement else None)
            states, margins, reasons = {}, {}, [shared_note] if shared_note else []
            for source in SOURCES:
                state, margin = _judge(available[source], criterion)
                if not criterion['enabled']:
                    state, margin = 'na', None
                elif source == 'calculation' and range_result is not None and not matched:
                    state, margin = 'stale', None
                elif source == 'simulation' and sim:
                    valid = bool(bound and sim.get('complete') and sim.get('nominal_comparable') and
                                 (sim.get('periodicity') or {}).get('stable') and not sim.get('protection_stop'))
                    if not valid:
                        state, margin = 'undefined', None
                        reasons.append('仿真未通过标称/逐周期检查或处于保护')
                    elif criterion['metric'] in ('fc', 'phase_margin', 'gain_margin') and not (sim.get('loop') or {}).get('available'):
                        state, margin = 'undefined', None
                elif source == 'measurement' and measurement:
                    if measurement['input_fingerprint'] != fingerprint:
                        state, margin = 'stale', None
                        reasons.append('实测记录对应旧输入')
                    elif not measurement['source'] or not measurement['conditions']:
                        state, margin = 'undefined', None
                        reasons.append('实测缺来源或测试条件')
                states[source], margins[source] = state, margin
            required = [states[s] for s in criterion['required_sources']]
            status = ('na' if not criterion['enabled'] else 'review' if 'review' in required else
                      'stale' if 'stale' in required else 'undefined' if 'undefined' in required else 'pass')
            base = available['calculation']
            def delta(value):
                return (value - base) / abs(base) * 100 if base not in (None, 0) and value is not None else None
            usable_margins = [margins[s] for s in criterion['required_sources'] if margins[s] is not None]
            row['cases'][case_id] = dict(V_in=_number(vin), **available, states=states, margins=margins,
                margin=min(usable_margins) if len(usable_margins) == len(required) else None,
                delta_simulation=delta(available['simulation']) if states['calculation'] != 'stale' else None,
                delta_measurement=delta(available['measurement']) if 'stale' not in (states['calculation'], states['measurement']) else None,
                status=status, reason='；'.join(dict.fromkeys(reasons)),
                sources=dict(calculation='当前双端共享计算快照' if matched else '未取得匹配双端快照',
                             simulation=origin, measurement=measurement['source'] if measurement else ''),
                measurement_record=copy.deepcopy(measurement),
                calculation_error=case.get('error') or case.get('loop_error'))
        rows.append(row)
    issues = copy.deepcopy(config['issues'])
    for issue in issues:
        issue['effective_status'] = ('stale' if issue['status'] == 'closed' and issue['input_fingerprint'] != fingerprint else
            'undefined' if issue['status'] == 'closed' and not issue['evidence'] else issue['status'])
    counts = {state: sum(r['cases'][c]['status'] == state for r in rows for c in CASE_IDS) for state in STATE_LABELS}
    open_issues = sum(i['effective_status'] != 'closed' for i in issues)
    enabled = sum(r['enabled'] for r in rows)
    summary_state = ('review' if counts['review'] or open_issues else 'stale' if counts['stale'] else
                     'undefined' if counts['undefined'] or not enabled else 'pass')
    return dict(schema=SCHEMA, version=VERSION, input_fingerprint=fingerprint,
        rows=rows, criteria=copy.deepcopy(criteria), issues=issues, evidence_notes=notes,
        calculation_matched=matched, simulation_matched=bound,
        summary=dict(state=summary_state, counts=counts, unresolved_issues=open_issues,
            label=STATE_LABELS[summary_state], scope='仅覆盖本页启用指标、指定来源和Vin两端；不等于所有负载/温度/容差/安规验收'),
        config=config)


def manual_measurement(p, criterion_id, case_id, value, *, source, conditions, evidence_ref='', note='', record_id=None):
    """Bind an explicit user entry to this exact input; no automatic rebinding."""
    return normalize(dict(measurements=[dict(id=record_id or f'{criterion_id}:{case_id}',
        criterion_id=criterion_id, case_id=case_id, value=value, source=source, conditions=conditions,
        evidence_ref=evidence_ref, note=note, input_fingerprint=input_fingerprint(p),
        recorded_at=datetime.now(timezone.utc).isoformat())]))['measurements'][0]
