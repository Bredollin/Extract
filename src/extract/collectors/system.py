"""Operating system, computer model, BIOS and boot mode."""

from __future__ import annotations

from extract.collectors._parse import cim_datetime, clean, first, text
from extract.core.models import SystemInfo
from extract.core.powershell import PowerShellRunner, safe_query

# `$env:firmware_type` is set by Windows itself ("UEFI" or "Legacy") and, unlike
# Confirm-SecureBootUEFI or bcdedit, needs no admin rights. The registry gives the
# marketing version (23H2) and the update build revision that CIM does not expose.
SCRIPT = r"""
$os = Get-CimInstance Win32_OperatingSystem |
    Select-Object Caption, Version, BuildNumber, InstallDate, LastBootUpTime
$cs = Get-CimInstance Win32_ComputerSystem | Select-Object Manufacturer, Model, UserName
$bios = Get-CimInstance Win32_BIOS | Select-Object SerialNumber, SMBIOSBIOSVersion
$ntKey = 'HKLM:\SOFTWARE\Microsoft\Windows NT\CurrentVersion'
$nt = Get-ItemProperty $ntKey -ErrorAction SilentlyContinue |
    Select-Object DisplayVersion, ReleaseId, UBR
# A 32-bit host process sees the native architecture only in PROCESSOR_ARCHITEW6432.
$arch = $env:PROCESSOR_ARCHITEW6432
if (-not $arch) { $arch = $env:PROCESSOR_ARCHITECTURE }
[pscustomobject]@{
    Hostname = $env:COMPUTERNAME
    UserName = $cs.UserName
    EnvUser = $env:USERNAME
    Caption = $os.Caption
    Version = $os.Version
    BuildNumber = $os.BuildNumber
    DisplayVersion = if ($nt.DisplayVersion) { $nt.DisplayVersion } else { $nt.ReleaseId }
    UBR = $nt.UBR
    Architecture = $arch
    Manufacturer = $cs.Manufacturer
    Model = $cs.Model
    SerialNumber = $bios.SerialNumber
    BiosVersion = $bios.SMBIOSBIOSVersion
    FirmwareType = $env:firmware_type
    InstallDate = $os.InstallDate
    LastBootUpTime = $os.LastBootUpTime
}
"""

_ARCHITECTURES = {"AMD64": "x64", "X86": "x86", "ARM64": "ARM64"}


def collect_system(ps: PowerShellRunner) -> SystemInfo:
    row = first(safe_query(ps, SCRIPT))
    if not row:
        return SystemInfo()
    return SystemInfo(
        hostname=text(row.get("Hostname")),
        user=text(row.get("UserName")) or text(row.get("EnvUser")),
        os_name=text(row.get("Caption")),
        os_version=text(row.get("DisplayVersion")) or text(row.get("Version")),
        os_build=_build(row),
        architecture=_architecture(row.get("Architecture")),
        manufacturer=clean(row.get("Manufacturer")),
        model=clean(row.get("Model")),
        serial_number=clean(row.get("SerialNumber")),
        bios_version=text(row.get("BiosVersion")),
        boot_mode=_boot_mode(row.get("FirmwareType")),
        install_date=cim_datetime(row.get("InstallDate")),
        last_boot=cim_datetime(row.get("LastBootUpTime")),
    )


def _build(row: dict) -> str:
    """Build plus update revision ("22631.4317"), as `winver` shows it."""
    build = text(row.get("BuildNumber"))
    revision = text(row.get("UBR"))
    return f"{build}.{revision}" if build and revision else build


def _architecture(value: object) -> str:
    raw = text(value)
    return _ARCHITECTURES.get(raw.upper(), raw)


def _boot_mode(value: object) -> str:
    raw = text(value).lower()
    if raw == "uefi":
        return "UEFI"
    if raw in {"legacy", "bios"}:
        return "Legacy"
    return ""
