"""Yazı boyutu büyüt / küçült (Ctrl + / Ctrl - / Ctrl 0). (Sahibi: C)

Tema yazı boyutlarını "font-size: 14px" gibi stil sayfasında tanımlıyor. Büyütmek için
stil sayfasındaki her px değerini bir oranla çarpıp uygulamaya yeniden veriyoruz.
"""

import re

from PySide6.QtWidgets import QApplication

_FONT_SIZE = re.compile(r"font-size:\s*(\d+)px")
MIN_SCALE = 0.7
MAX_SCALE = 2.0
STEP = 0.1


def scale_font_sizes(css: str, scale: float) -> str:
    """Stil sayfasındaki tüm font-size px değerlerini scale ile çarpar."""
    return _FONT_SIZE.sub(lambda m: f"font-size: {round(int(m.group(1)) * scale)}px", css)


class FontZoom:
    def __init__(self, app: QApplication, base_css: str) -> None:
        self._app = app
        self._base_css = base_css
        self.scale = 1.0
        self._apply()

    def zoom_in(self) -> None:
        self._set(self.scale + STEP)

    def zoom_out(self) -> None:
        self._set(self.scale - STEP)

    def reset(self) -> None:
        self._set(1.0)

    def _set(self, scale: float) -> None:
        self.scale = round(min(MAX_SCALE, max(MIN_SCALE, scale)), 2)
        self._apply()

    def _apply(self) -> None:
        self._app.setStyleSheet(scale_font_sizes(self._base_css, self.scale))
