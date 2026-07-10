"""SMD design system: typography, spacing, surfaces, and Qt stylesheets."""
from __future__ import annotations

import sys
from pathlib import Path

THEME_SYSTEM = "system"
THEME_LIGHT = "light"
THEME_DARK = "dark"

# Layout tokens (px) — tuned for 1080p–1440p Windows displays
WINDOW_MIN_WIDTH = 960
WINDOW_MIN_HEIGHT = 680
SIDEBAR_WIDTH = 220
CONTENT_MAX_FORM = 1370
CONTENT_MIN_FORM = 720
CONTENT_MAX_DOCS = 1370
CONTENT_MAX_NARROW = 1370
PAGE_MARGIN_H = 28
PAGE_MARGIN_V = 20
CONTENT_AREA_MARGIN_H = PAGE_MARGIN_H
CONTENT_AREA_MARGIN_V = PAGE_MARGIN_V
SECTION_GAP = 24
CONTROL_GAP = 10
FIELD_GAP = 8
SECTION_PADDING = 16

FONT_STACK = "'Segoe UI Variable Text', 'Segoe UI', system-ui, sans-serif"
FONT_STACK_DISPLAY = "'Segoe UI Variable Display', 'Segoe UI', system-ui, sans-serif"
FONT_MONO = "'Cascadia Mono', 'Cascadia Code', Consolas, monospace"

# Typography (px) — Discord default chat/UI size at 100% zoom
FONT_SIZE_BASE = 16
FONT_SIZE_SMALL = 14
FONT_SIZE_CAPTION = 13
FONT_SIZE_MONO = 13
FONT_SIZE_TAB = 16
FONT_SIZE_TITLE = 20
FONT_SIZE_SECTION = 16
FONT_SIZE_TOOLBAR = 14
TAB_MIN_WIDTH = 148
TAB_PADDING_V = 12
TAB_PADDING_H = 32

# Brand palette — light: yellow primary, dark orange secondary
LIGHT_PRIMARY = "#F5C400"
LIGHT_PRIMARY_HOVER = "#D9AE00"
LIGHT_PRIMARY_TEXT = "#1A1A1A"
LIGHT_SECONDARY = "#D35400"
LIGHT_SECONDARY_HOVER = "#B84700"
LIGHT_SECONDARY_TEXT = "#FFFFFF"
LIGHT_BG = "#F4F2EC"
LIGHT_SURFACE = "#FFFDF8"
LIGHT_CARD = "#FFFFFF"
LIGHT_BORDER = "#3A3A3C"
LIGHT_TEXT = "#1A1A1A"
LIGHT_MUTED = "#52525B"
LIGHT_CAPTION = "#6B6B70"

# Brand palette — dark: yellow buttons, dark orange primary CTA only
DARK_PRIMARY = "#CC5500"
DARK_PRIMARY_HOVER = "#E06010"
DARK_PRIMARY_TEXT = "#FFFFFF"
DARK_SECONDARY = "#C59E21"
DARK_SECONDARY_HOVER = "#D4AE2A"
DARK_SECONDARY_TEXT = "#0A0A0A"
DARK_BG = "#141414"
DARK_SURFACE = "#1C1C1E"
DARK_CARD = "#0A0A0A"
DARK_BORDER = "#6E6E73"
DARK_TEXT = "#F2F2F7"
DARK_MUTED = "#A1A1A6"
DARK_CAPTION = "#8E8E93"

SUCCESS = "#2D8A3E"
SUCCESS_DARK = "#4CD964"
WARNING = "#C45C0A"
WARNING_DARK = "#D4A82A"
ERROR = "#C42B2B"
ERROR_DARK = "#FF6B6B"

# Legacy aliases (prefer palette helpers below)
ACCENT = LIGHT_SECONDARY
ACCENT_HOVER = LIGHT_SECONDARY_HOVER
ACCENT_DARK = DARK_SECONDARY
ACCENT_DARK_HOVER = DARK_SECONDARY_HOVER


def palette(dark: bool) -> dict[str, str]:
    """Return semantic color tokens for the active theme."""
    if dark:
        return {
            "primary": DARK_PRIMARY,
            "primary_hover": DARK_PRIMARY_HOVER,
            "primary_text": DARK_PRIMARY_TEXT,
            "secondary": DARK_SECONDARY,
            "secondary_hover": DARK_SECONDARY_HOVER,
            "secondary_text": DARK_SECONDARY_TEXT,
            "bg": DARK_BG,
            "surface": DARK_SURFACE,
            "card": DARK_CARD,
            "border": DARK_BORDER,
            "text": DARK_TEXT,
            "muted": DARK_MUTED,
            "caption": DARK_CAPTION,
            "ok": SUCCESS_DARK,
            "warn": WARNING_DARK,
            "err": ERROR_DARK,
            "info": DARK_SECONDARY,
            # Layered surfaces — panel (tab well) → raised (sections) → inset (fields)
            "panel": "#18181A",
            "raised": "#242426",
            "inset": "#1C1C1E",
            "console_bg": "#0A0A0A",
            "console_fg": "#D1D1D6",
            "prog_bg": "#1C1C1E",
            "tab_bg": "#242426",
            "tab_fg": DARK_MUTED,
            "tab_sel_bg": "#242426",
            "tab_sel_fg": DARK_TEXT,
            "header_border": DARK_BORDER,
            "banner_bg": "rgba(197, 158, 33, 0.18)",
            "btn_bg": "#C59E21",
            "btn_fg": "#0A0A0A",
            "btn_border": "#A88718",
            "btn_hover": "#D4AE2A",
            "input_bg": "#1C1C1E",
            "input_border": DARK_BORDER,
            "chk_bg": "#1C1C1E",
            "menu_bg": DARK_SURFACE,
            "disabled_fg": "#636366",
            "scroll_track": "#242426",
            "scroll_handle": "#6E6E73",
            "scroll_handle_hover": "#8E8E93",
        }
    return {
        "primary": LIGHT_PRIMARY,
        "primary_hover": LIGHT_PRIMARY_HOVER,
        "primary_text": LIGHT_PRIMARY_TEXT,
        "secondary": LIGHT_SECONDARY,
        "secondary_hover": LIGHT_SECONDARY_HOVER,
        "secondary_text": LIGHT_SECONDARY_TEXT,
        "bg": LIGHT_BG,
        "surface": LIGHT_SURFACE,
        "card": LIGHT_CARD,
        "border": LIGHT_BORDER,
        "text": LIGHT_TEXT,
        "muted": LIGHT_MUTED,
        "caption": LIGHT_CAPTION,
        "ok": SUCCESS,
        "warn": WARNING,
        "err": ERROR,
        "info": LIGHT_SECONDARY,
        "panel": "#EFEDE6",
        "raised": "#E0DED8",
        "inset": "#D4D2CC",
        "console_bg": "#1A1A1C",
        "console_fg": "#ECECEF",
        "prog_bg": "#D4D2CC",
        "tab_bg": "#ECEAE4",
        "tab_fg": LIGHT_MUTED,
        "tab_sel_bg": "#E0DED8",
        "tab_sel_fg": LIGHT_TEXT,
        "header_border": LIGHT_BORDER,
        "banner_bg": "rgba(211, 84, 0, 0.18)",
        "btn_bg": "#D35400",
        "btn_fg": "#FFFFFF",
        "btn_border": "#A84000",
        "btn_hover": "#B84700",
        "input_bg": "#D4D2CC",
        "input_border": LIGHT_BORDER,
        "chk_bg": "#D4D2CC",
        "menu_bg": LIGHT_CARD,
        "disabled_fg": "#AEAEB2",
        "scroll_track": "#E0DED8",
        "scroll_handle": "#A8A8AD",
        "scroll_handle_hover": "#8E8E93",
    }


def system_prefers_dark() -> bool:
    if sys.platform == "win32":
        try:
            import winreg

            key = winreg.OpenKey(
                winreg.HKEY_CURRENT_USER,
                r"Software\Microsoft\Windows\CurrentVersion\Themes\Personalize",
            )
            value, _ = winreg.QueryValueEx(key, "AppsUseLightTheme")
            winreg.CloseKey(key)
            return int(value) == 0
        except OSError:
            pass
    return False


def resolve_theme(mode: str) -> str:
    if mode == THEME_SYSTEM:
        return THEME_DARK if system_prefers_dark() else THEME_LIGHT
    return mode if mode in (THEME_LIGHT, THEME_DARK) else THEME_LIGHT


def stylesheet_for(theme: str) -> str:
    if theme == THEME_DARK:
        return DARK_QSS
    return LIGHT_QSS


def apply_status_property(widget, status: str) -> None:
    """Set status property for themed QLabel coloring (info|ok|warn|err|neutral)."""
    widget.setProperty("status", status or "neutral")
    widget.style().unpolish(widget)
    widget.style().polish(widget)


def apply_doc_browser_theme(browser, *, dark: bool) -> None:
    """Match QTextBrowser HTML document colors to the active Qt theme."""
    p = palette(dark)
    browser.document().setDefaultStyleSheet(
        f"body {{ color: {p['text']}; background-color: transparent; }}"
        f"a {{ color: {p['secondary']}; }}"
    )


def enable_styled_surface(widget) -> None:
    """Let Qt stylesheets paint solid backgrounds on frames/group boxes."""
    from PyQt5.QtCore import Qt

    widget.setAttribute(Qt.WA_StyledBackground, True)


def paint_widget_surface(widget, *, dark: bool, role: str = 'bg') -> None:
    """Force a solid themed background (QSS alone is unreliable on Windows tab/scroll surfaces)."""
    from PyQt5.QtGui import QColor, QPalette

    colors = palette(dark)
    color = QColor(colors[role])
    widget.setAutoFillBackground(True)
    pal = widget.palette()
    pal.setColor(QPalette.Window, color)
    widget.setPalette(pal)


def apply_scroll_area_theme(scroll, *, dark: bool) -> None:
    """Theme a scroll area and its viewport."""
    enable_styled_surface(scroll)
    paint_widget_surface(scroll, dark=dark, role='bg')
    paint_widget_surface(scroll.viewport(), dark=dark, role='bg')


def _scrollbars(p: dict[str, str]) -> str:
    return f"""
QScrollBar:vertical {{
    background: {p['scroll_track']};
    width: 8px;
    margin: 4px 2px;
    border: none;
    border-radius: 4px;
}}
QScrollBar::handle:vertical {{
    background: {p['scroll_handle']};
    min-height: 32px;
    border-radius: 4px;
}}
QScrollBar::handle:vertical:hover {{ background: {p['scroll_handle_hover']}; }}
QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical,
QScrollBar::add-page:vertical, QScrollBar::sub-page:vertical {{
    height: 0; background: none;
}}
QScrollBar:horizontal {{
    background: {p['scroll_track']};
    height: 8px;
    margin: 2px 4px;
    border: none;
    border-radius: 4px;
}}
QScrollBar::handle:horizontal {{
    background: {p['scroll_handle']};
    min-width: 32px;
    border-radius: 4px;
}}
QScrollBar::handle:horizontal:hover {{ background: {p['scroll_handle_hover']}; }}
QScrollBar::add-line:horizontal, QScrollBar::sub-line:horizontal,
QScrollBar::add-page:horizontal, QScrollBar::sub-page:horizontal {{
    width: 0; background: none;
}}
QScrollArea {{
    border: none;
    background-color: {p['bg']};
}}
QAbstractScrollArea::viewport {{
    background-color: {p['bg']};
}}
"""


def _sidebar_shell(p: dict[str, str]) -> str:
    return f"""
QFrame#Sidebar {{
    background: {p['surface']};
    border-right: 1px solid {p['border']};
}}
QWidget#ContentShell {{
    background: {p['bg']};
}}
QLabel#sidebarBrand {{
    font-family: {FONT_STACK_DISPLAY};
    font-size: {FONT_SIZE_BASE}px;
    font-weight: 700;
    color: {p['text']};
}}
QLabel#sidebarVersion {{
    font-size: {FONT_SIZE_CAPTION}px;
    color: {p['caption']};
}}
QPushButton#NavBtn {{
    background: transparent;
    color: {p['muted']};
    border: none;
    border-radius: 8px;
    padding: 10px 12px;
    text-align: left;
    font-weight: 600;
    font-size: {FONT_SIZE_BASE}px;
}}
QPushButton#NavBtn:hover {{
    background: {p['btn_hover']};
    color: {p['text']};
}}
QPushButton#NavBtn[active="true"] {{
    background: {p['banner_bg']};
    color: {p['text']};
    border-left: 3px solid {p['secondary']};
    padding-left: 9px;
}}
"""


def _results_splitter(p: dict[str, str]) -> str:
    return f"""
QSplitter#resultsPanels {{
    background: transparent;
}}
"""


def _tabs_main(p: dict[str, str]) -> str:
    return f"""
QTabWidget#mainTabs > QTabBar::tab, QTabWidget#resultsTabs > QTabBar::tab {{
    background: {p['tab_bg']};
    color: {p['tab_fg']};
    border: 1px solid {p['border']};
    border-bottom: none;
    padding: {TAB_PADDING_V}px {TAB_PADDING_H}px;
    min-width: {TAB_MIN_WIDTH}px;
    border-top-left-radius: 8px;
    border-top-right-radius: 8px;
    margin-right: 3px;
    font-size: {FONT_SIZE_TAB}px;
    font-weight: 600;
}}
QTabWidget#mainTabs > QTabBar::tab:selected, QTabWidget#resultsTabs > QTabBar::tab:selected {{
    background: {p['tab_sel_bg']};
    color: {p['tab_sel_fg']};
    border-bottom: 2px solid {p['secondary']};
}}
QTabWidget#mainTabs::pane, QTabWidget#resultsTabs::pane {{
    border: 1px solid {p['border']};
    border-radius: 8px;
    background-color: {p['panel']};
    top: -1px;
    padding: 8px;
}}
"""


def _semantic_labels(p: dict[str, str]) -> str:
    pad = SECTION_PADDING
    return f"""
QLabel.pageTitle {{
    font-family: {FONT_STACK_DISPLAY};
    font-size: {FONT_SIZE_TITLE}px;
    font-weight: 600;
    padding: 0;
    color: {p['text']};
}}
QLabel.sectionHeader {{
    font-family: {FONT_STACK_DISPLAY};
    font-size: {FONT_SIZE_SECTION}px;
    font-weight: 600;
    padding: 0;
    margin-top: 4px;
    color: {p['text']};
}}
QLabel.muted {{
    font-size: {FONT_SIZE_SMALL}px;
    color: {p['muted']};
}}
QLabel.caption {{
    font-size: {FONT_SIZE_CAPTION}px;
    color: {p['caption']};
}}
QLabel[status="info"] {{ color: {p['info']}; font-size: {FONT_SIZE_SMALL}px; font-weight: 600; }}
QLabel[status="ok"] {{ color: {p['ok']}; font-size: {FONT_SIZE_SMALL}px; font-weight: 600; }}
QLabel[status="warn"] {{ color: {p['warn']}; font-size: {FONT_SIZE_SMALL}px; font-weight: 600; }}
QLabel[status="err"] {{ color: {p['err']}; font-size: {FONT_SIZE_SMALL}px; font-weight: 600; }}
QLabel[status="neutral"] {{ color: {p['muted']}; font-size: {FONT_SIZE_SMALL}px; }}
QLabel {{
    background: transparent;
}}
QWidget#appHeader {{
    background-color: {p['raised']};
    border-bottom: 1px solid {p['header_border']};
}}
QWidget#tabsShell {{
    background-color: {p['bg']};
}}
QWidget#mainShell {{
    background-color: {p['bg']};
}}
QWidget#tabPage {{
    background-color: {p['panel']};
}}
QWidget#contentColumn {{
    background-color: {p['bg']};
}}
QScrollArea#tabScroll {{
    background-color: {p['bg']};
    border: none;
}}
QScrollArea#tabScroll QAbstractScrollArea::viewport {{
    background-color: {p['bg']};
}}
QFrame#contentSection {{
    background-color: {p['raised']};
    border: 1px solid {p['border']};
    border-radius: 10px;
}}
QFrame#contentSection QLabel {{
    background: transparent;
}}
QLabel#sectionBoxTitle {{
    font-family: {FONT_STACK_DISPLAY};
    font-size: {FONT_SIZE_SECTION}px;
    font-weight: 600;
    color: {p['text']};
    background: transparent;
    padding: 0;
    margin: 0 0 2px 0;
}}
QFrame#heroSection {{
    background-color: {p['raised']};
    border: 1px solid {p['secondary']};
    border-radius: 10px;
}}
QFrame#heroSection QLabel {{
    background: transparent;
}}
QLabel#heroBoxTitle {{
    font-family: {FONT_STACK_DISPLAY};
    font-size: {FONT_SIZE_SECTION}px;
    font-weight: 600;
    color: {p['text']};
    background: transparent;
    padding: 0;
    margin: 0 0 2px 0;
}}
QGroupBox#contentSection {{
    font-size: {FONT_SIZE_SECTION}px;
    font-weight: 600;
    color: {p['text']};
    border: 1px solid {p['border']};
    border-radius: 10px;
    margin-top: 14px;
    padding: {pad}px {pad}px {pad - 2}px {pad}px;
    background-color: {p['raised']};
}}
QGroupBox#contentSection::title {{
    subcontrol-origin: margin;
    subcontrol-position: top left;
    padding: 4px 12px;
    left: 12px;
    color: {p['text']};
    background-color: {p['raised']};
    border-radius: 6px;
}}
QGroupBox#contentSection QLabel {{
    background: transparent;
}}
QGroupBox#heroSection {{
    font-size: {FONT_SIZE_SECTION}px;
    font-weight: 600;
    color: {p['text']};
    border: 1px solid {p['secondary']};
    border-radius: 10px;
    margin-top: 14px;
    padding: {pad + 2}px {pad + 2}px {pad}px {pad + 2}px;
    background-color: {p['raised']};
}}
QGroupBox#heroSection::title {{
    subcontrol-origin: margin;
    subcontrol-position: top left;
    padding: 4px 12px;
    left: 12px;
    color: {p['text']};
    background-color: {p['raised']};
    border-radius: 6px;
}}
QGroupBox#heroSection QLabel {{
    background: transparent;
}}
QFrame#contentPanel {{
    background-color: {p['raised']};
    border: 1px solid {p['border']};
    border-radius: 10px;
}}
QFrame#contentPanel QLabel {{
    background: transparent;
}}
QLabel#infoBanner {{
    font-size: {FONT_SIZE_SMALL}px;
    color: {p['text']};
    padding: 12px 14px;
    background: {p['banner_bg']};
    border: 1px solid {p['border']};
    border-radius: 8px;
}}
QLabel#detailed_status {{
    color: {p['console_fg']};
    background-color: {p['console_bg']};
    border: 1px solid {p['border']};
    border-radius: 8px;
    font-family: {FONT_MONO};
    font-size: {FONT_SIZE_MONO}px;
    padding: 10px 12px;
}}
"""


def _checkbox_check_image(dark: bool) -> str:
    """Transparent checkmark PNG for Qt stylesheets (dev + frozen builds)."""
    from smd.runtime import app_root, internal_root

    name = 'checkbox-check-dark.png' if dark else 'checkbox-check-light.png'
    for base in (app_root(), internal_root(), Path(__file__).resolve().parent.parent):
        candidate = base / 'assets' / 'ui' / name
        if candidate.is_file():
            # Qt on Windows is picky about URL format in QSS.
            return str(candidate.resolve()).replace('\\', '/')
    return ''


def _controls(p: dict[str, str], *, dark: bool = False) -> str:
    check_img = _checkbox_check_image(dark)
    checked_image_rule = f'image: url({check_img});' if check_img else ''
    return f"""
QCheckBox {{
    spacing: 10px;
    color: {p['text']};
    font-size: {FONT_SIZE_BASE}px;
    padding: 5px 2px;
    min-height: 28px;
}}
QCheckBox::indicator {{
    width: 22px;
    height: 22px;
    border-radius: 6px;
    border: 2px solid {p['input_border']};
    background: {p['chk_bg']};
}}
QCheckBox::indicator:hover {{
    border-color: {p['secondary']};
    background: {p['surface']};
}}
QCheckBox::indicator:checked {{
    border: 2px solid {p['secondary']};
    background: {p['chk_bg']};
    {checked_image_rule}
}}
QCheckBox::indicator:checked:hover {{
    border-color: {p['secondary_hover']};
    background: {p['surface']};
}}
QCheckBox:disabled {{
    color: {p['disabled_fg']};
}}
QCheckBox::indicator:disabled {{
    border-color: {p['btn_border']};
    background: {p['btn_bg']};
}}
QCheckBox::indicator:checked:disabled {{
    border-color: {p['btn_border']};
    background: {p['btn_bg']};
}}
QRadioButton {{
    spacing: 10px;
    color: {p['text']};
    font-size: {FONT_SIZE_BASE}px;
    padding: 5px 2px;
    min-height: 28px;
}}
QRadioButton::indicator {{
    width: 22px;
    height: 22px;
    border-radius: 11px;
    border: 2px solid {p['input_border']};
    background: {p['chk_bg']};
}}
QRadioButton::indicator:hover {{
    border-color: {p['secondary']};
    background: {p['surface']};
}}
QRadioButton::indicator:checked {{
    border: 6px solid {p['secondary']};
    background: {p['chk_bg']};
}}
QRadioButton:disabled {{
    color: {p['disabled_fg']};
}}
QGroupBox {{
    font-size: {FONT_SIZE_SECTION}px;
    font-weight: 600;
    color: {p['text']};
    border: 1px solid {p['border']};
    border-radius: 10px;
    margin-top: 14px;
    padding: {SECTION_PADDING}px;
    background-color: {p['raised']};
}}
QGroupBox::title {{
    subcontrol-origin: margin;
    subcontrol-position: top left;
    padding: 4px 12px;
    left: 12px;
    color: {p['text']};
    background-color: {p['raised']};
}}
QDialog {{
    background-color: {p['bg']};
    color: {p['text']};
}}
QDialog QLabel {{
    color: {p['text']};
    background: transparent;
}}
QDialog#appDialog {{
    background-color: {p['bg']};
}}
QWidget#dialogBody {{
    background-color: {p['bg']};
}}
QComboBox {{
    padding: 7px 12px; min-height: 22px; font-size: {FONT_SIZE_BASE}px;
    background: {p['input_bg']}; color: {p['text']};
    border: 1px solid {p['input_border']}; border-radius: 8px;
}}
QComboBox::drop-down {{ border: none; width: 24px; }}
QComboBox QAbstractItemView {{
    background: {p['menu_bg']}; color: {p['text']};
    border: 1px solid {p['input_border']};
    selection-background-color: {p['secondary']};
    selection-color: {p['secondary_text']};
}}
QMenuBar {{ background: transparent; color: {p['text']}; border: none; font-size: {FONT_SIZE_BASE}px; }}
QMenuBar::item:selected {{ background: {p['btn_hover']}; border-radius: 4px; }}
QMenu {{
    background: {p['menu_bg']}; color: {p['text']};
    border: 1px solid {p['input_border']}; padding: 6px;
}}
QMenu::item:selected {{
    background: {p['secondary']}; color: {p['secondary_text']};
}}
QTextBrowser, QTextEdit {{
    selection-background-color: {p['secondary']};
    selection-color: {p['secondary_text']};
}}
QTextBrowser a {{ color: {p['secondary']}; text-decoration: none; }}
QPushButton {{
    background: {p['btn_bg']}; color: {p['btn_fg']};
    border: 1px solid {p['btn_border']}; border-radius: 8px;
    padding: 8px 16px; font-size: {FONT_SIZE_BASE}px; font-weight: 600;
    min-height: 22px;
}}
QPushButton:hover {{
    background: {p['btn_hover']};
    color: {p['btn_fg']};
    border-color: {p['secondary_hover']};
}}
QPushButton:pressed {{ background: {p['btn_hover']}; color: {p['btn_fg']}; }}
QPushButton#accentBtn {{
    background: {p['secondary']}; color: {p['secondary_text']}; border: none;
    padding: 8px 18px; border-radius: 8px; font-weight: 700;
}}
QPushButton#accentBtn:hover {{ background: {p['secondary_hover']}; color: {p['secondary_text']}; }}
QPushButton#primaryAction {{
    background: {p['secondary']}; color: {p['secondary_text']}; border: 1px solid {p['btn_border']};
    padding: 10px 22px; border-radius: 8px; font-size: {FONT_SIZE_BASE}px; font-weight: 700;
    max-width: 360px;
}}
QPushButton#primaryAction:hover {{
    background: {p['secondary_hover']}; color: {p['secondary_text']}; border-color: {p['secondary_hover']};
}}
QPushButton#runAction {{
    background: {p['primary']}; color: {p['primary_text']}; border: 1px solid {p['primary']};
    padding: 10px 22px; border-radius: 8px; font-size: {FONT_SIZE_BASE}px; font-weight: 700;
    max-width: 360px;
}}
QPushButton#runAction:hover {{
    background: {p['primary_hover']}; color: {p['primary_text']}; border-color: {p['primary_hover']};
}}
QPushButton#toolbarBtn {{
    padding: 6px 14px; font-size: {FONT_SIZE_TOOLBAR}px; font-weight: 600;
    background: {p['btn_bg']}; color: {p['btn_fg']};
    border: 1px solid {p['btn_border']};
}}
QPushButton#toolbarBtn:hover {{
    background: {p['btn_hover']}; color: {p['btn_fg']};
}}
QPushButton#dupThumbBtn {{
    background: {p['inset']};
    border: 1px solid {p['border']};
    border-radius: 8px;
    padding: 4px;
    outline: none;
}}
QPushButton#dupThumbBtn:hover {{
    border-color: {p['border']};
    background: {p['surface']};
}}
QPushButton#dupThumbBtn:focus {{
    border: 1px solid {p['border']};
    outline: none;
}}
QPushButton#themeToggleBtn {{
    padding: 6px 16px;
    font-size: {FONT_SIZE_TOOLBAR}px;
    font-weight: 600;
    border-radius: 8px;
    background: {p['secondary']};
    color: {p['secondary_text']};
    border: none;
}}
QPushButton#themeToggleBtn:hover {{
    background: {p['secondary_hover']};
    color: {p['secondary_text']};
}}
QPushButton#supportBtn {{
    padding: 6px 16px;
    font-size: {FONT_SIZE_TOOLBAR}px;
    font-weight: 600;
    border-radius: 8px;
    background: transparent;
    color: {p['text']};
    border: none;
}}
QPushButton#supportBtn:hover {{
    background: rgba(128, 128, 128, 0.18);
    color: {p['text']};
}}
QPushButton#supportBtn:pressed {{
    background: rgba(128, 128, 128, 0.28);
    color: {p['text']};
}}
QPushButton:disabled {{
    color: {p['disabled_fg']};
    background: {p['raised']};
    border-color: {p['border']};
}}
"""


def _surfaces(p: dict[str, str]) -> str:
    return f"""
QMainWindow {{
    background-color: {p['bg']};
    color: {p['text']};
    font-family: {FONT_STACK};
    font-size: {FONT_SIZE_BASE}px;
}}
QWidget {{
    color: {p['text']};
    font-family: {FONT_STACK};
    font-size: {FONT_SIZE_BASE}px;
}}
QLineEdit, QSpinBox, QComboBox {{
    background-color: {p['inset']};
    color: {p['text']};
    border: 1px solid {p['border']};
    border-radius: 8px;
    padding: 8px 10px;
}}
QTextEdit, QTextBrowser {{
    background-color: {p['inset']};
    color: {p['text']};
    border: 1px solid {p['border']};
    border-radius: 8px;
    padding: 8px 10px;
}}
QTextBrowser#docReader {{
    background-color: {p['raised']};
    border: 1px solid {p['border']};
    border-radius: 10px;
    padding: 12px 14px;
}}
QPlainTextEdit#consoleLog, QTextEdit#consoleLog {{
    font-family: {FONT_MONO};
    font-size: {FONT_SIZE_MONO}px;
    background-color: {p['console_bg']};
    color: {p['console_fg']};
    border: 1px solid {p['border']};
    border-radius: 8px;
    padding: 8px;
    selection-background-color: {p['secondary']};
    selection-color: {p['secondary_text']};
}}
QProgressBar {{
    border: 1px solid {p['border']};
    border-radius: 8px;
    background-color: {p['inset']};
    text-align: center;
    min-height: 28px;
    max-height: 28px;
    padding: 2px 4px;
    font-size: {FONT_SIZE_CAPTION}px;
    font-weight: 600;
    color: {p['text']};
}}
QProgressBar::chunk {{
    background: {p['secondary']};
    border-radius: 6px;
}}
QWidget#liveRunDashboard {{
    background-color: {p['panel']};
    border: 1px solid {p['border']};
    border-radius: 12px;
}}
QWidget#liveRunDashboard QLabel {{
    background: transparent;
}}
QFrame#runStatCard {{
    background-color: {p['raised']};
    border: 1px solid {p['border']};
    border-radius: 10px;
    min-height: 76px;
}}
QFrame#runStatCard QLabel {{
    background: transparent;
}}
QLabel#runStatTitle {{
    color: {p['caption']};
    font-size: {FONT_SIZE_CAPTION}px;
    font-weight: 600;
    background: transparent;
}}
QLabel#runStatValue {{
    color: {p['text']};
    font-size: 17px;
    font-weight: 700;
    background: transparent;
}}
QLabel#runStatValueLarge {{
    color: {p['secondary']};
    font-size: 28px;
    font-weight: 700;
    background: transparent;
    min-height: 34px;
    padding-bottom: 2px;
}}
QPlainTextEdit#runActivityLog {{
    font-family: {FONT_MONO};
    font-size: {FONT_SIZE_MONO}px;
    background-color: {p['console_bg']};
    color: {p['console_fg']};
    border: 1px solid {p['border']};
    border-radius: 8px;
    padding: 8px;
    selection-background-color: {p['secondary']};
    selection-color: {p['secondary_text']};
}}
QTextEdit#debugOutput {{
    font-family: {FONT_MONO};
    font-size: {FONT_SIZE_MONO}px;
    background-color: {p['console_bg']};
    color: {p['console_fg']};
    border-radius: 8px;
}}
"""


def _build_qss(dark: bool) -> str:
    p = palette(dark)
    return (
        _surfaces(p)
        + _semantic_labels(p)
        + _controls(p, dark=dark)
        + _sidebar_shell(p)
        + _tabs_main(p)
        + _results_splitter(p)
        + _scrollbars(p)
    )


LIGHT_QSS = _build_qss(False)
DARK_QSS = _build_qss(True)
