"""Current RC page -> Word, native math and nonduplicated multi-rail caps."""
import copy
import json
import math
from pathlib import Path
import sys
import unittest
from unittest.mock import patch

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from runtime_resources import configure_numeric_threads
configure_numeric_threads()
from docx import Document
import comp_design as compd
from compensation_report import compensation_snapshot, _equations
from docx_layout import new_document
from design_api import load_spec
from loss_model import compute_design
from plants import build_loop_models
from power_stage import DEFAULT_PARAMS
from report_docx import export_design_docx,value


def state(key='tl431f',direction='fwd',**values):
    return dict(topo=key,dir=direction,type2=False,
                vars={k:dict(v=v,u='') for k,v in values.items()})


def initial(key):
    if key=='opamp3': return dict(R1=10e3,Vref=2.5)
    if key=='gm3': return dict(R2=10e3,R1u=0,gm=2e-3)
    result=dict(R1=40e3,CTR=1.,Rpullup=20e3,Copto=.1e-9)
    if key=='tl431nf': result['R_LED']=1e3
    return result


class CompensationReportChecks(unittest.TestCase):
    p=dict(DEFAULT_PARAMS,KP=1e4,fz1=100.,fz2=1000.,fp1=1e4,fp2=2e4,controller_type='type3')
    op=dict(V_out=30.)

    def test_all_forward_networks_round_trip_through_the_same_existing_evaluators(self):
        for key in ('opamp3','gm3','tl431nf','tl431f'):
            with self.subTest(key=key):
                st=state(key,**initial(key)); saved=copy.deepcopy(st)
                data=compensation_snapshot(self.p,self.op,st)
                self.assertEqual(st,saved)
                expected=tuple(self.p[k]*2*math.pi for k in ('fz1','fz2','fp1','fp2'))
                for name,w in zip(('wz1','wz2','wp1','wp2'),expected):
                    self.assertAlmostEqual(data['realized'][name],w,delta=w*1e-10)
                self.assertAlmostEqual(data['realized']['KP'],self.p['KP'])
                doc=new_document('补偿计算测试','','测试')
                _equations(doc,data)
                self.assertGreater(len(doc.element.xpath('.//m:oMath')),3)
                # Reverse export must use the entered parts, without solving.
                entries={k:v for k,v in data['parts'].items() if isinstance(v,(int,float))}
                with patch.object(compd,'tl431_f_solve',side_effect=AssertionError('reverse must not solve')):
                    reverse=compensation_snapshot(self.p,self.op,state(key,'rev',**entries))
                self.assertEqual(reverse['realized'],data['realized'])

    def test_display_units_and_actual_feedback_voltage_are_used(self):
        st=state(**initial('tl431f'))
        st['vars']['R1']=dict(v=40,u='k')
        st['vars']['Copto']=dict(v=.1,u='n')
        data=compensation_snapshot(self.p,dict(V_out=12.),st)
        self.assertEqual(data['inputs']['R1'],40000)
        self.assertAlmostEqual(data['parts']['R_lower'],40000*2.5/9.5)

    def test_negative_c2_and_approximate_fast_lane_are_explicit(self):
        p=dict(self.p,fz2=2e6,fp1=58e3,fp2=159e3)
        data=compensation_snapshot(p,self.op,state(**initial('tl431f')))
        self.assertFalse(data['buildable'])
        self.assertLess(data['parts']['C2'],0)
        self.assertTrue(any('负值' in note for note in data['notes']))
        self.assertTrue(any('近似抵消' in note for note in data['notes']))
        self.assertNotAlmostEqual(data['realized']['wp1'],p['fp1']*2*math.pi)

    def test_legacy_simplified_branches_and_voltage_guard(self):
        for key in ('opamp3','gm3'):
            values=initial(key)
            if key=='gm3': values['R1u']=40e3
            st=state(key,**values); st['type2']=True
            data=compensation_snapshot(self.p,self.op,st)
            self.assertTrue(math.isinf(data['realized']['wp1']))
            _equations(new_document('测试','','测试'),data)
        data=compensation_snapshot(self.p,dict(V_out=2.5),state(**initial('tl431f')))
        self.assertNotIn('R_lower',data['parts'])
        self.assertFalse(data['buildable'])

    def test_multi_output_report_keeps_each_cap_once_and_does_not_mutate_inputs(self):
        p=load_spec(json.loads((ROOT/'examples/3_OUTPUT_COUPLED_FLYBACK.json').read_text(encoding='utf-8')))
        result=compute_design(p)
        models,_=build_loop_models(p,result['op'])
        st=state(**initial('tl431f'))
        saved=copy.deepcopy((p,st))
        output=ROOT/'_tmp_report_compensation_qa/3路反激_补偿电路与电容纹波.docx'
        outcome=export_design_docx(output,p,result['op'],result['wf'],result,models=models,
                                   compensation_state=st)
        self.assertTrue(outcome['compensation_available'])
        self.assertEqual((p,st),saved)
        doc=Document(output)
        body='\n'.join(para.text for para in doc.paragraphs)
        self.assertIn('6.1  补偿电路参数计算',body)
        self.assertIn('6.2  补偿电路计算关系与回代核验',body)
        self.assertIn('当前补偿参考电路',body)
        self.assertNotIn('图 1-C1',body)
        self.assertNotIn('图 1-C2',body)
        cap_tables=[t for t in doc.tables if t.cell(0,0).text=='电容']
        self.assertEqual(len(cap_tables),1)
        actual=cap_tables[0]
        banks=[('共享输入',result['capacitors']['input'])]+[
            (f"OUT{r['id']}",r['capacitors']['output']) for r in result['outputs']]
        expected=[(f'{label} C{i}',c) for label,bank in banks for i,c in enumerate(bank['caps'],1)]
        self.assertEqual(len(actual.rows),len(expected)+1)
        for row,(label,c) in zip(actual.rows[1:],expected):
            self.assertEqual(row.cells[0].text,label)
            self.assertEqual(row.cells[4].text,value(c['total'],'A'))
        for label,_ in banks:
            self.assertEqual(body.count(label+' 电容 FFT 分带（仅列一次）'),1)
        self.assertGreaterEqual(len(doc.element.xpath('.//m:oMath')),9)
        print('Verified integration report:',output)

    def test_missing_or_invalid_reference_state_is_not_replaced_by_defaults(self):
        from compensation_report import add_compensation_report
        for st in (None,dict(topo='unknown'),state(R1=0)):
            doc=new_document('测试','','测试')
            self.assertFalse(add_compensation_report(doc,self.p,self.op,st))
            self.assertIn('未能计算',''.join(p.text for p in doc.paragraphs))
        doc=new_document('测试','','测试')
        self.assertFalse(add_compensation_report(doc,self.p,self.op,None,psr=True))
        self.assertIn('MP6005 PSR',''.join(p.text for p in doc.paragraphs))


if __name__=='__main__': unittest.main(verbosity=2)
