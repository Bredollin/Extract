# ==============================================================================
# Script: extrac.py
# Módulo de Coleta Avançada e Modular com Logs em Tempo Real
# ==============================================================================

import os
import sys
import argparse
import platform
import subprocess
import json

def log_step(msg):
    """Imprime a mensagem imediatamente no terminal para captura em tempo real."""
    print(f"[EXTRAC] {msg}", flush=True)

def run_ps(cmd):
    """Executa comando PowerShell em JSON e retorna dicionário/lista."""
    ps_command = f"powershell -NoProfile -Command \"{cmd} | ConvertTo-Json -Depth 3\""
    try:
        res = subprocess.run(ps_command, capture_output=True, text=True, shell=True, encoding='utf-8', errors='ignore')
        if not res.stdout.strip():
            return []
        data = json.loads(res.stdout)
        return [data] if isinstance(data, dict) else data
    except Exception:
        return []

def collect_system():
    log_step("Coletando informações gerais do Sistema Operacional e Máquina...")
    os_info = run_ps("Get-CimInstance Win32_OperatingSystem")
    cs_info = run_ps("Get-CimInstance Win32_ComputerSystem")
    bb_info = run_ps("Get-CimInstance Win32_BIOS")
    
    os_data = os_info[0] if os_info else {}
    cs_data = cs_info[0] if cs_info else {}
    bb_data = bb_info[0] if bb_info else {}

    return {
        "Nome da Máquina": platform.node(),
        "Usuário Logado": cs_data.get("UserName", "N/A"),
        "Sistema Operacional": os_data.get("Caption", platform.system()),
        "Arquitetura": os_data.get("OSArchitecture", "N/A"),
        "Versão / Build": os_data.get("Version", "N/A"),
        "Fabricante da Maquina": cs_data.get("Manufacturer", "N/A"),
        "Modelo da Maquina": cs_data.get("Model", "N/A"),
        "Modo Boot / BIOS": bb_data.get("SMBIOSBIOSVersion", "N/A")
    }

def collect_cpu():
    log_step("Identificando Processador (CPU), núcleos e soquete...")
    cpu_info = run_ps("Get-CimInstance Win32_Processor")
    if not cpu_info:
        return {"Processador": platform.processor()}
    
    c = cpu_info[0]
    return {
        "Modelo CPU": c.get("Name", "").strip(),
        "Núcleos Físicos": c.get("NumberOfCores", "N/A"),
        "Processadores Lógicos": c.get("NumberOfLogicalProcessors", "N/A"),
        "Frequência Base": f"{c.get('MaxClockSpeed', 0)} MHz",
        "Soquete / Soquete": c.get("SocketDesignation", "N/A")
    }

def collect_motherboard():
    log_step("Coletando dados da Placa-Mãe e BIOS...")
    mb = run_ps("Get-CimInstance Win32_BaseBoard")
    mb_data = mb[0] if mb else {}
    return {
        "Fabricante Placa-Mãe": mb_data.get("Manufacturer", "N/A"),
        "Modelo Placa-Mãe": mb_data.get("Product", "N/A"),
        "Número de Série": mb_data.get("SerialNumber", "N/A")
    }

def collect_ram():
    log_step("Analisando Memória RAM (GB total, slots ocupados, frequência e geração DDR)...")
    ram_info = run_ps("Get-CimInstance Win32_PhysicalMemory")
    ram_array = run_ps("Get-CimInstance Win32_PhysicalMemoryArray")
    
    total_slots = ram_array[0].get("MemoryDevices", 2) if ram_array else 2
    total_bytes = sum([int(r.get("Capacity", 0)) for r in ram_info])
    total_gb = total_bytes // (1024**3)

    pentes = []
    freqs = []
    smbios_types = []

    for idx, r in enumerate(ram_info, 1):
        cap = int(r.get("Capacity", 0)) // (1024**3)
        spd = r.get("Speed", 0)
        mfg = r.get("Manufacturer", "Genérica").strip()
        part = r.get("PartNumber", "").strip()
        loc = r.get("DeviceLocator", f"Slot {idx}").strip()
        smbios_types.append(r.get("SMBIOSMemoryType", 0))
        freqs.append(spd)
        pentes.append(f"[{loc}] -> {cap} GB {mfg} ({spd} MHz) | Part: {part}")

    ddr = "DDR4"
    if 34 in smbios_types or any(f >= 4800 for f in freqs): ddr = "DDR5"
    elif 26 in smbios_types or any(f >= 2133 for f in freqs): ddr = "DDR4"
    elif 24 in smbios_types or any(f < 2133 for f in freqs if f > 0): ddr = "DDR3"

    return {
        "Total RAM": f"{total_gb} GB",
        "Geração": ddr,
        "Slots Totais / Ocupados": f"{total_slots} Slots ({len(ram_info)} Ocupados)",
        "Pentes Instalados": pentes
    }

def collect_disks():
    log_step("Varrendo unidades de Armazenamento (SSD NVMe, SATA e HDD)...")
    disks = run_ps("Get-CimInstance Win32_DiskDrive")
    disk_list = []
    for d in disks:
        mod = d.get("Model", "Desconhecido").strip()
        sz = int(d.get("Size", 0)) // (1024**3)
        media = "SSD NVMe" if "NVMe" in mod else ("SSD" if "SSD" in mod else "HDD / SSD")
        disk_list.append(f"• {mod} ({sz} GB) [{media}] - Interface: {d.get('InterfaceType', 'N/A')}")
    return {"Discos": disk_list if disk_list else ["N/A"]}

def collect_gpu():
    log_step("Verificando Placa de Vídeo e VRAM...")
    gpus = run_ps("Get-CimInstance Win32_VideoController")
    gpu_list = []
    for g in gpus:
        name = g.get("Name", "").strip()
        if name and "Virtual" not in name:
            ram_mb = int(g.get("AdapterRAM", 0)) // (1024**2) if g.get("AdapterRAM") else 0
            gpu_list.append(f"{name} ({ram_mb} MB VRAM)")
    return {"Placa de Vídeo": ", ".join(gpu_list) if gpu_list else "Vídeo Integrado"}

def collect_network():
    log_step("Mapeando Adaptadores de Rede, IPs ativos e Endereços MAC...")
    nets = run_ps("Get-CimInstance Win32_NetworkAdapterConfiguration")
    net_list = []
    for n in nets:
        if n.get("IPEnabled", False):
            desc = n.get("Description", "Adaptador")
            ips = n.get("IPAddress", [])
            ip = ips[0] if ips else "N/A"
            mac = n.get("MACAddress", "N/A")
            net_list.append(f"{desc}\n -> IP: {ip} | MAC: {mac}")
    return {"Redes": net_list if net_list else ["N/A"]}

def generate_report(options):
    log_step("Iniciando varredura modular de hardware...")
    
    report_lines = [
        "==================================================",
        "          RELATÓRIO DE HARDWARE - EXTRACT         ",
        "=================================================="
    ]

    sys_data = collect_system()
    report_lines.append(f"Nome da Maquina: {sys_data['Nome da Máquina']}")
    report_lines.append(f"Sistema Operacional: {sys_data['Sistema Operacional']} {sys_data['Arquitetura']}")
    report_lines.append(f"Usuário: {sys_data['Usuário Logado']}")
    report_lines.append(f"Modelo: {sys_data['Fabricante da Maquina']} - {sys_data['Modelo da Maquina']}")
    report_lines.append("")

    if options.get("all") or options.get("cpu"):
        report_lines.append("=== PROCESSADOR (CPU) ===")
        cpu = collect_cpu()
        for k, v in cpu.items(): report_lines.append(f"{k}: {v}")
        report_lines.append("")

    if options.get("all") or options.get("ram"):
        report_lines.append("=== MEMORIA RAM E SLOTS ===")
        ram = collect_ram()
        report_lines.append(f"Total de RAM Instalada: {ram['Total RAM']}")
        report_lines.append(f"Slots de Memoria: {ram['Slots Totais / Ocupados']}")
        report_lines.append(f"Geracao Detectada: {ram['Geração']}")
        report_lines.append("Pentes Instalados:")
        for p in ram["Pentes Instalados"]: report_lines.append(f"  {p}")
        report_lines.append("")

    if options.get("all") or options.get("mb"):
        report_lines.append("=== PLACA-MAE ===")
        mb = collect_motherboard()
        report_lines.append(f"Fabricante e Modelo: {mb['Fabricante Placa-Mãe']} {mb['Modelo Placa-Mãe']}")
        report_lines.append(f"Número de Série: {mb['Número de Série']}")
        report_lines.append("")

    if options.get("all") or options.get("gpu"):
        report_lines.append("=== PLACA DE VIDEO (GPU) ===")
        gpu = collect_gpu()
        report_lines.append(f"Nome / Modelo: {gpu['Placa de Vídeo']}")
        report_lines.append("")

    if options.get("all") or options.get("disk"):
        report_lines.append("=== ARMAZENAMENTO (DISCOS) ===")
        disks = collect_disks()
        for d in disks["Discos"]: report_lines.append(d)
        report_lines.append("")

    if options.get("all") or options.get("net"):
        report_lines.append("INFORMACOES DE REDE")
        report_lines.append("---------------------------------------------------")
        nets = collect_network()
        for n in nets["Redes"]: report_lines.append(f"Adaptador: {n}")

    report_lines.append("==================================================")

    log_step("Salvando relatório no arquivo local...")
    filename = f"{sys_data['Nome da Máquina']}-info.txt"
    filepath = os.path.join(os.getcwd(), filename)
    with open(filepath, "w", encoding="utf-8") as f:
        f.write("\n".join(report_lines))
    
    log_step(f"Relatório gerado com sucesso: {filename}")

if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--all", action="store_true")
    parser.add_argument("--cpu", action="store_true")
    parser.add_argument("--ram", action="store_true")
    parser.add_argument("--mb", action="store_true")
    parser.add_argument("--gpu", action="store_true")
    parser.add_argument("--disk", action="store_true")
    parser.add_argument("--net", action="store_true")
    
    args = parser.parse_args()
    opts = vars(args)
    
    if not any(opts.values()):
        opts["all"] = True

    generate_report(opts)