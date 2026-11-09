"""Independent copper identities, fixed hardware and physical parallel wire counts."""
import copy,json,math,sys,unittest
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
from runtime_resources import configure_numeric_threads
configure_numeric_threads()
from design_api import load_spec
from loss_model import compute_design
from analysis_workflows import pin_hardware
from winding_layout import transformer_windings,assess_winding_window,iter_bundle_sections


class ParallelWires(unittest.TestCase):
    def test_two_complete_wires_double_copper_without_changing_turns(self):
        p=load_spec({'topology':'FLYBACK','core_choice':'PQ20-20','Np':6,'Ns':12,
            'd_wire_p':.3e-3,'d_wire_s':.2e-3,'n_strand_p':1,'n_strand_s':3})
        a=compute_design(p);q=dict(p,parallel_wires_p=2,parallel_wires_s=2);b=compute_design(q)
        x,y=(r['mag']['transformer'] for r in (a,b))
        for side in ('p','s'):
            self.assertAlmostEqual(y['R_dc_'+side],x['R_dc_'+side]/2)
            self.assertAlmostEqual(y['J_actual_'+side],x['J_actual_'+side]/2)
        self.assertEqual(y['Np'],6);self.assertEqual(y['Ns'],12)
        self.assertAlmostEqual(y['fill'],2*x['fill'])
        self.assertAlmostEqual(y['P_cu'],x['P_cu']/2)
        rows=transformer_windings(b)
        assessment=assess_winding_window(rows,dict(window_width=.02,window_height=.02))
        primary=assessment['windings'][0]
        self.assertEqual(primary['parallel_wires'],2)
        self.assertEqual(primary['bundle_count'],12)
        self.assertEqual(len(list(iter_bundle_sections(primary,assessment['config']))),12)
        self.assertEqual(primary['conductor_count'],12)
        fixed=pin_hardware(q,b)
        self.assertEqual(fixed['_fixed_transformer']['parallel_wires_p'],2)
        self.assertEqual(compute_design(dict(fixed,V_in=35))['mag']['transformer']['parallel_wires_p'],2)

    def test_coupled_multi_dcr_is_the_same_total_copper_geometry(self):
        p=json.loads((ROOT/'examples/40W_CCM_3OUT_FLYBACK.json').read_text(encoding='utf-8'))
        p['parallel_wires_p']=2
        p['outputs'][1]['parallel_wires_s']=3
        p=load_spec(p);r=compute_design(p)
        t=r['mag']['transformer'];hw=r['op']['coupled_model']['transformer_hardware']
        self.assertEqual(t['Np'],6)
        self.assertEqual(t['windings'][1]['parallel_wires_s'],3)
        self.assertAlmostEqual(t['R_dc_p'],p['rho']*t['MLT']*t['Np']/(2*t['n_strand_p']*math.pi*t['d_wire_p']**2/4))
        w=t['windings'][1]
        self.assertAlmostEqual(w['R_dc'],p['rho']*t['MLT']*w['Ns']/(3*w['n_strand_s']*math.pi*w['d_wire_s']**2/4))
        self.assertAlmostEqual(hw['windings'][1]['R_dc'],w['R_dc'])
        fixed=pin_hardware(p,r)
        self.assertEqual(fixed['outputs'][1]['parallel_wires_s'],3)

    def test_defaults_one_and_invalid_inputs(self):
        from parallel_wires import count
        self.assertEqual(count({},'p'),1)
        for value in (0,-1,1.2,True,float('inf')):
            with self.subTest(value=value),self.assertRaises(ValueError):count({'parallel_wires_p':value},'p')
        from example_catalog import EXAMPLES
        for file in EXAMPLES:
            p=load_spec(json.loads((ROOT/'examples'/file).read_text(encoding='utf-8-sig')))
            self.assertEqual(p['parallel_wires_p'],1);self.assertEqual(p['parallel_wires_s'],1)
            self.assertTrue(all(w.get('parallel_wires_s',1)==1 for w in p.get('outputs',[])))

    def test_qr_and_forward_keep_parallel_copper_in_their_transformer(self):
        for filename in ['90W_QR_L6565_300V.json','33W_3OUT_ACF_MP6005_COMPACT.json']:
            with self.subTest(filename=filename):
                p=json.loads((ROOT/'examples'/filename).read_text(encoding='utf8'))
                p['parallel_wires_p']=2;p['parallel_wires_s']=3
                if p.get('outputs'):p['outputs'][0]['parallel_wires_s']=3
                p=load_spec(p);r=compute_design(p);t=r['mag']['transformer']
                self.assertEqual(t['parallel_wires_p'],2)
                expected=p['rho']*t['MLT']*t['Np']/(2*t['n_strand_p']*math.pi*t['d_wire_p']**2/4)
                self.assertAlmostEqual(t['R_dc_p'],expected)
                if t.get('windings'):
                    self.assertEqual(t['windings'][0]['parallel_wires_s'],3)
                else:self.assertEqual(t['parallel_wires_s'],3)


if __name__=='__main__':unittest.main(verbosity=2)
