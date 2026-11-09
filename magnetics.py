"""Magnetic component design: core selection (area-product), turns, air gap,
core loss (Steinmetz / NSE / iGSE) and copper loss (DC + skin effect).

Core-loss models (all share the editable k/alpha/beta, f in kHz):
  - Steinmetz  : sinusoidal flux;
  - NSE        : Natural Steinmetz Extension for square-wave/PWM drive
                 (flyback & QR-flyback transformers), book eq. (3.23)-(3.25);
  - iGSE       : triangular flux with DC bias (filter inductors), duty
                 corrected so it equals NSE for a triangle.

References
----------
- Steinmetz equation and iGSE: J. Reinert, A. Brockmeyer, R. W. De Doncker,
  "Calculation of losses in ferro- and ferrimagnetic materials based on the
  modified Steinmetz equation", IEEE Trans. Ind. Appl., 2001.
- NSE: R. W. Erickson, D. Maksimovic, "Fundamentals of Power Electronics",
  3rd ed. (section on ferrite core loss under non-sinusoidal voltage,
  eqs. (3.21)-(3.25), Natural Steinmetz Extension).
- Magnetics Inc. core-loss application note (units: mW/cm^3, kHz, mT/T).
- Area-product method: R. Erickson / standard magnetics design texts.

Core data below are *typical* published values — verify with the
manufacturer datasheet for a real design.
"""

import numpy as np
from custom_cores import CUSTOM_CORE, is_custom, validate_geometry, geometry_snapshot

# ----------------------------------------------------------------------------
# Core database: 2-level directory, shape -> model.  Ae (m^2), Ve (m^3),
# window area Wa (m^2), MLT (m).
#
# Standard MnZn-ferrite designations (IEC / DMEGC-compatible): EE, EI, EF,
# EFD, EPC, EP, ER, EER, ETD, PQ, RM, PM, PT, toroid (T), UU.  Values are
# *typical* published dimensions (matching the international core sizes used
# by DMEGC / TDK / EPCOS / Ferroxcube) — always verify against the core
# manufacturer's datasheet before a final design.  The GUI offers a two-level
# picker: pick the SHAPE first, then the MODEL (or leave the model on 'auto'
# to auto-select the smallest core of that shape).
# ----------------------------------------------------------------------------
CORE_SHAPES = {
    'EE': {
        'EE13': dict(Ae=17.1e-6, Ve=1.14e-6, Wa=12.6e-6, MLT=27e-3),
        'EE16': dict(Ae=20.1e-6, Ve=1.15e-6, Wa=17.4e-6, MLT=30e-3),
        'EE19': dict(Ae=23.1e-6, Ve=1.52e-6, Wa=23.4e-6, MLT=34e-3),
        'EE22': dict(Ae=41.7e-6, Ve=2.40e-6, Wa=26.0e-6, MLT=42e-3),
        'EE25': dict(Ae=40.0e-6, Ve=3.00e-6, Wa=50.0e-6, MLT=45e-3),
        'EE28': dict(Ae=84.5e-6, Ve=5.00e-6, Wa=62.0e-6, MLT=50e-3),
        'EE30': dict(Ae=109e-6,  Ve=6.60e-6, Wa=79.0e-6, MLT=59e-3),
        'EE33': dict(Ae=119e-6,  Ve=8.00e-6, Wa=84.0e-6, MLT=64e-3),
        'EE35': dict(Ae=98.4e-6, Ve=8.90e-6, Wa=100e-6,  MLT=62e-3),
        'EE40': dict(Ae=127e-6,  Ve=11.6e-6, Wa=153e-6,  MLT=76e-3),
        'EE42': dict(Ae=177e-6,  Ve=19.8e-6, Wa=165e-6,  MLT=90e-3),
        'EE50': dict(Ae=226e-6,  Ve=22.7e-6, Wa=252e-6,  MLT=96e-3),
        'EE55': dict(Ae=354e-6,  Ve=31.7e-6, Wa=352e-6,  MLT=112e-3),
    },
    'EI': {
        'EI22': dict(Ae=41.7e-6, Ve=2.40e-6, Wa=26.0e-6, MLT=42e-3),
        'EI25': dict(Ae=40.0e-6, Ve=3.00e-6, Wa=50.0e-6, MLT=45e-3),
        'EI30': dict(Ae=109e-6,  Ve=6.60e-6, Wa=79.0e-6, MLT=59e-3),
        'EI40': dict(Ae=127e-6,  Ve=11.6e-6, Wa=153e-6, MLT=76e-3),
    },
    'EF': {
        'EF12.6': dict(Ae=12.6e-6, Ve=0.60e-6, Wa=12.0e-6, MLT=26e-3),
        'EF16':   dict(Ae=20.0e-6, Ve=1.10e-6, Wa=18.0e-6, MLT=30e-3),
        'EF20':   dict(Ae=33.0e-6, Ve=1.53e-6, Wa=33.0e-6, MLT=42e-3),
        'EF25':   dict(Ae=52.5e-6, Ve=3.20e-6, Wa=55.0e-6, MLT=50e-3),
        'EF30':   dict(Ae=61.0e-6, Ve=4.20e-6, Wa=60.0e-6, MLT=56e-3),
    },
    'EFD': {
        'EFD15': dict(Ae=15.0e-6, Ve=0.50e-6, Wa=14.0e-6, MLT=28e-3),
        'EFD20': dict(Ae=31.0e-6, Ve=1.40e-6, Wa=24.0e-6, MLT=40e-3),
        'EFD25': dict(Ae=58.0e-6, Ve=2.80e-6, Wa=44.0e-6, MLT=50e-3),
        'EFD30': dict(Ae=69.0e-6, Ve=4.20e-6, Wa=58.0e-6, MLT=58e-3),
    },
    'EPC': {
        'EPC13': dict(Ae=10.6e-6, Ve=0.32e-6, Wa=12.0e-6, MLT=24e-3),
        'EPC17': dict(Ae=22.1e-6, Ve=0.70e-6, Wa=20.0e-6, MLT=32e-3),
        'EPC25': dict(Ae=44.8e-6, Ve=2.00e-6, Wa=30.0e-6, MLT=42e-3),
    },
    'EP': {
        'EP7':  dict(Ae=14.5e-6, Ve=0.50e-6, Wa=10.0e-6, MLT=22e-3),
        'EP10': dict(Ae=30.0e-6, Ve=1.10e-6, Wa=20.0e-6, MLT=28e-3),
        'EP13': dict(Ae=57.0e-6, Ve=2.40e-6, Wa=28.0e-6, MLT=34e-3),
    },
    'ER': {
        'ER28': dict(Ae=81.5e-6, Ve=8.20e-6, Wa=67.0e-6, MLT=56e-3),
        'ER35': dict(Ae=107e-6,  Ve=12.0e-6, Wa=95.0e-6, MLT=66e-3),
    },
    'EER': {
        'EER28L': dict(Ae=81.5e-6, Ve=8.70e-6, Wa=70.0e-6, MLT=56e-3),
        'EER40':  dict(Ae=155e-6,  Ve=21.0e-6, Wa=130e-6, MLT=80e-3),
    },
    'ETD': {
        'ETD29': dict(Ae=76.0e-6, Ve=5.50e-6, Wa=71.0e-6, MLT=51e-3),
        'ETD34': dict(Ae=97.1e-6, Ve=7.60e-6, Wa=87.0e-6, MLT=58e-3),
        'ETD39': dict(Ae=125e-6,  Ve=11.5e-6, Wa=120e-6, MLT=66e-3),
        'ETD44': dict(Ae=173e-6,  Ve=18.0e-6, Wa=146e-6, MLT=78e-3),
        'ETD49': dict(Ae=213e-6,  Ve=24.3e-6, Wa=198e-6, MLT=88e-3),
        'ETD54': dict(Ae=282e-6,  Ve=36.7e-6, Wa=240e-6, MLT=110e-3),
        'ETD59': dict(Ae=368e-6,  Ve=51.0e-6, Wa=300e-6, MLT=125e-3),
    },
    'PQ': {
        # PQ{width}-{height}: Ae is fixed by the core family (centre-post
        # cross-section).  Ve of the full-height core is the DMEGC catalogue
        # value (PQ20-20 = 2814.80 mm^3 = 2.8148e-6 m^3); the short-height
        # variants (-16/-17) carry Ve scaled by the height ratio from the
        # full-height core of the same family (estimate — verify with the
        # datasheet before a real design).
        'PQ20-16': dict(Ae=62.0e-6,  Ve=2.252e-6, Wa=24.0e-6, MLT=35e-3),
        'PQ20-17': dict(Ae=62.0e-6,  Ve=2.393e-6, Wa=25.5e-6, MLT=37e-3),
        'PQ20-20': dict(Ae=62.0e-6,  Ve=2.8148e-6, Wa=30.0e-6, MLT=44e-3),
        'PQ26-20': dict(Ae=119e-6,   Ve=3.52e-6, Wa=40.0e-6, MLT=45e-3),
        'PQ26-25': dict(Ae=119e-6,   Ve=4.40e-6, Wa=50.0e-6, MLT=56e-3),
        'PQ32-25': dict(Ae=170e-6,   Ve=6.67e-6, Wa=72.5e-6, MLT=57e-3),
        'PQ32-30': dict(Ae=170e-6,   Ve=8.00e-6, Wa=87.0e-6, MLT=68e-3),
        'PQ35-35': dict(Ae=196e-6,   Ve=11.6e-6, Wa=100e-6, MLT=72e-3),
        'PQ40-40': dict(Ae=201e-6,   Ve=11.2e-6, Wa=116e-6, MLT=80e-3),
        'PQ50-50': dict(Ae=328e-6,   Ve=22.3e-6, Wa=196e-6, MLT=102e-3),
    },
    'RM': {
        'RM6':  dict(Ae=37.0e-6, Ve=1.10e-6, Wa=22.0e-6, MLT=30e-3),
        'RM8':  dict(Ae=64.0e-6, Ve=1.90e-6, Wa=30.0e-6, MLT=43e-3),
        'RM10': dict(Ae=98.0e-6, Ve=4.30e-6, Wa=48.0e-6, MLT=52e-3),
        'RM12': dict(Ae=146e-6,  Ve=8.20e-6, Wa=75.0e-6, MLT=65e-3),
        'RM14': dict(Ae=198e-6,  Ve=11.8e-6, Wa=100e-6, MLT=70e-3),
    },
    'PM': {
        'PM50/39': dict(Ae=303e-6, Ve=28.0e-6, Wa=200e-6, MLT=110e-3),
        'PM62/49': dict(Ae=345e-6, Ve=45.0e-6, Wa=260e-6, MLT=130e-3),
    },
    'PT': {
        'PT18': dict(Ae=52.0e-6, Ve=1.60e-6, Wa=30.0e-6, MLT=40e-3),
        'PT22': dict(Ae=113e-6,  Ve=3.70e-6, Wa=45.0e-6, MLT=48e-3),
    },
    'T': {   # toroid (round) cores
        'T25x15x10': dict(Ae=50.0e-6,  Ve=3.14e-6, Wa=176.7e-6, MLT=62.8e-3),
        'T36x23x15': dict(Ae=97.5e-6,  Ve=9.03e-6, Wa=415.5e-6, MLT=92.7e-3),
        'T58x37x20': dict(Ae=210e-6,   Ve=31.3e-6, Wa=1075e-6, MLT=149e-3),
    },
    'UU': {
        'UU9.8':  dict(Ae=9.0e-6,  Ve=0.20e-6, Wa=12.0e-6, MLT=30e-3),
        'UU10.5': dict(Ae=15.0e-6, Ve=0.40e-6, Wa=18.0e-6, MLT=34e-3),
    },
}

# flattened database (backwards compatible with the single-level API)
CORE_DB = {model: data
           for _shape, models in CORE_SHAPES.items()
           for model, data in models.items()}
CORE_SHAPE_ORDER = list(CORE_SHAPES.keys())


def core_shape_list():
    """Display order of the core shapes (first level of the picker)."""
    return list(CORE_SHAPE_ORDER)


def core_model_list(shape):
    """Model names available for a given shape (second level of the picker)."""
    return list(CORE_SHAPES.get(shape, {}).keys())

# Steinmetz coefficients Pv[mW/cm^3] = k * f[kHz]^a * B[T]^b.
# k is calibrated to the typical 100 C datasheet core-loss points:
#   N87  ~375 kW/m3 @ 100 kHz / 200 mT
#   PC40 ~600 kW/m3 @ 100 kHz / 200 mT
#   3C90 ~500 kW/m3 @ 100 kHz / 200 mT
#   3F3  ~120 kW/m3 @ 100 kHz / 100 mT
#   N27  ~700 kW/m3 @ 100 kHz / 200 mT
# (the GUI lets you edit k/a/b directly for your exact material / temperature)
STEINMETZ_MATERIALS = {
    'N87':  dict(k=52.0,  a=1.25, b=2.35),
    'DMR44': dict(k=27.49, a=1.456, b=2.246),
    'PC40': dict(k=25.3,  a=1.65, b=2.75),
    '3C90': dict(k=49.9,  a=1.28, b=2.23),
    '3F3':  dict(k=18.6,  a=1.63, b=2.45),
    'N27':  dict(k=107.5, a=1.35, b=2.70),
    'Custom': dict(k=52.0, a=1.25, b=2.35),
}


def select_core(ap_required, shape=None):
    """Smallest core whose area product >= ap_required.  Returns (name, data)
    or (None, None).  If shape is given, the search is restricted to that
    shape family (the first level of the two-level core picker)."""
    db = CORE_SHAPES.get(shape, CORE_DB) if shape else CORE_DB
    best = None
    for name, data in sorted(db.items(),
                             key=lambda kv: kv[1]['Ae'] * kv[1]['Wa']):
        if data['Ae'] * data['Wa'] >= ap_required:
            best = (name, data)
            break
    return best


def _steinmetz_pv(k, a, b, f_hz, B_pk):
    """Pv in W/m^3.

    Datasheet convention: Pv[mW/cm^3] = k * f[kHz]^a * B[T]^b.
    1 mW/cm^3 = 1e-3 W / 1e-6 m^3 = 1e3 W/m^3.
    """
    return (k * (f_hz / 1e3) ** a * B_pk ** b) * 1e3


def core_loss_steinmetz(k, a, b, f_hz, B_pk, Ve):
    return _steinmetz_pv(k, a, b, f_hz, B_pk) * Ve


def igse_coeff(k, a, b):
    """iGSE coefficient ki (Reinert et al., 2001)."""
    C = 0.2761 + 1.7061 / (a + 1.354)
    return k / (2.0 ** (b + 1.0) * np.pi ** (a - 1.0) * C)


def core_loss_igse(k, a, b, f_hz, dB, Ve, D_on=0.5, D_off=None):
    """iGSE for a *triangular* flux waveform with peak-peak swing dB.

    dB is the peak-peak flux swing; D_on / D_off are the rise / fall duties
    of the flux triangle (CCM inductor: D + (1-D) = 1; DCM: D + Dp < 1, the
    dead time contributes zero loss).  For a symmetric 50/50 triangle this
    reduces to Pv = ki*(2f)^a*dB^b; for any triangle it equals the NSE
    closed form (3.25).

    f is used in kHz (same datasheet convention as Steinmetz / NSE); the
    result is scaled to W.  Used for DC filter inductors (buck/boost/
    buck-boost) whose flux is triangular with DC bias.
    """
    f_k = f_hz / 1e3
    ki = igse_coeff(k, a, b)
    if D_off is None:
        D_off = D_on
    duty = ((max(D_on, 1e-9) ** (1.0 - a) + max(D_off, 1e-9) ** (1.0 - a))
            / 2.0 ** a)          # = 1 for a symmetric 50/50 triangle
    return ki * (2.0 * f_k) ** a * dB ** b * duty * 1e3 * Ve


# ----------------------------------------------------------------------------
# NSE - Natural Steinmetz Extension (Erickson & Maksimovic, Fundamentals of
# Power Electronics, 3rd ed., section on core loss, eqs. (3.21)-(3.25)):
#
#   P_NSE = (dB/2)^(b-a) * (k_N/T) * int_0^T |dB/dt|^a dt          (3.23)
#   k_N   = k / ((2*pi)^(a-1) * int_0^{2pi} |cos t|^a dt)          (3.24)
#
# For a square-wave voltage with duty D (triangular flux, peak-peak swing
# dB = 2*B_hat) the integral closes to (3.25):
#
#   P_NSE = k_N * (2f)^a * B_hat^b * (D_on^(1-a) + D_off^(1-a))    (3.25)
#
# NSE reduces exactly to the classical Steinmetz equation for sinusoidal
# flux, and is the recommended model for non-sinusoidal (PWM / square-wave)
# transformer core loss - i.e. flyback / forward / QR-flyback transformers.
# It uses the same editable k/alpha/beta (f in kHz) as the Steinmetz preset.
# ----------------------------------------------------------------------------
import math


def _cos_alpha_integral(a):
    """int_0^{2pi} |cos t|^a dt  (denominator of eq. 3.24).

    = 4 * int_0^{pi/2} cos^a t dt = 2*sqrt(pi)*Gamma((a+1)/2)/Gamma(a/2+1).
    """
    return (2.0 * math.sqrt(math.pi) * math.gamma((a + 1.0) / 2.0)
            / math.gamma(a / 2.0 + 1.0))


def nse_coeff(k, a, b=None):
    """NSE coefficient k_N from eq. (3.24), using the Steinmetz k (f in kHz)."""
    return k / ((2.0 * math.pi) ** (a - 1.0) * _cos_alpha_integral(a))


def core_loss_nse(k, a, b, f_hz, dB, D_on, D_off, Ve):
    """NSE core loss for a square-wave / PWM voltage, closed form (3.25).

    Parameters
    ----------
    k, a, b : Steinmetz coefficients (datasheet convention, f in kHz).
    f_hz    : operating frequency (Hz).
    dB      : peak-peak flux swing  (flyback: B_pk - B_min; BCM/DCM: B_pk).
    D_on    : on-time duty (T_on/T_sw).
    D_off   : off-time (demagnetising) duty (T_demag/T_sw).  CCM: 1-D_on;
              DCM/QR-BCM: Dp; dead time contributes zero loss.
    Ve      : effective core volume (m^3).

    Returns the core loss in W.  Identical to the general integral (3.23)
    for a triangular flux waveform with slopes dB/(D_on*T) and dB/(D_off*T).
    """
    f_k = f_hz / 1e3
    kN = nse_coeff(k, a, b)
    B_hat = dB / 2.0
    D_on = max(float(D_on), 1e-9)
    D_off = max(float(D_off), 1e-9)
    pv = kN * (2.0 * f_k) ** a * B_hat ** b * (D_on ** (1.0 - a) + D_off ** (1.0 - a))
    return pv * 1e3 * Ve          # mW/cm^3 -> W/m^3, then * Ve -> W


def inductor_flux_waveform(op, L, N, Ae, n_cycles=2, n_pts=2000):
    """Actual B(t) of a PWM filter inductor: rise during D*T by L*dI_L/(N*Ae),
    fall during Dp*T, dwell during dead time (DCM).  DC offset irrelevant to
    the NSE integral."""
    T = op['Ts']
    D, Dp = op['D'], op['Dp']
    dB = L * (op.get('dI_L', op['I_L_pk'])) / (N * Ae)
    t = np.linspace(0.0, n_cycles * T, n_cycles * n_pts, endpoint=False)
    ph = t % T
    B = np.where(
        ph < D * T, dB * ph / max(D * T, 1e-30),
        np.where(ph < (D + Dp) * T,
                 dB * (1.0 - (ph - D * T) / max(Dp * T, 1e-30)), 0.0))
    return t, B


def sinusoid_flux_waveform(B_pk, f_hz, n_cycles=2, n_pts=2000):
    """Sinusoidal B(t) = B_pk*sin(2*pi*f*t) over n_cycles."""
    T = 1.0 / f_hz
    t = np.linspace(0.0, n_cycles * T, n_cycles * n_pts, endpoint=False)
    return t, B_pk * np.sin(2.0 * np.pi * f_hz * t)


def flyback_flux_waveform(op, Np, Ae, n_cycles=2, n_pts=2000):
    """Actual B(t) of the flyback transformer over n_cycles: rise at
    Vin/(Np·Ae) during D·T, fall at V_ref/(Np·Ae) during Dp·T, dwell at
    B_min during the dead time (DCM/QR-BCM).  The DC offset of B does not
    affect the NSE integral, so the waveform is referenced to B_min = 0."""
    T = op['Ts']
    D, Dp = op['D'], op['Dp']
    dB = op['V_in'] * D * T / (Np * Ae)
    t = np.linspace(0.0, n_cycles * T, n_cycles * n_pts, endpoint=False)
    ph = t % T
    B = np.where(
        ph < D * T, dB * ph / max(D * T, 1e-30),
        np.where(ph < (D + Dp) * T,
                 dB * (1.0 - (ph - D * T) / max(Dp * T, 1e-30)), 0.0))
    return t, B


def core_loss_nse_waveform(k, a, b, t, B, Ve):
    """General NSE (3.23)+(3.24) evaluated numerically on an arbitrary B(t).

    t in seconds, B in tesla.  Internally works in ms so the Steinmetz
    k/alpha/beta (f in kHz) stay consistent.  For a sinusoid this reproduces
    the classical Steinmetz loss; for a triangle it matches (3.25).
    """
    t = np.asarray(t, dtype=float)
    B = np.asarray(B, dtype=float)
    dt_ms = (t[1] - t[0]) * 1e3
    t_ms = t * 1e3
    dBdt = np.gradient(B, t_ms)              # T/ms
    dB = float(np.max(B) - np.min(B))
    kN = nse_coeff(k, a, b)
    T_ms = float(t_ms[-1] - t_ms[0])
    integ = float(np.sum(np.abs(dBdt) ** a) * dt_ms)
    return (dB / 2.0) ** (b - a) * kN / max(T_ms, 1e-30) * integ * 1e3 * Ve


def core_loss(k, a, b, f_hz, B_pk, Ve, waveform='sin'):
    """Dispatch: 'sin' -> Steinmetz, 'tri' -> iGSE with dB = 2*B_pk."""
    if waveform == 'tri':
        return core_loss_igse(k, a, b, f_hz, 2.0 * B_pk, Ve)
    return core_loss_steinmetz(k, a, b, f_hz, B_pk, Ve)


def skin_depth(f_hz, rho=1.72e-8):
    return np.sqrt(rho / (np.pi * f_hz * 4e-7 * np.pi))


def ac_factor(d_wire, f_hz, rho=1.72e-8):
    """Rac/Rdc for a round wire (Dowell approximation)."""
    d = skin_depth(f_hz, rho)
    x = d_wire / max(d, 1e-30)
    return 1.0 + x ** 4 / (48.0 + 0.8 * x ** 4)


def wire_diameter(I_rms, J, rho=1.72e-8):
    """Required bare wire diameter for a given current density."""
    A = I_rms / J
    return 2.0 * np.sqrt(A / np.pi)


def resolve_core(p, ap_required, fixed=None):
    """One core selection path for losses, turns, DCR and fixed-BOM corners."""
    fixed=fixed or {}
    choice=fixed.get('core',p.get('core_choice','auto'))
    if fixed.get('core_geometry'):
        return choice, geometry_snapshot(fixed['core_geometry'])
    if is_custom(choice):
        return CUSTOM_CORE, validate_geometry(p.get('custom_core',{}))
    if choice and choice!='auto' and choice in CORE_DB:
        return choice, geometry_snapshot(CORE_DB[choice])
    shape=p.get('core_shape','auto')
    return select_core(ap_required,shape if shape in CORE_SHAPES else None)


def resolve_mlt(p, name, core, fixed=None):
    """Custom geometry owns its MLT; legacy standard overrides remain valid."""
    fixed = fixed or {}
    if fixed.get('MLT'):
        return float(fixed['MLT'])
    if is_custom(name):
        return float(core['MLT'])
    override = p.get('MLT', 0.) or 0.
    return float(override if override > 0 else core['MLT'])


def mlt_source(p, name, fixed=None):
    return (fixed or {}).get('MLT_source') or ('非标准磁芯尺寸输入' if is_custom(name) else
            '用户指定平均匝长' if (p.get('MLT', 0.) or 0.) > 0 else '标准磁芯数据库')


def design_inductor(op, p, I_rms=None, B_pk_ratio=1.0):
    """Design a single-winding inductor (buck/boost/buck-boost L).

    op: operating point (needs f_sw);  p: params with Bmax, J, Ku, rho, k/a/b.
    Returns a dict with the full design + losses.
    """
    from inductor_selection import purchased, design
    if purchased(p):
        return design(op if I_rms is None else dict(op, I_L_rms=I_rms), p)
    fixed = p.get('_fixed_inductor') or {}
    if fixed:
        p = dict(p, core_choice=fixed['core'], MLT=fixed['MLT'])
    f = op['f_sw']
    L = op['L']
    I_pk = op['I_L_pk']
    I_rms = I_rms or op['I_L_rms']

    Bmax = p['Bmax']
    J, Ku, rho = p['J'], p['Ku'], p['rho']
    k, a, b = p['k_core'], p['a_core'], p['b_core']

    # area product: Ap = L*I_pk*I_rms/(Bmax*J*Ku)
    ap = L * I_pk * I_rms / (Bmax * J * Ku)
    name, core = resolve_core(p, ap, fixed)
    if core is None:
        return dict(ok=False, reason='no core large enough in database',

                    ap=ap, L=L, I_pk=I_pk, I_rms=I_rms)
    Ae, Ve, Wa = core['Ae'], core['Ve'], core['Wa']
    MLT = resolve_mlt(p, name, core, fixed)

    # turns so B_peak = Bmax at I_pk
    N = int(fixed.get('N') or np.ceil(L * I_pk / (Bmax * Ae)))
    # air gap for an ungapped assumption (mu_r >> 1)
    lg = 4e-7 * np.pi * N ** 2 * Ae / max(L, 1e-30)
    # wire
    d_wire = fixed.get('d_wire') or wire_diameter(I_rms, J)
    A_wire = np.pi * d_wire ** 2 / 4.0
    R_dc = rho * MLT * N / A_wire
    Fr = ac_factor(d_wire, f, rho)
    P_cu = Fr * R_dc * I_rms ** 2

    # peak flux from the ampere-turns relation  L*I_pk = N*B_pk*Ae
    B_pk = L * I_pk / (N * Ae)
    # core loss: NSE general integral (3.23) on the actual B(t); the flux
    # swing is set by the current ripple.  The iGSE closed form is the
    # analytic triangle solution and is kept as a reference in tests.
    dI = op.get('dI_L', op['I_L_pk'])
    dB = L * dI / (N * Ae)
    t_b, B_t = inductor_flux_waveform(op, L, N, Ae)
    P_core = core_loss_nse_waveform(k, a, b, t_b, B_t, Ve)

    P_total = P_cu + P_core
    h = p.get('h_conv', 10.0)                       # convection coeff W/(m^2 K)
    A_surf = 2.0 * (1.5 * Ve ** (1.0 / 3.0)) ** 2   # rough outer surface area
    dT = P_total / (h * A_surf)                     # temp. rise, K (Erickson ch.11)
    fill = N * A_wire / max(Wa, 1e-30)
    return dict(ok=True, core=name, core_geometry=geometry_snapshot(core),
                core_label=core.get('name') or name, MLT_source=mlt_source(p, name, fixed),
                Ae=Ae, Ve=Ve, Wa=Wa, MLT=MLT,
                ap=ap, N=N, gap=lg, d_wire=d_wire, A_wire=A_wire,
                R_dc=R_dc, Fr=Fr, P_cu=P_cu, P_core=P_core, P_total=P_total,
                B_pk=B_pk, dB=dB,
                J_actual=I_rms / max(A_wire, 1e-30), fill=fill, dT=dT,
                h_conv=h, A_surf=A_surf,
                L=L, I_pk=I_pk, I_rms=I_rms)


def transformer_temperature(P_total, p):
    """User-specified whole-transformer to ambient thermal resistance, K/W.

    This lumped steady-state model does not predict a winding hotspot. The
    default is an editable starting assumption, not a core-database property.
    """
    resistance = float(p.get('Rth_transformer', 100.))
    if not np.isfinite(resistance) or resistance <= 0:
        raise ValueError('变压器至环境热阻 Ri-a 必须为有限正数，单位 K/W')
    return dict(Rth_transformer=resistance, thermal_model='user_thermal_resistance',
                dT=float(P_total)*resistance)


def design_transformer(op, p, I_p_rms, I_s_rms, n_ratio=None, Np=None,
                       Ns=None):
    """Design a two-winding transformer (flyback or active-clamp forward).

    Np is derived from the volt-second / Bmax budget (or given explicitly),
    Ns from the turns ratio n_ratio = Np/Ns (or given).  Computes winding
    wires, window fill, copper loss and core loss.

    Np = Vin*D*Ts/(Bmax*Ae),  dB = Vin*D*Ts/(Np*Ae)  (triangular flux).
    """
    fixed = p.get('_fixed_transformer') or {}
    if fixed:
        p = dict(p, core_choice=fixed['core'], MLT=fixed['MLT'],
                 **{k: fixed[k] for k in ('Np', 'Ns', 'd_wire_p', 'd_wire_s',
                                          'n_strand_p', 'n_strand_s')},
                 **{k: fixed.get(k,p.get(k,1)) for k in ('parallel_wires_p','parallel_wires_s')})
    f = op['f_sw']
    Bmax, J, Ku, rho = p['Bmax'], p['J'], p['Ku'], p['rho']
    k, a, b = p['k_core'], p['a_core'], p['b_core']

    ap = max(2.0 * op['P_out'] * 1.0 / (Bmax * J * Ku * f), 1e-30)
    name, core = resolve_core(p, ap, fixed)
    if core is None:

        return dict(ok=False, reason='no core large enough', ap=ap)
    Ae, Ve, Wa = core['Ae'], core['Ve'], core['Wa']
    MLT = resolve_mlt(p, name, core, fixed)

    # winding parameters may be entered by the user (0 / None -> auto):
    #   Np / Ns  turns, d_wire_p / d_wire_s  wire diameter (m), and the
    #   parallel strand count (并绕数) n_strand_p / n_strand_s.  The primary /
    #   secondary RMS current is shared equally among the strands, the DC
    #   resistance is divided by the strand count, and the window fill uses
    #   the total conductor area.
    Np_u = int(p.get('Np', 0) or 0)
    Ns_u = int(p.get('Ns', 0) or 0)
    strp = max(1, int(p.get('n_strand_p', 1) or 1))
    strs = max(1, int(p.get('n_strand_s', 1) or 1))
    from parallel_wires import count
    copies_p,copies_s=count(p,'p'),count(p,'s')
    total_p,total_s=strp*copies_p,strs*copies_s
    dwp_u = float(p.get('d_wire_p', 0.0) or 0.0)     # m (displayed as mm)
    dws_u = float(p.get('d_wire_s', 0.0) or 0.0)

    if Np_u > 0:
        Np = Np_u
    elif Np is None:
        Np = int(np.ceil(op['V_in'] * op['D'] * op['Ts'] / (Bmax * Ae)))
    Np = max(1, Np)
    if Ns_u > 0:
        Ns = Ns_u
    elif Ns is None:
        Ns = max(1, int(round(Np / n_ratio))) if n_ratio else 1
    Ns = max(1, Ns)

    dw_p = dwp_u if dwp_u > 0 else wire_diameter(I_p_rms / total_p, J)
    dw_s = dws_u if dws_u > 0 else wire_diameter(I_s_rms / total_s, J)
    A_p = np.pi * dw_p ** 2 / 4.0
    A_s = np.pi * dw_s ** 2 / 4.0
    R_p = rho * MLT * Np / (total_p * A_p)
    R_s = rho * MLT * Ns / (total_s * A_s)
    Fr_p = ac_factor(dw_p, f, rho)
    Fr_s = ac_factor(dw_s, f, rho)
    P_cu = Fr_p * R_p * I_p_rms ** 2 + Fr_s * R_s * I_s_rms ** 2
    fill = (Np * total_p * A_p + Ns * total_s * A_s) / max(Wa, 1e-30)
    J_p = I_p_rms / (total_p * A_p)
    J_s = I_s_rms / (total_s * A_s)

    # flux: triangular (flyback).  NSE evaluated directly on the actual B(t)
    # waveform (book eq. 3.23 + 3.24); the closed form (3.25) is its analytic
    # solution for the ideal triangle and is kept as a cross-check in tests.
    # op['Dp'] = 1-D in CCM, = demagnetising duty in DCM/QR-BCM (dead time
    # dwells at B_min).
    dB = op['V_in'] * op['D'] * op['Ts'] / (Np * Ae)   # flux swing (core loss)
    # true peak flux for the SATURATION check: Bpk = Lm*I_pk/(Np*Ae)
    B_pk = (dB / 2 if op['topology'] == 'ACF-FORWARD'
            else op['L'] * op['I_L_pk'] / (Np * Ae))
    flux_op = dict(op, Dp=1-op['D']) if op['topology'] == 'ACF-FORWARD' else op
    t_b, B_t = flyback_flux_waveform(flux_op, Np, Ae)
    P_core = core_loss_nse_waveform(k, a, b, t_b, B_t, Ve)
    P_total = P_cu + P_core
    from transformer_gap import estimate
    gap_design = estimate(p, core, Np)
    return dict(ok=True, core=name, core_geometry=geometry_snapshot(core),
                core_label=core.get('name') or name, MLT_source=mlt_source(p, name, fixed),
                Ae=Ae, Ve=Ve, Wa=Wa, MLT=MLT, ap=ap,
                Np=Np, Ns=Ns, n_actual=Np / Ns, d_wire_p=dw_p, d_wire_s=dw_s,
                n_strand_p=strp, n_strand_s=strs, A_strand_p=A_p, A_strand_s=A_s,
                parallel_wires_p=copies_p, parallel_wires_s=copies_s,
                J_actual_p=J_p, J_actual_s=J_s, I_rms_p=I_p_rms, I_rms_s=I_s_rms,
                R_dc_p=R_p, R_dc_s=R_s, Fr_p=Fr_p, Fr_s=Fr_s,
                P_cu=P_cu, P_core=P_core, P_total=P_total, fill=fill,
                B_pk=B_pk, dB=dB, gap=gap_design['gap_m'], gap_design=gap_design,
                **transformer_temperature(P_total, p))


def rcd_snubber(K, Kc, Lm, I_pk, V_reflect, f_sw, delta_vc=0.10,
                *, L_leak=None):
    """Flyback primary RC (RCD) clamp snubber.

    User inputs:  K  = legacy leakage convention, L_leak=(1-K)*Lm;
                  Kc = V_clamp / V_reflect  (clamp ratio).

    K is deliberately not a pairwise mutual coupling kij.  If a coupled
    inductance model provides its primary-referred leakage, pass L_leak
    explicitly; this avoids silently changing old saved design files.

    Derived:
      L_leak      = (1 - K) * Lm                  (leakage referred to primary)
      V_clamp     = Kc * V_reflect
      dV_clamp    = delta_vc * V_clamp            (capacitor voltage ripple, 10%)
      P_user      = 0.5 * L_leak * I_pk^2 * V_clamp / (V_clamp - V_reflect)
                    (user formula; per-switch-cycle energy equivalent)
      P_res       = P_user * f_sw                 (actual clamp-resistor power, W)
      R_snub      = V_clamp^2 / P_res
      C_snub      = V_clamp / (dV_clamp * R_snub * f_sw)
    """
    L_leak = ((1.0 - float(K)) * Lm if L_leak is None else float(L_leak))
    if not math.isfinite(L_leak) or L_leak < 0.:
        raise ValueError('RCD leakage inductance must be finite and non-negative')
    V_clamp = float(Kc) * V_reflect
    dV_clamp = float(delta_vc) * V_clamp
    E_leak = 0.5 * L_leak * I_pk ** 2
    ratio = V_clamp / max(V_clamp - V_reflect, 1e-9)
    P_user = E_leak * ratio
    P_res = P_user * f_sw
    R_snub = V_clamp ** 2 / max(P_res, 1e-12)
    C_snub = V_clamp / (max(dV_clamp, 1e-9) * max(R_snub, 1e-9)
                        * max(f_sw, 1e-9))
    return dict(K=K, Kc=Kc, Lm=Lm, L_leak=L_leak, V_reflect=V_reflect,
                V_clamp=V_clamp, dV_clamp=dV_clamp, E_leak=E_leak,
                P_user=P_user, P_res=P_res, R_snub=R_snub, C_snub=C_snub)
