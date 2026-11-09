"""Joint workflow ordering, invalidation and independent matrix-margin checks."""
from copy import deepcopy
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch, Mock
from zipfile import ZipFile

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
import joint_simulation as joint
from config_io import decode_config


def temporary_directory():
    base=ROOT/'artifacts/joint-workflow-check'
    base.mkdir(parents=True,exist_ok=True)
    return tempfile.TemporaryDirectory(dir=base)


def values(order=('P', 'OUT1')):
    matrix = np.asarray([[100., 45.], [45., 25.]]) * 1e-6
    return dict(port_order=list(order), L_ports_H=matrix.tolist())


class LeakageMarginChecks(unittest.TestCase):
    def test_real_hardware_freeze_is_a_loadable_public_spec(self):
        cfg=json.loads((ROOT/'examples/40W_CCM_FLYBACK.json').read_text('utf-8'))
        original=deepcopy(cfg)
        before=joint._calculate(cfg,None)
        frozen=joint._freeze_hardware(cfg,before)
        self.assertFalse(any(k.startswith('_') and not k.startswith('__') for k in frozen))
        self.assertTrue(joint.validate_spec(frozen)['ok'])
        after=joint._calculate(frozen,None)
        a=before.runtime_bundle()['cases'][0]['result']['mag']['transformer']
        b=after.runtime_bundle()['cases'][0]['result']['mag']['transformer']
        for key in ('core','Np','Ns','d_wire_p','d_wire_s','n_strand_p','n_strand_s','MLT'):
            self.assertEqual(a[key],b[key])
        self.assertEqual(cfg,original)

    def test_two_winding_closed_form_and_preserved_self_inductances(self):
        data = values()
        original = deepcopy(data)
        m = joint.apply_leakage_margin(data, 1.2)
        matrix = np.asarray(m['adopted_L_ports_H'])
        # Independent two-winding relation Lsc = Lp - M²/Ls.
        target = 1.2 * (100e-6 - (45e-6)**2 / 25e-6)
        expected_mutual = np.sqrt((100e-6-target)*25e-6)
        self.assertAlmostEqual(matrix[0, 1], expected_mutual, places=15)
        self.assertAlmostEqual(m['adopted_primary_short_H'], target, places=15)
        np.testing.assert_array_equal(matrix.diagonal(), np.array([100.,25.])*1e-6)
        self.assertEqual(data, original)

    def test_permuted_three_port_short_matches_direct_constrained_energy(self):
        # A nonuniform SPD matrix, not equal pairwise k.
        matrix = np.asarray([[9.,3.,1.],[3.,8.,2.],[1.,2.,4.]])*1e-6
        p = 1
        m = joint.apply_leakage_margin(dict(port_order=['OUT2','P','OUT1'],L_ports_H=matrix.tolist()),1.1)
        adopted = np.asarray(m['adopted_L_ports_H'])
        for sample,key in ((matrix,'original_short_by_port_H'),(adopted,'adopted_short_by_port_H')):
            inverse=np.linalg.inv(sample)
            for index in range(3):
                # Minimum stored energy with fixed Iport=1, other terminal flux=0.
                i=inverse[:,index]/inverse[index,index]
                independent=float(i @ sample @ i)
                self.assertAlmostEqual(independent,m[key][index],places=15)
        self.assertAlmostEqual(m['adopted_short_by_port_H'][p],1.1*m['original_short_by_port_H'][p],places=15)
        self.assertGreater(np.linalg.eigvalsh(adopted).min(),0)
        np.testing.assert_array_equal(adopted.diagonal(),matrix.diagonal())
        unchanged=joint.apply_leakage_margin(dict(port_order=['OUT2','P','OUT1'],L_ports_H=matrix.tolist()),1)
        np.testing.assert_allclose(unchanged['adopted_L_ports_H'],matrix,rtol=1e-15,atol=1e-20)

    def test_invalid_margin_and_impossible_target_are_not_clipped(self):
        for factor in (True,False,float('nan'),float('inf'),0,.99,None,'bad',6):
            with self.subTest(factor=factor),self.assertRaises(ValueError):
                joint.apply_leakage_margin(values(),factor)
        for matrix in ([[1,2],[2,1]], [[1,-.2],[-.2,1]], [[1,float('nan')],[0,1]]):
            with self.subTest(matrix=matrix),self.assertRaises(ValueError):
                joint.apply_leakage_margin(dict(port_order=['P','OUT1'],L_ports_H=matrix))

    def test_unity_factor_preserves_decoupled_identity_limit(self):
        diagonal=np.diag([8e-6,3e-6])
        m=joint.apply_leakage_margin(dict(port_order=['P','OUT1'],L_ports_H=diagonal.tolist()),1)
        np.testing.assert_array_equal(m['adopted_L_ports_H'],diagonal)
        with self.assertRaises(ValueError):
            joint.apply_leakage_margin(dict(port_order=['P','OUT1'],L_ports_H=diagonal.tolist()),1.01)

    def test_qr_adoption_keeps_valley_model_and_persists_full_spice_matrix(self):
        cfg=json.loads((ROOT/'examples/90W_QR_L6565_300V.json').read_text('utf-8'))
        m=joint.apply_leakage_margin(values(('OUT1','P')),1.2)
        record=dict(model_conditions=dict(core=dict(mode='half_center_gap',total_gap_m=.001,
            source='test',path='test.step',sha256='a'*64)))
        adopted,notes=joint._adopt(cfg,record,m)
        self.assertFalse(adopted['coupling_config']['enabled'])
        self.assertTrue(adopted['coupling_config']['field_matrix_enabled'])
        self.assertEqual(adopted['coupling_config']['port_order'],['P','OUT1'])
        np.testing.assert_allclose(adopted['coupling_config']['self_inductances_H'],[25e-6,100e-6])
        si=decode_config(adopted)
        self.assertAlmostEqual(si['L']*(1-si['K']),m['adopted_primary_short_H'],places=15)
        self.assertTrue(any('QR' in note for note in notes))


class WorkflowChecks(unittest.TestCase):
    def test_builtin_environment_drives_current_project_without_external_template(self):
        from contextlib import ExitStack
        with temporary_directory() as tmp:
            cfg, exe, template, patches = self.fixture(tmp)
            environment = dict(ltspice=str(exe), elmer_home='selected-local-Elmer')
            with ExitStack() as stack:
                mocks = [stack.enter_context(p) for p in patches]
                check = stack.enter_context(patch('simulation_environment.check_environment',
                    return_value=dict(ok=True, checks=[])))
                prepare = stack.enter_context(patch('portable_transformer_project.prepare_portable_reference',
                    return_value=dict(config=deepcopy(cfg), project_file=str(template), summary='current geometry')))
                result = joint.run_joint_simulation(cfg, output_directory=tmp, environment=environment)
                self.assertEqual(result['status'], 'complete')
                self.assertEqual(result['record']['runtime_mode'], 'builtin')
                self.assertEqual(check.call_args.args[0]['ltspice'], str(exe))
                self.assertTrue(check.call_args.kwargs['probe'])
                self.assertEqual(prepare.call_args.kwargs['environment']['elmer_home'], 'selected-local-Elmer')
                field = mocks[6]
                self.assertEqual(field.call_args.kwargs['tool_root'], 'builtin')
                self.assertEqual(field.call_args.kwargs['project_file'], str(template))

    def test_bad_new_machine_stops_before_any_field_or_circuit_run(self):
        from contextlib import ExitStack
        with temporary_directory() as tmp:
            cfg, exe, template, patches = self.fixture(tmp)
            with ExitStack() as stack:
                mocks = [stack.enter_context(p) for p in patches]
                stack.enter_context(patch('simulation_environment.check_environment', return_value=dict(
                    ok=False, checks=[dict(name='ElmerSolver', ok=False, message='missing on target PC')])))
                result = joint.run_joint_simulation(cfg, output_directory=tmp,
                    environment=dict(ltspice=str(exe)), prepare_reference_inputs=False)
                self.assertEqual(result['status'], 'failed')
                mocks[6].assert_not_called()
                mocks[7].assert_not_called()
                self.assertIn('missing on target PC', result['record']['error'])

    def fixture(self,tmp):
        root=Path(tmp)
        cfg=json.loads((ROOT/'examples/90W_QR_L6565_300V.json').read_text('utf-8'))
        exe=Path(sys.executable)  # mocked compare_design never executes this file
        template=root/'project.json';template.write_text(json.dumps(dict(core=dict(mode='half_center_gap',
            total_gap_m=.001,source='test',path='test.step',sha256='a'*64))),encoding='utf-8')
        evidence=root/'spice.zip'
        with ZipFile(evidence,'w') as z:z.writestr('comparison.json',json.dumps({'cases':[]}))
        field_dir=root/'field';field_dir.mkdir()
        field_record=dict(directory=str(field_dir),field=dict(values(),primary_self_H=100e-6,
            primary_short_H=19e-6,k_ports=[[1,.9],[.9,1]]),model_conditions=json.loads(template.read_text('utf-8')),
            adoption_error='')
        geometry=dict(source=dict(geometry_sha256='a'*64,engine_snapshot_id='b'*64,
                                   input_sha256='c'*64,design_id='T1'))
        run=Mock()
        run.runtime_bundle.return_value=dict(cases=[dict(id='Vinmin',loop_error=None),dict(id='Vinmax',loop_error=None)])
        def save(path):Path(path).write_text('{}');return 'd'*64
        run.save.side_effect=save
        def report(path,record,**kw):Path(path).write_bytes(b'validated separately by report checks')
        patches=[patch.object(joint,'_calculate',return_value=run),
                 patch.object(joint,'_freeze_hardware',side_effect=lambda c,r:deepcopy(c)),
                 patch.object(joint,'calculate',return_value=run),
                 patch.object(joint,'_endpoint_metrics',return_value=[dict(case='Vinmin'),dict(case='Vinmax')]),
                 patch.object(joint,'resolve_geometry',return_value=(geometry,{})),
                 patch.object(joint,'read_geometry_package',return_value=geometry),
                 patch('transformer_simulation.run_transformer_simulation',return_value=dict(record=field_record,proposed_config=deepcopy(cfg))),
                 patch('spice_runtime.compare_design',return_value=dict(path=str(evidence),incomplete=False)),
                 patch('joint_simulation_report.write_joint_report',side_effect=report)]
        return cfg,exe,template,patches

    def test_serial_workflow_preserves_caller_and_records_all_stages(self):
        from contextlib import ExitStack
        with temporary_directory() as tmp:
            cfg,exe,template,patches=self.fixture(tmp);old=deepcopy(cfg);events=[]
            with ExitStack() as stack:
                mocks=[stack.enter_context(p) for p in patches]
                result=joint.run_joint_simulation(cfg,tool_root=tmp,project_file=template,
                    output_directory=tmp,executable=exe,prepare_reference_inputs=False,progress=events.append)
                self.assertEqual(result['status'],'complete')
                self.assertEqual(cfg,old)
                self.assertEqual([s['name'] for s in result['record']['stages']],
                                 ['prepare','field','margin','calculation','spice','report'])
                self.assertTrue(all(s['status']=='complete' for s in result['record']['stages']))
                self.assertEqual(json.loads(Path(result['manifest_path']).read_text('utf-8'))['status'],'complete')
                adopted=mocks[-2].call_args.args[0]
                self.assertIs(adopted,mocks[2].return_value)
                self.assertTrue(Path(result['report_path']).is_file())
                self.assertEqual(Path(result['report_path']).name,'电磁仿真，电路仿真，设计计算联合报告.docx')
                adopted_metadata=result['proposed_config']['__transformer_simulation']
                self.assertEqual(adopted_metadata['after'],result['record']['calculation']['endpoint_metrics'])
                self.assertEqual(adopted_metadata['comparison_path'],result['report_path'])
                self.assertIn('raw_field_after',adopted_metadata)
                self.assertTrue(events)

    def test_failed_field_never_starts_calculation_or_spice(self):
        from contextlib import ExitStack
        with temporary_directory() as tmp:
            cfg,exe,template,patches=self.fixture(tmp)
            with ExitStack() as stack:
                mocks=[stack.enter_context(p) for p in patches]
                mocks[-3].side_effect=ValueError('field mesh failed')
                result=joint.run_joint_simulation(cfg,tool_root=tmp,project_file=template,
                    output_directory=tmp,executable=exe,prepare_reference_inputs=False)
                self.assertEqual(result['status'],'failed')
                mocks[2].assert_not_called();mocks[-2].assert_not_called()
                states={s['name']:s['status'] for s in result['record']['stages']}
                self.assertEqual(states['field'],'failed');self.assertEqual(states['spice'],'skipped')
                self.assertIn('field mesh failed',result['summary'])
                self.assertTrue(Path(result['report_path']).is_file())

    def test_cancellation_stops_before_next_solver_and_keeps_record(self):
        from contextlib import ExitStack
        with temporary_directory() as tmp:
            cfg,exe,template,patches=self.fixture(tmp)
            with ExitStack() as stack:
                mocks=[stack.enter_context(p) for p in patches]
                result=joint.run_joint_simulation(cfg,tool_root=tmp,project_file=template,
                    output_directory=tmp,executable=exe,prepare_reference_inputs=False,cancelled=lambda:True)
                self.assertEqual(result['status'],'cancelled')
                mocks[-3].assert_not_called();mocks[-2].assert_not_called()
                self.assertTrue(Path(result['manifest_path']).is_file())

    def test_invalid_multiplier_rejected_before_field(self):
        from contextlib import ExitStack
        with temporary_directory() as tmp:
            cfg,exe,template,patches=self.fixture(tmp)
            with ExitStack() as stack:
                mocks=[stack.enter_context(p) for p in patches]
                result=joint.run_joint_simulation(cfg,tool_root=tmp,project_file=template,
                    output_directory=tmp,executable=exe,prepare_reference_inputs=False,leakage_factor=True)
                self.assertEqual(result['status'],'failed');mocks[-3].assert_not_called()


if __name__=='__main__':unittest.main(verbosity=2)
