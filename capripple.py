"""Capacitor-bank ripple-current analysis (input & output).

For each rail (input / output) the *ripple current* that the capacitor bank
must absorb is decomposed into frequency bands with a coherent DFT (or an
energy-calibrated flat-top FFT for noncoherent input),
and the current is then divided among the (up to two) parallel capacitors by
the ratio of their impedances at every frequency,

    Z_j(f) = R_esr,j + j*(2*pi*f*ESL_j - 1/(2*pi*f*C_j))

A converter's ripple current is dominated by the switching-frequency
harmonics, so the band decomposition is built around them: band 0 is below
0.5*f_sw, band k surrounds k*f_sw, and the last band is the high-frequency
remainder. All FFT bins contribute; the one-sided Nyquist energy is halved.
For noncoherent input the estimated spectrum is calibrated to time-domain
AC RMS. A single capacitor's band-sum total equals the bank AC RMS.

For two parallel capacitors the individual cap currents can exceed the bank
total because of phase differences (circulating current) — that is physical.
"""

import numpy as np


def _flattop(N):
    """Flat-top window, bit-identical to scipy.signal.windows.flattop(N)
    (sym=True, 5 coefficients).  Inlined so the startup path does not pull
    in scipy.signal."""
    a = (0.21557895, 0.41663158, 0.277263158, 0.083578947, 0.006947368)
    n = np.arange(N) * 2 * np.pi / (N - 1)
    return (a[0] - a[1] * np.cos(n) + a[2] * np.cos(2 * n)
            - a[3] * np.cos(3 * n) + a[4] * np.cos(4 * n))


def _bank_spectrum(x, dt):
    """Flat-top windowed rFFT + coherent gain.

    Returns (freqs, X, coh) where X is the complex rFFT of the DC-removed
    windowed signal and coh = sum(w) is the coherent (amplitude) gain; the
    peak-amplitude phasor of a bin is X[bin] * 2.0 / coh.
    """
    N = len(x)
    w = _flattop(N)
    xw = (np.asarray(x, dtype=float) - np.mean(x)) * w
    X = np.fft.rfft(xw)
    freqs = np.fft.rfftfreq(N, dt)
    return freqs, X, float(np.sum(w))


def _impedance(f, C, R, ESL):
    """Ripple-current impedance of one capacitor at frequency f (Hz)."""
    w = 2.0 * np.pi * f
    return R + 1j * (w * ESL - 1.0 / (w * max(C, 1e-30)))


def _split(ph, f, caps):
    """Impedance-divide a peak-amplitude phasor among parallel caps."""
    ad = [1.0 / _impedance(f, c['C'], c['ESR'], c['ESL']) for c in caps]
    ytot = sum(ad)
    return [ph * (a / ytot) for a in ad]


def _divide_and_band(x, dt, f_sw, caps, n_harm=20):
    """Whole-bin power split. Coherent steady-state uses an unwindowed DFT.

    Parseval weights include the one-sided Nyquist correction. Noncoherent
    inputs use a flat-top window and explicit time-RMS energy calibration.
    Never discard side bins or apply peak-amplitude calibration to HF noise.
    """
    x = np.asarray(x, float) - np.mean(x)
    N = len(x)
    if N < 2 or dt <= 0 or f_sw <= 0 or not caps:
        raise ValueError('Invalid capacitor spectrum input')
    periods = N * dt * f_sw
    coherent = abs(periods - round(periods)) < 1e-6
    window = np.ones(N) if coherent else _flattop(N)
    X = np.fft.rfft(x * window)
    f = np.fft.rfftfreq(N, dt)[1:]
    power = 2 * np.abs(X[1:]/N)**2
    if N % 2 == 0:
        power[-1] *= .5
    total_bank = float(np.sqrt(np.mean(x*x)))
    # Noncoherent estimates require calibration for the window's energy.
    if not coherent:
        power *= total_bank**2 / max(float(power.sum()), 1e-30)
    labels = ['<0.5f'] + [f'{h}f' for h in range(1, n_harm+1)] + ['HF']
    band = np.minimum(np.floor(f/f_sw+.5).astype(int), n_harm+1)
    w = 2*np.pi*f
    Y = np.array([1/(c['ESR'] + 1j*(w*c['ESL']-1/(w*max(c['C'], 1e-30))))
                  for c in caps])
    ytot = Y.sum(axis=0)
    if np.any(np.abs(ytot) < 1e-30):
        raise ValueError('Singular parallel capacitor impedance')
    currents = Y/ytot
    infos = []
    for c, ratio in zip(caps, currents):
        bins = np.bincount(band, weights=power*np.abs(ratio)**2,
                           minlength=len(labels))
        infos.append(dict(C=c['C'], ESR=c['ESR'], ESL=c['ESL'],
                          total=float(np.sqrt(bins.sum())),
                          bands=np.sqrt(bins).tolist()))
    return dict(total_bank=total_bank, labels=labels, caps=infos,
                spectrum_method='coherent DFT' if coherent else 'flat-top estimate')


def analyze_capacitors(p, op, wf=None):
    """Shared waveform/FFT snapshot for losses, GUI, API and Word."""
    from isolated_outputs import selected_params
    if p.get('outputs'): p=selected_params(p)
    if wf is None:
        from waveforms import make_waveforms
        wf = make_waveforms(op)
    from capacitor_banks import bank
    ins,outs=bank(p,'input'),bank(p)
    return capacitor_ripple_analysis(wf['t'], wf['i_cin'], wf['i_c'],
                                     op['f_sw'], ins, outs)


def cap_bank_esr_loss(t, i_c, f_sw, caps):
    """Total ESR loss of a parallel capacitor bank carrying ripple i_c.

    The ripple current is impedance-split between the caps (whole-bin spectral
    split, see _divide_and_band) and P = sum(R_j * I_rms_j^2).  Returns
    (P_total, [I_rms_j ...]).
    """
    rail = _divide_and_band(np.asarray(i_c, float), float(t[1] - t[0]),
                            f_sw, caps)
    totals = [c['total'] for c in rail['caps']]
    p = sum(c['ESR'] * c['total'] ** 2 for c in rail['caps'])
    return p, totals


def capacitor_ripple_analysis(t, i_cin, i_cout, f_sw, in_caps, out_caps,
                              n_harm=20):
    """Full input/output capacitor-bank ripple analysis.

    Parameters
    ----------
    t        : time axis (s), must cover whole switching period(s).
    i_cin    : input capacitor bank total ripple current (A), i.e. the AC
               part of the source-side current.
    i_cout   : output capacitor bank total ripple current (A) (= wf['i_c']).
    f_sw     : switching frequency (Hz).
    in_caps  : list of dicts {C, ESR, ESL} (1 or 2 parallel input caps).
    out_caps : list of dicts {C, ESR, ESL} (1 or 2 parallel output caps).
    n_harm   : number of harmonic bands (default 20).

    Returns dict(f_sw, total_in, total_out, input=..., output=...) where each
    rail dict has total_bank (time-domain RMS), labels (band names) and caps
    (per-cap total + per-band RMS).
    """
    dt = float(t[1] - t[0])
    ins = _divide_and_band(np.asarray(i_cin, float), dt, f_sw, in_caps, n_harm)
    outs = _divide_and_band(np.asarray(i_cout, float), dt, f_sw, out_caps, n_harm)
    return dict(f_sw=f_sw, input=ins, output=outs,
                total_in=ins['total_bank'], total_out=outs['total_bank'])
