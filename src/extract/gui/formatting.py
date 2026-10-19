"""Brazilian Portuguese formatting for numbers, sizes, dates and durations."""

from __future__ import annotations

from datetime import datetime


def number(value: float, decimals: int | None = None) -> str:
    """`1234.5` -> `1.234,5`. Without `decimals`, precision shrinks as the value grows."""
    auto = decimals is None
    if decimals is None:
        size = abs(value)
        decimals = 0 if size >= 100 else 1 if size >= 10 else 2
    text = f"{value:,.{decimals}f}"
    if auto and "." in text:
        text = text.rstrip("0").rstrip(".")
    return text.replace(",", "\x00").replace(".", ",").replace("\x00", ".")


def with_unit(value: float, unit: str) -> str:
    if unit in ("x", "%"):
        return f"{number(value)}{unit}"
    return f"{number(value)} {unit}".strip()


def size_gb(value: float) -> str:
    if value >= 1000:
        return f"{number(value / 1024, 1)} TB"
    return f"{number(value, 0 if value >= 100 else 1)} GB"


def date_time(iso: str) -> str:
    """ISO 8601 -> `19/10/2026 10:42`; unparseable text is returned as is."""
    try:
        return datetime.fromisoformat(iso).strftime("%d/%m/%Y %H:%M")
    except ValueError:
        return iso


def duration(seconds: float) -> str:
    """`95` -> `01:35`, `3725` -> `1:02:05`."""
    total = max(int(seconds), 0)
    hours, rest = divmod(total, 3600)
    minutes, secs = divmod(rest, 60)
    return f"{hours}:{minutes:02d}:{secs:02d}" if hours else f"{minutes:02d}:{secs:02d}"


def plural(count: int, singular: str, plural_form: str) -> str:
    return f"{count} {singular if count == 1 else plural_form}"
