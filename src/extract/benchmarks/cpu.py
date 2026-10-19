"""CPU benchmarks: single-core, multi-core and sustained (throttling) performance.

All three run the same fixed, deterministic work unit (integer hashing, zlib compression and
sorting on a fixed seed), so their scores are directly comparable. Worker functions live at
module level because the multi-core tests use the 'spawn' start method, which is what a
frozen PyInstaller executable on Windows uses anyway.
"""

from __future__ import annotations

import logging
import multiprocessing
import os
import queue
import random
import statistics
import sys
import threading
import time
import zlib
from collections.abc import Callable
from dataclasses import dataclass

from extract.core.models import BenchmarkResult, Category, Metric
from extract.core.powershell import PowerShellRunner, safe_query
from extract.core.progress import CancelToken, ProgressCallback

log = logging.getLogger(__name__)

# Score = work units per second scaled so that one core of the calibration machine (a
# current x86-64 server core, ~3 GHz) scores about 1000.
SCORE_PER_UNIT_PER_S = 1000 / 53.0

SINGLE_TITLE = "Processador: um núcleo"
MULTI_TITLE = "Processador: todos os núcleos"
SUSTAINED_TITLE = "Processador: carga contínua"

_WORDS = ("processador", "memória", "disco", "rede", "sistema", "arquivo", "lento", "rápido")


@dataclass(frozen=True)
class CpuSizes:
    single_rounds: int
    units_per_round: int
    multi_units_per_worker: int
    sustained_s: float


FULL = CpuSizes(single_rounds=5, units_per_round=24, multi_units_per_worker=60, sustained_s=30.0)
QUICK = CpuSizes(single_rounds=3, units_per_round=12, multi_units_per_worker=16, sustained_s=6.0)

_CLOCK_SCRIPT = (
    "Get-CimInstance Win32_PerfFormattedData_Counters_ProcessorInformation "
    "-Filter \"Name='_Total'\" | Select-Object PercentProcessorPerformance"
)
_BASE_CLOCK_SCRIPT = "Get-CimInstance Win32_Processor | Select-Object MaxClockSpeed"
CLOCK_SAMPLE_INTERVAL_S = 2.0


def work_unit(seed: int) -> int:
    """One fixed slice of CPU work (~20 ms on a modern core); returns a checksum."""
    rng = random.Random(seed)

    value = seed & 0xFFFFFFFF
    for i in range(60_000):
        value = ((value ^ i) * 16777619) & 0xFFFFFFFF

    text = " ".join(rng.choice(_WORDS) for _ in range(16_000)).encode()
    compressed = zlib.compress(text, 6)

    numbers = [rng.random() for _ in range(40_000)]
    numbers.sort()

    return value ^ len(compressed) ^ int(numbers[len(numbers) // 2] * 1_000_000)


def _score(units: float, seconds: float) -> float:
    return units / seconds * SCORE_PER_UNIT_PER_S if seconds > 0 else 0.0


# multiprocessing on Windows cannot wait on more than 61 worker processes.
_MAX_WINDOWS_WORKERS = 61


def worker_count() -> int:
    count = os.cpu_count() or 1
    return min(count, _MAX_WINDOWS_WORKERS) if sys.platform == "win32" else count


# --- single core ------------------------------------------------------------------


def run_single(progress: ProgressCallback, cancel: CancelToken, sizes: CpuSizes) -> BenchmarkResult:
    work_unit(0)  # warm-up: imports, allocator, CPU leaving idle state
    round_times: list[float] = []
    for r in range(sizes.single_rounds):
        start = time.perf_counter()
        for u in range(sizes.units_per_round):
            cancel.raise_if_cancelled()
            work_unit(r * 1000 + u)
        round_times.append(time.perf_counter() - start)
        progress((r + 1) / sizes.single_rounds, "Testando processador (um núcleo)")

    median = statistics.median(round_times)
    return BenchmarkResult(
        "cpu.single",
        Category.CPU,
        SINGLE_TITLE,
        {
            "score": Metric(round(_score(sizes.units_per_round, median), 1), "pts", "Nota"),
            "median_round_s": Metric(round(median, 3), "s", "Tempo mediano por rodada"),
        },
    )


# --- multi core ---------------------------------------------------------------------


class _PoolRunner:
    """Keeps a spawn-based pool busy with work units, a bounded number in flight."""

    def __init__(self, workers: int) -> None:
        self.workers = workers
        self._done: queue.Queue[object] = queue.Queue()
        self._pool = multiprocessing.get_context("spawn").Pool(workers)
        self._submitted = 0
        self._in_flight = 0

    def __enter__(self) -> _PoolRunner:
        return self

    def __exit__(self, *exc: object) -> None:
        self._pool.terminate()
        self._pool.join()

    def _submit(self) -> None:
        self._pool.apply_async(
            work_unit,
            (self._submitted,),
            callback=self._done.put,
            error_callback=self._done.put,
        )
        self._submitted += 1
        self._in_flight += 1

    def run(
        self,
        cancel: CancelToken,
        keep_going: Callable[[int], bool],
        on_unit: Callable[[int, float], None],
    ) -> None:
        """Run units until `keep_going(submitted)` is false and all have finished.

        `submitted` counts the units of this call; `on_unit(completed, timestamp)` is
        called after each unit completes.
        """
        self._submitted = 0
        completed = 0
        for _ in range(self.workers * 2):
            if keep_going(self._submitted):
                self._submit()
        while self._in_flight:
            cancel.raise_if_cancelled()
            try:
                item = self._done.get(timeout=0.2)
            except queue.Empty:
                continue
            self._in_flight -= 1
            if isinstance(item, BaseException):
                raise RuntimeError(f"worker failed: {item}") from item
            completed += 1
            on_unit(completed, time.perf_counter())
            if keep_going(self._submitted):
                self._submit()

    def warm_up(self, cancel: CancelToken) -> None:
        """Start every worker process before anything is timed."""
        self.run(cancel, lambda submitted: submitted < self.workers, lambda *_: None)


def run_multi(
    progress: ProgressCallback,
    cancel: CancelToken,
    sizes: CpuSizes,
    single_score: float | None,
) -> BenchmarkResult:
    workers = worker_count()
    total = workers * sizes.multi_units_per_worker
    progress(0.0, "Iniciando processos de teste")
    with _PoolRunner(workers) as pool:
        pool.warm_up(cancel)
        start = time.perf_counter()
        pool.run(
            cancel,
            lambda submitted: submitted < total,
            lambda done, _: progress(done / total, "Testando processador (todos os núcleos)"),
        )
        elapsed = time.perf_counter() - start

    score = _score(total, elapsed)
    metrics = {
        "score": Metric(round(score, 1), "pts", "Nota"),
        "workers": Metric(float(workers), "processos", "Processos em paralelo"),
    }
    if single_score:
        metrics["scaling"] = Metric(
            round(score / single_score, 2), "x", "Ganho em relação a um núcleo"
        )
    return BenchmarkResult("cpu.multi", Category.CPU, MULTI_TITLE, metrics)


# --- sustained load -------------------------------------------------------------------


class _ClockSampler(threading.Thread):
    """Samples the effective CPU clock through PowerShell while the load runs."""

    def __init__(self, ps: PowerShellRunner, base_clock_mhz: float) -> None:
        super().__init__(daemon=True)
        self._ps = ps
        self._base = base_clock_mhz
        self._stop_event = threading.Event()
        self.samples: list[tuple[float, float]] = []

    def run(self) -> None:
        while not self._stop_event.is_set():
            rows = safe_query(self._ps, _CLOCK_SCRIPT, timeout=10)
            percent = _number(rows[0].get("PercentProcessorPerformance")) if rows else None
            if percent:
                self.samples.append((time.perf_counter(), percent * self._base / 100))
            self._stop_event.wait(CLOCK_SAMPLE_INTERVAL_S)

    def stop(self) -> None:
        self._stop_event.set()
        self.join(timeout=15)


def _number(value: object) -> float | None:
    try:
        return float(value)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return None


def _base_clock(ps: PowerShellRunner) -> float | None:
    rows = safe_query(ps, _BASE_CLOCK_SCRIPT, timeout=20)
    return _number(rows[0].get("MaxClockSpeed")) if rows else None


def _window_mean(values: list[float], first: bool, share: float = 0.25) -> float:
    count = max(1, round(len(values) * share))
    window = values[:count] if first else values[-count:]
    return statistics.fmean(window)


def _drop_percent(start: float, end: float) -> float:
    return round(max(0.0, (start - end) / start * 100), 1) if start > 0 else 0.0


def run_sustained(
    ps: PowerShellRunner, progress: ProgressCallback, cancel: CancelToken, sizes: CpuSizes
) -> BenchmarkResult:
    workers = worker_count()
    duration = sizes.sustained_s
    # The first and last fifth of the run are compared.
    edge = duration / 5
    base = _base_clock(ps)
    sampler = _ClockSampler(ps, base) if base else None
    stamps: list[float] = []

    def on_unit(_: int, timestamp: float) -> None:
        stamps.append(timestamp)
        progress(min((timestamp - start) / duration, 1.0), "Carga contínua no processador")

    progress(0.0, "Iniciando teste de carga contínua")
    with _PoolRunner(workers) as pool:
        pool.warm_up(cancel)
        if sampler:
            sampler.start()
        start = time.perf_counter()
        deadline = start + duration
        try:
            pool.run(cancel, lambda _: time.perf_counter() < deadline, on_unit)
        finally:
            if sampler:
                sampler.stop()

    first = sum(1 for ts in stamps if ts - start <= edge)
    last = sum(1 for ts in stamps if deadline - edge <= ts <= deadline)
    start_score, end_score = _score(first, edge), _score(last, edge)
    metrics = {
        "start_score": Metric(round(start_score, 1), "pts", "Nota no início"),
        "end_score": Metric(round(end_score, 1), "pts", "Nota no fim"),
        "throughput_drop_percent": Metric(
            _drop_percent(start_score, end_score), "%", "Queda de desempenho"
        ),
    }
    if sampler and len(sampler.samples) >= 2:
        clocks = [mhz for _, mhz in sampler.samples]
        clock_start, clock_end = _window_mean(clocks, True), _window_mean(clocks, False)
        metrics["clock_start_mhz"] = Metric(round(clock_start), "MHz", "Clock no início")
        metrics["clock_end_mhz"] = Metric(round(clock_end), "MHz", "Clock no fim")
        metrics["clock_drop_percent"] = Metric(
            _drop_percent(clock_start, clock_end), "%", "Queda de clock"
        )
    return BenchmarkResult("cpu.sustained", Category.CPU, SUSTAINED_TITLE, metrics)
