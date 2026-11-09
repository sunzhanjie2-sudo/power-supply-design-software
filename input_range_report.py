"""One Word document comparing and fully documenting both input endpoints.

The input is a solved ``calculate_input_endpoints`` snapshot. This module never
resizes hardware, tunes compensation or changes the selected UI operating case.
Complete case blocks are captured in memory and paired by engineering module.
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
                B_pk=max((dev['B_pk'] for dev in devices if dev.get('B_pk') is not None), default=None),
                dT=max((dev['dT'] for dev in devices if dev.get('dT') is not None), default=None),
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
        if key in ('B_pk','dT') and all(((_result(case) or {}).get('mag',{}).get('inductor') or {}).get('design_enabled') is False for case in cases):
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
        if dev.get('design_enabled') is False:
            rows.append((label, '外购成品电感', value(dev['L'], 'H'),
                         'DCR '+value(dev['inductor_dcr'], 'Ω')))
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
        table(doc, ['共用磁件', '磁芯 / 来源', '固定匝数 / L', '线径 / 成品 DCR'], rows,
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
                            mos_real_time=False, comparison=None, corners=None,
                            document=None, save=True, include_acceptance=True):
    """Author by engineering module, comparing the same hardware side by side.

    The complete single-case author remains the content/OMML authority. Its
    native blocks are captured in memory and aligned by module; no case is
    recalculated, retuned or substituted during report generation.
    """
    from docx import Document
    from report_architecture import (add_acceptance_report, capture_document,
        comparison_charts, write_paired_modules, module_section)
    by_id={case['id']:case for case in range_result.get('cases',[])}
    if len(range_result.get('cases',[]))!=2 or set(by_id)!={'Vinmin','Vinmax'}:
        raise ValueError('输入范围报告必须包含 Vinmin 与 Vinmax 两个具名工况')
    cases=[by_id[key] for key in ('Vinmin','Vinmax')]
    base=range_result['base_spec']
    failed=[case['id'] for case in cases if _result(case) is None]
    fixed=bool(range_result.get('fixed_hardware',range_result.get('hardware')))
    stamp=datetime.now(timezone(timedelta(hours=8))).strftime('%Y-%m-%d %H:%M %Z')
    subtitle=f"{TOPOLOGY.get(base['topology'],base['topology'])}  |  {stamp}"
    if document is None:
        doc=new_document('开关电源设计评审报告',subtitle,'开关电源设计与环路分析  设计评审')
    else:
        doc=document
        module_section(doc,'采用参数后的电路设计',new_page=False)
        paragraph(doc,subtitle)
    paragraph(doc,'本报告面向研发与设计评审。先看验收与待闭合事项，再按需求、功率级、器件、'
        '电容、磁件和环路逐层核查。同一模块的 Vinmin 在左、Vinmax 在右，共同配置和公式只列一次。')
    if failed:
        paragraph(doc,'计算不完整  '+ '、'.join(failed)+' 未获得有效稳态结果；缺失端保留失败原因，不借用另一端数据。')
    elif not fixed:
        paragraph(doc,'硬件未闭合  未固定有效磁件，现有结果不能作为同一套硬件的双端验收。'+str(range_result.get('hardware_note') or ''))
    else:
        paragraph(doc,'两个输入端点使用同一套已确定硬件与补偿。端点比较不等同全输入、全负载、温度和器件容差验证。')
    module_section(doc,'1 评审结论与工程验收',new_page=False)
    table(doc,['工况','输入电压','计算与核查状态'],[(case['id'],value(case['voltage'],'V'),_status(case)) for case in cases],[.8,1.15,5.15])
    table(doc,['关键指标','Vinmin','Vinmax','两端较不利值'],
          _metric_rows(cases,{'eta','P_total','I_L_pk','V_sw_max','ripple_pp','dT','min_pm'}),[2.1,1.55,1.55,1.9])
    acceptance=(add_acceptance_report(doc,base,range_result,title='工程验收与证据') if include_acceptance else
        __import__('report_architecture').acceptance_snapshot(base,range_result))
    module_section(doc,'共同硬件与节点口径',new_page=False)
    _add_hardware(doc,range_result)
    from voltage_nodes import NOTE
    paragraph(doc,NOTE)
    paragraph(doc,'阅读导航  需求与共同硬件 → 功率级与钳位 → 器件选型与损耗 → 电容 → 磁件 → '
        '环路与反馈补偿 → 负载边界 → 模型限制与输入追溯。蓝色表头为 Vinmin，橙色表头为 Vinmax。',True)
    if cases[0]['voltage']==cases[1]['voltage']:
        from mos_manual import distinct_endpoints
        paragraph(doc,'输入上下限相同，但手动MOS事件参数不同，仍分别计算。' if distinct_endpoints(base) else
            '输入上下限相同，两端数值可以相同；保留具名端点便于与仿真和实测对应。',True)
    # Keep the complete author as the single source for data, equations and
    # plots. The paired capture renders graphics at their final physical width.
    contents=[];details=[]
    for case in cases:
        temp=Document()
        result=_result(case)
        if result is not None:
            with comparison_charts():
                details.append(export_design_docx('',case['p'],result['op'],result['wf'],result,
                    models=case.get('models'),loop_error=case.get('loop_error'),
                    corners=case.get('corners') or (corners if case['id']=='Vinmin' else None),
                    comparison=comparison if case['id']=='Vinmin' else None,
                    mos_real_time=mos_real_time,efficiency_curve=case.get('efficiency_curve'),
                    compensation_state=compensation_state,document=temp,save=False))
        contents.append(capture_document(temp))
    structure=write_paired_modules(doc,contents,cases,chapter_start=2)
    if save:
        Path(path).parent.mkdir(parents=True,exist_ok=True);doc.save(path)
    cross=range_result.get('cross_regulation')
    incomplete=bool(failed) or not fixed or bool(cross and cross.get('supported') and not cross.get('complete'))
    return dict(path=str(path),case_count=2,successful_cases=2-len(failed),failed_cases=failed,
        incomplete=incomplete,hardware_fixed=fixed,
        cross_regulation_complete=cross.get('complete') if cross else None,
        figure_count=len(doc.inline_shapes),check_count=sum(d['checks'] for d in details),
        cases=details,figures=len(doc.inline_shapes),checks=sum(d['checks'] for d in details),
        needs_review=sum(d['needs_review'] for d in details),
        loop_available=all((_result(c) or {}).get('loop') is not None for c in cases),
        report_architecture='module-paired-v1',acceptance_summary=acceptance['summary'],**structure)
