"""Right card of the Diagnóstico page: live steps, progress, elapsed time and log."""

from __future__ import annotations

from PySide6.QtCore import QElapsedTimer, QTimer, Signal
from PySide6.QtWidgets import QProgressBar, QWidget

from extract.core.models import Category
from extract.gui import formatting, scan_steps
from extract.gui.icons import IconLabel
from extract.gui.scan_steps import ALL_STEPS, BENCHMARKS, HEALTH, idle_states, step_states
from extract.gui.theme import Space
from extract.gui.widgets.card import Card
from extract.gui.widgets.common import ElidedLabel, button, divider, hbox, label, set_tone
from extract.gui.widgets.log_panel import LogPanel
from extract.gui.widgets.steps_view import StepState, StepsView

IDLE_MESSAGE = "Pronto para começar"


class ScanProgressCard(Card):
    cancel_requested = Signal()

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent=parent)
        self._enabled: dict[str, bool] = {}
        self._fraction = 0.0
        self._clock = QElapsedTimer()
        self._ticker = QTimer(self)
        self._ticker.setInterval(1000)
        self._ticker.timeout.connect(self._tick)

        head = hbox(Space.S)
        head.addWidget(label("Andamento", role="section"), 1)
        head.addWidget(IconLabel("clock", "text_muted", 16))
        self.elapsed = label("00:00", role="muted")
        head.addWidget(self.elapsed)
        head.addSpacing(Space.S)
        self.cancel_button = button("Cancelar", "x", "danger")
        self.cancel_button.clicked.connect(self._on_cancel)
        self.cancel_button.setVisible(False)
        head.addWidget(self.cancel_button)
        self.body.addLayout(head)
        self.body.addSpacing(Space.S)

        self.steps = StepsView()
        self.body.addWidget(self.steps)
        self.body.addStretch(1)

        status = hbox(Space.S)
        self.message = ElidedLabel(IDLE_MESSAGE)
        self.message.setProperty("role", "muted")
        status.addWidget(self.message, 1)
        self.percent = label("0%", role="strong")
        status.addWidget(self.percent)
        self.body.addLayout(status)
        self.bar = QProgressBar()
        self.bar.setRange(0, 1000)
        self.bar.setTextVisible(False)
        self.body.addWidget(self.bar)
        self.body.addSpacing(Space.XS)
        self.body.addWidget(divider())
        self.log = LogPanel()
        self.body.addWidget(self.log)
        self.reset(True, {Category.CPU, Category.MEMORY, Category.STORAGE})

    def reset(self, health: bool, benchmarks: set[Category]) -> None:
        """Show every step as pending for the chosen options."""
        self._enabled = {HEALTH.key: health, BENCHMARKS.key: bool(benchmarks)}
        titles = {BENCHMARKS.key: scan_steps.benchmarks_title(benchmarks)}
        self.steps.set_steps([(s.key, titles.get(s.key, s.title)) for s in ALL_STEPS])
        self._apply_states(idle_states(self._enabled))
        self._set_status(0.0, IDLE_MESSAGE, "")

    def start(self, health: bool, benchmarks: set[Category]) -> None:
        self.reset(health, benchmarks)
        self.log.clear()
        self.cancel_button.setVisible(True)
        self.cancel_button.setEnabled(True)
        self._clock.start()
        self._ticker.start()
        self._render_elapsed(0)
        self.update_progress(0.0, "Iniciando…")

    def update_progress(self, fraction: float, message: str) -> None:
        self._fraction = fraction
        states = step_states(fraction, self._enabled)
        self._apply_states(states, message)
        self._set_status(fraction, message, "")

    def mark_saving(self) -> None:
        self._apply_states(
            step_states(1.0, self._enabled, finished=True), "Gravando o arquivo JSON"
        )

    def finish(self, message: str) -> None:
        self._stop()
        states = step_states(1.0, self._enabled, finished=True)
        states[scan_steps.SAVE.key] = StepState.DONE
        self._apply_states(states)
        self._set_status(1.0, message, "ok")

    def fail(self, message: str, cancelled: bool = False) -> None:
        self._stop()
        states = step_states(self._fraction, self._enabled)
        for key, state in states.items():
            if state is StepState.RUNNING:
                self.steps.set_state(key, StepState.FAILED, message)
        self._set_status(self._fraction, message, "warning" if cancelled else "critical")
        if not cancelled:
            self.log.set_expanded(True)

    def show_elapsed(self, seconds: float) -> None:
        """Stop the live clock and show a fixed elapsed time."""
        self._ticker.stop()
        self._render_elapsed(seconds)

    def _apply_states(self, states: dict[str, StepState], detail: str = "") -> None:
        for key, state in states.items():
            self.steps.set_state(key, state, detail if state is StepState.RUNNING else "")

    def _set_status(self, fraction: float, message: str, tone: str) -> None:
        self.bar.setValue(round(fraction * 1000))
        self.percent.setText(f"{round(fraction * 100)}%")
        self.message.setText(message)
        set_tone(self.message, tone)

    def _on_cancel(self) -> None:
        self.cancel_button.setEnabled(False)
        self.message.setText("Cancelando… aguardando a etapa atual terminar")
        self.cancel_requested.emit()

    def _stop(self) -> None:
        self._ticker.stop()
        self.cancel_button.setVisible(False)

    def _tick(self) -> None:
        self._render_elapsed(self._clock.elapsed() / 1000)

    def _render_elapsed(self, seconds: float) -> None:
        self.elapsed.setText(formatting.duration(seconds))
