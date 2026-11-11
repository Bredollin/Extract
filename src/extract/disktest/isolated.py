"""Run the disk benchmark in a child process, so a disk that stops answering cannot freeze
the app.

A read or write stuck in the Windows kernel (failing disk, bad USB bridge or cable) cannot
be interrupted from Python, and a thread blocked there ignores the cancel flag. A child
process can be terminated: Cancel takes effect at once, and when no progress arrives for
`stall_timeout_s` the test stops with a clear error. The benchmark's test file is opened
with DELETE_ON_CLOSE on Windows, so Windows removes it with the process; leftovers from a
child killed before it opened the file are deleted here.
"""

from __future__ import annotations

import logging
import multiprocessing
import queue as queue_module
import time
from pathlib import Path
from typing import Any

from extract.benchmarks import disk as disk_bench
from extract.core.models import BenchmarkResult, from_dict, to_dict
from extract.core.progress import Cancelled, CancelToken, ProgressCallback

log = logging.getLogger(__name__)

# No progress for this long means the disk is not answering. Each progress step is a 1 MB
# sequential request or 16 random 4 KB requests, so a working disk reports within seconds.
STALL_TIMEOUT_S = 90.0
_POLL_S = 0.25
_TERMINATE_WAIT_S = 5.0


def _child(channel, target: str, sizes, folder: str, write_through: bool) -> None:
    """Child process entry point: run `target` and send progress and results back."""
    module_name, _, function_name = target.rpartition(".")
    module = __import__(module_name, fromlist=[function_name])
    function = getattr(module, function_name)
    try:
        results = function(
            lambda fraction, message: channel.put(("progress", fraction, message)),
            CancelToken(),
            sizes,
            folder,
            write_through=write_through,
        )
        channel.put(("results", [to_dict(r) for r in results]))
    except BaseException as exc:  # reported to the parent instead of a silent exit
        channel.put(("error", f"{exc.__class__.__name__}: {exc}"))


def _remove_leftovers(folder: str, since: float) -> None:
    try:
        candidates = list(Path(folder).glob("extract-bench-*.tmp"))
    except OSError:
        return
    for path in candidates:
        try:
            if path.stat().st_mtime >= since - 2:
                path.unlink()
                log.info("Removed leftover benchmark file %s", path)
        except OSError:
            log.warning("Could not remove leftover benchmark file %s", path)


def run_disk_isolated(
    progress: ProgressCallback,
    cancel: CancelToken,
    sizes: disk_bench.DiskSizes,
    folder: str,
    write_through: bool = True,
    *,
    stall_timeout_s: float = STALL_TIMEOUT_S,
    target: str = "extract.benchmarks.disk.run_disk",
) -> list[BenchmarkResult]:
    """Same contract as `benchmarks.disk.run_disk`, run in a child process."""
    context = multiprocessing.get_context("spawn")
    channel = context.Queue()
    started = time.time()
    process = context.Process(
        target=_child,
        args=(channel, target, sizes, folder, write_through),
        name="extract-disk-bench",
        daemon=True,
    )
    process.start()
    last_progress = time.monotonic()
    outcome: tuple[Any, ...] | None = None
    try:
        while outcome is None:
            if cancel.cancelled:
                raise Cancelled()
            try:
                message = channel.get(timeout=_POLL_S)
            except queue_module.Empty:
                if not process.is_alive():
                    # Give a message sent just before exiting a last chance to arrive.
                    try:
                        message = channel.get(timeout=1.0)
                    except queue_module.Empty:
                        outcome = ("error", f"o processo do teste terminou ({process.exitcode})")
                        continue
                elif time.monotonic() - last_progress > stall_timeout_s:
                    seconds = int(stall_timeout_s)
                    outcome = (
                        "error",
                        f"O disco não respondeu por {seconds} s e o teste foi interrompido. "
                        "Suspeite do disco, do cabo ou do adaptador USB.",
                    )
                    continue
                else:
                    continue
            kind = message[0]
            if kind == "progress":
                last_progress = time.monotonic()
                progress(message[1], message[2])
            else:
                outcome = message
    finally:
        if process.is_alive():
            process.terminate()
        process.join(_TERMINATE_WAIT_S)
        if process.is_alive():
            log.warning("Disk benchmark process did not exit (I/O still pending)")
        channel.close()
        _remove_leftovers(folder, started)

    if outcome[0] == "results":
        return [from_dict(BenchmarkResult, item) for item in outcome[1]]
    log.warning("Isolated disk benchmark failed: %s", outcome[1])
    text = outcome[1]
    if not text.startswith("O disco"):
        text = f"Falha no teste de velocidade: {text}"
    return disk_bench._failed(text)
