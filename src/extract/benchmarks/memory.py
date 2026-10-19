"""Memory bandwidth: large buffer writes, reads and copies.

Each operation is a single C-level pass over a large buffer (`memset`, a `memchr` scan that
never matches, and a slice copy that becomes `memcpy`), so Python overhead is negligible and
the number tracks the memory subsystem: channel count, module speed and CPU memory
controller. It is single-threaded, so it reflects what one application sees, not the peak
the platform could reach with every core.
"""

from __future__ import annotations

import ctypes
import logging
import os
import sys
import time
from collections.abc import Callable

from extract.core.models import BenchmarkResult, Category, Metric
from extract.core.progress import CancelToken, ProgressCallback

log = logging.getLogger(__name__)

TITLE = "Memória: largura de banda"
FULL_BUFFER_MB = 256
QUICK_BUFFER_MB = 64
MIN_BUFFER_MB = 16
ROUNDS = 3
# Never take more than this share of the available memory (two buffers are allocated).
MAX_SHARE_OF_AVAILABLE = 0.25


class _MemoryStatusEx(ctypes.Structure):
    _fields_ = [
        ("dwLength", ctypes.c_ulong),
        ("dwMemoryLoad", ctypes.c_ulong),
        ("ullTotalPhys", ctypes.c_ulonglong),
        ("ullAvailPhys", ctypes.c_ulonglong),
        ("ullTotalPageFile", ctypes.c_ulonglong),
        ("ullAvailPageFile", ctypes.c_ulonglong),
        ("ullTotalVirtual", ctypes.c_ulonglong),
        ("ullAvailVirtual", ctypes.c_ulonglong),
        ("ullAvailExtendedVirtual", ctypes.c_ulonglong),
    ]


def available_memory_mb() -> float | None:
    """Physical memory currently available to applications, or None if unknown."""
    try:
        if sys.platform == "win32":
            status = _MemoryStatusEx()
            status.dwLength = ctypes.sizeof(_MemoryStatusEx)
            if ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(status)):
                return status.ullAvailPhys / 2**20
            return None
        with open("/proc/meminfo", encoding="ascii") as meminfo:
            for line in meminfo:
                if line.startswith("MemAvailable:"):
                    return int(line.split()[1]) / 1024
        pages = os.sysconf("SC_AVPHYS_PAGES") * os.sysconf("SC_PAGE_SIZE")
        return pages / 2**20
    except (OSError, ValueError, AttributeError):
        log.warning("Could not read available memory", exc_info=True)
        return None


def choose_buffer_mb(target_mb: int, available_mb: float | None) -> int:
    """Shrink the buffer when memory is tight; 0 means there is not enough to test."""
    if available_mb is None:
        return target_mb
    limit = int(available_mb * MAX_SHARE_OF_AVAILABLE / 2)
    size = min(target_mb, limit)
    return size if size >= MIN_BUFFER_MB else 0


def _best_rate(
    op: Callable[[], object], size_bytes: int, cancel: CancelToken, step: Callable[[], None]
) -> float:
    """Best of `ROUNDS` runs in GB/s; best-of filters out interruptions by other tasks."""
    best = float("inf")
    for _ in range(ROUNDS):
        cancel.raise_if_cancelled()
        start = time.perf_counter()
        op()
        best = min(best, time.perf_counter() - start)
        step()
    return size_bytes / best / 1e9


def run_bandwidth(progress: ProgressCallback, cancel: CancelToken, quick: bool) -> BenchmarkResult:
    target = QUICK_BUFFER_MB if quick else FULL_BUFFER_MB
    available = available_memory_mb()
    size_mb = choose_buffer_mb(target, available)
    if not size_mb:
        return BenchmarkResult(
            "memory.bandwidth",
            Category.MEMORY,
            TITLE,
            error=f"Memória livre insuficiente para o teste ({available or 0:.0f} MB disponíveis).",
        )

    size = size_mb * 2**20
    progress(0.0, "Reservando memória para o teste")
    src = bytearray(size)
    dst = bytearray(size)
    src_view, dst_view = memoryview(src), memoryview(dst)
    dst_address = ctypes.addressof(ctypes.c_char.from_buffer(dst))
    # A fresh zeroed buffer may be backed by one shared zero page; touch every page so the
    # read pass really goes to memory.
    ctypes.memset(ctypes.addressof(ctypes.c_char.from_buffer(src)), 0, size)
    total_steps = ROUNDS * 3
    done = 0

    def step() -> None:
        nonlocal done
        done += 1
        progress(done / total_steps, "Testando memória")

    try:
        # Writing first also commits every page, so later passes do not pay page faults.
        write = _best_rate(lambda: ctypes.memset(dst_address, 0x5A, size), size, cancel, step)
        read = _best_rate(lambda: src.find(b"\x01"), size, cancel, step)
        copy = _best_rate(lambda: dst_view.__setitem__(slice(None), src_view), size, cancel, step)
    finally:
        src_view.release()
        dst_view.release()

    return BenchmarkResult(
        "memory.bandwidth",
        Category.MEMORY,
        TITLE,
        {
            "read_gb_s": Metric(round(read, 2), "GB/s", "Leitura"),
            "write_gb_s": Metric(round(write, 2), "GB/s", "Escrita"),
            "copy_gb_s": Metric(round(copy, 2), "GB/s", "Cópia"),
            "buffer_mb": Metric(float(size_mb), "MB", "Tamanho do bloco testado"),
        },
    )
