"""Enabled network adapters: addresses, gateway, DNS and link speed."""

from __future__ import annotations

from extract.collectors._parse import as_list, first, text, to_bool, to_int
from extract.core.models import NetworkAdapter
from extract.core.powershell import PowerShellRunner, safe_query

# IP configuration comes from Win32_NetworkAdapterConfiguration (IPEnabled only); the
# friendly name ("Wi-Fi") and link speed come from Get-NetAdapter, joined by InterfaceIndex.
SCRIPT = """
[pscustomobject]@{
    Configs = @(Get-CimInstance Win32_NetworkAdapterConfiguration -Filter 'IPEnabled=True' |
        Select-Object InterfaceIndex, Description, MACAddress, IPAddress, DefaultIPGateway,
        DNSServerSearchOrder, DHCPEnabled)
    Adapters = @(Get-NetAdapter -ErrorAction SilentlyContinue |
        Select-Object InterfaceIndex, Name, InterfaceDescription, Status, Speed, MacAddress)
}
"""


def collect_network(ps: PowerShellRunner) -> list[NetworkAdapter]:
    row = first(safe_query(ps, SCRIPT))
    adapters = {
        to_int(a.get("InterfaceIndex"), -1): a
        for a in as_list(row.get("Adapters"))
        if isinstance(a, dict)
    }
    result = []
    for config in as_list(row.get("Configs")):
        if not isinstance(config, dict):
            continue
        adapter = adapters.get(to_int(config.get("InterfaceIndex"), -1), {})
        result.append(_adapter(config, adapter))
    return result


def _adapter(config: dict, adapter: dict) -> NetworkAdapter:
    description = text(config.get("Description")) or text(adapter.get("InterfaceDescription"))
    friendly = text(adapter.get("Name"))
    name = f"{friendly} ({description})" if friendly and description else friendly or description
    mac = text(config.get("MACAddress")) or text(adapter.get("MacAddress"))
    return NetworkAdapter(
        name=name,
        mac_address=mac.replace("-", ":").upper(),
        ipv4=_ipv4(config.get("IPAddress")),
        gateway=_ipv4(config.get("DefaultIPGateway")),
        dns_servers=[text(s) for s in as_list(config.get("DNSServerSearchOrder")) if text(s)],
        dhcp=to_bool(config.get("DHCPEnabled")),
        link_speed_mbps=to_int(adapter.get("Speed")) // 1_000_000,
    )


def _ipv4(value: object) -> list[str]:
    return [text(a) for a in as_list(value) if text(a) and ":" not in text(a)]
