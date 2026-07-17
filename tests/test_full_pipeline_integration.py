"""End-to-end integration tests for the bundled export pipeline.

Unlike the other tests/test_*.py files, which each exercise one helper
function in isolation (matching, naming, hardlinking, staging checks...),
this file drives the real top-level entry point - process_bundled_export()
- against a synthetic-but-real ZIP export (real JPEGs via Pillow, a real
tiny MP4 via the bundled ffmpeg) and checks the whole chain end to end:

    ZIP -> extract -> JSON match -> merge/hardlink -> checkpoint
        -> resume after a simulated crash -> check_staging_readiness

This is the safety net for the exact class of bug that would actually lose
or corrupt someone's memories, which the narrower unit tests can't catch on
their own since they each mock or bypass the surrounding orchestration.
"""
from __future__ import annotations

import json
import zipfile
from pathlib import Path

import pytest
from PIL import Image

from smd.account_layout import AccountPaths
from smd.ffmpeg_bundle import ffmpeg_available, resolve_ffmpeg
from smd.local_pipeline import _load_checkpoint, process_bundled_export
from smd.staging_check import check_staging_readiness

# Three items, deliberately covering the three cases that matter most:
#   PLAIN  - image, no overlay      -> keep_raw hardlink fast path
#   OVERLAY - image, with overlay   -> merged/raw must differ (burned-in)
#   VIDEO  - video, no overlay      -> real ffmpeg remux + hardlink + deep ffprobe check
UID_PLAIN = "aaaaaaaa-0000-0000-0000-000000000001"
UID_OVERLAY = "bbbbbbbb-0000-0000-0000-000000000002"
UID_VIDEO = "cccccccc-0000-0000-0000-000000000003"
DATE_PREFIX = "2026-04-17"


def _mid_link(uid: str) -> str:
    return f"https://app.snapchat.com/dmd/memories?uid=x&sid=y&mid={uid}&ts=1&sig=z"


def _make_synthetic_mp4(path: Path) -> None:
    import subprocess

    ffmpeg = resolve_ffmpeg()
    assert ffmpeg, "bundled ffmpeg must be present for this test"
    subprocess.run(
        [
            ffmpeg, "-y",
            "-f", "lavfi", "-i", "color=c=blue:s=32x32:d=1:r=5",
            "-pix_fmt", "yuv420p", "-c:v", "libx264", "-preset", "ultrafast",
            str(path),
        ],
        capture_output=True,
        check=True,
        timeout=30,
    )


def _build_export_zip(tmp_path: Path) -> Path:
    """Build a small but real bundled-export ZIP with 3 memories + matching JSON."""
    work = tmp_path / "_build"
    work.mkdir()

    plain_main = work / f"{DATE_PREFIX}_{UID_PLAIN}-main.jpg"
    Image.new("RGB", (16, 16), "red").save(plain_main, format="JPEG", quality=90)

    overlay_main = work / f"{DATE_PREFIX}_{UID_OVERLAY}-main.jpg"
    Image.new("RGB", (16, 16), "green").save(overlay_main, format="JPEG", quality=90)
    overlay_png = work / f"{DATE_PREFIX}_{UID_OVERLAY}-overlay.png"
    Image.new("RGBA", (16, 16), (0, 0, 255, 160)).save(overlay_png, format="PNG")

    video_main = work / f"{DATE_PREFIX}_{UID_VIDEO}-main.mp4"
    _make_synthetic_mp4(video_main)

    memories_history = {
        "Saved Media": [
            {
                "Date": "2026-04-17 09:00:00 UTC",
                "Media Type": "Image",
                "Download Link": _mid_link(UID_PLAIN),
                "Location": "Latitude, Longitude: 55.6761, 12.5683",
            },
            {
                "Date": "2026-04-17 10:00:00 UTC",
                "Media Type": "Image",
                "Download Link": _mid_link(UID_OVERLAY),
                "Location": "",
            },
            {
                "Date": "2026-04-17 11:00:00 UTC",
                "Media Type": "Video",
                "Download Link": _mid_link(UID_VIDEO),
                "Location": "",
            },
        ]
    }

    zip_path = tmp_path / "export.zip"
    with zipfile.ZipFile(zip_path, "w") as zf:
        zf.write(plain_main, f"memories/{plain_main.name}")
        zf.write(overlay_main, f"memories/{overlay_main.name}")
        zf.write(overlay_png, f"memories/{overlay_png.name}")
        zf.write(video_main, f"memories/{video_main.name}")
        zf.writestr("json/memories_history.json", json.dumps(memories_history))

    return zip_path


def _run_pipeline(zip_path: Path, account_dir: Path) -> tuple:
    paths = AccountPaths.for_account(account_dir)
    stats = process_bundled_export(
        zip_path,
        account_dir,
        zip_paths=[zip_path],
        max_workers=2,
        max_ffmpeg=2,
        ffmpeg_threads=1,
        layout=paths,
    )
    return stats, paths


pytestmark = pytest.mark.skipif(
    not ffmpeg_available(), reason="bundled/system ffmpeg not available"
)


def test_full_run_produces_correct_outputs_and_passes_verification(tmp_path):
    zip_path = _build_export_zip(tmp_path)
    account_dir = tmp_path / "account"

    stats, paths = _run_pipeline(zip_path, account_dir)

    assert stats.failed == 0
    assert stats.quarantined == 0
    assert stats.json_matched == 3
    assert stats.files_extracted == 4  # 3 mains + 1 overlay

    merged_files = sorted(p.name for p in paths.merged_dir.iterdir())
    raw_files = sorted(p.name for p in paths.raw_dir.iterdir())
    assert len(merged_files) == 3
    assert len(raw_files) == 3
    assert sum(1 for n in merged_files if n.endswith(".jpg")) == 2
    assert sum(1 for n in merged_files if n.endswith(".mp4")) == 1

    # PLAIN and VIDEO have no overlay + keep_raw defaults True -> hardlinked
    # (same bytes, no point in a second on-disk copy). OVERLAY must differ
    # (burned-in overlay means genuinely different bytes). Compare merged vs
    # raw bytes/inodes directly for every output name rather than guessing
    # which output name belongs to which item.
    overlay_applied_count = 0
    hardlinked_count = 0
    for name in merged_files:
        merged_out = paths.merged_dir / name
        raw_out = paths.raw_dir / name
        assert raw_out.is_file()
        if merged_out.stat().st_ino == raw_out.stat().st_ino:
            hardlinked_count += 1
        else:
            overlay_applied_count += 1
            assert merged_out.read_bytes() != raw_out.read_bytes()

    assert hardlinked_count == 2  # plain image + video
    assert overlay_applied_count == 1  # the overlay image

    # Checkpoint reflects all 3 items as done.
    done, skipped, _version = _load_checkpoint(paths.checkpoint_path)
    assert len(done) == 3
    assert not skipped

    # The exhaustive post-run integrity gate (ffprobes the real video too)
    # must agree everything is safe to delete staging for.
    report = check_staging_readiness(account_dir, layout=paths)
    assert report.safe_to_delete, report.issues
    assert report.outputs_verified == 3


def test_resume_reprocesses_item_after_missing_merged_output(tmp_path):
    """Simulates a crash/disk-full right after a merged/ file was deleted or
    never finished writing, despite the checkpoint saying it was done -
    process_bundled_export must detect and repair it on the next run rather
    than trusting a stale checkpoint (see reconcile_checkpoint_with_disk)."""
    zip_path = _build_export_zip(tmp_path)
    account_dir = tmp_path / "account"

    _run_pipeline(zip_path, account_dir)
    paths = AccountPaths.for_account(account_dir)

    merged_files = sorted(paths.merged_dir.iterdir())
    assert len(merged_files) == 3
    victim = merged_files[0]
    victim_name = victim.name
    victim.unlink()  # merged/ output vanished; raw/ (hardlink partner) still intact
    assert not (paths.merged_dir / victim_name).exists()

    stats2, paths2 = _run_pipeline(zip_path, account_dir)

    # Reprocessed exactly the one broken item, not all 3 again - resuming
    # must be an efficient repair, not a silent full redo every time.
    assert stats2.failed == 0
    assert stats2.json_matched == 1
    restored = paths2.merged_dir / victim_name
    assert restored.is_file()
    assert len(list(paths2.merged_dir.iterdir())) == 3

    done, _skipped, _version = _load_checkpoint(paths2.checkpoint_path)
    assert len(done) == 3

    report = check_staging_readiness(account_dir, layout=paths2)
    assert report.safe_to_delete, report.issues
