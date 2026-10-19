"""Excel/PDF export and opening files, shared by the Resultados and Relatórios pages.

The exporters are imported on use so the GUI keeps working if they fail to import.
"""

from __future__ import annotations

import logging
from datetime import datetime
from pathlib import Path

from PySide6.QtCore import QUrl
from PySide6.QtGui import QDesktopServices
from PySide6.QtWidgets import QFileDialog, QMessageBox, QWidget

from extract.core.models import MachineReport

log = logging.getLogger(__name__)

FORMATS = {
    "excel": ("Planilha Excel", ".xlsx", "Planilha Excel (*.xlsx)"),
    "pdf": ("Relatório PDF", ".pdf", "Documento PDF (*.pdf)"),
}


def export_reports(kind: str, reports: list[MachineReport], path: Path) -> Path:
    if kind == "excel":
        from extract.reports.excel import export_excel

        return export_excel(reports, path)
    from extract.reports.pdf import export_pdf

    return export_pdf(reports, path)


def default_export_name(base: str, kind: str) -> str:
    from extract.reports.storage import safe_filename

    return f"{safe_filename(base)}_{datetime.now():%Y-%m-%d}{FORMATS[kind][1]}"


def export_with_dialog(
    parent: QWidget, kind: str, reports: list[MachineReport], folder: Path, base_name: str
) -> Path | None:
    """Ask where to save, export, and report errors in a message box."""
    title, _suffix, file_filter = FORMATS[kind]
    suggested = folder / default_export_name(base_name, kind)
    chosen, _ = QFileDialog.getSaveFileName(
        parent, f"Exportar {title}", str(suggested), file_filter
    )
    if not chosen:
        return None
    try:
        path = export_reports(kind, reports, Path(chosen))
    except Exception as exc:
        log.exception("Export to %s failed", chosen)
        QMessageBox.critical(parent, "Falha na exportação", f"Não foi possível exportar:\n{exc}")
        return None
    log.info("Exported %d report(s) to %s", len(reports), path)
    return path


def open_path(path: Path) -> bool:
    """Open a file or folder with the system's default application."""
    return QDesktopServices.openUrl(QUrl.fromLocalFile(str(path)))
