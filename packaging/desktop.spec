# Build via tools/build_release.ps1; use an onedir bundle to avoid extraction.
from pathlib import Path
import sys
sys.path.insert(0, SPECPATH)
from bundle_common import ROOT, DATA, EXCLUDES
import gmsh
from PyInstaller.utils.hooks import collect_data_files, copy_metadata
field_data = [(str(ROOT/'transformer_field_runtime'/name), 'transformer_field_runtime')
              for name in ('report_style.css', 'report_template.html', 'vendor-provenance.json',
                           'SOURCE_MANIFEST.json', 'README.md')]
field_data += collect_data_files('jsonschema_specifications')
field_data += copy_metadata('gmsh') + copy_metadata('meshio')
field_data += [(str(ROOT/'transformer_field_runtime/THIRD_PARTY'), 'transformer_field_runtime/THIRD_PARTY')]
a = Analysis([str(ROOT/'desktop_entry.py')],pathex=[str(ROOT)],
    binaries=[(str(gmsh.libpath), '.')],datas=DATA+field_data,
    hiddenimports=['matplotlib.backends.backend_tkagg','matplotlib.backends.backend_agg','matplotlib.backends.backend_svg',
                   'scipy.signal','control','docx','field_worker',
                   'transformer_field_runtime.pipeline', 'transformer_field_runtime.meshing',
                   'transformer_field_runtime.solving', 'transformer_field_runtime.reporting'],
    excludes=EXCLUDES,hookspath=[],runtime_hooks=[],noarchive=False)
pyz = PYZ(a.pure)
exe = EXE(pyz,a.scripts,[],exclude_binaries=True,name='SwitchingPowerSupplyDesign_V0',
    debug=False,bootloader_ignore_signals=False,strip=False,upx=False,console=False,
    icon=str(ROOT/'resources/icons/icon.ico'))
coll = COLLECT(exe,a.binaries,a.datas,strip=False,upx=False,name='PowerDesignDesktop')
