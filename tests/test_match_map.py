"""Tests for UID-based JSON matching in the bundled pipeline."""
from datetime import datetime, timezone

from smd.local_pipeline import (
    BundledMediaItem,
    build_deterministic_match_map,
    build_match_map,
)
from smd.models import Memory


def _memory(date_utc: str, media_type: str, mid: str | None = None) -> Memory:
    link = ""
    if mid:
        link = f"https://app.snapchat.com/dmd/memories?uid=x&sid=y&mid={mid}&ts=1&sig=z"
    return Memory(
        Date=date_utc,
        **{"Media Type": media_type, "Download Link": link},
    )


def _item(date_prefix: str, uid: str, ext: str = ".jpg") -> BundledMediaItem:
    from pathlib import Path

    stem = f"{date_prefix}_{uid}"
    return BundledMediaItem(
        stem=stem,
        date_prefix=date_prefix,
        uid=uid,
        main_path=Path(f"{stem}-main{ext}"),
        main_ext=ext,
    )


def test_uid_match_beats_positional_order():
    # Two images same day; JSON rows listed in the "wrong" order relative to
    # filename sort - UID matching must still pair them correctly.
    uid_a = "0aaa0107-7afa-01c7-c3fc-0e31fc14ad8b"
    uid_b = "fed50595-692d-55e1-2391-58c7607af190"
    mem_a = _memory("2026-04-17 09:14:49 UTC", "Image", uid_a)
    mem_b = _memory("2026-04-17 08:00:00 UTC", "Image", uid_b)

    items = {
        f"2026-04-17_{uid_a}": _item("2026-04-17", uid_a),
        f"2026-04-17_{uid_b}": _item("2026-04-17", uid_b),
    }

    match_map = build_match_map(items, [mem_a, mem_b])
    assert match_map[f"2026-04-17_{uid_a}"] is mem_a
    assert match_map[f"2026-04-17_{uid_b}"] is mem_b

    # Positional fallback alone would swap them (sorted by time vs by stem).
    positional = build_deterministic_match_map(items, [mem_a, mem_b])
    assert positional[f"2026-04-17_{uid_a}"] is mem_b


def test_unmatched_uids_fall_back_to_positional():
    uid = "1111aaaa-bbbb-cccc-dddd-eeeeffff0000"
    mem = _memory("2026-04-17 09:14:49 UTC", "Image")  # no mid= link
    items = {f"2026-04-17_{uid}": _item("2026-04-17", uid)}

    match_map = build_match_map(items, [mem])
    assert match_map[f"2026-04-17_{uid}"] is mem


def test_memory_dates_parse_as_utc():
    mem = _memory("2026-04-17 09:14:49 UTC", "Image")
    assert mem.date == datetime(2026, 4, 17, 9, 14, 49, tzinfo=timezone.utc)
