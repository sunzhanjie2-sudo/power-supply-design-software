"""Physical invariants for the supplemental flyback comparison."""
import copy
import json
from pathlib import Path
import sys
import unittest
import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from runtime_resources import configure_numeric_threads
configure_numeric_threads()
from capacitor_banks import bank
from design_engine.service import calculate
from flyback_cap_boundary import predict, _positive_pulse_fraction


class CapacitorBoundaryChecks(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        design = json.loads((ROOT/'examples/40W_CCM_3OUT_FLYBACK.json').read_text(encoding='utf-8'))
        run = calculate(design, analysis='endpoints', include_loop=False, include_cross_regulation=False)
        case = run.runtime_bundle()['cases'][0]
        cls.parameters = case['p']
        cls.op = case['result']['op']

    def test_feedback_charge_balance_and_physical_split(self):
        original = predict(self.parameters, self.op)
        self.assertTrue(original['available'], original)
        outputs = original['outputs']
        self.assertAlmostEqual(outputs[0]['port_v'], self.op['V_out'], places=5)
        for row, resistance in zip(outputs, self.op['coupled_model']['load_resistances']):
            self.assertAlmostEqual(row['average_a'], row['port_v']/resistance, places=6)
            self.assertLessEqual(row['average_a'], row['rms_a'])
            self.assertLessEqual(row['rms_a'], row['peak_a'])

        # Two half-size C branches with twice ESR have exactly the impedance
        # of the original part. A correct branch-resolved solver is invariant.
        equivalent = copy.deepcopy(self.op)
        for rail in equivalent['outputs']:
            parts = bank(rail)
            first = parts[0]
            half = dict(first, C=first['C']/2, ESR=first['ESR']*2)
            rail['output_capacitors'] = [half.copy(), half.copy(), *parts[1:]]
        split = predict(self.parameters,equivalent)
        self.assertTrue(split['available'], split)
        for a,b in zip(outputs,split['outputs']):
            np.testing.assert_allclose(list(a.values()),list(b.values()),rtol=1e-6,atol=1e-7)

    def test_pulse_width_uses_interpolated_crossings(self):
        self.assertAlmostEqual(_positive_pulse_fraction([0,1,3],[0,1,0]),.95)
        self.assertIsNone(_positive_pulse_fraction([0,1],[0,0]))

if __name__=='__main__':
    unittest.main()
