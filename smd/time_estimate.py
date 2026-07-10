"""Rough processing time estimates for bundled exports."""
from __future__ import annotations

from smd.system_profile import PERF_MODES, SystemProfile, compute_workers, get_system_profile


def _format_duration(seconds: float) -> str:
    if seconds < 60:
        return f"{int(seconds)} sec"
    if seconds < 3600:
        return f"{int(seconds // 60)} min {int(seconds % 60)} sec"
    hours = int(seconds // 3600)
    mins = int((seconds % 3600) // 60)
    return f"{hours} hr {mins} min"


def estimate_bundled_processing(
    file_count: int,
    *,
    profile: SystemProfile | None = None,
    overlay_fraction: float = 0.24,
    video_fraction: float = 0.12,
    needs_zip_extract: bool = False,
    staging_gb: float = 0.0,
) -> dict[str, dict[str, str | float]]:
    """
    Estimate merge/metadata time per performance mode.
    Returns {mode: {seconds, label, workers, note}}.
    """
    profile = profile or get_system_profile()
    file_count = max(1, int(file_count))

    # Empirical seconds per item (tuned on ~700-file bundled runs with warm staging)
    base = 0.06
    overlay_img = 0.35
    overlay_vid = 2.5
    per_item = (
        base
        + overlay_fraction * overlay_img
        + overlay_fraction * video_fraction * overlay_vid
    )

    extract_sec = 0.0
    if needs_zip_extract:
        gb = staging_gb if staging_gb > 0 else max(1.0, file_count * 0.003)
        # First-time ZIP extract; warm staging/resume skips this entirely.
        extract_sec = gb * 14

    results: dict[str, dict[str, str | float]] = {}
    for mode in PERF_MODES:
        settings = compute_workers(mode, profile, task="export")
        workers = max(1, settings.max_workers)
        merge_sec = (file_count * per_item) / workers
        if mode == "conservative":
            merge_sec *= 1.35
        elif mode == "balanced":
            merge_sec *= 1.1
        total = extract_sec + merge_sec
        note_parts = []
        if needs_zip_extract:
            note_parts.append("includes ZIP extract from scratch")
        if mode == "conservative":
            note_parts.append("leaves CPU headroom for other work")
        elif mode == "maximum":
            note_parts.append("uses most of your CPU")
        results[mode] = {
            "seconds": total,
            "label": _format_duration(total),
            "workers": workers,
            "note": "; ".join(note_parts) if note_parts else "estimate only",
        }
    return results
