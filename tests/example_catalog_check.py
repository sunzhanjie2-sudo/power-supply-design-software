"""One curated example catalog, valid shipped configurations and menu commands."""
import copy
import hashlib
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

    def test_flyback_is_exact_user_configuration(self):
        data=(ROOT/'examples/40W_CCM_3OUT_FLYBACK.json').read_bytes()
        self.assertEqual(hashlib.sha256(data).hexdigest(),
                         '55ac5dc49208f177c997d2f419f808b85bdbdc9fc54e65474d9bdb2b8f6483c1')
        p=load_spec(json.loads(data))
        self.assertEqual([r['Ns'] for r in p['outputs']],[12,5,2])
        self.assertEqual((p['V_in_min'],p['V_in_max']),(20,30))

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
                file_index=next(i for i in range(bar.index('end')+1)
                                if bar.type(i)=='cascade' and bar.entrycget(i,'label').startswith('File'))
                menu=root.nametowidget(bar.entrycget(file_index,'menu'))
                entries=[i for i in range(menu.index('end')+1)
                         if menu.type(i)=='command' and menu.entrycget(i,'label').startswith('示例: ')]
                self.assertEqual(len(entries),6)
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
