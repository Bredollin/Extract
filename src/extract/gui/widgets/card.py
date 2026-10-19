"""Rounded surface panel, the basic building block of every page."""

from __future__ import annotations

from PySide6.QtWidgets import QFrame, QVBoxLayout, QWidget

from extract.gui.theme import Space
from extract.gui.widgets.common import label, set_tone


class Card(QFrame):
    """A bordered surface with an optional section title."""

    def __init__(
        self,
        title: str = "",
        padding: int = Space.XL,
        spacing: int = Space.M,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.setProperty("card", True)
        self.body = QVBoxLayout(self)
        self.body.setContentsMargins(padding, padding - 4, padding, padding)
        self.body.setSpacing(spacing)
        if title:
            self.body.addWidget(label(title, role="section"))

    def set_tone(self, tone: str) -> None:
        set_tone(self, tone)
