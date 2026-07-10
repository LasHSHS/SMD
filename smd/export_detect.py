"""Detect Snapchat export format (bundled local media vs unsupported link-only)."""
from __future__ import annotations

import json
import re
import zipfile
from dataclasses import dataclass
from enum import Enum
from pathlib import Path


class ExportFormat(str, Enum):
    BUNDLED_LOCAL = "bundled_local"
    LINKS_ONLY = "links_only"
    JSON_ONLY = "json_only"
    EMPTY = "empty"


@dataclass
class ExportAnalysis:
    format: ExportFormat
    json_rows: int = 0
    rows_with_link: int = 0
    https_count: int = 0
    embedded_media_count: int = 0
    main_file_count: int = 0
    overlay_file_count: int = 0
    zip_paths: list[Path] | None = None
    json_path: Path | None = None
    message: str = ""

    @property
    def is_bundled(self) -> bool:
        return self.format == ExportFormat.BUNDLED_LOCAL

    @property
    def is_supported(self) -> bool:
        return self.is_bundled

    @property
    def has_links(self) -> bool:
        return self.rows_with_link > 0


def _count_links_in_json_text(raw: str) -> tuple[int, int]:
    https = len(re.findall(r"https://", raw))
    try:
        data = json.loads(raw)
    except json.JSONDecodeError:
        return 0, https
    rows = data.get("Saved Media", data if isinstance(data, list) else [])
    if not isinstance(rows, list):
        rows = []
    with_link = sum(
        1
        for r in rows
        if isinstance(r, dict) and (r.get("Download Link") or r.get("Media Download Url") or "").strip()
    )
    return len(rows), with_link


def discover_export_zip_parts(seed: Path) -> list[Path]:
    """Find all parts of a split Snapchat export (mydata~ID.zip, mydata~ID-2.zip, ...)."""
    seed = seed.resolve()
    if seed.is_dir():
        zips = sorted(seed.glob("mydata*.zip"), key=_zip_sort_key)
        return zips if zips else sorted(seed.glob("*.zip"), key=_zip_sort_key)

    if not seed.suffix.lower() == ".zip":
        return []

    parent = seed.parent
    stem = seed.stem  # e.g. mydata~1783373820861 or mydata~1783373820861-2
    base_match = re.match(r"(mydata~\d+)", stem, re.I)
    if not base_match:
        return [seed]

    base = base_match.group(1)
    parts = sorted(parent.glob(f"{base}*.zip"), key=_zip_sort_key)
    return parts if parts else [seed]


def resolve_export_zip_paths(seed: Path | list[Path]) -> list[Path]:
    """
    Resolve ZIP parts from a folder, one file (auto-find siblings), or explicit multi-select.
    """
    if isinstance(seed, list):
        paths = [Path(p).resolve() for p in seed if Path(p).suffix.lower() == ".zip"]
        if not paths:
            return []
        if len(paths) == 1:
            return discover_export_zip_parts(paths[0])
        return sorted(paths, key=_zip_sort_key)
    return discover_export_zip_parts(Path(seed))


def export_base_ids(zip_paths: list[Path]) -> set[str]:
    """Return mydata~ID bases for validation when user picks multiple files."""
    bases: set[str] = set()
    for p in zip_paths:
        m = re.match(r"(mydata~\d+)", p.stem, re.I)
        bases.add(m.group(1) if m else p.stem)
    return bases


def _zip_sort_key(p: Path) -> tuple:
    # Base part (mydata~ID.zip) sorts before numbered parts (…-2.zip, …-3.zip);
    # lowercase name is a stable tiebreaker so generic *.zip lists stay ordered.
    m = re.search(r"-(\d+)\.zip$", p.name, re.I)
    order = (0, 0) if m is None else (1, int(m.group(1)))
    return (*order, p.name.lower())


def analyze_zip_export(seed_path: Path | list[Path]) -> ExportAnalysis:
    """Analyze export from ZIP file(s) or a folder containing ZIPs."""
    zip_paths = resolve_export_zip_paths(
        seed_path if isinstance(seed_path, list) else Path(seed_path)
    )
    if not zip_paths:
        return ExportAnalysis(ExportFormat.EMPTY, message="No ZIP files found.")

    json_rows = 0
    rows_with_link = 0
    https_count = 0
    embedded = 0
    main_count = 0
    overlay_count = 0
    json_path: Path | None = None

    for zpath in zip_paths:
        try:
            with zipfile.ZipFile(zpath, "r") as zf:
                names = zf.namelist()
                if json_path is None:
                    jmembers = [n for n in names if n.lower().endswith("memories_history.json")]
                    if jmembers:
                        raw = zf.read(jmembers[0]).decode("utf-8", errors="replace")
                        json_rows, link_n = _count_links_in_json_text(raw)
                        rows_with_link = max(rows_with_link, link_n)
                        https_count = max(https_count, len(re.findall(r"https://", raw)))

                for n in names:
                    if not n.startswith("memories/") or n.endswith("/"):
                        continue
                    embedded += 1
                    low = n.lower()
                    if "-main." in low:
                        main_count += 1
                    elif "-overlay." in low:
                        overlay_count += 1
        except zipfile.BadZipFile:
            continue

    if json_rows == 0:
        fmt = ExportFormat.EMPTY
        msg = "No memories_history.json found in export."
    elif main_count > 0 or embedded > 0:
        fmt = ExportFormat.BUNDLED_LOCAL
        msg = (
            f"Bundled export: {main_count} main files across {len(zip_paths)} ZIP(s), "
            f"{json_rows} JSON rows. Processing is fully offline."
        )
    elif rows_with_link > 0:
        fmt = ExportFormat.LINKS_ONLY
        msg = (
            f"Link-only export: {rows_with_link} JSON rows with download URLs, "
            "but no media files inside the ZIP. SMD only supports bundled exports."
        )
    else:
        fmt = ExportFormat.JSON_ONLY
        msg = (
            f"JSON-only export ({json_rows} rows). No bundled media files in the ZIP. "
            "Request a new Snapchat export with memories included."
        )

    return ExportAnalysis(
        format=fmt,
        json_rows=json_rows,
        rows_with_link=rows_with_link,
        https_count=https_count,
        embedded_media_count=embedded,
        main_file_count=main_count,
        overlay_file_count=overlay_count,
        zip_paths=zip_paths,
        json_path=json_path,
        message=msg,
    )


def extract_json_from_zips(zip_paths: list[Path], dest: Path) -> Path:
    """Extract memories_history.json from first ZIP that contains it."""
    from smd.fsutil import atomic_write_bytes

    dest.parent.mkdir(parents=True, exist_ok=True)
    for zpath in zip_paths:
        with zipfile.ZipFile(zpath, "r") as zf:
            member = next((n for n in zf.namelist() if n.lower().endswith("memories_history.json")), None)
            if member:
                data = zf.read(member)
                atomic_write_bytes(dest, data)
                return dest
    raise FileNotFoundError("memories_history.json not found in any ZIP.")
