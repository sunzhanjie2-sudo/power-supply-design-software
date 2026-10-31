import sys,unittest,copy
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
import tkinter as tk
from unittest.mock import patch
from system_workspace_ui import SystemWorkspace
import system_workspace as w

class LdoDesktop(unittest.TestCase):
    def test_add_open_return_and_saved_parameters(self):
        root=tk.Tk();root.withdraw();app=SystemWorkspace(root,recovery=False);root.withdraw();app.initialized=True
        try:
            app.project=w.load_project(ROOT/'examples/SYSTEM_LDO.json');app.title.set(app.project['title']);app.render()
            before=copy.deepcopy(app.project);app.add_ldo();new=app.project['units'][-1]
            self.assertEqual(new['spec']['topology'],'LDO');self.assertEqual(len(new['rails']),1)
            app.open_unit('LDO-01');ui=app.calculator;ui.root.withdraw()
            self.assertIsNotNone(ui.result);self.assertEqual(ui.spec['V_in_min'],4.75)
            root.update();self.assertFalse(ui.adjustable_frame.winfo_manager())
            ui.vars['output_mode'][0].set('可调输出（计算分压）');root.update()
            self.assertEqual(ui.adjustable_frame.winfo_manager(),'pack');self.assertTrue(ui.compute())
            self.assertGreater(ui.result['divider']['R_bottom'],0)
            ui.vars['I_out_max'][0].set('80');self.assertTrue(ui.compute());self.assertAlmostEqual(ui.spec['I_out_max'],.08)
            ui.close();self.assertIsNone(app.calculator);root.withdraw()
            self.assertAlmostEqual(app.project['units'][0]['spec']['I_out_max'],.08)
            self.assertEqual(app.project['connections'],before['connections'])
        finally:root.destroy()

if __name__=='__main__':unittest.main(verbosity=2)
