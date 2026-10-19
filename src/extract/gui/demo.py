"""Sample reports for `--demo`: try the interface and take screenshots without scanning.

The data is built directly with the models (not by running the analysis), so the demo
works on any OS. The main machine is a typical slow office PC: system on a hard disk,
4 GB of single-channel RAM, many startup programs and a couple of hardware errors.
"""

from __future__ import annotations

import tempfile
from dataclasses import replace
from pathlib import Path

from extract import __version__
from extract.core.models import (
    BenchmarkResult,
    Category,
    CpuInfo,
    DiskInfo,
    Finding,
    GpuInfo,
    HealthCheck,
    Inventory,
    MachineReport,
    MemoryInfo,
    MemoryModule,
    Metric,
    MotherboardInfo,
    NetworkAdapter,
    Severity,
    Status,
    SystemInfo,
    VolumeInfo,
)

DEMO_CLIENT = "Clinica Exemplo"
DEMO_LOG = [
    "10:41:58  INFO     Starting scan for client 'Clinica Exemplo'",
    "10:41:58  INFO     Collecting hardware inventory",
    "10:42:06  INFO     Running health checks",
    "10:42:21  INFO     Sampling disk activity for 5 s",
    "10:42:27  INFO     Running benchmarks: ['cpu', 'memory', 'storage']",
    "10:42:59  INFO     CPU single-core: 642 pts",
    "10:43:20  INFO     CPU multi-core: 2.214 pts (3,4x)",
    "10:43:31  INFO     Memory bandwidth: copy 6,1 GB/s",
    "10:43:33  INFO     Disk sequential test: writing 1.024 MB to C:\\",
]


def _inventory() -> Inventory:
    return Inventory(
        system=SystemInfo(
            hostname="RECEPCAO-01",
            user="recepcao",
            os_name="Windows 10 Pro",
            os_version="22H2",
            os_build="19045.4894",
            architecture="64 bits",
            manufacturer="Dell Inc.",
            model="OptiPlex 3050",
            serial_number="DEMO123",
            bios_version="1.24.0",
            boot_mode="UEFI",
            install_date="2018-03-12T09:15:00-03:00",
            last_boot="2026-09-27T08:02:00-03:00",
        ),
        cpu=CpuInfo(
            name="Intel(R) Core(TM) i5-7400 CPU @ 3.00GHz",
            manufacturer="GenuineIntel",
            cores=4,
            logical_processors=4,
            base_clock_mhz=3000,
            socket="LGA1151",
            l2_cache_kb=1024,
            l3_cache_kb=6144,
        ),
        memory=MemoryInfo(
            total_gb=4.0,
            total_slots=2,
            memory_type="DDR4",
            modules=[
                MemoryModule(
                    slot="DIMM1",
                    capacity_gb=4.0,
                    speed_mhz=2400,
                    configured_speed_mhz=2400,
                    manufacturer="SK Hynix",
                    part_number="HMA851U6AFR6N-UH",
                    memory_type="DDR4",
                )
            ],
        ),
        motherboard=MotherboardInfo(manufacturer="Dell Inc.", product="0JP3NX"),
        gpus=[GpuInfo(name="Intel HD Graphics 630", vram_mb=1024, driver_version="27.20.100.8681")],
        disks=[
            DiskInfo(
                model="ST500DM002-1BD142",
                size_gb=465.8,
                media_type="HDD",
                bus_type="SATA",
                health_status="Healthy",
                is_system_disk=True,
            )
        ],
        volumes=[
            VolumeInfo(letter="C:", label="Windows", filesystem="NTFS", size_gb=464.9, free_gb=38.2)
        ],
        network=[
            NetworkAdapter(
                name="Intel Ethernet I219-V",
                mac_address="00-00-5E-00-53-01",
                ipv4=["192.168.0.25"],
                gateway=["192.168.0.1"],
                dns_servers=["192.168.0.1"],
                dhcp=True,
                link_speed_mbps=1000,
            )
        ],
    )


def _health() -> list[HealthCheck]:
    def check(id_, category, title, status, summary, **data) -> HealthCheck:
        return HealthCheck(id_, category, title, status, summary, data)

    storage, memory, system = Category.STORAGE, Category.MEMORY, Category.SYSTEM
    return [
        check(
            "storage.activity", storage, "Atividade do disco", Status.CRITICAL,
            "Disco 100% ocupado, fila média de 4,2 e resposta de 186 ms.",
            busy_percent=100, avg_queue_length=4.2, avg_response_ms=186,
        ),
        check(
            "memory.pressure", memory, "Uso de memória", Status.CRITICAL,
            "91% da RAM em uso, 360 MB livres e 410 falhas de página por segundo.",
            used_percent=91, available_mb=360, commit_percent=118, hard_faults_per_s=410,
            pagefile_used_percent=64,
        ),
        check(
            "system.startup", system, "Programas na inicialização", Status.WARNING,
            "23 programas iniciam com o Windows.",
            count=23, items=[],
        ),
        check(
            "system.events", system, "Erros no log de eventos", Status.WARNING,
            "2 erros de hardware (WHEA) e 3 desligamentos inesperados nos últimos 30 dias.",
            window_days=30, disk_errors=0, whea_errors=2, unexpected_shutdowns=3, bugchecks=0,
            app_crashes=5,
        ),
        check(
            "storage.free_space", storage, "Espaço livre no disco", Status.WARNING,
            "C: com 38 GB livres (8%).",
            letter="C:", size_gb=464.9, free_gb=38.2, free_percent=8.2,
        ),
        check(
            "system.uptime", system, "Tempo ligado", Status.WARNING,
            "Ligado há 22 dias sem reiniciar.", days=22,
        ),
        check(
            "storage.health", storage, "Saúde do disco (SMART)", Status.OK,
            "HD saudável, 38 °C, 21.400 horas de uso.",
            disks=[{"model": "ST500DM002-1BD142", "media_type": "HDD", "health_status": "Healthy",
                    "temperature_c": 38, "wear_percent": None, "read_errors_total": 0,
                    "write_errors_total": 0, "power_on_hours": 21400}],
        ),
        check(
            "cpu.load", Category.CPU, "Uso do processador", Status.OK,
            "Carga média de 34%, clock em 3.400 MHz.",
            load_percent=34, current_clock_mhz=3400, max_clock_mhz=3500, top_processes=[],
        ),
        check(
            "system.power_plan", system, "Plano de energia", Status.OK,
            "Equilibrado, ligado na tomada.",
            plan_name="Equilibrado", is_power_saver=False, on_battery=False,
        ),
        check(
            "system.antivirus", system, "Antivírus", Status.OK,
            "Microsoft Defender ativo, nenhuma verificação em andamento.",
            products=["Microsoft Defender"], realtime_enabled=True, scan_in_progress=False,
        ),
        check(
            "network.connectivity", Category.NETWORK, "Conectividade", Status.OK,
            "Gateway em 1 ms, internet em 18 ms, sem perda de pacotes.",
            gateway_ms=1, gateway_loss_percent=0, internet_ms=18, internet_loss_percent=0,
            dns_ms=24,
        ),
        check(
            "system.pending_reboot", system, "Reinicialização pendente", Status.UNKNOWN,
            "Não foi possível verificar.", pending=None, reasons=[],
        ),
    ]  # fmt: skip


def _metric(value: float, unit: str, label: str) -> Metric:
    return Metric(value, unit, label)


def _benchmarks() -> list[BenchmarkResult]:
    return [
        BenchmarkResult(
            "cpu.single", Category.CPU, "Processador: um núcleo",
            {"score": _metric(642, "pts", "Pontuação"),
             "median_round_s": _metric(0.78, "s", "Tempo por rodada")},
            duration_s=12.4,
        ),
        BenchmarkResult(
            "cpu.multi", Category.CPU, "Processador: todos os núcleos",
            {"score": _metric(2214, "pts", "Pontuação"),
             "scaling": _metric(3.4, "x", "Ganho com vários núcleos"),
             "workers": _metric(4, "processos", "Processos")},
            duration_s=14.1,
        ),
        BenchmarkResult(
            "cpu.sustained", Category.CPU, "Processador: carga contínua",
            {"start_score": _metric(2230, "pts", "Pontuação no início"),
             "end_score": _metric(2105, "pts", "Pontuação no fim"),
             "throughput_drop_percent": _metric(5.6, "%", "Queda de desempenho")},
            duration_s=60.3,
        ),
        BenchmarkResult(
            "memory.bandwidth", Category.MEMORY, "Memória: velocidade",
            {"read_gb_s": _metric(8.4, "GB/s", "Leitura"),
             "write_gb_s": _metric(7.1, "GB/s", "Escrita"),
             "copy_gb_s": _metric(6.1, "GB/s", "Cópia"),
             "buffer_mb": _metric(256, "MB", "Tamanho do teste")},
            duration_s=8.7,
        ),
        BenchmarkResult(
            "storage.sequential", Category.STORAGE, "Disco: leitura e escrita sequencial",
            {"read_mb_s": _metric(118.6, "MB/s", "Leitura sequencial"),
             "write_mb_s": _metric(96.2, "MB/s", "Escrita sequencial"),
             "file_mb": _metric(1024, "MB", "Arquivo de teste"),
             "uncached": _metric(1, "", "Sem cache do Windows")},
            duration_s=21.5,
        ),
        BenchmarkResult(
            "storage.random", Category.STORAGE, "Disco: acesso aleatório (4 KB)",
            {"read_iops": _metric(74, "IOPS", "Leitura aleatória"),
             "write_iops": _metric(152, "IOPS", "Escrita aleatória"),
             "read_latency_ms": _metric(13.5, "ms", "Latência de leitura"),
             "write_latency_ms": _metric(6.6, "ms", "Latência de escrita"),
             "uncached": _metric(1, "", "Sem cache do Windows")},
            duration_s=18.9,
        ),
    ]  # fmt: skip


def _findings() -> list[Finding]:
    return [
        Finding(
            "verdict.upgrade", Category.SYSTEM, Severity.CRITICAL,
            "Vale a pena atualizar: trocar o HD por SSD e ampliar a memória",
            "O processador ainda dá conta do trabalho; a lentidão vem do disco e da falta de RAM.",
            "Instalar um SSD SATA de 240 GB ou mais e um segundo pente de 4 GB DDR4 2400 MHz "
            "(dual channel). Não é preciso trocar a máquina.",
        ),
        Finding(
            "storage.hdd_system", Category.STORAGE, Severity.CRITICAL,
            "Windows instalado em HD mecânico",
            "O disco do sistema é um HD de 7.200 rpm: 74 IOPS em leitura aleatória, contra "
            "cerca de 6.000 de um SSD. Durante o diagnóstico ele ficou 100% ocupado.",
            "Clonar o sistema para um SSD SATA ou NVMe. É a melhoria de maior impacto.",
        ),
        Finding(
            "memory.insufficient", Category.MEMORY, Severity.CRITICAL,
            "Memória RAM insuficiente para o uso atual",
            "Só 4 GB instalados, com 91% em uso e 410 falhas de página por segundo: o Windows "
            "usa o disco (que já é lento) como memória.",
            "Instalar mais 4 GB DDR4 2400 MHz no slot livre (total de 8 GB).",
        ),
        Finding(
            "memory.single_channel", Category.MEMORY, Severity.WARNING,
            "Memória em canal simples",
            "Há um único pente ocupando 1 de 2 slots, o que limita a velocidade da memória "
            "(cópia de 6,1 GB/s).",
            "Usar dois pentes iguais para ativar o dual channel.",
        ),
        Finding(
            "system.startup_heavy", Category.SYSTEM, Severity.WARNING,
            "Muitos programas na inicialização",
            "23 programas iniciam com o Windows e disputam o disco logo após ligar.",
            "Desativar no Gerenciador de Tarefas o que não for necessário (atualizadores, "
            "mensageiros, utilitários de impressora).",
        ),
        Finding(
            "system.whea_errors", Category.SYSTEM, Severity.WARNING,
            "Erros de hardware registrados (WHEA)",
            "2 eventos WHEA nos últimos 30 dias, além de 3 desligamentos inesperados.",
            "Acompanhar; se voltarem a ocorrer, testar a memória e verificar a fonte.",
        ),
        Finding(
            "storage.low_space", Category.STORAGE, Severity.WARNING,
            "Pouco espaço livre em C:",
            "Restam 38 GB (8%). Abaixo de 10% o Windows fragmenta mais e as atualizações falham.",
            "Limpar arquivos temporários e a pasta Downloads, ou aproveitar a troca por um "
            "SSD maior.",
        ),
        Finding(
            "system.uptime_long", Category.SYSTEM, Severity.INFO,
            "Máquina ligada há 22 dias",
            "Atualizações e vazamentos de memória se acumulam sem reiniciar.",
            "Orientar o usuário a reiniciar o computador pelo menos uma vez por semana.",
        ),
    ]  # fmt: skip


def build_demo_report() -> MachineReport:
    """The slow office PC used for screenshots."""
    return MachineReport(
        inventory=_inventory(),
        health=_health(),
        benchmarks=_benchmarks(),
        findings=_findings(),
        client=DEMO_CLIENT,
        created_at="2026-10-19T10:44:12-03:00",
        tool_version=__version__,
    )


def build_demo_fleet() -> list[MachineReport]:
    """The slow PC plus two more machines of the same client, for the Relatórios page."""
    slow = build_demo_report()

    healthy = build_demo_report()
    healthy.inventory.system = replace(
        healthy.inventory.system,
        hostname="FINANCEIRO-02",
        model="OptiPlex 7090",
        serial_number="DEMO456",
    )
    healthy.created_at = "2026-10-19T11:20:40-03:00"
    healthy.findings = [
        Finding(
            "verdict.ok", Category.SYSTEM, Severity.INFO, "Máquina saudável",
            "Nenhuma causa de lentidão encontrada.", "Nenhuma ação necessária.",
        )
    ]  # fmt: skip

    software = build_demo_report()
    software.inventory.system = replace(
        software.inventory.system, hostname="DIRETORIA-01", manufacturer="Lenovo",
        model="ThinkCentre M720q", serial_number="DEMO789",
    )  # fmt: skip
    software.created_at = "2026-10-19T09:05:13-03:00"
    software.findings = [
        Finding(
            "verdict.software", Category.SYSTEM, Severity.WARNING,
            "Problema de software, não de hardware",
            "Os testes de hardware estão normais.",
            "Revisar programas na inicialização e reiniciar a máquina.",
        ),
        _findings()[4],
    ]  # fmt: skip
    return [slow, healthy, software]


def save_demo_fleet(folder: Path) -> list[Path]:
    from extract.reports import save_report

    return [save_report(report, folder) for report in build_demo_fleet()]


def load_into(window) -> None:
    """Fill a `MainWindow` with the demo: reports saved to a temporary client folder."""
    temp = tempfile.TemporaryDirectory(prefix="extract-demo-")
    window._demo_dir = temp  # removed with the window
    folder = Path(temp.name) / DEMO_CLIENT.replace(" ", "-")
    paths = save_demo_fleet(folder)
    window.reports.refresh_clients(folder)
    window.diagnostic.setup.set_folder(folder)
    window.open_report(build_demo_report(), paths[0])


def show_scan_preview(window) -> None:
    """Freeze the Diagnóstico page in a mid-scan look (benchmarks running)."""
    window.diagnostic.show_preview(0.71, "Teste de disco: leitura sequencial", 95, DEMO_LOG)
