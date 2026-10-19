# Diagnostics: benchmarks and analysis

This document describes how Extract measures performance (`src/extract/benchmarks/`) and how
it turns inventory, health checks and benchmark results into findings
(`src/extract/analysis/`). Every threshold lives in `analysis/reference.py`; this page explains
each one and how confident we are in it.

## Benchmarks

`run_benchmarks(categories, ps, progress, cancel, quick)` runs the steps for the requested
categories in this order: CPU single, CPU multi, CPU sustained, memory, disk. A step that
raises is turned into a `BenchmarkResult` with `error` set (message in Portuguese) and the
other steps still run. Cancelling raises `Cancelled` immediately; the disk test deletes its
file on the way out. `duration_s` is the wall time of the step (split evenly when a step
produces two results).

| Mode | CPU single | CPU multi | Sustained | Memory buffer | Disk file | Typical total |
|---|---|---|---|---|---|---|
| full | 5 rounds x 24 units | 60 units per process | 30 s | 256 MB | 1 GiB | ~1.5 to 2 min |
| quick | 3 rounds x 12 units | 16 units per process | 6 s | 64 MB | 128 MiB | ~15 to 25 s |

Sizes are module-level values (`cpu.FULL`/`cpu.QUICK`, `memory.FULL_BUFFER_MB`/
`QUICK_BUFFER_MB`, `disk.FULL`/`disk.QUICK`), which the tests shrink further.

### CPU (`cpu.single`, `cpu.multi`, `cpu.sustained`)

All three run the same deterministic **work unit** (`cpu.work_unit(seed)`): 60 000 rounds of
an FNV-style integer hash, zlib compression of ~100 KB of generated Portuguese text, and
sorting 40 000 random floats from a seeded generator. It mixes integer ALU work, a real-world
C library (zlib) and memory-heavy Python object handling, which is roughly what makes office
software and browsers feel slow. A unit takes about 19 ms on the calibration machine.

The **score** is units per second x `SCORE_PER_UNIT_PER_S`, scaled so that one core of the
calibration machine (a current ~3 GHz x86-64 server core, running CPython 3.13) scores
about **1000 pts**. The scale is arbitrary but linear: 500 pts means half the speed.

| Benchmark | Key | Unit | Meaning |
|---|---|---|---|
| `cpu.single` | `score` | pts | single-core score from the median round |
| | `median_round_s` | s | median time of one round |
| `cpu.multi` | `score` | pts | all logical CPUs together |
| | `workers` | processos | number of worker processes (logical CPUs; max 61 on Windows) |
| | `scaling` | x | multi score / single score (absent if single failed) |
| `cpu.sustained` | `start_score`, `end_score` | pts | multi-core throughput in the first and last fifth of the run |
| | `throughput_drop_percent` | % | loss from start to end |
| | `clock_start_mhz`, `clock_end_mhz` | MHz | effective clock, first and last quarter of the samples |
| | `clock_drop_percent` | % | clock loss from start to end |

How it works:

- **Single**: one warm-up unit, then N rounds; the median round time is used, so one
  interrupted round does not skew the score.
- **Multi**: a `multiprocessing` pool using the **spawn** start method (the only one on
  Windows and in a frozen PyInstaller build; worker functions are top-level, no lambdas are
  pickled). Every process runs one unit before timing starts, so process start-up is not
  measured. Units are fed with at most two per process in flight, which keeps cancellation
  responsive. The entry points must call `multiprocessing.freeze_support()`.
- **Sustained**: the pool runs units continuously for 30 s (quick: 6 s). In parallel, a
  thread samples `Win32_PerfFormattedData_Counters_ProcessorInformation` (`_Total`,
  `PercentProcessorPerformance`) every 2 s and multiplies it by `Win32_Processor.MaxClockSpeed`
  to get the effective clock. If the base clock or the counter cannot be read, the clock
  metrics are omitted and only throughput is reported.

Limitations:

- CPython overhead is part of the workload. This is intentional (it is the kind of work that
  matters for "the machine is slow"), but scores do not map linearly to native benchmarks
  such as Cinebench or Geekbench.
- `scaling` depends on SMT: a 4-core/8-thread CPU typically scales ~5x, not 8x.
- Each PowerShell sample costs some CPU itself (a short-lived `powershell.exe`), slightly
  lowering throughput while it runs. The effect is the same at start and end, so drops stay
  comparable.
- 30 s is enough to catch thin laptops and dusty coolers, which typically throttle within
  10 to 20 s, but not slow heat soak of a desktop over several minutes.

### Memory (`memory.bandwidth`)

Two buffers of 256 MB (quick: 64 MB) are allocated. Each operation is one C-level pass:

- **write**: `ctypes.memset` over the destination;
- **read**: `bytearray.find` for a byte that does not occur (a `memchr` scan);
- **copy**: slice assignment between `memoryview`s (a `memcpy`).

Each runs three times and the best time is kept (best-of filters out preemption). The source
buffer is written once before timing, so it is backed by real pages and not by the shared
zero page.

| Key | Unit | Meaning |
|---|---|---|
| `read_gb_s`, `write_gb_s`, `copy_gb_s` | GB/s | bytes processed per second (copy counts each byte once) |
| `buffer_mb` | MB | buffer size actually used |

The buffer shrinks so the two buffers take at most 25% of the available physical memory
(`GlobalMemoryStatusEx` on Windows, `/proc/meminfo` elsewhere); below 16 MB the benchmark is
skipped with an error.

Limitations:

- Single-threaded: it shows what one application gets, not the platform's peak bandwidth.
  It still clearly separates single from dual channel and DDR3 from DDR4/DDR5.
- CPUs with very large L3 caches (some server and X3D parts) can hold a good part of the 64 MB
  quick buffer in cache and report inflated values; prefer the full mode for comparisons.
- **No latency metric.** A random-access latency test in pure Python would measure the
  interpreter (tens of nanoseconds per operation) rather than DRAM latency (~60 to 100 ns),
  so it would not be meaningful and was left out.

### Disk (`storage.sequential`, `storage.random`)

The test file is created with `tempfile.mkstemp` in the user's temp folder (on the system
volume) and removed in a `finally` block, including on errors and cancellation.

On **Windows** the file is opened with `CreateFileW` and
`FILE_FLAG_NO_BUFFERING | FILE_FLAG_WRITE_THROUGH`, so neither reads nor writes are served by
the Windows file cache. That mode requires sector-aligned buffers, offsets and lengths: the
buffer is an anonymous `mmap` (page-aligned) and all I/O sizes are multiples of 4 KiB, which
covers 512-byte and 4Kn sectors. Positioned I/O uses `ReadFile`/`WriteFile` with an
`OVERLAPPED` offset on a synchronous handle. Buffers are filled with random bytes so SSD
controllers that compress data cannot inflate the numbers.

On **other systems** (development and CI) it falls back to buffered `os.pwrite`/`os.preadv`
with `fsync` after the sequential write and after each random write, plus a best-effort
`posix_fadvise(DONTNEED)` before reads. Reads may still come from the page cache, so the
labels say "(com cache do sistema)" and `uncached` is 0. The analysis ignores disk results
with `uncached = 0`.

Phases, in order:

1. **Sequential write**: 1 MiB blocks up to the file size, or until 20 s pass (quick: 8 s),
   so very slow disks do not stall the scan; then a flush.
2. **Sequential read** of what was written, same time cap.
3. **Random read**: 4 KiB at random aligned offsets within the file, queue depth 1, for 8 s
   (quick: 2.5 s).
4. **Random write**: same, with write-through.

Worst case is about 56 s (full) on a disk slow enough to hit both sequential caps.

| Benchmark | Key | Unit | Meaning |
|---|---|---|---|
| `storage.sequential` | `write_mb_s`, `read_mb_s` | MB/s | MiB per second, 1 MiB blocks |
| | `file_mb` | MB | data actually written (may be below the target on slow disks) |
| | `uncached` | (none) | 1 = OS cache bypassed (Windows), 0 = buffered fallback |
| `storage.random` | `read_iops`, `write_iops` | IOPS | 4 KiB operations per second at queue depth 1 |
| | `read_latency_ms`, `write_latency_ms` | ms | average time per operation |
| | `uncached` | (none) | as above |

Free space is checked first: the file shrinks so that at least 1 GiB stays free on the volume,
and the test is skipped with an error if that leaves less than 64 MiB.

Limitations:

- Queue depth 1, single thread: this is the latency-bound pattern that makes a desktop feel
  slow, but it is far below an NVMe drive's rated maximum (measured at QD32 with many
  threads). Do not compare these numbers with the box specifications.
- A 1 GiB file can fit inside the SLC cache of most SSDs, so sustained writes on QLC drives
  may be worse than measured.
- Random reads over a 128 MiB (quick) file on an HDD cover a small area, so seeks are short
  and IOPS are somewhat optimistic.
- Write-through random writes on consumer SSDs without power-loss protection can be much
  slower than reads; this is real behavior, not an error.

## Analysis

`analyze(report)` runs every rule in `analysis/rules.py`, then builds the verdict
(`analysis/verdict.py`). The result is sorted by severity (critical first) and, within a
severity, by rule priority (registration order in `rules.py`). The verdict is always the
first item. A rule that raises is logged and skipped; every rule treats a missing check, a
`None` value, a non-numeric value or a failed benchmark as "no data" and produces nothing.

Each rule has a **role**, used only by the verdict:

| Role | Meaning |
|---|---|
| fault | hardware defect or maintenance problem |
| upgrade | a part too slow or too small |
| replace | the machine is not worth upgrading |
| software | settings, programs, drivers, Windows |
| network | outside the computer |
| other | context or something to investigate; does not drive the verdict |

### Rules

Listed in priority order. Each finding carries the numbers it used in `evidence`.

| Finding id | Role | Data | Triggers when | Severity | Why |
|---|---|---|---|---|---|
| `storage.disk_failing` | fault | `storage.health`, inventory disks, `system.events.disk_errors` | health status Warning/Unhealthy; wear >= 80%; temperature >= 55 °C (HDD) / 70 °C (SSD); the `storage.health` check itself is WARNING/CRITICAL (it weighs uncorrected errors, which are not in its data); disk errors in the event log | critical if Unhealthy, wear >= 95%, check CRITICAL or >= 10 log errors; else warning | A failing disk retries reads and freezes the system for seconds. The raw `read_errors_total` counters include corrected errors (normal on HDDs) so they are reported as evidence only. |
| `storage.system_hdd` | upgrade | inventory: system disk `media_type == "HDD"` | always when true | critical | Windows 10/11 does thousands of small random reads at boot and app start; an HDD delivers ~100 per second, an SSD thousands. The single most common cause of "slow PC". |
| `storage.behaves_like_hdd` | upgrade | unknown media type + `storage.random.read_iops` | read IOPS < 400 (uncached) | warning | Catches HDDs that Windows reports as "Unspecified" (common behind RAID/USB bridges). |
| `storage.slower_than_expected` | other | system disk type + disk benchmarks | below the per-type minimums in the table below (uncached only) | warning | A drive far below its class points to a full or DRAM-less/QLC SSD, overheating, IDE mode, a SATA II port, old firmware or a weak HDD. |
| `storage.busy` | software | `storage.activity` | busy >= 90% or average response >= 50 ms | critical if response >= 150 ms | With the disk saturated, everything queues. On an HDD the verdict treats this as explained by the SSD upgrade. |
| `storage.low_free_space` | software | `storage.free_space` (fallback: inventory volume C:) | free < 10% or < 15 GB | critical if < 5% or < 5 GB | No room for the page file and updates; full SSDs slow down. |
| `memory.low_total` | upgrade | inventory total RAM, OS name, `memory.pressure` | below 8 GB on Windows 10/11 or unknown OS (4 GB on older Windows), or below 16 GB while under memory pressure | critical if <= ~4 GB on Windows 10/11 or under pressure; else warning | Below 8 GB a modern browser plus Windows pages to disk. 16 GB is the target once 8 GB is already exhausted. 0.5 GB tolerance because Windows reports installed memory minus reserved. |
| `memory.pressure` | software | `memory.pressure`, `cpu.load.top_processes` | used >= 85%, commit >= 90% or hard faults >= 300/s, with >= 16 GB (or unknown) installed | critical if used >= 95% or commit >= 98% | With enough RAM installed, pressure means a program is consuming too much. |
| `memory.single_channel` | upgrade | inventory modules and slots, `memory.bandwidth.copy_gb_s` | one module in a board with >= 2 slots, or all modules on the same channel letter | warning if copy < 5 GB/s, else info | Single channel halves bandwidth; matters most with integrated graphics. Channel detection is a heuristic on slot names (`ChannelA-DIMM0`, `DIMM_A1`, `A1`); names like `DIMM 1` or `BANK 0` are not interpreted. |
| `memory.below_rated_speed` | software | module `speed_mhz` vs `configured_speed_mhz` | configured < 90% of rated | info | XMP/EXPO disabled, mixed modules or a CPU/board limit. Moderate gain only. |
| `cpu.throttling` | fault | `cpu.sustained`, `cpu.load` | throughput or clock drop >= 15%; or, from health data, clock < 60% of max while load >= 50% | critical if drop >= 30% | Dust, dried thermal paste, a weak charger or power limits. |
| `cpu.high_load` | software | `cpu.load` | load >= 85% | warning | Names the top process (ignoring Idle) if it uses >= 40%. |
| `cpu.weak` | replace | `cpu.single.score`, `cpu.multi.score`; CPU name when there are no scores | single < 550 or multi < 2000 | critical if single < 350 or multi < 1000; name-only match is info | An SSD and RAM do not fix a CPU that is too slow. Name patterns: Atom, Celeron, Pentium (not Gold), Athlon, AMD A4/A6/E1/E2, Core 2, Core i 2nd to 4th generation. A name alone is weak evidence, so it never drives the verdict. |
| `system.hardware_errors` | fault | `system.events` | any WHEA error or bug check, or >= 2 unexpected shutdowns | critical with WHEA or bug checks | Points to RAM, PSU, overheating, board or a bad driver. |
| `system.startup` | software | `system.startup` | >= 10 items | warning if >= 20 | Slow boot and memory used by background programs. |
| `system.uptime` | software | `system.uptime` | >= 7 days | warning if >= 30 days | Leaks and pending updates accumulate. With Fast Startup, shutting down does not reset uptime; only Restart does. |
| `system.pending_reboot` | software | `system.pending_reboot` | `pending` is true | info | Reasons (`component_servicing`, `windows_update`, `file_rename`) are shown in Portuguese. |
| `system.power_saver` | software | `system.power_plan` | `is_power_saver` | warning | The plan caps the CPU. |
| `system.on_battery` | other | `system.power_plan` | `on_battery` | info | Benchmarks on battery are lower; retest plugged in. |
| `system.antivirus_scan` | software | `system.antivirus` | `scan_in_progress` | warning | A scan competes for disk and CPU during the test. |
| `system.multiple_antivirus` | software | `system.antivirus.products` | >= 2 products other than Microsoft/Windows Defender | warning | Two real-time scanners double the work per file and conflict. Defender is excluded because Windows lists it even when it is passive. |
| `system.problem_devices` | software | `system.devices` | any problem device | warning | Missing or broken drivers (code 28 = no driver, 10 = cannot start, ...). |
| `system.app_crashes` | software | `system.events.app_crashes` | >= 10 in the window | info | Recurring program crashes. |
| `network.local` | network | `network.connectivity` gateway | loss >= 5% or latency >= 20 ms | critical if loss >= 30% | A healthy LAN answers in < 5 ms with no loss. `None` (router ignores ping) is not a failure. |
| `network.internet` | network | `network.connectivity` internet | loss >= 5% or latency >= 150 ms | critical if loss >= 30% | Provider or upstream problem. |
| `network.dns` | network | `network.connectivity.dns_ms` | >= 200 ms | warning | Every new site waits for DNS before it starts loading: "nothing opens". |
| `network.wifi` | network | `network.wifi` | signal < 40% or link < 20 Mbps | warning | Weak signal means retransmissions and drops. |

Disk expectations used by `storage.slower_than_expected` (queue depth 1, uncached, as measured
by this tool; "typical" is quoted to the user):

| Type | Min seq read | Min seq write | Min random read | Typical seq read | Typical random read |
|---|---|---|---|---|---|
| SSD NVMe | 800 MB/s | 400 MB/s | 5000 IOPS | 2500 MB/s | 12000 IOPS |
| SSD SATA | 300 MB/s | 150 MB/s | 3000 IOPS | 500 MB/s | 6000 IOPS |
| HD | 60 MB/s | 40 MB/s | 50 IOPS | 130 MB/s | 90 IOPS |

The disk type comes from the inventory: `media_type == "HDD"` is an HDD, `bus_type == "NVMe"`
is NVMe, any other `media_type == "SSD"` is SATA SSD; anything else is unknown.

### Verdict

`verdict.*` is one finding, category `SYSTEM`, always first. Its severity is the highest
severity among all findings (info if there are none). Only findings of severity **warning or
above** count; the first matching case wins:

| Order | Condition | Id | Title |
|---|---|---|---|
| 1 | a `replace` finding that is critical, or a warning one plus two or more upgrade parts | `verdict.replace` | Troca da máquina é mais econômica |
| 2 | any `fault` finding | `verdict.fault` | Problema de hardware: corrigir antes de qualquer upgrade |
| 3 | any upgrade parts | `verdict.upgrade` | Upgrade recomendado: SSD + 8 GB de RAM (parts vary) |
| 4 | any `software` finding | `verdict.software` | Problema de software, não de hardware |
| 5 | only `network` findings | `verdict.network` | Problema de rede, não do computador |
| 6 | nothing | `verdict.ok` | Nenhum gargalo encontrado |

Upgrade parts: "SSD" from `storage.system_hdd` or `storage.behaves_like_hdd`; "N GB de RAM"
from `memory.low_total` (its `recommended_total_gb`); otherwise "segundo pente de memória
(dual channel)" from a warning-level `memory.single_channel`. The verdict's detail lists the
other problems to fix (software and network), except `storage.busy` when an SSD is already
recommended. Its `evidence` holds the contributing finding ids per role and the parts list.

## Where the reference values come from

None of these numbers are citations of a specific study or product; they are rule-of-thumb
values. Treat them as assumptions to be tuned with real scans.

- **CPU scores**: the scale is anchored on the development machine (a cloud server core,
  ~19 ms per work unit = 1000 pts). The weak/very weak limits (550/350 single, 2000/1000
  multi) are **estimates** of where low-power Celeron/Atom-class and ~2012 to 2014 desktop
  cores fall relative to a current core in CPython workloads (roughly 30 to 55%). They should
  be recalibrated once scans from real client machines are available.
- **Disk expectations**: derived from typical published specifications (SATA III tops out
  around 550 MB/s; mainstream PCIe 3.0/4.0 NVMe drives read 2000 to 5000 MB/s; 7200 rpm
  desktop HDDs do 100 to 200 MB/s and roughly 75 to 150 random IOPS) and adjusted down for
  queue depth 1 and a single thread. The minimums are deliberately loose (roughly half of a
  healthy drive) so a finding means something is clearly wrong.
- **RAM sizes**: Microsoft's stated minimum for Windows 11 is 4 GB; 8 GB as a practical
  minimum and 16 GB as the comfortable target are common field practice, not official
  numbers.
- **Memory pressure, disk activity, free space, uptime, startup, network latency and
  Wi-Fi**: field-experience thresholds, chosen to flag clearly abnormal values rather than
  borderline ones.
- **Memory bandwidth 5 GB/s**: an estimate of single-threaded copy speed below which a
  modern machine is very likely running single channel or old memory (dual-channel DDR4 is
  typically around 10 GB/s or more in this test).
- **Throttling 15%/30%**: chosen above the normal turbo decay of a healthy CPU (it is
  normal for the clock to drop a few percent once turbo time limits expire).
