"""Model transfer, machine override and untrusted archive boundary checks."""
import copy
import json
from pathlib import Path
import shutil
import sys
import tempfile
import unittest
from unittest.mock import patch
from zipfile import ZipFile

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import simulation_environment as env


class EnvironmentChecks(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.old = self.root / '旧电脑' / '任意模型名.step'
        self.old.parent.mkdir()
        self.old.write_bytes(b'ISO-10303-21; fixture for file transfer, not CAD solver')
        self.config = dict(core_choice='PQ32-30')
        self.value = dict(core_path=str(self.old), core_model='PQ32-30', core_mode='half_center_gap',
                          brep_unit='mm', translation_mm=[0, 0, 0], rotation_deg=[0, 0, 0],
                          center_leg_radius_m=.006725, gap_center_z_m=0., r0_m=.008, z0_m=-.0094,
                          core_source='test model transfer only', elmer_home='',
                          mesh_profile='standard', air_radius_m=.05, timeout_s=1200)
        self.addCleanup(patch.stopall)
        patch.object(env, '_settings_file', return_value=self.root / 'prefs' / 'env.json').start()
        patch.object(env, '_model_root', return_value=self.root / 'portable' / 'simulation-models').start()
        patch('spice_runtime.find_ltspice', return_value='').start()
        patch('transformer_sim_ui._read_settings', return_value={}).start()
        patch.object(env, 'find_elmer', return_value='').start()

    def test_move_complete_model_folder_uses_relative_catalog_and_same_cad(self):
        env.save_environment(self.config, self.value)
        catalog = self.root / 'portable' / 'simulation-models' / 'index.json'
        record = json.loads(catalog.read_text('utf-8'))['models']['PQ32-30']
        self.assertFalse(Path(record['core_path']).is_absolute())
        self.assertNotIn('elmer_home', record)
        new = self.root / '其他电脑' / 'simulation-models'
        shutil.copytree(catalog.parent, new)
        for obsolete in (self.old.parent, catalog.parent):
            self.assertTrue(obsolete.resolve().is_relative_to(self.root.resolve()))
            shutil.rmtree(obsolete)
        with patch.object(env, '_model_root', return_value=new):
            actual = env.load_environment(self.config)
        self.assertTrue(Path(actual['core_path']).is_relative_to(new))
        self.assertEqual(env._sha(actual['core_path']), record['core_sha256'])
        self.assertEqual(actual['center_leg_radius_m'], .006725)

    def test_model_zip_requires_no_old_project_package_or_solver(self):
        package = self.root / 'portable-model.zip'
        env.export_model_package(self.value, package, 'PQ32-30')
        with ZipFile(package) as archive:
            self.assertEqual(set(archive.namelist()), {'model.json', 'core.step'})
            model = json.loads(archive.read('model.json'))
            self.assertNotIn('elmer_home', model)
            self.assertNotIn('package_path', model)
        self.assertTrue(self.old.parent.resolve().is_relative_to(self.root.resolve()))
        shutil.rmtree(self.old.parent)
        actual = env.import_model_package(package, 'PQ32-30')
        self.assertTrue(Path(actual['core_path']).is_file())
        self.assertEqual(actual['r0_m'], .008)

    def test_zip_rejects_traversal_wrong_model_and_changed_cad(self):
        good = self.root / 'good.zip'
        env.export_model_package(self.value, good, 'PQ32-30')
        with self.assertRaisesRegex(ValueError, '型号'):
            env.import_model_package(good, 'PQ20-20')
        with ZipFile(good) as archive:
            original = json.loads(archive.read('model.json'))
        for filename, content, message in [('../core.step', b'evil', '实体文件'), ('core.step', b'changed', '哈希')]:
            record = dict(original, core_path=filename)
            bad = self.root / 'bad.zip'
            with ZipFile(bad, 'w') as archive:
                archive.writestr('model.json', json.dumps(record))
                archive.writestr(filename, content)
            with self.assertRaisesRegex(ValueError, message):
                env.import_model_package(bad, 'PQ32-30')
        self.assertFalse((self.root / 'core.step').exists())

    def test_explicit_machine_elmer_wins_and_three_entry_forms(self):
        home = self.root / 'ElmerFEM'
        forms = [home, home / 'bin', home / 'bin' / 'ElmerSolver.exe']
        for form in forms:
            self.assertEqual(env.normalize_elmer(form), str(home))
        env.save_environment(self.config, dict(self.value, elmer_home=str(home)))
        with patch.dict('os.environ', ELMER_HOME=str(self.root / 'wrong')):
            self.assertEqual(env.load_environment(self.config)['elmer_home'], str(home))

    def test_frame_and_cad_type_fail_with_actionable_message(self):
        for key, invalid in [('r0_m', 0.), ('z0_m', float('nan')), ('core_mode', 'guess')]:
            with self.assertRaises(ValueError):
                env.validate_model(dict(self.value, **{key: invalid}))
        stl = self.root / 'core.stl'
        stl.write_bytes(b'not a solid')
        with self.assertRaisesRegex(ValueError, 'STEP'):
            env.validate_model(dict(self.value, core_path=str(stl)))
        actual = env.check_environment(self.value, require_spice=True)
        self.assertFalse(actual['ok'])
        self.assertTrue(any(item['name'] == 'ElmerSolver.exe' and not item['ok'] for item in actual['checks']))

    def test_current_winding_frame_has_precedence_over_registered_defaults(self):
        env.save_environment(self.config, self.value)
        cfg = dict(self.config, winding_config=dict(model_3d=dict(frame=dict(r0_m_if_circular=.009, z0_m=-.008))))
        self.assertEqual(env.load_environment(cfg)['r0_m'], .009)
        self.assertEqual(env.load_environment(cfg)['z0_m'], -.008)

    def test_readonly_catalog_write_falls_back_to_user_directory(self):
        original_write = env._write
        portable = self.root/'portable'/'simulation-models'
        def readonly(path, value):
            if Path(path).resolve().is_relative_to(portable.resolve()):
                raise PermissionError('read-only program directory')
            return original_write(path, value)
        with patch.object(env, '_write', side_effect=readonly):
            saved = env.save_environment(self.config, self.value)
        self.assertTrue(Path(saved['core_path']).is_relative_to(self.root/'prefs'/'simulation-models'))
        self.assertEqual(env.load_environment(self.config)['core_path'], saved['core_path'])

    def test_invalid_portable_catalog_does_not_mask_valid_machine_fallback(self):
        saved = env.save_environment(self.config, self.value)
        catalog_path = self.root/'portable'/'simulation-models'/'index.json'
        catalog = json.loads(catalog_path.read_text('utf-8'))
        catalog['models']['PQ32-30']['core_path'] = 'missing/core.step'
        catalog_path.write_text(json.dumps(catalog), 'utf-8')
        self.assertEqual(env.load_environment(self.config)['core_path'], saved['core_path'])

    def test_model_package_cannot_inject_machine_executable(self):
        good = self.root/'injection.zip'
        record = env._model_record(self.value)
        record.update(core_path='core.step', elmer_home='unexpected executable location')
        with ZipFile(good, 'w') as archive:
            archive.writestr('model.json', json.dumps(record))
            archive.write(self.old, 'core.step')
        with self.assertRaisesRegex(ValueError, '字段'):
            env.import_model_package(good, 'PQ32-30')


if __name__ == '__main__':
    unittest.main(verbosity=2)
