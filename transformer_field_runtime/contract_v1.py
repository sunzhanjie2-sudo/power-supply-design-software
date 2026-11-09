# Frozen private geometry interface; source provenance in vendor-provenance.json.
"""Portable JSON Schema and engineering checks shared by the writer and reader."""
from functools import lru_cache

GEOMETRY='power-transformer.geometry.v1'
PROFILE='power-transformer.model-input.v1'
PACKAGE='power-transformer.package.v1'
VERSION='winding-window/1.0'


def obj(properties, *, require_all=True):
    fields=dict(type='object',properties=properties,additionalProperties=False)
    if require_all: fields['required']=list(properties)
    return fields


def array(item, maximum=None):
    result=dict(type='array',items=item)
    if maximum is not None: result['maxItems']=maximum
    return result


def nullable(rule):
    return {'anyOf':[rule,{'type':'null'}]}


def vector(size):
    return dict(type='array',items={'type':'number'},minItems=size,maxItems=size)


TEXT={'type':'string','minLength':1}
ID={'type':'string','pattern':'^[A-Za-z][A-Za-z0-9_-]{0,79}$'}
POS={'type':'number','exclusiveMinimum':0}
NUM={'type':'number'}
NN={'type':'number','minimum':0}
INT={'type':'integer','minimum':1}
SHA={'type':'string','pattern':'^[0-9a-f]{64}$'}
BOOL={'type':'boolean'}
STATUS={'enum':['unconfirmed','assumed','confirmed']}
ROUTE={'enum':['circular','rounded_rectangle','custom_closed']}
DIRECTION={'enum':['cw','ccw']}
GAP=obj(dict(type={'enum':['center_leg_ground','spacer','none']},length_m=NN,source=TEXT,
             center_xyz_m=nullable(vector(3))),require_all=False)
GAP['required']=['type','length_m','source']
CORE=dict(manufacturer=nullable(TEXT),part_number=nullable(TEXT),geometry_reference=nullable(TEXT),
          geometry_sha256=nullable(SHA),material_reference=nullable(TEXT),gap_geometry=nullable(GAP))
BOBBIN=dict(part_number=nullable(TEXT),geometry_reference=nullable(TEXT),geometry_sha256=nullable(SHA),
            winding_route_type=nullable(ROUTE),winding_path_xy_m=nullable(array(vector(2),256)),
            rounded_rectangle_m=nullable(obj(dict(center_xy_m=vector(2),width_m=POS,height_m=POS,corner_radius_m=POS))),
            wall_thickness_m=nullable(POS),source=nullable(TEXT),status=STATUS)
PINS=dict(winding_id=ID,turns=INT,start_node=nullable(TEXT),end_node=nullable(TEXT),dot_node=nullable(TEXT),
          direction=nullable(DIRECTION),status=STATUS,source=nullable(TEXT))
PORT=dict(dot_node=nullable(TEXT),other_node=nullable(TEXT),connection=nullable({'enum':['series','parallel']}),
          section_order=array(ID),status=STATUS,source=nullable(TEXT))
LEAD=obj(dict(node=TEXT,path_xyz_m={**array(vector(3),512),'minItems':2},source=TEXT))
TERMINAL=obj(dict(node=TEXT,pin=TEXT,position_xyz_m=nullable(vector(3)),
                  external_connection=nullable({'enum':['none','net']}),net=nullable(TEXT),status=STATUS,source=nullable(TEXT)))
WIRE_EVIDENCE=obj(dict(source=TEXT,basis={'enum':['estimated','drawing','measured']},
                       width_tolerance_m=nullable(NN),height_tolerance_m=nullable(NN)))
FRAME=dict(z0_m=nullable(NUM),r0_m_if_circular=nullable(POS))
PROFILE_SCHEMA=obj(dict(schema={'const':PROFILE},frame=obj(FRAME,require_all=False),core=obj(CORE,require_all=False),
    bobbin=obj(BOBBIN,require_all=False),sections={'type':'object','propertyNames':ID,'additionalProperties':obj(PINS,require_all=False)},
    ports={'type':'object','propertyNames':ID,'additionalProperties':obj(PORT,require_all=False)},
    terminals=array(TERMINAL),wire_evidence={'type':'object','propertyNames':ID,'additionalProperties':WIRE_EVIDENCE},
    leads=array(LEAD),assumptions=array(TEXT)),require_all=False)
PROFILE_SCHEMA.update(required=['schema'],**{'$schema':'https://json-schema.org/draft/2020-12/schema'})

BUNDLE=obj(dict(turn_id=TEXT,parallel_bundle_id=TEXT,turn_index_in_layer_one_based=INT,
    parallel_bundle_index_one_based=INT,bbox_uv_m=vector(4),center_uv_m=vector(2),
    profile_type={'enum':['ellipse','rectangle']},corner_radius_m=nullable(NN),center_rz_m=nullable(vector(2))))
SECTION=obj(dict(section_id=ID,winding_id=ID,layer_index_one_based=INT,turns=INT,
    winding_style=TEXT,insulation_before_m=NN,insulation_kind=TEXT,layer_envelope_uv_m=vector(4),
    occupied_width_m=NN,route_ref=nullable(TEXT),
    **{k:PINS[k] for k in ('start_node','end_node','dot_node','direction','status','source')},bundles=array(BUNDLE)))
WINDING=obj(dict(id=ID,turns=INT,bare_strand_diameter_m=POS,strands=INT,insulated_strand_diameter_m=nullable(POS),
    parallel_bundles=nullable(INT),strands_per_bundle=nullable(INT),bundle_width_m=nullable(POS),bundle_height_m=nullable(POS),
    unflattened_bundle_diameter_m=nullable(POS),flatten_ratio=nullable(POS),wire_type=nullable(TEXT),wire_evidence=nullable(WIRE_EVIDENCE),
    bundle_dimension_basis=TEXT,bundle_packing_factor=nullable(POS),sum_layer_envelope_height_m=nullable(NN),
    stack_buildup_m=nullable(NN),first_to_last_span_m=nullable(NN),section_ids=array(ID),dcr_ohm=nullable(NN)))
WINDING['properties'].update(parallel_wires=INT,strands_per_wire=INT,bundles_per_wire=INT)
CONNECTION=obj(dict(winding_id=ID,**PORT,series_coefficients=nullable(array({'enum':[-1,1]})),
                    effective_series_turns=nullable({'type':'integer','minimum':0}),turns_match_calculator=nullable(BOOL),
                    reduction_status={'enum':['unresolved','series','tap_requires_circuit','parallel_requires_circuit']}))
SOURCE=obj(dict(design_id=TEXT,input_sha256=SHA,engine_snapshot_id=SHA,engine_kind={'const':'python'},
                geometry_algorithm_version={'const':VERSION},geometry_sha256=SHA))
CHECKS=obj(dict(two_dimensional_fit=nullable(BOOL),height_margin_m=nullable(NUM),same_endpoint_geometry=BOOL,
                three_dimensional_interference={'const':'not_run'},mesh={'const':'not_run'},
                electromagnetic_convergence={'const':'not_run'},measurement_comparison={'const':'not_run'}))
MATRIX=obj(dict(row_sections=array(ID),column_ports=array(ID),values=nullable(array(array({'enum':[-1,0,1]}))),
                convention={'const':'i_sections=A*i_ports; L_ports=transpose(A)*L_sections*A'}))
GEOMETRY_SCHEMA=obj(dict(schema={'const':GEOMETRY},units={'const':'SI'},source=SOURCE,
    frame=obj(dict(origin={'const':'core_mating_plane_center'},winding_axis={'const':'Z'},handedness={'const':'right'},
                   local_u={'const':'axial'},local_v={'const':'radial'},**FRAME)),
    core=obj(dict(**CORE,calculator_core=TEXT,calculator_material=TEXT,mean_length_per_turn_m=POS)),
    bobbin=obj(dict(**BOBBIN,axial_window_m=nullable(POS),radial_window_m=nullable(POS))),
    bbox_convention={'const':'[u_min,v_min,width,height]; ellipse dimensions are full diameters'},
    windings=array(WINDING),physical_sections=array(SECTION),connections=array(CONNECTION),connection_matrix=MATRIX,
    terminals=array(TERMINAL),leads=array(LEAD),assumptions=array(TEXT),checks=CHECKS,missing_fields=array(TEXT),
    ready=obj(dict(cross_section=BOOL,geometry_3d=BOOL,electromagnetic={'const':False})),
    operating_points=array(obj(dict(case=TEXT,vin_V=POS,frequency_Hz=POS,mode=TEXT,primary_peak_A=NN))),
    design_targets=obj(dict(primary_self_inductance_H=POS,coupling_enabled=BOOL,coupling_order=array(ID),coupling_k=nullable(array(array(NUM))),
                            provenance={'const':'calculator_input_not_extracted'}))))
GEOMETRY_SCHEMA['$schema']='https://json-schema.org/draft/2020-12/schema'
GAP_ESTIMATE=obj(dict(model={'const':'linear_magnetic_circuit_no_fringing'},material=nullable(TEXT),
    target_inductance_H=POS,primary_turns=INT,Ae_m2=POS,le_m=POS,le_source=TEXT,
    mu_r=nullable(POS),mu_r_source=TEXT,mu_r_conditions=nullable(TEXT),mu_r_tolerance=nullable(NN),
    material_source=nullable(TEXT),AL_target_H=POS,AL_ungapped_H=nullable(POS),L_ungapped_H=nullable(POS),
    mu_effective=nullable(POS),gap_m=nullable(NN),gap_raw_m=nullable(NUM),
    status={'enum':['estimated','unavailable','infeasible']},formula_source=TEXT,note=TEXT,
    provenance={'const':'calculator_estimate_not_geometry_or_measurement'}))
# Optional for v1 packages created before gap estimates were implemented.
GEOMETRY_SCHEMA['allOf']=[{
    'if':{'properties':{'ready':{'properties':{'geometry_3d':{'const':True}}}}},
    'then':{'properties':{
        'ready':{'properties':{'cross_section':{'const':True}}},
        'frame':{'properties':{'z0_m':NUM}},
        'bobbin':{'properties':{'winding_route_type':ROUTE,'status':{'enum':['confirmed','assumed']},
                                'axial_window_m':POS,'radial_window_m':POS}},
        'physical_sections':{'minItems':1,'items':{'properties':{
            'start_node':TEXT,'end_node':TEXT,'dot_node':TEXT,'direction':DIRECTION}}},
        'checks':{'properties':{'two_dimensional_fit':{'const':True}}}}}}]

from copy import deepcopy
LEGACY_GEOMETRY_SCHEMA=deepcopy(GEOMETRY_SCHEMA)
GEOMETRY_SCHEMA['properties']['design_targets']['properties']['air_gap']=GAP_ESTIMATE
PRE_PARALLEL_GEOMETRY_SCHEMA=deepcopy(GEOMETRY_SCHEMA)
PRE_PARALLEL_LEGACY_GEOMETRY_SCHEMA=deepcopy(LEGACY_GEOMETRY_SCHEMA)
for _old in (PRE_PARALLEL_GEOMETRY_SCHEMA,PRE_PARALLEL_LEGACY_GEOMETRY_SCHEMA):
    for _key in ('parallel_wires','strands_per_wire','bundles_per_wire'):
        _old['properties']['windings']['items']['properties'].pop(_key)


@lru_cache(maxsize=2)
def _validator(which):
    from jsonschema import Draft202012Validator
    return Draft202012Validator(PROFILE_SCHEMA if which==PROFILE else GEOMETRY_SCHEMA)


def validate_schema(value,which):
    if not isinstance(value,dict) or value.get('schema')!=which:
        raise ValueError(f'无法识别模型接口版本，需要 {which}')
    error=next(_validator(which).iter_errors(value),None)
    if error:
        path='.'.join(str(v) for v in error.absolute_path)
        raise ValueError(f'{path or which}：{error.message}')
    # jsonschema accepts non-finite Python floats as numbers.
    import json
    json.dumps(value,allow_nan=False)


def validate_profile(p):
    validate_schema(p,PROFILE)
    b=p.get('bobbin',{})
    rr=b.get('rounded_rectangle_m')
    if rr and 2*rr['corner_radius_m']>min(rr['width_m'],rr['height_m']):
        raise ValueError('圆角半径超过路径宽高的一半')
    pts=b.get('winding_path_xy_m')
    if b.get('winding_route_type') and ((rr and b['winding_route_type']!='rounded_rectangle')
            or (pts is not None and b['winding_route_type']!='custom_closed')):
        raise ValueError('绕线轨迹类型与路径尺寸不符')
    if pts is not None:
        if len(pts)<4 or pts[0]!=pts[-1] or len(set(map(tuple,pts[:-1])))!=len(pts)-1:
            raise ValueError('自定义路径必须闭合，至少三个不同顶点，且仅首末点重合')
        def cross(a,b,c):
            return (b[0]-a[0])*(c[1]-a[1])-(b[1]-a[1])*(c[0]-a[0])
        edges=list(zip(pts,pts[1:]))
        if sum(a[0]*b[1]-a[1]*b[0] for a,b in edges)<=0:
            raise ValueError('自定义路径须从 +Z 看逆时针，且围成非零面积')
        for i,(a,b1) in enumerate(edges):
            for j,(c,d) in enumerate(edges[i+2:],i+2):
                if i==0 and j==len(edges)-1: continue
                if any(max(a[k],b1[k])<min(c[k],d[k]) or max(c[k],d[k])<min(a[k],b1[k]) for k in (0,1)): continue
                if cross(a,b1,c)*cross(a,b1,d)<=0 and cross(c,d,a)*cross(c,d,b1)<=0:
                    raise ValueError('自定义绕线路径存在自交或接触')
    for name,data in (*p.get('sections',{}).items(),*p.get('ports',{}).items(),('bobbin',b)):
        if data.get('status') in ('assumed','confirmed') and not (data.get('source') or '').strip():
            raise ValueError(f'{name} 的已确认或假设数据需要填写来源')
    for key,data in p.get('sections',{}).items():
        if not {'winding_id','turns'}<=data.keys(): raise ValueError(key+' 的段配置必须绑定绕组和匝数')
        a,b1,dot=(data.get(k) for k in ('start_node','end_node','dot_node'))
        if a is not None and a==b1 or dot is not None and a and b1 and dot not in (a,b1):
            raise ValueError(key+' 的起止节点或同名端无效')
    gap=p.get('core',{}).get('gap_geometry')
    if gap and (gap['type']=='none')!=(gap['length_m']==0):
        raise ValueError('无气隙应为 0 m；磨隙或垫片厚度必须大于 0')
    terminals=p.get('terminals',[])
    if len({t['node'] for t in terminals})!=len(terminals) or len({t['pin'] for t in terminals})!=len(terminals):
        raise ValueError('端子节点或脚位号重复')
    for t in terminals:
        if (t['external_connection']=='net')!=(t['net'] is not None):
            raise ValueError('已声明的外部网络须与端子的连接类型对应')
        if t['status']!='unconfirmed' and not (t['source'] or '').strip():
            raise ValueError(t['node']+' 端子需要来源')


def profile_template(layers=()):
    sections={s['section_id']:dict(winding_id=s['winding_id'],turns=int(s['turns']),start_node=None,
        end_node=None,dot_node=None,direction=None,status='unconfirmed',source=None) for s in layers}
    windings=dict.fromkeys(s['winding_id'] for s in layers)
    return dict(schema=PROFILE,frame=dict(z0_m=None,r0_m_if_circular=None),
        bobbin=dict(winding_route_type=None,part_number=None,status='unconfirmed',source=None),
        core=dict(manufacturer=None,part_number=None,geometry_reference=None,geometry_sha256=None,
                  material_reference=None,gap_geometry=None),sections=sections,
        ports={w:dict(dot_node=None,other_node=None,connection=None,section_order=[],status='unconfirmed',source=None)
               for w in windings},terminals=[],leads=[],wire_evidence={},assumptions=[])
