"""Runtime paths for portable / PyInstaller all-in-one SMD builds."""
from __future__ import annotations

import os
import sys
from pathlib import Path

_INSTALL_LABEL = "{install}"


def is_frozen() -> bool:
    return bool(getattr(sys, "frozen", False))


def app_root() -> Path:
    """Install folder (release) or project root (development)."""
    if is_frozen():
        return Path(sys.executable).resolve().parent
    return Path(__file__).resolve().parent.parent


def internal_root() -> Path:
    """PyInstaller _internal folder when present."""
    meipass = getattr(sys, "_MEIPASS", None)
    if meipass:
        return Path(meipass)
    return app_root()


def bundled_dir(*parts: str) -> Path | None:
    """Find first existing bundled resource directory under known layout roots."""
    rel = Path(*parts)
    for base in (app_root(), internal_root()):
        candidate = base / rel
        if candidate.is_dir():
            return candidate
    return None


def _path_sep() -> str:
    return "\\" if os.name == "nt" else "/"


def _profile_prefix() -> str:
    return "%USERPROFILE%" if os.name == "nt" else "~"


def _format_relative(base: Path, resolved: Path, *, label: str) -> str:
    rel = resolved.relative_to(base)
    return label + _path_sep() + rel.as_posix().replace("/", _path_sep())


def display_path(path: str | Path | None) -> str:
    """Format a filesystem path for UI without exposing the Windows username or home folder."""
    if path is None or path == "":
        return "Not found"
    try:
        resolved = Path(path).resolve()
    except OSError:
        return str(path)

    root = app_root().resolve()
    try:
        if resolved == root:
            return _INSTALL_LABEL
        if resolved.is_relative_to(root):
            return _format_relative(root, resolved, label=_INSTALL_LABEL)
    except ValueError:
        pass

    home_bases: list[Path] = []
    try:
        home_bases.append(Path.home().resolve())
    except OSError:
        pass
    profile = os.environ.get("USERPROFILE")
    if profile:
        try:
            home_bases.append(Path(profile).resolve())
        except OSError:
            pass

    prefix = _profile_prefix()
    for home_base in home_bases:
        try:
            if resolved == home_base:
                return prefix
            if resolved.is_relative_to(home_base):
                return _format_relative(home_base, resolved, label=prefix)
        except ValueError:
            continue

    return str(resolved)


def sanitize_user_text(text: str) -> str:
    """Redact user-profile path segments embedded in free-form diagnostic text."""
    if not text:
        return text
    out = text
    prefix = _profile_prefix()
    candidates: list[str] = []
    if profile := os.environ.get("USERPROFILE"):
        candidates.append(profile)
    try:
        candidates.append(str(Path.home().resolve()))
    except OSError:
        pass
    for candidate in candidates:
        if candidate and candidate in out:
            out = out.replace(candidate, prefix)
    return out
