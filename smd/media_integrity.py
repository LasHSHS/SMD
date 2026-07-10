"""Media file validation helpers — prevent corrupt outputs."""
from __future__ import annotations

from pathlib import Path

MIN_IMAGE_BYTES = 512
JPEG_SOI = b"\xff\xd8"
PNG_SIG = b"\x89PNG\r\n\x1a\n"


def validate_image_file(path: Path) -> tuple[bool, str]:
    """Return (ok, reason). Uses magic bytes + Pillow load."""
    try:
        if not path.is_file():
            return False, "missing"
        size = path.stat().st_size
        if size < MIN_IMAGE_BYTES:
            return False, f"too_small ({size} bytes)"
        head = path.read_bytes()[:16]
        ext = path.suffix.lower()
        if ext in (".jpg", ".jpeg"):
            if not head.startswith(JPEG_SOI):
                return False, f"bad_jpeg_header ({head[:4].hex()})"
        elif ext == ".png" and not head.startswith(PNG_SIG):
            return False, "bad_png_header"

        from PIL import Image

        with Image.open(path) as im:
            im.load()
        return True, "ok"
    except Exception as exc:
        return False, str(exc)


def validate_video_file(path: Path) -> tuple[bool, str]:
    try:
        if not path.is_file():
            return False, "missing"
        if path.stat().st_size < MIN_IMAGE_BYTES:
            return False, "too_small"
        head = path.read_bytes()[:12]
        if head[4:8] == b"ftyp" or head[:4] == b"\x1aE\xdf\xa3":
            return True, "ok"
        return False, "unrecognized_video_header"
    except Exception as exc:
        return False, str(exc)


def validate_media_file(path: Path) -> tuple[bool, str]:
    ext = path.suffix.lower()
    if ext in (".jpg", ".jpeg", ".png", ".webp", ".gif", ".heic"):
        return validate_image_file(path)
    if ext in (".mp4", ".mov", ".m4v", ".mkv", ".avi"):
        return validate_video_file(path)
    return True, "skipped"
