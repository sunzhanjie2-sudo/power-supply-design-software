"""Shared Word blocks, also captured as the dedicated XLSX BOM module."""
from component_management import evaluate_components, STATUS, rating_text


def add_component_report(doc, p, res):
    from docx_layout import section, paragraph, table
    data = evaluate_components(p, res)
    section(doc, '1.4  关键器件 BOM 与降额初筛')
    paragraph(doc, f"规则来源：{data['source']}；{data['zone']} 区。{data['note']}")
    paragraph(doc, '器件使用率=模型应力/额定值；允许应力=降额因数×额定值。资料留空不是零，待补充不能判通过。'
              '同一颗电容的纹波额定值须按实际频率、温度及寿命条件修正后填写；厂家/型号不自动推导电气参数。')
    table(doc, ['位号 / 数量', '用途', '厂家', '型号', '封装', '额定参数'], [
        (r['ref']+(' / 1' if r['quantity'] else ' / 参考'), r['role'], r.get('manufacturer') or '待填',
         r.get('model') or '待填', r.get('package') or '待填', rating_text(r)) for r in data['rows']],
        [.7, 1.4, .8, 1.2, .9, 2.])
    def number(x, unit=''):
        return '待补充' if x is None else f'{x:.4g}{unit}'
    table(doc, ['位号 / 检查项', '实际应力', '额定值', '使用率', '限值 / 因数', '结论'], [
        (c['name'], number(c['value'], c['unit']), number(c['rating'], c['unit']),
         '—' if c['utilization'] is None else f"{c['utilization']:.1%}",
         number(c['limit'], c['unit'])+' / '+('未定义' if c['factor'] is None else f"{c['factor']:.0%}"),
         STATUS[c['state']]) for c in data['checks']], [1.7, 1., 1., .8, 1.5, 1.])
    table(doc, ['位号 / 检查项', '依据与限制'], [
        (c['name'], c['source']+'；'+c['note']) for c in data['checks']], [1.5, 5.5])
    notes = [(r['ref'], '；'.join(filter(None, [
        '资料缺失：'+ '/'.join(r['identity_missing']) if r['identity_missing'] else '',
        r.get('conditions'), r.get('note')]))) for r in data['rows']]
    if any(text for _,text in notes):
        table(doc, ['位号', '额定条件 / 资料待办'], [(r,t) for r,t in notes if t], [.9, 6.1])
    paragraph(doc, data['scope']+'。未展开的驱动、补偿、控制电源不自动生成虚构物料；虚拟负载不计 BOM。', True)
