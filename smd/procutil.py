"""Shared subprocess helpers for bundled tools (ffmpeg/ffprobe)."""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path


def subprocess_flags() -> tuple[object | None, int]:
    """Hide console windows for child processes on Windows."""
    startupinfo = None
    creationflags = 0
    if sys.platform.startswith("win"):
        startupinfo = subprocess.STARTUPINFO()
        startupinfo.dwFlags |= subprocess.STARTF_USESHOWWINDOW
        creationflags = subprocess.CREATE_NO_WINDOW
    return startupinfo, creationflags


def run_tool(cmd: list[str], *, timeout: float) -> subprocess.CompletedProcess | None:
    """Run a bundled tool quietly; returns None on timeout/OS error."""
    startupinfo, creationflags = subprocess_flags()
    try:
        return subprocess.run(
            cmd,
            capture_output=True,
            startupinfo=startupinfo,
            creationflags=creationflags,
            timeout=timeout,
        )
    except (subprocess.TimeoutExpired, OSError):
        return None


def ffprobe_stream_ok(path: Path, *, timeout: float = 20.0) -> bool | None:
    """Deep-check a video with ffprobe.

    Returns True/False for a definitive answer, or None when ffprobe is not
    available (callers should fall back to header checks).
    """
    from smd.ffmpeg_bundle import resolve_ffprobe

    ffprobe = resolve_ffprobe()
    if not ffprobe:
        return None
    r = run_tool(
        [
            ffprobe,
            "-v", "error",
            "-show_entries", "format=duration",
            "-of", "default=noprint_wrappers=1",
            str(path),
        ],
        timeout=timeout,
    )
    if r is None:
        return None
    if r.returncode != 0:
        return False
    return b"duration=" in (r.stdout or b"")
