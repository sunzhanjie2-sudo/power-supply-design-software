"""Periodic C+ESR boundary comparison for the coupled diode flyback.

A supplemental independent prediction. Uses the design winding matrix, fixed
diode drops, ideal Kc clamp and resistive loads. No simulator measurements.
"""
import numpy as np
from scipy.optimize import root
from capacitor_banks import bank


class _PeriodicBank:
    def __init__(self, parameters, op):
        model = op['coupled_model']
        self.matrix = np.asarray(model['L'])
        self.resistance = np.asarray(model['R'])
        self.vin = float(model['input_bus_voltage'])
        self.clamp = float(model['clamp_voltage'])
        self.on_resistance = parameters['Rds_on'] + parameters['Rs']
        self.load = np.asarray(model['load_resistances'])
        self.blocking = np.asarray(model['output_blocking_drops'])
        self.period = 1 / parameters['f_sw']
        self.fb = int(op['feedback_output']) - 1
        self.target = model['feedback_target']
        self.vf = np.array([rail['Vf_diode'] for rail in op['outputs']])
        banks = [bank(rail) for rail in op['outputs']]
        self.owner = np.repeat(np.arange(len(banks)),[len(b) for b in banks])
        self.cap = np.asarray([item['C'] for b in banks for item in b])
        self.esr = np.asarray([item['ESR'] for b in banks for item in b])
        self.w = len(self.matrix)
        self.guess = np.r_[op['coupled_solution']['i_winding'][:,0],
                           np.asarray(model['capacitor_voltages'])[self.owner],op['D']]
        self.current_scale = np.maximum(np.asarray(model['winding_rms']), .01)
        self.charge_scale = np.maximum(np.asarray(model['output_voltages']) / self.load, .001)
        self.counts = np.bincount(self.owner)
        self.scale = np.r_[self.current_scale, np.maximum(abs(self.guess[self.w:-1]),.1), 1.]

    def phase(self, state, on, duration, steps):
        # Backward-Euler companions: Vk = Vc_old + (ESR + h/C) * Icap.
        dt = duration / steps
        g = 1 / (self.esr + dt / self.cap)
        rnode = 1 / (np.bincount(self.owner,g) + 1 / self.load)
        matrix = self.matrix + dt * np.diag(self.resistance + np.r_[self.on_resistance if on else 0., rnode])
        drive = np.r_[self.vin if on else -self.clamp, -self.vf]
        self_charge = dt * g / self.cap
        inv_cache = {}
        current, cap_voltage = state[:self.w].copy(), state[self.w:].copy()
        active = tuple(np.flatnonzero(current>1e-8))
        if on and 0 not in active:active = (0,)+active
        samples = np.empty((steps,self.w))
        volts = np.empty((steps,self.w-1))

        def solve(mask, rhs):
            if mask not in inv_cache:
                selection = np.asarray(mask,dtype=int)
                inv_cache[mask] = selection,np.linalg.inv(matrix[np.ix_(selection,selection)])
            selected, inverse = inv_cache[mask]
            output = np.zeros(self.w)
            output[selected] = inverse @ rhs[selected]
            return output

        for k in range(steps):
            vth = rnode * (np.bincount(self.owner, g * cap_voltage) + self.blocking / self.load)
            rhs = self.matrix @ current + dt * (drive - np.r_[0., vth])
            # A conducting ideal diode needs nonnegative current. An open diode
            # needs a nonnegative blocking-voltage residual. The MOS is forced
            # on during the on phase; otherwise the primary is the clamp path.
            seen = set()
            while active not in seen:
                seen.add(active)
                current = solve(active,rhs)
                residual = matrix @ current - rhs
                remove = [j for j in active if not (on and j==0) and current[j]<-1e-9]
                if remove:
                    active = tuple(j for j in active if j!=min(remove,key=current.__getitem__))
                    continue
                add = [j for j in range(self.w) if j not in active and residual[j]<-dt*1e-8]
                if add:
                    active = tuple(sorted((*active,min(add,key=residual.__getitem__))))
                    continue
                break
            else:
                raise ValueError('动态电容边界整流状态迭代未收敛')
            v = vth + rnode*current[1:]
            cap_voltage += self_charge*(v[self.owner]-cap_voltage)
            samples[k] = current
            volts[k] = v
        return np.r_[current,cap_voltage],samples,volts

    def solve(self, points, guess, cancelled):
        from calculation_scheduler import CalculationCancelled
        split = min(points-1,max(1,round(guess[-1]*points)))
        def cycle(z):
            if cancelled():raise CalculationCancelled()
            x = z*self.scale
            duty = x[-1]
            if not .001<duty<.995:raise ValueError('动态边界占空比越界')
            mid, ion, von = self.phase(x[:-1],True,duty*self.period,split)
            end, ioff, voff = self.phase(mid,False,(1-duty)*self.period,points-split)
            vmean = duty*von.mean(axis=0)+(1-duty)*voff.mean(axis=0)
            delta = end-x[:-1]
            residual = np.r_[delta[:self.w]/self.current_scale,
                             delta[self.w:]*self.cap/self.period*self.counts[self.owner]/self.charge_scale[self.owner],
                             (vmean[self.fb]-self.target)/self.target]
            return residual, ion, ioff, vmean
        z = root(lambda z:cycle(z)[0],guess/self.scale,options={'xtol':1e-8, 'maxfev':180}).x
        err, ion, ioff, mean = cycle(z)
        residual = float(np.max(abs(err)))
        if residual>2e-5 or not np.isfinite(residual):raise ValueError('动态边界周期/电荷平衡未通过')
        duty=z[-1]
        average=duty*ion.mean(axis=0)+(1-duty)*ioff.mean(axis=0)
        square=duty*(ion**2).mean(axis=0)+(1-duty)*(ioff**2).mean(axis=0)
        peak=np.maximum(ion.max(axis=0),ioff.max(axis=0))
        table=np.column_stack((average[1:],np.sqrt(square[1:]),peak[1:],mean-self.blocking))
        if np.any(table<0) or not np.all(np.isfinite(table)):raise ValueError('动态边界电流或电压无效')
        return z*self.scale,table,residual


def predict(parameters, op, cancelled=lambda:False):
    """Refine the switch-period mesh before releasing a supplementary estimate."""
    if parameters.get('topology')!='FLYBACK' or not op.get('coupled_model',{}).get('converged'):
        return None
    settings=parameters.get('spice_config') or {}
    if settings.get('include_cap_esl'):
        return dict(available=False,error='启用了 ESL，此 C+ESR 补充模型不覆盖 ESL')
    if settings.get('frequency_hz') and not np.isclose(settings['frequency_hz'],parameters['f_sw']):
        return dict(available=False,error='设计与实际导出的频率不同')
    circuit=_PeriodicBank(parameters,op)
    seed=circuit.guess
    previous=None
    consecutive=0
    for points in (192,384,768,1536,3072,6144):
        seed,table,residual=circuit.solve(points,seed,cancelled)
        if previous is not None:
            change=float(100*np.max(abs(table-previous)/np.maximum(abs(table),1e-6)))
            consecutive=consecutive+1 if change<=1.0 else 0
            if consecutive>=2:
                keys=('average_a','rms_a','peak_a','port_v')
                return dict(available=True,method='设计互感矩阵、固定 Kc 钳位、逐颗 C+ESR 周期电荷平衡',
                            duty=float(seed[-1]),mesh=points,mesh_change_pct=change,normalized_residual=residual,
                            outputs=[dict(zip(keys,map(float,row))) for row in table])
        previous=table
    return dict(available=False,error=f'动态边界未连续两级达到 1% 网格检查，最后变化 {change:.2f}%')


def attach_comparison(parameters, op, record, cancelled=lambda:False):
    """Attach a supplementary prediction without changing measured or design rows."""
    if record.get('fault_test') or not record.get('nominal_comparable'):
        return
    try:
        result=predict(parameters,op,cancelled)
    except (ValueError,np.linalg.LinAlgError,FloatingPointError) as exc:
        result=dict(available=False,error=str(exc))
    if result is None:
        return
    record['capacitor_boundary']=result
    switching=record['switching']
    for branch in record['branches']:
        if result['available']:
            branch['capacitor_boundary']=result['outputs'][branch['id']-1]
        if branch.get('design_current') is not None:
            branch['current_shape']=dict(
                threshold_fraction=.05,
                design_fraction=_positive_pulse_fraction(switching['time'],branch['design_current']),
                simulation_fraction=_positive_pulse_fraction(switching['time'],switching[f"i(ls{branch['id']})"]),
                source='五个周期的展示波形，按各自正峰值 5% 的线性交点估算宽度')


def _positive_pulse_fraction(time, values):
    values=np.asarray(values)
    if max(values)<=0:
        return None
    residual=values-.05*max(values)
    left,right=residual[:-1],residual[1:]
    high=((left>0)&(right>0)).astype(float)
    rising=(left<=0)&(right>0)
    falling=(left>0)&(right<=0)
    high[rising]=right[rising]/(right[rising]-left[rising])
    high[falling]=left[falling]/(left[falling]-right[falling])
    return float(np.average(high,weights=np.diff(time)))
