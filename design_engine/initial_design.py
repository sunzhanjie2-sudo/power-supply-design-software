"""Size one editable design, then check that same hardware at the requested corners."""
import copy
import json
import math

from .preferred_values import standard as _standard, E12, E24
from .sizing_basis import REVISION, SCOPE, SOURCES, TOPOLOGY_MODES, fields_for


def form_options(current=None):
    from config_io import decode_config
    from capacitor_banks import bank
    p = decode_config(current or {})
    has_light_load='P_out_min' in p
    if p.get('topology') in TOPOLOGY_MODES:
        from .specification import load_spec
        p=load_spec(p)
    forms = {}
    for topo,modes in TOPOLOGY_MODES.items():
        fields = fields_for(topo)
        values = {key:default for key,_,_,default in fields}
        locks,mode = {},next(iter(modes))
        if p.get('topology')==topo and p.get('V_out',0)>0:
            values.update(vin_min=p.get('V_in_min',p.get('V_in')),vin_max=p.get('V_in_max',p.get('V_in')),
                          vout=p['V_out'],iout=p['P_out']/p['V_out'],fs=p['f_sw']/1000.,
                          ripple=p['ripple_target']*100,imin=p.get('P_out_min',0)/p['V_out'])
            if topo in ('BOOST','FLYBACK'):
                values['eta_guess']=p['eta_guess']*100.
            if p.get('control_mode') in modes:
                mode=p['control_mode']
            locks.update(L=p['L'],input_capacitors=bank(p,'input'),output_capacitors=bank(p))
            if p.get('inductor_design_enabled') is False and p.get('inductor_dcr',0)>0:
                locks['inductor_dcr']=p['inductor_dcr']
        forms[topo]=dict(fields=fields,values=values,modes=modes,mode=mode,locks=locks)
        if topo=='FLYBACK':
            from .flyback_sizing import form_context
            form_context(forms[topo],p if p.get('topology')==topo else {})
            if p.get('topology')==topo and not p.get('outputs') and not has_light_load:
                values['imin']=None
            saved=(current or {}).get('__auto_design_basis') or {}
            if p.get('topology')==topo and saved.get('topology')==topo:
                spec=saved.get('specification',{})
                forms[topo]['conduction']=spec.get('conduction','CCM')
                for key in ('duty_target','il_ratio'):
                    if key in spec: values[key]=spec[key]*100
                if spec.get('imin',0) is None: values['imin']=None
    active = p['topology'] if p.get('topology') in forms else 'BUCK'
    return dict(**forms[active],topology=active,variants=forms)


def _number(value, label):
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
        raise ValueError(label + '需要填写有限数值')
    return float(value)


def _prepare(request):
    if not isinstance(request, dict):
        raise ValueError('需要设计规格')
    topo = request.get('topology', 'BUCK')
    if not isinstance(topo,str) or topo not in TOPOLOGY_MODES:
        raise ValueError(f'{topo} 自动设计尚未接入。' + SCOPE.get(str(topo), '请核对拓扑。'))
    fields = fields_for(topo)
    known = {key for key, *_ in fields} | {'topology', 'control_mode', 'locked'}
    if topo=='FLYBACK':
        known.update(('conduction','windings'))
    if set(request)-known:
        raise ValueError('未知初版规格字段 ' + ', '.join(sorted(set(request)-known)))
    modes = TOPOLOGY_MODES[topo]
    mode = request.get('control_mode', next(iter(modes)))
    if not isinstance(mode,str) or mode not in modes:
        raise ValueError(topo+' 仅支持 '+ '、'.join(modes.values()))
    s = {}
    for key, label, scale, default in fields:
        value = request.get(key, None if key == 'imin' else default*scale)
        if key == 'imin' and value is None:
            s[key] = None
            continue
        s[key] = _number(value, label)
        if s[key] < 0 or (s[key] == 0 and key != 'imin'):
            raise ValueError(label + '超出范围')
    vm = mode == 'Voltage Mode'
    from nonisolated import PROFILES
    chip = dict(vmin=8.,vmax=80.) if topo=='FLYBACK' else PROFILES[3 if topo=='BOOST' else (1 if vm else 2)]
    if not chip['vmin'] <= s['vin_min'] <= s['vin_max'] <= chip['vmax']:
        raise ValueError(f"输入范围必须有序且在当前参考模型 {chip['vmin']:g}–{chip['vmax']:g} V 内")
    if topo=='FLYBACK':
        if not (s['vout']>3.5 and .5<=s['eta_guess']<=1 and .15<=s['duty_target']<=.48 and 1.05<=s['kc']<=4.):
            raise ValueError('MP6005 SSR 初版需要反馈端口大于 3.5 V（TL431 / 光耦偏置）、效率 50–100%、低线占空比 15–48%、Kc 1.05–4')
        if request.get('conduction','CCM') not in ('CCM','DCM'):
            raise ValueError('额定导通模式请选择 CCM 或 DCM')
        s['conduction']=request.get('conduction','CCM')
        low=high=250e3
    elif topo=='BOOST':
        if not s['vin_max'] < s['vout'] <= 300.:
            raise ValueError('非同步 Boost 初版要求输出高于最高输入，且在 300 V 初筛范围内。请核对直通供电路径。')
        if not .5 <= s['eta_guess'] <= 1.:
            raise ValueError('Boost 初筛预设效率需在 50%–100% 之间')
        low,high = 50e3,2.2e6
    else:
        if not chip['ref'] < s['vout'] < .9*s['vin_min']:
            raise ValueError('请核对 Buck 降压余量。本模型最大占空比为 90%，还需留出导通压降。')
        low,high = (35e3, 500e3) if vm else (50e3, 850e3)
    if not low <= s['fs'] <= high:
        raise ValueError(f'当前参考初版支持 {low/1000:g}–{high/1000:g} kHz')
    if s['imin'] is not None and s['imin'] > s['iout']:
        raise ValueError('最小负载电流不能超过额定电流')
    if not (.001 <= s['iout'] <= 100 and .0001 <= s['ripple'] <= .2
            and .05 <= s['il_ratio'] <= .8 and 30 <= s['pm'] <= 80):
        raise ValueError('初筛支持 1 mA–100 A、输出纹波 0.01–20%、电感纹波 5–80%、相位裕度 30–80°')
    pins = request.get('locked', {})
    allowed={'L','input_capacitors','output_capacitors'}
    allowed.add('rail_banks' if topo=='FLYBACK' else 'inductor_dcr')
    if not isinstance(pins, dict) or set(pins)-allowed:
        raise ValueError('锁定项限于电感、DCR 和输入／输出电容组')
    from capacitor_banks import validate
    locked = {}
    for key, value in pins.items():
        if key=='rail_banks':
            if not isinstance(value,list) or not 1<=len(value)<=6:
                raise ValueError('请逐路锁定现有输出电容组')
            locked[key]=[validate(v) for v in value]
        elif key.endswith('capacitors'):
            if not isinstance(value, list) or len(value) > 16:
                raise ValueError('初版选型每组支持 1–16 支路。可在原工程继续常规计算。')
            locked[key] = validate(value)
        else:
            locked[key] = _number(value, key)
            if locked[key] <= 0:
                raise ValueError('锁定的电感与 DCR 必须为正数')
    return topo, s, mode, locked


def _buck_power_stage(s, mode, locked):
    from app_resources import resource_path
    from .specification import load_spec
    vm = mode == 'Voltage Mode'
    name = '24W_BUCK_VM_TPS40200' if vm else '24W_BUCK_PCM_LTC3864'
    p = json.loads(resource_path('examples/'+name+'.json').read_text(encoding='utf-8'))
    lo, hi, vo, io, fs = (s[k] for k in ('vin_min','vin_max','vout','iout','fs'))
    di, dv = io*s['il_ratio'], vo*s['ripple']
    lmin = vo*(1-vo/hi)/(fs*di)
    inductance = locked.get('L', _standard(lmin, E12, True))
    dcr_budget = .005*vo*io/(io**2 + di**2/12)
    dcr = locked.get('inductor_dcr', _standard(dcr_budget, E24, False))
    # Charge balance alone can suggest a very small capacitor. Where a load
    # range is specified, screen for one cycle of additional charge demand.
    step = 0 if s['imin'] is None else io-s['imin']
    c_ripple = di/(8*fs*.5*dv)
    c_step = step/(fs*dv)
    cout = _standard(max(c_ripple,c_step), E12, True)
    # Split the 2% input ripple allowance between charge and the ESR step.
    d = min(max(.5, vo/hi), vo/lo)
    cin_min = io*d*(1-d)/(fs*.01*lo)
    peak = io + di/2
    low_cs, high_cs = (.055,.140) if vm else (.085,.103)
    # For PCM also reserve headroom for the explicit modelled slope ramp,
    # converted to equivalent current using the reference model's slope rule.
    from nonisolated import slope
    p.update(V_in_min=lo, V_in_max=hi, V_in=lo, input_voltage_case='min', V_out=vo,
             P_out=vo*io, P_out_min=vo*(s['imin'] or 0), f_sw=fs, L=inductance,
             inductor_design_enabled=False, inductor_dcr=dcr, ripple_target=s['ripple'],
             pm_target=s['pm'], A_sense=1., Rs=1., controller_type='type3' if vm else 'type2')
    cs_current = peak + slope(p)*p['spice_config']['duty_max']/fs
    p['Rs'] = _standard(low_cs/(1.25*cs_current), E24, False)
    for side, cap, esr_max in (('input', _standard(cin_min,E12,True), .01*lo/peak),
                              ('output', cout, .5*dv/di)):
        p[side+'_capacitors'] = locked.get(side+'_capacitors', [
            dict(C=cap, ESR=_standard(min(.035,esr_max),E24,False), ESL=1e-9)])
    rules = dict(template=name, L_min=lmin, delta_i_target=di, delta_v_limit=dv,
                 C_out_charge=c_ripple, C_out_step=c_step, C_in_charge=cin_min,
                 ESR_out_ceiling=.5*dv/di, DCR_budget=dcr_budget, cs_min=low_cs, cs_max=high_cs,
                 prospective_fault_current=high_cs/p['Rs'], locked=list(locked))
    return load_spec(p), rules


def _corners(p, s, rules):
    from calculation_scheduler import check_calculation_cancelled
    from loss_model import compute_design
    from nonisolated import slope
    from plants import build_loop_models
    from waveforms import cap_bank_ripple
    rows, plants = [], []
    volts = list(dict.fromkeys((s['vin_min'],s['vin_max'])))
    witness = rules.get('ripple_witness_vin')
    if witness is not None and not any(math.isclose(witness,v,rel_tol=1e-9) for v in volts):
        volts.append(witness)
    boost = p['topology']=='BOOST'
    for vin in volts:
        interior = vin not in (s['vin_min'],s['vin_max'])
        for amps in ((s['iout'],) if interior else dict.fromkeys((s['iout'],s['imin']))):
            if amps is None:
                continue
            check_calculation_cancelled()
            row = dict(vin=vin, current=amps, issues=[])
            if interior:
                row['interior_ripple']=True
            rows.append(row)
            if amps == 0:
                row['issues'].append('空载需独立检验跳脉冲／突发与输出漂升')
                continue
            q = dict(p, V_in=vin, P_out=amps*s['vout'],
                     input_voltage_case='min' if vin==s['vin_min'] else 'max')
            try:
                result = compute_design(q)
                op, wf = result['op'], result['wf']
                cs = op['I_L_pk']*q['Rs'] + slope(q)*op['D']/q['f_sw']
                # Match the low-frequency charge/ESR budget. Edge ESL is a
                # separate measurement with a specified probe bandwidth.
                bank = [(c['C'],c['ESR'],0.) for c in q['input_capacitors']]
                vcin = cap_bank_ripple(wf['t'],wf['i_cin'],bank)
                row.update(mode=op['mode'], duty=op['D'], delta_i=op['dI_L'], peak=op['I_L_pk'],
                           il_rms=op['I_L_rms'], rms_in=wf['i_cin_rms'], rms_out=wf['i_c_rms'],
                           input_ripple=float(vcin.max()-vcin.min()), ripple=wf['ripple_pp'],
                           vds=op['V_sw_max'], vrrm=op['V_d_max'], cs=cs, eta=result['eta'],
                           sense_loss=result['P_sense'], cap_rms={side:[c['total'] for c in result['capacitors'][side]['caps']]
                                                                for side in ('input','output')})
                if boost:
                    row.update(input_avg=op['I_L_avg'],diode_avg=op['I_d_avg'],diode_rms=op['I_d_rms'],
                               switch_rms=op['I_sw_rms'],
                               cs_with_margin=1.25*op['I_L_pk']*q['Rs']+rules['ramp_upper']*op['D'])
                    if op['mode']=='CCM':
                        row['rhp_hz'] = op['rhp_zero']
                        row['fc_limit'] = min(q['f_sw']/10.,row['rhp_hz']/rules['rhp_divisor'])
                if row['input_ripple'] > .02*s['vin_min']:
                    row['issues'].append('输入电容组纹波超过低线电压的 2%')
                if sum(c['C'] for c in p['output_capacitors']) < rules['C_out_step']*(1-1e-12):
                    row['issues'].append('输出有效容量低于一个周期的负载变化电荷预算')
                if row['ripple'] > rules['delta_v_limit']:
                    row['issues'].append('输出纹波超限')
                if amps == s['iout'] and row['delta_i'] > rules['delta_i_target']:
                    row['issues'].append('满载电感纹波超出目标')
                if row.get('cs_with_margin',1.25*cs) > rules['cs_min']:
                    row['issues'].append('限流余量不足 25%')
                if op['D']/q['f_sw'] < q['spice_config']['min_on_ns']*1e-9:
                    row['issues'].append('导通时间低于参考模型最小脉宽')
                (plant, _, _), _ = build_loop_models(q, op)
                if boost:
                    row['inner_radius'] = float(plant._loop_metadata['inner_spectral_radius'])
                    if row['inner_radius'] >= 1.:
                        row['issues'].append('峰值采样内环的周期特征根模达到 1')
                plants.append((row,plant))
            except (ValueError, ArithmeticError, RuntimeError) as exc:
                row['issues'].append(str(exc))
    return rows, plants


def _tune(p, plants, pm):
    from calculation_scheduler import check_calculation_cancelled
    from loop_tuning import analyze_loop, kfactor_tune
    from plants import make_compensator
    best, best_score = None, -1
    fs = p['f_sw']
    # Leave room for crossover migration with line and load. Only generated
    # Boost candidates use this rule; the normal Bode scan stays full length.
    scan_base = fs
    if p['topology'] in ('BOOST','FLYBACK'):
        scan_base = min(fs,12*.8*min(row['fc_limit'] for row,_ in plants))
    for divisor in (12, 16, 20, 30, 45, 70, 100):
        for _, anchor in plants:
            check_calculation_cancelled()
            fc = scan_base/divisor
            tune = kfactor_tune(anchor, fc, min(85.,pm+6.), p['controller_type'])
            if not tune['feasible'] or tune['fz1'] >= tune['fp1']:
                continue
            updates = {k:float(tune[k]) for k in ('KP','fz1','fp1','fz2','fp2') if tune[k] is not None}
            updates['fc_target'] = fc
            q = dict(p, **updates)
            gc = make_compensator(q).get_transfer_function()
            results, score = [], 0
            for row, plant in plants:
                m = analyze_loop(q, (plant,gc,plant*gc))
                stable=m.get('closed_loop_stable')
                if stable is None:
                    import control as ct
                    stable=all(v.real<0 for v in ct.poles(ct.feedback(plant*gc)))
                good = (stable and m['min_pm'] is not None and m['min_pm'] >= pm
                        and (m['gm_infinite'] or (m['gm_db'] is not None and m['gm_db'] >= 6))
                        and all(v['fc'] <= row.get('fc_limit',fs/10) for v in m['all_crosses']) and m['fc'] is not None)
                results.append(dict(fc=m['fc'], pm=m['min_pm'], gm_db=m['gm_db'],
                                    gm_infinite=m['gm_infinite'], stable=bool(stable), ok=bool(good),
                                    **({'gm_scan_limited':True} if m.get('gm_scan_limited') else {})))
                score += bool(good)
            if score > best_score:
                best, best_score = (updates,results), score
            if score == len(plants):
                return best
    if best is None:
        raise ValueError('当前硬件未找到可实现的补偿器，请调整电感、电容或相位裕度后重算')
    return best


def generate(request, *, cancelled=None):
    """The solver never edits its input or substitutes a different topology."""
    from input_voltage_range import _cancellation_scope
    with _cancellation_scope(cancelled):
        topo,s,mode,locked = _prepare(request)
        if topo=='FLYBACK':
            from .flyback_sizing import generate_flyback
            return generate_flyback(s,locked,request.get('windings'),cancelled=cancelled)
        from .boost_sizing import power_stage as boost_power_stage
        def size(pins):
            return boost_power_stage(s,pins) if topo=='BOOST' else _buck_power_stage(s,mode,pins)
        p, rules = size(locked)
        rows, plants = _corners(p,s,rules)
        # The lossless volt-second estimate can land exactly on an E12 value.
        # Move an unlocked L to the next size if the lossy full-load result
        # exceeds the requested ripple. Re-size dependent parts together.
        measured = max((r.get('delta_i',0.) for r in rows if r['current']==s['iout']), default=0.)
        if 'L' not in locked and measured > rules['delta_i_target']:
            revised = _standard(p['L']*measured/rules['delta_i_target'],E12,True)
            p, rules = size({**locked,'L':revised})
            rules.update(locked=list(locked), L_adjustment='按有损满载电感纹波上调')
            rows, plants = _corners(p,s,rules)
        if not plants:
            reasons = '；'.join(f"{r['vin']:g} V / {r['current']:g} A — {', '.join(r['issues'])}" for r in rows)
            raise ValueError('没有可整定的 CCM 工况。'+reasons)
        updates, margins = _tune(p,plants,s['pm'])
        p.update(updates)
        for (row,_), margin in zip(plants,margins):
            row['loop'] = margin
            if not margin['ok']:
                row['issues'].append('补偿未同时满足稳定性、PM、GM 和交越频率要求')
        from component_management import rule_for
        modeled = [r for r in rows if 'sense_loss' in r]
        config = p['component_management']
        def rating(key,metric):
            return max(r[metric] for r in modeled)/rule_for(config,key)['factor']
        requirements = dict(vds_steady_min=rating('mos_voltage','vds'),
                            vrrm_steady_min=rating('diode_voltage','vrrm'),
                            sense_rated_w=rating('resistor_power','sense_loss'),
                            inductor_load_peak=max(r['peak'] for r in modeled),
                            inductor_load_rms=max(r['il_rms'] for r in modeled),
                            cap_rms={side:[max(col) for col in zip(*(r['cap_rms'][side] for r in modeled))]
                                     for side in ('input','output')})
        # Input-capacitor RMS can peak inside the voltage range near D=0.5.
        # In triangular CCM, Ic_rms² = Io² D(1-D) + D ΔIL²/12. This bound
        # is for the complete bank, never an equal split across different ESRs.
        if topo=='BUCK' and all(r.get('mode')=='CCM' for r in rows if r['current']==s['iout']):
            delta_i = max(rules['delta_i_target'],max(r['delta_i'] for r in modeled))
            bound = math.sqrt(s['iout']**2/4 + delta_i**2/12)
            requirements['input_bank_ccm_rms_bound'] = bound
            if len(p['input_capacitors']) == 1:
                requirements['cap_rms']['input'][0] = max(bound,requirements['cap_rms']['input'][0])
        chip_name = 'TPS40200' if mode=='Voltage Mode' else 'LTC3864'
        if topo=='BOOST':
            chip_name='LM5022'
            vals=dict(R1=20000.,Vref=1.25)
            requirements.update(diode_average=max(r['diode_avg'] for r in modeled),
                                diode_rms=max(r['diode_rms'] for r in modeled),
                                mos_rms=max(r['switch_rms'] for r in modeled))
            full_load = [r for r in rows if r['current']==s['iout']]
            if all(r.get('mode')=='CCM' for r in full_load):
                # Input current is continuous. Output capacitor current is
                # the rectifier pulse less the load current. The bank's RMS
                # screen uses the largest duty and ripple independently.
                dmax = max(rules['duty_estimate'],max(r['duty'] for r in full_load))
                delta = max(rules['delta_i_target'],max(r['delta_i'] for r in full_load))
                bounds = dict(input=delta/math.sqrt(12.),
                              output=math.sqrt(s['iout']**2*dmax/(1.-dmax)+delta**2/12.))
                for side,bound in bounds.items():
                    requirements[side+'_bank_ccm_rms_bound']=bound
                    if len(p[side+'_capacitors'])==1:
                        requirements['cap_rms'][side][0]=max(requirements['cap_rms'][side][0],bound)
        elif mode=='Voltage Mode':
            vals=dict(R1=10000.,Vref=.7)
        else:
            vals=dict(R2=10000.,R1u=10000.*(s['vout']/.8-1),gm=.0018*p['spice_config']['niso_ith_gain'])
        p['__comp'] = dict(key='gm3' if chip_name=='LTC3864' else 'opamp3', type2=False, dir='fwd',
                           vars={k:dict(v=v,u='') for k,v in vals.items()})
        if 'inductor_dcr' in locked and p['inductor_dcr'] > rules['DCR_budget']:
            for row in rows:
                if row['current'] == s['iout']:
                    row['issues'].append('锁定的 DCR 超出 0.5% 额定功率的铜损预算')
        basis = dict(revision=REVISION, topology=topo, mode=mode, specification=s, rules=rules,
                     sources=[SOURCES[topo][2],SOURCES[chip_name][2]],
                     corners=rows, requirements=requirements, model_ok=all(not r['issues'] for r in rows),
                     selected={k:copy.deepcopy(p[k]) for k in ('L','inductor_dcr','Rs','input_capacitors','output_capacitors',
                                                 'controller_type',*updates)},
                     pending=['核对具体料号的偏压／温度曲线、容差、热态 DCR、饱和与纹波电流额定值',
                              '按最高限流阈值及关断延迟核对故障峰值，验证负载阶跃、热与实物 FRA'])
        p['__auto_design_basis'] = basis
        if topo=='BOOST':
            from compensation_report import compensation_snapshot
            network=compensation_snapshot(p,dict(V_out=s['vout']),p['__comp'])
            basis['compensation_pin']=dict(command_gain=network['command_scale'],kp=p['KP']/network['command_scale'],
                                           **{k:network['parts'][k] for k in ('R1','R_lower','R2','C1','C2','Vref')})
            basis['pending'].append('输出短路时输入仍可经电感和二极管供电，逐周期限流仅作用于 MOS 导通区间')
        return p


def describe(p):
    """Plain-text preview shared by both application front ends."""
    b = p['__auto_design_basis']
    if b['topology']=='FLYBACK':
        from .flyback_sizing import describe_flyback
        return describe_flyback(p)
    r = b['rules']
    fmt = lambda x: f'{x:.3g}'
    lines = ['所列工况的模型初筛通过' if b['model_ok'] else '部分角点待复核',
             f"{TOPOLOGY_MODES[b['topology']][b['mode']]}  ·  L ≥ {fmt(r['L_min']*1e6)} µH，采用 {fmt(p['L']*1e6)} µH",
             f"DCR {fmt(p['inductor_dcr']*1e3)} mΩ，采样电阻 {fmt(p['Rs']*1e3)} mΩ",
             '输入／输出电容组 ' + ' ／ '.join(' + '.join(fmt(c['C']*1e6) for c in p[side+'_capacitors'])+' µF' for side in ('input','output')),
             f"补偿 {p['controller_type']}，目标交越 {fmt(p['fc_target'])} Hz"]
    if b['topology']=='BOOST':
        lines.append(f"低线满载预计输入 {fmt(r['input_current_design'])} A，CS 附加串阻 {fmt(r['cs_external_ohm'])} Ω。")
    for row in b['corners']:
        line = f"{row['vin']:g} V · {row['current']:g} A"
        if row.get('interior_ripple'):
            line+='（区间纹波校核）'
        if 'ripple' in row:
            line += f"   {row['mode']}，纹波 {fmt(row['ripple']*1e3)} mVpp"
        if m := row.get('loop'):
            line += '，PM '+(fmt(m['pm'])+'°' if m['pm'] is not None else '未测得')
        if 'rhp_hz' in row:
            line += f"，RHP {fmt(row['rhp_hz']/1000)} kHz，交越上限 {fmt(row['fc_limit']/1000)} kHz"
        lines.append(line+'  '+('；'.join(row['issues']) or '通过'))
    req = b['requirements']
    lines.extend([f"稳态耐压初筛 Q1 ≥ {fmt(req['vds_steady_min'])} V，D1 ≥ {fmt(req['vrrm_steady_min'])} V。"
                  f"采样电阻额定 ≥ {fmt(req['sense_rated_w'])} W。",
                  '选定料号后仍需验证尖峰、负载阶跃、温升与环路。详见《自动计算参数依据》。'])
    return '\n'.join(lines)
