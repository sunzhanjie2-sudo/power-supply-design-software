"""Application service shared by future Web/API clients and today's desktop.

No server, GUI or report libraries are imported at module import time. Formula
modules are deliberately reused rather than translated into another language.
"""
from __future__ import annotations

import copy
from datetime import datetime, timezone
import hashlib
from importlib.metadata import PackageNotFoundError, version
import json
import math
from pathlib import Path
import platform
import tempfile
import os
from typing import Any, Callable, Literal

from . import CONTRACT_VERSION, MODEL_VERSION
from .contracts import content_hash, json_value

Analysis = Literal['selected', 'endpoints']
CancelCallback = Callable[[], bool]
ProgressCallback = Callable[[int, int, str], None]


class SpecValidationError(ValueError):
    def __init__(self, issues):
        self.issues = issues
        super().__init__('; '.join(issue['message'] for issue in issues))


def _parameters(spec):
    from runtime_resources import configure_numeric_threads
    configure_numeric_threads()
    if not isinstance(spec, dict):
        raise SpecValidationError([dict(field='$', code='type', message='设计输入必须为 JSON 对象')])
    from .specification import load_spec
    from .catalog import parameter_catalog
    from power_stage import validate_design_inputs
    try:
        p = copy.deepcopy(load_spec(copy.deepcopy(spec)))
    except (ValueError, TypeError, KeyError, AttributeError, OverflowError) as exc:
        raise SpecValidationError([dict(field='$', code='decode', message=str(exc))]) from exc
    issues = []
    for row in parameter_catalog():
        key, kind = row['name'], row['type']
        if key not in p:
            continue
        value = p[key]
        if key in ('input_capacitors','output_capacitors') and value is None:
            continue  # Legacy scalar banks remain valid until explicitly edited.
        correct = (isinstance(value, (int, float)) and not isinstance(value, bool) if kind == 'number'
                   else isinstance(value, bool) if kind == 'boolean'
                   else isinstance(value, str) if kind == 'string'
                   else isinstance(value, list) if kind == 'array'
                   else isinstance(value, dict))
        if not correct:
            issues.append(dict(field=key, code='type', message=f'{key} 应为 {kind}'))
        elif kind == 'number' and not math.isfinite(value):
            issues.append(dict(field=key, code='finite', message=f'{key} 必须为有限数值'))
    if issues:
        raise SpecValidationError(issues)
    diagnostics = []
    try:
        json_value(p, diagnostics)
    except TypeError as exc:
        raise SpecValidationError([dict(field='$', code='json_type', message=str(exc))]) from exc
    if diagnostics:
        raise SpecValidationError([dict(field=row['path'], code='finite',
            message=row['path']+' 必须为有限数值') for row in diagnostics])
    try:
        # Reuse existing conditional engineering rules; do not duplicate them.
        validate_design_inputs(p)
    except (ValueError, TypeError, KeyError) as exc:
        message = str(exc)
        field = next((key for key in p if message.startswith(key + ' ')), '$')
        raise SpecValidationError([dict(field=field, code='engineering_input', message=message)]) from exc
    return p


def validate_spec(spec: dict[str, Any]) -> dict[str, Any]:
    """Decode and validate inputs without solving the converter.

    Success is not proof of feasibility, convergence or hardware safety.
    """
    try:
        return dict(ok=True, spec=json_value(_parameters(spec)), issues=[], scope='input-validation-only')
    except SpecValidationError as exc:
        return dict(ok=False, spec=None, issues=exc.issues, scope='input-validation-only')


def _provenance(spec):
    root = Path(__file__).resolve().parents[1]
    names = ('capacitor_banks.py','power_stage.py', 'loss_model.py', 'semiconductor.py', 'magnetics.py',
             'waveforms.py', 'capripple.py', 'plants.py', 'loop_tuning.py',
             'design_checks.py', 'isolated_outputs.py', 'coupled_flyback.py',
             'winding_coupling.py', 'transformer_turns.py', 'voltage_nodes.py', 'custom_cores.py',
             'input_voltage_range.py', 'analysis_workflows.py', 'flyback_clamp.py',
             'active_clamp.py', 'mp6005.py', 'multi_output_loop.py', 'output_capacitors.py', 'cross_regulation.py',
             'diode_curves.py', 'mos_curves.py', 'mos_gate_charge.py', 'mos_gate.py',
             'mos_manual.py', 'device_curve_sources.py', 'config_io.py', 'component_management.py',
             'parasitics.py', 'parasitic_ringing.py', 'examples/40W_CCM_FLYBACK.json')
    paths = [root / name for name in names] + sorted((root / 'design_engine').glob('*.py'))
    sources = {path.relative_to(root).as_posix(): hashlib.sha256(path.read_bytes()).hexdigest()
               for path in paths if path.is_file()}
    packages = {}
    for name in ('numpy', 'scipy', 'control', 'matplotlib', 'python-docx', 'openpyxl'):
        try:
            packages[name] = version(name)
        except PackageNotFoundError:
            packages[name] = None
    curves = {key: content_hash(json_value(spec[key])) for key in
              ('mos_miller_curve', 'mos_charge_curve', 'diode_curves') if spec.get(key)}
    return dict(model_version=MODEL_VERSION,
                code_fingerprint=content_hash(sources) if sources else None,
                source_complete=all((root/name).is_file() for name in names),
                source_hashes=sources, python=platform.python_version(), packages=packages,
                curve_hashes=curves, provenance_scope='available-source-files; not a physical accuracy certificate')


def prepare_endpoint_bundle(parameters: dict[str, Any], *, cancelled: CancelCallback | None = None,
                            progress: ProgressCallback | None = None, include_loop: bool = True,
                            include_cross_regulation: bool = True,
                            include_efficiency: bool = True) -> dict[str, Any]:
    """Desktop-compatible preparation; all additional calculations happen here.

    Exporters receive this completed bundle and must not redesign the hardware.
    """
    from input_voltage_range import calculate_input_endpoints
    from calculation_scheduler import calculate_report_efficiency_curve, CalculationCancelled
    cancel = cancelled if cancelled is not None else lambda: False
    bundle = calculate_input_endpoints(copy.deepcopy(parameters), include_loop=include_loop,
        include_cross_regulation=include_cross_regulation, cancelled=cancel, progress=progress)
    if include_efficiency:
        for case in bundle['cases']:
            if cancel():
                raise CalculationCancelled()
            if case.get('result') is not None and not case.get('error'):
                case['efficiency_curve'] = calculate_report_efficiency_curve(
                    dict(p=case['p'], coupled=bool(case['result']['op'].get('coupled_model'))), cancel)
    if cancel():
        raise CalculationCancelled()
    return bundle


def _public_result(value, include_waveforms):
    """Keep canonical wf data, never duplicate private periodic-solver traces."""
    if isinstance(value, dict):
        return {key: _public_result(child, include_waveforms) for key, child in value.items()
                if key != 'coupled_solution' and (include_waveforms or key != 'wf')}
    if isinstance(value, (tuple, list)):
        return [_public_result(child, include_waveforms) for child in value]
    return value  # Arrays are converted/copied once at the strict JSON boundary.


class DesignRun:
    """Owned runtime data plus a versioned, strict-JSON view.

    Consumers get copies, never mutable engine-owned dictionaries. Transfer-
    function objects remain runtime-only; saved JSON is a read-only audit record,
    not a pickle or a promise of bit-identical re-execution on another platform.
    """
    def __init__(self, spec: dict[str, Any], bundle: dict[str, Any],
                 analysis: Analysis, options: dict[str, bool]):
        self._spec = copy.deepcopy(spec)
        self._bundle = copy.deepcopy(bundle)
        self._analysis = analysis
        self._options = dict(options)
        self._created = datetime.now(timezone.utc).isoformat()
        self._provenance = _provenance(self._spec)

    def runtime_bundle(self) -> dict[str, Any]:
        return copy.deepcopy(self._bundle)

    @property
    def analysis(self) -> Analysis:
        return self._analysis

    def reports(self) -> list[dict[str, Any]]:
        from .reporting import report_for_result
        reports = []
        for case in self._bundle['cases']:
            if case.get('error') or case.get('result') is None:
                report = dict(ok=False, error=case.get('error') or 'Missing calculation result')
            else:
                public = {key: copy.deepcopy(value) for key, value in case['p'].items() if not key.startswith('_')}
                report = report_for_result(case['p'], case['result'], public)
            reports.append(dict(id=case['id'], V_in=case['voltage'], report=report))
        return copy.deepcopy(reports)

    def legacy_report(self) -> dict[str, Any]:
        """Preserve the original scalar/range API keys and numerical values."""
        from .reporting import report_for_result
        case = self._bundle['cases'][0]
        context = self._bundle if 'V_in_min' in self._spec else None
        return report_for_result(case['p'], case['result'], self._spec, context)

    def legacy_endpoints(self) -> dict[str, Any]:
        cases = self.reports()
        return dict(base_spec=copy.deepcopy(self._bundle['base_spec']),
                    hardware=copy.deepcopy(self._bundle['hardware']),
                    hardware_reference='Vinmin', fixed_hardware=self._bundle['fixed_hardware'],
                    same_voltage=self._bundle['same_voltage'], cases=cases,
                    ok=all(case['report']['ok'] for case in cases),
                    cross_regulation=copy.deepcopy(self._bundle.get('cross_regulation')))

    def to_dict(self, *, include_waveforms: bool = True, include_details: bool = True) -> dict[str, Any]:
        cases = []
        for case, report in zip(self._bundle['cases'], self.reports()):
            result = _public_result(case.get('result'), include_waveforms) if include_details else None
            cases.append(dict(id=case['id'], V_in=case['voltage'],
                parameters={key: value for key, value in case['p'].items() if not key.startswith('_')},
                result=result, summary=report['report'], checks=case.get('checks', []),
                error=case.get('error'), loop_error=case.get('loop_error'),
                efficiency_curve=case.get('efficiency_curve')))
        diagnostics = []
        payload = json_value(dict(schema=CONTRACT_VERSION, model_version=MODEL_VERSION,
            analysis=self.analysis, options=dict(self._options, include_waveforms=include_waveforms,
                                               include_details=include_details),
            spec=self._spec, hardware=self._bundle.get('hardware', {}),
            hardware_reference=self._bundle.get('hardware_reference'),
            fixed_hardware=self._bundle.get('fixed_hardware', False), cases=cases,
            cross_regulation=self._bundle.get('cross_regulation'), provenance=self._provenance,
            ok=all(case['summary'].get('ok', False) for case in cases)), diagnostics)
        payload['numeric_diagnostics'] = diagnostics
        payload['snapshot_id'] = content_hash(payload)
        payload['created_at'] = self._created
        return payload

    def save(self, path: str | Path, *, include_waveforms: bool = True) -> str:
        destination = Path(path)
        destination.parent.mkdir(parents=True, exist_ok=True)
        payload = self.to_dict(include_waveforms=include_waveforms)
        # Interrupted writes never leave a half-written final engineering record.
        temporary = None
        try:
            with tempfile.NamedTemporaryFile(mode='w', encoding='utf-8', dir=destination.parent,
                                             prefix=destination.name + '.', suffix='.tmp', delete=False) as stream:
                temporary = stream.name
                json.dump(payload, stream, ensure_ascii=False, allow_nan=False, indent=2)
                stream.write('\n')
            os.replace(temporary, destination)
        finally:
            if temporary is not None and os.path.exists(temporary):
                os.unlink(temporary)
        return payload['snapshot_id']


def read_snapshot(path: str | Path) -> dict[str, Any]:
    def reject_constant(value):
        raise ValueError(f'Invalid JSON numeric token: {value}')
    payload = json.loads(Path(path).read_text(encoding='utf-8-sig'), parse_constant=reject_constant)
    if not isinstance(payload, dict) or payload.get('schema') != CONTRACT_VERSION:
        raise ValueError('不支持的设计快照版本')
    content = {key: value for key, value in payload.items() if key not in ('snapshot_id', 'created_at')}
    if payload.get('snapshot_id') != content_hash(content):
        raise ValueError('设计快照内容哈希不匹配，文件可能被修改或损坏')
    return payload


def calculate(spec: dict[str, Any], *, analysis: Analysis = 'selected', include_loop: bool = True,
              include_cross_regulation: bool = True, include_efficiency: bool = False,
              progress: ProgressCallback | None = None,
              cancelled: CancelCallback | None = None) -> DesignRun:
    if analysis not in ('selected', 'endpoints'):
        raise ValueError("analysis 必须为 'selected' 或 'endpoints'")
    return calculate_parameters(_parameters(spec), analysis=analysis, include_loop=include_loop,
        include_cross_regulation=include_cross_regulation, include_efficiency=include_efficiency,
        progress=progress, cancelled=cancelled)


def calculate_parameters(parameters: dict[str, Any], *, analysis: Analysis = 'selected',
                         include_loop: bool = True, include_cross_regulation: bool = True,
                         include_efficiency: bool = False, progress: ProgressCallback | None = None,
                         cancelled: CancelCallback | None = None) -> DesignRun:
    """Internal normalized-SI entry; external clients should use calculate()."""
    from input_voltage_range import (_cancellation_scope, has_input_voltage_range,
                                    calculate_input_operating_point)
    from .calculation import build_snapshot
    options = dict(include_loop=include_loop, include_cross_regulation=include_cross_regulation if analysis == 'endpoints' else False,
                   include_efficiency=include_efficiency)
    p = copy.deepcopy(parameters)
    with _cancellation_scope(cancelled):
        if analysis == 'endpoints':
            bundle = prepare_endpoint_bundle(p, cancelled=cancelled, progress=progress, **options)
        elif analysis == 'selected':
            snap = (calculate_input_operating_point(p, include_loop=include_loop) if has_input_voltage_range(p)
                    else build_snapshot(p, include_loop=include_loop))
            label = ('Vinmax' if p.get('input_voltage_case') == 'max' else 'Vinmin') if has_input_voltage_range(p) else 'Nominal'
            case = dict(id=label, voltage=snap['p']['V_in'], p=snap['p'], result=snap['res'],
                        models=snap['models'], checks=snap['checks'], loop_error=snap['loop_error'], error=None)
            if include_efficiency:
                from calculation_scheduler import calculate_report_efficiency_curve
                case['efficiency_curve'] = calculate_report_efficiency_curve(
                    dict(p=case['p'], coupled=bool(case['result']['op'].get('coupled_model'))),
                    cancelled if cancelled is not None else lambda: False)
            bundle = dict(base_spec=p, hardware=snap.get('hardware', {}),
                hardware_reference='Vinmin' if has_input_voltage_range(p) else None,
                fixed_hardware=snap.get('fixed_hardware', False), cases=[case])
        else:
            raise ValueError("analysis 必须为 'selected' 或 'endpoints'")
    return DesignRun(p, bundle, analysis, options)


def export_report(run: DesignRun, path: str | Path, *, compensation_state: dict | None = None,
                  mos_real_time: bool = False) -> dict[str, Any]:
    """Author only: consumes a prepared run, never silently solves new points."""
    if not isinstance(run, DesignRun) or run.analysis != 'endpoints':
        raise ValueError("报告需要 analysis='endpoints' 的设计快照")
    suffix = Path(path).suffix.lower()
    if suffix not in ('.docx', '.xlsx'):
        raise ValueError('报告格式必须为 .docx 或 .xlsx')
    bundle = run.runtime_bundle()
    if any(case.get('result') is not None and not case.get('error') and not case.get('efficiency_curve')
           for case in bundle['cases']):
        raise ValueError('快照缺少效率扫描；请先以 include_efficiency=True 计算，导出阶段不会补算')
    if suffix == '.xlsx':
        from report_xlsx import export_input_range_xlsx as writer
    else:
        from input_range_report import export_input_range_docx as writer
    return writer(path, bundle, compensation_state=compensation_state, mos_real_time=mos_real_time)
