"""Color themes: palettes stored as JSON, turned into one Qt stylesheet.

Each palette defines semantic tokens (background, surface, text, accent, ok, warning, ...).
`build_stylesheet` fills `assets/themes/style.qss` with those tokens plus a few derived
ones (`<tone>_soft` tints, hover shades), so every widget gets its colors from one place.
Custom-painted widgets read the active palette with `palette()`.
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from pathlib import Path
from string import Template

from PySide6.QtCore import QObject, Signal
from PySide6.QtGui import QColor, QFont, QPalette
from PySide6.QtWidgets import QApplication

from extract.core.models import Severity, Status
from extract.gui import settings

log = logging.getLogger(__name__)

THEMES_DIR = Path(__file__).parent / "assets" / "themes"
ICONS_DIR = Path(__file__).parent / "assets" / "icons"
THEME_NAMES = ("dark", "light")
DEFAULT_THEME = "dark"
REQUIRED_TOKENS = (
    "background",
    "surface",
    "surface_alt",
    "border",
    "text",
    "text_muted",
    "accent",
    "ok",
    "warning",
    "critical",
    "info",
)
TONES = ("accent", "ok", "warning", "critical", "info")
FONT_FAMILIES = ["Segoe UI", "Segoe UI Variable", "Inter", "Helvetica Neue", "Arial"]
MONO_FAMILIES = ["Cascadia Mono", "Consolas", "DejaVu Sans Mono", "monospace"]
_SETTINGS_KEY = "ui/theme"


class Space:
    """Spacing scale in pixels, used by every layout."""

    XS = 4
    S = 8
    M = 12
    L = 16
    XL = 24
    XXL = 32


STATUS_TONES = {
    Status.OK: "ok",
    Status.WARNING: "warning",
    Status.CRITICAL: "critical",
    Status.UNKNOWN: "neutral",
}
SEVERITY_TONES = {
    Severity.INFO: "info",
    Severity.WARNING: "warning",
    Severity.CRITICAL: "critical",
}


@dataclass(frozen=True)
class Palette:
    name: str
    label: str
    colors: dict[str, str]

    def __getitem__(self, token: str) -> str:
        return self.colors[token]

    def color(self, token: str) -> QColor:
        """The token as a QColor; `neutral` maps to the muted text color."""
        return QColor(self.colors.get(token) or self.colors["text_muted"])

    @property
    def is_dark(self) -> bool:
        return QColor(self.colors["background"]).lightnessF() < 0.5


def load_palette(name: str) -> Palette:
    data = json.loads((THEMES_DIR / f"{name}.json").read_text(encoding="utf-8"))
    colors = dict(data["colors"])
    missing = [t for t in REQUIRED_TOKENS if t not in colors]
    if missing:
        raise ValueError(f"Theme {name!r} is missing tokens: {', '.join(missing)}")
    colors.setdefault("accent_text", "#FFFFFF")
    colors.update(_derived_tokens(colors))
    return Palette(name=data.get("name", name), label=data.get("label", name), colors=colors)


def _derived_tokens(colors: dict[str, str]) -> dict[str, str]:
    surface, text = colors["surface"], colors["text"]
    dark = QColor(colors["background"]).lightnessF() < 0.5
    derived = {
        f"{tone}_soft": blend(colors[tone], surface, 0.16 if dark else 0.10) for tone in TONES
    }
    derived["neutral"] = colors["text_muted"]
    derived["neutral_soft"] = blend(colors["text_muted"], surface, 0.14)
    derived["accent_hover"] = blend(text, colors["accent"], 0.14)
    derived["surface_hover"] = blend(text, colors["surface_alt"], 0.05)
    derived["border_strong"] = blend(text, colors["border"], 0.18)
    derived["track"] = blend(text, colors["surface_alt"], 0.07)
    # QSS can only load images from files: pick the bundled checkmark that reads on the accent.
    light_mark = QColor(colors.get("accent_text", "#FFFFFF")).lightnessF() >= 0.5
    checkmark = ICONS_DIR / f"checkmark-{'light' if light_mark else 'dark'}.svg"
    derived["checkmark"] = checkmark.as_posix()
    return derived


def blend(top: str, bottom: str, amount: float) -> str:
    """Mix `top` over `bottom` with the given opacity, as a hex color."""
    a, b = QColor(top), QColor(bottom)
    mixed = QColor(
        round(a.red() * amount + b.red() * (1 - amount)),
        round(a.green() * amount + b.green() * (1 - amount)),
        round(a.blue() * amount + b.blue() * (1 - amount)),
    )
    return mixed.name().upper()


def contrast_ratio(fg: str, bg: str) -> float:
    """WCAG 2.x contrast ratio between two colors."""

    def luminance(hex_color: str) -> float:
        def channel(c: float) -> float:
            return c / 12.92 if c <= 0.03928 else ((c + 0.055) / 1.055) ** 2.4

        color = QColor(hex_color)
        r, g, b = (channel(v) for v in (color.redF(), color.greenF(), color.blueF()))
        return 0.2126 * r + 0.7152 * g + 0.0722 * b

    high, low = sorted((luminance(fg), luminance(bg)), reverse=True)
    return (high + 0.05) / (low + 0.05)


def build_stylesheet(palette: Palette) -> str:
    template = Template((THEMES_DIR / "style.qss").read_text(encoding="utf-8"))
    return template.substitute(palette.colors)


def qt_palette(palette: Palette) -> QPalette:
    """A QPalette matching the theme, for the parts Qt draws natively (arrows, menus)."""
    roles = QPalette.ColorRole
    qp = QPalette()
    for role, token in (
        (roles.Window, "background"),
        (roles.WindowText, "text"),
        (roles.Base, "surface_alt"),
        (roles.AlternateBase, "surface"),
        (roles.Text, "text"),
        (roles.Button, "surface_alt"),
        (roles.ButtonText, "text"),
        (roles.ToolTipBase, "surface_alt"),
        (roles.ToolTipText, "text"),
        (roles.PlaceholderText, "text_muted"),
        (roles.Highlight, "accent"),
        (roles.HighlightedText, "accent_text"),
        (roles.Link, "accent"),
    ):
        qp.setColor(role, palette.color(token))
    qp.setColor(QPalette.ColorGroup.Disabled, roles.Text, palette.color("text_muted"))
    qp.setColor(QPalette.ColorGroup.Disabled, roles.ButtonText, palette.color("text_muted"))
    return qp


def app_font() -> QFont:
    font = QFont()
    font.setFamilies(FONT_FAMILIES)
    font.setPixelSize(13)
    font.setHintingPreference(QFont.HintingPreference.PreferNoHinting)
    return font


def mono_font() -> QFont:
    font = QFont()
    font.setFamilies(MONO_FAMILIES)
    font.setStyleHint(QFont.StyleHint.Monospace)
    font.setPixelSize(12)
    return font


class ThemeManager(QObject):
    """Holds the active palette and applies it to the application."""

    changed = Signal(object)

    def __init__(self) -> None:
        super().__init__()
        self._palette = load_palette(DEFAULT_THEME)

    @property
    def palette(self) -> Palette:
        return self._palette

    def apply(self, name: str, remember: bool = True) -> Palette:
        if name not in THEME_NAMES:
            log.warning("Unknown theme %r, using %s", name, DEFAULT_THEME)
            name = DEFAULT_THEME
        self._palette = load_palette(name)
        app = QApplication.instance()
        if isinstance(app, QApplication):
            app.setPalette(qt_palette(self._palette))
            app.setStyleSheet(build_stylesheet(self._palette))
        if remember:
            settings.set_value(_SETTINGS_KEY, name)
        self.changed.emit(self._palette)
        return self._palette

    def apply_saved(self) -> Palette:
        return self.apply(str(settings.value(_SETTINGS_KEY, DEFAULT_THEME)), remember=False)

    def toggle(self) -> Palette:
        return self.apply("light" if self._palette.name == "dark" else "dark")


_manager: ThemeManager | None = None


def manager() -> ThemeManager:
    global _manager
    if _manager is None:
        _manager = ThemeManager()
    return _manager


def palette() -> Palette:
    return manager().palette
