"""Keep inherited DOCX theme fonts from overprinting CJK headings."""
from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from docx.oxml.ns import qn
from docx_layout import new_document, FONT, paragraph


class WordLayoutChecks(unittest.TestCase):
    def test_small_notes_do_not_inherit_larger_complex_script_size(self):
        doc = new_document('测试', '排版检查', '页眉')
        p = paragraph(doc, '小字号说明', True)
        prop = p.runs[0]._element.get_or_add_rPr()
        self.assertEqual(prop.find(qn('w:szCs')).get(qn('w:val')), '18')

    def test_core_styles_have_explicit_fonts_and_matching_script_sizes(self):
        doc = new_document('测试', '排版检查', '页眉')
        for name in ('Normal', 'Title', 'Subtitle', 'Heading 1', 'Heading 2', 'Heading 3', 'Caption'):
            with self.subTest(style=name):
                style = doc.styles[name]
                prop = style.element.get_or_add_rPr()
                fonts = prop.get_or_add_rFonts()
                self.assertFalse(any('theme' in key.lower() for key in fonts.attrib))
                for script in ('ascii', 'hAnsi', 'eastAsia', 'cs'):
                    self.assertEqual(fonts.get(qn('w:'+script)), FONT)
                self.assertEqual(prop.find(qn('w:sz')).get(qn('w:val')),
                                 prop.find(qn('w:szCs')).get(qn('w:val')))


if __name__ == '__main__':
    unittest.main(verbosity=2)
