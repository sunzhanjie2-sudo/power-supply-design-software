"""Offline endpoint comparison alongside the extractor's original field report."""
from html import escape
from pathlib import Path
import os
from urllib.parse import quote


def _number(value, factor=1):
    return '—' if value is None else f'{value * factor:.6g}'


def _table(headers, rows):
    heading = ''.join('<th>' + escape(str(h)) + '</th>' for h in headers)
    data = ''.join('<tr>' + ''.join('<td>' + escape(str(c)) + '</td>' for c in row) + '</tr>'
                   for row in rows)
    return f'<div class="table"><table><thead><tr>{heading}</tr></thead><tbody>{data}</tbody></table></div>'


def write_comparison(path, record):
    f = record['field']
    labels = f['port_order']
    settings = record['model_conditions']
    source = settings['material']
    core = settings['core']
    target = record['original_target_H']
    lp = f['primary_self_H']
    field_report = Path(record['report_path'])
    try:
        report_url = quote(Path(os.path.relpath(field_report, path.parent)).as_posix(), safe='/')
    except ValueError:
        report_url = field_report.as_uri()
    bobbin = settings['bobbin']
    status = '已按场解参数复算' if record['after'] else '场解完成 · 参数待复核'
    parts = [f'<h1>变压器仿真与设计复算</h1><p class="status">{status}</p>',
             f'<p>{escape(record["topology"])} · {escape(source["name"])} · '
             f'<a href="{report_url}">打开完整磁场报告与绕组剖面</a></p>',
             '<h2>场解的工作条件</h2>',
             _table(('项目', '采用值', '来源或条件'), [
                 ('磁芯实体', core.get('calculator_core_model') or Path(core['path']).name, core.get('source', '')),
                 ('骨架净窗口', f'{_number(bobbin["axial_window_m"], 1000)} × '
                  f'{_number(bobbin["radial_window_m"], 1000)} mm', bobbin.get('source') or '当前绕制配置'),
                 ('各绕组总匝数', ' / '.join(f'{name} · {n} 匝' for name, n in settings['windings']),
                  '从内至外：' + ' → '.join(f'{name} {n}' for name, n in settings['layers'])),
                 ('线性相对磁导率', _number(source['relative_permeability']), source.get('source', '')),
                 ('气隙', _number(core['total_gap_m'], 1e3) + ' mm', core['mode']),
                 ('求解条件', f'{source["temperature_C"]:g} °C · {source["frequency_Hz"]:g} Hz · {source["bias_current_A"]:g} A',
                  '磁静态提取，电源开关频率见下表'),
                 ('网格 / 空气域半径', f'{settings["solver"]["mesh_profile"]} / '
                  f'{settings["solver"]["air_radius_m"]*1000:g} mm', '精度按独立收敛与实测记录判断')]),
             '<h2>原边电感与端口耦合</h2>',
             _table(('设计目标', '场解原边开路自感', '相对目标偏差', '其余端口理想短路时的原边电感'), [
                 (_number(target, 1e6)+' µH', _number(lp, 1e6)+' µH',
                  f'{100*(lp / target-1):+.2f}%', _number(f['primary_short_H'], 1e6)+' µH')]),
             '<h3>自感与互感 / µH</h3>',
             _table(['端口'] + labels, [[name] + [_number(v, 1e6) for v in row]
                                       for name, row in zip(labels, f['L_ports_H'])]),
             '<h3>有符号耦合系数 k</h3>',
             _table(['端口'] + labels, [[name] + [_number(v) for v in row]
                                       for name, row in zip(labels, f['k_ports'])])]
    if record.get('rcd_factors'):
        original, updated = record['rcd_factors']
        parts.append(_table(('写回设计的参数', '原设计', '场解参数复算', '换算依据'), [
            ('RCD 模型漏感系数 K', _number(original), _number(updated), 'K = 1 − L短路 / L原边开路')]))
    metrics = [('frequency_Hz', '开关频率 / kHz', .001), ('duty', '占空比 / %', 100),
               ('switch_peak_A', 'MOS 峰值电流 / A', 1), ('switch_stress_V', '设计 MOS 电压应力 / V', 1),
               ('primary_short_H', '功率级使用的原边漏感 / µH', 1e6),
               ('clamp_loss_W', 'RCD 损耗估算 / W', 1), ('efficiency', '设计效率 / %', 100)]
    parts.append('<h2>同一电源的输入端点</h2><p>两列均由电源计算器求得。复算列使用场解映射后的磁件参数。</p>')
    for i, before in enumerate(record['before']):
        after = record['after'][i] if record['after'] else {}
        parts.append(f'<h3>{escape(before["case"])} · {before["vin_V"]:g} V</h3>')
        parts.append(_table(('指标', '原设计', '场解参数复算'), [
            (title, _number(before.get(key), factor), _number(after.get(key), factor))
            for key, title, factor in metrics if before.get(key) is not None or after.get(key) is not None]))
    parts.append('<h2>适用范围与追溯</h2><ul>')
    parts.extend('<li>' + escape(note) + '</li>' for note in record['limits'])
    parts.append('</ul>')
    parts.append(_table(('验证', '本次状态'), [
        (name, '有验证记录' if record['validation'][key] else '待验证')
        for key, name in [('mesh_converged', '网格收敛'), ('air_domain_converged', '空气域收敛'),
                          ('measurement_validated', '样机实测')]]))
    parts.append(f'<p>求解工具 {escape(str(record["solver_version"]))}<br>源几何 SHA-256 · '
                 f'{escape(record["geometry_sha256"])}<br>场解结果 SHA-256 · {escape(record["field_result_sha256"])}</p>')
    css = """
body{margin:0;background:#f0f4f6;color:#16324a;font:16px/1.55 "Microsoft YaHei",sans-serif}
main{box-sizing:border-box;max-width:1000px;margin:36px auto;background:white;padding:32px 5%;border-top:5px solid #157b83}
h1{font-size:1.8rem;margin:0}h2{margin-top:1.6em;border-bottom:1px solid #dce6eb;padding-bottom:.3em;font-size:1.3rem}
h3{font-size:1.05rem}p,li,td{overflow-wrap:anywhere}.status{font-weight:bold;color:#12656a}
.table{overflow-x:auto}table{width:100%;border-collapse:collapse;font-variant-numeric:tabular-nums}
td,th{padding:8px;text-align:left;border-bottom:1px solid #dce6eb}th{background:#ecf3f5}a{color:#006b82}
@media print{body{background:white}main{margin:0;padding:0}tr,h2,h3{break-inside:avoid}h2,h3{break-after:avoid}}
"""
    path.write_text('<!DOCTYPE html><html lang="zh-CN"><meta charset="utf-8">'
                    '<meta name="viewport" content="width=device-width,initial-scale=1">'
                    '<title>变压器仿真与设计复算</title><style>' + css +
                    '</style><main>' + '\n'.join(parts) + '</main></html>', encoding='utf-8')
