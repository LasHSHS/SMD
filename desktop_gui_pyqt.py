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
        _early_log = open(
            os.path.join(os.path.dirname(os.path.abspath(__file__)), 'smd_gui.log'),
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
from datetime import datetime, timedelta
from PyQt5.QtWidgets import (QApplication, QMainWindow, QWidget, QVBoxLayout, 
                             QHBoxLayout, QPushButton, QLabel, QFileDialog, QLineEdit,
                             QTextEdit, QTextBrowser, QComboBox, QSpinBox, QCheckBox, QTabWidget, QProgressBar, QToolTip, QSizePolicy, QSplashScreen, QGroupBox, QGridLayout,
                             QRadioButton, QButtonGroup, QFrame, QPlainTextEdit, QMenu, QScrollArea)
from PyQt5.QtCore import Qt, QThread, pyqtSignal, QUrl, QTimer, QObject, pyqtSlot, QSettings, QCoreApplication, QSize
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

ROOT = Path(__file__).parent


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


class StreamRedirector:
    """Redirect stdout/stderr lines into the GUI debug console."""

    def __init__(self, callback):
        self._callback = callback
        self._buffer = ""

    def write(self, text: str) -> None:
        if not text:
            return
        self._buffer += text
        while "\n" in self._buffer:
            line, self._buffer = self._buffer.split("\n", 1)
            if line:
                self._callback(line.rstrip())

    def flush(self) -> None:
        if self._buffer:
            self._callback(self._buffer.rstrip())
            self._buffer = ""

    def isatty(self) -> bool:
        return False


class DocBrowser(QTextBrowser):
    """QTextBrowser that reflows HTML to the full widget width."""

    def __init__(self, parent=None):
        super().__init__(parent)
        from smd.theme import enable_styled_surface

        enable_styled_surface(self)
        self.setObjectName('docReader')
        self.setReadOnly(True)
        self.setOpenExternalLinks(True)
        self.setFrameShape(QTextBrowser.NoFrame)
        self.setLineWrapMode(QTextEdit.WidgetWidth)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        self.document().setDocumentMargin(12)

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self.document().setTextWidth(self.viewport().width())


class FlowDocBrowser(DocBrowser):
    """Grows to fit HTML height; parent QScrollArea handles scrolling."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setVerticalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Minimum)
        self.document().contentsChanged.connect(self._sync_height)
        QTimer.singleShot(0, self._sync_height)

    def _sync_height(self) -> None:
        width = self.viewport().width()
        if width > 0:
            self.document().setTextWidth(width)
        margin = self.document().documentMargin()
        height = int(self.document().size().height()) + margin * 2 + 4
        self.setMinimumHeight(height)
        self.setMaximumHeight(height)

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self._sync_height()


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


class WidthAwareColumn(QWidget):
    """Centered column that expands to available width (optional max_width cap)."""

    def __init__(
        self,
        content: QWidget,
        max_width: int,
        margins: tuple[int, int, int, int] | None = None,
        min_width: int = 520,
        parent=None,
    ):
        super().__init__(parent)
        from smd.theme import PAGE_MARGIN_H, PAGE_MARGIN_V, enable_styled_surface

        self.setObjectName('contentColumn')
        enable_styled_surface(self)
        self._content = content
        self._max_width = max_width
        self._min_width = min_width
        self._margins = margins or (PAGE_MARGIN_H, PAGE_MARGIN_V, PAGE_MARGIN_H, PAGE_MARGIN_V)
        self._row = QHBoxLayout(self)
        self._row.setContentsMargins(*self._margins)
        self._row.addStretch(1)
        content.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Preferred)
        self._row.addWidget(content, 1)
        self._row.addStretch(1)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        QTimer.singleShot(0, self._apply_content_width)

    def _apply_content_width(self) -> None:
        left, _top, right, _bottom = self._margins
        available = max(0, self.width() - left - right)
        floor = self._min_width
        if self._max_width > 0:
            if available >= floor:
                content_w = min(self._max_width, available)
            else:
                content_w = floor
            self._content.setMinimumWidth(content_w)
            self._content.setMaximumWidth(min(self._max_width, max(available, floor)))
        else:
            content_w = max(floor, available)
            self._content.setMinimumWidth(content_w)
            self._content.setMaximumWidth(content_w)
        self._sync_doc_browsers(self._content)

    @staticmethod
    def _sync_doc_browsers(widget: QWidget) -> None:
        if isinstance(widget, DocBrowser):
            widget.document().setTextWidth(widget.viewport().width())
        for child in widget.findChildren(DocBrowser):
            child.document().setTextWidth(child.viewport().width())

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self._apply_content_width()
        if isinstance(self._content, DocBrowser):
            self._content.document().setTextWidth(self._content.viewport().width())


def _accent_play_button_qss() -> str:
    """Themed accent for media viewer overlay (dark surface)."""
    from smd.theme import DARK_SECONDARY, DARK_SECONDARY_HOVER, DARK_SECONDARY_TEXT

    return f"""
        QPushButton {{
            background-color: {DARK_SECONDARY};
            color: {DARK_SECONDARY_TEXT};
            padding: 12px 20px;
            font-size: 16px;
            border: none;
            border-radius: 8px;
            font-weight: bold;
        }}
        QPushButton:hover {{
            background-color: {DARK_SECONDARY_HOVER};
        }}
    """


class MediaViewer(QWidget):
    """Widget for displaying images and videos with close button"""
    file_opened = pyqtSignal(str)  # Signal when file is opened
    
    def __init__(self):
        super().__init__()
        self.current_file = None
        self.init_ui()
        self.setStyleSheet("""
            MediaViewer {
                background-color: #000;
                border: 1px solid #ddd;
            }
        """)
    
    def init_ui(self):
        layout = QVBoxLayout()
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)
        
        # Header with close button
        header = QHBoxLayout()
        self.file_label = QLabel('No file selected')
        self.file_label.setStyleSheet('color: white; padding: 10px; background-color: #333; font-weight: bold;')
        header.addWidget(self.file_label)
        
        close_btn = QPushButton('×')
        close_btn.setMaximumWidth(40)
        close_btn.setMaximumHeight(40)
        close_btn.setStyleSheet("""
            QPushButton {
                background-color: #d13438;
                color: white;
                border: none;
                font-size: 24px;
                font-weight: bold;
                padding: 0px;
            }
            QPushButton:hover {
                background-color: #a4373a;
            }
        """)
        close_btn.clicked.connect(self.close_viewer)
        header.addWidget(close_btn)
        
        header_widget = QWidget()
        header_widget.setLayout(header)
        layout.addWidget(header_widget)
        
        # Scrollable content area
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setStyleSheet("QScrollArea { border: none; background-color: #000; }")
        
        self.content_widget = QWidget()
        self.content_layout = QVBoxLayout(self.content_widget)
        self.content_layout.setContentsMargins(0, 0, 0, 0)
        self.content_layout.setAlignment(Qt.AlignCenter | Qt.AlignTop)
        
        scroll.setWidget(self.content_widget)
        layout.addWidget(scroll)
        
        self.setLayout(layout)
    
    def open_file(self, file_path):
        """Open and display a media file"""
        try:
            file_path = str(file_path)
            if not os.path.exists(file_path):
                self.show_error(f"File not found: {file_path}")
                return
            
            self.current_file = file_path
            filename = os.path.basename(file_path)
            self.file_label.setText(f'📁 {filename}')
            
            # Clear previous content
            while self.content_layout.count():
                self.content_layout.takeAt(0).widget().deleteLater()
            
            file_ext = os.path.splitext(file_path)[1].lower()
            
            if file_ext in ['.jpg', '.jpeg', '.png', '.bmp', '.gif', '.webp']:
                # Display image
                img = Image.open(file_path)
                
                # Scale to fit viewer (max 600x800)
                img.thumbnail((600, 800), Image.Resampling.LANCZOS)
                
                # Convert to QPixmap
                from PIL import ImageQt
                pixmap = ImageQt.toqpixmap(img)
                
                img_label = QLabel()
                img_label.setPixmap(pixmap)
                img_label.setAlignment(Qt.AlignCenter)
                img_label.setStyleSheet('background-color: #000;')
                
                self.content_layout.addWidget(img_label)
            
            elif file_ext in ['.mp4', '.m4v', '.avi', '.mov', '.mkv']:
                # Display video info and play button
                video_label = QLabel(f'🎥 Video File\n\n{filename}')
                video_label.setAlignment(Qt.AlignCenter)
                video_label.setStyleSheet("""
                    color: white;
                    font-size: 16px;
                    padding: 40px;
                    background-color: #222;
                """)
                self.content_layout.addWidget(video_label)
                
                # Add play button
                play_btn = QPushButton('Open with default player')
                play_btn.setStyleSheet(_accent_play_button_qss())
                play_btn.clicked.connect(lambda: self.open_in_player(file_path))
                self.content_layout.addWidget(play_btn)
            
            else:
                self.show_error(f"Unsupported file type: {file_ext}")
        
        except Exception as e:
            self.show_error(f"Error opening file: {str(e)}")
    
    def show_error(self, message):
        """Display error message in viewer"""
        error_label = QLabel(f'Error\n\n{message}')
        error_label.setAlignment(Qt.AlignCenter)
        error_label.setStyleSheet("""
            color: #d13438;
            font-size: 14px;
            padding: 20px;
            background-color: #222;
            border: 2px solid #d13438;
        """)
        
        while self.content_layout.count():
            self.content_layout.takeAt(0).widget().deleteLater()
        
        self.content_layout.addWidget(error_label)
    
    def open_in_player(self, file_path):
        """Open file with default system player"""
        try:
            if sys.platform == 'win32':
                os.startfile(file_path)
            elif sys.platform == 'darwin':
                subprocess.Popen(['open', str(file_path)])
            else:  # Linux
                subprocess.Popen(['xdg-open', str(file_path)])
        except Exception as e:
            self.show_error(f"Could not open player: {str(e)}")
    
    def close_viewer(self):
        """Close the viewer and clear content"""
        self.current_file = None
        self.file_label.setText('No file selected')
        while self.content_layout.count():
            widget = self.content_layout.takeAt(0).widget()
            if widget:
                widget.deleteLater()
        self.setVisible(False)


class ProcessingShieldOverlay(QWidget):
    """Blocks the UI with a dark tint while processing runs."""

    def __init__(self, parent=None, *, on_cancel=None):
        super().__init__(parent)
        self._on_cancel = on_cancel
        self.setObjectName('processingShield')
        self.setAttribute(Qt.WA_StyledBackground, True)
        self.setStyleSheet('background-color: rgba(0, 0, 0, 165);')
        self.hide()

        outer = QVBoxLayout(self)
        outer.setContentsMargins(24, 24, 24, 24)
        outer.addStretch(2)

        panel = QFrame()
        panel.setObjectName('contentPanel')
        from smd.theme import enable_styled_surface

        enable_styled_surface(panel)
        panel_lay = QVBoxLayout(panel)
        panel_lay.setContentsMargins(28, 24, 28, 24)
        panel_lay.setSpacing(14)

        title = QLabel('Processing your memories…')
        title.setProperty('class', 'sectionHeader')
        title.setAlignment(Qt.AlignCenter)
        panel_lay.addWidget(title)

        self.hint_label = QLabel('Please wait. SMD will show a summary when finished.')
        self.hint_label.setWordWrap(True)
        self.hint_label.setAlignment(Qt.AlignCenter)
        self.hint_label.setProperty('class', 'caption')
        panel_lay.addWidget(self.hint_label)

        cancel_btn = QPushButton('Cancel')
        cancel_btn.setObjectName('runAction')
        cancel_btn.setSizePolicy(QSizePolicy.Fixed, QSizePolicy.Fixed)
        if on_cancel:
            cancel_btn.clicked.connect(on_cancel)
        row = QHBoxLayout()
        row.addStretch(1)
        row.addWidget(cancel_btn)
        row.addStretch(1)
        panel_lay.addLayout(row)
        outer.addWidget(panel, 0, Qt.AlignCenter)
        outer.addStretch(3)

    def show_over(self) -> None:
        parent = self.parentWidget()
        if parent is not None:
            self.setGeometry(parent.rect())
        self.show()
        self.raise_()

    def resizeEvent(self, event):
        parent = self.parentWidget()
        if parent is not None:
            self.setGeometry(parent.rect())
        super().resizeEvent(event)


class FullScreenMediaPopup(QWidget):
    """Overlay popup for viewing media files inside the main window"""
    
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowFlags(Qt.Widget)  # Not a separate window, overlay inside parent
        self.setAttribute(Qt.WA_TranslucentBackground, False)
        self.setStyleSheet("background-color: rgba(0, 0, 0, 250);")
        self.current_file = None
        self.init_ui()
        self.hide()  # Hidden by default
    
    def showEvent(self, event):
        """Position overlay to cover entire parent window"""
        try:
            if self.parent():
                self.setGeometry(self.parent().rect())
        except Exception as e:
            print(f"Error positioning overlay: {e}")
        super().showEvent(event)
    
    def init_ui(self):
        layout = QVBoxLayout()
        layout.setContentsMargins(40, 40, 40, 40)
        
        # Top bar with filename and close button
        top_bar = QHBoxLayout()
        self.filename_label = QLabel('File Viewer')
        self.filename_label.setStyleSheet("""
            color: white;
            font-size: 16px;
            font-weight: bold;
            padding: 10px;
        """)
        top_bar.addWidget(self.filename_label)
        top_bar.addStretch()
        
        close_btn = QPushButton('×')
        close_btn.setFixedSize(50, 50)
        close_btn.setStyleSheet("""
            QPushButton {
                background-color: #d13438;
                color: white;
                border: none;
                border-radius: 25px;
                font-size: 32px;
                font-weight: bold;
            }
            QPushButton:hover {
                background-color: #ff4444;
            }
        """)
        close_btn.clicked.connect(self.close)
        top_bar.addWidget(close_btn)
        
        layout.addLayout(top_bar)
        
        # Content area
        self.content_scroll = QScrollArea()
        self.content_scroll.setWidgetResizable(True)
        self.content_scroll.setStyleSheet("""
            QScrollArea {
                border: 2px solid #333;
                border-radius: 8px;
                background-color: #1a1a1a;
            }
        """)
        
        self.content_widget = QWidget()
        self.content_layout = QVBoxLayout(self.content_widget)
        self.content_layout.setAlignment(Qt.AlignCenter)
        self.content_scroll.setWidget(self.content_widget)
        
        layout.addWidget(self.content_scroll)
        self.setLayout(layout)
    
    def open_file(self, file_path):
        """Open and display a media file in fullscreen"""
        try:
            file_path = str(file_path)
            if not os.path.exists(file_path):
                self.show_error(f"File not found: {file_path}")
                return
            
            self.current_file = file_path
            filename = os.path.basename(file_path)
            self.filename_label.setText(f'📁 {filename}')
            
            # Clear previous content
            while self.content_layout.count():
                item = self.content_layout.takeAt(0)
                if item.widget():
                    item.widget().deleteLater()
            
            file_ext = os.path.splitext(file_path)[1].lower()
            
            if file_ext in ['.jpg', '.jpeg', '.png', '.bmp', '.gif', '.webp']:
                # Display image
                img = Image.open(file_path)
                
                # Scale to fit screen (max 90% of screen size)
                screen = QApplication.primaryScreen().geometry()
                max_width = int(screen.width() * 0.8)
                max_height = int(screen.height() * 0.7)
                img.thumbnail((max_width, max_height), Image.Resampling.LANCZOS)
                
                # Convert to QPixmap
                from PIL import ImageQt
                pixmap = ImageQt.toqpixmap(img)
                
                img_label = QLabel()
                img_label.setPixmap(pixmap)
                img_label.setAlignment(Qt.AlignCenter)
                img_label.setStyleSheet('background-color: transparent;')
                
                self.content_layout.addWidget(img_label)
            
            elif file_ext in ['.mp4', '.m4v', '.avi', '.mov', '.mkv']:
                # Display video info
                video_label = QLabel(f'🎥 Video File\n\n{filename}')
                video_label.setAlignment(Qt.AlignCenter)
                video_label.setStyleSheet("""
                    color: white;
                    font-size: 18px;
                    padding: 60px;
                """)
                self.content_layout.addWidget(video_label)
                
                # Add play button
                play_btn = QPushButton('Open with default player')
                play_btn.setFixedSize(300, 60)
                play_btn.setStyleSheet(_accent_play_button_qss())
                play_btn.clicked.connect(lambda: self.open_in_player(file_path))
                self.content_layout.addWidget(play_btn)
            
            else:
                self.show_error(f"Unsupported file type: {file_ext}")
            
            # Show as overlay on parent window
            if self.parent():
                self.setGeometry(self.parent().rect())
            self.show()
            self.raise_()  # Bring to front
        
        except Exception as e:
            self.show_error(f"Error opening file: {str(e)}")

    def show_media(self, file_path):
        """Compatibility wrapper for show_export_example usage."""
        self.open_file(file_path)
    
    def show_error(self, message):
        """Display error message"""
        error_label = QLabel(f'Error\n\n{message}')
        error_label.setAlignment(Qt.AlignCenter)
        error_label.setStyleSheet("""
            color: #ff4444;
            font-size: 16px;
            padding: 40px;
        """)
        
        while self.content_layout.count():
            item = self.content_layout.takeAt(0)
            if item.widget():
                item.widget().deleteLater()
        
        self.content_layout.addWidget(error_label)
        self.showFullScreen()
    
    def open_in_player(self, file_path):
        """Open file with default system player"""
        try:
            if sys.platform == 'win32':
                os.startfile(file_path)
            elif sys.platform == 'darwin':
                subprocess.Popen(['open', str(file_path)])
            else:  # Linux
                subprocess.Popen(['xdg-open', str(file_path)])
        except Exception as e:
            self.show_error(f"Could not open player: {str(e)}")
    
    def keyPressEvent(self, event):
        """Close on Escape key"""
        if event.key() == Qt.Key_Escape:
            self.close()
        super().keyPressEvent(event)


def _map_base_tile(*, dark: bool) -> str:
    return "CartoDB.DarkMatter" if dark else "OpenStreetMap"


def _add_map_layer_options(m: folium.Map, *, dark: bool) -> None:
    """Optional basemaps alongside the theme default (street / dark / satellite / terrain)."""
    if dark:
        folium.TileLayer(
            tiles="OpenStreetMap",
            name="Light map",
            overlay=False,
            control=True,
        ).add_to(m)
    else:
        folium.TileLayer(
            tiles="CartoDB.DarkMatter",
            name="Dark map",
            overlay=False,
            control=True,
        ).add_to(m)
    folium.TileLayer(
        tiles='https://server.arcgisonline.com/ArcGIS/rest/services/World_Imagery/MapServer/tile/{z}/{y}/{x}',
        attr='Esri',
        name='Satellite',
        overlay=False,
        control=True,
    ).add_to(m)
    folium.TileLayer(
        tiles='OpenTopoMap',
        name='Terrain',
        overlay=False,
        control=True,
    ).add_to(m)


def _create_themed_map(
    location: list[float],
    zoom_start: int,
    *,
    dark: bool,
    control_scale: bool = False,
) -> folium.Map:
    """Create a folium map with theme-appropriate default tiles and alternates."""
    m = folium.Map(
        location=location,
        zoom_start=zoom_start,
        tiles=_map_base_tile(dark=dark),
        control_scale=control_scale,
    )
    _add_map_layer_options(m, dark=dark)
    return m


class MapRenderWorker(QThread):
    """Background thread for rendering folium map (non-blocking)"""
    progress = pyqtSignal(int, str)  # progress_percent, status_text
    finished = pyqtSignal(str)  # html_file_path
    error = pyqtSignal(str)
    
    def __init__(self, locations, parent_gui):
        super().__init__()
        self.locations = locations
        self.parent_gui = parent_gui
    
    def run(self):
        try:
            from collections import defaultdict
            
            self.progress.emit(5, 'Building marker groups...')
            QApplication.processEvents()
            
            try:
                # Find the latest file to center map
                latest_location = max(self.locations, key=lambda x: x.get('modified', 0))
                center_lat = latest_location['coords'][0]
                center_lon = latest_location['coords'][1]
            except (ValueError, IndexError, KeyError) as e:
                print(f"DEBUG: Error finding map center: {e}")
                # Default to center of US
                center_lat, center_lon = 39.8283, -98.5795
            
            self.progress.emit(10, 'Creating base map...')
            QApplication.processEvents()
            
            try:
                dark = bool(getattr(self.parent_gui, 'dark_mode_enabled', False))
                m = _create_themed_map(
                    [center_lat, center_lon],
                    8,
                    dark=dark,
                    control_scale=True,
                )
            except Exception as e:
                print(f"DEBUG: Error creating folium map: {e}")
                self.error.emit(f'Failed to create map: {str(e)}')
                return
            
            # Create marker cluster
            try:
                self.progress.emit(25, '📍 Creating marker cluster...')
                QApplication.processEvents()
                marker_cluster = MarkerCluster(
                    name='Photos/Videos',
                    overlay=True,
                    control=False,
                    show=True
                ).add_to(m)
            except Exception as e:
                print(f"DEBUG: Error creating marker cluster: {e}")
                marker_cluster = None
                self.error.emit(f'Warning: Could not create marker cluster: {str(e)}')
            
            # Group locations by coordinates
            try:
                self.progress.emit(30, '🧮 Grouping locations...')
                QApplication.processEvents()
                grouped_locations = defaultdict(list)
                for loc in self.locations:
                    try:
                        coord_key = (round(loc['coords'][0], 5), round(loc['coords'][1], 5))
                        grouped_locations[coord_key].append(loc)
                    except (KeyError, TypeError) as e:
                        print(f"DEBUG: Error processing location: {e}, loc: {loc}")
                        continue
            except Exception as e:
                print(f"DEBUG: Error grouping locations: {e}")
                self.error.emit(f'Error processing locations: {str(e)}')
                return
            
            total_groups = len(grouped_locations)
            if total_groups == 0:
                print("DEBUG: No locations to display on map")
                self.error.emit('No valid locations found to display on map')
                return
            
            current_group = 0
            
            # Add markers
            all_files_json = {}
            
            for coord_key, loc_group in grouped_locations.items():
                try:
                    current_group += 1
                    progress_val = 30 + int((current_group / total_groups) * 60)
                    self.progress.emit(progress_val, f'📌 Adding markers ({current_group}/{total_groups})...')
                    QApplication.processEvents()
                    
                    primary_loc = loc_group[0]
                    
                    # Generate thumbnail (images and videos)
                    thumbnail_b64 = None
                    for loc in loc_group:
                        try:
                            thumbnail_b64 = self.parent_gui.generate_thumbnail_base64(loc['full_path'])
                            if thumbnail_b64:
                                break
                        except Exception as thumb_err:
                            print(f"DEBUG: Error generating thumbnail: {thumb_err}")
                    
                    # Create popup HTML
                    try:
                        file_list = '<br>'.join([f"• {html.escape(loc['filename'])}" for loc in loc_group[:10]])
                        if len(loc_group) > 10:
                            file_list += f"<br>• ... and {len(loc_group) - 10} more"
                        
                        safe_file_path = primary_loc['full_path'].replace('\\', '/').replace("'", "\\'").replace('"', '\\"')
                        thumb_html = ""
                        if thumbnail_b64:
                            thumb_html = f'<img src="{thumbnail_b64}" style="max-width:180px;max-height:120px;border-radius:4px;margin-bottom:6px;"><br>'

                        popup_html = f"""
                            <div style="min-width:200px; max-width:300px;" data-filepath="{safe_file_path}">
                                {thumb_html}
                                <b style="font-size:14px;">{len(loc_group)} file(s) at this location</b><br>
                                <div style="margin-top:8px; max-height:120px; overflow-y:auto; font-size:11px;">
                                    {file_list}
                                </div>
                                <small style="color:#999; margin-top:5px; display:block; font-size:10px;">
                                    📍 {primary_loc['coords'][0]:.6f}, {primary_loc['coords'][1]:.6f}
                                </small>
                            </div>
                        """
                    except Exception as popup_err:
                        print(f"DEBUG: Error creating popup HTML: {popup_err}")
                        popup_html = f"""
                            <div style="min-width:200px; max-width:300px;">
                                <b>{len(loc_group)} file(s) at this location</b>
                            </div>
                        """
                    
                    # Create tooltip
                    try:
                        safe_filename = html.escape(primary_loc['filename'])
                        if thumbnail_b64:
                            tooltip_html = f"""
                            <div style="text-align:center; background:white; padding:5px; border-radius:5px;">
                                <img src="{thumbnail_b64}" style="max-width:150px; max-height:150px; border-radius:3px;"><br>
                                <small style="color:#333; margin-top:3px; display:block;"><b>{safe_filename}</b></small>
                                <small style="color:#666; font-size:9px;">{len(loc_group)} file(s) here</small>
                            </div>
                            """
                            tooltip = folium.Tooltip(tooltip_html, sticky=True)
                        else:
                            tooltip_text = f"{len(loc_group)} files: {safe_filename}"
                            tooltip = folium.Tooltip(tooltip_text, sticky=True)
                    except Exception as tooltip_err:
                        print(f"DEBUG: Error creating tooltip: {tooltip_err}")
                        tooltip = folium.Tooltip(f"{len(loc_group)} files at location", sticky=True)
                    
                    # Add marker
                    try:
                        folium.Marker(
                            location=primary_loc['coords'],
                            popup=folium.Popup(popup_html, max_width=350),
                            tooltip=tooltip,
                            icon=folium.Icon(
                                color='red' if primary_loc.get('type') == 'image' else 'blue',
                                icon='camera' if primary_loc.get('type') == 'image' else 'video-camera',
                                prefix='fa'
                            )
                        ).add_to(marker_cluster if marker_cluster else m)
                    except Exception as marker_err:
                        print(f"DEBUG: Error adding marker: {marker_err}")
                        # Skip this marker but continue
                        pass
                    
                    # Store file data for click handling
                    try:
                        coord_str = f"{coord_key[0]:.5f},{coord_key[1]:.5f}"
                        all_files_json[coord_str] = [{'path': loc['full_path'], 'name': loc['filename']} for loc in loc_group]
                    except Exception as data_err:
                        print(f"DEBUG: Error storing file data: {data_err}")
                        pass
                
                except Exception as e:
                    print(f"DEBUG: Error processing marker group: {e}")
                    continue
            
            try:
                self.progress.emit(92, '🔗 Adding layer controls...')
                QApplication.processEvents()
                folium.LayerControl().add_to(m)
            except Exception as e:
                print(f"DEBUG: Error adding layer controls: {e}")
                pass
            
            try:
                self.progress.emit(95, 'Generating HTML...')
                QApplication.processEvents()
                
                # Add JavaScript with file data
                all_files_json_str = json.dumps(all_files_json)
                from smd.theme import LIGHT_SECONDARY, LIGHT_SECONDARY_HOVER

                custom_js = f"""
                <script>
                window.fileData = {all_files_json_str};
                
                window.addEventListener('resize', function() {{
                    if (typeof map !== 'undefined') {{
                        map.invalidateSize();
                    }}
                }});
                </script>
                <style>
                .leaflet-popup-content {{
                    margin: 13px 19px;
                    line-height: 1.4;
                }}
                .leaflet-popup-content button:hover {{
                    background-color: {LIGHT_SECONDARY_HOVER} !important;
                    transform: scale(1.02);
                    transition: all 0.2s;
                }}
                .leaflet-tooltip {{
                    background-color: rgba(255, 255, 255, 0.95);
                    border: 2px solid {LIGHT_SECONDARY};
                    border-radius: 8px;
                    padding: 8px;
                    box-shadow: 0 4px 12px rgba(0,0,0,0.3);
                }}
                </style>
                """
                m.get_root().html.add_child(folium.Element(custom_js))
            except Exception as e:
                print(f"DEBUG: Error adding custom JavaScript: {e}")
                pass
            
            try:
                # Save map to file
                self.progress.emit(98, 'Saving map file...')
                QApplication.processEvents()
                temp_file = tempfile.NamedTemporaryFile(delete=False, suffix='.html', mode='w', encoding='utf-8')
                temp_path = temp_file.name
                temp_file.close()
                
                m.save(temp_path)
                
                print(f"DEBUG: Map saved to {temp_path}")
                
                # Inject JavaScript for auto-opening files
                try:
                    with open(temp_path, 'r', encoding='utf-8') as f:
                        html_content = f.read()
                    
                    # Add script before closing body tag
                    auto_open_script = """
                    <script>
                    // Auto-open file when a marker's popup opens
                    document.addEventListener('DOMContentLoaded', function() {
                        if (typeof map !== 'undefined') {
                            map.on('popupopen', function(e) {
                                try {
                                    var content = e.popup.getContent();
                                    var div = document.createElement('div');
                                    div.innerHTML = content;
                                    var target = div.querySelector('div[data-filepath]');
                                    if (target) {
                                        var filepath = target.getAttribute('data-filepath');
                                        if (filepath) {
                                            console.log('Auto-opening file:', filepath);
                                            window.pyOpenFile = filepath;
                                        }
                                    }
                                } catch (err) {
                                    console.log('popupopen handler error', err);
                                }
                            });
                        }
                    });
                    </script>
                    """
                    html_content = html_content.replace('</body>', auto_open_script + '</body>')
                    
                    with open(temp_path, 'w', encoding='utf-8') as f:
                        f.write(html_content)
                    
                    print("DEBUG: Auto-open JavaScript injected into map HTML")
                except Exception as inject_err:
                    print(f"WARNING: Could not inject auto-open JavaScript: {inject_err}")
                
                self.progress.emit(100, 'Map rendered!')
                QApplication.processEvents()
                self.finished.emit(temp_path)
            except Exception as save_err:
                print(f"DEBUG: Error saving map: {save_err}")
                self.error.emit(f'Failed to save map: {str(save_err)}')
                return
            
        except Exception as e:
            print(f"DEBUG: Unexpected error in MapRenderWorker: {e}")
            import traceback
            traceback.print_exc()
            self.error.emit(f'Unexpected error rendering map: {str(e)}')

class ScanWorker(QThread):
    finished = pyqtSignal(int)
    output = pyqtSignal(str)
    progress = pyqtSignal(int)
    
    @staticmethod
    def detect_file_type(file_path: Path):
        """Detect actual file type from magic bytes/file header using smd.utils"""
        from smd.utils import detect_ext_from_bytes
        try:
            with open(file_path, 'rb') as f:
                header = f.read(32) # Read enough bytes
            ext = detect_ext_from_bytes(header)
            return ext.replace('.', '') if ext else None
        except Exception:
            return None

    
    def __init__(self, folder, dry_run=False):
        super().__init__()
        self.folder = folder
        self.dry_run = bool(dry_run)
        self.renamed_count = 0
        self.total_scanned = 0
        self.planned_count = 0
    
    def run(self):
        try:
            folder_path = Path(self.folder)
            if not folder_path.exists() or not folder_path.is_dir():
                self.output.emit(f'Error: Folder not found or not a directory: {folder_path}')
                self.finished.emit(1)
                return

            files = [p for p in sorted(folder_path.rglob('*'))
                     if p.is_file() and p.suffix.lower() in {'.jpg', '.jpeg', '.png', '.heic', '.mp4', '.mov', '.m4v'}]
            total = len(files)
            self.total_scanned = total

            self.output.emit('\n' + '=' * 72)
            title = 'File Extension Checker - Dry-Run Preview' if self.dry_run else 'File Extension Fixer - Magic Byte Scanner'
            self.output.emit(title)
            self.output.emit('=' * 72)
            self.output.emit(f'\nScanning folder: {folder_path}')

            if total == 0:
                self.output.emit('No .jpg/.jpeg/.mp4/.m4v files found to scan.')
                self.progress.emit(100)
                self.finished.emit(0)
                return

            renamed_count = 0
            already_correct = 0
            unrecognized = 0
            errors = 0

            for idx, file_path in enumerate(files, start=1):
                actual_type = self.detect_file_type(file_path)

                if actual_type is None:
                    unrecognized += 1
                    self.output.emit(f'[!] {file_path.name:50} - [unrecognized]')
                else:
                    suffix = file_path.suffix.lower()
                    if (actual_type == 'jpg' and suffix in ['.jpg', '.jpeg']) or \
                       (actual_type == 'mp4' and suffix in ['.mp4', '.m4v']):
                        already_correct += 1
                    else:
                        new_suffix = '.jpg' if actual_type == 'jpg' else '.mp4'
                        new_name = file_path.stem + new_suffix
                        new_path = file_path.parent / new_name

                        if new_path.exists():
                            self.output.emit(f'[!] {file_path.name:50} -> {new_name} (target exists, skipped)')
                            errors += 1
                        else:
                            if self.dry_run:
                                self.planned_count += 1
                                self.output.emit(f'[~] {file_path.name:50} -> {new_name} (planned)')
                            else:
                                try:
                                    file_path.rename(new_path)
                                    renamed_count += 1
                                    self.output.emit(f'[+] {file_path.name:50} -> {new_name}')
                                except Exception as e:
                                    errors += 1
                                    self.output.emit(f'[E] {file_path.name:50} - Error: {e}')

                progress = int((idx / total) * 100)
                self.progress.emit(progress)

            # Summary
            self.output.emit('\n' + '=' * 72)
            self.output.emit('Summary')
            self.output.emit('=' * 72)
            self.output.emit(f'  [+] Renamed:      {renamed_count} files')
            if self.dry_run:
                self.output.emit(f'  [~] Planned:       {self.planned_count} files')
            self.output.emit(f'  [*] Correct:       {already_correct} files')
            self.output.emit(f'  [!] Unrecognized: {unrecognized} files')
            self.output.emit(f'  [E] Errors:       {errors} files')
            self.output.emit(f'  [*] Total:        {total} files scanned')

            self.renamed_count = renamed_count

            if self.dry_run:
                if self.planned_count > 0:
                    self.output.emit(f'\n[~] {self.planned_count} files can be fixed. Click "Apply Fixes" to proceed.')
                else:
                    self.output.emit('\n[*] All files appear correctly labeled!')
            else:
                if renamed_count > 0:
                    self.output.emit(f'\n[+] {renamed_count} files renamed successfully!')
                else:
                    self.output.emit('\n[*] All files have correct extensions!')

            self.finished.emit(0)
        except Exception as e:
            self.output.emit(f'[E] Error: {str(e)}')
            self.finished.emit(1)

class MapWorker(QThread):
    finished = pyqtSignal(list, int, int)  # locations, total_images, total_videos
    progress = pyqtSignal(int, int, int, str, float)  # current, total, found, eta, speed
    file_detail = pyqtSignal(str, str, dict)  # filename, status, metadata
    error = pyqtSignal(str)
    
    def __init__(self, folder, parent_gui, json_path=None):
        super().__init__()
        self.folder = folder
        self.parent_gui = parent_gui
        self.json_path = json_path
        self.cancelled = False
        self.json_coords_lookup = {}  # {filename_stem: (lat, lon)}
        self.scan_report: dict = {}
    
    def process_file(self, file_path):
        """Scan one media file for GPS, extension label, and stats."""
        from smd.map_gps import lookup_json_coords
        from smd.media_types import (
            IMAGE_EXTENSIONS,
            MAGIC_CHECK_EXTENSIONS,
            VIDEO_EXTENSIONS,
            extension_matches_magic,
        )

        suffix = file_path.suffix.lower()
        file_type = None
        embedded_coords = None

        if suffix in IMAGE_EXTENSIONS:
            from smd.metadata import extract_gps_image
            embedded_coords = extract_gps_image(file_path)
            file_type = 'image'
        elif suffix in VIDEO_EXTENSIONS:
            from smd.metadata import extract_gps_video
            embedded_coords = extract_gps_video(file_path)
            file_type = 'video'
        else:
            return None

        coords = embedded_coords
        gps_source = 'embedded' if coords else None
        if not coords and self.json_coords_lookup:
            coords = lookup_json_coords(self.json_coords_lookup, file_path)
            if coords:
                gps_source = 'json'

        extension_mismatch = False
        if suffix in MAGIC_CHECK_EXTENSIONS:
            actual_type = ScanWorker.detect_file_type(file_path)
            extension_mismatch = not extension_matches_magic(suffix, actual_type)

        file_size = file_path.stat().st_size
        base = {
            'filename': file_path.name,
            'path': file_path.as_posix(),
            'full_path': str(file_path),
            'type': file_type,
            'size': file_size,
            'modified': file_path.stat().st_mtime,
            'gps_source': gps_source,
            'extension_mismatch': extension_mismatch,
        }
        if coords:
            base['coords'] = coords
            base['gps_source'] = gps_source
        return base
    
    def run(self):
        try:
            import os
            import time
            
            folder_path = Path(self.folder)
            
            # Build JSON lookup if provided
            if self.json_path and Path(self.json_path).exists():
                try:
                    from smd.map_gps import build_json_coord_lookup
                    from smd.utils import load_memories

                    print(f"DEBUG: MapWorker loading JSON: {self.json_path}")
                    memories = load_memories(Path(self.json_path))
                    self.json_coords_lookup = build_json_coord_lookup(memories)
                except Exception as e:
                    print(f"ERROR loading JSON for mapping: {e}")

            from smd.media_types import MEDIA_EXTENSIONS

            # Collect all media files first
            all_files = [
                f for f in folder_path.rglob('*')
                if f.is_file() and f.suffix.lower() in MEDIA_EXTENSIONS
            ]

            total_files = len(all_files)
            if total_files == 0:
                self.error.emit('No supported media files found')
                self.scan_report = {}
                self.finished.emit([], 0, 0)
                return

            locations = []
            total_images = 0
            total_videos = 0
            file_types: dict[str, dict[str, int]] = {}
            extension_mismatches = 0
            gps_embedded = {'image': 0, 'video': 0}
            gps_json = {'image': 0, 'video': 0}
            gps_missing = {'image': 0, 'video': 0}
            processed = 0
            start_time = time.time()
            last_progress_time = start_time
            
            # Adaptive threading from system profile (GPS scan)
            cpu_count = os.cpu_count() or 2
            perf_mode = getattr(self.parent_gui, 'performance_mode', 'maximum')
            from smd.system_profile import compute_workers, get_system_profile

            settings = compute_workers(perf_mode, get_system_profile(), task="gps")
            max_workers = settings.max_workers
            
            # Adaptive batch processing for ultra-large file sets
            batch_size = min(max_workers * 50, 1000)  # Process in batches to reduce memory pressure
            
            # Adaptive batch processing: prevents memory overflow on ultra-large datasets
            # while maintaining maximum throughput
            batches = [all_files[i:i + batch_size] for i in range(0, len(all_files), batch_size)]
            
            # Track performance metrics for dynamic adjustment
            batch_times = []
            
            for batch_idx, batch in enumerate(batches):
                batch_start_time = time.time()
                
                with ThreadPoolExecutor(max_workers=max_workers) as executor:
                    # Submit batch for processing
                    future_to_file = {executor.submit(self.process_file, f): f for f in batch}
                    
                    # Process results as they complete
                    for future in as_completed(future_to_file):
                        if self.cancelled:
                            executor.shutdown(wait=False, cancel_futures=True)
                            self.error.emit('Scan cancelled by user')
                            self.scan_report = {
                                'total_media': total_images + total_videos,
                                'total_images': total_images,
                                'total_videos': total_videos,
                                'file_types': file_types,
                                'extension_mismatches': extension_mismatches,
                                'gps_embedded': gps_embedded,
                                'gps_json': gps_json,
                                'gps_missing': gps_missing,
                            }
                            self.finished.emit(locations, total_images, total_videos)
                            return
                        
                        file_path = future_to_file[future]
                        processed += 1
                        
                        try:
                            result = future.result()
                            if not result:
                                continue

                            suffix = file_path.suffix.lower()
                            file_type = result['type']
                            file_size = result['size']
                            if file_type == 'image':
                                total_images += 1
                            else:
                                total_videos += 1

                            ext_key = suffix or 'no_extension'
                            if ext_key not in file_types:
                                file_types[ext_key] = {'count': 0, 'size': 0}
                            file_types[ext_key]['count'] += 1
                            file_types[ext_key]['size'] += file_size

                            if result.get('extension_mismatch'):
                                extension_mismatches += 1

                            file_modified = datetime.fromtimestamp(result['modified'])
                            metadata = {
                                'size': file_size,
                                'size_mb': file_size / (1024 * 1024),
                                'modified': file_modified.strftime('%Y-%m-%d %H:%M:%S'),
                                'type': suffix,
                            }

                            gps_source = result.get('gps_source')
                            if gps_source == 'embedded':
                                gps_embedded[file_type] += 1
                            elif gps_source == 'json':
                                gps_json[file_type] += 1
                            else:
                                gps_missing[file_type] += 1

                            if 'coords' in result:
                                locations.append(result)
                                metadata['coords'] = result['coords']
                                metadata['lat'] = f"{result['coords'][0]:.6f}"
                                metadata['lon'] = f"{result['coords'][1]:.6f}"
                                metadata['gps_source'] = gps_source
                                self.file_detail.emit(result['filename'], 'found', metadata)
                            else:
                                self.file_detail.emit(file_path.name, 'no-gps', metadata)
                        except Exception:
                            pass
                        
                        # Calculate ETA and speed
                        elapsed = time.time() - start_time
                        if processed > 10:
                            avg_time_per_file = elapsed / processed
                            remaining_files = total_files - processed
                            eta_seconds = avg_time_per_file * remaining_files
                            if eta_seconds > 60:
                                eta_str = f"{int(eta_seconds / 60)}m {int(eta_seconds % 60)}s"
                            else:
                                eta_str = f"{int(eta_seconds)}s"
                            
                            # Calculate speed (files/sec)
                            files_per_sec = processed / elapsed if elapsed > 0 else 0
                        else:
                            eta_str = "calculating..."
                            files_per_sec = 0
                        
                        # Emit progress every 10 files or at completion
                        if processed % 10 == 0 or processed == total_files:
                            self.progress.emit(processed, total_files, len(locations), eta_str, files_per_sec)
                
                # Track batch performance
                batch_elapsed = time.time() - batch_start_time
                batch_times.append(batch_elapsed)
                
                # Dynamic thread adjustment: if processing is too slow, warn user
                if len(batch_times) >= 2 and perf_mode == 'maximum':
                    avg_batch_time = sum(batch_times) / len(batch_times)
                    # If batches are taking longer than expected, system might be bottlenecked
                    if avg_batch_time > 10 and cpu_count >= 8:
                        # High-end system but slow processing = likely I/O bottleneck
                        pass  # Continue with current settings
            
            self.scan_report = {
                'total_media': total_images + total_videos,
                'total_images': total_images,
                'total_videos': total_videos,
                'file_types': file_types,
                'extension_mismatches': extension_mismatches,
                'gps_embedded': gps_embedded,
                'gps_json': gps_json,
                'gps_missing': gps_missing,
            }
            self.finished.emit(locations, total_images, total_videos)
        except Exception as e:
            self.error.emit(str(e))
            self.scan_report = {}
            self.finished.emit([], 0, 0)

class StagingCheckWorker(QThread):
    """Verify staging folder can be safely deleted."""
    finished = pyqtSignal(object)
    error = pyqtSignal(str)

    def __init__(self, account_dir):
        super().__init__()
        self.account_dir = Path(account_dir)

    def run(self):
        try:
            from smd.account_layout import resolve_account_paths
            from smd.staging_check import check_staging_readiness, save_staging_readiness_report

            paths = resolve_account_paths(self.account_dir, migrate=False, create=False)
            report = check_staging_readiness(self.account_dir, layout=paths)
            save_staging_readiness_report(paths, report)
            self.finished.emit(report)
        except Exception as exc:
            self.error.emit(str(exc))


def _video_frame_pil_image(video_path: Path) -> Image.Image | None:
    """Extract a single preview frame from a video file."""
    from smd.ffmpeg_bundle import resolve_ffmpeg

    ffmpeg = resolve_ffmpeg()
    if not ffmpeg:
        return None
    tmp = Path(tempfile.gettempdir()) / f"smd_dup_thumb_{video_path.stem[:24]}.jpg"
    try:
        startupinfo = None
        creationflags = 0
        if sys.platform.startswith('win'):
            startupinfo = subprocess.STARTUPINFO()
            startupinfo.dwFlags |= subprocess.STARTF_USESHOWWINDOW
            creationflags = subprocess.CREATE_NO_WINDOW
        subprocess.run(
            [
                ffmpeg, '-nostdin', '-y', '-ss', '0.5', '-i', str(video_path),
                '-vframes', '1', '-q:v', '2', str(tmp),
            ],
            capture_output=True,
            timeout=20,
            startupinfo=startupinfo,
            creationflags=creationflags,
        )
        if tmp.is_file() and tmp.stat().st_size > 0:
            return Image.open(tmp)
    except Exception:
        return None
    finally:
        try:
            tmp.unlink(missing_ok=True)
        except OSError:
            pass
    return None


def _pil_preview_image(media_path: Path, max_dim: int) -> Image.Image | None:
    """Load a photo or video frame scaled for on-screen preview."""
    if not media_path.is_file():
        return None
    ext = media_path.suffix.lower()
    try:
        if ext in ('.mp4', '.mov', '.m4v', '.mkv', '.avi'):
            img = _video_frame_pil_image(media_path)
        elif ext in ('.jpg', '.jpeg', '.png', '.bmp', '.gif', '.webp'):
            img = Image.open(media_path)
        else:
            return None
        if img is None:
            return None
        if img.mode in ('RGBA', 'LA', 'P'):
            background = Image.new('RGB', img.size, (255, 255, 255))
            if img.mode == 'P':
                img = img.convert('RGBA')
            if img.mode in ('RGBA', 'LA'):
                background.paste(img, mask=img.split()[-1])
                img = background
        elif img.mode != 'RGB':
            img = img.convert('RGB')
        img.thumbnail((max_dim, max_dim), Image.Resampling.LANCZOS)
        return img
    except Exception:
        return None


def _pixmap_for_media(media_path: Path, max_dim: int) -> QPixmap | None:
    img = _pil_preview_image(media_path, max_dim)
    if img is None:
        return None
    try:
        from PIL import ImageQt

        pix = ImageQt.toqpixmap(img)
        if pix is not None and not pix.isNull():
            return pix
    except Exception:
        pass
    try:
        import io

        from PyQt5.QtGui import QImage, QPixmap

        buf = io.BytesIO()
        img.save(buf, format='JPEG', quality=90)
        qimg = QImage.fromData(buf.getvalue(), 'JPEG')
        if qimg.isNull():
            return None
        return QPixmap.fromImage(qimg)
    except Exception:
        return None


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

        hint = QLabel('Scroll inside each panel to inspect details. Files are byte-identical.')
        hint.setWordWrap(True)
        root.addWidget(hint)

        outer_scroll = QScrollArea()
        outer_scroll.setWidgetResizable(True)
        outer_scroll.setFrameShape(QScrollArea.NoFrame)
        outer_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAsNeeded)
        outer_scroll.setVerticalScrollBarPolicy(Qt.ScrollBarAlwaysOff)

        row_host = QWidget()
        row_host.setObjectName('dialogBody')
        row_lay = QHBoxLayout(row_host)
        row_lay.setSpacing(16)
        row_lay.setContentsMargins(0, 0, 0, 0)

        for name, path in files:
            col = QFrame()
            col.setObjectName('contentPanel')
            from smd.theme import enable_styled_surface

            enable_styled_surface(col)
            col_lay = QVBoxLayout(col)
            col_lay.setSpacing(8)
            col_lay.setContentsMargins(12, 12, 12, 12)

            title = QLabel(name)
            title.setWordWrap(True)
            title.setProperty('class', 'sectionHeader')
            col_lay.addWidget(title)

            preview_scroll = QScrollArea()
            preview_scroll.setWidgetResizable(True)
            preview_scroll.setFrameShape(QScrollArea.NoFrame)
            preview_scroll.setMinimumSize(360, 420)

            preview_host = QWidget()
            preview_lay = QVBoxLayout(preview_host)
            preview_lay.setContentsMargins(0, 0, 0, 0)
            preview_lay.setAlignment(Qt.AlignCenter)

            pixmap = _pixmap_for_media(path, 1280)
            if pixmap is not None and not pixmap.isNull():
                img_label = QLabel()
                img_label.setPixmap(pixmap)
                img_label.setAlignment(Qt.AlignCenter)
                preview_lay.addWidget(img_label)
            elif path.suffix.lower() in ('.mp4', '.mov', '.m4v', '.mkv', '.avi'):
                video_note = QLabel('Video preview unavailable.\nOpen with your default player to inspect.')
                video_note.setAlignment(Qt.AlignCenter)
                video_note.setWordWrap(True)
                preview_lay.addWidget(video_note)
                open_btn = QPushButton('Open video')
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

            preview_scroll.setWidget(preview_host)
            col_lay.addWidget(preview_scroll, 1)
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
        self._keep_both_groups: set[str] = set()

        self.setWindowTitle('Review duplicates - choose keepers')
        self.setMinimumWidth(960)
        self.setMinimumHeight(720)
        self.setObjectName('appDialog')

        root = QVBoxLayout(self)
        root.setSpacing(12)
        root.setContentsMargins(16, 16, 16, 16)

        intro = QLabel(
            'Some files in your library are byte-for-byte identical. '
            'For each group, pick which copy to keep (or choose Keep both). '
            'SMD can copy the extras to a review folder — your main library is not changed.'
        )
        intro.setWordWrap(True)
        root.addWidget(intro)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QScrollArea.NoFrame)
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
            btn_group.setExclusive(True)

            cards_row = QHBoxLayout()
            cards_row.setSpacing(12)
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
                    ),
                    1,
                )
            box_layout.addLayout(cards_row)

            compare_btn = QPushButton('Compare side by side')
            compare_btn.setObjectName('toolbarBtn')
            compare_btn.clicked.connect(
                lambda _checked=False, files=file_paths: self._open_compare(files)
            )
            keep_both_btn = QPushButton('Keep both')
            keep_both_btn.setObjectName('toolbarBtn')
            keep_both_btn.setToolTip('Leave every file in this group in your library (no copies moved)')
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
        copy_btn = QPushButton('Copy non-keepers to review folder')
        copy_btn.setObjectName('accentBtn')
        buttons_row.addWidget(cancel_btn)
        buttons_row.addStretch(1)
        buttons_row.addWidget(copy_btn)
        root.addLayout(buttons_row)

        copy_btn.clicked.connect(self._on_copy_clicked)
        cancel_btn.clicked.connect(self.reject)
        self._apply_theme(scroll, inner)

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
        pixmap = _pixmap_for_media(media_path, 148)
        if pixmap is not None and not pixmap.isNull():
            thumb_btn.setIcon(QIcon(pixmap))
            thumb_btn.setIconSize(QSize(148, 148))
        else:
            thumb_btn.setText('No preview')
        thumb_btn.clicked.connect(lambda _checked=False, files=compare_files: self._open_compare(files))
        lay.addWidget(thumb_btn, alignment=Qt.AlignCenter)

        keeper = QCheckBox('Keep this one')
        keeper.setProperty('dup_filename', filename)
        keeper.setChecked(checked)
        keeper.toggled.connect(
            lambda on, group=btn_group, btn=keeper, prefix=sha_prefix: self._on_keeper_toggled(
                group, btn, on, prefix
            )
        )
        btn_group.addButton(keeper)
        lay.addWidget(keeper, alignment=Qt.AlignCenter)

        name_lbl = QLabel(filename)
        name_lbl.setWordWrap(True)
        name_lbl.setAlignment(Qt.AlignCenter)
        name_lbl.setProperty('class', 'caption')
        lay.addWidget(name_lbl)
        return card

    def _on_keep_both(self, sha_prefix: str, btn_group: QButtonGroup) -> None:
        self._keep_both_groups.add(sha_prefix)
        for btn in btn_group.buttons():
            btn.blockSignals(True)
            btn.setChecked(True)
            btn.blockSignals(False)

    def _on_keeper_toggled(
        self, btn_group: QButtonGroup, toggled_btn: QCheckBox, checked: bool, sha_prefix: str
    ) -> None:
        if not checked:
            return
        self._keep_both_groups.discard(sha_prefix)
        for btn in btn_group.buttons():
            if btn is toggled_btn:
                continue
            btn.blockSignals(True)
            btn.setChecked(False)
            btn.blockSignals(False)

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

    def _keeper_filename(self, btn_group: QButtonGroup, entries_sorted: list) -> str:
        chosen_btn = next((b for b in btn_group.buttons() if b.isChecked()), None)
        if chosen_btn is not None:
            name = chosen_btn.property('dup_filename')
            if name:
                return str(name)
            text = chosen_btn.text().strip()
            if text:
                return text
        return entries_sorted[0].filename if entries_sorted else ''

    def _on_copy_clicked(self) -> None:
        ts = datetime.utcnow().strftime('%Y%m%d_%H%M%S')
        out_dir = self.paths.library_root / f'duplicates_selected_{ts}'
        out_dir.mkdir(parents=True, exist_ok=True)

        selection_report = {
            'generated_at_utc': datetime.utcnow().isoformat() + 'Z',
            'account_name': self.account_name,
            'source_folder': str(self.paths.merged_dir),
            'review_folder': str(out_dir),
            'group_selections': {},
            'copied_non_keeper_files': [],
        }

        copied = 0
        for sha_prefix, entries_sorted, btn_group in self._group_ui:
            if sha_prefix in self._keep_both_groups:
                selection_report['group_selections'][sha_prefix] = {
                    'keeper': 'all',
                    'non_keepers': [],
                }
                continue
            keeper_name = self._keeper_filename(btn_group, entries_sorted)

            non_keepers = [e for e in entries_sorted if e.filename != keeper_name]
            selection_report['group_selections'][sha_prefix] = {
                'keeper': keeper_name,
                'non_keepers': [e.filename for e in non_keepers],
            }

            group_dir = out_dir / sha_prefix
            group_dir.mkdir(parents=True, exist_ok=True)

            for e in non_keepers:
                src = self.paths.merged_dir / e.filename
                if not src.is_file():
                    continue
                dest = group_dir / e.filename
                if dest.exists():
                    dest = group_dir / f"{src.stem}_dup{copied + 1}{src.suffix}"
                shutil.copy2(str(src), str(dest))
                selection_report['copied_non_keeper_files'].append(str(dest))
                copied += 1

        self.paths.reports_dir.mkdir(parents=True, exist_ok=True)
        out_json = self.paths.reports_dir / f'duplicates_selected_report_{ts}.json'
        out_json.write_text(json.dumps(selection_report, indent=2), encoding='utf-8')

        QMessageBox.information(
            self,
            'Duplicates copied',
            f'Copied {copied} non-keeper file(s) to:\n{out_dir}\n\n'
            f'Selection report:\n{out_json}',
        )
        self.accept()


class LocalExportWorker(QThread):
    """Process bundled Snapchat exports (media inside ZIP, no CDN links)."""
    finished = pyqtSignal(int)
    output = pyqtSignal(str)
    progress = pyqtSignal(int, int)

    def __init__(
        self,
        seed_path,
        account_dir,
        json_path=None,
        merge_overlays=True,
        keep_raw=True,
        repair_videos=True,
        performance_mode="maximum",
        zip_paths=None,
        paths=None,
    ):
        super().__init__()
        self.seed_path = Path(seed_path)
        self.account_dir = Path(account_dir)
        self.paths = paths
        self.json_path = Path(json_path) if json_path else None
        self.merge_overlays = merge_overlays
        self.keep_raw = keep_raw
        self.repair_videos = repair_videos
        self.performance_mode = performance_mode
        self.zip_paths = [Path(p) for p in zip_paths] if zip_paths else None
        self.limit = 0
        self._should_cancel = False

    def cancel(self):
        self._should_cancel = True
        self.output.emit('[*] Cancelling processing...')

    def run(self):
        import re
        import threading
        import time
        from smd.local_pipeline import process_bundled_export
        from smd.account_layout import resolve_account_paths

        paths = self.paths or resolve_account_paths(self.account_dir, migrate=True)

        self._heartbeat_running = True
        self._last_status = ""

        def heartbeat():
            while self._heartbeat_running and not self._should_cancel:
                time.sleep(10)
                if self._last_status:
                    self.output.emit(f"⏳ Still working… {self._last_status}")

        threading.Thread(target=heartbeat, daemon=True).start()

        try:
            from smd.system_profile import compute_workers, get_system_profile

            profile = get_system_profile()
            settings = compute_workers(self.performance_mode, profile, task="export")
            self.output.emit(f"⚙️ {profile.summary()}")
            self.output.emit(
                f"⚙️ {settings.reason}: {settings.max_workers} parallel jobs, "
                f"max {settings.max_ffmpeg} ffmpeg × {settings.ffmpeg_threads} threads"
            )

            checkpoint = paths.checkpoint_path

            def status_callback(msg):
                self._last_status = msg
                m = re.search(r"Processing (\d+)/(\d+)", msg)
                if m:
                    current = int(m.group(1))
                    total_n = int(m.group(2))
                    self.progress.emit(current, total_n)
                    # Log every 25 files to avoid flooding Qt (was crashing GUI)
                    if current <= 3 or current % 25 == 0:
                        self.output.emit(msg)
                elif msg.startswith("⏳"):
                    pass  # heartbeat handled separately
                else:
                    self.output.emit(msg)

            stats = process_bundled_export(
                self.seed_path,
                self.account_dir,
                merge_overlays=self.merge_overlays,
                keep_raw=self.keep_raw,
                repair_videos=self.repair_videos,
                limit=self.limit,
                apply_meta=True,
                json_path=self.json_path or paths.json_path,
                status_callback=status_callback,
                should_stop=lambda: self._should_cancel,
                checkpoint_path=checkpoint,
                max_workers=settings.max_workers,
                max_ffmpeg=settings.max_ffmpeg,
                ffmpeg_threads=settings.ffmpeg_threads,
                zip_paths=self.zip_paths,
                layout=paths,
            )
            self.run_stats = stats
            for line in stats.summary_lines():
                self.output.emit(line)
            self.finished.emit(0 if not self._should_cancel else 1)
        except Exception as e:
            self.output.emit(f"Error in local export: {e}")
            import traceback
            tb = traceback.format_exc()
            self.output.emit(tb)
            try:
                log = paths.logs_dir / "processing_error.log"
                log.write_text(tb, encoding="utf-8")
            except OSError:
                pass
            self.finished.emit(1)
        finally:
            self._heartbeat_running = False


class LiveRunDashboard(QWidget):
    """Live processing dashboard: stat cards + activity log."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("liveRunDashboard")
        from smd.theme import enable_styled_surface

        enable_styled_surface(self)
        self.setAttribute(Qt.WA_StyledBackground, True)
        self.setVisible(False)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Preferred)

        root = QVBoxLayout(self)
        root.setContentsMargins(12, 12, 12, 12)
        root.setSpacing(10)

        header = QHBoxLayout()
        title = QLabel("Live run dashboard")
        title.setProperty("class", "sectionTitle")
        header.addWidget(title)
        header.addStretch(1)
        self.header_hint = QLabel("")
        self.header_hint.setProperty("class", "caption")
        header.addWidget(self.header_hint)
        root.addLayout(header)

        grid = QGridLayout()
        grid.setHorizontalSpacing(10)
        grid.setVerticalSpacing(10)

        self.stat_pct = self._stat_card("Progress", "0%")
        self.stat_files = self._stat_card("Files", "0 / 0")
        self.stat_speed = self._stat_card("Speed", "-")
        self.stat_eta = self._stat_card("Time left", "-")
        self.stat_elapsed = self._stat_card("Elapsed", "0:00")
        self.stat_phase = self._stat_card("Step", "Waiting")

        grid.addWidget(self.stat_pct[0], 0, 0)
        grid.addWidget(self.stat_files[0], 0, 1)
        grid.addWidget(self.stat_speed[0], 0, 2)
        grid.addWidget(self.stat_eta[0], 1, 0)
        grid.addWidget(self.stat_elapsed[0], 1, 1)
        grid.addWidget(self.stat_phase[0], 1, 2)
        root.addLayout(grid)

        self.status_line = QLabel("Ready to start.")
        self.status_line.setWordWrap(True)
        self.status_line.setProperty("status", "neutral")
        root.addWidget(self.status_line)

        self.log = QPlainTextEdit()
        self.log.setObjectName("runActivityLog")
        self.log.setReadOnly(True)
        self.log.setMinimumHeight(160)
        self.log.setMaximumBlockCount(600)
        root.addWidget(self.log, 1)

    def _stat_card(self, title: str, initial: str) -> tuple[QFrame, QLabel]:
        card = QFrame()
        card.setObjectName("runStatCard")
        from smd.theme import enable_styled_surface

        enable_styled_surface(card)
        card.setAttribute(Qt.WA_StyledBackground, True)
        is_progress = title == "Progress"
        card.setMinimumHeight(76 if is_progress else 68)
        lay = QVBoxLayout(card)
        lay.setContentsMargins(12, 10, 12, 12)
        lay.setSpacing(6)
        lbl = QLabel(title)
        lbl.setObjectName("runStatTitle")
        val = QLabel(initial)
        val.setObjectName("runStatValueLarge" if is_progress else "runStatValue")
        val.setWordWrap(True)
        if is_progress:
            val.setMinimumHeight(34)
            val.setAlignment(Qt.AlignLeft | Qt.AlignVCenter)
        lay.addWidget(lbl)
        lay.addWidget(val)
        return card, val

    def reset(self, *, planned_estimate: str | None = None) -> None:
        self.set_value(self.stat_pct[1], "0%")
        self.set_value(self.stat_files[1], "0 / 0")
        self.set_value(self.stat_speed[1], "-")
        self.set_value(self.stat_eta[1], "-")
        self.set_value(self.stat_elapsed[1], "0:00")
        self.set_value(self.stat_phase[1], "Starting")
        self.status_line.setText("Starting…")
        self.log.clear()
        if planned_estimate:
            self.header_hint.setText(f"Planned ~{planned_estimate}")
        else:
            self.header_hint.setText("")

    def set_value(self, label: QLabel, text: str) -> None:
        label.setText(text)

    def update_stats(
        self,
        *,
        pct: int | None = None,
        files_current: int | None = None,
        files_total: int | None = None,
        speed: str | None = None,
        eta: str | None = None,
        elapsed: str | None = None,
        phase: str | None = None,
        status: str | None = None,
        status_kind: str = "info",
    ) -> None:
        if pct is not None:
            self.set_value(self.stat_pct[1], f"{max(0, min(100, pct))}%")
        if files_current is not None and files_total is not None:
            self.set_value(self.stat_files[1], f"{files_current:,} / {files_total:,}")
        if speed is not None:
            self.set_value(self.stat_speed[1], speed)
        if eta is not None:
            self.set_value(self.stat_eta[1], eta)
        if elapsed is not None:
            self.set_value(self.stat_elapsed[1], elapsed)
        if phase is not None:
            self.set_value(self.stat_phase[1], phase)
        if status is not None:
            self.status_line.setText(status)
            from smd.theme import apply_status_property

            apply_status_property(self.status_line, status_kind)


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
        self.init_ui()
        self.processing_shield = ProcessingShieldOverlay(self, on_cancel=self.cancel_download)
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
                        'Update required',
                        'This copy of SMD cannot process bundled ZIP exports.\n\n'
                        'Please install the latest version of Snapchat Memories Downloader.',
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

    def _apply_technical_view_ui(self) -> None:
        technical = self._technical_view_enabled()
        for widget in (
            getattr(self, 'open_technical_btn', None),
            getattr(self, 'verify_staging_btn', None),
            getattr(self, 'open_debug_btn', None),
            getattr(self, 'technical_storage_label', None),
        ):
            if widget is not None:
                widget.setVisible(technical)
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
        """Clean up temporary files when app closes."""
        try:
            # Delete temp map files
            temp_files = ['temp_default_map.html', 'temp_gps_map.html']
            for filename in temp_files:
                temp_path = Path(filename)
                if temp_path.exists():
                    temp_path.unlink()
        except Exception:
            pass
        event.accept()

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
        title_col.setSpacing(0)
        header = QLabel('Snapchat Memories Downloader')
        header.setProperty('class', 'pageTitle')
        subtitle = QLabel(f'Version {__version__}')
        subtitle.setProperty('class', 'caption')
        title_col.addWidget(header)
        title_col.addWidget(subtitle)
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
        self.save_raw_chk = QCheckBox('Also save without filters (optional, more disk space)')
        self.save_raw_chk.setChecked(False)
        self.save_raw_chk.setToolTip(
            'Keeps a second copy of each memory without filters, stickers, or text overlays. '
            'Useful if you want the clean photo or video underneath.'
        )
        self.save_raw_chk.stateChanged.connect(self._on_save_raw_changed)

        self.technical_view_chk = QCheckBox('Technical view (advanced folders and troubleshooting)')
        self.technical_view_chk.setToolTip(
            'Shows staging, checkpoints, reports, and other working data used by SMD. '
            'Leave off for a simple Desktop folder with just your memories.'
        )
        stored_tv = QSettings('SnapchatMemories', 'Downloader').value('technical_view', False)
        self.technical_view_chk.setChecked(str(stored_tv).lower() in ('1', 'true', 'yes'))
        self.technical_view_chk.stateChanged.connect(self._on_technical_view_changed)

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
            'Scan merged/ for byte-identical duplicates, let you pick one keeper per group, '
            'then copy the non-keepers to a review folder (merged/ is not modified).'
        )
        self.review_duplicates_btn.clicked.connect(self.review_duplicates)

        self.open_debug_btn = QPushButton('Open debug folder')
        self.open_debug_btn.setObjectName('toolbarBtn')
        self.open_debug_btn.setToolTip('Opens technical/debug/ - processing logs and failed items')
        self.open_debug_btn.clicked.connect(self.open_debug_folder)

        after_grid.addWidget(self.open_folder_btn, 0, 0)
        after_grid.addWidget(self.review_duplicates_btn, 0, 1)
        after_grid.addWidget(self.open_technical_btn, 1, 0)
        after_grid.addWidget(self.verify_staging_btn, 1, 1)
        after_grid.addWidget(self.open_debug_btn, 2, 0)
        after_lay.addLayout(after_grid)

        self._setup_section = setup_box
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
            'Pick a folder to check and fix file extensions, verify metadata, and build a GPS map. '
            'Defaults to merged/ when a project exists.'
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
        map_layout = QHBoxLayout(map_widget)
        map_layout.setContentsMargins(8, 8, 8, 8)
        if WEB_ENGINE_AVAILABLE and QWebEngineView is not None:
            self.map_view = QWebEngineView()
        else:
            self.map_view = QTextBrowser()
            self.map_view.setOpenExternalLinks(True)
            self.map_view.setHtml(
                "<h3>GPS Map requires Qt WebEngine</h3>"
                "<p>The map will open in your default browser after rendering.</p>"
            )
        map_layout.addWidget(self.map_view, 1)
        self.media_viewer = MediaViewer()
        self.media_viewer.setMinimumWidth(180)
        self.media_viewer.setMaximumWidth(320)
        self.media_viewer.setVisible(False)
        map_layout.addWidget(self.media_viewer)
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
        tab_bar.setExpanding(True)
        tab_bar.setUsesScrollButtons(False)

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
        
        # Performance mode: 'balanced', 'maximum', 'conservative'
        self.performance_mode = 'maximum'
        self._last_power_on_battery: bool | None = None
        self.power_watch_timer = QTimer()
        self.power_watch_timer.timeout.connect(self.refresh_system_profile)
        self.power_watch_timer.start(30_000)

        self.refresh_system_profile()
        settings = QSettings("SMD", "SnapchatMemoriesDownloader")
        if not settings.value("auto_perf_applied_v1", False, type=bool):
            self.apply_recommended_settings(silent=True)
            settings.setValue("auto_perf_applied_v1", True)

        self.update_export_ui_mode()

        # Defer map HTML load so the main window appears immediately.
        QTimer.singleShot(200, self.init_default_map)
    
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
        self.performance_mode = mode_map.get(index, 'maximum')
        self.refresh_system_profile()
        self.update_export_ui_mode()
    
    def _account_name(self) -> str:
        return self.account_input.text().strip()

    @staticmethod
    def _is_valid_account_name(name: str) -> bool:
        if not name or name in ('.', '..'):
            return False
        return not any(ch in name for ch in '<>:"/\\|?*')

    def _rebuild_process_controls_grid(self) -> None:
        """Simple layout: export full-width; technical view adds Performance column."""
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
        if technical:
            grid.addWidget(self._setup_section, 0, 0)
            grid.addWidget(self._perf_section, 0, 1)
            grid.addWidget(self._run_section, 1, 0)
            grid.addWidget(self._after_section, 1, 1)
        else:
            grid.addWidget(self._setup_section, 0, 0, 1, 2)
            grid.addWidget(self._run_section, 1, 0)
            grid.addWidget(self._after_section, 1, 1)
        for col in range(2):
            grid.setColumnStretch(col, 1)

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
        if name:
            self.update_download_path_label(name, create=False)

    def update_download_path_label(self, account_name: str, *, create: bool = False) -> None:
        try:
            from smd.account_layout import format_bytes, technical_storage_summary

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
                rows = technical_storage_summary(paths)
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
            else:
                self.technical_storage_label.setText('')
        except Exception:
            self.download_path_label.setText('Folder: (unavailable)')
            self.technical_storage_label.setText('')
        self._refresh_after_processing_actions()

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
            for line in self._run_log_buffer[-80:]:
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
            for line in self._run_log_buffer[-80:]:
                self.live_run_dashboard.log.appendPlainText(line)

    def append_debug_message(self, message: str):
        """Append a message to the live dashboard log and update step hints."""
        if not hasattr(self, "live_run_dashboard"):
            return
        timestamp = datetime.now().strftime("%H:%M:%S")
        line = f"[{timestamp}] {message}"
        self._run_log_buffer.append(line)
        if len(self._run_log_buffer) > 400:
            self._run_log_buffer.pop(0)

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
        path = Path(media_path)
        try:
            if path.suffix.lower() in ('.mp4', '.mov', '.m4v', '.mkv', '.avi'):
                return self._video_frame_thumbnail_b64(path, max_size)
            img = Image.open(path)
            if img.mode in ('RGBA', 'LA', 'P'):
                background = Image.new('RGB', img.size, (255, 255, 255))
                if img.mode == 'P':
                    img = img.convert('RGBA')
                if img.mode in ('RGBA', 'LA'):
                    background.paste(img, mask=img.split()[-1])
                    img = background
            img.thumbnail((max_size, max_size), Image.Resampling.LANCZOS)
            import io
            buffer = io.BytesIO()
            img.save(buffer, format='JPEG', quality=90)
            img_base64 = base64.b64encode(buffer.getvalue()).decode('utf-8')
            return f"data:image/jpeg;base64,{img_base64}"
        except Exception:
            return None

    def _video_frame_thumbnail_b64(self, video_path: Path, max_size: int = 150):
        """Extract one frame with ffmpeg for map popup."""
        from smd.ffmpeg_bundle import resolve_ffmpeg
        ffmpeg = resolve_ffmpeg()
        if not ffmpeg:
            return None
        tmp = Path(tempfile.gettempdir()) / f"smd_thumb_{video_path.stem[:20]}.jpg"
        try:
            startupinfo = None
            creationflags = 0
            if sys.platform.startswith('win'):
                startupinfo = subprocess.STARTUPINFO()
                startupinfo.dwFlags |= subprocess.STARTF_USESHOWWINDOW
                creationflags = subprocess.CREATE_NO_WINDOW
            subprocess.run(
                [
                    ffmpeg, '-nostdin', '-y', '-ss', '0.5', '-i', str(video_path),
                    '-vframes', '1', '-q:v', '2', str(tmp),
                ],
                capture_output=True,
                timeout=15,
                startupinfo=startupinfo,
                creationflags=creationflags,
                check=False,
            )
            if not tmp.is_file() or tmp.stat().st_size < 100:
                return None
            img = Image.open(tmp)
            img.thumbnail((max_size, max_size), Image.Resampling.LANCZOS)
            import io
            buffer = io.BytesIO()
            img.convert('RGB').save(buffer, format='JPEG', quality=90)
            return f"data:image/jpeg;base64,{base64.b64encode(buffer.getvalue()).decode('utf-8')}"
        except Exception:
            return None
        finally:
            try:
                tmp.unlink(missing_ok=True)
            except OSError:
                pass

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

            self.map_render_worker = MapRenderWorker(locations, self)
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
        """Cancel ongoing map scan"""
        if hasattr(self, 'map_worker') and self.map_worker.isRunning():
            self.map_worker.cancelled = True
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
            print(f"DEBUG: Map file path: {html_file_path}")
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
        extensions_fixed = scan_report.get('extensions_fixed', 0)

        output = "\n" + "=" * 60 + "\n"
        output += "📊 MEDIA STATISTICS\n"
        output += "=" * 60 + "\n"
        output += f"📁 Folder: {folder_name}\n"
        output += f"📊 Media files: {total_media:,} ({total_images:,} photos, {total_videos:,} videos)\n"
        output += f"💾 Total size: {format_bytes(total_size)}\n"
        if extensions_fixed:
            output += f"🔧 Extensions fixed: {extensions_fixed:,}\n"
        if mismatches:
            output += f"⚠ Wrong extension remaining: {mismatches:,}\n"
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
        if getattr(self, '_last_extensions_fixed', 0):
            report['extensions_fixed'] = self._last_extensions_fixed
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
        base_text = f'Fixing file extensions... {value}%'
        if self.status_animation_active:
            self.status_base_text = base_text
        else:
            self.start_status_animation(base_text)

    def on_scan_finished_in_full_workflow(self, return_code: int) -> None:
        """After extension fix — continue to GPS scan and map."""
        self.stop_status_animation()
        if return_code != 0:
            self._apply_status(self.unified_status, 'Extension fix failed', 'err')
            self.full_analysis_mode = False
            self._set_browse_scan_busy(False)
            return

        renamed = getattr(self.scan_worker, 'renamed_count', 0)
        total = getattr(self.scan_worker, 'total_scanned', 0)
        self._last_extensions_fixed = renamed
        if renamed:
            self.scan_output.append(
                f"\n🔧 Fixed {renamed} mislabeled file(s) out of {total} checked.\n"
            )
        else:
            self.scan_output.append(f"\n✓ All {total} checked extensions look correct.\n")

        self.unified_progress.setValue(0)
        self._apply_status(self.unified_status, 'Step 2/3: Scanning media and GPS...', 'info')
        self._start_map_worker(full_workflow=True)

    def run_full_analysis(self):
        """Check folder: fix extensions → media stats + GPS → map."""
        if not self.selected_scan:
            QMessageBox.warning(self, 'Error', 'Please select a folder first')
            return

        self.full_analysis_mode = True
        self._set_browse_scan_busy(True)
        self._last_extensions_fixed = 0

        self.scan_output.clear()
        json_path = self._mapping_json_for_scan(self.selected_scan)
        if json_path:
            self.scan_output.append(
                f"GPS lookup: using {Path(json_path).name} for files missing embedded coordinates.\n"
            )
        self.unified_progress.setValue(0)
        self._apply_status(self.unified_status, 'Step 1/3: Fixing file extensions...', 'info')

        self.scan_worker = ScanWorker(self.selected_scan, dry_run=False)
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
            self.map_render_worker = MapRenderWorker(gps_data, self)
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
            self._show_run_dashboard(reset=True)
            self.download_cancelled = False
            self.download_running = True
            self._refresh_after_processing_actions()
            self.download_btn.setText('Cancel')
            self.download_btn.setToolTip('Stop the current operation.')
            if hasattr(self, 'processing_shield'):
                self.processing_shield.show_over()

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
            if hasattr(self, 'processing_shield'):
                self.processing_shield.hide()
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
            play_happy_tone()
            account_name = self._account_name()
            paths = self._account_paths(account_name)
            report = None
            keep_raw = self.save_raw_chk.isChecked()
            try:
                stats = getattr(getattr(self, 'local_export_worker', None), 'run_stats', None)
                from smd.account_layout import format_bytes
                from smd.session_report import build_session_report, save_session_report
                from smd.staging_check import check_staging_readiness, delete_staging_folder

                readiness = check_staging_readiness(
                    paths.account_dir, layout=paths, require_raw=keep_raw
                )
                staging_deleted = False
                staging_freed = ""
                if readiness.safe_to_delete:
                    ok, _msg = delete_staging_folder(
                        paths.account_dir, report=readiness, layout=paths
                    )
                    if ok:
                        staging_deleted = True
                        staging_freed = format_bytes(readiness.staging_bytes)

                report = build_session_report(
                    paths.account_dir,
                    stats=stats,
                    success=True,
                    require_raw=keep_raw,
                    staging_deleted=staging_deleted,
                    staging_freed=staging_freed,
                    layout=paths,
                )
                save_session_report(paths, report)
                dlg = SessionSummaryDialog(report, paths.library_root, paths.reports_dir, self)
                dlg.exec_()
                if hasattr(self, 'processing_shield'):
                    self.processing_shield.hide()
                QTimer.singleShot(
                    0,
                    lambda an=account_name, p=paths, r=report: self._after_processing_summary(an, p, r),
                )
            except Exception as exc:
                print(f"Session summary error: {exc}")
                if hasattr(self, 'processing_shield'):
                    self.processing_shield.hide()
        else:
            if hasattr(self, 'processing_shield'):
                self.processing_shield.hide()
            if getattr(self, 'download_cancelled', False):
                self._apply_status(self.status_label, '⏹ Stopped. Click Start to resume with the same account name.', "warn")
            else:
                tail = '\n'.join(self.download_log_lines[-12:]) if self.download_log_lines else 'No output was captured.'
                title = 'Processing Failed'

                if 'permission' in tail.lower():
                    error_msg = 'The app does not have permission to access that folder.\n\nCheck Windows security settings and try again.'
                elif 'no module' in tail.lower() or 'local_pipeline' in tail.lower():
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

    def _refresh_map_for_theme(self) -> None:
        """Re-render the map when switching light/dark so basemap tiles match the UI theme."""
        locations = getattr(self, '_last_map_locations', None)
        if locations:
            worker = getattr(self, 'map_render_worker', None)
            if worker is not None and worker.isRunning():
                return
            self.map_render_worker = MapRenderWorker(locations, self)
            self.map_render_worker.finished.connect(self.on_map_render_finished)
            self.map_render_worker.error.connect(self.on_map_render_error)
            self.map_render_worker.start()
            return
        try:
            self.init_default_map()
        except Exception:
            pass

    def toggle_dark_mode(self):
        from smd.theme import THEME_DARK, THEME_LIGHT

        self.dark_mode_enabled = not self.dark_mode_enabled
        QSettings('SnapchatMemories', 'Downloader').setValue(
            'theme_mode', THEME_DARK if self.dark_mode_enabled else THEME_LIGHT
        )
        self._apply_current_theme()
        self._refresh_map_for_theme()

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
            from smd.duplicates import load_cached_duplicate_report, scan_content_duplicates

            report = load_cached_duplicate_report(paths)
            if not report or not report.duplicate_groups:
                report = scan_content_duplicates(paths, move_to_folder=False)
            if not report.duplicate_groups:
                return
            self._show_duplicate_review_dialog(account_name, paths, report)
        except Exception as exc:
            print(f"Duplicate review error: {exc}")
            QMessageBox.warning(
                self,
                'Review duplicates',
                'Could not open duplicate review.\n\n'
                'Your finished photos and videos are already saved — this step is optional.',
            )

    def review_duplicates(self):
        account_name = self._account_name()
        if not account_name:
            QMessageBox.information(self, 'Duplicates', 'Enter an account name first.')
            return
        paths = self._account_paths(account_name)
        try:
            from smd.duplicates import scan_content_duplicates

            report = scan_content_duplicates(paths, move_to_folder=False)
            if not report.duplicate_groups:
                QMessageBox.information(
                    self,
                    'Duplicates',
                    f'Scanned {report.merged_scanned} files - no byte-identical duplicates found.',
                )
                return
            self._show_duplicate_review_dialog(account_name, paths, report)
        except Exception as exc:
            print(f"Duplicate review error: {exc}")
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


_SMD_GUI_SCRIPT = (ROOT / 'desktop_gui_pyqt.py').resolve()


def _startup_log(message: str) -> None:
    """Append startup diagnostics to smd_gui.log (works under pythonw)."""
    try:
        with (ROOT / 'smd_gui.log').open('a', encoding='utf-8') as log_file:
            log_file.write(message.rstrip() + '\n')
            log_file.flush()
    except OSError:
        pass


def _cmdline_runs_smd_gui(cmdline: list) -> bool:
    """True only when cmdline is actually executing desktop_gui_pyqt.py (not -c one-liners)."""
    if len(cmdline) < 2:
        return False
    if cmdline[1] in ('-c', '-m'):
        return False
    script_name = _SMD_GUI_SCRIPT.name
    for arg in cmdline[1:]:
        if arg.startswith('-'):
            continue
        try:
            if Path(arg).resolve() == _SMD_GUI_SCRIPT:
                return True
        except (OSError, ValueError):
            pass
        normalized = str(arg).replace('\\', '/')
        if normalized.endswith('/' + script_name) or normalized == script_name:
            return True
    return False


def _process_runs_smd_gui(proc: psutil.Process, my_pid=None) -> bool:
    if my_pid is not None and proc.pid == my_pid:
        return False
    try:
        name = (proc.name() or '').lower()
        if 'python' not in name:
            return False
        return _cmdline_runs_smd_gui(proc.cmdline())
    except (psutil.NoSuchProcess, psutil.AccessDenied):
        return False


class SingleInstance:
    """Ensures only one instance of the application can run at a time"""
    def __init__(self, port=58923):  # Changed to different port
        self.port = port
        self.socket = None
        self.lock_file = None
        self.lock_path = Path(tempfile.gettempdir()) / 'snapchat_memories_gui.lock'
        self.signal_file = Path(tempfile.gettempdir()) / 'snapchat_memories_show.signal'
        
    def force_takeover(self) -> None:
        """Terminate a stuck prior instance and clear the lock so we can start fresh."""
        pid = None
        try:
            if self.lock_path.exists():
                pid_str = self.lock_path.read_text(encoding='utf-8').strip()
                if pid_str.isdigit():
                    pid = int(pid_str)
        except OSError:
            pass
        if pid is not None and pid != os.getpid():
            try:
                proc = psutil.Process(pid)
                if proc.is_running() and _process_runs_smd_gui(proc):
                    print(f"DEBUG: Terminating unresponsive instance PID {pid}")
                    proc.terminate()
                    proc.wait(timeout=3)
            except (psutil.NoSuchProcess, psutil.TimeoutExpired, psutil.AccessDenied):
                try:
                    if pid is not None:
                        psutil.Process(pid).kill()
                except Exception:
                    pass
            except Exception as exc:
                print(f"DEBUG: force_takeover: {exc}")
        try:
            if self.lock_path.exists():
                self.lock_path.unlink()
        except OSError:
            pass
        try:
            if self.signal_file.exists():
                self.signal_file.unlink()
        except OSError:
            pass

    def is_already_running(self):
        """Check if another instance is already running"""
        # First, try file-based locking (more reliable on Windows)
        try:
            # Check if lock file exists and process is still running
            if self.lock_path.exists():
                try:
                    pid_str = self.lock_path.read_text().strip()
                    if pid_str.isdigit():
                        pid = int(pid_str)
                        # Check if process is still running
                        if psutil.pid_exists(pid):
                            try:
                                proc = psutil.Process(pid)
                                proc_name = proc.name().lower()
                                print(f"DEBUG: Found process {pid} with name: {proc_name}")
                                # Check if it's Python and running this script
                                if 'python' in proc_name:
                                    try:
                                        cmdline = proc.cmdline()
                                        print(f"DEBUG: Process command line: {cmdline}")
                                        if _cmdline_runs_smd_gui(cmdline):
                                            print(f"DEBUG: Confirmed running instance with PID {pid}")
                                            return True
                                    except (psutil.AccessDenied, psutil.NoSuchProcess):
                                        # If we can't get cmdline, assume it's our process
                                        print(f"DEBUG: Found running Python instance with PID {pid}")
                                        return True
                            except (psutil.NoSuchProcess, psutil.AccessDenied) as e:
                                print(f"DEBUG: Process {pid} no longer accessible: {e}")
                                pass
                except Exception as e:
                    print(f"DEBUG: Error checking lock file: {e}")
                
                # Lock file is stale, remove it
                print(f"DEBUG: Removing stale lock file")
                try:
                    self.lock_path.unlink()
                except Exception:
                    pass
            
            # Create new lock file
            self.lock_file = open(self.lock_path, 'w')
            self.lock_file.write(str(os.getpid()))
            self.lock_file.flush()
            print(f"DEBUG: Created lock file with PID {os.getpid()}")
            
            # Register cleanup on exit
            atexit.register(self.cleanup)
            return False
            
        except Exception as e:
            print(f"DEBUG: Error in is_already_running: {e}")
            return False
    
    def cleanup(self):
        """Clean up resources"""
        try:
            if self.lock_file:
                self.lock_file.close()
            if self.lock_path and self.lock_path.exists():
                self.lock_path.unlink()
            if self.signal_file and self.signal_file.exists():
                self.signal_file.unlink()
        except Exception:
            pass

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
