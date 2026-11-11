"""The "Resumo" of a disk test: the drive's situation in plain words, for anyone to read.

Built only from a finished `DiskTestReport` (pure, no disk access), so the page and the PDF
say exactly the same thing.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from extract.analysis import reference as ref
from extract.core.models import Status
from extract.health.base import fmt

from .models import DiskTestReport

# Health percent at or below these: replace the drive / plan the replacement.
REPLACE_AT_PERCENT = 30
ATTENTION_AT_PERCENT = 60


@dataclass
class Fact:
    title: str
    value: str
    detail: str = ""
    status: Status = Status.OK


@dataclass
class Summary:
    status: Status
    situation: str  # "Bom", "Atenção", "Substituir" or "Sem dados"
    headline: str
    reasons: list[str] = field(default_factory=list)  # what weighs on the situation
    facts: list[Fact] = field(default_factory=list)
    speed: str = ""
    cares: list[str] = field(default_factory=list)  # setup/usage, not a defect
    actions: list[str] = field(default_factory=list)


def time_powered(hours: int) -> str:
    """6520 -> "cerca de 9 meses ligado" (counting 24 h a day)."""
    days = hours / 24
    if days < 1:
        return "menos de 1 dia ligado"
    if days < 60:
        return f"cerca de {fmt(days)} dias ligado"
    if days < 365 * 2:
        return f"cerca de {fmt(days / 30.4)} meses ligado"
    return f"cerca de {fmt(days / 365, 1)} anos ligado"


def _situation(report: DiskTestReport) -> tuple[Status, str, str]:
    health, percent = report.health_status, report.health_percent
    if health is Status.CRITICAL or (percent is not None and percent <= REPLACE_AT_PERCENT):
        return (
            Status.CRITICAL,
            "Substituir",
            "O disco está falhando ou no fim da vida. Faça backup agora e troque o disco.",
        )
    if health is Status.WARNING or (percent is not None and percent <= ATTENTION_AT_PERCENT):
        return (
            Status.WARNING,
            "Atenção",
            "O disco funciona, mas já mostra desgaste ou erros. Faça backup e planeje a troca.",
        )
    if health is Status.UNKNOWN and percent is None:
        return (
            Status.UNKNOWN,
            "Sem dados",
            "Não foi possível ler a saúde do disco, então não dá para dizer se ele está bom.",
        )
    used = (
        ""
        if report.life_left in (None, 100)
        else (f", já usou {100 - report.life_left}% da vida útil")
    )
    return Status.OK, "Bom", f"O disco está saudável{used}. Pode continuar em uso."


def _speed(report: DiskTestReport) -> str:
    read = report.performance.get("read_mb_s")
    write = report.performance.get("write_mb_s")
    if read is None:
        if report.performance_error:
            return f"Não medida: {report.performance_error}"
        return "Não medida (teste só de saúde)."
    measured = f"Leitura {fmt(read.value)} MB/s"
    if write is not None:
        measured += f", gravação {fmt(write.value)} MB/s"
    if report.over_usb:
        link = " (nível de USB 2.0)" if read.value < ref.DISKTEST_USB2_READ_MB_S else ""
        return (
            f"{measured} pelo USB{link}. Essa velocidade é do adaptador e da porta USB, "
            "não do disco, e não conta na avaliação."
        )
    expected = ref.DISK_EXPECTATIONS.get(report.drive.kind or "sata_ssd")
    if report.performance_status is Status.OK or expected is None:
        return f"{measured}: dentro do esperado."
    return (
        f"{measured}: abaixo do esperado para {expected.label} "
        f"(mínimo {fmt(expected.min_seq_read_mb_s)} MB/s de leitura)."
    )


def build(report: DiskTestReport) -> Summary:
    status, situation, headline = _situation(report)
    summary = Summary(status, situation, headline)

    problems = [
        r for r in report.readings
        if r.group == "health" and r.status in (Status.WARNING, Status.CRITICAL)
    ]  # fmt: skip
    problems.sort(key=lambda r: r.status is not Status.CRITICAL)
    summary.reasons = [
        f"{r.label}: {r.value}" + (f" ({r.note})" if r.note else "") for r in problems
    ]

    percent = report.health_percent
    summary.facts.append(
        Fact(
            "Saúde",
            "?" if percent is None else f"{percent}%",
            "vida útil e defeitos do disco" if percent is not None else "SMART não lido",
            status,
        )
    )
    if report.life_left is not None:
        life_status = next((r.status for r in report.readings if r.key == "wear"), Status.OK)
        summary.facts.append(
            Fact("Vida útil restante", f"{report.life_left}%", "do que o fabricante garante",
                 life_status)
        )  # fmt: skip
    if report.power_on_hours is not None:
        summary.facts.append(
            Fact("Tempo ligado", f"{fmt(report.power_on_hours)} h",
                 time_powered(report.power_on_hours))
        )  # fmt: skip
    temperature = next((r for r in report.readings if r.key == "temperature"), None)
    if temperature is not None:
        summary.facts.append(Fact("Temperatura", temperature.value, "agora", temperature.status))

    summary.speed = _speed(report)
    summary.cares = [
        f"{r.label}: {r.value}" + (f" ({r.note})" if r.note else "")
        for r in report.readings
        if r.group == "care" and r.status is not Status.OK
    ]
    summary.cares += [r.note for r in report.readings if r.group == "info" and r.note]
    summary.actions = report.recommendations[:3]
    return summary
