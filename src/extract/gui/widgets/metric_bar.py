"""Horizontal bar drawn with QPainter (no QtCharts, to keep the executable small)."""

from __future__ import annotations

from PySide6.QtCore import QRectF, QSize, Qt
from PySide6.QtGui import QPainter
from PySide6.QtWidgets import QSizePolicy, QWidget

from extract.gui import theme


class MetricBar(QWidget):
    """Fills `fraction` (0..1) of a rounded track in a palette tone."""

    def __init__(self, fraction: float = 0.0, tone: str = "accent", parent: QWidget | None = None):
        super().__init__(parent)
        self._fraction = 0.0
        self._tone = tone
        self.set_fraction(fraction)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)

    @property
    def fraction(self) -> float:
        return self._fraction

    def set_fraction(self, fraction: float, tone: str | None = None) -> None:
        self._fraction = min(max(fraction, 0.0), 1.0)
        self._tone = tone or self._tone
        self.update()

    def sizeHint(self) -> QSize:
        return QSize(160, 10)

    def paintEvent(self, event) -> None:
        palette = theme.palette()
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.setPen(Qt.PenStyle.NoPen)
        height = 8.0
        track = QRectF(0, (self.height() - height) / 2, self.width(), height)
        painter.setBrush(palette.color("track"))
        painter.drawRoundedRect(track, height / 2, height / 2)
        if self._fraction > 0:
            fill = QRectF(track)
            fill.setWidth(max(track.width() * self._fraction, height))
            painter.setBrush(palette.color(self._tone))
            painter.drawRoundedRect(fill, height / 2, height / 2)
