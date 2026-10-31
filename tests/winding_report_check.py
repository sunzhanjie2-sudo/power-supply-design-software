"""Geometry in Word uses the same assessment, independent numerical snapshot."""
from pathlib import Path
import copy
import sys
import unittest
from unittest.mock import patch
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from docx import Document
from docx_layout import new_document
from winding_report import add_winding_snapshot,add_winding_reference
from winding_layout import assess_winding_window,transformer_windings
from design_api import load_spec
from config_io import read_default_config
from loss_model import compute_design


class WindingReportChecks(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.p=load_spec(read_default_config());cls.r=compute_design(cls.p)

    def test_legacy_unconfigured_and_nonisolated_skip_only_the_new_section(self):
        doc=new_document('检查','测试','测试')
        self.assertIsNone(add_winding_snapshot(doc,self.p,self.r))
        self.assertEqual(len(doc.inline_shapes),0)
        self.assertIsNone(add_winding_snapshot(doc,dict(winding_config=dict(window_width=.01,window_height=.005)),dict(mag={})))

    def test_shared_geometry_and_embedded_plot_do_not_mutate_parameters(self):
        p=dict(self.p,winding_config=dict(window_width=.012,window_height=.006))
        before=copy.deepcopy(p)
        doc=new_document('检查','测试','测试')
        actual=add_winding_snapshot(doc,p,self.r)
        expected=assess_winding_window(transformer_windings(self.r),p['winding_config'])
        self.assertEqual(actual,expected);self.assertEqual(p,before)
        self.assertEqual(len(doc.inline_shapes),1);self.assertEqual(len(doc.tables),3)
        self.assertIn('几何可放下',' '.join(c.text for t in doc.tables for row in t.rows for c in row.cells))

    def test_equivalent_bundle_inputs_are_recorded_without_adding_copper(self):
        result=dict(mag=dict(transformer=dict(ok=True,Np=3,n_strand_p=60,d_wire_p=.1e-3,
                    Ns=2,n_strand_s=1,d_wire_s=.2e-3)))
        p=dict(winding_config=dict(window_width=.02,window_height=.01,
            overrides=dict(P=dict(parallel_bundles=3,packing_factor=.8,wire_type='litz',
                flatten_ratio=1.5,winding_style='dense_right',turns_per_layer=2),
                OUT1=dict(wire_type='solid',winding_style='dense_left'))))
        before=copy.deepcopy(p)
        doc=new_document('检查','测试','测试')
        actual=add_winding_snapshot(doc,p,result)
        self.assertEqual(p,before)
        primary=actual['windings'][0]
        self.assertEqual(primary['conductor_count'],180)
        self.assertEqual(primary['bundle_count'],9)
        self.assertAlmostEqual(primary['bundle_width']*primary['bundle_height'],primary['bundle_diameter']**2)
        cells='\n'.join(c.text for t in doc.tables for row in t.rows for c in row.cells)
        text='\n'.join(p.text for p in doc.paragraphs)
        self.assertIn('3 × 20',cells);self.assertIn('密绕靠右',cells)
        self.assertIn('密绕靠左',cells);self.assertIn('估算 k=0.8',cells)
        self.assertIn('电气总股数为 60',text);self.assertIn('不逐根绘制',text)
        for t in doc.tables:
            self.assertAlmostEqual(sum(col.width.inches for col in t.columns),7.1,places=3)

    def test_measured_bundle_diameter_and_legacy_rectangle_are_labelled(self):
        result=dict(mag=dict(transformer=dict(ok=True,Np=3,n_strand_p=4,d_wire_p=.1e-3,
                    Ns=2,n_strand_s=1,d_wire_s=.2e-3)))
        for override,expected in ((dict(bundle_diameter=.4e-3),'指定外径'),
                                  (dict(strand_columns=2),'旧矩形束')):
            p=dict(winding_config=dict(window_width=.01,window_height=.01,overrides=dict(P=override)))
            doc=new_document('检查','测试','测试');add_winding_snapshot(doc,p,result)
            cells='\n'.join(c.text for t in doc.tables for row in t.rows for c in row.cells)
            self.assertIn(expected,cells)

    def test_interleaved_snapshot_keeps_logical_winding_and_all_physical_layers(self):
        result=dict(mag=dict(transformer=dict(ok=True,Np=6,n_strand_p=1,d_wire_p=.2e-3,
                    Ns=2,n_strand_s=1,d_wire_s=.3e-3)))
        p=dict(winding_config=dict(window_width=.01,window_height=.01,
            overrides=dict(P=dict(winding_style='dense_right',turns_per_layer=3)),
            layer_plan=[dict(winding_id='P',turns=3,winding_style='dense_left'),
                        dict(winding_id='OUT1',turns=2),dict(winding_id='P',turns=3)]))
        before=copy.deepcopy(p)
        doc=new_document('检查','测试','测试')
        actual=add_winding_snapshot(doc,p,result)
        expected=assess_winding_window(transformer_windings(result),p['winding_config'])
        self.assertEqual(actual,expected);self.assertEqual(p,before)
        self.assertEqual(len(actual['windings']),2)
        self.assertEqual(actual['total_layer_count'],3)
        self.assertEqual(actual['windings'][0]['physical_layer_indices'],[1,3])
        self.assertEqual(actual['conductor_count'],8)
        self.assertAlmostEqual(actual['required_height'],1.29e-3)
        self.assertEqual(len(doc.tables),4);self.assertEqual(len(doc.inline_shapes),1)
        physical=doc.tables[3]
        self.assertEqual(len(physical.rows),4)
        self.assertEqual([row.cells[1].text for row in physical.rows[1:]],['P','OUT1','P'])
        self.assertEqual([row.cells[2].text for row in physical.rows[1:]],['3','2','3'])
        self.assertEqual([row.cells[3].text for row in physical.rows[1:]],['密绕靠左','疏绕','密绕靠右'])
        self.assertEqual(physical.rows[2].cells[4].text,'0.15\n异绕组间')
        self.assertEqual(physical.rows[3].cells[4].text,'0.15\n异绕组间')
        self.assertEqual(len(physical.rows[0]._tr.xpath('./w:trPr/w:tblHeader')),1)
        for t in doc.tables:
            self.assertAlmostEqual(sum(col.width.inches for col in t.columns),7.1,places=3)
        self.assertIn('1、3',doc.tables[2].rows[1].cells[2].text)
        self.assertIn('不自动评估跨线','\n'.join(p.text for p in doc.paragraphs))

    def test_interleaved_report_counts_adjacent_same_and_different_barriers(self):
        result=dict(mag=dict(transformer=dict(ok=True,Np=6,n_strand_p=1,d_wire_p=.2e-3,
                    Ns=2,n_strand_s=1,d_wire_s=.3e-3)))
        p=dict(winding_config=dict(window_width=.01,window_height=.01,
            layer_plan=[dict(winding_id='P',turns=2),dict(winding_id='P',turns=1),
                        dict(winding_id='OUT1',turns=2),dict(winding_id='P',turns=3)]))
        doc=new_document('检查','测试','测试')
        actual=add_winding_snapshot(doc,p,result)
        physical=doc.tables[3]
        self.assertEqual(physical.rows[2].cells[4].text,'0.05\n同绕组层间')
        self.assertEqual(physical.rows[3].cells[4].text,'0.15\n异绕组间')
        self.assertEqual(physical.rows[4].cells[4].text,'0.15\n异绕组间')
        self.assertAlmostEqual(actual['required_height'],1.57e-3)
        self.assertAlmostEqual(actual['windings'][0]['buildup'],.74e-3)
        self.assertGreater(actual['windings'][0]['stack_span'],actual['windings'][0]['buildup'])

    def test_native_window_equations_are_not_rasterized(self):
        doc=new_document('检查','测试','测试');add_winding_reference(doc)
        self.assertGreaterEqual(len(doc.element.xpath('.//m:oMath')),22)
        self.assertGreaterEqual(len(doc.element.xpath('.//m:f')),7)
        self.assertGreaterEqual(len(doc.element.xpath('.//m:rad')),1)
        native_text=''.join(doc.element.xpath('.//m:t/text()'))
        for token in ('pack','max','occ','D'):
            self.assertIn(token,native_text)
        self.assertIn('0.75 只是可编辑', '\n'.join(p.text for p in doc.paragraphs))
        self.assertIn('手动物理层序与交错绕制', '\n'.join(p.text for p in doc.paragraphs))
        self.assertIn('ℓ−1',native_text)
        self.assertEqual(len(doc.inline_shapes),0)

    def test_full_export_with_precomputed_efficiency_does_not_resolve_load_points(self):
        from report_docx import export_design_docx
        from plants import build_loop_models
        p=dict(self.p,winding_config=dict(window_width=.012,window_height=.006))
        out=Path('_tmp_winding_qa');out.mkdir(exist_ok=True)
        target=out/'winding_design_report.docx'
        curve=dict(fracs=[.1,.5,1.],etas=[.70,.85,self.r['eta']],modes=['DCM','CCM','CCM'],failures=[])
        models,_=build_loop_models(self.p,self.r['op'])
        with patch('report_docx.compute_design',side_effect=AssertionError('must use precomputed curve')):
            export_design_docx(target,p,self.r['op'],self.r['wf'],self.r,models=models,efficiency_curve=curve)
        doc=Document(target)
        self.assertIn('5.2  变压器可绕制几何评估','\n'.join(p.text for p in doc.paragraphs))
        self.assertGreaterEqual(len(doc.inline_shapes),11)

    def test_full_interleaved_export_preserves_four_physical_layers(self):
        """Internal layout fixture only: its mock efficiency is not design data."""
        from report_docx import export_design_docx
        from plants import build_loop_models
        plan=[dict(winding_id='P',turns=3,winding_style='dense_left'),
              dict(winding_id='OUT1',turns=9,winding_style='dense_right'),
              dict(winding_id='P',turns=3,winding_style='sparse'),
              dict(winding_id='OUT1',turns=3,winding_style='dense_left')]
        p=dict(self.p,winding_config=dict(window_width=.012,window_height=.006,layer_plan=plan))
        assessment=assess_winding_window(transformer_windings(self.r),p['winding_config'])
        self.assertEqual(assessment['total_layer_count'],4)
        self.assertEqual({r['id']:r['turns'] for r in assessment['windings']},{'P':6,'OUT1':12})
        self.assertEqual([r['physical_layer_indices'] for r in assessment['windings']],[[1,3],[2,4]])
        out=Path('_tmp_interleaved_winding_qa');out.mkdir(exist_ok=True)
        target=out/'interleaved_design_report.docx'
        # Deliberately precomputed test points exercise the export interface;
        # never hand this QA document to a user as an engineering result.
        curve=dict(fracs=[.1,.5,1.],etas=[.70,.85,self.r['eta']],modes=['DCM','CCM','CCM'],failures=[])
        models,_=build_loop_models(self.p,self.r['op'])
        before=copy.deepcopy(p)
        with patch('report_docx.compute_design',side_effect=AssertionError('must use precomputed QA curve')):
            export_design_docx(target,p,self.r['op'],self.r['wf'],self.r,models=models,efficiency_curve=curve)
        self.assertEqual(p,before)
        doc=Document(target)
        self.assertIn('5.2  变压器可绕制几何评估','\n'.join(p.text for p in doc.paragraphs))
        physical=[t for t in doc.tables if [c.text for c in t.rows[0].cells][:3]==['物理层号','绕组','本层匝数']]
        self.assertEqual(len(physical),1)
        physical=physical[0]
        self.assertEqual(len(physical.rows),5)
        self.assertEqual([r.cells[1].text for r in physical.rows[1:]],['P','OUT1','P','OUT1'])
        self.assertEqual([r.cells[2].text for r in physical.rows[1:]],['3','9','3','3'])
        self.assertEqual(sum(int(r.cells[2].text) for r in physical.rows[1:] if r.cells[1].text=='P'),6)
        self.assertEqual(sum(int(r.cells[2].text) for r in physical.rows[1:] if r.cells[1].text=='OUT1'),12)
        self.assertEqual(len(physical.rows[0]._tr.xpath('./w:trPr/w:tblHeader')),1)
        self.assertGreaterEqual(len(doc.inline_shapes),11)


if __name__=='__main__':unittest.main(verbosity=2)
