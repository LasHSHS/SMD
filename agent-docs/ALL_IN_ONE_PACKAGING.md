# SMD — All-in-One Packaging (project memory)

**Last updated:** 2026-07-07  
**Owner decision:** Las — file size is **not** a concern. Prefer completeness over a smaller download.

This document is the canonical note for humans and AI assistants working on SMD.  
When in doubt about distribution: **end users install only SMD — nothing else.**

---

## Product rule

> SMD must run as **one program** after install.  
> No Python, pip, ffmpeg, PATH tweaks, or third-party tools for normal users.

Same philosophy as commercial tools (SnapEasy, etc.), but open source (GPLv3 planned).

---

## What the official Windows build must include

| Bundled | Used for |
|---------|----------|
| Python runtime (PyInstaller) | Run the app |
| PyQt5 + **Qt WebEngine** | GUI + in-app GPS map |
| **ffmpeg + ffprobe** (`tools/ffmpeg/`) | Video overlay merge, repair, GPS read |
| Pillow, mutagen, exif | Date + GPS metadata embed |
| timezonefinder + data | Local time from GPS |
| folium + assets | Map HTML generation |

**Do not** tell users to install ffmpeg, choco packages, or Python.  
**Do not** ship a “lightweight” public build that drops WebEngine or ffmpeg unless explicitly labeled as a dev/debug variant.

---

## File size policy

- Installer/ZIP may be **large** (hundreds of MB with WebEngine + ffmpeg). **That is acceptable.**
- Never remove bundling to save size without an explicit new decision from Las.
- Never suggest “users can install ffmpeg separately” in user-facing copy for the official release.

---

## Build (maintainer / release only)

From repo root:

```powershell
powershell -ExecutionPolicy Bypass -File .\build_smd.ps1
```

This script:

1. Uses `.venv` (developers only — **not** shipped)
2. Runs `scripts\fetch_ffmpeg.ps1` if `tools\ffmpeg\ffmpeg.exe` is missing
3. Runs `pyinstaller smd.spec`
4. Copies ffmpeg into `dist\smd\tools\ffmpeg` (and `_internal` if present)

**Output:** `dist\smd\smd.exe` + folder → zip or compile `smd_installer.iss` (Inno Setup).

### Fetch ffmpeg only (dev, without full build)

```powershell
powershell -ExecutionPolicy Bypass -File .\scripts\fetch_ffmpeg.ps1
```

Source: gyan.dev **ffmpeg-release-essentials** (Windows). Binaries are gitignored; fetched at build time.

---

## Code touchpoints

| File | Role |
|------|------|
| `smd/ffmpeg_bundle.py` | Resolve bundled vs PATH ffmpeg/ffprobe |
| `smd/runtime.py` | App root / PyInstaller paths |
| `smd.spec` | PyInstaller all-in-one spec (WebEngine, folium, ffmpeg, …) |
| `build_smd.ps1` | Release build entry point |
| `scripts/fetch_ffmpeg.ps1` | Download Windows ffmpeg essentials |
| `tools/ffmpeg/` | Bundled binaries (not in git) |
| `smd_installer.iss` | Windows installer |
| `DISTRIBUTION_GUIDE.md` | Release checklist |
| `desktop_gui_pyqt.py` | Startup check: frozen build = “SMD ready”, not “install ffmpeg” |

---

## Legal / release notes

- **FFmpeg** is LGPL/GPL. Official releases must mention FFmpeg and link to https://ffmpeg.org/legal.html
- SMD is **not affiliated with Snap Inc.**
- GPLv3 for SMD itself when published

---

## Developer vs end user

| | End user | Developer (Las / contributors) |
|---|----------|----------------------------------|
| Install | SMD installer or portable `dist/smd` | Git clone + `.venv` + `pip install -r requirements` |
| ffmpeg | Already inside SMD | `fetch_ffmpeg.ps1` once, or `build_smd.ps1` |
| Run | `smd.exe` | `python desktop_gui_pyqt.py` or CLI `main.py` |

---

## Checklist before each public release

- [ ] `build_smd.ps1` completes without errors
- [ ] About dialog: ffmpeg shows **Bundled**
- [ ] GPS map tab works (WebEngine)
- [ ] Bundled Snapchat export processes offline (test ZIP)
- [ ] No UI text asking users to install external tools
- [ ] SHA-256 published for installer/ZIP
- [ ] FFmpeg license mentioned in release notes

---

## Related docs

- `DISTRIBUTION_GUIDE.md` — release process
- `README.md` — user-facing overview
- `tools/ffmpeg/README.md` — ffmpeg folder layout
