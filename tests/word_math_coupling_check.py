"""Native OMML n-ary operators: sums, absolute integrands and coupling math."""
import ast
from pathlib import Path
import sys
import unittest

from docx.oxml.ns import qn

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from word_math import math_nodes,element


def expression(text):
    return element('oMath',*math_nodes(text))


def text_of(node):
    return ''.join(part.text or '' for part in node.iter(qn('m:t')))


class NativeNaryChecks(unittest.TestCase):
    def test_parallel_rc_equations_have_native_subscripts(self):
        for source,expected in (
            ('Z_k(s)=R_k+1/(s·C_k)',('k',)),
            ('Z_p(s)=Z_1(s)·Z_2(s)/(Z_1(s)+Z_2(s))',('p','1','2')),
            ('Z_o(s)=Z_p(s)·R_L/(Z_p(s)+R_L)',('o','p','L')),
            ('i_k=(vnode-u_k)/R_k',('k','node')),
            ('du_k/dt=i_k/C_k',('k',))):
            node=expression(source)
            self.assertNotIn('_',text_of(node))
            subs=[text_of(part) for part in node.iter(qn('m:sub'))]
            for label in expected:self.assertIn(label,subs)

    def test_multi_output_loop_symbols_have_native_subscripts(self):
        for source, expected in (
                ('δxnext=Ad·δxstate+Bd·δu', ('n+1','d','n')),
                ('T(s)=Gc(s)·Gb(s)', ('c','b')),
                ('Hj(s)=Gj(s)·Gc(s)/(1+T(s))', ('j','c')),
                ('Zjk(s)=Gjk(s)-Gj(s)·Gc(s)·Gbk(s)/(1+T(s))', ('jk','bk'))):
            node=expression(source)
            subs=[text_of(part) for part in node.iter(qn('m:sub'))]
            for label in expected:
                self.assertIn(label,subs)
            self.assertNotIn('_',text_of(node))

    def test_transformer_electrical_symbols_use_one_native_subscript(self):
        for source, expected in (
                ('N_j=Np/Ns_j', ('s,j',)),
                ('V_j,est=V_b·Ns_j/Ns_b', ('j,est', 's,j', 's,b')),
                ('Acu_j=nstrand_j·π·d_j²/4', ('Cu,j', 'strand,j')),
                ('J_j=Irms_j/Acu_j', ('rms,j', 'Cu,j')),
                ('Rdc_j=ρ·MLT·Ns_j/Acu_j', ('dc,j', 's,j', 'Cu,j'))):
            with self.subTest(source=source):
                node = expression(source)
                subs = [text_of(part) for part in node.iter(qn('m:sub'))]
                for label in expected:
                    self.assertIn(label, subs)
                self.assertNotIn('_', text_of(node))

    def check_naries(self,node):
        operators=list(node.iter(qn('m:nary')))
        for operator in operators:
            body=operator.find(qn('m:e'))
            self.assertIsNotNone(body)
            self.assertTrue(len(body), 'empty OMML n-ary operand')
            self.assertTrue(text_of(body), 'empty grouped operand is a Word placeholder')
            character=operator.find(qn('m:naryPr')).find(qn('m:chr')).get(qn('m:val'))
            self.assertIn(character,('∑','∫'))
            self.assertNotEqual(character,'Σ')  # Greek Sigma is not an OMML sum
        return operators

    def test_fraction_sums_are_real_native_operators(self):
        for source in ('Ij(f)=Ibank(f)·Yj(f)/ΣYk(f)；Yj=1/Zj',
                       'V(f)=Ic(f)·Zeq(f)；Zeq=1/ΣYj',
                       'Ij,band²=Σ(p[k]·|Yj(f[k])/(ΣYk(f[k]))|²)',
                       'Ij,total=√(ΣIj,band²)；PESR,j=ESRj·Ij,total²'):
            node=expression(source)
            self.assertTrue(self.check_naries(node))
            self.assertTrue(list(node.iter(qn('m:sSub'))))
        node=expression('Zeq=1/ΣYj')
        denominator=next(node.iter(qn('m:den')))
        self.assertIsNotNone(denominator.find(qn('m:nary')))

    def test_bounded_integrals_include_absolute_integrands(self):
        for source,bound in (('Cα=∫_0^(2π)|cosθ|^αdθ','2π'),
                             ('A=∫_0^(Tms)|dB/dtms|^α dtms','Tms')):
            node=expression(source)
            integral=self.check_naries(node)[0]
            self.assertEqual(text_of(integral.find(qn('m:sub'))),'0')
            self.assertEqual(text_of(integral.find(qn('m:sup'))),bound)
            body=integral.find(qn('m:e'))
            self.assertTrue(any(d.find(qn('m:dPr')).find(qn('m:begChr')).get(qn('m:val'))=='|'
                                for d in body.iter(qn('m:d'))))
            self.assertIn('α',text_of(body))
            self.assertIn('d',text_of(body))

    def test_explicit_sum_and_integral_bounds_keep_operands(self):
        for source,character in (('Σ_{j=1}^{n}(L_ij·di_j/dt)','∑'),
                                 ('∑_1^n (P_j)','∑'),
                                 ('∫_0^Ts(Vc·iclamp)dt','∫')):
            operator=self.check_naries(expression(source))[0]
            self.assertEqual(operator.find(qn('m:naryPr')).find(qn('m:chr')).get(qn('m:val')),character)
            self.assertTrue(text_of(operator.find(qn('m:sub'))))
            self.assertTrue(text_of(operator.find(qn('m:sup'))))

    def test_coupling_equations_have_native_scripts_and_derivative(self):
        source='v_i = R_i·i_i + Σ (L_ij·di_j/dt)'
        node=expression(source)
        operator=self.check_naries(node)[0]
        subs=[text_of(part) for part in node.iter(qn('m:sub'))]
        self.assertIn('ij',subs)
        self.assertIn('i',subs)
        self.assertIn('j',subs)
        denominator=next(operator.iter(qn('m:den')))
        self.assertEqual(text_of(denominator),'dt')
        integral=self.check_naries(expression('Prcd = fs·∫(Vc·iclamp)dt'))[0]
        self.assertIn('clamp',text_of(integral.find(qn('m:e'))))
        self.assertIn('dt',text_of(integral.find(qn('m:e'))))

    def test_scope_does_not_swallow_binary_expression_or_closing_bar(self):
        node=expression('ΔPin=Po+ΣPloss−Pin,est')
        operator=self.check_naries(node)[0]
        self.assertNotIn('est',text_of(operator.find(qn('m:e'))))
        self.assertIn('est',text_of(node))
        node=expression('|ΣYj|')
        self.assertEqual(text_of(self.check_naries(node)[0].find(qn('m:e'))),'Yj')

    def test_empty_operand_is_rejected_not_rendered_as_placeholder(self):
        for source in ('Σ','Σ=0','Σ()','∫_0^1','∫()'):
            with self.assertRaisesRegex(ValueError,'Empty n-ary'):
                expression(source)

    def test_all_reference_and_coupling_literal_formulas_parse(self):
        count=0
        for path,called in ((ROOT/'docs/build_calculation_reference.py','E'),
                            (ROOT/'coupling_report.py','equation'),
                            (ROOT/'winding_report.py','equation'),
                            (ROOT/'loop_report.py','equation')):
            tree=ast.parse(path.read_text(encoding='utf-8'))
            for call in ast.walk(tree):
                if not isinstance(call,ast.Call) or not isinstance(call.func,ast.Name) or call.func.id!=called:
                    continue
                args=call.args if called=='E' else call.args[1:]
                for arg in args[:3]:
                    if isinstance(arg,ast.Constant) and isinstance(arg.value,str):
                        self.check_naries(expression(arg.value));count+=1
        self.assertGreater(count,150)

    def test_gate_charge_ln_remains_upright_native_word_math(self):
        node=expression('t₁=−(Qg_th·Ron/Vth)·ln(1−Vth/Vgs)')
        logarithms=[run for run in node.iter(qn('m:r'))
                    if run.find(qn('m:t')) is not None and run.find(qn('m:t')).text=='ln']
        self.assertEqual(len(logarithms),1)
        self.assertEqual(logarithms[0].find(qn('m:rPr')).find(qn('m:sty')).get(qn('m:val')),'p')
        self.assertTrue(list(node.iter(qn('m:f'))))

    def test_text_subscripts_are_literal_not_reserved_math_keywords(self):
        node=expression('Pcap,in=Pin,est+Iin,est')
        for sub in node.iter(qn('m:sub')):
            for run in sub.iter(qn('m:r')):
                self.assertIsNotNone(run.find(qn('m:rPr')).find(qn('m:lit')))
        self.assertEqual(text_of(node),'Pcap,in=Pin,est+Iin,est')

    def test_numbers_keep_native_fraction_alignment_not_literal_text_alignment(self):
        node=expression('Rdc=ρ·MLT·N/(nstrand·π·dwire²/4)')
        for run in node.iter(qn('m:r')):
            text=run.find(qn('m:t')).text
            if text.isdigit():
                self.assertIsNone(run.find(qn('m:rPr')).find(qn('m:lit')))


if __name__=='__main__':
    unittest.main(verbosity=2)
