"""Sınav bitti / gönderildi ekranı. (Sahibi: C)"""

from datetime import datetime

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QFrame, QLabel, QVBoxLayout, QWidget


def local_time_text(moment: datetime) -> str:
    """UTC zamanı bilgisayarın yerel saatine çevirip 'SS:DD' olarak yazar."""
    return moment.astimezone().strftime("%H:%M")


class FinishedPage(QWidget):
    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        card = QFrame()
        card.setObjectName("card")
        card.setMinimumWidth(520)
        layout = QVBoxLayout(card)
        layout.setContentsMargins(40, 40, 40, 40)
        layout.setSpacing(12)

        self.icon_label = QLabel("✓")
        self.icon_label.setObjectName("title")
        self.icon_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.title_label = QLabel()
        self.title_label.setObjectName("title")
        self.title_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.detail_label = QLabel()
        self.detail_label.setObjectName("subtitle")
        self.detail_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.detail_label.setWordWrap(True)

        layout.addWidget(self.icon_label)
        layout.addWidget(self.title_label)
        layout.addWidget(self.detail_label)

        outer = QVBoxLayout(self)
        outer.addWidget(card, alignment=Qt.AlignmentFlag.AlignCenter)

    def show_result(self, at: datetime, detail: str) -> None:
        self.title_label.setText(f"Sınavın gönderildi — {local_time_text(at)}")
        self.detail_label.setText(detail)
