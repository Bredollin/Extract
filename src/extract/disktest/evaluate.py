"""Turn raw disk readings into health lines, a performance status, a 0-100 score, a verdict
and recommendations. Pure functions: no PowerShell, no disk access, easy to test.
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import Any

from extract.analysis import reference as ref
from extract.core.models import Metric, Status
from extract.health.base import fmt, level, to_int, worst

from .models import DiskTestReport, DriveEntry, Reading
from .smart import (
    CRC_ATTRIBUTE,
    POWER_CYCLES,
    POWER_ON_HOURS,
    SSD_LIFE_ATTRIBUTES,
    TEMPERATURE_ATTRIBUTES,
    SmartAttribute,
    find,
)

_WINDOWS_HEALTH = {
    "Healthy": (Status.OK, "Saudável"),
    "Warning": (Status.WARNING, "Em alerta"),
    "Unhealthy": (Status.CRITICAL, "Com falha"),
}


def _bad_sector_count(smart: Sequence[SmartAttribute]) -> int | None:
    present = [a for a in smart if a.id in (5, 197, 198)]
    return sum(a.raw for a in present) if present else None


def _wear(counters: dict[str, Any], smart: Sequence[SmartAttribute], drive: DriveEntry):
    """Percent of rated life used, from Windows' counter or the SSD's own life attribute."""
    wear = to_int(counters.get("Wear"))
    if wear is not None and (wear > 0 or drive.kind in ("nvme", "sata_ssd")):
        return wear
    if drive.kind != "hdd":
        life = find(smart, *SSD_LIFE_ATTRIBUTES)
        if life is not None and 0 < life.current <= 100:
            return 100 - life.current
    return None


def health_readings(
    drive: DriveEntry,
    counters: dict[str, Any],
    smart: Sequence[SmartAttribute],
    predicted_failure: bool | None,
    trim: bool | None,
    is_admin: bool,
) -> list[Reading]:
    readings: list[Reading] = []

    def add(key: str, label: str, value: str, status: Status = Status.OK, note: str = ""):
        readings.append(Reading(key, label, value, status, note))

    status, text = _WINDOWS_HEALTH.get(drive.health_status, (Status.UNKNOWN, "Desconhecido"))
    add("windows", "Avaliação do Windows", text, status)

    if predicted_failure is not None:
        add(
            "smart_predict",
            "Previsão de falha (SMART)",
            "Falha prevista" if predicted_failure else "Nenhuma",
            Status.CRITICAL if predicted_failure else Status.OK,
            "o próprio disco avisa que vai falhar" if predicted_failure else "",
        )

    temperature = to_int(counters.get("Temperature")) or None
    smart_temp = find(smart, *TEMPERATURE_ATTRIBUTES)
    if temperature is None and smart_temp is not None:
        temperature = (smart_temp.raw & 0xFF) or None
    if temperature is not None:
        warn, crit = ref.DISKTEST_TEMPERATURE_C[drive.kind]
        status = level(temperature, warn, crit)
        note = f"limite recomendado {warn} °C" if status is not Status.OK else ""
        add("temperature", "Temperatura atual", f"{temperature} °C", status, note)
    max_temp = to_int(counters.get("TemperatureMax")) or None
    if max_temp:
        add("temperature_max", "Temperatura máxima registrada", f"{max_temp} °C")

    wear = _wear(counters, smart, drive)
    if wear is not None:
        status = level(wear, *ref.DISKTEST_WEAR_PERCENT)
        add(
            "wear",
            "Vida útil usada",
            f"{wear}% (restam {max(0, 100 - wear)}%)",
            status,
            "planeje a troca" if status is not Status.OK else "",
        )

    hours = to_int(counters.get("PowerOnHours"))
    hours_attr = find(smart, POWER_ON_HOURS)
    if hours is None and hours_attr is not None:
        hours = hours_attr.raw & 0xFFFFFFFF
    if hours is not None:
        status = Status.OK
        note = f"cerca de {fmt(hours / 24 / 365, 1)} anos ligado"
        if drive.kind == "hdd" and hours >= ref.DISKTEST_HDD_POWER_ON_HOURS_WARNING:
            status, note = Status.WARNING, note + "; HD já passou da vida típica"
        add("power_on_hours", "Horas ligado", f"{fmt(hours)} h", status, note)

    cycles = to_int(counters.get("StartStopCycleCount"))
    cycles_attr = find(smart, POWER_CYCLES)
    if cycles is None and cycles_attr is not None:
        cycles = cycles_attr.raw
    if cycles is not None:
        add("power_cycles", "Ciclos de liga/desliga", fmt(cycles))

    uncorrected = [
        to_int(counters.get(k)) for k in ("ReadErrorsUncorrected", "WriteErrorsUncorrected")
    ]
    known = [v for v in uncorrected if v is not None]
    if known:
        total = sum(known)
        status = level(total, *ref.DISKTEST_UNCORRECTED_ERRORS)
        add("uncorrected", "Erros de leitura/gravação não corrigidos", fmt(total), status)

    bad = _bad_sector_count(smart)
    if bad is not None:
        status = worst(*(a.status for a in smart if a.id in (5, 197, 198)))
        note = "dados em risco: faça backup" if status is not Status.OK else ""
        add("bad_sectors", "Setores defeituosos (realocados + pendentes)", fmt(bad), status, note)

    crc = find(smart, CRC_ATTRIBUTE)
    if crc is not None:
        add("crc", "Erros de comunicação (CRC)", fmt(crc.raw), crc.status, crc.note)

    worst_latency = [
        (label, to_int(counters.get(key)))
        for key, label in (
            ("ReadLatencyMax", "leitura"),
            ("WriteLatencyMax", "gravação"),
            ("FlushLatencyMax", "flush"),
        )
    ]
    worst_latency = [(label, v) for label, v in worst_latency if v]
    if worst_latency:
        label, value = max(worst_latency, key=lambda item: item[1])
        status = Status.WARNING if value >= ref.DISKTEST_MAX_LATENCY_WARNING_MS else Status.OK
        note = "o disco já travou por mais de 2 s" if status is not Status.OK else ""
        add("max_latency", f"Maior espera registrada ({label})", f"{fmt(value)} ms", status, note)

    if drive.kind in ("nvme", "sata_ssd") and trim is not None:
        add(
            "trim",
            "TRIM",
            "Ativado" if trim else "Desativado",
            Status.OK if trim else Status.WARNING,
            "" if trim else "o SSD perde velocidade com o tempo",
        )

    aligned = [v.aligned for v in drive.volumes if v.aligned is not None]
    if aligned:
        ok = all(aligned)
        add(
            "alignment",
            "Alinhamento das partições (4 KB)",
            "Alinhadas" if ok else "Desalinhada",
            Status.OK if ok else Status.WARNING,
            "" if ok else "partição desalinhada deixa o disco mais lento",
        )

    for volume in drive.volumes:
        if not volume.size_gb:
            continue
        percent = volume.free_gb / volume.size_gb * 100
        warn = ref.DISKTEST_FREE_WARNING_PERCENT
        add(
            f"free_{volume.letter}",
            f"Espaço livre em {volume.letter}",
            f"{fmt(percent)}% ({fmt(volume.free_gb, 1)} de {fmt(volume.size_gb, 1)} GB)",
            # Low space slows the disk but is not a hardware fault: never "critical" here.
            Status.WARNING if percent <= warn else Status.OK,
            "pouco espaço livre" if percent <= warn else "",
        )

    if not is_admin and not counters and not smart:
        add(
            "admin",
            "Contadores SMART",
            "Indisponíveis",
            Status.UNKNOWN,
            "abra o Extract como administrador para ler temperatura, desgaste e setores",
        )
    return readings


def _expectation(drive: DriveEntry):
    return ref.DISK_EXPECTATIONS.get(drive.kind or "sata_ssd")


def performance_status(drive: DriveEntry, metrics: dict[str, Metric]) -> tuple[Status, list[str]]:
    """Compare measured numbers with the minimum expected for the drive's kind."""
    expected = _expectation(drive)
    if not metrics or expected is None:
        return Status.UNKNOWN, []
    checks = (
        ("read_mb_s", expected.min_seq_read_mb_s, "leitura sequencial"),
        ("write_mb_s", expected.min_seq_write_mb_s, "gravação sequencial"),
        ("read_iops", expected.min_random_read_iops, "leitura aleatória"),
    )
    statuses: list[Status] = [Status.OK]
    slow: list[str] = []
    for key, minimum, label in checks:
        metric = metrics.get(key)
        if metric is None or not minimum:
            continue
        if metric.value < minimum:
            share = metric.value / minimum
            critical = share < ref.DISKTEST_PERF_CRITICAL_SHARE and drive.bus_type != "USB"
            statuses.append(Status.CRITICAL if critical else Status.WARNING)
            slow.append(label)
    return worst(*statuses), slow


def _health_score(readings: Sequence[Reading]) -> int:
    score = 100
    for reading in readings:
        if reading.status is Status.CRITICAL:
            score -= 45
        elif reading.status is Status.WARNING:
            score -= 15
    return max(0, score)


def _performance_score(drive: DriveEntry, metrics: dict[str, Metric]) -> int | None:
    expected = _expectation(drive)
    if not metrics or expected is None:
        return None
    pairs = (
        ("read_mb_s", expected.typical_seq_read_mb_s),
        ("write_mb_s", expected.typical_seq_read_mb_s * 0.8),
        ("read_iops", expected.typical_random_read_iops),
    )
    shares = [
        min(1.0, metrics[key].value / typical)
        for key, typical in pairs
        if key in metrics and typical
    ]
    return round(sum(shares) / len(shares) * 100) if shares else None


def finish(report: DiskTestReport) -> DiskTestReport:
    """Fill the statuses, score, verdict and recommendations of a report with its readings."""
    drive = report.drive
    known = [r.status for r in report.readings if r.status is not Status.UNKNOWN]
    report.health_status = worst(*known) if known else Status.UNKNOWN
    report.performance_status, slow = performance_status(drive, report.performance)

    health = _health_score(report.readings)
    performance = _performance_score(drive, report.performance)
    if performance is None:
        report.score = health
    else:
        weight = ref.DISKTEST_HEALTH_WEIGHT
        report.score = round(health * weight + performance * (1 - weight))
    # A drive the system says is failing can never look good on the score.
    if report.health_status is Status.CRITICAL:
        report.score = min(report.score, 40)

    report.verdict = _verdict(report)
    report.recommendations = _recommendations(report, slow)
    return report


def _verdict(report: DiskTestReport) -> str:
    health = report.health_status
    perf = report.performance_status
    if health is Status.CRITICAL:
        return "Disco com sinais de falha: faça backup agora e substitua o disco."
    if health is Status.WARNING and report.score is not None and report.score < 50:
        return "Disco com vários alertas de saúde: faça backup e planeje a troca."
    if health is Status.WARNING and perf in (Status.WARNING, Status.CRITICAL):
        return "Disco com alertas de saúde e desempenho abaixo do esperado."
    if health is Status.WARNING:
        return "Disco funcionando, mas com alertas que precisam de acompanhamento."
    if perf is Status.CRITICAL:
        return "Disco saudável, mas muito mais lento que o esperado para o tipo."
    if perf is Status.WARNING:
        return "Disco saudável, com desempenho um pouco abaixo do esperado."
    if health is Status.UNKNOWN and perf is Status.UNKNOWN:
        return "Não foi possível avaliar o disco (sem dados de saúde nem desempenho)."
    if perf is Status.UNKNOWN:
        return "Disco saudável. Rode o teste de desempenho para medir a velocidade."
    return "Disco saudável e com desempenho dentro do esperado."


def _recommendations(report: DiskTestReport, slow: list[str]) -> list[str]:
    drive = report.drive
    by_key = {r.key: r for r in report.readings}
    tips: list[str] = []

    def bad(key: str) -> bool:
        reading = by_key.get(key)
        return reading is not None and reading.status in (Status.WARNING, Status.CRITICAL)

    if report.health_status is Status.CRITICAL or bad("bad_sectors") or bad("uncorrected"):
        tips.append(
            "Faça backup dos dados imediatamente e planeje a troca do disco; "
            "setores defeituosos tendem a aumentar."
        )
    if bad("crc"):
        tips.append("Troque o cabo SATA ou mude o disco de porta: os erros são de comunicação.")
    if bad("temperature"):
        tips.append("Melhore a ventilação do gabinete; calor encurta a vida do disco.")
    if bad("wear"):
        tips.append("O SSD está perto do fim da vida útil: programe a substituição.")
    if bad("power_on_hours"):
        tips.append("HD com muitas horas de uso: considere trocar por SSD preventivamente.")
    if bad("max_latency"):
        tips.append("O disco já travou por segundos: verifique cabos, energia e o log de eventos.")
    if bad("trim"):
        tips.append(
            "Ative o TRIM (prompt como administrador): fsutil behavior set DisableDeleteNotify 0"
        )
    if bad("alignment"):
        tips.append("Partição desalinhada: realinhe com ferramenta de partição ou reinstale.")
    if any(r.key.startswith("free_") and r.status is not Status.OK for r in report.readings):
        tips.append("Libere espaço: abaixo de 20% livre o Windows e o disco ficam mais lentos.")
    if slow:
        listed = ", ".join(slow)
        if drive.bus_type == "USB":
            tips.append(f"Abaixo do esperado em {listed}: confira se a porta é USB 3.")
        else:
            tips.append(
                f"Abaixo do esperado em {listed}: confira modo AHCI/driver da controladora, "
                "cabo e porta (SATA III), antivírus fazendo varredura e espaço livre."
            )
    if drive.kind == "hdd" and drive.is_system:
        tips.append("Sistema instalado em HD: trocar por SSD é o upgrade que mais acelera o PC.")
    if "admin" in by_key:
        tips.append("Abra o Extract como administrador para ler os contadores SMART completos.")
    if report.mode == "health" and report.health_status is not Status.CRITICAL:
        tips.append("Rode também o teste de desempenho para medir a velocidade real.")
    return tips
