"""Power-stage DC operating point, component design and device stress for
Buck / Boost / Buck-Boost / Flyback / QR-Flyback switching converters.

All quantities are SI.  The small-signal models live in plants.py; this module
is the *steady-state* design engine (duty, CCM/DCM, currents, voltages).

Key references
--------------
- R. W. Erickson, D. Maksimović, "Fundamentals of Power Electronics", 3rd ed.
  (Buck/Boost/Buck-Boost/Flyback CCM & DCM, RHP zero, ripple).
"""

import numpy as np

# ----------------------------------------------------------------------------
# Topology names (kept in sync with the GUI)
# ----------------------------------------------------------------------------
TOPO_BUCK = 'BUCK'
TOPO_BOOST = 'BOOST'
TOPO_BUCKBOOST = 'BUCK-BOOST'
TOPO_FLYBACK = 'FLYBACK'
TOPO_QRFLYBACK = 'QR-FLYBACK'
TOPO_ACFFORWARD = 'ACF-FORWARD'
TOPOLOGIES = [TOPO_BUCK, TOPO_BOOST, TOPO_BUCKBOOST, TOPO_FLYBACK, TOPO_QRFLYBACK,
              TOPO_ACFFORWARD]

# Default parameters (SI).  The GUI reads this table to build entry widgets,
# so it is the single source of truth for parameter names / defaults.
DEFAULT_PARAMS = {
    # --- specifications ------------------------------------------------
    'topology': TOPO_BUCK,
    'control_mode': 'Voltage Mode',
    'controller_type': 'auto',     # legacy mode default / type2 / type3
    'V_in': 12.0, 'V_out': 5.0, 'P_out': 5.0, 'P_out_min': 0.0, 'f_sw': 100e3,
    # --- power stage ----------------------------------------------------
    'L': 4.7e-6, 'C_out': 100e-6, 'Rc': 15e-3, 'Rs': 10e-3, 'Vm': 5.0,
    'N': 3.0,                       # transformer turns ratio (flyback Np/Ns)
    'Lm_forward': 220e-6,           # ACF transformer Lm; L is output choke
    'C_clamp': 47e-9, 'forward_d_max': 0.70, 'forward_dead_time': 80e-9,
    'Rds_aux': 100e-3, 'Qg_aux': 10e-9, 'Coss_aux': 200e-12,
    'ESR_clamp': 30e-3,             # clamp capacitor ESR
    'core_choice_L': 'auto',        # ACF choke selected independently from T
    'Vf': 0.7,                      # legacy working-point drop, config compatibility
    'ESL': 5e-9,                    # output-capacitor ESL (ripple spikes)
    'core_choice': 'auto',          # magnetics core: 'auto' or a CORE_DB name
    'custom_core': {}, 'custom_core_L': {},  # effective geometry, SI; inactive drafts retained
    'ripple_target': 0.01,          # output ripple design target (rel. of Vout)
    'ring_margin': 0.30,            # switching-node ringing allowance (stress)
    'eta_guess': 0.93,              # editable design assumption, ALL topologies
    # --- power devices ---------------------------------------------------
    'Rds_on': 50e-3, 'Vf_diode': 0.7, 'Rd_diode': 0.,  # deprecated Rd keys: JSON compatibility only
    'tr': 20e-9, 'tf': 20e-9, 'Coss': 200e-12, 'Qg': 10e-9,
    # gate-charge switching-loss model (data-sheet parameters)
    'Vth': 2.5, 'Vgp_on': 4.5, 'Vgp_off': 4.5, 'gfs': 0.,
    'mos_miller_mode': 'auto', 'mos_miller_curve': {}, 'mos_curve_vds': 0., 'diode_curves': {},
      'mos_charge_mode':'manual', 'mos_charge_curve':{}, 'mos_manual_events':{},
    'device_curve_settings': {},
    'component_management': {},  # identity/ratings/policy; not electrical model inputs
    'spice_config': {},         # independent transient/export settings
    'parasitic_config': {},     # unified optional parasitic inputs, SI
    'Qg_th': 1.5e-9, 'Qgs': 2.5e-9, 'Qgd': 3.0e-9,
    'Rg_drive': 2.0, 'Rs_on': 4.7, 'Rs_off': 4.7, 'Rg': 1.5,
    'k_sw': 0.25,                     # 0.25 inductive / 0.167 resistive
    'Qrr': 0.0,                     # diode reverse-recovery charge (0 = off)
    'Vgs': 10.0,
    # --- current-sense chain (peak-current-mode loop, flyback etc.) -------
    'A_sense': 1.0,                 # CSA gain: some chips amplify the sense
    'ma_slope': 0.0,                # slope compensation, A/s (primary L)

    # --- magnetics --------------------------------------------------------
    'core_material': 'DMR44', 'k_core': 27.49, 'a_core': 1.456, 'b_core': 2.246,
    'mu_r': 0., 'le_core': 0.,     # le_core is accepted for old files; le always derives from Ve/Ae
    'MLT': 0.0,                            # mean length per turn (m, 0 = auto)
    'Np': 0, 'Ns': 0,                       # transformer turns (0 = auto)
    'd_wire_p': 0.0, 'd_wire_s': 0.0,        # winding wire dia (m, 0 = auto)
    'n_strand_p': 1, 'n_strand_s': 1,        # parallel strands (并绕数)
    'parallel_wires_p': 1, 'parallel_wires_s': 1,  # complete identical wires in parallel
    'Bmax': 0.30, 'J': 4.0e6, 'Ku': 0.30, 'rho': 1.72e-8,
    'Bsat': 0.40,                  # saturation flux density (saturation check)
    'h_conv': 10.0,                # thermal convection coefficient W/(m^2 K)
    'Rth_transformer': 100.0,      # user T-to-ambient thermal resistance K/W (initial assumption)
    'temp_rise_limit': 40.0,       # one review threshold shared by GUI/API/Word
    # --- input / output capacitor bank (parallel caps, ripple analysis) ---
    'input_capacitors': None, 'output_capacitors': None,
    'Cin1': 10e-6, 'Rcin1': 15e-3, 'ESLin1': 5e-9,   # input cap 1
    'Cin2': 10e-6, 'Rcin2': 15e-3, 'ESLin2': 5e-9,   # input cap 2 (if enabled)
    'cin2_enable': True,           # use a 2nd parallel input capacitor (default on)
    'C_out2': 100e-6, 'Rc2': 15e-3, 'ESL2': 5e-9,    # output cap 2 (if enabled)
    'cout2_enable': True,          # use a 2nd parallel output capacitor (default on)
    # --- controller (loop tab) ---------------------------------------------
    'KP': 100.0, 'fz1': 1000.0, 'fz2': 10000.0, 'fp1': 100000.0, 'fp2': 500000.0,
    # --- anti-reverse (blocking) diodes ------------------------------------
    # Series protection diodes: one at the input (carries the pulsed source
    # current i_in), one at the output (after the output cap bank, carries the
    # DC load current).  Their conduction losses enter the efficiency via the
    # loss model; the forward drops are NOT subtracted from V_in/V_out in the
    # operating point (first-order treatment, same as the sense resistor).
    'd_in_enable': True, 'Vf_din': 0.7, 'Rd_din': 0.,
    'd_out_enable': True, 'Vf_dout': 0.7, 'Rd_dout': 0.,
    # --- optimisation --------------------------------------------------------
    'target_eta': 0.92, 'load_frac': 1.0,
    'sweep_var': 'f_sw', 'sweep_min': 50e3, 'sweep_max': 500e3, 'sweep_n': 41,
}

# Ship the user's 40 W CCM flyback as the numerical AND GUI startup default.
# Keep the built-in table above as the schema/fallback for absent optional keys.
from config_io import read_default_config, decode_config
DEFAULT_PARAMS.update(decode_config(read_default_config()))
# The startup example is explicitly loaded by the UI. Its device identity,
# curve-source policy and explicit capacitor lists must not become defaults
# for unrelated legacy files that use scalar caps or pre-hub curve modes.
DEFAULT_PARAMS.update(component_management={}, device_curve_settings={},
                      mos_miller_curve={}, mos_charge_curve={}, diode_curves={},
                      mos_manual_events={}, mos_miller_mode='auto', mos_charge_mode='manual',
                      input_capacitors=None, output_capacitors=None)
from inductor_selection import DEFAULTS as INDUCTOR_DEFAULTS
DEFAULT_PARAMS.update(INDUCTOR_DEFAULTS)
from mp6005 import DEFAULTS as PSR_DEFAULTS
DEFAULT_PARAMS.update(PSR_DEFAULTS)
DEFAULT_PARAMS.update(outputs=[],feedback_mode='SSR',feedback_output=1,
                      coupling_config=dict(enabled=False, k=[], dcr=[]))
DEFAULT_PARAMS['engineering_acceptance'] = {}


# ----------------------------------------------------------------------------
# Operating points
# ----------------------------------------------------------------------------
def validate_design_inputs(p):
    """Reject invalid numerical inputs consistently before making a snapshot."""
    from inductor_selection import validate as validate_inductor, purchased, DESIGN_FIELDS
    validate_inductor(p)
    from custom_cores import validate_selected_cores
    validate_selected_cores(p)
    if p['topology'] in (TOPO_FLYBACK, TOPO_QRFLYBACK, TOPO_ACFFORWARD):
        from transformer_gap import validate_inputs
        validate_inputs(p)
        from parallel_wires import count
        count(p,'p');count(p,'s')
    from parasitics import normalize
    normalize(p.get('parasitic_config'))
    if 'V_in_min' in p or 'V_in_max' in p:
        lo, hi = p.get('V_in_min', p['V_in']), p.get('V_in_max', p['V_in'])
        if not (np.isfinite(lo) and np.isfinite(hi) and 0 < lo <= hi):
            raise ValueError('输入电压范围必须满足 0 < Vin min ≤ Vin max，且为有限数值')
    if p.get('input_voltage_case', 'min') not in ('min', 'max'):
        raise ValueError('显示输入工况必须为 Vin min 或 Vin max')
    coupling = p.get('coupling_config', {})
    if not isinstance(coupling, dict) or not isinstance(coupling.get('enabled', False), bool):
        raise ValueError('coupling_config 必须为参数字典，enabled 必须为布尔值')
    for key, value in p.items():
        if isinstance(value, (int, float)) and not isinstance(value, bool) and not np.isfinite(value):
            raise ValueError(f'{key} must be finite')
    positive = ['V_in','V_out','P_out','f_sw','L','C_out','Cin1','Vm','A_sense',
                'Bmax','Bsat','J','Ku']
    if purchased(p):
        positive = [key for key in positive if key not in DESIGN_FIELDS]
    positive += ['Rth_transformer'] if p['topology'] in (TOPO_FLYBACK, TOPO_QRFLYBACK, TOPO_ACFFORWARD) else []
    if p['topology'] not in (TOPO_FLYBACK, TOPO_QRFLYBACK) and not purchased(p):
        positive += ['h_conv']
    if p.get('cout2_enable'): positive.append('C_out2')
    if p.get('cin2_enable'): positive.append('Cin2')
    if p.get('topology') in ('FLYBACK','QR-FLYBACK','ACF-FORWARD'): positive.append('N')
    if p.get('control_mode') == 'Peak Current Mode': positive.append('Rs')
    for key in positive:
        if key in p and p[key] <= 0:
            raise ValueError(f'{key} must be positive')
    nonnegative = ['Rc','Rc2','ESL','ESL2','Rcin1','Rcin2','ESLin1','ESLin2',
                   'Rds_on','Rds_aux','Rs','rho','Vf','Vf_diode','Rd_diode','Qrr',
                   'Coss','Qg','temp_rise_limit','ripple_target']
    for key in nonnegative:
        if key in p and p[key] < 0:
            raise ValueError(f'{key} must be nonnegative')
    eta = float(p.get('eta_guess', DEFAULT_PARAMS['eta_guess']))
    if not np.isfinite(eta) or not 0 < eta <= 1:
        raise ValueError('预设效率 eta_guess 必须满足 0 < η ≤ 1（例如 0.93）')


def _with_efficiency(p, solver):
    """Energy-equivalent loss burden, not a detailed nonideal circuit model.

    U=Vo/eta and Pcore=Po/eta preserve Io, volt-seconds and charge balance.
    eta includes the aggregate rectifier loss; adding Vf here would double
    count its design budget. Real device drops still enter final losses.
    Keep this assumption fixed; never replace it with the calculated eta.
    """
    validate_design_inputs(p)
    eta = float(p.get('eta_guess', DEFAULT_PARAMS['eta_guess']))
    vo, po = float(p['V_out']), float(p['P_out'])
    effective = dict(p, V_out=vo / eta, P_out=po / eta, Vf=0.0, eta_guess=1.0)
    op = solver(effective)
    op.update(V_out_equiv=op['V_out'], R_equiv=op['R'],
              V_out=vo, P_out=po, R=vo**2/po, I_out=po/vo,
              eta_guess=eta, P_in_est=po/eta, I_in_est=po/eta/p['V_in'],
              P_loss_budget=po*(1/eta-1), Vf=p.get('Vf', .7),
              efficiency_model='equivalent_output_burden')
    # C_min is constrained by the REAL output-ripple specification, not U.
    op['C_min'] /= eta
    if op['topology'] in (TOPO_FLYBACK, TOPO_QRFLYBACK):
        op['V_r'] = op['N'] * op['V_out_equiv']
    return op


def compute_operating_point(p):
    from capacitor_banks import normalize
    from isolated_outputs import selected_params,output_specs
    p=normalize(p)
    op=_compute_operating_point(p)
    op['output_capacitors']=selected_params(p).get('output_capacitors')
    for child,rail in zip(op.get('output_ops',[]),output_specs(p)):
        child['output_capacitors']=rail.get('output_capacitors')
    return op


def _compute_operating_point(p):
    """Compute the steady-state operating point for the selected topology.

    p: parameter dict (SI).  Returns an 'op' dict consumed by the waveform,
    stress, magnetics and loss modules.
    """
    from parasitics import effective_parameters
    p = effective_parameters(p)
    validate_design_inputs(p)
    from nonisolated import is_enabled
    if is_enabled(p):
        from nonisolated import solve, effective
        q=effective(p)
        return solve(q,compute_nonllc_op(q))
    if p['topology']==TOPO_ACFFORWARD and p.get('coupling_config',{}).get('enabled'):
        from acf_periodic import solve_forward
        nominal=compute_operating_point(dict(p,coupling_config=dict(enabled=False),_acf_predesign=True))
        return solve_forward(p,nominal)
    if p.get('coupling_config', {}).get('enabled', False) and p['topology'] != TOPO_ACFFORWARD:
        # Obtain design estimates without recursively entering the circuit
        # solver.  Its solved currents, not nominal power weights, then feed
        # every waveform, loss and stress consumer.
        from coupled_flyback import solve_coupled_flyback
        from flyback_clamp import attach_clamp
        nominal = dict(p, coupling_config=dict(enabled=False))
        if p['topology']==TOPO_QRFLYBACK:
            from qr_coupled import solve_coupled_qr
            solved = solve_coupled_qr(p, compute_operating_point(nominal))
        else:
            solved = solve_coupled_flyback(p, compute_operating_point(nominal))
        clamp_params = dict(p,K=1.) if solved.get('coupled_model',{}).get('ideal_fallback') else p
        return attach_clamp(solved, clamp_params)
    from isolated_outputs import output_specs, compute_isolated_op
    output_specs(p)
    if p.get('outputs') or p.get('feedback_mode','SSR')!='SSR':
        op = compute_isolated_op(p)
    elif p['topology'] == TOPO_QRFLYBACK:
        op = compute_qrflyback_op(p)
    elif p['topology'] == TOPO_ACFFORWARD:
        from active_clamp import compute_forward_op
        op = compute_forward_op(p)
    else:
        op = compute_nonllc_op(p)
    from voltage_nodes import attach_nodes
    if op.get('outputs'):
        from isolated_outputs import selected_params
        attach_nodes(op,selected_params(p))
    else:attach_nodes(op,p)
    from flyback_clamp import attach_clamp
    return attach_clamp(op, p)


def compute_nonllc_op(p):
    from flyback_clamp import attach_clamp
    return attach_clamp(_with_efficiency(p, _compute_nonllc_op), p)


def _compute_nonllc_op(p):
    topo = p['topology']
    V_in, V_out = p['V_in'], p['V_out']
    P_out, f_sw = p['P_out'], p['f_sw']
    L, C_out, Rc, Rs = p['L'], p['C_out'], p['Rc'], p['Rs']
    ring = p.get('ring_margin', 0.30)

    if P_out <= 0 or f_sw <= 0 or L <= 0:
        raise ValueError('P_out, f_sw and L must be positive')
    if topo == 'BUCK' and V_out >= V_in:
        raise ValueError(f'Buck requires V_in > V_out (got {V_in} / {V_out})')
    if topo == 'BOOST' and V_out <= V_in:
        raise ValueError(f'Boost requires V_out > V_in (got {V_in} / {V_out})')

    Ts = 1.0 / f_sw
    R = V_out ** 2 / max(P_out, 1e-9)
    I_out = P_out / max(V_out, 1e-9)
    Vf = p.get('Vf', 0.7)
    N = p.get('N', 1.0)

    op = dict(topology=topo, V_in=V_in, V_out=V_out, P_out=P_out, f_sw=f_sw,
              Ts=Ts, R=R, I_out=I_out, L=L, C_out=C_out, Rc=Rc, Rs=Rs, N=N,
              Vf=Vf, ring_margin=ring)

    if topo == TOPO_BUCK:
        D = V_out / max(V_in, 1e-9)
        dI = (V_in - V_out) * D / (f_sw * L)
        I_bound = 0.5 * dI                      # CCM boundary average current
        mode = 'CCM' if I_out >= I_bound else 'DCM'
        if mode == 'CCM':
            I_L = I_out
            I_pk, I_min = I_L + dI / 2, I_L - dI / 2
            D2 = 1.0 - D
        else:
            # DCM: I_out = 0.5*(Vin-Vo)*D^2*T*Vin/(L*Vo)  (Erickson ch.5)
            D = np.sqrt(2.0 * I_out * L * V_out * f_sw
                        / (V_in * (V_in - V_out) + 1e-30))
            I_pk = (V_in - V_out) * D / (f_sw * L)
            D2 = (V_in - V_out) * D / V_out      # diode conduction duty
            I_L = 0.5 * I_pk * (D + D2)
            dI = I_pk
            I_min = 0.0
        Dp = D2                                  # off-time duty (CCM: 1-D)
        I_L_rms = _tri_rms(I_pk, I_min, D + Dp)
        I_sw_rms = _tri_rms(I_pk, I_min, D)
        I_d_rms = _tri_rms(I_pk, I_min, Dp)
        I_d_avg = I_out
        V_sw = V_in * (1.0 + ring)
        V_d = V_in
        rhp_zero = np.inf
        # CCM-based minimum inductance (independent of the operating mode)
        D_ccm = V_out / max(V_in, 1e-9)
        L_min = (V_in - V_out) * D_ccm / (2.0 * f_sw * I_out) * 1.5
        # Farads only. ESR ripple is a separate voltage check, not capacitance.
        C_min = dI / (8.0 * f_sw * p.get('ripple_target', 0.01) * V_out)
        pwr_factor = 1.0                      # I_L is the inductor/load current

    elif topo == TOPO_BOOST:
        D = 1.0 - V_in / max(V_out, 1e-9)
        Dp = 1.0 - D
        dI = V_in * D / (f_sw * L)
        I_L = I_out / Dp
        I_bound = 0.5 * dI
        mode = 'CCM' if I_L >= I_bound else 'DCM'
        if mode == 'CCM':
            I_pk, I_min = I_L + dI / 2, I_L - dI / 2
        else:
            M = V_out / max(V_in, 1e-9)
            D = np.sqrt(L * ((2.0 * M - 1.0) ** 2 - 1.0) / (2.0 * R * Ts + 1e-30))
            I_pk = V_in * D * Ts / L
            Dp = 2.0 * I_out / max(I_pk, 1e-30)     # diode conduction duty
            I_L = 0.5 * I_pk * (D + Dp)
            dI = I_pk
            I_min = 0.0
        I_L_rms = _tri_rms(I_pk, I_min, D + Dp)
        I_sw_rms = _tri_rms(I_pk, I_min, D)
        I_d_rms = _tri_rms(I_pk, I_min, Dp)
        I_d_avg = I_out
        V_sw = V_out * (1.0 + ring)
        V_d = V_out
        # CCM boost right-half-plane zero (rad/s -> Hz).  DCM has no RHP zero.
        rhp_zero = (Dp ** 2 * R / L / (2 * np.pi)) if mode == 'CCM' else np.inf
        D_ccm = 1.0 - V_in / max(V_out, 1e-9)
        L_min = V_in * D_ccm * (1.0 - D_ccm) / (2.0 * f_sw * I_out) * 1.5
        # charge ripple (I_out*D/f/C) + ESR ripple (I_pk*Rc)
        _dv = p.get('ripple_target', 0.01) * V_out
        C_min = I_out * D / (f_sw * _dv)
        pwr_factor = 1.0

    elif topo == TOPO_BUCKBOOST:
        D = V_out / max(V_in + V_out, 1e-9)
        Dp = 1.0 - D
        dI = V_in * D / (f_sw * L)
        I_L = I_out / Dp
        I_bound = 0.5 * dI
        mode = 'CCM' if I_L >= I_bound else 'DCM'
        if mode == 'CCM':
            I_pk, I_min = I_L + dI / 2, I_L - dI / 2
        else:
            M = V_out / max(V_in, 1e-9)
            D = M * np.sqrt(2.0 * L / (R * Ts + 1e-30))
            I_pk = V_in * D * Ts / L
            Dp = 2.0 * I_out / max(I_pk, 1e-30)
            I_L = 0.5 * I_pk * (D + Dp)
            dI = I_pk
            I_min = 0.0
        I_L_rms = _tri_rms(I_pk, I_min, D + Dp)
        I_sw_rms = _tri_rms(I_pk, I_min, D)
        I_d_rms = _tri_rms(I_pk, I_min, Dp)
        I_d_avg = I_out
        V_sw = (V_in + V_out) * (1.0 + ring)
        V_d = V_in + V_out
        # CCM buck-boost right-half-plane zero (rad/s -> Hz).  DCM has none.
        rhp_zero = (Dp ** 2 * R / (D * L) / (2 * np.pi)) if mode == 'CCM' else np.inf
        D_ccm = V_out / max(V_in + V_out, 1e-9)
        L_min = V_in * D_ccm / (2.0 * f_sw * I_out / max(1.0 - D_ccm, 1e-9)) * 1.5
        _dv = p.get('ripple_target', 0.01) * V_out
        C_min = I_out * D / (f_sw * _dv)
        pwr_factor = 1.0

    elif topo == TOPO_FLYBACK:
        D = N * (V_out + Vf) / max(V_in + N * (V_out + Vf), 1e-9)
        Dp = 1.0 - D
        I_p_avg = P_out / max(V_in * D, 1e-30)
        dI = V_in * D / (f_sw * L)
        I_pk = I_p_avg + dI / 2.0
        I_min = I_p_avg - dI / 2.0
        if I_min < 0:                       # DCM
            mode = 'DCM'
            # energy balance: 0.5*Lm*Ipk^2*f = (Vo+Vf)*Io  (Erickson ch.5)
            D = np.sqrt(2.0 * (V_out + Vf) * I_out * L * f_sw) / max(V_in, 1e-9)
            I_pk = V_in * D * Ts / L
            I_s_pk = N * I_pk
            Dp = 2.0 * I_out / max(I_s_pk, 1e-30)
            dI = I_pk
            I_min = 0.0
        else:
            mode = 'CCM'
            I_s_pk = N * I_pk
        I_s_min = N * I_min
        I_p_rms = _tri_rms(I_pk, I_min, D)
        I_s_rms = _tri_rms(I_s_pk, I_s_min, Dp)
        V_ref = N * (V_out + Vf)
        # RCD (RC) clamp sets the drain turn-off peak when the user chose a
        # clamp ratio Kc > 1:  V_sw_peak = V_in + Kc * V_reflect.  Otherwise
        # No generic ring allowance is added on top of an explicit clamp.
        Kc = p.get('Kc', 0.0)
        if Kc and Kc > 1.0:
            V_sw = V_in + Kc * V_ref
        else:
            V_sw = V_in + V_ref  # unspecified clamp: ideal plateau only
        V_d = V_out + V_in / N   # excludes parasitic spikes
        # CCM flyback right-half-plane zero (in Hz).  Only CCM has it; DCM has
        # no RHP zero.  n = Np/Ns (the turns ratio entered in the GUI):
        #   f_RHPZ = Vin*n*(1-D)/(2*pi*Lp*Io)
        # The secondary-referred inductance is Lp/n^2, NOT Lp*n^2.
        # This is the same finite zero as the shared small-signal factory.
        if mode == 'CCM':
            rhp_zero = V_in * N * (1.0 - D) / (2.0 * np.pi * L * I_out)
        else:
            rhp_zero = np.inf
        D_ccm = N * (V_out + Vf) / max(V_in + N * (V_out + Vf), 1e-9)
        I_p_ccm = P_out / max(V_in * D_ccm, 1e-30)
        L_min = V_in * D_ccm / (f_sw * 0.4 * I_p_ccm) * 1.5
        # charge ripple (I_out*D/f/C) + ESR ripple (I_s_pk*Rc)
        _dv = p.get('ripple_target', 0.01) * V_out
        C_min = I_out * D / (f_sw * _dv)
        # alias the switch/diode currents of the generic interface
        I_sw_rms, I_d_rms = I_p_rms, I_s_rms
        I_L_rms = I_p_rms
        I_d_avg = I_out
        pwr_factor = 1.0
    else:
        raise ValueError('unknown topology %r' % topo)

    op.update(dict(
        D=D, Dp=Dp, mode=mode,
        I_L_avg=I_L if topo != TOPO_FLYBACK else (I_pk + I_min) / 2,
        dI_L=dI, I_L_pk=I_pk, I_L_min=I_min,
        I_L_rms=I_L_rms,
        I_sw_rms=I_sw_rms, I_sw_avg=(I_pk + I_min) / 2.0 * D, I_sw_pk=I_pk,
        V_sw_max=V_sw,
        I_d_rms=I_d_rms, I_d_avg=I_d_avg, I_d_pk=I_pk * (N if topo == TOPO_FLYBACK else 1),
        V_d_max=V_d,
        rhp_zero=rhp_zero,
        L_min=L_min, C_min=C_min,
        ESL=p.get('ESL', 0.0),
        C_out2=p.get('C_out2', p['C_out']), Rc2=p.get('Rc2', p['Rc']),
        ESL2=p.get('ESL2', p.get('ESL', 0.0)),
        cout2_enable=bool(p.get('cout2_enable', False)),
        tr=p.get('tr', 20e-9), tf=p.get('tf', 20e-9),
        pwr_factor=pwr_factor,
    ))
    return op

def compute_qrflyback_op(p):
    from flyback_clamp import attach_clamp
    return attach_clamp(_with_efficiency(p, _compute_qrflyback_op), p)


def _compute_qrflyback_op(p):
    """Quasi-resonant (valley-switching) flyback operating point.

    A QR flyback always operates in BCM / transition mode: the primary current
    ramps from zero to I_pk during T_on, the magnetising energy is fully
    transferred to the secondary during T_demag, and the switch is turned on
    again when the drain voltage rings down to the (first) valley, after a
    resonant delay T_ring = pi*sqrt(Lm*C_ds).  The switching frequency is
    therefore NOT fixed - it depends on V_in, V_out, turns ratio N, Lm, power
    and efficiency:

        T_on    = Lm*I_pk / V_in
        T_demag = Lm*I_pk / (N*(V_out+Vf))          V_r = N*(V_out+Vf)
        T_ring  = pi*sqrt(Lm*C_ds)                  (first valley)
        f_sw    = 1 / (T_on + T_demag + T_ring)
        P_in    = 0.5*Lm*I_pk^2 * f_sw              -> solves I_pk for P_in

    References: R. Erickson ch.20 (resonant switching); Infineon application
    note "Quasi-resonant and fixed-frequency flyback comparison"; ON Semi
    AND8127 (design equations).  The p['f_sw'] entry is used only as the
    frequency *limit* f_max for the design check.
    """
    topo = TOPO_QRFLYBACK
    V_in, V_out = p['V_in'], p['V_out']
    P_out, f_max = p['P_out'], p['f_sw']
    L, C_out, Rc, Rs = p['L'], p['C_out'], p['Rc'], p['Rs']
    ring = p.get('ring_margin', 0.30)
    N = p.get('N', 1.0)
    Vf = p.get('Vf', 0.7)
    C_ds = p.get('Coss', 200e-12)          # drain-source capacitance (valley ring)
    if p.get('parasitic_config'):
        from parasitics import resolved
        C_ds += resolved(p,1)['cw_primary']
    eta = p.get('eta_guess', 0.93)

    if P_out <= 0 or V_in <= 0 or L <= 0 or N <= 0:
        raise ValueError('QR flyback: P_out, V_in, L, N must be positive')

    V_r = N * (V_out + Vf)                 # reflected output voltage
    P_in = P_out / max(eta, 1e-3)
    T_ring = float(np.pi * np.sqrt(L * C_ds))
    a = L * (1.0 / V_in + 1.0 / V_r)
    # 0.5*L*Ipk^2 = P_in*(a*Ipk + T_ring)  ->  quadratic in Ipk
    b = P_in * a
    I_pk = (b + np.sqrt(b * b + 2.0 * L * P_in * T_ring)) / L
    I_pk = float(I_pk)

    T_on = L * I_pk / V_in
    T_demag = L * I_pk / V_r
    T_sw = T_on + T_demag + T_ring
    f_sw = 1.0 / T_sw
    D = T_on / T_sw
    Dp = T_demag / T_sw

    I_s_pk = N * I_pk
    I_p_avg = P_in / V_in                  # average primary current
    I_p_rms = _tri_rms(I_pk, 0.0, D)
    I_s_rms = _tri_rms(I_s_pk, 0.0, Dp)
    I_sw_rms = I_p_rms
    I_d_rms = I_s_rms
    I_out = P_out / V_out
    I_d_avg = I_out

    # QR flyback: RCD clamp ratio Kc > 1 sets the drain turn-off peak
    # (V_in + Kc*V_r); no clamp means only the ideal plateau is known.
    Kc = p.get('Kc', 0.0)
    if Kc and Kc > 1.0:
        V_sw = V_in + Kc * V_r
    else:
        V_sw = V_in + V_r
    V_d = V_out + V_in / N  # excludes parasitic spikes
    R = V_out ** 2 / max(P_out, 1e-9)
    # Quasi-resonant (BCM / transition-mode) flyback, like DCM, has NO
    # right-half-plane zero: the primary current reaches zero each cycle and
    # the energy is fully transferred, so the small-signal behaviour is
    # DCM-like.  (The RHP zero is a CCM-only phenomenon.)
    rhp_zero = np.inf

    _dv = p.get('ripple_target', 0.01) * V_out
    C_min = I_out * D / (f_sw * _dv)

    return dict(
        topology=topo, V_in=V_in, V_out=V_out, P_out=P_out, f_sw=f_sw,
        Ts=T_sw, R=R, I_out=I_out,
        L=L, C_out=C_out, Rc=Rc, Rs=Rs, N=N, Vf=Vf, ring_margin=ring,
        D=D, Dp=Dp, mode='BCM',
        T_on=T_on, T_demag=T_demag, T_ring=T_ring, I_pk=I_pk,
        V_r=V_r, f_max=f_max,
        I_L_avg=I_p_avg, dI_L=I_pk, I_L_pk=I_pk, I_L_min=0.0,
        I_L_rms=I_p_rms,
        I_sw_rms=I_sw_rms, I_sw_avg=0.5 * I_pk * D, I_sw_pk=I_pk,
        V_sw_max=V_sw,
        I_d_rms=I_d_rms, I_d_avg=I_d_avg, I_d_pk=I_s_pk,
        V_d_max=V_d,
        rhp_zero=rhp_zero,
        L_min=0.0, C_min=C_min,
        ESL=p.get('ESL', 0.0),
        C_out2=p.get('C_out2', p['C_out']), Rc2=p.get('Rc2', p['Rc']),
        ESL2=p.get('ESL2', p.get('ESL', 0.0)),
        cout2_enable=bool(p.get('cout2_enable', False)),
        tr=p.get('tr', 20e-9), tf=p.get('tf', 20e-9),
        pwr_factor=1.0,
    )




def _tri_rms(peak, valley, duty):
    """RMS of a triangle wave segment (peak..valley) active for `duty` of T."""
    duty = max(0.0, min(duty, 1.0))
    return float(np.sqrt(((peak ** 2 + peak * valley + valley ** 2) / 3.0) * duty))


# ----------------------------------------------------------------------------
# Auto-design (recommended component values)
# ----------------------------------------------------------------------------
def design_power_stage(p):
    """Recommend power-stage components (L, C_out, N) for the given
    specification.  Returns a dict of recommended parameter values."""
    rec = {}
    op = compute_operating_point(p)
    rec['L'] = op['L_min']
    rec['C_out'] = op['C_min']
    if p['topology'] == TOPO_FLYBACK:
        rec['N'] = max(1.0, p['V_in'] / op['V_out_equiv'] * 0.9)
    return rec


def fmt_eng(x, unit=''):
    """Format with engineering prefix for display."""
    x = float(x)
    if not np.isfinite(x):
        return ('inf' if x > 0 else '-inf') + unit
    if x == 0:
        return '0' + unit
    pref = ['p', 'n', 'u', 'm', '', 'k', 'M', 'G']
    exp = int(np.floor(np.log10(abs(x)) / 3))
    exp = max(-4, min(3, exp))
    return f'{x / 10 ** (3 * exp):.3g}{pref[exp + 4]}{unit}'
