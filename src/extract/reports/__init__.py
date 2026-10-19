"""Reports: one JSON file per machine, consolidated per client into Excel and PDF."""

from extract.reports.storage import load_folder, load_report, save_report

__all__ = ["load_folder", "load_report", "save_report"]
