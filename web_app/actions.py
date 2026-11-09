"""Read-only advanced desktop workflows, executed only in the numerical worker.

The result belongs to the input snapshot. ``spec_updates`` are proposals: neither
the worker's DesignRun nor the browser draft is changed by an action.
"""
from contextlib import contextmanager
import copy
import math
from pathlib import Path

ACTIONS = {'tune', 'compensate', 'sweep', 'find_target', 'optimize',
           'corners', 'loop_response', 'winding_preview'}
VARIABLES = {'f_sw', 'L', 'N', 'C_out', 'Rds_on', 'Bmax', 'Lm_forward', 'C_clamp'}
_FIELDS = {
    'tune': {'fc', 'pm', 'controller_type'},
    'compensate': {'key', 'direction', 'type2', 'inputs'},
    'sweep': {'variable', 'minimum', 'maximum', 'points', 'load_frac'},
    'find_target': {'variable', 'minimum', 'maximum', 'points', 'load_frac', 'target_eta'},
    'optimize': {'variables', 'bounds', 'load_frac', 'maxiter', 'popsize', 'seed'},
    'corners': {'v_in_min', 'v_in_max', 'load_fracs', 'include_nominal'},
    'loop_response': {'load_output'}, 'winding_preview': {'config', 'render_chart'},
}
_INPUTS = {
    'opamp3': {'R1', 'Vref', 'R2', 'R3', 'C1', 'C2', 'C3'},
    'gm3': {'R1u', 'gm', 'R1', 'R2', 'R3', 'C1', 'C2', 'C3'},
    'tl431nf': {'CTR', 'R_LED', 'Rpullup', 'Copto', 'R1', 'R2', 'R3', 'C1', 'C2', 'C3'},
    'tl431f': {'CTR', 'R_LED', 'Rpullup', 'Copto', 'R1', 'C1', 'R_pz', 'C_pz', 'C2'},
}
_DESKTOP_TOPO_LABELS = {
    'opamp3': '普通运放补偿网络（跟随⑤页类型）',
    'gm3': '跨导运放补偿网络（跟随⑤页类型）',
    'tl431nf': 'TL431+光耦 — 无快车道 (LED 接独立偏置)',
    'tl431f': 'TL431+光耦 — 快车道 (LED 接 Vout)',
}


def _number(value, label, low=0., high=1e12, *, integer=False):
    if (isinstance(value, bool) or not isinstance(value, (int, float)) or
            not math.isfinite(value) or not low <= value <= high or
            (integer and int(value) != value)):
        raise ValueError(f'{label} 必须为 [{low:g}, {high:g}] 内的有限' + ('整数' if integer else '数值'))
    return int(value) if integer else float(value)


def validate_options(action, options):
    """Cheap transport validation, no model imports or arbitrary expressions."""
    if action not in ACTIONS or not isinstance(options, dict):
        raise ValueError('未知高级操作或无效选项')
    opts = copy.deepcopy(options)
    unknown = set(opts)-_FIELDS[action]-{'case'}
    if unknown:
        raise ValueError('未知操作选项：'+', '.join(sorted(unknown)))
    if opts.get('case', 'Vinmin') not in ('Vinmin', 'Vinmax'):
        raise ValueError('工况须为 Vinmin 或 Vinmax')
    opts.setdefault('case', 'Vinmin')
    if action == 'tune':
        opts['fc'] = _number(opts.get('fc', 1000.), 'fc', 1e-6, 1e8)
        opts['pm'] = _number(opts.get('pm', 60.), 'PM', 1., 179.)
        if opts.get('controller_type', 'auto') not in ('auto', 'type2', 'type3'):
            raise ValueError('补偿器类型无效')
    elif action == 'compensate':
        key = opts.get('key', 'opamp3')
        if not isinstance(key, str) or key not in _INPUTS or opts.get('direction', 'fwd') not in ('fwd', 'rev'):
            raise ValueError('补偿网络或计算方向无效')
        if not isinstance(opts.get('type2', False), bool):
            raise ValueError('type2 须为布尔值')
        values = opts.get('inputs', {})
        if not isinstance(values, dict) or set(values)-_INPUTS[key]:
            raise ValueError('补偿元件输入包含未知字段')
        opts['inputs'] = {k: _number(v, k) for k, v in values.items()}
    elif action in ('sweep', 'find_target', 'optimize'):
        opts['load_frac'] = _number(opts.get('load_frac', 1.), '负载比例', .01, 1.)
        if action == 'optimize':
            variables, bounds = opts.get('variables'), opts.get('bounds')
            if (not isinstance(variables, list) or not 1 <= len(variables) <= 3 or
                    any(not isinstance(v, str) or v not in VARIABLES for v in variables) or
                    len(set(variables)) != len(variables)):
                raise ValueError('优化变量须为 1–3 个不重复的受支持参数')
            if not isinstance(bounds, list) or len(bounds) != len(variables):
                raise ValueError('每个优化变量必须有一组上下界')
            opts['bounds'] = [_bounds(pair) for pair in bounds]
            for k, default, lo, hi in (('maxiter', 8, 1, 20), ('popsize', 5, 5, 10), ('seed', 0, 0, 1000000)):
                opts[k] = _number(opts.get(k, default), k, lo, hi, integer=True)
        else:
            if not isinstance(opts.get('variable'), str) or opts.get('variable') not in VARIABLES:
                raise ValueError('扫描变量不受支持')
            opts['minimum'], opts['maximum'] = _bounds([opts.get('minimum'), opts.get('maximum')])
            opts['points'] = _number(opts.get('points', 21), '扫描点数', 5, 41, integer=True)
            if action == 'find_target':
                opts['target_eta'] = _number(opts.get('target_eta', .9), '目标效率', .01, 1.)
    elif action == 'corners':
        for k in ('v_in_min', 'v_in_max'):
            if k in opts:
                opts[k] = _number(opts[k], k, 1e-6, 1e6)
        fractions = opts.get('load_fracs', [.1, .5, 1.])
        if not isinstance(fractions, list) or not 1 <= len(fractions) <= 8:
            raise ValueError('角点负载点数须为 1–8')
        opts['load_fracs'] = [_number(v, '角点负载比例', .01, 1.) for v in fractions]
        if not isinstance(opts.get('include_nominal', True), bool):
            raise ValueError('include_nominal 须为布尔值')
    elif action == 'loop_response':
        opts['load_output'] = _number(opts.get('load_output', 1), '负载扰动输出编号', 1, 6, integer=True)
    elif action == 'winding_preview':
        from winding_layout import validate_winding_config
        opts['config'] = validate_winding_config(opts.get('config', {}))
        if not isinstance(opts.get('render_chart', True), bool):
            raise ValueError('render_chart 须为布尔值')
    return opts


def _bounds(pair):
    if not isinstance(pair, list) or len(pair) != 2:
        raise ValueError('上下界须为二元素列表')
    lo, hi = [_number(v, '边界', 1e-15) for v in pair]
    if lo >= hi:
        raise ValueError('下界必须小于上界')
    return [lo, hi]


@contextmanager
def _cancellation(cancelled):
    # Reuse the desktop solver's deeply nested cancellation hooks. This module
    # runs only on the single owned process, so this thread-local has one owner.
    import calculation_scheduler as scheduler
    previous = getattr(scheduler._CURRENT, 'cancelled', None)
    scheduler._CURRENT.cancelled = cancelled
    try:
        scheduler.check_calculation_cancelled()
        yield
        scheduler.check_calculation_cancelled()
    finally:
        scheduler._CURRENT.cancelled = previous


def _figure(path, draw, size=(11.8, 6.5)):
    from matplotlib.figure import Figure
    from matplotlib.backends.backend_agg import FigureCanvasAgg
    from matplotlib import rc_context
    from power_charts import POWER_CHART_STYLE
    with rc_context(dict(POWER_CHART_STYLE, **{'font.family': POWER_CHART_STYLE['font.sans-serif'], 'font.size': 11})):
        fig = Figure(figsize=size, dpi=120)
        FigureCanvasAgg(fig)
        try:
            draw(fig)
            fig.tight_layout(pad=1.6)
            fig.savefig(path, dpi=120, facecolor='white')
        finally:
            fig.clear()


def execute(run, action, options, path, *, cancelled=lambda: False, progress=None):
    """Return bounded strict JSON, optional PNG, and explicit draft updates."""
    from design_engine.contracts import json_value
    opts = validate_options(action, options)
    case = next((row for row in run.runtime_bundle()['cases'] if row['id'] == opts['case']), None)
    if not case or case.get('error') or not case.get('result'):
        raise ValueError('该输入工况没有成功计算结果')
    p, result = case['p'], case['result']
    with _cancellation(cancelled):
        if action == 'tune':
            data = _tune(p, result, opts, path)
        elif action == 'compensate':
            data = _compensate(p, result, opts, path)
        elif action in ('sweep', 'find_target', 'optimize'):
            data = _optimization(p, action, opts, path, cancelled, progress)
        elif action == 'corners':
            from analysis_workflows import corners
            data = corners(p, opts.get('v_in_min'), opts.get('v_in_max'),
                opts['load_fracs'], opts.get('include_nominal', True), progress=progress, cancelled=cancelled)
            def draw(fig):
                ax = fig.subplots()
                for vin in sorted({r['V_in'] for r in data['corners']}):
                    rows = [r for r in data['corners'] if r['V_in'] == vin and not r['skipped']]
                    ax.plot([r['load_frac']*100 for r in rows], [r['eta']*100 for r in rows], 'o-', label=f'Vin={vin:g} V')
                ax.set(xlabel='负载 / %', ylabel='模型效率 / %', title='固定硬件 · 输入电压与负载角点')
                ax.grid(alpha=.2); ax.legend()
            _figure(path, draw)
        elif action == 'loop_response':
            data = _loop_response(result, opts, path)
        else:
            from winding_layout import transformer_windings, assess_winding_window, build_automatic_layer_plan, draw_winding_cross_section
            windings = transformer_windings(result)
            if not windings:
                raise ValueError('当前工况没有有效变压器，不能预览绕制')
            preview_error = None
            try:
                assessment = assess_winding_window(windings, opts['config'])
            except ValueError as exc:
                preview_error = str(exc)
                assessment = dict(config=copy.deepcopy(opts['config']), configured=True,
                    status='invalid_plan', fits=None, windings=[], physical_layers=[],
                    total_layer_count=0, warnings=[preview_error])
            try:
                automatic = build_automatic_layer_plan(windings, dict(opts['config'], layer_plan=[]))
                plan_note = []
            except ValueError as exc:
                # An undersized window still deserves its overflow drawing;
                # failure to create an editable auto plan is not a lost preview.
                automatic, plan_note = [], ['自动逐层计划不可用：'+str(exc)]
            def draw(fig):
                ax = fig.subplots()
                if preview_error:
                    ax.axis('off')
                    ax.text(.5, .5, '当前手动排层需修正\n'+preview_error, ha='center', va='center', wrap=True)
                else:
                    draw_winding_cross_section(ax, assessment)
            if opts.get('render_chart', True) or not assessment.get('editable'):
                _figure(path, draw)
            data = dict(windings=windings, assessment=assessment, automatic_plan=automatic,
                preview_error=preview_error,
                notes=['仅基于当前已计算匝数和线材的几何预览；不修改电气快照。']+plan_note)
    data.update(action=action, case=opts['case'], snapshot_unchanged=True)
    if Path(path).is_file():
        data.update(path=str(path), media_type='image/png', has_chart=True)
    else:
        data['has_chart'] = False
    return json_value(data)


def _tune(p, result, opts, path):
    import numpy as np
    from plants import build_loop_models, make_compensator, resolve_controller_type
    from loop_tuning import kfactor_tune, analyze_loop
    op = result['op']
    psr = p.get('feedback_mode') == 'PSR-MP6005'
    (plant, _, _), _device = build_loop_models(p, op)
    metadata = getattr(plant, '_loop_metadata', {})
    if metadata.get('experimental') and metadata['inner_spectral_radius'] >= 1:
        raise ValueError('周期内环谱半径 ≥1；先修正斜坡或工况，未提出外环参数')
    fc, pm = opts['fc'], opts['pm']
    limit = op['f_sw']/(10. if psr else 6.)
    if p['topology'] == 'ACF-FORWARD':
        limit = min(limit, op['fc_recommended_max'])
    fc = min(fc, limit)
    kind = 'type2' if psr else resolve_controller_type(opts.get('controller_type', p.get('controller_type', 'auto')), p['control_mode'])
    design = kfactor_tune(plant, fc, pm, kind)
    notes = ['整定为模型初值，实物须验证偏置、器件误差与 FRA。']
    if fc != opts['fc']:
        notes.append(f'沿用桌面开关频率 / 有源钳位限制，实际目标 fc={fc:g} Hz。')
    if not design['feasible']:
        return dict(feasible=False, design=design, achieved=None, spec_updates={}, notes=notes+['所需相位提升超出所选补偿器范围，未提出参数。'])
    updates = dict(fc_target=fc, pm_target=pm)
    tuned = dict(p)
    if psr:
        from mp6005 import compensation_parts, design_psr
        updates.update(compensation_parts(design))
        tuned.update(updates)
        # The physical MP6005 COMP network, not an SSR surrogate, is verified.
        candidate_op = copy.deepcopy(op)
        candidate_op['psr'] = design_psr(tuned, candidate_op, result['mag'].get('transformer'))
        models, _ = build_loop_models(tuned, candidate_op)
    else:
        updates['controller_type'] = kind
        updates.update({k: design[k] for k in ('KP', 'fz1', 'fz2', 'fp1', 'fp2') if design.get(k) is not None})
        if kind=='type2' and p.get('__comp'):
            updates['__comp']=dict(copy.deepcopy(p['__comp']),type2=False)
        tuned.update(updates)
        candidate = make_compensator(tuned).get_transfer_function()
        models = (plant, candidate, plant*candidate)
    loop = analyze_loop(tuned, models, op)
    achieved = {k: loop.get(k) for k in ('fc', 'pm', 'min_pm', 'gm_db', 'gm_infinite', 'all_crosses', 'closed_loop_stable')}
    # Coupled state-space stability is available from the shared scan. For all
    # other models check the actual closed-loop poles rather than PM alone.
    import control as ct
    stable = bool(np.all(np.real(ct.poles(ct.feedback(models[2], 1))) < 0))
    achieved['closed_loop_stable'] = stable
    feasible = stable and loop['fc'] is not None and loop['min_pm'] is not None and loop['min_pm'] >= pm-1
    if not feasible:
        notes.append('候选未通过闭环极点或全部穿越裕度校验，未提出写回参数。')
    def draw(fig):
        axes = fig.subplots(2, 1)
        axes[0].semilogx(loop['f'], 20*np.log10(np.maximum(abs(loop['gains'][2]), 1e-300)))
        axes[1].semilogx(loop['f'], loop['phases'][2])
        axes[0].axhline(0, color='#e05555', ls='--'); axes[1].axhline(-180, color='#e05555', ls='--')
        for ax in axes:
            ax.axvline(fc, color='#27885e', ls=':'); ax.grid(alpha=.2); ax.set_xlabel('频率 / Hz')
        axes[0].set(ylabel='环路幅值 / dB', title='候选补偿 · 回代校验（未应用）'); axes[1].set_ylabel('相位 / °')
    _figure(path, draw)
    return dict(feasible=bool(feasible), design=design, achieved=achieved, spec_updates=updates if feasible else {}, notes=notes)


def _compensate(p, result, opts, path):
    from compensation_report import compensation_snapshot, NETWORKS
    if p.get('feedback_mode') == 'PSR-MP6005':
        raise ValueError('MP6005 使用物理 COMP 网络；SSR 四种参考网络不适用，请使用 PSR 自动整定或输入 Rcomp/Ccomp/Cpole')
    key, direction = opts.get('key', 'opamp3'), opts.get('direction', 'fwd')
    state = dict(key=key, topo=_DESKTOP_TOPO_LABELS[key], encoding='si', dir=direction, type2=opts.get('type2', False),
        vars={k: dict(v=v, u='') for k, v in opts['inputs'].items()})
    from app_resources import resource_path
    image = resource_path('comp_images')/NETWORKS[key][1]
    if not image.is_file():
        raise ValueError('当前网络的参考电路图资源缺失')
    Path(path).write_bytes(image.read_bytes())
    try:
        data = compensation_snapshot(p, result['op'], state)
    except KeyError as exc:
        raise ValueError('补偿网络缺少输入元件：'+str(exc).strip("'")) from None
    except (ValueError, ZeroDivisionError, OverflowError) as exc:
        # Reference drawings remain usable when a requested network cannot
        # realize the current loop target. Never invent substitute RC values.
        return dict(key=key, direction=direction, parts={}, realized={}, checks=[],
            targets={k: p[k] for k in ('KP', 'fz1', 'fz2', 'fp1', 'fp2')},
            buildable=False, notes=['当前网络不能按这些输入实现：'+str(exc)], spec_updates={'__comp': state})
    checks, realized = [], {}
    updates = {'__comp': state}
    for name, field in (('KP', 'KP'), ('fz1', 'wz1'), ('fz2', 'wz2'), ('fp1', 'wp1'), ('fp2', 'wp2')):
        if field not in data['active_fields']:continue
        divisor = 1 if name == 'KP' else 2*math.pi
        target, actual = data['targets'][field]/divisor, data['realized'][field]/divisor
        realized[name] = actual if math.isfinite(actual) else None
        checks.append(dict(name=name, target=target, actual=realized[name],
            ok=math.isfinite(actual) and abs(actual-target) <= 1e-6*max(abs(target), 1e-30),
            note='省略 / 无限远' if not math.isfinite(actual) else '代数回代；实物可实现性另见提示'))
        if direction == 'rev' and data['buildable']:
            updates[name] = actual if math.isfinite(actual) else 1e9
    if direction == 'rev' and data['buildable']:
        from comp_design import controller_updates
        updates.update(controller_updates(data['realized']))
        data['notes'].append('按实际网络阶数写回；标准二型仅写KP/fz1/fp1，未启用的第二零极点不参与。')
    data.update(realized=realized, targets={row['name']: row['target'] for row in checks}, checks=checks, spec_updates=updates)
    return data


def _optimization(p, action, opts, path, cancelled, progress):
    import numpy as np
    import optimizer
    from calculation_scheduler import calculate_optimization, CalculationCancelled
    # Desktop scans are design alternatives, not fixed-hardware production
    # corners. Strip only internally generated frozen geometry, retain inputs.
    p = {k: copy.deepcopy(v) for k, v in p.items() if not k.startswith('_fixed_')}
    variables = opts['variables'] if action == 'optimize' else [opts['variable']]
    for key in variables:
        if key == 'f_sw' and p['topology'] == 'QR-FLYBACK':
            raise ValueError('QR 频率由工作点求解，不能直接扫描 f_sw')
        if key in ('Lm_forward', 'C_clamp') and p['topology'] != 'ACF-FORWARD':
            raise ValueError('Lm_forward / C_clamp 仅适用于有源钳位正激')
        if key == 'N' and p['topology'] not in ('FLYBACK', 'QR-FLYBACK', 'ACF-FORWARD'):
            raise ValueError('当前非隔离拓扑没有变压器匝比 N')
    optimizer._check_variables(p, variables)
    notes = ['扫描 / 优化沿用桌面模型，可重新选择自动磁件；不等同于固定硬件角点，也不构成器件选型结论。']
    if action == 'optimize':
        # Reuse the unchanged desktop objective/optimizer; wrapper checks the
        # shared cancellation before/after every physical solve. The legacy
        # optimizer catches Exception, so a private BaseException crosses its
        # feasibility guards and is immediately converted back at this boundary.
        class StopOptimization(BaseException):
            pass
        class EvaluationBudget(BaseException):
            pass
        original = optimizer.compute_design
        count = 0
        budget = max(100, opts['popsize']*len(variables)*(opts['maxiter']+1)+100)
        best_seen = None
        def checked(spec):
            nonlocal count, best_seen
            if cancelled():
                raise StopOptimization()
            if count >= budget:
                raise EvaluationBudget()
            count += 1
            try:
                value = original(spec)
            except CalculationCancelled:
                raise StopOptimization() from None
            score = -value['eta']+(.25 if value['op']['mode'] == 'DCM' else 0.)
            if math.isfinite(score) and (best_seen is None or score < best_seen['fun']):
                best_seen = dict(best={k: float(spec[k]) for k in variables}, eta=value['eta'], fun=score)
            if progress and count % 5 == 0:
                progress(count, max(count+1, opts['popsize']*len(variables)*(opts['maxiter']+1)), f'候选 {count}')
            if cancelled():
                raise StopOptimization()
            return value
        optimizer.compute_design = checked
        try:
            try:
                data = optimizer.optimize_efficiency(p, variables, opts['bounds'], opts['load_frac'],
                    seed=opts['seed'], maxiter=opts['maxiter'], popsize=opts['popsize'])
            except StopOptimization:
                raise CalculationCancelled() from None
            except EvaluationBudget:
                data = dict(best_seen or dict(best={}, eta=float('nan'), fun=None), ok=False, nit=None)
                notes.append('达到包含精修阶段在内的硬评估次数上限，已停止；保留已求解候选，不宣称收敛。')
        finally:
            optimizer.compute_design = original
        data.update(spec_updates=data['best'] if math.isfinite(data['eta']) else {}, notes=notes,
                    evaluations=count, evaluation_budget=budget, limited_budget=True)
        if not data['ok']:
            notes.append('搜索预算已用尽或未收敛；best 仅为当前找到的候选，不保证全局最优。')
        return data
    data = calculate_optimization(dict(kind='sweep', p=p, frac=opts['load_frac'],
        var=variables[0], lo=opts['minimum'], hi=opts['maximum'], n=opts['points']), cancelled)
    values, etas = data['values'], data['etas']
    target = optimizer.find_target(values, etas, opts['target_eta']) if action == 'find_target' else None
    def draw(fig):
        ax = fig.subplots()
        ax.plot(values, etas*100, 'o-', markersize=3)
        if variables[0] in optimizer._LOG_VARS:
            ax.set_xscale('log')
        if action == 'find_target':
            ax.axhline(opts['target_eta']*100, ls='--', color='#e05555', label='目标效率')
            ax.legend()
        ax.set(xlabel=variables[0]+' / SI', ylabel='模型效率 / %', title='参数扫描 · '+variables[0])
        ax.grid(alpha=.2)
    _figure(path, draw)
    return dict(variable=variables[0], rows=[dict(value=float(x), eta=float(y)) for x, y in zip(values, etas)],
        target_value=target, target_eta=opts.get('target_eta'),
        spec_updates={variables[0]: target} if target is not None else {}, notes=notes)


def _loop_response(result, opts, path):
    import numpy as np
    from loop_charts import draw_multi_output_response
    loop = result.get('loop') or {}
    data = loop.get('multi_output')
    if not data:
        raise ValueError('当前工况没有可用多路输出线性模型；不生成虚假的独立环路或负载矩阵')
    selected = opts['load_output']-1
    if selected >= len(data['outputs']):
        raise ValueError('负载扰动输出编号超出当前输出数量')
    indices = np.unique(np.linspace(0, len(loop['f'])-1, min(800, len(loop['f'])), dtype=int))
    rows = []
    for i, rail in enumerate(data['outputs']):
        ref = data['reference'][i, indices]
        load = data['load'][i, selected, indices] if data['load'] is not None else None
        rows.append(dict(id=rail['id'], reference_db=20*np.log10(np.maximum(abs(ref), 1e-300)),
            reference_phase=np.degrees(np.unwrap(np.angle(ref))),
            load_db=20*np.log10(np.maximum(abs(load), 1e-300)) if load is not None else None,
            load_phase=np.degrees(np.unwrap(np.angle(load))) if load is not None else None))
    _figure(path, lambda fig: draw_multi_output_response(fig.subplots(2, 2), loop, selected+1))
    return dict(frequency=loop['f'][indices], outputs=rows, feedback_output=data['feedback_output'],
        load_output=selected+1, dc_load=data['dc_load'], model=loop.get('model'),
        notes=['只闭合主反馈路，各路共用同一闭环分母；负载扰动为局部小信号，不等同于大信号交叉调整率。']+
        (['理想匝比近似没有独立负载动态，未生成负载扰动曲线。'] if data['load'] is None else []))
