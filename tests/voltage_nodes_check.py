"""Independent charge, energy, feedback-node and export-node regressions."""
import copy
import json
from pathlib import Path
import sys
import unittest
import numpy as np
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
from runtime_resources import configure_numeric_threads
configure_numeric_threads()
from power_stage import DEFAULT_PARAMS,compute_operating_point
from isolated_outputs import output_specs
from multi_output_loop import CoupledPeriodMap
from spice_export import project_files


class VoltageNodesChecks(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.p=copy.deepcopy(DEFAULT_PARAMS)
        cls.p.update(Np=6,Ns=12,V_in=20,V_in_min=20,V_in_max=30,feedback_output=1,
            outputs=[dict(V_out=30,P_out=30,Ns=12,d_out_enable=True,Vf_dout=.7),
                     dict(V_out=12,P_out=1,Ns=5,d_out_enable=True,Vf_dout=.4),
                     dict(V_out=5,P_out=2,Ns=2,d_out_enable=False)],
            coupling_config=dict(enabled=True,k=[],dcr=[]))
        cls.op=compute_operating_point(cls.p)

    def test_port_feedback_and_energy_are_distinct_and_balanced(self):
        op=self.op;m=op['coupled_model'];self.assertAlmostEqual(op['V_out'],30)
        self.assertAlmostEqual(op['V_feedback'],30.7)
        self.assertAlmostEqual(op['V_in_bus'],19.3)
        for child,drop,r in zip(op['output_ops'],(.7,.4,0),m['load_resistances']):
            self.assertAlmostEqual(child['V_out_cap']-child['V_out'],drop)
            self.assertAlmostEqual(child['P_out'],child['V_out']**2/r)
            self.assertAlmostEqual(child['I_d_avg'],child['V_out']/r,delta=1e-6)
        losses=sum(m['P_dcr'])+sum(m['P_rectifier'])+sum(m['P_output_blocking'])+m['P_input_blocking']+m['P_mos_conduction']+m['P_sense']+m['P_rcd']
        self.assertAlmostEqual(m['P_in'],m['P_out']+losses,delta=1e-5)

    def test_loop_map_uses_capacitor_states_and_actual_load_current(self):
        period=CoupledPeriodMap(self.p,self.op)
        state,_,_=period.evaluate(period.state,period.duty)
        np.testing.assert_allclose(state,period.state,atol=2e-6)
        np.testing.assert_allclose(period.voltage-period.blocking,self.op['coupled_model']['output_voltages'])

    def test_no_blocking_collapses_nodes_and_feedback_selection_moves(self):
        p=copy.deepcopy(self.p);p['feedback_output']=2
        p['outputs'][1].update(V_out=12,d_out_enable=False)
        op=compute_operating_point(p)
        self.assertAlmostEqual(op['V_out'],12);self.assertAlmostEqual(op['V_feedback'],12)
        self.assertGreater(op['output_ops'][0]['V_out_cap'],op['output_ops'][0]['V_out'])

    def test_turn_estimates_cover_both_fixed_drops(self):
        rails=output_specs(self.p)
        self.assertAlmostEqual(rails[1]['V_out'],31.4*5/12-.7-.4)
        self.assertAlmostEqual(rails[2]['V_out'],31.4*2/12-.7)

    def test_native_and_cir_sense_before_blocking_and_measure_after(self):
        files=project_files(self.p);m=json.loads(files['manifest.json'])
        self.assertAlmostEqual(m['resolved_controller']['VSET'],30.7)
        self.assertIn(b'XFBSEL cap1 cap2 cap3',files['power_stage.inc'])
        self.assertIn(b'AVG V(out1,sgnd)',files['analysis.inc'])
        self.assertIn(b'out1_cap_before AVG V(cap1,sgnd)',files['analysis.inc'])
        self.assertRegex(files['Flyback.asc'],rb'FLAG 2128 \d+ cap1')


if __name__=='__main__':unittest.main()
