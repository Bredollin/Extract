"""Shared plumbing for analysis rules.

Each rule looks looks at a slice of the report and returns zero or more findings.

Rules are registered with `@rule(role)` in priority order: within the same severity, a rule
registered earlier is listed first. The role says what kind of fix a finding calls for and
is what the final verdict is built from. Every rule must tolerate missing data: checks that
were not run, `None` values and failed benchmarks simply produce no finding.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from enum import Enum
from typing import Any

from extract.core.models import (
    Category,
    DiskInfo,
    Finding,
    HealthCheck,
    MachineReport,
    Severity,
)


class Role(str, Enum):
    """What kind of action a finding calls for."""

    FAULT = "fault"  # a hardware defect or maintenance problem (failing disk, overheating)
    UPGRADE = "upgrade"  # a part that is too slow or too small for the workload
    REPLACE = "replace"  # the machine itself is too weak to be worth upgrading
    SOFTWARE = "software"  # configuration, programs, drivers, Windows itself
    NETWORK = "network"  # outside the computer: Wi-Fi, router, provider, DNS
    OTHER = "other"  # context or something to investigate; does not drive the verdict


# --- data access ------------------------------------------------------------------------


def number(value: Any) -> float | None:
    """Coerce a JSON value to float; None for missing or non-numeric values."""
    if isinstance(value, bool) or value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def fmt(value: float, decimals: int = 0) -> str:
    """Format a number the Brazilian way (decimal comma, dot for thousands)."""
    text = f"{value:,.{decimals}f}"
    return text.replace(",", "_").replace(".", ",").replace("_", ".")


def join_known(*parts: tuple[float | None, str]) -> str:
    """Join the texts whose value is known: `join_known((ms, f"{ms} ms"), ...)`."""
    return ", ".join(text for value, text in parts if value is not None)


@dataclass(frozen=True)
class Context:
    """Read-only, None-tolerant access to the parts of a report the rules need."""

    report: MachineReport

    def health_check(self, check_id: str) -> HealthCheck | None:
        return next((c for c in self.report.health if c.id == check_id), None)

    def check(self, check_id: str) -> dict[str, Any]:
        found = self.health_check(check_id)
        return (found.data or {}) if found else {}

    def value(self, check_id: str, key: str) -> float | None:
        return number(self.check(check_id).get(key))

    def flag(self, check_id: str, key: str) -> bool:
        return self.check(check_id).get(key) is True

    def metric(self, bench_id: str, key: str) -> float | None:
        for bench in self.report.benchmarks:
            if bench.id == bench_id and bench.ok and key in bench.metrics:
                return number(bench.metrics[key].value)
        return None

    @property
    def system_disk(self) -> DiskInfo | None:
        disks = self.report.inventory.disks
        marked = [d for d in disks if d.is_system_disk]
        if marked:
            return marked[0]
        return disks[0] if len(disks) == 1 else None

    @property
    def os_name(self) -> str:
        return self.report.inventory.system.os_name

    @property
    def is_modern_windows(self) -> bool:
        """Windows 10/11, or unknown (assume the stricter, current requirements)."""
        name = self.os_name
        return not name or "Windows 10" in name or "Windows 11" in name

    @property
    def ram_total_gb(self) -> float | None:
        total = self.report.inventory.memory.total_gb
        if not total:
            total = sum(m.capacity_gb for m in self.report.inventory.memory.modules)
        return total or None


def disk_kind(disk: DiskInfo | None) -> str | None:
    """Key into `reference.DISK_EXPECTATIONS`, or None when the type is unknown."""
    if disk is None:
        return None
    if disk.media_type.upper() == "HDD":
        return "hdd"
    if disk.bus_type.upper() == "NVME":
        return "nvme"
    if disk.media_type.upper() == "SSD":
        return "sata_ssd"
    return None


# --- registry -----------------------------------------------------------------------------

RuleFunc = Callable[[Context], list[Finding]]


@dataclass(frozen=True)
class Rule:
    func: RuleFunc
    role: Role

    @property
    def name(self) -> str:
        return self.func.__name__


RULES: list[Rule] = []


def rule(role: Role) -> Callable[[RuleFunc], RuleFunc]:
    def register(func: RuleFunc) -> RuleFunc:
        RULES.append(Rule(func, role))
        return func

    return register


def make_finding(
    id_: str,
    category: Category,
    severity: Severity,
    title: str,
    detail: str,
    recommendation: str,
    **evidence: Any,
) -> list[Finding]:
    clean = {k: v for k, v in evidence.items() if v is not None}
    return [Finding(id_, category, severity, title, detail, recommendation, clean)]


_IGNORED_PROCESSES = {"idle", "_total", "system idle process"}


def top_process(ctx: Context, key: str) -> dict[str, Any] | None:
    processes = [
        p
        for p in ctx.check("cpu.load").get("top_processes") or []
        if isinstance(p, dict)
        and p.get("name")
        and str(p["name"]).lower() not in _IGNORED_PROCESSES
        and number(p.get(key)) is not None
    ]
    return max(processes, key=lambda p: number(p[key]) or 0.0, default=None)
