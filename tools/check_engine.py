"""Serial, bounded regression runner; never executes document-update scripts."""
import argparse
from datetime import datetime
import json
import os
from pathlib import Path
import subprocess
import sys
import time

ROOT = Path(__file__).resolve().parents[1]
HEADLESS = ('design_engine_check.py', 'engine_cli_check.py', 'input_voltage_range_check.py', 'api_check.py',
            'forward_check.py', 'efficiency_preset_check.py', 'gate_charge_check.py',
            'multi_output_loop_check.py',
            'cross_regulation_check.py', 'winding_electrical_check.py',
            'thermal_stress_check.py')
GUI = ('engineering_check.py', 'custom_core_check.py', 'parameter_reorg_check.py',
       'input_range_ui_check.py', 'excel_ui_check.py', 'topology_calculation_check.py',
       'diode_curves_check.py', 'mos_curves_check.py', 'mos_gate_charge_curve_check.py',
       'winding_coupling_check.py', 'multi_output_check.py', 'coupled_integration_check.py')
REPORTS = ('engine_report_service_check.py', 'excel_report_check.py', 'input_range_report_check.py',
           'mos_simple_report_check.py')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--gui', action='store_true', help='Also test owned Tk windows')
    parser.add_argument('--reports', action='store_true', help='Also exercise real Word/Excel authoring')
    parser.add_argument('--timeout', type=int, default=180, help='Maximum seconds per test script')
    parser.add_argument('--only', nargs='+', choices=HEADLESS + GUI + REPORTS,
                        help='Run only these named scripts from the safe whitelist')
    args = parser.parse_args()
    if args.timeout <= 0:
        parser.error('--timeout must be positive')
    output = ROOT/'artifacts'/'checks'/datetime.now().strftime('%Y%m%d-%H%M%S')
    output.mkdir(parents=True, exist_ok=False)
    scripts = tuple(args.only) if args.only else HEADLESS + (GUI if args.gui else ()) + (REPORTS if args.reports else ())
    env = dict(os.environ, PYTHONUTF8='1', POWER_DESIGN_NUM_THREADS='1')
    rows = []
    for script in scripts:
        print('RUN ' + script, flush=True)
        start = time.perf_counter()
        try:
            process = subprocess.run([sys.executable, '-X', 'utf8', str(ROOT/'tests'/script)],
                cwd=ROOT, env=env, capture_output=True, text=True, encoding='utf-8',
                errors='replace', timeout=args.timeout)
            code = process.returncode
            log = process.stdout + '\n' + process.stderr
        except subprocess.TimeoutExpired as exc:
            code = 124
            def decoded(value):
                return value.decode('utf-8', errors='replace') if isinstance(value, bytes) else value or ''
            log = decoded(exc.stdout) + '\n' + decoded(exc.stderr) + '\nTEST TIMEOUT\n'
        seconds = round(time.perf_counter()-start, 3)
        (output/(script + '.log')).write_text(log, encoding='utf-8')
        row = dict(test=script, exit_code=code, seconds=seconds, passed=code == 0)
        rows.append(row)
        print(('PASS ' if code == 0 else 'FAIL ') + script + f' ({seconds:.1f}s)', flush=True)
        (output/'summary.json').write_text(json.dumps(dict(
            schema='power-design.regression.v1', all_passed=all(r['passed'] for r in rows),
            complete=len(rows) == len(scripts), planned=len(scripts), results=rows),
            ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    print('Logs: ' + str(output), flush=True)
    return 0 if all(row['passed'] for row in rows) else 1


if __name__ == '__main__':
    raise SystemExit(main())
