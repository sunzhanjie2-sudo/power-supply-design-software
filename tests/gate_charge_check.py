"""MOS gate-charge time regression against the supplied spreadsheet.

The source workbook remains unchanged. Its F26 references empty H15;
the user-approved calculation uses F15 (the internal MOS gate resistance).
"""
import math
from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from semiconductor import mosfet_loss
from power_stage import DEFAULT_PARAMS
from loss_model import compute_design
from word_math import math_nodes


OP = dict(topology='BUCK', f_sw=20e3, I_L_min=10., I_L_pk=10.)
DEV = dict(Rds_on=.0032, Coss=200e-12, Qg=17e-9, Vgs=10., Vth=1.3,
           Vgp_on=2.2, Vgp_off=2.2, Qg_th=1.6e-9, Qgs=3.1e-9,
           Qgd=2.3e-9, Rg_drive=0., Rs_on=100., Rs_off=100., Rg=1.1,
           k_sw=.1666667)
STRESS = dict(I_rms=10.*math.sqrt(.5), V_max=15.)


def loss(dev=None, op=None):
    return mosfet_loss(op or OP, dev or DEV, STRESS)


class GateChargeChecks(unittest.TestCase):
    def test_spreadsheet_times(self):
        # Cached F22:F28 values, with F26 corrected from H15 to F15.
        expected_ns = dict(t1=17.328486162975533, t2=18.06709320872572,
                           t3=29.811538461538458, t6=105.69545454545454,
                           t7=88.64668665860727, t8=373.29230769230765)
        actual = loss()
        for key, expected in expected_ns.items():
            with self.subTest(time=key):
                self.assertAlmostEqual(actual[key]*1e9, expected, places=10)

    def test_spreadsheet_losses_and_distinct_total(self):
        actual = loss()
        self.assertAlmostEqual(actual['Ptr'], .023939320622995256, places=14)
        self.assertAlmostEqual(actual['Ptf'], .09717109003624502, places=14)
        self.assertAlmostEqual(actual['P_cond'], .16, places=14)
        self.assertAlmostEqual(actual['Ptr']+actual['Ptf'], .12111041065924028, places=14)
        # The app retains separately reported Coss and full gate-drive loss;
        # spreadsheet F32 contains only conduction + switching overlap loss.
        self.assertAlmostEqual(actual['P_total'],
                               .16+.12111041065924028+actual['P_coss']+actual['P_gate'], places=14)

    def test_turn_on_and_turn_off_resistances_are_independent(self):
        actual = loss(dict(DEV, Rs_on=49.45))  # Ron halves; Roff unchanged.
        baseline = loss()
        for key in ('t1', 't2', 't3', 'Ptr'):
            self.assertAlmostEqual(actual[key], baseline[key]/2, delta=1e-18)
        for key in ('t6', 't7', 't8', 'Ptf'):
            self.assertEqual(actual[key], baseline[key])
        actual = loss(dict(DEV, Rs_off=49.45))
        for key in ('t6', 't7', 't8', 'Ptf'):
            self.assertAlmostEqual(actual[key], baseline[key]/2, delta=1e-18)

    def test_charge_and_frequency_units(self):
        baseline = loss()
        actual = loss(dict(DEV, Qg_th=3.2e-9, Qgs=6.2e-9, Qgd=4.6e-9))
        for key in ('t1', 't2', 't3', 't6', 't7', 't8'):
            self.assertAlmostEqual(actual[key], 2*baseline[key], delta=1e-18)
        actual = loss(op=dict(OP, f_sw=40e3))
        for key in ('t1', 't2', 't3', 't6', 't7', 't8'):
            self.assertEqual(actual[key], baseline[key])
        for key in ('Ptr', 'Ptf', 'P_gate', 'P_coss'):
            self.assertEqual(actual[key], 2*baseline[key])

    def test_turn_off_plateau_is_independent(self):
        actual = loss(dict(DEV, Vgp_off=3.5))
        baseline = loss()
        for key in ('t1', 't2', 't3'):
            self.assertEqual(actual[key], baseline[key])
        roff = DEV['Rg_drive']+DEV['Rs_off']+DEV['Rg']
        self.assertAlmostEqual(actual['t6'], DEV['Qgd']*roff/3.5, places=18)
        self.assertAlmostEqual(actual['t7'],
                               -roff*(DEV['Qgs']-DEV['Qg_th'])/(3.5-DEV['Vth'])*math.log(DEV['Vth']/3.5), places=18)

    def test_nearby_voltages_keep_precision(self):
        actual = loss(dict(DEV, Vgp_off=DEV['Vth']*(1+1e-10)))
        limit = (DEV['Rg_drive']+DEV['Rs_off']+DEV['Rg'])*(DEV['Qgs']-DEV['Qg_th'])/DEV['Vth']
        self.assertTrue(math.isclose(actual['t7'], limit, rel_tol=1e-9))
        actual = loss(dict(DEV, Vgs=1e12))
        limit = (DEV['Rg_drive']+DEV['Rs_on']+DEV['Rg'])*DEV['Qg_th']/1e12
        self.assertTrue(math.isclose(actual['t1'], limit, rel_tol=1e-11))

    def test_invalid_parameters_are_not_silently_clamped(self):
        invalid = [dict(Vth=0), dict(Vgs=DEV['Vgp_on']),
                   dict(Vgp_on=DEV['Vth']), dict(Vgp_off=DEV['Vth']),
                   dict(Qgs=DEV['Qg_th']/2), dict(Qg_th=-1e-9),
                   dict(Qgd=-1e-9), dict(Rs_on=-1), dict(Rs_off=-1),
                   dict(Rg=-1), dict(Rg_drive=-1), dict(Vgs=math.nan),
                   dict(Qgs=math.inf)]
        for change in invalid:
            with self.subTest(change=change), self.assertRaises(ValueError):
                loss(dict(DEV, **change))

    def test_qr_only_suppresses_turn_on_power(self):
        actual = loss(op=dict(OP, topology='QR-FLYBACK'))
        baseline = loss()
        for key in ('t1', 't2', 't3', 't6', 't7', 't8'):
            self.assertEqual(actual[key], baseline[key])
        self.assertEqual(actual['Ptr'], 0.)
        self.assertEqual(actual['P_coss'], 0.)
        self.assertEqual(actual['Ptf'], baseline['Ptf'])

    def test_default_engine_uses_same_time_model(self):
        result = compute_design(dict(DEFAULT_PARAMS))
        direct = mosfet_loss(result['op'], DEFAULT_PARAMS)
        for key in ('t1', 't2', 't3', 't6', 't7', 't8', 'Ptr', 'Ptf'):
            self.assertEqual(result['semi']['switch'][key], direct[key])

    def test_native_word_logarithm(self):
        ns = {'m': 'http://schemas.openxmlformats.org/officeDocument/2006/math'}
        nodes = math_nodes('t₁=−(Qg_th·Ron/Vth)·ln(1−Vth/Vgs)')
        logarithms = [r for node in nodes for r in node.iter('{'+ns['m']+'}r')
                      if r.find('m:t', ns) is not None and r.find('m:t', ns).text == 'ln']
        self.assertEqual(len(logarithms), 1)
        self.assertEqual(logarithms[0].find('m:rPr/m:sty', ns).get('{'+ns['m']+'}val'), 'p')


if __name__ == '__main__':
    unittest.main(verbosity=2)
