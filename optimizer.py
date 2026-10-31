"""Efficiency-target optimisation.

Two modes, both "curve based" as requested:

1. sweep_efficiency: vary one design parameter and plot efficiency vs it
   (e.g. fsw, L, ...), then read off the value that meets a target efficiency.
2. optimize_efficiency: multi-variable search (scipy differential evolution)
   that maximises efficiency at a given load point, subject to soft
   constraints (CCM at full load for PWM converters).
"""

import numpy as np

from power_stage import compute_operating_point
from loss_model import compute_design, efficiency_curve
from isolated_outputs import scale_load


# variables that span decades -> sweep on a log grid
_LOG_VARS = {'f_sw', 'L', 'C_out', 'Rds_on', 'Bmax', 'J', 'k_core'}


def sweep_values(var, vmin, vmax, n, log=None):
    if log is None:
        log = var in _LOG_VARS
    if log:
        return np.logspace(np.log10(max(vmin, 1e-30)),
                           np.log10(max(vmax, 1e-30)), n)
    return np.linspace(vmin, vmax, n)


def sweep_efficiency(p, var, vmin, vmax, n=41, load_frac=1.0):
    """Efficiency vs one parameter.  Returns (values, etas)."""
    _check_variables(p,[var])
    values = sweep_values(var, vmin, vmax, n)
    etas = []
    for v in values:
        pp = scale_load(p,load_frac)
        pp[var] = v
        try:
            res = compute_design(pp)
            etas.append(res['eta'])
        except Exception:
            etas.append(np.nan)
    return np.asarray(values), np.asarray(etas)


def find_target(values, etas, target):
    """First (smallest) value whose efficiency reaches the target.  Linear
    interpolation.  Returns value or None."""
    ok = np.isfinite(etas) & (etas >= target)
    if not ok.any():
        return None
    i = int(np.argmax(ok))
    if i == 0:
        return float(values[i])
    # interpolate between i-1 and i
    v0, v1 = values[i - 1], values[i]
    e0, e1 = etas[i - 1], etas[i]
    if v1 == v0 or not np.isfinite(e0):
        return float(v1)
    t = (target - e0) / (e1 - e0)
    return float(v0 + t * (v1 - v0))


def _objective(x, p, var_list, load_frac):
    pp = scale_load(p,load_frac)
    for name, val in zip(var_list, x):
        pp[name] = float(val)
    try:
        res = compute_design(pp)
        op = res['op']
        pen = 0.0
        if op['mode'] == 'DCM':
            pen += 0.25                      # prefer CCM at full load
        return -(res['eta']) + pen
    except Exception:
        return 1.0


def optimize_efficiency(p, var_list, bounds, load_frac=1.0, seed=0,
                        maxiter=200, popsize=15):
    """Maximise efficiency over var_list (scipy differential evolution).

    Returns dict(best=dict(var->value), eta, ok).
    """
    _check_variables(p,var_list)
    from scipy.optimize import differential_evolution
    lo = np.array([b[0] for b in bounds])
    hi = np.array([b[1] for b in bounds])
    res = differential_evolution(lambda x: _objective(x, p, var_list, load_frac),
                                 bounds=list(zip(lo, hi)), seed=seed,
                                 maxiter=maxiter, popsize=popsize, tol=1e-6,
                                 polish=True, workers=1)
    best = {name: float(v) for name, v in zip(var_list, res.x)}
    pp = scale_load(p,load_frac)
    for name, v in best.items():
        pp[name] = v
    try:
        final = compute_design(pp)
        eta = final['eta']
    except Exception:
        eta = float('nan')
    return dict(best=best, eta=eta, ok=res.success, fun=res.fun,
                nit=res.nit)


def _check_variables(p,variables):
    if p.get('feedback_mode')=='PSR-MP6005' and 'f_sw' in variables:
        raise ValueError('MP6005 PWM 频率固定 250kHz，不能优化 f_sw')
    restricted=('C_out','Rc','P_out','V_out')+(('L',) if p['topology']=='ACF-FORWARD' else ())
    if p.get('outputs') and any(k in variables for k in restricted):
        raise ValueError('多输出的支路参数须在输出配置中修改；当前扫描仅支持共享原边参数（反激 L 除外）')


def efficiency_curve(p, fracs=None):
    """Convenience wrapper around loss_model.efficiency_curve."""
    return efficiency_curve(p, fracs)
