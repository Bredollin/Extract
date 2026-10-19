"""Resultados page: verdict, summary and the details of one machine's report."""

from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import Signal
from PySide6.QtWidgets import QFileDialog, QMessageBox, QStackedWidget, QTabWidget, QWidget

from extract.core.models import MachineReport
from extract.gui import exporting, settings
from extract.gui.pages.results.findings import findings_view
from extract.gui.pages.results.hardware import hardware_view
from extract.gui.pages.results.health import health_view
from extract.gui.pages.results.performance import performance_view
from extract.gui.pages.results.summary import machine_subtitle, summary_cards
from extract.gui.theme import Space
from extract.gui.widgets.common import button, vbox
from extract.gui.widgets.empty_state import EmptyState
from extract.gui.widgets.page_header import PageHeader
from extract.gui.widgets.verdict_banner import VerdictBanner

TABS = ("Achados", "Saúde", "Desempenho", "Hardware")


class ResultsPage(QWidget):
    new_scan_requested = Signal()

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("Page")
        self.report: MachineReport | None = None
        self.path: Path | None = None
        self.stack = QStackedWidget()
        self.stack.addWidget(self._empty_state())
        self.content = QWidget()
        self.stack.addWidget(self.content)
        layout = vbox()
        layout.addWidget(self.stack)
        self.setLayout(layout)
        self._build_content()

    def _empty_state(self) -> QWidget:
        start = button("Iniciar diagnóstico", "play", "primary")
        start.clicked.connect(self.new_scan_requested)
        open_file = button("Abrir relatório salvo", "folder")
        open_file.clicked.connect(self._open_saved_report)
        return EmptyState(
            "clipboard-check",
            "Nenhum diagnóstico aberto",
            "Faça um diagnóstico desta máquina ou abra um relatório JSON salvo anteriormente.",
            [start, open_file],
        )

    def _build_content(self) -> None:
        column = vbox(Space.L, (Space.XXL, Space.XL + 4, Space.XXL, Space.L))
        self.header = PageHeader("", "")
        self.json_button = button("Abrir JSON", "file-json")
        self.json_button.clicked.connect(self._open_json)
        self.header.add_action(self.json_button)
        self.pdf_button = button("Exportar PDF", "file-pdf", "primary")
        self.pdf_button.clicked.connect(self._export_pdf)
        self.header.add_action(self.pdf_button)
        column.addWidget(self.header)
        self.banner = VerdictBanner()
        column.addWidget(self.banner)
        self.summary_slot = vbox()
        column.addLayout(self.summary_slot)
        self.tabs = QTabWidget()
        self.tabs.setDocumentMode(True)
        column.addWidget(self.tabs, 1)
        self.content.setLayout(column)

    def show_report(self, report: MachineReport, path: Path | None = None) -> None:
        self.report, self.path = report, path
        system = report.inventory.system
        self.header.title.setText(report.hostname)
        self.header.subtitle.setText(machine_subtitle(report))
        serial = system.serial_number
        self.header.subtitle.setToolTip(f"Nº de série {serial}" if serial else "")
        self.json_button.setEnabled(path is not None)
        self.banner.show_findings(report.findings)
        while self.summary_slot.count():
            self.summary_slot.takeAt(0).widget().deleteLater()
        self.summary_slot.addWidget(summary_cards(report))
        self._fill_tabs(report)
        self.stack.setCurrentWidget(self.content)

    def _fill_tabs(self, report: MachineReport) -> None:
        current = max(self.tabs.currentIndex(), 0)
        while self.tabs.count():
            widget = self.tabs.widget(0)
            self.tabs.removeTab(0)
            widget.deleteLater()
        views = (
            findings_view(report.findings),
            health_view(report.health),
            performance_view(report.benchmarks),
            hardware_view(report.inventory),
        )
        for title, view in zip(TABS, views, strict=True):
            self.tabs.addTab(view, title)
        self.tabs.setCurrentIndex(current)

    def show_tab(self, title: str) -> None:
        self.tabs.setCurrentIndex(TABS.index(title))

    def _open_json(self) -> None:
        if self.path is not None:
            exporting.open_path(self.path)

    def _export_pdf(self) -> None:
        if self.report is None:
            return
        folder = self.path.parent if self.path else settings.reports_root()
        path = exporting.export_with_dialog(
            self, "pdf", [self.report], folder, self.report.hostname
        )
        if path is not None:
            exporting.open_path(path)

    def _open_saved_report(self) -> None:
        start = str(settings.reports_root())
        chosen, _ = QFileDialog.getOpenFileName(
            self, "Abrir relatório", start, "Relatório (*.json)"
        )
        if not chosen:
            return
        from extract.reports import load_report

        try:
            report = load_report(Path(chosen))
        except (OSError, ValueError, TypeError, KeyError) as exc:
            QMessageBox.warning(
                self, "Relatório inválido", f"Não foi possível abrir o arquivo:\n{exc}"
            )
            return
        self.show_report(report, Path(chosen))
