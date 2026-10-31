"""Render-QA fixtures through the production Word/Excel report paths."""
import json
from pathlib import Path
import sys
from zipfile import ZipFile
from xml.etree import ElementTree as ET

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from runtime_resources import configure_numeric_threads
configure_numeric_threads()
from design_api import load_spec
from input_voltage_range import calculate_input_endpoints
from docx_layout import new_document,section,paragraph,figure,table
from report_docx import _mos_gate_report,_chart,value
from report_xlsx import export_input_range_xlsx
from power_charts import draw_power_switching


def run():
    folder=ROOT/'_tmp_mos_miller_qa';folder.mkdir(exist_ok=True)
    p=load_spec(json.loads((ROOT/'examples/40W_CCM_FLYBACK.json').read_text(encoding='utf-8')))
    p.update(V_in_min=20.,V_in_max=40.,gfs=5.)
    bundle=calculate_input_endpoints(p,include_loop=False,include_cross_regulation=False)
    doc=new_document('MOS 米勒平台工作点核算','20 V 与 40 V 输入端点','MOS 开关工作点')
    gates=[]
    for c in bundle['cases']:
        assert not c.get('error'),c
        r=c['result'];gate=r['semi']['switch']['gate'];gates.append(gate)
        section(doc,f"Vin {c['voltage']:g} V 米勒平台与开关过程")
        _mos_gate_report(doc,r['semi']['switch'])
        paragraph(doc,'开通与关断曲线使用上表平台电压及实际工作点，与程序②页共用绘图函数。')
        def draw(fig):draw_power_switching(fig.subplots(1,2),r['op'],c['p'],r,real_time=False)
        figure(doc,_chart((7.1,2.8),draw),'MOS 开通与关断的阶段展开图')
        sw=r['semi']['switch']
        table(doc,['时间 / 损耗','结果','时间 / 损耗','结果'],[
            ('t2 / t3',value(sw['t2'],'s')+' / '+value(sw['t3'],'s'), 't6 / t7',value(sw['t6'],'s')+' / '+value(sw['t7'],'s')),
            ('开通交叠损耗',value(sw['P_sw_on'],'W'),'关断交叠损耗',value(sw['P_sw_off'],'W')),
        ])
        c['efficiency_curve']=dict(fracs=[1.],etas=[r['eta']],modes=[r['op']['mode']],failures=[])
    assert gates[0]['Vgp_on']!=gates[1]['Vgp_on'] and gates[0]['Vgp_off']!=gates[1]['Vgp_off']
    doc.save(folder/'MOS米勒平台核算验证.docx')
    assert len(doc.element.xpath('.//m:oMath'))==10
    result=export_input_range_xlsx(folder/'MOS米勒平台_双端点验证.xlsx',bundle)
    with ZipFile(folder/'MOS米勒平台_双端点验证.xlsx') as z:
        book=ET.fromstring(z.read('xl/workbook.xml'))
        names=[x.get('name') for x in book.findall('{*}sheets/{*}sheet')]
        sheet=ET.fromstring(z.read(f'xl/worksheets/sheet{names.index("03 功率级与开关波形")+1}.xml'))
        text=''.join(sheet.itertext())
        assert text.count('计算平台电压')==2 and '电流相关平台' in text
        for gate in gates:
            assert any(value(gate['Vgp_on'],'V').split(' ')[0] in t for t in sheet.itertext())
    (folder/'endpoints.json').write_text(json.dumps(gates,ensure_ascii=False,indent=2,allow_nan=False),encoding='utf-8')
    print(json.dumps(result,ensure_ascii=False),flush=True)


if __name__=='__main__':run()
