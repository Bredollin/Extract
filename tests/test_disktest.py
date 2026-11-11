"""Disk test page logic: SMART decoding, drive parsing, evaluation, runner and report files."""

from __future__ import annotations

import json

import pytest

from extract.core.models import Metric, Status
from extract.core.powershell import FakePowerShell
from extract.core.progress import Cancelled, CancelToken
from extract.disktest import (
    DiskTestMode,
    evaluate,
    list_drives,
    probe,
    report,
    run_disk_test,
    runner,
    smart,
)
from extract.disktest.models import DiskTestReport, DriveEntry, VolumeEntry

GB = 1024**3

DRIVE_ROWS = [
    {
        "Number": 1,
        "Model": "ST1000DM010-2EP102",
        "Serial": "Z9A0TEST",
        "Firmware": "CC43",
        "BusType": "SATA",
        "MediaType": "HDD",
        "SpindleSpeed": 7200,
        "Size": 1000 * GB,
        "PartitionStyle": "GPT",
        "HealthStatus": "Healthy",
        "OperationalStatus": "OK",
        "IsSystem": False,
        "Volumes": {"Letter": "D:", "Label": "Dados", "FileSystem": "NTFS",
                    "Size": 900 * GB, "Free": 90 * GB, "Offset": 1048576},
    },
    {
        "Number": 0,
        "Model": "Samsung SSD 970 EVO Plus 500GB",
        "Serial": "S4EVTEST",
        "Firmware": "2B2QEXM7",
        "BusType": 17,
        "MediaType": 4,
        "SpindleSpeed": 0,
        "Size": 500 * GB,
        "PartitionStyle": "GPT",
        "HealthStatus": 0,
        "OperationalStatus": "OK",
        "IsSystem": True,
        "Volumes": [
            {"Letter": "C:", "Label": "", "FileSystem": "NTFS",
             "Size": 465 * GB, "Free": 200 * GB, "Offset": 16777216},
        ],
    },
]  # fmt: skip

HDD_SMART = smart.encode_attributes(
    [
        (1, 117, 99, 123456),
        (5, 100, 100, 8),
        (9, 82, 82, 41000),
        (12, 98, 98, 2100),
        (194, 40, 52, 0x0000_0014_0000_0033),  # 51 °C (low byte)
        (197, 100, 100, 2),
        (198, 100, 100, 0),
        (199, 200, 200, 120),
    ]
)
HDD_THRESHOLDS = smart.encode_thresholds([(1, 6), (5, 10), (9, 0), (194, 0), (197, 0)])


def hdd_ps(**extra) -> FakePowerShell:
    responses = {
        "IsInRole": [{"IsAdmin": True, "Host": "PC-TESTE"}],
        "Get-StorageReliabilityCounter": [
            {"Temperature": 51, "TemperatureMax": 58, "Wear": 0, "PowerOnHours": 41000,
             "StartStopCycleCount": 2100, "ReadErrorsUncorrected": 3,
             "WriteErrorsUncorrected": 0, "ReadLatencyMax": 2500, "WriteLatencyMax": 300}
        ],
        "FailurePredictData": [
            {"InstanceName": "SCSI\\Disk&Ven_&Prod_ST1000DM010-2EP102\\4&1&0_0",
             "Data": HDD_SMART, "Thresholds": HDD_THRESHOLDS, "PredictFailure": False},
            {"InstanceName": "SCSI\\Disk&Ven_&Prod_Other_Drive\\4&1&0_1",
             "Data": [], "Thresholds": [], "PredictFailure": True},
        ],
        "DisableDeleteNotify": [{"Output": "NTFS DisableDeleteNotify = 0  (Allowed)"}],
    }  # fmt: skip
    responses.update(extra)
    return FakePowerShell(responses)


def fake_bench(results_metrics):
    from extract.core.models import BenchmarkResult, Category

    calls = []

    def bench(progress, cancel, sizes, folder, write_through=True):
        calls.append((sizes, folder, write_through))
        progress(1.0, "done")
        return [
            BenchmarkResult("storage.sequential", Category.STORAGE, "seq", {
                k: v for k, v in results_metrics.items() if k in ("read_mb_s", "write_mb_s")
            }),
            BenchmarkResult("storage.random", Category.STORAGE, "rnd", {
                k: v for k, v in results_metrics.items() if k not in ("read_mb_s", "write_mb_s")
            }),
        ]  # fmt: skip

    bench.calls = calls
    return bench


# --- SMART ---------------------------------------------------------------------------


def test_smart_attributes_are_decoded_and_judged():
    attributes = smart.parse_attributes(HDD_SMART, smart.parse_thresholds(HDD_THRESHOLDS))
    by_id = {a.id: a for a in attributes}
    assert set(by_id) == {1, 5, 9, 12, 194, 197, 198, 199}
    assert by_id[5].raw == 8 and by_id[5].threshold == 10
    assert by_id[5].status is Status.WARNING
    assert by_id[197].status is Status.WARNING
    assert by_id[198].status is Status.OK
    assert by_id[199].status is Status.WARNING and "cabo" in by_id[199].note
    assert by_id[194].raw_display == "51 °C"
    assert by_id[9].raw_display == "41000 h"
    assert by_id[1].status is Status.OK  # high raw read-error rate is normal on Seagate


def test_smart_value_below_threshold_is_critical():
    data = smart.encode_attributes([(5, 5, 5, 3000)])
    (attribute,) = smart.parse_attributes(data, {5: 10})
    assert attribute.status is Status.CRITICAL
    assert "falha prevista" in attribute.note


@pytest.mark.parametrize("data", [None, [], "garbage", [1, 2, 3]])
def test_smart_parser_tolerates_bad_input(data):
    assert smart.parse_attributes(data) == []


# --- probe ---------------------------------------------------------------------------


def test_list_drives_parses_numbers_and_names_and_puts_system_first():
    drives = list_drives(FakePowerShell({"Get-PhysicalDisk": DRIVE_ROWS}))
    system, data = drives
    assert system.is_system and system.number == 0
    assert system.bus_type == "NVMe" and system.media_type == "SSD"
    assert system.health_status == "Healthy" and system.kind == "nvme"
    assert system.volumes[0].letter == "C:" and system.volumes[0].aligned
    assert data.kind == "hdd" and data.spindle_rpm == 7200
    assert data.volumes[0].free_gb == 90.0
    assert data.title == "Disco 1: ST1000DM010-2EP102 (D:)"


def test_raw_smart_matches_drive_by_model():
    drive = probe.parse_drive(DRIVE_ROWS[0])
    attributes, predicted = probe.raw_smart(hdd_ps(), drive, drive_count=2)
    assert {a.id for a in attributes} >= {5, 197}
    assert predicted is False


def test_raw_smart_without_match_returns_nothing():
    drive = probe.parse_drive(DRIVE_ROWS[1])  # Samsung NVMe: no ATA SMART instance
    assert probe.raw_smart(hdd_ps(), drive, drive_count=2) == ([], None)


@pytest.mark.parametrize(
    ("output", "expected"),
    [
        ("NTFS DisableDeleteNotify = 0  (Allowed)\nReFS DisableDeleteNotify = 0", True),
        ("NTFS DisableDeleteNotify = 1  (Desabilitado)", False),
        ("DisableDeleteNotify = 0", True),
        ("Acesso negado.", None),
    ],
)
def test_trim_state(output, expected):
    ps = FakePowerShell({"DisableDeleteNotify": [{"Output": output}]})
    assert probe.trim_enabled(ps) is expected


def test_misaligned_partition():
    assert VolumeEntry(partition_offset=32256).aligned is False
    assert VolumeEntry(partition_offset=None).aligned is None


# --- evaluation --------------------------------------------------------------------------


def test_worn_hdd_gets_warnings_score_and_backup_advice():
    drive = probe.parse_drive(DRIVE_ROWS[0])
    result = run_disk_test(hdd_ps(), drive, DiskTestMode.HEALTH, drive_count=2)
    by_key = {r.key: r for r in result.readings}
    assert by_key["temperature"].status is Status.WARNING  # HDD: 50 °C warning, 60 critical
    assert by_key["power_on_hours"].status is Status.WARNING
    assert by_key["bad_sectors"].value == "10"
    assert by_key["bad_sectors"].status is Status.WARNING
    assert by_key["crc"].status is Status.WARNING
    assert by_key["uncorrected"].status is Status.WARNING
    assert by_key["max_latency"].status is Status.WARNING
    assert "trim" not in by_key  # HDDs have no TRIM
    assert result.health_status is Status.WARNING
    assert result.score is not None and result.score < 50
    assert result.verdict.startswith("Disco com vários alertas")
    assert any("backup" in tip for tip in result.recommendations)
    assert any("cabo SATA" in tip for tip in result.recommendations)
    assert result.performance == {} and result.hostname == "PC-TESTE"


def test_healthy_nvme_with_good_speed_scores_high(tmp_path):
    drive = probe.parse_drive(DRIVE_ROWS[1])
    ps = FakePowerShell(
        {
            "IsInRole": [{"IsAdmin": True, "Host": "PC-TESTE"}],
            "Get-StorageReliabilityCounter": [
                {"Temperature": 38, "Wear": 2, "PowerOnHours": 900, "ReadErrorsUncorrected": 0}
            ],
            "DisableDeleteNotify": [{"Output": "NTFS DisableDeleteNotify = 0"}],
        }
    )
    bench = fake_bench(
        {
            "read_mb_s": Metric(3100, "MB/s", ""),
            "write_mb_s": Metric(2500, "MB/s", ""),
            "read_iops": Metric(14000, "IOPS", ""),
            "write_iops": Metric(30000, "IOPS", ""),
            "read_p99_ms": Metric(0.2, "ms", ""),
        }
    )
    result = run_disk_test(ps, drive, DiskTestMode.QUICK, benchmark=bench)
    assert bench.calls[0][0].file_mb == 128
    assert result.tested_volume == "C:"
    assert result.health_status is Status.OK and result.performance_status is Status.OK
    assert result.score is not None and result.score >= 95
    assert result.verdict == "Disco saudável e com desempenho dentro do esperado."
    assert "uncached" not in result.performance
    assert {r.key for r in result.readings} >= {"trim", "wear", "alignment", "free_C:"}


def test_slow_ssd_is_flagged_with_hardware_tips():
    drive = probe.parse_drive(DRIVE_ROWS[1])
    drive.bus_type, drive.media_type = "SATA", "SSD"
    bench = fake_bench(
        {"read_mb_s": Metric(120, "MB/s", ""), "write_mb_s": Metric(100, "MB/s", ""),
         "read_iops": Metric(2500, "IOPS", "")}
    )  # fmt: skip
    ps = FakePowerShell({"DisableDeleteNotify": [{"Output": "NTFS DisableDeleteNotify = 1"}]})
    result = run_disk_test(ps, drive, DiskTestMode.FULL, benchmark=bench)
    assert result.performance_status is Status.CRITICAL
    assert any("AHCI" in tip for tip in result.recommendations)
    assert any("fsutil behavior set DisableDeleteNotify 0" in tip for tip in result.recommendations)
    # Not admin and no counters at all: the page says how to get them.
    assert any(r.key == "admin" for r in result.readings)


def test_drive_without_letter_cannot_run_speed_test():
    drive = DriveEntry(number=3, model="Disco vazio", media_type="HDD")
    bench = fake_bench({})
    result = run_disk_test(FakePowerShell({}), drive, DiskTestMode.QUICK, benchmark=bench)
    assert bench.calls == []
    assert "letra" in result.performance_error


def test_cancel_stops_before_benchmark():
    token = CancelToken()
    token.cancel()
    with pytest.raises(Cancelled):
        run_disk_test(FakePowerShell({}), probe.parse_drive(DRIVE_ROWS[0]), cancel=token)


def test_bench_folder_uses_temp_on_system_drive(monkeypatch):
    monkeypatch.setenv("SYSTEMDRIVE", "C:")
    assert runner.bench_folder("C:") == runner.tempfile.gettempdir()
    assert runner.bench_folder("e:") == "E:\\"


def test_failure_prediction_is_critical():
    drive = probe.parse_drive(DRIVE_ROWS[0])
    drive.model = "Other Drive"
    result = run_disk_test(hdd_ps(), drive, DiskTestMode.HEALTH, drive_count=2)
    assert result.health_status is Status.CRITICAL
    assert result.score is not None and result.score <= 40
    assert result.verdict.startswith("Disco com sinais de falha")


def test_unknown_everything_is_unknown():
    result = evaluate.finish(DiskTestReport())
    assert result.overall_status is Status.UNKNOWN
    assert "Não foi possível" in result.verdict


# --- report files ------------------------------------------------------------------------


def test_report_round_trips_and_exports_pdf(tmp_path):
    drive = probe.parse_drive(DRIVE_ROWS[0])
    result = run_disk_test(hdd_ps(), drive, DiskTestMode.HEALTH, drive_count=2)
    json_path, pdf_path = report.save(result, tmp_path)
    assert json_path.name.startswith("PC-TESTE_disco1_") and json_path.name.endswith(".disco.json")
    assert pdf_path.read_bytes().startswith(b"%PDF")
    loaded = report.load_json(json_path)
    assert loaded.drive.model == drive.model
    assert loaded.smart[0].name == result.smart[0].name
    assert loaded.health_status is result.health_status
    assert json.loads(json_path.read_text(encoding="utf-8"))["mode"] == "health"


# --- CLI ---------------------------------------------------------------------------------


def _cli_ps() -> FakePowerShell:
    ps = hdd_ps()
    ps.responses = {"Get-PhysicalDisk | ForEach-Object": DRIVE_ROWS, **ps.responses}
    return ps


def test_cli_lists_drives(capsys):
    from extract import cli

    args = cli.build_parser().parse_args(["disk", "--list"])
    assert cli._disk(args, _cli_ps()) == cli.EXIT_OK
    out = capsys.readouterr().out
    assert "Disco 0: Samsung SSD 970 EVO Plus 500GB (C:) - SSD NVMe, 500 GB [sistema]" in out
    assert "Disco 1: ST1000DM010-2EP102 (D:)" in out


def test_cli_health_test_saves_json_and_pdf(capsys, tmp_path):
    from extract import cli

    args = cli.build_parser().parse_args(
        ["disk", "--disk", "1", "--mode", "health", "--output", str(tmp_path)]
    )
    assert cli._disk(args, _cli_ps()) == cli.EXIT_OK
    out = capsys.readouterr().out
    assert "nota" in out and "[Atenção] Setores defeituosos" in out
    assert len(list(tmp_path.glob("*.disco.json"))) == 1
    assert len(list(tmp_path.glob("*.pdf"))) == 1


def test_cli_unknown_disk(capsys):
    from extract import cli

    args = cli.build_parser().parse_args(["disk", "--disk", "7"])
    assert cli._disk(args, _cli_ps()) == cli.EXIT_ERROR
    assert "--list" in capsys.readouterr().err


def test_null_reliability_counters_count_as_missing():
    ps = FakePowerShell({"Get-StorageReliabilityCounter": [{"Temperature": None, "Wear": None}]})
    assert probe.reliability(ps, 0) == {}


@pytest.mark.windows
def test_disk_test_on_real_windows(tmp_path):
    from extract.core.powershell import PowerShell

    ps = PowerShell()
    drives = list_drives(ps)
    assert drives and drives[0].is_system
    assert any(v.letter for v in drives[0].volumes)
    result = run_disk_test(ps, drives[0], DiskTestMode.QUICK, drive_count=len(drives))
    assert result.readings and result.readings[0].key == "windows"
    assert result.performance.get("read_mb_s") and result.performance["read_mb_s"].value > 0
    assert result.score is not None
    json_path, pdf_path = report.save(result, tmp_path)
    assert report.load_json(json_path).drive.number == drives[0].number
    assert pdf_path.stat().st_size > 0


def test_usb_drive_is_tested_without_write_through():
    drive = probe.parse_drive(DRIVE_ROWS[0])
    drive.bus_type = "USB"
    bench = fake_bench({"read_mb_s": Metric(300, "MB/s", "")})
    run_disk_test(FakePowerShell({}), drive, DiskTestMode.QUICK, benchmark=bench)
    assert bench.calls[0][2] is False
    drive.bus_type = "SATA"
    run_disk_test(FakePowerShell({}), drive, DiskTestMode.QUICK, benchmark=bench)
    assert bench.calls[1][2] is True


# --- isolated benchmark ----------------------------------------------------------------------


def hanging_bench(progress, cancel, sizes, folder, write_through=True):
    """Child-process target that reports once, then blocks like a stuck disk."""
    import time as _time
    from pathlib import Path as _Path

    (_Path(folder) / "extract-bench-stuck.tmp").write_bytes(b"x")
    progress(0.1, "Disco: gravação sequencial")
    _time.sleep(600)


def quick_bench(progress, cancel, sizes, folder, write_through=True):
    from extract.core.models import BenchmarkResult, Category

    progress(0.5, "meio")
    return [
        BenchmarkResult(
            "storage.sequential",
            Category.STORAGE,
            "seq",
            {"read_mb_s": Metric(123.0, "MB/s", "x"), "uncached": Metric(1.0, "", "")},
        )
    ]


def test_isolated_benchmark_returns_child_results(tmp_path):
    from extract.disktest.isolated import run_disk_isolated

    seen = []
    results = run_disk_isolated(
        lambda f, m: seen.append(m), CancelToken(), runner.disk_bench.QUICK, str(tmp_path),
        target="test_disktest.quick_bench",
    )  # fmt: skip
    assert results[0].metrics["read_mb_s"].value == 123.0
    assert seen == ["meio"]


def test_isolated_benchmark_stops_a_stuck_disk_and_cleans_up(tmp_path):
    from extract.disktest.isolated import run_disk_isolated

    results = run_disk_isolated(
        lambda f, m: None, CancelToken(), runner.disk_bench.QUICK, str(tmp_path),
        stall_timeout_s=2, target="test_disktest.hanging_bench",
    )  # fmt: skip
    assert all("não respondeu por 2 s" in r.error for r in results)
    assert not list(tmp_path.glob("extract-bench-*.tmp"))


def test_isolated_benchmark_cancel_is_immediate(tmp_path):
    import threading
    import time as _time

    from extract.disktest.isolated import run_disk_isolated

    token = CancelToken()
    threading.Timer(1.5, token.cancel).start()
    began = _time.monotonic()
    with pytest.raises(Cancelled):
        run_disk_isolated(
            lambda f, m: None, token, runner.disk_bench.QUICK, str(tmp_path),
            target="test_disktest.hanging_bench",
        )  # fmt: skip
    assert _time.monotonic() - began < 10
    assert not list(tmp_path.glob("extract-bench-*.tmp"))


def test_isolated_benchmark_real_run(tmp_path):
    from extract.disktest.isolated import run_disk_isolated

    results = run_disk_isolated(
        lambda f, m: None, CancelToken(), runner.disk_bench.QUICK, str(tmp_path)
    )
    assert [r.id for r in results] == ["storage.sequential", "storage.random"]
    assert results[0].ok and results[1].metrics["read_p99_ms"].value >= 0


# --- USB drives: wear and SMART through the bridge -------------------------------------------

SSD_LIFE_SMART = smart.encode_attributes(
    [(9, 100, 100, 6520), (12, 99, 99, 310), (194, 67, 62, 33), (231, 72, 72, 72)]
)


def usb_ssd() -> DriveEntry:
    drive = probe.parse_drive(DRIVE_ROWS[1])
    drive.bus_type, drive.media_type, drive.model = "USB", "SSD", "INFOKIT USB 3.0"
    return drive


def test_usb_wear_zero_without_smart_is_unknown():
    ps = FakePowerShell(
        {
            "IsInRole": [{"IsAdmin": False, "Host": "PC"}],
            "Get-StorageReliabilityCounter": [{"Temperature": 32, "Wear": 0}],
        }
    )
    result = run_disk_test(ps, usb_ssd(), DiskTestMode.HEALTH)
    keys = {r.key: r for r in result.readings}
    assert "wear" not in keys
    assert keys["usb_smart"].status is Status.UNKNOWN
    assert "administrador" in keys["usb_smart"].note


def test_usb_smart_through_bridge_gives_ssd_life():
    ps = FakePowerShell(
        {
            "IsInRole": [{"IsAdmin": True, "Host": "PC"}],
            "Get-StorageReliabilityCounter": [{"Temperature": 32, "Wear": 0}],
        }
    )
    calls = []

    def reader(number):
        calls.append(number)
        return SSD_LIFE_SMART, []

    result = run_disk_test(ps, usb_ssd(), DiskTestMode.HEALTH, sat_reader=reader)
    keys = {r.key: r for r in result.readings}
    assert calls == [0]
    assert keys["wear"].value == "28% (restam 72%)"
    assert keys["power_on_hours"].value == "6.520 h"
    assert "usb_smart" not in keys
    assert {a.id for a in result.smart} == {9, 12, 194, 231}


def test_bridge_reader_not_called_without_admin_or_for_sata():
    calls = []
    reader = lambda n: calls.append(n)  # noqa: E731
    ps = FakePowerShell({"IsInRole": [{"IsAdmin": False, "Host": "PC"}]})
    run_disk_test(ps, usb_ssd(), DiskTestMode.HEALTH, sat_reader=reader)
    ps = FakePowerShell({"IsInRole": [{"IsAdmin": True, "Host": "PC"}]})
    run_disk_test(ps, probe.parse_drive(DRIVE_ROWS[0]), DiskTestMode.HEALTH, sat_reader=reader)
    assert calls == []


def test_sat_cdb_is_ata_pass_through_16_smart_read():
    from extract.disktest import sat

    cdb = sat.sat_cdb(sat.SMART_READ_DATA)
    assert len(cdb) == 16 and cdb[0] == 0x85 and cdb[4] == 0xD0
    assert (cdb[10], cdb[12], cdb[14]) == (0x4F, 0xC2, 0xB0)


def fake_sat_ok(number):
    return SSD_LIFE_SMART, [0] * 362


def fake_sat_hang(number):
    import time as _time

    _time.sleep(600)


def test_sat_reader_child_process_result_and_timeout():
    from extract.disktest import sat

    data, _thresholds = sat.read_sat_smart(1, target="test_disktest.fake_sat_ok")
    assert data == SSD_LIFE_SMART
    assert sat.read_sat_smart(1, timeout_s=2, target="test_disktest.fake_sat_hang") is None


# --- reliability: health percent, USB speed, setup items -------------------------------------


def test_usb_ssd_health_matches_hard_disk_sentinel():
    """Real case: Kingston 240 GB on a USB bridge; Hard Disk Sentinel showed 72% and 6520 h."""
    from extract.disktest import summary

    ps = FakePowerShell({"IsInRole": [{"IsAdmin": True, "Host": "PC"}]})
    bench = fake_bench(
        {"read_mb_s": Metric(22, "MB/s", ""), "write_mb_s": Metric(20, "MB/s", ""),
         "read_iops": Metric(900, "IOPS", "")}
    )  # fmt: skip
    result = run_disk_test(
        ps,
        usb_ssd(),
        DiskTestMode.QUICK,
        benchmark=bench,
        sat_reader=lambda n: (SSD_LIFE_SMART, []),
    )
    assert result.health_percent == 72 and result.life_left == 72
    assert result.power_on_hours == 6520
    # USB speed is the link's: no "slow disk" alert and it does not pull the score down.
    assert result.performance_status is Status.UNKNOWN
    assert result.health_status is Status.OK
    assert "conexão USB" in result.verdict
    assert any("USB 3" in tip for tip in result.recommendations)
    view = summary.build(result)
    assert view.situation == "Bom" and "28%" in view.headline
    assert [f.value for f in view.facts][:3] == ["72%", "72%", "6.520 h"]
    assert "pelo USB (nível de USB 2.0)" in view.speed and "não do disco" in view.speed
    assert report.expected_text(result, "read_mb_s") == "pelo USB: não avaliado"


def test_setup_items_never_lower_health():
    drive = probe.parse_drive(DRIVE_ROWS[1])
    drive.bus_type, drive.media_type = "SATA", "SSD"
    drive.volumes[0].free_gb = 1.0  # almost full
    ps = FakePowerShell(
        {
            "Get-StorageReliabilityCounter": [{"Wear": 5, "PowerOnHours": 100}],
            "DisableDeleteNotify": [{"Output": "NTFS DisableDeleteNotify = 1"}],
        }
    )
    result = run_disk_test(ps, drive, DiskTestMode.HEALTH)
    groups = {r.key: r.group for r in result.readings}
    assert groups["trim"] == "care" and groups["free_C:"] == "care"
    assert result.health_status is Status.OK and result.health_percent == 95
    from extract.disktest import summary

    view = summary.build(result)
    assert view.situation == "Bom" and len(view.cares) == 2


def test_bad_sectors_lower_health_percent_and_summary():
    from extract.disktest import summary

    drive = probe.parse_drive(DRIVE_ROWS[0])
    result = run_disk_test(hdd_ps(), drive, DiskTestMode.HEALTH, drive_count=2)
    assert result.health_percent is not None and result.health_percent < 100
    view = summary.build(result)
    assert view.situation in ("Atenção", "Substituir")
    assert any("Setores defeituosos" in reason for reason in view.reasons)


def test_health_percent_unknown_without_any_reading():
    result = evaluate.finish(DiskTestReport())
    assert result.health_percent is None
    from extract.disktest import summary

    assert summary.build(result).situation == "Sem dados"


def test_time_powered_text():
    from extract.disktest.summary import time_powered

    assert time_powered(6520) == "cerca de 9 meses"
    assert time_powered(48) == "cerca de 2 dias"
    assert time_powered(40000) == "cerca de 4,6 anos"
