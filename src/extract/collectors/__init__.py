"""Hardware inventory: what the machine has (CPU, memory, disks, network, ...)."""

from __future__ import annotations

import logging
from collections.abc import Callable

from extract.collectors.cpu import collect_cpu
from extract.collectors.gpu import collect_gpus
from extract.collectors.memory import collect_memory
from extract.collectors.motherboard import collect_motherboard
from extract.collectors.network import collect_network
from extract.collectors.storage import collect_storage
from extract.collectors.system import collect_system
from extract.core.models import Inventory
from extract.core.powershell import PowerShellRunner
from extract.core.progress import CancelToken, ProgressCallback, no_progress

log = logging.getLogger(__name__)

__all__ = [
    "collect_cpu",
    "collect_gpus",
    "collect_inventory",
    "collect_memory",
    "collect_motherboard",
    "collect_network",
    "collect_storage",
    "collect_system",
]


def _system(ps: PowerShellRunner, inv: Inventory) -> None:
    inv.system = collect_system(ps)


def _cpu(ps: PowerShellRunner, inv: Inventory) -> None:
    inv.cpu = collect_cpu(ps)


def _memory(ps: PowerShellRunner, inv: Inventory) -> None:
    inv.memory = collect_memory(ps)


def _motherboard(ps: PowerShellRunner, inv: Inventory) -> None:
    inv.motherboard = collect_motherboard(ps)


def _gpus(ps: PowerShellRunner, inv: Inventory) -> None:
    inv.gpus = collect_gpus(ps)


def _storage(ps: PowerShellRunner, inv: Inventory) -> None:
    inv.disks, inv.volumes = collect_storage(ps)


def _network(ps: PowerShellRunner, inv: Inventory) -> None:
    inv.network = collect_network(ps)


_SECTIONS: list[tuple[str, Callable[[PowerShellRunner, Inventory], None]]] = [
    ("Lendo informações do sistema", _system),
    ("Identificando o processador", _cpu),
    ("Lendo módulos de memória", _memory),
    ("Identificando a placa-mãe", _motherboard),
    ("Identificando a placa de vídeo", _gpus),
    ("Lendo discos e partições", _storage),
    ("Lendo adaptadores de rede", _network),
]


def collect_inventory(
    ps: PowerShellRunner,
    progress: ProgressCallback = no_progress,
    cancel: CancelToken | None = None,
) -> Inventory:
    """Read the full hardware inventory. A section that fails is left with empty values."""
    cancel = cancel or CancelToken()
    inventory = Inventory()
    for index, (message, collect) in enumerate(_SECTIONS):
        cancel.raise_if_cancelled()
        progress(index / len(_SECTIONS), message)
        try:
            collect(ps, inventory)
        except Exception:
            # Collectors already swallow query failures; this guards against unexpected
            # data shapes, so one odd section never costs the whole scan.
            log.exception("Inventory section failed: %s", collect.__name__)
    progress(1.0, "Inventário concluído")
    return inventory
