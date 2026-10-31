"""N-branch physical limits, propagation, real GUI and complete report rows."""
import copy,json,sys,tempfile,unittest
from pathlib import Path
from unittest.mock import patch
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
from runtime_resources import configure_numeric_threads
configure_numeric_threads()
import numpy as np
from capacitor_banks import bank,normalize,total,validate
from design_engine.specification import load_spec
from design_engine.service import calculate_parameters,export_report
from capripple import capacitor_ripple_analysis
from loss_model import compute_design
from output_capacitors import build_output_filters
from spice_export import project_files


def example(name='24W_BUCK_VM_TPS40200.json'):
    return load_spec(json.loads((ROOT/'examples'/name).read_text(encoding='utf-8')))


def caps(n):return [dict(C=(100+10*i)*1e-6,ESR=(15+2*i)*1e-3,ESL=(1+i)*1e-9) for i in range(n)]


class CapacitorBankChecks(unittest.TestCase):
    def test_legacy_pair_and_invalid_new_bank(self):
        p=example();self.assertEqual(len(bank(p)),2)
        self.assertEqual(bank(normalize(p)),bank(p))
        for bad in ([],{},[dict(C=0,ESR=.01)],[dict(C=1e-6,ESR=-1)],[dict(C=1e-6,ESL=float('nan'))]):
            with self.assertRaises(ValueError):validate(bad)

    def test_equal_parallel_branch_current_and_loss(self):
        t=np.arange(2048)/2048/50000*2;i=np.sin(2*np.pi*50000*t)
        a=capacitor_ripple_analysis(t,i,i,50000,[dict(C=1e-4,ESR=.03,ESL=1e-9)]*5,[dict(C=1e-4,ESR=.03,ESL=1e-9)]*7)
        for side,n in (('input',5),('output',7)):
            for cap in a[side]['caps']:self.assertAlmostEqual(cap['total'],np.sqrt(.5)/n)
            self.assertAlmostEqual(sum(c['ESR']*c['total']**2 for c in a[side]['caps']),.03*.5/n)

    def test_each_different_esr_branch_has_a_state(self):
        p=example();p['output_capacitors']=caps(5)
        f=build_output_filters([p],[6],[12])
        self.assertEqual(f.A.shape,(5,5));self.assertEqual(len(f.banks[0]['branches']),5)
        p['output_capacitors'][1]['ESR']=0.;p['output_capacitors'][3]['ESR']=0.
        self.assertEqual(build_output_filters([p],[6],[12]).A.shape,(4,4))

    def test_single_bank_reaches_models_losses_bom_and_spice(self):
        p=example();p.update(input_capacitors=caps(3),output_capacitors=caps(5))
        p=load_spec(p);r=compute_design(p)
        from design_engine.service import validate_spec
        self.assertTrue(validate_spec(p)['ok'])
        self.assertEqual(len(r['capacitors']['input']['caps']),3)
        self.assertEqual(len(r['capacitors']['output']['caps']),5)
        self.assertEqual(r['op']['niso_model']['capacitor_banks'][0]['states'],5)
        from component_management import component_registry
        refs={row['ref'] for row in component_registry(p)}
        self.assertIn('C_IN3',refs);self.assertIn('C_O5',refs)
        f=project_files(p)
        self.assertIn(b'XC_IN3',f['support.inc']);self.assertIn(b'XC_O1_5',f['support.inc'])
        from matplotlib.figure import Figure
        from topology_diagram import draw_topology
        draw_topology(Figure().subplots(),p,r['op'])

    def test_all_three_isolated_outputs_keep_independent_banks(self):
        p=example('40W_CCM_3OUT_FLYBACK.json');p['coupling_config']['enabled']=False
        p['input_capacitors']=caps(4)
        for i,row in enumerate(p['outputs']):row['output_capacitors']=caps(i+3)
        p=load_spec(p);r=compute_design(p)
        self.assertEqual([len(row['capacitors']['output']['caps']) for row in r['outputs']],[3,4,5])
        f=project_files(p);self.assertIn(b'XC_O3_5',f['support.inc'])
        from matplotlib.figure import Figure
        from topology_diagram import draw_topology
        draw_topology(Figure().subplots(),p,r['op'])

    def test_word_and_excel_include_every_capacitor(self):
        p=example();p.update(input_capacitors=caps(3),output_capacitors=caps(4))
        run=calculate_parameters(p,analysis='endpoints',include_efficiency=True,include_cross_regulation=False)
        with tempfile.TemporaryDirectory() as folder:
            from docx import Document
            for suffix in ('.docx','.xlsx'):
                path=Path(folder)/('bank'+suffix)
                result=export_report(run,path);self.assertEqual(result['successful_cases'],2)
            doc=Document(Path(folder)/'bank.docx')
            text='\n'.join(c.text for table in doc.tables for row in table.rows for c in row.cells)
            self.assertIn('输入 C3',text);self.assertIn('输出 C4',text);self.assertIn('C_O4',text)

    def test_tk_edit_save_reload_invalid_draft_and_chart(self):
        import tkinter as tk
        import main
        root=tk.Tk();root.withdraw()
        try:
            with patch.object(main.PowerSupplyAnalyzer,'schedule_update',return_value=None):
                app=main.PowerSupplyAnalyzer(root);app._apply_config(example())
                for side,n in (('input',3),('output',5)):
                    e=app._cap_editors[side];e.count.set(str(n));e.resize()
                self.assertEqual(len(app.get_params()['output_capacitors']),5)
                saved=app._config_dict();app._apply_config(saved)
                self.assertEqual(len(app.get_params()['input_capacitors']),3)
                self.assertTrue(app.update_all());app._draw_cap(app._last['res']['capacitors'])
                self.assertEqual(len(app.ax_cap_band),8)
                e=app._cap_editors['output'];e.variables['C'].set('bad')
                with self.assertRaises(ValueError):app.get_params()
                e.variables['C'].set('100')
                app._apply_config(example('40W_CCM_FLYBACK.json'))
                e=app._cap_editors['output'];e.count.set('5');e.resize()
                app.multi_enabled.set(True)
                self.assertEqual(len(app.get_params()['outputs'][0]['output_capacitors']),5)
                app._apply_config(example('40W_CCM_3OUT_FLYBACK.json'))
                e=app._inline_cap_editors[2];e.count.set('4');e.resize()
                self.assertEqual(len(app.get_params()['outputs'][2]['output_capacitors']),4)
        finally:
            if 'app' in locals():app._calculation_worker.close()
            for timer in root.tk.splitlist(root.tk.call('after','info')):
                try:root.after_cancel(timer)
                except tk.TclError:pass
            root.destroy()

if __name__=='__main__':unittest.main(verbosity=2)
