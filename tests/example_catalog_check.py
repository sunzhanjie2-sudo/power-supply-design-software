"""One curated example catalog, valid shipped configurations and menu commands."""
import copy
import json
from pathlib import Path
import sys
import unittest
from unittest.mock import patch

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from runtime_resources import configure_numeric_threads
configure_numeric_threads()
from example_catalog import EXAMPLES
from web_app.metadata import read_example,bootstrap
from design_engine.service import calculate_parameters
from design_engine.specification import load_spec


class CatalogChecks(unittest.TestCase):
    def test_curated_isolated_and_three_nonisolated_examples(self):
        self.assertEqual(len(EXAMPLES),6)
        self.assertEqual(bootstrap()['examples'],EXAMPLES)
        self.assertEqual([load_spec(read_example(n))['topology'] for n in EXAMPLES],
                         ['ACF-FORWARD','FLYBACK','QR-FLYBACK','BUCK','BUCK','BOOST'])
        with self.assertRaises(ValueError):read_example('../main.py')

    def test_flyback_preserves_user_requirements_and_winding_structure(self):
        data=(ROOT/'examples/40W_CCM_3OUT_FLYBACK.json').read_bytes()
        p=load_spec(json.loads(data))
        # Device scalars/ratings intentionally change as real components are
        # selected; electrical requirements and user winding arrangement do
        # not. A whole-file SHA would forbid precisely the requested update.
        self.assertEqual([r['Ns'] for r in p['outputs']],[12,5,2])
        self.assertEqual((p['V_in_min'],p['V_in_max']),(20,30))
        self.assertEqual((p['V_out'],p['P_out'],p['f_sw']),(30.,40.,250e3))
        self.assertEqual((p['feedback_mode'],p['feedback_output']),('SSR',1))
        self.assertEqual((p['control_mode'],p['Np'],p['N']),('Peak Current Mode',6,.5))
        self.assertEqual([r['P_out'] for r in p['outputs']],[30.,1.,2.])
        self.assertEqual([r['P_out_min'] for r in p['outputs']],[2.,.3,.5])
        self.assertEqual([r['n_strand_s'] for r in p['outputs']],[30,10,20])
        self.assertEqual([r['parallel_wires_s'] for r in p['outputs']],[1,1,1])
        self.assertEqual((p['d_wire_p'],p['n_strand_p'],p['parallel_wires_p']),(100e-6,40,1))
        self.assertEqual([r['d_wire_s'] for r in p['outputs']],[100e-6]*3)
        winding=p['winding_config']
        self.assertEqual((winding['window_width'],winding['window_height']),(.012,.0033))
        self.assertEqual([(s['winding_id'],s['turns'],s['section_id']) for s in winding['layer_plan']],
                         [('OUT1',6,'OUT1_A'),('P',6,'P_A'),('OUT2',5,'OUT2_A'),('OUT3',2,'OUT3_A'),('OUT1',6,'OUT1_B')])
        self.assertTrue(all(s['winding_style']=='sparse' for s in winding['layer_plan']))
        self.assertEqual(winding['turn_positions'],{})

    def test_compact_chokes_and_both_endpoints(self):
        p=load_spec(read_example('33W_3OUT_ACF_MP6005_COMPACT.json'))
        self.assertEqual([r['L'] for r in p['outputs']],[100e-6,330e-6,47e-6])
        self.assertEqual(p['L'],p['outputs'][0]['L'])
        before=copy.deepcopy(p)
        cases=calculate_parameters(p,analysis='endpoints',include_loop=True,
                                   include_cross_regulation=False).runtime_bundle()['cases']
        self.assertEqual(p,before)
        for case in cases:
            self.assertFalse(case.get('error'));self.assertFalse(case.get('loop_error'))
            op=case['result']['op']
            self.assertTrue(op['acf_model']['current_mesh_verified'])
            self.assertTrue(all(c['mode']=='CCM' and c['I_L_pk']<2 for c in op['output_ops']))

    def test_desktop_menu_callbacks_load_their_own_example(self):
        import tkinter as tk
        import main
        root=tk.Tk();root.withdraw()
        try:
            with patch.object(main.PowerSupplyAnalyzer,'schedule_update',return_value=None):
                app=main.PowerSupplyAnalyzer(root)
                bar=root.nametowidget(root.cget('menu'))
                example_index=next(i for i in range(bar.index('end')+1)
                                   if bar.type(i)=='cascade' and bar.entrycget(i,'label')=='示例')
                menu=root.nametowidget(bar.entrycget(example_index,'menu'))
                entries=[i for i in range(menu.index('end')+1)
                         if menu.type(i)=='command']
                self.assertEqual(len(entries),6)
                self.assertEqual([menu.entrycget(i,'label') for i in entries],list(EXAMPLES.values()))
                with patch.object(app,'load_isolated_example') as loader:
                    for index,name in zip(entries,EXAMPLES):
                        menu.invoke(index)
                        loader.assert_called_with(name)
                for name,topology in zip(EXAMPLES,('ACF-FORWARD','FLYBACK','QR-FLYBACK','BUCK','BUCK','BOOST')):
                    app.load_isolated_example(name)
                    p=app.get_params()
                    self.assertEqual(p['topology'],topology)
                    if topology in ('ACF-FORWARD','FLYBACK'):
                        self.assertEqual(len(p['outputs']),3)
                    if topology=='ACF-FORWARD':
                        self.assertEqual([r['L'] for r in p['outputs']],[100e-6,330e-6,47e-6])
        finally:
            for job in root.tk.splitlist(root.tk.call('after','info')):
                try:root.after_cancel(job)
                except tk.TclError:pass
            root.destroy()


if __name__=='__main__':unittest.main()
