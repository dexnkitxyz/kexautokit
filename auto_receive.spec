# -*- mode: python ; coding: utf-8 -*-

from pathlib import Path
from PyInstaller.utils.hooks import collect_all, collect_data_files, collect_dynamic_libs

project_dir = Path(SPEC).parent
webview_datas, webview_binaries, webview_hiddenimports = collect_all('webview')
pythonnet_datas, pythonnet_binaries, pythonnet_hiddenimports = collect_all('pythonnet')
clr_loader_datas, clr_loader_binaries, clr_loader_hiddenimports = collect_all('clr_loader')

a = Analysis(
    [str(project_dir / 'auto_receive.py')],
    pathex=[str(project_dir)],
    binaries=[
        *collect_dynamic_libs('zxingcpp'),
        *webview_binaries,
        *pythonnet_binaries,
        *clr_loader_binaries,
    ],
    datas=[
        (str(project_dir / 'kexauto.ico'), '.'),
        (str(project_dir / 'poppler'), 'poppler'),
        (str(project_dir / 'tesseract'), 'tesseract'),
        (str(project_dir / 'ui_app.html'), '.'),
        *collect_data_files('tkinterdnd2'),
        *collect_data_files('webview'),
        *webview_datas,
        *pythonnet_datas,
        *clr_loader_datas,
    ],
    hiddenimports=[
        'tkinterdnd2',
        'zxingcpp',
        *webview_hiddenimports,
        *pythonnet_hiddenimports,
        *clr_loader_hiddenimports,
    ],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
    noarchive=False,
    optimize=0,
)
pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.datas,
    [],
    name='kexauto',
    icon=str(project_dir / 'kexauto.ico'),
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    upx_exclude=[],
    runtime_tmpdir=None,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
)
