"""Hardware tab: the inventory grouped into readable cards."""

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QGridLayout, QWidget

from extract.core.models import Inventory
from extract.gui import formatting
from extract.gui.icons import IconLabel
from extract.gui.theme import Space
from extract.gui.widgets.card import Card
from extract.gui.widgets.common import hbox, label, scroll_area

Rows = list[tuple[str, str]]


def hardware_view(inventory: Inventory) -> QWidget:
    sections = [
        ("Sistema", "monitor", _system_rows(inventory)),
        ("Processador", "cpu", _cpu_rows(inventory)),
        ("Memória", "memory", _memory_rows(inventory)),
        ("Placa-mãe e vídeo", "board", _board_rows(inventory)),
        ("Armazenamento", "disk", _storage_rows(inventory)),
        ("Rede", "network", _network_rows(inventory)),
    ]
    content = QWidget()
    grid = QGridLayout()
    grid.setContentsMargins(0, Space.L, Space.S, Space.L)
    grid.setSpacing(Space.M)
    for index, (title, icon_name, rows) in enumerate(sections):
        grid.addWidget(_section(title, icon_name, rows), index // 2, index % 2)
    grid.setColumnStretch(0, 1)
    grid.setColumnStretch(1, 1)
    grid.setRowStretch(len(sections) // 2 + 1, 1)
    content.setLayout(grid)
    return scroll_area(content)


def _section(title: str, icon_name: str, rows: Rows) -> Card:
    card = Card(padding=Space.L + 4, spacing=Space.M)
    head = hbox(Space.S + 2)
    head.addWidget(IconLabel(icon_name, "accent", 18))
    head.addWidget(label(title, role="section"), 1)
    card.body.addLayout(head)
    grid = QGridLayout()
    grid.setHorizontalSpacing(Space.L)
    grid.setVerticalSpacing(Space.S)
    grid.setColumnStretch(1, 1)
    shown = [(k, v) for k, v in rows if v] or [("", "Sem dados coletados")]
    for row, (key, value) in enumerate(shown):
        key_label = label(key, role="caption")
        grid.addWidget(key_label, row, 0, Qt.AlignmentFlag.AlignTop)
        grid.addWidget(label(value, wrap=True, selectable=True), row, 1)
    card.body.addLayout(grid)
    card.body.addStretch(1)
    return card


def _system_rows(inv: Inventory) -> Rows:
    s = inv.system
    os_text = " ".join(p for p in (s.os_name, s.os_version) if p)
    return [
        ("Nome", s.hostname),
        ("Fabricante", s.manufacturer),
        ("Modelo", s.model),
        ("Nº de série", s.serial_number),
        ("Sistema", f"{os_text} (build {s.os_build})" if s.os_build else os_text),
        ("Arquitetura", s.architecture),
        ("BIOS", " · ".join(p for p in (s.bios_version, s.boot_mode) if p)),
        ("Último boot", formatting.date_time(s.last_boot) if s.last_boot else ""),
    ]


def _cpu_rows(inv: Inventory) -> Rows:
    c = inv.cpu
    cores = f"{c.cores} núcleos / {c.logical_processors} threads" if c.cores else ""
    cache = (
        f"L2 {c.l2_cache_kb // 1024} MB · L3 {c.l3_cache_kb // 1024} MB" if c.l3_cache_kb else ""
    )
    return [
        ("Modelo", c.name),
        ("Núcleos", cores),
        (
            "Clock base",
            f"{formatting.number(c.base_clock_mhz / 1000, 2)} GHz" if c.base_clock_mhz else "",
        ),
        ("Soquete", c.socket),
        ("Cache", cache),
    ]


def _memory_rows(inv: Inventory) -> Rows:
    m = inv.memory
    rows = [
        (
            "Total",
            f"{formatting.number(m.total_gb)} GB {m.memory_type}".strip() if m.total_gb else "",
        ),
        ("Slots", f"{m.used_slots} de {m.total_slots} em uso" if m.total_slots else ""),
    ]
    for module in m.modules:
        speed = module.configured_speed_mhz or module.speed_mhz
        parts = [f"{formatting.number(module.capacity_gb)} GB", module.memory_type]
        parts += [f"{speed} MHz" if speed else "", module.manufacturer]
        rows.append((module.slot or "Módulo", " · ".join(p for p in parts if p)))
    return rows


def _board_rows(inv: Inventory) -> Rows:
    b = inv.motherboard
    rows = [("Placa-mãe", " ".join(p for p in (b.manufacturer, b.product) if p))]
    for gpu in inv.gpus:
        vram = f"{formatting.number(gpu.vram_mb / 1024)} GB" if gpu.vram_mb >= 1024 else ""
        driver = f"driver {gpu.driver_version}" if gpu.driver_version else ""
        rows.append(("Vídeo", " · ".join(p for p in (gpu.name, vram, driver) if p)))
    return rows


def _storage_rows(inv: Inventory) -> Rows:
    rows: Rows = []
    for disk in inv.disks:
        kind = " ".join(p for p in (disk.media_type, disk.bus_type) if p and p != "Unknown")
        parts = [disk.model, kind, formatting.size_gb(disk.size_gb)]
        if disk.is_system_disk:
            parts.append("disco do sistema")
        rows.append(("Disco", " · ".join(p for p in parts if p)))
    for vol in inv.volumes:
        free = f"{formatting.size_gb(vol.free_gb)} livres de {formatting.size_gb(vol.size_gb)}"
        rows.append((f"Volume {vol.letter}", f"{free} ({formatting.number(vol.free_percent, 0)}%)"))
    return rows


def _network_rows(inv: Inventory) -> Rows:
    rows: Rows = []
    for adapter in inv.network:
        details = [", ".join(adapter.ipv4), "DHCP" if adapter.dhcp else "IP fixo"]
        if adapter.link_speed_mbps:
            details.append(f"{formatting.number(adapter.link_speed_mbps)} Mbps")
        rows.append((adapter.name, " · ".join(p for p in details if p)))
    return rows
