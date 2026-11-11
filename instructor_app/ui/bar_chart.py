"""Basit yatay çubuk grafik (QPainter ile çizilir). (Sahibi: D)

Kullanım:
    chart = BarChart()
    chart.set_bars([Bar("Soru 1", 0.8, "%80", "#16a34a"), Bar("Soru 2", 0.3, "%30", "#dc2626")])

Her satır:  [etiket]  [██████████░░░░░░]  [değer yazısı]
value 0 ile 1 arasında bir orandır; çubuğun ne kadar dolacağını belirler.
"""

from dataclasses import dataclass

from PySide6.QtCore import QRectF, QSize, Qt
from PySide6.QtGui import QColor, QPainter, QPaintEvent
from PySide6.QtWidgets import QWidget

from shared.theme import MUTED, TEXT

TRACK_COLOR = "#eef1f6"  # çubuğun boş kısmı


@dataclass
class Bar:
    label: str
    value: float   # 0..1
    text: str      # çubuğun sağına yazılır (ör. "%75")
    color: str


class BarChart(QWidget):
    ROW_HEIGHT = 30
    LABEL_WIDTH = 130
    TEXT_WIDTH = 80
    PADDING = 10

    def __init__(self, empty_text: str = "Gösterilecek veri yok", parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.bars: list[Bar] = []
        self.empty_text = empty_text
        self.setMinimumWidth(self.LABEL_WIDTH + self.TEXT_WIDTH + 120)

    def set_bars(self, bars: list[Bar]) -> None:
        self.bars = bars
        # Yükseklik satır sayısına göre; çok soru varsa grafik kaydırma alanında kayar
        self.setMinimumHeight(self._content_height())
        self.updateGeometry()
        self.update()  # yeniden çiz (paintEvent)

    def _content_height(self) -> int:
        rows = max(len(self.bars), 1)
        return rows * self.ROW_HEIGHT + 2 * self.PADDING

    def sizeHint(self) -> QSize:
        return QSize(500, self._content_height())

    def paintEvent(self, event: QPaintEvent) -> None:
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        if not self.bars:
            painter.setPen(QColor(MUTED))
            painter.drawText(self.rect(), Qt.AlignmentFlag.AlignCenter, self.empty_text)
            return
        bar_width = self.width() - self.LABEL_WIDTH - self.TEXT_WIDTH - 2 * self.PADDING
        for row, bar in enumerate(self.bars):
            top = self.PADDING + row * self.ROW_HEIGHT
            self._draw_label(painter, bar.label, top)
            self._draw_bar(painter, bar, top, max(bar_width, 10))

    def _draw_label(self, painter: QPainter, label: str, top: float) -> None:
        rect = QRectF(self.PADDING, top, self.LABEL_WIDTH - 10, self.ROW_HEIGHT)
        # Uzun etiket sığmazsa sonu "…" ile kısaltılır
        text = painter.fontMetrics().elidedText(label, Qt.TextElideMode.ElideRight, int(rect.width()))
        painter.setPen(QColor(TEXT))
        painter.drawText(rect, Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignRight, text)

    def _draw_bar(self, painter: QPainter, bar: Bar, top: float, width: float) -> None:
        left = self.PADDING + self.LABEL_WIDTH
        height = self.ROW_HEIGHT - 12
        value = min(max(bar.value, 0.0), 1.0)

        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QColor(TRACK_COLOR))
        painter.drawRoundedRect(QRectF(left, top + 6, width, height), 4, 4)
        if value > 0:
            painter.setBrush(QColor(bar.color))
            painter.drawRoundedRect(QRectF(left, top + 6, width * value, height), 4, 4)

        painter.setPen(QColor(MUTED))
        text_rect = QRectF(left + width + 8, top, self.TEXT_WIDTH - 8, self.ROW_HEIGHT)
        painter.drawText(text_rect, Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft, bar.text)
