"""Reusable Qt widgets for the SMD desktop GUI."""
from __future__ import annotations

import os
import subprocess
import sys

from PIL import Image
from PyQt5.QtCore import Qt, QObject, QTimer, pyqtSignal, QSize, QRect
from PyQt5.QtGui import QFontMetrics, QPixmap
from PyQt5.QtWidgets import (
    QApplication, QWidget, QVBoxLayout, QHBoxLayout, QGridLayout, QPushButton,
    QLabel, QLayout, QTextBrowser, QTextEdit, QFrame, QPlainTextEdit,
    QSizePolicy, QTabBar, QTabWidget, QScrollArea,
)


class StreamRedirector(QObject):
    """Redirect stdout/stderr lines into the GUI debug console.

    write() may be called from any thread (workers use print()), so lines are
    delivered through a queued Qt signal instead of touching widgets directly.
    """

    line_written = pyqtSignal(str)

    def __init__(self, callback):
        super().__init__()
        import threading

        self._lock = threading.Lock()
        self._buffer = ""
        # Queued connection: slot always runs on the GUI thread.
        self.line_written.connect(callback, Qt.QueuedConnection)

    def write(self, text: str) -> None:
        if not text:
            return
        lines = []
        with self._lock:
            self._buffer += text
            while "\n" in self._buffer:
                line, self._buffer = self._buffer.split("\n", 1)
                if line:
                    lines.append(line.rstrip())
        for line in lines:
            self.line_written.emit(line)

    def flush(self) -> None:
        with self._lock:
            pending, self._buffer = self._buffer, ""
        if pending:
            self.line_written.emit(pending.rstrip())

    def isatty(self) -> bool:
        return False


class FlowLayout(QLayout):
    """Lays out child widgets left-to-right, wrapping to a new row when the
    next item would not fit. Unlike QHBoxLayout, it never demands more width
    than it is given, so a scroll area hosting it only ever needs to scroll
    vertically - never horizontally."""

    def __init__(self, parent=None, margin: int = 0, spacing: int = 12):
        super().__init__(parent)
        if parent is not None:
            self.setContentsMargins(margin, margin, margin, margin)
        self._item_list = []
        self._spacing = spacing

    def __del__(self):
        while self.count():
            self.takeAt(0)

    def addItem(self, item):
        self._item_list.append(item)

    def count(self) -> int:
        return len(self._item_list)

    def itemAt(self, index):
        if 0 <= index < len(self._item_list):
            return self._item_list[index]
        return None

    def takeAt(self, index):
        if 0 <= index < len(self._item_list):
            return self._item_list.pop(index)
        return None

    def expandingDirections(self):
        return Qt.Orientation(0)

    def hasHeightForWidth(self) -> bool:
        return True

    def heightForWidth(self, width: int) -> int:
        return self._do_layout(QRect(0, 0, width, 0), test_only=True)

    def setGeometry(self, rect) -> None:
        super().setGeometry(rect)
        self._do_layout(rect, test_only=False)

    def sizeHint(self):
        return self.minimumSize()

    def minimumSize(self):
        size = QSize()
        for item in self._item_list:
            size = size.expandedTo(item.minimumSize())
        left, top, right, bottom = self.getContentsMargins()
        size += QSize(left + right, top + bottom)
        return size

    def _do_layout(self, rect, test_only: bool) -> int:
        left, top, right, bottom = self.getContentsMargins()
        effective_rect = rect.adjusted(left, top, -right, -bottom)
        x = effective_rect.x()
        y = effective_rect.y()
        line_height = 0
        spacing = self._spacing

        for item in self._item_list:
            item_size = item.sizeHint()
            next_x = x + item_size.width() + spacing
            if next_x - spacing > effective_rect.right() and line_height > 0:
                x = effective_rect.x()
                y = y + line_height + spacing
                next_x = x + item_size.width() + spacing
                line_height = 0
            if not test_only:
                item.setGeometry(QRect(x, y, item_size.width(), item_size.height()))
            x = next_x
            line_height = max(line_height, item_size.height())

        return y + line_height - rect.y() + bottom


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
        self._syncing_height = False
        self.document().contentsChanged.connect(self._sync_height)
        QTimer.singleShot(0, self._sync_height)

    def _sync_height(self) -> None:
        # Guard: setTextWidth fires contentsChanged and setMin/MaxHeight fires
        # resizeEvent, both of which land back here - unguarded this recurses
        # until the C stack overflows (Windows fail-fast 0xC0000409).
        if self._syncing_height:
            return
        self._syncing_height = True
        try:
            width = self.viewport().width()
            if width > 0 and self.document().textWidth() != width:
                self.document().setTextWidth(width)
            margin = self.document().documentMargin()
            height = int(self.document().size().height()) + int(margin * 2) + 4
            if self.minimumHeight() != height or self.maximumHeight() != height:
                self.setMinimumHeight(height)
                self.setMaximumHeight(height)
        finally:
            self._syncing_height = False

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self._sync_height()


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

    def _reference_width(self) -> int:
        """Width to size against. Prefer the main QTabWidget over self.width():
        once _content's minimum width is raised, self.width() can never report a
        smaller number afterwards (the layout won't shrink us below our own
        content's minimum), which would otherwise wedge this column at whatever
        width it first happened to compute during the very first layout pass.
        QTabWidget#mainTabs is also reliable for columns that live on a tab page
        that isn't the current page yet - a hidden page's own width can be
        stale, but the always-visible tab widget itself is up to date."""
        top = self.window()
        tabs = top.findChild(QTabWidget, 'mainTabs') if top is not None else None
        if tabs is not None and tabs.width() > 0:
            return tabs.width()
        parent = self.parentWidget()
        if parent is not None and parent.width() > 0:
            return parent.width()
        return self.width()

    def _apply_content_width(self) -> None:
        left, _top, right, _bottom = self._margins
        available = max(0, self._reference_width() - left - right)
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
    """Full-window dark tint used only for the brief, non-cancelable, read-only
    post-run verification step (see StagingVerifyWorker). While a run is
    actively processing, Setup/Performance/After-processing are dimmed
    per-section instead (see _set_run_lockout) so the Run section's
    Start/Cancel button and the live dashboard stay clickable and scrollable
    - this overlay used to cover the whole window during the active run too,
    which blocked scrolling the dashboard and made SMD look unresponsive."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName('processingShield')
        self.setAttribute(Qt.WA_StyledBackground, True)
        self.setStyleSheet('background-color: rgba(0, 0, 0, 165);')
        self.hide()

        outer = QVBoxLayout(self)
        outer.setContentsMargins(32, 32, 32, 32)
        outer.addStretch(2)

        self._panel = QFrame()
        self._panel.setObjectName('contentPanel')
        # Modest floor size - just enough that 3 short wrapped lines never
        # clip, without ballooning into empty whitespace for typical hints.
        self._panel.setMinimumWidth(480)
        self._panel.setMaximumWidth(640)
        from smd.theme import enable_styled_surface

        enable_styled_surface(self._panel)
        panel_lay = QVBoxLayout(self._panel)
        panel_lay.setContentsMargins(28, 22, 28, 22)
        panel_lay.setSpacing(10)

        self.title_label = QLabel('Verifying your files…')
        self.title_label.setProperty('class', 'sectionHeader')
        self.title_label.setAlignment(Qt.AlignCenter)
        panel_lay.addWidget(self.title_label)

        self.hint_label = QLabel('Please wait. SMD will show a summary when finished.')
        self.hint_label.setWordWrap(True)
        self.hint_label.setAlignment(Qt.AlignCenter)
        self.hint_label.setProperty('class', 'caption')
        # Enough for ~3 wrapped lines at the caption font size - fixes the
        # earlier bug where a 0-height label clipped its own last line,
        # without the previous overcorrection to a much taller fixed panel.
        self.hint_label.setMinimumHeight(58)
        self.hint_label.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Minimum)
        panel_lay.addWidget(self.hint_label)

        outer.addWidget(self._panel, 0, Qt.AlignCenter)
        outer.addStretch(3)

    def set_hint(self, text: str, *, title: str | None = None) -> None:
        """Update the overlay copy and force a layout pass so nothing clips."""
        if title is not None:
            self.title_label.setText(title)
        self.hint_label.setText(text)
        self.hint_label.adjustSize()
        self._panel.adjustSize()
        self._panel.updateGeometry()

    def show_over(self) -> None:
        parent = self.parentWidget()
        if parent is not None:
            self.setGeometry(parent.rect())
        self.hint_label.adjustSize()
        self._panel.adjustSize()
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


class FittedPixmapLabel(QLabel):
    """QLabel that always scales its source pixmap to fit its current size.

    Used by the duplicate compare dialog so large photos never force a
    horizontal scrollbar - the image shrinks to the panel instead of the
    panel growing to the image."""

    def __init__(self, pixmap: QPixmap, parent=None):
        super().__init__(parent)
        self._source = pixmap
        self.setAlignment(Qt.AlignCenter)
        self.setMinimumSize(1, 1)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self._refit()

    def showEvent(self, event):
        super().showEvent(event)
        self._refit()

    def _refit(self) -> None:
        if self._source is None or self._source.isNull():
            return
        avail = self.size()
        if avail.width() < 2 or avail.height() < 2:
            return
        scaled = self._source.scaled(
            avail, Qt.KeepAspectRatio, Qt.SmoothTransformation
        )
        self.setPixmap(scaled)


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
        # 0 = unlimited - a full run can produce several thousand lines and
        # users need to scroll all the way back to the start, not just the
        # last few hundred lines.
        self.log.setMaximumBlockCount(0)
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


class _MainTabBar(QTabBar):
    """Sizes each tab directly from its own text metrics + a fixed, generous
    padding, instead of relying on the QSS `padding`/`min-width` properties
    on `QTabBar::tab`.

    Those QSS properties alone were not enough: even with
    `setElideMode(Qt.ElideNone)`, "Save memories" (the longest label) was
    still rendered hard-clipped (no "..." - literal missing letters) in a
    real screenshot. `elideMode` only controls whether the *painter* adds an
    ellipsis when told to draw text in a too-small rect; it does not force
    the *layout* to size that rect correctly in the first place, and
    Qt's stylesheet-driven `sizeFromContents()` for `QTabBar::tab` does not
    reliably honor custom padding for compound/OR-ed selectors like the one
    this app uses (`QTabWidget#mainTabs > QTabBar::tab, QTabWidget#resultsTabs
    > QTabBar::tab`). Computing the size hint directly here sidesteps that
    whole class of QSS/style-engine quirk.
    """

    EXTRA_PADDING_PX = 56

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        # Qt's Fusion style paints a separate "tab bar base" line (the
        # PE_FrameTabBarBase primitive) connecting the bar to the pane -
        # this is independent of the QSS border on QTabBar::tab, so
        # `border-top: none` in the stylesheet cannot remove it. This is
        # the one line across the whole tab strip that survived every
        # QSS-only attempt; setDrawBase(False) is the actual Qt API for it.
        self.setDrawBase(False)

    def tabSizeHint(self, index: int) -> QSize:
        base = super().tabSizeHint(index)
        text_width = QFontMetrics(self.font()).horizontalAdvance(self.tabText(index))
        return QSize(max(base.width(), text_width + self.EXTRA_PADDING_PX), base.height())
