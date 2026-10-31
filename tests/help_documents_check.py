"""Help menu order, document opening and bundle data without creating a GUI."""
import ast
from pathlib import Path
import sys
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from app_resources import resource_path
from main import PowerSupplyAnalyzer

TUTORIAL = '多路反激电源设计入门教程.docx'
REFERENCE = '计算方法与公式说明.docx'


class HelpDocuments(unittest.TestCase):
    def setUp(self):
        self.app = object.__new__(PowerSupplyAnalyzer)

    def test_tutorial_immediately_follows_reference(self):
        tree = ast.parse((ROOT/'main.py').read_text(encoding='utf-8-sig'))
        entries = []
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call) or not isinstance(node.func, ast.Attribute):
                continue
            if not isinstance(node.func.value, ast.Name) or node.func.value.id != 'helpmenu':
                continue
            for arg in node.keywords:
                if arg.arg == 'label' and isinstance(arg.value, ast.Constant):
                    entries.append((node.lineno, arg.value.value))
        labels = [label for _, label in sorted(entries)]
        self.assertEqual(labels, [REFERENCE[:-5], TUTORIAL[:-5]])

    def test_tutorial_opens_exact_shipped_document(self):
        with patch('main.os.startfile') as launch, patch('main.messagebox.showerror') as error:
            self.app.open_design_tutorial()
            self.assertEqual(Path(launch.call_args.args[0]).resolve(), resource_path(TUTORIAL).resolve())
            error.assert_not_called()

    def test_reference_still_opens(self):
        with patch('main.os.startfile') as launch:
            self.app.open_calculation_reference()
            self.assertEqual(Path(launch.call_args.args[0]).resolve(), resource_path(REFERENCE).resolve())

    def test_missing_tutorial_has_useful_error(self):
        with patch('main.os.path.isfile', return_value=False), patch('main.os.startfile') as launch, \
                patch('main.messagebox.showerror') as error:
            self.app.open_design_tutorial()
            launch.assert_not_called()
            self.assertIn(TUTORIAL, error.call_args.args[1])

    def test_missing_word_association_has_useful_error(self):
        with patch('main.os.startfile', side_effect=OSError('no association')), \
                patch('main.messagebox.showerror') as error:
            self.app.open_design_tutorial()
            self.assertIn('Word 或 WPS', error.call_args.args[1])

    def test_both_documents_are_bundled_without_build_scripts(self):
        from runpy import run_path
        DATA = run_path(str(ROOT/'packaging/bundle_common.py'))['DATA']
        for name in (REFERENCE, TUTORIAL):
            self.assertIn((str(resource_path(name)), '.'), DATA)
        self.assertFalse(any('tutorials' in source and not source.endswith('.docx') for source, _ in DATA))


if __name__ == '__main__':
    unittest.main(verbosity=2)
