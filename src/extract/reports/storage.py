"""Saving and loading per-machine reports as JSON.

Each scan becomes `<client folder>/<HOSTNAME>_<YYYY-MM-DD_HHMMSS>.json`. Excel and PDF
exports are always built from these files, never from free-form text.
"""

from __future__ import annotations

import json
import logging
import re
from datetime import datetime
from pathlib import Path

from extract.core.models import MachineReport

log = logging.getLogger(__name__)

REPORT_SUFFIX = ".json"
_UNSAFE_CHARS = re.compile(r"[^A-Za-z0-9._-]+")


def safe_filename(name: str) -> str:
    """Replace characters Windows does not accept in file names."""
    cleaned = _UNSAFE_CHARS.sub("-", name.strip()).strip("-.")
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
    data = json.loads(path.read_text(encoding="utf-8"))
    return MachineReport.from_dict(data)


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
