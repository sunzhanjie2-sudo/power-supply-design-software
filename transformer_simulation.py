"""Personal calculator → frozen transformer geometry → field solve → endpoint review."""
import copy
from datetime import datetime
import hashlib
import math
from pathlib import Path
from uuid import uuid4

import numpy as np

from calculation_scheduler import CalculationCancelled
from config_io import UNITS
from design_engine.contracts import content_hash
from design_engine.service import calculate
from transformer_geometry import (export_geometry_package, json_bytes, read_geometry_package,
                                  resolve_geometry, strict_json)


RECORD = '__transformer_simulation'
LIMITS = [
    '场解采用零偏置、线性磁静态。实际工作频率下的磁导率、损耗、电容和饱和特性仍由原设计模型或实测确定。',
    '漏感按其余端口全部理想短路、折算到原边计算。单次网格、空气域和样机实测是三项独立的验证。',
]


def _sha(file):
    with Path(file).open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


def _input_id(config):
    return content_hash({k: v for k, v in config.items()
                         if k not in (RECORD, '__joint_simulation')})


def _calculate(config, cancelled):
    return calculate(config, analysis='endpoints', include_loop=False, include_efficiency=False,
                     include_cross_regulation=False, cancelled=cancelled)


def _endpoint_metrics(cases):
    rows = []
    for case in cases:
        if case.get('error') or not case.get('result'):
            raise ValueError(f"{case['id']} 复算失败：{case.get('error') or '缺少计算结果'}")
        result = case['result']
        op = result['op']
        clamp = op.get('clamp') or {}
        row = dict(case=case['id'], vin_V=float(case['voltage']), frequency_Hz=float(op['f_sw']),
                   switch_peak_A=float(op['I_sw_pk']), switch_stress_V=float(op['V_sw_max']),
                   duty=float(op['D']), efficiency=float(result['eta']),
                   primary_short_H=clamp.get('L_leak'), clamp_loss_W=result.get('P_rcd'))
        if not all(v is None or isinstance(v, str) or math.isfinite(v) for v in row.values()):
            raise ValueError(f"{case['id']} 出现无效工况值")
        rows.append(row)
    return rows


def _field_values(field, geometry):
    """Check the matrix itself, independent of record order and solver labels."""
    ports = field['port_order']
    if (field.get('schema') != 'transformer-coupling-tool.results.v1' or
            field.get('primary_port') != 'P' or len(ports) != len(set(ports)) or
            set(ports) != {w['id'] for w in geometry['windings']} or len(ports) < 2):
        raise ValueError('仿真结果的原边或端口集合与本次绕组不符')
    matrix = np.asarray(field['L_ports_H'], dtype=float)
    coeff = np.asarray(field['k_ports'], dtype=float)
    n = len(ports)
    if (matrix.shape != (n, n) or coeff.shape != (n, n) or not np.isfinite(matrix).all()
            or not np.isfinite(coeff).all() or not np.allclose(matrix, matrix.T, rtol=1e-8, atol=1e-15)
            or np.linalg.eigvalsh(matrix).min() <= 0):
        raise ValueError('场解电感矩阵尺寸、对称性或正定性校验失败')
    expected = matrix / np.sqrt(np.outer(matrix.diagonal(), matrix.diagonal()))
    if not np.allclose(expected, coeff, rtol=1e-8, atol=1e-10):
        raise ValueError('场解 k 与自感和互感不一致')
    p = ports.index('P')
    others = [i for i in range(n) if i != p]
    lp = float(matrix[p, p])
    ls = float(lp - matrix[p, others] @ np.linalg.solve(matrix[np.ix_(others, others)], matrix[others, p]))
    declared = field.get('ideal_all_secondary_short_Lp_H')
    if (not 0 < ls <= lp or declared is None or
            not math.isclose(ls, float(declared), rel_tol=1e-6, abs_tol=1e-15)):
        raise ValueError('场解的理想短路漏感与端口矩阵消元结果不一致')
    return dict(port_order=list(ports), L_ports_H=matrix.tolist(), k_ports=coeff.tolist(),
                primary_self_H=lp, primary_short_H=ls)


def _set_si(config, key, value):
    # Keep the display prefixes of GUI projects (including rcd_K vs SI K).
    entry = config.get(key)
    if isinstance(entry, dict) and 'v' in entry:
        config[key] = dict(entry, v=value / UNITS[entry.get('u', '')])
    else:
        config[key] = value


def _proposal(config, base, values, notes):
    q = copy.deepcopy(config)
    lp, ls = values['primary_self_H'], values['primary_short_H']
    order = values['port_order']
    k = np.asarray(values['k_ports'])
    if np.any(k < 0):
        raise ValueError('端口存在反向互感，请核对同名端和接线后再采用。带符号矩阵保留在场解报告。')
    forward = base['topology'] == 'ACF-FORWARD'
    _set_si(q, 'Lm_forward' if forward else 'L', lp)
    if base.get('coupling_config', {}).get('enabled'):
        ids = ['P'] + [f'OUT{i+1}' for i in range(len(base.get('outputs') or [1]))]
        if set(ids) != set(order):
            raise ValueError('当前功率级的耦合端口与场解端口不同，不能直接映射矩阵')
        indices = [order.index(name) for name in ids]
        q['coupling_config'] = dict(base['coupling_config'], k=k[np.ix_(indices, indices)].tolist())
        notes.append('已按功率端口顺序映射 kij。电路模型以原边自感和实际匝比构造副边自感；原始场解矩阵另存。')
    elif not forward:
        # Historical scalar in the RCD model is 1 - Lsc/Lp, not the pairwise k.
        key = 'rcd_K' if 'rcd_K' in q else 'K'
        _set_si(q, key, 1 - ls / lp)
        if key == 'rcd_K':
            q.pop('K', None)
        notes.append('RCD 漏感系数按 K = 1 − L短路 / L原边开路换算；QR 保留原谷底开通模型。')
        if len(order) > 2:
            notes.append('多端口在当前快速模型中仅采用原边总短路漏感；各路独立互感保留在场解表内。')
    else:
        notes.append('当前正激设计按提取的原边自感更新励磁支路，输出滤波电感独立。')
    return q


def _keep_physical_gap(proposal, project):
    """Changing the electrical L target must never remachine the solved CAD."""
    from transformer_geometry_contract import profile_template, validate_profile
    core = project['core']
    winding = proposal.setdefault('winding_config', {})
    model = winding.get('model_3d') or profile_template()
    winding['model_3d'] = model
    data = model.setdefault('core', {})
    if not data.get('gap_geometry'):
        kind = {'half_center_gap': 'center_leg_ground', 'half_spacer': 'spacer'}.get(core['mode'])
        if not core['total_gap_m']:
            kind = 'none'
        if not kind:
            raise ValueError('装配实体含气隙，请先在三维建模设置中记录实际的加工方式和间隙长度，再采用参数')
        data['gap_geometry'] = dict(type=kind, length_m=core['total_gap_m'], source=core['source'])
    data.setdefault('geometry_reference', None)
    if not data['geometry_reference']:
        data['geometry_reference'] = Path(core['path']).name
    data['geometry_sha256'] = core['sha256']
    validate_profile(model)


def complete_field_comparison(config, package, result_dir, directory, *, cancelled=None, project_file=None):
    """Resume a field run only after checking its complete manifest against this input."""
    from transformer_sim_runner import verify_field_result
    verified = verify_field_result(result_dir, package, cancelled=cancelled)
    return _compare_verified(config, package, verified, directory, cancelled=cancelled, project_file=project_file)


def _compare_verified(config, package, result_dir, directory, *, cancelled=None, project_file=None):
    from zipfile import ZipFile
    from transformer_sim_report import write_comparison

    directory = Path(directory).resolve()
    result_dir = Path(result_dir).resolve()
    geometry = read_geometry_package(package)
    with ZipFile(package) as archive:
        frozen = strict_json(archive.read('calculator-input.json'))
    if _input_id(config) != _input_id(frozen):
        raise ValueError('当前单元和场解导入包的电源配置不同，请重新运行')
    field = strict_json((result_dir / 'results.json').read_bytes())
    project = strict_json((result_dir / 'inputs/project.json').read_bytes())
    resolved = strict_json((result_dir / 'inputs/resolved-geometry.json').read_bytes())
    if resolved['source_geometry_sha256'] != geometry['source']['geometry_sha256']:
        raise ValueError('仿真源几何与本次几何不符')
    values = _field_values(field, geometry)
    before = _calculate(config, cancelled).runtime_bundle()
    baseline = _endpoint_metrics(before['cases'])
    topology = before['base_spec']['topology']
    notes = list(LIMITS)
    conditions = {k: project[k] for k in ('material', 'frame', 'core', 'solver', 'classification')}
    conditions['bobbin'] = geometry['bobbin']
    conditions['layers'] = [[s['winding_id'], s['turns']] for s in geometry['physical_sections']]
    conditions['windings'] = [[w['id'], w['turns']] for w in geometry['windings']]
    notes.extend(geometry.get('assumptions', []))
    if any(v.get('status') == 'assumed' for v in project.get('connections', {}).get('sections', {}).values()):
        notes.append('物理段方向与接线采用提取设置中的参考假设，需用实际绕线图核对。')
    proposal, after, problem = None, None, ''
    rcd_factors = None
    try:
        proposal = _proposal(config, before['base_spec'], values, notes)
        updated = _calculate(proposal, cancelled).runtime_bundle()
        after = _endpoint_metrics(updated['cases'])
        after_geometry, _ = resolve_geometry(updated['cases'], geometry['source']['engine_snapshot_id'],
                geometry['source']['input_sha256'], geometry['source']['design_id'], cancelled=cancelled)
        if geometry['source']['geometry_sha256'] != after_geometry['source']['geometry_sha256']:
            raise ValueError('复算会改变磁芯或绕组几何。请固定磁芯、匝数和线材后再仿真')
        _keep_physical_gap(proposal, project)
        if topology in ('FLYBACK', 'QR-FLYBACK') and not before['base_spec'].get('coupling_config', {}).get('enabled'):
            rcd_factors = [before['cases'][0]['p'].get('K', .95), updated['cases'][0]['p']['K']]
        notes.append('复算使用同一副磁芯和绕组；CAD 气隙见场解设置，新电感反推的等效气隙仅供对照。')
    except ValueError as exc:
        proposal, after, problem = None, None, str(exc)
        notes.append(problem)
    comparison_path = directory / '变压器仿真与设计复算.html'
    record = dict(schema='power-design.transformer-simulation.v1', topology=topology,
                  report_path=str(result_dir / 'report.html'), comparison_path=str(comparison_path),
                  directory=str(directory), input_sha256=geometry['source']['input_sha256'],
                  geometry_sha256=geometry['source']['geometry_sha256'], solver_version=field['tool_version'],
                  field_result_sha256=_sha(result_dir / 'results.json'), limits=notes,
                  validation={key: field.get(key, False) for key in
                              ('mesh_converged', 'air_domain_converged', 'measurement_validated')},
                  field=values, before=baseline, after=after,
                  rcd_factors=rcd_factors,
                  original_target_H=geometry['design_targets']['primary_self_inductance_H'],
                  model_conditions=conditions, project_file=str(Path(project_file).resolve()) if project_file else None,
                  adoption_error=problem)
    write_comparison(comparison_path, record)
    (directory / '闭环记录.json').write_bytes(json_bytes(record))
    if proposal is not None:
        proposal[RECORD] = copy.deepcopy(record)
    return dict(report_path=record['report_path'], comparison_path=str(comparison_path), directory=str(directory),
                proposed_config=proposal, notes=notes, input_id=_input_id(config), record=record)


def run_transformer_simulation(config, *, tool_root, project_file, output_directory,
                               cancelled=None, progress=None):
    from transformer_sim_runner import run_field_solver
    config = copy.deepcopy(config)
    base = Path(output_directory).expanduser().resolve()
    directory = base / ('变压器仿真-' + datetime.now().strftime('%Y%m%d-%H%M%S-') + uuid4().hex[:8])
    directory.mkdir(parents=True, exist_ok=False)
    status = directory / '任务状态.json'
    def stage(message):
        if cancelled and cancelled():
            raise CalculationCancelled()
        if progress:
            progress(message)
    try:
        stage('正在冻结当前工况并导出本次变压器几何')
        package = directory / '当前变压器.zip'
        exported = export_geometry_package(_calculate(config, cancelled), package, config, cancelled=cancelled)
        if not exported['ready']['cross_section']:
            raise ValueError('当前设计没有可用绕组截面。请在磁件页填写骨架净窗口宽高并核对层序。')
        stage('已冻结绕组，正在运行磁场求解')
        field_dir = run_field_solver(package, tool_root=tool_root, project_file=project_file,
                                     output_directory=directory, cancelled=cancelled, progress=progress)
        stage('场解已完成，正在校验矩阵并复算原设计的输入端点')
        # run_field_solver publishes only after checking every field and input hash.
        result = _compare_verified(config, package, field_dir, directory, cancelled=cancelled,
                                   project_file=project_file)
        stage('仿真报告和电源端点对比已生成')
        status.write_bytes(json_bytes(dict(state='complete' if result['proposed_config'] else 'review_only',
                                           comparison=result['comparison_path'])))
        return result
    except CalculationCancelled as exc:
        status.write_bytes(json_bytes(dict(state='cancelled')))
        exc.directory = str(directory)
        raise
    except Exception as exc:
        status.write_bytes(json_bytes(dict(state='failed', error=str(exc))))
        failure = ValueError(f'{exc}\n本次任务目录：{directory}')
        failure.directory = str(directory)
        raise failure from exc


def apply_transformer_simulation(current_config, result):
    if _input_id(current_config) != result['input_id']:
        raise ValueError('场解启动后该单元的设计已变化，请以当前参数重新仿真')
    if result.get('proposed_config') is None:
        raise ValueError('该结果只供评审：' + result['record']['adoption_error'])
    return copy.deepcopy(result['proposed_config'])
