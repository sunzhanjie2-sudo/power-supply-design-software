# Build via tools/build_release.ps1; use an onedir bundle to avoid extraction.
from pathlib import Path
import sys
sys.path.insert(0, SPECPATH)
from bundle_common import ROOT, DATA, EXCLUDES
a = Analysis([str(ROOT/'desktop_entry.py')],pathex=[str(ROOT)],binaries=[],datas=DATA,
    hiddenimports=['matplotlib.backends.backend_tkagg','matplotlib.backends.backend_agg','matplotlib.backends.backend_svg',
                   'scipy.signal','control','docx'],
    excludes=EXCLUDES,hookspath=[],runtime_hooks=[],noarchive=False)
pyz = PYZ(a.pure)
exe = EXE(pyz,a.scripts,[],exclude_binaries=True,name='SwitchingPowerSupplyDesign_V0',
    debug=False,bootloader_ignore_signals=False,strip=False,upx=False,console=False,
    icon=str(ROOT/'resources/icons/icon.ico'))
coll = COLLECT(exe,a.binaries,a.datas,strip=False,upx=False,name='PowerDesignDesktop')
