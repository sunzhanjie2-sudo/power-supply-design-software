"""Field self inductances must survive matrix resolution and the SPICE deck."""
from copy import deepcopy
import json
from pathlib import Path
import sys
import unittest

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from winding_coupling import resolve_winding_model, validate_coupling_config


class FieldMatrixChecks(unittest.TestCase):
    def test_field_diagonal_is_not_replaced_by_turn_ratio(self):
        config = dict(enabled=True, port_order=['OUT1', 'P'],
                      self_inductances_H=[30e-6, 100e-6], k=[[1., .95], [.95, 1.]])
        original = deepcopy(config)
        geometry = dict(Np=10, R_dc_p=.1, windings=[dict(Ns=5, R_dc=.2)])
        model = resolve_winding_model(dict(topology='FLYBACK', L=100e-6, coupling_config=config),
                                      [{}], geometry=geometry)
        expected = np.array([[100., .95*np.sqrt(100*30)], [.95*np.sqrt(100*30), 30.]])*1e-6
        np.testing.assert_allclose(model['L'], expected, rtol=1e-13)
        self.assertAlmostEqual(model['L_leak'], 9.75e-6, places=15)
        self.assertEqual(config, original)
        self.assertEqual(model['inductance_source'], 'field-matrix')

    def test_stale_primary_and_invalid_ports_are_rejected(self):
        coupling = dict(enabled=True, self_inductances_H=[100e-6, 30e-6],
                        port_order=['P','OUT1'], k=[[1.,.95],[.95,1.]])
        with self.assertRaisesRegex(ValueError, '原边电感'):
            resolve_winding_model(dict(topology='FLYBACK', L=90e-6, coupling_config=coupling),
                [{}], geometry=dict(Np=10, R_dc_p=.1, windings=[dict(Ns=5,R_dc=.2)]))
        for replacement in (['P','P'], ['P','OUT2']):
            with self.subTest(replacement=replacement), self.assertRaisesRegex(ValueError,'端口'):
                validate_coupling_config(dict(coupling, port_order=replacement), 1)

    def test_qr_export_uses_full_field_matrix_without_enabling_fixed_pwm_solver(self):
        from design_engine.specification import load_spec
        from spice_export import project_files
        p = load_spec(json.loads((ROOT/'examples/90W_QR_L6565_300V.json').read_text('utf-8-sig')))
        p.update(V_in=300., V_in_min=300., V_in_max=300.)
        lp = p['L']
        secondary = lp / p['N']**2 * 1.04
        p['coupling_config'] = dict(enabled=False, field_matrix_enabled=True,
            port_order=['P','OUT1'], self_inductances_H=[lp, secondary], k=[[1.,.98],[.98,1.]])
        files = project_files(p)
        params = files['design_params.inc'].decode('ascii')
        numbers = {}
        for line in params.splitlines():
            if line.startswith('.param ') and '=' in line:
                key, value = line[7:].split('=',1)
                try:numbers[key] = float(value)
                except ValueError:pass
        self.assertAlmostEqual(numbers['LP'], lp, places=13)
        self.assertAlmostEqual(numbers['LS1'], secondary, places=13)
        meta = json.loads(files['manifest.json'])
        self.assertEqual(meta['coupling']['source'], 'field-self-and-pairwise-kij')
        self.assertEqual(meta['topology'], 'QR-FLYBACK')
        self.assertIn(b'GenericQR_L6565.lib', files['Flyback.cir'])

    def test_single_output_field_solver_keeps_diode_identity_and_losses(self):
        from design_engine.specification import load_spec
        from diode_curves import validate_curve
        from loss_model import compute_design
        p = load_spec(json.loads((ROOT/'examples/40W_CCM_FLYBACK.json').read_text('utf-8-sig')))
        p.update(d_in_enable=True, d_out_enable=True)
        p['coupling_config'] = dict(enabled=True, field_matrix_enabled=True,
            k=[[1., .995], [.995, 1.]], port_order=['P','OUT1'],
            self_inductances_H=[p['L'],p['L']/p['N']**2])
        p['diode_curves'] = {ref:validate_curve(dict(name=ref, points=[[.4,0.],[.5,1.],[1.4,10.]]))
                              for ref in ('D1','D_IN','D_OUT')}
        original = deepcopy(p)
        result = compute_design(p)
        self.assertEqual(p, original)
        self.assertTrue(np.isfinite(result['P_total']))
        self.assertEqual(result['outputs'][0]['diode']['curve_name'], 'D1')
        self.assertEqual(result['outputs'][0]['blocking']['curve_name'], 'D_OUT')
        models = {row['ref']:row for row in result['diode_models']}
        self.assertEqual(set(models), {'D1','D_IN','D_OUT'})
        for ref, model in models.items():
            self.assertEqual(model['curve_name'], ref)


if __name__ == '__main__':
    unittest.main(verbosity=2)
