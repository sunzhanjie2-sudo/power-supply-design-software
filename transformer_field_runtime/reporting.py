"""Render standalone reports from solved fields. All user-supplied HTML text is escaped."""
from __future__ import annotations
import base64
from html import escape
from pathlib import Path
import re
from string import Template

from . import __version__
from .field_figures import plots
from .presentation import CLASSIFICATIONS, CORE_MODES, key_readings, port_readings, winding_colors
from .storage import now, read


def h(value):
    return escape(str(value), quote=True)


def md(value):
    plain = h(value).replace('\n', ' ')
    return re.sub(r'([\\|\[\]*_`])', r'\\\1', plain)


def html_table(headers, rows, *, css='', row_headers=None, cell_style=None):
    # cell_style returns only internal CSS (never text from the input package).
    head = ''.join(f'<th scope="col">{h(item)}</th>' for item in headers)
    body = []
    for i, row in enumerate(rows):
        label = row_headers[i] if row_headers is not None else h(row[0])
        cells = [f'<th scope="row">{label}</th>']
        for j, value in enumerate(row[1:]):
            attrs = cell_style(i, j) if cell_style else ''
            cells.append(f'<td{attrs}>{h(value)}</td>')
        body.append('<tr>'+''.join(cells)+'</tr>')
    return f'<table class="{css}"><thead><tr>{head}</tr></thead><tbody>'+''.join(body)+'</tbody></table>'


def md_table(headers, rows):
    return '\n'.join('| '+' | '.join(map(md, row))+' |'
                     for row in [headers, ['---', *['---:']*(len(headers)-1)], *rows])


def facts(items):
    return ''.join(f'<div class="fact"><span>{h(key)}</span><b>{h(value)}</b></div>' for key, value in items)


def md_facts(items):
    return '\n'.join(f'- **{md(key)}**　{md(value)}' for key, value in items)


def data_image(file):
    return 'data:image/png;base64,'+base64.b64encode(file.read_bytes()).decode('ascii')


def evidence(config, g, source, report, mesh, quality):
    core, material = config['core'], config['material']
    gap_mm = core['total_gap_m']*1000
    short_error = report['ideal_short_energy_relative_error']
    overlaps = mesh.get('core_winding_overlap_mm3', [])
    checks = [
        ('求解网格', f"{mesh['nodes']:,} 个节点 · {mesh['tetrahedra']:,} 个四面体"),
        ('网格质量', f"{quality['nonpositive_tetrahedra']} 个非正体积单元 · 最小 SICN {quality['minSICN']:.4g}"),
        ('磁芯与线束重叠体积', f'{max(overlaps):.4g} mm³（最大单束）' if overlaps else '见原算例 CAD 记录'),
        ('分段自能最大相对差', f"{max(report['element_to_scalar_energy_relative_errors']):.3g}"),
        ('混合正负激励能量相对差', f"{report['combined_energy_relative_error']:.3g}"),
        ('理想短路组合能量相对差', f'{short_error:.3g}' if short_error is not None else '单端口 · 不适用'),
        ('矩阵检查', '分段及端口矩阵正定，所有 |k| ≤ 1（含数值容差）'),
    ]
    model = [
        ('磁性材料', f"{material['name']} · μr = {material['relative_permeability']:g} · {material['temperature_C']:g} °C"),
        ('装配与总气隙', f"{CORE_MODES[core['mode']]} · {gap_mm:.6g} mm"),
        ('绕线基准', f"r₀ = {config['frame']['r0_m']*1000:g} mm · z₀ = {config['frame']['z0_m']*1000:g} mm"),
        ('求解范围', f"空气球半径 {config['solver']['air_radius_m']*1000:g} mm，外边界切向矢势为零"),
    ]
    target = (report.get('input_targets_not_fitted') or {}).get('primary_self_inductance_H')
    if target and target>0 and report['primary_port']=='P':
        i = report['port_order'].index('P')
        delta = (report['L_ports_H'][i][i]/target-1)*100
        model.append(('设计软件给定的原边目标', f'{target*1e6:g} µH · 场解相对该目标 {delta:+.2f}%'))
    assumptions = list(dict.fromkeys(g.get('assumptions', [])+config.get('assumptions', [])))
    if any(w['parallel_bundles']>1 for w in g['windings']):
        assumptions.append('各并绕线束均匀分流，电流分配采用指定值。')
    if source['geometry'].get('leads'):
        assumptions.append('源包有引线记录，本算例只求解闭合等效匝。')
    assumptions.extend(['模型采用恒定磁导率与零偏置，导体使用闭合等效匝。引线与匝间走线、高频铜损、电容和饱和特性超出本次提取范围。',
                        '正电流流入同名端，绕向从 +Z 看起点到终点。逐元积分 Bᵢ·Hⱼ 得到分段矩阵，端口按 L = Cᵀ L段 C 归算。'])
    ready = source['geometry']['ready']
    statuses = '、'.join(f"{key}{'就绪' if ready.get(field) else '待补充'}"
                        for key,field in [('二维截面','cross_section'),('三维几何','geometry_3d'),('电磁输入','electromagnetic')])
    sources = [
        ('材料来源', material['source']), ('磁芯与气隙来源', core['source']),
        ('气隙中心', f"z = {core['gap_center_z_m']*1000:g} mm，已装配模式按导入实体核对"),
        ('磁芯姿态', f"XYZ 平移 {core['translation_mm']} mm，依 XYZ 顺序旋转 {core['rotation_deg']} °"),
        ('单位与共同坐标', f"STEP 按声明单位换算，BREP 选用 {core['brep_unit']}。建模用 mm，求解用 m，Z 为绕线轴。"),
        ('原导出包状态', statuses), ('源包 SHA-256', source['sha256']), ('磁芯 SHA-256', core['sha256'])]
    return checks, model, sources, assumptions


def export_report(out, report, field, g, config, source, *, case_dir=None):
    out = Path(out)
    case = Path(case_dir) if case_dir else out
    mesh = read(case/'geometry-validation.json')
    quality = read(case/'mesh-quality.json')
    plots(out, report, field, g)
    primary, ports = report['primary_port'], report['port_order']
    readings = port_readings(report)
    colors = winding_colors(g)
    turns = {w['id']: w['turns'] for w in g['windings']}
    cards = key_readings(report)
    port_headers = ['端口', '匝数', '自感 L（µH）', f'互感 M（对 {primary}，µH）', f'k（对 {primary}）']
    port_rows = [[r.name, turns[r.name], f'{r.self_uH:.5f}',
                  '—' if r.primary else f'{r.mutual_uH:+.5f}', '—' if r.primary else f'{r.k:+.7f}'] for r in readings]
    row_heads = [f'<span class="swatch" style="background:{colors[r.name]}"></span>{h(r.name)}'
                 + ('<span class="reference">原边</span>' if r.primary else '') for r in readings]
    matrix_head = ['端口', *ports]
    lrows = [[name, *[f'{v*1e6:.6f}' for v in row]] for name, row in zip(ports, report['L_ports_H'])]
    krows = [[name, *[f'{v:.7f}' for v in row]] for name, row in zip(ports, report['k_ports'])]
    sections = sorted(g['physical_sections'], key=lambda s:s['layer_index_one_based'])
    sec_head = ['层', '物理段', '端口', '匝数', '绕向（+Z）', '起点 → 终点', '同名端', '来源']
    status_names = {'assumed':'参考假设', 'confirmed':'已确认', 'unconfirmed':'待确认'}
    sec_rows = [[s['layer_index_one_based'], s['section_id'], s['winding_id'], s['turns'],
                 '逆时针' if s['direction']=='ccw' else '顺时针', f"{s['start_node']} → {s['end_node']}",
                 s['dot_node'], status_names.get(s['status'], s['status'])] for s in sections]
    connections = [f"{p['winding_id']}（{p['dot_node']} → {p['other_node']}）　"+' → '.join(p['section_order'])
                   for p in g['connections']]
    checks, model, sources, assumptions = evidence(config, g, source, report, mesh, quality)
    classification = CLASSIFICATIONS.get(config['classification'], config['classification'])
    pending = [label for label, key in [('网格收敛','mesh_converged'), ('空气域收敛','air_domain_converged'),
                                         ('实测对照','measurement_validated')] if not report.get(key)]
    scope_title = '验证范围'
    scope = ('已通过能量与矩阵校核。仍需完成'+'、'.join(pending)+'。') if pending else '收敛与实测验证状态见结果记录。'
    field_note = (f'沿 y = 0 的 x–z 平面剖切，虚线框对应右侧放大区域。彩色轮廓来自导线网格，轮廓内外的底色均为 |B|（mT，对数色标）。'
                  f'白色实线是磁芯边界，箭头仅指示面内磁场方向。激励为 {primary} 的归一化 1 A。')
    model_note = f"本次模型包含 {len(sections)} 个物理段、{mesh['coil_solids']} 个等效线束实体。"
    if len(sections) <= 8:
        model_note += '由内向外依次为 '+' → '.join(str(s['section_id']) for s in sections)+'。'
    model_note += '剖口用于显示内层线束，模型采用闭合等效匝。'
    generated = now()
    finished = report.get('finished_at') or '见原算例日志'
    duration_s = report['total_solver_wall_s']
    duration = f'{int(duration_s//60)} 分 {duration_s%60:.1f} 秒'
    card_html = ''.join(f'<article class="metric"><h3>{h(label)}</h3><div class="number">{h(value)}<small>{h(unit)}</small></div>'
                        f'<p>{h(detail)}</p></article>' for label, value, unit, detail in cards)
    def k_style(i, j):
        value = report['k_ports'][i][j]
        tint = '203,76,81' if value<0 else '26,128,133'
        return f' style="background:rgba({tint},{.045+.10*min(1,abs(value)):.3f})"' + (' class="diag"' if i==j else '')
    resources = Path(__file__).parent
    template = Template((resources/'report_template.html').read_text(encoding='utf-8'))
    document = template.substitute(css=(resources/'report_style.css').read_text(encoding='utf-8'),
        name=h(config['name']), classification=h(classification), finished=h(finished.replace('T',' ',1)),
        nports=len(ports), nsections=len(sections), primary=h(primary), cards=card_html,
        port_table=html_table(port_headers,port_rows,css='port-grid',row_headers=row_heads),
        scope_title=h(scope_title), scope_body=h(scope), field_alt=h(f'{primary} 归一化 1 A 的磁场与各绕组导线轮廓，以及右侧绕线窗口放大图'),
        field_image=data_image(out/'model_field.png'), model_image=data_image(out/'winding_model.png'),
        field_note=h(field_note), model_note=h(model_note),
        ltable=html_table(matrix_head,lrows), ktable=html_table(matrix_head,krows,cell_style=k_style),
        duration=h(duration), checks=facts(checks), model_facts=facts(model), sources=facts(sources),
        sections=html_table(sec_head,sec_rows), connections=''.join(f'<li>{h(x)}</li>' for x in connections),
        assumptions=''.join(f'<li>{h(x)}</li>' for x in assumptions),
        version=h(__version__), generated=h(generated.replace('T',' ',1)))
    if len(ports)>4:
        document = document.replace('class="matrix-layout"', 'class="matrix-layout wide"')
    (out/'report.html').write_text(document, encoding='utf-8')

    summary = '\n'.join(f'- **{md(label)}**　{md(value)} {md(unit)}（{md(detail)}）' for label,value,unit,detail in cards)
    markdown = f"""# {md(config['name'])} · 变压器耦合仿真报告

{md(classification)} · 求解于 {md(finished)} · 报告 v{__version__} 生成于 {generated}

## 结果概览

{summary}

{md_table(port_headers, port_rows)}

**{scope_title}**　{scope}

## 磁场与绕组

![磁场总览与绕线窗口](model_field.png)

{field_note}

![完整装配与绕组剖视](winding_model.png)

{model_note}

## 端口自感与互感（µH）

{md_table(matrix_head, lrows)}

## 有符号耦合系数

{md_table(matrix_head, krows)}

![有符号耦合矩阵](k_matrix.png)

## 数值校核

{md_facts(checks)}
- **求解累计耗时**　{duration}

## 模型与来源

{md_facts(model + sources)}

{md_table(sec_head, sec_rows)}

{chr(10).join('- '+md(x) for x in connections)}

### 假设与适用范围

{chr(10).join('- '+md(a) for a in assumptions)}

完整算例保存冻结输入、CAD、网格、分段场解及日志。L_ports_H.csv、L_sections_H.csv 使用 H，k_ports.csv 为无量纲有符号系数。
"""
    (out/'report.md').write_text(markdown, encoding='utf-8')
    return out/'report.html'

