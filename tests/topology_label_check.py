"""Expanded-winding designators must not touch core/capacitor strokes."""
from pathlib import Path
import sys
import unittest
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from matplotlib.figure import Figure
from matplotlib.backends.backend_agg import FigureCanvasAgg
from matplotlib.transforms import Bbox
from power_stage import DEFAULT_PARAMS
from topology_diagram import draw_topology, topology_components


class TopologyLabelChecks(unittest.TestCase):
    def test_component_values_do_not_double_apply_display_unit_prefixes(self):
        p = dict(DEFAULT_PARAMS, outputs=[dict(V_out=30., P_out=40., Ns=12,
            cout2_enable=True, Rc2=0.0001, ESL2=1e-10, C_out2=10e-6)])
        rows = {row['ref']: row for row in topology_components(p)}
        self.assertEqual(rows['C_O1B']['values'], 'C=10uF; ESR=100uΩ; ESL=100pH')

    def test_multi_winding_labels_clear_core_and_adjacent_capacitors(self):
        for count in (2, 3, 6):
            with self.subTest(count=count):
                p = dict(DEFAULT_PARAMS, outputs=[dict(V_out=30., P_out=40./count,
                    Ns=12, cout2_enable=True) for _ in range(count)])
                figure = Figure(figsize=(7.1, 6.4 if count > 3 else 4.6), dpi=140)
                ax = figure.subplots()
                draw_topology(ax, p)
                for text in ax.texts:
                    text.set_fontfamily('Microsoft YaHei')
                canvas = FigureCanvasAgg(figure)
                canvas.draw()
                renderer = canvas.get_renderer()
                labels = {text.get_text(): text.get_window_extent(renderer) for text in ax.texts}
                core_x = ax.transData.transform((8.3, 0))[0]
                self.assertLess(labels['Q1'].x1, core_x - 2)
                height = max(12, 5*count+2)
                for i in range(1, count+1):
                    yy = height-2-5*(i-1)
                    plate_box = Bbox.from_extents(15.72, yy-1.55, 16.48, yy-1.25)
                    plate_pixels = ax.transData.transform_bbox(plate_box)
                    self.assertFalse(labels[f'C_O{i}B'].overlaps(plate_pixels))
                    self.assertFalse(labels[f'C_O{i}A'].overlaps(labels[f'C_O{i}B']))


if __name__ == '__main__':
    unittest.main(verbosity=2)
