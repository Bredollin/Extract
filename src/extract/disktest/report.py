"""Save a disk test as JSON plus a one-page PDF the technician can hand to the client.

Files go to `<reports root>/teste-de-disco/`, apart from the per-client scan folders, so
the scan lists and exports never pick them up.
"""

from __future__ import annotations

import json
import logging
from datetime import datetime
from pathlib import Path
from xml.sax.saxutils import escape

from extract.core.models import Status
from extract.health.base import fmt
from extract.reports.paths import DISK_TEST_FOLDER, default_reports_root
from extract.reports.storage import safe_filename

from . import summary
from .models import DiskTestMode, DiskTestReport

log = logging.getLogger(__name__)

FOLDER_NAME = DISK_TEST_FOLDER
SUFFIX = ".disco.json"

STATUS_HEX = {
    Status.OK: "#1E7F4F",
    Status.WARNING: "#B7791F",
    Status.CRITICAL: "#C53030",
    Status.UNKNOWN: "#5B6573",
}

# Display order and Portuguese format of the performance metrics.
PERFORMANCE_ROWS = (
    ("read_mb_s", "Leitura sequencial", "MB/s", 0),
    ("write_mb_s", "Gravação sequencial", "MB/s", 0),
    ("read_iops", "Leitura aleatória 4 KB", "IOPS", 0),
    ("write_iops", "Gravação aleatória 4 KB", "IOPS", 0),
    ("read_latency_ms", "Tempo médio de leitura", "ms", 2),
    ("write_latency_ms", "Tempo médio de gravação", "ms", 2),
    ("read_p99_ms", "Pior leitura (99%)", "ms", 2),
    ("write_p99_ms", "Pior gravação (99%)", "ms", 2),
    ("file_mb", "Tamanho do arquivo de teste", "MB", 0),
)


def default_folder() -> Path:
    return default_reports_root() / FOLDER_NAME


def base_name(report: DiskTestReport) -> str:
    try:
        stamp = datetime.fromisoformat(report.created_at).strftime("%Y-%m-%d_%H%M%S")
    except ValueError:
        stamp = datetime.now().strftime("%Y-%m-%d_%H%M%S")
    host = safe_filename(report.hostname or "maquina")
    return f"{host}_disco{report.drive.number}_{stamp}"


def save_json(report: DiskTestReport, folder: Path) -> Path:
    folder.mkdir(parents=True, exist_ok=True)
    path = folder / f"{base_name(report)}{SUFFIX}"
    path.write_text(json.dumps(report.to_dict(), ensure_ascii=False, indent=2), encoding="utf-8")
    return path


def load_json(path: Path) -> DiskTestReport:
    return DiskTestReport.from_dict(json.loads(path.read_text(encoding="utf-8")))


def expected_text(report: DiskTestReport, key: str) -> str:
    from extract.analysis.reference import DISK_EXPECTATIONS

    expected = DISK_EXPECTATIONS.get(report.drive.kind or "sata_ssd")
    if expected is None:
        return ""
    if report.over_usb:
        return "pelo USB: não avaliado" if key in ("read_mb_s", "write_mb_s", "read_iops") else ""
    minimum = {
        "read_mb_s": (expected.min_seq_read_mb_s, "MB/s"),
        "write_mb_s": (expected.min_seq_write_mb_s, "MB/s"),
        "read_iops": (expected.min_random_read_iops, "IOPS"),
    }.get(key)
    if minimum is None:
        return ""
    return f"mín. {fmt(minimum[0])} {minimum[1]}"


def identity_rows(report: DiskTestReport) -> list[tuple[str, str]]:
    drive = report.drive
    rows = [
        ("Modelo", drive.model or "?"),
        ("Tipo", drive.kind_label),
        ("Capacidade", f"{fmt(drive.size_gb)} GB"),
        ("Firmware", drive.firmware or "?"),
        ("Número de série", drive.serial_number or "?"),
        ("Disco do sistema", "Sim" if drive.is_system else "Não"),
    ]
    if drive.spindle_rpm:
        rows.insert(2, ("Rotação", f"{fmt(drive.spindle_rpm)} RPM"))
    if drive.partition_style:
        rows.append(("Tabela de partição", drive.partition_style))
    letters = ", ".join(f"{v.letter} {v.filesystem}".strip() for v in drive.volumes if v.letter)
    if letters:
        rows.append(("Unidades", letters))
    return rows


def export_pdf(report: DiskTestReport, path: Path) -> Path:
    from reportlab.lib import colors
    from reportlab.lib.pagesizes import A4
    from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
    from reportlab.lib.units import mm
    from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle

    margin = 18 * mm
    width = A4[0] - 2 * margin
    primary = colors.HexColor("#1F3A5F")
    zebra = colors.HexColor("#F5F7FA")
    grid = colors.HexColor("#D0D7E2")
    base = getSampleStyleSheet()
    body = ParagraphStyle("b", parent=base["BodyText"], fontSize=9.5, leading=13)
    cell = ParagraphStyle("c", parent=body, fontSize=8.5, leading=11)
    head = ParagraphStyle("hd", parent=cell, textColor=colors.white)
    h1 = ParagraphStyle("h1", parent=base["Title"], fontSize=20, textColor=primary)
    h2 = ParagraphStyle("h2", parent=base["Heading3"], textColor=primary, spaceBefore=8)

    def p(text: str, style=cell, bold: bool = False) -> Paragraph:
        text = escape(text)
        return Paragraph(f"<b>{text}</b>" if bold else text, style)

    def status_p(status: Status) -> Paragraph:
        color = STATUS_HEX[status]
        return Paragraph(f'<font color="{color}"><b>{escape(status.label)}</b></font>', cell)

    def colored_p(text: str, status: Status) -> Paragraph:
        if status is Status.OK:
            return p(text)
        return Paragraph(f'<font color="{STATUS_HEX[status]}"><b>{escape(text)}</b></font>', cell)

    def table(rows, fractions, header=True) -> Table:
        t = Table(rows, colWidths=[width * f for f in fractions], repeatRows=1 if header else 0)
        style = [
            ("LINEBELOW", (0, 0), (-1, -1), 0.4, grid),
            ("VALIGN", (0, 0), (-1, -1), "TOP"),
            ("ROWBACKGROUNDS", (0, 1 if header else 0), (-1, -1), [colors.white, zebra]),
        ]
        if header:
            style.append(("BACKGROUND", (0, 0), (-1, 0), primary))
        t.setStyle(TableStyle(style))
        return t

    story = [
        Paragraph("Teste de disco", h1),
        p(
            f"{report.hostname or 'Máquina'} · {report.drive.title} · "
            f"{_format_date(report.created_at)} · {DiskTestMode.LABELS.get(report.mode, '')}",
            body,
        ),
        Spacer(1, 6),
        Paragraph(
            f'<font color="{STATUS_HEX[report.overall_status]}"><b>'
            f"Nota {report.score if report.score is not None else '?'}/100 · "
            f"{escape(report.verdict)}</b></font>",
            body,
        ),
    ]
    resumo = summary.build(report)
    color = STATUS_HEX[resumo.status]
    story += [
        Paragraph("Resumo", h2),
        Paragraph(
            f'<font color="{color}" size="14"><b>{escape(resumo.situation)}</b></font>', body
        ),
        p(resumo.headline, body, bold=True),
        *[p(f"• {reason}", body) for reason in resumo.reasons],
        Spacer(1, 4),
        table(
            [[p(f.title, bold=True), p(f"{f.value}  {f.detail}")] for f in resumo.facts]
            + [[p("Velocidade", bold=True), p(resumo.speed)]],
            [0.3, 0.7],
            False,
        ),
    ]
    if resumo.cares:
        story.append(p("Cuidados (não são defeito do disco):", body, bold=True))
        story += [p(f"• {care}", body) for care in resumo.cares]
    story += [
        Paragraph("Identificação", h2),
        table([[p(k, bold=True), p(v)] for k, v in identity_rows(report)], [0.3, 0.7], False),
        Paragraph("Saúde", h2),
        table(
            [[p(h, head, True) for h in ("Item", "Valor", "Situação", "Observação")]]
            + [[p(r.label), p(r.value), status_p(r.status), p(r.note)] for r in report.readings],
            [0.34, 0.22, 0.12, 0.32],
        ),
    ]
    if report.smart:
        story += [
            Paragraph("Atributos SMART", h2),
            table(
                [[p(h, head, True) for h in ("ID", "Atributo", "Atual", "Pior", "Limite", "Bruto")]]
                + [
                    [
                        p(str(a.id)),
                        p(a.name),
                        p(str(a.current)),
                        p(str(a.worst)),
                        p("" if a.threshold is None else str(a.threshold)),
                        colored_p(a.raw_display, a.status),
                    ]
                    for a in report.smart
                ],
                [0.07, 0.43, 0.1, 0.1, 0.1, 0.2],
            ),
        ]
    if report.performance or report.performance_error:
        story.append(Paragraph(f"Desempenho (unidade {report.tested_volume or '?'})", h2))
        if report.performance_error:
            story.append(p(report.performance_error, body))
        rows = [[p(h, head, True) for h in ("Medida", "Resultado", "Esperado")]]
        for key, label, unit, decimals in PERFORMANCE_ROWS:
            metric = report.performance.get(key)
            if metric is not None:
                rows.append(
                    [p(label), p(f"{fmt(metric.value, decimals)} {unit}"),
                     p(expected_text(report, key))]
                )  # fmt: skip
        if len(rows) > 1:
            story.append(table(rows, [0.45, 0.3, 0.25]))
    if report.recommendations:
        story.append(Paragraph("Recomendações", h2))
        story += [p(f"• {tip}", body) for tip in report.recommendations]

    path.parent.mkdir(parents=True, exist_ok=True)
    doc = SimpleDocTemplate(
        str(path), pagesize=A4, leftMargin=margin, rightMargin=margin,
        topMargin=margin, bottomMargin=margin, title="Teste de disco",
    )  # fmt: skip
    doc.build(story)
    log.info("Disk test PDF saved to %s", path)
    return path


def save(report: DiskTestReport, folder: Path | None = None) -> tuple[Path, Path]:
    """Save JSON and PDF side by side; returns (json path, pdf path)."""
    folder = folder or default_folder()
    json_path = save_json(report, folder)
    pdf_path = export_pdf(report, folder / f"{base_name(report)}.pdf")
    return json_path, pdf_path


def _format_date(value: str) -> str:
    try:
        return datetime.fromisoformat(value).strftime("%d/%m/%Y %H:%M")
    except ValueError:
        return value
