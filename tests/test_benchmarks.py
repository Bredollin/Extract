from __future__ import annotations

import sys
import tempfile
from collections import namedtuple

import pytest

from extract.benchmarks import cpu, disk, memory, run_benchmarks
from extract.core.models import Category
from extract.core.powershell import FakePowerShell
from extract.core.progress import Cancelled, CancelToken

ALL = {Category.CPU, Category.MEMORY, Category.STORAGE}


@pytest.fixture(autouse=True)
def tiny_sizes(monkeypatch, tmp_path):
    """Shrink every workload so the suite stays fast, and isolate the temp folder."""
    monkeypatch.setattr(cpu, "QUICK", cpu.CpuSizes(2, 3, 2, 1.5))
    monkeypatch.setattr(memory, "QUICK_BUFFER_MB", 16)
    monkeypatch.setattr(disk, "QUICK", disk.DiskSizes(file_mb=8, sequential_max_s=2, random_s=0.3))
    monkeypatch.setattr(disk, "MIN_FILE_MB", 4)
    monkeypatch.setattr(tempfile, "tempdir", str(tmp_path))


@pytest.fixture
def clock_ps():
    return FakePowerShell(
        {
            "MaxClockSpeed": [{"MaxClockSpeed": 2800}],
            "ProcessorInformation": [{"PercentProcessorPerformance": 110}],
        }
    )


def _leftover_files(tmp_path):
    return list(tmp_path.glob("extract-bench-*"))


def test_run_benchmarks_quick_returns_sane_metrics(clock_ps, tmp_path):
    seen: list[float] = []
    results = run_benchmarks(ALL, clock_ps, lambda f, m: seen.append(f), quick=True)

    by_id = {r.id: r for r in results}
    assert list(by_id) == [
        "cpu.single",
        "cpu.multi",
        "cpu.sustained",
        "memory.bandwidth",
        "storage.sequential",
        "storage.random",
    ]
    for result in results:
        assert result.ok, result.error
        assert result.title and result.duration_s >= 0
        for key, metric in result.metrics.items():
            assert metric.label and metric.value >= 0, key
    assert by_id["cpu.single"].metrics["score"].value > 0
    assert by_id["cpu.multi"].metrics["scaling"].value > 0
    assert by_id["memory.bandwidth"].metrics["copy_gb_s"].value > 0
    assert by_id["storage.sequential"].metrics["write_mb_s"].value > 0
    assert by_id["storage.random"].metrics["read_iops"].value > 0
    # Windows bypasses the file cache; elsewhere the buffered fallback must say so.
    expected_uncached = 1 if sys.platform == "win32" else 0
    assert by_id["storage.random"].metrics["uncached"].value == expected_uncached
    assert seen == sorted(seen) and seen[-1] == 1.0
    assert _leftover_files(tmp_path) == []


def test_sustained_reports_clock_when_available(clock_ps, monkeypatch):
    monkeypatch.setattr(cpu, "CLOCK_SAMPLE_INTERVAL_S", 0.1)
    result = cpu.run_sustained(clock_ps, lambda f, m: None, CancelToken(), cpu.QUICK)
    assert result.metrics["clock_start_mhz"].value == 3080
    assert result.metrics["clock_drop_percent"].value == 0
    assert result.metrics["start_score"].value > 0


def test_sustained_without_clock_still_measures_throughput():
    result = cpu.run_sustained(FakePowerShell({}), lambda f, m: None, CancelToken(), cpu.QUICK)
    assert "clock_drop_percent" not in result.metrics
    assert "throughput_drop_percent" in result.metrics


def test_only_requested_categories_run():
    results = run_benchmarks({Category.MEMORY}, FakePowerShell({}), quick=True)
    assert [r.id for r in results] == ["memory.bandwidth"]


def test_cancel_stops_cpu_multi():
    token = CancelToken()
    token.cancel()
    with pytest.raises(Cancelled):
        cpu.run_multi(lambda f, m: None, token, cpu.QUICK, None)


def test_cancel_during_disk_test_deletes_file(tmp_path):
    token = CancelToken()
    seen_file = []

    def progress(fraction, message):
        seen_file.extend(_leftover_files(tmp_path))
        if fraction > 0.3:
            token.cancel()

    with pytest.raises(Cancelled):
        disk.run_disk(progress, token, disk.QUICK)
    assert seen_file, "the test file should exist while the test runs"
    assert _leftover_files(tmp_path) == []


def test_disk_skips_when_free_space_is_too_low(monkeypatch, tmp_path):
    usage = namedtuple("usage", "total used free")
    monkeypatch.setattr(disk.shutil, "disk_usage", lambda _: usage(10, 9, 500 * disk.MIB))
    results = disk.run_disk(lambda f, m: None, CancelToken(), disk.QUICK)
    assert [r.id for r in results] == ["storage.sequential", "storage.random"]
    assert all("Espaço livre insuficiente" in r.error for r in results)
    assert _leftover_files(tmp_path) == []


def test_failing_benchmark_is_reported_and_others_continue(monkeypatch):
    def broken(*args):
        raise RuntimeError("sem memória")

    monkeypatch.setattr(memory, "run_bandwidth", broken)
    results = run_benchmarks({Category.MEMORY, Category.STORAGE}, FakePowerShell({}), quick=True)
    by_id = {r.id: r for r in results}
    assert "sem memória" in by_id["memory.bandwidth"].error
    assert by_id["storage.sequential"].ok


@pytest.mark.parametrize(
    ("target", "available", "expected"),
    [(256, None, 256), (256, 16_000, 256), (256, 1_000, 125), (256, 100, 0)],
)
def test_choose_buffer_mb(target, available, expected):
    assert memory.choose_buffer_mb(target, available) == expected


@pytest.mark.parametrize(
    ("target", "free", "expected"), [(1024, 50_000, 1024), (1024, 1_500, 476), (1024, 1_050, 0)]
)
def test_choose_file_mb(target, free, expected, monkeypatch):
    monkeypatch.setattr(disk, "MIN_FILE_MB", 64)
    assert disk.choose_file_mb(target, free) == expected


def test_work_unit_is_deterministic():
    assert cpu.work_unit(7) == cpu.work_unit(7)
    assert cpu.work_unit(7) != cpu.work_unit(8)


@pytest.mark.windows
def test_disk_bypasses_cache_on_windows():
    results = disk.run_disk(lambda f, m: None, CancelToken(), disk.QUICK)
    assert all(r.ok and r.metrics["uncached"].value == 1 for r in results)
