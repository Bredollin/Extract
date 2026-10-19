"""Windows health: current machine state (free space, memory pressure, errors, network)."""

from __future__ import annotations

from extract.core.models import HealthCheck, Inventory
from extract.core.powershell import PowerShellRunner
from extract.core.progress import CancelToken, ProgressCallback, no_progress


def run_health_checks(
    ps: PowerShellRunner,
    inventory: Inventory,
    progress: ProgressCallback = no_progress,
    cancel: CancelToken | None = None,
) -> list[HealthCheck]:
    """Run every health check. A check that fails is reported with status UNKNOWN."""
    raise NotImplementedError
