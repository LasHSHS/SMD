import json
from pathlib import Path

from smd.models import Memory


def detect_ext_from_bytes(data: bytes) -> str | None:
    """Detect file type from magic bytes. Returns actual extension, not forced conversion."""
    if not data or len(data) < 4:
        return None
    # JPEG
    if data.startswith(b"\xff\xd8\xff"):
        return ".jpg"
    # PNG
    if data.startswith(b"\x89PNG\r\n\x1a\n"):
        return ".png"
    # WebP
    if data.startswith(b"RIFF") and len(data) >= 12 and data[8:12] == b"WEBP":
        return ".webp"
    # GIF
    if data.startswith(b"GIF87a") or data.startswith(b"GIF89a"):
        return ".gif"
    # MP4/HEIC/MOV (all use ftyp - need to check brand)
    if len(data) >= 12 and data[4:8] == b"ftyp":
        brand = data[8:12].decode('latin1', errors='ignore').strip()
        # HEIC variants
        if brand in ["heix", "heic", "mif1"]:
            return ".heic"
        # QuickTime/MOV variants
        elif brand in ["qt  ", "mdat"]:
            return ".mov"
        # MP4 variants (most common)
        else:
            return ".mp4"
    # AVI
    if data.startswith(b"RIFF") and len(data) >= 12 and data[8:12] == b"AVI ":
        return ".avi"
    # Matroska (MKV)
    if data.startswith(b"\x1a\x45\xdf\xa3"):
        return ".mkv"
    # BMP
    if data.startswith(b"BM"):
        return ".bmp"
    # ZIP
    if data.startswith(b"PK\x03\x04"):
        return ".zip"
    return None


class MemoriesJsonError(ValueError):
    """memories_history.json exists but cannot be parsed."""


def load_memories(json_path: Path) -> list[Memory]:
    """Load memory records from memories_history.json.

    Raises FileNotFoundError if the file is missing and MemoriesJsonError if it
    is present but not valid JSON, so callers can show a real error instead of
    treating a corrupt export as an empty library.
    """
    if not json_path.exists():
        raise FileNotFoundError(f"Memories JSON not found: {json_path}")
    if json_path.stat().st_size == 0:
        return []
    try:
        with open(json_path, "r", encoding="utf-8") as f:
            data = json.load(f)
    except json.JSONDecodeError as e:
        raise MemoriesJsonError(
            f"memories_history.json is not valid JSON ({e}). "
            "The export may be corrupt - re-download it from Snapchat."
        ) from e
    items = data.get("Saved Media")
    if not isinstance(items, list):
        return []
    memories: list[Memory] = []
    skipped = 0
    for item in items:
        try:
            memories.append(Memory(**item))
        except Exception:
            skipped += 1
    if skipped:
        print(f"Warning: skipped {skipped} malformed entries in {json_path.name}")
    return memories
