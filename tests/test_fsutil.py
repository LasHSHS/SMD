"""Tests for atomic file helpers."""
import tempfile
from pathlib import Path

from smd.fsutil import atomic_copy, atomic_write_bytes, atomic_write_text, tmp_sibling


def test_tmp_sibling_keeps_extension():
    assert tmp_sibling(Path("photo.jpg")) == Path("photo.tmp.jpg")


def test_atomic_write_text_replaces_atomically():
    with tempfile.TemporaryDirectory() as tmp:
        dest = Path(tmp) / "out.txt"
        atomic_write_text(dest, "first")
        atomic_write_text(dest, "second")
        assert dest.read_text(encoding="utf-8") == "second"


def test_atomic_copy():
    with tempfile.TemporaryDirectory() as tmp:
        src = Path(tmp) / "src.bin"
        dest = Path(tmp) / "dest.bin"
        atomic_write_bytes(src, b"payload")
        atomic_copy(src, dest)
        assert dest.read_bytes() == b"payload"
