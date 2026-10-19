"""On/off switch: a QCheckBox painted as a modern toggle."""

from __future__ import annotations

from PySide6.QtCore import QRectF, QSize, Qt
from PySide6.QtGui import QPainter
from PySide6.QtWidgets import QCheckBox, QWidget

from extract.gui import theme

_TRACK_W, _TRACK_H, _GAP = 34, 20, 10


class ToggleSwitch(QCheckBox):
    def __init__(self, text: str = "", checked: bool = False, parent: QWidget | None = None):
        super().__init__(text, parent)
        self.setChecked(checked)
        self.setCursor(Qt.CursorShape.PointingHandCursor)

    def sizeHint(self) -> QSize:
        text_width = self.fontMetrics().horizontalAdvance(self.text())
        return QSize(
            _TRACK_W + _GAP + text_width + 4, max(_TRACK_H, self.fontMetrics().height()) + 4
        )

    def minimumSizeHint(self) -> QSize:
        return self.sizeHint()

    def set_locked(self, locked: bool) -> None:
        """Keep the normal look but ignore clicks (for options that are always on)."""
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, locked)
        self.setFocusPolicy(Qt.FocusPolicy.NoFocus if locked else Qt.FocusPolicy.StrongFocus)
        self.setCursor(Qt.CursorShape.ArrowCursor if locked else Qt.CursorShape.PointingHandCursor)

    def hitButton(self, pos) -> bool:
        return self.rect().contains(pos)

    def paintEvent(self, event) -> None:
        palette = theme.palette()
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        if not self.isEnabled():
            painter.setOpacity(0.5)
        top = (self.height() - _TRACK_H) / 2
        track = QRectF(0.5, top + 0.5, _TRACK_W - 1, _TRACK_H - 1)
        if self.isChecked():
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(palette.color("accent"))
        else:
            painter.setPen(palette.color("border_strong"))
            painter.setBrush(palette.color("track"))
        painter.drawRoundedRect(track, _TRACK_H / 2, _TRACK_H / 2)
        knob = _TRACK_H - 6
        x = _TRACK_W - knob - 3 if self.isChecked() else 3
        painter.setPen(Qt.PenStyle.NoPen)
        knob_color = "accent_text" if self.isChecked() else "text_muted"
        painter.setBrush(palette.color(knob_color))
        painter.drawEllipse(QRectF(x, top + 3, knob, knob))
        painter.setOpacity(1.0 if self.isEnabled() else 0.7)
        painter.setPen(palette.color("text"))
        text_rect = self.rect().adjusted(_TRACK_W + _GAP, 0, 0, 0)
        painter.drawText(text_rect, int(Qt.AlignmentFlag.AlignVCenter), self.text())
