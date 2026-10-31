"""Physical regression checks for the active-clamp forward model."""
import sys
import unittest
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from power_stage import DEFAULT_PARAMS, compute_operating_point
from waveforms import make_waveforms
from loss_model import compute_design
from design_api import run_design, autotune_loop, load_transient
from cli import report_markdown


class ForwardChecks(unittest.TestCase):
    def setUp(self):
        self.p = dict(DEFAULT_PARAMS, topology='ACF-FORWARD', V_in=30, V_out=30,
                      P_out=40, f_sw=250e3, N=.5, L=68e-6,
                      Np=6, Ns=12, core_choice='PQ20-20')

    def test_volt_seconds_and_conversion_ratio(self):
        o = compute_operating_point(self.p)
        self.assertEqual(o['mode'], 'CCM')
        self.assertAlmostEqual(o['D']*self.p['V_in']/self.p['N'], 30/self.p['eta_guess'])
        self.assertAlmostEqual(30*o['D']-o['V_reset']*(1-o['D']), 0)
        self.assertAlmostEqual(o['V_clamp'], 30/(1-o['D']))
        self.assertAlmostEqual(o['I_d_avg']+o['I_free_avg'], o['I_out'])

    def test_waveform_energy_and_rms(self):
        o = compute_operating_point(self.p)
        w = make_waveforms(o, n_pts=24000)
        self.assertAlmostEqual(float(np.mean(w['iL'])), o['I_out'], places=4)
        self.assertAlmostEqual(float(np.mean(w['i_c'])), 0, places=4)
        # Input waveform transfers Po plus the preset aggregate loss budget.
        self.assertAlmostEqual(30*float(np.mean(w['i_in'])),
                               40/self.p['eta_guess'], delta=.015)
        for signal, key in [('i_sw','I_sw_rms'),('i_aux','I_aux_rms'),
                            ('i_d','I_d_rms'),('i_free','I_free_rms'),('i_p','I_p_rms')]:
            self.assertAlmostEqual(float(np.sqrt(np.mean(w[signal]**2))),
                                   o[key], delta=5e-4)
        self.assertLess(abs(float(np.mean(w['i_mag']))), 1e-4)

    def test_light_load_dcm(self):
        o = compute_operating_point(dict(self.p, P_out=1))
        w = make_waveforms(o, n_pts=24000)
        self.assertEqual(o['mode'], 'DCM')
        self.assertLess(o['D']+o['Dp'], 1)
        self.assertTrue(np.all(w['iL'] >= 0))
        self.assertAlmostEqual(float(np.mean(w['iL'])), o['I_out'], delta=1e-5)
        self.assertAlmostEqual(30*o['D']-o['V_reset']*(1-o['D']), 0)
        q_positive = float(np.mean(np.maximum(w['i_c'],0)))*o['Ts']
        self.assertAlmostEqual(o['C_min']*.01*o['V_out'],q_positive,delta=1e-11)

    def test_clamp_sizing_and_frequency(self):
        o = compute_operating_point(self.p)
        larger = compute_operating_point(dict(self.p,C_clamp=2*self.p['C_clamp']))
        self.assertAlmostEqual(o['V_clamp_hump']/larger['V_clamp_hump'], 2)
        self.assertAlmostEqual(o['f_clamp']/larger['f_clamp'], np.sqrt(2))
        self.assertAlmostEqual(o['fc_recommended_max'], o['f_clamp_effective']/5)

    def test_two_magnetics_and_loss_balance(self):
        r = compute_design(self.p)
        self.assertTrue(r['mag']['ok'])
        t, L = r['mag']['transformer'], r['mag']['inductor']
        self.assertAlmostEqual(t['B_pk'], t['dB']/2)
        self.assertAlmostEqual(r['P_mag'], t['P_total']+L['P_total'])
        self.assertAlmostEqual(r['P_semi'], sum(r['semi'][k]['P_total']
                              for k in ('switch','diode','auxiliary','freewheel')))
        self.assertEqual(r['P_rcd'], 0)
        self.assertAlmostEqual(r['P_total'], sum(r[k] for k in
            ('P_semi','P_mag','P_cap','P_cap_in','P_sense','P_din','P_dout','P_clamp','P_rcd')))
        self.assertTrue(0 < r['eta'] < 1)

    def test_no_implicit_zvs_loss_credit(self):
        r = compute_design(self.p)
        self.assertGreater(r['semi']['switch']['P_sw_on'], 0)
        self.assertGreater(r['semi']['switch']['P_coss'], 0)
        self.assertGreater(r['semi']['auxiliary']['P_total'], 0)

    def test_api_report_and_tuning(self):
        for mode in ('Voltage Mode','Peak Current Mode'):
            p = dict(self.p,control_mode=mode)
            r = run_design(p)
            self.assertTrue(r['ok'], r.get('error'))
            self.assertIn('auxiliary',r['stress'])
            self.assertIn('freewheel',r['stress'])
            self.assertIn('active_clamp',r)
            self.assertEqual(set(r['magnetics']['devices']), {'inductor','transformer'})
            tuned = autotune_loop(p,3000,60)
            self.assertAlmostEqual(tuned['achieved']['fc'],3000,delta=2)
            self.assertAlmostEqual(tuned['achieved']['pm'],60,delta=.05)
            self.assertTrue(tuned['achieved']['descending_crossovers'])
            markdown = report_markdown(r)
            self.assertIn('有源钳位正激', markdown)
            self.assertIn('transformer:', markdown)

    def test_bandwidth_limit_and_transient_default(self):
        op = compute_operating_point(self.p)
        tuned = autotune_loop(dict(self.p,control_mode='Peak Current Mode'),25000,60)
        self.assertAlmostEqual(tuned['fc_target'],op['fc_recommended_max'])
        self.assertAlmostEqual(tuned['achieved']['fc'],op['fc_recommended_max'],delta=3)
        step = load_transient(self.p,di=.5)
        self.assertAlmostEqual(step['fc'],op['fc_recommended_max'])

    def test_impossible_specs_rejected(self):
        for update in ({'N':1.1},{'forward_d_max':.4},{'Lm_forward':0},
                       {'C_clamp':0},{'forward_dead_time':2e-6},{'V_in':float('nan')},
                       {'ESR_clamp':-.01},{'Rds_aux':-1},{'Coss_aux':float('nan')}):
            with self.subTest(update=update), self.assertRaises(ValueError):
                compute_operating_point(dict(self.p,**update))


if __name__ == '__main__':
    unittest.main(verbosity=2)
