# SMD — Pre-publication checklist

Author: **Las HS** — [las-hs.com](https://las-hs.com)

Use this list before publishing to GitHub, creating a release, or distributing the installer.

---

## 1. Legal & attribution

- [ ] `README.md` credits **Las HS** as author with link to https://las-hs.com
- [ ] About dialog shows author and version (GUI → About)
- [ ] Clear disclaimer: **not affiliated with Snap Inc.**
- [x] Choose and add `LICENSE` file (GPLv3 - required because the GUI links PyQt5/GPL)
- [x] Third-party notices: ffmpeg, PyQt5, Pillow, etc. in `NOTICE`

---

## 2. Git repository

- [ ] Create repo (e.g. `Snapchat-Memories-Downloader` or `SMD`)
- [ ] `.gitignore` excludes: `.venv/`, `dist/`, `accounts/`, `*.log`, user exports, `technical/staging/`
- [ ] No secrets in history (API keys, passwords, personal exports)
- [ ] Initial commit message describes purpose, not “fix stuff”
- [ ] Tag release: `v1.0.0` with changelog
- [ ] GitHub release attaches built `smd.exe` / installer from `build_smd.ps1`

---

## 3. Quality & testing (your export)

- [ ] Full bundled export processed (13k+ files for Las account)
- [ ] **Verify staging** passes before deleting `technical/staging/`
- [ ] **Review duplicates** — keep the copies you want; the rest are permanently deleted
- [ ] Spot-check: merged vs raw on photos with/without overlays
- [ ] Run on clean Windows 10 and Windows 11 VM (no Python installed)
- [ ] Test resume after cancel mid-processing
- [ ] Test theme: System / Light / Dark

---

## 4. Build & distribute

- [ ] `powershell -ExecutionPolicy Bypass -File .\build_smd.ps1`
- [ ] Test `Run-SMD.bat` from Desktop shortcut on non-dev PC
- [ ] ffmpeg bundled in official build (`tools/ffmpeg/` or PyInstaller bundle)
- [ ] Version number consistent: `smd/version.py`, About dialog, release tag
- [ ] Optional: code-sign `.exe` (SmartScreen trust)

---

## 5. Documentation

- [ ] `README.md`: install, first run, export ZIP selection, account name, output folders
- [ ] Explain folder layout: `downloads/merged`, `downloads/raw`, `technical/`
- [ ] Link to Snapchat export steps (Memories + JSON, all ZIP parts)
- [ ] Troubleshooting: overlays, corrupt files, staging disk space

---

## 6. Competitive positioning (critical review)

| Feature | **SMD (yours)** | **SnapEasy** | **Snapy.io / online tools** | **Manual / ZIP only** |
|--------|-----------------|--------------|----------------------------|------------------------|
| 2026 bundled multi-ZIP export | ✅ Native | ✅ | Varies | ❌ Manual extract |
| Offline after export download | ✅ | ✅ | ❌ Upload to cloud | ✅ |
| Overlay merge (filters/text) | ✅ ffmpeg + PIL | ✅ | ✅ | ❌ |
| Raw + merged outputs | ✅ Both | Often one | Varies | Raw only |
| GPS / date metadata | ✅ EXIF + MP4 tags | ✅ | Partial | ❌ |
| Unique filenames (no overwrites) | ✅ v3 naming | Unknown | Unknown | ❌ Collisions |
| Resume / checkpoint | ✅ | Partial | N/A | ❌ |
| Staging verify before delete | ✅ | ❌ | N/A | ❌ |
| Duplicate review + delete | ✅ User-controlled | ❌ | ❌ | ❌ |
| Output integrity checks | ✅ | Unknown | Unknown | ❌ |
| Open source / self-hosted | ✅ | ❌ | ❌ | N/A |
| Windows desktop GUI | ✅ | ✅ | Web | ❌ |
| Link-only export (URLs, no ZIP media) | ❌ Not supported | ✅ | ✅ | ❌ |

**Honest gaps to improve before marketing as “best”:**

1. **UI polish** — theme system added; still PyQt5 widgets (not Flutter/Electron-level polish)
2. **macOS / Linux** — Windows-first today
3. **One-click installer** — MSI/Inno Setup vs zip + bat
4. **Duplicate deletion is permanent** — user selects keepers and confirms (by design; no undo)
5. **HEIC/WebP viewer compatibility** — some Windows apps struggle; JPG is safest for merged
6. ~~**Video quality vs size** — CRF 0 is lossless but huge~~ — fixed: overlay merges now use CRF 16 (VMAF-verified 99.9+ visually lossless vs the old CRF 0 output), cutting overlay video size by ~85-90% with no perceptible quality loss

**Strengths to highlight:**

- Built for **your** exact pain (400+ hours, 2026 export format, no CDN links)
- **Transparent** folder layout (`technical/` visible, not hidden)
- **Safety nets**: staging verify, corrupt JPEG guard, checkpoint repair
- **No upload** — privacy vs cloud converters

---

## 7. Release day

- [ ] Write GitHub release notes (what changed, known limits)
- [ ] Post short demo GIF (ZIP select → process → merged folder)
- [ ] Optional: las-hs.com project page linking to repo + donate
- [ ] Monitor first issues: corrupt files, theme, disk space

---

## 8. After publish (maintenance)

- [ ] Issue template: export type, ZIP count, error log from `technical/logs/`
- [ ] Bump version for overlay/quality fixes
- [ ] Keep `PRE_PUBLISH.md` updated when adding features

---

*Last updated: July 2026 — Las HS / SMD*
