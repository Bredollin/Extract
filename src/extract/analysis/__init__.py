"""Analysis: cross-checks inventory, health and benchmarks to point at the likely root cause."""

from __future__ import annotations

from extract.core.models import Finding, MachineReport


def analyze(report: MachineReport) -> list[Finding]:
    """Return findings sorted from most to least severe."""
    raise NotImplementedError
