"""Exercise production Word/Excel exports with the curve mode at two inputs.

The CSV fixture is synthetic format data, not a real semiconductor model.
Generated documents stay in a task QA folder, not user report directories.
"""
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
from mos_curves import read_curve_candidates
from input_voltage_range import calculate_input_endpoints
from docx_layout import new_document,section,paragraph,figure,table
from report_docx import _mos_gate_report,_chart,value
from report_xlsx import export_input_range_xlsx
from power_charts import draw_power_switching


def run():
    folder=ROOT/'_tmp_mos_curve_qa';folder.mkdir(exist_ok=True)
    p=load_spec(json.loads((ROOT/'examples/40W_CCM_FLYBACK.json').read_text(encoding='utf-8')))
    curve=read_curve_candidates(ROOT/'examples/MOS_CURVE_DEMO_OUTPUT_FAMILY.csv')[0]
    curve['name']='格式验证示例（非真实器件）'
    curve['conditions']='Tj=25 °C；固定 Vds=2 V 切片；仅用于导出验证'
    p.update(V_in_min=20.,V_in_max=40.,mos_miller_mode='curve',mos_miller_curve=curve,mos_curve_vds=2.)
    bundle=calculate_input_endpoints(p,include_loop=False,include_cross_regulation=False)
    doc=new_document('MOS 曲线查值工作点核算','20 V 与 40 V 输入端点','MOS 开关工作点')
    gates=[]
    for case in bundle['cases']:
        assert not case.get('error'),case
        result=case['result'];sw=result['semi']['switch'];gate=sw['gate'];gates.append(gate)
        section(doc,f"Vin {case['voltage']:g} V 平台与开关过程")
        _mos_gate_report(doc,sw)
        paragraph(doc,'开通与关断曲线使用上表平台及实际电流，与程序②页共用绘图函数。')
        def draw(fig):draw_power_switching(fig.subplots(1,2),result['op'],case['p'],result,real_time=False)
        figure(doc,_chart((7.1,2.8),draw),'MOS 开通与关断的阶段展开图')
        table(doc,['时间 / 损耗','结果','时间 / 损耗','结果'],[
            ('t2 / t3',value(sw['t2'],'s')+' / '+value(sw['t3'],'s'),'t6 / t7',value(sw['t6'],'s')+' / '+value(sw['t7'],'s')),
            ('开通交叠损耗',value(sw['P_sw_on'],'W'),'关断交叠损耗',value(sw['P_sw_off'],'W')),
        ])
        case['efficiency_curve']=dict(fracs=[1.],etas=[result['eta']],modes=[result['op']['mode']],failures=[])
    assert gates[0]['Vgp_on']!=gates[1]['Vgp_on'] and gates[0]['Vgp_off']!=gates[1]['Vgp_off']
    doc.save(folder/'MOS曲线查值核算验证.docx')
    assert len(doc.element.xpath('.//m:oMath'))==10
    exported=export_input_range_xlsx(folder/'MOS曲线查值_双端点验证.xlsx',bundle)
    with ZipFile(folder/'MOS曲线查值_双端点验证.xlsx') as z:
        book=ET.fromstring(z.read('xl/workbook.xml'))
        names=[x.get('name') for x in book.findall('{*}sheets/{*}sheet')]
        sheet=ET.fromstring(z.read(f'xl/worksheets/sheet{names.index("03 功率级与开关波形")+1}.xml'))
        text=''.join(sheet.itertext())
        assert text.count('计算平台电压')==2 and '曲线查值' in text
        assert text.count('MOS_CURVE_DEMO_OUTPUT_FAMILY.csv')==2 and curve['import_file']['sha256'] in text
        assert '2 V' in text and '固定' in text
        for gate in gates:
            assert any(value(gate['Vgp_on'],'V').split(' ')[0] in t for t in sheet.itertext())
    (folder/'endpoints.json').write_text(json.dumps(gates,ensure_ascii=False,indent=2,allow_nan=False),encoding='utf-8')
    print(json.dumps(exported,ensure_ascii=False),flush=True)


if __name__=='__main__':run()
