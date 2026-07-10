"""Regression tests for the post-run session summary HTML.

summary_html() is the last step before the completion popup; if it raises,
the user sees no summary at all. A stray bare-name reference once silently
broke this, so exercise every conditional branch here.
"""
from smd.session_report import SessionReport


def _report(**overrides) -> SessionReport:
    base = dict(
        generated_at="2026-04-17T09:14:49+00:00",
        account_name="Mary",
        success=True,
        steps_completed=["Detected export", "Merged overlays"],
        merged_count=10,
        raw_count=10,
        overlays_merged=4,
        metadata_applied=10,
        staging_files=10,
        staging_bytes=1024,
        merged_bytes=2048,
        safe_to_delete_staging=True,
    )
    base.update(overrides)
    return SessionReport(**base)


def test_summary_html_renders_when_staging_cleaned():
    html = _report(staging_deleted=True, staging_freed="1.0 MB").summary_html()
    assert "Processing summary" in html
    assert "1.0 MB freed" in html


def test_summary_html_renders_when_staging_kept():
    html = _report(staging_deleted=False, staging_freed="").summary_html()
    assert "Staging check passed" in html


def test_summary_html_with_duplicates_and_notes():
    html = _report(
        duplicate_groups=3,
        webp_outputs=2,
        corrupt_images_found=1,
        corrupt_image_names=["bad.jpg"],
        notes=["1 item(s) failed."],
        safe_to_delete_staging=False,
    ).summary_html()
    assert "Duplicate content groups" in html
    assert "run again with the same name" in html
    assert "Notes" in html


def test_summary_html_failure_state():
    html = _report(success=False, failed=2).summary_html()
    assert "Finished with issues" in html
