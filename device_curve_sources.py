"""Explicit loss-model source selection; numerical formulas live elsewhere.

The saved curve banks are never modified.  Only a calculation-local copy is
filtered, so switching to fixed values does not destroy imported data.
"""
import copy
import re

TRANSFER = 'Q1:transfer'
CHARGE = 'Q1:charge'
LABELS = {'fixed': '固定值', 'curve': '曲线', 'legacy': '旧跨导兼容'}


def validate_settings(data):
    if not data:
        if data is None or data == {}:
            return {}
        raise ValueError('器件计算来源设置须为对象')
    if not isinstance(data, dict) or set(data) - {'mode', 'overrides'}:
        raise ValueError('器件计算来源设置格式错误')
    if data.get('mode') not in ('fixed', 'curve'):
        raise ValueError('器件计算方式须为 fixed 或 curve')
    overrides = data.get('overrides', {})
    if not isinstance(overrides, dict) or len(overrides) > 25:
        raise ValueError('器件逐项来源设置格式错误')
    for target, source in overrides.items():
        if not isinstance(target, str) or not re.fullmatch(r'Q1:(transfer|charge)|D1|D2|D_IN|D_OUT|D_[OFB][1-6]', target):
            raise ValueError('未知曲线目标：' + str(target))
        if source not in ('fixed', 'curve') and not (target == TRANSFER and source == 'legacy'):
            raise ValueError('未知器件计算来源：' + str(source))
    return dict(mode=data['mode'], overrides=dict(overrides))


def source_for(p, target):
    settings = validate_settings(p.get('device_curve_settings', {}))
    if settings:
        return settings['overrides'].get(target, settings['mode'])
    if target == TRANSFER:
        mode = p.get('mos_miller_mode', 'auto')
        if mode == 'curve':
            return 'curve'
        return 'legacy' if mode == 'gfs' or (mode == 'auto' and p.get('gfs', 0) > 0) else 'fixed'
    if target == CHARGE:
        return 'curve' if p.get('mos_charge_mode') == 'curve' else 'fixed'
    return 'curve' if p.get('diode_curves', {}).get(target) else 'fixed'


def targets(p):
    from diode_curves import active_diodes
    family=p.get('mos_miller_curve',{}).get('kind')=='output_family'
    return [dict(target=TRANSFER, ref='Q1', role='主开关 · 米勒平台',
                 axes='X=Vds / V；Y=Id / A；按 Vgs 分组' if family else 'X=Vgs / V；Y=Id / A', kind='transfer'),
            dict(target=CHARGE, ref='Q1', role='主开关 · 栅电荷', axes='X=Qg / C；Y=Vgs / V', kind='charge')] + [
                dict(r, target=r['ref'], axes='X=Vf / V；Y=If / A') for r in active_diodes(p)]


def curve_for(p, target):
    if target == TRANSFER:
        return p.get('mos_miller_curve', {})
    if target == CHARGE:
        return p.get('mos_charge_curve', {})
    return p.get('diode_curves', {}).get(target, {})


def inferred_settings(p):
    """Freeze legacy behavior when the user first makes an explicit selection."""
    all_targets = [TRANSFER, CHARGE, 'D1', 'D2', 'D_IN', 'D_OUT'] + [
        f'D_{kind}{n}' for kind in 'OFB' for n in range(1, 7)]
    sources = {target: source_for(p, target) for target in all_targets}
    mode = 'curve' if any(source == 'curve' for source in sources.values()) else 'fixed'
    return dict(mode=mode, overrides={target: source for target, source in sources.items() if source != mode})


def validate_requests(p):
    validate_settings(p.get('device_curve_settings', {}))
    missing = [row['ref'] + ' · ' + row['role'] for row in targets(p)
               if source_for(p, row['target']) == 'curve' and not curve_for(p, row['target'])]
    if missing:
        raise ValueError('已选择曲线计算，但以下项目待导入：' + '；'.join(missing) +
                         '。请在左栏“器件计算方式与曲线”导入，或明确将该项改为固定值。')


def effective_sources(p):
    settings = validate_settings(p.get('device_curve_settings', {}))
    if not settings:
        return p
    validate_requests(p)
    result = dict(p)
    result['mos_miller_mode'] = {'fixed': 'manual', 'curve': 'curve', 'legacy': 'gfs'}[source_for(p, TRANSFER)]
    result['mos_charge_mode'] = 'curve' if source_for(p, CHARGE) == 'curve' else 'manual'
    result['diode_curves'] = {ref: curve for ref, curve in p.get('diode_curves', {}).items()
                              if source_for(p, ref) == 'curve'}
    return result


def source_summary(p):
    values = [source_for(p, row['target']) for row in targets(p)]
    if all(source == 'fixed' for source in values):
        return '固定值快速估算'
    if all(source == 'curve' for source in values):
        return '导入曲线精细计算'
    return '混合来源：部分曲线计算，部分固定值或旧模型估算'


def source_rows(p):
    """Small provenance ledger shared by the UI and both report formats."""
    return [dict(row, source=source_for(p, row['target']),
                 curve=copy.deepcopy(curve_for(p, row['target']))) for row in targets(p)]
