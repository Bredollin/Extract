"""Saving and loading per-machine reports as JSON.

Each scan becomes `<client folder>/<HOSTNAME>_<YYYY-MM-DD_HHMMSS>.json`. Excel and PDF
exports are always built from these files, never from free-form text.
"""

from __future__ import annotations

import json
import logging
import re
import unicodedata
from datetime import datetime
from pathlib import Path

from extract.core.models import MachineReport

log = logging.getLogger(__name__)

REPORT_SUFFIX = ".json"
_UNSAFE_CHARS = re.compile(r"[^A-Za-z0-9._-]+")
_MAX_NAME_LENGTH = 80  # keeps <stick>/Relatorios/<client>/<host>_<stamp>.json under MAX_PATH
# Device names Windows reserves in every folder, with or without an extension.
_RESERVED_NAMES = {
    "CON", "PRN", "AUX", "NUL",
    *(f"COM{i}" for i in range(1, 10)),
    *(f"LPT{i}" for i in range(1, 10)),
}  # fmt: skip


def safe_filename(name: str) -> str:
    """Turn any name into a portable file name: accents dropped, other symbols as `-`."""
    ascii_name = unicodedata.normalize("NFKD", name).encode("ascii", "ignore").decode()
    cleaned = _UNSAFE_CHARS.sub("-", ascii_name.strip()).strip("-.")
    cleaned = cleaned[:_MAX_NAME_LENGTH].rstrip("-.")
    if cleaned.split(".")[0].upper() in _RESERVED_NAMES:
        cleaned = f"_{cleaned}"
    return cleaned or "unnamed"


def report_filename(report: MachineReport) -> str:
    try:
        stamp = datetime.fromisoformat(report.created_at).strftime("%Y-%m-%d_%H%M%S")
    except ValueError:
        stamp = datetime.now().strftime("%Y-%m-%d_%H%M%S")
    return f"{safe_filename(report.hostname)}_{stamp}{REPORT_SUFFIX}"


def save_report(report: MachineReport, folder: Path) -> Path:
    folder.mkdir(parents=True, exist_ok=True)
    path = folder / report_filename(report)
    path.write_text(json.dumps(report.to_dict(), ensure_ascii=False, indent=2), encoding="utf-8")
    log.info("Report saved to %s", path)
    return path


def load_report(path: Path) -> MachineReport:
    """Load one report. Any malformed or edited file raises `ValueError` (or `OSError`)."""
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(data, dict):
            raise ValueError("not a report object")
        return MachineReport.from_dict(data)
    except (AttributeError, KeyError, RecursionError, TypeError) as exc:
        raise ValueError(f"malformed report: {exc}") from exc


def load_folder(folder: Path, latest_only: bool = True) -> list[MachineReport]:
    """Load every report in a client folder.

    With `latest_only`, keep only the most recent scan of each machine. Corrupted files
    are skipped with a warning in the log.
    """
    reports: list[MachineReport] = []
    for path in sorted(folder.glob(f"*{REPORT_SUFFIX}")):
        try:
            reports.append(load_report(path))
        except (OSError, ValueError, TypeError, KeyError) as exc:
            log.warning("Skipping %s: %s", path.name, exc)

    if not latest_only:
        return reports
    latest: dict[str, MachineReport] = {}
    for report in reports:
        current = latest.get(report.hostname)
        if current is None or report.created_at > current.created_at:
            latest[report.hostname] = report
    return sorted(latest.values(), key=lambda r: r.hostname.lower())
