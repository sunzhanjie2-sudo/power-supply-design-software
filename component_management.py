"""Key-component identity, ratings and traceable model-only derating checks.

This is a projection of completed calculations, never another converter solver.
Ratings are optional, SI-valued and distinct from electrical model parameters.
The supplied workbook is a partial transcription, not a certification standard.
"""
import copy
import math

SOURCE = '器件降额规范速查表.xlsx'
SOURCE_NOTE = ('用户提供的整理版速查表；I/II 区定义须按原规范确认。'
               '表2注4～10缺失；仅作初筛，不覆盖温度、寿命、浪涌、SOA或安规。')
STATUS = {'pass': '模型内满足', 'review': '超出限值', 'undefined': '待补充/复核', 'na': '不适用'}
CAP_TYPES = {'unknown': '未选类型', 'electrolytic': '非固体铝电解', 'mlcc': 'MLCC', 'film': '薄膜', 'other': '其他/自定义'}
# (label, I, II, workbook cell range). Merged D:E cells apply to both zones.
RULES = {
    'mos_voltage': ('MOS 稳态 Vds', .85, .90, '表1 半导体分立器件!D5:E5'),
    'mos_spike': ('MOS 窄尖峰 Vds', .95, 1., '表1 半导体分立器件!D6:E6；B58（宽度条件）'),
    'diode_voltage': ('功率二极管反压', .85, .90, '表1 半导体分立器件!D31:E31'),
    'electrolytic_voltage': ('铝电解正向电压', .90, .95, '表2 阻容类器件!D15:E15'),
    'electrolytic_ripple': ('铝电解纹波 RMS', .95, 1., '表2 阻容类器件!D18:E18'),
    'mlcc_voltage': ('MLCC 工作电压', .70, .75, '表2 阻容类器件!D22:E22'),
    'film_voltage': ('薄膜工作电压', .90, .95, '表2 阻容类器件!D25:E25'),
    'film_ripple': ('薄膜纹波 RMS', .90, .90, '表2 阻容类器件!D26:E26（合并单元格）'),
    'resistor_power': ('电阻平均功耗', .20, .20, '表2 阻容类器件!D8:E8（合并单元格）'),
    'mlcc_ripple': ('MLCC 纹波 RMS（规范未列）', None, None, '需自定义限值及依据'),
    'other_voltage': ('其他电容电压', None, None, '需自定义限值及依据'),
    'other_ripple': ('其他电容纹波 RMS', None, None, '需自定义限值及依据'),
}
TEXT_FIELDS = ('manufacturer', 'model', 'package', 'conditions', 'note')
RATING_FIELDS = ('voltage_V', 'ripple_A', 'power_W')


def normalize_management(value=None):
    if value is None:
        value = {}
    if not isinstance(value, dict):
        raise ValueError('关键器件管理必须为对象')
    if set(value)-{'version','zone','items','overrides','override_reason'}:
        raise ValueError('关键器件管理包含未知配置字段')
    if value.get('version', 1) != 1:
        raise ValueError('不支持的关键器件管理版本')
    zone = value.get('zone', 'I')
    if zone not in ('I', 'II'):
        raise ValueError('降额分区必须为 I 或 II')
    items = value.get('items', {})
    overrides = value.get('overrides', {})
    if not isinstance(items, dict) or not isinstance(overrides, dict):
        raise ValueError('器件条目/自定义降额规则必须为对象')
    result = dict(version=1, zone=zone, items={}, overrides={}, override_reason=str(value.get('override_reason', ''))[:1000])
    for key, v in overrides.items():
        if key not in RULES or isinstance(v, bool) or not isinstance(v, (float, int)) or not math.isfinite(v) or not 0 < v <= 1:
            raise ValueError('自定义降额因数无效：'+str(key)+'（应为 0～1 比例）')
        result['overrides'][key] = float(v)
    if overrides and not result['override_reason'].strip():
        raise ValueError('自定义降额规则请填写依据/原因')
    for ref, item in items.items():
        if not isinstance(ref, str) or not ref.strip() or len(ref) > 80 or not isinstance(item, dict):
            raise ValueError('关键器件位号/资料格式无效')
        if set(item)-set(TEXT_FIELDS)-set(RATING_FIELDS)-{'capacitor_type'}:
            raise ValueError(ref+' 包含未知器件资料字段')
        entry = {}
        for field in TEXT_FIELDS:
            text = item.get(field, '')
            if not isinstance(text, str):
                raise ValueError(ref+' '+field+' 应为文字')
            entry[field] = text[:1000]
        entry['capacitor_type'] = item.get('capacitor_type', 'unknown')
        if entry['capacitor_type'] not in CAP_TYPES:
            raise ValueError(ref+' 电容类型无效')
        for field in RATING_FIELDS:
            number = item.get(field)
            if number is None or number == '':
                entry[field] = None
            elif isinstance(number, bool) or not isinstance(number, (int, float)) or not math.isfinite(number) or number <= 0:
                raise ValueError(ref+' '+field+' 必须为正数；未知请留空')
            else:
                entry[field] = float(number)
        result['items'][ref] = entry
    return result


def component_registry(p, res=None):
    """Active physical/reference designators only; no solve, no virtual loads.

    Retired topology/output drafts are kept in saved items but not displayed or
    checked. Multi-output capacitors/rectifiers have independent identities.
    """
    rows = []
    def add(ref, kind, role, value=''):
        rows.append(dict(ref=ref, kind=kind, role=role, values=value))
    add('J1', 'connector', '输入端口')
    add('Q1', 'mos', '主开关 MOS')
    add('R_S1', 'resistor', '主开关采样电阻', f"Rs={p.get('Rs', 0):g} Ω")
    topo = p.get('topology')
    isolated = topo in ('FLYBACK', 'QR-FLYBACK', 'ACF-FORWARD')
    if isolated:
        add('T1', 'magnetic', '共享变压器')
    if not isolated or (topo == 'ACF-FORWARD' and not p.get('outputs')):
        add('L1', 'magnetic', '储能/输出电感')
    if topo == 'ACF-FORWARD':
        add('Q2', 'mos', '有源钳位 MOS')
        add('C_CL1', 'capacitor', '有源钳位电容')
    from capacitor_banks import bank,output_ref
    for j,_ in enumerate(bank(p,'input'),1):add('C_IN'+str(j),'capacitor','输入电容 '+str(j))
    if p.get('d_in_enable'):
        add('D_IN', 'diode', '输入防反二极管')
    if topo in ('FLYBACK', 'QR-FLYBACK') and p.get('Kc', 0) > 1:
        add('D_SN1', 'diode', 'RCD 钳位二极管')
        add('R_SN1', 'resistor', 'RCD 钳位电阻')
        add('C_SN1', 'capacitor', 'RCD 钳位电容')
    multi_refs = bool(isolated and (p.get('outputs') or p.get('feedback_mode') == 'PSR-MP6005'))
    if multi_refs:
        from isolated_outputs import output_specs
        rails = output_specs(p) or [dict(p, id=1)]
    else:
        rails = [dict(p, id=1)]
    for rail in rails:
        i = rail['id']
        label = f'OUT{i} · ' if multi_refs else ''
        add(f'J_O{i}' if multi_refs else 'J2', 'connector', label+'输出端口')
        add(f'D_O{i}' if multi_refs else 'D1', 'diode', label+'整流/续流二极管')
        for j,_ in enumerate(bank(rail),1):add(output_ref(i,j,multi_refs),'capacitor',label+'输出电容 '+str(j))
        if rail.get('d_out_enable'):
            add(f'D_B{i}' if multi_refs else 'D_OUT', 'diode', label+'输出防反二极管')
        if topo == 'ACF-FORWARD':
            add(f'D_F{i}' if multi_refs else 'D2', 'diode', label+'续流二极管')
            if multi_refs:
                add(f'L_O{i}', 'magnetic', label+'输出电感')
    if isolated and p.get('feedback_mode') == 'PSR-MP6005':
        add('U_PSR', 'controller', 'MP6005 PSR 控制器')
        add('N_A', 'magnetic', '辅助采样绕组（T1 内部，不独立计件）')
        for ref in ('R_FBH', 'R_FBL', 'R_REG', 'R_COMP'):
            add(ref, 'resistor', 'MP6005 '+ref)
        for ref in ('C_COMP', 'C_POLE'):
            add(ref, 'capacitor', 'MP6005 '+ref)
    elif isolated and p.get('outputs'):
        add('U_FB', 'block', '主反馈通路（模块参考，非展开 BOM）')
    if res:
        from topology_diagram import topology_components
        mapped = {x['ref']: x for x in topology_components(p, res['op'])}
        for row in rows:
            row['values'] = mapped.get(row['ref'], {}).get('values', row['values'])
    return rows


def rule_for(config, key):
    spec = RULES[key]
    custom = key in config['overrides']
    ratio = config['overrides'].get(key, spec[1 if config['zone'] == 'I' else 2])
    return dict(key=key, label=spec[0], factor=ratio,
                source=('自定义：'+config['override_reason']) if custom else SOURCE+' / '+spec[3], custom=custom)


def _finite(value):
    return float(value) if isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value) else None


def _input_cap_voltage(p, res):
    """DC + spectral input-bank ripple; no start-up/surge or wiring spikes."""
    import numpy as np
    wf = res['wf']
    x = np.asarray(wf['i_cin'], float)
    f = np.fft.rfftfreq(len(x), float(wf['t'][1]-wf['t'][0]))[1:]
    w = 2*np.pi*f
    caps = res['capacitors']['input']['caps']
    admittance = sum(1/(c['ESR']+1j*(w*c['ESL']-1/(w*c['C']))) for c in caps)
    spectrum = np.zeros(len(f)+1, complex)
    spectrum[1:] = np.fft.rfft(x-x.mean())[1:]/admittance
    return abs(float(res['op'].get('V_in_bus',res['op']['V_in'])))+float(np.max(np.abs(np.fft.irfft(spectrum, n=len(x)))))


def stress_map(p, res):
    """(designator,metric) -> model value/note, no fabricated missing stress."""
    import numpy as np
    from semiconductor import device_stress
    op = res['op']
    s = device_stress(op)
    data = {}
    def put(ref, key, val, note=''):
        data[(ref, key)] = (_finite(val), note)
    c = op.get('clamp') or {}
    for ref, key in [('Q1', 'switch'), ('Q2', 'auxiliary')]:
        if key not in s:
            continue
        put(ref, 'voltage', s[key].get('V_block', s[key]['V_max']), '模型稳态阻断平台，不含未建模寄生振铃。')
        if ref == 'Q1' and c:
            width = c.get('t_pulse')
            narrow = width is not None and width < min(1e-6, op['Ts']/50)
            put(ref, 'spike' if narrow else 'peak_regular', c.get('V_peak'),
                ('模型尖峰宽度满足 <min(1µs,Ts/50)；' if narrow else '未证明窄尖峰宽度条件，按稳态因数；')+'三温耐压和实测振铃仍须复核。')
        else:
            put(ref, 'spike', None, '无可用于窄尖峰放宽因数的已验证包络/宽度。')
    put('R_S1', 'power', res.get('P_sense'), '平均耗散 I_rms²·Rs；未覆盖脉冲曲线/热态降额。')
    if p.get('topology') in ('FLYBACK', 'QR-FLYBACK') and p.get('Kc', 0) > 1:
        put('R_SN1', 'power', res.get('P_rcd'), '同一钳位模型的平均电阻耗散；脉冲功率仍须按厂家曲线复核。')
        put('C_SN1', 'voltage', c.get('V_clamp', 0)*(1+p.get('dC', .1)/2), '钳位电容直流+半峰峰纹波近似，不含振铃。')
        put('D_SN1', 'voltage', None, '钳位二极管反压未单独求解，不套用主整流二极管应力。')
    if p.get('topology') == 'ACF-FORWARD':
        put('C_CL1', 'voltage', op.get('V_clamp'), '仅钳位电容稳态直流电压，未求解电压纹波峰值。')
        put('C_CL1', 'ripple', op.get('I_clamp_rms'), '钳位电流 RMS，未含未建模振铃。')
    vi = _input_cap_voltage(p, res)
    for i, cap in enumerate(res.get('capacitors', {}).get('input', {}).get('caps', []), 1):
        put('C_IN'+str(i), 'voltage', vi, '输入直流+稳态频谱纹波包络，不含启动、浪涌/线缆尖峰。')
        put('C_IN'+str(i), 'ripple', cap['total'], '本颗电容复阻抗分流后的 RMS；额定能力须按频率/温度修正。')
    multi = bool(p.get('outputs') or p.get('feedback_mode') == 'PSR-MP6005')
    rails = res.get('outputs') or [dict(id=1, op=op, capacitors=res['capacitors'])]
    for rail in rails:
        i, rop = rail['id'], rail['op']
        rs = device_stress(rop)
        rect = f'D_O{i}' if multi else 'D1'
        put(rect, 'voltage', rs['diode']['V_max'], '未考虑寄生尖峰；具体反压须实测，选型留有余量。')
        if 'freewheel' in rs:
            put(f'D_F{i}' if multi else 'D2', 'voltage', rs['freewheel']['V_max'], '未考虑寄生尖峰，须实测。')
        # Blocking reverse voltage depends on external back-feed conditions.
        put(f'D_B{i}' if multi else 'D_OUT', 'voltage', None, '防反二极管需外部反接/回灌最大电压，不能用正向输出电压代替。')
        wf = res['wf']['outputs'][i-1] if res.get('outputs') else res['wf']
        peak = float(np.max(np.abs(np.asarray(wf.get('vcap',wf['vout']))+np.asarray(wf.get('v_esl', 0.)))))
        for j, cap in enumerate(rail['capacitors']['output']['caps']):
            from capacitor_banks import output_ref
            ref = output_ref(i,j+1,multi)
            put(ref, 'voltage', peak, '防反管前电容端直流+已建模纹波/ESL；不含启动过冲和跨负载最坏值。')
            put(ref, 'ripple', cap['total'], '本颗电容分流 RMS；额定能力须按实际频率/温度修正。')
    put('D_IN', 'voltage', None, '输入防反器件的外部反接/回灌电压未定义，需另行核定。')
    return data


def evaluate_components(p, res=None):
    config = normalize_management(p.get('component_management'))
    data = stress_map(p, res) if res else {}
    rows, checks = [], []
    for component in component_registry(p, res):
        ref, kind = component['ref'], component['kind']
        item = config['items'].get(ref, {})
        row = dict(component, **{key:copy.deepcopy(item.get(key)) for key in (*TEXT_FIELDS, *RATING_FIELDS, 'capacitor_type')})
        row['quantity'] = 0 if kind == 'block' or ref == 'N_A' else 1
        row_checks = []
        def check(metric, rule_key, rating_key, unit, actual_key=None, note=''):
            rule = rule_for(config, rule_key)
            actual, extra = data.get((ref, actual_key or metric), (None, '该项应力未建模/尚未计算。'))
            rating = item.get(rating_key)
            limit = rating*rule['factor'] if rating is not None and rule['factor'] is not None else None
            state = 'undefined' if actual is None or limit is None else 'pass' if actual <= limit+1e-12*max(1.,limit) else 'review'
            missing = []
            if rating is None: missing.append('缺少额定值')
            if rule['factor'] is None: missing.append('无适用规则，请选电容类型或设定有依据的自定义规则')
            entry = dict(id='bom_'+ref+'_'+metric, ref=ref, name=ref+' '+rule['label'], metric=metric,
                value=actual, rating=rating, factor=rule['factor'], limit=limit, unit=unit,
                utilization=actual/rating if actual is not None and rating else None,
                margin=limit-actual if actual is not None and limit is not None else None,
                state=state, pass_=state=='pass', comparison='<=', source=rule['source'],
                note='；'.join(x for x in [*missing, extra, note] if x))
            row_checks.append(entry)
        if kind == 'mos':
            check('voltage', 'mos_voltage', 'voltage_V', 'V')
            regular = (ref, 'peak_regular') in data
            check('peak', 'mos_voltage' if regular else 'mos_spike', 'voltage_V', 'V', 'peak_regular' if regular else 'spike')
        elif kind == 'diode':
            check('voltage', 'diode_voltage', 'voltage_V', 'V')
            # Explicit open item: a steady-state pass is not a spike sign-off.
            row_checks.append(dict(id='bom_'+ref+'_spike',ref=ref,name=ref+' 尖峰反压',metric='spike',
                value=None,rating=item.get('voltage_V'),factor=None,limit=None,unit='V',utilization=None,margin=None,
                state='undefined',pass_=False,comparison='<=',source=SOURCE+' / 表1!B58',
                note='寄生尖峰/宽度未建模，需样机实测，不可据稳态通过项判器件全部通过。'))
        elif kind == 'capacitor':
            ctype = item.get('capacitor_type', 'unknown')
            ctype = ctype if ctype in ('electrolytic','mlcc','film') else 'other'
            check('voltage', ctype+'_voltage', 'voltage_V', 'V')
            check('ripple', ctype+'_ripple', 'ripple_A', 'A')
        elif kind == 'resistor':
            check('power', 'resistor_power', 'power_W', 'W')
        missing = [label for key,label in [('manufacturer','厂家'),('model','型号'),('package','封装')] if not item.get(key)]
        row['identity_missing'] = missing
        row['checks'] = row_checks
        row['state'] = ('review' if any(c['state']=='review' for c in row_checks) else
                        'undefined' if missing or any(c['state']=='undefined' for c in row_checks) else
                        'pass' if row_checks else 'na')
        row['status'] = STATUS[row['state']]
        rows.append(row)
        checks.extend(row_checks)
    active = {r['ref'] for r in rows}
    return dict(version=1, zone=config['zone'], source=SOURCE, note=SOURCE_NOTE, rows=rows, checks=checks,
                counts={s:sum(c['state']==s for c in checks) for s in STATUS},
                inactive_refs=sorted(set(config['items'])-active),
                scope='当前输入/负载模型内初筛；非完整物料清单，非全角点/温度或合规认证')


def rating_text(row):
    parts = []
    for key, label, unit in [('voltage_V', 'Vds' if row['kind']=='mos' else 'Vrrm' if row['kind']=='diode' else '耐压', 'V'),
                             ('ripple_A','纹波能力','A'),('power_W','额定功率','W')]:
        if row.get(key) is not None:
            parts.append(f'{label}={row[key]:g}{unit}')
    return '；'.join(parts) or '额定值待补充'


def compact_projection(data, *, with_row_checks=False):
    """Wire format has one owner per detailed check, not three copies per row.

    Summaries already carry canonical checks; the browser detail projection
    owns rich per-row evidence. Avoid copying the flat/row check lists twice.
    """
    result = {key:value for key,value in data.items() if key != 'checks'}
    if not with_row_checks:
        result['rows'] = [{k:v for k,v in row.items() if k != 'checks'} for row in data['rows']]
    return result


def check_text(check):
    def v(x): return '—' if x is None else f'{x:.4g}{check["unit"]}'
    ratio = '—' if check['utilization'] is None else f'{check["utilization"]:.1%}'
    factor = '未定义' if check['factor'] is None else f'{check["factor"]:.0%}'
    return f'{check["name"]}：{v(check["value"])} / 额定 {v(check["rating"])}，使用率 {ratio}，限值 {factor}×额定={v(check["limit"])}，{STATUS[check["state"]]}'
