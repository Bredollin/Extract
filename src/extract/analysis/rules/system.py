"""System rules: hardware errors, startup, uptime, power, antivirus, drivers."""

from __future__ import annotations

from extract.analysis import reference as ref
from extract.analysis.rules.base import (
    Context,
    Role,
    fmt,
    make_finding,
    number,
    rule,
)
from extract.core.models import (
    Category,
    Finding,
    Severity,
)


@rule(Role.FAULT)
def hardware_errors(ctx: Context) -> list[Finding]:
    """WHEA errors, blue screens and unexpected shutdowns in the event log."""
    whea = ctx.value("system.events", "whea_errors") or 0
    bugchecks = ctx.value("system.events", "bugchecks") or 0
    shutdowns = ctx.value("system.events", "unexpected_shutdowns") or 0
    if not (whea or bugchecks or shutdowns >= ref.UNEXPECTED_SHUTDOWNS_WARNING):
        return []
    days = ctx.value("system.events", "window_days")
    parts = [
        text
        for count, text in (
            (whea, f"{fmt(whea)} erros de hardware (WHEA)"),
            (bugchecks, f"{fmt(bugchecks)} telas azuis"),
            (shutdowns, f"{fmt(shutdowns)} desligamentos inesperados"),
        )
        if count
    ]
    period = f" nos últimos {fmt(days)} dias" if days else ""
    return make_finding(
        "system.hardware_errors",
        Category.SYSTEM,
        Severity.CRITICAL if whea or bugchecks else Severity.WARNING,
        "Erros de hardware no log do Windows",
        f"Foram registrados {', '.join(parts)}{period}. Isso aponta para defeito de hardware "
        "(memória, fonte, superaquecimento, placa) ou driver com problema.",
        "Testar a memória (Diagnóstico de Memória do Windows ou MemTest86), verificar "
        "temperaturas e a fonte/carregador, e atualizar BIOS e drivers de chipset.",
        whea_errors=whea,
        bugchecks=bugchecks,
        unexpected_shutdowns=shutdowns,
        window_days=days,
    )


@rule(Role.SOFTWARE)
def too_many_startup_programs(ctx: Context) -> list[Finding]:
    data = ctx.check("system.startup")
    count = number(data.get("count"))
    if count is None and isinstance(data.get("items"), list):
        count = float(len(data["items"]))
    if count is None or count < ref.STARTUP_INFO_COUNT:
        return []
    names = [str(i.get("name")) for i in data.get("items") or [] if isinstance(i, dict)][:8]
    listed = f" Alguns: {', '.join(names)}." if names else ""
    return make_finding(
        "system.startup",
        Category.SYSTEM,
        Severity.WARNING if count >= ref.STARTUP_WARNING_COUNT else Severity.INFO,
        "Muitos programas na inicialização",
        f"{fmt(count)} programas iniciam com o Windows, deixando a inicialização lenta e "
        f"ocupando memória.{listed}",
        "Desativar em Gerenciador de Tarefas > Inicializar o que não é necessário "
        "(atualizadores, mensageiros, launchers de jogos).",
        count=count,
    )


@rule(Role.SOFTWARE)
def long_uptime(ctx: Context) -> list[Finding]:
    days = ctx.value("system.uptime", "days")
    if days is None or days < ref.UPTIME_INFO_DAYS:
        return []
    return make_finding(
        "system.uptime",
        Category.SYSTEM,
        Severity.WARNING if days >= ref.UPTIME_WARNING_DAYS else Severity.INFO,
        "Muito tempo sem reiniciar",
        f"O Windows está ligado há {fmt(days)} dias sem reiniciar. Com a Inicialização Rápida, "
        "desligar não zera esse tempo; só Reiniciar faz isso.",
        "Reiniciar a máquina (Iniciar > Reiniciar) e repetir o teste se a lentidão continuar.",
        days=days,
    )


_REBOOT_REASONS = {
    "component_servicing": "atualização de componentes do Windows",
    "windows_update": "Windows Update",
    "file_rename": "arquivos aguardando substituição",
}


@rule(Role.SOFTWARE)
def pending_reboot(ctx: Context) -> list[Finding]:
    data = ctx.check("system.pending_reboot")
    if data.get("pending") is not True:
        return []
    reasons = [str(r) for r in data.get("reasons") or []]
    shown = [_REBOOT_REASONS.get(r, r) for r in reasons]
    return make_finding(
        "system.pending_reboot",
        Category.SYSTEM,
        Severity.INFO,
        "Reinicialização pendente",
        "Há atualizações ou instalações aguardando reinicialização"
        + (f" ({', '.join(shown)})." if shown else "."),
        "Reiniciar para concluir as atualizações antes de avaliar o desempenho.",
        reasons=reasons or None,
    )


@rule(Role.SOFTWARE)
def power_saver(ctx: Context) -> list[Finding]:
    if not ctx.flag("system.power_plan", "is_power_saver"):
        return []
    plan = ctx.check("system.power_plan").get("plan_name")
    return make_finding(
        "system.power_saver",
        Category.SYSTEM,
        Severity.WARNING,
        "Plano de energia em economia",
        f"O plano ativo{f' ({plan})' if plan else ''} limita o processador para economizar "
        "energia.",
        "Mudar para o plano Equilibrado (ou Alto desempenho em desktops) em Opções de Energia.",
        plan_name=plan,
    )


@rule(Role.OTHER)
def on_battery(ctx: Context) -> list[Finding]:
    if not ctx.flag("system.power_plan", "on_battery"):
        return []
    return make_finding(
        "system.on_battery",
        Category.SYSTEM,
        Severity.INFO,
        "Notebook na bateria durante o teste",
        "A máquina estava sem carregador; na bateria o Windows reduz o desempenho e os "
        "resultados dos testes ficam menores.",
        "Repetir os testes de desempenho com o carregador ligado.",
        on_battery=True,
    )


@rule(Role.SOFTWARE)
def antivirus_scan_running(ctx: Context) -> list[Finding]:
    if not ctx.flag("system.antivirus", "scan_in_progress"):
        return []
    return make_finding(
        "system.antivirus_scan",
        Category.SYSTEM,
        Severity.WARNING,
        "Verificação do antivírus em andamento",
        "O antivírus estava fazendo uma verificação durante a coleta, o que ocupa disco e "
        "processador e reduz os resultados dos testes.",
        "Aguardar o fim da verificação e repetir os testes; agendar verificações para fora do "
        "horário de uso.",
        scan_in_progress=True,
    )


_BUILT_IN_ANTIVIRUS = ("windows defender", "microsoft defender")


@rule(Role.SOFTWARE)
def multiple_antivirus(ctx: Context) -> list[Finding]:
    products = [str(p) for p in ctx.check("system.antivirus").get("products") or []]
    third_party = [p for p in products if not any(b in p.lower() for b in _BUILT_IN_ANTIVIRUS)]
    if len(third_party) < 2:
        return []
    return make_finding(
        "system.multiple_antivirus",
        Category.SYSTEM,
        Severity.WARNING,
        "Mais de um antivírus instalado",
        f"Estão instalados: {', '.join(third_party)}. Dois antivírus examinam cada arquivo "
        "em dobro e brigam entre si.",
        "Manter apenas um antivírus (o Microsoft Defender já é suficiente para a maioria).",
        products=third_party,
    )


@rule(Role.SOFTWARE)
def problem_devices(ctx: Context) -> list[Finding]:
    devices = [
        d for d in ctx.check("system.devices").get("problem_devices") or [] if isinstance(d, dict)
    ]
    if not devices:
        return []
    names = ", ".join(
        f"{d.get('name') or 'Dispositivo desconhecido'} (código {d.get('error_code')})"
        for d in devices[:6]
    )
    return make_finding(
        "system.problem_devices",
        Category.SYSTEM,
        Severity.WARNING,
        "Dispositivos com problema de driver",
        f"{len(devices)} dispositivo(s) com erro no Gerenciador de Dispositivos: {names}.",
        "Instalar os drivers corretos do fabricante (chipset, vídeo, rede, armazenamento).",
        count=len(devices),
        devices=[d.get("name") for d in devices],
    )


@rule(Role.SOFTWARE)
def app_crashes(ctx: Context) -> list[Finding]:
    crashes = ctx.value("system.events", "app_crashes")
    if crashes is None or crashes < ref.APP_CRASHES_INFO:
        return []
    return make_finding(
        "system.app_crashes",
        Category.SYSTEM,
        Severity.INFO,
        "Programas travando com frequência",
        f"O log registra {fmt(crashes)} travamentos de programas no período analisado.",
        "Ver no Visualizador de Eventos (ou Monitor de Confiabilidade) quais programas falham "
        "e atualizá-los ou reinstalá-los.",
        app_crashes=crashes,
        window_days=ctx.value("system.events", "window_days"),
    )
