"""Read ATA SMART data through a USB bridge (SCSI/ATA Translation, "SAT passthrough").

Windows' WMI SMART classes only cover drives on a native ATA/SATA port. Behind a USB
adapter the drive is a SCSI device, so tools such as Hard Disk Sentinel send the ATA
command wrapped in the SCSI "ATA PASS-THROUGH (16)" CDB (opcode 0x85). Most USB-SATA
bridges (JMicron, ASMedia, Realtek, VIA) support it; some cheap ones do not, and then
nothing is returned.

The query is read-only (SMART READ DATA / READ THRESHOLDS) and needs admin rights to open
`\\\\.\\PhysicalDriveN`. It runs in a child process with a timeout, since a misbehaving
bridge can block a DeviceIoControl call indefinitely.
"""

from __future__ import annotations

import ctypes
import logging
import multiprocessing
import queue as queue_module
import sys

log = logging.getLogger(__name__)

SECTOR = 512
TIMEOUT_S = 15.0

IOCTL_SCSI_PASS_THROUGH = 0x0004D004
SCSI_IOCTL_DATA_IN = 1
SMART_READ_DATA = 0xD0
SMART_READ_THRESHOLDS = 0xD1
ATA_SMART = 0xB0


class _ScsiPassThrough(ctypes.Structure):
    _fields_ = [
        ("Length", ctypes.c_ushort),
        ("ScsiStatus", ctypes.c_ubyte),
        ("PathId", ctypes.c_ubyte),
        ("TargetId", ctypes.c_ubyte),
        ("Lun", ctypes.c_ubyte),
        ("CdbLength", ctypes.c_ubyte),
        ("SenseInfoLength", ctypes.c_ubyte),
        ("DataIn", ctypes.c_ubyte),
        ("DataTransferLength", ctypes.c_uint32),
        ("TimeOutValue", ctypes.c_uint32),
        ("DataBufferOffset", ctypes.c_size_t),
        ("SenseInfoOffset", ctypes.c_uint32),
        ("Cdb", ctypes.c_ubyte * 16),
    ]


class _Request(ctypes.Structure):
    _fields_ = [
        ("spt", _ScsiPassThrough),
        ("filler", ctypes.c_uint32),
        ("sense", ctypes.c_ubyte * 32),
        ("data", ctypes.c_ubyte * SECTOR),
    ]


def sat_cdb(feature: int) -> bytes:
    """ATA PASS-THROUGH (16) for SMART `feature`: PIO data-in, one 512-byte block."""
    return bytes(
        [
            0x85,
            4 << 1,  # protocol 4 = PIO data-in
            0x0E,  # t_dir = in, byt_blok = blocks, t_length = sector count field
            0x00,
            feature,
            0x00,
            0x01,  # sector count
            0x00,
            0x00,  # LBA low
            0x00,
            0x4F,  # LBA mid: SMART signature
            0x00,
            0xC2,  # LBA high: SMART signature
            0x00,  # device
            ATA_SMART,
            0x00,
        ]
    )


def _read(handle, kernel32, feature: int) -> bytes:
    request = _Request()
    request.spt.Length = ctypes.sizeof(_ScsiPassThrough)
    request.spt.CdbLength = 16
    request.spt.SenseInfoLength = 32
    request.spt.DataIn = SCSI_IOCTL_DATA_IN
    request.spt.DataTransferLength = SECTOR
    request.spt.TimeOutValue = 5
    request.spt.SenseInfoOffset = _Request.sense.offset
    request.spt.DataBufferOffset = _Request.data.offset
    for index, byte in enumerate(sat_cdb(feature)):
        request.spt.Cdb[index] = byte
    returned = ctypes.c_uint32(0)
    ok = kernel32.DeviceIoControl(
        handle,
        IOCTL_SCSI_PASS_THROUGH,
        ctypes.byref(request),
        ctypes.sizeof(request),
        ctypes.byref(request),
        ctypes.sizeof(request),
        ctypes.byref(returned),
        None,
    )
    if not ok:
        raise OSError(ctypes.get_last_error(), "DeviceIoControl failed")
    if request.spt.ScsiStatus != 0:
        raise OSError(0, f"SCSI status {request.spt.ScsiStatus:#x}")
    return bytes(request.data)


def read_sat_smart_now(number: int) -> tuple[list[int], list[int]]:
    """(data, thresholds) as byte lists; raises OSError when the bridge refuses."""
    from ctypes import wintypes

    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)  # type: ignore[attr-defined]
    kernel32.CreateFileW.argtypes = [
        wintypes.LPCWSTR, wintypes.DWORD, wintypes.DWORD, ctypes.c_void_p,
        wintypes.DWORD, wintypes.DWORD, wintypes.HANDLE,
    ]  # fmt: skip
    kernel32.CreateFileW.restype = wintypes.HANDLE
    kernel32.DeviceIoControl.argtypes = [
        wintypes.HANDLE, wintypes.DWORD, ctypes.c_void_p, wintypes.DWORD,
        ctypes.c_void_p, wintypes.DWORD, ctypes.POINTER(ctypes.c_uint32), ctypes.c_void_p,
    ]  # fmt: skip
    kernel32.CloseHandle.argtypes = [wintypes.HANDLE]
    handle = kernel32.CreateFileW(
        f"\\\\.\\PhysicalDrive{int(number)}",
        0x80000000 | 0x40000000,  # GENERIC_READ | GENERIC_WRITE (required by the IOCTL)
        0x1 | 0x2,  # share read and write
        None,
        3,  # OPEN_EXISTING
        0,
        None,
    )
    if not handle or handle == ctypes.c_void_p(-1).value:
        raise OSError(ctypes.get_last_error(), "cannot open the physical drive (admin?)")
    try:
        data = _read(handle, kernel32, SMART_READ_DATA)
        try:
            thresholds = _read(handle, kernel32, SMART_READ_THRESHOLDS)
        except OSError:
            thresholds = b""
    finally:
        kernel32.CloseHandle(handle)
    if not any(data[2:14]):  # no attribute in the first slot: the bridge sent nothing real
        raise OSError(0, "bridge returned empty SMART data")
    return list(data), list(thresholds)


def _child(channel, number: int, target: str) -> None:
    module_name, _, name = target.rpartition(".")
    function = getattr(__import__(module_name, fromlist=[name]), name)
    try:
        channel.put(("ok", *function(number)))
    except BaseException as exc:
        channel.put(("error", f"{exc.__class__.__name__}: {exc}"))


def read_sat_smart(
    number: int,
    timeout_s: float = TIMEOUT_S,
    target: str = "extract.disktest.sat.read_sat_smart_now",
) -> tuple[list[int], list[int]] | None:
    """SMART data and thresholds through the USB bridge, or None (with a log line)."""
    if sys.platform != "win32" and target.endswith("read_sat_smart_now"):
        return None
    context = multiprocessing.get_context("spawn")
    channel = context.Queue()
    process = context.Process(
        target=_child, args=(channel, number, target), name="extract-sat", daemon=True
    )
    process.start()
    try:
        message = channel.get(timeout=timeout_s)
    except queue_module.Empty:
        log.warning("SAT SMART: no answer from disk %s in %.0f s", number, timeout_s)
        return None
    finally:
        if process.is_alive():
            process.terminate()
        process.join(5)
        channel.close()
    if message[0] != "ok":
        log.info("SAT SMART not available on disk %s: %s", number, message[1])
        return None
    return message[1], message[2]
