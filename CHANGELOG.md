# Changelog

All notable changes to this project are documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and this
project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [2.0.0] - 2026-10-19

Full rewrite. Extract now explains *why* a machine is slow instead of only listing its
hardware.

### Added

- Health checks: disk health, free space and activity, memory pressure, CPU load and top
  processes, startup programs, event log errors, uptime and pending reboot, power plan,
  antivirus, problem devices, network reachability and Wi-Fi signal.
- Benchmarks: CPU single-core, multi-core and sustained load (throttling detection), memory
  bandwidth, disk sequential and random I/O bypassing the Windows file cache; full and quick
  modes; cancellable, with the temporary test file always removed.
- Root-cause analysis: 26 rules that turn inventory, health and benchmark data into findings
  ranked by severity, with evidence and recommendations, plus a verdict (replace, fix
  hardware fault, upgrade with named parts, software, network, or no bottleneck).
- One JSON report per scan as the single source of truth; Excel and PDF are rebuilt from it.
- `extract-cli` command (`scan`, `export`) for scripted use.
- Portable mode for the packaged exe: reports in `Relatorios/` and settings in `extract.ini`
  next to the exe, with a `Documents\Extract` fallback when that folder is read-only.
- Demo mode (`--demo`) and a script that regenerates the README screenshots.
- Test suite with recorded PowerShell fixtures, runnable on any OS, plus real-collection
  tests on Windows.
- GitHub Actions: lint, tests on Windows (Python 3.10 and 3.12), end-to-end quick scan, exe
  build, and release publishing on `v*` tags.
- Architecture and diagnostics documentation, CONTRIBUTING and this changelog.

### Changed

- Restructured into a `src/extract` package (core, collectors, health, benchmarks, analysis,
  reports, gui) with shared data models.
- New PySide6 desktop interface with dark and light themes, replacing Tkinter/ttkbootstrap.
- Hardware inventory rewritten as separate, tested collectors with more detail (memory
  slots and channels, disk bus and media type, volumes).
- Excel and PDF reports now include the verdict, findings and benchmark results per machine
  (the PDF also lists the health checks).
- PyInstaller build defined in `packaging/extract.spec`: single windowed exe with version
  resource, no UPX, no admin manifest.
- Minimum Python version raised from 3.8 to 3.10.
- License stated correctly as GPL-3.0 (the previous README said MIT).

### Removed

- `extrac.py` and `gui_extract.py` (replaced by the package).
- Plain-text `*-info.txt` reports (replaced by JSON).
- `requirements.txt` (dependencies are declared in `pyproject.toml`).
- `ttkbootstrap` dependency.

## [1.0.0] - 2026-10-06

### Added

- Hardware scan via PowerShell/CIM: CPU, RAM, motherboard, GPU, disks and network adapters.
- Tkinter (ttkbootstrap) interface with per-client report folders, component selection and
  a log panel.
- Plain-text report per machine.
- Consolidation of a client's reports into an Excel workbook and a landscape PDF.

[2.0.0]: https://github.com/Bredollin/Extract/compare/v1.0.0...v2.0.0
[1.0.0]: https://github.com/Bredollin/Extract/releases/tag/v1.0.0
