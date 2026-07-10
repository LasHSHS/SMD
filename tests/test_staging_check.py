"""Tests for staging deletion readiness checks."""
import json
import tempfile
from pathlib import Path

from smd.account_layout import AccountPaths
from smd.local_pipeline import _save_checkpoint, CHECKPOINT_VERSION
from smd.staging_check import (
    check_staging_readiness,
    delete_staging_folder,
)

# Minimal bytes that pass magic-byte validation as an MP4.
FAKE_MP4 = b"\x00\x00\x00\x18ftypmp42" + b"\x00" * 1016


def _setup_complete_account(tmp: Path) -> AccountPaths:
    paths = AccountPaths.for_account(tmp / "Las")
    paths.ensure_dirs()

    stem = "2020-12-14_0610d8a6-fbce-c5c9-35c2-550484a732a0"
    main_name = f"{stem}-main.mp4"
    (paths.staging_dir / main_name).write_bytes(FAKE_MP4)

    (paths.json_path.parent).mkdir(parents=True, exist_ok=True)
    out_name = "2020-12-14_19-44-01.mp4"
    (paths.merged_dir / out_name).write_bytes(FAKE_MP4)
    (paths.raw_dir / out_name).write_bytes(FAKE_MP4)

    _save_checkpoint(paths.checkpoint_path, {stem}, set())
    return paths


def test_unsafe_when_merged_missing():
    with tempfile.TemporaryDirectory() as tmp:
        paths = AccountPaths.for_account(Path(tmp) / "Las")
        paths.ensure_dirs()
        stem = "2020-12-14_0610d8a6-fbce-c5c9-35c2-550484a732a0"
        (paths.staging_dir / f"{stem}-main.mp4").write_bytes(b"x" * 1024)
        _save_checkpoint(paths.checkpoint_path, {stem}, set())

        report = check_staging_readiness(paths.account_dir, layout=paths)
        assert not report.safe_to_delete
        assert report.missing_merged == [stem]


def test_safe_when_outputs_and_checkpoint_complete():
    with tempfile.TemporaryDirectory() as tmp:
        paths = _setup_complete_account(Path(tmp))
        # Without valid JSON, planned name uses uid fallback - fix outputs
        stem = "2020-12-14_0610d8a6-fbce-c5c9-35c2-550484a732a0"
        out_name = "2020-12-14_0610d8a6.mp4"
        (paths.merged_dir / out_name).write_bytes(FAKE_MP4)
        (paths.raw_dir / out_name).write_bytes(FAKE_MP4)

        report = check_staging_readiness(
            paths.account_dir, layout=paths, deep_video_check=False
        )
        assert report.outputs_verified == 1
        assert not report.pending_checkpoint
        # missing json is warning only if outputs ok
        assert report.safe_to_delete


def test_delete_refuses_when_unsafe():
    with tempfile.TemporaryDirectory() as tmp:
        paths = AccountPaths.for_account(Path(tmp) / "Las")
        paths.ensure_dirs()
        (paths.staging_dir / "a-main.mp4").write_bytes(b"x" * 100)

        ok, msg = delete_staging_folder(paths.account_dir, layout=paths)
        assert not ok
        assert paths.staging_dir.exists()


def test_delete_succeeds_when_safe():
    with tempfile.TemporaryDirectory() as tmp:
        paths = _setup_complete_account(Path(tmp))
        stem = "2020-12-14_0610d8a6-fbce-c5c9-35c2-550484a732a0"
        out_name = "2020-12-14_0610d8a6.mp4"
        (paths.merged_dir / out_name).write_bytes(FAKE_MP4)
        (paths.raw_dir / out_name).write_bytes(FAKE_MP4)

        report = check_staging_readiness(
            paths.account_dir, layout=paths, deep_video_check=False
        )
        assert report.safe_to_delete
        ok, msg = delete_staging_folder(paths.account_dir, report=report, layout=paths)
        assert ok
        assert not any(paths.staging_dir.iterdir())


def test_unsafe_when_quarantine_nonempty():
    with tempfile.TemporaryDirectory() as tmp:
        paths = _setup_complete_account(Path(tmp))
        out_name = "2020-12-14_0610d8a6.mp4"
        (paths.merged_dir / out_name).write_bytes(FAKE_MP4)
        (paths.raw_dir / out_name).write_bytes(FAKE_MP4)
        paths.quarantine_dir.mkdir(parents=True, exist_ok=True)
        (paths.quarantine_dir / "broken.mp4").write_bytes(b"x" * 600)

        report = check_staging_readiness(
            paths.account_dir, layout=paths, deep_video_check=False
        )
        assert not report.safe_to_delete
        assert any(i.code == "quarantine_nonempty" for i in report.issues)


def test_unsafe_when_video_stream_corrupt(monkeypatch):
    with tempfile.TemporaryDirectory() as tmp:
        paths = _setup_complete_account(Path(tmp))
        out_name = "2020-12-14_0610d8a6.mp4"
        (paths.merged_dir / out_name).write_bytes(FAKE_MP4)
        (paths.raw_dir / out_name).write_bytes(FAKE_MP4)

        import smd.procutil as procutil

        monkeypatch.setattr(procutil, "ffprobe_stream_ok", lambda p, **kw: False)
        report = check_staging_readiness(paths.account_dir, layout=paths)
        assert not report.safe_to_delete
        assert any(i.code == "corrupt_video_stream" for i in report.issues)
