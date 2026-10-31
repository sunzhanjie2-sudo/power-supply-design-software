"""Shared, SI-valued parasitic contract. No GUI or simulator dependency.

Fast mode preserves the established average models. Transient mode adds a
local, single-port commutation estimate for flybacks; it is deliberately not
a new closed-loop or full multi-winding switching solver.
"""
import copy
import math

ISOLATED = ('FLYBACK', 'QR-FLYBACK', 'ACF-FORWARD')
FIELDS = {
    'coss': ('Q1 有效输出电容，0=沿用器件 Coss', 'pF', 1e12, 0.),
    'coss_aux': ('Q2 有效输出电容，0=沿用器件 Coss', 'pF', 1e12, 0.),
    'cw_primary': ('原边绕组端间等效电容', 'pF', 1e12, 0.),
    'lp_pcb': ('原边串联布线/引线电感', 'nH', 1e9, 0.),
    'rp_pcb': ('原边串联布线/引线电阻', 'mΩ', 1e3, 0.),
    'snub_r_primary': ('Q1 并联 RC：串联电阻', 'Ω', 1., 10.),
    'snub_c_primary': ('Q1 并联 RC：电容，0=不装', 'pF', 1e12, 0.),
    'cj_default': ('未单独配置的二极管 Cj', 'pF', 1e12, 20e-12),
    'r_cj': ('结电容串联阻尼（模型假设）', 'Ω', 1., .1),
}
RAIL_FIELDS = {
    'cj': ('整流二极管 Cj', 'pF', 1e12, 20e-12),
    'cj_free': ('续流二极管 Cj（正激）', 'pF', 1e12, 20e-12),
    'cw': ('该绕组端间等效电容', 'pF', 1e12, 0.),
    'l_pcb': ('该绕组串联布线/引线电感', 'nH', 1e9, 0.),
    'r_pcb': ('该绕组串联布线/引线电阻', 'mΩ', 1e3, 0.),
    'snub_r': ('整流管并联 RC：串联电阻', 'Ω', 1., 10.),
    'snub_c': ('整流管并联 RC：电容，0=不装', 'pF', 1e12, 0.),
}
NOTE = ('寄生参数均为工作电压附近的集中等效值。独立二极管默认 Cj=20 pF、结电容阻尼=0.1 Ω 为模型假设；MOS Coss 不重复叠加体结电容。'
        '0 的绕组/布线寄生表示尚未建模，不表示实物为零。未含电容非线性、反向恢复、分布电容矩阵及实际探头。'
        '反激局部振铃估算不替代多绕组完整瞬态，平均工作点和低频环路沿用原模型。')


def normalize(raw=None):
    if raw is None: raw = {}
    if not isinstance(raw, dict): raise ValueError('parasitic_config 必须为字典')
    allowed = set(FIELDS) | {'mode', 'rails'}
    unknown = set(raw)-allowed
    if unknown: raise ValueError('未知寄生参数：'+', '.join(sorted(unknown)))
    result = {'mode': raw.get('mode', 'fast')}
    if result['mode'] not in ('fast', 'transient'): raise ValueError('寄生计算模式必须为 fast 或 transient')
    def number(value, name):
        if isinstance(value, bool): raise ValueError(name+' 必须为有限非负数')
        try: value = float(value)
        except (ValueError, TypeError): raise ValueError(name+' 必须为有限非负数') from None
        if not math.isfinite(value) or value < 0: raise ValueError(name+' 必须为有限非负数')
        return value
    for key, (_, _, _, default) in FIELDS.items(): result[key] = number(raw.get(key, default), key)
    if result['r_cj'] <= 0: raise ValueError('结电容串联阻尼必须大于 0')
    rails = raw.get('rails', {})
    if not isinstance(rails, dict): raise ValueError('寄生 rails 必须按 OUT1…OUT6 保存')
    result['rails'] = {}
    for ref, row in rails.items():
        if ref not in {f'OUT{i}' for i in range(1, 7)} or not isinstance(row, dict): raise ValueError('无效的寄生输出位号')
        if set(row)-set(RAIL_FIELDS): raise ValueError(ref+' 存在未知寄生参数')
        entry = {k:number(v,ref+'.'+k) for k,v in row.items()}
        if entry.get('snub_c',0)>0 and entry.get('snub_r',10)<=0: raise ValueError(ref+' 吸收电阻必须大于 0')
        result['rails'][ref] = entry
    if result['snub_c_primary']>0 and result['snub_r_primary']<=0: raise ValueError('Q1 吸收电阻必须大于 0')
    return result


def resolved(p, count=1):
    raw = p.get('parasitic_config') or {}
    cfg = normalize(raw)
    # Explicit settings win. Legacy settings are migrated only at this boundary.
    old = p.get('spice_config') or {}
    if 'cj_default' not in raw: cfg['cj_default'] = float(old.get('diode_cj_pf',20))*1e-12
    cfg['coss_source'] = '寄生配置' if cfg['coss'] else '器件 Coss'
    if p['topology']=='QR-FLYBACK' and not cfg['coss'] and old.get('qr_cds_pf',0)>0:
        cfg['coss'] = float(old['qr_cds_pf'])*1e-12
        cfg['coss_source'] = '旧 QR 有效漏极电容'
    cfg['coss'] = cfg['coss'] or float(p['Coss'])
    cfg['coss_aux'] = cfg['coss_aux'] or float(p.get('Coss_aux',0))
    cfg['rails'] = [{k:cfg['rails'].get(f'OUT{i}',{}).get(k,cfg['cj_default'] if k in ('cj','cj_free') else v[3])
                     for k,v in RAIL_FIELDS.items()} for i in range(1,count+1)]
    if cfg['coss'] < 0 or not math.isfinite(cfg['coss']): raise ValueError('有效 Coss 必须为有限非负值')
    return cfg


def effective_parameters(p):
    """Capacitance used by QR timing, ACF circuit and loss estimates is identical."""
    if p['topology'] not in ISOLATED: return p
    cfg = resolved(p, len(p.get('outputs') or [None]))
    # No implicit legacy migration changes fast-mode calculations.
    if not p.get('parasitic_config'): return p
    return dict(p, Coss=cfg['coss'], Coss_aux=cfg['coss_aux'])


def augment_matrix(model, cfg):
    """Series uncoupled PCB L changes only Lii; never adds leakage twice."""
    import numpy as np
    m = dict(model)
    m['L'] = np.array(model['L'],copy=True)
    m['R'] = np.array(model['R'],copy=True)
    series_l = [cfg['lp_pcb']]+[r['l_pcb'] for r in cfg['rails']]
    series_r = [cfg['rp_pcb']]+[r['r_pcb'] for r in cfg['rails']]
    m['L'] += np.diag(series_l); m['R'] += series_r
    diag = np.sqrt(np.diag(m['L']))
    m['K'] = m['L']/np.outer(diag,diag)
    return m


def schema():
    return dict(fields={k:dict(label=v[0],unit=v[1],scale=v[2],default=v[3]) for k,v in FIELDS.items()},
                rail_fields={k:dict(label=v[0],unit=v[1],scale=v[2],default=v[3]) for k,v in RAIL_FIELDS.items()}, note=NOTE)


def summary(data):
    """HTTP/report metadata excludes private adaptive integration arrays."""
    if not data:return None
    result={k:copy.deepcopy(v) for k,v in data.items() if k!='edges'}
    result['edges']=[{k:copy.deepcopy(z[k]) for k in ('ref','peak','frequency','status','clamped','parameters') if k in z} for z in data.get('edges',[])]
    return result


def parameter_rows(p, count=1):
    c = resolved(p,count)
    rows = [('模式', '快速 / 原有模型' if c['mode']=='fast' else '寄生瞬态 / 反激局部估算')]
    for key, (label, unit, scale, _) in FIELDS.items():
        if key=='coss_aux' and p['topology']!='ACF-FORWARD': continue
        rows.append((label, f'{c[key]*scale:.6g} {unit}'+(' · '+c['coss_source'] if key=='coss' else '')))
    for i,row in enumerate(c['rails'],1):
        for key,(label,unit,scale,_) in RAIL_FIELDS.items():
            if key=='cj_free' and p['topology']!='ACF-FORWARD': continue
            rows.append((f'OUT{i} · '+label,f'{row[key]*scale:.6g} {unit}'))
    return rows
