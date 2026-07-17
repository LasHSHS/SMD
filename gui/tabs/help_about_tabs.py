"""Help and About tab builders for DownloaderGUI."""
from __future__ import annotations

from PyQt5.QtWidgets import QVBoxLayout

from gui.common import build_about_panel, build_help_panel


class HelpAboutTabMixin:
    """Mixin: Help + About tabs (thin wrappers around content builders)."""

    def _add_help_and_about_tabs(self) -> None:
        # --- Tab 4: Help and troubleshooting ---
        help_tab = self._make_tab_page()
        help_tab_layout = QVBoxLayout(help_tab)
        help_tab_layout.setContentsMargins(0, 0, 0, 0)
        help_tab_layout.addWidget(self._doc_tab(build_help_panel()))
        self.tabs.addTab(help_tab, "Help")

        # --- Tab 5: About ---
        about_tab = self._make_tab_page()
        about_tab_layout = QVBoxLayout(about_tab)
        about_tab_layout.setContentsMargins(0, 0, 0, 0)
        about_tab_layout.addWidget(self._doc_tab(build_about_panel()))
        self.tabs.addTab(about_tab, "About")
