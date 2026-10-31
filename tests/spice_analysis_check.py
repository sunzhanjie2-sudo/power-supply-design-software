"""Meaningful signal/coverage checks, separate from long real-LTspice QA."""
import sys
from pathlib import Path
import math
import tempfile
import unittest
import numpy as np
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
from spice_analysis import cycle_quality,statistics,FrequencyRaw,loop_metrics
from spice_studies import corner_plan,prepare_fra


class AnalysisChecks(unittest.TestCase):
    def test_period_two_is_not_passed_by_constant_output_voltage(self):
        class Raw:
            time=np.linspace(0,80,80001)
            def trace(self,key):
                phase=np.mod(self.time,1);number=np.floor(self.time).astype(int)
                duty=np.where(number%2,.7,.2) if self.alternating else .45
                high=phase<duty
                return np.where(high,10,0) if key=='v(gate)' else np.zeros_like(phase) if key=='v(sense)' else np.where(high,phase,0)
        raw=Raw();raw.alternating=True
        result=cycle_quality(raw,1,0,79)
        self.assertFalse(result['stable']);self.assertEqual(result['reason'],'周期二大小波')
        raw.alternating=False;self.assertTrue(cycle_quality(raw,1,0,79)['stable'])

    def test_integrals_use_time_not_clustered_sample_counts(self):
        time=np.r_[np.linspace(0,.1,1000),.5,1.];values=time
        result=statistics(time,values,0,1)
        self.assertAlmostEqual(result['mean'],.5,12)
        self.assertGreater(abs(np.mean(values)-.5),.4)

    def test_fra_margins_and_missing_phase_crossing(self):
        f=np.geomspace(10,1e5,2000);gain=10/(1+1j*f/1000)
        result=loop_metrics(f,gain)
        self.assertLess(abs(result['fc']/(1000*math.sqrt(99))-1),1e-4)
        self.assertAlmostEqual(result['pm'],180-math.degrees(math.atan(math.sqrt(99))),places=3)
        self.assertIsNone(result['gm_db'])

    def test_complex_reader_refuses_partial_or_decreasing_frequency(self):
        with tempfile.TemporaryDirectory() as td:
            path=Path(td)/'fra.raw'
            header='Title: FRA\nFlags: complex forward\nNo. Variables: 2\nNo. Points: 2\nVariables:\n0 frequency frequency\n1 gain_1 voltage\nBinary:\n'.encode('utf-16-le')
            values=np.array([[100,1+2j],[200,3+4j]],dtype='<c16')
            path.write_bytes(header+values.tobytes());self.assertEqual(FrequencyRaw(path).traces['gain_1'].tolist(),[1+2j,3+4j])
            values[1,0]=100
            path.write_bytes(header+values.tobytes())
            with self.assertRaisesRegex(ValueError,'非递增'):FrequencyRaw(path)
            values[1,0]=200;values[1,1]=complex(float('inf'),0)
            path.write_bytes(header+values.tobytes())
            with self.assertRaisesRegex(ValueError,'无效'):FrequencyRaw(path)
            path.write_bytes(path.read_bytes()[:-1])
            with self.assertRaisesRegex(ValueError,'不完整'):FrequencyRaw(path)

    def test_half_amplitude_uses_only_three_native_octave_points(self):
        from spice_export import normalize_settings
        files={'design_params.inc':b'.param TLOAD=1\n.param LOAD_AFTER=1\n',
            'power_stage.inc':b'XFBSEL out1 sgnd fb 0 GPWR_FEEDBACK\n'}
        meta={'resolved_controller':dict(FSW=250000,VSET=30,FB_SELECT=1)}
        prepared,definition=prepare_fra(files,meta,normalize_settings(),frequencies=[1500,3000,6000],amplitude_factor=.5)
        stage=prepared['power_stage.inc'].decode()
        self.assertIn('fstart=1500 fend=6000 oct=1',stage)
        self.assertIn('nmax=1',stage);self.assertNotIn('flist',stage)
        self.assertIn('fb_return fb',stage);self.assertIn('.fra ',prepared['analysis.inc'].decode())

    def test_cross_load_coverage_is_explicit(self):
        rails=[dict(P_out=10,P_out_min=1) for _ in range(3)]
        cases,scope=corner_plan(rails,0);self.assertEqual(len(cases),8)
        self.assertIn((1,10,10),cases);self.assertIn((10,1,10),cases);self.assertIn((10,10,1),cases)
        six=rails*2;cases,scope=corner_plan(six,0);self.assertEqual(len(cases),14);self.assertIn('非完整',scope)
        self.assertEqual(len(corner_plan(six,1)[0]),64)


if __name__=='__main__':unittest.main()
