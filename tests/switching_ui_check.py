"""Q1 switching charts and topology-page regression, including actual Tk UI."""
import copy
from pathlib import Path
import sys
import tkinter as tk
import unittest

import numpy as np
from matplotlib.figure import Figure
from matplotlib.backends.backend_agg import FigureCanvasAgg

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from power_stage import DEFAULT_PARAMS, TOPOLOGIES
from loss_model import compute_design
from switching_transients import switching_voltage_data, draw_switching_event
from topology_diagram import topology_components, draw_topology


def spec(topo):
    p = dict(DEFAULT_PARAMS, topology=topo)
    if topo in ('BUCK', 'BUCK-BOOST'):
        p.update(V_in=12., V_out=5., P_out=5., L=47e-6)
    elif topo == 'BOOST':
        p.update(V_in=12., V_out=24., P_out=12., L=100e-6)
    elif topo == 'ACF-FORWARD':
        p.update(N=.5, L=68e-6, Lm_forward=220e-6, C_clamp=47e-9)
    return p


class SwitchingChecks(unittest.TestCase):
    def test_six_times_and_loss_ledger_unchanged(self):
        for topo in TOPOLOGIES:
            with self.subTest(topology=topo):
                p = spec(topo); r = compute_design(p)
                before = copy.deepcopy(r['semi']['switch'])
                data = switching_voltage_data(r['op'], p, r['semi']['switch'])
                for k in ('t1', 't2', 't3', 't6', 't7', 't8'):
                    self.assertEqual(data['times'][k], before[k])
                self.assertEqual(r['semi']['switch'], before)
                self.assertGreater(data['times']['t4'], 0)
                self.assertGreater(data['times']['t5'], 0)

    def test_threshold_plateau_and_drain_edges(self):
        p = spec('FLYBACK'); r = compute_design(p)
        d = switching_voltage_data(r['op'], p, r['semi']['switch'])
        on, off = d['on'], d['off']
        self.assertEqual([s['key'] for s in on+off], [f't{i}' for i in range(1, 9)])
        self.assertAlmostEqual(on[0]['vgs'][-1], p['Vth'])
        self.assertAlmostEqual(on[1]['vgs'][-1], p['Vgp_on'])
        self.assertTrue(np.all(on[2]['vgs'] == p['Vgp_on']))
        self.assertTrue(np.all(off[1]['vgs'] == p['Vgp_off']))
        self.assertAlmostEqual(off[2]['vgs'][-1], p['Vth'])
        self.assertAlmostEqual(off[3]['vgs'][-1], p['Vth']*np.exp(-3))
        self.assertGreater(on[2]['vds'][0], on[2]['vds'][-1])
        self.assertLess(off[1]['vds'][0], off[1]['vds'][-1])
        for stages in (on, off):
            for a, b in zip(stages, stages[1:]):
                self.assertAlmostEqual(a['vgs'][-1], b['vgs'][0])
                self.assertAlmostEqual(a['vds'][-1], b['vds'][0])

    def test_missing_post_plateau_charge_is_not_fabricated(self):
        p = spec('FLYBACK'); p['Qg'] = p['Qgs']+p['Qgd']
        r = compute_design(p); d = switching_voltage_data(r['op'], p, r['semi']['switch'])
        self.assertIsNone(d['times']['t4']); self.assertIsNone(d['times']['t5'])
        self.assertIn('时长未知', ' '.join(d['notes']))
        fig = Figure(); ax = fig.subplots(); FigureCanvasAgg(fig)
        draw_switching_event(ax, d, 'off', real_time=True)
        self.assertIn('非等时长', ax.get_xlabel())

    def test_render_reuses_drain_axis_and_actual_time(self):
        p = spec('FLYBACK'); r = compute_design(p)
        d = switching_voltage_data(r['op'], p, r['semi']['switch'])
        fig = Figure(); ax = fig.subplots(); drain = ax.twinx(); FigureCanvasAgg(fig)
        for _ in range(12):
            draw_switching_event(ax, d, 'on', real_time=True, drain_ax=drain)
        self.assertEqual(len(fig.axes), 2)
        self.assertIn('时间 / ns', ax.get_xlabel())
        self.assertAlmostEqual(ax.lines[3].get_xdata()[-1],
                               sum(d['times'][f't{i}'] for i in range(1, 5))*1e9)
        self.assertTrue(all(np.isfinite(line.get_ydata()).all() for line in drain.lines))

    def test_invalid_off_plateau_does_not_draw_a_false_discharge(self):
        p = dict(spec('FLYBACK'), Vgp_off=12.)
        r = compute_design(p); d = switching_voltage_data(r['op'], p, r['semi']['switch'])
        self.assertIsNone(d['off'])
        fig = Figure(); ax = fig.subplots(); FigureCanvasAgg(fig)
        draw_switching_event(ax, d, 'off')
        self.assertIn('无法重建', ax.get_title())

    def test_schematic_registry_matches_all_symbols_and_options(self):
        fig = Figure(); ax = fig.subplots(); FigureCanvasAgg(fig)
        for topo in TOPOLOGIES:
            for enabled in (True, False):
                with self.subTest(topology=topo, optional=enabled):
                    p = dict(spec(topo), cin2_enable=enabled, cout2_enable=enabled,
                             d_in_enable=enabled, d_out_enable=enabled,
                             Kc=1.5 if enabled else 0.)
                    before = dict(p); rows = draw_topology(ax, p)
                    self.assertEqual(p, before)
                    self.assertEqual(rows, topology_components(p))
                    refs = [r['ref'] for r in rows]
                    self.assertEqual(len(refs), len(set(refs)))
                    self.assertIn('Q1', refs)
                    for ref in ('D_IN', 'D_OUT', 'C_IN2', 'C_O2'):
                        self.assertEqual(ref in refs, enabled)
                    self.assertEqual('Q2' in refs, topo == 'ACF-FORWARD')
                    self.assertEqual('T1' in refs, topo in ('FLYBACK', 'QR-FLYBACK', 'ACF-FORWARD'))


class GUIPageChecks(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        import main
        # This suite verifies every tab's drawing, not the separately tested
        # asynchronous control import. Make the dependency available before
        # asserting all tabs have rendered, independent of warm-up timing.
        import control
        cls.main = main
        cls.root = tk.Tk(); cls.root.withdraw()
        cls.app = main.PowerSupplyAnalyzer(cls.root)
        assert cls.app.update_all()

    @classmethod
    def tearDownClass(cls):
        a = cls.app; a._closing = True; a._work_cancel.set()
        for job in (a.update_timer, a._font_timer, a._initial_update_job,
                    a._control_warmup_job, a._control_poll_job, a._work_poll):
            if job is not None:
                try: cls.root.after_cancel(job)
                except tk.TclError: pass
        cls.root.destroy()

    def setUp(self):
        # The minimum-size test drains Tk startup/variable callbacks. They
        # may invalidate a snapshot until the debounced calculation runs.
        # Each rendering test must start from a freshly computed snapshot.
        self.assertTrue(self.app.update_all())

    def test_tab_order_and_all_lazy_updaters(self):
        a = self.app
        expected = [a.tab_topology, a.tab_power, a.tab_stress, a.tab_mag,
                    a.tab_loop, a.tab_eff, a.tab_cap, a.tab_rcd, a.tab_comp, a.tab_review]
        self.assertEqual(list(a.nb.tabs()), [str(w) for w in expected])
        self.assertEqual(len(a._tab_updaters()), 10)
        a._rendered_tabs.clear()
        for tab in expected:
            a.nb.select(tab); a._refresh_visible_tab()
            self.assertNotIn('Refresh:', a.status_var.get())
        self.assertEqual(a._rendered_tabs, set(range(10)))
        a.nb.select(a.tab_topology)

    def test_power_chart_order_and_repeated_redraw(self):
        a = self.app; L = a._last
        for real_time in (True, False)*4:
            a.mos_real_time.set(real_time)
            a._update_power(L['op'], L['wf'], L['res'], L['p'])
            self.assertEqual(len(a.fig_power.axes), 8)  # six panels + two right voltage axes
            self.assertNotIn('Power:', a.status_var.get())
        titles = [ax.get_title() for ax in a.ax_power.ravel()]
        self.assertIn('MOS 电流 Q1', titles[0]); self.assertIn('二极管电流 D1', titles[1])
        self.assertIn('输出纹波', titles[2]); self.assertIn('输出电压', titles[3])
        self.assertIn('开通', titles[4]); self.assertIn('关断', titles[5])
        for ax, expected in zip(a.ax_power.ravel()[-2:], (range(1, 5), range(5, 9))):
            labels = ' '.join(t.get_text() for t in ax.get_xticklabels())
            for i in expected: self.assertIn(f't{i}', labels)
        a._update_topology(L['op'], L['p'])
        self.assertIn('Q1', a.topology_tree.get_children())

    def test_minimum_window_keeps_all_ten_tabs_accessible(self):
        a = self.app
        try:
            # Map only our test window, fully transparent and off-screen, so
            # Tk computes real tab hit-boxes without exposing a user window.
            self.root.attributes('-alpha', 0.)
            self.root.geometry('1000x600-10000-10000')
            self.root.deiconify()
            a._apply_scale(self.main._font_scale_for(1000, 600))
            self.root.update()
            self.assertGreater(a.nb.winfo_width(), 300, self.root.geometry())
            visible = set()
            for y in (8, 15, 22, 29):
                for x in range(0, a.nb.winfo_width(), 3):
                    try: visible.add(a.nb.index(f'@{x},{y}'))
                    except tk.TclError: pass
            self.assertEqual(visible, set(range(10)), f'Notebook width={a.nb.winfo_width()}')
        finally:
            self.root.withdraw()
            self.root.geometry('1600x950')
            self.root.attributes('-alpha', 1.)
            a._apply_scale(1.)


if __name__ == '__main__':
    unittest.main(verbosity=2)
