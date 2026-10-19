"""Page title, subtitle and an optional row of actions on the right."""

from __future__ import annotations

from PySide6.QtWidgets import QWidget

from extract.gui.theme import Space
from extract.gui.widgets.common import hbox, label, vbox


class PageHeader(QWidget):
    def __init__(self, title: str, subtitle: str = "", parent: QWidget | None = None) -> None:
        super().__init__(parent)
        row = hbox(Space.L)
        texts = vbox(Space.XS)
        self.title = label(title, role="title")
        self.subtitle = label(subtitle, role="subtitle", wrap=True)
        texts.addWidget(self.title)
        texts.addWidget(self.subtitle)
        row.addLayout(texts, 1)
        self.actions = hbox(Space.S)
        row.addLayout(self.actions)
        self.setLayout(row)

    def add_action(self, widget: QWidget) -> None:
        self.actions.addWidget(widget)
