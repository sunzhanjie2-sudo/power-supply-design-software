"""Verify real two-endpoint reports and the shared Word/Excel section."""
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
from cross_regulation_report import add_report
from docx_layout import new_document,section
from report_xlsx import export_input_range_xlsx


def run():
    folder=ROOT/'_tmp_cross_regulation_qa';folder.mkdir(exist_ok=True)
    p=load_spec(json.loads((ROOT/'examples/3_OUTPUT_CROSS_REGULATION.json').read_text(encoding='utf-8')))
    bundle=calculate_input_endpoints(p,include_loop=False)
    assert bundle['cross_regulation']['complete'],bundle['cross_regulation']
    assert bundle['cross_regulation']['total_cases']==16
    doc=new_document('多路输出交叉调整率计算报告','20 V 和 30 V 输入端点','多路输出交叉调整率')
    for case in bundle['cases']:
        data=case['result']['cross_regulation']
        assert data['total_cases']==8 and data['complete']
        assert all(c['V_in']==case['voltage'] for c in data['cases'])
        case['efficiency_curve']=dict(fracs=[1.],etas=[case['result']['eta']],modes=[case['result']['op']['mode']],failures=[])
        add_report(doc,case['p'],case['result'])
    doc.save(folder/'交叉调整率验证.docx')
    assert len(doc.element.xpath('.//m:oMath'))>=4
    text='\n'.join(c.text for t in doc.tables for r in t.rows for c in r.cells)
    assert 'X016' in text and 'X008' in text and '纯交叉跨度' in text
    result=export_input_range_xlsx(folder/'三路反激交叉调整率_双端点.xlsx',bundle)
    assert '13 交叉调整率' in result['sheet_names']
    with ZipFile(folder/'三路反激交叉调整率_双端点.xlsx') as z:
        book=ET.fromstring(z.read('xl/workbook.xml'))
        names=[x.get('name') for x in book.findall('{*}sheets/{*}sheet')]
        sheet=ET.fromstring(z.read(f'xl/worksheets/sheet{names.index("13 交叉调整率")+1}.xml'))
        native=''.join(sheet.itertext())
        assert 'X001' in native and 'X016' in native and 'Vinmin' in native and 'Vinmax' in native
    (folder/'scan.json').write_text(json.dumps(bundle['cross_regulation'],ensure_ascii=False,indent=2,allow_nan=False),encoding='utf-8')
    print(json.dumps(result,ensure_ascii=False),flush=True)


if __name__=='__main__':run()
