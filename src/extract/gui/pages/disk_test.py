"""Teste de disco page: pick a physical drive, read its health (SMART), measure its speed
and get a 0-100 score with a verdict and recommendations. Results can be saved as PDF.
"""

from __future__ import annotations

import logging
import time
from collections.abc import Callable
from pathlib import Path

from PySide6.QtCore import QThread, QTimer, QUrl, Signal
from PySide6.QtGui import QDesktopServices
from PySide6.QtWidgets import (
    QComboBox,
    QGridLayout,
    QMessageBox,
    QProgressBar,
    QTabWidget,
    QWidget,
)

from extract.core.models import Status
from extract.core.powershell import PowerShell, PowerShellRunner
from extract.disktest import DiskTestMode, DiskTestReport, DriveEntry, list_drives, run_disk_test
from extract.disktest import report as disk_report
from extract.disktest import summary as disk_summary
from extract.gui import formatting, settings
from extract.gui.pages.disk_test_progress import DiskTestProgress
from extract.gui.theme import STATUS_TONES, Space
from extract.gui.widgets.card import Card
from extract.gui.widgets.common import (
    ElidedLabel,
    button,
    divider,
    hbox,
    label,
    scroll_area,
    vbox,
)
from extract.gui.widgets.empty_state import EmptyState
from extract.gui.widgets.metric_bar import MetricBar
from extract.gui.widgets.page_header import PageHeader
from extract.gui.widgets.stat_card import StatCard
from extract.gui.widgets.status_chip import StatusChip
from extract.gui.workers import TaskWorker, start_in_thread

log = logging.getLogger(__name__)

SETUP_WIDTH = 360
MODES = (DiskTestMode.QUICK, DiskTestMode.FULL, DiskTestMode.HEALTH)
MODE_HINTS = {
    DiskTestMode.HEALTH: "Só leitura: nada é gravado no disco.",
    DiskTestMode.QUICK: "Grava um arquivo temporário de 128 MB (apagado no fim). Cerca de 30 s.",
    DiskTestMode.FULL: "Grava um arquivo temporário de 1 GB (apagado no fim). Cerca de 1 min.",
}
START_TEXT = "Testar disco"
# Seconds without progress before the page says the disk is not answering. A single
# request can block that long on a failing disk or a USB bridge; it cannot be interrupted,
# so the page explains the wait instead of looking frozen.
STALL_WARNING_S = 15
WINDOWS_HEALTH = {"Healthy": "saudável", "Warning": "em alerta", "Unhealthy": "com falha"}
# (metric key, typical-value attribute of DiskExpectation, factor) for the bars.
BAR_REFERENCES = {
    "read_mb_s": ("typical_seq_read_mb_s", 1.0),
    "write_mb_s": ("typical_seq_read_mb_s", 0.8),
    "read_iops": ("typical_random_read_iops", 1.0),
    "write_iops": ("typical_random_read_iops", 1.0),
}

FACT_ICONS = {
    "Saúde": "heart-pulse",
    "Vida útil": "gauge",
    "Tempo ligado": "clock",
    "Temperatura": "activity",
}
RESULT_TABS = ("Resumo", "Detalhes")


def _status_tone(status: Status) -> str:
    return STATUS_TONES.get(status, "neutral")


def _score_tone(score: int | None) -> str:
    if score is None:
        return "text_muted"
    if score >= 80:
        return "ok"
    if score >= 50:
        return "warning"
    return "critical"


class DiskTestPage(QWidget):
    running_changed = Signal(bool)

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("Page")
        # Swapped in tests and demos; the real one starts powershell.exe.
        self.ps_factory: Callable[[], PowerShellRunner] = PowerShell
        self.drives: list[DriveEntry] = []
        self.report: DiskTestReport | None = None
        self.saved_pdf: Path | None = None
        self._worker: TaskWorker | None = None
        self._thread: QThread | None = None
        self._loaded = False
        self._busy = False
        self._last_progress = 0.0
        self._last_message = ""
        self._watchdog = QTimer(self)
        self._watchdog.setInterval(1000)
        self._watchdog.timeout.connect(self._check_stall)
        self._started = 0.0
        self.live: DiskTestProgress | None = None

        column = vbox(Space.XL, (Space.XXL, Space.XL + 4, Space.XXL, Space.XL))
        column.addWidget(
            PageHeader(
                "Teste de disco",
                "Saúde (SMART), velocidade e veredito de SSD e HD, um disco por vez.",
            )
        )
        row = hbox(Space.XL)
        row.addWidget(self._build_setup())
        self.results_holder = vbox()
        row.addLayout(self.results_holder, 1)
        column.addLayout(row, 1)
        self.setLayout(column)
        self._results_widget: QWidget | None = None
        self._show_widget(
            EmptyState(
                "disk",
                "Nenhum disco testado",
                "Escolha o disco à esquerda e clique em Testar disco.",
            )
        )

    # --- Setup card -------------------------------------------------------------------

    def _build_setup(self) -> Card:
        card = Card("Configuração")
        card.setFixedWidth(SETUP_WIDTH)
        card.body.addWidget(label("Disco", role="strong"))
        drive_row = hbox(Space.S)
        self.drive_combo = QComboBox()
        self.drive_combo.currentIndexChanged.connect(self._on_drive_changed)
        drive_row.addWidget(self.drive_combo, 1)
        self.refresh_button = button("", "activity")
        self.refresh_button.setToolTip("Procurar os discos de novo")
        self.refresh_button.clicked.connect(self.load_drives)
        drive_row.addWidget(self.refresh_button)
        card.body.addLayout(drive_row)
        self.drive_info = label("", role="caption", wrap=True)
        card.body.addWidget(self.drive_info)

        card.body.addSpacing(Space.XS)
        card.body.addWidget(label("Tipo de teste", role="strong"))
        self.mode_combo = QComboBox()
        for mode in MODES:
            self.mode_combo.addItem(DiskTestMode.LABELS[mode], mode)
        self.mode_combo.currentIndexChanged.connect(self._on_mode_changed)
        card.body.addWidget(self.mode_combo)
        self.mode_hint = label("", role="caption", wrap=True)
        card.body.addWidget(self.mode_hint)

        card.body.addSpacing(Space.XS)
        self.volume_title = label("Unidade do teste de velocidade", role="strong")
        card.body.addWidget(self.volume_title)
        self.volume_combo = QComboBox()
        card.body.addWidget(self.volume_combo)

        card.body.addSpacing(Space.XS)
        card.body.addWidget(divider())
        self.message = ElidedLabel("Pronto para testar.")
        self.message.setProperty("role", "muted")
        card.body.addWidget(self.message)
        self.bar = QProgressBar()
        self.bar.setRange(0, 1000)
        self.bar.setTextVisible(False)
        card.body.addWidget(self.bar)
        card.body.addStretch(1)
        self.cancel_button = button("Cancelar", "x")
        self.cancel_button.clicked.connect(self.cancel)
        self.cancel_button.setVisible(False)
        card.body.addWidget(self.cancel_button)
        self.start_button = button(START_TEXT, "play", "primary", "large")
        self.start_button.clicked.connect(self.start_test)
        card.body.addWidget(self.start_button)
        self._on_mode_changed()
        return card

    @property
    def mode(self) -> str:
        return self.mode_combo.currentData() or DiskTestMode.QUICK

    @property
    def selected_drive(self) -> DriveEntry | None:
        index = self.drive_combo.currentIndex()
        return self.drives[index] if 0 <= index < len(self.drives) else None

    @property
    def is_running(self) -> bool:
        """True while drives are being listed or a test runs."""
        return self._busy

    def showEvent(self, event) -> None:
        super().showEvent(event)
        if not self._loaded:
            self._loaded = True
            self.load_drives()

    def _on_mode_changed(self, _index: int = 0) -> None:
        self.mode_hint.setText(MODE_HINTS[self.mode])
        benchmarking = self.mode != DiskTestMode.HEALTH
        self.volume_title.setVisible(benchmarking)
        self.volume_combo.setVisible(benchmarking)

    def _on_drive_changed(self, _index: int = 0) -> None:
        drive = self.selected_drive
        self.volume_combo.clear()
        if drive is None:
            self.drive_info.setText("")
            return
        parts = [drive.kind_label, f"{formatting.number(drive.size_gb)} GB"]
        if drive.is_system:
            parts.append("disco do sistema")
        if drive.health_status:
            health = WINDOWS_HEALTH.get(drive.health_status, drive.health_status)
            parts.append(f"Windows: {health}")
        self.drive_info.setText("  ·  ".join(parts))
        for volume in drive.volumes:
            if volume.letter:
                text = f"{volume.letter} {volume.label}".strip()
                text += f"  ({formatting.number(volume.free_gb)} GB livres)"
                self.volume_combo.addItem(text, volume.letter)
        if not self.volume_combo.count():
            self.volume_combo.addItem("Sem unidade com letra", "")
        self._update_start_enabled()

    def _update_start_enabled(self) -> None:
        self.start_button.setEnabled(not self._busy and self.selected_drive is not None)

    # --- Drive listing --------------------------------------------------------------

    def load_drives(self) -> None:
        if self._busy:
            return
        self.message.setText("Procurando discos…")
        self.drive_combo.clear()
        self.drives = []
        ps_factory = self.ps_factory
        self._run(
            lambda progress, cancel: list_drives(ps_factory()),
            self._on_drives_loaded,
            lambda error: self._idle(f"Não foi possível listar os discos: {error}"),
        )

    def set_drives(self, drives: list[DriveEntry]) -> None:
        self.drives = list(drives)
        self.drive_combo.blockSignals(True)
        self.drive_combo.clear()
        for drive in self.drives:
            self.drive_combo.addItem(drive.title)
        self.drive_combo.blockSignals(False)
        self._on_drive_changed()

    def _on_drives_loaded(self, drives: list[DriveEntry]) -> None:
        self.set_drives(drives)
        found = formatting.plural(len(drives), "disco encontrado", "discos encontrados")
        self._idle(found if drives else "Nenhum disco físico encontrado.")

    # --- Test -------------------------------------------------------------------------

    def start_test(self) -> None:
        drive = self.selected_drive
        if drive is None or self._busy:
            return
        mode = self.mode
        volume = self.volume_combo.currentData() or ""
        count = len(self.drives)
        ps_factory = self.ps_factory
        log.info("Disk test: disk %s, mode %s, volume %r", drive.number, mode, volume)
        self.bar.setValue(0)
        self._started = time.monotonic()
        self.live = DiskTestProgress()
        subject = drive.title
        if mode != DiskTestMode.HEALTH and volume:
            subject += f"  ·  velocidade em {volume}"
        self.live.start(subject, mode != DiskTestMode.HEALTH)
        self._show_widget(self.live)
        self._run(
            lambda progress, cancel: run_disk_test(
                ps_factory(), drive, mode, volume, count, progress, cancel
            ),
            self.show_report,
            self._on_test_failed,
            cancellable=True,
        )
        self._worker.cancelled.connect(lambda: self._live_fail("Teste cancelado."))

    def _live_fail(self, message: str) -> None:
        if self.live is not None:
            self.live.fail(message)

    def _on_test_failed(self, error: str) -> None:
        message = f"O teste falhou: {error}"
        self._live_fail(message)
        self._idle(message)

    def cancel(self) -> None:
        if self._worker is not None:
            self._last_message = "cancelando, o arquivo de teste será apagado"
            self.message.setText("Cancelando… (o arquivo de teste será apagado)")
            self._worker.cancel()

    def wait(self, timeout_ms: int = 30000) -> bool:
        """Block until the worker thread ends (used when closing the window)."""
        if self._thread is None:
            return True
        if not self._busy:
            self._thread.quit()  # work done; its queued quit() may not have run yet
        return self._thread.wait(timeout_ms)

    def _run(self, task, on_done, on_error, cancellable: bool = False) -> None:
        if self._thread is not None:
            # The previous run already ended; its queued quit() may not have run yet.
            self._thread.quit()
            self._thread.wait()
        self._worker = TaskWorker(task)
        self._worker.progress.connect(self._on_progress)
        self._worker.finished.connect(on_done)
        self._worker.failed.connect(on_error)
        self._worker.cancelled.connect(lambda: self._idle("Teste cancelado."))
        self._thread = start_in_thread(self._worker)
        self._set_running(True, cancellable)

    def _on_progress(self, fraction: float, message: str) -> None:
        self.bar.setValue(int(min(max(fraction, 0.0), 1.0) * 1000))
        self._last_progress = time.monotonic()
        self._last_message = message
        self.message.setText(message)
        self.message.setToolTip("")
        if self.live is not None and self._busy:
            self.live.update(fraction, message)

    def stalled_seconds(self) -> float:
        return time.monotonic() - self._last_progress if self._busy else 0.0

    def _check_stall(self) -> None:
        waited = self.stalled_seconds()
        stalled = waited >= STALL_WARNING_S
        text = f"Disco sem resposta há {waited:.0f} s ({self._last_message})" if stalled else ""
        if self.live is not None:
            self.live.tick(time.monotonic() - self._started, text)
        if not stalled:
            return
        self.message.setText(text)
        self.message.setToolTip(
            "O Windows ainda espera o disco concluir uma leitura ou gravação. Disco com "
            "defeito, cabo ou adaptador USB ruim costumam causar isso. Cancelar só vale "
            "quando o disco responder."
        )

    def _set_running(self, running: bool, cancellable: bool = False) -> None:
        self._busy = running
        self._last_progress = time.monotonic()
        self._last_message = self.message.text()
        if running:
            self._watchdog.start()
        else:
            self._watchdog.stop()
        for widget in (self.drive_combo, self.mode_combo, self.volume_combo, self.refresh_button):
            widget.setEnabled(not running)
        self.cancel_button.setVisible(running and cancellable)
        self.start_button.setVisible(not (running and cancellable))
        self.start_button.setEnabled(not running and self.selected_drive is not None)
        self.running_changed.emit(running)

    def _idle(self, message: str) -> None:
        # The thread and worker stay referenced until the next run: the thread quits a moment
        # after this signal (its quit() is queued to this thread), and dropping a running
        # QThread aborts the app.
        self.message.setText(message)
        self._set_running(False)

    # --- Results ----------------------------------------------------------------------

    def show_report(self, report: DiskTestReport) -> None:
        self.live = None
        self.report = report
        self.saved_pdf = None
        self.bar.setValue(1000)
        self._idle("Teste concluído.")
        self._show_widget(self._results_view(report))

    def _show_widget(self, widget: QWidget) -> None:
        if self._results_widget is not None:
            self.results_holder.removeWidget(self._results_widget)
            self._results_widget.hide()
            self._results_widget.deleteLater()
        self._results_widget = widget
        self.results_holder.addWidget(widget)

    def _results_view(self, report: DiskTestReport) -> QWidget:
        holder = QWidget()
        outer = vbox(Space.M, (0, 0, 0, 0))
        self.result_tabs = QTabWidget()
        self.result_tabs.setDocumentMode(True)
        self.result_tabs.addTab(self._summary_view(report), RESULT_TABS[0])
        self.result_tabs.addTab(self._details_view(report), RESULT_TABS[1])
        outer.addWidget(self.result_tabs, 1)

        actions = hbox(Space.S)
        actions.addStretch(1)
        self.open_folder_button = button("Abrir pasta", "folder")
        self.open_folder_button.clicked.connect(self._open_folder)
        actions.addWidget(self.open_folder_button)
        self.save_button = button("Salvar PDF", "file-pdf", "primary")
        self.save_button.clicked.connect(self.save_report)
        actions.addWidget(self.save_button)
        outer.addLayout(actions)
        holder.setLayout(outer)
        return holder

    def _summary_view(self, report: DiskTestReport) -> QWidget:
        """Plain-language situation of the drive: what anyone needs to decide."""
        summary = disk_summary.build(report)
        content = QWidget()
        column = vbox(Space.L, (0, Space.M, Space.S, Space.L))

        situation = Card(spacing=Space.S)
        situation.set_tone(_status_tone(summary.status))
        situation.body.addWidget(label("Situação do disco", role="eyebrow"))
        situation.body.addWidget(
            label(summary.situation, role="title", tone=_status_tone(summary.status))
        )
        situation.body.addWidget(label(summary.headline, role="headline", wrap=True))
        situation.body.addWidget(label(report.drive.title, role="muted", wrap=True))
        for reason in summary.reasons:
            situation.body.addWidget(label(f"•  {reason}", wrap=True, selectable=True))
        column.addWidget(situation)
        self.summary_situation = summary.situation

        tiles = hbox(Space.M)
        for fact in summary.facts:
            tiles.addWidget(
                StatCard(fact.title, fact.value, fact.detail, FACT_ICONS.get(fact.title, "info"),
                         _status_tone(fact.status))
            )  # fmt: skip
        column.addLayout(tiles)

        speed = Card("Velocidade", spacing=Space.S)
        speed.body.addWidget(label(summary.speed, wrap=True, selectable=True))
        column.addWidget(speed)

        if summary.cares:
            cares = Card("Cuidados (não são defeito do disco)", spacing=Space.S)
            for care in summary.cares:
                cares.body.addWidget(label(f"•  {care}", wrap=True, selectable=True))
            column.addWidget(cares)

        if summary.actions:
            actions = Card("O que fazer", spacing=Space.S)
            for number, action in enumerate(summary.actions, 1):
                actions.body.addWidget(label(f"{number}.  {action}", wrap=True, selectable=True))
            column.addWidget(actions)

        column.addWidget(
            label(
                "Saúde calculada como no Hard Disk Sentinel: vida útil do SSD menos setores "
                "defeituosos e erros que o disco não corrigiu. Pode variar alguns pontos.",
                role="caption",
                wrap=True,
            )
        )
        column.addStretch(1)
        content.setLayout(column)
        return scroll_area(content)

    def _details_view(self, report: DiskTestReport) -> QWidget:
        content = QWidget()
        column = vbox(Space.L, (0, Space.M, Space.S, Space.L))

        tiles = hbox(Space.M)
        score = "?" if report.score is None else f"{report.score}/100"
        tiles.addWidget(StatCard("Nota", score, report.drive.kind_label, "gauge",
                                 _score_tone(report.score)))  # fmt: skip
        tiles.addWidget(
            StatCard("Saúde", report.health_status.label, self._health_detail(report),
                     "heart-pulse", _status_tone(report.health_status))
        )  # fmt: skip
        perf_detail = f"unidade {report.tested_volume}" if report.tested_volume else "não medido"
        perf_value = report.performance_status.label
        if report.over_usb and report.performance:
            perf_value, perf_detail = "Pelo USB", "não avalia o disco"
        tiles.addWidget(
            StatCard("Desempenho", perf_value, perf_detail, "activity",
                     _status_tone(report.performance_status))
        )  # fmt: skip
        column.addLayout(tiles)

        verdict = Card(spacing=Space.S)
        verdict.set_tone(_status_tone(report.overall_status))
        verdict.body.addWidget(label(report.verdict, role="headline", wrap=True))
        verdict.body.addWidget(label(report.drive.title, role="muted", wrap=True))
        column.addWidget(verdict)

        if report.recommendations:
            tips = Card("Recomendações", spacing=Space.S)
            for tip in report.recommendations:
                tips.body.addWidget(label(f"•  {tip}", wrap=True, selectable=True))
            column.addWidget(tips)

        column.addWidget(self._health_card(report))
        if report.performance or report.performance_error:
            column.addWidget(self._performance_card(report))
        if report.smart:
            column.addWidget(self._smart_card(report))
        column.addWidget(self._identity_card(report))
        column.addStretch(1)
        content.setLayout(column)
        return scroll_area(content)

    @staticmethod
    def _health_detail(report: DiskTestReport) -> str:
        problems = sum(1 for r in report.readings if r.status in (Status.WARNING, Status.CRITICAL))
        if not report.readings:
            return "sem leituras"
        if not problems:
            return formatting.plural(len(report.readings), "item OK", "itens OK")
        return formatting.plural(problems, "alerta", "alertas")

    def _health_card(self, report: DiskTestReport) -> Card:
        card = Card("Saúde", spacing=0)
        order = [Status.CRITICAL, Status.WARNING, Status.UNKNOWN, Status.OK]
        readings = sorted(report.readings, key=lambda r: order.index(r.status))
        grid = QGridLayout()
        grid.setHorizontalSpacing(Space.L)
        grid.setVerticalSpacing(Space.S)
        for row, reading in enumerate(readings):
            chip = StatusChip.for_status(reading.status)
            grid.addWidget(chip, row, 0)
            grid.addWidget(label(reading.label, role="strong", wrap=True), row, 1)
            grid.addWidget(label(reading.value, selectable=True), row, 2)
            grid.addWidget(label(reading.note, role="caption", wrap=True), row, 3)
        grid.setColumnStretch(1, 3)
        grid.setColumnStretch(2, 2)
        grid.setColumnStretch(3, 3)
        card.body.addSpacing(Space.S)
        card.body.addLayout(grid)
        return card

    def _performance_card(self, report: DiskTestReport) -> Card:
        from extract.analysis.reference import DISK_EXPECTATIONS

        card = Card("Desempenho", spacing=Space.S)
        if report.performance_error:
            card.body.addWidget(label(report.performance_error, tone="warning", wrap=True))
        # Over USB the link sets the speed: comparing with a SATA SSD would only confuse.
        expected = (
            None if report.over_usb else DISK_EXPECTATIONS.get(report.drive.kind or "sata_ssd")
        )
        grid = QGridLayout()
        grid.setHorizontalSpacing(Space.L)
        grid.setVerticalSpacing(Space.S)
        row = 0
        for key, title, unit, decimals in disk_report.PERFORMANCE_ROWS:
            metric = report.performance.get(key)
            if metric is None:
                continue
            grid.addWidget(label(title, role="strong"), row, 0)
            value = f"{formatting.number(metric.value, decimals)} {unit}"
            grid.addWidget(label(value, selectable=True), row, 1)
            reference = BAR_REFERENCES.get(key)
            if reference and expected is not None:
                typical = getattr(expected, reference[0]) * reference[1]
                fraction = min(1.0, metric.value / typical) if typical else 0.0
                tone = "ok" if fraction >= 0.6 else "warning" if fraction >= 0.25 else "critical"
                grid.addWidget(MetricBar(fraction, tone), row, 2)
            grid.addWidget(label(disk_report.expected_text(report, key), role="caption"), row, 3)
            row += 1
        grid.setColumnStretch(2, 1)
        card.body.addLayout(grid)
        if report.over_usb and row:
            card.body.addWidget(
                label(
                    "Medido pelo USB: a velocidade é a do adaptador e da porta, não a do disco, "
                    "por isso não há barras nem comparação com SSD/HD.",
                    role="caption",
                    wrap=True,
                )
            )
        elif expected is not None and row:
            card.body.addWidget(
                label(
                    f"Barras em relação a um {expected.label} típico "
                    f"({formatting.number(expected.typical_seq_read_mb_s)} MB/s, "
                    f"{formatting.number(expected.typical_random_read_iops)} IOPS).",
                    role="caption",
                    wrap=True,
                )
            )
        return card

    def _smart_card(self, report: DiskTestReport) -> Card:
        card = Card("Atributos SMART", spacing=Space.S)
        grid = QGridLayout()
        grid.setHorizontalSpacing(Space.L)
        grid.setVerticalSpacing(Space.XS)
        for col, text in enumerate(("ID", "Atributo", "Atual", "Pior", "Limite", "Bruto")):
            grid.addWidget(label(text, role="eyebrow"), 0, col)
        for row, attribute in enumerate(report.smart, start=1):
            values = (
                str(attribute.id),
                attribute.name,
                str(attribute.current),
                str(attribute.worst),
                "" if attribute.threshold is None else str(attribute.threshold),
                attribute.raw_display,
            )
            flagged = attribute.status is not Status.OK
            for col, text in enumerate(values):
                cell = label(text, role="strong" if col == 1 else None, wrap=col == 1)
                if flagged and col in (1, 5):
                    cell.setProperty("tone", _status_tone(attribute.status))
                    cell.setToolTip(attribute.note)
                grid.addWidget(cell, row, col)
        grid.setColumnStretch(1, 1)
        card.body.addLayout(grid)
        card.body.addWidget(
            label(
                "Atual e Pior caem com o uso; o disco é dado como falho quando chegam ao Limite. "
                "Itens em cor: passe o mouse para ver o motivo.",
                role="caption",
                wrap=True,
            )
        )
        return card

    def _identity_card(self, report: DiskTestReport) -> Card:
        card = Card("Identificação", spacing=Space.XS)
        grid = QGridLayout()
        grid.setHorizontalSpacing(Space.L)
        for row, (key, value) in enumerate(disk_report.identity_rows(report)):
            grid.addWidget(label(key, role="muted"), row, 0)
            grid.addWidget(label(value, selectable=True), row, 1)
        grid.setColumnStretch(1, 1)
        card.body.addLayout(grid)
        if not report.is_admin:
            card.body.addWidget(
                label(
                    "Dica: abra o Extract como administrador para ler todos os contadores SMART.",
                    role="caption",
                    wrap=True,
                )
            )
        return card

    # --- Saving -----------------------------------------------------------------------

    def folder(self) -> Path:
        return settings.reports_root() / disk_report.FOLDER_NAME

    def save_report(self) -> Path | None:
        if self.report is None:
            return None
        try:
            _json_path, pdf_path = disk_report.save(self.report, self.folder())
        except OSError as exc:
            QMessageBox.warning(self, "Não foi possível salvar", str(exc))
            return None
        self.saved_pdf = pdf_path
        self.message.setText(f"Salvo em {pdf_path.name}")
        QDesktopServices.openUrl(QUrl.fromLocalFile(str(pdf_path)))
        return pdf_path

    def _open_folder(self) -> None:
        folder = self.folder()
        folder.mkdir(parents=True, exist_ok=True)
        QDesktopServices.openUrl(QUrl.fromLocalFile(str(folder)))
