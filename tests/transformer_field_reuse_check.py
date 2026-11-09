"""Load-only reuse never changes field identity or ignores physical changes."""
from copy import deepcopy
import hashlib
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch
from zipfile import ZipFile

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from calculation_scheduler import CalculationCancelled
from design_engine.specification import load_spec
import transformer_field_reuse as reuse


def config():
    return load_spec(json.loads((ROOT/'examples/40W_CCM_FLYBACK.json').read_text('utf-8-sig')))


def fixtures(core_sha):
    project = dict(core=dict(path='actual.step',sha256=core_sha,mode='half_center_gap',total_gap_m=.00094),
        material=dict(name='DMR44',relative_permeability=2400.,temperature_C=25.,frequency_Hz=0.,bias_current_A=0.),
        frame=dict(z0_m=-.0094,r0_m=.008),solver=dict(mesh_profile='coarse'),classification='reference_assumptions')
    geometry = {key:{} for key in reuse._GEOMETRY}
    geometry.update(schema='power-transformer.geometry.v1', units='SI', source=dict(geometry_sha256='original'),
        core=dict(calculator_core='PQ32-30',calculator_material='DMR44',geometry_reference=None,
            geometry_sha256=None,material_reference=None,gap_geometry=None),
        windings=[dict(id='P',turns=60),dict(id='OUT1',turns=30)],
        physical_sections=[dict(section_id='P_A',turns=60)],
        connections=[dict(winding_id='P',dot_node='P_D')],
        design_targets=dict(air_gap=dict(mu_r=2400.,gap_m=.00094)))
    return project, geometry


class FieldReuseChecks(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        (ROOT/'artifacts').mkdir(exist_ok=True)

    def test_only_output_power_changes_survive_SI_normalization(self):
        before = config()
        current = deepcopy(before)
        current['P_out'] = dict(v=50000.,u='m')
        delta, metadata = reuse._load_changes(before,current)
        self.assertEqual(delta,[dict(path=['P_out'],before=40.,current=50.)])
        self.assertEqual(metadata,[])
        current['P_out'] = dict(v=40000.,u='m')
        self.assertEqual(reuse._load_changes(before,current),([],[]))

    def test_output_list_power_allowed_but_turns_and_control_rejected(self):
        before = load_spec(json.loads((ROOT/'examples/40W_CCM_3OUT_FLYBACK.json').read_text('utf-8-sig')))
        current = deepcopy(before)
        current['outputs'][1].update(P_out=.1,P_out_min=.01)
        delta,_ = reuse._load_changes(before,current)
        self.assertEqual({tuple(d['path']) for d in delta},
                         {('outputs',1,'P_out'),('outputs',1,'P_out_min')})
        for changed in (dict(f_sw=250001.),dict(L=9e-6),dict(Np=7)):
            with self.subTest(changed=changed), self.assertRaisesRegex(ValueError,'非负载差异'):
                reuse._load_changes(before,dict(current,**changed))
        current['outputs'][1]['Ns'] += 1
        with self.assertRaisesRegex(ValueError,'非负载差异'):
            reuse._load_changes(before,current)

    def test_geometry_provenance_seal_is_proven_against_original_CAD(self):
        project,old = fixtures('a'*64)
        new = deepcopy(old)
        new['core'].update(geometry_sha256='a'*64,geometry_reference='actual.step',
            gap_geometry=dict(type='center_leg_ground',length_m=.00094,source='实物复核'))
        delta = reuse._geometry_audit(old,new,project,'a'*64)
        self.assertEqual(len(delta),3)
        bad = deepcopy(new)
        bad['core']['geometry_sha256'] = 'b'*64
        with self.assertRaisesRegex(ValueError,'SHA'):
            reuse._geometry_audit(old,bad,project,'a'*64)
        bad = deepcopy(new)
        bad['core']['gap_geometry']['length_m'] += 1e-5
        with self.assertRaisesRegex(ValueError,'气隙'):
            reuse._geometry_audit(old,bad,project,'a'*64)

    def test_geometric_dimension_connection_and_mu_edits_are_blocked(self):
        project,old = fixtures('a'*64)
        for key,value in [('bobbin',dict(radial_window_m=.0051)),
                          ('physical_sections',[dict(section_id='P_A',turns=61)]),
                          ('connections',[dict(winding_id='P',dot_node='P_R')])]:
            new=deepcopy(old);new[key]=value
            with self.subTest(key=key),self.assertRaisesRegex(ValueError,'几何/接线'):
                reuse._geometry_audit(old,new,project,'a'*64)
        new=deepcopy(old);new['design_targets']['air_gap']['mu_r']=2200.
        with self.assertRaisesRegex(ValueError,'磁导率'):
            reuse._geometry_audit(old,new,project,'a'*64)

    def test_frequency_and_bias_must_both_be_explicitly_zero(self):
        project,_=fixtures('a'*64)
        for key,value in [('frequency_Hz',100000.),('bias_current_A',.1),('frequency_Hz',None)]:
            changed=deepcopy(project);changed['material'][key]=value
            with self.subTest(key=key,value=value),self.assertRaisesRegex(ValueError,'0 Hz'):
                reuse._zero_bias(changed)

    def test_cancel_and_corrupt_original_abort_before_calculation(self):
        with patch.object(reuse,'verify_field_result') as verify:
            with self.assertRaises(CalculationCancelled):
                reuse.complete_load_rebound_field_comparison({},'old.zip','old','new',cancelled=lambda:True)
            verify.assert_not_called()
        with tempfile.TemporaryDirectory(dir=ROOT/'artifacts') as folder:
            path=Path(folder)/'old.zip';path.touch()
            with patch.object(reuse,'verify_field_result',side_effect=ValueError('原artifact损坏')) as verify,\
                 patch.object(reuse,'_calculate') as calculate:
                with self.assertRaisesRegex(ValueError,'artifact'):
                    reuse.complete_load_rebound_field_comparison({},path,folder,Path(folder)/'new')
                verify.assert_called_once_with(folder,path.resolve(),cancelled=None)
                calculate.assert_not_called()

    def test_new_binding_keeps_old_artifacts_byte_for_byte(self):
        with tempfile.TemporaryDirectory(dir=ROOT/'artifacts') as folder:
            folder=Path(folder);original=folder/'old.zip';field=folder/'field';field.mkdir()
            (field/'inputs').mkdir();core=field/'inputs/core.step';core.write_bytes(b'actual CAD')
            project,geometry=fixtures(hashlib.sha256(core.read_bytes()).hexdigest())
            (field/'inputs/project.json').write_text(json.dumps(project),encoding='utf-8')
            (field/'results.json').write_text('{"original":true}',encoding='utf-8')
            before=config();current=dict(deepcopy(before),P_out=41.)
            with ZipFile(original,'w') as archive:
                archive.writestr('calculator-input.json',json.dumps(before))
            retained={p:p.read_bytes() for p in (original,core,field/'results.json',field/'inputs/project.json')}
            output=folder/'new'
            record=dict(limits=[],report_path=str(field/'report.html'))
            def export(_run,path,cfg,**kw):
                self.assertEqual(cfg,current)
                Path(path).write_bytes(b'new ZIP, distinct from original')
            def compare(cfg,package,result,where,**kw):
                self.assertEqual(cfg,current)
                self.assertEqual(result,field)
                self.assertNotEqual(package,original)
                return dict(record=deepcopy(record),notes=[],proposed_config=deepcopy(cfg),
                    comparison_path=str(output/'comparison.html'))
            with patch.object(reuse,'verify_field_result',return_value=field) as verify,\
                 patch.object(reuse,'read_geometry_package',side_effect=[deepcopy(geometry),deepcopy(geometry)]),\
                 patch.object(reuse,'_calculate',return_value=None),\
                 patch.object(reuse,'export_geometry_package',side_effect=export),\
                 patch.object(reuse,'_compare_verified',side_effect=compare),\
                 patch('transformer_sim_report.write_comparison'):
                result=reuse.complete_load_rebound_field_comparison(current,original,field,output)
            verify.assert_called_once_with(field,original.resolve(),cancelled=None)
            audit=result['record']['reused_field_provenance']
            self.assertFalse(audit['field_solver_rerun'])
            self.assertFalse(audit['original_artifacts_rewritten'])
            self.assertNotEqual(audit['original_package_sha256'],audit['new_package_sha256'])
            self.assertEqual(audit['load_changes'][0]['path'],['P_out'])
            self.assertTrue((output/'场解负载重绑定审计.json').is_file())
            for path,value in retained.items():
                self.assertEqual(path.read_bytes(),value)


if __name__=='__main__':
    unittest.main(verbosity=2)
