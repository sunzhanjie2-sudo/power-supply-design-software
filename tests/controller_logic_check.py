"""Explanatory UI must match all exported fields and preserve model semantics."""
from pathlib import Path
import sys
import unittest
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from controller_logic import HELP,definition,display_value,state_note
from spice_export import SETTINGS,normalize_settings,mp6005_preset
from design_engine.contracts import json_value


class ControllerLogicChecks(unittest.TestCase):
    def test_all_settings_are_explained_and_scoped(self):
        self.assertEqual(set(HELP),set(SETTINGS))
        d=definition();nodes={n['id']:n for n in d['nodes']}
        self.assertEqual(json_value(d),d)
        for key,(node,purpose,meaning) in HELP.items():
            self.assertIn(node,nodes);self.assertTrue(purpose);self.assertTrue(meaning)
        for key in ('feedback_scale','kp','comp_voltage_max'):
            self.assertEqual(nodes[HELP[key][0]]['scope'],'external')
        self.assertEqual(HELP['diode_cj_pf'][0],'power')
        self.assertEqual(HELP['short_test'][0],'test')
        self.assertEqual(HELP['scp_threshold_v'][0],'protect')

    def test_inactive_controls_and_automatic_values_are_explicit(self):
        generic=normalize_settings();preset=mp6005_preset()
        self.assertIn('当前',state_note('ss_comp_start_v',generic))
        self.assertEqual(state_note('ss_comp_start_v',preset),'')
        self.assertIn('暂不生效',state_note('hiccup_off_ms',generic))
        self.assertEqual(state_note('hiccup_off_ms',preset),'')
        self.assertIn('250',display_value('frequency_hz',generic,{'f_sw':250000}))
        self.assertEqual(display_value('cs_limit',generic),'自动确定')
        self.assertEqual(display_value('kp',generic),'沿用软件')
        self.assertEqual(display_value('frequency_hz',{'frequency_hz':'1e-'}),'编辑中…')
        definition()['nodes'][0]['scope']='chip'
        self.assertEqual(definition()['nodes'][0]['scope'],'external')

if __name__=='__main__':unittest.main()
