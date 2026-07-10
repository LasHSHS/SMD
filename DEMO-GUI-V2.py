#!/usr/bin/env python3
"""
Snapchat Memories Downloader (SMD) - Modern Demo V2
Premium Glassmorphic UI with advanced features.

Created by: Las HS (https://las-hs.com)
Inspired by: Ridely Design System
"""
import sys
import os
import json
import time
import base64
import tempfile
import subprocess
from pathlib import Path
from datetime import datetime
from concurrent.futures import ThreadPoolExecutor

from PyQt5.QtWidgets import (QApplication, QMainWindow, QWidget, QVBoxLayout, 
                             QHBoxLayout, QPushButton, QLabel, QFileDialog, 
                             QTextEdit, QTabWidget, QProgressBar, QFrame, 
                             QScrollArea, QGraphicsDropShadowEffect, QGridLayout,
                             QLineEdit, QCheckBox)
from PyQt5.QtCore import Qt, QSize, QTimer, QPropertyAnimation, QEasingCurve, pyqtSignal, QObject, QRunnable, QThreadPool, pyqtSlot
from PyQt5.QtGui import QFont, QIcon, QColor, QPalette, QBrush, QPixmap, QPainter, QLinearGradient, QImage
from PIL import Image
import zipfile
import shutil

# Constants
VERSION = "v2.0-MODERN-DEMO"
APP_DATA = Path(os.getenv('APPDATA', '.')) / 'SMD_V2'
APP_DATA.mkdir(exist_ok=True)

# Styling Tokens (Inspired by PROJECT X / Ridely)
ACCENT_COLOR = "#0078d4"
BG_GRADIENT_START = "#0f172a"
BG_GRADIENT_END = "#1e293b"
GLASS_BG = "rgba(255, 255, 255, 0.05)"
GLASS_BORDER = "rgba(255, 255, 255, 0.1)"
TEXT_PRIMARY = "#f8fafc"
TEXT_SECONDARY = "#94a3b8"

MODERN_STYLE = f"""
    QMainWindow {{
        background-color: {BG_GRADIENT_START};
    }}
    
    #MainContainer {{
        background: qlineargradient(x1:0, y1:0, x2:1, y2:1, stop:0 {BG_GRADIENT_START}, stop:1 {BG_GRADIENT_END});
    }}
    
    #Sidebar {{
        background: {GLASS_BG};
        border-right: 1px solid {GLASS_BORDER};
    }}
    
    #ContentArea {{
        background: transparent;
    }}
    
    #GlassCard {{
        background: {GLASS_BG};
        border: 1px solid {GLASS_BORDER};
        border-radius: 16px;
    }}
    
    QLabel {{
        color: {TEXT_PRIMARY};
        font-family: 'Segoe UI', system-ui, sans-serif;
    }}
    
    #GhostLabel {{
        color: {TEXT_SECONDARY};
    }}
    
    QPushButton#NavBtn {{
        background: transparent;
        color: {TEXT_SECONDARY};
        border: none;
        border-radius: 8px;
        padding: 12px;
        text-align: left;
        font-weight: 600;
        font-size: 14px;
    }}
    
    QPushButton#NavBtn:hover {{
        background: {GLASS_BG};
        color: {TEXT_PRIMARY};
    }}
    
    QPushButton#NavBtn[active="true"] {{
        background: rgba(0, 120, 212, 0.2);
        color: {ACCENT_COLOR};
        border-left: 3px solid {ACCENT_COLOR};
    }}
    
    QPushButton#ActionBtn {{
        background: {ACCENT_COLOR};
        color: white;
        border-radius: 12px;
        padding: 12px 24px;
        font-weight: bold;
        font-size: 14px;
    }}
    
    QPushButton#ActionBtn:hover {{
        background: #0086ed;
    }}
    
    QLineEdit {{
        background: {GLASS_BG};
        border: 1px solid {GLASS_BORDER};
        border-radius: 8px;
        color: {TEXT_PRIMARY};
        padding: 10px;
    }}
    
    QProgressBar {{
        background: {GLASS_BG};
        border: none;
        border-radius: 4px;
        text-align: center;
        color: transparent;
    }}
    
    QProgressBar::chunk {{
        background: qlineargradient(x1:0, y1:0, x2:1, y2:0, stop:0 #3b82f6, stop:1 #2dd4bf);
        border-radius: 4px;
    }}
"""

class ThumbnailWorker(QObject):
    finished = pyqtSignal(str, QPixmap)

    def __init__(self, file_path):
        super().__init__()
        self.file_path = file_path

    def run(self):
        try:
            path = Path(self.file_path)
            ext = path.suffix.lower()
            
            # Create a thumb cache dir
            cache_dir = APP_DATA / 'thumbs'
            cache_dir.mkdir(exist_ok=True)
            thumb_path = cache_dir / f"{path.stem}_{path.stat().st_mtime}.jpg"
            
            if thumb_path.exists():
                pixmap = QPixmap(str(thumb_path))
                self.finished.emit(self.file_path, pixmap)
                return

            if ext in ['.jpg', '.jpeg', '.png']:
                img = Image.open(path)
                img.thumbnail((150, 150))
                img.save(thumb_path, "JPEG")
            elif ext in ['.mp4', '.mov']:
                # Simple ffmpeg hook if available
                subprocess.run(['ffmpeg', '-i', str(path), '-ss', '00:00:01', '-vframes', '1', str(thumb_path)], 
                               capture_output=True, timeout=5)
            
            if thumb_path.exists():
                pixmap = QPixmap(str(thumb_path))
                self.finished.emit(self.file_path, pixmap)
        except Exception as e:
            print(f"Thumb error: {e}")

class GlassCard(QFrame):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("GlassCard")
        self.layout = QVBoxLayout(self)
        
        # Shadow effect
        shadow = QGraphicsDropShadowEffect(self)
        shadow.setBlurRadius(20)
        shadow.setColor(QColor(0, 0, 0, 60))
        shadow.setOffset(0, 4)
        self.setGraphicsEffect(shadow)

class ModernSMD(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("Snapchat Memories Downloader V2")
        self.setMinimumSize(1100, 750)
        
        # Central Widget & Layout
        self.central_widget = QWidget()
        self.central_widget.setObjectName("MainContainer")
        self.setCentralWidget(self.central_widget)
        self.main_layout = QHBoxLayout(self.central_widget)
        self.main_layout.setContentsMargins(0, 0, 0, 0)
        self.main_layout.setSpacing(0)
        
        self.init_ui()
        self.apply_styles()
        
        # Thread Pool for heavy tasks
        self.thread_pool = QThreadPool()
        
        # Drag & Drop
        self.setAcceptDrops(True)
        
        # Auto-refresh gallery on start
        QTimer.singleShot(500, self.refresh_gallery)
        
    def init_ui(self):
        # 1. Sidebar
        self.sidebar = QFrame()
        self.sidebar.setObjectName("Sidebar")
        self.sidebar.setFixedWidth(240)
        self.sidebar_layout = QVBoxLayout(self.sidebar)
        self.sidebar_layout.setContentsMargins(20, 40, 20, 20)
        
        logo = QLabel("SMD PRO")
        logo.setStyleSheet("font-size: 24px; font-weight: 900; color: #0078d4; margin-bottom: 30px;")
        self.sidebar_layout.addWidget(logo)
        
        self.nav_btns = []
        self.create_nav_btn("🚀 Dashboard", "dashboard")
        self.create_nav_btn("📥 Download", "download")
        self.create_nav_btn("🖼️ Gallery", "gallery")
        self.create_nav_btn("🗺️ Map", "map")
        self.create_nav_btn("⚙️ Settings", "settings")
        
        self.sidebar_layout.addStretch()
        
        version_lbl = QLabel(f"Version {VERSION}")
        version_lbl.setObjectName("GhostLabel")
        version_lbl.setStyleSheet("font-size: 10px;")
        self.sidebar_layout.addWidget(version_lbl)
        
        self.main_layout.addWidget(self.sidebar)
        
        # 2. Content Area
        self.content_stack = QTabWidget()
        self.content_stack.setObjectName("ContentArea")
        self.content_stack.tabBar().hide() # Hide default tab bar for custom navigation
        
        self.init_dashboard()
        self.init_download_tab()
        self.init_gallery_tab()
        self.init_map_tab()
        self.init_settings_tab()
        
        self.main_layout.addWidget(self.content_stack)

    def create_nav_btn(self, text, page_name):
        btn = QPushButton(text)
        btn.setObjectName("NavBtn")
        btn.setProperty("active", "false")
        btn.clicked.connect(lambda: self.switch_page(page_name, btn))
        self.sidebar_layout.addWidget(btn)
        self.nav_btns.append(btn)
        
        # Default active
        if page_name == "dashboard":
            btn.setProperty("active", "true")
            self.active_btn = btn

    def switch_page(self, page_name, btn):
        self.active_btn.setProperty("active", "false")
        self.active_btn.style().unpolish(self.active_btn)
        self.active_btn.style().polish(self.active_btn)
        
        btn.setProperty("active", "true")
        btn.style().unpolish(btn)
        btn.style().polish(btn)
        self.active_btn = btn
        
        # Switch tab
        pages = {"dashboard": 0, "download": 1, "gallery": 2, "map": 3, "settings": 4}
        if page_name in pages:
            self.content_stack.setCurrentIndex(pages[page_name])

    def init_dashboard(self):
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(40, 40, 40, 40)
        
        header = QLabel("Welcome back, Explorer")
        header.setStyleSheet("font-size: 32px; font-weight: 800; margin-bottom: 20px;")
        layout.addWidget(header)
        
        # Stats Grid
        stats_layout = QGridLayout()
        
        # Real-ish stats
        memories_count = self.get_local_media_count()
        s1 = self.create_stat_card("Local Memories", f"{memories_count:,}", "Files")
        s2 = self.create_stat_card("Storage Used", f"{memories_count * 0.5:.1f} MB", "Estimated")
        
        # Smart Sync Status
        history_path = APP_DATA / "smd_history.json"
        sync_status = "Not Initialized"
        if history_path.exists():
            sync_status = "Sync Active"
        
        s3 = self.create_stat_card("Smart Sync", sync_status, "Ready")
        
        stats_layout.addWidget(s1, 0, 0)
        stats_layout.addWidget(s2, 0, 1)
        stats_layout.addWidget(s3, 0, 2)
        
        layout.addLayout(stats_layout)
        
        # Quick info
        info_card = GlassCard()
        info_card.layout.addWidget(QLabel("<b>🚀 Get Started</b>"))
        info_card.layout.addWidget(QLabel("Drag your Snapchat ZIP here or click Download to start."))
        layout.addWidget(info_card)
        
        layout.addStretch()
        self.content_stack.addTab(page, "Dashboard")

    def get_local_media_count(self):
        """Helper to count files in the download dir."""
        search_path = Path.home() / "Desktop" / "SMD Media"
        if not search_path.exists():
            search_path = Path.cwd() / "downloads"
        if not search_path.exists():
            return 0
        return len(list(search_path.glob("*.*")))

    def create_stat_card(self, title, val, sub):
        card = GlassCard()
        card.setFixedSize(200, 120)
        t_lbl = QLabel(title)
        t_lbl.setObjectName("GhostLabel")
        v_lbl = QLabel(val)
        v_lbl.setStyleSheet("font-size: 24px; font-weight: bold; color: #3b82f6;")
        s_lbl = QLabel(sub)
        s_lbl.setObjectName("GhostLabel")
        card.layout.addWidget(t_lbl)
        card.layout.addWidget(v_lbl)
        card.layout.addWidget(s_lbl)
        return card

    def init_download_tab(self):
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(40, 40, 40, 40)
        
        header = QLabel("Download Hub")
        header.setStyleSheet("font-size: 32px; font-weight: 800; margin-bottom: 10px;")
        layout.addWidget(header)
        
        desc = QLabel("Add your memories_history.json to start the magic.")
        desc.setObjectName("GhostLabel")
        layout.addWidget(desc)
        
        # Input Card
        input_card = GlassCard()
        c_layout = QVBoxLayout(input_card)
        
        self.file_input = QLineEdit()
        self.file_input.setPlaceholderText("Select memories_history.json...")
        c_layout.addWidget(self.file_input)
        
        select_btn = QPushButton("Browse Files")
        select_btn.setObjectName("ActionBtn")
        c_layout.addWidget(select_btn)
        
        layout.addWidget(input_card)
        
        # Progress
        self.progress_bar = QProgressBar()
        self.progress_bar.setValue(65) # Demo value
        layout.addWidget(self.progress_bar)
        
        # Output Console (Modern)
        self.console = QTextEdit()
        self.console.setReadOnly(True)
        self.console.setStyleSheet(f"background: rgba(0,0,0,0.3); border: 1px solid {GLASS_BORDER}; border-radius: 12px; font-family: 'Consolas';")
        self.console.append("[SYSTEM] Interface V2 Ready.")
        layout.addWidget(self.console)
        
        layout.addStretch()
        self.content_stack.addTab(page, "Download")

    def init_gallery_tab(self):
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(40, 40, 40, 40)
        
        header_row = QHBoxLayout()
        header = QLabel("Memory Gallery")
        header.setStyleSheet("font-size: 32px; font-weight: 800;")
        header_row.addWidget(header)
        
        refresh_btn = QPushButton("🔄 Refresh")
        refresh_btn.setFixedWidth(100)
        refresh_btn.setStyleSheet("background: transparent; border: 1px solid rgba(255,255,255,0.2); border-radius: 8px; font-weight: bold; padding: 5px;")
        refresh_btn.clicked.connect(self.refresh_gallery)
        header_row.addWidget(refresh_btn)
        
        layout.addLayout(header_row)
        
        # Gallery Grid
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setStyleSheet("background: transparent; border: none;")
        
        self.grid_container = QWidget()
        self.grid_container.setStyleSheet("background: transparent;")
        self.gallery_grid = QGridLayout(self.grid_container)
        self.gallery_grid.setSpacing(15)
        self.gallery_grid.setAlignment(Qt.AlignLeft | Qt.AlignTop)
        
        scroll.setWidget(self.grid_container)
        layout.addWidget(scroll)
        
        self.content_stack.addTab(page, "Gallery")

    def init_map_tab(self):
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(40, 40, 40, 40)
        
        header = QLabel("Global Memories")
        header.setStyleSheet("font-size: 32px; font-weight: 800; margin-bottom: 20px;")
        layout.addWidget(header)
        
        # Placeholder for real map
        map_view = QFrame()
        map_view.setMinimumHeight(450)
        map_view.setStyleSheet("background: rgba(0,0,0,0.5); border-radius: 16px; border: 1px dashed rgba(255,255,255,0.2);")
        v = QVBoxLayout(map_view)
        
        # Simulated Map Graphic using a QLabel with a world icon or text
        map_icon = QLabel("🌍")
        map_icon.setStyleSheet("font-size: 80px;")
        v.addWidget(map_icon, alignment=Qt.AlignCenter)
        
        info = QLabel("Map Engine Ready\n\nClustering 4,281 memories across 12 countries.\n(Requires Folium + WebEngine for live view)")
        info.setStyleSheet("font-size: 16px; font-weight: 600; text-align: center;")
        info.setAlignment(Qt.AlignCenter)
        v.addWidget(info)
        
        layout.addWidget(map_view)
        layout.addStretch()
        
        self.content_stack.addTab(page, "Map")

    def init_settings_tab(self):
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(40, 40, 40, 40)
        
        header = QLabel("Settings")
        header.setStyleSheet("font-size: 32px; font-weight: 800; margin-bottom: 20px;")
        layout.addWidget(header)
        
        # Template Section
        template_card = GlassCard()
        template_card.layout.addWidget(QLabel("<b>🏷️ Filename Template</b>"))
        template_card.layout.addWidget(QLabel("Use variables like {date}, {time}, {type}"))
        
        self.template_input = QLineEdit()
        self.template_input.setText("{date}_{filename}")
        template_card.layout.addWidget(self.template_input)
        layout.addWidget(template_card)
        
        # Sync Section
        sync_card = GlassCard()
        sync_card.layout.addWidget(QLabel("<b>🔄 Smart Sync</b>"))
        self.sync_toggle = QCheckBox("Skip already downloaded memories (Sync Mode)")
        self.sync_toggle.setChecked(True)
        self.sync_toggle.setStyleSheet("color: white;")
        sync_card.layout.addWidget(self.sync_toggle)
        layout.addWidget(sync_card)
        
        layout.addStretch()
        self.content_stack.addTab(page, "Settings")

    def refresh_gallery(self):
        """Scan the download folder and populate the grid."""
        # Clear grid
        while self.gallery_grid.count():
            item = self.gallery_grid.takeAt(0)
            widget = item.widget()
            if widget:
                widget.deleteLater()
        
        # For demo, search in Desktop/SMD Media
        search_path = Path.home() / "Desktop" / "SMD Media"
        if not search_path.exists():
            search_path = Path.cwd() / "downloads"
            
        if not search_path.exists():
            self.gallery_grid.addWidget(QLabel("No media found. Download some memories first!"), 0, 0)
            return

        media_extensions = ['.jpg', '.jpeg', '.png', '.mp4', '.mov']
        files = []
        for ext in media_extensions:
            files.extend(list(search_path.glob(f"*{ext}")))
        
        # Sort by latest
        files.sort(key=lambda x: x.stat().st_mtime, reverse=True)
        
        files = files[:40]
        
        self.gallery_widgets = {}
        for idx, f in enumerate(files):
            card, thumb_label = self.create_gallery_item(f)
            self.gallery_grid.addWidget(card, idx // 4, idx % 4)
            self.gallery_widgets[str(f)] = thumb_label
            
            # Start thumb generation in background
            worker = ThumbnailWorker(str(f))
            worker.finished.connect(self.on_thumb_ready)
            # We use a simple layout for the demo, but for heavy lifting we'd use a pool
            QTimer.singleShot(10 * idx, lambda w=worker: self.run_worker(w))

    def run_worker(self, worker):
        # In a real app we'd use QThreadPool, but for the demo signal/slots 
        # on a simple QObject.run() is fine if we wrap it in a thread
        import threading
        threading.Thread(target=worker.run, daemon=True).start()

    def on_thumb_ready(self, file_path, pixmap):
        if file_path in self.gallery_widgets:
            lbl = self.gallery_widgets[file_path]
            lbl.setPixmap(pixmap.scaled(150, 150, Qt.KeepAspectRatioByExpanding, Qt.SmoothTransformation))
            lbl.setText("")

    def create_gallery_item(self, file_path):
        card = QFrame()
        card.setFixedSize(160, 200)
        card.setStyleSheet(f"background: {GLASS_BG}; border: 1px solid {GLASS_BORDER}; border-radius: 12px;")
        
        vbox = QVBoxLayout(card)
        vbox.setContentsMargins(5, 5, 5, 5)
        
        # Thumbnail Label
        thumb = QLabel()
        thumb.setFixedSize(150, 150)
        thumb.setStyleSheet("background: rgba(0,0,0,0.5); border-radius: 8px;")
        thumb.setAlignment(Qt.AlignCenter)
        
        ext = file_path.suffix.lower()
        if ext in ['.jpg', '.jpeg', '.png']:
            thumb.setText("🖼️")
        else:
            thumb.setText("🎬")
            
        vbox.addWidget(thumb)
        
        name = QLabel(file_path.name)
        name.setStyleSheet("font-size: 10px; color: white;")
        name.setWordWrap(True)
        name.setAlignment(Qt.AlignCenter)
        vbox.addWidget(name)
        
        return card, thumb

    def apply_styles(self):
        self.setStyleSheet(MODERN_STYLE)

    # Drag & Drop Events
    def dragEnterEvent(self, event):
        if event.mimeData().hasUrls():
            event.accept()
        else:
            event.ignore()

    def dropEvent(self, event):
        files = [u.toLocalFile() for u in event.mimeData().urls()]
        for f in files:
            path = Path(f)
            if path.suffix.lower() == '.zip':
                self.handle_zip_drop(path)
            elif path.name == 'memories_history.json':
                self.file_input.setText(f)
                self.switch_page("download", self.nav_btns[1])

    def handle_zip_drop(self, zip_path):
        self.console.append(f"📦 Processing ZIP: {zip_path.name}")
        try:
            with zipfile.ZipFile(zip_path, 'r') as zf:
                # Look for memories_history.json
                json_targets = [n for n in zf.namelist() if 'memories_history.json' in n]
                if json_targets:
                    # Extract it to temp
                    target = json_targets[0]
                    extract_path = APP_DATA / 'memories_history.json'
                    with zf.open(target) as source, open(extract_path, 'wb') as target_f:
                        shutil.copyfileobj(source, target_f)
                    
                    self.file_input.setText(str(extract_path))
                    self.console.append(f"✅ Extracted history from ZIP: {target}")
                    self.switch_page("download", self.nav_btns[1])
                else:
                    self.console.append("❌ Could not find memories_history.json in ZIP.")
        except Exception as e:
            self.console.append(f"❌ ZIP Error: {e}")

if __name__ == "__main__":
    app = QApplication(sys.argv)
    window = ModernSMD()
    window.show()
    sys.exit(app.exec_())
