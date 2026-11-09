"""Recompute the documented three-output example without changing the engine.

Run with the project's numerical Python. Only X004 keeps all accepted solver
steps; other corners keep their final results. This is documentation evidence,
not a second implementation of the electrical equations.
"""
from pathlib import Path
import hashlib
import inspect
import json
import sys
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
from runtime_resources import configure_numeric_threads
configure_numeric_threads()
import numpy as np
import scipy
import coupled_flyback as cf
from cross_regulation import scan_cross_regulation
from design_api import load_spec
from isolated_outputs import output_specs

SOURCE = ROOT / 'examples/3_OUTPUT_CROSS_REGULATION.json'
OUTPUT = Path(__file__).with_name('cross_regulation_worked_example.json')


def safe(value):
    if isinstance(value, np.ndarray): return value.tolist()
    if isinstance(value, np.generic): return value.item()
    if isinstance(value, dict): return {str(k): safe(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)): return [safe(v) for v in value]
    return value


def collect():
    p = load_spec(json.loads(SOURCE.read_text(encoding='utf-8-sig')))
    original_periodic, original_solver = cf._periodic_solution, cf.least_squares
    records, case_ids = [], {}
    current = None

    def decode(inputs, x, residual):
        target = np.asarray(inputs['target']); n = len(target)
        other = [j for j in range(n) if j != inputs['main']]
        port = target.copy(); port[other] *= np.asarray(x[n:2*n-1])
        return safe(dict(x=x, duty=x[-1], output_port_V=port,
            initial_secondary_A=np.asarray(x[:n])*inputs['current_scale'],
            residual=residual, max_abs_residual=np.max(np.abs(residual)),
            cost=np.dot(residual, residual)/2))

    def solver(fun, x0, **settings):
        record = current
        record['settings'] = safe(settings)
        record['accepted'] = []
        calls = 0

        def evaluate(x):
            nonlocal calls
            r = fun(x); calls += 1
            if calls == 1: record['initial'] = decode(record['inputs'], x, r)
            return r

        def callback(intermediate_result):
            row = decode(record['inputs'], intermediate_result.x, intermediate_result.fun)
            row.update(step=len(record['accepted'])+1, nfev=int(intermediate_result.nfev))
            record['accepted'].append(row)

        solved = original_solver(evaluate, x0, callback=callback, **settings)
        record['solver'] = safe(dict(nfev=solved.nfev, njev=solved.njev,
            residual_calls=calls, accepted_steps=len(record['accepted']),
            success=solved.success, message=solved.message, optimality=solved.optimality))
        return solved

    def periodic(*args, **kwargs):
        nonlocal current
        inputs = inspect.signature(original_periodic).bind(*args, **kwargs).arguments
        record = dict(inputs=safe(inputs)); records.append(record); current = record
        original_periodic.cache_clear()
        try: point = original_periodic(*args, **kwargs)
        finally: current = None
        circuit = cf._Circuit(inputs['matrix'], inputs['dcr'], inputs['vin'], inputs['vf'],
            inputs['rd'], inputs['ron'], inputs['rs'], inputs['clamp'], inputs['period'])
        end, segments = circuit.cycle(point['start'], point['voltage'], point['duty'])
        parts, times, currents = [], [], []
        for seg in segments:
            start = np.zeros(circuit.count); finish = start.copy(); charge = start.copy()
            local_t = np.linspace(0, seg.dt, 65)
            values = np.zeros((circuit.count, len(local_t)))
            if seg.active:
                indices = list(seg.active); start[indices] = seg.initial
                finish[indices], charge[indices] = seg.flow.values(seg.initial, seg.voltage, seg.dt)
                values[indices] = seg.flow.prepare_current(seg.initial, seg.voltage)(local_t)
            parts.append(safe(dict(start_s=seg.t, end_s=seg.t+seg.dt,
                on=seg.on, active=list(seg.active), current_start_A=start,
                current_end_A=finish, charge_C=charge)))
            times.extend((seg.t+local_t).tolist()); currents.extend(values.T.tolist())
        target, rated, block = map(np.asarray, (inputs['target'], inputs['rated'], inputs['blocking']))
        load = target**2/rated; port = point['voltage']-block
        q, q2, on_q, on_q2, clamp_q = point['integrals']; period_s = inputs['period']
        vin_port = inputs['vin']+(p['Vf_din'] if p['d_in_enable'] else 0.)
        losses = dict(winding_dcr=float(np.dot(inputs['dcr'], q2)/period_s),
            rectifiers=float(np.dot(inputs['vf'], q[1:])/period_s),
            output_blocking=float(np.dot(block, q[1:])/period_s),
            input_blocking=float((vin_port-inputs['vin'])*on_q/period_s),
            mos_conduction=float(inputs['ron']*on_q2/period_s),
            sense=float(inputs['rs']*on_q2/period_s), clamp=float(inputs['clamp']*clamp_q/period_s))
        pin = vin_port*on_q/period_s; powers = port**2/load
        record['final'] = safe(dict(duty=point['duty'], initial_secondary_A=point['start'],
            output_cap_V=point['voltage'], output_port_V=port, load_ohm=load,
            average_rectifier_A=q[1:]/period_s, average_load_A=port/load,
            output_charge_C=q[1:], periodic_residual_A=end[1:]-point['start'],
            charge_residual_A=q[1:]/period_s-port/load, normalized_residual=point['error'],
            output_power_W=powers, input_power_W=pin, rl_losses_W=losses,
            energy_residual_W=pin-sum(powers)-sum(losses.values()), segments=parts,
            waveform=dict(time_s=times, currents_A=currents)))
        assert max(abs(point['error'])) <= 2e-5
        assert abs(record['final']['energy_residual_W']) < max(.001, .002*pin)
        return point

    def progress(done, total, case_id): case_ids[case_id] = len(records)-1

    with patch.object(cf, '_periodic_solution', side_effect=periodic), \
         patch.object(cf, 'least_squares', side_effect=solver):
        result = scan_cross_regulation(p, progress=progress)
    assert result['complete'] and result['successful_cases'] == 16
    for case in result['cases']:
        record = records[case_ids[case['id']]]
        np.testing.assert_allclose(record['final']['output_port_V'], case['voltages'], atol=1e-10)
        case['solver'] = record['solver']
        case['energy_residual_W'] = record['final']['energy_residual_W']
    focus = records[case_ids['X004']]
    focus.update(case_id='X004', powers_W=[30, .05, .95])
    rails = output_specs(p)
    payload = dict(schema='power-design.cross-regulation-worked-example.v1',
        generated_date='2026-11-02', scipy_version=scipy.__version__,
        source=str(SOURCE.relative_to(ROOT)).replace('\\', '/'),
        source_sha256=hashlib.sha256(SOURCE.read_bytes()).hexdigest(),
        code_sha256={name:hashlib.sha256((ROOT/name).read_bytes()).hexdigest() for name in
            ('coupled_flyback.py','cross_regulation.py','winding_coupling.py','isolated_outputs.py')},
        resistivity_ohm_m=p['rho'], eta_guess=p['eta_guess'],
        geometry=dict(MLT_m=p['MLT'], turns=[p['Np']]+[r['Ns'] for r in rails],
            diameter_m=[p['d_wire_p']]+[r['d_wire_s'] for r in rails],
            strands=[p['n_strand_p']]+[r['n_strand_s'] for r in rails]),
        result=result, focus=focus)
    OUTPUT.write_text(json.dumps(safe(payload),ensure_ascii=False,indent=2,allow_nan=False),encoding='utf-8')
    print(json.dumps(dict(output=str(OUTPUT),corners=16,
        X004_steps=focus['solver']['accepted_steps'],X004_voltages=focus['final']['output_port_V']),ensure_ascii=False))


if __name__ == '__main__': collect()
