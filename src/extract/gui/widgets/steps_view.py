"""Vertical list of scan stages with pending / running / done / failed indicators."""

from __future__ import annotations

from enum import Enum

from PySide6.QtCore import QRectF, QSize, Qt, QTimer
from PySide6.QtGui import QPainter, QPen
from PySide6.QtWidgets import QSizePolicy, QWidget

from extract.gui import theme
from extract.gui.icons import paint_icon
from extract.gui.theme import Space
from extract.gui.widgets.common import ElidedLabel, hbox, label, set_tone, vbox

_DOT = 22


class StepState(str, Enum):
    PENDING = "pending"
    RUNNING = "running"
    DONE = "done"
    FAILED = "failed"
    SKIPPED = "skipped"

    @property
    def label(self) -> str:
        return _STATE_LABELS[self]

    @property
    def tone(self) -> str:
        return _STATE_TONES[self]


_STATE_LABELS = {
    StepState.PENDING: "Aguardando",
    StepState.RUNNING: "Em andamento",
    StepState.DONE: "Concluído",
    StepState.FAILED: "Falhou",
    StepState.SKIPPED: "Não selecionado",
}
_STATE_TONES = {
    StepState.PENDING: "text_muted",
    StepState.RUNNING: "accent",
    StepState.DONE: "ok",
    StepState.FAILED: "critical",
    StepState.SKIPPED: "text_muted",
}


class StepIndicator(QWidget):
    """The round marker plus the connector lines that join consecutive steps."""

    def __init__(self, first: bool, last: bool, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._first, self._last = first, last
        self._state = StepState.PENDING
        self._angle = 0
        self._spin = QTimer(self)
        self._spin.setInterval(60)
        self._spin.timeout.connect(self._advance)
        self.setFixedWidth(_DOT + 2)
        self.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Expanding)

    def set_state(self, state: StepState) -> None:
        self._state = state
        if state is StepState.RUNNING:
            self._spin.start()
        else:
            self._spin.stop()
        self.update()

    def _advance(self) -> None:
        self._angle = (self._angle + 24) % 360
        self.update()

    def sizeHint(self) -> QSize:
        return QSize(_DOT + 2, _DOT + Space.L)

    def paintEvent(self, event) -> None:
        palette = theme.palette()
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        cx = self.width() / 2
        dot = QRectF(cx - _DOT / 2, 2, _DOT, _DOT)
        line_color = palette.color("ok" if self._state is StepState.DONE else "border")
        painter.setPen(QPen(palette.color("border"), 2))
        if not self._first:
            painter.drawLine(int(cx), 0, int(cx), int(dot.top()) - 1)
        if not self._last:
            painter.setPen(QPen(line_color, 2))
            painter.drawLine(int(cx), int(dot.bottom()) + 3, int(cx), self.height())
        self._paint_dot(painter, dot)

    def _paint_dot(self, painter: QPainter, dot: QRectF) -> None:
        palette = theme.palette()
        state = self._state
        if state in (StepState.DONE, StepState.FAILED):
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(palette.color(state.tone))
            painter.drawEllipse(dot)
            glyph = dot.adjusted(5, 5, -5, -5)
            paint_icon(painter, glyph, "check" if state is StepState.DONE else "x", "surface")
            return
        if state is StepState.RUNNING:
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(palette.color("accent_soft"))
            painter.drawEllipse(dot)
            arc_pen = QPen(palette.color("accent"), 2.5)
            arc_pen.setCapStyle(Qt.PenCapStyle.RoundCap)
            painter.setPen(arc_pen)
            painter.drawArc(dot.adjusted(2, 2, -2, -2), -self._angle * 16, 100 * 16)
            painter.setBrush(palette.color("accent"))
            painter.setPen(Qt.PenStyle.NoPen)
            painter.drawEllipse(dot.center(), 3.5, 3.5)
            return
        pen = QPen(palette.color("border_strong"), 2)
        if state is StepState.SKIPPED:
            pen.setStyle(Qt.PenStyle.DotLine)
        painter.setPen(pen)
        painter.setBrush(palette.color("surface"))
        painter.drawEllipse(dot.adjusted(1, 1, -1, -1))


class StepRow(QWidget):
    def __init__(self, title: str, first: bool, last: bool, parent: QWidget | None = None):
        super().__init__(parent)
        self.state = StepState.PENDING
        row = hbox(Space.M)
        self.indicator = StepIndicator(first, last)
        row.addWidget(self.indicator)
        texts = vbox(2, (0, 2, 0, 0 if last else Space.L))
        head = hbox(Space.S)
        self.title = label(title, role="strong")
        head.addWidget(self.title, 1)
        self.state_label = label(StepState.PENDING.label, role="caption")
        head.addWidget(self.state_label)
        texts.addLayout(head)
        self.detail = ElidedLabel("")
        self.detail.setProperty("role", "caption")
        self.detail.setVisible(False)
        texts.addWidget(self.detail)
        texts.addStretch(1)
        row.addLayout(texts, 1)
        self.setLayout(row)

    def set_state(self, state: StepState, detail: str = "") -> None:
        self.state = state
        self.indicator.set_state(state)
        self.state_label.setText(state.label)
        set_tone(self.state_label, state.tone if state is not StepState.PENDING else "")
        self.title.setProperty("role", "strong" if state is not StepState.SKIPPED else "muted")
        set_tone(self.title, "")
        self.detail.setText(detail)
        self.detail.setVisible(bool(detail))


class StepsView(QWidget):
    """Shows a fixed list of steps; `set_states` updates them all at once."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._layout = vbox(0)
        self.setLayout(self._layout)
        self.rows: dict[str, StepRow] = {}

    def set_steps(self, steps: list[tuple[str, str]]) -> None:
        """`steps` is a list of (key, title)."""
        while self._layout.count():
            item = self._layout.takeAt(0)
            if item.widget():
                item.widget().setParent(None)
                item.widget().deleteLater()
        self.rows = {}
        for index, (key, title) in enumerate(steps):
            row = StepRow(title, first=index == 0, last=index == len(steps) - 1)
            self.rows[key] = row
            self._layout.addWidget(row)

    def set_state(self, key: str, state: StepState, detail: str = "") -> None:
        self.rows[key].set_state(state, detail)

    def state(self, key: str) -> StepState:
        return self.rows[key].state
