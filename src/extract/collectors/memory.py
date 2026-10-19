"""Installed memory modules, slots and memory type."""

from __future__ import annotations

from collections import Counter
from string import hexdigits

from extract.collectors._parse import GIB, as_list, first, text, to_float, to_int
from extract.core.models import MemoryInfo, MemoryModule
from extract.core.powershell import PowerShellRunner, safe_query

# Use = 3 keeps only system memory arrays (not flash or video memory arrays).
SCRIPT = """
$modules = @(Get-CimInstance Win32_PhysicalMemory | Select-Object DeviceLocator, BankLabel,
    Capacity, Speed, ConfiguredClockSpeed, Manufacturer, PartNumber, SMBIOSMemoryType,
    MemoryType)
$arrays = @(Get-CimInstance Win32_PhysicalMemoryArray -ErrorAction SilentlyContinue |
    Where-Object { $_.Use -eq 3 })
[pscustomobject]@{
    Modules = $modules
    Slots = ($arrays | Measure-Object -Property MemoryDevices -Sum).Sum
    TotalPhysicalMemory = (Get-CimInstance Win32_ComputerSystem).TotalPhysicalMemory
}
"""

# SMBIOS spec, "Memory Device - Type" (what Win32_PhysicalMemory.SMBIOSMemoryType holds).
_SMBIOS_TYPES = {
    15: "SDRAM",
    17: "RDRAM",
    18: "DDR",
    19: "DDR2",
    20: "DDR2",  # DDR2 FB-DIMM
    24: "DDR3",
    26: "DDR4",
    27: "LPDDR",
    28: "LPDDR2",
    29: "LPDDR3",
    30: "LPDDR4",
    34: "DDR5",
    35: "LPDDR5",
}
# The older Win32_PhysicalMemory.MemoryType uses the CIM enumeration, which numbers the
# early DDR generations differently from SMBIOS (20 = DDR there, 20 = DDR2 FB-DIMM above).
_CIM_TYPES = {
    15: "SDRAM",
    17: "RDRAM",
    20: "DDR",
    21: "DDR2",
    22: "DDR2",
    24: "DDR3",
    26: "DDR4",
}
# Common JEDEC manufacturer codes that some BIOSes report instead of a name.
_JEDEC_VENDORS = {
    "80CE": "Samsung",
    "CE00": "Samsung",
    "802C": "Micron",
    "2C00": "Micron",
    "80AD": "SK Hynix",
    "AD00": "SK Hynix",
    "0198": "Kingston",
    "859B": "Crucial",
    "04CD": "G.Skill",
    "029E": "Corsair",
    "830B": "Nanya",
    "0443": "Ramaxel",
    "04CB": "Adata",
}


def collect_memory(ps: PowerShellRunner) -> MemoryInfo:
    row = first(safe_query(ps, SCRIPT))
    modules = [_module(m) for m in as_list(row.get("Modules")) if isinstance(m, dict)]
    modules = [m for m in modules if m.capacity_gb > 0]

    total_gb = round(sum(m.capacity_gb for m in modules), 1)
    if not total_gb:
        # Some virtual machines expose no memory devices at all.
        total_gb = round(to_float(row.get("TotalPhysicalMemory")) / GIB, 1)

    types = Counter(m.memory_type for m in modules if m.memory_type)
    return MemoryInfo(
        total_gb=total_gb,
        total_slots=max(to_int(row.get("Slots")), len(modules)),
        memory_type=types.most_common(1)[0][0] if types else "",
        modules=modules,
    )


def _module(row: dict) -> MemoryModule:
    speed = to_int(row.get("Speed"))
    return MemoryModule(
        slot=text(row.get("DeviceLocator")) or text(row.get("BankLabel")),
        capacity_gb=round(to_float(row.get("Capacity")) / GIB, 2),
        speed_mhz=speed,
        configured_speed_mhz=to_int(row.get("ConfiguredClockSpeed")),
        manufacturer=_vendor(row.get("Manufacturer")),
        part_number=text(row.get("PartNumber")),
        memory_type=memory_type(
            to_int(row.get("SMBIOSMemoryType")), to_int(row.get("MemoryType")), speed
        ),
    )


def memory_type(smbios_type: int, cim_type: int, speed_mhz: int) -> str:
    """Name the memory generation.

    SMBIOSMemoryType is authoritative. When the firmware leaves it at 0/1/2 (unknown, as
    happens on some older Windows builds and VMs), the CIM MemoryType is tried next. Only
    when both are unknown do we infer the generation from the rated speed, using JEDEC
    ranges that do not overlap in practice: DDR5 starts at 4800 MT/s, DDR4 covers
    2133-3200, DDR3 800-1866. Speeds between those ranges stay unknown instead of guessed.
    """
    if smbios_type in _SMBIOS_TYPES:
        return _SMBIOS_TYPES[smbios_type]
    if cim_type in _CIM_TYPES:
        return _CIM_TYPES[cim_type]
    if speed_mhz >= 4800:
        return "DDR5"
    if 2133 <= speed_mhz <= 3200:
        return "DDR4"
    if 800 <= speed_mhz <= 1866:
        return "DDR3"
    return ""


def _vendor(value: object) -> str:
    raw = text(value)
    if raw.lower() in {"", "unknown", "undefined"} or set(raw.upper()) <= {"0", "F"}:
        return ""
    if all(c in hexdigits for c in raw):
        return _JEDEC_VENDORS.get(raw[:4].upper(), raw)
    return raw
