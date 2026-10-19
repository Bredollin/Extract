"""Storage checks: disk health (SMART-like counters), system volume free space, disk activity."""

from __future__ import annotations

from typing import Any

from extract.core.models import Category, Inventory, Status
from extract.core.powershell import PowerShellRunner

from .base import (
    MissingData,
    Outcome,
    first_row,
    fmt,
    health_check,
    level,
    plural,
    rounded,
    to_float,
    to_int,
    worst,
)

# Disk health: Windows' own verdict counts most; wear is "percent of rated life used".
DISK_WEAR_PERCENT = {"warning": 70, "critical": 90}
DISK_TEMPERATURE_C = {"warning": 60, "critical": 70}
DISK_UNCORRECTED_ERRORS = {"warning": 1, "critical": 50}

# Free space on the system volume, at or below (percent), plus an absolute floor because
# Windows Update and the page file need room even on large disks.
FREE_SPACE_PERCENT = {"warning": 20, "critical": 10}
FREE_SPACE_MIN_GB = 15

# Disk activity averaged over the sampling window.
DISK_BUSY_PERCENT = {"warning": 80, "critical": 95}
DISK_RESPONSE_MS = {"warning": 50, "critical": 200}
DISK_QUEUE_LENGTH = {"warning": 2, "critical": 10}

# Reliability counters need admin rights; without them the values come back null and only
# the health status from Get-PhysicalDisk is reported.
DISK_HEALTH_SCRIPT = """
Get-PhysicalDisk | ForEach-Object {
    $rel = $null
    try { $rel = $_ | Get-StorageReliabilityCounter -ErrorAction Stop } catch { }
    [pscustomobject]@{
        Model = $_.FriendlyName
        MediaType = [string]$_.MediaType
        HealthStatus = [string]$_.HealthStatus
        Temperature = $rel.Temperature
        Wear = $rel.Wear
        ReadErrorsUncorrected = $rel.ReadErrorsUncorrected
        WriteErrorsUncorrected = $rel.WriteErrorsUncorrected
        ReadErrorsTotal = $rel.ReadErrorsTotal
        WriteErrorsTotal = $rel.WriteErrorsTotal
        PowerOnHours = $rel.PowerOnHours
    }
}
"""

FREE_SPACE_SCRIPT = """
Get-CimInstance Win32_LogicalDisk |
    Where-Object { $_.DeviceID -eq $env:SystemDrive } |
    Select-Object DeviceID, Size, FreeSpace
"""

# Busy time comes from the formatted class, sampled once per second (the first sample is
# discarded because formatted counters need a previous sample). Queue length and response
# time come from the raw class: the formatted response time is truncated to whole seconds.
ACTIVITY_SCRIPT = """
$filter = { $_.Name -eq '_Total' }
$busy = @()
$first = Get-CimInstance Win32_PerfRawData_PerfDisk_PhysicalDisk | Where-Object $filter
for ($i = 0; $i -lt 4; $i++) {
    $fmt = Get-CimInstance Win32_PerfFormattedData_PerfDisk_PhysicalDisk | Where-Object $filter
    if ($i -gt 0) { $busy += 100 - [double]$fmt.PercentIdleTime }
    Start-Sleep -Milliseconds 1000
}
$last = Get-CimInstance Win32_PerfRawData_PerfDisk_PhysicalDisk | Where-Object $filter
$elapsed = [double]($last.Timestamp_Sys100NS - $first.Timestamp_Sys100NS)
$transfers = [double]($last.AvgDisksecPerTransfer_Base - $first.AvgDisksecPerTransfer_Base)
$ticks = [double]($last.AvgDisksecPerTransfer - $first.AvgDisksecPerTransfer)
[pscustomobject]@{
    BusyPercent = ($busy | Measure-Object -Average).Average
    AvgQueueLength = if ($elapsed -gt 0) {
        [double]($last.AvgDiskQueueLength - $first.AvgDiskQueueLength) / $elapsed
    } else { $null }
    AvgResponseMs = if ($transfers -gt 0) {
        $ticks / [double]$last.Frequency_PerfTime / $transfers * 1000
    } else { 0 }
}
"""

_MEDIA_TYPES = {"3": "HDD", "4": "SSD", "5": "SCM", "0": "Unspecified"}
_HEALTH_STATUSES = {"0": "Healthy", "1": "Warning", "2": "Unhealthy", "5": "Unknown"}
_HEALTH_LABELS = {"Healthy": "saudável", "Warning": "em alerta", "Unhealthy": "com falha"}


def _enum_text(value: Any, names: dict[str, str]) -> str | None:
    """Storage enums arrive as names (`[string]` cast) or, on some builds, as numbers."""
    if value is None or value == "":
        return None
    text = str(value)
    return names.get(text, text)


def _parse_disk(row: dict[str, Any]) -> dict[str, Any]:
    temperature = to_int(row.get("Temperature"))
    return {
        "model": (row.get("Model") or "").strip() or None,
        "media_type": _enum_text(row.get("MediaType"), _MEDIA_TYPES),
        "health_status": _enum_text(row.get("HealthStatus"), _HEALTH_STATUSES),
        # Drives that do not report temperature return 0.
        "temperature_c": temperature or None,
        "wear_percent": to_int(row.get("Wear")),
        "read_errors_total": to_int(row.get("ReadErrorsTotal")),
        "write_errors_total": to_int(row.get("WriteErrorsTotal")),
        "power_on_hours": to_int(row.get("PowerOnHours")),
    }


def _uncorrected_errors(row: dict[str, Any]) -> int | None:
    values = [to_int(row.get(k)) for k in ("ReadErrorsUncorrected", "WriteErrorsUncorrected")]
    known = [v for v in values if v is not None]
    return sum(known) if known else None


def _disk_status(disk: dict[str, Any], uncorrected: int | None) -> tuple[Status, list[str]]:
    problems: list[str] = []
    statuses = [Status.OK]
    health = disk["health_status"]
    if health == "Unhealthy":
        statuses.append(Status.CRITICAL)
    elif health == "Warning":
        statuses.append(Status.WARNING)
    if health in ("Warning", "Unhealthy"):
        problems.append(_HEALTH_LABELS[health])

    checks = (
        (disk["wear_percent"], DISK_WEAR_PERCENT, "desgaste {}%"),
        (disk["temperature_c"], DISK_TEMPERATURE_C, "temperatura {} °C"),
        (uncorrected, DISK_UNCORRECTED_ERRORS, "{} erros de leitura/gravação não corrigidos"),
    )
    for value, limits, text in checks:
        status = level(value, limits["warning"], limits["critical"])
        if status is not Status.OK:
            statuses.append(status)
            problems.append(text.format(value))
    return worst(*statuses), problems


@health_check(
    "storage.health",
    Category.STORAGE,
    "Saúde dos discos",
    ["disks"],
)
def check_disk_health(ps: PowerShellRunner, inventory: Inventory) -> Outcome:
    rows = ps.query(DISK_HEALTH_SCRIPT)
    if not rows:
        raise MissingData("no physical disks")
    disks = [_parse_disk(row) for row in rows]
    verdicts = [
        (disk, *_disk_status(disk, _uncorrected_errors(row)))
        for disk, row in zip(disks, rows, strict=True)
    ]
    status = worst(*(s for _, s, _ in verdicts))

    flagged = [(disk, problems) for disk, s, problems in verdicts if s is not Status.OK]
    if flagged:
        summary = "; ".join(
            f"{disk['model'] or 'Disco'}: {', '.join(problems)}" for disk, problems in flagged
        )
        summary += "."
    elif all(d["health_status"] == "Healthy" for d in disks):
        summary = f"{plural(len(disks), 'disco saudável', 'discos saudáveis')}."
    else:
        summary = f"{plural(len(disks), 'disco', 'discos')} sem problemas relatados."
    if all(d["wear_percent"] is None and d["temperature_c"] is None for d in disks):
        summary += " Contadores SMART indisponíveis (requer administrador)."
    return Outcome(status, summary, {"disks": disks})


@health_check(
    "storage.free_space",
    Category.STORAGE,
    "Espaço livre no disco do sistema",
    ["letter", "size_gb", "free_gb", "free_percent"],
)
def check_free_space(ps: PowerShellRunner, inventory: Inventory) -> Outcome:
    row = first_row(ps.query(FREE_SPACE_SCRIPT))
    size = to_float(row.get("Size"))
    free = to_float(row.get("FreeSpace"))
    if not size or free is None:
        raise ValueError("volume size unavailable")
    size_gb = size / 1024**3
    free_gb = free / 1024**3
    free_percent = free / size * 100
    letter = row.get("DeviceID") or "C:"

    status = level(
        free_percent,
        FREE_SPACE_PERCENT["warning"],
        FREE_SPACE_PERCENT["critical"],
        below=True,
    )
    if free_gb < FREE_SPACE_MIN_GB:
        status = worst(status, Status.WARNING)
    summary = (
        f"Disco {letter} com {fmt(free_percent)}% livre ({fmt(free_gb)} GB de {fmt(size_gb)} GB)."
    )
    return Outcome(
        status,
        summary,
        {
            "letter": letter,
            "size_gb": rounded(size_gb),
            "free_gb": rounded(free_gb),
            "free_percent": rounded(free_percent),
        },
    )


@health_check(
    "storage.activity",
    Category.STORAGE,
    "Atividade do disco",
    ["busy_percent", "avg_queue_length", "avg_response_ms"],
)
def check_disk_activity(ps: PowerShellRunner, inventory: Inventory) -> Outcome:
    row = first_row(ps.query(ACTIVITY_SCRIPT, timeout=60))
    busy = to_float(row.get("BusyPercent"))
    queue = to_float(row.get("AvgQueueLength"))
    response = to_float(row.get("AvgResponseMs"))
    if busy is None and response is None:
        raise ValueError("no disk counters")
    if busy is not None:
        busy = min(max(busy, 0.0), 100.0)

    status = worst(
        level(busy, DISK_BUSY_PERCENT["warning"], DISK_BUSY_PERCENT["critical"]),
        level(response, DISK_RESPONSE_MS["warning"], DISK_RESPONSE_MS["critical"]),
        level(queue, DISK_QUEUE_LENGTH["warning"], DISK_QUEUE_LENGTH["critical"]),
    )
    summary = (
        f"Disco ocupado {fmt(busy)}% do tempo, fila média {fmt(queue, 1)}, "
        f"resposta média {fmt(response)} ms."
    )
    return Outcome(
        status,
        summary,
        {
            "busy_percent": rounded(busy),
            "avg_queue_length": rounded(queue, 2),
            "avg_response_ms": rounded(response),
        },
    )
