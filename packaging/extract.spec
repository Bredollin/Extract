# PyInstaller spec for the single-file, windowed Extract.exe.
# Build from the repository root:  pyinstaller packaging/extract.spec --noconfirm
# Output: dist/Extract.exe (build on Windows: the version resource needs its win32 helpers).
#
# The exe is unsigned and runs from USB sticks on client machines, so it avoids anything
# that makes SmartScreen and antivirus heuristics suspicious: no UPX packing, no
# obfuscation, no admin manifest, and a complete Windows version resource.

import re
import sys
from pathlib import Path

from PyInstaller.utils.win32.versioninfo import (
    FixedFileInfo,
    StringFileInfo,
    StringStruct,
    StringTable,
    VarFileInfo,
    VarStruct,
    VSVersionInfo,
)

ROOT = Path(SPECPATH).resolve().parent
SRC = ROOT / "src"
ASSETS = SRC / "extract" / "gui" / "assets"
ICON = ASSETS / "icon.ico"

sys.path.insert(0, str(SRC))
from extract import __version__  # noqa: E402

_numbers = [int(n) for n in re.findall(r"\d+", __version__)[:4]]
VERSION_TUPLE = tuple(_numbers + [0] * (4 - len(_numbers)))
VERSION_TEXT = ".".join(str(n) for n in VERSION_TUPLE)

# 0x0416 = Portuguese (Brazil), 1200 = Unicode code page.
version_info = VSVersionInfo(
    ffi=FixedFileInfo(filevers=VERSION_TUPLE, prodvers=VERSION_TUPLE),
    kids=[
        StringFileInfo(
            [
                StringTable(
                    "041604B0",
                    [
                        StringStruct("CompanyName", "Michael Bredollin"),
                        StringStruct("FileDescription", "Diagnóstico de hardware e desempenho"),
                        StringStruct("FileVersion", VERSION_TEXT),
                        StringStruct("InternalName", "Extract"),
                        StringStruct("LegalCopyright", "© Michael Bredollin. Licença GPL-3.0."),
                        StringStruct("OriginalFilename", "Extract.exe"),
                        StringStruct("ProductName", "Extract"),
                        StringStruct("ProductVersion", __version__),
                    ],
                )
            ]
        ),
        VarFileInfo([VarStruct("Translation", [0x0416, 1200])]),
    ],
)

# Qt modules Extract never uses (the GUI needs only QtCore, QtGui, QtWidgets and QtSvg).
QT_EXCLUDES = [
    f"PySide6.{name}"
    for name in (
        "Qt3DAnimation",
        "Qt3DCore",
        "Qt3DExtras",
        "Qt3DInput",
        "Qt3DLogic",
        "Qt3DRender",
        "QtBluetooth",
        "QtCharts",
        "QtConcurrent",
        "QtDataVisualization",
        "QtDesigner",
        "QtGraphs",
        "QtHelp",
        "QtHttpServer",
        "QtLocation",
        "QtMultimedia",
        "QtMultimediaWidgets",
        "QtNetworkAuth",
        "QtNfc",
        "QtOpenGL",
        "QtOpenGLWidgets",
        "QtPdf",
        "QtPdfWidgets",
        "QtPositioning",
        "QtQml",
        "QtQuick",
        "QtQuick3D",
        "QtQuickControls2",
        "QtQuickWidgets",
        "QtRemoteObjects",
        "QtScxml",
        "QtSensors",
        "QtSerialBus",
        "QtSerialPort",
        "QtSpatialAudio",
        "QtSql",
        "QtStateMachine",
        "QtTest",
        "QtTextToSpeech",
        "QtUiTools",
        "QtWebChannel",
        "QtWebEngineCore",
        "QtWebEngineQuick",
        "QtWebEngineWidgets",
        "QtWebSockets",
        "QtXml",
    )
]

a = Analysis(
    [str(Path(SPECPATH) / "launcher.py")],
    pathex=[str(SRC)],
    datas=[(str(ASSETS), "extract/gui/assets")] if ASSETS.is_dir() else [],
    hiddenimports=[],
    excludes=[*QT_EXCLUDES, "tkinter", "unittest", "pytest"],
    noarchive=False,
)
pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.datas,
    [],
    name="Extract",
    console=False,
    upx=False,
    uac_admin=False,
    strip=False,
    version=version_info,
    icon=str(ICON) if ICON.exists() else None,
)
