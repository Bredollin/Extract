"""Physical disks (type, bus, health) and fixed volumes."""

from __future__ import annotations

from typing import Any, NamedTuple

from extract.collectors._parse import as_list, bytes_to_gb, clean, first, text, to_int
from extract.core.models import DiskInfo, VolumeInfo
from extract.core.powershell import PowerShellRunner, safe_query

# Get-PhysicalDisk (MSFT_PhysicalDisk) is the only source that tells SSD from HDD;
# Win32_DiskDrive is kept as a fallback for machines where the Storage module fails.
# The system disk comes from Get-Partition, or from the WMI associations
# LogicalDisk -> DiskPartition -> DiskDrive when Get-Partition is unavailable.
SCRIPT = """
$sysDisk = $null
$letter = $env:SystemDrive.TrimEnd(':')
try { $sysDisk = (Get-Partition -DriveLetter $letter -ErrorAction Stop).DiskNumber } catch { }
if ($null -eq $sysDisk) {
    try {
        $sysDisk = (Get-CimInstance Win32_LogicalDisk -Filter "DeviceID='$env:SystemDrive'" |
            Get-CimAssociatedInstance -ResultClassName Win32_DiskPartition |
            Get-CimAssociatedInstance -ResultClassName Win32_DiskDrive |
            Select-Object -First 1).Index
    } catch { }
}
$physical = @()
try {
    $physical = @(Get-PhysicalDisk -ErrorAction Stop | Select-Object DeviceId, FriendlyName,
        Model, SerialNumber, MediaType, BusType, HealthStatus, Size)
} catch { }
[pscustomobject]@{
    SystemDiskNumber = $sysDisk
    PhysicalDisks = $physical
    DiskDrives = @(Get-CimInstance Win32_DiskDrive -ErrorAction SilentlyContinue |
        Select-Object Index, Model, SerialNumber, Size, InterfaceType, PNPDeviceID)
    Volumes = @(Get-CimInstance Win32_LogicalDisk -Filter 'DriveType=3' |
        Select-Object DeviceID, VolumeName, FileSystem, Size, FreeSpace)
}
"""

# MSFT_PhysicalDisk enumerations. ConvertTo-Json writes them as numbers, but newer
# PowerShell versions or formatting can yield the names, so both are accepted.
_MEDIA_TYPES = {0: "Unknown", 3: "HDD", 4: "SSD", 5: "SSD"}  # 5 = SCM (storage-class memory)
_BUS_TYPES = {
    1: "SCSI",
    2: "ATAPI",
    3: "ATA",
    4: "IEEE 1394",
    5: "SSA",
    6: "Fibre Channel",
    7: "USB",
    8: "RAID",
    9: "iSCSI",
    10: "SAS",
    11: "SATA",
    12: "SD",
    13: "MMC",
    15: "Virtual",
    16: "Storage Spaces",
    17: "NVMe",
}
_HEALTH = {0: "Healthy", 1: "Warning", 2: "Unhealthy", 5: "Unknown"}


class Storage(NamedTuple):
    disks: list[DiskInfo]
    volumes: list[VolumeInfo]


def collect_storage(ps: PowerShellRunner) -> Storage:
    row = first(safe_query(ps, SCRIPT))
    system_disk = row.get("SystemDiskNumber")
    system_index = to_int(system_disk, -1) if system_disk is not None else -1

    drives = {to_int(d.get("Index"), -1): d for d in _dicts(row.get("DiskDrives"))}
    physical = _dicts(row.get("PhysicalDisks"))
    if physical:
        disks = [_from_physical(p, drives, system_index) for p in physical]
    else:
        disks = [_from_drive(i, d, system_index) for i, d in sorted(drives.items())]

    volumes = [_volume(v) for v in _dicts(row.get("Volumes"))]
    return Storage(disks=disks, volumes=sorted(volumes, key=lambda v: v.letter))


def _dicts(value: Any) -> list[dict[str, Any]]:
    return [item for item in as_list(value) if isinstance(item, dict)]


def _from_physical(row: dict, drives: dict[int, dict], system_index: int) -> DiskInfo:
    number = to_int(row.get("DeviceId"), -1)
    drive = drives.get(number, {})
    return DiskInfo(
        model=text(row.get("FriendlyName")) or text(row.get("Model")) or text(drive.get("Model")),
        size_gb=bytes_to_gb(row.get("Size") or drive.get("Size")),
        media_type=_enum(row.get("MediaType"), _MEDIA_TYPES, "Unknown"),
        bus_type=_enum(row.get("BusType"), _BUS_TYPES, ""),
        serial_number=clean(row.get("SerialNumber")) or clean(drive.get("SerialNumber")),
        health_status=_enum(row.get("HealthStatus"), _HEALTH, ""),
        is_system_disk=number >= 0 and number == system_index,
    )


def _from_drive(index: int, row: dict, system_index: int) -> DiskInfo:
    """Fallback without MSFT_PhysicalDisk: media type is only known when the model says so."""
    model = text(row.get("Model"))
    pnp = text(row.get("PNPDeviceID")).upper()
    is_nvme = "NVME" in pnp or "NVME" in model.upper()
    is_ssd = is_nvme or "SSD" in model.upper()
    return DiskInfo(
        model=model,
        size_gb=bytes_to_gb(row.get("Size")),
        media_type="SSD" if is_ssd else "Unknown",
        bus_type="NVMe" if is_nvme else text(row.get("InterfaceType")),
        serial_number=clean(row.get("SerialNumber")),
        is_system_disk=index >= 0 and index == system_index,
    )


def _enum(value: Any, names: dict[int, str], default: str) -> str:
    if value is None or value == "":
        return default
    if isinstance(value, int) or text(value).isdigit():
        return names.get(to_int(value), default)
    raw = text(value)
    return "Unknown" if raw == "Unspecified" else raw


def _volume(row: dict) -> VolumeInfo:
    return VolumeInfo(
        letter=text(row.get("DeviceID")),
        label=text(row.get("VolumeName")),
        filesystem=text(row.get("FileSystem")),
        size_gb=bytes_to_gb(row.get("Size")),
        free_gb=bytes_to_gb(row.get("FreeSpace")),
    )
