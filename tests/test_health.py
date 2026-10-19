from __future__ import annotations

import pytest

from conftest import load_fixture
from extract.core.models import Category, Inventory, Status
from extract.core.powershell import FakePowerShell, PowerShell, PowerShellError
from extract.core.progress import Cancelled, CancelToken
from extract.health import CHECKS, cpu, memory, network, run_health_checks, storage, system
from extract.health.base import UNKNOWN_SUMMARY, fmt, level

SCRIPTS = {
    "storage.health": storage.DISK_HEALTH_SCRIPT,
    "storage.free_space": storage.FREE_SPACE_SCRIPT,
    "storage.activity": storage.ACTIVITY_SCRIPT,
    "memory.pressure": memory.MEMORY_SCRIPT,
    "cpu.load": cpu.CPU_SCRIPT,
    "system.startup": system.STARTUP_SCRIPT,
    "system.uptime": system.UPTIME_SCRIPT,
    "system.events": system.EVENTS_SCRIPT,
    "system.power_plan": system.POWER_SCRIPT,
    "system.antivirus": system.ANTIVIRUS_SCRIPT,
    "system.devices": system.DEVICES_SCRIPT,
    "system.pending_reboot": system.PENDING_REBOOT_SCRIPT,
    "network.connectivity": network.CONNECTIVITY_SCRIPT,
    "network.wifi": network.WIFI_SCRIPT,
}
CHECK_BY_ID = {check.id: check for check in CHECKS}
CONTRACT_KEYS = {
    "storage.health": {"disks"},
    "storage.free_space": {"letter", "size_gb", "free_gb", "free_percent"},
    "storage.activity": {"busy_percent", "avg_queue_length", "avg_response_ms"},
    "memory.pressure": {
        "used_percent",
        "available_mb",
        "commit_percent",
        "hard_faults_per_s",
        "pagefile_used_percent",
    },
    "cpu.load": {"load_percent", "current_clock_mhz", "max_clock_mhz", "top_processes"},
    "system.startup": {"count", "items"},
    "system.uptime": {"days"},
    "system.events": {
        "window_days",
        "disk_errors",
        "whea_errors",
        "unexpected_shutdowns",
        "bugchecks",
        "app_crashes",
    },
    "system.power_plan": {"plan_name", "is_power_saver", "on_battery"},
    "system.antivirus": {"products", "realtime_enabled", "scan_in_progress"},
    "system.devices": {"problem_devices"},
    "system.pending_reboot": {"pending", "reasons"},
    "network.connectivity": {
        "gateway_ms",
        "gateway_loss_percent",
        "internet_ms",
        "internet_loss_percent",
        "dns_ms",
    },
    "network.wifi": {"ssid_present", "signal_percent", "link_speed_mbps"},
}
DISK_KEYS = {
    "model",
    "media_type",
    "health_status",
    "temperature_c",
    "wear_percent",
    "read_errors_total",
    "write_errors_total",
    "power_on_hours",
}


def fake(responses: dict[str, object]) -> FakePowerShell:
    """FakePowerShell keyed by check id: each script is a unique substring of itself."""
    return FakePowerShell({SCRIPTS[check_id]: rows for check_id, rows in responses.items()})


def run(check_id: str, rows: object):
    return CHECK_BY_ID[check_id](fake({check_id: rows}), Inventory())


@pytest.fixture(scope="module")
def normal():
    return load_fixture("health_normal.json")


@pytest.fixture(scope="module")
def bad():
    return load_fixture("health_bad.json")


# --- Whole run ------------------------------------------------------------------------


def test_scripts_are_distinct_so_fake_matching_is_unambiguous():
    for check_id, script in SCRIPTS.items():
        others = [o for o, s in SCRIPTS.items() if o != check_id and script in s]
        assert not others, check_id


def test_run_returns_every_contract_id_when_wired(normal):
    results = run_health_checks(fake(normal), Inventory())
    assert [r.id for r in results] == [c.id for c in CHECKS if c.id != "network.wifi"]
    assert all(r.status is Status.OK for r in results), [
        (r.id, r.summary) for r in results if r.status is not Status.OK
    ]


def test_run_includes_wifi_when_on_wifi(bad):
    results = run_health_checks(fake(bad), Inventory())
    assert {r.id for r in results} == set(SCRIPTS)


@pytest.mark.parametrize("fixture", ["health_normal.json", "health_bad.json"])
def test_data_matches_contract(fixture):
    for result in run_health_checks(fake(load_fixture(fixture)), Inventory()):
        assert set(result.data) == CONTRACT_KEYS[result.id], result.id
        assert result.category is Category(result.id.split(".")[0])
        assert result.title and result.summary.endswith(".")


def test_run_with_failing_powershell_reports_unknown_everywhere():
    ps = FakePowerShell({"": PowerShellError("powershell.exe não encontrado")})
    results = run_health_checks(ps, Inventory())
    # The Wi-Fi check cannot tell whether the machine is on Wi-Fi, so it reports UNKNOWN too.
    assert {r.id for r in results} == set(SCRIPTS)
    for result in results:
        assert result.status is Status.UNKNOWN
        assert result.summary == UNKNOWN_SUMMARY
        assert set(result.data) == CONTRACT_KEYS[result.id]
        assert all(v is None for v in result.data.values())


def test_run_with_empty_output_never_crashes():
    results = run_health_checks(FakePowerShell({}), Inventory())
    by_id = {r.id: r for r in results}
    assert "network.wifi" not in by_id
    assert by_id["storage.free_space"].status is Status.UNKNOWN
    assert by_id["system.devices"].status is Status.OK  # no rows means no problem devices


def test_progress_and_cancel(normal):
    seen: list[tuple[float, str]] = []
    run_health_checks(fake(normal), Inventory(), lambda f, m: seen.append((f, m)))
    assert seen[0] == (0.0, "Verificando: Saúde dos discos")
    assert seen[-1][0] == 1.0
    assert [f for f, _ in seen] == sorted(f for f, _ in seen)

    token = CancelToken()
    ps = fake(normal)
    calls = []

    def cancel_after_first(fraction: float, message: str) -> None:
        calls.append(message)
        token.cancel()

    with pytest.raises(Cancelled):
        run_health_checks(ps, Inventory(), cancel_after_first, token)
    assert len(ps.calls) == 1


def test_unexpected_exception_becomes_unknown():
    class Exploding:
        def query(self, script, timeout=0):
            raise KeyError("boom")

    result = CHECK_BY_ID["cpu.load"](Exploding(), Inventory())
    assert result.status is Status.UNKNOWN
    assert result.summary == "Não foi possível verificar."


# --- Helpers ----------------------------------------------------------------------


def test_fmt_uses_brazilian_separators():
    assert fmt(1234.56, 1) == "1.234,6"
    assert fmt(None) == "?"


def test_level_thresholds_are_inclusive():
    assert level(79.9, 80, 95) is Status.OK
    assert level(80, 80, 95) is Status.WARNING
    assert level(95, 80, 95) is Status.CRITICAL
    assert level(20, 20, 10, below=True) is Status.WARNING
    assert level(10, 20, 10, below=True) is Status.CRITICAL
    assert level(None, 1, 2) is Status.OK


# --- Storage ----------------------------------------------------------------------


def test_disk_health_normal(normal):
    result = run("storage.health", normal["storage.health"])
    assert result.status is Status.OK
    assert result.summary == "1 disco saudável."
    (disk,) = result.data["disks"]
    assert set(disk) == DISK_KEYS
    assert disk["media_type"] == "SSD" and disk["wear_percent"] == 3


def test_disk_health_bad(bad):
    result = run("storage.health", bad["storage.health"])
    assert result.status is Status.CRITICAL  # 118 uncorrected errors
    assert "em alerta" in result.summary
    assert "118 erros de leitura/gravação não corrigidos" in result.summary


def test_disk_health_without_admin_and_numeric_enums():
    rows = [{"Model": "WDC WD10EZEX-08WN4A0", "MediaType": 3, "HealthStatus": 0}]
    result = run("storage.health", rows)
    disk = result.data["disks"][0]
    assert (disk["media_type"], disk["health_status"]) == ("HDD", "Healthy")
    assert disk["temperature_c"] is None and disk["power_on_hours"] is None
    assert result.status is Status.OK
    assert "requer administrador" in result.summary


def test_disk_health_unhealthy_is_critical():
    rows = [{"Model": "KINGSTON SA400S37240G", "MediaType": "SSD", "HealthStatus": "Unhealthy"}]
    assert run("storage.health", rows).status is Status.CRITICAL


@pytest.mark.parametrize(
    ("wear", "status"), [(69, Status.OK), (70, Status.WARNING), (90, Status.CRITICAL)]
)
def test_disk_wear_thresholds(wear, status):
    rows = [{"Model": "SSD", "MediaType": "SSD", "HealthStatus": "Healthy", "Wear": wear}]
    assert run("storage.health", rows).status is status


def test_disk_health_empty_is_unknown():
    assert run("storage.health", []).status is Status.UNKNOWN


def test_free_space_bad_summary(bad):
    result = run("storage.free_space", bad["storage.free_space"])
    assert result.status is Status.CRITICAL
    assert result.summary == "Disco C: com 6% livre (14 GB de 238 GB)."
    assert result.data == {"letter": "C:", "size_gb": 237.9, "free_gb": 14.0, "free_percent": 5.9}


@pytest.mark.parametrize(
    ("free_percent", "status"),
    [(20.1, Status.OK), (20, Status.WARNING), (10.1, Status.WARNING), (10, Status.CRITICAL)],
)
def test_free_space_thresholds(free_percent, status):
    size = 1000 * 1024**3
    rows = [{"DeviceID": "C:", "Size": size, "FreeSpace": size * free_percent / 100}]
    assert run("storage.free_space", rows).status is status


def test_free_space_small_disk_absolute_floor():
    size = 64 * 1024**3
    rows = [{"DeviceID": "C:", "Size": size, "FreeSpace": 14 * 1024**3}]  # 22% but 14 GB
    assert run("storage.free_space", rows).status is Status.WARNING


def test_disk_activity(normal, bad):
    ok = run("storage.activity", normal["storage.activity"])
    assert ok.status is Status.OK
    assert ok.data == {"busy_percent": 3.7, "avg_queue_length": 0.02, "avg_response_ms": 0.8}
    slow = run("storage.activity", bad["storage.activity"])
    assert slow.status is Status.CRITICAL
    assert slow.summary == "Disco ocupado 99% do tempo, fila média 4,8, resposta média 313 ms."


def test_disk_activity_response_warning():
    rows = [{"BusyPercent": 30, "AvgQueueLength": 0.5, "AvgResponseMs": 50}]
    assert run("storage.activity", rows).status is Status.WARNING


# --- Memory -----------------------------------------------------------------------


def test_memory_normal(normal):
    result = run("memory.pressure", normal["memory.pressure"])
    assert result.status is Status.OK
    assert result.data["used_percent"] == 43.9
    assert result.data["pagefile_used_percent"] == 4.9


def test_memory_bad(bad):
    result = run("memory.pressure", bad["memory.pressure"])
    assert result.status is Status.CRITICAL
    assert result.summary.startswith("95% da memória em uso (0,2 GB livres de 3,9 GB)")


def _memory_row(used_percent: float, commit: float, faults: float) -> list[dict]:
    total_kb = 8 * 1024**2
    available_mb = total_kb / 1024 * (100 - used_percent) / 100
    return [
        {
            "TotalVisibleMemoryKB": total_kb,
            "AvailableMBytes": available_mb,
            "PercentCommittedBytesInUse": commit,
            "HardFaultsPerSec": faults,
        }
    ]


@pytest.mark.parametrize(
    ("used", "commit", "faults", "status"),
    [
        (89, 60, 500, Status.OK),  # many hard faults alone are not pressure
        (90, 60, 10, Status.WARNING),
        (70, 90, 10, Status.WARNING),
        (90, 60, 50, Status.CRITICAL),
        (70, 98, 0, Status.CRITICAL),
    ],
)
def test_memory_thresholds(used, commit, faults, status):
    result = run("memory.pressure", _memory_row(used, commit, faults))
    assert result.status is status
    assert result.data["pagefile_used_percent"] is None


# --- CPU --------------------------------------------------------------------------


def test_cpu_normal(normal):
    result = run("cpu.load", normal["cpu.load"])
    assert result.status is Status.OK
    assert result.data["current_clock_mhz"] == 3319
    top = result.data["top_processes"]
    assert top[0] == {"name": "chrome", "cpu_percent": 2.2, "memory_mb": 586}
    assert len(top) == 5


def test_cpu_bad_is_critical_and_throttled(bad):
    result = run("cpu.load", bad["cpu.load"])
    assert result.status is Status.CRITICAL
    assert result.data["current_clock_mhz"] == 912
    assert result.data["top_processes"][0]["name"] == "MsMpEng"
    assert "limitação térmica" in result.summary


def test_cpu_throttling_alone_is_warning():
    rows = [{"LoadPercent": 60, "PerformancePercent": 40, "MaxClockMHz": 3000}]
    assert run("cpu.load", rows).status is Status.WARNING


def test_cpu_falls_back_to_inventory_clock():
    inventory = Inventory()
    inventory.cpu.base_clock_mhz = 2000
    ps = fake({"cpu.load": [{"LoadPercent": 10, "PerformancePercent": 100}]})
    result = CHECK_BY_ID["cpu.load"](ps, inventory)
    assert result.data["max_clock_mhz"] == 2000
    assert result.data["top_processes"] == []


# --- System -----------------------------------------------------------------------


def test_startup_dedupes(normal):
    result = run("system.startup", normal["system.startup"])
    assert result.status is Status.OK
    assert result.data["count"] == 4
    assert result.summary == "4 programas iniciam com o Windows."
    assert set(result.data["items"][0]) == {"name", "command", "location"}


def test_startup_many_is_warning(bad):
    result = run("system.startup", bad["system.startup"])
    assert result.status is Status.WARNING and result.data["count"] == 18


def test_startup_empty_is_ok():
    result = run("system.startup", [])
    assert (result.status, result.data["count"]) == (Status.OK, 0)


@pytest.mark.parametrize(
    ("hours", "status"), [(5, Status.OK), (14 * 24 - 1, Status.OK), (14 * 24, Status.WARNING)]
)
def test_uptime_thresholds(hours, status):
    assert run("system.uptime", [{"UptimeHours": hours}]).status is status


def test_uptime_summaries(normal, bad):
    assert run("system.uptime", normal["system.uptime"]).summary == (
        "Ligado há 1,3 dias desde a última reinicialização."
    )
    assert "Inicialização Rápida" in run("system.uptime", bad["system.uptime"]).summary
    assert run("system.uptime", [{"UptimeHours": 3}]).summary.startswith("Ligado há 3 horas")


def test_events(normal, bad):
    ok = run("system.events", normal["system.events"])
    assert ok.status is Status.OK
    assert ok.summary == "Nos últimos 7 dias: 2 travamentos de programas."
    worse = run("system.events", bad["system.events"])
    assert worse.status is Status.CRITICAL
    assert "14 erros de disco" in worse.summary and "1 tela azul" in worse.summary


def test_events_single_whea_is_warning_and_partial_read():
    rows = [{"WindowDays": 7, "WheaErrors": 1, "DiskErrors": 0, "AppCrashes": None}]
    result = run("system.events", rows)
    assert result.status is Status.WARNING
    assert result.data["app_crashes"] is None
    assert "Parte do log não pôde ser lida." in result.summary


def test_events_unreadable_is_unknown():
    assert run("system.events", [{"WindowDays": 7}]).status is Status.UNKNOWN


def test_power_plan(normal, bad):
    ok = run("system.power_plan", normal["system.power_plan"])
    assert ok.status is Status.OK
    assert ok.data == {"plan_name": "Equilibrado", "is_power_saver": False, "on_battery": False}
    saver = run("system.power_plan", bad["system.power_plan"])
    assert saver.status is Status.WARNING
    assert saver.data["is_power_saver"] and saver.data["on_battery"]


def test_power_plan_without_guid_is_unknown():
    assert run("system.power_plan", [{"SchemeGuid": None}]).status is Status.UNKNOWN


def test_antivirus(normal, bad):
    ok = run("system.antivirus", normal["system.antivirus"])
    assert ok.status is Status.OK
    assert ok.data == {
        "products": ["Windows Defender"],
        "realtime_enabled": True,
        "scan_in_progress": False,
    }
    two = run("system.antivirus", bad["system.antivirus"])
    assert two.status is Status.WARNING
    assert "Mais de um antivírus" in two.summary and "Defender em andamento" in two.summary


def test_antivirus_passive_defender_is_not_listed():
    rows = [
        {
            "Products": [
                {"Name": "Kaspersky", "State": 266240},
                {"Name": "Windows Defender", "State": 393472},
            ],
            "DefenderPresent": True,
            "ScanInProgress": False,
        }
    ]
    result = run("system.antivirus", rows)
    assert (result.status, result.data["products"]) == (Status.OK, ["Kaspersky"])


def test_antivirus_none_active_and_server_fallback():
    off = run("system.antivirus", [{"Products": {"Name": "Windows Defender", "State": 393472}}])
    assert off.status is Status.WARNING and off.data["realtime_enabled"] is False
    server = run(
        "system.antivirus",
        [
            {
                "Products": [],
                "DefenderPresent": True,
                "DefenderEnabled": True,
                "DefenderRealTime": True,
            }
        ],
    )
    assert server.data["products"] == ["Microsoft Defender Antivirus"]
    assert run("system.antivirus", [{"Products": []}]).status is Status.UNKNOWN


def test_devices(normal, bad):
    assert run("system.devices", normal["system.devices"]).status is Status.OK
    result = run("system.devices", bad["system.devices"])
    assert result.status is Status.WARNING
    assert result.data["problem_devices"] == [
        {"name": "Controlador Ethernet", "error_code": 28},
        {"name": "ACPI\\VPC2004\\0", "error_code": 28},
    ]
    assert result.summary.startswith(
        "2 dispositivos com problema: Controlador Ethernet (código 28: driver não instalado)"
    )


def test_pending_reboot(normal, bad):
    ok = run("system.pending_reboot", normal["system.pending_reboot"])
    assert ok.data == {"pending": False, "reasons": []}
    pending = run("system.pending_reboot", bad["system.pending_reboot"])
    assert pending.status is Status.WARNING
    assert pending.data == {"pending": True, "reasons": ["windows_update", "file_rename"]}
    single = run("system.pending_reboot", [{"Reasons": "component_servicing"}])
    assert single.data["reasons"] == ["component_servicing"]


# --- Network ----------------------------------------------------------------------


def test_connectivity_normal(normal):
    result = run("network.connectivity", normal["network.connectivity"])
    assert result.status is Status.OK
    assert result.data == {
        "gateway_ms": 1.2,
        "gateway_loss_percent": 0.0,
        "internet_ms": 15.9,
        "internet_loss_percent": 0.0,
        "dns_ms": 23.4,
    }
    assert result.summary == (
        "Roteador 1 ms (0% de perda), internet 16 ms (0% de perda), DNS 23 ms."
    )


def test_connectivity_bad(bad):
    result = run("network.connectivity", bad["network.connectivity"])
    assert result.status is Status.CRITICAL  # 60% loss to the internet
    assert result.data["internet_loss_percent"] == 60.0
    assert result.data["gateway_loss_percent"] == 20.0


def test_connectivity_no_route():
    rows = [{"HasRoute": False, "Gateway": None, "Internet": [None, None], "DnsMs": None}]
    result = run("network.connectivity", rows)
    assert result.status is Status.CRITICAL
    assert "não está em rede" in result.summary


def test_connectivity_router_ignoring_ping_is_not_a_problem():
    rows = [
        {
            "HasRoute": True,
            "Gateway": {"Sent": 10, "Lost": 10, "AvgMs": None},
            "Internet": {"Sent": 5, "Lost": 0, "AvgMs": 20},
            "DnsMs": 30,
        }
    ]
    result = run("network.connectivity", rows)
    assert result.status is Status.OK
    assert result.data["gateway_loss_percent"] is None
    assert result.summary.startswith("Roteador não responde a ping")


def test_connectivity_dns_down_is_warning_even_when_pings_work():
    rows = [
        {
            "HasRoute": True,
            "Gateway": {"Sent": 10, "Lost": 0, "AvgMs": 1},
            "Internet": [{"Sent": 5, "Lost": 0, "AvgMs": 20}],
            "DnsMs": None,
        }
    ]
    result = run("network.connectivity", rows)
    assert result.status is Status.WARNING and "DNS sem resposta" in result.summary


def test_wifi_omitted_when_wired(normal):
    assert run("network.wifi", normal["network.wifi"]) is None
    assert run("network.wifi", []) is None


def test_wifi_weak(bad):
    result = run("network.wifi", bad["network.wifi"])
    assert result.status is Status.CRITICAL
    assert result.data == {"ssid_present": True, "signal_percent": 28, "link_speed_mbps": 5.5}
    assert result.summary == "Conectado via Wi-Fi com sinal de 28% e velocidade de 5,5 Mbps."


@pytest.mark.parametrize(
    ("signal", "status"),
    [(51, Status.OK), (50, Status.WARNING), (31, Status.WARNING), (30, Status.CRITICAL)],
)
def test_wifi_signal_thresholds(signal, status):
    rows = [{"OnWifi": True, "SsidPresent": True, "Signal": signal, "ReceiveMbps": 300}]
    assert run("network.wifi", rows).status is status


def test_wifi_signal_hidden_by_location_permission():
    result = run("network.wifi", [{"OnWifi": True, "SsidPresent": False, "Signal": None}])
    assert result.status is Status.UNKNOWN
    assert "permissão de localização" in result.summary


# --- Real Windows -----------------------------------------------------------------


@pytest.mark.windows
def test_real_health_checks_on_windows():
    results = run_health_checks(PowerShell(), Inventory())
    ids = {r.id for r in results}
    assert set(SCRIPTS) - {"network.wifi"} <= ids
    for result in results:
        assert set(result.data) == CONTRACT_KEYS[result.id]
