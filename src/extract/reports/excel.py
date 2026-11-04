"""Excel export: one workbook with the inventory of every machine of a client.

Sheets:
- "Inventário": one row per machine, grouped by department, with the fields a technician
  asks for first (Windows version, memory and modules, system disk and its health, IP,
  DHCP or fixed address, MAC);
- "Por grupo": machine count and the main totals per department, for presenting;
- "Memória", "Discos" and "Rede": one row per module, disk and network adapter;
- "Achados" and "Desempenho": only when the reports hold analysis or benchmark data.

Each sheet is a plain table with a styled header, frozen header row and autofilter, so the
technician can sort and filter without reformatting anything.
"""

from __future__ import annotations

import logging
from collections.abc import Sequence
from datetime import datetime
from pathlib import Path
from typing import Any

from openpyxl import Workbook
from openpyxl.styles import Alignment, Border, Font, PatternFill, Side
from openpyxl.utils import get_column_letter
from openpyxl.worksheet.worksheet import Worksheet

from extract.core.models import DiskInfo, MachineReport, Severity, Status
from extract.reports.summary import (
    SEVERITY_COLORS,
    STATUS_COLORS,
    disk_health,
    disk_type,
    group_label,
    health_label,
    ip_mode,
    modules_label,
    primary_adapter,
    sorted_findings,
    system_disk,
    windows_edition,
    windows_feature_version,
)

log = logging.getLogger(__name__)

_HEADER_FILL = PatternFill("solid", fgColor="1F3A5F")
_HEADER_FONT = Font(bold=True, color="FFFFFF")
_BORDER = Border(bottom=Side(style="thin", color="D0D7E2"))
_WRAP = Alignment(wrap_text=True, vertical="top")
_TOP = Alignment(vertical="top")
_MAX_WIDTH = 60

# Column headers per sheet; columns listed in _WRAPPED hold sentences and wrap.
_INVENTORY_COLUMNS = [
    "Grupo",
    "Computador",
    "Usuário",
    "Fabricante",
    "Modelo",
    "Nº de série",
    "Windows",
    "Versão",
    "Build",
    "Processador",
    "Memória total (GB)",
    "Tipo de memória",
    "Pentes instalados",
    "Slots (em uso/total)",
    "Pentes",
    "Disco do sistema",
    "Tipo do disco",
    "Tamanho do disco (GB)",
    "Saúde do disco",
    "Temperatura do disco (°C)",
    "Desgaste do disco (%)",
    "Livre em C: (GB)",
    "IP",
    "Máscara",
    "Gateway",
    "DHCP ou fixo",
    "MAC",
    "Placa de rede",
    "Data do inventário",
]
_GROUP_COLUMNS = [
    "Grupo",
    "Máquinas",
    "Windows 11",
    "Windows 10",
    "Outro Windows",
    "Memória média (GB)",
    "Até 4 GB de memória",
    "Disco SSD",
    "Disco HDD",
    "Discos com alerta",
    "IP fixo",
    "DHCP",
]
_MEMORY_COLUMNS = [
    "Grupo",
    "Computador",
    "Slot",
    "Capacidade (GB)",
    "Tipo",
    "Velocidade (MT/s)",
    "Fabricante",
    "Modelo do pente",
]
_DISK_COLUMNS = [
    "Grupo",
    "Computador",
    "Disco",
    "Disco do sistema",
    "Tipo",
    "Tamanho (GB)",
    "Saúde",
    "Temperatura (°C)",
    "Desgaste (%)",
    "Horas ligado",
    "Erros não corrigidos",
    "Nº de série",
]
_NETWORK_COLUMNS = [
    "Grupo",
    "Computador",
    "Placa de rede",
    "MAC",
    "IP",
    "Máscara",
    "Gateway",
    "DNS",
    "DHCP ou fixo",
    "Velocidade (Mbps)",
]
_FINDING_COLUMNS = [
    "Grupo",
    "Computador",
    "Gravidade",
    "Área",
    "Achado",
    "Detalhes",
    "Recomendação",
]
_BENCHMARK_COLUMNS = [
    "Grupo",
    "Computador",
    "Teste",
    "Área",
    "Métrica",
    "Valor",
    "Unidade",
    "Duração (s)",
    "Erro",
]
_WRAPPED = {"Detalhes", "Recomendação", "Erro"}

# Disk health labels colored like the health statuses.
_HEALTH_STATUS = {"Saudável": Status.OK, "Atenção": Status.WARNING, "Com falha": Status.CRITICAL}


def export_excel(reports: Sequence[MachineReport], path: Path) -> Path:
    """Write the consolidated workbook to `path` and return it."""
    reports = sorted(reports, key=lambda r: (group_label(r).casefold(), r.hostname.casefold()))
    workbook = Workbook()
    inventory = workbook.active
    inventory.title = "Inventário"
    _fill(inventory, _INVENTORY_COLUMNS, [_inventory_row(r) for r in reports])
    _color_health(inventory, _INVENTORY_COLUMNS.index("Saúde do disco"))

    groups = workbook.create_sheet("Por grupo")
    _fill(groups, _GROUP_COLUMNS, _group_rows(reports))

    memory = workbook.create_sheet("Memória")
    _fill(memory, _MEMORY_COLUMNS, [row for r in reports for row in _memory_rows(r)])

    disks = workbook.create_sheet("Discos")
    _fill(disks, _DISK_COLUMNS, [row for r in reports for row in _disk_rows(r)])
    _color_health(disks, _DISK_COLUMNS.index("Saúde"))

    network = workbook.create_sheet("Rede")
    _fill(network, _NETWORK_COLUMNS, [row for r in reports for row in _network_rows(r)])

    finding_rows = [row for r in reports for row in _finding_rows(r)]
    if finding_rows:
        findings = workbook.create_sheet("Achados")
        _fill(findings, _FINDING_COLUMNS, finding_rows)
        _color_severity(findings, _FINDING_COLUMNS.index("Gravidade"))

    benchmark_rows = [row for r in reports for row in _benchmark_rows(r)]
    if benchmark_rows:
        benchmarks = workbook.create_sheet("Desempenho")
        _fill(benchmarks, _BENCHMARK_COLUMNS, benchmark_rows)

    path.parent.mkdir(parents=True, exist_ok=True)
    workbook.save(path)
    log.info("Excel report saved to %s", path)
    return path


def export_machine_excel(
    report: MachineReport, sections: Sequence[tuple[str, Sequence[tuple[str, str]]]], path: Path
) -> Path:
    """One machine, laid out like the Hardware tab: a block of key/value rows per section."""
    workbook = Workbook()
    sheet = workbook.active
    sheet.title = "Máquina"
    title_font = Font(bold=True, size=14, color="1F3A5F")
    key_font = Font(bold=True, color="5B6573")
    sheet.append([report.hostname])
    sheet["A1"].font = title_font
    info = [
        ("Cliente", report.client),
        ("Grupo", group_label(report)),
        ("Data do inventário", _parse_date(report.created_at)),
    ]
    for key, value in info:
        sheet.append([key, value])
    for cell, value_cell in sheet.iter_rows(min_row=2, max_row=sheet.max_row, max_col=2):
        cell.font = key_font
        if isinstance(value_cell.value, datetime):
            value_cell.number_format = "dd/mm/yyyy hh:mm"
    for title, rows in sections:
        sheet.append([])
        sheet.append([title])
        header = sheet.cell(row=sheet.max_row, column=1)
        for column in (1, 2):
            cell = sheet.cell(row=sheet.max_row, column=column)
            cell.fill = _HEADER_FILL
            cell.font = _HEADER_FONT
        header.alignment = Alignment(vertical="center")
        shown = [(k, v) for k, v in rows if v] or [("", "Sem dados coletados")]
        for key, value in shown:
            sheet.append([key, value])
            row = sheet.max_row
            sheet.cell(row=row, column=1).font = key_font
            sheet.cell(row=row, column=1).alignment = _TOP
            sheet.cell(row=row, column=2).alignment = _WRAP
            for column in (1, 2):
                sheet.cell(row=row, column=column).border = _BORDER
    for row in sheet.iter_rows():
        for cell in row:
            if cell.data_type == "f":  # text from the machine never becomes a formula
                cell.data_type = "s"
                cell.quotePrefix = True
    sheet.column_dimensions["A"].width = 34
    sheet.column_dimensions["B"].width = 80
    path.parent.mkdir(parents=True, exist_ok=True)
    workbook.save(path)
    log.info("Machine Excel saved to %s", path)
    return path


def _inventory_row(report: MachineReport) -> list[Any]:
    inv = report.inventory
    system, memory = inv.system, inv.memory
    disk = system_disk(report) or (inv.disks[0] if inv.disks else None)
    adapter = primary_adapter(report)
    volume = next((v for v in inv.volumes if v.letter.upper() == "C:"), None)
    return [
        group_label(report),
        report.hostname,
        system.user,
        system.manufacturer,
        system.model,
        system.serial_number,
        windows_edition(system),
        windows_feature_version(system),
        system.os_build,
        inv.cpu.name,
        memory.total_gb or None,
        memory.memory_type,
        memory.used_slots or None,
        f"{memory.used_slots}/{memory.total_slots}" if memory.total_slots else "",
        modules_label(report),
        disk.model if disk else "",
        disk_type(disk),
        disk.size_gb if disk and disk.size_gb else None,
        disk_health(disk),
        disk.temperature_c if disk else None,
        disk.wear_percent if disk else None,
        volume.free_gb if volume else None,
        ", ".join(adapter.ipv4) if adapter else "",
        ", ".join(adapter.subnet_masks) if adapter else "",
        ", ".join(adapter.gateway) if adapter else "",
        ip_mode(adapter),
        adapter.mac_address if adapter else "",
        adapter.name if adapter else "",
        _parse_date(report.created_at),
    ]


def _group_rows(reports: Sequence[MachineReport]) -> list[list[Any]]:
    by_group: dict[str, list[MachineReport]] = {}
    for report in reports:
        by_group.setdefault(group_label(report), []).append(report)
    rows = []
    for group, members in by_group.items():
        names = [windows_edition(r.inventory.system) for r in members]
        memory = [r.inventory.memory.total_gb for r in members if r.inventory.memory.total_gb]
        disks = [system_disk(r) for r in members]
        adapters = [primary_adapter(r) for r in members]
        win11 = sum("Windows 11" in n for n in names)
        win10 = sum("Windows 10" in n for n in names)
        rows.append(
            [
                group,
                len(members),
                win11,
                win10,
                len(members) - win11 - win10,
                round(sum(memory) / len(memory), 1) if memory else None,
                sum(gb <= 4 for gb in memory),
                sum(d is not None and d.media_type == "SSD" for d in disks),
                sum(d is not None and d.media_type == "HDD" for d in disks),
                sum(d is not None and _disk_alert(d) for d in disks),
                sum(a is not None and not a.dhcp for a in adapters),
                sum(a is not None and a.dhcp for a in adapters),
            ]
        )
    return rows


def _disk_alert(disk: DiskInfo) -> bool:
    return disk_health(disk) not in {"Saudável", "Indisponível"}


def _memory_rows(report: MachineReport) -> list[list[Any]]:
    return [
        [
            group_label(report),
            report.hostname,
            m.slot,
            m.capacity_gb or None,
            m.memory_type,
            (m.configured_speed_mhz or m.speed_mhz) or None,
            m.manufacturer,
            m.part_number,
        ]
        for m in report.inventory.memory.modules
    ]


def _disk_rows(report: MachineReport) -> list[list[Any]]:
    return [
        [
            group_label(report),
            report.hostname,
            d.model,
            "Sim" if d.is_system_disk else "Não",
            disk_type(d),
            d.size_gb or None,
            health_label(d.health_status) or "Indisponível",
            d.temperature_c,
            d.wear_percent,
            d.power_on_hours,
            d.uncorrected_errors,
            d.serial_number,
        ]
        for d in report.inventory.disks
    ]


def _network_rows(report: MachineReport) -> list[list[Any]]:
    return [
        [
            group_label(report),
            report.hostname,
            a.name,
            a.mac_address,
            ", ".join(a.ipv4),
            ", ".join(a.subnet_masks),
            ", ".join(a.gateway),
            ", ".join(a.dns_servers),
            ip_mode(a),
            a.link_speed_mbps or None,
        ]
        for a in report.inventory.network
    ]


def _finding_rows(report: MachineReport) -> list[list[Any]]:
    return [
        [
            group_label(report),
            report.hostname,
            f.severity.label,
            f.category.label,
            f.title,
            f.detail,
            f.recommendation,
        ]
        for f in sorted_findings(report)
    ]


def _benchmark_rows(report: MachineReport) -> list[list[Any]]:
    rows: list[list[Any]] = []
    for bench in report.benchmarks:
        duration = round(bench.duration_s, 1) if bench.duration_s else None
        if not bench.metrics:
            label = bench.category.label
            rows.append(
                [
                    group_label(report),
                    report.hostname,
                    bench.title,
                    label,
                    "",
                    None,
                    "",
                    duration,
                    bench.error,
                ]
            )
        for metric in bench.metrics.values():
            rows.append(
                [
                    group_label(report),
                    report.hostname,
                    bench.title,
                    bench.category.label,
                    metric.label,
                    metric.value,
                    metric.unit,
                    duration,
                    bench.error,
                ]
            )
    return rows


def _parse_date(iso: str) -> datetime | str:
    """Excel has no time zones: keep the local wall-clock time of the scan."""
    try:
        return datetime.fromisoformat(iso).replace(tzinfo=None)
    except ValueError:
        return iso


def _fill(sheet: Worksheet, headers: list[str], rows: Sequence[Sequence[Any]]) -> None:
    sheet.append(headers)
    for cell in sheet[1]:
        cell.fill = _HEADER_FILL
        cell.font = _HEADER_FONT
        cell.alignment = Alignment(vertical="center", wrap_text=True)
    for row in rows:
        sheet.append(list(row))

    for index, header in enumerate(headers, start=1):
        alignment = _WRAP if header in _WRAPPED else _TOP
        for (cell,) in sheet.iter_rows(min_row=2, min_col=index, max_col=index):
            cell.alignment = alignment
            cell.border = _BORDER
            if cell.data_type == "f":
                # Report text can come from the client's machine (device names, startup
                # entries) or from an edited JSON file: never let it become a live formula.
                cell.data_type = "s"
                cell.quotePrefix = True
            elif isinstance(cell.value, datetime):
                cell.number_format = "dd/mm/yyyy hh:mm"
            elif isinstance(cell.value, float):
                cell.number_format = "#,##0.0"
        sheet.column_dimensions[get_column_letter(index)].width = _width(sheet, index, header)

    sheet.row_dimensions[1].height = 30
    sheet.freeze_panes = "C2"
    sheet.auto_filter.ref = sheet.dimensions


def _width(sheet: Worksheet, column: int, header: str) -> float:
    longest = len(header)
    for (value,) in sheet.iter_rows(min_row=2, min_col=column, max_col=column, values_only=True):
        if isinstance(value, datetime):
            longest = max(longest, 16)
        elif value is not None:
            longest = max(longest, len(str(value)))
    return min(longest + 3, _MAX_WIDTH)


def _color_severity(sheet: Worksheet, column_index: int) -> None:
    colors = {severity.label: SEVERITY_COLORS[severity] for severity in Severity}
    for (cell,) in sheet.iter_rows(min_row=2, min_col=column_index + 1, max_col=column_index + 1):
        if cell.value in colors:
            text, background = colors[cell.value]
            cell.fill = PatternFill("solid", fgColor=background)
            cell.font = Font(bold=True, color=text)


def _color_health(sheet: Worksheet, column_index: int) -> None:
    column = column_index + 1
    for (cell,) in sheet.iter_rows(min_row=2, min_col=column, max_col=column):
        value = str(cell.value or "")
        status = _HEALTH_STATUS.get(value.split(" (")[0])
        if value and status is None:
            status = Status.UNKNOWN
        elif status is Status.OK and "(" in value:
            status = Status.WARNING  # healthy for Windows, but SMART counters show a problem
        if status is not None:
            text, background = STATUS_COLORS[status]
            cell.fill = PatternFill("solid", fgColor=background)
            cell.font = Font(bold=True, color=text)
