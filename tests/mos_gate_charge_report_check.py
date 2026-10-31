"""Production export integration and focused gate-charge layout fixtures."""
import json
from pathlib import Path
import sys
from zipfile import ZipFile
from xml.etree import ElementTree as ET
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
from mos_gate_charge_curve_check import spec
from input_voltage_range import calculate_input_endpoints
from docx_layout import new_document,section,paragraph,figure
from report_docx import _mos_gate_report,_chart
from report_xlsx import export_input_range_xlsx
from power_charts import draw_power_switching


def run():
    folder=ROOT/'_tmp_gate_charge_qa';folder.mkdir(exist_ok=True)
    bundle=calculate_input_endpoints(spec(),include_loop=False,include_cross_regulation=False)
    doc=new_document('MOS 栅电荷曲线查值核算','输入电压两端的开通与关断事件','MOS 栅电荷计算')
    paragraph(doc,'本页用于核对曲线查值、自然对数时间法与导出一致性。测试数据只验证格式与算法，不对应真实器件。')
    for case in bundle['cases']:
        assert not case.get('error'),case.get('error')
        r=case['result'];g=r['semi']['switch']['gate']
        section(doc,f"Vin {case['voltage']:g} V 栅电荷与开关过程")
        _mos_gate_report(doc,r['semi']['switch'])
        def draw(fig):draw_power_switching(fig.subplots(1,2),r['op'],case['p'],r,real_time=False)
        figure(doc,_chart((7.1,2.8),draw),'开通关断波形与计算事件使用相同电荷')
        case['efficiency_curve']=dict(fracs=[1.],etas=[r['eta']],modes=[r['op']['mode']],failures=[])
    assert len(doc.element.xpath('.//m:oMath'))==14
    text=''.join(doc.element.itertext())
    assert 'Fpre' in text and 'Fpost' in text and 'Cgs,inc' not in text
    doc.save(folder/'MOS栅电荷曲线核算.docx')
    result=export_input_range_xlsx(folder/'MOS栅电荷_双端点.xlsx',bundle)
    with ZipFile(folder/'MOS栅电荷_双端点.xlsx') as z:
        names=[x.get('name') for x in ET.fromstring(z.read('xl/workbook.xml')).findall('{*}sheets/{*}sheet')]
        for name,required in [('01 需求与工况总览','四开关事件'),('03 功率级与开关波形','Fpre')]:
            xml=ET.fromstring(z.read(f'xl/worksheets/sheet{names.index(name)+1}.xml'))
            assert required in ''.join(xml.itertext())
    (folder/'gates.json').write_text(json.dumps([dict(case=c['id'],gate=c['result']['semi']['switch']['gate']) for c in bundle['cases']],ensure_ascii=False,indent=2),encoding='utf-8')
    print(json.dumps(result,ensure_ascii=False))


if __name__=='__main__':run()
