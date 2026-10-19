"""CPU, memory and disk benchmarks.

Each benchmark returns `BenchmarkResult`s; one that fails comes back with `error` set and
the others still run. Cancelling raises `Cancelled` right away (the disk test deletes its
temporary file on the way out).
"""

from __future__ import annotations

import logging
import time
from collections.abc import Callable
from dataclasses import dataclass

from extract.benchmarks import cpu, disk, memory
from extract.core.models import BenchmarkResult, Category
from extract.core.powershell import PowerShellRunner
from extract.core.progress import (
    Cancelled,
    CancelToken,
    ProgressCallback,
    no_progress,
    sub_progress,
)

log = logging.getLogger(__name__)


@dataclass
class _Step:
    category: Category
    results: tuple[tuple[str, str], ...]  # (id, title) of each result the step produces
    weight: float  # rough relative duration, for the progress bar
    run: Callable[[ProgressCallback], list[BenchmarkResult]]


def _plan(
    ps: PowerShellRunner, cancel: CancelToken, quick: bool, done: dict[str, BenchmarkResult]
) -> list[_Step]:
    cpu_sizes = cpu.QUICK if quick else cpu.FULL
    disk_sizes = disk.QUICK if quick else disk.FULL

    def single_score() -> float | None:
        single = done.get("cpu.single")
        score = single.metrics.get("score") if single and single.ok else None
        return score.value if score else None

    return [
        _Step(
            Category.CPU,
            (("cpu.single", cpu.SINGLE_TITLE),),
            1,
            lambda p: [cpu.run_single(p, cancel, cpu_sizes)],
        ),
        _Step(
            Category.CPU,
            (("cpu.multi", cpu.MULTI_TITLE),),
            1,
            lambda p: [cpu.run_multi(p, cancel, cpu_sizes, single_score())],
        ),
        _Step(
            Category.CPU,
            (("cpu.sustained", cpu.SUSTAINED_TITLE),),
            4,
            lambda p: [cpu.run_sustained(ps, p, cancel, cpu_sizes)],
        ),
        _Step(
            Category.MEMORY,
            (("memory.bandwidth", memory.TITLE),),
            1,
            lambda p: [memory.run_bandwidth(p, cancel, quick)],
        ),
        _Step(
            Category.STORAGE,
            (("storage.sequential", disk.SEQUENTIAL_TITLE), ("storage.random", disk.RANDOM_TITLE)),
            6,
            lambda p: disk.run_disk(p, cancel, disk_sizes),
        ),
    ]


def _run_step(step: _Step, progress: ProgressCallback) -> list[BenchmarkResult]:
    start = time.perf_counter()
    try:
        produced = step.run(progress)
    except Cancelled:
        raise
    except Exception as exc:
        log.exception("Benchmark step %s failed", step.results[0][0])
        produced = [
            BenchmarkResult(id_, step.category, title, error=f"Falha no teste: {exc}")
            for id_, title in step.results
        ]
    share = (time.perf_counter() - start) / len(produced)
    for result in produced:
        result.duration_s = round(share, 2)
    return produced


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
    cancel = cancel or CancelToken()
    done: dict[str, BenchmarkResult] = {}
    steps = [s for s in _plan(ps, cancel, quick, done) if s.category in categories]
    total = sum(s.weight for s in steps) or 1.0
    elapsed_weight = 0.0
    for step in steps:
        cancel.raise_if_cancelled()
        start, end = elapsed_weight / total, (elapsed_weight + step.weight) / total
        for result in _run_step(step, sub_progress(progress, start, end)):
            done[result.id] = result
        elapsed_weight += step.weight
    progress(1.0, "Testes de desempenho concluídos")
    return list(done.values())
