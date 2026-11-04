from __future__ import annotations

import re
import sys
from datetime import datetime

import pytest
from openpyxl import load_workbook

from extract.core.models import (
    BenchmarkResult,
    Category,
    DiskInfo,
    Finding,
    GpuInfo,
    HealthCheck,
    MachineReport,
    MemoryModule,
    Metric,
    NetworkAdapter,
    Severity,
    Status,
    VolumeInfo,
)
from extract.reports import export_excel, export_pdf
from extract.reports import paths as report_paths
from extract.reports.summary import format_metric, format_number, inventory_rows


def _machine(hostname: str, *, slow_disk: bool) -> MachineReport:
    report = MachineReport(
        client="Padaria Pão & Cia", created_at="2026-10-19T14:30:00-03:00", tool_version="2.0.0"
    )
    inv = report.inventory
    inv.system.hostname = hostname
    inv.system.os_name = "Microsoft Windows 10 Pro"
    inv.system.os_version = "22H2"
    inv.system.os_build = "19045.4291"
    inv.system.boot_mode = "UEFI"
    inv.cpu.name = "Intel(R) Core(TM) i3-7100 CPU @ 3.90GHz"
    inv.cpu.cores, inv.cpu.logical_processors, inv.cpu.base_clock_mhz = 2, 4, 3912
    inv.memory.total_gb, inv.memory.total_slots, inv.memory.memory_type = 4.0, 2, "DDR4"
    inv.memory.modules = [
        MemoryModule("DIMM1", 4.0, 2400, 2133, "Kingston", "KVR24N17S6/4", "DDR4")
    ]
    inv.disks = [
        DiskInfo(
            "WDC WD5000AAKX",
            465.8,
            "HDD" if slow_disk else "SSD",
            "SATA",
            "",
            "Healthy",
            is_system_disk=True,
        )
    ]
    inv.volumes = [VolumeInfo("C:", "", "NTFS", 465.2, 18.4)]
    inv.gpus = [GpuInfo("Intel(R) HD Graphics 630", 1024, "31.0.101.2111", "2022-08-01")]
    inv.network = [NetworkAdapter("Ethernet", "00:11:22:33:44:55", ["192.168.0.10"], dhcp=True)]

    report.health = [
        HealthCheck(
            "storage.free_space",
            Category.STORAGE,
            "Espaço livre",
            Status.CRITICAL,
            "Disco C: com 4% livre.",
        ),
        HealthCheck(
            "system.uptime", Category.SYSTEM, "Tempo ligado", Status.OK, "Ligado há 1 dia."
        ),
        HealthCheck("system.antivirus", Category.SYSTEM, "Antivírus", Status.UNKNOWN, "Sem dados."),
    ]
    report.benchmarks = [
        BenchmarkResult(
            "storage.sequential",
            Category.STORAGE,
            "Disco: leitura e gravação sequencial",
            {
                "read_mb_s": Metric(98.4, "MB/s", "Leitura sequencial"),
                "write_mb_s": Metric(87.12, "MB/s", "Gravação sequencial"),
            },
            duration_s=21.37,
        ),
        BenchmarkResult("cpu.multi", Category.CPU, "Processador", error="Teste cancelado"),
    ]
    if slow_disk:
        report.findings = [
            Finding(
                "storage.hdd_system",
                Category.STORAGE,
                Severity.CRITICAL,
                "Windows instalado em HD mecânico",
                "O disco do sistema é um HD de 7200 rpm <lento> & antigo.",
                "Trocar por um SSD de 240 GB ou mais.",
            ),
            Finding(
                "memory.low",
                Category.MEMORY,
                Severity.WARNING,
                "Pouca memória RAM",
                "4 GB de RAM para o Windows 10.",
                "Adicionar um módulo de 4 GB DDR4.",
            ),
            Finding("info", Category.SYSTEM, Severity.INFO, "Sem dados de antivírus", "", ""),
        ]
    return report


@pytest.fixture
def reports() -> list[MachineReport]:
    return [_machine("CAIXA-01", slow_disk=True), _machine("ESCRITORIO", slow_disk=False)]


def test_format_number_uses_brazilian_separators():
    assert format_number(1234.5) == "1.234,5"
    assert format_number(16.0) == "16"
    assert format_metric(Metric(98.4, "MB/s", "")) == "98,4 MB/s"
    assert format_metric(Metric(0.123, "ms", "")) == "0,12 ms"


def test_inventory_rows_describe_hardware(reports):
    rows = {component: (name, details) for component, name, details in inventory_rows(reports[0])}
    assert rows["Disco do sistema"] == ("WDC WD5000AAKX", "HDD SATA · 465,8 GB · Saudável")
    assert rows["Memória"][0] == "4 GB DDR4 (1 de 2 slots)"
    assert "18,4 GB livres" in rows["Unidade C:"][1]


def _rows(sheet) -> list[dict]:
    header = [c.value for c in sheet[1]]
    return [
        dict(zip(header, row, strict=True)) for row in sheet.iter_rows(min_row=2, values_only=True)
    ]


def test_excel_export(tmp_path, reports):
    reports[0].group = "Recepção"
    reports[1].group = "Financeiro"
    path = export_excel(reports, tmp_path / "saida" / "relatorio.xlsx")
    workbook = load_workbook(path)
    assert workbook.sheetnames == [
        "Inventário",
        "Por grupo",
        "Memória",
        "Discos",
        "Rede",
        "Achados",
        "Desempenho",
    ]

    inventory = workbook["Inventário"]
    escritorio, caixa = _rows(inventory)  # sorted by group: Financeiro before Recepção
    assert (caixa["Grupo"], caixa["Nome da máquina"]) == ("Recepção", "CAIXA-01")
    assert escritorio["Grupo"] == "Financeiro"
    assert caixa["Windows"] == "Windows 10 Pro"
    assert caixa["Versão"] == "22H2"
    assert caixa["Build"] == "19045.4291"
    assert caixa["Memória total (GB)"] == 4.0
    assert caixa["Pentes instalados"] == 1
    assert caixa["Slots (em uso/total)"] == "1/2"
    assert caixa["Pentes"] == "4 GB"
    assert caixa["Tipo do disco"] == "HDD SATA"
    assert caixa["Tamanho do disco (GB)"] == 465.8
    assert caixa["Saúde do disco"] == "Saudável"
    assert caixa["IP"] == "192.168.0.10"
    assert caixa["DHCP ou fixo"] == "DHCP"
    assert caixa["MAC"] == "00:11:22:33:44:55"
    assert caixa["Data do inventário"] == datetime(2026, 10, 19, 14, 30)
    assert inventory.freeze_panes == "C2"
    health = inventory.cell(row=3, column=list(caixa).index("Saúde do disco") + 1)
    assert health.fill.fgColor.rgb.endswith("DDF3E4")

    groups = {row["Grupo"]: row for row in _rows(workbook["Por grupo"])}
    assert groups["Recepção"]["Máquinas"] == 1
    assert groups["Recepção"]["Windows 10"] == 1
    assert groups["Recepção"]["Disco HDD"] == 1
    assert groups["Financeiro"]["Disco SSD"] == 1
    assert groups["Financeiro"]["DHCP"] == 1

    assert [r["Capacidade (GB)"] for r in _rows(workbook["Memória"])] == [4.0, 4.0]
    disks = _rows(workbook["Discos"])
    assert disks[0]["Disco do sistema"] == "Sim"
    network = _rows(workbook["Rede"])
    assert network[0]["MAC"] == "00:11:22:33:44:55"

    findings = workbook["Achados"]
    assert findings.max_row == 4
    assert [findings.cell(row=r, column=3).value for r in (2, 3, 4)] == [
        "Crítico",
        "Atenção",
        "Informativo",
    ]

    performance = workbook["Desempenho"]
    rows = list(performance.iter_rows(min_row=2, values_only=True))
    assert any(row[2] == "Disco: leitura e gravação sequencial" and row[5] == 98.4 for row in rows)
    assert any(row[-1] == "Teste cancelado" for row in rows)


def test_excel_inventory_only_shows_smart_problems_and_fixed_ip(tmp_path):
    report = _machine("PC-01", slow_disk=False)
    report.health, report.benchmarks, report.findings = [], [], []
    disk = report.inventory.disks[0]
    disk.temperature_c, disk.wear_percent, disk.power_on_hours, disk.uncorrected_errors = (
        45,
        82,
        20000,
        3,
    )
    report.inventory.system.os_name = "Microsoft Windows 11 Pro"
    report.inventory.system.os_version = "24H2"
    report.inventory.network = [
        NetworkAdapter(
            "Wi-Fi",
            "66:77:88:99:AA:BB",
            ["10.0.0.8"],
            ["255.0.0.0"],
            dhcp=True,
        ),
        NetworkAdapter(
            "Ethernet",
            "00:11:22:33:44:55",
            ["192.168.0.20"],
            ["255.255.255.0"],
            ["192.168.0.1"],
            dhcp=False,
        ),
    ]
    workbook = load_workbook(export_excel([report], tmp_path / "inv.xlsx"))
    assert workbook.sheetnames == ["Inventário", "Por grupo", "Memória", "Discos", "Rede"]
    (row,) = _rows(workbook["Inventário"])
    assert row["Grupo"] == "Sem grupo"
    assert (row["Windows"], row["Versão"]) == ("Windows 11 Pro", "24H2")
    assert row["Saúde do disco"] == "Saudável (3 erros não corrigidos, desgaste 82%)"
    assert row["Desgaste do disco (%)"] == 82
    # The adapter with a gateway is the one in use.
    assert (row["IP"], row["Máscara"], row["Gateway"]) == (
        "192.168.0.20",
        "255.255.255.0",
        "192.168.0.1",
    )
    assert row["DHCP ou fixo"] == "Fixo (estático)"
    (disk_row,) = _rows(workbook["Discos"])
    assert disk_row["Horas ligado"] == 20000
    (group,) = _rows(workbook["Por grupo"])
    assert group["Discos com alerta"] == 1
    assert group["Windows 11"] == 1
    assert group["IP fixo"] == 1


def test_excel_export_with_no_reports(tmp_path):
    path = export_excel([], tmp_path / "vazio.xlsx")
    assert load_workbook(path)["Inventário"].max_row == 1


def _page_count(data: bytes) -> int:
    return len(re.findall(rb"/Type\s*/Page(?!s)", data))


def test_pdf_export(tmp_path, reports):
    path = export_pdf(reports, tmp_path / "relatorio.pdf")
    data = path.read_bytes()
    assert data.startswith(b"%PDF")
    assert _page_count(data) >= 3  # cover + one section per machine


def test_pdf_export_single_machine_without_findings(tmp_path):
    report = _machine("SOZINHO", slow_disk=False)
    report.client = ""
    report.health = []
    report.benchmarks = []
    path = export_pdf([report], tmp_path / "um.pdf")
    assert path.read_bytes().startswith(b"%PDF")


def test_default_reports_root_from_source(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    monkeypatch.delattr(sys, "frozen", raising=False)
    assert report_paths.client_folder("") == tmp_path / "reports" / "sem-cliente"
    assert report_paths.client_folder("Pão & Cia") == tmp_path / "reports" / "Pao-Cia"


def test_default_reports_root_when_frozen(tmp_path, monkeypatch):
    monkeypatch.setattr(sys, "frozen", True, raising=False)
    monkeypatch.setattr(sys, "executable", str(tmp_path / "Extract.exe"))
    assert report_paths.app_dir() == tmp_path.resolve()
    assert report_paths.default_reports_root() == tmp_path.resolve() / "Relatorios"


def test_exports_handle_an_empty_report(tmp_path):
    empty = [MachineReport()]
    assert export_pdf(empty, tmp_path / "vazio.pdf").read_bytes().startswith(b"%PDF")
    assert load_workbook(export_excel(empty, tmp_path / "vazio.xlsx"))["Inventário"].max_row == 2


def test_default_reports_root_falls_back_when_read_only(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    monkeypatch.delattr(sys, "frozen", raising=False)
    monkeypatch.setattr(report_paths, "_is_writable", lambda folder: False)
    monkeypatch.setattr(report_paths.Path, "home", lambda: tmp_path / "home")
    assert report_paths.default_reports_root() == tmp_path / "home" / "Documents" / "Extract"


# --- Hardening against hostile names and edited files ---------------------------------


@pytest.mark.parametrize(
    ("name", "expected"),
    [
        ("CON", "_CON"),
        ("nul.txt", "_nul.txt"),
        ("COM1", "_COM1"),
        ("../../x", "x"),
        ("..", "unnamed"),
    ],
)
def test_safe_filename_blocks_traversal_and_device_names(name, expected):
    from extract.reports.storage import safe_filename

    assert safe_filename(name) == expected
    assert len(safe_filename("a" * 500)) <= 80


def test_excel_never_writes_report_text_as_formula(tmp_path):
    report = _machine("PC-01", slow_disk=True)
    report.group = '=HYPERLINK("http://example.invalid","x")'
    path = export_excel([report], tmp_path / "out.xlsx")

    cell = load_workbook(path)["Inventário"]["A2"]
    assert cell.data_type == "s"
    assert cell.value == report.group


@pytest.mark.parametrize(
    "content",
    [
        "[1]",
        '{"inventory": []}',
        '{"inventory": {"system": {"hostname": 5}}}',
        '{"findings": {"x": 1}}',
        "[" * 100_000,
    ],
    ids=["list", "wrong-section-type", "wrong-field-type", "dict-for-list", "deep-nesting"],
)
def test_load_report_rejects_malformed_files(tmp_path, content):
    from extract.reports import load_report
    from extract.reports.storage import load_folder

    path = tmp_path / "PC_2026-10-19_143000.json"
    path.write_text(content, encoding="utf-8")
    with pytest.raises(ValueError):
        load_report(path)
    assert load_folder(tmp_path) == []
