"""Verify custom-core calculations and UI are present in the delivered EXE."""
from pathlib import Path
import sys

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from PyInstaller.archive.readers import CArchiveReader
from device_curve_package_check import check, normalized
from app_resources import resource_path


def verify(path):
    check(path)
    archive=CArchiveReader(str(path));pyz=archive.open_embedded_archive('PYZ.pyz')
    for name in ('custom_cores','custom_core_ui','magnetics','transformer_turns','winding_coupling',
                 'analysis_workflows','output_parameter_panel','isolated_outputs'):
        source=(ROOT/(name+'.py')).read_text(encoding='utf-8-sig')
        assert normalized(pyz.extract(name))==normalized(compile(source,name+'.py','exec')),name+' source mismatch'
    for relative in ('docs/CUSTOM_CORES.md','计算方法与公式说明.docx'):
        assert resource_path(relative).read_bytes()==(path.parent/'_internal'/relative).read_bytes(),relative+' mismatch'
    print('Custom-core engine, UI, fixed hardware and documents verified.')


if __name__=='__main__':
    verify(Path(sys.argv[1]) if len(sys.argv)>1 else ROOT/'releases/Windows-x64/20261023/PowerDesignDesktop/SwitchingPowerSupplyDesign_V0.exe')
