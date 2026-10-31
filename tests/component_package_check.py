"""Read-only source/resource identity checks on explicitly supplied own builds."""
from pathlib import Path
import sys
from PyInstaller.archive.readers import CArchiveReader

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT));sys.path.insert(0,str(ROOT/'tests'))
from device_curve_package_check import normalized


def check(folder):
    folder=Path(folder).resolve()
    exe=folder/('PowerDesignWeb.exe' if (folder/'PowerDesignWeb.exe').is_file() else 'SwitchingPowerSupplyDesign_V0.exe')
    archive=CArchiveReader(str(exe));pyz=archive.open_embedded_archive('PYZ.pyz')
    modules=['component_management','component_report','report_docx','report_xlsx','design_checks','power_stage',
             'design_engine.specification','design_engine.reporting','design_engine.service']
    if exe.name=='PowerDesignWeb.exe':modules+=['web_app.metadata','web_app.presentation']
    else:modules+=['component_ui']
    for name in modules:
        path=ROOT.joinpath(*name.split('.')).with_suffix('.py')
        assert normalized(pyz.extract(name))==normalized(compile(path.read_text(encoding='utf-8-sig'),str(path),'exec')),name+' frozen source differs'
    guide='docs/COMPONENT_BOM_DERATING.md'
    assert (folder/'_internal'/guide).read_bytes()==(ROOT/guide).read_bytes()
    if exe.name=='PowerDesignWeb.exe':
        source=ROOT/'web_app/static';target=folder/'_internal/web_app/static'
        for path in source.rglob('*'):
            if path.is_file():assert (target/path.relative_to(source)).read_bytes()==path.read_bytes(),str(path)
    print(f'Frozen BOM sources and resources verified: {exe}')


if __name__=='__main__':check(sys.argv[1])
