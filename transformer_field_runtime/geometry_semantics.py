"""Frozen geometry-only semantics; never imports the calculator engine."""
from .storage import content_hash
from .contract_v1 import BOBBIN, CORE, GEOMETRY, PORT, profile_template, validate_profile, validate_schema
def _assemble_connections(windings,sections,profile,missing):
    by_id={s['section_id']:s for s in sections}
    unknown=set(profile.get('ports',{}))-{w['id'] for w in windings}
    if unknown: raise ValueError('端口引用了不存在的绕组：'+', '.join(sorted(unknown)))
    terminals={t['node']:t for t in profile.get('terminals',[])}
    ports=[]
    for w in windings:
        key=w['id']
        p={k:None for k in PORT}
        p.update(section_order=[],status='unconfirmed')
        p.update({k:v for k,v in profile.get('ports',{}).get(key,{}).items() if k in PORT})
        order=p['section_order']
        if order and (len(set(order))!=len(order) or set(order)!=set(w['section_ids'])):
            raise ValueError(key+' 的连接顺序必须恰好覆盖本绕组全部物理段')
        coeff=None
        reduction='unresolved'
        if not order or not p['connection'] or not p['dot_node'] or not p['other_node'] or p['status']=='unconfirmed':
            missing.append('ports.'+key+'.connections')
        elif p['dot_node']==p['other_node']:
            raise ValueError(key+' 的两个端口节点不能相同')
        elif all(by_id[i]['start_node'] and by_id[i]['end_node'] and by_id[i]['dot_node']
                 and by_id[i]['status']!='unconfirmed' for i in order):
            node=p['dot_node']; signs=[];nodes=[node]
            for i in order:
                s=by_id[i]
                if p['connection']=='parallel': node=p['dot_node']
                a,b=s['start_node'],s['end_node']
                if node not in (a,b):
                    raise ValueError(f'{key} 的 {i} 不能从节点 {node} 接入')
                signs.append(1 if node==s['dot_node'] else -1)
                node=b if node==a else a
                nodes.append(node)
                if p['connection']=='parallel' and node!=p['other_node']:
                    raise ValueError(f'{i} 的并联支路终点与端口不符')
            if node!=p['other_node']: raise ValueError(key+' 的连接链没有到达另一端口')
            if p['connection']=='series':
                if len(set(nodes))!=len(nodes): raise ValueError(key+' 的串联路径包含重复节点')
                interior=nodes[1:-1]
                isolated=all(terminals.get(n,{}).get('external_connection')=='none' and
                             terminals[n]['status']!='unconfirmed' for n in interior)
                other_nodes={s[k] for s in sections if s['winding_id']!=key for k in ('start_node','end_node')}
                if isolated and not other_nodes.intersection(interior):
                    coeff=signs;reduction='series'
                else:
                    reduction='tap_requires_circuit'
            else:
                reduction='parallel_requires_circuit'
        effective=abs(sum(sign*by_id[i]['turns'] for sign,i in zip(coeff,order))) if coeff is not None else None
        match=effective==w['turns'] if effective is not None else None
        if match is False: missing.append('ports.'+key+'.effective_turns')
        ports.append(dict(winding_id=key,**p,series_coefficients=coeff,reduction_status=reduction,
                          effective_series_turns=effective,turns_match_calculator=match))
    order=list(by_id)
    matrix=None
    if ports and all(p['series_coefficients'] is not None for p in ports):
        columns=[dict(zip(p['section_order'],p['series_coefficients'])) for p in ports]
        matrix=[[col.get(sec,0) for col in columns] for sec in order]
    return ports,dict(row_sections=order,column_ports=[w['id'] for w in windings],values=matrix,
                      convention='i_sections=A*i_ports; L_ports=transpose(A)*L_sections*A')

def _geometry_hash(g):
    return content_hash({k:g[k] for k in ('schema','units','frame','core','bobbin','bbox_convention',
                                          'windings','physical_sections','connections','connection_matrix','terminals','leads')})

def validate_geometry(g):
    validate_schema(g,GEOMETRY)
    if g['source']['geometry_sha256']!=_geometry_hash(g): raise ValueError('几何内容哈希不符')
    wires={w['id']:w for w in g['windings']}
    for w in wires.values():
        if 'parallel_wires' in w and (w['strands']!=w['parallel_wires']*w.get('strands_per_wire',0)
                or w['parallel_bundles']!=w['parallel_wires']*w.get('bundles_per_wire',0)):
            raise ValueError('线圈并绕根数、单根股数与总铜线数不守恒')
    sections={s['section_id']:s for s in g['physical_sections']}
    if len(wires)!=len(g['windings']) or len(sections)!=len(g['physical_sections']):
        raise ValueError('绕组或物理段 ID 重复')
    for index,s in enumerate(g['physical_sections'],1):
        if s['winding_id'] not in wires or s['layer_index_one_based']!=index:
            raise ValueError('物理层的顺序或绕组引用不正确')
        w=wires[s['winding_id']];count=w['parallel_bundles']
        if not count or len(s['bundles'])!=s['turns']*count: raise ValueError('物理段匝数和并绕束数不守恒')
        for n,b in enumerate(s['bundles']):
            ti,bi=divmod(n,count)
            if (b['turn_index_in_layer_one_based'],b['parallel_bundle_index_one_based'],b['turn_id'],b['parallel_bundle_id'])!=(
                    ti+1,bi+1,f"{s['section_id']}.T{ti+1}",f"{w['id']}.B{bi+1}"):
                raise ValueError('逐匝编号或并绕束编号不一致')
            u,v,width,height=b['bbox_uv_m']
            if min(width,height)<=0 or b['center_uv_m']!=[u+width/2,v+height/2]:
                raise ValueError('线束中心或完整直径与包围盒不一致')
            rz=None;frame=g['frame']
            if g['bobbin']['winding_route_type']=='circular' and frame['r0_m_if_circular'] is not None and frame['z0_m'] is not None:
                rz=[frame['r0_m_if_circular']+b['center_uv_m'][1],frame['z0_m']+b['center_uv_m'][0]]
            if b['center_rz_m']!=rz: raise ValueError('圆形路径的全局 r/z 与局部 u/v 不一致')
    for key,w in wires.items():
        subset=[s for s in sections.values() if s['winding_id']==key]
        if [s['section_id'] for s in subset]!=w['section_ids'] or (g['ready']['cross_section'] and sum(s['turns'] for s in subset)!=w['turns']):
            raise ValueError(f'{key} 的物理段引用或总匝数不守恒')
    if g['ready']['cross_section']!=bool(sections): raise ValueError('二维截面就绪标志不一致')
    ports_by_id={p['winding_id']:p for p in g['connections']}
    if list(ports_by_id)!=list(wires) or len(g['connections'])!=len(wires): raise ValueError('电气端口顺序或数量不符')
    expected_ports,expected=_assemble_connections(list(wires.values()),list(sections.values()),
        dict(ports=ports_by_id,terminals=g['terminals']),[])
    if expected!=g['connection_matrix'] or expected_ports!=g['connections']:
        raise ValueError('连接矩阵的顺序、方向或系数不符')
    profile=dict(schema=profile_template()['schema'],frame={k:g['frame'][k] for k in ('z0_m','r0_m_if_circular')},
        bobbin={k:g['bobbin'][k] for k in BOBBIN},core={k:g['core'][k] for k in CORE},leads=g['leads'],terminals=g['terminals'],
        sections={key:{k:s[k] for k in ('winding_id','turns','start_node','end_node','dot_node','direction','source','status')}
                  for key,s in sections.items()},ports={key:{k:p[k] for k in PORT} for key,p in ports_by_id.items()})
    validate_profile(profile)
    nodes={t['node'] for t in g['terminals']}|{s[k] for s in sections.values() for k in ('start_node','end_node')}
    if any(lead['node'] not in nodes for lead in g['leads']): raise ValueError('引线引用了未声明的端子或段节点')
    b=g['bobbin'];frame=g['frame']
    route_data={'circular':frame['r0_m_if_circular'],'rounded_rectangle':b['rounded_rectangle_m'],
                'custom_closed':b['winding_path_xy_m']}.get(b['winding_route_type'])
    complete=bool(sections and g['checks']['two_dimensional_fit'] and frame['z0_m'] is not None and route_data
                  and b['status']!='unconfirmed' and all(s['direction'] and s['start_node'] and s['end_node'] and s['dot_node']
                  and s['status']!='unconfirmed' for s in sections.values()) and all(p['section_order'] and p['connection']
                  and p['dot_node'] and p['other_node'] and p['status']!='unconfirmed' and p['turns_match_calculator'] is not False for p in ports_by_id.values()))
    if g['ready']['geometry_3d']!=complete: raise ValueError('三维就绪标志与实际轨迹或接线不符')
    return g
