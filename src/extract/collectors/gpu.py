"""Video adapters, video memory and driver."""

from __future__ import annotations

from extract.collectors._parse import as_list, cim_date, first, text, to_int
from extract.core.models import GpuInfo
from extract.core.powershell import PowerShellRunner, safe_query

# Win32_VideoController.AdapterRAM is a 32-bit value that tops out at 4 GB, so the real
# size comes from the display driver's registry key (qwMemorySize, a 64-bit value).
SCRIPT = r"""
$classKey = 'HKLM:\SYSTEM\CurrentControlSet\Control\Class\' +
    '{4d36e968-e325-11ce-bfc1-08002be10318}\0*'
[pscustomobject]@{
    Controllers = @(Get-CimInstance Win32_VideoController |
        Select-Object Name, AdapterRAM, DriverVersion, DriverDate)
    Drivers = @(Get-ItemProperty $classKey -ErrorAction SilentlyContinue |
        Select-Object DriverDesc, @{n='MemorySize'; e={$_.'HardwareInformation.qwMemorySize'}})
}
"""

# Virtual adapters added by remote access sessions, not real hardware.
_IGNORED = ("Remote Display Adapter", "Remote Desktop")
_MB = 1024**2


def collect_gpus(ps: PowerShellRunner) -> list[GpuInfo]:
    row = first(safe_query(ps, SCRIPT))
    registry_sizes = {
        text(d.get("DriverDesc")): to_int(d.get("MemorySize"))
        for d in as_list(row.get("Drivers"))
        if isinstance(d, dict)
    }
    gpus = []
    for controller in as_list(row.get("Controllers")):
        if not isinstance(controller, dict):
            continue
        name = text(controller.get("Name"))
        if not name or any(marker in name for marker in _IGNORED):
            continue
        vram_bytes = max(to_int(controller.get("AdapterRAM")), registry_sizes.get(name, 0))
        gpus.append(
            GpuInfo(
                name=name,
                vram_mb=vram_bytes // _MB,
                driver_version=text(controller.get("DriverVersion")),
                driver_date=cim_date(controller.get("DriverDate")),
            )
        )
    return gpus
