"""Source grouping and frozen relative names share one resource contract."""
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from app_resources import resource_path

class Paths(unittest.TestCase):
    def test_source_resources_exist(self):
        for relative in ('icon.png','icon.ico','MANUAL_ZH.md','计算方法与公式说明.docx',
                         '多路反激电源设计入门教程.docx','自动计算参数依据.docx',
                         'comp_images/opamp3_clean.png','examples/40W_CCM_FLYBACK.json'):
            self.assertTrue(resource_path(relative).is_file(),relative)
        self.assertEqual(resource_path('计算方法与公式说明.docx').parent,ROOT/'docs/reference')
        self.assertEqual(resource_path('自动计算参数依据.docx').parent,ROOT/'docs/reference')
        self.assertEqual(resource_path('多路反激电源设计入门教程.docx').parent,ROOT/'docs/tutorials')

    def test_frozen_resource_names_stay_compatible(self):
        with tempfile.TemporaryDirectory() as folder,patch.object(sys,'_MEIPASS',folder,create=True):
            for relative in ('comp_images/tl431f_clean.png','icon.png','计算方法与公式说明.docx',
                             '多路反激电源设计入门教程.docx'):
                self.assertEqual(resource_path(relative),Path(folder)/relative)

    def test_paths_cannot_escape_resource_root(self):
        for value in ('../secrets','C:/Windows/win.ini'):
            with self.assertRaises(ValueError):resource_path(value)

if __name__=='__main__':unittest.main(verbosity=2)
