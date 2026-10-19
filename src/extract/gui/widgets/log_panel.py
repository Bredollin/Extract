"""Collapsible log viewer fed by a `logging.Handler` (safe to log from worker threads)."""

from __future__ import annotations

import contextlib
import logging

from PySide6.QtCore import QObject, Qt, Signal
from PySide6.QtWidgets import QPlainTextEdit, QPushButton, QWidget

from extract.gui.icons import icon
from extract.gui.theme import Space, mono_font
from extract.gui.widgets.common import hbox, label, vbox

MAX_LINES = 2000


class _Emitter(QObject):
    message = Signal(str)


class QtLogHandler(logging.Handler):
    """Forwards log records to the GUI thread through a Qt signal (queued connection)."""

    def __init__(self, level: int = logging.INFO) -> None:
        super().__init__(level)
        self.emitter = _Emitter()
        self.setFormatter(
            logging.Formatter("%(asctime)s  %(levelname)-7s  %(message)s", "%H:%M:%S")
        )

    def emit(self, record: logging.LogRecord) -> None:
        # RuntimeError: the window (and the emitter's C++ object) is gone already.
        with contextlib.suppress(RuntimeError):
            self.emitter.message.emit(self.format(record))


class LogPanel(QWidget):
    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        column = vbox(Space.S)
        head = hbox(Space.S)
        self.toggle = QPushButton("Registro de execução")
        self.toggle.setProperty("variant", "ghost")
        self.toggle.setCheckable(True)
        self.toggle.setCursor(Qt.CursorShape.PointingHandCursor)
        self.toggle.setIcon(icon("chevron-right", "text_muted", "text_muted"))
        self.toggle.toggled.connect(self.set_expanded)
        head.addWidget(self.toggle)
        head.addStretch(1)
        self.count = label("", role="caption")
        head.addWidget(self.count)
        column.addLayout(head)
        self.view = QPlainTextEdit()
        self.view.setObjectName("LogView")
        self.view.setReadOnly(True)
        self.view.setFont(mono_font())
        self.view.setMaximumBlockCount(MAX_LINES)
        self.view.setLineWrapMode(QPlainTextEdit.LineWrapMode.WidgetWidth)
        self.view.setVisible(False)
        column.addWidget(self.view, 1)
        self.setLayout(column)
        self._lines = 0

    def set_expanded(self, expanded: bool) -> None:
        self.toggle.setChecked(expanded)
        self.view.setVisible(expanded)
        self.toggle.setIcon(icon("chevron-down" if expanded else "chevron-right", "text_muted"))

    def append(self, line: str) -> None:
        self.view.appendPlainText(line)
        self._lines += 1
        self.count.setText(f"{self._lines} linhas")

    def clear(self) -> None:
        self.view.clear()
        self._lines = 0
        self.count.setText("")
