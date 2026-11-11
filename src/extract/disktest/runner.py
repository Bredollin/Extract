"""Run a disk test: read the drive's health, optionally measure its speed, then judge it."""

from __future__ import annotations

import logging
import os
import tempfile

from extract import __version__
from extract.benchmarks import disk as disk_bench
from extract.core.models import Metric
from extract.core.powershell import PowerShellRunner
from extract.core.progress import CancelToken, ProgressCallback, no_progress, sub_progress

from . import evaluate, probe
from .isolated import run_disk_isolated
from .models import DiskTestMode, DiskTestReport, DriveEntry
from .sat import read_sat_smart
from .smart import parse_attributes, parse_thresholds

log = logging.getLogger(__name__)

_SIZES = {DiskTestMode.QUICK: disk_bench.QUICK, DiskTestMode.FULL: disk_bench.FULL}


def bench_folder(letter: str) -> str:
    """Where the temporary test file goes on `letter`.

    The system volume uses the user's temp folder (its root needs admin rights); other
    volumes use their root, which normal users can write on data disks and USB drives.
    """
    letter = letter.rstrip(":\\/").upper()
    system = os.environ.get("SYSTEMDRIVE", "C:").rstrip(":\\/").upper()
    if letter == system or not letter:
        return tempfile.gettempdir()
    return f"{letter}:\\"


def run_disk_test(
    ps: PowerShellRunner,
    drive: DriveEntry,
    mode: str = DiskTestMode.QUICK,
    volume: str = "",
    drive_count: int = 1,
    progress: ProgressCallback = no_progress,
    cancel: CancelToken | None = None,
    benchmark=run_disk_isolated,
    sat_reader=read_sat_smart,
) -> DiskTestReport:
    """Test one physical drive. `volume` ("D:") picks where the speed test writes."""
    cancel = cancel or CancelToken()
    benchmarking = mode in _SIZES
    health_end = 0.25 if benchmarking else 1.0

    progress(0.0, "Disco: lendo identificação e permissões")
    is_admin, hostname = probe.session_info(ps)
    cancel.raise_if_cancelled()
    progress(health_end * 0.3, "Disco: lendo contadores de confiabilidade")
    counters = probe.reliability(ps, drive.number)
    cancel.raise_if_cancelled()
    progress(health_end * 0.6, "Disco: lendo atributos SMART")
    smart, predicted = probe.raw_smart(ps, drive, drive_count)
    if not smart and is_admin and drive.bus_type.upper() == "USB" and drive.kind != "nvme":
        progress(health_end * 0.7, "Disco: lendo SMART pelo adaptador USB")
        raw = sat_reader(drive.number)
        if raw is not None:
            smart = parse_attributes(raw[0], parse_thresholds(raw[1]))
            log.info("SAT SMART: %d attributes from disk %s", len(smart), drive.number)
    cancel.raise_if_cancelled()
    trim = probe.trim_enabled(ps) if drive.kind in ("nvme", "sata_ssd") else None
    progress(health_end, "Disco: saúde lida")

    report = DiskTestReport(
        drive=drive,
        mode=mode,
        smart=smart,
        is_admin=is_admin,
        hostname=hostname,
        tool_version=__version__,
    )
    report.readings = evaluate.health_readings(drive, counters, smart, predicted, trim, is_admin)

    if benchmarking:
        letter = volume or next((v.letter for v in drive.volumes if v.letter), "")
        if not letter:
            report.performance_error = "O disco não tem unidade com letra para gravar o teste."
        else:
            report.tested_volume = letter
            usb = drive.bus_type.upper() == "USB"
            log.info("Disk test: speed test on %s (%s, usb=%s)", letter, mode, usb)
            progress(health_end, f"Disco: criando o arquivo de teste em {letter}")
            results = benchmark(
                sub_progress(progress, health_end, 1.0),
                cancel,
                _SIZES[mode],
                bench_folder(letter),
                write_through=not usb,
            )
            errors = [r.error for r in results if r.error]
            metrics: dict[str, Metric] = {}
            for result in results:
                metrics.update({k: m for k, m in result.metrics.items() if k != "uncached"})
            report.performance = metrics
            report.performance_error = errors[0] if errors else ""

    progress(1.0, "Disco: teste concluído")
    return evaluate.finish(report)
