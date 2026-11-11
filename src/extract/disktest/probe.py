"""Read-only queries about the physical disks: identity, Windows health, reliability
counters, raw SMART, volumes, TRIM and admin rights.

Nothing here writes to a disk. Every query degrades gracefully: without admin rights the
reliability counters and raw SMART come back empty and the test says so.
"""

from __future__ import annotations

import logging
import re
from typing import Any

from extract.core.powershell import PowerShellRunner, safe_query
from extract.health.base import to_float, to_int

from .models import DriveEntry, VolumeEntry
from .smart import SmartAttribute, parse_attributes, parse_thresholds

log = logging.getLogger(__name__)

GB = 1024**3

DRIVES_SCRIPT = """
$system = (Get-Partition -ErrorAction SilentlyContinue |
    Where-Object { "$($_.DriveLetter):" -eq $env:SystemDrive } |
    Select-Object -First 1).DiskNumber
Get-PhysicalDisk | ForEach-Object {
    $pd = $_
    $number = [int]$pd.DeviceId
    $disk = Get-Disk -Number $number -ErrorAction SilentlyContinue
    $volumes = @(Get-Partition -DiskNumber $number -ErrorAction SilentlyContinue |
        Where-Object { "$($_.DriveLetter)" -match '^[A-Za-z]$' } | ForEach-Object {
            $v = $_ | Get-Volume -ErrorAction SilentlyContinue
            [pscustomobject]@{
                Letter = "$($_.DriveLetter):"
                Label = $v.FileSystemLabel
                FileSystem = $v.FileSystem
                Size = $v.Size
                Free = $v.SizeRemaining
                Offset = $_.Offset
            }
        })
    [pscustomobject]@{
        Number = $number
        Model = $pd.FriendlyName
        Serial = $pd.SerialNumber
        Firmware = $pd.FirmwareVersion
        BusType = [string]$pd.BusType
        MediaType = [string]$pd.MediaType
        SpindleSpeed = $pd.SpindleSpeed
        Size = $pd.Size
        PartitionStyle = [string]$disk.PartitionStyle
        HealthStatus = [string]$pd.HealthStatus
        OperationalStatus = [string]($pd.OperationalStatus -join ', ')
        IsSystem = ($number -eq $system)
        Volumes = $volumes
    }
}
"""

RELIABILITY_SCRIPT = """
Get-PhysicalDisk | Where-Object { [int]$_.DeviceId -eq __NUMBER__ } |
    Get-StorageReliabilityCounter -ErrorAction Stop |
    Select-Object Temperature, TemperatureMax, Wear, PowerOnHours, StartStopCycleCount,
        LoadUnloadCycleCount, ReadErrorsTotal, ReadErrorsCorrected, ReadErrorsUncorrected,
        WriteErrorsTotal, WriteErrorsCorrected, WriteErrorsUncorrected,
        ReadLatencyMax, WriteLatencyMax, FlushLatencyMax
"""

# Raw ATA SMART (SATA drives only, admin only). Each row is one drive; matched by model.
SMART_SCRIPT = """
$ns = 'root\\wmi'
$data = Get-CimInstance -Namespace $ns -ClassName MSStorageDriver_FailurePredictData -EA Stop
$limits = @{}
Get-CimInstance -Namespace $ns -ClassName MSStorageDriver_FailurePredictThresholds -EA 0 |
    ForEach-Object { $limits[$_.InstanceName] = $_.VendorSpecific }
$predict = @{}
Get-CimInstance -Namespace $ns -ClassName MSStorageDriver_FailurePredictStatus -EA 0 |
    ForEach-Object { $predict[$_.InstanceName] = $_.PredictFailure }
$data | ForEach-Object {
    [pscustomobject]@{
        InstanceName = $_.InstanceName
        Data = @($_.VendorSpecific)
        Thresholds = @($limits[$_.InstanceName])
        PredictFailure = $predict[$_.InstanceName]
    }
}
"""

TRIM_SCRIPT = """
$out = try { (fsutil behavior query DisableDeleteNotify) -join "`n" } catch { '' }
[pscustomobject]@{ Output = $out }
"""

ADMIN_SCRIPT = """
$id = [Security.Principal.WindowsIdentity]::GetCurrent()
[pscustomobject]@{
    IsAdmin = (New-Object Security.Principal.WindowsPrincipal $id).IsInRole(
        [Security.Principal.WindowsBuiltInRole]::Administrator)
    Host = $env:COMPUTERNAME
}
"""

_MEDIA = {"3": "HDD", "4": "SSD", "5": "SCM", "0": "Unspecified"}
_BUS = {"17": "NVMe", "11": "SATA", "7": "USB", "8": "RAID", "10": "SAS", "3": "ATA", "1": "SCSI"}
_HEALTH = {"0": "Healthy", "1": "Warning", "2": "Unhealthy", "5": "Unknown"}


def _text(value: Any, names: dict[str, str] | None = None) -> str:
    if value is None:
        return ""
    text = str(value).strip()
    return names.get(text, text) if names else text


def _rows(value: Any) -> list[dict[str, Any]]:
    if isinstance(value, dict):
        return [value]
    if isinstance(value, list):
        return [v for v in value if isinstance(v, dict)]
    return []


def parse_drive(row: dict[str, Any]) -> DriveEntry:
    volumes = [
        VolumeEntry(
            letter=_text(v.get("Letter")),
            label=_text(v.get("Label")),
            filesystem=_text(v.get("FileSystem")),
            size_gb=round((to_float(v.get("Size")) or 0) / GB, 1),
            free_gb=round((to_float(v.get("Free")) or 0) / GB, 1),
            partition_offset=to_int(v.get("Offset")),
        )
        for v in _rows(row.get("Volumes"))
    ]
    return DriveEntry(
        number=to_int(row.get("Number")) if row.get("Number") is not None else -1,
        model=_text(row.get("Model")),
        serial_number=_text(row.get("Serial")),
        firmware=_text(row.get("Firmware")),
        bus_type=_text(row.get("BusType"), _BUS),
        media_type=_text(row.get("MediaType"), _MEDIA),
        spindle_rpm=_spindle(row.get("SpindleSpeed")),
        size_gb=round((to_float(row.get("Size")) or 0) / GB, 1),
        partition_style=_text(row.get("PartitionStyle")),
        health_status=_text(row.get("HealthStatus"), _HEALTH),
        operational_status=_text(row.get("OperationalStatus")),
        is_system=bool(row.get("IsSystem")),
        volumes=volumes,
    )


def _spindle(value: Any) -> int | None:
    rpm = to_int(value)
    # 4294967295 (uint32 max) means "unknown"; 0 means no spindle (SSD).
    if rpm is None or rpm >= 0xFFFFFFFF:
        return None
    return rpm


def list_drives(ps: PowerShellRunner) -> list[DriveEntry]:
    drives = [parse_drive(row) for row in ps.query(DRIVES_SCRIPT, timeout=60)]
    return sorted(drives, key=lambda d: (not d.is_system, d.number))


def reliability(ps: PowerShellRunner, number: int) -> dict[str, Any]:
    rows = safe_query(ps, RELIABILITY_SCRIPT.replace("__NUMBER__", str(int(number))))
    # Without admin rights Windows returns the object with every counter null.
    return {k: v for k, v in rows[0].items() if v is not None} if rows else {}


def _instance_tokens(instance: str) -> set[str]:
    # "SCSI\\Disk&Ven_&Prod_ST1000DM010-2EP1\\4&...": product name words.
    match = re.search(r"Prod_([^\\&]+)", instance, re.IGNORECASE)
    text = match.group(1) if match else instance
    return {t for t in re.split(r"[_\s-]+", text.lower()) if len(t) >= 3}


def _model_tokens(model: str) -> set[str]:
    return {t for t in re.split(r"[_\s-]+", model.lower()) if len(t) >= 3}


def raw_smart(
    ps: PowerShellRunner, drive: DriveEntry, drive_count: int
) -> tuple[list[SmartAttribute], bool | None]:
    """(attributes, predicted failure) for `drive`; empty when unavailable or not matched."""
    rows = safe_query(ps, SMART_SCRIPT)
    if not rows:
        return [], None
    wanted = _model_tokens(drive.model)
    match = None
    if wanted:
        scored = [(len(wanted & _instance_tokens(_text(r.get("InstanceName")))), r) for r in rows]
        scored = [s for s in scored if s[0] > 0]
        if scored:
            match = max(scored, key=lambda s: s[0])[1]
    if match is None and len(rows) == 1 and drive_count == 1:
        match = rows[0]
    if match is None:
        log.info("Raw SMART: no WMI instance matches %r", drive.model)
        return [], None
    attributes = parse_attributes(match.get("Data"), parse_thresholds(match.get("Thresholds")))
    predict = match.get("PredictFailure")
    return attributes, (bool(predict) if predict is not None else None)


def trim_enabled(ps: PowerShellRunner) -> bool | None:
    """TRIM state for NTFS (`DisableDeleteNotify = 0` means TRIM is on)."""
    rows = safe_query(ps, TRIM_SCRIPT)
    output = _text(rows[0].get("Output")) if rows else ""
    match = re.search(r"NTFS\s+DisableDeleteNotify\s*=\s*(\d)", output, re.IGNORECASE)
    if not match:
        match = re.search(r"DisableDeleteNotify\s*=\s*(\d)", output, re.IGNORECASE)
    return None if not match else match.group(1) == "0"


def session_info(ps: PowerShellRunner) -> tuple[bool, str]:
    rows = safe_query(ps, ADMIN_SCRIPT)
    if not rows:
        return False, ""
    return bool(rows[0].get("IsAdmin")), _text(rows[0].get("Host"))
