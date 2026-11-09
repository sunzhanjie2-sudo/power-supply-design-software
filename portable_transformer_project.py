"""Build a self-contained FEM input from the current design and a local CAD file.

No earlier extractor project, source ZIP or external tool installation is needed.
This module prepares and validates inputs only; CAD assembly/interference and the
field solution remain independent checks in the bundled extractor runtime.
"""
from __future__ import annotations

from copy import deepcopy
import math
from pathlib import Path
from uuid import uuid4

from calculation_scheduler import CalculationCancelled
from transformer_geometry import (export_geometry_package, json_bytes, read_geometry_package,
                                  resolve_geometry)
from transformer_geometry_contract import profile_template
from transformer_sim_reference import _connections
from transformer_sim_runner import _sha, bind_solver_project
from transformer_simulation import _calculate


_MODES = {'assembled', 'half_center_gap', 'half_spacer'}


def _number(value, label, *, positive=False, nonnegative=False):
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
        raise ValueError(label + '需要有限数值')
    if positive and value <= 0:
        raise ValueError(label + '必须大于0')
    if nonnegative and value < 0:
        raise ValueError(label + '不能小于0')
    return float(value)


def _vector(value, label):
    if not isinstance(value, (list, tuple)) or len(value) != 3:
        raise ValueError(label + '需要XYZ三个数值')
    return [_number(v, label) for v in value]


def _environment(value):
    """Validate local selections before doing any design calculation or copying."""
    if not isinstance(value, dict):
        raise ValueError('请先配置本机电磁仿真环境与磁芯模型')
    env = deepcopy(value)
    if env.get('core_mode') not in _MODES:
        raise ValueError('请选择磁芯装配方式：已装配实体、单半芯中柱磨隙或单半芯整体垫片')
    if env.get('brep_unit') not in ('mm', 'm'):
        raise ValueError('磁芯BREP单位需要mm或m；STEP按文件内声明单位读取')
    for key, label in (('core_path', '磁芯实体'), ('elmer_home', 'Elmer安装目录')):
        raw = env.get(key)
        if not isinstance(raw, str) or not raw.strip():
            raise ValueError('请选择' + label)
        try:
            env[key] = str(Path(raw).expanduser().resolve(strict=True))
        except (OSError, ValueError):
            raise ValueError(label + '不存在，请在本机重新选择') from None
    core = Path(env['core_path'])
    if not core.is_file() or core.suffix.lower() not in ('.step', '.stp', '.brep'):
        raise ValueError('请选择封闭实体STEP/STP/BREP；图片或STL不能替代磁芯实体')
    if core.suffix.lower() in ('.step', '.stp'):
        with core.open('rb') as stream:
            header = stream.read(4096)
        if b'ISO-10303-21' not in header.upper():
            raise ValueError('磁芯文件不是可识别的STEP文本，请勿只修改文件后缀')
    home = Path(env['elmer_home'])
    if not home.is_dir() or not all((home / 'bin' / name).is_file()
            for name in ('ElmerSolver.exe', 'ElmerGrid.exe')):
        raise ValueError('Elmer目录须同时包含bin/ElmerSolver.exe及bin/ElmerGrid.exe')
    env['translation_mm'] = _vector(env.get('translation_mm'), '磁芯平移/mm')
    env['rotation_deg'] = _vector(env.get('rotation_deg'), '磁芯转角/°')
    env['gap_center_z_m'] = _number(env.get('gap_center_z_m'), '气隙中心Z/m')
    if env['core_mode'] != 'assembled' and abs(env['gap_center_z_m']) > 1e-10:
        raise ValueError('半芯模式要求拼合面和气隙中心Z=0、半芯位于Z<0；请先设置姿态')
    if env['core_mode'] == 'half_center_gap':
        env['center_leg_radius_m'] = _number(env.get('center_leg_radius_m'), '中柱半径/m', positive=True)
    elif env.get('center_leg_radius_m') is not None:
        env['center_leg_radius_m'] = _number(env['center_leg_radius_m'], '中柱半径/m', positive=True)
    if env.get('mesh_profile', 'standard') not in ('coarse', 'standard', 'fine'):
        raise ValueError('网格档位需要coarse、standard或fine')
    env['air_radius_m'] = _number(env.get('air_radius_m', .05), '空气域半径/m', positive=True)
    env['timeout_s'] = _number(env.get('timeout_s', 1200), '场求解超时/s', positive=True)
    if not isinstance(env.get('core_source'), str) or not env['core_source'].strip():
        raise ValueError('请填写磁芯模型/装配依据，或明确注明参考假设')
    return env


def _frame(profile, env):
    frame = profile.setdefault('frame', {})
    for key, name, label in (('r0_m_if_circular', 'r0_m', '线圈内侧基准半径r0'),
                             ('z0_m', 'z0_m', '线圈轴向起点z0')):
        existing, chosen = frame.get(key), env.get(name)
        if existing is not None:
            _number(existing, label, positive=name == 'r0_m')
            if chosen is not None and not math.isclose(
                    existing, _number(chosen, label, positive=name == 'r0_m'),
                    rel_tol=1e-10, abs_tol=1e-12):
                raise ValueError(label + '与当前工程不一致；请修改当前建模坐标或清空环境覆盖值')
        elif chosen is None:
            raise ValueError('当前工程缺少' + label + '，请按骨架/CAD坐标填写，不能自动猜测')
        else:
            frame[key] = _number(chosen, label, positive=name == 'r0_m')


def _copy_verified(source, target, expected_sha, cancel):
    with source.open('rb') as reader, target.open('xb') as writer:
        for block in iter(lambda: reader.read(4 * 1024**2), b''):
            if cancel():
                raise CalculationCancelled()
            writer.write(block)
    if _sha(target, cancel) != expected_sha or _sha(source, cancel) != expected_sha:
        raise ValueError('磁芯文件在输入准备期间发生变化，请重新选择')


def prepare_portable_reference(config, *, environment, output_directory, cancelled=None):
    """Return ``{config, project_file, summary}`` without mutating the caller.

    The returned settings JSON uses relative source-ZIP and CAD paths, so its
    entire directory can be moved. Elmer remains a machine-local selection.
    Existing window, layer IDs, turn locations, connections and wire evidence
    are authoritative. Only fully blank connections may receive explicit
    series-additive reference assumptions.
    """
    cancel = cancelled or (lambda: False)
    if cancel():
        raise CalculationCancelled()
    env = _environment(environment)
    candidate = deepcopy(config)
    winding = candidate.setdefault('winding_config', {})
    for key, label in (('window_width', '骨架净窗口宽度'), ('window_height', '骨架净窗口高度')):
        if not winding.get(key):
            raise ValueError('当前设计缺少' + label + '，请先在磁件页输入；仅凭磁芯STEP不能推定骨架净窗口')
        _number(winding[key], label, positive=True)
    profile = deepcopy(winding.get('model_3d') or profile_template())
    winding['model_3d'] = profile
    _frame(profile, env)
    bobbin = profile.setdefault('bobbin', {})
    if bobbin.get('winding_route_type') not in (None, 'circular'):
        raise ValueError('内置提取首版支持圆形等效匝；不能将已有非圆形路径静默改成圆形')
    if not bobbin.get('winding_route_type') or bobbin.get('status') in (None, 'unconfirmed'):
        bobbin.update(winding_route_type='circular', status='assumed',
                      source='当前窗口与用户指定r0/z0的圆形等效匝参考模型')
    core = profile.setdefault('core', {})
    source = Path(env['core_path'])
    source_sha = _sha(source, cancel)
    if core.get('geometry_sha256') and core['geometry_sha256'].lower() != source_sha:
        raise ValueError('所选磁芯实体与当前工程已冻结CAD的SHA-256不符，请先复核并更新工程模型')
    run = _calculate(candidate, cancel)
    geometry, _ = resolve_geometry(run.runtime_bundle()['cases'], '0' * 64, '0' * 64,
                                   'T1', profile, cancelled=cancel)
    if not geometry['ready']['cross_section'] or not geometry['checks']['two_dimensional_fit']:
        raise ValueError('当前线材、层序、手动匝位置与净窗口未通过可绕制评估，请先调整磁件设计')
    connection_note = _connections(profile, geometry)
    # Re-resolve: partial, tapped or parallel connections must not be silently
    # replaced by a simple series circuit just because some fields exist.
    geometry, _ = resolve_geometry(run.runtime_bundle()['cases'], '0' * 64, '0' * 64,
                                   'T1', profile, cancelled=cancel)
    if (geometry['connection_matrix']['values'] is None or
            any(p['turns_match_calculator'] is not True for p in geometry['connections'])):
        raise ValueError('当前绕组接线不完整或含未支持的外接抽头/并联约束，请在建模设置中补全')
    target = geometry['design_targets'].get('air_gap') or {}
    physical = core.get('gap_geometry') or {}
    gap = physical.get('length_m', target.get('gap_m'))
    gap = _number(gap, '当前设计总气隙/m', nonnegative=True)
    mu = _number(target.get('mu_r'), '当前设计相对磁导率', positive=True)
    if mu < 1:
        raise ValueError('当前线性铁氧体磁导率不能小于1')
    expected_type = {'half_center_gap': 'center_leg_ground', 'half_spacer': 'spacer'}.get(env['core_mode'])
    if gap and expected_type and physical.get('type') not in (None, expected_type):
        raise ValueError('所选半芯气隙加工方式与当前设计指定方式不符')
    if physical.get('center_xyz_m') is not None:
        center = physical['center_xyz_m']
        if (not math.isclose(center[0], 0., abs_tol=1e-12) or
                not math.isclose(center[1], 0., abs_tol=1e-12) or
                not math.isclose(center[2], env['gap_center_z_m'], rel_tol=1e-10, abs_tol=1e-12)):
            raise ValueError('所选气隙中心与当前工程指定的气隙位置不符')
    material_source = target.get('material_source') or '当前电源设计指定的线性相对磁导率，非偏磁测量'
    assumptions = list(profile.get('assumptions') or [])
    if connection_note != '保留当前工程接线':
        assumptions.append(connection_note)
    if not physical:
        physical = dict(type='none' if gap == 0 else expected_type or 'center_leg_ground',
                        length_m=gap, center_xyz_m=[0., 0., env['gap_center_z_m']],
                        source='当前电源磁路初算的等效总气隙；已装配CAD须在实体检查中独立核对，未按目标电感拟合')
        core['gap_geometry'] = physical
        assumptions.append(physical['source'])
    # Preserve intentional winding placement. Only the selected local CAD
    # reference and missing model provenance are added to the exported copy.
    local_cad = 'models/core' + source.suffix.lower()
    core.update(geometry_reference=local_cad, geometry_sha256=source_sha)
    if not core.get('material_reference'):
        core['material_reference'] = material_source
    assumptions.extend(['选定CAD仅通过文件与哈希检查；半芯姿态、实体气隙、空气域及线圈干涉由后续CAD检查独立判定。',
                        '采用均匀电流的圆形闭合等效匝；未包含螺旋跨层线、引线、涡流和非线性偏磁。'])
    profile['assumptions'] = list(dict.fromkeys(assumptions))
    directory = Path(output_directory).expanduser().resolve() / ('自动电磁输入-' + uuid4().hex[:10])
    directory.mkdir(parents=True, exist_ok=False)
    (directory / 'models').mkdir()
    _copy_verified(source, directory / local_cad, source_sha, cancel)
    package = directory / '当前绕制输入.zip'
    export_geometry_package(_calculate(candidate, cancel), package, candidate, cancelled=cancel)
    final_geometry = read_geometry_package(package)
    project = dict(schema='transformer-coupling-tool.project.v1', name='T1',
        package_path=package.name, package_sha256=_sha(package, cancel), primary_port='P',
        core=dict(path=local_cad, sha256=source_sha, calculator_core_model=final_geometry['core']['calculator_core'],
                  mode=env['core_mode'], brep_unit=env['brep_unit'], translation_mm=env['translation_mm'],
                  rotation_deg=env['rotation_deg'], total_gap_m=gap,
                  center_leg_radius_m=env.get('center_leg_radius_m'), gap_center_z_m=env['gap_center_z_m'],
                  source=env['core_source'].strip()),
        frame=dict(r0_m=profile['frame']['r0_m_if_circular'], z0_m=profile['frame']['z0_m']),
        material=dict(name=final_geometry['core']['calculator_material'], relative_permeability=mu,
                      temperature_C=25., source=material_source, frequency_Hz=0., bias_current_A=0.),
        connections=deepcopy(profile), classification='reference_assumptions',
        assumptions=profile['assumptions'],
        solver=dict(elmer_home=env['elmer_home'], mesh_profile=env.get('mesh_profile', 'standard'),
                    air_radius_m=env['air_radius_m'], timeout_s=env['timeout_s']), output_root='.')
    path = directory / '自动提取设置.json'
    path.write_bytes(json_bytes(project))
    # Use the same contract as manual/legacy projects. This does not call CAD,
    # mesh or Elmer and must not be described as field-solution validation.
    bind_solver_project(package, path, directory)
    summary = (f"已从当前设计生成可迁移输入：{project['core']['calculator_core_model']} · "
               f"{project['material']['name']} · μr={mu:g}\n"
               f"净窗口 {winding['window_width']*1e3:g}×{winding['window_height']*1e3:g} mm；"
               f"r0={project['frame']['r0_m']*1e3:g} mm，z0={project['frame']['z0_m']*1e3:g} mm\n"
               f"总气隙 {gap*1e3:g} mm；{connection_note}\n"
               'CAD与绕制包已复制到同一输入目录；后续仍须通过实体装配/干涉检查和场求解。')
    return dict(config=candidate, project_file=str(path), summary=summary)
