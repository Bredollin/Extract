"""The verdict: one finding that sums up what the technician should do.

The logic is deliberately simple so it can be explained to a client. Only findings of
severity WARNING or above count, and the first matching case wins:

1. Very weak CPU, or weak CPU plus two or more parts to upgrade -> replace the machine.
2. A hardware fault (failing disk, hardware errors, overheating) -> fix that first.
3. Parts to upgrade (SSD, RAM) -> list them.
4. Only software or network problems -> "not a hardware problem".
5. Nothing -> no bottleneck found.
"""

from __future__ import annotations

from dataclasses import dataclass

from extract.analysis.rules import Role, fmt
from extract.core.models import Category, Finding, Severity


@dataclass(frozen=True)
class RatedFinding:
    finding: Finding
    role: Role


_SSD_FINDINGS = ("storage.system_hdd", "storage.behaves_like_hdd")
# Symptoms that an upgrade already explains, so they are not listed as separate fixes.
_EXPLAINED_BY_SSD = ("storage.busy",)


def _upgrade_parts(findings: list[Finding]) -> list[str]:
    by_id = {f.id: f for f in findings}
    parts: list[str] = []
    if any(i in by_id for i in _SSD_FINDINGS):
        parts.append("SSD")
    low_ram = by_id.get("memory.low_total")
    if low_ram:
        target = low_ram.evidence.get("recommended_total_gb")
        parts.append(f"{fmt(target)} GB de RAM" if target else "mais RAM")
    elif "memory.single_channel" in by_id:
        parts.append("segundo pente de memória (dual channel)")
    return parts


def _titles(findings: list[Finding]) -> str:
    return "; ".join(f.title.lower() for f in findings)


def build_verdict(rated: list[RatedFinding]) -> Finding:
    relevant = [r for r in rated if r.finding.severity.rank >= Severity.WARNING.rank]
    severity = max((r.finding.severity for r in rated), key=lambda s: s.rank, default=None)
    severity = severity or Severity.INFO

    def of(*roles: Role) -> list[Finding]:
        return [r.finding for r in relevant if r.role in roles]

    faults, replace = of(Role.FAULT), of(Role.REPLACE)
    software, network = of(Role.SOFTWARE), of(Role.NETWORK)
    parts = _upgrade_parts(of(Role.UPGRADE))
    evidence = {
        "faults": [f.id for f in faults],
        "upgrades": parts,
        "replace": [f.id for f in replace],
        "software": [f.id for f in software],
        "network": [f.id for f in network],
    }

    def verdict(id_: str, title: str, detail: str, recommendation: str) -> Finding:
        return Finding(
            f"verdict.{id_}", Category.SYSTEM, severity, title, detail, recommendation, evidence
        )

    cpu_very_weak = any(f.severity is Severity.CRITICAL for f in replace)
    if replace and (cpu_very_weak or len(parts) >= 2):
        needed = f" Além disso, precisaria de {' + '.join(parts)}." if parts else ""
        return verdict(
            "replace",
            "Troca da máquina é mais econômica",
            "O processador é o gargalo e não tem upgrade que resolva." + needed,
            "Orçar uma máquina nova (com SSD e ao menos 8 GB de RAM) e comparar com o custo "
            "dos upgrades; fazer backup dos dados.",
        )
    if faults:
        also = f" Depois, considerar: {' + '.join(parts)}." if parts else ""
        return verdict(
            "fault",
            "Problema de hardware: corrigir antes de qualquer upgrade",
            f"Encontrado: {_titles(faults)}.{also}",
            faults[0].recommendation,
        )
    if parts:
        if "SSD" in parts:
            software = [f for f in software if f.id not in _EXPLAINED_BY_SSD]
        others = software + network
        fix_too = f" Corrigir também: {_titles(others)}." if others else ""
        return verdict(
            "upgrade",
            f"Upgrade recomendado: {' + '.join(parts)}",
            "O hardware atual é o principal motivo da lentidão." + fix_too,
            "Fazer os upgrades indicados; são as mudanças com maior ganho para esta máquina.",
        )
    if software:
        net = f" Na rede: {_titles(network)}." if network else ""
        return verdict(
            "software",
            "Problema de software, não de hardware",
            f"O hardware dá conta; a lentidão vem de: {_titles(software)}.{net}",
            "Corrigir os itens apontados (sem custo de peças) e repetir o teste.",
        )
    if network:
        return verdict(
            "network",
            "Problema de rede, não do computador",
            f"A máquina está bem; o que falha é a conexão: {_titles(network)}.",
            "Resolver a rede (Wi-Fi, cabo, roteador ou provedor) antes de mexer no computador.",
        )
    return verdict(
        "ok",
        "Nenhum gargalo encontrado",
        "Nenhum item de atenção nos dados coletados.",
        "Se a queixa persistir, repetir o teste no momento em que a lentidão acontece e "
        "incluir os testes de desempenho.",
    )
