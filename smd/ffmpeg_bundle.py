"""Resolve bundled ffmpeg/ffprobe (all-in-one SMD package) or system PATH fallback."""
from __future__ import annotations

import shutil
import subprocess
import sys
from pathlib import Path

from smd.runtime import app_root, bundled_dir, is_frozen


def _bundled_tool_dir() -> Path:
    found = bundled_dir("tools", "ffmpeg")
    if found and (found / "ffmpeg.exe").is_file():
        return found
    return app_root() / "tools" / "ffmpeg"


def resolve_ffmpeg() -> str | None:
    """Path to ffmpeg executable, or None if unavailable."""
    bundled = _bundled_tool_dir() / "ffmpeg.exe"
    if bundled.is_file():
        return str(bundled)
    return shutil.which("ffmpeg")


def resolve_ffprobe() -> str | None:
    """Path to ffprobe executable, or None if unavailable."""
    bundled = _bundled_tool_dir() / "ffprobe.exe"
    if bundled.is_file():
        return str(bundled)
    return shutil.which("ffprobe")


def ffmpeg_available() -> bool:
    return resolve_ffmpeg() is not None


def ffprobe_available() -> bool:
    return resolve_ffprobe() is not None


def verify_tool(exe_path: str | None, version_args: tuple[str, ...] = ("-version",)) -> bool:
    if not exe_path:
        return False
    try:
        r = subprocess.run(
            [exe_path, *version_args],
            capture_output=True,
            timeout=8,
        )
        return r.returncode == 0
    except (FileNotFoundError, subprocess.TimeoutExpired, OSError):
        return False


def bundled_status() -> dict[str, str]:
    """Human-readable status for About / startup checks."""
    ff = resolve_ffmpeg()
    fp = resolve_ffprobe()
    bundled_dir_path = _bundled_tool_dir()
    using_bundle = (bundled_dir_path / "ffmpeg.exe").is_file()
    if is_frozen():
        source = "bundled" if using_bundle else "missing from package"
    else:
        source = "bundled" if using_bundle else "system PATH"
    return {
        "source": source,
        "frozen": is_frozen(),
        "ffmpeg": "ok" if verify_tool(ff) else "missing",
        "ffprobe": "ok" if verify_tool(fp) else "missing",
        "ffmpeg_path": ff or "",
        "ffprobe_path": fp or "",
    }
