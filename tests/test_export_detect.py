"""Tests for export format detection (offline bundled vs unsupported)."""
import json
import tempfile
import zipfile
from pathlib import Path

from smd.export_detect import ExportFormat, analyze_zip_export


def _write_bundled_zip(path: Path, *, with_links: bool = False) -> None:
    row = {
        "Date": "2026-04-17 09:14:49 UTC",
        "Media Type": "Image",
        "Location": "",
    }
    if with_links:
        row["Download Link"] = (
            "https://app.snapchat.com/dmd/memories?uid=x&mid=0aaa0107-7afa-01c7-c3fc-0e31fc14ad8b"
        )
    payload = {"Saved Media": [row]}
    with zipfile.ZipFile(path, "w") as zf:
        zf.writestr("memories_history.json", json.dumps(payload))
        zf.writestr(
            "memories/2026-04-17_0aaa0107-7afa-01c7-c3fc-0e31fc14ad8b-main.jpg",
            b"\xff\xd8\xff" + b"\x00" * 1024,
        )


def _write_links_only_zip(path: Path) -> None:
    payload = {
        "Saved Media": [
            {
                "Date": "2026-04-17 09:14:49 UTC",
                "Media Type": "Image",
                "Download Link": "https://example.test/memories?mid=abc",
            }
        ]
    }
    with zipfile.ZipFile(path, "w") as zf:
        zf.writestr("memories_history.json", json.dumps(payload))


def test_bundled_export_detected_even_with_links_in_json():
    with tempfile.TemporaryDirectory() as tmp:
        zpath = Path(tmp) / "mydata~123.zip"
        _write_bundled_zip(zpath, with_links=True)
        analysis = analyze_zip_export(zpath)
        assert analysis.format == ExportFormat.BUNDLED_LOCAL
        assert analysis.is_bundled
        assert analysis.is_supported
        assert "offline" in analysis.message.lower()


def test_links_only_export_is_unsupported():
    with tempfile.TemporaryDirectory() as tmp:
        zpath = Path(tmp) / "mydata~456.zip"
        _write_links_only_zip(zpath)
        analysis = analyze_zip_export(zpath)
        assert analysis.format == ExportFormat.LINKS_ONLY
        assert not analysis.is_bundled
        assert not analysis.is_supported
        assert "link-only" in analysis.message.lower()


def test_empty_export():
    with tempfile.TemporaryDirectory() as tmp:
        zpath = Path(tmp) / "empty.zip"
        with zipfile.ZipFile(zpath, "w") as zf:
            zf.writestr("readme.txt", "hello")
        analysis = analyze_zip_export(zpath)
        assert analysis.format == ExportFormat.EMPTY
