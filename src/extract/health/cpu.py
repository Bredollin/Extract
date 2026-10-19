"""CPU check: load averaged over a few seconds, current clock and the busiest processes."""

from __future__ import annotations

import re
from collections import defaultdict
from typing import Any

from extract.core.models import Category, Inventory, Status
from extract.core.powershell import PowerShellRunner

from .base import (
    Outcome,
    as_list,
    first_row,
    fmt,
    health_check,
    level,
    rounded,
    to_float,
    to_int,
    worst,
)

CPU_LOAD_PERCENT = {"warning": 80, "critical": 95}
# A busy CPU running far below its rated clock points to thermal or power throttling; an
# idle CPU at low clock is just saving power, hence the load condition.
THROTTLE_CLOCK_RATIO = 0.5
THROTTLE_MIN_LOAD_PERCENT = 50
TOP_PROCESS_COUNT = 5

# PercentProcessorPerformance is the current speed as a percentage of the rated clock
# (above 100 when boosting); Win32_Processor.CurrentClockSpeed is often stale.
CPU_SCRIPT = """
$load = @(); $perf = @()
for ($i = 0; $i -lt 4; $i++) {
    $cpu = Get-CimInstance Win32_PerfFormattedData_PerfOS_Processor |
        Where-Object { $_.Name -eq '_Total' }
    $info = Get-CimInstance Win32_PerfFormattedData_Counters_ProcessorInformation |
        Where-Object { $_.Name -eq '_Total' }
    if ($i -gt 0) {
        $load += [double]$cpu.PercentProcessorTime
        $perf += [double]$info.PercentProcessorPerformance
    }
    if ($i -lt 3) { Start-Sleep -Milliseconds 1000 }
}
$procs = @(Get-CimInstance Win32_Processor)
$processes = Get-CimInstance Win32_PerfFormattedData_PerfProc_Process |
    Where-Object { $_.Name -ne '_Total' -and $_.Name -ne 'Idle' } |
    Sort-Object PercentProcessorTime -Descending |
    Select-Object -First 25 |
    ForEach-Object {
        [pscustomobject]@{
            Name = $_.Name
            PercentProcessorTime = $_.PercentProcessorTime
            WorkingSetPrivate = $_.WorkingSetPrivate
        }
    }
[pscustomobject]@{
    LoadPercent = ($load | Measure-Object -Average).Average
    PerformancePercent = ($perf | Measure-Object -Average).Average
    MaxClockMHz = ($procs | Measure-Object MaxClockSpeed -Maximum).Maximum
    LogicalProcessors = ($procs | Measure-Object NumberOfLogicalProcessors -Sum).Sum
    Processes = @($processes)
}
"""

# Performance counter instances of the same program are named "chrome", "chrome#1", ...
_INSTANCE_SUFFIX = re.compile(r"#\d+$")


def _top_processes(rows: list[Any], logical_processors: int) -> list[dict[str, Any]]:
    """Group process instances by name; per-process CPU is per core, so scale to total."""
    cpu: dict[str, float] = defaultdict(float)
    memory: dict[str, float] = defaultdict(float)
    for row in rows:
        if not isinstance(row, dict) or not row.get("Name"):
            continue
        name = _INSTANCE_SUFFIX.sub("", str(row["Name"]))
        cpu[name] += (to_float(row.get("PercentProcessorTime")) or 0.0) / logical_processors
        memory[name] += (to_float(row.get("WorkingSetPrivate")) or 0.0) / 1024**2
    ranked = sorted(cpu, key=lambda n: (cpu[n], memory[n]), reverse=True)
    return [
        {"name": name, "cpu_percent": round(cpu[name], 1), "memory_mb": round(memory[name])}
        for name in ranked[:TOP_PROCESS_COUNT]
    ]


@health_check(
    "cpu.load",
    Category.CPU,
    "Uso do processador",
    ["load_percent", "current_clock_mhz", "max_clock_mhz", "top_processes"],
)
def check_cpu_load(ps: PowerShellRunner, inventory: Inventory) -> Outcome:
    row = first_row(ps.query(CPU_SCRIPT, timeout=60))
    load = to_float(row.get("LoadPercent"))
    if load is None:
        raise ValueError("processor counters unavailable")
    load = min(max(load, 0.0), 100.0)
    max_clock = to_int(row.get("MaxClockMHz")) or inventory.cpu.base_clock_mhz or None
    performance = to_float(row.get("PerformancePercent"))
    current_clock = round(max_clock * performance / 100) if max_clock and performance else None
    logical = to_int(row.get("LogicalProcessors")) or inventory.cpu.logical_processors or 1
    top = _top_processes(as_list(row.get("Processes")), logical)

    throttled = (
        current_clock is not None
        and max_clock is not None
        and load >= THROTTLE_MIN_LOAD_PERCENT
        and current_clock < max_clock * THROTTLE_CLOCK_RATIO
    )
    status = worst(
        level(load, CPU_LOAD_PERCENT["warning"], CPU_LOAD_PERCENT["critical"]),
        Status.WARNING if throttled else Status.OK,
    )

    summary = f"Processador com {fmt(load)}% de uso"
    if current_clock and max_clock:
        summary += f", a {fmt(current_clock)} MHz de {fmt(max_clock)} MHz"
    if top and top[0]["cpu_percent"] >= 1:
        summary += f"; maior consumo: {top[0]['name']} ({fmt(top[0]['cpu_percent'])}%)"
    if throttled:
        summary += ". Clock muito abaixo do nominal sob carga (possível limitação térmica)"
    return Outcome(
        status,
        summary + ".",
        {
            "load_percent": rounded(load),
            "current_clock_mhz": current_clock,
            "max_clock_mhz": max_clock,
            "top_processes": top,
        },
    )
