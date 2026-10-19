"""System checks: startup programs, uptime, event log errors, power plan, antivirus,
devices with problems and pending reboot."""

from __future__ import annotations

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
    plural,
    rounded,
    to_float,
    to_int,
    worst,
)

STARTUP_ITEMS = {"warning": 15}
UPTIME_DAYS = {"warning": 14}
EVENT_WINDOW_DAYS = 7
# Counts over EVENT_WINDOW_DAYS that make the event check WARNING / CRITICAL.
EVENT_THRESHOLDS = {
    "disk_errors": {"warning": 1, "critical": 10},
    "whea_errors": {"warning": 1, "critical": 10},
    "bugchecks": {"warning": 1, "critical": 3},
    "unexpected_shutdowns": {"warning": 1, "critical": 5},
    "app_crashes": {"warning": 20, "critical": 100},
}
POWER_SAVER_GUID = "a1841308-3541-4fab-bc81-f71556f20b4a"
# Win32_Battery.BatteryStatus values meaning the machine is running on battery.
ON_BATTERY_CODES = {1, 4, 5}
# ConfigManagerErrorCode 22 (disabled by the user) and 45 (not plugged in) are not faults.
IGNORED_DEVICE_CODES = {22, 45}

# Entries disabled in Task Manager stay in the Run keys; StartupApproved marks them with an
# odd first byte, so they are filtered out here.
STARTUP_SCRIPT = r"""
$approved = 'Software\Microsoft\Windows\CurrentVersion\Explorer\StartupApproved\'
$disabled = @{}
foreach ($root in 'HKCU:\', 'HKLM:\') {
    foreach ($sub in 'Run', 'Run32', 'StartupFolder') {
        $key = Get-Item -Path ($root + $approved + $sub) -ErrorAction SilentlyContinue
        if (-not $key) { continue }
        foreach ($name in $key.GetValueNames()) {
            $value = $key.GetValue($name)
            if ($value -is [byte[]] -and $value.Length -gt 0 -and ($value[0] -band 1)) {
                $disabled[$name] = $true
            }
        }
    }
}
$items = @(Get-CimInstance Win32_StartupCommand | ForEach-Object {
    [pscustomobject]@{ Name = $_.Name; Command = $_.Command; Location = $_.Location }
})
$wow = 'HKLM\SOFTWARE\WOW6432Node\Microsoft\Windows\CurrentVersion\Run'
$props = Get-ItemProperty -Path ('Registry::' + $wow) -ErrorAction SilentlyContinue
if ($props) {
    $skip = 'PSPath', 'PSParentPath', 'PSChildName', 'PSDrive', 'PSProvider'
    foreach ($p in $props.PSObject.Properties) {
        if ($skip -notcontains $p.Name) {
            $items += [pscustomobject]@{
                Name = $p.Name; Command = [string]$p.Value; Location = $wow
            }
        }
    }
}
$items | Where-Object { -not ($disabled[[string]$_.Name] -or $disabled[[string]$_.Command]) }
"""

UPTIME_SCRIPT = """
$os = Get-CimInstance Win32_OperatingSystem
[pscustomobject]@{ UptimeHours = ((Get-Date) - $os.LastBootUpTime).TotalHours }
"""

# "No events found" is an error for Get-WinEvent; it is mapped to 0, while any other failure
# (for example access denied) gives null so it is not mistaken for a clean log.
EVENTS_SCRIPT = """
$since = (Get-Date).AddDays(-7)
function Get-EventCount($filter, $match) {
    try {
        $events = @(Get-WinEvent -FilterHashtable $filter -MaxEvents 500 -ErrorAction Stop)
        if ($match) { $events = @($events | Where-Object { $_.ProviderName -match $match }) }
        $events.Count
    } catch {
        if ($_.FullyQualifiedErrorId -like 'NoMatching*') { 0 } else { $null }
    }
}
[pscustomobject]@{
    WindowDays = 7
    DiskErrors = Get-EventCount @{ LogName = 'System'; Id = 7, 51, 55, 98, 129, 153;
        StartTime = $since } 'disk|ntfs|stor|nvme|ahci'
    WheaErrors = Get-EventCount @{ LogName = 'System';
        ProviderName = 'Microsoft-Windows-WHEA-Logger'; StartTime = $since } $null
    UnexpectedShutdowns = Get-EventCount @{ LogName = 'System';
        ProviderName = 'Microsoft-Windows-Kernel-Power'; Id = 41; StartTime = $since } $null
    BugChecks = Get-EventCount @{ LogName = 'System'; Id = 1001;
        StartTime = $since } 'BugCheck|WER-SystemErrorReporting'
    AppCrashes = Get-EventCount @{ LogName = 'Application'; ProviderName = 'Application Error';
        Id = 1000; StartTime = $since } $null
}
"""

# The active plan is read by GUID because powercfg prints localized names.
POWER_SCRIPT = r"""
$text = (powercfg /getactivescheme) -join ' '
$guid = $null; $name = $null
if ($text -match '[0-9a-fA-F]{8}-([0-9a-fA-F]{4}-){3}[0-9a-fA-F]{12}') { $guid = $Matches[0] }
if ($text -match '\(([^)]+)\)\s*$') { $name = $Matches[1] }
$battery = @(Get-CimInstance Win32_Battery) | Select-Object -First 1
[pscustomobject]@{
    SchemeGuid = $guid
    PlanName = $name
    BatteryStatus = $battery.BatteryStatus
}
"""

# SecurityCenter2 only exists on client editions; Get-MpComputerStatus only with Defender.
ANTIVIRUS_SCRIPT = """
$products = @()
try {
    $products = @(Get-CimInstance -Namespace root/SecurityCenter2 -ClassName AntiVirusProduct |
        ForEach-Object { [pscustomobject]@{ Name = $_.displayName; State = $_.productState } })
} catch { }
$mp = $null
try { $mp = Get-MpComputerStatus -ErrorAction Stop } catch { }
$scanning = $null
if ($mp) {
    $scanning = ($mp.QuickScanStartTime -gt $mp.QuickScanEndTime) -or
        ($mp.FullScanStartTime -gt $mp.FullScanEndTime)
}
[pscustomobject]@{
    Products = $products
    DefenderPresent = [bool]$mp
    DefenderEnabled = $mp.AntivirusEnabled
    DefenderRealTime = $mp.RealTimeProtectionEnabled
    ScanInProgress = $scanning
}
"""

DEVICES_SCRIPT = """
Get-CimInstance Win32_PnPEntity -Filter 'ConfigManagerErrorCode <> 0' |
    Select-Object Name, DeviceID, ConfigManagerErrorCode
"""

PENDING_REBOOT_SCRIPT = r"""
$reasons = @()
$cbs = 'HKLM:\SOFTWARE\Microsoft\Windows\CurrentVersion\Component Based Servicing\RebootPending'
$wu = 'HKLM:\SOFTWARE\Microsoft\Windows\CurrentVersion\WindowsUpdate\Auto Update\RebootRequired'
if (Test-Path $cbs) { $reasons += 'component_servicing' }
if (Test-Path $wu) { $reasons += 'windows_update' }
$session = 'HKLM:\SYSTEM\CurrentControlSet\Control\Session Manager'
$sm = Get-ItemProperty -Path $session -ErrorAction SilentlyContinue
if ($sm -and $sm.PendingFileRenameOperations) { $reasons += 'file_rename' }
[pscustomobject]@{ Reasons = $reasons }
"""

_REBOOT_REASONS = {
    "component_servicing": "atualização de componentes do Windows",
    "windows_update": "Windows Update",
    "file_rename": "arquivos aguardando substituição",
}
_DEVICE_ERRORS = {
    1: "não configurado corretamente",
    3: "driver corrompido ou falta de memória",
    10: "não pode ser iniciado",
    12: "sem recursos livres",
    18: "precisa reinstalar o driver",
    19: "configuração do registro danificada",
    28: "driver não instalado",
    31: "não está funcionando corretamente",
    39: "driver ausente ou corrompido",
    43: "parado após relatar problemas",
    52: "driver sem assinatura digital",
}
_EVENT_LABELS = {
    "disk_errors": ("erro de disco", "erros de disco"),
    "whea_errors": ("erro de hardware (WHEA)", "erros de hardware (WHEA)"),
    "bugchecks": ("tela azul", "telas azuis"),
    "unexpected_shutdowns": ("desligamento inesperado", "desligamentos inesperados"),
    "app_crashes": ("travamento de programa", "travamentos de programas"),
}


@health_check(
    "system.startup",
    Category.SYSTEM,
    "Programas na inicialização",
    ["count", "items"],
)
def check_startup(ps: PowerShellRunner, inventory: Inventory) -> Outcome:
    items: list[dict[str, Any]] = []
    seen: set[tuple[str, str]] = set()
    for row in ps.query(STARTUP_SCRIPT):
        name = str(row.get("Name") or "").strip()
        command = str(row.get("Command") or "").strip()
        if not (name or command) or (name.lower(), command.lower()) in seen:
            continue
        seen.add((name.lower(), command.lower()))
        items.append({"name": name, "command": command, "location": row.get("Location")})

    status = level(len(items), STARTUP_ITEMS["warning"], float("inf"))
    summary = f"{plural(len(items), 'programa inicia', 'programas iniciam')} com o Windows."
    return Outcome(status, summary, {"count": len(items), "items": items})


@health_check("system.uptime", Category.SYSTEM, "Tempo ligado", ["days"])
def check_uptime(ps: PowerShellRunner, inventory: Inventory) -> Outcome:
    hours = to_float(first_row(ps.query(UPTIME_SCRIPT)).get("UptimeHours"))
    if hours is None:
        raise ValueError("uptime unavailable")
    days = hours / 24
    status = level(days, UPTIME_DAYS["warning"], float("inf"))
    if days < 1:
        summary = f"Ligado há {fmt(hours)} horas desde a última reinicialização."
    else:
        summary = f"Ligado há {fmt(days, 1)} dias desde a última reinicialização."
    if status is not Status.OK:
        summary += " Com a Inicialização Rápida ativa, desligar não zera este tempo; use Reiniciar."
    return Outcome(status, summary, {"days": rounded(days)})


@health_check(
    "system.events",
    Category.SYSTEM,
    "Erros no log de eventos",
    ["window_days", *EVENT_THRESHOLDS],
)
def check_events(ps: PowerShellRunner, inventory: Inventory) -> Outcome:
    row = first_row(ps.query(EVENTS_SCRIPT, timeout=120))
    counts = {
        "disk_errors": to_int(row.get("DiskErrors")),
        "whea_errors": to_int(row.get("WheaErrors")),
        "unexpected_shutdowns": to_int(row.get("UnexpectedShutdowns")),
        "bugchecks": to_int(row.get("BugChecks")),
        "app_crashes": to_int(row.get("AppCrashes")),
    }
    if all(v is None for v in counts.values()):
        raise ValueError("event log unreadable")
    days = to_int(row.get("WindowDays")) or EVENT_WINDOW_DAYS

    status = worst(
        *(level(counts[k], t["warning"], t["critical"]) for k, t in EVENT_THRESHOLDS.items())
    )
    found = [plural(counts[key], *labels) for key, labels in _EVENT_LABELS.items() if counts[key]]
    if found:
        summary = f"Nos últimos {days} dias: {', '.join(found)}."
    else:
        summary = f"Nenhum erro relevante nos últimos {days} dias."
    if any(v is None for v in counts.values()):
        summary += " Parte do log não pôde ser lida."
    return Outcome(status, summary, {"window_days": days, **counts})


@health_check(
    "system.power_plan",
    Category.SYSTEM,
    "Plano de energia",
    ["plan_name", "is_power_saver", "on_battery"],
)
def check_power_plan(ps: PowerShellRunner, inventory: Inventory) -> Outcome:
    row = first_row(ps.query(POWER_SCRIPT))
    guid = str(row.get("SchemeGuid") or "").lower()
    if not guid:
        raise ValueError("active power scheme unavailable")
    name = row.get("PlanName") or guid
    is_saver = guid == POWER_SAVER_GUID
    on_battery = to_int(row.get("BatteryStatus")) in ON_BATTERY_CODES

    status = Status.WARNING if is_saver else Status.OK
    summary = f"Plano de energia ativo: {name}."
    if is_saver:
        summary += " O modo economia limita o desempenho do processador."
    if on_battery:
        summary += " Funcionando na bateria."
    return Outcome(
        status,
        summary,
        {"plan_name": name, "is_power_saver": is_saver, "on_battery": on_battery},
    )


def _product_enabled(state: Any) -> bool:
    """Bits 12-13 of SecurityCenter2's productState are set when protection is on."""
    value = to_int(state)
    return value is not None and bool(value & 0x1000)


@health_check(
    "system.antivirus",
    Category.SYSTEM,
    "Antivírus",
    ["products", "realtime_enabled", "scan_in_progress"],
)
def check_antivirus(ps: PowerShellRunner, inventory: Inventory) -> Outcome:
    """`products` lists only products with protection on (Defender in passive mode is not)."""
    row = first_row(ps.query(ANTIVIRUS_SCRIPT))
    products = [p for p in as_list(row.get("Products")) if isinstance(p, dict) and p.get("Name")]
    active = [str(p["Name"]) for p in products if _product_enabled(p.get("State"))]
    defender_on = bool(row.get("DefenderEnabled")) and bool(row.get("DefenderRealTime"))
    if not products and defender_on:
        active = ["Microsoft Defender Antivirus"]
    if products:
        realtime: bool | None = bool(active)
    elif row.get("DefenderPresent"):
        realtime = defender_on
    else:
        raise ValueError("no antivirus information")
    scanning = row.get("ScanInProgress")
    scanning = None if scanning is None else bool(scanning)

    problems: list[str] = []
    if not active:
        problems.append("nenhum antivírus com proteção ativa")
    if len(active) > 1:
        problems.append("mais de um antivírus ativo ao mesmo tempo (pode deixar a máquina lenta)")
    if scanning:
        problems.append("verificação do Defender em andamento")
    status = Status.WARNING if problems else Status.OK
    summary = f"Antivírus ativo: {', '.join(active) or 'nenhum'}."
    if problems:
        text = "; ".join(problems)
        summary += f" {text[0].upper()}{text[1:]}."
    return Outcome(
        status,
        summary,
        {
            "products": active,
            "realtime_enabled": realtime,
            "scan_in_progress": scanning,
        },
    )


def _describe_device(device: dict[str, Any]) -> str:
    code = device["error_code"]
    meaning = _DEVICE_ERRORS.get(code)
    return f"{device['name']} (código {code}{': ' + meaning if meaning else ''})"


@health_check(
    "system.devices",
    Category.SYSTEM,
    "Dispositivos com problema",
    ["problem_devices"],
)
def check_devices(ps: PowerShellRunner, inventory: Inventory) -> Outcome:
    devices = []
    for row in ps.query(DEVICES_SCRIPT):
        code = to_int(row.get("ConfigManagerErrorCode"))
        if not code or code in IGNORED_DEVICE_CODES:
            continue
        name = row.get("Name") or row.get("DeviceID") or "Dispositivo desconhecido"
        devices.append({"name": str(name), "error_code": code})

    if not devices:
        return Outcome(Status.OK, "Nenhum dispositivo com problema.", {"problem_devices": []})
    summary = (
        f"{plural(len(devices), 'dispositivo com problema', 'dispositivos com problema')}: "
        f"{'; '.join(_describe_device(d) for d in devices)}."
    )
    return Outcome(Status.WARNING, summary, {"problem_devices": devices})


@health_check(
    "system.pending_reboot",
    Category.SYSTEM,
    "Reinicialização pendente",
    ["pending", "reasons"],
)
def check_pending_reboot(ps: PowerShellRunner, inventory: Inventory) -> Outcome:
    row = first_row(ps.query(PENDING_REBOOT_SCRIPT))
    reasons = [str(r) for r in as_list(row.get("Reasons"))]
    if not reasons:
        return Outcome(
            Status.OK, "Nenhuma reinicialização pendente.", {"pending": False, "reasons": []}
        )
    described = ", ".join(_REBOOT_REASONS.get(r, r) for r in reasons)
    return Outcome(
        Status.WARNING,
        f"Reinicialização pendente ({described}).",
        {"pending": True, "reasons": reasons},
    )
