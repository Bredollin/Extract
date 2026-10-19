"""Saúde tab: every health check with its status chip, problems first."""

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QWidget

from extract.core.models import HealthCheck, Status
from extract.gui import formatting
from extract.gui.theme import Space
from extract.gui.widgets.card import Card
from extract.gui.widgets.common import divider, hbox, label, scroll_area, vbox
from extract.gui.widgets.empty_state import EmptyState
from extract.gui.widgets.status_chip import StatusChip

STATUS_ORDER = [Status.CRITICAL, Status.WARNING, Status.UNKNOWN, Status.OK]
STATUS_COUNT_LABELS = {
    Status.CRITICAL: ("crítica", "críticas"),
    Status.WARNING: ("em atenção", "em atenção"),
    Status.UNKNOWN: ("indisponível", "indisponíveis"),
    Status.OK: ("OK", "OK"),
}
CHIP_WIDTH = 104
TITLE_WIDTH = 230


def health_view(checks: list[HealthCheck]) -> QWidget:
    if not checks:
        return EmptyState(
            "heart-pulse",
            "Saúde não verificada",
            "Este diagnóstico foi feito sem as verificações de saúde do sistema.",
        )
    ordered = sorted(checks, key=lambda c: STATUS_ORDER.index(c.status))
    content = QWidget()
    column = vbox(Space.M, (0, Space.L, Space.S, Space.L))
    column.addWidget(label(_summary(checks), role="muted"))
    card = Card(padding=Space.S, spacing=0)
    for index, check in enumerate(ordered):
        if index:
            card.body.addWidget(divider())
        card.body.addWidget(_row(check))
    column.addWidget(card)
    column.addStretch(1)
    content.setLayout(column)
    return scroll_area(content)


def _summary(checks: list[HealthCheck]) -> str:
    counts = {s: sum(1 for c in checks if c.status is s) for s in STATUS_ORDER}
    parts = [
        formatting.plural(counts[s], *STATUS_COUNT_LABELS[s]) for s in STATUS_ORDER if counts[s]
    ]
    return f"{len(checks)} verificações  ·  " + "  ·  ".join(parts)


def _row(check: HealthCheck) -> QWidget:
    row_widget = QWidget()
    row = hbox(Space.L, (Space.M, Space.M, Space.M, Space.M))
    chip_box = QWidget()
    chip_box.setFixedWidth(CHIP_WIDTH)
    chip_layout = hbox()
    chip_layout.addWidget(StatusChip.for_status(check.status))
    chip_layout.addStretch(1)
    chip_box.setLayout(chip_layout)
    row.addWidget(chip_box, 0, Qt.AlignmentFlag.AlignTop)
    title = label(check.title, role="strong", wrap=True)
    title.setFixedWidth(TITLE_WIDTH)
    row.addWidget(title, 0, Qt.AlignmentFlag.AlignTop)
    row.addWidget(label(check.summary, role="muted", wrap=True, selectable=True), 1)
    row.addWidget(label(check.category.label, role="caption"), 0, Qt.AlignmentFlag.AlignTop)
    row_widget.setLayout(row)
    return row_widget
