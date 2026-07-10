"""Themed splitter with a visible dotted grip handle."""
from __future__ import annotations

from PyQt5.QtCore import QPointF, QSize, Qt
from PyQt5.QtGui import QColor, QPainter
from PyQt5.QtWidgets import QSplitter, QSplitterHandle

from smd.theme import palette


class ResultsGripHandle(QSplitterHandle):
    """Vertical grip bar with large dots for the metadata/map splitter."""

    GRIP_WIDTH = 16
    DOT_RADIUS = 3.5
    DOT_SPACING_Y = 10
    DOT_COUNT = 5

    def __init__(self, orientation, parent):
        super().__init__(orientation, parent)
        if orientation == Qt.Horizontal:
            self.setCursor(Qt.SplitHCursor)

    def sizeHint(self) -> QSize:
        if self.orientation() == Qt.Horizontal:
            return QSize(self.GRIP_WIDTH, super().sizeHint().height())
        return super().sizeHint()

    def _is_dark(self) -> bool:
        splitter = self.splitter()
        if splitter is not None:
            value = splitter.property("darkTheme")
            if value is not None:
                return bool(value)
        window = self.window()
        if window is not None:
            value = window.property("darkTheme")
            if value is not None:
                return bool(value)
        return False

    def paintEvent(self, event) -> None:  # noqa: N802
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)

        colors = palette(self._is_dark())
        bar_rect = self.rect().adjusted(3, 10, -3, -10)

        bar_color = QColor(colors["secondary_hover"] if self.underMouse() else colors["secondary"])
        painter.setPen(Qt.NoPen)
        painter.setBrush(bar_color)
        painter.drawRoundedRect(bar_rect, 7, 7)

        dot_color = QColor(colors["secondary_text"])
        dot_color.setAlpha(235 if self.underMouse() else 210)
        painter.setBrush(dot_color)

        center_x = bar_rect.center().x()
        span = (self.DOT_COUNT - 1) * self.DOT_SPACING_Y
        start_y = bar_rect.center().y() - span / 2
        for index in range(self.DOT_COUNT):
            y = start_y + index * self.DOT_SPACING_Y
            painter.drawEllipse(QPointF(center_x, y), self.DOT_RADIUS, self.DOT_RADIUS)


class ResultsGripSplitter(QSplitter):
    """Horizontal splitter used between metadata summary and map."""

    def __init__(self, parent=None):
        super().__init__(Qt.Horizontal, parent)
        self.setHandleWidth(ResultsGripHandle.GRIP_WIDTH)
        self.setChildrenCollapsible(False)

    def createHandle(self) -> QSplitterHandle:
        return ResultsGripHandle(self.orientation(), self)

    def set_dark_theme(self, dark: bool) -> None:
        self.setProperty("darkTheme", bool(dark))
        for index in range(1, self.count()):
            handle = self.handle(index)
            if handle is not None:
                handle.update()
