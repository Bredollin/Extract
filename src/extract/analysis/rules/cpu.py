"""CPU rules: throttling, sustained load and overall processor strength."""

from __future__ import annotations

import re

from extract.analysis import reference as ref
from extract.analysis.rules.base import (
    Context,
    Role,
    fmt,
    join_known,
    make_finding,
    number,
    rule,
    top_process,
)
from extract.core.models import (
    Category,
    Finding,
    Severity,
)


@rule(Role.FAULT)
def cpu_throttling(ctx: Context) -> list[Finding]:
    clock_drop = ctx.metric("cpu.sustained", "clock_drop_percent")
    throughput_drop = ctx.metric("cpu.sustained", "throughput_drop_percent")
    drop = max((d for d in (clock_drop, throughput_drop) if d is not None), default=None)
    load = ctx.value("cpu.load", "load_percent")
    current = ctx.value("cpu.load", "current_clock_mhz")
    maximum = ctx.value("cpu.load", "max_clock_mhz")
    low_clock = (
        load is not None
        and current
        and maximum
        and load >= ref.LOW_CLOCK_MIN_LOAD_PERCENT
        and current < maximum * ref.LOW_CLOCK_SHARE
    )
    throttled = drop is not None and drop >= ref.THROTTLE_WARNING_PERCENT
    if not (throttled or low_clock):
        return []
    if throttled:
        detail = (
            f"Sob carga contínua o desempenho caiu {fmt(drop or 0)}% do início para o fim do "
            "teste: o processador reduz o clock para não superaquecer ou por limite de energia."
        )
    else:
        detail = (
            f"Com {fmt(load or 0)}% de uso, o processador estava a {current or 0:.0f} MHz "
            f"de {maximum or 0:.0f} MHz possíveis."
        )
    on_battery = ctx.flag("system.power_plan", "on_battery")
    battery_hint = " Teste novamente com o carregador ligado." if on_battery else ""
    return make_finding(
        "cpu.throttling",
        Category.CPU,
        Severity.CRITICAL if (drop or 0) >= ref.THROTTLE_CRITICAL_PERCENT else Severity.WARNING,
        "Processador perdendo desempenho por temperatura ou energia",
        detail + battery_hint,
        "Limpar poeira do cooler e das saídas de ar, trocar a pasta térmica e conferir o "
        "plano de energia e o carregador (notebooks).",
        clock_drop_percent=clock_drop,
        throughput_drop_percent=throughput_drop,
        clock_start_mhz=ctx.metric("cpu.sustained", "clock_start_mhz"),
        clock_end_mhz=ctx.metric("cpu.sustained", "clock_end_mhz"),
        load_percent=load if low_clock else None,
        current_clock_mhz=current if low_clock else None,
        max_clock_mhz=maximum if low_clock else None,
    )


@rule(Role.SOFTWARE)
def cpu_high_load(ctx: Context) -> list[Finding]:
    load = ctx.value("cpu.load", "load_percent")
    if load is None or load < ref.CPU_HIGH_LOAD_PERCENT:
        return []
    top = top_process(ctx, key="cpu_percent")
    top_cpu = number(top["cpu_percent"]) if top else None
    culprit = (
        f" O maior consumo é de {top['name']} ({fmt(top_cpu or 0)}%)."
        if top and (top_cpu or 0) >= ref.CPU_TOP_PROCESS_PERCENT
        else ""
    )
    return make_finding(
        "cpu.high_load",
        Category.CPU,
        Severity.WARNING,
        "Processador constantemente ocupado",
        f"Com a máquina parada, o processador estava em {fmt(load)}% de uso.{culprit}",
        "Identificar o processo no Gerenciador de Tarefas: atualização do Windows, antivírus, "
        "programa travado ou malware. Fazer uma verificação antimalware se o processo for "
        "desconhecido.",
        load_percent=load,
        top_process=top["name"] if top else None,
        top_process_cpu_percent=top_cpu,
    )


@rule(Role.REPLACE)
def weak_cpu(ctx: Context) -> list[Finding]:
    single = ctx.metric("cpu.single", "score")
    multi = ctx.metric("cpu.multi", "score")
    name = ctx.report.inventory.cpu.name
    if single is None and multi is None:
        if not name or not any(re.search(p, name) for p in ref.WEAK_CPU_NAME_PATTERNS):
            return []
        return make_finding(
            "cpu.weak",
            Category.CPU,
            # A name alone is weak evidence, so it informs but does not drive the verdict.
            Severity.INFO,
            "Processador de entrada ou antigo",
            f"O processador ({name}) é de linha de entrada ou de geração antiga e pode "
            "limitar o desempenho mesmo com SSD e RAM suficientes.",
            "Rodar os testes de desempenho para confirmar. Antes de investir em upgrades, "
            "avaliar se a troca da máquina não é mais econômica.",
            cpu_name=name,
        )
    very_weak = (single is not None and single < ref.CPU_SINGLE_VERY_WEAK) or (
        multi is not None and multi < ref.CPU_MULTI_VERY_WEAK
    )
    weak = (single is not None and single < ref.CPU_SINGLE_WEAK) or (
        multi is not None and multi < ref.CPU_MULTI_WEAK
    )
    if not weak:
        return []
    scores = join_known(
        (single, f"um núcleo {fmt(single or 0)} pts"),
        (multi, f"todos os núcleos {fmt(multi or 0)} pts"),
    )
    return make_finding(
        "cpu.weak",
        Category.CPU,
        Severity.CRITICAL if very_weak else Severity.WARNING,
        "Processador fraco para o uso atual",
        f"Notas do processador{f' ({name})' if name else ''}: {scores}. Referência: cerca de "
        f"1.000 pts por núcleo em um processador atual; abaixo de {fmt(ref.CPU_SINGLE_WEAK)} "
        "pts por núcleo, navegadores e sistemas modernos ficam lentos.",
        "SSD e RAM ajudam, mas não resolvem um processador fraco. Comparar o custo dos "
        "upgrades com o de uma máquina nova.",
        single_score=single,
        multi_score=multi,
        single_weak_below=ref.CPU_SINGLE_WEAK,
        multi_weak_below=ref.CPU_MULTI_WEAK,
    )
