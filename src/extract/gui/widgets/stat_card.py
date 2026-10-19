"""Compact summary tile: caption, big value and a detail line."""

from __future__ import annotations

from PySide6.QtWidgets import QFrame, QWidget

from extract.gui.icons import IconLabel
from extract.gui.theme import Space
from extract.gui.widgets.common import ElidedLabel, hbox, label, vbox


class StatCard(QFrame):
    def __init__(
        self,
        caption: str,
        value: str,
        detail: str = "",
        icon_name: str = "info",
        tone: str = "text_muted",
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.setProperty("card", True)
        column = vbox(Space.XS, (Space.L, Space.M, Space.L, Space.M))
        top = hbox(Space.S)
        top.addWidget(IconLabel(icon_name, tone, 16))
        top.addWidget(label(caption.upper(), role="eyebrow"), 1)
        column.addLayout(top)
        self.value = ElidedLabel(value)
        self.value.setProperty("role", "value")
        if tone in ("ok", "warning", "critical", "info", "accent"):
            self.value.setProperty("tone", tone)
        self.value.setToolTip(value)
        column.addWidget(self.value)
        self.detail = ElidedLabel(detail)
        self.detail.setProperty("role", "caption")
        self.detail.setToolTip(detail)
        column.addWidget(self.detail)
        self.setLayout(column)
