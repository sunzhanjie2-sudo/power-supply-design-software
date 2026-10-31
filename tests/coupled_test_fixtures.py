"""Numerical coupling fixtures without importing a GUI integration test."""
import copy
from power_stage import DEFAULT_PARAMS
from winding_coupling import default_coupling_config


def configuration(count=3, enabled=True):
    p = copy.deepcopy(DEFAULT_PARAMS)
    if count == 6:
        voltages, powers = (30, 12, 5, 3.3, 24, 15), (20, 8, 4, 2, 4, 2)
    else:
        voltages, powers = (30, 12, 5), (30, .5, 1)
    p.update(topology='FLYBACK', feedback_mode='SSR', feedback_output=1, K=.95, Kc=1.5, dC=.1,
             outputs=[dict(V_out=v, P_out=w, Ns=0) for v, w in zip(voltages[:count], powers[:count])],
             coupling_config=default_coupling_config(count))
    p['coupling_config']['enabled'] = enabled
    return p
