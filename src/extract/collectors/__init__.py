"""Hardware inventory: what the machine has (CPU, memory, disks, network, ...)."""

from __future__ import annotations

from extract.core.models import Inventory
from extract.core.powershell import PowerShellRunner
from extract.core.progress import CancelToken, ProgressCallback, no_progress


def collect_inventory(
    ps: PowerShellRunner,
    progress: ProgressCallback = no_progress,
    cancel: CancelToken | None = None,
) -> Inventory:
    """Read the full hardware inventory. A section that fails is left with empty values."""
    raise NotImplementedError
