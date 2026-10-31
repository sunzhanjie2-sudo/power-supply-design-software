"""Small unit-type boundary; keep linear and switching model ownership separate."""
from ldo import is_ldo

def load_unit(raw):
    from config_io import decode_config
    decoded=decode_config(raw)
    if is_ldo(decoded):
        from ldo import normalize
        return normalize(dict(decoded,**{k:v for k,v in raw.items() if k.startswith('__')}))
    from design_engine.specification import load_spec
    return load_spec(decoded)

def unit_rails(p):
    if is_ldo(p):return [dict(V_out=p['V_out'],P_out=p['P_out'],name='LDO 输出')]
    from isolated_outputs import output_specs
    return output_specs(p) or [dict(V_out=p['V_out'],P_out=p['P_out'],name='OUT1')]

def export_ldo(raw,destination):
    from ldo import calculate
    from ldo_report import export_report
    return export_report(calculate(raw),destination)
