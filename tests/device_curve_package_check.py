"""Read-only verification that the delivered frozen build matches its sources."""
from pathlib import Path
import marshal
import sys
import types
from PyInstaller.archive.readers import CArchiveReader

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from app_resources import resource_path


def normalized(code):
    return (code.co_code, code.co_names, code.co_varnames,
            tuple(normalized(value) if isinstance(value,types.CodeType) else value for value in code.co_consts))


def check(path):
    archive=CArchiveReader(str(path)); pyz=archive.open_embedded_archive('PYZ.pyz')
    names=('device_curve_ui','device_curve_sources','device_curve_report','mos_curve_ui','diode_curve_ui',
           'parameter_panel','parameter_layout','mos_manual','loss_model','design_api','power_stage',
           'report_docx','topology_diagram','isolated_ui','manual')
    for name in names:
        assert normalized(pyz.extract(name))==normalized(compile((ROOT/(name+'.py')).read_text(encoding='utf-8-sig'),name+'.py','exec')),name+' source mismatch'
    assert normalized(marshal.loads(archive.extract('main')))==normalized(compile((ROOT/'main.py').read_text(encoding='utf-8-sig'),'main.py','exec'))
    for relative in ('docs/DEVICE_CURVE_HUB.md','docs/DIODE_CURVES.md','docs/MOS_MILLER_MODEL.md','docs/PARAMETER_PANEL.md','MANUAL_ZH.md'):
        assert resource_path(relative).read_bytes()==(path.parent/'_internal'/relative).read_bytes(),relative+' source mismatch'
    print('Frozen sources and bundled guides match:',path)


if __name__=='__main__':
    check(Path(sys.argv[1]) if len(sys.argv)>1 else ROOT/'releases/Windows-x64/20261023/PowerDesignDesktop/SwitchingPowerSupplyDesign_V0.exe')
