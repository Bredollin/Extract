"""Small factories shared by every page, so styling stays declarative (QSS properties)."""

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QBoxLayout,
    QFrame,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QScrollArea,
    QVBoxLayout,
    QWidget,
)

from extract.gui.icons import icon


def repolish(widget: QWidget) -> None:
    """Re-apply the stylesheet after a dynamic property change."""
    widget.style().unpolish(widget)
    widget.style().polish(widget)
    widget.update()


def set_tone(widget: QWidget, tone: str) -> None:
    if widget.property("tone") != tone:
        widget.setProperty("tone", tone)
        repolish(widget)


def label(
    text: str = "",
    role: str | None = None,
    tone: str | None = None,
    wrap: bool = False,
    selectable: bool = False,
) -> QLabel:
    widget = QLabel(text)
    if role:
        widget.setProperty("role", role)
    if tone:
        widget.setProperty("tone", tone)
    widget.setWordWrap(wrap)
    if selectable:
        widget.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
    return widget


def button(
    text: str,
    icon_name: str | None = None,
    variant: str | None = None,
    size: str | None = None,
    icon_token: str | None = None,
) -> QPushButton:
    widget = QPushButton(text)
    widget.setCursor(Qt.CursorShape.PointingHandCursor)
    if variant:
        widget.setProperty("variant", variant)
    if size:
        widget.setProperty("size", size)
    if icon_name:
        default_token = {"primary": "accent_text", "danger": "critical", "link": "accent"}
        widget.setIcon(icon(icon_name, icon_token or default_token.get(variant or "", "text")))
    return widget


def divider() -> QFrame:
    line = QFrame()
    line.setProperty("divider", True)
    return line


def scroll_area(content: QWidget) -> QScrollArea:
    """Vertical-only scroll area with a transparent background."""
    content.setObjectName("ScrollBody")
    area = QScrollArea()
    area.setWidget(content)
    area.setWidgetResizable(True)
    area.setFrameShape(QFrame.Shape.NoFrame)
    area.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
    return area


def vbox(spacing: int = 0, margins: tuple[int, int, int, int] = (0, 0, 0, 0)) -> QVBoxLayout:
    layout = QVBoxLayout()
    _setup(layout, spacing, margins)
    return layout


def hbox(spacing: int = 0, margins: tuple[int, int, int, int] = (0, 0, 0, 0)) -> QHBoxLayout:
    layout = QHBoxLayout()
    _setup(layout, spacing, margins)
    return layout


def _setup(layout: QBoxLayout, spacing: int, margins: tuple[int, int, int, int]) -> None:
    layout.setSpacing(spacing)
    layout.setContentsMargins(*margins)


class ElidedLabel(QLabel):
    """Single-line label that ends with "…" instead of widening its layout."""

    def minimumSizeHint(self):
        hint = super().minimumSizeHint()
        hint.setWidth(min(hint.width(), 40))
        return hint

    def paintEvent(self, event) -> None:
        from PySide6.QtGui import QPainter

        painter = QPainter(self)
        rect = self.contentsRect()
        text = self.fontMetrics().elidedText(self.text(), Qt.TextElideMode.ElideRight, rect.width())
        painter.setPen(self.palette().color(self.foregroundRole()))
        painter.drawText(rect, int(self.alignment()), text)
