"""Run the local transformer extractor's supported CLI against a frozen design."""
from __future__ import annotations

import hashlib
import json
import math
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import time
from contextlib import contextmanager

from calculation_scheduler import CalculationCancelled
from transformer_geometry import read_geometry_package, strict_json


def _read(path):
    return strict_json(Path(path).read_bytes())


def _sha(path, cancelled=None):
    with Path(path).open('rb') as source:
        digest = hashlib.sha256()
        for block in iter(lambda: source.read(4 * 1024**2), b''):
            if cancelled and cancelled():
                raise CalculationCancelled()
            digest.update(block)
    return digest.hexdigest()


def _local_path(base, value):
    if not isinstance(value, str) or not value.strip():
        raise ValueError('提取设置缺少本地文件或目录路径')
    return (base / value).resolve()


def _same_number(left, right):
    return (isinstance(left, (int, float)) and isinstance(right, (int, float))
            and math.isclose(left, right, rel_tol=1e-7, abs_tol=1e-11))


def _check_windings(project, geometry):
    bindings = project['connections']
    sections = bindings.get('sections', {})
    ports = bindings.get('ports', {})
    if (set(sections) != {s['section_id'] for s in geometry['physical_sections']}
            or set(ports) != {w['id'] for w in geometry['windings']}
            or project.get('primary_port') != 'P'):
        raise ValueError('提取设置的绕组端口、原边或物理层 ID 与当前设计不匹配，请选择对应设置。')
    for section in geometry['physical_sections']:
        sid = section['section_id']
        overlay = sections[sid]
        for key in ('winding_id', 'turns', 'start_node', 'end_node', 'dot_node', 'direction'):
            if section.get(key) is not None and overlay.get(key) != section[key]:
                raise ValueError(f'{sid} 的 {key} 与设计不符，请核对连接和匝数。')
    for connection in geometry['connections']:
        port = connection['winding_id']
        for key in ('connection', 'section_order', 'other_node', 'dot_node'):
            if connection.get(key) and ports[port].get(key) != connection[key]:
                raise ValueError(f'{port} 的 {key} 与设计接线不符。')
    by_node = {row['node']: row for row in bindings.get('terminals', [])}
    for terminal in geometry['terminals']:
        target = by_node.get(terminal['node'], {})
        for key in ('external_connection', 'net', 'pin'):
            if terminal.get(key) is not None and target.get(key) != terminal[key]:
                raise ValueError(f'端子 {terminal["node"]} 的 {key} 与提取设置不符。')


def bind_solver_project(package_path, project_file, output_directory):
    """Bind a new ZIP while retaining only compatible CAD/material/connection inputs."""
    from zipfile import ZipFile

    package = Path(package_path).resolve(strict=True)
    template = Path(project_file).resolve(strict=True)
    project = _read(template)
    if project.get('schema') != 'transformer-coupling-tool.project.v1':
        raise ValueError('请选择变压器提取器保存的提取设置 JSON。')
    geometry = read_geometry_package(package)
    source_sha = _sha(package)
    core = project['core']
    design_core = geometry['core']
    if core.get('calculator_core_model'):
        model = core['calculator_core_model']
    else:
        reference = _local_path(template.parent, project.get('package_path'))
        if not reference.is_file() or _sha(reference) != project.get('package_sha256'):
            raise ValueError('模板原几何包缺失或已变化，无法核实磁芯型号，请重新保存提取设置。')
        if reference == package:
            model = design_core['calculator_core']
        else:
            with ZipFile(reference) as archive:
                entry = archive.getinfo('resolved-cross-section.json')
                if entry.file_size > 64 * 1024**2:
                    raise ValueError('模板参考几何超过读取上限')
                model = strict_json(archive.read(entry))['core']['calculator_core']
    if model != design_core['calculator_core']:
        raise ValueError(f'磁芯型号不符：当前设计 {design_core["calculator_core"]}，提取模板 {model}。')
    path = _local_path(template.parent, core['path'])
    if not path.is_file() or path.suffix.lower() not in ('.step', '.stp', '.brep'):
        raise ValueError('请在提取设置中选择存在的磁芯实体 STEP 或 BREP。')
    actual_core_sha = _sha(path)
    for sealed in (core.get('sha256'), design_core.get('geometry_sha256')):
        if sealed and sealed.lower() != actual_core_sha:
            raise ValueError('磁芯实体文件与设计或提取设置的 SHA-256 不符。')
    core.update(path=str(path), sha256=actual_core_sha)

    gap = geometry['design_targets'].get('air_gap') or {}
    physical_gap = design_core.get('gap_geometry') or {}
    target_gap = physical_gap.get('length_m', gap.get('gap_m'))
    if target_gap is not None and not _same_number(target_gap, core.get('total_gap_m')):
        raise ValueError('模板气隙与设计指定气隙不符，请核对装配和中柱磨隙。')
    modes = {'half_center_gap': 'center_leg_ground', 'half_spacer': 'spacer'}
    if target_gap and physical_gap.get('type') and core['mode'] in modes and physical_gap['type'] != modes[core['mode']]:
        raise ValueError('模板的气隙加工方式与设计不符。')
    material = project['material']
    if (material['name'].casefold() != design_core['calculator_material'].casefold()
            or gap.get('mu_r') is not None and not _same_number(material['relative_permeability'], gap['mu_r'])):
        raise ValueError('磁材或线性磁导率与设计不匹配，请选择对应材料的提取设置。')
    if material.get('source_file'):
        path = _local_path(template.parent, material['source_file'])
        if not path.is_file():
            raise ValueError('材料来源文件缺失')
        material['source_file'] = str(path)
    for key, source in [('r0_m', 'r0_m_if_circular'), ('z0_m', 'z0_m')]:
        value = geometry['frame'].get(source)
        if value is not None:
            project['frame'][key] = value
    _check_windings(project, geometry)
    solver = project['solver']
    # An explicit per-machine selection takes precedence over stale inherited
    # environment variables (common after moving the complete application).
    elmer = _local_path(template.parent, solver.get('elmer_home') or os.environ.get('ELMER_HOME'))
    if not all((elmer / 'bin' / name).is_file() for name in ('ElmerSolver.exe', 'ElmerGrid.exe')):
        raise ValueError('Elmer 安装目录无效，请核对提取设置的 solver.elmer_home。')
    solver['elmer_home'] = str(elmer)
    project.update(name=geometry['source']['design_id'], package_path=str(package),
                   package_sha256=source_sha, output_root=str(Path(output_directory).resolve()))
    return project


def verify_field_result(run_directory, package_path, *, cancelled=None):
    """Check completion and archived evidence before exposing results for adoption."""
    case = Path(run_directory).resolve(strict=True)
    manifest = _read(case / 'artifact-manifest.json')
    status = _read(case / 'status.json')
    if (manifest.get('schema') != 'transformer-coupling-tool.artifacts.v1'
            or status.get('status') != 'complete' or status.get('report') != 'report.html'):
        raise ValueError('场解或报告未完整完成。')
    stamp = _sha(package_path, cancelled)
    if manifest.get('source_package_sha256') != stamp:
        raise ValueError('场解与本次提交的几何 ZIP 不一致。')
    files = {}
    for entry in manifest['files']:
        name = entry['path']
        path = (case / name).resolve(strict=True)
        if (not path.is_relative_to(case) or path.relative_to(case).as_posix() != name
                or name in files or not path.is_file()):
            raise ValueError('场解产物清单含越界、重复或无效路径。')
        if path.stat().st_size != entry['bytes'] or _sha(path, cancelled) != entry['sha256']:
            raise ValueError(f'场解产物校验失败：{name}')
        files[name] = entry['sha256']
    required = {'report.html', 'report.md', 'results.json', 'status.json', 'inputs/source.zip',
                'inputs/project.json', 'inputs/resolved-geometry.json', 'L_ports_H.csv', 'k_ports.csv',
                'geometry-validation.json', 'mesh-quality.json', 'model_field.png', 'winding_model.png'}
    results = _read(case / 'results.json')
    if (not required.issubset(files) or files['inputs/source.zip'] != stamp
            or results.get('schema') != 'transformer-coupling-tool.results.v1'
            or results.get('original_package_sha256') != stamp):
        raise ValueError('缺少已校验的输入、端口矩阵或正式场解报告。')
    project = _read(case / 'inputs/project.json')
    resolved = _read(case / 'inputs/resolved-geometry.json')
    encoded = json.dumps(project, ensure_ascii=False, separators=(',', ':'), sort_keys=True, allow_nan=False)
    geometry = resolved['effective_geometry']
    field_files = [f'section_{i:03d}/field_t0001.vtu' for i in range(len(geometry['physical_sections']))]
    core_name = 'inputs/core' + Path(project['core']['path']).suffix.lower()
    if (results.get('effective_input_hash') != hashlib.sha256(encoded.encode('utf-8')).hexdigest()
            or project.get('package_sha256') != stamp or resolved.get('source_package_sha256') != stamp
            or core_name not in files or results.get('core_sha256') != files[core_name]
            or project['core'].get('sha256') != files[core_name]
            or results.get('field_files') != field_files or not set(field_files).issubset(files)
            or results.get('section_order') != [s['section_id'] for s in geometry['physical_sections']]
            or results.get('port_order') != geometry['connection_matrix']['column_ports']
            or results.get('connection_matrix') != geometry['connection_matrix']['values']):
        raise ValueError('冻结场解的设置、几何或端口顺序与矩阵不一致。')
    return case


def _stage_runtime_file(src, dst):
    # Native libraries and the embedded archive are read-only inputs at runtime.
    # All editable layouts, preferences, Python sources and caches get private copies.
    if Path(src).suffix.lower() in ('.dll', '.pyd', '.pyz', '.zip'):
        try:
            os.link(src, dst)
            return dst
        except OSError:
            pass  # FAT volumes, separate drives and restricted installations
    return shutil.copy2(src, dst)


def _solver_command(tool_root, runtime):
    """Only the temporary installation receives the extractor's data/runtime cache."""
    if not tool_root or str(tool_root).casefold() == 'builtin':
        if getattr(sys, 'frozen', False):
            return [sys.executable, '--field-worker']
        return [sys.executable, '-E', '-s', '-B', '-X', 'utf8',
                str(Path(__file__).resolve().with_name('desktop_entry.py')), '--field-worker']
    root = Path(tool_root).resolve(strict=True)
    if (root / '变压器耦合参数提取工具').is_dir():
        root = root / '变压器耦合参数提取工具'
    source = root / 'coupling_tool'
    python = root.parent / '.venv/Scripts/python.exe'
    if (root / 'app.py').is_file() and source.is_dir() and python.is_file():
        if runtime.is_relative_to(source.resolve()):
            raise ValueError('结果目录不能放在求解器源码目录内。')
        shutil.copytree(source, runtime / 'coupling_tool', ignore=shutil.ignore_patterns('__pycache__'))
        shutil.copy2(root / 'app.py', runtime / 'app.py')
        return [str(python), '-E', '-s', '-B', '-X', 'utf8', str(runtime / 'app.py')]
    exe_name = '变压器耦合参数提取器.exe'
    exe = root if root.is_file() else root / exe_name
    if not exe.is_file() and (root / 'releases/Windows-x64').is_dir():
        builds = sorted((root / 'releases/Windows-x64').glob('*/' + exe_name), reverse=True)
        exe = builds[0] if builds else exe
    if exe.name != exe_name or not exe.is_file() or not (exe.parent / '_internal').is_dir():
        raise ValueError('未找到本地提取工具及运行库，请选择研究根目录或完整离线版目录。')
    if runtime.is_relative_to((exe.parent / '_internal').resolve()):
        raise ValueError('结果目录不能放在求解器运行库内。')
    shutil.copytree(exe.parent / '_internal', runtime / '_internal', copy_function=_stage_runtime_file)
    shutil.copy2(exe, runtime / exe_name)
    return [str(runtime / exe_name)]


def _diagnostic(path):
    if not path.exists():
        return ''
    with path.open('rb') as stream:
        stream.seek(max(0, path.stat().st_size - 4096))
        lines = stream.read().decode('utf-8', errors='replace').strip().splitlines()
    return lines[-1][:600] if lines else ''


@contextmanager
def _field_process(command, directory, environment, log):
    """Assign the suspended process to a dedicated Windows Job before it can fork Elmer."""
    import _winapi
    import ctypes
    from ctypes import wintypes
    import msvcrt

    system = ctypes.WinDLL('kernel32', use_last_error=True)
    system.CreateJobObjectW.restype = wintypes.HANDLE
    handle = system.CreateJobObjectW(None, None)
    if not handle:
        raise ctypes.WinError(ctypes.get_last_error())
    job = wintypes.HANDLE(handle)
    process = thread = None
    old = ctypes.create_unicode_buffer(32768)
    try:
        class BasicLimits(ctypes.Structure):
            _fields_ = [('process_time', ctypes.c_longlong), ('job_time', ctypes.c_longlong),
                        ('flags', wintypes.DWORD), ('minimum_working_set', ctypes.c_size_t),
                        ('maximum_working_set', ctypes.c_size_t), ('active_processes', wintypes.DWORD),
                        ('affinity', ctypes.c_size_t), ('priority', wintypes.DWORD),
                        ('scheduling', wintypes.DWORD)]

        class ExtendedLimits(ctypes.Structure):
            _fields_ = [('basic', BasicLimits), ('io_counters', ctypes.c_uint64 * 6),
                        ('memory_counters', ctypes.c_size_t * 4)]

        limits = ExtendedLimits()
        limits.basic.flags = 0x2000  # JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE, also on parent exit
        if not system.SetInformationJobObject(job, 9, ctypes.byref(limits), ctypes.sizeof(limits)):
            raise ctypes.WinError(ctypes.get_last_error())
        with open(os.devnull, 'rb') as devnull:
            stdin, stdout = [msvcrt.get_osfhandle(f.fileno()) for f in (devnull, log)]
            info = subprocess.STARTUPINFO(dwFlags=subprocess.STARTF_USESTDHANDLES,
                         hStdInput=stdin, hStdOutput=stdout, hStdError=stdout,
                         lpAttributeList={'handle_list': [stdin, stdout]})
            for value in (stdin, stdout):
                os.set_handle_inheritable(value, True)
            frozen = getattr(sys, 'frozen', False)
            if frozen:
                system.GetDllDirectoryW(len(old), old)
                system.SetDllDirectoryW(None)
            try:
                process, thread, _, _ = _winapi.CreateProcess(
                    command[0], subprocess.list2cmdline(command), None, None, True,
                    subprocess.CREATE_NO_WINDOW | 0x00000004,  # CREATE_SUSPENDED
                    environment, str(directory), info)
            finally:
                if frozen:
                    system.SetDllDirectoryW(old.value or None)
                for value in (stdin, stdout):
                    os.set_handle_inheritable(value, False)
        if not system.AssignProcessToJobObject(job, wintypes.HANDLE(process)):
            raise ctypes.WinError(ctypes.get_last_error())
        if system.ResumeThread(wintypes.HANDLE(thread)) == -1:
            raise ctypes.WinError(ctypes.get_last_error())

        def poll():
            if _winapi.WaitForSingleObject(process, 0) == _winapi.WAIT_OBJECT_0:
                return _winapi.GetExitCodeProcess(process)
            return None
        yield poll
    finally:
        if process is not None:
            # Includes the Python venv launcher, mesh generator and solver. The
            # fallback is for a suspended process whose job assignment failed.
            system.TerminateJobObject(job, 1)
            if _winapi.WaitForSingleObject(process, 1000) == _winapi.WAIT_TIMEOUT:
                _winapi.TerminateProcess(process, 1)
                _winapi.WaitForSingleObject(process, 5000)
            _winapi.CloseHandle(process)
        if thread is not None:
            _winapi.CloseHandle(thread)
        _winapi.CloseHandle(handle)


def run_field_solver(package_path, *, tool_root='', project_file, output_directory, cancelled=None, progress=None):
    """Run CAD, mesh, independent field excitations and report as one background job."""
    if os.name != 'nt':
        raise OSError('本机场解工具需要 Windows x64 和 Elmer。')
    root = Path(output_directory).resolve()
    project = bind_solver_project(package_path, project_file, root)
    if cancelled and cancelled():
        raise CalculationCancelled()
    root.mkdir(parents=True, exist_ok=True)
    job = Path(tempfile.mkdtemp(prefix='field-', dir=root))
    project['output_root'] = str(job)
    config = job / 'extraction-settings.json'
    config.write_text(json.dumps(project, ensure_ascii=False, indent=2, allow_nan=False), encoding='utf-8')
    events, console = job / 'events.log', job / 'console.log'
    complete = None
    with tempfile.TemporaryDirectory(prefix='solver-', dir=job) as temporary:
        runtime = Path(temporary)
        command = _solver_command(tool_root, runtime)
        environment = os.environ.copy()
        for key in ('PYTHONHOME', 'PYTHONPATH', 'PYTHONEXECUTABLE', 'VIRTUAL_ENV'):
            environment.pop(key, None)
        if getattr(sys, 'frozen', False):
            bundle = Path(sys._MEIPASS).resolve()
            environment['PATH'] = os.pathsep.join(p for p in environment.get('PATH', '').split(os.pathsep)
                                                  if p and not Path(p).resolve().is_relative_to(bundle))
        environment.update(MPLCONFIGDIR=str(runtime / 'matplotlib'), PYINSTALLER_RESET_ENVIRONMENT='1',
                           POWER_DESIGN_FIELD_WORKDIR=str(runtime), MPLBACKEND='Agg')
        command += ['run', '--project', str(config), '--events', str(events)]
        events.touch()
        with console.open('wb') as log, events.open('rb') as stream:
            with _field_process(command, job, environment, log) as poll:
                while True:
                    if cancelled and cancelled():
                        raise CalculationCancelled()
                    code = poll()
                    for raw in iter(stream.readline, b''):
                        if not raw.endswith(b'\n'):
                            if code is None:
                                stream.seek(-len(raw), 1)
                            break
                        if raw.startswith(b'@@EVENT '):
                            event = json.loads(raw[8:])
                            if progress:
                                progress(event['message'])
                            if event['stage'] == 'complete':
                                complete = Path(event['output']).resolve()
                    if code is not None:
                        break
                    time.sleep(.25)
            if code or complete is None or complete.parent != job:
                detail = _diagnostic(events) or _diagnostic(console)
                raise RuntimeError(f'变压器场解失败（{code}）。{detail}\n运行日志：{job}')
    if progress:
        progress('报告已生成，正在核对场解文件与本次几何包。')
    return verify_field_result(complete, package_path, cancelled=cancelled)
