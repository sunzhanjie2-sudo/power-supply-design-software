"""One Word document comparing and fully documenting both input endpoints.

The input is a solved ``calculate_input_endpoints`` snapshot. This module never
resizes hardware, tunes compensation or changes the selected UI operating case.
Complete case sections are authored into one Document, not merged as OOXML.
"""
from datetime import datetime, timedelta, timezone
import math
from pathlib import Path

import numpy as np

from docx_layout import new_document, paragraph, table, figure, section
from report_docx import TOPOLOGY, _chart, export_design_docx, value


CASE_COLORS = {'Vinmin': '#2068A0', 'Vinmax': '#D18532'}


def _finite(number):
    try:
        return number is not None and math.isfinite(float(number))
    except (TypeError, ValueError):
        return False


def _result(case):
    return case.get('result') if not case.get('error') else None


def _magnetic_devices(result):
    mag = (result or {}).get('mag', {})
    devices = [mag[key] for key in ('transformer', 'inductor')
               if mag.get(key) and mag[key].get('ok')]
    devices += [dev for dev in mag.get('inductors', []) if dev.get('ok')]
    return devices


def _metrics(case):
    result = _result(case)
    if not result:
        return {}
    op, wf = result['op'], result['wf']
    loop = result.get('loop') or {}
    caps = result.get('capacitors') or {}
    devices = _magnetic_devices(result)
    return dict(eta=result.get('eta'), P_total=result.get('P_total'),
                D=op.get('D'), f_sw=op.get('f_sw'),
                I_L_pk=op.get('I_L_pk'), I_L_min=op.get('I_L_min'),
                I_sw_rms=op.get('I_sw_rms'), V_sw_max=op.get('V_sw_max'),
                V_d_max=op.get('V_d_max'), ripple_pp=wf.get('ripple_pp'),
                cap_in_rms=caps.get('input', {}).get('total_bank'),
                B_pk=max((dev['B_pk'] for dev in devices), default=None),
                dT=max((dev['dT'] for dev in devices), default=None),
                fc=loop.get('fc'), min_pm=loop.get('min_pm'),
                gm_db=loop.get('gm_db'))


def _worse(a, b, direction):
    """Compare only two valid endpoints, never certify the whole interval."""
    if not direction:
        return '仅对比'
    if not (_finite(a) and _finite(b)):
        return '未完整计算'
    if math.isclose(a, b, rel_tol=1e-8, abs_tol=1e-12):
        return '两端相同'
    lower = a < b
    return 'Vinmin' if lower == (direction == 'min') else 'Vinmax'


# direction describes which numerical extreme warrants greater attention. It
# does not imply that device voltage/current ratings have been supplied.
METRICS = (
    ('eta', '模型效率', '%', 100, 'min'),
    ('P_total', '总损耗', 'W', 1, 'max'),
    ('I_L_pk', '电感或原边峰值电流', 'A', 1, 'max'),
    ('I_sw_rms', '主开关有效值电流', 'A', 1, 'max'),
    ('V_sw_max', '主开关电压应力', 'V', 1, 'max'),
    ('V_d_max', '所选路整流反压', 'V', 1, 'max'),
    ('ripple_pp', '主反馈路低频纹波', 'V', 1, 'max'),
    ('cap_in_rms', '输入电容组纹波 RMS', 'A', 1, 'max'),
    ('B_pk', '最高磁件峰值磁密', 'T', 1, 'max'),
    ('dT', '最高磁件估算温升', 'K', 1, 'max'),
    ('min_pm', '所有穿越最小相位裕度', '°', 1, 'min'),
    ('gm_db', '增益裕度', 'dB', 1, 'min'),
    ('fc', '所选下降穿越频率', 'Hz', 1, None),
    ('f_sw', '实际开关频率', 'Hz', 1, None),
    ('D', '导通占空比', '', 1, None),
    ('I_L_min', '电感或原边谷值电流', 'A', 1, None),
)


def _metric_rows(cases, metric_keys=None):
    left, right = [_metrics(case) for case in cases]
    rows = []
    for key, label, unit, scale, direction in METRICS:
        if metric_keys is not None and key not in metric_keys:
            continue
        a, b = left.get(key), right.get(key)
        rows.append((label, value(a*scale if _finite(a) else None, unit),
                     value(b*scale if _finite(b) else None, unit),
                     _worse(a, b, direction)))
    return rows


def _checks(case):
    return case.get('checks') or (_result(case) or {}).get('checks') or []


def _status(case):
    result = _result(case)
    if not result:
        return '计算失败'
    checks = _checks(case)
    review = sum(check.get('state') == 'review' for check in checks)
    undefined = sum(check.get('state') == 'undefined' for check in checks)
    loop = '有环路结果' if result.get('loop') is not None else '环路未计算'
    return f'稳态已计算；{review} 项需复核，{undefined} 项未定义；{loop}'


def _add_hardware(doc, range_result):
    hardware = range_result.get('hardware') or {}
    rows = []
    for key, label in (('transformer', '共享变压器'), ('inductor', '电感')):
        dev = hardware.get(key)
        if not isinstance(dev, dict):
            continue
        turns = (f"Np {dev['Np']} / Ns {dev['Ns']}" if key == 'transformer'
                 else f"N {dev['N']}")
        wire = (value(dev['d_wire_p'], 'm')+' / '+value(dev['d_wire_s'], 'm')
                if key == 'transformer' else value(dev['d_wire'], 'm'))
        rows.append((label, str(dev.get('core', '未定义')), turns, wire))
    for index, dev in enumerate(hardware.get('inductors', []), 1):
        rows.append((f'OUT{index} 电感', str(dev.get('core', '未定义')),
                     f"N {dev['N']}", value(dev['d_wire'], 'm')))
    if rows:
        table(doc, ['共用磁件', '磁芯', '固定匝数', '单股线径'], rows,
              [1.2, 1.45, 2.05, 2.4])
    else:
        paragraph(doc, '未获得有效的 Vinmin 参考磁件，不能声称两个端点使用了已确定的共同硬件。')


def _draw_comparison(fig, cases):
    axes = np.asarray(fig.subplots(2, 2)).ravel()
    for case in cases:
        result = _result(case)
        if not result:
            continue
        wf = result['wf']
        label = case['id']+' '+value(case['voltage'], 'V')
        color = CASE_COLORS[case['id']]
        time = np.asarray(wf['t'])*1e6
        for ax, key, scale in zip(axes[:3], ('i_sw', 'v_sw', 'vout_ripple'), (1, 1, 1000)):
            if key in wf:
                ax.plot(time, np.asarray(wf[key])*scale, color=color, label=label, lw=1.15)
        loop = result.get('loop')
        if loop is not None:
            axes[3].semilogx(loop['f'], 20*np.log10(np.maximum(np.abs(loop['gains'][2]), 1e-300)),
                            color=color, label=label, lw=1.15)
    for ax, title, unit in zip(axes[:3], ('主开关电流', '主开关漏源电压', '主反馈路输出低频纹波'), ('A', 'V', 'mV')):
        ax.set(title=title, xlabel='时间 / μs', ylabel=unit)
    axes[3].set(title='同一补偿器下的主反馈开环增益', xlabel='频率 / Hz', ylabel='dB')
    axes[3].axhline(0, color='#737373', ls='--', lw=.7)
    for ax in axes:
        ax.grid(alpha=.18)
        if ax.get_legend_handles_labels()[0]:
            ax.legend(fontsize=7, loc='best')
        else:
            ax.text(.5, .5, '该项未能计算', transform=ax.transAxes, ha='center')


def _add_output_comparison(doc, cases):
    banks = []
    for case in cases:
        result = _result(case) or {}
        banks.append({rail['id']: rail for rail in result.get('outputs', [])})
    indices = sorted(set(banks[0]) | set(banks[1]))
    if not indices:
        return
    doc.add_heading('各路输出端点对比', 2)
    paragraph(doc, '电压为各端点的实际解算值；纹波为峰峰值。下表只作汇总，单只电容 RMS、FFT 分带和绕组结果在后续两个完整工况中分别列出。', True)
    rows = []
    for index in indices:
        pair = [bank.get(index) for bank in banks]
        cells = []
        ripples = []
        for rail in pair:
            if rail is None:
                cells.append('未计算'); ripples.append(None)
            else:
                cells.append(value(rail['op']['V_out'], 'V')+' / '+value(rail['ripple_pp'], 'V'))
                ripples.append(rail['ripple_pp'])
        loss = ' / '.join(value(rail.get('P_rectifier') if rail else None, 'W') for rail in pair)
        rows.append((f'OUT{index}', *cells, _worse(*ripples, 'max'), loss))
    table(doc, ['输出', 'Vinmin 电压 / 纹波', 'Vinmax 电压 / 纹波', '纹波较大端', '整流损耗 min / max'], rows,
          [.6, 1.8, 1.8, 1.0, 1.9])


def _add_check_comparison(doc, cases):
    from design_checks import STATE_LABELS
    table(doc, ['工况', '计算与核查状态'], [(case['id'], _status(case)) for case in cases], [.9, 6.2])
    all_checks = [{check['id']: check for check in _checks(case)} for case in cases]
    rows = []
    for key in dict.fromkeys(list(all_checks[0])+list(all_checks[1])):
        pair = [checks.get(key) for checks in all_checks]
        if all(check is not None and check['state'] not in ('review', 'undefined') for check in pair):
            continue
        sample = next(check for check in pair if check is not None)
        cells = [STATE_LABELS.get(check['state'], check['state']) if check else '未计算' for check in pair]
        rows.append((sample['name'], *cells))
    if rows:
        table(doc, ['需关注的核查项', 'Vinmin', 'Vinmax'], rows, [4.1, 1.5, 1.5])
    elif all(_result(case) is not None and _checks(case) for case in cases):
        paragraph(doc, '两个端点已建模的检查均未出现需复核或未定义项，仍需额定值、热态及样机验证。')
    else:
        paragraph(doc, '没有完整的双端点核查结果，不能判定输入范围验证通过。')
    for case in cases:
        if case.get('error'):
            paragraph(doc, case['id']+' 计算失败：'+str(case['error']))
        if case.get('loop_error'):
            paragraph(doc, case['id']+' 环路未计算：'+str(case['loop_error']))


def export_input_range_docx(path, range_result, *, compensation_state=None,
                            mos_real_time=False, comparison=None, corners=None):
    """Write the endpoint overview followed by both complete design reports.

    ``range_result`` has ``base_spec``, ``fixed_spec``, ``hardware`` and two
    ``cases``: id, voltage, p, result, models, loop_error, error, checks. A case
    may additionally provide a precomputed ``efficiency_curve`` or ``corners``.
    Failures remain visible; neither omitted cases nor omitted loop models are
    replaced by fresh calculations of a different design.
    """
    by_id = {case['id']: case for case in range_result.get('cases', [])}
    if len(range_result.get('cases', [])) != 2 or set(by_id) != {'Vinmin', 'Vinmax'}:
        raise ValueError('输入范围报告必须包含 Vinmin 与 Vinmax 两个具名工况')
    cases = [by_id[key] for key in ('Vinmin', 'Vinmax')]
    base = range_result['base_spec']
    failed = [case['id'] for case in cases if _result(case) is None]
    hardware_fixed=bool(range_result.get('fixed_hardware',range_result.get('hardware')))
    from isolated_outputs import selected_params
    try:
        demand_power=selected_params(base)['P_out']
    except (ValueError,KeyError,TypeError):
        # An invalid reference still gets a useful failure report; never call
        # an OUT1 legacy scalar the multi-output total when parsing failed.
        demand_power=base.get('P_out') if not base.get('outputs') else None
    stamp = datetime.now(timezone(timedelta(hours=8))).strftime('%Y-%m-%d %H:%M %Z')
    doc = new_document('开关电源输入电压范围设计评审报告',
                       f"{TOPOLOGY.get(base['topology'], base['topology'])}  |  {stamp}",
                       '开关电源设计与环路分析  输入范围评审')
    doc.add_heading('输入范围与评审结论', 1)
    paragraph(doc, '报告先并列比较 Vinmin 与 Vinmax，再保留两个端点各自完整的需求、波形、器件、纹波、磁件、环路和补偿电路核算。蓝色表示 Vinmin，橙色表示 Vinmax。')
    if failed:
        paragraph(doc, '本报告计算不完整：'+ '、'.join(failed)+' 未获得有效稳态结果。已算出的端点可供查阅，不能据此宣称输入范围验证通过。')
    elif not hardware_fixed:
        paragraph(doc, '本报告为部分计算结果：未成功固定有效磁件，不能宣称完成同一套硬件的双端点设计验证。'+str(range_result.get('hardware_note') or ''))
    else:
        paragraph(doc, '两个端点均已完成稳态计算。两端点较不利值仅表示本次两点比较结果，不代表整个输入区间及所有负载、温度和器件容差下的最坏工况。')
    table(doc, ['设计需求', '共同设定'], [
        ('输入电压范围', value(cases[0]['voltage'], 'V')+' 至 '+value(cases[1]['voltage'], 'V')),
        ('总输出功率 / 频率设定', value(demand_power, 'W')+' / '+value(base['f_sw'], 'Hz')),
        ('反馈方式与主反馈',
         (str(base.get('feedback_mode', 'SSR'))+' / OUT'+str(int(base.get('feedback_output', 1))))
         if base['topology'] in ('FLYBACK','QR-FLYBACK','ACF-FORWARD') else
         '单路直接反馈 / '+str(base.get('control_mode','未定义'))),
        ('磁件与补偿口径', ('磁件按 Vinmin 确定后固定；' if hardware_fixed else '未固定有效磁件；')+
         '两端使用同一组补偿参数，不分别自动整定'),
    ], [2.1, 5.0])
    if math.isclose(cases[0]['voltage'], cases[1]['voltage'], rel_tol=0, abs_tol=0):
        from mos_manual import distinct_endpoints
        paragraph(doc, ('输入上下限相同，但两端手动 MOS 事件参数不同，因此分别核算损耗和开关过程。' if distinct_endpoints(base) else
            '输入上下限相同，底层复用同一计算结果；仍保留两个具名工况的完整内容，便于归档。'), True)
    doc.add_heading('关键结果并列摘要', 2)
    table(doc, ['指标', 'Vinmin', 'Vinmax', '两端点较不利值'],
          _metric_rows(cases, {'eta', 'P_total', 'I_L_pk', 'V_sw_max', 'ripple_pp', 'dT', 'min_pm'}),
          [2.2, 1.6, 1.6, 1.7])
    paragraph(doc, '阅读顺序：端点摘要 → 共同硬件与核查差异 → 同轴波形及各路比较 → Vinmin 完整核算 → Vinmax 完整核算。所有补偿参数在两个工况间保持不变。', True)

    from mos_four_cases import event_rows
    if any((_result(c) or {}).get('semi',{}).get('switch',{}).get('gate') for c in cases):
        doc.add_heading('MOS 四开关事件的电压与电荷',2)
        table(doc,['输入','事件','Id / A','Vgp / V','Qgs / nC','Qgd / nC','Qg(th) / nC','总Qg / nC'],[
            tuple(list(row[:2])+[f'{x*(1e9 if i>=4 else 1):.5g}' if isinstance(x,(int,float)) else x for i,x in enumerate(row[2:],2)])
            for row in event_rows(dict(cases=cases))],[.85,.5,.75,.85,1.,1.,1.1,1.05])
        paragraph(doc,'四事件分别取实际换流电流。曲线电荷模式只在所选 Vgs–Qg 平台前反查 Qgs；Qgd 为已确认平台段的电荷差。复用同一参考曲线时，Qgd、Qg(th) 与总 Qg 可以相同。测试电流及 VDD 不等于当前电流及 Vin，复用属于工程近似。',True)

    section(doc, '两端点应力与共同硬件')
    paragraph(doc, '较大应力、较大损耗或较小裕度标为较不利端。占空比、频率及谷值电流只并列展示，不作优劣判断。缺失结果保持未定义，不以零替代。', True)
    table(doc, ['指标', 'Vinmin', 'Vinmax', '两端点较不利值'], _metric_rows(cases),
          [2.2, 1.6, 1.6, 1.7])
    doc.add_heading('共用的物理磁件', 2)
    _add_hardware(doc, range_result)

    section(doc, '两端点核查差异')
    _add_check_comparison(doc, cases)

    section(doc, '两端点波形与多路输出比较')
    paragraph(doc, '同一坐标轴叠加两个端点，避免仅凭独立图轴误判大小。时间轴使用实际时间；QR 两端的开关频率可能不同。环路曲线始终对应同一补偿器、同一主反馈输出。', True)
    figure(doc, _chart((7.1, 4.6), lambda fig: _draw_comparison(fig, cases)),
           '图 R1  蓝色 Vinmin 与橙色 Vinmax 的同轴对比')
    _add_output_comparison(doc, cases)

    details = []
    for case in cases:
        result = _result(case)
        if result is None:
            section(doc, '['+case['id']+'] 完整核算不可用')
            paragraph(doc, '输入电压 '+value(case['voltage'], 'V')+'；失败原因：'+str(case.get('error') or '没有有效计算结果'))
            paragraph(doc, '本工况没有有效波形、损耗或环路结果；未使用另一端点数据替代。')
            continue
        details.append(export_design_docx(path, case['p'], result['op'], result['wf'], result,
            models=case.get('models'), loop_error=case.get('loop_error'),
            corners=case.get('corners') or (corners if case['id']=='Vinmin' else None),
            comparison=comparison if case['id']=='Vinmin' else None,
            mos_real_time=mos_real_time, efficiency_curve=case.get('efficiency_curve'),
            compensation_state=compensation_state, document=doc, case_label=case['id'], save=False))
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    doc.save(path)
    cross = range_result.get('cross_regulation')
    cross_incomplete = bool(cross and cross.get('supported') and not cross.get('complete'))
    return dict(path=str(path), case_count=2, successful_cases=2-len(failed), failed_cases=failed,
                incomplete=bool(failed) or not hardware_fixed or cross_incomplete, hardware_fixed=hardware_fixed,
                cross_regulation_complete=cross.get('complete') if cross else None,
                figure_count=len(doc.inline_shapes),
                check_count=sum(detail['checks'] for detail in details),
                cases=details, figures=len(doc.inline_shapes),
                checks=sum(detail['checks'] for detail in details),
                needs_review=sum(detail['needs_review'] for detail in details),
                loop_available=all((_result(case) or {}).get('loop') is not None for case in cases))
