#!/usr/bin/env python3
"""
Snapchat Memories Downloader (SMD) - Desktop GUI
Professional native Windows application for downloading Snapchat memories with GPS embedding

Created by: Las HS (https://github.com/LasHSHS)
License: Open Source
"""

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

import tempfile
from pathlib import Path
from PyQt5.QtWidgets import (
    QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout, QPushButton,
    QLabel, QTabWidget, QSplashScreen, QMessageBox,
)
from PyQt5.QtCore import Qt, QTimer, QSettings, QCoreApplication
from PyQt5.QtGui import QFont, QIcon, QColor, QPixmap, QPainter

from gui.common import ROOT, configure_webengine_storage, startup_log
from gui.widgets import FullScreenMediaPopup, ProcessingShieldOverlay, StreamRedirector, _MainTabBar
from gui.single_instance import SingleInstance
from gui.tabs.completion import CompletionMixin
from gui.tabs.file_checker_tab import FileCheckerTabMixin
from gui.tabs.guide_tab import GuideTabMixin
from gui.tabs.help_about_tabs import HelpAboutTabMixin
from gui.tabs.save_memories_tab import SaveMemoriesTabMixin
from gui.window_chrome import WindowChromeMixin


class DownloaderGUI(QMainWindow, WindowChromeMixin, GuideTabMixin, SaveMemoriesTabMixin, FileCheckerTabMixin, CompletionMixin, HelpAboutTabMixin):
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

    def init_ui(self):
        from smd.theme import WINDOW_MIN_HEIGHT, WINDOW_MIN_WIDTH
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

        self.free_palestine_banner = QLabel('Free Palestine')
        self.free_palestine_banner.setObjectName('infoBanner')
        self.free_palestine_banner.setAlignment(Qt.AlignCenter)
        self.free_palestine_banner.setWordWrap(True)
        layout.addWidget(self.free_palestine_banner)

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

        self._add_guide_tab()

        self._add_save_memories_tab()

        self._add_file_checker_tab()

        self._add_help_and_about_tabs()

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
    startup_log(f"DEBUG: Starting application (pid={os.getpid()})")
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
    configure_webengine_storage()
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
    startup_log("DEBUG: main window shown")
    try:
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
