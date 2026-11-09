"""Specification-driven MP6005 SSR flyback. Quantities are SI; n = Np/Ns."""
import copy
import math

from .preferred_values import E12, E24, standard
from .sizing_basis import REVISION, SOURCES
from .specification import load_spec
from voltage_nodes import capacitor_voltage, input_drop, ratio_voltage


def form_context(form, current):
    from capacitor_banks import bank
    from isolated_outputs import output_specs
    form.update(conduction='CCM', hint='单路 MP6005 SSR。多路设计先在当前单元配置输出、反馈路和绕组。')
    if not current:
        return
    p=current
    rails=output_specs(p)
    fb=int(p['feedback_output'])
    ref=rails[fb-1] if rails else p
    w={k:p[k] for k in ('d_in_enable','Vf_din','feedback_mode','K')}
    w.update(feedback_output=fb, rails=[{k:r[k] for k in ('name','Ns','P_out','P_out_min','Vf_diode',
             'd_out_enable','Vf_dout')} for r in rails], coupling_config=copy.deepcopy(p['coupling_config']))
    w.update({k:ref[k] for k in ('Vf_diode','d_out_enable','Vf_dout')})
    form['windings']=w
    form['locks'].pop('inductor_dcr',None)
    form['values'].update(vout=ref['V_out'],iout=ref['P_out']/ref['V_out'],
                          imin=ref.get('P_out_min',0.)/ref['V_out'],fs=250.,kc=p.get('Kc',1.6),rth=p['Rth_transformer'])
    if rails:
        form['locks'].pop('output_capacitors',None)
        form['locks']['rail_banks']=[bank(r) for r in rails]
        form['hint']=f'{len(rails)} 路，OUT{fb} 为反馈。保留副边匝数比例、各路负载及防反配置。多路复算使用原有 kij，未填写时按 0.995 初估。'
    if p['feedback_mode']!='SSR':
        form['hint']='当前工程采用 PSR。此选型使用 SSR，请在原工程明确选择 SSR 或新建 SSR 单元。'
    elif p['f_sw']!=250e3:
        form['hint']+=f" 当前工程为 {p['f_sw']/1000:g} kHz，采用 MP6005 初版后为标称 250 kHz。"


def _rails(s, w):
    from .initial_design import _number
    if not isinstance(w,dict) or w.get('feedback_mode','SSR')!='SSR':
        raise ValueError('自动初版适用于 MP6005 SSR。PSR 请使用原边反馈设计入口。')
    raw=w.get('rails',[])
    if not isinstance(raw,list) or len(raw)>6:
        raise ValueError('反激支持 1–6 路绕组')
    fb=w.get('feedback_output',1)
    if type(fb) is not int or not 1<=fb<=max(1,len(raw)):
        raise ValueError('反馈路编号超出输出范围')
    rails=[]
    for j,r in enumerate(raw or [w]):
        if not isinstance(r,dict):
            raise ValueError('需要逐路绕组规格')
        def number(k,default):
            v=_number(r.get(k,default),k)
            if v<0: raise ValueError(k+' 不能为负数')
            return v
        ns=number('Ns',1)
        if int(ns)!=ns or not 1<=ns<=10000:
            raise ValueError('副边比例必须为正整数匝')
        rated=s['vout']*s['iout'] if j==fb-1 else number('P_out',0)
        light=(None if s['imin'] is None else s['vout']*s['imin']) if j==fb-1 else number('P_out_min',rated)
        if rated<=0 or (light is not None and light>rated):
            raise ValueError(f'OUT{j+1} 需要正的额定功率且最小功率不可超过额定值')
        rails.append(dict(name=str(r.get('name',f'OUT{j+1}'))[:24],Ns=int(ns),P_out=rated,
                          P_out_min=rated if light is None else light,Vf_diode=number('Vf_diode',.7),
                          Vf_dout=number('Vf_dout',.7),d_out_enable=bool(r.get('d_out_enable',False))))
    ref=rails[fb-1]
    ref['V_out']=s['vout']
    for r in rails:
        r['V_out']=ratio_voltage(ref,r,r['Ns']/ref['Ns']) if r is not ref else s['vout']
        if r['V_out']<=0:
            raise ValueError('副边绕组电压不足以覆盖二极管压降')
    return rails,fb-1


def _transformer(p, rails, ref, n, peak, pin, low):
    """Search actual PQ sizes and integer windings using peak flux and copper area."""
    from magnetics import CORE_SHAPES, skin_depth
    common=math.gcd(*(r['Ns'] for r in rails))
    proportions=[r['Ns']//common for r in rails]
    wire=min(.20e-3,2*skin_depth(p['f_sw'],p['rho']))
    strand_area=math.pi*wire**2/4
    cores=sorted(CORE_SHAPES['PQ'].items(),key=lambda v:v[1]['Ae']*v[1]['Wa'])
    for name,core in cores:
        min_np=max(1,math.ceil(p['L']*peak/(core['Ae']*p['Bmax'])))
        # Ns scale is common to all rails. Increasing it never changes the
        # existing inter-secondary turns ratios (including a non-OUT1 master).
        start=max(1,math.floor(min_np/(n*proportions[ref])))
        for factor in range(start,start+16):
            ns=[a*factor for a in proportions]
            np_=max(min_np,round(ns[ref]*n))
            if abs(np_/ns[ref]/n-1.)>.06:
                continue
            rms=[math.sqrt(peak*pin/low)]
            rms.extend(math.sqrt(peak*np_/count*r['P_out']/r['V_out']) for count,r in zip(ns,rails))
            strands=[max(1,math.ceil(i/(p['J']*strand_area))) for i in rms]
            fill=strand_area*sum(a*b for a,b in zip([np_,*ns],strands))/core['Wa']
            if fill>p['Ku']: break
            for r,count,num in zip(rails,ns,strands[1:]):
                r.update(Ns=count,d_wire_s=wire,n_strand_s=num)
            p.update(core_choice=name,core_shape='PQ',Np=np_,Ns=ns[0],N=np_/ns[0],MLT=core['MLT'],
                     d_wire_p=wire,n_strand_p=strands[0],d_wire_s=wire,n_strand_s=strands[1])
            return dict(core=name,Ae=core['Ae'],Wa=core['Wa'],turns=[np_,*ns],strands=strands,
                        wire=wire,fill_est=fill,AL=p['L']/np_**2)
    raise ValueError('磁通及窗口约束下未找到可绕制的 PQ 磁芯，请调整规格或手动设计磁件')


def _cap(c, esr):
    return [dict(C=standard(c,E12,True),ESR=standard(min(.035,esr),E24,False),ESL=1e-9)]


def _size(s,locked,w):
    from capacitor_banks import normalize
    from spice_export import mp6005_preset
    from winding_coupling import validate_coupling_config
    from magnetics import STEINMETZ_MATERIALS
    rails,ref=_rails(s,w)
    manual_rails=bool(w.get('rails'))
    if ('rail_banks' in locked and (not manual_rails or len(locked['rail_banks'])!=len(rails))) or (manual_rails and 'output_capacitors' in locked):
        raise ValueError('输出电容组锁定项必须与当前绕组一一对应')
    p=load_spec(dict(topology='FLYBACK',control_mode='Peak Current Mode',controller_type='type2'))
    p.update(V_in=s['vin_min'],V_in_min=s['vin_min'],V_in_max=s['vin_max'],input_voltage_case='min',
             V_out=s['vout'],P_out=sum(r['P_out'] for r in rails),f_sw=s['fs'],eta_guess=s['eta_guess'],
             feedback_mode='SSR',feedback_output=ref+1,A_sense=11.,ripple_target=s['ripple'],pm_target=s['pm'],
             K=w.get('K',.99),Kc=s['kc'],dC=.1,Bmax=.22,Bsat=.35,Ku=.30,J=4e6,
             Rth_transformer=s['rth'],core_material='N87',ma_slope=0.,
             d_in_enable=bool(w.get('d_in_enable',False)),Vf_din=w.get('Vf_din',.7),
             spice_config=mp6005_preset())
    coeff=STEINMETZ_MATERIALS[p['core_material']]
    p.update(k_core=coeff['k'],a_core=coeff['a'],b_core=coeff['b'])
    from .initial_design import _number
    if _number(p['Vf_din'],'输入防反管压降')<0 or not 0<_number(p['K'],'K')<=1:
        raise ValueError('漏感系数或输入防反压降超出范围')
    low,high=(x-input_drop(p) for x in (s['vin_min'],s['vin_max']))
    if low<8:
        raise ValueError('输入防反压降后，MP6005 供电母线需达到 8 V；独立偏置供电请另行核算')
    duty,fs=s['duty_target'],s['fs']
    dcm=s['conduction']=='DCM'
    idle=.15 if dcm else 0.
    vr=low*duty/(1.-duty-idle)
    ref_rect=capacitor_voltage(rails[ref])+rails[ref]['Vf_diode']
    n=vr/ref_rect
    pin=p['P_out']/s['eta_guess']
    # Use the higher of the physical reflected voltage and the calculator's
    # fixed-efficiency equivalent to screen the high-line ripple.
    vr_budget=1.06*n*max(ref_rect,s['vout']/s['eta_guess'])
    volt_seconds=s['vin_max']*vr_budget/(s['vin_max']+vr_budget)
    l_bound=(low*duty)**2/(2.*pin*fs) if dcm else volt_seconds**2/(fs*pin*s['il_ratio'])
    p['L']=locked.get('L',standard(l_bound,E12,not dcm))
    ip_on=pin/(low*duty)
    peak=math.sqrt(2*pin/(p['L']*fs)) if dcm else max(
        ip_on+volt_seconds/(2*fs*p['L']),pin/(low*(.94*vr/(low+.94*vr)))+low*duty/(2*fs*p['L']))
    # A locked small L can move the design into DCM.
    peak=max(peak,math.sqrt(2*pin/(p['L']*fs)))
    tr=_transformer(p,rails,ref,n,peak,pin,low)
    rs=standard(.140/(1.25*peak),E24,False)
    p['Rs']=rs
    p['input_capacitors']=locked.get('input_capacitors',_cap(pin/(low*fs*.01*low),.01*low/peak))
    budgets=[]
    for j,r in enumerate(rails):
        io=r['P_out']/r['V_out']
        i_secondary=peak*p['Np']/r['Ns']
        dv=s['ripple']*r['V_out']
        # For DCM the capacitor can supply load during both Ton and dead time.
        cap_time=1. if dcm or len(rails)>1 else max(duty,vr_budget/(low+vr_budget))
        charge=io*cap_time/(fs*.5*dv)
        step=(r['P_out']-r['P_out_min'])/(r['V_out']*fs*dv)
        esr=.5*dv/i_secondary
        r['output_capacitors']= (locked['rail_banks'][j] if 'rail_banks' in locked else
                                 locked.get('output_capacitors',_cap(max(charge,step),esr)))
        r['ripple_target']=s['ripple']
        budgets.append(dict(charge=charge,step=step,esr=esr))
    main=rails[ref]
    p.update({k:main[k] for k in ('V_out','P_out_min','output_capacitors','d_out_enable','Vf_dout','Vf_diode')})
    if manual_rails:
        config=validate_coupling_config(w.get('coupling_config') or {},len(rails))
        p.update(outputs=rails,coupling_config=dict(enabled=True,k=config['K'].tolist()))
    # Use the same fixed engineering slope in the Bode calculation and the
    # exported behavior model. MP6005 does not specify this internal value.
    p['ma_slope']=.75*(p['Np']/main['Ns'])*ref_rect/p['L']
    p['spice_config']['slope_mode']=0.
    p=load_spec(normalize(p))
    rules=dict(L_bound=l_bound,peak_design=peak,reflected_target=vr,ratio_target=n,idle_target=idle,
               delta_i_ratio=s['il_ratio'],cap_budgets=budgets,cs_min=.14,cs_typ=.16,cs_max=.18,
               clamp_ratio=p['Kc'],geometry=tr,locked=list(locked),secondary_ratio_preserved=manual_rails)
    return p,rails,ref,rules


def _corners(p,rails,ref,s):
    from calculation_scheduler import check_calculation_cancelled, CalculationCancelled
    from loss_model import compute_design
    from flyback_clamp import rcd_components
    from plants import build_loop_models
    from waveforms import cap_bank_ripple
    rows,plants,nominal=[],[],{}
    full=[r['P_out'] for r in rails]
    light=[r['P_out_min'] for r in rails]
    for vin in dict.fromkeys((s['vin_min'],s['vin_max'])):
        for powers in ([full,light] if full!=light else [full]):
            check_calculation_cancelled()
            row=dict(vin=vin,current=powers[ref]/s['vout'],powers=list(powers),rated=powers==full,issues=[])
            rows.append(row)
            if min(powers)==0:
                row['issues'].append('含真空载，当前连续 PWM / 恒阻模型不能验证漂升、跳脉冲或预负载')
                continue
            q=dict(p,V_in=vin,input_voltage_case='min' if vin==s['vin_min'] else 'max',P_out=sum(powers),
                   outputs=[dict(r,P_out=w) for r,w in zip(p['outputs'],powers)])
            try:
                result=compute_design(q)
                op,tr,wf=result['op'],result['mag']['transformer'],result['wf']
                if row['rated']:
                    nominal[vin]=result
                parts=rcd_components(op,q)
                outputs=result['outputs'] or [dict(op=op,ripple_pp=wf['ripple_pp'],capacitors=result['capacitors'])]
                branch=[dict(vout=o['op']['V_out'],ripple=o['ripple_pp'],vrrm=o['op']['V_d_max'],
                             diode_rms=o['op']['I_d_rms'],diode_peak=o['op']['I_d_pk'],
                             cap_rms=[c['total'] for c in o['capacitors']['output']['caps']]) for o in outputs]
                vin_ripple=cap_bank_ripple(wf['t'],wf['i_cin'],[(c['C'],c['ESR'],0.) for c in p['input_capacitors']])
                ipk=op['I_sw_pk']
                row.update(mode=op['mode'],duty=op['D'],idle=max(0.,1-op['D']-op['Dp']),peak=ipk,
                           primary_rms=op['I_sw_rms'],input_ripple=float(vin_ripple.max()-vin_ripple.min()),
                           input_cap_rms=[c['total'] for c in result['capacitors']['input']['caps']],
                           ripple=branch[ref]['ripple'],outputs=branch,eta=result['eta'],vds=op['V_sw_max'],
                           reflected=op['V_r'],cs=ipk*p['Rs'],sense_loss=result['P_sense'],clamp_loss=result['P_rcd'],
                           rcd_r=parts['R_snub'] if math.isfinite(parts['R_snub']) else None,rcd_c=parts['C_snub'],
                           bpeak=tr['B_pk'],fill=tr['fill'],temp_rise=tr['dT'],fc_limit=s['fs']/10.)
                if row['mode']=='CCM' and math.isfinite(op['rhp_zero']):
                    row['rhp_hz']=op['rhp_zero']
                    row['fc_limit']=min(row['fc_limit'],row['rhp_hz']/5.)
                if row['cs']*1.25>.14: row['issues'].append('最低逐周期限流门限的 25% 峰值余量不足')
                if row['duty']>=.7 or row['duty']/s['fs']<=250e-9:
                    row['issues'].append('脉宽超出 MP6005 最大占空比或前沿消隐窗口')
                if row['rated'] and row['mode']!=s['conduction']:
                    row['issues'].append('额定工作模式与所选 CCM/DCM 不符')
                if row['rated'] and row['mode']=='CCM':
                    peak, valley=op['I_L_pk'],op['I_L_min']
                    row['ripple_ratio']=2*(peak-valley)/max(peak+valley,1e-12)
                    if row['ripple_ratio']>s['il_ratio']:
                        row['issues'].append('满载励磁电流纹波比例超限')
                if row['rated'] and s['conduction']=='DCM' and row['idle']<.10:
                    row['issues'].append('满载剩余退磁空闲时间低于周期的 10%')
                if row['bpeak']>p['Bmax'] or row['fill']>p['Ku'] or row['temp_rise']>p['temp_rise_limit']:
                    row['issues'].append('磁通、窗口或估计温升超过设计目标')
                if row['input_ripple']>.02*s['vin_min']: row['issues'].append('输入低频纹波超过低线的 2%')
                for j,(o,r) in enumerate(zip(branch,rails),1):
                    if o['ripple']>r['V_out']*s['ripple']: row['issues'].append(f'OUT{j} 输出纹波超限')
                (plant,_,_),_=build_loop_models(q,op)
                plants.append((row,plant))
            except CalculationCancelled:
                raise
            except (ValueError,ArithmeticError,RuntimeError) as exc:
                row['issues'].append('工作点或小信号模型不可用：'+str(exc))
    return rows,plants,nominal


def generate_flyback(s,locked,w,*,cancelled=None):
    from component_management import rule_for
    from compensation_report import compensation_snapshot
    from cross_regulation import scan_cross_regulation
    from .initial_design import _tune
    p,rails,ref,rules=_size(s,locked,{} if w is None else w)
    rows,plants,nominal=_corners(p,rails,ref,s)
    if not plants or any(r['rated'] and 'vds' not in r for r in rows):
        raise ValueError('无法完成反激额定工况的校核或整定。'+'；'.join(dict.fromkeys(i for r in rows for i in r['issues'])))
    updates,margins=_tune(p,plants,s['pm'])
    p.update(updates)
    for (row,_),margin in zip(plants,margins):
        row['loop']=margin
        if not margin['ok']:
            if margin.get('gm_scan_limited') and margin['gm_db'] is None:
                row['issues'].append('扫频未遇到 −180° 相位交点，增益裕度待验证')
            if not margin['stable'] or margin['pm'] is None or margin['pm']<s['pm']:
                row['issues'].append('闭环极点或相位裕度未满足要求')
            if margin['gm_db'] is not None and margin['gm_db']<6:
                row['issues'].append('增益裕度不足 6 dB')
            if not row['issues']:
                row['issues'].append('存在未验证或超过带宽上限的交越')
    vcap=capacitor_voltage(rails[ref])
    led=standard((vcap-3.5)/.002,E24,False)
    vals=dict(R1=20000.,CTR=1.,Rpullup=10000.,Copto=100e-12,R_LED=led)
    p['__comp']=dict(key='tl431nf',dir='fwd',type2=False,vars={k:dict(v=v,u='') for k,v in vals.items()})
    net=compensation_snapshot(p,dict(V_out=s['vout'],V_feedback=vcap),p['__comp'])
    rated_rows=[r for r in rows if 'vds' in r]
    factor=lambda key:rule_for(p['component_management'],key)['factor']
    req=dict(vds_min=max(r['vds'] for r in rated_rows)/factor('mos_voltage'),
             vrrm_min=[max(r['outputs'][i]['vrrm'] for r in rated_rows)/factor('diode_voltage') for i in range(len(rails))],
             input_cap_rms=[max(vals) for vals in zip(*(r['input_cap_rms'] for r in rated_rows))],
             output_cap_rms=[[max(vals) for vals in zip(*(r['outputs'][i]['cap_rms'] for r in rated_rows))] for i in range(len(rails))],
             sense_rated_w=max(r['sense_loss'] for r in rated_rows)/factor('resistor_power'),
             clamp_rated_w=max(r['clamp_loss'] for r in rated_rows)/factor('resistor_power'))
    clamp=max(rated_rows,key=lambda r:r['clamp_loss'])
    req.update(clamp_vin=clamp['vin'],rcd_r=clamp['rcd_r'],rcd_c=clamp['rcd_c'])
    cross=None
    if len(rails)>1:
        reference=nominal.get(s['vin_min'])
        cross=scan_cross_regulation(p,reference_result=reference,cancelled=cancelled,include_flyback_stress=True,
                                    known_ops={v:r['op'] for v,r in nominal.items()})
        cross={k:cross.get(k) for k in ('complete','supported','total_cases','error','summary','cases')}
        cross['issues']=[]
        for case in cross['cases']:
            if case['status']!='ok': continue
            stress=case['stress']
            req['vds_min']=max(req['vds_min'],stress['vds']/factor('mos_voltage'))
            req['vrrm_min']=[max(v,w/factor('diode_voltage')) for v,w in zip(req['vrrm_min'],stress['vrrm'])]
            req['sense_rated_w']=max(req['sense_rated_w'],stress['sense_loss']/factor('resistor_power'))
            if stress['clamp_loss']/factor('resistor_power')>req['clamp_rated_w']:
                req.update(clamp_rated_w=stress['clamp_loss']/factor('resistor_power'),clamp_vin=case['V_in'],
                           rcd_r=stress['rcd_r'],rcd_c=stress['rcd_c'],clamp_case=case['id'])
            if stress['peak']*p['Rs']*1.25>rules['cs_min']:
                cross['issues'].append(case['id']+' 混合负载的最低限流门限余量不足')
    basis=dict(topology='FLYBACK',mode='Peak Current Mode',revision=REVISION,specification=s,rules=rules,
               corners=rows,requirements=req,feedback_output=ref+1,cross_regulation=cross,
               compensation_pin={k:net['parts'].get(k) for k in ('R1','R_lower','R_LED','R2','C1','C2','Rpullup','Copto')},
               compensation_buildable=net['buildable'],model_ok=bool(net['buildable'] and all(not r['issues'] for r in rows)
                                              and (cross is None or (cross['complete'] and not cross['issues']))),
               sources=[SOURCES[k][2] for k in ('FLYBACK','MP6005','FLYBACK-DCM','RCD','CROSS')],
               pending=['用实物确认气隙与 AL、各绕组漏感／耦合、热阻、光耦 CTR 及 TL431 最低偏置。',
                        '按最高正常门限、消隐及关断延时另验故障峰值；整流反压未计尖峰，RCD 的固定阻容需台架复核。',
                        '最低负载及连续 PWM 以外的跳脉冲、启动、负载阶跃与实物 FRA 单独验证。'])
    p['__auto_design_basis']=basis
    return p


def describe_flyback(p):
    b=p['__auto_design_basis'];g=b['rules']['geometry'];req=b['requirements']
    lines=['所列工况的模型初筛通过' if b['model_ok'] else '部分项目待复核',
           f"MP6005 · SSR · 满载目标 {b['specification']['conduction']}，反馈 OUT{b['feedback_output']}",
           f"{g['core']} · 原边 / 各副边匝数 "+' / '.join(str(n) for n in g['turns'])+
           f" · Lm {p['L']*1e6:.3g} µH · AL {g['AL']*1e9:.3g} nH/匝²",
           f"采样 {p['Rs']*1000:.3g} mΩ，额定 ≥ {math.ceil(req['sense_rated_w']*100)/100:g} W。Q1 耐压 ≥ {math.ceil(req['vds_min'])} V。"]
    for row in b['corners']:
        msg=f"{row['vin']:g} V · 各路负载 "+'/'.join(f'{v:.3g}' for v in row['powers'])+' W'
        if 'ripple' in row: msg+=f" · {row['mode']} · 原边峰值 {row['peak']:.3g} A · 反馈路纹波 {row['ripple']*1000:.3g} mVpp"
        if (row.get('loop') or {}).get('pm') is not None: msg+=f" · PM {row['loop']['pm']:.1f}°"
        lines.append(msg+'  '+('；'.join(row['issues']) or '通过'))
    lines.append('各路整流管耐压下限（未计尖峰） '+' / '.join(f'{math.ceil(v)} V' for v in req['vrrm_min']))
    if not b['compensation_buildable']: lines.append('TL431 / 光耦阻容当前不能实现，需调整。')
    if c:=b['cross_regulation']:
        lines.append(f"交叉负载 {sum(case['status']=='ok' for case in c['cases'])}/{len(c['cases'])} 工况完成。"+(c['error'] or ''))
        lines.extend(c.get('issues',[]))
        for r in c['summary']:
            if not r['feedback'] and r['V_min'] is not None:
                lines.append(f"OUT{r['id']} 已求工况端口 {r['V_min']:.3g}–{r['V_max']:.3g} V")
        if any('stress' in case for case in c['cases']):
            lines.append('器件耐压和采样／钳位电阻额定功耗已计入有解的混合负载。')
        lines.append('各非反馈路电压范围须与下游允许值对照。')
    return '\n'.join(lines+['选型和待测项见《自动计算参数依据》。'])
