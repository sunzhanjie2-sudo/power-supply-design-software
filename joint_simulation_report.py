"""One Word report from frozen field, calculator and actual SPICE evidence.

This renderer never starts a solver or recalculates a design. The independent
engines own the values; one python-docx Document owns sections, equations and
image relationships throughout the report.
"""
import base64
from datetime import datetime, timedelta, timezone
from html.parser import HTMLParser
from io import BytesIO
import json
import math
import re
from pathlib import Path
from urllib.parse import unquote, urlparse
from zipfile import ZipFile


def _number(value, scale=1, suffix=''):
    if value is None:
        return '未取得'
    if isinstance(value, str):
        return value
    try:
        value = float(value) * scale
    except (ValueError, TypeError):
        return str(value)
    return f'{value:.6g}{suffix}' if math.isfinite(value) else '无有效值'


class _Images(HTMLParser):
    def __init__(self):
        super().__init__()
        self.items = []

    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        if tag == 'img' and attrs.get('src'):
            self.items.append((attrs['src'], attrs.get('alt') or '变压器场仿真图'))


def _field_images(report_path):
    """Read local / embedded raster figures; never fetch remote content."""
    from PIL import Image
    if not report_path or not Path(report_path).is_file():
        return [], ['原始场报告图像文件不可用，本节仅保留已取得的矩阵与条件。']
    report = Path(report_path).resolve()
    parser = _Images()
    if report.stat().st_size > 64 * 1024 * 1024:
        return [], ['原始场报告超过64 MiB，未载入图像；完整文件保留在工程目录。']
    parser.feed(report.read_text('utf-8-sig'))
    images, notes, seen = [], [], set()
    for source, caption in parser.items:
        if source in seen:
            continue
        seen.add(source)
        try:
            if source.startswith('data:image/'):
                header, body = source.split(',', 1)
                if ';base64' not in header:
                    raise ValueError('图像并非base64编码')
                blob = base64.b64decode(body, validate=True)
            else:
                parsed = urlparse(source)
                if parsed.scheme or parsed.netloc:
                    raise ValueError('不自动下载远程图像')
                path = (report.parent / unquote(parsed.path)).resolve()
                if not path.is_relative_to(report.parent) or not path.is_file():
                    raise ValueError('图像未包含在本地场报告目录中')
                blob = path.read_bytes()
            if len(blob) > 20 * 1024 * 1024:
                raise ValueError('单张图像超过20 MiB')
            with Image.open(BytesIO(blob)) as image:
                image.verify()
            images.append((blob, caption))
        except (ValueError, OSError) as exc:
            notes.append(f'{caption}：未嵌入，{exc}')
    return images, notes


def _evidence(record, spice_result):
    circuit = record.get('circuit') or {}
    if isinstance(circuit.get('evidence'), dict):
        return circuit['evidence']
    if circuit.get('evidence_path') and Path(circuit['evidence_path']).is_file():
        return json.loads(Path(circuit['evidence_path']).read_text('utf-8-sig'))
    result = spice_result or circuit.get('summary') or {}
    if result.get('path') and Path(result['path']).is_file():
        with ZipFile(result['path']) as archive:
            if 'comparison.json' in archive.namelist():
                return json.loads(archive.read('comparison.json'))
    return None


def write_joint_report(path, record, *, design_run=None, spice_result=None):
    """Consume the joint workflow record and optional in-memory design run.

    ``record.field`` is the verified transformer comparison record. ``margin``
    keeps both matrix versions, achieved leakage and the engineering factor.
    Partial and failed stages produce a useful report with explicit gaps.
    Returns a rendering receipt; the caller owns cancellation / publication.
    """
    from docx_layout import new_document, paragraph, table, figure, equation, section
    from docx.oxml.ns import qn
    from docx.shared import Pt
    bundle = design_run.runtime_bundle() if design_run is not None else None
    from config_io import decode_config
    design_spec = (bundle or {}).get('base_spec') or record.get('adopted_config') or record.get('original_config')
    design_spec = decode_config(design_spec) if isinstance(design_spec, dict) else None
    evidence = _evidence(record, spice_result)
    stamp = datetime.now(timezone(timedelta(hours=8))).strftime('%Y-%m-%d %H:%M UTC+08:00')
    doc = new_document('电磁仿真，电路仿真，设计计算联合报告', stamp,
                       '电磁仿真  电路仿真  设计计算')
    doc.add_heading('1 评审结论与验证范围', 1)
    paragraph(doc, '本报告依次回答四个问题：需求与硬件是什么，磁场提取采用了什么参数，采用后的电路设计是否满足要求，实际电路仿真与计算有哪些差异。各模块按 Vinmin 左列与 Vinmax 右列对照，共同结构和参数仅记录一次。')
    paragraph(doc, '报告编制时间：'+stamp+'；证据执行起止：'+str(record.get('started_at') or '未记录')+' 至 '+str(record.get('completed_at') or '未记录')+'。重新排版不会重新执行场解或电路仿真。', True)
    acceptance = None
    if design_spec is not None:
        from report_architecture import add_acceptance_report
        summary_start = len(doc.paragraphs)
        acceptance = add_acceptance_report(doc, design_spec, bundle, joint_record=record,
                              spice_evidence=evidence, title='工程验收摘要', short_summary=True)
        for p in doc.paragraphs[summary_start:]:
            if p.style.name in ('Heading 1', 'Heading 2'):
                p.style = doc.styles['Heading 2' if p.style.name == 'Heading 1' else 'Heading 3']
                for run in p.runs:
                    run.font.size = Pt(13 if p.style.name == 'Heading 2' else 11)
    else:
        paragraph(doc, '未取得可对应的设计输入，工程验收保持待验证。')
    stages = record.get('stages') or []
    errors = list(record.get('errors') or [])
    if record.get('error'):
        errors.append(record['error'])
    failed = [s for s in stages if s.get('status') in ('failed', 'error', 'cancelled', 'skipped')]
    paragraph(doc, '本报告面向研发设计评审，按当前变压器结构提取自感与互感，记录工程裕量后的参数映射，再用同一套硬件完成输入两端的电路计算与实际 LTspice 对比。原始场解、工程采用值及仿真证据分别展示。')
    workflow_incomplete = bool(failed or errors or record.get('status') not in ('complete', 'completed', 'success'))
    if workflow_incomplete:
        paragraph(doc, '本次联合流程尚有未完成或需复核项目，不能作为全部工况验证通过的结论。下表及各章节保留实际失败原因和已完成的证据。')
    else:
        paragraph(doc, '流程已执行完成。执行完成不代表模型已通过网格收敛、样机验证，亦不代表所有电路指标均满足规格；判定以各工况的检查项为准。')
    table(doc, ['步骤', '本次状态', '耗时 / s', '问题或说明'], [
        ('既有场解输入与结果重校验' if record.get('resumed_field') and s.get('name') == 'field' else s.get('label') or s.get('name', ''),
         {'complete': '完成', 'completed': '完成', 'partial': '部分完成，需复核', 'failed': '失败', 'error': '失败',
          'cancelled': '已取消', 'skipped': '未执行', 'pending': '待执行', 'running': '执行中'}.get(s.get('status'), s.get('status', '未记录')),
         _number(s.get('elapsed_s')), s.get('error') or s.get('message') or '—') for s in stages
    ] or [('联合流程', '未记录', '—', '没有取得阶段状态')], [1.4, .8, .7, 4.2])
    for error in errors:
        paragraph(doc, '问题：' + str(error), True)
    if record.get('resumed_field'):
        paragraph(doc, '本任务经输入、几何、原始产物及结果哈希校验后，续用已经完成的场解。本表场解阶段耗时为本次重新校验与衔接耗时，不是原始磁场求解耗时；本次没有重新运行该磁场解。原场解结果与验证范围仍单独记录。', True)
    table(doc, ['层级', '本节要回答的问题', '证据口径'], [
        ('需求与结构', '端口、功率及绕组如何定义', '同一设计输入与物理结构'),
        ('磁件与参数映射', '自感互感从何而来，采用了什么裕量', '原始场解与工程采用值分开'),
        ('电路设计', '同套硬件在两个输入端点如何工作', 'Vinmin / Vinmax 并列，补偿不变'),
        ('实际电路验证', '仿真与设计差异是否可解释', '按测试族及模块并列，失败保留'),
        ('验收与追溯', '哪些满足，哪些仍需整改', '目标、计算、仿真、实测独立判定'),
    ], [1.25, 3.0, 2.85])

    transformer = record.get('field') or (record.get('transformer') or {}).get('record') or {}
    field = transformer.get('field') or {}
    conditions = transformer.get('model_conditions') or {}
    section(doc, '2 共同需求与变压器仿真').paragraph_format.page_break_before = False
    if design_spec is not None:
        table(doc, ['需求', 'Vinmin', 'Vinmax'], [
            ('输入电压 / V', _number(design_spec.get('V_in_min', design_spec.get('V_in'))), _number(design_spec.get('V_in_max', design_spec.get('V_in')))),
            ('拓扑', str(design_spec.get('topology') or '未取得'), '同一拓扑'),
            ('频率设定 / Hz', _number(design_spec.get('f_sw')), '同一设定，QR实际频率另列'),
            ('输出与反馈', '端口在防反后，反馈在所选路防反前', '同一接线与反馈路'),
        ], [1.8, 2.65, 2.65])
    if field:
        material, core, solver = (conditions.get(k) or {} for k in ('material', 'core', 'solver'))
        bobbin = conditions.get('bobbin') or {}
        table(doc, ['项目', '采用条件'], [
            ('拓扑与磁芯', str(transformer.get('topology') or '未记录') + ' / ' + str(core.get('calculator_core_model') or '未记录')),
            ('材料与相对磁导率', str(material.get('name') or '未记录') + ' / ' + _number(material.get('relative_permeability'))),
            ('骨架净窗口 宽 × 高 / mm', _number(bobbin.get('axial_window_m'), 1e3) + ' × ' + _number(bobbin.get('radial_window_m'), 1e3)),
            ('从内到外的物理层', ' → '.join(f'{name} {turns}匝' for name, turns in conditions.get('layers', [])) or '未记录'),
            ('绕组总匝数', ' / '.join(f'{name} {turns}匝' for name, turns in conditions.get('windings', [])) or '未记录'),
            ('实际模型总气隙 / mm', _number(core.get('total_gap_m'), 1e3)),
            ('磁静态工作点', _number(material.get('temperature_C'), suffix=' °C') + ' / ' + _number(material.get('bias_current_A'), suffix=' A偏置')),
            ('网格与空气域半径', str(solver.get('mesh_profile') or '未记录') + ' / ' + _number(solver.get('air_radius_m'), 1e3, ' mm')),
            ('原边开路自感 / µH', _number(field.get('primary_self_H'), 1e6)),
            ('全部其他端口理想短路时原边电感 / µH', _number(field.get('primary_short_H'), 1e6)),
        ], [2.3, 4.8])
        for key, title in (('L_ports_H', '原始场解自感与互感矩阵 µH'), ('k_ports', '原始场解有符号耦合系数矩阵')):
            doc.add_heading(title, 2)
            ports = field.get('port_order') or []
            rows = field.get(key) or []
            if len(rows) == len(ports) and ports:
                scale = 1e6 if key == 'L_ports_H' else 1
                table(doc, ['端口'] + ports,
                      [[label] + [_number(value, scale) for value in row] for label, row in zip(ports, rows)],
                      [.65] + [6.45 / len(ports)] * len(ports))
            else:
                paragraph(doc, '本矩阵未取得完整数据，不补零。')
        validation = transformer.get('validation') or {}
        paragraph(doc, '独立验证记录：' + '；'.join(name + ('已有记录' if validation.get(key) else '尚未验证')
             for key, name in [('mesh_converged', '网格收敛'), ('air_domain_converged', '空气域收敛'), ('measurement_validated', '样机实测')]) + '。', True)
        images, image_notes = _field_images(transformer.get('report_path'))
        for index, (blob, caption) in enumerate(images, 1):
            figure(doc, blob, f'变压器图 {index}  {caption}')
        for note in image_notes:
            paragraph(doc, note, True)
    else:
        paragraph(doc, '没有取得本次有效场解。未采用旧场解或默认耦合系数替代本次结果，后续回填与电路验证应按流程状态处理。')

    section(doc, '3 工程裕量与电路参数回填').paragraph_format.page_break_before = False
    margin = record.get('margin') or (record.get('transformer') or {}).get('margin') or {}
    if margin:
        paragraph(doc, '裕量属于工程设定，不是场求解器精度或实测修正系数。保留原始矩阵，单独列出电路采用矩阵；倍数作用的具体定义与实际达到的漏感同时列出。')
        table(doc, ['项目', '本次值'], [
            ('裕量目标倍数', _number(margin.get('factor'))),
            ('映射方法', margin.get('method') or '未记录'),
            ('互感统一缩放系数 α', _number(margin.get('off_diagonal_scale'))),
            ('采用原边开路自感 / µH', _number(margin.get('primary_self_H'), 1e6)),
            ('场解原边理想短路电感 / µH', _number(margin.get('original_primary_short_H'), 1e6)),
            ('采用原边理想短路电感 / µH', _number(margin.get('adopted_primary_short_H'), 1e6)),
        ], [2.7, 4.4])
        equation(doc, 'L_ii,采用=L_ii,场解')
        equation(doc, 'M_ij,采用=α×M_ij,场解')
        equation(doc, 'L_短路,目标=倍数×L_短路,场解')
        equation(doc, 'k_ij=', 'M_ij', '√(L_ii×L_jj)')
        paragraph(doc, '自感、互感及耦合系数以同一次完整矩阵为依据。上述关系仅解释统一缩放映射，不能把工程裕量后的参数冒充原始场解。')
        ports = margin.get('port_order') or field.get('port_order') or []
        for key, title, scale in [('adopted_L_ports_H', '电路采用自感与互感矩阵 µH', 1e6),
                                  ('adopted_k_ports', '电路采用耦合系数矩阵', 1)]:
            matrix = margin.get(key) or []
            if matrix and len(matrix) == len(ports):
                doc.add_heading(title, 2)
                table(doc, ['端口'] + ports,
                      [[label] + [_number(v, scale) for v in row] for label, row in zip(ports, matrix)],
                      [.65] + [6.45 / len(ports)] * len(ports))
        old_short = margin.get('original_short_by_port_H') or []
        new_short = margin.get('adopted_short_by_port_H') or []
        if len(old_short) == len(new_short) == len(ports) and ports:
            doc.add_heading('各端口其余绕组全部理想短路时的电感', 2)
            table(doc, ['端口', '场解 / µH', '工程采用 / µH', '实际倍数'], [
                (name, _number(old, 1e6), _number(new, 1e6), _number(new / old) if old else '未定义')
                for name, old, new in zip(ports, old_short, new_short)
            ], [1., 2., 2., 2.1])
        for note in margin.get('notes') or []:
            paragraph(doc, note, True)
    else:
        paragraph(doc, '尚未取得可采用的矩阵，未执行参数回填。')

    if bundle is not None:
        from input_range_report import export_input_range_docx
        design_start = len(doc.paragraphs)
        export_input_range_docx(None, bundle, document=doc, save=False, include_acceptance=False)
        # Standalone reports start every module on a fresh page. In the
        # combined report this strands short module conclusions on otherwise
        # empty pages; preserve endpoint boundaries and let other sections
        # flow naturally, with existing keep-with-next and repeating headers.
        for p in doc.paragraphs[design_start:]:
            if p.style.name == 'Heading 1':
                if p.text == '采用参数后的电路设计':
                    p.text = '4 采用参数后的电路设计'
                else:
                    p.text = re.sub(r'^(\d+)(?=\s)', r'4.\1', p.text)
                    p.style = doc.styles['Heading 2']
                    for run in p.runs:
                        run.font.size = Pt(13)
                        run.font.bold = True
                p.paragraph_format.page_break_before = False
            elif p.style.name == 'Heading 2':
                p.style = doc.styles['Heading 3']
                for run in p.runs:
                    run.font.size = Pt(11)
                    run.font.bold = True
    else:
        section(doc, '电路计算结果不可用')
        paragraph(doc, '没有取得本次采用矩阵后的共享计算快照。未重新运行其他设计或使用另一套参数补齐本节。')
        metrics = (record.get('calculation') or {}).get('endpoint_metrics') or []
        if metrics:
            table(doc, ['端点', 'Vin / V', '频率 / kHz', 'MOS峰值 / A', '效率 / %'], [
                (r.get('case', ''), _number(r.get('vin_V')), _number(r.get('frequency_Hz'), .001),
                 _number(r.get('switch_peak_A')), _number(r.get('efficiency'), 100)) for r in metrics
            ], [1.5, 1.2, 1.5, 1.5, 1.4])

    if evidence is not None:
        from spice_comparison_report import write_report
        write_report(None, evidence, document=doc, save=False)
    else:
        section(doc, '电路仿真尚未取得完整证据')
        paragraph(doc, 'LTspice尚未运行、执行失败或没有取得可读的comparison.json。未生成有效波形、FRA或交叉调整率的工况不发布仿真通过结论。实际问题见流程状态和工程日志。')

    if design_spec is not None:
        from report_architecture import add_acceptance_report
        add_acceptance_report(doc, design_spec, bundle, joint_record=record,
                              spice_evidence=evidence, title='6 工程验收与问题闭环')
    section(doc, '7 适用范围与证据追溯')
    for note in dict.fromkeys(list(transformer.get('limits') or []) + list(record.get('limits') or [])):
        p = paragraph(doc, note, True)
        p.paragraph_format.space_after = Pt(2)
        p.paragraph_format.line_spacing = 1.05
    p = paragraph(doc, '磁静态场解不包含运行频率下的全部涡流、非线性磁芯损耗、饱和或寄生电容。通用行为SPICE模型与实际控制芯片、样机测量是不同证据层级。报告用同一份工程输入串联结果，不以一致性代替硬件验证。')
    p.paragraph_format.space_after = Pt(5)
    table(doc, ['证据', '记录'], [
        ('源几何 SHA-256', transformer.get('geometry_sha256') or '未取得'),
        ('场解结果 SHA-256', transformer.get('field_result_sha256') or '未取得'),
        ('求解工具版本', transformer.get('solver_version') or '未取得'),
        ('原始运行目录', record.get('directory') or '见随附工程'),
        ('电路计算快照文件', Path(str((record.get('calculation') or {}).get('snapshot_path'))).name if (record.get('calculation') or {}).get('snapshot_path') else '未取得'),
        ('实际电路仿真证据文件', Path(str((record.get('circuit') or {}).get('evidence_path'))).name if evidence and (record.get('circuit') or {}).get('evidence_path') else '见随附电路工程 comparison.json' if evidence else '未取得'),
    ], [1.8, 5.3])
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    doc.save(target)
    return dict(path=str(target), figures=len(doc.inline_shapes), tables=len(doc.tables),
                equations=len(doc.element.xpath('.//m:oMath')), sections=len(doc.sections),
                circuit_evidence_available=evidence is not None,
                complete_design_snapshot=bundle is not None,
                acceptance_state=(acceptance or {}).get('summary', {}).get('state', 'undefined'),
                engineering_accepted=(acceptance or {}).get('summary', {}).get('state') == 'pass',
                incomplete=bool(workflow_incomplete or evidence is None or bundle is None))
