"""CPU, memory and disk benchmarks."""

from __future__ import annotations

from extract.core.models import BenchmarkResult, Category
from extract.core.powershell import PowerShellRunner
from extract.core.progress import CancelToken, ProgressCallback, no_progress


def run_benchmarks(
    categories: set[Category],
    ps: PowerShellRunner,
    progress: ProgressCallback = no_progress,
    cancel: CancelToken | None = None,
    quick: bool = False,
) -> list[BenchmarkResult]:
    """Run the benchmarks for the requested categories (CPU, MEMORY, STORAGE).

    `quick=True` uses smaller workloads (for CI and for a fast sanity check).
    """
    raise NotImplementedError
