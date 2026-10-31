"""Own Tk window: ACF import, kij retention and topology-specific controls."""
import json
from pathlib import Path
import sys
import tkinter as tk
from unittest.mock import patch
import unittest
ROOT=Path(__file__).resolve().parents[1];sys.path[:0]=[str(ROOT),str(ROOT/'tests')]
import main
from spice_ui import open_export_dialog
from spice_logic_ui import ControllerLogicPanel
from parameter_panel_preview import capture


def all_widgets(w):
    for x in w.winfo_children():yield x;yield from all_widgets(x)


class ACFUI(unittest.TestCase):
    def test_loaded_matrix_and_sync_form(self):
        root=tk.Tk();root.attributes('-alpha',0)
        try:
            with patch.object(main.PowerSupplyAnalyzer,'schedule_update',return_value=None):
                app=main.PowerSupplyAnalyzer(root)
                app._apply_config(json.loads((ROOT/'examples/33W_3OUT_ACF_MP6005.json').read_text(encoding='utf-8')))
                p=app.get_params();p.update(app._rcd_parameters())
                self.assertEqual(p['topology'],'ACF-FORWARD')
                self.assertTrue(p['coupling_config']['enabled'])
                self.assertEqual(len(p['outputs']),3)
                open_export_dialog(root,p,lambda _:None,initial_tab='有源钳位与 SYNC')
                root.update()
                panels=[w for w in all_widgets(root) if isinstance(w,ControllerLogicPanel)]
                self.assertEqual(len(panels),1)
                self.assertIn('acf_dead_ns',panels[0].help)
                self.assertNotIn('qr_cds_pf',panels[0].help)
                dialog=panels[0].winfo_toplevel();capture(dialog,ROOT/'artifacts/qa/acf/controller_ui.png')
        finally:
            for job in root.tk.splitlist(root.tk.call('after','info')):
                try:root.after_cancel(job)
                except tk.TclError:pass
            root.destroy()


if __name__=='__main__':unittest.main()
