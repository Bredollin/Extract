"""Where reports are saved by default.

Extract usually runs from a USB stick on the client's machine and must leave nothing
behind there, so the frozen .exe keeps its reports next to itself, on the stick. Running
from source (development, CI) uses `./reports` instead.
"""

from __future__ import annotations

import sys
import tempfile
from pathlib import Path

from extract.reports.storage import safe_filename

NO_CLIENT_FOLDER = "sem-cliente"


def app_dir() -> Path:
    """Folder of the running .exe when frozen by PyInstaller, else the working directory."""
    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve().parent
    return Path.cwd()


def default_reports_root() -> Path:
    """`Relatorios` next to the .exe (or `./reports` from source).

    Falls back to `Documents/Extract` when that location is read-only, e.g. a write-protected
    stick or the exe launched from a network share.
    """
    root = app_dir() / ("Relatorios" if getattr(sys, "frozen", False) else "reports")
    return root if _is_writable(root) else Path.home() / "Documents" / "Extract"


def _is_writable(folder: Path) -> bool:
    try:
        folder.mkdir(parents=True, exist_ok=True)
        with tempfile.TemporaryFile(dir=folder):
            return True
    except OSError:
        return False


def client_folder(client: str) -> Path:
    """Default folder for one client's reports (`sem-cliente` when no client is given)."""
    name = safe_filename(client) if client.strip() else NO_CLIENT_FOLDER
    return default_reports_root() / name
