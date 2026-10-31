"""Viewport-lazy rail cards use only this process' transparent Tk window.

Small chart stubs isolate ownership and scheduling from electrical solvers.
The existing multi_output_results_check suite still validates all real axes.
"""
from pathlib import Path
import gc
import sys
import time
import tkinter as tk
from tkinter import ttk
import unittest
import weakref
from unittest.mock import patch

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from multi_output_results import MultiOutputResultsUI


def snapshot(value=1., count=6):
    rows, waves = [], []
    for rail_id in range(1, count + 1):
        rows.append(dict(
            id=rail_id, name=f'Rail {rail_id}',
            spec=dict(V_out=12., P_out=4.),
            op=dict(topology='FLYBACK', V_out=12., P_out=4.,
                    I_d_rms=1., mode='CCM'), ripple_pp=.01))
        waves.append(dict(t=np.array([0., 1e-6]),
                          i_s=np.array([value, value + rail_id]), ripple_pp=.01))
    return dict(feedback_output=1, topology='FLYBACK'), dict(outputs=rows, wf=dict(outputs=waves))


class Host(MultiOutputResultsUI):
    def __init__(self, root):
        self.root = root
        self._closing = False
        self._snapshot_valid = True
        self._lazy_output_cards = True
        self.nb = ttk.Notebook(root)
        self.nb.pack(fill='both', expand=True)
        self.page = ttk.Frame(self.nb)
        self.other = ttk.Frame(self.nb)
        self.nb.add(self.page, text='Power')
        self.nb.add(self.other, text='Other')
        body = self._build_results_scroll(self.page, 'power')
        spacer = ttk.Frame(body, height=280)
        spacer.pack(fill='x')
        spacer.pack_propagate(False)
        self._build_output_result_host(body, 'power')


class LazyRailCardsChecks(unittest.TestCase):
    def setUp(self):
        self.root = tk.Tk()
        self.root.attributes('-alpha', 0)
        self.root.geometry('1000x650')
        self.errors = []
        self.root.report_callback_exception = lambda *exc: self.errors.append(exc)
        self.draws = []

        def draw(fig, branch, *, feedback=False):
            self.draws.append((branch['id'], branch['wf']['i_s'][0]))
            fig.clear()
            ax = fig.add_subplot(111)
            ax.plot(branch['wf']['t'], branch['wf']['i_s'])
            return dict(i_s=ax)

        self.draw_patch = patch('multi_output_charts.draw_output_power', side_effect=draw)
        self.draw_patch.start()
        self.app = Host(self.root)
        self.root.update()
        self.base_images = len(self.root.tk.splitlist(self.root.tk.call('image', 'names')))

    def tearDown(self):
        self.app._closing = True
        self.app._hide_output_result_page('power')
        for job in self.root.tk.splitlist(self.root.tk.call('after', 'info')):
            self.root.after_cancel(job)
        self.root.destroy()
        self.draw_patch.stop()
        self.assertEqual(self.errors, [])

    def pump(self, seconds=.28):
        until = time.perf_counter() + seconds
        while time.perf_counter() < until:
            self.root.update()
            time.sleep(.005)
        self.root.update()

    def pump_until(self, predicate, timeout=3.):
        deadline = time.perf_counter() + timeout
        while not predicate():
            self.root.update()
            if time.perf_counter() > deadline:
                self.fail('Viewport did not settle before the timeout')
            time.sleep(.005)
        self.root.update()

    def update(self, value=1., count=6):
        op, result = snapshot(value, count)
        self.app._update_output_result_cards('power', op, result)
        self.pump()
        return self.app._output_result_cards['power']

    def live(self):
        return {key for key, card in self.app._output_result_cards['power'].items()
                if card['canvas'] is not None}

    def test_only_visible_cards_allocate_tkagg_and_keep_every_output_placeholder(self):
        cards = self.update()
        self.assertEqual(set(cards), set(range(1, 7)))
        self.assertEqual(self.live(), {1})
        self.assertEqual(self.draws, [(1, 1.)])
        self.assertTrue(all(card['plot'].winfo_reqheight() == 600 for card in cards.values()))
        for rail_id in range(2, 7):
            self.assertEqual(cards[rail_id]['figure'].axes, [])
            self.assertTrue(cards[rail_id]['placeholder'].winfo_manager())

    def test_scroll_reaches_all_six_outputs_and_releases_old_photos(self):
        cards = self.update()
        view = self.app._result_scrolls['power']
        visited = {1}
        # Center each rail in turn, then visit OUT6 at the end of the page.
        for rail_id, card in cards.items():
            content_y = card['plot'].winfo_y() + card['frame'].winfo_y() + card['frame'].master.winfo_y()
            region_height = float(view.canvas.cget('scrollregion').split()[3])
            view.canvas.yview_moveto(content_y / region_height)
            self.pump()
            visited.update(self.live())
            self.assertLessEqual(len(self.live()), 2)
        view.canvas.yview_moveto(1.)
        self.pump()
        self.assertIn(6, self.live())
        self.assertEqual(visited, set(range(1, 7)))
        self.assertIsNone(cards[1]['canvas'])
        self.assertEqual(cards[1]['figure'].axes, [])
        self.assertLessEqual(len(self.root.tk.splitlist(self.root.tk.call('image', 'names'))),
                             self.base_images + 2)

    def test_hidden_page_releases_pixels_and_refreshes_from_latest_snapshot(self):
        cards = self.update()
        first_frame = cards[1]['frame']
        self.app.nb.select(self.app.other)
        self.pump(.12)
        self.assertEqual(self.live(), set())
        before = len(self.draws)
        self.update(value=7.)
        self.assertEqual(len(self.draws), before)
        self.assertIs(cards[1]['frame'], first_frame)
        self.app.nb.select(self.app.page)
        self.pump()
        self.assertEqual(self.live(), {1})
        self.assertEqual(self.draws[-1], (1, 7.))

    def test_scroll_storm_is_coalesced_and_removed_rails_free_geometry(self):
        cards = self.update()
        view = self.app._result_scrolls['power']
        before = len(self.draws)
        for index in range(80):
            view.canvas.yview_moveto((index % 10) / 9.)
            self.root.update_idletasks()
        self.pump()
        self.assertLessEqual(len(self.draws) - before, 2)
        removed = [cards[key] for key in (3, 4, 5, 6)]
        self.update(count=2)
        self.assertEqual(set(cards), {1, 2})
        for card in removed:
            self.assertFalse(card['frame'].winfo_exists())
            self.assertEqual(card['figure'].axes, [])
        self.update(count=0)
        self.assertEqual(cards, {})
        self.assertFalse(self.app._output_result_hosts['power'].winfo_manager())

    def test_invalidated_snapshot_never_draws_stale_data_after_page_change(self):
        self.update()
        self.app._snapshot_valid = False
        self.app.nb.select(self.app.other)
        self.pump(.12)
        before = len(self.draws)
        self.app.nb.select(self.app.page)
        self.pump()
        self.assertEqual(self.live(), set())
        self.assertEqual(len(self.draws), before)
        self.app._snapshot_valid = True
        self.app._schedule_output_result_viewport('power')
        self.pump()
        self.assertEqual(self.live(), {1})

    def test_new_design_releases_surviving_cards_old_snapshot_before_page_visit(self):
        op, old = snapshot(value=2.)
        refs = [weakref.ref(wave['i_s']) for wave in old['wf']['outputs']]
        self.app._update_output_result_cards('power', op, old)
        self.pump()
        cards = self.app._output_result_cards['power']
        frame, reserved = cards[1]['frame'], cards[1]['reserved_size']
        self.app.nb.select(self.app.other)
        self.pump(.12)
        del old
        _op, current = snapshot(value=9.)
        self.app._prune_output_result_cards(current)
        self.draw_patch.target.draw_output_power.reset_mock()
        gc.collect()
        self.assertTrue(all(reference() is None for reference in refs))
        self.assertIs(cards[1]['frame'], frame)
        self.assertEqual(cards[1]['reserved_size'], reserved)
        self.assertTrue(all(card['branch'] is None for card in cards.values()))
        self.assertTrue(all(card['figure'].axes == [] for card in cards.values()))
        # A Map before the lazy page updater runs cannot resurrect old data.
        before = len(self.draws)
        self.app.nb.select(self.app.page)
        self.pump()
        self.assertEqual(len(self.draws), before)
        self.assertEqual(self.live(), set())
        self.app._update_output_result_cards('power', op, current)
        self.pump()
        self.assertEqual(self.draws[-1], (1, 9.))

    def test_resize_updates_offscreen_reservations_without_rendering_all_rails(self):
        cards = self.update()
        before = len(self.draws)
        for width in (620, 560, 610, 500):
            self.root.geometry(f'{width}x650')
            self.root.update_idletasks()
        self.pump_until(lambda: all(card['plot'].winfo_reqheight() == 1085
                                   for card in cards.values())
                        and not self.app._result_card_jobs)
        self.assertEqual(self.live(), {1})
        self.assertLessEqual(len(self.draws) - before, 2)
        self.assertTrue(all(card['plot'].winfo_reqheight() == 1085 for card in cards.values()))
        self.assertTrue(all(card['figure'].get_figwidth() < 7.2 for card in cards.values()))
        for rail_id in range(2, 7):
            self.assertIsNone(cards[rail_id]['canvas'])
        view = self.app._result_scrolls['power']
        view.canvas.yview_moveto(1.)
        self.pump()
        self.assertIn(6, self.live())

    def test_explicit_eager_render_still_builds_all_axes_for_diagnostics(self):
        cards = self.update()
        self.app._lazy_output_cards = False
        for card in cards.values():
            self.app._render_output_result_card(card)
        self.root.update()
        self.assertEqual(self.live(), set(range(1, 7)))
        self.assertTrue(all(len(card['figure'].axes) == 1 for card in cards.values()))
        self.app._lazy_output_cards = True


if __name__ == '__main__':
    unittest.main(verbosity=2)
