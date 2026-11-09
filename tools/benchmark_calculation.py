"""Reproducible local timings; separate first solves from electrical-cache hits.

Example: python tools/benchmark_calculation.py --output artifacts/benchmark.json
Use --source-root to compare a separate source checkout with the same script.
"""
from pathlib import Path
import argparse
import importlib
import json
import platform
import statistics
import sys
import time


CASES = {
    'flyback3': '40W_CCM_3OUT_FLYBACK.json',
    'coupled3': '3_OUTPUT_COUPLED_FLYBACK.json',
    'acf3': '33W_3OUT_ACF_MP6005_COMPACT.json',
    'qr': '90W_QR_L6565_300V.json',
    'buck_vm': '24W_BUCK_VM_TPS40200.json',
    'buck_pcm': '24W_BUCK_PCM_LTC3864.json',
    'boost_pcm': '24W_BOOST_PCM_LM5022.json',
}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source-root', type=Path, default=Path(__file__).resolve().parents[1])
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--repeat', type=int, default=3)
    parser.add_argument('--cases', nargs='+', choices=CASES, default=list(CASES))
    parser.add_argument('--report', action='store_true', help='Also time endpoint/efficiency preparation (no file rendering)')
    args = parser.parse_args()
    if args.repeat < 1:
        parser.error('--repeat must be positive')
    root = args.source_root.resolve()
    sys.path.insert(0, str(root))
    started = time.perf_counter()
    from runtime_resources import configure_numeric_threads
    configure_numeric_threads()
    from design_engine.service import calculate
    from loop_tuning import analyze_loop
    # Warm dependency imports once; clear numerical caches for each cold solve.
    calculate({})
    pools = [(importlib.import_module(module), name) for module, name in (
        ('coupled_flyback', '_periodic_solution'), ('acf_periodic', '_cached_point'),
        ('nonisolated', '_cached_solution'))]
    def clear():
        for module, name in pools:
            cache = getattr(module, name, None)
            if cache is not None:
                cache.cache_clear()
    def timed(function):
        start = time.perf_counter()
        result = function()
        return result, time.perf_counter()-start
    def measurements(values):
        return dict(seconds=values, median_seconds=statistics.median(values))
    summary = dict(python=sys.version, platform=platform.platform(), source_root=str(root),
                   import_and_warmup_seconds=time.perf_counter()-started, repeat=args.repeat,
                   note='Wall-clock times on this PC. Same examples, 6000 loop frequencies and full waveforms; no LTspice runs.',
                   cases={})
    args.output.parent.mkdir(parents=True, exist_ok=True)
    for name in args.cases:
        spec = json.loads((root/'examples'/CASES[name]).read_text(encoding='utf-8-sig'))
        print(name+': first solves', flush=True)
        first, repeated, loops = [], [], []
        for _ in range(args.repeat):
            clear()
            run, elapsed = timed(lambda: calculate(spec, include_cross_regulation=False))
            first.append(elapsed)
        for _ in range(args.repeat):
            run, elapsed = timed(lambda: calculate(spec, include_cross_regulation=False))
            repeated.append(elapsed)
        case = run.runtime_bundle()['cases'][0]
        if case.get('loop_error'):
            raise RuntimeError(case['loop_error'])
        for _ in range(args.repeat):
            _, elapsed = timed(lambda: analyze_loop(case['p'], case['models'], case['result']['op']))
            loops.append(elapsed)
        row = dict(first_solve=measurements(first), repeat_solve=measurements(repeated),
                   loop_scan=measurements(loops), ok=run.legacy_report()['ok'])
        # Preserve raw numerical cases for an independent before/after diff.
        path = args.output.with_name(args.output.stem+'-'+name+'-values.json')
        path.write_text(json.dumps(run.to_dict()['cases'], ensure_ascii=False, allow_nan=False), encoding='utf-8')
        if args.report:
            clear()
            report, elapsed = timed(lambda: calculate(spec, analysis='endpoints',
                include_cross_regulation=False, include_efficiency=True))
            row['endpoint_report_preparation_seconds'] = elapsed
            row['endpoint_errors'] = [c.get('error') for c in report.runtime_bundle()['cases']]
        summary['cases'][name] = row
        args.output.write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding='utf-8')
        print(name+': '+json.dumps(row), flush=True)


if __name__ == '__main__':
    main()
