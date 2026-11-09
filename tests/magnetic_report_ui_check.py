"""Owned Tk report: reflow, bold states, scrolling and immutable rerender."""
import json
from pathlib import Path
import sys
import tkinter as tk
from tkinter import font
from tkinter import ttk
import unittest
from unittest.mock import patch

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from runtime_resources import configure_numeric_threads
configure_numeric_threads()


class MagneticReportUI(unittest.TestCase):
    def test_readable_scrollable_and_cached_report_in_calculator(self):
        import main
        from design_engine.service import calculate
        from magnetic_report_ui import COLORS
        root=tk.Tk();root.withdraw();root.maxsize(2400,1800)
        errors=[]
        root.report_callback_exception=lambda *args:errors.append(args)
        with patch.object(main.PowerSupplyAnalyzer,'schedule_update'),patch.object(main.PowerSupplyAnalyzer,'request_update'):
            app=main.PowerSupplyAnalyzer(root)
        try:
            bar=root.nametowidget(root.cget('menu'))
            labels=[bar.entrycget(i,'label') for i in range(1,bar.index('end')+1)]
            self.assertEqual(labels[:3],['File (文件)','示例','自动设计'])
            files=root.nametowidget(bar.entrycget(1,'menu'))
            self.assertFalse(any('示例' in files.entrycget(i,'label') or '初版' in files.entrycget(i,'label')
                for i in range(files.index('end')+1) if files.type(i)=='command'))
            app.load_isolated_example('40W_CCM_3OUT_FLYBACK.json')
            self.assertEqual(app.get_params()['parallel_wires_p'],1)
            app.params['parallel_wires_p'].set('2')
            saved_parallel=app._config_dict()
            app.params['parallel_wires_p'].set('1');app._apply_config(saved_parallel)
            self.assertEqual(app.get_params()['parallel_wires_p'],2)
            app.params['parallel_wires_p'].set('1')
            self.assertNotIn('le_core',app._param_widgets)
            self.assertEqual(app.mat_combo.get(),'DMR44')
            self.assertEqual(app.get_params()['core_material'],'DMR44')
            self.assertEqual(app._config_dict()['core_material']['v'],'DMR44')
            c=calculate(app._config_dict(),analysis='selected',include_loop=False,include_efficiency=False,include_cross_regulation=False).runtime_bundle()['cases'][0]
            r=c['result'];app._update_mag(r['op'],c['p'],r,r['wf'])
            self.assertIn('μr=2400',app.transformer_gap_readout.get())
            self.assertIn('OUT3',app.mag_text.get())
            self.assertIn('40 K',app.mag_check.get())
            # Show the real notebook/report at a useful viewport, then enlarge text.
            app.nb.select(app.tab_mag);app.mag_nb.select(app.tab_mag_design)
            root.geometry('1280x860');root.deiconify();root.update()
            widget=app.mag_report
            first=widget.scroll.content.winfo_children()
            view=widget._view
            widget.render(view);root.update()
            self.assertEqual(first,widget.scroll.content.winfo_children())
            labels=[label for label,_ in widget._wrapped]
            for state in ('success','danger','warning'):
                selected=[x for x in labels if x.cget('foreground')==COLORS[state] and x.cget('font')=='TkHeadingFont']
                self.assertTrue(selected,state)
                self.assertEqual(font.nametofont('TkHeadingFont').actual('weight'),'bold')
            for size,width in ((13,1280),(26,920)):
                app._apply_scale(size/13)
                root.geometry(f'{width}x860');root.update()
                widget.scroll.sync();root.update()
                if width==1280:self.assertGreater(widget.winfo_width(),320)
                self.assertLess(widget.scroll.canvas.yview()[1],.95)
                for card in widget.scroll.content.winfo_children()[1:]:
                    byrow={}
                    for label in card.winfo_children():
                        info=label.grid_info()
                        if int(info.get('columnspan',1))==1:
                            byrow.setdefault(int(info['row']),[]).append(label)
                    for row in byrow.values():
                        if len(row)==2:
                            left,right=sorted(row,key=lambda w:w.winfo_x())
                            self.assertLessEqual(left.winfo_x()+left.winfo_width(),right.winfo_x())
                root.update()
            self.assertEqual(errors,[])
            # Exercise the real desktop calculation path as well as service normalization.
            from loss_model import compute_design
            p=app.get_params();r=compute_design(p)
            self.assertEqual(r['mag']['transformer']['gap_design']['mu_r'],2400.)
            app.params['core_material'].set('N87')
            saved=app._config_dict()
            app.params['core_material'].set('DMR44');app._apply_config(saved)
            self.assertEqual(app.get_params()['core_material'],'N87')
        finally:
            app._closing=True;app._work_cancel.set()
            from engineering_ui import Tooltip
            Tooltip.hide_all(root)
            for job in root.tk.splitlist(root.tk.call('after','info')):root.after_cancel(job)
            root.destroy()


if __name__=='__main__':unittest.main(verbosity=2)
