"""Frozen all-parameter UI and unchanged calculation-engine verification."""
from pathlib import Path
import sys

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'tests'))
from thermal_package_check import verify
from device_curve_package_check import normalized
from PyInstaller.archive.readers import CArchiveReader


def check(path):
    verify(path)
    pyz=CArchiveReader(str(path)).open_embedded_archive('PYZ.pyz')
    for name in ('engineering_ui','parameter_layout','parameter_panel'):
        source=compile((ROOT/(name+'.py')).read_text(encoding='utf-8-sig'),name+'.py','exec')
        assert normalized(pyz.extract(name))==normalized(source),name
    previous=ROOT/'dist/Thermal_clamp_stress_20261021/SwitchingPowerSupplyDesign_V0/SwitchingPowerSupplyDesign_V0.exe'
    old=CArchiveReader(str(previous)).open_embedded_archive('PYZ.pyz')
    for name in ('magnetics','power_stage','loss_model','semiconductor','flyback_clamp',
                 'isolated_outputs','waveforms','active_clamp','mos_gate','mos_gate_charge',
                 'report_docx','report_xlsx','design_api'):
        assert normalized(pyz.extract(name))==normalized(old.extract(name)),name+' calculation changed'
    print('All-parameter UI matches source; calculation/report engines unchanged from previous release')


if __name__=='__main__':
    check(Path(sys.argv[1]) if len(sys.argv)>1 else ROOT/'dist/All_parameters_visible_20261021/SwitchingPowerSupplyDesign_V0/SwitchingPowerSupplyDesign_V0.exe')
