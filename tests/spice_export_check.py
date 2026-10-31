"""Electrical mapping and portable export contracts; real LTspice QA is separate."""
import copy
import json
from pathlib import Path
import sys
import tempfile
import unittest
from zipfile import ZipFile

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from runtime_resources import configure_numeric_threads
configure_numeric_threads()
from config_io import read_default_config
from design_engine.specification import load_spec
from design_engine.service import calculate
from spice_export import project_files, export_project, normalize_settings,mp6005_preset


class SpiceExportChecks(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.p=load_spec(read_default_config())
        cls.bundle=calculate(read_default_config(),analysis='endpoints',include_loop=False,include_cross_regulation=False).runtime_bundle()

    def test_default_is_closed_loop_and_portable(self):
        original=copy.deepcopy(self.p)
        files=project_files(self.p,bundle=self.bundle)
        self.assertEqual(self.p,original)
        text=files['power_stage.inc'].decode('ascii')
        self.assertIn('XU_CTRL fb sense en vcc gate comp ramp ss fault 0 GFLY_CTRL2',text)
        self.assertIn('LP vin_bus drain',text)
        self.assertIn('LS1 sgnd rect1',text)
        self.assertIn('XQ1 drain gate sense GPWR_MOS',text)
        self.assertIn('XD_SN1 drain clamp GPWR_DIODE',text)
        self.assertIn('XC_O1 cap1 sgnd GPWR_CAP',text)
        self.assertIn('ESL={C_O1_ESL}',text)
        self.assertIn('.param C_O1_ESL=0',files['design_params.inc'].decode())
        self.assertIn('SYMBOL GFLY_CTRL2',files['Flyback.asc'].decode())
        self.assertIn('SYMATTR InstName LS1',files['Flyback.asc'].decode())
        self.assertNotIn('.include power_stage.inc',files['Flyback.asc'].decode())
        self.assertNotIn('Vg n_gate',text)
        for name in ('Flyback.cir','design_params.inc','power_stage.inc','analysis.inc','GenericFlybackPWM.lib'):
            self.assertNotIn('E:\\',files[name].decode('ascii'))
            self.assertNotIn('µ',files[name].decode('ascii'))
        manifest=json.loads(files['manifest.json'])
        self.assertAlmostEqual(manifest['coupling']['k'][0][1]**2,self.p['K'])
        self.assertGreater(manifest['hardware']['R_dc_p'],0)
        self.assertIn('MODEL_GUIDE.md',files)

    def test_same_voltage_once_and_range_steps(self):
        files=project_files(self.p,bundle=self.bundle)
        self.assertNotIn('.step',files['design_params.inc'].decode())
        p=dict(self.p,V_in_min=24.,V_in_max=36.)
        files=project_files(p)
        self.assertIn('.step param VIN list 24 36',files['design_params.inc'].decode())

    def test_feedback_gain_and_override_are_explicit(self):
        p=dict(self.p,spice_config=dict(feedback_scale=.1,kp=50,cs_limit=.2,slope=1234))
        m=json.loads(project_files(p,bundle=self.bundle)['manifest.json'])
        self.assertEqual(m['resolved_controller']['KP'],500)
        self.assertAlmostEqual(m['resolved_controller']['VSET'],3.07)
        self.assertEqual(m['resolved_controller']['CS_LIM'],.2)
        self.assertEqual(m['resolved_controller']['SLOPE'],1234)

    def test_unsupported_models_reject(self):
        for change in (dict(topology='BUCK-BOOST'),dict(feedback_mode='PSR-MP6005')):
            with self.assertRaisesRegex(ValueError,'支持'):
                project_files(dict(self.p,**change),bundle=self.bundle)

    def test_bad_settings_reject_without_partial_zip(self):
        for cfg in (dict(step_ms=20),dict(kp=float('nan')),dict(slope=-.5),dict(stop_ms=True),dict(custom_spice='.include secret')):
            with self.assertRaises(ValueError):normalize_settings(cfg)
        with tempfile.TemporaryDirectory() as folder:
            path=Path(folder)/'project.zip'
            path.write_bytes(b'old-complete-export')
            with self.assertRaises(ValueError):export_project(path,dict(self.p,spice_config=dict(kp=float('inf'))),bundle=self.bundle)
            self.assertEqual(path.read_bytes(),b'old-complete-export')

    def test_multi_output_uses_selected_feedback_and_matrix(self):
        raw=json.loads((ROOT/'examples/3_OUTPUT_COUPLED_FLYBACK.json').read_text(encoding='utf-8'))
        p=load_spec(raw)
        p['feedback_output']=2
        files=project_files(p)
        text=files['power_stage.inc'].decode()
        self.assertIn('XFBSEL cap1 cap2 cap3 sgnd sgnd sgnd sgnd fb 0 GPWR_FEEDBACK',text)
        self.assertIn('.param FB_SELECT=2',files['design_params.inc'].decode())
        self.assertIn('LS3 sgnd rect3',text)
        self.assertEqual(sum(line.startswith('K_') for line in files['coupling.inc'].decode().splitlines()),6)
        self.assertIn('BLOAD3',text)
        self.assertNotIn('Lleak',text)
        m=json.loads(files['manifest.json'])
        self.assertEqual(m['coupling']['source'],'user-pairwise-kij')

    def test_export_roundtrip(self):
        with tempfile.TemporaryDirectory() as folder:
            path=Path(folder)/'中文目录'/'工程.zip'
            export_project(path,self.p,bundle=self.bundle)
            with ZipFile(path) as archive:
                self.assertIsNone(archive.testzip())
                self.assertIn('GenericFlybackPWM.lib',archive.namelist())
                self.assertNotIn('.raw',' '.join(archive.namelist()))
            self.assertEqual(list(path.parent.glob('*.tmp')),[])

    def test_zero_cap_parasitics_do_not_leave_floating_nodes(self):
        p=dict(self.p,Rc=0.,ESL=0.,cout2_enable=False,Rcin1=0.,ESLin1=0.,cin2_enable=False)
        text=project_files(p)['power_stage.inc'].decode()
        self.assertIn('XC_O1 cap1 sgnd GPWR_CAP',text)
        self.assertIn('XC_IN1 vin_bus 0 GPWR_CAP',text)
        self.assertNotIn('C_O1_l',text)
        self.assertNotIn('C_O1_r',text)

    def test_detailed_esl_is_explicit_and_not_silently_removed(self):
        files=project_files(dict(self.p,spice_config=dict(include_cap_esl=1)),bundle=self.bundle)
        self.assertNotIn('.param C_O1_ESL=0\n',files['design_params.inc'].decode())
        self.assertIn('Lser={ESL}',files['GenericFlybackPWM.lib'].decode())

    def test_mp6005_preset_and_modes(self):
        cfg=mp6005_preset()
        self.assertEqual((cfg['frequency_hz'],cfg['cs_limit'],cfg['soft_start_mode']),(250000,.16,2))
        self.assertEqual((cfg['olp_ms'],cfg['ocp_hold_us'],cfg['hiccup_off_ms']),(4.8,50,340))
        files=project_files(dict(self.p,spice_config=cfg),bundle=self.bundle)
        m=json.loads(files['manifest.json'])['resolved_controller']
        self.assertEqual((m['SCP'],m['COFF'],m['SSCLO'],m['SSCHI']),(.3,1.5,1.5,3.5))
        self.assertAlmostEqual(m['TSS'],.0047)
        self.assertAlmostEqual(m['TOFF'],.34)
        for bad in ({'soft_start_mode':.5},{'short_mode':3},{'short_mode':1,'cs_limit':.4}):
            with self.assertRaises(ValueError):normalize_settings(bad)


if __name__=='__main__':unittest.main()
