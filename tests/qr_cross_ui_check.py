"""Owned real Tk QR matrix editor, save/reopen and corner table integration."""
import copy
import json
from pathlib import Path
import sys
from types import SimpleNamespace
import tkinter as tk
import unittest
from unittest.mock import patch

ROOT=Path(__file__).resolve().parents[1]
sys.path[:0]=[str(ROOT),str(ROOT/'tests')]
from runtime_resources import configure_numeric_threads
configure_numeric_threads()
from qr_coupled_check import fixture
from input_voltage_range import calculate_input_endpoints
import main


class QRCrossUIChecks(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.p=fixture()
        cls.p['outputs'][0]['P_out_min']=45.
        cls.p['outputs'][1]['P_out_min']=.5
        cls.p['V_in_max']=320.
        cls.root=tk.Tk();cls.root.withdraw();cls.errors=[]
        cls.root.report_callback_exception=lambda kind,value,tb:cls.errors.append(str(value))
        cls.schedule=patch.object(main.PowerSupplyAnalyzer,'schedule_update',return_value=None)
        cls.schedule.start()
        cls.app=main.PowerSupplyAnalyzer(cls.root)
        cls.root.unbind('<Configure>')
        for job in cls.root.tk.call('after','info'):cls.root.after_cancel(job)

    @classmethod
    def tearDownClass(cls):
        cls.app._closing=True;cls.app._work_cancel.set()
        for job in cls.root.tk.call('after','info'):cls.root.after_cancel(job)
        cls.root.destroy();cls.schedule.stop()

    def setUp(self):
        self.app._apply_config(copy.deepcopy(self.p))
        self.root.update()

    def test_qr_matrix_enabled_and_cross_page_available(self):
        self.assertTrue(self.app._coupling_supported())
        self.assertTrue(self.app.coupling_enabled.get())
        book=self.app._isolated_result_book
        self.assertNotEqual(book.tab(self.app._cross_page,'state'),'hidden')
        self.assertEqual(self.app.cross_cases['columns'],('id','vin','loads','voltages','frequency','state'))

    def test_scrollable_layout_keeps_case_table_visible_at_large_font(self):
        self.root.attributes('-alpha',0);self.root.deiconify()
        self.root.geometry('1440x900')
        self.app.nb.select(self.app.tab_topology)
        book=self.app._isolated_result_book
        book.select(self.app._cross_page)
        self.root.update()
        # Give the native window manager its normal configure event after
        # mapping. Layout testing must not read the previous frame's size.
        self.root.geometry('1440x900')
        self.root.after(120,self.root.quit);self.root.mainloop()
        # Presentation only; use the public scale mechanism without writing
        # the real user's font preferences or scheduling electrical work.
        with patch.object(self.app,'_refresh_visible_tab',return_value=None):
            self.app._apply_scale(18/13)
            self.root.update()
        self.assertGreater(self.app.cross_cases.winfo_width(),400)
        self.assertGreater(self.app.cross_cases.winfo_height(),90)
        self.assertLess(self.app.cross_detail_text.winfo_rooty()+self.app.cross_detail_text.winfo_height(),
                        self.root.winfo_rooty()+self.root.winfo_height())
        self.root.withdraw();self.app._apply_scale(1.)

    def test_matrix_and_minimum_load_survive_real_serialization(self):
        saved=json.loads(json.dumps(self.app._config_dict()))
        self.app._apply_config(saved)
        current=self.app.get_params()
        self.assertTrue(current['coupling_config']['enabled'])
        self.assertEqual(current['coupling_config']['k'],self.p['coupling_config']['k'])
        self.assertEqual([r['P_out_min'] for r in current['outputs']],[45.,.5])
        self.assertEqual([r['Ns'] for r in current['outputs']],[30.,8.])

    def test_actual_scan_enters_corner_table_and_selection_details(self):
        p=self.app.get_params()
        result=calculate_input_endpoints(p,include_loop=True)
        self.assertTrue(result['cross_regulation']['complete'])
        self.assertTrue(all(c['loop_error'] is None and c['error'] is None for c in result['cases']))
        self.app._snapshot_valid=True;self.app._last={'p':p}
        self.app._finish_cross_regulation(SimpleNamespace(parameters={'p':p},error=None,value=result['cross_regulation']))
        ids=self.app.cross_cases.get_children()
        self.assertEqual(len(ids),8)
        self.app.cross_cases.selection_set(ids[0]);self.app._select_cross_case()
        self.assertIn('实际频率',self.app.cross_detail.get())
        self.assertTrue(self.app.cross_cases.item(ids[0],'values')[4])
        self.assertEqual(self.errors,[])


if __name__=='__main__':unittest.main(verbosity=2)
