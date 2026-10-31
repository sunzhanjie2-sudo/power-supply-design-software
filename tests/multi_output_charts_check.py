"""Actual six-output chart snapshots: no branch recompute or shared copies."""
import copy
import json
from pathlib import Path
import sys
import unittest

import numpy as np
from matplotlib.backends.backend_agg import FigureCanvasAgg
from matplotlib.figure import Figure

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from design_api import load_spec
from loss_model import compute_design
from power_stage import DEFAULT_PARAMS
from multi_output_charts import (
    OUTPUT_POWER_FIGSIZE, OUTPUT_FORWARD_POWER_FIGSIZE,
    OUTPUT_CAPACITORS_FIGSIZE, OUTPUT_LOSSES_FIGSIZE,
    draw_output_power, draw_output_capacitors, draw_output_losses,
    draw_shared_power_signals, output_chart_figsize, draw_output_currents,
)


def multi(topology):
    p = copy.deepcopy(DEFAULT_PARAMS)
    p.update(topology=topology, V_in=30., Vgs=8.5, L=8e-6,
             N=.5, feedback_output=2)
    p['outputs'] = [dict(name=f'Rail {i+1}', V_out=v, P_out=watts,
                         C_out=220e-6, C_out2=10e-6, Rc=.08, Rc2=.1,
                         ESL=8e-9, ESL2=2e-9, cout2_enable=i % 2 == 0,
                         Vf_diode=.5 + i/10, Rd_diode=.01 + i/100,
                         Qrr=i*2e-9, L=1e-3, d_out_enable=i % 2 == 1)
                    for i, (v, watts) in enumerate(
                        zip((30., 12., 5., 3.3, 24., 15.), (20., 8., 4., 2., 4., 2.)))]
    return p


def enriched(result):
    return [dict(branch, wf=wf) for branch, wf in
            zip(result['outputs'], result['wf']['outputs'])]


class ChartChecks(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.results = {topology: compute_design(multi(topology)) for topology in
                       ('FLYBACK', 'QR-FLYBACK', 'ACF-FORWARD')}

    def test_all_power_samples_belong_to_the_output(self):
        for topology, result in self.results.items():
            for branch in enriched(result):
                fig = Figure(figsize=OUTPUT_FORWARD_POWER_FIGSIZE if topology ==
                             'ACF-FORWARD' else OUTPUT_POWER_FIGSIZE)
                axes = draw_output_power(fig, branch, feedback=branch['id'] == 2)
                self.assertEqual(len(fig.axes), 6 if topology == 'ACF-FORWARD' else 4)
                self.assertEqual('iL' in axes, topology == 'ACF-FORWARD')
                self.assertEqual('i_free' in axes, topology == 'ACF-FORWARD')
                self.assertNotIn('i_sw', axes)
                for key, ax in axes.items():
                    if key == 'currents':
                        artists = draw_output_currents(ax, branch)
                        for signal, artist in artists.items():
                            np.testing.assert_array_equal(artist.get_xdata(), branch['wf']['t'] * 1e6)
                            np.testing.assert_array_equal(artist.get_ydata(), branch['wf'][signal])
                        self.assertEqual(len(ax.lines), 2 if np.array_equal(branch['wf']['i_s'], branch['wf']['i_d']) else 3)
                        continue
                    np.testing.assert_allclose(ax.lines[0].get_xdata(), branch['wf']['t'] * 1e6)
                    np.testing.assert_allclose(ax.lines[0].get_ydata(),
                                               branch['wf'][key] * (1e3 if key == 'vout_ripple' else 1.))
                self.assertEqual('★' in fig._suptitle.get_text(), branch['id'] == 2)
                self.assertIn(f'OUT{branch["id"]}', fig._suptitle.get_text())

    def test_cap_rms_bands_and_voltage_match_each_real_bank(self):
        for result in self.results.values():
            for branch in enriched(result):
                fig = Figure(figsize=OUTPUT_CAPACITORS_FIGSIZE)
                axes = draw_output_capacitors(fig, branch)
                bank = branch['capacitors']['output']
                actual = [bar.get_width() for bar in axes['rms'].patches]
                np.testing.assert_allclose(actual, [bank['total_bank']] + [c['total'] for c in bank['caps']])
                self.assertAlmostEqual(branch['P_cap'], sum(c['ESR'] * c['total']**2 for c in bank['caps']))
                for container, cap in zip(axes['bands'].containers, bank['caps']):
                    np.testing.assert_allclose([bar.get_height() for bar in container], cap['bands'])
                    self.assertAlmostEqual(sum(value**2 for value in cap['bands']), cap['total']**2)
                np.testing.assert_allclose(axes['waveform'].lines[0].get_ydata(),
                                           (branch['wf']['vout_ripple'] + branch['wf']['v_esl']) * 1e3)
                np.testing.assert_allclose(axes['waveform'].lines[1].get_ydata(), branch['wf']['vout_ripple'] * 1e3)
                self.assertEqual(len(fig.axes), 3)
                self.assertFalse(any('C_IN' in label.get_text() for label in axes['rms'].get_yticklabels()))

    def test_loss_bars_match_ledger_without_duplicated_q1(self):
        for topology, result in self.results.items():
            total = 0.
            for branch in enriched(result):
                fig = Figure(figsize=OUTPUT_LOSSES_FIGSIZE)
                ax = draw_output_losses(fig, branch)['losses']
                bars_total = sum(bar.get_width() for bar in ax.patches)
                self.assertAlmostEqual(bars_total, branch['P_rectifier'] + branch['P_dout'])
                total += bars_total
                labels = [label.get_text() for label in ax.get_yticklabels()]
                self.assertEqual(any('续流' in label for label in labels), topology == 'ACF-FORWARD')
                self.assertFalse(any('Q1' in label or 'Q2' in label for label in labels))
                self.assertEqual(any('防反' in label for label in labels), branch['spec']['d_out_enable'])
            self.assertAlmostEqual(total + result['semi']['switch']['P_total'] +
                                   result['semi'].get('auxiliary', {}).get('P_total', 0),
                                   result['P_semi'] + result['P_dout'])

    def test_repeated_draw_replaces_axes_instead_of_accumulating(self):
        fig = Figure(figsize=OUTPUT_FORWARD_POWER_FIGSIZE)
        for topology, result in self.results.items():
            branch = enriched(result)[-1]
            for draw, count in ((draw_output_power, 6 if topology == 'ACF-FORWARD' else 4),
                                (draw_output_capacitors, 3), (draw_output_losses, 1)):
                draw(fig, branch)
                draw(fig, branch)
                self.assertEqual(len(fig.axes), count)

    def test_shared_signals_are_aggregate_not_current_feedback(self):
        for topology, result in self.results.items():
            fig = Figure(figsize=(11.2, 6.))
            axes = fig.subplots(2, 2)
            draw_shared_power_signals(axes, result['op'], result['wf'])
            keys = ('i_sw', 'i_in', 'v_sw', 'i_mag' if topology == 'ACF-FORWARD' else 'i_p')
            for ax, key in zip(axes.flat, keys):
                np.testing.assert_allclose(ax.lines[0].get_ydata(), result['wf'][key])
                self.assertIn('共享', ax.get_title())
            draw_shared_power_signals(axes, result['op'], result['wf'])
            self.assertTrue(all(len(ax.lines) == 1 for ax in axes.flat))

    def test_existing_six_output_example_and_rendered_label_spacing(self):
        p = load_spec(json.loads((ROOT / 'examples' / '6_OUTPUT_FLYBACK_SSR.json').read_text(encoding='utf-8')))
        result = compute_design(p)
        self.assertEqual(len(result['outputs']), 6)
        branch = enriched(result)[-1]
        for draw, size in ((draw_output_power, OUTPUT_POWER_FIGSIZE),
                           (draw_output_capacitors, OUTPUT_CAPACITORS_FIGSIZE),
                           (draw_output_losses, OUTPUT_LOSSES_FIGSIZE)):
            fig = Figure(figsize=size)
            FigureCanvasAgg(fig)
            axes = draw(fig, branch, feedback=True)
            fig.canvas.draw()
            for ax in fig.axes:
                self.assertGreater(ax.get_position().width, .1)
                self.assertGreater(ax.get_position().height, .1)
            if draw is draw_output_capacitors:
                boxes = [tick.get_window_extent(fig.canvas.get_renderer())
                         for tick in axes['bands'].get_xticklabels()]
                self.assertTrue(all(a.x1 + 3 < b.x0 for a, b in zip(boxes, boxes[1:])))

    def test_missing_waveform_is_not_silently_recomputed(self):
        branch = self.results['FLYBACK']['outputs'][0]
        for draw in (draw_output_power, draw_output_capacitors):
            with self.assertRaisesRegex(ValueError, '快照'):
                draw(Figure(), branch)

    def test_nearly_equal_but_distinct_currents_are_not_merged(self):
        branch = dict(enriched(self.results['FLYBACK'])[0])
        branch['wf'] = dict(branch['wf'])
        branch['wf']['i_d'] = branch['wf']['i_s'].copy()
        branch['wf']['i_d'][1] += 1e-9
        ax = Figure().subplots()
        artists = draw_output_currents(ax, branch)
        self.assertEqual(len(ax.lines), 3)
        self.assertIsNot(artists['i_s'], artists['i_d'])
        np.testing.assert_array_equal(artists['i_d'].get_ydata(), branch['wf']['i_d'])

    def test_combining_currents_does_not_change_the_snapshot(self):
        branch = enriched(self.results['FLYBACK'])[0]
        before = {key: value.copy() for key, value in branch['wf'].items() if isinstance(value, np.ndarray)}
        axes = draw_output_power(Figure(figsize=OUTPUT_POWER_FIGSIZE), branch)
        self.assertIn('currents', axes)
        self.assertTrue({'i_s', 'i_d', 'i_c'}.isdisjoint(axes))
        for key, value in before.items():
            np.testing.assert_array_equal(branch['wf'][key], value)

    def test_gui_font_does_not_rescale_titles_or_squeeze_data_areas(self):
        from matplotlib import rc_context
        from types import SimpleNamespace
        from multi_output_results import MultiOutputResultsUI
        from multi_output_charts import relayout_output_figure
        branch=enriched(self.results['FLYBACK'])[0]
        for size in (20,32,40):
            with self.subTest(size=size),rc_context({'font.size':size,'axes.titlesize':size}):
                fig=Figure(figsize=(24.06,6*max(1,size/14)),dpi=100)
                FigureCanvasAgg(fig)
                axes=draw_output_power(fig,branch,feedback=True)
                MultiOutputResultsUI._scale_result_text(SimpleNamespace(_font_k=size/13),'power',fig)
                relayout_output_figure(fig,size/14)
                fig.canvas.draw();renderer=fig.canvas.get_renderer()
                for ax in fig.axes:
                    self.assertAlmostEqual(ax.title.get_fontsize(),10*size/14)
                    self.assertGreater(ax.get_window_extent(renderer).height,150)
                title=axes['currents'].title.get_window_extent(renderer)
                legend=axes['currents'].get_legend().get_window_extent(renderer)
                self.assertGreater(title.y0,legend.y1+3)
                self.assertGreater(fig._suptitle.get_window_extent(renderer).y0,title.y1+3)

    def test_narrow_540px_cards_use_readable_single_columns(self):
        for topology, result in self.results.items():
            branch = enriched(result)[0]
            # User-defined long rail names must not push a title outside PNG.
            branch = dict(branch, name='控制板与通信接口辅助电源长名称输出通道')
            for kind, draw in (('power', draw_output_power),
                               ('cap', draw_output_capacitors),
                               ('stress', draw_output_losses)):
                fig = Figure(figsize=output_chart_figsize(kind, topology, 5.4), dpi=100)
                FigureCanvasAgg(fig)
                axes = draw(fig, branch, feedback=True)
                fig.canvas.draw()
                renderer = fig.canvas.get_renderer()
                self.assertEqual(round(fig.bbox.width), 540)
                # Power/cap axes are genuinely stacked, not squeezed columns.
                if kind != 'stress':
                    centers = [ax.get_position().x0 + ax.get_position().width / 2 for ax in fig.axes]
                    self.assertLess(max(centers) - min(centers), .001)
                    self.assertTrue(all(ax.get_window_extent(renderer).height > 100 for ax in fig.axes))
                for text in (fig._suptitle, *fig.texts):
                    box = text.get_window_extent(renderer)
                    self.assertGreaterEqual(box.x0, 0)
                    self.assertLessEqual(box.x1, fig.bbox.width)
                    self.assertGreaterEqual(box.y0, 0)
                    self.assertLessEqual(box.y1, fig.bbox.height)
                if kind == 'cap':
                    boxes = [tick.get_window_extent(renderer) for tick in axes['bands'].get_xticklabels()]
                    self.assertTrue(all(a.x1 + 3 < b.x0 for a, b in zip(boxes, boxes[1:])))
                    self.assertEqual(len(axes['bands'].patches), 22 * len(branch['capacitors']['output']['caps']))


if __name__ == '__main__':
    unittest.main(verbosity=2)
