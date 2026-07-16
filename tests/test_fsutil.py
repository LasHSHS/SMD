"""Tests for atomic file helpers."""
import os
import tempfile
from pathlib import Path
from unittest.mock import patch

from smd.fsutil import atomic_copy, atomic_write_bytes, atomic_write_text, link_or_copy, tmp_sibling


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


def test_link_or_copy_creates_real_hardlink():
    with tempfile.TemporaryDirectory() as tmp:
        src = Path(tmp) / "src.bin"
        dest = Path(tmp) / "dest.bin"
        atomic_write_bytes(src, b"payload")

        linked = link_or_copy(src, dest)

        assert linked is True
        assert dest.read_bytes() == b"payload"
        assert dest.stat().st_ino == src.stat().st_ino
        assert dest.stat().st_nlink >= 2


def test_link_or_copy_replaces_existing_dest_atomically():
    with tempfile.TemporaryDirectory() as tmp:
        src = Path(tmp) / "src.bin"
        dest = Path(tmp) / "dest.bin"
        atomic_write_bytes(src, b"new-payload")
        atomic_write_bytes(dest, b"stale-payload")

        link_or_copy(src, dest)

        assert dest.read_bytes() == b"new-payload"


def test_link_or_copy_falls_back_to_copy_when_linking_unsupported():
    with tempfile.TemporaryDirectory() as tmp:
        src = Path(tmp) / "src.bin"
        dest = Path(tmp) / "dest.bin"
        atomic_write_bytes(src, b"payload")

        with patch("smd.fsutil.os.link", side_effect=OSError("cross-device link")):
            linked = link_or_copy(src, dest)

        assert linked is False
        assert dest.read_bytes() == b"payload"
        # A real, independent copy - not sharing the source's inode.
        assert dest.stat().st_ino != src.stat().st_ino
