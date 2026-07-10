"""Detect duplicate content and collect copies for manual review."""
from __future__ import annotations

import hashlib
import json
import shutil
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path

from smd.account_layout import AccountPaths


@dataclass
class DuplicateEntry:
    filename: str
    duplicate_of: str
    sha256: str
    moved_to: str | None = None


@dataclass
class DuplicateScanReport:
    scanned_at: str
    merged_scanned: int = 0
    duplicate_groups: int = 0
    files_moved: int = 0
    entries: list[DuplicateEntry] = field(default_factory=list)

    def to_dict(self) -> dict:
        data = asdict(self)
        return data


def _file_hash(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def load_cached_duplicate_group_count(paths: AccountPaths) -> int:
    """Read duplicate_groups from a prior scan without re-hashing merged/."""
    report = load_cached_duplicate_report(paths)
    return report.duplicate_groups if report else 0


def load_cached_duplicate_report(paths: AccountPaths) -> DuplicateScanReport | None:
    """Load duplicates_report.json from the last scan."""
    report_path = paths.reports_dir / "duplicates_report.json"
    if not report_path.is_file():
        return None
    try:
        data = json.loads(report_path.read_text(encoding="utf-8"))
        entries = [
            DuplicateEntry(
                filename=e["filename"],
                duplicate_of=e["duplicate_of"],
                sha256=e["sha256"],
                moved_to=e.get("moved_to"),
            )
            for e in data.get("entries", [])
        ]
        return DuplicateScanReport(
            scanned_at=data.get("scanned_at", ""),
            merged_scanned=int(data.get("merged_scanned", 0) or 0),
            duplicate_groups=int(data.get("duplicate_groups", 0) or 0),
            files_moved=int(data.get("files_moved", 0) or 0),
            entries=entries,
        )
    except (OSError, json.JSONDecodeError, TypeError, ValueError, KeyError):
        return None


def scan_content_duplicates(
    paths: AccountPaths,
    *,
    move_to_folder: bool = False,
    status_callback: Callable[[str], None] | None = None,
    hash_workers: int = 4,
) -> DuplicateScanReport:
    """
    Find byte-identical files in `merged/`.

    Only scans `downloads/merged/` — not `raw/`. Two files are duplicates only when
    every byte matches (same photo/video saved twice under different names).

    If `move_to_folder=True`, copy the *entire duplicate groups* (every file in each
    identical-content group) into `downloads/duplicates/` for manual assessment.

    If `move_to_folder=False`, no files are written/mutated; only a JSON report is produced.
    """
    def status(msg: str) -> None:
        if status_callback:
            status_callback(msg)

    report = DuplicateScanReport(scanned_at=datetime.now(timezone.utc).isoformat())
    merged = paths.merged_dir
    if not merged.is_dir():
        return report

    duplicates_dir = paths.downloads_dir / "duplicates"

    files = sorted(p for p in merged.iterdir() if p.is_file())
    total = len(files)
    if not files:
        return report

    status(f"Checking for duplicate files (0/{total})...")
    digest_to_files: dict[str, list[Path]] = {}
    workers = max(1, min(int(hash_workers), 16))
    progress_every = max(25, total // 40)
    done = 0

    if workers == 1 or total < 50:
        for path in files:
            digest = _file_hash(path)
            digest_to_files.setdefault(digest, []).append(path)
            done += 1
            report.merged_scanned = done
            if done == 1 or done == total or done % progress_every == 0:
                status(f"Checking for duplicate files ({done}/{total})...")
    else:
        with ThreadPoolExecutor(max_workers=workers) as executor:
            futures = {executor.submit(_file_hash, path): path for path in files}
            for fut in as_completed(futures):
                path = futures[fut]
                digest = fut.result()
                digest_to_files.setdefault(digest, []).append(path)
                done += 1
                report.merged_scanned = done
                if done == 1 or done == total or done % progress_every == 0:
                    status(f"Checking for duplicate files ({done}/{total})...")

    # Optional second pass: copy entire duplicate groups out for inspection.
    if move_to_folder:
        duplicates_dir.mkdir(parents=True, exist_ok=True)

    for digest, files in sorted(digest_to_files.items(), key=lambda kv: kv[0]):
        if len(files) < 2:
            continue

        report.duplicate_groups += 1
        rep = sorted(files, key=lambda p: p.name)[0].name  # deterministic representative name

        # Stable order for easier review.
        for path in sorted(files, key=lambda p: p.name):
            moved_to = None
            if move_to_folder:
                group_dir = duplicates_dir / digest[:16]
                group_dir.mkdir(parents=True, exist_ok=True)

                dest = group_dir / path.name
                if dest.exists():
                    # Extremely defensive: keep multiple copies even if filenames collide.
                    dest = group_dir / f"{path.stem}_dup{report.files_moved + 1}{path.suffix}"

                shutil.copy2(str(path), str(dest))
                moved_to = str(dest)
                report.files_moved += 1

            report.entries.append(
                DuplicateEntry(
                    filename=path.name,
                    duplicate_of=rep,
                    sha256=digest[:16],
                    moved_to=moved_to,
                )
            )

    paths.reports_dir.mkdir(parents=True, exist_ok=True)
    (paths.reports_dir / "duplicates_report.json").write_text(
        json.dumps(report.to_dict(), indent=2),
        encoding="utf-8",
    )
    return report
