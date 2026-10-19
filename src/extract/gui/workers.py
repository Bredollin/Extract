"""Runs the scan in a worker thread and reports back through Qt signals.

The scan code is plain Python that knows nothing about Qt: its progress callback and
cancel token are bridged here, so the UI thread never blocks.
"""

from __future__ import annotations

import logging
from collections.abc import Callable
from pathlib import Path
from typing import TYPE_CHECKING

from PySide6.QtCore import QObject, QThread, Signal, Slot

from extract.core.models import MachineReport
from extract.core.progress import Cancelled, CancelToken

if TYPE_CHECKING:
    from extract.core.pipeline import ScanOptions

log = logging.getLogger(__name__)

ScanFunction = Callable[..., MachineReport]


def _pipeline_run_scan(*args, **kwargs) -> MachineReport:
    # Imported on use so the GUI starts even while a scan module fails to import.
    from extract.core.pipeline import run_scan

    return run_scan(*args, **kwargs)


class ScanWorker(QObject):
    """Runs `scan(options, progress=..., cancel=...)` and saves the report to `folder`."""

    progress = Signal(float, str)
    finished = Signal(object, object)  # MachineReport, Path of the saved JSON
    failed = Signal(str)
    cancelled = Signal()

    def __init__(
        self, options: ScanOptions, folder: Path, scan: ScanFunction | None = None
    ) -> None:
        super().__init__()
        self.options = options
        self.folder = folder
        self._scan = scan or _pipeline_run_scan
        self._token = CancelToken()

    def cancel(self) -> None:
        log.info("Cancellation requested")
        self._token.cancel()

    @property
    def is_cancelled(self) -> bool:
        return self._token.cancelled

    @Slot()
    def run(self) -> None:
        try:
            report = self._scan(self.options, progress=self._report_progress, cancel=self._token)
            self._token.raise_if_cancelled()
            from extract.reports import save_report

            path = save_report(report, self.folder)
        except Cancelled:
            log.info("Scan cancelled")
            self.cancelled.emit()
        except Exception as exc:
            log.exception("Scan failed")
            self.failed.emit(str(exc) or exc.__class__.__name__)
        else:
            self.finished.emit(report, path)

    def _report_progress(self, fraction: float, message: str) -> None:
        self.progress.emit(fraction, message)


def start_in_thread(worker: ScanWorker) -> QThread:
    """Move `worker` to a new thread and start it; the thread quits when the worker ends.

    The caller keeps both objects referenced until the thread has finished.
    """
    thread = QThread()
    worker.moveToThread(thread)
    thread.started.connect(worker.run)
    for signal in (worker.finished, worker.failed, worker.cancelled):
        signal.connect(thread.quit)
    thread.start()
    return thread
