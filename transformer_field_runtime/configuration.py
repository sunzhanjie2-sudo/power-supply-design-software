from __future__ import annotations
from copy import deepcopy
import math
import os
from pathlib import Path
import numpy as np

from .storage import app_home,read,sha
from .contract_v1 import validate_profile
from .geometry_semantics import _assemble_connections

SCOPE_NOTE='本工具参考设置；非实际骨架、接线、绕向或气隙测量。'


def new_config(loaded=None):
    g=loaded['geometry'] if loaded else None
    profile=deepcopy(loaded['profile']) if loaded else {}
    if g:
        profile.setdefault('sections',{s['section_id']:{k:s[k] for k in ['winding_id','turns','start_node','end_node','dot_node','direction','status','source']}
                                       for s in g['physical_sections']})
        profile.setdefault('ports',{p['winding_id']:{k:p[k] for k in ['dot_node','other_node','connection','section_order','status','source']}
                                    for p in g['connections']})
        profile.setdefault('terminals',deepcopy(g['terminals']))
    frame=deepcopy(g['frame']) if g else {}
    return dict(schema='transformer-coupling-tool.project.v1',name=g['source']['design_id'] if g else '变压器',
                package_path=loaded['path'] if loaded else '',package_sha256=loaded['sha256'] if loaded else None,
                core=dict(path='',sha256=None,mode='assembled',brep_unit='mm',translation_mm=[0.,0.,0.],rotation_deg=[0.,0.,0.],
                          total_gap_m=None,center_leg_radius_m=None,gap_center_z_m=0.,source=''),
                frame=dict(r0_m=frame.get('r0_m_if_circular'),z0_m=frame.get('z0_m')),
                material=dict(name='',relative_permeability=None,temperature_C=25.,source='',frequency_Hz=0.,bias_current_A=0.),
                connections=profile,classification='reference_assumptions',assumptions=[],
                primary_port='P' if g and any(w['id']=='P' for w in g['windings']) else g['windings'][0]['id'] if g else '',
                solver=dict(elmer_home=detect_elmer(),mesh_profile='standard',air_radius_m=.05,timeout_s=1200),
                output_root=str(app_home()/'results'))


def detect_elmer():
    # Machine-local selection is supplied by the design application's settings.
    for root in [Path(os.environ['ELMER_HOME'])] if os.environ.get('ELMER_HOME') else []:
        if (root/'bin/ElmerSolver.exe').is_file() and (root/'bin/ElmerGrid.exe').is_file():return str(root)
    return ''


def apply_reference(config,loaded):
    c=deepcopy(config);g=loaded['geometry']
    target=g.get('design_targets',{}).get('air_gap') or {}
    c['material'].update(name=g['core']['calculator_material'],relative_permeability=target.get('mu_r'),
                         source=target.get('material_source') or '用户需补充材料依据')
    if target.get('gap_m') is not None:c['core']['total_gap_m']=target['gap_m']
    if c['frame']['z0_m'] is None and g['bobbin']['axial_window_m']:
        c['frame']['z0_m']=-g['bobbin']['axial_window_m']/2
    profile=dict(schema='power-transformer.model-input.v1',sections={},ports={},terminals=[],leads=[],assumptions=[SCOPE_NOTE])
    for winding in g['windings']:
        ids=winding['section_ids'];wid=winding['id']
        for i,sid in enumerate(ids):
            a=wid+'_D' if i==0 else f'{wid}_J{i}'
            b=wid+'_R' if i==len(ids)-1 else f'{wid}_J{i+1}'
            source=next(s for s in g['physical_sections'] if s['section_id']==sid)
            profile['sections'][sid]=dict(winding_id=wid,turns=source['turns'],start_node=a,end_node=b,dot_node=a,
                                          direction='ccw',status='assumed',source=SCOPE_NOTE)
            if i<len(ids)-1:
                profile['terminals'].append(dict(node=b,pin='REF_'+b,position_xyz_m=None,external_connection='none',
                                                 net=None,status='assumed',source=SCOPE_NOTE))
        profile['ports'][wid]=dict(dot_node=wid+'_D',other_node=wid+'_R',connection='series',section_order=ids,
                                   status='assumed',source=SCOPE_NOTE)
    c['connections']=profile;c['classification']='reference_assumptions'
    c['core']['source']=SCOPE_NOTE+' 由用户导入CAD并核对气隙。'
    c['assumptions']=[SCOPE_NOTE,'各段ccw、dot=start；分段按物理层序串联相加，内部连接点无外接电路。',
                       '以包内气隙估算作参考值，CAD中的实际实体为准，未按目标电感拟合。',
                       '均匀分流的闭合等效匝源；不含引线、匝间连接、涡流、电容或非线性偏磁。']
    return c


def resolve_paths(config,path):
    c=deepcopy(config);base=Path(path).resolve().parent
    for container,key in [(c,'package_path'),(c['core'],'path'),(c['solver'],'elmer_home'),(c,'output_root')]:
        if container.get(key) and not Path(container[key]).is_absolute():container[key]=str((base/container[key]).resolve())
    return c


def load_config(path):
    c=read(path)
    if c.get('schema')!='transformer-coupling-tool.project.v1':raise ValueError('不是本工具的项目设置文件。')
    return resolve_paths(c,path)


def finite(value,label,positive=False,nonnegative=False):
    if isinstance(value,bool) or not isinstance(value,(int,float)) or not math.isfinite(value):raise ValueError(label+'需要有限数值。')
    if positive and value<=0:raise ValueError(label+'必须大于0。')
    if nonnegative and value<0:raise ValueError(label+'不能小于0。')


def prepare_geometry(config,loaded):
    g=deepcopy(loaded['geometry']);c=config;errors=[]
    validate_profile(c['connections'])
    if loaded['sha256']!=c.get('package_sha256'):raise ValueError('导出包哈希已变化，请重新导入。')
    if g['checks']['two_dimensional_fit'] is not True:raise ValueError('导出包的二维窗口检查未通过，请先在设计软件修正排布。')
    if g['bobbin']['winding_route_type']!='circular':raise ValueError('首版支持圆形路径；圆角矩形/自定义路径尚未接入求解。')
    if not 1<=len(g['physical_sections'])<=32 or not 1<=len(g['windings'])<=8:raise ValueError('支持1至32个物理段、1至8个端口。')
    if sum(len(s['bundles']) for s in g['physical_sections'])>300:raise ValueError('首版最多300个等效线束截面，不能静默截断。')
    finite(c['frame']['r0_m'],'内侧基准半径',positive=True);finite(c['frame']['z0_m'],'轴向起点')
    g['frame'].update(r0_m_if_circular=c['frame']['r0_m'],z0_m=c['frame']['z0_m'])
    for s in g['physical_sections']:
        overlay=c['connections'].get('sections',{}).get(s['section_id'],{})
        for key in ['direction','start_node','end_node','dot_node','status','source']:
            if key in overlay:s[key]=overlay[key]
        if s['direction'] not in ('cw','ccw') or not all(s.get(k) for k in ['start_node','end_node','dot_node','source']) or s['status']=='unconfirmed':
            errors.append('请补齐物理段 '+s['section_id']+' 的绕向/节点/同名端和来源。')
        if s['start_node']==s['end_node'] or s['dot_node'] not in (s['start_node'],s['end_node']):errors.append(s['section_id']+' 的节点或同名端无效。')
        for b in s['bundles']:
            if b['profile_type']!='ellipse':errors.append('首版支持椭圆等效线束；暂未接入矩形截面。')
            b['center_rz_m']=[c['frame']['r0_m']+b['center_uv_m'][1],c['frame']['z0_m']+b['center_uv_m'][0]]
            winding=next(w for w in g['windings'] if w['id']==s['winding_id'])
            if not np.allclose(b['bbox_uv_m'][2:],[winding['bundle_width_m'],winding['bundle_height_m']],rtol=1e-10,atol=1e-15):
                errors.append(s['section_id']+' 的束尺寸与绕组摘要不一致。')
            if b['center_rz_m'][0]<=b['bbox_uv_m'][3]/2:errors.append('线束不能穿过Z轴。')
    ports,matrix=_assemble_connections(g['windings'],g['physical_sections'],c['connections'],errors)
    if matrix['values'] is None:errors.append('未得到可归算的串联连接矩阵；一般并联/外接抽头需额外电路约束，首版不自动处理。')
    if any(p['turns_match_calculator'] is False for p in ports):errors.append('串联有效匝数与设计软件不一致。')
    if errors:raise ValueError('\n'.join(dict.fromkeys(errors)))
    g['connections']=ports;g['connection_matrix']=matrix;g['terminals']=deepcopy(c['connections'].get('terminals',[]))
    g['leads']=[]
    return g


def validate_config(c,loaded,check_tools=True):
    if c.get('schema')!='transformer-coupling-tool.project.v1':raise ValueError('设置版本不支持。')
    if c.get('classification') not in ('reference_assumptions','user_defined_linear_model'):raise ValueError('模型分类不受支持。')
    core=Path(c['core']['path'])
    if not core.is_file() or core.suffix.lower() not in ('.step','.stp','.brep'):raise ValueError('请选择磁芯实体STEP/STP/BREP；STL不作为首版实体输入。')
    if c['core'].get('sha256') and sha(core)!=c['core']['sha256']:raise ValueError('磁芯文件哈希已变化，请重新选择文件。')
    if c['core']['mode'] not in ('assembled','half_center_gap','half_spacer'):raise ValueError('请选择磁芯装配方式。')
    if c['core']['brep_unit'] not in ('mm','m'):raise ValueError('BREP单位需要mm或m。')
    finite(c['core']['total_gap_m'],'总气隙',nonnegative=True)
    finite(c['core']['gap_center_z_m'],'气隙Z位置')
    if c['core']['mode']=='half_center_gap':finite(c['core']['center_leg_radius_m'],'中柱半径',positive=True)
    for key in ['translation_mm','rotation_deg']:
        if len(c['core'][key])!=3:raise ValueError('磁芯位置和转角均需3个数值。')
        for value in c['core'][key]:finite(value,'磁芯位置/转角')
    if not c['core']['source'].strip():raise ValueError('请填写磁芯/气隙来源或注明参考假设。')
    finite(c['material']['relative_permeability'],'相对磁导率',positive=True)
    if c['material']['relative_permeability']<1:raise ValueError('首版铁氧体相对磁导率不能小于1。')
    finite(c['material']['temperature_C'],'温度')
    if c['material'].get('frequency_Hz',0)!=0 or c['material'].get('bias_current_A',0)!=0:
        raise ValueError('首版为零偏置线性磁静态；不支持频率/偏磁材料模型。')
    if not c['material']['name'].strip() or not c['material']['source'].strip():raise ValueError('请填写材料名称及来源。')
    finite(c['solver']['air_radius_m'],'空气域半径',positive=True)
    if not c.get('output_root','').strip():raise ValueError('请选择结果保存目录。')
    if c['solver']['mesh_profile'] not in ('coarse','standard','fine'):raise ValueError('网格档位无效。')
    if check_tools:
        root=Path(c['solver']['elmer_home'])
        if not all((root/'bin'/name).is_file() for name in ('ElmerSolver.exe','ElmerGrid.exe')):
            raise ValueError('请选择包含bin/ElmerSolver.exe及ElmerGrid.exe的Elmer安装目录。')
    return prepare_geometry(c,loaded)
