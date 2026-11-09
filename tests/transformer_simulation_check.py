"""Project-level adoption of linear magnetic data, independent of installed FEM tools."""
from copy import deepcopy
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from config_io import decode_config
from transformer_sim_reference import _connections
import transformer_simulation as sim


def field(ports, microhenries, short_uH):
    l = np.array(microhenries) * 1e-6
    return dict(schema='transformer-coupling-tool.results.v1', primary_port='P', port_order=ports,
                L_ports_H=l.tolist(), k_ports=(l / np.sqrt(np.outer(l.diagonal(), l.diagonal()))).tolist(),
                ideal_all_secondary_short_Lp_H=short_uH * 1e-6)


def winding_ids(*labels):
    return dict(windings=[dict(id=p) for p in labels])


class FieldAdoptionChecks(unittest.TestCase):
    def test_port_permutation_and_full_schur(self):
        # Secondary block [4,1;1,9] µH. The cross term contributes -12/35 µH
        # to the reduction term. Treating the secondary ports independently fails.
        sample = field(['OUT2', 'P', 'OUT1'], [[9, 3, 1], [3, 8, 2], [1, 2, 4]], 44/7)
        values = sim._field_values(sample, winding_ids('P', 'OUT1', 'OUT2'))
        self.assertAlmostEqual(values['primary_self_H'] * 1e6, 8)
        self.assertAlmostEqual(values['primary_short_H'] * 1e6, 44/7)
        base = dict(topology='FLYBACK', coupling_config={'enabled': True}, outputs=[{}, {}])
        mapped = sim._proposal({}, base, values, [])
        self.assertEqual(mapped['coupling_config']['enabled'], True)
        expected = [[1, 2/np.sqrt(32), 3/np.sqrt(72)],
                    [2/np.sqrt(32), 1, 1/6], [3/np.sqrt(72), 1/6, 1]]
        np.testing.assert_allclose(mapped['coupling_config']['k'], expected)

    def test_invalid_field_is_blocked(self):
        valid = field(['P', 'OUT1'], [[100, 45], [45, 25]], 19)
        errors = [('primary_port', 'OUT1'), ('port_order', ['P', 'P']), ('port_order', ['P', 'OUT2']),
                  ('L_ports_H', [[1]]), ('L_ports_H', [[1., 2.], [2., 1.]]),
                  ('L_ports_H', [[1., .1], [.2, 1.]]), ('L_ports_H', [[1., float('nan')], [0., 1.]]),
                  ('k_ports', [[1., .7], [.7, 1.]]), ('ideal_all_secondary_short_Lp_H', 18e-6)]
        for key, value in errors:
            with self.subTest(key=key, value=value), self.assertRaises(ValueError):
                sim._field_values(dict(valid, **{key: value}), winding_ids('P', 'OUT1'))

    def test_qr_scalar_uses_short_ratio_and_preserves_user_units(self):
        sample = field(['OUT1', 'P'], [[25, 45], [45, 100]], 19)
        values = sim._field_values(sample, winding_ids('P', 'OUT1'))
        cfg = dict(L=dict(v=90, u='u'), rcd_K=dict(v=800, u='m'), K=.8, N=2., V_in=300.)
        original = deepcopy(cfg)
        proposed = sim._proposal(cfg, {'topology': 'QR-FLYBACK'}, values, [])
        self.assertEqual(cfg, original)
        self.assertEqual(proposed['L']['u'], 'u')
        self.assertEqual(proposed['rcd_K']['u'], 'm')
        self.assertNotIn('K', proposed)
        self.assertAlmostEqual(proposed['L']['v'], 100.)
        self.assertAlmostEqual(proposed['rcd_K']['v'], 810.)
        scaled = decode_config(proposed)
        self.assertAlmostEqual(scaled['L'] * (1-scaled['K']), 19e-6)
        self.assertAlmostEqual(values['k_ports'][0][1], .9)
        si_proposed = sim._proposal({'K': .8, 'L': 90e-6}, {'topology': 'QR-FLYBACK'}, values, [])
        self.assertAlmostEqual(si_proposed['K'], .81)
        self.assertAlmostEqual(si_proposed['L'], 100e-6)

    def test_reversed_polarity_readable_but_adoption_requires_review(self):
        sample = field(['P', 'OUT1'], [[100, -45], [-45, 25]], 19)
        values = sim._field_values(sample, winding_ids('P', 'OUT1'))
        self.assertAlmostEqual(values['k_ports'][0][1], -.9)
        with self.assertRaisesRegex(ValueError, '同名端'):
            sim._proposal({}, {'topology': 'QR-FLYBACK'}, values, [])

    def test_adoption_preserves_cad_gap_and_independent_output_inductor(self):
        cfg = {'L': {'v': 220, 'u': 'u'}, 'Lm_forward': {'v': 60, 'u': 'u'}}
        values = sim._field_values(field(['P', 'OUT1'], [[100, 45], [45, 25]], 19),
                                   winding_ids('P', 'OUT1'))
        result = sim._proposal(cfg, {'topology': 'ACF-FORWARD'}, values, [])
        self.assertEqual(result['L'], cfg['L'])
        self.assertAlmostEqual(result['Lm_forward']['v'], 100)
        core = dict(mode='half_center_gap', total_gap_m=.00094, source='参考实体', path='X/core.step', sha256='a'*64)
        sim._keep_physical_gap(result, {'core': core})
        saved = result['winding_config']['model_3d']['core']
        self.assertEqual(saved['gap_geometry'], dict(source='参考实体', length_m=.00094, type='center_leg_ground'))
        self.assertEqual(saved['geometry_reference'], 'core.step')
        self.assertEqual(saved['geometry_sha256'], 'a'*64)
        saved['gap_geometry']['source'] = '样件实测（原输入）'
        sim._keep_physical_gap(result, {'core': core})
        self.assertEqual(saved['gap_geometry']['source'], '样件实测（原输入）')

    def test_stale_or_unadoptable_result_blocked(self):
        current = {'L': 80e-6, 'winding_config': {'window_width': .01}}
        src = deepcopy(current)
        result = dict(input_id=sim._input_id(src), proposed_config=dict(src, L=81e-6), record={})
        apply = sim.apply_transformer_simulation
        accepted = apply(current, result)
        accepted['winding_config']['window_width'] = .02
        self.assertEqual(result['proposed_config']['winding_config']['window_width'], .01)
        self.assertEqual(current, src)
        with self.assertRaisesRegex(ValueError, '变化'):
            apply(dict(src, winding_config={'window_width': .012}), result)
        with self.assertRaisesRegex(ValueError, '评审'):
            apply(current, dict(result, proposed_config=None, record={'adoption_error': '反向互感'}))

    def test_assembled_core_requires_declared_gap_type(self):
        core = dict(mode='assembled', total_gap_m=.001, source='已装配实体', path='unit.step', sha256='a'*64)
        with self.assertRaisesRegex(ValueError, '加工方式'):
            sim._keep_physical_gap({}, {'core': core})
        cfg = {}
        sim._keep_physical_gap(cfg, {'core': dict(core, total_gap_m=0)})
        self.assertEqual(cfg['winding_config']['model_3d']['core']['gap_geometry']['type'], 'none')

    def test_reference_preserves_user_wiring(self):
        empty = {'connection_matrix': {'values': None}}
        cases = ({'sections': {'P_A': {'start_node': '已有接线'}}},
                 {'ports': {'P': {'section_order': ['P_B', 'P_A']}}},
                 {'terminals': [{'node': '抽头'}]}, {'leads': [{'node': '板上接线'}]})
        for profile in cases:
            saved = deepcopy(profile)
            with self.subTest(profile=profile), self.assertRaisesRegex(ValueError, '部分填写'):
                _connections(profile, empty)
            self.assertEqual(saved, profile)
            _connections(profile, {'connection_matrix': {'values': [[1]]}})
            self.assertEqual(saved, profile)

    def test_orchestration_and_explicit_adoption(self):
        # The separate acceptance run covers Elmer. Here check the normal controller
        # lifecycle and the work directory, without starting a solver process.
        cfg = {'topology': 'QR-FLYBACK', 'L': 90e-6, 'K': .8}
        proposed = {'topology': 'QR-FLYBACK', 'L': 100e-6, 'K': .81}
        progress = []
        def complete(design, package, result_dir, directory, **kwargs):
            self.assertEqual(design, cfg)
            self.assertEqual(Path(result_dir).name, 'field-case')
            self.assertEqual(Path(package).parent, directory)
            return dict(input_id=sim._input_id(design), proposed_config=proposed,
                        directory=str(directory), comparison_path=str(directory/'对比.html'))
        with (tempfile.TemporaryDirectory() as tmp, patch.object(sim, '_calculate'),
              patch.object(sim, 'export_geometry_package', return_value={'ready': {'cross_section': True}}),
              patch('transformer_sim_runner.run_field_solver', return_value=Path(tmp)/'field-case') as dispatched,
              patch.object(sim, '_compare_verified', side_effect=complete)):
            result = sim.run_transformer_simulation(cfg, tool_root='工具', project_file='设置',
                                                    output_directory=tmp, progress=progress.append)
            state = json.loads((Path(result['directory'])/'任务状态.json').read_bytes())
            self.assertEqual(state['state'], 'complete')
            self.assertEqual(state['comparison'], result['comparison_path'])
            dispatched.assert_called_once()
            self.assertEqual(dispatched.call_args.kwargs['project_file'], '设置')
            self.assertTrue(progress)
        self.assertEqual(cfg['L'], 90e-6)
        self.assertEqual(sim.apply_transformer_simulation(cfg, result), proposed)


if __name__ == '__main__':
    unittest.main(verbosity=2)
