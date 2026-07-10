"""Merge Snapchat -main and -overlay export files."""
from __future__ import annotations

import shutil
import subprocess
import sys
from pathlib import Path

from PIL import Image

from smd.ffmpeg_bundle import resolve_ffmpeg

# Maximum practical quality for export outputs
JPEG_QUALITY = 100
# x264 CRF 0 = lossless (large files); use 1 for near-lossless if size explodes
VIDEO_CRF = 0


def _subprocess_flags():
    startupinfo = None
    creationflags = 0
    if sys.platform.startswith("win"):
        startupinfo = subprocess.STARTUPINFO()
        startupinfo.dwFlags |= subprocess.STARTF_USESHOWWINDOW
        creationflags = subprocess.CREATE_NO_WINDOW
    return startupinfo, creationflags


def merge_image_overlay(main_path: Path, overlay_path: Path, output_path: Path) -> bool:
    """Composite PNG overlay onto image; save to output_path."""
    try:
        base = Image.open(main_path).convert("RGBA")
        overlay = Image.open(overlay_path).convert("RGBA")
        if overlay.size != base.size:
            overlay = overlay.resize(base.size, Image.Resampling.LANCZOS)
        merged = Image.alpha_composite(base, overlay)
        out_ext = output_path.suffix.lower()
        if out_ext in (".jpg", ".jpeg"):
            merged.convert("RGB").save(output_path, quality=JPEG_QUALITY, subsampling=0)
        elif out_ext == ".webp":
            merged.convert("RGB").save(
                output_path.with_suffix(".jpg"),
                quality=JPEG_QUALITY,
                subsampling=0,
            )
        else:
            merged.save(output_path)
        return True
    except Exception:
        return False


def merge_video_overlay(
    main_path: Path,
    overlay_path: Path,
    output_path: Path,
    *,
    threads: int | None = None,
) -> bool:
    """Burn PNG overlay onto video using ffmpeg overlay filter."""
    from smd.gpu_encode import detect_video_encode_profiles

    ffmpeg = resolve_ffmpeg()
    if not ffmpeg:
        return False
    startupinfo, creationflags = _subprocess_flags()

    for profile in detect_video_encode_profiles(ffmpeg):
        cmd = [
            ffmpeg,
            "-nostdin",
            "-y",
        ]
        if threads and threads > 0 and profile.id == "cpu_lossless":
            cmd.extend(["-threads", str(threads)])
        cmd.extend(
            [
                "-i",
                str(main_path),
                "-i",
                str(overlay_path),
                "-filter_complex",
                "overlay=0:0",
                *profile.args,
                "-c:a",
                "copy",
                str(output_path),
            ]
        )
        try:
            r = subprocess.run(
                cmd,
                capture_output=True,
                startupinfo=startupinfo,
                creationflags=creationflags,
                timeout=300,
            )
            if r.returncode == 0 and output_path.exists() and output_path.stat().st_size > 0:
                return True
        except (subprocess.TimeoutExpired, OSError):
            continue
        if output_path.exists():
            try:
                output_path.unlink()
            except OSError:
                pass
    return False
