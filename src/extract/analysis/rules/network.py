"""Network rules: local network, internet, DNS and Wi-Fi."""

from __future__ import annotations

from extract.analysis import reference as ref
from extract.analysis.rules.base import (
    Context,
    Role,
    fmt,
    join_known,
    make_finding,
    rule,
)
from extract.core.models import (
    Category,
    Finding,
    Severity,
)


def _loss_severity(loss: float | None) -> Severity:
    return (
        Severity.CRITICAL
        if loss is not None and loss >= ref.LOSS_CRITICAL_PERCENT
        else Severity.WARNING
    )


def _latency_and_loss(latency: float | None, loss: float | None) -> str:
    return join_known(
        (latency, f"{fmt(latency or 0)} ms de resposta"), (loss, f"{fmt(loss or 0)}% de perda")
    )


@rule(Role.NETWORK)
def local_network(ctx: Context) -> list[Finding]:
    latency = ctx.value("network.connectivity", "gateway_ms")
    loss = ctx.value("network.connectivity", "gateway_loss_percent")
    if not (
        (loss is not None and loss >= ref.LOSS_WARNING_PERCENT)
        or (latency is not None and latency >= ref.GATEWAY_LATENCY_WARNING_MS)
    ):
        return []
    return make_finding(
        "network.local",
        Category.NETWORK,
        _loss_severity(loss),
        "Conexão instável com o roteador",
        f"Até o roteador: {_latency_and_loss(latency, loss)} (o normal é menos de 5 ms e "
        "nenhuma perda). Páginas e sistemas na rede vão demorar ou falhar.",
        "Verificar cabo, porta do switch ou, no Wi-Fi, a distância e interferência; "
        "reiniciar o roteador.",
        gateway_ms=latency,
        gateway_loss_percent=loss,
    )


@rule(Role.NETWORK)
def internet_connection(ctx: Context) -> list[Finding]:
    latency = ctx.value("network.connectivity", "internet_ms")
    loss = ctx.value("network.connectivity", "internet_loss_percent")
    if not (
        (loss is not None and loss >= ref.LOSS_WARNING_PERCENT)
        or (latency is not None and latency >= ref.INTERNET_LATENCY_WARNING_MS)
    ):
        return []
    return make_finding(
        "network.internet",
        Category.NETWORK,
        _loss_severity(loss),
        "Internet lenta ou instável",
        f"Até a internet: {_latency_and_loss(latency, loss)}. Se a rede local está boa, o "
        "problema é do provedor.",
        "Testar em outro dispositivo na mesma rede e acionar o provedor se confirmar.",
        internet_ms=latency,
        internet_loss_percent=loss,
    )


@rule(Role.NETWORK)
def slow_dns(ctx: Context) -> list[Finding]:
    dns = ctx.value("network.connectivity", "dns_ms")
    if dns is None or dns < ref.DNS_WARNING_MS:
        return []
    return make_finding(
        "network.dns",
        Category.NETWORK,
        Severity.WARNING,
        "Resolução de nomes (DNS) lenta",
        f"Cada endereço novo leva {fmt(dns)} ms só para ser encontrado, então sites e "
        "sistemas demoram a começar a abrir.",
        "Configurar um DNS mais rápido no roteador ou na placa de rede (por exemplo, o do "
        "provedor ou um DNS público confiável).",
        dns_ms=dns,
    )


@rule(Role.NETWORK)
def weak_wifi(ctx: Context) -> list[Finding]:
    signal = ctx.value("network.wifi", "signal_percent")
    link = ctx.value("network.wifi", "link_speed_mbps")
    weak_signal = signal is not None and signal < ref.WIFI_SIGNAL_WARNING_PERCENT
    slow_link = link is not None and link < ref.WIFI_LINK_WARNING_MBPS
    if not (weak_signal or slow_link):
        return []
    return make_finding(
        "network.wifi",
        Category.NETWORK,
        Severity.WARNING,
        "Sinal de Wi-Fi fraco",
        join_known(
            (signal, f"Sinal de {fmt(signal or 0)}%"),
            (link, f"velocidade de conexão de {fmt(link or 0)} Mbps"),
        )
        + ". Com sinal fraco, a conexão cai e as páginas demoram a carregar.",
        "Aproximar a máquina do roteador, usar cabo, um repetidor/mesh ou um adaptador Wi-Fi "
        "melhor.",
        signal_percent=signal,
        link_speed_mbps=link,
    )
