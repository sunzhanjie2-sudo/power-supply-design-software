"""Exercise the actual Tk loop tab, beyond backend/report calculations."""
from pathlib import Path
import json,sys,unittest
from unittest.mock import patch
import numpy as np
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
from runtime_resources import configure_numeric_threads
configure_numeric_threads()
import tkinter as tk
import main

class DesktopLoopChecks(unittest.TestCase):
    def test_open_endpoint_files_tune_and_redraw(self):
        root=tk.Tk();root.withdraw()
        try:
            with patch.object(main.PowerSupplyAnalyzer,'schedule_update',return_value=None):
                app=main.PowerSupplyAnalyzer(root)
                names=('24W_BUCK_VM_TPS40200.json','24W_BUCK_PCM_LTC3864.json','24W_BOOST_PCM_LM5022.json')
                for name in names:
                    for endpoint in ('min','max'):
                        with self.subTest(example=name,endpoint=endpoint):
                            cfg=json.loads((ROOT/'examples'/name).read_text(encoding='utf-8'))
                            cfg['input_voltage_case']=endpoint
                            app._apply_config(cfg)
                            self.assertTrue(app.update_all())
                            app.nb.select(app.tab_loop)
                            app._update_loop(app._last['p'])
                            self.assert_loop_rendered(app)
                            self.assertAlmostEqual(app._last['p']['V_in'],app._last['p']['V_in_'+endpoint])
                            # The original failure used an operating point without
                            # this multi-output-only field. Metadata is authoritative.
                            app._last['op'].pop('feedback_output',None)
                            app._redraw_loop_view()
                            self.assert_loop_rendered(app)
                            app.run_auto_tune()
                            self.assertTrue(app.tune_result.get().startswith('type '),app.tune_result.get())
                            self.assertTrue(app.update_all())
                            app._redraw_loop_view()
                            self.assert_loop_rendered(app)
                            self.assertAlmostEqual(app._loop_result['pm'],app._last['p']['pm_target'],delta=.1)
                            self.assertAlmostEqual(app._loop_result['fc']/app._last['p']['fc_target'],1.,delta=.001)
                            if name.startswith('24W_BOOST') and endpoint=='min':
                                image=ROOT/'artifacts/qa/loop_ui_fix_20261029/boost_loop_fixed.png'
                                image.parent.mkdir(parents=True,exist_ok=True)
                                app.fig_loop.savefig(image,dpi=130)
        finally:
            if 'app' in locals():app._calculation_worker.close()
            for timer in root.tk.splitlist(root.tk.call('after','info')):
                try:root.after_cancel(timer)
                except tk.TclError:pass
            root.destroy()

    def assert_loop_rendered(self,app):
        loop=app._loop_result
        self.assertIsNotNone(loop,app.loop_esr_note.get())
        self.assertTrue(all(len(axis.lines)>0 for axis in app.ax_loop.flat))
        self.assertTrue(np.isfinite(loop['fc']))
        self.assertTrue(np.isfinite(loop['pm']))
        self.assertNotIn('未计算',app.margin_info['fc'].get())
        self.assertIn('反馈路：OUT1',app.loop_esr_note.get())
        self.assertNotIn('multi_output',loop)
        self.assertFalse(app.loop_view_row.winfo_manager())

if __name__=='__main__':unittest.main()
