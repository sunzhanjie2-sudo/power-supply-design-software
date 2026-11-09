"""Per-section axial wire locations, independent of electrical calculations."""
import math
import re

MAX_POINTS=12000
SECTION=re.compile(r'[A-Za-z][A-Za-z0-9_-]{0,79}')
POINT=re.compile(r'[1-9][0-9]*:[1-9][0-9]*')


def validate(raw):
    if not isinstance(raw,dict):raise ValueError('turn_positions 必须为逐物理段的位置字典')
    if sum(len(v) if isinstance(v,dict) else MAX_POINTS+1 for v in raw.values())>MAX_POINTS:
        raise ValueError(f'逐匝位置最多支持 {MAX_POINTS} 个截面，不能静默截断')
    result={}
    for sid,entries in raw.items():
        if not isinstance(sid,str) or not SECTION.fullmatch(sid) or not isinstance(entries,dict):
            raise ValueError('逐匝位置必须使用有效的稳定段 ID')
        result[sid]={}
        for key,value in entries.items():
            if not isinstance(key,str) or not POINT.fullmatch(key):
                raise ValueError('逐匝位置键必须为 本层匝号:并绕束号（从 1 开始）')
            if isinstance(value,bool) or not isinstance(value,(int,float)) or not math.isfinite(value):
                raise ValueError('逐匝轴向中心必须为有限数值，内部单位 m')
            result[sid][key]=float(value)
    return result


def prepare(assessment):
    """Materialize bounded editable boxes and check margins/spacing after edits."""
    from winding_layout import iter_bundle_records
    cfg=assessment['config']
    assessment['cross_sections']=[]
    assessment['position_issues']=[]
    assessment['editable']=False
    if not assessment['configured'] or not assessment['windings']:return
    if (assessment['bundle_count']>MAX_POINTS or assessment['physical_layers'] is None
            or len(assessment['physical_layers'])>256):
        if cfg['turn_positions']:
            raise ValueError('截面数超过微调容量，请先缩小排布规模再应用逐匝位置')
        return
    sections=[s for row in assessment['windings'] for s in iter_bundle_records(row,cfg)]
    assessment['cross_sections']=sections
    assessment['editable']=True
    if not cfg['turn_positions']:return
    by_layer={};seen=set();bad=set();issues=[]
    for s in sections:
        sid=s['section_id'];pid=s['position_key'];seen.add((sid,pid))
        by_layer.setdefault(sid,[]).append(s)
        if s['x']<cfg['margin_x']-1e-12 or s['x']+s['width']>cfg['window_width']-cfg['margin_x']+1e-12:
            bad.add(s['id']);issues.append(f"{sid} 第 {s['turn']} 匝 / 束 {s['bundle']} 超出轴向留边")
    for sid,entries in cfg['turn_positions'].items():
        for key in entries:
            if (sid,key) not in seen:issues.append(f'{sid} 位置 {key} 已失效；请清除或重新排布后核对')
    for sid,points in by_layer.items():
        previous=None
        for s in sorted(points,key=lambda s:s['x']):
            if previous and previous['x']+previous['width']+cfg['wire_gap']>s['x']+1e-12:
                bad.update((previous['id'],s['id']))
                issues.append(f"{sid} 匝/束 {previous['position_key']} 与 {s['position_key']} 重叠或净隙不足")
            if previous is None or s['x']+s['width']>previous['x']+previous['width']:previous=s
    for s in sections:s['conflict']=s['id'] in bad
    for layer in assessment['physical_layers']:
        points=by_layer.get(layer['section_id'],[])
        if points:
            layer['x']=min(s['x'] for s in points)
            layer['width']=max(s['x']+s['width'] for s in points)-layer['x']
            layer['occupied_width']=layer['width']
            layer['horizontal_fit']=not any(s['id'] in bad for s in points)
    for row in assessment['windings']:
        entries=row.get('layer_layout') or []
        if entries:
            row['x']=min(e['x'] for e in entries)
            row['width']=max(e['x']+e['width'] for e in entries)-row['x']
            row['horizontal_fit']=all(e['horizontal_fit'] for e in entries)
    assessment['position_issues']=issues
    if issues:
        assessment['fits']=False;assessment['status']='position_conflict'
        assessment['warnings'][-1:-1]=issues


def freeze_plan(assessment):
    """Freeze the resolved layers before a user starts moving individual wires."""
    if not assessment.get('editable') or len(assessment.get('physical_layers') or [])>1000:
        raise ValueError('当前层数或截面数过多，不能进行逐匝编辑；请先调整窗口和线材')
    return [dict(section_id=e['section_id'],winding_id=e['winding_id'],turns=e['turns'],
                 winding_style=e['winding_style']) for e in assessment['physical_layers']]
