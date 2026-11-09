"""Validate the worked documentation evidence and editable Word additions.

Run the evidence collector first after changing a numerical dependency. This
check independently verifies each RL segment with an augmented matrix
exponential, then checks charges, balances, corner grouping and Word structure.
"""
from pathlib import Path
import hashlib
import sys
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from runtime_resources import configure_numeric_threads
configure_numeric_threads()
import numpy as np
from scipy.linalg import expm
from docx import Document
from docx.oxml.ns import qn
from docs.update_cross_regulation_documents import (
    load_data, TARGETS, QA, START, END, update_document,
)


class WorkedExampleChecks(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.data = load_data()
        cls.inputs = cls.data['focus']['inputs']
        cls.final = cls.data['focus']['final']

    def test_geometry_reference_and_load(self):
        d, p, f = self.data, self.inputs, self.final
        geom = d['geometry']; turns = np.array(geom['turns'])
        copper = np.array(geom['strands'])*np.pi*np.array(geom['diameter_m'])**2/4
        dcr = d['resistivity_ohm_m']*geom['MLT_m']*turns/copper
        np.testing.assert_allclose(dcr, p['dcr'], rtol=1e-13)
        self_l = 8e-6*(turns/turns[0])**2
        coupling = np.full((4, 4), .995); np.fill_diagonal(coupling, 1.)
        matrix = np.sqrt(np.outer(self_l, self_l))*coupling
        np.testing.assert_allclose(matrix, p['matrix'], rtol=1e-13)
        self.assertGreater(np.linalg.eigvalsh(matrix).min(), 0)
        refs = turns[1:]/turns[1]*(30+.7+.7)-.7-.7
        np.testing.assert_allclose(refs, p['target'], atol=1e-13)
        np.testing.assert_allclose(refs**2/p['rated'], f['load_ohm'], rtol=1e-13)
        np.testing.assert_allclose(np.array(f['output_cap_V'])-.7,
                                   f['output_port_V'], rtol=1e-13)

    def test_segment_equations_and_balances(self):
        p, f = self.inputs, self.final
        total_q = np.zeros(4); elapsed = 0.
        for segment in f['segments']:
            self.assertAlmostEqual(segment['start_s'], elapsed, places=15)
            active = segment['active']; count = len(active)
            inductance = np.array(p['matrix'])[np.ix_(active, active)]
            resistance = np.array(p['dcr'])
            if segment['on']: resistance[0] += p['ron']+p['rs']
            voltage = np.r_[p['vin'] if segment['on'] else -p['clamp'],
                            -np.array(f['output_cap_V'])-p['vf']][active]
            generator = np.zeros((2*count+1, 2*count+1))
            generator[:count, :count] = -np.linalg.solve(inductance, np.diag(resistance[active]))
            generator[:count, -1] = np.linalg.solve(inductance, voltage)
            generator[count:2*count, :count] = np.eye(count)
            initial = np.r_[np.array(segment['current_start_A'])[active], np.zeros(count), 1.]
            duration = segment['end_s']-segment['start_s']
            evolved = expm(generator*duration) @ initial
            np.testing.assert_allclose(evolved[:count], np.array(segment['current_end_A'])[active],
                                       rtol=2e-8, atol=1e-10)
            np.testing.assert_allclose(evolved[count:2*count], np.array(segment['charge_C'])[active],
                                       rtol=2e-8, atol=1e-16)
            total_q += segment['charge_C']; elapsed = segment['end_s']
        self.assertAlmostEqual(elapsed, p['period'], places=15)
        np.testing.assert_allclose(total_q[1:], f['output_charge_C'], atol=1e-16)
        np.testing.assert_allclose(total_q[1:]/p['period'],
            np.array(f['output_port_V'])/f['load_ohm'], rtol=2e-9, atol=2e-12)
        self.assertLess(max(abs(x) for x in f['normalized_residual']), 2e-5)
        power_error = f['input_power_W']-sum(f['output_power_W'])-sum(f['rl_losses_W'].values())
        self.assertAlmostEqual(power_error, f['energy_residual_W'], places=13)
        self.assertLess(abs(power_error), max(.001, .002*f['input_power_W']))

    def test_all_corners_and_statistics(self):
        cases = self.data['result']['cases']
        self.assertEqual({c['id'] for c in cases}, {f'X{i:03d}' for i in range(1, 17)})
        self.assertEqual(len({(c['V_in'], *c['powers']) for c in cases}), 16)
        for j, summary in enumerate(self.data['result']['summary']):
            values = [c['voltages'][j] for c in cases]; ref = self.inputs['target'][j]
            groups = {}
            for c in cases: groups.setdefault((c['V_in'], c['powers'][j]), []).append(c['voltages'][j])
            cross = max(100*(max(v)-min(v))/ref for v in groups.values())
            self.assertAlmostEqual(cross, summary['cross_only_pct'], places=10)
            self.assertAlmostEqual(100*(max(values)-min(values))/ref, summary['span_pct'], places=10)
            self.assertAlmostEqual(min(values), summary['V_min'], places=12)
            self.assertAlmostEqual(max(values), summary['V_max'], places=12)
        final = next(c for c in cases if c['id']=='X004')
        np.testing.assert_allclose(final['voltages'], self.final['output_port_V'], atol=1e-12)
        focus = self.data['focus']
        self.assertEqual(len(focus['accepted']), focus['solver']['accepted_steps'])
        np.testing.assert_allclose(focus['accepted'][-1]['residual'], self.final['normalized_residual'], atol=1e-12)

    def test_editable_equations_complete_tables_and_idempotence(self):
        for kind, path in TARGETS.items():
            with self.subTest(kind=kind):
                doc = Document(path)
                start = doc.element.xpath(f'.//w:bookmarkStart[@w:name="{START}"]')
                end = doc.element.xpath(f'.//w:bookmarkStart[@w:name="{END}"]')
                self.assertEqual((len(start), len(end)), (1, 1))
                body = list(doc.element.body)
                addition = body[body.index(start[0].getparent())+1:body.index(end[0].getparent())]
                maths = [m for node in addition for m in node.iter(qn('m:oMath'))]
                self.assertEqual(len(maths), 42)
                matrix = [m for node in addition for m in node.iter(qn('m:m'))]
                self.assertEqual(len(matrix), 1)
                self.assertEqual(len(matrix[0].findall(qn('m:mr'))), 4)
                denominator = maths[35].find('.//'+qn('m:den'))
                denominator_text = ''.join(denominator.itertext())
                self.assertIn('max', denominator_text)
                self.assertIn('0.01', denominator_text)
                tables = [n for n in addition if n.tag==qn('w:tbl')]
                self.assertEqual(len(tables), 13)
                row_counts = [len(t.findall(qn('w:tr'))) for t in tables]
                self.assertIn(34, row_counts)  # initial plus 32 accepted updates
                self.assertIn(17, row_counts)  # all corners
                before = (len(doc.paragraphs),len(doc.tables),len(doc.inline_shapes),len(doc.element.xpath('.//m:oMath')))
                if (QA/'x004_current.png').exists() and (QA/'x004_convergence.png').exists():
                    update_document(doc, kind, self.data)  # in-memory only
                    self.assertEqual(before, (len(doc.paragraphs),len(doc.tables),len(doc.inline_shapes),len(doc.element.xpath('.//m:oMath'))))
                # When the pre-edit local baseline exists, protect original math and figures.
                backup = QA/'before'/path.name
                if backup.exists():
                    original = Document(backup)
                    self.assertEqual(before[2], len(original.inline_shapes)+2)
                    self.assertEqual(before[3], len(original.element.xpath('.//m:oMath'))+42)
                    self.assertTrue(set(hashlib.sha256(s._inline.xml.encode()).hexdigest() for s in original.inline_shapes)
                        .issubset(set(hashlib.sha256(s._inline.xml.encode()).hexdigest() for s in Document(path).inline_shapes)))


if __name__ == '__main__': unittest.main(verbosity=2)
