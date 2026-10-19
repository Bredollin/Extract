"""Data models shared across Extract.

Everything a scan produces fits in a `MachineReport`. Models are plain dataclasses that
round-trip through JSON (`to_dict` / `MachineReport.from_dict`), so collection, analysis,
reports and the GUI never depend on each other directly.

Enum values are stable English identifiers stored in the JSON files; the Portuguese text
shown to users comes from each enum's `label`.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field, fields, is_dataclass
from datetime import datetime, timezone
from enum import Enum
from typing import Any, TypeVar

SCHEMA_VERSION = 1

T = TypeVar("T")


class Category(str, Enum):
    """Machine area a piece of data, benchmark or finding belongs to."""

    SYSTEM = "system"
    CPU = "cpu"
    MEMORY = "memory"
    STORAGE = "storage"
    GPU = "gpu"
    NETWORK = "network"

    @property
    def label(self) -> str:
        return _CATEGORY_LABELS[self]


class Status(str, Enum):
    """Outcome of a health check."""

    OK = "ok"
    WARNING = "warning"
    CRITICAL = "critical"
    UNKNOWN = "unknown"

    @property
    def label(self) -> str:
        return _STATUS_LABELS[self]


class Severity(str, Enum):
    """How serious a finding is, from least to most severe."""

    INFO = "info"
    WARNING = "warning"
    CRITICAL = "critical"

    @property
    def rank(self) -> int:
        return list(Severity).index(self)

    @property
    def label(self) -> str:
        return _SEVERITY_LABELS[self]


_CATEGORY_LABELS = {
    Category.SYSTEM: "Sistema",
    Category.CPU: "Processador",
    Category.MEMORY: "Memória",
    Category.STORAGE: "Armazenamento",
    Category.GPU: "Vídeo",
    Category.NETWORK: "Rede",
}
_STATUS_LABELS = {
    Status.OK: "OK",
    Status.WARNING: "Atenção",
    Status.CRITICAL: "Crítico",
    Status.UNKNOWN: "Indisponível",
}
_SEVERITY_LABELS = {
    Severity.INFO: "Informativo",
    Severity.WARNING: "Atenção",
    Severity.CRITICAL: "Crítico",
}


# --- Hardware inventory ----------------------------------------------------------


@dataclass
class SystemInfo:
    hostname: str = ""
    user: str = ""
    os_name: str = ""
    os_version: str = ""
    os_build: str = ""
    architecture: str = ""
    manufacturer: str = ""
    model: str = ""
    serial_number: str = ""
    bios_version: str = ""
    boot_mode: str = ""  # "UEFI" or "Legacy"
    install_date: str = ""  # ISO 8601
    last_boot: str = ""  # ISO 8601


@dataclass
class CpuInfo:
    name: str = ""
    manufacturer: str = ""
    cores: int = 0
    logical_processors: int = 0
    base_clock_mhz: int = 0
    socket: str = ""
    l2_cache_kb: int = 0
    l3_cache_kb: int = 0


@dataclass
class MemoryModule:
    slot: str = ""
    capacity_gb: float = 0.0
    speed_mhz: int = 0
    configured_speed_mhz: int = 0
    manufacturer: str = ""
    part_number: str = ""
    memory_type: str = ""  # "DDR4", "DDR5", ...


@dataclass
class MemoryInfo:
    total_gb: float = 0.0
    total_slots: int = 0
    memory_type: str = ""
    modules: list[MemoryModule] = field(default_factory=list)

    @property
    def used_slots(self) -> int:
        return len(self.modules)


@dataclass
class MotherboardInfo:
    manufacturer: str = ""
    product: str = ""
    serial_number: str = ""


@dataclass
class GpuInfo:
    name: str = ""
    vram_mb: int = 0
    driver_version: str = ""
    driver_date: str = ""


@dataclass
class DiskInfo:
    model: str = ""
    size_gb: float = 0.0
    media_type: str = ""  # "SSD", "HDD" or "Unknown"
    bus_type: str = ""  # "NVMe", "SATA", "USB", ...
    serial_number: str = ""
    health_status: str = ""  # as reported by Windows: "Healthy", "Warning", "Unhealthy"
    is_system_disk: bool = False


@dataclass
class VolumeInfo:
    letter: str = ""  # "C:"
    label: str = ""
    filesystem: str = ""
    size_gb: float = 0.0
    free_gb: float = 0.0

    @property
    def free_percent(self) -> float:
        return round(self.free_gb / self.size_gb * 100, 1) if self.size_gb else 0.0


@dataclass
class NetworkAdapter:
    name: str = ""
    mac_address: str = ""
    ipv4: list[str] = field(default_factory=list)
    gateway: list[str] = field(default_factory=list)
    dns_servers: list[str] = field(default_factory=list)
    dhcp: bool = False
    link_speed_mbps: int = 0


@dataclass
class Inventory:
    system: SystemInfo = field(default_factory=SystemInfo)
    cpu: CpuInfo = field(default_factory=CpuInfo)
    memory: MemoryInfo = field(default_factory=MemoryInfo)
    motherboard: MotherboardInfo = field(default_factory=MotherboardInfo)
    gpus: list[GpuInfo] = field(default_factory=list)
    disks: list[DiskInfo] = field(default_factory=list)
    volumes: list[VolumeInfo] = field(default_factory=list)
    network: list[NetworkAdapter] = field(default_factory=list)


# --- System health --------------------------------------------------------------------


@dataclass
class HealthCheck:
    """Result of one Windows health check (disk, memory, event log, ...).

    `data` holds the raw numbers the analysis uses; `title` and `summary` are the short
    Portuguese texts shown to the user.
    """

    id: str
    category: Category
    title: str
    status: Status
    summary: str
    data: dict[str, Any] = field(default_factory=dict)


# --- Benchmarks -------------------------------------------------------------------


@dataclass
class Metric:
    value: float
    unit: str
    label: str


@dataclass
class BenchmarkResult:
    id: str
    category: Category
    title: str
    metrics: dict[str, Metric] = field(default_factory=dict)
    duration_s: float = 0.0
    error: str = ""

    @property
    def ok(self) -> bool:
        return not self.error


# --- Analysis ----------------------------------------------------------------------


@dataclass
class Finding:
    """A likely cause of slowness or failure, with a recommendation for the technician.

    `title`, `detail` and `recommendation` are user-facing Portuguese text.
    """

    id: str
    category: Category
    severity: Severity
    title: str
    detail: str
    recommendation: str
    evidence: dict[str, Any] = field(default_factory=dict)


# --- Full report ------------------------------------------------------------------


def _now_iso() -> str:
    return datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds")


@dataclass
class MachineReport:
    inventory: Inventory = field(default_factory=Inventory)
    health: list[HealthCheck] = field(default_factory=list)
    benchmarks: list[BenchmarkResult] = field(default_factory=list)
    findings: list[Finding] = field(default_factory=list)
    client: str = ""
    notes: str = ""
    created_at: str = field(default_factory=_now_iso)
    tool_version: str = ""
    schema_version: int = SCHEMA_VERSION

    @property
    def hostname(self) -> str:
        return self.inventory.system.hostname or "unknown-machine"

    def to_dict(self) -> dict[str, Any]:
        return to_dict(self)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> MachineReport:
        return from_dict(cls, data)


# --- Serialization ----------------------------------------------------------------


def to_dict(obj: Any) -> Any:
    """Convert dataclasses and enums into plain JSON types."""
    if is_dataclass(obj) and not isinstance(obj, type):
        return {k: to_dict(v) for k, v in asdict(obj).items()}
    if isinstance(obj, Enum):
        return obj.value
    if isinstance(obj, dict):
        return {k: to_dict(v) for k, v in obj.items()}
    if isinstance(obj, list):
        return [to_dict(v) for v in obj]
    return obj


def from_dict(cls: type[T], data: Any) -> T:
    """Rebuild a dataclass from `to_dict` output, ignoring unknown keys."""
    import typing

    hints = typing.get_type_hints(cls)
    kwargs: dict[str, Any] = {}
    for f in fields(cls):  # type: ignore[arg-type]
        if f.name in data:
            kwargs[f.name] = _coerce(hints[f.name], data[f.name])
    return cls(**kwargs)


def _coerce(tp: Any, value: Any) -> Any:
    import typing

    origin = typing.get_origin(tp)
    args = typing.get_args(tp)
    if value is None:
        return None
    if origin is list:
        return [_coerce(args[0], v) for v in value]
    if origin is dict:
        return {k: _coerce(args[1], v) for k, v in value.items()}
    if isinstance(tp, type) and issubclass(tp, Enum):
        return tp(value)
    if is_dataclass(tp):
        return from_dict(tp, value)
    return value
