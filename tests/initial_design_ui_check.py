"""Exercise Tk's topology switch and adopt action without touching an existing project."""
import json
from pathlib import Path
import sys
import time
import tkinter as tk
from tkinter import ttk
import unittest
from unittest.mock import patch

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from runtime_resources import configure_numeric_threads
configure_numeric_threads()
from config_io import decode_config
from main import PowerSupplyAnalyzer


def children(parent):
    for w in parent.winfo_children():
        yield w
        yield from children(w)


def button(dialog,text):
    return next(w for w in children(dialog) if isinstance(w,ttk.Button) and w.cget('text')==text)


class InitialDesignUi(unittest.TestCase):
    def test_change_topology_invalidates_pending_draft_and_adopt_preserves_comp(self):
        root=tk.Tk()
        root.withdraw()
        with patch.object(PowerSupplyAnalyzer,'schedule_update'):
            app=PowerSupplyAnalyzer(root)
            try:
                before=app._config_dict()
                dlg=app.open_initial_design()
                dlg.withdraw()
                choose,controller=[w for w in children(dlg) if isinstance(w,ttk.Combobox)][:2]
                choose.set('BUCK')
                go=button(dlg,'生成并校核')
                apply=button(dlg,'采用此初版')
                go.invoke()
                choose.set('BOOST')
                self.assertEqual(tuple(controller['values']),('LM5022 · 峰值电流模式',))
                end=time.monotonic()+30
                while go.instate(['disabled']) and time.monotonic()<end:
                    root.update()
                    time.sleep(.02)
                self.assertFalse(go.instate(['disabled']))
                self.assertTrue(apply.instate(['disabled']))
                go.invoke()
                while go.instate(['disabled']) and time.monotonic()<end:
                    root.update()
                    time.sleep(.02)
                info=next(w for w in children(dlg) if isinstance(w,tk.Text)).get('1.0','end')
                self.assertFalse(apply.instate(['disabled']),info)
                self.assertIn('RHP',info)
                self.assertEqual(decode_config(app._config_dict())['topology'],decode_config(before)['topology'])
                apply.invoke()
                stored=json.loads(json.dumps(app._config_dict()))
                self.assertEqual(decode_config(stored)['topology'],'BOOST')
                self.assertEqual(stored['__auto_design_basis']['topology'],'BOOST')
                app._apply_config(stored)
                p=app.get_params()
                self.assertEqual(p['spice_config']['niso_profile'],3)
                self.assertAlmostEqual(p['L'],39e-6)
                self.assertAlmostEqual(p['eta_guess'],.9)
                self.assertEqual(app._comp_key(),'opamp3')
                app._run_comp_calc()
                self.assertIn('COMP 网络 KP',app.comp_result.get())
                dlg=app.open_initial_design()
                dlg.withdraw()
                choose=next(w for w in children(dlg) if isinstance(w,ttk.Combobox))
                self.assertEqual(choose.get(),'BOOST')
                self.assertTrue(any(isinstance(w,ttk.Checkbutton) and w.cget('text')=='锁定 L' for w in children(dlg)))
                choose.set('BUCK')
                self.assertFalse(any(isinstance(w,ttk.Checkbutton) for w in children(dlg)))
                choose.set('FLYBACK')
                choices=[w for w in children(dlg) if isinstance(w,ttk.Combobox)]
                choices[-1].set('DCM')
                go=button(dlg,'生成并校核')
                go.invoke()
                end=time.monotonic()+30
                while go.instate(['disabled']) and time.monotonic()<end:
                    root.update()
                    time.sleep(.02)
                info=next(w for w in children(dlg) if isinstance(w,tk.Text)).get('1.0','end')
                self.assertIn('满载目标 DCM',info)
                button(dlg,'采用此初版').invoke()
                report=app._config_dict()
                self.assertEqual(report['__auto_design_basis']['topology'],'FLYBACK')
                self.assertEqual(app._comp_key(),'tl431nf')
                app._apply_config(report)
                dlg=app.open_initial_design()
                self.assertEqual([w for w in children(dlg) if isinstance(w,ttk.Combobox)][-1].get(),'DCM')
                button(dlg,'关闭').invoke()
            finally:
                app._closing=True
                app._work_cancel.set()
                for job in root.tk.splitlist(root.tk.call('after','info')):
                    root.after_cancel(job)
                root.destroy()


if __name__=='__main__':
    unittest.main(verbosity=2)
