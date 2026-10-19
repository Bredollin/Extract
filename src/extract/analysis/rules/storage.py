"""Storage rules: disk health, disk type and speed, disk load, free space."""

from __future__ import annotations

from typing import Any

from extract.analysis import reference as ref
from extract.analysis.rules.base import (
    Context,
    Role,
    disk_kind,
    fmt,
    join_known,
    make_finding,
    number,
    rule,
)
from extract.core.models import (
    Category,
    Finding,
    Severity,
    Status,
)


def _disk_problems(disk: dict[str, Any]) -> tuple[list[str], bool]:
    """Problems found in one disk of `storage.health`, and whether any is critical.

    The error counters in the data are totals (corrected errors included, which are normal
    on HDDs); uncorrected errors only show up in the check's status, handled by the caller.
    """
    problems: list[str] = []
    critical = False
    status = str(disk.get("health_status") or "")
    if status.lower() in ("unhealthy", "warning"):
        problems.append(f"o Windows informa o estado “{status}”")
        critical = status.lower() == "unhealthy"
    wear = number(disk.get("wear_percent"))
    if wear is not None and wear >= ref.DISK_WEAR_WARNING_PERCENT:
        problems.append(f"desgaste de {fmt(wear)}% da vida útil")
        critical = critical or wear >= ref.DISK_WEAR_CRITICAL_PERCENT
    temperature = number(disk.get("temperature_c"))
    media = "hdd" if str(disk.get("media_type") or "").upper() == "HDD" else "ssd"
    if temperature is not None and temperature >= ref.DISK_TEMP_WARNING_C[media]:
        problems.append(f"temperatura de {fmt(temperature)} °C")
    return problems, critical


_DISK_EVIDENCE_KEYS = (
    "model",
    "health_status",
    "wear_percent",
    "temperature_c",
    "read_errors_total",
    "write_errors_total",
)


@rule(Role.FAULT)
def disk_failing(ctx: Context) -> list[Finding]:
    """Disk health status, wear, temperature, the check's own verdict and disk log errors."""
    lines: list[str] = []
    critical = False
    health = ctx.health_check("storage.health")
    disks = [d for d in ctx.check("storage.health").get("disks") or [] if isinstance(d, dict)]
    if not disks:
        # No health data: fall back to the status the inventory recorded.
        disks = [
            {"model": d.model, "health_status": d.health_status} for d in ctx.report.inventory.disks
        ]
    for disk in disks:
        problems, disk_critical = _disk_problems(disk)
        if problems:
            lines.append(f"{disk.get('model') or 'Disco'}: {', '.join(problems)}.")
            critical = critical or disk_critical
    if health and health.status in (Status.WARNING, Status.CRITICAL):
        # The check also weighs counters not in its data (uncorrected errors).
        critical = critical or health.status is Status.CRITICAL
        if not lines and health.summary:
            lines.append(health.summary)
    disk_errors = ctx.value("system.events", "disk_errors")
    if disk_errors:
        days = ctx.value("system.events", "window_days")
        period = f" nos últimos {fmt(days)} dias" if days else ""
        lines.append(f"Log de eventos: {fmt(disk_errors)} erros de disco{period}.")
        critical = critical or disk_errors >= ref.DISK_ERRORS_CRITICAL
    if not lines:
        return []
    return make_finding(
        "storage.disk_failing",
        Category.STORAGE,
        Severity.CRITICAL if critical else Severity.WARNING,
        "Sinais de falha no disco",
        " ".join(lines) + " Um disco com defeito trava o sistema por segundos ao repetir leituras.",
        "Faça backup dos dados imediatamente e substitua o disco. Não instale upgrades "
        "nem formate sobre um disco com erros.",
        disks=[{k: d[k] for k in _DISK_EVIDENCE_KEYS if d.get(k) is not None} for d in disks],
        health_check_status=health.status.value if health else None,
        disk_errors=disk_errors,
    )


@rule(Role.UPGRADE)
def system_disk_hdd(ctx: Context) -> list[Finding]:
    disk = ctx.system_disk
    if disk_kind(disk) != "hdd":
        return []
    iops = ctx.metric("storage.random", "read_iops")
    measured = f" No teste, fez {fmt(iops)} leituras aleatórias por segundo." if iops else ""
    return make_finding(
        "storage.system_hdd",
        Category.STORAGE,
        Severity.CRITICAL,
        "Windows instalado em HD mecânico",
        f"O disco do sistema ({disk.model or 'HD'}) é um HD. O Windows 10/11 faz milhares de "
        "leituras pequenas ao iniciar e abrir programas, e um HD entrega cerca de 100 por "
        "segundo, contra milhares de um SSD." + measured,
        "Trocar o HD por um SSD (SATA ou NVMe, conforme a placa) e clonar o sistema. É o "
        "upgrade com maior ganho para este sintoma.",
        disk_model=disk.model,
        media_type=disk.media_type,
        random_read_iops=iops,
    )


@rule(Role.UPGRADE)
def disk_behaves_like_hdd(ctx: Context) -> list[Finding]:
    """Unknown media type, but random reads at HDD level."""
    iops = ctx.metric("storage.random", "read_iops")
    if (
        disk_kind(ctx.system_disk) is not None
        or iops is None
        or iops >= ref.HDD_LIKE_RANDOM_READ_IOPS
        or ctx.metric("storage.random", "uncached") == 0
    ):
        return []
    return make_finding(
        "storage.behaves_like_hdd",
        Category.STORAGE,
        Severity.WARNING,
        "Disco do sistema com desempenho de HD",
        f"O tipo do disco não foi identificado, mas ele fez apenas {fmt(iops)} leituras "
        "aleatórias por segundo, valor típico de HD mecânico.",
        "Confirmar o modelo do disco; se for HD, trocar por SSD.",
        random_read_iops=iops,
        threshold_iops=ref.HDD_LIKE_RANDOM_READ_IOPS,
    )


@rule(Role.OTHER)
def disk_slower_than_expected(ctx: Context) -> list[Finding]:
    """Benchmark results below what a healthy drive of the same type delivers."""
    kind = disk_kind(ctx.system_disk)
    if kind is None or ctx.metric("storage.sequential", "uncached") == 0:
        return []
    expected = ref.DISK_EXPECTATIONS[kind]
    seq_read = ctx.metric("storage.sequential", "read_mb_s")
    seq_write = ctx.metric("storage.sequential", "write_mb_s")
    random_read = ctx.metric("storage.random", "read_iops")
    slow: list[str] = []
    if seq_read is not None and seq_read < expected.min_seq_read_mb_s:
        slow.append(
            f"leitura sequencial de {fmt(seq_read)} MB/s "
            f"(típico: {fmt(expected.typical_seq_read_mb_s)} MB/s)"
        )
    if seq_write is not None and seq_write < expected.min_seq_write_mb_s:
        slow.append(f"gravação sequencial de {fmt(seq_write)} MB/s")
    if random_read is not None and random_read < expected.min_random_read_iops:
        slow.append(
            f"{fmt(random_read)} leituras aleatórias/s "
            f"(típico: {fmt(expected.typical_random_read_iops)})"
        )
    if not slow:
        return []
    causes = (
        "HD com setores fracos, fragmentação ou outro programa usando o disco"
        if kind == "hdd"
        else "SSD quase cheio ou sem cache (DRAM-less/QLC), superaquecimento, modo SATA em "
        "IDE em vez de AHCI, porta SATA II ou firmware desatualizado"
    )
    return make_finding(
        "storage.slower_than_expected",
        Category.STORAGE,
        Severity.WARNING,
        f"Disco abaixo do esperado para um {expected.label}",
        f"Resultados: {'; '.join(slow)}. Causas comuns: {causes}.",
        "Verificar a saúde do disco e o espaço livre, o modo AHCI na BIOS e atualizações de "
        "firmware. Se persistir, substituir por um SSD de linha melhor.",
        disk_type=expected.label,
        seq_read_mb_s=seq_read,
        seq_write_mb_s=seq_write,
        random_read_iops=random_read,
        min_seq_read_mb_s=expected.min_seq_read_mb_s,
        min_random_read_iops=expected.min_random_read_iops,
    )


@rule(Role.SOFTWARE)
def disk_busy(ctx: Context) -> list[Finding]:
    busy = ctx.value("storage.activity", "busy_percent")
    response = ctx.value("storage.activity", "avg_response_ms")
    is_busy = busy is not None and busy >= ref.DISK_BUSY_WARNING_PERCENT
    is_slow = response is not None and response >= ref.DISK_RESPONSE_WARNING_MS
    if not (is_busy or is_slow):
        return []
    critical = (response or 0) >= ref.DISK_RESPONSE_CRITICAL_MS
    measured = join_known(
        (busy, f"ocupado {fmt(busy or 0)}% do tempo"),
        (response, f"com tempo médio de resposta de {fmt(response or 0)} ms"),
    )
    return make_finding(
        "storage.busy",
        Category.STORAGE,
        Severity.CRITICAL if critical else Severity.WARNING,
        "Disco sobrecarregado",
        f"Durante a coleta o disco ficou {measured}. Com o disco no limite, tudo "
        "que depende dele (abrir programas, o menu Iniciar) espera na fila.",
        "Identificar no Gerenciador de Tarefas (aba Desempenho/Processos, coluna Disco) o "
        "que está usando o disco: atualizações, antivírus, indexação ou sincronização. Em HD, "
        "a solução definitiva é o SSD.",
        busy_percent=busy,
        avg_response_ms=response,
        avg_queue_length=ctx.value("storage.activity", "avg_queue_length"),
    )


@rule(Role.SOFTWARE)
def low_free_space(ctx: Context) -> list[Finding]:
    data = ctx.check("storage.free_space")
    free_gb, free_pct = number(data.get("free_gb")), number(data.get("free_percent"))
    letter = data.get("letter") or "C:"
    if free_gb is None and free_pct is None:
        volume = next((v for v in ctx.report.inventory.volumes if v.letter == "C:"), None)
        if volume is None or not volume.size_gb:
            return []
        free_gb, free_pct = volume.free_gb, volume.free_percent
    critical = (free_pct is not None and free_pct < ref.FREE_SPACE_CRITICAL_PERCENT) or (
        free_gb is not None and free_gb < ref.FREE_SPACE_CRITICAL_GB
    )
    warning = (free_pct is not None and free_pct < ref.FREE_SPACE_WARNING_PERCENT) or (
        free_gb is not None and free_gb < ref.FREE_SPACE_WARNING_GB
    )
    if not warning:
        return []
    shown = join_known(
        (free_gb, f"{fmt(free_gb or 0, 1)} GB"), (free_pct, f"{fmt(free_pct or 0, 1)}%")
    )
    return make_finding(
        "storage.low_free_space",
        Category.STORAGE,
        Severity.CRITICAL if critical else Severity.WARNING,
        f"Pouco espaço livre em {letter}",
        f"Restam {shown} livres. Sem espaço, o Windows não consegue ampliar o arquivo de "
        "paginação nem instalar atualizações, e SSDs cheios ficam mais lentos.",
        "Liberar espaço: Limpeza de Disco (arquivos do sistema), esvaziar Downloads e "
        "Lixeira, mover arquivos grandes para outro disco. Manter ao menos 15% livre.",
        free_gb=free_gb,
        free_percent=free_pct,
    )
