"""Preset efficiency: all topologies, charge/power balance, GUI/API and losses."""
import copy
from pathlib import Path
import sys
import unittest

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from power_stage import DEFAULT_PARAMS, TOPOLOGIES, compute_operating_point, compute_nonllc_op, compute_qrflyback_op
from active_clamp import compute_forward_op
from loss_model import compute_design, efficiency_curve, recompute_qr_eta
from waveforms import make_waveforms
from plants import build_loop_models
from design_api import run_design, autotune_loop, loop_margins_for
from config_io import read_default_config, decode_config
from design_checks import check_catalog


def spec(topo, eta=.93, light=False):
    return dict(DEFAULT_PARAMS, topology=topo, eta_guess=eta, V_in=30,
                V_out=15 if topo == 'BUCK' else 40 if topo == 'BOOST' else 30,
                P_out=1 if light else 40, L=68e-6 if topo == 'ACF-FORWARD' else 100e-6,
                N=.5, Kc=0, core_choice='auto', core_shape='auto',
                Np=0, Ns=0, d_wire_p=0, d_wire_s=0, MLT=0)


class PresetChecks(unittest.TestCase):
    def test_power_and_charge_for_all_modes(self):
        for topo in TOPOLOGIES:
            for eta in (1., .93, .8):
                for light in (False, True):
                    with self.subTest(topo=topo, eta=eta, light=light):
                        p=spec(topo, eta, light); o=compute_operating_point(p)
                        w=make_waveforms(o, n_pts=100000)
                        self.assertAlmostEqual(o['I_out'], p['P_out']/p['V_out'])
                        self.assertAlmostEqual(o['P_in_est'], p['P_out']/eta)
                        self.assertAlmostEqual(o['V_out_equiv'], p['V_out']/eta)
                        self.assertAlmostEqual(o['R_equiv'], o['R']/eta)
                        self.assertLess(abs(np.mean(w['i_c']))/o['I_out'], .0001)
                        self.assertLess(abs(p['V_in']*np.mean(w['i_in'])/o['P_in_est']-1), .0001)
                        self.assertAlmostEqual(np.mean(w['vout']), p['V_out'], places=10)
                        self.assertGreaterEqual(o['D'], 0)
                        self.assertLessEqual(o['D']+o['Dp'], 1+1e-12)
                        if light:
                            self.assertEqual(o['mode'], 'BCM' if topo=='QR-FLYBACK' else 'DCM')
                        elif topo != 'QR-FLYBACK':
                            self.assertEqual(o['mode'], 'CCM')

    def test_assumption_changes_waveforms_and_loop(self):
        for topo in TOPOLOGIES:
            with self.subTest(topo=topo):
                a=spec(topo, 1.); b=spec(topo, .85)
                oa=compute_operating_point(a); ob=compute_operating_point(b)
                self.assertNotAlmostEqual(oa['D'], ob['D'])
                self.assertNotAlmostEqual(oa['dI_L'], ob['dI_L'])
                ga, pa=build_loop_models(a, oa); gb, pb=build_loop_models(b, ob)
                self.assertAlmostEqual(pb.D_actual, ob['D'])
                self.assertAlmostEqual(pb.V_out, ob['V_out_equiv'])
                self.assertFalse(np.isclose(ga[0](2j*np.pi*1000), gb[0](2j*np.pi*1000)))

    def test_loss_ledger_and_no_overwrite_or_budget_double_count(self):
        for topo in TOPOLOGIES:
            with self.subTest(topo=topo):
                p=spec(topo); saved=copy.deepcopy(p); r=compute_design(p)
                self.assertEqual(p, saved)
                self.assertEqual(r['eta_guess'], .93)
                total=sum(r[k] for k in ('P_semi','P_mag','P_cap','P_cap_in','P_sense','P_rcd','P_din','P_dout','P_clamp'))
                self.assertAlmostEqual(r['P_total'], total)
                self.assertAlmostEqual(r['eta'], p['P_out']/(p['P_out']+total))
                self.assertAlmostEqual(r['eta_delta'], r['eta']-.93)
                self.assertAlmostEqual(r['P_in_delta'], r['P_in']-p['P_out']/.93)
                check=next(c for c in check_catalog(p,r) if c['id']=='efficiency_preset_gap')
                self.assertAlmostEqual(check['value'], abs(r['eta_delta'])*100)

    def test_direct_entries_and_qr_compatibility(self):
        for topo, entry in [('BUCK',compute_nonllc_op),('QR-FLYBACK',compute_qrflyback_op),('ACF-FORWARD',compute_forward_op)]:
            p=spec(topo)
            self.assertEqual(entry(p), compute_operating_point(p))
        p=spec('QR-FLYBACK', .8); r=recompute_qr_eta(p, max_iter=9)
        self.assertEqual(r['op'], compute_operating_point(p))
        self.assertEqual(p['eta_guess'], .8)
        _, _, points=efficiency_curve(p, load_fracs=[.25, .5, 1])
        self.assertTrue(all(r['op']['eta_guess']==.8 for r in points))

    def test_api_and_tuning_share_preset(self):
        p=spec('BUCK', .85); r=run_design(p)
        self.assertTrue(r['ok'], r.get('error'))
        self.assertEqual(r['losses']['eta_guess'], .85)
        tuned=autotune_loop(p, 1500, 60)
        verified=loop_margins_for(dict(p,**tuned['spec_updates'],fc_target=1500))
        self.assertAlmostEqual(verified['fc'], tuned['achieved']['fc'])
        self.assertAlmostEqual(verified['pm'], 60, delta=.05)

    def test_validation_and_old_configuration_fallback(self):
        for eta in (0, -.1, 1.001, float('nan'), float('inf')):
            for topo in TOPOLOGIES:
                with self.subTest(topo=topo, eta=eta), self.assertRaises(ValueError):
                    compute_operating_point(spec(topo, eta))
        for topo in ('BUCK','ACF-FORWARD'):
            with self.assertRaises(ValueError): compute_operating_point(spec(topo, .4))
        p=spec('FLYBACK'); p.pop('eta_guess')
        self.assertEqual(compute_operating_point(p)['eta_guess'], DEFAULT_PARAMS['eta_guess'])
        self.assertEqual(decode_config(read_default_config())['eta_guess'], .93)

    def test_rhp_zero_matches_shared_plant(self):
        import control as ct
        for topo in ('BOOST','BUCK-BOOST','FLYBACK'):
            for mode in ('Voltage Mode','Peak Current Mode'):
                with self.subTest(topo=topo, mode=mode):
                    p=dict(spec(topo),control_mode=mode); o=compute_operating_point(p)
                    (g,_,_),_=build_loop_models(p,o)
                    zeros=[z.real/(2*np.pi) for z in ct.zeros(g) if z.real>0 and abs(z.imag)<1e-4]
                    self.assertTrue(any(np.isclose(z,o['rhp_zero'],rtol=1e-5) for z in zeros), (zeros,o['rhp_zero']))

    def test_native_math_preset_symbols(self):
        from word_math import math_nodes, element
        from docx.oxml.ns import nsmap
        expr=element('oMath',*math_nodes('Pin,est=Po/η₀；ηfinal=Po/(Po+Ploss)'))
        subs=[''.join(x.xpath('.//m:t/text()',namespaces=nsmap)) for x in expr.xpath('.//m:sub',namespaces=nsmap)]
        self.assertIn('in,est',subs)
        self.assertIn('final',subs)


if __name__=='__main__': unittest.main(verbosity=2)
