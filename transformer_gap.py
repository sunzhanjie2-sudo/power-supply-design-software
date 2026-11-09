"""Transformer air-gap estimate from a linear magnetic circuit, in SI units.

TI UCC2863x SLUSBW3D, eq.45 and MPS AN069, eq.30 retain ferrite reluctance.
The calculated gap is an equivalent length referred to Ae, without fringing.
"""
import math

MU0 = 4e-7 * math.pi
FORMULA_SOURCE = 'https://www.ti.com/lit/ds/symlink/ucc28630.pdf#page=61'
_FERROXCUBE = 'https://www.ferroxcube.com/en-global/download/download/11'
MATERIAL_PERMEABILITY = {
    'N87': dict(mu_r=2200., tolerance=.25, conditions='25 °C，小信号初始磁导率 μi',
                source='https://www.tdk-electronics.tdk.com/download/528882/3226013b0ed82a6a2af3666f537cbf83/pdf-n87.pdf'),
    'DMR44': dict(mu_r=2400., tolerance=.25, conditions='25 °C，10 kHz，B < 0.25 mT，初始磁导率 μi',
                  source='https://www.dmegc.de/uploads/20230401/DMR44%20Material%20Characteristics.pdf'),
    'PC40': dict(mu_r=2300., tolerance=.25, conditions='25 °C，小信号初始磁导率 μi',
                 source='https://product.tdk.com/en/system/files?file=dam%2Fdoc%2Fproduct%2Fferrite%2Fferrite%2Fferrite-core%2Fcatalog%2Fferrite_material_characteristics_en.pdf'),
    '3C90': dict(mu_r=2300., tolerance=.20, conditions='25 °C，≤10 kHz，0.25 mT，初始磁导率 μi', source=_FERROXCUBE),
    '3F3': dict(mu_r=2000., tolerance=.20, conditions='25 °C，≤10 kHz，0.25 mT，初始磁导率 μi', source=_FERROXCUBE),
    'N27': dict(mu_r=2000., tolerance=.25, conditions='25 °C，小信号初始磁导率 μi',
                source='https://www.tdk-electronics.tdk.com/download/528850/3a7f957d754f899aec42cd946598c5c4/pdf-n27.pdf'),
}
LIMITATIONS = ('线性磁路估算，忽略气隙边缘磁通、接合残隙与偏磁/温度引起的磁导率变化。'
               'lg 为折算到 Ae 的总等效气隙；中柱单处开隙可作初值，实际加工按目标 AL 调整并测量。')


def validate_inputs(p):
    for key in ('mu_r', 'le_core'):
        value = p.get(key, 0.)
        if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value) or value < 0:
            raise ValueError(key+' 必须为有限非负数，0 表示自动；le_core 单位为 m')
    if 0 < p.get('mu_r', 0.) < 1:
        raise ValueError('mu_r 是相对磁导率，手动值必须 ≥1；真空磁导率 μ0 由程序提供')


def estimate(p, core, turns):
    validate_inputs(p)
    inductance = float(p['Lm_forward'] if p['topology'] == 'ACF-FORWARD' else p['L'])
    if not math.isfinite(inductance) or inductance <= 0:
        raise ValueError('变压器目标励磁电感必须为有限正数')
    ae = float(core['Ae'])
    le = float(core['Ve']) / ae
    preset = MATERIAL_PERMEABILITY.get(p.get('core_material'), {})
    manual = bool(p.get('mu_r', 0.))
    mu = float(p['mu_r']) if manual else preset.get('mu_r')
    result = dict(model='linear_magnetic_circuit_no_fringing', material=p.get('core_material'),
        target_inductance_H=inductance, primary_turns=int(turns), Ae_m2=ae, le_m=le,
        le_source='由有效体积 Ve / 有效截面积 Ae 推得',
        mu_r=mu, mu_r_source='用户指定相对磁导率' if manual else '材料手册初始磁导率 μi' if preset else '待提供磁导率',
        mu_r_conditions=None if manual else preset.get('conditions'),
        mu_r_tolerance=None if manual else preset.get('tolerance'),
        material_source=None if manual else preset.get('source'),
        AL_target_H=inductance / turns**2, AL_ungapped_H=None, L_ungapped_H=None, mu_effective=None,
        gap_m=None, gap_raw_m=None, status='unavailable', formula_source=FORMULA_SOURCE,
        note=LIMITATIONS, provenance='calculator_estimate_not_geometry_or_measurement')
    if mu is None:
        result['note']='当前材料没有磁导率预设，请输入 μr 后计算气隙。'+LIMITATIONS
        return result
    base = MU0 * ae * turns**2
    ungapped = base * mu / le
    raw = base / inductance - le / mu
    tolerance = 1e-12 * max(base / inductance, le / mu)
    feasible = raw >= -tolerance
    result.update(AL_ungapped_H=ungapped / turns**2, L_ungapped_H=ungapped,
                  mu_effective=inductance * le / base, gap_raw_m=raw,
                  gap_m=max(0., raw) if feasible else None,
                  status='estimated' if feasible else 'infeasible')
    if not feasible:
        result['note']=('目标 Lm 高于当前匝数、磁芯与 μr 对应的无气隙电感，增加气隙会继续降低电感。'
                        '请复核 μr / le、增加原边匝数或调整磁芯与 Lm。'+LIMITATIONS)
    return result


def summary(result):
    """A concise shared reading, also suitable for the narrow parameter panel."""
    gap = result.get('gap_m')
    reading = f'等效总气隙 lg ≈ {gap*1e3:.4g} mm' if gap is not None else '气隙待核对'
    mu = result.get('mu_r')
    return (f"{reading}；μr={mu:g}；le={result['le_m']*1e3:.4g} mm；"
            f"目标 AL={result['AL_target_H']*1e9:.4g} nH/匝²。" if mu is not None else reading+'。') + result['note']
