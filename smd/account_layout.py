"""Account folder layout: user media vs technical/developer data."""
from __future__ import annotations

import os
import shutil
from dataclasses import dataclass
from pathlib import Path

INTERNAL_APP_DIRNAME = "SnapchatMemoriesDownloader"

TECHNICAL_DIRNAME = "technical"
DOWNLOADS_DIRNAME = "downloads"
README_NAME = "README.txt"

# Legacy locations (pre-restructure)
LEGACY_STAGING = ".staging"
LEGACY_CHECKPOINT = ".local_checkpoint.json"


@dataclass(frozen=True)
class AccountPaths:
    account_dir: Path
    downloads_dir: Path
    merged_dir: Path
    raw_dir: Path
    technical_dir: Path
    staging_dir: Path
    json_dir: Path
    json_path: Path
    reports_dir: Path
    checkpoint_path: Path
    quarantine_dir: Path
    logs_dir: Path
    debug_dir: Path

    @property
    def library_root(self) -> Path:
        """User-facing library folder (Desktop/<account> or parent of merged/)."""
        if self.merged_dir.name == "merged":
            return self.merged_dir.parent
        return self.merged_dir

    @classmethod
    def internal_accounts_root(cls) -> Path:
        local = Path(os.environ.get("LOCALAPPDATA", Path.home() / "AppData" / "Local"))
        return local / INTERNAL_APP_DIRNAME / "accounts"

    @classmethod
    def user_desktop_dir(cls, account_name: str) -> Path:
        return Path.home() / "Desktop" / account_name

    @classmethod
    def for_user(cls, account_name: str, *, keep_raw: bool = False) -> AccountPaths:
        """
        Simple layout: photos/videos on Desktop/<account>/.
        Checkpoints, staging, JSON live under %LOCALAPPDATA% only.
        """
        internal = cls.internal_accounts_root() / account_name
        desktop = cls.user_desktop_dir(account_name)
        technical = internal / TECHNICAL_DIRNAME
        if keep_raw:
            merged = desktop / "merged"
            raw = desktop / "raw"
        else:
            merged = desktop
            raw = technical / "raw_unused"
        return cls(
            account_dir=internal,
            downloads_dir=desktop,
            merged_dir=merged,
            raw_dir=raw,
            technical_dir=technical,
            staging_dir=technical / "staging",
            json_dir=technical / "json",
            json_path=technical / "json" / "memories_history.json",
            reports_dir=technical / "reports",
            checkpoint_path=technical / "checkpoint" / "local_checkpoint.json",
            quarantine_dir=technical / "quarantine",
            logs_dir=technical / "logs",
            debug_dir=technical / "debug",
        )

    def ensure_user_dirs(self, *, keep_raw: bool = False) -> None:
        """Create folders for simple user layout."""
        self.merged_dir.mkdir(parents=True, exist_ok=True)
        if keep_raw:
            self.raw_dir.mkdir(parents=True, exist_ok=True)
        for d in (
            self.technical_dir,
            self.staging_dir,
            self.json_dir,
            self.reports_dir,
            self.checkpoint_path.parent,
            self.quarantine_dir,
            self.logs_dir,
            self.debug_dir,
        ):
            d.mkdir(parents=True, exist_ok=True)

    @classmethod
    def for_account(cls, account_dir: Path) -> AccountPaths:
        account_dir = Path(account_dir)
        technical = account_dir / TECHNICAL_DIRNAME
        downloads = account_dir / DOWNLOADS_DIRNAME
        return cls(
            account_dir=account_dir,
            downloads_dir=downloads,
            merged_dir=downloads / "merged",
            raw_dir=downloads / "raw",
            technical_dir=technical,
            staging_dir=technical / "staging",
            json_dir=technical / "json",
            json_path=technical / "json" / "memories_history.json",
            reports_dir=technical / "reports",
            checkpoint_path=technical / "checkpoint" / "local_checkpoint.json",
            quarantine_dir=technical / "quarantine",
            logs_dir=technical / "logs",
            debug_dir=technical / "debug",
        )

    def ensure_dirs(self) -> None:
        for d in (
            self.downloads_dir,
            self.merged_dir,
            self.raw_dir,
            self.technical_dir,
            self.staging_dir,
            self.json_dir,
            self.reports_dir,
            self.checkpoint_path.parent,
            self.quarantine_dir,
            self.logs_dir,
            self.debug_dir,
        ):
            d.mkdir(parents=True, exist_ok=True)
        readme = self.technical_dir / README_NAME
        if not readme.exists():
            readme.write_text(_technical_readme_text(), encoding="utf-8")


def normalize_account_dir(path: Path) -> Path:
    """Accept account dir or legacy downloads/ path."""
    path = Path(path)
    if path.name == DOWNLOADS_DIRNAME:
        return path.parent
    return path


def resolve_account_paths(
    account_dir: Path,
    *,
    migrate: bool = True,
    create: bool = True,
) -> AccountPaths:
    """Resolve layout paths. Only creates on-disk folders when create=True."""
    account_dir = normalize_account_dir(account_dir)
    paths = AccountPaths.for_account(account_dir)
    if create:
        paths.ensure_dirs()
        if migrate:
            migrate_account_layout(paths)
    elif migrate and account_dir.exists():
        migrate_account_layout(paths)
    return paths


def migrate_flat_library_to_subfolders(desktop_account: Path) -> bool:
    """
    Move loose files in Desktop/<account>/ into merged/ when user later enables raw copies.
    Returns True if files were moved.
    """
    desktop_account = Path(desktop_account)
    merged_dir = desktop_account / "merged"
    if merged_dir.is_dir() and any(merged_dir.iterdir()):
        return False
    loose = [p for p in desktop_account.iterdir() if p.is_file()]
    if not loose:
        return False
    merged_dir.mkdir(parents=True, exist_ok=True)
    for path in loose:
        target = merged_dir / path.name
        if target.exists():
            continue
        shutil.move(str(path), str(target))
    return True


def migrate_account_layout(paths: AccountPaths) -> list[str]:
    """Move legacy hidden/ scattered files into technical/. Returns actions taken."""
    actions: list[str] = []
    downloads = paths.downloads_dir
    account = paths.account_dir

    moves: list[tuple[Path, Path, str]] = [
        (downloads / LEGACY_STAGING, paths.staging_dir, "staging"),
        (downloads / LEGACY_CHECKPOINT, paths.checkpoint_path, "checkpoint"),
        (downloads / "reports", paths.reports_dir, "reports"),
        (downloads / "quarantine", paths.quarantine_dir, "quarantine"),
        (downloads / "processing_error.log", paths.logs_dir / "processing_error.log", "log"),
        (account / "json", paths.json_dir, "json"),
        (account / "debug", paths.debug_dir, "debug"),
    ]

    for src, dest, label in moves:
        if not src.exists():
            continue
        if src.is_dir():
            if dest.exists() and any(dest.iterdir()):
                # Merge contents into destination
                for child in src.iterdir():
                    target = dest / child.name
                    if target.exists():
                        continue
                    shutil.move(str(child), str(target))
                    actions.append(f"Moved {label}/{child.name}")
                try:
                    src.rmdir()
                except OSError:
                    pass
            else:
                dest.parent.mkdir(parents=True, exist_ok=True)
                if dest.exists():
                    shutil.rmtree(dest, ignore_errors=True)
                shutil.move(str(src), str(dest))
                actions.append(f"Moved {label}/")
        else:
            dest.parent.mkdir(parents=True, exist_ok=True)
            if not dest.exists():
                shutil.move(str(src), str(dest))
                actions.append(f"Moved {label}")

    return actions


def folder_size_bytes(path: Path) -> int:
  total = 0
  if not path.exists():
      return 0
  if path.is_file():
      try:
          return path.stat().st_size
      except OSError:
          return 0
  for child in path.rglob("*"):
      if child.is_file():
          try:
              total += child.stat().st_size
          except OSError:
              pass
  return total


from smd.media_types import format_bytes  # single shared implementation  # noqa: E402


def technical_storage_summary(paths: AccountPaths) -> list[tuple[str, int]]:
    """Named technical subfolders with byte sizes (for UI)."""
    rows: list[tuple[str, int]] = []
    for label, folder in (
        ("staging", paths.staging_dir),
        ("json", paths.json_dir),
        ("reports", paths.reports_dir),
        ("checkpoint", paths.checkpoint_path.parent),
        ("quarantine", paths.quarantine_dir),
        ("logs", paths.logs_dir),
        ("debug", paths.debug_dir),
    ):
        rows.append((label, folder_size_bytes(folder)))
    return rows


def _technical_readme_text() -> str:
    return """Snapchat Memories Downloader - technical folder
================================================

This folder holds working data used by the program. It is NOT hidden on purpose:
staging especially can use a lot of disk space (often similar to your ZIP export).

Subfolders
----------
staging/     Extracted media from ZIP parts (main + overlay pairs). Safe to delete
             ONLY after the in-app "Verify staging" check passes (Download tab).
             Deleting early means re-extracting from ZIPs on the next run.

json/        memories_history.json - dates, GPS, media types from Snapchat.

reports/     processing_report.json, filename_collisions.json,
             staging_readiness.json - run statistics and verification.

checkpoint/  Resume state (local_checkpoint.json) - lets interrupted runs continue.

quarantine/  Broken or unusable files isolated during processing.

logs/        Error logs from failed runs, plus a full run_activity log per run.

debug/       Processing diagnostics and logs

Your photos and videos
----------------------
Open: ../downloads/merged/  (with overlays)
      ../downloads/raw/     (without overlays, only if "Also save without filters" was on)

Byte-identical duplicates are NOT moved to a separate folder. Use "Review
duplicates" in the app to see them side by side (with thumbnails/duration for
video) and choose which copy to keep; anything not kept is permanently
deleted from both merged/ and raw/, and the deletion is recorded in
reports/duplicates_deleted_report_*.json.
"""
