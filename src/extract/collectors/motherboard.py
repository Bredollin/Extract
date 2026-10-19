"""Motherboard manufacturer and model."""

from __future__ import annotations

from extract.collectors._parse import clean, first
from extract.core.models import MotherboardInfo
from extract.core.powershell import PowerShellRunner, safe_query

SCRIPT = "Get-CimInstance Win32_BaseBoard | Select-Object Manufacturer, Product, SerialNumber"


def collect_motherboard(ps: PowerShellRunner) -> MotherboardInfo:
    row = first(safe_query(ps, SCRIPT))
    return MotherboardInfo(
        manufacturer=clean(row.get("Manufacturer")),
        product=clean(row.get("Product")),
        serial_number=clean(row.get("SerialNumber")),
    )
