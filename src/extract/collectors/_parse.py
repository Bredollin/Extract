"""Helpers that turn loosely typed `ConvertTo-Json` values into clean Python values.

CIM data is messy: numbers sometimes arrive as strings, single-item arrays arrive as plain
objects, OEMs leave placeholder text in serial numbers, and dates come in three different
formats depending on the PowerShell version. Collectors go through these helpers so each
of them only has to deal with the meaning of the data.
"""

from __future__ import annotations

import re
from datetime import datetime, timedelta, timezone
from typing import Any

GIB = 1024**3

# Text that firmware vendors leave in fields they never filled in.
_PLACEHOLDERS = {
    "",
    "0",
    "none",
    "n/a",
    "na",
    "null",
    "unknown",
    "default string",
    "to be filled by o.e.m.",
    "to be filled by oem",
    "system serial number",
    "system product name",
    "system manufacturer",
    "system version",
    "base board serial number",
    "chassis serial number",
    "not applicable",
    "not specified",
    "oem",
    "o.e.m.",
}

_DOTNET_DATE = re.compile(r"/Date\((-?\d+)(?:[+-]\d{4})?\)/")
_DMTF_DATE = re.compile(r"^(\d{14})\.\d{6}([+-])(\d{3})$")
_FRACTION = re.compile(r"\.\d+")


def as_list(value: Any) -> list[Any]:
    """`ConvertTo-Json` turns one-item arrays into a bare object and empty ones into null."""
    if value is None:
        return []
    if isinstance(value, list):
        return value
    return [value]


def first(rows: list[dict[str, Any]]) -> dict[str, Any]:
    return rows[0] if rows else {}


def text(value: Any) -> str:
    """Strip a value into a string; `None` becomes an empty string."""
    if value is None:
        return ""
    return str(value).strip()


def clean(value: Any) -> str:
    """Like `text`, but drops OEM placeholders such as "To Be Filled By O.E.M."."""
    result = text(value)
    return "" if result.lower() in _PLACEHOLDERS else result


def to_int(value: Any, default: int = 0) -> int:
    if isinstance(value, bool):
        return int(value)
    try:
        return int(float(value))
    except (TypeError, ValueError):
        return default


def to_float(value: Any, default: float = 0.0) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def to_bool(value: Any) -> bool:
    if isinstance(value, str):
        return value.strip().lower() in {"true", "1", "yes"}
    return bool(value)


def bytes_to_gb(value: Any, digits: int = 1) -> float:
    """Bytes to GiB, which is what Windows itself labels "GB"."""
    return round(to_float(value) / GIB, digits)


def cim_datetime(value: Any) -> str:
    """Convert any CIM date representation to ISO 8601 (empty string when unknown).

    Handles Windows PowerShell 5.1 (`/Date(ms)/`, sometimes wrapped in an object with a
    `value` key), PowerShell 7 (already ISO 8601) and raw WMI DMTF strings
    (`20231017083000.000000-180`).
    """
    if isinstance(value, dict):
        value = value.get("value", value.get("DateTime"))
    raw = text(value)
    if not raw:
        return ""
    parsed = _parse_datetime(raw)
    return parsed.isoformat(timespec="seconds") if parsed else ""


def cim_date(value: Any) -> str:
    """Like `cim_datetime`, but keeps only the date (driver dates carry no real time)."""
    iso = cim_datetime(value)
    return iso[:10]


def _parse_datetime(raw: str) -> datetime | None:
    if match := _DOTNET_DATE.search(raw):
        stamp = datetime.fromtimestamp(int(match.group(1)) / 1000, tz=timezone.utc)
        return stamp.astimezone()
    if match := _DMTF_DATE.match(raw):
        digits, sign, minutes = match.groups()
        offset = timedelta(minutes=int(minutes)) * (-1 if sign == "-" else 1)
        return datetime.strptime(digits, "%Y%m%d%H%M%S").replace(tzinfo=timezone(offset))
    # Python 3.10's fromisoformat rejects "Z" and 7-digit fractions (PowerShell 7 emits both).
    normalized = _FRACTION.sub("", raw).replace("Z", "+00:00")
    try:
        parsed = datetime.fromisoformat(normalized)
    except ValueError:
        return None
    # A date without offset is local time on the scanned machine.
    return parsed if parsed.tzinfo else parsed.astimezone()
