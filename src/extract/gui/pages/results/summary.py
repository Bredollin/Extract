"""Header pieces of the Resultados page: machine title and summary tiles."""

from __future__ import annotations

import re

from PySide6.QtWidgets import QWidget

from extract.core.models import CpuInfo, MachineReport, MemoryInfo, Severity
from extract.gui import formatting
from extract.gui.theme import Space
from extract.gui.widgets.common import hbox
from extract.gui.widgets.stat_card import StatCard
from extract.gui.widgets.verdict_banner import VERDICT_PREFIX

_CPU_NOISE = re.compile(
    r"\((R|TM)\)|\b(Intel|AMD|CPU|Processor)\b|\b\d+(th|st|nd|rd) Gen\b|@.*$|\d+-Core", re.I
)


def machine_subtitle(report: MachineReport) -> str:
    system = report.inventory.system
    model = " ".join(p for p in (system.manufacturer, system.model) if p)
    os_text = " ".join(p for p in (system.os_name, system.os_version) if p)
    parts = [model, os_text, report.client, formatting.date_time(report.created_at)]
    return "  ·  ".join(p for p in parts if p)


def short_cpu_name(name: str) -> str:
    """`Intel(R) Core(TM) i5-7400 CPU @ 3.00GHz` -> `Core i5-7400`."""
    return " ".join(_CPU_NOISE.sub(" ", name).split())


def severity_count(report: MachineReport, severity: Severity) -> int:
    return sum(
        1 for f in report.findings if f.severity is severity and not f.id.startswith(VERDICT_PREFIX)
    )


def summary_cards(report: MachineReport) -> QWidget:
    inv = report.inventory
    critical = severity_count(report, Severity.CRITICAL)
    warning = severity_count(report, Severity.WARNING)
    memory = inv.memory
    system_disk = next(
        (d for d in inv.disks if d.is_system_disk), inv.disks[0] if inv.disks else None
    )

    cards = [
        StatCard(
            "Críticos",
            str(critical),
            "exigem ação" if critical else "nenhum problema grave",
            "alert-octagon",
            "critical" if critical else "ok",
        ),
        StatCard(
            "Atenção",
            str(warning),
            "pontos a verificar" if warning else "nada a verificar",
            "alert-triangle",
            "warning" if warning else "ok",
        ),
        StatCard(
            "Processador",
            short_cpu_name(inv.cpu.name) or "—",
            _cpu_detail(inv.cpu),
            "cpu",
        ),
        StatCard("Memória", _memory_value(memory), _memory_detail(memory), "memory"),
        StatCard(
            "Disco do sistema",
            f"{system_disk.media_type} {formatting.size_gb(system_disk.size_gb)}"
            if system_disk
            else "—",
            system_disk.model if system_disk else "",
            "disk",
        ),
    ]
    widget = QWidget()
    row = hbox(Space.M)
    for card in cards:
        row.addWidget(card, 1)
    widget.setLayout(row)
    return widget


def _memory_value(memory: MemoryInfo) -> str:
    if not memory.total_gb:
        return "—"
    return f"{formatting.number(memory.total_gb)} GB {memory.memory_type}".strip()


def _memory_detail(memory: MemoryInfo) -> str:
    speed = max((m.configured_speed_mhz or m.speed_mhz for m in memory.modules), default=0)
    parts = [
        f"{memory.used_slots} de {memory.total_slots} slots" if memory.total_slots else "",
        f"{speed} MHz" if speed else "",
    ]
    return " · ".join(p for p in parts if p)


def _cpu_detail(cpu: CpuInfo) -> str:
    vendor = next((v for v in ("Intel", "AMD") if v.lower() in cpu.name.lower()), "")
    cores = f"{cpu.cores} núcleos · {cpu.logical_processors} threads" if cpu.cores else ""
    return " · ".join(p for p in (vendor, cores) if p)
