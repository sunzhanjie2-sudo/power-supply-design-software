"""Independent RLC laws, multi-output ownership and ASC/CIR contracts."""
import copy
import json
import math
from pathlib import Path
import re
import sys
import unittest
import numpy as np
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
from runtime_resources import configure_numeric_threads
configure_numeric_threads()
from parasitics import normalize,resolved,augment_matrix
from parasitic_ringing import solve_edge
from design_engine.specification import load_spec
from loss_model import compute_design


def example(name):return load_spec(json.loads((ROOT/'examples'/name).read_text(encoding='utf-8')))


class ParasiticChecks(unittest.TestCase):
    def test_invalid_inputs_and_default_migration(self):
        for bad in ({'mode':'cosmetic'},{'lp_pcb':-1},{'cj_default':float('nan')},{'r_cj':0},{'rails':{'OUT7':{}}},{'coss':True}):
            with self.assertRaises(ValueError):normalize(bad)
        p=example('90W_QR_L6565_300V.json');c=resolved(p)
        self.assertAlmostEqual(c['coss'],470e-12)
        p['parasitic_config']={'coss':800e-12,'rails':{'OUT1':{'cj':70e-12}}}
        c=resolved(p);self.assertAlmostEqual(c['coss'],800e-12);self.assertAlmostEqual(c['rails'][0]['cj'],70e-12)

    def test_exact_damped_second_order_solution(self):
        L=100e-9;C=500e-12;R=2.;I=2.
        z=solve_edge(L,C,R,I,100.)
        alpha=R/(2*L);wd=math.sqrt(1/(L*C)-alpha**2)
        expected=100+I/(C*wd)*np.exp(-alpha*z['t'])*np.sin(wd*z['t'])
        self.assertLess(float(max(abs(z['voltage']-expected))),2e-5)
        self.assertLess(z['energy_final'],z['energy_initial'])

    def test_actual_clamp_and_rc_damp_without_painted_sine(self):
        base=dict(inductance=100e-9,capacitance=500e-12,resistance=.2,current=3.,plateau=100.)
        free=solve_edge(**base);clamp=solve_edge(**base,ceiling=115.)
        snub=solve_edge(**base,snub_r=10.,snub_c=2e-9)
        self.assertTrue(clamp['clamped']);self.assertAlmostEqual(clamp['peak'],115.,places=5)
        self.assertLess(snub['peak'],free['peak'])
        self.assertLess(snub['energy_final'],snub['energy_initial']*.01)

    def test_zero_leakage_has_no_manufactured_peak(self):
        z=solve_edge(0,500e-12,1,3,100,ceiling=130)
        self.assertEqual(z['peak'],100);self.assertIsNone(z['frequency'])

    def test_all_ideal_kij_cannot_create_numerical_leakage(self):
        p=example('40W_CCM_FLYBACK.json')
        p.update(coupling_config={'enabled':True,'k':[[1.,1.],[1.,1.]]},parasitic_config={'mode':'transient'})
        result=compute_design(p)
        self.assertTrue(all(z['frequency'] is None for z in result['op']['parasitics']['edges']))

    def test_uncoupled_series_l_preserves_mutual_and_input(self):
        L=np.array([[8e-6,3e-6],[3e-6,2e-6]])
        m=dict(L=L,R=np.array([.1,.2]));p=example('40W_CCM_FLYBACK.json')
        p['parasitic_config']={'lp_pcb':100e-9,'rails':{'OUT1':{'l_pcb':50e-9}}}
        n=augment_matrix(m,resolved(p));self.assertEqual(n['L'][0,1],L[0,1])
        self.assertAlmostEqual(n['L'][0,0]-L[0,0],100e-9)
        self.assertEqual(L[0,0],8e-6)

    def test_fast_mode_preserves_old_numerics_and_three_output_ownership(self):
        p=example('40W_CCM_3OUT_FLYBACK.json');before=copy.deepcopy(p)
        a=compute_design(p);q=copy.deepcopy(p);q['parasitic_config']={'mode':'fast'}
        b=compute_design(q)
        self.assertEqual(a['eta'],b['eta']);np.testing.assert_array_equal(a['wf']['v_sw'],b['wf']['v_sw'])
        q['parasitic_config'].update(mode='transient',rails={'OUT2':{'cj':100e-12}})
        c=compute_design(q);self.assertEqual(len(c['op']['parasitics']['edges']),4)
        self.assertEqual(p,before)
        for key in ('D','V_out','I_sw_rms'):self.assertEqual(a['op'][key],c['op'][key])
        self.assertGreaterEqual(c['op']['V_sw_max'],a['op']['V_sw_max'])

    def test_qr_effective_capacitance_changes_timing_and_export(self):
        from power_stage import compute_operating_point
        from spice_export import project_files
        p=example('90W_QR_L6565_300V.json');old=compute_operating_point(p)
        p['parasitic_config']={'mode':'fast','coss':900e-12}
        new=compute_operating_point(p);self.assertNotEqual(new['T_ring'],old['T_ring'])
        files=project_files(p);m=json.loads(files['manifest.json'])
        self.assertAlmostEqual(m['qr']['cds_f'],900e-12)
        self.assertIn(b'.param Q_COSS=9e-10',files['design_params.inc'])
        self.assertIn(b'.include parasitics.inc',files['Flyback.asc'])

    def test_spice_and_native_sheet_share_per_device_values(self):
        from spice_export import project_files
        p=example('40W_CCM_FLYBACK.json');p['parasitic_config']={'mode':'fast','coss':400e-12,'lp_pcb':50e-9,
            'cw_primary':30e-12,'snub_r_primary':22.,'snub_c_primary':100e-12,'r_cj':.2,'rails':{'OUT1':{'cj':75e-12}}}
        files=project_files(p);params={k:float(v) for k,v in re.findall(r'(?m)^\.param (\w+)=([-+\d.eE]+)',files['design_params.inc'].decode())}
        self.assertAlmostEqual(params['LP'],p['L']+50e-9)
        self.assertAlmostEqual(params['K_0_1']*math.sqrt(params['LP']*params['LS1']),math.sqrt(p['K'])*math.sqrt(p['L']*params['LS1']))
        for name in ('Flyback.asc','power_stage.inc'):
            self.assertIn(b'CJ={PAR_D_O1_CJ} RCJ={PAR_RCJ}',files[name])
        self.assertIn(b'Rser={RCJ}',files['GenericFlybackPWM.lib'])
        self.assertIn(b'Xbody S D GPWR_DIODE VF=0.8 CJ=0',files['GenericFlybackPWM.lib'])
        self.assertIn(b'R_PAR_Q1',files['parasitics.inc'])
        self.assertIn(b'.include parasitics.inc',files['Flyback.cir'])

    def test_acf_new_parts_are_actual_state_variables(self):
        from power_stage import compute_operating_point
        from winding_coupling import resolve_winding_geometry,resolve_winding_model
        from acf_periodic import PeriodicForward
        p=example('33W_3OUT_ACF_MP6005_COMPACT.json')
        p['parasitic_config']={'r_cj':.3,'cw_primary':25e-12,'snub_c_primary':100e-12,
            'rails':{'OUT2':{'cj':60e-12,'snub_c':150e-12}}}
        nominal=compute_operating_point(dict(p,coupling_config={'enabled':False}))
        rails=nominal['outputs'];g=resolve_winding_geometry(p,nominal,rails);m=resolve_winding_model(p,rails,geometry=g)
        c=PeriodicForward(p,rails,g,m)
        self.assertEqual(len(c.extra_rc),2);self.assertAlmostEqual(c.cj_values[4],60e-12)
        self.assertEqual(c.cj_values[:2],[0.,0.])
        self.assertAlmostEqual(c.E[c.base,c.base],p['Coss']+25e-12)


if __name__=='__main__':unittest.main(verbosity=2)
