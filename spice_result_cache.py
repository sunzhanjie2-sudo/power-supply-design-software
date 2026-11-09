"""Bounded local cache of validated nominal evidence, never incomplete RAW data.

Exact generated deck, simulator identity, design inputs and post-processing
implementation all participate in the key. Study selections do not invalidate
an otherwise identical nominal run. No pickle or arbitrary cached file paths.
"""
from __future__ import annotations

import hashlib
import importlib.util
import json
import os
from pathlib import Path
import time
import types
import uuid
import zipfile

SCHEMA = 3
MAX_ENTRIES = 6
MAX_BYTES = 64 * 1024 * 1024
MAX_ENTRY_BYTES = 16 * 1024 * 1024


def cache_key(files, case, settings, executable, processors):
    from design_engine.contracts import canonical_json, json_value
    digest = hashlib.sha256()
    path = Path(executable).resolve()
    stat = path.stat()
    digest.update(f'{SCHEMA}|{path}|{stat.st_size}|{stat.st_mtime_ns}'.encode())
    for name, data in sorted(files.items()):
        if name.endswith(('.cir', '.inc', '.lib')):
            digest.update(name.encode());digest.update(data)
    parameters = {k:v for k,v in case['p'].items() if k != 'spice_config'}
    # Including the full result makes changes in the analytical engine invalidate
    # the comparison even if the physical netlist remains identical.
    payload = dict(parameters=parameters, result=case['result'], voltage=case['voltage'],
                   tolerance=settings['comparison_tolerance_pct'], cycle=settings['cycle_tolerance_pct'])
    def without_execution_config(value):
        if isinstance(value,dict):
            return {k:without_execution_config(v) for k,v in value.items() if k!='spice_config'}
        if isinstance(value,list):return [without_execution_config(v) for v in value]
        return value
    # Aggregate results embed their original input dictionaries at several
    # depths. The exact deck already covers controller settings; execution
    # selections nested there must not turn quick -> full into a cache miss.
    digest.update(canonical_json(without_execution_config(json_value(payload))).encode())
    # marshal's reference/intern flags may change after first execution on
    # CPython 3.13. Hash semantic code content, not its live serialization.
    def code_signature(code):
        def constant(value):
            if isinstance(value,types.CodeType):return code_signature(value)
            if isinstance(value,frozenset):return tuple(sorted((constant(v) for v in value),key=repr))
            if isinstance(value,tuple):return tuple(constant(v) for v in value)
            return value
        return (code.co_code,code.co_names,code.co_varnames,code.co_freevars,code.co_cellvars,
                tuple(constant(v) for v in code.co_consts))
    for function in processors:digest.update(repr(code_signature(function.__code__)).encode())
    # Include helper implementations as well as the top-level functions. Load
    # code through the module loader so source and frozen PyInstaller builds
    # both invalidate evidence when RAW parsing or quality checks change.
    modules = ['spice_runtime', 'spice_analysis']
    topology = parameters.get('topology')
    if topology == 'FLYBACK':modules.append('flyback_cap_boundary')
    if topology == 'QR-FLYBACK':modules.append('qr_spice_analysis')
    if topology == 'ACF-FORWARD':modules.append('acf_spice')
    for name in modules:
        spec = importlib.util.find_spec(name)
        loader = getattr(spec, 'loader', None)
        if not hasattr(loader, 'get_code'):raise ValueError('无法校验仿真后处理版本')
        code = loader.get_code(name)
        if not isinstance(code, types.CodeType):raise ValueError('无法校验仿真后处理版本')
        digest.update(name.encode());digest.update(repr(code_signature(code)).encode())
    import numpy as np
    digest.update(np.__version__.encode())
    return digest.hexdigest()


class NominalCache:
    def __init__(self, root=None):
        self.root = Path(root or os.environ.get('POWER_DESIGN_SPICE_CACHE') or
                         Path(os.environ.get('LOCALAPPDATA', Path.home())) / 'PowerDesign' / 'spice-cache')

    def load(self, key):
        try:
            path = self.root / (key + '.zip')
            if path.stat().st_size > MAX_ENTRY_BYTES:return None
            with zipfile.ZipFile(path) as archive:
                if sum(i.file_size for i in archive.infolist()) > MAX_ENTRY_BYTES:return None
                value = json.loads(archive.read('evidence.json'))
                log = archive.read('Flyback.log')
            record = value['record']
            if (value['schema'] != SCHEMA or value['key'] != key or not record['complete']
                    or not record['nominal_comparable'] or record['fault_test']):return None
            if not all(k in record for k in ('measurements','periodicity','startup','switching','branches','source_hashes')):return None
            return record, log, value['created_at']
        except (OSError, ValueError, KeyError, TypeError, zipfile.BadZipFile):
            return None

    def store(self, key, record, log):
        if not record.get('complete') or not record.get('nominal_comparable') or record.get('fault_test'):return
        pending = None
        try:
            payload = json.dumps(dict(schema=SCHEMA, key=key, created_at=time.strftime('%Y-%m-%d %H:%M:%S'),
                                      record=record), ensure_ascii=False, allow_nan=False).encode()
            if len(payload) + len(log) > MAX_ENTRY_BYTES:return
            self.root.mkdir(parents=True, exist_ok=True)
            pending = self.root / (uuid.uuid4().hex + '.tmp')
            # One attempt: tempfile retries PermissionError for a very long
            # time on Windows read-only caches, which must never stall export.
            with pending.open('xb') as stream:
                with zipfile.ZipFile(stream, 'w', zipfile.ZIP_DEFLATED) as archive:
                    archive.writestr('evidence.json', payload);archive.writestr('Flyback.log', log)
            os.replace(pending, self.root / (key + '.zip'));pending = None
            entries = sorted(self.root.glob('*.zip'), key=lambda p:p.stat().st_mtime, reverse=True)
            total = 0
            for index, path in enumerate(entries):
                total += path.stat().st_size
                if index >= MAX_ENTRIES or total > MAX_BYTES:path.unlink()
        except (OSError, ValueError, TypeError):
            pass  # Cache failure never changes a valid simulation outcome.
        finally:
            if pending is not None:
                try:pending.unlink(missing_ok=True)
                except OSError:pass
