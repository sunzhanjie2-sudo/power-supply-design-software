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
        # This contract deliberately exercises the historical design-Coss=0,
        # explicit 470pF controller override and missing-cap fallback. The
        # purchasing example now uses a real 99pF device and must not silently
        # redefine what the missing-cap/override tests are checking.
        cls.p['Coss']=0.
        cls.p['spice_config']['qr_cds_pf']=470.
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

    def test_qr_saves_only_its_actual_internal_probes(self):
        import re
        analysis=self.files['analysis.inc'].decode('ascii')
        probes=set(re.findall(r'V\(xu_ctrl:([^)]*)\)',analysis,re.I))
        self.assertEqual(probes,{'filtered','trip'})
        lib=self.files['GenericQR_L6565.lib'].decode('ascii')
        for name in probes:
            self.assertRegex(lib,rf'(?m)^\w+ {name} ')
        self.assertIn('.save V(zcd) V(vcc)',analysis)

    def test_qr_latched_cs_evidence_is_recognized(self):
        from spice_analysis import protection_stop
        class Raw:
            time=np.arange(6)*1e-6
            names={'v(fault)': [0,0,0,1,1,1], 'v(xu_ctrl:trip)': [0,0,1,1,0,0],
                   'v(xu_ctrl:filtered)': [0,0,2.1,2.,0,0], 'i(lp)': [0,2,3,2,0,0]}
            def trace(self,name):return np.array(self.names[name])
        evidence=protection_stop(Raw(),{'fault_max':1},50e3)
        self.assertIn('QR 异常 CS',evidence['cause'])
        self.assertEqual(evidence['filtered_cs_peak_v'],2.1)

    def test_startup_gate_winding_evidence_excludes_steady_state_and_coarse_raw(self):
        from qr_spice_analysis import startup_gate_current
        class Raw:
            def __init__(self, spacing):
                self.time=np.arange(0,30e-6,spacing)
            def trace(self,name):
                t=self.time
                traces={'v(ss)':np.minimum(t/15e-6,1), 'v(sense)':np.zeros_like(t),
                        'v(gate)':np.where(((t%10e-6)>=2e-6)&((t%10e-6)<4e-6),10,0),
                        'i(ls1)':np.where(t<9e-6,1.,np.where(t<18e-6,3.,90.))}
                return traces[name]
        observed=startup_gate_current(Raw(10e-9),28e-6,10)
        self.assertEqual((observed['observed_edges'],observed['total_edges']),(2,2))
        self.assertAlmostEqual(observed['max_gate_rise_s'],12e-6,delta=20e-9)
        self.assertEqual(observed['max_pre_current_a'],3.)
        self.assertFalse(startup_gate_current(Raw(2e-6),28e-6,10)['available'])
        class VdsOnly:
            time=np.array([0.,1e-6,2e-6,3e-6])
            def trace(self,name):
                return {'v(drain)':np.array([600.,580.,580.,320.]),
                        'v(sense)':np.array([50.,1.,0.,0.])}[name]
        peak=startup_gate_current(VdsOnly(),1e-6,10)
        self.assertFalse(peak['available'])
        self.assertEqual((peak['vds_peak_full_v'],peak['vds_peak_full_s']),(580.,2e-6))

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

    def test_turnoff_slew_is_not_reported_as_qr_valley(self):
        # The conducted switch holds its drain low briefly at the first
        # turn-off edge. The free off-state voltage later bottoms at 175 V.
        class Raw:
            time=np.arange(0.,340e-6,5e-9)
            def trace(self,name):
                phase=np.mod(self.time,20e-6)
                on=phase<6e-6
                return {'v(gate)':np.where(on,10.,0.),
                    'v(sense)':np.zeros_like(phase),'i(lp)':np.where(on,1.,0.),
                    'v(drain)':np.where(phase<6.08e-6,1.,np.where(phase<19.8e-6,300.,175.))}[name]
        raw=Raw()
        for reference in (40e3,100e3):
            quality=cycle_quality(raw,reference,5e-6,335e-6)
            self.assertEqual(quality['valley_vds_mean_v'],175.)
            self.assertEqual(quality['turnon_vds_mean_v'],175.)


if __name__=='__main__':unittest.main()
