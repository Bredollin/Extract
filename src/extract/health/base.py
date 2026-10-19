"""Shared plumbing for health checks: the fail-soft wrapper and small parsing helpers.

A check is written as a plain function that returns an `Outcome` and decorated with
`health_check`, which turns it into a `Check`: callable as `check(ps, inventory)`, it
always returns a `HealthCheck` (or `None` when the check does not apply) and converts any
exception into `Status.UNKNOWN`.
"""

from __future__ import annotations

import logging
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from typing import Any

from extract.core.models import Category, HealthCheck, Inventory, Status
from extract.core.powershell import PowerShellRunner

log = logging.getLogger(__name__)

UNKNOWN_SUMMARY = "Não foi possível verificar."

STATUS_ORDER = (Status.OK, Status.WARNING, Status.CRITICAL)


class MissingData(LookupError):
    """The query ran but returned nothing usable."""


@dataclass
class Outcome:
    status: Status
    summary: str
    data: dict[str, Any] = field(default_factory=dict)


CheckBody = Callable[[PowerShellRunner, Inventory], "Outcome | None"]


@dataclass(frozen=True)
class Check:
    """A health check with its fixed id, category, title and contract data keys."""

    id: str
    category: Category
    title: str
    keys: tuple[str, ...]
    body: CheckBody

    def __call__(self, ps: PowerShellRunner, inventory: Inventory) -> HealthCheck | None:
        try:
            outcome = self.body(ps, inventory)
        except Exception as exc:
            # Expected on locked-down machines, so keep the traceback out of the normal log.
            log.warning("Health check %s failed: %s", self.id, exc)
            log.debug("Health check %s traceback", self.id, exc_info=True)
            return self._result(Outcome(Status.UNKNOWN, UNKNOWN_SUMMARY))
        return None if outcome is None else self._result(outcome)

    def _result(self, outcome: Outcome) -> HealthCheck:
        # Every contract key is always present, so consumers can index without guarding.
        data = dict.fromkeys(self.keys) | outcome.data
        return HealthCheck(
            self.id, self.category, self.title, outcome.status, outcome.summary, data
        )


def health_check(
    check_id: str, category: Category, title: str, keys: Sequence[str]
) -> Callable[[CheckBody], Check]:
    def decorate(body: CheckBody) -> Check:
        return Check(check_id, category, title, tuple(keys), body)

    return decorate


def worst(*statuses: Status) -> Status:
    """The most severe of OK / WARNING / CRITICAL (UNKNOWN is ignored)."""
    known = [s for s in statuses if s in STATUS_ORDER]
    return max(known, key=STATUS_ORDER.index, default=Status.OK)


def level(value: float | None, warning: float, critical: float, *, below: bool = False) -> Status:
    """Status of `value` against two thresholds; `below=True` when lower is worse."""
    if value is None:
        return Status.OK
    if below:
        value, warning, critical = -value, -warning, -critical
    if value >= critical:
        return Status.CRITICAL
    if value >= warning:
        return Status.WARNING
    return Status.OK


def first_row(rows: list[dict[str, Any]]) -> dict[str, Any]:
    if not rows:
        raise MissingData("query returned no rows")
    return rows[0]


def as_list(value: Any) -> list[Any]:
    """`ConvertTo-Json` may turn a one-item array into a scalar; normalize back to a list."""
    if value is None:
        return []
    if isinstance(value, list):
        return value
    return [value]


def to_float(value: Any) -> float | None:
    if value is None or isinstance(value, bool):
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def to_int(value: Any) -> int | None:
    number = to_float(value)
    return None if number is None else int(number)


def rounded(value: float | None, digits: int = 1) -> float | None:
    return None if value is None else round(value, digits)


def fmt(value: float | None, decimals: int = 0) -> str:
    """Format a number the Brazilian way: `1.234,5`."""
    if value is None:
        return "?"
    text = f"{value:,.{decimals}f}"
    return text.replace(",", "_").replace(".", ",").replace("_", ".")


def plural(count: int, singular: str, plural_form: str) -> str:
    return f"{count} {singular if count == 1 else plural_form}"
