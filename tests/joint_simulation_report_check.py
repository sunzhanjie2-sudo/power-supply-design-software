"""Verify joint report evidence gaps and single-package Word composition."""
import base64
from copy import deepcopy
from io import BytesIO
import json
from pathlib import Path
import sys
import tempfile
import unittest
from zipfile import ZipFile

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from docx import Document
from docx.oxml.ns import qn
from PIL import Image

from joint_simulation_report import write_joint_report, _field_images


def png():
    stream = BytesIO()
    Image.new('RGB', (240, 90), 'white').save(stream, format='PNG')
    return stream.getvalue()


def field_record(report):
    return dict(topology='FLYBACK', report_path=str(report), field={
        'port_order': ['P', 'OUT1'], 'L_ports_H': [[100e-6, 45e-6], [45e-6, 25e-6]],
        'k_ports': [[1, .9], [.9, 1]], 'primary_self_H': 100e-6,
        'primary_short_H': 19e-6}, validation={}, model_conditions={
        'material': {'name': 'TEST', 'relative_permeability': 2400, 'temperature_C': 25, 'bias_current_A': 0},
        'core': {'calculator_core_model': 'TEST', 'total_gap_m': .001},
        'solver': {'mesh_profile': 'test', 'air_radius_m': .05},
        'bobbin': {'axial_window_m': .012, 'radial_window_m': .005},
        'layers': [['P', 6], ['OUT1', 12]], 'windings': [['P', 6], ['OUT1', 12]]})


def failed_spice():
    from spice_export import normalize_settings
    return dict(schema='powerdesign-spice-comparison-2', model='UNIT-TEST', topology='FLYBACK',
                settings=normalize_settings({}), cases=[dict(
                    id='Vinmin_标称负载', voltage=20, fault_test=False, complete=False,
                    error='本测试模拟超时，不是实际LTspice数据', measurements={}, loop={}, cross={})])


class JointReportChecks(unittest.TestCase):
    def test_early_failure_remains_visible_without_invented_evidence(self):
        with tempfile.TemporaryDirectory(dir=ROOT / 'artifacts') as tmp:
            path = Path(tmp) / '联合.docx'
            record = dict(status='failed', stages=[dict(name='场仿真', status='failed', error='窗口超限')])
            receipt = write_joint_report(path, record)
            text = '\n'.join(p.text for p in Document(path).paragraphs)
            self.assertIn('电磁仿真，电路仿真，设计计算联合报告', text)
            tables = '\n'.join(c.text for t in Document(path).tables for r in t.rows for c in r.cells)
            self.assertIn('窗口超限', tables)
            self.assertIn('没有取得本次有效场解', text)
            self.assertIn('电路仿真尚未取得完整证据', text)
            self.assertTrue(receipt['incomplete'])
            self.assertFalse(receipt['circuit_evidence_available'])

    def test_local_and_embedded_field_images_are_embedded_not_linked(self):
        with tempfile.TemporaryDirectory(dir=ROOT / 'artifacts') as tmp:
            folder = Path(tmp)
            (folder / 'field.png').write_bytes(png())
            report = folder / 'report.html'
            report.write_text('<img src="field.png" alt="本地场图"><img src="data:image/png;base64,' +
                              base64.b64encode(png()).decode() + '" alt="内嵌场图">' +
                              '<img src="https://example.com/private.png" alt="远程图">' +
                              '<img src="../outside.png" alt="越界图">', 'utf-8')
            images, notes = _field_images(report)
            self.assertEqual(len(images), 2)
            self.assertEqual(len(notes), 2)
            record = dict(status='partial', field=field_record(report), margin={
                'factor': 1.25, 'off_diagonal_scale': .97, 'port_order': ['P', 'OUT1'],
                'primary_self_H': 100e-6, 'original_primary_short_H': 19e-6,
                'adopted_primary_short_H': 23.75e-6,
                'adopted_L_ports_H': [[100e-6, 43.660e-6], [43.660e-6, 25e-6]],
                'adopted_k_ports': [[1, .8732], [.8732, 1]]})
            path = folder / '联合.docx'
            result = write_joint_report(path, record)
            self.assertEqual(result['figures'], 2)
            self.assertGreaterEqual(result['equations'], 2)
            with ZipFile(path) as archive:
                xml = archive.read('word/document.xml').decode('utf-8')
                self.assertNotIn('r:link=', xml)
                self.assertIn('r:embed=', xml)
            tables = '\n'.join(c.text for t in Document(path).tables for row in t.rows for c in row.cells)
            self.assertIn('23.75', tables)
            self.assertIn('尚未验证', '\n'.join(p.text for p in Document(path).paragraphs))

    def test_spice_append_preserves_styles_sections_equations_and_footer(self):
        from docx_layout import new_document, equation, figure
        from spice_comparison_report import write_report
        with tempfile.TemporaryDirectory(dir=ROOT / 'artifacts') as tmp:
            doc = new_document('组合验证', '测试', '前一章节')
            equation(doc, 'P=V×I')
            figure(doc, png(), '第一节图片')
            original_size = doc.styles['Normal'].font.size
            original_footer = doc.sections[0].footer.part.partname
            write_report(None, failed_spice(), document=doc, save=False)
            self.assertEqual(doc.styles['Normal'].font.size, original_size)
            self.assertEqual(len(doc.sections), 2)
            self.assertEqual(doc.sections[0].page_width, 7772400)
            self.assertGreater(doc.sections[-1].page_width, doc.sections[-1].page_height)
            self.assertNotEqual(doc.sections[-1].footer.part.partname, original_footer)
            self.assertGreaterEqual(len(doc.element.xpath('.//m:oMath')), 2)
            self.assertIn('本测试模拟超时', '\n'.join(p.text for p in doc.paragraphs))
            path = Path(tmp) / '组合.docx'
            doc.save(path)
            reopened = Document(path)
            self.assertEqual(len(reopened.sections), 2)
            ids = [n.get('id') for n in reopened.element.xpath('.//wp:docPr')]
            self.assertEqual(len(ids), len(set(ids)))
            for node in reopened.element.iter():
                rid = node.get(qn('r:embed'))
                if rid:
                    self.assertIn(rid, reopened.part.rels)

    def test_complete_design_snapshot_is_consumed_without_recomputation(self):
        from unittest.mock import patch
        from design_engine.service import calculate
        config = json.loads((ROOT / 'examples/40W_CCM_FLYBACK.json').read_text('utf-8'))
        run = calculate(config, analysis='endpoints', include_loop=True,
                        include_efficiency=False, include_cross_regulation=False)
        before = deepcopy(config)
        record = dict(status='partial', stages=[dict(name='电路仿真', status='failed', error='测试超时')],
                      circuit={'evidence': failed_spice()})
        with tempfile.TemporaryDirectory(dir=ROOT / 'artifacts') as tmp, patch('design_engine.service.calculate', side_effect=AssertionError('renderer must not calculate')):
            path = Path(tmp) / '联合.docx'
            receipt = write_joint_report(path, record, design_run=run)
            doc = Document(path)
            text = '\n'.join(p.text for p in doc.paragraphs)
            self.assertIn('Vinmin', text)
            self.assertIn('Vinmax', text)
            self.assertIn('本测试模拟超时', text)
            self.assertGreater(receipt['figures'], 10)
            self.assertGreater(receipt['equations'], 5)
            self.assertGreaterEqual(receipt['sections'], 3)
            self.assertTrue(receipt['complete_design_snapshot'])
            self.assertTrue(receipt['incomplete'])
        self.assertEqual(config, before)


if __name__ == '__main__':
    unittest.main(verbosity=2)
