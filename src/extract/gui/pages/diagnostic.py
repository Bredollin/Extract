"""Diagnóstico page: choose what to run, start the scan and follow it live."""

from __future__ import annotations

import logging
from pathlib import Path

from PySide6.QtCore import QThread, Signal
from PySide6.QtWidgets import QWidget

from extract.core.models import Category, MachineReport
from extract.gui.pages.scan_progress import ScanProgressCard
from extract.gui.pages.scan_setup import ScanSetupCard
from extract.gui.theme import Space
from extract.gui.widgets.common import hbox, vbox
from extract.gui.widgets.log_panel import QtLogHandler
from extract.gui.widgets.page_header import PageHeader
from extract.gui.workers import ScanFunction, ScanWorker, start_in_thread

log = logging.getLogger(__name__)
SETUP_WIDTH = 400


class DiagnosticPage(QWidget):
    report_ready = Signal(object, object)  # MachineReport, Path
    running_changed = Signal(bool)

    def __init__(self, log_handler: QtLogHandler, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("Page")
        self.scan_function: ScanFunction | None = None
        self._worker: ScanWorker | None = None
        self._thread: QThread | None = None

        column = vbox(Space.XL, (Space.XXL, Space.XL + 4, Space.XXL, Space.XL))
        column.addWidget(
            PageHeader(
                "Diagnóstico",
                "Inventário, saúde e desempenho da máquina, com a causa provável da lentidão.",
            )
        )
        row = hbox(Space.XL)
        self.setup = ScanSetupCard()
        self.setup.setFixedWidth(SETUP_WIDTH)
        self.setup.start_requested.connect(self.start_scan)
        row.addWidget(self.setup)
        self.progress = ScanProgressCard()
        self.progress.cancel_requested.connect(self.cancel_scan)
        row.addWidget(self.progress, 1)
        column.addLayout(row, 1)
        self.setLayout(column)

        log_handler.emitter.message.connect(self.progress.log.append)
        for toggle in (
            self.setup.health,
            self.setup.benchmarks,
            *self.setup.bench_toggles.values(),
        ):
            toggle.toggled.connect(self._preview_steps)

    @property
    def is_running(self) -> bool:
        return self._thread is not None and self._thread.isRunning()

    def _preview_steps(self) -> None:
        if not self.is_running:
            self.progress.reset(self.setup.health.isChecked(), self.setup.benchmark_categories)

    def start_scan(self) -> None:
        if self.is_running:
            return
        options = self.setup.build_options()
        folder = self.setup.folder
        self.setup.remember_client()
        log.info("Starting scan for client %r into %s", options.client, folder)
        self.setup.set_running(True)
        self.progress.start(options.health, set(options.benchmarks))
        self._worker = ScanWorker(options, folder, self.scan_function)
        self._worker.progress.connect(self._on_progress)
        self._worker.finished.connect(self._on_finished)
        self._worker.failed.connect(self._on_failed)
        self._worker.cancelled.connect(self._on_cancelled)
        self._thread = start_in_thread(self._worker)
        self.running_changed.emit(True)

    def cancel_scan(self) -> None:
        if self._worker is not None:
            self._worker.cancel()

    def wait_for_scan(self, timeout_ms: int = 30000) -> bool:
        """Block until the worker thread ends (used when closing the window)."""
        return self._thread.wait(timeout_ms) if self._thread is not None else True

    def _on_progress(self, fraction: float, message: str) -> None:
        self.progress.update_progress(fraction, message)
        if fraction >= 1.0:
            self.progress.mark_saving()

    def _on_finished(self, report: MachineReport, path: Path) -> None:
        self.progress.finish(f"Concluído. Relatório salvo em {path.name}")
        self._done()
        self.setup.refresh_clients()
        self.report_ready.emit(report, path)

    def _on_failed(self, message: str) -> None:
        self.progress.fail(f"O diagnóstico falhou: {message}")
        self._done()

    def _on_cancelled(self) -> None:
        self.progress.fail("Diagnóstico cancelado pelo usuário", cancelled=True)
        self._done()

    def _done(self) -> None:
        self.setup.set_running(False)
        self.running_changed.emit(False)

    def show_preview(self, fraction: float, message: str, elapsed_s: float, log_lines: list[str]):
        """Freeze the page in a mid-scan look (for `--demo` screenshots); nothing runs."""
        categories = {Category.CPU, Category.MEMORY, Category.STORAGE}
        self.setup.set_running(True)
        self.progress.start(True, categories)
        self.progress.update_progress(fraction, message)
        self.progress.show_elapsed(elapsed_s)
        for line in log_lines:
            self.progress.log.append(line)
        self.progress.log.set_expanded(True)
