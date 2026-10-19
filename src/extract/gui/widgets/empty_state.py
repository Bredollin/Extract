"""Friendly placeholder shown when a page has nothing to display yet."""

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QPushButton, QWidget

from extract.gui.icons import IconLabel
from extract.gui.theme import Space
from extract.gui.widgets.common import hbox, label, vbox


class EmptyState(QWidget):
    def __init__(
        self,
        icon_name: str,
        title: str,
        message: str,
        actions: list[QPushButton] | None = None,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        column = vbox(Space.M, (Space.XL, Space.XXL, Space.XL, Space.XXL))
        column.addStretch(1)
        center = Qt.AlignmentFlag.AlignHCenter
        column.addWidget(IconLabel(icon_name, "accent", 28, badge=True), 0, center)
        column.addSpacing(Space.S)
        heading = label(title, role="section")
        heading.setAlignment(Qt.AlignmentFlag.AlignCenter)
        column.addWidget(heading)
        text = label(message, role="muted", wrap=True)
        text.setAlignment(Qt.AlignmentFlag.AlignCenter)
        text.setMaximumWidth(440)
        text_row = hbox()
        text_row.addStretch(1)
        text_row.addWidget(text, 4)
        text_row.addStretch(1)
        column.addLayout(text_row)
        if actions:
            row = hbox(Space.S)
            row.addStretch(1)
            for action in actions:
                row.addWidget(action)
            row.addStretch(1)
            column.addSpacing(Space.S)
            column.addLayout(row)
        column.addStretch(2)
        self.setLayout(column)
