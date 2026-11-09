"""Real report exports share selected purchased L and truthful unknown checks."""
from pathlib import Path
import sys,tempfile,unittest
from zipfile import ZipFile
ROOT=Path(__file__).resolve().parents[1]
sys.path[:0]=[str(ROOT),str(ROOT/'tests')]
from runtime_resources import configure_numeric_threads
configure_numeric_threads()
from purchased_inductor_check import spec
from design_engine.service import calculate,export_report


class PurchasedInductorReportChecks(unittest.TestCase):
    def test_word_and_excel_keep_both_endpoints_without_winding_design(self):
        from docx import Document
        from openpyxl import load_workbook
        from web_app.charts import render
        run=calculate(spec(),analysis='endpoints',include_efficiency=True,include_cross_regulation=False)
        identity=run.to_dict()['snapshot_id']
        with tempfile.TemporaryDirectory() as directory:
            directory=Path(directory)
            for suffix in ('.docx','.xlsx'):
                target=directory/('purchased'+suffix)
                result=export_report(run,target)
                self.assertEqual(result['successful_cases'],2)
                self.assertFalse(result['incomplete'])
                with ZipFile(target) as archive:self.assertIsNone(archive.testzip())
            doc=Document(directory/'purchased.docx')
            text='\n'.join(p.text for p in doc.paragraphs)
            self.assertEqual(text.count('L1 · 外购成品电感'),2)
            self.assertIn('温升未评估',text)
            self.assertNotIn('图 5-1  磁通密度波形',text)
            self.assertGreaterEqual(len(doc.element.xpath('.//m:oMath//m:sSub')),4)
            workbook=load_workbook(directory/'purchased.xlsx')
            try:
                sheet=workbook['06 磁件与绕制']
                cells=[(c.column,str(c.value)) for row in sheet for c in row if c.value is not None]
                self.assertTrue(any(col<=8 and '外购成品电感' in value for col,value in cells))
                self.assertTrue(any(col>=10 and '外购成品电感' in value for col,value in cells))
                self.assertFalse(any('Steinmetz' in value for col,value in cells))
            finally:workbook.close()
            for kind in ('magnetics','magnetic_flux'):
                path=render(run,directory/(kind+'.png'),'Vinmin',kind)
                self.assertTrue(path.read_bytes().startswith(b'\x89PNG'))
        self.assertEqual(run.to_dict()['snapshot_id'],identity)


if __name__=='__main__':unittest.main()
