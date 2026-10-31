"""Fast presentation-catalogue tests, without importing Tk or matplotlib."""

import ast
from pathlib import Path
import sys
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from parameter_layout import (FieldSpec, GROUPS, META, SECTION_ORDER,
                              SECTION_TITLES, applicable, visible)


def parameter_specs():
    tree = ast.parse((ROOT / 'main.py').read_text(encoding='utf-8-sig'))
    for node in tree.body:
        if isinstance(node, ast.Assign) and any(
                isinstance(target, ast.Name) and target.id == 'PARAM_SPECS'
                for target in node.targets):
            return ast.literal_eval(node.value)
    raise AssertionError('PARAM_SPECS not found in main.py')


class CatalogueTests(unittest.TestCase):
    def test_every_existing_key_is_grouped_exactly_once(self):
        expected = [key for key, *_rest in parameter_specs()]
        actual = [key for section in SECTION_ORDER
                  for _title, keys in GROUPS[section] for key in keys]
        self.assertEqual(len(actual), len(set(actual)))
        self.assertCountEqual(actual, expected)
        self.assertEqual(set(META), set(expected))
        self.assertEqual(set(GROUPS), set(SECTION_ORDER))
        self.assertEqual(set(SECTION_TITLES), set(SECTION_ORDER))

    def test_contract_is_plain_frozen_metadata(self):
        self.assertIsInstance(SECTION_ORDER, tuple)
        for key, field in META.items():
            self.assertIsInstance(field, FieldSpec, key)
            self.assertTrue(field.label, key)
            self.assertTrue(field.symbol, key)
            self.assertGreater(field.display_factor, 0, key)
            self.assertIsInstance(field.topologies, tuple, key)

    def test_real_units_and_percentage_conversion(self):
        for key in ('Rds_on', 'Rg', 'Rg_drive', 'Rs_on', 'Rs_off', 'Rc', 'Rcin2'):
            self.assertEqual(META[key].unit, 'Ω', key)
        for key in ('Qg', 'Qgs', 'Qgd', 'Qg_th', 'Qrr'):
            self.assertEqual(META[key].unit, 'C', key)
        for key in ('L', 'Lm_forward', 'ESL', 'ESLin2'):
            self.assertEqual(META[key].unit, 'H', key)
        for key in ('C_out', 'Cin1', 'Coss', 'C_clamp'):
            self.assertEqual(META[key].unit, 'F', key)
        for key in ('MLT', 'd_wire_p', 'd_wire_s'):
            self.assertEqual(META[key].unit, 'm', key)
        for key in ('eta_guess', 'ripple_target', 'forward_d_max', 'ring_margin'):
            self.assertEqual((META[key].unit, META[key].display_factor), ('%', 100), key)
        self.assertEqual(META['eta_guess'].display_factor * .9, 90)
        self.assertEqual(META['temp_rise_limit'].unit, 'K')

    def test_isolated_and_forward_fields_are_topology_specific(self):
        for topology in ('BUCK', 'BOOST', 'BUCK-BOOST'):
            for key in ('N', 'Np', 'Ns', 'd_wire_p', 'd_wire_s', 'n_strand_s'):
                self.assertFalse(applicable(key, topology, 'Peak Current Mode'), (key, topology))
                self.assertFalse(visible(key, topology, 'Peak Current Mode', True, {}))
            self.assertTrue(applicable('MLT', topology, 'Voltage Mode'))
            self.assertTrue(applicable('ring_margin', topology, 'Voltage Mode'))
        for topology in ('FLYBACK', 'QR-FLYBACK', 'ACF-FORWARD'):
            self.assertTrue(applicable('N', topology, 'Peak Current Mode'))
            self.assertTrue(applicable('Np', topology, 'Peak Current Mode'))
        for key in ('Lm_forward', 'C_clamp', 'ESR_clamp', 'forward_d_max',
                    'forward_dead_time', 'Rds_aux', 'Qg_aux', 'Coss_aux'):
            self.assertTrue(applicable(key, 'ACF-FORWARD', 'Voltage Mode'))
            self.assertFalse(applicable(key, 'FLYBACK', 'Peak Current Mode'))

    def test_loss_parameters_are_not_hidden_by_control_mode(self):
        for mode in ('Voltage Mode', 'Peak Current Mode'):
            for key in ('Rs', 'Vm', 'Vth', 'Vgp_on', 'Vgp_off', 'Qg_th', 'Qgs',
                        'Qgd', 'Rg', 'Rg_drive', 'Rs_on', 'Rs_off'):
                self.assertTrue(visible(key, 'FLYBACK', mode, False, {}), (key, mode))
        for key in ('A_sense', 'ma_slope'):
            self.assertFalse(applicable(key, 'FLYBACK', 'Voltage Mode'))
            self.assertTrue(applicable(key, 'FLYBACK', 'Peak Current Mode'))
            self.assertTrue(applicable(key, 'FLYBACK', 'PCM'))

    def test_disabled_optional_banks_stay_hidden_in_advanced_mode(self):
        flags = ('cin2_enable', 'cout2_enable', 'd_in_enable', 'd_out_enable')
        expected = {'cin2_enable': ('Cin2', 'Rcin2', 'ESLin2'),
                    'cout2_enable': ('C_out2', 'Rc2', 'ESL2'),
                    'd_in_enable': ('Vf_din',),
                    'd_out_enable': ('Vf_dout',)}
        self.assertEqual(set(field.enabled_by for field in META.values()
                             if field.enabled_by), set(flags))
        for flag, keys in expected.items():
            for key in keys:
                self.assertEqual(META[key].enabled_by, flag)
                self.assertFalse(visible(key, 'FLYBACK', 'Peak Current Mode', True, {}))
                self.assertFalse(visible(key, 'FLYBACK', 'Peak Current Mode', True, {flag: False}))
                self.assertTrue(visible(key, 'FLYBACK', 'Peak Current Mode', False, {flag: True}))

    def test_advanced_does_not_hide_model_required_gate_data(self):
        for key in ('Vth', 'Vgp_on', 'Vgp_off', 'Qg_th', 'Qgs', 'Qgd', 'Rg',
                    'Vgs', 'Rg_drive', 'Rs_on', 'Rs_off'):
            self.assertTrue(META[key].required, key)
            self.assertFalse(META[key].advanced, key)
        for key in ('Vf', 'rho', 'k_core', 'a_core', 'b_core'):
            self.assertTrue(visible(key, 'FLYBACK', 'Peak Current Mode', False, {}))
            self.assertTrue(visible(key, 'FLYBACK', 'Peak Current Mode', True, {}))

    def test_all_parameters_ignore_legacy_advanced_filter(self):
        flags=dict(cin2_enable=True,cout2_enable=True,d_in_enable=True,d_out_enable=True)
        for topo in ('BUCK','BOOST','BUCK-BOOST','FLYBACK','QR-FLYBACK','ACF-FORWARD'):
            for key in META:
                self.assertFalse(META[key].advanced,key)
                self.assertEqual(visible(key,topo,'Peak Current Mode',False,flags),
                                 visible(key,topo,'Peak Current Mode',True,flags),(topo,key))

    def test_auto_mode_is_only_supported_zero_auto_fields(self):
        actual = {key for key, field in META.items() if field.auto}
        self.assertEqual(actual, {'MLT', 'Np', 'Ns', 'd_wire_p', 'd_wire_s'})


if __name__ == '__main__':
    unittest.main()
