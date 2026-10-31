"""Read-only release verification for typed units, equations and web assets."""
from pathlib import Path
import sys,hashlib,json
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT/'tests'));sys.path.insert(0,str(ROOT))
from device_curve_package_check import normalized
from PyInstaller.archive.readers import CArchiveReader
release=ROOT/'releases/Windows-x64'/(sys.argv[1] if len(sys.argv)>1 else '20261031-chart-ui-fix')
for folder,exe in [('PowerDesignDesktop','SwitchingPowerSupplyDesign_V0.exe'),('PowerDesignWeb','PowerDesignWeb.exe')]:
    path=release/folder/exe;pyz=CArchiveReader(str(path)).open_embedded_archive('PYZ.pyz')
    names=['ldo','ldo_report','power_units','power_network','network_report','system_workspace','pcs_workspace','word_math','magnetic_plot','multi_output_charts','report_docx']
    if folder=='PowerDesignDesktop':names+=['ldo_ui','system_workspace_ui','system_canvas','ui_preferences','main','engineering_ui','parameter_panel','multi_output_results','resource_canvas']
    else:names+=['web_app.server','web_app.charts']
    for name in names:
        source=ROOT/(name.replace('.','/')+'.py')
        assert normalized(pyz.extract(name))==normalized(compile(source.read_text(encoding='utf-8-sig'),str(source),'exec')),name
    for name in ['docs/LDO_DESIGN.md','examples/SYSTEM_LDO.json']:
        assert (ROOT/name).read_bytes()==(path.parent/'_internal'/name).read_bytes(),name
    if folder=='PowerDesignWeb':
        for source in (ROOT/'web_app/static').rglob('*'):
            if source.is_file():assert source.read_bytes()==(path.parent/'_internal/web_app/static'/source.relative_to(ROOT/'web_app/static')).read_bytes()
    print(folder,len(names),'modules match source; docs/example/assets match; SHA256',hashlib.sha256(path.read_bytes()).hexdigest())
