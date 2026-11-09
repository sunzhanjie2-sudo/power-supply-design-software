"""Charge-balanced, fixed-frequency diode flyback with a full winding matrix.

This is a *DC-capacitor-voltage* periodic circuit calculation, not a SPICE
replacement.  Winding currents and diode/clamp commutation are solved from
``v = L di/dt + R i``; they are never allocated in proportion to output power.
Loads are resistors Vtarget**2/Prated.  The main feedback fixes its DC voltage;
the other output voltages and the PWM duty are solved by periodic current and
capacitor charge balance.  Output capacitor ripple is reconstructed elsewhere.

The clamp is an ideal, constant-voltage dissipative clamp, above the input
rail.  Coss/Cj, reverse recovery, layout ringing, controller dynamics, and
frequency modulation are intentionally not included.  A singular all-ones
matrix is an explicit ideal-transformer fallback, not numerically regularized.
All quantities are SI.  Secondary dots are at the output return terminals.
"""
from __future__ import annotations

import copy
from dataclasses import dataclass
from functools import lru_cache
from itertools import combinations

import numpy as np
from scipy.optimize import brentq, least_squares

from winding_coupling import resolve_winding_model


_QUADRATURE=np.polynomial.legendre.leggauss(20)


class CoupledConvergenceError(ValueError):
    """A physically valid matrix did not yield a verified periodic solution."""


@dataclass
class _Segment:
    t: float
    dt: float
    active: tuple
    initial: np.ndarray
    voltage: np.ndarray
    flow: "_Flow"
    on: bool


class _Flow:
    """Exact RL propagation using a symmetric (and well-conditioned) basis."""
    def __init__(self, inductance, resistance):
        c = np.linalg.cholesky(inductance)
        cinv = np.linalg.inv(c)
        self.back = np.linalg.solve(c.T, np.eye(len(c)))
        self.forward = c.T
        self.cinv = cinv
        eigen, basis = np.linalg.eigh(cinv @ np.diag(resistance) @ cinv.T)
        self.eigen = np.maximum(eigen, 0.)
        self.basis = basis

    def values(self, initial, voltage, dt):
        """Return current and exact current integral over ``dt``."""
        q = self.basis.T @ (self.forward @ initial)
        g = self.basis.T @ (self.cinv @ voltage)
        eigen = self.eigen
        z = eigen * dt
        e = np.exp(-z)
        # Stable phi functions, including zero resistance and very small dt.
        f = np.empty_like(eigen)
        h = np.empty_like(eigen)
        small = np.abs(z) < 1e-4
        f[small] = dt * (1-z[small]/2+z[small]**2/6-z[small]**3/24)
        h[small] = dt**2 * (.5-z[small]/6+z[small]**2/24-z[small]**3/120)
        f[~small] = -np.expm1(-z[~small]) / eigen[~small]
        h[~small] = (dt-f[~small]) / eigen[~small]
        current = self.back @ (self.basis @ (q*e+g*f))
        integral = self.back @ (self.basis @ (q*f+g*h))
        return current, integral

    def prepare_current(self, initial, voltage):
        """Reuse an interval's modal coordinates during diode root searches.

        Only time changes within an RL interval. Event checks do not need the
        current integral; avoid recomputing both transforms and that integral
        for every trial time. The event grid and root tolerances are unchanged.
        """
        q = self.basis.T @ (self.forward @ initial)
        g = self.basis.T @ (self.cinv @ voltage)
        eigen = self.eigen
        nonzero = eigen > 0

        def current(dt):
            # Works for a scalar time or a 1-D array of sample times.
            times = np.asarray(dt)
            batch = times.ndim != 0
            rates = eigen[:, None] if batch else eigen
            z = rates * times
            small = np.abs(z) < 1e-4
            if batch:
                f = np.broadcast_to(times, z.shape).copy()
                np.divide(-np.expm1(-z), rates, out=f, where=nonzero[:, None])
                # Preserve the same small-step polynomial as values(); tiny
                # rounding differences otherwise perturb diode event roots.
                series = times*(1-z/2+z**2/6-z**3/24)
                f[small] = series[small]
            else:
                f = np.empty_like(eigen)
                f[small] = dt*(1-z[small]/2+z[small]**2/6-z[small]**3/24)
                f[~small] = -np.expm1(-z[~small])/eigen[~small]
            modes = q[:, None] if batch else q
            drive = g[:, None] if batch else g
            return self.back @ (self.basis @ (modes*np.exp(-z)+drive*f))

        return current


class _Circuit:
    def __init__(self, matrix, dcr, vin, vf, rd, ron, rs, clamp, period):
        self.L = np.asarray(matrix, dtype=float)
        self.dcr = np.asarray(dcr, dtype=float)
        self.vin, self.vf, self.rd = float(vin), np.asarray(vf), np.asarray(rd)
        self.ron, self.rs, self.clamp, self.period = ron, rs, clamp, period
        self.count = len(self.dcr)
        self.cache = {}
        self.inverse_cache = {}
        self.current_tol = 1e-9
        self.voltage_tol = 1e-8 * max(vin, clamp, 1.)

    def _parameters(self, active, on, vo):
        active = tuple(sorted(active))
        resistance = np.r_[self.dcr[0]+((self.ron+self.rs) if on else 0.),
                           self.dcr[1:]+self.rd]
        applied = np.r_[self.vin if on else -self.clamp, -vo-self.vf]
        key = (active, on)
        if key not in self.cache:
            self.cache[key] = _Flow(self.L[np.ix_(active, active)], resistance[list(active)])
        return active, resistance, applied, self.cache[key]

    def _slope(self, active, current, resistance, applied):
        result = np.zeros(self.count)
        if active:
            a = list(active)
            key=tuple(active)
            if key not in self.inverse_cache:
                self.inverse_cache[key]=np.linalg.solve(self.L[np.ix_(a,a)],np.eye(len(a)))
            result[a] = self.inverse_cache[key] @ (applied[a]-resistance[a]*current[a])
        return result

    def _settle(self, current, seed, on, vo):
        """Resolve the diode linear complementarity condition at one instant."""
        positive = set(np.flatnonzero(current > self.current_tol))
        if on:
            positive.add(0)  # commanded ideal MOS channel; its Rds is included
        active = set(seed) | positive
        applied = np.r_[self.vin if on else -self.clamp, -vo-self.vf]
        resistance = np.r_[self.dcr[0]+((self.ron+self.rs) if on else 0.),
                           self.dcr[1:]+self.rd]
        seen = set()
        for _ in range(4*self.count+4):
            signature = tuple(sorted(active))
            if signature in seen:
                break
            seen.add(signature)
            slope = self._slope(signature, current, resistance, applied)
            bad_active = [j for j in active-positive if slope[j] < -1e-7]
            if bad_active:
                active.remove(min(bad_active, key=lambda j:slope[j]))
                continue
            induced = self.L @ slope
            bad_open = [j for j in range(self.count) if j not in active and
                        induced[j] < applied[j]-self.voltage_tol]
            if bad_open:
                active.add(min(bad_open, key=lambda j:induced[j]-applied[j]))
                continue
            return tuple(sorted(active))
        # Small (at most 7-winding) monotone LCP: exhaustive fallback is safe,
        # and avoids silently accepting a cycling, nonphysical diode state.
        optional = [j for j in range(self.count) if j not in positive]
        for size in range(len(optional)+1):
            for extra in combinations(optional, size):
                candidate = tuple(sorted(positive | set(extra)))
                slope = self._slope(candidate,current,resistance,applied)
                induced = self.L @ slope
                if (all(slope[j] >= -1e-7 for j in extra) and
                    all(induced[j] >= applied[j]-self.voltage_tol for j in optional if j not in candidate)):
                    return candidate
        raise CoupledConvergenceError('耦合绕组二极管状态无解；请检查极性、钳位电压和参数')

    def _phase(self, initial, on, duration, vo, offset):
        current = initial.copy()
        seed = set(np.flatnonzero(current > self.current_tol))
        if on:
            seed.add(0)
        elapsed, segments = 0., []
        minimum_dt = self.period*1e-12
        for _ in range(80):
            left = duration-elapsed
            if left <= minimum_dt:
                return current, segments
            active = self._settle(current,seed,on,vo)
            if not active:
                # Every diode open, zero winding currents, no stored energy.
                return np.zeros(self.count), segments+[
                    _Segment(offset+elapsed,left,(),np.empty(0),np.empty(0),None,on)]
            active,resistance,applied,flow = self._parameters(active,on,vo)
            a = list(active)
            ia, ua = current[a].copy(), applied[a]
            inactive = [j for j in range(self.count) if j not in active]
            propagate = flow.prepare_current(ia, ua)

            def constraints(dt):
                value = propagate(dt)
                full = np.zeros(self.count); full[a] = value
                slope = self._slope(active,full,resistance,applied)
                slack = self.L @ slope-applied
                return value,slack

            # A passive RL interval has smooth exponential state variables.
            # Scanning all constraints also catches activation of an initially
            # blocked output during primary leakage commutation.
            previous_t = 0.
            previous_i,previous_slack = constraints(0.)
            event = None
            for sample_t in np.linspace(0.,left,13)[1:]:
                value,slack = constraints(sample_t)
                candidates=[]
                for local,j in enumerate(active):
                    if on and j == 0:
                        continue
                    if value[local] < -self.current_tol:
                        fun=lambda dt,k=local: constraints(dt)[0][k]
                        if previous_i[local] <= 0:
                            when=previous_t
                        else:
                            when=brentq(fun,previous_t,sample_t,xtol=minimum_dt)
                        candidates.append((when,'open',j))
                for j in inactive:
                    if slack[j] < -self.voltage_tol:
                        # Close at a tiny, explicit forward-bias tolerance.
                        # Rooting exactly at zero can chatter indefinitely:
                        # roundoff gives a just-closed zero-current diode a
                        # negative derivative and the LCP opens it again.
                        fun=lambda dt,k=j: constraints(dt)[1][k]+self.voltage_tol
                        if previous_slack[j] <= -self.voltage_tol:
                            when=previous_t
                        else:
                            when=brentq(fun,previous_t,sample_t,xtol=minimum_dt)
                        candidates.append((when,'close',j))
                if candidates:
                    event=min(candidates,key=lambda item:item[0])
                    break
                previous_t,previous_i,previous_slack=sample_t,value,slack
            dt=left if event is None else event[0]
            if dt > minimum_dt:
                segments.append(_Segment(offset+elapsed,dt,active,ia,ua,flow,on))
                value=propagate(dt)
                current=np.zeros(self.count); current[a]=value
                current[np.abs(current)<self.current_tol]=0.
                if np.min(current) < -1e-6:
                    raise CoupledConvergenceError('耦合绕组出现反向整流电流，二极管事件求解失败')
                current=np.maximum(current,0.)
                elapsed+=dt
            seed=set(active)
            if event is None:
                return current,segments
            _,action,j=event
            if action=='open':
                current[j]=0.; seed.discard(j)
            else:
                seed.add(j)
        raise CoupledConvergenceError('耦合绕组换流事件过密；本理想二极管模型未收敛')

    def cycle(self, secondary_initial, vo, duty):
        initial=np.r_[0.,secondary_initial]
        middle,on_segments=self._phase(initial,True,duty*self.period,vo,0.)
        final,off_segments=self._phase(middle,False,(1-duty)*self.period,vo,duty*self.period)
        return final,on_segments+off_segments


def _segment_integrals(segments,count,*,squares=True):
    integral=np.zeros(count)
    squared=np.zeros(count)
    on_integral=on_squared=clamp_integral=0.
    nodes,weights=_QUADRATURE
    for segment in segments:
        if not segment.active:
            continue
        a=list(segment.active)
        _,charge=segment.flow.values(segment.initial,segment.voltage,segment.dt)
        integral[a]+=charge
        square=np.zeros(len(a))
        if squares:
            values=segment.flow.prepare_current(segment.initial,segment.voltage)(
                (nodes+1)*segment.dt/2)
            square=np.sum(weights*values**2*segment.dt/2,axis=1)
        squared[a]+=square
        if 0 in segment.active:
            local=a.index(0)
            if segment.on:
                on_integral+=charge[local]; on_squared+=square[local]
            else:
                clamp_integral+=charge[local]
    return integral,squared,on_integral,on_squared,clamp_integral


def _sample_solution(circuit,segments,vo,duty,points=2400):
    """Uniform samples plus both sides of every switching/diode event."""
    period=circuit.period
    regular=np.linspace(0.,period,points+1)
    event=np.array([s.t for s in segments]+[s.t+s.dt for s in segments])
    # Extra near-event samples preserve sub-grid commutation peaks while
    # retaining a strictly increasing grid suitable for interpolation.
    epsilon=period*1e-10
    times=np.unique(np.clip(np.r_[regular,event,event-epsilon,event+epsilon],0.,period))
    current=np.zeros((circuit.count,len(times)))
    winding_voltage=np.zeros_like(current)
    clamp=np.zeros(len(times)); switch=np.zeros(len(times))
    boundaries=np.array([s.t+s.dt-epsilon/2 for s in segments[:-1]])
    segment_indices=np.searchsorted(boundaries,times,side='right')
    for segment_index,segment in enumerate(segments):
        if not segment.active:
            continue
        indices=np.flatnonzero(segment_indices==segment_index)
        if not len(indices):
            continue
        a=list(segment.active)
        value=segment.flow.prepare_current(segment.initial,segment.voltage)(
            np.clip(times[indices]-segment.t,0.,segment.dt))
        current[np.ix_(a,indices)]=value
        _,resistance,applied,_=circuit._parameters(segment.active,segment.on,vo)
        # Populate the same active-set inverse used by the event solver.
        circuit._slope(segment.active,current[:,indices[0]],resistance,applied)
        slope=circuit.inverse_cache[segment.active] @ (applied[a,None]-resistance[a,None]*value)
        winding_voltage[:,indices]=circuit.L[:,a]@slope
        if 0 in a:
            if segment.on:
                switch[indices]=value[a.index(0)]
            else:
                clamp[indices]=value[a.index(0)]
    gate=times<duty*period
    # Terminal primary voltage includes copper drop.  The OFF ideal clamp
    # therefore reaches Vin+Vc, whereas the ON MOS drop is Ron*ip.
    primary_terminal=winding_voltage[0]+circuit.dcr[0]*current[0]
    vds=circuit.vin-primary_terminal
    vds[gate]=circuit.ron*switch[gate]
    return dict(t=times,i_winding=current,v_winding=winding_voltage,
                # The clamp returns to Vin: OFF primary current circulates
                # back into that rail and cancels its source-side draw.
                i_sw=switch,i_in=switch.copy(),i_clamp=clamp,v_sw=vds,
                gate_on=gate,i_magnetizing=(circuit.L[0]@current)/circuit.L[0,0],
                lambda_p=circuit.L[0]@current,output_voltages=vo.copy())


@lru_cache(maxsize=6)
def _periodic_solution(matrix,dcr,vin,vf,rd,ron,rs,clamp,period,
                       target,blocking,rated,main,current_scale,initial,
                       nominal_duty,nominal_sw_peak):
    """Small electrical-only cache shared by endpoint/report recalculations.

    Keys contain every RL circuit, load and solver-seed input. Curves, BOM,
    thermal data and compensator edits do not change this physical period.
    Retain at most six compact traces, no circuits, optimizers or GUI objects.
    The caller copies arrays before publishing or adding presentation data.
    """
    from calculation_scheduler import check_calculation_cancelled
    check_calculation_cancelled()
    circuit=_Circuit(matrix,dcr,vin,vf,rd,ron,rs,clamp,period)
    target,blocking,rated,current_scale,initial=map(np.asarray,
        (target,blocking,rated,current_scale,initial))
    count=len(target)
    target_cap=target+blocking
    load_r=target**2/rated
    other=[j for j in range(count) if j!=main]
    x0=np.r_[initial/current_scale,np.ones(count-1),nominal_duty]
    lower=np.r_[np.zeros(count),np.full(count-1,.05),.005]
    upper=np.r_[np.full(count,30.),np.full(count-1,5.),.9]
    x0=np.maximum(lower+1e-8,np.minimum(upper-1e-8,x0))
    load_scale=np.maximum(rated/target,.001)

    def decode(x):
        voltage=target_cap.copy()
        voltage[other]=blocking[other]+target[other]*x[count:2*count-1]
        return x[:count]*current_scale,voltage,float(x[-1])

    def residual(x):
        check_calculation_cancelled()
        start,voltage,duty=decode(x)
        end,segments=circuit.cycle(start,voltage,duty)
        average=_segment_integrals(segments,count+1,squares=False)[0]/period
        return np.r_[(end[1:]-start)/current_scale,
                     (average[1:]-(voltage-blocking)/load_r)/load_scale,
                     end[0]/max(nominal_sw_peak,.01)]

    def solve_from(seed):
        return least_squares(residual,seed,bounds=(lower,upper),
                             xtol=2e-10,ftol=2e-10,gtol=2e-10,
                             max_nfev=180,diff_step=2e-5)
    solved=solve_from(x0)
    # An auxiliary diode that never turns on has no local charge derivative.
    # Start it on either side of conduction before declaring the case unsolved.
    if other and (not solved.success or np.max(np.abs(solved.fun))>2e-5):
        for voltage_scale in (.95,.85,1.03):
            seed=x0.copy()
            seed[count:2*count-1]=voltage_scale
            trial=solve_from(seed)
            if np.max(np.abs(trial.fun))<np.max(np.abs(solved.fun)):
                solved=trial
            if solved.success and np.max(np.abs(solved.fun))<=2e-5:
                break
    start,vc,duty=decode(solved.x)
    error=residual(solved.x)
    if not solved.success or np.max(np.abs(error))>2e-5:
        raise CoupledConvergenceError(f'耦合矩阵周期/电荷平衡未收敛（最大归一化残差 {np.max(np.abs(error)):.3g}）；请复核匝比、负载、钳位及 DCR')
    end,segments=circuit.cycle(start,vc,duty)
    integrals=_segment_integrals(segments,count+1)
    solution=_sample_solution(circuit,segments,vc,duty)
    check_calculation_cancelled()
    return dict(start=start,end=end,voltage=vc,duty=duty,error=error,
                iterations=int(solved.nfev),integrals=integrals,solution=solution,
                clamp_duty=float(sum(s.dt for s in segments if not s.on and 0 in s.active)/period))


def solve_coupled_flyback(p,nominal_op):
    """Return a verified operating point and ``coupled_solution`` period data.

    ``coupled_model`` contains only JSON-safe metadata and diagnostics.  Period
    arrays are intentionally kept separately.  Invalid/nonconverged circuits
    raise ``ValueError``; the sole fallback is explicitly requested kij=1.
    """
    if p.get('topology')!='FLYBACK' or p.get('feedback_mode','SSR')!='SSR':
        raise ValueError('耦合矩阵时域计算目前只支持固定频率 FLYBACK + SSR')
    from isolated_outputs import output_specs, RAIL_KEYS
    rails=output_specs(p)
    if not rails:
        rails=[dict({k:p.get(k) for k in RAIL_KEYS},name='OUT1',id=1)]
    model=resolve_winding_model(p,rails,nominal_op=nominal_op)
    op=copy.deepcopy(nominal_op)
    metadata=dict(enabled=True,ideal_fallback=bool(model['ideal']),
        model='coupled-RL-stiff-capacitor-fixed-R',
        labels=list(model['labels']),ratios=model['ratios'].tolist(),
        ratio_sources=list(model['ratio_sources']),L=model['L'].tolist(),
        K=model['K'].tolist(),R=model['R'].tolist(),L_leak=float(model['L_leak']),
        dcr_source=model['dcr_source'],
        transformer_hardware=copy.deepcopy(model['transformer_hardware']),
        auto_wire_sizing='nominal-predesign-frozen',
        L_leak_primary=float(model['L_leak']),
        assumptions=['固定频率 SSR；主反馈直流稳压；各路负载 R=反馈设定/匝比近似电压²/额定功率',
                     '逐段求解完整自感/互感矩阵、二极管换流及恒压钳位；无功率比例分配',
                     '输出电容按恒定直流电压求周期电荷平衡；大纹波时需开关电路仿真复核',
                     'RCD 钳位回到 Vin：关断换流电流在原边与钳位间回流，不重复计入净输入电流',
                     '输出为防反管后端口；主反馈固定防反管前电容端，输入/输出防反采用固定压降',
                     '不含 Coss/Cj、反向恢复、寄生振铃、动态反馈和磁芯损耗',
                     '预设效率仅用作初值；物理 RL 方程不叠加等效效率压降',
                     'DCR 由电阻率、MLT、整数匝数、裸铜线径与并绕股数计算；旧手填 DCR 不参与计算',
                     '自动线径按标称预设计 RMS 选择后固定；求解后的实际 RMS 用于电流密度与铜损，不再次改变线径',
                     '原边磁链/Lp 为磁件参考量，不代表任意互感矩阵下唯一可分离的公共磁芯磁通'])
    if model['ideal']:
        # The singular ideal-transformer model cannot independently satisfy
        # arbitrary target voltages and arbitrary secondary turn ratios.
        from voltage_nodes import capacitor_voltage
        loop_voltages=np.array([capacitor_voltage(r)+float(r['Vf_diode']) for r in rails])
        nominal_ratios=model['ratios'][1]*loop_voltages[0]/loop_voltages
        if not np.allclose(model['ratios'][1:],nominal_ratios,rtol=1e-9,atol=1e-12):
            raise ValueError('全部 kij=1 的理想回退要求各路匝比与目标电压比例一致；非一致实际匝数请使用正定耦合矩阵')
        from power_stage import compute_operating_point
        from winding_coupling import resolve_winding_geometry
        hardware=model['transformer_hardware']
        # Resolve the ideal currents at the *actual* integer turns ratio.
        # Freeze the already selected Np/core before this second predesign:
        # changing N must not silently choose another automatic primary.
        ideal_params=dict(p,N=float(model['ratios'][1]),Np=hardware['Np'],
            Ns=hardware['windings'][int(p.get('feedback_output',1))-1]['Ns'],
            core_choice=hardware['core'],MLT=hardware['MLT'],
            coupling_config=dict(enabled=False))
        if p.get('outputs'):
            ideal_params['outputs']=[{key:value for key,value in rail.items() if key!='id'}
                                     for rail in rails]
        op=compute_operating_point(ideal_params)
        # Automatic wire sizes get one cheap corrected-current predesign.
        # Explicit/fixed gauges remain fixed; there is no RL solve iteration.
        geometry=resolve_winding_geometry(ideal_params,op,rails)
        model=resolve_winding_model(ideal_params,rails,geometry=geometry,nominal_op=op)
        metadata.update(ratios=model['ratios'].tolist(),ratio_sources=list(model['ratio_sources']),
            L=model['L'].tolist(),R=model['R'].tolist(),
            transformer_hardware=copy.deepcopy(model['transformer_hardware']))
        from flyback_clamp import attach_clamp
        ideal_clamp_params=dict(ideal_params,K=1.)
        attach_clamp(op,ideal_clamp_params)
        if op.get('aggregate_op'):
            attach_clamp(op['aggregate_op'],ideal_clamp_params)
        for child in op.get('output_ops',[]):
            attach_clamp(child,ideal_clamp_params)
        metadata['assumptions'].append('全部 kij=1：采用原理想变压器标称/预设效率解，DCR 不参与换流；不声称能唯一分配各路电流；漏感尖峰与钳位功耗为 0')
        op['coupled_model']=metadata
        return op
    reached={0}
    for _ in range(len(model['K'])):
        reached |= {j for i in tuple(reached) for j in range(len(model['K'])) if model['K'][i,j]>0}
    if len(reached)!=len(model['K']):
        raise ValueError('存在与原边完全解耦的输出绕组，不能传递功率或由 SSR 稳压')
    for rail in rails:
        if rail['P_out']<=0:
            raise ValueError('耦合矩阵固定电阻负载模型要求各路 P_out>0；空载需明确预负载/寄生泄放')
    count=len(rails)
    main=int(p.get('feedback_output',1))-1
    from voltage_nodes import output_drop,input_drop,CONVENTION
    target=np.array([float(r['V_out']) for r in rails])
    blocking=np.array([output_drop(r) for r in rails])
    target_cap=target+blocking
    vin_bus=float(p['V_in'])-input_drop(p)
    if vin_bus<=0:raise ValueError('输入电压不足以覆盖输入防反二极管压降')
    rated=np.array([float(r['P_out']) for r in rails])
    load_r=target**2/rated
    vf=np.array([float(r['Vf_diode']) for r in rails])
    rd=np.zeros(len(rails))  # deprecated user Rd removed; fixed Vf commutation model
    kc=float(p.get('Kc',1.5))
    clamp=kc*model['ratios'][main+1]*(target_cap[main]+vf[main])
    highest=float(np.max(model['ratios'][1:]*(target_cap+vf)))
    if not np.isfinite(kc) or kc<=1 or clamp<=highest*1.001:
        raise ValueError('耦合矩阵要求 Kc>1，且钳位电压高于所有绕组目标反射电压；请提高 Kc')
    period=1/float(p['f_sw'])
    nominal_children=nominal_op.get('output_ops',[nominal_op])
    current_scale=np.array([max(float(q.get('I_d_pk',rated[j]/target[j]*3)),rated[j]/target[j],.01)
                            for j,q in enumerate(nominal_children)])
    if len(current_scale)!=count:
        current_scale=np.maximum(rated/target*3,.01)
    initial=np.array([max(0.,float(q.get('I_L_min',0)))*model['ratios'][j+1]
                      for j,q in enumerate(nominal_children)])
    if len(initial)!=count:
        initial=np.zeros(count)
    from calculation_scheduler import check_calculation_cancelled
    check_calculation_cancelled()
    point=copy.deepcopy(_periodic_solution(
        tuple(map(tuple,model['L'])),tuple(model['R']),vin_bus,tuple(vf),tuple(rd),
        float(p.get('Rds_on',0)),float(p.get('Rs',0)),clamp,period,
        tuple(target),tuple(blocking),tuple(rated),main,tuple(current_scale),
        tuple(initial),float(nominal_op['D']),float(nominal_op['I_sw_pk'])))
    check_calculation_cancelled()
    return finish_operating_point(p,nominal_op,model,rails,metadata,point,period,
        target,blocking,rated,vin_bus,vf,rd,clamp,main)


def finish_operating_point(p,nominal_op,model,rails,metadata,point,period,
                           target,blocking,rated,vin_bus,vf,rd,clamp,main):
    """Publish one verified RL period; shared by fixed-frequency and QR.

    No control/timing equations live here. Exact charge/energy accounting and
    output-port conventions are identical for either solved switching period.
    """
    op=copy.deepcopy(nominal_op)
    op.update(Ts=float(period),f_sw=1/float(period))
    from isolated_outputs import RAIL_KEYS
    from voltage_nodes import input_drop,CONVENTION
    target_cap=target+blocking
    load_r=target**2/rated
    start,vc,duty=point['start'],point['voltage'],point['duty']
    vo=vc-blocking
    end,error=point['end'],point['error']
    integral,squared,on_integral,on_squared,clamp_integral=point['integrals']
    average,rms2=integral/period,squared/period
    solution=point['solution']
    solution.update(output_voltages=vo.copy(),capacitor_voltages=vc.copy())
    if float(np.min(solution['i_winding'])) < -1e-6:
        raise CoupledConvergenceError('周期样本中出现反向绕组电流；理想二极管导通约束未通过，不输出结果')
    # Independently verify the event solution rather than trusting only its
    # nonlinear root residual.  A blocked diode must not be forward biased.
    open_mask=solution['i_winding'][1:] < 1e-9
    blocking_slack=solution['v_winding'][1:]+vc[:,None]+vf[:,None]
    blocked_violation=float(np.max(np.where(open_mask,np.maximum(-blocking_slack,0.),0.)))
    if blocked_violation>1e-5*max(float(p['V_in']),clamp,1.):
        raise CoupledConvergenceError('周期样本中存在被误判为关断的正向偏置二极管；换流事件校验未通过')
    actual_power=vo**2/load_r
    p_clamp=clamp*clamp_integral/period
    p_dcr=model['R']*rms2
    p_rect=vf*average[1:]+rd*rms2[1:]
    p_block=blocking*average[1:]
    p_input_block=input_drop(p)*on_integral/period
    p_mos=float(p.get('Rds_on',0))*on_squared/period
    p_sense=float(p.get('Rs',0))*on_squared/period
    pin=float(p['V_in'])*on_integral/period
    pout=float(sum(actual_power))
    balance=pin-pout-float(sum(p_dcr))-float(sum(p_rect))-float(sum(p_block))-p_input_block-p_mos-p_sense-p_clamp
    if abs(balance)>max(.001,pin*.002):
        raise CoupledConvergenceError(f'耦合矩阵能量平衡未通过（残差 {balance:.4g} W）；不输出未经验证的应力结果')
    im=solution['i_magnetizing']
    time=solution['t']
    primary_peak=float(np.max(solution['i_sw']))
    # The ideal MOS current starts at zero while leakage current commutates,
    # but this is NOT evidence of zero finite gate-charge switching loss.
    # Use the initial primary-linkage equivalent as an overlap amplitude;
    # the detailed Coss/gate/commutation edge is outside this RL model.
    turnon_overlap_current=max(float(im[0]),0.)
    before_off=solution['i_sw'][time<duty*period]
    turnoff_current=float(before_off[-1]) if len(before_off) else primary_peak
    metadata.update(converged=True,iterations=point['iterations'],duty=duty,
        clamp_voltage=clamp,load_resistances=load_r.tolist(),
        output_voltages=vo.tolist(),capacitor_voltages=vc.tolist(),output_blocking_drops=blocking.tolist(),
        feedback_voltage=float(vc[main]),feedback_target=float(target_cap[main]),
        input_bus_voltage=vin_bus,input_blocking_drop=input_drop(p),voltage_convention=CONVENTION,
        output_power=actual_power.tolist(),P_output_blocking=p_block.tolist(),P_input_blocking=float(p_input_block),
        P_in=pin,P_out=pout,P_rcd=float(p_clamp),P_clamp=float(p_clamp),
        P_dcr=p_dcr.tolist(),P_rectifier=p_rect.tolist(),P_mos_conduction=p_mos,
        P_sense=p_sense,turnon_overlap_current=turnon_overlap_current,
        switching_loss_model='gate-charge engineering estimate; turn-on amplitude uses initial primary linkage/Lp, not instantaneous zero ideal-switch current',
        energy_balance_W=float(balance),
        energy_balance_relative=float(abs(balance)/max(pin,1e-12)),
        normalized_residual=float(np.max(np.abs(error))),
        blocked_diode_violation_V=blocked_violation,
        periodic_current_residual_A=(end[1:]-start).tolist(),
        charge_balance_A=(average[1:]-vo/load_r).tolist(),
        winding_rms=np.sqrt(np.maximum(rms2,0)).tolist(),
        clamp_duty=point['clamp_duty'])
    op.update(coupled_model=metadata,coupled_solution=solution,
        D=duty,Dp=1-duty,mode='CCM' if np.min(im)>max(np.max(im)*1e-5,1e-7) else 'DCM',
        P_out=pout,P_in_est=pin,I_in_est=float(on_integral/period),
        P_loss_budget=pin-pout,efficiency_model='coupled-RL-explicit-losses',
        I_L_avg=float(np.trapezoid(im,time)/period),dI_L=float(np.ptp(im)),
        I_L_pk=float(np.max(im)),I_L_min=float(np.min(im)),
        I_L_rms=float(np.sqrt(np.trapezoid(im**2,time)/period)),
        I_sw_pk=primary_peak,I_sw_avg=float(on_integral/period),
        I_sw_rms=float(np.sqrt(on_squared/period)),I_sw_on=turnon_overlap_current,I_sw_off=turnoff_current,
        V_sw_max=float(np.max(solution['v_sw'])),
        V_out=float(vo[main]),V_out_cap=float(vc[main]),V_feedback=float(vc[main]),V_feedback_target=float(target_cap[main]),
        V_in_bus=vin_bus,V_block=float(blocking[main]),V_input_block=input_drop(p),voltage_convention=CONVENTION,
        V_out_equiv=float(vc[main]+vf[main]),
        R=float(load_r[main]),R_equiv=float(load_r[main]),
        N=float(model['ratios'][main+1]),V_r=float(model['ratios'][main+1]*(vc[main]+vf[main])),
        outputs=rails,feedback_output=main+1,feedback_mode='SSR')
    branch_ops=[]
    transfer_start=duty*period
    for j,rail in enumerate(rails):
        current=solution['i_winding'][j+1]
        conducting=(current>max(float(np.max(current))*1e-5,1e-7)) & (time>transfer_start)
        last=float(time[np.flatnonzero(conducting)[-1]]) if np.any(conducting) else transfer_start
        # Local DCM means early extinction in the energy-transfer interval;
        # ordinary zero current throughout primary ON is not called DCM.
        local_mode='DCM' if last<period-period*.003 else 'CCM'
        child=dict(op)
        child.pop('coupled_solution',None)
        child.pop('aggregate_op',None)
        child.pop('output_ops',None)
        child.update({k:rail[k] for k in RAIL_KEYS if k not in ('L','core_choice_L')})
        child.update(output_id=rail['id'],name=rail['name'],V_out=float(vo[j]),
            V_out_target=float(target[j]),V_out_cap=float(vc[j]),V_feedback=float(vc[j]),
            V_feedback_target=float(target_cap[j]),V_block=float(blocking[j]),
            V_out_equiv=float(vc[j]+vf[j]),P_out=float(actual_power[j]),
            N=float(model['ratios'][j+1]),R=float(load_r[j]),R_equiv=float(load_r[j]),
            I_out=float(vo[j]/load_r[j]),I_d_pk=float(np.max(current)),
            I_d_avg=float(average[j+1]),I_d_rms=float(np.sqrt(rms2[j+1])),
            I_s_rms=float(np.sqrt(rms2[j+1])),local_mode=local_mode,branch_mode=local_mode,mode=local_mode,
            V_d_max=float(np.max(vc[j]+solution['v_winding'][j+1]+model['R'][j+1]*current)),
            C_min=float(vo[j]/load_r[j]*duty*period/(max(rail.get('ripple_target',.01),1e-9)*vo[j])))
        branch_ops.append(child)
    op['output_ops']=branch_ops
    selected=branch_ops[main]
    for key in ('I_out','I_d_pk','I_d_avg','I_d_rms','I_s_rms','V_d_max','C_min',
                'C_out','Rc','ESL','C_out2','Rc2','ESL2','cout2_enable'):
        op[key]=selected[key]
    aggregate=copy.copy(op)
    aggregate.pop('coupled_solution',None)
    aggregate.pop('aggregate_op',None)
    aggregate.pop('output_ops',None)
    aggregate['outputs']=[]
    op['aggregate_op']=aggregate
    op['aggregate_params']=dict(p,outputs=[],feedback_mode='SSR',feedback_output=1)
    solution['diagnostics']=metadata
    op['warnings']=([str(w) for w in op.get('warnings',[]) if '功率比例' not in str(w)]+
        ['耦合矩阵：恒直流电容/固定电阻负载周期解；局部 DCM 不适用原标称 PWM Bode，可另作低频周期映射线性化；钳位波形不含 Coss 寄生振铃。'])
    return op
