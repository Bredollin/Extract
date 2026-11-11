"""Data of one disk test: the drive, its health readings, performance and the verdict.

Like `MachineReport`, everything is a plain dataclass that round-trips through JSON, so a
saved test can be reopened, exported or compared later.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, ClassVar

from extract.core.models import Metric, Status, from_dict, to_dict

from .smart import SmartAttribute


class DiskTestMode:
    """How deep the test goes. Stored as plain strings in the JSON."""

    HEALTH = "health"  # health only: nothing is written to the disk
    QUICK = "quick"  # + 128 MB performance test (about 30 s)
    FULL = "full"  # + 1 GB performance test (about 1 min 15 s)

    LABELS: ClassVar[dict[str, str]] = {
        HEALTH: "Só saúde (não grava nada)",
        QUICK: "Saúde + desempenho rápido",
        FULL: "Saúde + desempenho completo",
    }


@dataclass
class VolumeEntry:
    letter: str = ""  # "C:"
    label: str = ""
    filesystem: str = ""
    size_gb: float = 0.0
    free_gb: float = 0.0
    partition_offset: int | None = None  # bytes from the start of the disk

    @property
    def aligned(self) -> bool | None:
        """4 KiB alignment of the partition: misaligned partitions slow SSDs and AF HDDs."""
        if self.partition_offset is None:
            return None
        return self.partition_offset % 4096 == 0


@dataclass
class DriveEntry:
    number: int = -1  # Windows disk number (Gerenciamento de Disco)
    model: str = ""
    serial_number: str = ""
    firmware: str = ""
    bus_type: str = ""  # "NVMe", "SATA", "USB", "RAID", ...
    media_type: str = ""  # "SSD", "HDD" or "Unspecified"
    spindle_rpm: int | None = None
    size_gb: float = 0.0
    partition_style: str = ""  # "GPT" or "MBR"
    health_status: str = ""  # Windows: "Healthy", "Warning", "Unhealthy"
    operational_status: str = ""
    is_system: bool = False
    volumes: list[VolumeEntry] = field(default_factory=list)

    @property
    def kind(self) -> str:
        """Expectation key for performance: "nvme", "sata_ssd", "hdd" or "" (unknown)."""
        bus = self.bus_type.upper()
        media = self.media_type.upper()
        if bus == "NVME":
            return "nvme"
        if media == "SSD" or self.spindle_rpm == 0:
            return "sata_ssd"
        if media == "HDD" or (self.spindle_rpm or 0) > 0:
            return "hdd"
        return ""

    @property
    def kind_label(self) -> str:
        labels = {"nvme": "SSD NVMe", "sata_ssd": "SSD", "hdd": "HD"}
        text = labels.get(self.kind, "Disco")
        if self.bus_type and self.bus_type.upper() not in ("NVME",):
            text += f" {self.bus_type}"
        return text

    @property
    def title(self) -> str:
        letters = ", ".join(v.letter for v in self.volumes if v.letter)
        name = self.model or f"Disco {self.number}"
        suffix = f" ({letters})" if letters else ""
        return f"Disco {self.number}: {name}{suffix}"


@dataclass
class Reading:
    """One health line shown to the technician: what was read and how it looks."""

    key: str
    label: str
    value: str
    status: Status = Status.OK
    note: str = ""


@dataclass
class DiskTestReport:
    drive: DriveEntry = field(default_factory=DriveEntry)
    mode: str = DiskTestMode.HEALTH
    tested_volume: str = ""  # letter used for the performance test
    readings: list[Reading] = field(default_factory=list)
    smart: list[SmartAttribute] = field(default_factory=list)
    performance: dict[str, Metric] = field(default_factory=dict)
    performance_error: str = ""
    health_status: Status = Status.UNKNOWN
    performance_status: Status = Status.UNKNOWN
    score: int | None = None  # 0-100, health and performance together
    verdict: str = ""
    recommendations: list[str] = field(default_factory=list)
    is_admin: bool = False
    hostname: str = ""
    created_at: str = field(
        default_factory=lambda: datetime.now(timezone.utc).astimezone().isoformat("T", "seconds")
    )
    tool_version: str = ""

    @property
    def overall_status(self) -> Status:
        from extract.health.base import worst

        statuses = (self.health_status, self.performance_status)
        known = [s for s in statuses if s is not Status.UNKNOWN]
        return worst(*known) if known else Status.UNKNOWN

    def to_dict(self) -> dict[str, Any]:
        return to_dict(self)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> DiskTestReport:
        return from_dict(cls, data)
