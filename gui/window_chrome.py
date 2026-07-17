"""Window chrome mixin: theme, nav helpers, technical view, close/cleanup."""
from __future__ import annotations

import os
import sys
from pathlib import Path

from PyQt5.QtCore import Qt, QTimer, QSettings, QUrl
from PyQt5.QtGui import QIcon, QColor, QDesktopServices
from PyQt5.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QGridLayout, QPushButton, QLabel,
    QScrollArea, QFrame, QSizePolicy, QGraphicsOpacityEffect, QMessageBox,
)

from gui.common import ROOT, WEB_ENGINE_AVAILABLE
from gui.widgets import DocBrowser, WidthAwareColumn


class WindowChromeMixin:
    """Mixin: window chrome shared by every tab (theme, nav, section helpers)."""

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

    def _add_nav_button(self, label: str, index: int) -> QPushButton:
        btn = QPushButton(label)
        btn.setObjectName('NavBtn')
        btn.setProperty('active', 'false')
        btn.clicked.connect(lambda _checked=False, tab_index=index: self._switch_nav_tab(tab_index))
        self._nav_buttons.append(btn)
        return btn

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
