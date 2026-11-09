"""Strictly audited reuse of a zero-bias field solve after load-only edits.

The original ZIP, solver inputs and artifact manifest are never rewritten.
This is a circuit-condition rebinding, not a field result for a new source ZIP.
"""
from __future__ import annotations

import copy
import math
from pathlib import Path
from zipfile import ZipFile

from calculation_scheduler import CalculationCancelled
from design_engine.service import validate_spec
from transformer_geometry import (export_geometry_package, json_bytes, read_geometry_package,
                                  resolve_geometry, strict_json)
from transformer_sim_runner import bind_solver_project, verify_field_result
from transformer_simulation import (_calculate, _compare_verified, _endpoint_metrics,
                                    _input_id, _keep_physical_gap, _proposal, _sha, RECORD)


_META = ('geometry_reference', 'geometry_sha256', 'material_reference', 'gap_geometry')
_GEOMETRY = ('schema', 'units', 'frame', 'core', 'bobbin', 'bbox_convention', 'windings',
             'physical_sections', 'connections', 'connection_matrix', 'terminals', 'leads')


def _diff(before, current, path=()):
    if isinstance(before, dict) and isinstance(current, dict):
        rows = []
        for key in sorted(set(before) | set(current)):
            if key not in before or key not in current:
                rows.append(dict(path=list(path + (key,)), before=before.get(key), current=current.get(key)))
            else:
                rows.extend(_diff(before[key], current[key], path + (key,)))
        return rows
    if isinstance(before, (list, tuple)) and isinstance(current, (list, tuple)):
        if len(before) != len(current):
            return [dict(path=list(path + ('length',)), before=len(before), current=len(current))]
        return [d for i, (a, b) in enumerate(zip(before, current)) for d in _diff(a, b, path + (i,))]
    return [] if before == current else [dict(path=list(path), before=before, current=current)]


def _validated(config):
    checked = validate_spec(config)
    if not checked['ok']:
        raise ValueError('负载重绑定输入无效：' + '; '.join(i['message'] for i in checked['issues']))
    return checked['spec']


def _load_changes(before, current):
    changes, metadata = [], []
    for row in _diff(_validated(before), _validated(current)):
        path = row['path']
        if (len(path) == 1 and path[0] in ('P_out', 'P_out_min') or
                len(path) == 3 and path[0] == 'outputs' and isinstance(path[1], int)
                and path[2] in ('P_out', 'P_out_min')):
            changes.append(row)
        elif path[:3] == ['winding_config', 'model_3d', 'core'] and len(path) >= 4 and path[3] in _META:
            metadata.append(row)
        else:
            raise ValueError('仅允许改变输出负载；发现非负载差异：' + '.'.join(map(str, path)))
    return changes, metadata


def _zero_bias(project):
    material = project.get('material') or {}
    for key in ('frequency_Hz', 'bias_current_A'):
        value = material.get(key)
        if isinstance(value, bool) or not isinstance(value, (float, int)) or not math.isfinite(value) or value != 0:
            raise ValueError('只允许复用已明确记录0 Hz、0 A的线性零偏置场解')
    if not all(key in material for key in ('name', 'relative_permeability', 'temperature_C')):
        raise ValueError('旧场解缺少材料、磁导率或温度，不能重绑定')


def _geometry_audit(before, current, project, staged_core_sha):
    """Allow only independently proven provenance additions, never dimensions."""
    _zero_bias(project)
    if project['core']['sha256'] != staged_core_sha:
        raise ValueError('原磁芯实体哈希与已校验CAD不一致')
    for geometry in (before, current):
        core = geometry['core']
        target = geometry.get('design_targets', {}).get('air_gap') or {}
        if (core.get('calculator_material', '').casefold() != project['material']['name'].casefold()
                or target.get('mu_r') != project['material']['relative_permeability']):
            raise ValueError('当前磁材或磁导率与已验证场解不同')
        if core.get('geometry_sha256') not in (None, staged_core_sha):
            raise ValueError('当前磁芯实体SHA与已验证CAD不同')
        physical = core.get('gap_geometry') or {}
        length = physical.get('length_m', target.get('gap_m'))
        if length is None or not math.isclose(length, project['core']['total_gap_m'], rel_tol=1e-10, abs_tol=1e-14):
            raise ValueError('当前实际/设计气隙与已验证场解不同')
        if physical:
            expected = {'half_center_gap': 'center_leg_ground', 'half_spacer': 'spacer'}.get(project['core']['mode'])
            if not project['core']['total_gap_m']:
                expected = 'none'
            if expected is None:
                expected = (before['core'].get('gap_geometry') or {}).get('type')
            if expected is None or physical.get('type') != expected:
                raise ValueError('当前气隙加工方式未与已验证CAD对应')
    left, right = ({k: copy.deepcopy(g[k]) for k in _GEOMETRY} for g in (before, current))
    provenance = []
    for key in _META:
        if left['core'].get(key) != right['core'].get(key):
            provenance.append(dict(field='core.'+key, before=left['core'].get(key), current=right['core'].get(key)))
        left['core'].pop(key, None)
        right['core'].pop(key, None)
    changed = _diff(left, right)
    if changed:
        raise ValueError('场解几何/接线已有变化，不能只重绑定负载：' + '.'.join(map(str, changed[0]['path'])))
    return provenance


def _recalculate_comparison(config, package, result_dir, directory, old_config, old_package,
                            *, cancelled, project_file):
    """Metadata-only geometry differences use a separate explicit bridge.

    The old strict path is checked against its own unchanged ZIP; the new
    circuit is recomputed with shared helpers after the full geometry audit.
    """
    from transformer_sim_report import write_comparison
    raw = directory / '原场解重新校验'
    raw.mkdir(exist_ok=False)
    previous = _compare_verified(old_config, old_package, result_dir, raw,
                                 cancelled=cancelled, project_file=project_file)
    geometry = read_geometry_package(package)
    record = copy.deepcopy(previous['record'])
    before = _calculate(config, cancelled).runtime_bundle()
    notes = list(record['limits'])
    proposed = _proposal(config, before['base_spec'], record['field'], notes)
    after = _calculate(proposed, cancelled).runtime_bundle()
    later, _ = resolve_geometry(after['cases'], geometry['source']['engine_snapshot_id'],
        geometry['source']['input_sha256'], geometry['source']['design_id'], cancelled=cancelled)
    if later['source']['geometry_sha256'] != geometry['source']['geometry_sha256']:
        raise ValueError('重绑定后的复算改变了当前实际几何，不能采用原场解')
    project = strict_json((result_dir/'inputs/project.json').read_bytes())
    _keep_physical_gap(proposed, project)
    record.update(directory=str(directory), comparison_path=str(directory/'变压器仿真与设计复算.html'),
        input_sha256=geometry['source']['input_sha256'], geometry_sha256=geometry['source']['geometry_sha256'],
        before=_endpoint_metrics(before['cases']), after=_endpoint_metrics(after['cases']), limits=notes,
        adoption_error='', raw_field_comparison_path=previous['comparison_path'])
    return dict(report_path=record['report_path'], comparison_path=record['comparison_path'],
        directory=str(directory), proposed_config=proposed, notes=notes, input_id=_input_id(config), record=record)


def complete_load_rebound_field_comparison(config, original_package, result_dir, directory,
                                         *, cancelled=None, project_file=None):
    """Reuse verified static fields ONLY for audited output-power changes.

    Every original artifact remains bound to ``original_package``. The new
    calculator ZIP and source identity are published separately with an audit.
    """
    def check():
        if cancelled and cancelled():
            raise CalculationCancelled()
    check()
    config = copy.deepcopy(config)
    original_package = Path(original_package).resolve(strict=True)
    result_dir = verify_field_result(result_dir, original_package, cancelled=cancelled)
    with ZipFile(original_package) as archive:
        old_config = strict_json(archive.read('calculator-input.json'))
    load_changes, metadata_changes = _load_changes(old_config, config)
    old_geometry = read_geometry_package(original_package)
    project = strict_json((result_dir/'inputs/project.json').read_bytes())
    _zero_bias(project)
    directory = Path(directory).resolve()
    directory.mkdir(parents=True, exist_ok=True)
    package = directory/'当前变压器.zip'
    if package == original_package or package.exists():
        raise ValueError('负载重绑定必须使用新任务目录，不能覆盖原始几何包')
    export_geometry_package(_calculate(config, cancelled), package, config, cancelled=cancelled)
    check()
    geometry = read_geometry_package(package)
    core_path = result_dir/('inputs/core'+Path(project['core']['path']).suffix.lower())
    core_sha = _sha(core_path)
    geometry_metadata = _geometry_audit(old_geometry, geometry, project, core_sha)
    bound = None
    if project_file is not None:
        bound = bind_solver_project(package, project_file, directory)
        for key in ('material', 'frame', 'core', 'solver', 'classification'):
            if bound.get(key) != project.get(key):
                raise ValueError('当前提取设置改变了原场解条件：'+key)
    audit = dict(schema='power-design.field-load-rebinding.v1', field_solver_rerun=False,
        original_package_path=str(original_package), original_package_sha256=_sha(original_package),
        original_field_directory=str(result_dir), original_result_sha256=_sha(result_dir/'results.json'),
        new_package_path=str(package), new_package_sha256=_sha(package),
        original_input_id=_input_id(old_config), new_input_id=_input_id(config),
        original_geometry_sha256=old_geometry['source']['geometry_sha256'],
        new_geometry_sha256=geometry['source']['geometry_sha256'], load_changes=load_changes,
        input_provenance_changes=metadata_changes, geometry_provenance_changes=geometry_metadata,
        physical_geometry_and_connections_identical=True,
        original_artifact_manifest_verified=True, original_artifacts_rewritten=False,
        core_sha256=core_sha,
        field_conditions={key:copy.deepcopy(project.get(key)) for key in
                          ('material','frame','core','solver','classification')},
        selected_project_file=str(Path(project_file).resolve()) if project_file else None,
        selected_project_file_sha256=_sha(project_file) if project_file else None,
        condition_policy='Preserve original linear 0 Hz, 0 A field conditions; reuse only for output power edits.')
    (directory/'场解负载重绑定审计.json').write_bytes(json_bytes(audit))
    check()
    if geometry['source']['geometry_sha256'] == old_geometry['source']['geometry_sha256']:
        result = _compare_verified(config, package, result_dir, directory, cancelled=cancelled, project_file=project_file)
    else:
        result = _recalculate_comparison(config, package, result_dir, directory, old_config,
            original_package, cancelled=cancelled, project_file=project_file)
    record = result['record']
    record['reused_field_provenance'] = audit
    note = ('场解负载重绑定：原场解仍绑定原始ZIP（'+audit['original_package_sha256']+'），本次生成新电路输入ZIP（'
            +audit['new_package_sha256']+'）。完整几何/接线和线性零偏置条件校验一致，只改变输出负载；没有重新运行磁场求解。')
    record['limits'].append(note)
    result['notes'] = record['limits']
    result['input_id'] = _input_id(config)
    if result.get('proposed_config') is not None:
        result['proposed_config'][RECORD] = copy.deepcopy(record)
    from transformer_sim_report import write_comparison
    write_comparison(Path(result['comparison_path']), record)
    (directory/'闭环记录.json').write_bytes(json_bytes(record))
    return result
