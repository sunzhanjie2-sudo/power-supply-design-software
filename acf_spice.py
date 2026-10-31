"""Physical low-side active-clamp forward stage and MP6005-inspired timing.

The clamp is a P-channel switch to primary ground, in series with Cclamp
to the main drain (MP6005 Rev1.1 fig16). No ideal reset-voltage source.
"""
import math

MODEL_VERSION = 'GenericACF-MP6005-1.0'
SETTINGS = {
    'acf_dead_ns': (0., 0., 1000., 'GATE／SYNC 死区，0=沿用正激设计', 'ns'),
    'acf_sync_resistance': (5., .01, 1000., 'SYNC 等效驱动串联电阻', 'Ω'),
}


def preset(current=None):
    from spice_export import mp6005_preset
    return mp6005_preset(dict(current or {}, acf_dead_ns=100., acf_sync_resistance=5.))


def current_slope(p,rails,geometry,settings=None):
    """One explicit amplified-CS ramp definition for calculation and export."""
    if settings is None:
        from spice_export import normalize_settings
        settings=normalize_settings(p.get('spice_config'))
    gain=float(p['A_sense']);rs=float(p['Rs'])
    design=max(0.,float(p.get('ma_slope',0.)))*gain*rs
    recommended=.75*sum((r['V_out']+r['Vf_diode']+(r['Vf_dout'] if r.get('d_out_enable') else 0))
        /r['L']*w['Ns']/geometry['Np'] for r,w in zip(rails,geometry['windings']))*gain*rs
    mode=settings['slope_mode']
    value=settings['slope'] if mode==2 else max(design,recommended) if mode==1 and p['control_mode']=='Peak Current Mode' else design
    return float(value)


def render_stage(q, rails, geometry, kvals, settings):
    from spice_circuit import render_stage as flyback_stage, CONTROL_KEYS
    # Reuse the cap-bank, load, feedback and protection-fixture contract.
    body, params = flyback_stage(q, rails, geometry, kvals,
                                dict(C_snub=0., R_snub=math.inf), settings)
    body = [s for s in body if not s.startswith(('XD_SN1 ', 'R_SN1 ', 'C_SN1 '))]
    params = {k: v for k, v in params.items() if not k.startswith(('D_SN1_', 'R_SN1', 'C_SN1'))}
    params['LP'] = float(q['Lm_forward'])
    for i, (r, w) in enumerate(zip(rails, geometry['windings']), 1):
        params['LS'+str(i)] = params['LP']*(w['Ns']/geometry['Np'])**2
        # Same dot at VIN and rectN: secondary transfers power during ON.
        index = next(j for j, s in enumerate(body) if s.startswith(f'LS{i} '))
        body[index] = body[index].replace(f'LS{i} sgnd rect{i}', f'LS{i} rect{i} sgnd')
        index = next(j for j, s in enumerate(body) if s.startswith(f'XD_O{i} '))
        body[index] = body[index].replace(f'rect{i} cap{i}', f'rect{i} choke{i}')
        body += [f'LO{i} choke{i} cap{i} {{LO{i}}} Rser=0',
                 f'XD_F{i} sgnd choke{i} GPWR_DIODE VF={{D_O{i}_VF}} CJ={{DIODE_CJ}}']
        params['LO'+str(i)] = float(r['L'])
    params.update(C_ACTIVE=float(q['C_clamp']), ESR_ACTIVE=float(q['ESR_clamp']),
                  QA_RON=float(q['Rds_aux']), QA_COSS=max(float(q['Coss_aux']),1e-12),
                  QA_CG=max(float(q['Qg_aux'])/float(q['Vgs']),1e-12))
    body += ['C_ACTIVE drain aclamp {C_ACTIVE} Rser={ESR_ACTIVE}',
             'XQA aclamp auxgate 0 GACF_PMOS RON={QA_RON} COSS={QA_COSS} CG={QA_CG} VG={VG} CJ={DIODE_CJ}']
    index = next(j for j, s in enumerate(body) if s.startswith('XU_CTRL '))
    body[index] = ('XU_CTRL fb sense en vcc gate comp ramp ss fault 0 sync auxgate GACF_CTRL '
                   + ' '.join(k+'={'+k+'}' for k in CONTROL_KEYS) + ' TDEAD={TDEAD} RSYNC={RSYNC}')
    return body, params


def extra_analysis(count):
    lines = ['.save V(sync) V(auxgate) V(aclamp) V(vin_bus) I(C_ACTIVE) V(overlap)',
             'BOVERLAP overlap 0 V=if((V(gate,sense)>{VG/2})&(V(auxgate)<{-VG/2}),1,0)',
             '.meas tran gate_overlap MAX V(overlap) FROM {TLOAD-200/FSW} TO {TLOAD-10/FSW}',
             '.meas tran clamp_mean AVG V(drain,aclamp) FROM {TLOAD-200/FSW} TO {TLOAD-10/FSW}',
             '.meas tran clamp_ripple PP V(drain,aclamp) FROM {TLOAD-200/FSW} TO {TLOAD-10/FSW}',
             '.meas tran clamp_current_rms RMS I(C_ACTIVE) FROM {TLOAD-200/FSW} TO {TLOAD-10/FSW}',
             '.meas tran reset_voltsecond INTEG V(vin_bus,drain) FROM {TLOAD-200/FSW} TO {TLOAD-10/FSW}']
    for i in range(1,count+1):
        lines += [f'.save I(LO{i}) V(choke{i})',
                  f'.meas tran out{i}_choke_rms RMS I(LO{i}) FROM {{TLOAD-200/FSW}} TO {{TLOAD-10/FSW}}',
                  f'.meas tran out{i}_choke_peak MAX I(LO{i}) FROM {{TLOAD-200/FSW}} TO {{TLOAD-10/FSW}}',
                  f'.meas tran out{i}_choke_valley MIN I(LO{i}) FROM {{TLOAD-200/FSW}} TO {{TLOAD-10/FSW}}',
                  f'.meas tran out{i}_free_reverse MAX V(choke{i},sgnd) FROM {{TLOAD-200/FSW}} TO {{TLOAD-10/FSW}}']
    return lines


def timing_quality(raw, frequency, end, vg, primary_r=0.):
    """Time-weighted actual-threshold edge and flux-balance audit."""
    import numpy as np
    ts=1/frequency;finish=math.floor(end/ts)*ts;start=finish-64*ts
    a,b=np.searchsorted(raw.time,[start,finish]);t=raw.time[a:b]
    main=raw.trace('v(gate)')[a:b]-raw.trace('v(sense)')[a:b]
    aux=-raw.trace('v(auxgate)')[a:b]
    def edges(v):
        high=v>vg/2;idx=np.flatnonzero(np.diff(high.astype(np.int8)))
        x=t[idx]+(vg/2-v[idx])*(t[idx+1]-t[idx])/(v[idx+1]-v[idx])
        return x[~high[idx]],x[high[idx]]
    mr,mf=edges(main);ar,af=edges(aux)
    def gaps(on,off):
        result=[]
        for x in on:
            prior=off[off<x]
            if len(prior) and x-prior[-1]<ts:result.append(x-prior[-1])
        return min(result) if result else None
    voltage=raw.trace('v(vin_bus)')[a:b]-raw.trace('v(drain)')[a:b]-primary_r*raw.trace('i(lp)')[a:b]
    residual=float(np.trapezoid(voltage,t)/(t[-1]-t[0]))
    relative=abs(residual)/max(float(np.max(np.abs(voltage))),1e-6)
    overlap=bool(np.any((main>vg/2)&(aux>vg/2)))
    dm,da=gaps(mr,af),gaps(ar,mf)
    return dict(overlap=overlap,main_dead_min_s=dm,aux_dead_min_s=da,
                flux_residual_mean_v=residual,flux_residual_relative=relative,
                passed=not overlap and dm is not None and da is not None and dm>0 and da>0 and relative<.01)
