"""Auditable field → fixed-hardware calculation → LTspice joint workflow.

The user's project is never mutated. Automatic adoption happens only inside
the exported run; callers may separately offer explicit project adoption.
"""
from __future__ import annotations

import copy
from datetime import datetime
import math
from pathlib import Path
import time
from uuid import uuid4
from zipfile import ZipFile

import numpy as np

from calculation_scheduler import CalculationCancelled
from design_engine.contracts import json_value
from design_engine.service import calculate, validate_spec
from transformer_geometry import json_bytes, read_geometry_package, resolve_geometry, strict_json
from transformer_simulation import (_calculate, _endpoint_metrics, _field_values, _input_id,
                                    _keep_physical_gap, _proposal, _set_si, _sha)


STAGES = (('prepare', '冻结输入与智能准备'), ('field', '变压器场仿真'),
          ('margin', '矩阵校验与漏感裕量'), ('calculation', '同一硬件设计复算'),
          ('spice', '电路仿真与对比'), ('report', '联合报告'))
REPORT_NAME = '电磁仿真，电路仿真，设计计算联合报告.docx'
LIMITS = [
    '磁场结果来自线性、零偏置磁静态；单次求解不代表网格收敛、交流场或样机验证。',
    '漏感裕量默认1.20倍是可修改的项目工程假设，不是厂家推荐值或实测修正系数。',
    '裕量保持各绕组自感，以原边、其余功率绕组全部理想短路的漏感为目标统一调整互感。',
    '自动采用仅作用于本次导出副本；不会自动覆盖当前单元或原始工程。',
    '电路仿真使用本软件通用行为控制器，不冒充原厂芯片模型或实测结论。',
]


def _short(matrix, primary):
    other = [i for i in range(len(matrix)) if i != primary]
    return float(matrix[primary, primary] - matrix[primary, other] @
                 np.linalg.solve(matrix[np.ix_(other, other)], matrix[other, primary]))


def apply_leakage_margin(values, factor=1.2):
    """Keep self-L and SPD, solving Lsc(margin) = factor * Lsc(field).

    K(a) = (1-a) I + a Kfield, a ∈ [0,1]. This convex family preserves
    realizability; independently multiplying pairwise k does not.
    """
    if isinstance(factor, bool):
        raise ValueError('漏感裕量倍数必须为不小于1的有限数值')
    try:
        factor = float(factor)
    except (ValueError, TypeError):
        raise ValueError('漏感裕量倍数必须为不小于1的有限数值') from None
    if not math.isfinite(factor) or factor < 1:
        raise ValueError('漏感裕量倍数必须为不小于1的有限数值')
    ports = list(values['port_order'])
    matrix = np.asarray(values['L_ports_H'], dtype=float)
    if len(ports) != len(set(ports)) or ports.count('P') != 1 or len(ports) < 2:
        raise ValueError('裕量矩阵需要唯一P及至少一个副边端口')
    if (matrix.shape != (len(ports), len(ports)) or not np.isfinite(matrix).all()
            or not np.allclose(matrix, matrix.T, rtol=1e-10, atol=1e-15)
            or np.linalg.eigvalsh(matrix).min() <= 0):
        raise ValueError('裕量输入电感矩阵不是有限对称正定矩阵')
    diagonal = matrix.diagonal()
    scale = np.sqrt(np.outer(diagonal, diagonal))
    k = matrix / scale
    if np.any(k < 0):
        raise ValueError('存在反向互感，请核对同名端，不能自动采用')
    primary = ports.index('P')
    lp, original_short = float(diagonal[primary]), _short(matrix, primary)
    target = factor * original_short
    identity_retained = factor == 1 and math.isclose(original_short, lp, rel_tol=1e-14, abs_tol=1e-20)
    if target >= lp and not identity_retained:
        raise ValueError(f'漏感裕量目标{target:.6g} H不小于原边自感{lp:.6g} H，无法在保持自感时实现；请降低倍数')
    eye = np.eye(len(ports))
    alpha = 1.
    if factor != 1:
        left, right = 0., 1.
        for _ in range(90):
            alpha = (left + right) / 2
            candidate = (eye + alpha * (k - eye)) * scale
            if _short(candidate, primary) > target:
                left = alpha
            else:
                right = alpha
        alpha = (left + right) / 2
    adopted_k = eye + alpha * (k - eye)
    adopted_l = adopted_k * scale
    adopted_short = _short(adopted_l, primary)
    if (np.linalg.eigvalsh(adopted_l).min() <= 0 or
            not math.isclose(adopted_short, target, rel_tol=1e-9, abs_tol=1e-17)):
        raise ValueError('漏感裕量求根未通过正定性与目标复核')
    return dict(factor=factor, method='K(a)=(1-a)I+aK_field; Lsc_target=factor*Lsc_field',
                port_order=ports, original_L_ports_H=matrix.tolist(),
                adopted_L_ports_H=adopted_l.tolist(), original_k_ports=k.tolist(),
                adopted_k_ports=adopted_k.tolist(), primary_self_H=lp,
                original_primary_short_H=original_short, adopted_primary_short_H=adopted_short,
                off_diagonal_scale=alpha,
                original_short_by_port_H=[_short(matrix, i) for i in range(len(ports))],
                adopted_short_by_port_H=[_short(adopted_l, i) for i in range(len(ports))],
                notes=['所有自感保持不变，全部互感按同一个a缩放。',
                       '倍数仅针对原边全短路漏感；各副边的漏感变化另行列出，不保证同倍数。',
                       '1.20倍为项目默认假设；1.00倍保留原始场解，不代表样机验证。'])


def _freeze_hardware(config, run):
    """Pin resolved conductors/turns before extracting fields, never after."""
    from analysis_workflows import pin_hardware
    bundle = run.runtime_bundle()
    _endpoint_metrics(bundle['cases'])
    first = bundle['cases'][0]
    candidate = pin_hardware(first['p'], first['result'])
    fixed = candidate.get('_fixed_transformer')
    if not fixed:
        raise ValueError('当前单元没有可用变压器，无法冻结场仿真硬件')
    for key in ('Np', 'Ns', 'd_wire_p', 'd_wire_s', 'n_strand_p', 'n_strand_s',
                'parallel_wires_p', 'parallel_wires_s', 'MLT'):
        if key in fixed:
            candidate[key] = copy.deepcopy(fixed[key])
    candidate['core_choice'] = fixed['core']
    # Public design specifications deliberately reject internal _fixed_* keys.
    # Freeze their resolved values into the supported explicit hardware inputs.
    candidate = {key: value for key, value in candidate.items() if not key.startswith('_')}
    candidate.update({k: copy.deepcopy(v) for k, v in config.items() if k.startswith('__')})
    return candidate


def _adopt(config, field_record, margin):
    base = validate_spec(config)
    if not base['ok']:
        raise ValueError('; '.join(issue['message'] for issue in base['issues']))
    p = base['spec']
    values = dict(port_order=margin['port_order'], L_ports_H=margin['adopted_L_ports_H'],
                  k_ports=margin['adopted_k_ports'], primary_self_H=margin['primary_self_H'],
                  primary_short_H=margin['adopted_primary_short_H'])
    notes = []
    # The original adopter already distinguishes historical RCD K from pairwise k.
    q = _proposal(config, p, values, notes)
    power_ids = ['P'] + [f'OUT{i+1}' for i in range(len(p.get('outputs') or [1]))]
    order = margin['port_order']
    if set(order) != set(power_ids):
        raise ValueError('场解包含当前电路未建模的端口，不能静默删去或把该端口短路后采用')
    coupling = copy.deepcopy(p.get('coupling_config') or {})
    indices = [order.index(name) for name in power_ids]
    qr_multi=p['topology']=='QR-FLYBACK' and len(p.get('outputs') or [])>1
    coupling.update(enabled=p['topology'] != 'QR-FLYBACK' or qr_multi, field_matrix_enabled=True,
                    port_order=power_ids,
                    k=np.asarray(margin['adopted_k_ports'])[np.ix_(indices, indices)].tolist(),
                    self_inductances_H=np.diag(margin['adopted_L_ports_H'])[indices].tolist(),
                    source='joint-field-margin')
    q['coupling_config'] = coupling
    # _proposal also serves older scalar-only callers; replace its legacy
    # mapping explanation now that this workflow consumes every power self-L.
    if p['topology'] != 'QR-FLYBACK' or qr_multi:
        notes = [note for note in notes if not any(text in note for text in
                 ('实际匝比构造副边自感', '仅采用原边总短路漏感', 'QR 保留原谷底开通模型'))]
        notes.append('功率级设计计算与电路仿真采用同一组完整场解自感及裕量后互感；副边自感不再按原边自感和匝比重构。')
    _set_si(q, 'rcd_K' if 'rcd_K' in q else 'K',
            1 - margin['adopted_primary_short_H'] / margin['primary_self_H'])
    if 'rcd_K' in q:
        q.pop('K', None)
    if qr_multi:
        notes.append('QR多路设计与交叉负载采用完整场解矩阵、实际DCR和退磁/离散谷底稳态求解；电路仿真继续保留真实ZCD等动态，用于独立复核时序近似。')
    elif p['topology'] == 'QR-FLYBACK':
        notes.append('QR设计采用原边全短路漏感折算的快速标量K；完整场解矩阵保留供电路仿真，不能声称QR快速模型逐绕组精确求解。')
    project = field_record['model_conditions']
    _keep_physical_gap(q, project)
    q['__transformer_simulation'] = copy.deepcopy(field_record)
    q['__transformer_simulation'].update(joint_margin=copy.deepcopy(margin), adoption_scope='joint-export-copy')
    return q, notes


def _write(path, value):
    path = Path(path)
    temporary = path.with_suffix(path.suffix + '.tmp')
    temporary.write_bytes(json_bytes(json_value(value)))
    temporary.replace(path)


def run_joint_simulation(config, *, tool_root='builtin', project_file=None, output_directory,
                         leakage_factor=1.2, executable=None, prepare_reference_inputs=True,
                         resume_field=None, cancelled=None, progress=None, environment=None):
    """Run all stages serially in an isolated, uniquely named export directory.

    ``resume_field`` is an optional {package,result_directory} bundle, checked
    through the same source/hash/artifact verification as a new field run.
    ``progress`` receives {stage,message,status}. No Tk objects are accessed.
    """
    cancel = cancelled or (lambda: False)
    original = copy.deepcopy(config)
    directory = Path(output_directory).expanduser().resolve() / (
        '联合仿真-' + datetime.now().strftime('%Y%m%d-%H%M%S-') + uuid4().hex[:8])
    directory.mkdir(parents=True, exist_ok=False)
    manifest = directory / 'joint-record.json'
    record = dict(schema='power-design.joint-simulation.v1', status='running',
                  directory=str(directory), started_at=datetime.now().astimezone().isoformat(),
                  input_id=_input_id(original), original_config=original, limits=list(LIMITS),
                  stages=[dict(name=k, label=label, status='pending') for k, label in STAGES])
    if resume_field:
        record['stages'][1]['label'] = '既有场解与输入重校验'
    design_run = None
    spice_result = None
    proposed = None
    active = None
    started = time.monotonic()

    def publish(name, message, status='running'):
        if progress:
            progress(dict(stage=name, message=message, status=status))

    def begin(name, message):
        nonlocal active
        if cancel():
            raise CalculationCancelled()
        active = next(s for s in record['stages'] if s['name'] == name)
        active.update(status='running', started=time.monotonic())
        _write(manifest, record)
        publish(name, message)

    def finish(status='complete', **data):
        active.update(status=status, elapsed_s=time.monotonic()-active.pop('started'), **data)
        _write(manifest, record)
        publish(active['name'], active.get('error') or active['label'] + '已完成', status)

    try:
        begin('prepare', '检查支持范围、冻结同一套磁芯绕组并准备本次任务')
        from spice_runtime import find_ltspice
        executable = executable or (environment or {}).get('ltspice') or find_ltspice()
        if not executable or not Path(executable).is_file():
            raise ValueError('请先在集中设置中选择有效的 LTspice.exe，避免场解完成后才发现无法运行电路')
        validated = validate_spec(original)
        if not validated['ok']:
            raise ValueError('; '.join(i['message'] for i in validated['issues']))
        p = validated['spec']
        if p['topology'] not in ('FLYBACK', 'QR-FLYBACK', 'ACF-FORWARD'):
            raise ValueError('变压器联合报告目前支持反激、准谐振反激和有源钳位正激')
        if p.get('feedback_mode', 'SSR') != 'SSR':
            raise ValueError('当前电路对比仅支持SSR；PSR不得套用SSR闭环')
        if isinstance(leakage_factor, bool) or not math.isfinite(float(leakage_factor)) or float(leakage_factor) < 1:
            raise ValueError('漏感裕量倍数必须为不小于1的有限数值')
        if resume_field:
            # Resume accepts the EXACT archived frozen input, not a newly
            # normalized or "equivalent" GUI project. The verified adapter
            # below checks its input hash and all archived field artifacts.
            candidate = copy.deepcopy(original)
        else:
            candidate = _freeze_hardware(original, _calculate(original, cancel))
            from spice_planning import recommend_settings
            from config_io import decode_config
            candidate['spice_config'] = recommend_settings(decode_config(candidate),
                candidate.get('spice_config') or {}, scope='full')
        if environment is not None and not resume_field:
            from simulation_environment import check_environment
            environment = dict(environment, ltspice=str(executable))
            checked = check_environment(environment, require_spice=True, probe=True)
            record['environment_check'] = checked
            if not checked['ok']:
                raise ValueError('仿真环境检查未通过：' + '; '.join(
                    item['name'] + '：' + item['message'] for item in checked['checks'] if not item['ok']))
            if cancel():
                raise CalculationCancelled()
            from portable_transformer_project import prepare_portable_reference
            prepared = prepare_portable_reference(candidate, environment=environment,
                output_directory=directory, cancelled=cancel)
            candidate, project_file = prepared['config'], prepared['project_file']
            tool_root = 'builtin'
            record['reference_preparation'] = prepared['summary']
            record['runtime_mode'] = 'builtin'
        elif prepare_reference_inputs and not resume_field:
            from transformer_sim_reference import prepare_reference
            prepared = prepare_reference(candidate, project_file=project_file,
                                          output_directory=directory, cancelled=cancel)
            candidate, project_file = prepared['config'], prepared['project_file']
            record['reference_preparation'] = prepared['summary']
        # Seal physical CAD/gap metadata before exporting and hashing the field
        # input, so subsequent adoption does not itself change that geometry.
        if not resume_field:
            _keep_physical_gap(candidate, strict_json(Path(project_file).read_bytes()))
            normalized = validate_spec(candidate)
            if not normalized['ok']:
                raise ValueError('; '.join(i['message'] for i in normalized['issues']))
            candidate = dict(normalized['spec'], **{k:copy.deepcopy(v) for k,v in candidate.items() if k.startswith('__')})
        record['prepared_config'] = copy.deepcopy(candidate)
        _write(directory / '01-冻结输入.json', candidate)
        finish()

        begin('field', '校验既有场解产物与本次变压器的匹配性' if resume_field else
              '导出本次变压器并求解所有绕组的自感与互感')
        if resume_field:
            if resume_field.get('allow_load_only_rebind'):
                from transformer_field_reuse import complete_load_rebound_field_comparison
                field_run = complete_load_rebound_field_comparison(candidate, resume_field['package'],
                    resume_field['result_directory'], directory, cancelled=cancel,
                    project_file=project_file)
            else:
                from transformer_simulation import complete_field_comparison
                field_run = complete_field_comparison(candidate, resume_field['package'],
                    resume_field['result_directory'], directory, cancelled=cancel,
                    project_file=project_file)
            record['resumed_field'] = dict(resume_field)
        else:
            from transformer_simulation import run_transformer_simulation
            field_run = run_transformer_simulation(candidate, tool_root=tool_root,
                project_file=project_file, output_directory=directory, cancelled=cancel,
                progress=lambda message: publish('field', message))
        record['field'] = copy.deepcopy(field_run['record'])
        record['transformer'] = dict(record=record['field'])
        if not field_run.get('proposed_config'):
            raise ValueError('场解已完成，但同硬件回填预检失败：'+record['field'].get('adoption_error', '未知原因'))
        finish()

        begin('margin', '保持自感，按原边全短路漏感倍数求取可实现的裕量矩阵')
        margin = apply_leakage_margin(record['field']['field'], leakage_factor)
        proposed, notes = _adopt(candidate, record['field'], margin)
        record['margin'] = margin
        record['limits'].extend(notes)
        record['adopted_config'] = copy.deepcopy(proposed)
        _write(directory / '02-已采用裕量矩阵.json', proposed)
        finish()

        begin('calculation', '在同一硬件及新矩阵上计算Vinmin/Vinmax、损耗、波形与环路')
        design_run = calculate(proposed, analysis='endpoints', include_loop=True,
            include_efficiency=True, include_cross_regulation=True, cancelled=cancel,
            progress=lambda done, total, message: publish('calculation', message))
        bundle = design_run.runtime_bundle()
        metrics = _endpoint_metrics(bundle['cases'])
        # Ensure the electrical adoption did not silently rewind or remachine it.
        source_geometry = read_geometry_package(Path(record['field']['directory']) / '当前变压器.zip'
            if not resume_field else resume_field['package'])
        after_geometry, _ = resolve_geometry(bundle['cases'], source_geometry['source']['engine_snapshot_id'],
            source_geometry['source']['input_sha256'], source_geometry['source']['design_id'], cancelled=cancel)
        if after_geometry['source']['geometry_sha256'] != source_geometry['source']['geometry_sha256']:
            reused = record['field'].get('reused_field_provenance')
            if not reused:
                raise ValueError('回填后磁芯或绕组发生改变，不能继续套用旧场解')
            from transformer_field_reuse import _geometry_audit
            # Adopting a verified field may seal its already-known CAD/gap
            # provenance. Audit those exact additions rather than treating
            # them as new physical geometry or relaxing the general guard.
            changes = _geometry_audit(source_geometry, after_geometry,
                reused['field_conditions'], reused['core_sha256'])
            record['adoption_geometry_provenance_changes'] = changes
        adopted_metadata = proposed['__transformer_simulation']
        adopted_metadata['raw_field_after'] = copy.deepcopy(adopted_metadata.get('after'))
        adopted_metadata['after'] = copy.deepcopy(metrics)
        adopted_metadata['raw_field_comparison_path'] = adopted_metadata.get('comparison_path')
        adopted_metadata['comparison_path'] = str(directory / REPORT_NAME)
        adopted_metadata['raw_field_limits'] = copy.deepcopy(adopted_metadata.get('limits', []))
        adopted_metadata['limits'] = list(record['limits'])
        if adopted_metadata.get('rcd_factors'):
            adopted_metadata['rcd_factors'][-1] = 1 - margin['adopted_primary_short_H'] / margin['primary_self_H']
        record['adopted_config'] = copy.deepcopy(proposed)
        _write(directory / '02-已采用裕量矩阵.json', proposed)
        snapshot = directory / '03-电路设计计算快照.json'
        snapshot_id = design_run.save(snapshot)
        record['calculation'] = dict(snapshot_path=str(snapshot), snapshot_id=snapshot_id,
                                      endpoint_metrics=metrics,
                                      loop_errors=[dict(case=c['id'], error=c['loop_error'])
                                          for c in bundle['cases'] if c.get('loop_error')])
        if record['calculation']['loop_errors']:
            record['limits'].append('部分端点的解析环路未完成，报告并列呈现失败原因，不补造波特图。')
        finish()

        begin('spice', '使用同一矩阵执行电路瞬态、环路FRA和适用的交叉负载角点')
        from spice_runtime import compare_design
        spice_result = compare_design(design_run, directory / '电路仿真与设计对比.docx',
            cancelled=cancel, executable=executable,
            progress=lambda done, total, message: publish('spice', message))
        evidence_path = directory / '电路仿真证据.json'
        with ZipFile(spice_result['path']) as archive:
            evidence = strict_json(archive.read('comparison.json'))
        _write(evidence_path, evidence)
        record['circuit'] = dict(summary=spice_result, evidence_path=str(evidence_path), evidence=evidence)
        finish('partial' if spice_result.get('incomplete') else 'complete')
        record['status'] = 'partial' if spice_result.get('incomplete') or record['calculation']['loop_errors'] else 'complete'
    except Exception as exc:
        was_cancelled = isinstance(exc, CalculationCancelled)
        record['status'] = 'cancelled' if was_cancelled else 'failed'
        record['error'] = str(exc) or type(exc).__name__
        if active and active['status'] == 'running':
            finish('cancelled' if was_cancelled else 'failed', error=record['error'])
        for stage in record['stages']:
            if stage['status'] == 'pending' and stage['name'] != 'report':
                stage.update(status='skipped', error='前置阶段未完成')
    record['elapsed_s'] = time.monotonic()-started
    report_path = directory / REPORT_NAME
    try:
        # A cancellation stops solvers. It still gets an honest partial record.
        active = next(s for s in record['stages'] if s['name'] == 'report')
        active.update(status='running', started=time.monotonic())
        publish('report', '汇总已经完成的证据及未完成原因，生成同一份联合报告')
        from joint_simulation_report import write_joint_report
        record['report_path'] = str(report_path)
        rendered = copy.deepcopy(record)
        report_stage = next(s for s in rendered['stages'] if s['name'] == 'report')
        report_stage.pop('started', None)
        report_stage['status'] = 'complete'
        write_joint_report(report_path, rendered, design_run=design_run, spice_result=spice_result)
        finish()
    except Exception as exc:
        record.update(status='failed', report_error=str(exc))
        if active and active.get('status') == 'running':
            finish('failed', error=str(exc))
        _write(manifest, record)
        failure = RuntimeError(f'联合报告未完成，阶段记录已保存：{manifest}\n{exc}')
        failure.directory = str(directory)
        raise failure from exc
    record.update(elapsed_s=time.monotonic()-started, completed_at=datetime.now().astimezone().isoformat())
    _write(manifest, record)
    return dict(directory=str(directory), report_path=str(report_path), manifest_path=str(manifest),
                status=record['status'], proposed_config=proposed, input_id=record['input_id'],
                record=record, summary=record.get('error') or ('部分工况未通过，请查看报告' if record['status']=='partial' else '联合流程已完成'))
