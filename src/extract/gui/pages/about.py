"""Sobre page: version, what the tool does and where the code lives."""

from __future__ import annotations

from PySide6.QtCore import QUrl
from PySide6.QtGui import QDesktopServices
from PySide6.QtWidgets import QWidget

from extract import __version__
from extract.gui.icons import AppLogo, IconLabel
from extract.gui.theme import Space
from extract.gui.widgets.card import Card
from extract.gui.widgets.common import button, hbox, label, vbox
from extract.gui.widgets.page_header import PageHeader

REPO_URL = "https://github.com/Bredollin/Extract"
DESCRIPTION = (
    "O Extract responde a uma pergunta do técnico de TI: por que este computador está "
    "lento e o que fazer? Ele coleta o inventário de hardware, verifica a saúde do "
    "Windows, mede o desempenho real de processador, memória e disco e transforma tudo "
    "em uma lista curta de achados com recomendações, antes de trocar peças ou a máquina."
)
TAGLINE = "Diagnóstico de hardware, saúde e desempenho para Windows"
FEATURES = (
    ("cpu", "Inventário completo", "Processador, memória, placa-mãe, vídeo, discos e rede."),
    ("heart-pulse", "Saúde do sistema", "SMART, espaço livre, eventos, inicialização e energia."),
    ("gauge", "Testes de desempenho", "CPU, memória e disco medidos na própria máquina."),
    ("files", "Relatórios por cliente", "JSON por máquina, consolidado em Excel e PDF."),
)


class AboutPage(QWidget):
    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("Page")
        column = vbox(Space.XL, (Space.XXL, Space.XL + 4, Space.XXL, Space.XL))
        column.addWidget(PageHeader("Sobre", "Informações do programa."))

        card = Card(padding=Space.XXL, spacing=Space.L)
        top = hbox(Space.XL)
        top.addWidget(AppLogo(72))
        names = vbox(Space.XS)
        title = label("Extract", role="title")
        names.addWidget(title)
        names.addWidget(
            label(
                f"Versão {__version__}  ·  {TAGLINE}",
                role="muted",
            )
        )
        names.addStretch(1)
        top.addLayout(names, 1)
        card.body.addLayout(top)
        description = label(DESCRIPTION, wrap=True)
        description.setMaximumWidth(760)
        card.body.addWidget(description)
        card.body.addSpacing(Space.S)
        for icon_name, heading, text in FEATURES:
            row = hbox(Space.M)
            row.addWidget(IconLabel(icon_name, "accent", 16, badge=True))
            texts = vbox(0)
            texts.addWidget(label(heading, role="strong"))
            texts.addWidget(label(text, role="muted"))
            row.addLayout(texts, 1)
            card.body.addLayout(row)
        card.body.addSpacing(Space.S)
        links = hbox(Space.S)
        github = button("Código no GitHub", "github")
        github.setToolTip(REPO_URL)
        github.clicked.connect(lambda: QDesktopServices.openUrl(QUrl(REPO_URL)))
        links.addWidget(github)
        links.addStretch(1)
        links.addWidget(label("Licença GPL-3.0  ·  Michael Bredollin", role="caption"))
        card.body.addLayout(links)
        column.addWidget(card)
        column.addStretch(1)
        self.setLayout(column)
