from __future__ import annotations
from copy import deepcopy
from datetime import datetime
from pathlib import Path
import shutil
import sys
import uuid

from . import __version__
from .configuration import validate_config
from .package import load_package
from .storage import content_hash,event,now,sha,write


def run(config,stage='all'):
    loaded=load_package(config['package_path']);g=validate_config(config,loaded)
    c=deepcopy(config);c['core']['sha256']=sha(c['core']['path'])
    name=datetime.now().strftime('%Y%m%d-%H%M%S')+'-'+uuid.uuid4().hex[:6]
    out=Path(c['output_root']).resolve()/name;out.mkdir(parents=True,exist_ok=False)
    write(out/'status.json',dict(status='running',stage=stage,started_at=now()))
    event('start','已建立独立运行目录',2,output=str(out))
    try:
        inputs=out/'inputs';inputs.mkdir()
        package=inputs/'source.zip';core=inputs/('core'+Path(c['core']['path']).suffix.lower())
        shutil.copy2(c['package_path'],package);shutil.copy2(c['core']['path'],core)
        if sha(package)!=loaded['sha256'] or sha(core)!=c['core']['sha256']:raise RuntimeError('输入在复制过程中发生变化。')
        write(inputs/'project.json',c)
        # This is a tool-resolved input, not a re-issued calculator geometry package.
        # Keep the original ready/hash claims in source.zip and name the new contract.
        write(inputs/'resolved-geometry.json',dict(schema='transformer-coupling-tool.resolved-input.v1',
              source_package_sha256=loaded['sha256'],source_geometry_sha256=loaded['geometry']['source']['geometry_sha256'],
              original_package_ready=loaded['geometry']['ready'],input_complete=True,
              effective_geometry={k:g[k] for k in ['units','frame','bobbin','windings','physical_sections','connections','connection_matrix','terminals']},
              core=c['core'],material=c['material'],classification=c['classification']))
        (inputs/'cross-section.png').write_bytes(loaded['cross_section_png'])
        source_material=c['material'].get('source_file')
        if source_material and Path(source_material).is_file():shutil.copy2(source_material,inputs/'material-source.json')
        effective=deepcopy(c);effective['package_path']=str(package);effective['core']['path']=str(core)
        from .meshing import build
        mesh=build(out,effective,g,make_mesh=stage!='cad')
        if stage in ('cad','mesh'):
            write(out/'status.json',dict(status='cad_checked' if stage=='cad' else 'mesh_checked',finished_at=now()))
            event('complete','模型检查完成' if stage=='cad' else '网格生成完成',100,output=str(out),stage_only=stage)
            return out
        from .solving import solve_matrix
        report,field=solve_matrix(out,effective,g)
        report.update(tool_version=__version__,frozen_application=bool(getattr(sys,'frozen',False)),
                      original_package_sha256=loaded['sha256'],core_sha256=c['core']['sha256'],
                      effective_input_hash=content_hash(c),package_validation_scope=loaded['validation_scope'])
        write(out/'results.json',report)
        event('report','能量校核通过，正在导出报告与图表',94)
        from .reporting import export_report
        result=export_report(out,report,field,g,c,loaded)
        write(out/'status.json',dict(status='complete',finished_at=now(),report='report.html',
                                     mesh_converged=False,air_domain_converged=False,measurement_validated=False))
        manifest=dict(schema='transformer-coupling-tool.artifacts.v1',tool_version=__version__,created_at=now(),
                      classification=c['classification'],source_package_sha256=loaded['sha256'],
                      files=[dict(path=f.relative_to(out).as_posix(),bytes=f.stat().st_size,sha256=sha(f))
                             for f in sorted(out.rglob('*')) if f.is_file() and f.name!='artifact-manifest.json'])
        write(out/'artifact-manifest.json',manifest)
        event('complete','仿真和报告导出完成',100,output=str(out),report=str(result),
              self_inductance_H=[report['L_ports_H'][i][i] for i in range(len(report['port_order']))],
              port_order=report['port_order'])
        return out
    except BaseException as error:
        write(out/'status.json',dict(status='failed',finished_at=now(),error=str(error)))
        event('error',str(error),output=str(out));raise
