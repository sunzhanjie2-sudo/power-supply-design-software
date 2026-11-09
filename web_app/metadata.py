"""Form hints reuse the desktop's metadata; no electrical formula duplication."""
import copy
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
from example_catalog import EXAMPLES

# Keep old files addressable for established regression and saved links, but
# publish only the same curated catalog as the desktop.
_LEGACY_EXAMPLES = {
    '40W_CCM_FLYBACK.json': '40W CCM 单路反激',
    '90W_QR_L6565_300V.json': 'L6565 QR 反激 300V / 60V / 92W',
    '90W_QR_L6565_300V_TUNED.json': 'L6565 QR 300V / 92W 仿真补偿覆盖示例',
    '6_OUTPUT_FLYBACK_SSR.json': '40W 六路反激 · SSR',
    '3_OUTPUT_COUPLED_FLYBACK.json': '三路耦合反激 · 实验模型',
    '3_OUTPUT_CROSS_REGULATION.json': '三路交叉调整率示例',
    '40W_ACF_FORWARD.json': '40W 有源钳位正激',
    '33W_3OUT_ACF_MP6005.json': 'MP6005 三路有源钳位正激 20–30V / 33W',
    'MP6005_PSR_FLYBACK.json': 'MP6005 原边反馈反激',
    'spec_buck.json': 'Buck 降压示例',
}


def read_example(name):
    if name not in EXAMPLES and name not in _LEGACY_EXAMPLES:
        raise ValueError('示例不存在')
    return json.loads((ROOT/'examples'/name).read_text(encoding='utf-8'))


def normalize_config(spec):
    from config_io import decode_config
    from power_stage import DEFAULT_PARAMS
    from input_voltage_range import normalize_input_voltage_spec
    p=dict(copy.deepcopy(DEFAULT_PARAMS),**decode_config(spec))
    from engineering_acceptance import normalize as normalize_acceptance
    p['engineering_acceptance'] = normalize_acceptance(p.get('engineering_acceptance'))
    from capacitor_banks import normalize
    p=normalize(p)
    p=normalize_input_voltage_spec(p)
    from device_curve_sources import inferred_settings
    if not p.get('device_curve_settings'):
        p['device_curve_settings'] = inferred_settings(p)
    # Preserve report-only/reference-network metadata without interpreting it.
    p.update({key:copy.deepcopy(value) for key,value in spec.items() if key.startswith('__')})
    return p


def preview(spec):
    from power_stage import DEFAULT_PARAMS
    from config_io import decode_config
    from isolated_outputs import output_specs, ISOLATED
    from device_curve_sources import targets, source_for, curve_for
    p = dict(copy.deepcopy(DEFAULT_PARAMS), **decode_config(spec))
    rails = output_specs(p)
    from component_management import component_registry, normalize_management, RULES, CAP_TYPES, SOURCE_NOTE
    p['component_management'] = normalize_management(p.get('component_management'))
    from voltage_nodes import NOTE
    return dict(outputs=rails, isolated=p['topology'] in ISOLATED,voltage_node_note=NOTE,
                component_rows=component_registry(p), component_rules=RULES, capacitor_types=CAP_TYPES,
                component_note=SOURCE_NOTE,
                targets=[dict(row, source=source_for(p, row['target']),
                    loaded=bool(curve_for(p, row['target'])),
                    filename=(curve_for(p, row['target']).get('import_file') or
                              curve_for(p, row['target']).get('source') or {}).get('filename', ''))
                         for row in targets(p)])


def bootstrap():
    from spice_export import SETTINGS,CHOICES,setting_group,ordered_setting_keys,normalize_settings,mp6005_preset
    from controller_logic import definition as controller_definition
    from power_stage import TOPOLOGIES
    from parameter_layout import SECTION_TITLES, GROUPS
    from design_engine.catalog import parameter_catalog
    from winding_coupling import default_coupling_config
    from magnetics import CORE_DB, CORE_SHAPES, STEINMETZ_MATERIALS
    from design_engine.contracts import json_value
    spec = normalize_config(read_example('40W_CCM_FLYBACK.json'))
    spec.update(V_in_min=spec['V_in'], V_in_max=spec['V_in'], input_voltage_case='min')
    parameters = parameter_catalog()
    hints = {
        'J': ('设计电流密度', 'J', 'A/mm²', 1e-6),
        'K': ('等效耦合系数（旧 K）', 'Lleak=(1-K)Lm', '', 1.),
        'Kc': ('钳位电压比', 'Vclamp/Vreflect', '', 1.),
        'dC': ('钳位电容纹波比例', 'ΔVc/Vc', '%', 100.),
        'P_out_min': ('最小输出功率', 'Po,min', 'W', 1.),
        'cin2_enable': ('启用输入第二电容', '', '', 1.),
        'cout2_enable': ('启用输出第二电容', '', '', 1.),
        'd_in_enable': ('启用输入防反二极管', 'D_IN', '', 1.),
        'd_out_enable': ('启用输出防反二极管', 'D_OUT', '', 1.),
        'target_eta': ('评审目标效率', 'η,target', '%', 100.),
        'fc_target': ('目标穿越频率', 'fc', 'Hz', 1.),
        'pm_target': ('目标相位裕度', 'PM', '°', 1.),
        'psr_Na': ('辅助绕组匝数', 'Na', '匝', 1.),
        'psr_Vcc': ('控制器供电电压', 'Vcc', 'V', 1.),
        'psr_aux_target': ('辅助绕组目标电压', 'Vaux', 'V', 1.),
        'psr_RfbH': ('辅助反馈上分压', 'RfbH', 'Ω', 1.),
        'psr_RfbL': ('辅助反馈下分压', 'RfbL', 'Ω', 1.),
        'psr_Rreg': ('线路补偿电阻', 'Rreg', 'Ω', 1.),
        'psr_Rcomp': ('COMP 电阻', 'Rcomp', 'Ω', 1.),
        'psr_Ccomp': ('COMP 电容', 'Ccomp', 'F', 1.),
        'psr_Cpole': ('COMP 高频电容', 'Cpole', 'F', 1.),
    }
    for row in parameters:
        if row['name'] in hints:
            label, symbol, unit, factor = hints[row['name']]
            row.update(label=label, symbol=symbol, display_unit=unit,
                       unit='' if unit in ('%', '匝') else unit, display_factor=factor)
        if row['name'] in ('K','Kc','dC'):
            row.update(category='stage',group='RCD 钳位')
        if row['name']=='J':
            row.update(category='mag',group='绕组与导线')
        if row['name'].startswith('psr_'):
            row.update(category='psr',group='物理 COMP 网络' if row['name'] in ('psr_Rcomp','psr_Ccomp','psr_Cpole') else '辅助绕组、采样与分压')
            if row['name'] in ('psr_Na','psr_RfbL'):row['auto_zero']=True
        if row['name'] in ('cin2_enable','cout2_enable','d_in_enable','d_out_enable'):
            row.update(category='capacitors',group='可选器件')
    options = {'cin2_enable':'Cin2','cout2_enable':'C_out2','d_in_enable':'Vf_din','d_out_enable':'Vf_dout'}
    for row in parameters:
        if row['name'] in options:
            row['group'] = next(r['group'] for r in parameters if r['name']==options[row['name']])
    ordered = [key for entries in GROUPS.values() for _,keys in entries for key in keys]
    order = {key:index for index,key in enumerate(ordered)}
    for flag,key in options.items():
        order[flag] = order[key]-.1
    parameters.sort(key=lambda row:(order.get(row['name'],1000),row['name']))
    return json_value(dict(version='0.2.0-local', spec=spec, parameters=parameters,
        sections=dict(SECTION_TITLES,psr='MP6005 原边反馈参数'), topologies=TOPOLOGIES, examples=EXAMPLES,
        materials=STEINMETZ_MATERIALS,
        permeability_materials=__import__('transformer_gap').MATERIAL_PERMEABILITY,
        spice_presets=dict(generic=normalize_settings(),mp6005=mp6005_preset(),mp6005_acf=__import__('acf_spice').preset(),l6565=__import__('qr_spice_settings').l6565_preset(),tps40200=__import__('nonisolated').preset(1),ltc3864=__import__('nonisolated').preset(2),lm5022=__import__('nonisolated').preset(3)),
        spice_niso_logic=__import__('controller_logic').nonisolated_definition(),
        spice_niso_reference_keys=list(__import__('nonisolated').REFERENCE_KEYS),
        spice_acf_logic=__import__('controller_logic').acf_definition(),
        spice_qr_logic=__import__('controller_logic').qr_definition(),
        spice_logic=controller_definition(),
        parasitics=__import__('parasitics').schema(),
        spice_options=[dict(key=k,default=d,minimum=lo,maximum=hi,label=label,unit=unit,group=setting_group(k),topologies=[t for t in ('FLYBACK','QR-FLYBACK','ACF-FORWARD','BUCK','BOOST') if k in __import__('qr_spice_settings').applicable_keys(t)],choices={str(v):text for v,text in CHOICES[k].items()} if k in CHOICES else None)
                       for k in ordered_setting_keys() for d,lo,hi,label,unit in (SETTINGS[k],)],
        core_shapes={name:list(cores) for name,cores in CORE_SHAPES.items()},
        cores={name: {key:value for key,value in core.items() if key in ('Ae','Ve','Wa','MLT')}
               for name,core in CORE_DB.items()},
        coupling={str(count): default_coupling_config(count) for count in range(1,7)},
        output_template={key: copy.deepcopy(spec[key]) for key in __import__('isolated_outputs').RAIL_KEYS},
        preview=preview(spec)))
