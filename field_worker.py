"""Isolated CLI entry for the bundled transformer field runtime.

Only the worker imports Gmsh / meshio. No Tk GUI is created in this process.
The supervisor retains the Windows Job Object that owns every Elmer child.
"""
from __future__ import annotations

import argparse
from contextlib import ExitStack, redirect_stderr, redirect_stdout
import os
from pathlib import Path
import sys
import tempfile
import traceback


def main(argv=None):
    parser = argparse.ArgumentParser(description='电源设计软件内置变压器场解工作进程')
    parser.add_argument('command', choices=('doctor', 'check', 'cad', 'mesh', 'run'))
    parser.add_argument('--project', type=Path)
    parser.add_argument('--events', type=Path)
    args = parser.parse_args(argv)
    work = Path(os.environ['POWER_DESIGN_FIELD_WORKDIR']).resolve() if os.environ.get(
        'POWER_DESIGN_FIELD_WORKDIR') else Path(tempfile.mkdtemp(prefix='power-design-field-'))
    work.mkdir(parents=True, exist_ok=True)
    os.environ['POWER_DESIGN_FIELD_WORKDIR'] = str(work)
    os.environ.setdefault('MPLCONFIGDIR', str(work / 'matplotlib'))
    os.environ.setdefault('MPLBACKEND', 'Agg')
    with ExitStack() as stack:
        if args.events:
            args.events.parent.mkdir(parents=True, exist_ok=True)
            stream = stack.enter_context(args.events.open('w', encoding='utf-8', buffering=1))
            stack.enter_context(redirect_stdout(stream))
            stack.enter_context(redirect_stderr(stream))
        elif sys.stdout is None or sys.stderr is None:
            stream = stack.enter_context((work / 'worker-console.log').open('w', encoding='utf-8', buffering=1))
            stack.enter_context(redirect_stdout(stream))
            stack.enter_context(redirect_stderr(stream))
        try:
            from transformer_field_runtime.storage import event
            if args.command == 'doctor':
                import gmsh
                import meshio
                import numpy
                import jsonschema
                import matplotlib
                gmsh.initialize(['power-design-field', '-nopopup'])
                try:
                    gmsh.option.setNumber('General.Terminal', 0)
                    # Exercise OCC and the native library, not just Python imports.
                    tag = gmsh.model.occ.addBox(0, 0, 0, 1, 1, 1)
                    gmsh.model.occ.synchronize()
                    volume = gmsh.model.occ.getMass(3, tag)
                    if abs(volume - 1) > 1e-12:
                        raise RuntimeError('内置Gmsh OCC实体自检失败')
                finally:
                    gmsh.finalize()
                event('doctor', '内置场解运行库与Gmsh OCC载入通过', 100,
                      gmsh=gmsh.__version__, meshio=meshio.__version__,
                      numpy=numpy.__version__, matplotlib=matplotlib.__version__,
                      frozen=bool(getattr(sys, 'frozen', False)), work_directory=str(work))
                return 0
            if not args.project:
                raise ValueError('需要 --project 场解设置文件。')
            from transformer_field_runtime.configuration import load_config, validate_config
            from transformer_field_runtime.package import load_package
            config = load_config(args.project)
            loaded = load_package(config['package_path'])
            geometry = validate_config(config, loaded)
            if args.command == 'check':
                event('check', '当前设计、磁芯与求解器输入检查通过', 100,
                      sections=len(geometry['physical_sections']),
                      ports=geometry['connection_matrix']['column_ports'])
                return 0
            from transformer_field_runtime.pipeline import run
            run(config, stage='all' if args.command == 'run' else args.command)
            return 0
        except Exception as error:
            traceback.print_exc()
            from transformer_field_runtime.storage import event
            event('error', str(error))
            return 1


if __name__ == '__main__':
    raise SystemExit(main())
