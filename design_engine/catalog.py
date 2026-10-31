"""Machine-readable parameter catalogue derived from existing defaults/UI metadata.

Does not create a second table of default values or electrical validation rules.
The schema describes transport types; numerical/model validity remains enforced
by the existing engine, including conditional and nested device constraints.
"""
import copy


def parameter_catalog(topology=None):
    from power_stage import DEFAULT_PARAMS, TOPOLOGIES
    from parameter_layout import META, GROUPS, applicable
    if topology is not None and topology not in TOPOLOGIES:
        raise ValueError(f'unknown topology: {topology!r}')
    defaults = copy.deepcopy(DEFAULT_PARAMS)
    defaults.update(V_in_min=defaults['V_in'], V_in_max=defaults['V_in'], input_voltage_case='min')
    defaults.setdefault('winding_config', {})
    groups = {key: (section, label) for section, entries in GROUPS.items()
              for label, keys in entries for key in keys}
    rows = []
    for key, default in sorted(defaults.items()):
        meta = META.get(key)
        # GUI grouping and units are reused, not re-entered in another registry.
        kind = ('boolean' if isinstance(default, bool) else 'number' if isinstance(default, (int, float))
                else 'string' if isinstance(default, str) else 'array' if isinstance(default, list) else 'object')
        if key in ('input_capacitors','output_capacitors'):kind='array'
        display_unit = meta.unit if meta else ''
        row = dict(name=key, default=default, type=kind,
                   label=meta.label if meta else key, symbol=meta.symbol if meta else key,
                   unit='' if display_unit in ('%', '倍', '股', '匝') else display_unit,
                   display_unit=display_unit, display_factor=meta.display_factor if meta else 1.,
                   category=groups.get(key, ('options', '选项与结构化配置'))[0],
                   group=groups.get(key, ('options', '选项与结构化配置'))[1],
                   topologies=list(meta.topologies) if meta else [],
                   enabled_by=meta.enabled_by if meta else '',
                   auto_zero=bool(meta and meta.auto),
                   deprecated=key in ('Rd_diode', 'Rd_din', 'Rd_dout', 'tr', 'tf', 'Vf', 'gfs'))
        if topology is not None:
            row['applicable'] = applicable(key, topology, 'Peak Current Mode') if meta else True
        rows.append(row)
    return rows


def specification_schema():
    from power_stage import TOPOLOGIES
    from isolated_outputs import RAIL_KEYS
    properties = {}
    for row in parameter_catalog():
        raw = {'type': row['type']}
        if row['name'] in ('input_capacitors','output_capacitors'):
            raw={'type':['array','null'],'minItems':1,'items':{'type':'object','required':['C'],
                'additionalProperties':False,'properties':{k:{'type':'number','minimum':0} for k in ('C','ESR','ESL')}}}
        if row['name'] == 'topology':
            # load_spec also accepts case-insensitive legacy aliases.
            raw['examples'] = list(TOPOLOGIES)
        if row['name'] == 'outputs':
            raw.update(maxItems=6, items={'type': 'object'})
        if row['type'] in ('number', 'string', 'boolean'):
            value_schema = {'anyOf': [raw, {'type': 'object', 'required': ['v'],
                'properties': {'v': raw, 'u': {'type': 'string'}}, 'additionalProperties': False}]}
        else:
            value_schema = raw
        value_schema.update(title=row['label'], default=row['default'])
        properties[row['name']] = value_schema
    properties['outputs']['items'] = {
        'type': 'object',
        'properties': dict({key: copy.deepcopy(properties[key]) for key in RAIL_KEYS}, name={'type': 'string'},output_capacitors=copy.deepcopy(properties['output_capacitors'])),
        'additionalProperties': False}
    # Old saved files use these aliases; the shared decoder resolves them.
    for alias, key in (('rcd_K', 'K'), ('rcd_Kc', 'Kc'), ('rcd_dC', 'dC')):
        if key in properties:
            properties[alias] = copy.deepcopy(properties[key])
    return {'$schema': 'https://json-schema.org/draft/2020-12/schema',
            '$id': 'urn:power-design:specification:v1', 'type': 'object',
            'title': 'Power design input (SI or legacy v/u values)',
            'properties': properties, 'patternProperties': {'^__': {}},
            'additionalProperties': False,
            '$comment': 'Transport schema only. Call validate_spec for engineering/model checks.'}
