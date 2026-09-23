# -*- mode: python ; coding: utf-8 -*-

from pathlib import Path
from pyzbar import pyzbar
from PyInstaller.utils.hooks import collect_data_files, collect_dynamic_libs

project_dir = Path(SPEC).parent

a = Analysis(
    [str(project_dir / 'auto_receive.py')],
    pathex=[str(project_dir)],
    binaries=collect_dynamic_libs('pyzbar'),
    datas=[
        (str(project_dir / 'auto_receive_config.json'), '.'),
        (str(project_dir / 'poppler'), 'poppler'),
        (str(project_dir / 'tesseract'), 'tesseract'),
        *collect_data_files('tkinterdnd2'),
    ],
    hiddenimports=['tkinterdnd2'],
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
    name='auto_receive',
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
