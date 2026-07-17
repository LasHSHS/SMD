"""Guide tab for DownloaderGUI."""
from __future__ import annotations

import base64

from PyQt5.QtWidgets import QVBoxLayout, QSizePolicy, QMessageBox

from gui.common import ROOT, TAB_SAVE_MEMORIES, build_guide_panel


class GuideTabMixin:
    """Mixin: Guide tab (how to request a Snapchat export)."""

    def _add_guide_tab(self) -> None:
        # --- Tab 1: Guide (request export from Snapchat) ---
        guide_tab = self._make_tab_page()
        guide_inner = build_guide_panel(
            lambda: self.tabs.setCurrentIndex(self._tab_process)
        )
        guide_inner.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Preferred)
        guide_tab_layout = QVBoxLayout(guide_tab)
        guide_tab_layout.setContentsMargins(0, 0, 0, 0)
        guide_tab_layout.addWidget(self._doc_tab(guide_inner))
        self.tabs.addTab(guide_tab, "Guide")

    def show_export_example(self):
        """Show the export settings example image in fullscreen popup"""
        if hasattr(self, "export_example_image") and self.export_example_image:
            # Save image temporarily
            temp_path = ROOT / ".temp_export_example.png"
            try:
                img_data = self.export_example_image.split(",")[1]
                with open(temp_path, "wb") as f:
                    f.write(base64.b64decode(img_data))
                # Show in fullscreen popup
                self.fullscreen_popup.show_media(str(temp_path))
            except Exception as e:
                QMessageBox.warning(
                    self, "Preview Error", f"Could not display example image:\n{str(e)}"
                )
