#!/usr/bin/env python
"""Headless CLI for the switching-power-supply design engine (AI tool chain).

    python cli.py design    --spec spec.json --out report.json [--md report.md]
    python cli.py corners   --spec spec.json --out corners.json
    python cli.py transient --spec spec.json --di 2.0 [--fc 10e3] [--out t.json]
    python cli.py autotune  --spec spec.json --fc 10e3 --pm 60 [--out comp.json]

Spec format: JSON object with DEFAULT_PARAMS keys (SI values) or config-file
{'v': .., 'u': prefix} objects, e.g.

    {"topology": "BUCK", "V_in": 12, "V_out": 5, "P_out": 5,
     "f_sw": 100e3, "L": 47e-6, "C_out": 100e-6, "pm_target": 60}
"""

import argparse
import json
import sys
import os
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import design_api  # noqa: E402


def _read_spec(path):
    with open(path, 'r', encoding='utf-8') as f:
        return json.load(f)


def _write(path, data):
    if not path:
        return
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    with open(path, 'w', encoding='utf-8') as f:
        json.dump(data, f, ensure_ascii=False, indent=2, default=float)
    print('written', path)


def report_markdown(r):
    """Human-readable Markdown summary of a run_design report."""
    if not r.get('ok'):
        return f'# 设计失败\n\n```\n{r.get("error")}\n```'
    L = []
    op, lo, mg = r['operating_point'], r['losses'], r['magnetics']
    L.append(f"# 设计报告 — {r['topology']}")
    L.append('')
    L.append('## 工作点')
    L.append(f"- D = {op['D']:.3f}  ({op['mode']})  f_sw = {op['f_sw']:.0f} Hz")
    L.append(f"- I_L: avg {op['I_L_avg']:.2f} A / rms {op['I_L_rms']:.2f} A / pk {op['I_L_pk']:.2f} A")
    L.append(f"- 开关管: rms {op['I_sw_rms']:.2f} A, V_ds max {op['V_sw_max']:.1f} V")
    L.append(f"- 整流管: rms {op['I_d_rms']:.2f} A, V_r max {op['V_d_max']:.1f} V")
    L.append(f"- 输出纹波 pp = {op['ripple_pp'] * 1e3:.1f} mV")
    L.append('')
    L.append('## 损耗与效率')
    L.append(f"- η = **{lo['eta'] * 100:.2f} %** (模型计算值, 偏高)")
    L.append(f"- 总损耗 {lo['P_total']:.3f} W = 半导体 {lo['P_semi']:.3f} + 磁件 {lo['P_mag']:.3f}"
             f" + 电容 {lo['P_cap']:.3f} + 采样 {lo['P_sense']:.3f} + RCD {lo['P_rcd']:.3f}"
             f" + 钳位电容 ESR {lo.get('P_clamp',0):.3f}"
             f" + 防反二极管 {lo['P_din']:.3f}/{lo['P_dout']:.3f}")
    L.append('')
    L.append('## 磁件')
    if mg.get('ok'):
        L.append(f"- 磁芯 {mg['core']}, B_pk = {mg['B_pk']:.3f} T, ΔT = {mg['dT']:.1f} K")
        L.append(f"- P_cu = {mg['P_cu']:.3f} W, P_core = {mg['P_core']:.3f} W, fill = {mg['fill'] * 100:.0f}%")
    else:
        L.append(f"- 设计失败: {mg.get('reason', '')}")
    if 'active_clamp' in r:
        ac = r['active_clamp']
        L.append('')
        L.append('## 有源钳位正激 (低侧钳位)')
        L.append(f"- V_clamp = {ac['V_clamp']:.2f} V, V_reset = {ac['V_reset']:.2f} V, "
                 f"钳位隆起 ≈ {ac['V_clamp_hump']:.2f} V")
        L.append(f"- Lm = {ac['Lm_forward']*1e6:.1f} µH, C_clamp = {ac['C_clamp']*1e9:.1f} nF; "
                 f"建议 fc ≤ {ac['fc_recommended_max']:.0f} Hz")
        for name, dev in mg.get('devices', {}).items():
            L.append(f"- {name}: {dev.get('core','')}, B_pk = {dev.get('B_pk',0):.3f} T, "
                     f"P_core/P_cu = {dev.get('P_core',0):.3f}/{dev.get('P_cu',0):.3f} W")
    L.append('')
    L.append('## 设计检查')
    L.append('')
    L.append('| 检查项 | 值 | 限值 | 结果 |')
    L.append('|---|---|---|---|')
    for c in r['checks']:
        mark = '—' if c['pass_'] is None else '✅' if c['pass_'] else '❌'
        value='—' if c['value'] is None else f"{c['value']:.4g}"
        limit='—' if c['limit'] is None else f"{c['limit']:.4g}"
        L.append(f"| {c['name']} | {value} {c['unit']} | {c['comparison']} {limit} | {mark} |")
    L.append('')
    if r['failed_checks']:
        L.append(f"**未通过**: {', '.join(r['failed_checks'])}")
    if r['warnings']:
        L.append('')
        L.append('## 提示')
        for w in r['warnings']:
            L.append(f'- {w}')
    return '\n'.join(L)


def main():
    ap = argparse.ArgumentParser(description='开关电源设计引擎 (无头模式)')
    sub = ap.add_subparsers(dest='cmd', required=True)

    d = sub.add_parser('design', help='完整设计报告')
    d.add_argument('--spec', required=True)
    d.add_argument('--out', default=None)
    d.add_argument('--md', default=None)

    c = sub.add_parser('corners', help='角点分析 (Vin × 负载)')
    c.add_argument('--spec', required=True)
    c.add_argument('--vin-min', type=float, default=None)
    c.add_argument('--vin-max', type=float, default=None)
    c.add_argument('--out', default=None)

    t = sub.add_parser('transient', help='负载阶跃 ΔV 估算')
    t.add_argument('--spec', required=True)
    t.add_argument('--di', type=float, required=True, help='负载阶跃幅度, A')
    t.add_argument('--fc', type=float, default=None, help='环路穿越频率, Hz')
    t.add_argument('--out', default=None)

    a = sub.add_parser('autotune', help='K 因子自动整定 (BUCK)')
    a.add_argument('--spec', required=True)
    a.add_argument('--fc', type=float, required=True, help='目标穿越频率, Hz')
    a.add_argument('--pm', type=float, default=60.0, help='目标相位裕度, deg')
    a.add_argument('--out', default=None)

    v = sub.add_parser('validate', help='仅检查输入类型与现有工程输入规则，不求解')
    v.add_argument('--spec', required=True)
    v.add_argument('--out', default=None)

    p = sub.add_parser('parameters', help='输出统一参数目录或 JSON Schema')
    p.add_argument('--schema', action='store_true')
    p.add_argument('--out', default=None)

    s = sub.add_parser('snapshot', help='生成版本化计算快照，供后续网页和软件联动')
    s.add_argument('--spec', required=True)
    s.add_argument('--analysis', choices=('selected', 'endpoints'), default='selected')
    s.add_argument('--include-efficiency', action='store_true')
    s.add_argument('--no-waveforms', action='store_true')
    s.add_argument('--out', required=True)

    r = sub.add_parser('report', help='统一计算后导出 Word / Excel 双输入端点报告')
    r.add_argument('--spec', required=True)
    r.add_argument('--out', required=True, help='.docx 或 .xlsx')

    sp = sub.add_parser('spice', help='导出固定频率反激 SSR 通用闭环 LTspice 工程')
    sp.add_argument('--spec', required=True)
    sp.add_argument('--out', required=True, help='可移植 ZIP 工程')

    args = ap.parse_args()

    if args.cmd == 'spice':
        from design_engine.specification import load_spec
        from spice_export import export_project
        try:
            print(json.dumps(export_project(args.out,load_spec(_read_spec(args.spec))),ensure_ascii=False))
        except (ValueError, TypeError, KeyError) as exc:
            print(str(exc),file=sys.stderr)
            sys.exit(2)

    elif args.cmd == 'validate':
        from design_engine.service import validate_spec
        r = validate_spec(_read_spec(args.spec))
        _write(args.out, r)
        print(json.dumps(r, ensure_ascii=False, allow_nan=False))
        if not r['ok']:
            sys.exit(2)

    elif args.cmd == 'parameters':
        from design_engine.catalog import parameter_catalog, specification_schema
        r = specification_schema() if args.schema else parameter_catalog()
        _write(args.out, r)
        if not args.out:
            print(json.dumps(r, ensure_ascii=False, allow_nan=False, indent=2))

    elif args.cmd in ('snapshot', 'report'):
        from design_engine.service import calculate, export_report, SpecValidationError
        from calculation_scheduler import CalculationCancelled
        try:
            if args.cmd == 'snapshot':
                run = calculate(_read_spec(args.spec), analysis=args.analysis,
                                include_efficiency=args.include_efficiency)
                identity = run.save(args.out, include_waveforms=not args.no_waveforms)
                print('written', args.out, 'snapshot_id=' + identity)
                if not run.to_dict(include_waveforms=False)['ok']:
                    sys.exit(2)
            else:
                if os.path.splitext(args.out)[1].lower() not in ('.docx', '.xlsx'):
                    ap.error('report --out 必须以 .docx 或 .xlsx 结尾')
                run = calculate(_read_spec(args.spec), analysis='endpoints', include_efficiency=True)
                outcome = export_report(run, args.out)
                print(json.dumps(outcome, ensure_ascii=False, default=str))
                if outcome.get('incomplete'):
                    sys.exit(2)
        except SpecValidationError as exc:
            print(json.dumps(dict(ok=False, error='invalid_spec', issues=exc.issues), ensure_ascii=False))
            sys.exit(2)
        except CalculationCancelled:
            print(json.dumps(dict(ok=False, error='cancelled'), ensure_ascii=False))
            sys.exit(130)
        except (ValueError, FloatingPointError, RuntimeError, OverflowError) as exc:
            print(json.dumps(dict(ok=False, error='calculation_failed', message=str(exc)), ensure_ascii=False))
            sys.exit(2)

    elif args.cmd == 'design':
        r = design_api.run_design(_read_spec(args.spec))
        if args.md:
            with open(args.md, 'w', encoding='utf-8') as f:
                f.write(report_markdown(r) + '\n')
            print('written', args.md)
        _write(args.out, r)
        if not r.get('ok'):
            sys.exit(2)
        if r['failed_checks']:
            print('FAILED CHECKS:', ', '.join(r['failed_checks']))
            sys.exit(1)
        print('all checks passed, eta = %.2f%%' % (r['losses']['eta'] * 100))

    elif args.cmd == 'corners':
        r = design_api.run_corners(_read_spec(args.spec),
                                   v_in_min=args.vin_min, v_in_max=args.vin_max)
        _write(args.out, r)
        w = r['worst']
        if w:
            print('corners=%d  min_eta=%.1f%%  max_I_pk=%.2f A  max_ripple=%.1f mV'
                  % (len(r['corners']), w['min_eta'] * 100, w['max_I_L_pk'],
                     w['max_ripple_pp'] * 1e3))

    elif args.cmd == 'transient':
        r = design_api.load_transient(_read_spec(args.spec), args.di, fc=args.fc)
        _write(args.out, r)
        print('ΔV_esr=%.1f mV  ΔV_cap=%.1f mV  total=%.1f mV'
              % (r['dv_esr'] * 1e3, r['dv_cap'] * 1e3, r['dv_total'] * 1e3))

    elif args.cmd == 'autotune':
        r = design_api.autotune_loop(_read_spec(args.spec), args.fc, args.pm)
        _write(args.out, r)
        if not r['feasible']:
            print('Target infeasible for %s (required boost %.2f deg); no spec updates.'
                  % (r['comp_type'], r['boost_required']))
            sys.exit(1)
        corners = ('KP=%.4g fz1=%.0f Hz fp1=%.0f Hz'
                   % (r['KP'], r['fz1'], r['fp1']))
        achieved = r['achieved']
        verify = ('PM=%.1f deg @ %.0f Hz' % (achieved['pm'], achieved['fc'])
                  if achieved['pm'] is not None and achieved['fc'] is not None else
                  'no descending 0-dB crossover found')
        print('%s: %s -> %s' % (r['comp_type'], corners, verify))


if __name__ == '__main__':
    main()
