"""Network checks: gateway and internet reachability, DNS resolution time and Wi-Fi signal.

Everything is resolved from the default IPv4 route, so the checks look at the connection
the machine actually uses. Parsing never depends on the Windows display language.
"""

from __future__ import annotations

from extract.core.models import Category, Inventory, Status
from extract.core.powershell import PowerShellRunner

from .base import Outcome, first_row, fmt, health_check, level, rounded, to_float, to_int, worst

GATEWAY_MS = {"warning": 20, "critical": 100}
INTERNET_MS = {"warning": 150, "critical": 400}
LOSS_PERCENT = {"warning": 5, "critical": 30}
DNS_MS = {"warning": 200, "critical": 1000}
# Signal as Windows reports it (0-100 %), at or below.
WIFI_SIGNAL_PERCENT = {"warning": 50, "critical": 30}
WIFI_LINK_MBPS = {"warning": 20, "critical": 6}

# The default route with the lowest total metric; NextHop 0.0.0.0 means "on-link" (no gateway).
_DEFAULT_ROUTE = """
$route = Get-NetRoute -DestinationPrefix '0.0.0.0/0' -ErrorAction SilentlyContinue |
    Sort-Object { $_.RouteMetric + $_.InterfaceMetric } | Select-Object -First 1
$gateway = $null
if ($route -and $route.NextHop -ne '0.0.0.0') { $gateway = $route.NextHop }
"""

# .NET Ping behaves the same on every PowerShell version and language; each target gets a
# fixed number of echoes with a 1 s timeout. DNS queries go straight to the configured
# server so the local cache does not hide a slow resolver.
CONNECTIVITY_SCRIPT = (
    _DEFAULT_ROUTE
    + """
function Measure-Ping($target, $count) {
    if (-not $target) { return $null }
    $ping = New-Object System.Net.NetworkInformation.Ping
    $times = @(); $lost = 0
    for ($i = 0; $i -lt $count; $i++) {
        try {
            $reply = $ping.Send($target, 1000)
            if ($reply.Status -eq 'Success') { $times += $reply.RoundtripTime } else { $lost++ }
        } catch { $lost++ }
    }
    $avg = $null
    if ($times.Count) { $avg = ($times | Measure-Object -Average).Average }
    [pscustomobject]@{ Sent = $count; Lost = $lost; AvgMs = $avg }
}
$dnsServer = $null
if ($route) {
    $servers = Get-DnsClientServerAddress -InterfaceIndex $route.InterfaceIndex `
        -AddressFamily IPv4 -ErrorAction SilentlyContinue
    $dnsServer = @($servers.ServerAddresses) | Select-Object -First 1
}
$dnsTimes = @()
foreach ($name in 'www.microsoft.com', 'www.google.com', 'www.wikipedia.org') {
    $watch = [System.Diagnostics.Stopwatch]::StartNew()
    $query = @{ Name = $name; Type = 'A'; DnsOnly = $true; ErrorAction = 'Stop' }
    if ($dnsServer) { $query.Server = $dnsServer }
    try {
        $null = Resolve-DnsName @query
        $dnsTimes += $watch.Elapsed.TotalMilliseconds
    } catch { }
}
[pscustomobject]@{
    HasRoute = [bool]$route
    Gateway = Measure-Ping $gateway 10
    Internet = @((Measure-Ping '1.1.1.1' 5), (Measure-Ping '8.8.8.8' 5))
    DnsMs = if ($dnsTimes.Count) { ($dnsTimes | Measure-Object -Average).Average } else { $null }
}
"""
)

# netsh output is localized, so fields are recognized by shape: "SSID" is never translated,
# the signal is the only value ending in "%", and rates are the keys containing "(Mbps)".
# The Wi-Fi adapter is identified by its physical medium (9 = Native 802.11).
WIFI_SCRIPT = (
    _DEFAULT_ROUTE
    + r"""
$adapter = $null
if ($route) {
    $adapter = Get-NetAdapter -InterfaceIndex $route.InterfaceIndex -ErrorAction SilentlyContinue
}
$onWifi = $adapter -and $adapter.NdisPhysicalMedium -eq 9
$lines = @()
if ($onWifi) { $lines = @(netsh wlan show interfaces) }
$blocks = @(); $current = $null; $firstKey = $null
foreach ($line in $lines) {
    if ($line -notmatch '^\s*([^:]+?)\s+:\s(.*)$') { continue }
    $key = $Matches[1].Trim(); $value = $Matches[2].Trim()
    if (-not $firstKey) { $firstKey = $key }
    if ($key -eq $firstKey) { $current = @{ Name = $value; Rates = @() }; $blocks += $current }
    if ($key -eq 'SSID') { $current.SsidPresent = [bool]$value }
    elseif ($value -match '^(\d+)\s*%$') { $current.Signal = [int]$Matches[1] }
    elseif ($key -match '\(Mbps\)' -and $value -match '^[\d.,]+$') {
        $current.Rates += [double]($value -replace ',', '.')
    }
}
$block = $blocks | Where-Object { $_.Name -eq $adapter.Name } | Select-Object -First 1
if (-not $block) { $block = $blocks | Where-Object { $_.SsidPresent } | Select-Object -First 1 }
[pscustomobject]@{
    OnWifi = [bool]$onWifi
    SsidPresent = [bool]$block.SsidPresent
    Signal = $block.Signal
    ReceiveMbps = if ($block -and $block.Rates.Count) { $block.Rates[0] } else { $null }
}
"""
)


def _ping_stats(rows: list[object]) -> tuple[float | None, float | None]:
    """Average latency over the targets that answered and the overall loss percentage."""
    sent = lost = 0
    latencies: list[float] = []
    for row in rows:
        if not isinstance(row, dict):
            continue
        sent += to_int(row.get("Sent")) or 0
        lost += to_int(row.get("Lost")) or 0
        avg = to_float(row.get("AvgMs"))
        if avg is not None:
            latencies.append(avg)
    if not sent:
        return None, None
    latency = sum(latencies) / len(latencies) if latencies else None
    return latency, lost / sent * 100


@health_check(
    "network.connectivity",
    Category.NETWORK,
    "Conectividade de rede",
    ["gateway_ms", "gateway_loss_percent", "internet_ms", "internet_loss_percent", "dns_ms"],
)
def check_connectivity(ps: PowerShellRunner, inventory: Inventory) -> Outcome:
    row = first_row(ps.query(CONNECTIVITY_SCRIPT, timeout=120))
    gateway_ms, gateway_loss = _ping_stats([row.get("Gateway")])
    internet = row.get("Internet")
    internet_ms, internet_loss = _ping_stats(internet if isinstance(internet, list) else [internet])
    dns_ms = to_float(row.get("DnsMs"))
    # Some routers ignore ping: a silent gateway while the internet answers is not loss.
    gateway_ignores_ping = gateway_ms is None and bool(gateway_loss) and internet_ms is not None
    if gateway_ignores_ping:
        gateway_loss = None
    data = {
        "gateway_ms": rounded(gateway_ms),
        "gateway_loss_percent": rounded(gateway_loss),
        "internet_ms": rounded(internet_ms),
        "internet_loss_percent": rounded(internet_loss),
        "dns_ms": rounded(dns_ms),
    }

    if not row.get("HasRoute"):
        return Outcome(Status.CRITICAL, "Sem rota padrão: a máquina não está em rede.", data)

    status = worst(
        level(gateway_ms, GATEWAY_MS["warning"], GATEWAY_MS["critical"]),
        level(gateway_loss, LOSS_PERCENT["warning"], LOSS_PERCENT["critical"]),
        level(internet_ms, INTERNET_MS["warning"], INTERNET_MS["critical"]),
        level(internet_loss, LOSS_PERCENT["warning"], LOSS_PERCENT["critical"]),
        level(dns_ms, DNS_MS["warning"], DNS_MS["critical"]),
    )
    parts = []
    if gateway_ms is not None:
        parts.append(f"roteador {fmt(gateway_ms)} ms ({fmt(gateway_loss)}% de perda)")
    elif gateway_ignores_ping:
        parts.append("roteador não responde a ping")
    elif gateway_loss is not None:
        parts.append("roteador sem resposta")
    if internet_ms is None:
        parts.append("internet sem resposta")
    else:
        parts.append(f"internet {fmt(internet_ms)} ms ({fmt(internet_loss)}% de perda)")
    if dns_ms is None:
        parts.append("DNS sem resposta")
        # Pings may be blocked by a firewall, but no DNS at all means nothing opens.
        status = worst(status, Status.CRITICAL if internet_ms is None else Status.WARNING)
    else:
        parts.append(f"DNS {fmt(dns_ms)} ms")
    summary = ", ".join(parts)
    return Outcome(status, summary[0].upper() + summary[1:] + ".", data)


@health_check(
    "network.wifi",
    Category.NETWORK,
    "Sinal do Wi-Fi",
    ["ssid_present", "signal_percent", "link_speed_mbps"],
)
def check_wifi(ps: PowerShellRunner, inventory: Inventory) -> Outcome | None:
    """Returns `None` when the machine is not connected through Wi-Fi."""
    rows = ps.query(WIFI_SCRIPT)
    if not rows or not rows[0].get("OnWifi"):
        return None
    row = rows[0]
    signal = to_int(row.get("Signal"))
    link = to_float(row.get("ReceiveMbps"))
    data = {
        "ssid_present": bool(row.get("SsidPresent")),
        "signal_percent": signal,
        "link_speed_mbps": rounded(link),
    }
    if signal is None:
        # Windows 11 24H2 hides Wi-Fi details from netsh unless location access is allowed.
        return Outcome(
            Status.UNKNOWN,
            "Conectado via Wi-Fi, mas o sinal não pôde ser lido "
            "(verifique a permissão de localização do Windows).",
            data,
        )
    status = worst(
        level(signal, WIFI_SIGNAL_PERCENT["warning"], WIFI_SIGNAL_PERCENT["critical"], below=True),
        level(link, WIFI_LINK_MBPS["warning"], WIFI_LINK_MBPS["critical"], below=True),
    )
    summary = f"Conectado via Wi-Fi com sinal de {signal}%"
    if link is not None:
        summary += f" e velocidade de {fmt(link, 1 if link < 10 else 0)} Mbps"
    return Outcome(status, summary + ".", data)
