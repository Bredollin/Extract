"""Windows health: current machine state (free space, memory pressure, errors, network).

Each check reports state only (`Status` plus raw numbers in `data`); deciding what the
numbers mean for the user is the job of `extract.analysis`.
"""

from __future__ import annotations

import logging

from extract.core.models import HealthCheck, Inventory
from extract.core.powershell import PowerShellRunner
from extract.core.progress import CancelToken, ProgressCallback, no_progress

from .base import Check
from .cpu import check_cpu_load
from .memory import check_memory_pressure
from .network import check_connectivity, check_wifi
from .storage import check_disk_activity, check_disk_health, check_free_space
from .system import (
    check_antivirus,
    check_devices,
    check_events,
    check_pending_reboot,
    check_power_plan,
    check_startup,
    check_uptime,
)

log = logging.getLogger(__name__)

# Run one after another: the sampled checks measure load, so running them in parallel
# would make them measure each other.
CHECKS: tuple[Check, ...] = (
    check_disk_health,
    check_free_space,
    check_disk_activity,
    check_memory_pressure,
    check_cpu_load,
    check_startup,
    check_uptime,
    check_events,
    check_power_plan,
    check_antivirus,
    check_devices,
    check_pending_reboot,
    check_connectivity,
    check_wifi,
)


def run_health_checks(
    ps: PowerShellRunner,
    inventory: Inventory,
    progress: ProgressCallback = no_progress,
    cancel: CancelToken | None = None,
) -> list[HealthCheck]:
    """Run every health check. A check that fails is reported with status UNKNOWN.

    Raises `Cancelled` between checks when `cancel` is set.
    """
    cancel = cancel or CancelToken()
    results: list[HealthCheck] = []
    for index, check in enumerate(CHECKS):
        cancel.raise_if_cancelled()
        progress(index / len(CHECKS), f"Verificando: {check.title}")
        log.info("Health check %s", check.id)
        result = check(ps, inventory)
        if result is not None:
            results.append(result)
    progress(1.0, "Verificações de saúde concluídas")
    return results
