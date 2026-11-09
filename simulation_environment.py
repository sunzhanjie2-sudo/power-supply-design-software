"""Machine-local solvers and relocatable, CAD-only magnetic model profiles.

No winding, material, electrical design or old field result is copied into a
model profile. Those inputs always come from the current calculator snapshot.
"""
from __future__ import annotations

import copy
import hashlib
import json
import math
import os
from pathlib import Path
import shutil
import struct
import subprocess
import sys
import tempfile
from zipfile import ZipFile, ZIP_DEFLATED

from ui_preferences import preferences_path

SCHEMA = 'power-design.simulation-environment.v1'
MODEL_SCHEMA = 'power-design.core-model.v1'
MODEL_FIELDS = ('core_model', 'core_mode', 'brep_unit', 'translation_mm', 'rotation_deg',
                'center_leg_radius_m', 'gap_center_z_m', 'r0_m', 'z0_m', 'core_source')
MAX_CAD_BYTES = 128 * 1024**2


def core_name(config):
    value = config.get('core_choice', '')
    return str(value.get('v', '') if isinstance(value, dict) else value)


def _settings_file():
    return preferences_path().with_name('simulation-environment.json')


def _read(path):
    try:
        value = json.loads(Path(path).read_text('utf-8-sig'))
        return value if isinstance(value, dict) else {}
    except (OSError, ValueError):
        return {}


def _write(path, value):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(mode='w', encoding='utf-8', dir=path.parent,
                                     suffix='.tmp', delete=False) as stream:
        temporary = Path(stream.name)
        try:
            json.dump(value, stream, ensure_ascii=False, indent=2, allow_nan=False)
        except BaseException:
            temporary.unlink(missing_ok=True)
            raise
    try:
        temporary.replace(path)
    finally:
        temporary.unlink(missing_ok=True)


def _model_root():
    # This optional sibling folder travels with a complete desktop directory.
    if getattr(sys, 'frozen', False):
        return Path(sys.executable).resolve().parent / 'simulation-models'
    return Path(__file__).resolve().parent / 'user_data' / 'simulation-models'


def _sha(path):
    h = hashlib.sha256()
    with Path(path).open('rb') as stream:
        for block in iter(lambda: stream.read(4 * 1024**2), b''):
            h.update(block)
    return h.hexdigest()


def normalize_elmer(value):
    path = Path(str(value or '').strip()).expanduser()
    if path.name.casefold() in ('elmersolver.exe', 'elmergrid.exe'):
        path = path.parent
    if path.name.casefold() == 'bin':
        path = path.parent
    return str(path.resolve()) if str(value or '').strip() else ''


def find_elmer():
    candidates = [os.environ.get('ELMER_HOME', '')]
    exe = shutil.which('ElmerSolver.exe')
    if exe:
        candidates.append(exe)
    for base in (os.environ.get('ProgramFiles'), os.environ.get('ProgramFiles(x86)')):
        if base:
            candidates.extend(str(p) for p in Path(base).glob('Elmer*'))
    for value in candidates:
        if value:
            root = Path(normalize_elmer(value))
            if all((root / 'bin' / name).is_file() for name in ('ElmerSolver.exe', 'ElmerGrid.exe')):
                return str(root)
    return ''


def from_legacy_template(path):
    """Import CAD placement only; never retain its old ZIP or winding overlay."""
    path = Path(path).resolve(strict=True)
    value = _read(path)
    if value.get('schema') != 'transformer-coupling-tool.project.v1':
        raise ValueError('不是可迁移的旧提取设置 JSON。')
    core, solver, frame = value.get('core', {}), value.get('solver', {}), value.get('frame', {})
    cad = (path.parent / core.get('path', '')).resolve()
    if not cad.is_file() or cad.suffix.lower() not in ('.step', '.stp', '.brep'):
        raise ValueError('旧设置引用的磁芯实体不存在，请重新选择磁芯模型文件。')
    return dict(core_path=str(cad), core_model=core.get('calculator_core_model', ''),
                core_mode=core.get('mode', 'assembled'), brep_unit=core.get('brep_unit', 'mm'),
                translation_mm=core.get('translation_mm', [0., 0., 0.]),
                rotation_deg=core.get('rotation_deg', [0., 0., 0.]),
                center_leg_radius_m=core.get('center_leg_radius_m'),
                gap_center_z_m=core.get('gap_center_z_m', 0.),
                r0_m=frame.get('r0_m'), z0_m=frame.get('z0_m'),
                core_source=core.get('source') or '从已有提取设置迁移CAD定位，需核对当前磁芯。',
                elmer_home=normalize_elmer(path.parent / solver['elmer_home']) if solver.get('elmer_home') else '',
                mesh_profile=solver.get('mesh_profile', 'standard'),
                air_radius_m=solver.get('air_radius_m', .05), timeout_s=solver.get('timeout_s', 1200))


def load_environment(config):
    from spice_runtime import find_ltspice
    name = core_name(config)
    local = _read(_settings_file())
    result = dict(elmer_home=local.get('elmer_home') or find_elmer(), ltspice=find_ltspice() or '',
                  core_path='', core_model=name, core_mode='assembled', brep_unit='mm',
                  translation_mm=[0., 0., 0.], rotation_deg=[0., 0., 0.],
                  center_leg_radius_m=None, gap_center_z_m=0., r0_m=None, z0_m=None,
                  core_source='', mesh_profile=local.get('mesh_profile', 'standard'),
                  air_radius_m=local.get('air_radius_m', .05), timeout_s=local.get('timeout_s', 1200))
    # Prefer a relative sibling model if the program directory was moved.
    models = _read(_model_root() / 'index.json').get('models') or {}
    for saved in (models.get(name), (local.get('models') or {}).get(name)):
        if not isinstance(saved, dict):
            continue
        saved = copy.deepcopy(saved)
        cad = (_model_root() / saved.get('core_path', '')).resolve()
        if cad.is_file() and _sha(cad) == saved.get('core_sha256'):
            saved['core_path'] = str(cad)
            result.update(saved)
            break
    if not result['core_path']:
        # One-time migration of existing settings. Never needed on a new PC.
        from transformer_sim_ui import _read_settings, _matching_template
        old = _read_settings()
        template = _matching_template(old.get('tool_root', ''), name, old)
        if template:
            try:
                migrated = from_legacy_template(template)
                if not migrated.get('core_model') or migrated['core_model'] == name:
                    result.update(migrated, core_model=name)
            except (OSError, ValueError, KeyError, TypeError):
                pass
    # The current design owns an explicitly configured winding frame.
    frame = ((config.get('winding_config') or {}).get('model_3d') or {}).get('frame') or {}
    for target, source in [('r0_m', 'r0_m_if_circular'), ('z0_m', 'z0_m')]:
        if frame.get(source) is not None:
            result[target] = frame[source]
    if local.get('elmer_home'):
        result['elmer_home'] = normalize_elmer(local['elmer_home'])
    return result


def _finite(value, label, positive=False):
    if isinstance(value, bool) or not isinstance(value, (float, int)) or not math.isfinite(value):
        raise ValueError(label + '需要有限数值。')
    if positive and value <= 0:
        raise ValueError(label + '必须大于0。')


def validate_model(environment, name=None):
    env = copy.deepcopy(environment)
    path = Path(str(env.get('core_path') or '')).expanduser()
    if not path.is_file() or path.suffix.lower() not in ('.step', '.stp', '.brep'):
        raise ValueError('请选择磁芯实体 STEP/STP/BREP 文件；不支持仅含表面的 STL。')
    if path.stat().st_size > MAX_CAD_BYTES:
        raise ValueError('磁芯文件超过128 MiB上限。')
    if name and env.get('core_model') != name:
        raise ValueError('登记的磁芯型号与当前设计不同，请为当前型号登记模型。')
    if env.get('core_mode') not in ('assembled', 'half_center_gap', 'half_spacer'):
        raise ValueError('请选择已装配实体、中柱磨隙半芯或垫片半芯。')
    if env.get('brep_unit') not in ('mm', 'm'):
        raise ValueError('BREP单位需要mm或m。')
    for key, label in [('translation_mm', '平移'), ('rotation_deg', '旋转')]:
        if not isinstance(env.get(key), (list, tuple)) or len(env[key]) != 3:
            raise ValueError(label + '需要X/Y/Z三个值。')
        for value in env[key]:
            _finite(value, label)
    _finite(env.get('r0_m'), '绕组内侧半径r0', True)
    _finite(env.get('z0_m'), '绕组轴向起点z0')
    _finite(env.get('gap_center_z_m'), '气隙中心Z')
    if env['core_mode'] == 'half_center_gap':
        _finite(env.get('center_leg_radius_m'), '中柱半径', True)
    if not str(env.get('core_source') or '').strip():
        raise ValueError('请填写磁芯/坐标来源，例如厂家型号或已核对的装配参考。')
    env['core_path'] = str(path.resolve())
    return env


def _model_record(env):
    return dict(schema=MODEL_SCHEMA, **{key: copy.deepcopy(env.get(key)) for key in MODEL_FIELDS},
                core_sha256=_sha(env['core_path']))


def save_environment(config, environment):
    env = validate_model(environment, core_name(config))
    env['elmer_home'] = normalize_elmer(env.get('elmer_home'))
    local = _read(_settings_file())
    record = _model_record(env)
    relative = Path(record['core_sha256'][:20]) / ('core' + Path(env['core_path']).suffix.lower())
    last_error = None
    for root in (_model_root(), _settings_file().parent / 'simulation-models'):
        target = root / relative
        try:
            target.parent.mkdir(parents=True, exist_ok=True)
            if env['core_path'] != str(target.resolve()):
                shutil.copy2(env['core_path'], target)
            if _sha(target) != record['core_sha256']:
                raise ValueError('登记模型复制后的哈希不同，未保存配置。')
            record['core_path'] = relative.as_posix()
            catalog = _read(root / 'index.json')
            catalog.setdefault('models', {})[core_name(config)] = record
            _write(root / 'index.json', catalog)
            last_error = None
            break
        except OSError as exc:
            last_error = exc
    if last_error is not None:
        raise last_error
    local.update(schema=SCHEMA, elmer_home=env['elmer_home'], mesh_profile=env.get('mesh_profile', 'standard'),
                 air_radius_m=env.get('air_radius_m', .05), timeout_s=env.get('timeout_s', 1200))
    saved = copy.deepcopy(record)
    # Absolute local fallback is never written into the portable catalog/ZIP.
    saved['core_path'] = str(target.resolve())
    local.setdefault('models', {})[core_name(config)] = saved
    _write(_settings_file(), local)
    if env.get('ltspice'):
        from spice_runtime import set_ltspice
        set_ltspice(env['ltspice'])
    env['core_path'] = str(target.resolve())
    return env


def export_model_package(environment, path, core_name):
    env = validate_model(environment, core_name)
    record = _model_record(env)
    record['core_path'] = 'core' + Path(env['core_path']).suffix.lower()
    with ZipFile(path, 'w', ZIP_DEFLATED) as archive:
        archive.writestr('model.json', json.dumps(record, ensure_ascii=False, indent=2, allow_nan=False))
        archive.write(env['core_path'], record['core_path'])
    return str(Path(path).resolve())


def import_model_package(path, core_name):
    with ZipFile(path) as archive:
        names = archive.namelist()
        if len(names) != 2 or len(set(names)) != 2 or 'model.json' not in names:
            raise ValueError('模型包只应包含model.json及一个磁芯实体。')
        if archive.getinfo('model.json').file_size > 64 * 1024:
            raise ValueError('模型配置文件过大。')
        try:
            record = json.loads(archive.read('model.json'))
        except (ValueError, UnicodeError):
            raise ValueError('模型包配置不是有效JSON。') from None
        if not isinstance(record, dict) or set(record) - set(MODEL_FIELDS) - {'schema', 'core_path', 'core_sha256'}:
            raise ValueError('模型包配置结构或字段无效。')
        filename = record.get('core_path')
        if (record.get('schema') != MODEL_SCHEMA or record.get('core_model') != core_name
                or filename not in ('core.step', 'core.stp', 'core.brep') or filename not in names):
            raise ValueError('模型包版本、磁芯型号或实体文件不符。')
        member = archive.getinfo(filename)
        if member.file_size > MAX_CAD_BYTES:
            raise ValueError('磁芯实体超过128 MiB上限。')
        blob = archive.read(filename)
    digest = hashlib.sha256(blob).hexdigest()
    if digest != record.get('core_sha256'):
        raise ValueError('模型包实体哈希校验失败。')
    root = _settings_file().parent / 'imported-core-models' / digest[:20]
    root.mkdir(parents=True, exist_ok=True)
    cad = root / filename
    cad.write_bytes(blob)
    record['core_path'] = str(cad.resolve())
    return validate_model(record, core_name)


def _windows_x64_exe(path):
    with Path(path).open('rb') as stream:
        data = stream.read(64)
        if len(data) < 64 or data[:2] != b'MZ':
            return False
        stream.seek(struct.unpack_from('<I', data, 60)[0])
        header = stream.read(6)
    return len(header) == 6 and header[:4] == b'PE\0\0' and header[4:] == b'\x64\x86'


def check_environment(environment, require_spice=True, probe=False):
    checks = []
    def check(name, ok, message):
        checks.append(dict(name=name, ok=bool(ok), message=message))
    root = Path(normalize_elmer(environment.get('elmer_home')) or '.')
    for name in ('ElmerSolver.exe', 'ElmerGrid.exe'):
        path = root / 'bin' / name
        try:
            ok = path.is_file() and _windows_x64_exe(path)
        except (OSError, ValueError, struct.error):
            ok = False
        check(name, ok, str(path) if ok else '未找到有效Windows x64程序，请选择完整Elmer安装目录。')
    library = root / 'share' / 'elmersolver' / 'lib'
    check('Elmer运行库', library.is_dir(), str(library) if library.is_dir() else '缺少share/elmersolver/lib；仅复制两个exe不足以运行。')
    try:
        validate_model(environment, environment.get('core_model'))
        check('磁芯与定位配置', True, '文件与输入值完整；真实实体、装配、气隙和绕组相交检查在准备阶段执行。')
    except (ValueError, OSError) as exc:
        check('磁芯与定位配置', False, str(exc))
    if require_spice:
        exe = Path(environment.get('ltspice') or '.')
        check('LTspice', exe.is_file() and exe.suffix.lower() == '.exe', str(exe))
    if environment.get('mesh_profile') not in ('coarse', 'standard', 'fine'):
        check('网格档位', False, '请选择coarse、standard或fine。')
    for key, label in [('air_radius_m', '空气域半径'), ('timeout_s', '单工况超时')]:
        try:
            _finite(environment.get(key), label, True)
        except ValueError as exc:
            check(label, False, str(exc))
    if probe:
        # Isolated subprocess, same dispatch as the production worker; never
        # imports Gmsh into the live Tk process or runs an electrical solver.
        with tempfile.TemporaryDirectory(prefix='power-design-doctor-') as temporary:
            events = Path(temporary) / 'events.log'
            cmd = [sys.executable]
            if not getattr(sys, 'frozen', False):
                cmd.append(str(Path(__file__).with_name('desktop_entry.py')))
            cmd += ['--field-worker', 'doctor', '--events', str(events)]
            env = os.environ.copy()
            for key in ('PYTHONHOME', 'PYTHONPATH', 'PYTHONEXECUTABLE', 'VIRTUAL_ENV'):
                env.pop(key, None)
            env.update(POWER_DESIGN_FIELD_WORKDIR=temporary, PYINSTALLER_RESET_ENVIRONMENT='1')
            try:
                done = subprocess.run(cmd, cwd=temporary, env=env, capture_output=True, timeout=35,
                                      creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
                details = events.read_text('utf-8', errors='replace')[-1600:] if events.is_file() else ''
                check('内置提取运行库', done.returncode == 0 and 'doctor' in details,
                      details or done.stderr.decode('utf-8', errors='replace')[-1600:])
            except (OSError, subprocess.TimeoutExpired) as exc:
                check('内置提取运行库', False, str(exc))
    return dict(ok=all(item['ok'] for item in checks), checks=checks,
                scope='Windows x64；文件/运行库检查不代表磁场收敛或电路验证通过。')
