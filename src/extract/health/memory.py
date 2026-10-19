"""Memory check: RAM in use, commit charge, hard faults and page file usage."""

from __future__ import annotations

from extract.core.models import Category, Inventory, Status
from extract.core.powershell import PowerShellRunner

from .base import Outcome, first_row, fmt, health_check, level, rounded, to_float, worst

# High RAM use alone is normal on a busy machine; it becomes a problem when Windows has to
# read pages back from disk (hard faults) to keep up, so CRITICAL needs both.
MEMORY_USED_PERCENT = {"warning": 90}
MEMORY_COMMIT_PERCENT = {"warning": 90, "critical": 98}
HARD_FAULTS_PER_S = {"high": 50}

# Page reads/s is the rate of disk reads done to resolve hard page faults, sampled over ~3 s.
MEMORY_SCRIPT = """
$os = Get-CimInstance Win32_OperatingSystem
$faults = @()
for ($i = 0; $i -lt 4; $i++) {
    $mem = Get-CimInstance Win32_PerfFormattedData_PerfOS_Memory
    if ($i -gt 0) { $faults += [double]$mem.PageReadsPersec }
    if ($i -lt 3) { Start-Sleep -Milliseconds 1000 }
}
$pf = @(Get-CimInstance Win32_PageFileUsage)
[pscustomobject]@{
    TotalVisibleMemoryKB = $os.TotalVisibleMemorySize
    AvailableMBytes = $mem.AvailableMBytes
    PercentCommittedBytesInUse = $mem.PercentCommittedBytesInUse
    HardFaultsPerSec = ($faults | Measure-Object -Average).Average
    PageFileAllocatedMB = ($pf | Measure-Object AllocatedBaseSize -Sum).Sum
    PageFileCurrentMB = ($pf | Measure-Object CurrentUsage -Sum).Sum
}
"""


@health_check(
    "memory.pressure",
    Category.MEMORY,
    "Uso de memória",
    [
        "used_percent",
        "available_mb",
        "commit_percent",
        "hard_faults_per_s",
        "pagefile_used_percent",
    ],
)
def check_memory_pressure(ps: PowerShellRunner, inventory: Inventory) -> Outcome:
    row = first_row(ps.query(MEMORY_SCRIPT, timeout=60))
    total_kb = to_float(row.get("TotalVisibleMemoryKB"))
    available_mb = to_float(row.get("AvailableMBytes"))
    if not total_kb or available_mb is None:
        raise ValueError("memory counters unavailable")
    used_percent = max(0.0, 100 - available_mb * 1024 / total_kb * 100)
    commit = to_float(row.get("PercentCommittedBytesInUse"))
    faults = to_float(row.get("HardFaultsPerSec"))
    pf_allocated = to_float(row.get("PageFileAllocatedMB"))
    pf_current = to_float(row.get("PageFileCurrentMB"))
    pagefile_percent = (
        pf_current / pf_allocated * 100 if pf_allocated and pf_current is not None else None
    )

    full = (
        used_percent >= MEMORY_USED_PERCENT["warning"]
        or (commit or 0) >= MEMORY_COMMIT_PERCENT["warning"]
    )
    status = worst(
        Status.WARNING if full else Status.OK,
        level(commit, MEMORY_COMMIT_PERCENT["warning"], MEMORY_COMMIT_PERCENT["critical"]),
        Status.CRITICAL if full and (faults or 0) >= HARD_FAULTS_PER_S["high"] else Status.OK,
    )

    total_gb = total_kb / 1024**2
    summary = (
        f"{fmt(used_percent)}% da memória em uso ({fmt(available_mb / 1024, 1)} GB livres "
        f"de {fmt(total_gb, 1)} GB), carga de confirmação em {fmt(commit)}%"
    )
    if faults is not None:
        summary += f", {fmt(faults)} leituras de paginação por segundo"
    return Outcome(
        status,
        summary + ".",
        {
            "used_percent": rounded(used_percent),
            "available_mb": rounded(available_mb, 0),
            "commit_percent": rounded(commit),
            "hard_faults_per_s": rounded(faults),
            "pagefile_used_percent": rounded(pagefile_percent),
        },
    )
