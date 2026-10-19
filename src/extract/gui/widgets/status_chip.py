"""Pill-shaped status label colored by tone (ok, warning, critical, info, neutral)."""

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QLabel, QSizePolicy, QWidget

from extract.core.models import Severity, Status
from extract.gui.theme import SEVERITY_TONES, STATUS_TONES
from extract.gui.widgets.common import set_tone


class StatusChip(QLabel):
    def __init__(self, text: str = "", tone: str = "neutral", parent: QWidget | None = None):
        super().__init__(text, parent)
        self.setObjectName("Chip")
        self.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Fixed)
        self.set_tone(tone)

    def set_tone(self, tone: str) -> None:
        set_tone(self, tone)

    @classmethod
    def for_status(cls, status: Status) -> StatusChip:
        return cls(status.label, STATUS_TONES[status])

    @classmethod
    def for_severity(cls, severity: Severity) -> StatusChip:
        return cls(severity.label, SEVERITY_TONES[severity])
