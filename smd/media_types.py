"""Shared media extension constants for File Checker and scanners."""
from __future__ import annotations

from pathlib import Path

IMAGE_EXTENSIONS = frozenset({".jpg", ".jpeg", ".png", ".heic"})
VIDEO_EXTENSIONS = frozenset({".mp4", ".mov", ".m4v"})
MEDIA_EXTENSIONS = IMAGE_EXTENSIONS | VIDEO_EXTENSIONS

# Magic-byte extension check (subset used by legacy ScanWorker)
MAGIC_CHECK_EXTENSIONS = frozenset({".jpg", ".jpeg", ".mp4", ".m4v"})


def is_media_file(path: Path) -> bool:
    return path.is_file() and path.suffix.lower() in MEDIA_EXTENSIONS


def is_image_file(path: Path) -> bool:
    return path.is_file() and path.suffix.lower() in IMAGE_EXTENSIONS


def is_video_file(path: Path) -> bool:
    return path.is_file() and path.suffix.lower() in VIDEO_EXTENSIONS


def format_bytes(bytes_val: float) -> str:
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if bytes_val < 1024:
            return f"{bytes_val:.1f} {unit}"
        bytes_val /= 1024
    return f"{bytes_val:.1f} PB"


def extension_matches_magic(suffix: str, actual_type: str | None) -> bool:
    """True when filename extension matches detected magic-byte type."""
    if actual_type is None:
        return True
    suffix = suffix.lower()
    if actual_type == "jpg":
        return suffix in (".jpg", ".jpeg")
    if actual_type == "mp4":
        return suffix in (".mp4", ".m4v")
    return True
