"""Charge-balanced QR flyback using the existing full winding RL circuit.

Each cycle starts after all rectifier/clamp currents have extinguished. The
ON and demagnetization intervals are exact active-set RL flows. Constant-C
lossless valley timing closes the period; that timing is not a resonant
current/voltage field solution or a complete L6565 silicon model.
"""
from __future__ import annotations

import copy
import math
from functools import lru_cache

import numpy as np
from scipy.optimize import least_squares

from coupled_flyback import (_Circuit, _Segment, _segment_integrals,
    _sample_solution, CoupledConvergenceError, finish_operating_point)
from winding_coupling import resolve_winding_model


def _filtered_cs(t, ton, period, vin, lp, resistance, rs, tau):
    """Periodic one-pole CS value during an RL primary ON ramp, in raw V."""
    def unforced_start(x):
        if x <= 0: return 0.
        if tau <= 0:
            current = vin/lp*x if resistance <= 1e-16 else vin/resistance*(-math.expm1(-resistance/lp*x))
            return rs*current
        fast=math.exp(-x/tau)
        if resistance <= 1e-16:
            return rs*vin/lp*(x-tau*(-math.expm1(-x/tau)))
        a=resistance/lp
        difference=(x/tau*fast if abs(1-a*tau)<1e-7 else (math.exp(-a*x)-fast)/(1-a*tau))
        return max(0.,rs*vin/resistance*(-math.expm1(-x/tau)-difference))
    value=unforced_start(t)
    if tau>0:
        # CS is zero when the MOS is off. Retain the exact periodic filter
        # residue instead of silently resetting its capacitor every cycle.
        initial=unforced_start(ton)*math.exp(-(period-ton)/tau)/(-math.expm1(-period/tau))
        value+=initial*math.exp(-t/tau)
    return value


def _cycle(circuit, ton, voltage, nominal_period, ring, valley):
    """Return the physical energy-transfer segments and an explicit idle."""
    from calculation_scheduler import check_calculation_cancelled
    check_calculation_cancelled()
    middle,on=circuit._phase(np.zeros(circuit.count),True,ton,voltage,0.)
    # A conservative search horizon; its empty tail is removed. Extending the
    # horizon cannot manufacture an ON pulse or a residual-current fallback.
    flux=np.abs(circuit.L @ middle)
    reset=np.r_[circuit.clamp,voltage+circuit.vf]
    duration=max(4*nominal_period,4*float(np.max(flux/np.maximum(reset,1e-12))),4*ton)
    for _ in range(5):
        end,off=circuit._phase(middle,False,duration,voltage,ton)
        if np.max(np.abs(end))<=circuit.current_tol and off and not off[-1].active:
            break
        duration*=4
        check_calculation_cancelled()
    else:
        raise CoupledConvergenceError('QR 绕组未在关断搜索窗口内完全退磁，不能生成谷底周期')
    transfer=[segment for segment in off if segment.active]
    reset_end=transfer[-1].t+transfer[-1].dt if transfer else ton
    period=reset_end+(2*valley-1)*ring
    idle=_Segment(reset_end,period-reset_end,(),np.empty(0),np.empty(0),None,False)
    return np.zeros(circuit.count),on+transfer+[idle],period,reset_end-ton


def _rcd_hardware(p):
    """An optional frozen resistor/capacitor, never a per-corner redesign."""
    value=p.get('_qr_rcd_hardware')
    if value is None:return None
    if not isinstance(value,dict):raise ValueError('固定 QR RCD 硬件必须为 R_ohm/C_F 对象')
    result={}
    for key in ('R_ohm','C_F'):
        x=value.get(key)
        if isinstance(x,bool) or not isinstance(x,(int,float)) or not math.isfinite(x) or x<=0:
            raise ValueError(f'固定 QR RCD {key} 必须为有限正数；零钳位功率不能生成有限RCD硬件')
        result[key]=float(x)
    result['source']=str(value.get('source','explicit-fixed-hardware'))
    return result


@lru_cache(maxsize=6)
def _solution(matrix,dcr,vin,vf,ron,rs,clamp,target,blocking,rated,main,
              nominal_period,nominal_ton,ring,timing,rcd):
    from calculation_scheduler import check_calculation_cancelled
    check_calculation_cancelled()
    target,blocking,rated=np.asarray(target),np.asarray(blocking),np.asarray(rated)
    count=len(target);other=[j for j in range(count) if j!=main]
    target_cap=target+blocking;load_r=target**2/rated
    load_scale=np.maximum(rated/target,1e-4)
    circuit=_Circuit(matrix,dcr,vin,vf,np.zeros(count),ron,rs,clamp,nominal_period)
    toffmin,tofflight,cs0,csmax,tau,delay,tonmin,tonmax=timing
    # Solve one continuous valley branch at a time. Enumerating a branch is
    # not a stability claim: its own blanking inequalities are checked below.
    minimum_on=max(tonmin+delay,nominal_ton*.0001,1e-10)
    maximum_on=min(tonmax,max(nominal_period*30,nominal_ton*30))
    if minimum_on>=maximum_on:
        raise ValueError('QR 最小导通/延时不低于最大导通约束')
    lower=np.r_[np.full(len(other),.01),minimum_on/nominal_ton]
    upper=np.r_[np.full(len(other),8.),maximum_on/nominal_ton]
    x0=np.r_[np.ones(len(other)),1.]
    if rcd:
        # Freeze real R and solve its mean capacitor voltage together with
        # every independent output's charge. The reference Kc is only a seed.
        minimum_clamp=float(np.max(np.asarray([math.sqrt(matrix[0][0]/matrix[j+1][j+1])
            for j in range(count)])*(target_cap+np.asarray(vf))))*1.001
        lower=np.r_[lower,minimum_clamp/clamp]
        upper=np.r_[upper,max(8.,minimum_clamp/clamp*2)]
        x0=np.r_[x0,1.]
        clamp_power_scale=clamp**2/rcd[0]
    x0=np.clip(x0,lower+1e-8,upper-1e-8)
    maximum_valley=max(1,2+int(math.ceil(max(toffmin,tofflight)/(2*ring))))
    if maximum_valley>128:
        raise CoupledConvergenceError('QR 消隐跨越超过128个候选谷底，当前单周期模型不支持此时序范围')
    visited=set();valley=1;best_error=math.inf
    for branch_attempt in range(maximum_valley):
        check_calculation_cancelled()
        if valley in visited:
            remaining=[n for n in range(1,maximum_valley+1) if n not in visited]
            if not remaining:break
            valley=remaining[0]
        visited.add(valley)
        def decode(x):
            vc=target_cap.copy();vc[other]=blocking[other]+target[other]*x[:len(other)]
            actual_clamp=float(x[-1]*clamp) if rcd else clamp
            circuit.clamp=actual_clamp
            circuit.voltage_tol=1e-8*max(vin,actual_clamp,1.)
            return vc,float(x[len(other)]*nominal_ton),actual_clamp
        def residual(x):
            check_calculation_cancelled()
            vc,ton,actual_clamp=decode(x)
            _,segments,period,_=_cycle(circuit,ton,vc,nominal_period,ring,valley)
            integrals=_segment_integrals(segments,count+1,squares=False)
            charge=integrals[0][1:]
            result=(charge/period-(vc-blocking)/load_r)/load_scale
            if rcd:
                balance=actual_clamp*integrals[-1]/period-actual_clamp**2/rcd[0]
                result=np.r_[result,balance/clamp_power_scale]
            return result
        def solve(seed):
            return least_squares(residual,seed,bounds=(lower,upper),max_nfev=140,
                xtol=2e-10,ftol=2e-10,gtol=2e-10,diff_step=2e-5)
        solved=solve(x0)
        if other and (not solved.success or np.max(np.abs(solved.fun))>2e-5):
            for factor in (.94,.85,1.03):
                seed=x0.copy();seed[:len(other)]=factor
                trial=solve(seed)
                if np.max(np.abs(trial.fun))<np.max(np.abs(solved.fun)): solved=trial
                if solved.success and np.max(np.abs(solved.fun))<=2e-5: break
        best_error=min(best_error,float(np.max(np.abs(solved.fun))))
        if not solved.success or np.max(np.abs(solved.fun))>2e-5:
            raise CoupledConvergenceError(f'QR 矩阵周期电荷平衡未收敛（最大归一化残差 {best_error:.3g}）')
        vc,ton,actual_clamp=decode(solved.x)
        end,segments,period,tdemag=_cycle(circuit,ton,vc,nominal_period,ring,valley)
        cs=_filtered_cs(max(ton-delay,0.),ton,period,vin,matrix[0][0],dcr[0]+ron+rs,rs,tau)
        if cs>csmax*(1+2e-5):
            raise CoupledConvergenceError(f'QR 负载所需 CS 指令 {cs:.6g} V 超过逐周期钳位 {csmax:.6g} V')
        blank=max(toffmin,tofflight+(toffmin-tofflight)/.7*(3*cs/cs0))
        earliest=max(1,1+int(math.ceil(max(0.,blank-tdemag-ring)/(2*ring)-1e-10)))
        if earliest!=valley:
            valley=earliest;x0=solved.x.copy();continue
        if tdemag+(2*valley-1)*ring < blank-1e-12 or (valley>1 and tdemag+(2*valley-3)*ring >= blank+1e-12):
            raise CoupledConvergenceError('QR 谷底与关断消隐约束不一致')
        circuit.period=period
        point=dict(start=np.zeros(count),end=end,voltage=vc,duty=ton/period,
            error=residual(solved.x),iterations=int(solved.nfev),
            integrals=_segment_integrals(segments,count+1),
            solution=_sample_solution(circuit,segments,vc,ton/period),
            clamp_duty=float(sum(s.dt for s in segments if not s.on and 0 in s.active)/period),
            period=period,ton=ton,tdemag=tdemag,ring_wait=(2*valley-1)*ring,
            valley_index=valley,blanking=blank,raw_cs_command=cs,
            chip_comp_estimate=2.5+3*cs/cs0,clamp_voltage=actual_clamp)
        if rcd:
            charge=point['integrals'][-1]
            if charge<=0:raise CoupledConvergenceError('固定 QR RCD 无正的钳位充电，不能维持正的稳态钳位电压')
            point.update(rcd_power_balance_W=actual_clamp*charge/period-actual_clamp**2/rcd[0],
                rcd_ripple_upper_V=charge/rcd[1])
        check_calculation_cancelled()
        return point
    raise CoupledConvergenceError('QR 谷底消隐分支无单周期自洽解；可能跳谷/多周期，需实际电路仿真，不发布角点电压')


def solve_coupled_qr(p,nominal_op):
    """Return independently charge-balanced voltages with the current matrix."""
    if p.get('topology')!='QR-FLYBACK' or p.get('feedback_mode','SSR')!='SSR':
        raise ValueError('QR 耦合周期模型需要 QR-FLYBACK + SSR')
    from isolated_outputs import output_specs,RAIL_KEYS
    from voltage_nodes import input_drop,output_drop
    from spice_export import normalize_settings
    rails=output_specs(p)
    if not rails:
        rails=[dict({key:p.get(key) for key in RAIL_KEYS},name='OUT1',id=1)]
    model=resolve_winding_model(p,rails,nominal_op=nominal_op)
    if model['ideal']:
        op=copy.deepcopy(nominal_op)
        op['coupled_model']=dict(enabled=True,ideal_fallback=True,converged=False,
            model='qr-ideal-ratio-fallback',assumptions=['全部 kij=1 仅保留名义匝比，不能独立计算交叉调整率'])
        op['qr_coupled_model']=copy.deepcopy(op['coupled_model'])
        return op
    if any(r['P_out']<=0 for r in rails):
        raise ValueError('QR 耦合恒阻负载需要每路 P_out>0；真空载请指定实际预负载/泄放')
    reached={0}
    for _ in range(len(model['K'])):
        reached|={j for i in tuple(reached) for j in range(len(model['K'])) if model['K'][i,j]>0}
    if len(reached)!=len(model['K']): raise ValueError('存在与原边完全解耦的输出绕组')
    main=int(p.get('feedback_output',1))-1
    target=np.array([r['V_out'] for r in rails],float)
    blocking=np.array([output_drop(r) for r in rails],float)
    vf=np.array([r['Vf_diode'] for r in rails],float)
    rated=np.array([r['P_out'] for r in rails],float)
    vin=float(p['V_in'])-input_drop(p)
    if vin<=0: raise ValueError('输入电压不足以覆盖输入防反压降')
    kc=float(p.get('Kc',1.5));clamp=kc*model['ratios'][main+1]*(target[main]+blocking[main]+vf[main])
    if kc<=1 or clamp<=float(np.max(model['ratios'][1:]*(target+blocking+vf)))*1.001:
        raise ValueError('QR 耦合模型需要 Kc>1 且钳位高于各路目标反射电压')
    settings=normalize_settings(p.get('spice_config'))
    rcd=_rcd_hardware(p)
    coss=settings['qr_cds_pf']*1e-12 if settings['qr_cds_pf']>0 else float(p['Coss'])
    from parasitics import resolved
    effective_c=coss+resolved(p,len(rails))['cw_primary']
    if effective_c<=0: raise ValueError('QR 谷底时序需要正的有效漏极谐振电容')
    ring=math.pi*math.sqrt(float(model['L'][0,0])*effective_c)
    timing=(settings['qr_off_min_us']*1e-6,settings['qr_off_light_us']*1e-6,
        settings['qr_cs_clamp_v'],settings['qr_cs_clamp_v']*(1-settings['qr_vff_v']/3),
        settings['cs_filter_ns']*1e-9,settings['delay_ns']*1e-9,
        max(settings['min_on_ns'],settings['blanking_ns'])*1e-9,settings['qr_max_on_us']*1e-6)
    from calculation_scheduler import check_calculation_cancelled
    check_calculation_cancelled()
    point=copy.deepcopy(_solution(tuple(map(tuple,model['L'])),tuple(model['R']),vin,tuple(vf),
        float(p['Rds_on']),float(p['Rs']),clamp,tuple(target),tuple(blocking),tuple(rated),main,
        float(nominal_op['Ts']),float(nominal_op['T_on']),ring,timing,
        (rcd['R_ohm'],rcd['C_F']) if rcd else ()))
    check_calculation_cancelled()
    metadata=dict(enabled=True,ideal_fallback=False,model='qr-coupled-RL-stiff-capacitor-fixed-R',
        labels=list(model['labels']),ratios=model['ratios'].tolist(),ratio_sources=list(model['ratio_sources']),
        L=model['L'].tolist(),K=model['K'].tolist(),R=model['R'].tolist(),
        L_leak=float(model['L_leak']),L_leak_primary=float(model['L_leak']),
        dcr_source=model['dcr_source'],transformer_hardware=copy.deepcopy(model['transformer_hardware']),
        auto_wire_sizing='nominal-predesign-frozen',independent_cross_regulation=True,
        independent_winding_commutation=True,timing_policy='lossless-constant-C-blanked-valleys',
        effective_cds_F=effective_c,first_valley_delay_s=ring,
        valley_index=point['valley_index'],off_blanking_s=point['blanking'],
        raw_cs_command_V=point['raw_cs_command'],chip_comp_estimate_V=point['chip_comp_estimate'],
        T_on=point['ton'],T_demag=point['tdemag'],T_ring=point['ring_wait'],
        frequency_hz=1/point['period'],design_frequency_limit_hz=float(p['f_sw']),
        design_frequency_limit_exceeded=1/point['period']>float(p['f_sw'])*(1+1e-9),
        assumptions=[
            'QR 单主反馈固定防反管前电容电压；各路恒阻负载由需求端口电压平方/功耗换算，输出在防反管后统计',
            '逐段完整互感矩阵 RL、二极管互补约束与恒压钳位；各路电荷平衡独立求解，不按功率分配电流',
            '每周期从全部绕组电流为零开始，最后一支路电流归零为退磁终点；忽略谷底谐振的负向磁化电流',
            '退磁后谷底为(2n-1)π√(Lp*Cds)，恒C无损时序近似；不模拟Coss谐振电流、RC阻尼、ZCD阈值/RC延时、启动定时器和多周期稳定性',
            '沿用通用L6565行为模型COMP相关关断消隐，CS指令由周期一阶滤波和导通延时近似反推，选择首个未被消隐谷底',
            '设计f_sw只作频率上限校核，不加入SPICE不存在的限频时钟，不以设计频率强改周期',
            '预设效率只用于预设计初值；实际RL损耗、DCR、整流和防反压降由同一周期汇总；输出电容按恒直流电压，纹波另重建',
            '不含磁芯非线性、器件温度、反向恢复、真实硅片或光耦/TL431动态；无单周期自洽解/真空载不发布包络'])
    if rcd:
        metadata.update(rcd_hardware=copy.deepcopy(rcd),rcd_policy='fixed-RC-mean-clamp-power-balance',
            rcd_power_balance_W=point['rcd_power_balance_W'],
            rcd_ripple_upper_V=point['rcd_ripple_upper_V'],
            rcd_ripple_upper_relative=point['rcd_ripple_upper_V']/point['clamp_voltage'])
        metadata['assumptions'].append(
            '固定同一RCD电阻/电容，以Vclamp·Qclamp/T=Vclamp²/R联立平均钳位电压；'
            'Qclamp/C为忽略周期内泄放的纹波上界估计。仍是平均恒压换流，未求解RCD瞬态，纹波较大时精度下降')
    else:
        metadata['rcd_policy']='nominal-fixed-Kc-clamp'
        metadata['assumptions'].append('未提供冻结RCD硬件的单点名义解采用Kc恒压钳位，不作为同一RCD跨负载特性')
    op=finish_operating_point(p,nominal_op,model,rails,metadata,point,point['period'],
        target,blocking,rated,vin,vf,np.zeros(len(rails)),point['clamp_voltage'],main)
    op.update(T_on=point['ton'],T_demag=point['tdemag'],T_ring=point['ring_wait'],
        Dp=point['tdemag']/point['period'],mode='BCM',f_max=float(p['f_sw']),
        I_pk=op['I_sw_pk'],regulation_region='QR-coupled-cycle')
    op['qr_coupled_model']=op['coupled_model']
    op['qr_multi_model']=dict(kind='qr-coupled-cycle',scope='independent-charge-balanced',
        independent_cross_regulation=True,independent_winding_commutation=True,
        assumptions='；'.join(metadata['assumptions']))
    op['warnings']=[w for w in op.get('warnings',[]) if not ('固定频率' in w or '标称 PWM' in w)]
    op['warnings'].append('QR矩阵周期：恒直流电容、无损恒C谷底时序，真实ZCD/衰减/跳谷动态需实际电路复核。')
    if rcd:
        op['warnings'].append(f'固定RCD平均钳位：Vclamp={point["clamp_voltage"]:.6g} V；'
            f'Q/C纹波上界约{metadata["rcd_ripple_upper_relative"]*100:.3g}%，未模拟电容周期内RC瞬态。')
    return op
