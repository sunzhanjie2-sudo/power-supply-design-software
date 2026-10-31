"""Generate and inspect the LDO example delivery, including native Word math."""
from pathlib import Path
import sys,json
from zipfile import ZipFile
from xml.etree import ElementTree as ET
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
from runtime_resources import configure_numeric_threads
configure_numeric_threads()
from system_workspace import load_project
from ldo import calculate
from ldo_report import export_report
from network_report import export_network
from openpyxl import load_workbook

out=ROOT/'output/LDO_线性稳压_20261031';out.mkdir(parents=True,exist_ok=True)
p=load_project(ROOT/'examples/SYSTEM_LDO.json')
for mode,title in [('fixed','5V到3.3V_固定输出'),('adjustable','5V到3.3V_可调输出')]:
    r=calculate(dict(p['units'][0]['spec'],output_mode=mode))
    for kind in ('docx','xlsx','json'):export_report(r,out/(title+'.'+kind))
    with ZipFile(out/(title+'.docx')) as z:
        ns={'m':'http://schemas.openxmlformats.org/officeDocument/2006/math'}
        xml=ET.fromstring(z.read('word/document.xml'))
        assert len(xml.findall('.//m:oMath',ns))==4
        assert len(xml.findall('.//m:sSub',ns))>=15
        assert len(xml.findall('.//m:f',ns))==1
    b=load_workbook(out/(title+'.xlsx'))
    assert b['双端点角点对比']['B3'].value==4.75
    assert b['双端点角点对比']['J3'].value==5.25
    assert b['功率与输出范围']['B3'].value>0
    assert b['功率与输出范围']['E3'].value==3.3*.99
result=export_network(p,out/'LDO系统设计报告.zip')
assert result['successful']==1,result
with ZipFile(out/'LDO系统设计报告.zip') as z:
    manifest=json.loads(z.read('manifest.json'))
    assert manifest['units'][0]['design_type']=='ldo'
    for name in z.namelist():
        if name.endswith('.docx') or name.endswith('.xlsx'):
            (out/name).write_bytes(z.read(name))
print('PASS native Word scripts/fraction, both-input numeric Excel, system ZIP with complete LDO unit')
print(out)
