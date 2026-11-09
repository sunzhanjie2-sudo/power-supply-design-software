"""Canonical legacy-compatible specification decoding (no GUI imports)."""

import copy
from power_stage import DEFAULT_PARAMS, TOPOLOGIES
from config_io import UNITS as _UNIT
import plants

# accepted spec keys (plain values or {'v': x, 'u': unit-prefix} objects)
_SPEC_KEYS = sorted(set(DEFAULT_PARAMS) | {'V_in_min', 'V_in_max', 'input_voltage_case'})
_TOPO_ALIAS = {k.upper(): k for k in TOPOLOGIES}
_CTRL_ALIAS = {'VM': 'Voltage Mode', 'PCM': 'Peak Current Mode',
               'VOLTAGE MODE': 'Voltage Mode',
               'PEAK CURRENT MODE': 'Peak Current Mode'}


def load_spec(spec):
    """Normalise a user spec dict into a full parameter dict (SI values).

    Accepts plain SI values or config-file style {'v': .., 'u': prefix}
    objects.  Unknown keys raise ValueError (typos must not silently pass).
    """
    p = copy.deepcopy(DEFAULT_PARAMS)
    from config_io import decode_config
    spec = decode_config(spec or {})
    errors = []
    from input_voltage_range import RANGE_KEYS, has_input_voltage_range, normalize_input_voltage_spec
    accepted = set(DEFAULT_PARAMS) | {'K', 'Kc', 'dC', 'pm_target', 'fc_target', 'winding_config'} | set(RANGE_KEYS)
    for k, v in (spec or {}).items():
        if k not in accepted:
            errors.append(f'unknown spec key: {k!r}')
            continue
        if isinstance(v, dict) and 'v' in v:
            if isinstance(DEFAULT_PARAMS.get(k), str):
                v = v['v']
        if isinstance(v, dict) and 'v' in v:
            mult = _UNIT.get(str(v.get('u', '')), None)
            if mult is None:
                errors.append(f'{k}: unknown unit prefix {v.get("u")!r}')
                continue
            p[k] = float(v['v']) * mult
        elif isinstance(v, bool):
            p[k] = v
        elif isinstance(v, (int, float)):
            p[k] = float(v)
        elif isinstance(v, str):
            if k == 'topology':
                key = _TOPO_ALIAS.get(v.strip().upper())
                if key is None:
                    errors.append(f'topology {v!r} not in {TOPOLOGIES}')
                else:
                    p[k] = key
            elif k == 'control_mode':
                p[k] = _CTRL_ALIAS.get(v.strip().upper(), v)
            else:
                p[k] = v
        else:
            p[k] = v
    if errors:
        raise ValueError('invalid spec: ' + '; '.join(errors))
    from engineering_acceptance import normalize as normalize_acceptance
    p['engineering_acceptance'] = normalize_acceptance(p.get('engineering_acceptance'))
    from component_management import normalize_management
    from parasitics import normalize as normalize_parasitics
    if p.get('parasitic_config'):
        p['parasitic_config'] = normalize_parasitics(p['parasitic_config'])
    p['component_management'] = normalize_management(p.get('component_management'))
    from spice_export import normalize_settings
    p['spice_config'] = normalize_settings(p.get('spice_config'))
    from device_curve_sources import effective_sources
    stored_diodes=p.get('diode_curves',{})
    p=dict(effective_sources(p),diode_curves=stored_diodes)
    from diode_curves import validate_bank,DEPRECATED_RD
    p['diode_curves']=validate_bank(p.get('diode_curves',{}))
    for key in DEPRECATED_RD:p[key]=0.  # accepted only for old JSON compatibility
    if p['mos_miller_mode'] not in ('auto','manual','curve','gfs'):
        raise ValueError('unknown MOS platform mode')
    if p.get('mos_miller_curve'):
        from mos_curves import validate_curve
        p['mos_miller_curve']=validate_curve(p['mos_miller_curve'])
    if p['mos_miller_mode']=='curve' and not p.get('mos_miller_curve'):
        raise ValueError('MOS 曲线模式缺少内嵌曲线数据')
    if p['mos_charge_mode'] not in ('manual','curve'):raise ValueError('未知栅电荷来源')
    if p.get('mos_charge_curve'):
        from mos_gate_charge import validate_charge
        p['mos_charge_curve']=validate_charge(p['mos_charge_curve'])
    if p['mos_charge_mode']=='curve' and not p.get('mos_charge_curve'):raise ValueError('缺少 Vgs–Qg 栅电荷曲线')
    if p.get('mos_manual_events'):
        from mos_manual import normalize_events
        p['mos_manual_events']=normalize_events(p['mos_manual_events'])
    # Normalize only explicitly ranged inputs.  Scalar legacy APIs keep the
    # original V_in semantics, including their historical default corner grid.
    if has_input_voltage_range(spec):
        p = normalize_input_voltage_spec(p)
    if 'winding_config' in p:
        from winding_layout import validate_winding_config
        p['winding_config'] = validate_winding_config(p['winding_config'])
    if p['topology'] not in TOPOLOGIES:
        raise ValueError(f'topology must be one of {TOPOLOGIES}')
    p['controller_type'] = plants.normalize_controller_type(p['controller_type'])
    # RCD clamp entries ride on top of DEFAULT_PARAMS like the GUI does
    for k in ('K', 'Kc', 'dC'):
        if k in (spec or {}):
            p[k] = float(spec[k]['v']) if isinstance(spec[k], dict) else float(spec[k])
    from capacitor_banks import normalize
    p=normalize(p)
    from isolated_outputs import output_specs
    if p.get('outputs'):
        p['outputs'] = [{k:v for k,v in r.items() if k!='id'} for r in output_specs(p)]
    else: output_specs(p)
    return p
