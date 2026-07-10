"""Tests for privacy-safe path display in About / diagnostics."""
import os
from pathlib import Path

from smd.runtime import app_root, display_path, sanitize_user_text


def _profile_name() -> str:
    return Path.home().name.lower()


def test_display_path_masks_home_and_install_segments():
    root = app_root().resolve()
    tool = root / "tools" / "ffmpeg" / "ffmpeg.exe"
    shown = display_path(tool)
    assert _profile_name() not in shown.lower()
    assert shown.startswith("{install}")
    assert shown.endswith("ffmpeg.exe")


def test_display_path_install_root_label():
    assert display_path(app_root()) == "{install}"


def test_sanitize_user_text_redacts_home_path():
    home = str(Path.home())
    if not home:
        return
    text = f"Python {home}{os.sep}python.exe"
    cleaned = sanitize_user_text(text)
    assert home not in cleaned
    assert _profile_name() not in cleaned.lower()
