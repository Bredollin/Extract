# Extract

**Find out why a Windows PC is slow, and what to do about it, in a few minutes from a USB stick.**

[![CI](https://github.com/Bredollin/Extract/actions/workflows/ci.yml/badge.svg)](https://github.com/Bredollin/Extract/actions/workflows/ci.yml)
![Python 3.10+](https://img.shields.io/badge/python-3.10%2B-blue)
![Platform: Windows](https://img.shields.io/badge/platform-Windows-0078D6)
[![License: GPL-3.0](https://img.shields.io/badge/license-GPL--3.0-green)](LICENSE)

[Leia em português](README.pt-BR.md)

![Results page: verdict, summary cards and ranked findings](docs/images/resultados.png)

Extract inventories the hardware, checks the health of Windows, benchmarks the CPU, memory
and disk, and turns all of it into a short list of ranked findings with a single verdict:
upgrade a part, fix the software, look at the network, or replace the machine.

> The app and its reports are in Brazilian Portuguese (the language of the clients it was
> built for). Code, comments and technical docs are in English.

## Why

I work as an IT technician. The most common call is some version of *"the computer is slow"*,
*"it freezes"* or *"nothing opens"*. The cause is usually one of a handful of things (Windows
on a mechanical hard drive, 4 GB of RAM, a failing disk, a CPU throttling because of dust,
too many startup programs, a bad network), but proving which one takes time, and the client
wants a clear answer: *is it worth upgrading, or should I buy a new machine?*

Extract automates that investigation. It runs on the client's PC without installation,
measures instead of guessing, and produces a report I can hand to the client with the
evidence behind each recommendation.

## Features

- **Hardware inventory**: system, CPU, memory modules and slots, motherboard, GPU, disks and
  volumes, network adapters (via CIM/WMI and `ctypes`).
- **Health checks**: disk health and free space, disk activity, memory pressure, CPU load and
  top processes, startup programs, event log errors (disk, WHEA, crashes, unexpected
  shutdowns), uptime and pending reboot, power plan, antivirus, problem devices, network
  reachability and Wi-Fi signal.
- **Benchmarks**: CPU single-core, multi-core and sustained load (detects thermal
  throttling), memory bandwidth, disk sequential and 4 KiB random I/O bypassing the Windows
  file cache. Full mode takes about 1.5 to 2 minutes; quick mode about 15 to 25 seconds.
- **Root-cause analysis and verdict**: 26 rules combine inventory, health and benchmark data
  into findings ranked by severity, each with its evidence and a recommendation. A verdict
  sums them up: replace the machine, fix a hardware fault first, upgrade (naming the parts),
  software problem, network problem, or no bottleneck found.
- **Reports**: one JSON file per scan, consolidated per client into an Excel workbook and a
  PDF, so several machines of the same client can be compared side by side.
- **Portable**: a single `Extract.exe`, no installation. Reports and settings
  (`extract.ini`) are stored next to the exe, on the USB stick; nothing goes to the registry
  and no log files are written on the client's PC.
- **Read-only, no admin required**: it never changes system settings. Without admin rights
  a few SMART reliability counters are unavailable, and the report says so.
- **Desktop app and CLI**: a PySide6 interface with dark and light themes, and an
  `extract-cli` command for scripted use.

### Screenshots

| Running a scan | Benchmarks |
|---|---|
| ![Scan in progress](docs/images/diagnostico.png) | ![Performance tab](docs/images/desempenho.png) |
| **Client reports** | **Light theme** |
| ![Reports page](docs/images/relatorios.png) | ![Results in the light theme](docs/images/resultados-claro.png) |

The screenshots use the built-in demo data (fictitious machines).

## Quick start

1. Download `Extract.exe` from the
   [Releases](https://github.com/Bredollin/Extract/releases) page and copy it to a USB stick.
2. On the client's PC, run `Extract.exe` from the stick. No installation or Python needed.
3. Type the client's name, choose what to run and start the diagnostic.
4. Reports are saved in `Relatorios\<client>\` next to the exe. Open the **Relatórios** page
   to export the client's machines to Excel or PDF.

If the folder next to the exe is not writable (a write-protected stick, a network share),
reports go to `Documents\Extract` instead.

> **Windows SmartScreen**: the exe is not code-signed yet, so Windows may show
> *"Windows protected your PC"*. Click **More info → Run anyway**. You can also build the exe
> yourself from source (see [Building the exe](#building-the-exe)).

## Command line

The CLI is installed as `extract-cli` (or run `python -m extract scan ...`). Its messages are
in Portuguese.

```console
# Full scan; saves JSON, Excel and PDF in reports/<client>
extract-cli scan --client "Clinica Exemplo"

# Quick benchmarks, custom output folder
extract-cli scan --client "Clinica Exemplo" --quick --output D:\Relatorios\Clinica

# Only the disk benchmark, skip health checks, keep only the JSON
extract-cli scan --only storage --no-health --json-only

# Inventory and health only, no benchmarks
extract-cli scan --no-benchmarks

# Rebuild Excel and PDF from a folder of JSON reports
extract-cli export reports/Clinica-Exemplo
extract-cli export reports/Clinica-Exemplo --excel resumo.xlsx --pdf resumo.pdf
```

| Option | Meaning |
|---|---|
| `--client NAME` | client name; also the name of the report folder |
| `--output FOLDER` | report folder (default `reports/<client>`, or `Relatorios/<client>` in the exe) |
| `--quick` | shorter benchmarks |
| `--no-health` / `--no-benchmarks` | skip a stage |
| `--only cpu,memory,storage` | run only these benchmarks |
| `--json-only` | do not generate Excel and PDF |
| `-v`, `--verbose` | detailed log |

Exit codes: `0` success, `1` error, `130` cancelled (Ctrl+C stops at the next safe point and
removes the benchmark temp file).

## How it works

```
collectors (inventory) → health (state checks) → benchmarks → analysis (findings + verdict)
                                                                   ↓
                                              MachineReport (JSON) → Excel / PDF, GUI, CLI
```

- A single pipeline (`core/pipeline.py`) wires the stages; the GUI and CLI only call it.
- Every stage reads and writes the same dataclasses (`core/models.py`); exports are rebuilt
  from the JSON, never by parsing text.
- All Windows queries go through an injectable PowerShell runner, so the test suite runs on
  any OS with recorded responses, and Windows-only tests run on a real Windows CI runner.
- A failing query leaves a field empty or marks a check as unknown; it never aborts the scan.

Details:

- [docs/architecture.md](docs/architecture.md): packages, data flow and design rules.
- [docs/diagnostics.md](docs/diagnostics.md): how each benchmark measures, every analysis
  rule and threshold, how the verdict is chosen, and where the reference values come from
  (including their limitations).

## Development

Requires Python 3.10+. The test suite also runs on Linux and macOS; real data collection and
the exe build need Windows.

```console
git clone https://github.com/Bredollin/Extract.git
cd Extract
python -m venv .venv
.venv\Scripts\activate            # Linux/macOS: source .venv/bin/activate
pip install -e ".[gui,dev]"
```

```console
pytest                            # tests (Windows-only tests are skipped elsewhere)
ruff check .                      # lint
ruff format --check .             # formatting
python -m extract.gui.app --demo  # open the GUI with sample reports
python scripts/screenshots.py     # regenerate docs/images (headless)
```

Other entry points: `extract` (GUI), `extract-cli` (CLI), `python -m extract` (GUI, or the CLI
when given `scan`/`export`). `--theme light` or `--theme dark` forces a GUI theme.

### Building the exe

On Windows:

```console
pyinstaller packaging/extract.spec --noconfirm
```

The output is `dist/Extract.exe`: a single-file, windowed build with a version resource, no
UPX packing and no admin manifest (to keep SmartScreen and antivirus heuristics calm).
CI builds it on every push, and pushing a `v*` tag publishes it to GitHub Releases.

## Project structure

```
Extract/
├── src/extract/
│   ├── core/          # data models, PowerShell runner, progress/cancellation, pipeline
│   ├── collectors/    # hardware inventory
│   ├── health/        # system health checks
│   ├── benchmarks/    # CPU, memory and disk tests
│   ├── analysis/      # rules, reference values, verdict
│   ├── reports/       # JSON storage, Excel, PDF, default report paths
│   ├── gui/           # PySide6 app (pages, widgets, themes, icons, demo data)
│   ├── cli.py         # extract-cli
│   └── __main__.py    # python -m extract
├── tests/             # pytest suite and anonymized fixtures (recorded PowerShell output)
├── docs/              # architecture, diagnostics, screenshots
├── packaging/         # PyInstaller spec and launcher
├── scripts/           # screenshot generator
├── .github/workflows/ # CI (lint, tests on Windows, exe build) and release
└── pyproject.toml
```

## Privacy and security

- **Read-only.** Extract does not change settings, install anything or need admin rights. The
  only file it writes outside the report folder is the temporary disk-benchmark file in the
  user's temp folder, which is always deleted (also on error or cancellation).
- **Nothing is uploaded.** There is no telemetry and no online service. The only network
  traffic is the reachability test: pings to the default gateway, `1.1.1.1` and `8.8.8.8`,
  and DNS lookups of a few well-known sites.
- **Reports are client data.** They contain the hostname, user name, serial numbers, IP and
  MAC addresses, startup programs and process names. Store and share them as you would any
  other client information. Never commit real reports: `reports/`, `*.xlsx` and `*.pdf` are
  ignored by git, and test fixtures are anonymized.
- **What can remain on the client's PC.** PyInstaller unpacks the exe into a `%TEMP%\_MEI*`
  folder that is removed on exit; Windows itself remembers recent files when you use an
  open/save dialog; and reports fall back to `Documents\Extract` if the stick is
  write-protected.
- **Report files are treated as input.** Edited or corrupted JSON files are skipped, and
  report text is always written to Excel as plain text, never as a formula.
- **Verify the download.** Each release publishes `Extract.exe.sha256`; compare it with
  `Get-FileHash .\Extract.exe` before running the exe on a client's machine.

## Roadmap

- Calibrate the CPU reference scores and other thresholds with scans from real client
  machines (today they are documented estimates; see
  [docs/diagnostics.md](docs/diagnostics.md#where-the-reference-values-come-from)).
- Code-sign the exe to avoid the SmartScreen warning.
- Possibly more interface and report languages (English, Spanish).

## History

Version 1.0 (October 2026) was a two-file Tkinter script that wrote hardware information to
text files. Version 2.0 is a full rewrite: a tested package with health checks, benchmarks,
root-cause analysis and a new interface. See [CHANGELOG.md](CHANGELOG.md).

## License

[GPL-3.0](LICENSE). Contributions are welcome: see [CONTRIBUTING.md](CONTRIBUTING.md).

## Author

**Michael Bredollin**, IT technician. GitHub: [@Bredollin](https://github.com/Bredollin)
