#!/usr/bin/env python3
"""
Snapchat Memories Downloader (SMD) - Desktop GUI
Professional native Windows application for downloading Snapchat memories with GPS embedding

Created by: Las HS (https://github.com/LasHSHS)
License: Open Source
"""

# User-facing name for the main workflow tab (was "Process").
TAB_SAVE_MEMORIES = "Save memories"

import sys
import os

# Under pythonw.exe (no console) sys.stdout / sys.stderr are None. Any print() or
# flush() — including ones triggered inside imported libraries at import time —
# raises AttributeError and kills the app silently before __main__ ever runs.
# Redirect both streams to smd_gui.log (or a null sink) as the very first thing.
if sys.stdout is None or sys.stderr is None:
    try:
        # When frozen (PyInstaller), __file__ resolves inside _internal/, which
        # is regenerated wholesale on every build - write next to the exe
        # instead so runtime logs never get swept into a packaged build.
        _log_dir = (
            os.path.dirname(os.path.abspath(sys.executable))
            if getattr(sys, 'frozen', False)
            else os.path.dirname(os.path.abspath(__file__))
        )
        _early_log = open(
            os.path.join(_log_dir, 'smd_gui.log'),
            'a', encoding='utf-8', buffering=1,
        )
    except OSError:
        import io as _io
        _early_log = _io.StringIO()
    if sys.stdout is None:
        sys.stdout = _early_log
    if sys.stderr is None:
        sys.stderr = _early_log

import subprocess
import json
import re
import zipfile
import shutil
import base64
import html
import socket
import atexit
import psutil
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timedelta, timezone
from PyQt5.QtWidgets import (QApplication, QMainWindow, QWidget, QVBoxLayout, 
                             QHBoxLayout, QPushButton, QLabel, QFileDialog, QLineEdit,
                             QTextEdit, QTextBrowser, QComboBox, QSpinBox, QCheckBox, QTabWidget, QTabBar, QProgressBar, QToolTip, QSizePolicy, QSplashScreen, QGroupBox, QGridLayout,
                             QRadioButton, QButtonGroup, QFrame, QPlainTextEdit, QMenu, QScrollArea, QLayout, QGraphicsOpacityEffect)
from PyQt5.QtCore import Qt, QThread, pyqtSignal, QUrl, QTimer, QObject, pyqtSlot, QSettings, QCoreApplication, QSize, QRect
from PyQt5.QtGui import QFont, QIcon, QColor, QDesktopServices, QCursor, QPixmap, QPainter
from PyQt5.QtWidgets import QMessageBox
from PyQt5.QtWidgets import QDialog
if os.environ.get('SMD_DISABLE_WEBENGINE') == '1':
    QWebEngineView = None  # type: ignore
    WEB_ENGINE_AVAILABLE = False
else:
    try:
        from PyQt5.QtWebEngineWidgets import QWebEngineView  # Optional; excluded in lightweight builds
        WEB_ENGINE_AVAILABLE = True
    except Exception:
        QWebEngineView = None  # type: ignore
        WEB_ENGINE_AVAILABLE = False
from PyQt5.QtMultimediaWidgets import QVideoWidget
from PyQt5.QtMultimedia import QMediaPlayer, QMediaContent
import folium
from folium.plugins import MarkerCluster
from PIL import Image
from PIL.ExifTags import TAGS, GPSTAGS
import tempfile
from smd.grip_splitter import ResultsGripSplitter
from PyQt5.QtCore import QSize

# When frozen (PyInstaller), __file__ resolves inside _internal/, which is
# regenerated wholesale on every build - use the exe's own directory instead.
ROOT = Path(sys.executable).parent if getattr(sys, 'frozen', False) else Path(__file__).parent


def _doc_browser_anchor_clicked(browser: QTextBrowser, url: QUrl) -> None:
    """Scroll in-page for #anchors; open http(s) links externally."""
    scheme = url.scheme().lower()
    if scheme in ('http', 'https', 'mailto'):
        QDesktopServices.openUrl(url)
        return
    fragment = url.fragment()
    if fragment:
        browser.scrollToAnchor(fragment)


def build_help_panel() -> QWidget:
    """Illustrative help - same DocBrowser style as the Guide tab."""
    panel = QWidget()
    lay = QVBoxLayout(panel)
    lay.setContentsMargins(0, 0, 0, 0)
    lay.setSpacing(0)

    from smd.help_content import build_help_html

    browser = DocBrowser()
    browser.setOpenExternalLinks(False)
    browser.setHtml(build_help_html(TAB_SAVE_MEMORIES))
    browser.anchorClicked.connect(lambda url: _doc_browser_anchor_clicked(browser, url))
    lay.addWidget(browser, 1)
    return panel


def build_about_panel() -> QWidget:
    """About tab - version, credits, environment, and component status."""
    panel = QWidget()
    lay = QVBoxLayout(panel)
    lay.setContentsMargins(0, 0, 0, 0)
    lay.setSpacing(0)

    from smd.about_content import build_about_html

    browser = DocBrowser()
    browser.setHtml(build_about_html(web_engine_available=WEB_ENGINE_AVAILABLE))
    browser.anchorClicked.connect(lambda url: QDesktopServices.openUrl(url))
    lay.addWidget(browser, 1)
    return panel


# Optional Windows-only happy tone
try:
    import winsound  # Available on Windows
except Exception:
    winsound = None

def play_happy_tone():
    """Play a short happy completion tone on Windows; no-op elsewhere."""
    try:
        if winsound:
            winsound.Beep(880, 120)
            winsound.Beep(1200, 160)
            winsound.Beep(1500, 140)
    except Exception:
        pass

def friendly_error_message(error_obj):
    """Convert technical Python errors to friendly user messages."""
    error_str = str(error_obj).lower()
    error_type = type(error_obj).__name__
    if 'permission' in error_str or 'permissionerror' in error_type:
        return "The app doesn't have permission to access that folder. Check your Windows settings."
    elif 'connectionerror' in error_type or 'timeout' in error_str or 'connection' in error_str:
        return "Network error. Please check your internet connection and try again."
    elif 'filenotfound' in error_type or 'no such file' in error_str:
        return "File not found. The folder or file may have been moved or deleted."
    elif 'module' in error_str:
        return "A required component is missing. The app download may be corrupted. Please reinstall."
    elif 'invalid' in error_str and 'credential' in error_str:
        return "Invalid Snapchat username or password. Please check and try again."
    elif 'json' in error_str:
        return "The Snapchat data file is corrupted. Please download again."
    else:
        return f"An unexpected error occurred. Please try again. If this persists, contact support."


from gui.dialogs import (
    DuplicateCompareDialog,
    DuplicateReviewDialog,
    SessionSummaryDialog,
)

from gui.widgets import (
    DocBrowser,
    FittedPixmapLabel,
    FlowDocBrowser,
    FlowLayout,
    FullScreenMediaPopup,
    LiveRunDashboard,
    MediaViewer,
    ProcessingShieldOverlay,
    StreamRedirector,
    WidthAwareColumn,
    _MainTabBar,
)

from gui.workers import (
    CompletionFinalizeWorker,
    DuplicatePreviewWorker,
    DuplicateScanWorker,
    LocalExportWorker,
    MapRenderWorker,
    MapWorker,
    ScanWorker,
    StagingCheckWorker,
    StagingVerifyWorker,
    TechnicalStorageWorker,
    _create_themed_map,
    _qpixmap_from_pil,
    generate_thumbnail_base64,
)


def build_guide_panel(go_to_process_cb) -> QWidget:
    """Single-column guide: outer scroll only, text and screenshots stacked vertically."""
    from smd.guide_content import build_guide_html, guide_assets_dir

    panel = QWidget()
    lay = QVBoxLayout(panel)
    lay.setSpacing(12)
    lay.setContentsMargins(0, 0, 0, 0)

    browser = FlowDocBrowser()
    browser.setSearchPaths([str(guide_assets_dir())])
    browser.setHtml(build_guide_html(TAB_SAVE_MEMORIES))
    browser.anchorClicked.connect(lambda url: QDesktopServices.openUrl(url))

    go_btn = QPushButton(f'Go to {TAB_SAVE_MEMORIES}')
    go_btn.setObjectName('accentBtn')
    go_btn.clicked.connect(go_to_process_cb)

    lay.addWidget(browser, 0)
    lay.addWidget(go_btn, 0)
    return panel


class DownloaderGUI(QMainWindow):
    def __init__(self):
        super().__init__()
        # Set window flags to ensure it shows in taskbar
        self.setWindowFlags(Qt.Window | Qt.WindowMinMaxButtonsHint | Qt.WindowCloseButtonHint | Qt.WindowTitleHint)

        self.apply_window_icon()
        self.json_path_for_mapping = None  # Optional JSON for GPS mapping
        self.media_viewer = None  # Will be initialized in init_ui
        self.fullscreen_popup = FullScreenMediaPopup(self)  # Overlay media viewer
        self.dark_mode_enabled = True  # resolved theme is dark
        self._map_html_temp_files: list[Path] = []
        self.init_ui()
        self.processing_shield = ProcessingShieldOverlay(self)
        self.stdout_redirector = StreamRedirector(self.append_debug_message)
        sys.stdout = self.stdout_redirector
        sys.stderr = self.stdout_redirector
        self.run_startup_self_check()
        if getattr(sys, 'frozen', False):
            try:
                import smd.local_pipeline  # noqa: F401
            except ImportError:
                QTimer.singleShot(
                    800,
                    lambda: QMessageBox.warning(
                        self,
                        'Incomplete build',
                        'This copy of SMD cannot process bundled ZIP exports.\n\n'
                        'Reinstall from the official release package.',
                    ),
                )
        
        # Timer to check for show signals from other instances
        self.show_signal_timer = QTimer()
        self.show_signal_timer.timeout.connect(self.check_show_signal)
        self.show_signal_timer.start(100)  # Check every 100ms for faster response
        self.signal_file = Path(tempfile.gettempdir()) / 'snapchat_memories_show.signal'
        
        # Theme: system default, persisted in settings
        self._load_and_apply_theme()
        self._apply_technical_view_ui()

        self._storage_debounce_timer = QTimer(self)
        self._storage_debounce_timer.setSingleShot(True)
        self._storage_debounce_timer.timeout.connect(self._run_technical_storage_scan)
        self._pending_storage_account = ''
        self._storage_scan_generation = 0
        self._duplicate_scan_auto_open = False

    def _technical_view_enabled(self) -> bool:
        return bool(
            getattr(self, 'technical_view_chk', None) and self.technical_view_chk.isChecked()
        )

    def _on_technical_view_changed(self, _state: int = 0) -> None:
        QSettings('SnapchatMemories', 'Downloader').setValue(
            'technical_view', self._technical_view_enabled()
        )
        self._apply_technical_view_ui()
        name = self._account_name()
        if name:
            self.update_download_path_label(name)

    def _on_save_raw_changed(self, _state: int = 0) -> None:
        name = self._account_name()
        if name:
            self.update_download_path_label(name)

    def _on_keep_staging_changed(self, _state: int = 0) -> None:
        QSettings('SnapchatMemories', 'Downloader').setValue(
            'keep_staging_files', self.keep_staging_chk.isChecked()
        )

    def _technical_widgets(self) -> list:
        """Every control that only appears once 'Technical view' is enabled.
        Kept in one place so visibility and the red 'not for average users'
        styling always stay in sync."""
        return [
            getattr(self, 'open_technical_btn', None),
            getattr(self, 'verify_staging_btn', None),
            getattr(self, 'open_debug_btn', None),
            getattr(self, 'technical_storage_label', None),
            getattr(self, 'keep_staging_chk', None),
            getattr(self, 'keep_staging_hint', None),
        ]

    def _apply_technical_view_ui(self) -> None:
        from smd.theme import technical_text_style

        technical = self._technical_view_enabled()
        style = technical_text_style(getattr(self, 'dark_mode_enabled', False))
        for widget in self._technical_widgets():
            if widget is not None:
                widget.setVisible(technical)
                widget.setStyleSheet(style)
        if hasattr(self, '_rebuild_process_controls_grid'):
            self._rebuild_process_controls_grid()
        self._refresh_after_processing_actions()
        self._update_run_readiness()

    def run_startup_self_check(self):
        """Confirm the all-in-one package is complete (no extra installs for end users)."""
        from smd.ffmpeg_bundle import bundled_status
        import sys

        status = bundled_status()
        ffmpeg_ok = status["ffmpeg"] == "ok"
        ffprobe_ok = status["ffprobe"] == "ok"
        webengine_ok = WEB_ENGINE_AVAILABLE
        frozen = getattr(sys, 'frozen', False)

        if frozen:
            if ffmpeg_ok and webengine_ok:
                self._apply_status(self.status_label, 'SMD ready - all components included.', "ok")
            elif ffmpeg_ok:
                self._apply_status(self.status_label, 'SMD ready. Map preview limited in this build.', "warn")
            else:
                self._apply_status(self.status_label, 'Package incomplete - reinstall SMD from the official installer.', "err")
            return

        if ffmpeg_ok and webengine_ok:
            self._apply_status(self.status_label, 'SMD ready - all components included.', "ok")
        elif ffmpeg_ok:
            self._apply_status(self.status_label, 'SMD ready. Map preview limited in this build.', "warn")
        else:
            self._apply_status(self.status_label, 'Video tools missing - reinstall SMD from the official installer.', "err")

    def closeEvent(self, event):
        """Clean up temporary map HTML files when the app closes."""
        self._cleanup_map_html_temps()
        self._set_keep_awake(False)
        event.accept()

    def _track_map_html_temp(self, path: str | Path) -> None:
        temp_path = Path(path)
        if temp_path not in self._map_html_temp_files:
            self._map_html_temp_files.append(temp_path)

    def _cleanup_map_html_temps(self) -> None:
        for temp_path in self._map_html_temp_files:
            try:
                if temp_path.exists():
                    temp_path.unlink()
            except OSError:
                pass
        self._map_html_temp_files.clear()

    def apply_window_icon(self):
        """Set the window icon from icon.ico or icon.png if present."""
        try:
            candidates = [ROOT / 'icon.ico', ROOT / 'icon.png']
            for path in candidates:
                if path.exists():
                    self.setWindowIcon(QIcon(str(path)))
                    break
        except Exception:
            pass
    
    
    def check_show_signal(self):
        """Check if another instance is requesting this window to show"""
        try:
            if self.signal_file.exists():
                print("DEBUG: Signal file detected, bringing window to front")
                self.signal_file.unlink()  # Delete signal file
                # Bring window to front with more aggressive methods
                if self.isMinimized():
                    print("DEBUG: Window was minimized, restoring")
                    self.showNormal()
                else:
                    print("DEBUG: Showing window")
                    self.show()
                self.setWindowState(Qt.WindowActive)
                self.raise_()
                self.activateWindow()
                # Windows-specific: flash the taskbar if we can't get focus
                if sys.platform == 'win32':
                    try:
                        import ctypes
                        hwnd = int(self.winId())
                        print(f"DEBUG: Using Windows API to focus window {hwnd}")
                        ctypes.windll.user32.SetForegroundWindow(hwnd)
                        # Flash the window to get attention
                        ctypes.windll.user32.FlashWindow(hwnd, True)
                    except Exception as e:
                        print(f"DEBUG: Windows API error: {e}")
                        pass
        except Exception as e:
            print(f"DEBUG: Error in check_show_signal: {e}")
            pass
    
    def _apply_status(self, label, text: str, status: str = "neutral") -> None:
        from smd.theme import apply_status_property

        label.setText(text)
        apply_status_property(label, status)

    def _make_tab_page(self) -> QWidget:
        from smd.theme import enable_styled_surface

        page = QWidget()
        page.setObjectName('tabPage')
        enable_styled_surface(page)
        return page

    def _scroll_tab(self, body: QWidget) -> QScrollArea:
        scroll = QScrollArea()
        scroll.setObjectName('tabScroll')
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QScrollArea.NoFrame)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        scroll.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        scroll.setWidget(body)
        return scroll

    def _doc_tab(self, inner: QWidget) -> QScrollArea:
        """Centered reading column (Guide / Help) at CONTENT_MAX_DOCS width."""
        from smd.theme import CONTENT_MAX_DOCS

        column = WidthAwareColumn(inner, CONTENT_MAX_DOCS)
        return self._scroll_tab(column)

    def _form_tab(self, inner: QWidget) -> QScrollArea:
        """Centered form column (Process) capped for comfortable control width."""
        from smd.theme import CONTENT_MAX_FORM, CONTENT_MIN_FORM

        column = WidthAwareColumn(inner, CONTENT_MAX_FORM, min_width=CONTENT_MIN_FORM)
        scroll = self._scroll_tab(column)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAsNeeded)
        return scroll

    def _section(self, title: str) -> tuple:
        from smd.theme import CONTROL_GAP, SECTION_PADDING, enable_styled_surface

        box = QFrame()
        box.setObjectName('contentSection')
        box.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        enable_styled_surface(box)
        lay = QVBoxLayout(box)
        lay.setSpacing(CONTROL_GAP)
        lay.setContentsMargins(SECTION_PADDING, SECTION_PADDING, SECTION_PADDING, SECTION_PADDING)
        if title:
            hdr = QLabel(title)
            hdr.setObjectName('sectionBoxTitle')
            lay.addWidget(hdr)
        return box, lay

    def _hero_section(self, title: str) -> tuple:
        """Highlighted section for the primary workflow (Save memories tab)."""
        from smd.theme import CONTROL_GAP, SECTION_PADDING, enable_styled_surface

        box = QFrame()
        box.setObjectName('heroSection')
        enable_styled_surface(box)
        lay = QVBoxLayout(box)
        lay.setSpacing(CONTROL_GAP + 2)
        lay.setContentsMargins(
            SECTION_PADDING + 2,
            SECTION_PADDING + 2,
            SECTION_PADDING + 2,
            SECTION_PADDING,
        )
        if title:
            hdr = QLabel(title)
            hdr.setObjectName('heroBoxTitle')
            lay.addWidget(hdr)
        return box, lay

    def _section_grid(self, *cells: tuple[QWidget, int, int]) -> QWidget:
        """2-column section grid with shared column widths and matched row heights."""
        from smd.theme import CONTROL_GAP, SECTION_GAP

        host = QWidget()
        host.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Preferred)
        grid = QGridLayout(host)
        grid.setContentsMargins(0, 0, 0, 0)
        grid.setHorizontalSpacing(CONTROL_GAP)
        grid.setVerticalSpacing(SECTION_GAP)
        for box, row, col in cells:
            box.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
            box.setMinimumWidth(0)
            grid.addWidget(box, row, col)
        for col in range(2):
            grid.setColumnStretch(col, 1)
            grid.setColumnMinimumWidth(col, 0)
        return host

    def _switch_nav_tab(self, index: int) -> None:
        if index < 0 or index >= self.tabs.count():
            return
        self.tabs.setCurrentIndex(index)
        for i, btn in enumerate(self._nav_buttons):
            active = i == index
            btn.setProperty('active', 'true' if active else 'false')
            btn.style().unpolish(btn)
            btn.style().polish(btn)

    def _refresh_content_columns(self, _index: int = 0) -> None:
        """A tab page that was hidden inside the QStackedWidget doesn't receive
        real resize events while inactive, so if the window was resized while
        a tab was in the background, its WidthAwareColumn can be sized for a
        stale width. Recompute for the newly-shown page so it always matches
        the window's current width."""
        page = self.tabs.currentWidget()
        if page is None:
            return
        for column in page.findChildren(WidthAwareColumn):
            column._apply_content_width()

    def _on_main_tab_changed(self, index: int) -> None:
        self._refresh_content_columns(index)
        if index == self._tab_file_checker:
            # Start the expensive WebEngine init as soon as the user looks at
            # this tab, not only once they click Scan - gives it a head
            # start so it's more likely ready by the time a map is actually
            # rendered.
            self._ensure_map_view()

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

    def _add_nav_button(self, label: str, index: int) -> QPushButton:
        btn = QPushButton(label)
        btn.setObjectName('NavBtn')
        btn.setProperty('active', 'false')
        btn.clicked.connect(lambda _checked=False, tab_index=index: self._switch_nav_tab(tab_index))
        self._nav_buttons.append(btn)
        return btn

    def init_ui(self):
        from smd.theme import (
            CONTENT_AREA_MARGIN_H,
            CONTENT_AREA_MARGIN_V,
            SECTION_GAP,
            SIDEBAR_WIDTH,
            WINDOW_MIN_HEIGHT,
            WINDOW_MIN_WIDTH,
        )
        from smd.version import __version__
        self.setWindowTitle(f'Snapchat Memories Downloader v{__version__}')
        self.setGeometry(100, 100, 1280, 820)
        self.setMinimumSize(WINDOW_MIN_WIDTH, WINDOW_MIN_HEIGHT)
        
        # Quit the app when the user closes this window (do not use WA_DeleteOnClose on the
        # main window — it can destroy the shell while modal post-run dialogs are closing).
        self.setAttribute(Qt.WA_QuitOnClose, True)

        # Set window icon (prioritize .ico for Windows)
        icon_path = None
        possible_icons = [ROOT / 'assets' / 'icon.ico', ROOT / 'assets' / 'icon.png']
        
        # Check local assets first
        for p in possible_icons:
            if p.exists():
                icon_path = p
                break
        
        # Fallback to bundled resources
        if not icon_path and getattr(sys, 'frozen', False):
            try:
                bundle_dir = Path(sys._MEIPASS)
                for name in ['icon.ico', 'icon.png']:
                    p = bundle_dir / 'assets' / name
                    if p.exists():
                        icon_path = p
                        break
            except Exception:
                pass

        if icon_path:
            self.setWindowIcon(QIcon(str(icon_path)))

        self.menuBar().setVisible(False)

        # Main shell: header + top tabs (original structure)
        from smd.theme import enable_styled_surface

        main_widget = QWidget()
        main_widget.setObjectName('mainShell')
        enable_styled_surface(main_widget)
        self.setCentralWidget(main_widget)
        layout = QVBoxLayout()
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        # Header with logo and theme toggle
        header_layout = QHBoxLayout()
        from smd.theme import PAGE_MARGIN_H, PAGE_MARGIN_V
        header_layout.setContentsMargins(PAGE_MARGIN_H, 16, PAGE_MARGIN_H, 16)
        header_layout.setSpacing(12)

        self.header_logo = QLabel()
        self.header_logo.setFixedSize(32, 32)
        icon_pix = None
        for p in (ROOT / 'assets' / 'icon.png', ROOT / 'assets' / 'icon.ico'):
            if p.exists():
                icon_pix = QIcon(str(p)).pixmap(32, 32)
                break
        if icon_pix is not None:
            self.header_logo.setPixmap(icon_pix)
        header_layout.addWidget(self.header_logo)

        title_col = QVBoxLayout()
        title_col.setSpacing(2)
        header = QLabel('Snapchat Memories Downloader')
        header.setProperty('class', 'pageTitle')
        subtitle_row = QHBoxLayout()
        subtitle_row.setSpacing(8)
        subtitle = QLabel(f'Version {__version__}')
        subtitle.setProperty('class', 'caption')
        offline_badge = QLabel('Works fully offline')
        offline_badge.setObjectName('offlineBadge')
        offline_badge.setToolTip(
            'Memory processing runs on your PC with no uploads. '
            'The optional GPS map may load map tiles when you open File Checker.'
        )
        subtitle_row.addWidget(subtitle)
        subtitle_row.addWidget(offline_badge)
        subtitle_row.addStretch(1)
        title_col.addWidget(header)
        title_col.addLayout(subtitle_row)
        header_layout.addLayout(title_col)
        header_layout.addStretch()

        self.support_btn = QPushButton('Support me')
        self.support_btn.setObjectName('supportBtn')
        self.support_btn.setToolTip('Ways to support SMD - free options and optional tips')
        self._populate_support_menu(self.support_btn)
        header_layout.addWidget(self.support_btn)

        self.dark_mode_btn = QPushButton('Dark')
        self.dark_mode_btn.setObjectName('themeToggleBtn')
        self.dark_mode_btn.setToolTip('Switch light and dark appearance')
        self.dark_mode_btn.clicked.connect(self.toggle_dark_mode)
        header_layout.addWidget(self.dark_mode_btn)

        header_widget = QWidget()
        header_widget.setObjectName('appHeader')
        header_widget.setLayout(header_layout)
        layout.addWidget(header_widget)

        self._tab_guide = 0
        self._tab_process = 1
        self._tab_file_checker = 2
        self._tab_help = 3
        self._tab_about = 4

        self.tabs = QTabWidget()
        self.tabs.setObjectName('mainTabs')
        # Must be set before any addTab() calls - QTabWidget only accepts a
        # replacement tab bar while empty. See _MainTabBar's docstring for
        # why QSS padding/min-width alone wasn't a reliable enough fix.
        self.tabs.setTabBar(_MainTabBar())

        # --- Tab 1: Guide (request export from Snapchat) ---
        guide_tab = self._make_tab_page()
        guide_inner = build_guide_panel(
            lambda: self.tabs.setCurrentIndex(self._tab_process)
        )
        guide_inner.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Preferred)
        guide_tab_layout = QVBoxLayout(guide_tab)
        guide_tab_layout.setContentsMargins(0, 0, 0, 0)
        guide_tab_layout.addWidget(self._doc_tab(guide_inner))
        self.tabs.addTab(guide_tab, 'Guide')

        # --- Tab 2: Save memories ---
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

        import os
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

        # --- Tab 4: Help and troubleshooting ---
        help_tab = self._make_tab_page()
        help_tab_layout = QVBoxLayout(help_tab)
        help_tab_layout.setContentsMargins(0, 0, 0, 0)
        help_tab_layout.addWidget(self._doc_tab(build_help_panel()))
        self.tabs.addTab(help_tab, 'Help')

        # --- Tab 5: About ---
        about_tab = self._make_tab_page()
        about_tab_layout = QVBoxLayout(about_tab)
        about_tab_layout.setContentsMargins(0, 0, 0, 0)
        about_tab_layout.addWidget(self._doc_tab(build_about_panel()))
        self.tabs.addTab(about_tab, 'About')

        tab_bar = self.tabs.tabBar()
        # Not setExpanding(True): that forces every tab to the *same* width,
        # which can starve the longest label ("Save memories") of the room
        # its own text needs and clip letters off. Each tab's own sizeHint
        # (which always accounts for its actual text + padding) is used
        # instead, so no tab can ever be narrower than what it needs to
        # render in full.
        #
        # setElideMode(ElideNone) is the actual guarantee against clipped
        # text: without it, Qt will still shrink/elide tabs below their
        # natural sizeHint whenever the bar doesn't have room for all of
        # them at full size and can't scroll - which is exactly what was
        # still happening ("Save memories" rendering as "iave memorie:") even
        # after removing setExpanding. Scroll buttons are re-enabled as the
        # fallback for that "not enough room" case instead: a couple of
        # small arrows beat silently truncated tab labels.
        tab_bar.setElideMode(Qt.ElideNone)
        tab_bar.setUsesScrollButtons(True)
        self.tabs.currentChanged.connect(self._on_main_tab_changed)

        try:
            QSettings('SnapchatMemories', 'Downloader').remove('recent_folders')
        except Exception:
            pass
        
        from smd.theme import PAGE_MARGIN_H, PAGE_MARGIN_V, enable_styled_surface
        tabs_shell = QWidget()
        tabs_shell.setObjectName('tabsShell')
        enable_styled_surface(tabs_shell)
        tabs_shell_layout = QVBoxLayout(tabs_shell)
        tabs_shell_layout.setContentsMargins(PAGE_MARGIN_H, 8, PAGE_MARGIN_H, PAGE_MARGIN_V)
        tabs_shell_layout.setSpacing(0)
        tabs_shell_layout.addWidget(self.tabs, 1)
        layout.addWidget(tabs_shell, 1)
        main_widget.setLayout(layout)
        
        # Store selected paths
        self.selected_zip = None
        self.export_analysis = None
        self.selected_dest = None
        self.selected_scan = None
        self.ffprobe_warned = False
        self.download_log_lines = []  # Capture recent downloader output for error context
        
        # Animation for status
        self.status_animation_timer = QTimer()
        self.status_animation_timer.timeout.connect(self.update_status_animation)
        self.status_animation_frame = 0
        self.status_base_text = ''
        self.status_animation_active = False
        
        # Detailed view state
        self.show_detailed_view = False
        self.current_file_being_processed = ''
        self.operation_start_time = None
        self.last_processed_count = 0
        self.processing_speeds = []
        
        # File Checker workflow state
        self.full_analysis_mode = False
        
        # Performance mode: 'balanced' (default), 'maximum', 'conservative'.
        # Restore the user's last choice; fall back to the friendly default.
        from smd.system_profile import PERF_MODES, mode_to_combo_index

        self._perf_settings = QSettings("SMD", "SnapchatMemoriesDownloader")
        saved_mode = self._perf_settings.value("performance_mode_v1", None, type=str)
        self.performance_mode = saved_mode if saved_mode in PERF_MODES else 'balanced'
        self.perf_mode_combo.blockSignals(True)
        self.perf_mode_combo.setCurrentIndex(mode_to_combo_index(self.performance_mode))
        self.perf_mode_combo.blockSignals(False)

        self._last_power_on_battery: bool | None = None
        self.power_watch_timer = QTimer()
        self.power_watch_timer.timeout.connect(self.refresh_system_profile)
        self.power_watch_timer.start(30_000)

        self.refresh_system_profile()
        # First launch only: seed the mode from a hardware-based recommendation.
        # After that we honour whatever the user last selected.
        if not self._perf_settings.value("auto_perf_applied_v1", False, type=bool):
            self.apply_recommended_settings(silent=True)
            self._perf_settings.setValue("auto_perf_applied_v1", True)

        self.update_export_ui_mode()

        # The default Copenhagen map is built lazily in _ensure_map_view(),
        # not here - it needs a real map_view to render into, and that
        # widget itself is now only created once the user opens File
        # Checker (see the comment on self.map_view = None in init_ui).
    
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

    # GPS extraction logic moved to smd.metadata
    
    def generate_thumbnail_base64(self, media_path, max_size=150):
        """Generate a base64 encoded thumbnail for map preview (photo or video)."""
        return generate_thumbnail_base64(media_path, max_size)

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
    
    def _load_and_apply_theme(self):
        from smd.theme import THEME_DARK, THEME_LIGHT, THEME_SYSTEM, resolve_theme

        settings = QSettings('SnapchatMemories', 'Downloader')
        stored = settings.value('theme_mode')
        if stored is None:
            self.dark_mode_enabled = resolve_theme(THEME_SYSTEM) == THEME_DARK
        else:
            self.dark_mode_enabled = str(stored) == THEME_DARK
        self._apply_current_theme()

    def _sync_doc_readers_theme(self) -> None:
        from smd.theme import apply_doc_browser_theme

        for browser in self.findChildren(DocBrowser):
            apply_doc_browser_theme(browser, dark=self.dark_mode_enabled)

    def _sync_surface_colors(self) -> None:
        from smd.theme import apply_scroll_area_theme, paint_widget_surface

        dark = self.dark_mode_enabled
        for obj_name, role in (('mainShell', 'bg'), ('tabsShell', 'bg')):
            widget = self.findChild(QWidget, obj_name)
            if widget is not None:
                paint_widget_surface(widget, dark=dark, role=role)
        paint_widget_surface(self.tabs, dark=dark, role='panel')
        for index in range(self.tabs.count()):
            page = self.tabs.widget(index)
            if page is not None:
                paint_widget_surface(page, dark=dark, role='panel')
        for scroll in self.findChildren(QScrollArea):
            if scroll.objectName() == 'tabScroll':
                apply_scroll_area_theme(scroll, dark=dark)
        for column in self.findChildren(WidthAwareColumn):
            paint_widget_surface(column, dark=dark, role='bg')

    def _apply_current_theme(self):
        from smd.theme import stylesheet_for

        theme = 'dark' if self.dark_mode_enabled else 'light'
        self.setStyleSheet(stylesheet_for(theme))
        self.dark_mode_btn.setText('Light' if self.dark_mode_enabled else 'Dark')
        self.update_title_bar_color(self.dark_mode_enabled)
        self._sync_surface_colors()
        self._sync_doc_readers_theme()
        if hasattr(self, 'results_panels'):
            self.results_panels.set_dark_theme(self.dark_mode_enabled)
        if hasattr(self, 'technical_view_chk'):
            self._apply_technical_view_ui()

    def apply_theme_mode(self, mode: str):
        from smd.theme import THEME_DARK, resolve_theme

        self.dark_mode_enabled = resolve_theme(mode) == THEME_DARK
        self._apply_current_theme()

    def update_title_bar_color(self, is_dark: bool):
        """
        Update Windows title bar color using DWM API.
        Works on Windows 10 (build 17763+) and Windows 11.
        """
        if sys.platform != 'win32':
            return
            
        try:
            import ctypes
            from ctypes import wintypes
            
            # DWMWA_USE_IMMERSIVE_DARK_MODE = 20
            DWMWA_USE_IMMERSIVE_DARK_MODE = 20
            
            hwnd = int(self.winId())
            
            # Create a boolean attribute
            attribute = ctypes.c_int(1 if is_dark else 0)
            
            ctypes.windll.dwmapi.DwmSetWindowAttribute(
                hwnd, 
                DWMWA_USE_IMMERSIVE_DARK_MODE, 
                ctypes.byref(attribute), 
                ctypes.sizeof(attribute)
            )
            
            # Force redraw to apply change immediately
            self.repaint()
        except Exception as e:
            print(f"Failed to set title bar color: {e}")

    def toggle_dark_mode(self):
        from smd.theme import THEME_DARK, THEME_LIGHT

        self.dark_mode_enabled = not self.dark_mode_enabled
        QSettings('SnapchatMemories', 'Downloader').setValue(
            'theme_mode', THEME_DARK if self.dark_mode_enabled else THEME_LIGHT
        )
        self._apply_current_theme()
        # Intentionally do NOT re-render the map here. Toggling the app theme
        # should only restyle the UI chrome; re-rendering was expensive
        # (regenerated all thumbnails) and reset the user's pan/zoom. The map
        # picks up the current theme the next time it is loaded.

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

    def show_export_example(self):
        """Show the export settings example image in fullscreen popup"""
        if hasattr(self, 'export_example_image') and self.export_example_image:
            # Save image temporarily
            temp_path = ROOT / '.temp_export_example.png'
            try:
                import base64
                img_data = self.export_example_image.split(',')[1]
                with open(temp_path, 'wb') as f:
                    f.write(base64.b64decode(img_data))
                # Show in fullscreen popup
                self.fullscreen_popup.show_media(str(temp_path))
            except Exception as e:
                QMessageBox.warning(self, 'Preview Error', f'Could not display example image:\n{str(e)}')

def _configure_webengine_storage() -> None:
    """Use a dedicated WebEngine profile so stray pythonw processes cannot deadlock startup."""
    if not WEB_ENGINE_AVAILABLE:
        return
    try:
        from PyQt5.QtWebEngineWidgets import QWebEngineProfile

        base = Path(os.environ.get('LOCALAPPDATA', Path.home())) / 'SnapchatMemoriesDownloader' / 'WebEngine'
        base.mkdir(parents=True, exist_ok=True)
        profile = QWebEngineProfile.defaultProfile()
        profile.setCachePath(str(base / 'cache'))
        profile.setPersistentStoragePath(str(base / 'storage'))
    except Exception as exc:
        print(f"DEBUG: WebEngine storage setup skipped: {exc}")


def _startup_log(message: str) -> None:
    """Append startup diagnostics to smd_gui.log (works under pythonw)."""
    try:
        with (ROOT / 'smd_gui.log').open('a', encoding='utf-8') as log_file:
            log_file.write(message.rstrip() + '\n')
            log_file.flush()
    except OSError:
        pass


from gui.single_instance import SingleInstance  # noqa: E402


if __name__ == '__main__':
    # Backend mode: allow the bundled exe to run the downloader instead of relaunching the GUI
    if '--backend' in sys.argv:
        try:
            sys.argv.remove('--backend')
        except ValueError:
            pass
        try:
            import asyncio
            import main as smd_backend
            asyncio.run(smd_backend.main())
        except Exception as e:
            print(f"[ERROR] Backend failed: {e}")
        sys.exit(0)

    print("DEBUG: Starting application...")
    _startup_log(f"DEBUG: Starting application (pid={os.getpid()})")
    sys.stdout.flush()

    if sys.platform == 'win32':
        # Claims a distinct taskbar/Alt-Tab identity for SMD so Windows shows
        # our own icon instead of grouping under pythonw.exe's generic icon
        # when running from source (the compiled SMD.exe doesn't need this,
        # since it isn't hosted by python.exe/pythonw.exe).
        try:
            import ctypes
            ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID('SMD.SnapchatMemoriesDownloader')
        except Exception:
            pass
    # Check for single instance — never blanket-kill other python processes at startup
    single_instance = SingleInstance()
    print(f"DEBUG: Checking if already running...")
    if single_instance.is_already_running():
        print("DEBUG: Another instance detected, bringing existing window to front...")
        signal_file = Path(tempfile.gettempdir()) / 'snapchat_memories_show.signal'
        try:
            signal_file.write_text('show')
            print(f"DEBUG: Signal file written to {signal_file}")
        except Exception as e:
            print(f"DEBUG: Error writing signal file: {e}")

        import time
        time.sleep(1.5)
        if signal_file.exists():
            print("DEBUG: Prior instance did not respond — starting a fresh window")
            single_instance.force_takeover()
        else:
            print("DEBUG: Existing window brought to front")
            sys.exit(0)
    
    # Fix for QtWebEngine cache/GPU errors on Windows
    os.environ["QTWEBENGINE_DISABLE_GPU"] = "1"
    
    app = QApplication(sys.argv)
    _configure_webengine_storage()
    app.setStyle('Fusion')
    from smd.theme import FONT_SIZE_BASE
    app_font = QFont('Segoe UI')
    app_font.setPixelSize(FONT_SIZE_BASE)
    app.setFont(app_font)
    app.setApplicationName("SnapchatMemoriesDownloader")
    app.setOrganizationName("SnapchatMemoriesTeam")
    # Only the main window should end the session (WA_QuitOnClose), not child modal dialogs.
    app.setQuitOnLastWindowClosed(False)

    def _build_splash_pixmap() -> QPixmap:
        width, height = 440, 320
        pixmap = QPixmap(width, height)
        pixmap.fill(QColor(20, 20, 20))

        painter = QPainter(pixmap)
        painter.setRenderHint(QPainter.Antialiasing)

        logo_bottom = 44
        icon_path = ROOT / 'assets' / 'icon.png'
        if icon_path.exists():
            logo = QPixmap(str(icon_path)).scaled(
                88, 88, Qt.KeepAspectRatio, Qt.SmoothTransformation
            )
            logo_x = (width - logo.width()) // 2
            painter.drawPixmap(logo_x, logo_bottom, logo)
            title_y = logo_bottom + logo.height() + 22
        else:
            title_y = 120

        title_font = QFont('Segoe UI', 17)
        title_font.setWeight(QFont.DemiBold)
        painter.setFont(title_font)
        painter.setPen(QColor(242, 242, 247))
        painter.drawText(
            0, title_y, width, 30,
            Qt.AlignHCenter | Qt.AlignTop,
            'Snapchat Memories Downloader',
        )

        subtitle_font = QFont('Segoe UI', 13)
        painter.setFont(subtitle_font)
        painter.setPen(QColor(142, 142, 147))
        painter.drawText(
            0, title_y + 34, width, 24,
            Qt.AlignHCenter | Qt.AlignTop,
            'Loading application…',
        )
        painter.end()
        return pixmap

    splash = QSplashScreen(_build_splash_pixmap())
    splash.show()
    QCoreApplication.processEvents()
    splash.showMessage(
        'Preparing interface…',
        Qt.AlignBottom | Qt.AlignHCenter,
        QColor(161, 161, 166),
    )
    QCoreApplication.processEvents()
    
    print("DEBUG: Creating main window...")
    sys.stdout.flush()
    try:
        gui = DownloaderGUI()
    except Exception as exc:
        import traceback
        err_text = traceback.format_exc()
        print(f"DEBUG: Failed to create main window:\n{err_text}")
        try:
            (ROOT / 'smd_gui.log').open('a', encoding='utf-8').write(
                '\nSTARTUP FAILED:\n' + err_text + '\n'
            )
        except OSError:
            pass
        try:
            QMessageBox.critical(
                None,
                'SMD could not start',
                f'Snapchat Memories Downloader failed to open.\n\n{exc}\n\n'
                f'See smd_gui.log in the SMD folder for details.',
            )
        except Exception:
            pass
        sys.exit(1)
    print(f"DEBUG: Window created, showing at position ({gui.x()}, {gui.y()})")
    
    # Hide splash screen and show main window
    splash.finish(gui)
    gui.showNormal()
    gui.show()
    gui.raise_()
    gui.activateWindow()
    _startup_log("DEBUG: main window shown")
    try:
        from PyQt5.QtWidgets import QDesktopWidget
        screen = QApplication.desktop().availableGeometry(gui)
        gui.move(
            screen.x() + max(0, (screen.width() - gui.width()) // 2),
            screen.y() + max(0, (screen.height() - gui.height()) // 2),
        )
    except Exception:
        pass
    print(f"DEBUG: Window shown, visible={gui.isVisible()}, minimized={gui.isMinimized()}")
    sys.stdout.flush()
    sys.exit(app.exec_())
