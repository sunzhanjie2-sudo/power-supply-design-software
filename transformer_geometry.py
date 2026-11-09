"""Resolve the calculator's winding cross-section into a versioned CAD exchange."""
import hashlib
import json
from pathlib import Path

from design_engine.contracts import content_hash, json_value
from transformer_geometry_contract import (BOBBIN, CORE, GEOMETRY, GEOMETRY_SCHEMA, PACKAGE, PROFILE_SCHEMA,
    PORT, VERSION, LEGACY_GEOMETRY_SCHEMA, PRE_PARALLEL_GEOMETRY_SCHEMA,PRE_PARALLEL_LEGACY_GEOMETRY_SCHEMA,
    profile_template, validate_profile, validate_schema)
from winding_layout import assess_winding_window, iter_bundle_sections, transformer_windings

MAX_DETAILED_BUNDLES=100000
MAX_PACKAGE_BYTES=256*1024**2


def json_bytes(value):
    return (json.dumps(value,ensure_ascii=False,allow_nan=False,indent=2)+'\n').encode('utf-8')


def strict_json(raw):
    def pairs(items):
        values={}
        for key,value in items:
            if key in values: raise ValueError(f'JSON 键重复：{key}')
            values[key]=value
        return values
    def reject(value):
        raise ValueError('JSON 不允许 '+value)
    return json.loads(raw.decode('utf-8-sig'),object_pairs_hook=pairs,parse_constant=reject)


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


def _physical(wires,assessment,tr,profile,frame,bobbin,missing,cancelled):
    by_winding={r['id']:r for r in assessment['windings']}
    detail=(assessment['configured'] and assessment['physical_layers'] is not None
            and assessment['bundle_count']<=MAX_DETAILED_BUNDLES)
    layers=assessment['physical_layers'] if detail else []
    if not assessment['configured']: missing.append('winding_config.window_width/window_height')
    elif not detail: missing.append('cross_section.detail_exceeds_export_limit')
    s_profiles=profile.get('sections',{})
    if detail and (unknown:=set(s_profiles)-{s['section_id'] for s in layers}):
        raise ValueError('接线配置包含已删除的段：'+', '.join(sorted(unknown)))
    # Consume the same per-winding box iterator as the equal-aspect plot.
    boxes={key:iter(iter_bundle_sections(row,assessment['config'])) for key,row in by_winding.items()} if detail else {}
    physical=[]
    for layer in layers:
        if cancelled and cancelled():
            from calculation_scheduler import CalculationCancelled
            raise CalculationCancelled()
        key=layer['winding_id']; sid=layer['section_id']; row=by_winding[key]
        count=int(layer['turns']); origin=s_profiles.get(sid,{})
        if origin and (origin['winding_id']!=key or origin['turns']!=count):
            raise ValueError(f'{sid} 的绕组或匝数发生变化，请复核并更新段接线配置')
        pins={k:origin.get(k) for k in ('start_node','end_node','dot_node','direction','source')}
        pins['status']=origin.get('status','unconfirmed')
        for name in ('start_node','end_node','dot_node','direction'):
            if not pins[name]: missing.append(f'sections.{sid}.{name}')
        if pins['status']=='unconfirmed': missing.append(f'sections.{sid}.status')
        bundles=[]
        for ti in range(1,count+1):
            for bi in range(1,row['parallel_bundles']+1):
                u,v,width,height=next(boxes[key])
                center=[u+width/2,v+height/2]
                rz=None
                if bobbin['winding_route_type']=='circular' and frame['z0_m'] is not None and frame['r0_m_if_circular'] is not None:
                    rz=[frame['r0_m_if_circular']+center[1],frame['z0_m']+center[0]]
                rectangle=row['layout_model']=='legacy_rectangular'
                bundles.append(dict(turn_id=f'{sid}.T{ti}',parallel_bundle_id=f'{key}.B{bi}',
                    turn_index_in_layer_one_based=ti,parallel_bundle_index_one_based=bi,
                    bbox_uv_m=[u,v,width,height],center_uv_m=center,profile_type='rectangle' if rectangle else 'ellipse',
                    corner_radius_m=0. if rectangle else None,center_rz_m=rz))
        physical.append(dict(section_id=sid,winding_id=key,layer_index_one_based=layer['layer_index'],turns=count,
            winding_style=layer['winding_style'],insulation_before_m=layer['insulation_before'],insulation_kind=layer['insulation_kind'],
            layer_envelope_uv_m=[layer['x'],layer['y'],layer['width'],layer['height']],occupied_width_m=layer['occupied_width'],
            route_ref='bobbin' if bobbin['winding_route_type'] else None,**pins,bundles=bundles))
    if any(next(it,None) is not None for it in boxes.values()):
        raise ValueError('逐匝截面数量与已解析物理段不一致')
    dc={'P':tr['R_dc_p'],'OUT1':tr['R_dc_s']}
    dc.update({f"OUT{w['id']}":w['R_dc'] for w in tr.get('windings',[])})
    if tr.get('auxiliary'): dc['AUX']=tr['auxiliary'].get('R_dc')
    windings=[]
    if set(profile.get('wire_evidence',{}))-{w['id'] for w in wires}:
        raise ValueError('线束公差引用了不存在的绕组')
    for wire in wires:
        key=wire['id']; row=by_winding.get(key,{})
        found=[s for s in physical if s['winding_id']==key]
        measured=assessment['config']['overrides'].get(key,{}).get('bundle_diameter',0)
        basis='user_supplied_outer_diameter' if measured else 'calculator_estimate' if row else 'unavailable'
        windings.append(dict(id=key,turns=int(wire['turns']),bare_strand_diameter_m=wire['bare_diameter'],
            strands=int(wire['strands']*wire.get('parallel_wires',1)),insulated_strand_diameter_m=row.get('outer_diameter'),
            parallel_bundles=row.get('parallel_bundles'),strands_per_bundle=row.get('strands_per_bundle'),
            bundle_width_m=row.get('bundle_width'),bundle_height_m=row.get('bundle_height'),bundle_dimension_basis=basis,
            unflattened_bundle_diameter_m=row.get('bundle_diameter') if row.get('layout_model')=='equivalent' else None,
            flatten_ratio=row.get('flatten_ratio') if row.get('layout_model')=='equivalent' else None,
            wire_type=row.get('wire_type'),wire_evidence=profile.get('wire_evidence',{}).get(key),
            bundle_packing_factor=row.get('packing_factor'),
            sum_layer_envelope_height_m=sum(s['layer_envelope_uv_m'][3] for s in found) if found else None,
            stack_buildup_m=row.get('buildup'),first_to_last_span_m=row.get('stack_span'),
            section_ids=[s['section_id'] for s in found],dcr_ohm=dc.get(key)))
        if wire.get('parallel_wires',1)>1:
            windings[-1].update(parallel_wires=wire['parallel_wires'],strands_per_wire=wire['strands'],
                                bundles_per_wire=row.get('bundles_per_wire'))
    return windings,physical


def _geometry_hash(g):
    return content_hash({k:g[k] for k in ('schema','units','frame','core','bobbin','bbox_convention',
                                          'windings','physical_sections','connections','connection_matrix','terminals','leads')})


def resolve_geometry(cases,snapshot_id,input_hash,design_id,profile=None,*,cancelled=None):
    if ([c.get('id') for c in cases]!=['Vinmin','Vinmax']
            or any(c.get('error') or not c.get('result') for c in cases)):
        raise ValueError('输入端点计算不完整，不能绑定几何快照')
    case=cases[0];p=case['p'];cfg=p.get('winding_config')
    if [c['voltage'] for c in cases]!=[p.get('V_in_min',p['V_in']),p.get('V_in_max',p['V_in'])]:
        raise ValueError('端点电压与设计规格不一致')
    if p['topology'] not in ('FLYBACK','QR-FLYBACK','ACF-FORWARD'):
        raise ValueError('当前拓扑没有隔离变压器')
    wires=transformer_windings(case['result'])
    if not wires: raise ValueError('未得到有效变压器，无法导出')
    tr=case['result']['mag']['transformer']
    assessment=assess_winding_window(wires,cfg)
    for other in cases[1:]:
        other_tr=other['result']['mag']['transformer']
        if (assess_winding_window(transformer_windings(other['result']),other['p'].get('winding_config'))!=assessment
                or transformer_windings(other['result'])!=wires or other_tr['core']!=tr['core']
                or other_tr['MLT']!=tr['MLT'] or other_tr['core_geometry']!=tr['core_geometry']):
            raise ValueError('输入端点的绕组或磁芯几何不一致，不能合并导出')
    profile=profile if profile is not None else (cfg or {}).get('model_3d') or profile_template()
    validate_profile(profile)
    frame=dict(origin='core_mating_plane_center',winding_axis='Z',handedness='right',local_u='axial',local_v='radial',
               z0_m=None,r0_m_if_circular=None)
    frame.update(profile.get('frame',{}))
    core=dict.fromkeys(CORE);core.update(profile.get('core',{}))
    core.update(calculator_core=tr['core'],calculator_material=p['core_material'],mean_length_per_turn_m=tr['MLT'])
    bobbin=dict.fromkeys(BOBBIN);bobbin.update(status='unconfirmed')
    bobbin.update(profile.get('bobbin',{}))
    bobbin.update(axial_window_m=assessment['config']['window_width'] or None,
                  radial_window_m=assessment['config']['window_height'] or None)
    missing=[]
    if frame['z0_m'] is None: missing.append('frame.z0_m')
    route=bobbin['winding_route_type']
    if not route: missing.append('bobbin.winding_route_type')
    elif route=='circular' and frame['r0_m_if_circular'] is None: missing.append('frame.r0_m_if_circular')
    elif route=='rounded_rectangle' and not bobbin['rounded_rectangle_m']: missing.append('bobbin.rounded_rectangle_m')
    elif route=='custom_closed' and not bobbin['winding_path_xy_m']: missing.append('bobbin.winding_path_xy_m')
    if bobbin['status']=='unconfirmed': missing.append('bobbin.status')
    windings,sections=_physical(wires,assessment,tr,profile,frame,bobbin,missing,cancelled)
    ports,matrix=_assemble_connections(windings,sections,profile if sections else {},missing)
    if assessment['fits'] is False: missing.append('winding_config.window_fit')
    ready_3d=bool(sections) and not missing
    for key in ('geometry_reference','geometry_sha256','material_reference','gap_geometry'):
        if core[key] is None: missing.append('core.'+key)
    for port in ports:
        if port['reduction_status'] in ('tap_requires_circuit','parallel_requires_circuit'):
            missing.append('electromagnetic.ports.'+port['winding_id']+'.current_constraints')
    if not profile.get('leads'): missing.append('leads')
    missing.extend(['electromagnetic.material_and_bias_model','electromagnetic.mesh_and_convergence'])
    from winding_coupling import validate_coupling_config
    power_ids=[w['id'] for w in windings if w['id']!='AUX']
    coupling=p.get('coupling_config') or {}
    matrix_k=coupling.get('k') or None
    if coupling.get('enabled') or (matrix_k and len(matrix_k)==len(power_ids)):
        matrix_k=validate_coupling_config(coupling,len(power_ids)-1)['K'].tolist()
    else: matrix_k=None
    conditions=[]
    for c in cases:
        op=c['result']['op']
        conditions.append(dict(case=c['id'],vin_V=c['voltage'],frequency_Hz=op['f_sw'],mode=op['mode'],primary_peak_A=op['I_sw_pk']))
    g=json_value(dict(schema=GEOMETRY,units='SI',source=dict(design_id=design_id,input_sha256=input_hash,
        engine_snapshot_id=snapshot_id,engine_kind='python',geometry_algorithm_version=VERSION),
        frame=frame,core=core,bobbin=bobbin,bbox_convention='[u_min,v_min,width,height]; ellipse dimensions are full diameters',
        windings=windings,physical_sections=sections,connections=ports,connection_matrix=matrix,
        terminals=profile.get('terminals',[]),leads=profile.get('leads',[]),
        assumptions=['图中挡墙为示意；线束尺寸默认按等效包络估算。','轨迹从 +Z 看按逆时针定义，v 沿内边界外法向，电气正电流流入同名端。',
                     *profile.get('assumptions',[])],
        checks=dict(two_dimensional_fit=assessment['fits'],height_margin_m=assessment.get('height_margin'),
                    same_endpoint_geometry=True,three_dimensional_interference='not_run',mesh='not_run',
                    electromagnetic_convergence='not_run',measurement_comparison='not_run'),
        ready=dict(cross_section=bool(sections),geometry_3d=ready_3d,electromagnetic=False),
        missing_fields=missing,operating_points=conditions,
        design_targets=dict(primary_self_inductance_H=p['Lm_forward'] if p['topology']=='ACF-FORWARD' else p['L'],
            coupling_enabled=bool(coupling.get('enabled')),coupling_order=power_ids if matrix_k else [],
            coupling_k=matrix_k,provenance='calculator_input_not_extracted')))
    if tr.get('gap_design'):
        g['design_targets']['air_gap']=json_value(tr['gap_design'])
    g['source']['geometry_sha256']=_geometry_hash(g)
    validate_geometry(g)
    return g,assessment


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


def _plots(assessment):
    from io import BytesIO
    from matplotlib.figure import Figure
    from matplotlib.backends.backend_agg import FigureCanvasAgg
    from matplotlib.text import Text
    from winding_layout import draw_winding_cross_section
    fig=Figure(figsize=(12.5,5.5),layout='constrained')
    FigureCanvasAgg(fig)
    draw_winding_cross_section(fig.subplots(),assessment)
    for artist in fig.findobj(Text):
        artist.set_fontfamily(['Microsoft YaHei','DejaVu Sans'])
    for fmt in ('svg','png'):
        buf=BytesIO()
        fig.savefig(buf,format=fmt,dpi=160,metadata={'Date':None} if fmt=='svg' else None)
        yield 'cross-section.'+fmt,buf.getvalue()
    fig.clear()


def export_geometry_package(run,path,config,*,original_bytes=None,original_name=None,profile=None,cancelled=None):
    """Atomically publish one package; pictures, dimensions and source share the given run."""
    import os
    import tempfile
    from zipfile import ZipFile,ZIP_DEFLATED
    from calculation_scheduler import CalculationCancelled
    from design_engine.service import validate_spec
    def check():
        if cancelled and cancelled(): raise CalculationCancelled()
    check()
    if run.analysis!='endpoints': raise ValueError('三维建模需要双端点计算快照')
    snapshot=run.to_dict(include_waveforms=False)
    normalized=validate_spec(config)
    if not normalized['ok'] or normalized['spec']!=snapshot['spec']:
        raise ValueError('原工程与计算快照不符，请用当前工程重新计算')
    if not snapshot['ok']: raise ValueError('双端点设计快照不完整，无法导出几何')
    bundle=run.runtime_bundle()
    raw=json_bytes(config)
    origin='working_copy'
    original=None
    if original_bytes is not None:
        original= strict_json(original_bytes)
        if not isinstance(original,dict): raise ValueError('原始来源应为 JSON 工程')
        # JSON-level equality also retains UI metadata and display units.
        if original==config:
            raw=original_bytes
            origin='original_bytes'
    name=Path(original_name or '').name or str(config.get('__web_project_title') or 'T1')
    digest=lambda data:hashlib.sha256(data).hexdigest()
    g,assessment=resolve_geometry(bundle['cases'],snapshot['snapshot_id'],digest(raw),name,profile,cancelled=cancelled)
    supplied=profile if profile is not None else (snapshot['spec'].get('winding_config') or {}).get('model_3d')
    template=profile_template(g['physical_sections'])
    files={'calculator-input.json':raw,'engine-snapshot.json':json_bytes(snapshot),
           'resolved-cross-section.json':json_bytes(g),'geometry.schema.json':json_bytes(GEOMETRY_SCHEMA),
           'model-input.template.json':json_bytes(template),'model-input.schema.json':json_bytes(PROFILE_SCHEMA)}
    if supplied is not None: files['model-input.json']=json_bytes(supplied)
    if original_bytes is not None and origin!='original_bytes':
        files['source-input.original.json']=original_bytes
    check()
    files.update(_plots(assessment))
    manifest=dict(schema=PACKAGE,engine_snapshot_id=snapshot['snapshot_id'],geometry_sha256=g['source']['geometry_sha256'],
        input_sha256=digest(raw),input_kind=origin,original_name=Path(original_name).name if original_name else None,
        original_sha256=digest(original_bytes) if original_bytes is not None else None,
        geometry_algorithm_version=VERSION,files={n:dict(sha256=digest(b),bytes=len(b)) for n,b in files.items()})
    manifest['normalized_spec_sha256']=content_hash(snapshot['spec'])
    manifest['engine_model_version']=snapshot['model_version']
    manifest_bytes=json_bytes(manifest)
    if sum(map(len,files.values()))+len(manifest_bytes)>MAX_PACKAGE_BYTES:
        raise ValueError('几何包超过 256 MiB 的无压缩读取上限，请减少逐匝规模')
    path=Path(path)
    if path.suffix.lower()!='.zip': raise ValueError('三维建模数据包需要 .zip 后缀')
    handle,tmp=tempfile.mkstemp(prefix='.geometry-',suffix='.tmp',dir=path.parent)
    os.close(handle)
    try:
        with ZipFile(tmp,'w',ZIP_DEFLATED,compresslevel=5) as z:
            for n,data in files.items():
                check()
                z.writestr(n,data)
            z.writestr('manifest.json',manifest_bytes)
        check()
        os.replace(tmp,path)
    finally:
        Path(tmp).unlink(missing_ok=True)
    return dict(ready=g['ready'],missing_fields=g['missing_fields'],snapshot_id=snapshot['snapshot_id'],
                geometry_sha256=g['source']['geometry_sha256'],sections=len(g['physical_sections']),
                bundles=sum(len(s['bundles']) for s in g['physical_sections']),input_kind=origin)


def read_geometry_package(path):
    """Verify a ZIP without ever extracting file paths or following references."""
    from zipfile import ZipFile
    from design_engine import CONTRACT_VERSION
    required={'calculator-input.json','engine-snapshot.json','resolved-cross-section.json','geometry.schema.json',
              'cross-section.svg','cross-section.png','model-input.template.json','model-input.schema.json'}
    with ZipFile(path) as z:
        names=z.namelist()
        allowed=required|{'manifest.json','model-input.json','source-input.original.json'}
        if not (required|{'manifest.json'}).issubset(names) or set(names)-allowed or len(names)!=len(set(names)):
            raise ValueError('数据包含缺失、重复或未知文件')
        if sum(i.file_size for i in z.infolist())>MAX_PACKAGE_BYTES: raise ValueError('几何数据包超过读取上限')
        manifest=strict_json(z.read('manifest.json'))
        if manifest.get('schema')!=PACKAGE or set(manifest.get('files',{}))!=set(names)-{'manifest.json'}:
            raise ValueError('不支持的包版本或清单条目不匹配')
        for n,seal in manifest['files'].items():
            data=z.read(n)
            if seal!={'sha256':hashlib.sha256(data).hexdigest(),'bytes':len(data)}: raise ValueError(n+' 源清单校验失败')
        if strict_json(z.read('geometry.schema.json')) not in (GEOMETRY_SCHEMA,LEGACY_GEOMETRY_SCHEMA,
                PRE_PARALLEL_GEOMETRY_SCHEMA,PRE_PARALLEL_LEGACY_GEOMETRY_SCHEMA) or strict_json(z.read('model-input.schema.json'))!=PROFILE_SCHEMA:
            raise ValueError('接口 Schema 不匹配')
        for n in ('model-input.json','model-input.template.json'):
            if n in names: validate_profile(strict_json(z.read(n)))
        g=validate_geometry(strict_json(z.read('resolved-cross-section.json')))
        snap=strict_json(z.read('engine-snapshot.json'))
        snap_id=content_hash({k:v for k,v in snap.items() if k not in ('snapshot_id','created_at')})
        if snap.get('schema')!=CONTRACT_VERSION or not snap.get('ok') or snap.get('analysis')!='endpoints':
            raise ValueError('计算快照无效')
        for k,expected in [('engine_snapshot_id',snap_id),('input_sha256',manifest['files']['calculator-input.json']['sha256']),
                           ('geometry_sha256',_geometry_hash(g))]:
            if g['source'][k]!=expected or manifest.get(k)!=expected: raise ValueError(k+' 绑定不一致')
        if snap['snapshot_id']!=snap_id: raise ValueError('引擎快照哈希不符')
        if manifest.get('normalized_spec_sha256')!=content_hash(snap['spec']) or manifest.get('engine_model_version')!=snap['model_version']:
            raise ValueError('计算输入或引擎版本绑定不一致')
        if manifest.get('input_kind') not in ('original_bytes','working_copy'): raise ValueError('未知输入来源')
        original_path='source-input.original.json' if 'source-input.original.json' in names else 'calculator-input.json' if manifest['input_kind']=='original_bytes' else None
        if manifest.get('original_sha256')!=(manifest['files'][original_path]['sha256'] if original_path else None):
            raise ValueError('原始工程哈希不符')
        from design_engine.service import validate_spec
        from config_io import decode_config
        # An old file may omit a parameter whose application default later changed.
        # The frozen complete spec supplies that run's defaults, while explicit file values win.
        original_config=decode_config(strict_json(z.read('calculator-input.json')))
        active=validate_spec(dict(snap['spec'],**original_config))
        saved=validate_spec(snap['spec'])
        if not active['ok'] or not saved['ok'] or active['spec']!=saved['spec']:
            raise ValueError('输入工程与快照所用的规格不符')
        cases=[dict(id=c['id'],voltage=c['V_in'],p=c['parameters'],result=c['result'],error=c.get('error'))
               for c in snap['cases']]
        profile=strict_json(z.read('model-input.json')) if 'model-input.json' in names else None
        # Reproject the stored magnetic results, without running a converter
        # solve. This also catches geometry accidentally paired with other rails.
        expected,_=resolve_geometry(cases,snap_id,g['source']['input_sha256'],g['source']['design_id'],profile)
        if expected!=g: raise ValueError('几何、工况或就绪标志与包内已冻结的计算结果不符')
        return g
