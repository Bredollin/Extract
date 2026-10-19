"""Memory rules: amount, pressure, dual channel and speed."""

from __future__ import annotations

import re

from extract.analysis import reference as ref
from extract.analysis.rules.base import (
    Context,
    Role,
    fmt,
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


def _memory_under_pressure(ctx: Context) -> bool:
    used = ctx.value("memory.pressure", "used_percent")
    commit = ctx.value("memory.pressure", "commit_percent")
    faults = ctx.value("memory.pressure", "hard_faults_per_s")
    return (
        (used is not None and used >= ref.MEMORY_USED_WARNING_PERCENT)
        or (commit is not None and commit >= ref.MEMORY_COMMIT_WARNING_PERCENT)
        or (faults is not None and faults >= ref.HARD_FAULTS_WARNING_PER_S)
    )


def _pressure_evidence(ctx: Context) -> dict[str, float | None]:
    keys = ("used_percent", "commit_percent", "hard_faults_per_s", "available_mb")
    return {k: ctx.value("memory.pressure", k) for k in keys}


@rule(Role.UPGRADE)
def ram_too_small(ctx: Context) -> list[Finding]:
    total = ctx.ram_total_gb
    if total is None:
        return []
    minimum = ref.RAM_MIN_GB_MODERN if ctx.is_modern_windows else ref.RAM_MIN_GB_LEGACY
    pressure = _memory_under_pressure(ctx)
    tolerance = ref.RAM_SIZE_TOLERANCE_GB
    if total + tolerance < minimum:
        target = minimum
        critical = pressure or (
            ctx.is_modern_windows and total < ref.RAM_CRITICAL_GB_MODERN + tolerance
        )
        detail = (
            f"A máquina tem {fmt(total, 1)} GB de RAM; o mínimo prático para "
            f"{ctx.os_name or 'o Windows atual'} é {fmt(minimum)} GB."
        )
    elif pressure and total + tolerance < ref.RAM_RECOMMENDED_GB:
        target = ref.RAM_RECOMMENDED_GB
        critical = False
        detail = (
            f"A máquina tem {fmt(total, 1)} GB de RAM e a memória está no limite durante o "
            "uso atual."
        )
    else:
        return []
    detail += " Quando falta RAM, o Windows usa o disco como memória e tudo fica lento."
    return make_finding(
        "memory.low_total",
        Category.MEMORY,
        Severity.CRITICAL if critical else Severity.WARNING,
        "Pouca memória RAM",
        detail,
        f"Ampliar para {fmt(target)} GB, de preferência em dois pentes iguais (dual channel).",
        total_gb=total,
        recommended_total_gb=target,
        **_pressure_evidence(ctx),
    )


@rule(Role.SOFTWARE)
def memory_pressure(ctx: Context) -> list[Finding]:
    """Memory pressure on a machine that already has enough RAM: a program is the cause."""
    total = ctx.ram_total_gb
    if not _memory_under_pressure(ctx) or (
        total is not None and total + ref.RAM_SIZE_TOLERANCE_GB < ref.RAM_RECOMMENDED_GB
    ):
        return []
    used = ctx.value("memory.pressure", "used_percent")
    commit = ctx.value("memory.pressure", "commit_percent")
    critical = (used is not None and used >= ref.MEMORY_USED_CRITICAL_PERCENT) or (
        commit is not None and commit >= ref.MEMORY_COMMIT_CRITICAL_PERCENT
    )
    top = top_process(ctx, key="memory_mb")
    top_mb = number(top["memory_mb"]) if top else None
    culprit = (
        f" O processo que mais usa memória é {top['name']} ({fmt(top_mb or 0)} MB)." if top else ""
    )
    return make_finding(
        "memory.pressure",
        Category.MEMORY,
        Severity.CRITICAL if critical else Severity.WARNING,
        "Memória no limite",
        "A memória está quase esgotada mesmo com quantidade adequada instalada, o que "
        "indica um programa consumindo demais." + culprit,
        "Verificar no Gerenciador de Tarefas quais programas ocupam mais memória; fechar, "
        "atualizar ou remover o responsável (extensões de navegador são suspeitas comuns).",
        total_gb=total,
        top_process=top["name"] if top else None,
        **_pressure_evidence(ctx),
    )


_CHANNEL_PATTERNS = (
    re.compile(r"channel\s*-?\s*([A-H])\b", re.IGNORECASE),
    re.compile(r"\bDIMM[_ ]?([A-H])\d\b", re.IGNORECASE),
    re.compile(r"^([A-H])\d$", re.IGNORECASE),
)


def memory_channel(slot: str) -> str | None:
    """Channel letter from a slot name such as 'ChannelA-DIMM0' or 'DIMM_B1', if any."""
    for pattern in _CHANNEL_PATTERNS:
        match = pattern.search(slot.strip())
        if match:
            return match.group(1).upper()
    return None


@rule(Role.UPGRADE)
def single_channel_memory(ctx: Context) -> list[Finding]:
    memory = ctx.report.inventory.memory
    modules = memory.modules
    if not modules:
        return []
    channels = {memory_channel(m.slot) for m in modules}
    if len(modules) == 1:
        if memory.total_slots < 2:
            return []
        reason = "Há apenas um pente de memória instalado"
    elif None not in channels and len(channels) == 1:
        reason = f"Os {len(modules)} pentes estão no mesmo canal ({channels.pop()})"
    else:
        return []
    copy = ctx.metric("memory.bandwidth", "copy_gb_s")
    slow = copy is not None and copy < ref.MEMORY_COPY_LOW_GB_S
    measured = f" A cópia de memória mediu {fmt(copy, 1)} GB/s." if copy is not None else ""
    module = modules[0]
    pair = " ".join(
        p
        for p in (
            f"{fmt(module.capacity_gb)} GB" if module.capacity_gb else "",
            module.memory_type,
            f"{module.speed_mhz} MHz" if module.speed_mhz else "",
        )
        if p
    )
    recommendation = (
        f"Adicionar um pente igual ({pair}) no canal livre para ativar o dual channel."
        if len(modules) == 1
        else "Redistribuir os pentes nos slots indicados no manual da placa (canais A e B)."
    )
    return make_finding(
        "memory.single_channel",
        Category.MEMORY,
        Severity.WARNING if slow else Severity.INFO,
        "Memória em canal único",
        f"{reason}, então a memória trabalha em single channel, com metade da largura de "
        "banda possível. O impacto é maior em vídeo integrado e multitarefa." + measured,
        recommendation,
        modules=len(modules),
        total_slots=memory.total_slots or None,
        copy_gb_s=copy,
        module_capacity_gb=module.capacity_gb or None,
    )


@rule(Role.SOFTWARE)
def ram_below_rated_speed(ctx: Context) -> list[Finding]:
    slow = [
        m
        for m in ctx.report.inventory.memory.modules
        if m.speed_mhz
        and m.configured_speed_mhz
        and m.configured_speed_mhz < m.speed_mhz * ref.MEMORY_SPEED_MIN_SHARE
    ]
    if not slow:
        return []
    module = slow[0]
    return make_finding(
        "memory.below_rated_speed",
        Category.MEMORY,
        Severity.INFO,
        "Memória abaixo da velocidade nominal",
        f"Pentes de {module.speed_mhz} MHz estão trabalhando a "
        f"{module.configured_speed_mhz} MHz. Pode ser o perfil XMP/EXPO desativado, "
        "pentes misturados ou o limite do processador/placa.",
        "Conferir na BIOS o perfil XMP/EXPO e se o processador suporta essa velocidade. "
        "Ganho moderado; não é causa de lentidão grave.",
        rated_mhz=module.speed_mhz,
        configured_mhz=module.configured_speed_mhz,
    )
