"""Reference values and thresholds used by the analysis rules.

These are rule-of-thumb numbers from field experience and typical published specifications,
not measurements of specific products. `docs/diagnostics.md` explains where each one comes
from and which are assumptions. Keeping them in one place makes the rules easy to audit and
tune.
"""

from __future__ import annotations

from dataclasses import dataclass

# --- CPU (scores from benchmarks.cpu: ~1000 per core on a current ~3 GHz x86-64 core) -----

CPU_SINGLE_VERY_WEAK = 350  # assumed: low-power Celeron/Atom/A4-class cores
CPU_SINGLE_WEAK = 550  # assumed: ~2012-2014 desktop cores, recent entry-level laptops
CPU_MULTI_VERY_WEAK = 1000  # about two very weak cores
CPU_MULTI_WEAK = 2000  # about a dual-core with Hyper-Threading of the same era

# Processor names that, without benchmark results, suggest an entry-level or old CPU.
WEAK_CPU_NAME_PATTERNS = (
    r"\bAtom\b",
    r"\bCeleron\b",
    r"\bPentium\b(?!.*\bGold\b)",
    r"\bAthlon\b",
    r"\b(?:A4|A6|E1|E2)-\d{4}",
    r"\bCore\(TM\)2\b|\bCore 2\b",
    r"\bi[3579]-[2-4]\d{3}",  # Intel Core 2nd to 4th generation (2011-2014)
)

# Sustained load: share of the starting clock / throughput lost by the end of the run.
THROTTLE_WARNING_PERCENT = 15.0
THROTTLE_CRITICAL_PERCENT = 30.0
# Idle-state check from the health data: clock below this share of the maximum under load.
LOW_CLOCK_SHARE = 0.6
LOW_CLOCK_MIN_LOAD_PERCENT = 50.0

CPU_HIGH_LOAD_PERCENT = 85.0
CPU_TOP_PROCESS_PERCENT = 40.0  # a single process above this is named as the culprit

# --- Memory -----------------------------------------------------------------------------

RAM_MIN_GB_MODERN = 8.0  # Windows 10/11 with a browser and office apps
RAM_CRITICAL_GB_MODERN = 4.0
RAM_MIN_GB_LEGACY = 4.0  # Windows 7/8
RAM_RECOMMENDED_GB = 16.0  # target when 8 GB is already under pressure
# Installed memory sizes are reported slightly below the nominal size (reserved for video).
RAM_SIZE_TOLERANCE_GB = 0.5

MEMORY_USED_WARNING_PERCENT = 85.0
MEMORY_USED_CRITICAL_PERCENT = 95.0
MEMORY_COMMIT_WARNING_PERCENT = 90.0
MEMORY_COMMIT_CRITICAL_PERCENT = 98.0
HARD_FAULTS_WARNING_PER_S = 300.0

MEMORY_SPEED_MIN_SHARE = 0.9  # configured speed below this share of the rated speed
# Single-threaded copy bandwidth below this suggests single channel or old memory.
MEMORY_COPY_LOW_GB_S = 5.0

# --- Storage ------------------------------------------------------------------------------


@dataclass(frozen=True)
class DiskExpectation:
    """Minimum sane results for a healthy drive of a type, plus a typical value to quote."""

    label: str
    min_seq_read_mb_s: float
    min_seq_write_mb_s: float
    min_random_read_iops: float
    typical_seq_read_mb_s: float
    typical_random_read_iops: float


DISK_EXPECTATIONS = {
    "nvme": DiskExpectation("SSD NVMe", 800, 400, 5000, 2500, 12000),
    "sata_ssd": DiskExpectation("SSD SATA", 300, 150, 3000, 500, 6000),
    "hdd": DiskExpectation("HD", 60, 40, 50, 130, 90),
}
# With unknown media type, random reads below this mean the disk behaves like an HDD.
HDD_LIKE_RANDOM_READ_IOPS = 400

DISK_BUSY_WARNING_PERCENT = 90.0
DISK_RESPONSE_WARNING_MS = 50.0
DISK_RESPONSE_CRITICAL_MS = 150.0

FREE_SPACE_WARNING_PERCENT = 10.0
FREE_SPACE_WARNING_GB = 15.0
FREE_SPACE_CRITICAL_PERCENT = 5.0
FREE_SPACE_CRITICAL_GB = 5.0

DISK_WEAR_WARNING_PERCENT = 80.0
DISK_WEAR_CRITICAL_PERCENT = 95.0
DISK_TEMP_WARNING_C = {"hdd": 55.0, "ssd": 70.0}
DISK_ERRORS_CRITICAL = 10  # disk errors (bad blocks, controller errors) in the event log

# --- System -------------------------------------------------------------------------------

STARTUP_INFO_COUNT = 10
STARTUP_WARNING_COUNT = 20
UPTIME_INFO_DAYS = 7
UPTIME_WARNING_DAYS = 30
UNEXPECTED_SHUTDOWNS_WARNING = 2
APP_CRASHES_INFO = 10

# --- Network ------------------------------------------------------------------------------

GATEWAY_LATENCY_WARNING_MS = 20.0
INTERNET_LATENCY_WARNING_MS = 150.0
LOSS_WARNING_PERCENT = 5.0
LOSS_CRITICAL_PERCENT = 30.0
DNS_WARNING_MS = 200.0
WIFI_SIGNAL_WARNING_PERCENT = 40.0
WIFI_LINK_WARNING_MBPS = 20.0
