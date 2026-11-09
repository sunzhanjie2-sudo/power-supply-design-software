"""Purchased L stays electrical; absent geometry must not leak into results."""
import copy
import json
from pathlib import Path
import sys
import unittest
from unittest.mock import patch
import numpy as np

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from runtime_resources import configure_numeric_threads
configure_numeric_threads()
from power_stage import DEFAULT_PARAMS, validate_design_inputs
from loss_model import compute_design
from design_engine.service import calculate, validate_spec
from design_checks import check_catalog


def spec(topo='BUCK'):
    return dict(topology=topo, control_mode='Voltage Mode', V_in_min=24., V_in_max=32.,
                V_out=12. if topo=='BUCK' else 48. if topo=='BOOST' else 24.,
                P_out=12., L=100e-6, f_sw=100e3, inductor_design_enabled=False,
                inductor_dcr=.035, inductor_rated_current=2.,
                inductor_saturation_current=3., inductor_extra_loss=.12,
                outputs=[], spice_config={}, d_in_enable=False, d_out_enable=False)


class PurchasedInductorChecks(unittest.TestCase):
    def test_three_topologies_keep_electrical_calculation_without_core(self):
        for topo in ('BUCK','BOOST','BUCK-BOOST'):
            p=dict(copy.deepcopy(DEFAULT_PARAMS),**spec(topo),V_in=24.)
            with patch('magnetics.resolve_core', side_effect=AssertionError('must not design core')):
                result=compute_design(p)
            dev=result['mag']['inductor']
            self.assertTrue(dev['ok']);self.assertFalse(dev['design_enabled'])
            self.assertEqual(dev['L'],p['L'])
            self.assertAlmostEqual(dev['P_cu'],result['op']['I_L_rms']**2*.035)
            self.assertAlmostEqual(result['P_mag'],dev['P_cu']+.12)
            self.assertIsNone(dev['B_pk']);self.assertIsNone(dev['dT'])
            self.assertNotIn('Ae',dev);self.assertNotIn('N',dev)
            auto=compute_design(dict(p,inductor_design_enabled=True))
            for key in ('L','D','I_L_rms','I_L_pk','V_sw_max'):
                self.assertEqual(result['op'][key],auto['op'][key])
            np.testing.assert_array_equal(result['wf']['iL'],auto['wf']['iL'])
            self.assertIn('Ae',auto['mag']['inductor'])

    def test_L_is_required_and_component_inputs_validated(self):
        self.assertFalse(validate_spec(dict(spec(),L=0))['ok'])
        for key in ('inductor_dcr','inductor_rated_current','inductor_saturation_current','inductor_extra_loss'):
            self.assertFalse(validate_spec(dict(spec(),**{key:-1}))['ok'])
        self.assertFalse(validate_spec(dict(spec(),inductor_design_enabled=0))['ok'])
        self.assertTrue(validate_spec(dict(spec(),core_choice='custom',custom_core={},Bmax=0.,Ku=0.,h_conv=0.))['ok'])

    def test_same_purchased_hardware_endpoints_loops_and_serialization(self):
        for topo in ('BUCK','BOOST','BUCK-BOOST'):
            original=spec(topo)
            run=calculate(original,analysis='endpoints',include_cross_regulation=False)
            bundle=run.runtime_bundle()
            self.assertTrue(bundle['fixed_hardware'])
            self.assertFalse(bundle['hardware']['inductor']['design_enabled'])
            self.assertNotIn('core',bundle['hardware']['inductor'])
            for case in bundle['cases']:
                self.assertIsNone(case['error']);self.assertIsNone(case['loop_error'])
                self.assertEqual(case['result']['mag']['inductor']['R_dc'],.035)
            json.dumps(run.to_dict(),allow_nan=False)
            for row in run.reports():
                self.assertFalse(row['report']['magnetics']['design_enabled'])
                self.assertIsNone(row['report']['magnetics']['B_pk'])
            self.assertEqual(original,spec(topo))

    def test_missing_ratings_are_unknown_and_low_ratings_fail(self):
        for rating,state in ((0.,'undefined'),(.001,'review'),(100.,'pass')):
            p=dict(copy.deepcopy(DEFAULT_PARAMS),**spec(),V_in=24.)
            p.update(inductor_rated_current=rating,inductor_saturation_current=rating)
            result=compute_design(p)
            checks={row['id']:row for row in check_catalog(p,result)}
            self.assertEqual(checks['inductor_rms']['state'],state)
            self.assertEqual(checks['inductor_peak']['state'],state)
            self.assertNotIn('B_sat',checks)
            self.assertEqual(checks['inductor_thermal']['state'],'undefined')
        p=dict(p,inductor_dcr=0.,inductor_extra_loss=0.)
        checks={row['id']:row for row in check_catalog(p,compute_design(p))}
        self.assertEqual(checks['inductor_dcr']['state'],'undefined')
        self.assertEqual(checks['inductor_extra_loss']['state'],'undefined')

    def test_buck_boost_controller_and_spice_share_component_dcr(self):
        from nonisolated import preset
        from spice_export import project_files
        for profile,name in enumerate(('24W_BUCK_VM_TPS40200.json','24W_BUCK_PCM_LTC3864.json','24W_BOOST_PCM_LM5022.json'),1):
            from design_engine.specification import load_spec
            p=load_spec(json.loads((ROOT/'examples'/name).read_text(encoding='utf-8')))
            p.update({key:value for key,value in spec().items() if key.startswith('inductor_')})
            p['spice_config']=dict(preset(profile),niso_inductor_dcr=.9)
            run=calculate(p,analysis='endpoints',include_cross_regulation=False)
            bundle=run.runtime_bundle()
            for case in bundle['cases']:
                self.assertIsNone(case['error']);self.assertIsNone(case['loop_error'])
                self.assertEqual(case['result']['op']['niso_model']['dcr'],.035)
                self.assertAlmostEqual(case['result']['mag']['inductor']['P_cu'],
                                       case['result']['op']['I_L_rms']**2*.035)
            files=project_files(bundle['base_spec'],bundle=bundle)
            params=files['design_params.inc'].decode('utf-8')
            self.assertIn('.param RL1=0.035',params)

    def test_switch_does_not_disable_transformer_or_forward_design(self):
        for topo in ('FLYBACK','QR-FLYBACK','ACF-FORWARD'):
            p=copy.deepcopy(DEFAULT_PARAMS);p.update(topology=topo,outputs=[],inductor_design_enabled=False)
            if topo=='QR-FLYBACK':p.update(V_in=300.,V_out=24.,P_out=20.,L=500e-6,N=5.)
            result=compute_design(p)
            self.assertTrue(result['mag']['transformer']['ok'])
            self.assertIn('Ae',result['mag']['transformer'])

    def test_corner_analysis_does_not_invent_flux_or_temperature(self):
        from analysis_workflows import corners
        from design_engine.specification import load_spec
        result=corners(load_spec(spec()),load_fracs=(.5,1.))
        self.assertTrue(all(not row['skipped'] for row in result['corners']))
        self.assertTrue(all(row['B_pk'] is None and row['dT'] is None for row in result['corners']))

    def test_report_loss_equation_has_native_subscripts(self):
        from word_math import math_nodes
        from docx.oxml.ns import qn
        nodes=math_nodes('PL=ILrms^2·Rdc+Pextra')
        subs=[item for node in nodes for item in node.iter(qn('m:sSub'))]
        self.assertGreaterEqual(len(subs),4)
        self.assertFalse(any('_' in (item.text or '') for node in nodes for item in node.iter(qn('m:t'))))


if __name__=='__main__':unittest.main()
