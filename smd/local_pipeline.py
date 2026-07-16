"""Process bundled Snapchat exports (multi-ZIP, local memories/ folder)."""
from __future__ import annotations

import json
import os
import re
import shutil
import threading
import zipfile
from collections import defaultdict
from concurrent.futures import FIRST_COMPLETED, ThreadPoolExecutor, wait
from dataclasses import dataclass, field, asdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable

from smd.export_detect import discover_export_zip_parts, extract_json_from_zips
from smd.account_layout import AccountPaths, normalize_account_dir, resolve_account_paths, LEGACY_STAGING
from smd.metadata import (
    apply_metadata,
    copy_video_with_metadata,
    read_video_capture_time,
    video_metadata_ffmpeg_flags,
)
from smd.models import Memory
from smd.overlays import merge_image_overlay, merge_video_overlay
from smd.utils import detect_ext_from_bytes, load_memories
from smd.video_repair import is_likely_corrupt_video, repair_video
from smd.media_integrity import validate_media_file

MEDIA_RE = re.compile(
    r"^(?P<date>\d{4}-\d{2}-\d{2})_(?P<uid>[0-9A-Fa-f-]+)-(?P<role>main|overlay)\.(?P<ext>[A-Za-z0-9]+)$",
    re.I,
)


@dataclass
class LocalProcessStats:
    zips_processed: int = 0
    files_extracted: int = 0
    duplicates_skipped: int = 0
    merged: int = 0
    raw_copied: int = 0
    metadata_applied: int = 0
    overlays_missing: int = 0
    repaired_videos: int = 0
    quarantined: int = 0
    failed: int = 0
    json_matched: int = 0
    json_unmatched: int = 0
    collision_groups: int = 0
    files_disambiguated: int = 0
    collision_avoided: int = 0
    integrity_repairs: int = 0

    def summary_lines(self) -> list[str]:
        lines = [
            f"ZIP parts processed: {self.zips_processed}",
            f"Media files extracted: {self.files_extracted} (duplicates skipped: {self.duplicates_skipped})",
            f"Merged (overlay baked): {self.merged}",
            f"Raw copies: {self.raw_copied}",
            f"Metadata applied: {self.metadata_applied}",
            f"Overlays missing: {self.overlays_missing}",
            f"Videos repaired: {self.repaired_videos}",
            f"Quarantined: {self.quarantined}",
            f"Failed: {self.failed}",
            f"JSON matched: {self.json_matched} / unmatched: {self.json_unmatched}",
        ]
        if self.collision_groups:
            lines.append(
                f"Filename collisions resolved: {self.collision_groups} groups, "
                f"{self.files_disambiguated} disambiguated names"
            )
        if self.collision_avoided:
            lines.append(f"Runtime collision guards triggered: {self.collision_avoided}")
        if self.integrity_repairs:
            lines.append(f"Output integrity repairs: {self.integrity_repairs}")
        return lines


@dataclass
class BundledMediaItem:
    stem: str
    date_prefix: str
    uid: str
    main_path: Path | None = None
    overlay_path: Path | None = None
    main_ext: str = ".mp4"


def _media_type_from_ext(ext: str) -> str:
    return "Video" if ext.lower() in (".mp4", ".mov", ".m4v", ".avi", ".mkv") else "Image"


def _normalize_media_type(value: str | None) -> str:
    if not value:
        return "image"
    low = value.lower()
    return "video" if low.startswith("vid") else "image"


def _memory_type_key(memory: Memory) -> str:
    if memory.media_type:
        return _normalize_media_type(memory.media_type)
    if memory.download_link and ".mp4" in memory.download_link.lower():
        return "video"
    if memory.media_download_url and ".mp4" in (memory.media_download_url or "").lower():
        return "video"
    return "image"


_MID_RE = re.compile(r"[?&]mid=([^&]+)", re.I)


def _memory_media_id(memory: Memory) -> str | None:
    """Snapchat media id (mid=) from export JSON URLs."""
    for url in (memory.download_link, memory.media_download_url or ""):
        if not url:
            continue
        match = _MID_RE.search(url)
        if match:
            return match.group(1).lower()
    return None


def build_deterministic_match_map(
    items: dict[str, BundledMediaItem],
    memories: list[Memory],
    *,
    probe_workers: int | None = None,
) -> dict[str, Memory | None]:
    """
    Pair bundled files to JSON rows within the same (date, media-type)
    bucket, used when a file has no Snapchat media id to match on (see
    ``build_match_map``).

    Videos: sorted by each file's own embedded ``creation_time`` (read
    straight off the staged file, before SMD writes anything) when ffprobe
    can read one. This is the phone's own recorded capture instant, and it
    reliably tracks the same chronological order as the JSON rows' ``Date``
    field even though the two are never identical (Date lags capture by a
    roughly consistent 15-40s "saved to memories" delay). Any video ffprobe
    can't read falls back to UID-stem order, sorted after all timed videos
    so it can't silently displace one that IS correctly ordered.

    Images: Snapchat strips EXIF entirely from exported photos - there is
    no per-file signal to sort by, so this remains UID-stem order and can
    still mismatch same-day multi-photo bursts. See agent-docs/DECISIONS.md
    ("2026-07-14 - video matching uses each file's own creation_time") for
    the investigation that found this and why photos can't be fully fixed.

    Stable across runs and resume - no FIFO consumption drift.
    """
    mem_groups: dict[tuple[str, str], list[Memory]] = defaultdict(list)
    for m in memories:
        day = m.date.strftime("%Y-%m-%d")
        mem_groups[(day, _memory_type_key(m))].append(m)
    for group in mem_groups.values():
        group.sort(key=lambda m: m.date)

    item_groups: dict[tuple[str, str], list[tuple[str, BundledMediaItem]]] = defaultdict(list)
    for stem, item in items.items():
        if not item.main_path:
            continue
        mtype = _normalize_media_type(_media_type_from_ext(item.main_ext))
        item_groups[(item.date_prefix, mtype)].append((stem, item))

    # Only bother probing videos in buckets that actually have >1 item -
    # a lone video in its (day, type) bucket has nothing to be mis-ordered
    # against, so skip the ffprobe call entirely for the common case.
    video_stems_to_probe = [
        stem
        for (_, mtype), group in item_groups.items()
        if mtype == "video" and len(group) > 1
        for stem, _ in group
    ]
    capture_times: dict[str, datetime | None] = {}
    if video_stems_to_probe:
        paths = {stem: items[stem].main_path for stem in video_stems_to_probe}
        workers = min(16, max(1, probe_workers or (os.cpu_count() or 8)))
        with ThreadPoolExecutor(max_workers=workers) as pool:
            futures = {
                stem: pool.submit(read_video_capture_time, path)
                for stem, path in paths.items()
            }
            for stem, fut in futures.items():
                try:
                    capture_times[stem] = fut.result()
                except Exception:
                    capture_times[stem] = None

    _NEVER = datetime.max.replace(tzinfo=timezone.utc)
    for (_, mtype), group in item_groups.items():
        if mtype == "video" and len(group) > 1:
            group.sort(
                key=lambda x: (
                    capture_times.get(x[0]) is None,
                    capture_times.get(x[0]) or _NEVER,
                    x[0],
                )
            )
        else:
            group.sort(key=lambda x: x[0])

    match_map: dict[str, Memory | None] = {}
    for key, item_list in item_groups.items():
        mem_list = mem_groups.get(key, [])
        for i, (stem, _) in enumerate(item_list):
            match_map[stem] = mem_list[i] if i < len(mem_list) else None
    return match_map


def build_match_map(
    items: dict[str, BundledMediaItem],
    memories: list[Memory],
    *,
    probe_workers: int | None = None,
) -> dict[str, Memory | None]:
    """Match bundled files to JSON rows by Snapchat media id when possible."""
    match_map: dict[str, Memory | None] = {
        stem: None for stem, item in items.items() if item.main_path
    }
    mid_index: dict[str, Memory] = {}
    for mem in memories:
        mid = _memory_media_id(mem)
        if mid and mid not in mid_index:
            mid_index[mid] = mem

    used: set[int] = set()
    unmatched_stems: list[str] = []
    # Sort by stem (not raw dict/filesystem order) so that when more than one
    # staged item shares a uid, the same one always "wins" the match - dict
    # order here follows directory enumeration order, which is not guaranteed
    # stable across runs/resumes on all filesystems, and a different winner
    # would send a different item through the positional fallback below,
    # producing a different (and wrong, if re-verified later) output name.
    for stem, item in sorted(items.items()):
        if not item.main_path:
            continue
        uid = item.uid.lower()
        mem = mid_index.get(uid)
        if mem is not None and id(mem) not in used:
            match_map[stem] = mem
            used.add(id(mem))
        else:
            unmatched_stems.append(stem)

    if unmatched_stems:
        unmatched_items = {s: items[s] for s in unmatched_stems}
        remaining = [m for m in memories if id(m) not in used]
        fallback = build_deterministic_match_map(
            unmatched_items, remaining, probe_workers=probe_workers
        )
        for stem, mem in fallback.items():
            match_map[stem] = mem

    return match_map


CHECKPOINT_VERSION = 4


def _preferred_output_ext(ext: str) -> str:
    """Normalize export extensions for user-facing library (WebP -> JPEG)."""
    ext = (ext or "").lower()
    if ext == ".webp":
        return ".jpg"
    return ext


def _write_main_to_output(work_main: Path, dest: Path) -> None:
    """Copy or convert main media to dest (WebP sources become JPEG). Atomic."""
    from smd.fsutil import atomic_copy, tmp_sibling

    dest_ext = dest.suffix.lower()
    if work_main.suffix.lower() == ".webp" and dest_ext in (".jpg", ".jpeg"):
        from PIL import Image

        from smd.overlays import JPEG_QUALITY

        tmp = tmp_sibling(dest)
        try:
            Image.open(work_main).convert("RGB").save(
                tmp, format="JPEG", quality=JPEG_QUALITY, subsampling=0
            )
            os.replace(tmp, dest)
        finally:
            if tmp.exists():
                try:
                    tmp.unlink()
                except OSError:
                    pass
        return
    atomic_copy(work_main, dest)


def _base_output_name(memory: Memory | None, item: BundledMediaItem, ext: str) -> str:
    """Preferred output filename (may collide when JSON times match)."""
    if memory:
        return f"{memory.filename}{ext}"
    return f"{item.date_prefix}_{item.uid[:8]}{ext}"


def _disambiguated_name(base_name: str, item: BundledMediaItem) -> str:
    """Unique filename when base_name is shared by multiple export files."""
    stem_part = Path(base_name).stem
    suffix = Path(base_name).suffix
    uid = (item.uid or "").replace("-", "")
    tag = uid[:12] if uid else item.stem.split("_", 1)[-1][:12]
    return f"{stem_part}_{tag}{suffix}"


def build_unique_output_names(
    items: dict[str, BundledMediaItem],
    match_map: dict[str, Memory | None],
) -> tuple[dict[str, str], list[dict]]:
    """
    Assign a unique output filename per stem.
    Returns (stem -> filename, collision groups for reporting).
    """
    stem_base: dict[str, str] = {}
    for stem, item in items.items():
        if not item.main_path:
            continue
        ext = _preferred_output_ext(item.main_ext or item.main_path.suffix.lower())
        item.main_ext = ext
        stem_base[stem] = _base_output_name(match_map.get(stem), item, ext)

    by_base: dict[str, list[str]] = defaultdict(list)
    for stem, base in stem_base.items():
        by_base[base].append(stem)

    unique: dict[str, str] = {}
    collision_report: list[dict] = []

    for base, stems in by_base.items():
        stems_sorted = sorted(stems)
        if len(stems_sorted) == 1:
            unique[stems_sorted[0]] = base
            continue

        outputs: dict[str, str] = {}
        for i, stem in enumerate(stems_sorted):
            item = items[stem]
            if i == 0:
                outputs[stem] = base
                unique[stem] = base
            else:
                name = _disambiguated_name(base, item)
                attempt = 0
                while name in unique.values() and attempt < 10:
                    attempt += 1
                    uid = (item.uid or stem).replace("-", "")
                    name = f"{Path(base).stem}_{uid[:12]}_{attempt}{Path(base).suffix}"
                unique[stem] = name
                outputs[stem] = name

        collision_report.append(
            {
                "base_name": base,
                "count": len(stems_sorted),
                "stems": stems_sorted,
                "outputs": outputs,
            }
        )

    return unique, collision_report


def collision_stems_from_report(collision_report: list[dict]) -> set[str]:
    """All stems that participated in a duplicate base-name group."""
    stems: set[str] = set()
    for entry in collision_report:
        stems.update(entry.get("stems", []))
    return stems


def build_allowed_output_filenames(
    items: dict[str, BundledMediaItem],
    output_names: dict[str, str],
) -> set[str]:
    """Every valid merged/raw filename for the current naming plan."""
    allowed: set[str] = set()
    for stem, planned in output_names.items():
        item = items.get(stem)
        if not item or not item.main_path:
            continue
        ext = _preferred_output_ext(item.main_ext or item.main_path.suffix.lower())
        allowed.add(planned)
        allowed.add(_resolve_output_filename(planned, ext))
    return allowed


_MIN_OUTPUT_BYTES = 512


_HEADER_FAMILY = {
    ".jpg": ".jpg", ".jpeg": ".jpg",
    ".mp4": ".mp4", ".mov": ".mp4", ".m4v": ".mp4", ".heic": ".mp4",
}


def _output_file_valid(path: Path) -> bool:
    """Fast validity check: exists, plausible size, and magic bytes match extension."""
    try:
        if not path.is_file() or path.stat().st_size <= _MIN_OUTPUT_BYTES:
            return False
        with open(path, "rb") as f:
            head = f.read(16)
    except OSError:
        return False
    detected = detect_ext_from_bytes(head)
    if detected is None:
        return False
    suffix = path.suffix.lower()
    return _HEADER_FAMILY.get(detected, detected) == _HEADER_FAMILY.get(suffix, suffix)


def stem_has_output_on_disk(
    stem: str,
    item: BundledMediaItem,
    planned: str,
    merged_dir: Path,
) -> bool:
    """True when merged/ contains the expected output for this stem."""
    if not planned:
        return False
    ext = item.main_ext or (item.main_path.suffix.lower() if item.main_path else ".mp4")
    for name in {planned, _resolve_output_filename(planned, ext)}:
        if _output_file_valid(merged_dir / name):
            return True
    return False


def outputs_already_complete(
    item: BundledMediaItem,
    planned: str,
    merged_dir: Path,
    raw_dir: Path,
    *,
    keep_raw: bool,
) -> bool:
    """True when merged/ (and raw/ if requested) already contain valid outputs."""
    if not planned or not stem_has_output_on_disk("", item, planned, merged_dir):
        return False
    if not keep_raw:
        return True
    ext = _preferred_output_ext(item.main_ext or (item.main_path.suffix.lower() if item.main_path else ".mp4"))
    out_name = _resolve_output_filename(planned, ext)
    return _output_file_valid(raw_dir / out_name)


def reconcile_checkpoint_with_disk(
    done_stems: set[str],
    skipped_stems: set[str],
    items: dict[str, BundledMediaItem],
    output_names: dict[str, str],
    merged_dir: Path,
    raw_dir: Path | None = None,
    *,
    keep_raw: bool = False,
) -> tuple[set[str], set[str], list[str]]:
    """
    Drop completed stems whose output files are missing on disk.
    Checks merged/ always, and raw/ too when keep_raw is requested, so a
    checkpoint can never permanently hide a missing raw copy.
    """
    missing: list[str] = []
    for stem in sorted(done_stems):
        item = items.get(stem)
        planned = output_names.get(stem)
        if not item or not item.main_path or not planned:
            missing.append(stem)
            continue
        if not stem_has_output_on_disk(stem, item, planned, merged_dir):
            missing.append(stem)
            continue
        if keep_raw and raw_dir is not None:
            ext = _preferred_output_ext(item.main_ext or item.main_path.suffix.lower())
            raw_name = _resolve_output_filename(planned, ext)
            if not _output_file_valid(raw_dir / raw_name):
                missing.append(stem)
    if missing:
        done_stems = done_stems - set(missing)
    return done_stems, skipped_stems, missing


def prune_stale_outputs(
    merged_dir: Path,
    raw_dir: Path,
    allowed_filenames: set[str],
) -> tuple[int, int]:
    """Remove merged/raw files that are not part of the current naming plan."""
    removed = 0
    nbytes = 0
    for folder in (merged_dir, raw_dir):
        if not folder.is_dir():
            continue
        for path in list(folder.iterdir()):
            if not path.is_file() or path.name in allowed_filenames:
                continue
            try:
                nbytes += path.stat().st_size
                path.unlink()
                removed += 1
            except OSError:
                continue
    return removed, nbytes


def _resolve_output_filename(planned: str, actual_ext: str) -> str:
    """Keep planned name but swap extension after magic-byte correction."""
    if Path(planned).suffix.lower() == actual_ext.lower():
        return planned
    return f"{Path(planned).stem}{actual_ext}"


def _load_checkpoint(path: Path) -> tuple[set[str], set[str], int]:
    if not path.exists():
        return set(), set(), 0
    try:
        ck = json.loads(path.read_text(encoding="utf-8"))
        return (
            set(ck.get("completed_stems", [])),
            set(ck.get("skipped_stems", [])),
            int(ck.get("version", 1)),
        )
    except (json.JSONDecodeError, OSError, TypeError, ValueError):
        return set(), set(), 0


def _save_checkpoint(path: Path, completed: set[str], skipped: set[str]) -> None:
    from smd.fsutil import atomic_write_text

    atomic_write_text(
        path,
        json.dumps(
            {
                "version": CHECKPOINT_VERSION,
                "completed_stems": sorted(completed),
                "skipped_stems": sorted(skipped),
            },
            indent=2,
        ),
    )


def extract_media_from_zips(
    zip_paths: list[Path],
    staging_dir: Path,
    status: Callable[[str], None] | None = None,
) -> tuple[dict[str, BundledMediaItem], LocalProcessStats]:
    """Extract memories/ media from all ZIP parts with deduplication."""
    staging_dir.mkdir(parents=True, exist_ok=True)
    stats = LocalProcessStats()
    items: dict[str, BundledMediaItem] = {}
    seen_sizes: dict[str, int] = {}

    from smd.fsutil import tmp_sibling

    for zpath in zip_paths:
        stats.zips_processed += 1
        if status:
            status(f"Extracting {zpath.name}...")
        try:
            zf = zipfile.ZipFile(zpath, "r")
        except (zipfile.BadZipFile, OSError) as e:
            raise RuntimeError(
                f"ZIP part is corrupt or unreadable: {zpath.name} ({e}). "
                "Re-download this part from Snapchat and run again - "
                "processing a partial export would silently lose memories."
            ) from e
        with zf:
            for name in zf.namelist():
                if not name.startswith("memories/") or name.endswith("/"):
                    continue
                fname = Path(name).name
                if fname.lower() in ("memories.html",):
                    continue
                m = MEDIA_RE.match(fname)
                if not m:
                    continue
                stem = f"{m.group('date')}_{m.group('uid')}"
                role = m.group("role").lower()
                ext = "." + m.group("ext").lower()
                dest = staging_dir / fname
                info = zf.getinfo(name)
                prev = seen_sizes.get(fname, -1)
                if dest.exists() and info.file_size <= prev:
                    stats.duplicates_skipped += 1
                    continue
                dest.parent.mkdir(parents=True, exist_ok=True)
                tmp = tmp_sibling(dest)
                try:
                    with zf.open(name) as src, open(tmp, "wb") as out:
                        shutil.copyfileobj(src, out)
                    os.replace(tmp, dest)
                finally:
                    if tmp.exists():
                        try:
                            tmp.unlink()
                        except OSError:
                            pass
                seen_sizes[fname] = info.file_size
                stats.files_extracted += 1

                if stem not in items:
                    items[stem] = BundledMediaItem(
                        stem=stem,
                        date_prefix=m.group("date"),
                        uid=m.group("uid"),
                    )
                item = items[stem]
                if role == "main":
                    item.main_path = dest
                    item.main_ext = ext
                else:
                    item.overlay_path = dest

    return items, stats


def _load_items_from_staging(staging_dir: Path) -> dict[str, BundledMediaItem]:
    """Build item index from files already extracted under technical/staging/."""
    items: dict[str, BundledMediaItem] = {}
    if not staging_dir.is_dir():
        return items
    for path in staging_dir.iterdir():
        if not path.is_file():
            continue
        m = MEDIA_RE.match(path.name)
        if not m:
            continue
        stem = f"{m.group('date')}_{m.group('uid')}"
        role = m.group("role").lower()
        ext = "." + m.group("ext").lower()
        if stem not in items:
            items[stem] = BundledMediaItem(
                stem=stem,
                date_prefix=m.group("date"),
                uid=m.group("uid"),
            )
        item = items[stem]
        if role == "main":
            item.main_path = path
            item.main_ext = ext
        else:
            item.overlay_path = path
    return items


def _get_staging_items(
    zip_paths: list[Path],
    staging_dir: Path,
    status: Callable[[str], None] | None = None,
    legacy_staging_dir: Path | None = None,
) -> tuple[dict[str, BundledMediaItem], LocalProcessStats]:
    """Extract ZIPs or reuse existing staging (fast resume)."""
    existing = _load_items_from_staging(staging_dir)
    main_count = sum(1 for it in existing.values() if it.main_path)
    if main_count < 100 and legacy_staging_dir and legacy_staging_dir.is_dir():
        legacy = _load_items_from_staging(legacy_staging_dir)
        legacy_main = sum(1 for it in legacy.values() if it.main_path)
        if legacy_main > main_count:
            existing = legacy
            main_count = legacy_main
            staging_dir = legacy_staging_dir
    if main_count >= 100:
        if status:
            status(f"Reusing {main_count} staged files - skipping ZIP re-extract.")
        stats = LocalProcessStats(zips_processed=len(zip_paths))
        stats.files_extracted = len(existing) * 2  # approximate main+overlay rows
        return existing, stats
    return extract_media_from_zips(zip_paths, staging_dir, status)


def _fix_extension(path: Path) -> Path:
    """Rename file if magic bytes disagree with extension."""
    try:
        head = path.read_bytes()[:16]
    except OSError:
        return path
    real_ext = detect_ext_from_bytes(head)
    if not real_ext or real_ext == path.suffix.lower():
        return path
    new_path = path.with_suffix(real_ext)
    if new_path.exists():
        return path
    path.rename(new_path)
    return new_path


@dataclass
class _ItemOutcome:
    stem: str
    display_name: str
    skipped: bool = False
    done: bool = False
    merged: int = 0
    raw_copied: int = 0
    metadata_applied: int = 0
    overlays_missing: int = 0
    repaired_videos: int = 0
    quarantined: int = 0
    failed: int = 0
    json_matched: int = 0
    json_unmatched: int = 0
    collision_avoided: int = 0
    integrity_repairs: int = 0
    repair_note: str | None = None


def _process_single_item(
    stem: str,
    item: BundledMediaItem,
    memory: Memory | None,
    *,
    merged_dir: Path,
    raw_dir: Path,
    quarantine_dir: Path,
    staging_dir: Path,
    merge_overlays: bool,
    keep_raw: bool,
    repair_videos: bool,
    apply_meta: bool,
    ffmpeg_sem: threading.Semaphore | None,
    ffmpeg_threads: int = 1,
    planned_output_name: str,
) -> _ItemOutcome:
    """Process one bundled media item (thread-safe - no shared mutable state)."""
    name = item.main_path.name if item.main_path else stem
    out = _ItemOutcome(stem=stem, display_name=name)

    if not item.main_path or not item.main_path.exists():
        out.skipped = True
        out.failed = 1
        return out

    main_path = _fix_extension(item.main_path)
    item.main_ext = _preferred_output_ext(main_path.suffix.lower())

    if main_path.stat().st_size < 512:
        shutil.move(str(main_path), str(quarantine_dir / main_path.name))
        out.skipped = True
        out.quarantined = 1
        return out

    if memory:
        out.json_matched = 1
    else:
        out.json_unmatched = 1

    out_name = _resolve_output_filename(planned_output_name, item.main_ext)
    raw_out = raw_dir / out_name
    merged_out = merged_dir / out_name

    work_main = main_path
    if repair_videos and item.main_ext in (".mp4", ".mov", ".m4v"):
        if is_likely_corrupt_video(main_path):
            repaired = staging_dir / f"repaired_{main_path.name}"
            if ffmpeg_sem:
                with ffmpeg_sem:
                    ok, method = repair_video(main_path, repaired, threads=ffmpeg_threads)
            else:
                ok, method = repair_video(main_path, repaired, threads=ffmpeg_threads)
            if ok:
                work_main = repaired
                out.repaired_videos = 1
                out.repair_note = f"  Repaired video ({method}): {main_path.name}"
            else:
                shutil.copy2(main_path, quarantine_dir / main_path.name)
                out.skipped = True
                out.quarantined = 1
                out.failed = 1
                out.report_entry = {"stem": stem, "status": "quarantine", "error": method}
                return out

    is_video = item.main_ext in (".mp4", ".mov", ".m4v")
    want_meta = bool(apply_meta and memory)
    has_overlay = bool(merge_overlays and item.overlay_path and item.overlay_path.exists())

    # Fast path: with keep_raw on and no overlay to burn into merged/, raw/
    # and merged/ end up byte-identical - process once (into raw_out) and
    # hardlink merged_out instead of a second full copy/ffmpeg remux. This
    # never runs for overlay items (they need genuinely different bytes in
    # each folder) or when keep_raw is off (nothing to link from), so the
    # overlay-merge branch below is completely unaffected by this path. See
    # agent-docs/DECISIONS.md ("2026-07 - raw/merged hardlinked when
    # identical") for why later "repairs" here must stay atomic (os.replace-
    # based), never an in-place truncate+write, to avoid silently corrupting
    # the other hardlinked name.
    if keep_raw and not has_overlay:
        if item.overlay_path is None and merge_overlays:
            out.overlays_missing = 1

        raw_write_error: str | None = None
        try:
            raw_container_done = False
            if is_video and want_meta:
                if ffmpeg_sem:
                    with ffmpeg_sem:
                        raw_container_done = copy_video_with_metadata(work_main, raw_out, memory)
                else:
                    raw_container_done = copy_video_with_metadata(work_main, raw_out, memory)
            if not raw_container_done:
                _write_main_to_output(work_main, raw_out)
            if want_meta:
                apply_metadata(
                    raw_out, memory, raw_out.suffix, container_date_done=raw_container_done
                )
                ts = memory.date.timestamp()
                os.utime(raw_out, (ts, ts))
        except OSError as e:
            raw_write_error = str(e)

        ok_raw, raw_reason = (
            validate_media_file(raw_out) if raw_out.exists() else (False, raw_write_error or "missing")
        )
        if not ok_raw:
            try:
                _write_main_to_output(work_main, raw_out)
                if want_meta:
                    apply_metadata(raw_out, memory, raw_out.suffix)
                    ts = memory.date.timestamp()
                    os.utime(raw_out, (ts, ts))
                ok_raw, raw_reason = validate_media_file(raw_out)
            except OSError as e:
                ok_raw, raw_reason = False, str(e)
        if not ok_raw:
            out.failed = 1
            out.report_entry = {
                "stem": stem,
                "status": "raw_output_failed",
                "error": raw_reason,
                "output": raw_out.name,
            }
            return out
        out.raw_copied = 1

        from smd.fsutil import atomic_copy, link_or_copy

        link_or_copy(raw_out, merged_out)
        ok_merged, reason = validate_media_file(merged_out)
        if not ok_merged:
            # Atomic (os.replace-based) on purpose, never an in-place write -
            # raw_out may still be a hardlinked twin of merged_out at this
            # point, and an in-place rewrite would silently mutate raw_out's
            # bytes too instead of just fixing merged_out.
            try:
                atomic_copy(raw_out, merged_out)
                ok_merged, reason = validate_media_file(merged_out)
            except OSError as e:
                ok_merged, reason = False, str(e)
        if not ok_merged:
            out.failed = 1
            out.report_entry = {
                "stem": stem,
                "status": "invalid_output",
                "error": reason,
                "output": merged_out.name,
            }
            return out

        if want_meta:
            out.metadata_applied = 1

        out.done = True
        out.report_entry = {
            "stem": stem,
            "status": "ok",
            "merged": bool(item.overlay_path),
            "output": merged_out.name,
            "json_date": memory.date.isoformat() if memory else None,
        }
        return out

    raw_write_error: str | None = None
    if keep_raw:
        try:
            raw_container_done = False
            if is_video and want_meta:
                if ffmpeg_sem:
                    with ffmpeg_sem:
                        raw_container_done = copy_video_with_metadata(work_main, raw_out, memory)
                else:
                    raw_container_done = copy_video_with_metadata(work_main, raw_out, memory)
            if not raw_container_done:
                _write_main_to_output(work_main, raw_out)
            if want_meta:
                apply_metadata(
                    raw_out, memory, raw_out.suffix, container_date_done=raw_container_done
                )
                ts = memory.date.timestamp()
                os.utime(raw_out, (ts, ts))
            out.raw_copied = 1
        except OSError as e:
            raw_write_error = str(e)

    # When a video needs its date/GPS embedded, fold the -metadata flags into
    # whichever ffmpeg pass already touches the file (overlay burn, or a
    # metadata-aware copy for non-overlay videos) instead of paying for a
    # second, separate remux of the whole file afterward.
    merged_container_done = False
    if merge_overlays and item.overlay_path and item.overlay_path.exists():
        ok = False
        if item.main_ext in (".jpg", ".jpeg", ".png", ".webp"):
            ok = merge_image_overlay(work_main, item.overlay_path, merged_out)
        elif is_video:
            meta_flags = video_metadata_ffmpeg_flags(memory) if want_meta else None
            if ffmpeg_sem:
                with ffmpeg_sem:
                    ok = merge_video_overlay(
                        work_main, item.overlay_path, merged_out,
                        threads=ffmpeg_threads, metadata_flags=meta_flags,
                    )
            else:
                ok = merge_video_overlay(
                    work_main, item.overlay_path, merged_out,
                    threads=ffmpeg_threads, metadata_flags=meta_flags,
                )
            merged_container_done = ok and meta_flags is not None
        if ok:
            out.merged = 1
        else:
            shutil.copy2(work_main, merged_out)
            out.overlays_missing = 1
    else:
        if item.overlay_path is None and merge_overlays:
            out.overlays_missing = 1
        if is_video and want_meta:
            if ffmpeg_sem:
                with ffmpeg_sem:
                    merged_container_done = copy_video_with_metadata(work_main, merged_out, memory)
            else:
                merged_container_done = copy_video_with_metadata(work_main, merged_out, memory)
        if not merged_container_done:
            _write_main_to_output(work_main, merged_out)

    if want_meta:
        try:
            apply_metadata(
                merged_out, memory, merged_out.suffix, container_date_done=merged_container_done
            )
            ts = memory.date.timestamp()
            os.utime(merged_out, (ts, ts))
            out.metadata_applied = 1
        except OSError:
            pass

    ok_merged, reason = validate_media_file(merged_out)
    if not ok_merged and merged_out.exists():
        try:
            shutil.copy2(work_main, merged_out)
            if apply_meta and memory:
                apply_metadata(merged_out, memory, merged_out.suffix)
            out.integrity_repairs = 1
        except OSError:
            pass
        ok_merged, reason = validate_media_file(merged_out)
        if not ok_merged:
            out.skipped = True
            out.failed = 1
            out.report_entry = {
                "stem": stem,
                "status": "invalid_output",
                "error": reason,
                "output": merged_out.name,
            }
            return out

    if keep_raw:
        # A stem is only "done" when every requested output is valid; otherwise
        # the checkpoint would permanently hide a missing/corrupt raw copy.
        ok_raw, raw_reason = (
            validate_media_file(raw_out) if raw_out.exists() else (False, raw_write_error or "missing")
        )
        if not ok_raw:
            try:
                _write_main_to_output(work_main, raw_out)
                ok_raw, raw_reason = validate_media_file(raw_out)
            except OSError as e:
                ok_raw, raw_reason = False, str(e)
        if not ok_raw:
            out.failed = 1
            out.report_entry = {
                "stem": stem,
                "status": "raw_output_failed",
                "error": raw_reason,
                "output": raw_out.name,
            }
            return out

    out.done = True
    out.report_entry = {
        "stem": stem,
        "status": "ok",
        "merged": bool(item.overlay_path),
        "output": merged_out.name,
        "json_date": memory.date.isoformat() if memory else None,
    }
    return out


def _apply_item_outcome(
    out: _ItemOutcome,
    stats: LocalProcessStats,
    done_stems: set[str],
    skipped_stems: set[str],
    report_entries: list[dict],
) -> None:
    stats.merged += out.merged
    stats.raw_copied += out.raw_copied
    stats.metadata_applied += out.metadata_applied
    stats.overlays_missing += out.overlays_missing
    stats.repaired_videos += out.repaired_videos
    stats.quarantined += out.quarantined
    stats.failed += out.failed
    stats.json_matched += out.json_matched
    stats.json_unmatched += out.json_unmatched
    stats.collision_avoided += out.collision_avoided
    stats.integrity_repairs += out.integrity_repairs
    if out.skipped:
        skipped_stems.add(out.stem)
    elif out.done:
        done_stems.add(out.stem)
    if out.report_entry:
        report_entries.append(out.report_entry)


def process_bundled_export(
    seed_path: Path,
    account_dir: Path,
    *,
    merge_overlays: bool = True,
    keep_raw: bool = True,
    repair_videos: bool = True,
    apply_meta: bool = True,
    json_path: Path | None = None,
    limit: int = 0,
    status_callback: Callable[[str], None] | None = None,
    should_stop: Callable[[], bool] | None = None,
    checkpoint_path: Path | None = None,
    max_workers: int = 1,
    max_ffmpeg: int = 2,
    ffmpeg_threads: int = 1,
    zip_paths: list[Path] | None = None,
    layout: AccountPaths | None = None,
) -> LocalProcessStats:
    """
    Full bundled export pipeline.
    Layout:
      account/downloads/merged/  - overlay merged + metadata (your library)
      account/downloads/raw/     - main files (+ metadata), optional
      account/technical/         - staging, json, reports, checkpoint, quarantine, logs
    """
    def status(msg: str):
        if status_callback:
            status_callback(msg)

    account_dir = normalize_account_dir(account_dir)
    paths = layout or resolve_account_paths(account_dir, migrate=True)
    merged_dir = paths.merged_dir
    raw_dir = paths.raw_dir
    quarantine_dir = paths.quarantine_dir
    reports_dir = paths.reports_dir
    staging_dir = paths.staging_dir
    if checkpoint_path is None:
        checkpoint_path = paths.checkpoint_path

    zip_paths = zip_paths or discover_export_zip_parts(seed_path)
    if not zip_paths:
        raise FileNotFoundError("No export ZIP files found.")

    paths.ensure_dirs()
    for d in (merged_dir, raw_dir, quarantine_dir, reports_dir):
        d.mkdir(parents=True, exist_ok=True)

    if json_path is None:
        json_path = paths.json_path
    if not json_path.exists():
        extract_json_from_zips(zip_paths, json_path)

    memories = load_memories(json_path)
    status(f"Loaded {len(memories)} JSON rows.")

    done_stems: set[str] = set()
    skipped_stems: set[str] = set()
    ck_version = 0
    if checkpoint_path:
        done_stems, skipped_stems, ck_version = _load_checkpoint(checkpoint_path)
        if done_stems or skipped_stems:
            status(f"Resuming: {len(done_stems)} done, {len(skipped_stems)} skipped.")
        if ck_version < CHECKPOINT_VERSION and done_stems:
            status("Applying the latest quality and naming settings to your library.")

    items, stats = _get_staging_items(
        zip_paths,
        staging_dir,
        status,
        legacy_staging_dir=paths.downloads_dir / LEGACY_STAGING,
    )
    match_map = build_match_map(
        items, memories, probe_workers=min(16, max(1, int(max_workers or 8)))
    )
    matched_count = sum(1 for v in match_map.values() if v is not None)
    status(f"Matched {matched_count}/{len(match_map)} files to JSON metadata.")

    output_names, collision_report = build_unique_output_names(items, match_map)
    if collision_report:
        stats.collision_groups = len(collision_report)
        stats.files_disambiguated = sum(max(0, e["count"] - 1) for e in collision_report)
        status(
            f"Unique naming: {len(collision_report)} duplicate time groups -> "
            f"{stats.files_disambiguated} extra filenames (no overwrites)."
        )
        (reports_dir / "filename_collisions.json").write_text(
            json.dumps(
                {
                    "groups": len(collision_report),
                    "files_disambiguated": stats.files_disambiguated,
                    "entries": collision_report,
                },
                indent=2,
            ),
            encoding="utf-8",
        )

    allowed_outputs = build_allowed_output_filenames(items, output_names)
    if done_stems:
        done_stems, skipped_stems, missing_outputs = reconcile_checkpoint_with_disk(
            done_stems, skipped_stems, items, output_names, merged_dir,
            raw_dir, keep_raw=keep_raw,
        )
        if missing_outputs:
            status(
                f"Repairing {len(missing_outputs)} items that were marked finished "
                f"but had no output file on disk."
            )
            if checkpoint_path:
                _save_checkpoint(checkpoint_path, done_stems, skipped_stems)

    pruned, pruned_bytes = prune_stale_outputs(merged_dir, raw_dir, allowed_outputs)
    if pruned:
        status(
            f"Removed {pruned} outdated output files ({pruned_bytes / (1024 * 1024):.1f} MB)."
        )

    if checkpoint_path and ck_version < CHECKPOINT_VERSION:
        collide = collision_stems_from_report(collision_report)
        if collide and (done_stems or skipped_stems):
            redo = (done_stems | skipped_stems) & collide
            done_stems -= redo
            skipped_stems -= redo
            if redo:
                status(
                    f"Updating {len(redo)} files that shared the same filename."
                )
        elif done_stems:
            status(
                "Refreshing any files that need unique filenames after a naming collision."
            )

    report_entries: list[dict] = []

    total = len(items)
    max_workers = max(1, int(max_workers))
    max_ffmpeg = max(1, int(max_ffmpeg))
    ffmpeg_threads = max(1, int(ffmpeg_threads))
    if max_workers > 1:
        status(
            f"Parallel: {max_workers} workers, max {max_ffmpeg} ffmpeg "
            f"({ffmpeg_threads} threads each)."
        )
    try:
        from smd.gpu_encode import preferred_video_encoder_label

        enc_label = preferred_video_encoder_label()
        if "GPU" in enc_label or enc_label.startswith("AMD") or enc_label.startswith("NVIDIA"):
            status(f"Video encoding: {enc_label}.")
        else:
            status(f"Video encoding: {enc_label} (no compatible graphics card encoder found).")
    except Exception:
        pass

    work_queue: list[tuple[str, BundledMediaItem]] = []
    skipped_existing = 0
    for stem, item in sorted(items.items()):
        if stem in done_stems or stem in skipped_stems:
            continue
        planned = output_names.get(stem)
        if planned and outputs_already_complete(
            item, planned, merged_dir, raw_dir, keep_raw=keep_raw
        ):
            done_stems.add(stem)
            skipped_existing += 1
            continue
        work_queue.append((stem, item))
    if skipped_existing:
        status(f"Skipping {skipped_existing} items - outputs already on disk.")
        if checkpoint_path:
            _save_checkpoint(checkpoint_path, done_stems, skipped_stems)

    processed_count = 0
    since_checkpoint = 0
    state_lock = threading.Lock()
    ffmpeg_sem = threading.Semaphore(max_ffmpeg) if max_ffmpeg > 0 else None
    status_every = 25
    last_reported = 0

    def report_progress(force: bool = False) -> None:
        nonlocal last_reported
        with state_lock:
            files_done = len(done_stems) + len(skipped_stems)
        if force or files_done <= 3 or files_done - last_reported >= status_every:
            last_reported = files_done
            status(f"Processing {files_done}/{total}")

    def run_one(stem: str, item: BundledMediaItem) -> _ItemOutcome:
        memory = match_map.get(stem)
        planned = output_names.get(stem)
        if not planned:
            ext = item.main_ext or (item.main_path.suffix.lower() if item.main_path else ".mp4")
            planned = _base_output_name(memory, item, ext)
        try:
            return _process_single_item(
                stem,
                item,
                memory,
                merged_dir=merged_dir,
                raw_dir=raw_dir,
                quarantine_dir=quarantine_dir,
                staging_dir=staging_dir,
                merge_overlays=merge_overlays,
                keep_raw=keep_raw,
                repair_videos=repair_videos,
                apply_meta=apply_meta,
                ffmpeg_sem=ffmpeg_sem,
                ffmpeg_threads=ffmpeg_threads,
                planned_output_name=planned,
            )
        except Exception as exc:
            fail = _ItemOutcome(stem=stem, display_name=item.main_path.name if item.main_path else stem)
            fail.skipped = True
            fail.failed = 1
            fail.report_entry = {"stem": stem, "status": "error", "error": str(exc)}
            return fail

    def handle_outcome(out: _ItemOutcome) -> bool:
        """Apply result; return False if limit reached."""
        nonlocal processed_count, since_checkpoint
        with state_lock:
            if out.repair_note:
                status(out.repair_note)
            _apply_item_outcome(out, stats, done_stems, skipped_stems, report_entries)
            if out.done or out.skipped:
                processed_count += 1
                since_checkpoint += 1
            if checkpoint_path and since_checkpoint >= 25:
                _save_checkpoint(checkpoint_path, done_stems, skipped_stems)
                since_checkpoint = 0
            limit_hit = limit > 0 and processed_count >= limit
        report_progress()
        return not limit_hit

    if max_workers == 1:
        for stem, item in work_queue:
            if should_stop and should_stop():
                status("Stopped by user.")
                break
            if limit > 0 and processed_count >= limit:
                status(f"Limit reached ({limit} files).")
                break
            status(f"Processing {len(done_stems) + len(skipped_stems) + 1}/{total}: {item.main_path.name if item.main_path else stem}")
            if not handle_outcome(run_one(stem, item)):
                status(f"Limit reached ({limit} files).")
                break
    else:
        pending = list(work_queue)
        futures: dict = {}
        stop = False
        with ThreadPoolExecutor(max_workers=max_workers) as executor:
            while pending or futures:
                if should_stop and should_stop():
                    status("Stopped by user.")
                    stop = True
                while (
                    not stop
                    and len(futures) < max_workers
                    and pending
                    and (limit <= 0 or processed_count + len(futures) < limit)
                ):
                    stem, item = pending.pop(0)
                    fut = executor.submit(run_one, stem, item)
                    futures[fut] = stem
                if not futures:
                    break
                done_set, _ = wait(futures, return_when=FIRST_COMPLETED)
                for fut in done_set:
                    futures.pop(fut)
                    if not handle_outcome(fut.result()):
                        stop = True
                        pending.clear()
                if limit > 0 and processed_count >= limit:
                    status(f"Limit reached ({limit} files).")
                    stop = True
                    pending.clear()
            if futures and stop:
                for fut in futures:
                    try:
                        handle_outcome(fut.result())
                    except Exception:
                        pass

    report_progress(force=True)
    if checkpoint_path:
        _save_checkpoint(checkpoint_path, done_stems, skipped_stems)

    try:
        from smd.duplicates import scan_content_duplicates

        dup_report = scan_content_duplicates(
            paths,
            move_to_folder=False,
            status_callback=status,
            hash_workers=max(2, min(16, max_workers)),
        )
        if dup_report.duplicate_groups:
            status(
                f"Duplicate check done: {dup_report.duplicate_groups} identical-file group(s) found "
                f"({dup_report.merged_scanned:,} files checked). "
                "Use Review duplicates on the Save memories tab to pick which copy to keep."
            )
        else:
            status(
                f"Duplicate check done: no identical files found "
                f"({dup_report.merged_scanned:,} checked)."
            )
    except Exception:
        pass

    report = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "checkpoint_version": CHECKPOINT_VERSION,
        "stats": asdict(stats),
        "collision_groups": stats.collision_groups,
        "files_disambiguated": stats.files_disambiguated,
        "entries_sample": report_entries[:50],
        "total_entries": len(report_entries),
    }
    (reports_dir / "processing_report.json").write_text(
        json.dumps(report, indent=2), encoding="utf-8"
    )
    status("Processing complete.")
    return stats
