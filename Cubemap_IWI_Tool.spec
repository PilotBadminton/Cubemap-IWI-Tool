# -*- mode: python ; coding: utf-8 -*-
from pathlib import Path
import os

project_root = Path(SPECPATH).resolve()
sdk_dir = os.environ.get('NVTT_SDK_DIR')
if not sdk_dir:
    raise SystemExit('Set NVTT_SDK_DIR to the NVTT SDK directory before packaging.')
sdk = Path(sdk_dir)
a = Analysis(
    [str(project_root / 'cubemap_iwi_tool.py')],
    pathex=[str(project_root)],
    binaries=[(str(sdk / 'nvtt30205.dll'), 'nvtt')],
    datas=[(str(project_root / 'licenses'), 'licenses'),
           (str(project_root / 'assets' / 'app.ico'), 'assets'),
           (str(project_root / 'skybox' / 'locales'), 'skybox/locales'),
           (str(project_root / 'README.md'), '.'),
           (str(project_root / 'LICENSE'), '.'),
           (str(project_root / 'UserGuide.md'), '.'),
           (str(project_root / 'docs' / 'figures' / '*.png'), 'docs/figures'),
           (str(project_root / '使用说明.md'), '.')],
    hiddenimports=[],
    hookspath=[str(project_root / 'tools' / 'hooks')],
    excludes=['tkinter', 'PySide6.QtNetwork'],
    noarchive=False,
    optimize=0,
)
pyz = PYZ(a.pure)
exe = EXE(
    pyz, a.scripts, [], exclude_binaries=True,
    name='Cubemap_IWI_Tool', console=False, debug=False,
    strip=False, upx=False, icon=str(project_root / 'assets' / 'app.ico'),
)
coll = COLLECT(exe, a.binaries, a.datas, strip=False, upx=False,
               name='Cubemap_IWI_Tool')
