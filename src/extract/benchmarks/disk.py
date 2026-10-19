"""Disk benchmarks on the system volume: sequential throughput and random 4 KiB I/O.

The test file lives in the user's temp folder (on the system volume) and is always deleted,
even when the test fails or is cancelled. On Windows it is opened with
`FILE_FLAG_NO_BUFFERING | FILE_FLAG_WRITE_THROUGH`, so neither the read nor the write
numbers come from the Windows file cache; that requires sector-aligned buffers, offsets and
sizes, which `mmap` (page-aligned) and 4 KiB multiples give us. Elsewhere it falls back to
buffered I/O with `fsync`, and the results are marked as possibly cached (`uncached = 0`).

Random I/O is measured at queue depth 1 (one request at a time), which is what makes an
everyday desktop feel fast or slow and is where HDDs and SSDs differ the most.
"""

from __future__ import annotations

import ctypes
import logging
import mmap
import os
import random
import shutil
import sys
import tempfile
import time
from dataclasses import dataclass
from typing import Protocol

from extract.core.models import BenchmarkResult, Category, Metric
from extract.core.progress import CancelToken, ProgressCallback

log = logging.getLogger(__name__)

SEQUENTIAL_TITLE = "Disco: leitura e gravação sequencial"
RANDOM_TITLE = "Disco: acesso aleatório 4 KB"

MIB = 2**20
BLOCK = 4096  # random I/O size; also a multiple of every common sector size (512, 4096)
CHUNK = 1 * MIB  # sequential I/O size
FREE_SPACE_RESERVE_MB = 1024  # never leave the volume with less than this free
MIN_FILE_MB = 64


@dataclass(frozen=True)
class DiskSizes:
    file_mb: int
    sequential_max_s: float  # per direction; stops early on very slow disks
    random_s: float  # per direction


FULL = DiskSizes(file_mb=1024, sequential_max_s=20.0, random_s=8.0)
QUICK = DiskSizes(file_mb=128, sequential_max_s=8.0, random_s=2.5)


class _TestFile(Protocol):
    uncached: bool

    def write_at(self, offset: int, buffer: _AlignedBuffer, length: int) -> None: ...

    def read_at(self, offset: int, buffer: _AlignedBuffer, length: int) -> None: ...

    def sync(self) -> None: ...

    def drop_cache(self) -> None: ...

    def close(self) -> None: ...


class _AlignedBuffer:
    """Page-aligned memory (anonymous mmap) usable from both ctypes and Python."""

    def __init__(self, size: int) -> None:
        self._map = mmap.mmap(-1, size)
        self._map.write(os.urandom(size))  # incompressible, so SSD compression cannot cheat
        self._c_buffer = (ctypes.c_char * size).from_buffer(self._map)
        self.address = ctypes.addressof(self._c_buffer)
        self.view = memoryview(self._map)

    def close(self) -> None:
        self.view.release()
        del self._c_buffer
        self._map.close()


class _PosixFile:
    """Fallback for non-Windows systems: buffered I/O plus fsync (results may be cached)."""

    uncached = False

    def __init__(self, path: str) -> None:
        self._fd = os.open(path, os.O_RDWR | os.O_CREAT | os.O_TRUNC | getattr(os, "O_BINARY", 0))

    def write_at(self, offset: int, buffer: _AlignedBuffer, length: int) -> None:
        os.pwrite(self._fd, buffer.view[:length], offset)

    def read_at(self, offset: int, buffer: _AlignedBuffer, length: int) -> None:
        os.preadv(self._fd, [buffer.view[:length]], offset)

    def sync(self) -> None:
        os.fsync(self._fd)

    def drop_cache(self) -> None:
        # Best effort: ask the kernel to forget the cached pages of the file.
        if hasattr(os, "posix_fadvise"):
            os.posix_fadvise(self._fd, 0, 0, os.POSIX_FADV_DONTNEED)

    def close(self) -> None:
        os.close(self._fd)


class _Overlapped(ctypes.Structure):
    _fields_ = [
        ("Internal", ctypes.c_void_p),
        ("InternalHigh", ctypes.c_void_p),
        ("Offset", ctypes.c_uint32),
        ("OffsetHigh", ctypes.c_uint32),
        ("hEvent", ctypes.c_void_p),
    ]


class _Win32File:
    """Unbuffered, write-through file through the Win32 API (bypasses the file cache)."""

    uncached = True

    _GENERIC_READ = 0x80000000
    _GENERIC_WRITE = 0x40000000
    _CREATE_ALWAYS = 2
    _FILE_FLAG_NO_BUFFERING = 0x20000000
    _FILE_FLAG_WRITE_THROUGH = 0x80000000
    _FILE_FLAG_DELETE_ON_CLOSE = 0x04000000
    _INVALID_HANDLE = ctypes.c_void_p(-1).value

    def __init__(self, path: str) -> None:
        from ctypes import wintypes

        k32 = ctypes.WinDLL("kernel32", use_last_error=True)  # type: ignore[attr-defined]
        k32.CreateFileW.argtypes = [
            wintypes.LPCWSTR,
            wintypes.DWORD,
            wintypes.DWORD,
            ctypes.c_void_p,
            wintypes.DWORD,
            wintypes.DWORD,
            wintypes.HANDLE,
        ]
        k32.CreateFileW.restype = wintypes.HANDLE
        io_args = [
            wintypes.HANDLE,
            ctypes.c_void_p,
            wintypes.DWORD,
            ctypes.POINTER(wintypes.DWORD),
            ctypes.POINTER(_Overlapped),
        ]
        k32.ReadFile.argtypes = io_args
        k32.WriteFile.argtypes = io_args
        k32.ReadFile.restype = k32.WriteFile.restype = wintypes.BOOL
        k32.FlushFileBuffers.argtypes = [wintypes.HANDLE]
        k32.CloseHandle.argtypes = [wintypes.HANDLE]
        self._k32 = k32
        self._dword = wintypes.DWORD
        # No FILE_ATTRIBUTE_TEMPORARY: it asks Windows to keep the data in memory, the
        # opposite of what a disk test needs. DELETE_ON_CLOSE makes Windows remove the file
        # even if the process is killed, so a client's disk never keeps a stray 1 GB file.
        handle = k32.CreateFileW(
            path,
            self._GENERIC_READ | self._GENERIC_WRITE,
            0,
            None,
            self._CREATE_ALWAYS,
            self._FILE_FLAG_NO_BUFFERING
            | self._FILE_FLAG_WRITE_THROUGH
            | self._FILE_FLAG_DELETE_ON_CLOSE,
            None,
        )
        if not handle or handle == self._INVALID_HANDLE:
            raise ctypes.WinError(ctypes.get_last_error())  # type: ignore[attr-defined]
        self._handle = handle

    def _io(self, func, offset: int, buffer: _AlignedBuffer, length: int) -> None:
        overlapped = _Overlapped(Offset=offset & 0xFFFFFFFF, OffsetHigh=offset >> 32)
        transferred = self._dword(0)
        ok = func(
            self._handle,
            buffer.address,
            length,
            ctypes.byref(transferred),
            ctypes.byref(overlapped),
        )
        if not ok or transferred.value != length:
            raise ctypes.WinError(ctypes.get_last_error())  # type: ignore[attr-defined]

    def write_at(self, offset: int, buffer: _AlignedBuffer, length: int) -> None:
        self._io(self._k32.WriteFile, offset, buffer, length)

    def read_at(self, offset: int, buffer: _AlignedBuffer, length: int) -> None:
        self._io(self._k32.ReadFile, offset, buffer, length)

    def sync(self) -> None:
        self._k32.FlushFileBuffers(self._handle)

    def drop_cache(self) -> None:
        """Nothing to drop: the handle never goes through the cache."""

    def close(self) -> None:
        self._k32.CloseHandle(self._handle)


def _open_test_file(path: str) -> _TestFile:
    return _Win32File(path) if sys.platform == "win32" else _PosixFile(path)


def choose_file_mb(target_mb: int, free_mb: float) -> int:
    """Shrink the test file to fit the free space; 0 means there is not enough room."""
    size = min(target_mb, int(free_mb - FREE_SPACE_RESERVE_MB))
    return size if size >= MIN_FILE_MB else 0


@dataclass
class _Measurements:
    write_mb_s: float = 0.0
    read_mb_s: float = 0.0
    file_mb: float = 0.0
    read_iops: float = 0.0
    write_iops: float = 0.0
    read_latency_ms: float = 0.0
    write_latency_ms: float = 0.0


class _DiskTest:
    """Runs the four disk phases on one open test file."""

    def __init__(
        self,
        file: _TestFile,
        size: int,
        sizes: DiskSizes,
        progress: ProgressCallback,
        cancel: CancelToken,
    ) -> None:
        self.file = file
        self.size = size
        self.sizes = sizes
        self.progress = progress
        self.cancel = cancel

    def _report(self, phase: int, fraction: float, message: str) -> None:
        self.progress((phase + min(fraction, 1.0)) / 4, message)

    def sequential_write(self, buffer: _AlignedBuffer) -> tuple[int, float]:
        """Returns (bytes written, MB/s)."""
        offset = 0
        start = time.perf_counter()
        deadline = start + self.sizes.sequential_max_s
        while offset < self.size and time.perf_counter() < deadline:
            self.cancel.raise_if_cancelled()
            self.file.write_at(offset, buffer, CHUNK)
            offset += CHUNK
            self._report(0, offset / self.size, "Disco: gravação sequencial")
        self.file.sync()
        return offset, offset / MIB / (time.perf_counter() - start)

    def sequential_read(self, buffer: _AlignedBuffer, written: int) -> float:
        self.file.drop_cache()
        offset = 0
        start = time.perf_counter()
        deadline = start + self.sizes.sequential_max_s
        while offset < written and time.perf_counter() < deadline:
            self.cancel.raise_if_cancelled()
            self.file.read_at(offset, buffer, CHUNK)
            offset += CHUNK
            self._report(1, offset / written, "Disco: leitura sequencial")
        return offset / MIB / (time.perf_counter() - start)

    def random_io(self, buffer: _AlignedBuffer, written: int, write: bool) -> tuple[float, float]:
        """Queue-depth-1 4 KiB random I/O for a fixed time. Returns (IOPS, average ms)."""
        if write:
            phase, message, operation = 3, "Disco: gravação aleatória", self.file.write_at
            # The unbuffered Windows handle already writes through; elsewhere each write is
            # synced so it reaches the disk like it would there.
            sync = None if self.file.uncached else self.file.sync
        else:
            phase, message, operation = 2, "Disco: leitura aleatória", self.file.read_at
            sync = None
            self.file.drop_cache()
        rng = random.Random(4096)
        blocks = written // BLOCK
        duration = self.sizes.random_s
        ops = 0
        start = time.perf_counter()
        elapsed = 0.0
        while elapsed < duration:
            # Checking the clock and the cancel flag every few requests keeps their cost
            # out of the measurement.
            for _ in range(16):
                operation(rng.randrange(blocks) * BLOCK, buffer, BLOCK)
                if sync:
                    sync()
            ops += 16
            self.cancel.raise_if_cancelled()
            elapsed = time.perf_counter() - start
            self._report(phase, elapsed / duration, message)
        return ops / elapsed, elapsed / ops * 1000

    def run(self) -> _Measurements:
        result = _Measurements()
        buffer = _AlignedBuffer(CHUNK)
        try:
            written, result.write_mb_s = self.sequential_write(buffer)
            result.file_mb = written / MIB
            result.read_mb_s = self.sequential_read(buffer, written)
            result.read_iops, result.read_latency_ms = self.random_io(buffer, written, False)
            result.write_iops, result.write_latency_ms = self.random_io(buffer, written, True)
        finally:
            buffer.close()
        return result


def _remove(path: str) -> None:
    try:
        os.remove(path)
    except FileNotFoundError:
        pass
    except OSError:
        log.exception("Could not delete benchmark file %s", path)


def _results(m: _Measurements, uncached: bool) -> list[BenchmarkResult]:
    suffix = "" if uncached else " (com cache do sistema)"
    flag = Metric(1.0 if uncached else 0.0, "", "Sem cache do sistema (1 = sim)")
    sequential = BenchmarkResult(
        "storage.sequential",
        Category.STORAGE,
        SEQUENTIAL_TITLE,
        {
            "write_mb_s": Metric(round(m.write_mb_s, 1), "MB/s", f"Gravação sequencial{suffix}"),
            "read_mb_s": Metric(round(m.read_mb_s, 1), "MB/s", f"Leitura sequencial{suffix}"),
            "file_mb": Metric(round(m.file_mb), "MB", "Tamanho do arquivo de teste"),
            "uncached": flag,
        },
    )
    random_result = BenchmarkResult(
        "storage.random",
        Category.STORAGE,
        RANDOM_TITLE,
        {
            "read_iops": Metric(round(m.read_iops), "IOPS", f"Leitura aleatória{suffix}"),
            "write_iops": Metric(round(m.write_iops), "IOPS", f"Gravação aleatória{suffix}"),
            "read_latency_ms": Metric(round(m.read_latency_ms, 3), "ms", "Tempo médio de leitura"),
            "write_latency_ms": Metric(
                round(m.write_latency_ms, 3), "ms", "Tempo médio de gravação"
            ),
            "uncached": flag,
        },
    )
    return [sequential, random_result]


def _failed(message: str) -> list[BenchmarkResult]:
    return [
        BenchmarkResult(
            "storage.sequential",
            Category.STORAGE,
            SEQUENTIAL_TITLE,
            error=message,
        ),
        BenchmarkResult("storage.random", Category.STORAGE, RANDOM_TITLE, error=message),
    ]


def run_disk(
    progress: ProgressCallback, cancel: CancelToken, sizes: DiskSizes
) -> list[BenchmarkResult]:
    """Run both disk benchmarks; returns [storage.sequential, storage.random]."""
    folder = tempfile.gettempdir()
    free_mb = shutil.disk_usage(folder).free / MIB
    file_mb = choose_file_mb(sizes.file_mb, free_mb)
    if not file_mb:
        return _failed(
            f"Espaço livre insuficiente no disco do sistema para o teste ({free_mb:.0f} MB livres)."
        )

    fd, path = tempfile.mkstemp(prefix="extract-bench-", suffix=".tmp", dir=folder)
    os.close(fd)
    try:
        file = _open_test_file(path)
        try:
            measurements = _DiskTest(file, file_mb * MIB, sizes, progress, cancel).run()
        finally:
            file.close()
        return _results(measurements, file.uncached)
    except OSError as exc:
        log.warning("Disk benchmark failed: %s", exc)
        return _failed(f"Falha ao acessar o arquivo de teste: {exc.strerror or exc}")
    finally:
        _remove(path)
