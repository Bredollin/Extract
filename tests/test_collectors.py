from __future__ import annotations

from datetime import datetime, timezone

import pytest

from conftest import load_fixture
from extract.collectors import collect_inventory
from extract.collectors._parse import cim_date, cim_datetime
from extract.collectors.cpu import collect_cpu
from extract.collectors.gpu import collect_gpus
from extract.collectors.memory import collect_memory, memory_type
from extract.collectors.motherboard import collect_motherboard
from extract.collectors.network import collect_network
from extract.collectors.storage import collect_storage
from extract.collectors.system import collect_system
from extract.core.powershell import FakePowerShell, PowerShell, PowerShellError
from extract.core.progress import Cancelled, CancelToken


def _ps(key: str, fixture: str) -> FakePowerShell:
    return FakePowerShell({key: load_fixture(f"collectors_{fixture}.json")})


def _full_ps() -> FakePowerShell:
    return FakePowerShell(
        {
            "Win32_OperatingSystem": load_fixture("collectors_system.json"),
            "Win32_Processor": load_fixture("collectors_cpu.json"),
            "Win32_PhysicalMemory": load_fixture("collectors_memory.json"),
            "Win32_BaseBoard": load_fixture("collectors_motherboard.json"),
            "Win32_VideoController": load_fixture("collectors_gpu.json"),
            "Get-PhysicalDisk": load_fixture("collectors_storage.json"),
            "Get-NetAdapter": load_fixture("collectors_network.json"),
        }
    )


def _utc(iso: str) -> datetime:
    return datetime.fromisoformat(iso).astimezone(timezone.utc)


# --- date parsing ------------------------------------------------------------------


@pytest.mark.parametrize(
    "value",
    [
        "/Date(1729335600000)/",
        {"value": "/Date(1729335600000)/", "DateTime": "sábado, 19 de outubro de 2024"},
        "20241019080000.000000-180",
        "2024-10-19T08:00:00.1234567-03:00",
        "2024-10-19T11:00:00Z",
    ],
)
def test_cim_datetime_formats(value):
    assert _utc(cim_datetime(value)) == datetime(2024, 10, 19, 11, 0, tzinfo=timezone.utc)


@pytest.mark.parametrize("value", [None, "", "não é data"])
def test_cim_datetime_unknown(value):
    assert cim_datetime(value) == ""


def test_cim_date_keeps_only_the_date():
    assert cim_date("20230124000000.000000-000") == "2023-01-24"


# --- sections ----------------------------------------------------------------------


def test_system():
    info = collect_system(_ps("Win32_OperatingSystem", "system"))
    assert info.hostname == "RECEPCAO-01"
    assert info.os_name == "Microsoft Windows 11 Pro"
    assert info.os_version == "23H2"
    assert info.os_build == "22631.4317"
    assert info.architecture == "x64"
    assert info.boot_mode == "UEFI"
    assert info.user == "RECEPCAO-01\\usuario"
    assert _utc(info.last_boot) == datetime(2024, 10, 19, 11, 0, tzinfo=timezone.utc)
    assert info.install_date


def test_system_with_oem_placeholders():
    info = collect_system(_ps("Win32_OperatingSystem", "system_odd"))
    assert info.manufacturer == info.model == info.serial_number == ""
    assert info.os_version == "10.0.19045"
    assert info.os_build == "19045"
    assert info.user == "tecnico"
    assert info.boot_mode == "Legacy"
    assert info.install_date.startswith("2019-03-12T14:15:00")
    assert info.last_boot


def test_cpu():
    cpu = collect_cpu(_ps("Win32_Processor", "cpu"))
    assert cpu.name == "Intel(R) Core(TM) i5-10400 CPU @ 2.90GHz"
    assert cpu.manufacturer == "Intel"
    assert (cpu.cores, cpu.logical_processors, cpu.base_clock_mhz) == (6, 12, 2904)
    assert cpu.l3_cache_kb == 12288


def test_cpu_dual_socket_sums_cores_and_tidies_name():
    cpu = collect_cpu(_ps("Win32_Processor", "cpu_dual_socket"))
    assert cpu.name == "Intel(R) Xeon(R) CPU E5-2620 v4 @ 2.10GHz"
    assert (cpu.cores, cpu.logical_processors) == (16, 32)
    assert cpu.l3_cache_kb == 20480


def test_memory():
    memory = collect_memory(_ps("Win32_PhysicalMemory", "memory"))
    assert memory.total_gb == 16.0
    assert (memory.total_slots, memory.used_slots) == (4, 2)
    assert memory.memory_type == "DDR4"
    first, second = memory.modules
    assert first.part_number == "9905702-017.A00G"
    assert second.manufacturer == "Samsung"
    assert second.configured_speed_mhz == 2400


def test_memory_single_module_with_unknown_type():
    memory = collect_memory(_ps("Win32_PhysicalMemory", "memory_odd"))
    assert memory.total_gb == 4.0
    assert memory.total_slots == 1
    assert memory.memory_type == "DDR3"  # inferred from 1600 MT/s
    assert memory.modules[0].manufacturer == ""


@pytest.mark.parametrize(
    ("smbios", "cim", "speed", "expected"),
    [
        (34, 0, 2133, "DDR5"),  # SMBIOS wins over speed
        (35, 0, 6400, "LPDDR5"),
        (0, 24, 1333, "DDR3"),
        (0, 20, 400, "DDR"),
        (2, 0, 3200, "DDR4"),
        (0, 0, 5600, "DDR5"),
        (0, 0, 4000, ""),  # ambiguous range: not guessed
        (0, 0, 0, ""),
    ],
)
def test_memory_type(smbios, cim, speed, expected):
    assert memory_type(smbios, cim, speed) == expected


def test_memory_falls_back_to_total_physical_memory():
    ps = FakePowerShell(
        {"Win32_PhysicalMemory": [{"Modules": None, "Slots": 0, "TotalPhysicalMemory": 8.5e9}]}
    )
    memory = collect_memory(ps)
    assert memory.total_gb == 7.9
    assert memory.modules == []


def test_motherboard():
    board = collect_motherboard(_ps("Win32_BaseBoard", "motherboard"))
    assert (board.manufacturer, board.product) == ("Dell Inc.", "0J37JC")


def test_gpus_use_registry_vram_and_skip_remote_adapter():
    gpus = collect_gpus(_ps("Win32_VideoController", "gpu"))
    assert [g.name for g in gpus] == [
        "NVIDIA GeForce GTX 1660 SUPER",
        "Intel(R) UHD Graphics 630",
    ]
    assert gpus[0].vram_mb == 6144
    assert gpus[1].vram_mb == 1024
    assert gpus[1].driver_date == "2023-01-24"
    assert gpus[0].driver_date.startswith("2024-04-0")


def test_storage():
    disks, volumes = collect_storage(_ps("Get-PhysicalDisk", "storage"))
    hdd, nvme = disks
    assert (hdd.media_type, hdd.bus_type, hdd.health_status) == ("HDD", "SATA", "Healthy")
    assert hdd.size_gb == 931.5
    assert not hdd.is_system_disk
    assert (nvme.media_type, nvme.bus_type, nvme.health_status) == ("SSD", "NVMe", "Warning")
    assert nvme.is_system_disk
    assert [v.letter for v in volumes] == ["C:", "D:"]
    assert volumes[0].free_gb == 40.0
    assert volumes[0].size_gb == 465.2


def test_storage_accepts_enum_names():
    ps = FakePowerShell(
        {
            "Get-PhysicalDisk": [
                {
                    "SystemDiskNumber": 0,
                    "PhysicalDisks": {
                        "DeviceId": "0",
                        "FriendlyName": "Disco",
                        "MediaType": "Unspecified",
                        "BusType": "RAID",
                        "HealthStatus": "Healthy",
                        "Size": None,
                    },
                }
            ]
        }
    )
    (disk,), volumes = collect_storage(ps)
    assert (disk.media_type, disk.bus_type, disk.health_status) == ("Unknown", "RAID", "Healthy")
    assert disk.is_system_disk
    assert volumes == []


def test_storage_falls_back_to_win32_diskdrive():
    disks, volumes = collect_storage(_ps("Get-PhysicalDisk", "storage_fallback"))
    (disk,) = disks
    assert disk.model == "SAMSUNG SSD 860 EVO 250GB"
    assert disk.media_type == "SSD"
    assert disk.serial_number == ""
    assert not disk.is_system_disk
    assert volumes[0].free_gb == 0.0


def test_network():
    ethernet, wifi = collect_network(_ps("Get-NetAdapter", "network"))
    assert ethernet.name == "Ethernet (Realtek PCIe GbE Family Controller)"
    assert ethernet.ipv4 == ["192.168.0.25"]
    assert ethernet.gateway == ["192.168.0.1"]
    assert ethernet.dns_servers == ["192.168.0.1", "8.8.8.8"]
    assert ethernet.dhcp is True
    assert ethernet.link_speed_mbps == 1000
    assert ethernet.mac_address == "00:11:22:33:44:55"
    assert wifi.ipv4 == ["10.0.0.8"]
    assert wifi.gateway == []
    assert wifi.dhcp is False
    assert wifi.link_speed_mbps == 866


# --- full inventory -----------------------------------------------------------------


def test_collect_inventory_reports_progress():
    seen: list[tuple[float, str]] = []
    inventory = collect_inventory(_full_ps(), lambda f, m: seen.append((f, m)))
    assert inventory.system.hostname == "RECEPCAO-01"
    assert inventory.cpu.cores == 6
    assert inventory.memory.total_gb == 16.0
    assert len(inventory.gpus) == 2
    assert len(inventory.disks) == 2
    assert len(inventory.network) == 2
    fractions = [f for f, _ in seen]
    assert fractions == sorted(fractions)
    assert seen[-1] == (1.0, "Inventário concluído")


def test_collect_inventory_survives_failures():
    ps = FakePowerShell({"Win32_": PowerShellError("acesso negado")})
    inventory = collect_inventory(ps)
    assert inventory.system.hostname == ""
    assert inventory.disks == []


def test_collect_inventory_survives_unexpected_shapes():
    ps = _full_ps()
    ps.responses["Win32_Processor"] = ["texto em vez de objeto"]
    inventory = collect_inventory(ps)
    assert inventory.system.hostname == "RECEPCAO-01"
    assert inventory.disks


def test_collect_inventory_respects_cancel():
    token = CancelToken()
    token.cancel()
    ps = _full_ps()
    with pytest.raises(Cancelled):
        collect_inventory(ps, cancel=token)
    assert ps.calls == []


@pytest.mark.windows
def test_collect_inventory_on_real_windows():
    inventory = collect_inventory(PowerShell())
    assert inventory.system.hostname
    assert inventory.cpu.name
    assert inventory.cpu.cores > 0
    assert inventory.memory.total_gb > 0
