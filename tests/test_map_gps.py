from datetime import datetime, timezone
from pathlib import Path

from smd.map_gps import build_json_coord_lookup, lookup_json_coords, resolve_memories_json
from smd.models import Memory


def test_build_json_coord_lookup_indexes_local_and_utc_stems():
    memory = Memory(
        Date="2026-04-17 09:14:49 UTC",
        Location="Latitude, Longitude: 56.15527, 10.186975",
        **{"Download Link": ""},
    )
    lookup = build_json_coord_lookup([memory])
    assert lookup[memory.filename] == (56.15527, 10.186975)
    assert lookup["2026-04-17_09-14-49"] == (56.15527, 10.186975)


def test_lookup_json_coords_matches_disambiguated_filename():
    memory = Memory(
        Date="2026-04-17 09:14:49 UTC",
        Location="Latitude, Longitude: 56.15527, 10.186975",
        **{"Download Link": ""},
    )
    lookup = build_json_coord_lookup([memory])
    coords = lookup_json_coords(lookup, Path("2026-04-17_11-14-49_017bb5c1a4a1.jpg"))
    assert coords == (56.15527, 10.186975)


def test_resolve_memories_json_from_account_tree(tmp_path: Path):
    account = tmp_path / "Las"
    json_path = account / "technical" / "json" / "memories_history.json"
    json_path.parent.mkdir(parents=True)
    json_path.write_text('{"Saved Media": []}', encoding="utf-8")
    merged = account / "downloads" / "merged"
    merged.mkdir(parents=True)

    resolved = resolve_memories_json(merged)
    assert resolved == json_path
