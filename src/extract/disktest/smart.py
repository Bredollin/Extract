"""Raw ATA SMART attributes, decoded from the bytes Windows exposes through WMI.

`MSStorageDriver_FailurePredictData.VendorSpecific` (namespace `root\\wmi`, admin only) is the
512-byte SMART data block of ATA/SATA drives: a 2-byte revision followed by 30 entries of
12 bytes each (id, 2 flag bytes, current value, worst value, 6 raw bytes, 1 reserved byte).
`MSStorageDriver_FailurePredictThresholds.VendorSpecific` has the same layout, with the
threshold in the byte after the id. NVMe drives do not use this format; their health comes
from `Get-StorageReliabilityCounter` instead.

How to read an attribute: `current` and `worst` are normalized (usually 100 or 200 when new,
going down); the drive itself considers the attribute failed when `current <= threshold`.
The `raw` value is a counter whose meaning depends on the attribute (sectors, hours, ...).
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass

from extract.core.models import Status

ENTRY_SIZE = 12
ENTRY_COUNT = 30
HEADER_SIZE = 2

# Attribute names in Portuguese (the most common ones; vendors add their own).
ATTRIBUTE_NAMES = {
    1: "Taxa de erros de leitura",
    3: "Tempo para girar o disco",
    4: "Partidas e paradas do motor",
    5: "Setores realocados",
    7: "Taxa de erros de posicionamento",
    9: "Horas ligado",
    10: "Tentativas de girar o disco",
    12: "Ciclos de liga/desliga",
    170: "Blocos reservas disponíveis",
    171: "Falhas de programação",
    172: "Falhas de apagamento",
    173: "Contagem de desgaste",
    174: "Desligamentos inesperados",
    177: "Nivelamento de desgaste",
    179: "Blocos reservas usados",
    181: "Falhas de programação",
    182: "Falhas de apagamento",
    183: "Erros de SATA (downshift)",
    184: "Erros de ponta a ponta",
    187: "Erros não corrigidos",
    188: "Timeouts de comando",
    189: "Gravações com cabeça alta",
    190: "Temperatura do ar",
    191: "Impactos (G-sense)",
    192: "Desligamentos de emergência",
    193: "Ciclos de carga da cabeça",
    194: "Temperatura",
    195: "Correções por ECC",
    196: "Eventos de realocação",
    197: "Setores pendentes",
    198: "Setores incorrigíveis",
    199: "Erros de CRC (cabo/conector)",
    200: "Erros de gravação",
    202: "Vida útil usada",
    231: "Vida útil restante",
    232: "Reserva disponível",
    233: "Indicador de desgaste da mídia",
    235: "Desligamentos inesperados",
    241: "Total gravado (LBAs)",
    242: "Total lido (LBAs)",
}

# Raw counters that should stay at zero on a healthy drive: (warning from, critical from).
# 5/196/197/198 are bad or unstable sectors (data at risk); 187 errors the drive could not
# fix; 184 corrupted data between cache and media; 10 the motor struggling to spin.
BAD_SECTOR_LIMITS = {
    5: (1, 50),
    10: (1, 10),
    184: (1, 1),
    187: (1, 20),
    196: (1, 50),
    197: (1, 10),
    198: (1, 10),
}
# CRC errors point at the SATA cable or port, not at the drive: never critical on their own.
CRC_ATTRIBUTE = 199
CRC_WARNING = 50

TEMPERATURE_ATTRIBUTES = (194, 190)
POWER_ON_HOURS = 9
POWER_CYCLES = 12
UNSAFE_SHUTDOWNS = (192, 174, 235)
# Normalized value of these is "percent of life left" on most SSDs.
SSD_LIFE_ATTRIBUTES = (231, 233, 177, 202, 173)


@dataclass
class SmartAttribute:
    id: int
    name: str
    current: int
    worst: int
    threshold: int | None
    raw: int
    status: Status = Status.OK
    note: str = ""

    @property
    def raw_display(self) -> str:
        """Raw value as people expect it (temperature is only the low byte)."""
        if self.id in TEMPERATURE_ATTRIBUTES:
            return f"{self.raw & 0xFF} °C"
        if self.id == POWER_ON_HOURS:
            return f"{self.raw & 0xFFFFFFFF} h"
        return str(self.raw)


def _as_bytes(data: Sequence[int] | bytes | None) -> bytes:
    if not data:
        return b""
    try:
        return bytes(int(b) & 0xFF for b in data)
    except (TypeError, ValueError):
        return b""


def parse_thresholds(data: Sequence[int] | bytes | None) -> dict[int, int]:
    raw = _as_bytes(data)
    thresholds: dict[int, int] = {}
    for index in range(ENTRY_COUNT):
        start = HEADER_SIZE + index * ENTRY_SIZE
        entry = raw[start : start + ENTRY_SIZE]
        if len(entry) < 2 or entry[0] == 0:
            continue
        thresholds[entry[0]] = entry[1]
    return thresholds


def parse_attributes(
    data: Sequence[int] | bytes | None, thresholds: dict[int, int] | None = None
) -> list[SmartAttribute]:
    """Decode the 30 attribute slots; empty slots (id 0) are skipped."""
    raw = _as_bytes(data)
    thresholds = thresholds or {}
    attributes: list[SmartAttribute] = []
    for index in range(ENTRY_COUNT):
        start = HEADER_SIZE + index * ENTRY_SIZE
        entry = raw[start : start + ENTRY_SIZE]
        if len(entry) < ENTRY_SIZE or entry[0] == 0:
            continue
        attribute_id = entry[0]
        attribute = SmartAttribute(
            id=attribute_id,
            name=ATTRIBUTE_NAMES.get(attribute_id, f"Atributo {attribute_id}"),
            current=entry[3],
            worst=entry[4],
            threshold=thresholds.get(attribute_id),
            raw=int.from_bytes(entry[5:11], "little"),
        )
        _judge(attribute)
        attributes.append(attribute)
    return attributes


def _judge(attribute: SmartAttribute) -> None:
    """Set `status` and `note` from the drive's own threshold and the known bad counters."""
    threshold = attribute.threshold
    if threshold and 0 < attribute.current <= threshold:
        attribute.status = Status.CRITICAL
        attribute.note = "abaixo do limite do fabricante (falha prevista)"
        return
    if attribute.id in BAD_SECTOR_LIMITS:
        warning, critical = BAD_SECTOR_LIMITS[attribute.id]
        if attribute.raw >= critical:
            attribute.status, attribute.note = Status.CRITICAL, "valor alto: dados em risco"
        elif attribute.raw >= warning:
            attribute.status, attribute.note = Status.WARNING, "deveria ser zero"
    elif attribute.id == CRC_ATTRIBUTE and attribute.raw >= CRC_WARNING:
        attribute.status, attribute.note = Status.WARNING, "verifique cabo SATA e porta"


def find(attributes: Sequence[SmartAttribute], *ids: int) -> SmartAttribute | None:
    """First attribute present among `ids`, in the given order of preference."""
    by_id = {a.id: a for a in attributes}
    for attribute_id in ids:
        if attribute_id in by_id:
            return by_id[attribute_id]
    return None


def encode_attributes(entries: Sequence[tuple[int, int, int, int]]) -> list[int]:
    """Build a VendorSpecific block from (id, current, worst, raw); used by tests and demos."""
    block = bytearray(HEADER_SIZE + ENTRY_COUNT * ENTRY_SIZE)
    block[0] = 0x10
    for index, (attribute_id, current, worst, raw) in enumerate(entries[:ENTRY_COUNT]):
        start = HEADER_SIZE + index * ENTRY_SIZE
        block[start] = attribute_id
        block[start + 3] = current
        block[start + 4] = worst
        block[start + 5 : start + 11] = raw.to_bytes(6, "little")
    return list(block)


def encode_thresholds(entries: Sequence[tuple[int, int]]) -> list[int]:
    block = bytearray(HEADER_SIZE + ENTRY_COUNT * ENTRY_SIZE)
    for index, (attribute_id, threshold) in enumerate(entries[:ENTRY_COUNT]):
        start = HEADER_SIZE + index * ENTRY_SIZE
        block[start] = attribute_id
        block[start + 1] = threshold
    return list(block)
