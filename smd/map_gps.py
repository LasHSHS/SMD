"""GPS lookup helpers for the File Checker map."""
from __future__ import annotations

import re
from pathlib import Path

from smd.models import Memory

_DATE_STEM_RE = re.compile(r"^(\d{4}-\d{2}-\d{2}_\d{2}-\d{2}-\d{2})")


def build_json_coord_lookup(memories: list[Memory]) -> dict[str, tuple[float, float]]:
    """Index JSON memories by every filename stem we might see on disk."""
    lookup: dict[str, tuple[float, float]] = {}
    for memory in memories:
        if memory.latitude is None or memory.longitude is None:
            continue
        coords = (float(memory.latitude), float(memory.longitude))
        keys = {
            memory.filename,
            memory.date.strftime("%Y-%m-%d_%H-%M-%S"),
        }
        for key in keys:
            if key:
                lookup[key] = coords
    return lookup


def lookup_json_coords(
    lookup: dict[str, tuple[float, float]],
    file_path: Path,
) -> tuple[float, float] | None:
    """Match a media file to JSON GPS using exact or date-based stems."""
    if not lookup:
        return None

    stem = file_path.stem
    if stem in lookup:
        return lookup[stem]

    match = _DATE_STEM_RE.match(stem)
    if match and match.group(1) in lookup:
        return lookup[match.group(1)]

    return None


def resolve_memories_json(scan_folder: str | Path | None) -> Path | None:
    """Find memories_history.json for a scanned folder or account tree."""
    if not scan_folder:
        return None

    folder_path = Path(scan_folder).resolve()
    for parent in (folder_path, *folder_path.parents):
        for relative in (
            Path("technical") / "json" / "memories_history.json",
            Path("json") / "memories_history.json",
            Path("memories_history.json"),
        ):
            candidate = parent / relative
            if candidate.is_file():
                return candidate
    return None
