"""Module-first simulation comparison keeps endpoint identity and evidence gaps."""
from pathlib import Path
import sys,unittest
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
from docx import Document
from docx_layout import table
from spice_comparison_report import _endpoint,_render_endpoint_modules

class Pairing(unittest.TestCase):
 def render(self,modules):
  doc=Document()
  _render_endpoint_modules(doc,modules,
   lambda h,r,w:table(doc,h,r,[x/2.54 for x in w]),
   lambda t:doc.add_paragraph(t),lambda t:doc.add_heading(t,1))
  return doc
 def module(self,endpoint,value,voltage=30,complete=True):
  return dict(case=dict(id=endpoint+'_标称负载',voltage=voltage,complete=complete,error='实际超时'),
   title='原边电流与控制过程',blocks=[dict(kind='table',headers=['指标','单位','设计计算','LTspice 实测','偏差','判定口径'],rows=[('峰值','A',value,value+.1,'+1%','待复核')])])
 def test_equal_voltage_keeps_explicit_endpoint_values(self):
  doc=self.render([self.module('Vinmin',10),self.module('Vinmax',20)])
  self.assertEqual(len([p for p in doc.paragraphs if p.style.name=='Heading 1']),1)
  data=doc.tables[1].rows[1].cells
  self.assertEqual(data[2].text,'10');self.assertEqual(data[5].text,'20')
  self.assertIn('Vinmin',doc.tables[1].rows[0].cells[2].text)
 def test_failed_side_does_not_borrow_other_modules(self):
  left=self.module('Vinmin',10)
  failed=dict(case=dict(id='Vinmax_标称负载',voltage=30,complete=False,error='实际超时'),title='运行与稳态检查',blocks=[dict(kind='paragraph',text='实际超时')])
  doc=self.render([left,failed]);text='\n'.join(c.text for t in doc.tables for r in t.rows for c in r.cells)
  self.assertIn('实际超时',text);self.assertIn('未取得',text)
  row=doc.tables[1].rows[1].cells;self.assertEqual(row[5].text,'未取得')
 def test_rows_unique_to_one_endpoint_remain_visible(self):
  a=self.module('Vinmin',10);b=self.module('Vinmax',20)
  b['blocks'][0]['rows'].append(('新增实测项','V',1,2,'+100%','待复核'))
  doc=self.render([a,b]);self.assertIn('新增实测项','\n'.join(c.text for t in doc.tables for r in t.rows for c in r.cells))
 def test_unbound_id_is_explicit_not_guessed_from_voltage(self):
  a=self.module('other',10);doc=self.render([a])
  self.assertIn('未绑定端点','\n'.join(p.text for p in doc.paragraphs))
  self.assertIsNone(_endpoint(a['case'])[0])
 def test_duplicate_evidence_cannot_silently_overwrite(self):
  with self.assertRaisesRegex(ValueError,'重复证据'):self.render([self.module('Vinmin',10),self.module('Vinmin',20)])
 def test_different_units_are_not_lost(self):
  a=self.module('Vinmin',10);b=self.module('Vinmax',20);b['blocks'][0]['rows'][0]=('峰值','V',20,21,'+5%','待复核')
  doc=self.render([a,b]);self.assertIn('Vinmin A / Vinmax V',doc.tables[1].rows[1].cells[1].text)
 def test_same_voltage_different_test_families_are_not_merged(self):
  modules=[self.module('Vinmin',10),self.module('Vinmax',20),self.module('Vinmin',30),self.module('Vinmax',40)]
  for m in modules[2:]:m['case']['id']=m['case']['id'].replace('标称负载','负载阶跃')
  doc=self.render(modules)
  self.assertEqual(len(doc.tables),4)
  self.assertEqual(doc.tables[1].rows[1].cells[2].text,'10')
  self.assertEqual(doc.tables[1].rows[1].cells[5].text,'20')
  self.assertEqual(doc.tables[3].rows[1].cells[2].text,'30')
  self.assertEqual(doc.tables[3].rows[1].cells[5].text,'40')
if __name__=='__main__':unittest.main(verbosity=2)
