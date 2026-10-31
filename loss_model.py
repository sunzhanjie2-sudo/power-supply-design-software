"""Total loss model: semiconductor + magnetics + capacitor + sense resistor +
input/output anti-reverse diodes, efficiency, loss breakdown, and the
efficiency-vs-load curve.

Every topology first uses the user-specified design efficiency, then reports
a separate loss-derived efficiency. The assumption is never overwritten.
"""

import numpy as np

from power_stage import (TOPO_BUCK, TOPO_BOOST, TOPO_BUCKBOOST, TOPO_FLYBACK,
                         TOPO_QRFLYBACK, compute_operating_point,
                         compute_qrflyback_op)
from waveforms import make_waveforms, waveform_rms
from semiconductor import semiconductor_losses
import magnetics as mag


def _device_params(p,rail=None):
    from diode_curves import refs
    rect,free,_=refs(p,rail)
    bank=p.get('diode_curves',{})
    return dict(diode_curve=bank.get(rect),freewheel_curve=bank.get(free),
                Rds_on=p['Rds_on'], tr=p['tr'], tf=p['tf'], Coss=p['Coss'],
                Qg=p['Qg'], Vgs=p['Vgs'], Vf_diode=p['Vf_diode'],
                Rd_diode=p['Rd_diode'], Qrr=p['Qrr'],
                Vth=p.get('Vth', 2.5), Vgp_on=p.get('Vgp_on', 4.5),
                gfs=p.get('gfs', 0.),
                mos_miller_mode=p.get('mos_miller_mode','auto'),
                mos_miller_curve=p.get('mos_miller_curve',{}), mos_curve_vds=p.get('mos_curve_vds',0.),
                mos_charge_mode=p.get('mos_charge_mode','manual'), mos_charge_curve=p.get('mos_charge_curve',{}),
                mos_manual_events=p.get('mos_manual_events',{}),input_voltage_case=p.get('input_voltage_case','min'),
                Vgp_off=p.get('Vgp_off', 4.5), Qg_th=p.get('Qg_th', 1.5e-9),
                Qgs=p.get('Qgs', 2.5e-9), Qgd=p.get('Qgd', 3.0e-9),
                Rg_drive=p.get('Rg_drive', 2.0), Rs_on=p.get('Rs_on', 4.7),
                Rs_off=p.get('Rs_off', 4.7), Rg=p.get('Rg', 1.5),
                k_sw=p.get('k_sw', 0.25), Rds_aux=p.get('Rds_aux', .1),
                Qg_aux=p.get('Qg_aux', 10e-9), Coss_aux=p.get('Coss_aux', 200e-12))


def magnetics_design(op, p):
    """Magnetic design + losses for the selected topology."""
    hardware = (op.get('coupled_model') or op.get('acf_model') or {}).get('transformer_hardware')
    if hardware:
        # The ideal single-output fallback has no ``outputs`` list and does
        # not pass through multi_magnetics. It must use the same resolved
        # transformer as the matrix metadata, not resize automatic gauges.
        p = dict(p, _fixed_transformer=hardware)
    topo = op['topology']
    if topo == 'ACF-FORWARD':
        xfmr = mag.design_transformer(op, p, op['I_p_rms'], op['I_s_rms'],
                                      n_ratio=op['N'])
        choke_p = dict(p, core_choice=p.get('core_choice_L', 'auto'), core_shape='auto',
                       custom_core=p.get('custom_core_L',{}))
        ind = mag.design_inductor(op, choke_p)
        ok = xfmr.get('ok', False) and ind.get('ok', False)
        return dict(ok=ok, transformer=xfmr, inductor=ind,
                    P_total=xfmr.get('P_total', 0)+ind.get('P_total', 0),
                    reason=None if ok else '正激变压器或输出电感选芯失败')
    if topo in (TOPO_FLYBACK, TOPO_QRFLYBACK):
        xfmr = mag.design_transformer(op, p, op['I_sw_rms'], op['I_d_rms'],
                                      n_ratio=op['N'])
        return dict(ok=xfmr.get('ok', False), transformer=xfmr,
                    P_total=xfmr.get('P_total', np.inf), inductor=None,
                    reason=xfmr.get('reason', None))
    # buck / boost / buck-boost: one inductor
    if op.get('niso_model'):
        hardware=op['niso_model']['inductor']
        if hardware.get('ok'):
            p=dict(p,_fixed_inductor={k:hardware[k] for k in ('core','core_geometry','MLT','MLT_source','N','d_wire')})
    ind = mag.design_inductor(op, p)
    if op.get('niso_model') and ind.get('ok'):
        old_total=ind['P_total'];old_rise=ind['dT']
        ind=dict(ind,R_dc=op['niso_model']['dcr'])
        ind['P_cu']=ind['Fr']*ind['R_dc']*op['I_L_rms']**2
        ind['P_total']=ind['P_cu']+ind['P_core']
        ind['dT']=old_rise*ind['P_total']/old_total if old_total>0 else 0.
        ind['DCR_source']='Buck/Boost 控制器配置覆盖' if p.get('spice_config',{}).get('niso_inductor_dcr',-1)>=0 else '冻结几何'
    return dict(ok=ind.get('ok', False), inductor=ind,
                P_total=ind.get('P_total', np.inf),
                reason=ind.get('reason', None))


def total_losses(op, p, wf=None):
    """Loss breakdown + efficiency at the given operating point.

    wf: optional waveform dict (for exact capacitor/sense rms currents);
        computed here if not given.
    """
    from device_curve_sources import effective_sources
    p = effective_sources(p)
    if wf is None:
        wf = make_waveforms(op, n_cycles=2, n_pts=2048)
    from isolated_outputs import selected_params, multi_magnetics, RAIL_KEYS
    source_p = p
    p = selected_params(p)
    p['outputs'] = []
    from diode_curves import conduction,refs,active_diodes
    bank=p.get('diode_curves',{})
    dev = _device_params(p,int(source_p.get('feedback_output',1)) if op.get('outputs') else None)
    semi = semiconductor_losses(op, dev, wf=wf)
    magd = multi_magnetics(op,source_p) if op.get('outputs') else magnetics_design(op,p)

    # One spectral result feeds the loss ledger and every presentation path.
    from capripple import analyze_capacitors
    capacitors = analyze_capacitors(p, op, wf)
    P_cap = sum(c['ESR'] * c['total']**2 for c in capacitors['output']['caps'])
    P_cap_in = sum(c['ESR'] * c['total']**2 for c in capacitors['input']['caps'])
    outputs = []
    if op.get('outputs'):
        for rail,child,child_wf in zip(op['outputs'],op['output_ops'],wf['outputs']):
            rp = dict(p,**{k:rail[k] for k in RAIL_KEYS})
            rp['output_capacitors']=rail.get('output_capacitors')
            sc = semiconductor_losses(child,_device_params(rp,rail['id']),wf=child_wf)
            ca = analyze_capacitors(rp,child,child_wf)
            cap_loss = sum(c['ESR']*c['total']**2 for c in ca['output']['caps'])
            block_model=conduction([child['I_out']],bank.get(refs(rp,rail['id'])[2]),rp['Vf_dout']) if rp['d_out_enable'] else None
            blocking=block_model['P_cond'] if block_model else 0.
            outputs.append(dict(id=rail['id'],name=rail['name'],spec=rail,op=child,
                capacitors=ca,diode=sc['diode'],freewheel=sc.get('freewheel'),
                P_rectifier=sc['diode']['P_total']+sc.get('freewheel',{}).get('P_total',0),
                P_cap=cap_loss,P_dout=blocking,blocking=block_model,ripple_pp=child_wf['ripple_pp']))
        P_cap = sum(x['P_cap'] for x in outputs)
        semi['P_total'] = semi['switch']['P_total']+semi.get('auxiliary',{}).get('P_total',0)+sum(x['P_rectifier'] for x in outputs)
        semi['output_rectifiers'] = outputs
    P_sense = op.get('Rs', 0.0) * _sense_rms(op, wf) ** 2 if op.get('Rs', 0.0) else 0.0

    # RCD (RC) clamp snubber loss for the flyback primary leakage.  When the
    # user chose a clamp ratio Kc > 1 on the RCD tab, the snubber resistor
    # dissipates the leakage energy 0.5*L_leak*Ipk^2*f*Vc/(Vc-Vr).
    P_rcd = 0.0
    if op['topology'] in (TOPO_FLYBACK, TOPO_QRFLYBACK):
        if op.get('clamp'):
            # Matrix commutation is integrated once; nominal LC/clamp
            # envelope likewise owns its power. Never add another leakage
            # estimate on top of the already modelled clamp branch.
            P_rcd = op['clamp']['P_res']
        elif p.get('Kc', 0.0) > 1.0:
            Kc = p['Kc']
            V_reflect = op['V_r']
            rcd = mag.rcd_snubber(p.get('K', 0.95), Kc, op['L'],
                                  op['I_L_pk'], V_reflect, op['f_sw'],
                                  delta_vc=p.get('dC', 0.10))
            P_rcd = rcd['P_res']

    P_semi = semi['P_total']
    P_mag = magd['P_total'] if magd['ok'] else np.nan

    # series anti-reverse (blocking) diodes at the input / output rails.
    # Input diode carries pulsed source current; average instantaneous Vf(I)*I.
    # Output diode sits after the output cap bank and carries
    # the DC load current I_out. Coupled operating points already use fixed
    # input/output drops in their physical equations. These loss entries
    # count each diode once; curve imports refine losses only, not that solve.
    P_din = P_dout = 0.0
    input_model=output_model=None
    if p.get('d_in_enable', False):
        i_in = np.asarray(wf['i_in'], dtype=float)
        input_model=conduction(i_in,bank.get('D_IN'),p.get('Vf_din',.7))
        P_din=input_model['P_cond']
    if p.get('d_out_enable', False) and not outputs:
        I_out = op['I_out']
        output_model=conduction([I_out],bank.get(refs(source_p)[2]),p.get('Vf_dout',.7))
        P_dout=output_model['P_cond']
    if outputs: P_dout = sum(x['P_dout'] for x in outputs)

    from mp6005 import design_psr
    psr = design_psr(source_p,op,magd.get('transformer'))
    P_controller = psr['P_controller'] if psr else 0.
    if psr:
        op['psr'] = psr
        tr = magd.get('transformer')
        if tr and tr.get('ok'):
            ia = psr['Vaux']/(psr['RfbH']+psr['RfbL'])
            rms = ia*op['I_d_rms']/max(op['I_out'],1e-30)
            # Endpoint comparisons use one physical auxiliary winding too;
            # its copper area must not be automatically resized at Vinmax.
            frozen_aux = source_p.get('_fixed_auxiliary') or {}
            dw = frozen_aux.get('d_wire') or max(50e-6,mag.wire_diameter(rms,p['J']))
            area = np.pi*dw**2/4
            raux = p['rho']*tr['MLT']*psr['Na']/area
            loss = mag.ac_factor(dw,op['f_sw'],p['rho'])*raux*rms**2
            tr['auxiliary'] = dict(Na=psr['Na'],I_rms=rms,d_wire=dw,R_dc=raux,P_cu=loss)
            tr['P_cu']+=loss; tr['P_total']+=loss
            tr['fill']+=psr['Na']*area/tr['Wa']
            tr.update(mag.transformer_temperature(tr['P_total'], p))
            magd['P_total']+=loss
            P_mag = magd['P_total'] if magd['ok'] else np.nan

    P_clamp = (op.get('I_clamp_rms', 0)**2 * p.get('ESR_clamp', .03)
               if op['topology'] == 'ACF-FORWARD' else 0.0)
    P_parasitic=float(op.get('P_parasitic',0.))
    P_total = P_semi + P_mag + P_cap + P_cap_in + P_sense + P_rcd + P_din + P_dout + P_clamp + P_controller + P_parasitic
    P_in = op['P_out'] + P_total
    eta = op['P_out'] / max(P_in, 1e-30)

    diode_models=[]
    for item in active_diodes(source_p):
        if item['kind']=='input':model=input_model
        elif outputs:
            row=outputs[item['rail']-1];model=row.get({'rectifier':'diode','freewheel':'freewheel','output':'blocking'}[item['kind']])
        else:model=output_model if item['kind']=='output' else semi.get('diode' if item['kind']=='rectifier' else 'freewheel')
        if model:diode_models.append(dict(item,**model))
    return dict(semi=semi, mag=magd, P_cap=P_cap, P_cap_in=P_cap_in,diode_models=diode_models,
                capacitors=capacitors, P_sense=P_sense,
                P_rcd=P_rcd, P_din=P_din, P_dout=P_dout, P_clamp=P_clamp, P_parasitic=P_parasitic,
                P_semi=P_semi, P_mag=P_mag, P_total=P_total, eta=eta,
                P_in=P_in, P_out=op['P_out'], wf=wf, op=op,
                eta_guess=op['eta_guess'], P_in_est=op['P_in_est'],
                P_loss_budget=op['P_loss_budget'],
                eta_delta=eta-op['eta_guess'],
                P_in_delta=P_in-op['P_in_est'],outputs=outputs,psr=psr,P_controller=P_controller)


def _sense_rms(op, wf):
    """RMS current through the sense resistor (switch current for PCM)."""
    return waveform_rms(wf, 'i_sw')


def recompute_qr_eta(p, max_iter=5):
    """Compatibility entry: one pass with a FIXED preset (max_iter unused).

    Previously iterated eta silently. That behavior has been withdrawn.
    """
    return compute_design(p)


def compute_design(p):
    """Master entry: operating point + waveforms + losses for current params.

    Returns dict(op=..., wf=..., loss=..., stress=..., mag=...).
    """
    from power_stage import validate_design_inputs
    from parasitics import effective_parameters
    p = effective_parameters(p)
    from capacitor_banks import normalize
    p=normalize(p)
    from calculation_scheduler import check_calculation_cancelled
    check_calculation_cancelled()
    from diode_curves import validate_bank
    p=dict(p,Rd_diode=0.,Rd_din=0.,Rd_dout=0.,diode_curves=validate_bank(p.get('diode_curves',{})))
    validate_design_inputs(p)
    op = compute_operating_point(p)
    op['output_capacitors']=__import__('copy').deepcopy(__import__('isolated_outputs').selected_params(p).get('output_capacitors'))
    if op.get('output_ops'):
        for child,rail in zip(op['output_ops'],__import__('isolated_outputs').output_specs(p)):
            child['output_capacitors']=__import__('copy').deepcopy(rail.get('output_capacitors'))
    check_calculation_cancelled()
    wf = make_waveforms(op)
    from parasitic_ringing import attach
    attach(p,op,wf)
    check_calculation_cancelled()
    res = total_losses(op, p, wf)
    return res


def efficiency_curve(p, load_fracs=None, n_pts=24):
    """Efficiency vs load fraction.  Returns (fracs, etas, losses_list).

    Every load point re-solves the operating point with the SAME preset.
    """
    if load_fracs is None:
        load_fracs = np.linspace(0.05, 1.05, n_pts)
    etas, losses = [], []
    for frac in load_fracs:
        from isolated_outputs import scale_load
        pp = scale_load(p,frac)
        try:
            res = compute_design(pp)
        except (ValueError, FloatingPointError):
            etas.append(np.nan)
            losses.append(None)
            continue
        etas.append(res['eta'])
        losses.append(res)
    return np.asarray(load_fracs), np.asarray(etas), losses
