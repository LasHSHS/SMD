"""Save memories tab mixin: setup, run lifecycle, dashboard, after-processing."""
from __future__ import annotations

import os
import re
import shutil
import sys
import zipfile
from datetime import datetime
from pathlib import Path

from PyQt5.QtCore import Qt, QSettings, QUrl
from PyQt5.QtGui import QDesktopServices
from PyQt5.QtWidgets import (
    QApplication, QWidget, QVBoxLayout, QHBoxLayout, QGridLayout, QPushButton,
    QLabel, QLineEdit, QComboBox, QCheckBox, QProgressBar, QFileDialog,
    QMessageBox, QSizePolicy, QMenu, QGraphicsOpacityEffect,
)

from gui.common import ROOT, TAB_SAVE_MEMORIES, play_happy_tone
from gui.widgets import LiveRunDashboard
from gui.workers import (
    LocalExportWorker,
    StagingCheckWorker,
    TechnicalStorageWorker,
)


class SaveMemoriesTabMixin:
    """Mixin: Save memories tab (full processing run + after-processing actions)."""

    def _add_save_memories_tab(self) -> None:
        # --- Tab 2: Save memories ---
        from smd.theme import SECTION_GAP

        download_tab = self._make_tab_page()
        download_tab_layout = QVBoxLayout(download_tab)
        download_tab_layout.setContentsMargins(0, 0, 0, 0)
        process_panel = QWidget()
        process_panel.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Preferred)
        controls_layout = QVBoxLayout(process_panel)
        controls_layout.setSpacing(SECTION_GAP)
        controls_layout.setContentsMargins(0, 0, 0, 0)

        setup_box, setup_lay = self._section('Export & project')
        zip_btn_row = QHBoxLayout()
        zip_btn_row.setSpacing(8)
        zip_files_btn = QPushButton('Choose ZIP files')
        zip_files_btn.setObjectName('accentBtn')
        zip_files_btn.setToolTip('Select one or more ZIP parts (Ctrl or Shift for multiple)')
        zip_files_btn.clicked.connect(self.select_zip_files)
        zip_folder_btn = QPushButton('Choose folder')
        zip_folder_btn.setObjectName('accentBtn')
        zip_folder_btn.setToolTip('Select a folder that contains all ZIP parts')
        zip_folder_btn.clicked.connect(self.select_zip_folder)
        zip_btn_row.addWidget(zip_files_btn)
        zip_btn_row.addWidget(zip_folder_btn)
        zip_btn_row.addStretch(1)
        setup_lay.addLayout(zip_btn_row)
        self.zip_label = QLabel('No file selected')
        self.zip_label.setProperty('class', 'muted')
        setup_lay.addWidget(self.zip_label)
        self.export_summary_label = QLabel(
            'Select ZIP files or a folder. A summary of what was found appears here.'
        )
        self.export_summary_label.setWordWrap(True)
        self.export_summary_label.setTextFormat(Qt.RichText)
        self.export_summary_label.setObjectName('infoBanner')
        setup_lay.addWidget(self.export_summary_label)

        project_divider = QLabel('Where to save')
        project_divider.setProperty('class', 'sectionHeader')
        setup_lay.addWidget(project_divider)
        account_hint = QLabel('Your memories are saved on the Desktop in a folder with this name.')
        account_hint.setWordWrap(True)
        account_hint.setProperty('class', 'muted')
        setup_lay.addWidget(account_hint)
        self.account_input = QLineEdit()
        self.account_input.setPlaceholderText('Project folder name (e.g. Mary, Las)')
        self.account_input.setToolTip('Folder name on your Desktop, e.g. Mary')
        self.account_input.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        setup_lay.addWidget(self.account_input)
        self.restore_account_name_field()
        self.account_input.textChanged.connect(self._on_account_name_edited)
        self.account_input.editingFinished.connect(self._update_run_readiness)

        self.download_path_label = QLabel('Folder: (will be shown when you pick a project)')
        self.download_path_label.setProperty('class', 'caption')
        setup_lay.addWidget(self.download_path_label)
        self.technical_storage_label = QLabel('')
        self.technical_storage_label.setProperty('class', 'caption')
        self.technical_storage_label.setWordWrap(True)
        setup_lay.addWidget(self.technical_storage_label)
        setup_lay.addStretch(1)

        perf_box, perf_lay = self._section('Performance')
        self.perf_mode_combo = QComboBox()
        self.perf_mode_combo.addItems([
            'Maximum (use all power)',
            'Balanced (smooth PC use)',
            'Eco (background friendly)',
        ])
        self.perf_mode_combo.setToolTip('Controls speed for ZIP processing and GPS scanning')
        self.perf_mode_combo.setCurrentIndex(0)
        self.perf_mode_combo.currentIndexChanged.connect(self.on_perf_mode_changed)

        cpu_cores = os.cpu_count() or 2
        self.cpu_info_label = QLabel(f'({cpu_cores} threads)')
        self.cpu_info_label.setProperty('class', 'caption')

        perf_lay.addWidget(self.perf_mode_combo)
        perf_lay.addWidget(self.cpu_info_label)
        self.system_profile_label = QLabel("")
        self.system_profile_label.setProperty('class', 'muted')
        self.system_profile_label.setWordWrap(True)
        perf_lay.addWidget(self.system_profile_label)
        perf_btn_row = QHBoxLayout()
        perf_btn_row.setSpacing(8)
        self.apply_recommend_btn = QPushButton('Recommended settings')
        self.apply_recommend_btn.setObjectName('toolbarBtn')
        self.apply_recommend_btn.setToolTip('Set performance from your PC, RAM, and power state')
        self.apply_recommend_btn.clicked.connect(self.apply_recommended_settings)
        self.assess_time_btn = QPushButton('Estimate time')
        self.assess_time_btn.setObjectName('toolbarBtn')
        self.assess_time_btn.setToolTip('Rough time for each performance mode before you start')
        self.assess_time_btn.clicked.connect(self.show_processing_estimate)
        perf_btn_row.addWidget(self.apply_recommend_btn)
        perf_btn_row.addWidget(self.assess_time_btn)
        perf_btn_row.addStretch(1)
        perf_lay.addLayout(perf_btn_row)
        perf_lay.addStretch(1)
        self.perf_section = perf_box

        from smd.theme import CONTROL_GAP, FIELD_GAP

        output_hint = QLabel(
            'Snapchat filters included by default. Optionally keep plain originals too.'
        )
        output_hint.setWordWrap(True)
        output_hint.setProperty('class', 'caption')
        self.save_raw_chk = QCheckBox('Also save without filters')
        self.save_raw_chk.setChecked(False)
        self.save_raw_chk.setToolTip(
            'Keeps a second copy of each memory without filters, stickers, or text overlays. '
            'Useful if you want the clean photo or video underneath.'
        )
        self.save_raw_chk.stateChanged.connect(self._on_save_raw_changed)

        self.technical_view_chk = QCheckBox('Technical view')
        self.technical_view_chk.setToolTip(
            'Shows staging, checkpoints, reports, and other working data used by SMD. '
            'Leave off for a simple Desktop folder with just your memories.'
        )
        stored_tv = QSettings('SnapchatMemories', 'Downloader').value('technical_view', False)
        self.technical_view_chk.setChecked(str(stored_tv).lower() in ('1', 'true', 'yes'))
        self.technical_view_chk.stateChanged.connect(self._on_technical_view_changed)

        self.keep_staging_chk = QCheckBox('Keep staging media files')
        self.keep_staging_chk.setToolTip(
            "Skips the automatic integrity check and cleanup of technical/staging/ "
            "after a run, so the original extracted files stick around until you "
            "delete them yourself. Turn this off to let SMD verify and free that "
            "disk space automatically once a run finishes successfully."
        )
        stored_keep_staging = QSettings('SnapchatMemories', 'Downloader').value(
            'keep_staging_files', False
        )
        self.keep_staging_chk.setChecked(
            str(stored_keep_staging).lower() in ('1', 'true', 'yes')
        )
        self.keep_staging_chk.stateChanged.connect(self._on_keep_staging_changed)
        self.keep_staging_hint = QLabel(
            "Staging is the working copy SMD extracts from your export before "
            "building merged/ and raw/. Leave unchecked to auto-verify and free "
            "that disk space once a run succeeds."
        )
        self.keep_staging_hint.setWordWrap(True)
        self.keep_staging_hint.setProperty('class', 'caption')

        run_box, run_lay = self._section('Run')
        run_body = QHBoxLayout()
        run_body.setSpacing(CONTROL_GAP)
        self.download_btn = QPushButton('Start full processing')
        self.download_btn.setObjectName('runAction')
        self.download_btn.setSizePolicy(QSizePolicy.Fixed, QSizePolicy.Fixed)
        self.download_btn.setToolTip('Extract, merge overlays, embed metadata, and show a summary report')
        self.download_btn.clicked.connect(self.on_download_button_clicked)

        run_options_col = QVBoxLayout()
        run_options_col.setSpacing(FIELD_GAP)
        run_options_col.addWidget(output_hint)
        run_options_col.addWidget(self.save_raw_chk)
        run_options_col.addWidget(self.technical_view_chk)
        run_options_col.addWidget(self.keep_staging_chk)
        run_options_col.addWidget(self.keep_staging_hint)
        run_options_col.addStretch(1)
        run_body.addLayout(run_options_col, 1)
        run_body.addWidget(self.download_btn, 0, Qt.AlignVCenter | Qt.AlignRight)
        run_body_host = QWidget()
        run_body_host.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        run_body_host.setLayout(run_body)
        run_lay.addWidget(run_body_host, 1)

        run_footer = QHBoxLayout()
        run_footer.setSpacing(CONTROL_GAP)
        self.action_header = QLabel('Ready to start?')
        self.action_header.setProperty('class', 'caption')
        run_footer.addWidget(self.action_header)
        self.step_status_label = QLabel('Steps: waiting for export selection')
        self.step_status_label.setProperty('class', 'caption')
        run_footer.addWidget(self.step_status_label, 1)
        run_lay.addLayout(run_footer)

        after_box, after_lay = self._section('After processing')
        after_grid = QGridLayout()
        after_grid.setHorizontalSpacing(8)
        after_grid.setVerticalSpacing(8)
        self.open_folder_btn = QPushButton('Open finished folder')
        self.open_folder_btn.setObjectName('toolbarBtn')
        self.open_folder_btn.setToolTip('Your finished photos and videos (with Snapchat filters)')
        self.open_folder_btn.clicked.connect(self.open_download_folder)

        self.open_gallery_btn = QPushButton('View as gallery')
        self.open_gallery_btn.setObjectName('toolbarBtn')
        self.open_gallery_btn.setToolTip(
            "Opens your first memory in the Windows Photos app - from there, use the "
            "arrow keys or on-screen arrows to flip through every photo and video in the "
            "folder, or start a slideshow. No separate gallery to maintain."
        )
        self.open_gallery_btn.clicked.connect(self.open_gallery_view)

        self.open_technical_btn = QPushButton('Open technical folder')
        self.open_technical_btn.setObjectName('toolbarBtn')
        self.open_technical_btn.setToolTip(
            'Opens technical/ - staging, JSON, reports, checkpoint (can use a lot of disk space)'
        )
        self.open_technical_btn.clicked.connect(self.open_technical_folder)

        self.verify_staging_btn = QPushButton('Verify staging')
        self.verify_staging_btn.setObjectName('toolbarBtn')
        self.verify_staging_btn.setToolTip(
            'Checks that every memory in staging has output in merged/ and raw/ '
            'before you delete technical/staging/ to free disk space'
        )
        self.verify_staging_btn.clicked.connect(self.verify_staging_readiness)

        self.review_duplicates_btn = QPushButton('Review duplicates')
        self.review_duplicates_btn.setObjectName('toolbarBtn')
        self.review_duplicates_btn.setToolTip(
            'Scan merged/ for byte-identical duplicates, tick the copies to keep per group, '
            'then permanently delete the ones you did not keep (from both merged/ and raw/).'
        )
        self.review_duplicates_btn.clicked.connect(self.review_duplicates)

        self.open_debug_btn = QPushButton('Open debug folder')
        self.open_debug_btn.setObjectName('toolbarBtn')
        self.open_debug_btn.setToolTip('Opens technical/debug/ - processing logs and failed items')
        self.open_debug_btn.clicked.connect(self.open_debug_folder)

        after_grid.addWidget(self.open_folder_btn, 0, 0)
        after_grid.addWidget(self.open_gallery_btn, 0, 1)
        after_grid.addWidget(self.review_duplicates_btn, 1, 0)
        after_grid.addWidget(self.open_technical_btn, 1, 1)
        after_grid.addWidget(self.verify_staging_btn, 2, 0)
        after_grid.addWidget(self.open_debug_btn, 2, 1)
        after_lay.addLayout(after_grid)

        self._setup_section = setup_box
        self._perf_section = perf_box
        self._run_section = run_box
        self._after_section = after_box
        self._process_controls_grid_host = QWidget()
        self._process_controls_grid_host.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Preferred)
        self._process_controls_grid = QGridLayout(self._process_controls_grid_host)
        self._process_controls_grid.setContentsMargins(0, 0, 0, 0)
        from smd.theme import CONTROL_GAP as _cg, SECTION_GAP as _sg
        self._process_controls_grid.setHorizontalSpacing(_cg)
        self._process_controls_grid.setVerticalSpacing(_sg)
        controls_layout.addWidget(self._process_controls_grid_host)
        self._rebuild_process_controls_grid()
        self._refresh_after_processing_actions()

        progress_box, progress_lay = self._section('Progress')
        progress_box.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Maximum)
        self.progress_section = progress_box
        self.progress_bar = QProgressBar()
        self.progress_bar.setRange(0, 100)
        self.progress_bar.setValue(0)
        self.progress_bar.setFixedHeight(28)
        progress_lay.addWidget(self.progress_bar)

        self.status_label = QLabel('Ready')
        self.status_label.setWordWrap(True)
        progress_lay.addWidget(self.status_label)

        self.mode_status_label = QLabel('Mode: waiting')
        self.mode_status_label.setProperty('class', 'caption')
        progress_lay.addWidget(self.mode_status_label)

        self.download_details = QLabel('Files: 0/0 | Speed: - | ETA: -')
        self.download_details.setProperty('class', 'caption')
        progress_lay.addWidget(self.download_details)

        dashboard_row = QHBoxLayout()
        dashboard_row.addStretch(1)
        self.debug_output_toggle = QCheckBox('Show live run dashboard')
        self.debug_output_toggle.setToolTip(
            'Shows a larger live panel with progress, time estimates, and activity messages during processing'
        )
        self.debug_output_toggle.setChecked(False)
        self.debug_output_toggle.stateChanged.connect(self.toggle_debug_output)
        dashboard_row.addWidget(self.debug_output_toggle)
        progress_lay.addLayout(dashboard_row)

        self.live_run_dashboard = LiveRunDashboard()
        self.live_run_dashboard.setVisible(self.debug_output_toggle.isChecked())
        progress_lay.addWidget(self.live_run_dashboard, 0)
        self._apply_dashboard_visibility(self.debug_output_toggle.isChecked())
        self._run_phase = "Waiting"
        self._run_log_buffer: list[str] = []
        self._last_estimate_label: str | None = None
        controls_layout.addWidget(progress_box)
        # Absorb leftover vertical space so the last section (Progress) keeps its
        # natural height instead of stretching tall when the dashboard is hidden.
        controls_layout.addStretch(1)

        self.download_running = False
        download_tab_layout.addWidget(self._form_tab(process_panel))
        self.tabs.addTab(download_tab, TAB_SAVE_MEMORIES)


    def update_status_animation(self):
        """Animate status text with moving indicator"""
        if not self.status_animation_active:
            return
        
        # Create moving dots animation (8 frame cycle)
        indicators = ['⠋', '⠙', '⠹', '⠸', '⠼', '⠴', '⠦', '⠧']
        frame = indicators[self.status_animation_frame % len(indicators)]
        
        # Update status with animated frame
        animated_text = f"{frame} {self.status_base_text}"
        self.unified_status.setText(animated_text)
        self.status_animation_frame += 1

    def start_status_animation(self, base_text):
        """Start animated status display"""
        self.status_base_text = base_text
        self.status_animation_active = True
        self.status_animation_frame = 0
        self.status_animation_timer.start(100)  # Update every 100ms

    def stop_status_animation(self):
        """Stop animated status display"""
        self.status_animation_active = False
        self.status_animation_timer.stop()

    def refresh_system_profile(self):
        """Update PC / power labels and warn if power source changed."""
        from smd.system_profile import (
            compute_workers,
            get_system_profile,
        )

        profile = get_system_profile()
        settings = compute_workers(self.performance_mode, profile, task="export")

        self.system_profile_label.setText(
            f"{profile.summary()} • ~{settings.max_workers} parallel jobs"
        )
        self.cpu_info_label.setText(
            f"({profile.physical_cores} cores / {profile.logical_cpus} threads, {settings.max_workers} jobs)"
        )

        if self._last_power_on_battery is not None and profile.on_battery is not None:
            if profile.on_battery != self._last_power_on_battery:
                msg = (
                    "On battery - consider Balanced or Eco for the next run"
                    if profile.on_battery
                    else "Plugged in - Maximum is fine for the next run"
                )
                self._apply_status(self.status_label, msg, 'warn')
                if hasattr(self, 'unified_status'):
                    self._apply_status(self.unified_status, msg, 'warn')
        self._last_power_on_battery = profile.on_battery

    def apply_recommended_settings(self, silent: bool = False):
        """Apply hardware-based performance mode recommendation."""
        from smd.system_profile import mode_to_combo_index, recommend_settings

        rec = recommend_settings()
        self.performance_mode = rec.performance_mode
        self._persist_perf_mode()
        self.perf_mode_combo.blockSignals(True)
        self.perf_mode_combo.setCurrentIndex(mode_to_combo_index(rec.performance_mode))
        self.perf_mode_combo.blockSignals(False)
        self.refresh_system_profile()
        if not silent:
            msg = (
                f"Recommended: {rec.performance_mode.title()} "
                f"({rec.max_workers} parallel jobs - {rec.reason})"
            )
            self._apply_status(self.status_label, msg, 'info')

    def on_perf_mode_changed(self, index):
        """Handle performance mode change"""
        mode_map = {0: 'maximum', 1: 'balanced', 2: 'conservative'}
        self.performance_mode = mode_map.get(index, 'balanced')
        self._persist_perf_mode()
        self.refresh_system_profile()
        self.update_export_ui_mode()

    def _persist_perf_mode(self) -> None:
        """Remember the selected performance mode across launches."""
        try:
            self._perf_settings.setValue("performance_mode_v1", self.performance_mode)
        except Exception:
            pass

    def _account_name(self) -> str:
        return self.account_input.text().strip()

    @staticmethod
    def _is_valid_account_name(name: str) -> bool:
        if not name or name in ('.', '..'):
            return False
        return not any(ch in name for ch in '<>:"/\\|?*')

    def _rebuild_process_controls_grid(self) -> None:
        """Stack sections in a single column so none of them ever has to share
        row width with a sibling - a 2-column layout here forced Run and After
        processing side by side, and their combined natural width couldn't
        shrink below ~1600px, wedging the whole tab wide no matter the window
        size. Stacking vertically works at any window width since the tab is
        already scrollable."""
        grid = self._process_controls_grid
        for section in (
            self._setup_section,
            self._perf_section,
            self._run_section,
            self._after_section,
        ):
            grid.removeWidget(section)
            section.setParent(self._process_controls_grid_host)

        technical = self._technical_view_enabled()
        self._perf_section.setVisible(technical)
        row = 0
        grid.addWidget(self._setup_section, row, 0)
        row += 1
        if technical:
            grid.addWidget(self._perf_section, row, 0)
            row += 1
        grid.addWidget(self._run_section, row, 0)
        row += 1
        grid.addWidget(self._after_section, row, 0)
        grid.setColumnStretch(0, 1)

    def _set_run_lockout(self, active: bool) -> None:
        """Dim and disable Setup/Performance/After-processing while a run is
        active. Deliberately excludes the Run section (the Start/Cancel
        button lives there and must stay clickable) and the Progress section
        (the live dashboard must stay scrollable) - a previous full-window
        overlay covered those too and made it impossible to scroll the log
        or click Cancel while a run was in progress."""
        for section in (
            getattr(self, '_setup_section', None),
            getattr(self, '_perf_section', None),
            getattr(self, '_after_section', None),
        ):
            if section is None:
                continue
            section.setEnabled(not active)
            if active:
                effect = section.graphicsEffect()
                if not isinstance(effect, QGraphicsOpacityEffect):
                    effect = QGraphicsOpacityEffect(section)
                    section.setGraphicsEffect(effect)
                effect.setOpacity(0.4)
            else:
                section.setGraphicsEffect(None)

    def _set_keep_awake(self, active: bool) -> None:
        """Prevent Windows from sleeping the system or display while a run
        (including the post-run verification/finalize passes) is in
        progress, then release it as soon as that work ends.

        Motivated by a user report: some AMD GPUs render at a fraction of
        normal speed for a while after the display wakes from sleep (a
        known driver quirk - Ctrl+Shift+Win+B, which restarts the graphics
        driver, is the common workaround). If SMD is mid-run when the
        monitor sleeps, that post-wake slowdown hits ffmpeg too. Keeping
        the display on for the run's duration avoids the wake cycle
        entirely instead of trying to detect/react to it. See
        agent-docs/DECISIONS.md, "Keep system/display awake during a run".
        """
        if sys.platform != 'win32':
            return
        try:
            import ctypes

            ES_CONTINUOUS = 0x80000000
            ES_SYSTEM_REQUIRED = 0x00000001
            ES_DISPLAY_REQUIRED = 0x00000002
            flags = ES_CONTINUOUS | (ES_SYSTEM_REQUIRED | ES_DISPLAY_REQUIRED if active else 0)
            ctypes.windll.kernel32.SetThreadExecutionState(flags)
        except Exception:
            pass

    def _update_run_readiness(self) -> None:
        """Enable Start only when export is valid and account name is usable."""
        if getattr(self, 'download_running', False):
            self.download_btn.setEnabled(True)
            return

        analysis = getattr(self, 'export_analysis', None)
        bundled = bool(analysis and analysis.is_bundled)
        name = self._account_name()
        valid_name = self._is_valid_account_name(name)
        ready = bundled and valid_name

        self.download_btn.setEnabled(ready)
        if not analysis:
            tip = 'Select a Snapchat export ZIP or folder first.'
        elif not bundled:
            tip = 'This export has no media files. Request a new export from Snapchat.'
        elif not name:
            tip = 'Enter a project folder name (shown on your Desktop).'
        elif not valid_name:
            tip = 'Folder name cannot contain \\ / : * ? " < > |'
        else:
            tip = 'Extract, merge overlays, embed metadata, and show a summary report'
        self.download_btn.setToolTip(tip)

    def update_export_ui_mode(self):
        """Update summary and button labels based on detected export type."""
        from smd.system_profile import compute_workers, get_system_profile

        analysis = getattr(self, 'export_analysis', None)
        bundled = bool(analysis and analysis.is_bundled)

        if not analysis:
            self.download_btn.setText('Start full processing')
            self.action_header.setText('Ready to start?')
            self._update_run_readiness()
            return

        settings = compute_workers(self.performance_mode, get_system_profile(), task='export')
        parts = len(analysis.zip_paths or [])
        technical = self._technical_view_enabled()

        if bundled:
            self.download_btn.setText('Start full processing')
            self.action_header.setText('Ready to process?')
            worker_line = (
                f"{settings.max_workers} parallel jobs • metadata, GPS, and overlays"
                if technical
                else 'metadata, GPS, and Snapchat filters included'
            )
            self.export_summary_label.setText(
                f"<b>Bundled export</b> - {parts} ZIP parts, "
                f"~{analysis.main_file_count:,} media files, fully offline<br>"
                f"{worker_line}"
            )
            self.step_status_label.setText(
                'Steps on start: detect export → extract ZIPs → match JSON → '
                'merge overlays → embed metadata → summary report'
            )
            self.export_summary_label.setObjectName('infoBanner')
            self.export_summary_label.setStyleSheet('')
        else:
            self.download_btn.setText('Start full processing')
            self.action_header.setText('Export not supported')
            self.export_summary_label.setText(
                '<b>This export does not include media files.</b><br>'
                'Request a new Snapchat data export with memories included in the ZIP.'
            )
            self.export_summary_label.setObjectName('infoBanner')
            self.export_summary_label.setStyleSheet('')

        self._update_run_readiness()

    def _export_default_dir(self) -> str:
        default_dir = str(Path.home() / 'Downloads')
        if not Path(default_dir).exists():
            default_dir = str(Path.home() / 'Pictures')
        if not Path(default_dir).exists():
            default_dir = str(Path.home())
        return default_dir

    def _suggest_account_from_export(self, zip_paths):
        from smd.export_detect import export_base_ids

        bases = export_base_ids(zip_paths)
        if not bases:
            return
        base_id = sorted(bases)[0]
        short = base_id.replace("mydata~", "export-")
        search_dirs = []
        if self._technical_view_enabled():
            accounts_root = Path(self.get_download_base_dir()) / "accounts"
            if accounts_root.is_dir():
                search_dirs.append(accounts_root)
        else:
            desktop = Path.home() / "Desktop"
            if desktop.is_dir():
                search_dirs.append(desktop)

        for root in search_dirs:
            for existing in root.iterdir():
                if existing.is_dir() and short in existing.name.lower():
                    self.account_input.setText(existing.name)
                    self.update_download_path_label(existing.name)
                    return

        if not self._account_name():
            if "~" in base_id:
                tail = base_id.split("~", 1)[-1][:8]
                suggested = f"Memories {tail}" if tail else "My memories"
            else:
                suggested = "My memories"
            self.account_input.setText(suggested)
            self.update_download_path_label(suggested)

    def show_processing_estimate(self):
        analysis = getattr(self, "export_analysis", None)
        if not analysis or not analysis.is_bundled:
            QMessageBox.information(
                self,
                "Estimate",
                "Select a bundled Snapchat export ZIP or folder first.",
            )
            return
        from smd.system_profile import MODE_LABELS, get_system_profile
        from smd.time_estimate import estimate_bundled_processing

        file_count = analysis.json_rows or analysis.main_file_count or 1
        account_name = self._account_name()
        needs_extract = True
        staging_gb = 0.0
        zip_total_gb = 0.0
        if account_name:
            try:
                paths = self._account_paths(account_name)
                staging = paths.staging_dir
                if staging.is_dir():
                    mains = sum(
                        1
                        for p in staging.iterdir()
                        if p.is_file() and "-main." in p.name.lower()
                    )
                    needs_extract = mains < max(50, file_count // 20)
                    if not needs_extract:
                        staging_gb = sum(
                            p.stat().st_size for p in staging.rglob("*") if p.is_file()
                        ) / (1024**3)
            except Exception:
                pass

        # Hybrid estimate:
        overlay_fraction = 0.24
        if analysis.main_file_count and analysis.main_file_count > 0:
            overlay_fraction = min(
                1.0, max(0.0, (analysis.overlay_file_count or 0) / analysis.main_file_count)
            )

        video_fraction = 0.12
        try:
            import tempfile
            from smd.export_detect import extract_json_from_zips
            from smd.utils import load_memories

            zip_paths = analysis.zip_paths or []
            if zip_paths:
                est_json = Path(tempfile.gettempdir()) / "smd_estimate_memories_history.json"
                extract_json_from_zips(zip_paths, est_json)
                memories = load_memories(est_json)
                if memories:
                    videos = sum(1 for m in memories if (m.media_type or "").strip().lower() == "video")
                    video_fraction = min(1.0, max(0.0, videos / max(len(memories), 1)))
        except Exception:
            pass

        if needs_extract and staging_gb <= 0.0:
            try:
                zip_paths = analysis.zip_paths or []
                if zip_paths:
                    zip_total_gb = sum(p.stat().st_size for p in zip_paths) / (1024**3)
                    staging_gb = zip_total_gb
            except Exception:
                pass

        est = estimate_bundled_processing(
            file_count,
            profile=get_system_profile(),
            needs_zip_extract=needs_extract,
            staging_gb=staging_gb,
            overlay_fraction=overlay_fraction,
            video_fraction=video_fraction,
        )

        lines = [f"About {file_count:,} memories in this export.", ""]
        if not needs_extract:
            lines.append("Staging found on disk: ZIP extract should be skipped (faster).")
        else:
            if zip_total_gb > 0:
                lines.append("No staging found: estimate includes ZIP extract time (rough).")
            else:
                lines.append("No staging found: estimate includes full ZIP extract.")
        lines.append("")

        lines.append(
            f"Split: videos {int(video_fraction * 100)}%, overlays {int(overlay_fraction * 100)}% (from JSON and ZIP listing)."
        )
        lines.append("")
        for mode, data in est.items():
            lines.append(f"{MODE_LABELS[mode]}: about {data['label']} ({data['workers']} workers)")
            note = str(data.get("note") or "")
            if note:
                lines.append(f"  {note}")
        self._last_estimate_label = str(est.get(self.performance_mode, {}).get("label") or "")
        QMessageBox.information(self, "Processing time estimate", "\n".join(lines))

    def select_zip_files(self):
        """Open file picker - one or many ZIP parts (multi-select)."""
        paths, _ = QFileDialog.getOpenFileNames(
            self,
            'Select Snapchat ZIP files',
            self._export_default_dir(),
            'ZIP files (*.zip);;All files (*)',
        )
        if paths:
            self._set_export_selection(paths)

    def select_zip_folder(self):
        """Open folder picker for a directory containing ZIP parts."""
        folder = QFileDialog.getExistingDirectory(
            self,
            'Select folder with ZIP files',
            self._export_default_dir(),
        )
        if folder:
            self._set_export_selection(folder)

    def _set_export_selection(self, path: str | list[str]):
        from smd.export_detect import analyze_zip_export, export_base_ids, resolve_export_zip_paths

        if isinstance(path, list):
            paths = [Path(p) for p in path]
            self.selected_zip = str(paths[0])
        else:
            paths = [Path(path)]
            self.selected_zip = path

        p = paths[0]
        zip_paths = resolve_export_zip_paths(paths if isinstance(path, list) else p)
        if isinstance(path, list) and len(path) > 1:
            bases = export_base_ids(zip_paths)
            if len(bases) > 1:
                QMessageBox.warning(
                    self,
                    'Different exports',
                    'You selected ZIP files from more than one Snapchat export.\n'
                    'Choose only files from the same export (same mydata ID).',
                )
                return

        analysis = analyze_zip_export(path if isinstance(path, list) else p)
        self.export_analysis = analysis
        part_txt = f"{len(zip_paths)} ZIP parts" if len(zip_paths) > 1 else "1 ZIP"
        if analysis.is_bundled:
            fmt = f"Bundled • {part_txt} • ~{analysis.main_file_count} main files"
        else:
            fmt = "No media in ZIP — request a new export from Snapchat"

        if isinstance(path, list) and len(path) > 1:
            label_name = f"{len(path)} files selected"
        elif p.is_dir():
            label_name = p.name + "/"
        else:
            label_name = p.name

        self.zip_label.setText(f'{label_name} ({fmt})')
        from smd.theme import apply_status_property
        apply_status_property(self.zip_label, 'ok')
        self._suggest_account_from_export(zip_paths)
        self.update_export_ui_mode()

    def get_default_base_dir(self):
        """Default to Desktop/SMD Media as requested by user."""
        desktop = Path.home() / 'Desktop' / 'SMD Media'
        try:
             desktop.mkdir(parents=True, exist_ok=True)
             return str(desktop)
        except Exception:
             # Fallback to Documents if Desktop fails
             docs = Path.home() / 'Documents' / 'SMD Media'
             docs.mkdir(parents=True, exist_ok=True)
             return str(docs)

    def get_download_base_dir(self):
        try:
            settings = QSettings('SnapchatMemories', 'Downloader')
            base_dir = settings.value('download_base_dir', None)
            if not base_dir:
                base_dir = self.get_default_base_dir()
                settings.setValue('download_base_dir', base_dir)
            return str(base_dir)
        except Exception:
            return self.get_default_base_dir()

    def _account_paths(self, account_name: str, *, create: bool = False):
        from smd.account_layout import AccountPaths, migrate_account_layout, normalize_account_dir, resolve_account_paths

        keep_raw = self.save_raw_chk.isChecked() if hasattr(self, 'save_raw_chk') else False
        if self._technical_view_enabled():
            base_dir = Path(self.get_download_base_dir())
            account_dir = normalize_account_dir(base_dir / 'accounts' / account_name)
            if create:
                return resolve_account_paths(account_dir, migrate=True, create=True)
            return AccountPaths.for_account(account_dir)

        paths = AccountPaths.for_user(account_name, keep_raw=keep_raw)
        if create:
            paths.ensure_user_dirs(keep_raw=keep_raw)
            migrate_account_layout(paths)
        return paths

    def _on_account_name_edited(self, _text: str) -> None:
        """Update labels while typing without creating account folders on disk."""
        name = self._account_name()
        if not name:
            return
        self.update_download_path_label(name, create=False, storage_scan=False)
        if self._technical_view_enabled():
            self._pending_storage_account = name
            self._storage_debounce_timer.start(400)

    def update_download_path_label(
        self, account_name: str, *, create: bool = False, storage_scan: bool = True
    ) -> None:
        try:
            from smd.account_layout import format_bytes

            paths = self._account_paths(account_name, create=create)
            if self._technical_view_enabled():
                self.download_path_label.setText(f'Media: {paths.merged_dir}')
            else:
                self.download_path_label.setText(f'Saved to: {paths.library_root}')
            if not paths.account_dir.exists() and not create and not paths.library_root.exists():
                self.technical_storage_label.setText(
                    'Technical: (folder is created when you start processing)'
                )
                return
            if self._technical_view_enabled():
                if storage_scan:
                    self.technical_storage_label.setText('Technical: Calculating…')
                    self._pending_storage_account = account_name
                    self._run_technical_storage_scan()
            else:
                self.technical_storage_label.setText('')
        except Exception:
            self.download_path_label.setText('Folder: (unavailable)')
            self.technical_storage_label.setText('')
        self._refresh_after_processing_actions()

    def _run_technical_storage_scan(self) -> None:
        account_name = self._pending_storage_account or self._account_name()
        if not account_name or not self._technical_view_enabled():
            return
        try:
            paths = self._account_paths(account_name, create=False)
        except Exception:
            return
        self._storage_scan_generation += 1
        generation = self._storage_scan_generation
        self._stop_worker('technical_storage_worker')
        self.technical_storage_worker = TechnicalStorageWorker(paths, account_name)
        self.technical_storage_worker.finished_ok.connect(
            lambda name, rows, gen=generation: self._on_technical_storage_ready(name, rows, gen)
        )
        self.technical_storage_worker.error.connect(self._on_technical_storage_error)
        self.technical_storage_worker.start()

    def _on_technical_storage_ready(self, account_name: str, rows, generation: int) -> None:
        if generation != self._storage_scan_generation:
            return
        if self._account_name() != account_name or not self._technical_view_enabled():
            return
        try:
            from smd.account_layout import format_bytes

            paths = self._account_paths(account_name, create=False)
            staging_bytes = next((n for label, n in rows if label == 'staging'), 0)
            total_tech = sum(n for _, n in rows)
            parts = [f"staging {format_bytes(staging_bytes)}"]
            parts.extend(
                f"{label} {format_bytes(size)}"
                for label, size in rows
                if label != 'staging' and size > 0
            )
            self.technical_storage_label.setText(
                f"Technical: {paths.technical_dir} - {', '.join(parts)} "
                f"(total {format_bytes(total_tech)})"
            )
        except Exception:
            self.technical_storage_label.setText('Technical: (unavailable)')

    def _on_technical_storage_error(self, _message: str) -> None:
        if self._technical_view_enabled():
            self.technical_storage_label.setText('Technical: (size scan failed)')

    @staticmethod
    def _folder_has_files(folder: Path, *, min_files: int = 1) -> bool:
        if not folder.is_dir():
            return False
        try:
            found = 0
            for entry in folder.iterdir():
                if entry.is_file():
                    found += 1
                    if found >= min_files:
                        return True
            return found >= min_files
        except OSError:
            return False

    def _refresh_after_processing_actions(self) -> None:
        """Enable After processing buttons only when the relevant project data exists."""
        buttons = (
            self.open_folder_btn,
            self.open_gallery_btn,
            self.open_technical_btn,
            self.verify_staging_btn,
            self.review_duplicates_btn,
            self.open_debug_btn,
        )
        busy = bool(getattr(self, 'download_running', False))
        account_name = self._account_name()

        def _disable_all() -> None:
            for btn in buttons:
                btn.setEnabled(False)

        if not account_name or busy:
            _disable_all()
            return

        try:
            paths = self._account_paths(account_name, create=False)
        except Exception:
            _disable_all()
            return

        has_merged = self._folder_has_files(paths.merged_dir)
        has_staging = self._folder_has_files(paths.staging_dir)
        has_technical = paths.account_dir.is_dir() and paths.technical_dir.is_dir() and (
            paths.json_path.exists()
            or has_staging
            or self._folder_has_files(paths.reports_dir)
            or self._folder_has_files(paths.debug_dir)
        )
        has_debug = self._folder_has_files(paths.debug_dir)

        self.open_folder_btn.setEnabled(has_merged)
        self.open_gallery_btn.setEnabled(has_merged)
        self.open_technical_btn.setEnabled(has_technical)
        self.verify_staging_btn.setEnabled(has_staging)
        self.review_duplicates_btn.setEnabled(has_merged)
        self.open_debug_btn.setEnabled(has_debug)

    def open_download_folder(self):
        try:
            account_name = self._account_name()
            if not account_name:
                QMessageBox.information(self, 'Folder', 'Enter an account name first.'); return
            paths = self._account_paths(account_name)
            paths.library_root.mkdir(parents=True, exist_ok=True)
            QDesktopServices.openUrl(QUrl.fromLocalFile(str(paths.library_root)))
        except Exception as e:
            try:
                QMessageBox.warning(self, 'Folder Error', f'Could not open folder:\n{e}')
            except Exception:
                pass

    def open_gallery_view(self):
        """Exploit the Windows Photos app as a zero-maintenance gallery: opening
        one memory launches the OS default viewer, which lets the user arrow
        through every photo/video in the same folder, zoom, and run a slideshow -
        no custom gallery UI for SMD to build or maintain."""
        try:
            account_name = self._account_name()
            if not account_name:
                QMessageBox.information(self, 'Gallery', 'Enter an account name first.')
                return
            paths = self._account_paths(account_name)
            merged_dir = paths.merged_dir
            if not merged_dir.is_dir():
                QMessageBox.information(
                    self, 'Gallery', 'No finished memories yet - run processing first.'
                )
                return
            from smd.media_types import MEDIA_EXTENSIONS

            gallery_exts = MEDIA_EXTENSIONS | {'.webp'}
            first_file = min(
                (
                    p
                    for p in merged_dir.iterdir()
                    if p.is_file() and p.suffix.lower() in gallery_exts
                ),
                key=lambda p: p.name.lower(),
                default=None,
            )
            if first_file is None:
                QMessageBox.information(
                    self, 'Gallery', 'No photos or videos found in the finished folder.'
                )
                return
            QDesktopServices.openUrl(QUrl.fromLocalFile(str(first_file)))
        except Exception as e:
            try:
                QMessageBox.warning(self, 'Gallery Error', f'Could not open gallery view:\n{e}')
            except Exception:
                pass

    def open_technical_folder(self):
        try:
            account_name = self._account_name()
            if not account_name:
                QMessageBox.information(self, 'Technical Folder', 'Enter an account name first.')
                return
            paths = self._account_paths(account_name)
            paths.technical_dir.mkdir(parents=True, exist_ok=True)
            QDesktopServices.openUrl(QUrl.fromLocalFile(str(paths.technical_dir)))
        except Exception as e:
            try:
                QMessageBox.warning(self, 'Folder Error', f'Could not open technical folder:\n{e}')
            except Exception:
                pass

    def verify_staging_readiness(self):
        """Run staging completeness check; offer delete if safe."""
        if self.download_running:
            QMessageBox.information(
                self,
                'Verify staging',
                'Wait until the current download/processing job finishes.',
            )
            return
        account_name = self._account_name()
        if not account_name:
            QMessageBox.information(self, 'Verify staging', 'Enter an account name first.')
            return
        self.verify_staging_btn.setEnabled(False)
        self._apply_status(self.status_label, 'Verifying staging folder…', 'info')
        self._stop_worker('staging_check_worker')
        self.staging_check_worker = StagingCheckWorker(
            self._account_paths(account_name).account_dir
        )
        self.staging_check_worker.finished.connect(self.on_staging_check_finished)
        self.staging_check_worker.error.connect(self.on_staging_check_error)
        self.staging_check_worker.start()

    def on_staging_check_error(self, message: str):
        self._refresh_after_processing_actions()
        self._apply_status(self.status_label, 'Staging verification failed.', 'err')
        QMessageBox.critical(self, 'Verify staging', message)

    def on_staging_check_finished(self, report):
        from smd.account_layout import format_bytes
        from smd.staging_check import delete_staging_folder

        self._refresh_after_processing_actions()
        account_name = self._account_name()
        paths = self._account_paths(account_name)
        self.update_download_path_label(account_name)

        lines = report.summary_lines()
        detail_parts = [lines[0], *lines[1:], ""]
        for issue in report.issues:
            detail_parts.append(f"[{issue.severity.upper()}] {issue.message}")
            if issue.stems:
                detail_parts.append("  e.g. " + ", ".join(issue.stems[:5]))
        detail = "\n".join(detail_parts)
        report_path = paths.reports_dir / "staging_readiness.json"

        if report.safe_to_delete:
            self._apply_status(self.status_label, 'Staging verified - safe to delete.', 'ok')
            reply = QMessageBox.question(
                self,
                'Staging verified',
                f"All {report.staging_main_count} memories have outputs in merged/ and raw/.\n\n"
                f"Staging uses {format_bytes(report.staging_bytes)}.\n\n"
                "Delete technical/staging/ now to free this space?\n"
                "(You can re-extract from ZIPs later if needed.)",
                QMessageBox.Yes | QMessageBox.No,
                QMessageBox.No,
            )
            if reply == QMessageBox.Yes:
                ok, msg = delete_staging_folder(paths.account_dir, report=report, layout=paths)
                if ok:
                    self.update_download_path_label(account_name)
                    self._apply_status(self.status_label, msg, 'ok')
                    QMessageBox.information(self, 'Staging deleted', msg)
                else:
                    QMessageBox.warning(self, 'Delete staging', msg)
            else:
                QMessageBox.information(
                    self,
                    'Staging verified',
                    f"Check passed. Report saved to:\n{report_path}\n\n"
                    "You can delete technical/staging/ manually when ready.",
                )
        else:
            self._apply_status(self.status_label, 'Staging NOT safe to delete - see report.', 'warn')
            box = QMessageBox(self)
            box.setIcon(QMessageBox.Warning)
            box.setWindowTitle('Staging not ready')
            box.setText(
                "Do not delete staging yet - some memories are missing or unfinished."
            )
            box.setInformativeText("\n".join(lines))
            box.setDetailedText(detail)
            box.exec_()

    def open_debug_folder(self):
        """Open the debug folder for the current account"""
        try:
            account_name = self._account_name()
            if not account_name:
                QMessageBox.information(self, 'Debug Folder', 'Enter an account name first.')
                return
            paths = self._account_paths(account_name)
            debug_dir = paths.debug_dir
            if not debug_dir.exists():
                debug_dir.mkdir(parents=True, exist_ok=True)
            QDesktopServices.openUrl(QUrl.fromLocalFile(str(debug_dir)))
        except Exception as e:
            try:
                QMessageBox.warning(self, 'Debug Folder Error', f'Could not open debug folder:\n{e}')
            except Exception:
                pass

    def _populate_support_menu(self, button: QPushButton) -> None:
        """Attach a menu with free and optional tip links."""
        from smd.support_links import support_options

        menu = QMenu(self)
        donate_opts = [o for o in support_options() if o.category == "donate"]
        free_opts = [o for o in support_options() if o.category == "free"]

        if donate_opts:
            for opt in donate_opts:
                action = menu.addAction(opt.label.replace("&", "&&"))
                action.setToolTip(opt.description)
                action.triggered.connect(
                    lambda _checked=False, url=opt.url: QDesktopServices.openUrl(QUrl(url))
                )
            if free_opts:
                menu.addSeparator()

        for opt in free_opts:
            action = menu.addAction(opt.label.replace("&", "&&"))
            action.setToolTip(opt.description)
            action.triggered.connect(
                lambda _checked=False, url=opt.url: QDesktopServices.openUrl(QUrl(url))
            )

        button.setMenu(menu)

    @staticmethod
    def _phase_from_log_message(message: str) -> str | None:
        low = message.lower()
        if "checking for duplicate" in low:
            return "Checking duplicates"
        if "duplicate check done" in low:
            return "Finishing up"
        if "extracting" in low and ".zip" in low:
            return "Extracting ZIPs"
        if "reusing" in low and "staged" in low:
            return "Loading staging"
        if "matched" in low and "json" in low:
            return "Matching to dates & GPS"
        if "parallel:" in low or "video encoding:" in low:
            return "Preparing workers"
        if "processing complete" in low:
            return "Complete"
        if "merging" in low or re.search(r"processing \d+/\d+", low):
            return "Merging & saving"
        if "loaded" in low and "json" in low:
            return "Reading export data"
        return None

    @staticmethod
    def _format_elapsed_short(seconds: float) -> str:
        if seconds < 60:
            return f"{int(seconds)} sec"
        if seconds < 3600:
            return f"{int(seconds // 60)} min {int(seconds % 60)} sec"
        return f"{int(seconds // 3600)} hr {int((seconds % 3600) // 60)} min"

    def _show_run_dashboard(self, *, reset: bool = False) -> None:
        if not hasattr(self, "live_run_dashboard"):
            return
        self.debug_output_toggle.setChecked(True)
        self.live_run_dashboard.setVisible(True)
        if reset:
            self.live_run_dashboard.reset(planned_estimate=self._last_estimate_label)
            for line in self._run_log_buffer:
                self.live_run_dashboard.log.appendPlainText(line)

    def _refresh_run_dashboard(
        self,
        *,
        pct: int | None = None,
        files_current: int | None = None,
        files_total: int | None = None,
        speed: str | None = None,
        eta: str | None = None,
        phase: str | None = None,
        status: str | None = None,
        status_kind: str = "info",
    ) -> None:
        if not hasattr(self, "live_run_dashboard"):
            return
        elapsed_str = None
        if getattr(self, "dl_start_time", None):
            import time as _t

            elapsed_str = self._format_elapsed_short(_t.time() - self.dl_start_time)
        self.live_run_dashboard.update_stats(
            pct=pct,
            files_current=files_current,
            files_total=files_total,
            speed=speed,
            eta=eta,
            elapsed=elapsed_str,
            phase=phase or self._run_phase,
            status=status,
            status_kind=status_kind,
        )

    def _apply_dashboard_visibility(self, visible: bool) -> None:
        """Show or fully collapse the live dashboard without stretching the Progress box."""
        if not hasattr(self, 'live_run_dashboard'):
            return
        dash = self.live_run_dashboard
        if visible:
            dash.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Preferred)
            dash.setMinimumHeight(0)
            dash.setMaximumHeight(16777215)
            dash.log.setMinimumHeight(160)
            dash.setVisible(True)
        else:
            dash.setVisible(False)
            dash.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Ignored)
            dash.log.setMinimumHeight(0)
            dash.setMinimumHeight(0)
            dash.setMaximumHeight(0)
        dash.updateGeometry()
        if hasattr(self, 'progress_section'):
            self.progress_section.adjustSize()
            self.progress_section.updateGeometry()

    def toggle_debug_output(self):
        """Toggle visibility of the live run dashboard."""
        visible = self.debug_output_toggle.isChecked()
        self._apply_dashboard_visibility(visible)
        if visible and not self.live_run_dashboard.log.toPlainText():
            self.live_run_dashboard.log.appendPlainText(
                f"[{datetime.now().strftime('%H:%M:%S')}] Live dashboard opened."
            )
            for line in self._run_log_buffer:
                self.live_run_dashboard.log.appendPlainText(line)

    def append_debug_message(self, message: str):
        """Append a message to the live dashboard log and update step hints.

        Kept in full (no in-memory cap) and also mirrored to a per-run log
        file on disk, so a run that lasts hours can still be scrolled back
        to the very start, and remains reviewable even after SMD closes."""
        if not hasattr(self, "live_run_dashboard"):
            return
        timestamp = datetime.now().strftime("%H:%M:%S")
        line = f"[{timestamp}] {message}"
        self._run_log_buffer.append(line)
        self._write_run_log_line(line)

        phase = self._phase_from_log_message(message)
        if phase:
            self._run_phase = phase

        if self.debug_output_toggle.isChecked():
            self.live_run_dashboard.log.appendPlainText(line)
            sb = self.live_run_dashboard.log.verticalScrollBar()
            sb.setValue(sb.maximum())

        short = message.strip()
        if short and not short.startswith("⏳"):
            self._refresh_run_dashboard(status=short[:240], phase=phase, status_kind="info")

    def _write_run_log_line(self, line: str) -> None:
        """Append one line to this run's on-disk activity log, if open."""
        path = getattr(self, '_run_log_path', None)
        if not path:
            return
        try:
            with open(path, 'a', encoding='utf-8') as f:
                f.write(line + '\n')
        except OSError:
            self._run_log_path = None

    def restore_account_name_field(self):
        """Restore last project name as plain text (no scrollable dropdown)."""
        try:
            settings = QSettings('SnapchatMemories', 'Downloader')
            recent = settings.value('recent_accounts', [])
            if isinstance(recent, list) and recent:
                last = recent[-1]
                if isinstance(last, str) and last.strip():
                    self.account_input.setText(last.strip())
                    return
            accounts_dir = Path(self.get_download_base_dir()) / 'accounts'
            if accounts_dir.exists():
                dirs = sorted(
                    (d.name for d in accounts_dir.iterdir() if d.is_dir()),
                    key=str.lower,
                )
                if len(dirs) == 1:
                    self.account_input.setText(dirs[0])
        except Exception:
            pass

    def remember_account_name(self, name):
        """Store account name in settings."""
        try:
            name = name.strip()
            if not name:
                return
            self.account_input.setText(name)

            settings = QSettings('SnapchatMemories', 'Downloader')
            recent = settings.value('recent_accounts', [])
            if not isinstance(recent, list):
                recent = []
            if name in recent:
                recent.remove(name)
            recent.append(name)
            if len(recent) > 10:
                recent = recent[-10:]
            settings.setValue('recent_accounts', recent)
        except Exception:
            pass

        self.update_download_path_label(name)

    def start_download(self):
        # Validate inputs
        if not self.selected_zip:
            QMessageBox.warning(self, 'Error', 'Please select a Snapchat export ZIP or folder')
            return
        account_name = self._account_name()
        if not account_name:
            QMessageBox.warning(self, 'Error', 'Please enter a project folder name')
            return
        if not self._is_valid_account_name(account_name):
            QMessageBox.warning(
                self,
                'Error',
                'Project folder name cannot contain \\ / : * ? " < > |',
            )
            return

        # Remember account name for future sessions
        self.remember_account_name(account_name)
        self.update_download_path_label(account_name)

        try:
            from smd.export_detect import analyze_zip_export, extract_json_from_zips, ExportFormat

            seed_path = Path(self.selected_zip)
            if not seed_path.exists():
                QMessageBox.warning(self, 'Error', 'Selected path does not exist')
                return
            if seed_path.is_file() and seed_path.suffix.lower() != '.zip':
                QMessageBox.warning(self, 'Error', 'Selected file must be a .zip (or choose a folder)')
                return

            analysis = getattr(self, 'export_analysis', None) or analyze_zip_export(seed_path)
            self.export_analysis = analysis

            is_bundled = analysis.format == ExportFormat.BUNDLED_LOCAL
            if not is_bundled:
                QMessageBox.warning(
                    self,
                    'Export not supported',
                    'This export does not include media files inside the ZIP.\n\n'
                    'Request a new Snapchat data export from Snapchat with memories included.',
                )
                return

            paths = self._account_paths(account_name, create=True)
            dest_json = paths.json_path

            if analysis.zip_paths:
                extract_json_from_zips(analysis.zip_paths, dest_json)
            elif seed_path.is_dir():
                candidate = seed_path / 'json' / 'memories_history.json'
                if candidate.exists():
                    shutil.copy2(candidate, dest_json)
                else:
                    QMessageBox.critical(self, 'Error', 'memories_history.json not found in export.')
                    return
            else:
                temp_dir = ROOT / '.temp_import_gui'
                if temp_dir.exists():
                    shutil.rmtree(temp_dir, ignore_errors=True)
                temp_dir.mkdir(parents=True, exist_ok=True)
                with zipfile.ZipFile(str(seed_path), 'r') as z:
                    mem_member = next((n for n in z.namelist() if n.lower().endswith('memories_history.json')), None)
                    if not mem_member:
                        shutil.rmtree(temp_dir, ignore_errors=True)
                        QMessageBox.critical(self, 'Error', 'memories_history.json is missing from export.')
                        return
                    z.extract(mem_member, str(temp_dir))
                    mem_json = (temp_dir / mem_member).resolve()
                shutil.copy2(mem_json, dest_json)
                shutil.rmtree(temp_dir, ignore_errors=True)

            self.tabs.setCurrentIndex(self._tab_process)
            self.progress_bar.setValue(0)
            self.download_log_lines = []
            self._run_log_buffer = []
            self._run_phase = "Starting"
            self.dl_start_time = None
            self.dl_total_files = 0
            try:
                paths.logs_dir.mkdir(parents=True, exist_ok=True)
                ts = datetime.now().strftime('%Y%m%d_%H%M%S')
                self._run_log_path = paths.logs_dir / f'run_activity_{ts}.log'
            except OSError:
                self._run_log_path = None
            self._show_run_dashboard(reset=True)
            self.append_debug_message(
                f"Performance mode: {self.perf_mode_combo.currentText()}"
            )
            self.download_cancelled = False
            self.download_running = True
            self._refresh_after_processing_actions()
            self.download_btn.setText('Cancel')
            self.download_btn.setToolTip('Stop the current operation.')
            self._set_run_lockout(True)
            self._set_keep_awake(True)

            merge_overlays = True
            keep_raw = self.save_raw_chk.isChecked()
            if keep_raw and not self._technical_view_enabled():
                from smd.account_layout import migrate_flat_library_to_subfolders

                migrate_flat_library_to_subfolders(paths.library_root)

            self._apply_status(self.status_label, 'Bundled export detected. Processing locally (offline).', 'info')
            outputs = ['with filters']
            if keep_raw:
                outputs.append('originals without filters')
            self.mode_status_label.setText(
                f'Mode: Bundled local • outputs: {", ".join(outputs)} • metadata and GPS'
            )
            self.step_status_label.setText('Step 1 of 5: preparing export and JSON')
            QApplication.processEvents()

            self.local_export_worker = LocalExportWorker(
                seed_path=seed_path,
                account_dir=paths.account_dir,
                json_path=dest_json,
                merge_overlays=merge_overlays,
                keep_raw=keep_raw,
                repair_videos=True,
                performance_mode=self.performance_mode,
                zip_paths=analysis.zip_paths,
                paths=paths,
            )
            self.local_export_worker.limit = 0
            self.local_export_worker.output.connect(self.on_download_output)
            self.local_export_worker.progress.connect(self.on_local_progress)
            self.local_export_worker.finished.connect(self.on_download_finished)
            self.local_export_worker.start()
        except Exception as e:
            self.download_running = False
            self.download_btn.setText('Start full processing')
            self._refresh_after_processing_actions()
            self._set_run_lockout(False)
            self._set_keep_awake(False)
            QMessageBox.critical(self, 'Error', str(e))

    def on_local_progress(self, current, total):
        import time as _t

        if total > 0:
            pct = int(current / total * 100)
            self.progress_bar.setValue(pct)
            self._apply_status(
                self.status_label,
                f'Merging and saving… {current:,} of {total:,}',
                'info',
            )
            self.step_status_label.setText(f'Step 3 of 5: merging and saving ({pct}%)')
            if self.dl_start_time is None and current > 0:
                self.dl_start_time = _t.time()
                self.dl_total_files = total
            eta_str = '-'
            speed_str = '-'
            if self.dl_start_time and current > 0:
                elapsed = _t.time() - self.dl_start_time
                rate = current / elapsed
                speed_str = f'{rate:.1f} files/s'
                remaining = max(total - current, 0)
                eta_sec = remaining / rate if rate > 0 else 0
                if eta_sec > 3600:
                    eta_str = f'{int(eta_sec // 3600)} hr {int((eta_sec % 3600) // 60)} min'
                elif eta_sec > 60:
                    eta_str = f'{int(eta_sec // 60)} min {int(eta_sec % 60)} sec'
                else:
                    eta_str = f'{int(eta_sec)} sec'
            self.download_details.setText(
                f'Files: {current:,}/{total:,} | Speed: {speed_str} | ETA: {eta_str}'
            )
            self.mode_status_label.setText(
                f'Mode: Bundled local | Progress: {current:,}/{total:,} | ETA: {eta_str}'
            )
            self._refresh_run_dashboard(
                pct=pct,
                files_current=current,
                files_total=total,
                speed=speed_str,
                eta=eta_str,
                phase="Merging & saving",
                status=f"Merging and saving… {current:,} of {total:,}",
            )

    def on_download_output(self, line):
        """Append worker log lines to the live dashboard."""
        try:
            self.download_log_lines.append(line)
            if len(self.download_log_lines) > 50:
                self.download_log_lines.pop(0)
            self.append_debug_message(line)
        except Exception:
            pass

    def on_download_finished(self, return_code):
        """Handle download/completion"""
        self.download_running = False
        self.update_export_ui_mode()
        self._refresh_after_processing_actions()
        self._set_run_lockout(False)
        self.download_btn.setText('Start full processing')
        self.download_btn.setToolTip("Runs extract, merge, metadata, and reports in one flow")
        bundled = getattr(self, 'export_analysis', None) and getattr(self.export_analysis, 'is_bundled', False)
        if return_code == 0:
            self.progress_bar.setValue(100)
            msg = 'Processing completed successfully!'
            self._apply_status(self.status_label, msg, "ok")
            self._refresh_run_dashboard(
                pct=100,
                phase="Complete",
                status=msg,
                status_kind="ok",
            )
            try:
                play_happy_tone()
            except Exception:
                pass
            self._show_completion_summary()
        else:
            # Success continues into verification/finalize below, which still
            # needs the display kept awake - only release it here on the
            # cancelled/failed path, where no further background work runs.
            self._set_keep_awake(False)
            if getattr(self, 'download_cancelled', False):
                self._apply_status(self.status_label, '⏹ Stopped. Click Start to resume with the same account name.', "warn")
            else:
                tail = '\n'.join(self.download_log_lines[-12:]) if self.download_log_lines else 'No output was captured.'
                tail_low = tail.lower()
                title = 'Processing Failed'

                if 'no space left' in tail_low or 'errno 28' in tail_low:
                    title = 'Out of disk space'
                    error_msg = (
                        'Your disk ran out of space while processing.\n\n'
                        'Free up space on the output drive - merged/, raw/, and '
                        'technical/staging/ can be very large for big exports - then click '
                        'Start again with the same project name. SMD resumes where it left '
                        'off and only processes the files that remain.'
                    )
                elif 'permission' in tail_low:
                    error_msg = 'The app does not have permission to access that folder.\n\nCheck Windows security settings and try again.'
                elif 'no module named' in tail_low or 'cannot import name' in tail_low:
                    error_msg = (
                        'Processing is not available in this copy of SMD.\n\n'
                        'Please install the latest version of Snapchat Memories Downloader.'
                    )
                else:
                    error_msg = (
                        'Processing failed.\n\n'
                        'Details from log:\n' + tail + '\n\n'
                        'Tips: free disk space on the output drive, close other heavy apps, '
                        'and try again with the same project name.'
                    )

                self._apply_status(self.status_label, 'Processing failed - see details in the log.', "err")
                try:
                    QMessageBox.critical(self, title, error_msg)
                except Exception:
                    pass

    def cancel_download(self):
        """Cancel the running processing job."""
        try:
            if hasattr(self, 'local_export_worker') and self.local_export_worker.isRunning():
                self.download_cancelled = True
                self.local_export_worker.cancel()
                self._apply_status(self.status_label, 'Cancelling processing...', "warn")
        except Exception:
            pass

    def _stop_worker(self, attr: str, timeout_ms: int = 3000) -> None:
        """Stop and detach a previous QThread worker before starting a replacement.

        Prevents stale threads from emitting into shared slots (double map
        renders, crossed progress updates) and shutdown crashes.
        """
        worker = getattr(self, attr, None)
        if worker is None:
            return
        try:
            if worker.isRunning():
                if hasattr(worker, 'cancel'):
                    worker.cancel()
                elif hasattr(worker, 'cancelled'):
                    worker.cancelled = True
                worker.wait(timeout_ms)
            try:
                worker.disconnect()
            except TypeError:
                pass
        except RuntimeError:
            pass  # C++ object already deleted

    def on_download_button_clicked(self):
        """Unified Start/Cancel behavior on single button."""
        if not self.download_running:
            self.start_download()
        else:
            self.cancel_download()
