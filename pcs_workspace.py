"""Validated PCS power-tree contracts. Capacity accounting is not a converter solver."""
import copy
import math
import re

SCHEMA = 'pcs.aux-workspace/1'


def validate_project(value):
    from config_io import decode_config
    from power_units import load_unit, unit_rails
    if not isinstance(value, dict) or value.get('schema_version') != SCHEMA:
        raise ValueError('需要 pcs.aux-workspace/1 辅源工程')
    def name(text, maximum=120):
        if not isinstance(text, str) or not text.strip() or len(text) > maximum:
            raise ValueError('工程、单元和输入源名称必须为非空文本')
        return text.strip()
    def identity(text):
        if not isinstance(text, str) or not re.fullmatch(r'[A-Za-z0-9_-]{1,40}', text):
            raise ValueError('单元和输入源 ID 仅允许英文字母、数字、下划线及短横线')
        return text
    def positive(number):
        if isinstance(number, bool) or not isinstance(number, (int,float)) or not math.isfinite(number) or number <= 0:
            raise ValueError('输入源电压和容量必须为有限正数')
        return float(number)
    buses, units = value.get('sources'), value.get('units')
    if not isinstance(buses, list) or not 0 <= len(buses) <= 24 or not isinstance(units, list) or not 0 <= len(units) <= 24:
        raise ValueError('工程最多包含 24 个输入源及 24 个辅源单元')
    out = dict(schema_version=SCHEMA, title=name(value.get('title')), revision=name(value.get('revision','A'),30),
               sources=[], units=[], includeCrossRegulation=bool(value.get('includeCrossRegulation', False)))
    used = set()
    for b in buses:
        i=identity(b.get('id'))
        if i in used: raise ValueError('输入源与辅源 ID 必须各自唯一')
        used.add(i)
        lo, hi=positive(b.get('min')),positive(b.get('max'))
        if hi < lo: raise ValueError('输入源最大电压不得小于最小电压')
        out['sources'].append(dict(id=i,name=name(b.get('name')),min=lo,max=hi,capacity=positive(b.get('capacity'))))
    used = set()
    for u in units:
        i=identity(u.get('id'))
        if i in used: raise ValueError('辅源 ID 重复')
        used.add(i)
        source=u.get('source',{})
        if source.get('kind') not in ('bus','unit','none'): raise ValueError('辅源输入来源无效')
        port=source.get('output',1)
        if isinstance(port,bool) or not isinstance(port,int) or not 1<=port<=6: raise ValueError('上游端口需为 OUT1～OUT6')
        p=load_unit(u.get('spec',{}))
        rails=unit_rails(p)
        source_id='' if source['kind']=='none' else identity(source.get('id'))
        out['units'].append(dict(id=i,name=name(u.get('name')),source=dict(kind=source['kind'],id=source_id,output=port),spec=p,rails=rails))
    by_id={u['id']:u for u in out['units']}; buses={b['id']:b for b in out['sources']}
    if by_id.keys() & buses.keys(): raise ValueError('输入源与辅源单元不得使用相同 ID')
    for u in out['units']:
        s=u['source']
        if s['kind']=='none': continue
        if s['kind']=='bus':
            if s['id'] not in buses: raise ValueError(u['id']+' 的输入源不存在')
        elif s['id'] not in by_id or s['output']>len(by_id[s['id']]['rails']):
            raise ValueError(u['id']+' 的上游单元或输出端口不存在')
        seen={u['id']}; current=u
        while current['source']['kind']=='unit':
            current=by_id[current['source']['id']]
            if current['id'] in seen: raise ValueError('辅源架构包含循环供电')
            seen.add(current['id'])
    out['activeUnit']=value.get('activeUnit') if value.get('activeUnit') in by_id else (out['units'][0]['id'] if out['units'] else '')
    positions=value.get('layout',{}).get('nodes',{})
    if not isinstance(positions,dict): raise ValueError('节点布局需为坐标映射')
    valid_keys={'bus:'+b['id'] for b in out['sources']}|{'unit:'+u['id'] for u in out['units']}
    layout={}
    for key,point in positions.items():
        if key not in valid_keys: continue
        if not isinstance(point,dict) or any(isinstance(point.get(axis),bool) or not isinstance(point.get(axis),(int,float)) or not math.isfinite(point[axis]) or not 0<=point[axis]<=10000 for axis in ('x','y')):
            raise ValueError('节点布局坐标无效')
        layout[key]={'x':float(point['x']),'y':float(point['y'])}
    out['layout']={'nodes':layout}
    return out


def capacity_checks(project):
    """Reserve child input power within its parent's configured output rating."""
    units={u['id']:u for u in project['units']}; buses={b['id']:b for b in project['sources']}
    from ldo import is_ldo,input_power
    demands={u['id']:(input_power(u['spec'],u['spec']['V_in_max']) if is_ldo(u['spec']) else sum(r['P_out'] for r in u['rails'])/u['spec']['eta_guess']) for u in units.values()}
    rows=[]
    def add(ref,capacity,used):
        rows.append(dict(port=ref,capacity=capacity,allocated=used,remaining=capacity-used,ok=used<=capacity+1e-9))
    for b in buses.values():
        add(b['id'],b['capacity'],sum(demands[u['id']] for u in units.values() if u['source']['kind']=='bus' and u['source']['id']==b['id']))
    for u in units.values():
        for i,r in enumerate(u['rails'],1):
            add(u['id']+'/OUT'+str(i),r['P_out'],sum(demands[v['id']] for v in units.values() if v['source']==dict(kind='unit',id=u['id'],output=i)))
    return rows


def interface_checks(project):
    units={u['id']:u for u in project['units']};buses={b['id']:b for b in project['sources']}
    rows=[]
    for u in project['units']:
        source=u['source']
        if source['kind']=='none':
            p=u['spec'];rows.append(dict(unit=u['id'],source_min=None,source_max=None,design_min=p.get('V_in_min',p['V_in']),design_max=p.get('V_in_max',p['V_in']),ok=False,note='输入尚未连接'));continue
        if source['kind']=='bus':lo,hi=buses[source['id']]['min'],buses[source['id']]['max']
        else:lo=hi=units[source['id']]['rails'][source['output']-1]['V_out']
        p=u['spec'];ok=p.get('V_in_min',p['V_in'])<=lo+1e-9 and p.get('V_in_max',p['V_in'])>=hi-1e-9
        rows.append(dict(unit=u['id'],source_min=lo,source_max=hi,design_min=p.get('V_in_min',p['V_in']),design_max=p.get('V_in_max',p['V_in']),ok=ok))
    return rows
