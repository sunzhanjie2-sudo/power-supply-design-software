"""Report projection shared by the legacy API and new design service."""
import copy

def _design_checks(p, res):
    if 'checks' in res:
        return res['checks']
    from design_checks import check_catalog
    from plants import build_loop_models
    from loop_tuning import analyze_loop
    if res.get('loop') is not None:
        return check_catalog(p, res, res['loop'])
    try:
        models, _ = build_loop_models(p, res['op'])
        loop = analyze_loop(p, models, res['op'])
        res['loop'] = loop
        return check_catalog(p, res, loop)
    except Exception as exc:
        from calculation_scheduler import CalculationCancelled
        if isinstance(exc, CalculationCancelled):
            raise
        res['loop'] = None
        return check_catalog(p, res, loop_error=str(exc))


def report_for_result(p, res, user_spec=None, range_snapshot=None):
    """Serialize an already calculated snapshot without redesigning hardware."""
    user_spec = copy.deepcopy(user_spec if user_spec is not None else p)

    op, wf = res['op'], res['wf']
    md = res.get('mag') or {}
    stress = __import__('semiconductor').device_stress(op)

    checks = _design_checks(p, res)
    from component_management import evaluate_components, compact_projection
    failed = [c for c in checks if c['state'] in ('review', 'undefined')]

    warnings = []
    from plants import uses_dcm_peak_energy, DCM_PEAK_NOTE
    if uses_dcm_peak_energy(p,op):
        warnings.append(DCM_PEAK_NOTE)
    elif op.get('mode') == 'DCM' and not op.get('coupled_model'):
        warnings.append('DCM 工况 (轻载或 L 偏小): 环路按单极点 DCM 模型近似')
    if op['topology'] in ('FLYBACK',) and op.get('mode') == 'CCM' and not op.get('coupled_model'):
        warnings.append(f"反激 CCM 存在右半平面零点 f_RHPZ = {op['rhp_zero']:.0f} Hz, fc 应远低于它")
    if p.get('Kc') and p['Kc'] > 1.0 and op['topology'] in ('FLYBACK','QR-FLYBACK'):
        warnings.append('RCD 钳位电压为设定上限，实际包络峰值及钳位功耗来自同一模型；零漏感不产生虚假尖峰')
    warnings.append('效率为模型计算值，未计温度/辅助电路/整流桥/EMI 等附加损耗；误差需实测确定，不保证实测上限')
    warnings.append('逐对耦合模型以预设效率初始化，显式支路压降参与求解；最终效率仍汇总额外工程损耗，不覆盖预设。' if op.get('coupled_model') else
                    '工作点按预设效率的等效输出负担求解；最终效率独立反算，不覆盖输入，也不宣称逐器件损耗自洽。')
    warnings.extend(op.get('warnings', []))
    warnings.extend(res['semi']['switch'].get('gate', {}).get('notes', []))
    for model in res.get('diode_models',[]):
        warnings.extend(model['ref']+'：'+note for note in model.get('extrapolations',[]))

    mdev = md.get('inductor') or md.get('transformer') or {}
    if mdev.get('design_enabled') is False:
        warnings.append(mdev['note'])
    report = dict(
        component_management=compact_projection(evaluate_components(p, res)),
        ok=True,diode_models=copy.deepcopy(res.get('diode_models',[])),
        spec=user_spec,
        topology=op['topology'],
        operating_point=dict(
            eta_guess=float(op['eta_guess']), V_out_equiv=float(op['V_out_equiv']),
            P_in_est=float(op['P_in_est']), I_in_est=float(op['I_in_est']),
            R_equiv=float(op['R_equiv']),
            D=float(op['D']), Dp=float(op['Dp']), mode=str(op['mode']),
            f_sw=float(op['f_sw']),
            I_L_avg=float(op['I_L_avg']), I_L_pk=float(op['I_L_pk']),
            I_L_rms=float(op['I_L_rms']),
            I_sw_rms=float(op['I_sw_rms']), I_sw_pk=float(op['I_sw_pk']),
            I_d_rms=float(op['I_d_rms']), I_d_pk=float(op['I_d_pk']),
            V_sw_max=float(op['V_sw_max']), V_d_max=float(op['V_d_max']),
            ripple_pp=float(wf.get('ripple_pp', float('nan'))),
            rhp_zero=float(op.get('rhp_zero', float('inf'))),
        ),
        losses=dict(
            P_semi=float(res['P_semi']), P_mag=float(res['P_mag']),
            P_cap=float(res['P_cap']), P_cap_in=float(res['P_cap_in']), P_sense=float(res['P_sense']),
            P_rcd=float(res.get('P_rcd', 0.0)),
            P_parasitic=float(res.get('P_parasitic',0.0)),
            P_clamp=float(res.get('P_clamp', 0.0)),
            P_controller=float(res.get('P_controller',0.)),
            P_din=float(res.get('P_din', 0.0)),
            P_dout=float(res.get('P_dout', 0.0)),
            P_total=float(res['P_total']), eta=float(res['eta']),
            eta_guess=float(res['eta_guess']), eta_delta=float(res['eta_delta']),
            P_in_est=float(res['P_in_est']), P_in=float(res['P_in']),
            P_loss_budget=float(res['P_loss_budget']), P_in_delta=float(res['P_in_delta']),
        ),
        magnetics=(dict(ok=True, core=mdev.get('core'), core_label=mdev.get('core_label'),
                        core_geometry=copy.deepcopy(mdev.get('core_geometry')),
                        Ae=mdev.get('Ae'), Ve=mdev.get('Ve'), Wa=mdev.get('Wa'),
                        MLT=mdev.get('MLT'), MLT_source=mdev.get('MLT_source'), Np=mdev.get('Np'),
                        Ns=mdev.get('Ns'), N=mdev.get('N'),
                        gap=mdev.get('gap'), B_pk=mdev['B_pk'],
                        dB=mdev['dB'], P_cu=float(mdev['P_cu']),
                        P_core=mdev['P_core'],
                        P_total=float(mdev['P_total']), dT=mdev['dT'],
                        thermal_model=mdev.get('thermal_model','convection_estimate'),
                        Rth_transformer=mdev.get('Rth_transformer'),
                        fill=mdev['fill'], design_enabled=mdev.get('design_enabled', True),
                        R_dc=mdev.get('R_dc'), L=mdev.get('L'),
                        I_pk=mdev.get('I_pk'), I_rms=mdev.get('I_rms'),
                        inductor_rated_current=mdev.get('inductor_rated_current'),
                        inductor_saturation_current=mdev.get('inductor_saturation_current'),
                        P_extra=mdev.get('P_extra'), note=mdev.get('note'))
                   if md.get('ok') else dict(ok=False,
                                             reason=md.get('reason', ''))),
        stress={k: dict(v) for k, v in stress.items()},
        mosfet=copy.deepcopy(res['semi']['switch']),
        checks=checks,
        loop={k: res['loop'][k] for k in ('fc', 'pm', 'min_pm', 'gm_db', 'gm_infinite')} if res.get('loop') else None,
        failed_checks=[c['id'] for c in failed],
        warnings=warnings,
    )
    if op['topology'] == 'ACF-FORWARD':
        report['active_clamp'] = {k: float(op[k]) for k in (
            'Lm_forward','C_clamp','V_clamp','V_reset','V_clamp_hump',
            'I_mag_pk','I_aux_rms','I_clamp_rms','f_clamp',
            'f_clamp_effective','fc_recommended_max','C_clamp_min')}
        report['magnetics']['devices'] = {k: dict(md[k]) for k in ('inductor','transformer')}
    report['feedback'] = dict(mode=op.get('feedback_mode','SSR'),output=op.get('feedback_output',1),region=op.get('regulation_region','PWM'))
    if res.get('loop') and res['loop'].get('model'):
        loop = res['loop']
        report['loop'].update(model=copy.deepcopy(loop['model']),
            closed_loop_stable=loop['closed_loop_stable'], gm_band_limited=loop['gm_band_limited'],
            gm_scan_limited=loop['gm_scan_limited'])
        dc = loop.get('multi_output', {}).get('dc_load')
        report['loop']['dc_load_V_per_A'] = dc.tolist() if dc is not None else None
    report['psr'] = copy.deepcopy(res.get('psr'))
    if op.get('parasitics'):
        from parasitics import summary
        report['parasitics']=summary(op['parasitics'])
    if res.get('cross_regulation') is not None:
        report['cross_regulation']=copy.deepcopy(res['cross_regulation'])
    report['outputs'] = [dict(id=r['id'],name=r['name'],spec=r['spec'],I_out=r['op']['I_out'],
        V_out=r['op']['V_out'],mode=r['op'].get('branch_mode',r['op']['mode']),
        I_d_pk=r['op']['I_d_pk'],I_d_rms=r['op']['I_d_rms'],V_d_max=r['op']['V_d_max'],
        ripple_pp=r['ripple_pp'],P_rectifier=r['P_rectifier'],P_cap=r['P_cap'],P_dout=r['P_dout']) for r in res.get('outputs',[])]
    if op.get('coupled_model'):
        report['operating_point']['rhp_zero_scope'] = 'nominal-reference-only; use loop model bandwidth and limitations'
        report['coupling'] = copy.deepcopy(op['coupled_model'])
    if op.get('clamp'):
        report['flyback_clamp'] = copy.deepcopy(op['clamp'])
    if md.get('transformer',{}).get('windings'):
        report['magnetics']['windings'] = copy.deepcopy(md['transformer']['windings'])
    if md.get('inductors'): report['magnetics']['inductors'] = copy.deepcopy(md['inductors'])
    if range_snapshot is not None:
        report['input_voltage_range'] = dict(
            min=user_spec['V_in_min'], max=user_spec['V_in_max'],
            selected=user_spec['input_voltage_case'], V_in=p['V_in'],
            hardware_reference='Vinmin', hardware=range_snapshot['hardware'])
    return report
