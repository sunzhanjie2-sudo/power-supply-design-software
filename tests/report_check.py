"""Generate report QA artifacts and check snapshot, image and model integrity."""
import argparse
from pathlib import Path
from types import SimpleNamespace
import sys
import json
import math

sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from docx import Document
import main
from design_api import load_spec
from loss_model import compute_design
from report_docx import export_design_docx, capacitor_data, loop_data
from power_stage import DEFAULT_PARAMS
from config_io import read_default_config
from switching_transients import switching_voltage_data, STAGE_NAMES


def run(out):
    out=Path(out); out.mkdir(parents=True,exist_ok=True)
    cfg=json.loads(Path('examples/40W_ACF_FORWARD.json').read_text(encoding='utf-8'))
    # API loader intentionally rejects GUI metadata, unlike GUI config import.
    cfg.pop('__version__',None)
    cfg['topology']={'v':'ACF-FORWARD','u':''}
    cfg['control_mode']={'v':'Peak Current Mode','u':''}
    flyback_cfg={k:v for k,v in read_default_config().items() if not k.startswith('__')}
    tests=[('40W_有源钳位正激_设计评审报告',load_spec(cfg)),
           ('Buck_单电容_设计报告',dict(DEFAULT_PARAMS,topology='BUCK',V_in=12,V_out=5,P_out=5,L=47e-6,cin2_enable=False,cout2_enable=False,fc_target=3000,pm_target=60)),
           ('40W_CCM_反激_波形同步报告',load_spec(flyback_cfg)),
           ('QR_设计报告',dict(DEFAULT_PARAMS,topology='QR-FLYBACK',V_in=30,V_out=30,P_out=40,L=8e-6,N=.5,f_sw=500e3,fc_target=3000,pm_target=60))]
    results=[]
    for name,p in tests:
        before=dict(p); r=compute_design(p)
        models=main.PowerSupplyAnalyzer.calculate_transfer_functions(SimpleNamespace(),p,op=r['op'])
        path=out/(name+'.docx')
        result=export_design_docx(path,p,r['op'],r['wf'],r,models)
        assert p==before,'export changed input parameters'
        d=Document(path)
        assert len(d.inline_shapes)>=8
        assert len(d.tables)>=12
        assert '附录 A' in '\n'.join(x.text for x in d.paragraphs)
        preset_table=next(t for t in d.tables if t.cell(0,0).text=='效率设计 / 复核')
        assert preset_table.cell(1,1).text==f"{p['eta_guess']*100:.2f}%"
        assert preset_table.cell(3,1).text==f"{r['eta']*100:.2f}% / {r['eta_delta']*100:+.2f} pp"
        loss_table=next(t for t in d.tables if t.cell(0,0).text=='损耗类别')
        from report_docx import value
        assert next(row for row in loss_table.rows if row.cells[0].text=='输入电容 ESR').cells[1].text==value(r['P_cap_in'],'W')
        text='\n'.join(x.text for x in d.paragraphs)
        assert 'Q1 MOS 开通 Vgs / Vds' in text
        assert '阶段展开（非等时长）' in text
        stage_table=next(t for t in d.tables if t.cell(0,0).text=='过程')
        assert len(stage_table.rows)==9
        data=switching_voltage_data(r['op'],p,r['semi']['switch'])
        from report_docx import value
        for i,row in enumerate(stage_table.rows[1:],1):
            assert row.cells[1].text==f't{i}'+('*' if i in (4,5) else '')
            assert row.cells[2].text==STAGE_NAMES[f't{i}']
            assert row.cells[3].text==value(data['times'][f't{i}'],'s')
        for t in d.tables:
            assert t.rows[0]._tr.xpath('./w:trPr/w:tblHeader')
            assert t._tbl.xpath('./w:tblPr/w:tblBorders/w:insideH')
        caps=capacitor_data(p,r['op'])
        output_loss=sum(c['ESR']*c['total']**2 for c in caps['output']['caps'])
        assert math.isclose(output_loss,r['P_cap'],rel_tol=1e-10,abs_tol=1e-10)
        results.append(result)
        print(json.dumps(result,ensure_ascii=False))
    # No crossover must not fabricate a finite fc.
    import control as ct
    l=loop_data(tests[0][1],(ct.tf([.1],[1]),ct.tf([1],[1]),ct.tf([.1],[1])))
    assert l['fc'] is None and l['pm'] is None
    # Failed model must still produce a report that explicitly records the gap.
    p=tests[1][1]; r=compute_design(p)
    bad=export_design_docx(out/'无环路模型_报告.docx',p,r['op'],r['wf'],r,loop_error='测试：无法生成传函')
    assert not bad['loop_available']
    # A real-time request with unknown post-plateau charge must remain explicit.
    p=dict(tests[2][1]); p['Qg']=p['Qgs']+p['Qgd']; r=compute_design(p)
    unknown=out/'未知分段时间_报告.docx'
    export_design_docx(unknown,p,r['op'],r['wf'],r,mos_real_time=True)
    d=Document(unknown)
    assert '时长未知时该图退回阶段展开' in '\n'.join(x.text for x in d.paragraphs)
    times=next(t for t in d.tables if t.cell(0,0).text=='过程')
    assert times.rows[4].cells[3].text==times.rows[5].cells[3].text=='未定义'
    print('Report checks passed: 4 topologies + missing-loop fallback + no-crossing handling.')


if __name__=='__main__':
    a=argparse.ArgumentParser(); a.add_argument('--out',default='_tmp_report_qa'); run(a.parse_args().out)
