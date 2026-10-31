"""Physical clamp envelope, stress and immutable gate-time regression."""
from pathlib import Path
import sys
import unittest

import numpy as np
from matplotlib.figure import Figure
from matplotlib.backends.backend_agg import FigureCanvasAgg

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from flyback_clamp import (attach_clamp, clamp_voltage, leakage_pulse,
                           clamp_current, rcd_components)
from power_stage import DEFAULT_PARAMS, compute_operating_point
from semiconductor import mosfet_loss, device_stress
from switching_transients import switching_voltage_data, draw_switching_event
from magnetics import rcd_snubber


def setup(**overrides):
    p = dict(DEFAULT_PARAMS, topology='FLYBACK', V_in=30., V_out=30.,
             P_out=40., N=.5, L=8e-6, f_sw=250e3, K=.995, Kc=1.5,
             Coss=200e-12)
    p.update(overrides)
    op = compute_operating_point(p)
    return p, attach_clamp(op, p)


class ClampChecks(unittest.TestCase):
    def test_period_plateau_peak_and_physical_reset_duration(self):
        p, op = setup(Coss=0.)
        c = op['clamp']
        self.assertAlmostEqual(c['L_leak'], (1.-p['K'])*op['L'])
        self.assertAlmostEqual(c['V_peak'], op['V_in']+p['Kc']*op['V_r'])
        self.assertAlmostEqual(c['t_decay'], c['L_leak']*op['I_L_pk']/((p['Kc']-1.)*op['V_r']))
        start = op['D']*op['Ts']
        time = np.array([0., start+c['t_pulse']/2., start+c['t_pulse']*1.1])
        values = clamp_voltage(time, op)
        np.testing.assert_allclose(values, [0., c['V_peak'], c['V_plateau']])
        self.assertAlmostEqual(c['P_res'], rcd_snubber(p['K'],p['Kc'],op['L'],
            op['I_L_pk'],op['V_r'],op['f_sw'])['P_res'])

    def test_finite_coss_charge_and_no_energy_means_no_spike(self):
        p, op = setup()
        c = op['clamp']
        self.assertGreater(c['t_rise'], 0.)
        self.assertLess(c['I_clamp_start'], c['I_initial'])
        self.assertAlmostEqual(float(leakage_pulse(np.array([c['t_rise']]),c)[0]),
                               c['V_peak']-c['V_plateau'])
        _, ideal = setup(K=1.)
        self.assertEqual(ideal['clamp']['t_pulse'], 0.)
        self.assertEqual(ideal['clamp']['P_res'], 0.)
        self.assertEqual(ideal['clamp']['V_peak'], ideal['clamp']['V_plateau'])
        self.assertEqual(ideal['V_sw_max'], ideal['clamp']['V_ceiling'])

    def test_clamp_not_reached_and_unspecified_clamp_not_invented(self):
        _, op = setup(Coss=.01)
        c = op['clamp']
        self.assertEqual(c['shape'], 'unclamped_lobe')
        self.assertFalse(c['clamp_conducts'])
        self.assertEqual(c['P_res'], 0.)
        self.assertLess(c['V_peak'], c['V_ceiling'])
        _, absent = setup(Kc=0.)
        self.assertEqual(absent['clamp']['shape'], 'none')
        self.assertEqual(absent['V_sw_max'], absent['clamp']['V_peak'])
        self.assertTrue(any('未覆盖漏感尖峰' in note for note in absent['clamp']['notes']))

    def test_gate_times_unchanged_and_tail_not_stretched_to_t8(self):
        p, op = setup(K=.9)
        loss = mosfet_loss(op, p)
        data = switching_voltage_data(op, p, loss)
        for key in ('t1','t2','t3','t6','t7','t8'):
            self.assertEqual(data['times'][key], loss[key])
        self.assertEqual([s['key'] for s in data['off']], ['t5','t6','t7','t8'])
        self.assertIsNotNone(data['off_tail'])
        self.assertAlmostEqual(data['on'][0]['vds'][0], op['clamp']['V_plateau'])
        self.assertAlmostEqual(data['off'][1]['vds'][-1], op['clamp']['V_plateau'])
        for left, right in zip(data['off'], data['off'][1:]):
            self.assertAlmostEqual(left['vds'][-1],right['vds'][0])
        physical_peak = max(float(np.max(s['vds'])) for s in data['off'])
        self.assertAlmostEqual(physical_peak, op['clamp']['V_peak'])
        fig=Figure(figsize=(9,4)); ax=fig.subplots(); FigureCanvasAgg(fig)
        draw_switching_event(ax,data,'off',real_time=True)
        self.assertEqual(len(fig.axes),2)
        self.assertTrue(any('钳位恢复' in t.get_text() for t in ax.texts))
        stress = device_stress(op)['switch']
        self.assertEqual(stress['V_peak_physical'],op['clamp']['V_peak'])
        self.assertGreaterEqual(stress['V_recommended'],stress['V_max'])

    def test_matrix_voltage_authoritative_no_second_spike(self):
        p, op = setup()
        tt=np.linspace(0.,op['Ts'],1024,endpoint=False)
        off=tt >= op['D']*op['Ts']
        voltage=np.where(off,52.,0.)
        active=off & (tt < op['D']*op['Ts']+100e-9)
        voltage[active]=61.
        current=np.where(active,1.,0.)
        op['coupled_solution']=dict(t=tt,v_sw=voltage,i_clamp=current,
                                    diagnostics=dict(P_clamp=.123))
        attach_clamp(op,p)
        self.assertEqual(op['V_sw_max'],61.)
        self.assertEqual(op['clamp']['P_res'],.123)
        self.assertEqual(op['clamp']['model'],'coupled_winding_transient')
        self.assertIsNone(op['clamp']['L_leak'])
        data=switching_voltage_data(op,p,mosfet_loss(op,p))
        self.assertEqual(data['vhigh'],61.)
        self.assertLessEqual(max(float(np.max(s['vds'])) for s in data['off']),61.)

    def test_explicit_leakage_does_not_reinterpret_legacy_k(self):
        legacy=rcd_snubber(.99,1.5,100e-6,2.,50.,100e3)
        self.assertAlmostEqual(legacy['L_leak'],1e-6)
        explicit=rcd_snubber(.99,1.5,100e-6,2.,50.,100e3,L_leak=3e-6)
        self.assertEqual(explicit['L_leak'],3e-6)
        self.assertAlmostEqual(explicit['P_res'],3.*legacy['P_res'])

    def test_matrix_nonuniform_grid_and_clamp_metadata(self):
        p,op=setup()
        period=op['Ts']
        op['coupled_solution']=dict(t=np.array([0.,.5,.6,1.])*period,
            v_sw=np.array([0.,60.,60.,0.]),i_clamp=np.array([0.,1.,0.,0.]),
            diagnostics=dict(clamp_voltage=35.,L_leak=2e-7))
        attach_clamp(op,p)
        self.assertAlmostEqual(op['clamp']['P_res'],9.)
        self.assertEqual(op['clamp']['V_ceiling'],65.)
        self.assertEqual(op['clamp']['V_clamp'],35.)
        self.assertEqual(op['clamp']['L_leak'],2e-7)

    def test_all_one_matrix_fallback_never_reintroduces_legacy_leakage(self):
        p,op=setup(K=.9,Kc=0.)
        op['coupled_model']=dict(ideal_fallback=True,L_leak=0.)
        attach_clamp(op,p)
        self.assertEqual(op['clamp']['L_leak'],0.)
        self.assertEqual(op['clamp']['P_res'],0.)
        self.assertEqual(op['V_sw_max'],op['clamp']['V_plateau'])
        self.assertGreaterEqual(op['V_sw_recommended'],op['V_sw_max'])

    def test_rcd_components_and_current_share_ledger(self):
        p,op=setup()
        rcd=rcd_components(op,p)
        self.assertEqual(rcd['P_res'],op['clamp']['P_res'])
        self.assertAlmostEqual(rcd['R_snub'],rcd['V_clamp']**2/rcd['P_res'])
        self.assertAlmostEqual(rcd['C_snub'],rcd['P_res']/(op['f_sw']*rcd['V_clamp']*rcd['dV_clamp']))
        c=op['clamp']
        # Exact midpoint integration of the triangular clamp current.
        mid=np.linspace(c['t_rise'],c['t_pulse'],10001,endpoint=False)
        step=(c['t_pulse']-c['t_rise'])/10001
        current=clamp_current(op['D']*op['Ts']+mid+step/2,op)
        self.assertAlmostEqual(np.sum(current)*step*c['V_clamp']*op['f_sw'],rcd['P_res'])
        p0,op0=setup(K=1.)
        r0=rcd_components(op0,p0)
        self.assertTrue(np.isinf(r0['R_snub']))
        self.assertEqual(r0['C_snub'],0.)


if __name__ == '__main__':
    unittest.main(verbosity=2)
