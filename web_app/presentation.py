"""Small display payload from a solved run. No converter is recalculated here."""
import copy


def present(run):
    from design_engine.contracts import json_value
    from topology_diagram import topology_components
    from semiconductor import device_stress
    from winding_layout import transformer_windings, assess_winding_window
    from magnetic_report_view import build_report
    compact = run.to_dict(include_waveforms=False, include_details=False)
    bundle = run.runtime_bundle()
    displays = []
    for case in bundle['cases']:
        result = case.get('result')
        if result is None or case.get('error'):
            displays.append(dict(id=case['id'], error=case.get('error')))
            continue
        md = result['mag']
        magnetics = []
        devices = [('transformer',md.get('transformer'))]
        devices += [('inductor',device) for device in md.get('inductors',[])] if md.get('inductors') else [('inductor',md.get('inductor'))]
        for kind,device in devices:
            if device:
                magnetics.append(dict(kind=kind, **{key: copy.deepcopy(device.get(key)) for key in
                    ('ok','core','core_label','core_geometry','Ae','Ve','Wa','MLT','MLT_source',
                     'Np','Ns','N','B_pk','dB','gap','gap_design','P_core','P_cu','P_total','dT','fill',
                     'R_dc_p','R_dc_s','R_dc','J_actual_p','J_actual_s','J_actual','windings','reason',
                     'I_rms_p','I_rms_s','I_rms','d_wire','d_wire_p','d_wire_s','n_strand_p','n_strand_s',
                     'Fr','Fr_p','Fr_s','ap','A_surf','Rth_transformer','auxiliary','output_id','id','name','parallel_wires_p','parallel_wires_s',
                     'design_enabled','L','I_pk','inductor_rated_current','inductor_saturation_current','P_extra','note')}))
        windings = transformer_windings(result)
        winding_assessment = None
        if windings:
            try:
                winding_assessment = assess_winding_window(windings, case['p'].get('winding_config'))
            except ValueError as exc:
                # An unfinished mechanical layer plan must not discard a valid
                # electrical solution. Keep the requested config and report an
                # unknown fit; never replace it with a passing automatic plan.
                winding_assessment = dict(config=copy.deepcopy(case['p'].get('winding_config') or {}),
                    configured=True, status='invalid_plan', fits=None, windings=[],
                    physical_layers=[], total_layer_count=0, warnings=[str(exc)])
        rcd = None
        if result['op']['topology'] in ('FLYBACK','QR-FLYBACK'):
            from flyback_clamp import rcd_components
            rcd = rcd_components(result['op'],case['p'])
        scalar_op = {key:value for key,value in result['op'].items()
                     if isinstance(value,(str,int,float,bool)) or value is None}
        from component_management import evaluate_components, compact_projection
        displays.append(dict(id=case['id'], components=topology_components(case['p'], result['op']),
            component_management=compact_projection(evaluate_components(case['p'], result), with_row_checks=True),
            magnetics=magnetics, magnetic_report=build_report(case['p'], result), switch_loss=result['semi']['switch'],
            stress=device_stress(result['op']),semiconductors={key:result['semi'].get(key) for key in
                ('switch','diode','auxiliary','freewheel','n_switches','n_diodes','P_total')},
            operating_point=scalar_op,capacitors=result.get('capacitors',{}),
            winding_rows=windings,winding_assessment=winding_assessment,
            rcd=rcd,clamp=result['op'].get('clamp'),
            capacitor_rms={key:result.get('capacitors',{}).get(key) for key in ('total_in','total_out')},
            psr=result.get('psr'),parasitics=__import__('parasitics').summary(result['op'].get('parasitics')),
            outputs=[dict(id=rail['id'],name=rail['name'],V_out=rail['op']['V_out'],V_out_cap=rail['op'].get('V_out_cap',rail['op']['V_out']),
                I_out=rail['op']['I_out'],P_out=rail['op']['P_out'],
                mode=rail['op'].get('branch_mode', rail['op']['mode']),
                ripple_pp=rail['ripple_pp'],P_rectifier=rail['P_rectifier'],P_cap=rail['P_cap'],
                P_dout=rail['P_dout'],stress=device_stress(rail['op']),semiconductors={key:rail.get(key) for key in ('diode','freewheel','blocking')},
                capacitors=rail.get('capacitors'),spec=rail.get('spec')) for rail in result.get('outputs', [])],
            loop_available=result.get('loop') is not None,
            waveform_points=len(result['wf']['t'])))
    compact['display'] = json_value(displays)
    from engineering_acceptance import report_snapshot
    compact['engineering_acceptance'] = report_snapshot(bundle['base_spec'], range_result=bundle)
    return compact
