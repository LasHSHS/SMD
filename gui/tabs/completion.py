"""Post-run completion summary and duplicate-review mixin."""
from __future__ import annotations

from pathlib import Path

from PyQt5.QtWidgets import QMessageBox

from gui.common import play_happy_tone
from gui.dialogs import DuplicateReviewDialog, SessionSummaryDialog
from gui.workers import (
    CompletionFinalizeWorker,
    DuplicateScanWorker,
    StagingVerifyWorker,
)


class CompletionMixin:
    """Mixin: completion summary, staging verify finalize, duplicate review."""

    def _show_completion_summary(self) -> None:
        """Kick off the post-run summary. The staging integrity check that
        this depends on ffprobes every video, which can take minutes on a
        large library - it now runs on a background thread (see
        StagingVerifyWorker) so the window stays responsive instead of
        looking frozen right after processing finishes."""
        account_name = self._account_name()
        try:
            paths = self._account_paths(account_name)
        except Exception as exc:
            self._log_completion_error("resolve account paths", exc, None)
            if hasattr(self, 'processing_shield'):
                self.processing_shield.hide()
            self._set_keep_awake(False)
            self._show_minimal_completion_message(account_name, None)
            return

        self._completion_account_name = account_name
        self._completion_paths = paths
        self._completion_stats = getattr(
            getattr(self, 'local_export_worker', None), 'run_stats', None
        )
        self._completion_keep_raw = self.save_raw_chk.isChecked()

        if getattr(self, 'keep_staging_chk', None) and self.keep_staging_chk.isChecked():
            # "Keep staging media files" means nothing will be deleted, so
            # there is no point paying for the expensive ffprobe-every-video
            # integrity check either - skip straight to the summary.
            self._finish_completion_summary(None, skipped_by_setting=True)
            return

        if hasattr(self, 'processing_shield'):
            self.processing_shield.set_hint(
                'Double-checking every saved file before showing the summary.\n'
                'Large libraries can take a few minutes.\n'
                'Your files are already saved - this step only verifies them.',
                title='Verifying your files…',
            )
            self.processing_shield.show_over()

        self._staging_verify_worker = StagingVerifyWorker(
            paths.account_dir, paths, self._completion_keep_raw
        )
        self._staging_verify_worker.finished_ok.connect(self._on_staging_verified)
        self._staging_verify_worker.error.connect(self._on_staging_verify_error)
        self._staging_verify_worker.start()

    def _on_staging_verify_error(self, message: str) -> None:
        self._log_completion_error(
            "verify staging", RuntimeError(message), self._completion_paths
        )
        self._finish_completion_summary(None)

    def _on_staging_verified(self, readiness) -> None:
        self._finish_completion_summary(readiness)

    def _finish_completion_summary(self, readiness, skipped_by_setting: bool = False) -> None:
        """Kick off background finalize (staging delete + session report)."""
        paths = self._completion_paths
        stats = self._completion_stats
        keep_raw = self._completion_keep_raw

        if hasattr(self, 'processing_shield'):
            self.processing_shield.set_hint(
                'Preparing your summary.\n'
                'Large libraries can take a minute.\n'
                'Your files are already saved.',
                title='Verifying your files…',
            )
            self.processing_shield.show_over()

        self._stop_worker('completion_finalize_worker')
        self.completion_finalize_worker = CompletionFinalizeWorker(
            paths, stats, keep_raw, readiness, skipped_by_setting
        )
        self.completion_finalize_worker.finished_ok.connect(self._on_completion_finalize_finished)
        self.completion_finalize_worker.error.connect(self._on_completion_finalize_error)
        self.completion_finalize_worker.start()

    def _on_completion_finalize_finished(self, report) -> None:
        account_name = self._completion_account_name
        paths = self._completion_paths
        if hasattr(self, 'processing_shield'):
            self.processing_shield.hide()
        self._set_keep_awake(False)
        try:
            dlg = SessionSummaryDialog(report, paths.library_root, paths.reports_dir, self)
            dlg.exec_()
        except Exception as exc:
            self._log_completion_error("show session summary", exc, paths)
            self._show_minimal_completion_message(account_name, paths)
        QTimer.singleShot(
            0,
            lambda an=account_name, p=paths, r=report: self._after_processing_summary(an, p, r),
        )

    def _on_completion_finalize_error(self, message: str) -> None:
        account_name = self._completion_account_name
        paths = self._completion_paths
        self._log_completion_error("build session summary", RuntimeError(message), paths)
        if hasattr(self, 'processing_shield'):
            self.processing_shield.hide()
        self._set_keep_awake(False)
        self._show_minimal_completion_message(account_name, paths)
        QTimer.singleShot(
            0,
            lambda an=account_name, p=paths, r=None: self._after_processing_summary(an, p, r),
        )

    def _show_minimal_completion_message(self, account_name: str, paths) -> None:
        """Fallback when the rich summary dialog cannot be built."""
        where = ''
        try:
            if paths is not None:
                where = f'\n\nYour memories are saved in:\n{paths.library_root}'
        except Exception:
            pass
        try:
            QMessageBox.information(
                self,
                'Processing complete',
                'Your Snapchat memories were processed successfully.' + where +
                '\n\nUse "Open finished folder" to view them, or "Review duplicates" '
                'to check for repeated files.',
            )
        except Exception:
            pass

    def _log_completion_error(self, stage: str, exc: Exception, paths) -> None:
        """Record a completion-stage error to disk and the run log."""
        import traceback
        tb = traceback.format_exc()
        print(f"Completion error ({stage}): {exc}\n{tb}")
        try:
            if paths is not None:
                paths.logs_dir.mkdir(parents=True, exist_ok=True)
                (paths.logs_dir / 'summary_error.log').write_text(
                    f"Stage: {stage}\n{tb}\n", encoding='utf-8'
                )
        except Exception:
            pass

    def _after_processing_summary(self, account_name: str, paths, report) -> None:
        """Refresh the main window after the session summary dialog closes."""
        try:
            self.show()
            self.raise_()
            self.activateWindow()
            if account_name:
                self.update_download_path_label(account_name)
        except Exception as exc:
            print(f"Post-summary refresh error: {exc}")
        if report and report.duplicate_groups > 0:
            self._open_duplicate_review_if_needed(account_name, paths, report.duplicate_groups)

    def _show_duplicate_review_dialog(self, account_name: str, paths, report) -> None:
        dlg = DuplicateReviewDialog(self, paths, account_name, report, dark=self.dark_mode_enabled)
        dlg.setModal(True)
        dlg.setAttribute(Qt.WA_QuitOnClose, False)
        dlg.exec_()

    def _open_duplicate_review_if_needed(self, account_name: str, paths, duplicate_groups: int) -> None:
        """Open duplicate review after a successful run when duplicates were found."""
        if duplicate_groups <= 0:
            return
        try:
            from smd.duplicates import load_cached_duplicate_report

            report = load_cached_duplicate_report(paths)
            if report and report.duplicate_groups:
                self._show_duplicate_review_dialog(account_name, paths, report)
                return

            self._duplicate_scan_account_name = account_name
            self._duplicate_scan_paths = paths
            self._duplicate_scan_auto_open = True
            self._stop_worker('duplicate_scan_worker')
            self.duplicate_scan_worker = DuplicateScanWorker(paths)
            self.duplicate_scan_worker.finished.connect(self.on_duplicate_scan_finished)
            self.duplicate_scan_worker.error.connect(self._on_post_run_duplicate_scan_error)
            self.duplicate_scan_worker.start()
        except Exception as exc:
            print(f"Duplicate review error: {exc}")
            QMessageBox.warning(
                self,
                'Review duplicates',
                'Could not open duplicate review.\n\n'
                'Your finished photos and videos are already saved — this step is optional.',
            )

    def _on_post_run_duplicate_scan_error(self, message: str) -> None:
        self._duplicate_scan_auto_open = False
        print(f"Duplicate review error: {message}")

    def review_duplicates(self):
        if self.download_running:
            QMessageBox.information(
                self,
                'Review duplicates',
                'Wait until the current download/processing job finishes.',
            )
            return
        account_name = self._account_name()
        if not account_name:
            QMessageBox.information(self, 'Duplicates', 'Enter an account name first.')
            return
        paths = self._account_paths(account_name)

        # Processing already hashed merged/ once and saved the result to
        # technical/reports/duplicates_report.json. Trust that cache instead
        # of re-hashing everything on every click - it's kept in sync
        # whenever duplicates are deleted, and a full re-process (which
        # everyone runs after fixing a real bug) always regenerates it fresh.
        from smd.duplicates import load_cached_duplicate_report

        self._duplicate_scan_account_name = account_name
        self._duplicate_scan_paths = paths

        cached = load_cached_duplicate_report(paths)
        if cached is not None:
            self.on_duplicate_scan_finished(cached)
            return

        self.review_duplicates_btn.setEnabled(False)
        self._apply_status(self.status_label, 'Checking for duplicate files…', 'info')
        # No cache yet (first check on this account) - hashing every file in
        # merged/ can take a while on large libraries, so run it off the UI
        # thread rather than blocking the window.
        self._stop_worker('duplicate_scan_worker')
        self.duplicate_scan_worker = DuplicateScanWorker(paths)
        self.duplicate_scan_worker.progress.connect(self.on_duplicate_scan_progress)
        self.duplicate_scan_worker.finished.connect(self.on_duplicate_scan_finished)
        self.duplicate_scan_worker.error.connect(self.on_duplicate_scan_error)
        self.duplicate_scan_worker.start()

    def on_duplicate_scan_progress(self, message: str) -> None:
        self._apply_status(self.status_label, message, 'info')

    def on_duplicate_scan_finished(self, report) -> None:
        auto_open = getattr(self, '_duplicate_scan_auto_open', False)
        self._duplicate_scan_auto_open = False
        self._refresh_after_processing_actions()
        account_name = getattr(self, '_duplicate_scan_account_name', None)
        paths = getattr(self, '_duplicate_scan_paths', None)
        if not report.duplicate_groups:
            if not auto_open:
                self._apply_status(self.status_label, 'No duplicates found.', 'ok')
                QMessageBox.information(
                    self,
                    'Duplicates',
                    f'Scanned {report.merged_scanned} files - no byte-identical duplicates found.',
                )
            return
        self._apply_status(self.status_label, 'Duplicates found - opening review.', 'info')
        if account_name and paths is not None:
            self._show_duplicate_review_dialog(account_name, paths, report)

    def on_duplicate_scan_error(self, message: str) -> None:
        self._refresh_after_processing_actions()
        self._apply_status(self.status_label, 'Duplicate check failed.', 'err')
        print(f"Duplicate review error: {message}")
        QMessageBox.warning(
            self,
            'Review duplicates',
            'Could not open duplicate review.\n\n'
            'Your finished files are not affected — this step is optional.',
        )
