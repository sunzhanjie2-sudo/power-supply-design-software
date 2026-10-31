"""Nominal multi-output design, not a cross-regulation simulation.

The primary processes total power. Flyback secondary currents are shared in
proportion to power, conserving ampere-turns. Forward branches share one PWM
and the supported nominal model requires CCM in every output choke.
"""
import copy
import math

ISOLATED = ('FLYBACK', 'QR-FLYBACK', 'ACF-FORWARD')
RAIL_KEYS = ('V_out','P_out','P_out_min','C_out','Rc','ESL','C_out2','Rc2','ESL2',
             'cout2_enable','Vf_diode','Rd_diode','Qrr','d_out_enable',
             'Vf_dout','Rd_dout','ripple_target','Ns','d_wire_s',
             'n_strand_s','L','core_choice_L','custom_core_L')


def _resolved_output_specs(p):
    raw = p.get('outputs', [])
    if not isinstance(raw, list) or len(raw)>6:
        raise ValueError('outputs 必须是最多 6 路输出的列表')
    if raw and p['topology'] not in ISOLATED:
        raise ValueError('多绕组输出仅适用于隔离拓扑')
    rails = []
    for i,entry in enumerate(raw):
        if not isinstance(entry,dict): raise ValueError(f'OUT{i+1} 必须是参数字典')
        unknown = set(entry)-set(RAIL_KEYS)-{'name','output_capacitors'}
        if unknown: raise ValueError(f'OUT{i+1} 未知参数：{sorted(unknown)}')
        from config_io import decode_config
        entry = decode_config(entry)
        rail = {k:copy.deepcopy(p.get(k)) for k in RAIL_KEYS}
        if i>0: rail.update(Ns=0,d_wire_s=0.)
        rail.update(entry)
        from capacitor_banks import normalize
        rail=normalize(rail)
        rail['Rd_diode']=rail['Rd_dout']=0.  # old JSON accepted, no hidden Rd model
        # Old designs did not declare a light-load condition. Do not invent
        # one (or turn a working legacy file into an all-no-load experiment).
        rail['P_out_min'] = entry.get('P_out_min', rail['P_out'])
        rail.update(name=str(entry.get('name',f'OUT{i+1}'))[:24],id=i+1)
        # L/core_choice_L are legacy-compatible branch fields, but only a
        # forward converter has a separate choke per output.  Flyback uses
        # the one shared primary magnetizing L; inactive branch values must
        # neither constrain it nor be mistaken for an output inductor.
        active_keys = RAIL_KEYS if p['topology']=='ACF-FORWARD' else tuple(
            k for k in RAIL_KEYS if k not in ('L','core_choice_L','custom_core_L'))
        from custom_cores import is_custom, validate_geometry
        if p['topology']=='ACF-FORWARD' and is_custom(rail['core_choice_L']):
            fixed_chokes=p.get('_fixed_inductors') or []
            frozen=fixed_chokes[i].get('core_geometry') if i<len(fixed_chokes) else None
            rail['custom_core_L']=validate_geometry(frozen or rail.get('custom_core_L',{}))
        for k in active_keys:
            if k == 'V_out' and i != int(p.get('feedback_output', 1)) - 1 and rail.get('Ns', 0) > 0:
                # An old stored value is not another regulation constraint.
                continue
            v = rail.get(k)
            if isinstance(v,(int,float)) and not math.isfinite(v):
                raise ValueError(f'OUT{i+1}.{k} 必须为有限值')
        positive_keys = ('V_out','C_out','L') if p['topology']=='ACF-FORWARD' else ('V_out','C_out')
        for k in positive_keys:
            if k == 'V_out' and i != int(p.get('feedback_output', 1)) - 1 and rail.get('Ns', 0) > 0:
                continue
            if not isinstance(rail.get(k),(int,float)) or rail[k]<=0:
                raise ValueError(f'OUT{i+1}.{k} 必须大于 0')
        if rail['cout2_enable'] and rail['C_out2']<=0:
            raise ValueError(f'OUT{i+1}.C_out2 必须大于 0')
        for k in ('P_out','Rc','ESL','Rc2','ESL2','Vf_diode','Rd_diode','Qrr',
                  'Vf_dout','Rd_dout','ripple_target','Ns','d_wire_s'):
            if rail[k]<0: raise ValueError(f'OUT{i+1}.{k} 不得为负')
        for k in ('Ns','n_strand_s'):
            if int(rail[k])!=rail[k] or (k=='n_strand_s' and rail[k]<1):
                raise ValueError(f'OUT{i+1}.{k} 必须为合法整数')
        if (isinstance(rail['P_out_min'], bool) or not isinstance(rail['P_out_min'], (int,float))
                or not math.isfinite(rail['P_out_min']) or not 0 <= rail['P_out_min'] <= rail['P_out']):
            raise ValueError(f'OUT{i+1} 最小输出功率必须为有限数，且 0 ≤ P_out_min ≤ P_out（最大功率）')
        rails.append(rail)
    selected = p.get('feedback_output',1)
    if not isinstance(selected,(int,float)) or int(selected)!=selected or not 1<=selected<=max(1,len(rails)):
        raise ValueError('主反馈路必须是现有输出的 1-based 编号')
    if rails:
        if rails[int(selected)-1]['P_out']<=0:
            raise ValueError('主反馈路需要正的设计负载；空载调节不能用此标称模型验证')
    mode = p.get('feedback_mode','SSR')
    if mode not in ('SSR','PSR-MP6005'):
        raise ValueError('feedback_mode 必须为 SSR 或 PSR-MP6005')
    if mode=='PSR-MP6005' and p['topology']!='FLYBACK':
        raise ValueError('MP6005 PSR 仅支持固定频率反激，不是 QR 控制器，也不支持 PSR 正激')
    from transformer_turns import resolve_output_turns
    turns = resolve_output_turns(p, rails)
    if turns:
        for rail, ns, voltage in zip(rails, turns['Ns'], turns['voltages']):
            rail.update(Ns=ns, V_out=voltage)
    return rails, turns


def output_specs(p):
    """Canonical rails: only the selected feedback voltage is a setpoint.

    Returned secondary turns are resolved integers.  Persist these values when
    importing old automatic-turn configurations so their former non-feedback
    voltage entries remain migration hints, not live design inputs.
    """
    return _resolved_output_specs(p)[0]


def selected_params(p, rails=None, turns=None):
    if rails is None:
        rails, turns = _resolved_output_specs(p)
    elif rails and turns is None:
        from transformer_turns import resolve_output_turns
        turns = resolve_output_turns(p, rails)
    q = copy.deepcopy(p)
    if rails:
        j = int(p.get('feedback_output',1))-1
        q.update({k:rails[j][k] for k in RAIL_KEYS if k not in ('L','core_choice_L','custom_core_L') or p['topology']=='ACF-FORWARD'})
        q['output_capacitors']=copy.deepcopy(rails[j].get('output_capacitors'))
        q['N'] = turns['ratios'][j]
        q['Np'] = turns['Np']
        q['Ns'] = turns['Ns'][j]
        q['P_out'] = sum(r['P_out'] for r in rails)
    return q


def compute_isolated_op(p):
    from power_stage import compute_operating_point
    rails, turns = _resolved_output_specs(p)
    pp = selected_params(p, rails, turns)
    pp['outputs'],pp['feedback_mode'],pp['feedback_output'] = [],'SSR',1
    if rails and p['topology']=='ACF-FORWARD':
        pp['L'] = 1/sum((r['V_out']/pp['V_out'])**2/r['L'] for r in rails)
    if p.get('feedback_mode')=='PSR-MP6005':
        pp.update(f_sw=250e3,control_mode='Peak Current Mode',A_sense=11.)
        if pp['Rs']<=0: raise ValueError('MP6005 的 Rs 必须大于 0')
    core = compute_operating_point(pp)
    region = 'PWM'
    if p.get('feedback_mode')=='PSR-MP6005' and core['I_sw_pk']*pp['Rs']<.036:
        minimum_peak = .036/pp['Rs']
        required = 2*core['P_in_est']/(pp['L']*minimum_peak**2)
        if required<30e3:
            floor = .5*pp['L']*minimum_peak**2*30e3*core['eta_guess']
            raise ValueError(f'MP6005 PSR 低于最小能量负载，不能假定稳压：总输出需约 ≥{floor:.4g} W；请增加预负载')
        pp['f_sw'] = min(required,250e3)
        core = compute_operating_point(pp)
        if core['mode']!='DCM':
            raise ValueError('MP6005 的轻载降频估算仅支持 DCM，当前需要控制器时域仿真')
        region = 'PFM-estimate'
    op = copy.deepcopy(core)
    op.update(feedback_mode=p.get('feedback_mode','SSR'),
              feedback_output=int(p.get('feedback_output',1)),regulation_region=region,
              aggregate_op=core,aggregate_params=pp,outputs=rails)
    if not rails: return op
    op['output_turns'] = turns
    total = sum(r['P_out'] for r in rails)
    branch_ops = []
    for rail in rails:
        q = dict(pp,**{k:rail[k] for k in RAIL_KEYS})
        q['output_capacitors']=rail.get('output_capacitors')
        q['P_out'] = max(rail['P_out'],1e-15)
        q['N'] = turns['ratios'][rail['id'] - 1]
        if p['topology']=='ACF-FORWARD':
            child = compute_operating_point(q)
            if child['mode']!='CCM' and not p.get('_acf_predesign'):
                raise ValueError(f"{rail['name']} 正激支路进入 DCM：共享占空比下不能独立稳压；请增加该路 L/最小负载，或用后级稳压。多路正激模型限各路 CCM。")
        else:
            weight = rail['P_out']/total
            child = dict(core,N=q['N'],V_out=rail['V_out'],
                         V_out_equiv=rail['V_out']/core['eta_guess'],P_out=rail['P_out'],
                         I_out=rail['P_out']/rail['V_out'],R=rail['V_out']**2/max(rail['P_out'],1e-15),
                         I_L_pk=core['I_L_pk']*weight,I_L_min=core['I_L_min']*weight)
            child.update({k:rail[k] for k in ('C_out','Rc','ESL','C_out2','Rc2','ESL2','cout2_enable')})
            child.update(I_d_pk=core['I_L_pk']*weight*q['N'],I_d_avg=child['I_out'],
                         I_d_rms=core['I_d_rms']*weight*q['N']/core['N'],
                         C_min=core['C_min']*weight*(core['V_out']/rail['V_out'])**2,
                         V_d_max=child['V_out_equiv']+core['V_in']/q['N'])
        child.update(output_id=rail['id'],name=rail['name'])
        from voltage_nodes import attach_nodes
        attach_nodes(child,dict(p,**rail))
        branch_ops.append(child)
    main = branch_ops[op['feedback_output']-1]
    for key in ('I_out','R','I_d_pk','I_d_rms','I_d_avg','V_d_max','C_min',
                'C_out','Rc','ESL','C_out2','Rc2','ESL2','cout2_enable'):
        if key in main: op[key] = main[key]
    if p['topology']=='ACF-FORWARD':
        for key in ('I_free_pk','I_free_rms','I_free_avg','V_free_max','I_s_rms',
                    'L','dI_L','I_L_pk','I_L_min','I_L_rms','L_min'):
            if key in main: op[key] = main[key]
    op['output_ops'] = branch_ops
    op['warnings'] = list(op.get('warnings',[]))+['仅反馈路电压为设定值；其他输出由实际副边匝比推导理想近似电压。标称同步波形/功率比例模型不含交叉调整率，整流压降、DCR 与漏感影响需用耦合模型或仿真复核。']
    return op


def multi_waveforms(op,n_cycles,n_pts):
    from waveforms import make_waveforms
    wf = make_waveforms(op['aggregate_op'],n_cycles,n_pts)
    outputs = [make_waveforms(q,n_cycles,n_pts) for q in op['output_ops']]
    main = outputs[op['feedback_output']-1]
    for key in ('i_d','i_s','i_c','v_d','vout','vout_ripple','v_esl','ripple_pp',
                'ripple_pp_total','esl_spike_pp','i_c_rms'):
        if key in main: wf[key] = main[key]
    wf['outputs'] = outputs
    return wf


def coupled_waveforms(op, n_cycles, n_pts):
    """Uniform FFT samples of the verified switched-matrix solution.

    Resampling is checked against the solver's exact segment charge.  Only
    after periodic charge balance is verified is the AC ripple reconstructed;
    the FFT's DC removal must not hide an unregulated/charging output.
    """
    import numpy as np
    from waveforms import cap_bank_ripple
    solution = op['coupled_solution']
    period = float(op['Ts'])
    source_t = np.asarray(solution['t'], dtype=float)
    points = max(int(n_pts), 2048)
    while True:
        t = np.linspace(0., n_cycles*period, int(n_cycles)*points, endpoint=False)
        phase = np.mod(t, period)
        def sample(values):
            return np.interp(phase, source_t, np.asarray(values, dtype=float))
        secondary = [sample(x) for x in solution['i_winding'][1:]]
        errors = [abs(float(np.mean(x))-q['I_out'])/max(q['I_out'],1e-6)
                  for x,q in zip(secondary,op['output_ops'])]
        if max(errors, default=0.) <= .002:
            break
        points *= 2
        if points > max(int(n_pts), 131072):
            raise ValueError('耦合支路的窄电流脉冲采样未通过电荷检查；请复核工况或提高采样分辨率')
    shared = dict(t=t,dt=float(t[1]-t[0]),f_sw=op['f_sw'],topology=op['topology'],
                  i_sw=sample(solution['i_sw']),i_in=sample(solution['i_in']),
                  v_sw=sample(solution['v_sw']),i_p=sample(solution['i_magnetizing']),
                  i_primary=sample(solution['i_winding'][0]),i_clamp=sample(solution['i_clamp']))
    shared['iL'] = shared['i_p']
    shared['i_cin'] = shared['i_in']-np.mean(shared['i_in'])
    shared['i_cin_rms'] = float(np.sqrt(np.mean(shared['i_cin']**2)))
    outputs = []
    for j,(child,current) in enumerate(zip(op['output_ops'],secondary)):
        wf = dict(shared,i_s=current,i_d=current,i_c=current-child['I_out'])
        wf['v_d'] = np.maximum(child.get('V_out_cap',child['V_out'])+sample(solution['v_winding'][j+1])+
                                op['coupled_model']['R'][j+1]*current,0.)
        from capacitor_banks import tuples
        caps = tuples(child)
        full = cap_bank_ripple(t,wf['i_c'],caps)
        low = cap_bank_ripple(t,wf['i_c'],[(c,r,0.) for c,r,_ in caps])
        wf.update(vout_ripple=low,v_esl=full-low,vout=child['V_out']+low,
                  vcap=child.get('V_out_cap',child['V_out'])+low,
                  ripple_pp=float(np.ptp(low)),ripple_pp_total=float(np.ptp(full)),
                  esl_spike_pp=float(np.max(np.abs(full-low))),
                  i_c_rms=float(np.sqrt(np.mean(wf['i_c']**2))),
                  charge_sampling_relative=errors[j])
        outputs.append(wf)
    result = dict(outputs[op['feedback_output']-1])
    result['outputs'] = outputs
    return result


def scale_load(p,fraction):
    q = copy.deepcopy(p)
    q['P_out'] *= fraction
    if q.get('outputs'):
        q['outputs'] = [{k:v for k,v in r.items() if k!='id'} for r in output_specs(p)]
        for rail in q['outputs']:
            rail['P_out'] *= fraction
            rail['P_out_min'] = min(rail['P_out_min'], rail['P_out'])
    return q


def multi_magnetics(op,p):
    """One core/primary, all secondary copper and window area, all chokes."""
    import magnetics as mag
    from loss_model import magnetics_design
    q = selected_params(p); q['outputs'] = []
    coupled_metadata = op.get('coupled_model') or op.get('acf_model') or {}
    hardware = coupled_metadata.get('transformer_hardware')
    if hardware:
        # Auto gauges were selected once before the physical solve.  Reuse
        # that exact conductor/core geometry; otherwise final RMS would
        # silently choose another gauge and displayed DCR would disagree
        # with the resistance that produced the waveforms.
        q['_fixed_transformer'] = hardware
    base = magnetics_design(dict(op,outputs=[]),q)
    tr = base.get('transformer')
    if not tr or not tr.get('ok'): return base
    coupled = op.get('coupled_model') if op.get('coupled_solution') is not None else op.get('acf_model') if op.get('acf_solution') is not None else None
    if coupled:
        tr['R_dc_p_geometry'] = tr['R_dc_p']
        tr['R_dc_p'] = coupled['R'][0]
        tr['I_rms_p'] = coupled['winding_rms'][0]
        tr['J_actual_p'] = tr['I_rms_p']/(tr['n_strand_p']*tr['A_strand_p'])
        tr['dcr_source'] = 'geometry'
        tr['auto_wire_sizing'] = 'nominal-predesign-frozen'
        # A general L matrix does not identify a unique common-core flux.
        # Retain a labelled primary-linkage reference, not an exact B claim.
        solution=op.get('coupled_solution') or op['acf_solution']
        flux = solution['lambda_p']/(tr['Np']*tr['Ae'])
        import numpy as np
        tr.update(B_pk=float(np.max(np.abs(flux))),dB=float(np.ptp(flux)),
                  flux_model='primary_winding_linkage_reference')
        # NSE currently expects a uniform grid. Event-time samples can be
        # only femtoseconds apart and must not be treated as a uniform dt.
        uniform_t = np.linspace(0.,op['Ts'],8193)
        uniform_flux = np.interp(uniform_t,solution['t'],flux)
        tr['P_core'] = mag.core_loss_nse_waveform(p['k_core'],p['a_core'],p['b_core'],
                            uniform_t,uniform_flux,tr['Ve'])
    windings,inductors = [],[]
    copper = tr['Fr_p']*tr['R_dc_p']*tr['I_rms_p']**2
    area = tr['Np']*tr['n_strand_p']*tr['A_strand_p']
    for rail,child in zip(op['outputs'],op['output_ops']):
        current = child.get('I_s_rms',child['I_d_rms'])
        frozen = hardware['windings'][rail['id']-1] if hardware else None
        turns = frozen['Ns'] if frozen else int(rail['Ns']) or max(1,round(tr['Np']/child['N']))
        strands = int(frozen['n_strand_s'] if frozen else rail['n_strand_s'])
        diameter = frozen['d_wire_s'] if frozen else rail['d_wire_s'] or max(50e-6,mag.wire_diameter(current/strands,p['J']))
        a = math.pi*diameter**2/4
        geometric_resistance = p['rho']*tr['MLT']*turns/(strands*a)
        resistance = coupled['R'][rail['id']] if coupled else geometric_resistance
        fr = mag.ac_factor(diameter,op['f_sw'],p['rho'])
        loss = fr*resistance*current**2
        copper += loss; area += turns*strands*a
        predicted = op['aggregate_op']['V_out']*(turns/tr['Np'])*op['aggregate_op']['N']
        windings.append(dict(id=rail['id'],name=rail['name'],Ns=turns,N=child['N'],
            n_actual=tr['Np']/turns,d_wire_s=diameter,n_strand_s=strands,
            I_rms=current,R_dc=resistance,Fr=fr,P_cu=loss,J_actual=current/(strands*a),
            R_dc_geometry=geometric_resistance,
            V_turns_est=predicted,voltage_error=(predicted/rail['V_out']-1)*100))
        if op['topology']=='ACF-FORWARD':
            ip = dict(p,**{k:rail[k] for k in RAIL_KEYS},core_choice=rail['core_choice_L'],core_shape='auto',
                      custom_core=rail.get('custom_core_L',{}))
            if p.get('_fixed_inductors'):
                ip['_fixed_inductor'] = p['_fixed_inductors'][rail['id']-1]
            inductors.append(mag.design_inductor(child,ip))
    tr.update(windings=windings,P_cu=copper,fill=area/tr['Wa'])
    tr.setdefault('dcr_source', 'geometry')
    if coupled:
        selected_winding = windings[op['feedback_output']-1]
        tr['R_dc_s_geometry'] = tr['R_dc_s']
        tr.update(R_dc_s=selected_winding['R_dc'],I_rms_s=selected_winding['I_rms'],
                  Fr_s=selected_winding['Fr'],J_actual_s=selected_winding['J_actual'])
    tr['P_total'] = tr['P_cu']+tr['P_core']
    tr.update(mag.transformer_temperature(tr['P_total'], p))
    if inductors:
        base.update(inductors=inductors,inductor=inductors[op['feedback_output']-1],
                    ok=all(x['ok'] for x in inductors))
    base['P_total'] = tr['P_total']+sum(x.get('P_total',0) for x in inductors)
    return base
