"""Optional real-LTspice check of event startup, fault latch and UVLO reset."""
from pathlib import Path
import shutil
import sys
import tempfile
import unittest
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
from spice_runtime import find_ltspice,_run,read_log


class QRControllerBench(unittest.TestCase):
    @unittest.skipUnless(find_ltspice(),'LTspice is not installed')
    def test_fault_stays_latched_until_uvlo_and_restarts(self):
        with tempfile.TemporaryDirectory(prefix='qr-controller-test-') as d:
            d=Path(d)
            shutil.copy2(ROOT/'tests/fixtures/qr_controller_bench.cir',d/'Flyback.cir')
            for name in ('GenericFlybackPWM.lib','GenericQR_L6565.lib'):
                shutil.copy2(ROOT/'resources/spice'/name,d/name)
            _run(find_ltspice(),d,60,lambda:False)
            m,_,errors,_=read_log(d/'Flyback.log');self.assertFalse(errors)
            self.assertGreater(m['active_gate'],9)
            self.assertGreater(m['fault_latched'],.9)
            self.assertLess(m['gate_locked'],.1)
            self.assertLess(m['fault_reset'],.1)
            self.assertGreater(m['gate_restart'],9)


if __name__=='__main__':unittest.main()
