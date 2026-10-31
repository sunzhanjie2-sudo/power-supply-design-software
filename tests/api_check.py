"""Headless tests for design_api / cli (AI tool-chain interface).

Run:  python tests/api_check.py
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import re as _re  # noqa: E402

import design_api  # noqa: E402
import comp_design as _compd  # noqa: E402

FAILS = []


def check(name, cond, detail=''):
    print(f'[{"OK " if cond else "FAIL"}] {name} {detail}')
    if not cond:
        FAILS.append(name)


SPEC_BUCK = {'topology': 'BUCK', 'V_in': 12, 'V_out': 5, 'P_out': 5,
             'f_sw': 100e3, 'L': 47e-6, 'C_out': 100e-6, 'Rc': 15e-3,
             'Vm': 5.0, 'pm_target': 60.0, 'control_mode': 'Voltage Mode',
             'controller_type': 'auto', 'Rc2': 15e-3, 'cout2_enable': True}
SPEC_FB = {'topology': 'FLYBACK', 'V_in': 12, 'V_out': 12, 'P_out': 5,
           'f_sw': 100e3, 'L': 300e-6, 'C_out': 200e-6, 'N': 3.0,
           'K': 0.95, 'Kc': 1.5, 'dC': 0.1}

# ---- 1. run_design structure ----
r = design_api.run_design(SPEC_BUCK)
check('BUCK report ok', r.get('ok') is True, r.get('error', ''))
need = {'ok', 'spec', 'topology', 'operating_point', 'losses', 'magnetics',
        'stress', 'checks', 'failed_checks', 'warnings'}
check('report has all sections', need.issubset(r.keys()),
      str(need - set(r.keys())))
ids = [c['id'] for c in r['checks']]
for expect in ('L_min', 'C_charge', 'ESR_ripple', 'ripple', 'temp_rise',
               'window_fill', 'phase_margin'):
    check(f'check catalog contains {expect}', expect in ids)
for c in r['checks']:
    if not isinstance(c.get('pass_'), bool):
        check(f'check {c["id"]} pass_ is bool', False, repr(c.get("pass_")))
check('BUCK duty', abs(r['operating_point']['D'] - 5 / (12*r['losses']['eta_guess'])) < 1e-6,
      f"D={r['operating_point']['D']:.4f}")
check('BUCK eta sane', 0.5 < r['losses']['eta'] < 1.0,
      f"eta={r['losses']['eta'] * 100:.1f}%")

# ---- 2. checks detect real design faults ----
r_bad = design_api.run_design(dict(SPEC_BUCK, L=4.7e-6))   # tiny L -> L_min fail
check('L_min check fails for small L', 'L_min' in r_bad['failed_checks'],
      f"failed={r_bad['failed_checks']}")
r_big = design_api.run_design(dict(SPEC_BUCK, C_out=2200e-6, Rc=5e-3))
check('ESR/charge checks pass for healthy C',
      'C_charge' not in r_big['failed_checks']
      and 'ESR_ripple' not in r_big['failed_checks'],
      f"failed={r_big['failed_checks']}")

# ---- 3. v/u spec format accepted ----
r_vu = design_api.run_design(dict(SPEC_BUCK,
                                  L={'v': 47, 'u': 'u'},
                                  C_out={'v': 100, 'u': 'u'}))
check('v/u spec accepted, same eta',
      abs(r_vu['losses']['eta'] - r['losses']['eta']) < 1e-9)

# ---- 4. invalid spec raises with useful message ----
try:
    design_api.run_design({'topology': 'CUCKOO'})
    check('invalid topology raises', False)
except ValueError as e:
    check('invalid topology raises', 'topology' in str(e), str(e)[:60])
try:
    design_api.run_design({'topo': 'BUCK'})
    check('unknown key raises', False)
except ValueError as e:
    check('unknown key raises', 'unknown spec key' in str(e), str(e)[:60])

# ---- 5. flyback report + RCD ----
rf = design_api.run_design(SPEC_FB)
check('FLYBACK report ok', rf.get('ok') is True, rf.get('error', ''))
check('FLYBACK RCD warning present',
      any('RCD' in w for w in rf['warnings']))
check('FLYBACK Vds uses Kc',
      rf['operating_point']['V_sw_max'] > 12 + 1.4 * 3.0 * 1.3,
      f"V_sw={rf['operating_point']['V_sw_max']:.1f} V")

# ---- 6. corner analysis ----
c = design_api.run_corners(SPEC_FB)
corners = c['corners']
check('corner count = 10', len(corners) == 10)
check('no skipped corners', not any(x.get('skipped') for x in corners))
valid = [x for x in corners if not x.get('skipped')]
lo = [x for x in valid if x['V_in'] == c['v_in'][0]]
hi = [x for x in valid if x['V_in'] == c['v_in'][1]]
check('worst I_pk at Vin-min full load',
      max(lo, key=lambda x: x['load_frac'])['I_L_pk'] == c['worst']['max_I_L_pk'])
check('worst eta equals minimum across all corners',
      min(x['eta'] for x in valid) == c['worst']['min_eta'])
# invalid corner skipped: boost with V_out < V_in
cb = design_api.run_corners({'topology': 'BOOST', 'V_in': 4, 'V_out': 5,
                             'P_out': 5, 'f_sw': 100e3, 'L': 22e-6,
                             'C_out': 100e-6}, v_in_min=3.5, v_in_max=5.5)
check('invalid boost corners skipped',
      all(x.get('skipped') for x in cb['corners'] if x['V_in']==5.5)
      and all(not x.get('skipped') for x in cb['corners'] if x['V_in']==3.5), f"{len(cb['corners'])} corners")

# ---- 7. load transient ----
t1 = design_api.load_transient(SPEC_BUCK, di=1.0)
t2 = design_api.load_transient(SPEC_BUCK, di=2.0)
t3 = design_api.load_transient(dict(SPEC_BUCK, C_out=470e-6), di=1.0)
check('dV grows with ΔI', t2['dv_total'] > t1['dv_total'],
      f"{t1['dv_total'] * 1e3:.1f} -> {t2['dv_total'] * 1e3:.1f} mV")
check('dV shrinks with C_out', t3['dv_total'] < t1['dv_cap'] + 1e9
      and t3['dv_cap'] < t1['dv_cap'],
      f"C 100u: {t1['dv_cap'] * 1e3:.1f} mV -> 470u: {t3['dv_cap'] * 1e3:.1f} mV")
check('ESR term = ΔI·ESR', abs(t1['dv_esr'] - 1.0 * (15e-3 * 15e-3 / 30e-3)) < 1e-12,
      f"{t1['dv_esr'] * 1e3:.2f} mV (2x15mΩ parallel)")

# ---- 7b2. fast-lane fallback when boost<=0 (wp1<=wz2, user-reported bug) ----
import math as _m  # noqa: E402
_KP, _wz1 = 1.299e5, 2 * _m.pi * 1e3
_wz2, _wp1 = 2 * _m.pi * 2.4e3, 2 * _m.pi * 1.8e3
d_fb = _compd.tl431_f_solve(
    _KP, _wz1, _wz2, _wp1, 2 * _m.pi * 1.8e5,
    R1=60e3, CTR=1.0, Rpullup=10e3, Copto=2e-9, Vout=5.0)
check('fast-lane boost<=0 does not crash', True)
check('fast-lane fallback returns warning',
      any('boost' in w for w in d_fb.get('warnings', [])),
      (d_fb.get('warnings') or ['<none>'])[0][:60])
ev_fb = _compd.tl431_f_eval(
    d_fb['CTR'], d_fb['Rpullup'], d_fb['Copto'], d_fb['R_LED'],
    d_fb['R1'], d_fb['C1'], d_fb['R_pz'], d_fb['C_pz'], d_fb['C2'])
check('fallback preserves KP/wz1',
      abs(ev_fb['KP'] - _KP) / _KP < 1e-9 and abs(ev_fb['wz1'] - _wz1) / _wz1 < 1e-9)
check('fallback places fz2 below fp1', ev_fb['wp1'] > ev_fb['wz2'],
      f"fz2={ev_fb['wz2'] / _m.pi / 2:.0f} Hz fp1={ev_fb['wp1'] / _m.pi / 2:.0f} Hz")
wm = _re.search(r'([\d.]+) Hz / ([\d.]+) Hz', (d_fb.get('warnings') or [''])[0])
check('warning Hz == realized parts',
      wm is not None
      and abs(float(wm.group(1)) - ev_fb['wz2'] / _m.pi / 2) < 1
      and abs(float(wm.group(2)) - ev_fb['wp1'] / _m.pi / 2) < 1,
      wm.group(0) if wm else 'no match')

# ---- 8. autotune closes the loop ----
a = design_api.autotune_loop(SPEC_BUCK, fc=10e3, pm=60)
r2 = design_api.run_design(dict(SPEC_BUCK, KP=a['KP'], fz1=a['fz1'],
                                fp1=a['fp1'], fz2=a['fz2'], fp2=a['fp2']))
pm_chk = [c for c in r2['checks'] if c['id'] == 'phase_margin'][0]
check('autotune type3', a['comp_type'] == 'type3')
check('autotune achieves target fc ±20 %',
      abs(a['achieved']['fc'] - 10e3) / 10e3 < 0.2,
      f"fc={a['achieved']['fc']:.0f} Hz")
check('post-tune PM check passes', pm_chk['pass_'],
      f"PM={pm_chk['value']:.2f} deg")

print()
if FAILS:
    print(f'{len(FAILS)} FAILED: {FAILS}')
    sys.exit(1)
print('ALL API CHECKS PASSED')
