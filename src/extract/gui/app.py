"""Entry point of the desktop app: `extract` (or `python -m extract` without arguments)."""

from __future__ import annotations

import argparse
import logging
import multiprocessing
import sys

from extract import __version__

APP_ID = "Bredollin.Extract"


def parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(prog="extract", description="Extract (interface gráfica)")
    parser.add_argument("--demo", action="store_true", help="abre com relatórios de exemplo")
    parser.add_argument("--theme", choices=("dark", "light"), help="tema da interface")
    args, _qt_args = parser.parse_known_args(argv)
    return args


def setup_logging() -> None:
    # The packaged exe has no console (stderr is None) and must not leave log files on a
    # client's PC; the in-app log panel attaches its own handler.
    logger = logging.getLogger("extract")
    logger.setLevel(logging.INFO)
    if sys.stderr is not None:
        handler = logging.StreamHandler()
        handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(name)s: %(message)s"))
        logger.addHandler(handler)


def _set_windows_app_id() -> None:
    """Give the taskbar our own icon instead of python.exe's."""
    if sys.platform != "win32":
        return
    import ctypes

    try:
        ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID(APP_ID)
    except (AttributeError, OSError):
        logging.getLogger(__name__).debug("Could not set AppUserModelID", exc_info=True)


def main(argv: list[str] | None = None) -> int:
    multiprocessing.freeze_support()
    args = parse_args(sys.argv[1:] if argv is None else argv)
    setup_logging()
    _set_windows_app_id()

    from PySide6.QtCore import Qt
    from PySide6.QtGui import QGuiApplication
    from PySide6.QtWidgets import QApplication

    from extract.gui import theme
    from extract.gui.icons import app_icon
    from extract.gui.main_window import MainWindow

    QGuiApplication.setHighDpiScaleFactorRoundingPolicy(
        Qt.HighDpiScaleFactorRoundingPolicy.PassThrough
    )
    app = QApplication.instance() or QApplication(sys.argv[:1])
    app.setApplicationName("Extract")
    app.setOrganizationName("Bredollin")
    app.setApplicationVersion(__version__)
    app.setWindowIcon(app_icon())
    app.setStyle("Fusion")
    app.setFont(theme.app_font())
    if args.theme:
        theme.manager().apply(args.theme, remember=False)
    else:
        theme.manager().apply_saved()

    window = MainWindow()
    if args.demo:
        from extract.gui import demo

        demo.load_into(window)
    window.show()
    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())
