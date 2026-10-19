"""Desempenho tab: benchmark metrics as value/unit, with bars against a reference PC."""

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QGridLayout, QWidget

from extract.core.models import BenchmarkResult, Category, Metric
from extract.gui import formatting
from extract.gui.icons import IconLabel
from extract.gui.theme import Space
from extract.gui.widgets.card import Card
from extract.gui.widgets.common import hbox, label, scroll_area, vbox
from extract.gui.widgets.empty_state import EmptyState
from extract.gui.widgets.metric_bar import MetricBar
from extract.gui.widgets.status_chip import StatusChip

# Typical values of a current office desktop with a SATA SSD (100% of the bar).
REFERENCES: dict[tuple[str, str], float] = {
    ("cpu.single", "score"): 1000,
    ("cpu.multi", "score"): 6000,
    ("cpu.sustained", "start_score"): 6000,
    ("cpu.sustained", "end_score"): 6000,
    ("memory.bandwidth", "read_gb_s"): 15,
    ("memory.bandwidth", "write_gb_s"): 15,
    ("memory.bandwidth", "copy_gb_s"): 15,
    ("storage.sequential", "read_mb_s"): 500,
    ("storage.sequential", "write_mb_s"): 450,
    ("storage.random", "read_iops"): 6000,
    ("storage.random", "write_iops"): 6000,
}
# Test parameters rather than results: shown in one small line under the bars.
DETAIL_KEYS = {"workers", "buffer_mb", "file_mb", "uncached", "median_round_s"}
CATEGORY_ICONS = {Category.CPU: "cpu", Category.MEMORY: "memory", Category.STORAGE: "disk"}
REFERENCE_NOTE = (
    "As barras comparam cada resultado com um PC de escritório atual com SSD SATA "
    "(barra cheia = referência)."
)
LABEL_WIDTH = 150
VALUE_WIDTH = 84
COLUMNS = 2


def performance_view(benchmarks: list[BenchmarkResult]) -> QWidget:
    if not benchmarks:
        return EmptyState(
            "gauge",
            "Sem testes de desempenho",
            "Este diagnóstico foi feito sem os testes de CPU, memória e disco.",
        )
    content = QWidget()
    column = vbox(Space.M, (0, Space.L, Space.S, Space.L))
    column.addWidget(label(REFERENCE_NOTE, role="muted", wrap=True))
    grid = QGridLayout()
    grid.setSpacing(Space.M)
    for index, result in enumerate(benchmarks):
        grid.addWidget(BenchmarkCard(result), index // COLUMNS, index % COLUMNS)
    for col in range(COLUMNS):
        grid.setColumnStretch(col, 1)
    column.addLayout(grid)
    column.addStretch(1)
    content.setLayout(column)
    return scroll_area(content)


def reference_fraction(result: BenchmarkResult, key: str) -> float | None:
    """Share of the reference value reached by a metric, or None when it has no bar."""
    reference = REFERENCES.get((result.id, key))
    if not reference:
        return None
    return result.metrics[key].value / reference


def fraction_tone(fraction: float) -> str:
    if fraction >= 0.7:
        return "ok"
    return "warning" if fraction >= 0.35 else "critical"


def metric_text(key: str, metric: Metric) -> str:
    if key == "uncached":
        return "Sim" if metric.value else "Não"
    return formatting.with_unit(metric.value, metric.unit)


class BenchmarkCard(Card):
    def __init__(self, result: BenchmarkResult, parent: QWidget | None = None) -> None:
        super().__init__(padding=Space.L + 4, spacing=Space.M, parent=parent)
        head = hbox(Space.S + 2)
        head.addWidget(IconLabel(CATEGORY_ICONS.get(result.category, "gauge"), "accent", 18))
        head.addWidget(label(result.title, role="section"), 1)
        if result.duration_s:
            duration = f"{formatting.number(result.duration_s, 0)} s"
            head.addWidget(label(f"Duração {duration}", role="caption"))
        self.body.addLayout(head)
        if result.error:
            row = hbox(Space.S)
            row.addWidget(StatusChip("Falhou", "critical"), 0, Qt.AlignmentFlag.AlignTop)
            row.addWidget(label(result.error, role="muted", wrap=True), 1)
            self.body.addLayout(row)
        else:
            self._add_metrics(result)
        self.body.addStretch(1)

    def _add_metrics(self, result: BenchmarkResult) -> None:
        grid = QGridLayout()
        grid.setHorizontalSpacing(Space.L)
        grid.setVerticalSpacing(Space.S + 2)
        grid.setColumnMinimumWidth(0, LABEL_WIDTH)
        grid.setColumnStretch(1, 1)
        details: list[str] = []
        row = 0
        for key, metric in result.metrics.items():
            fraction = reference_fraction(result, key)
            if fraction is None:
                if key in DETAIL_KEYS:
                    details.append(f"{metric.label}: {metric_text(key, metric)}")
                    continue
                bar = None
            else:
                bar = MetricBar(fraction, fraction_tone(fraction))
                bar.setToolTip(f"{formatting.number(fraction * 100, 0)}% da referência")
            grid.addWidget(label(metric.label, role="muted"), row, 0)
            if bar is not None:
                grid.addWidget(bar, row, 1)
            value = label(metric_text(key, metric), role="strong")
            value.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
            value.setMinimumWidth(VALUE_WIDTH)
            grid.addWidget(value, row, 2)
            row += 1
        self.body.addLayout(grid)
        if details:
            self.body.addWidget(label("  ·  ".join(details), role="caption", wrap=True))
