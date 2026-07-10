# Bundled FFmpeg (Windows)

SMD ships **ffmpeg** and **ffprobe** here so end users do not install anything extra.

## For developers / release builds

Run from project root:

```powershell
powershell -ExecutionPolicy Bypass -File .\scripts\fetch_ffmpeg.ps1
```

Or build with `build_smd.ps1` — it fetches ffmpeg automatically if missing.

Expected files after fetch:

- `ffmpeg.exe`
- `ffprobe.exe`
- supporting `.dll` files from the essentials build

## License

FFmpeg is licensed under LGPL/GPL. Source and license: https://ffmpeg.org/legal.html

The official SMD installer must include FFmpeg license notices (see `DISTRIBUTION_GUIDE.md`).
