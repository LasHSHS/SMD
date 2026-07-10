"""Tests for account folder layout and migration."""
import json
import tempfile
from pathlib import Path

from smd.account_layout import (
    AccountPaths,
    migrate_account_layout,
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


def test_technical_storage_summary():
    with tempfile.TemporaryDirectory() as tmp:
        account = Path(tmp) / "Las"
        paths = resolve_account_paths(account, migrate=True)
        (paths.staging_dir / "big.bin").write_bytes(b"x" * 2048)
        rows = technical_storage_summary(paths)
        staging_size = next(size for label, size in rows if label == "staging")
        assert staging_size >= 2048
