"""Left card of the Diagnóstico page: client folder and the machine's group and what to run."""

from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import Signal
from PySide6.QtWidgets import QComboBox, QFileDialog, QWidget

from extract.core.models import Category
from extract.gui import settings
from extract.gui.theme import Space
from extract.gui.widgets.card import Card
from extract.gui.widgets.common import ElidedLabel, button, divider, hbox, label, vbox
from extract.gui.widgets.toggle import ToggleSwitch

LAST_CLIENT_KEY = "scan/last_client"
LAST_GROUP_KEY = "scan/last_group"
GROUPS_KEY = "scan/groups"
DEFAULT_GROUPS = ("Recepção", "Administrativo", "Financeiro", "Comercial", "Diretoria")
MAX_GROUP_LENGTH = 40
MAX_SAVED_GROUPS = 20
START_TEXT = "Iniciar inventário"


def _split_groups(value: object) -> list[str]:
    return [g.strip() for g in str(value or "").split("|") if g.strip()]


class ScanSetupCard(Card):
    start_requested = Signal()

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__("Configuração", parent=parent)
        self._custom_folder: Path | None = None
        self._build_client_section()
        self.body.addSpacing(Space.XS)
        self.body.addWidget(divider())
        self.body.addSpacing(Space.XS)
        self._build_options_section()
        self.body.addStretch(1)
        self.start_button = button(START_TEXT, "play", "primary", "large")
        self.start_button.clicked.connect(self.start_requested)
        self.body.addWidget(self.start_button)
        self.refresh_clients()

    # --- Client folder -------------------------------------------------------------

    def _build_client_section(self) -> None:
        self.body.addWidget(label("Cliente", role="strong"))
        row = hbox(Space.S)
        self.client_combo = QComboBox()
        self.client_combo.setEditable(True)
        self.client_combo.setInsertPolicy(QComboBox.InsertPolicy.NoInsert)
        self.client_combo.lineEdit().setPlaceholderText("Nome do cliente ou empresa")
        self.client_combo.editTextChanged.connect(self._on_client_edited)
        row.addWidget(self.client_combo, 1)
        self.browse_button = button("", "folder")
        self.browse_button.setToolTip("Escolher outra pasta para os relatórios")
        self.browse_button.clicked.connect(self._choose_folder)
        row.addWidget(self.browse_button)
        self.body.addLayout(row)
        self.folder_label = ElidedLabel("")
        self.folder_label.setProperty("role", "caption")
        self.body.addWidget(self.folder_label)

    def refresh_clients(self) -> None:
        root = settings.reports_root()
        names = sorted(p.name for p in root.iterdir() if p.is_dir()) if root.is_dir() else []
        current = str(settings.value(LAST_CLIENT_KEY, "")) or self.client_combo.currentText()
        self.client_combo.blockSignals(True)
        self.client_combo.clear()
        self.client_combo.addItems(names)
        self.client_combo.setEditText(current)
        self.client_combo.blockSignals(False)
        self._update_folder_label()

    def _on_client_edited(self, _text: str) -> None:
        self._custom_folder = None
        self._update_folder_label()

    def _choose_folder(self) -> None:
        start = str(self.folder.parent if self.folder.parent.exists() else settings.reports_root())
        chosen = QFileDialog.getExistingDirectory(self, "Pasta do cliente", start)
        if chosen:
            self.set_folder(Path(chosen))

    def set_folder(self, folder: Path) -> None:
        self.client_combo.blockSignals(True)
        self.client_combo.setEditText(folder.name)
        self.client_combo.blockSignals(False)
        self._custom_folder = folder
        self._update_folder_label()

    def _update_folder_label(self) -> None:
        text = f"Salvo em  {self.folder}"
        self.folder_label.setText(text)
        self.folder_label.setToolTip(str(self.folder))

    @property
    def client(self) -> str:
        return self.client_combo.currentText().strip()

    @property
    def folder(self) -> Path:
        return self._custom_folder or settings.client_folder(self.client)

    def remember_client(self) -> None:
        settings.set_value(LAST_CLIENT_KEY, self.client)

    # --- Group and what runs ----------------------------------------------------------

    def _build_options_section(self) -> None:
        self.body.addWidget(label("Grupo", role="strong"))
        self.group_combo = QComboBox()
        self.group_combo.setEditable(True)
        self.group_combo.setInsertPolicy(QComboBox.InsertPolicy.NoInsert)
        self.group_combo.lineEdit().setPlaceholderText("Setor da máquina, ex.: Recepção")
        self.body.addWidget(self.group_combo)
        hint = label("Usado para separar as máquinas na planilha.", role="caption")
        self.body.addWidget(hint)
        self.body.addSpacing(Space.S)
        self.body.addWidget(label("O que executar", role="strong"))
        self.inventory = self._option(
            "Inventário rápido",
            "Windows e versão, memória e pentes, discos e saúde, IP, DHCP ou fixo e MAC. "
            "Poucos segundos.",
            True,
        )
        self.inventory.set_locked(True)
        self.health = self._option(
            "Saúde do sistema", "Disco, memória, eventos, inicialização", False
        )
        self.benchmarks = self._option(
            "Testes de desempenho", "Mede a velocidade real das peças", False
        )
        sub = hbox(Space.L, (44, 0, 0, 0))
        self.bench_toggles: dict[Category, ToggleSwitch] = {}
        for category, text in (
            (Category.CPU, "CPU"),
            (Category.MEMORY, "Memória"),
            (Category.STORAGE, "Disco"),
        ):
            toggle = ToggleSwitch(text, True)
            self.bench_toggles[category] = toggle
            sub.addWidget(toggle)
        sub.addStretch(1)
        self.body.addLayout(sub)
        self.quick = self._option("Modo rápido", "Testes mais curtos, em cerca de 1 minuto", False)
        self.benchmarks.toggled.connect(self._sync_benchmarks)
        self.health.toggled.connect(self._sync_start_text)
        self.benchmarks.toggled.connect(self._sync_start_text)
        self._sync_benchmarks(False)
        self.refresh_groups()

    def refresh_groups(self) -> None:
        current = self.group_combo.currentText().strip() or str(
            settings.value(LAST_GROUP_KEY, "") or ""
        )
        names = list(DEFAULT_GROUPS)
        for name in _split_groups(settings.value(GROUPS_KEY, "")):
            if name.casefold() not in {n.casefold() for n in names}:
                names.append(name)
        self.group_combo.blockSignals(True)
        self.group_combo.clear()
        self.group_combo.addItems(names)
        self.group_combo.setEditText(current)
        self.group_combo.blockSignals(False)

    def _option(self, title: str, caption: str, checked: bool = True) -> ToggleSwitch:
        column = vbox(0)
        toggle = ToggleSwitch(title, checked)
        column.addWidget(toggle)
        hint = label(caption, role="caption")
        hint.setWordWrap(True)
        hint.setContentsMargins(44, 0, 0, 0)
        column.addWidget(hint)
        self.body.addLayout(column)
        return toggle

    def _sync_benchmarks(self, enabled: bool) -> None:
        for toggle in self.bench_toggles.values():
            toggle.setEnabled(enabled)
        self.quick.setEnabled(enabled)

    def _sync_start_text(self, _checked: bool = False) -> None:
        self.start_button.setText(self._start_text)

    @property
    def inventory_only(self) -> bool:
        return not self.health.isChecked() and not self.benchmark_categories

    @property
    def _start_text(self) -> str:
        return START_TEXT if self.inventory_only else "Iniciar diagnóstico"

    @property
    def benchmark_categories(self) -> set[Category]:
        if not self.benchmarks.isChecked():
            return set()
        return {cat for cat, toggle in self.bench_toggles.items() if toggle.isChecked()}

    @property
    def group(self) -> str:
        return " ".join(self.group_combo.currentText().split())[:MAX_GROUP_LENGTH]

    def remember_group(self) -> None:
        group = self.group
        settings.set_value(LAST_GROUP_KEY, group)
        if group and group.casefold() not in {g.casefold() for g in DEFAULT_GROUPS}:
            saved = _split_groups(settings.value(GROUPS_KEY, ""))
            if group.casefold() not in {g.casefold() for g in saved}:
                settings.set_value(GROUPS_KEY, "|".join([*saved, group][-MAX_SAVED_GROUPS:]))

    def build_options(self):
        from extract.core.pipeline import ScanOptions

        # The quick inventory is the default (disk health comes with it); the slower health
        # checks and benchmarks run only when switched on.
        return ScanOptions(
            client=self.client,
            group=self.group,
            health=self.health.isChecked(),
            benchmarks=self.benchmark_categories,
            quick_benchmarks=self.quick.isChecked(),
        )

    def set_running(self, running: bool) -> None:
        widgets = (self.client_combo, self.browse_button, self.group_combo)
        for widget in (*widgets, self.health, self.benchmarks):
            widget.setEnabled(not running)
        for toggle in self.bench_toggles.values():
            toggle.setEnabled(not running and self.benchmarks.isChecked())
        self.quick.setEnabled(not running and self.benchmarks.isChecked())
        self.start_button.setEnabled(not running)
        busy = "Inventário em andamento…" if self.inventory_only else "Diagnóstico em andamento…"
        self.start_button.setText(busy if running else self._start_text)
