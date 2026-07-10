"""Verify bundled export completeness before deleting technical/staging/."""
from __future__ import annotations

import json
import shutil
from collections import Counter
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path

from smd.account_layout import AccountPaths, folder_size_bytes, format_bytes, resolve_account_paths
from smd.local_pipeline import (
    BundledMediaItem,
    _load_checkpoint,
    _load_items_from_staging,
    _resolve_output_filename,
    build_allowed_output_filenames,
    build_deterministic_match_map,
    build_unique_output_names,
)
from smd.media_integrity import validate_image_file, validate_video_file
from smd.utils import load_memories

MIN_OUTPUT_BYTES = 512

def _output_file_status(folder: Path, filename: str) -> str:
    path = folder / filename
    if not path.is_file():
        return "missing"
    try:
        if path.stat().st_size <= MIN_OUTPUT_BYTES:
            return "too_small"
    except OSError:
        return "missing"
    return "ok"


def _stem_output_status(
    item: BundledMediaItem,
    planned: str,
    folder: Path,
) -> str:
    ext = item.main_ext or (item.main_path.suffix.lower() if item.main_path else ".mp4")
    names = {planned, _resolve_output_filename(planned, ext)}
    best = "missing"
    for name in names:
        status = _output_file_status(folder, name)
        if status == "ok":
            return "ok"
        if status == "too_small":
            best = "too_small"
    return best


@dataclass
class StagingCheckIssue:
    code: str
    severity: str  # error | warning
    message: str
    stems: list[str] = field(default_factory=list)


@dataclass
class StagingReadinessReport:
    checked_at: str
    safe_to_delete: bool
    staging_main_count: int = 0
    staging_bytes: int = 0
    merged_count: int = 0
    raw_count: int = 0
    checkpoint_done: int = 0
    checkpoint_skipped: int = 0
    outputs_verified: int = 0
    missing_merged: list[str] = field(default_factory=list)
    missing_raw: list[str] = field(default_factory=list)
    undersized_merged: list[str] = field(default_factory=list)
    undersized_raw: list[str] = field(default_factory=list)
    pending_checkpoint: list[str] = field(default_factory=list)
    orphan_merged: int = 0
    orphan_raw: int = 0
    duplicate_merged_names: int = 0
    quarantine_count: int = 0
    issues: list[StagingCheckIssue] = field(default_factory=list)

    def summary_lines(self) -> list[str]:
        lines = [
            f"Staging: {self.staging_main_count} memories ({format_bytes(self.staging_bytes)})",
            f"Outputs: merged {self.merged_count}, raw {self.raw_count}",
            f"Verified on disk: {self.outputs_verified}/{self.staging_main_count}",
        ]
        if self.checkpoint_done or self.checkpoint_skipped:
            lines.append(
                f"Checkpoint: {self.checkpoint_done} done, {self.checkpoint_skipped} skipped"
            )
        if self.pending_checkpoint:
            lines.append(f"Not finished yet: {len(self.pending_checkpoint)}")
        if self.missing_merged:
            lines.append(f"Missing in merged/: {len(self.missing_merged)}")
        if self.missing_raw:
            lines.append(f"Missing in raw/: {len(self.missing_raw)}")
        if self.undersized_merged:
            lines.append(f"Too small in merged/ (corrupt): {len(self.undersized_merged)}")
        if self.undersized_raw:
            lines.append(f"Too small in raw/ (corrupt): {len(self.undersized_raw)}")
        if self.orphan_merged or self.orphan_raw:
            lines.append(
                f"Unexpected extra files: merged {self.orphan_merged}, raw {self.orphan_raw}"
            )
        if self.quarantine_count:
            lines.append(f"Quarantined (review first): {self.quarantine_count}")
        lines.append(
            "SAFE to delete staging"
            if self.safe_to_delete
            else "NOT SAFE to delete staging - fix issues first"
        )
        return lines

    def to_dict(self) -> dict:
        data = asdict(self)
        data["issues"] = [asdict(i) for i in self.issues]
        return data


def _count_media_files(folder: Path) -> int:
    if not folder.is_dir():
        return 0
    return sum(1 for p in folder.iterdir() if p.is_file())


def _count_quarantine(folder: Path) -> int:
    if not folder.is_dir():
        return 0
    return sum(
        1
        for p in folder.iterdir()
        if p.is_file() and p.stat().st_size > 0
    )


def check_staging_readiness(
    account_dir: Path,
    *,
    require_raw: bool = True,
    layout: AccountPaths | None = None,
    deep_video_check: bool = True,
    video_check_limit: int | None = None,
) -> StagingReadinessReport:
    """
    Verify every staged memory has finished outputs before deleting staging/.

    deep_video_check runs an ffprobe stream-decode check on merged videos;
    disable only in tests with synthetic media files. video_check_limit caps
    how many videos are deep-checked (random sample) - None (default) checks
    every video, since this is the gate before staging (the only re-source
    for re-processing) is deleted.
    """
    paths = layout or resolve_account_paths(account_dir, migrate=False, create=False)
    issues: list[StagingCheckIssue] = []
    report = StagingReadinessReport(
        checked_at=datetime.now(timezone.utc).isoformat(),
        safe_to_delete=False,
    )

    if not paths.staging_dir.is_dir() or not any(paths.staging_dir.iterdir()):
        issues.append(
            StagingCheckIssue(
                code="no_staging",
                severity="warning",
                message="Staging folder is empty or missing - nothing to delete.",
            )
        )
        report.issues = issues
        report.safe_to_delete = True
        return report

    report.staging_bytes = folder_size_bytes(paths.staging_dir)

    if not paths.json_path.is_file():
        issues.append(
            StagingCheckIssue(
                code="missing_json",
                severity="warning",
                message=f"JSON metadata not found: {paths.json_path}",
            )
        )

    items = _load_items_from_staging(paths.staging_dir)
    main_stems = sorted(stem for stem, it in items.items() if it.main_path)
    report.staging_main_count = len(main_stems)

    if report.staging_main_count == 0:
        issues.append(
            StagingCheckIssue(
                code="no_staged_media",
                severity="error",
                message="Staging has files but no recognizable main media.",
            )
        )
        report.issues = issues
        return report

    output_names: dict[str, str] = {}
    if paths.json_path.is_file():
        try:
            memories = load_memories(paths.json_path)
            match_map = build_deterministic_match_map(items, memories)
            output_names, _ = build_unique_output_names(items, match_map)
        except Exception as exc:
            issues.append(
                StagingCheckIssue(
                    code="json_load_failed",
                    severity="error",
                    message=f"Could not read JSON metadata: {exc}",
                )
            )

    done_stems: set[str] = set()
    skipped_stems: set[str] = set()
    if paths.checkpoint_path.is_file():
        done_stems, skipped_stems, _ = _load_checkpoint(paths.checkpoint_path)
        report.checkpoint_done = len(done_stems)
        report.checkpoint_skipped = len(skipped_stems)
    else:
        issues.append(
            StagingCheckIssue(
                code="no_checkpoint",
                severity="warning",
                message="No checkpoint file - relying on output files on disk only.",
            )
        )

    finished = done_stems | skipped_stems
    report.pending_checkpoint = [s for s in main_stems if s not in finished]
    if report.pending_checkpoint:
        issues.append(
            StagingCheckIssue(
                code="pending_processing",
                severity="error",
                message=(
                    f"{len(report.pending_checkpoint)} memories are not marked finished "
                    f"in the checkpoint."
                ),
                stems=report.pending_checkpoint[:20],
            )
        )

    missing_merged: list[str] = []
    missing_raw: list[str] = []
    undersized_merged: list[str] = []
    undersized_raw: list[str] = []
    for stem in main_stems:
        item = items[stem]
        planned = output_names.get(stem)
        if not planned:
            ext = item.main_ext or (item.main_path.suffix.lower() if item.main_path else ".mp4")
            planned = f"{item.date_prefix}_{item.uid[:8]}{ext}"

        merged_status = _stem_output_status(item, planned, paths.merged_dir)
        if merged_status == "ok":
            report.outputs_verified += 1
        elif merged_status == "too_small":
            undersized_merged.append(stem)
        else:
            missing_merged.append(stem)

        if require_raw:
            raw_status = _stem_output_status(item, planned, paths.raw_dir)
            if raw_status == "too_small":
                undersized_raw.append(stem)
            elif raw_status != "ok":
                missing_raw.append(stem)

    report.missing_merged = missing_merged
    report.missing_raw = missing_raw
    report.undersized_merged = undersized_merged
    report.undersized_raw = undersized_raw
    if missing_merged:
        issues.append(
            StagingCheckIssue(
                code="missing_merged",
                severity="error",
                message=f"{len(missing_merged)} memories have no file in downloads/merged/.",
                stems=missing_merged[:20],
            )
        )
    if missing_raw:
        issues.append(
            StagingCheckIssue(
                code="missing_raw",
                severity="error",
                message=f"{len(missing_raw)} memories have no file in downloads/raw/.",
                stems=missing_raw[:20],
            )
        )
    if undersized_merged:
        issues.append(
            StagingCheckIssue(
                code="undersized_merged",
                severity="error",
                message=(
                    f"{len(undersized_merged)} merged files are too small "
                    f"(≤{MIN_OUTPUT_BYTES} bytes) - likely corrupt."
                ),
                stems=undersized_merged[:20],
            )
        )
    if undersized_raw:
        issues.append(
            StagingCheckIssue(
                code="undersized_raw",
                severity="error",
                message=(
                    f"{len(undersized_raw)} raw files are too small "
                    f"(≤{MIN_OUTPUT_BYTES} bytes) - re-run processing for these."
                ),
                stems=undersized_raw[:20],
            )
        )

    report.merged_count = _count_media_files(paths.merged_dir)
    report.raw_count = _count_media_files(paths.raw_dir)

    if output_names:
        allowed = build_allowed_output_filenames(items, output_names)
        merged_names = {p.name for p in paths.merged_dir.iterdir() if p.is_file()} if paths.merged_dir.is_dir() else set()
        raw_names = {p.name for p in paths.raw_dir.iterdir() if p.is_file()} if paths.raw_dir.is_dir() else set()
        report.orphan_merged = len(merged_names - allowed)
        report.orphan_raw = len(raw_names - allowed)
        if report.orphan_merged or report.orphan_raw:
            issues.append(
                StagingCheckIssue(
                    code="orphan_outputs",
                    severity="warning",
                    message=(
                        "Some output files do not match the current naming plan "
                        f"(merged {report.orphan_merged}, raw {report.orphan_raw}). "
                        "Re-run processing or prune stale files before deleting staging."
                    ),
                )
            )

        dup_merged = sum(1 for c in Counter(merged_names).values() if c > 1)
        report.duplicate_merged_names = dup_merged
        if dup_merged:
            issues.append(
                StagingCheckIssue(
                    code="duplicate_names",
                    severity="error",
                    message=f"{dup_merged} duplicate filenames in merged/.",
                )
            )

        if report.merged_count != len(set(output_names.values())):
            issues.append(
                StagingCheckIssue(
                    code="merged_count_mismatch",
                    severity="warning",
                    message=(
                        f"Expected {len(set(output_names.values()))} unique merged files, "
                        f"found {report.merged_count}."
                    ),
                )
            )

    report.quarantine_count = _count_quarantine(paths.quarantine_dir)
    if report.quarantine_count:
        # Quarantined files are memories that never reached the library.
        # Staging is their only remaining source - block deletion until reviewed.
        issues.append(
            StagingCheckIssue(
                code="quarantine_nonempty",
                severity="error",
                message=(
                    f"{report.quarantine_count} file(s) in technical/quarantine/ never reached "
                    "your library. Review them before deleting staging - staging is their only copy."
                ),
            )
        )

    corrupt_merged: list[str] = []
    video_paths: list[Path] = []
    if paths.merged_dir.is_dir():
        for path in paths.merged_dir.iterdir():
            suffix = path.suffix.lower()
            if suffix in (".jpg", ".jpeg", ".png", ".webp"):
                ok, reason = validate_image_file(path)
            elif suffix in (".mp4", ".mov", ".m4v", ".mkv", ".avi"):
                ok, reason = validate_video_file(path)
                if ok:
                    video_paths.append(path)
            else:
                continue
            if not ok:
                corrupt_merged.append(path.name)
                if len(corrupt_merged) <= 20:
                    issues.append(
                        StagingCheckIssue(
                            code="corrupt_merged",
                            severity="error",
                            message=f"Corrupt output in merged/: {path.name} ({reason})",
                        )
                    )
    if len(corrupt_merged) > 20:
        issues.append(
            StagingCheckIssue(
                code="corrupt_merged",
                severity="error",
                message=f"{len(corrupt_merged)} corrupt files in merged/ - repair before deleting staging.",
                stems=corrupt_merged[:20],
            )
        )

    # Deep-check videos with ffprobe: header/size checks cannot detect
    # truncated or corrupt streams, and staging is the only source to
    # reprocess from once it is deleted. By default every video is checked
    # (not just a sample), run in parallel since ffprobe is I/O-bound.
    if video_paths and deep_video_check:
        import os as _os
        import random
        from concurrent.futures import ThreadPoolExecutor, as_completed

        from smd.procutil import ffprobe_stream_ok

        if video_check_limit is not None and len(video_paths) > video_check_limit:
            sample = random.sample(video_paths, video_check_limit)
        else:
            sample = video_paths

        bad_videos = []
        max_workers = min(8, max(2, _os.cpu_count() or 4))
        with ThreadPoolExecutor(max_workers=max_workers) as pool:
            futures = {pool.submit(ffprobe_stream_ok, vp): vp for vp in sample}
            for fut in as_completed(futures):
                vp = futures[fut]
                try:
                    verdict = fut.result()
                except Exception:
                    verdict = None
                if verdict is False:
                    bad_videos.append(vp.name)

        if bad_videos:
            scope = "all" if sample is video_paths else f"{len(sample)} sampled"
            issues.append(
                StagingCheckIssue(
                    code="corrupt_video_stream",
                    severity="error",
                    message=(
                        f"{len(bad_videos)} of {scope} videos failed a deep "
                        f"ffprobe check (e.g. {bad_videos[0]}). Re-run processing before "
                        "deleting staging."
                    ),
                    stems=sorted(bad_videos)[:20],
                )
            )

    has_errors = any(i.severity == "error" for i in issues)
    report.issues = issues
    report.safe_to_delete = (
        not has_errors
        and report.staging_main_count > 0
        and report.outputs_verified == report.staging_main_count
        and not report.pending_checkpoint
        and not report.missing_merged
        and not report.undersized_merged
        and not report.undersized_raw
        and (not require_raw or not report.missing_raw)
    )
    return report


def save_staging_readiness_report(paths: AccountPaths, report: StagingReadinessReport) -> Path:
    paths.reports_dir.mkdir(parents=True, exist_ok=True)
    out = paths.reports_dir / "staging_readiness.json"
    out.write_text(json.dumps(report.to_dict(), indent=2), encoding="utf-8")
    return out


def delete_staging_folder(
    account_dir: Path,
    *,
    report: StagingReadinessReport | None = None,
    layout: AccountPaths | None = None,
    force: bool = False,
) -> tuple[bool, str]:
    """
    Remove technical/staging/ after a successful readiness check.
    Returns (ok, message).
    """
    paths = layout or resolve_account_paths(account_dir, migrate=False, create=False)
    check = report or check_staging_readiness(account_dir, layout=paths)
    if not check.safe_to_delete and not force:
        return False, "Staging check failed - not deleting. See staging_readiness.json."

    if not paths.staging_dir.exists():
        return True, "Staging folder already empty."

    freed = folder_size_bytes(paths.staging_dir)
    shutil.rmtree(paths.staging_dir, ignore_errors=True)
    paths.staging_dir.mkdir(parents=True, exist_ok=True)
    return True, f"Deleted staging ({format_bytes(freed)} freed)."
