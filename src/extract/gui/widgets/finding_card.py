"""Card for one analysis finding: severity, title, detail and recommendation."""

from __future__ import annotations

from PySide6.QtWidgets import QFrame, QWidget

from extract.core.models import Finding, Severity
from extract.gui.icons import IconLabel
from extract.gui.theme import SEVERITY_TONES, Space
from extract.gui.widgets.common import hbox, label, set_tone, vbox
from extract.gui.widgets.status_chip import StatusChip

SEVERITY_ICONS = {
    Severity.CRITICAL: "alert-octagon",
    Severity.WARNING: "alert-triangle",
    Severity.INFO: "info",
}


class FindingCard(QFrame):
    def __init__(self, finding: Finding, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setProperty("card", True)
        tone = SEVERITY_TONES[finding.severity]

        row = hbox(Space.L, (Space.L, Space.L, Space.XL, Space.L))
        stripe = QFrame()
        stripe.setObjectName("Stripe")
        stripe.setFixedWidth(4)
        set_tone(stripe, tone)
        row.addWidget(stripe)
        icon_column = vbox()
        icon_column.addWidget(IconLabel(SEVERITY_ICONS[finding.severity], tone, 18, badge=True))
        icon_column.addStretch(1)
        row.addLayout(icon_column)

        content = vbox(Space.S)
        head = hbox(Space.S)
        head.addWidget(label(finding.title, role="section", wrap=True), 1)
        head.addWidget(label(finding.category.label, role="caption"))
        head.addWidget(StatusChip(finding.severity.label, tone))
        content.addLayout(head)
        content.addWidget(label(finding.detail, role="muted", wrap=True, selectable=True))
        if finding.recommendation:
            content.addWidget(self._recommendation(finding.recommendation))
        row.addLayout(content, 1)
        self.setLayout(row)

    @staticmethod
    def _recommendation(text: str) -> QFrame:
        box = QFrame()
        box.setProperty("inset", True)
        layout = hbox(Space.S, (Space.M, Space.S, Space.M, Space.S))
        icon_column = vbox()
        icon_column.addWidget(IconLabel("check-circle", "accent", 16))
        icon_column.addStretch(1)
        layout.addLayout(icon_column)
        body = label(f"<b>Recomendação:</b> {text}", wrap=True, selectable=True)
        layout.addWidget(body, 1)
        box.setLayout(layout)
        return box
