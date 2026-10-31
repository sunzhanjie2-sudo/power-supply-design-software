"""Custom effective core geometry. Calculations always use SI dimensions."""
import copy
import math

CUSTOM_CORE = '自定义（非标准）'
DIMENSIONS = {
    'Ae': ('有效截面积 Ae', {'mm²': 1e-6, 'cm²': 1e-4, 'm²': 1.}),
    'Ve': ('有效磁芯体积 Ve', {'mm³': 1e-9, 'cm³': 1e-6, 'm³': 1.}),
    'Wa': ('可用窗口面积 Wa', {'mm²': 1e-6, 'cm²': 1e-4, 'm²': 1.}),
    'MLT': ('平均每匝长度 MLT', {'mm': 1e-3, 'cm': 1e-2, 'm': 1.}),
}
DISPLAY_UNITS = dict(Ae='mm²', Ve='cm³', Wa='mm²', MLT='mm')


def is_custom(choice):
    return choice in (CUSTOM_CORE, 'CUSTOM', 'custom')


def validate_geometry(data):
    if not isinstance(data, dict):
        raise ValueError('自定义磁芯尺寸必须为参数字典')
    unknown=set(data)-set(DIMENSIONS)-{'name','display_units'}
    if unknown:raise ValueError('自定义磁芯包含未知字段：'+str(sorted(unknown)))
    result={'name':str(data.get('name','')).strip()[:48]}
    for key,(label,units) in DIMENSIONS.items():
        raw=data.get(key)
        factor=1.
        if isinstance(raw,dict):
            if set(raw)-{'v','u'}:raise ValueError(label+' 单位数据无效')
            unit=str(raw.get('u',''))
            if unit not in units:raise ValueError(label+' 单位应为 '+ ' / '.join(units))
            factor=units[unit];raw=raw.get('v')
        if isinstance(raw,bool) or not isinstance(raw,(int,float)) or not math.isfinite(raw) or raw<=0:
            raise ValueError('自定义磁芯 '+label+' 必须填写有限正数；不会回退标准磁芯')
        result[key]=float(raw)*factor
        if not math.isfinite(result[key]) or result[key]<=0:raise ValueError(label+' 换算后无效')
    selected=data.get('display_units',{})
    if not isinstance(selected,dict) or set(selected)-set(DIMENSIONS):
        raise ValueError('自定义磁芯显示单位无效')
    result['display_units']=dict(DISPLAY_UNITS)
    for key,unit in selected.items():
        if unit not in DIMENSIONS[key][1]:raise ValueError(DIMENSIONS[key][0]+' 显示单位无效')
        result['display_units'][key]=unit
    return result


def validate_selected_cores(p):
    """Inactive custom drafts never affect a standard core calculation."""
    owner='_fixed_transformer' if p.get('topology') in ('FLYBACK','QR-FLYBACK','ACF-FORWARD') else '_fixed_inductor'
    if is_custom(p.get('core_choice')) and not (p.get(owner) or {}).get('core_geometry'):
        validate_geometry(p.get('custom_core',{}))
    if p.get('topology')=='ACF-FORWARD' and not p.get('outputs') and is_custom(p.get('core_choice_L')) and not (p.get('_fixed_inductor') or {}).get('core_geometry'):
        validate_geometry(p.get('custom_core_L',{}))


def geometry_snapshot(core):
    """Own the snapshot: changing a draft must not change pinned hardware."""
    return copy.deepcopy(core)
