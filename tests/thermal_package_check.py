"""Read-only frozen bytecode, guide and native-equation bundle verification."""
from pathlib import Path
import hashlib
import marshal
import sys
from zipfile import ZipFile
from xml.etree import ElementTree as ET

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'tests'))
from device_curve_package_check import check,normalized
from app_resources import resource_path
from PyInstaller.archive.readers import CArchiveReader


def verify(path):
    check(path)
    a=CArchiveReader(str(path));pyz=a.open_embedded_archive('PYZ.pyz')
    for name in ('magnetics','isolated_outputs','loss_model','power_stage','flyback_clamp',
                 'semiconductor','waveforms','active_clamp','stress_notes','multi_output_charts',
                 'multi_output_results','word_math','report_docx','report_xlsx','coupling_report','design_api'):
        assert normalized(pyz.extract(name))==normalized(compile((ROOT/(name+'.py')).read_text(encoding='utf-8-sig'),name+'.py','exec')),name
    for relative in ('计算方法与公式说明.docx','docs/THERMAL_AND_STRESS.md','docs/COUPLED_FLYBACK.md'):
        assert resource_path(relative).read_bytes()==(path.parent/'_internal'/relative).read_bytes(),relative
    with ZipFile(resource_path('计算方法与公式说明.docx')) as archive:
        document=ET.fromstring(archive.read('word/document.xml'))
        ns={'w':'http://schemas.openxmlformats.org/wordprocessingml/2006/main',
            'm':'http://schemas.openxmlformats.org/officeDocument/2006/math'}
        texts=''.join(e.text or '' for e in document.findall('.//w:t',ns))
        assert 'Rth_transformer' in texts
        assert '未考虑寄生尖峰' in texts
        assert '另加振铃裕量的器件选型参考' not in texts
        assert len(document.findall('.//m:oMath',ns))>200
    print('Thermal/stress frozen modules, guide and native Word math match')
    print('EXE SHA256',hashlib.sha256(path.read_bytes()).hexdigest())


if __name__=='__main__':
    verify(Path(sys.argv[1]) if len(sys.argv)>1 else ROOT/'releases/Windows-x64/20261023/PowerDesignDesktop/SwitchingPowerSupplyDesign_V0.exe')
