"""Analysis: cross-checks inventory, health and benchmarks to point at the likely root cause."""

from __future__ import annotations

import logging

from extract.analysis.rules import RULES, Context
from extract.analysis.verdict import RatedFinding, build_verdict
from extract.core.models import Finding, MachineReport

log = logging.getLogger(__name__)


def analyze(report: MachineReport) -> list[Finding]:
    """Return findings sorted from most to least severe, with the verdict first.

    Within one severity, findings keep the priority order the rules were registered in. A
    rule that crashes on unexpected data is logged and skipped.
    """
    ctx = Context(report)
    rated: list[tuple[int, RatedFinding]] = []
    for priority, rule in enumerate(RULES):
        try:
            produced = rule.func(ctx)
        except Exception:
            log.exception("Analysis rule %s failed", rule.name)
            continue
        rated.extend((priority, RatedFinding(f, rule.role)) for f in produced)

    rated.sort(key=lambda item: (-item[1].finding.severity.rank, item[0]))
    verdict = build_verdict([r for _, r in rated])
    return [verdict, *(r.finding for _, r in rated)]
