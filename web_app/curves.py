"""Uploaded text adapters. Never accept a server-side source path."""
import copy
import hashlib
import json
from pathlib import Path
import tempfile


def candidates(filename, content, target):
    suffix = Path(filename).suffix.lower()
    if suffix not in ('.json', '.csv') or len(content.encode('utf-8')) > 5 * 1024 * 1024:
        raise ValueError('仅支持不超过 5 MiB 的 CSV / JSON 曲线')
    source = dict(filename=Path(filename).name[:150], sha256=hashlib.sha256(content.encode('utf-8')).hexdigest())
    with tempfile.TemporaryDirectory(prefix='power-curve-') as directory:
        path = Path(directory)/('upload' + suffix)
        path.write_text(content, encoding='utf-8')
        from simple_curves import read_simple
        simple = read_simple(path)
        if simple is not None:
            return dict(simple=True, curves=simple['curves'], source=source)
        if target == 'Q1:transfer':
            from mos_curves import read_curve_candidates
            curves = read_curve_candidates(path)
        elif target == 'Q1:charge':
            from mos_gate_charge import read_charge_candidates
            curves = read_charge_candidates(path)
        else:
            from diode_curves import validate_curve
            data = json.loads(content)
            curves = [validate_curve(data)]
    return dict(simple=False, curves=curves, source=source)


def inspect_curve(filename, content, target):
    data = candidates(filename, content, target)
    result = []
    for index, curve in enumerate(data['curves']):
        suggestion = None
        if target == 'Q1:charge' and data['simple']:
            try:
                from mos_gate_charge import suggest_plateau
                suggestion = list(suggest_plateau(curve['points']))
            except ValueError:
                pass
        rows = curve.get('curves') or [curve]
        samples = []
        for row in rows[:12]:
            points = row.get('points',[])
            stride = max(1,(len(points)+699)//700)
            sampled = points[::stride]
            if points and sampled[-1] != points[-1]:sampled=sampled+[points[-1]]
            samples.append(dict(name=row.get('name',str(row.get('Vgs','曲线'))),points=sampled))
        result.append(dict(index=index, name=curve.get('name', f'曲线 {index+1}'),
                           points=sum(len(row.get('points',[])) for row in rows), plateau=suggestion,
                           sample_curves=samples))
    return dict(simple=data['simple'], curves=result, source=data['source'])


def apply_curve(spec, filename, content, target, index=0, x_multiplier=1., y_multiplier=1.,
                plateau_start=None, plateau_end=None):
    import math
    from device_curve_sources import targets, inferred_settings
    from config_io import decode_config
    from power_stage import DEFAULT_PARAMS
    p = dict(copy.deepcopy(DEFAULT_PARAMS), **decode_config(spec))
    if target not in {row['target'] for row in targets(p)}:
        raise ValueError('该位号不属于当前拓扑/输出配置，请重新选择导入对象')
    for scale in (x_multiplier, y_multiplier):
        if not math.isfinite(scale) or scale <= 0:
            raise ValueError('坐标数量级必须为有限正数')
    data = candidates(filename, content, target)
    if not 0 <= index < len(data['curves']):
        raise ValueError('请选择文件中实际存在的曲线')
    curve = data['curves'][index]
    if data['simple']:
        if target == 'Q1:transfer':
            from simple_curves import to_transfer
            curve = to_transfer(curve, x_multiplier, y_multiplier, source=data['source'])
        elif target == 'Q1:charge':
            from simple_curves import to_charge
            if plateau_start is None or plateau_end is None:
                raise ValueError('请核对并确认栅电荷曲线的米勒平台起止电荷')
            curve = to_charge(curve, x_multiplier, y_multiplier, start=plateau_start,
                              end=plateau_end, source=data['source'])
        else:
            from diode_curves import from_xy
            curve = from_xy(curve, x_multiplier, y_multiplier, source=data['source'])
    else:
        # Structured legacy files already declare SI coordinates; never scale twice.
        if x_multiplier != 1. or y_multiplier != 1.:
            raise ValueError('该文件为带结构的 SI 曲线，X/Y 数量级均应选 1')
        curve = copy.deepcopy(curve)
        curve['source' if target.startswith('D') else 'import_file'] = data['source']
    result = copy.deepcopy(spec)
    if target == 'Q1:transfer':
        result.update(mos_miller_curve=curve, mos_miller_mode='curve')
    elif target == 'Q1:charge':
        result.update(mos_charge_curve=curve, mos_charge_mode='curve')
    else:
        result.setdefault('diode_curves', {})[target] = curve
    settings = inferred_settings(p)
    settings['overrides'][target] = 'curve'
    result['device_curve_settings'] = settings
    return dict(spec=result, curve=curve, target=target)
