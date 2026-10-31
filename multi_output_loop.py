"""Low-frequency multi-output loop models, never independent feedback loops.

The event-resolved RL period map supplies winding/current-control derivatives.
Its averaged injection currents are interconnected with independent series-RC
capacitor branches. This retains parallel-bank dynamics and ESR feedthrough
at the actual feedback node, without rerunning a switching steady-state solve.
"""
from types import SimpleNamespace

import numpy as np

from calculation_scheduler import check_calculation_cancelled


def _capacitors(rails):
    from output_capacitors import branches
    capacitance, esr_zero = [], []
    for rail in rails:
        caps = branches(rail)
        total = sum(c for c, _ in caps)
        if not np.isfinite(total) or total <= 0:
            raise ValueError('多路环路要求每路有正的输出电容')
        # First-order low-frequency series resistance of parallel RC banks.
        resistance = sum(r*c*c for c, r in caps) / total**2
        capacitance.append(total)
        esr_zero.append(1/(2*np.pi*total*resistance) if resistance > 0 else np.inf)
    return np.asarray(capacitance), np.asarray(esr_zero)


class CoupledPeriodMap:
    """Normalized current/voltage states for finite-difference verification."""
    def __init__(self, p, op):
        from coupled_flyback import _Circuit
        meta, solution = op['coupled_model'], op['coupled_solution']
        self.rails = op['outputs']
        self.count = len(self.rails)
        self.period = 1/float(op['f_sw'])
        self.duty = float(op['D'])
        self.voltage = np.asarray(meta.get('capacitor_voltages',meta['output_voltages']), float)
        self.blocking = np.asarray(meta.get('output_blocking_drops',np.zeros(self.count)),float)
        self.load = np.asarray(meta['load_resistances'], float)
        self.capacitance, self.esr_zero = _capacitors(self.rails)
        self.scale = np.r_[np.maximum(np.max(solution['i_winding'][1:], axis=1), .01),
                           np.maximum(self.voltage, .01)]
        initial = np.maximum(np.asarray(solution['i_winding'][1:, 0], float), 0.)
        self.state = np.r_[initial, self.voltage] / self.scale
        self.sense = float(p['Rs'])*float(p.get('A_sense', 1))
        self.ramp = float(p.get('ma_slope', 0))
        self.circuit = _Circuit(meta['L'], meta['R'], float(meta.get('input_bus_voltage',p['V_in'])),
            np.array([r['Vf_diode'] for r in self.rails]),
            np.zeros(len(self.rails)),
            float(p.get('Rds_on', 0)), float(p['Rs']),
            float(meta['clamp_voltage']), self.period)

    def evaluate(self, state, duty):
        from coupled_flyback import _segment_integrals
        check_calculation_cancelled()
        count = self.count
        physical = np.asarray(state)*self.scale
        start, vo = physical[:count], physical[count:]
        if np.any(start < 0) or np.any(vo <= 0) or not 0 < duty < 1:
            raise ValueError('多路环路扰动超出合法周期状态')
        end, segments = self.circuit.cycle(start, vo, duty)
        if end[0] > max(1e-6, float(max(self.scale[:count]))*1e-5):
            raise ValueError('微扰周期的原边未完全复位，不能沿用周期起点原边电流为零的模型')
        charge = _segment_integrals(segments, count+1, squares=False)[0][1:]
        next_voltage = vo + (charge-self.period*(vo-self.blocking)/self.load)/self.capacitance
        on = [s for s in segments if s.on and 0 in s.active]
        if not on:
            raise ValueError('没有可线性化的 MOS 导通区间')
        last = on[-1]
        current, _ = last.flow.values(last.initial, last.voltage, last.dt)
        peak = float(current[list(last.active).index(0)])
        threshold = self.sense*(peak+self.ramp*duty*self.period)
        return np.r_[end[1:], next_voltage]/self.scale, threshold, float(end[0])

    def linearize(self, step):
        x, d = self.state, self.duty
        baseline, peak0, _ = self.evaluate(x, d)
        a, peak_x = np.empty((len(x), len(x))), np.empty(len(x))
        for j in range(len(x)):
            change = np.zeros_like(x); change[j] = step
            high, peak_hi, _ = self.evaluate(x+change, d)
            if j < self.count and x[j] < step:
                # Zero-current diode states live on a nonnegative cone.
                low, peak_lo, span = baseline, peak0, step
            else:
                low, peak_lo, _ = self.evaluate(x-change, d)
                span = 2*step
            a[:, j], peak_x[j] = (high-low)/span, (peak_hi-peak_lo)/span
        h = min(step, d/4, (1-d)/4)
        high, peak_hi, _ = self.evaluate(x, d+h)
        low, peak_lo, _ = self.evaluate(x, d-h)
        return a, (high-low)/(2*h), peak_x, (peak_hi-peak_lo)/(2*h)


def _winding_kernel(period_map,derivatives):
    """Continuous low-frequency equivalent of winding states and charge.

    Remove the old lumped capacitor update from the period-map Jacobian to
    recover rectifier average-current derivatives. Only the winding-state
    block is converted with Tustin; output RC dynamics are physical continuous
    states. Current and threshold outputs use the same Tustin feedthrough.
    """
    a,bd,hx,hd=derivatives;n=period_map.count
    voltage_scale=period_map.scale[n:]
    charge_scale=period_map.capacitance*voltage_scale/period_map.period
    ji=charge_scale[:,None]*a[n:,:n]
    jv=charge_scale[:,None]*(a[n:,n:]-np.eye(n))/voltage_scale[None,:]+np.diag(1/period_map.load)
    jd=charge_scale*bd[n:]
    ai=a[:n,:n];bi=np.column_stack((a[:n,n:]/voltage_scale[None,:],bd[:n]))
    if np.linalg.cond(np.eye(n)+ai)>1e10:
        raise ValueError('绕组周期映射接近 −1 极点，不能作低频连续等效')
    inv=np.linalg.solve(np.eye(n)+ai,np.eye(n))
    ac=2/period_map.period*(ai-np.eye(n))@inv
    bc=2/period_map.period*inv@bi
    jc=2*ji@inv;jfeed=np.column_stack((jv,jd))-ji@inv@bi
    hc=2*hx[:n]@inv
    hfeed=np.r_[hx[n:]/voltage_scale,hd]-hx[:n]@inv@bi
    return ac,bc,jc,jfeed,hc,hfeed


def _connect_output_filters(period_map,derivatives,peak_mode,vm):
    """Joint winding/RC/peak-control equations, including load feedthrough."""
    import control as ct
    from output_capacitors import build_output_filters
    n=period_map.count
    filters=build_output_filters(period_map.rails,period_map.load,period_map.voltage)
    m=len(filters.A)
    ax,bx,jx,jfeed,hx,hfeed=_winding_kernel(period_map,derivatives)
    av,ad=bx[:,:n],bx[:,n]
    jv,jd=jfeed[:,:n],jfeed[:,n]
    # v = Cf*u + Df*(j-load), j = Jx*x + Jv*v + Jd*d.
    # Peak control adds Hx*x+Hv*v+Hd*d = command. In VM, Vm*d=command.
    algebraic=np.zeros((n+1,n+1))
    algebraic[:n,:n]=np.eye(n)-filters.D@jv
    algebraic[:n,n]=-filters.D@jd
    algebraic[n,:n]=hfeed[:n] if peak_mode else 0.
    algebraic[n,n]=hfeed[n] if peak_mode else vm
    if not np.isfinite(algebraic[n,n]) or algebraic[n,n]<=1e-8:
        raise ValueError('电流比较器/调制器的占空比增益非正，不能建立环路')
    # Row scaling separates volts and duty and avoids an arbitrary ESR cap.
    row_scale=np.maximum(np.max(abs(algebraic),axis=1),1e-20)
    scaled=algebraic/row_scale[:,None]
    if np.linalg.cond(scaled)>1e10:
        raise ValueError('输出电容 ESR 与峰值内环的代数耦合接近奇异，无法可靠线性化')
    state_rhs=np.zeros((n+1,n+m))
    state_rhs[:n,:n]=filters.D@jx;state_rhs[:n,n:]=filters.C
    if peak_mode:state_rhs[n,:n]=-hx
    input_rhs=np.zeros((n+1,n+1));input_rhs[n,0]=1.
    input_rhs[:n,1:]=-filters.D
    solved=np.linalg.solve(scaled,np.column_stack((state_rhs,input_rhs))/row_scale[:,None])
    vstate,dstate=solved[:n,:n+m],solved[n,:n+m]
    vinput,dinput=solved[:n,n+m:],solved[n,n+m:]
    acoil=np.column_stack((ax,np.zeros((n,m))))+av@vstate+np.outer(ad,dstate)
    acap=np.column_stack((filters.B@jx,filters.A))+filters.B@jv@vstate+np.outer(filters.B@jd,dstate)
    bcoil=av@vinput+np.outer(ad,dinput)
    bcap=filters.B@jv@vinput+np.outer(filters.B@jd,dinput)
    bcap[:,1:]-=filters.B
    full=ct.ss(np.vstack((acoil,acap)),np.vstack((bcoil,bcap)),vstate,vinput)
    return full,filters


def build_coupled_loop(p, op):
    """Return the single feedback plant and full control/load response bank."""
    import control as ct
    from plants import make_compensator
    if p['topology'] != 'FLYBACK' or p.get('feedback_mode', 'SSR') != 'SSR':
        raise ValueError('耦合小信号目前仅支持固定频率反激 SSR')
    if not op.get('coupled_solution') or not op['coupled_model'].get('converged'):
        raise ValueError('没有已收敛的耦合周期解，不能生成对应环路')
    period_map = CoupledPeriodMap(p, op)
    n = period_map.count
    if np.any((period_map.state[:n] > 1e-9) & (period_map.state[:n] < 2e-4)):
        raise ValueError('副边周期初值太接近 CCM/DCM 边界，不输出唯一的小信号模型')
    # Large ripple invalidates the held-voltage assumption, not just accuracy.
    time = np.asarray(op['coupled_solution']['t'])
    for j, child in enumerate(op['output_ops']):
        current = op['coupled_solution']['i_winding'][j+1]-child['I_out']
        charge = np.r_[0., np.cumsum((current[:-1]+current[1:])*np.diff(time)/2)]
        if np.ptp(charge)/period_map.capacitance[j]/child['V_out'] > .1:
            raise ValueError(f'OUT{j+1} 电容充放电纹波超过 10%，不输出刚性电容近似 Bode')
    a, bd, hx, hd = period_map.linearize(2e-5)
    fine = period_map.linearize(1e-5)
    error = max(float(np.linalg.norm(v-w)/max(np.linalg.norm(w), 1e-8))
                for v, w in zip((a, bd, hx, hd), fine))
    if not np.isfinite(error) or error > .03:
        raise ValueError(f'周期小信号差分不一致（{error:.1%}），可能位于导通模式边界；请换角点或用开关仿真')
    a, bd, hx, hd = fine
    peak_mode = p['control_mode'] == 'Peak Current Mode'
    if peak_mode:
        _, threshold, _ = period_map.evaluate(period_map.state, period_map.duty)
        solution = op['coupled_solution']
        on = solution['t'] < period_map.duty*period_map.period
        earlier = period_map.sense*(solution['i_sw'][on]+period_map.ramp*solution['t'][on])
        if len(earlier) and np.max(earlier) > threshold+max(1e-7, abs(threshold)*1e-5):
            raise ValueError('峰值采样在关断前已超过末端阈值，不能假设首次比较器交点位于当前边沿')
        if not np.isfinite(hd) or hd <= 1e-8:
            raise ValueError('峰值电流比较器的占空比斜率非正，不能建立稳定的内环')
    full,filters=_connect_output_filters(period_map,fine,peak_mode,float(p['Vm']))
    identity=np.eye(full.nstates)
    discrete_a=np.linalg.solve(identity-full.A*period_map.period/2,
                               identity+full.A*period_map.period/2)
    # Fast physical RC poles map close to -1 under Tustin. They must not be
    # mislabeled as a sampled PWM period-doubling mode.
    kernel_a=a-np.outer(bd,hx)/hd if peak_mode else a
    discrete_poles=np.linalg.eigvals(kernel_a)
    main = int(op['feedback_output'])-1
    gvc = full[main, 0]
    gc = make_compensator(p).get_transfer_function()
    rhp = [abs(z)/(2*np.pi) for z in ct.zeros(gvc) if np.isfinite(z) and np.real(z) > 1e-5]
    rhp_limit = float(min(rhp)) if rhp else None
    metadata = dict(kind='coupled-period-map',revision='independent-parallel-rc-v1',experimental=True,
        feedback_output=main+1, outputs=[dict(id=r['id'], name=r.get('name', f'OUT{r["id"]}'),
            voltage=float(v), current=float(v/load)) for r, v, load in
            zip(period_map.rails, period_map.voltage-period_map.blocking, period_map.load)],
        # The provisional fs/20 and ESR/5 gates are disabled. Keep explicit
        # nulls for API consumers; no model-specific fc clamp is applied.
        frequency_limit=None, recommended_fc_max=None, bandwidth_limit_enabled=False,
        rhp_zero_estimate=rhp_limit,
        derivative_error=error, inner_spectral_radius=float(np.max(np.abs(discrete_poles))),
        inner_spectral_radius_scope='恒电容端绕组周期核的采样检查；不是完整 ESR 开关周期验证',
        current_mode=peak_mode,capacitance=period_map.capacitance.tolist(),
        esr_included=True,capacitor_banks=filters.banks,
        capacitor_states=len(filters.A),state_count=full.nstates,
        state_labels=[f'OUT{i+1}.winding' for i in range(n)]+filters.state_labels,
        assumptions='绕组周期平均电流与峰值采样线性化，联立各路每颗 C+ESR 支路；保留并联电容独立状态和端口直通项。'
        '仅主反馈闭环，取样为防反管前电容端；恒阻负载，扰动为额外负载电流。'
        '低频实验模型：直流/开关电流仍来自恒电容端周期解，未将 ESR 纹波反算至该周期电流；'
        '不含 ESL、光耦/TL431、驱动延迟、钳位电容动态、Coss/Cj 或大信号模式切换。'
        '临时低频带宽限制已停用；高频结果属于近似外推，精度未验证。'
        '增益裕度只在扫描范围内检查；PM 不能代替闭环极点和样机 FRA。')
    gvc._multi_output_system = full
    gvc._loop_metadata = metadata
    return (gvc, gc, gvc*gc), SimpleNamespace(model_note=metadata['assumptions'],
        loop_metadata=metadata,period_map=period_map,discrete_A=discrete_a,full_system=full,
        output_filters=filters)


def attach_nominal_context(gvc, source, solved):
    """Explicitly label the existing ideal-ratio approximation, not a matrix model."""
    if not solved.get('outputs'):
        return
    main = int(solved['feedback_output'])-1
    rails = solved['outputs']
    gvc._loop_metadata = dict(kind='ideal-ratio-aggregate', experimental=False,
        feedback_output=main+1,
        outputs=[dict(id=r['id'], name=r.get('name', f'OUT{r["id"]}'), voltage=float(r['V_out'])) for r in rails],
        assumptions='仅主反馈闭环；理想匝比、总负载与电容能量折算。各路参考响应仅按刚性匝比推导，'
        '不是各路独立环路；不提供独立负载动态或交叉调整率。正激独立 LC 动态需开关模型复核。')
