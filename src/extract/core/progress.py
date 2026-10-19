"""Progress reporting and cancellation for long-running work (scans and benchmarks)."""

from __future__ import annotations

import threading
from typing import Protocol


class ProgressCallback(Protocol):
    def __call__(self, fraction: float, message: str) -> None:
        """`fraction` goes from 0.0 to 1.0; `message` describes the current step."""
        ...


def no_progress(fraction: float, message: str) -> None:
    """Default callback when nobody is watching."""


class Cancelled(Exception):
    """Raised when the user cancels a running task."""


class CancelToken:
    """Cancellation flag shared between the GUI and the running task."""

    def __init__(self) -> None:
        self._event = threading.Event()

    def cancel(self) -> None:
        self._event.set()

    @property
    def cancelled(self) -> bool:
        return self._event.is_set()

    def raise_if_cancelled(self) -> None:
        if self._event.is_set():
            raise Cancelled()


def sub_progress(progress: ProgressCallback, start: float, end: float) -> ProgressCallback:
    """Map a step's 0..1 progress onto the [start, end] slice of the overall progress."""

    def report(fraction: float, message: str) -> None:
        fraction = min(max(fraction, 0.0), 1.0)
        progress(start + (end - start) * fraction, message)

    return report
