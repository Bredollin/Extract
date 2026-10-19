"""Regenerate the README screenshots in docs/images from the `--demo` data.

    python scripts/screenshots.py

Runs headless (QT_QPA_PLATFORM=offscreen) at 1280×800.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from PySide6.QtWidgets import QApplication  # noqa: E402

from extract.gui import demo, theme  # noqa: E402
from extract.gui.main_window import DIAGNOSTIC, REPORTS, RESULTS, MainWindow  # noqa: E402

OUTPUT = ROOT / "docs" / "images"
SIZE = (1280, 800)


def capture(window: MainWindow, name: str) -> Path:
    QApplication.processEvents()
    path = OUTPUT / f"{name}.png"
    window.grab().save(str(path))
    print(f"saved {path.relative_to(ROOT)}")
    return path


def main() -> int:
    app = QApplication.instance() or QApplication(sys.argv[:1])
    app.setStyle("Fusion")
    app.setFont(theme.app_font())
    OUTPUT.mkdir(parents=True, exist_ok=True)

    theme.manager().apply("dark", remember=False)
    window = MainWindow()
    window.resize(*SIZE)
    demo.load_into(window)
    window.show()

    window.show_page(RESULTS)
    window.results.show_tab("Achados")
    capture(window, "resultados")
    window.results.show_tab("Desempenho")
    capture(window, "desempenho")
    window.show_page(REPORTS)
    capture(window, "relatorios")

    theme.manager().apply("light", remember=False)
    window.show_page(RESULTS)
    window.results.show_tab("Achados")
    capture(window, "resultados-claro")

    theme.manager().apply("dark", remember=False)
    demo.show_scan_preview(window)
    window.show_page(DIAGNOSTIC)
    capture(window, "diagnostico")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
