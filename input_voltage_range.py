"""Input-voltage requirements and fixed-hardware endpoint calculations.

Import-safe: configuration/UI startup must not import the scientific or control
stack merely to resolve Vinmin/Vinmax.  Existing numerical engines still accept
one scalar ``V_in``; only explicit UI/API/report boundaries resolve the range.
"""
import copy
import math
from contextlib import contextmanager


RANGE_KEYS = ('V_in_min', 'V_in_max', 'input_voltage_case')


def has_input_voltage_range(spec):
    return any(key in spec for key in RANGE_KEYS)


def normalize_input_voltage_spec(spec):
    """Return a private SI snapshot with a validated range and selected Vin.

    A legacy scalar migrates to equal endpoints, never an invented +/- range.
    If either endpoint is explicitly supplied both are required.  This function
    does not decode display units: ``config_io.decode_config`` does that first.
    """
    result = copy.deepcopy(spec)
    present = ('V_in_min' in result, 'V_in_max' in result)
    if any(present) and not all(present):
        raise ValueError('输入电压范围必须同时填写 V_in_min 和 V_in_max')
    if all(present):
        lo, hi = result['V_in_min'], result['V_in_max']
    else:
        if 'V_in' not in result:
            raise ValueError('缺少输入电压 V_in 或 V_in_min / V_in_max')
        lo = hi = result['V_in']
    for name, value in (('V_in_min', lo), ('V_in_max', hi)):
        if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value) or value <= 0:
            raise ValueError(f'{name} 必须为有限正数')
    if lo > hi:
        raise ValueError('输入电压下限 V_in_min 不能大于上限 V_in_max')
    selection = result.get('input_voltage_case', 'min')
    if selection not in ('min', 'max'):
        raise ValueError("input_voltage_case 必须为 'min' 或 'max'")
    result.update(V_in_min=float(lo), V_in_max=float(hi),
                  input_voltage_case=selection,
                  V_in=float(lo if selection == 'min' else hi))
    return result


@contextmanager
def _cancellation_scope(cancelled):
    # Cooperate both with LatestCalculationWorker and headless callers.  Restore
    # its thread-local predicate even when a solver or loop build is cancelled.
    from calculation_scheduler import _CURRENT, check_calculation_cancelled
    previous = getattr(_CURRENT, 'cancelled', None)
    if cancelled is not None:
        _CURRENT.cancelled = lambda: bool((previous and previous()) or cancelled())
    try:
        check_calculation_cancelled()
        yield
        check_calculation_cancelled()
    finally:
        _CURRENT.cancelled = previous


def _gate_context(result,parameters):
    """Reuse equal electrical results without mislabelling a manual endpoint."""
    gate=result.get('semi',{}).get('switch',{}).get('gate',{})
    selected=parameters.get('input_voltage_case','min')
    if not gate.get('manual_case') or gate['manual_case']==selected:return result
    updated=dict(gate,manual_case=selected,label='手动四事件 '+('Vinmin' if selected=='min' else 'Vinmax'))
    return dict(result,semi=dict(result['semi'],switch=dict(result['semi']['switch'],gate=updated)))


def _snapshot(parameters, result=None, *, include_loop=False):
    # Compatibility entry point; one constructor now serves every caller.
    from design_engine.calculation import build_snapshot
    return build_snapshot(parameters, result, include_loop=include_loop)


def _prepare_reference(base):
    """Size automatic magnetic hardware exactly once, always at Vinmin."""
    from loss_model import compute_design
    from analysis_workflows import pin_hardware
    reference = dict(copy.deepcopy(base), V_in=base['V_in_min'], input_voltage_case='min')
    result = compute_design(reference)
    if not result['mag'].get('ok') and base['V_in_min'] == base['V_in_max']:
        # Preserve the legacy partial-design view (electrical waveforms and
        # failed magnetic checks) when there is only one actual operating point.
        # There is no second point that could silently select different hardware.
        return reference, {}, result
    fixed = pin_hardware(reference, result)
    hardware = {key.removeprefix('_fixed_'): copy.deepcopy(value)
                for key, value in fixed.items() if key.startswith('_fixed_')}
    return fixed, hardware, result


def calculate_input_operating_point(p, *, include_loop=False, cancelled=None):
    """One selected endpoint, sharing Vinmin-sized hardware with the report.

    ``base_spec`` is the normalized user request (for UI cache identity).
    ``p`` contains the pinned internal hardware actually used by all downstream
    calculations.  Never discard those private fields when computing curves.
    """
    with _cancellation_scope(cancelled):
        base = normalize_input_voltage_spec(p)
        fixed, hardware, reference = _prepare_reference(base)
        selected = dict(copy.deepcopy(fixed), V_in=base['V_in'],
                        input_voltage_case=base['input_voltage_case'])
        from mos_manual import distinct_endpoints
        same = base['V_in'] == base['V_in_min'] and not (base['input_voltage_case']=='max' and distinct_endpoints(base))
        snap = _snapshot(selected, reference if same else None, include_loop=include_loop)
        snap.update(base_spec=base, fixed_spec=fixed, hardware=hardware,
                    reference_voltage=base['V_in_min'], fixed_hardware=bool(hardware),
                    hardware_note=('Vinmin 磁件选型失败；保留单一工况电气结果，不宣称已固定有效磁件。'
                                   if not hardware else ''))
        return snap


def calculate_input_endpoints(p, *, include_loop=True, include_cross_regulation=True, cancelled=None, progress=None):
    """Full Vinmin/Vinmax snapshots with one physical BOM and compensation.

    Numerical errors are recorded per case; cancellation always propagates.
    Equal endpoints share one calculation but retain both explicit case labels.
    A failed Vinmin reference cannot silently create a different design at max.
    """
    from calculation_scheduler import CalculationCancelled, check_calculation_cancelled
    with _cancellation_scope(cancelled):
        base = normalize_input_voltage_spec(p)
        try:
            fixed, hardware, reference = _prepare_reference(base)
            reference_error = None
        except CalculationCancelled:
            raise
        except Exception as exc:
            fixed, hardware, reference = None, {}, None
            reference_error = f'{type(exc).__name__}: {exc}'
        cases, solved = [], {}
        for index, (case_id, selected, voltage) in enumerate((
                ('Vinmin', 'min', base['V_in_min']), ('Vinmax', 'max', base['V_in_max'])), 1):
            check_calculation_cancelled()
            case_p = dict(copy.deepcopy(fixed if fixed is not None else base),
                          V_in=voltage, input_voltage_case=selected)
            case = dict(id=case_id, voltage=voltage, V_in=voltage, p=case_p,
                        result=None, models=None, checks=[], loop_error=None, error=None)
            if reference_error:
                case['error'] = (reference_error if selected == 'min' else
                                 'Vinmin 参考设计失败，无法固定同一套硬件：' + reference_error)
            else:
                try:
                    from mos_manual import distinct_endpoints
                    solve_key=(voltage,selected if distinct_endpoints(base) else 'shared')
                    if solve_key not in solved:
                        solved[solve_key] = _snapshot(case_p,
                            reference if selected == 'min' else None,
                            include_loop=include_loop)
                    snap = solved[solve_key]
                    case.update(result=_gate_context(snap['res'],case_p), models=snap['models'],
                                checks=snap['checks'], loop_error=snap['loop_error'])
                except CalculationCancelled:
                    raise
                except Exception as exc:
                    case['error'] = f'{type(exc).__name__}: {exc}'
            cases.append(case)
            if progress:
                progress(index, 2, case_id)
        bundle = dict(base_spec=base, fixed_spec=fixed, hardware=hardware, cases=cases,
                    fixed_hardware=bool(hardware), hardware_reference='Vinmin',
                    hardware_note=('Vinmin 磁件选型失败；没有可用于双工况验证的有效磁件。'
                                   if not hardware else ''),
                    reference_voltage=base['V_in_min'],
                    same_voltage=base['V_in_min'] == base['V_in_max'])
        if include_cross_regulation:
            from cross_regulation import attach_to_endpoints
            attach_to_endpoints(bundle, cancelled=cancelled)
        return bundle
