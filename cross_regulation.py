"""Fixed-BOM min/max resistive-load corner estimates for SSR flyback.

No synthetic zero-load bleeder, ideal-ratio answer, or assumed worst corner.
Only DC switched-matrix solutions passing the existing charge/energy tests
enter the observed envelope. A failed corner makes that envelope incomplete.
"""
import copy
from itertools import product
import math

NOTE = ('固定频率 SSR 反激的逐对耦合矩阵实验模型；固定磁芯、整数匝数、线径、DCR、kij、钳位与控制参数。'
        '输出及负载功率在防反管后，反馈在所选路防反管前；各路以含整流/防反压降的匝比参考电压和所选功耗换算恒阻负载。'
        '仅主反馈路理想直流稳压；结果是最小/最大负载组合及输入端点的稳态采样包络，'
        '不是连续区间的严格极值，也不是负载阶跃过冲；不含 Coss/Cj、控制器跳周期与完整寄生谐振。'
        '0 W 真空载缺少泄放/预负载模型，不给出有限电压承诺。')
SOURCE = 'https://www.ti.com/document-viewer/lit/html/SSZTCW3/GUID-9BE5B4A2-3166-4329-A3F0-4F836580FCC7'


def load_label(case):
    return '；'.join(f'OUT{i+1}={v:g}W' for i,v in enumerate(case['powers']))


def summarize(rails, cases, feedback):
    valid = [c for c in cases if c.get('status') == 'ok']
    complete = bool(cases) and len(valid) == len(cases)
    summary = []
    for j, rail in enumerate(rails):
        item = dict(id=rail['id'], name=rail['name'], feedback=rail['id']==feedback,
                    V_reference=rail['V_out'], P_min=rail['P_out_min'], P_max=rail['P_out'],
                    complete=complete, V_min=None, V_max=None, min_case=None, max_case=None,
                    deviation_min_pct=None, deviation_max_pct=None, span_pct=None,
                    cross_only_pct=None)
        if valid:
            lo = min(valid, key=lambda c:c['voltages'][j]); hi = max(valid, key=lambda c:c['voltages'][j])
            vmin,vmax = lo['voltages'][j],hi['voltages'][j]
            ref = rail['V_out']
            groups = {}
            for c in valid:
                # Hold this rail's load AND Vin fixed: other loads only.
                groups.setdefault((c['V_in'],c['powers'][j]),[]).append(c['voltages'][j])
            item.update(V_min=vmin,V_max=vmax,min_case=lo['id'],max_case=hi['id'],
                        deviation_min_pct=100*(vmin/ref-1),deviation_max_pct=100*(vmax/ref-1),
                        span_pct=100*(vmax-vmin)/ref,
                        cross_only_pct=max((max(v)-min(v))/ref*100 for v in groups.values()))
        summary.append(item)
    return summary


def scan_cross_regulation(p, *, reference_result=None, voltages=None,
                          known_ops=None, cancelled=None, progress=None):
    from input_voltage_range import normalize_input_voltage_spec, _cancellation_scope
    from calculation_scheduler import check_calculation_cancelled, CalculationCancelled
    from isolated_outputs import output_specs
    from power_stage import compute_operating_point
    from loss_model import compute_design
    from analysis_workflows import pin_hardware
    base = normalize_input_voltage_spec(p)
    rails = output_specs(base)
    result = dict(supported=False,complete=False,feedback_output=int(base.get('feedback_output',1)),
                  rails=copy.deepcopy(rails),cases=[],summary=[],note=NOTE,source=SOURCE,
                  scope='min-max-load-corners-and-input-endpoints',error=None)
    if (base['topology'] not in ('FLYBACK','ACF-FORWARD') or base.get('feedback_mode','SSR')!='SSR' or len(rails)<2
            or not base.get('coupling_config',{}).get('enabled')):
        result['error']='需要至少两路输出、固定频率反激/有源钳位正激 SSR，并启用非理想绕组耦合矩阵。'
        return result
    if base['topology']=='ACF-FORWARD':
        result['note']='正激物理周期/各路电荷平衡；固定同一硬件与完整 kij，单路主反馈，端口恒阻负载。包含钳位和恒定 Coss/Cj，不包含真实芯片 PSM、温度及非线性电容。高频电流网格敏感不等于直流电压包络未收敛；两项独立标注。'
        result['source']='https://www.ti.com/lit/an/slua535a/slua535a.pdf'
    from winding_coupling import resolve_winding_model
    if resolve_winding_model(base,rails)['ideal']:
        result['error']='全部 kij=1 是理想回退，不具备交叉调整率物理模型；请填写实际正定耦合矩阵。'
        return result
    vins = sorted(set(voltages if voltages is not None else (base['V_in_min'],base['V_in_max'])))
    if not vins or any(isinstance(v,bool) or not isinstance(v,(int,float)) or not math.isfinite(v) or v<=0 for v in vins):
        raise ValueError('交叉调整率输入电压必须为有限正数')
    combinations = list(product(*(tuple(dict.fromkeys((r['P_out'],r['P_out_min']))) for r in rails)))
    with _cancellation_scope(cancelled):
        check_calculation_cancelled()
        try:
            reference_p = dict(base,V_in=base['V_in_min'],input_voltage_case='min')
            reference = reference_result if reference_result is not None else compute_design(reference_p)
            fixed = pin_hardware(reference_p,reference)
        except CalculationCancelled:
            raise
        except Exception as exc:
            result['error']='固定硬件参考设计失败：'+str(exc)
            return result
        result.update(supported=True,fixed_hardware=True,voltages=vins,
                      hardware_reference_voltage=base['V_in_min'],total_cases=len(vins)*len(combinations))
        result['varied_outputs']=[r['id'] for r in rails if r['P_out_min']!=r['P_out']]
        if not result['varied_outputs']:
            result['note']+='所有最小功耗等于最大功耗，未覆盖轻载变化；单点跨度为 0 不代表全负载交叉调整率为 0。'
        for vin in vins:
            for powers in combinations:
                check_calculation_cancelled()
                case = dict(id=f'X{len(result["cases"])+1:03d}',V_in=float(vin),powers=list(powers),
                            status='unavailable',error=None,voltages=None,actual_powers=None,D=None,modes=None)
                if any(v<=0 for v in powers):
                    case['error']='包含 0 W 真空载；未指定泄放/预负载，当前恒阻周期模型不计算此角点。'
                else:
                    q = copy.deepcopy(fixed);q['V_in']=float(vin)
                    for rail, power in zip(q['outputs'],powers):
                        rail.update(P_out=power,P_out_min=min(rail['P_out_min'],power))
                    q['P_out']=sum(powers)
                    try:
                        nominal = all(power==rail['P_out'] for power,rail in zip(powers,rails))
                        op = (known_ops or {}).get(vin) if nominal else None
                        op = op if op is not None else compute_operating_point(q)
                        if op.get('coupled_solution') is None and op.get('acf_solution') is None:
                            raise ValueError('没有物理耦合解，不使用理想匝比替代')
                        children = op['output_ops']
                        values = [float(r['V_out']) for r in children]
                        if any(not math.isfinite(v) or v<=0 for v in values):
                            raise ValueError('解算电压无效')
                        case.update(status='ok',voltages=values,D=float(op['D']),
                                    actual_powers=[float(r['P_out']) for r in children],
                                    modes=[r.get('branch_mode',r['mode']) for r in children],
                                    residual=(op.get('coupled_model') or op['acf_model'])['normalized_residual'])
                    except CalculationCancelled:
                        raise
                    except Exception as exc:
                        case.update(status='failed',error=str(exc))
                result['cases'].append(case)
                if progress:progress(len(result['cases']),result['total_cases'],case['id'])
        result['summary']=summarize(rails,result['cases'],result['feedback_output'])
        result['successful_cases']=sum(c['status']=='ok' for c in result['cases'])
        result['complete']=result['successful_cases']==result['total_cases']
        return result


def for_input(result, voltage):
    selected = dict(result)
    selected['cases']=[c for c in result['cases'] if c['V_in']==voltage]
    selected['summary']=summarize(result['rails'],selected['cases'],result['feedback_output'])
    selected['total_cases']=len(selected['cases'])
    selected['successful_cases']=sum(c['status']=='ok' for c in selected['cases'])
    selected['complete']=bool(selected['cases']) and selected['successful_cases']==selected['total_cases']
    selected['voltages']=[voltage]
    return selected


def attach_to_endpoints(bundle, *, cancelled=None, progress=None):
    p=bundle['base_spec']
    if len(p.get('outputs',[]))<2:return bundle
    cases=bundle['cases'];reference=cases[0].get('result')
    if reference is None:
        return bundle
    result=scan_cross_regulation(bundle.get('fixed_spec') or p,reference_result=reference,
        known_ops={c['voltage']:c['result']['op'] for c in cases if c.get('result') and not c.get('error')},
        cancelled=cancelled,progress=progress)
    bundle['cross_regulation']=result
    for case in cases:
        if case.get('result') is not None:
            # Equal Vin endpoints may share a result object; identical slice.
            case['result']['cross_regulation']=for_input(result,case['voltage'])
    return bundle
