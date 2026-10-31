"""Small-signal (control-to-output) models for the loop-design tab.

Buck / Boost / Buck-Boost / Flyback: CCM average models, voltage mode and
peak-current mode, following R. W. Erickson "Fundamentals of Power
Electronics" (3rd ed.) — see the book's chapters on the averaged switch
model and current-programmed control (Fm/Fg/Fv formulation).

"""

class _LazyControl:
    """Import the (heavy) control package on first attribute access instead
    of at module import time — start-up does not need it until the loop tab
    is used."""
    def __getattr__(self, name):
        import control
        globals()['ct'] = control          # replace the proxy outright
        return getattr(control, name)


ct = _LazyControl()

import numpy as np


def build_loop_models(p, op):
    """One plant factory for GUI, API, reports and corners, using solved op."""
    if op.get('niso_model'):
        from nonisolated import build_loop
        return build_loop(p,op)
    if op.get('acf_model',{}).get('converged'):
        from acf_loop import build_loop
        return build_loop(p,op)
    if op.get('coupled_model') and not op['coupled_model'].get('ideal_fallback'):
        from multi_output_loop import build_coupled_loop
        return build_coupled_loop(p, op)
    source, solved = p, op
    if op.get('aggregate_op'):
        p, op = dict(op['aggregate_params']), op['aggregate_op']
        if solved.get('outputs'):
            # Secondary voltages are constrained by the nominal turns ratios.
            # Refer all stored capacitor energy to the selected feedback rail.
            from capacitor_banks import total
            p['C_out'] = sum(total(r)
                             *(r['V_out']/op['V_out'])**2 for r in solved['outputs'])
    psr = source.get('feedback_mode') == 'PSR-MP6005'
    if psr and solved.get('regulation_region') != 'PWM':
        raise ValueError('MP6005 轻载 PFM：不提供 PWM/SSR Bode 裕度；需时域仿真与实测')
    topo = p['topology']
    if topo == 'QR-FLYBACK' and p['control_mode']=='Peak Current Mode' and not solved.get('outputs') and not psr:
        from qr_loop import plant as qr_plant
        from types import SimpleNamespace
        gvc,detail=qr_plant(p,op)
        gc=make_compensator(p).get_transfer_function()
        note=('QR/BCM 峰值电流控制的周期平均低频近似：按实际电压、峰值电流及变频线性化；'
              '并联电容分别计入 ESR。Gvc 输入为放大后 CS 等效控制指令；'
              'A_sense 只表示采样增益，不代替真实 COMP 管脚的前馈/电平转换。'
              '损耗按工作点常数比例近似，不含谷底跳变、开关延迟及光耦动态。')
        return (gvc,gc,gvc*gc),SimpleNamespace(model_note=note,qr_linearization=detail,mode='BCM')
    cls = {'BUCK': BuckConverter, 'BOOST': BoostConverter,
           'BUCK-BOOST': BuckBoostConverter, 'FLYBACK': FlybackConverter,
           'QR-FLYBACK': FlybackConverter, 'ACF-FORWARD': ActiveClampForwardConverter}[topo]
    # Freeze the design efficiency at this operating point. The ideal core
    # sees U=Vo/eta, R_eq=R/eta; map its output gain back to the real Vo.
    # This is an engineering approximation, NOT a dynamic loss model.
    if p.get('output_capacitors') is not None:
        from capacitor_banks import total,bank
        p=dict(p);p['C_out']=total(p)
        p['Rc']=sum(c['ESR']*c['C']**2 for c in bank(p))/p['C_out']**2
    args = [p['V_in'], op['V_out_equiv'], op['P_in_est'], op['f_sw'], p['L'],
            p['C_out'], p['Vm']]
    kwargs = dict(Rs=p['Rs'], Rc=p['Rc'], A_sense=p.get('A_sense', 1),
                  ma=p.get('ma_slope', 0))
    if topo in ('FLYBACK', 'QR-FLYBACK', 'ACF-FORWARD'):
        kwargs.update(N=p['N'], Vf=0.0)
    if topo == 'ACF-FORWARD':
        kwargs['Lm'] = p['Lm_forward']
    plant = cls(*args, **kwargs)
    plant.mode, plant.D_actual = op['mode'], op['D']
    gvc = (plant.get_peak_current_mode_transfer_function()
           if p['control_mode'] == 'Peak Current Mode'
           else plant.get_voltage_mode_transfer_function())
    gvc *= op['eta_guess']
    if psr:
        from mp6005 import design_psr
        from loss_model import magnetics_design
        from isolated_outputs import multi_magnetics
        detail = solved.get('psr')
        if detail is None:
            md = multi_magnetics(solved,source) if solved.get('outputs') else magnetics_design(solved,p)
            detail = design_psr(source,solved,md.get('transformer'))
        s = ct.tf('s')
        gvc *= detail['Hfb']*(1-s*op['Ts']/4)/(1+s*op['Ts']/4)
        gc = Compensator2P2Z(detail['KP'],detail['fz'],detail['fp']).get_transfer_function()
        plant.model_note = detail['note']
    else:
        gc = make_compensator(p).get_transfer_function()
    if solved.get('outputs'):
        from multi_output_loop import attach_nominal_context
        attach_nominal_context(gvc, source, solved)
    return (gvc, gc, gvc * gc), plant



def _dcm_gvd(s, V_out, D, M, R, C, kind):
    """DCM control-to-output Gvd(s): single-pole, no RHP zero.

    Erickson, Fundamentals of Power Electronics, 3rd ed., Table 15.3
    (approximate DCM model of Fig. 15.20).  The exact DCM model retains a
    second pole and an RHP zero, but both occur near / above the switching
    frequency and are ignored for loop analysis.  'kind' in
    {'buck', 'boost', 'buckboost'} (flyback uses the buck-boost form).
    """
    if kind == 'buck':
        Gd0 = 2.0 * V_out / D * (1.0 - M) / (2.0 - M)
        wp = (2.0 - M) / ((1.0 - M) * R * C)
    elif kind == 'boost':
        Gd0 = 2.0 * V_out / D * (M - 1.0) / (2.0 * M - 1.0)
        wp = (2.0 * M - 1.0) / ((M - 1.0) * R * C)
    else:  # buck-boost / flyback
        Gd0 = V_out / D
        wp = 2.0 / (R * C)
    return Gd0 / (1.0 + s / max(wp, 1e-9))


def normalize_controller_type(value):
    kind = str(value).strip().lower()
    if kind == 'pi':
        return 'auto'  # compatibility with configs from the withdrawn PI update
    if kind not in ('auto', 'type2', 'type3'):
        raise ValueError('Controller type must be auto / type2 / type3')
    return kind


def resolve_controller_type(selection='auto', control_mode='Voltage Mode'):
    kind = normalize_controller_type(selection)
    return ('type2' if control_mode == 'Peak Current Mode' else 'type3') if kind == 'auto' else kind


def make_compensator(p):
    """Shared GUI/API factory. Control mode selects the plant, not an explicit controller."""
    kind = resolve_controller_type(p.get('controller_type', 'auto'), p.get('control_mode'))
    if kind == 'type2':
        return Compensator2P2Z(p['KP'], p['fz1'], p['fp1'])
    return Compensator3P3Z(p['KP'], p['fz1'], p['fz2'], p['fp1'], p['fp2'])


class Compensator3P3Z:
    """Type III: three poles (including the origin), two finite zeros."""

    def __init__(self, KP, fz1, fz2, fp1, fp2):
        self.s = ct.tf('s')
        self.KP = KP
        self.wz1 = 2 * np.pi * fz1
        self.wz2 = 2 * np.pi * fz2
        self.wp1 = 2 * np.pi * fp1
        self.wp2 = 2 * np.pi * fp2

    def get_transfer_function(self):
        Gc = (self.KP * (1 + self.s / self.wz1) * (1 + self.s / self.wz2)
              / self.s / (1 + self.s / self.wp1) / (1 + self.s / self.wp2))
        return Gc


class Compensator2P2Z:
    """Type II: two poles (including the origin), one finite zero."""

    def __init__(self, KP, fz, fp):
        self.s = ct.tf('s')
        self.KP = KP
        self.wz = 2 * np.pi * fz
        self.wp = 2 * np.pi * fp

    def get_transfer_function(self):
        Gc = self.KP * (1 + self.s / self.wz) / self.s / (1 + self.s / self.wp)
        return Gc


def _pwm_fm(f_switch, Rs, A_sense, ma, M1, M2):
    """PWM modulator gain (Ridley/Basso): Fm = 1/((ma+(M1-M2)/2)*Ts*Rs),
    scaled by the sense amplifier gain.  Falls back to the mean of the up/down
    slopes when the raw denominator is not positive (e.g. no slope comp with
    D > 0.5) so Fm stays finite and positive."""
    den = ma + (M1 - M2) / 2.0
    if den <= 0:
        den = (M1 + M2) / 2.0
    return f_switch / (Rs * A_sense * max(abs(den), 1.0))


class BuckConverter:
    def __init__(self, V_in, V_out, P_out, f_switch, L, C_out, Vm,
                 Rs=0.01, Rc=15e-3, A_sense=1.0, ma=0.0):
        self.s = ct.tf('s')
        self.V_in = V_in
        self.V_out = V_out
        self.P_out = P_out
        self.f_switch = f_switch
        self.L = L
        self.C_out = C_out
        self.Vm = Vm
        self.Rs = Rs
        self.Rc = Rc
        self.A_sense = A_sense          # current-sense amplifier gain
        self.ma = ma                    # slope compensation (A/s)
        self.R = V_out ** 2 / P_out if P_out > 0 else 5
        self.D = V_out / V_in if V_in > 0 else 0.5
        self.Ts = 1 / f_switch

        self.Fm = _pwm_fm(f_switch, Rs, A_sense, ma, V_in / L, V_out / L)

        self.Fg = (self.D ** 2 * self.Ts * Rs * A_sense) / (2 * L)
        self.Fv = ((1 - 2 * self.D) * self.Ts * Rs * A_sense) / (2 * L)

    def get_voltage_mode_transfer_function(self):
        if getattr(self, 'mode', 'CCM') in ('DCM', 'BCM'):
            D = getattr(self, 'D_actual', self.D)
            M = self.V_out / max(self.V_in, 1e-9)
            return _dcm_gvd(self.s, self.V_out, D, M, self.R, self.C_out, 'buck') / self.Vm
        den = 1 + self.s * self.L / self.R + self.s ** 2 * self.L * self.C_out
        Gvd = self.V_out / self.D / den
        Gvc = Gvd / self.Vm
        return Gvc

    def get_peak_current_mode_transfer_function(self):
        if getattr(self, 'mode', 'CCM') in ('DCM', 'BCM'):
            D = getattr(self, 'D_actual', self.D)
            M = self.V_out / max(self.V_in, 1e-9)
            return _dcm_gvd(self.s, self.V_out, D, M, self.R, self.C_out, 'buck') / self.Vm
        Fi = self.Rs * self.A_sense
        term1 = self.Fm * self.V_out * Fi / (self.D * self.R)
        term2 = (self.Fm * self.Fv * self.V_out) / self.D

        omega_c = 1 / np.sqrt(self.L * self.C_out) * np.sqrt(1 + term1 + term2)
        Q_c = (self.R * np.sqrt(self.C_out / self.L)
               * np.sqrt(1 + term1 + term2)
               / (1 + self.R * self.C_out * self.Fm * self.V_out * Fi
                  / (self.D * self.L)))

        G_c0 = self.V_out * self.Fm / self.D / (1 + term1 + term2)

        num = G_c0
        den = 1 + self.s / (Q_c * omega_c) + (self.s / omega_c) ** 2

        Gvc = num / den
        return Gvc


class ActiveClampForwardConverter(BuckConverter):
    """Buck-derived forward plant below the clamp resonance (TI SLUA535A).

    Primary current sensing observes iL/N plus magnetizing current, so Rs/N
    is used on the secondary-referred model. The magnetizing ON slope is
    included in the equivalent artificial current ramp. Clamp resonance and
    sampled-data/dead-time effects require a switching model; the UI reports
    a crossover ceiling instead of claiming broadband model accuracy.
    """
    def __init__(self, V_in, V_out, P_out, f_switch, L, C_out, Vm, N,
                 Rs=.01, Rc=.015, A_sense=1.0, ma=0.0, Lm=220e-6, Vf=.7):
        if N <= 0 or Lm <= 0:
            raise ValueError('Forward: N and Lm must be positive')
        self.turns_ratio = N
        super().__init__(V_in/N, V_out, P_out, f_switch, L, C_out, Vm,
                         Rs/N, Rc, A_sense=A_sense,
                         ma=N*(ma+V_in/Lm))
        self.D = (V_out+Vf)/(V_in/N)

    def get_voltage_mode_transfer_function(self):
        if getattr(self, 'mode', 'CCM') == 'DCM':
            return super().get_voltage_mode_transfer_function()
        s = self.s
        den = 1+s*(self.L/self.R+self.Rc*self.C_out) + \
              s**2*self.L*self.C_out*(1+self.Rc/self.R)
        return self.V_in*(1+s*self.Rc*self.C_out)/(self.Vm*den)


class BoostConverter:
    def __init__(self, V_in, V_out, P_out, f_switch, L, C_out, Vm,
                 Rs=0.01, Rc=15e-3, A_sense=1.0, ma=0.0):
        self.s = ct.tf('s')
        self.V_in = V_in
        self.V_out = V_out
        self.P_out = P_out
        self.f_switch = f_switch
        self.L = L
        self.C_out = C_out
        self.Vm = Vm
        self.Rs = Rs
        self.Rc = Rc
        self.A_sense = A_sense
        self.ma = ma
        self.R = V_out ** 2 / P_out if P_out > 0 else 5
        self.D = 1 - V_in / V_out if V_out > 0 else 0.5
        self.D_prime = 1 - self.D
        self.Ts = 1 / f_switch

        self.Fm = _pwm_fm(f_switch, Rs, A_sense, ma,
                          V_in / L, (V_out - V_in) / L)

        self.Fg = ((2 * self.D - 1) * self.Ts * Rs * A_sense) / (2 * L)
        self.Fv = (self.D_prime ** 2 * self.Ts * Rs * A_sense) / (2 * L)

    def get_voltage_mode_transfer_function(self):
        if getattr(self, 'mode', 'CCM') in ('DCM', 'BCM'):
            D = getattr(self, 'D_actual', self.D)
            M = self.V_out / max(self.V_in, 1e-9)
            return _dcm_gvd(self.s, self.V_out, D, M, self.R, self.C_out, 'boost') / self.Vm
        den = (1 + self.s * self.L / (self.D_prime ** 2 * self.R)
               + self.s ** 2 * self.L * self.C_out / (self.D_prime ** 2))
        Gvd = (self.V_out / self.D_prime
               * (1 - self.s * self.L / (self.D_prime ** 2 * self.R)) / den)
        Gvc = Gvd / self.Vm
        return Gvc

    def get_peak_current_mode_transfer_function(self):
        if getattr(self, 'mode', 'CCM') in ('DCM', 'BCM'):
            D = getattr(self, 'D_actual', self.D)
            M = self.V_out / max(self.V_in, 1e-9)
            return _dcm_gvd(self.s, self.V_out, D, M, self.R, self.C_out, 'boost') / self.Vm
        Fi = self.Rs * self.A_sense
        term1 = 2 * self.Fm * self.V_out * Fi / (self.D_prime ** 2 * self.R)
        term2 = (self.Fm * self.Fv * self.V_out) / self.D_prime

        omega_c = (self.D_prime / np.sqrt(self.L * self.C_out)
                   * np.sqrt(1 + term1 + term2))
        Q_c = (self.D_prime * self.R * np.sqrt(self.C_out / self.L)
               * np.sqrt(1 + term1 + term2)
               / (1 + self.R * self.C_out * self.Fm * self.V_out * Fi
                  / (self.D_prime * self.L)
                  - self.Fm * self.Fv * self.V_out / self.D_prime))

        G_c0 = self.V_out * self.Fm / self.D_prime / (1 + term1 + term2)

        num = G_c0 * (1 - self.s * self.L / (self.D_prime ** 2 * self.R))
        den = 1 + self.s / (Q_c * omega_c) + (self.s / omega_c) ** 2

        Gvc = num / den
        return Gvc


class BuckBoostConverter:
    def __init__(self, V_in, V_out, P_out, f_switch, L, C_out, Vm,
                 Rs=0.01, Rc=15e-3, A_sense=1.0, ma=0.0):
        self.s = ct.tf('s')
        self.V_in = V_in
        self.V_out = V_out
        self.P_out = P_out
        self.f_switch = f_switch
        self.L = L
        self.C_out = C_out
        self.Vm = Vm
        self.Rs = Rs
        self.Rc = Rc
        self.A_sense = A_sense
        self.ma = ma
        self.R = V_out ** 2 / P_out if P_out > 0 else 5
        self.D = V_out / (V_in + V_out) if (V_in + V_out) > 0 else 0.5
        self.D_prime = 1 - self.D
        self.Ts = 1 / f_switch

        self.Fm = _pwm_fm(f_switch, Rs, A_sense, ma, V_in / L, V_out / L)

        self.Fg = (self.D ** 2 * self.Ts * Rs * A_sense) / (2 * L)
        self.Fv = -(self.D_prime ** 2 * self.Ts * Rs * A_sense) / (2 * L)

    def get_voltage_mode_transfer_function(self):
        if getattr(self, 'mode', 'CCM') in ('DCM', 'BCM'):
            D = getattr(self, 'D_actual', self.D)
            M = self.V_out / max(self.V_in, 1e-9)
            return _dcm_gvd(self.s, self.V_out, D, M, self.R, self.C_out, 'buckboost') / self.Vm
        den = (1 + self.s * self.L / (self.D_prime ** 2 * self.R)
               + self.s ** 2 * self.L * self.C_out / (self.D_prime ** 2))
        Gvd = (-self.V_out / self.D_prime / self.D
               * (1 - self.s * self.D * self.L / (self.D_prime ** 2 * self.R))
               / den)
        Gvc = Gvd / self.Vm
        return Gvc

    def get_peak_current_mode_transfer_function(self):
        if getattr(self, 'mode', 'CCM') in ('DCM', 'BCM'):
            D = getattr(self, 'D_actual', self.D)
            M = self.V_out / max(self.V_in, 1e-9)
            return _dcm_gvd(self.s, self.V_out, D, M, self.R, self.C_out, 'buckboost') / self.Vm
        Fi = self.Rs * self.A_sense
        term1 = (self.Fm * self.V_out * (1 + self.D) * Fi
                 / (self.D_prime ** 2 * self.R * self.D))
        term2 = -(self.Fm * self.Fv * self.V_out) / self.D_prime / self.D

        omega_c = (self.D_prime / np.sqrt(self.L * self.C_out)
                   * np.sqrt(1 + term1 + term2))
        Q_c = (self.D_prime * self.R * np.sqrt(self.C_out / self.L)
               * np.sqrt(1 + term1 + term2)
               / (1 + self.R * self.C_out * self.Fm * self.V_out * Fi
                  / (self.D * self.L)
                  + self.Fm * self.Fv * self.V_out / self.D_prime))

        G_c0 = (-self.V_out * self.Fm / self.D_prime / self.D
                / (1 + term1 + term2))

        num = G_c0 * (1 - self.s * self.D * self.L / (self.D_prime ** 2 * self.R))
        den = 1 + self.s / (Q_c * omega_c) + (self.s / omega_c) ** 2

        Gvc = num / den
        return Gvc


class FlybackConverter:
    def __init__(self, V_in, V_out, P_out, f_switch, L, C_out, Vm, N=10,
                 Rs=0.01, Rc=15e-3, Vf=0.7, A_sense=1.0, ma=0.0):
        self.s = ct.tf('s')
        self.V_in = V_in
        self.V_out = V_out
        self.P_out = P_out
        self.f_switch = f_switch
        self.L = L
        self.C_out = C_out
        self.Vm = Vm
        self.N = N
        self.Rs = Rs
        self.Rc = Rc
        self.Vf = Vf
        self.A_sense = A_sense          # current-sense amplifier gain
        self.ma = ma                    # slope compensation (A/s, primary)
        self.R = V_out ** 2 / P_out if P_out > 0 else 5
        self.D = (N * (V_out + Vf) / (V_in + N * (V_out + Vf))
                  if (V_in + N * (V_out + Vf)) > 0 else 0.5)
        self.D_prime = 1 - self.D
        self.Ts = 1 / f_switch

        # PWM modulator gain (Ridley/Basso): Fm = 1/((ma + (M1-M2)/2)·Ts·Rs),
        # scaled by the sense amplifier gain.  With no slope compensation and
        # D > 0.5 the raw denominator goes negative -> fall back to the mean
        # of the up/down slopes (finite, positive).
        self.Fm = _pwm_fm(f_switch, Rs, A_sense, ma, V_in / L,
                          (V_out + Vf) * N / L)
        self.fm_fallback = ma + ((V_out + Vf) * N - V_in) / L / 2.0 <= 0

    def get_voltage_mode_transfer_function(self):
        if getattr(self, 'mode', 'CCM') in ('DCM', 'BCM'):
            D = getattr(self, 'D_actual', self.D)
            M = self.V_out / max(self.V_in, 1e-9)
            return _dcm_gvd(self.s, self.V_out, D, M, self.R, self.C_out, 'buckboost') / self.Vm
        delta = (1 + self.s * self.L / (self.N * self.D_prime) ** 2 / self.R
                 + self.s ** 2 * self.L * self.C_out
                 / (self.N * self.D_prime) ** 2)
        Gvd = (self.V_out / self.D / self.D_prime
               * (1 - self.s * self.D * self.L
                  / (self.N * self.D_prime) ** 2 / self.R) / delta)
        return Gvd / self.Vm

    def get_peak_current_mode_transfer_function(self):
        if getattr(self, 'mode', 'CCM') in ('DCM', 'BCM'):
            D = getattr(self, 'D_actual', self.D)
            M = self.V_out / max(self.V_in, 1e-9)
            return _dcm_gvd(self.s, self.V_out, D, M, self.R, self.C_out, 'buckboost') / self.Vm
        delta = (1 + self.s * self.L / (self.N * self.D_prime) ** 2 / self.R
                 + self.s ** 2 * self.L * self.C_out
                 / (self.N * self.D_prime) ** 2)
        Gvd = (self.V_out / self.D / self.D_prime
               * (1 - self.s * self.D * self.L
                  / (self.N * self.D_prime) ** 2 / self.R) / delta)

        Fg = (self.D ** 2 * self.Ts * self.Rs * self.A_sense) / (2 * self.L)
        Fv = -(self.D_prime ** 2 * self.Ts * self.Rs * self.A_sense) \
            / (2 * self.L)

        Gid = (self.N * self.V_out * (1 + self.D)
               * (1 + self.s * self.R * self.C_out / (1 + self.D))
               / self.D / (self.N * self.D_prime) ** 2 / self.R / delta)

        # Current-loop return: the sensed inductor current enters the PWM
        # comparator through Fi = Rs*A_sense (the factor the model used to
        # miss -> Rs barely changed the loop).  Gid is duty->inductor current
        # [A/duty], so Fi*Gid is comparator-referred [V/duty].
        Fi = self.Rs * self.A_sense
        Gvc = self.Fm * Gvd / (1 + self.Fm * (Fi * Gid + Fv * Gvd))
        return Gvc
