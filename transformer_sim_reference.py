"""Prepare a reviewable local extraction profile from an existing core project."""
from copy import deepcopy
from pathlib import Path
from uuid import uuid4
import math

from transformer_geometry import (export_geometry_package, json_bytes, read_geometry_package,
                                  resolve_geometry, strict_json)
from transformer_geometry_contract import profile_template
from transformer_sim_runner import bind_solver_project
from transformer_simulation import _calculate, _sha


def _connections(profile, geometry):
    if geometry['connection_matrix']['values'] is not None:
        return '保留当前工程接线'
    if (profile.get('terminals') or profile.get('leads') or
            any(s.get('start_node') or s.get('end_node') or s.get('dot_node') or s.get('direction')
                for s in profile.get('sections', {}).values()) or
            any(p.get('section_order') or p.get('connection') or p.get('dot_node') or p.get('other_node')
                for p in profile.get('ports', {}).values())):
        raise ValueError('当前接线已部分填写，请在三维建模设置中补全后再准备；自动参考接线仅用于空白接线。')
    source = '名义绕制假设：从 +Z 观察各段逆时针，电流流入起点同名端，同一绕组各段按层序串联相加，中间节点不外接。'
    sections, ports, terminals = {}, {}, []
    turns = {s['section_id']: s['turns'] for s in geometry['physical_sections']}
    for winding in geometry['windings']:
        label, ids = winding['id'], winding['section_ids']
        nodes = [label + '_D'] + [f'{label}_J{i}' for i in range(1, len(ids))] + [label + '_R']
        for i, sid in enumerate(ids):
            sections[sid] = dict(winding_id=label, turns=turns[sid], start_node=nodes[i], end_node=nodes[i+1],
                                 dot_node=nodes[i], direction='ccw', status='assumed', source=source)
        ports[label] = dict(dot_node=nodes[0], other_node=nodes[-1], connection='series',
                            section_order=ids, status='assumed', source=source)
        for n in nodes[1:-1]:
            terminals.append(dict(node=n, pin='REF_' + n, position_xyz_m=None, external_connection='none',
                                  net=None, status='assumed', source=source))
    profile.update(sections=sections, ports=ports, terminals=terminals)
    return source


def prepare_reference(config, *, project_file, output_directory, cancelled=None):
    template = Path(project_file).resolve(strict=True)
    settings = strict_json(template.read_bytes())
    if settings.get('schema') != 'transformer-coupling-tool.project.v1':
        raise ValueError('请选择磁芯参考工程的提取设置 JSON')
    reference_zip = (template.parent / settings['package_path']).resolve(strict=True)
    if _sha(reference_zip) != settings['package_sha256']:
        raise ValueError('磁芯参考工程的原几何包与模板哈希不同')
    reference = read_geometry_package(reference_zip)
    candidate = deepcopy(config)
    winding = candidate.setdefault('winding_config', {})
    profile = winding.get('model_3d') or profile_template()
    winding['model_3d'] = profile
    for key, dimension in [('window_width', 'axial_window_m'), ('window_height', 'radial_window_m')]:
        if not winding.get(key):
            value = reference['bobbin'].get(dimension)
            if not value or value <= 0:
                raise ValueError('同型号参考工程没有净窗口尺寸，请在当前磁件页输入窗口宽和高')
            winding[key] = value
    bobbin = profile.setdefault('bobbin', {})
    if bobbin.get('winding_route_type') not in (None, 'circular'):
        raise ValueError('当前提取工具只支持圆形匝路径，已有轨迹需由设计者核对')
    if not bobbin.get('winding_route_type') and reference['bobbin'].get('winding_route_type') not in ('circular', None):
        raise ValueError('模板骨架并非圆形匝路径')
    frame = profile.setdefault('frame', {})
    for key, ref in [('r0_m_if_circular', 'r0_m'), ('z0_m', 'z0_m')]:
        if frame.get(key) is None:
            frame[key] = settings['frame'][ref]
        if frame[key] is None:
            raise ValueError('参考工具设置中缺少骨架基准 ' + ref)
    if not bobbin.get('winding_route_type') or bobbin.get('status') in (None, 'unconfirmed'):
        bobbin.update(winding_route_type='circular', status='assumed', source='同型号参考工程名义骨架：' + template.name)
    # Resolve the current windings, including current wire count and every user-positioned turn.
    first = _calculate(candidate, cancelled)
    cases = first.runtime_bundle()['cases']
    g, _ = resolve_geometry(cases, '0'*64, '0'*64, 'T1', profile, cancelled=cancelled)
    if (g['core']['calculator_core'] != reference['core']['calculator_core'] or
            settings['core'].get('calculator_core_model', g['core']['calculator_core']) != g['core']['calculator_core']):
        raise ValueError('当前计算的磁芯型号与参考工程不同，请选择同型号磁芯')
    if not g['ready']['cross_section'] or not g['checks']['two_dimensional_fit']:
        raise ValueError('当前线材、层序与净窗口未通过可绕制评估，请先调整磁件设计')
    note = _connections(profile, g)
    target = g['design_targets']['air_gap']
    core = settings['core']
    physical = (profile.get('core') or {}).get('gap_geometry') or {}
    gap = physical.get('length_m', target.get('gap_m'))
    if gap is None or target['mu_r'] is None:
        raise ValueError('需要当前磁件的磁导率和可用的气隙设计')
    if core['mode'] == 'assembled' and not math.isclose(core['total_gap_m'], gap, abs_tol=1e-11):
        raise ValueError('参考 STEP 为已装配实体，现有气隙与本设计不同。请选择可磨隙的半芯或相符的装配模型')
    core.update(path=str((template.parent / core['path']).resolve(strict=True)), total_gap_m=gap,
                calculator_core_model=g['core']['calculator_core'],
                source=physical.get('source') or '参考模板磁芯实体，按当前电源磁路初算的等效总气隙进行名义装配。')
    material = settings['material']
    material.pop('source_file', None)
    material.update(name=g['core']['calculator_material'], relative_permeability=target['mu_r'],
                    source=target.get('material_source') if target.get('mu_r_source') != '用户指定相对磁导率' and target.get('material_source')
                    else '采用当前电源设计的相对磁导率；按零偏置常数建模。')
    settings.update(frame=dict(z0_m=frame['z0_m'], r0_m=frame['r0_m_if_circular']),
                    connections=profile, classification='reference_assumptions', assumptions=[note, core['source']])
    if settings['solver'].get('elmer_home'):
        settings['solver']['elmer_home'] = str((template.parent / settings['solver']['elmer_home']).resolve())
    directory = Path(output_directory).resolve() / ('参考提取设置-' + uuid4().hex[:10])
    directory.mkdir(parents=True, exist_ok=False)
    package = directory / '参考绕制输入.zip'
    export_geometry_package(_calculate(candidate, cancelled), package, candidate, cancelled=cancelled)
    settings.update(package_path=package.name, package_sha256=_sha(package), output_root='.')
    new_path = directory / '提取设置.json'
    new_path.write_bytes(json_bytes(settings))
    bind_solver_project(package, new_path, directory)
    layers = ' → '.join(s['winding_id'] + ' ' + str(s['turns']) + ' 匝' for s in g['physical_sections'])
    summary = (f"{g['core']['calculator_core']} · {material['name']} · μr={target['mu_r']:g}\n"
               f"净窗口 {winding['window_width']*1e3:.3g} × {winding['window_height']*1e3:.3g} mm，"
               f"r0={frame['r0_m_if_circular']*1e3:g} mm，z0={frame['z0_m']*1e3:g} mm。\n"
               f"层序：{layers}\n总气隙 {gap*1e3:.6g} mm；{core['source']}\n{note}")
    return dict(config=candidate, project_file=str(new_path), summary=summary)
