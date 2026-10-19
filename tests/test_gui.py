"""GUI tests, run headless (offscreen Qt platform)."""

from __future__ import annotations

import os
import struct
import time
from pathlib import Path

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
pytest.importorskip("PySide6.QtWidgets", exc_type=ImportError)

from PySide6.QtWidgets import QApplication

from extract.core.models import Category, MachineReport
from extract.core.progress import CancelToken
from extract.gui import demo, formatting, settings, theme
from extract.gui.scan_steps import idle_states, step_states
from extract.gui.widgets.steps_view import StepState
from extract.gui.workers import ScanWorker, start_in_thread


@pytest.fixture(scope="module")
def qapp():
    app = QApplication.instance() or QApplication([])
    app.setStyle("Fusion")
    return app


@pytest.fixture(autouse=True)
def portable_dirs(tmp_path, monkeypatch):
    """Keep settings and reports inside the test's temporary folder."""
    monkeypatch.chdir(tmp_path)  # from source, app_dir() is the working directory
    monkeypatch.setattr(settings, "_memory", {})
    return tmp_path


@pytest.fixture
def window(qapp):
    from extract.gui.main_window import MainWindow

    theme.manager().apply("dark", remember=False)
    win = MainWindow()
    win.resize(1280, 800)
    win.show()
    yield win
    win.close()
    win.deleteLater()
    qapp.processEvents()


def wait_until(predicate, timeout: float = 5.0) -> bool:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        QApplication.processEvents()
        if predicate():
            return True
        time.sleep(0.01)
    return predicate()


def stub_scan(options, progress, cancel):
    for step in range(5):
        cancel.raise_if_cancelled()
        progress(step / 5, f"Etapa {step}")
    progress(1.0, "Concluído")
    report = demo.build_demo_report()
    report.client = options.client
    return report


def scan_options(client: str = "Cliente Teste"):
    from extract.core.pipeline import ScanOptions

    return ScanOptions(client=client)


# --- Theme -------------------------------------------------------------------------


@pytest.mark.parametrize("name", theme.THEME_NAMES)
def test_palette_loads_and_builds_stylesheet(qapp, name):
    palette = theme.load_palette(name)
    assert all(token in palette.colors for token in theme.REQUIRED_TOKENS)
    stylesheet = theme.build_stylesheet(palette)
    assert "${" not in stylesheet
    assert palette["accent"] in stylesheet


@pytest.mark.parametrize("name", theme.THEME_NAMES)
def test_palette_text_meets_wcag_aa(qapp, name):
    p = theme.load_palette(name)
    for background in ("background", "surface", "surface_alt"):
        for token in ("text", "text_muted"):
            assert theme.contrast_ratio(p[token], p[background]) >= 4.5, (token, background)
    for tone in ("accent", "ok", "warning", "critical", "info"):
        assert theme.contrast_ratio(p[tone], p["surface"]) >= 4.5, tone
        assert theme.contrast_ratio(p[tone], p[f"{tone}_soft"]) >= 4.5, f"{tone} chip"
    assert theme.contrast_ratio(p["accent_text"], p["accent"]) >= 4.5


def test_theme_toggle_is_remembered_in_portable_ini(qapp, portable_dirs):
    theme.manager().apply("dark")
    assert theme.manager().toggle().name == "light"
    assert (portable_dirs / settings.SETTINGS_FILENAME).exists()
    settings._memory.clear()
    assert theme.manager().apply_saved().name == "light"
    theme.manager().apply("dark", remember=False)


# --- Main window and pages ----------------------------------------------------------


def test_main_window_switches_pages(window):
    from extract.gui.main_window import ABOUT, DIAGNOSTIC, REPORTS, RESULTS

    for index in (RESULTS, REPORTS, ABOUT, DIAGNOSTIC):
        window.sidebar.buttons[index].click()
        assert window.stack.currentIndex() == index
        assert window.sidebar.buttons[index].isChecked()


def test_theme_button_switches_palette(window):
    window.sidebar.theme_button.click()
    assert theme.palette().name == "light"
    assert window.sidebar.theme_button.text() == "Tema escuro"
    window.sidebar.theme_button.click()
    assert theme.palette().name == "dark"


def test_results_page_renders_demo_report(window):
    report = demo.build_demo_report()
    window.open_report(report)
    page = window.results
    assert window.stack.currentWidget() is page
    assert page.header.title.text() == "RECEPCAO-01"
    assert page.banner.title.text() == report.findings[0].title
    assert page.banner.property("tone") == "critical"
    assert [page.tabs.tabText(i) for i in range(page.tabs.count())] == list(
        ("Achados", "Saúde", "Desempenho", "Hardware")
    )
    from extract.gui.widgets.finding_card import FindingCard

    cards = page.tabs.widget(0).findChildren(FindingCard)
    assert len(cards) == len(report.findings) - 1  # the verdict is the banner


def test_results_page_handles_empty_report(window):
    window.open_report(MachineReport())
    assert window.results.banner.title.text() == "Nenhum problema relevante encontrado"


def test_reports_page_lists_client_folder(window, portable_dirs):
    folder = portable_dirs / "reports" / "Clinica"
    demo.save_demo_fleet(folder)
    window.reports.refresh_clients(folder)
    assert window.reports.table.rowCount() == 3
    assert len(window.reports.selected_reports()) == 3
    assert window.reports.pdf_button.isEnabled()


def test_performance_bars_use_reference(qapp):
    from extract.gui.pages.results.performance import fraction_tone, reference_fraction

    seq = next(b for b in demo.build_demo_report().benchmarks if b.id == "storage.sequential")
    fraction = reference_fraction(seq, "read_mb_s")
    assert fraction == pytest.approx(118.6 / 500)
    assert fraction_tone(fraction) == "critical"
    assert reference_fraction(seq, "file_mb") is None


# --- Scan worker -------------------------------------------------------------------


def run_worker(worker: ScanWorker) -> dict[str, object]:
    events: dict[str, object] = {}
    worker.progress.connect(lambda f, m: events.setdefault("progress", []).append(f))
    worker.finished.connect(lambda report, path: events.update(finished=(report, path)))
    worker.failed.connect(lambda message: events.update(failed=message))
    worker.cancelled.connect(lambda: events.update(cancelled=True))
    thread = start_in_thread(worker)
    assert wait_until(lambda: {"finished", "failed", "cancelled"} & events.keys())
    assert thread.wait(5000)
    return events


def test_worker_runs_scan_and_saves_report(qapp, tmp_path):
    events = run_worker(ScanWorker(scan_options(), tmp_path, stub_scan))
    report, path = events["finished"]
    assert report.client == "Cliente Teste"
    assert Path(path).exists() and Path(path).parent == tmp_path
    assert events["progress"][-1] == 1.0


def test_worker_uses_pipeline_by_default(qapp, tmp_path, monkeypatch):
    import extract.core.pipeline as pipeline

    monkeypatch.setattr(pipeline, "run_scan", stub_scan)
    events = run_worker(ScanWorker(scan_options(), tmp_path))
    assert "finished" in events


def test_worker_cancel(qapp, tmp_path):
    started = []

    def slow_scan(options, progress, cancel: CancelToken):
        started.append(True)
        while True:
            cancel.raise_if_cancelled()
            time.sleep(0.01)

    worker = ScanWorker(scan_options(), tmp_path, slow_scan)
    events: dict[str, object] = {}
    worker.cancelled.connect(lambda: events.update(cancelled=True))
    thread = start_in_thread(worker)
    assert wait_until(lambda: started)
    worker.cancel()
    assert wait_until(lambda: "cancelled" in events)
    assert thread.wait(5000)
    assert not list(tmp_path.glob("*.json"))


def test_worker_reports_failure(qapp, tmp_path):
    def broken_scan(options, progress, cancel):
        raise RuntimeError("PowerShell indisponível")

    events = run_worker(ScanWorker(scan_options(), tmp_path, broken_scan))
    assert events["failed"] == "PowerShell indisponível"


def test_diagnostic_page_runs_scan_and_opens_results(window, portable_dirs):
    page = window.diagnostic
    page.scan_function = stub_scan
    page.setup.client_combo.setEditText("Cliente Teste")
    page.start_scan()
    assert page.is_running
    assert wait_until(lambda: window.stack.currentWidget() is window.results)
    assert page.wait_for_scan()
    assert all(row.state is StepState.DONE for row in page.progress.steps.rows.values())
    assert list((portable_dirs / "reports" / "Cliente-Teste").glob("*.json"))
    assert page.setup.start_button.isEnabled()


# --- Helpers -------------------------------------------------------------------------


def test_step_states_follow_progress():
    enabled = {"health": False, "benchmarks": True}
    assert idle_states(enabled)["inventory"] is StepState.PENDING
    states = step_states(0.5, enabled)
    assert states["inventory"] is StepState.DONE
    assert states["health"] is StepState.SKIPPED
    assert states["benchmarks"] is StepState.RUNNING
    assert states["analysis"] is StepState.PENDING
    assert step_states(1.0, enabled, finished=True)["save"] is StepState.RUNNING


@pytest.mark.parametrize(
    ("value", "expected"),
    [(1234.4, "1.234"), (118.6, "119"), (8.4, "8,4"), (0.78, "0,78"), (4.0, "4"), (12.34, "12,3")],
)
def test_number_formatting(value, expected):
    assert formatting.number(value) == expected


def test_duration_and_units():
    assert formatting.duration(95) == "01:35"
    assert formatting.duration(3725) == "1:02:05"
    assert formatting.with_unit(3.4, "x") == "3,4x"
    assert formatting.with_unit(642, "pts") == "642 pts"


def test_benchmark_categories_follow_toggles(window):
    setup = window.diagnostic.setup
    setup.bench_toggles[Category.STORAGE].setChecked(False)
    assert setup.benchmark_categories == {Category.CPU, Category.MEMORY}
    setup.benchmarks.setChecked(False)
    assert setup.benchmark_categories == set()
    assert setup.build_options().benchmarks == set()


def test_icon_ico_has_multiple_sizes():
    from extract.gui.icons import APP_ICON_ICO

    data = APP_ICON_ICO.read_bytes()
    reserved, kind, count = struct.unpack("<HHH", data[:6])
    assert (reserved, kind) == (0, 1)
    assert count >= 5
