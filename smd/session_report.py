"""Post-run session summary for the user dashboard."""
from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path

from smd.account_layout import AccountPaths, format_bytes, folder_size_bytes, resolve_account_paths
from smd.duplicates import load_cached_duplicate_group_count
from smd.local_pipeline import LocalProcessStats, _load_items_from_staging
from smd.media_integrity import validate_image_file
from smd.staging_check import check_staging_readiness


@dataclass
class SessionReport:
    generated_at: str
    account_name: str
    success: bool
    steps_completed: list[str] = field(default_factory=list)
    staging_files: int = 0
    merged_count: int = 0
    raw_count: int = 0
    overlays_merged: int = 0
    metadata_applied: int = 0
    failed: int = 0
    quarantined: int = 0
    integrity_repairs: int = 0
    corrupt_images_found: int = 0
    corrupt_image_names: list[str] = field(default_factory=list)
    duplicate_groups: int = 0
    webp_outputs: int = 0
    staging_bytes: int = 0
    merged_bytes: int = 0
    safe_to_delete_staging: bool = False
    staging_deleted: bool = False
    staging_freed: str = ""
    staging_kept_by_setting: bool = False
    quality_note: str = ""
    notes: list[str] = field(default_factory=list)
    # Completeness: staging_main_count is the ground truth - how many memories
    # SMD actually found to process for this export (matched from the JSON +
    # ZIP staging). completeness_checked is True only when the full
    # per-memory ffprobe/output-matching pass ran (check_staging_readiness);
    # when staging is kept and that check is skipped, we still show the two
    # cheap folder counts (merged_count/raw_count vs staging_main_count) but
    # flag completeness_checked=False since that's a weaker (count-only, not
    # per-file) signal.
    staging_main_count: int = 0
    outputs_verified: int = 0
    missing_merged_count: int = 0
    missing_raw_count: int = 0
    completeness_checked: bool = False

    def _completeness_banner(self) -> str:
        """Prominent, plain-language answer to "did I lose any files?" -
        shown before anything else so it can't be missed. Green only when
        the exhaustive per-memory check actually ran and found zero gaps."""
        style = (
            "margin:0 0 14px 0;padding:12px 16px;border-radius:8px;"
            "font-size:14px;{color}"
        )
        if self.completeness_checked:
            missing = self.missing_merged_count + self.missing_raw_count
            if missing == 0 and self.outputs_verified >= self.staging_main_count:
                box = style.format(color="background:#1f4d2b;color:#c8f5d0;")
                return (
                    f"<div style='{box}'>✅ <b>All {self.staging_main_count:,} memories from "
                    f"your export are in your library.</b> Every file SMD found in the "
                    f"JSON + ZIP was verified present in merged/ (and raw/, if enabled) "
                    f"- nothing is missing.</div>"
                )
            box = style.format(color="background:#5a2626;color:#ffd6d6;")
            return (
                f"<div style='{box}'>⚠ <b>{missing} of {self.staging_main_count:,} memories "
                f"need attention.</b> {self.outputs_verified:,} verified OK, "
                f"{self.missing_merged_count} missing from merged/, "
                f"{self.missing_raw_count} missing from raw/. See Storage below, or "
                f"re-run processing with the same account name to fill in the gaps.</div>"
            )
        # Full per-memory check was skipped ("Keep staging media files") -
        # only cheap folder counts are available, so keep this neutral.
        box = style.format(color="background:#3a3a1f;color:#f0e6b8;")
        note = (
            f"{self.merged_count:,} files in merged/ for {self.staging_main_count:,} "
            f"memories detected in this export."
        )
        return (
            f"<div style='{box}'>ℹ <b>Full per-file verification was skipped</b> because "
            f"\"Keep staging media files\" is on. {note} If the counts don't roughly "
            f"match, turn that setting off and re-run to get an exact check.</div>"
        )

    def summary_html(self) -> str:
        status = "Completed successfully" if self.success else "Finished with issues"
        lines = [
            f"<h2>Processing summary</h2>",
            f"<p><b>Account:</b> {self.account_name}<br><b>Status:</b> {status}</p>",
            self._completeness_banner(),
            "<h3>What ran</h3><ul>",
        ]
        for step in self.steps_completed:
            lines.append(f"<li>{step}</li>")
        lines.append("</ul>")
        lines.append("<h3>Your library</h3><ul>")
        lines.append(f"<li><b>Merged:</b> {self.merged_count:,} files ({format_bytes(self.merged_bytes)})</li>")
        lines.append(f"<li><b>Raw:</b> {self.raw_count:,} files</li>")
        lines.append(f"<li><b>Overlays merged:</b> {self.overlays_merged:,}</li>")
        lines.append(f"<li><b>Metadata applied:</b> {self.metadata_applied:,}</li>")
        if self.webp_outputs:
            lines.append(
                f"<li><b>WebP files:</b> {self.webp_outputs} "
                f"(Snapchat exported these as WebP, not JPEG)</li>"
            )
        lines.append("</ul>")
        lines.append("<h3>Quality and repairs</h3><ul>")
        if self.quality_note:
            lines.append(f"<li>{self.quality_note}</li>")
        if self.integrity_repairs:
            lines.append(
                f"<li><b>Auto repaired during run:</b> {self.integrity_repairs} "
                f"(bad output replaced with original media)</li>"
            )
        if self.corrupt_images_found:
            lines.append(
                f"<li><b>Corrupt images still in merged:</b> {self.corrupt_images_found} "
                f"- try the matching file in raw/ if you saved plain copies</li>"
            )
            for name in self.corrupt_image_names[:5]:
                lines.append(f"<li style='margin-left:1em;color:#c00;'>{name}</li>")
        else:
            lines.append("<li>No corrupt JPEG/PNG detected in merged</li>")
        lines.append("</ul>")
        lines.append("<h3>Storage</h3><ul>")
        lines.append(
            f"<li><b>Staging:</b> {self.staging_files:,} working files "
            f"({format_bytes(self.staging_bytes)})</li>"
        )
        if self.staging_kept_by_setting:
            lines.append(
                "<li>Staging kept because \"Keep staging media files\" is turned on - "
                "the integrity check was skipped and technical/staging/ was left in place.</li>"
            )
        elif self.safe_to_delete_staging:
            if self.staging_deleted and self.staging_freed:
                lines.append(f"<li>Staging cleaned up automatically ({self.staging_freed} freed).</li>")
            else:
                lines.append("<li>Staging check passed.</li>")
        else:
            lines.append("<li>Some outputs may still be finishing — run again with the same name if files look incomplete.</li>")
        if self.duplicate_groups:
            lines.append(
                f"<li><b>Duplicate content groups:</b> {self.duplicate_groups:,} "
                f"- use <b>Review duplicates</b> to keep the copies you want and delete the rest</li>"
            )
        lines.append("</ul>")
        if self.notes:
            lines.append("<h3>Notes</h3><ul>")
            for n in self.notes:
                lines.append(f"<li>{n}</li>")
            lines.append("</ul>")
        return "\n".join(lines)

    def to_dict(self) -> dict:
        return asdict(self)


def build_session_report(
    account_dir: Path,
    *,
    stats: LocalProcessStats | None = None,
    success: bool = True,
    steps: list[str] | None = None,
    require_raw: bool = True,
    staging_deleted: bool = False,
    staging_freed: str = "",
    layout: AccountPaths | None = None,
    readiness=None,
    skip_staging_check: bool = False,
) -> SessionReport:
    paths = layout or resolve_account_paths(account_dir, migrate=False, create=False)
    account_name = paths.account_dir.name
    items = _load_items_from_staging(paths.staging_dir)
    staging_main = sum(1 for it in items.values() if it.main_path)

    merged_files = list(paths.merged_dir.iterdir()) if paths.merged_dir.is_dir() else []
    merged_count = sum(1 for p in merged_files if p.is_file())
    raw_count = sum(1 for p in paths.raw_dir.iterdir() if p.is_file()) if paths.raw_dir.is_dir() else 0
    webp_count = sum(1 for p in merged_files if p.suffix.lower() == ".webp")

    corrupt: list[str] = []
    for p in merged_files:
        if p.suffix.lower() not in (".jpg", ".jpeg", ".png", ".webp"):
            continue
        ok, _ = validate_image_file(p)
        if not ok:
            corrupt.append(p.name)

    duplicate_groups = load_cached_duplicate_group_count(paths)
    if skip_staging_check:
        readiness = None
    elif readiness is None:
        # check_staging_readiness() ffprobes every video in staging, which is
        # expensive on large libraries - callers that already ran it (e.g. the
        # post-run StagingVerifyWorker) should pass the result in instead of
        # paying for a second full scan here.
        readiness = check_staging_readiness(account_dir, layout=paths, require_raw=require_raw)

    default_steps = steps or [
        "Detected export format",
        "Copied JSON metadata",
        "Extracted or reused ZIP staging",
        "Matched files to JSON rows",
        "Merged overlays and saved merged + raw",
        "Applied date and GPS metadata",
        "Saved reports",
    ]

    report = SessionReport(
        generated_at=datetime.now(timezone.utc).isoformat(),
        account_name=account_name,
        success=success and stats.failed == 0 if stats else success,
        steps_completed=default_steps,
        staging_files=staging_main,
        merged_count=merged_count,
        raw_count=raw_count,
        overlays_merged=stats.merged if stats else 0,
        metadata_applied=stats.metadata_applied if stats else 0,
        failed=stats.failed if stats else 0,
        quarantined=stats.quarantined if stats else 0,
        integrity_repairs=getattr(stats, "integrity_repairs", 0) if stats else 0,
        corrupt_images_found=len(corrupt),
        corrupt_image_names=corrupt[:20],
        duplicate_groups=duplicate_groups,
        webp_outputs=webp_count,
        staging_bytes=folder_size_bytes(paths.staging_dir),
        merged_bytes=folder_size_bytes(paths.merged_dir),
        safe_to_delete_staging=readiness.safe_to_delete if readiness is not None else False,
        staging_deleted=staging_deleted,
        staging_freed=staging_freed,
        staging_kept_by_setting=skip_staging_check,
        staging_main_count=readiness.staging_main_count if readiness is not None else staging_main,
        outputs_verified=readiness.outputs_verified if readiness is not None else 0,
        missing_merged_count=len(readiness.missing_merged) if readiness is not None else 0,
        missing_raw_count=len(readiness.missing_raw) if readiness is not None else 0,
        completeness_checked=readiness is not None,
        quality_note=(
            "Photos are saved at maximum JPEG quality. "
            "Video overlays are re-encoded at visually lossless quality when "
            "Snapchat filters are merged, without the huge file sizes of true "
            "lossless encoding."
        ),
    )
    if stats and stats.failed:
        report.notes.append(f"{stats.failed} item(s) failed. See technical/logs/.")
    if stats and stats.quarantined:
        report.notes.append(f"{stats.quarantined} file(s) moved to technical/quarantine/.")
    return report


def save_session_report(paths: AccountPaths, report: SessionReport) -> Path:
    paths.reports_dir.mkdir(parents=True, exist_ok=True)
    out = paths.reports_dir / "session_summary.json"
    out.write_text(json.dumps(report.to_dict(), indent=2), encoding="utf-8")
    return out
