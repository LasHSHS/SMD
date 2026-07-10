# -*- mode: python ; coding: utf-8 -*-
"""
SMD all-in-one Windows build (portable folder).

Includes: Python runtime, PyQt5 + WebEngine, ffmpeg, timezone data, folium assets.
End users run dist/smd/smd.exe — no Python, pip, or separate tool installs.
"""
from pathlib import Path

from PyInstaller.utils.hooks import collect_all, collect_data_files

datas = []
binaries = []
hiddenimports = [
    'smd',
    'smd.models',
    'smd.utils',
    'smd.metadata',
    'smd.export_detect',
    'smd.local_pipeline',
    'smd.system_profile',
    'smd.overlays',
    'smd.video_repair',
    'smd.ffmpeg_bundle',
    'smd.runtime',
    'mutagen',
    'exif',
    'pydantic',
    'pytz',
    'timezonefinder',
    'PIL',
    'folium',
    'branca',
    'jinja2',
    'numpy',
]

for pkg in (
    'PyQt5',
    'PyQt5.QtWebEngineWidgets',
    'psutil',
    'folium',
    'branca',
    'timezonefinder',
    'mutagen',
    'numpy',
):
    try:
        tmp = collect_all(pkg)
        datas += tmp[0]
        binaries += tmp[1]
        hiddenimports += tmp[2]
    except Exception:
        pass

try:
    datas += collect_data_files('timezonefinder')
except Exception:
    pass

icon_file = Path('icon.ico')
icon_arg = str(icon_file) if icon_file.is_file() else None

# Bundle ffmpeg/ffprobe + DLLs (fetched by scripts/fetch_ffmpeg.ps1 before build)
ffmpeg_dir = Path('tools/ffmpeg')
if ffmpeg_dir.is_dir():
    for f in sorted(ffmpeg_dir.iterdir()):
        if f.is_file():
            binaries.append((str(f), 'tools/ffmpeg'))

guide_assets = Path('assets/guide')
if guide_assets.is_dir():
    for name in ('1.png', '2.png', '3.png', '4.png', '5.png'):
        f = guide_assets / name
        if f.is_file():
            datas.append((str(f), 'assets/guide'))

ui_assets = Path('assets/ui')
if ui_assets.is_dir():
    for f in sorted(ui_assets.iterdir()):
        if f.is_file():
            datas.append((str(f), 'assets/ui'))

a = Analysis(
    ['desktop_gui_pyqt.py'],
    pathex=[],
    binaries=binaries,
    datas=datas,
    hiddenimports=hiddenimports,
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
    [],
    exclude_binaries=True,
    name='smd',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon=icon_arg,
)
coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=True,
    upx_exclude=[],
    name='smd',
)
