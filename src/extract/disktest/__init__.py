"""Disk test ("Teste de disco"): health (Windows status, reliability counters, raw SMART,
TRIM, alignment, free space), speed (sequential, random 4 KB, latency) and a verdict for
one physical drive at a time.
"""

from .models import DiskTestMode, DiskTestReport, DriveEntry, Reading, VolumeEntry
from .probe import list_drives
from .runner import run_disk_test

__all__ = [
    "DiskTestMode",
    "DiskTestReport",
    "DriveEntry",
    "Reading",
    "VolumeEntry",
    "list_drives",
    "run_disk_test",
]
