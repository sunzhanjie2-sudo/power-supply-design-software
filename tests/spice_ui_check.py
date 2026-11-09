"""Own transparent Tk window: settings/save roundtrip and asynchronous export."""
import copy
from pathlib import Path
import sys
import tempfile
import time
import tkinter as tk
from tkinter import ttk
import unittest
from unittest.mock import patch

ROOT=Path(__file__).resolve().parents[1]
sys.path[:0]=[str(ROOT),str(ROOT/'tests')]
import main
from parameter_panel_preview import capture
from spice_ui import open_export_dialog,comparison_feedback
from spice_export import SETTINGS,CHOICES
from spice_logic_ui import ControllerLogicPanel


def descendants(widget):
    for child in widget.winfo_children():
        yield child
        yield from descendants(child)


class SpiceUICheck(unittest.TestCase):
    def test_quick_plan_is_explicit_and_preserves_controller(self):
        import json
        from design_engine.specification import load_spec
        root=tk.Tk();root.withdraw()
        try:
            p=load_spec(json.loads((ROOT/'examples/40W_CCM_3OUT_FLYBACK.json').read_text(encoding='utf-8')))
            applied=[]
            open_export_dialog(root,p,applied.append)
            dialog=next(w for w in root.winfo_children() if isinstance(w,tk.Toplevel))
            buttons=[w for w in descendants(dialog) if isinstance(w,ttk.Button)]
            next(w for w in buttons if w.cget('text')=='快速预检（推荐）').invoke()
            next(w for w in buttons if w.cget('text')=='应用到计算器').invoke()
            self.assertEqual(applied[-1]['fra_enabled'],0)
            self.assertEqual(applied[-1]['cross_enabled'],0)
            self.assertEqual(applied[-1]['step_ms'],12)
            self.assertEqual(applied[-1]['cs_limit'],p['spice_config']['cs_limit'])
            next(w for w in buttons if w.cget('text')=='完整对比').invoke()
            next(w for w in buttons if w.cget('text')=='应用到计算器').invoke()
            self.assertEqual(applied[-1]['fra_enabled'],1)
            self.assertEqual(applied[-1]['cross_enabled'],1)
        finally:root.destroy()

    def test_reference_buttons_for_all_six_topology_control_contexts(self):
        import json
        from design_engine.specification import load_spec
        examples=('40W_CCM_3OUT_FLYBACK.json','90W_QR_L6565_300V.json','33W_3OUT_ACF_MP6005.json',
                  '24W_BUCK_VM_TPS40200.json','24W_BUCK_PCM_LTC3864.json','24W_BOOST_PCM_LM5022.json')
        root=tk.Tk();root.withdraw()
        try:
            for name in examples:
                with self.subTest(example=name):
                    p=load_spec(json.loads((ROOT/'examples'/name).read_text(encoding='utf-8')))
                    applied=[]
                    with patch('spice_ui.messagebox.showerror') as error:
                        open_export_dialog(root,p,applied.append)
                        dialog=next(w for w in root.winfo_children() if isinstance(w,tk.Toplevel))
                        try:
                            buttons=[w for w in descendants(dialog) if isinstance(w,ttk.Button)]
                            next(w for w in buttons if w.cget('text').startswith('填入')).invoke()
                            self.assertFalse(error.called,str(error.call_args))
                            next(w for w in buttons if w.cget('text')=='应用到计算器').invoke()
                            self.assertEqual(len(applied),1)
                            self.assertFalse(error.called,str(error.call_args))
                            if p['topology'] in ('BUCK','BOOST'):
                                self.assertEqual(applied[0]['niso_profile'],p['spice_config']['niso_profile'])
                            else:
                                self.assertEqual(applied[0]['niso_profile'],0.)
                        finally:dialog.destroy()
        finally:root.destroy()

    def test_failed_comparison_is_not_presented_as_success(self):
        result=dict(successful=0,total=2,fra_successful=0,fra_total=2,cross_successful=0,cross_total=0,incomplete=True)
        level,title,text=comparison_feedback(result)
        self.assertEqual(level,'warning');self.assertIn('未完成',title);self.assertIn('没有有效',text)
        result['successful']=1
        self.assertEqual(comparison_feedback(result)[1],'对比部分完成')
        result.update(successful=2,fra_successful=2,incomplete=False)
        self.assertEqual(comparison_feedback(result)[0],'info')

    def test_buck_reference_button_keeps_example_dcr_and_test_plan(self):
        import json
        from design_engine.specification import load_spec
        root=tk.Tk();root.withdraw()
        try:
            p=load_spec(json.loads((ROOT/'examples/24W_BUCK_VM_TPS40200.json').read_text(encoding='utf-8')))
            original=copy.deepcopy(p['spice_config']);applied=[]
            open_export_dialog(root,p,applied.append)
            dialog=next(w for w in root.winfo_children() if isinstance(w,tk.Toplevel))
            buttons=[w for w in descendants(dialog) if isinstance(w,ttk.Button)]
            next(w for w in buttons if w.cget('text')=='填入控制器参考值').invoke()
            next(w for w in buttons if w.cget('text')=='应用到计算器').invoke()
            for key in ('niso_inductor_dcr','soft_start_ms','step_ms','stop_ms','fra_start_hz','fra_stop_hz','simulation_threads'):
                self.assertEqual(applied[0][key],original[key],key)
        finally:root.destroy()

    def test_owned_dialog_and_export(self):
        root=tk.Tk();root.attributes('-alpha',0)
        try:
            with patch.object(main.PowerSupplyAnalyzer,'schedule_update',return_value=None):
                app=main.PowerSupplyAnalyzer(root)
            for job in root.tk.call('after','info'):root.after_cancel(job)
            app._spice_config=dict(kp=120)
            cfg=app._config_dict();self.assertEqual(cfg['spice_config']['kp'],120)
            app._apply_config(copy.deepcopy(cfg))
            self.assertEqual(app.get_params()['spice_config']['kp'],120)
            p=app.get_params();p.update(app._rcd_parameters())
            applied=[]
            open_export_dialog(root,p,applied.append)
            dialog=next(w for w in root.winfo_children() if isinstance(w,tk.Toplevel))
            dialog.attributes('-alpha',0);root.update()
            from qr_spice_settings import applicable_keys
            applicable=set(applicable_keys('FLYBACK'))
            self.assertEqual(len([w for w in descendants(dialog) if isinstance(w,ttk.Entry) and not isinstance(w,ttk.Combobox)]),len(applicable-set(CHOICES)))
            self.assertEqual(len([w for w in descendants(dialog) if isinstance(w,ttk.Combobox)]),len(applicable&set(CHOICES)))
            self.assertEqual(len(next(w for w in descendants(dialog) if isinstance(w,ttk.Notebook)).tabs()),6)
            logic=next(w for w in descendants(dialog) if isinstance(w,ControllerLogicPanel))
            field=next(w for w in descendants(dialog) if isinstance(w,ttk.Entry) and not isinstance(w,ttk.Combobox))
            field.delete(0,'end');field.insert(0,'123000');field.event_generate('<FocusIn>')
            end=time.monotonic()+.25
            while time.monotonic()<end:root.update();time.sleep(.01)
            self.assertEqual(logic.active_key,'frequency_hz')
            self.assertIn('123',logic.heading.cget('text'))
            field.delete(0,'end');field.insert(0,'0')
            logic.select('hiccup_off_ms')
            end=time.monotonic()+.25
            while time.monotonic()<end:root.update();time.sleep(.01)
            self.assertIn('当前不是打嗝',logic.condition.cget('text'))
            logic.select('frequency_hz')
            folder=ROOT/'artifacts/qa/spice-controller-v3';folder.mkdir(parents=True,exist_ok=True)
            capture(dialog,folder/'desktop-settings.png')
            dialog.geometry('1120x760')
            end=time.monotonic()+.4
            while time.monotonic()<end:root.update();time.sleep(.01)
            # Small windows now retain readable diagram boxes and expose a
            # horizontal scrollbar, instead of shrinking text into overlaps.
            extent=tuple(float(v) for v in logic.canvas.cget('scrollregion').split())
            self.assertLessEqual(logic.canvas.bbox('all')[2],extent[2]+2)
            self.assertTrue(logic.xscroll.winfo_ismapped())
            logic.canvas.xview_moveto(1);root.update()
            self.assertGreater(logic.canvas.xview()[0],0)
            self.assertAlmostEqual(logic.canvas.xview()[1],1)
            capture(dialog,folder/'desktop-settings-small.png')
            with tempfile.TemporaryDirectory() as td, patch('spice_ui.filedialog.asksaveasfilename',return_value=str(Path(td)/'project.zip')),patch('spice_ui.messagebox.showinfo') as info:
                button=next(w for w in descendants(dialog) if isinstance(w,ttk.Button) and '导出 ASC' in w.cget('text'))
                button.invoke()
                deadline=time.monotonic()+20
                while not info.called and time.monotonic()<deadline:
                    root.update();time.sleep(.025)
                self.assertTrue(info.called,'background export did not return')
                self.assertTrue((Path(td)/'project.zip').is_file())
                self.assertEqual(applied[0]['kp'],120)
            names=[w.cget('textvariable') for w in descendants(dialog) if isinstance(w,ttk.Entry)]
            self.assertTrue(any(root.tk.call('trace','info','variable',name) for name in names))
            dialog.destroy();root.update()
            self.assertTrue(all(not root.tk.call('trace','info','variable',name) for name in names))
        finally:
            if 'app' in locals():app._closing=True;app._work_cancel.set()
            for job in root.tk.call('after','info'):root.after_cancel(job)
            root.destroy()


if __name__=='__main__':unittest.main()
