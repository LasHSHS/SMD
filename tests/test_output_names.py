"""Tests for collision-safe bundled export output naming."""
from pathlib import Path

from smd.local_pipeline import (
    BundledMediaItem,
    build_allowed_output_filenames,
    build_unique_output_names,
    collision_stems_from_report,
    prune_stale_outputs,
    reconcile_checkpoint_with_disk,
    stem_has_output_on_disk,
)
from smd.models import Memory
from datetime import datetime, timezone


def _item(stem: str, uid: str, ext: str = ".mp4") -> BundledMediaItem:
    date = stem.split("_")[0]
    return BundledMediaItem(
        stem=stem,
        date_prefix=date,
        uid=uid,
        main_ext=ext,
    )


def _memory(ts: str) -> Memory:
    return Memory.model_validate(
        {"Date": f"{ts} UTC", "Download Link": "", "Location": ""}
    )


def test_unique_names_when_same_json_time():
    items = {
        "a": _item("2020-12-14_a", "0610d8a6-fbce-c5c9-35c2-550484a732a0"),
        "b": _item("2020-12-14_b", "3055c4c3-4c08-ebc5-140b-accc4f94a93f"),
    }
    for it in items.values():
        it.main_path = Path(f"/fake/{it.stem}-main.mp4")
    mem = _memory("2020-12-14 19:44:01")
    match_map = {"a": mem, "b": mem}

    names, report = build_unique_output_names(items, match_map)

    assert len(report) == 1
    assert names["a"] != names["b"]
    assert len(set(names.values())) == 2
    assert "3055c4c3" in names["b"] or names["b"].startswith(Path(names["a"]).stem + "_")


def test_collision_stems_from_report():
    report = [{"stems": ["a", "b", "c"]}]
    assert collision_stems_from_report(report) == {"a", "b", "c"}


def test_reconcile_removes_done_without_output(tmp_path):
    merged = tmp_path / "merged_reconcile"
    merged.mkdir()
    items = {
        "a": _item("2020-12-14_a", "0610d8a6-fbce-c5c9-35c2-550484a732a0"),
        "b": _item("2020-12-14_b", "3055c4c3-4c08-ebc5-140b-accc4f94a93f"),
    }
    for it in items.values():
        it.main_path = tmp_path / f"{it.stem}-main.mp4"
    names = {"a": "2020-12-14_19-44-01.mp4", "b": "2020-12-14_19-44-01_b.mp4"}
    (merged / names["a"]).write_bytes(b"x" * 1024)

    done, skipped, missing = reconcile_checkpoint_with_disk(
        {"a", "b"}, set(), items, names, merged
    )
    assert done == {"a"}
    assert missing == ["b"]


def test_prune_stale_outputs(tmp_path):
    merged = tmp_path / "merged_prune"
    raw = tmp_path / "raw_prune"
    merged.mkdir()
    raw.mkdir()
    (merged / "keep.mp4").write_bytes(b"x" * 1024)
    (merged / "orphan.mp4").write_bytes(b"y" * 1024)
    (raw / "orphan.mp4").write_bytes(b"z" * 1024)

    removed, nbytes = prune_stale_outputs(merged, raw, {"keep.mp4"})
    assert removed == 2
    assert nbytes == 2048
    assert (merged / "keep.mp4").exists()
    assert not (merged / "orphan.mp4").exists()
    assert not (raw / "orphan.mp4").exists()


def test_build_allowed_output_filenames_includes_resolved_ext(tmp_path):
    item = _item("2020-12-14_a", "0610d8a6-fbce-c5c9-35c2-550484a732a0", ".webp")
    item.main_path = tmp_path / "main.webp"
    names = {"2020-12-14_a": "2020-12-14_19-44-01.mp4"}
    allowed = build_allowed_output_filenames(
        {"2020-12-14_a": item},
        names,
    )
    assert "2020-12-14_19-44-01.mp4" in allowed
    assert "2020-12-14_19-44-01.webp" in allowed
