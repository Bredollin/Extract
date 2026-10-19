"""Scan stages as shown in the steps view, mapped onto `run_scan`'s progress slices."""

from __future__ import annotations

from dataclasses import dataclass

from extract.core.models import Category
from extract.gui.widgets.steps_view import StepState


@dataclass(frozen=True)
class ScanStep:
    key: str
    title: str
    start: float
    end: float


# Slices mirror the sub_progress ranges in core/pipeline.py::run_scan.
INVENTORY = ScanStep("inventory", "Inventário de hardware", 0.0, 0.15)
HEALTH = ScanStep("health", "Saúde do sistema", 0.15, 0.35)
BENCHMARKS = ScanStep("benchmarks", "Testes de desempenho", 0.35, 0.95)
ANALYSIS = ScanStep("analysis", "Análise dos resultados", 0.95, 1.0)
SAVE = ScanStep("save", "Salvar relatório", 1.0, 1.0)
ALL_STEPS = (INVENTORY, HEALTH, BENCHMARKS, ANALYSIS, SAVE)

BENCHMARK_LABELS = {
    Category.CPU: "Processador",
    Category.MEMORY: "Memória",
    Category.STORAGE: "Disco",
}


def benchmarks_title(categories: set[Category]) -> str:
    names = [label for cat, label in BENCHMARK_LABELS.items() if cat in categories]
    return f"{BENCHMARKS.title} ({', '.join(names)})" if names else BENCHMARKS.title


def idle_states(enabled: dict[str, bool]) -> dict[str, StepState]:
    """Every step before the scan starts: pending, or skipped when not selected."""
    return {
        step.key: StepState.PENDING if enabled.get(step.key, True) else StepState.SKIPPED
        for step in ALL_STEPS
    }


def step_states(
    fraction: float, enabled: dict[str, bool], finished: bool = False
) -> dict[str, StepState]:
    """State of every step for an overall progress `fraction` (0..1).

    The step whose slice contains `fraction` is running, earlier enabled steps are done.
    Saving only starts once the scan itself has finished.
    """
    states: dict[str, StepState] = {}
    for step in ALL_STEPS:
        if not enabled.get(step.key, True):
            states[step.key] = StepState.SKIPPED
        elif step is SAVE:
            states[step.key] = StepState.RUNNING if finished else StepState.PENDING
        elif finished or fraction >= step.end:
            states[step.key] = StepState.DONE
        elif fraction >= step.start:
            states[step.key] = StepState.RUNNING
        else:
            states[step.key] = StepState.PENDING
    return states
