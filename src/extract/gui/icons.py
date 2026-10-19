"""Bundled SVG icons, tinted with the active theme at paint time.

The icons use `currentColor`; `ThemedIconEngine` swaps in a palette token when Qt paints
them, so a theme switch only needs a repaint and no icon has to be rebuilt.
"""

from __future__ import annotations

from functools import cache
from pathlib import Path

from PySide6.QtCore import QByteArray, QRect, QRectF, QSize, Qt
from PySide6.QtGui import QIcon, QIconEngine, QPainter, QPixmap
from PySide6.QtSvg import QSvgRenderer
from PySide6.QtWidgets import QSizePolicy, QWidget

from extract.gui import theme

ASSETS_DIR = Path(__file__).parent / "assets"
ICONS_DIR = ASSETS_DIR / "icons"
APP_ICON_SVG = ASSETS_DIR / "icon.svg"
APP_ICON_ICO = ASSETS_DIR / "icon.ico"


@cache
def _svg_source(name: str) -> str:
    return (ICONS_DIR / f"{name}.svg").read_text(encoding="utf-8")


@cache
def _renderer(name: str, color: str) -> QSvgRenderer:
    data = _svg_source(name).replace("currentColor", color)
    return QSvgRenderer(QByteArray(data.encode("utf-8")))


def paint_icon(painter: QPainter, rect: QRect | QRectF, name: str, token: str) -> None:
    _renderer(name, theme.palette().color(token).name()).render(painter, QRectF(rect))


class ThemedIconEngine(QIconEngine):
    """Paints an SVG icon in `token`, or `checked_token` when the button is checked."""

    def __init__(self, name: str, token: str, checked_token: str | None = None) -> None:
        super().__init__()
        self._name = name
        self._token = token
        self._checked_token = checked_token or token

    def paint(self, painter: QPainter, rect: QRect, mode: QIcon.Mode, state: QIcon.State) -> None:
        token = self._checked_token if state == QIcon.State.On else self._token
        if mode == QIcon.Mode.Disabled:
            token = "text_muted"
            painter.setOpacity(0.6)
        paint_icon(painter, rect, self._name, token)

    def pixmap(self, size: QSize, mode: QIcon.Mode, state: QIcon.State) -> QPixmap:
        pixmap = QPixmap(size)
        pixmap.fill(Qt.GlobalColor.transparent)
        painter = QPainter(pixmap)
        self.paint(painter, QRect(0, 0, size.width(), size.height()), mode, state)
        painter.end()
        return pixmap

    def clone(self) -> QIconEngine:
        return ThemedIconEngine(self._name, self._token, self._checked_token)


def icon(name: str, token: str = "text", checked_token: str | None = None) -> QIcon:
    return QIcon(ThemedIconEngine(name, token, checked_token))


class IconLabel(QWidget):
    """A fixed-size themed icon, optionally on a soft circular background."""

    def __init__(
        self,
        name: str,
        token: str = "text_muted",
        size: int = 20,
        badge: bool = False,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self._name = name
        self._token = token
        self._size = size
        self._badge = badge
        side = round(size * 1.9) if badge else size
        self.setFixedSize(side, side)
        self.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Fixed)

    def set_icon(self, name: str, token: str | None = None) -> None:
        self._name = name
        self._token = token or self._token
        self.update()

    def paintEvent(self, event) -> None:
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        if self._badge:
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(theme.palette().color(_soft_token(self._token)))
            painter.drawEllipse(self.rect())
        offset = (self.width() - self._size) / 2
        paint_icon(painter, QRectF(offset, offset, self._size, self._size), self._name, self._token)


class AppLogo(QWidget):
    """The full-color app icon (not tinted by the theme)."""

    def __init__(self, size: int, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setFixedSize(size, size)

    def paintEvent(self, event) -> None:
        app_icon().paint(QPainter(self), self.rect())


def _soft_token(token: str) -> str:
    soft = "neutral_soft" if token == "text_muted" else f"{token}_soft"
    return soft if soft in theme.palette().colors else "surface_alt"


def app_icon() -> QIcon:
    if APP_ICON_ICO.exists():
        return QIcon(str(APP_ICON_ICO))
    return QIcon(str(APP_ICON_SVG))
