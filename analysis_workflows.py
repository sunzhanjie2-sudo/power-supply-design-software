"""Read-only engineering workflows; no Tk or Word dependencies."""
import copy
import math

def evaluate(p, *, resolve_input_range=True):
    """One canonical snapshot: steady state, waveforms, losses, loop, checks."""
    if resolve_input_range:
        from input_voltage_range import has_input_voltage_range, calculate_input_operating_point
        if has_input_voltage_range(p):
            return calculate_input_operating_point(p, include_loop=True)
    from design_engine.calculation import build_snapshot
    return build_snapshot(p)


def pin_hardware(p, res):
    """Freeze nominal magnetic core, turns and winding geometry, not load."""
    fixed = copy.deepcopy(p)
    md = res['mag']
    if not md.get('ok'):
        raise ValueError('标称磁件无有效设计，不能执行固定硬件角点分析')
    for kind in ('inductor', 'transformer'):
        dev = md.get(kind)
        if dev and dev.get('ok'):
            keys = (('core', 'core_geometry', 'MLT', 'MLT_source', 'N', 'd_wire') if kind == 'inductor' else
                    ('core', 'core_geometry', 'MLT', 'MLT_source', 'Np', 'Ns', 'd_wire_p', 'd_wire_s',
                     'n_strand_p', 'n_strand_s'))
            fixed['_fixed_'+kind] = copy.deepcopy({k: dev[k] for k in keys})
    coupled_hardware = (res['op'].get('coupled_model') or res['op'].get('acf_model') or {}).get('transformer_hardware')
    if coupled_hardware:
        # The numerical circuit used the predesign geometry, including every
        # secondary's conductor and DCR.  Keep that whole physical transformer,
        # not only the selected feedback winding's top-level fields.
        fixed['_fixed_transformer'] = copy.deepcopy(coupled_hardware)
    elif md.get('transformer', {}).get('windings'):
        fixed['_fixed_transformer']['windings'] = [
            {key: winding[key] for key in ('id', 'Ns', 'd_wire_s', 'n_strand_s', 'R_dc')}
            for winding in md['transformer']['windings']]
    if res.get('outputs'):
        from isolated_outputs import output_specs
        fixed['outputs'] = [{k:v for k,v in r.items() if k!='id'} for r in output_specs(p)]
        for rail,winding in zip(fixed['outputs'],md['transformer']['windings']):
            for key in ('Ns','d_wire_s','n_strand_s'):
                rail[key] = winding[key]
        if md.get('inductors'):
            fixed['_fixed_inductors'] = [{k:copy.deepcopy(d[k]) for k in ('core','core_geometry','MLT','MLT_source','N','d_wire')}
                                          for d in md['inductors']]
    if res.get('psr'):
        fixed['psr_Na'] = res['psr']['Na']
        fixed['psr_RfbL'] = res['psr']['RfbL']
        auxiliary = md.get('transformer', {}).get('auxiliary')
        if auxiliary:
            fixed['_fixed_auxiliary'] = copy.deepcopy(auxiliary)
    return fixed


def corners(p, v_in_min=None, v_in_max=None,
            load_fracs=(.1, .25, .5, .75, 1.), include_nominal=True,
            progress=None, cancelled=None):
    from input_voltage_range import has_input_voltage_range, normalize_input_voltage_spec
    ranged = has_input_voltage_range(p)
    if ranged:
        p = normalize_input_voltage_spec(p)
    lo = p.get('V_in_min', p['V_in']*.9) if v_in_min is None else float(v_in_min)
    hi = p.get('V_in_max', p['V_in']*1.1) if v_in_max is None else float(v_in_max)
    fractions = tuple(float(x) for x in load_fracs)
    if not (math.isfinite(lo) and math.isfinite(hi) and 0 < lo <= p['V_in'] <= hi):
        raise ValueError('输入下限 ≤ 标称输入 ≤ 输入上限，且必须为有限正数')
    if not fractions or any(not math.isfinite(x) or not 0 < x <= 1 for x in fractions):
        raise ValueError('负载比例必须为 (0, 1] 内的有限数')
    reference = dict(p, V_in=lo, input_voltage_case='min') if ranged else p
    nominal = evaluate(reference, resolve_input_range=False)
    fixed = pin_hardware(reference, nominal['res'])
    voltages = sorted(set((lo, p['V_in'], hi) if include_nominal else (lo, hi)))
    rows = []
    total = len(voltages)*len(fractions)
    for vin in voltages:
        for frac in fractions:
            if cancelled and cancelled():
                raise InterruptedError('角点分析已取消；不保留不完整结果')
            entry = dict(id=f'C{len(rows)+1:02d}', V_in=vin, load_frac=frac)
            try:
                from isolated_outputs import scale_load
                corner_p=dict(scale_load(fixed,frac), V_in=vin)
                if ranged:
                    corner_p['input_voltage_case']='max' if vin==hi and hi!=lo else 'min' if vin==lo else p['input_voltage_case']
                snap = evaluate(corner_p, resolve_input_range=False)
                res, op = snap['res'], snap['op']
                devices = [res['mag'][k] for k in ('inductor','transformer')
                           if res['mag'].get(k) and res['mag'][k].get('ok')]
                loop = res['loop'] or {}
                entry.update(skipped=False, mode=op['mode'], D=op['D'], f_sw=op['f_sw'],
                             I_L_pk=op['I_L_pk'], V_sw_max=op['V_sw_max'],
                             ripple_pp=res['wf']['ripple_pp'], eta=res['eta'],
                             dT=max((d['dT'] for d in devices), default=None),
                             B_pk=max((d['B_pk'] for d in devices), default=None),
                             fc=loop.get('fc'), pm=loop.get('pm'), min_pm=loop.get('min_pm'),
                             gm_db=loop.get('gm_db'),
                             failed_checks=[c['id'] for c in snap['checks']
                                            if c['state'] in ('review','undefined')],
                             checks=snap['checks'])
            except Exception as exc:
                from calculation_scheduler import CalculationCancelled
                if isinstance(exc, CalculationCancelled):
                    raise
                entry.update(skipped=True, error=f'{type(exc).__name__}: {exc}')
            rows.append(entry)
            if progress:
                progress(len(rows), total, entry['id'])
    valid = [c for c in rows if not c['skipped']]
    worst, worst_cases = {}, {}
    for label, key, fn in [('min_eta','eta',min), ('max_I_L_pk','I_L_pk',max),
                           ('max_ripple_pp','ripple_pp',max), ('max_V_sw_max','V_sw_max',max),
                           ('max_dT','dT',max), ('max_B_pk','B_pk',max), ('min_pm','min_pm',min)]:
        available = [c for c in valid if c.get(key) is not None and math.isfinite(c[key])]
        if available:
            row = fn(available, key=lambda c: c[key])
            worst[label] = row[key]
            worst_cases[label] = dict(id=row['id'], V_in=row['V_in'], load_frac=row['load_frac'])
    if any(c['mode']=='DCM' for c in valid):
        worst['DCM_at_loads'] = sorted(set(c['load_frac'] for c in valid if c['mode']=='DCM'))
    return dict(corners=rows, worst=worst, worst_cases=worst_cases,
                v_in=(lo,hi), load_fracs=list(fractions), fixed_hardware=True,
                hardware={k.removeprefix('_fixed_'): v for k,v in fixed.items() if k.startswith('_fixed_')},
                base_spec=copy.deepcopy(p), include_nominal=include_nominal)


METRICS = [('eta','模型效率','%',100), ('P_total','总损耗','W',1),
           ('ripple_pp','低频纹波','mV',1000), ('I_L_pk','电感 / 原边峰值','A',1),
           ('V_sw_max','主开关最大电压','V',1), ('dT','最高磁件温升','K',1),
           ('fc','所选下降穿越','Hz',1), ('min_pm','所有穿越最小 PM','°',1)]


def metric_values(snap):
    res, op = snap['res'], snap['op']
    devices = [res['mag'][k] for k in ('inductor','transformer')
               if res['mag'].get(k) and res['mag'][k].get('ok')]
    return dict(eta=res['eta'], P_total=res['P_total'], ripple_pp=snap['wf']['ripple_pp'],
                I_L_pk=op['I_L_pk'], V_sw_max=op['V_sw_max'],
                dT=max((d['dT'] for d in devices),default=None),
                fc=(res['loop'] or {}).get('fc'), min_pm=(res['loop'] or {}).get('min_pm'))


def compare(a, b, names=('方案 A','方案 B')):
    va, vb = metric_values(a), metric_values(b)
    rows = []
    for key,label,unit,scale in METRICS:
        x, y = va[key], vb[key]
        rows.append(dict(key=key, name=label, unit=unit,
                         a=x*scale if x is not None else None,
                         b=y*scale if y is not None else None,
                         delta=(y-x)*scale if x is not None and y is not None else None))
    diffs = [dict(key=k,a=a['p'].get(k),b=b['p'].get(k))
             for k in sorted(set(a['p'])|set(b['p'])) if a['p'].get(k)!=b['p'].get(k)
             and not k.startswith('_')]
    from isolated_outputs import output_specs
    def requirements(p):
        rails = output_specs(p)
        return (p['V_in'],[(r['V_out'],r['P_out']) for r in rails] if rails else [(p['V_out'],p['P_out'])])
    same = requirements(a['p']) == requirements(b['p'])
    return dict(names=list(names), metrics=rows, differences=diffs,
                same_requirements=same, a=a, b=b)
