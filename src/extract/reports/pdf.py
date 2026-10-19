"""PDF export: the client-facing report the technician presents.

A cover page summarizes the visit (client, date, machines, findings overview); then each
machine gets its own section with key specs, findings with recommendations, health checks
and benchmark results. Built with reportlab's platypus so text wraps and tables split
across pages on their own.
"""

from __future__ import annotations

import logging
from collections import Counter
from collections.abc import Sequence
from pathlib import Path
from xml.sax.saxutils import escape

from reportlab.lib import colors
from reportlab.lib.enums import TA_CENTER
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import mm
from reportlab.pdfgen.canvas import Canvas
from reportlab.platypus import (
    Flowable,
    KeepTogether,
    PageBreak,
    Paragraph,
    SimpleDocTemplate,
    Spacer,
    Table,
    TableStyle,
)

from extract import __version__
from extract.core.models import Finding, MachineReport, Severity
from extract.reports.summary import (
    SEVERITY_COLORS,
    STATUS_COLORS,
    client_label,
    format_date,
    format_metric,
    inventory_rows,
    os_label,
    severity_counts,
    sorted_findings,
    top_finding,
)

log = logging.getLogger(__name__)

_MARGIN = 18 * mm
_WIDTH = A4[0] - 2 * _MARGIN
_PRIMARY = colors.HexColor("#1F3A5F")
_MUTED = colors.HexColor("#5B6573")
_GRID = colors.HexColor("#D0D7E2")
_ZEBRA = colors.HexColor("#F5F7FA")
# Hardware rows that matter to the client; per-module and network details stay in Excel.
_KEY_COMPONENTS = ("Sistema", "Computador", "Processador", "Memória", "Disco", "Unidade", "Vídeo")


def _styles() -> dict[str, ParagraphStyle]:
    base = getSampleStyleSheet()
    body = ParagraphStyle("body", parent=base["BodyText"], fontSize=9.5, leading=13)
    return {
        "title": ParagraphStyle(
            "title", parent=base["Title"], fontSize=24, leading=30, textColor=_PRIMARY
        ),
        "subtitle": ParagraphStyle(
            "subtitle", parent=body, fontSize=13, leading=18, alignment=TA_CENTER
        ),
        "h2": ParagraphStyle(
            "h2", parent=base["Heading2"], fontSize=16, textColor=_PRIMARY, spaceAfter=2
        ),
        "h3": ParagraphStyle(
            "h3",
            parent=base["Heading3"],
            fontName="Helvetica-Bold",
            fontSize=11.5,
            textColor=_PRIMARY,
            spaceBefore=10,
        ),
        "body": body,
        "muted": ParagraphStyle("muted", parent=body, textColor=_MUTED),
        "cell": ParagraphStyle("cell", parent=body, fontSize=8.5, leading=11),
        "head": ParagraphStyle(
            "head", parent=body, fontSize=8.5, leading=11, textColor=colors.white
        ),
        "badge": ParagraphStyle("badge", parent=body, fontSize=8, leading=10, alignment=TA_CENTER),
    }


def export_pdf(reports: Sequence[MachineReport], path: Path) -> Path:
    """Write the client report to `path` and return it."""
    styles = _styles()
    client = client_label(reports)
    story: list[Flowable] = _cover(reports, client, styles)
    for report in reports:
        story.append(PageBreak())
        story.extend(_machine_section(report, styles))

    path.parent.mkdir(parents=True, exist_ok=True)
    doc = SimpleDocTemplate(
        str(path),
        pagesize=A4,
        leftMargin=_MARGIN,
        rightMargin=_MARGIN,
        topMargin=_MARGIN,
        bottomMargin=_MARGIN,
        title=f"Relatório de diagnóstico - {client}",
        author=f"Extract {__version__}",
    )

    def footer(canvas: Canvas, _doc: SimpleDocTemplate) -> None:
        canvas.saveState()
        canvas.setFont("Helvetica", 7.5)
        canvas.setFillColor(_MUTED)
        canvas.drawString(_MARGIN, 10 * mm, f"Extract {__version__} · {client}")
        canvas.drawRightString(A4[0] - _MARGIN, 10 * mm, f"Página {canvas.getPageNumber()}")
        canvas.restoreState()

    doc.build(story, onFirstPage=footer, onLaterPages=footer)
    log.info("PDF report saved to %s", path)
    return path


# --- cover ---------------------------------------------------------------------------


def _cover(
    reports: Sequence[MachineReport], client: str, styles: dict[str, ParagraphStyle]
) -> list[Flowable]:
    dates = sorted(r.created_at for r in reports)
    totals: Counter[Severity] = Counter()
    for report in reports:
        totals.update(severity_counts(report))

    story: list[Flowable] = [
        Spacer(1, 30 * mm),
        Paragraph("Relatório de diagnóstico", styles["title"]),
        Paragraph(escape(client), styles["subtitle"]),
        Spacer(1, 12 * mm),
        _key_value_table(
            [
                ("Cliente", client),
                ("Data da análise", format_date(dates[-1], with_time=False) if dates else ""),
                ("Computadores analisados", str(len(reports))),
                ("Problemas críticos", str(totals[Severity.CRITICAL])),
                ("Pontos de atenção", str(totals[Severity.WARNING])),
            ],
            styles,
        ),
        Spacer(1, 8 * mm),
        Paragraph(
            "Este relatório reúne o inventário de hardware, a verificação de saúde do Windows "
            "e os testes de desempenho de cada computador. Os achados estão ordenados do mais "
            "grave para o menos grave e trazem a recomendação do técnico.",
            styles["muted"],
        ),
    ]
    if reports:
        story += [Paragraph("Visão geral", styles["h3"]), _overview_table(reports, styles)]
    return story


def _overview_table(reports: Sequence[MachineReport], styles: dict[str, ParagraphStyle]) -> Table:
    rows: list[list[Flowable | str]] = [
        _header_row(["Computador", "Sistema", "Críticos", "Atenção", "Principal achado"], styles)
    ]
    highlights: list[tuple[int, Severity]] = []
    for index, report in enumerate(reports, start=1):
        counts = severity_counts(report)
        top = top_finding(report)
        if top:
            highlights.append((index, top.severity))
        rows.append(
            [
                _cell(report.hostname, styles),
                _cell(os_label(report.inventory.system), styles),
                _cell(str(counts[Severity.CRITICAL]), styles),
                _cell(str(counts[Severity.WARNING]), styles),
                _cell(top.title if top else "Nenhum problema encontrado", styles),
            ]
        )
    table = _table(rows, [0.18, 0.28, 0.1, 0.1, 0.34])
    for row, severity in highlights:
        _, background = SEVERITY_COLORS[severity]
        table.setStyle([("BACKGROUND", (4, row), (4, row), colors.HexColor(f"#{background}"))])
    return table


# --- per machine ---------------------------------------------------------------------


def _machine_section(report: MachineReport, styles: dict[str, ParagraphStyle]) -> list[Flowable]:
    subtitle = f"Análise de {format_date(report.created_at)}"
    if report.client:
        subtitle += f" · {report.client}"
    story: list[Flowable] = [
        Paragraph(escape(report.hostname), styles["h2"]),
        Paragraph(escape(subtitle), styles["muted"]),
        Paragraph("Configuração", styles["h3"]),
        _specs(report, styles),
        Paragraph("Achados e recomendações", styles["h3"]),
    ]
    findings = sorted_findings(report)
    if findings:
        story += [_finding_block(f, styles) for f in findings]
    else:
        story.append(Paragraph("Nenhum problema relevante encontrado.", styles["body"]))

    if report.health:
        story += [Paragraph("Verificações de saúde", styles["h3"]), _health_table(report, styles)]
    if report.benchmarks:
        story += [Paragraph("Testes de desempenho", styles["h3"]), _bench_table(report, styles)]
    if report.notes:
        story += [
            Paragraph("Observações do técnico", styles["h3"]),
            Paragraph(escape(report.notes), styles["body"]),
        ]
    return story


def _specs(report: MachineReport, styles: dict[str, ParagraphStyle]) -> Flowable:
    rows = [row for row in inventory_rows(report) if row[0].startswith(_KEY_COMPONENTS)]
    if not rows:
        return Paragraph("Inventário de hardware indisponível.", styles["muted"])
    pairs = [
        (component, " · ".join(p for p in (name, details) if p))
        for component, name, details in rows
    ]
    return _key_value_table(pairs, styles)


def _finding_block(finding: Finding, styles: dict[str, ParagraphStyle]) -> Flowable:
    text_color, background = SEVERITY_COLORS[finding.severity]
    badge = Paragraph(
        f'<font color="#{text_color}"><b>{escape(finding.severity.label.upper())}</b></font>',
        styles["badge"],
    )
    parts = [f"<b>{escape(finding.title)}</b>"]
    if finding.detail:
        parts.append(escape(finding.detail))
    if finding.recommendation:
        parts.append(f"<b>Recomendação:</b> {escape(finding.recommendation)}")
    body = Paragraph("<br/>".join(parts), styles["body"])
    table = Table([[badge, body]], colWidths=[24 * mm, _WIDTH - 24 * mm])
    table.setStyle(
        TableStyle(
            [
                ("BACKGROUND", (0, 0), (0, 0), colors.HexColor(f"#{background}")),
                ("VALIGN", (0, 0), (-1, -1), "TOP"),
                ("BOX", (0, 0), (-1, -1), 0.5, _GRID),
                ("TOPPADDING", (0, 0), (-1, -1), 5),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 6),
            ]
        )
    )
    return KeepTogether([table, Spacer(1, 4)])


def _health_table(report: MachineReport, styles: dict[str, ParagraphStyle]) -> Table:
    rows: list[list[Flowable | str]] = [_header_row(["Verificação", "Situação", "Resumo"], styles)]
    for check in report.health:
        rows.append(
            [
                _cell(check.title, styles),
                _cell(check.status.label, styles, bold=True),
                _cell(check.summary, styles),
            ]
        )
    table = _table(rows, [0.3, 0.14, 0.56])
    for row, check in enumerate(report.health, start=1):
        _, background = STATUS_COLORS[check.status]
        table.setStyle([("BACKGROUND", (1, row), (1, row), colors.HexColor(f"#{background}"))])
    return table


def _bench_table(report: MachineReport, styles: dict[str, ParagraphStyle]) -> Table:
    rows: list[list[Flowable | str]] = [_header_row(["Teste", "Medida", "Resultado"], styles)]
    for bench in report.benchmarks:
        if bench.error or not bench.metrics:
            reason = bench.error or "sem resultados"
            rows.append(
                [
                    _cell(bench.title, styles),
                    _cell("Não concluído", styles),
                    _cell(reason, styles),
                ]
            )
        for metric in bench.metrics.values():
            rows.append(
                [
                    _cell(bench.title, styles),
                    _cell(metric.label, styles),
                    _cell(format_metric(metric), styles),
                ]
            )
    return _table(rows, [0.32, 0.4, 0.28])


# --- building blocks -------------------------------------------------------------------


def _cell(text: str, styles: dict[str, ParagraphStyle], bold: bool = False) -> Paragraph:
    content = escape(text)
    return Paragraph(f"<b>{content}</b>" if bold else content, styles["cell"])


def _header_row(headers: list[str], styles: dict[str, ParagraphStyle]) -> list[Flowable | str]:
    return [Paragraph(f"<b>{escape(h)}</b>", styles["head"]) for h in headers]


def _table(rows: list[list[Flowable | str]], fractions: list[float]) -> Table:
    table = Table(rows, colWidths=[_WIDTH * f for f in fractions], repeatRows=1)
    table.setStyle(
        TableStyle(
            [
                ("BACKGROUND", (0, 0), (-1, 0), _PRIMARY),
                ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, _ZEBRA]),
                ("LINEBELOW", (0, 0), (-1, -1), 0.4, _GRID),
                ("VALIGN", (0, 0), (-1, -1), "TOP"),
                ("TOPPADDING", (0, 0), (-1, -1), 4),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
            ]
        )
    )
    return table


def _key_value_table(pairs: list[tuple[str, str]], styles: dict[str, ParagraphStyle]) -> Table:
    rows = [[_cell(key, styles, bold=True), _cell(value, styles)] for key, value in pairs]
    table = Table(rows, colWidths=[_WIDTH * 0.3, _WIDTH * 0.7])
    table.setStyle(
        TableStyle(
            [
                ("ROWBACKGROUNDS", (0, 0), (-1, -1), [colors.white, _ZEBRA]),
                ("LINEBELOW", (0, 0), (-1, -1), 0.4, _GRID),
                ("VALIGN", (0, 0), (-1, -1), "TOP"),
            ]
        )
    )
    return table
