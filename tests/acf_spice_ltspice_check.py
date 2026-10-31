from pathlib import Path
import shutil
import sys
import tempfile
import unittest
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
from spice_runtime import _run,read_log,find_ltspice


class ACFBench(unittest.TestCase):
    @unittest.skipUnless(find_ltspice(),'LTspice not installed')
    def test_no_clock_boundary_retrigger_and_fault_clears_both_gates(self):
        with tempfile.TemporaryDirectory(prefix='acf-timing-') as d:
            d=Path(d);shutil.copy2(ROOT/'tests/fixtures/acf_controller_bench.cir',d/'Flyback.cir')
            for name in ('GenericFlybackPWM.lib','GenericACF_MP6005.lib'):shutil.copy2(ROOT/'resources/spice'/name,d/name)
            _run(find_ltspice(),d,60,lambda:False)
            m,_,errors,_=read_log(d/'Flyback.log');self.assertFalse(errors)
            self.assertEqual(m['overlap_max'],0.)
            self.assertGreater(m['main_active'],9.)
            self.assertLess(m['aux_active'],-9.)
            self.assertGreater(m['fault_latched'],.9)
            self.assertLess(m['main_off'],.1)
            self.assertGreater(m['aux_off'],-.1)


if __name__=='__main__':unittest.main()
