"""Physical impedance checks for independent parallel series-RC branches."""
from pathlib import Path
import sys
import unittest
import numpy as np
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
from output_capacitors import build_output_filters


def rail(c1=330e-6,r1=.04,c2=10e-6,r2=1e-4,enabled=True):
    return dict(C_out=c1,Rc=r1,C_out2=c2,Rc2=r2,cout2_enable=enabled)


def response(network,s):
    return network.C@np.linalg.solve(s*np.eye(len(network.A))-network.A,network.B)+network.D


class OutputCapacitorChecks(unittest.TestCase):
    def check_impedance(self,r,load=30.):
        model=build_output_filters([r],[load],[30.7])
        for f in (0.,1.,500.,2000.,4000.,1e5,1e7):
            s=2j*np.pi*f
            y=1/load+s*r['C_out']/(1+s*r['Rc']*r['C_out'])
            if r['cout2_enable']:y+=s*r['C_out2']/(1+s*r['Rc2']*r['C_out2'])
            np.testing.assert_allclose(response(model,s)[0,0],1/y,rtol=2e-9,atol=1e-10)
        self.assertTrue(np.all(np.real(np.linalg.eigvals(model.A))<0))
        return model

    def test_single_capacitor_esr_and_load_are_both_retained(self):
        self.assertEqual(len(self.check_impedance(rail(enabled=False)).A),1)

    def test_dissimilar_parallel_branches_match_exact_impedance(self):
        self.assertEqual(len(self.check_impedance(rail()).A),2)

    def test_equal_parallel_capacitors_match_two_c_and_half_esr(self):
        pair=self.check_impedance(rail(c2=330e-6,r2=.04))
        equivalent=self.check_impedance(rail(c1=660e-6,r1=.02,enabled=False))
        for f in (0,500,4000,1e5):
            np.testing.assert_allclose(response(pair,2j*np.pi*f),response(equivalent,2j*np.pi*f),rtol=1e-10)

    def test_swapping_branches_does_not_change_the_network(self):
        a=self.check_impedance(rail());b=self.check_impedance(rail(c1=10e-6,r1=1e-4,c2=330e-6,r2=.04))
        for f in (0,1000,4000,1e5):
            np.testing.assert_allclose(response(a,2j*np.pi*f),response(b,2j*np.pi*f),rtol=1e-10)

    def test_one_ideal_branch_does_not_erase_other_branch_dynamics(self):
        self.assertEqual(len(self.check_impedance(rail(r2=0)).A),2)

    def test_two_ideal_capacitors_share_one_physical_voltage_state(self):
        self.assertEqual(len(self.check_impedance(rail(r1=0,r2=0)).A),1)

    def test_disabled_branch_is_not_validated_or_added(self):
        self.assertEqual(len(self.check_impedance(rail(c2=-1,r2=float('nan'),enabled=False)).A),1)

    def test_nonphysical_enabled_values_are_rejected(self):
        for r in (rail(r1=-.01),rail(c1=0),rail(r2=float('nan'))):
            with self.assertRaises(ValueError):build_output_filters([r],[30],[30.7])

    def test_output_banks_have_no_accidental_connection_between_rails(self):
        network=build_output_filters([rail(),rail(enabled=False)],[30,100],[30.7,12.7])
        self.assertEqual(network.A.shape,(3,3))
        for f in (0,500,4000):
            value=response(network,2j*np.pi*f)
            np.testing.assert_array_equal([value[0,1],value[1,0]],[0,0])


if __name__=='__main__':unittest.main(verbosity=2)
