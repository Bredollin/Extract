from __future__ import annotations

from typing import Any

import pytest

from conftest import load_fixture
from extract.analysis import analyze
from extract.analysis import reference as ref
from extract.analysis.rules import RULES, Role, Rule, fmt, memory_channel
from extract.core.models import (
    BenchmarkResult,
    Category,
    DiskInfo,
    HealthCheck,
    MachineReport,
    MemoryInfo,
    MemoryModule,
    Metric,
    Severity,
    Status,
    VolumeInfo,
)

CATEGORIES = {
    "storage": Category.STORAGE,
    "memory": Category.MEMORY,
    "cpu": Category.CPU,
    "system": Category.SYSTEM,
    "network": Category.NETWORK,
}


def check(check_id: str, status: Status = Status.OK, summary: str = "", **data: Any):
    return HealthCheck(check_id, CATEGORIES[check_id.split(".")[0]], "", status, summary, data)


def bench(bench_id: str, error: str = "", **metrics: float) -> BenchmarkResult:
    category = {"cpu": Category.CPU, "memory": Category.MEMORY}.get(
        bench_id.split(".")[0], Category.STORAGE
    )
    return BenchmarkResult(
        bench_id, category, "", {k: Metric(v, "", k) for k, v in metrics.items()}, error=error
    )


def report(
    health: list[HealthCheck] | None = None,
    benchmarks: list[BenchmarkResult] | None = None,
    disks: list[DiskInfo] | None = None,
    memory: MemoryInfo | None = None,
    os_name: str = "Microsoft Windows 11 Pro",
    cpu_name: str = "",
) -> MachineReport:
    r = MachineReport()
    r.inventory.system.os_name = os_name
    r.inventory.cpu.name = cpu_name
    r.inventory.disks = disks or []
    r.inventory.memory = memory or MemoryInfo()
    r.health = health or []
    r.benchmarks = benchmarks or []
    return r


def ids(findings) -> list[str]:
    return [f.id for f in findings]


def by_id(findings, finding_id):
    return next(f for f in findings if f.id == finding_id)


SSD = DiskInfo(model="Kingston A400", media_type="SSD", bus_type="SATA", is_system_disk=True)
NVME = DiskInfo(model="WD SN570", media_type="SSD", bus_type="NVMe", is_system_disk=True)
HDD = DiskInfo(model="WDC WD10EZEX", media_type="HDD", bus_type="SATA", is_system_disk=True)
UNKNOWN_DISK = DiskInfo(model="Disco genérico", media_type="Unknown", is_system_disk=True)


def dual(gb: float = 8, rated: int = 3200, configured: int = 3200) -> MemoryInfo:
    modules = [
        MemoryModule("ChannelA-DIMM0", gb / 2, rated, configured, memory_type="DDR4"),
        MemoryModule("ChannelB-DIMM0", gb / 2, rated, configured, memory_type="DDR4"),
    ]
    return MemoryInfo(total_gb=gb, total_slots=2, memory_type="DDR4", modules=modules)


# (description, report, expected finding id, expected severity)
TRIGGERING = [
    ("HD no sistema", report(disks=[HDD]), "storage.system_hdd", Severity.CRITICAL),
    (
        "disco desconhecido com IOPS de HD",
        report(disks=[UNKNOWN_DISK], benchmarks=[bench("storage.random", read_iops=120)]),
        "storage.behaves_like_hdd",
        Severity.WARNING,
    ),
    (
        "saúde Unhealthy",
        report(
            health=[check("storage.health", disks=[{"model": "X", "health_status": "Unhealthy"}])]
        ),
        "storage.disk_failing",
        Severity.CRITICAL,
    ),
    (
        "status do check com erros não corrigidos",
        report(
            health=[
                check(
                    "storage.health",
                    Status.CRITICAL,
                    "X: 12 erros de leitura/gravação não corrigidos.",
                    disks=[{"model": "X", "health_status": "Healthy", "read_errors_total": 400}],
                )
            ]
        ),
        "storage.disk_failing",
        Severity.CRITICAL,
    ),
    (
        "desgaste alto",
        report(health=[check("storage.health", disks=[{"model": "X", "wear_percent": 85}])]),
        "storage.disk_failing",
        Severity.WARNING,
    ),
    (
        "erros de disco no log",
        report(health=[check("system.events", disk_errors=3, window_days=7)]),
        "storage.disk_failing",
        Severity.WARNING,
    ),
    (
        "disco ocupado",
        report(health=[check("storage.activity", busy_percent=99, avg_response_ms=40)]),
        "storage.busy",
        Severity.WARNING,
    ),
    (
        "resposta muito lenta",
        report(health=[check("storage.activity", busy_percent=None, avg_response_ms=300)]),
        "storage.busy",
        Severity.CRITICAL,
    ),
    (
        "pouco espaço",
        report(health=[check("storage.free_space", letter="C:", free_gb=12, free_percent=5.5)]),
        "storage.low_free_space",
        Severity.WARNING,
    ),
    (
        "quase sem espaço",
        report(health=[check("storage.free_space", letter="C:", free_gb=2, free_percent=1)]),
        "storage.low_free_space",
        Severity.CRITICAL,
    ),
    (
        "SSD SATA lento",
        report(
            disks=[SSD],
            benchmarks=[bench("storage.sequential", read_mb_s=120, write_mb_s=90, uncached=1)],
        ),
        "storage.slower_than_expected",
        Severity.WARNING,
    ),
    (
        "NVMe com acesso aleatório lento",
        report(disks=[NVME], benchmarks=[bench("storage.random", read_iops=1500, uncached=1)]),
        "storage.slower_than_expected",
        Severity.WARNING,
    ),
    (
        "4 GB no Windows 11",
        report(memory=MemoryInfo(total_gb=3.9)),
        "memory.low_total",
        Severity.CRITICAL,
    ),
    (
        "6 GB no Windows 10",
        report(memory=MemoryInfo(total_gb=6), os_name="Microsoft Windows 10 Home"),
        "memory.low_total",
        Severity.WARNING,
    ),
    (
        "8 GB no limite",
        report(memory=dual(8), health=[check("memory.pressure", used_percent=91)]),
        "memory.low_total",
        Severity.WARNING,
    ),
    (
        "16 GB no limite",
        report(memory=dual(16), health=[check("memory.pressure", commit_percent=99)]),
        "memory.pressure",
        Severity.CRITICAL,
    ),
    (
        "um pente só",
        report(
            memory=MemoryInfo(
                total_gb=8, total_slots=2, modules=[MemoryModule("DIMM 1", 8, 2666, 2666)]
            )
        ),
        "memory.single_channel",
        Severity.INFO,
    ),
    (
        "dois pentes no mesmo canal e banda baixa",
        report(
            memory=MemoryInfo(
                total_gb=8,
                total_slots=4,
                modules=[MemoryModule("DIMM_A1", 4), MemoryModule("DIMM_A2", 4)],
            ),
            benchmarks=[bench("memory.bandwidth", copy_gb_s=3.2)],
        ),
        "memory.single_channel",
        Severity.WARNING,
    ),
    (
        "memória abaixo do nominal",
        report(memory=dual(16, rated=3200, configured=2133)),
        "memory.below_rated_speed",
        Severity.INFO,
    ),
    (
        "throttling",
        report(
            benchmarks=[bench("cpu.sustained", clock_drop_percent=35, throughput_drop_percent=20)]
        ),
        "cpu.throttling",
        Severity.CRITICAL,
    ),
    (
        "clock baixo sob carga",
        report(
            health=[check("cpu.load", load_percent=70, current_clock_mhz=800, max_clock_mhz=2600)]
        ),
        "cpu.throttling",
        Severity.WARNING,
    ),
    (
        "CPU sempre ocupada",
        report(
            health=[
                check(
                    "cpu.load",
                    load_percent=97,
                    top_processes=[
                        {"name": "Idle", "cpu_percent": 99},
                        {"name": "MsMpEng", "cpu_percent": 60, "memory_mb": 300},
                    ],
                )
            ]
        ),
        "cpu.high_load",
        Severity.WARNING,
    ),
    (
        "CPU muito fraca",
        report(benchmarks=[bench("cpu.single", score=250), bench("cpu.multi", score=700)]),
        "cpu.weak",
        Severity.CRITICAL,
    ),
    (
        "CPU fraca",
        report(benchmarks=[bench("cpu.single", score=500), bench("cpu.multi", score=2500)]),
        "cpu.weak",
        Severity.WARNING,
    ),
    (
        "CPU de entrada pelo nome",
        report(cpu_name="Intel(R) Celeron(R) N4020 CPU @ 1.10GHz"),
        "cpu.weak",
        Severity.INFO,
    ),
    (
        "WHEA",
        report(health=[check("system.events", whea_errors=2, bugchecks=0, window_days=7)]),
        "system.hardware_errors",
        Severity.CRITICAL,
    ),
    (
        "desligamentos inesperados",
        report(health=[check("system.events", unexpected_shutdowns=3)]),
        "system.hardware_errors",
        Severity.WARNING,
    ),
    (
        "muitos programas na inicialização",
        report(health=[check("system.startup", count=25, items=[{"name": "Steam"}])]),
        "system.startup",
        Severity.WARNING,
    ),
    (
        "uptime longo",
        report(health=[check("system.uptime", days=45)]),
        "system.uptime",
        Severity.WARNING,
    ),
    (
        "reinício pendente",
        report(health=[check("system.pending_reboot", pending=True, reasons=["windows_update"])]),
        "system.pending_reboot",
        Severity.INFO,
    ),
    (
        "economia de energia",
        report(
            health=[
                check("system.power_plan", plan_name="Economia de energia", is_power_saver=True)
            ]
        ),
        "system.power_saver",
        Severity.WARNING,
    ),
    (
        "na bateria",
        report(health=[check("system.power_plan", is_power_saver=False, on_battery=True)]),
        "system.on_battery",
        Severity.INFO,
    ),
    (
        "verificação de antivírus",
        report(health=[check("system.antivirus", scan_in_progress=True)]),
        "system.antivirus_scan",
        Severity.WARNING,
    ),
    (
        "dois antivírus",
        report(
            health=[check("system.antivirus", products=["Avast", "McAfee", "Windows Defender"])]
        ),
        "system.multiple_antivirus",
        Severity.WARNING,
    ),
    (
        "dispositivo com erro",
        report(
            health=[check("system.devices", problem_devices=[{"name": "Rede", "error_code": 28}])]
        ),
        "system.problem_devices",
        Severity.WARNING,
    ),
    (
        "programas travando",
        report(health=[check("system.events", app_crashes=25)]),
        "system.app_crashes",
        Severity.INFO,
    ),
    (
        "perda até o roteador",
        report(health=[check("network.connectivity", gateway_ms=3, gateway_loss_percent=40)]),
        "network.local",
        Severity.CRITICAL,
    ),
    (
        "internet lenta",
        report(health=[check("network.connectivity", internet_ms=320, internet_loss_percent=0)]),
        "network.internet",
        Severity.WARNING,
    ),
    (
        "DNS lento",
        report(health=[check("network.connectivity", dns_ms=900)]),
        "network.dns",
        Severity.WARNING,
    ),
    (
        "Wi-Fi fraco",
        report(health=[check("network.wifi", ssid_present=True, signal_percent=25)]),
        "network.wifi",
        Severity.WARNING,
    ),
]

# (description, report, finding id that must NOT appear)
NOT_TRIGGERING = [
    ("SSD no sistema", report(disks=[SSD]), "storage.system_hdd"),
    (
        "disco desconhecido rápido",
        report(disks=[UNKNOWN_DISK], benchmarks=[bench("storage.random", read_iops=8000)]),
        "storage.behaves_like_hdd",
    ),
    (
        "disco saudável",
        report(
            health=[check("storage.health", disks=[{"model": "X", "health_status": "Healthy"}])]
        ),
        "storage.disk_failing",
    ),
    (
        "erros totais sem status de alerta",
        report(
            health=[
                check("storage.health", disks=[{"model": "X", "read_errors_total": 500}]),
                check("system.events", disk_errors=0),
            ]
        ),
        "storage.disk_failing",
    ),
    (
        "disco tranquilo",
        report(health=[check("storage.activity", busy_percent=12, avg_response_ms=3)]),
        "storage.busy",
    ),
    (
        "espaço suficiente",
        report(health=[check("storage.free_space", free_gb=180, free_percent=38)]),
        "storage.low_free_space",
    ),
    (
        "SSD SATA normal",
        report(
            disks=[SSD],
            benchmarks=[
                bench("storage.sequential", read_mb_s=520, write_mb_s=450, uncached=1),
                bench("storage.random", read_iops=7000, uncached=1),
            ],
        ),
        "storage.slower_than_expected",
    ),
    (
        "resultado com cache não é julgado",
        report(disks=[SSD], benchmarks=[bench("storage.sequential", read_mb_s=50, uncached=0)]),
        "storage.slower_than_expected",
    ),
    ("8 GB sem pressão", report(memory=dual(8)), "memory.low_total"),
    (
        "Windows 7 com 4 GB",
        report(memory=MemoryInfo(total_gb=4), os_name="Windows 7"),
        "memory.low_total",
    ),
    (
        "8 GB no limite vai para low_total, não pressure",
        report(memory=dual(8), health=[check("memory.pressure", used_percent=91)]),
        "memory.pressure",
    ),
    ("dual channel", report(memory=dual(16)), "memory.single_channel"),
    (
        "notebook com um único slot",
        report(memory=MemoryInfo(total_gb=8, total_slots=1, modules=[MemoryModule("DIMM 0", 8)])),
        "memory.single_channel",
    ),
    ("memória na velocidade", report(memory=dual(16)), "memory.below_rated_speed"),
    (
        "clock estável",
        report(
            benchmarks=[bench("cpu.sustained", clock_drop_percent=3, throughput_drop_percent=5)]
        ),
        "cpu.throttling",
    ),
    ("CPU ociosa", report(health=[check("cpu.load", load_percent=8)]), "cpu.high_load"),
    (
        "CPU forte",
        report(benchmarks=[bench("cpu.single", score=1100), bench("cpu.multi", score=7000)]),
        "cpu.weak",
    ),
    (
        "nome fraco mas benchmark bom",
        report(cpu_name="Intel Celeron", benchmarks=[bench("cpu.single", score=900)]),
        "cpu.weak",
    ),
    ("Pentium Gold pelo nome", report(cpu_name="Intel(R) Pentium(R) Gold 7505"), "cpu.weak"),
    (
        "log limpo",
        report(health=[check("system.events", whea_errors=0, bugchecks=0, unexpected_shutdowns=1)]),
        "system.hardware_errors",
    ),
    ("poucos programas", report(health=[check("system.startup", count=4)]), "system.startup"),
    ("reiniciado ontem", report(health=[check("system.uptime", days=1)]), "system.uptime"),
    (
        "sem reinício pendente",
        report(health=[check("system.pending_reboot", pending=False)]),
        "system.pending_reboot",
    ),
    (
        "plano equilibrado",
        report(health=[check("system.power_plan", is_power_saver=False)]),
        "system.power_saver",
    ),
    (
        "Defender + um antivírus",
        report(health=[check("system.antivirus", products=["Windows Defender", "Avast"])]),
        "system.multiple_antivirus",
    ),
    (
        "sem dispositivos com erro",
        report(health=[check("system.devices", problem_devices=[])]),
        "system.problem_devices",
    ),
    (
        "roteador ignora ping",
        report(
            health=[
                check(
                    "network.connectivity",
                    gateway_ms=None,
                    gateway_loss_percent=None,
                    internet_ms=20,
                )
            ]
        ),
        "network.local",
    ),
    (
        "rede boa",
        report(health=[check("network.connectivity", internet_ms=25, dns_ms=15)]),
        "network.dns",
    ),
    (
        "Wi-Fi forte",
        report(health=[check("network.wifi", signal_percent=90, link_speed_mbps=433)]),
        "network.wifi",
    ),
]


@pytest.mark.parametrize(
    ("description", "machine", "finding_id", "severity"),
    TRIGGERING,
    ids=[t[0] for t in TRIGGERING],
)
def test_rule_triggers(description, machine, finding_id, severity):
    findings = analyze(machine)
    found = by_id(findings, finding_id)
    assert found.severity is severity
    assert found.title and found.detail and found.recommendation
    assert found.evidence


@pytest.mark.parametrize(
    ("description", "machine", "finding_id"),
    NOT_TRIGGERING,
    ids=[t[0] for t in NOT_TRIGGERING],
)
def test_rule_does_not_trigger(description, machine, finding_id):
    assert finding_id not in ids(analyze(machine))


def test_empty_report_gives_only_ok_verdict():
    findings = analyze(MachineReport())
    assert ids(findings) == ["verdict.ok"]
    assert findings[0].severity is Severity.INFO


def test_missing_and_garbage_data_is_tolerated():
    keys = {
        "storage.health": ["disks"],
        "storage.free_space": ["letter", "size_gb", "free_gb", "free_percent"],
        "storage.activity": ["busy_percent", "avg_queue_length", "avg_response_ms"],
        "memory.pressure": ["used_percent", "commit_percent", "hard_faults_per_s"],
        "cpu.load": ["load_percent", "current_clock_mhz", "max_clock_mhz", "top_processes"],
        "system.startup": ["count", "items"],
        "system.events": ["disk_errors", "whea_errors", "bugchecks", "app_crashes"],
        "system.antivirus": ["products", "scan_in_progress"],
        "system.devices": ["problem_devices"],
        "network.connectivity": ["gateway_ms", "internet_ms", "dns_ms"],
    }
    unknown = [check(i, Status.UNKNOWN, **dict.fromkeys(k)) for i, k in keys.items()]
    garbage = [
        check("memory.pressure", used_percent="muito"),
        check("cpu.load", load_percent=99, top_processes=["x", {"name": None}]),
        check("storage.health", disks="sem dados"),
    ]
    failed = [bench(b, error="Falha no teste") for b in ("cpu.single", "storage.random")]
    machine = report(health=unknown + garbage, benchmarks=failed, os_name="")

    findings = analyze(machine)
    assert ids(findings)[0].startswith("verdict.")
    assert "cpu.weak" not in ids(findings)  # failed benchmark gives no score


def test_crashing_rule_is_skipped(monkeypatch):
    def broken(ctx):
        raise ZeroDivisionError

    monkeypatch.setattr("extract.analysis.RULES", [Rule(broken, Role.OTHER), *RULES])
    assert "storage.system_hdd" in ids(analyze(report(disks=[HDD])))


def test_findings_sorted_by_severity_then_priority():
    machine = report(
        disks=[HDD],
        memory=MemoryInfo(total_gb=3.9),
        health=[
            check("system.startup", count=12),
            check("system.power_plan", is_power_saver=True),
            check("system.events", whea_errors=1),
        ],
    )
    findings = analyze(machine)
    assert findings[0].id.startswith("verdict.")
    ranks = [f.severity.rank for f in findings[1:]]
    assert ranks == sorted(ranks, reverse=True)
    critical = [f.id for f in findings[1:] if f.severity is Severity.CRITICAL]
    assert critical == ["storage.system_hdd", "memory.low_total", "system.hardware_errors"]
    assert ids(findings)[-1] == "system.startup"


# --- verdict -------------------------------------------------------------------------


def test_verdict_upgrade_lists_parts():
    findings = analyze(report(disks=[HDD], memory=MemoryInfo(total_gb=4)))
    verdict = findings[0]
    assert verdict.id == "verdict.upgrade"
    assert verdict.title == "Upgrade recomendado: SSD + 8 GB de RAM"
    assert verdict.severity is Severity.CRITICAL
    assert verdict.evidence["upgrades"] == ["SSD", "8 GB de RAM"]


def test_verdict_upgrade_mentions_software_fixes():
    machine = report(disks=[HDD], health=[check("system.power_plan", is_power_saver=True)])
    verdict = analyze(machine)[0]
    assert verdict.id == "verdict.upgrade"
    assert "plano de energia" in verdict.detail.lower()


def test_verdict_software_when_hardware_is_fine():
    machine = report(
        disks=[NVME],
        memory=dual(16),
        health=[
            check("system.startup", count=30),
            check("system.antivirus", scan_in_progress=True),
        ],
    )
    verdict = analyze(machine)[0]
    assert verdict.id == "verdict.software"
    assert verdict.title == "Problema de software, não de hardware"


def test_verdict_network_only():
    machine = report(disks=[SSD], health=[check("network.connectivity", dns_ms=800)])
    assert analyze(machine)[0].id == "verdict.network"


def test_verdict_fault_comes_before_upgrades():
    machine = report(
        disks=[HDD],
        health=[check("storage.health", disks=[{"model": "HD", "health_status": "Unhealthy"}])],
    )
    verdict = analyze(machine)[0]
    assert verdict.id == "verdict.fault"
    assert "SSD" in verdict.detail


def test_verdict_replace_for_very_weak_cpu():
    machine = report(disks=[SSD], benchmarks=[bench("cpu.single", score=200)])
    assert analyze(machine)[0].id == "verdict.replace"


def test_verdict_replace_for_weak_cpu_needing_two_upgrades():
    machine = report(
        disks=[HDD], memory=MemoryInfo(total_gb=4), benchmarks=[bench("cpu.single", score=500)]
    )
    verdict = analyze(machine)[0]
    assert verdict.id == "verdict.replace"
    assert "SSD + 8 GB de RAM" in verdict.detail


def test_weak_cpu_with_one_upgrade_still_recommends_upgrade():
    machine = report(disks=[HDD], benchmarks=[bench("cpu.single", score=500)])
    assert analyze(machine)[0].id == "verdict.upgrade"


def test_info_findings_do_not_drive_verdict():
    machine = report(health=[check("system.uptime", days=10)])
    findings = analyze(machine)
    assert findings[0].id == "verdict.ok"
    assert findings[0].severity is Severity.INFO
    assert "system.uptime" in ids(findings)


def test_recorded_slow_machine_fixture():
    machine = MachineReport.from_dict(load_fixture("analysis_slow_hdd_machine.json"))
    findings = analyze(machine)
    assert findings[0].title == "Upgrade recomendado: SSD + 8 GB de RAM"
    assert "sobrecarregado" not in findings[0].detail  # the SSD already explains it
    assert {"storage.system_hdd", "memory.low_total", "storage.busy"} <= set(ids(findings))


# --- helpers -----------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("slot", "channel"),
    [
        ("ChannelA-DIMM0", "A"),
        ("Channel B DIMM 1", "B"),
        ("DIMM_A2", "A"),
        ("B1", "B"),
        ("DIMM 1", None),
        ("BANK 0", None),
    ],
)
def test_memory_channel(slot, channel):
    assert memory_channel(slot) == channel


def test_fmt_uses_brazilian_separators():
    assert fmt(1234.5, 1) == "1.234,5"
    assert fmt(3.0) == "3"


def test_pending_reboot_reasons_are_translated():
    machine = report(health=[check("system.pending_reboot", pending=True, reasons=["file_rename"])])
    assert (
        "arquivos aguardando substituição"
        in by_id(analyze(machine), "system.pending_reboot").detail
    )


def test_low_free_space_falls_back_to_inventory():
    machine = report()
    machine.inventory.volumes = [VolumeInfo(letter="C:", size_gb=100, free_gb=3)]
    assert by_id(analyze(machine), "storage.low_free_space").severity is Severity.CRITICAL


def test_reference_disk_expectations_are_ordered():
    hdd, sata, nvme = (ref.DISK_EXPECTATIONS[k] for k in ("hdd", "sata_ssd", "nvme"))
    assert hdd.min_random_read_iops < sata.min_random_read_iops < nvme.min_random_read_iops
