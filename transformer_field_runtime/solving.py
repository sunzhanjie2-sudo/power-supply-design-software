from __future__ import annotations
import csv
from pathlib import Path
import re
import meshio
import numpy as np

from .runtime import prepare_solver,run_logged
from .sif_writer import sif
from .storage import event,now,sha,write


def load_field(path):
    m=meshio.read(path);indices=[i for i,c in enumerate(m.cells) if c.type=='tetra']
    if not indices:raise ValueError('Elmer结果中没有四面体。')
    tet=np.concatenate([m.cells[i].data for i in indices])
    def values(key):return np.concatenate([m.cell_data[key][i] for i in indices])
    x=m.points[tet]
    volumes=np.einsum('ij,ij->i',x[:,1]-x[:,0],np.cross(x[:,2]-x[:,0],x[:,3]-x[:,0]))/6
    if not np.all(volumes>0):raise ValueError('结果网格含非正体积单元。')
    return dict(points=m.points,tetra=tet,volumes=volumes,B=values('magnetic flux density e'),
                H=values('magnetic field strength e'),regions=values('GeometryIds').astype(int))


def solve_case(out,config,g,solver,name,currents):
    out=Path(out);(out/name).mkdir()
    text=sif(config,g,currents,name);(out/(name+'.sif')).write_text(text,encoding='ascii')
    log,elapsed=run_logged([solver,name+'.sif'],out,name+'.log',config['solver']['elmer_home'],config['solver']['timeout_s'])
    if 'ALL DONE' not in log or re.search(r'ERROR::|FATAL|NOT CONVERGED',log,re.I):raise RuntimeError('Elmer未成功收敛：'+name)
    names=(out/name/'scalars.dat.names').read_text(encoding='utf-8')
    match=re.search(r'^\s*(\d+):.*electromagnetic field energy',names,re.M|re.I)
    if not match:raise RuntimeError('Elmer未输出磁场能量：'+name)
    energy=float(np.loadtxt(out/name/'scalars.dat',ndmin=2)[-1,int(match[1])-1])
    if not np.isfinite(energy) or energy<=0:raise RuntimeError('Elmer磁场能量无效：'+name)
    return energy,load_field(out/name/'field_t0001.vtu'),elapsed


def matrix_csv(path,matrix,labels):
    with Path(path).open('w',encoding='utf-8-sig',newline='') as f:
        writer=csv.writer(f);writer.writerow(['port',*labels]);writer.writerows([[name,*row] for name,row in zip(labels,matrix)])


def gram(fields):
    ref=fields[0]
    for field in fields[1:]:
        if not np.array_equal(field['tetra'],ref['tetra']) or not np.allclose(field['points'],ref['points'],rtol=0,atol=1e-14):
            raise ValueError('不同激励使用的结果网格不一致。')
    return np.array([[np.einsum('ij,ij,i',a['B'],b['H'],ref['volumes']) for b in fields] for a in fields])


def solve_matrix(out,config,g):
    solver,provenance=prepare_solver(config['solver']['elmer_home']);write(Path(out)/'solver-provenance.json',provenance)
    count=len(g['physical_sections']);fields=[];energies=[];timings=[];files=[]
    for i,section in enumerate(g['physical_sections']):
        name=f'section_{i:03d}';currents=np.eye(count)[i]
        event('solve',f"求解物理段 {i+1}/{count}：{section['section_id']}",32+int(43*i/count))
        energy,field,elapsed=solve_case(out,config,g,solver,name,currents)
        fields.append(field);energies.append(energy);files.append(name+'/field_t0001.vtu')
        timings.append(dict(excitation=section['section_id'],wall_s=elapsed))
    ls=gram(fields);diagonal=np.abs(np.diag(ls)/(2*np.asarray(energies))-1)
    if diagonal.max()>1e-6:raise ValueError('逐元场能与Elmer标量能量不一致。')
    asymmetry=float(np.max(np.abs(ls-ls.T))/np.max(np.abs(ls)))
    if asymmetry>1e-8 or np.linalg.eigvalsh((ls+ls.T)/2).min()<=0:raise ValueError('分段电感矩阵对称性或正定性检查失败。')
    matrix=g['connection_matrix'];c=np.asarray(matrix['values'],dtype=float)
    if matrix['row_sections']!=[s['section_id'] for s in g['physical_sections']]:raise ValueError('连接矩阵行序不一致。')
    ports=matrix['column_ports'];lp=c.T@ls@c;k=lp/np.sqrt(np.outer(np.diag(lp),np.diag(lp)))
    if np.linalg.eigvalsh((lp+lp.T)/2).min()<=0 or np.max(np.abs(k))>1+1e-9:raise ValueError('端口电感矩阵或耦合系数无效。')
    combination=np.linspace(.2,.7,count)*np.where(np.arange(count)%2==0,1,-1)
    event('check','正在做混合正负激励的独立能量校核',78)
    mixed,_,elapsed=solve_case(out,config,g,solver,'combined_check',combination)
    predicted=float(combination@ls@combination/2);mixed_error=abs(mixed/predicted-1)
    if mixed_error>1e-6:raise ValueError('混合激励独立能量校核失败。')
    timings.append(dict(excitation='combined_check',wall_s=elapsed))
    primary=ports.index(config.get('primary_port','P') if config.get('primary_port','P') in ports else ports[0])
    secondary=[i for i in range(len(ports)) if i!=primary]
    short_l=None;short_error=None;short_currents=None
    if secondary:
        event('check','正在做理想副边零磁链约束的独立校核',86)
        currents=np.zeros(len(ports));currents[primary]=1
        currents[secondary]=-np.linalg.solve(lp[np.ix_(secondary,secondary)],lp[secondary,primary])
        short_l=float(lp[primary,primary]+lp[primary,secondary]@currents[secondary])
        energy,_,elapsed=solve_case(out,config,g,solver,'ideal_secondary_shorts_check',c@currents)
        short_error=abs(2*energy/short_l-1)
        if short_error>1e-6:raise ValueError('理想短路组合独立能量校核失败。')
        short_currents=currents.tolist();timings.append(dict(excitation='ideal_secondary_shorts_check',wall_s=elapsed))
    report=dict(schema='transformer-coupling-tool.results.v1',finished_at=now(),classification=config['classification'],
        section_order=[s['section_id'] for s in g['physical_sections']],port_order=ports,primary_port=ports[primary],
        L_sections_H=ls.tolist(),connection_matrix=c.tolist(),L_ports_H=lp.tolist(),k_ports=k.tolist(),
        energies_J=energies,element_to_scalar_energy_relative_errors=diagonal.tolist(),matrix_asymmetry_relative=asymmetry,
        combined_energy_relative_error=mixed_error,ideal_all_secondary_short_Lp_H=short_l,
        ideal_short_energy_relative_error=short_error,ideal_short_port_currents_A=short_currents,
        ideal_short_definition='Zero secondary flux linkage, zero resistance; not a DC short or measured high-frequency leakage.',
        field_files=files,solver=provenance,solve_timings=timings,total_solver_wall_s=sum(t['wall_s'] for t in timings),
        matrix_method='Integral of elemental B_i dot H_j on the same linear mesh; L_ports=C^T L_sections C',
        input_targets_not_fitted=g['design_targets'],mesh_converged=False,air_domain_converged=False,measurement_validated=False,
        limitations=['linear zero-bias magnetostatics','closed equivalent turns; no leads/inter-turn routing',
                     'uniform bundle-current sharing; no circulating-current solve','no high-frequency loss, nonlinear material or capacitance model'])
    write(Path(out)/'results.json',report)
    for name,value,labels in [('L_ports_H.csv',lp,ports),('k_ports.csv',k,ports),('L_sections_H.csv',ls,report['section_order'])]:matrix_csv(Path(out)/name,value,labels)
    field=dict(fields[0]);field['B']=sum(c[i,primary]*f['B'] for i,f in enumerate(fields))
    field['H']=sum(c[i,primary]*f['H'] for i,f in enumerate(fields))
    return report,field


def load_primary(out,report):
    primary=report['port_order'].index(report['primary_port']);weights=np.asarray(report['connection_matrix'])[:,primary]
    combined=None
    for weight,file in zip(weights,report['field_files']):
        if weight==0:continue
        field=load_field(Path(out)/file)
        if combined is None:
            combined=dict(field);combined['B']=weight*field['B'];combined['H']=weight*field['H']
        else:combined['B']+=weight*field['B'];combined['H']+=weight*field['H']
    return combined
