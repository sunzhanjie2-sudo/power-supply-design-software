"""Compensation-network component calculator (tab 8).

Back-solves the RC values of four compensator topologies from the K-factor
compensator constants designed on tab 4 (KP, fz1, fz2, fp1, fp2, entered in
Hz on the GUI, converted to rad/s here).  Part names follow the reference
figures shown on the GUI tab:

1. opamp3 — op-amp type III (figure "Ⅲ补偿"):
   R1 upper divider, R3+C3 series (parallel R1), R2+C1 series feedback with
   C2 in parallel, R_lower lower divider, output Vc.
        KP  = 1/(R1 (C1+C2))
        fz1 = 1/(2πR2C1)          fz2 = 1/(2π(R1+R3)C3)
        fp2 = 1/(2πR2·C1C2/(C1+C2))   (fp1 = 0: integrator)
        fp3 = 1/(2πR3C3)
   Type II special case: C2 = C3 = 0.

2. gm3 — transconductance type III (TI gm figure):
   R1 upper divider with C1 in parallel, R2 lower divider, gm amp with +
   input at Vref, output Vcont, Zt = C3 ∥ (R3 + C2 series) to ground.
        KP  = gm·R2/((C2+C3)(R1+R2))
        fz1 = 1/(2πR3C2)          fz2 = 1/(2πR1C1)
        fp1 = 1/(2πR3·C2C3/(C2+C3))
        fp2 = (R1+R2)/(2πR1C1R2)
   Type II special case: C1 = C3 = 0 (R1 must be given by the user).

3. tl431nf — TL431 + optocoupler type III WITHOUT fast lane (TND381-D p.45
   figure; LED resistor to the independent bias Vdd):
        KP  = CTR·Rpullup/(R_LED·R1·C1)     (integrator gain)
        fz1 = 1/(2πR2C1)          (R2+C1 series, FB → cathode)
        fz2 = 1/(2πR1C3)          (R3+C3 series parallel R1, Vout → FB)
        fp1 = 1/(2πR3C3)
        fp2 = 1/(2πRpullup(C2 ∥ Copto))
   Exact derivation: FB is a virtual ground, the LED branch sees no Vout
   feedthrough (Vdd is an AC ground), so v_c/v_out = CTR·Rpullup/R_LED·
   v_k/v_out with v_k = -v_out·Y_div/Y_f.
   R_z (Vout→Vz cathode bias) and R_bias are design hints, not solved.

4. tl431f — TL431 + optocoupler type III WITH fast lane (TND381-D p.44
   figure; LED resistor to Vout):
        KP  = CTR·Rpullup/(R_LED·R1·C1)     (integrator gain)
        fz1 = 1/(2πR1C1)          (C1 directly FB → cathode)
        fz2 = 1/(2π(R_LED+R_pz)C_pz)
        fp1 = 1/(2πR_pzC_pz)
        fp2 = 1/(2πRpullup(C2 ∥ Copto))
   The fast lane adds a direct Vout→LED feedthrough (flat gain floor
   CTR·Rpullup/R_LED at high frequency) but the K-factor integrator gain
   still comes from C1 against the divider R1.
   NOTE: the fast lane creates a high-frequency gain floor (TND381-D p.35);
   the no-fast-lane version is preferred when that matters.

References: TND381-D (C. Basso, "The TL431 in the Control of Switching Power
Supplies", ON Semiconductor); D. Venable, "The K Factor", Powercon 10, 1983.
"""

import math


def _series_split(S, ratio):
    """C1 + C2 = S with C1*C2/(C1+C2) = S*ratio (ratio = wz1/wp1 < 1)."""
    if not 0.0 < ratio < 1.0:
        raise ValueError('need wz1 < wp1 for the C1/C2 split')
    C2 = S * ratio
    C1 = S - C2
    return C1, C2


def type2_network_solve(key, KP, wz, wp, inputs, *, Vout):
    """Realize KP(1+s/wz)/(s(1+s/wp)), without inactive Type III corners.

    Component names follow the existing figures. This is distinct from the
    historical ``type2=True`` PI reduction, which omits the finite pole.
    TL431 assumes an ideal cathode virtual ground and configured CTR/Copto.
    """
    if not all(math.isfinite(v) and v>0 for v in (KP,wz,wp)):
        raise ValueError('二型有效 KP、fz1、fp1 必须为有限正数')
    def positive(name,default=None):
        value=float(inputs[name] if name in inputs else default)
        if not math.isfinite(value) or value<=0:raise ValueError(name+' 必须为有限正数')
        return value
    if key=='opamp3':
        R1=positive('R1');S=1/(KP*R1)
        C1,C2=_series_split(S,wz/wp)
        return dict(kind=key,type2=True,R1=R1,R2=1/(wz*C1),R3=0.,C1=C1,C2=C2,C3=0.,Vref=positive('Vref',2.5))
    if key=='gm3':
        R2=positive('R2');gm=positive('gm');vref=positive('Vref',2.5)
        R1=float(inputs.get('R1u',0))
        if not R1:
            if Vout<=vref:raise ValueError('输出电压必须高于 gm 分压基准')
            R1=R2*(Vout/vref-1)
        if not math.isfinite(R1) or R1<=0:raise ValueError('R1 必须为有限正数')
        C2,C3=_series_split(gm*R2/(KP*(R1+R2)),wz/wp)
        return dict(kind=key,type2=True,gm=gm,R1=R1,R2=R2,R3=1/(wz*C2),C1=0.,C2=C2,C3=C3)
    if key not in ('tl431nf','tl431f'):raise ValueError('未知补偿参考网络')
    R1=positive('R1');CTR=positive('CTR');Rp=positive('Rpullup')
    Copto=float(inputs.get('Copto',0))
    if not math.isfinite(Copto) or Copto<0:raise ValueError('C_opto 必须为有限非负数')
    total=1/(wp*Rp)
    d=dict(kind=key,type2=True,R1=R1,CTR=CTR,Rpullup=Rp,Copto=Copto,
           C2=total-Copto,C2_tot=total,Vref=2.5,Vout=Vout,
           fp_opto=1/(2*math.pi*Rp*Copto) if Copto>0 else math.inf)
    if key=='tl431nf':
        Rled=positive('R_LED');C1=CTR*Rp/(KP*R1*Rled)
        d.update(R_LED=Rled,C1=C1,R2=1/(wz*C1),R3=0.,C3=0.,
                 R_LED_max=(Vout-3.5)/2e-3)
    else:
        C1=1/(R1*wz)
        d.update(C1=C1,R_LED=CTR*Rp*wz/KP,R_pz=0.,C_pz=0.)
    return d


def controller_updates(realized):
    """Preserve a physical two-pole/one-zero network without far-away pairs."""
    exact_two=(math.isfinite(realized['wp1']) and not math.isfinite(realized['wz2'])
               and not math.isfinite(realized['wp2']))
    keys=('wz1','wp1') if exact_two else ('wz1','wz2','wp1','wp2')
    names=dict(wz1='fz1',wz2='fz2',wp1='fp1',wp2='fp2')
    updates=dict(KP=realized['KP'],controller_type='type2' if exact_two else 'type3')
    for key in keys:
        updates[names[key]]=realized[key]/(2*math.pi) if math.isfinite(realized[key]) else 1e9
    return updates


# ---------------------------------------------------------------- op-amp III
def opamp_type3_solve(KP, wz1, wz2, wp1, wp2, R1, type2=False):
    """Op-amp type III (figure "Ⅲ补偿" naming).  User chooses R1 (divider)."""
    if R1 <= 0 or KP <= 0:
        raise ValueError('R1 / KP must be positive')
    if type2:
        C1 = 1.0 / (KP * R1)
        R2 = 1.0 / (wz1 * C1)
        return dict(kind='opamp3', type2=True, R1=R1, R2=R2, R3=0.0,
                    C1=C1, C2=0.0, C3=0.0)
    if not (0 < wz1 < wp1 and 0 < wz2 < wp2):
        raise ValueError('need wz1 < wp1 and wz2 < wp2')
    R3 = wz2 * R1 / (wp2 - wz2)
    C3 = 1.0 / (wp2 * R3)
    S = 1.0 / (KP * R1)                     # C1 + C2
    C1, C2 = _series_split(S, wz1 / wp1)
    R2 = 1.0 / (wz1 * C1)
    return dict(kind='opamp3', type2=False, R1=R1, R2=R2, R3=R3,
                C1=C1, C2=C2, C3=C3)


def opamp_type3_eval(R1, R2, R3, C1, C2, C3):
    """Parts -> realized constants (rad/s)."""
    if C3 == 0.0:  # no input lead branch; retain the finite feedback pole
        return dict(KP=1/(R1*(C1+C2)),wz1=1/(R2*C1),wz2=math.inf,
                    wp1=(C1+C2)/(R2*C1*C2) if C2>0 else math.inf,wp2=math.inf)
    Cs = C1 * C2 / (C1 + C2)
    return dict(KP=1.0 / (R1 * (C1 + C2)),
                wz1=1.0 / (R2 * C1),
                wz2=1.0 / ((R1 + R3) * C3),
                wp1=1.0 / (R2 * Cs),
                wp2=1.0 / (R3 * C3))


# -------------------------------------------------------------- gm-amp III
def gm_type3_solve(KP, wz1, wz2, wp1, wp2, R2, gm=2e-3, R1=None,
                   type2=False):
    """gm-amp type III (TI figure naming).  User chooses R2 (lower divider);
    R1 comes out of wz2/wp2.  For type2 (C1=C3=0) the split is not available,
    so the user must provide R1 instead."""
    if R2 <= 0 or gm <= 0:
        raise ValueError('R2 / gm must be positive')
    if type2:
        if not R1 or R1 <= 0:
            raise ValueError('type II gm compensator needs R1 from the user')
        C2 = gm * R2 / (KP * (R1 + R2))
        R3 = 1.0 / (wz1 * C2)
        return dict(kind='gm3', type2=True, R1=R1, R2=R2, R3=R3,
                    C1=0.0, C2=C2, C3=0.0, gm=gm)
    if wp2 <= wz2:
        raise ValueError('跨导型 (gm) 补偿器的 wz2/fp2 支路物理上只能实现零点低于极点'
                         '——④页目标 boost≤0 (wp2≤wz2) 时无法实现；'
                         '请改用普通运放方案，或在④页重新整定使 boost>0')
    R1 = R2 * (wp2 - wz2) / wz2
    C1 = 1.0 / (wz2 * R1)
    S = gm * R2 / (KP * (R1 + R2))          # C2 + C3
    C2, C3 = _series_split(S, wz1 / wp1)
    R3 = 1.0 / (wz1 * C2)
    return dict(kind='gm3', type2=False, R1=R1, R2=R2, R3=R3,
                C1=C1, C2=C2, C3=C3, gm=gm)


def gm_type3_eval(gm, R1, R2, R3, C1, C2, C3):
    if C1 == 0.0:  # no divider capacitor; retain the finite output pole
        return dict(KP=gm*R2/((C2+C3)*(R1+R2)),wz1=1/(R3*C2),wz2=math.inf,
                    wp1=(C2+C3)/(R3*C2*C3) if C3>0 else math.inf,wp2=math.inf)
    Cs = C2 * C3 / (C2 + C3)
    return dict(KP=gm * R2 / ((C2 + C3) * (R1 + R2)),
                wz1=1.0 / (R3 * C2),
                wz2=1.0 / (R1 * C1),
                wp1=1.0 / (R3 * Cs),
                wp2=(R1 + R2) / (R1 * C1 * R2))


# ------------------------------------------------- TL431 + opto, no fast lane
def tl431_nf_solve(KP, wz1, wz2, wp1, wp2, R1, R_LED, CTR=1.0, Rpullup=20e3,
                   Copto=2e-9, Vref=2.5, Vout=12.0):
    """TL431 type III without fast lane (p.45 figure naming).  User chooses
    R1 (divider upper) and R_LED; everything else is derived.

    Note: fz2 = 1/(2πR1C3) and fp1 = fz2·R1/R3 are independently placeable
    (R3 = R1·fz2/fp1 for ANY fp1 > 0) — no boost>0 constraint here.
    """
    if R1 <= 0 or R_LED <= 0:
        raise ValueError('R1 / R_LED must be positive')
    if wz2 <= 0 or wp1 <= 0:
        raise ValueError('wz2 / wp1 must be positive')
    C3 = 1.0 / (wz2 * R1)
    R3 = 1.0 / (wp1 * C3)              # = R1·wz2/wp1 — any ratio solvable
    C1 = CTR * Rpullup / (KP * R1 * R_LED)
    R2 = 1.0 / (wz1 * C1)
    C2_tot = 1.0 / (wp2 * Rpullup)
    C2 = C2_tot - Copto
    Rlower = R1 * Vref / max(Vout - Vref, 1e-9)
    fp_opto = 1.0 / (2.0 * math.pi * Rpullup * Copto)
    # TL431 / LED bias hint (TND381-D p.15/46): keep ~2 mA total
    R_LED_max = (Vout - 2.5 - 1.0) / 2e-3
    return dict(kind='tl431nf', R1=R1, R2=R2, R3=R3,
                C1=C1, C2=C2, C3=C3, C2_tot=C2_tot,
                R_LED=R_LED, CTR=CTR, Rpullup=Rpullup, Copto=Copto,
                R_lower=Rlower, fp_opto=fp_opto, R_LED_max=R_LED_max,
                Vref=Vref, Vout=Vout)


def tl431_nf_eval(CTR, Rpullup, Copto, R_LED, R1, R2, R3, C1, C2, C3):
    """Parts -> realized constants (rad/s)."""
    if C3==0:
        return dict(KP=CTR*Rpullup/(R_LED*R1*C1),wz1=1/(R2*C1),wz2=math.inf,
                    wp1=1/(Rpullup*(C2+Copto)),wp2=math.inf)
    return dict(KP=CTR * Rpullup / (R_LED * R1 * C1),
                wz1=1.0 / (R2 * C1),
                wz2=1.0 / (R1 * C3),
                wp1=1.0 / (R3 * C3),
                wp2=1.0 / (Rpullup * (C2 + Copto)))


# ----------------------------------------------------- TL431 + opto, fast lane
def tl431_f_solve(KP, wz1, wz2, wp1, wp2, R1, CTR=1.0, Rpullup=20e3,
                  Copto=2e-9, Vref=2.5, Vout=12.0):
    """TL431 type III with fast lane (p.44 figure naming).  User chooses R1
    (divider upper); everything else is derived.

    The R_pz+C_pz branch physically realizes zero-below-pole only
    (fp1/fz2 = 1 + R_LED/R_pz).  When the K-factor targets place the pole at
    or below the zero (boost <= 0, K <= 1), the branch is placed as a
    near-cancelled pair at the geometric mean of the two target frequencies
    (2-octave spread) — the loop then behaves as integrator + fz1 + opto
    pole — and a warning is returned in d['warnings']."""
    if R1 <= 0:
        raise ValueError('R1 must be positive')
    if wz1 <= 0:
        raise ValueError('wz1 must be positive')
    C1 = 1.0 / (wz1 * R1)
    # K-factor integrator gain: KP = CTR*Rpullup/(R_LED*R1*C1)
    R_LED = CTR * Rpullup / (KP * R1 * C1)
    warnings = []
    if wp1 > wz2:
        # normal boost>0 placement
        R_pz = R_LED * wz2 / (wp1 - wz2)
        C_pz = 1.0 / (wp1 * R_pz)
    else:
        # boost <= 0: place the branch as a near-cancelled pair around the
        # geometric mean of the two target corner frequencies.
        wz2e = max(wz2, 1.0)
        wp1e = max(wp1, wz2e * 4.0)          # keep the mean finite/sane
        fx = math.sqrt(wz2e * wp1e)
        rho = 4.0                            # 2-octave spread (mild boost)
        R_pz = R_LED / (rho - 1.0)
        C_pz = 1.0 / ((R_LED + R_pz) * fx / math.sqrt(rho))
        warnings.append(
            '④页目标 boost≤0 (fp1≤fz2): 快车道支路无法实现极点低于零点，'
            'R_pz/C_pz 已作为近似抵消对放在 %.0f Hz / %.0f Hz (环路近似为'
            '积分器+fz1+光耦极点)。如需精确二型补偿请改用无快车道拓扑。'
            % ((fx / math.sqrt(rho)) / (2 * math.pi),
               (fx * math.sqrt(rho)) / (2 * math.pi)))
    C2_tot = 1.0 / (wp2 * Rpullup)
    C2 = C2_tot - Copto
    R_lower = R1 * Vref / max(Vout - Vref, 1e-9)
    out = dict(kind='tl431f', R1=R1, C1=C1, R_pz=R_pz, C_pz=C_pz,
               R_LED=R_LED, CTR=CTR, Rpullup=Rpullup, Copto=Copto,
               C2=C2, C2_tot=C2_tot, R_lower=R_lower,
               Vref=Vref, Vout=Vout)
    if warnings:
        out['warnings'] = warnings
    return out


def tl431_f_eval(CTR, Rpullup, Copto, R_LED, R1, C1, R_pz, C_pz, C2):
    """Parts -> realized constants (rad/s)."""
    if C_pz==0:
        return dict(KP=CTR*Rpullup/(R_LED*R1*C1),wz1=1/(R1*C1),wz2=math.inf,
                    wp1=1/(Rpullup*(C2+Copto)),wp2=math.inf)
    return dict(KP=CTR * Rpullup / (R_LED * R1 * C1),
                wz1=1.0 / (R1 * C1),
                wz2=1.0 / ((R_LED + R_pz) * C_pz),
                wp1=1.0 / (R_pz * C_pz),
                wp2=1.0 / (Rpullup * (C2 + Copto)))
