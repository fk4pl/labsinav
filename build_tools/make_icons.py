"""Uygulama ikonlarını üretir: python build_tools/make_icons.py

Basit bir ikon: yuvarlak köşeli kare üzerinde "LS" yazısı. Eğitmen mavi, öğrenci yeşil.
Çıktı build_tools/icons/*.ico repoda tutulur; bu betik sadece ikon değiştirilecekse çalıştırılır.

.ico dosyası birkaç boyutu (16, 32, 48, 256 piksel) bir arada tutar; Windows nerede
gösterecekse (görev çubuğu, masaüstü, dosya gezgini) uygun boyutu seçer.
Her boyut PNG olarak gömülür (Windows Vista'dan beri desteklenir).
"""

import os
import struct
import sys
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")  # pencere açmadan çizilebilsin

from PySide6.QtCore import QBuffer, QByteArray, QIODevice, QRectF, Qt  # noqa: E402
from PySide6.QtGui import QColor, QFont, QGuiApplication, QImage, QPainter  # noqa: E402

ICON_DIR = Path(__file__).resolve().parent / "icons"
SIZES = [16, 32, 48, 256]
ICONS = {
    "egitmen.ico": "#1d4ed8",  # mavi
    "ogrenci.ico": "#15803d",  # yeşil
}


def draw_icon(color: str, size: int) -> QImage:
    image = QImage(size, size, QImage.Format.Format_ARGB32)
    image.fill(Qt.GlobalColor.transparent)
    painter = QPainter(image)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing)
    painter.setPen(Qt.PenStyle.NoPen)
    painter.setBrush(QColor(color))
    margin = size / 32
    painter.drawRoundedRect(QRectF(margin, margin, size - 2 * margin, size - 2 * margin),
                            size / 5, size / 5)
    font = QFont()
    font.setPixelSize(int(size * 0.47))
    font.setBold(True)
    painter.setFont(font)
    painter.setPen(QColor("white"))
    painter.drawText(QRectF(0, 0, size, size), Qt.AlignmentFlag.AlignCenter, "LS")
    painter.end()
    return image


def png_bytes(image: QImage) -> bytes:
    data = QByteArray()
    buffer = QBuffer(data)
    buffer.open(QIODevice.OpenModeFlag.WriteOnly)
    image.save(buffer, "PNG")
    return bytes(data.data())


def write_ico(path: Path, images: list[bytes]) -> None:
    """ICO biçimi: 6 baytlık başlık + her resim için 16 baytlık kayıt + resim verileri."""
    header = struct.pack("<HHH", 0, 1, len(images))  # ayrılmış, tip=1 (ikon), resim sayısı
    offset = len(header) + 16 * len(images)
    entries, payload = b"", b""
    for size, data in zip(SIZES, images):
        side = 0 if size >= 256 else size  # 256 piksel 0 olarak yazılır
        entries += struct.pack("<BBBBHHII", side, side, 0, 0, 1, 32, len(data), offset)
        offset += len(data)
        payload += data
    path.write_bytes(header + entries + payload)


def main() -> int:
    _app = QGuiApplication(sys.argv)
    ICON_DIR.mkdir(exist_ok=True)
    for name, color in ICONS.items():
        path = ICON_DIR / name
        write_ico(path, [png_bytes(draw_icon(color, size)) for size in SIZES])
        print(f"Oluşturuldu: {path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
