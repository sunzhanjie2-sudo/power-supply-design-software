"""QR export, actual-event metrology and UI field applicability contracts."""
import copy
import json
from pathlib import Path
import sys
import unittest
import numpy as np
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
from design_engine.specification import load_spec
from design_engine.service import calculate_parameters
from spice_export import project_files,normalize_settings
from qr_spice_settings import applicable_keys,l6565_preset
from qr_spice_analysis import cycle_quality
from controller_logic import qr_definition


class QRChecks(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.p=load_spec(json.loads((ROOT/'examples/90W_QR_L6565_300V_TUNED.json').read_text(encoding='utf-8')))
        cls.bundle=calculate_parameters(cls.p,analysis='endpoints',include_loop=True,include_cross_regulation=False).runtime_bundle()
        cls.files=project_files(cls.p,bundle=cls.bundle)

    def test_example_and_physical_contract(self):
        p=self.p;f=self.files;m=json.loads(f['manifest.json'])
        self.assertEqual((p['V_in_min'],p['V_in_max'],p['P_out']),(300,300,92))
        self.assertEqual((p['KP'],p['fz1']),(100,1000))
        self.assertEqual((m['resolved_controller']['KP'],m['resolved_controller']['FZ1']),(200,10))
        self.assertEqual(m['qr']['design_coss_f'],0)
        self.assertAlmostEqual(m['resolved_controller']['Q_COSS'],470e-12)
        self.assertNotEqual(m['resolved_controller']['FSW'],p['f_sw'])
        self.assertGreater(m['resolved_controller']['ZDELAY'],0)
        stage=f['power_stage.inc'].decode();self.assertIn('GQR_CTRL',stage);self.assertIn('GQR_ZCD',stage)
        self.assertNotIn('GFLY_CTRL2',stage)
        self.assertIn(b'SYMBOL GQR_CTRL',f['Flyback.asc'])
        self.assertIn('Flyback.plt',f)
        self.assertEqual(f['GenericQR_L6565.lib'],(ROOT/'resources/spice/GenericQR_L6565.lib').read_bytes())

    def test_explicit_limits_and_parameter_validation(self):
        for change in ({'feedback_mode':'PSR-MP6005'},{'control_mode':'Voltage Mode'},
                       {'outputs':[{'V_out':60,'P_out':92}]}):
            with self.assertRaises(ValueError):project_files(dict(self.p,**change),bundle=self.bundle)
        for cfg in ({'qr_zcd_trigger_v':2.2},{'qr_uvlo_on_v':9},{'qr_zcd_delay_ns':-.5}):
            with self.assertRaises(ValueError):normalize_settings(cfg)
        q=copy.deepcopy(self.p);q['spice_config']['qr_cds_pf']=0
        with self.assertRaisesRegex(ValueError,'谐振电容'):project_files(q,bundle=self.bundle)

    def test_diagram_and_forms_do_not_expose_wrong_controller(self):
        keys=applicable_keys('QR-FLYBACK');d=qr_definition()
        self.assertEqual(set(d['parameters']),set(keys))
        self.assertNotIn('frequency_hz',keys);self.assertNotIn('hiccup_off_ms',keys)
        self.assertIn('qr_zcd_r',keys);self.assertNotIn('qr_zcd_r',applicable_keys('FLYBACK'))
        for n in d['nodes']:
            self.assertTrue(set(n['values'])<=set(keys),n)
        self.assertIn('st.com',d['source'])

    def test_actual_edges_are_independent_of_reference_clock(self):
        class Raw:
            time=np.arange(0,.003,20e-9)
            def trace(self,name):
                phase=np.mod(self.time,23.7e-6)
                return {'v(gate)':np.where(phase<6e-6,10.,0.),'v(sense)':np.zeros(len(phase)),
                    'i(lp)':np.where(phase<6e-6,phase/6e-6*2.4,0.),
                    'v(drain)':np.where(phase<6e-6,0.,180.)}[name]
        raw=Raw();a=cycle_quality(raw,100000,.001,.0029);b=cycle_quality(raw,50000,.001,.0029)
        self.assertTrue(a['stable']);self.assertAlmostEqual(a['frequency_mean_hz'],1/23.7e-6,delta=50)
        self.assertAlmostEqual(a['frequency_mean_hz'],b['frequency_mean_hz'])
        self.assertAlmostEqual(a['turnon_vds_mean_v'],180)


if __name__=='__main__':unittest.main()
