"""Processor model, cores, clock and cache."""

from __future__ import annotations

import re

from extract.collectors._parse import text, to_int
from extract.core.models import CpuInfo
from extract.core.powershell import PowerShellRunner, safe_query

SCRIPT = """
Get-CimInstance Win32_Processor | Select-Object Name, Manufacturer, NumberOfCores,
    NumberOfLogicalProcessors, MaxClockSpeed, SocketDesignation, L2CacheSize, L3CacheSize
"""

_VENDORS = {"GenuineIntel": "Intel", "AuthenticAMD": "AMD"}
_SPACES = re.compile(r"\s+")


def collect_cpu(ps: PowerShellRunner) -> CpuInfo:
    """Read the processor. On multi-socket machines, cores and caches are summed."""
    rows = safe_query(ps, SCRIPT)
    if not rows:
        return CpuInfo()
    main = rows[0]
    manufacturer = text(main.get("Manufacturer"))
    return CpuInfo(
        # Intel pads names with runs of spaces ("Intel(R) Core(TM) i5-8250U CPU   @ 1.60GHz").
        name=_SPACES.sub(" ", text(main.get("Name"))),
        manufacturer=_VENDORS.get(manufacturer, manufacturer),
        cores=sum(to_int(r.get("NumberOfCores")) for r in rows),
        logical_processors=sum(to_int(r.get("NumberOfLogicalProcessors")) for r in rows),
        base_clock_mhz=to_int(main.get("MaxClockSpeed")),
        socket=text(main.get("SocketDesignation")),
        l2_cache_kb=sum(to_int(r.get("L2CacheSize")) for r in rows),
        l3_cache_kb=sum(to_int(r.get("L3CacheSize")) for r in rows),
    )
