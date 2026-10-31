"""Real GUI regressions for every output's waves, ripple and device losses.

Only this process' transparent Tk window is used. No desktop image, pointer,
focus manipulation or access to a user's running application is involved.
"""
import copy
from pathlib import Path
import sys
import tkinter as tk
import unittest
from unittest.mock import patch

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import main
from engineering_ui import Tooltip
from power_stage import DEFAULT_PARAMS


KINDS = ('power', 'stress', 'cap')
ISOLATED = ('FLYBACK', 'QR-FLYBACK', 'ACF-FORWARD')


def configuration(topology='FLYBACK', count=6, feedback=1):
    p = copy.deepcopy(DEFAULT_PARAMS)
    p.update(topology=topology, V_in=30., Vgs=8.5, L=8e-6,
             N=.5, feedback_mode='SSR', feedback_output=feedback)
    p['outputs'] = [
        dict(name=f'Rail {i+1}', V_out=voltage, P_out=watts,
             C_out=220e-6, C_out2=10e-6, Rc=.08, Rc2=.1,
             ESL=8e-9, ESL2=2e-9, cout2_enable=i % 2 == 0,
             Vf_diode=.5 + i/10, Rd_diode=.01 + i/100,
             Qrr=i*2e-9, L=1e-3, d_out_enable=i % 2 == 1)
        for i, (voltage, watts) in enumerate(
            zip((30., 12., 5., 3.3, 24., 15.), (20., 8., 4., 2., 4., 2.)))
    ][:count]
    return p


class MultiOutputResultsChecks(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.root = tk.Tk()
        cls.root.attributes('-alpha', 0)
        cls.update_patch = patch.object(main.PowerSupplyAnalyzer, 'schedule_update', return_value=None)
        cls.update_patch.start()
        cls.app = main.PowerSupplyAnalyzer(cls.root)
        # These assertions deliberately inspect every Matplotlib artist. The
        # production viewport-lazy mode has its own scrolling/resource suite.
        cls.app._lazy_output_cards = False
        cls.single_config = copy.deepcopy(cls.app._config_dict())
        for job in cls.root.tk.splitlist(cls.root.tk.call('after', 'info')):
            cls.root.after_cancel(job)
        cls.root.geometry('1400x880')
        cls.root.update()

    @classmethod
    def tearDownClass(cls):
        cls.app._closing = True
        cls.app._work_cancel.set()
        Tooltip.hide_all(cls.root)
        for job in cls.root.tk.splitlist(cls.root.tk.call('after', 'info')):
            cls.root.after_cancel(job)
        cls.root.destroy()
        cls.update_patch.stop()

    def setUp(self):
        self.errors = []
        self.root.report_callback_exception = lambda *exc: self.errors.append(exc)
        self.root.geometry('1400x880')
        self.app.nb.select(self.app.tab_topology)
        self.root.update()

    def tearDown(self):
        Tooltip.hide_all(self.root)
        self.root.update()
        self.assertEqual(self.errors, [], 'A test-owned GUI callback failed')

    def render(self, config):
        self.app._apply_config(copy.deepcopy(config))
        self.assertTrue(self.app.update_all(), self.app.status_var.get())
        last = self.app._last
        self.app._update_power(last['op'], last['wf'], last['res'], last['p'])
        self.app._update_stress(last['op'], last['res'])
        self.app._update_cap(last['op'], last['p'], last['res'])
        for kind in KINDS:
            tab = getattr(self.app, 'tab_' + kind)
            self.app._rendered_tabs.add(self.app.nb.index(tab))
        self.root.update()
        for view in self.app._result_scrolls.values():
            view.sync()
        self.root.update()
        self.assertFalse(self.app.status_var.get().startswith(('Power:', 'Stress:', 'Cap:')),
                         self.app.status_var.get())
        return last['res']

    def show(self, kind):
        self.app.nb.select(getattr(self.app, 'tab_' + kind))
        self.root.update()
        view = self.app._result_scrolls[kind]
        view.sync()
        self.root.update()
        return view

    def assert_cards(self, result, feedback):
        rows = result['outputs']
        waveforms = result['wf']['outputs']
        ids = {row['id'] for row in rows}
        for kind in KINDS:
            cards = self.app._output_result_cards[kind]
            self.assertEqual(set(cards), ids)
            for row, wf in zip(rows, waveforms):
                with self.subTest(kind=kind, topology=row['op']['topology'], output=row['id']):
                    card = cards[row['id']]
                    self.assertIs(card['branch']['wf'], wf)
                    self.assertIs(card['branch']['op'], row['op'])
                    self.assertEqual('★' in card['frame'].cget('text'), row['id'] == feedback)
                    self.assertIn(f"OUT{row['id']}", card['frame'].cget('text'))
                    self.assertGreater(card['plot'].winfo_reqheight(), 300)
                    if kind == 'power':
                        self.assertEqual(len(card['figure'].axes), 6 if row['op']['topology'] == 'ACF-FORWARD' else 4)
                        self.assertNotIn('i_sw', card['axes'])
                        self.assertEqual('iL' in card['axes'], row['op']['topology'] == 'ACF-FORWARD')
                        for key, ax in card['axes'].items():
                            if key == 'currents':
                                currents = [wf[k] for k in ('i_s', 'i_d', 'i_c')]
                                for line in ax.lines:
                                    np.testing.assert_array_equal(line.get_xdata(), wf['t'] * 1e6)
                                    self.assertTrue(any(np.array_equal(line.get_ydata(), values) for values in currents))
                                for values in currents:
                                    self.assertTrue(any(np.array_equal(line.get_ydata(), values) for line in ax.lines))
                                continue
                            np.testing.assert_allclose(ax.lines[0].get_xdata(), wf['t'] * 1e6)
                            np.testing.assert_allclose(ax.lines[0].get_ydata(),
                                                       wf[key] * (1e3 if key == 'vout_ripple' else 1.))
                    elif kind == 'cap':
                        self.assertEqual(len(card['figure'].axes), 3)
                        axes = card['axes']
                        bank = row['capacitors']['output']
                        np.testing.assert_allclose([bar.get_width() for bar in axes['rms'].patches],
                                                   [bank['total_bank']] + [cap['total'] for cap in bank['caps']])
                        np.testing.assert_allclose(axes['waveform'].lines[0].get_ydata(),
                                                   (wf['vout_ripple'] + wf['v_esl']) * 1e3)
                        for bars, cap in zip(axes['bands'].containers, bank['caps']):
                            np.testing.assert_allclose([bar.get_height() for bar in bars], cap['bands'])
                        self.assertFalse(any('C_IN' in label.get_text()
                                             for label in axes['rms'].get_yticklabels()))
                    else:
                        self.assertEqual(len(card['figure'].axes), 1)
                        ax = card['axes']['losses']
                        self.assertAlmostEqual(sum(bar.get_width() for bar in ax.patches),
                                               row['P_rectifier'] + row['P_dout'])
                        labels = [label.get_text() for label in ax.get_yticklabels()]
                        self.assertFalse(any('Q1' in label or 'Q2' in label for label in labels))
                        self.assertEqual(any('续流' in label for label in labels), row['op']['topology'] == 'ACF-FORWARD')
        ledger = self.app._multi_stress_ledger
        self.assertAlmostEqual(ledger['total'], result['P_semi'] + result['P_din'] + result['P_dout'])
        self.assertAlmostEqual(ledger['shared'] + sum(ledger['outputs']), ledger['total'])
        self.assertEqual(len(self.app.di_tree.get_children()), len(rows))
        self.assertEqual(len(self.app.dil_tree.get_children()), len(rows))
        bank = result['capacitors']['input']
        self.assertEqual(len(self.app.ax_cap_band), len(bank['caps']))
        self.assertEqual(len(self.app.fig_cap.axes), len(bank['caps']) + 1)
        np.testing.assert_allclose([bar.get_width() for bar in self.app.ax_cap_tot.patches],
                                   [cap['total'] for cap in bank['caps']])
        self.assertTrue(all('输入' in label.get_text() for label in self.app.ax_cap_tot.get_yticklabels()))
        self.assertEqual(len(self.app.fig_power.axes), 8)
        self.assertEqual(len(self.app.fig_stress.axes), 2)
        # The first two pages may not have been visited yet. Their hidden
        # Canvas must not resize a Matplotlib figure to a 1 px placeholder.
        for figure in (self.app.fig_power, self.app.fig_stress, self.app.fig_cap):
            self.assertGreater(figure.get_figwidth(), 2.)

    def test_all_isolated_topologies_show_six_matching_outputs_and_feedback_moves(self):
        for topology in ISOLATED:
            for feedback in (1, 6):
                with self.subTest(topology=topology, feedback=feedback):
                    result = self.render(configuration(topology, feedback=feedback))
                    self.assert_cards(result, feedback)

    def test_six_to_two_to_single_reclaims_cards_axes_trees_and_page_height(self):
        self.render(self.single_config)
        baseline = {}
        for kind in KINDS:
            baseline[kind] = self.show(kind).content.winfo_reqheight()
        self.render(configuration())
        removed = {kind: list(self.app._output_result_cards[kind].values())[2:] for kind in KINDS}
        two = self.render(configuration(count=2))
        self.assert_cards(two, 1)
        for kind in KINDS:
            for card in removed[kind]:
                self.assertFalse(card['frame'].winfo_exists())
                self.assertEqual(card['figure'].axes, [])
            self.assertEqual(len(self.app._output_result_hosts[kind].winfo_children()), 3)
        for _ in range(2):
            self.render(configuration(count=2))
            for kind in KINDS:
                self.assertEqual(len(self.app._output_result_cards[kind]), 2)
                self.assertEqual(len(self.app._output_result_hosts[kind].winfo_children()), 3)
            self.assertEqual(len(self.app.di_tree.get_children()), 2)
            self.assertEqual(len(self.app.fig_power.axes), 8)
        self.render(self.single_config)
        for kind in KINDS:
            view = self.show(kind)
            self.assertEqual(self.app._output_result_cards[kind], {})
            self.assertFalse(self.app._output_result_hosts[kind].winfo_manager())
            self.assertLessEqual(view.content.winfo_reqheight(), baseline[kind] + 100)
            region_height = float(view.canvas.cget('scrollregion').split()[3])
            self.assertLessEqual(region_height, max(view.content.winfo_reqheight(), view.canvas.winfo_height()) + 1)
            self.assertEqual(len(self.app._output_result_hosts[kind].winfo_children()), 1)
        self.assertEqual(len(self.app.fig_power.axes), 8)
        self.assertEqual(len(self.app.ax_power.flat), 6)
        self.assertEqual(len(self.app.ax_power_drain), 2)

    def test_long_pages_scroll_to_out6_and_follow_small_and_large_viewports(self):
        self.render(configuration('ACF-FORWARD'))
        for width, height in ((1000, 600), (1400, 880)):
            self.root.geometry(f'{width}x{height}')
            self.root.update()
            for kind in KINDS:
                with self.subTest(kind=kind, geometry=(width, height)):
                    view = self.show(kind)
                    self.assertEqual(view.content.winfo_width(), view.canvas.winfo_width())
                    self.assertLessEqual(view.winfo_width(), self.app.nb.winfo_width())
                    self.assertGreater(view.content.winfo_reqheight(), view.canvas.winfo_height())
                    self.assertGreater(float(view.canvas.cget('scrollregion').split()[3]), view.canvas.winfo_height())
                    self.assertLess(view.canvas.yview()[1] - view.canvas.yview()[0], .9)
                    view.canvas.yview_moveto(1.)
                    self.root.update()
                    self.assertGreater(view.canvas.yview()[1], .99)
                    card = self.app._output_result_cards[kind][6]
                    plot = card['canvas'].get_tk_widget()
                    self.assertLessEqual(plot.winfo_width(), view.canvas.winfo_width())
                    self.assertLess(plot.winfo_rooty(), view.canvas.winfo_rooty() + view.canvas.winfo_height())
                    self.assertGreater(plot.winfo_rooty() + plot.winfo_height(), view.canvas.winfo_rooty())
                    self.assertGreater(plot.winfo_height(), 300)
                    if width == 1000:
                        self.assertLess(view.canvas.winfo_width(), 720)
                        if kind in ('power', 'cap'):
                            for output_card in self.app._output_result_cards[kind].values():
                                for axis in output_card['figure'].axes:
                                    self.assertEqual(axis.get_subplotspec().get_gridspec().ncols, 1,
                                                     f'{kind}: narrow card must use one readable column')

    def test_default_single_output_keeps_original_six_plots_and_two_drain_axes(self):
        result = self.render(self.single_config)
        self.assertEqual(result.get('outputs', []), [])
        self.assertEqual(len(self.app.fig_power.axes), 8)
        self.assertEqual(len(self.app.ax_power.flat), 6)
        self.assertEqual(len(self.app.ax_power_drain), 2)
        for kind in KINDS:
            self.assertEqual(self.app._output_result_cards[kind], {})
        self.assertAlmostEqual(self.app._last['op']['P_out'], 40.)

    def test_removed_outputs_are_released_without_visiting_lazy_pages(self):
        self.render(configuration())
        self.app.nb.select(self.app.tab_topology)
        self.app._apply_config(configuration(count=2))
        self.assertTrue(self.app.update_all())
        for kind in KINDS:
            self.assertEqual(set(self.app._output_result_cards[kind]), {1, 2})
        self.app._apply_config(self.single_config)
        self.assertTrue(self.app.update_all())
        for kind in KINDS:
            self.assertEqual(self.app._output_result_cards[kind], {})
            self.assertFalse(self.app._output_result_hosts[kind].winfo_manager())


if __name__ == '__main__':
    unittest.main(verbosity=2)
