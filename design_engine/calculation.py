"""One runtime snapshot constructor for desktop, range analysis and services."""
import copy


def build_snapshot(parameters, result=None, *, include_loop=True):
    from calculation_scheduler import CalculationCancelled, check_calculation_cancelled
    from loss_model import compute_design
    from design_checks import check_catalog
    from input_voltage_range import _gate_context

    p = copy.deepcopy(parameters)
    check_calculation_cancelled()
    res = _gate_context(compute_design(p) if result is None else result, p)
    models, error = None, None
    res['loop'] = None
    if include_loop:
        try:
            from plants import build_loop_models
            from loop_tuning import analyze_loop
            models, _ = build_loop_models(p, res['op'])
            res['loop'] = analyze_loop(p, models, res['op'])
        except CalculationCancelled:
            raise
        except Exception as exc:
            error = f'{type(exc).__name__}: {exc}'
    check_calculation_cancelled()
    checks = check_catalog(p, res, res['loop'], loop_error=error)
    res['checks'] = checks
    return dict(p=p, op=res['op'], wf=res['wf'], res=res, result=res,
                checks=checks, models=models, loop_error=error)
