"""Regenerate `assets/icon.ico` from `assets/icon.svg`: `python -m extract.gui.icon_file`.

Qt's ICO writer stores a single image, so the multi-size file is assembled here from
PNG-encoded entries (supported by Windows Vista and later).
"""

from __future__ import annotations

import struct
import sys
from pathlib import Path

from PySide6.QtCore import QBuffer, QByteArray, QIODevice, Qt
from PySide6.QtGui import QGuiApplication, QImage, QPainter
from PySide6.QtSvg import QSvgRenderer

from extract.gui.icons import APP_ICON_ICO, APP_ICON_SVG

ICO_SIZES = (16, 20, 24, 32, 40, 48, 64, 128, 256)


def render_png(svg: Path, size: int) -> bytes:
    image = QImage(size, size, QImage.Format.Format_ARGB32_Premultiplied)
    image.fill(Qt.GlobalColor.transparent)
    painter = QPainter(image)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing)
    QSvgRenderer(str(svg)).render(painter)
    painter.end()
    data = QByteArray()
    buffer = QBuffer(data)
    buffer.open(QIODevice.OpenModeFlag.WriteOnly)
    image.save(buffer, "PNG")
    return bytes(data.data())


def write_ico(svg: Path, path: Path, sizes: tuple[int, ...] = ICO_SIZES) -> Path:
    images = [render_png(svg, size) for size in sizes]
    header = struct.pack("<HHH", 0, 1, len(images))
    offset = len(header) + 16 * len(images)
    entries, payload = b"", b""
    for size, png in zip(sizes, images, strict=True):
        dim = 0 if size >= 256 else size  # 0 means 256 in the ICO directory
        entries += struct.pack("<BBBBHHII", dim, dim, 0, 0, 1, 32, len(png), offset)
        payload += png
        offset += len(png)
    path.write_bytes(header + entries + payload)
    return path


def main() -> int:
    app = QGuiApplication.instance() or QGuiApplication(sys.argv)  # noqa: F841 - SVG rendering needs a Qt app
    write_ico(APP_ICON_SVG, APP_ICON_ICO)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
