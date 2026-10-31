"""Verify GUI/print waveform contents match, not merely similar captions."""
import copy
from pathlib import Path
import sys
import tkinter as tk
import unittest

import numpy as np
from matplotlib.figure import Figure
from matplotlib import rc_context

sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import main
from power_charts import draw_power_signals, draw_power_switching
from switching_ui_check import spec
from power_stage import TOPOLOGIES


class PowerReportChecks(unittest.TestCase):
    def test_gui_and_print_contents(self):
        root=tk.Tk(); root.withdraw(); app=main.PowerSupplyAnalyzer(root)
        try:
            for topology in TOPOLOGIES:
                for physical in (False,True):
                    with self.subTest(topology=topology,real_time=physical):
                        p=spec(topology); r=main.compute_design(p)
                        before=copy.deepcopy(r['semi']['switch'])
                        app.mos_real_time.set(physical)
                        app._update_power(r['op'],r['wf'],r,p)
                        steady=Figure(); steady_axes=steady.subplots(2,2)
                        mos=Figure(); mos_axes=mos.subplots(1,2)
                        # Report-local defaults must not change the power chart theme.
                        with rc_context({'axes.titleweight':'normal','grid.color':'#000000'}):
                            draw_power_signals(steady_axes,topology,r['wf'])
                            data=draw_power_switching(mos_axes,r['op'],p,r,real_time=physical)
                        # Same order, units, curve samples, time labels and voltage axes.
                        print_axes=list(steady_axes.flat)+list(mos_axes)+mos.axes[-2:]
                        for actual,expected in zip(app.fig_power.axes,print_axes):
                            self.assertEqual(actual.get_title(),expected.get_title())
                            self.assertEqual(actual.title.get_fontweight(),expected.title.get_fontweight())
                            self.assertEqual(actual.get_xlabel(),expected.get_xlabel())
                            self.assertEqual(actual.get_ylabel(),expected.get_ylabel())
                            self.assertEqual(len(actual.lines),len(expected.lines))
                            for a,b in zip(actual.lines,expected.lines):
                                np.testing.assert_array_equal(a.get_xdata(),b.get_xdata())
                                np.testing.assert_array_equal(a.get_ydata(),b.get_ydata())
                                self.assertEqual(a.get_color(),b.get_color())
                            if expected.get_xlabel().startswith('阶段展开'):
                                self.assertEqual([t.get_text() for t in actual.get_xticklabels()],
                                                 [t.get_text() for t in expected.get_xticklabels()])
                        self.assertEqual(app._mos_voltage_data['times'],data['times'])
                        self.assertEqual(before,r['semi']['switch'])
                        self.assertEqual(len(app.fig_power.axes),8)
        finally:
            app._closing=True
            for name in ('update_timer','_font_timer','_initial_update_job','_control_warmup_job'):
                job=getattr(app,name,None)
                if job is not None: root.after_cancel(job)
            root.destroy()


if __name__=='__main__': unittest.main(verbosity=2)
