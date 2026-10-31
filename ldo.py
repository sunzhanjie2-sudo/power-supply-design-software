"""Linear-regulator static design; independent of switching converter models.

Iq is the worst-case ground current, excluding load and divider current.
Thermal estimates use the user's effective board-to-ambient theta, not an
assertion that the datasheet test-board value applies to the actual PCB.
"""
import copy
import math

DEFAULTS = dict(design_type='ldo', topology='LDO', V_in=5., V_in_min=4.75, V_in_max=5.25,
    V_out=3.3, I_out_min=.01, I_out_max=.1, dropout_max=.3, Iq_max=50e-6,
    manufacturer='', model='', package='', input_rating_min=None, input_rating_max=None,
    current_rating=None, ambient=50., theta_ja=100., junction_limit=125., thermal_verified=False,
    accuracy_pct=1., output_mode='fixed', Vref=1.2, R_top=10000., follow_input=True,
    C_in=1e-6, C_out=2.2e-6, ESR_out=.01, required_C_in=None, required_C_out=None,
    required_ESR_min=None, required_ESR_max=None, reverse_blocking='unknown', enable_pin=False,
    power_good=False, component_management={}, notes='')

FIELDS = [
 ('电路需求',[('V_in_min','输入下限','V',1),('V_in_max','输入上限','V',1),('V_out','输出电压','V',1),('I_out_min','最小负载','mA',.001),('I_out_max','最大负载','mA',.001),('accuracy_pct','规格书输出精度 ±','%',1)]),
 ('芯片电气',[('dropout_max','最大压差（对应最大电流/温度）','mV',.001),('Iq_max','最大接地静态电流 Iq','µA',1e-6),('input_rating_min','推荐工作输入下限','V',1),('input_rating_max','推荐工作输入上限','V',1),('current_rating','额定输出电流','mA',.001)]),
 ('热设计',[('ambient','最高环境温度','°C',1),('theta_ja','有效结至环境热阻','K/W',1),('junction_limit','设计结温上限','°C',1)]),
 ('外围与稳定性要求',[('C_in','输入电容有效容量','µF',1e-6),('C_out','输出电容有效容量','µF',1e-6),('ESR_out','输出电容 ESR','mΩ',.001),('required_C_in','规格书最小输入电容','µF',1e-6),('required_C_out','规格书最小输出电容','µF',1e-6),('required_ESR_min','规格书 ESR 下限','mΩ',.001),('required_ESR_max','规格书 ESR 上限','mΩ',.001)]),
 ('可调输出分压',[('Vref','可调型基准电压','V',1),('R_top','上分压电阻 R1','kΩ',1000)]),
]
OPTIONAL={'input_rating_min','input_rating_max','current_rating','required_C_in','required_C_out','required_ESR_min','required_ESR_max'}

def is_ldo(spec):
    return isinstance(spec,dict) and (spec.get('design_type')=='ldo' or spec.get('topology')=='LDO')

def normalize(value=None):
    from component_management import normalize_management
    if value is not None and not isinstance(value,dict):raise ValueError('LDO 配置必须为对象')
    p=copy.deepcopy(DEFAULTS);p.update(copy.deepcopy(value or {}))
    for k in ('manufacturer','model','package','notes'):
        if not isinstance(p[k],str):raise ValueError(k+' 必须为文字')
        p[k]=p[k].strip()[:1000]
    keys={k for _,fields in FIELDS for k,_,_,_ in fields}|{'V_in'}
    for k in keys:
        v=p[k]
        if k in OPTIONAL and (v is None or v==''):p[k]=None;continue
        if isinstance(v,bool) or not isinstance(v,(int,float)) or not math.isfinite(v):raise ValueError(k+' 须为有限数值；未知额定值留空')
        if k=='ambient':
            if not -273.15<v<250:raise ValueError('环境温度超出有效范围')
        elif v<0 or (k not in {'I_out_min','Iq_max','dropout_max','ESR_out','accuracy_pct','required_ESR_min'} and v==0):raise ValueError(k+' 须为正数或允许的零值')
        p[k]=float(v)
    if not p['V_in_min']<=p['V_in_max']:raise ValueError('输入上限不得小于下限')
    if p['I_out_min']>p['I_out_max']:raise ValueError('最小负载不得大于最大负载')
    if p['accuracy_pct']>=100:raise ValueError('输出精度须小于100%')
    if p['output_mode'] not in ('fixed','adjustable'):raise ValueError('输出类型无效')
    if p['output_mode']=='adjustable' and p['V_out']<=p['Vref']:raise ValueError('可调输出须高于基准电压')
    if p['reverse_blocking'] not in ('unknown','yes','no'):raise ValueError('反向电流保护选项无效')
    for k in ('thermal_verified','follow_input','enable_pin','power_good'):
        if not isinstance(p[k],bool):raise ValueError(k+' 必须为布尔值')
    for lo,hi in [('input_rating_min','input_rating_max'),('required_ESR_min','required_ESR_max')]:
        if p[lo] is not None and p[hi] is not None and p[lo]>p[hi]:raise ValueError(lo+' 不得高于上限')
    p['component_management']=normalize_management(p['component_management'])
    p.update(design_type='ldo',topology='LDO',P_out=p['V_out']*p['I_out_max'],V_in=p['V_in_min'])
    # Compatibility only; network input demand uses input_power(), never this scalar.
    p['eta_guess']=p['P_out']/input_power(p,p['V_in_max'])
    return p

def divider(p):
    if p['output_mode']=='fixed':return dict(R_top=None,R_bottom=None,I_divider=0.,P_top=0.,P_bottom=0.)
    bottom=p['R_top']*p['Vref']/(p['V_out']-p['Vref']);i=p['V_out']/(p['R_top']+bottom)
    return dict(R_top=p['R_top'],R_bottom=bottom,I_divider=i,P_top=i*i*p['R_top'],P_bottom=i*i*bottom)

def input_power(p,vin,current=None):
    return vin*((p['I_out_max'] if current is None else current)+divider(p)['I_divider']+p['Iq_max'])

def operating_point(p,vin,current):
    d=divider(p);pass_current=current+d['I_divider'];pin=input_power(p,vin,current);pout=p['V_out']*current
    required=p['V_out']*(1+p['accuracy_pct']/100)+p['dropout_max'];margin=vin-required
    regulation=margin>=-1e-12;overcurrent=p['current_rating'] is not None and pass_current>p['current_rating']+1e-12
    # Loss and temperature have a valid regulated interpretation only with headroom.
    chip=(vin-p['V_out'])*pass_current+vin*p['Iq_max'] if regulation else None
    return dict(V_in=vin,I_out=current,I_pass=pass_current,I_in=pass_current+p['Iq_max'],V_required=required,
        headroom=vin-p['V_out'],dropout_margin=margin,regulated=regulation,
        V_out=p['V_out'] if regulation else None,V_out_min=p['V_out']*(1-p['accuracy_pct']/100) if regulation else None,
        V_out_max=p['V_out']*(1+p['accuracy_pct']/100) if regulation else None,
        P_in=pin if regulation else None,P_out=pout if regulation else None,P_chip=chip,
        P_divider=d['P_top']+d['P_bottom'],P_loss=pin-pout if regulation else None,
        eta=pout/pin if regulation and pin else None,T_j=p['ambient']+chip*p['theta_ja'] if chip is not None else None,
        within_current_rating=None if p['current_rating'] is None else not overcurrent)

def calculate(raw):
    from component_management import rule_for
    p=normalize(raw);d=divider(p);corners=[]
    for label,vin in [('Vinmin',p['V_in_min']),('Vinmax',p['V_in_max'])]:
        for load,current in [('轻载',p['I_out_min']),('满载',p['I_out_max'])]:corners.append(dict(id=label+'_'+load,**operating_point(p,vin,current)))
    rows=[]
    def check(key,name,value,limit,unit='',lower=False,note=''):
        state='undefined' if value is None or limit is None else 'pass' if (value>=limit-1e-12 if lower else value<=limit+1e-12) else 'review'
        rows.append(dict(id=key,name=name,value=value,limit=limit,unit=unit,state=state,note=note,comparison='>=' if lower else '<='))
    check('dropout','Vinmin 稳压压差裕量',corners[1]['dropout_margin'],0,'V',True,'采用最大压差与输出精度上限；压差值须覆盖最大电流/温度')
    check('input_min','推荐输入下限',p['V_in_min'],p['input_rating_min'],'V',True)
    check('input_max','推荐输入上限',p['V_in_max'],p['input_rating_max'],'V')
    check('current','最大通过电流（含分压）',corners[-1]['I_pass'],p['current_rating'],'A')
    tj=[c['T_j'] for c in corners if c['T_j'] is not None]
    check('thermal','端点最高估算结温（标称Vo）',max(tj) if tj else None,p['junction_limit'],'°C',note='只统计可稳压角点；压差失败角点不伪造温度和效率')
    check('thermal_evidence','有效热阻证据',1 if p['thermal_verified'] else None,1,note='需匹配实际 PCB 铜面积、层数及散热条件')
    for k,name in [('C_in','输入有效容量'),('C_out','输出有效容量')]:check(k,name,p[k],p['required_'+k],'F',True)
    check('esr_min','输出 ESR 下限',p['ESR_out'],p['required_ESR_min'],'Ω',True)
    check('esr_max','输出 ESR 上限',p['ESR_out'],p['required_ESR_max'],'Ω')
    items=p['component_management']['items'];bom=[]
    for ref,role,kind,v,power in [('U1','LDO 稳压芯片','ic',p['V_in_max'],None),('C_IN1','输入电容','capacitor',p['V_in_max'],None),('C_OUT1','输出电容','capacitor',p['V_out']*(1+p['accuracy_pct']/100),None)]+([('R1','上分压电阻','resistor',None,d['P_top']),('R2','下分压电阻','resistor',None,d['P_bottom'])] if p['output_mode']=='adjustable' else []):
        item=items.get(ref,{});e=dict(ref=ref,role=role,kind=kind,quantity=1,**item)
        if ref=='U1':e.update({k:p[k] for k in ('manufacturer','model','package')})
        if kind=='resistor':
            rule=rule_for(p['component_management'],'resistor_power');rating=item.get('power_W');limit=rating*rule['factor'] if rating else None
            check('bom_'+ref,ref+' 平均功耗降额',power,limit,'W',note='电阻额定功率的20%（或已注明依据的自定义值）；脉冲需另核对')
            e.update(value=power,rating=rating,factor=rule['factor'],limit=limit,state=rows[-1]['state'])
        elif kind=='capacitor':
            cap_type=item.get('capacitor_type','unknown');rule=rule_for(p['component_management'],cap_type+'_voltage' if cap_type in ('electrolytic','mlcc','film') else 'other_voltage');rating=item.get('voltage_V');limit=rating*rule['factor'] if rating and rule['factor'] else None
            check('bom_'+ref,ref+' 耐压降额',v,limit,'V',note='未计算电容瞬态纹波 RMS；未将容量/ESR检查当作环路稳定性证明')
            e.update(value=v,rating=rating,factor=rule['factor'],limit=limit,state=rows[-1]['state'])
        else:e.update(value=p['V_in_max'],rating=p['input_rating_max'],factor=None,limit=p['input_rating_max'],state=next(r['state'] for r in rows if r['id']=='input_max'))
        if any(not e.get(k) for k in ('manufacturer','model','package')):check('identity_'+ref,ref+' 厂家/型号/封装',None,1,note='器件身份资料未填全')
        bom.append(e)
    notes=['静态线性稳压估算；Iq 为接地电流，不包含负载及外部分压。','输出精度为用户填写的规格书包络，不叠加未知的线性/负载调整率；功耗、温升及系统后级预算使用标称输出电压。','有效容量和 ESR 仅核对已填写规格书条件；不产生通用 Bode/稳定性、PSRR、噪声或瞬态预测。','反向电流保护：'+{'unknown':'未知，需核对掉电或输出被外部供电时的能力','yes':'已声明具备，仍需遵守芯片条件','no':'无保护，存在回灌可能时需外部处理'}[p['reverse_blocking']]]
    return dict(schema='power.ldo-result/1',spec=p,corners=corners,divider=d,checks=rows,bom=bom,notes=notes,
        worst=dict(P_chip=max((c['P_chip'] for c in corners if c['P_chip'] is not None),default=None),T_j=max(tj) if tj else None),
        state='review' if any(r['state']=='review' for r in rows) else 'undefined' if any(r['state']=='undefined' for r in rows) else 'pass')
