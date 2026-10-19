"""Prominent banner with the scan's overall verdict."""

from __future__ import annotations

from PySide6.QtWidgets import QFrame, QWidget

from extract.core.models import Finding, Severity
from extract.gui.icons import IconLabel
from extract.gui.theme import SEVERITY_TONES, Space
from extract.gui.widgets.common import hbox, label, set_tone, vbox

VERDICT_PREFIX = "verdict."
_ICONS = {
    "ok": "check-circle",
    "info": "info",
    "warning": "alert-triangle",
    "critical": "alert-octagon",
}


def find_verdict(findings: list[Finding]) -> Finding | None:
    return next((f for f in findings if f.id.startswith(VERDICT_PREFIX)), None)


class VerdictBanner(QFrame):
    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setProperty("card", True)
        row = hbox(Space.L, (Space.XL, Space.L, Space.XL, Space.L))
        self.icon = IconLabel("info", "info", 22, badge=True)
        icon_column = vbox()
        icon_column.addWidget(self.icon)
        icon_column.addStretch(1)
        row.addLayout(icon_column)
        texts = vbox(Space.XS)
        self.eyebrow = label("VEREDITO", role="eyebrow")
        texts.addWidget(self.eyebrow)
        self.title = label("", role="headline", wrap=True)
        texts.addWidget(self.title)
        self.detail = label("", wrap=True, selectable=True)
        texts.addWidget(self.detail)
        row.addLayout(texts, 1)
        self.setLayout(row)

    def show_findings(self, findings: list[Finding]) -> None:
        verdict = find_verdict(findings)
        if verdict is not None:
            tone = "ok" if verdict.id == f"{VERDICT_PREFIX}ok" else SEVERITY_TONES[verdict.severity]
            text = verdict.recommendation or verdict.detail
            self._show(tone, verdict.title, text)
            return
        worst = max(findings, key=lambda f: f.severity.rank, default=None)
        if worst is None or worst.severity is Severity.INFO:
            self._show("ok", "Nenhum problema relevante encontrado", "A máquina está saudável.")
        else:
            self._show(SEVERITY_TONES[worst.severity], worst.title, worst.recommendation)

    def _show(self, tone: str, title: str, detail: str) -> None:
        set_tone(self, tone)
        set_tone(self.eyebrow, tone)
        self.icon.set_icon(_ICONS[tone], tone)
        self.title.setText(title)
        self.detail.setText(detail)
        self.detail.setVisible(bool(detail))
