# Distribution Guide — All-in-One SMD (Windows)

SMD is distributed as **one self-contained package**. End users install or unzip once and run `smd.exe`. They never install Python, ffmpeg, pip, or other tools.

## What is bundled

| Component | Purpose |
|-----------|---------|
| Python runtime | App execution (inside PyInstaller build) |
| PyQt5 + Qt WebEngine | GUI + in-app GPS map |
| ffmpeg + ffprobe | Video overlays, repair, GPS read |
| Pillow, mutagen, exif | Metadata embed |
| folium + assets | Map HTML generation |

## Build (release maintainer only)

```powershell
powershell -ExecutionPolicy Bypass -File .\build_smd.ps1
```

This script:

1. Creates/uses `.venv` (developers only — not shipped)
2. Downloads ffmpeg into `tools/ffmpeg/` if missing
3. Runs `pyinstaller smd.spec`
4. Copies ffmpeg beside `dist/smd/smd.exe`

**Output:** `dist/smd/` — zip this folder or compile `smd_installer.iss` with Inno Setup.

## Release checklist

- [ ] `dist/smd/smd.exe` launches without console window
- [ ] About dialog shows ffmpeg: **Bundled**
- [ ] Bundled export: merge + metadata on sample ZIP
- [ ] GPS map tab loads (WebEngine)
- [ ] No prompts to install external software
- [ ] Publish SHA-256 for installer/ZIP
- [ ] Include FFmpeg LGPL notice in release notes (ffmpeg.org/legal.html)

## User messaging

- **Not affiliated with Snap Inc.**
- **All-in-one:** no extra installs
- **Bundled exports (2026+):** works fully offline
- **Link-only exports (legacy JSON with URLs):** not supported - request a new export with media in the ZIP
- **My Eyes Only** not included in Memories export

## Code signing (optional)

Unsigned builds may trigger SmartScreen. Publish hashes; add Authenticode signing when budget allows.
