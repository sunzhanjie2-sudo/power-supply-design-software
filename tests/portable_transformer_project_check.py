"""Native geometry preparation without an old extractor project or old ZIP."""
from copy import deepcopy
import json
from pathlib import Path
import shutil
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from runtime_resources import configure_numeric_threads
configure_numeric_threads()
from calculation_scheduler import CalculationCancelled
from portable_transformer_project import prepare_portable_reference
from transformer_geometry import read_geometry_package, strict_json
from transformer_sim_runner import bind_solver_project


class PortableProjectChecks(unittest.TestCase):
    def setUp(self):
        base = ROOT / 'artifacts/portable-transformer-project-check'
        base.mkdir(parents=True, exist_ok=True)
        tmp = tempfile.TemporaryDirectory(dir=base)
        self.addCleanup(tmp.cleanup)
        self.root = Path(tmp.name)
        self.core = self.root / 'selected.step'
        # The input builder checks a STEP header; independent CAD checks own
        # solid content. This fixture intentionally never starts a solver.
        self.core.write_bytes(b'ISO-10303-21;\nHEADER; ENDSEC; DATA; ENDSEC; END-ISO-10303-21;')
        (self.root / 'elmer/bin').mkdir(parents=True)
        for name in ('ElmerSolver.exe', 'ElmerGrid.exe'):
            (self.root / 'elmer/bin' / name).write_bytes(b'not executed')
        self.env = dict(elmer_home=str(self.root / 'elmer'), core_path=str(self.core),
            core_mode='half_center_gap', brep_unit='mm', translation_mm=[0., 0., 0.],
            rotation_deg=[0., 0., 0.], center_leg_radius_m=.0044, gap_center_z_m=0.,
            r0_m=.006, z0_m=-.006, mesh_profile='standard', air_radius_m=.05,
            timeout_s=1200, core_source='仅用于输入合同测试的参考半芯，不代表CAD实体已通过')
        self.cfg = strict_json((ROOT / 'examples/40W_CCM_3OUT_FLYBACK.json').read_bytes())

    def prepare(self, config=None, environment=None):
        return prepare_portable_reference(config or self.cfg, environment=environment or self.env,
                                          output_directory=self.root / 'output')

    def test_blank_connections_are_explicit_assumptions_and_do_not_modify_design(self):
        before = deepcopy(self.cfg)
        result = self.prepare()
        self.assertEqual(self.cfg, before)
        candidate = result['config']
        profile = candidate['winding_config']['model_3d']
        self.assertEqual(candidate['winding_config']['layer_plan'], before['winding_config']['layer_plan'])
        self.assertTrue(all(s['status'] == 'assumed' for s in profile['sections'].values()))
        self.assertEqual(profile['frame'], dict(r0_m_if_circular=.006, z0_m=-.006))
        project = strict_json(Path(result['project_file']).read_bytes())
        package = Path(result['project_file']).parent / project['package_path']
        geometry = read_geometry_package(package)
        self.assertEqual(geometry['connection_matrix']['column_ports'], ['P', 'OUT1', 'OUT2', 'OUT3'])
        self.assertTrue(all(p['turns_match_calculator'] for p in geometry['connections']))
        self.assertEqual(project['material']['name'], 'DMR44')
        self.assertEqual(project['material']['relative_permeability'], 2400.)
        self.assertEqual(project['core']['total_gap_m'], geometry['design_targets']['air_gap']['gap_m'])
        self.assertEqual(project['core']['total_gap_m'], profile['core']['gap_geometry']['length_m'])
        self.assertIn('后续仍须', result['summary'])

    def test_generated_project_is_relocatable_and_existing_connections_are_preserved(self):
        first = self.prepare()
        candidate = first['config']
        old_profile = deepcopy(candidate['winding_config']['model_3d'])
        second = self.prepare(candidate)
        self.assertEqual(second['config']['winding_config']['model_3d']['sections'], old_profile['sections'])
        self.assertEqual(second['config']['winding_config']['model_3d']['ports'], old_profile['ports'])
        original = Path(second['project_file']).parent
        moved = self.root / 'other-computer-input'
        shutil.move(original, moved)
        self.core.unlink()  # The original selected model is no longer available.
        settings = moved / Path(second['project_file']).name
        p = strict_json(settings.read_bytes())
        self.assertFalse(Path(p['core']['path']).is_absolute())
        self.assertFalse(Path(p['package_path']).is_absolute())
        bound = bind_solver_project(moved / p['package_path'], settings, moved / 'run')
        self.assertEqual(Path(bound['core']['path']).parent, moved / 'models')
        self.assertEqual(bound['connections']['sections'], old_profile['sections'])

    def test_missing_window_and_frame_are_not_guessed(self):
        c = deepcopy(self.cfg)
        c['winding_config'].pop('window_width')
        with self.assertRaisesRegex(ValueError, '骨架净窗口宽度'):
            self.prepare(c)
        for key in ('r0_m', 'z0_m'):
            env = dict(self.env, **{key: None})
            with self.subTest(key=key), self.assertRaisesRegex(ValueError, '不能自动猜测'):
                self.prepare(environment=env)

    def test_manual_turn_centers_and_complete_parallel_wires_survive_preparation(self):
        from transformer_simulation import _calculate
        from winding_layout import assess_winding_window, transformer_windings
        c = deepcopy(self.cfg)
        c['parallel_wires_p'] = 2
        c['winding_config']['window_width'] = .025
        run = _calculate(c, None)
        case = run.runtime_bundle()['cases'][0]
        assessment = assess_winding_window(transformer_windings(case['result']), c['winding_config'])
        point = next(p for p in assessment['cross_sections']
                     if p['winding_id'] == 'P' and p['turn'] == 1 and p['bundle'] == 2)
        center = point['x'] + point['width'] / 2 + .01e-3
        positions = {point['section_id']: {point['position_key']: center}}
        c['winding_config']['turn_positions'] = positions
        result = self.prepare(c)
        self.assertEqual(result['config']['winding_config']['turn_positions'], positions)
        project = strict_json(Path(result['project_file']).read_bytes())
        geometry = read_geometry_package(Path(result['project_file']).parent / project['package_path'])
        winding = next(w for w in geometry['windings'] if w['id'] == 'P')
        self.assertEqual(winding['parallel_wires'], 2)
        boxes = [b for s in geometry['physical_sections'] if s['winding_id'] == 'P' for b in s['bundles']]
        self.assertEqual(len(boxes), 12)
        self.assertAlmostEqual(boxes[1]['center_uv_m'][0], center)

    def test_conflicting_frame_is_not_silently_overwritten(self):
        c = deepcopy(self.cfg)
        c['winding_config']['model_3d'] = dict(schema='power-transformer.model-input.v1',
                                               frame=dict(r0_m_if_circular=.007, z0_m=-.006))
        with self.assertRaisesRegex(ValueError, '与当前工程不一致'):
            self.prepare(c)

    def test_unknown_mode_wrong_file_and_invalid_solver_stop_before_work(self):
        cases = [('core_mode', 'guess'), ('brep_unit', 'cm'), ('mesh_profile', 'fast'),
                 ('translation_mm', [0, 0]), ('rotation_deg', [0, float('nan'), 0]),
                 ('center_leg_radius_m', 0.), ('gap_center_z_m', .001),
                 ('timeout_s', 0), ('core_source', ''), ('elmer_home', str(self.root))]
        for key, value in cases:
            with self.subTest(key=key), self.assertRaises(ValueError):
                self.prepare(environment=dict(self.env, **{key: value}))
        self.core.write_bytes(b'<html>not a STEP model</html>')
        with self.assertRaisesRegex(ValueError, '只修改文件后缀'):
            self.prepare()
        stl = self.root / 'mesh.stl'; stl.touch()
        with self.assertRaisesRegex(ValueError, 'STL'):
            self.prepare(environment=dict(self.env, core_path=str(stl)))

    def test_partial_connections_non_circular_path_and_sealed_cad_are_not_replaced(self):
        c = deepcopy(self.cfg)
        c['winding_config']['model_3d'] = dict(schema='power-transformer.model-input.v1',
            ports={'P': dict(connection='series')})
        with self.assertRaisesRegex(ValueError, '已部分填写'):
            self.prepare(c)
        c['winding_config']['model_3d'] = dict(schema='power-transformer.model-input.v1',
            bobbin=dict(winding_route_type='rounded_rectangle'))
        with self.assertRaisesRegex(ValueError, '已有非圆形'):
            self.prepare(c)
        c['winding_config']['model_3d'] = dict(schema='power-transformer.model-input.v1',
            core=dict(geometry_sha256='a' * 64))
        with self.assertRaisesRegex(ValueError, 'SHA-256不符'):
            self.prepare(c)

    def test_physical_gap_processing_and_position_must_match_existing_design(self):
        c = deepcopy(self.cfg)
        c['winding_config']['model_3d'] = dict(schema='power-transformer.model-input.v1',
            core=dict(gap_geometry=dict(type='spacer', length_m=.0003, source='试验用已确认垫片',
                                        center_xyz_m=[0., 0., 0.])))
        with self.assertRaisesRegex(ValueError, '加工方式'):
            self.prepare(c)
        c['winding_config']['model_3d']['core']['gap_geometry'].update(type='center_leg_ground',
                                                                      center_xyz_m=[.001, 0., 0.])
        with self.assertRaisesRegex(ValueError, '气隙中心'):
            self.prepare(c)

    def test_cancel_is_honored_before_environment_or_calculation(self):
        with self.assertRaises(CalculationCancelled):
            prepare_portable_reference(self.cfg, environment={}, output_directory=self.root,
                                       cancelled=lambda: True)


if __name__ == '__main__':
    unittest.main(verbosity=2)
