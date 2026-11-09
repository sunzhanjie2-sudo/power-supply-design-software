"""Venable K-factor compensator design (loop auto-tuning).

Given the plant Gvc(s), a target crossover frequency fc and a target phase
margin PM, place the compensator zeros/poles symmetrically around fc so the
compensator contributes exactly the phase boost needed:

    boost = PM - 90 deg - phase_plant(fc)  (relative to the integrator)

Type-2 (one finite zero + one finite pole + integrator): max boost ~90 deg
    K = tan(45 deg + boost/2),  fz = fc/K,  fp = fc*K,  KP = wc/(K*|Gvc(fc)|)

Type-3 (three poles, two zeros; includes integrator): max boost ~180 deg
    K = tan(45 deg + boost/4),  fz1=fz2 = fc/K,  fp1=fp2 = fc*K,
    KP = wc/(K^2*|Gvc(fc)|)

Reference: D. Venable, "The K Factor: A New Technique for Accurate Analysis
and Design of the Feedback Loop", Proc. Powercon 10, 1983.
"""

import numpy as np


def _frequency_values(model, points):
    """Evaluate the existing model at every supplied complex point.

    NumPy's batched solve avoids thousands of Python calls for state-space
    plants. Bounded chunks keep the temporary matrices small even with many
    capacitor states. No transfer-function conversion or pole cancellation.
    Always return (outputs, inputs, frequencies), like squeeze=False.
    """
    import control as ct
    from calculation_scheduler import check_calculation_cancelled

    points = np.atleast_1d(np.asarray(points, dtype=complex))
    if not isinstance(model, ct.StateSpace):
        return np.asarray(model(points, squeeze=False))
    count = model.nstates
    if not count:
        return np.broadcast_to(model.D[:, :, None],
                               (*model.D.shape, len(points))).astype(complex).copy()
    result = np.empty((model.noutputs, model.ninputs, len(points)), dtype=complex)
    identity = np.eye(count)
    # Allow for the shifted matrix, solver workspace and right-hand side.
    bytes_per_point = 16 * (3*count*count + 2*count*model.ninputs)
    chunk = max(1, min(256, 8*1024*1024 // max(bytes_per_point, 1)))
    for start in range(0, len(points), chunk):
        check_calculation_cancelled()
        values = points[start:start+chunk]
        try:
            states = np.linalg.solve(values[:, None, None]*identity-model.A,
                np.broadcast_to(model.B, (len(values), *model.B.shape)))
            response = model.C @ states + model.D
            result[:, :, start:start+chunk] = np.moveaxis(response, 0, -1)
        except np.linalg.LinAlgError:
            # At an exact pole retain python-control's inf/nan diagnostics;
            # one singular frequency must not discard the other frequencies.
            result[:, :, start:start+chunk] = model(values, squeeze=False)
    return result


def analyze_loop(p, models, op=None, n=6000):
    """Shared scan; undefined is None, never the last sampled frequency."""
    import control as ct
    fs = (op or {}).get('f_sw', p['f_sw'])
    metadata = getattr(models[0], '_loop_metadata', None)
    full = getattr(models[0], '_multi_output_system', None)
    limit = metadata.get('frequency_limit') if metadata else None
    scan_margin = bool(limit or (metadata and metadata.get('experimental')))
    f = np.logspace(-2, np.log10(limit or max(fs * 10, 1e6)), n)
    bank = _frequency_values(full, 2j*np.pi*f) if full is not None else None
    if bank is not None:
        feedback = metadata['feedback_output']-1
        plant = bank[feedback, 0]
        compensator = _frequency_values(models[1], 2j*np.pi*f).ravel()
        gains = [plant, compensator, plant*compensator]
    else:
        gains = [_frequency_values(g, 2j*np.pi*f).ravel() for g in models]
    phases = []
    for gain in gains:
        ph = np.degrees(np.unwrap(np.angle(gain)))
        if ph[0] > 90:
            ph -= 360
        phases.append(ph)
    db = 20 * np.log10(np.maximum(np.abs(gains[2]), 1e-300))
    crosses, all_crosses = [], []
    for i in np.where(((db[:-1] >= 0) & (db[1:] < 0)) |
                      ((db[:-1] < 0) & (db[1:] >= 0)))[0]:
        k = -db[i] / (db[i+1] - db[i])
        fc = float(10**(np.log10(f[i]) + k*np.log10(f[i+1]/f[i])))
        pm = float(180 + phases[2][i] + k*(phases[2][i+1]-phases[2][i]))
        direction = 'down' if db[i+1] < db[i] else 'up'
        all_crosses.append(dict(fc=fc, pm=pm, direction=direction))
        if direction == 'down':
            crosses.append((fc, pm))
    selected = min(crosses, key=lambda v: abs(np.log(v[0]/max(p.get('fc_target', 1000), 1e-9)))) if crosses else (None, None)
    if scan_margin:
        # Evaluate numerical state-space models directly. Removing a model
        # bandwidth gate must not introduce ill-conditioned TF conversion or
        # turn a missing crossing in a finite scan into infinite hardware GM.
        margins = []
        low, high = float(min(phases[2])), float(max(phases[2]))
        for turn in range(int(np.floor((low+180)/360))-1, int(np.ceil((high+180)/360))+1):
            level = -180+360*turn
            delta = phases[2]-level
            for i in np.flatnonzero(delta[:-1]*delta[1:] < 0):
                k = -delta[i]/(delta[i+1]-delta[i])
                margins.append(float(-(db[i]+k*(db[i+1]-db[i]))))
        gm_db, gm_infinite = (min(margins) if margins else None), False
    else:
        gm, _, _, _ = ct.margin(models[2])
        gm_db = float(20*np.log10(gm)) if 0 < gm < np.inf else None
        gm_infinite = bool(np.isinf(gm))
    result = dict(f=f, gains=gains, phases=phases, fc=selected[0], pm=selected[1],
                gm_db=gm_db, gm_infinite=gm_infinite, crosses=crosses,
                all_crosses=all_crosses,
                min_pm=min((v['pm'] for v in all_crosses), default=None))
    if metadata:
        result['model'] = dict(metadata)
        result['gm_band_limited'] = bool(limit)
        result['gm_scan_limited'] = scan_margin
        poles = ct.poles(ct.feedback(models[2], 1))
        result['closed_loop_stable'] = bool(np.all(np.real(poles) < 0))
        result['closed_loop_max_pole_real'] = float(max(np.real(poles))) if len(poles) else None
        outputs = metadata['outputs']
        if len(outputs) <= 1:
            # Shared model metadata also describes single-output Buck/Boost.
            # A physical model alone does not imply multiple output responses.
            return result
        feedback = metadata['feedback_output']-1
        voltages = np.array([r['voltage'] for r in outputs])
        if bank is None:
            # Only the existing rigid-ratio approximation, not cross-regulation.
            reference = np.tile(gains[2]/(1+gains[2]), (len(outputs), 1))
            load, dc_load = None, None
        else:
            response = bank[:, 0]
            reference = (response*gains[1]/(1+gains[2]))*voltages[feedback]/voltages[:, None]
            load = bank[:, 1:]-response[:, None, :]*gains[1]/(1+gains[2])*bank[feedback, 1:][None, :, :]
            zero = np.real(np.asarray(full(0, squeeze=False)))
            dc_load = zero[:, 1:]
            if p.get('KP', 0) > 0 and abs(zero[feedback, 0]) > 1e-12:
                dc_load = dc_load-zero[:, 0, None]*zero[feedback, 1:][None, :]/zero[feedback, 0]
        result['multi_output'] = dict(outputs=outputs, feedback_output=feedback+1,
            reference=reference, load=load, dc_load=dc_load)
    return result


def gain_at(G, f):
    """Complex gain |G(j*2*pi*f)| magnitude and phase (deg)."""
    g = G(1j * 2 * np.pi * f)
    return abs(g), float(np.degrees(np.angle(g)))


def plant_phase_unwrapped(G, fc, n=400):
    """Continuous (unwrapped) phase of G at fc [deg], normalised to (-360, 90].

    np.angle() wraps to (-180, 180]; the phase of a converter plant can fall
    below -180 deg (double pole + RHP zero, inverting DC gain), so sweep from
    fc/100 to fc and unwrap.  A phase that sits on the +pi branch (inverting
    plants: DC phase = -180 == +180 in np.angle) is pushed back down by 360."""
    f = np.logspace(np.log10(max(fc / 100.0, 1e-3)), np.log10(fc), n)
    ph = np.unwrap(np.angle(_frequency_values(G, 2j*np.pi*f).ravel()))
    ph = float(np.degrees(ph[-1]))
    if ph > 90.0:                      # wrapped from the (-360, -180) branch
        ph -= 360.0
    return ph


def kfactor_tune(Gvc, fc, pm_target, comp_type='auto'):
    """Design the compensator for crossover fc (Hz) and phase margin
    pm_target (deg).

    comp_type: 'auto' | 'type2' | 'type3'
    Returns dict(KP, fz1, fz2, fp1, fp2, K, boost, fc, pm, comp_type).
    Unused corners are None (fz2/fp2 for type 2).
    """
    comp_type = str(comp_type).strip().lower()
    if comp_type not in ('auto','type2','type3'):
        raise ValueError('Unknown compensator type')
    if not np.isfinite(fc) or fc <= 0 or not np.isfinite(pm_target):
        raise ValueError('fc must be positive and finite; PM must be finite')
    wc = 2 * np.pi * fc
    mag = abs(Gvc(1j * wc))
    if not np.isfinite(mag) or mag <= 0:
        raise ValueError('Plant gain at fc must be finite and nonzero')
    phase_plant = plant_phase_unwrapped(Gvc, fc)
    # loop phase at fc = phase_plant + phase_comp; the compensator always
    # contains an integrator (-90 deg), so the zero/pole pairs must supply:
    #   boost = PM - 180 - phase_plant - (-90) = PM - 90 - phase_plant
    boost = pm_target - 90.0 - phase_plant

    if comp_type == 'auto':
        comp_type = 'type2' if boost <= 75.0 else 'type3'
    required = float(boost)
    lo, hi = (-89.999,89.999) if comp_type == 'type2' else (-170.0,170.0)
    feasible = lo <= required <= hi
    boost = float(np.clip(required,lo,hi))

    if comp_type == 'type2':
        K = np.tan(np.radians(45.0 + boost / 2.0))
        K = float(K)
        KP = wc / (K * mag)
        return dict(KP=KP, fz1=fc / K, fz2=None, fp1=fc * K, fp2=None,
                    K=K, boost=float(boost), boost_required=required,
                    fc=fc, pm=pm_target, comp_type='type2',
                    feasible=feasible)
    K = np.tan(np.radians(45.0 + boost / 4.0))
    K = float(K)
    KP = wc / (K * K * mag)
    return dict(KP=KP, fz1=fc / K, fz2=fc / K, fp1=fc * K, fp2=fc * K,
                K=K, boost=float(boost), boost_required=required,
                fc=fc, pm=pm_target, comp_type='type3', feasible=feasible)


def evaluate_loop(Gvc, Gc, fmin=10.0, fmax=1e6, n=20000):
    """Compute the actual crossover frequency and phase margin of the loop
    Gc*Gvc (used to verify the K-factor result)."""
    import control as ct
    omega = np.logspace(np.log10(2 * np.pi * fmin),
                        np.log10(2 * np.pi * fmax), n)
    mag, phase, w = ct.bode(Gc * Gvc, omega=omega, dB=False, Hz=False,
                            plot=False)
    mag = np.atleast_1d(np.asarray(mag).ravel())
    phase = np.atleast_1d(np.asarray(phase).ravel())
    w = np.asarray(w).ravel()
    fc = None
    for i in range(len(mag) - 1):
        if mag[i] >= 1.0 >= mag[i + 1]:
            fc = float(np.interp(0.0, 20 * np.log10(mag[i:i + 2][::-1]),
                                 w[i:i + 2][::-1])) / (2 * np.pi)
            pm = 180.0 + np.interp(fc * 2 * np.pi, w, phase) * 180.0 / np.pi
            return fc, pm
    return None, None
