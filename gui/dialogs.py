"""Modal dialogs for the SMD desktop GUI."""
from __future__ import annotations

import json
from pathlib import Path

from PyQt5.QtCore import Qt, QUrl
from PyQt5.QtGui import QDesktopServices, QPixmap
from PyQt5.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QPushButton, QLabel, QScrollArea,
    QWidget, QButtonGroup, QRadioButton, QMessageBox, QFrame, QSizePolicy,
    QTextBrowser, QGroupBox,
)

from gui.widgets import FittedPixmapLabel, FlowLayout
from gui.workers import DuplicatePreviewWorker, _qpixmap_from_pil


class DuplicateCompareDialog(QDialog):
    """Side-by-side enlarged preview for duplicate files in one group."""

    def __init__(self, parent, files: list[tuple[str, Path]], *, dark: bool):
        super().__init__(parent)
        self._dark = dark
        self.setWindowTitle('Compare duplicates')
        self.setMinimumSize(960, 620)
        self.setObjectName('appDialog')

        root = QVBoxLayout(self)
        root.setContentsMargins(16, 16, 16, 16)
        root.setSpacing(12)

        hint = QLabel(
            'Each preview scales to fit its panel. Files are byte-identical.'
        )
        hint.setWordWrap(True)
        root.addWidget(hint)

        outer_scroll = QScrollArea()
        outer_scroll.setWidgetResizable(True)
        outer_scroll.setFrameShape(QScrollArea.NoFrame)
        # Only needed when there are many columns; each image itself is
        # fitted so individual panels never force a horizontal scrollbar.
        outer_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAsNeeded)
        outer_scroll.setVerticalScrollBarPolicy(Qt.ScrollBarAlwaysOff)

        row_host = QWidget()
        row_host.setObjectName('dialogBody')
        row_lay = QHBoxLayout(row_host)
        row_lay.setSpacing(16)
        row_lay.setContentsMargins(0, 0, 0, 0)

        self._preview_targets: dict[str, tuple[QVBoxLayout, Path]] = {}
        for name, path in files:
            col = QFrame()
            col.setObjectName('contentPanel')
            from smd.theme import enable_styled_surface

            enable_styled_surface(col)
            col.setMinimumWidth(280)
            col_lay = QVBoxLayout(col)
            col_lay.setSpacing(8)
            col_lay.setContentsMargins(12, 12, 12, 12)

            title = QLabel(name)
            title.setWordWrap(True)
            title.setProperty('class', 'sectionHeader')
            col_lay.addWidget(title)

            # No nested scroll area: FittedPixmapLabel fills this slot and
            # scales to whatever space the column has, so zoomed-in crops
            # and horizontal scrollbars cannot appear.
            preview_host = QWidget()
            preview_host.setMinimumHeight(360)
            preview_host.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
            preview_lay = QVBoxLayout(preview_host)
            preview_lay.setContentsMargins(0, 0, 0, 0)
            preview_lay.setAlignment(Qt.AlignCenter)

            placeholder = QLabel('Loading preview…')
            placeholder.setAlignment(Qt.AlignCenter)
            placeholder.setWordWrap(True)
            preview_lay.addWidget(placeholder)
            self._preview_targets[str(path)] = (preview_lay, path)

            col_lay.addWidget(preview_host, 1)
            row_lay.addWidget(col, 1)

        outer_scroll.setWidget(row_host)
        root.addWidget(outer_scroll, 1)

        close_btn = QPushButton('Close')
        close_btn.setObjectName('toolbarBtn')
        close_btn.clicked.connect(self.accept)
        btn_row = QHBoxLayout()
        btn_row.addStretch(1)
        btn_row.addWidget(close_btn)
        root.addLayout(btn_row)

        from smd.theme import apply_scroll_area_theme, enable_styled_surface, paint_widget_surface

        enable_styled_surface(self)
        paint_widget_surface(self, dark=dark, role='bg')
        apply_scroll_area_theme(outer_scroll, dark=dark)
        enable_styled_surface(row_host)
        paint_widget_surface(row_host, dark=dark, role='bg')
        self._start_compare_preview_loader()

    def _start_compare_preview_loader(self) -> None:
        if not self._preview_targets:
            return
        # Load a high-res source; FittedPixmapLabel scales it down to the
        # panel at display time so quality stays good without overflowing.
        jobs = [(Path(path_key), 1280) for path_key in self._preview_targets]
        self._preview_worker = DuplicatePreviewWorker(jobs)
        self._preview_worker.preview_ready.connect(self._on_compare_preview_ready)
        self._preview_worker.start()

    def _on_compare_preview_ready(self, path_key: str, pil_img, caption: str) -> None:
        entry = self._preview_targets.get(path_key)
        if not entry:
            return
        preview_lay, path = entry
        while preview_lay.count():
            item = preview_lay.takeAt(0)
            widget = item.widget()
            if widget is not None:
                widget.deleteLater()

        if pil_img is not None:
            pixmap = _qpixmap_from_pil(pil_img)
            if pixmap is not None and not pixmap.isNull():
                img_label = FittedPixmapLabel(pixmap)
                preview_lay.addWidget(img_label, 1)
                return

        if path.suffix.lower() in ('.mp4', '.mov', '.m4v', '.mkv', '.avi'):
            video_note = QLabel(
                f"Video preview unavailable.\n{caption or 'Unknown size'}\n"
                "Open with your default player to inspect."
            )
            video_note.setAlignment(Qt.AlignCenter)
            video_note.setWordWrap(True)
            preview_lay.addWidget(video_note)
            open_btn = QPushButton('Play video')
            open_btn.setObjectName('toolbarBtn')
            open_btn.clicked.connect(
                lambda _checked=False, p=path: QDesktopServices.openUrl(QUrl.fromLocalFile(str(p)))
            )
            preview_lay.addWidget(open_btn, alignment=Qt.AlignCenter)
        else:
            missing = QLabel('Preview unavailable for this file.')
            missing.setAlignment(Qt.AlignCenter)
            missing.setWordWrap(True)
            preview_lay.addWidget(missing)


class SessionSummaryDialog(QDialog):
    """Post-run summary shown after bundled export processing."""

    def __init__(self, report, merged_dir, reports_dir, parent=None):
        super().__init__(parent)
        dark = bool(getattr(parent, 'dark_mode_enabled', False))
        self.setWindowTitle('Processing complete')
        self.setMinimumSize(640, 520)
        self.setObjectName('appDialog')

        lay = QVBoxLayout(self)
        lay.setContentsMargins(16, 16, 16, 16)
        lay.setSpacing(12)

        browser = QTextBrowser()
        browser.setObjectName('docReader')
        browser.setHtml(report.summary_html())
        lay.addWidget(browser, 1)

        row = QHBoxLayout()
        open_btn = QPushButton('Open finished folder')
        open_btn.setObjectName('accentBtn')
        open_btn.clicked.connect(
            lambda: QDesktopServices.openUrl(QUrl.fromLocalFile(str(merged_dir)))
        )
        close_btn = QPushButton('Close')
        close_btn.setObjectName('toolbarBtn')
        close_btn.clicked.connect(self.accept)
        row.addWidget(open_btn)
        row.addStretch(1)
        row.addWidget(close_btn)
        lay.addLayout(row)

        from smd.theme import apply_doc_browser_theme, enable_styled_surface, paint_widget_surface

        enable_styled_surface(self)
        paint_widget_surface(self, dark=dark, role='bg')
        apply_doc_browser_theme(browser, dark=dark)
        self.setModal(True)
        self.setAttribute(Qt.WA_QuitOnClose, False)


class DuplicateReviewDialog(QDialog):
    """Pick one keeper per byte-identical group in merged/."""

    def __init__(self, parent, paths, account_name: str, report, *, dark: bool):
        super().__init__(parent)
        self.paths = paths
        self.account_name = account_name
        self.report = report
        self._dark = dark
        self._group_ui: list[tuple[str, list, QButtonGroup]] = []
        self._preview_targets: dict[str, tuple[QPushButton, QLabel]] = {}

        self.setWindowTitle('Review duplicates - choose keepers')
        self.setMinimumWidth(960)
        self.setMinimumHeight(720)
        self.setObjectName('appDialog')

        root = QVBoxLayout(self)
        root.setSpacing(12)
        root.setContentsMargins(16, 16, 16, 16)

        intro = QLabel(
            'Some files in your library are byte-for-byte identical. '
            'Tick the copy (or copies) you want to keep in each group - use "Keep both" '
            'to keep all of them. When you apply, the copies you did not tick are '
            'permanently deleted from both your merged and raw folders. This cannot be undone.'
        )
        intro.setWordWrap(True)
        root.addWidget(intro)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QScrollArea.NoFrame)
        # Cards use a wrapping FlowLayout (below), so this view only ever
        # needs to scroll vertically - never horizontally.
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        inner = QWidget()
        inner.setObjectName('dialogBody')
        inner_layout = QVBoxLayout(inner)
        inner_layout.setSpacing(12)
        inner_layout.setContentsMargins(0, 0, 0, 0)
        scroll.setWidget(inner)
        root.addWidget(scroll, 1)

        groups: dict[str, list] = {}
        for e in report.entries:
            groups.setdefault(e.sha256, []).append(e)
        group_items = sorted(groups.items(), key=lambda kv: kv[0].lower())

        for sha_prefix, entries in group_items:
            entries_sorted = sorted(entries, key=lambda x: x.filename.lower())
            default_keeper = entries_sorted[0].filename if entries_sorted else ''
            file_paths = [(e.filename, self.paths.merged_dir / e.filename) for e in entries_sorted]

            box = QGroupBox(f'Duplicate group {sha_prefix} ({len(entries_sorted)} files)')
            box_layout = QVBoxLayout(box)
            box_layout.setSpacing(10)
            box_layout.setContentsMargins(10, 10, 10, 10)

            btn_group = QButtonGroup(box)
            btn_group.setExclusive(False)

            # FlowLayout wraps cards onto additional rows instead of forcing
            # the group (and thus the whole dialog) to grow wider than the
            # available space - so groups with several duplicates never
            # require a horizontal scrollbar.
            cards_row = FlowLayout(spacing=12)
            for e in entries_sorted:
                media_path = self.paths.merged_dir / e.filename
                cards_row.addWidget(
                    self._build_duplicate_card(
                        sha_prefix,
                        e.filename,
                        media_path,
                        btn_group,
                        checked=(e.filename == default_keeper),
                        compare_files=file_paths,
                    )
                )
            box_layout.addLayout(cards_row)

            compare_btn = QPushButton('Compare side by side')
            compare_btn.setObjectName('toolbarBtn')
            compare_btn.clicked.connect(
                lambda _checked=False, files=file_paths: self._open_compare(files)
            )
            keep_both_btn = QPushButton('Keep both')
            keep_both_btn.setObjectName('toolbarBtn')
            keep_both_btn.setToolTip('Keep every file in this group (nothing in it will be deleted)')
            keep_both_btn.clicked.connect(
                lambda _checked=False, prefix=sha_prefix, group=btn_group: self._on_keep_both(
                    prefix, group
                )
            )
            action_row = QHBoxLayout()
            action_row.addWidget(compare_btn)
            action_row.addWidget(keep_both_btn)
            action_row.addStretch(1)
            box_layout.addLayout(action_row)

            inner_layout.addWidget(box)
            self._group_ui.append((sha_prefix, entries_sorted, btn_group))

        buttons_row = QHBoxLayout()
        cancel_btn = QPushButton('Cancel')
        cancel_btn.setObjectName('toolbarBtn')
        apply_btn = QPushButton('Delete unselected duplicates')
        apply_btn.setObjectName('accentBtn')
        buttons_row.addWidget(cancel_btn)
        buttons_row.addStretch(1)
        buttons_row.addWidget(apply_btn)
        root.addLayout(buttons_row)

        apply_btn.clicked.connect(self._on_apply_clicked)
        cancel_btn.clicked.connect(self.reject)
        self._apply_theme(scroll, inner)
        self._start_preview_loader()

    def _start_preview_loader(self) -> None:
        if not self._preview_targets:
            return
        jobs = [(Path(path_key), 148) for path_key in self._preview_targets]
        self._preview_worker = DuplicatePreviewWorker(jobs)
        self._preview_worker.preview_ready.connect(self._on_preview_ready)
        self._preview_worker.start()

    def _on_preview_ready(self, path_key: str, pil_img, caption: str) -> None:
        widgets = self._preview_targets.get(path_key)
        if not widgets:
            return
        thumb_btn, info_lbl = widgets
        if pil_img is not None:
            pixmap = _qpixmap_from_pil(pil_img)
            if pixmap is not None and not pixmap.isNull():
                thumb_btn.setIcon(QIcon(pixmap))
                thumb_btn.setIconSize(QSize(148, 148))
                thumb_btn.setText('')
            else:
                thumb_btn.setText('No preview')
        else:
            thumb_btn.setText('No preview')
        if caption:
            info_lbl.setText(caption)

    def _build_duplicate_card(
        self,
        sha_prefix: str,
        filename: str,
        media_path: Path,
        btn_group: QButtonGroup,
        *,
        checked: bool,
        compare_files: list[tuple[str, Path]],
    ) -> QFrame:
        from smd.theme import enable_styled_surface

        card = QFrame()
        card.setObjectName('contentPanel')
        enable_styled_surface(card)
        lay = QVBoxLayout(card)
        lay.setSpacing(8)
        lay.setContentsMargins(10, 10, 10, 10)

        thumb_btn = QPushButton()
        thumb_btn.setObjectName('dupThumbBtn')
        thumb_btn.setCursor(Qt.PointingHandCursor)
        thumb_btn.setToolTip('Click to compare side by side')
        thumb_btn.setFixedSize(156, 156)
        thumb_btn.setFocusPolicy(Qt.NoFocus)
        thumb_btn.setText('Loading preview…')
        thumb_btn.clicked.connect(lambda _checked=False, files=compare_files: self._open_compare(files))
        lay.addWidget(thumb_btn, alignment=Qt.AlignCenter)

        from smd.media_types import is_video_file

        is_video = is_video_file(media_path)
        if is_video:
            play_btn = QPushButton('Play video')
            play_btn.setObjectName('toolbarBtn')
            play_btn.setToolTip('Open this file in your default video player')
            play_btn.clicked.connect(
                lambda _checked=False, p=media_path: QDesktopServices.openUrl(QUrl.fromLocalFile(str(p)))
            )
            lay.addWidget(play_btn, alignment=Qt.AlignCenter)

        keeper = QCheckBox('Keep this one')
        keeper.setProperty('dup_filename', filename)
        keeper.setChecked(checked)
        btn_group.addButton(keeper)
        lay.addWidget(keeper, alignment=Qt.AlignCenter)

        name_lbl = QLabel(filename)
        name_lbl.setWordWrap(True)
        name_lbl.setAlignment(Qt.AlignCenter)
        name_lbl.setProperty('class', 'caption')
        lay.addWidget(name_lbl)

        info_lbl = QLabel('Loading…')
        info_lbl.setAlignment(Qt.AlignCenter)
        info_lbl.setProperty('class', 'caption')
        lay.addWidget(info_lbl)
        self._preview_targets[str(media_path)] = (thumb_btn, info_lbl)
        return card

    def _on_keep_both(self, sha_prefix: str, btn_group: QButtonGroup) -> None:
        for btn in btn_group.buttons():
            btn.setChecked(True)

    def _open_compare(self, files: list[tuple[str, Path]]) -> None:
        existing = [(name, path) for name, path in files if path.is_file()]
        if len(existing) < 2:
            QMessageBox.information(self, 'Compare', 'Need at least two files to compare.')
            return
        DuplicateCompareDialog(self, existing, dark=self._dark).exec_()

    def _apply_theme(self, scroll: QScrollArea, inner: QWidget) -> None:
        from smd.theme import apply_scroll_area_theme, enable_styled_surface, paint_widget_surface

        enable_styled_surface(self)
        paint_widget_surface(self, dark=self._dark, role='bg')
        apply_scroll_area_theme(scroll, dark=self._dark)
        enable_styled_surface(inner)
        paint_widget_surface(inner, dark=self._dark, role='bg')

    def _selected_filenames(self, btn_group: QButtonGroup) -> list[str]:
        names: list[str] = []
        for b in btn_group.buttons():
            if b.isChecked():
                name = b.property('dup_filename')
                if name:
                    names.append(str(name))
        return names

    def _on_apply_clicked(self) -> None:
        # Gather non-keepers (unticked) per group. As a safety net we never
        # delete an entire group: if nothing is ticked, we keep everything.
        to_delete: list[str] = []
        skipped_all_unselected: list[str] = []
        group_selections: dict[str, dict] = {}
        for sha_prefix, entries_sorted, btn_group in self._group_ui:
            keepers = set(self._selected_filenames(btn_group))
            if not keepers:
                skipped_all_unselected.append(sha_prefix)
                group_selections[sha_prefix] = {
                    'keepers': [e.filename for e in entries_sorted],
                    'deleted': [],
                    'note': 'nothing selected - kept all',
                }
                continue
            non_keepers = [e.filename for e in entries_sorted if e.filename not in keepers]
            group_selections[sha_prefix] = {
                'keepers': sorted(keepers),
                'deleted': non_keepers,
            }
            to_delete.extend(non_keepers)

        if not to_delete:
            QMessageBox.information(
                self,
                'Nothing to delete',
                'Every duplicate is selected to keep, so there is nothing to delete.',
            )
            return

        # Delete each non-keeper from every folder it lives in (merged + raw
        # share the same filename per item), not a separate review folder.
        target_folders: list[tuple[str, Path]] = [('merged', self.paths.merged_dir)]
        raw_dir = getattr(self.paths, 'raw_dir', None)
        if raw_dir is not None:
            target_folders.append(('raw', raw_dir))
        folder_names = ' and '.join(label for label, _ in target_folders)

        confirm = QMessageBox.question(
            self,
            'Permanently delete duplicates?',
            f'{len(to_delete)} unselected duplicate(s) will be permanently deleted '
            f'from your {folder_names} folder(s).\n\n'
            f'This cannot be undone. Continue?',
            QMessageBox.Yes | QMessageBox.Cancel,
            QMessageBox.Cancel,
        )
        if confirm != QMessageBox.Yes:
            return

        deleted = 0
        deleted_files: list[str] = []
        errors: list[str] = []
        for name in to_delete:
            for label, folder in target_folders:
                p = folder / name
                try:
                    if p.is_file():
                        p.unlink()
                        deleted += 1
                        deleted_files.append(f'{label}/{name}')
                except OSError as exc:
                    errors.append(f'{label}/{name}: {exc}')

        ts = datetime.now(timezone.utc).strftime('%Y%m%d_%H%M%S')
        selection_report = {
            'generated_at_utc': datetime.now(timezone.utc).isoformat(),
            'account_name': self.account_name,
            'source_folders': [str(folder) for _, folder in target_folders],
            'action': 'permanent_delete',
            'deleted_count': deleted,
            'group_selections': group_selections,
            'deleted_files': deleted_files,
            'errors': errors,
        }
        out_json = None
        try:
            self.paths.reports_dir.mkdir(parents=True, exist_ok=True)
            out_json = self.paths.reports_dir / f'duplicates_deleted_report_{ts}.json'
            out_json.write_text(json.dumps(selection_report, indent=2), encoding='utf-8')
        except OSError:
            out_json = None

        self._update_cached_duplicate_report(group_selections)

        msg = f'Permanently deleted {deleted} duplicate file(s).'
        if skipped_all_unselected:
            msg += (
                f'\n\n{len(skipped_all_unselected)} group(s) had nothing selected, '
                f'so all their files were kept.'
            )
        if errors:
            msg += (
                f'\n\n{len(errors)} file(s) could not be deleted:\n'
                + '\n'.join(errors[:8])
            )
        if out_json is not None:
            msg += f'\n\nReport:\n{out_json}'
        QMessageBox.information(self, 'Duplicates deleted', msg)
        self.accept()

    def _update_cached_duplicate_report(self, group_selections: dict[str, dict]) -> None:
        """Drop resolved groups from technical/reports/duplicates_report.json.

        Groups where files were actually deleted are down to one keeper now,
        so they're no longer duplicates - removing them keeps the cache
        accurate for the next time "Review duplicates" is opened, without
        needing to re-hash merged/ from scratch.
        """
        try:
            from smd.duplicates import load_cached_duplicate_report

            cached = load_cached_duplicate_report(self.paths)
            if cached is None:
                return
            resolved_prefixes = {
                prefix for prefix, sel in group_selections.items() if sel.get('deleted')
            }
            if not resolved_prefixes:
                return
            cached.entries = [e for e in cached.entries if e.sha256 not in resolved_prefixes]
            cached.duplicate_groups = len({e.sha256 for e in cached.entries})
            report_path = self.paths.reports_dir / 'duplicates_report.json'
            report_path.write_text(json.dumps(cached.to_dict(), indent=2), encoding='utf-8')
        except Exception:
            pass
