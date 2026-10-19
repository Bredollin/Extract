# Architecture

Extract answers one question for an IT technician: **why is this Windows machine slow, and
what should be done about it?** It collects the hardware inventory, checks the health of
the system, measures CPU, memory and disk performance, and turns all of that into a short
list of findings with recommendations.

## Flow

```
            ┌──────────────┐   ┌──────────────┐   ┌──────────────┐
 Windows ──▶│  collectors  │──▶│    health    │──▶│  benchmarks  │
 (CIM/WMI,  │  inventory   │   │ state checks │   │ CPU/RAM/disk │
  ctypes)   └──────┬───────┘   └──────┬───────┘   └──────┬───────┘
                   └──────────┬───────┴──────────────────┘
                              ▼
                       ┌──────────────┐      ┌──────────────────────┐
                       │   analysis   │─────▶│ MachineReport (JSON) │
                       │   findings   │      └──────────┬───────────┘
                       └──────────────┘                 ▼
                                              reports: Excel / PDF
                                              gui / cli: display
```

`core/pipeline.py::run_scan` is the only place that wires the stages together. The GUI and
the CLI call it and never talk to the stages directly.

## Packages

| Package | Responsibility |
|---|---|
| `core/` | Data models (`models.py`), PowerShell access (`powershell.py`), progress and cancellation (`progress.py`), the scan pipeline (`pipeline.py`). |
| `collectors/` | Hardware inventory: system, CPU, memory, motherboard, GPU, disks, volumes, network adapters. |
| `health/` | Current state checks: disk health and free space, memory pressure, CPU load, startup programs, event log errors, uptime, power plan, network reachability. |
| `benchmarks/` | Performance tests: CPU (single and multi-core, throttling under sustained load), memory bandwidth, disk sequential and random I/O. |
| `analysis/` | Rules that combine inventory, health and benchmarks into ranked `Finding`s. |
| `reports/` | One JSON file per scan, consolidated per client into Excel and PDF. |
| `gui/` | PySide6 desktop app. |
| `cli.py` | Command-line interface for scripted use. |

## Design rules

- **One data model.** Every stage reads and writes the dataclasses in `core/models.py`. A
  scan is saved as JSON; exports are rebuilt from JSON, never by parsing text.
- **Windows access is injectable.** All CIM/WMI queries go through a `PowerShellRunner`.
  Tests pass a `FakePowerShell` with recorded responses from `tests/fixtures/`, so the full
  suite runs on any OS. Tests marked `@pytest.mark.windows` run for real on the CI's
  Windows runner.
- **Fail soft.** A query that fails leaves that field empty or marks that check `UNKNOWN`;
  it never aborts the scan.
- **Read-only.** Extract never changes system settings. The only thing it writes outside
  the report folder is the temporary benchmark file, which is always deleted.
- **Language.** Code, comments and docs are in English. Everything the user sees in the app
  and in the reports is in Brazilian Portuguese.
- **Small dependency footprint.** Runtime: `PySide6`, `openpyxl`, `reportlab`. Everything
  else uses the standard library (`ctypes` for low-level Windows calls).
