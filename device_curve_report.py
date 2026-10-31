"""Provenance table rendered by both Word and the module-per-sheet XLSX path."""
from device_curve_sources import TRANSFER, CHARGE, LABELS, source_rows


def add_device_source_report(doc, p, res):
    from docx_layout import paragraph, table
    gate = res['semi']['switch']['gate']
    diode_models = {model['ref']: model for model in res.get('diode_models', [])}
    rows = []
    for row in source_rows(p):
        target = row['target']
        if target == TRANSFER:
            source = 'curve' if gate['mode']=='curve' else 'legacy' if gate['mode']=='current' else 'fixed'
        elif target == CHARGE:
            source = 'curve' if gate.get('charge_mode')=='curve' else 'fixed'
        else:
            source = 'curve' if diode_models.get(target, {}).get('model')=='vf_if_curve' else 'fixed'
        curve = row['curve']
        if source == 'curve':
            points = curve.get('points') or [pt for trace in curve.get('traces', []) for pt in trace['points']]
            detail = curve.get('name', '未命名') + f' · {len(points)} 点'
        elif curve:
            detail = '已存曲线但未启用：' + curve.get('name', '未命名')
        else:
            detail = '使用对应手动参数'
        rows.append((row['ref']+' · '+row['role'], row['axes'], LABELS[source], detail))
    doc.add_heading('3.0 器件计算方式与数据来源', 2)
    paragraph(doc, '下表按本工况实际采用的模型记录来源，不能把已保存但停用的曲线当作计算依据。混合来源时，每个器件/曲线分别列出；导入曲线不会自动使其余器件变成精细模型。')
    table(doc, ['器件与计算项', '曲线坐标（基本单位）', '实际来源', '使用或保留的数据'], rows, [1.8, 1.7, 1.0, 2.6])
    paragraph(doc, '精细计算仅指相应器件损耗采用曲线查值。MOS 平台仍是静态/脉冲栅压近似；四事件可复用同一参考栅电荷曲线。二极管曲线仅用于损耗后处理，换流/环路仍用固定 Vf 近似。整理量、端点外推及其他模型限制见各器件的计算说明。', True)
