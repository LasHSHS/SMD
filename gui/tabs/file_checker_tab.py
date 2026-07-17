"""File Checker tab mixin: folder scan, GPS map, metadata summary."""
from __future__ import annotations

import os
from datetime import datetime
from pathlib import Path

from PyQt5.QtCore import Qt, QTimer, QUrl
from PyQt5.QtGui import QDesktopServices
from PyQt5.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QPushButton, QLabel, QProgressBar,
    QTextEdit, QFrame, QSizePolicy, QMessageBox, QFileDialog,
)

from gui.common import ROOT, WEB_ENGINE_AVAILABLE, QWebEngineView
from gui.widgets import MediaViewer
from gui.workers import MapRenderWorker, MapWorker, ScanWorker, _create_themed_map, generate_thumbnail_base64 as _generate_thumbnail_base64
from smd.grip_splitter import ResultsGripSplitter


class FileCheckerTabMixin:
    """Mixin: File Checker tab (report-only scan + GPS map)."""

    def _add_file_checker_tab(self) -> None:
        # --- Tab 3: File Checker ---
        from smd.theme import SECTION_GAP

        scan_tab = self._make_tab_page()
        scan_layout = QVBoxLayout(scan_tab)
        scan_layout.setContentsMargins(0, SECTION_GAP, 0, 0)
        scan_layout.setSpacing(12)

        map_toolbar = QHBoxLayout()
        map_toolbar.setSpacing(8)
        self.scan_btn = QPushButton('Check folder')
        self.scan_btn.setObjectName('accentBtn')
        self.scan_btn.setToolTip(
            'Pick a folder to check file extensions, view metadata, and build a GPS map. '
            'Read-only - nothing is renamed or modified. Defaults to merged/ when a project exists.'
        )
        self.scan_btn.clicked.connect(self.select_scan_folder)
        map_toolbar.addWidget(self.scan_btn)
        self.cancel_map_btn = QPushButton('Cancel')
        self.cancel_map_btn.setObjectName('toolbarBtn')
        self.cancel_map_btn.clicked.connect(self.cancel_map_scan)
        self.cancel_map_btn.setVisible(False)
        map_toolbar.addWidget(self.cancel_map_btn)
        map_toolbar.addStretch()
        scan_layout.addLayout(map_toolbar)

        self.scan_label = QLabel('No folder selected')
        self.scan_label.setProperty('class', 'muted')
        scan_layout.addWidget(self.scan_label)

        self.scan_hint = QLabel(
            'Tip: check merged/ for finished files, or raw/ for originals without filters.'
        )
        self.scan_hint.setProperty('class', 'caption')
        self.scan_hint.setWordWrap(True)
        scan_layout.addWidget(self.scan_hint)

        self.unified_progress = QProgressBar()
        self.unified_progress.setRange(0, 100)
        self.unified_progress.setValue(0)
        scan_layout.addWidget(self.unified_progress)

        self.unified_status = QLabel('Choose a folder to check your files')
        self.unified_status.setWordWrap(True)
        from smd.theme import apply_status_property
        apply_status_property(self.unified_status, 'info')
        scan_layout.addWidget(self.unified_status)

        self.detailed_status = QLabel('')
        self.detailed_status.setObjectName('detailed_status')
        self.detailed_status.setWordWrap(True)
        self.detailed_status.setMinimumHeight(60)
        self.detailed_status.setVisible(False)
        scan_layout.addWidget(self.detailed_status)

        self.results_panels = ResultsGripSplitter()
        self.results_panels.setObjectName('resultsPanels')

        results_stats_widget = QFrame()
        results_stats_widget.setObjectName('contentPanel')
        from smd.theme import enable_styled_surface

        enable_styled_surface(results_stats_widget)
        results_stats_layout = QVBoxLayout(results_stats_widget)
        results_stats_layout.setContentsMargins(12, 12, 12, 12)
        dash_header = QLabel('Metadata summary')
        dash_header.setProperty('class', 'sectionHeader')
        results_stats_layout.addWidget(dash_header)
        self.scan_output = QTextEdit()
        self.scan_output.setObjectName('consoleLog')
        self.scan_output.setReadOnly(True)
        results_stats_layout.addWidget(self.scan_output)
        results_stats_widget.setMinimumWidth(200)
        self.results_panels.addWidget(results_stats_widget)

        map_widget = QFrame()
        map_widget.setObjectName('contentPanel')
        enable_styled_surface(map_widget)
        self._map_layout = QHBoxLayout(map_widget)
        self._map_layout.setContentsMargins(8, 8, 8, 8)
        # QWebEngineView spins up Qt's whole embedded-Chromium subsystem
        # (separate GPU/network helper processes, disk cache setup) - by far
        # the single most expensive thing App startup does, and it's only
        # ever needed by this one tab. Building it eagerly here made every
        # launch pay that cost even for users who never open File Checker.
        # A cheap placeholder goes in its place; _ensure_map_view() swaps in
        # the real widget lazily, the first time it's actually needed.
        self.map_view = None
        self._map_placeholder = QLabel('Map loads when you open this tab…')
        self._map_placeholder.setAlignment(Qt.AlignCenter)
        self._map_placeholder.setProperty('class', 'muted')
        self._map_layout.addWidget(self._map_placeholder, 1)
        self.media_viewer = MediaViewer()
        self.media_viewer.setMinimumWidth(180)
        self.media_viewer.setMaximumWidth(320)
        self.media_viewer.setVisible(False)
        self._map_layout.addWidget(self.media_viewer)
        map_widget.setMinimumWidth(240)
        self.results_panels.addWidget(map_widget)

        self.results_panels.setStretchFactor(0, 2)
        self.results_panels.setStretchFactor(1, 3)
        scan_layout.addWidget(self.results_panels, 1)

        self.tabs.addTab(scan_tab, 'File Checker')


    def _ensure_map_view(self) -> None:
        """Lazily create the real map widget (QWebEngineView) on first need.

        See the comment where self.map_view is set to None in init_ui for
        why this is deferred instead of built eagerly at startup.
        """
        if self.map_view is not None:
            return
        if WEB_ENGINE_AVAILABLE and QWebEngineView is not None:
            self.map_view = QWebEngineView()
        else:
            self.map_view = QTextBrowser()
            self.map_view.setOpenExternalLinks(True)
            self.map_view.setHtml(
                "<h3>GPS Map requires Qt WebEngine</h3>"
                "<p>The map will open in your default browser after rendering.</p>"
            )
        self._map_layout.replaceWidget(self._map_placeholder, self.map_view)
        self._map_placeholder.deleteLater()
        self._map_layout.setStretch(0, 1)
        if WEB_ENGINE_AVAILABLE and isinstance(self.map_view, QWebEngineView):
            # Give the freshly-created WebEngineView something to show;
            # previously this ran unconditionally 200ms after startup.
            QTimer.singleShot(0, self.init_default_map)

    def init_default_map(self):
        """Initialize map with a default view"""
        import folium
        
        # Create a default map centered on Copenhagen, Denmark
        copenhagen_center = [55.6761, 12.5683]
        dark = bool(getattr(self, 'dark_mode_enabled', False))
        m = _create_themed_map(copenhagen_center, 11, dark=dark)
        
        # Add instruction marker
        folium.Marker(
            location=copenhagen_center,
            popup=folium.Popup(
                "<div style='text-align:center;'><b>GPS Map</b><br><br>"
                "Default view: Copenhagen, Denmark<br><br>"
                "Click <b>'Load GPS Map'</b> to scan<br>"
                "your media folder and display<br>"
                "all photos/videos with GPS here.</div>",
                max_width=250
            ),
            tooltip="Click 'Load GPS Map' to begin",
            icon=folium.Icon(color='blue', icon='info-sign')
        ).add_to(m)
        
        folium.LayerControl().add_to(m)
        
        # Save and load the map (use a unique filename so QWebEngineView refreshes tiles)
        import tempfile
        temp_file = tempfile.NamedTemporaryFile(delete=False, suffix='.html', mode='w', encoding='utf-8')
        temp_path = temp_file.name
        temp_file.close()
        m.save(temp_path)
        self._track_map_html_temp(temp_path)

        map_url = QUrl.fromLocalFile(str(Path(temp_path).absolute()))
        if WEB_ENGINE_AVAILABLE and hasattr(self.map_view, 'setUrl'):
            self.map_view.setUrl(map_url)
        else:
            # Without WebEngine, present a clickable link to open in browser
            if hasattr(self.map_view, 'setHtml'):
                safe_link = map_url.toString()
                self.map_view.setHtml(
                    f"<h3>GPS Map (opens in browser)</h3>"
                    f"<p>Click <a href='{safe_link}'>here</a> to open the map in your default browser.</p>"
                )

    def _default_check_folder_dir(self) -> str:
        account_name = self._account_name()
        if account_name:
            merged = self._account_paths(account_name).merged_dir
            if merged.is_dir() and any(merged.iterdir()):
                return str(merged)
        for candidate in (Path.home() / 'Pictures', Path.home() / 'Downloads', Path.home()):
            if candidate.exists():
                return str(candidate)
        return str(Path.home())

    def _mapping_json_for_scan(self, folder: str | None = None) -> str | None:
        """Resolve memories_history.json for map GPS (manual pick, account, or folder walk)."""
        from smd.map_gps import resolve_memories_json

        if self.json_path_for_mapping and Path(self.json_path_for_mapping).exists():
            return self.json_path_for_mapping

        resolved = resolve_memories_json(folder)
        if resolved is not None:
            return str(resolved)

        account_name = self._account_name()
        if account_name:
            json_path = self._account_paths(account_name).json_path
            if json_path.is_file():
                return str(json_path)
        return None

    def _start_folder_check(self, folder: str) -> None:
        self.selected_scan = folder
        self.scan_label.setText(Path(folder).name)
        from smd.theme import apply_status_property
        apply_status_property(self.scan_label, 'ok')
        self._apply_status(
            self.unified_status,
            f'Checking folder: {Path(folder).name}...',
            'ok',
        )
        QTimer.singleShot(300, self.run_full_analysis)

    def is_browse_scan_busy(self) -> bool:
        """True while folder check or map render is running."""
        if getattr(self, 'full_analysis_mode', False):
            return True
        for attr in ('scan_worker', 'map_worker', 'map_render_worker'):
            worker = getattr(self, attr, None)
            if worker is not None and worker.isRunning():
                return True
        return False

    def _set_browse_scan_busy(self, busy: bool):
        """Enable/disable browse-tab controls during long operations."""
        self.scan_btn.setEnabled(not busy)
        if hasattr(self, 'cancel_map_btn'):
            self.cancel_map_btn.setVisible(busy)

    def select_scan_folder(self):
        if self.is_browse_scan_busy():
            QMessageBox.information(
                self,
                'Scan running',
                'Wait for the current scan to finish.',
            )
            return
        folder = QFileDialog.getExistingDirectory(
            self,
            'Select folder to check',
            self._default_check_folder_dir(),
        )
        if folder:
            self._start_folder_check(folder)

    def _start_map_worker(self, *, full_workflow: bool = False) -> None:
        """Start media + GPS scan (after extension fix when part of full workflow)."""
        self.cancel_map_btn.setVisible(True)
        self.operation_start_time = None
        self.processing_speeds = []
        self.current_file_being_processed = ''

        self._stop_worker('map_worker')
        self.map_worker = MapWorker(
            self.selected_scan,
            self,
            self._mapping_json_for_scan(self.selected_scan),
        )
        self.map_worker.progress.connect(self.on_map_progress)
        self.map_worker.error.connect(self.on_map_error)
        self.map_worker.file_detail.connect(self.on_map_file_detail)
        if full_workflow:
            self.map_worker.finished.connect(self.on_map_finished_full_workflow)
        else:
            self.map_worker.finished.connect(self.on_map_finished)
        self.map_worker.start()
        self.start_status_animation('Scanning media files...')

    def generate_thumbnail_base64(self, media_path, max_size=150):
        """Generate a base64 encoded thumbnail for map preview (photo or video)."""
        return _generate_thumbnail_base64(media_path, max_size)

    def on_map_error(self, error_msg):
        """Handle map scanning errors"""
        self.stop_status_animation()
        self.scan_btn.setEnabled(True)
        self.cancel_map_btn.setVisible(False)
        self._set_browse_scan_busy(False)
        self.full_analysis_mode = False
        self._apply_status(self.unified_status, f'Error: {error_msg}', 'err')
        if 'cancel' not in error_msg.lower():
            QMessageBox.warning(self, 'Check Error', error_msg)

    def on_map_finished(self, locations, total_images, total_videos):
        """Handle completion of GPS scanning and start map rendering."""
        try:
            self.stop_status_animation()
            self.scan_btn.setEnabled(True)
            self.cancel_map_btn.setVisible(False)

            scan_report = getattr(self.map_worker, 'scan_report', {})
            self._apply_scan_report(locations, scan_report)
            total_scanned = total_images + total_videos

            if not locations:
                self._apply_status(
                    self.unified_status,
                    f'Checked {total_scanned} files ({total_images} photos, {total_videos} videos) — no GPS found',
                    'warn',
                )
                self.unified_progress.setValue(100)
                return

            self.unified_progress.setValue(50)
            self.start_status_animation('Rendering map with markers...')
            self._last_map_locations = locations

            self._stop_worker('map_render_worker')
            self.map_render_worker = MapRenderWorker(
                locations,
                dark_mode=bool(getattr(self, 'dark_mode_enabled', False)),
            )
            self.map_render_worker.progress.connect(self.on_map_render_progress)
            self.map_render_worker.finished.connect(self.on_map_render_finished)
            self.map_render_worker.error.connect(self.on_map_render_error)
            self.map_render_worker.start()

        except Exception as e:
            self._apply_status(self.unified_status, f'Error starting map render: {str(e)}', 'err')
            QMessageBox.critical(self, 'Map Error', f'Failed to start map rendering:\n\n{str(e)}')

    def on_map_file_detail(self, filename, status, metadata):
        """Update detailed view with current file being processed."""
        if self.show_detailed_view:
            self.current_file_being_processed = filename

            size_str = f"{metadata.get('size_mb', 0):.2f} MB"
            modified = metadata.get('modified', 'unknown')
            file_type = metadata.get('type', '').upper()

            if status == 'found':
                lat = metadata.get('lat', 'N/A')
                lon = metadata.get('lon', 'N/A')
                source = metadata.get('gps_source', 'embedded')
                detail_text = (
                    f"GPS FOUND ({source}): {filename}\n"
                    f"   📍 Coordinates: {lat}, {lon}\n"
                    f"   📄 Size: {size_str} | 📅 Modified: {modified} | 📦 Type: {file_type}"
                )
            elif status == 'no-gps':
                detail_text = (
                    f"⚪ NO GPS: {filename}\n"
                    f"   📄 Size: {size_str} | 📅 Modified: {modified} | 📦 Type: {file_type}"
                )
            else:
                detail_text = f"Checking: {filename} ({size_str})"

            if not self.operation_start_time:
                self.operation_start_time = datetime.now()

    def cancel_map_scan(self):
        """Cancel every stage of the check-folder workflow (rename, scan, render)."""
        cancelled_any = False
        for attr in ('scan_worker', 'map_worker', 'map_render_worker'):
            worker = getattr(self, attr, None)
            try:
                if worker is not None and worker.isRunning():
                    if hasattr(worker, 'cancel'):
                        worker.cancel()
                    else:
                        worker.cancelled = True
                    cancelled_any = True
            except RuntimeError:
                pass
        if cancelled_any:
            self.stop_status_animation()
            self._apply_status(self.unified_status, 'Cancelling scan...', "warn")

    def on_map_progress(self, current, total, found, eta, speed):
        """Update map scan progress"""
        self._last_map_scan_total = total
        progress = int((current / total) * 100)
        self.unified_progress.setValue(progress)
        base_text = f'Scanning {current}/{total} files... {found} with GPS found ({progress}%) • ETA: {eta}'
        
        if self.status_animation_active:
            self.status_base_text = base_text
        else:
            self.start_status_animation(base_text)
        
        # Update detailed view with comprehensive stats
        if self.show_detailed_view:
            if not self.operation_start_time:
                self.operation_start_time = datetime.now()
            
            elapsed = (datetime.now() - self.operation_start_time).total_seconds()
            elapsed_str = str(timedelta(seconds=int(elapsed)))
            
            self.processing_speeds.append(speed)
            avg_speed = sum(self.processing_speeds[-20:]) / min(20, len(self.processing_speeds))
            
            detailed_text = (
                f"⌛ Elapsed: {elapsed_str} | Speed: {speed:.1f} files/sec (avg: {avg_speed:.1f})\n"
                f"📊 Progress: {current}/{total} ({progress}%) | 📍 GPS Found: {found} ({(found/current*100) if current > 0 else 0:.1f}%)\n"
                f"⏱️ ETA: {eta} | Current: {self.current_file_being_processed[:50]}..."
            )
            self.detailed_status.setText(detailed_text)

    def on_map_render_progress(self, progress, status_text):
        """Update progress during map rendering"""
        self.unified_progress.setValue(progress)
        # Only update base text if animation is active
        if self.status_animation_active:
            self.status_base_text = status_text
        else:
            self._apply_status(self.unified_status, status_text, "info")

    def on_map_render_finished(self, html_file_path):
        """Handle map rendering completion"""
        print("DEBUG: on_map_render_finished called")
        try:
            self._ensure_map_view()
            print(f"DEBUG: Map file path: {html_file_path}")
            self._track_map_html_temp(html_file_path)
            self.stop_status_animation()
            self.unified_progress.setValue(100)
            
            print("DEBUG: Creating QUrl from file path...")
            file_url = QUrl.fromLocalFile(html_file_path)
            print(f"DEBUG: Loading rendered map from: {file_url.toString()}")

            if WEB_ENGINE_AVAILABLE and hasattr(self.map_view, 'setUrl'):
                # Load map in embedded view
                self.map_view.setUrl(file_url)
                print("DEBUG: Map URL set in QWebEngineView")

                # Start polling for file open requests from the map
                if not hasattr(self, 'map_poll_timer'):
                    self.map_poll_timer = QTimer()
                    self.map_poll_timer.timeout.connect(self.check_map_file_open)
                    self.map_poll_timer.start(200)  # Check every 200ms
            else:
                # Fallback: open in default browser
                QDesktopServices.openUrl(file_url)
                if hasattr(self.map_view, 'setHtml'):
                    safe_link = file_url.toString()
                    self.map_view.setHtml(
                        f"<h3>GPS Map opened in your browser</h3>"
                        f"<p>If it didn't open automatically, click <a href='{safe_link}'>here</a>.</p>"
                    )
            
            # Get location count
            total_files = len(self.map_render_worker.locations) if hasattr(self.map_render_worker, 'locations') else 0
            print(f"DEBUG: Total files with GPS: {total_files}")
            
            # Handle full workflow completion
            if self.full_analysis_mode:
                status_text = (
                    f'Check complete — {total_files} files with GPS on the map'
                )
                self._apply_status(self.unified_status, status_text, "ok")
                self.unified_progress.setValue(100)
                self.full_analysis_mode = False
                self._set_browse_scan_busy(False)
            else:
                status_text = (
                    f'Map loaded — {total_files} files with GPS data'
                )
                self._apply_status(self.unified_status, status_text, "ok")
                self.unified_progress.setValue(100)
            play_happy_tone()
            
            # Hide cancel button after completion
            self.cancel_map_btn.setVisible(False)
            print("DEBUG: on_map_render_finished completed successfully")
            
        except Exception as e:
            print(f"ERROR in on_map_render_finished: {e}")
            import traceback
            traceback.print_exc()
            self._apply_status(self.unified_status, f'Error loading map: {str(e)}', 'err')
            self._set_browse_scan_busy(False)
            QMessageBox.critical(self, 'Map Error', f'Failed to display map:\n\n{str(e)}')

    def check_map_file_open(self):
        """Check if map requested to open a file"""
        if not WEB_ENGINE_AVAILABLE:
            return
        try:
            # Get and clear pyOpenFile in one atomic operation
            self.map_view.page().runJavaScript(
                "if (window.pyOpenFile) { var p = window.pyOpenFile; window.pyOpenFile = null; p; } else { null; }",
                self.handle_file_open_request
            )
        except Exception as e:
            pass

    def handle_file_open_request(self, file_path):
        """Handle file open request from map"""
        if file_path and isinstance(file_path, str) and file_path != 'null':
            try:
                # Normalize path back to Windows format
                file_path = file_path.replace('/', '\\')
                print(f"DEBUG: Opening file from map: {file_path}")
                if os.path.exists(file_path):
                    self.fullscreen_popup.open_file(file_path)
                else:
                    print(f"ERROR: File not found: {file_path}")
                    QMessageBox.warning(self, 'Error', f'File not found:\n{file_path}')
            except Exception as e:
                print(f"ERROR: Error opening file: {e}")
                import traceback
                traceback.print_exc()
                QMessageBox.warning(self, 'Error', f'Could not open file:\n{str(e)}')

    def on_map_render_error(self, error_msg):
        """Handle map rendering error with friendly message"""
        print(f"ERROR: Map rendering error: {error_msg}")
        self.stop_status_animation()
        
        # Convert technical error to user-friendly message
        if 'connect' in error_msg.lower() or 'network' in error_msg.lower() or 'timeout' in error_msg.lower():
            friendly_msg = "Unable to load map. Please check your internet connection and try again."
        elif 'tile' in error_msg.lower() or 'openstreetmap' in error_msg.lower():
            friendly_msg = "Map service is temporarily unavailable. Please check your internet connection and try again later."
        else:
            friendly_msg = error_msg
        
        self._apply_status(self.unified_status, f'Error: Map Error: Please check internet', "err")
        self.unified_progress.setValue(100)
        self._set_browse_scan_busy(False)
        self.full_analysis_mode = False
        QMessageBox.critical(self, 'Map Error', friendly_msg)

    def _append_media_stats(self, scan_report: dict, folder_name: str) -> None:
        """Append media-only folder statistics from MapWorker scan report."""
        from smd.media_types import format_bytes

        file_types = scan_report.get('file_types') or {}
        total_media = scan_report.get('total_media', 0)
        total_images = scan_report.get('total_images', 0)
        total_videos = scan_report.get('total_videos', 0)
        total_size = sum(info.get('size', 0) for info in file_types.values())
        mismatches = scan_report.get('extension_mismatches', 0)
        resolution_counts = scan_report.get('resolution_counts') or {}

        output = "\n" + "=" * 60 + "\n"
        output += "📊 MEDIA STATISTICS\n"
        output += "=" * 60 + "\n"
        output += f"📁 Folder: {folder_name}\n"
        output += f"📊 Media files: {total_media:,} ({total_images:,} photos, {total_videos:,} videos)\n"
        output += f"💾 Total size: {format_bytes(total_size)}\n"
        if mismatches:
            output += (
                f"⚠ Mismatched extension: {mismatches:,} "
                "(read-only report - re-run \"Save memories\" processing to fix these)\n"
            )
        if resolution_counts:
            # Not "which phone" - Snapchat strips Make/Model camera tags from
            # every exported photo and video (verified empirically), so that
            # can't be shown truthfully. Resolution is real, present data and
            # a reasonable rough proxy for "how many different screens/devices".
            ranked = sorted(resolution_counts.items(), key=lambda kv: kv[1], reverse=True)
            top_res, top_count = ranked[0]
            output += (
                f"📐 Photo resolutions: {len(ranked)} unique "
                f"(most common: {top_res} - {top_count:,} photo(s))\n"
            )
        output += "\n" + "─" * 60 + "\n"
        output += "📂 File types:\n"
        output += "─" * 60 + "\n"
        for ext, info in sorted(file_types.items(), key=lambda x: x[1]['count'], reverse=True):
            output += f"  {ext:15} | {info['count']:6,} files | {format_bytes(info['size']):>12}\n"
        output += "=" * 60 + "\n"
        self.scan_output.append(output)

    def _append_gps_summary(self, locations, scan_report: dict | None = None) -> None:
        """Append GPS counts with embedded vs JSON breakdown."""
        report = scan_report or {}
        embedded = report.get('gps_embedded') or {}
        json_gps = report.get('gps_json') or {}
        missing = report.get('gps_missing') or {}

        emb_photos = embedded.get('image', 0)
        emb_videos = embedded.get('video', 0)
        json_photos = json_gps.get('image', 0)
        json_videos = json_gps.get('video', 0)
        miss_photos = missing.get('image', 0)
        miss_videos = missing.get('video', 0)

        with_gps = emb_photos + emb_videos + json_photos + json_videos
        without_gps = miss_photos + miss_videos
        total_scanned = report.get('total_media') or (with_gps + without_gps) or len(locations)

        try:
            unique_locs = len({
                (round(loc['coords'][0], 4), round(loc['coords'][1], 4))
                for loc in locations
                if loc.get('coords')
            })
        except Exception:
            unique_locs = 0

        output = "\n" + "=" * 60 + "\n"
        output += "📍 GPS METADATA\n"
        output += "=" * 60 + "\n"
        output += f"✓ Files with GPS: {with_gps:,}\n"
        output += f"   • Embedded in file: {emb_photos + emb_videos:,} ({emb_photos:,} photos, {emb_videos:,} videos)\n"
        if json_photos or json_videos:
            output += f"   • From export JSON: {json_photos + json_videos:,} ({json_photos:,} photos, {json_videos:,} videos)\n"
        output += f"✗ Files without GPS: {without_gps:,} ({miss_photos:,} photos, {miss_videos:,} videos)\n"
        output += f"📊 Media files checked: {total_scanned:,}\n"
        output += f"🗺️ Unique locations: {unique_locs:,}\n"
        output += "=" * 60 + "\n"
        self.scan_output.append(output)

    def _apply_scan_report(self, locations, scan_report: dict | None) -> None:
        """Write media stats and GPS summary from a completed MapWorker run."""
        report = dict(scan_report or {})
        folder_name = Path(self.selected_scan).name if self.selected_scan else ''
        self._append_media_stats(report, folder_name)
        self._append_gps_summary(locations, report)

    def on_scan_output(self, line: str) -> None:
        """Append extension-fixer log lines during Check folder."""
        self.scan_output.append(line)
        scrollbar = self.scan_output.verticalScrollBar()
        scrollbar.setValue(scrollbar.maximum())

    def on_scan_progress(self, value: int) -> None:
        self.unified_progress.setValue(value)
        base_text = f'Checking file extensions... {value}%'
        if self.status_animation_active:
            self.status_base_text = base_text
        else:
            self.start_status_animation(base_text)

    def on_scan_finished_in_full_workflow(self, return_code: int) -> None:
        """After the read-only extension check — continue to GPS scan and map."""
        self.stop_status_animation()
        if return_code != 0:
            self._apply_status(self.unified_status, 'Extension check failed', 'err')
            self.full_analysis_mode = False
            self._set_browse_scan_busy(False)
            return

        mismatched = getattr(self.scan_worker, 'planned_count', 0)
        total = getattr(self.scan_worker, 'total_scanned', 0)
        if mismatched:
            self.scan_output.append(
                f"\n⚠ Found {mismatched} mislabeled file(s) out of {total} checked "
                "(file checker only reports - it never renames anything). If this "
                "folder came from SMD's own \"Save memories\" processing, re-run "
                "processing for this account to have it fix these automatically.\n"
            )
        else:
            self.scan_output.append(f"\n✓ All {total} checked extensions look correct.\n")

        self.unified_progress.setValue(0)
        self._apply_status(self.unified_status, 'Step 2/3: Scanning media and GPS...', 'info')
        self._start_map_worker(full_workflow=True)

    def run_full_analysis(self):
        """Check folder: report extension mismatches (read-only) → media stats + GPS → map.

        File Checker never renames or modifies anything - it's a read-only
        report for any folder, including ones SMD never touched. SMD's own
        "Save memories" processing already fixes mismatched extensions
        automatically for every file it writes (see _fix_extension() in
        smd/local_pipeline.py), so there is nothing left for this tab to fix
        on SMD's own output; this dry-run check exists for older or
        third-party folders that never went through that pipeline."""
        if not self.selected_scan:
            QMessageBox.warning(self, 'Error', 'Please select a folder first')
            return

        self.full_analysis_mode = True
        self._set_browse_scan_busy(True)

        self.scan_output.clear()
        json_path = self._mapping_json_for_scan(self.selected_scan)
        if json_path:
            self.scan_output.append(
                f"GPS lookup: using {Path(json_path).name} for files missing embedded coordinates.\n"
            )
        self.unified_progress.setValue(0)
        self._apply_status(self.unified_status, 'Step 1/3: Checking file extensions...', 'info')

        self._stop_worker('scan_worker')
        self.scan_worker = ScanWorker(self.selected_scan, dry_run=True)
        self.scan_worker.output.connect(self.on_scan_output)
        self.scan_worker.finished.connect(self.on_scan_finished_in_full_workflow)
        self.scan_worker.progress.connect(self.on_scan_progress)
        self.scan_worker.start()

    def on_map_finished_full_workflow(self, locations, total_images, total_videos):
        """After media scan during Check folder — show stats then render map."""
        try:
            self.stop_status_animation()
            scan_report = getattr(self.map_worker, 'scan_report', {})
            self._apply_scan_report(locations, scan_report)

            if not locations:
                self._apply_status(
                    self.unified_status,
                    f'Check complete — {total_images + total_videos} files, no GPS found',
                    'warn',
                )
                self.unified_progress.setValue(100)
                self.full_analysis_mode = False
                self._set_browse_scan_busy(False)
                self.cancel_map_btn.setVisible(False)
                return

            self._apply_status(self.unified_status, 'Step 3/3: Rendering map...', 'info')
            self.unified_progress.setValue(0)
            self.map_data = locations
            self.render_map_data(locations)
        except Exception as e:
            self._apply_status(self.unified_status, f'Error: {e}', 'err')
            self.full_analysis_mode = False
            self._set_browse_scan_busy(False)

    def render_map_data(self, gps_data):
        """Render map from GPS data."""
        try:
            if not gps_data:
                self._apply_status(self.unified_status, 'No GPS data to display on map', 'warn')
                self.full_analysis_mode = False
                self._set_browse_scan_busy(False)
                return

            self.unified_progress.setValue(50)
            self.start_status_animation('Rendering map with markers...')
            self._last_map_locations = gps_data
            self._stop_worker('map_render_worker')
            self.map_render_worker = MapRenderWorker(
                gps_data,
                dark_mode=bool(getattr(self, 'dark_mode_enabled', False)),
            )
            self.map_render_worker.progress.connect(self.on_map_render_progress)
            self.map_render_worker.finished.connect(self.on_map_render_finished)
            self.map_render_worker.error.connect(self.on_map_render_error)
            self.map_render_worker.start()
        except Exception as e:
            self._apply_status(self.unified_status, f'Error rendering map: {str(e)}', 'err')
            self.full_analysis_mode = False
            self._set_browse_scan_busy(False)
