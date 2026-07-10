# -*- mode: python ; coding: utf-8 -*-
# Legacy one-file spec — use smd.spec for official all-in-one builds.

a = Analysis(
    ['desktop_gui_pyqt.py'],
    pathex=[],
    binaries=[('tools/exiftool.exe', 'tools/')],
    datas=[],
    hiddenimports=['smd', 'smd.models', 'smd.utils', 'smd.metadata', 'smd.local_pipeline'],
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
    name='desktop_gui_pyqt',
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
    icon=['icon.ico'],
)
