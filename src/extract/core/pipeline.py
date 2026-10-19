"""A full scan: inventory, health checks, benchmarks and analysis.

This is the only place that wires the modules together; the CLI and the GUI just call
`run_scan`.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field

from extract import __version__
from extract.analysis import analyze
from extract.benchmarks import run_benchmarks
from extract.collectors import collect_inventory
from extract.core.models import Category, MachineReport
from extract.core.powershell import PowerShell, PowerShellRunner
from extract.core.progress import CancelToken, ProgressCallback, no_progress, sub_progress
from extract.health import run_health_checks

log = logging.getLogger(__name__)


@dataclass
class ScanOptions:
    client: str = ""
    health: bool = True
    benchmarks: set[Category] = field(
        default_factory=lambda: {Category.CPU, Category.MEMORY, Category.STORAGE}
    )
    quick_benchmarks: bool = False


def run_scan(
    options: ScanOptions,
    ps: PowerShellRunner | None = None,
    progress: ProgressCallback = no_progress,
    cancel: CancelToken | None = None,
) -> MachineReport:
    """Run the scan and return the analyzed report.

    Progress slices reflect the rough duration of each step; benchmarks take by far the
    longest.
    """
    ps = ps or PowerShell()
    cancel = cancel or CancelToken()
    report = MachineReport(client=options.client, tool_version=__version__)

    log.info("Collecting hardware inventory")
    report.inventory = collect_inventory(ps, sub_progress(progress, 0.0, 0.15), cancel)
    cancel.raise_if_cancelled()

    if options.health:
        log.info("Running health checks")
        report.health = run_health_checks(
            ps, report.inventory, sub_progress(progress, 0.15, 0.35), cancel
        )
        cancel.raise_if_cancelled()

    if options.benchmarks:
        log.info("Running benchmarks: %s", sorted(c.value for c in options.benchmarks))
        report.benchmarks = run_benchmarks(
            options.benchmarks,
            ps,
            sub_progress(progress, 0.35, 0.95),
            cancel,
            quick=options.quick_benchmarks,
        )
        cancel.raise_if_cancelled()

    progress(0.95, "Analisando resultados")
    report.findings = analyze(report)
    progress(1.0, "Concluído")
    return report
