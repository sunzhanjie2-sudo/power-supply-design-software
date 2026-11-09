"""OCC CAD, explicit mm->m conversion, conformal regions, positive-volume gate."""
from __future__ import annotations
import math
from pathlib import Path
import gmsh
import numpy as np

from .runtime import run_logged
from .storage import event,write


def remove_unused():
    for dim in [2,1,0]:
        used={t for d,t in gmsh.model.getBoundary(gmsh.model.getEntities(dim+1),combined=False,oriented=False) if d==dim}
        unused=[e for e in gmsh.model.getEntities(dim) if e[1] not in used]
        if unused:gmsh.model.occ.remove(unused,recursive=False);gmsh.model.occ.synchronize()


def mass(items):return sum(gmsh.model.occ.getMass(d,t) for d,t in items if d==3)


def turn_face(bundle):
    occ=gmsh.model.occ;r,z=np.asarray(bundle['center_rz_m'])*1000
    width,height=np.asarray(bundle['bbox_uv_m'][2:])*1000
    major,minor=max(width,height)/2,min(width,height)/2
    arcs=[occ.addEllipse(r,0,z,major,minor,angle1=q*math.pi/2,angle2=(q+1)*math.pi/2) for q in range(4)]
    face=occ.addPlaneSurface([occ.addCurveLoop(arcs)])
    if width>=height:
        occ.rotate([(2,face)],r,0,z,0,1,0,math.pi/2)
        occ.rotate([(2,face)],r,0,z,0,0,1,math.pi/2)
    else:occ.rotate([(2,face)],r,0,z,1,0,0,math.pi/2)
    return face,2*math.pi*r*math.pi*width*height/4


def import_core(config):
    c=config['core'];path=Path(c['path']);occ=gmsh.model.occ
    gmsh.option.setString('Geometry.OCCTargetUnit','MM')
    core=[e for e in occ.importShapes(str(path.resolve()),highestDimOnly=True) if e[0]==3]
    if not core:raise ValueError('磁芯文件没有封闭三维实体；请导入实体STEP/BREP。')
    if path.suffix.lower()=='.brep' and c['brep_unit']=='m':occ.dilate(core,0,0,0,1000,1000,1000)
    for angle,axis in zip(c['rotation_deg'],[(1,0,0),(0,1,0),(0,0,1)]):
        if angle:occ.rotate(core,0,0,0,*axis,math.radians(angle))
    occ.translate(core,*c['translation_mm']);occ.synchronize()
    gap=c['total_gap_m']*1000
    if c['mode']!='assembled':
        if len(core)!=1:raise ValueError('单半芯模式需要一个封闭实体。')
        bbox=occ.getBoundingBox(*core[0])
        if abs(bbox[5])>.002 or bbox[2]>=0 or abs(c['gap_center_z_m'])>1e-10:
            raise ValueError('半芯必须先对齐：拼合面Z=0，实体位于Z<0；气隙中心Z=0。')
        if c['mode']=='half_center_gap' and gap:
            cutter=occ.addCylinder(0,0,-gap/2,0,0,gap,c['center_leg_radius_m']*1000+1e-5)
            core,_=occ.cut(core,[(3,cutter)]);core=[e for e in core if e[0]==3]
        if c['mode']=='half_spacer' and gap:occ.translate(core,0,0,-gap/2)
        upper=occ.copy(core);occ.rotate(upper,0,0,0,1,0,0,math.pi);core+=upper
    if len(core)>1:core,_=occ.fuse(core[:1],core[1:]);core=[e for e in core if e[0]==3]
    occ.synchronize()
    if not core or min(occ.getMass(*e) for e in core)<=0:raise ValueError('磁芯装配后实体体积无效。')
    return core


def gap_planes(core, gap, center_z, tolerance):
    """Find the declared gap surfaces in the current CAD coordinate units."""
    if not gap:
        return []
    faces={tag for _,tag in gmsh.model.getBoundary(core,combined=False,oriented=False)}
    selected=[]
    for tag in faces:
        bounds=gmsh.model.getBoundingBox(2,tag)
        z=(bounds[2]+bounds[5])/2
        if (bounds[5]-bounds[2]<tolerance
                and min(abs(z-center_z-gap/2),abs(z-center_z+gap/2))<tolerance):
            selected.append(tag)
    if len(selected)<2:
        raise ValueError('声明的气隙与磁芯实体不一致。请核对已装配CAD中的实际气隙，'
                         '或导入单半芯并选择中柱磨隙/垫片配对。')
    return sorted(selected)


def build(out,config,g,make_mesh=True):
    out=Path(out);geo=out/'geometry';geo.mkdir(parents=True,exist_ok=True)
    gmsh.initialize();gmsh.logger.start()
    try:
        gmsh.option.setNumber('General.Terminal',1);gmsh.option.setNumber('General.NumThreads',1)
        gmsh.model.add('transformer');occ=gmsh.model.occ
        coils=[];expected=[];actual=[]
        for si,section in enumerate(g['physical_sections']):
            for bundle in section['bundles']:
                face,volume=turn_face(bundle)
                solid=next(e for e in occ.revolve([(2,face)],0,0,0,0,0,1,2*math.pi) if e[0]==3)
                coils.append((si,solid[1]));expected.append(volume);actual.append(occ.getMass(*solid))
        occ.synchronize();remove_unused()
        relative=np.asarray(actual)/expected-1
        if np.max(np.abs(relative))>1e-6:raise RuntimeError('等效匝CAD体积与解析截面不一致。')
        gmsh.write(str(geo/'windings_mm.step'))
        core=import_core(config);core_volume=mass(core)
        # Fail before repeating and fragmenting every winding quarter.
        gap_planes(core,config['core']['total_gap_m']*1000,config['core']['gap_center_z_m']*1000,.002)
        for e in core:
            bb=occ.getBoundingBox(*e)
            if np.linalg.norm(np.maximum(np.abs(bb[:3]),np.abs(bb[3:])))>=config['solver']['air_radius_m']*1000*.9:
                raise ValueError('磁芯接近或超出空气域；请核对CAD单位、坐标或增大空气半径。')
        overlaps=[]
        for _,tag in coils:
            common,_=occ.intersect(core,[(3,tag)],removeObject=False,removeTool=False)
            overlaps.append(mass(common))
            if common:occ.remove(common,recursive=True)
        occ.synchronize()
        if max(overlaps)>1e-6:raise ValueError('线圈与磁芯实体干涉；请调整导出坐标或磁芯位置。')
        gmsh.write(str(geo/'assembly_mm.step'))
        coil_count=len(coils)
        occ.remove([(3,t) for _,t in coils],recursive=True);occ.synchronize();remove_unused()
        gmsh.write(str(geo/'core_mm.step'))
        core_bounds=np.array([occ.getBoundingBox(*e) for e in core])
        span=float(np.max(core_bounds[:,3:].max(axis=0)-core_bounds[:,:3].min(axis=0)))
        scale=span/20.5
        if not .1<=span<=2000:raise ValueError('磁芯尺寸异常；请核对CAD单位。')
        report=dict(cad_unit='mm',solver_unit='m',coil_solids=coil_count,core_solids=len(core),
                    core_volume_mm3=core_volume,coil_volume_mm3=sum(actual),
                    coil_volume_relative_errors=relative.tolist(),core_winding_overlap_mm3=overlaps,
                    core_bounds_mm=core_bounds.tolist(),core_mode=config['core']['mode'],
                    declared_total_gap_m=config['core']['total_gap_m'])
        write(out/'cad-validation.json',report)
        event('cad','磁芯及绕组实体检查通过',15)
        if not make_mesh:return report
        event('geometry','正在构建等效匝分区，随后分割磁芯与空气域',16)
        coils=[]
        for si,section in enumerate(g['physical_sections']):
            for bundle in section['bundles']:
                face,_=turn_face(bundle)
                quarter=next(e for e in occ.revolve([(2,face)],0,0,0,0,0,1,math.pi/2) if e[0]==3)
                coils.append((si,quarter[1]))
                for quadrant in [1,2,3]:
                    piece=occ.copy([quarter])[0];occ.rotate([piece],0,0,0,0,0,1,quadrant*math.pi/2);coils.append((si,piece[1]))
        occ.synchronize();remove_unused()
        occ.dilate(occ.getEntities(3),0,0,0,.001,.001,.001)
        sphere=occ.addSphere(0,0,0,config['solver']['air_radius_m'])
        objects=[*core,*[(3,t) for _,t in coils]]
        event('geometry',f'正在分割空气域及{len(coils)}个导线分区',17)
        volumes,mapping=occ.fragment([(3,sphere)],objects);occ.synchronize();remove_unused()
        event('geometry','实体分割完成，正在建立材料区与网格约束',18)
        mapped=[set(t for d,t in group if d==3) for group in mapping[1:]]
        if any(len(group)!=1 for group in mapped):raise ValueError('实体分割后区域改变；可能存在线束重叠或无效CAD。')
        if len(set().union(*mapped))!=sum(len(x) for x in mapped):raise ValueError('存在重叠的源区域。')
        occupied=set().union(*mapped);air={t for d,t in volumes if d==3}-occupied
        if len(air)!=1:raise ValueError('空气域没有形成一个连续区域。')
        bodies={1:sorted(air),2:sorted(set().union(*mapped[:len(core)]))}
        for i in range(len(g['physical_sections'])):bodies[i+3]=[]
        for (si,_),tags in zip(coils,mapped[len(core):]):bodies[si+3].extend(tags)
        for group,tags in bodies.items():
            gmsh.model.addPhysicalGroup(3,tags,group)
            gmsh.model.setPhysicalName(3,group,'Air' if group==1 else 'Core' if group==2 else f'Section_{group-3:03d}')
        def faces(tags):return sorted({t for tag in tags for d,t in gmsh.model.getBoundary([(3,tag)],oriented=False) if d==2})
        core_faces=faces(bodies[2]);coil_faces=faces([tag for key,tags in bodies.items() if key>=3 for tag in tags])
        outer=[]
        for _,tag in gmsh.model.getBoundary([(3,next(iter(air)))],oriented=False):
            bb=gmsh.model.getBoundingBox(2,tag)
            if max(np.asarray(bb[3:])-bb[:3])>config['solver']['air_radius_m']:outer.append(tag)
        if not outer:raise ValueError('没有找到空气域外边界。')
        gmsh.model.addPhysicalGroup(2,outer,101);gmsh.model.setPhysicalName(2,101,'OuterBoundary')
        gap=config['core']['total_gap_m'];zc=config['core']['gap_center_z_m']
        gap_faces=gap_planes([(3,t) for t in bodies[2]],gap,zc,2e-6)
        factor={'coarse':1.45,'standard':1.,'fine':.7}[config['solver']['mesh_profile']]
        large=.009*scale*factor;near=.00065*scale*factor
        gap_size=min(.0001*scale*factor,gap/3) if gap else .0001*scale*factor
        fields=[]
        def threshold(surfaces,small,distance_near,distance_far):
            distance=gmsh.model.mesh.field.add('Distance');gmsh.model.mesh.field.setNumbers(distance,'SurfacesList',surfaces)
            field=gmsh.model.mesh.field.add('Threshold');gmsh.model.mesh.field.setNumber(field,'InField',distance)
            for k,v in dict(SizeMin=small,SizeMax=large,DistMin=distance_near,DistMax=distance_far).items():gmsh.model.mesh.field.setNumber(field,k,v)
            fields.append(field)
        threshold(core_faces,.0012*scale*factor,.001*scale,.016*scale)
        threshold(coil_faces,near,.0004*scale,.012*scale)
        if gap_faces:threshold(gap_faces,gap_size,.00035*scale,.004*scale)
        minimum=gmsh.model.mesh.field.add('Min');gmsh.model.mesh.field.setNumbers(minimum,'FieldsList',fields)
        gmsh.model.mesh.field.setAsBackgroundMesh(minimum)
        for key,value in {'Mesh.MeshSizeMin':min(.00009*scale*factor,gap_size),'Mesh.MeshSizeMax':large,
                          'Mesh.Algorithm3D':1,'Mesh.OptimizeThreshold':.3,'Mesh.MeshSizeFromCurvature':0,
                          'Mesh.MeshSizeFromPoints':0,'Mesh.MeshSizeExtendFromBoundary':0,'Mesh.MshFileVersion':2.2}.items():gmsh.option.setNumber(key,value)
        curves={t for _,t in gmsh.model.getBoundary([(2,t) for t in coil_faces],combined=False,oriented=False)}
        for tag in curves:
            bb=gmsh.model.getBoundingBox(1,tag)
            count=(9 if factor<1 else 7) if bb[5]-bb[2]>1e-7 else max(4,int(math.ceil(occ.getMass(1,tag)/(.0009*scale*factor)))+1)
            gmsh.model.mesh.setTransfiniteCurve(tag,count)
        for tag in coil_faces:
            if len(gmsh.model.getBoundary([(2,tag)],oriented=False))==4 and gmsh.model.getType(2,tag)!='Plane':gmsh.model.mesh.setTransfiniteSurface(tag)
        event('mesh','正在生成并优化三维网格',20)
        gmsh.model.mesh.generate(3)
        initial_types,initial_tags,_=gmsh.model.mesh.getElements(3)
        if any(int(t)!=4 for t in initial_types):
            raise ValueError('首版需要一次四面体网格。')
        initial_tags=np.concatenate(initial_tags)
        initial_volumes=np.asarray(gmsh.model.mesh.getElementQualities(initial_tags,'volume'))
        initial_quality=np.asarray(gmsh.model.mesh.getElementQualities(initial_tags,'minSICN'))
        initial_nodes=len(gmsh.model.mesh.getNodes()[0])
        write(out/'mesh-initial-quality.json',dict(nodes=initial_nodes,tetrahedra=len(initial_tags),
              nonpositive_tetrahedra=int((initial_volumes<=0).sum()),minimum_signed_volume_m3=float(initial_volumes.min()),
              minSICN=float(initial_quality.min())))
        event('mesh','三维网格已生成，正在做原生四面体优化与正体积检查',24,nodes=initial_nodes)
        # Keep constrained conductor surfaces fixed. Native tetrahedral swaps
        # avoid the Netgen access violation observed on the QR97 thin toroids.
        gmsh.model.mesh.optimize('',niter=5)
        types,tags,_=gmsh.model.mesh.getElements(3)
        if any(int(t)!=4 for t in types):raise ValueError('首版需要一次四面体网格。')
        tags=np.concatenate(tags);signed=np.asarray(gmsh.model.mesh.getElementQualities(tags,'volume'))
        quality=np.asarray(gmsh.model.mesh.getElementQualities(tags,'minSICN'))
        quality_report=dict(nonpositive_tetrahedra=int((signed<=0).sum()),minimum_signed_volume_m3=float(signed.min()),
                            minSICN=float(quality.min()),quality_quantiles=np.quantile(quality,[0,.001,.01,.1,.5]).tolist())
        write(out/'mesh-quality.json',quality_report)
        if np.any(signed<=0) or quality.min()<=0:raise ValueError('网格包含非正体积或无效单元，未启动求解。')
        nodes=len(gmsh.model.mesh.getNodes()[0])
        if nodes>300000:raise ValueError('网格超过首版30万节点限制；请使用较粗网格或简化等效匝。')
        gmsh.write(str(out/'transformer.msh'))
        report.update(nodes=nodes,tetrahedra=len(tags),physical_bodies=bodies,gap_faces=gap_faces,outer_boundaries=outer,
                      optimizer='Gmsh native tetrahedral optimizer; no unconstrained node relocation',
                      coil_mesh_subvolumes=len(coils),mesh_profile=config['solver']['mesh_profile'],mesh_scale=scale)
        write(out/'geometry-validation.json',report)
    finally:
        (out/'gmsh.log').write_text('\n'.join(gmsh.logger.get())+'\n',encoding='utf-8')
        gmsh.logger.stop();gmsh.finalize()
    root=Path(config['solver']['elmer_home'])
    run_logged([root/'bin/ElmerGrid.exe',14,2,'transformer.msh','-out','mesh'],out,'elmergrid.log',root,300)
    event('mesh','网格质量检查及Elmer网格转换通过',30,nodes=report['nodes'],tetrahedra=report['tetrahedra'])
    return report


def view_cad(path):
    gmsh.initialize()
    try:
        gmsh.option.setString('Geometry.OCCTargetUnit','MM');gmsh.open(str(Path(path).resolve()))
        gmsh.option.setNumber('Geometry.SurfaceType',1);gmsh.option.setNumber('Geometry.ColorCarousel',2)
        gmsh.fltk.run()
    finally:gmsh.finalize()
