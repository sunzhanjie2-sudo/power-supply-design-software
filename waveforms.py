"""Steady-state time-domain waveform synthesis + FFT analysis.

Produces the idealised (piecewise-linear / FHA) periodic waveforms of the
selected topology so the user can *see* the key signals — inductor/primary
current, switch & diode current, switch voltage, output-capacitor current and
output ripple — and run FFT / THD analysis on them.

"""

import numpy as np

from power_stage import (TOPO_BUCK, TOPO_BOOST, TOPO_BUCKBOOST, TOPO_FLYBACK,
                         TOPO_QRFLYBACK)


# ----------------------------------------------------------------------------
# Piecewise-linear waveform builders
# ----------------------------------------------------------------------------
def _time_axis(Ts, n_cycles, n_pts):
    return np.linspace(0.0, n_cycles * Ts, n_cycles * n_pts, endpoint=False)


def cap_bank_ripple(t, i_c, caps):
    """Output ripple voltage across a parallel capacitor bank.

    caps: list of (C, R, L) tuples (up to two).  The ripple voltage is the
    voltage across the bank impedance Z_eq = Z1||Z2 driven by the capacitor
    current, computed in the frequency domain:

        V(f) = I_c(f) * Z_eq(f),  Z_j(f) = R_j + j*(2*pi*f*L_j - 1/(2*pi*f*C_j))

    This captures the combined effect of both capacitors (total capacitance,
    ESR, ESL and the anti-resonance between a bulk cap and a HF bypass cap)
    exactly, without the sample-rate-dependent ESL-spike artefact.
    """
    i_c = np.asarray(i_c, dtype=float) - np.mean(i_c)
    N = len(i_c)
    dt = float(t[1] - t[0])
    Ic = np.fft.rfft(i_c)
    freqs = np.fft.rfftfreq(N, dt)
    Z = np.zeros(len(freqs), dtype=complex)
    for k in range(1, len(freqs)):
        w = 2.0 * np.pi * freqs[k]
        zj = [R + 1j * (w * L - 1.0 / (w * max(C, 1e-30)))
              for (C, R, L) in caps]
        z = zj[0]
        for z2 in zj[1:]:
            z = z * z2 / (z + z2)
        Z[k] = z
    return np.fft.irfft(Ic * Z, N)


def _tri_phase(tt, T, D_on, D_off, I_pk, I_min):
    """Triangle wave: rises I_min->I_pk during D_on*T, falls during D_off*T,
    zero elsewhere.  Works for CCM (D_on+D_off=1) and DCM."""
    tt = tt % T
    i = np.zeros_like(tt)
    on = tt < D_on * T
    off = (tt >= D_on * T) & (tt < (D_on + D_off) * T)
    i[on] = I_min + (I_pk - I_min) * (tt[on] / max(D_on * T, 1e-30))
    i[off] = I_pk - (I_pk - I_min) * ((tt[off] - D_on * T) / max(D_off * T, 1e-30))
    return i


def make_waveforms(op, n_cycles=2, n_pts=2048):
    if op.get('niso_model'):
        from nonisolated import waveform
        return waveform(op,n_cycles,n_pts)
    """Return dict {t, iL/i_p, i_sw, i_d, v_sw, v_d, i_c, vout_ripple, ...}.

    i_c  : output-capacitor current (ripple source)
    vout_ripple : ESR + charge ripple reconstructed from i_c
    """
    if op.get('acf_solution') is not None:
        from acf_periodic import waveforms
        return waveforms(op,n_cycles,n_pts)
    if op.get('coupled_solution') is not None:
        from isolated_outputs import coupled_waveforms
        return coupled_waveforms(op,n_cycles,n_pts)
    if op.get('output_ops'):
        from isolated_outputs import multi_waveforms
        return multi_waveforms(op,n_cycles,n_pts)
    topo = op['topology']
    T = op['Ts']
    f_sw = op['f_sw']
    t = _time_axis(T, n_cycles, n_pts)
    dt = t[1] - t[0]
    wf = {'t': t, 'dt': dt, 'f_sw': f_sw, 'topology': topo}

    _pwm_waveforms(op, t, wf)

    # output ripple: voltage across the parallel capacitor bank.  The bank
    # (cap1 = C_out/Rc/ESL, plus cap2 C_out2/Rc2/ESL2 when enabled) is
    # modelled in the frequency domain as Z1||Z2, so both capacitors'
    # capacitance, ESR and ESL act together (including the HF bypass of a
    # small parallel cap).  The low-frequency ripple (ESL = 0) is used for
    # the ripple target; the ESL switching spike is reported separately.
    i_c = wf['i_c']
    from capacitor_banks import tuples
    caps = tuples(op)
    v_rip = cap_bank_ripple(t, i_c, caps)
    v_lf = cap_bank_ripple(t, i_c, [(C, R, 0.0) for (C, R, _L) in caps])
    wf['vout_ripple'] = v_lf                      # LF ripple (both caps, no ESL)
    wf['v_esl'] = v_rip - v_lf                    # ESL-induced switching spike
    wf['vout'] = op['V_out'] + wf['vout_ripple']
    wf['vcap'] = op.get('V_out_cap',op['V_out']) + wf['vout_ripple']
    wf['ripple_pp'] = float(v_lf.max() - v_lf.min())
    wf['ripple_pp_total'] = float(v_rip.max() - v_rip.min())
    wf['esl_spike_pp'] = float(np.max(np.abs(wf['v_esl']))) if len(wf['v_esl']) else 0.0
    wf['i_c_rms'] = float(np.sqrt(np.mean(i_c ** 2)))
    # input-side current drawn from the source (for input-cap ripple analysis)
    wf['i_cin'] = wf['i_in'] - np.mean(wf['i_in'])
    wf['i_cin_rms'] = float(np.sqrt(np.mean(wf['i_cin'] ** 2)))
    return wf


def _pwm_waveforms(op, t, wf):
    topo = op['topology']
    if topo == 'ACF-FORWARD':
        from active_clamp import forward_waveforms
        wf.update(forward_waveforms(op, t))
        return
    T = op['Ts']
    D, Dp = op['D'], op['Dp']
    I_pk, I_min = op['I_L_pk'], op['I_L_min']

    iL = _tri_phase(t, T, D, Dp, I_pk, I_min)
    wf['iL'] = iL
    on = (t % T) < D * T
    off = ~on
    wf['i_sw'] = np.where(on, iL, 0.0)
    wf['i_d'] = np.where(off, iL, 0.0)
    wf['v_sw'] = np.where(on, 0.0, op['V_sw_max'] / (1.0 + op['ring_margin']))
    wf['v_d'] = np.where(off, 0.0, op['V_d_max'])

    if topo in (TOPO_FLYBACK, TOPO_QRFLYBACK):
        # primary = magnetising current; secondary reflected.  In DCM / QR-BCM
        # the secondary current must be zero during the dead time after
        # demagnetisation (the old code ramped it negative, inflating the
        # output-cap ripple current).
        I_s_pk, I_s_min = op['N'] * I_pk, op['N'] * I_min
        i_s = np.zeros_like(iL)
        off_mask = ~on
        tt_off = (t[off_mask] % T - D * T)
        i_s_off = I_s_pk - (I_s_pk - I_s_min) * (tt_off / max(Dp * T, 1e-30))
        i_s[off_mask] = np.clip(i_s_off, 0.0, None)
        wf['i_p'] = iL                       # primary (magnetising) current
        wf['i_s'] = i_s
        wf['i_sw'] = np.where(on, iL, 0.0)
        wf['i_d'] = i_s
        wf['i_c'] = i_s - op['I_out']        # output cap: secondary - load
        from flyback_clamp import clamp_voltage
        wf['v_sw'] = clamp_voltage(t, op)
        if op.get('clamp'):
            wf['clamp'] = op['clamp']
    elif topo == TOPO_BUCK:
        wf['i_p'] = iL
        wf['i_c'] = iL - op['I_out']
    elif topo in (TOPO_BOOST, TOPO_BUCKBOOST):
        # diode current flows into output
        wf['i_p'] = iL
        wf['i_c'] = wf['i_d'] - op['I_out']
        v_block = op['V_out_equiv'] + (op['V_in'] if topo == TOPO_BUCKBOOST else 0)
        wf['v_sw'] = np.where(on, 0.0, v_block)
        wf['v_d'] = np.where(off, 0.0, v_block)
    # input-side (source) current: pulsed for buck/flyback, inductor for boost
    if topo == TOPO_BUCK:
        wf['i_in'] = wf['i_sw']
    elif topo == TOPO_BOOST:
        wf['i_in'] = wf['iL']
    else:                                     # FLYBACK / QR-FLYBACK
        wf['i_in'] = wf['i_sw']


# ----------------------------------------------------------------------------
# FFT analysis
# ----------------------------------------------------------------------------
def fft_analysis(t, x, f_sw, n_harmonics=20):
    """Magnitude spectrum + harmonic table + THD of a periodic signal.

    Assumes `t` covers an integer number of switching periods (the waveform
    builder guarantees this), so a rectangular window is exact.
    """
    x = np.asarray(x, dtype=float)
    N = len(x)
    dt = t[1] - t[0]
    dc = float(x.mean())
    X = np.fft.rfft(x - dc) / N * 2.0          # peak amplitudes
    freqs = np.fft.rfftfreq(N, dt)
    mag = np.abs(X)

    harmonics = []
    for k in range(1, n_harmonics + 1):
        fk = k * f_sw
        i = int(np.argmin(np.abs(freqs - fk)))
        harmonics.append((k, float(freqs[i]), float(mag[i])))

    fund = harmonics[0][2] if len(harmonics) else 0.0
    thd = (np.sqrt(sum(h[2] ** 2 for h in harmonics[1:])) / fund
           if fund > 1e-30 else np.inf)
    return dict(freqs=freqs, mag=mag, dc=dc, harmonics=harmonics,
                thd=thd, fund=fund, f_sw=f_sw)


def waveform_rms(wf, name):
    return float(np.sqrt(np.mean(wf[name] ** 2)))
