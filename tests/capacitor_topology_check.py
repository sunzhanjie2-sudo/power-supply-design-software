"""Visible capacitor banks, readable report figures and real editor redraws."""
import copy
import json
from pathlib import Path
import sys
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from runtime_resources import configure_numeric_threads
configure_numeric_threads()
from matplotlib import rc_context
from matplotlib.figure import Figure
from matplotlib.backends.backend_agg import FigureCanvasAgg
from design_engine.specification import load_spec
from power_stage import DEFAULT_PARAMS, TOPOLOGIES, fmt_eng
from topology_diagram import draw_topology


def caps(n):
    return [dict(C=(100+i)*1e-6, ESR=.02, ESL=1e-9) for i in range(n)]


def multi(count=3):
    p = load_spec(json.loads((ROOT/'examples/40W_CCM_3OUT_FLYBACK.json').read_text(encoding='utf-8')))
    p['coupling_config']['enabled'] = False
    while len(p['outputs']) < count:
        p['outputs'].append(copy.deepcopy(p['outputs'][-1]))
    p['outputs'] = p['outputs'][:count]
    return p


class CapacitorTopologyChecks(unittest.TestCase):
    def draw(self, p, size=(7.1, 4.6)):
        figure = Figure(figsize=size, dpi=140, layout='constrained' if size[0] < 8 else None)
        ax = figure.subplots()
        if size[0] >= 8:
            figure.subplots_adjust(left=.02, right=.98, bottom=.02, top=.98)
        original = copy.deepcopy(p)
        rows = draw_topology(ax, p)
        self.assertEqual(p, original)
        return figure, ax, rows

    def test_every_topology_draws_three_and_summarizes_large_banks(self):
        for topology in TOPOLOGIES:
            for n in (1, 2, 3, 4, 27, 1000):
                with self.subTest(topology=topology, count=n):
                    p = dict(DEFAULT_PARAMS, topology=topology, outputs=[],
                             input_capacitors=caps(n), output_capacitors=caps(n))
                    _, ax, rows = self.draw(p)
                    texts = [t.get_text() for t in ax.texts]
                    refs = {r['ref'] for r in rows}
                    for prefix in ('C_IN', 'C_O'):
                        for i in (range(1, n+1) if n <= 3 else (1, n)):
                            self.assertIn(prefix+str(i), texts)
                        self.assertEqual({r for r in refs if r.startswith(prefix)},
                                         {prefix+str(i) for i in range(1, n+1)})
                    self.assertEqual(texts.count('…'), 2 if n > 3 else 0)
                    self.assertIn(f'{n} 颗 · ΣC={fmt_eng(sum(c["C"] for c in caps(n)), "F")}', texts)
                    # Rendering cost stays bounded as the configured bank grows.
                    self.assertLess(len(ax.lines), 200)

    def test_each_output_has_its_own_symbols_last_designator_and_total(self):
        from capacitor_banks import output_ref
        for topology, mode in (('FLYBACK', 'SSR'), ('ACF-FORWARD', 'SSR'),
                               ('QR-FLYBACK', 'SSR'), ('FLYBACK', 'PSR-MP6005')):
            with self.subTest(topology=topology, mode=mode):
                p = multi(); p.update(topology=topology, feedback_mode=mode, input_capacitors=caps(4))
                if topology == 'ACF-FORWARD':
                    p = load_spec(json.loads((ROOT/'examples/33W_3OUT_ACF_MP6005_COMPACT.json').read_text(encoding='utf-8')))
                    p['input_capacitors'] = caps(4)
                for rail, n in zip(p['outputs'], (1, 3, 27)):
                    rail['output_capacitors'] = caps(n)
                _, ax, rows = self.draw(p)
                texts = [t.get_text() for t in ax.texts]
                self.assertEqual(texts.count('…'), 2)
                self.assertIn('C_IN4', texts)
                self.assertIn('C_O1A', texts); self.assertNotIn('C_O1B', texts)
                self.assertIn('C_O2C', texts); self.assertIn('C_O3_27', texts)
                self.assertNotIn('C_O3B', texts)
                refs = {r['ref'] for r in rows}
                for output, n in enumerate((1, 3, 27), 1):
                    for i in range(1, n+1):
                        self.assertIn(output_ref(output, i, True), refs)

    def test_capacitor_labels_and_totals_do_not_overlap_in_report_or_desktop(self):
        for count in (3, 6):
            for n in (1, 2, 3, 40):
                for size in ((11.5, 4.4), (7.1, 6.4 if count > 3 else 4.6)):
                    with self.subTest(outputs=count, capacitors=n, size=size):
                        p = multi(count); p['input_capacitors'] = caps(n)
                        for row in p['outputs']: row['output_capacitors'] = caps(n)
                        with rc_context({'font.sans-serif': ['Microsoft YaHei', 'DejaVu Sans']}):
                            fig, ax, _ = self.draw(p, size)
                            canvas = FigureCanvasAgg(fig); canvas.draw()
                            labels = [t for t in ax.texts if t.get_text().startswith(('C_IN', 'C_O'))
                                      or 'ΣC=' in t.get_text()]
                            boxes = [(t.get_text(), t.get_window_extent(canvas.get_renderer())) for t in labels]
                            for i, (name, box) in enumerate(boxes):
                                for other in ax.texts:
                                    if other not in labels[:i+1] and other.get_text():
                                        self.assertFalse(box.overlaps(other.get_window_extent(canvas.get_renderer())),
                                                         (name, other.get_text()))

    def test_real_editor_resize_value_change_and_redraw_remove_old_labels(self):
        import tkinter as tk
        import main
        root = tk.Tk(); root.withdraw()
        try:
            with patch.object(main.PowerSupplyAnalyzer, 'schedule_update', return_value=None):
                app = main.PowerSupplyAnalyzer(root); app._apply_config(multi())
                editor = app._inline_cap_editors[1]
                editor.count.set('3'); editor.resize()
                self.assertTrue(app.update_all())
                self.assertIn('C_O2C', [t.get_text() for t in app.ax_topology.texts])
                editor.count.set('1'); editor.resize()
                editor.variables['C'].set('123')
                self.assertTrue(app.update_all())
                texts = [t.get_text() for t in app.ax_topology.texts]
                self.assertNotIn('C_O2C', texts); self.assertNotIn('C_O2B', texts)
                self.assertTrue(any('电容 1 颗 · ΣC='+fmt_eng(123e-6, 'F') in t for t in texts))
        finally:
            if 'app' in locals(): app._calculation_worker.close()
            for timer in root.tk.splitlist(root.tk.call('after', 'info')):
                try: root.after_cancel(timer)
                except tk.TclError: pass
            root.destroy()


if __name__ == '__main__': unittest.main(verbosity=2)
