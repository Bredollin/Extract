"""Left navigation: brand, one button per page and the theme switch."""

from __future__ import annotations

from PySide6.QtCore import QSize, Qt, Signal
from PySide6.QtWidgets import QButtonGroup, QFrame, QPushButton, QWidget

from extract import __version__
from extract.gui import theme
from extract.gui.icons import AppLogo, icon
from extract.gui.theme import Space
from extract.gui.widgets.common import hbox, label, vbox

SIDEBAR_WIDTH = 224


class Sidebar(QFrame):
    page_selected = Signal(int)
    theme_toggled = Signal()

    def __init__(self, pages: list[tuple[str, str]], parent: QWidget | None = None) -> None:
        """`pages` is a list of (title, icon name), in stack order."""
        super().__init__(parent)
        self.setObjectName("Sidebar")
        self.setFixedWidth(SIDEBAR_WIDTH)
        column = vbox(Space.XS, (Space.L, Space.XL, Space.L, Space.L))

        brand = hbox(Space.S + 2, (Space.S, 0, 0, 0))
        brand.addWidget(AppLogo(30))
        names = vbox(0)
        title = label("Extract")
        title.setObjectName("Brand")
        names.addWidget(title)
        names.addWidget(label("Diagnóstico de PCs", role="caption"))
        brand.addLayout(names, 1)
        column.addLayout(brand)
        column.addSpacing(Space.XL)
        column.addWidget(label("MENU", role="eyebrow"), 0, Qt.AlignmentFlag.AlignLeft)
        column.addSpacing(Space.XS)

        self.group = QButtonGroup(self)
        self.group.setExclusive(True)
        self.buttons: list[QPushButton] = []
        for index, (text, icon_name) in enumerate(pages):
            button = self._nav_button(text, icon_name)
            self.group.addButton(button, index)
            self.buttons.append(button)
            column.addWidget(button)
        self.group.idClicked.connect(self.page_selected)

        column.addStretch(1)
        self.theme_button = self._nav_button("", "moon")
        self.theme_button.setCheckable(False)
        self.theme_button.clicked.connect(self.theme_toggled)
        column.addWidget(self.theme_button)
        column.addSpacing(Space.S)
        column.addWidget(label(f"Versão {__version__}", role="caption"))
        self.setLayout(column)
        self.refresh_theme_button()
        theme.manager().changed.connect(self.refresh_theme_button)

    @staticmethod
    def _nav_button(text: str, icon_name: str) -> QPushButton:
        button = QPushButton(text)
        button.setObjectName("NavButton")
        button.setCheckable(True)
        button.setCursor(Qt.CursorShape.PointingHandCursor)
        button.setIcon(icon(icon_name, "text_muted", "accent"))
        button.setIconSize(QSize(18, 18))
        return button

    def refresh_theme_button(self, _palette: object = None) -> None:
        dark = theme.palette().is_dark
        self.theme_button.setText("Tema claro" if dark else "Tema escuro")
        self.theme_button.setIcon(icon("sun" if dark else "moon", "text_muted"))

    def select(self, index: int) -> None:
        self.buttons[index].setChecked(True)
