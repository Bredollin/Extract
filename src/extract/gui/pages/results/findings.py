"""Achados tab: one card per finding, most severe first (the verdict has its own banner)."""

from __future__ import annotations

from PySide6.QtWidgets import QWidget

from extract.core.models import Finding
from extract.gui.theme import Space
from extract.gui.widgets.common import scroll_area, vbox
from extract.gui.widgets.empty_state import EmptyState
from extract.gui.widgets.finding_card import FindingCard
from extract.gui.widgets.verdict_banner import VERDICT_PREFIX


def findings_view(findings: list[Finding]) -> QWidget:
    shown = sorted(
        (f for f in findings if not f.id.startswith(VERDICT_PREFIX)),
        key=lambda f: f.severity.rank,
        reverse=True,
    )
    if not shown:
        return EmptyState(
            "check-circle",
            "Nenhum achado",
            "A análise não encontrou causas de lentidão ou falha nesta máquina.",
        )
    content = QWidget()
    column = vbox(Space.M, (0, Space.L, Space.S, Space.L))
    for finding in shown:
        column.addWidget(FindingCard(finding))
    column.addStretch(1)
    content.setLayout(column)
    return scroll_area(content)
