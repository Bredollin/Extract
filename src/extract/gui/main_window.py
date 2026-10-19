"""Main window: sidebar navigation over the four pages."""

from __future__ import annotations

import logging
from pathlib import Path

from PySide6.QtGui import QCloseEvent
from PySide6.QtWidgets import QMainWindow, QMessageBox, QStackedWidget, QWidget

from extract.core.models import MachineReport
from extract.gui import theme
from extract.gui.icons import app_icon
from extract.gui.pages.about import AboutPage
from extract.gui.pages.diagnostic import DiagnosticPage
from extract.gui.pages.reports import ReportsPage
from extract.gui.pages.results import ResultsPage
from extract.gui.widgets.common import hbox
from extract.gui.widgets.log_panel import QtLogHandler
from extract.gui.widgets.sidebar import Sidebar

PAGES = (
    ("Diagnóstico", "activity"),
    ("Resultados", "clipboard-check"),
    ("Relatórios", "files"),
    ("Sobre", "info"),
)
DIAGNOSTIC, RESULTS, REPORTS, ABOUT = range(len(PAGES))
DEFAULT_SIZE = (1280, 800)
MINIMUM_SIZE = (1080, 700)


class MainWindow(QMainWindow):
    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Extract")
        self.setWindowIcon(app_icon())
        self.resize(*DEFAULT_SIZE)
        self.setMinimumSize(*MINIMUM_SIZE)

        self.log_handler = QtLogHandler()
        logging.getLogger("extract").addHandler(self.log_handler)

        self.sidebar = Sidebar(list(PAGES))
        self.stack = QStackedWidget()
        self.stack.setObjectName("Pages")
        self.diagnostic = DiagnosticPage(self.log_handler)
        self.results = ResultsPage()
        self.reports = ReportsPage()
        self.about = AboutPage()
        for page in (self.diagnostic, self.results, self.reports, self.about):
            self.stack.addWidget(page)

        root = QWidget()
        root.setObjectName("Root")
        layout = hbox()
        layout.addWidget(self.sidebar)
        layout.addWidget(self.stack, 1)
        root.setLayout(layout)
        self.setCentralWidget(root)

        self.sidebar.page_selected.connect(self.show_page)
        self.sidebar.theme_toggled.connect(theme.manager().toggle)
        self.diagnostic.report_ready.connect(self._on_report_ready)
        self.results.new_scan_requested.connect(lambda: self.show_page(DIAGNOSTIC))
        self.reports.report_opened.connect(self.open_report)
        self.show_page(DIAGNOSTIC)

    def show_page(self, index: int) -> None:
        self.stack.setCurrentIndex(index)
        self.sidebar.select(index)
        if index == REPORTS and not self.diagnostic.is_running:
            self.reports.refresh_clients()

    def open_report(self, report: MachineReport, path: Path | None = None) -> None:
        self.results.show_report(report, path)
        self.show_page(RESULTS)

    def _on_report_ready(self, report: MachineReport, path: Path) -> None:
        self.reports.refresh_clients(path.parent)
        self.open_report(report, path)

    def closeEvent(self, event: QCloseEvent) -> None:
        if self.diagnostic.is_running:
            answer = QMessageBox.question(
                self,
                "Diagnóstico em andamento",
                "Um diagnóstico está em andamento. Deseja cancelar e sair?",
            )
            if answer != QMessageBox.StandardButton.Yes:
                event.ignore()
                return
            self.diagnostic.cancel_scan()
            self.diagnostic.wait_for_scan()
        logging.getLogger("extract").removeHandler(self.log_handler)
        super().closeEvent(event)
