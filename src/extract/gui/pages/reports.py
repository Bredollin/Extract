"""Relatórios page: list the machines of a client folder and export them."""

from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QAbstractItemView,
    QComboBox,
    QFileDialog,
    QHeaderView,
    QStackedWidget,
    QTableWidget,
    QTableWidgetItem,
    QWidget,
)

from extract.core.models import MachineReport, Severity
from extract.gui import exporting, formatting, settings
from extract.gui.pages.results.summary import severity_count
from extract.gui.theme import SEVERITY_TONES, Space
from extract.gui.widgets.card import Card
from extract.gui.widgets.common import button, hbox, label, vbox
from extract.gui.widgets.empty_state import EmptyState
from extract.gui.widgets.page_header import PageHeader
from extract.gui.widgets.status_chip import StatusChip
from extract.gui.widgets.verdict_banner import find_verdict

CHIP_TEXT_WIDTH = 240
COLUMNS = ("Máquina", "Modelo", "Diagnóstico", "Críticos", "Atenção", "Situação")


def client_folders(root: Path) -> list[Path]:
    if not root.is_dir():
        return []
    return sorted((p for p in root.iterdir() if p.is_dir()), key=lambda p: p.name.lower())


class ReportsPage(QWidget):
    report_opened = Signal(object, object)  # MachineReport, Path | None

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("Page")
        self.reports: list[MachineReport] = []
        self.folder: Path | None = None
        self.last_export: Path | None = None

        column = vbox(Space.XL, (Space.XXL, Space.XL + 4, Space.XXL, Space.XL))
        header = PageHeader(
            "Relatórios",
            "Consolide as máquinas de um cliente em uma planilha Excel ou em um PDF.",
        )
        column.addWidget(header)
        column.addLayout(self._folder_row())

        card = Card(padding=Space.S, spacing=0)
        self.stack = QStackedWidget()
        self.empty = EmptyState(
            "inbox",
            "Nenhuma máquina nesta pasta",
            "Os diagnósticos salvos para este cliente aparecem aqui. "
            "Escolha outra pasta ou faça um novo diagnóstico.",
        )
        self.stack.addWidget(self.empty)
        self.table = self._build_table()
        self.stack.addWidget(self.table)
        card.body.addWidget(self.stack)
        column.addWidget(card, 1)
        column.addLayout(self._actions_row())
        self.setLayout(column)
        self.refresh_clients()

    # --- Building ------------------------------------------------------------------

    def _folder_row(self):
        row = hbox(Space.S)
        row.addWidget(label("Cliente", role="strong"))
        row.addSpacing(Space.XS)
        self.client_combo = QComboBox()
        self.client_combo.setMinimumWidth(280)
        self.client_combo.currentIndexChanged.connect(self._on_client_changed)
        row.addWidget(self.client_combo)
        browse = button("Escolher pasta…", "folder")
        browse.clicked.connect(self._choose_folder)
        row.addWidget(browse)
        row.addSpacing(Space.S)
        self.folder_label = label("", role="caption")
        row.addWidget(self.folder_label, 1)
        return row

    def _build_table(self) -> QTableWidget:
        table = QTableWidget(0, len(COLUMNS))
        table.setHorizontalHeaderLabels(COLUMNS)
        table.verticalHeader().setVisible(False)
        table.verticalHeader().setDefaultSectionSize(48)
        table.setShowGrid(False)
        table.setSelectionMode(QAbstractItemView.SelectionMode.NoSelection)
        table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        table.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        header = table.horizontalHeader()
        header.setDefaultAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)
        header.setHighlightSections(False)
        header.setSectionResizeMode(QHeaderView.ResizeMode.ResizeToContents)
        header.setSectionResizeMode(0, QHeaderView.ResizeMode.Interactive)
        header.setSectionResizeMode(len(COLUMNS) - 1, QHeaderView.ResizeMode.Stretch)
        table.itemChanged.connect(self._update_actions)
        table.cellDoubleClicked.connect(self._open_row)
        return table

    def _actions_row(self):
        row = hbox(Space.S)
        self.selection_label = label("", role="muted")
        row.addWidget(self.selection_label, 1)
        self.open_folder_button = button("Abrir pasta", "folder")
        self.open_folder_button.clicked.connect(self._open_folder)
        row.addWidget(self.open_folder_button)
        self.open_export_button = button("Abrir arquivo gerado", "external")
        self.open_export_button.clicked.connect(self._open_export)
        self.open_export_button.setVisible(False)
        row.addWidget(self.open_export_button)
        self.excel_button = button("Exportar Excel", "sheet")
        self.excel_button.clicked.connect(lambda: self._export("excel"))
        row.addWidget(self.excel_button)
        self.pdf_button = button("Exportar PDF", "file-pdf", "primary")
        self.pdf_button.clicked.connect(lambda: self._export("pdf"))
        row.addWidget(self.pdf_button)
        return row

    # --- Folder and listing ----------------------------------------------------------

    def refresh_clients(self, select: Path | None = None) -> None:
        root = settings.reports_root()
        folders = client_folders(root)
        target = select or self.folder
        if target is not None and target not in folders:
            folders.append(target)
        self.client_combo.blockSignals(True)
        self.client_combo.clear()
        for folder in folders:
            self.client_combo.addItem(folder.name, str(folder))
        index = folders.index(target) if target in folders else 0
        self.client_combo.setCurrentIndex(index)
        self.client_combo.blockSignals(False)
        self.load_folder(folders[index] if folders else None)

    def _on_client_changed(self, index: int) -> None:
        data = self.client_combo.itemData(index)
        self.load_folder(Path(data) if data else None)

    def _choose_folder(self) -> None:
        start = str(self.folder or settings.reports_root())
        chosen = QFileDialog.getExistingDirectory(self, "Pasta do cliente", start)
        if chosen:
            self.refresh_clients(Path(chosen))

    def load_folder(self, folder: Path | None) -> None:
        from extract.reports import load_folder

        self.folder = folder
        self.reports = load_folder(folder) if folder and folder.is_dir() else []
        self.folder_label.setText(str(folder) if folder else "")
        self.folder_label.setToolTip(str(folder) if folder else "")
        self._fill_table()

    def _fill_table(self) -> None:
        self.table.blockSignals(True)
        self.table.setRowCount(len(self.reports))
        for row, report in enumerate(self.reports):
            self._fill_row(row, report)
        self.table.resizeColumnToContents(0)
        # Room for the checkbox and the bold font, which the size hint does not count.
        self.table.setColumnWidth(0, self.table.columnWidth(0) + 36)
        self.table.blockSignals(False)
        self.stack.setCurrentWidget(self.table if self.reports else self.empty)
        self.open_export_button.setVisible(False)
        self._update_actions()

    def _fill_row(self, row: int, report: MachineReport) -> None:
        system = report.inventory.system
        critical = severity_count(report, Severity.CRITICAL)
        warning = severity_count(report, Severity.WARNING)
        values = (
            report.hostname,
            " ".join(p for p in (system.manufacturer, system.model) if p),
            formatting.date_time(report.created_at),
            str(critical),
            str(warning),
        )
        for column, value in enumerate(values):
            item = QTableWidgetItem(value)
            if column == 0:
                font = item.font()
                font.setBold(True)
                item.setFont(font)
                item.setFlags(item.flags() | Qt.ItemFlag.ItemIsUserCheckable)
                item.setCheckState(Qt.CheckState.Checked)
            self.table.setItem(row, column, item)
        verdict = find_verdict(report.findings)
        if verdict is not None:
            chip = StatusChip("", SEVERITY_TONES[verdict.severity])
            chip.ensurePolished()
            elide = Qt.TextElideMode.ElideRight
            chip.setText(chip.fontMetrics().elidedText(verdict.title, elide, CHIP_TEXT_WIDTH))
            if verdict.id == "verdict.ok":
                chip.set_tone("ok")
            chip.setToolTip(f"{verdict.title}\n{verdict.recommendation}")
            holder = QWidget()
            layout = hbox(0, (Space.S, 0, Space.S, 0))
            layout.addWidget(chip)
            layout.addStretch(1)
            holder.setLayout(layout)
            self.table.setCellWidget(row, len(COLUMNS) - 1, holder)

    # --- Actions -------------------------------------------------------------------

    def selected_reports(self) -> list[MachineReport]:
        return [
            report
            for row, report in enumerate(self.reports)
            if self.table.item(row, 0).checkState() == Qt.CheckState.Checked
        ]

    def _update_actions(self) -> None:
        count = len(self.selected_reports())
        total = len(self.reports)
        has_selection = count > 0
        self.excel_button.setEnabled(has_selection)
        self.pdf_button.setEnabled(has_selection)
        self.open_folder_button.setEnabled(self.folder is not None and self.folder.is_dir())
        if total:
            machines = formatting.plural(total, "máquina", "máquinas")
            self.selection_label.setText(
                f"{count} de {machines} marcadas para exportar  ·  duplo clique abre o diagnóstico"
            )
        else:
            self.selection_label.setText("")

    def _open_folder(self) -> None:
        if self.folder is not None:
            exporting.open_path(self.folder)

    def _open_export(self) -> None:
        if self.last_export is not None:
            exporting.open_path(self.last_export)

    def _open_row(self, row: int, _column: int) -> None:
        report = self.reports[row]
        self.report_opened.emit(report, self._report_path(report))

    def _report_path(self, report: MachineReport) -> Path | None:
        from extract.reports.storage import report_filename

        if self.folder is None:
            return None
        path = self.folder / report_filename(report)
        return path if path.exists() else None

    def _export(self, kind: str) -> None:
        reports = self.selected_reports()
        if not reports or self.folder is None:
            return
        path = exporting.export_with_dialog(self, kind, reports, self.folder, self.folder.name)
        if path is not None:
            self.last_export = path
            self.open_export_button.setVisible(True)
            self.selection_label.setText(f"Arquivo gerado: {path.name}")
