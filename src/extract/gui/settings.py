"""Portable user preferences and folders: nothing goes to the registry or the user profile.

The packaged exe runs from a USB stick on client machines and must leave no trace there,
so preferences live in an INI file next to the app. When that folder is read-only they
only last for the session. Folder rules come from `extract.reports.paths`.
"""

from __future__ import annotations

import tempfile
from pathlib import Path
from typing import Any

from PySide6.QtCore import QSettings

SETTINGS_FILENAME = "extract.ini"

_memory: dict[str, Any] = {}


def app_dir() -> Path:
    try:
        from extract.reports.paths import app_dir as shared_app_dir
    except ImportError:
        return Path.cwd()
    return shared_app_dir()


def reports_root() -> Path:
    """Parent folder of every client folder."""
    try:
        from extract.reports.paths import default_reports_root
    except ImportError:
        return Path.cwd() / "reports"
    return default_reports_root()


def client_folder(client: str) -> Path:
    """Default folder for one client's reports."""
    try:
        from extract.reports.paths import client_folder as shared_client_folder
    except ImportError:
        from extract.reports.storage import safe_filename

        return reports_root() / safe_filename(client or "sem-cliente")
    return shared_client_folder(client)


def _is_writable(folder: Path) -> bool:
    try:
        with tempfile.TemporaryFile(dir=folder):
            return True
    except OSError:
        return False


def _settings() -> QSettings | None:
    folder = app_dir()
    if not _is_writable(folder):
        return None
    return QSettings(str(folder / SETTINGS_FILENAME), QSettings.Format.IniFormat)


def value(key: str, default: Any = None) -> Any:
    if key in _memory:
        return _memory[key]
    settings = _settings()
    return settings.value(key, default) if settings else default


def set_value(key: str, value: Any) -> None:
    _memory[key] = value
    settings = _settings()
    if settings:
        settings.setValue(key, value)
        settings.sync()
