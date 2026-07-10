"""Crash-safe file writes: write to a temp sibling, then atomically replace.

A crash, power loss, or disk-full during a direct write leaves a half-written
file at the final path that later runs may treat as a valid output. Writing to
a ``*.tmp*`` sibling first and finishing with ``os.replace`` guarantees the
destination is either the old content or the complete new content.
"""
from __future__ import annotations

import os
import shutil
from pathlib import Path


def tmp_sibling(dest: Path) -> Path:
    """Temp path next to dest that keeps the real suffix last.

    ``photo.jpg`` -> ``photo.tmp.jpg`` so tools that infer format from the
    extension (PIL, ffmpeg) still work when writing the temp file.
    """
    return dest.with_name(f"{dest.stem}.tmp{dest.suffix}")


def atomic_copy(src: Path, dest: Path) -> None:
    tmp = tmp_sibling(dest)
    try:
        shutil.copy2(src, tmp)
        os.replace(tmp, dest)
    finally:
        if tmp.exists():
            try:
                tmp.unlink()
            except OSError:
                pass


def atomic_write_text(dest: Path, text: str, encoding: str = "utf-8") -> None:
    tmp = tmp_sibling(dest)
    try:
        tmp.write_text(text, encoding=encoding)
        os.replace(tmp, dest)
    finally:
        if tmp.exists():
            try:
                tmp.unlink()
            except OSError:
                pass


def atomic_write_bytes(dest: Path, data: bytes) -> None:
    tmp = tmp_sibling(dest)
    try:
        tmp.write_bytes(data)
        os.replace(tmp, dest)
    finally:
        if tmp.exists():
            try:
                tmp.unlink()
            except OSError:
                pass
