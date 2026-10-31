"""Headless sanity checks for the design engine (no GUI required).

Run:  python tests/quick_check.py
"""

import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import numpy as np

from power_stage import (DEFAULT_PARAMS, compute_operating_point,)
from waveforms import make_waveforms, fft_analysis
from loss_model import compute_design, efficiency_curve
from plants import BuckConverter, BoostConverter, FlybackConverter
import optimizer as opt
import comp_design as compd

FAILS = []


def check(name, cond, detail=''):
    status = 'OK ' if cond else 'FAIL'
    print(f'[{status}] {name} {detail}')
    if not cond:
        FAILS.append(name)


def gain_at(G, f):
    """|G(j2pi f)| via direct evaluation (avoids control.bode shape quirks)."""
    return abs(G(1j * 2 * np.pi * f))


# ---------------------------------------------------------------- buck
print('== BUCK (12V->5V, 5W, 100kHz, 47uH) ==')
p = dict(DEFAULT_PARAMS)
p.update(topology='BUCK', V_in=12, V_out=5, P_out=5, f_sw=100e3, L=47e-6)
op = compute_operating_point(p)
check('D duty', abs(op['D'] - 5 / (12*p['eta_guess'])) < 1e-6, f"D={op['D']:.4f}")
check('mode CCM', op['mode'] == 'CCM', f"mode={op['mode']}")
dI = (12 - 5/p['eta_guess']) * op['D'] / (100e3 * 47e-6)
check('dI_L', abs(op['dI_L'] - dI) < 1e-9, f"dI={op['dI_L']:.4f} A")
res = compute_design(p)
wf = res['wf']
check('efficiency sane', 0.5 < res['eta'] < 1.0, f"eta={res['eta'] * 100:.1f}%")
check('ripple finite', np.isfinite(wf['ripple_pp']) and wf['ripple_pp'] > 0,
      f"ripple={wf['ripple_pp'] * 1e3:.1f} mV")
fa = fft_analysis(wf['t'], wf['iL'], wf['f_sw'])
check('FFT fundamental at fsw', abs(fa['harmonics'][0][1] - 100e3) < 1e3,
      f"f1={fa['harmonics'][0][1]:.0f} Hz")
check('THD finite', np.isfinite(fa['thd']), f"THD={fa['thd'] * 100:.2f}%")
G = BuckConverter(12, 5, 5, 100e3, 47e-6, 100e-6, 5).get_voltage_mode_transfer_function()
g1k = gain_at(G, 1e3)
check('buck Gvc gain', 20 * np.log10(g1k) > 0, f"|Gvc(1k)|={20 * np.log10(g1k):.1f} dB")

# anti-reverse diodes: losses enter P_total; analytic formulas hold
p_nod = dict(DEFAULT_PARAMS)
p_nod.update(topology='BUCK', V_in=12, V_out=5, P_out=5, f_sw=100e3, L=47e-6,
             d_in_enable=False, d_out_enable=False)
res_off = compute_design(p_nod)
res_on = compute_design(p)
check('anti-rev diode loss added',
      abs((res_on['P_total'] - res_off['P_total'])
          - (res_on['P_din'] + res_on['P_dout'])) < 1e-12,
      f"P_din={res_on['P_din'] * 1e3:.1f} mW P_dout={res_on['P_dout'] * 1e3:.1f} mW")
I_av = float(np.mean(wf['i_in']))
I_rr = float(np.sqrt(np.mean(np.asarray(wf['i_in']) ** 2)))
check('P_din = Vf*Iavg (deprecated Rd ignored)',
      abs(res_on['P_din'] - 0.7 * I_av) < 1e-12)
check('P_dout = Vf*Iout (deprecated Rd ignored)',
      abs(res_on['P_dout']
          - 0.7 * res_on['op']['I_out']) < 1e-12)
check('eta drops with diodes', res_on['eta'] < res_off['eta'],
      f"eta {res_off['eta'] * 100:.2f}% -> {res_on['eta'] * 100:.2f}%")

# DCM check at light load / small L
p_dcm = dict(DEFAULT_PARAMS)
p_dcm.update(topology='BUCK', V_in=12, V_out=5, P_out=5, f_sw=100e3, L=4.7e-6)
op_dcm = compute_operating_point(p_dcm)
check('buck DCM at small L', op_dcm['mode'] == 'DCM', f"mode={op_dcm['mode']} D={op_dcm['D']:.3f}")
# DCM energy balance (Erickson ch.5): average inductor current == I_out
check('buck DCM I_L_avg == I_out',
      abs(op_dcm['I_L_avg'] - op_dcm['I_out']) / op_dcm['I_out'] < 1e-6,
      f"I_L={op_dcm['I_L_avg']:.4f} vs I_out={op_dcm['I_out']:.4f}")

# ---------------------------------------------------------------- boost
print('== BOOST (12V->24V, 12W, 100kHz, 220uH) ==')
p = dict(DEFAULT_PARAMS)
p.update(topology='BOOST', V_in=12, V_out=24, P_out=12, f_sw=100e3, L=220e-6)
op = compute_operating_point(p)
check('boost D', abs(op['D'] - (1-12*p['eta_guess']/24)) < 1e-6, f"D={op['D']:.4f}")
check('boost CCM', op['mode'] == 'CCM', op['mode'])
check('I_L avg', abs(op['I_L_avg'] - 1.0/p['eta_guess']) < 1e-6, f"I_L={op['I_L_avg']:.3f}")
check('RHP zero', op['rhp_zero'] > 0, f"f_rhp={op['rhp_zero']:.0f} Hz")
res = compute_design(p)
check('boost eta sane', 0.5 < res['eta'] < 1, f"eta={res['eta'] * 100:.1f}%")

# DCM check at light load
p2 = dict(p, P_out=0.5)
op2 = compute_operating_point(p2)
check('boost DCM at light load', op2['mode'] == 'DCM', f"mode={op2['mode']} D={op2['D']:.3f}")
# DCM energy balance for boost: 0.5*L*Ipk^2*f == (Vo-Vin)*Io
E_bo = 0.5 * op2['L'] * op2['I_L_pk'] ** 2 * op2['f_sw']
check('boost DCM energy balance',
      abs(E_bo - (op2['V_out_equiv'] - op2['V_in']) * op2['I_out']) < 1e-9,
      f"E={E_bo:.4f} W")
# C_min is capacitance (F); ESR is a separate voltage screening check.
check('boost C_min is charge-only capacitance',
      abs(op['C_min']-op['I_out']*op['D']/(op['f_sw']*p['ripple_target']*op['V_out'])) < 1e-12,
      f"C_min={op['C_min'] * 1e6:.1f} uF")

# ---------------------------------------------------------------- flyback
print('== FLYBACK (12V->5V, 5W, 100kHz, Lm=100uH, N=2.5) ==')
p = dict(DEFAULT_PARAMS)
p.update(topology='FLYBACK', V_in=12, V_out=5, P_out=5, f_sw=100e3, L=100e-6, N=2.5)
op = compute_operating_point(p)
V_ref = 2.5 * 5 / p['eta_guess']
D_exp = V_ref / (12 + V_ref)
check('flyback D', abs(op['D'] - D_exp) < 1e-6, f"D={op['D']:.4f}")
check('flyback Vds > Vin+reflected', op['V_sw_max'] > 12 + V_ref, f"Vds={op['V_sw_max']:.1f} V")
res = compute_design(p)
check('flyback eta sane', 0.5 < res['eta'] < 1, f"eta={res['eta'] * 100:.1f}%")
wf = res['wf']
check('primary current peaks', wf['i_p'].max() > 0, f"i_p pk={wf['i_p'].max():.3f} A")
# DCM energy balance includes the preset aggregate loss budget: Po/eta.
p_fb_dcm = dict(DEFAULT_PARAMS, topology='FLYBACK', V_in=12, V_out=5, P_out=5,
                f_sw=100e3, L=20e-6, N=2.5)
op_fb = compute_operating_point(p_fb_dcm)
E_fb = 0.5 * op_fb['L'] * op_fb['I_L_pk'] ** 2 * op_fb['f_sw']
check('flyback DCM energy balance',
      op_fb['mode'] == 'DCM' and
      abs(E_fb - op_fb['P_in_est']) < 1e-9,
      f"D={op_fb['D']:.4f} Ipk={op_fb['I_L_pk']:.3f} A")
# flyback transformer B_pk must be the true peak flux (saturation check)
from loss_model import magnetics_design
md = magnetics_design(op_fb, p_fb_dcm)
xf = md['transformer']
check('flyback transformer B_pk = L*Ipk/(Np*Ae)',
      xf['ok'] and abs(xf['B_pk'] - op_fb['L'] * op_fb['I_L_pk'] / (xf['Np'] * xf['Ae'])) < 1e-12,
      f"B_pk={xf['B_pk'] * 1e3:.0f} mT")

# ---------------------------------------------------------------- QR flyback
print('== QR-FLYBACK (BCM, variable f_sw) ==')
from power_stage import TOPO_QRFLYBACK, compute_qrflyback_op
from loss_model import recompute_qr_eta
p_qr = dict(DEFAULT_PARAMS)
p_qr.update(topology=TOPO_QRFLYBACK, V_in=90, V_out=12, P_out=24, f_sw=150e3,
            L=400e-6, N=8.0, C_out=470e-6, Coss=200e-12,
            core_choice='auto', core_shape='auto', Np=0, Ns=0, MLT=0,
            d_wire_p=0, d_wire_s=0, n_strand_p=1, n_strand_s=1, Kc=0)
op_qr = compute_operating_point(p_qr)
check('QR mode BCM', op_qr['mode'] == 'BCM', op_qr['mode'])
check('QR f_sw sane range', 20e3 < op_qr['f_sw'] < 250e3, f"f_sw={op_qr['f_sw']:.0f} Hz")
check('QR D+Dp<1 (valley delay present)', op_qr['D'] + op_qr['Dp'] < 1.0,
      f"D+Dp={op_qr['D'] + op_qr['Dp']:.3f}")
# energy balance: 0.5*Lm*Ipk^2*f_sw == P_out/eta_guess
E_qr = 0.5 * op_qr['L'] * op_qr['I_L_pk'] ** 2 * op_qr['f_sw']
check('QR energy balance', abs(E_qr - op_qr['P_out'] / p_qr['eta_guess']) < 1e-9,
      f"E={E_qr:.3f} W")
# classic BCM limit when C_ds -> 0: Ipk = 2*P_in*(1/Vin+1/Vr)
op_qr0 = compute_qrflyback_op(dict(p_qr, Coss=0.0))
Ipk_cl = 2 * (op_qr0['P_out'] / op_qr0['V_in'] * 0 + op_qr0['P_out'] / p_qr['eta_guess']) * (1 / op_qr0['V_in'] + 1 / op_qr0['V_r'])
check('QR no-ring limit = classic BCM Ipk', abs(op_qr0['I_L_pk'] - Ipk_cl) < 1e-9,
      f"Ipk={op_qr0['I_L_pk']:.4f} A")
# frequency depends on input voltage
op_qr_hi = compute_qrflyback_op(dict(p_qr, V_in=265))
check('QR f_sw rises with V_in', op_qr_hi['f_sw'] > op_qr['f_sw'],
      f"{op_qr['f_sw']:.0f} -> {op_qr_hi['f_sw']:.0f} Hz")
# frequency depends on load
op_qr_lo = compute_qrflyback_op(dict(p_qr, P_out=3))
check('QR f_sw rises at light load', op_qr_lo['f_sw'] > op_qr['f_sw'],
      f"{op_qr['f_sw']:.0f} -> {op_qr_lo['f_sw']:.0f} Hz")
# Compatibility entry preserves the preset rather than iterating it.
res_qr = recompute_qr_eta(p_qr)
check('QR eta sane', 0.5 < res_qr['eta'] < 1.0, f"eta={res_qr['eta'] * 100:.1f}%")
wf_qr = res_qr['wf']
check('QR waveforms: i_sw only during T_on', wf_qr['i_sw'].max() > 0 and
      np.all(wf_qr['i_d'][wf_qr['i_sw'] > 0] == 0),
      f"i_p pk={wf_qr['i_p'].max():.2f} A")
check('QR ripple finite', np.isfinite(wf_qr['ripple_pp']),
      f"ripple={wf_qr['ripple_pp'] * 1e3:.1f} mV")

# ---------------------------------------------------------------- Steinmetz convention
print('== Steinmetz coefficient convention (datasheet anchors) ==')
import magnetics as mag
_P87 = mag.core_loss_steinmetz(52.0, 1.25, 2.35, 100e3, 0.2, 1e-6)
check('N87 100kHz/200mT ~ 375 kW/m3', abs(_P87 - 0.3745) / 0.3745 < 0.02,
      f"{_P87 / 1e-6 * 1e-3:.0f} kW/m3")

# ---------------------------------------------------------------- NSE core loss
print('== NSE core loss (Steinmetz Natural Extension, book eq. 3.23-3.25) ==')
_k, _a, _b, _f, _Ve, _dB = 16.9, 1.25, 2.35, 100e3, 1.5e-6, 0.30
# (a) NSE general integral on a sinusoid == classical Steinmetz
_t = np.linspace(0, 1 / _f, 20001, endpoint=False)
_B = 0.20 * np.sin(2 * np.pi * _f * _t)
_P_stein = mag.core_loss_steinmetz(_k, _a, _b, _f, 0.20, _Ve)
_P_nse_sin = mag.core_loss_nse_waveform(_k, _a, _b, _t, _B, _Ve)
check('NSE sine == Steinmetz', abs(_P_nse_sin - _P_stein) / _P_stein < 5e-3,
      f"{_P_nse_sin:.4f} vs {_P_stein:.4f} W")
# (b) closed form (3.25) == general integral for a flyback DCM triangle
_D, _Dp = 0.40, 0.35
_n_on, _n_off = int(_D * 20000), int(_Dp * 20000)
_t_on = np.linspace(0, _D / _f, _n_on, endpoint=False)
_t_off = np.linspace(_D / _f, (_D + _Dp) / _f, _n_off, endpoint=False)
_t_gap = np.linspace((_D + _Dp) / _f, 1 / _f, 20000 - _n_on - _n_off, endpoint=False)
_B_tri = np.concatenate([_dB * _t_on / (_D / _f),
                         _dB - _dB * (_t_off - _D / _f) / (_Dp / _f),
                         np.zeros_like(_t_gap)])
_t_tri = np.concatenate([_t_on, _t_off, _t_gap])
_P_cl = mag.core_loss_nse(_k, _a, _b, _f, _dB, _D, _Dp, _Ve)
_P_gi = mag.core_loss_nse_waveform(_k, _a, _b, _t_tri, _B_tri, _Ve)
check('NSE closed form == general integral', abs(_P_cl - _P_gi) / _P_cl < 5e-3,
      f"{_P_cl:.4f} vs {_P_gi:.4f} W")
# (c) iGSE with duty == NSE closed form for a triangle
_P_ig = mag.core_loss_igse(_k, _a, _b, _f, _dB, _Ve, D_on=_D, D_off=_Dp)
check('iGSE(duty) == NSE triangle', abs(_P_cl - _P_ig) / _P_cl < 5e-3,
      f"{_P_cl:.4f} vs {_P_ig:.4f} W")
# (d) flyback transformer core loss uses the general NSE integral (3.23) on
# the actual B(t); agrees with the closed form (3.25) to numerical-error level
md_fb = magnetics_design(op_fb, p_fb_dcm)
P_nse_ref = mag.core_loss_nse(p_fb_dcm['k_core'], p_fb_dcm['a_core'],
                              p_fb_dcm['b_core'], op_fb['f_sw'],
                              md_fb['transformer']['dB'], op_fb['D'],
                              op_fb['Dp'], md_fb['transformer']['Ve'])
check('flyback transformer P_core uses NSE',
      abs(md_fb['transformer']['P_core'] - P_nse_ref) / P_nse_ref < 1e-3,
      f"P_core={md_fb['transformer']['P_core']:.4f} W "
      f"(closed form {P_nse_ref:.4f} W)")
# (e) NSE integral on a sinusoid == Steinmetz (mathematical property)
op_ind = dict(Ts=1e-5, D=0.45, Dp=0.55, dI_L=3.0, I_L_pk=3.0)
_L, _N, _Ae = 0.2 * 10 * 20e-6 / 3.0, 10, 20e-6        # L*dI/(N*Ae)=0.2 T
_t_i, _B_i = mag.inductor_flux_waveform(op_ind, _L, _N, _Ae)
P_ind_wf = mag.core_loss_nse_waveform(_k, _a, _b, _t_i, _B_i, _Ve)
P_ind_cl = mag.core_loss_igse(_k, _a, _b, _f, 0.2, _Ve, D_on=0.45, D_off=0.55)
check('inductor P_core (NSE integral) == iGSE closed form',
      abs(P_ind_wf - P_ind_cl) / P_ind_cl < 1e-3,
      f"{P_ind_wf:.4f} vs {P_ind_cl:.4f} W")
_t_s, _B_s = mag.sinusoid_flux_waveform(0.15, _f)
P_sin_wf = mag.core_loss_nse_waveform(_k, _a, _b, _t_s, _B_s, _Ve)
P_sin_cl = mag.core_loss_steinmetz(_k, _a, _b, _f, 0.15, _Ve)
check('LLC sinusoid P_core (NSE integral) == Steinmetz',
      abs(P_sin_wf - P_sin_cl) / P_sin_cl < 1e-3,
      f"{P_sin_wf:.4f} vs {P_sin_cl:.4f} W")

# ---------------------------------------------------------------- core DB (2-level)
print('== Two-level core database (shape -> model) ==')
check('core shape list >= 10', len(mag.core_shape_list()) >= 10,
      f"{len(mag.core_shape_list())} shapes")
check('CORE_DB flattened matches shapes',
      set(mag.CORE_DB.keys()) == {m for sh in mag.CORE_SHAPES.values() for m in sh},
      f"{len(mag.CORE_DB)} models")
# shape-restricted auto-select returns a core of that shape
sel = mag.select_core(1.0e-8, shape='PQ')       # Ap = 1e-8 m^4 (realistic)
check('select_core within shape PQ', sel is not None and sel[0].startswith('PQ'),
      f"{sel[0] if sel else 'none'}")
sel2 = mag.select_core(1.0e-8, shape='RM')
check('select_core within shape RM', sel2 is not None and sel2[0].startswith('RM'),
      f"{sel2[0] if sel2 else 'none'}")
# a chosen model overrides shape (engine honours explicit core_choice)
ind = mag.design_inductor(op_fb, dict(p_fb_dcm, core_choice='RM12', core_shape='auto'))
check('explicit core_choice wins', ind['core'] == 'RM12', f"core={ind['core']}")

# ---------------------------------------------------------------- cap ripple
print('== Input/output capacitor ripple current (flat-top Fourier + impedance split) ==')
import capripple as cr
f_c = 100e3
T_c = 1 / f_c
t_c = np.linspace(0, 32 * T_c, 32768, endpoint=False)
D_c = 0.4
iL_c = np.where(np.mod(t_c, T_c) < D_c * T_c, np.mod(t_c, T_c) / (D_c * T_c), 0.0) * 2.0
i_cout_c = iL_c - iL_c.mean()
i_cin_c = np.where(np.mod(t_c, T_c) < D_c * T_c, iL_c * (np.mod(t_c, T_c) / (D_c * T_c)), 0.0) - 0.5 * D_c
# single cap: per-cap total == bank time-domain total
r_cap = cr.capacitor_ripple_analysis(t_c, i_cin_c, i_cout_c, f_c,
                                     [dict(C=10e-6, ESR=15e-3, ESL=5e-9)],
                                     [dict(C=220e-6, ESR=10e-3, ESL=3e-9)])
check('cap single: out total matches bank', abs(r_cap['output']['caps'][0]['total'] - r_cap['total_out']) / r_cap['total_out'] < 0.02,
      f"{r_cap['output']['caps'][0]['total']:.4f} vs {r_cap['total_out']:.4f} A")
check('cap harmonic band contains k-th harmonic', r_cap['output']['labels'][1] == '1f',
      f"bands={r_cap['output']['labels'][:4]}")
# two caps: phase cancel -> sum can exceed bank, and per-cap band-sum == total
r_cap2 = cr.capacitor_ripple_analysis(t_c, i_cin_c, i_cout_c, f_c,
                                      [dict(C=10e-6, ESR=15e-3, ESL=5e-9), dict(C=100e-6, ESR=8e-3, ESL=20e-9)],
                                      [dict(C=220e-6, ESR=10e-3, ESL=3e-9), dict(C=22e-6, ESR=3e-3, ESL=1e-9)])
sum_out = sum(c['total'] for c in r_cap2['output']['caps'])
check('cap two-cap sum >= bank (phase)', sum_out >= r_cap2['total_out'] * 0.9,
      f"sum {sum_out:.3f} A vs bank {r_cap2['total_out']:.3f} A")
for rail in (r_cap2['input'], r_cap2['output']):
    for c in rail['caps']:
        check('cap per-cap band-sum == total', abs(c['total'] - float(np.sqrt(sum(b * b for b in c['bands'])))) < 1e-9,
              f"{c['total']:.3f} A")
# waveforms carry the input-cap ripple current
wfq = wf_dfcm = None
from waveforms import make_waveforms
opw = compute_operating_point(p_fb_dcm)
wfq = make_waveforms(opw)
check('waveforms include i_cin', 'i_cin' in wfq and wfq['i_cin_rms'] > 0,
      f"i_cin_rms={wfq['i_cin_rms']:.3f} A")

# ---------------------------------------------------------------- MOSFET gate-charge loss
print('== MOSFET gate-charge switching loss (spreadsheet reproduction) ==')
from semiconductor import mosfet_loss
op_g = dict(topology='BUCK', f_sw=20e3, I_L_min=10.0, I_L_pk=10.0)
dev_g = dict(Rds_on=0.0032, tr=20e-9, tf=20e-9, Coss=200e-12, Qg=17e-9,
             Vgs=10.0, Vth=1.3, Vgp_on=2.2, Vgp_off=2.2, Qg_th=1.6e-9,
             Qgs=3.1e-9, Qgd=2.3e-9, Rg_drive=0.0, Rs_on=100.0,
             Rs_off=100.0, Rg=1.1, k_sw=1.0/6.0)
loss_g = mosfet_loss(op_g, dev_g, sw_stress=dict(I_rms=10.0*0.5**0.5, V_max=15.0))
# Spreadsheet F26's empty H15 reference is corrected to F15 (internal Rg).
# With k=1/6: Ptr=0.023939316 W, Ptf=0.097171071 W; Pon=0.160 W.
check('MOS conduction loss (Pon)', abs(loss_g['P_cond'] - 0.160) < 1e-3,
      f"P_cond={loss_g['P_cond']:.3f} W")
check('MOS turn-on loss Ptr', abs(loss_g['P_sw_on'] - 0.02393931583513209) < 1e-12,
      f"Ptr={loss_g['P_sw_on']:.4f} W")
check('MOS turn-off loss Ptf', abs(loss_g['P_sw_off'] - 0.0971710706020309) < 1e-12,
      f"Ptf={loss_g['P_sw_off']:.4f} W")
check('MOS Coss loss included', loss_g['P_coss'] > 0,
      f"P_coss={loss_g['P_coss']:.4f} W")
check('MOS gate time t3 ~ 29.8ns', abs(loss_g['t3'] * 1e9 - 29.811538461538458) < 1e-9,
      f"t3={loss_g['t3'] * 1e9:.1f} ns")
for name, ns in [('t1',17.328486162975533),('t2',18.06709320872572),
                 ('t6',105.69545454545454),('t7',88.64668665860727),
                 ('t8',373.29230769230765)]:
    check(f'MOS gate time {name} follows spreadsheet', abs(loss_g[name]*1e9-ns)<1e-9,
          f"{name}={loss_g[name]*1e9:.9f} ns")

# ---------------------------------------------------------------- transformer windings
print('== Transformer winding params (turns / wire dia / parallel strands) ==')
p_w = dict(DEFAULT_PARAMS, topology='FLYBACK', V_in=12, V_out=5, P_out=5,
           f_sw=100e3, L=100e-6, N=2.5)
op_w = compute_operating_point(p_w)
# explicit turns + diameters + strands
xf_u = mag.design_transformer(op_w, dict(p_w, Np=40, Ns=8, d_wire_p=0.25e-3,
                                         d_wire_s=0.6e-3, n_strand_p=2,
                                         n_strand_s=1),
                              op_w['I_sw_rms'], op_w['I_d_rms'], n_ratio=op_w['N'])
check('xfr uses explicit turns', xf_u['Np'] == 40 and xf_u['Ns'] == 8,
      f"Np={xf_u['Np']} Ns={xf_u['Ns']}")
check('xfr uses explicit wire dia + strands',
      abs(xf_u['d_wire_p'] - 0.25e-3) < 1e-9 and xf_u['n_strand_p'] == 2 and
      abs(xf_u['d_wire_s'] - 0.6e-3) < 1e-9,
      f"dp={xf_u['d_wire_p'] * 1e3:.2f}mm x{xf_u['n_strand_p']}")
# strand count divides the DC resistance (2 strands -> ~half R of 1 strand)
xf_1 = mag.design_transformer(op_w, dict(p_w, Np=40, Ns=8, d_wire_p=0.25e-3,
                                         d_wire_s=0.6e-3, n_strand_p=1,
                                         n_strand_s=1),
                              op_w['I_sw_rms'], op_w['I_d_rms'], n_ratio=op_w['N'])
check('xfr 2 strands halves R_dc', abs(xf_u['R_dc_p'] - xf_1['R_dc_p'] / 2) / (xf_1['R_dc_p'] / 2) < 1e-9,
      f"R_p 2-strand {xf_u['R_dc_p'] * 1e3:.1f} mOhm vs 1-strand {xf_1['R_dc_p'] * 1e3:.1f} mOhm")
# auto turns (0) still works
xf_a = mag.design_transformer(op_w, dict(p_w, Np=0, Ns=0, d_wire_p=0.0, d_wire_s=0.0,
                                         n_strand_p=1, n_strand_s=1),
                              op_w['I_sw_rms'], op_w['I_d_rms'], n_ratio=op_w['N'])
check('xfr auto turns when 0', xf_a['Np'] > 0 and xf_a['Ns'] > 0,
      f"Np={xf_a['Np']} Ns={xf_a['Ns']}")

# ---------------------------------------------------------------- MLT input
print('== User MLT (mean length per turn) -> R_dc / copper loss ==')
# user MLT overrides the core MLT and R_dc = rho*MLT*N/(strand*A)
xf_m = mag.design_transformer(op_w, dict(p_w, Np=40, Ns=8, d_wire_p=0.25e-3,
                                         d_wire_s=0.6e-3, n_strand_p=2,
                                         n_strand_s=1, MLT=0.08),
                              op_w['I_sw_rms'], op_w['I_d_rms'], n_ratio=op_w['N'])
A_p_m = np.pi * (xf_m['d_wire_p'] / 2) ** 2
R_p_exp = p_w['rho'] * 0.08 * xf_m['Np'] / (xf_m['n_strand_p'] * A_p_m)
check('user MLT is used', abs(xf_m['MLT'] - 0.08) < 1e-12,
      f"MLT={xf_m['MLT'] * 1e3:.1f} mm")
check('R_dc = rho*MLT*N/(strand*A)', abs(xf_m['R_dc_p'] - R_p_exp) < 1e-12,
      f"R_p={xf_m['R_dc_p'] * 1e3:.2f} mOhm")
# plant: flyback voltage mode should divide by Vm
G = FlybackConverter(12, 5, 5, 100e3, 100e-6, 100e-6, 5, 2.5).get_voltage_mode_transfer_function()
check('flyback Gvc (Vm divided)', gain_at(G, 1e3) < 1e3, f"|Gvc|={gain_at(G, 1e3):.2f}")

# ---------------------------------------------------------------- K-factor tuning
print('== K-factor auto-tune ==')
from loop_tuning import kfactor_tune, evaluate_loop
from plants import BuckConverter, BoostConverter, Compensator3P3Z, Compensator2P2Z

for name, Gvc, fc_d, pm_exp in [
    ('buck VM', BuckConverter(12, 5, 5, 100e3, 47e-6, 100e-6, 5)
     .get_voltage_mode_transfer_function(), 10e3, 60.0),
    ('buck PCM', BuckConverter(12, 5, 5, 100e3, 47e-6, 100e-6, 5)
     .get_peak_current_mode_transfer_function(), 10e3, 55.0),
    ('boost VM fc below RHP zero', BoostConverter(12, 24, 12, 100e3, 220e-6, 100e-6, 5)
     .get_voltage_mode_transfer_function(), 1.5e3, 60.0),
]:
    r = kfactor_tune(Gvc, fc=fc_d, pm_target=pm_exp, comp_type='auto')
    if r['comp_type'] == 'type3':
        Gc = Compensator3P3Z(r['KP'], r['fz1'], r['fz2'], r['fp1'],
                             r['fp2']).get_transfer_function()
    else:
        Gc = Compensator2P2Z(r['KP'], r['fz1'], r['fp1']).get_transfer_function()
    fc_act, pm_act = evaluate_loop(Gvc, Gc)
    ok_fc = fc_act is not None and abs(np.log10(fc_act / fc_d)) < 0.1
    ok_pm = pm_act is not None and abs(pm_act - pm_exp) < 6.0
    check(f'kfactor {name} fc~{fc_d:.0f}', ok_fc,
          f"fc={fc_act:.0f} Hz (type {r['comp_type']}, boost {r['boost']:.0f} deg)")
    check(f'kfactor {name} PM~{pm_exp:.0f}', ok_pm, f"PM={pm_act:.1f} deg")

# boost with fc above the RHP zero is infeasible -> must be flagged
r_bad = kfactor_tune(BoostConverter(12, 24, 12, 100e3, 220e-6, 100e-6, 5)
                     .get_voltage_mode_transfer_function(), fc=10e3,
                     pm_target=60.0, comp_type='auto')
check('boost fc=10k flagged infeasible', r_bad['feasible'] is False,
      f"boost_required={r_bad['boost_required']:.0f} deg")

# ---------------------------------------------------------------- efficiency curves
print('== efficiency curves ==')
for topo in ('BUCK', 'BOOST', 'FLYBACK'):
    p = dict(DEFAULT_PARAMS)
    if topo == 'BUCK':
        p.update(topology='BUCK', V_in=12, V_out=5, P_out=5, f_sw=100e3, L=4.7e-6)
    elif topo == 'BOOST':
        p.update(topology='BOOST', V_in=12, V_out=24, P_out=12, f_sw=100e3, L=22e-6)
    else:
        p.update(topology='FLYBACK', V_in=12, V_out=5, P_out=5, f_sw=100e3, L=100e-6, N=2.5)
    fracs, etas, _ = efficiency_curve(p, n_pts=8)
    finite = np.isfinite(etas)
    check(f'{topo} eta curve', finite.all() and etas[finite].max() < 1 and etas[finite].min() > 0,
          f"eta range {np.nanmin(etas) * 100:.1f}..{np.nanmax(etas) * 100:.1f}%")

# ---------------------------------------------------------------- optimisation
print('== optimisation ==')
p = dict(DEFAULT_PARAMS)
p.update(topology='BUCK', V_in=12, V_out=5, P_out=5, f_sw=100e3, L=4.7e-6)
vals, etas = opt.sweep_efficiency(p, 'f_sw', 50e3, 300e3, n=15)
check('sweep returns array', len(vals) == 15 and np.isfinite(etas).any())
found = opt.find_target(vals, etas, 0.90)
print(f'   f_sw for 90% target: {found}')
r = opt.optimize_efficiency(p, ['f_sw', 'L'], [(30e3, 300e3), (2e-6, 20e-6)], load_frac=1.0)
check('DE optimisation', r['ok'] and 0 < r['eta'] < 1, f"eta={r['eta'] * 100:.2f}% best={r['best']}")

# ---------------------------------- flyback PCM loop: Rs / A_sense effect
print('== Flyback PCM loop model (Rs / A_sense sensitivity) ==')
FB = FlybackConverter

def _fb_g(Rs_, A=1.0, ma=0.0):
    c = FB(15, 30, 900 / 28.0, 250e3, 8e-6, 340e-6, 5, 0.5, Rs=Rs_,
           Vf=0.7, A_sense=A, ma=ma)
    c.mode = 'CCM'
    c.D_actual = c.D
    return c.get_peak_current_mode_transfer_function()


_w = 1j * 2 * np.pi * 2e3
m_ref = abs(_fb_g(0.165)(_w))
m_2rs = abs(_fb_g(0.33)(_w))
m_A10 = abs(_fb_g(0.165, A=10.0)(_w))
check('flyback PCM: Rs x2 -> |Gvc| halves',
      abs(m_ref / m_2rs - 2) < 1e-6, f'{m_ref:.4g} / {m_2rs:.4g} = {m_ref/m_2rs:.4f}')
check('flyback PCM: A_sense x10 -> |Gvc| /10',
      abs(m_ref / m_A10 - 10) < 1e-6,
      f'{m_ref:.4g} / {m_A10:.4g} = {m_ref/m_A10:.3f}')
check('flyback PCM: Fm finite without slope comp at D>0.5',
      np.isfinite(m_ref) and m_ref > 0)

# ------------------ buck VM / PCM plants vs the reference implementation
print('== Buck plants vs reference formulas ==')


def _cmp_plant(name, G_ours, G_ref, freqs=(500.0, 2e3, 10e3, 50e3)):
    ok = True
    for f in freqs:
        wv = 1j * 2 * np.pi * f
        go, gr = G_ours(wv), G_ref(wv)
        ok = ok and abs(go - gr) <= 1e-9 * abs(gr)
    check(name, ok)


conv = BuckConverter(12, 5, 5, 100e3, 4.7e-6, 100e-6, 5)
_cmp_plant('buck VM plant == reference formula',
           conv.get_voltage_mode_transfer_function(),
           lambda wv: 12 / 5 / (1 + wv * 4.7e-6 / 5
                                + wv ** 2 * 4.7e-6 * 100e-6))

_D = 3.3 / 12
_M1, _M2 = 12 / 3.3e-6, 3.3 / 3.3e-6
_Fm = 200e3 / 1.0 / ((_M1 - _M2) / 2)
_Fv = (1 - 2 * _D) * 1.0 / (200e3 * 2 * 3.3e-6)
_Fi = 1.0


def _ref_pcm(wv):
    delta = 1 + wv * 3.3e-6 / 1.5 + wv ** 2 * 3.3e-6 * 350e-6
    Gvd = 3.3 / _D / delta
    Gid = 3.3 * (1 + wv * 1.5 * 350e-6) / _D / 1.5 / delta
    return _Fm * Gvd / (1 + _Fm * (_Fi * Gid + _Fv * Gvd))


conv = BuckConverter(12, 3.3, 3.3 ** 2 / 1.5, 200e3, 3.3e-6, 350e-6, 5,
                     Rs=1.0)
conv.mode = 'CCM'
conv.D_actual = conv.D
G_pcm = conv.get_peak_current_mode_transfer_function()
_cmp_plant('buck PCM plant == reference formula', G_pcm, _ref_pcm)
m1 = abs(G_pcm(1j * 2 * np.pi * 2e3))
conv2 = BuckConverter(12, 3.3, 3.3 ** 2 / 1.5, 200e3, 3.3e-6, 350e-6, 5,
                      Rs=2.0)
conv2.mode = 'CCM'
conv2.D_actual = conv2.D
m2 = abs(conv2.get_peak_current_mode_transfer_function()(1j * 2 * np.pi * 2e3))
check('buck PCM: Rs x2 -> |Gvc| halves', abs(m1 / m2 - 2) < 1e-9,
      f'{m1:.4g}/{m2:.4g}')

# ------------------------------------------------- tab 8 compensation RC
print('== Compensation network RC back-solve (tab 8) ==')
KP, fz1, fz2, fp1, fp2 = 1.299e5, 1e3, 1e4, 1e5, 5e5
w = [2 * np.pi * f for f in (fz1, fz2, fp1, fp2)]


def _rt(name, solve_d, ev, targets, keys=('KP', 'wz1', 'wz2', 'wp1', 'wp2')):
    ok = True
    for k, tgt in zip(keys, targets):
        got = ev.get(k, np.nan)
        good = (np.isinf(tgt) and np.isinf(got)) or \
               (np.isfinite(tgt) and abs(got - tgt) <= 1e-9 * max(abs(tgt), 1.0))
        ok = ok and good
    check(name, ok,
          ' '.join(f'{k}={ev.get(k, float("nan")):.4g}' for k in keys))


# op-amp type III (figure "Ⅲ补偿" naming) + type II special case
d = compd.opamp_type3_solve(KP, *w, R1=10e3)
ev = compd.opamp_type3_eval(d['R1'], d['R2'], d['R3'], d['C1'], d['C2'], d['C3'])
_rt('opamp3 round trip', d, ev, [KP] + w)
d2 = compd.opamp_type3_solve(KP, w[0], 1.0, w[2], 1.0, R1=10e3, type2=True)
ev2 = compd.opamp_type3_eval(d2['R1'], d2['R2'], d2['R3'], d2['C1'], d2['C2'], d2['C3'])
check('opamp type2: C2=C3=0, KP/fz1 match',
      d2['C2'] == 0 and d2['C3'] == 0 and abs(ev2['KP'] - KP) < 1e-6 * KP
      and abs(ev2['wz1'] - w[0]) < 1e-9 * w[0])
# strict s-domain check: G(jw) from the RC network == K-factor form
def _zf(wv, R2, C1, C2):
    zc2 = 1.0 / (1j * wv * C2) if C2 > 0 else complex(np.inf)
    zc1r = R2 + 1.0 / (1j * wv * C1)
    if np.isinf(zc2):
        return zc1r
    return zc2 * zc1r / (zc2 + zc1r)


def _zi(wv, R1, R3, C3):
    zc3r = R3 + 1.0 / (1j * wv * C3) if C3 > 0 else complex(np.inf)
    if np.isinf(zc3r):
        return complex(R1)
    return R1 * zc3r / (R1 + zc3r)


ok = True
for wv in (2 * np.pi * 300.0, 2 * np.pi * 3e3, 2 * np.pi * 30e3,
           2 * np.pi * 300e3):
    g_net = _zf(wv, d['R2'], d['C1'], d['C2']) / _zi(wv, d['R1'], d['R3'], d['C3'])
    g_kf = KP * (1 + 1j * wv / w[0]) * (1 + 1j * wv / w[1]) / \
        (1j * wv * (1 + 1j * wv / w[2]) * (1 + 1j * wv / w[3]))
    ok = ok and abs(g_net - g_kf) <= 1e-9 * abs(g_kf)
check('opamp3 s-domain G(jw) == K-factor form (4 freqs)', ok)

# gm type III (TI figure naming: R1/R2/R3 + C1/C2/C3)
d = compd.gm_type3_solve(KP, *w, R2=10e3, gm=2e-3)
ev = compd.gm_type3_eval(d['gm'], d['R1'], d['R2'], d['R3'],
                         d['C1'], d['C2'], d['C3'])
_rt('gm3 round trip', d, ev, [KP] + w)
d = compd.gm_type3_solve(KP, w[0], 1.0, w[2], 1.0, R2=10e3, gm=2e-3,
                         R1=100e3, type2=True)
ev = compd.gm_type3_eval(d['gm'], d['R1'], d['R2'], d['R3'],
                         d['C1'], d['C2'], d['C3'])
check('gm type2: C1=C3=0, KP/fz1 match',
      d['C1'] == 0 and d['C3'] == 0 and abs(ev['KP'] - KP) < 1e-6 * KP
      and abs(ev['wz1'] - w[0]) < 1e-9 * w[0])

# TL431 + opto, no fast lane (p.45 naming/formulas).  fp2 target must sit
# above the bare opto pole so C2 > 0: opto pole 3.98 kHz -> fp2 = 15 kHz
d = compd.tl431_nf_solve(KP, w[0], w[1], w[2], wp2=2 * np.pi * 15e3,
                         R1=40e3, R_LED=1e3, CTR=1.0, Rpullup=20e3,
                         Copto=2e-9, Vout=12.0)
ev = compd.tl431_nf_eval(d['CTR'], d['Rpullup'], d['Copto'], d['R_LED'],
                         d['R1'], d['R2'], d['R3'], d['C1'], d['C2'], d['C3'])
_rt('tl431nf round trip', d, ev, [KP] + w[:1] + [w[1], w[2], 2 * np.pi * 15e3],
    keys=('KP', 'wz1', 'wz2', 'wp1', 'wp2'))
check('tl431nf divider / bias hints sane',
      d['R_lower'] > 0 and d['fp_opto'] > 0 and d['R_LED_max'] > d['R_LED'],
      f"R_lower={d['R_lower']/1e3:.2f}k fp_opto={d['fp_opto']/1e3:.1f}k "
      f"R2={d['R2']/1e3:.1f}k C1={d['C1']*1e9:.2f}n")

# TL431 + opto, fast lane (p.44 naming/formulas); C1 pairs with divider R1
_fp2f = 1.0 / (2 * np.pi * 20e3 * 3e-9)
d = compd.tl431_f_solve(KP, w[0], 2 * np.pi * 1.2e3, 2 * np.pi * 15e3,
                        2 * np.pi * _fp2f,
                        R1=40e3, CTR=1.0, Rpullup=20e3, Copto=2e-9, Vout=12.0)
ev = compd.tl431_f_eval(d['CTR'], d['Rpullup'], d['Copto'], d['R_LED'],
                        d['R1'], d['C1'], d['R_pz'], d['C_pz'], d['C2'])
_rt('tl431f round trip', d, ev, [KP, w[0], 2 * np.pi * 1.2e3, 2 * np.pi * 15e3],
    keys=('KP', 'wz1', 'wz2', 'wp1'))
check('tl431f opto pole = target fp2',
      abs(d['Copto'] + d['C2'] - 3e-9) < 1e-15,
      f"C2={d['C2'] * 1e9:.2f} nF, C1={d['C1'] * 1e9:.2f} nF")
# KP formula per the reference figure: KP = Rpullup*CTR/R_LED/R1/C1 (both
# fast-lane and no-fast-lane TL431 type 3)
check('tl431f KP = Rpullup*CTR/R_LED/R1/C1',
      abs(ev['KP'] - 20e3 * 1.0 / d['R_LED'] / 40e3 / d['C1']) < 1e-6,
      f"R_LED={d['R_LED']:.1f} ohm (sane for a 1-mA LED bias chain)")
check('tl431nf KP = Rpullup*CTR/R_LED/R1/C1',
      abs(compd.tl431_nf_eval(
          1.0, 20e3, 2e-9, 1e3, 40e3, 41.3e3, 4e3,
          3.85e-9, 3.3e-9, 0.4e-9)['KP']
          - 20e3 * 1.0 / 1e3 / 40e3 / 3.85e-9) < 1e-6)

print()
print('=' * 50)
if FAILS:
    print(f'{len(FAILS)} FAILED: {FAILS}')
    sys.exit(1)
print('ALL CHECKS PASSED')
