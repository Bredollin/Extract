# Contributing

Thanks for your interest in Extract. Bug reports, real-world scan results that help calibrate
the thresholds, and pull requests are all welcome.

## Setup

Python 3.10 or newer. The tests run on any OS; real collection and the exe build need Windows.

```console
git clone https://github.com/Bredollin/Extract.git
cd Extract
python -m venv .venv
.venv\Scripts\activate            # Linux/macOS: source .venv/bin/activate
pip install -e ".[gui,dev]"
```

## Checks

Run these before opening a pull request (CI runs the same ones):

```console
ruff check .
ruff format --check .
pytest
```

On Linux/macOS, tests marked `@pytest.mark.windows` are skipped; CI runs them on a Windows
runner. To try the GUI without scanning, use `python -m extract.gui.app --demo`. If you change
the interface, regenerate the screenshots with `python scripts/screenshots.py`.

## Conventions

See [docs/architecture.md](docs/architecture.md) for the full design rules. In short:

- **Language.** Code, comments, commit messages and docs are in English. Everything the user
  sees in the app and in the reports is in Brazilian Portuguese.
- **One data model.** Stages read and write the dataclasses in `src/extract/core/models.py`.
  The GUI and CLI go through `core/pipeline.py::run_scan`, never the stages directly.
- **Windows access through `PowerShellRunner`.** New queries need recorded responses in
  `tests/fixtures/` so they can be tested with `FakePowerShell`.
- **Fail soft and stay read-only.** A failing query leaves a field empty or marks a check
  `UNKNOWN`; Extract never changes system settings.
- **Anonymized fixtures.** Never commit real hostnames, user names, serial numbers, IP/MAC
  addresses or client reports.
- **No new dependencies without discussion.** The runtime depends only on PySide6, openpyxl
  and reportlab; open an issue before adding anything.
- **Thresholds** live in `src/extract/analysis/reference.py`; when you change one, update
  [docs/diagnostics.md](docs/diagnostics.md) and explain where the value comes from.

By contributing, you agree that your contributions are licensed under the
[GPL-3.0](LICENSE).
