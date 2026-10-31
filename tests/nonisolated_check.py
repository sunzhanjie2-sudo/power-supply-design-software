"""Physical limits, shared ESR states, endpoint hardware and export semantics."""
import copy,json,sys,unittest
from pathlib import Path
import numpy as np
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
from runtime_resources import configure_numeric_threads
configure_numeric_threads()
from nonisolated import Kernel,profile,preset,reference_settings
from design_engine.specification import load_spec
from design_engine.service import calculate_parameters
from spice_export import project_files,normalize_settings
from plants import build_loop_models

class NonisolatedChecks(unittest.TestCase):
    def test_reference_values_preserve_hardware_and_test_settings(self):
        current=preset(1)
        current.update(niso_inductor_dcr=.043,stop_ms=47.,step_ms=35.,simulation_threads=2.,
            soft_start_ms=2.,fra_start_hz=500.,fra_stop_hz=6000.,kp=123.,niso_edge_model=1.)
        result=reference_settings(1,current)
        for key in ('niso_inductor_dcr','stop_ms','step_ms','simulation_threads','soft_start_ms',
                    'fra_start_hz','fra_stop_hz','kp','niso_edge_model'):
            self.assertEqual(result[key],current[key],key)
        self.assertEqual(preset(1)['stop_ms'],40.)
        self.assertEqual(preset(1)['soft_start_ms'],1.)
    def example(self,name):return load_spec(json.loads((ROOT/'examples'/name).read_text(encoding='utf-8')))
    def test_lossless_buck_limit_and_two_capacitor_states(self):
        p=self.example('24W_BUCK_VM_TPS40200.json');p.update(Rds_on=0.,Rs=0.,Vf_diode=0.)
        k=Kernel(p,0.);x,d,off,err=k.solve()
        self.assertAlmostEqual(d,12/18,places=4);self.assertAlmostEqual(x[0],2-(18-12)*d/(p['L']*p['f_sw'])/2,places=2)
        self.assertEqual(len(x),3);self.assertLess(err,1e-8)
    def test_dcm_has_no_reverse_inductor_current(self):
        p=self.example('24W_BUCK_VM_TPS40200.json');p['P_out']=.12
        k=Kernel(p,.03);x,d,off,err=k.solve();_,il,_,_,_=k.traces(x,d,off)
        self.assertLess(d+off,.99);self.assertGreaterEqual(min(il),-1e-7);self.assertLess(err,1e-7)
    def test_reference_mismatch_and_invalid_dcr(self):
        p=self.example('24W_BUCK_VM_TPS40200.json');p['topology']='BOOST'
        with self.assertRaises(ValueError):profile(p)
        with self.assertRaises(ValueError):normalize_settings({'niso_inductor_dcr':-.5})
        p=self.example('24W_BUCK_VM_TPS40200.json');p['spice_config']={}
        with self.assertRaisesRegex(ValueError,'重新计算'):project_files(p)
    def test_three_profiles_endpoints_and_bom_semantics(self):
        names=['24W_BUCK_VM_TPS40200.json','24W_BUCK_PCM_LTC3864.json','24W_BOOST_PCM_LM5022.json']
        for i,name in enumerate(names,1):
            p=self.example(name);original=copy.deepcopy(p)
            run=calculate_parameters(p,analysis='endpoints',include_loop=True,include_cross_regulation=False)
            b=run.runtime_bundle()
            # The Web worker and report API must accept single-output metadata.
            json.dumps(run.to_dict(),allow_nan=False)
            for row in run.reports():
                self.assertTrue(row['report']['ok'])
                self.assertIsNone(row['report']['loop']['dc_load_V_per_A'])
            self.assertEqual(p,original);self.assertEqual(len(b['cases']),2)
            for c in b['cases']:
                self.assertFalse(c.get('error'));self.assertFalse(c.get('loop_error'))
                m=c['result']['op']['niso_model'];self.assertAlmostEqual(m['dcr'],.03)
                self.assertEqual(m['profile']['id'],i);self.assertLess(m['residual'],1e-7)
                self.assertEqual(c['result']['mag']['inductor']['R_dc'],.03)
                self.assertAlmostEqual(c['result']['op']['I_in_est']*c['voltage'],c['result']['op']['P_in_est'])
                self.assertEqual(c['result']['op']['efficiency_model'],'nonisolated_periodic_passive')
                from magnetics import design_inductor
                hardware=m['inductor']
                before=design_inductor(c['result']['op'],dict(c['p'],_fixed_inductor={k:hardware[k] for k in ('core','core_geometry','MLT','MLT_source','N','d_wire')}))
                after=c['result']['mag']['inductor']
                self.assertEqual(after['N'],hardware['N']);self.assertEqual(after['d_wire'],hardware['d_wire'])
                self.assertAlmostEqual(after['dT']/after['P_total'],before['dT']/before['P_total'],places=7)
                models,_=build_loop_models(c['p'],c['result']['op'])
                self.assertEqual(models[0]._loop_metadata['capacitor_states'],2)
                from loop_tuning import analyze_loop
                loop=analyze_loop(c['p'],models,c['result']['op'])
                self.assertNotIn('multi_output',loop)
                self.assertEqual(loop['model']['feedback_output'],1)
                self.assertIn('closed_loop_stable',loop)
            f=project_files(p,bundle=b);meta=json.loads(f['manifest.json'])
            self.assertEqual(meta['hardware']['kind'],'single-inductor');self.assertEqual(meta['niso']['id'],i)
            self.assertIn('Flyback.asc',f);self.assertIn(b'L1 ',f['power_stage.inc']);self.assertNotIn(b'LP ',f['power_stage.inc'])
            self.assertIn(b'I(V_D1)',f['analysis.inc']);self.assertIn(b'V(rect1)',f['analysis.inc'])
            self.assertIn(b'LIMIT_RAMP={LIMIT_RAMP}',f['power_stage.inc'])
            if i==1:self.assertIn(b'.param VM={RAMP_RATIO*(VIN-D_IN_EN*D_IN_VF)}',f['design_params.inc'])
    def test_profile_help_matches_editable_keys(self):
        from controller_logic import nonisolated_definition
        from qr_spice_settings import applicable_keys
        self.assertEqual(set(nonisolated_definition()['parameters']),set(applicable_keys('BUCK'))|set(applicable_keys('BOOST')))

if __name__=='__main__':unittest.main()
