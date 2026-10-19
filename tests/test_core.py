from __future__ import annotations

import pytest

from extract.core.models import (
    BenchmarkResult,
    Category,
    DiskInfo,
    Finding,
    HealthCheck,
    MachineReport,
    Metric,
    Severity,
    Status,
    VolumeInfo,
)
from extract.core.powershell import FakePowerShell, PowerShellError, parse_json_output, safe_query
from extract.core.progress import Cancelled, CancelToken, sub_progress
from extract.reports.storage import load_folder, safe_filename, save_report


def _sample_report(hostname: str = "PC-01", created_at: str = "2026-10-19T10:00:00-03:00"):
    report = MachineReport(client="Cliente A", created_at=created_at, tool_version="2.0.0")
    report.inventory.system.hostname = hostname
    report.inventory.disks.append(DiskInfo(model="WD Blue", size_gb=931.5, media_type="HDD"))
    report.health.append(
        HealthCheck("disk.free", Category.STORAGE, "Espaço livre", Status.WARNING, "8% livre")
    )
    report.benchmarks.append(
        BenchmarkResult(
            "cpu.single", Category.CPU, "Processador", {"score": Metric(812.0, "pts", "Nota")}
        )
    )
    report.findings.append(
        Finding("disk.hdd", Category.STORAGE, Severity.CRITICAL, "HD", "lento", "Trocar por SSD")
    )
    return report


def test_report_roundtrip_preserves_types():
    original = _sample_report()
    restored = MachineReport.from_dict(original.to_dict())
    assert restored == original
    assert restored.health[0].status is Status.WARNING
    assert isinstance(restored.benchmarks[0].metrics["score"], Metric)


def test_from_dict_ignores_unknown_fields():
    data = _sample_report().to_dict()
    data["campo_futuro"] = 123
    assert MachineReport.from_dict(data).client == "Cliente A"


def test_volume_free_percent():
    assert VolumeInfo(size_gb=200, free_gb=20).free_percent == 10.0
    assert VolumeInfo().free_percent == 0.0


@pytest.mark.parametrize(
    ("text", "expected"),
    [("", []), ('{"a": 1}', [{"a": 1}]), ('[{"a": 1}, {"b": 2}]', [{"a": 1}, {"b": 2}])],
)
def test_parse_json_output(text, expected):
    assert parse_json_output(text) == expected


def test_parse_json_output_rejects_garbage():
    with pytest.raises(PowerShellError):
        parse_json_output("not json")


def test_safe_query_swallows_errors():
    ps = FakePowerShell({"Win32_X": PowerShellError("falhou")})
    assert safe_query(ps, "Get-CimInstance Win32_X") == []


def test_sub_progress_maps_range():
    seen = []
    report = sub_progress(lambda f, m: seen.append(round(f, 2)), 0.5, 1.0)
    report(0.0, "")
    report(0.5, "")
    report(2.0, "")
    assert seen == [0.5, 0.75, 1.0]


def test_cancel_token():
    token = CancelToken()
    token.raise_if_cancelled()
    token.cancel()
    with pytest.raises(Cancelled):
        token.raise_if_cancelled()


def test_safe_filename():
    assert safe_filename("PC do João/01") == "PC-do-Jo-o-01"
    assert safe_filename("...") == "unnamed"


def test_load_folder_keeps_latest_per_machine(tmp_path):
    save_report(_sample_report("PC-01", "2026-10-18T10:00:00-03:00"), tmp_path)
    save_report(_sample_report("PC-01", "2026-10-19T10:00:00-03:00"), tmp_path)
    save_report(_sample_report("PC-02"), tmp_path)
    (tmp_path / "quebrado.json").write_text("{", encoding="utf-8")

    reports = load_folder(tmp_path)
    assert [r.hostname for r in reports] == ["PC-01", "PC-02"]
    assert reports[0].created_at.startswith("2026-10-19")
    assert len(load_folder(tmp_path, latest_only=False)) == 3
