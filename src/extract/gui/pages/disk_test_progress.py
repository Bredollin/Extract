"""Progress panel of the Teste de disco page: big percentage, bar, elapsed time and the
test phases, so the technician can follow a test that takes a minute or more."""

from __future__ import annotations

from PySide6.QtWidgets import QProgressBar, QWidget

from extract.gui import formatting
from extract.gui.theme import Space
from extract.gui.widgets.card import Card
from extract.gui.widgets.common import ElidedLabel, divider, hbox, label, set_tone
from extract.gui.widgets.steps_view import StepState, StepsView

HEALTH = "health"
# (key, title, words of the progress messages that belong to the phase)
SPEED_STEPS = (
    ("seq_write", "Gravação sequencial", ("arquivo de teste", "gravação sequencial")),
    ("seq_read", "Leitura sequencial", ("leitura sequencial",)),
    ("rnd_read", "Leitura aleatória 4 KB", ("leitura aleatória",)),
    ("rnd_write", "Gravação aleatória 4 KB", ("gravação aleatória",)),
)


def step_for(message: str) -> str | None:
    """Phase a progress message belongs to (None for the final "concluído" message)."""
    text = message.lower()
    for key, _title, words in SPEED_STEPS:
        if any(word in text for word in words):
            return key
    if "concluído" in text:
        return None
    return HEALTH


class DiskTestProgress(Card):
    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__("Teste em andamento", spacing=Space.M, parent=parent)
        self.subject = label("", role="muted", wrap=True)
        self.body.addWidget(self.subject)
        top = hbox(Space.M)
        self.percent = label("0%", role="title")
        top.addWidget(self.percent)
        top.addStretch(1)
        self.elapsed = label("0:00", role="headline")
        self.elapsed.setToolTip("Tempo decorrido")
        top.addWidget(self.elapsed)
        self.body.addLayout(top)
        self.bar = QProgressBar()
        self.bar.setRange(0, 1000)
        self.bar.setTextVisible(False)
        self.bar.setFixedHeight(14)
        self.body.addWidget(self.bar)
        self.status = ElidedLabel("")
        self.status.setProperty("role", "muted")
        self.body.addWidget(self.status)
        self.body.addWidget(divider())
        self.steps = StepsView()
        self.body.addWidget(self.steps)
        self.body.addStretch(1)
        self._order: list[str] = []
        self._current: str | None = None

    def start(self, subject: str, benchmarking: bool) -> None:
        steps = [(HEALTH, "Saúde e SMART (só leitura)")]
        if benchmarking:
            steps += [(key, title) for key, title, _words in SPEED_STEPS]
        self._order = [key for key, _title in steps]
        self.steps.set_steps(steps)
        self.subject.setText(subject)
        self._current = None
        self.update(0.0, "Iniciando…")
        self.tick(0.0)

    def update(self, fraction: float, message: str) -> None:
        fraction = min(max(fraction, 0.0), 1.0)
        self.bar.setValue(int(fraction * 1000))
        self.percent.setText(f"{fraction * 100:.0f}%")
        self.status.setText(message)
        set_tone(self.status, "")
        key = step_for(message) if message != "Iniciando…" else HEALTH
        if key is None or key not in self._order:
            return
        index = self._order.index(key)
        for position, other in enumerate(self._order):
            if position < index:
                self.steps.set_state(other, StepState.DONE)
            elif position == index:
                self.steps.set_state(other, StepState.RUNNING)
        self._current = key

    def tick(self, elapsed_s: float, warning: str = "") -> None:
        minutes, seconds = divmod(int(elapsed_s), 60)
        self.elapsed.setText(f"{minutes}:{seconds:02d}")
        if warning:
            self.status.setText(warning)
            set_tone(self.status, "warning")

    def fail(self, message: str) -> None:
        if self._current is not None:
            self.steps.set_state(self._current, StepState.FAILED)
        self.status.setText(message)
        set_tone(self.status, "critical")

    @property
    def summary(self) -> str:
        done = sum(1 for k in self._order if self.steps.state(k) is StepState.DONE)
        return formatting.plural(done, "etapa concluída", "etapas concluídas")
