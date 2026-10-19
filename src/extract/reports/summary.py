"""Formatting shared by the Excel and PDF exports.

Both exports describe the same machines in the same words, so the Portuguese labels,
number formats and colors live here instead of being repeated in each format.
"""

from __future__ import annotations

from collections import Counter
from collections.abc import Iterable
from datetime import datetime

from extract.core.models import (
    DiskInfo,
    Finding,
    MachineReport,
    Metric,
    Severity,
    Status,
    SystemInfo,
)

NO_CLIENT = "Sem cliente"

# (text, background) hex colors, without "#", readable when printed in grayscale too.
SEVERITY_COLORS = {
    Severity.CRITICAL: ("9B1C1C", "FDE2E1"),
    Severity.WARNING: ("8A5300", "FFF1C2"),
    Severity.INFO: ("1E4E8C", "E3EEFB"),
}
STATUS_COLORS = {
    Status.OK: ("1F6B3A", "DDF3E4"),
    Status.WARNING: SEVERITY_COLORS[Severity.WARNING],
    Status.CRITICAL: SEVERITY_COLORS[Severity.CRITICAL],
    Status.UNKNOWN: ("555555", "EEEEEE"),
}

_HEALTH_LABELS = {"Healthy": "Saudável", "Warning": "Atenção", "Unhealthy": "Com falha"}
_MEDIA_LABELS = {"Unknown": "Tipo desconhecido"}


def client_label(reports: Iterable[MachineReport]) -> str:
    clients = sorted({r.client for r in reports if r.client})
    return ", ".join(clients) or NO_CLIENT


def format_date(iso: str, with_time: bool = True) -> str:
    """ISO 8601 to the Brazilian format ("19/10/2026 10:00"); unparsable text is kept."""
    try:
        stamp = datetime.fromisoformat(iso)
    except (TypeError, ValueError):
        return iso or ""
    return stamp.strftime("%d/%m/%Y %H:%M" if with_time else "%d/%m/%Y")


def format_number(value: float, decimals: int = 1) -> str:
    """Brazilian number format: "1.234,5"; whole numbers lose the decimals."""
    if float(value).is_integer():
        decimals = 0
    text = f"{value:,.{decimals}f}"
    return text.replace(",", "\x00").replace(".", ",").replace("\x00", ".")


def format_metric(metric: Metric) -> str:
    decimals = 0 if abs(metric.value) >= 100 else 1 if abs(metric.value) >= 10 else 2
    return f"{format_number(metric.value, decimals)} {metric.unit}".strip()


def sorted_findings(report: MachineReport) -> list[Finding]:
    return sorted(report.findings, key=lambda f: f.severity.rank, reverse=True)


def top_finding(report: MachineReport) -> Finding | None:
    findings = sorted_findings(report)
    return findings[0] if findings else None


def severity_counts(report: MachineReport) -> Counter[Severity]:
    return Counter(f.severity for f in report.findings)


def os_label(system: SystemInfo) -> str:
    parts = [system.os_name, system.os_version]
    label = " ".join(p for p in parts if p)
    return f"{label} (build {system.os_build})" if system.os_build else label


def ram_label(report: MachineReport) -> str:
    memory = report.inventory.memory
    if not memory.total_gb:
        return ""
    label = f"{format_number(memory.total_gb)} GB"
    if memory.memory_type:
        label += f" {memory.memory_type}"
    if memory.total_slots:
        label += f" ({memory.used_slots} de {memory.total_slots} slots)"
    return label


def system_disk(report: MachineReport) -> DiskInfo | None:
    return next((d for d in report.inventory.disks if d.is_system_disk), None)


def disk_type(disk: DiskInfo | None) -> str:
    """Short description such as "SSD NVMe" or "HDD SATA", what a technician looks for first."""
    if disk is None:
        return ""
    media = _MEDIA_LABELS.get(disk.media_type, disk.media_type)
    return " ".join(p for p in (media, disk.bus_type) if p)


def health_label(status: str) -> str:
    return _HEALTH_LABELS.get(status, status)


def inventory_rows(report: MachineReport) -> list[tuple[str, str, str]]:
    """(component, name, details) rows describing the machine's hardware."""
    inv = report.inventory
    system, cpu, board = inv.system, inv.cpu, inv.motherboard
    rows = [
        ("Sistema", os_label(system), _join(system.architecture, _boot(system.boot_mode))),
        ("Computador", _join(system.manufacturer, system.model), _serial(system.serial_number)),
        ("Placa-mãe", _join(board.manufacturer, board.product), _bios(system.bios_version)),
        (
            "Processador",
            cpu.name,
            _join(
                f"{cpu.cores} núcleos / {cpu.logical_processors} threads" if cpu.cores else "",
                f"{format_number(cpu.base_clock_mhz / 1000, 2)} GHz" if cpu.base_clock_mhz else "",
            ),
        ),
        ("Memória", ram_label(report), ""),
    ]
    for module in inv.memory.modules:
        speed = module.configured_speed_mhz or module.speed_mhz
        rows.append(
            (
                f"Memória ({module.slot})" if module.slot else "Memória (módulo)",
                _join(module.manufacturer, module.part_number),
                _join(
                    f"{format_number(module.capacity_gb)} GB",
                    module.memory_type,
                    f"{speed} MT/s" if speed else "",
                ),
            )
        )
    for disk in inv.disks:
        rows.append(
            (
                "Disco do sistema" if disk.is_system_disk else "Disco",
                disk.model,
                _join(
                    disk_type(disk),
                    f"{format_number(disk.size_gb)} GB",
                    health_label(disk.health_status),
                ),
            )
        )
    for volume in inv.volumes:
        rows.append(
            (
                f"Unidade {volume.letter}",
                volume.label or volume.filesystem,
                f"{format_number(volume.free_gb)} GB livres de "
                f"{format_number(volume.size_gb)} GB ({format_number(volume.free_percent)}%)",
            )
        )
    for gpu in inv.gpus:
        vram = f"{format_number(gpu.vram_mb / 1024)} GB" if gpu.vram_mb else ""
        rows.append(("Vídeo", gpu.name, _join(vram, _driver(gpu.driver_version))))
    for adapter in inv.network:
        speed = f"{adapter.link_speed_mbps} Mbps" if adapter.link_speed_mbps else ""
        rows.append(
            (
                "Rede",
                adapter.name,
                _join(", ".join(adapter.ipv4), "DHCP" if adapter.dhcp else "IP fixo", speed),
            )
        )
    return [row for row in rows if row[1] or row[2]]


def _join(*parts: str) -> str:
    return " · ".join(p for p in parts if p)


def _boot(mode: str) -> str:
    return f"inicialização {mode}" if mode else ""


def _serial(serial: str) -> str:
    return f"nº de série {serial}" if serial else ""


def _bios(version: str) -> str:
    return f"BIOS {version}" if version else ""


def _driver(version: str) -> str:
    return f"driver {version}" if version else ""
