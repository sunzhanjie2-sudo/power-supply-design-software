"""Owned Tk widgets: switching, draft preservation and report-page rendering."""
import copy
from pathlib import Path
import sys
import tkinter as tk
import unittest
from unittest.mock import patch

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from runtime_resources import configure_numeric_threads
configure_numeric_threads()


class PurchasedInductorUIChecks(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        import main
        cls.main=main
        cls.root=tk.Tk();cls.root.attributes('-alpha',0)
        cls.errors=[];cls.root.report_callback_exception=lambda *args:cls.errors.append(args)
        cls.update_patch=patch.object(main.PowerSupplyAnalyzer,'schedule_update',return_value=None)
        cls.update_patch.start()
        cls.app=main.PowerSupplyAnalyzer(cls.root)
        cls.initial=copy.deepcopy(cls.app._config_dict())
        cls.root.geometry('1440x900');cls.root.update()

    @classmethod
    def tearDownClass(cls):
        cls.app._closing=True;cls.app._work_cancel.set()
        from engineering_ui import Tooltip
        Tooltip.hide_all(cls.root)
        for job in cls.root.tk.call('after','info'):
            cls.root.after_cancel(job)
        cls.root.destroy();cls.update_patch.stop()

    def test_controls_restore_old_config_and_render_without_geometry(self):
        from loss_model import compute_design
        app=self.app
        for topo in ('BUCK','BOOST','BUCK-BOOST'):
            app.params['topology'].set(self.main.TOPO_LABEL[topo])
            app.set_param('V_in',24.);app.set_param('V_out',12. if topo=='BUCK' else 48. if topo=='BOOST' else 24.)
            app.set_param('P_out',12.)
            app.params['inductor_design_enabled'].set(False)
            app.set_param('L',100e-6);app.set_param('inductor_dcr',.037)
            app._filter_params();self.root.update()
            self.assertEqual(app._param_widgets['L'][0].winfo_manager(),'grid')
            self.assertEqual(app._param_widgets['inductor_dcr'][0].winfo_manager(),'grid')
            self.assertEqual(app._param_widgets['Bmax'][0].winfo_manager(),'')
            self.assertEqual(app.core_combo.winfo_manager(),'')
            p=app.get_params()
            self.assertFalse(p['inductor_design_enabled'])
            self.assertAlmostEqual(p['inductor_dcr'],.037)
            cfg=copy.deepcopy(app._config_dict())
            app.params['inductor_design_enabled'].set(True)
            self.assertEqual(app.core_combo.winfo_manager(),'grid')
            app._apply_config(cfg)
            self.assertFalse(app.params['inductor_design_enabled'].get())
            result=compute_design(app.get_params())
            app._update_mag(result['op'],app.get_params(),result,result['wf'])
            self.assertIn('未评估',app.mag_text.get('1.0','end'))
            self.assertNotIn('全部通过',app.mag_check.get())
            self.assertEqual(app._b_waveforms(result['op'],result['wf'],result),[])
        legacy=copy.deepcopy(self.initial)
        for key in tuple(legacy):
            if key.startswith('inductor_'):legacy.pop(key)
        app._apply_config(legacy)
        self.assertTrue(app.params['inductor_design_enabled'].get())
        self.assertEqual(self.errors,[])


if __name__=='__main__':unittest.main()
