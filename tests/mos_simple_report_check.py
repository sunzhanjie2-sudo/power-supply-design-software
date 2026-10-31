"""Production exporters with manual four events and extrapolated simple Qg."""
import json
from pathlib import Path
import sys
from zipfile import ZipFile
from xml.etree import ElementTree as ET
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
from mos_four_manual_check import spec
from input_voltage_range import calculate_input_endpoints
from mos_four_cases import event_rows
from docx_layout import new_document,paragraph,table,figure
from report_docx import _mos_gate_report,_chart
from report_xlsx import export_input_range_xlsx
from power_charts import draw_power_switching


def run():
    folder=ROOT/'_tmp_mos_simple_qa';folder.mkdir(exist_ok=True)
    p=spec();p.update(mos_charge_mode='curve',mos_charge_curve=json.loads((ROOT/'tests/fixtures/actual_gate_profile.json').read_text(encoding='utf-8')))
    bundle=calculate_input_endpoints(p,include_loop=False,include_cross_regulation=False)
    doc=new_document('MOS 四事件与栅电荷外推核算','曲线导入和工程报告排版验证','MOS 四事件核算')
    paragraph(doc,'此验证使用用户截图中的栅电荷坐标与一组格式测试工况，检查四个手动平台的独立查值和端点外推提示，不用于真实器件选型。')
    rows=event_rows(bundle)
    table(doc,['工况','事件','Id / A','Vgp / V','Qgs / nC','Qgd / nC','Qg(th) / nC','总Qg / nC'],[
        [r[0],r[1]]+[f'{v*(1e9 if i>=4 else 1):.5g}' if isinstance(v,(int,float)) else v for i,v in enumerate(r[2:],2)] for r in rows],
        [.85,.5,.75,.85,1.,1.,1.1,1.05])
    for case in bundle['cases']:
        assert not case.get('error'),case.get('error')
        doc.add_heading(f"{case['id']} 平台和电荷",1)
        r=case['result'];g=r['semi']['switch']['gate']
        assert g['manual_case']==case['p']['input_voltage_case']
        _mos_gate_report(doc,r['semi']['switch'])
        def draw(fig):draw_power_switching(fig.subplots(1,2),r['op'],case['p'],r,real_time=False)
        figure(doc,_chart((7.1,2.7),draw),'四事件平台和电荷用于对应开关波形')
        case['efficiency_curve']=dict(fracs=[1.],etas=[r['eta']],modes=[r['op']['mode']],failures=[])
    assert len(doc.element.xpath('.//m:oMath'))==10
    assert '端点外推' in ''.join(doc.element.itertext())
    doc.save(folder/'四事件与曲线外推验证.docx')
    result=export_input_range_xlsx(folder/'四事件与曲线外推.xlsx',bundle)
    with ZipFile(folder/'四事件与曲线外推.xlsx') as z:
        names=[x.get('name') for x in ET.fromstring(z.read('xl/workbook.xml')).findall('{*}sheets/{*}sheet')]
        for name,terms in [('01 需求与工况总览',['四开关事件']),('03 功率级与开关波形',['外推','Qg.png']),('12 输入参数快照',['手动输入端点','Vinmin','Vinmax'])]:
            text=''.join(ET.fromstring(z.read(f'xl/worksheets/sheet{names.index(name)+1}.xml')).itertext())
            assert all(t in text for t in terms),(name,terms)
    print(json.dumps(result,ensure_ascii=False))


if __name__=='__main__':run()
