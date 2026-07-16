"""Regression tests for the raw/merged hardlink fast path.

When keep_raw is on and an item has no overlay, raw/ and merged/ should end
up as the *same file on disk* (a hardlink), not two independent copies -
see agent-docs/DECISIONS.md ("raw/merged hardlinked when identical").
"""
from datetime import datetime, timezone
from pathlib import Path

from PIL import Image

from smd.local_pipeline import BundledMediaItem, _process_single_item
from smd.models import Memory


def _make_jpeg(path: Path, color: str = "red") -> None:
    Image.new("RGB", (8, 8), color=color).save(path, format="JPEG", quality=90)


def _memory(lat: float | None = None, lon: float | None = None) -> Memory:
    return Memory(
        Date="2026-04-17 09:14:49 UTC",
        **{"Media Type": "Image", "Download Link": ""},
        latitude=lat,
        longitude=lon,
    )


def _item(tmp_path: Path, *, overlay: bool = False) -> BundledMediaItem:
    main_path = tmp_path / "staging" / "2026-04-17_abc-main.jpg"
    main_path.parent.mkdir(parents=True, exist_ok=True)
    _make_jpeg(main_path)

    overlay_path = None
    if overlay:
        overlay_path = tmp_path / "staging" / "2026-04-17_abc-overlay.png"
        Image.new("RGBA", (8, 8), color=(0, 255, 0, 128)).save(overlay_path, format="PNG")

    return BundledMediaItem(
        stem="2026-04-17_abc",
        date_prefix="2026-04-17",
        uid="abc",
        main_path=main_path,
        overlay_path=overlay_path,
        main_ext=".jpg",
    )


def _dirs(tmp_path: Path) -> dict[str, Path]:
    merged = tmp_path / "merged"
    raw = tmp_path / "raw"
    quarantine = tmp_path / "quarantine"
    staging = tmp_path / "staging"
    for d in (merged, raw, quarantine, staging):
        d.mkdir(parents=True, exist_ok=True)
    return {"merged": merged, "raw": raw, "quarantine": quarantine, "staging": staging}


def test_no_overlay_keep_raw_hardlinks_merged_to_raw(tmp_path: Path):
    dirs = _dirs(tmp_path)
    item = _item(tmp_path)
    memory = _memory(lat=55.6761, lon=12.5683)

    out = _process_single_item(
        item.stem,
        item,
        memory,
        merged_dir=dirs["merged"],
        raw_dir=dirs["raw"],
        quarantine_dir=dirs["quarantine"],
        staging_dir=dirs["staging"],
        merge_overlays=True,
        keep_raw=True,
        repair_videos=False,
        apply_meta=True,
        ffmpeg_sem=None,
        planned_output_name=memory.filename,
    )

    assert out.done
    assert out.failed == 0
    assert out.raw_copied == 1

    raw_out = dirs["raw"] / f"{memory.filename}.jpg"
    merged_out = dirs["merged"] / f"{memory.filename}.jpg"
    assert raw_out.is_file()
    assert merged_out.is_file()

    # Same file on disk, not two independent copies.
    assert raw_out.stat().st_ino == merged_out.stat().st_ino
    assert raw_out.stat().st_nlink >= 2
    assert raw_out.read_bytes() == merged_out.read_bytes()


def test_overlay_item_does_not_hardlink(tmp_path: Path):
    dirs = _dirs(tmp_path)
    item = _item(tmp_path, overlay=True)
    memory = _memory()

    out = _process_single_item(
        item.stem,
        item,
        memory,
        merged_dir=dirs["merged"],
        raw_dir=dirs["raw"],
        quarantine_dir=dirs["quarantine"],
        staging_dir=dirs["staging"],
        merge_overlays=True,
        keep_raw=True,
        repair_videos=False,
        apply_meta=True,
        ffmpeg_sem=None,
        planned_output_name=memory.filename,
    )

    assert out.done
    raw_out = dirs["raw"] / f"{memory.filename}.jpg"
    merged_out = dirs["merged"] / f"{memory.filename}.jpg"
    assert raw_out.is_file()
    assert merged_out.is_file()

    # Overlay burned into merged/ only - must NOT be the same file as raw/.
    assert raw_out.stat().st_ino != merged_out.stat().st_ino
    assert raw_out.read_bytes() != merged_out.read_bytes()


def test_keep_raw_off_skips_fast_path_and_raw_output(tmp_path: Path):
    dirs = _dirs(tmp_path)
    item = _item(tmp_path)
    memory = _memory()

    out = _process_single_item(
        item.stem,
        item,
        memory,
        merged_dir=dirs["merged"],
        raw_dir=dirs["raw"],
        quarantine_dir=dirs["quarantine"],
        staging_dir=dirs["staging"],
        merge_overlays=True,
        keep_raw=False,
        repair_videos=False,
        apply_meta=True,
        ffmpeg_sem=None,
        planned_output_name=memory.filename,
    )

    assert out.done
    assert out.raw_copied == 0
    merged_out = dirs["merged"] / f"{memory.filename}.jpg"
    raw_out = dirs["raw"] / f"{memory.filename}.jpg"
    assert merged_out.is_file()
    assert not raw_out.exists()
