"""Tests for account folder layout and migration."""
import json
import tempfile
from pathlib import Path

from smd.account_layout import (
    AccountPaths,
    migrate_account_layout,
    migrate_flat_accounts_root,
    resolve_account_paths,
    technical_storage_summary,
)


def test_migrate_legacy_layout():
    with tempfile.TemporaryDirectory() as tmp:
        account = Path(tmp) / "Las"
        downloads = account / "downloads"
        staging = downloads / ".staging"
        staging.mkdir(parents=True)
        (staging / "2020-01-01_uid-main.mp4").write_bytes(b"x")

        json_legacy = account / "json"
        json_legacy.mkdir(parents=True)
        (json_legacy / "memories_history.json").write_text("{}", encoding="utf-8")

        (downloads / ".local_checkpoint.json").write_text(
            json.dumps({"version": 3, "completed_stems": [], "skipped_stems": []}),
            encoding="utf-8",
        )
        (downloads / "reports").mkdir()
        (downloads / "reports" / "processing_report.json").write_text("{}", encoding="utf-8")

        paths = AccountPaths.for_account(account)
        paths.ensure_dirs()
        actions = migrate_account_layout(paths)

        assert paths.staging_dir.is_dir()
        assert any(paths.staging_dir.iterdir())
        assert paths.json_path.exists()
        assert paths.checkpoint_path.exists()
        assert (paths.reports_dir / "processing_report.json").exists()
        assert not (downloads / ".staging").exists()
        assert not (account / "json").exists()
        assert actions


def test_resolve_creates_technical_readme():
    with tempfile.TemporaryDirectory() as tmp:
        account = Path(tmp) / "Test"
        paths = resolve_account_paths(account, migrate=True)
        readme = paths.technical_dir / "README.txt"
        assert readme.exists()
        assert "staging" in readme.read_text(encoding="utf-8").lower()


def test_migrate_flat_accounts_root():
    with tempfile.TemporaryDirectory() as tmp:
        base_dir = Path(tmp)
        legacy_account = base_dir / "accounts" / "Las"
        (legacy_account / "downloads").mkdir(parents=True)
        (legacy_account / "downloads" / "photo.jpg").write_bytes(b"x")

        actions = migrate_flat_accounts_root(base_dir)

        assert (base_dir / "Las" / "downloads" / "photo.jpg").exists()
        assert not (base_dir / "accounts").exists()
        assert actions


def test_migrate_flat_accounts_root_skips_existing_target():
    with tempfile.TemporaryDirectory() as tmp:
        base_dir = Path(tmp)
        (base_dir / "accounts" / "Las").mkdir(parents=True)
        (base_dir / "Las").mkdir()
        (base_dir / "Las" / "keep.txt").write_text("keep", encoding="utf-8")

        migrate_flat_accounts_root(base_dir)

        # Pre-existing flat folder is never overwritten.
        assert (base_dir / "Las" / "keep.txt").exists()


def test_migrate_flat_accounts_root_noop_without_legacy_folder():
    with tempfile.TemporaryDirectory() as tmp:
        base_dir = Path(tmp)
        assert migrate_flat_accounts_root(base_dir) == []


def test_technical_storage_summary():
    with tempfile.TemporaryDirectory() as tmp:
        account = Path(tmp) / "Las"
        paths = resolve_account_paths(account, migrate=True)
        (paths.staging_dir / "big.bin").write_bytes(b"x" * 2048)
        rows = technical_storage_summary(paths)
        staging_size = next(size for label, size in rows if label == "staging")
        assert staging_size >= 2048
