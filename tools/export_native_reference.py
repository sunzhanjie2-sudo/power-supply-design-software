"""Build-time data and independent Python reference vectors for the TS engine.

No Python files or executable runtime are shipped to the browser. Re-run this
explicitly after reviewed model/metadata changes; it is not a runtime bridge.
"""
import copy
import hashlib
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from runtime_resources import configure_numeric_threads
configure_numeric_threads()
from design_engine.contracts import json_value
from web_app.metadata import bootstrap, read_example, normalize_config
from power_stage import DEFAULT_PARAMS, compute_operating_point
from magnetics import CORE_DB, STEINMETZ_MATERIALS

TARGET = ROOT / 'web_app/frontend/src/native_engine'
EXAMPLES = ['40W_CCM_FLYBACK.json', '40W_CCM_3OUT_FLYBACK.json',
            '90W_QR_L6565_300V.json', '33W_3OUT_ACF_MP6005_COMPACT.json',
            '24W_BUCK_VM_TPS40200.json', '24W_BUCK_PCM_LTC3864.json',
            '24W_BOOST_PCM_LM5022.json']


def write(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(json_value(value), ensure_ascii=False, separators=(',', ':')), encoding='utf-8')


def main():
    from component_management import RULES, CAP_TYPES
    data = dict(bootstrap=bootstrap(), defaults=DEFAULT_PARAMS, cores=CORE_DB,
                materials=STEINMETZ_MATERIALS, rules=RULES, cap_types=CAP_TYPES,
                examples={name: normalize_config(read_example(name)) for name in EXAMPLES})
    modules = ['power_stage', 'isolated_outputs', 'voltage_nodes', 'transformer_turns',
               'coupled_flyback', 'winding_coupling', 'magnetics', 'mos_gate',
               'semiconductor', 'plants', 'multi_output_loop', 'capripple']
    data['reference'] = {name: hashlib.sha256((ROOT/(name+'.py')).read_bytes()).hexdigest() for name in modules}
    write(TARGET/'reference-data.json', data)
    fixtures = []
    for name in EXAMPLES:
        p = copy.deepcopy(data['examples'][name])
        # Native operating-point port is checked separately from controller-
        # specific periodic solvers. Never silently apply this to user drafts.
        controller = copy.deepcopy(p)
        p['spice_config']['niso_profile'] = 0
        if name == '33W_3OUT_ACF_MP6005_COMPACT.json':
            continue
        cases = [('nominal', p)]
        if controller['spice_config'].get('niso_profile'):
            cases.append(('controller-periodic', controller))
        if p.get('coupling_config', {}).get('enabled'):
            ideal = copy.deepcopy(p); ideal['coupling_config']['enabled'] = False
            cases.append(('ideal-ratio', ideal))
        for label, spec in cases:
            for voltage in sorted(set([spec['V_in_min'], spec['V_in_max']])):
                spec = dict(spec, V_in=voltage)
                op = compute_operating_point(spec)
                keys = ['D', 'Dp', 'f_sw', 'I_L_pk', 'I_L_min', 'I_sw_rms',
                        'I_sw_pk', 'I_d_rms', 'I_d_pk', 'V_sw_max', 'V_d_max', 'V_out']
                expected = {key: op.get(key) for key in keys}
                expected['outputs'] = [{key: child.get(key) for key in keys}
                                       for child in op.get('output_ops', [])]
                if op.get('coupled_model'):
                    expected['coupling'] = {key: op['coupled_model'].get(key) for key in
                                           ('normalized_residual', 'energy_balance_W', 'output_voltages')}
                from loss_model import compute_design
                from plants import build_loop_models
                result = compute_design(spec)
                expected['losses'] = {key: result[key] for key in
                                      ('P_semi','P_mag','P_cap','P_cap_in','P_sense','P_rcd','P_din','P_dout','P_total','eta')}
                expected['gate'] = {key: result['semi']['switch']['gate'][key] for key in
                                    ('Vgp_on','Vgp_off','Qgs_on','Qgs_off','Qgd_on','Qg_th')}
                try:
                    models, _ = build_loop_models(spec, result['op'])
                    expected['plant_gains'] = [[complex(models[0](2j*3.141592653589793*f)).real,
                                               complex(models[0](2j*3.141592653589793*f)).imag]
                                              for f in (1,10,100,1000,10000)]
                except ValueError as error:
                    expected['loop_error'] = str(error)
                fixtures.append(dict(name=name+'/'+label+'/'+str(voltage), spec=spec, expected=expected))
                print('Reference:', fixtures[-1]['name'], flush=True)
    write(ROOT/'tests/fixtures/native_engine_reference.json', fixtures)


if __name__ == '__main__':
    main()
