"""ACF contract checks; physical timing and FRA have separate simulator QA."""
import copy
import json
from pathlib import Path
import sys
import unittest
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
from design_engine.service import calculate_parameters
from design_engine.specification import load_spec
from spice_export import project_files,normalize_settings
from spice_studies import prepare_fra
from acf_cross import estimate
from controller_logic import acf_definition
from qr_spice_settings import applicable_keys


class ACFChecks(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.p=load_spec(json.loads((ROOT/'examples/33W_3OUT_ACF_MP6005.json').read_text(encoding='utf-8')))
        cls.bundle=calculate_parameters(cls.p,analysis='endpoints',include_loop=True,include_cross_regulation=False).runtime_bundle()
        cls.files=project_files(cls.p,bundle=cls.bundle)
        cls.meta=json.loads(cls.files['manifest.json'])

    def test_physical_clamp_and_shared_hardware(self):
        p=self.p;m=self.meta;s=self.files['power_stage.inc'].decode()
        self.assertEqual(m['topology'],'ACF-FORWARD');self.assertEqual(m['voltages'],[20.,30.])
        self.assertIn('C_ACTIVE drain aclamp',s);self.assertIn('XQA aclamp auxgate 0 GACF_PMOS',s)
        self.assertNotIn('D_SN1',s);self.assertIn('LP vin_bus drain',s)
        self.assertNotEqual(p['L'],p['Lm_forward'])
        self.assertIn(f'.param LP={p["Lm_forward"]:.12g}',self.files['design_params.inc'].decode())
        for i in range(1,4):
            self.assertIn(f'LS{i} rect{i} sgnd',s)
            self.assertIn(f'LO{i} choke{i} cap{i}',s)
            self.assertIn(f'XD_F{i} sgnd choke{i}',s)
        self.assertIn(b'SYMBOL GACF_CTRL',self.files['Flyback.asc'])
        self.assertIn('Flyback.plt',self.files)
        self.assertIn(b'(-I(LS1))',self.files['analysis.inc'])

    def test_ui_and_model_limitations_are_explicit(self):
        d=acf_definition();keys=applicable_keys('ACF-FORWARD')
        self.assertEqual(set(d['parameters']),set(keys))
        self.assertIn('acf_dead_ns',keys);self.assertNotIn('qr_cds_pf',keys)
        self.assertNotIn('acf_dead_ns',applicable_keys('FLYBACK'))
        self.assertTrue(any('PSM' in n for n in self.meta['approximation_notes']))

    def test_fra_enable_outlives_transient_and_identical_half_frequencies(self):
        files,_=prepare_fra(self.files,self.meta,self.meta['settings'])
        self.assertIn(b'.param TSTOP=1000000',files['design_params.inc'])
        self.assertIn(b'nmax=1',files['power_stage.inc'])
        self.assertIn(b'tsettle=0.002',files['power_stage.inc'])

    def test_cross_prediction_does_not_force_every_rail_voltage(self):
        from isolated_outputs import output_specs
        rails=output_specs(self.p)
        a=estimate(self.p,rails,self.meta['hardware'],self.meta['coupling']['k'])
        light=copy.deepcopy(rails);light[0]['P_out']=light[0]['P_out_min']
        b=estimate(self.p,light,self.meta['hardware'],self.meta['coupling']['k'])
        self.assertAlmostEqual(a['voltages'][0],30.,places=6)
        self.assertAlmostEqual(b['voltages'][0],30.,places=6)
        self.assertGreater(abs(a['voltages'][1]-b['voltages'][1]),.3)
        self.assertLess(a['residual'],1e-5)

    def test_no_wrong_topology_snapshot_or_deadtime(self):
        old=copy.deepcopy(self.bundle);old['cases'][0]['p']['topology']='FLYBACK'
        with self.assertRaisesRegex(ValueError,'快照'):project_files(self.p,bundle=old)
        p=copy.deepcopy(self.p);p['spice_config']['acf_dead_ns']=1000.
        with self.assertRaisesRegex(ValueError,'死区'):project_files(p,bundle=self.bundle)

    def test_retained_window_shows_overflow_without_an_invalid_layer(self):
        from winding_layout import transformer_windings,assess_winding_window
        a=assess_winding_window(transformer_windings(self.bundle['cases'][0]['result']),self.p['winding_config'])
        self.assertTrue(a['configured']);self.assertFalse(a['fits'])
        self.assertTrue(a['interleaved']);self.assertLess(a['height_margin'],0)

    def test_retry_respects_the_endpoint_total_time_budget(self):
        from unittest.mock import Mock
        from spice_studies import retry_cross_corners
        settings=dict(self.meta['settings'],cross_timeout_s=1800.)
        record=dict(id='X002',settled=False,powers=[2.,1.,2.])
        result=dict(elapsed_s=1800.,records=[record]);execute=Mock()
        retry_cross_corners(result,{},self.meta,settings,ROOT/'artifacts/qa/acf/unstarted',execute,[])
        execute.assert_not_called();self.assertIn('预算',record['retry_error'])


if __name__=='__main__':unittest.main()
