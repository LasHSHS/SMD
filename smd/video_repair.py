"""Best-effort repair for corrupt/incomplete video files."""
from __future__ import annotations

import shutil
import subprocess
import sys
from pathlib import Path

from smd.utils import detect_ext_from_bytes
from smd.ffmpeg_bundle import resolve_ffmpeg
from smd.procutil import subprocess_flags as _subprocess_flags


def is_likely_corrupt_video(path: Path, min_bytes: int = 1024) -> bool:
    """Heuristic: tiny file or not a recognizable video container."""
    try:
        if path.stat().st_size < min_bytes:
            return True
        head = path.read_bytes()[:16]
        ext = detect_ext_from_bytes(head)
        return ext not in (".mp4", ".mov", ".mkv", ".avi")
    except OSError:
        return True


def repair_video(
    input_path: Path,
    output_path: Path,
    *,
    threads: int | None = None,
) -> tuple[bool, str]:
    """
    Try ffmpeg stream copy first, then re-encode.
    Returns (success, method_or_error).
    """
    ffmpeg = resolve_ffmpeg()
    if not ffmpeg:
        return False, "ffmpeg not available"

    startupinfo, creationflags = _subprocess_flags()
    output_path.parent.mkdir(parents=True, exist_ok=True)

    thread_args: list[str] = []
    if threads and threads > 0:
        thread_args = ["-threads", str(threads)]

    copy_cmd = [
        ffmpeg,
        "-nostdin",
        "-y",
        *thread_args,
        "-err_detect",
        "ignore_err",
        "-i",
        str(input_path),
        "-c",
        "copy",
        "-movflags",
        "+faststart",
        str(output_path),
    ]
    try:
        r = subprocess.run(
            copy_cmd,
            capture_output=True,
            startupinfo=startupinfo,
            creationflags=creationflags,
            timeout=300,
        )
        if r.returncode == 0 and output_path.exists() and output_path.stat().st_size > 512:
            return True, "copy"
    except (subprocess.TimeoutExpired, OSError) as e:
        return False, str(e)

    if output_path.exists():
        output_path.unlink(missing_ok=True)

    encode_cmd = [
        ffmpeg,
        "-nostdin",
        "-y",
        *thread_args,
        "-i",
        str(input_path),
        "-c:v",
        "libx264",
        "-preset",
        "fast",
        "-crf",
        "18",
        "-c:a",
        "aac",
        "-movflags",
        "+faststart",
        str(output_path),
    ]
    try:
        r = subprocess.run(
            encode_cmd,
            capture_output=True,
            startupinfo=startupinfo,
            creationflags=creationflags,
            timeout=900,
        )
        if r.returncode == 0 and output_path.exists() and output_path.stat().st_size > 512:
            return True, "reencode"
        err = (r.stderr or b"").decode("utf-8", errors="replace")[-200:]
        return False, err or "ffmpeg failed"
    except (subprocess.TimeoutExpired, OSError) as e:
        return False, str(e)
