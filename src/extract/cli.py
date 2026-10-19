"""Command-line interface: `extract-cli scan` and `extract-cli export`.

The scan runs in a worker thread so Ctrl+C in the main thread can set the `CancelToken`
and let the pipeline stop at its next checkpoint, instead of killing it mid-benchmark and
leaving a temporary file behind.
"""

from __future__ import annotations

import argparse
import logging
import sys
import threading
from collections.abc import Sequence
from pathlib import Path
from typing import TextIO

from extract import __version__
from extract.core.models import Category, MachineReport
from extract.core.pipeline import ScanOptions, run_scan
from extract.core.progress import Cancelled, CancelToken
from extract.reports import export_excel, export_pdf, load_folder, save_report
from extract.reports.paths import client_folder
from extract.reports.storage import safe_filename
from extract.reports.summary import sorted_findings

log = logging.getLogger(__name__)

EXIT_OK = 0
EXIT_ERROR = 1
EXIT_CANCELLED = 130

_BENCHMARK_CATEGORIES = {c.value: c for c in (Category.CPU, Category.MEMORY, Category.STORAGE)}


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="extract-cli",
        description="Diagnóstico de hardware, saúde e desempenho de computadores Windows.",
    )
    parser.add_argument("--version", action="version", version=f"Extract {__version__}")
    parser.add_argument("-v", "--verbose", action="store_true", help="mostra o log detalhado")
    commands = parser.add_subparsers(dest="command", required=True, metavar="COMANDO")

    scan = commands.add_parser("scan", help="analisa este computador")
    scan.add_argument("--client", default="", help="nome do cliente")
    scan.add_argument(
        "--output",
        type=Path,
        help="pasta dos relatórios (padrão: reports/<cliente> ou Relatorios/<cliente> no .exe)",
    )
    scan.add_argument("--quick", action="store_true", help="testes de desempenho rápidos")
    scan.add_argument("--no-health", action="store_true", help="pula as verificações de saúde")
    scan.add_argument("--no-benchmarks", action="store_true", help="pula os testes de desempenho")
    scan.add_argument(
        "--only",
        type=_categories,
        metavar="cpu,memory,storage",
        help="executa só os testes de desempenho dessas áreas",
    )
    scan.add_argument(
        "--json-only", action="store_true", help="salva só o JSON, sem gerar Excel e PDF"
    )

    export = commands.add_parser("export", help="gera Excel e PDF a partir de uma pasta")
    export.add_argument("folder", type=Path, metavar="PASTA", help="pasta com os JSON")
    export.add_argument("--excel", type=Path, metavar="ARQUIVO", help="caminho do .xlsx")
    export.add_argument("--pdf", type=Path, metavar="ARQUIVO", help="caminho do .pdf")
    return parser


def _categories(value: str) -> set[Category]:
    names = {part.strip().lower() for part in value.split(",") if part.strip()}
    unknown = names - _BENCHMARK_CATEGORIES.keys()
    if unknown or not names:
        valid = ", ".join(_BENCHMARK_CATEGORIES)
        raise argparse.ArgumentTypeError(
            f"área inválida: {', '.join(sorted(unknown))} (use {valid})"
        )
    return {_BENCHMARK_CATEGORIES[name] for name in names}


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    logging.basicConfig(
        level=logging.INFO if args.verbose else logging.WARNING,
        format="%(levelname)s %(name)s: %(message)s",
    )
    try:
        if args.command == "scan":
            return _scan(args)
        return _export(args.folder, args.excel, args.pdf)
    except KeyboardInterrupt:
        print("\nOperação cancelada.", file=sys.stderr)
        return EXIT_CANCELLED
    except Exception as exc:
        # Saving or exporting failed (file open in Excel, disk full, ...): report, don't trace.
        log.debug("Command failed", exc_info=True)
        print(f"Erro: {exc}", file=sys.stderr)
        return EXIT_ERROR


# --- scan --------------------------------------------------------------------------


def scan_options(args: argparse.Namespace) -> ScanOptions:
    options = ScanOptions(
        client=args.client.strip(), health=not args.no_health, quick_benchmarks=args.quick
    )
    if args.no_benchmarks:
        options.benchmarks = set()
    elif args.only:
        options.benchmarks = args.only
    return options


def _scan(args: argparse.Namespace) -> int:
    options = scan_options(args)
    output: Path = args.output or client_folder(options.client)
    progress = ProgressLine(sys.stderr)
    cancel = CancelToken()

    try:
        report = _run_in_thread(options, progress, cancel)
    except Cancelled:
        progress.finish()
        print("Análise cancelada.", file=sys.stderr)
        return EXIT_CANCELLED
    except Exception as exc:
        progress.finish()
        log.debug("Scan failed", exc_info=True)
        print(f"Erro durante a análise: {exc}", file=sys.stderr)
        return EXIT_ERROR
    progress.finish()

    path = save_report(report, output)
    print(f"Relatório salvo em {path}")
    print_findings(report)
    if args.json_only:
        return EXIT_OK
    return _export(output, None, None)


def _run_in_thread(
    options: ScanOptions, progress: ProgressLine, cancel: CancelToken
) -> MachineReport:
    reports: list[MachineReport] = []
    errors: list[BaseException] = []

    def work() -> None:
        try:
            reports.append(run_scan(options, progress=progress, cancel=cancel))
        except BaseException as exc:
            errors.append(exc)

    worker = threading.Thread(target=work, name="extract-scan", daemon=True)
    worker.start()
    try:
        # join() with a timeout keeps the main thread responsive to Ctrl+C on Windows.
        while worker.is_alive():
            worker.join(0.2)
    except KeyboardInterrupt:
        progress.finish()
        print("Cancelando, aguarde o passo atual terminar...", file=sys.stderr)
        cancel.cancel()
        worker.join()
        raise Cancelled() from None

    if errors:
        raise errors[0]
    return reports[0]


class ProgressLine:
    """One progress line rewritten in place on a terminal, plain lines when redirected."""

    def __init__(self, stream: TextIO) -> None:
        self.stream = stream
        self.interactive = stream.isatty()
        self._last = ""
        self._width = 0

    def __call__(self, fraction: float, message: str) -> None:
        if message == self._last and not self.interactive:
            return
        self._last = message
        line = f"[{fraction:4.0%}] {message}"
        if self.interactive:
            self.stream.write("\r" + line.ljust(self._width))
            self._width = len(line)
        else:
            self.stream.write(line + "\n")
        self.stream.flush()

    def finish(self) -> None:
        if self.interactive and self._width:
            self.stream.write("\n")
            self.stream.flush()
            self._width = 0


def print_findings(report: MachineReport, stream: TextIO | None = None) -> None:
    stream = stream or sys.stdout
    findings = sorted_findings(report)
    if not findings:
        print("Nenhum problema encontrado.", file=stream)
        return
    print(f"\n{len(findings)} achado(s) em {report.hostname}:", file=stream)
    for finding in findings:
        print(f"  [{finding.severity.label}] {finding.title}", file=stream)
        if finding.recommendation:
            print(f"      -> {finding.recommendation}", file=stream)


# --- export ------------------------------------------------------------------------


def _export(folder: Path, excel: Path | None, pdf: Path | None) -> int:
    if not folder.is_dir():
        print(f"Erro: pasta não encontrada: {folder}", file=sys.stderr)
        return EXIT_ERROR
    reports = load_folder(folder)
    if not reports:
        print(f"Erro: nenhum relatório JSON em {folder}", file=sys.stderr)
        return EXIT_ERROR

    if excel is None and pdf is None:
        stem = f"relatorio-{safe_filename(folder.resolve().name)}"
        excel, pdf = folder / f"{stem}.xlsx", folder / f"{stem}.pdf"
    if excel is not None:
        print(f"Excel salvo em {export_excel(reports, excel)}")
    if pdf is not None:
        print(f"PDF salvo em {export_pdf(reports, pdf)}")
    return EXIT_OK


if __name__ == "__main__":
    raise SystemExit(main())
